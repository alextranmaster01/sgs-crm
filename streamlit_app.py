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

# TAB 2: DB GIÁ NCC (LAYOUT CHIA ĐÔI: BẢNG | ẢNH)
with tab2:
    st.subheader("Database Giá NCC")
    
    # 1. TOOLBAR
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                status_box.write("🖼️ Đang quét ảnh...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=False) 
                ws = wb.active
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        r_idx = img.anchor._from.row + 1
                        image_map[r_idx] = img._data()
                
                status_box.write("📖 Đọc dữ liệu...")
                uploaded_file.seek(0)
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                data_clean = []
                prog_bar = status_box.progress(0)
                total = len(df_raw)
                
                for i, row in df_raw.iterrows():
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    excel_row_idx = i + 2
                    def get(col_name): return safe_str(row.get(col_name, ""))
                    code = safe_str(row.iloc[1])
                    if not code: continue

                    final_link = ""
                    if excel_row_idx in image_map:
                        img_bytes = image_map[excel_row_idx]
                        filename = f"{safe_filename(code)}.png"
                        status_box.write(f"☁️ Upload ảnh: {code}...")
                        link = backend.upload_to_drive(io.BytesIO(img_bytes), filename, folder_type="images")
                        if link: final_link = link
                    else:
                        old = safe_str(row.iloc[12]) if len(row) > 12 else ""
                        if "http" in old: final_link = old

                    item = {
                        "no": safe_str(row.iloc[0]), "item_code": code, "item_name": safe_str(row.iloc[2]), 
                        "specs": safe_str(row.iloc[3]), "qty": fmt_num(to_float(row.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(row.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(row.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(row.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(row.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(row.iloc[9])), 
                        "leadtime": safe_str(row.iloc[10]), "supplier_name": safe_str(row.iloc[11]), 
                        "image_path": final_link,
                        "_clean_code": clean_lookup_key(code), "_clean_specs": clean_lookup_key(safe_str(row.iloc[3])), "_clean_name": clean_lookup_key(safe_str(row.iloc[2]))
                    }
                    data_clean.append(item)
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label="✅ Hoàn tất!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    # 2. MAIN LAYOUT: CHIA CỘT (70% BẢNG - 30% ẢNH)
    col_table, col_gallery = st.columns([7, 3])
    
    df_pur = backend.load_data("purchases")
    
    with col_table:
        search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        # Config bảng
        cfg = {
            "image_path": st.column_config.ImageColumn("Hình Ảnh", width="small", help="Ảnh Thumbnail"),
            "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Mua", format="%d"),
            "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
        }
        order = ["image_path", "no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name"]
        
        # Bảng dữ liệu
        edited_pur = st.data_editor(
            df_pur, 
            column_config=cfg, 
            column_order=order, 
            use_container_width=True, 
            height=600, 
            key="ed_pur",
            num_rows="dynamic"
        )
        if st.button("💾 Lưu thay đổi"): backend.save_data("purchases", edited_pur)

    # 3. KHUNG XEM ẢNH (BÊN PHẢI)
    with col_gallery:
        st.info("📷 KHUNG XEM ẢNH TRỰC TIẾP")
        if not df_pur.empty:
            # Lấy list ảnh có link
            df_images = df_pur[df_pur["image_path"].str.contains("http", na=False)]
            
            if not df_images.empty:
                # Cho phép chọn sản phẩm để xem ảnh to
                selected_code = st.selectbox("Chọn mã hàng để xem ảnh:", df_images["item_code"].unique())
                
                # Tìm ảnh tương ứng
                row = df_images[df_images["item_code"] == selected_code].iloc[0]
                img_url = row["image_path"]
                
                st.image(img_url, caption=f"{row['item_code']} - {row['item_name']}", use_container_width=True)
                
                # Hiển thị thông số vắn tắt dưới ảnh
                st.markdown(f"""
                **Specs:** {row['specs']}  
                **Giá:** {row['buying_price_vnd']} VND  
                **NCC:** {row['supplier_name']}
                """)
            else:
                st.write("Chưa có sản phẩm nào có ảnh.")
        else:
            st.write("Chưa có dữ liệu.")

# (Giữ nguyên code các tab khác)
