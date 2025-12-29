# =============================================================================
# CRM SYSTEM - FULL VERSION PREMIER
# APP_VERSION = "V7001 - FINAL SPECS STANDARD & FULL FEATURES"
# Dựa trên: TECHNICAL SPECS FOR CRM SYSTEM.docx [cite: 1] & BACKUP V6091
# =============================================================================

import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import re
import json
from datetime import datetime, timedelta

# Import thư viện xử lý nâng cao
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
    import openpyxl 
except ImportError:
    st.error("⚠️ HỆ THỐNG THIẾU THƯ VIỆN. Vui lòng chạy lệnh cài đặt sau trong Terminal:")
    st.code("pip install streamlit pandas numpy supabase google-api-python-client google-auth-oauthlib python-docx xlsxwriter openpyxl")
    st.stop()

# =============================================================================
# 1. CẤU HÌNH HỆ THỐNG & GIAO DIỆN (UI/UX) - GIỮ NGUYÊN LAYOUT V6091
# =============================================================================
st.set_page_config(
    page_title="CRM SYSTEM V-FINAL PRO", 
    layout="wide", 
    page_icon="💎",
    initial_sidebar_state="expanded"
)

# CSS Customization: Giữ nguyên style "Card 3D" và màu sắc đặc trưng
st.markdown("""
    <style>
    /* Main Layout */
    .main { background-color: #0e1117; }
    
    /* Button Style High-End */
    div.stButton > button { 
        width: 100%; 
        border-radius: 8px; 
        font-weight: 700; 
        background-color: #262730; 
        color: #ffffff; 
        border: 1px solid #4e4e4e;
        padding: 10px 24px;
        transition: all 0.3s;
    }
    div.stButton > button:hover {
        background-color: #4CAF50;
        color: #ffffff;
        border-color: #ffffff;
        box-shadow: 0 4px 8px rgba(0,255,0,0.2);
    }
    
    /* 3D Cards for Dashboard */
    .card-sales { 
        background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); 
        padding: 20px; border-radius: 15px; color: white; 
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        text-align: center;
        margin-bottom: 20px;
    }
    .card-cost { 
        background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); 
        padding: 20px; border-radius: 15px; color: white; 
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        text-align: center;
        margin-bottom: 20px;
    }
    .card-profit { 
        background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); 
        padding: 20px; border-radius: 15px; color: white; 
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        text-align: center;
        margin-bottom: 20px;
    }
    .card-title { font-size: 1.2rem; opacity: 0.9; font-weight: 600; }
    .card-value { font-size: 2.5rem; font-weight: 800; margin-top: 10px; }
    
    /* Input Fields */
    .stTextInput > div > div > input { border-radius: 5px; }
    
    /* Tab Headers */
    button[data-baseweb="tab"] { font-size: 16px !important; font-weight: 700 !important; }
    </style>
""", unsafe_allow_html=True)

# Khởi tạo Session State để lưu trữ dữ liệu tạm thời
if 'quote_data' not in st.session_state: st.session_state['quote_data'] = None
if 'po_processing_data' not in st.session_state: st.session_state['po_processing_data'] = None

# =============================================================================
# 2. CORE LOGIC & UTILS (XỬ LÝ NGHIỆP VỤ PHỨC TẠP)
# =============================================================================

