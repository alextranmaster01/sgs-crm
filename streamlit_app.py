import streamlit as st
import pandas as pd
import os

def module_bao_gia_ncc():
    st.header("QUẢN LÝ BÁO GIÁ NHÀ CUNG CẤP (BG GIÁ)")

    # 1. Cấu hình danh sách cột CHUẨN (Thứ tự tuyệt đối từ A->O)
    # Lưu ý: Tên cột dưới đây phải khớp chính xác với Header trong file Excel của bạn
    STANDARD_COLUMNS = [
        "No",
        "Item code",
        "Item name",
        "Specs",
        "Q'ty",
        "Buying price (RMB)",
        "Total buying price (RMB)",
        "Exchange rate",
        "Buying price (VND)",
        "Total buying price (VND)",
        "Leadtime",
        "Supplier",
        "Images",
        "Type",
        "N/U/O/C"
    ]

    # Giả lập upload file (Thay thế bằng st.file_uploader trong thực tế)
    uploaded_file = st.file_uploader("Tải lên file Báo giá (Excel)", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            # Đọc file Excel
            df = pd.read_excel(uploaded_file)

            # --- XỬ LÝ MAPPING CỘT TUYỆT ĐỐI ---
            # Kiểm tra xem file tải lên có đủ các cột chuẩn không
            missing_cols = [col for col in STANDARD_COLUMNS if col not in df.columns]
            
            if missing_cols:
                st.error(f"File Excel thiếu các cột sau: {', '.join(missing_cols)}")
                return
            
            # Chỉ lấy đúng các cột chuẩn theo đúng thứ tự đã định nghĩa
            df_display = df[STANDARD_COLUMNS]

            # --- GIAO DIỆN HIỂN THỊ (Chia layout để thu nhỏ ảnh) ---
            # Chia màn hình thành 2 phần: 
            # col_table (75% chiều rộng) để hiện bảng
            # col_image (25% chiều rộng) để hiện ảnh -> Đáp ứng yêu cầu ảnh nhỏ đi
            col_table, col_image = st.columns([3, 1]) 

            with col_table:
                st.subheader("Dữ liệu báo giá")
                # Tạo bảng tương tác
                # selection_mode="single-row": Chỉ cho phép chọn 1 dòng
                # on_select="rerun": Khi chọn sẽ tải lại app để hiện ảnh ngay lập tức
                event = st.dataframe(
                    df_display,
                    hide_index=True,
                    use_container_width=True,
                    selection_mode="single-row", 
                    on_select="rerun",
                    height=500
                )

            # --- XỬ LÝ HIỂN THỊ ẢNH KHI CLICK ---
            with col_image:
                st.subheader("Hình ảnh")
                
                # Kiểm tra xem người dùng đã chọn dòng nào chưa
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    
                    # Lấy dữ liệu từ dòng được chọn
                    selected_item = df_display.iloc[selected_row_index]
                    
                    img_path = selected_item.get("Images") # Lấy đường dẫn/link ảnh
                    item_code = selected_item.get("Item code")
                    item_name = selected_item.get("Item name")

                    # Hiển thị thông tin tóm tắt
                    st.info(f"Đang xem: {item_code}")
                    st.caption(f"{item_name}")

                    # Hiển thị ảnh
                    if pd.notna(img_path) and str(img_path).strip() != "":
                        try:
                            # Nếu ảnh là Link Online hoặc Đường dẫn Local
                            # use_column_width=True sẽ tự động co giãn ảnh vừa khít với cột nhỏ này
                            st.image(img_path, caption="Ảnh sản phẩm", use_column_width=True)
                        except Exception as e:
                            st.error("Không thể tải ảnh. Link hỏng hoặc sai định dạng.")
                    else:
                        st.warning("Sản phẩm này chưa có dữ liệu ảnh.")
                else:
                    # Trạng thái chờ: Khi chưa chọn gì cả
                    st.info("👈 Bấm vào một dòng bên trái (Item code/Name/Specs...) để xem ảnh.")

        except Exception as e:
            st.error(f"Có lỗi khi đọc file: {e}")

# Chạy thử module
if __name__ == "__main__":
    st.set_page_config(layout="wide") # Chế độ màn hình rộng
    module_bao_gia_ncc()
