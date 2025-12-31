import streamlit as st
import pandas as pd
import backend # File backend của bạn
import time
import io
import re
from openpyxl import load_workbook

# --- 1. PHẦN CẤU HÌNH TRANG (BẮT BUỘC PHẢI CÓ Ở ĐẦU) ---
st.set_page_config(page_title="SGS CRM V4800 - ONLINE", layout="wide", page_icon="🪶")

# Các hàm phụ trợ (copy từ code cũ của bạn)
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

# --- 2. TẠO CÁC TAB (ĐÂY LÀ ĐOẠN BẠN ĐANG THIẾU) ---
st.title("SGS CRM V4800 - FINAL FULL FEATURES (ONLINE)")

# Lệnh này định nghĩa tab2 là gì. Nếu thiếu dòng này, code bên dưới sẽ lỗi NameError
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Tổng quan", 
    "💰 Báo giá NCC (DB Giá)", 
    "📝 Báo giá KH", 
    "📦 Đơn đặt hàng", 
    "🚚 Theo dõi & Thanh toán", 
    "⚙️ Master Data"
])

# --- 3. NỘI DUNG CÁC TAB ---

with tab1:
    st.write("Nội dung Dashboard...")
    # ... code tab 1 của bạn ...

# === ĐÂY LÀ ĐOẠN CODE MỚI TÔI GỬI, DÁN VÀO SAU DÒNG NÀY ===
with tab2:
    st.subheader("Database Giá NCC")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                status_box.write("🖼️ Quét ảnh...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=False); ws = wb.active
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        image_map[img.anchor._from.row + 1] = img._data()
                
                status_box.write("📖 Đọc dữ liệu...")
                uploaded_file.seek(0)
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                data_clean = []
                prog_bar = status_box.progress(0); total = len(df_raw)
                
                for i, row in df_raw.iterrows():
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    excel_row_idx = i + 2
                    
                    code = safe_str(row.iloc[1]) 
                    if not code: continue

                    final_link = ""
                    if excel_row_idx in image_map:
                        status_box.write(f"☁️ Up ảnh: {code}...")
                        link = backend.upload_to_drive(io.BytesIO(image_map[excel_row_idx]), f"{safe_filename(code)}.png", "images")
                        if link: final_link = link
                    else:
                        old = safe_str(row.iloc[12]) if len(row) > 12 else ""
                        if "http" in old: final_link = old

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
                        "type": safe_str(row.iloc[13]) if len(row) > 13 else "",
                        "nuoc": safe_str(row.iloc[14]) if len(row) > 14 else "",
                        "_clean_code": clean_lookup_key(code), 
                        "_clean_specs": clean_lookup_key(safe_str(row.iloc[3])), 
                        "_clean_name": clean_lookup_key(safe_str(row.iloc[2]))
                    }
                    data_clean.append(item)
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label="✅ Hoàn tất!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    # HIỂN THỊ
    df_pur = backend.load_data("purchases")
    col_table, col_gallery = st.columns([8, 2]) # 8 phần bảng - 2 phần ảnh
    selected_row_data = None 

    with col_table:
        search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        column_cfg = {
            "no": st.column_config.TextColumn("No", width="small"),
            "item_code": st.column_config.TextColumn("Item code"),
            "item_name": st.column_config.TextColumn("Item name"),
            "specs": st.column_config.TextColumn("Specs"),
            "qty": st.column_config.TextColumn("Q'ty"),
            "buying_price_rmb": st.column_config.TextColumn("Buying price (RMB)"),
            "total_buying_price_rmb": st.column_config.TextColumn("Total buying price (RMB)"),
            "exchange_rate": st.column_config.TextColumn("Exchange rate"),
            "buying_price_vnd": st.column_config.TextColumn("Buying price (VND)"),
            "total_buying_price_vnd": st.column_config.TextColumn("Total buying price (VND)"),
            "leadtime": st.column_config.TextColumn("Leadtime"),
            "supplier_name": st.column_config.TextColumn("Supplier"),
            "image_path": st.column_config.LinkColumn("Images", display_text="Link"),
            "type": st.column_config.TextColumn("Type"),
            "nuoc": st.column_config.TextColumn("N/U/O/C"),
            "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
        }

        display_order = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
        
        event = st.dataframe(
            df_pur,
            column_config=column_cfg,
            column_order=display_order,
            use_container_width=True,
            height=600,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            selected_row_data = df_pur.iloc[idx]

    with col_gallery:
        if selected_row_data is not None:
            code = selected_row_data['item_code']
            name = selected_row_data['item_name']
            specs = selected_row_data['specs']
            img_link = selected_row_data.get('image_path', '')
            
            st.info(f"📌 **{code}**")
            st.caption(f"{name}")
            
            if img_link and "http" in str(img_link):
                with st.spinner("Load ảnh..."):
                    img_bytes = backend.get_image_bytes(img_link)
                    if img_bytes:
                        st.image(img_bytes, caption="Ảnh sản phẩm", use_container_width=True)
                    else:
                        st.error("Lỗi tải ảnh.")
            else:
                st.warning("Không có ảnh")
            
            st.markdown("---")
            st.markdown(f"**Thông số:** {specs}")
            st.markdown(f"**Giá VND:** {selected_row_data['buying_price_vnd']}")
        else:
            st.info("👈 Click vào 1 dòng bất kỳ bên trái để xem ảnh.")

# ... Các tab khác (with tab3, with tab4...)
