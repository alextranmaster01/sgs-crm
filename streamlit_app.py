import streamlit as st
import pandas as pd
import backend # Import file backend vừa tạo
import time
import io
import re
from openpyxl import load_workbook

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="SGS CRM V4800 - ONLINE", layout="wide", page_icon="🪶")

# --- CSS TÙY CHỈNH ---
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { background-color: #ecf0f1; border-radius: 4px 4px 0 0; padding: 10px 20px; font-weight: bold; }
    .stTabs [aria-selected="true"] { background-color: #3498db; color: white; }
</style>
""", unsafe_allow_html=True)

# --- CÁC HÀM LOGIC BỔ TRỢ (ĐỂ TRONG NÀY LUÔN CHO GỌN) ---
def safe_str(val):
    if val is None: return ""
    return str(val).strip()

def safe_filename(s):
    return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))

def to_float(val):
    try:
        if isinstance(val, (int, float)): return float(val)
        clean = str(val).replace(",", "").replace("%", "").strip()
        return float(clean) if clean else 0.0
    except: return 0.0

def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"

def clean_lookup_key(s):
    if s is None: return ""
    try:
        f = float(str(s))
        if f.is_integer(): return str(int(f))
    except: pass
    return re.sub(r'\s+', '', str(s)).lower()

# --- KHỞI TẠO SESSION STATE ---
if 'quote_df' not in st.session_state:
    st.session_state.quote_df = pd.DataFrame(columns=["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"])

# --- HEADER ---
st.title("SGS CRM V4800 - FINAL FULL FEATURES (ONLINE)")

# --- TABS LAYOUT ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Tổng quan", 
    "💰 Báo giá NCC (DB Giá)", 
    "📝 Báo giá KH", 
    "📦 Đơn đặt hàng", 
    "🚚 Theo dõi & Thanh toán", 
    "⚙️ Master Data"
])

# =============================================================================
# TAB 1: DASHBOARD
# =============================================================================
with tab1:
    st.subheader("DASHBOARD KINH DOANH")
    col_act, col_reset = st.columns([8, 2])
    with col_act:
        if st.button("🔄 CẬP NHẬT DATA", type="primary"):
            st.cache_data.clear()
            st.rerun()
    
    # Load Data Snapshot (Sử dụng backend.load_data đã fix lỗi rỗng)
    db_cust_orders = backend.load_data("customer_orders")
    sales_history = backend.load_data("sales_history")
    payment_df = backend.load_data("payment")
    paid_history = backend.load_data("paid_history")

    # Tính toán Metrics
    rev = db_cust_orders['total_price'].apply(to_float).sum() if not db_cust_orders.empty else 0
    profit = sales_history['profit'].apply(to_float).sum() if not sales_history.empty else 0
    cost = rev - profit
    paid_count = len(paid_history)
    
    # Fix lỗi KeyError 'status' bằng cách check cột trước
    if 'status' in payment_df.columns:
        unpaid_count = len(payment_df[payment_df['status'] != "Đã thanh toán"])
    else:
        unpaid_count = 0

    m1, m2, m3 = st.columns(3)
    m1.info(f"**TỔNG DOANH THU**\n\n# {fmt_num(rev)}")
    m2.warning(f"**TỔNG CHI PHÍ**\n\n# {fmt_num(cost)}")
    m3.success(f"**LỢI NHUẬN**\n\n# {fmt_num(profit)}")
    
    m4, m5 = st.columns(2)
    m4.success(f"**TỔNG PO ĐÃ THANH TOÁN**: {paid_count}")
    m5.error(f"**TỔNG PO CHƯA THANH TOÁN**: {unpaid_count}")

# =============================================================================
# TAB 2: BÁO GIÁ NCC (DB GIÁ) - ĐÃ FIX FULL LỖI
# =============================================================================
with tab2:
    st.subheader("Database Giá NCC (Tự động tách ảnh & Upload lên Drive)")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file:
            if st.button("🚀 BẮT ĐẦU IMPORT & UPLOAD DRIVE", type="primary"):
                status_box = st.status("Đang xử lý dữ liệu...", expanded=True)
                try:
                    # A. ĐỌC DỮ LIỆU
                    status_box.write("📖 Đang đọc dữ liệu Excel...")
                    df_raw = pd.read_excel(uploaded_file, header=None, dtype=str).fillna("")
                    
                    start_row = 0
                    for i in range(min(20, len(df_raw))):
                        row_str = str(df_raw.iloc[i].values).lower()
                        if 'item code' in row_str or 'mã hàng' in row_str:
                            start_row = i + 1
                            break
                    
                    # B. TÁCH ẢNH TỪ EXCEL
                    status_box.write("🖼️ Đang tách ảnh từ file...")
                    uploaded_file.seek(0)
                    wb = load_workbook(uploaded_file, data_only=True)
                    ws = wb.active
                    
                    image_map = {}
                    if hasattr(ws, '_images'):
                        for img in ws._images:
                            row_idx = img.anchor._from.row
                            img_bytes = img._data()
                            image_map[row_idx] = img_bytes
                    
                    status_box.write(f"✅ Tìm thấy {len(image_map)} ảnh...")

                    # C. UPLOAD & TẠO DATA
                    data_clean = []
                    total_rows = len(df_raw) - start_row
                    prog_bar = status_box.progress(0)
                    count_uploaded = 0
                    
                    for idx, i in enumerate(range(start_row, len(df_raw))):
                        prog_bar.progress(min((idx + 1) / total_rows, 1.0))
                        row = df_raw.iloc[i]
                        
                        def get(col_idx): 
                            return safe_str(row[col_idx]) if col_idx < len(row) else ""
                        
                        code_val = get(1) # Item Code
                        if not code_val: continue 

                        # Xử lý Upload Ảnh
                        final_img_link = ""
                        if i in image_map:
                            img_data = image_map[i]
                            filename = f"{safe_filename(code_val)}.png"
                            file_obj = io.BytesIO(img_data)
                            
                            status_box.write(f"☁️ Upload ảnh: {filename}...")
                            # Gọi backend để upload (Đã có logic chống trùng)
                            link = backend.upload_to_drive(file_obj, filename, folder_type="images")
                            if link:
                                final_img_link = link
                                count_uploaded += 1
                        else:
                            # Lấy link cũ nếu có
                            old_path = get(12)
                            if "http" in old_path: final_img_link = old_path

                        # Tạo Dữ Liệu
                        item = {
                            "no": get(0), "item_code": code_val, "item_name": get(2),
                            "specs": get(3), "qty": fmt_num(to_float(get(4))),
                            "buying_price_rmb": fmt_num(to_float(get(5))),
                            "total_buying_price_rmb": fmt_num(to_float(get(6))),
                            "exchange_rate": fmt_num(to_float(get(7))),
                            "buying_price_vnd": fmt_num(to_float(get(8))),
                            "total_buying_price_vnd": fmt_num(to_float(get(9))),
                            "leadtime": get(10), "supplier_name": get(11),
                            "image_path": final_img_link, # Cột ảnh
                            "_clean_code": clean_lookup_key(code_val),
                            "_clean_specs": clean_lookup_key(get(3)),
                            "_clean_name": clean_lookup_key(get(2))
                        }
                        data_clean.append(item)
                    
                    # D. LƯU VÀO DATABASE
                    if data_clean:
                        df_final = pd.DataFrame(data_clean)
                        backend.save_data("purchases", df_final)
                        status_box.update(label=f"✅ Xong! Đã upload {count_uploaded} ảnh.", state="complete", expanded=False)
                        time.sleep(1)
                        st.rerun()
                    else:
                        status_box.update(label="⚠️ Không có dữ liệu!", state="error")

                except Exception as e:
                    st.error(f"❌ Lỗi: {e}")
                    status_box.update(label="Gặp lỗi!", state="error")

    # HIỂN THỊ DỮ LIỆU
    df_pur = backend.load_data("purchases")
    
    search_term = st.text_input("🔍 Tìm kiếm code, tên...", key="search_pur")
    if search_term and not df_pur.empty:
        mask = df_pur.apply(lambda x: x.astype(str).str.contains(search_term, case=False, na=False)).any(axis=1)
        df_pur = df_pur[mask]

    # Cấu hình hiển thị ảnh
    column_cfg = {
        "image_path": st.column_config.ImageColumn("Hình Ảnh", width="small"),
        "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Mua (VND)", format="%d"),
        "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
    }
    
    cols_order = ["image_path", "no", "item_code", "item_name", "specs", "qty", 
                  "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
                  "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name"]

    edited_pur = st.data_editor(
        df_pur, 
        num_rows="dynamic", 
        use_container_width=True,
        key="editor_pur",
        column_config=column_cfg, 
        column_order=cols_order,
        height=600
    )
    
    if st.button("💾 Lưu thay đổi DB NCC", type="primary"):
        backend.save_data("purchases", edited_pur)

# =============================================================================
# TAB 3: BÁO GIÁ KHÁCH HÀNG
# =============================================================================
with tab3:
    t3_sub1, t3_sub2 = st.tabs(["Tạo Báo Giá", "Tra Cứu Lịch Sử"])
    
    with t3_sub1:
        with st.expander("1. Thông tin chung & Tham số", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            cust_df = backend.load_data("customers")
            cust_list = cust_df["short_name"].tolist() if not cust_df.empty else []
            curr_cust = c1.selectbox("Khách hàng:", options=[""] + cust_list)
            quote_name = c2.text_input("Tên Báo Giá:")
            
            c3.markdown("**Chi phí (%)**")
            p_end = c3.number_input("End User (%)", value=0.0)
            p_buy = c3.number_input("Buyer (%)", value=0.0)
            p_tax = c3.number_input("Tax (%)", value=0.0)
            
            c4.markdown("**Chi phí khác**")
            p_vat = c4.number_input("VAT (%)", value=0.0)
            p_trans = c4.number_input("Trans (VND)", value=0)

        col_func, col_calc = st.columns([1, 1])
        with col_func:
            if st.button("✨ TẠO MỚI (RESET)"):
                st.session_state.quote_df = pd.DataFrame(columns=st.session_state.quote_df.columns)
                st.rerun()
                
        st.write("### Chi tiết Báo Giá")
        edited_quote = st.data_editor(st.session_state.quote_df, num_rows="dynamic", use_container_width=True)
        st.session_state.quote_df = edited_quote

        if st.button("🔄 TÍNH LỢI NHUẬN", type="primary"):
            df = st.session_state.quote_df
            for i, r in df.iterrows():
                qty = to_float(r.get("qty", 0))
                buy_vnd = to_float(r.get("buying_price_vnd", 0))
                t_buy = qty * buy_vnd
                
                use_trans = p_trans if p_trans > 0 else to_float(r.get("transportation", 0))
                ap_price = to_float(r.get("ap_price", 0))
                unit_price = to_float(r.get("unit_price", 0))
                
                ap_tot = ap_price * qty
                total_sell = unit_price * qty
                gap = total_sell - ap_tot
                
                tax_val = t_buy * (p_tax/100)
                buyer_val = total_sell * (p_buy/100)
                vat_val = total_sell * (p_vat/100)
                end_val = ap_tot * (p_end/100)
                trans_total = use_trans * qty
                
                df.at[i, "total_price_vnd"] = fmt_num(total_sell)
                df.at[i, "profit_vnd"] = fmt_num(total_sell - (t_buy + gap + end_val + buyer_val + tax_val + vat_val + trans_total))
                
            st.session_state.quote_df = df
            st.success("Đã tính toán xong!")
            st.rerun()

    with t3_sub2:
        st.write("Lịch sử báo giá (Chức năng đang phát triển)")

# =============================================================================
# TAB 4: ĐƠN ĐẶT HÀNG
# =============================================================================
with tab4:
    t4_sub1, t4_sub2 = st.tabs(["1. Đặt hàng NCC", "2. PO Khách Hàng"])
    
    with t4_sub1:
        st.info("Module tạo PO cho Nhà Cung Cấp")
        col_po1, col_po2 = st.columns(2)
        po_ncc_num = col_po1.text_input("Số PO NCC")
        
        supp_df = backend.load_data("suppliers")
        supp_list = supp_df["short_name"].tolist() if not supp_df.empty else []
        supp_select = col_po2.selectbox("Chọn NCC", [""] + supp_list)
        
        if 'temp_supp_order' not in st.session_state:
            st.session_state.temp_supp_order = pd.DataFrame(columns=["item_code", "qty", "price_rmb", "total_rmb", "eta"])
            
        edited_supp_order = st.data_editor(st.session_state.temp_supp_order, num_rows="dynamic")
        st.session_state.temp_supp_order = edited_supp_order
        
        if st.button("🚀 Gửi Đơn Hàng NCC"):
            # Logic lưu đơn hàng NCC sẽ thêm sau
            st.toast("Chức năng đang phát triển")

    with t4_sub2:
        st.info("Module tạo PO Khách Hàng")

# =============================================================================
# TAB 5: THEO DÕI & THANH TOÁN
# =============================================================================
with tab5:
    st.subheader("Trạng thái đơn hàng")
    df_track = backend.load_data("tracking")
    
    if 'status' in df_track.columns:
        status_filter = st.multiselect("Lọc trạng thái", options=df_track["status"].unique())
        if status_filter:
            df_track = df_track[df_track["status"].isin(status_filter)]
        
    edited_track = st.data_editor(df_track, key="tracking_editor", num_rows="dynamic")
    if st.button("Cập nhật Tracking"):
        backend.save_data("tracking", edited_track)
        
    st.divider()
    st.subheader("Quản lý Thanh Toán")
    df_pay = backend.load_data("payment")
    
    # Highlight dòng chưa thanh toán
    def highlight_late(row):
        if 'status' in row and row['status'] != 'Đã thanh toán':
            return ['background-color: #ffcccc'] * len(row)
        return [''] * len(row)

    if not df_pay.empty:
        st.dataframe(df_pay.style.apply(highlight_late, axis=1))
    else:
        st.dataframe(df_pay)

# =============================================================================
# TAB 6: MASTER DATA
# =============================================================================
with tab6:
    t6_1, t6_2 = st.tabs(["Khách Hàng", "Nhà Cung Cấp"])
    
    with t6_1:
        df_c = backend.load_data("customers")
        edited_c = st.data_editor(df_c, num_rows="dynamic", key="editor_cust")
        if st.button("Lưu Master KH"): backend.save_data("customers", edited_c)
        
    with t6_2:
        df_s = backend.load_data("suppliers")
        edited_s = st.data_editor(df_s, num_rows="dynamic", key="editor_supp")
        if st.button("Lưu Master NCC"): backend.save_data("suppliers", edited_s)
