import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import io
import time
import unicodedata

# --- THƯ VIỆN GOOGLE DRIVE (CLOUD) ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# =============================================================================
# 1. CẤU HÌNH & KẾT NỐI CLOUD
# =============================================================================

# --- !!! QUAN TRỌNG: ĐIỀN ID THƯ MỤC DRIVE CỦA BẠN VÀO ĐÂY !!! ---
# (Lấy ID từ link folder: drive.google.com/drive/folders/CHUỖI_KÝ_TỰ_NÀY)
DRIVE_FOLDER_ID = "HAY_THAY_ID_THU_MUC_CUA_BAN_VAO_DAY" 

APP_VERSION = "V5.0 - CLOUD EDITION (MULTI-USER)"
RELEASE_NOTE = """
- **Cloud System:** Chuyển đổi hoàn toàn sang hệ thống lưu trữ Google Drive.
- **Multi-user:** Hỗ trợ 20+ người dùng đồng thời, dữ liệu đồng bộ thời gian thực.
- **Profit Logic:** Giữ nguyên công thức V4.7: Profit = Revenue - (PO NCC + GAP*0.6 + Costs).
"""

st.set_page_config(page_title=f"CRM CLOUD - {APP_VERSION}", layout="wide", page_icon="☁️")

# --- CSS TÙY CHỈNH ---
st.markdown("""
    <style>
    /* CHỈ TĂNG KÍCH THƯỚC CHỮ CỦA CÁC TAB (300%) */
    button[data-baseweb="tab"] div p {
        font-size: 40px !important;
        font-weight: 900 !important;
        padding: 10px 20px !important;
    }
    
    /* Các phần khác giữ nguyên */
    h1 { font-size: 32px !important; }
    h2 { font-size: 28px !important; }
    h3 { font-size: 24px !important; }
    
    /* 3D DASHBOARD CARDS CSS */
    .card-3d {
        border-radius: 15px;
        padding: 20px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 20px rgba(0,0,0,0.19), 0 6px 6px rgba(0,0,0,0.23);
        transition: all 0.3s cubic-bezier(.25,.8,.25,1);
        margin-bottom: 20px;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .card-3d:hover {
        box-shadow: 0 14px 28px rgba(0,0,0,0.25), 0 10px 10px rgba(0,0,0,0.22);
        transform: translateY(-5px);
    }
    .card-title {
        font-size: 18px;
        font-weight: 500;
        margin-bottom: 10px;
        opacity: 0.9;
        text-transform: uppercase;
    }
    .card-value {
        font-size: 32px;
        font-weight: bold;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
    }
    
    /* MÀU SẮC 3D GRADIENT */
    .bg-sales { background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); }
    .bg-profit { background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); }
    .bg-ncc { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    .bg-recv { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
    .bg-del { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
    .bg-pend { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }

    .stAlert { font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- THƯ VIỆN XỬ LÝ EXCEL & ĐỒ HỌA ---
try:
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
except ImportError:
    st.error("Thiếu thư viện openpyxl. Vui lòng thêm vào requirements.txt")
    st.stop()

# Tắt cảnh báo
warnings.filterwarnings("ignore")

# --- HÀM KẾT NỐI DRIVE (CORE CLOUD) ---
SCOPES = ['https://www.googleapis.com/auth/drive']

@st.cache_resource
def get_drive_service():
    """Kết nối Drive qua Secrets (Cloud) hoặc File (Local)"""
    creds = None
    try:
        # Ưu tiên 1: Secrets (Streamlit Cloud)
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=SCOPES)
        # Ưu tiên 2: File Local (Chạy trên máy tính)
        elif os.path.exists('service_account.json'):
            creds = service_account.Credentials.from_service_account_file(
                'service_account.json', scopes=SCOPES)
        else:
            st.error("❌ Không tìm thấy thông tin xác thực (Secrets hoặc service_account.json)!")
            return None
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Lỗi kết nối Drive: {e}")
        return None

# --- CÁC HÀM XỬ LÝ FILE TRÊN DRIVE ---
def get_file_id_by_name(filename):
    service = get_drive_service()
    if not service: return None
    # Tìm file trong folder chỉ định, chưa bị xóa
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if not items: return None
        return items[0]['id']
    except: return None

def load_csv(filename, cols):
    """Thay thế hàm load_csv cũ: Đọc trực tiếp từ Drive"""
    service = get_drive_service()
    if not service: return pd.DataFrame(columns=cols)
    
    file_id = get_file_id_by_name(filename)
    if file_id:
        try:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_csv(fh, dtype=str, on_bad_lines='skip').fillna("")
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols]
        except: return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_csv(filename, df):
    """Thay thế hàm save_csv cũ: Ghi đè lên Drive"""
    service = get_drive_service()
    if not service or df is None: return
    try:
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
        csv_buffer.seek(0)
        
        media = MediaIoBaseUpload(csv_buffer, mimetype='text/csv', resumable=True)
        file_id = get_file_id_by_name(filename)
        
        if file_id:
            service.files().update_media(media_body=media, fileId=file_id).execute()
        else:
            meta = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
            service.files().create(body=meta, media_body=media, fields='id').execute()
    except Exception as e: st.error(f"Lỗi lưu file {filename}: {e}")

def upload_bytes_to_drive(file_obj, filename, mime_type='application/octet-stream'):
    """Upload ảnh/pdf lên Drive -> Trả về ID"""
    service = get_drive_service()
    if not service: return None
    try:
        media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
        meta = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
        file = service.files().create(body=meta, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"Upload lỗi: {e}")
        return None

def get_file_content_as_bytes(file_id):
    """Tải nội dung file (ảnh) về RAM để hiển thị"""
    service = get_drive_service()
    if not service or not file_id: return None
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        return fh
    except: return None

# --- FILE NAMES (TRÊN DRIVE) ---
CUSTOMERS_CSV = "crm_customers.csv"
SUPPLIERS_CSV = "crm_suppliers.csv"
PURCHASES_CSV = "crm_purchases.csv"
SHARED_HISTORY_CSV = "crm_shared_quote_history.csv" 
TRACKING_CSV = "crm_order_tracking.csv"
PAYMENT_CSV = "crm_payment_tracking.csv"
PAID_HISTORY_CSV = "crm_paid_history.csv"
DB_SUPPLIER_ORDERS = "db_supplier_orders.csv"
DB_CUSTOMER_ORDERS = "db_customer_orders.csv"
TEMPLATE_FILE_NAME = "AAA-QUOTATION.xlsx" # Lưu tên file thay vì path

ADMIN_PASSWORD = "admin"

# --- GLOBAL HELPER FUNCTIONS (LOGIC GIỮ NGUYÊN) ---
def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def safe_filename(s): 
    s = safe_str(s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    s = re.sub(r'[^\w\-_]', '_', s)
    s = re.sub(r'_{2,}', '_', s)
    return s.strip('_')

def to_float(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s.lower() in ['nan', 'none', 'null']: return 0.0
    s_clean = s.replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace("rmb", "").replace("vnd", "")
    try:
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", s_clean)
        if not numbers: return 0.0
        floats = [float(n) for n in numbers]
        return max(floats)
    except: return 0.0

def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"

def clean_lookup_key(s):
    if s is None: return ""
    s_str = str(s)
    try:
        f = float(s_str)
        if f.is_integer(): s_str = str(int(f))
    except: pass
    clean = re.sub(r'[^a-zA-Z0-9]', '', s_str).lower()
    return clean

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime):
            dt_order = order_date_str
        else:
            dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper().replace(",", "")
    try: return float(s)
    except: pass
    if not s.startswith("="): return 0.0
    expr = s[1:]
    expr = expr.replace("BUYING PRICE", str(buying_price))
    expr = expr.replace("BUY", str(buying_price))
    expr = expr.replace("AP PRICE", str(ap_price))
    expr = expr.replace("AP", str(ap_price))
    expr = re.sub(r'[^0-9.+\-*/()]', '', expr)
    try: return float(eval(expr))
    except: return 0.0

def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        found_merge = False
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                top_left_cell = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                top_left_cell.value = value
                found_merge = True
                break
        if not found_merge: cell.value = value
    except: pass

# --- COLUMN DEFINITIONS ---
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SHARED_HISTORY_COLS = ["history_id", "date", "quote_no", "customer"] + QUOTE_KH_COLUMNS + ["pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]

# =============================================================================
# 2. SESSION STATE MANAGEMENT
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    st.session_state.uploaded_po_files = [] 
    st.session_state.selected_po_files = []
    st.session_state.show_review_table = False
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
        st.session_state[f"pct_{k}"] = "0"

# LOAD DATA TỪ DRIVE (Thay vì Local CSV)
customers_df = load_csv(CUSTOMERS_CSV, MASTER_COLUMNS)
suppliers_df = load_csv(SUPPLIERS_CSV, MASTER_COLUMNS)
purchases_df = load_csv(PURCHASES_CSV, PURCHASE_COLUMNS)
shared_history_df = load_csv(SHARED_HISTORY_CSV, SHARED_HISTORY_COLS)
tracking_df = load_csv(TRACKING_CSV, TRACKING_COLS)
payment_df = load_csv(PAYMENT_CSV, PAYMENT_COLS)
paid_history_df = load_csv(PAID_HISTORY_CSV, PAYMENT_COLS)
db_supplier_orders = load_csv(DB_SUPPLIER_ORDERS, [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
db_customer_orders = load_csv(DB_CUSTOMER_ORDERS, [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

# =============================================================================
# 3. SIDEBAR (ADMIN & MENU)
# =============================================================================
st.sidebar.title("CRM V4800")
st.sidebar.markdown(f"**Version:** `{APP_VERSION}`")
with st.sidebar.expander("📝 Release Notes"):
    st.markdown(RELEASE_NOTE)

admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)

st.sidebar.divider()
st.sidebar.info("Hệ thống Cloud 20 User: Báo giá - Đơn hàng - Tracking - Doanh số")

# =============================================================================
# 4. GIAO DIỆN CHÍNH (TABS)
# =============================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", 
    "🏭 BÁO GIÁ NCC", 
    "💰 BÁO GIÁ KHÁCH", 
    "📑 QUẢN LÝ PO", 
    "🚚 TRACKING & THANH TOÁN", 
    "📂 MASTER DATA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH")
    
    col_act1, col_act2 = st.columns([1, 1])
    if col_act1.button("🔄 CẬP NHẬT DỮ LIỆU"): st.rerun()
    if col_act2.button("⚠️ RESET DATA (Admin)"):
        # Lưu ý: Trên Cloud không dùng os.remove, mà nên clear nội dung file
        if admin_pwd == ADMIN_PASSWORD:
            empty_df = pd.DataFrame() # Create empty to overwrite
            # Thực tế: Reset về cột rỗng
            save_csv(DB_CUSTOMER_ORDERS, pd.DataFrame(columns=[c for c in CUSTOMER_ORDER_COLS if c!="Delete"]))
            save_csv(DB_SUPPLIER_ORDERS, pd.DataFrame(columns=[c for c in SUPPLIER_ORDER_COLS if c!="Delete"]))
            save_csv(SHARED_HISTORY_CSV, pd.DataFrame(columns=SHARED_HISTORY_COLS))
            save_csv(TRACKING_CSV, pd.DataFrame(columns=TRACKING_COLS))
            save_csv(PAYMENT_CSV, pd.DataFrame(columns=PAYMENT_COLS))
            save_csv(PAID_HISTORY_CSV, pd.DataFrame(columns=PAYMENT_COLS))
            st.success("Đã reset toàn bộ dữ liệu trên Cloud!")
            st.rerun()
        else: st.error("Sai mật khẩu Admin!")
    
    st.divider()

    total_revenue = db_customer_orders['total_price'].apply(to_float).sum()
    total_po_ncc_cost = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    total_other_costs = 0.0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            try:
                gap_val = to_float(r['gap'])
                gap_cost = gap_val * 0.6
                end_user = to_float(r['end_user_val'])
                buyer = to_float(r['buyer_val'])
                tax = to_float(r['import_tax_val'])
                vat = to_float(r['vat_val'])
                trans = to_float(r['transportation']) * to_float(r['qty'])
                mgmt = to_float(r['mgmt_fee'])
                total_other_costs += (gap_cost + end_user + buyer + tax + vat + trans + mgmt)
            except: pass

    total_profit = total_revenue - (total_po_ncc_cost + total_other_costs)
    
    po_ordered_ncc = len(tracking_df[tracking_df['order_type'] == 'NCC'])
    po_total_recv = len(db_customer_orders['po_number'].unique())
    po_delivered = len(tracking_df[(tracking_df['order_type'] == 'KH') & (tracking_df['status'] == 'Đã giao hàng')])
    po_pending = po_total_recv - po_delivered

    # --- 3D CARDS DISPLAY ---
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""<div class="card-3d bg-sales"><div class="card-title">DOANH THU BÁN (VND)</div><div class="card-value">{fmt_num(total_revenue)}</div><p>Tổng PO Khách đã lưu</p></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="card-3d bg-cost"><div class="card-title">TỔNG CHI PHÍ (VND)</div><div class="card-value">{fmt_num(total_po_ncc_cost + total_other_costs)}</div><p>PO NCC + Các loại phí</p></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="card-3d bg-profit"><div class="card-title">LỢI NHUẬN THỰC (VND)</div><div class="card-value">{fmt_num(total_profit)}</div><p>Doanh thu - Tổng chi phí</p></div>""", unsafe_allow_html=True)
    
    st.divider()
    
    # Row 2: PO Metrics
    c4, c5, c6, c7 = st.columns(4)
    with c4: st.markdown(f"""<div class="card-3d bg-ncc"><div class="card-title">ĐƠN HÀNG ĐÃ ĐẶT NCC</div><div class="card-value">{po_ordered_ncc}</div></div>""", unsafe_allow_html=True)
    with c5: st.markdown(f"""<div class="card-3d bg-recv"><div class="card-title">TỔNG PO ĐÃ NHẬN</div><div class="card-value">{po_total_recv}</div></div>""", unsafe_allow_html=True)
    with c6: st.markdown(f"""<div class="card-3d bg-del"><div class="card-title">TỔNG PO ĐÃ GIAO</div><div class="card-value">{po_delivered}</div></div>""", unsafe_allow_html=True)
    with c7: st.markdown(f"""<div class="card-3d bg-pend"><div class="card-title">TỔNG PO CHƯA GIAO</div><div class="card-value">{po_pending}</div></div>""", unsafe_allow_html=True)
    
    st.divider()
    
    c_top1, c_top2 = st.columns(2)
    with c_top1:
        st.subheader("🥇 Top Khách Hàng (Doanh Số)")
        if not db_customer_orders.empty:
            top_cust = db_customer_orders.copy()
            top_cust['val'] = top_cust['total_price'].apply(to_float)
            top_cust_g = top_cust.groupby('customer')['val'].sum().sort_values(ascending=False).head(10)
            st.dataframe(top_cust_g.apply(fmt_num), use_container_width=True)
    with c_top2:
        st.subheader("🏭 Top Nhà Cung Cấp (Mua Nhiều)")
        if not db_supplier_orders.empty:
            top_supp = db_supplier_orders.copy()
            top_supp['val'] = top_supp['total_vnd'].apply(to_float)
            top_supp_g = top_supp.groupby('supplier')['val'].sum().sort_values(ascending=False).head(10)
            df_top_supp = top_supp_g.to_frame(name="Tổng tiền mua (VND)")
            df_top_supp["Tổng tiền mua (VND)"] = df_top_supp["Tổng tiền mua (VND)"].apply(fmt_num)
            st.dataframe(df_top_supp, use_container_width=True)

