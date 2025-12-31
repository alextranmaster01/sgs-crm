# =============================================================================
# CRM SYSTEM - HYBRID V4800 ONLINE
# SOURCE CODE: MERGED V4800 (LOGIC/UI STD) + V6023 (CLOUD BACKEND)
# =============================================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import re
from datetime import datetime, timedelta

# --- THƯ VIỆN BACKEND (V6023) ---
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
    st.error("⚠️ Thiếu thư viện! Vui lòng cài đặt theo file requirements.txt")
    st.stop()

# =============================================================================
# 1. GIAO DIỆN SẮC MÀU (CHUẨN V4800 PORTED TO WEB)
# =============================================================================
st.set_page_config(page_title="CRM PRO V4800-ONLINE", layout="wide", page_icon="🌈")

# CSS mô phỏng giao diện "Sắc màu" của bản Offline V4800
st.markdown("""
    <style>
    /* Main Background */
    .stApp { background-color: #f0f2f6; }
    
    /* Button Styles - Mô phỏng nút bấm nổi của Tkinter nhưng hiện đại hơn */
    div.stButton > button { 
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        color: white; 
        font-weight: bold; 
        border: none; 
        border-radius: 8px; 
        padding: 10px 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 8px rgba(0,0,0,0.3);
    }
    
    /* Card Styles for Dashboard */
    .card-box {
        border-radius: 15px;
        padding: 20px;
        color: white;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
    }
    .bg-gradient-1 { background: linear-gradient(135deg, #FF512F, #DD2476); } /* Sales */
    .bg-gradient-2 { background: linear-gradient(135deg, #11998e, #38ef7d); } /* Profit */
    .bg-gradient-3 { background: linear-gradient(135deg, #C6FFDD, #FBD786, #f7797d); color: #333; } /* Orders */
    
    /* Table Styling */
    [data-testid="stDataFrame"] { border: 2px solid #4b6cb7; border-radius: 10px; }
    
    /* Headers */
    h1, h2, h3 { color: #182848; font-family: 'Arial Black', sans-serif; }
    </style>
""", unsafe_allow_html=True)

# Session State
if 'quote_data' not in st.session_state: st.session_state['quote_data'] = None
if 'po_split_data' not in st.session_state: st.session_state['po_split_data'] = None

# =============================================================================
# 2. BACKEND LOGIC (V6023 CONNECTORS + V4800 ALGORITHMS)
# =============================================================================

