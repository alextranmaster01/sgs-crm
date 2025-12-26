import streamlit as st
import pandas as pd
import json
import io
import time
import numpy as np
import re
from datetime import datetime
from openpyxl import load_workbook
from utils import (supabase, load_data, clean_key, safe_str, fmt_float_1, search_file_in_drive_by_name, 
                   download_from_drive, to_float, strict_match_key, upload_to_drive_structured, fmt_num)

# =============================================================================
# LOCAL UTILS (Hàm xử lý nội bộ cho module Báo Giá)
# =============================================================================

def local_strict_match(val):
    """Hàm chuẩn hóa chuỗi để so sánh tuyệt đối: chữ thường, bỏ khoảng trắng"""
    if val is None: return ""
    s = str(val).lower()
    return re.sub(r'\s+', '', s)

def safe_float(val):
    """Chuyển đổi số an toàn, tránh lỗi NaN khi tính toán"""
    try:
        if val is None or val == "": return 0.0
        return float(val)
    except:
        return 0.0

def apply_formula_logic(df, formula_str, target_col):
    """Xử lý công thức linh hoạt kiểu Excel (BUY*1.1, AP*1.2...)"""
    if df.empty or not formula_str: return df
    
    # Chuẩn hóa công thức
    f_clean = str(formula_str).strip().upper()
    if f_clean.startswith("="): f_clean = f_clean[1:]
    
    # Validate ký tự an toàn
    allowed_chars = "0123456789.+-*/() BUYAP " # Cho phép từ khóa BUY, AP
    if not all(c in allowed_chars for c in f_clean):
        st.warning(f"Công thức chứa ký tự lạ: {formula_str}")
        return df

    for idx, row in df.iterrows():
        try:
            buy_val = safe_float(row.get("Buying price(VND)", 0))
            ap_val = safe_float(row.get("AP price(VND)", 0))
            
            # Thay thế biến
            expression = f_clean.replace("BUY", str(buy_val)).replace("AP", str(ap_val))
            
            # Tính toán
            result = eval(expression)
            df.at[idx, target_col] = result
        except Exception:
            pass # Bỏ qua dòng lỗi
            
    return df

