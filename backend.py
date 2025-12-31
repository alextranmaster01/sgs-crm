import pandas as pd
import requests
import streamlit as st

# --- GIỮ NGUYÊN CÁC HÀM KHÁC (load_data, save_data...) ---

def get_image_bytes(url):
    """Tải ảnh từ URL về dạng bytes và BÁO LỖI CHI TIẾT nếu thất bại"""
    try:
        # Nếu url rỗng hoặc None
        if not url: return None

        # Xử lý link Google Drive view -> export
        final_url = url
        if "drive.google.com" in url and "/view" in url:
            file_id = url.split("/d/")[1].split("/")[0]
            final_url = f"https://drive.google.com/uc?export=view&id={file_id}"

        # Tải ảnh với thời gian chờ 10s
        response = requests.get(final_url, timeout=10)
        
        # Nếu thành công (200 OK)
        if response.status_code == 200:
            return response.content
        else:
            # In lỗi ra màn hình console hoặc giao diện để debug
            print(f"Lỗi tải ảnh: Status code {response.status_code} - URL: {final_url}")
            return None
    except Exception as e:
        print(f"Lỗi ngoại lệ khi tải ảnh: {e}")
        return None

def upload_to_drive(file_obj, filename, folder_name="images"):
    # --- QUAN TRỌNG: BẠN PHẢI DÁN CODE UPLOAD DRIVE THẬT CỦA BẠN VÀO ĐÂY ---
    # Nếu bạn chưa có code thật, nó sẽ trả về link giả bên dưới
    # Link giả này có thể bị chặn bởi mạng công ty/VPN
    return "https://via.placeholder.com/300.png/09f/fff?text=Anh+Mau+Test"