class CRMBackend:
    def __init__(self):
        self.supabase = self.connect_supabase()
        self.drive_service = self.connect_google_drive()

    # --- KẾT NỐI (V6023) ---
    def connect_supabase(self):
        try:
            return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        except: return None

    def connect_google_drive(self):
        try:
            info = st.secrets["google_oauth"]
            creds = Credentials(None, refresh_token=info["refresh_token"],
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=info["client_id"], client_secret=info["client_secret"])
            return build('drive', 'v3', credentials=creds)
        except: return None

    # --- XỬ LÝ DRIVE ĐỆ QUY (V6023) ---
    def get_folder_id(self, name, parent_id):
        try:
            q = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            files = self.drive_service.files().list(q=q, fields="files(id)").execute().get('files', [])
            if files: return files[0]['id']
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
            return self.drive_service.files().create(body=meta, fields='id').execute().get('id')
        except: return None

    def upload_recursive(self, file_obj, filename, root_type, year, entity, month):
        if not self.drive_service: return None, "Lỗi kết nối Drive"
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            l1 = self.get_folder_id(root_type, root_id)
            l2 = self.get_folder_id(str(year), l1)
            clean_name = re.sub(r'[\\/*?:"<>|]', "", str(entity).upper().strip())
            l3 = self.get_folder_id(clean_name, l2)
            l4 = self.get_folder_id(str(month).upper(), l3)
            
            media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream', resumable=True)
            meta = {'name': filename, 'parents': [l4]}
            f = self.drive_service.files().create(body=meta, media_body=media, fields='webViewLink').execute()
            return f.get('webViewLink'), f"{root_type}/{year}/{clean_name}/{month}/{filename}"
        except Exception as e: return None, str(e)

    # --- THUẬT TOÁN TÍNH LỢI NHUẬN (TUYỆT ĐỐI CHUẨN V4800) ---
    def calculate_profit_v4800(self, row):
        try:
            # Lấy dữ liệu đầu vào
            qty = float(row.get("Q'ty", 0))
            buy_rmb = float(row.get('Buying Price (RMB)', 0))
            rate = float(row.get('Exchange Rate', 3600))
            
            # 1. Tính Giá Vốn (Buying Price VND)
            buy_vnd = buy_rmb * rate
            total_buy = buy_vnd * qty
            
            # 2. Tính AP Price (Theo quy tắc V4800: Nếu ko nhập thì mặc định x2 Buying)
            user_ap = float(row.get('AP Price (VND)', 0))
            if user_ap > 0:
                ap_total = user_ap * qty
            else:
                ap_total = total_buy * 2
            
            # 3. Tính GAP (10% AP Total)
            gap = 0.10 * ap_total
            
            # 4. Tính Giá Bán (Total Sell = AP + GAP)
            total_price = ap_total + gap
            unit_price = total_price / qty if qty > 0 else 0
            
            # 5. Các chi phí (Theo tỷ lệ cố định của V4800)
            val_end = 0.10 * ap_total       # End User
            val_buyer = 0.05 * total_price  # Buyer
            val_tax = 0.10 * total_buy      # Import Tax
            val_vat = 0.10 * total_price    # VAT
            val_mgmt = 0.10 * total_price   # Management Fee
            trans = 30000                   # Phí vận chuyển cố định
            
            # 6. Payback (40% GAP)
            val_payback = 0.40 * gap
            
            # 7. Lợi Nhuận Cuối (Profit = Price - Costs + Payback)
            total_costs = total_buy + gap + val_end + val_buyer + val_tax + val_vat + trans + val_mgmt
            profit = total_price - total_costs + val_payback
            
            pct = (profit / total_price * 100) if total_price > 0 else 0
            
            # Trả về Series đúng chuẩn cột của V4800
            return pd.Series({
                'Buying Price (VND)': buy_vnd,
                'Total Buying (VND)': total_buy,
                'AP Price (VND)': ap_total/qty if qty else 0,
                'AP Total (VND)': ap_total,
                'GAP': gap,
                'Total Price (VND)': total_price,
                'Unit Price (VND)': unit_price,
                'End User': val_end, 'Buyer': val_buyer, 'Import Tax': val_tax, 
                'VAT': val_vat, 'Mgmt Fee': val_mgmt, 'Transportation': trans,
                'Payback': val_payback,
                'PROFIT (VND)': profit,
                '% Profit': pct
            })
        except: return pd.Series({'PROFIT (VND)': 0})

    # --- TÁCH FILE PO (LOGIC V4800 PORTED TO WEB) ---
    def split_po_logic(self, df):
        # Chuẩn hóa tên cột để tránh lỗi
        df.columns = [str(c).strip() for c in df.columns]
        # Tìm cột Supplier
        sup_col = next((c for c in df.columns if 'supplier' in c.lower() or 'ncc' in c.lower()), None)
        res = {}
        if sup_col:
            for s in df[sup_col].unique():
                if pd.notna(s): res[str(s)] = df[df[sup_col] == s]
        return res

    # --- XUẤT DOCX (ĐỊNH DẠNG NGANG V4800) ---
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
        
        # Header
        for i, c in enumerate(cols):
            run = t.rows[0].cells[i].paragraphs[0].add_run(c)
            run.font.bold = True
            
        # Data
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
# 3. ĐIỀU HƯỚNG & CÁC TAB CHỨC NĂNG (MÔ PHỎNG TAB VIEW V4800)
# =============================================================================

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/906/906343.png", width=100)
    st.title("CRM V4800 ONLINE")
    st.write("---")
    menu = st.radio("CHỨC NĂNG CHÍNH", [
        "📊 DASHBOARD", 
        "📦 KHO HÀNG (INVENTORY)", 
        "💰 BÁO GIÁ (QUOTATION)", 
        "📑 XỬ LÝ PO (PO MANAGER)", 
        "🚚 VẬN ĐƠN (TRACKING)",
        "⚙️ DỮ LIỆU GỐC (MASTER)"
    ])
    st.write("---")
    st.info("Phiên bản Online 100% - Bảo mật OAuth2")

# --- TAB 1: DASHBOARD (GIAO DIỆN SẮC MÀU) ---
if menu == "📊 DASHBOARD":
    st.markdown("## 📊 TỔNG QUAN KINH DOANH")
    
    try:
        # Load Data Live từ Supabase
        q_data = backend.supabase.table("crm_shared_history").select("total_profit_vnd").execute().data
        p_data = backend.supabase.table("db_customer_orders").select("total_value, po_number").execute().data
        
        df_q = pd.DataFrame(q_data)
        df_p = pd.DataFrame(p_data)
        
        profit = df_q['total_profit_vnd'].sum() if not df_q.empty else 0
        sales = df_p['total_value'].sum() if not df_p.empty else 0
        orders = len(df_p)
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="card-box bg-gradient-1"><h3>DOANH SỐ</h3><h1>{sales:,.0f}</h1></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="card-box bg-gradient-2"><h3>LỢI NHUẬN</h3><h1>{profit:,.0f}</h1></div>', unsafe_allow_html=True)
        c3.markdown(f'<div class="card-box bg-gradient-3"><h3>ĐƠN HÀNG</h3><h1>{orders}</h1></div>', unsafe_allow_html=True)
        
        st.divider()
        st.subheader("📈 Biểu đồ hiệu suất")
        if not df_q.empty:
            st.line_chart(df_q['total_profit_vnd'])
            
    except Exception as e: st.error(f"Lỗi tải dữ liệu: {e}")