def recalculate_all_columns(df):
    """Tính toán lại toàn bộ các cột phụ thuộc ngay lập tức"""
    if df.empty: return df
    
    # 1. Ép kiểu dữ liệu số cho tất cả cột tính toán
    numeric_cols = [
        "Q'ty", "Buying price(RMB)", "Exchange rate", "Buying price(VND)", 
        "AP price(VND)", "Unit price(VND)", "End user(%)", "Buyer(%)", 
        "Import tax(%)", "VAT", "Transportation", "Management fee(%)", "Payback(%)"
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = df[c].apply(safe_float)

    # 2. Tính toán Logic
    # RMB Total
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    
    # VND Total Buying
    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    
    # AP Total
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    
    # Sale Total
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    
    # GAP
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]
    
    # GAP Positive (để tính cost operation)
    gap_positive = df["GAP"].apply(lambda x: x * 0.6 if x > 0 else 0)
    
    # Tổng chi phí (Cost Ops)
    cost_ops = (gap_positive + 
                df["End user(%)"] + 
                df["Buyer(%)"] + 
                df["Import tax(%)"] + 
                df["VAT"] + 
                df["Management fee(%)"] + 
                df["Transportation"])
    
    # Profit = Doanh thu - Giá vốn - Chi phí + Payback
    df["Profit(VND)"] = df["Total price(VND)"] - df["Total buying price(VND)"] - cost_ops + df["Payback(%)"]
    
    # Profit %
    df["Profit_Pct_Raw"] = df.apply(lambda r: (r["Profit(VND)"] / r["Total price(VND)"] * 100) if r["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    
    # Cảnh báo
    def set_warning(row):
        if "KHÔNG KHỚP" in str(row.get("Cảnh báo", "")): return "⚠️ DATA KHÔNG KHỚP"
        return "⚠️ LOW" if row["Profit_Pct_Raw"] < 10 else "✅ OK"
    
    df["Cảnh báo"] = df.apply(set_warning, axis=1)
    
    return df

# =============================================================================
# MAIN RENDER FUNCTION
# =============================================================================

def render_quote():
    # Khởi tạo session state
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    if 'quote_editor_key' not in st.session_state: st.session_state.quote_editor_key = 0

    # ------------------ PHẦN 1: TRA CỨU LỊCH SỬ ------------------
    with st.expander("🔎 TRA CỨU & TRẠNG THÁI BÁO GIÁ", expanded=False):
        c_src1, c_src2 = st.columns(2)
        search_kw = c_src1.text_input("Nhập từ khóa (Tên Khách, Quote No, Code, Name, Date)", help="Tìm kiếm trong lịch sử")
        up_src = c_src2.file_uploader("Hoặc Import Excel kiểm tra", type=["xlsx"], key="src_up")
        
        if st.button("Kiểm tra trạng thái"):
            df_hist = load_data("crm_shared_history")
            df_po = load_data("db_customer_orders")
            
            po_map = {}
            if not df_po.empty:
                for r in df_po.to_dict('records'):
                    k = f"{clean_key(r.get('customer'))}_{clean_key(r.get('item_code'))}"
                    po_map[k] = r.get('po_number')

            results = []
            if search_kw and not df_hist.empty:
                mask = df_hist.astype(str).apply(lambda x: x.str.contains(search_kw, case=False)).any(axis=1)
                found = df_hist[mask]
                for _, r in found.iterrows():
                    key = f"{clean_key(r['customer'])}_{clean_key(r['item_code'])}"
                    results.append({
                        "Trạng thái": "✅ Đã báo giá", "Customer": r['customer'], "Date": r['date'],
                        "Item Code": r['item_code'], "Unit Price": fmt_float_1(r['unit_price']),
                        "Quote No": r['quote_no'], "PO No": po_map.get(key, "---")
                    })
            if results: st.dataframe(pd.DataFrame(results), use_container_width=True)
            else: st.info("Không tìm thấy kết quả.")

    st.divider()
    
    # ------------------ PHẦN 2: TÍNH TOÁN & LÀM BÁO GIÁ ------------------
    st.subheader("TÍNH TOÁN & LÀM BÁO GIÁ")
    
    # Header inputs
    c1, c2, c3 = st.columns([2, 2, 1])
    cust_db = load_data("crm_customers")
    cust_list = cust_db["short_name"].tolist() if not cust_db.empty else []
    cust_name = c1.selectbox("Chọn Khách Hàng", [""] + cust_list)
    quote_no = c2.text_input("Số Báo Giá", key="q_no")
    
    # Nút Reset
    c3.markdown('<div class="dark-btn">', unsafe_allow_html=True)
    if c3.button("🔄 Reset Quote"): 
        st.session_state.quote_df = pd.DataFrame()
        st.session_state.show_review = False
        st.session_state.quote_editor_key += 1 
        st.rerun()
    c3.markdown('</div>', unsafe_allow_html=True)

    # --- MATCHING (CHECK TUYỆT ĐỐI 3 TRƯỜNG) ---
    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        db = load_data("crm_purchases")
        
        if db.empty: 
            st.error("Kho rỗng! Vui lòng import kho trước.")
        else:
            db_records = db.to_dict('records')
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            
            # Map cột linh hoạt
            cols_found = {clean_key(c): c for c in df_rfq.columns}
            
            for i, r in df_rfq.iterrows():
                def get_val(keywords):
                    for k in keywords:
                        real_col = cols_found.get(k)
                        if real_col: return safe_str(r[real_col])
                    return ""

                code_excel = get_val(["item code", "code", "mã", "part number"])
                name_excel = get_val(["item name", "name", "tên", "description"])
                specs_excel = get_val(["specs", "quy cách", "thông số"])
                qty_raw = get_val(["q'ty", "qty", "quantity", "số lượng"])
                qty = safe_float(qty_raw) if qty_raw else 1.0

                # --- STRICT MATCHING LOGIC (Khớp cả 3 mới ra data) ---
                match = None
                warning_msg = ""
                
                candidates = [
                    rec for rec in db_records 
                    if local_strict_match(rec['item_code']) == local_strict_match(code_excel)
                    and local_strict_match(rec['item_name']) == local_strict_match(name_excel)
                    and local_strict_match(rec['specs']) == local_strict_match(specs_excel)
                ]

                if candidates:
                    match = candidates[0]
                    warning_msg = "✅ OK"
                else:
                    warning_msg = "⚠️ DATA KHÔNG KHỚP" # Cảnh báo nếu không khớp đủ 3

                # Gán dữ liệu
                if match:
                    buy_rmb = safe_float(match.get('buying_price_rmb', 0))
                    buy_vnd = safe_float(match.get('buying_price_vnd', 0))
                    ex_rate = safe_float(match.get('exchange_rate', 0))
                    supplier = match.get('supplier_name', '')
                    leadtime = match.get('leadtime', '')
                else:
                    # Nếu không khớp -> Trả về 0
                    buy_rmb = 0.0; buy_vnd = 0.0; ex_rate = 0.0
                    supplier = ""; leadtime = ""

                item = {
                    "Xóa": False, 
                    "No": i+1, 
                    "Cảnh báo": warning_msg, 
                    "Item code": code_excel, "Item name": name_excel, "Specs": specs_excel, 
                    "Q'ty": qty, 
                    "Buying price(RMB)": buy_rmb, 
                    "Total buying price(rmb)": 0.0, 
                    "Exchange rate": ex_rate, 
                    "Buying price(VND)": buy_vnd, 
                    "Total buying price(VND)": 0.0,
                    "AP price(VND)": 0.0, "AP total price(VND)": 0.0, 
                    "Unit price(VND)": 0.0, "Total price(VND)": 0.0,
                    "GAP": 0.0, "End user(%)": 0.0, "Buyer(%)": 0.0, 
                    "Import tax(%)": 0.0, "VAT": 0.0, "Transportation": 0.0,
                    "Management fee(%)": 0.0, "Payback(%)": 0.0, 
                    "Profit(VND)": 0.0, "Profit(%)": "0.0%",
                    "Supplier": supplier, "Leadtime": leadtime
                }
                res.append(item)
            
            temp_df = pd.DataFrame(res)
            st.session_state.quote_df = recalculate_all_columns(temp_df)
            st.session_state.quote_editor_key += 1
            st.rerun()

    # --- CÔNG CỤ: FORMULA & XÓA ---
    c_form1, c_form2, c_del = st.columns([2, 2, 1])
    
    with c_form1:
        ap_f = st.text_input("Formula AP (vd: =BUY*1.1)", key="f_ap", placeholder="Nhập: =BUY*1.1")
        if st.button("⚡ Apply AP Price"):
            if not st.session_state.quote_df.empty:
                st.session_state.quote_df = apply_formula_logic(st.session_state.quote_df, ap_f, "AP price(VND)")
                st.session_state.quote_df = recalculate_all_columns(st.session_state.quote_df)
                st.session_state.quote_editor_key += 1
                st.rerun()

    with c_form2:
        unit_f = st.text_input("Formula Unit (vd: =AP*1.2)", key="f_unit", placeholder="Nhập: =AP*1.2")
        if st.button("⚡ Apply Unit Price"):
            if not st.session_state.quote_df.empty:
                st.session_state.quote_df = apply_formula_logic(st.session_state.quote_df, unit_f, "Unit price(VND)")
                st.session_state.quote_df = recalculate_all_columns(st.session_state.quote_df)
                st.session_state.quote_editor_key += 1
                st.rerun()
    
    with c_del:
        st.markdown("<br>", unsafe_allow_html=True) 
        if st.button("🗑️ XÓA DÒNG CHỌN", type="primary"):
            if not st.session_state.quote_df.empty:
                st.session_state.quote_df = st.session_state.quote_df[st.session_state.quote_df["Xóa"] == False].reset_index(drop=True)
                st.session_state.quote_df["No"] = st.session_state.quote_df.index + 1
                st.session_state.quote_editor_key += 1
                st.rerun()

    # --- DATA EDITOR (BẢNG CHÍNH) ---
    if not st.session_state.quote_df.empty:
        df_view = st.session_state.quote_df.copy()
        
        # Các cột cần định dạng số tiền (1.000,0)
        cols_currency = [
            "Buying price(RMB)", "Total buying price(rmb)", 
            "Buying price(VND)", "Total buying price(VND)", 
            "AP price(VND)", "AP total price(VND)", 
            "Unit price(VND)", "Total price(VND)", 
            "GAP", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", 
            "Transportation", "Management fee(%)", "Payback(%)", "Profit(VND)"
        ]
        
        column_config = {
            "Xóa": st.column_config.CheckboxColumn("Xóa", width="small", default=False),
            "Cảnh báo": st.column_config.TextColumn("Cảnh báo", width="small", disabled=True),
            "No": st.column_config.TextColumn("No", width="small", disabled=True),
            "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d", step=1),
            "Exchange rate": st.column_config.NumberColumn("Exchange rate", format="%.2f"),
            "Profit(%)": st.column_config.TextColumn("Profit(%)", disabled=True),
        }
        
        # Áp dụng format "1,234.5" 
        for c in cols_currency:
            column_config[c] = st.column_config.NumberColumn(c, format="%.1f")

        cols_to_hide = ["Profit_Pct_Raw", "Image"]
        cols_show = [c for c in df_view.columns if c not in cols_to_hide]
        ordered_cols = ["Xóa", "No", "Cảnh báo"] + [c for c in cols_show if c not in ["Xóa", "No", "Cảnh báo"]]
        df_view = df_view[ordered_cols]

        edited_df = st.data_editor(
            df_view,
            column_config=column_config,
            use_container_width=True,
            height=500,
            hide_index=True,
            key=f"quote_editor_{st.session_state.quote_editor_key}" 
        )

        # --- XỬ LÝ AUTO-UPDATE ---
        # Kiểm tra nếu dữ liệu thay đổi thì tính lại ngay
        if not edited_df.drop(columns=['Xóa']).equals(st.session_state.quote_df[ordered_cols].drop(columns=['Xóa'])):
            recalculated = recalculate_all_columns(edited_df)
            st.session_state.quote_df = recalculate_all_columns(recalculated)
            st.rerun()
        else:
            # Nếu chỉ tick checkbox, cập nhật trạng thái tick để không bị mất
            st.session_state.quote_df["Xóa"] = edited_df["Xóa"]

        # --- TOTAL ROW (Tự động tính tổng) ---
        cols_sum_target = [
            "Q'ty", "Buying price(RMB)", "Total buying price(rmb)", "Exchange rate",
            "Buying price(VND)", "Total buying price(VND)", "AP price(VND)", "AP total price(VND)",
            "Unit price(VND)", "Total price(VND)", "GAP",
            "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", "Transportation", 
            "Management fee(%)", "Payback(%)", "Profit(VND)"
        ]
        
        total_data = {}
        for c in df_view.columns:
            if c in cols_sum_target:
                val_sum = st.session_state.quote_df[c].apply(safe_float).sum()
                if c == "Exchange rate": total_data[c] = ""
                else: total_data[c] = val_sum
            elif c == "No": total_data[c] = "TOTAL"
            else: total_data[c] = ""

        df_total = pd.DataFrame([total_data])
        df_total = df_total[ordered_cols] 

        # Style cho dòng Total (Màu vàng, chữ đậm)
        def highlight_total(row):
            return ['background-color: #ffd700; color: black; font-weight: bold'] * len(row)

        st.dataframe(
            df_total.style.apply(highlight_total, axis=1).format(precision=1, thousands=","),
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )

    # ------------------ PHẦN 3: REVIEW & XUẤT ------------------
    st.divider()
    c_rev, c_sv = st.columns([1, 1])
    
    with c_rev:
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("🔍 REVIEW BÁO GIÁ"): st.session_state.show_review = True
        st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.get('show_review', False) and not st.session_state.quote_df.empty:
        st.write("### 📋 BẢNG REVIEW")
        
        cols_review = ["No", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Leadtime"]
        valid_cols = [c for c in cols_review if c in st.session_state.quote_df.columns]
        df_review = st.session_state.quote_df[valid_cols].copy()
        
        # Tổng Review
        total_rev = {c: "" for c in df_review.columns}
        total_rev["No"] = "TOTAL"
        total_rev["Q'ty"] = df_review["Q'ty"].apply(safe_float).sum()
        total_rev["Unit price(VND)"] = df_review["Unit price(VND)"].apply(safe_float).sum()
        total_rev["Total price(VND)"] = df_review["Total price(VND)"].apply(safe_float).sum()
        
        df_review = pd.concat([df_review, pd.DataFrame([total_rev])], ignore_index=True)

        # Style màu xanh cho dòng tổng review
        def style_review(row):
            if row['No'] == 'TOTAL':
                return ['background-color: #90ee90; color: black; font-weight: bold'] * len(row)
            return [''] * len(row)

        st.dataframe(
            df_review.style.apply(style_review, axis=1),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d"),
                "Unit price(VND)": st.column_config.NumberColumn("Unit price(VND)", format="%.1f"),
                "Total price(VND)": st.column_config.NumberColumn("Total price(VND)", format="%.1f")
            }
        )

        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("📤 XUẤT BÁO GIÁ (Excel)"):
            if not cust_name: st.error("Chưa chọn khách hàng!")
            else:
                try:
                    df_tmpl = load_data("crm_templates")
                    match_tmpl = df_tmpl[df_tmpl['template_name'].astype(str).str.contains("AAA-QUOTATION", case=False, na=False)]
                    if match_tmpl.empty: st.error("Không tìm thấy template 'AAA-QUOTATION'!")
                    else:
                        tmpl_id = match_tmpl.iloc[0]['file_id']
                        fh = download_from_drive(tmpl_id)
                        if not fh: st.error("Lỗi tải template!")
                        else:
                            wb = load_workbook(fh); ws = wb.active
                            start_row = 11
                            first_lt = st.session_state.quote_df.iloc[0]['Leadtime'] if 'Leadtime' in st.session_state.quote_df.columns else ""
                            ws['H8'] = safe_str(first_lt)
                            
                            for idx, row in st.session_state.quote_df.iterrows():
                                r = start_row + idx
                                ws[f'A{r}'] = row['No']
                                ws[f'C{r}'] = row['Item code']
                                ws[f'D{r}'] = row['Item name']
                                ws[f'E{r}'] = row['Specs']
                                ws[f'F{r}'] = safe_float(row["Q'ty"])
                                ws[f'G{r}'] = safe_float(row["Unit price(VND)"])
                                ws[f'H{r}'] = safe_float(row["Total price(VND)"])
                            
                            out = io.BytesIO(); wb.save(out); out.seek(0)
                            curr_year = datetime.now().strftime("%Y")
                            curr_month = datetime.now().strftime("%b").upper()
                            fname = f"QUOTE_{quote_no}_{cust_name}_{int(time.time())}.xlsx"
                            path_list = ["QUOTATION_HISTORY", cust_name, curr_year, curr_month]
                            lnk, _ = upload_to_drive_structured(out, path_list, fname)
                            st.success(f"✅ Đã xuất báo giá: {fname}")
                            st.markdown(f"📂 [Mở Folder]({lnk})", unsafe_allow_html=True)
                            st.download_button("📥 Tải File", out, fname, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception as e: st.error(f"Lỗi xuất Excel: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    with c_sv:
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("💾 LƯU LỊCH SỬ"):
            if cust_name:
                recs = []
                for r in st.session_state.quote_df.to_dict('records'):
                    recs.append({
                        "history_id": f"{cust_name}_{int(time.time())}", 
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "quote_no": quote_no, "customer": cust_name,
                        "item_code": r["Item code"], 
                        "qty": safe_float(r["Q'ty"]),
                        "unit_price": safe_float(r["Unit price(VND)"]),
                        "total_price_vnd": safe_float(r["Total price(VND)"]),
                        "profit_vnd": safe_float(r["Profit(VND)"])
                    })
                try:
                    try:
                        supabase.table("crm_shared_history").insert(recs).execute()
                    except:
                        st.warning("Đang lưu chế độ tương thích...")
                        supabase.table("crm_shared_history").insert(recs).execute()
                    
                    st.success("✅ Đã lưu lịch sử!")
                except Exception as e: st.error(f"Lỗi lưu: {e}")
            else: st.error("Chọn khách!")
        st.markdown('</div>', unsafe_allow_html=True)
