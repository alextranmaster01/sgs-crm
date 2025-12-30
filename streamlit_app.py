import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl import load_workbook
import io
import datetime
import re
import time

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO (CONFIG & SETUP)
# =============================================================================
st.set_page_config(layout="wide", page_title="CRM SYSTEM PRO", page_icon="🏢")

# Custom CSS cho giao diện chuyên nghiệp
st.markdown("""
<style>
    .metric-card { background-color: #262730; padding: 15px; border-radius: 10px; border: 1px solid #444; color: white; text-align: center; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px; color: black; font-weight: bold;}
    .stTabs [data-baseweb="tab"][aria-selected="true"] { background-color: #ff4b4b; color: white; }
</style>
""", unsafe_allow_html=True)

# Khởi tạo kết nối
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    GOOGLE_CLIENT_ID = st.secrets["google"]["client_id"]
    GOOGLE_CLIENT_SECRET = st.secrets["google"]["client_secret"]
    GOOGLE_REFRESH_TOKEN = st.secrets["google"]["refresh_token"]
    ROOT_FOLDER_ID = st.secrets["google"]["root_folder_id"]
except Exception as e:
    st.error(f"Lỗi cấu hình secrets.toml: {e}")
    st.stop()
# =============================================================================
# CẬP NHẬT LẠI PHẦN KẾT NỐI GOOGLE DRIVE (Copy đè vào phần cũ)
# =============================================================================
class GoogleDriveService:
    def __init__(self):
        try:
            # Lấy thông tin từ secrets
            self.client_id = st.secrets["google"]["client_id"]
            self.client_secret = st.secrets["google"]["client_secret"]
            self.refresh_token = st.secrets["google"]["refresh_token"]
            
            # Cấu hình Credentials chuẩn xác
            self.creds = Credentials(
                None, # Access token (để None để tự động lấy từ refresh token)
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            # Thử khởi tạo service để bắt lỗi ngay lập tức nếu sai key
            self.service = build('drive', 'v3', credentials=self.creds)
            
            # Test thử kết nối bằng cách gọi lệnh nhẹ nhất
            self.service.files().list(pageSize=1).execute()
            print("✅ Đã kết nối Google Drive thành công với Key mới!")
            
        except Exception as e:
            st.error("❌ LỖI KẾT NỐI GOOGLE DRIVE (MÃ MỚI BỊ TỪ CHỐI)")
            st.warning(f"Chi tiết lỗi: {e}")
            st.info("""
            Cách khắc phục:
            1. Vào Google OAuth Playground > Bấm Bánh răng ⚙️.
            2. Điền Client ID & Secret CỦA BẠN vào (Đừng dùng mặc định).
            3. Lấy lại Refresh Token và dán vào secrets.toml.
            """)
            st.stop()

    def get_or_create_folder(self, folder_name, parent_id):
        """Tìm thư mục, nếu chưa có thì tạo mới"""
        try:
            query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and '{parent_id}' in parents and trashed=false"
            results = self.service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])
            if files:
                return files[0]['id']
            else:
                meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
                folder = self.service.files().create(body=meta, fields='id').execute()
                return folder.get('id')
        except Exception as e:
            st.error(f"Lỗi khi tạo folder '{folder_name}': {e}")
            return None

    def upload_bytes(self, data_bytes, file_name, folder_id, mime_type='application/octet-stream'):
        """Upload file từ bộ nhớ lên Drive"""
        try:
            # Kiểm tra file trùng tên
            query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
            results = self.service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])
            
            media = MediaIoBaseUpload(data_bytes, mimetype=mime_type, resumable=True)
            
            if files:
                file_id = files[0]['id']
                self.service.files().update(fileId=file_id, media_body=media).execute()
            else:
                meta = {'name': file_name, 'parents': [folder_id]}
                res = self.service.files().create(body=meta, media_body=media, fields='id').execute()
                file_id = res.get('id')
                
            # Cấp quyền public read
            self.service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            return f"https://drive.google.com/uc?id={file_id}"
        except Exception as e:
            st.error(f"Lỗi upload file '{file_name}': {e}")
            return ""

    def download_file(self, file_id):
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = request.execute()
            fh.write(downloader)
            fh.seek(0)
            return fh
        except Exception as e:
            st.error(f"Lỗi download file: {e}")
            return None

