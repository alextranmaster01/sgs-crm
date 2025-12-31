import streamlit as st
import pandas as pd
import backend
import time
import io
import re
from openpyxl import load_workbook

st.set_page_config(page_title="SGS CRM V4800 - ONLINE", layout="wide", page_icon="🪶")
st.markdown("""<style>.stTabs [data-baseweb="tab-list"] { gap: 10px; } .stTabs [data-baseweb="tab"] { background-color: #ecf0f1; border-radius: 4px 4px 0 0; padding: 10px 20px; font-weight: bold; } .stTabs [aria-selected="true"] { background-color: #3498db; color: white; }</style>""", unsafe_allow_html=True)

# Helper functions
def safe_str(val): return str(val).strip() if val is not None else ""
def safe_filename(s): return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))
def to_float(val):
    try:
        clean = str(val).replace(",", "").replace("%", "").strip()
        return float(clean) if clean else 0.0
    except: return 0.0
def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"
def clean_lookup_key(s): return re.sub(r'\s+', '', str(s)).lower() if s else ""

if 'quote_df' not in st.session_state:
    st.session_state.quote_df = pd.DataFrame()

st.title("SGS CRM V4800 - FINAL FULL FEATURES (ONLINE)")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Tổng quan", "💰 Báo giá NCC (DB Giá)", "📝 Báo giá KH", "📦 Đơn đặt hàng", "🚚 Theo dõi & Thanh toán", "⚙️ Master Data"])

# TAB 1: DASHBOARD
with tab1:
    st.subheader("DASHBOARD KINH DOANH")
    if st.button("🔄 CẬP NHẬT DATA", type="primary"): st.rerun()
    st.info("Hệ thống CRM Online.")

# TAB 2: DB GIÁ NCC (LOGIC CHUẨN TỪ CODE MẪU CỦA BẠN)
with tab2:
    st.subheader("Database Giá NCC (Tự động tách ảnh & Upload lên Drive)")
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                # 1. TÁCH ẢNH (Logic openpyxl chuẩn từ file mẫu)
                status_box.write("🖼️ Đang quét ảnh từ Excel...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=False) 
                ws = wb.active
                
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        # LOGIC QUAN TRỌNG: Row Index (1-based) = Anchor Row + 1
                        r_idx = img.anchor._from.row + 1
                        image_map[r_idx] = img._data()
                
                status_box.write(f"✅ Tìm thấy {len(image_map)} ảnh...")

                # 2. ĐỌC DỮ LIỆU (Dùng header=0 để khớp với logic i+2)
                status_box.write("📖 Đang đọc dữ liệu văn bản...")
                uploaded_file.seek(0)
                # Dùng header=0: Dòng 1 là tiêu đề, dữ liệu bắt đầu từ dòng 2
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                data_clean = []
                prog_bar = status_box.progress(0)
                total = len(df_raw)
                count_uploaded = 0
                
                # Iterate rows
                for i, row in df_raw.iterrows():
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    
                    # LOGIC MAPPING CHUẨN:
                    # Dữ liệu dòng i trong DataFrame tương ứng với Row Excel là i + 2
                    # (Vì header là dòng 1, dòng đầu tiên của data là dòng 2)
                    excel_row_idx = i + 2
                    
                    # Lấy dữ liệu an toàn
                    def get(col_name): return safe_str(row.get(col_name, ""))
                    
                    # Mapping cột theo tên trong file Excel mẫu (hoặc index nếu cần)
                    # Giả sử file Excel có các cột: no, item_code, item_name...
                    # Nếu file Excel không có header chuẩn, bạn cần đổi lại thành iloc
                    code = safe_str(row.iloc[1]) # Cột 2 là item_code
                    if not code: continue

                    # XỬ LÝ UPLOAD ẢNH
                    final_link = ""
                    if excel_row_idx in image_map:
                        img_bytes = image_map[excel_row_idx]
                        filename = f"{safe_filename(code)}.png"
                        file_obj = io.BytesIO(img_bytes)
                        
                        status_box.write(f"☁️ Upload ảnh mã: {code}...")
                        # Upload lên Drive -> Lấy Link Thumbnail
                        link = backend.upload_to_drive(file_obj, filename, folder_type="images")
                        if link: 
                            final_link = link
                            count_uploaded += 1
                    else:
                        # Giữ link cũ nếu cột image_path có link
                        old = safe_str(row.iloc[12]) if len(row) > 12 else ""
                        if "http" in old: final_link = old

                    # TẠO ITEM
                    item = {
                        "no": safe_str(row.iloc[0]), 
                        "item_code": code, 
                        "item_name": safe_str(row.iloc[2]), 
                        "specs": safe_str(row.iloc[3]),
                        "qty": fmt_num(to_float(row.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(row.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(row.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(row.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(row.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(row.iloc[9])), 
                        "leadtime": safe_str(row.iloc[10]), 
                        "supplier_name": safe_str(row.iloc[11]), 
                        "image_path": final_link,
                        "_clean_code": clean_lookup_key(code), 
                        "_clean_specs": clean_lookup_key(safe_str(row.iloc[3])), 
                        "_clean_name": clean_lookup_key(safe_str(row.iloc[2]))
                    }
                    data_clean.append(item)
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label=f"✅ Hoàn tất! Upload {count_uploaded} ảnh mới.", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
                else:
                    status_box.update(label="⚠️ Không có dữ liệu!", state="error")

            except Exception as e: st.error(f"Lỗi: {e}")

    # HIỂN THỊ
    df_pur = backend.load_data("purchases")
    search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
    if search and not df_pur.empty:
        df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

    # Cấu hình cột hiển thị
    cfg = {
        "image_path": st.column_config.ImageColumn("Hình Ảnh", width="small", help="Ảnh từ Drive"),
        "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Mua", format="%d"),
        "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
    }
    order = ["image_path", "no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name"]
    
    edited_pur = st.data_editor(df_pur, column_config=cfg, column_order=order, use_container_width=True, height=600, key="ed_pur")
    if st.button("💾 Lưu thay đổi"): backend.save_data("purchases", edited_pur)

# GIỮ NGUYÊN CÁC TAB 3, 4, 5, 6
# (Bạn chỉ cần copy phần import từ code cũ của bạn vào các tab này nếu cần)