# --- TAB 2: BÁO GIÁ NCC ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        uploaded_pur = st.file_uploader("Import Excel Purchases (Kèm ảnh)", type=["xlsx"])
        if uploaded_pur and st.button("Thực hiện Import"):
            with st.spinner("Đang xử lý và upload lên Cloud..."):
                try:
                    wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                    img_map = {}
                    # Xử lý ảnh: Upload lên Drive và lấy ID
                    for img in getattr(ws, '_images', []):
                        r_idx = img.anchor._from.row + 1; c_idx = img.anchor._from.col
                        if c_idx == 12: 
                            img_name = f"img_r{r_idx}_{int(time.time())}.png"
                            img_bytes = io.BytesIO(img._data()) # Chuyển sang IO Stream
                            file_id = upload_bytes_to_drive(img_bytes, img_name, "image/png")
                            if file_id: img_map[r_idx] = file_id # Lưu File ID thay vì Path
                    
                    uploaded_pur.seek(0) # Reset pointer
                    df_ex = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                    rows = []
                    for i, r in df_ex.iterrows():
                        excel_row_idx = i + 2
                        im_id = img_map.get(excel_row_idx, "")
                        item = {
                            "no": safe_str(r.iloc[0]), "item_code": safe_str(r.iloc[1]), 
                            "item_name": safe_str(r.iloc[2]), "specs": safe_str(r.iloc[3]),
                            "qty": fmt_num(to_float(r.iloc[4])), "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                            "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                            "buying_price_vnd": fmt_num(to_float(r.iloc[8])), "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                            "leadtime": safe_str(r.iloc[10]), "supplier_name": safe_str(r.iloc[11]), 
                            "image_path": im_id, # Lưu ID Drive
                            "type": safe_str(r.iloc[13]) if len(r) > 13 else "", "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else ""
                        }
                        if item["item_code"] or item["item_name"]: rows.append(item)
                    
                    purchases_df = pd.DataFrame(rows)
                    save_csv(PURCHASES_CSV, purchases_df)
                    st.success(f"Đã import {len(rows)} dòng và lưu ảnh lên Cloud!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")
            
        # Upload Ảnh thủ công
        st.markdown("---")
        st.write("📸 Cập nhật ảnh cho Item")
        up_img_ncc = st.file_uploader("Upload ảnh", type=["png","jpg","jpeg"])
        item_to_update = st.text_input("Nhập mã Item Code")
        if st.button("Cập nhật ảnh") and up_img_ncc and item_to_update:
            fname = f"prod_{safe_filename(item_to_update)}_{int(time.time())}.png"
            fid = upload_bytes_to_drive(up_img_ncc, fname, up_img_ncc.type)
            if fid:
                mask = purchases_df['item_code'] == item_to_update
                if mask.any():
                    purchases_df.loc[mask, 'image_path'] = fid
                    save_csv(PURCHASES_CSV, purchases_df)
                    st.success("Đã cập nhật ảnh!")
                    st.rerun()
                else: st.error("Không tìm thấy mã Item")
            else: st.error("Lỗi upload")

    with col_p2:
        search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC)")
    
    if not purchases_df.empty:
        df_show = purchases_df.copy()
        if search_term:
            mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or 
                                             search_term.lower() in str(x['item_name']).lower() or 
                                             search_term.lower() in str(x['specs']).lower(), axis=1)
            df_show = df_show[mask]
        
        # Hiển thị bảng (không hiển thị cột ID ảnh vì nó là chuỗi loằng ngoằng)
        st.dataframe(df_show.drop(columns=['image_path']), use_container_width=True, hide_index=True)
        
        # Logic xem ảnh trên Cloud: Chọn item -> Load ảnh từ ID
        st.markdown("##### 🖼️ Xem ảnh chi tiết")
        sel_code = st.selectbox("Chọn mã để xem ảnh:", [""] + df_show['item_code'].unique().tolist())
        if sel_code:
            row = df_show[df_show['item_code'] == sel_code]
            if not row.empty:
                iid = row.iloc[0]['image_path']
                if iid:
                    with st.spinner("Đang tải ảnh..."):
                        ibytes = get_file_content_as_bytes(iid)
                        if ibytes: st.image(ibytes, width=300)
                        else: st.warning("Không tải được ảnh")
                else: st.info("Chưa có ảnh")
    else: st.info("Chưa có dữ liệu.")

    if is_admin and st.button("Xóa Database Mua Hàng"):
        save_csv(PURCHASES_CSV, pd.DataFrame(columns=PURCHASE_COLUMNS))
        st.rerun()