drive_service = GoogleDriveService()
# =============================================================================
# 3. HELPER FUNCTIONS (LOGIC & UTILS)
# =============================================================================
def clean_currency(val):
    """Chuyển đổi chuỗi tiền tệ (¥, $, ,) thành float"""
    if pd.isna(val) or val == "": return 0.0
    s = str(val)
    s = re.sub(r'[^\d\.-]', '', s)
    try:
        return float(s)
    except:
        return 0.0

def format_vnd(val):
    if not val: return "0"
    return "{:,.0f}".format(val)

def fetch_data(table_name):
    """Lấy dữ liệu từ Supabase"""
    resp = supabase.table(table_name).select("*").execute()
    return pd.DataFrame(resp.data)

# =============================================================================
# 4. TAB LOGIC: INVENTORY (KHO HÀNG)
# =============================================================================
def tab_inventory():
    st.header("📦 QUẢN LÝ KHO HÀNG (PRODUCTS)")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.info("Upload file 'BUYING PRICE-ALL-OK.xlsx'")
        uploaded_file = st.file_uploader("Chọn file Excel", type=['xlsx'])
        
        if uploaded_file and st.button("🚀 Bắt đầu Import"):
            try:
                # 1. Load Workbook để lấy ảnh
                wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                ws = wb.active
                
                # Folder chứa ảnh trên Drive
                img_folder_id = drive_service.get_or_create_folder("PRODUCT_IMAGES", ROOT_FOLDER_ID)
                
                # Map ảnh theo hàng (Row index trong openpyxl bắt đầu từ 1)
                image_map = {}
                for image in ws._images:
                    row = image.anchor._from.row + 1
                    image_map[row] = image

                # 2. Đọc dữ liệu text bằng Pandas cho nhanh
                # Skip rows=0 vì header ở dòng 1
                df_excel = pd.read_excel(uploaded_file, header=0)
                
                records = []
                progress_bar = st.progress(0)
                
                for index, row in df_excel.iterrows():
                    # Excel row index (1-based) = pandas index + 2 (header line)
                    excel_row_idx = index + 2
                    
                    item_code = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ""
                    if not item_code or item_code.lower() == 'nan': continue
                    
                    # Xử lý ảnh
                    img_url = ""
                    if excel_row_idx in image_map:
                        img_obj = image_map[excel_row_idx]
                        img_data = io.BytesIO(img_obj._data())
                        img_name = f"{item_code}_{int(time.time())}.png"
                        img_url = drive_service.upload_bytes(img_data, img_name, img_folder_id, 'image/png')

                    # Mapping cột theo yêu cầu
                    record = {
                        "item_code": item_code,
                        "item_name": str(row.iloc[2]) if pd.notna(row.iloc[2]) else "",
                        "specs": str(row.iloc[3]) if pd.notna(row.iloc[3]) else "",
                        "qty": clean_currency(row.iloc[4]),
                        "buying_price_rmb": clean_currency(row.iloc[5]),
                        "total_rmb": clean_currency(row.iloc[6]),
                        "exchange_rate": clean_currency(row.iloc[7]),
                        "buying_price_vnd": clean_currency(row.iloc[8]),
                        "total_vnd": clean_currency(row.iloc[9]),
                        "leadtime": str(row.iloc[10]) if pd.notna(row.iloc[10]) else "",
                        "supplier_name": str(row.iloc[11]) if pd.notna(row.iloc[11]) else "",
                        "image_url": img_url,
                        "type_category": str(row.iloc[13]) if pd.notna(row.iloc[13]) else "",
                        "status_nou": str(row.iloc[14]) if pd.notna(row.iloc[14]) else ""
                    }
                    records.append(record)
                    progress_bar.progress((index + 1) / len(df_excel))
                
                # 3. Upsert vào Supabase
                # Xóa cũ nhập mới hoặc Upsert. Ở đây chọn xóa cũ theo Item Code để update
                if records:
                    # Batch insert để tránh timeout
                    chunk_size = 100
                    for i in range(0, len(records), chunk_size):
                        chunk = records[i:i+chunk_size]
                        # Xóa những item trùng code trước
                        codes = [r['item_code'] for r in chunk]
                        supabase.table("crm_products").delete().in_("item_code", codes).execute()
                        supabase.table("crm_products").insert(chunk).execute()
                    
                    st.success(f"Đã import thành công {len(records)} sản phẩm!")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"Lỗi Import: {e}")

    with col2:
        # Hiển thị dữ liệu
        df_prods = fetch_data("crm_products")
        if not df_prods.empty:
            st.data_editor(
                df_prods,
                column_config={
                    "image_url": st.column_config.ImageColumn("Ảnh", width="small"),
                    "buying_price_vnd": st.column_config.NumberColumn("Giá Mua (VND)", format="%d"),
                    "total_vnd": st.column_config.NumberColumn("Tổng Mua (VND)", format="%d"),
                },
                use_container_width=True,
                height=600
            )

