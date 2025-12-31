import streamlit as st
import pandas as pd
import io
import re
from openpyxl import load_workbook
import backend  # Đảm bảo bạn đã có file backend.py chứa hàm upload_to_drive

# Hàm hỗ trợ làm sạch tên file
def safe_filename(s): 
    return re.sub(r"[\\/:*?\"<>|]+", "_", str(s).strip()) if s else "unknown"

def module_bao_gia_ncc():
    st.header("QUẢN LÝ BÁO GIÁ NHÀ CUNG CẤP (BG GIÁ)")

    # 1. Cấu hình danh sách cột CHUẨN (Thứ tự tuyệt đối từ A->O)
    STANDARD_COLUMNS = [
        "No", "Item code", "Item name", "Specs", "Q'ty",
        "Buying price (RMB)", "Total buying price (RMB)", "Exchange rate",
        "Buying price (VND)", "Total buying price (VND)", "Leadtime",
        "Supplier", "Images", "Type", "N/U/O/C"
    ]

    col_upload, col_action = st.columns([2, 1])
    with col_upload:
        uploaded_file = st.file_uploader("📥 Tải lên file Excel (Chứa ảnh dán trong ô)", type=['xlsx'])

    # Biến session để giữ dữ liệu sau khi upload xong (tránh reload mất bảng)
    if 'bg_data' not in st.session_state:
        st.session_state.bg_data = pd.DataFrame()

    # Nút bấm xử lý
    start_process = False
    if uploaded_file is not None:
        with col_action:
            st.write("") # Spacer
            st.write("") 
            if st.button("🚀 BẮT ĐẦU IMPORT & UPLOAD", type="primary"):
                start_process = True

    if start_process and uploaded_file:
        status_box = st.status("Đang xử lý dữ liệu...", expanded=True)
        try:
            # --- BƯỚC 1: DÙNG OPENPYXL ĐỂ MÓC ẢNH RA ---
            status_box.write("🖼️ Đang quét hình ảnh trong file Excel...")
            uploaded_file.seek(0)
            wb = load_workbook(uploaded_file, data_only=False)
            ws = wb.active
            
            # Tạo map: Số dòng Excel -> Dữ liệu ảnh (bytes)
            # Lưu ý: openpyxl tính dòng từ 1, pandas tính từ 0
            image_map = {}
            if hasattr(ws, '_images'):
                for img in ws._images:
                    # Lấy dòng chứa ảnh (anchor row)
                    r = img.anchor._from.row + 1 
                    image_map[r] = img._data()
            
            status_box.write(f"✅ Tìm thấy {len(image_map)} ảnh trong file.")

            # --- BƯỚC 2: ĐỌC DỮ LIỆU TEXT BẰNG PANDAS ---
            status_box.write("📖 Đang đọc dữ liệu văn bản...")
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file, header=0)

            # --- BƯỚC 3: MAPPING CỘT TUYỆT ĐỐI (A->O) ---
            if len(df.columns) < 15:
                st.error("File lỗi: Không đủ 15 cột dữ liệu (A->O).")
                status_box.update(label="❌ Lỗi dữ liệu", state="error")
                return

            # Cắt đúng 15 cột đầu tiên và ép tên chuẩn
            df_display = df.iloc[:, :15].copy()
            df_display.columns = STANDARD_COLUMNS

            # --- BƯỚC 4: DUYỆT TỪNG DÒNG ĐỂ UPLOAD ẢNH ---
            status_box.write("☁️ Đang đồng bộ ảnh lên Google Drive...")
            progress_bar = status_box.progress(0)
            total_rows = len(df_display)

            for i, row in df_display.iterrows():
                # Cập nhật thanh tiến trình
                progress_bar.progress(min((i + 1) / total_rows, 1.0))
                
                # Tính dòng tương ứng trong Excel
                # Header là dòng 1 => Data bắt đầu từ dòng 2
                # Pandas index 0 => Excel row 2
                excel_row = i + 2
                
                item_code = str(row["Item code"]).strip()
                
                # Logic xử lý ảnh
                final_link = ""
                
                # Trường hợp 1: Có ảnh dán trong ô (ưu tiên cao nhất)
                if excel_row in image_map:
                    # status_box.write(f"Đang upload ảnh mã: {item_code}...")
                    img_bytes = image_map[excel_row]
                    file_name = f"{safe_filename(item_code)}.png"
                    
                    # GỌI HÀM CỦA BẠN ĐỂ UPLOAD
                    try:
                        link = backend.upload_to_drive(io.BytesIO(img_bytes), file_name, "images")
                        if link:
                            final_link = link
                    except Exception as e:
                        print(f"Lỗi upload {item_code}: {e}")

                # Trường hợp 2: Không có ảnh dán, nhưng có link sẵn trong cột M (Images)
                if not final_link:
                    old_val = str(row["Images"])
                    if "http" in old_val:
                        final_link = old_val
                
                # Gán lại link vào DataFrame
                if final_link:
                    df_display.at[i, "Images"] = final_link
                else:
                    df_display.at[i, "Images"] = "" # Xóa rác nếu ko có ảnh

            # Lưu vào session
            st.session_state.bg_data = df_display
            status_box.update(label="✅ Hoàn tất Import & Upload!", state="complete", expanded=False)
            
        except Exception as e:
            st.error(f"Có lỗi xảy ra: {e}")
            status_box.update(label="❌ Có lỗi!", state="error")

    # --- GIAO DIỆN HIỂN THỊ (Sau khi đã có dữ liệu trong session) ---
    if not st.session_state.bg_data.empty:
        df_show = st.session_state.bg_data
        
        # Chia layout 70% - 30%
        col_table, col_gallery = st.columns([7, 3])

        with col_table:
            st.subheader("Dữ liệu báo giá")
            
            # Cấu hình hiển thị cột cho đẹp
            column_config = {
                "Images": st.column_config.LinkColumn("Link Ảnh"),
                "Buying price (RMB)": st.column_config.NumberColumn(format="%.2f"),
                "Buying price (VND)": st.column_config.NumberColumn(format="%d"),
                "Total buying price (VND)": st.column_config.NumberColumn(format="%d"),
            }

            # Bảng tương tác
            event = st.dataframe(
                df_show,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                height=600
            )

        with col_gallery:
            st.info("📷 XEM ẢNH CHI TIẾT")
            
            # Logic bắt sự kiện chọn dòng
            if len(event.selection.rows) > 0:
                idx = event.selection.rows[0]
                row = df_show.iloc[idx]
                
                img_link = row.get("Images")
                item_code = row.get("Item code")
                item_name = row.get("Item name")
                specs = row.get("Specs")
                
                st.markdown(f"#### {item_code}")
                st.caption(f"{item_name}")
                
                # Hiển thị ảnh
                if img_link and "http" in str(img_link):
                    # Nếu backend trả về link xem được ngay (vd: drive.google.com/thumbnail?...)
                    st.image(img_link, caption="Ảnh sản phẩm", use_column_width=True)
                else:
                    st.warning("Chưa có ảnh (Hoặc chưa Import xong).")
                
                st.divider()
                st.markdown(f"**Thông số:** {specs}")
                st.markdown(f"**NCC:** {row.get('Supplier')}")
            else:
                st.info("👈 Vui lòng chọn một dòng bên trái để xem ảnh.")
