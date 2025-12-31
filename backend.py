import streamlit as st
import pandas as pd
import io
import backend  # File backend của bạn chứa hàm upload_to_drive
from openpyxl import load_workbook

def module_bao_gia_ncc():
    st.header("QUẢN LÝ BÁO GIÁ NHÀ CUNG CẤP (BG GIÁ)")

    # 1. Cấu hình danh sách cột CHUẨN (Thứ tự tuyệt đối từ A->O)
    STANDARD_COLUMNS = [
        "No", "Item code", "Item name", "Specs", "Q'ty",
        "Buying price (RMB)", "Total buying price (RMB)", "Exchange rate",
        "Buying price (VND)", "Total buying price (VND)", "Leadtime",
        "Supplier", "Images", "Type", "N/U/O/C"
    ]

    col_tool, col_info = st.columns([1, 2])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Chứa ảnh)", type=['xlsx'])

    # Biến lưu dữ liệu tạm trong session để không bị mất khi reload
    if 'df_display' not in st.session_state:
        st.session_state.df_display = pd.DataFrame()

    if uploaded_file is not None:
        if st.button("🚀 BẮT ĐẦU XỬ LÝ & IMPORT", type="primary"):
            status_box = st.status("Đang xử lý dữ liệu...", expanded=True)
            try:
                # --- BƯỚC 1: DÙNG OPENPYXL ĐỂ MÓC ẢNH ---
                status_box.write("🖼️ Đang quét hình ảnh trong file Excel...")
                uploaded_file.seek(0) # Reset con trỏ file
                wb = load_workbook(uploaded_file, data_only=False)
                ws = wb.active
                
                # Tạo map: Dòng (Excel) -> Dữ liệu ảnh
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        # Lấy số dòng mà ảnh đang nằm (anchor)
                        # row trong openpyxl bắt đầu từ 1
                        r = img.anchor._from.row + 1 
                        image_map[r] = img._data()

                # --- BƯỚC 2: DÙNG PANDAS ĐỌC DỮ LIỆU ---
                status_box.write("📖 Đang đọc dữ liệu văn bản...")
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, header=0)

                # --- BƯỚC 3: MAPPING CỘT TUYỆT ĐỐI (Hard-Map A->O) ---
                if len(df.columns) < 15:
                    st.error("File thiếu cột (Cần ít nhất 15 cột A->O).")
                    return
                
                # Cắt đúng 15 cột, gán tên chuẩn
                df_clean = df.iloc[:, :15]
                df_clean.columns = STANDARD_COLUMNS

                # --- BƯỚC 4: UPLOAD ẢNH & GHÉP LINK ---
                # Tiến độ
                prog_bar = status_box.progress(0)
                total_rows = len(df_clean)

                for i, row in df_clean.iterrows():
                    prog_bar.progress(min((i + 1) / total_rows, 1.0))
                    
                    item_code = str(row["Item code"]).strip()
                    if not item_code or item_code == "nan": continue

                    # Tính dòng tương ứng trong Excel
                    # i là index của pandas (bắt đầu từ 0). Header là dòng 1. 
                    # => Dữ liệu bắt đầu từ dòng 2 trong Excel.
                    # => excel_row = i + 2
                    excel_row_idx = i + 2

                    # Nếu dòng này có ảnh trong map
                    if excel_row_idx in image_map:
                        status_box.write(f"☁️ Đang upload ảnh cho mã: {item_code}...")
                        
                        # Lấy data ảnh
                        img_bytes = image_map[excel_row_idx]
                        file_name = f"{item_code}.png"
                        
                        # GỌI HÀM BACKEND CỦA BẠN
                        # upload_to_drive(file_obj, filename, folder)
                        link = backend.upload_to_drive(io.BytesIO(img_bytes), file_name, "images")
                        
                        if link:
                            # Gán link trả về vào cột Images
                            df_clean.at[i, "Images"] = link
                    else:
                        # Nếu không có ảnh mới, giữ nguyên giá trị cũ nếu là link
                        old_val = str(row["Images"])
                        if "http" not in old_val:
                            df_clean.at[i, "Images"] = "" # Xóa rác nếu không phải link

                st.session_state.df_display = df_clean
                status_box.update(label="✅ Đã xử lý xong!", state="complete", expanded=False)
                
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # --- GIAO DIỆN HIỂN THỊ (70% Bảng - 30% Ảnh) ---
    if not st.session_state.df_display.empty:
        col_table, col_gallery = st.columns([7, 3])

        with col_table:
            st.subheader("Dữ liệu báo giá")
            # Cấu hình hiển thị bảng
            # Ẩn cột link ảnh dài loằng ngoằng, thay bằng LinkColumn gọn gàng
            column_config = {
                "Images": st.column_config.LinkColumn("Link Ảnh"),
                "Buying price (RMB)": st.column_config.NumberColumn(format="%.2f"),
                "Buying price (VND)": st.column_config.NumberColumn(format="%d"),
            }

            event = st.dataframe(
                st.session_state.df_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                height=600
            )

        with col_gallery:
            st.info("📷 KHUNG XEM ẢNH")
            
            # Logic hiển thị ảnh khi chọn dòng
            if len(event.selection.rows) > 0:
                idx = event.selection.rows[0]
                row = st.session_state.df_display.iloc[idx]
                
                img_link = row.get("Images")
                item_code = row.get("Item code")
                item_name = row.get("Item name")
                
                st.markdown(f"**{item_code}**")
                st.caption(f"{item_name}")
                
                if img_link and "http" in str(img_link):
                    # Dùng chính hàm backend để get bytes ảnh về hiển thị cho mượt
                    # Hoặc để st.image tự load link (tuỳ backend của bạn trả về link gì)
                    st.image(img_link, caption="Ảnh sản phẩm", use_column_width=True)
                else:
                    st.warning("Chưa có ảnh (File Excel không có ảnh tại dòng này).")
            else:
                st.info("👈 Chọn một dòng bên trái để xem ảnh.")

# Chạy thử
if __name__ == "__main__":
    # st.set_page_config(layout="wide") # Đã set ở main
    module_bao_gia_ncc()
