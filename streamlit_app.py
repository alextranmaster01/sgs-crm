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
    st.error("⚠️ LỖI: Thiếu thư viện. Vui lòng chạy lệnh: pip install pandas openpyxl supabase google-api-python-client google-auth-oauthlib")
    st.stop()

# =============================================================================
# 1. CẤU HÌNH & VERSION (KHỚP V4800)
# =============================================================================
APP_VERSION = "V4814 - HEAVY DUTY (FULL LOGIC V4800)"
RELEASE_NOTE = """
- **Core Logic:** Logic tính toán Profit, Cost, Gap giống hệt file V4800 gốc.
- **Mapping:** Tự động nhận diện cột trong Excel (bất kể xuống dòng hay viết hoa/thường).
- **Overwrite:** Tự động ghi đè dữ liệu và ảnh nếu trùng Mã hàng/Khách hàng.
"""

st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS GIAO DIỆN (GIỮ NGUYÊN STYLE V4800) ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 24px !important; font-weight: 800 !important; padding: 10px 20px !important; }
    h1 { font-size: 32px !important; font-weight: bold; }
    h2 { font-size: 26px !important; font-weight: bold; }
    h3 { font-size: 22px !important; font-weight: bold; }
    .card-3d { border-radius: 15px; padding: 25px; color: white; text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.19), 0 6px 6px rgba(0,0,0,0.23); margin-bottom: 20px; font-family: 'Arial', sans-serif; }
    .card-3d:hover { transform: translateY(-5px); box-shadow: 0 14px 28px rgba(0,0,0,0.25), 0 10px 10px rgba(0,0,0,0.22); }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    .bg-recv { background: linear-gradient(135deg, #43e97b, #38f9d7); }
    .bg-del { background: linear-gradient(135deg, #4facfe, #00f2fe); }
    .bg-pend { background: linear-gradient(135deg, #f093fb, #f5576c); }
    </style>""", unsafe_allow_html=True)

# --- KẾT NỐI SERVER (SUPABASE + DRIVE) ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi Cấu hình Secrets: {e}")
    st.stop()

# --- HÀM XỬ LÝ GOOGLE DRIVE (FULL OVERWRITE LOGIC) ---
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

def upload_to_drive(file_obj, sub_folder, file_name):
    """
    Logic: Tìm file -> Nếu có thì GHI ĐÈ nội dung (giữ ID) -> Nếu không thì tạo mới.
    """
    srv = get_drive_service()
    if not srv: return ""
    try:
        # 1. Tìm hoặc tạo Folder con
        q_f = f"'{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if folders:
            folder_id = folders[0]['id']
        else:
            folder_id = srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
            # Cấp quyền đọc
            srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        # 2. Kiểm tra file trùng
        q_file = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        existing = srv.files().list(q=q_file, fields='files(id)').execute().get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        
        file_id = ""
        if existing:
            # GHI ĐÈ (UPDATE)
            file_id = existing[0]['id']
            srv.files().update(fileId=file_id, media_body=media, fields='id').execute()
        else:
            # TẠO MỚI (INSERT)
            file_id = srv.files().create(body={'name': file_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()['id']
            
        # Đảm bảo quyền truy cập
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    except Exception as e: 
        print(f"Drive Upload Error: {e}")
        return ""

# --- HÀM XỬ LÝ DỮ LIỆU CỐT LÕI (BÊ TỪ V4800) ---
def safe_str(val): return str(val).strip() if val is not None and str(val).lower() not in ['nan', 'none', 'null', 'nat', ''] else ""
def safe_filename(s): return re.sub(r'[^\w\-_]', '_', unicodedata.normalize('NFKD', safe_str(s)).encode('ascii', 'ignore').decode('utf-8')).strip('_')
def to_float(val):
    if not val: return 0.0
    # Xử lý các ký tự tiền tệ và dấu phẩy từ file Excel
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").replace("\n","")
    try: return max([float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", s)])
    except: return 0.0
def fmt_num(x): 
    try: return "{:,.0f}".format(float(x)) 
    except: return "0"
def clean_lookup_key(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
def parse_formula(formula, buying, ap):
    # Hàm xử lý công thức giá từ V4800
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying)).replace("BUY", str(buying)).replace("AP PRICE", str(ap)).replace("AP", str(ap))
    try: return float(eval(re.sub(r'[^0-9.+\-*/()]', '', expr)))
    except: return 0.0

# --- SMART MAPPING (QUAN TRỌNG: ĐỂ KHỚP FILE EXCEL) ---
def normalize_header(h):
    # Biến "Buying price\n(RMB)" thành "buyingpricermb"
    return re.sub(r'[^a-zA-Z0-9]', '', str(h).lower())

# Map này khớp chính xác với file BUYING PRICE-ALL.xlsx của bạn
MAP_PURCHASE = {
    "itemcode": "item_code", 
    "itemname": "item_name", 
    "specs": "specs", 
    "qty": "qty",
    "buyingpricermb": "buying_price_rmb", 
    "totalbuyingpricermb": "total_buying_price_rmb",
    "exchangerate": "exchange_rate", 
    "buyingpricevnd": "buying_price_vnd",
    "totalbuyingpricevnd": "total_buying_price_vnd", 
    "leadtime": "leadtime",
    "supplier": "supplier_name", 
    "type": "type", # Khớp cột Type
    "nuoc": "nuoc"  # Khớp cột N/U/O/C
}

# Map này khớp với CUSTOMER LIST.xlsx và SUPPLIER LIST.xlsx
MAP_MASTER = {
    "shortname": "short_name", 
    "engname": "eng_name", 
    "vnname": "vn_name",
    "address1": "address_1", 
    "address2": "address_2", 
    "contactperson": "contact_person",
    "director": "director", 
    "phone": "phone", 
    "fax": "fax", 
    "taxcode": "tax_code",
    "destination": "destination", 
    "paymentterm": "payment_term"
}

# --- XỬ LÝ DATABASE (WHITELIST & UPSERT) ---
@st.cache_data(ttl=5) # Cache 5s cho multi-user
def load_data(table):
    try:
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        # Thêm cột 'no' giả lập để hiển thị STT đẹp trên bảng
        if not df.empty and 'no' not in df.columns: 
            df.insert(0, 'no', range(1, len(df)+1))
        return df
    except: return pd.DataFrame()

def save_data(table, df, unique_key=None):
    if df.empty: return
    try:
        # Whitelist: Danh sách cột chuẩn trong SQL (để lọc bỏ cột rác từ Excel)
        VALID_COLS = {
            "crm_purchases": list(MAP_PURCHASE.values()) + ["image_path", "_clean_code", "_clean_name", "_clean_specs"],
            "crm_customers": list(MAP_MASTER.values()),
            "crm_suppliers": list(MAP_MASTER.values()),
            "db_supplier_orders": ["po_number", "order_date", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path"],
            "db_customer_orders": ["po_number", "order_date", "customer", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "base_buying_vnd", "full_cost_total", "pdf_path"],
            "crm_tracking": ["po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"],
            "crm_payment": ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"],
            "crm_shared_history": ["history_id", "date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime", "pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
        }
        
        valid = VALID_COLS.get(table, df.columns.tolist())
        recs = df.to_dict(orient='records')
        clean_recs = []
        for r in recs:
            # Ép kiểu string để tránh lỗi
            clean = {k: str(v) if v is not None and str(v)!='nan' else None for k,v in r.items() if k in valid}
            if clean: clean_recs.append(clean)
        
        # Upsert: Ghi đè nếu trùng Key
        if unique_key: supabase.table(table).upsert(clean_recs, on_conflict=unique_key).execute()
        else: supabase.table(table).upsert(clean_recs).execute()
        
        st.cache_data.clear() # Xóa cache ngay lập tức để user khác thấy thay đổi
    except Exception as e: st.error(f"❌ Lỗi lưu dữ liệu ({table}): {e}")

# --- INIT STATE ---
if 'init' not in st.session_state:
    st.session_state.init = True
    st.session_state.quote_df = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "buying_price_vnd", "buying_price_rmb", "exchange_rate", "ap_price", "unit_price", "total_price_vnd", "supplier_name", "image_path", "leadtime", "transportation"])
    st.session_state.temp_supp = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "supplier"])
    st.session_state.temp_cust = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "unit_price", "total_price", "customer"])
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"

# --- GIAO DIỆN CHÍNH ---
st.title("HỆ THỐNG CRM QUẢN LÝ (FULL CLOUD)")
is_admin = (st.sidebar.text_input("Mật khẩu Admin", type="password") == "admin")

t1, t2, t3, t4, t5, t6 = st.tabs([
    "📊 DASHBOARD TỔNG QUAN", 
    "🏭 KHO HÀNG (PURCHASES)", 
    "💰 BÁO GIÁ (QUOTES)", 
    "📑 QUẢN LÝ ĐƠN HÀNG (PO)", 
    "🚚 TRACKING & THANH TOÁN", 
    "📂 DỮ LIỆU NỀN (MASTER)"
])

# =============================================================================
# TAB 1: DASHBOARD (LOGIC TÍNH LỢI NHUẬN CỦA V4800)
# =============================================================================
with t1:
    with st.spinner("Đang tải dữ liệu từ Cloud..."):
        if not get_drive_service(): st.stop()
        # Load Data
        db_cust_orders = load_data("db_customer_orders")
        db_supp_orders = load_data("db_supplier_orders")
        shared_hist = load_data("crm_shared_history")
        tracking_df = load_data("crm_tracking")
        
        # 1. Doanh thu (Tổng PO Khách)
        rev = db_cust_orders['total_price'].apply(to_float).sum() if not db_cust_orders.empty else 0
        
        # 2. Chi phí NCC (Tổng PO NCC)
        cost_ncc = db_supp_orders['total_vnd'].apply(to_float).sum() if not db_supp_orders.empty else 0
        
        # 3. Chi phí Phụ (OPS) - Logic chuẩn V4800
        # Formula: (Gap * 60%) + EndUser + Buyer + Tax + VAT + (Trans * Qty) + Mgmt
        other_cost = 0
        if not shared_hist.empty:
            for _, r in shared_hist.iterrows():
                try:
                    gap = to_float(r.get('gap', 0))
                    oc = (gap * 0.6) + \
                         to_float(r.get('end_user_val',0)) + \
                         to_float(r.get('buyer_val',0)) + \
                         to_float(r.get('import_tax_val',0)) + \
                         to_float(r.get('vat_val',0)) + \
                         to_float(r.get('mgmt_fee',0)) + \
                         (to_float(r.get('transportation',0)) * to_float(r.get('qty',0)))
                    other_cost += oc
                except: pass
        
        # 4. Lợi nhuận
        profit = rev - (cost_ncc + other_cost)
        
        # Hiển thị thẻ 3D
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ (NCC+OPS)</h3><h1>{fmt_num(cost_ncc + other_cost)}</h1></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN RÒNG</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)
        
        st.divider()
        c4, c5, c6, c7 = st.columns(4)
        po_ncc_count = len(tracking_df[tracking_df['order_type']=='NCC']) if not tracking_df.empty else 0
        po_kh_count = len(db_cust_orders['po_number'].unique()) if not db_cust_orders.empty else 0
        po_del = len(tracking_df[(tracking_df['order_type']=='KH') & (tracking_df['status']=='Đã giao hàng')]) if not tracking_df.empty else 0
        
        with c4: st.markdown(f"<div class='card-3d bg-ncc'><div>ĐƠN ĐẶT NCC</div><h3>{po_ncc_count}</h3></div>", unsafe_allow_html=True)
        with c5: st.markdown(f"<div class='card-3d bg-recv'><div>ĐƠN KHÁCH NHẬN</div><h3>{po_kh_count}</h3></div>", unsafe_allow_html=True)
        with c6: st.markdown(f"<div class='card-3d bg-del'><div>ĐÃ GIAO HÀNG</div><h3>{po_del}</h3></div>", unsafe_allow_html=True)
        with c7: st.markdown(f"<div class='card-3d bg-pend'><div>CHỜ GIAO</div><h3>{po_kh_count - po_del}</h3></div>", unsafe_allow_html=True)

# =============================================================================
# TAB 2: PURCHASES (IMPORT EXCEL BUYING PRICE)
# =============================================================================
with t2:
    purchases_df = load_data("crm_purchases")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.info("Import file BUYING PRICE-ALL.xlsx")
        up_file = st.file_uploader("Chọn file Excel", type=["xlsx"], key="up_pur")
        if up_file and st.button("🚀 IMPORT VÀO DB"):
            try:
                df = pd.read_excel(up_file, header=0, dtype=str).fillna("")
                
                # Load ảnh từ file Excel
                img_map = {}
                try:
                    wb = load_workbook(up_file, data_only=False); ws = wb.active
                    for img in getattr(ws, '_images', []):
                        img_map[img.anchor._from.row + 1] = img
                except: pass
                
                rows = []
                bar = st.progress(0)
                # Map tên cột (Normalized)
                headers_norm = {normalize_header(c): c for c in df.columns}
                
                for i, r in df.iterrows():
                    d = {}
                    # Smart Map: Tự động tìm cột khớp
                    for norm_key, db_col in MAP_PURCHASE.items():
                        if norm_key in headers_norm:
                            d[db_col] = safe_str(r[headers_norm[norm_key]])
                    
                    if not d.get('item_code'): continue # Bỏ qua dòng trống
                    
                    # Xử lý ảnh: GHI ĐÈ FILE TRÊN DRIVE
                    img_url = ""
                    if (i+2) in img_map:
                        try:
                            buf = io.BytesIO(img_map[i+2]._data())
                            fname = f"IMG_{safe_filename(d['item_code'])}.png"
                            img_url = upload_to_drive(buf, "CRM_PURCHASE_IMAGES", fname)
                        except: pass
                    if img_url: d['image_path'] = img_url
                    
                    # Tạo dữ liệu sạch để tìm kiếm
                    d['_clean_code'] = clean_lookup_key(d.get('item_code'))
                    d['_clean_name'] = clean_lookup_key(d.get('item_name'))
                    d['_clean_specs'] = clean_lookup_key(d.get('specs'))
                    
                    # Format số
                    for col in ['qty','buying_price_rmb','total_buying_price_rmb','exchange_rate','buying_price_vnd','total_buying_price_vnd']:
                        d[col] = fmt_num(to_float(d.get(col,0)))
                        
                    rows.append(d)
                    bar.progress((i+1)/len(df))
                
                # GHI ĐÈ VÀO DB (Dựa trên item_code)
                save_data("crm_purchases", pd.DataFrame(rows), unique_key="item_code")
                st.success(f"✅ Đã xử lý {len(rows)} dòng. Dữ liệu đã được GHI ĐÈ lên DB!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")
            
        st.write("---")
        st.write("Cập nhật ảnh lẻ")
        up_img = st.file_uploader("File ảnh", type=["png","jpg"], key="up_img_single")
        code = st.text_input("Mã hàng (Item Code)")
        if st.button("Upload Ảnh") and up_img and code:
            url = upload_to_drive(up_img, "CRM_PURCHASE_IMAGES", f"IMG_{safe_filename(code)}.png")
            supabase.table("crm_purchases").update({"image_path": url}).eq("item_code", code).execute()
            st.success("Xong!"); st.rerun()

    with c2:
        search = st.text_input("🔍 Tìm kiếm (Mã/Tên/Thông số)", key="search_pur")
        view = purchases_df.copy()
        if search:
            mask = view.apply(lambda x: search.lower() in str(x['item_code']).lower() or search.lower() in str(x['item_name']).lower(), axis=1)
            view = view[mask]
        st.dataframe(view, column_config={"image_path": st.column_config.ImageColumn("Ảnh")}, use_container_width=True, hide_index=True)

# =============================================================================
# TAB 3: BÁO GIÁ (LOGIC TÍNH GIÁ CỦA V4800)
# =============================================================================
with t3:
    customers_df = load_data("crm_customers")
    c1, c2 = st.columns([3, 1])
    with c1:
        cust = st.selectbox("Khách hàng", [""] + (customers_df['short_name'].tolist() if not customers_df.empty else []), key="sel_cust_q")
        ref = st.text_input("Mã Báo Giá (Quote Ref)", key="txt_ref_q")
    with c2:
        if st.button("LÀM MỚI (RESET)"):
            st.session_state.quote_df = pd.DataFrame(columns=st.session_state.quote_df.columns)
            st.rerun()
            
    cols = st.columns(7)
    pcts = {}
    # Tham số chi phí (Giống V4800)
    for i, k in enumerate(["end","buy","tax","vat","pay","mgmt","trans"]):
        pcts[k] = cols[i].text_input(k.upper(), st.session_state[f"pct_{k}"])
        st.session_state[f"pct_{k}"] = pcts[k]
        
    up_rfq = st.file_uploader("Import RFQ (Excel)", type=["xlsx"], key="up_rfq")
    if up_rfq and st.button("Load RFQ"):
        try:
            # Tạo Map tra cứu nhanh
            pmap = {}
            if not purchases_df.empty:
                for _, r in purchases_df.iterrows():
                    pmap[r['_clean_code']] = r
                    pmap[r['_clean_name']] = r
            
            rfq = pd.read_excel(up_rfq, header=None, dtype=str).fillna("")
            new_rows = []
            # Duyệt file RFQ
            for i, r in rfq.iloc[1:].iterrows():
                c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2])
                if not c_raw and not n_raw: continue
                # Tìm trong DB
                target = pmap.get(clean_lookup_key(c_raw)) or pmap.get(clean_lookup_key(n_raw))
                item = {
                    "item_code": c_raw, "item_name": n_raw, "specs": safe_str(r.iloc[3]), 
                    "qty": fmt_num(to_float(r.iloc[4])), "buying_price_vnd": "0", "buying_price_rmb": "0", "exchange_rate": "0",
                    "unit_price": "0", "ap_price": "0", "transportation": "0", "supplier_name": "", "image_path": "", "leadtime": ""
                }
                if target is not None:
                    item.update({
                        "buying_price_vnd": target["buying_price_vnd"], "buying_price_rmb": target["buying_price_rmb"],
                        "exchange_rate": target["exchange_rate"], "supplier_name": target["supplier_name"],
                        "image_path": target["image_path"], "leadtime": target["leadtime"]
                    })
                new_rows.append(item)
            st.session_state.quote_df = pd.DataFrame(new_rows)
            st.rerun()
        except Exception as e: st.error(f"Lỗi RFQ: {e}")

    # Công thức hàng loạt
    f1, f2, f3, f4 = st.columns(4)
    ap_f = f1.text_input("AP Formula"); unit_f = f3.text_input("Unit Formula")
    if f2.button("Apply AP"):
        for i, r in st.session_state.quote_df.iterrows():
            st.session_state.quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_f, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
        st.rerun()
    if f4.button("Apply Unit"):
        for i, r in st.session_state.quote_df.iterrows():
            st.session_state.quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_f, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
        st.rerun()

    # Bảng chỉnh sửa
    edited = st.data_editor(st.session_state.quote_df, num_rows="dynamic", use_container_width=True, column_config={"image_path": st.column_config.ImageColumn()}, key="quote_editor_main")
    
    # --- LOGIC TÍNH TOÁN (V4800) ---
    final = edited.copy()
    for i, r in final.iterrows():
        q = to_float(r.get('qty',0)); buy = to_float(r.get('buying_price_vnd',0))
        unit = to_float(r.get('unit_price',0)); ap = to_float(r.get('ap_price',0)); trans = to_float(pcts['trans'])
        
        t_buy = q * buy; t_sell = q * unit; ap_tot = q * ap; gap = t_sell - ap_tot
        
        v_end = to_float(pcts['end'])/100 * ap_tot
        v_buy = to_float(pcts['buy'])/100 * t_sell
        v_tax = to_float(pcts['tax'])/100 * t_buy
        v_vat = to_float(pcts['vat'])/100 * t_sell
        v_pay = to_float(pcts['pay'])/100 * gap
        v_mgmt = to_float(pcts['mgmt'])/100 * t_sell
        
        # COST FORMULA: Gap*0.6 + ...
        ops = (gap * 0.6) + v_end + v_buy + v_tax + v_vat + (trans * q) + v_mgmt
        # PROFIT FORMULA
        prof = t_sell - (t_buy + ops) + v_pay
        
        final.at[i, "total_price_vnd"] = fmt_num(t_sell); final.at[i, "total_buying_price_vnd"] = fmt_num(t_buy)
        final.at[i, "gap"] = fmt_num(gap); final.at[i, "profit_vnd"] = fmt_num(prof)
        final.at[i, "profit_pct"] = f"{(prof/t_sell*100):.1f}%" if t_sell else "0%"
        final.at[i, "transportation"] = fmt_num(trans)
        final.at[i, "end_user_val"] = fmt_num(v_end); final.at[i, "buyer_val"] = fmt_num(v_buy)
        final.at[i, "import_tax_val"] = fmt_num(v_tax); final.at[i, "vat_val"] = fmt_num(v_vat)
        final.at[i, "payback_val"] = fmt_num(v_pay); final.at[i, "mgmt_fee"] = fmt_num(v_mgmt)

    if not final.equals(st.session_state.quote_df):
        st.session_state.quote_df = final; st.rerun()

    if st.button("💾 LƯU LỊCH SỬ BÁO GIÁ"):
        if not cust or not ref: st.error("Thiếu Tên khách hoặc Mã Báo giá"); st.stop()
        save = final.copy()
        save['history_id'] = f"{ref}_{int(time.time())}"
        save['quote_no'] = ref; save['customer'] = cust; save['date'] = datetime.now().strftime("%d/%m/%Y")
        for k, v in pcts.items(): save[f"pct_{k}"] = v
        save_data("crm_shared_history", save)
        st.success("Đã lưu!"); st.rerun()

# =============================================================================
# TAB 4: PO MANAGER
# =============================================================================
with t4:
    suppliers_df = load_data("crm_suppliers")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("PO NHÀ CUNG CẤP (NCC)")
        sup = st.selectbox("NCC", [""] + (suppliers_df['short_name'].tolist() if not suppliers_df.empty else []), key="sel_sup_po")
        po_s = st.text_input("Số PO NCC")
        up_s = st.file_uploader("Upload PO NCC", type=["xlsx"], key="up_po_s")
        if up_s:
            df = pd.read_excel(up_s, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "price_rmb": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_supp = pd.DataFrame(recs)
        
        ed_s = st.data_editor(st.session_state.temp_supp, num_rows="dynamic", use_container_width=True, key="editor_po_supp")
        if st.button("Lưu PO NCC"):
            s_data = ed_s.copy()
            s_data['po_number'] = po_s; s_data['supplier'] = sup; s_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_supplier_orders", s_data)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_s, "partner": sup, "status": "Ordered", "order_type": "NCC"}]))
            st.success("Đã lưu")

    with c2:
        st.subheader("PO KHÁCH HÀNG")
        cus = st.selectbox("Khách", [""] + (customers_df['short_name'].tolist() if not customers_df.empty else []), key="sel_cust_po")
        po_c = st.text_input("Số PO Khách")
        up_c = st.file_uploader("Upload PO Khách", type=["xlsx"], key="up_po_c")
        if up_c:
            df = pd.read_excel(up_c, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "unit_price": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_cust = pd.DataFrame(recs)
            
        ed_c = st.data_editor(st.session_state.temp_cust, num_rows="dynamic", use_container_width=True, key="editor_po_cust")
        if st.button("Lưu PO Khách"):
            c_data = ed_c.copy()
            c_data['po_number'] = po_c; c_data['customer'] = cus; c_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_customer_orders", c_data)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_c, "partner": cus, "status": "Waiting", "order_type": "KH"}]))
            st.success("Đã lưu")

# =============================================================================
# TAB 5: TRACKING & PAYMENT
# =============================================================================
with t5:
    tracking_df = load_data("crm_tracking")
    payment_df = load_data("crm_payment")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Theo Dõi Hàng (Tracking)")
        if not tracking_df.empty:
            ed_t = st.data_editor(tracking_df, key="editor_tracking_main")
            if st.button("Cập nhật Tracking"):
                save_data("crm_tracking", ed_t, unique_key="id")
                # Auto chuyển sang Payment nếu đã giao
                for i, r in ed_t.iterrows():
                    if r['status'] == 'Delivered' and r['order_type'] == 'KH':
                        save_data("crm_payment", pd.DataFrame([{"po_no": r['po_no'], "customer": r['partner'], "status": "Pending"}]))
                st.success("Đã cập nhật")
            
            pk = st.text_input("Nhập Số PO để Up Proof")
            prf = st.file_uploader("Ảnh bằng chứng", accept_multiple_files=True, key="up_proof")
            if st.button("Up Proof") and pk and prf:
                urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"PRF_{pk}_{f.name}") for f in prf]
                supabase.table("crm_tracking").update({"proof_image": json.dumps(urls)}).eq("po_no", pk).execute()
                st.success("Đã Upload!")

    with c2:
        st.subheader("Thanh Toán (Payment)")
        if not payment_df.empty:
            ed_p = st.data_editor(payment_df, key="editor_payment_main")
            if st.button("Cập nhật Thanh Toán"):
                save_data("crm_payment", ed_p, unique_key="id")
                st.success("Đã cập nhật")

# =============================================================================
# TAB 6: MASTER DATA
# =============================================================================
with t6:
    if is_admin:
        c1, c2 = st.columns(2)
        with c1:
            st.write("Khách Hàng (Customer)")
            up_k = st.file_uploader("Import Khách", type=["xlsx"], key="up_mst_c")
            if up_k and st.button("Import"):
                df = pd.read_excel(up_k, header=0, dtype=str).fillna("")
                rows = []
                hn = {normalize_header(c): c for c in df.columns}
                for i, r in df.iterrows():
                    d = {}
                    for nk, db in MAP_MASTER.items():
                        if nk in hn: d[db] = safe_str(r[hn[nk]])
                    if d.get('short_name'): rows.append(d)
                save_data("crm_customers", pd.DataFrame(rows), unique_key="short_name")
                st.success("Xong!"); st.rerun()
            
            # Key đã được sửa để không trùng
            ed_k = st.data_editor(customers_df, num_rows="dynamic", key="editor_master_cust")
            if st.button("Lưu Khách"): save_data("crm_customers", ed_k, unique_key="short_name"); st.success("OK")

        with c2:
            st.write("Nhà Cung Cấp (Supplier)")
            up_s = st.file_uploader("Import NCC", type=["xlsx"], key="up_mst_s")
            if up_s and st.button("Import"):
                df = pd.read_excel(up_s, header=0, dtype=str).fillna("")
                rows = []
                hn = {normalize_header(c): c for c in df.columns}
                for i, r in df.iterrows():
                    d = {}
                    for nk, db in MAP_MASTER.items():
                        if nk in hn: d[db] = safe_str(r[hn[nk]])
                    if d.get('short_name'): rows.append(d)
                save_data("crm_suppliers", pd.DataFrame(rows), unique_key="short_name")
                st.success("Xong!"); st.rerun()
            
            # Key đã được sửa để không trùng
            ed_s = st.data_editor(suppliers_df, num_rows="dynamic", key="editor_master_supp")
            if st.button("Lưu NCC"): save_data("crm_suppliers", ed_s, unique_key="short_name"); st.success("OK")
    else: st.warning("Cần quyền Admin để sửa Master Data.")
