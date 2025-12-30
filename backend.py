import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 1. KẾT NỐI SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        # Đảm bảo trong Secrets bạn đang để chữ IN HOA: SUPABASE_URL, SUPABASE_KEY
        url = st.secrets["supabase"]["SUPABASE_URL"]
        key = st.secrets["supabase"]["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        return None

supabase: Client = init_supabase()

# --- 2. CẤU HÌNH BẢNG & CỘT (SCHEMAS) ---
# Đây là phần quan trọng để tránh lỗi KeyError khi bảng rỗng
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

# --- 3. CÁC HÀM XỬ LÝ DATA ---
def load_data(table_key):
    """Tải dữ liệu, nếu rỗng thì trả về DataFrame có cột sẵn theo Schema"""
    try:
        # Nếu chưa kết nối được Supabase, trả về bảng rỗng có cột
        if not supabase: 
            return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
            
        table_name = TABLES.get(table_key)
        if not table_name: return pd.DataFrame()
        
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        
        # QUAN TRỌNG: Nếu data rỗng, trả về DataFrame có cột chuẩn
        if not data:
            return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
            
        return pd.DataFrame(data)
    except Exception as e:
        # st.error(f"Lỗi tải {table_key}: {e}") # Tắt thông báo lỗi cho đỡ rối
        return pd.DataFrame(columns=SCHEMAS.get(table_key, []))

def save_data(table_key, df):
    try:
        if not supabase: return
        table_name = TABLES.get(table_key)
        data = df.to_dict(orient='records')
        
        # Nếu data rỗng thì không lưu gì cả
        if not data: return

        supabase.table(table_name).upsert(data).execute()
        st.toast(f"Đã lưu thành công!", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- 4. KẾT NỐI GOOGLE DRIVE ---
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
    except Exception as e:
        return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    try:
        service = get_drive_service()
        if not service: return None

        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        # A. CHỐNG TRÙNG LẶP
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webContentLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""

        if files:
            # GHI ĐÈ
            file_id = files[0]['id']
            updated_file = service.files().update(fileId=file_id, media_body=media, fields='id, webContentLink').execute()
            final_link = updated_file.get('webContentLink')
        else:
            # TẠO MỚI
            file_metadata = {'name': filename, 'parents': [folder_id]}
            created_file = service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
            file_id = created_file.get('id')
            final_link = created_file.get('webContentLink')

        # PUBLIC FILE
        try:
            service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass 

        return final_link

    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