# --- TAB 2: KHO HÀNG (TRA CỨU V4800) ---
elif menu == "📦 KHO HÀNG (INVENTORY)":
    st.markdown("## 📦 TRA CỨU TỒN KHO & GIÁ VỐN")
    search = st.text_input("🔍 Tìm kiếm (Mã Specs, Tên hàng, NCC)...", placeholder="Nhập từ khóa...")
    
    res = backend.supabase.table("crm_purchases").select("*").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        if search:
            mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)
            df = df[mask]
        
        st.dataframe(df, use_container_width=True, height=500)
    else: st.info("Kho hàng trống.")

# --- TAB 3: BÁO GIÁ (TÍNH TOÁN THEO V4800) ---
elif menu == "💰 BÁO GIÁ (QUOTATION)":
    st.markdown("## 💰 LẬP BÁO GIÁ CHI TIẾT")
    
    c1, c2 = st.columns([1,2])
    cust = c1.text_input("Tên Khách Hàng")
    rfq = c2.file_uploader("Upload RFQ (Excel/CSV)", type=['xlsx','csv'])
    
    if rfq and cust:
        if st.session_state['quote_data'] is None:
            # 1. Đọc file
            df_in = pd.read_csv(rfq) if rfq.name.endswith('.csv') else pd.read_excel(rfq)
            df_in.columns = [str(c).strip() for c in df_in.columns]
            
            # 2. Lấy giá từ Kho
            db = backend.supabase.table("crm_purchases").select("specs, buying_price_rmb, exchange_rate").execute()
            df_db = pd.DataFrame(db.data)
            
            # 3. Ghép file (Merge Logic)
            if 'Specs' in df_in.columns:
                if not df_db.empty:
                    df_in['Specs'] = df_in['Specs'].astype(str).str.strip()
                    df_db['specs'] = df_db['specs'].astype(str).str.strip()
                    merged = pd.merge(df_in, df_db, left_on='Specs', right_on='specs', how='left')
                    merged.rename(columns={'buying_price_rmb': 'Buying Price (RMB)', 'exchange_rate': 'Exchange Rate'}, inplace=True)
                    merged.fillna(0, inplace=True)
                    merged['Exchange Rate'].replace(0, 3600, inplace=True)
                    merged['AP Price (VND)'] = 0 # Cho phép nhập tay
                    st.session_state['quote_data'] = merged
                else: st.session_state['quote_data'] = df_in
            else: st.error("File RFQ thiếu cột 'Specs'")
            
        # 4. Data Editor (Thay thế Treeview của Tkinter)
        st.info("👇 Nhập số lượng/giá vào bảng dưới:")
        edited = st.data_editor(st.session_state['quote_data'], num_rows="dynamic", use_container_width=True)
        
        # 5. Nút Tính Toán (Giao diện Sắc màu)
        col_act1, col_act2 = st.columns([1,4])
        if col_act1.button("🚀 TÍNH LỢI NHUẬN"):
            res = edited.apply(backend.calculate_profit_v4800, axis=1)
            st.session_state['quote_data'] = pd.concat([edited, res], axis=1)
            st.success("Đã tính toán xong theo chuẩn V4800!")
            
        if col_act2.button("🔄 Làm mới"):
            st.session_state['quote_data'] = None
            st.rerun()
            
        # 6. Kết quả & Xuất file
        if 'PROFIT (VND)' in st.session_state['quote_data'].columns:
            final = st.session_state['quote_data']
            st.divider()
            st.dataframe(final.style.format("{:,.0f}", subset=['PROFIT (VND)', 'Total Price (VND)'])
                         .background_gradient(subset=['PROFIT (VND)'], cmap='RdYlGn'), use_container_width=True)
            
            total_profit = final['PROFIT (VND)'].sum()
            st.markdown(f"### TỔNG LỢI NHUẬN: :green[{total_profit:,.0f} VND]")
            
            # Export Buttons
            b1, b2, b3 = st.columns(3)
            docx = backend.export_docx_v4800(final, cust)
            b1.download_button("📄 Tải Specs (.docx)", docx, f"Specs_{cust}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            
            buf = io.BytesIO()
            with pd.ExcelWriter(buf) as w: final.to_excel(w)
            b2.download_button("📊 Tải Excel (.xlsx)", buf.getvalue(), f"Quote_{cust}.xlsx")
            
            if b3.button("💾 Lưu Lịch Sử"):
                qid = f"Q-{int(time.time())}"
                backend.supabase.table("crm_shared_history").insert({
                    "quote_id": qid, "customer_name": cust, "total_profit_vnd": total_profit, "status": "Done"
                }).execute()
                st.success("Đã lưu!")

# --- TAB 4: XỬ LÝ PO (CHỨC NĂNG TÁCH FILE V4800) ---
elif menu == "📑 XỬ LÝ PO (PO MANAGER)":
    st.markdown("## 📑 QUẢN LÝ ĐƠN HÀNG")
    
    t1, t2 = st.tabs(["NHẬN PO KHÁCH", "TÁCH PO NHÀ CUNG CẤP"])
    
    with t1:
        st.subheader("Lưu trữ PO Khách Hàng")
        po_c = st.file_uploader("File PO Khách", key="up1")
        name_c = st.text_input("Tên Khách", key="n1")
        val_c = st.number_input("Giá trị PO", step=1000.0)
        
        if po_c and name_c and st.button("Lưu & Upload"):
            with st.spinner("Đang đẩy lên Google Drive..."):
                m = datetime.now().strftime("%b").upper()
                y = datetime.now().year
                link, path = backend.upload_recursive(po_c, po_c.name, "PO_KHACH_HANG", y, name_c, m)
                
                if link:
                    pid = f"PO-C-{int(time.time())}"
                    backend.supabase.table("db_customer_orders").insert({
                        "po_number": pid, "customer_name": name_c, "total_value": val_c,
                        "po_file_url": link, "drive_folder_url": path, "status": "Ordered"
                    }).execute()
                    st.success(f"Xong! File tại: {path}")
                else: st.error("Lỗi Upload")
                
    with t2:
        st.subheader("Tách File PO Tổng -> Nhiều NCC (Logic V4800)")
        po_master = st.file_uploader("Upload PO Tổng (Excel)", type=['xlsx'], key="up2")
        
        if po_master and st.button("Phân tích & Tách File"):
            df_m = pd.read_excel(po_master)
            split_res = backend.split_po_logic(df_m)
            st.session_state['po_split_data'] = split_res
            st.success(f"Đã tách thành {len(split_res)} nhà cung cấp!")
            
        if st.session_state['po_split_data']:
            for sup, df_s in st.session_state['po_split_data'].items():
                with st.expander(f"📦 NCC: {sup} ({len(df_s)} items)"):
                    st.dataframe(df_s)
                    if st.button(f"Lưu PO {sup}"):
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf) as w: df_s.to_excel(w, index=False)
                        
                        m = datetime.now().strftime("%b").upper()
                        y = datetime.now().year
                        fname = f"PO_{sup}_{int(time.time())}.xlsx"
                        
                        link, path = backend.upload_recursive(buf, fname, "PO_NCC", y, sup, m)
                        if link:
                            backend.supabase.table("db_supplier_orders").insert({
                                "po_number": f"PO-S-{int(time.time())}", "supplier_name": sup,
                                "po_file_url": link, "drive_folder_url": path, "status": "Ordered"
                            }).execute()
                            st.success(f"Đã lưu PO {sup}!")

