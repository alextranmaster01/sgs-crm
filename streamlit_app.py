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
APP_VERSION = "V4804 - FIX SUPABASE COLUMN MISMATCH"
RELEASE_NOTE = """
- **Fix lỗi 'Could not find column':** Tự động bỏ qua cột 'no' nếu DB chưa tạo, giúp dữ liệu vẫn vào được.
- **UI:** Thêm nút xóa bộ lọc tìm kiếm nhanh.
- **Stability:** Giữ nguyên tính năng Import ảnh và Ghi đè thông minh.
"""

st.set_page_config(page_title=f"CRM V4804 - {APP_VERSION}", layout="wide", page_icon="☁️")

# --- CSS TÙY CHỈNH ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 30px !important; font-weight: 900 !important; padding: 10px 20px !important; }
    h1 { font-size: 32px !important; } h2 { font-size: 28px !important; } h3 { font-size: 24px !important; }
    .card-3d { border-radius: 15px; padding: 20px; color: white; text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.19); margin-bottom: 20px; height: 100%; display: flex; flex-direction: column; justify-content: center; }
    .card-3d:hover { transform: translateY(-5px); box-shadow: 0 14px 28px rgba(0,0,0,0.25); }
    .card-title { font-size: 18px; font-weight: 500; margin-bottom: 10px; opacity: 0.9; text-transform: uppercase; }
    .card-value { font-size: 32px; font-weight: bold; text-shadow: 1px 1px 2px rgba(0,0,0,0.3); }
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
def fmt_num(x): 
    try: return "{:,.0f}".format(float(x))
    except: return "0"
def clean_lookup_key(s):
    s_str = str(s)
    try: 
        if float(s_str).is_integer(): s_str = str(int(float(s_str)))
    except: pass
    return re.sub(r'[^a-zA-Z0-9]', '', s_str).lower()
def calc_eta(date_str, lead):
    try:
        dt = date_str if isinstance(date_str, datetime) else datetime.strptime(date_str, "%d/%m/%Y")
        days = int(re.findall(r'\d+', str(lead))[0]) if re.findall(r'\d+', str(lead)) else 0
        return (dt + timedelta(days=days)).strftime("%d/%m/%Y")
    except: return ""
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

# --- DATA HANDLERS ---
def load_data(table, cols):
    try:
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        for c in cols: 
            if c not in df.columns: df[c] = ""
        return df[cols]
    except: return pd.DataFrame(columns=cols)

def save_data(table, df):
    if df.empty: return
    try:
        df_clean = df.where(pd.notnull(df), None)
        recs = df_clean.to_dict(orient='records')
        final_recs = []
        for r in recs:
            clean_r = {k: (str(v) if v is not None else "") for k, v in r.items()}
            final_recs.append(clean_r)
        
        # Thử lưu bình thường
        try:
            supabase.table(table).upsert(final_recs).execute()
        except Exception as e_inner:
            # Nếu lỗi do thiếu cột 'no' (PGRST204), thử bỏ cột 'no' và lưu lại
            err_msg = str(e_inner)
            if "Could not find the 'no' column" in err_msg:
                st.warning(f"⚠️ Cảnh báo Supabase: Bảng '{table}' thiếu cột 'no'. Hệ thống sẽ tự động bỏ qua cột này để lưu dữ liệu.")
                for r in final_recs:
                    if 'no' in r: del r['no']
                supabase.table(table).upsert(final_recs).execute()
            else:
                raise e_inner # Nếu lỗi khác thì ném ra ngoài

    except Exception as e: 
        st.error(f"❌ LỖI LƯU DATA VÀO {table}: {e}")

# --- DEFINITIONS ---
TBL_CUSTOMERS = "crm_customers"; TBL_SUPPLIERS = "crm_suppliers"; TBL_PURCHASES = "crm_purchases"
TBL_SHARED_HISTORY = "crm_shared_history"; TBL_TRACKING = "crm_tracking"; TBL_PAYMENTS = "crm_payments"
TBL_PAID_HISTORY = "crm_paid_history"; TBL_SUPP_ORDERS = "crm_supplier_orders"; TBL_CUST_ORDERS = "crm_customer_orders"

MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SHARED_HISTORY_COLS = ["history_id", "date", "quote_no", "customer"] + QUOTE_KH_COLUMNS + ["pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]

TEMPLATE_FILE = "AAA-QUOTATION.xlsx" 
ADMIN_PASSWORD = "admin"

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
    customers_df = load_data(TBL_CUSTOMERS, MASTER_COLUMNS)
    suppliers_df = load_data(TBL_SUPPLIERS, MASTER_COLUMNS)
    purchases_df = load_data(TBL_PURCHASES, PURCHASE_COLUMNS)
    shared_history_df = load_data(TBL_SHARED_HISTORY, SHARED_HISTORY_COLS)
    tracking_df = load_data(TBL_TRACKING, TRACKING_COLS)
    payment_df = load_data(TBL_PAYMENTS, PAYMENT_COLS)
    paid_history_df = load_data(TBL_PAID_HISTORY, PAYMENT_COLS)
    db_supplier_orders = load_data(TBL_SUPP_ORDERS, [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
    db_customer_orders = load_data(TBL_CUST_ORDERS, [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

sales_history_df = db_customer_orders.copy()

# =============================================================================
# 3. SIDEBAR & TABS
# =============================================================================
st.sidebar.title("CRM CLOUD (V4804)")
st.sidebar.info("OAuth 2.0 Connected")
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
    
    total_revenue = db_customer_orders['total_price'].apply(to_float).sum()
    total_po_ncc_cost = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    total_other_costs = 0.0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            try:
                gap_cost = to_float(r['gap']) * 0.6
                total_other_costs += (gap_cost + to_float(r['end_user_val']) + to_float(r['buyer_val']) + 
                                      to_float(r['import_tax_val']) + to_float(r['vat_val']) + 
                                      to_float(r['transportation']) * to_float(r['qty']) + to_float(r['mgmt_fee']))
            except: pass

    total_profit = total_revenue - (total_po_ncc_cost + total_other_costs)
    po_ordered_ncc = len(tracking_df[tracking_df['order_type'] == 'NCC'])
    po_total_recv = len(db_customer_orders['po_number'].unique())
    po_delivered = len(tracking_df[(tracking_df['order_type'] == 'KH') & (tracking_df['status'] == 'Đã giao hàng')])
    po_pending = po_total_recv - po_delivered

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><div class='card-title'>DOANH THU (VND)</div><div class='card-value'>{fmt_num(total_revenue)}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><div class='card-title'>CHI PHÍ (VND)</div><div class='card-value'>{fmt_num(total_po_ncc_cost + total_other_costs)}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><div class='card-title'>LỢI NHUẬN (VND)</div><div class='card-value'>{fmt_num(total_profit)}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    c4, c5, c6, c7 = st.columns(4)
    with c4: st.markdown(f"<div class='card-3d bg-ncc'><div class='card-title'>ĐƠN ĐẶT NCC</div><div class='card-value'>{po_ordered_ncc}</div></div>", unsafe_allow_html=True)
    with c5: st.markdown(f"<div class='card-3d bg-recv'><div class='card-title'>PO ĐÃ NHẬN</div><div class='card-value'>{po_total_recv}</div></div>", unsafe_allow_html=True)
    with c6: st.markdown(f"<div class='card-3d bg-del'><div class='card-title'>PO ĐÃ GIAO</div><div class='card-value'>{po_delivered}</div></div>", unsafe_allow_html=True)
    with c7: st.markdown(f"<div class='card-3d bg-pend'><div class='card-title'>PO CHƯA GIAO</div><div class='card-value'>{po_pending}</div></div>", unsafe_allow_html=True)
    
    st.divider()
    c_top1, c_top2 = st.columns(2)
    with c_top1:
        st.subheader("🥇 Top Khách Hàng")
        if not db_customer_orders.empty:
            top = db_customer_orders.copy(); top['val'] = top['total_price'].apply(to_float)
            st.dataframe(top.groupby('customer')['val'].sum().sort_values(ascending=False).head(10).apply(fmt_num), use_container_width=True)
    with c_top2:
        st.subheader("🏭 Top NCC")
        if not db_supplier_orders.empty:
            top = db_supplier_orders.copy(); top['val'] = top['total_vnd'].apply(to_float)
            st.dataframe(top.groupby('supplier')['val'].sum().sort_values(ascending=False).head(10).apply(fmt_num), use_container_width=True)

# --- TAB 2: BÁO GIÁ NCC (FIXED IMPORT, OVERWRITE & NO-COL) ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        uploaded_pur = st.file_uploader("Import Excel (Kèm ảnh)", type=["xlsx"])
        
        if uploaded_pur and st.button("Thực hiện Import"):
            status = st.empty()
            status.info("⏳ Đang đọc file Excel...")
            try:
                df_debug = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                
                status.info("⏳ Đang xử lý ảnh từ Excel...")
                wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                img_row_map = {}
                for img in getattr(ws, '_images', []):
                    try:
                        rid = img.anchor._from.row + 1 
                        img_row_map[rid] = img 
                    except: pass
                
                status.info("⏳ Đang ghép dữ liệu và Upload ảnh (chế độ Ghi Đè)...")
                rows = []
                for i, r in df_debug.iterrows():
                    item_code = safe_str(r.iloc[1]) 
                    if not item_code: continue 
                    excel_row_idx = i + 2
                    
                    img_url = ""
                    if excel_row_idx in img_row_map:
                        try:
                            img_obj = img_row_map[excel_row_idx]
                            img_data = io.BytesIO(img_obj._data())
                            fname = f"IMG_{safe_filename(item_code)}.png"
                            img_url = upload_to_drive(img_data, "CRM_PURCHASE_IMAGES", fname)
                        except: pass

                    item = {
                        "no": safe_str(r.iloc[0]), 
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
                        "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else ""
                    }
                    rows.append(item)
                
                if len(rows) > 0:
                    status.info(f"⏳ Đang lưu {len(rows)} dòng vào Supabase...")
                    save_data(TBL_PURCHASES, pd.DataFrame(rows))
                    st.success(f"✅ THÀNH CÔNG! Đã import {len(rows)} dòng. Đang tải lại...")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("⚠️ KHÔNG TÌM THẤY DỮ LIỆU! Cột Mã hàng (Cột B) bị trống.")
            except Exception as e:
                st.error(f"❌ LỖI KHI IMPORT: {e}")
            
        st.markdown("---")
        st.write("📸 Cập nhật ảnh (Manual)")
        up_img_ncc = st.file_uploader("Upload ảnh", type=["png","jpg","jpeg"])
        item_to_update = st.text_input("Nhập mã Item Code")
        if st.button("Cập nhật ảnh") and up_img_ncc and item_to_update:
            fname = f"IMG_{safe_filename(item_to_update)}.png"
            url = upload_to_drive(up_img_ncc, "CRM_PURCHASE_IMAGES", fname)
            supabase.table(TBL_PURCHASES).update({"image_path": url}).eq("item_code", item_to_update).execute()
            st.success("Done!"); st.rerun()

    with col_p2:
        c_search, c_clear = st.columns([5, 1])
        with c_search:
            search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC)", key="search_term_box")
        with c_clear:
            if st.button("❌ Xóa"): 
                st.session_state.search_term_box = ""
                st.rerun()
        
        if search_term: st.caption(f"⚠️ Đang lọc theo: '{search_term}'.")
        if not purchases_df.empty:
            df_show = purchases_df.copy()
            if search_term:
                mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or 
                                                 search_term.lower() in str(x['item_name']).lower() or 
                                                 search_term.lower() in str(x['specs']).lower(), axis=1)
                df_show = df_show[mask]
            st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Img")}, use_container_width=True, hide_index=True)
        else: st.info("Chưa có dữ liệu. Vui lòng Import Excel.")

# --- TAB 3: BÁO GIÁ KHÁCH ---
with tab3:
    tab3_1, tab3_2 = st.tabs(["TẠO BÁO GIÁ", "LỊCH SỬ CHUNG"])
    with tab3_1:
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            cust_list = customers_df["short_name"].tolist()
            sel_cust = st.selectbox("Khách hàng", [""] + cust_list)
        with c2: quote_name = st.text_input("Tên Báo Giá / Mã BG")
        with c3:
             if st.button("✨ TẠO MỚI (RESET)", type="primary"):
                 st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                 for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"
                 st.rerun()

        st.markdown("**Tham số chi phí (%)**")
        col_params = st.columns(8)
        pct_end = col_params[0].text_input("EndUser(%)", st.session_state.pct_end)
        pct_buy = col_params[1].text_input("Buyer(%)", st.session_state.pct_buy)
        pct_tax = col_params[2].text_input("Tax(%)", st.session_state.pct_tax)
        pct_vat = col_params[3].text_input("VAT(%)", st.session_state.pct_vat)
        pct_pay = col_params[4].text_input("Payback(%)", st.session_state.pct_pay)
        pct_mgmt = col_params[5].text_input("Mgmt(%)", st.session_state.pct_mgmt)
        val_trans = col_params[6].text_input("Trans(VND)", st.session_state.pct_trans)
        
        st.session_state.update({f"pct_{k}":v for k,v in zip(["end","buy","tax","vat","pay","mgmt","trans"], [pct_end, pct_buy, pct_tax, pct_vat, pct_pay, pct_mgmt, val_trans])})

        c_imp1, c_imp2 = st.columns(2)
        with c_imp1:
            uploaded_rfq = st.file_uploader("📂 Import RFQ", type=["xlsx"])
            if uploaded_rfq and st.button("Load RFQ"):
                try:
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
                        it.update({"no":safe_str(r.iloc[0]), "item_code":c_raw, "item_name":n_raw, "specs":s_raw, "qty":fmt_num(qty)})
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

        # Editor
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
        c_rev, c_sav, c_exp = st.columns(3)
        with c_rev:
            if st.button("🔍 REVIEW"): st.session_state.show_review_table = not st.session_state.get('show_review_table', False)
        if st.session_state.get('show_review_table', False):
            st.dataframe(st.session_state.current_quote_df[["item_code", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]], use_container_width=True)

        with c_sav:
            if st.button("💾 LƯU (CLOUD)"):
                if not sel_cust or not quote_name: st.error("Thiếu thông tin"); st.stop()
                save = st.session_state.current_quote_df.copy()
                save["history_id"] = f"{quote_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                save.update({"date": datetime.now().strftime("%d/%m/%Y"), "quote_no": quote_name, "customer": sel_cust, "pct_end": pct_end, "pct_buy": pct_buy, "pct_tax": pct_tax, "pct_vat": pct_vat, "pct_pay": pct_pay, "pct_mgmt": pct_mgmt, "pct_trans": val_trans})
                save_data(TBL_SHARED_HISTORY, save)
                st.success("Đã lưu!"); st.rerun()

        with c_exp:
            if st.button("XUẤT EXCEL"):
                if not os.path.exists(TEMPLATE_FILE): st.error("Thiếu template")
                else:
                    out = io.BytesIO()
                    wb = load_workbook(TEMPLATE_FILE); ws = wb.active
                    safe_write_merged(ws, 1, 2, sel_cust); safe_write_merged(ws, 2, 8, quote_name); safe_write_merged(ws, 1, 8, datetime.now().strftime("%d-%b-%Y"))
                    for i, r in st.session_state.current_quote_df.iterrows():
                        ri = 11 + i
                        safe_write_merged(ws, ri, 1, r["no"]); safe_write_merged(ws, ri, 3, r["item_code"])
                        safe_write_merged(ws, ri, 4, r["item_name"]); safe_write_merged(ws, ri, 5, r["specs"])
                        safe_write_merged(ws, ri, 6, to_float(r["qty"])); safe_write_merged(ws, ri, 7, to_float(r["unit_price"])); safe_write_merged(ws, ri, 8, to_float(r["total_price_vnd"]))
                    wb.save(out)
                    st.download_button("Download", out.getvalue(), f"Quote_{quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab3_2:
        st.subheader("Tra cứu lịch sử chung (Cloud)")
        if not shared_history_df.empty:
            q_h = st.text_input("Tìm kiếm lịch sử")
            df_h = shared_history_df[shared_history_df.apply(lambda x: q_h.lower() in str(x.values).lower(), axis=1)] if q_h else shared_history_df
            st.dataframe(df_h, use_container_width=True)
            sel_id = st.selectbox("Tải lại báo giá cũ", [""]+list(df_h['history_id'].unique()))
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
        po_n = st.text_input("Số PO NCC"); sup = st.selectbox("NCC", [""]+suppliers_df["short_name"].tolist())
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
            for s, g in df.groupby("supplier"): tr.append({"no":str(len(tracking_df)+len(tr)+1), "po_no":po_n, "partner":s, "status":"Đã đặt hàng", "order_type":"NCC"})
            save_data(TBL_TRACKING, pd.DataFrame(tr)); st.success("OK")

    with c2:
        st.subheader("2. PO Khách")
        po_c = st.text_input("Số PO Khách"); cus = st.selectbox("Khách", [""]+customers_df["short_name"].tolist())
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
            save_data(TBL_TRACKING, pd.DataFrame([{"no":str(len(tracking_df)+1), "po_no":po_c, "partner":cus, "status":"Đang đợi hàng về", "order_type":"KH"}])); st.success("OK")

# --- TAB 5: TRACKING ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI", "LỊCH SỬ THANH TOÁN"])
    with t5_1:
        c1, c2 = st.columns(2)
        view_id = c1.text_input("Tracking ID")
        up_prf = c1.file_uploader("Up ảnh proof", accept_multiple_files=True)
        if c1.button("Up Proof") and view_id and up_prf:
            urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"prf_{view_id}_{f.name}") for f in up_prf]
            row = tracking_df[tracking_df['no']==view_id]
            if not row.empty:
                curr = json.loads(row.iloc[0]['proof_image']) if row.iloc[0]['proof_image'] else []
                supabase.table(TBL_TRACKING).update({"proof_image": json.dumps(curr+urls)}).eq("no", view_id).execute()
                st.success("OK")
        
        if c2.button("Xem Proof") and view_id:
            row = tracking_df[tracking_df['no']==view_id]
            if not row.empty and row.iloc[0]['proof_image']:
                for u in json.loads(row.iloc[0]['proof_image']): st.image(u)

        ed_tr = st.data_editor(tracking_df[tracking_df["finished"]!="1"], key="etr", use_container_width=True, column_config={"status": st.column_config.SelectboxColumn(options=["Đã đặt hàng", "Hàng đã về VN", "Đã giao hàng"])})
        if st.button("Cập nhật Tracking"):
            save_data(TBL_TRACKING, ed_tr)
            for i, r in ed_tr.iterrows():
                if r['status'] in ['Đã giao hàng', 'Hàng đã nhận ở VP']:
                    supabase.table(TBL_TRACKING).update({'finished':'1', 'last_update':datetime.now().strftime("%d/%m/%Y")}).eq('no', r['no']).execute()
                    if r['order_type'] == 'KH':
                        save_data(TBL_PAYMENTS, pd.DataFrame([{"no":str(len(payment_df)+1), "po_no":r['po_no'], "customer":r['partner'], "status":"Chưa thanh toán"}]))
            st.success("Updated!"); st.rerun()
    
    with t5_2:
        ed_pay = st.data_editor(payment_df[payment_df["status"]!="Đã thanh toán"], key="ep", use_container_width=True)
        if st.button("Update Payment"): save_data(TBL_PAYMENTS, ed_pay); st.success("OK")
        
        pop = st.selectbox("Chọn PO Paid", ed_pay["po_no"].unique())
        if st.button("Xác nhận Paid"):
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
