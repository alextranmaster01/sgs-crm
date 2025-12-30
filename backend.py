# File: backend.py
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_supabase():
    # Lấy thông tin từ secrets.toml
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

try:
    supabase: Client = init_supabase()
except Exception as e:
    st.error(f"Lỗi kết nối Supabase: {e}. Hãy kiểm tra lại secrets.toml")
    supabase = None

# Mapping Table Names
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

def load_data(table_key):
    if not supabase: return pd.DataFrame()
    try:
        response = supabase.table(TABLES[table_key]).select("*").execute()
        df = pd.DataFrame(response.data)
        return df
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu {table_key}: {e}")
        return pd.DataFrame()

def save_data(table_key, df, key_col='id'):
    if not supabase: return
    try:
        # Chuyển đổi NaN thành None để Supabase hiểu là null
        df_clean = df.where(pd.notnull(df), None)
        data = df_clean.to_dict(orient='records')
        
        # Upsert dữ liệu
        if data:
            supabase.table(TABLES[table_key]).upsert(data).execute()
            st.toast(f"Đã lưu dữ liệu vào {TABLES[table_key]}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- GOOGLE DRIVE CONNECTION (OAUTH2) ---
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
        st.error(f"Lỗi cấu hình Google Drive: {e}")
        return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    service = get_drive_service()
    if not service: return None
    
    try:
        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream')
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        return file.get('webContentLink')
    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
