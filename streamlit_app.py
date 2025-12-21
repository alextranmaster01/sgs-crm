import pandas as pd
import psycopg2
import streamlit as st

def import_excel_to_db(uploaded_file):
    # 1. Đọc file Excel
    try:
        df = pd.read_excel(uploaded_file)
        
        # Chuẩn hóa tên cột cho khớp với database (nếu cần)
        # Ví dụ: df = df.rename(columns={'Mã': 'code', 'Giá': 'price', ...})
        
    except Exception as e:
        st.error(f"Lỗi đọc file: {e}")
        return

    # 2. Kết nối Database
    conn = get_database_connection() # Hàm kết nối của bạn
    cursor = conn.cursor()

    try:
        # 3. Insert thẳng (KHÔNG kiểm tra trùng lặp)
        # Sử dụng executemany để tối ưu tốc độ insert nhiều dòng
        
        data_tuples = list(df.itertuples(index=False, name=None))
        
        # Câu lệnh SQL Insert cơ bản (bỏ qua id nếu id tự tăng)
        query = """
            INSERT INTO ten_bang_cua_ban (code, price, country, name, specs) 
            VALUES (%s, %s, %s, %s, %s)
        """
        
        cursor.executemany(query, data_tuples)
        conn.commit()
        
        st.success(f"Đã import thành công {len(df)} dòng dữ liệu!")
        
    except psycopg2.Error as e:
        conn.rollback()
        # Nếu vẫn gặp lỗi 23505 ở đây, nghĩa là bước 1 (Sửa Database) chưa xong
        if e.pgcode == '23505':
            st.error("LỖI DATABASE: Vẫn còn ràng buộc Unique trong bảng. Hãy xóa Constraint trong Database trước.")
        else:
            st.error(f"Lỗi Database: {e}")
            
    finally:
        cursor.close()
        conn.close()
