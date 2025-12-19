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
import os

# --- THƯ VIỆN KẾT NỐI CLOUD ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from supabase import create_client

# --- THƯ VIỆN XỬ LÝ EXCEL & ĐỒ HỌA ---
try:
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
except ImportError:
    st.error("Thiếu thư viện openpyxl. Vui lòng cài đặt.")
    st.stop()

# Tắt cảnh báo
warnings.filterwarnings("ignore")

# =============================================================================
# 1. CẤU HÌNH HỆ THỐNG
# =============================================================================

# --- !!! ĐIỀN ID FOLDER GOOGLE DRIVE CỦA BẠN VÀO ĐÂY !!! ---
DRIVE_FOLDER_ID = "15-j8O4g_..." # <--- THAY ID CỦA BẠN VÀO ĐÂY
SCOPES = ['https://www.googleapis.com/auth/drive']

APP_VERSION = "V6.3 - FULL LOGIC MIRROR (V4.7 ON CLOUD)"
RELEASE_NOTE = """
- **Logic Mirror:** Sao chép chính xác 100% logic tính toán từ bản V4.7.
- **Profit Fix:** Lợi Nhuận = Tổng PO Khách - (Tổng PO NCC + Tổng Chi Phí).
- **Storage:** Chuyển từ CSV local sang Supabase (SQL) để phục vụ 100 người dùng.
"""

st.set_page_config(page_title=f"CRM V4800 - {APP_VERSION}", layout="wide", page_icon="☁️")

# --- CSS TÙY CHỈNH (GIỮ NGUYÊN BẢN GỐC) ---
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

# =============================================================================
# 2. HÀM KẾT NỐI (CORE)
# =============================================================================

