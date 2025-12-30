import streamlit as st
from supabase import create_client, Client # <--- Đảm bảo có dòng import này
# File: backend.py
import pandas as pd
import streamlit as st
from supabase import create_client, Client
# ... các import khác của bạn (google, etc.)

# --- THÊM ĐOẠN NÀY VÀO ĐẦU FILE (SAU IMPORT) ---
SCHEMAS = {
    "purchases": [
        "no", "item_code", "item_name", "specs", "qty", 
        "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
        "buying_price_vnd", "total_buying_price_vnd", "leadtime", 
        "supplier_name", "image_path", 
        "_clean_code", "_clean_specs", "_clean_name"
    ],
    "customer_orders": [
        "order_id", "customer_name", "order_date", "delivery_date",
        "items", "total_amount", "status", "notes"
    ],
    "inventory": [
        "item_code", "item_name", "stock_qty", "location", "last_updated"
    ]
}
# ------------------------------------------------

# ... Sau đó mới đến các hàm init_supabase, load_data ...
# 1. Hàm khởi tạo kết nối (có Cache)
@st.cache_resource
def init_supabase():
    try:
        # Lấy thông tin từ secrets.toml
        url = st.secrets["supabase"]["SUPABASE_URL"]
        key = st.secrets["supabase"]["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Lỗi kết nối Supabase: {e}")
        return None

# 2. Gọi hàm để lấy biến client
supabase = init_supabase()

def get_drive_service():
    # Lấy thông tin từ secrets.toml
    info = st.secrets["google"]
    
    # Tạo credentials từ Refresh Token
    creds = Credentials(
        None, # Access token (để None để nó tự lấy mới)
        refresh_token=info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        scopes=['https://www.googleapis.com/auth/drive']
    )
    
    return build('drive', 'v3', credentials=creds)

# Hàm upload giữ nguyên logic, chỉ gọi get_drive_service ở trên
def upload_to_drive(file_obj, filename, folder_type="images"):
    service = get_drive_service()

# --- 1. CẤU HÌNH SCHEMA (ĐỂ TRÁNH LỖI KHI DB TRỐNG) ---
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

# --- 2. KẾT NỐI SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        return None

supabase: Client = init_supabase()

def load_data(table_key):
    if not supabase: return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
    try:
        response = supabase.table(TABLES[table_key]).select("*").execute()
        data = response.data
        if not data: return pd.DataFrame(columns=SCHEMAS.get(table_key, []))
        df = pd.DataFrame(data)
        for col in SCHEMAS.get(table_key, []):
            if col not in df.columns: df[col] = ""
        return df
    except Exception as e:
        return pd.DataFrame(columns=SCHEMAS.get(table_key, []))

def save_data(table_key, df):
    if not supabase: return
    try:
        df_clean = df.where(pd.notnull(df), None)
        data = df_clean.to_dict(orient='records')
        if data:
            supabase.table(TABLES[table_key]).upsert(data).execute()
            st.toast(f"Đã lưu dữ liệu vào {TABLES[table_key]}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- 3. KẾT NỐI GOOGLE DRIVE (QUAN TRỌNG) ---
def get_drive_service():
    """Tạo kết nối Google Drive API từ Refresh Token"""
    try:
        if "google" not in st.secrets: 
            st.error("Chưa cấu hình secrets[google]")
            return None
            
        creds = Credentials(
            None, # Access Token (None để tự refresh)
            refresh_token=st.secrets["google"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets["google"]["client_id"],
            client_secret=st.secrets["google"]["client_secret"]
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Lỗi Auth Google: {e}")
        return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    """
    Upload file lên Drive -> Set quyền Public -> Trả về Link xem trực tiếp
    """
    service = get_drive_service()
    if not service: return None
    
    try:
        # 1. Lấy ID thư mục từ secrets
        folder_key = f"folder_id_{folder_type}"
        if folder_key not in st.secrets["google"]:
            st.error(f"Thiếu cấu hình '{folder_key}' trong secrets.toml")
            return None
        folder_id = st.secrets["google"][folder_key]
        
        # 2. Tạo metadata cho file
        file_metadata = {
            'name': filename, 
            'parents': [folder_id]
        }
        
        # 3. Chuẩn bị file để upload
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        
        # 4. Thực hiện Upload
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webContentLink' # Yêu cầu trả về ID và Link
        ).execute()
        
        file_id = file.get('id')
        
        # 5. QUAN TRỌNG: Cấp quyền "Anyone with link" (Reader)
        # Nếu không có bước này, Streamlit sẽ KHÔNG hiển thị được ảnh
        try:
            permission = {
                'type': 'anyone',
                'role': 'reader',
            }
            service.permissions().create(
                fileId=file_id,
                body=permission,
            ).execute()
        except Exception as p_e:
            st.warning(f"Không thể set quyền public cho ảnh (Có thể do chính sách Google Workspace): {p_e}")

        # 6. Trả về link hiển thị (webContentLink)
        return file.get('webContentLink')

    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
