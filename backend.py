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
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        clean_key = key.replace("\n", "").replace(" ", "").strip()
        return create_client(url, clean_key)
    except Exception as e:
        return None

supabase: Client = init_supabase()

# =========================================================
# 2. CẤU HÌNH SCHEMA
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
# 3. HÀM TẢI & LƯU DATA
# =========================================================
def load_data(table_key):
    default_cols = SCHEMAS.get(table_key, [])
    try:
        if 'supabase' not in globals() or not supabase: return pd.DataFrame(columns=default_cols)
        table_name = TABLES.get(table_key)
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        if not data: return pd.DataFrame(columns=default_cols)
        return pd.DataFrame(data)
    except: return pd.DataFrame(columns=default_cols)

def save_data(table_key, df):
    try:
        if 'supabase' not in globals() or not supabase: return

        table_name = TABLES.get(table_key)
        valid_cols = SCHEMAS.get(table_key, [])
        
        if valid_cols:
            clean_df = df[df.columns.intersection(valid_cols)].copy()
        else:
            clean_df = df.copy()

        numeric_cols = ["qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "total_price", "amount", "profit"]
        for col in numeric_cols:
            if col in clean_df.columns:
                clean_df[col] = clean_df[col].astype(str).str.replace(",", "", regex=False)
                clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce').fillna(0)

        data = clean_df.to_dict(orient='records')
        if not data: return

        supabase.table(table_name).upsert(data).execute()
        st.toast(f"✅ Đã lưu {len(data)} dòng!", icon="💾")
    except Exception as e:
        st.error(f"❌ Lỗi Lưu Data: {e}")

# =========================================================
# 4. KẾT NỐI DRIVE (FIX LỖI HIỂN THỊ ẢNH)
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
        
        # 1. Tìm file cũ (Lấy thêm trường thumbnailLink)
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        # QUAN TRỌNG: Lấy thumbnailLink từ Google
        results = service.files().list(q=query, fields="files(id, thumbnailLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""
        
        # 2. Upload hoặc Update
        if files:
            file_id = files[0]['id']
            # Khi update cũng yêu cầu trả về thumbnailLink
            updated = service.files().update(fileId=file_id, media_body=media, fields='id, thumbnailLink').execute()
            final_link = updated.get('thumbnailLink')
        else:
            meta = {'name': filename, 'parents': [folder_id]}
            # Khi create cũng yêu cầu trả về thumbnailLink
            created = service.files().create(body=meta, media_body=media, fields='id, thumbnailLink').execute()
            file_id = created.get('id')
            final_link = created.get('thumbnailLink')

        # 3. Public file
        try: service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass
        
        # 4. XỬ LÝ LINK ẢNH (BÍ KÍP ĐỂ HIỂN THỊ ĐƯỢC)
        if final_link:
            # Google trả về link nhỏ (=s220), ta sửa thành =s1000 để lấy ảnh nét căng
            return final_link.replace("=s220", "=s2000")
        else:
            # Dự phòng nếu không lấy được thumbnail
            return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"
        
    except Exception as e:
        st.error(f"Lỗi Upload: {e}")
        return None