# --- KẾT NỐI GOOGLE DRIVE ---
@st.cache_resource
def get_drive_service():
    try:
        creds = None
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=SCOPES)
        elif os.path.exists('service_account.json'):
            creds = service_account.Credentials.from_service_account_file(
                'service_account.json', scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except: return None

# --- KẾT NỐI SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        st.error("❌ Lỗi: Chưa cấu hình Secrets cho Supabase!")
        return None

supabase_client = init_supabase()

# --- HÀM XỬ LÝ FILE TRÊN DRIVE ---
def get_file_id_by_name(filename):
    service = get_drive_service()
    if not service: return None
    try:
        q = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
        res = service.files().list(q=q, fields="files(id)").execute()
        items = res.get('files', [])
        return items[0]['id'] if items else None
    except: return None

def upload_bytes_to_drive(file_obj, filename, mime_type='application/octet-stream'):
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
    service = get_drive_service()
    if not service or not file_id: return None
    try:
        req = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while done is False: status, done = downloader.next_chunk()
        return fh
    except: return None

# --- HÀM TƯƠNG TÁC DB (THAY THẾ LOAD_CSV/SAVE_CSV) ---
def load_data(table_name, cols):
    """
    Hàm này thay thế load_csv cũ. 
    Nó lấy dữ liệu từ Supabase thay vì file local.
    """
    if not supabase_client: return pd.DataFrame(columns=cols)
    try:
        # Lấy tối đa 10.000 dòng để đảm bảo đủ dữ liệu lịch sử
        response = supabase_client.table(table_name).select("*").limit(10000).execute()
        df = pd.DataFrame(response.data)
        
        # Đảm bảo đủ các cột như định nghĩa (giống logic cũ)
        for c in cols:
            if c not in df.columns: df[c] = ""
            
        # Chuyển ID về string để xử lý nội bộ
        if 'id' in df.columns: df['id'] = df['id'].astype(str)
        
        return df[cols]
    except Exception: 
        # Nếu lỗi (ví dụ bảng chưa tạo), trả về bảng rỗng đúng cấu trúc
        return pd.DataFrame(columns=cols)

def save_data(table_name, df, key_col=None):
    """
    Hàm này thay thế save_csv cũ.
    """
    if not supabase_client or df.empty: return
    try:
        data = df.to_dict(orient='records')
        # Làm sạch dữ liệu (Supabase không nhận NaN, phải là None hoặc "")
        cleaned = [{k: (None if v == "" else v) for k, v in r.items()} for r in data]
        
        # Loại bỏ cột ID giả nếu có để Database tự sinh ID mới
        for r in cleaned:
            if 'id' in r and not r['id']: del r['id']
        
        if key_col:
            # Nếu có khóa chính, dùng Upsert (Cập nhật dòng cũ)
            supabase_client.table(table_name).upsert(cleaned, on_conflict=key_col).execute()
        else:
            # Nếu không, chèn mới (Insert)
            supabase_client.table(table_name).insert(cleaned).execute()
    except Exception as e: 
        st.error(f"Lỗi lưu Database {table_name}: {e}")

# --- MAP TÊN BẢNG DB VÀ CÁC BIẾN CONSTANT ---
TBL_CUST = "crm_customers"
TBL_SUPP = "crm_suppliers"
TBL_PUR = "crm_purchases"
TBL_HIST = "crm_shared_history"
TBL_TRACK = "crm_tracking"
TBL_PAY = "crm_payment"
TBL_PAID = "crm_paid_history"
TBL_PO_S = "db_supplier_orders"
TBL_PO_C = "db_customer_orders"
TEMPLATE_FILE_NAME = "AAA-QUOTATION.xlsx"

ADMIN_PASSWORD = "admin"

# --- HELPER FUNCTIONS (GIỮ NGUYÊN 100% TỪ BẢN GỐC) ---
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

# --- COLUMN DEFINITIONS (GIỮ NGUYÊN) ---
MASTER_COLS = ["short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLS = ["item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc", "_clean_code", "_clean_specs", "_clean_name"]
QUOTE_COLS = ["item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SHARED_HIST_COLS = ["history_id", "date", "quote_no", "customer"] + QUOTE_COLS + ["pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
SUPP_ORDER_COLS = ["po_number", "order_date", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path"]
CUST_ORDER_COLS = ["po_number", "order_date", "customer", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "base_buying_vnd", "full_cost_total", "pdf_path"]
TRACKING_COLS = ["po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
PAID_HIST_COLS = ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]

# =============================================================================
# 3. STATE & LOAD DATA
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_COLS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPP_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUST_ORDER_COLS)
    st.session_state.show_review_table = False
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"

# LOAD DATA TỪ SUPABASE
customers_df = load_data(TBL_CUST, MASTER_COLS)
suppliers_df = load_data(TBL_SUPP, MASTER_COLS)
purchases_df = load_data(TBL_PUR, PURCHASE_COLS)
shared_history_df = load_data(TBL_HIST, SHARED_HIST_COLS)
tracking_df = load_data(TBL_TRACK, TRACKING_COLS)
payment_df = load_data(TBL_PAY, PAYMENT_COLS)
paid_history_df = load_data(TBL_PAID, PAID_HIST_COLS)
db_supplier_orders = load_data(TBL_PO_S, SUPP_ORDER_COLS)
db_customer_orders = load_data(TBL_PO_C, CUST_ORDER_COLS)

# =============================================================================
# 4. GIAO DIỆN CHÍNH
# =============================================================================
st.sidebar.title("CRM V6.3")
st.sidebar.markdown(f"**Version:** `{APP_VERSION}`")
with st.sidebar.expander("📝 Release Notes"):
    st.markdown(RELEASE_NOTE)

admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == "admin")

if st.sidebar.button("🔄 LÀM MỚI DỮ LIỆU"): st.rerun()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", 
    "🏭 KHO DATA & GIÁ", 
    "💰 BÁO GIÁ KHÁCH", 
    "📑 QUẢN LÝ PO", 
    "🚚 TRACKING & CÔNG NỢ", 
    "📂 MASTER DATA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH (REAL-TIME)")
    
    # Logic tính toán từ DB Cloud
    total_rev = db_customer_orders['total_price'].apply(to_float).sum()
    total_cost_base = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    total_extra = 0.0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            try:
                # Công thức chi tiết từ V4.7
                gap_val = to_float(r['gap'])
                gap_cost = gap_val * 0.6
                
                end_user = to_float(r['end_user_val'])
                buyer = to_float(r['buyer_val'])
                tax = to_float(r['import_tax_val'])
                vat = to_float(r['vat_val'])
                trans = to_float(r['transportation']) * to_float(r['qty'])
                mgmt = to_float(r['mgmt_fee'])
                
                total_extra += (gap_cost + end_user + buyer + tax + vat + trans + mgmt)
            except: pass
            
    total_profit = total_rev - (total_cost_base + total_extra)
    
    po_ord = len(tracking_df[tracking_df['order_type']=='NCC'])
    po_rcv = len(db_customer_orders['po_number'].unique())
    po_del = len(tracking_df[(tracking_df['order_type']=='KH') & (tracking_df['status']=='Đã giao hàng')])
    po_pen = po_rcv - po_del

    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="card-3d bg-sales"><h3>DOANH THU</h3><h1>{fmt_num(total_rev)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="card-3d bg-cost"><h3>CHI PHÍ</h3><h1>{fmt_num(total_cost_base + total_extra)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="card-3d bg-profit"><h3>LỢI NHUẬN</h3><h1>{fmt_num(total_profit)}</h1></div>', unsafe_allow_html=True)
    
    st.divider()
    c4, c5, c6, c7 = st.columns(4)
    with c4: st.markdown(f'<div class="card-3d bg-ncc"><h5>ĐÃ ĐẶT NCC</h5><h2>{po_ord}</h2></div>', unsafe_allow_html=True)
    with c5: st.markdown(f'<div class="card-3d bg-recv"><h5>TỔNG PO NHẬN</h5><h2>{po_rcv}</h2></div>', unsafe_allow_html=True)
    with c6: st.markdown(f'<div class="card-3d bg-del"><h5>ĐÃ GIAO</h5><h2>{po_del}</h2></div>', unsafe_allow_html=True)
    with c7: st.markdown(f'<div class="card-3d bg-pend"><h5>CHƯA GIAO</h5><h2>{po_pen}</h2></div>', unsafe_allow_html=True)

    st.divider()
    c_top1, c_top2 = st.columns(2)
    with c_top1:
        st.subheader("🥇 Top Khách Hàng")
        if not db_customer_orders.empty:
            top_cust = db_customer_orders.copy(); top_cust['v'] = top_cust['total_price'].apply(to_float)
            st.dataframe(top_cust.groupby('customer')['v'].sum().sort_values(ascending=False).head(10).apply(fmt_num), use_container_width=True)
    with c_top2:
        st.subheader("🏭 Top NCC")
        if not db_supplier_orders.empty:
            top_supp = db_supplier_orders.copy(); top_supp['v'] = top_supp['total_vnd'].apply(to_float)
            st.dataframe(top_supp.groupby('supplier')['v'].sum().sort_values(ascending=False).head(10).apply(fmt_num), use_container_width=True)

# --- TAB 2: PURCHASES ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 2])
    
    with col_p1:
        up_pur = st.file_uploader("Import Excel Purchases (Kèm ảnh)", type=["xlsx"])
        if up_pur and st.button("Thực hiện Import"):
            with st.spinner("Đang tách ảnh và upload lên Cloud..."):
                try:
                    wb = load_workbook(up_pur, data_only=False); ws = wb.active
                    img_map = {}
                    # 1. Tách ảnh upload lên Drive
                    for img in getattr(ws, '_images', []):
                        if img.anchor._from.col == 12: # Cột M (Index 12)
                            buf = io.BytesIO(img._data())
                            fid = upload_bytes_to_drive(buf, f"pur_{int(time.time())}.png", "image/png")
                            if fid: img_map[img.anchor._from.row + 1] = fid
                    
                    # 2. Đọc dữ liệu
                    up_pur.seek(0)
                    df_ex = pd.read_excel(up_pur, header=0, dtype=str).fillna("")
                    rows = []
                    for i, r in df_ex.iterrows():
                        code = safe_str(r.iloc[1])
                        if code:
                            row = {
                                "no": safe_str(r.iloc[0]), "item_code": code, "item_name": safe_str(r.iloc[2]),
                                "specs": safe_str(r.iloc[3]), "qty": fmt_num(to_float(r.iloc[4])),
                                "buying_price_rmb": fmt_num(to_float(r.iloc[5])),
                                "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])),
                                "exchange_rate": fmt_num(to_float(r.iloc[7])),
                                "buying_price_vnd": fmt_num(to_float(r.iloc[8])),
                                "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])),
                                "leadtime": safe_str(r.iloc[10]), "supplier_name": safe_str(r.iloc[11]),
                                "image_path": img_map.get(i+2, ""), 
                                "type": safe_str(r.iloc[13]), "nuoc": safe_str(r.iloc[14]),
                                "_clean_code": clean_lookup_key(code),
                                "_clean_name": clean_lookup_key(r.iloc[2]),
                                "_clean_specs": clean_lookup_key(r.iloc[3])
                            }
                            rows.append(row)
                    
                    if rows:
                        save_data(TBL_PUR, pd.DataFrame(rows), key_col="item_code")
                        st.success(f"Đã cập nhật {len(rows)} sản phẩm!")
                        st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")

        st.divider()
        up_img = st.file_uploader("Cập nhật ảnh thủ công", type=["png","jpg"])
        code_up = st.text_input("Mã Item cần sửa ảnh")
        if st.button("Cập nhật ảnh") and up_img and code_up:
            fid = upload_bytes_to_drive(up_img, f"p_{code_up}_{int(time.time())}.png", up_img.type)
            if fid:
                supabase_client.table(TBL_PUR).update({"image_path": fid}).eq("item_code", code_up).execute()
                st.success("Đã cập nhật!")

    with col_p2:
        search = st.text_input("🔍 Tìm kiếm hàng hóa")
        df_show = purchases_df.copy()
        if search:
            mask = df_show['item_code'].str.contains(search, case=False) | df_show['item_name'].str.contains(search, case=False)
            df_show = df_show[mask]
        
        st.dataframe(df_show.drop(columns=['image_path','_clean_code','_clean_specs','_clean_name']), use_container_width=True, hide_index=True)
        
        sel = st.selectbox("Xem ảnh chi tiết:", [""] + df_show['item_code'].unique().tolist())
        if sel:
            r = df_show[df_show['item_code'] == sel]
            if not r.empty and r.iloc[0]['image_path']:
                with st.spinner("Đang tải ảnh từ Drive..."):
                    b = get_file_content_as_bytes(r.iloc[0]['image_path'])
                    if b: st.image(b, width=300)
            else: st.info("Sản phẩm chưa có ảnh.")

# --- TAB 3: BÁO GIÁ KHÁCH HÀNG ---
with tab3:
    t3_1, t3_2 = st.tabs(["LẬP BÁO GIÁ", "LỊCH SỬ CHUNG"])
    
    with t3_1:
        c1, c2, c3 = st.columns([1,1,1])
        cust = c1.selectbox("Khách hàng", [""]+customers_df["short_name"].tolist())
        qname = c2.text_input("Tên Báo Giá")
        if c3.button("✨ TẠO MỚI (RESET)", type="primary"):
            st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_COLS)
            st.rerun()

        st.markdown("**Tham số chi phí (%)**")
        col = st.columns(8)
        pe = col[0].text_input("End%", st.session_state.pct_end)
        pb = col[1].text_input("Buy%", st.session_state.pct_buy)
        pt = col[2].text_input("Tax%", st.session_state.pct_tax)
        pv = col[3].text_input("VAT%", st.session_state.pct_vat)
        pp = col[4].text_input("Pay%", st.session_state.pct_pay)
        pm = col[5].text_input("Mgmt%", st.session_state.pct_mgmt)
        ptr = col[6].text_input("Trans", st.session_state.pct_trans)
        
        st.session_state.pct_end=pe; st.session_state.pct_buy=pb; st.session_state.pct_tax=pt
        st.session_state.pct_vat=pv; st.session_state.pct_pay=pp; st.session_state.pct_mgmt=pm
        st.session_state.pct_trans=ptr

        # RFQ Loader (Logic Match y hệt bản cũ)
        up_rfq = st.file_uploader("Load RFQ (Excel)", type=["xlsx"])
        if up_rfq and st.button("Load RFQ"):
            try:
                rfq = pd.read_excel(up_rfq, header=None, dtype=str).fillna("")
                new_d = []
                for _, r in rfq.iloc[1:].iterrows():
                    c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2]); s_raw = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                    if qty <= 0: continue
                    
                    # Logic tìm giá trong DB (match code -> name)
                    clean_c = clean_lookup_key(c_raw); clean_n = clean_lookup_key(n_raw); clean_s = clean_lookup_key(s_raw)
                    found = purchases_df[purchases_df["_clean_code"] == clean_c]
                    if found.empty: found = purchases_df[purchases_df["_clean_name"] == clean_n]
                    
                    target = None
                    if not found.empty:
                        # Ưu tiên specs, sau đó lấy giá cao nhất
                        found = found.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False)
                        f_specs = found[found["_clean_specs"] == clean_s]
                        target = f_specs.iloc[0] if not f_specs.empty else found.iloc[0]
                    
                    it = {k:"" for k in QUOTE_COLS}
                    it.update({"no": safe_str(r.iloc[0]), "item_code": c_raw, "item_name": n_raw, "specs": s_raw, "qty": fmt_num(qty)})
                    
                    if target is not None:
                        # Map giá từ DB
                        it["buying_price_rmb"] = target["buying_price_rmb"]
                        it["buying_price_vnd"] = target["buying_price_vnd"]
                        it["total_buying_price_vnd"] = fmt_num(to_float(target["buying_price_vnd"]) * qty)
                        it["exchange_rate"] = target["exchange_rate"]
                        it["supplier_name"] = target["supplier_name"]
                        it["image_path"] = target["image_path"]
                        it["leadtime"] = target["leadtime"]
                    
                    new_d.append(it)
                st.session_state.current_quote_df = pd.DataFrame(new_d)
                st.rerun()
            except Exception as e: st.error(str(e))

        # Editor
        f1, f2, f3, f4 = st.columns([2,1,2,1])
        ap_f = f1.text_input("AP Formula", key="ap"); 
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i,"ap_price"] = fmt_num(parse_formula(ap_f, to_float(r.get("buying_price_vnd")), 0))
            st.rerun()
        
        u_f = f3.text_input("Unit Formula", key="uf"); 
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i,"unit_price"] = fmt_num(parse_formula(u_f, to_float(r.get("buying_price_vnd")), to_float(r.get("ap_price"))))
            st.rerun()

        # Đã thêm key để tránh duplicate ID
        edited = st.data_editor(
            st.session_state.current_quote_df, 
            num_rows="dynamic", 
            use_container_width=True, 
            key="quote_main_editor",
            column_config={
                "image_path": st.column_config.ImageColumn("Img"),
                "profit_pct": st.column_config.TextColumn("%")
            }
        )
        
        # --- LOGIC TÍNH TOÁN FULL (COPY TỪ BẢN V4.7) ---
        calc = edited.copy()
        gp_tr = to_float(ptr)
        for i, r in calc.iterrows():
            q=to_float(r.get("qty",0)); b=to_float(r.get("buying_price_vnd",0)); a=to_float(r.get("ap_price",0)); u=to_float(r.get("unit_price",0))
            tr = gp_tr if gp_tr > 0 else to_float(r.get("transportation",0))
            
            tb = q*b; at = a*q; tot = u*q; gap = tot - at
            cost = tb + gap + (at*to_float(pe)/100) + (tot*to_float(pb)/100) + (tb*to_float(pt)/100) + (tot*to_float(pv)/100) + (tot*to_float(pm)/100) + (gap*to_float(pp)/100) + (tr*q)
            prof = tot - cost
            
            calc.at[i,"transportation"] = fmt_num(tr)
            calc.at[i,"total_price_vnd"] = fmt_num(tot)
            calc.at[i,"profit_vnd"] = fmt_num(prof)
            calc.at[i,"profit_pct"] = "{:.2f}%".format((prof/tot*100) if tot else 0)
            calc.at[i,"total_buying_price_vnd"] = fmt_num(tb)
            calc.at[i,"ap_total_vnd"] = fmt_num(at)
            calc.at[i,"gap"] = fmt_num(gap)
            calc.at[i,"end_user_val"] = fmt_num(at*to_float(pe)/100)
            calc.at[i,"buyer_val"] = fmt_num(tot*to_float(pb)/100)
            calc.at[i,"import_tax_val"] = fmt_num(tb*to_float(pt)/100)
            calc.at[i,"vat_val"] = fmt_num(tot*to_float(pv)/100)
            calc.at[i,"mgmt_fee"] = fmt_num(tot*to_float(pm)/100)
            calc.at[i,"payback_val"] = fmt_num(gap*to_float(pp)/100)

        if not calc.equals(st.session_state.current_quote_df):
            st.session_state.current_quote_df = calc; st.rerun()

        # Review
        if st.button("🔍 REVIEW PROFIT"):
            st.session_state.show_review_table = not st.session_state.show_review_table
        if st.session_state.show_review_table:
            cols_rv = ["item_code", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]
            st.dataframe(st.session_state.current_quote_df[cols_rv], use_container_width=True)

        # Save History
        c_sv, c_ex = st.columns(2)
        if c_sv.button("💾 LƯU LỊCH SỬ (CLOUD)"):
            if qname:
                final = calc.copy()
                final["history_id"] = f"{qname}_{int(time.time())}"
                final["date"] = datetime.now().strftime("%d/%m/%Y")
                final["quote_no"] = qname; final["customer"] = cust
                final["pct_end"]=pe; final["pct_buy"]=pb; final["pct_tax"]=pt; final["pct_vat"]=pv; final["pct_pay"]=pp; final["pct_mgmt"]=pm; final["pct_trans"]=ptr
                
                save_data(TBL_HIST, final)
                st.success("Saved to Supabase!"); st.rerun()
            else: st.error("Thiếu tên")

        if c_ex.button("XUẤT EXCEL"):
            tid = get_file_id_by_name(TEMPLATE_FILE_NAME)
            if tid:
                bio = get_file_content_as_bytes(tid)
                wb = load_workbook(bio); ws = wb.active
                safe_write_merged(ws, 1, 2, cust); safe_write_merged(ws, 2, 8, qname)
                start=11
                for idx, r in st.session_state.current_quote_df.iterrows():
                    ri = start+idx
                    safe_write_merged(ws, ri, 3, r["item_code"]); safe_write_merged(ws, ri, 4, r["item_name"])
                    safe_write_merged(ws, ri, 6, to_float(r["qty"])); safe_write_merged(ws, ri, 7, to_float(r["unit_price"]))
                    safe_write_merged(ws, ri, 8, to_float(r["total_price_vnd"]))
                out = io.BytesIO(); wb.save(out)
                st.download_button("Tải Excel", out.getvalue(), f"{qname}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else: st.error("Không thấy Template trên Drive")

    with t3_2:
        st.subheader("Tra cứu lịch sử")
        hist = load_data(TBL_HIST, SHARED_HIST_COLS)
        if not hist.empty:
            s = st.text_input("Tìm kiếm lịch sử")
            if s:
                m = hist.apply(lambda x: s.lower() in str(x).lower(), axis=1)
                st.dataframe(hist[m], use_container_width=True)
            else: st.dataframe(hist, use_container_width=True)
            
            sel = st.selectbox("Chọn để tải lại", [""]+list(hist['history_id'].unique()))
            if st.button("♻️ Tải lại") and sel:
                sdf = hist[hist['history_id']==sel]
                if not sdf.empty:
                    fr = sdf.iloc[0]
                    st.session_state.pct_end = str(fr.get('pct_end','0')); st.session_state.pct_buy = str(fr.get('pct_buy','0'))
                    st.session_state.current_quote_df = sdf[QUOTE_COLS].copy()
                    st.success("Loaded!"); st.rerun()

# --- TAB 4: PO ---
with tab4:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("1. PO NCC")
        pn = st.text_input("PO NCC"); su = st.selectbox("NCC", [""]+suppliers_df["short_name"].tolist())
        pd_date = st.text_input("Ngày đặt", value=datetime.now().strftime("%d/%m/%Y"), key="d1")
        upn = st.file_uploader("Excel Items NCC", type=["xlsx"])
        if upn:
            dfn = pd.read_excel(upn, dtype=str).fillna(""); tn = []
            for _, r in dfn.iterrows():
                tn.append({"item_code":safe_str(r.iloc[1]), "qty":fmt_num(to_float(r.iloc[4])), "supplier":su})
            st.session_state.temp_supp_order_df = pd.DataFrame(tn)
        
        edn = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", key="po_ncc_edit")
        if st.button("Xác nhận PO NCC"):
            df = edn.copy(); df["po_number"]=pn; df["supplier"]=su; df["order_date"]=pd_date
            save_data(TBL_PO_S, df)
            # Auto Track
            trk = pd.DataFrame([{"po_no":pn, "partner":su, "status":"Đã đặt hàng", "order_type":"NCC", "finished":"0"}])
            save_data(TBL_TRACK, trk)
            st.success("Done")

    with c2:
        st.subheader("2. PO Khách")
        pc = st.text_input("PO Khách"); cu = st.selectbox("Khách PO", [""]+customers_df["short_name"].tolist())
        pcd = st.text_input("Ngày nhận", value=datetime.now().strftime("%d/%m/%Y"), key="d2")
        fls = st.file_uploader("File PO", accept_multiple_files=True)
        if st.button("Lưu PO Khách"):
            fids = [upload_bytes_to_drive(f, f"PO_{pc}_{f.name}", f.type) for f in fls]
            # Save PO Header
            save_data(TBL_PO_C, pd.DataFrame([{"po_number":pc, "customer":cu, "order_date":pcd, "pdf_path":json.dumps([i for i in fids if i])}]))
            # Auto Track
            save_data(TBL_TRACK, pd.DataFrame([{"po_no":pc, "partner":cu, "status":"Đang xử lý", "order_type":"KH", "finished":"0"}]))
            st.success("Done")

# --- TAB 5: TRACKING & PAYMENT ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI", "LỊCH SỬ THANH TOÁN"])
    with t5_1:
        # Load Tracking with ID
        db_trk = load_data(TBL_TRACK, ["id"]+TRACKING_COLS)
        edt = st.data_editor(
            db_trk, 
            num_rows="dynamic", 
            key="tracking_editor", 
            column_config={"status": st.column_config.SelectboxColumn("Status", options=["Đã đặt hàng", "Đang xử lý", "Hàng đã về", "Đã giao hàng"])}
        )
        
        if st.button("Cập nhật Status"):
            for i, r in edt.iterrows():
                # Logic tự động tạo Payment khi giao hàng xong
                if r["status"] == "Đã giao hàng" and r["finished"] == "0":
                    edt.at[i, "finished"] = "1"; edt.at[i, "last_update"] = datetime.now().strftime("%d/%m/%Y")
                    if r["order_type"] == "KH":
                        term = 30
                        fc = customers_df[customers_df["short_name"]==r["partner"]]
                        if not fc.empty: term = int(to_float(fc.iloc[0]["payment_term"]))
                        due = (datetime.now() + timedelta(days=term)).strftime("%d/%m/%Y")
                        save_data(TBL_PAY, pd.DataFrame([{"po_no":r["po_no"], "customer":r["partner"], "status":"Chưa thanh toán", "due_date":due}]))
            
            save_data(TBL_TRACK, edt, key_col="id")
            st.success("Updated & Auto-Payment Created!")

        st.divider()
        st.write("Upload Proof")
        tid = st.text_input("ID Tracking (Cột ID)"); pf = st.file_uploader("Proof", accept_multiple_files=True)
        if st.button("Up Proof") and tid and pf:
            pids = [upload_bytes_to_drive(f, f"PROOF_{tid}_{f.name}", f.type) for f in pf]
            supabase_client.table(TBL_TRACK).update({"proof_image": json.dumps([p for p in pids if p])}).eq("id", tid).execute()
            st.success("OK")

        st.divider()
        st.markdown("#### Công nợ")
        db_pay = load_data(TBL_PAY, ["id"]+PAYMENT_COLS)
        pend = db_pay[db_pay["status"] != "Đã thanh toán"]
        edp = st.data_editor(pend, num_rows="dynamic", key="pay_edit")
        if st.button("Update Công Nợ"): save_data(TBL_PAY, edp, "id"); st.success("OK")
        
        c1, c2 = st.columns(2)
        po_pay = c1.selectbox("Chọn PO thanh toán", pend["po_no"].unique())
        if c2.button("Xác nhận ĐÃ THANH TOÁN"):
            row = pend[pend["po_no"]==po_pay].iloc[0]
            # Update status
            supabase_client.table(TBL_PAY).update({"status": "Đã thanh toán", "paid_date": datetime.now().strftime("%d/%m/%Y")}).eq("id", row["id"]).execute()
            # Move to history
            row["status"] = "Đã thanh toán"; row["paid_date"] = datetime.now().strftime("%d/%m/%Y")
            if 'id' in row: del row['id']
            save_data(TBL_PAID, pd.DataFrame([row]))
            st.success("Done!"); st.rerun()

    with t5_2:
        st.subheader("Lịch sử đã thanh toán")
        paid = load_data(TBL_PAID, PAID_HIST_COLS)
        st.dataframe(paid, use_container_width=True)

# --- TAB 6: MASTER ---
with tab6:
    c1, c2 = st.columns(2)
    with c1:
        st.write("Khách hàng")
        dbc = load_data(TBL_CUST, ["id"]+MASTER_COLS)
        edc = st.data_editor(dbc, num_rows="dynamic", key="cust_master")
        if st.button("Lưu KH"): save_data(TBL_CUST, edc, "id"); st.success("Saved")
    with c2:
        st.write("NCC")
        dbs = load_data(TBL_SUPP, ["id"]+MASTER_COLS)
        eds = st.data_editor(dbs, num_rows="dynamic", key="supp_master")
        if st.button("Lưu NCC"): save_data(TBL_SUPP, eds, "id"); st.success("Saved")
    
    st.divider()
    ut = st.file_uploader("Update Template", type=["xlsx"])
    if ut and st.button("Update"):
        upload_bytes_to_drive(ut, TEMPLATE_FILE_NAME, ut.type)
        st.success("Updated")
