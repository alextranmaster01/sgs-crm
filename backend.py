import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =========================================================
# 1. KẾT NỐI SUPABASE (DÙNG CHỮ THƯỜNG KHỚP SECRETS)
# =========================================================
@st.cache_resource
def init_supabase():
    try:
        # Lấy thông tin từ secrets
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        
        # Làm sạch key để tránh lỗi xuống dòng khi copy paste
        clean_key = key.replace("\n", "").replace(" ", "").strip()
        
        return create_client(url, clean_key)
    except Exception as e:
        st.error(f"Lỗi kết nối Supabase: {e}")
        return None

# Khởi tạo biến toàn cục
supabase: Client = init_supabase()

# =========================================================
# 2. CẤU HÌNH BẢNG & SCHEMA (KHUNG XƯƠNG DỮ LIỆU)
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

# Định nghĩa cột mặc định để tránh lỗi KeyError khi bảng rỗng
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
# 3. HÀM TẢI & LƯU DỮ LIỆU (ĐÃ FIX LỖI SỐ LIỆU)
# =========================================================
def load_data(table_key):
    """Tải dữ liệu an toàn, trả về bảng trống có cột nếu DB rỗng"""
    default_cols = SCHEMAS.get(table_key, [])
    
    try:
        if 'supabase' not in globals() or not supabase:
            return pd.DataFrame(columns=default_cols)
        
        table_name = TABLES.get(table_key)
        if not table_name: return pd.DataFrame(columns=default_cols)
        
        # Tải dữ liệu từ Supabase
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        
        if not data:
            return pd.DataFrame(columns=default_cols)
            
        return pd.DataFrame(data)

    except Exception as e:
        # st.warning(f"⚠️ Không tải được bảng '{table_key}'. Lỗi: {e}")
        return pd.DataFrame(columns=default_cols)

def save_data(table_key, df):
    """Lưu dữ liệu, tự động làm sạch số (1,925 -> 1925)"""
    try:
        if 'supabase' not in globals() or not supabase:
            st.error("Chưa kết nối được Database!")
            return

        table_name = TABLES.get(table_key)
        valid_cols = SCHEMAS.get(table_key, [])
        
        # 1. Lọc bỏ cột rác
        if valid_cols:
            clean_df = df[df.columns.intersection(valid_cols)].copy()
        else:
            clean_df = df.copy()

        # 2. Làm sạch dữ liệu số (Fix lỗi invalid input syntax for type numeric)
        numeric_cols = [
            "qty", "buying_price_rmb", "total_buying_price_rmb", 
            "exchange_rate", "buying_price_vnd", "total_buying_price_vnd",
            "total_price", "amount", "profit"
        ]
        
        for col in numeric_cols:
            if col in clean_df.columns:
                # Chuyển về chuỗi, xóa dấu phẩy, ép kiểu số
                clean_df[col] = clean_df[col].astype(str).str.replace(",", "", regex=False)
                clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce').fillna(0)

        data = clean_df.to_dict(orient='records')
        if not data: return

        # 3. Gửi lên Supabase
        supabase.table(table_name).upsert(data).execute()
        st.toast(f"✅ Đã lưu thành công vào {table_name}!", icon="💾")
        
    except Exception as e:
        st.error(f"❌ Lỗi Lưu Data: {e}")

# =========================================================
# 4. KẾT NỐI DRIVE & UPLOAD (ĐÃ FIX LỖI TRÙNG LẶP)
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
        
        # 1. Kiểm tra file cũ (Chống trùng lặp)
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webContentLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""

        if files:
            # 2. Ghi đè (Update) nếu đã có
            file_id = files[0]['id']
            updated = service.files().update(fileId=file_id, media_body=media, fields='id, webContentLink').execute()
            final_link = updated.get('webContentLink')
        else:
            # 3. Tạo mới (Create) nếu chưa có
            meta = {'name': filename, 'parents': [folder_id]}
            created = service.files().create(body=meta, media_body=media, fields='id, webContentLink').execute()
            file_id = created.get('id')
            final_link = created.get('webContentLink')

        # 4. Public file (Để hiển thị trên Streamlit)
        try: service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass 
        
        return final_link
    except Exception as e:
        st.error(f"Lỗi Upload: {e}")
        return None
