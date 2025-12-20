import streamlit as st
import pandas as pd
import os
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import io
import time
import unicodedata
import mimetypes

# --- THƯ VIỆN KẾT NỐI CLOUD ---
try:
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
    from openpyxl.drawing.image import Image as OpenpyxlImage
    from supabase import create_client, Client
    # Google OAuth Libraries
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
except ImportError:
    st.error("⚠️ Thiếu thư viện! Chạy: pip install pandas openpyxl supabase google-api-python-client google-auth-oauthlib")
    st.stop()

# =============================================================================
# 1. CẤU HÌNH & KẾT NỐI
# =============================================================================
APP_VERSION = "V4807 - FULL APP + STRICT FIX"

st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS TÙY CHỈNH ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 20px !important; font-weight: 700 !important; }
    h1 { font-size: 28px !important; } h2 { font-size: 24px !important; } h3 { font-size: 20px !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); }
    .bg-profit { background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); }
    .bg-ncc { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    .bg-recv { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
    .bg-del { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
    .bg-pend { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
    </style>""", unsafe_allow_html=True)

# --- INIT CLOUD SERVICES ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi cấu hình secrets.toml: {e}")
    st.stop()

def get_drive_service():
    try:
        creds = Credentials(
            None, refresh_token=OAUTH_INFO["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=OAUTH_INFO["client_id"],
            client_secret=OAUTH_INFO["client_secret"],
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    except: return None

# --- DRIVE FUNCTIONS ---
def get_or_create_subfolder(folder_name, parent_id):
    srv = get_drive_service()
    if not srv: return None
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    files = srv.files().list(q=q, fields="files(id)").execute().get('files', [])
    if files: return files[0]['id']
    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    file = srv.files().create(body=meta, fields='id').execute()
    try: srv.permissions().create(fileId=file['id'], body={'role': 'reader', 'type': 'anyone'}).execute()
    except: pass
    return file['id']

def upload_to_drive(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return ""
    try:
        target_id = get_or_create_subfolder(sub_folder, ROOT_FOLDER_ID)
        q = f"'{target_id}' in parents and name = '{file_name}' and trashed = false"
        existing_files = srv.files().list(q=q, fields='files(id)').execute().get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        
        if existing_files:
            file_id = existing_files[0]['id']
            srv.files().update(fileId=file_id, media_body=media, fields='id').execute()
        else:
            meta = {'name': file_name, 'parents': [target_id]}
            file = srv.files().create(body=meta, media_body=media, fields='id').execute()
            file_id = file['id']
            
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    except Exception as e: st.error(f"Lỗi Upload: {e}"); return ""

# --- HELPER FUNCTIONS ---
def safe_str(val): return str(val).strip() if val is not None and str(val).lower() not in ['nan', 'none', 'null', 'nat', ''] else ""
def safe_filename(s): return re.sub(r'[^\w\-_]', '_', unicodedata.normalize('NFKD', safe_str(s)).encode('ascii', 'ignore').decode('utf-8')).strip('_')
def to_float(val):
    if not val: return 0.0
    s_clean = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace("rmb", "").replace("vnd", "")
    try: return max([float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", s_clean)])
    except: return 0.0
def fmt_num(x): return "{:,.0f}".format(float(x)) if x else "0"
def clean_lookup_key(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
def parse_formula(formula, buying, ap):
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying)).replace("BUY", str(buying)).replace("AP PRICE", str(ap)).replace("AP", str(ap))
    try: return float(eval(re.sub(r'[^0-9.+\-*/()]', '', expr)))
    except: return 0.0
def safe_write_merged(ws, r, c, v):
    cell = ws.cell(row=r, column=c)
    for rng in ws.merged_cells.ranges:
        if cell.coordinate in rng:
            ws.cell(row=rng.min_row, column=rng.min_col).value = v; return
    cell.value = v

# --- STRICT SCHEMA DEFINITIONS (WHITELIST) ---
# Danh sách này KHỚP 100% với file SQL chuẩn bạn cung cấp.
# Mọi cột khác (ví dụ 'no', 'Delete') sẽ bị hàm save_data lọc bỏ.
SCHEMA_WHITELIST = {
    "crm_purchases": [
        "item_code", "item_name", "specs", "qty", 
        "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
        "buying_price_vnd", "total_buying_price_vnd", "leadtime", 
        "supplier_name", "image_path", "type", "nuoc",
        "_clean_code", "_clean_specs", "_clean_name"
    ],
    "crm_customers": ["short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"],
    "crm_suppliers": ["short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"],
    "crm_shared_history": ["history_id", "date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime", "pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"],
    "db_supplier_orders": ["po_number", "order_date", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path"],
    "db_customer_orders": ["po_number", "order_date", "customer", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "base_buying_vnd", "full_cost_total", "pdf_path"],
    "crm_tracking": ["po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"],
    "crm_payment": ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"],
    "crm_paid_history": ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
}

# --- DATA HANDLERS (STRICT MODE) ---
def load_data(table, cols):
    try:
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        for c in cols: 
            if c not in df.columns: df[c] = ""
        # Thêm cột 'no' giả lập để hiển thị UI đẹp hơn (nhưng ko lưu lại)
        if 'no' not in df.columns: 
            df.insert(0, 'no', range(1, len(df) + 1))
            df['no'] = df['no'].astype(str)
        return df
    except: return pd.DataFrame(columns=cols+['no'])

def save_data(table, df, unique_key=None):
    if df.empty: return
    try:
        # 1. Lấy danh sách cột chuẩn
        valid_cols = SCHEMA_WHITELIST.get(table)
        if not valid_cols: 
            st.warning(f"Chưa định nghĩa Whitelist cho {table}, lưu chế độ thường.")
            valid_cols = df.columns.tolist()

        # 2. Lọc dữ liệu
        recs = df.to_dict(orient='records')
        final_recs = []
        for r in recs:
            clean_r = {}
            for k, v in r.items():
                if k in valid_cols:
                    # Chuyển về string để tránh lỗi định dạng
                    clean_r[k] = str(v) if v is not None and str(v) != 'nan' else None
            if clean_r: final_recs.append(clean_r)
            
        if not final_recs: return

        # 3. Gửi lên Supabase (Có upsert nếu cần)
        if unique_key:
            supabase.table(table).upsert(final_recs, on_conflict=unique_key).execute()
        else:
            supabase.table(table).upsert(final_recs).execute()
            
    except Exception as e:
        st.error(f"❌ Lỗi lưu {table}: {e}")

# --- DEFINITIONS ---
TBL_CUSTOMERS = "crm_customers"
TBL_SUPPLIERS = "crm_suppliers"
TBL_PURCHASES = "crm_purchases"
TBL_SHARED_HISTORY = "crm_shared_history"
TBL_TRACKING = "crm_tracking"
TBL_PAID_HISTORY = "crm_paid_history"
TBL_SUPP_ORDERS = "db_supplier_orders" # Tên chuẩn
TBL_CUST_ORDERS = "db_customer_orders" # Tên chuẩn
TBL_PAYMENTS = "crm_payment" # Tên chuẩn

TEMPLATE_FILE = "AAA-QUOTATION.xlsx" 
ADMIN_PASSWORD = "admin"

QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]

# =============================================================================
# 2. SESSION STATE
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    st.session_state.show_review_table = False
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"

# --- LOAD DATA AT STARTUP ---
with st.spinner("Đang kết nối 2TB Drive và Supabase..."):
    if not get_drive_service(): st.stop()
    customers_df = load_data(TBL_CUSTOMERS, SCHEMA_WHITELIST[TBL_CUSTOMERS])
    suppliers_df = load_data(TBL_SUPPLIERS, SCHEMA_WHITELIST[TBL_SUPPLIERS])
    purchases_df = load_data(TBL_PURCHASES, SCHEMA_WHITELIST[TBL_PURCHASES])
    shared_history_df = load_data(TBL_SHARED_HISTORY, SCHEMA_WHITELIST[TBL_SHARED_HISTORY])
    tracking_df = load_data(TBL_TRACKING, SCHEMA_WHITELIST[TBL_TRACKING])
    payment_df = load_data(TBL_PAYMENTS, SCHEMA_WHITELIST[TBL_PAYMENTS])
    # Load Orders
    db_supplier_orders = load_data(TBL_SUPP_ORDERS, SCHEMA_WHITELIST[TBL_SUPP_ORDERS])
    db_customer_orders = load_data(TBL_CUST_ORDERS, SCHEMA_WHITELIST[TBL_CUST_ORDERS])
    sales_history_df = db_customer_orders.copy()

# =============================================================================
# 3. SIDEBAR & TABS
# =============================================================================
st.sidebar.title("CRM CLOUD (V4807)")
st.sidebar.info("Full Version + Strict Fix")
admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", "🏭 BÁO GIÁ NCC", "💰 BÁO GIÁ KHÁCH", 
    "📑 QUẢN LÝ PO", "🚚 TRACKING & THANH TOÁN", "📂 MASTER DATA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH")
    col_act1, col_act2 = st.columns([1, 1])
    if col_act1.button("🔄 CẬP NHẬT DỮ LIỆU"): st.rerun()
    if col_act2.button("⚠️ XÓA CACHE (Local Only)"): st.rerun()
    
    total_revenue = db_customer_orders['total_price'].apply(to_float).sum() if not db_customer_orders.empty else 0
    total_po_ncc_cost = db_supplier_orders['total_vnd'].apply(to_float).sum() if not db_supplier_orders.empty else 0
    
    total_other_costs = 0.0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            try:
                gap_cost = to_float(r['gap']) * 0.6
                others = (to_float(r['end_user_val']) + to_float(r['buyer_val']) + 
                          to_float(r['import_tax_val']) + to_float(r['vat_val']) + 
                          to_float(r['transportation']) * to_float(r['qty']) + to_float(r['mgmt_fee']))
                total_other_costs += (gap_cost + others)
            except: pass

    total_profit = total_revenue - (total_po_ncc_cost + total_other_costs)
    
    po_ordered_ncc = len(tracking_df[tracking_df['order_type'] == 'NCC']) if not tracking_df.empty else 0
    po_total_recv = len(db_customer_orders['po_number'].unique()) if not db_customer_orders.empty else 0
    po_delivered = len(tracking_df[(tracking_df['order_type'] == 'KH') & (tracking_df['status'] == 'Đã giao hàng')]) if not tracking_df.empty else 0
    po_pending = po_total_recv - po_delivered

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><div>DOANH THU</div><h3>{fmt_num(total_revenue)}</h3></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><div>CHI PHÍ</div><h3>{fmt_num(total_po_ncc_cost + total_other_costs)}</h3></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><div>LỢI NHUẬN</div><h3>{fmt_num(total_profit)}</h3></div>", unsafe_allow_html=True)
    
    st.divider()
    c4, c5, c6, c7 = st.columns(4)
    with c4: st.markdown(f"<div class='card-3d bg-ncc'><div>ĐƠN ĐẶT NCC</div><h3>{po_ordered_ncc}</h3></div>", unsafe_allow_html=True)
    with c5: st.markdown(f"<div class='card-3d bg-recv'><div>PO ĐÃ NHẬN</div><h3>{po_total_recv}</h3></div>", unsafe_allow_html=True)
    with c6: st.markdown(f"<div class='card-3d bg-del'><div>PO ĐÃ GIAO</div><h3>{po_delivered}</h3></div>", unsafe_allow_html=True)
    with c7: st.markdown(f"<div class='card-3d bg-pend'><div>PO CHƯA GIAO</div><h3>{po_pending}</h3></div>", unsafe_allow_html=True)

# --- TAB 2: BÁO GIÁ NCC ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        uploaded_pur = st.file_uploader("Import Excel/CSV (Kèm ảnh)", type=["xlsx", "xls", "csv"])
        if uploaded_pur and st.button("Thực hiện Import"):
            status = st.empty()
            status.info("⏳ Đang đọc file...")
            try:
                if uploaded_pur.name.endswith('.csv'): df_debug = pd.read_csv(uploaded_pur, dtype=str).fillna("")
                else: df_debug = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                
                status.info("⏳ Đang xử lý ảnh...")
                img_row_map = {}
                if uploaded_pur.name.endswith(('.xlsx', '.xls')):
                    try:
                        wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                        for img in getattr(ws, '_images', []):
                            img_row_map[img.anchor._from.row + 1] = img 
                    except: pass
                
                status.info("⏳ Đang ghép dữ liệu...")
                rows = []
                for i, r in df_debug.iterrows():
                    item_code = safe_str(r.iloc[1]) 
                    if not item_code: continue 
                    
                    # Upload ảnh
                    img_url = ""
                    if (i + 2) in img_row_map:
                        try:
                            img_data = io.BytesIO(img_row_map[i + 2]._data())
                            fname = f"IMG_{safe_filename(item_code)}.png"
                            img_url = upload_to_drive(img_data, "CRM_PURCHASE_IMAGES", fname)
                        except: pass

                    item = {
                        "item_code": item_code, 
                        "item_name": safe_str(r.iloc[2]), 
                        "specs": safe_str(r.iloc[3]),
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(r.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                        "leadtime": safe_str(r.iloc[10]), 
                        "supplier_name": safe_str(r.iloc[11]), 
                        "image_path": img_url, 
                        "type": safe_str(r.iloc[13]) if len(r) > 13 else "",
                        "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else "",
                        "_clean_code": clean_lookup_key(item_code),
                        "_clean_specs": clean_lookup_key(safe_str(r.iloc[3])),
                        "_clean_name": clean_lookup_key(safe_str(r.iloc[2]))
                    }
                    rows.append(item)
                
                if len(rows) > 0:
                    status.info(f"⏳ Đang lưu {len(rows)} dòng (Strict Mode - Item Code Key)...")
                    # Dùng item_code làm khóa để update nếu trùng
                    save_data(TBL_PURCHASES, pd.DataFrame(rows), unique_key="item_code")
                    st.success(f"✅ THÀNH CÔNG! Đã import {len(rows)} dòng.")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("⚠️ Không có dữ liệu hợp lệ (Mã hàng trống).")
            except Exception as e: st.error(f"❌ Lỗi: {e}")
            
        st.markdown("---")
        st.write("📸 Cập nhật ảnh thủ công")
        up_img_ncc = st.file_uploader("Upload ảnh", type=["png","jpg","jpeg"])
        item_to_update = st.text_input("Nhập Item Code")
        if st.button("Cập nhật ảnh") and up_img_ncc and item_to_update:
            fname = f"IMG_{safe_filename(item_to_update)}.png"
            url = upload_to_drive(up_img_ncc, "CRM_PURCHASE_IMAGES", fname)
            supabase.table(TBL_PURCHASES).update({"image_path": url}).eq("item_code", item_to_update).execute()
            st.success("Done!"); st.rerun()

    with col_p2:
        c_search, c_clear = st.columns([5, 1])
        with c_search: search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC)", key="search_term_box")
        with c_clear: 
            if st.button("❌"): st.session_state.search_term_box = ""; st.rerun()
        
        if not purchases_df.empty:
            df_show = purchases_df.copy()
            if search_term:
                mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or search_term.lower() in str(x['item_name']).lower(), axis=1)
                df_show = df_show[mask]
            st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Img")}, use_container_width=True, hide_index=True)
        else: st.info("Chưa có dữ liệu.")

# --- TAB 3: BÁO GIÁ KHÁCH ---
with tab3:
    tab3_1, tab3_2 = st.tabs(["TẠO BÁO GIÁ", "LỊCH SỬ CHUNG"])
    with tab3_1:
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            cust_list = customers_df["short_name"].tolist() if not customers_df.empty else []
            sel_cust = st.selectbox("Khách hàng", [""] + cust_list)
        with c2: quote_name = st.text_input("Tên Báo Giá / Mã BG")
        with c3:
             if st.button("✨ TẠO MỚI (RESET)", type="primary"):
                 st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                 st.rerun()

        col_params = st.columns(7)
        pct_end = col_params[0].text_input("EndUser(%)", st.session_state.pct_end)
        pct_buy = col_params[1].text_input("Buyer(%)", st.session_state.pct_buy)
        pct_tax = col_params[2].text_input("Tax(%)", st.session_state.pct_tax)
        pct_vat = col_params[3].text_input("VAT(%)", st.session_state.pct_vat)
        pct_pay = col_params[4].text_input("Payback(%)", st.session_state.pct_pay)
        pct_mgmt = col_params[5].text_input("Mgmt(%)", st.session_state.pct_mgmt)
        val_trans = col_params[6].text_input("Trans(VND)", st.session_state.pct_trans)
        st.session_state.update({f"pct_{k}":v for k,v in zip(["end","buy","tax","vat","pay","mgmt","trans"], [pct_end, pct_buy, pct_tax, pct_vat, pct_pay, pct_mgmt, val_trans])})

        uploaded_rfq = st.file_uploader("📂 Import RFQ", type=["xlsx"])
        if uploaded_rfq and st.button("Load RFQ"):
            try:
                # Clean lookup
                purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                purchases_df["_clean_name"] = purchases_df["item_name"].apply(clean_lookup_key)
                df_rfq = pd.read_excel(uploaded_rfq, header=None, dtype=str).fillna("")
                new_data = []
                for i, r in df_rfq.iloc[1:].iterrows():
                    c_raw=safe_str(r.iloc[1]); n_raw=safe_str(r.iloc[2]); s_raw=safe_str(r.iloc[3]); qty=to_float(r.iloc[4])
                    if qty <= 0: continue
                    clean_c = clean_lookup_key(c_raw); clean_n = clean_lookup_key(n_raw)
                    found = purchases_df[purchases_df["_clean_code"] == clean_c]
                    if found.empty: found = purchases_df[purchases_df["_clean_name"] == clean_n]
                    target = found.iloc[0] if not found.empty else None
                    it = {k:"" for k in QUOTE_KH_COLUMNS}
                    it.update({"no":str(len(new_data)+1), "item_code":c_raw, "item_name":n_raw, "specs":s_raw, "qty":fmt_num(qty)})
                    if target is not None:
                        it.update({
                            "buying_price_rmb": fmt_num(target["buying_price_rmb"]),
                            "total_buying_price_rmb": fmt_num(to_float(target["buying_price_rmb"])*qty),
                            "exchange_rate": fmt_num(target["exchange_rate"]),
                            "buying_price_vnd": fmt_num(target["buying_price_vnd"]),
                            "total_buying_price_vnd": fmt_num(to_float(target["buying_price_vnd"])*qty),
                            "supplier_name": target["supplier_name"], "image_path": target["image_path"], "leadtime": target["leadtime"]
                        })
                    new_data.append(it)
                st.session_state.current_quote_df = pd.DataFrame(new_data)
                st.success(f"Loaded {len(new_data)} items!"); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

        # Editor & Formula
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        ap_formula = f1.text_input("AP Formula", key="ap_f")
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_formula, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
            st.rerun()
        unit_formula = f3.text_input("Unit Formula", key="unit_f")
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_formula, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
            st.rerun()

        edited_df = st.data_editor(st.session_state.current_quote_df, key="quote_editor", use_container_width=True, num_rows="dynamic", column_config={"image_path": st.column_config.ImageColumn("Img")})
        
        # Auto Calc
        pend=to_float(pct_end)/100; pbuy=to_float(pct_buy)/100; ptax=to_float(pct_tax)/100
        pvat=to_float(pct_vat)/100; ppay=to_float(pct_pay)/100; pmgmt=to_float(pct_mgmt)/100
        g_trans=to_float(val_trans); use_global=g_trans>0
        
        df_temp = edited_df.copy()
        for i, r in df_temp.iterrows():
            q=to_float(r.get("qty")); buy=to_float(r.get("buying_price_vnd")); rmb=to_float(r.get("buying_price_rmb"))
            ap=to_float(r.get("ap_price")); unit=to_float(r.get("unit_price"))
            use_trans = g_trans if use_global else to_float(r.get("transportation"))
            
            t_buy=q*buy; ap_tot=ap*q; total=unit*q; gap=total-ap_tot
            v_end=ap_tot*pend; v_buy=total*pbuy; v_tax=t_buy*ptax; v_vat=total*pvat; v_mgmt=total*pmgmt; v_pay=gap*ppay
            cost = t_buy + gap + v_end + v_buy + v_tax + v_vat + v_mgmt + (use_trans*q)
            prof = total - cost + v_pay
            
            df_temp.at[i, "transportation"] = fmt_num(use_trans)
            df_temp.at[i, "total_buying_price_rmb"] = fmt_num(rmb*q)
            df_temp.at[i, "total_buying_price_vnd"] = fmt_num(t_buy)
            df_temp.at[i, "ap_total_vnd"] = fmt_num(ap_tot)
            df_temp.at[i, "total_price_vnd"] = fmt_num(total)
            df_temp.at[i, "gap"] = fmt_num(gap)
            df_temp.at[i, "end_user_val"] = fmt_num(v_end); df_temp.at[i, "buyer_val"] = fmt_num(v_buy)
            df_temp.at[i, "import_tax_val"] = fmt_num(v_tax); df_temp.at[i, "vat_val"] = fmt_num(v_vat)
            df_temp.at[i, "mgmt_fee"] = fmt_num(v_mgmt); df_temp.at[i, "payback_val"] = fmt_num(v_pay)
            df_temp.at[i, "profit_vnd"] = fmt_num(prof)
            df_temp.at[i, "profit_pct"] = f"{(prof/total*100) if total else 0:.2f}%"

        if not df_temp.equals(st.session_state.current_quote_df): st.session_state.current_quote_df = df_temp; st.rerun()

        st.divider()
        if st.button("💾 LƯU BÁO GIÁ"):
            if not sel_cust or not quote_name: st.error("Thiếu thông tin"); st.stop()
            save = st.session_state.current_quote_df.copy()
            save["history_id"] = f"{quote_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            save.update({"date": datetime.now().strftime("%d/%m/%Y"), "quote_no": quote_name, "customer": sel_cust, "pct_end": pct_end, "pct_buy": pct_buy, "pct_tax": pct_tax, "pct_vat": pct_vat, "pct_pay": pct_pay, "pct_mgmt": pct_mgmt, "pct_trans": val_trans})
            save_data(TBL_SHARED_HISTORY, save)
            st.success("Đã lưu!"); st.rerun()

    with tab3_2:
        if not shared_history_df.empty:
            q_h = st.text_input("Tìm kiếm lịch sử")
            df_h = shared_history_df[shared_history_df.apply(lambda x: q_h.lower() in str(x.values).lower(), axis=1)] if q_h else shared_history_df
            st.dataframe(df_h, use_container_width=True)
            sel_id = st.selectbox("Tải lại ID", [""]+list(df_h['history_id'].unique()))
            if st.button("♻️ Tải lại") and sel_id:
                df = shared_history_df[shared_history_df['history_id']==sel_id]
                r0 = df.iloc[0]
                st.session_state.update({f"pct_{k}": str(r0.get(f"pct_{k}",0)) for k in ["end","buy","tax","vat","pay","mgmt","trans"]})
                st.session_state.current_quote_df = df[QUOTE_KH_COLUMNS].copy()
                st.success("Loaded!"); st.rerun()

# --- TAB 4: PO ---
with tab4:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("1. PO NCC")
        suppliers_list = suppliers_df["short_name"].tolist() if not suppliers_df.empty else []
        po_n = st.text_input("Số PO NCC"); sup = st.selectbox("NCC", [""] + suppliers_list)
        up_n = st.file_uploader("Excel NCC", type=["xlsx"])
        if up_n:
            df = pd.read_excel(up_n, dtype=str).fillna(""); tmp = []
            purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
            for i, r in df.iterrows():
                c = safe_str(r.iloc[1]); found = purchases_df[purchases_df["_clean_code"]==clean_lookup_key(c)]
                it = {"item_code":c, "qty":fmt_num(to_float(r.iloc[4])), "specs":safe_str(r.iloc[3]), "item_name":safe_str(r.iloc[2])}
                if not found.empty: it.update({"price_rmb":found.iloc[0]["buying_price_rmb"], "price_vnd":found.iloc[0]["buying_price_vnd"], "supplier":found.iloc[0]["supplier_name"]})
                tmp.append(it)
            st.session_state.temp_supp_order_df = pd.DataFrame(tmp)
        
        ed_n = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", key="en", use_container_width=True)
        if st.button("Lưu PO NCC"):
            df = ed_n.copy(); df["po_number"] = po_n; df["order_date"] = datetime.now().strftime("%d/%m/%Y")
            save_data(TBL_SUPP_ORDERS, df)
            tr = []; 
            for s, g in df.groupby("supplier"): tr.append({"po_no":po_n, "partner":s, "status":"Đã đặt hàng", "order_type":"NCC"})
            save_data(TBL_TRACKING, pd.DataFrame(tr)); st.success("OK")

    with c2:
        st.subheader("2. PO Khách")
        po_c = st.text_input("Số PO Khách"); cus = st.selectbox("Khách", [""] + (customers_df["short_name"].tolist() if not customers_df.empty else []))
        files = st.file_uploader("File PO", accept_multiple_files=True)
        urls = []
        if files:
            for f in files: urls.append(upload_to_drive(f, "CRM_PO_FILES", f"PO_{po_c}_{f.name}"))
            st.success(f"Uploaded {len(urls)} files")
        
        up_c = st.file_uploader("Excel Khách", type=["xlsx"])
        if up_c:
            df = pd.read_excel(up_c, dtype=str).fillna(""); tmp = []
            for i, r in df.iterrows():
                c = safe_str(r.iloc[1]); price = 0
                hist = sales_history_df[(sales_history_df["customer"]==cus) & (sales_history_df["item_code"]==c)]
                if not hist.empty: price = to_float(hist.iloc[-1]["unit_price"])
                tmp.append({"item_code":c, "qty":fmt_num(to_float(r.iloc[4])), "unit_price":fmt_num(price), "specs":safe_str(r.iloc[3]), "item_name":safe_str(r.iloc[2])})
            st.session_state.temp_cust_order_df = pd.DataFrame(tmp)
            
        ed_c = st.data_editor(st.session_state.temp_cust_order_df, num_rows="dynamic", key="ec", use_container_width=True)
        if st.button("Lưu PO Khách"):
            df = ed_c.copy(); df["po_number"] = po_c; df["customer"] = cus; df["order_date"] = datetime.now().strftime("%d/%m/%Y"); df["pdf_path"] = ",".join(urls)
            save_data(TBL_CUST_ORDERS, df)
            save_data(TBL_TRACKING, pd.DataFrame([{"po_no":po_c, "partner":cus, "status":"Đang đợi hàng về", "order_type":"KH"}])); st.success("OK")

# --- TAB 5: TRACKING ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI", "LỊCH SỬ THANH TOÁN"])
    with t5_1:
        c1, c2 = st.columns(2)
        view_id = c1.text_input("Tracking ID (PO No)")
        up_prf = c1.file_uploader("Up ảnh proof", accept_multiple_files=True)
        if c1.button("Up Proof") and view_id and up_prf:
            urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"prf_{view_id}_{f.name}") for f in up_prf]
            # Update proof image
            row = tracking_df[tracking_df['po_no']==view_id]
            if not row.empty:
                curr = json.loads(row.iloc[0]['proof_image']) if row.iloc[0]['proof_image'] else []
                supabase.table(TBL_TRACKING).update({"proof_image": json.dumps(curr+urls)}).eq("po_no", view_id).execute()
                st.success("OK")
        
        if c2.button("Xem Proof") and view_id:
            row = tracking_df[tracking_df['po_no']==view_id]
            if not row.empty and row.iloc[0]['proof_image']:
                for u in json.loads(row.iloc[0]['proof_image']): st.image(u)

        ed_tr = st.data_editor(tracking_df[tracking_df["finished"]!="1"], key="etr", use_container_width=True, column_config={"status": st.column_config.SelectboxColumn(options=["Đã đặt hàng", "Hàng đã về VN", "Đã giao hàng"])})
        if st.button("Cập nhật Tracking"):
            save_data(TBL_TRACKING, ed_tr)
            for i, r in ed_tr.iterrows():
                if r['status'] in ['Đã giao hàng', 'Hàng đã nhận ở VP']:
                     supabase.table(TBL_TRACKING).update({'finished':'1', 'last_update':datetime.now().strftime("%d/%m/%Y")}).eq('po_no', r['po_no']).eq('partner', r['partner']).execute()
                     if r['order_type'] == 'KH':
                        save_data(TBL_PAYMENTS, pd.DataFrame([{"po_no":r['po_no'], "customer":r['partner'], "status":"Chưa thanh toán"}]))
            st.success("Updated!"); st.rerun()
    
    with t5_2:
        ed_pay = st.data_editor(payment_df[payment_df["status"]!="Đã thanh toán"], key="ep", use_container_width=True)
        if st.button("Update Payment"): save_data(TBL_PAYMENTS, ed_pay); st.success("OK")
        
        pop = st.selectbox("Chọn PO Paid", ed_pay["po_no"].unique()) if not ed_pay.empty else None
        if st.button("Xác nhận Paid") and pop:
            supabase.table(TBL_PAYMENTS).update({"status":"Đã thanh toán", "paid_date":datetime.now().strftime("%d/%m/%Y")}).eq("po_no", pop).execute()
            st.success("Done"); st.rerun()

# --- TAB 6: MASTER ---
with tab6:
    st.write("Template"); up_t = st.file_uploader("Up Template", type=["xlsx"])
    if up_t and st.button("Save Tpl"): 
        with open(TEMPLATE_FILE, "wb") as f: f.write(up_t.getbuffer())
        st.success("OK")
    
    if is_admin:
        c1, c2 = st.columns(2)
        with c1: 
            st.write("KH"); ed_c = st.data_editor(customers_df, num_rows="dynamic", use_container_width=True, key="editor_kh"); 
            if st.button("Lưu KH"): save_data(TBL_CUSTOMERS, ed_c); st.success("OK")
        with c2: 
            st.write("NCC"); ed_s = st.data_editor(suppliers_df, num_rows="dynamic", use_container_width=True, key="editor_ncc"); 
            if st.button("Lưu NCC"): save_data(TBL_SUPPLIERS, ed_s); st.success("OK")
    else: st.warning("Admin only")
