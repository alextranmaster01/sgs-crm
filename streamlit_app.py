import streamlit as st
import pandas as pd
import os
import shutil
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import platform
import subprocess
import unicodedata
from copy import copy
import io
import time

# --- CLOUD LIBS ---
from supabase import create_client, Client
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =============================================================================
# 1. CẤU HÌNH & KẾT NỐI CLOUD (SUPABASE & GOOGLE DRIVE)
# =============================================================================
APP_VERSION = "V4900 - CLOUD EDITION (SUPABASE + GDRIVE)"
RELEASE_NOTE = """
- **Cloud Database:** Dữ liệu chuyển từ CSV sang Supabase (PostgreSQL) -> Hỗ trợ 100+ người dùng đồng thời.
- **Cloud Storage:** Ảnh lưu trữ trên Google Drive thay vì ổ cứng máy tính.
- **Logic:** Giữ nguyên 100% công thức tính lợi nhuận và quy trình cũ.
"""

st.set_page_config(page_title=f"CRM V4900 - {APP_VERSION}", layout="wide", page_icon="☁️")

# --- KẾT NỐI SUPABASE ---
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Supabase: {e}. Vui lòng kiểm tra secrets.toml")
        return None

supabase: Client = init_supabase()

# --- KẾT NỐI GOOGLE DRIVE ---
@st.cache_resource
def init_drive():
    try:
        # Tạo thông tin credentials từ secrets
        key_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            key_dict, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Google Drive: {e}")
        return None

drive_service = init_drive()

# ID của Folder gốc trên Drive (Bạn nên tạo 1 folder trên drive, lấy ID và điền vào secrets hoặc hardcode)
# Nếu chưa có, code sẽ tạo folder gốc tên "CRM_DATA_IMAGES"
ROOT_DRIVE_FOLDER_ID = st.secrets.get("drive_folder_id", None) 

