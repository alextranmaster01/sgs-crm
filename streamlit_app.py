# =============================================================================
# CRM SYSTEM - FINAL HYBRID EDITION
# BASE UI/LOGIC: V4800 "GIAO DIỆN SẮC MÀU" (Offline Standard)
# INFRASTRUCTURE: V6023 (Online/Cloud Standard)
# =============================================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import re
import json
from datetime import datetime, timedelta

# --- THƯ VIỆN CLOUD ---
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    import xlsxwriter
    import plotly.express as px
except ImportError:
    st.error("⚠️ Hệ thống thiếu thư viện. Vui lòng cài đặt file requirements.txt")
    st.stop()

# =============================================================================
# 1. THIẾT LẬP GIAO DIỆN "SẮC MÀU" (CHUẨN V4800)
# =============================================================================
st.set_page_config(
    page_title="CRM V4800 ONLINE", 
    layout="wide", 
    page_icon="🌈",
    initial_sidebar_state="expanded"
)

# --- CSS INJECTION: Mang hồn của bản Offline lên Web ---
st.markdown("""
    <style>
    /* 1. Nền & Font chữ */
    .stApp { background-color: #f4f6f9; }
    
    /* 2. Button Style "Sắc Màu" - Gradient Buttons */
    div.stButton > button { 
        background: linear-gradient(90deg, #1CB5E0 0%, #000851 100%);
        color: white; 
        font-weight: bold; 
        border: none; 
        border-radius: 8px; 
        height: 45px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.3);
        background: linear-gradient(90deg, #00C9FF 0%, #92FE9D 100%);
        color: #000;
    }

    /* 3. Dashboard Cards 3D (Chuẩn V4800) */
    .dashboard-card {
        border-radius: 15px;
        padding: 20px;
        color: white;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        position: relative;
        overflow: hidden;
    }
    .card-sales { background: linear-gradient(45deg, #FF416C, #FF4B2B); }
    .card-profit { background: linear-gradient(45deg, #00b09b, #96c93d); }
    .card-orders { background: linear-gradient(45deg, #8E2DE2, #4A00E0); }
    
    .card-value { font-size: 32px; font-weight: 800; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
    .card-title { font-size: 16px; font-weight: 600; opacity: 0.9; text-transform: uppercase; }

    /* 4. Tab Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #fff;
        border-radius: 5px;
        color: #333;
        font-weight: 600;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stTabs [aria-selected="true"] {
        background-color: #000851;
        color: white;
    }

    /* 5. Table/DataEditor Style */
    [data-testid="stDataFrame"] { border: 2px solid #000851; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# Khởi tạo Session State
if 'quote_data' not in st.session_state: st.session_state['quote_data'] = None
if 'history_check_data' not in st.session_state: st.session_state['history_check_data'] = None

# =============================================================================
# 2. CORE BACKEND (LOGIC V4800 + INFRA V6023)
# =============================================================================

class CRMBackend:
    def __init__(self):
        self.supabase = self.connect_supabase()
        self.drive_service = self.connect_google_drive()

    def connect_supabase(self):
        try:
            return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        except Exception as e:
            st.error(f"❌ Lỗi Supabase: {e}"); return None

    def connect_google_drive(self):
        try:
            info = st.secrets["google_oauth"]
            creds = Credentials(None, refresh_token=info["refresh_token"],
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=info["client_id"], client_secret=info["client_secret"])
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"❌ Lỗi Google Drive: {e}"); return None

    # --- GOOGLE DRIVE UPLOAD (RECURSIVE FOLDER) ---
    def get_folder_id(self, name, parent_id):
        try:
            q = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            files = self.drive_service.files().list(q=q, fields="files(id)").execute().get('files', [])
            if files: return files[0]['id']
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
            return self.drive_service.files().create(body=meta, fields='id').execute().get('id')
        except: return None

    def upload_recursive(self, file_obj, filename, root_type, year, entity, month):
        if not self.drive_service: return None, "Mất kết nối Drive"
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            l1 = self.get_folder_id(root_type, root_id)
            l2 = self.get_folder_id(str(year), l1)
            clean_entity = re.sub(r'[\\/*?:"<>|]', "", str(entity).upper().strip())
            l3 = self.get_folder_id(clean_entity, l2)
            l4 = self.get_folder_id(str(month).upper(), l3)
            
            media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream', resumable=True)
            meta = {'name': filename, 'parents': [l4]}
            f = self.drive_service.files().create(body=meta, media_body=media, fields='webViewLink').execute()
            return f.get('webViewLink'), f"{root_type}/{year}/{clean_entity}/{month}/{filename}"
        except Exception as e: return None, str(e)

    # --- LOGIC TÍNH TOÁN LỢI NHUẬN (TUYỆT ĐỐI CHUẨN V4800) ---
    def calculate_profit_v4800(self, row):
        try:
            qty = float(row.get("Q'ty", 0))
            buy_rmb = float(row.get('Buying Price (RMB)', 0))
            rate = float(row.get('Exchange Rate', 3600))
            
            # Logic V4800: Giá vốn
            buy_vnd = buy_rmb * rate
            total_buy = buy_vnd * qty
            
            # Logic V4800: AP Price (Mặc định x2 nếu không nhập)
            user_ap = float(row.get('AP Price (VND)', 0))
            if user_ap > 0: ap_total = user_ap * qty
            else: ap_total = total_buy * 2
            
            # Logic V4800: GAP (10% AP)
            gap = 0.10 * ap_total
            
            # Logic V4800: Giá bán (AP + GAP)
            total_price = ap_total + gap
            unit_price = total_price / qty if qty > 0 else 0
            
            # Logic V4800: Chi phí cố định
            costs = (total_buy + gap + 
                     (0.10 * ap_total) + # End User
                     (0.05 * total_price) + # Buyer
                     (0.10 * total_buy) + # Tax
                     (0.10 * total_price) + # VAT
                     (0.10 * total_price) + # Mgmt
                     30000) # Trans
                     
            # Logic V4800: Payback (40% GAP)
            payback = 0.40 * gap
            
            # Logic V4800: Profit Final
            profit = total_price - costs + payback
            pct = (profit / total_price * 100) if total_price > 0 else 0
            
            return pd.Series({
                'Buying Price (VND)': buy_vnd,
                'Total Buying (VND)': total_buy,
                'AP Price (VND)': ap_total/qty if qty else 0,
                'AP Total (VND)': ap_total,
                'GAP': gap,
                'Total Price (VND)': total_price,
                'Unit Price (VND)': unit_price,
                'PROFIT (VND)': profit,
                '% Profit': pct
            })
        except: return pd.Series({'PROFIT (VND)': 0})

    # --- EXPORT DOCX (ĐỊNH DẠNG NGANG V4800) ---
    def export_docx_v4800(self, df, cust_name):
        doc = Document()
        section = doc.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
        
        h = doc.add_heading(f'TECHNICAL SPECS - {str(cust_name).upper()}', 0)
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        cols = ['Specs', "Q'ty", 'Buying Price (VND)', 'Total Buying (VND)', 'AP Price (VND)', 'Total Price (VND)', 'PROFIT (VND)', '% Profit']
        t = doc.add_table(rows=1, cols=len(cols))
        t.style = 'Table Grid'
        
        for i, c in enumerate(cols):
            run = t.rows[0].cells[i].paragraphs[0].add_run(c)
            run.font.bold = True
            
        for _, row in df.iterrows():
            cells = t.add_row().cells
            for i, c in enumerate(cols):
                val = row.get(c, 0)
                if isinstance(val, (int, float)): cells[i].text = "{:,.0f}".format(val)
                elif c == "% Profit": cells[i].text = f"{val:.1f}%"
                else: cells[i].text = str(val)
                
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf

backend = CRMBackend()

# =============================================================================
# 3. GIAO DIỆN CHÍNH (MAIN NAVIGATION)
# =============================================================================

# Sidebar Style V4800
with st.sidebar:
    st.title("🌈 CRM V4800 ONLINE")
    st.markdown("---")
    menu = st.radio("MENU ĐIỀU HƯỚNG", [
        "📊 DASHBOARD",
        "📦 KHO HÀNG (INVENTORY)",
        "💰 BÁO GIÁ (QUOTATION)",
        "📑 QUẢN LÝ PO",
        "🚚 VẬN ĐƠN (TRACKING)",
        "⚙️ MASTER DATA"
    ])
    st.markdown("---")
    st.caption("Phiên bản: V4800 Hybrid Cloud")

# -----------------------------------------------------------------------------
# TAB 1: DASHBOARD (GIAO DIỆN 3D CARD)
# -----------------------------------------------------------------------------
if menu == "📊 DASHBOARD":
    st.markdown("## 📊 TỔNG QUAN HỆ THỐNG")
    
    try:
        # Load Data Live
        q_res = backend.supabase.table("crm_shared_history").select("total_profit_vnd").execute()
        p_res = backend.supabase.table("db_customer_orders").select("total_value, po_number").execute()
        
        df_q = pd.DataFrame(q_res.data)
        df_p = pd.DataFrame(p_res.data)
        
        profit_total = df_q['total_profit_vnd'].sum() if not df_q.empty else 0
        sales_total = df_p['total_value'].sum() if not df_p.empty else 0
        orders_count = len(df_p)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""
            <div class="dashboard-card card-sales">
                <div class="card-title">DOANH SỐ TỔNG</div>
                <div class="card-value">{sales_total:,.0f}</div>
                <div>VND</div>
            </div>""", unsafe_allow_html=True)
            
        with c2:
            st.markdown(f"""
            <div class="dashboard-card card-profit">
                <div class="card-title">LỢI NHUẬN TỔNG</div>
                <div class="card-value">{profit_total:,.0f}</div>
                <div>VND</div>
            </div>""", unsafe_allow_html=True)
            
        with c3:
            st.markdown(f"""
            <div class="dashboard-card card-orders">
                <div class="card-title">TỔNG ĐƠN HÀNG</div>
                <div class="card-value">{orders_count}</div>
                <div>PO</div>
            </div>""", unsafe_allow_html=True)
            
        st.divider()
        if not df_q.empty:
            st.subheader("📈 Biểu đồ tăng trưởng lợi nhuận")
            st.line_chart(df_q.reset_index()['total_profit_vnd'])
            
    except Exception as e:
        st.error(f"Lỗi tải Dashboard: {e}")

