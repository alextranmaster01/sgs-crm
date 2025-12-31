# =============================================================================
# CRM SYSTEM - ULTIMATE HYBRID EDITION (FINAL FIXED)
# UI STANDARD: V4800 (Colorful, 3D Cards, Layout)
# CORE ENGINE: V6023 (Supabase, Google Drive OAuth2 Refresh Token)
# FEATURES: Full Modules (Dashboard, Inventory, Quote, PO, Tracking, Master Data)
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
    st.error("⚠️ Thiếu thư viện. Vui lòng cài đặt file requirements.txt")
    st.stop()

# =============================================================================
# 1. THIẾT LẬP GIAO DIỆN "SẮC MÀU" (CHUẨN V4800)
# =============================================================================
st.set_page_config(
    page_title="CRM V4800 ONLINE PRO", 
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
        transition: transform 0.3s;
    }
    .dashboard-card:hover { transform: scale(1.02); }
    .card-sales { background: linear-gradient(45deg, #FF416C, #FF4B2B); }
    .card-profit { background: linear-gradient(45deg, #00b09b, #96c93d); }
    .card-orders { background: linear-gradient(45deg, #8E2DE2, #4A00E0); }
    
    .card-value { font-size: 32px; font-weight: 800; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
    .card-title { font-size: 16px; font-weight: 600; opacity: 0.9; text-transform: uppercase; }

    /* 4. Image Preview Box */
    .img-preview-box {
        border: 2px dashed #4b6cb7;
        border-radius: 10px;
        padding: 10px;
        text-align: center;
        background-color: white;
        min-height: 200px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    /* 5. Custom Table Style */
    [data-testid="stDataFrame"] { border: 2px solid #000851; border-radius: 8px; }
    
    /* 6. Tabs Style */
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
    </style>
""", unsafe_allow_html=True)

# Khởi tạo Session State
if 'quote_data' not in st.session_state: st.session_state['quote_data'] = None
if 'selected_item_code' not in st.session_state: st.session_state['selected_item_code'] = None

# =============================================================================
# 2. CORE BACKEND (LOGIC V4800 + INFRA V6023 + IMAGE HANDLER)
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

    # --- GOOGLE DRIVE: UPLOAD & IMAGE LINK ---
    def get_folder_id(self, name, parent_id):
        try:
            q = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            files = self.drive_service.files().list(q=q, fields="files(id)").execute().get('files', [])
            if files: return files[0]['id']
            meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
            return self.drive_service.files().create(body=meta, fields='id').execute().get('id')
        except: return None

    def upload_image_to_drive(self, file_obj, filename, item_code):
        """Upload ảnh SP lên Drive và trả về Direct Link"""
        if not self.drive_service: return None
        try:
            root_id = st.secrets["google_oauth"]["root_folder_id"]
            # Cấu trúc: ROOT / PRODUCT_IMAGES / ITEM_CODE
            l1 = self.get_folder_id("PRODUCT_IMAGES", root_id)
            
            media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
            # Lưu ý: parents=[l1] để file nằm trong folder PRODUCT_IMAGES
            meta = {'name': filename, 'parents': [l1]} 
            
            file = self.drive_service.files().create(body=meta, media_body=media, fields='id, webViewLink, thumbnailLink').execute()
            
            # Tạo link hiển thị trực tiếp (Hack link Google Drive để hiển thị trong App)
            file_id = file.get('id')
            direct_link = f"https://drive.google.com/uc?export=view&id={file_id}"
            
            return direct_link
        except Exception as e:
            st.error(f"Upload lỗi: {e}")
            return None

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

    # --- LOGIC TÍNH TOÁN V4800 (GIỮ NGUYÊN) ---
    def calculate_profit_v4800(self, row):
        try:
            qty = float(row.get("Q'ty", 0))
            buy_rmb = float(row.get('Buying Price (RMB)', 0))
            rate = float(row.get('Exchange Rate', 3600))
            
            buy_vnd = buy_rmb * rate
            total_buy = buy_vnd * qty
            
            user_ap = float(row.get('AP Price (VND)', 0))
            ap_total = user_ap * qty if user_ap > 0 else total_buy * 2
            
            gap = 0.10 * ap_total
            total_price = ap_total + gap
            unit_price = total_price / qty if qty > 0 else 0
            
            costs = (total_buy + gap + (0.10 * ap_total) + (0.05 * total_price) + 
                     (0.10 * total_buy) + (0.10 * total_price) + (0.10 * total_price) + 30000)
            
            payback = 0.40 * gap
            profit = total_price - costs + payback
            pct = (profit / total_price * 100) if total_price > 0 else 0
            
            return pd.Series({
                'Buying Price (VND)': buy_vnd, 'Total Buying (VND)': total_buy,
                'AP Price (VND)': ap_total/qty if qty else 0, 'AP Total (VND)': ap_total,
                'GAP': gap, 'Total Price (VND)': total_price, 'Unit Price (VND)': unit_price,
                'PROFIT (VND)': profit, '% Profit': pct
            })
        except: return pd.Series({'PROFIT (VND)': 0})

    # --- EXPORT WORD NGANG ---
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

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/906/906343.png", width=80)
    st.title("CRM V4800 PRO")
    st.markdown("---")
    menu = st.radio("CHỨC NĂNG", [
        "📊 DASHBOARD",
        "📦 KHO HÀNG (IMAGES)", 
        "💰 BÁO GIÁ (QUOTATION)",
        "📑 QUẢN LÝ PO",
        "🚚 VẬN ĐƠN (TRACKING)",
        "⚙️ MASTER DATA"
    ])
    st.markdown("---")
    st.caption("Phiên bản: V4800 Online Ultimate")

# -----------------------------------------------------------------------------
# TAB 1: DASHBOARD
# -----------------------------------------------------------------------------
if menu == "📊 DASHBOARD":
    st.markdown("## 📊 TỔNG QUAN KINH DOANH")
    try:
        q_res = backend.supabase.table("crm_shared_history").select("total_profit_vnd").execute()
        p_res = backend.supabase.table("db_customer_orders").select("total_value").execute()
        
        profit = sum([x['total_profit_vnd'] for x in q_res.data]) if q_res.data else 0
        sales = sum([x['total_value'] for x in p_res.data]) if p_res.data else 0
        orders = len(p_res.data) if p_res.data else 0
        
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(f'<div class="dashboard-card card-sales"><div class="card-title">DOANH SỐ</div><div class="card-value">{sales:,.0f}</div></div>', unsafe_allow_html=True)
        with c2: st.markdown(f'<div class="dashboard-card card-profit"><div class="card-title">LỢI NHUẬN</div><div class="card-value">{profit:,.0f}</div></div>', unsafe_allow_html=True)
        with c3: st.markdown(f'<div class="dashboard-card card-orders"><div class="card-title">ĐƠN HÀNG</div><div class="card-value">{orders}</div></div>', unsafe_allow_html=True)
        
        st.divider()
        st.subheader("Hoạt động gần đây")
        # Placeholder for charts if needed
    except: st.error("Lỗi kết nối Dashboard - Kiểm tra Supabase")

# -----------------------------------------------------------------------------
# TAB 2: KHO HÀNG (TÍNH NĂNG ĐẶC BIỆT: CLICK XEM ẢNH)
# -----------------------------------------------------------------------------
elif menu == "📦 KHO HÀNG (IMAGES)":
    st.markdown("## 📦 TRA CỨU & HÌNH ẢNH SẢN PHẨM")
    
    col_search, col_upload = st.columns([3, 1])
    search = col_search.text_input("🔍 Tìm kiếm (Specs/Tên)...", placeholder="Nhập mã hàng...")
    
    # 1. Load Data
    res = backend.supabase.table("crm_purchases").select("*").execute()
    df = pd.DataFrame(res.data)
    
    if not df.empty:
        # Filter
        if search:
            mask = df.astype(str).apply(lambda x: x.str.contains(search, case=False)).any(axis=1)
            df = df[mask]

        # 2. Layout: Trái (Bảng) - Phải (Ảnh)
        c_table, c_preview = st.columns([7, 3])
        
        with c_table:
            st.caption("💡 Mẹo: Bấm vào một dòng để xem ảnh và upload ảnh mới.")
            # SỬ DỤNG TÍNH NĂNG SELECTION MỚI CỦA STREAMLIT
            event = st.dataframe(
                df,
                use_container_width=True,
                height=600,
                selection_mode="single-row", # Chỉ chọn 1 dòng
                on_select="rerun",           # Chạy lại app để hiển thị ảnh ngay
                column_config={
                    "image_url": st.column_config.LinkColumn("Link Ảnh"),
                    "buying_price_rmb": st.column_config.NumberColumn("Giá RMB", format="%.2f")
                },
                hide_index=True
            )

        # 3. Xử lý Logic Hiển thị & Upload Ảnh
        with c_preview:
            st.markdown("### 🖼️ XEM TRƯỚC ẢNH")
            
            selected_rows = event.selection.rows
            if selected_rows:
                # Lấy dòng được chọn
                idx = selected_rows[0]
                row_data = df.iloc[idx]
                
                item_code = row_data.get('specs', 'N/A')
                current_img = row_data.get('image_url', None)
                record_id = row_data.get('id') # ID trong DB để update
                
                st.info(f"Đang chọn: **{item_code}**")
                
                # A. Hiển thị ảnh (Nếu có)
                if current_img:
                    st.image(current_img, caption=item_code, use_column_width=True)
                else:
                    st.markdown("""<div class="img-preview-box">📵 Chưa có ảnh</div>""", unsafe_allow_html=True)
                
                st.divider()
                
                # B. Upload Ảnh Mới (Ngay tại chỗ)
                st.markdown("#### 📤 Upload Ảnh Mới")
                uploaded_img = st.file_uploader("Chọn ảnh (JPG/PNG)", type=['jpg', 'png', 'jpeg'], key="img_up")
                
                if uploaded_img:
                    if st.button("Lưu Ảnh vào Drive"):
                        with st.spinner("Đang upload..."):
                            # 1. Upload Drive
                            new_link = backend.upload_image_to_drive(uploaded_img, f"{item_code}_{int(time.time())}.jpg", item_code)
                            
                            if new_link:
                                # 2. Update Supabase
                                backend.supabase.table("crm_purchases").update({"image_url": new_link}).eq("id", record_id).execute()
                                st.success("Đã cập nhật ảnh!")
                                time.sleep(1)
                                st.rerun() # Refresh để hiện ảnh mới
            else:
                st.info("👈 Hãy chọn một dòng bên trái để xem ảnh.")

    else: st.info("Kho hàng trống.")

# -----------------------------------------------------------------------------
# TAB 3: BÁO GIÁ (V4800 LOGIC)
# -----------------------------------------------------------------------------
elif menu == "💰 BÁO GIÁ (QUOTATION)":
    st.markdown("## 💰 TẠO BÁO GIÁ")
    
    t1, t2 = st.tabs(["TẠO MỚI", "TRA CỨU LỊCH SỬ"])
    
    with t1:
        c1, c2 = st.columns([1, 2])
        cust = c1.text_input("Tên Khách")
        rfq = c2.file_uploader("Upload RFQ", type=['xlsx','csv'])
        
        if rfq and cust:
            if st.session_state['quote_data'] is None:
                df_in = pd.read_csv(rfq) if rfq.name.endswith('.csv') else pd.read_excel(rfq)
                df_in.columns = [str(c).strip() for c in df_in.columns]
                
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
                        st.session_state['quote_data'] = merged
                    else: st.session_state['quote_data'] = df_in
            
            st.info("👇 Nhập liệu trực tiếp:")
            edited = st.data_editor(st.session_state['quote_data'], num_rows="dynamic", use_container_width=True)
            
            if st.button("🚀 TÍNH TOÁN (V4800 FORMULA)"):
                res = edited.apply(backend.calculate_profit_v4800, axis=1)
                st.session_state['quote_data'] = pd.concat([edited, res], axis=1)
                st.success("Đã tính xong!")
            
            if st.session_state['quote_data'] is not None and 'PROFIT (VND)' in st.session_state['quote_data'].columns:
                final = st.session_state['quote_data']
                st.divider()
                st.dataframe(final.style.format("{:,.0f}", subset=['PROFIT (VND)', 'Total Price (VND)'])
                             .background_gradient(subset=['PROFIT (VND)'], cmap='RdYlGn'), use_container_width=True)
                
                b1, b2, b3 = st.columns(3)
                docx = backend.export_docx_v4800(final, cust)
                b1.download_button("📄 Tải Docs", docx, f"Specs_{cust}.docx")
                
                if b3.button("💾 Lưu Lịch Sử"):
                     backend.supabase.table("crm_shared_history").insert({
                        "quote_id": f"Q-{int(time.time())}", "customer_name": cust, 
                        "total_profit_vnd": final['PROFIT (VND)'].sum(), "status": "Quote Sent"
                     }).execute()
                     st.success("Đã lưu!")

    with t2:
        st.subheader("Tra cứu lịch sử giá (Bulk Check)")
        f = st.file_uploader("Upload Excel chứa Specs", key="h_up")
        if f and st.button("Kiểm tra"):
            st.info("Tính năng đang query dữ liệu lịch sử...")
            # Demo query (Cần phát triển thêm phần query JSON nếu muốn chi tiết)
            hist = backend.supabase.table("crm_shared_history").select("*").execute().data
            st.dataframe(pd.DataFrame(hist))

# -----------------------------------------------------------------------------
# TAB 4: QUẢN LÝ PO
# -----------------------------------------------------------------------------
elif menu == "📑 QUẢN LÝ PO":
    st.markdown("## 📑 XỬ LÝ ĐƠN HÀNG")
    t_c, t_s = st.tabs(["PO KHÁCH HÀNG", "PO NHÀ CUNG CẤP"])
    
    with t_c:
        po = st.file_uploader("File PO Khách")
        cn = st.text_input("Tên Khách")
        val = st.number_input("Giá trị PO", step=1000.0)
        if po and cn and st.button("Lưu PO Khách"):
            l, p = backend.upload_recursive(po, po.name, "PO_KHACH_HANG", datetime.now().year, cn, datetime.now().strftime("%b"))
            if l:
                backend.supabase.table("db_customer_orders").insert({
                    "po_number": f"POC-{int(time.time())}", "customer_name": cn, "total_value": val,
                    "po_file_url": l, "drive_folder_url": p, "status": "Ordered"
                }).execute()
                st.success("Thành công!")

    with t_s:
        mst = st.file_uploader("File PO Tổng (Excel)", type=['xlsx'])
        if mst and st.button("Tách File"):
            df = pd.read_excel(mst)
            sup_col = next((c for c in df.columns if 'supplier' in c.lower() or 'ncc' in c.lower()), None)
            if sup_col:
                for s, d in df.groupby(sup_col):
                    with st.expander(f"NCC: {s}"):
                        st.dataframe(d)
                        if st.button(f"Lưu PO {s}"):
                            buf = io.BytesIO(); d.to_excel(buf, index=False); buf.seek(0)
                            l, p = backend.upload_recursive(buf, f"PO_{s}.xlsx", "PO_NCC", datetime.now().year, s, datetime.now().strftime("%b"))
                            if l: st.success(f"Đã lưu PO {s}")

# -----------------------------------------------------------------------------
# TAB 5: TRACKING
# -----------------------------------------------------------------------------
elif menu == "🚚 VẬN ĐƠN (TRACKING)":
    st.markdown("## 🚚 TRACKING")
    pos = backend.supabase.table("db_customer_orders").select("*").execute()
    df = pd.DataFrame(pos.data)
    if not df.empty:
        st.dataframe(df[['po_number', 'customer_name', 'status', 'drive_folder_url']])
        c1, c2, c3 = st.columns(3)
        sel = c1.selectbox("Chọn PO", df['po_number'])
        stt = c2.selectbox("Trạng thái", ["Shipping", "Arrived", "Delivered"])
        img = c3.file_uploader("Proof")
        if st.button("Cập nhật"):
            backend.supabase.table("db_customer_orders").update({"status": stt}).eq("po_number", sel).execute()
            if img: backend.upload_recursive(img, f"Proof_{sel}.jpg", "TRACKING_PROOF", "2025", "PROOF", "ALL")
            if stt == "Delivered":
                backend.supabase.table("crm_payments").insert({"po_number": sel, "status": "Pending", "eta_payment": str(datetime.now().date())}).execute()
            st.success("Updated!")

# -----------------------------------------------------------------------------
# TAB 6: MASTER DATA (ĐẦY ĐỦ 3 MODULE NHƯ V4800)
# -----------------------------------------------------------------------------
elif menu == "⚙️ MASTER DATA":
    st.markdown("## ⚙️ QUẢN LÝ DỮ LIỆU GỐC")
    
    t_price, t_cust, t_supp = st.tabs(["BẢNG GIÁ VỐN", "DANH SÁCH KHÁCH HÀNG", "DANH SÁCH NCC"])
    
    # 1. BẢNG GIÁ
    with t_price:
        st.info("Cập nhật Giá Vốn (Buying Price)")
        up = st.file_uploader("File Excel", type=['xlsx'], key="up_p")
        if up and st.button("Update Prices"):
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
            st.success("Đã xong!")

    # 2. KHÁCH HÀNG (THÊM MỚI VÀO)
    with t_cust:
        st.info("Import Danh Sách Khách Hàng (Customer)")
        up_c = st.file_uploader("File Customer", type=['xlsx'], key="up_c")
        if up_c and st.button("Update Customers"):
            df = pd.read_excel(up_c)
            # Giả định cột: Name, Address, Tax
            # Bạn cần tạo bảng crm_customers trên Supabase trước nếu chưa có
            st.warning("Đang phát triển module insert DB cho Customer")

    # 3. NHÀ CUNG CẤP (THÊM MỚI VÀO)
    with t_supp:
        st.info("Import Danh Sách Nhà Cung Cấp (Supplier)")
        up_s = st.file_uploader("File Supplier", type=['xlsx'], key="up_s")
        if up_s and st.button("Update Suppliers"):
             st.warning("Đang phát triển module insert DB cho Supplier")