# --- TAB 5: TRACKING ---
elif menu == "🚚 VẬN ĐƠN (TRACKING)":
    st.markdown("## 🚚 THEO DÕI VẬN ĐƠN")
    
    pos = backend.supabase.table("db_customer_orders").select("*").order("created_at", desc=True).execute()
    df_pos = pd.DataFrame(pos.data)
    
    if not df_pos.empty:
        st.dataframe(df_pos[['po_number', 'customer_name', 'status', 'drive_folder_url']])
        
        c1, c2, c3 = st.columns(3)
        po_sel = c1.selectbox("Chọn PO", df_pos['po_number'])
        stat = c2.selectbox("Trạng thái", ["Shipping", "Arrived", "Delivered"])
        proof = c3.file_uploader("Ảnh Proof", type=['jpg','png'])
        
        if st.button("Cập nhật"):
            backend.supabase.table("db_customer_orders").update({"status": stat}).eq("po_number", po_sel).execute()
            if proof:
                link, _ = backend.upload_recursive(proof, f"Proof_{po_sel}.jpg", "TRACKING_PROOF", "2025", "PROOF", "ALL")
            st.success("Updated!")
    else: st.info("Chưa có đơn hàng.")

# --- TAB 6: MASTER DATA ---
elif menu == "⚙️ DỮ LIỆU GỐC (MASTER)":
    st.markdown("## ⚙️ CẬP NHẬT GIÁ VỐN")
    up = st.file_uploader("Upload Excel Bảng Giá (BUYING PRICE)", type=['xlsx'])
    
    if up and st.button("Cập nhật Database"):
        try:
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
            st.success("Đã cập nhật thành công!")
        except Exception as e: st.error(f"Lỗi: {e}")