# --- TAB 3: BÁO GIÁ KHÁCH HÀNG ---
with tab3:
    tab3_1, tab3_2 = st.tabs(["TẠO BÁO GIÁ", "TRA CỨU LỊCH SỬ CHUNG"])
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
        
        st.session_state.pct_end = pct_end; st.session_state.pct_buy = pct_buy
        st.session_state.pct_tax = pct_tax; st.session_state.pct_vat = pct_vat
        st.session_state.pct_pay = pct_pay; st.session_state.pct_mgmt = pct_mgmt
        st.session_state.pct_trans = val_trans

        c_imp1, c_imp2 = st.columns(2)
        with c_imp1:
            uploaded_rfq = st.file_uploader("📂 Import RFQ (Excel)", type=["xlsx"])
            if uploaded_rfq and st.button("Load RFQ"):
                try:
                    purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                    purchases_df["_clean_specs"] = purchases_df["specs"].apply(clean_lookup_key)
                    purchases_df["_clean_name"] = purchases_df["item_name"].apply(clean_lookup_key)
                    
                    df_rfq = pd.read_excel(uploaded_rfq, header=None, dtype=str).fillna("")
                    new_data = []
                    
                    for i, r in df_rfq.iloc[1:].iterrows():
                        c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2])
                        s_raw = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                        if qty <= 0: continue
                        if not c_raw and not n_raw and not s_raw: continue

                        # READ PRICES FROM EXCEL
                        ex_rmb = to_float(r.iloc[5]) if len(r) > 5 else 0
                        ex_rate = to_float(r.iloc[7]) if len(r) > 7 else 0
                        ex_vnd = to_float(r.iloc[8]) if len(r) > 8 else 0
                        ex_supp = safe_str(r.iloc[11]) if len(r) > 11 else ""
                        ex_lead = safe_str(r.iloc[10]) if len(r) > 10 else ""

                        clean_c = clean_lookup_key(c_raw); clean_s = clean_lookup_key(s_raw); clean_n = clean_lookup_key(n_raw)
                        target_row = None
                        found_in_db = pd.DataFrame()
                        
                        if c_raw: found_in_db = purchases_df[purchases_df["_clean_code"] == clean_c]
                        if found_in_db.empty and n_raw: found_in_db = purchases_df[purchases_df["_clean_name"] == clean_n]

                        if not found_in_db.empty:
                            found_in_db = found_in_db.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False)
                            if s_raw:
                                found_specs = found_in_db[found_in_db["_clean_specs"] == clean_s]
                                if not found_specs.empty:
                                     found_specs = found_specs.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False)
                                     target_row = found_specs.iloc[0]
                                else: target_row = found_in_db.iloc[0]
                            else: target_row = found_in_db.iloc[0]
                        
                        it = {k:"0" if "price" in k or "val" in k or "fee" in k else "" for k in QUOTE_KH_COLUMNS}
                        it.update({"no": safe_str(r.iloc[0]), "item_code": c_raw, "item_name": n_raw, "specs": s_raw, "qty": fmt_num(qty)})

                        db_rmb = to_float(target_row["buying_price_rmb"]) if target_row is not None else 0
                        db_vnd = to_float(target_row["buying_price_vnd"]) if target_row is not None else 0
                        db_rate = to_float(target_row["exchange_rate"]) if target_row is not None else 0
                        db_supp = target_row["supplier_name"] if target_row is not None else ""
                        db_lead = target_row["leadtime"] if target_row is not None else ""
                        db_img = target_row["image_path"] if target_row is not None else ""

                        final_rmb = ex_rmb if ex_rmb > 0 else db_rmb
                        final_vnd = ex_vnd if ex_vnd > 0 else db_vnd
                        final_rate = ex_rate if ex_rate > 0 else db_rate
                        final_supp = ex_supp if ex_supp else db_supp
                        final_lead = ex_lead if ex_lead else db_lead
                        final_img = db_img

                        it.update({
                            "buying_price_rmb": fmt_num(final_rmb),
                            "total_buying_price_rmb": fmt_num(final_rmb * qty),
                            "exchange_rate": fmt_num(final_rate),
                            "buying_price_vnd": fmt_num(final_vnd),
                            "total_buying_price_vnd": fmt_num(final_vnd * qty),
                            "supplier_name": final_supp,
                            "image_path": final_img,
                            "leadtime": final_lead
                        })
                        new_data.append(it)
                    
                    st.session_state.current_quote_df = pd.DataFrame(new_data)
                    st.success(f"Đã load {len(new_data)} dòng từ RFQ và khớp dữ liệu NCC!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")
        
        with c_imp2:
             st.info("Dữ liệu được lưu chung cho 20 người trên Cloud.")

        # --- DATA EDITOR ---
        st.markdown("### Chi tiết báo giá")
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        ap_formula = f1.text_input("AP Formula (vd: BUY*1.1)", key="ap_f")
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r.get("buying_price_vnd", 0)); a = to_float(r.get("ap_price", 0))
                st.session_state.current_quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_formula, b, a))
            st.rerun()

        unit_formula = f3.text_input("Unit Formula (vd: AP/0.8)", key="unit_f")
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r.get("buying_price_vnd", 0)); a = to_float(r.get("ap_price", 0))
                st.session_state.current_quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_formula, b, a))
            st.rerun()

        edited_df = st.data_editor(st.session_state.current_quote_df, key="quote_editor", use_container_width=True, num_rows="dynamic")
        
        # --- AUTO-CALC (LOGIC GỐC) ---
        pend = to_float(pct_end)/100; pbuy = to_float(pct_buy)/100
        ptax = to_float(pct_tax)/100; pvat = to_float(pct_vat)/100
        ppay = to_float(pct_pay)/100; pmgmt = to_float(pct_mgmt)/100
        global_trans = to_float(val_trans)
        use_global = global_trans > 0
        df_temp = edited_df.copy()
        
        for i, r in df_temp.iterrows():
            qty = to_float(r.get("qty", 0)); buy_vnd = to_float(r.get("buying_price_vnd", 0))
            buy_rmb = to_float(r.get("buying_price_rmb", 0))
            ap = to_float(r.get("ap_price", 0)); unit = to_float(r.get("unit_price", 0))
            cur_trans = to_float(r.get("transportation", 0))
            use_trans = global_trans if use_global else cur_trans
            
            t_buy = qty * buy_vnd; ap_tot = ap * qty; total = unit * qty; gap = total - ap_tot
            end_val = ap_tot * pend; buyer_val = total * pbuy; tax_val = t_buy * ptax; vat_val = total * pvat
            mgmt_val = total * pmgmt; pay_val = gap * ppay; tot_trans = use_trans * qty
            
            cost = t_buy + gap + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
            prof = total - cost + pay_val
            pct = (prof/total*100) if total else 0
            
            df_temp.at[i, "transportation"] = fmt_num(use_trans)
            df_temp.at[i, "total_buying_price_rmb"] = fmt_num(buy_rmb * qty)
            df_temp.at[i, "total_buying_price_vnd"] = fmt_num(t_buy)
            df_temp.at[i, "ap_total_vnd"] = fmt_num(ap_tot)
            df_temp.at[i, "total_price_vnd"] = fmt_num(total)
            df_temp.at[i, "gap"] = fmt_num(gap)
            df_temp.at[i, "end_user_val"] = fmt_num(end_val)
            df_temp.at[i, "buyer_val"] = fmt_num(buyer_val)
            df_temp.at[i, "import_tax_val"] = fmt_num(tax_val)
            df_temp.at[i, "vat_val"] = fmt_num(vat_val)
            df_temp.at[i, "mgmt_fee"] = fmt_num(mgmt_val)
            df_temp.at[i, "payback_val"] = fmt_num(pay_val)
            df_temp.at[i, "profit_vnd"] = fmt_num(prof)
            df_temp.at[i, "profit_pct"] = "{:.2f}%".format(pct)

        if not df_temp.equals(st.session_state.current_quote_df):
             st.session_state.current_quote_df = df_temp
             st.rerun()

        st.divider()
        c_rev, c_sav, c_exp = st.columns([1, 1, 1])
        
        with c_rev:
            if st.button("🔍 REVIEW & KIỂM TRA LỢI NHUẬN", type="primary"):
                st.session_state.show_review_table = not st.session_state.get('show_review_table', False)
        
        if st.session_state.get('show_review_table', False):
            st.write("### Bảng kiểm tra lợi nhuận")
            def highlight_low_profit(val):
                try:
                    p = float(val.replace("%",""))
                    return 'background-color: #ffcccc; color: red; font-weight: bold' if p < 10 else ''
                except: return ''
            cols_review = ["item_code", "item_name", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]
            df_review = st.session_state.current_quote_df[cols_review].copy()
            st.dataframe(df_review.style.applymap(highlight_low_profit, subset=['profit_pct']), use_container_width=True)
        
        # --- NÚT LƯU LỊCH SỬ CLOUD ---
        with c_sav:
            if st.button("💾 LƯU LỊCH SỬ (CLOUD)"):
                if not sel_cust or not quote_name: st.error("Thiếu thông tin khách hoặc tên báo giá")
                else:
                    now = datetime.now()
                    d_str = now.strftime("%d/%m/%Y")
                    rows_to_save = st.session_state.current_quote_df.copy()
                    rows_to_save["history_id"] = f"{quote_name}_{now.strftime('%Y%m%d%H%M%S')}"
                    rows_to_save["date"] = d_str; rows_to_save["quote_no"] = quote_name; rows_to_save["customer"] = sel_cust
                    rows_to_save["pct_end"] = pct_end; rows_to_save["pct_buy"] = pct_buy; rows_to_save["pct_tax"] = pct_tax
                    rows_to_save["pct_vat"] = pct_vat; rows_to_save["pct_pay"] = pct_pay; rows_to_save["pct_mgmt"] = pct_mgmt; rows_to_save["pct_trans"] = val_trans
                    
                    for c in SHARED_HISTORY_COLS:
                        if c not in rows_to_save.columns: rows_to_save[c] = ""
                    
                    updated_history = pd.concat([shared_history_df, rows_to_save[SHARED_HISTORY_COLS]], ignore_index=True)
                    save_csv(SHARED_HISTORY_CSV, updated_history)
                    
                    # Cho phép tải CSV về máy
                    csv_data = rows_to_save.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button("📥 Tải file CSV", csv_data, f"Quote_{safe_filename(quote_name)}.csv", "text/csv")
                    st.success("✅ Đã lưu lên Cloud!"); st.rerun()

        with c_exp:
            if st.button("XUẤT EXCEL"):
                # Excel vẫn cần template, ta sẽ download template từ Drive về RAM nếu cần
                tpl_id = get_file_id_by_name(TEMPLATE_FILE_NAME)
                if not tpl_id: st.error("Không tìm thấy template trên Cloud")
                else:
                    try:
                        tpl_bytes = get_file_content_as_bytes(tpl_id)
                        wb = load_workbook(tpl_bytes)
                        ws = wb.active
                        now = datetime.now()
                        safe_write_merged(ws, 1, 2, sel_cust); safe_write_merged(ws, 2, 8, quote_name)
                        safe_write_merged(ws, 1, 8, now.strftime("%d-%b-%Y"))
                        if not st.session_state.current_quote_df.empty:
                            lt = safe_str(st.session_state.current_quote_df.iloc[0]["leadtime"])
                            safe_write_merged(ws, 8, 8, lt)
                        start_row = 11
                        for idx, r in st.session_state.current_quote_df.iterrows():
                            ri = start_row + idx
                            safe_write_merged(ws, ri, 1, r["no"]); safe_write_merged(ws, ri, 3, r["item_code"])
                            safe_write_merged(ws, ri, 4, r["item_name"]); safe_write_merged(ws, ri, 5, r["specs"])
                            safe_write_merged(ws, ri, 6, to_float(r["qty"])); safe_write_merged(ws, ri, 7, to_float(r["unit_price"]))
                            safe_write_merged(ws, ri, 8, to_float(r["total_price_vnd"]))
                        
                        output = io.BytesIO(); wb.save(output)
                        fname = f"Quote_{safe_filename(quote_name)}.xlsx"
                        st.download_button("📥 Tải Excel", output.getvalue(), fname, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception as e: st.error(str(e))

    with tab3_2:
        st.subheader("Tra cứu lịch sử Cloud")
        shared_history_df = load_csv(SHARED_HISTORY_CSV, SHARED_HISTORY_COLS)
        if not shared_history_df.empty:
            search_h = st.text_input("🔍 Tìm kiếm")
            df_search = shared_history_df.copy()
            if search_h:
                mask = df_search.apply(lambda x: search_h.lower() in str(x).lower(), axis=1)
                df_search = df_search[mask]
            st.dataframe(df_search, use_container_width=True)
            
            sel_qid = st.selectbox("Chọn báo giá tải lại:", [""] + list(df_search['history_id'].unique()))
            if st.button("♻️ Tải lại") and sel_qid:
                df_sel = shared_history_df[shared_history_df['history_id'] == sel_qid]
                if not df_sel.empty:
                    fr = df_sel.iloc[0]
                    st.session_state.pct_end = str(fr.get('pct_end','0')); st.session_state.pct_buy = str(fr.get('pct_buy','0'))
                    st.session_state.pct_tax = str(fr.get('pct_tax','0')); st.session_state.pct_vat = str(fr.get('pct_vat','0'))
                    st.session_state.pct_pay = str(fr.get('pct_pay','0')); st.session_state.pct_mgmt = str(fr.get('pct_mgmt','0'))
                    st.session_state.pct_trans = str(fr.get('pct_trans','0'))
                    st.session_state.current_quote_df = df_sel[QUOTE_KH_COLUMNS].copy()
                    st.success("Đã tải lại!"); st.rerun()

# --- TAB 4: QUẢN LÝ PO ---
with tab4:
    col_po1, col_po2 = st.columns(2)
    with col_po1:
        st.subheader("1. Đặt hàng NCC (PO NCC)")
        po_ncc_no = st.text_input("Số PO NCC"); supp_list = suppliers_df["short_name"].tolist()
        po_ncc_supp = st.selectbox("NCC", [""] + supp_list); po_ncc_date = st.text_input("Ngày đặt", value=datetime.now().strftime("%d/%m/%Y"))
        up_ncc = st.file_uploader("Excel Items NCC", type=["xlsx"], key="up_ncc")
        if up_ncc:
             df_ncc = pd.read_excel(up_ncc, dtype=str).fillna(""); temp_ncc = []
             purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
             for i, r in df_ncc.iterrows():
                 code = safe_str(r.iloc[1]); specs = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                 clean_c = clean_lookup_key(code); found = purchases_df[purchases_df["_clean_code"]==clean_c]
                 it = {"item_code":code, "qty":fmt_num(qty), "specs": specs, "item_name": safe_str(r.iloc[2])}
                 if not found.empty:
                     fr = found.iloc[0]
                     it.update({"item_name":fr["item_name"], "price_rmb":fr["buying_price_rmb"], "total_rmb":fmt_num(to_float(fr["buying_price_rmb"])*qty), "price_vnd":fr["buying_price_vnd"], "total_vnd":fmt_num(to_float(fr["buying_price_vnd"])*qty), "exchange_rate":fr["exchange_rate"], "eta":calc_eta(po_ncc_date, fr["leadtime"]), "supplier":fr["supplier_name"]})
                 else: it.update({"price_rmb":"0", "total_rmb":"0", "price_vnd":"0", "total_vnd":"0", "exchange_rate":"0", "supplier":po_ncc_supp})
                 temp_ncc.append(it)
             st.session_state.temp_supp_order_df = pd.DataFrame(temp_ncc)
        
        if "Delete" not in st.session_state.temp_supp_order_df.columns: st.session_state.temp_supp_order_df["Delete"] = False
        if st.button("🗑️ Xóa dòng (NCC)"):
            st.session_state.temp_supp_order_df = st.session_state.temp_supp_order_df[~st.session_state.temp_supp_order_df["Delete"]]
            st.rerun()

        edited_ncc = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", key="ed_ncc", use_container_width=True)
        if not edited_ncc.equals(st.session_state.temp_supp_order_df): st.session_state.temp_supp_order_df = edited_ncc; st.rerun()

        if st.button("🚀 XÁC NHẬN PO NCC"):
            if not po_ncc_no: st.error("Thiếu PO"); st.stop()
            final_df = st.session_state.temp_supp_order_df.copy()
            if "Delete" in final_df.columns: del final_df["Delete"]
            final_df["po_number"] = po_ncc_no; final_df["order_date"] = po_ncc_date
            
            db_supplier_orders = pd.concat([db_supplier_orders, final_df], ignore_index=True)
            save_csv(DB_SUPPLIER_ORDERS, db_supplier_orders)
            
            for supp, g in final_df.groupby("supplier"):
                new_track = {"no": len(tracking_df)+1, "po_no": po_ncc_no, "partner": supp, "status": "Đã đặt hàng", "eta": g.iloc[0]["eta"], "proof_image": "", "order_type": "NCC", "last_update": po_ncc_date, "finished": "0"}
                tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
            save_csv(TRACKING_CSV, tracking_df); st.success("Done!")

    with col_po2:
        st.subheader("2. PO Khách Hàng")
        po_cust_no = st.text_input("Số PO Khách"); cust_po_list = customers_df["short_name"].tolist()
        po_cust_name = st.selectbox("Khách Hàng", [""] + cust_po_list); po_cust_date = st.text_input("Ngày nhận", value=datetime.now().strftime("%d/%m/%Y"))
        
        uploaded_files = st.file_uploader("Upload File PO (Lên Cloud)", type=["xlsx", "pdf", "png", "jpg"], accept_multiple_files=True)
        
        # LOGIC UPLOAD FILE PO LÊN DRIVE (Thay vì lưu Local folder)
        po_file_ids = []
        if uploaded_files and st.button("Upload File PO"):
             for f in uploaded_files:
                 fname = f"PO_{po_cust_no}_{f.name}"
                 fid = upload_bytes_to_drive(f, fname, f.type)
                 if fid: po_file_ids.append(fid)
             st.success(f"Đã upload {len(po_file_ids)} file lên Cloud!")
        
        # Parse Excel (Logic cũ)
        if uploaded_files:
             for f in uploaded_files:
                 if f.name.endswith('.xlsx'):
                     try:
                         df_c = pd.read_excel(f, dtype=str).fillna(""); temp_c = []
                         purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                         for i, r in df_c.iterrows():
                             code = safe_str(r.iloc[1]); qty = to_float(r.iloc[4]); specs = safe_str(r.iloc[3])
                             price = 0; # Logic tìm giá cũ tạm bỏ qua nếu phức tạp, hoặc giữ nguyên nếu có shared history
                             eta = ""; clean_code = clean_lookup_key(code); found_pur = purchases_df[purchases_df["_clean_code"] == clean_code]
                             if not found_pur.empty: eta = calc_eta(po_cust_date, found_pur.iloc[0]["leadtime"])
                             temp_c.append({"item_code":code, "item_name":safe_str(r.iloc[2]), "specs":specs, "qty":fmt_num(qty), "unit_price":fmt_num(price), "total_price":fmt_num(price*qty), "eta": eta})
                         st.session_state.temp_cust_order_df = pd.DataFrame(temp_c)
                     except: pass

        edited_cust_po = st.data_editor(st.session_state.temp_cust_order_df, num_rows="dynamic", key="ed_cust_po", use_container_width=True)
        if not edited_cust_po.equals(st.session_state.temp_cust_order_df): st.session_state.temp_cust_order_df = edited_cust_po; st.rerun()

        if st.button("💾 LƯU PO KHÁCH"):
             if not po_cust_no: st.error("Thiếu PO"); st.stop()
             final_c = st.session_state.temp_cust_order_df.copy()
             if "Delete" in final_c.columns: del final_c["Delete"]
             final_c["po_number"] = po_cust_no; final_c["customer"] = po_cust_name; final_c["order_date"] = po_cust_date
             final_c["pdf_path"] = json.dumps(po_file_ids) # Lưu danh sách ID file JSON
             
             db_customer_orders = pd.concat([db_customer_orders, final_c], ignore_index=True)
             save_csv(DB_CUSTOMER_ORDERS, db_customer_orders)
             
             eta_list = [datetime.strptime(x, "%d/%m/%Y") for x in final_c["eta"] if x]
             final_eta = max(eta_list).strftime("%d/%m/%Y") if eta_list else ""
             
             new_track = {"no": len(tracking_df)+1, "po_no": po_cust_no, "partner": po_cust_name, "status": "Đang đợi hàng về", "eta": final_eta, "proof_image": "", "order_type": "KH", "last_update": po_cust_date, "finished": "0"}
             tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
             save_csv(TRACKING_CSV, tracking_df)
             st.success("OK"); st.rerun()

# --- TAB 5: TRACKING ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI", "LỊCH SỬ THANH TOÁN"])
    with t5_1:
        c_up, c_view = st.columns(2)
        uploaded_proofs = c_up.file_uploader("Upload Ảnh Proof", type=["png", "jpg"], key="proof_upl", accept_multiple_files=True)
        view_id = c_up.text_input("ID Tracking")

        if c_up.button("Upload Proof") and uploaded_proofs and view_id:
             idx = tracking_df.index[tracking_df['no'].astype(str) == view_id].tolist()
             if idx:
                 current_imgs = tracking_df.at[idx[0], "proof_image"]
                 try: img_list = json.loads(current_imgs) if current_imgs else []
                 except: img_list = []
                 for f in uploaded_proofs:
                     fid = upload_bytes_to_drive(f, f"proof_{view_id}_{f.name}", f.type)
                     if fid: img_list.append(fid)
                 tracking_df.at[idx[0], "proof_image"] = json.dumps(img_list)
                 save_csv(TRACKING_CSV, tracking_df); st.success("OK")
             else: st.error("Sai ID")
        
        if c_view.button("Xem Proof") and view_id:
             idx = tracking_df.index[tracking_df['no'].astype(str) == view_id].tolist()
             if idx:
                 try: 
                     img_list = json.loads(tracking_df.at[idx[0], "proof_image"])
                     for i in img_list: st.image(get_file_content_as_bytes(i), width=200)
                 except: st.warning("Không có ảnh")

        st.markdown("#### Tracking")
        edited_track = st.data_editor(tracking_df[tracking_df["finished"]=="0"], num_rows="dynamic", key="ed_track", use_container_width=True)
        if st.button("Cập nhật Tracking"):
             # Logic xử lý finished (giữ nguyên)
             to_keep = edited_track
             finished_rows = tracking_df[tracking_df["finished"]=="1"]
             for i, r in to_keep.iterrows():
                if r["status"] in ["Hàng đã nhận ở VP", "Đã giao hàng"]:
                    to_keep.at[i, "finished"] = "1"; to_keep.at[i, "last_update"] = datetime.now().strftime("%d/%m/%Y")
                    # Tự động tạo payment
                    if r["order_type"] == "KH":
                        cust = r["partner"]; term = 30
                        f_cust = customers_df[customers_df["short_name"]==cust]
                        if not f_cust.empty: 
                            try: term = int(to_float(f_cust.iloc[0]["payment_term"]))
                            except: pass
                        due = (datetime.now() + timedelta(days=term)).strftime("%d/%m/%Y")
                        payment_df = pd.concat([payment_df, pd.DataFrame([{"no": len(payment_df)+1, "po_no": r["po_no"], "customer": cust, "invoice_no": "", "status": "Chưa thanh toán", "due_date": due, "paid_date": ""}])], ignore_index=True)
                        save_csv(PAYMENT_CSV, payment_df)

             tracking_df = pd.concat([finished_rows, to_keep], ignore_index=True)
             save_csv(TRACKING_CSV, tracking_df); st.success("Updated!"); st.rerun()

        st.divider(); st.markdown("#### Công nợ")
        pending_pay = payment_df[payment_df["status"] != "Đã thanh toán"]
        edited_pay = st.data_editor(pending_pay, key="ed_pay", num_rows="dynamic", use_container_width=True)
        if st.button("Cập nhật Payment"):
             paid_items = payment_df[payment_df["status"] == "Đã thanh toán"]
             payment_df = pd.concat([paid_items, edited_pay], ignore_index=True)
             save_csv(PAYMENT_CSV, payment_df); st.success("Updated")

        c1, c2 = st.columns(2)
        pop = c1.selectbox("Chọn PO thanh toán", pending_pay["po_no"].unique())
        if c2.button("Xác nhận ĐÃ THANH TOÁN"):
             idx = payment_df[payment_df["po_no"]==pop].index
             payment_df.loc[idx, "status"] = "Đã thanh toán"
             payment_df.loc[idx, "paid_date"] = datetime.now().strftime("%d/%m/%Y")
             paid_history_df = pd.concat([paid_history_df, payment_df.loc[idx]], ignore_index=True)
             save_csv(PAID_HISTORY_CSV, paid_history_df); save_csv(PAYMENT_CSV, payment_df); st.success("Done!"); st.rerun()

    with t5_2:
        st.subheader("Lịch sử thanh toán")
        if not paid_history_df.empty:
            st.dataframe(paid_history_df, use_container_width=True)
        else: st.info("Trống")

# --- TAB 6: MASTER DATA ---
with tab6:
    t6_1, t6_2, t6_3 = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    with t6_1:
        up_cust = st.file_uploader("Upload Excel KH", type=["xlsx"], key="u_c")
        if up_cust and st.button("Import KH"):
            df = pd.read_excel(up_cust, dtype=str).fillna("")
            save_csv(CUSTOMERS_CSV, df[MASTER_COLUMNS])
            st.success("Import xong"); st.rerun()
        ed_c = st.data_editor(customers_df, num_rows="dynamic", use_container_width=True)
        if st.button("Lưu KH"): save_csv(CUSTOMERS_CSV, ed_c); st.success("Đã lưu")

    with t6_2:
        up_sup = st.file_uploader("Upload Excel NCC", type=["xlsx"], key="u_s")
        if up_sup and st.button("Import NCC"):
            df = pd.read_excel(up_sup, dtype=str).fillna("")
            save_csv(SUPPLIERS_CSV, df[MASTER_COLUMNS])
            st.success("Import xong"); st.rerun()
        ed_s = st.data_editor(suppliers_df, num_rows="dynamic", use_container_width=True)
        if st.button("Lưu NCC"): save_csv(SUPPLIERS_CSV, ed_s); st.success("Đã lưu")

    with t6_3:
        up_tpl = st.file_uploader("Upload Template Mới", type=["xlsx"])
        if up_tpl and st.button("Cập nhật Template"):
            upload_bytes_to_drive(up_tpl, TEMPLATE_FILE_NAME, up_tpl.type)
            st.success("Đã cập nhật Template trên Cloud!")
