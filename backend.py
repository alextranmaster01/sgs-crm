import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =========================================================
# 1. KẾT NỐI SUPABASE
# =========================================================
@st.cache_resource
def init_supabase():
    try:
        # Lấy thông tin từ secrets (dùng chữ thường url/key khớp với file của bạn)
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        
        # Làm sạch key đề phòng lỗi copy paste bị xuống dòng
        clean_key = key.replace("\n", "").replace(" ", "").strip()
        
        return create_client(url, clean_key)
    except Exception as e:
        st.error(f"Lỗi kết nối Supabase: {e}")
        return None

# --- DÒNG QUAN TRỌNG ĐỂ SỬA LỖI "name 'supabase' is not defined" ---
supabase: Client = init_supabase()
# -------------------------------------------------------------------

# =========================================================
# 2. CẤU HÌNH BẢNG & CỘT
# =========================================================
TABLES = {
    "purchases": "crm_purchases",
    "customers": "crm_customers",
    "suppliers": "crm_suppliers",
    "sales_history": "crm_sales_history",
    "tracking": "crm_order_tracking",
    "payment": "crm_payment_tracking",
    "paid_history": "crm_paid_history",
    "supplier_orders": "db_supplier_orders",
    "customer_orders": "db_customer_orders"
}

SCHEMAS = {
    "payment": ["id", "order_id", "customer_name", "amount", "status", "payment_date", "notes"],
    "customer_orders": ["id", "order_id", "customer_name", "total_price", "order_date", "status"],
    "purchases": ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path"],
    "tracking": ["id", "order_id", "status", "update_time", "location"],
    "customers": ["id", "short_name", "full_name", "address", "tax_code", "contact"],
    "suppliers": ["id", "short_name", "full_name", "contact", "products"],
    "sales_history": ["id", "order_id", "profit", "date"],
    "paid_history": ["id", "order_id", "amount", "date"]
}

# =========================================================
# 3. CÁC HÀM XỬ LÝ DATA (LOAD & SAVE)
# =========================================================
def load_data(table_key):
    # Lấy danh sách cột mặc định để tránh lỗi thiếu cột
    default_cols = SCHEMAS.get(table_key, [])
    
    try:
        # Kiểm tra biến supabase
        if 'supabase' not in globals() or not supabase:
            return pd.DataFrame(columns=default_cols)
        
        table_name = TABLES.get(table_key)
        if not table_name: return pd.DataFrame(columns=default_cols)
        
        # Tải dữ liệu
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        
        if not data:
            return pd.DataFrame(columns=default_cols)
            
        return pd.DataFrame(data)

    except Exception as e:
        # Nếu lỗi (ví dụ chưa tạo bảng), trả về bảng rỗng đúng chuẩn
        st.warning(f"⚠️ Không tải được bảng '{table_key}'. Lỗi: {e}")
        return pd.DataFrame(columns=default_cols)

def save_data(table_key, df):
    try:
        if 'supabase' not in globals() or not supabase:
            st.error("Chưa kết nối được Database!")
            return

        table_name = TABLES.get(table_key)
        valid_cols = SCHEMAS.get(table_key, [])
        
        # Lọc bỏ cột rác, chỉ giữ cột chuẩn
        if valid_cols:
            clean_df = df[df.columns.intersection(valid_cols)]
        else:
            clean_df = df

        data = clean_df.to_dict(orient='records')
        if not data: return

        # Gửi lên Supabase
        supabase.table(table_name).upsert(data).execute()
        st.toast(f"✅ Đã lưu dữ liệu vào {table_name}!", icon="💾")
        
    except Exception as e:
        st.error(f"❌ Lỗi Lưu Data: {e}")

# =========================================================
# 4. KẾT NỐI GOOGLE DRIVE
# =========================================================
def get_drive_service():
    try:
        creds = Credentials(
            None,
            refresh_token=st.secrets["google"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets["google"]["client_id"],
            client_secret=st.secrets["google"]["client_secret"]
        )
        return build('drive', 'v3', credentials=creds)
    except: return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    try:
        service = get_drive_service()
        if not service: return None
        
        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        # Kiểm tra file trùng
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webContentLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""

        if files:
            # Ghi đè
            file_id = files[0]['id']
            updated = service.files().update(fileId=file_id, media_body=media, fields='id, webContentLink').execute()
            final_link = updated.get('webContentLink')
        else:
            # Tạo mới
            meta = {'name': filename, 'parents': [folder_id]}
            created = service.files().create(body=meta, media_body=media, fields='id, webContentLink').execute()
            file_id = created.get('id')
            final_link = created.get('webContentLink')

        # Public quyền xem
        try: service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass 
        
        return final_link
    except Exception as e:
        st.error(f"Lỗi Upload: {e}")
        return None
