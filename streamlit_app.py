import streamlit as st
import pandas as pd
import os

def module_bao_gia_ncc():
    st.header("QUẢN LÝ BÁO GIÁ NHÀ CUNG CẤP (BG GIÁ)")

    # 1. Cấu hình danh sách cột CHUẨN (Thứ tự tuyệt đối từ A->O)
    STANDARD_COLUMNS = [
        "No",                        # Cột A
        "Item code",                 # Cột B
        "Item name",                 # Cột C
        "Specs",                     # Cột D
        "Q'ty",                      # Cột E
        "Buying price (RMB)",        # Cột F
        "Total buying price (RMB)",  # Cột G
        "Exchange rate",             # Cột H
        "Buying price (VND)",        # Cột I
        "Total buying price (VND)",  # Cột J
        "Leadtime",                  # Cột K
        "Supplier",                  # Cột L
        "Images",                    # Cột M
        "Type",                      # Cột N
        "N/U/O/C"                    # Cột O
    ]

    uploaded_file = st.file_uploader("Tải lên file Báo giá (Excel)", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            # Đọc file Excel (bỏ qua header cũ để tránh lỗi xuống dòng)
            df = pd.read_excel(uploaded_file)

            # --- SỬA LỖI MAPPING TUYỆT ĐỐI (FIXED) ---
            # Kiểm tra số lượng cột
            if len(df.columns) < len(STANDARD_COLUMNS):
                st.error(f"File Excel lỗi: File chỉ có {len(df.columns)} cột, nhưng hệ thống cần ít nhất {len(STANDARD_COLUMNS)} cột (từ A đến O).")
                return

            # Cắt lấy đúng 15 cột đầu tiên (bất kể tên gốc là gì)
            df_display = df.iloc[:, :len(STANDARD_COLUMNS)]
            
            # Gán lại tên chuẩn cho 15 cột này (Ép buộc mapping theo vị trí)
            # Việc này giúp sửa lỗi header bị xuống dòng trong Excel
            df_display.columns = STANDARD_COLUMNS

            # --- GIAO DIỆN HIỂN THỊ ---
            col_table, col_image = st.columns([3, 1]) 

            with col_table:
                st.subheader("Dữ liệu báo giá")
                event = st.dataframe(
                    df_display,
                    hide_index=True,
                    use_container_width=True,
                    selection_mode="single-row", 
                    on_select="rerun",
                    height=500
                )

            # --- XỬ LÝ HIỂN THỊ ẢNH ---
            with col_image:
                st.subheader("Hình ảnh")
                
                if len(event.selection.rows) > 0:
                    selected_row_index = event.selection.rows[0]
                    selected_item = df_display.iloc[selected_row_index]
                    
                    img_path = selected_item.get("Images") 
                    item_code = selected_item.get("Item code")
                    item_name = selected_item.get("Item name")

                    st.info(f"Mã: {item_code}")
                    st.caption(f"{item_name}")

                    if pd.notna(img_path) and str(img_path).strip() != "":
                        try:
                            # Hiển thị ảnh (Local hoặc URL)
                            st.image(str(img_path), caption="Ảnh sản phẩm", use_column_width=True)
                        except Exception as e:
                            st.warning("Không tải được ảnh.")
                    else:
                        st.info("Chưa có ảnh.")
                else:
                    st.info("👈 Chọn 1 dòng để xem ảnh")

        except Exception as e:
            st.error(f"Có lỗi hệ thống: {e}")

if __name__ == "__main__":
    st.set_page_config(layout="wide")
    module_bao_gia_ncc()
