import pandas as pd
import requests
import io
import streamlit as st

# --- 1. QUẢN LÝ DỮ LIỆU (DATABASE) ---
# Ở đây tôi dùng CSV để chạy demo ngay lập tức.
# Nếu bạn dùng Supabase, hãy thay code trong hàm này bằng code gọi Supabase của bạn.

def load_data(table_name):
    """Đọc dữ liệu từ file CSV (hoặc Database)"""
    try:
        # Thử đọc file CSV local
        df = pd.read_csv(f"{table_name}.csv")
        # Đảm bảo các cột số là số
        return df
    except FileNotFoundError:
        # Nếu chưa có file thì trả về DataFrame rỗng
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Lỗi load data: {e}")
        return pd.DataFrame()

def save_data(table_name, df):
    """Lưu dữ liệu xuống file CSV (hoặc Database)"""
    try:
        # Lưu tạm vào file CSV
        df.to_csv(f"{table_name}.csv", index=False)
        st.toast(f"Đã lưu dữ liệu vào {table_name}.csv", icon="✅")
    except Exception as e:
        st.error(f"Lỗi save data: {e}")

# --- 2. XỬ LÝ ẢNH & GOOGLE DRIVE ---

def get_image_bytes(url):
    """Tải ảnh từ URL về dạng bytes để hiển thị lên Streamlit"""
    try:
        # Xử lý link Google Drive để tải trực tiếp
        if "drive.google.com" in url:
            file_id = url.split("/d/")[1].split("/")[0]
            url = f"https://drive.google.com/uc?export=view&id={file_id}"
            
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.content
        return None
    except:
        return None

def upload_to_drive(file_obj, filename, folder_name="images"):
    """
    Hàm này cần cấu hình Google Drive API thật để hoạt động.
    Hiện tại tôi sẽ trả về một link ảnh mẫu (Placeholder) để code không bị lỗi.
    BẠN CẦN DÁN CODE UPLOAD DRIVE CỦA BẠN VÀO ĐÂY.
    """
    # --- VÙNG CODE GIẢ LẬP (MOCK) ---
    # Nếu bạn chưa cấu hình Drive API, code sẽ trả về link ảnh mẫu này
    # để quy trình import không bị chết giữa chừng.
    return "https://via.placeholder.com/150?text=Uploaded+Image"

    # --- VÙNG CODE THẬT (Gợi ý) ---
    # import googleapiclient.discovery
    # ... logic xác thực service_account.json ...
    # ... logic upload ...
    # return web_view_link
