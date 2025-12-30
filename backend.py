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
        # Lấy thông tin từ secrets (viết hoa cho chuẩn)
        url = st.secrets["supabase"]["SUPABASE_URL"]
        key = st.secrets["supabase"]["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        return None

# Khởi tạo client (Biến toàn cục)
supabase: Client = init_supabase()

# --- 2. CẤU HÌNH BẢNG (TABLES) ---
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

# --- 3. CÁC HÀM XỬ LÝ DATA ---
def load_data(table_key):
    try:
        if not supabase: return pd.DataFrame()
        table_name = TABLES.get(table_key)
        if not table_name: return pd.DataFrame()
        
        response = supabase.table(table_name).select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu {table_key}: {e}")
        return pd.DataFrame()

def save_data(table_key, df):
    try:
        if not supabase: return
        table_name = TABLES.get(table_key)
        
        # Chuyển DataFrame thành danh sách dictionary để upload
        data = df.to_dict(orient='records')
        
        # Upsert (Cập nhật hoặc Thêm mới)
        supabase.table(table_name).upsert(data).execute()
        st.toast(f"Đã lưu dữ liệu vào {table_name}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- 4. KẾT NỐI GOOGLE DRIVE (OAUTH2) ---
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
        st.error(f"Lỗi xác thực Google: {e}")
        return None

def upload_to_drive(file_obj, filename, folder_type="images"):
    try:
        service = get_drive_service()
        if not service: return None

        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        # A. KIỂM TRA FILE CŨ (Chống trùng lặp)
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webContentLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""

        if files:
            # B. NẾU CÓ RỒI -> GHI ĐÈ (UPDATE)
            file_id = files[0]['id']
            updated_file = service.files().update(
                fileId=file_id,
                media_body=media,
                fields='id, webContentLink'
            ).execute()
            final_link = updated_file.get('webContentLink')
        else:
            # C. NẾU CHƯA CÓ -> TẠO MỚI (CREATE)
            file_metadata = {'name': filename, 'parents': [folder_id]}
            created_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webContentLink'
            ).execute()
            file_id = created_file.get('id')
            final_link = created_file.get('webContentLink')

        # D. PUBLIC ẢNH
        try:
            permission = {'type': 'anyone', 'role': 'reader'}
            service.permissions().create(fileId=file_id, body=permission).execute()
        except:
            pass 

        return final_link

    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
