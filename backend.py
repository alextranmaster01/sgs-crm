import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# 1. KẾT NỐI SUPABASE (Dùng url/key chữ thường như ảnh bạn gửi)
# ==========================================
@st.cache_resource
def init_supabase():
    try:
        # Lấy đúng key chữ thường trong file secrets của bạn
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        return None

supabase: Client = init_supabase()

# ==========================================
# 2. CẤU HÌNH BẢNG (Khớp với SQL vừa chạy)
# ==========================================
TABLE_NAME = "crm_purchases"

# ==========================================
# 3. KẾT NỐI GOOGLE DRIVE & UPLOAD (Xử lý trùng lặp)
# ==========================================
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
        
        # A. Tìm file cũ
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webContentLink)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype='image/png', resumable=True)
        final_link = ""
        file_id = ""

        if files:
            # B. Ghi đè (Update)
            file_id = files[0]['id']
            updated = service.files().update(fileId=file_id, media_body=media, fields='id, webContentLink').execute()
            final_link = updated.get('webContentLink')
        else:
            # C. Tạo mới (Create)
            meta = {'name': filename, 'parents': [folder_id]}
            created = service.files().create(body=meta, media_body=media, fields='id, webContentLink').execute()
            file_id = created.get('id')
            final_link = created.get('webContentLink')

        # D. Public ảnh
        try:
            service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except: pass 

        return final_link

    except Exception as e:
        st.error(f"Upload lỗi: {e}")
        return None

# ==========================================
# 4. HÀM LOAD & SAVE DATA (Quan trọng)
# ==========================================
def load_data(table_key_ignored=None):
    """Tải dữ liệu từ Supabase về"""
    try:
        if not supabase: return pd.DataFrame()
        
        # Select toàn bộ dữ liệu, sắp xếp theo ID giảm dần (mới nhất lên đầu)
        response = supabase.table(TABLE_NAME).select("*").order("id", desc=True).execute()
        data = response.data
        
        if not data: return pd.DataFrame()
        return pd.DataFrame(data)
        
    except Exception as e:
        return pd.DataFrame()

def save_data(table_key_ignored, df):
    """Lưu dữ liệu vào Supabase"""
    try:
        if not supabase: return
        
        # Chuyển đổi dữ liệu sang dạng list of dicts
        # Chỉ giữ lại các cột có trong database để tránh lỗi
        valid_cols = [
            "no", "item_code", "item_name", "specs", "qty", 
            "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
            "buying_price_vnd", "total_buying_price_vnd", "leadtime", 
            "supplier_name", "image_path"
        ]
        
        # Lọc DataFrame chỉ lấy các cột hợp lệ
        df_clean = df[df.columns.intersection(valid_cols)]
        data_records = df_clean.to_dict(orient='records')
        
        if not data_records: return

        # Insert dữ liệu (Dùng insert thay vì upsert để đơn giản hóa lúc này)
        # Nếu muốn xóa cũ nạp mới thì uncomment dòng dưới:
        # supabase.table(TABLE_NAME).delete().neq("id", 0).execute() 
        
        supabase.table(TABLE_NAME).insert(data_records).execute()
        st.toast(f"Đã lưu {len(data_records)} dòng!", icon="✅")
        
    except Exception as e:
        st.error(f"Lỗi lưu DB: {e}")