# =============================================================================
# 5. TAB LOGIC: QUOTATION (BÁO GIÁ) - LOGIC PHỨC TẠP NHẤT
# =============================================================================
def tab_quotation():
    st.header("📜 TẠO BÁO GIÁ (QUOTATION)")
    
    # 1. Config Header
    c1, c2, c3 = st.columns(3)
    
    # Lấy danh sách khách hàng
    cust_df = fetch_data("crm_customers")
    cust_names = cust_df['short_name'].tolist() if not cust_df.empty else []
    
    selected_cust = c1.selectbox("Khách hàng:", options=cust_names)
    quote_code = c2.text_input("Mã báo giá:", value=f"APL{datetime.date.today().strftime('%Y%m%d')}-01")
    quote_date = c3.date_input("Ngày báo giá:", datetime.date.today())

    # 2. Chọn sản phẩm từ Kho
    st.subheader("Chi tiết sản phẩm")
    
    # Lấy data kho để search
    inventory_df = fetch_data("crm_products")
    
    if "quote_items" not in st.session_state:
        st.session_state.quote_items = []

    # Search Box
    with st.expander("🔍 Tìm và Thêm sản phẩm từ Kho"):
        search_txt = st.text_input("Nhập Mã, Tên hoặc Specs:")
        if search_txt and not inventory_df.empty:
            # Filter
            mask = inventory_df.apply(lambda x: search_txt.lower() in str(x['item_code']).lower() or 
                                                search_txt.lower() in str(x['item_name']).lower(), axis=1)
            results = inventory_df[mask]
            
            # Show results to add
            for idx, row in results.iterrows():
                col_res1, col_res2, col_res3, col_res4 = st.columns([1, 3, 2, 1])
                col_res1.image(row['image_url'] if row['image_url'] else "https://via.placeholder.com/50", width=50)
                col_res2.write(f"**{row['item_code']}** - {row['item_name']}")
                col_res3.write(f"Vốn: {format_vnd(row['buying_price_vnd'])} VND")
                if col_res4.button("➕ Thêm", key=f"add_{row['id']}"):
                    item = {
                        "item_code": row['item_code'],
                        "item_name": row['item_name'],
                        "specs": row['specs'],
                        "qty": 1.0,
                        "cost_price": float(row['buying_price_vnd']),
                        "markup": 1.2, # Default lãi 20%
                        "unit_price": float(row['buying_price_vnd']) * 1.2,
                        "total_price": float(row['buying_price_vnd']) * 1.2 * 1.0,
                        "leadtime": row['leadtime']
                    }
                    st.session_state.quote_items.append(item)
                    st.success("Đã thêm!")

    # 3. Bảng Editor Chính (Logic V6045)
    if st.session_state.quote_items:
        df_quote = pd.DataFrame(st.session_state.quote_items)
        
        # Cấu hình cột cho data_editor
        edited_df = st.data_editor(
            df_quote,
            column_config={
                "cost_price": st.column_config.NumberColumn("Giá Vốn", disabled=True, format="%d"),
                "markup": st.column_config.NumberColumn("Hệ số (Markup)", format="%.2f"),
                "unit_price": st.column_config.NumberColumn("Đơn giá Bán (VND)", format="%d"),
                "total_price": st.column_config.NumberColumn("Thành tiền (VND)", disabled=True, format="%d"),
            },
            use_container_width=True,
            num_rows="dynamic",
            key="quote_editor"
        )
        
        # Logic tính toán lại (Recalculate)
        # Nếu user sửa Markup -> Update Unit Price
        # Nếu user sửa Unit Price -> Update Markup
        # Ở đây làm đơn giản: Ưu tiên Markup nếu thay đổi, sau đó tính Total
        
        updated_items = []
        total_quote_value = 0
        
        for idx, row in edited_df.iterrows():
            qty = float(row['qty'])
            cost = float(row['cost_price'])
            markup = float(row['markup'])
            
            # Tính giá bán
            unit_price = cost * markup
            total_price = unit_price * qty
            
            # Update lại row
            row['unit_price'] = unit_price
            row['total_price'] = total_price
            total_quote_value += total_price
            updated_items.append(row)
        
        # Hiển thị tổng
        st.markdown(f"### 💰 TỔNG GIÁ TRỊ: {format_vnd(total_quote_value)} VND")
        
        # 4. Export & Save
        if st.button("💾 Lưu & Xuất File Báo Giá"):
            # A. Tải template
            template_files = drive_service.service.files().list(q="name contains 'AAA-QUOTATION' and trashed=false").execute().get('files', [])
            if not template_files:
                st.error("Không tìm thấy file mẫu 'AAA-QUOTATION' trên Drive!")
                return
            
            tmpl_id = template_files[0]['id']
            byte_tmpl = drive_service.download_file(tmpl_id)
            
            # B. Fill Data (openpyxl)
            wb = load_workbook(byte_tmpl)
            ws = wb.active
            
            # Header Info (Row 4, 5...)
            # Điều chỉnh cell theo file thực tế
            ws['G4'] = quote_code
            ws['G5'] = quote_date.strftime("%Y-%m-%d")
            ws['C4'] = selected_cust
            
            # Get Customer Address info from DB
            cust_info = cust_df[cust_df['short_name'] == selected_cust].iloc[0] if not cust_df.empty else None
            if cust_info is not None:
                ws['C6'] = cust_info['address_1']
            
            # Table Data (Start Row 11 based on specs/csv)
            start_row = 11
            for i, item in enumerate(updated_items):
                r = start_row + i
                ws[f'A{r}'] = i + 1
                ws[f'C{r}'] = item['item_code']
                ws[f'D{r}'] = item['item_name']
                ws[f'E{r}'] = item['specs']
                ws[f'F{r}'] = item['qty']
                ws[f'G{r}'] = item['unit_price']
                ws[f'H{r}'] = item['total_price']
                ws[f'I{r}'] = item['leadtime']
            
            # Save to buffer
            out_buffer = io.BytesIO()
            wb.save(out_buffer)
            out_buffer.seek(0)
            
            # C. Upload to Drive
            # Tạo folder theo Khách hàng
            quote_folder_id = drive_service.get_or_create_folder("QUOTATION_HISTORY", ROOT_FOLDER_ID)
            cust_folder_id = drive_service.get_or_create_folder(selected_cust, quote_folder_id)
            
            file_name = f"QUOTE_{quote_code}_{selected_cust}.xlsx"
            file_link = drive_service.upload_bytes(out_buffer, file_name, cust_folder_id, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            
            # D. Save to DB
            quote_data = {
                "quote_code": quote_code,
                "customer_short_name": selected_cust,
                "quote_date": quote_date.isoformat(),
                "total_value": total_quote_value,
                "excel_file_url": file_link,
                "status": "Sent"
            }
            res = supabase.table("crm_quotes").insert(quote_data).execute()
            quote_id = res.data[0]['id']
            
            # Save items
            items_db = []
            for item in updated_items:
                items_db.append({
                    "quote_id": quote_id,
                    "item_code": item['item_code'],
                    "item_name": item['item_name'],
                    "specs": item['specs'],
                    "qty": item['qty'],
                    "unit_price_vnd": item['unit_price'],
                    "total_price_vnd": item['total_price'],
                    "cost_price_vnd": item['cost_price']
                })
            supabase.table("crm_quote_items").insert(items_db).execute()
            
            st.success(f"Đã tạo báo giá thành công! Link file: {file_link}")
            st.session_state.quote_items = [] # Reset

# =============================================================================
# 6. TAB LOGIC: MASTER DATA (KHÁCH HÀNG & NCC)
# =============================================================================
def tab_partners():
    st.header("👥 DANH SÁCH ĐỐI TÁC")
    
    tab_c, tab_s = st.tabs(["Khách Hàng (Customers)", "Nhà Cung Cấp (Suppliers)"])
    
    with tab_c:
        # Import Khách hàng
        up_c = st.file_uploader("Upload CUSTOMER LIST.xlsx", type=['xlsx'], key="up_c")
        if up_c and st.button("Import Khách Hàng"):
            df = pd.read_excel(up_c)
            # Map columns based on file
            recs = []
            for _, r in df.iterrows():
                # Skip row 1 if header issues, assume header=0 correct
                recs.append({
                    "short_name": str(r.get('short_name', '')),
                    "eng_name": str(r.get('eng_name', '')),
                    "vn_name": str(r.get('vn_name', '')),
                    "address_1": str(r.get('address_1', '')),
                    "contact_person": str(r.get('contact_person', '')),
                    "phone": str(r.get('phone', ''))
                })
            if recs:
                supabase.table("crm_customers").insert(recs).execute()
                st.success("Done!")
        
        # View
        df_cust = fetch_data("crm_customers")
        st.dataframe(df_cust)

    with tab_s:
        # Tương tự cho NCC
        up_s = st.file_uploader("Upload SUPPLIER LIST.xlsx", type=['xlsx'], key="up_s")
        if up_s and st.button("Import NCC"):
            df = pd.read_excel(up_s)
            recs = []
            for _, r in df.iterrows():
                recs.append({
                    "short_name": str(r.get('short_name', '')),
                    "eng_name": str(r.get('eng_name', '')),
                    "vn_name": str(r.get('vn_name', ''))
                })
            if recs:
                supabase.table("crm_suppliers").insert(recs).execute()
                st.success("Done!")
                
        df_sup = fetch_data("crm_suppliers")
        st.dataframe(df_sup)

# =============================================================================
# 7. MAIN APP LAYOUT
# =============================================================================
def main():
    st.title("🚀 SYSTEM V6099 - CRM AUTOMATION")
    
    t1, t2, t3, t4 = st.tabs(["KHO HÀNG (INVENTORY)", "BÁO GIÁ (QUOTES)", "ĐỐI TÁC (PARTNERS)", "ĐƠN HÀNG (ORDERS)"])
    
    with t1:
        tab_inventory()
    with t2:
        tab_quotation()
    with t3:
        tab_partners()
    with t4:
        st.info("Chức năng PO đang phát triển theo module Tracking...")
        # Có thể thêm logic PO tương tự Báo giá ở đây
        df_po = fetch_data("crm_orders")
        st.dataframe(df_po)

if __name__ == "__main__":
    main()

