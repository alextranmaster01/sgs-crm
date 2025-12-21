import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import json
import io
import time
import unicodedata
import mimetypes
import numpy as np

# --- THƯ VIỆN KẾT NỐI CLOUD ---
try:
    from openpyxl import load_workbook
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from openpyxl.styles import Border, Side, Alignment, Font
except ImportError:
    st.error("⚠️ Cài đặt: pip install pandas openpyxl supabase google-api-python-client google-auth-oauthlib numpy")
    st.stop()

# =============================================================================
# CẤU HÌNH & VERSION
# =============================================================================
APP_VERSION = "V4871 - FINAL ULTIMATE (4-KEY UNIQUE IMPORT + FIX TRACKING)"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 20px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 15px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    
    /* Fix bảng và ẩn index */
    [data-testid="stDataFrame"] { margin-bottom: 20px; }
    [data-testid="stDataFrame"] > div { height: auto !important; min_height: 150px; max_height: 1000px; overflow-y: auto; }
    [data-testid="stDataFrame"] table thead th:first-child { display: none; }
    [data-testid="stDataFrame"] table tbody td:first-child { display: none; }
    
    /* Alert Box */
    .alert-box {
        padding: 15px;
        background-color: #ffcccc;
        color: #cc0000;
        border-radius: 5px;
        border: 1px solid #ff0000;
        font-weight: bold;
        margin-top: 10px;
    }
    </style>""", unsafe_allow_html=True)

# --- KẾT NỐI SERVER ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi Config: {e}")
    st.stop()

# --- XỬ LÝ GOOGLE DRIVE ---
def get_drive_service():
    try:
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], client_secret=OAUTH_INFO["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

def upload_to_drive(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return ""
    try:
        q_f = f"'{ROOT_FOLDER_ID}' in parents and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        folder_id = folders[0]['id'] if folders else srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
        srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        q_file = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        existing = srv.files().list(q=q_file, fields='files(id)').execute().get('files', [])
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        
        if existing:
            file_id = existing[0]['id']
            srv.files().update(fileId=file_id, media_body=media, fields='id').execute()
        else:
            file_id = srv.files().create(body={'name': file_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()['id']
        
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=200" 
    except: return ""

# --- DATA HELPERS ---
def get_scalar(val):
    if isinstance(val, pd.Series): return val.iloc[0] if not val.empty else None
    if isinstance(val, (list, np.ndarray)): return val[0] if len(val) > 0 else None
    return val

def safe_str(val):
    val = get_scalar(val)
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def safe_filename(s): return re.sub(r'[^\w\-_]', '_', unicodedata.normalize('NFKD', safe_str(s)).encode('ascii', 'ignore').decode('utf-8')).strip('_')

def to_float(val):
    val = get_scalar(val)
    if val is None: return 0.0
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").upper()
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(nums[0]) if nums else 0.0
    except: return 0.0

def fmt_num(x): return "{:,.0f}".format(x) if x else "0"
def clean_key(s): return re.sub(r'[^a-zA-Z0-9]', '', safe_str(s)).lower()
def normalize_header(h): return re.sub(r'[^a-zA-Z0-9]', '', str(h).lower())

def parse_formula(formula, buying, ap):
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying)).replace("BUY", str(buying)).replace("AP PRICE", str(ap)).replace("AP", str(ap))
    try: return float(eval(re.sub(r'[^0-9.+\-*/()]', '', expr)))
    except: return 0.0

# --- MAPPING & COLUMNS ---
QUOTE_DISPLAY_COLS = [
    "No", "Item code", "Item name", "Specs", "Q'ty",
    "Buying price (RMB)", "Total buying price (RMB)", "Exchange rate",
    "Buying price (VND)", "Total buying price (VND)",
    "AP price (VND)", "AP total price (VND)",
    "Unit price (VND)", "Total price (VND)",
    "GAP", "End user", "Buyer", "Import tax", "VAT", "Transportation", "Management fee", "Payback",
    "Profit (VND)", "Profit (%)",
    "Leadtime", "Supplier", "Images", "Type", "N/U/O/C"
]

REVIEW_COLS = [
    "No", "Item code", "Item name", "Specs", "Q'ty",
    "Unit price (VND)", "Total price (VND)", "Profit (VND)", "Profit (%)"
]

MAP_PURCHASE = {
    "itemcode": "item_code", "itemname": "item_name", "specs": "specs", "qty": "qty",
    "buyingpricermb": "buying_price_rmb", "totalbuyingpricermb": "total_buying_price_rmb",
    "exchangerate": "exchange_rate", "buyingpricevnd": "buying_price_vnd",
    "totalbuyingpricevnd": "total_buying_price_vnd", "leadtime": "leadtime",
    "supplier": "supplier_name", 
    "type": "type",   # Cột N
    "nuoc": "nuoc"    # Cột O
}
MAP_MASTER = {
    "shortname": "short_name", "engname": "eng_name", "vnname": "vn_name",
    "address1": "address_1", "address_2": "address_2", "contactperson": "contact_person",
    "director": "director", "phone": "phone", "fax": "fax", "taxcode": "tax_code",
    "destination": "destination", "paymentterm": "payment_term"
}

# --- DB HANDLERS ---
@st.cache_data(ttl=5) 
def load_data(table):
    try:
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df = df.loc[:, ~df.columns.duplicated()]
            for c in ['id', '_clean_code', '_clean_name', '_clean_specs']:
                if c in df.columns: df = df.drop(columns=[c])
        return df
    except: return pd.DataFrame()

def save_data(table, df, unique_cols=None):
    """
    Hàm lưu dữ liệu (Upsert).
    """
    if df.empty: return
    try:
        # Chuẩn hóa tên cột
        db_cols_map = {
            "Item code": "item_code", "Item name": "item_name", "Specs": "specs", "Q'ty": "qty",
            "Buying price (RMB)": "buying_price_rmb", "Total buying price (RMB)": "total_buying_price_rmb",
            "Exchange rate": "exchange_rate", "Buying price (VND)": "buying_price_vnd",
            "Total buying price (VND)": "total_buying_price_vnd",
            "AP price (VND)": "ap_price", "AP total price (VND)": "ap_total_vnd",
            "Unit price (VND)": "unit_price", "Total price (VND)": "total_price_vnd",
            "GAP": "gap", "End user": "end_user_val", "Buyer": "buyer_val",
            "Import tax": "import_tax_val", "VAT": "vat_val", "Transportation": "transportation",
            "Management fee": "mgmt_fee", "Payback": "payback_val",
            "Profit (VND)": "profit_vnd", "Profit (%)": "profit_pct",
            "Leadtime": "leadtime", "Supplier": "supplier_name", "Images": "image_path"
        }
        df = df.rename(columns=db_cols_map)

        valid_db_cols = set(list(MAP_PURCHASE.values()) + list(MAP_MASTER.values()) + [
            "image_path", "po_number", "order_date", "price_rmb", "total_rmb", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path",
            "customer", "unit_price", "total_price", "base_buying_vnd", "full_cost_total",
            "po_no", "partner", "status", "proof_image", "order_type", "last_update", "finished",
            "invoice_no", "due_date", "paid_date",
            "history_id", "date", "quote_no", "ap_price", "ap_total_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"
        ])
        
        recs = df.to_dict(orient='records')
        clean_recs = []
        for r in recs:
            clean = {k: safe_str(v) for k,v in r.items() if k in valid_db_cols}
            if clean: clean_recs.append(clean)
        
        # Gửi dữ liệu theo batch
        if unique_cols:
            conflict_target = ",".join(unique_cols)
            chunk_size = 500
            for i in range(0, len(clean_recs), chunk_size):
                supabase.table(table).upsert(clean_recs[i:i+chunk_size], on_conflict=conflict_target).execute()
        else:
            chunk_size = 500
            for i in range(0, len(clean_recs), chunk_size):
                supabase.table(table).upsert(clean_recs[i:i+chunk_size]).execute()
            
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Lưu Lỗi ({table}): {e}")

# --- LOGIC MATCHING THÔNG MINH ---
def run_smart_matching(rfq_file, db_df):
    lookup_code = {}
    lookup_name = {}
    lookup_specs = {}
    
    for _, row in db_df.iterrows():
        data = {
            'price_rmb': to_float(row.get('buying_price_rmb')),
            'rate': to_float(row.get('exchange_rate')),
            'lead': safe_str(row.get('leadtime')),
            'supp': safe_str(row.get('supplier_name')),
            'img': safe_str(row.get('image_path')),
            'type': safe_str(row.get('type')),
            'nuoc': safe_str(row.get('nuoc'))
        }
        c_key = clean_key(row.get('item_code'))
        n_key = clean_key(row.get('item_name'))
        s_key = clean_key(row.get('specs'))
        
        if c_key: lookup_code[c_key] = data
        if n_key: lookup_name[n_key] = data
        if s_key: lookup_specs[s_key] = data

    df_rfq = pd.read_excel(rfq_file, header=0, dtype=str).fillna("")
    df_rfq = df_rfq.loc[:, ~df_rfq.columns.duplicated()]
    rfq_map = {normalize_header(c): c for c in df_rfq.columns}
    
    results = []
    
    for _, r in df_rfq.iterrows():
        no = safe_str(r.get(rfq_map.get('no')))
        code = safe_str(r.get(rfq_map.get('itemcode')))
        name = safe_str(r.get(rfq_map.get('itemname')))
        specs = safe_str(r.get(rfq_map.get('specs')))
        qty_key = rfq_map.get('qty') or rfq_map.get('qty') or rfq_map.get('quantity')
        qty_val = to_float(r.get(qty_key))

        info = None
        if clean_key(code) in lookup_code: info = lookup_code[clean_key(code)]
        elif clean_key(name) in lookup_name: info = lookup_name[clean_key(name)]
        elif clean_key(specs) in lookup_specs: info = lookup_specs[clean_key(specs)]
            
        if not info:
            info = {'price_rmb': 0, 'rate': 0, 'lead': '', 'supp': '', 'img': '', 'type': '', 'nuoc': ''}
        
        rmb = info['price_rmb']
        rate = info['rate'] if info['rate'] > 0 else 4000
        
        row_res = {
            "No": no, "Item code": code, "Item name": name, "Specs": specs, "Q'ty": fmt_num(qty_val),
            "Buying price (RMB)": fmt_num(rmb),
            "Total buying price (RMB)": fmt_num(rmb * qty_val),
            "Exchange rate": fmt_num(rate),
            "Buying price (VND)": fmt_num(rmb * rate),
            "Total buying price (VND)": fmt_num(rmb * qty_val * rate),
            "AP price (VND)": "0", "AP total price (VND)": "0",
            "Unit price (VND)": "0", "Total price (VND)": "0",
            "GAP": "0", "End user": "0", "Buyer": "0", "Import tax": "0", "VAT": "0",
            "Transportation": "0", "Management fee": "0", "Payback": "0",
            "Profit (VND)": "0", "Profit (%)": "0%",
            "Leadtime": info['lead'], "Supplier": info['supp'], "Images": info['img'],
            "Type": info['type'], "N/U/O/C": info['nuoc']
        }
        results.append(row_res)
        
    return pd.DataFrame(results)

# --- INIT STATE ---
if 'init' not in st.session_state:
    st.session_state.init = True

# Khởi tạo trước để tránh lỗi AttributeError
if 'current_quote_df' not in st.session_state:
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_DISPLAY_COLS)

if 'quote_result' not in st.session_state:
    st.session_state.quote_result = pd.DataFrame()
if 'temp_supp' not in st.session_state:
    st.session_state.temp_supp = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "supplier"])
if 'temp_cust' not in st.session_state:
    st.session_state.temp_cust = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "unit_price", "total_price", "customer"])
if 'quote_template' not in st.session_state:
    st.session_state.quote_template = None
for k in ["end","buy","tax","vat","pay","mgmt","trans"]: 
    if f"pct_{k}" not in st.session_state: st.session_state[f"pct_{k}"] = "0"
if 'customer_name' not in st.session_state: st.session_state.customer_name = ""
if 'quote_number' not in st.session_state: st.session_state.quote_number = ""

# --- UI ---
st.title("HỆ THỐNG CRM QUẢN LÝ (V4871)")
is_admin = (st.sidebar.text_input("Admin Password", type="password") == "admin")

t1, t2, t3, t4, t5, t6 = st.tabs(["DASHBOARD", "KHO HÀNG (PURCHASES)", "BÁO GIÁ (QUOTES)", "ĐƠN HÀNG (PO)", "TRACKING", "DỮ LIỆU NỀN"])

# --- TAB 1: DASHBOARD ---
with t1:
    with st.spinner("Đang tính toán..."):
        if not get_drive_service(): st.stop()
        db_cust = load_data("db_customer_orders")
        db_supp = load_data("db_supplier_orders")
        track = load_data("crm_tracking")
        
        rev = db_cust['total_price'].apply(to_float).sum() if not db_cust.empty else 0
        cost_ncc = db_supp['total_vnd'].apply(to_float).sum() if not db_supp.empty else 0
        profit = rev - cost_ncc
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='card-3d bg-cost'><h3>TỔNG CHI PHÍ</h3><h1>{fmt_num(cost_ncc)}</h1></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: PURCHASES ---
with t2:
    purchases_df = load_data("crm_purchases")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.info("Import file BUYING PRICE-ALL.xlsx")
        up_file = st.file_uploader("Chọn file Excel", type=["xlsx"], key="up_pur")
        if up_file and st.button("🚀 IMPORT & TÍNH TOÁN"):
            try:
                # 1. Đọc file Excel cơ bản (Header = 0)
                df = pd.read_excel(up_file, header=0, dtype=str).fillna("")
                df = df.loc[:, ~df.columns.duplicated()]
                
                img_map = {}
                try:
                    wb = load_workbook(up_file, data_only=False); ws = wb.active
                    for img in getattr(ws, '_images', []):
                        img_map[img.anchor._from.row + 1] = img
                except: pass
                
                rows = []
                bar = st.progress(0)
                hn = {normalize_header(c): c for c in df.columns}
                
                # 2. Loop & Map
                for i, r in df.iterrows():
                    d = {}
                    for nk, db in MAP_PURCHASE.items():
                        if nk in hn: d[db] = safe_str(r[hn[nk]])
                    
                    if not d.get('item_code'): continue
                    
                    img_url = ""
                    if (i+2) in img_map:
                        try:
                            buf = io.BytesIO(img_map[i+2]._data())
                            fname = f"IMG_{safe_filename(d['item_code'])}.png"
                            img_url = upload_to_drive(buf, "CRM_PURCHASE_IMAGES", fname)
                        except: pass
                    if img_url: d['image_path'] = img_url
                    
                    d['_clean_code'] = clean_key(d.get('item_code'))
                    d['_clean_name'] = clean_key(d.get('item_name'))
                    d['_clean_specs'] = clean_key(d.get('specs'))
                    
                    qty = to_float(d.get('qty'))
                    price_rmb = to_float(d.get('buying_price_rmb'))
                    rate = to_float(d.get('exchange_rate'))
                    if rate == 0: rate = 4000
                    
                    d['total_buying_price_rmb'] = fmt_num(qty * price_rmb)
                    d['exchange_rate'] = fmt_num(rate)
                    d['buying_price_vnd'] = fmt_num(price_rmb * rate)
                    d['total_buying_price_vnd'] = fmt_num(qty * price_rmb * rate)

                    rows.append(d)
                    bar.progress((i+1)/len(df))
                
                # --- LOGIC MỚI: DEDUPLICATE THEO 4 KEY (Code, Name, Specs, Price) ---
                # Chuyển list -> DataFrame để lọc
                df_rows = pd.DataFrame(rows)
                if not df_rows.empty:
                    # Logic: Giữ lại tất cả các dòng khác nhau về (Code, Name, Specs, Price)
                    # Nếu trùng cả 4 thì giữ dòng cuối
                    df_rows = df_rows.drop_duplicates(subset=['item_code', 'item_name', 'specs', 'buying_price_rmb'], keep='last')
                    
                    # Chuyển lại thành list dict
                    valid_cols = list(MAP_PURCHASE.values()) + ["image_path", "_clean_code", "_clean_name", "_clean_specs"]
                    clean_final = []
                    for r in df_rows.to_dict('records'):
                        c = {k: str(v) if v is not None and str(v)!='nan' else None for k,v in r.items() if k in valid_cols}
                        if c: clean_final.append(c)

                    # Lưu (Upsert) - Lưu ý: Nếu DB vẫn còn constraint 3 key cũ, nó có thể lỗi nếu trùng (Code, Price, NUOC)
                    # Nhưng theo yêu cầu là "bắt buộc import", nên ta dùng upsert. 
                    # Nếu DB không cho phép, bạn cần xóa constraint cũ trong Supabase.
                    if clean_final:
                        # Thử upsert (Nếu conflict key không khớp DB thì nó sẽ insert)
                        supabase.table("crm_purchases").upsert(clean_final).execute()
                
                st.cache_data.clear()
                st.success(f"✅ Đã import {len(rows)} mã hàng! (Logic Unique 4 keys)"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")
            
        st.divider()
        if is_admin:
            if st.button("⚠️ RESET DATABASE KHO HÀNG"):
                try:
                    supabase.table("crm_purchases").delete().neq("item_code", "XXXX").execute()
                    st.success("Đã xóa sạch dữ liệu kho hàng!"); time.sleep(1); st.rerun()
                except Exception as e: st.error(f"Lỗi Reset: {e}")

    with c2:
        search = st.text_input("Search", key="search_pur")
        view = purchases_df.copy()
        if search:
            mask = view.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
            view = view[mask]
        
        # Ẩn index, hiện cột No
        st.dataframe(view, column_config={"image_path": st.column_config.ImageColumn("Hình ảnh")}, use_container_width=True, height=800, hide_index=True)

# --- TAB 3: QUOTES ---
with t3:
    if st.button("🆕 TẠO BÁO GIÁ MỚI (RESET)"):
        st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_DISPLAY_COLS)
        st.session_state.customer_name = ""
        st.session_state.quote_number = ""
        st.rerun()

    # KHUNG TÍNH TOÁN
    with st.container(border=True):
        st.header("1. TÍNH TOÁN GIÁ")
        c_inf1, c_inf2 = st.columns(2)
        st.session_state.customer_name = c_inf1.text_input("Tên Khách Hàng", st.session_state.customer_name)
        st.session_state.quote_number = c_inf2.text_input("Số Báo Giá", st.session_state.quote_number)
        
        with st.expander("CẤU HÌNH TÍNH TOÁN (%)", expanded=True):
            cols = st.columns(7)
            pct_inputs = {}
            labels = ["END USER(%)", "BUYER(%)", "TAX(%)", "VAT(%)", "PAYBACK(%)", "MGMT(%)", "TRANS(VND)"]
            keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
            for i, (label, key) in enumerate(zip(labels, keys)):
                val = st.session_state.get(f"pct_{key}", "0")
                pct_inputs[key] = cols[i].text_input(label, val)
                st.session_state[f"pct_{key}"] = pct_inputs[key]

        col_up, col_act = st.columns([1, 2])
        with col_up:
            up_rfq = st.file_uploader("Upload 'RFQ-38 FROM ALL.xlsx'", type=["xlsx"], key="up_rfq")
        with col_act:
            st.write(""); st.write("")
            if up_rfq and st.button("🚀 BƯỚC 1: LẤY GIÁ VỐN (MATCHING)"):
                if purchases_df.empty:
                    st.error("Chưa có dữ liệu trong Kho hàng.")
                else:
                    try:
                        st.session_state.current_quote_df = run_smart_matching(up_rfq, purchases_df)
                        st.success("Đã tìm thấy giá vốn!")
                    except Exception as e: st.error(f"Lỗi tính toán: {e}")

        # TÍNH TOÁN TỨC THÌ
        if 'current_quote_df' in st.session_state and not st.session_state.current_quote_df.empty:
            st.write("---")
            f1, f2 = st.columns(2)
            ap_f = f1.text_input("AP Formula (e.g. =BUY*1.1)", key="ap_formula_in")
            unit_f = f2.text_input("Unit Formula (e.g. =AP*1.2)", key="unit_formula_in")
            
            df = st.session_state.current_quote_df.copy()
            
            p_end = to_float(st.session_state.pct_end)/100
            p_buy = to_float(st.session_state.pct_buy)/100
            p_tax = to_float(st.session_state.pct_tax)/100
            p_vat = to_float(st.session_state.pct_vat)/100
            p_pay = to_float(st.session_state.pct_pay)/100
            p_mgmt = to_float(st.session_state.pct_mgmt)/100
            trans = to_float(st.session_state.pct_trans)
            
            for i, r in df.iterrows():
                buy_vnd = to_float(r["Buying price (VND)"])
                curr_ap = to_float(r.get("AP price (VND)", 0))
                
                if ap_f:
                    curr_ap = parse_formula(ap_f, buy_vnd, curr_ap)
                    df.at[i, "AP price (VND)"] = fmt_num(curr_ap)
                
                if unit_f:
                    new_unit = parse_formula(unit_f, buy_vnd, curr_ap)
                    df.at[i, "Unit price (VND)"] = fmt_num(new_unit)
                
                qty = to_float(r["Q'ty"])
                unit_sell = to_float(df.at[i, "Unit price (VND)"])
                ap_price = to_float(df.at[i, "AP price (VND)"])
                
                total_sell = unit_sell * qty
                ap_total = ap_price * qty
                buy_total = to_float(r["Total buying price (VND)"])
                
                gap = total_sell - ap_total 
                gap_share = gap * 0.6 if gap > 0 else 0
                
                v_end = ap_total * p_end
                v_buy = total_sell * p_buy
                v_tax = total_sell * p_tax
                v_vat = total_sell * p_vat
                v_mgmt = total_sell * p_mgmt
                v_trans = trans * qty
                
                ops = gap_share + v_end + v_buy + v_tax + v_vat + v_mgmt + v_trans
                v_payback = gap * p_pay
                profit = total_sell - buy_total - ops + v_payback
                pct_profit = (profit / total_sell * 100) if total_sell else 0
                
                df.at[i, "AP total price (VND)"] = fmt_num(ap_total)
                df.at[i, "Total price (VND)"] = fmt_num(total_sell)
                df.at[i, "GAP"] = fmt_num(gap)
                df.at[i, "Profit (VND)"] = fmt_num(profit)
                df.at[i, "Profit (%)"] = f"{pct_profit:.1f}%"
                df.at[i, "End user"] = fmt_num(v_end)
                df.at[i, "Buyer"] = fmt_num(v_buy)
                df.at[i, "Import tax"] = fmt_num(v_tax)
                df.at[i, "VAT"] = fmt_num(v_vat)
                df.at[i, "Transportation"] = fmt_num(v_trans)
                df.at[i, "Management fee"] = fmt_num(v_mgmt)
                df.at[i, "Payback"] = fmt_num(v_payback)
            
            st.session_state.current_quote_df = df
            
            # Editor
            edited_quote = st.data_editor(
                st.session_state.current_quote_df,
                column_config={
                    "Images": st.column_config.ImageColumn("Hình ảnh", width="small"),
                    "Buying price (RMB)": st.column_config.TextColumn("Giá Vốn RMB", disabled=True),
                    "Buying price (VND)": st.column_config.TextColumn("Giá Vốn VND", disabled=True),
                    "AP price (VND)": st.column_config.TextColumn("AP Price (VND)", required=True),
                    "Unit price (VND)": st.column_config.TextColumn("Unit Price (VND)", required=True),
                    "Total price (VND)": st.column_config.TextColumn("Thành Tiền Bán", disabled=True),
                    "Profit (VND)": st.column_config.TextColumn("LỢI NHUẬN", disabled=True),
                },
                use_container_width=True,
                height=500,
                num_rows="dynamic",
                column_order=QUOTE_DISPLAY_COLS
            )
            
            if not edited_quote.equals(st.session_state.current_quote_df):
                st.session_state.current_quote_df = edited_quote
                st.rerun()

    st.write(""); st.write(""); st.write(""); st.write("")

    # KHUNG REVIEW
    if 'current_quote_df' in st.session_state and not st.session_state.current_quote_df.empty:
        with st.container(border=True):
            st.header("2. REVIEW LỢI NHUẬN")
            df_review = st.session_state.current_quote_df.copy()
            df_low = df_review[df_review["Profit (%)"].apply(lambda x: to_float(str(x).replace('%','')) < 10)]
            
            if not df_low.empty:
                st.dataframe(df_low[REVIEW_COLS], use_container_width=True, hide_index=True)
                st.markdown(f"<div class='alert-box'>⚠️ CẢNH BÁO: Có {len(df_low)} mặt hàng lợi nhuận dưới 10%!</div>", unsafe_allow_html=True)
            else:
                st.success("✅ Tuyệt vời! Tất cả mặt hàng đều đạt lợi nhuận > 10%.")

        # KHUNG EXPORT
        with st.container(border=True):
            st.header("3. XUẤT FILE BÁO GIÁ")
            col_ex1, col_ex2 = st.columns(2)
            with col_ex1:
                csv = edited_quote.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 Tải CSV (Thô)", csv, "RFQ_Result.csv", "text/csv")
            
            with col_ex2:
                if st.session_state.quote_template:
                    if st.button("📤 EXPORT EXCEL (THEO TEMPLATE AAA)"):
                        try:
                            output = io.BytesIO()
                            wb = load_workbook(io.BytesIO(st.session_state.quote_template.getvalue()))
                            ws = wb.active
                            
                            leadtime_val = get_scalar(edited_quote['Leadtime'].iloc[0]) if not edited_quote.empty else ""
                            ws['H8'] = f"{leadtime_val}"
                            
                            # Export bắt đầu từ dòng 11 (theo yêu cầu A11)
                            start_row = 11 
                            thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
                            
                            for i, r in edited_quote.iterrows():
                                current_row = start_row + i
                                ws.cell(row=current_row, column=1, value=r.get("No"))          
                                ws.cell(row=current_row, column=3, value=r.get("Item code"))   
                                ws.cell(row=current_row, column=4, value=r.get("Item name"))   
                                ws.cell(row=current_row, column=5, value=r.get("Specs"))       
                                ws.cell(row=current_row, column=6, value=to_float(r.get("Q'ty"))) 
                                ws.cell(row=current_row, column=7, value=to_float(r.get("Unit price (VND)"))) 
                                ws.cell(row=current_row, column=8, value=to_float(r.get("Total price (VND)"))) 
                                
                                for c in range(1, 9): ws.cell(row=current_row, column=c).border = thin_border

                            wb.save(output)
                            st.download_button("📥 TẢI FILE BÁO GIÁ ĐÃ XONG", output.getvalue(), "Bao_Gia_Final.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        except Exception as e: st.error(f"Lỗi xuất Excel: {e}")
                else:
                    st.warning("⚠️ Chưa có Template. Upload tại Tab 6.")

            if st.button("💾 Lưu vào Lịch sử"):
                to_save = edited_quote.copy()
                save_data("crm_shared_history", to_save, "history_id")
                st.success("Đã lưu!")

# --- TAB 4: PO ---
with t4:
    suppliers_df = load_data("crm_suppliers")
    customers_df = load_data("crm_customers")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("PO NCC")
        sup = st.selectbox("Supplier", [""] + (suppliers_df['short_name'].tolist() if not suppliers_df.empty else []), key="sel_sup_po")
        po_s = st.text_input("PO NCC No")
        up_s = st.file_uploader("Upload PO NCC", type=["xlsx"], key="up_po_s")
        if up_s:
            df = pd.read_excel(up_s, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                try:
                    recs.append({
                        "item_code": safe_str(r.iloc[1]), 
                        "item_name": safe_str(r.iloc[2]), 
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "price_rmb": fmt_num(to_float(r.iloc[5]))
                    })
                except: pass
            st.session_state.temp_supp = pd.DataFrame(recs)
        
        ed_s = st.data_editor(st.session_state.temp_supp, num_rows="dynamic", use_container_width=True, key="editor_po_supp", hide_index=True)
        if st.button("Save PO NCC"):
            s_data = ed_s.copy()
            s_data['po_number'] = po_s; s_data['supplier'] = sup; s_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_supplier_orders", s_data)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_s, "partner": sup, "status": "Ordered", "order_type": "NCC"}]), unique_cols=['po_no'])
            st.success("Saved")

    with c2:
        st.subheader("PO CUSTOMER")
        cus = st.selectbox("Customer PO", [""] + (customers_df['short_name'].tolist() if not customers_df.empty else []), key="sel_cust_po")
        po_c = st.text_input("PO Cust No")
        up_c = st.file_uploader("Upload PO Cust", type=["xlsx"], key="up_po_c")
        if up_c:
            df = pd.read_excel(up_c, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                try:
                    recs.append({
                        "item_code": safe_str(r.iloc[1]), 
                        "item_name": safe_str(r.iloc[2]), 
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "unit_price": fmt_num(to_float(r.iloc[5]))
                    })
                except: pass
            st.session_state.temp_cust = pd.DataFrame(recs)
            
        ed_c = st.data_editor(st.session_state.temp_cust, num_rows="dynamic", use_container_width=True, key="editor_po_cust", hide_index=True)
        if st.button("Save PO Cust"):
            c_data = ed_c.copy()
            c_data['po_number'] = po_c; c_data['customer'] = cus; c_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_customer_orders", c_data)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_c, "partner": cus, "status": "Waiting", "order_type": "KH"}]), unique_cols=['po_no'])
            st.success("Saved")

# --- TAB 5: TRACKING & PAYMENT ---
with t5:
    tracking_df = load_data("crm_tracking")
    payment_df = load_data("crm_payment")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Tracking")
        if not tracking_df.empty:
            ed_t = st.data_editor(tracking_df, key="editor_tracking_main", height=600, hide_index=True, column_config={"proof_image": st.column_config.ImageColumn("Proof")})
            if st.button("Update Tracking"):
                save_data("crm_tracking", ed_t, unique_cols=['po_no', 'partner'])
                for i, r in ed_t.iterrows():
                    if r['status'] == 'Delivered' and r['order_type'] == 'KH':
                        save_data("crm_payment", pd.DataFrame([{"po_no": r['po_no'], "customer": r['partner'], "status": "Pending"}]), unique_cols=['po_no'])
                st.success("Updated")
            
            pk = st.text_input("Proof for PO")
            prf = st.file_uploader("Proof Img", accept_multiple_files=True, key="up_proof")
            if st.button("Upload Proof") and pk and prf:
                urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"PRF_{pk}_{f.name}") for f in prf]
                if urls: supabase.table("crm_tracking").update({"proof_image": urls[0]}).eq("po_no", pk).execute()
                st.success("Uploaded")
        else:
            st.info("Chưa có dữ liệu Tracking. Hãy tạo PO ở Tab 4 trước.")

    with c2:
        st.subheader("Payment")
        if not payment_df.empty:
            ed_p = st.data_editor(payment_df, key="editor_payment_main", height=600, hide_index=True)
            if st.button("Update Payment"):
                save_data("crm_payment", ed_p, unique_cols=['po_no'])
                st.success("Updated")
        else:
            st.info("Chưa có dữ liệu Payment.")

# --- TAB 6: MASTER DATA ---
with t6:
    if is_admin:
        st.subheader("1. DỮ LIỆU KHÁCH HÀNG & NCC")
        c1, c2 = st.columns(2)
        with c1:
            st.write("Customers")
            up_k = st.file_uploader("Import Cust", type=["xlsx"], key="up_mst_c")
            if up_k and st.button("Import K"):
                df = pd.read_excel(up_k, header=0, dtype=str).fillna("")
                rows = []
                hn = {normalize_header(c): c for c in df.columns}
                for i, r in df.iterrows():
                    d = {}
                    for nk, db in MAP_MASTER.items():
                        if nk in hn: d[db] = safe_str(r[hn[nk]])
                    if d.get('short_name'): rows.append(d)
                save_data("crm_customers", pd.DataFrame(rows), unique_cols=['short_name'])
                st.success("Imported"); st.rerun()
            
            ed_k = st.data_editor(customers_df, num_rows="dynamic", key="editor_master_cust", height=600, hide_index=True)
            if st.button("Save Cust"): save_data("crm_customers", ed_k, unique_cols=['short_name']); st.success("OK")

        with c2:
            st.write("Suppliers")
            up_s = st.file_uploader("Import Supp", type=["xlsx"], key="up_mst_s")
            if up_s and st.button("Import S"):
                df = pd.read_excel(up_s, header=0, dtype=str).fillna("")
                rows = []
                hn = {normalize_header(c): c for c in df.columns}
                for i, r in df.iterrows():
                    d = {}
                    for nk, db in MAP_MASTER.items():
                        if nk in hn: d[db] = safe_str(r[hn[nk]])
                    if d.get('short_name'): rows.append(d)
                save_data("crm_suppliers", pd.DataFrame(rows), unique_cols=['short_name'])
                st.success("Imported"); st.rerun()
            
            ed_s = st.data_editor(suppliers_df, num_rows="dynamic", key="editor_master_supp", height=600, hide_index=True)
            if st.button("Save Supp"): save_data("crm_suppliers", ed_s, unique_cols=['short_name']); st.success("OK")
        
        st.divider()
        st.subheader("2. TEMPLATE BÁO GIÁ (CHO TAB 3)")
        up_template = st.file_uploader("Upload Template Báo Giá (.xlsx)", type=["xlsx"], key="up_template")
        if up_template:
            st.session_state.quote_template = up_template
            st.success("Đã tải Template lên bộ nhớ tạm! Bây giờ bạn có thể qua Tab 3 để Export.")
            
    else: st.warning("Admin Only")
