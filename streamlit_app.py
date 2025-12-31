import streamlit as st
import pandas as pd
import backend
import time
import io
import re
from openpyxl import load_workbook

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="SGS CRM V4800 - ONLINE", layout="wide", page_icon="🪶")
st.markdown("""<style>.stTabs [data-baseweb="tab-list"] { gap: 10px; } .stTabs [data-baseweb="tab"] { background-color: #ecf0f1; border-radius: 4px 4px 0 0; padding: 10px 20px; font-weight: bold; } .stTabs [aria-selected="true"] { background-color: #3498db; color: white; }</style>""", unsafe_allow_html=True)

# --- LOGIC ---
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
    st.session_state.quote_df = pd.DataFrame(columns=["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"])

st.title("SGS CRM V4800 - FINAL FULL FEATURES (ONLINE)")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Tổng quan", "💰 Báo giá NCC (DB Giá)", "📝 Báo giá KH", "📦 Đơn đặt hàng", "🚚 Theo dõi & Thanh toán", "⚙️ Master Data"])

# TAB 1: DASHBOARD
with tab1:
    st.subheader("DASHBOARD KINH DOANH")
    if st.button("🔄 CẬP NHẬT DATA", type="primary"): st.rerun()
    
    db_cust_orders = backend.load_data("customer_orders")
    sales_history = backend.load_data("sales_history")
    payment_df = backend.load_data("payment")
    paid_history = backend.load_data("paid_history")

    rev = db_cust_orders['total_price'].apply(to_float).sum() if not db_cust_orders.empty else 0
    profit = sales_history['profit'].apply(to_float).sum() if not sales_history.empty else 0
    cost = rev - profit
    paid_count = len(paid_history)
    unpaid_count = len(payment_df[payment_df['status'] != "Đã thanh toán"]) if 'status' in payment_df.columns else 0

    c1, c2, c3 = st.columns(3)
    c1.info(f"DOANH THU: {fmt_num(rev)}")
    c2.warning(f"CHI PHÍ: {fmt_num(cost)}")
    c3.success(f"LỢI NHUẬN: {fmt_num(profit)}")
    st.write(f"PO Đã TT: {paid_count} | PO Chưa TT: {unpaid_count}")

# TAB 2: DB GIÁ NCC
with tab2:
    st.subheader("Database Giá NCC (Tự động tách ảnh & Upload lên Drive)")
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                status_box.write("📖 Đọc Excel...")
                df_raw = pd.read_excel(uploaded_file, header=None, dtype=str).fillna("")
                
                start_row = 0
                for i in range(min(20, len(df_raw))):
                    if 'item code' in str(df_raw.iloc[i].values).lower() or 'mã hàng' in str(df_raw.iloc[i].values).lower():
                        start_row = i + 1; break
                
                status_box.write("🖼️ Tách ảnh...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=True)
                image_map = {img.anchor._from.row: img._data() for img in wb.active._images} if hasattr(wb.active, '_images') else {}
                
                status_box.write(f"✅ Thấy {len(image_map)} ảnh. Đang upload...")
                data_clean = []
                prog_bar = status_box.progress(0)
                total = len(df_raw) - start_row
                
                for idx, i in enumerate(range(start_row, len(df_raw))):
                    prog_bar.progress(min((idx + 1) / total, 1.0))
                    row = df_raw.iloc[i]
                    def get(x): return safe_str(row[x]) if x < len(row) else ""
                    code = get(1)
                    if not code: continue
                    
                    final_link = ""
                    if i in image_map:
                        status_box.write(f"☁️ Up: {code}...")
                        link = backend.upload_to_drive(io.BytesIO(image_map[i]), f"{safe_filename(code)}.png")
                        if link: final_link = link
                    else:
                        old = get(12)
                        if "http" in old: final_link = old

                    data_clean.append({
                        "no": get(0), "item_code": code, "item_name": get(2), "specs": get(3),
                        "qty": fmt_num(to_float(get(4))), "buying_price_rmb": fmt_num(to_float(get(5))),
                        "total_buying_price_rmb": fmt_num(to_float(get(6))), "exchange_rate": fmt_num(to_float(get(7))),
                        "buying_price_vnd": fmt_num(to_float(get(8))), "total_buying_price_vnd": fmt_num(to_float(get(9))),
                        "leadtime": get(10), "supplier_name": get(11), "image_path": final_link,
                        "_clean_code": clean_lookup_key(code), "_clean_specs": clean_lookup_key(get(3)), "_clean_name": clean_lookup_key(get(2))
                    })
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label="✅ Hoàn tất!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    df_pur = backend.load_data("purchases")
    search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
    if search and not df_pur.empty:
        df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

    # CẤU HÌNH HIỂN THỊ ẢNH
    cfg = {
        "image_path": st.column_config.ImageColumn("Hình Ảnh", width="small"),
        "total_buying_price_vnd": st.column_config.NumberColumn("Tổng Mua", format="%d"),
        "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
    }
    order = ["image_path", "no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name"]
    
    edited_pur = st.data_editor(df_pur, column_config=cfg, column_order=order, use_container_width=True, height=600, key="ed_pur")
    if st.button("💾 Lưu thay đổi"): backend.save_data("purchases", edited_pur)

# CÁC TAB CÒN LẠI (GIỮ NGUYÊN CODE CŨ CỦA BẠN HOẶC COPY TỪ LẦN TRƯỚC)
# ...
