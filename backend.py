import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- 1. ĐỊNH NGHĨA CẤU TRÚC CỘT (SCHEMA) ---
# Giúp phần mềm biết tên cột ngay cả khi DB trống
SCHEMAS = {
    "customers": ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"],
    "suppliers": ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"],
    "purchases": ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "_clean_code", "_clean_specs", "_clean_name"],
    "sales_history": ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "total_cost", "profit", "supplier", "status", "delivery_date", "po_number", "_clean_code", "_clean_specs"],
    "tracking": ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"],
    "payment": ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"],
    "paid_history": ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"],
    "supplier_orders": ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path"],
    "customer_orders": ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "_clean_code", "_clean_specs"]
}

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

# --- 2. SUPABASE CONNECTION ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Thiếu cấu hình Supabase trong secrets.toml: {e}")
        return None

supabase: Client = init_supabase()

def load_data(table_key):
    """
    Tải dữ liệu và đảm bảo luôn có đủ cột (ngay cả khi DB trống)
    """
    if not supabase: return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
    
    try:
        response = supabase.table(TABLES[table_key]).select("*").execute()
        data = response.data
        
        # Nếu data rỗng, trả về DataFrame rỗng nhưng CÓ ĐỦ CỘT
        if not data:
            return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
            
        df = pd.DataFrame(data)
        
        # Đảm bảo các cột bắt buộc phải có (tránh trường hợp DB thiếu cột)
        expected_cols = SCHEMAS.get(table_key, [])
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "" # Tạo cột trống nếu thiếu
                
        return df
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu {table_key}: {e}")
        return pd.DataFrame(columns=SCHEMAS.get(table_key, []))

def save_data(table_key, df):
    if not supabase: return
    try:
        # Chuyển đổi NaN thành None để Supabase hiểu là null
        df_clean = df.where(pd.notnull(df), None)
        data = df_clean.to_dict(orient='records')
        
        if data:
            supabase.table(TABLES[table_key]).upsert(data).execute()
            st.toast(f"Đã lưu dữ liệu vào {TABLES[table_key]}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- 3. GOOGLE DRIVE CONNECTION (OAUTH2) ---
def get_drive_service():
    try:
        if "google" not in st.secrets: return None
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
        # Lấy folder ID từ secrets, nếu không có thì báo lỗi nhẹ
        folder_key = f"folder_id_{folder_type}"
        if folder_key not in st.secrets["google"]:
            st.warning(f"Chưa cấu hình '{folder_key}' trong secrets.toml")
            return None

        folder_id = st.secrets["google"][folder_key]
        
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream')
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        return file.get('webContentLink')
    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