class CRMBackend:
    def __init__(self):
        self.supabase = self.connect_supabase()
        self.drive_service = self.connect_google_drive()

    def connect_supabase(self):
        try:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"]["key"]
            return create_client(url, key)
        except Exception as e:
            st.error(f"❌ LỖI KẾT NỐI SUPABASE: {e}")
            return None

    def connect_google_drive(self):
        try:
            oauth_info = st.secrets["google_oauth"]
            creds = Credentials(None, refresh_token=oauth_info["refresh_token"],
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=oauth_info["client_id"], client_secret=oauth_info["client_secret"])
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"❌ LỖI KẾT NỐI GOOGLE DRIVE: {e}")
            return None

    # --- GOOGLE DRIVE: RECURSIVE FOLDER STRATEGY (Theo Specs [cite: 66, 71]) ---
    def get_folder_id(self, folder_name, parent_id):
        try:
            query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive_service.files().list(q=query, fields="files(id)").execute().get('files', [])
            if results: return results[0]['id']
            # Create if not exists
            meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
            folder = self.drive_service.files().create(body=meta, fields='id').execute()
            return folder.get('id')
        except: return None

    def upload_to_drive_structured(self, file_obj, filename, root_type, year, entity_name, month):
        """
        Upload file vào cấu trúc: ROOT / NĂM / ĐỐI TƯỢNG / THÁNG
        root_type: 'PO_NCC' hoặc 'PO_KHACH_HANG'
        """
        if not self.drive_service: return None, "Service Error"
        
        root_id = st.secrets["google_oauth"].get("root_folder_id")
        
        # 1. Level 1: Root Type
        l1_id = self.get_folder_id(root_type, root_id)
        # 2. Level 2: Year
        l2_id = self.get_folder_id(str(year), l1_id)
        # 3. Level 3: Entity (Customer/Supplier Name)
        clean_entity = re.sub(r'[\\/*?:"<>|]', "", str(entity_name).upper().strip())
        l3_id = self.get_folder_id(clean_entity, l2_id)
        # 4. Level 4: Month
        l4_id = self.get_folder_id(str(month).upper(), l3_id)
        
        # Upload
        media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream', resumable=True)
        file_meta = {'name': filename, 'parents': [l4_id]}
        file = self.drive_service.files().create(body=file_meta, media_body=media, fields='id, webViewLink').execute()
        
        return file.get('webViewLink'), f"{root_type}/{year}/{clean_entity}/{month}/{filename}"

    # --- LOGIC TÍNH TOÁN LỢI NHUẬN (CHUẨN FILE SPECS [cite: 30-45]) ---
    def calculate_profit_row(self, row):
        try:
            qty = float(row.get("Q'ty", 0))
            buy_rmb = float(row.get('Buying Price (RMB)', 0))
            rate = float(row.get('Exchange Rate', 3600))
            
            # 1. Giá vốn hàng bán
            buy_vnd = buy_rmb * rate
            total_buy_vnd = buy_vnd * qty
            
            # 2. AP Price (Nếu ko nhập thì tự tính x2)
            user_ap = float(row.get('AP Price (VND)', 0))
            if user_ap > 0: ap_total = user_ap * qty
            else: ap_total = total_buy_vnd * 2
            
            # 3. GAP
            gap = 0.10 * ap_total
            
            # 4. Giá bán
            total_price = ap_total + gap
            unit_price = total_price / qty if qty > 0 else 0
            
            # 5. Chi phí & Thuế
            val_end = 0.10 * ap_total
            val_buyer = 0.05 * total_price
            val_tax = 0.10 * total_buy_vnd
            val_vat = 0.10 * total_price
            val_mgmt = 0.10 * total_price
            cost_trans = 30000
            
            # 6. Payback
            val_payback = 0.40 * gap
            
            # 7. PROFIT FINAL
            # Profit = Total Sell - (Total Buy + Costs) + Payback
            total_costs = total_buy_vnd + gap + val_end + val_buyer + val_tax + val_vat + cost_trans + val_mgmt
            profit = total_price - total_costs + val_payback
            
            pct = (profit / total_price * 100) if total_price > 0 else 0
            
            return pd.Series({
                'Buying Price (VND)': buy_vnd,
                'Total Buying (VND)': total_buy_vnd,
                'AP Price (VND)': ap_total/qty if qty else 0,
                'AP Total (VND)': ap_total,
                'GAP': gap,
                'Total Price (VND)': total_price,
                'Unit Price (VND)': unit_price,
                'End User': val_end, 'Buyer': val_buyer, 'Tax': val_tax, 'VAT': val_vat, 'Mgmt': val_mgmt, 'Trans': cost_trans,
                'Payback': val_payback,
                'PROFIT (VND)': profit,
                '% Profit': pct
            })
        except: return pd.Series({'PROFIT (VND)': 0})

    # --- LOGIC TÁCH FILE PO THEO NHÀ CUNG CẤP (THEO SPECS [cite: 64]) ---
    def split_po_by_supplier(self, df_input):
        """
        Nhận vào DataFrame tổng (nhiều item của nhiều NCC).
        Trả về Dictionary: { 'Ten_NCC': DataFrame_cua_NCC_do }
        """
        # Chuẩn hóa tên cột
        df_input.columns = [str(c).strip() for c in df_input.columns]
        
        # Kiểm tra cột Supplier
        # Tìm cột có tên chứa 'Supplier' hoặc 'NCC'
        sup_col = next((c for c in df_input.columns if 'supplier' in c.lower() or 'ncc' in c.lower()), None)
        
        output_dict = {}
        if sup_col:
            unique_suppliers = df_input[sup_col].unique()
            for sup in unique_suppliers:
                if pd.notna(sup):
                    sub_df = df_input[df_input[sup_col] == sup].copy()
                    output_dict[str(sup)] = sub_df
        else:
            # Nếu không có cột Supplier, coi như 1 file chung
            output_dict['Unknown_Supplier'] = df_input
            
        return output_dict

    # --- EXPORT DOCX SPECS (LANDSCAPE) ---
    def create_specs_file(self, df, customer_name):
        doc = Document()
        section = doc.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
        
        head = doc.add_heading(f'TECHNICAL SPECS - {str(customer_name).upper()}', 0)
        head.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph(f'Generated: {datetime.now().strftime("%d/%m/%Y %H:%M")}')
        
        # Columns
        show_cols = ['Specs', "Q'ty", 'Buying Price (VND)', 'Total Buying (VND)', 'AP Price (VND)', 'GAP', 'Payback', 'Total Price (VND)', 'PROFIT (VND)', '% Profit']
        
        t = doc.add_table(rows=1, cols=len(show_cols))
        t.style = 'Table Grid'
        
        # Header
        for i, c in enumerate(show_cols):
            run = t.rows[0].cells[i].paragraphs[0].add_run(c)
            run.font.bold = True
            
        # Body
        for _, row in df.iterrows():
            cells = t.add_row().cells
            for i, c in enumerate(show_cols):
                val = row.get(c, 0)
                if c == "Q'ty": cells[i].text = str(int(val))
                elif c == "% Profit": cells[i].text = f"{val:.1f}%"
                elif isinstance(val, (int, float)): cells[i].text = "{:,.0f}".format(val)
                else: cells[i].text = str(val)
                
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf

# Khởi tạo Backend
backend = CRMBackend()

# =============================================================================
# 3. MAIN APP NAVIGATION (SIDEBAR 6 TABS)
# =============================================================================

st.sidebar.markdown("## 🏢 CRM MANAGEMENT")
st.sidebar.markdown("---")
menu = st.sidebar.radio("CHỨC NĂNG (MODULES):", [
    "📊 DASHBOARD",
    "📦 KHO HÀNG",
    "💰 BÁO GIÁ",
    "📑 QUẢN LÝ PO",
    "🚚 TRACKING",
    "⚙️ MASTER DATA"
])
st.sidebar.markdown("---")
st.sidebar.caption(f"Phiên bản: {st.secrets.get('APP_VERSION', 'V7001-PRO')}")

# =============================================================================
# TAB 1: DASHBOARD [cite: 49-51]
# =============================================================================
if menu == "📊 DASHBOARD":
    st.markdown("## 📊 DASHBOARD TỔNG QUAN")
    
    try:
        # Load Data
        quotes = backend.supabase.table("crm_shared_history").select("total_profit_vnd, status").execute()
        pos = backend.supabase.table("db_customer_orders").select("po_number, total_value, status").execute()
        
        df_q = pd.DataFrame(quotes.data)
        df_p = pd.DataFrame(pos.data)
        
        # Metrics Calculation
        total_profit = df_q['total_profit_vnd'].sum() if not df_q.empty else 0
        total_sales = df_p['total_value'].sum() if not df_p.empty else 0
        count_po = len(df_p)
        count_pending = len(df_p[df_p['status'] != 'Delivered']) if not df_p.empty else 0
        
        # Display 3D Cards
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-sales">
                <div class="card-title">DOANH SỐ (SALES)</div>
                <div class="card-value">{total_sales:,.0f}</div>
                <div>VND</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col2:
            st.markdown(f"""
            <div class="card-cost">
                <div class="card-title">ĐƠN HÀNG (PO)</div>
                <div class="card-value">{count_po}</div>
                <div>Pending: {count_pending}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col3:
            st.markdown(f"""
            <div class="card-profit">
                <div class="card-title">LỢI NHUẬN (PROFIT)</div>
                <div class="card-value">{total_profit:,.0f}</div>
                <div>VND</div>
            </div>
            """, unsafe_allow_html=True)
            
        # Recent Activity Table
        st.divider()
        st.subheader("📋 Hoạt động gần đây")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Báo giá mới nhất")
            if not df_q.empty: st.dataframe(df_q.tail(5), use_container_width=True)
        with c2:
            st.caption("PO mới nhất")
            if not df_p.empty: st.dataframe(df_p.tail(5), use_container_width=True)
            
    except Exception as e:
        st.error(f"Không thể tải dữ liệu Dashboard: {e}")

# =============================================================================
# TAB 2: KHO HÀNG (TRA CỨU & XEM ẢNH) [cite: 52-55]
# =============================================================================
elif menu == "📦 KHO HÀNG":
    st.markdown("## 📦 KHO HÀNG (WAREHOUSE)")
    
    search_txt = st.text_input("🔍 Tra cứu (Nhập Mã Specs, Tên hàng, hoặc Nhà cung cấp):", placeholder="Ví dụ: N610...")
    
    # Load items
    res = backend.supabase.table("crm_purchases").select("*").execute()
    df_items = pd.DataFrame(res.data)
    
    if not df_items.empty:
        if search_txt:
            # Filter logic
            mask = df_items.astype(str).apply(lambda x: x.str.contains(search_txt, case=False)).any(axis=1)
            df_display = df_items[mask]
        else:
            df_display = df_items
        
        st.dataframe(
            df_display, 
            use_container_width=True,
            column_config={
                "image_url": st.column_config.ImageColumn("Ảnh SP"),
                "buying_price_rmb": st.column_config.NumberColumn("Giá Mua (RMB)", format="%.2f"),
                "specs": "Mã Specs"
            }
        )
        st.caption(f"Tìm thấy {len(df_display)} kết quả.")
    else:
        st.info("Kho hàng trống.")

# =============================================================================
# TAB 3: BÁO GIÁ (QUOTATION) - CORE FUNCTION [cite: 56-62]
# =============================================================================
elif menu == "💰 BÁO GIÁ":
    st.markdown("## 💰 TẠO BÁO GIÁ & TÍNH LỢI NHUẬN")
    
    # Workflow
    col_c, col_f = st.columns([1, 2])
    cust_name = col_c.text_input("1. Nhập Tên Khách Hàng")
    rfq_file = col_f.file_uploader("2. Upload File RFQ (Excel/CSV - Yêu cầu cột Specs, Q'ty)", type=['xlsx', 'csv'])
    
    if rfq_file and cust_name:
        # Load & Merge
        if st.session_state['quote_data'] is None:
            if rfq_file.name.endswith('.csv'): df_rfq = pd.read_csv(rfq_file)
            else: df_rfq = pd.read_excel(rfq_file)
            
            # Clean Headers
            df_rfq.columns = [str(c).strip() for c in df_rfq.columns]
            
            # Get DB
            db_res = backend.supabase.table("crm_purchases").select("specs, buying_price_rmb, exchange_rate").execute()
            df_db = pd.DataFrame(db_res.data)
            
            # Merge Logic
            if 'Specs' in df_rfq.columns:
                if not df_db.empty:
                    df_rfq['Specs'] = df_rfq['Specs'].astype(str).str.strip()
                    df_db['specs'] = df_db['specs'].astype(str).str.strip()
                    merged = pd.merge(df_rfq, df_db, left_on='Specs', right_on='specs', how='left')
                    merged.rename(columns={'buying_price_rmb': 'Buying Price (RMB)', 'exchange_rate': 'Exchange Rate'}, inplace=True)
                    merged.fillna(0, inplace=True)
                    merged['Exchange Rate'].replace(0, 3600, inplace=True)
                    merged['AP Price (VND)'] = 0 # Cột cho user nhập
                    st.session_state['quote_data'] = merged
                else:
                    st.session_state['quote_data'] = df_rfq
            else:
                st.error("File RFQ thiếu cột 'Specs'. Vui lòng kiểm tra lại file.")
        
        # Editor
        st.info("👇 Bảng dữ liệu bên dưới cho phép chỉnh sửa trực tiếp (Số lượng, Giá AP...).")
        edited_df = st.data_editor(st.session_state['quote_data'], num_rows="dynamic", key="q_editor", use_container_width=True)
        
        # Action Buttons
        c_calc, c_reset = st.columns([1, 4])
        if c_calc.button("🚀 TÍNH TOÁN NGAY"):
            with st.spinner("Đang chạy công thức lợi nhuận..."):
                res_cols = edited_df.apply(backend.calculate_profit_row, axis=1)
                final_df = pd.concat([edited_df, res_cols], axis=1)
                st.session_state['quote_data'] = final_df
                st.success("Tính toán hoàn tất!")
        
        if c_reset.button("Làm mới"):
            st.session_state['quote_data'] = None
            st.experimental_rerun()
            
        # Display Result
        if 'PROFIT (VND)' in st.session_state['quote_data'].columns:
            final_df = st.session_state['quote_data']
            st.divider()
            st.subheader("KẾT QUẢ TÍNH TOÁN CHI TIẾT")
            
            # Highlight Profit columns
            st.dataframe(
                final_df.style.format("{:,.0f}", subset=['PROFIT (VND)', 'Total Price (VND)', 'GAP'])
                .background_gradient(subset=['PROFIT (VND)'], cmap='RdYlGn'),
                use_container_width=True
            )
            
            # Summary
            total_profit = final_df['PROFIT (VND)'].sum()
            st.markdown(f"### TỔNG LỢI NHUẬN DỰ KIẾN: :green[{total_profit:,.0f} VND]")
            
            # Export Zone
            st.write("---")
            st.write("#### Xuất file & Lưu trữ")
            xc1, xc2, xc3 = st.columns(3)
            
            # 1. Docs
            docx_bytes = backend.create_specs_file(final_df, cust_name)
            xc1.download_button("📄 Tải Specs (.docx)", docx_bytes, f"Specs_{cust_name}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            
            # 2. Excel
            buf_xl = io.BytesIO()
            with pd.ExcelWriter(buf_xl, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, sheet_name='Quotation')
            xc2.download_button("📊 Tải Excel (.xlsx)", buf_xl.getvalue(), f"Quote_{cust_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            # 3. Save DB
            if xc3.button("💾 Lưu vào Hệ thống"):
                qid = f"Q-{int(time.time())}"
                backend.supabase.table("crm_shared_history").insert({
                    "quote_id": qid, "customer_name": cust_name,
                    "total_profit_vnd": total_profit, "status": "Quote Sent"
                }).execute()
                st.success(f"Đã lưu thành công! ID: {qid}")

# =============================================================================
# TAB 4: QUẢN LÝ PO - ĐẦY ĐỦ TÍNH NĂNG TÁCH FILE [cite: 63-71]
# =============================================================================
elif menu == "📑 QUẢN LÝ PO":
    st.markdown("## 📑 QUẢN LÝ ĐƠN ĐẶT HÀNG (PO)")
    
    tab_cust, tab_supp = st.tabs(["📥 PO KHÁCH HÀNG (IN)", "📤 PO NHÀ CUNG CẤP (OUT)"])
    
    # --- 1. PO KHÁCH HÀNG ---
    with tab_cust:
        st.subheader("Tiếp nhận PO từ Khách hàng")
        po_c_file = st.file_uploader("Upload File PO Khách (PDF/Excel)", key="u_po_c")
        c_name = st.text_input("Tên Khách Hàng", key="n_po_c")
        val_po = st.number_input("Tổng giá trị PO (VND)", min_value=0.0, step=1000.0, format="%.0f")
        
        if po_c_file and c_name and st.button("Lưu & Upload PO Khách"):
            with st.spinner("Đang upload lên Google Drive..."):
                month = datetime.now().strftime("%b").upper()
                year = datetime.now().year
                
                link, path = backend.upload_to_drive_structured(po_c_file, po_c_file.name, "PO_KHACH_HANG", year, c_name, month)
                
                if link:
                    po_id = f"PO-C-{int(time.time())}"
                    backend.supabase.table("db_customer_orders").insert({
                        "po_number": po_id, "customer_name": c_name, 
                        "po_file_url": link, "drive_folder_url": path, "status": "Ordered", "total_value": val_po
                    }).execute()
                    
                    # Auto Tracking
                    backend.supabase.table("crm_tracking").insert({"po_number": po_id, "step": "Ordered"}).execute()
                    
                    st.success(f"✅ Đã lưu PO Khách thành công!\n📁 Đường dẫn Drive: {path}")
                else:
                    st.error("Lỗi Upload.")

    # --- 2. PO NHÀ CUNG CẤP (CHỨC NĂNG TÁCH FILE CAO CẤP) ---
    with tab_supp:
        st.subheader("Xử lý Đặt hàng Nhà Cung Cấp (PO Supplier)")
        st.info("💡 Chức năng: Upload 1 file tổng -> Hệ thống tự tách thành nhiều file Excel cho từng NCC -> Upload Drive.")
        
        po_master_file = st.file_uploader("Upload File Đặt Hàng Tổng (Excel)", type=['xlsx'])
        
        if po_master_file:
            if st.button("Phân tích & Tách PO"):
                try:
                    df_master = pd.read_excel(po_master_file)
                    # Gọi hàm tách
                    split_dict = backend.split_po_by_supplier(df_master)
                    st.session_state['po_processing_data'] = split_dict
                    st.success(f"Đã tách thành {len(split_dict)} nhà cung cấp!")
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")
        
        # Hiển thị kết quả tách & Nút Upload
        if st.session_state['po_processing_data']:
            split_dict = st.session_state['po_processing_data']
            
            for sup_name, df_sub in split_dict.items():
                with st.expander(f"📦 Nhà cung cấp: {sup_name} ({len(df_sub)} items)"):
                    st.dataframe(df_sub)
                    
                    if st.button(f"Xuất & Lưu PO cho {sup_name}", key=f"btn_{sup_name}"):
                        # 1. Tạo Excel trong bộ nhớ
                        out_buffer = io.BytesIO()
                        with pd.ExcelWriter(out_buffer, engine='xlsxwriter') as writer:
                            df_sub.to_excel(writer, index=False)
                        out_buffer.seek(0)
                        
                        # 2. Upload Drive
                        month = datetime.now().strftime("%b").upper()
                        year = datetime.now().year
                        file_name = f"PO_{sup_name}_{int(time.time())}.xlsx"
                        
                        link, path = backend.upload_to_drive_structured(out_buffer, file_name, "PO_NCC", year, sup_name, month)
                        
                        if link:
                            # 3. Save DB
                            po_s_id = f"PO-S-{int(time.time())}"
                            backend.supabase.table("db_supplier_orders").insert({
                                "po_number": po_s_id, "supplier_name": sup_name,
                                "po_file_url": link, "drive_folder_url": path, "status": "Ordered"
                            }).execute()
                            st.success(f"✅ Đã tạo PO cho {sup_name} thành công!")

# =============================================================================
# TAB 5: TRACKING & PAYMENT [cite: 72-80]
# =============================================================================
elif menu == "🚚 TRACKING":
    st.markdown("## 🚚 THEO DÕI VẬN ĐƠN & THANH TOÁN")
    
    # Load List PO
    pos = backend.supabase.table("db_customer_orders").select("*").order("created_at", desc=True).execute()
    df_pos = pd.DataFrame(pos.data)
    
    if not df_pos.empty:
        st.dataframe(df_pos[['po_number', 'customer_name', 'status', 'drive_folder_url', 'created_at']])
        
        st.divider()
        st.subheader("Cập nhật Trạng Thái (Tracking Update)")
        
        tc1, tc2, tc3 = st.columns(3)
        sel_po = tc1.selectbox("Chọn Mã PO", df_pos['po_number'])
        new_stat = tc2.selectbox("Trạng thái Mới", ["Shipping", "Arrived", "Delivered"])
        proof = tc3.file_uploader("Ảnh Bằng Chứng (Proof Image)", type=['jpg', 'png'])
        
        if st.button("Cập nhật Tracking"):
            # Update Status in DB
            backend.supabase.table("db_customer_orders").update({"status": new_stat}).eq("po_number", sel_po).execute()
            
            # Upload Proof
            proof_link = None
            if proof:
                proof_link, _ = backend.upload_to_drive_structured(proof, f"PROOF_{sel_po}.jpg", "TRACKING_PROOF", "2025", "PROOF", "ALL")
            
            # Insert Tracking History
            backend.supabase.table("crm_tracking").insert({
                "po_number": sel_po, "step": new_stat, "proof_image_url": proof_link
            }).execute()
            
            # AUTOMATION: Delivered -> Payment [cite: 75]
            if new_stat == "Delivered":
                eta_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                backend.supabase.table("crm_payments").insert({
                    "po_number": sel_po, "customer_name": df_pos[df_pos['po_number']==sel_po]['customer_name'].values[0],
                    "status": "Pending", "eta_payment": eta_date
                }).execute()
                st.info(f"🔔 Hệ thống tự động tạo lịch thanh toán (ETA: {eta_date})")
                
            st.success("Cập nhật trạng thái thành công!")
            
    else:
        st.info("Chưa có đơn hàng nào.")
        
    st.divider()
    st.subheader("📅 Lịch Thanh Toán (Payment Schedule)")
    pays = backend.supabase.table("crm_payments").select("*").execute()
    if pays.data:
        st.dataframe(pd.DataFrame(pays.data))

# =============================================================================
# TAB 6: MASTER DATA [cite: 82-89]
# =============================================================================
elif menu == "⚙️ MASTER DATA":
    st.markdown("## ⚙️ QUẢN LÝ DỮ LIỆU GỐC")
    
    st.write("### 1. Cập nhật Giá Mua (Buying Price List)")
    st.info("Upload file Excel 'BUYING PRICE-ALL-OK.xlsx' để cập nhật giá vốn.")
    
    up_file = st.file_uploader("Chọn file Excel", type=['xlsx'])
    
    if up_file and st.button("Bắt đầu Import"):
        try:
            df = pd.read_excel(up_file)
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            records = []
            for _, row in df.iterrows():
                # Logic map cột linh hoạt
                p = row.get('buying price\n(rmb)', 0) or row.get('buying price (rmb)', 0)
                
                records.append({
                    "specs": str(row.get('specs', '')).strip(),
                    "buying_price_rmb": float(p) if pd.notnull(p) else 0,
                    "supplier_name": str(row.get('supplier', 'Unknown')),
                    "exchange_rate": 3600
                })
            
            # Insert Batch
            backend.supabase.table("crm_purchases").insert(records).execute()
            st.success(f"✅ Đã import thành công {len(records)} mã hàng!")
            
        except Exception as e:
            st.error(f"Lỗi Import: {e}")
            
    st.divider()
    st.write("### 2. Danh sách Khách Hàng (Customers)")
    # Placeholder for Customer Management
    custs = backend.supabase.table("db_customer_orders").select("customer_name").execute()
    if custs.data:
        unique_custs = list(set([x['customer_name'] for x in custs.data]))
        st.write(f"Khách hàng hiện có: {', '.join(unique_custs)}")
