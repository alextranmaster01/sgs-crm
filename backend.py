import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import io
import re

# --- 1. KẾT NỐI SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        clean_key = key.replace("\n", "").replace(" ", "").strip()
        return create_client(url, clean_key)
    except: return None

supabase: Client = init_supabase()

# --- 2. CẤU HÌNH SCHEMA ---
TABLES = {
    "purchases": "crm_purchases", "customers": "crm_customers", "suppliers": "crm_suppliers",
    "sales_history": "crm_sales_history", "tracking": "crm_order_tracking", "payment": "crm_payment_tracking",
    "paid_history": "crm_paid_history", "supplier_orders": "db_supplier_orders", "customer_orders": "db_customer_orders"
}

SCHEMAS = {
    "purchases": ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path"],
    "customers": ["id", "short_name", "full_name", "address", "tax_code", "contact"],
    "suppliers": ["id", "short_name", "full_name", "contact", "products"],
    "payment": ["id", "order_id", "customer_name", "amount", "status", "payment_date", "notes"],
    "tracking": ["id", "order_id", "status", "update_time", "location"]
}

# --- 3. HÀM TẢI & LƯU DATA ---
def load_data(table_key):
    default_cols = SCHEMAS.get(table_key, [])
    try:
        if 'supabase' not in globals() or not supabase: return pd.DataFrame(columns=default_cols)
        table_name = TABLES.get(table_key)
        response = supabase.table(table_name).select("*").order("id", desc=True).execute()
        return pd.DataFrame(response.data) if response.data else pd.DataFrame(columns=default_cols)
    except: return pd.DataFrame(columns=default_cols)

def save_data(table_key, df):
    try:
        if 'supabase' not in globals() or not supabase: return
        table_name = TABLES.get(table_key)
        valid_cols = SCHEMAS.get(table_key, [])
        clean_df = df[df.columns.intersection(valid_cols)].copy() if valid_cols else df.copy()
        numeric_cols = ["qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "total_price", "amount", "profit"]
        for col in numeric_cols:
            if col in clean_df.columns:
                clean_df[col] = clean_df[col].astype(str).str.replace(",", "", regex=False).str.replace("¥", "").str.replace("$", "")
                clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce').fillna(0)
        data = clean_df.to_dict(orient='records')
        if not data: return
        supabase.table(table_name).upsert(data).execute()
        st.toast(f"✅ Đã lưu {len(data)} dòng!", icon="💾")
    except Exception as e: st.error(f"❌ Lỗi Lưu: {e}")

# --- 4. KẾT NỐI DRIVE & HÀM LẤY ẢNH TRỰC TIẾP (QUAN TRỌNG) ---
def get_drive_service():
    try:
        creds = Credentials(
            None, refresh_token=st.secrets["google"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets["google"]["client_id"],
            client_secret=st.secrets["google"]["client_secret"]
        )
        return build('drive', 'v3', credentials=creds)
    except: return None

def get_image_bytes(link):
    """Hàm này tải thẳng dữ liệu ảnh về, không dùng link nhúng nữa"""
    if not link or "http" not in str(link): return None
    try:
        # Trích xuất File ID từ Link
        file_id = ""
        if "id=" in link: file_id = link.split("id=")[1].split("&")[0]
        elif "/d/" in link: file_id = link.split("/d/")[1].split("/")[0]
        elif "picture/3" in link: file_id = link.split("picture/3")[1].split("=")[0] # Link lh3 cũ
        
        if not file_id: return None

        service = get_drive_service()
        if not service: return None
        
        # Tải nội dung file về RAM
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: status, done = downloader.next_chunk()
        return fh.getvalue() # Trả về cục dữ liệu ảnh
    except: return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    try:
        service = get_drive_service()
        if not service: return None
        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        file_id = ""

        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {'name': filename, 'parents': [folder_id]}
            created = service.files().create(body=meta, media_body=media, fields='id').execute()
            file_id = created.get('id')

        try: service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass
        
        # Lưu link dạng ID chuẩn để dễ xử lý sau này
        return f"https://drive.google.com/uc?id={file_id}"
        
    except Exception as e:
        st.error(f"Lỗi Upload: {e}")
        return None