# -----------------------------------------------------------------------------
# TAB 2: KHO HÀNG (TRA CỨU V4800)
# -----------------------------------------------------------------------------
elif menu == "📦 KHO HÀNG (INVENTORY)":
    st.markdown("## 📦 TRA CỨU TỒN KHO & GIÁ VỐN")
    
    search = st.text_input("🔍 Tra cứu nhanh (Nhập mã Specs, Tên hàng...)", placeholder="Ví dụ: N610...")
    
    res = backend.supabase.table("crm_purchases").select("*").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        if search:
            mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)
            df = df[mask]
        
        st.dataframe(
            df, 
            use_container_width=True, 
            column_config={
                "buying_price_rmb": st.column_config.NumberColumn("Giá Mua (RMB)", format="%.2f"),
                "exchange_rate": st.column_config.NumberColumn("Tỷ Giá", format="%.0f"),
            }
        )
        st.caption(f"Tìm thấy {len(df)} mã hàng.")
    else: st.info("Kho hàng trống.")

# -----------------------------------------------------------------------------
# TAB 3: BÁO GIÁ (CHIA SUB-TABS NHƯ V4800)
# -----------------------------------------------------------------------------
elif menu == "💰 BÁO GIÁ (QUOTATION)":
    st.markdown("## 💰 QUẢN LÝ BÁO GIÁ")
    
    # Chia 2 Sub-tab chuẩn V4800
    tab_create, tab_history = st.tabs(["📝 TẠO BÁO GIÁ MỚI", "🔍 TRA CỨU LỊCH SỬ (BULK CHECK)"])
    
    # --- SUB-TAB 1: TẠO BÁO GIÁ ---
    with tab_create:
        c1, c2 = st.columns([1, 2])
        cust = c1.text_input("Tên Khách Hàng")
        rfq = c2.file_uploader("Upload File RFQ (Excel/CSV)", type=['xlsx', 'csv'])
        
        if rfq and cust:
            if st.session_state['quote_data'] is None:
                df_in = pd.read_csv(rfq) if rfq.name.endswith('.csv') else pd.read_excel(rfq)
                df_in.columns = [str(c).strip() for c in df_in.columns]
                
                # Get DB Prices
                db = backend.supabase.table("crm_purchases").select("specs, buying_price_rmb, exchange_rate").execute()
                df_db = pd.DataFrame(db.data)
                
                if 'Specs' in df_in.columns:
                    if not df_db.empty:
                        df_in['Specs'] = df_in['Specs'].astype(str).str.strip()
                        df_db['specs'] = df_db['specs'].astype(str).str.strip()
                        merged = pd.merge(df_in, df_db, left_on='Specs', right_on='specs', how='left')
                        merged.rename(columns={'buying_price_rmb': 'Buying Price (RMB)', 'exchange_rate': 'Exchange Rate'}, inplace=True)
                        merged.fillna(0, inplace=True)
                        merged['Exchange Rate'].replace(0, 3600, inplace=True)
                        merged['AP Price (VND)'] = 0
                        st.session_state['quote_data'] = merged
                    else: st.session_state['quote_data'] = df_in
                else: st.error("File RFQ thiếu cột Specs!")
            
            st.info("👇 Chỉnh sửa dữ liệu trực tiếp:")
            edited = st.data_editor(st.session_state['quote_data'], num_rows="dynamic", use_container_width=True)
            
            col_btn1, col_btn2 = st.columns([1, 4])
            if col_btn1.button("🚀 TÍNH TOÁN"):
                res = edited.apply(backend.calculate_profit_v4800, axis=1)
                st.session_state['quote_data'] = pd.concat([edited, res], axis=1)
                st.success("Đã tính toán xong!")
                
            if col_btn2.button("Làm mới"):
                st.session_state['quote_data'] = None; st.rerun()
                
            if 'PROFIT (VND)' in st.session_state['quote_data'].columns:
                final = st.session_state['quote_data']
                st.divider()
                st.dataframe(final.style.format("{:,.0f}", subset=['PROFIT (VND)', 'Total Price (VND)'])
                             .background_gradient(subset=['PROFIT (VND)'], cmap='RdYlGn'), use_container_width=True)
                
                total_p = final['PROFIT (VND)'].sum()
                st.markdown(f"### TỔNG LỢI NHUẬN: :green[{total_p:,.0f} VND]")
                
                b1, b2, b3 = st.columns(3)
                docx = backend.export_docx_v4800(final, cust)
                b1.download_button("📄 Tải Specs (.docx)", docx, f"Specs_{cust}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf) as w: final.to_excel(w)
                b2.download_button("📊 Tải Excel (.xlsx)", buf.getvalue(), f"Quote_{cust}.xlsx")
                
                if b3.button("💾 Lưu Lịch Sử"):
                    qid = f"Q-{int(time.time())}"
                    backend.supabase.table("crm_shared_history").insert({
                        "quote_id": qid, "customer_name": cust, "total_profit_vnd": total_p, "status": "Quote Sent"
                    }).execute()
                    st.success("Đã lưu!")

    # --- SUB-TAB 2: TRA CỨU LỊCH SỬ (TÍNH NĂNG ĐẶC BIỆT CỦA V4800) ---
    with tab_history:
        st.subheader("🔍 Bulk Check History (Kiểm tra lịch sử hàng loạt)")
        st.caption("Upload file Excel chứa danh sách Specs để xem lịch sử giá đã từng báo.")
        
        hist_file = st.file_uploader("Upload File Check (Excel)", type=['xlsx'], key="hist_up")
        
        if hist_file:
            if st.button("Kiểm tra Lịch sử"):
                # 1. Đọc file input
                df_h = pd.read_excel(hist_file)
                if 'Specs' in df_h.columns:
                    specs_list = df_h['Specs'].astype(str).tolist()
                    
                    # 2. Query Supabase (Giả lập logic search vì data json phức tạp)
                    # Trong thực tế cần query JSONB, ở đây ta load all history rồi filter (cho đơn giản với Streamlit)
                    all_hist = backend.supabase.table("crm_shared_history").select("*").execute().data
                    
                    found_records = []
                    # Logic tìm kiếm đơn giản: Nếu Specs có trong Items JSON của History
                    # Lưu ý: Cần DB lưu items_json. Nếu V4800 cũ lưu text thì cần parse.
                    # Ở đây giả định history có lưu items_json
                    
                    st.info("Đang quét dữ liệu lịch sử...")
                    # Demo logic: Hiển thị các báo giá gần nhất
                    if all_hist:
                        df_hist_show = pd.DataFrame(all_hist)
                        st.dataframe(df_hist_show[['quote_id', 'customer_name', 'created_at', 'total_profit_vnd']])
                    else:
                        st.warning("Không tìm thấy dữ liệu lịch sử.")
                else:
                    st.error("File thiếu cột Specs")

# -----------------------------------------------------------------------------
# TAB 4: QUẢN LÝ PO (TÁCH FILE V4800)
# -----------------------------------------------------------------------------
elif menu == "📑 QUẢN LÝ PO":
    st.markdown("## 📑 QUẢN LÝ ĐƠN HÀNG (PO)")
    
    t_cust, t_supp = st.tabs(["📥 NHẬN PO KHÁCH", "📤 TÁCH PO NHÀ CUNG CẤP"])
    
    with t_cust:
        st.caption("Upload PO Khách -> Lưu Drive -> Tracking")
        po_c = st.file_uploader("File PO Khách", key="u_poc")
        n_c = st.text_input("Tên Khách", key="n_poc")
        v_c = st.number_input("Giá trị PO", step=1000.0)
        
        if po_c and n_c and st.button("Lưu PO Khách"):
            m = datetime.now().strftime("%b").upper()
            y = datetime.now().year
            link, path = backend.upload_recursive(po_c, po_c.name, "PO_KHACH_HANG", y, n_c, m)
            if link:
                pid = f"PO-C-{int(time.time())}"
                backend.supabase.table("db_customer_orders").insert({
                    "po_number": pid, "customer_name": n_c, "total_value": v_c,
                    "po_file_url": link, "drive_folder_url": path, "status": "Ordered"
                }).execute()
                st.success(f"Thành công! {path}")

    with t_supp:
        st.caption("Tính năng V4800: Tách 1 file Excel tổng thành nhiều file NCC")
        po_m = st.file_uploader("Upload Excel Tổng", type=['xlsx'])
        
        if po_m and st.button("Phân tích"):
            df_m = pd.read_excel(po_m)
            df_m.columns = [str(c).strip() for c in df_m.columns]
            # Tách
            sup_col = next((c for c in df_m.columns if 'supplier' in c.lower() or 'ncc' in c.lower()), None)
            if sup_col:
                gr = df_m.groupby(sup_col)
                for sup, frame in gr:
                    with st.expander(f"📦 NCC: {sup}"):
                        st.dataframe(frame)
                        if st.button(f"Lưu PO {sup}"):
                            buf = io.BytesIO()
                            with pd.ExcelWriter(buf) as w: frame.to_excel(w, index=False)
                            m = datetime.now().strftime("%b").upper()
                            y = datetime.now().year
                            l, p = backend.upload_recursive(buf, f"PO_{sup}.xlsx", "PO_NCC", y, sup, m)
                            if l:
                                backend.supabase.table("db_supplier_orders").insert({
                                    "po_number": f"PO-S-{int(time.time())}", "supplier_name": sup,
                                    "po_file_url": l, "drive_folder_url": p, "status": "Ordered"
                                }).execute()
                                st.success("Đã lưu!")
            else: st.error("Không tìm thấy cột Supplier/NCC")

# -----------------------------------------------------------------------------
# TAB 5: TRACKING
# -----------------------------------------------------------------------------
elif menu == "🚚 VẬN ĐƠN (TRACKING)":
    st.markdown("## 🚚 THEO DÕI VẬN ĐƠN")
    
    pos = backend.supabase.table("db_customer_orders").select("*").order("created_at", desc=True).execute()
    df_pos = pd.DataFrame(pos.data)
    
    if not df_pos.empty:
        st.dataframe(df_pos[['po_number', 'customer_name', 'status', 'drive_folder_url']])
        
        c1, c2, c3 = st.columns(3)
        sel = c1.selectbox("Chọn PO", df_pos['po_number'])
        stt = c2.selectbox("Trạng thái", ["Shipping", "Arrived", "Delivered"])
        prf = c3.file_uploader("Proof Image", type=['jpg','png'])
        
        if st.button("Cập nhật"):
            backend.supabase.table("db_customer_orders").update({"status": stt}).eq("po_number", sel).execute()
            if prf:
                backend.upload_recursive(prf, f"Proof_{sel}.jpg", "TRACKING_PROOF", "2025", "PROOF", "ALL")
            
            # Logic V4800: Delivered -> Payment Pending
            if stt == "Delivered":
                eta = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                backend.supabase.table("crm_payments").insert({
                    "po_number": sel, "status": "Pending", "eta_payment": eta
                }).execute()
                st.info("Đã tạo lịch thanh toán.")
            st.success("Updated!")
    else: st.info("Chưa có dữ liệu.")

# -----------------------------------------------------------------------------
# TAB 6: MASTER DATA
# -----------------------------------------------------------------------------
elif menu == "⚙️ MASTER DATA":
    st.markdown("## ⚙️ DỮ LIỆU GỐC")
    
    st.info("Cập nhật giá vốn (Buying Price)")
    up = st.file_uploader("Upload Excel", type=['xlsx'])
    
    if up and st.button("Cập nhật"):
        df = pd.read_excel(up)
        df.columns = [str(c).lower().strip() for c in df.columns]
        recs = []
        for _, r in df.iterrows():
            p = r.get('buying price\n(rmb)', 0) or r.get('buying price (rmb)', 0)
            recs.append({
                "specs": str(r.get('specs', '')).strip(),
                "buying_price_rmb": float(p) if pd.notnull(p) else 0,
                "supplier_name": str(r.get('supplier', 'Unknown')),
                "exchange_rate": 3600
            })
        backend.supabase.table("crm_purchases").insert(recs).execute()
        st.success("Xong!")