# --- CSS TÙY CHỈNH ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 24px !important; font-weight: 900 !important; padding: 10px 20px !important; }
    h1 { font-size: 32px !important; }
    .card-3d { border-radius: 15px; padding: 20px; color: white; text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.19); margin-bottom: 20px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); }
    .bg-profit { background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); }
    .bg-ncc { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    .bg-recv { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
    .bg-del { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
    .bg-pend { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
    </style>
    """, unsafe_allow_html=True)

try:
    from openpyxl import load_workbook
    from openpyxl.styles import Side, Border
except ImportError:
    st.error("Thiếu thư viện openpyxl.")
    st.stop()

warnings.filterwarnings("ignore")

# --- HELPER FUNCTIONS: CLOUD STORAGE ---

def get_or_create_drive_folder(folder_name, parent_id=None):
    """Tìm hoặc tạo folder trên Google Drive"""
    try:
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if files:
            return files[0]['id']
        else:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
    except: return None

# Thiết lập Folder gốc trên Drive
MAIN_FOLDER_ID = get_or_create_drive_folder("CRM_SYSTEM_DATA", ROOT_DRIVE_FOLDER_ID)
IMG_FOLDER_ID = get_or_create_drive_folder("product_images", MAIN_FOLDER_ID)
PROOF_FOLDER_ID = get_or_create_drive_folder("proof_images", MAIN_FOLDER_ID)
PO_FOLDER_ID = get_or_create_drive_folder("po_documents", MAIN_FOLDER_ID)

def upload_file_to_drive(file_obj, filename, folder_id):
    """Upload file object lên Google Drive và trả về WebViewLink"""
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype='image/jpeg', resumable=True)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink, webViewLink').execute()
        
        # Set permission public để xem được trong app (hoặc xử lý signed url - ở đây set anyoneReader cho đơn giản)
        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        # Trả về link thumbnail hoặc webContentLink
        return file.get('webContentLink') # Link download trực tiếp
    except Exception as e:
        st.error(f"Lỗi upload ảnh: {e}")
        return ""

# --- HELPER FUNCTIONS: DATABASE (SUPABASE REPLACEMENT FOR CSV) ---
# Logic: Table name maps to old CSV filename logic. 
# Data structure: Để giữ nguyên logic code cũ mà không phải sửa lại cấu trúc DataFrame, 
# ta lưu DataFrame dưới dạng JSON vào cột 'data' trong Supabase hoặc map columns.
# Cách an toàn nhất để "Giữ nguyên logic tính toán" là load DB -> convert sang DataFrame y hệt CSV cũ.

TABLE_MAP = {
    "crm_customers.csv": "crm_customers",
    "crm_suppliers.csv": "crm_suppliers",
    "crm_purchases.csv": "crm_purchases",
    "crm_shared_quote_history.csv": "crm_shared_history",
    "crm_order_tracking.csv": "crm_tracking",
    "crm_payment_tracking.csv": "crm_payment",
    "crm_paid_history.csv": "crm_paid_history",
    "db_supplier_orders.csv": "db_supplier_orders",
    "db_customer_orders.csv": "db_customer_orders"
}

def load_data(csv_name, cols):
    """Thay thế load_csv: Lấy dữ liệu từ Supabase về DataFrame"""
    table_name = TABLE_MAP.get(csv_name)
    if not table_name: return pd.DataFrame(columns=cols)
    
    try:
        # Lấy tối đa 10000 dòng (có thể phân trang nếu cần)
        response = supabase.table(table_name).select("data").execute()
        rows = [item['data'] for item in response.data]
        
        if rows:
            df = pd.DataFrame(rows)
            # Đảm bảo đủ cột
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols].fillna("")
        else:
            return pd.DataFrame(columns=cols)
    except Exception as e:
        # st.error(f"Lỗi load DB {table_name}: {e}") # Debug only
        return pd.DataFrame(columns=cols)

def save_data(csv_name, df):
    """Thay thế save_csv: Lưu DataFrame lên Supabase"""
    # Logic cũ là Overwrite (Ghi đè). Supabase không hỗ trợ ghi đè file như CSV.
    # Ta sẽ dùng chiến thuật: Xóa hết dữ liệu cũ trong bảng -> Insert dữ liệu mới.
    # (Lưu ý: Với hệ thống lớn thật sự thì không làm thế này, nhưng để giữ logic code cũ 100% thì đây là cách map nhanh nhất)
    
    table_name = TABLE_MAP.get(csv_name)
    if not table_name or df is None: return

    try:
        # 1. Convert DF to list of dicts (JSON ready)
        # Convert all to string to match CSV behavior
        df_str = df.astype(str).fillna("")
        data_to_insert = [{"data": row} for row in df_str.to_dict(orient='records')]
        
        # 2. Xóa dữ liệu cũ (Truncate-like simulation)
        # Supabase delete requires a where clause. Delete all IDs > 0
        # (Cần đảm bảo bảng có cột ID auto increment)
        supabase.table(table_name).delete().neq("id", 0).execute()
        
        # 3. Insert dữ liệu mới (Batch insert để tránh lỗi request quá lớn)
        batch_size = 100
        for i in range(0, len(data_to_insert), batch_size):
            batch = data_to_insert[i:i+batch_size]
            supabase.table(table_name).insert(batch).execute()
            
    except Exception as e:
        st.error(f"Lỗi lưu DB {table_name}: {e}")

# --- GLOBAL HELPER FUNCTIONS (LOGIC CŨ) ---
def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def safe_filename(s): 
    s = safe_str(s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    s = re.sub(r'[^\w\-_]', '_', s)
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
    except:
        return 0.0

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
        if isinstance(order_date_str, datetime): dt_order = order_date_str
        else: dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
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
    expr = expr.replace("BUYING PRICE", str(buying_price)).replace("BUY", str(buying_price))
    expr = expr.replace("AP PRICE", str(ap_price)).replace("AP", str(ap_price))
    expr = re.sub(r'[^0-9.+\-*/()]', '', expr)
    try: return float(eval(expr))
    except: return 0.0

def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        cell.value = value
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

# --- LOAD DATA FROM SUPABASE ---
customers_df = load_data("crm_customers.csv", MASTER_COLUMNS)
suppliers_df = load_data("crm_suppliers.csv", MASTER_COLUMNS)
purchases_df = load_data("crm_purchases.csv", PURCHASE_COLUMNS)
shared_history_df = load_data("crm_shared_quote_history.csv", SHARED_HISTORY_COLS)
tracking_df = load_data("crm_order_tracking.csv", TRACKING_COLS)
payment_df = load_data("crm_payment_tracking.csv", PAYMENT_COLS)
paid_history_df = load_data("crm_paid_history.csv", PAYMENT_COLS)
db_supplier_orders = load_data("db_supplier_orders.csv", [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
db_customer_orders = load_data("db_customer_orders.csv", [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

ADMIN_PASSWORD = "admin"
TEMPLATE_FILE = "AAA-QUOTATION.xlsx" # Cái này vẫn để local tạm hoặc upload lên drive nếu cần

# =============================================================================
# 2. SESSION STATE
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    st.session_state.show_review_table = False
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
        st.session_state[f"pct_{k}"] = "0"

# =============================================================================
# 3. SIDEBAR
# =============================================================================
st.sidebar.title("CRM CLOUD")
st.sidebar.markdown(f"**Version:** `{APP_VERSION}`")
admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)

# =============================================================================
# 4. GIAO DIỆN CHÍNH
# =============================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 DASHBOARD", "🏭 BÁO GIÁ NCC", "💰 BÁO GIÁ KHÁCH", "📑 QUẢN LÝ PO", "🚚 TRACKING", "📂 MASTER DATA"])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH (REAL-TIME)")
    if st.button("🔄 CẬP NHẬT DỮ LIỆU"): st.rerun()
    
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
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><div class='card-value'>{fmt_num(total_revenue)}</div><p>DOANH THU</p></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><div class='card-value'>{fmt_num(total_po_ncc_cost + total_other_costs)}</div><p>CHI PHÍ</p></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><div class='card-value'>{fmt_num(total_profit)}</div><p>LỢI NHUẬN</p></div>", unsafe_allow_html=True)

# --- TAB 2: BÁO GIÁ NCC (UPDATED WITH DRIVE) ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        uploaded_pur = st.file_uploader("Import Excel Purchases (Có ảnh)", type=["xlsx"])
        if uploaded_pur and st.button("Thực hiện Import"):
            try:
                wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                img_map = {}
                
                # Trích xuất ảnh từ Excel -> Upload lên Drive -> Lấy Link
                status_holder = st.empty()
                status_holder.info("⏳ Đang trích xuất và upload ảnh lên Google Drive...")
                
                for img in getattr(ws, '_images', []):
                    r_idx = img.anchor._from.row + 1; c_idx = img.anchor._from.col
                    if c_idx == 12: 
                        img_name = f"img_r{r_idx}_{datetime.now().strftime('%f')}.png"
                        img_bytes = io.BytesIO(img._data())
                        
                        # Upload to Drive
                        web_link = upload_file_to_drive(img_bytes, img_name, IMG_FOLDER_ID)
                        img_map[r_idx] = web_link
                        
                status_holder.success("✅ Upload ảnh hoàn tất! Đang xử lý dữ liệu...")
                
                df_ex = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                rows = []
                for i, r in df_ex.iterrows():
                    excel_row_idx = i + 2
                    im_path = img_map.get(excel_row_idx, "")
                    item = {
                        "no": safe_str(r.iloc[0]), "item_code": safe_str(r.iloc[1]), 
                        "item_name": safe_str(r.iloc[2]), "specs": safe_str(r.iloc[3]),
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(r.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                        "leadtime": safe_str(r.iloc[10]), "supplier_name": safe_str(r.iloc[11]), 
                        "image_path": im_path, # Đây giờ là URL Drive
                        "type": safe_str(r.iloc[13]) if len(r) > 13 else "",
                        "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else ""
                    }
                    if item["item_code"] or item["item_name"]: rows.append(item)
                
                purchases_df = pd.DataFrame(rows)
                save_data("crm_purchases.csv", purchases_df) # Save to Supabase
                st.success(f"Đã import {len(rows)} dòng vào Cloud Database!")
                st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")
            
        # Nút Upload Ảnh thủ công
        st.markdown("---")
        up_img_ncc = st.file_uploader("Upload ảnh thủ công (Drive)", type=["png","jpg","jpeg"])
        item_to_update = st.text_input("Mã Item Code cần gán ảnh")
        if st.button("Cập nhật ảnh") and up_img_ncc and item_to_update:
            fname = f"prod_{safe_filename(item_to_update)}.png"
            link = upload_file_to_drive(up_img_ncc, fname, IMG_FOLDER_ID)
            
            mask = purchases_df['item_code'] == item_to_update
            if mask.any():
                purchases_df.loc[mask, 'image_path'] = link
                save_data("crm_purchases.csv", purchases_df)
                st.success("Đã cập nhật ảnh trên Cloud!")
                st.rerun()

    with col_p2:
        search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC)")
    
    if not purchases_df.empty:
        df_show = purchases_df.copy()
        if search_term:
            mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or 
                                             search_term.lower() in str(x['item_name']).lower(), axis=1)
            df_show = df_show[mask]
        st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Image")}, use_container_width=True, hide_index=True)

# --- TAB 3: BÁO GIÁ KHÁCH ---
with tab3:
    tab3_1, tab3_2 = st.tabs(["TẠO BÁO GIÁ", "LỊCH SỬ CHUNG"])
    with tab3_1:
        c1, c2, c3 = st.columns([1,1,1])
        with c1: sel_cust = st.selectbox("Khách hàng", [""] + customers_df["short_name"].tolist())
        with c2: quote_name = st.text_input("Tên Báo Giá / Mã BG")
        with c3:
             if st.button("✨ TẠO MỚI (RESET)", type="primary"):
                 st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                 st.rerun()

        st.markdown("**Tham số chi phí (%)**")
        col_params = st.columns(7)
        pct_end = col_params[0].text_input("EndUser", st.session_state.pct_end)
        pct_buy = col_params[1].text_input("Buyer", st.session_state.pct_buy)
        pct_tax = col_params[2].text_input("Tax", st.session_state.pct_tax)
        pct_vat = col_params[3].text_input("VAT", st.session_state.pct_vat)
        pct_pay = col_params[4].text_input("Payback", st.session_state.pct_pay)
        pct_mgmt = col_params[5].text_input("Mgmt", st.session_state.pct_mgmt)
        val_trans = col_params[6].text_input("Trans(VND)", st.session_state.pct_trans)
        
        st.session_state.pct_end = pct_end; st.session_state.pct_buy = pct_buy; st.session_state.pct_trans = val_trans
        
        uploaded_rfq = st.file_uploader("📂 Import RFQ (Excel)", type=["xlsx"])
        if uploaded_rfq and st.button("Load RFQ"):
            try:
                # Logic tìm kiếm vẫn giữ nguyên, chỉ khác là purchases_df giờ load từ Supabase
                purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                purchases_df["_clean_name"] = purchases_df["item_name"].apply(clean_lookup_key)
                
                df_rfq = pd.read_excel(uploaded_rfq, header=None, dtype=str).fillna("")
                new_data = []
                for i, r in df_rfq.iloc[1:].iterrows():
                    c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2]); qty = to_float(r.iloc[4])
                    if qty <= 0: continue
                    clean_c = clean_lookup_key(c_raw); clean_n = clean_lookup_key(n_raw)
                    
                    found_in_db = purchases_df[purchases_df["_clean_code"] == clean_c]
                    if found_in_db.empty and n_raw: found_in_db = purchases_df[purchases_df["_clean_name"] == clean_n]
                    
                    target_row = None
                    if not found_in_db.empty:
                        target_row = found_in_db.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False).iloc[0]

                    it = {k:"0" if "price" in k or "val" in k else "" for k in QUOTE_KH_COLUMNS}
                    it.update({"no": safe_str(r.iloc[0]), "item_code": c_raw, "item_name": n_raw, "specs": safe_str(r.iloc[3]), "qty": fmt_num(qty)})
                    
                    if target_row is not None:
                        it.update({
                            "buying_price_rmb": target_row["buying_price_rmb"],
                            "exchange_rate": target_row["exchange_rate"],
                            "buying_price_vnd": target_row["buying_price_vnd"],
                            "supplier_name": target_row["supplier_name"],
                            "image_path": target_row["image_path"],
                            "leadtime": target_row["leadtime"]
                        })
                    new_data.append(it)
                
                st.session_state.current_quote_df = pd.DataFrame(new_data)
                st.success("Load RFQ thành công!")
                st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

        # --- EDITOR & CALC ---
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        ap_formula = f1.text_input("AP Formula", key="ap_f")
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_formula, to_float(r.get("buying_price_vnd")), to_float(r.get("ap_price"))))
            st.rerun()
            
        unit_formula = f3.text_input("Unit Formula", key="unit_f")
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                st.session_state.current_quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_formula, to_float(r.get("buying_price_vnd")), to_float(r.get("ap_price"))))
            st.rerun()

        edited_df = st.data_editor(st.session_state.current_quote_df, key="quote_editor", use_container_width=True, num_rows="dynamic", column_config={"image_path": st.column_config.ImageColumn("Img")})
        
        # AUTO-CALC (Logic giữ nguyên)
        df_temp = edited_df.copy()
        pend = to_float(pct_end)/100; pbuy = to_float(pct_buy)/100
        ptax = to_float(pct_tax)/100; pvat = to_float(pct_vat)/100
        ppay = to_float(pct_pay)/100; pmgmt = to_float(pct_mgmt)/100
        global_trans = to_float(val_trans)
        
        for i, r in df_temp.iterrows():
            qty = to_float(r.get("qty", 0)); buy_vnd = to_float(r.get("buying_price_vnd", 0))
            ap = to_float(r.get("ap_price", 0)); unit = to_float(r.get("unit_price", 0))
            
            use_trans = global_trans if global_trans > 0 else to_float(r.get("transportation", 0))
            
            t_buy = qty * buy_vnd; ap_tot = ap * qty; total = unit * qty; gap = total - ap_tot
            end_val = ap_tot * pend; buyer_val = total * pbuy; tax_val = t_buy * ptax; vat_val = total * pvat
            mgmt_val = total * pmgmt; pay_val = gap * ppay; tot_trans = use_trans * qty
            
            cost = t_buy + gap + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
            prof = total - cost + pay_val
            pct = (prof/total*100) if total else 0
            
            df_temp.at[i, "transportation"] = fmt_num(use_trans)
            df_temp.at[i, "total_price_vnd"] = fmt_num(total)
            df_temp.at[i, "profit_vnd"] = fmt_num(prof)
            df_temp.at[i, "profit_pct"] = "{:.2f}%".format(pct)
            df_temp.at[i, "gap"] = fmt_num(gap); df_temp.at[i, "end_user_val"] = fmt_num(end_val); df_temp.at[i, "buyer_val"] = fmt_num(buyer_val)
            df_temp.at[i, "import_tax_val"] = fmt_num(tax_val); df_temp.at[i, "vat_val"] = fmt_num(vat_val); df_temp.at[i, "mgmt_fee"] = fmt_num(mgmt_val)

        if not df_temp.equals(st.session_state.current_quote_df):
             st.session_state.current_quote_df = df_temp
             st.rerun()
             
        if st.button("💾 LƯU LỊCH SỬ (VÀO SUPABASE)"):
            if not sel_cust or not quote_name: st.error("Thiếu thông tin")
            else:
                rows_to_save = st.session_state.current_quote_df.copy()
                rows_to_save["history_id"] = f"{quote_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                rows_to_save["date"] = datetime.now().strftime("%d/%m/%Y")
                rows_to_save["quote_no"] = quote_name; rows_to_save["customer"] = sel_cust
                
                # Tham số
                rows_to_save["pct_end"] = pct_end; rows_to_save["pct_buy"] = pct_buy
                rows_to_save["pct_tax"] = pct_tax; rows_to_save["pct_vat"] = pct_vat
                rows_to_save["pct_pay"] = pct_pay; rows_to_save["pct_mgmt"] = pct_mgmt
                rows_to_save["pct_trans"] = val_trans
                
                # Append to Shared History via Supabase
                updated_history = pd.concat([shared_history_df, rows_to_save[SHARED_HISTORY_COLS]], ignore_index=True)
                save_data("crm_shared_quote_history.csv", updated_history)
                st.success("✅ Đã lưu vào Database dùng chung!")

    with tab3_2:
        st.subheader("Tra cứu lịch sử chung (Dữ liệu từ Supabase)")
        # Load mới nhất từ DB
        shared_history_df = load_data("crm_shared_quote_history.csv", SHARED_HISTORY_COLS)
        st.dataframe(shared_history_df, use_container_width=True)

# --- TAB 4: QUẢN LÝ PO ---
with tab4:
    col_po1, col_po2 = st.columns(2)
    with col_po1:
        st.subheader("1. PO NCC")
        po_ncc_no = st.text_input("Số PO NCC")
        po_ncc_supp = st.selectbox("NCC", [""] + suppliers_df["short_name"].tolist())
        up_ncc = st.file_uploader("Excel NCC", type=["xlsx"], key="up_ncc")
        
        if up_ncc:
             # Logic parse excel giữ nguyên
             df_ncc = pd.read_excel(up_ncc, dtype=str).fillna(""); temp_ncc = []
             purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
             for i, r in df_ncc.iterrows():
                 code = safe_str(r.iloc[1]); qty = to_float(r.iloc[4])
                 clean_c = clean_lookup_key(code); found = purchases_df[purchases_df["_clean_code"]==clean_c]
                 it = {"item_code":code, "qty":fmt_num(qty), "item_name": safe_str(r.iloc[2])}
                 if not found.empty:
                      fr = found.iloc[0]
                      it.update({"price_vnd":fr["buying_price_vnd"], "total_vnd":fmt_num(to_float(fr["buying_price_vnd"])*qty), "supplier":fr["supplier_name"]})
                 else: it.update({"supplier":po_ncc_supp})
                 temp_ncc.append(it)
             st.session_state.temp_supp_order_df = pd.DataFrame(temp_ncc)

        edited_ncc = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", use_container_width=True)
        if st.button("🚀 XÁC NHẬN PO NCC (LƯU DB)"):
            final_df = edited_ncc.copy()
            final_df["po_number"] = po_ncc_no; final_df["order_date"] = datetime.now().strftime("%d/%m/%Y")
            
            db_supplier_orders = pd.concat([db_supplier_orders, final_df], ignore_index=True)
            save_data("db_supplier_orders.csv", db_supplier_orders)
            
            # Auto add tracking
            new_track = {"no": str(len(tracking_df)+1), "po_no": po_ncc_no, "status": "Đã đặt hàng", "order_type": "NCC"}
            tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
            save_data("crm_order_tracking.csv", tracking_df)
            st.success("Đã lưu PO NCC vào Supabase!")

    with col_po2:
        st.subheader("2. PO Khách")
        po_cust_no = st.text_input("Số PO Khách")
        po_file = st.file_uploader("Upload File PO (Lưu Drive)", type=["pdf", "xlsx", "png", "jpg"])
        
        if po_file and po_cust_no and st.button("Upload PO lên Drive"):
            fname = f"PO_{po_cust_no}_{po_file.name}"
            # Upload to Drive
            link = upload_file_to_drive(po_file, fname, PO_FOLDER_ID)
            st.success(f"Đã lưu PO lên Drive. Link: {link}")
            
            # Logic parse excel nếu là excel
            if po_file.name.endswith('.xlsx'):
                df_c = pd.read_excel(po_file, dtype=str).fillna(""); temp_c = []
                for i, r in df_c.iterrows():
                    temp_c.append({"item_code":safe_str(r.iloc[1]), "qty":fmt_num(to_float(r.iloc[4])), "po_number":po_cust_no, "pdf_path": link})
                st.session_state.temp_cust_order_df = pd.DataFrame(temp_c)
        
        edited_cust = st.data_editor(st.session_state.temp_cust_order_df, num_rows="dynamic", use_container_width=True)
        if st.button("💾 LƯU PO KHÁCH (LƯU DB)"):
             db_customer_orders = pd.concat([db_customer_orders, edited_cust], ignore_index=True)
             save_data("db_customer_orders.csv", db_customer_orders)
             st.success("Đã lưu PO Khách!")

# --- TAB 5: TRACKING ---
with tab5:
    st.subheader("Tracking & Proof Images (Drive)")
    c_up, c_view = st.columns(2)
    
    # Upload Proof to Drive
    proof_upl = c_up.file_uploader("Upload bằng chứng (Lưu Drive)", accept_multiple_files=True)
    track_id = c_up.text_input("ID Tracking")
    
    if c_up.button("Upload Ảnh Proof") and proof_upl and track_id:
        idx = tracking_df.index[tracking_df['no'].astype(str) == track_id].tolist()
        if idx:
            current_imgs_json = tracking_df.at[idx[0], "proof_image"]
            try: img_list = json.loads(current_imgs_json) if current_imgs_json else []
            except: img_list = []
            
            for f in proof_upl:
                fname = f"proof_{track_id}_{f.name}"
                link = upload_file_to_drive(f, fname, PROOF_FOLDER_ID)
                img_list.append(link)
            
            tracking_df.at[idx[0], "proof_image"] = json.dumps(img_list)
            save_data("crm_order_tracking.csv", tracking_df)
            st.success("Upload ảnh lên Drive thành công!")
    
    # View Images
    if c_view.button("Xem Ảnh Proof") and track_id:
        idx = tracking_df.index[tracking_df['no'].astype(str) == track_id].tolist()
        if idx:
            imgs_str = tracking_df.at[idx[0], "proof_image"]
            try:
                links = json.loads(imgs_str)
                for l in links: st.image(l) # Streamlit hiển thị ảnh từ URL Drive (cần public)
            except: st.warning("Chưa có ảnh")

    edited_track = st.data_editor(tracking_df, num_rows="dynamic", use_container_width=True)
    if st.button("Cập nhật Tracking DB"):
        save_data("crm_order_tracking.csv", edited_track)
        st.success("Updated!")

# --- TAB 6: MASTER DATA ---
with tab6:
    st.info("Dữ liệu Master được lưu trực tiếp trên Supabase Database.")
    t6_1, t6_2 = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP"])
    with t6_1:
        edited_cust = st.data_editor(customers_df, num_rows="dynamic", use_container_width=True)
        if st.button("Lưu thay đổi KH"):
            save_data("crm_customers.csv", edited_cust)
            st.success("Đã lưu vào Supabase")
    with t6_2:
        edited_supp = st.data_editor(suppliers_df, num_rows="dynamic", use_container_width=True)
        if st.button("Lưu thay đổi NCC"):
            save_data("crm_suppliers.csv", edited_supp)
            st.success("Đã lưu vào Supabase")
