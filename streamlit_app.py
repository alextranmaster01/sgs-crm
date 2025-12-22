import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import io
import time
import json
import mimetypes
import numpy as np

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO
# =============================================================================
APP_VERSION = "V6006 - STRICT MAPPING & FOLDER STRUCTURE"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="💎")

# CSS UI
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 18px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 10px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    [data-testid="stDataFrame"] > div { max-height: 750px; }
    .highlight-low { background-color: #ffcccc !important; color: red !important; font-weight: bold; }
    div.stButton > button { width: 100%; border-radius: 5px; font-weight: bold; background-color: #f0f2f6; }
    </style>""", unsafe_allow_html=True)

# LIBRARIES & CONNECTIONS
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Border, Side, Alignment, Font
except ImportError:
    st.error("⚠️ Thiếu thư viện. Vui lòng chạy lệnh: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl")
    st.stop()

# CONNECT SERVER
try:
    if "supabase" not in st.secrets or "google_oauth" not in st.secrets:
        st.error("⚠️ Chưa cấu hình secrets.toml. Vui lòng kiểm tra lại file secrets.")
        st.stop()

    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi Config: {e}"); st.stop()

# =============================================================================
# 2. HÀM HỖ TRỢ (UTILS)
# =============================================================================

def get_drive_service():
    try:
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], client_secret=OAUTH_INFO["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

# Hàm tạo folder đệ quy (Recursive) để đảm bảo cấu trúc folder
def get_or_create_folder_hierarchy(srv, path_list, parent_id):
    current_parent_id = parent_id
    for folder_name in path_list:
        # Tìm folder trong parent hiện tại
        q = f"'{current_parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = srv.files().list(q=q, fields="files(id)").execute().get('files', [])
        
        if results:
            current_parent_id = results[0]['id']
        else:
            # Tạo mới nếu chưa có
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [current_parent_id]
            }
            folder = srv.files().create(body=file_metadata, fields='id').execute()
            current_parent_id = folder.get('id')
            # Set public reader
            try: srv.permissions().create(fileId=current_parent_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            except: pass
            
    return current_parent_id

def upload_to_drive_structured(file_obj, path_list, file_name):
    """Upload file vào cấu trúc thư mục định sẵn: ROOT/Năm/NCC/Tháng..."""
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, path_list, ROOT_FOLDER_ID)
        
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        
        # Check exists
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
            
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        # Return Folder Link and File ID
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        return folder_link, file_id
    except Exception as e: 
        st.error(f"Lỗi upload Drive: {e}")
        return "", ""

def upload_to_drive_simple(file_obj, sub_folder, file_name):
    """Dùng cho ảnh sản phẩm"""
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, [sub_folder], ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        
        if exists:
            # Logic ghi đè ảnh cũ nếu trùng tên
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200", file_id
    except: return "", ""

def download_from_drive(file_id):
    srv = get_drive_service()
    if not srv: return None
    try:
        request = srv.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        return fh
    except: return None

def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def to_float(val):
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").upper()
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(nums[0]) if nums else 0.0
    except: return 0.0

def fmt_num(x): 
    try:
        return "{:,.0f}".format(float(x)) if x else "0"
    except:
        return "0"

def clean_key(s): return safe_str(s).lower()

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime):
            dt_order = order_date_str
        else:
            try: dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
            except: dt_order = datetime.now()
            
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

def load_data(table, order_by="id", ascending=True):
    try:
        query = supabase.table(table).select("*")
        if table == "crm_purchases":
            # Giữ nguyên thứ tự import (dựa vào row_order)
            query = query.order("row_order", desc=False) # Ascending=True theo row_order
        else:
            query = query.order(order_by, desc=not ascending)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if table != "crm_tracking" and not df.empty and 'id' in df.columns: 
            df = df.drop(columns=['id'])
        return df
    except: return pd.DataFrame()

# =============================================================================
# 3. LOGIC TÍNH TOÁN CORE (GIỮ NGUYÊN)
# =============================================================================
def recalculate_quote_logic(df, params):
    cols_to_num = ["Q'ty", "Buying price(VND)", "Buying price(RMB)", "AP price(VND)", "Unit price(VND)"]
    for c in cols_to_num:
        if c in df.columns: df[c] = df[c].apply(to_float)
    
    pend = params['end']/100; pbuy = params['buy']/100
    ptax = params['tax']/100; pvat = params['vat']/100
    ppay = params['pay']/100; pmgmt = params['mgmt']/100
    val_trans = params['trans']

    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]

    df["End user(%)"] = df["AP total price(VND)"] * pend
    df["Buyer(%)"] = df["Total price(VND)"] * pbuy
    df["Import tax(%)"] = df["Total buying price(VND)"] * ptax
    df["VAT"] = df["Total price(VND)"] * pvat
    df["Management fee(%)"] = df["Total price(VND)"] * pmgmt
    df["Payback(%)"] = df["GAP"] * ppay
    df["Transportation"] = val_trans * df["Q'ty"]

    gap_positive = df["GAP"].apply(lambda x: x * 0.6 if x > 0 else 0)
    cost_ops = gap_positive + df["End user(%)"] + df["Buyer(%)"] + df["Import tax(%)"] + df["VAT"] + df["Management fee(%)"] + df["Transportation"]
    
    df["Profit(VND)"] = df["Total price(VND)"] - df["Total buying price(VND)"] - cost_ops + df["Payback(%)"]
    df["Profit_Pct_Raw"] = df.apply(lambda row: (row["Profit(VND)"] / row["Total price(VND)"] * 100) if row["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    df["Cảnh báo"] = df["Profit_Pct_Raw"].apply(lambda x: "⚠️ LOW" if x < 10 else "✅ OK")

    cols_format = ["AP total price(VND)", "Total price(VND)", "GAP", "End user(%)", "Buyer(%)", 
                   "Import tax(%)", "VAT", "Management fee(%)", "Transportation", "Payback(%)", "Profit(VND)",
                   "Total buying price(VND)", "Total buying price(rmb)"]
    for c in cols_format:
        if c in df.columns: df[c] = df[c].apply(fmt_num)
    
    df["Buying price(VND)"] = df["Buying price(VND)"].apply(fmt_num)
    df["Buying price(RMB)"] = df["Buying price(RMB)"].apply(fmt_num)
    df["AP price(VND)"] = df["AP price(VND)"].apply(fmt_num)
    df["Unit price(VND)"] = df["Unit price(VND)"].apply(fmt_num)
    return df

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper().replace(",", ".").replace("%", "/100").replace("X", "*")
    if s.startswith("="): s = s[1:]
    s = s.replace("BUYING PRICE", str(buying_price)).replace("BUY", str(buying_price))
    s = s.replace("AP PRICE", str(ap_price)).replace("AP", str(ap_price))
    s = re.sub(r'[^0-9.+\-*/()]', '', s)
    try: return float(eval(s))
    except: return 0.0

# =============================================================================
# 4. GIAO DIỆN CHÍNH
# =============================================================================
t1, t2, t3, t4, t5, t6 = st.tabs(["📊 DASHBOARD", "📦 KHO HÀNG", "💰 BÁO GIÁ", "📑 QUẢN LÝ PO", "🚚 TRACKING", "⚙️ MASTER DATA"])

# --- TAB 1: DASHBOARD ---
with t1:
    if st.button("🔄 REFRESH DATA"): st.cache_data.clear(); st.rerun()
    db_cust = load_data("db_customer_orders")
    db_supp = load_data("db_supplier_orders")
    rev = db_cust['total_price'].apply(to_float).sum() if not db_cust.empty else 0
    cost = db_supp['total_vnd'].apply(to_float).sum() if not db_supp.empty else 0
    profit = rev - cost 
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ NCC</h3><h1>{fmt_num(cost)}</h1></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN GỘP</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: KHO HÀNG (Mapping cột A-O) ---
with t2:
    st.subheader("QUẢN LÝ KHO HÀNG (Excel Online)")
    
    # CHỈNH SỬA: Tăng tỷ lệ cột View để giảm kích thước cột Import (1:4)
    c_imp, c_view = st.columns([1, 4])
    
    with c_imp:
        st.markdown("**📥 Import Kho Hàng**")
        st.caption("Excel cột A->O") # Rút gọn text
        st.info("No, Code, Name, Specs, Qty, BuyRMB, TotalRMB, Rate, BuyVND, TotalVND, Leadtime, Supplier, Images, Type, N/U/O/C")
        
        with st.expander("🛠️ Reset DB"):
            adm_pass = st.text_input("Pass", type="password", key="adm_inv")
            if st.button("⚠️ XÓA SẠCH"):
                if adm_pass == "admin":
                    supabase.table("crm_purchases").delete().neq("id", 0).execute()
                    st.success("Deleted!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass!")
        
        up_file = st.file_uploader("Upload Excel", type=["xlsx"], key="inv_up")
            
        if up_file and st.button("🚀 Import"):
            try:
                # 1. Xử lý Ảnh
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                img_map = {}
                
                # Logic mới: Tên ảnh theo Specs & Ghi đè
                for image in getattr(ws, '_images', []):
                    row = image.anchor._from.row + 1
                    buf = io.BytesIO(image._data())
                    
                    # Lấy giá trị Specs từ cột D (Cột 4) của dòng tương ứng
                    cell_specs = ws.cell(row=row, column=4).value # Cột D là cột 4
                    specs_val = safe_str(cell_specs)
                    
                    # Sanitize tên file từ specs (bỏ ký tự đặc biệt)
                    safe_name = re.sub(r'[\\/*?:"<>|]', "", specs_val).strip()
                    if not safe_name: safe_name = f"NO_SPECS_R{row}"
                    
                    # Tên file ảnh dựa trên Specs
                    fname = f"{safe_name}.png"
                    
                    # Upload (hàm simple đã có sẵn logic check exists -> update/overwrite)
                    link, _ = upload_to_drive_simple(buf, "CRM_PRODUCT_IMAGES", fname)
                    img_map[row] = link
                
                # 2. Đọc Data (Không dùng Header, đọc theo Index cột)
                # Skip rows=1 để bỏ dòng tiêu đề, đọc dữ liệu raw
                df = pd.read_excel(up_file, header=None, skiprows=1, dtype=str).fillna("")
                records = []
                prog = st.progress(0)
                
                # Mapping Cột A(0) -> O(14)
                cols_map = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", 
                            "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", 
                            "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]

                for i, r in df.iterrows():
                    d = {}
                    # Map từng cột theo index
                    for idx, field in enumerate(cols_map):
                        if idx < len(r):
                            d[field] = safe_str(r.iloc[idx])
                        else:
                            d[field] = ""
                    
                    # Logic kiểm tra: Chỉ cần 1 trong 3 cột Code/Name/Specs có data là lấy
                    has_data = d['item_code'] or d['item_name'] or d['specs']
                    
                    if has_data:
                        # Gán ảnh nếu có
                        if not d.get('image_path') and (i+2) in img_map:
                            d['image_path'] = img_map[i+2]
                        
                        d['row_order'] = i + 1 # Giữ nguyên thứ tự dòng
                        
                        # Chuyển đổi số liệu (bắt buộc thể hiện data giá)
                        d['qty'] = to_float(d.get('qty', 0))
                        d['buying_price_rmb'] = to_float(d['buying_price_rmb'])
                        d['total_buying_price_rmb'] = to_float(d['total_buying_price_rmb'])
                        d['exchange_rate'] = to_float(d['exchange_rate'])
                        d['buying_price_vnd'] = to_float(d['buying_price_vnd'])
                        d['total_buying_price_vnd'] = to_float(d['total_buying_price_vnd'])
                        
                        records.append(d)
                    
                    prog.progress((i + 1) / len(df))
                
                if records:
                    # Logic Ghi Đè: Xóa cũ insert mới để sạch data rác và giữ đúng thứ tự
                    chunk_ins = 100
                    # Xóa theo code (hoặc xóa hết nếu muốn làm mới hoàn toàn - ở đây ta làm upsert kiểu xóa chèn)
                    codes = [b['item_code'] for b in records if b['item_code']]
                    if codes:
                        supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                    
                    for k in range(0, len(records), chunk_ins):
                        batch = records[k:k+chunk_ins]
                        supabase.table("crm_purchases").insert(batch).execute()
                        
                    st.success(f"✅ Đã import {len(records)} dòng (đúng thứ tự Excel)!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")

    with c_view:
        # Load theo row_order ASC để đúng thứ tự Excel
        df_pur = load_data("crm_purchases", order_by="row_order", ascending=True) 
        
        # Bỏ đi cột created_at và row_order khi hiển thị
        cols_to_drop = ['created_at', 'row_order']
        df_pur = df_pur.drop(columns=[c for c in cols_to_drop if c in df_pur.columns], errors='ignore')

        search = st.text_input("🔍 Tìm kiếm (Name, Code, Specs...)", key="search_pur")
        
        if not df_pur.empty:
            # Logic Search: Tìm trên tất cả các cột (Đảm bảo tìm được tên, code, specs)
            if search:
                # Convert toàn bộ DF sang string và tìm kiếm
                mask = df_pur.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
                df_pur = df_pur[mask]
            
            st.dataframe(
                df_pur, 
                column_config={
                    "image_path": st.column_config.ImageColumn("Images"),
                    # Cấu hình hiển thị tiền tệ có dấu phân cách (1,000,000)
                    "buying_price_vnd": st.column_config.NumberColumn("Buying (VND)", format="%.0f"),
                    "total_buying_price_vnd": st.column_config.NumberColumn("Total (VND)", format="%.0f"),
                    "buying_price_rmb": st.column_config.NumberColumn("Buying (RMB)", format="%.0f"),
                    "total_buying_price_rmb": st.column_config.NumberColumn("Total (RMB)", format="%.0f"),
                    "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                }, 
                use_container_width=True, # Tự động căn chỉnh vừa màn hình
                height=700,
                hide_index=True
            )
        else: st.info("Kho hàng trống.")

# --- TAB 3: BÁO GIÁ ---
with t3:
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    st.subheader("TÍNH TOÁN & LÀM BÁO GIÁ")
    
    c1, c2, c3 = st.columns([2, 2, 1])
    cust_db = load_data("crm_customers")
    cust_list = cust_db["short_name"].tolist() if not cust_db.empty else []
    cust_name = c1.selectbox("Chọn Khách Hàng", [""] + cust_list)
    quote_no = c2.text_input("Số Báo Giá", key="q_no")
    
    if c3.button("🔄 Reset Quote"): 
        st.session_state.quote_df = pd.DataFrame()
        st.session_state.show_review = False 
        for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
             if f"pct_{k}" in st.session_state: del st.session_state[f"pct_{k}"]
        st.rerun()

    with st.expander("Cấu hình chi phí (%)", expanded=True):
        cols = st.columns(7)
        keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
        params = {}
        for i, k in enumerate(keys):
            default_val = st.session_state.get(f"pct_{k}", "0")
            val = cols[i].text_input(k.upper(), default_val, key=f"input_{k}")
            st.session_state[f"pct_{k}"] = val
            params[k] = to_float(val)

    # MATCHING
    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        db = load_data("crm_purchases")
        if db.empty: st.error("Kho rỗng!")
        else:
            lookup_code = {clean_key(r['item_code']): r for r in db.to_dict('records')}
            lookup_name = {clean_key(r['item_name']): r for r in db.to_dict('records')}
            
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            cols_found = {clean_key(c): c for c in df_rfq.columns}
            
            for i, r in df_rfq.iterrows():
                def get_val(keywords):
                    for k in keywords:
                        real_col = cols_found.get(k)
                        if real_col: return safe_str(r[real_col])
                    return ""

                code_excel = get_val(["item code", "code", "mã", "part number"])
                name_excel = get_val(["item name", "name", "tên", "description"])
                specs_excel = get_val(["specs", "quy cách", "thông số"])
                qty_raw = get_val(["q'ty", "qty", "quantity", "số lượng"])
                qty = to_float(qty_raw) if qty_raw else 1.0

                match = None
                if code_excel: match = lookup_code.get(clean_key(code_excel))
                if not match and name_excel: match = lookup_name.get(clean_key(name_excel))
                
                if match:
                    buy_rmb = to_float(match.get('buying_price_rmb', 0))
                    buy_vnd = to_float(match.get('buying_price_vnd', 0))
                    ex_rate = to_float(match.get('exchange_rate', 0))
                    final_code = match.get('item_code', '')
                    final_name = match.get('item_name', '')
                    final_specs = match.get('specs', '')
                    supplier = match.get('supplier_name', '')
                    image = match.get('image_path', '')
                    leadtime = match.get('leadtime', '')
                else:
                    buy_rmb = 0; buy_vnd = 0; ex_rate = 0
                    final_code = code_excel; final_name = name_excel; final_specs = specs_excel
                    supplier = ""; image = ""; leadtime = ""

                item = {
                    "No": i+1, "Cảnh báo": "", "Item code": final_code, "Item name": final_name, "Specs": final_specs, "Q'ty": qty, 
                    "Buying price(RMB)": fmt_num(buy_rmb), "Total buying price(rmb)": fmt_num(buy_rmb * qty),
                    "Exchange rate": fmt_num(ex_rate), "Buying price(VND)": fmt_num(buy_vnd), "Total buying price(VND)": fmt_num(buy_vnd * qty),
                    "AP price(VND)": "0", "AP total price(VND)": "0", "Unit price(VND)": "0", "Total price(VND)": "0",
                    "GAP": "0", "End user(%)": "0", "Buyer(%)": "0", "Import tax(%)": "0", "VAT": "0", "Transportation": "0",
                    "Management fee(%)": "0", "Payback(%)": "0", "Profit(VND)": "0", "Profit(%)": "0%",
                    "Supplier": supplier, "Image": image, "Leadtime": leadtime
                }
                res.append(item)
            
            st.session_state.quote_df = pd.DataFrame(res)
            st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, params)
            st.rerun()

    c_form1, c_form2 = st.columns(2)
    with c_form1:
        ap_f = st.text_input("Formula AP (vd: =BUY*1.1)", key="f_ap")
        if st.button("Apply AP Price"):
            if not st.session_state.quote_df.empty:
                for idx, row in st.session_state.quote_df.iterrows():
                    buy = to_float(row["Buying price(VND)"])
                    ap = to_float(row["AP price(VND)"])
                    new_ap = parse_formula(ap_f, buy, ap)
                    st.session_state.quote_df.at[idx, "AP price(VND)"] = fmt_num(new_ap)
                st.rerun()
    with c_form2:
        unit_f = st.text_input("Formula Unit (vd: =AP*1.2)", key="f_unit")
        if st.button("Apply Unit Price"):
            if not st.session_state.quote_df.empty:
                for idx, row in st.session_state.quote_df.iterrows():
                    buy = to_float(row["Buying price(VND)"])
                    ap = to_float(row["AP price(VND)"])
                    new_unit = parse_formula(unit_f, buy, ap)
                    st.session_state.quote_df.at[idx, "Unit price(VND)"] = fmt_num(new_unit)
                st.rerun()
    
    if not st.session_state.quote_df.empty:
        edited_df = st.data_editor(
            st.session_state.quote_df,
            column_config={
                "Image": st.column_config.ImageColumn("Ảnh"),
                "Buying price(RMB)": st.column_config.TextColumn("Buying(RMB)", disabled=True),
                "Buying price(VND)": st.column_config.TextColumn("Buying(VND)", disabled=True),
                "Cảnh báo": st.column_config.TextColumn("Cảnh báo", width="small", disabled=True),
                "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d"),
            },
            use_container_width=True, height=600, key="main_editor"
        )
        
        df_temp = edited_df.copy()
        df_recalc = recalculate_quote_logic(df_temp, params)
        if not df_recalc.equals(st.session_state.quote_df):
             st.session_state.quote_df = df_recalc; st.rerun()

        st.divider()
        c_rev, c_sv = st.columns([1, 1])
        with c_rev:
            if st.button("🔍 REVIEW BÁO GIÁ"): st.session_state.show_review = True
        
        if st.session_state.get('show_review', False):
            st.write("### 📋 BẢNG REVIEW")
            cols_review = ["No", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Leadtime"]
            valid_cols = [c for c in cols_review if c in st.session_state.quote_df.columns]
            st.dataframe(st.session_state.quote_df[valid_cols], use_container_width=True)

        with c_sv:
            if st.button("💾 LƯU LỊCH SỬ (QUAN TRỌNG ĐỂ LÀM PO)"):
                if cust_name:
                    recs = []
                    for r in st.session_state.quote_df.to_dict('records'):
                        recs.append({
                            "history_id": f"{cust_name}_{int(time.time())}", "date": datetime.now().strftime("%Y-%m-%d"),
                            "quote_no": quote_no, "customer": cust_name,
                            "item_code": r["Item code"], "qty": to_float(r["Q'ty"]),
                            "unit_price": to_float(r["Unit price(VND)"]),
                            "total_price_vnd": to_float(r["Total price(VND)"]),
                            "profit_vnd": to_float(r["Profit(VND)"])
                        })
                    supabase.table("crm_shared_history").insert(recs).execute(); st.success("Đã lưu lịch sử báo giá! Dữ liệu này sẽ dùng cho PO Khách hàng.")
                else: st.error("Chọn khách!")

# --- TAB 4: PO & ĐẶT HÀNG ---
with t4:
    # Init Flags
    if 'show_ncc_upload' not in st.session_state: st.session_state.show_ncc_upload = False
    if 'show_cust_upload' not in st.session_state: st.session_state.show_cust_upload = False
    if 'po_ncc_df' not in st.session_state: st.session_state.po_ncc_df = pd.DataFrame()
    if 'po_cust_df' not in st.session_state: st.session_state.po_cust_df = pd.DataFrame()
    
    c_ncc, c_kh = st.columns(2)
    
    # ---------------- PO NHÀ CUNG CẤP ----------------
    with c_ncc:
        st.subheader("1. ĐẶT HÀNG NHÀ CUNG CẤP")
        
        # Nút Admin Reset
        with st.expander("🔐 Admin: Reset Đếm Đơn NCC"):
            adm_po_ncc = st.text_input("Pass Admin NCC", type="password")
            if st.button("Reset Đếm Đơn NCC"):
                if adm_po_ncc == "admin":
                    supabase.table("db_supplier_orders").delete().neq("id", 0).execute()
                    st.success("Đã reset bộ đếm PO NCC!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass")

        # Nút Tạo Mới (Clear & Allow Upload)
        if st.button("➕ TẠO MỚI (Đặt NCC)"):
            st.session_state.po_ncc_df = pd.DataFrame()
            st.session_state.show_ncc_upload = True # Cho phép hiện upload
            st.rerun()

        if st.session_state.show_ncc_upload:
            po_s_no = st.text_input("Số PO NCC", key="po_s_input")
            supps = load_data("crm_suppliers")
            s_name = st.selectbox("Chọn NCC", [""] + supps['short_name'].tolist() if not supps.empty else [], key="sel_ncc")
            
            up_s = st.file_uploader("Upload File Items (Excel)", key="ups")
            
            if up_s and st.button("Load Items NCC"):
                # Load Excel
                df_up = pd.read_excel(up_s, dtype=str).fillna("")
                # Merge with Database to get Prices & Leadtime
                db = load_data("crm_purchases")
                lookup = {clean_key(r['item_code']): r for r in db.to_dict('records')}
                
                recs = []
                for i, r in df_up.iterrows():
                    # Excel NCC: Code(B), Qty(E)
                    code = safe_str(r.iloc[1])
                    qty = to_float(r.iloc[4])
                    
                    # Lookup Info
                    match = lookup.get(clean_key(code))
                    if match:
                        name = match['item_name']
                        specs = match['specs']
                        buy_rmb = to_float(match['buying_price_rmb'])
                        rate = to_float(match['exchange_rate'])
                        buy_vnd = to_float(match['buying_price_vnd'])
                        leadtime = match['leadtime']
                    else:
                        name = safe_str(r.iloc[2]); specs = safe_str(r.iloc[3]); 
                        buy_rmb = 0; rate = 0; buy_vnd = 0; leadtime = "0"
                    
                    eta = calc_eta(datetime.now(), leadtime)
                    
                    recs.append({
                        "No": i+1, "Item code": code, "Item name": name, "Specs": specs, "Q'ty": qty,
                        "Buying price(RMB)": fmt_num(buy_rmb), "Total buying price(RMB)": fmt_num(buy_rmb * qty),
                        "Exchange rate": fmt_num(rate),
                        "Buying price(VND)": fmt_num(buy_vnd), "Total buying price(VND)": fmt_num(buy_vnd * qty),
                        "ETA": eta
                    })
                st.session_state.po_ncc_df = pd.DataFrame(recs)
            
            # Hiển thị bảng
            if not st.session_state.po_ncc_df.empty:
                st.dataframe(st.session_state.po_ncc_df, use_container_width=True)
                
                if st.button("💾 XÁC NHẬN ĐẶT HÀNG NCC"):
                    if not po_s_no or not s_name: st.error("Thiếu PO hoặc NCC")
                    else:
                        # 1. Lưu DB Đơn hàng
                        db_recs = []
                        for r in st.session_state.po_ncc_df.to_dict('records'):
                            db_recs.append({
                                "po_number": po_s_no, "supplier": s_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                                "item_code": r["Item code"], "item_name": r["Item name"], "specs": r["Specs"],
                                "qty": to_float(r["Q'ty"]), "total_vnd": to_float(r["Total buying price(VND)"]),
                                "eta": r["ETA"]
                            })
                        supabase.table("db_supplier_orders").insert(db_recs).execute()
                        
                        # 2. Insert Tracking (Link Data)
                        track_rec = {
                            "po_no": po_s_no, "partner": s_name, "status": "Ordered", "order_type": "NCC",
                            "last_update": datetime.now().strftime("%d/%m/%Y"), 
                            "eta": st.session_state.po_ncc_df.iloc[0]["ETA"]
                        }
                        supabase.table("crm_tracking").insert([track_rec]).execute()

                        # 3. Xuất File Excel (No footer) & Lưu Drive
                        wb = Workbook()
                        ws = wb.active; ws.title = "PO NCC"
                        ws.append(["No", "Item code", "Item name", "Specs", "Q'ty", "Buying(RMB)", "Total(RMB)", "Rate", "Buying(VND)", "Total(VND)", "ETA"])
                        for r in st.session_state.po_ncc_df.to_dict('records'):
                            ws.append([r["No"], r["Item code"], r["Item name"], r["Specs"], r["Q'ty"], r["Buying price(RMB)"], r["Total buying price(RMB)"], r["Exchange rate"], r["Buying price(VND)"], r["Total buying price(VND)"], r["ETA"]])
                        
                        out = io.BytesIO(); wb.save(out); out.seek(0)
                        
                        # Cấu trúc: PO_NCC \ NĂM \ NCC \ THÁNG \ FILE
                        curr_year = datetime.now().strftime("%Y")
                        curr_month = datetime.now().strftime("%b").upper() # DEC
                        file_name = f"PO_{po_s_no}_{s_name}.xlsx"
                        path_list = ["PO_NCC", curr_year, s_name, curr_month]
                        
                        folder_link, file_id = upload_to_drive_structured(out, path_list, file_name)
                        
                        st.success("✅ Đặt hàng thành công! Đã link sang Tracking.")
                        st.markdown(f"📂 **[Mở Folder PO NCC: {s_name}/{curr_month}]({folder_link})**", unsafe_allow_html=True)

    # ---------------- PO KHÁCH HÀNG ----------------
    with c_kh:
        st.subheader("2. PO KHÁCH HÀNG")
        
        with st.expander("🔐 Admin: Reset Đếm Đơn Khách"):
            adm_po_cust = st.text_input("Pass Admin Cust", type="password")
            if st.button("Reset Đếm Đơn Khách"):
                if adm_po_cust == "admin":
                    supabase.table("db_customer_orders").delete().neq("id", 0).execute()
                    st.success("Đã reset bộ đếm PO Khách!"); time.sleep(1); st.rerun()
                else: st.error("Sai Pass")

        if st.button("➕ TẠO MỚI (PO Khách)"):
            st.session_state.po_cust_df = pd.DataFrame()
            st.session_state.show_cust_upload = True
            st.rerun()

        if st.session_state.show_cust_upload:
            po_c_no = st.text_input("Số PO Khách", key="po_c_input")
            custs = load_data("crm_customers")
            c_name = st.selectbox("Chọn Khách", [""] + custs['short_name'].tolist() if not custs.empty else [], key="sel_cust_po")
            
            up_c = st.file_uploader("Upload File PO Khách (Excel)", key="upc")
            
            if up_c and st.button("Load PO Khách"):
                if not c_name: st.error("Vui lòng chọn khách trước để lấy giá!")
                else:
                    # Load Excel PO (Mapping A-E)
                    df_up = pd.read_excel(up_c, header=None, skiprows=1, dtype=str).fillna("")
                    
                    # QUAN TRỌNG: Lấy giá từ lịch sử báo giá của CHÍNH KHÁCH HÀNG NÀY
                    hist = load_data("crm_shared_history") 
                    # Filter khách & Sort mới nhất
                    cust_hist = hist[hist['customer'] == c_name].sort_values(by='date', ascending=False)
                    
                    # Tạo Map: Code -> Unit Price
                    price_lookup = {}
                    for _, h in cust_hist.iterrows():
                        c_code = clean_key(h['item_code'])
                        if c_code not in price_lookup:
                            price_lookup[c_code] = to_float(h['unit_price'])
                    
                    # Load DB for Leadtime -> ETA
                    db_items = load_data("crm_purchases")
                    lt_lookup = {clean_key(r['item_code']): r['leadtime'] for r in db_items.to_dict('records')}

                    recs = []
                    for i, r in df_up.iterrows():
                        # Map Cols: A(No), B(Code), C(Name), D(Specs), E(Qty)
                        code = safe_str(r.iloc[1])
                        qty = to_float(r.iloc[4])
                        
                        # Unit Price (From specific customer history)
                        unit_price = price_lookup.get(clean_key(code), 0)
                        total = unit_price * qty
                        
                        # ETA calculation
                        leadtime = lt_lookup.get(clean_key(code), "0")
                        eta = calc_eta(datetime.now(), leadtime)

                        if code:
                            recs.append({
                                "No.": safe_str(r.iloc[0]), "Item code": code, "Item name": safe_str(r.iloc[2]),
                                "Specs": safe_str(r.iloc[3]), "Q'ty": qty,
                                "Unit price(VND)": fmt_num(unit_price), "Total price(VND)": fmt_num(total),
                                "Customer": c_name, "ETA": eta
                            })
                    st.session_state.po_cust_df = pd.DataFrame(recs)
            
            if not st.session_state.po_cust_df.empty:
                st.dataframe(st.session_state.po_cust_df, use_container_width=True)
                
                if st.button("💾 LƯU PO KHÁCH HÀNG"):
                    if not po_c_no: st.error("Thiếu số PO")
                    else:
                        # 1. Save DB
                        db_recs = []
                        for r in st.session_state.po_cust_df.to_dict('records'):
                            db_recs.append({
                                "po_number": po_c_no, "customer": c_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                                "item_code": r["Item code"], "item_name": r["Item name"], "specs": r["Specs"],
                                "qty": to_float(r["Q'ty"]), "unit_price": to_float(r["Unit price(VND)"]),
                                "total_price": to_float(r["Total price(VND)"]), "eta": r["ETA"]
                            })
                        supabase.table("db_customer_orders").insert(db_recs).execute()
                        
                        # 2. Insert Tracking
                        track_rec = {
                            "po_no": po_c_no, "partner": c_name, "status": "Waiting", "order_type": "KH",
                            "last_update": datetime.now().strftime("%d/%m/%Y"),
                            "eta": st.session_state.po_cust_df.iloc[0]["ETA"]
                        }
                        supabase.table("crm_tracking").insert([track_rec]).execute()
                        
                        # 3. Save Excel: PO_KHACH_HANG \ NĂM \ KHÁCH \ THÁNG \ FILE
                        wb = Workbook()
                        ws = wb.active; ws.title = "PO Customer"
                        ws.append(["No.", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Customer", "ETA"])
                        for r in st.session_state.po_cust_df.to_dict('records'):
                            ws.append([r["No."], r["Item code"], r["Item name"], r["Specs"], r["Q'ty"], r["Unit price(VND)"], r["Total price(VND)"], r["Customer"], r["ETA"]])
                        
                        out = io.BytesIO(); wb.save(out); out.seek(0)
                        
                        curr_year = datetime.now().strftime("%Y")
                        curr_month = datetime.now().strftime("%b").upper()
                        file_name = f"PO_{po_c_no}_{c_name}.xlsx"
                        path_list = ["PO_KHACH_HANG", curr_year, c_name, curr_month]
                        
                        folder_link, _ = upload_to_drive_structured(out, path_list, file_name)
                        
                        st.success("✅ Lưu PO Khách thành công! Đã link sang Tracking.")
                        st.markdown(f"📂 **[Mở Folder PO Khách: {c_name}/{curr_month}]({folder_link})**", unsafe_allow_html=True)

# --- TAB 5: TRACKING ---
with t5:
    st.subheader("THEO DÕI ĐƠN HÀNG (TRACKING)")
    if st.button("🔄 Refresh Tracking"): st.cache_data.clear(); st.rerun()
    
    # Load Data (Fix lỗi hiển thị)
    df_track = load_data("crm_tracking", order_by="id")
    
    if not df_track.empty:
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.markdown("#### Cập nhật trạng thái / Ảnh")
            po_list = df_track['po_no'].unique()
            sel_po = st.selectbox("Chọn PO", po_list, key="tr_po")
            
            # Form Update
            new_status = st.selectbox("Trạng thái mới", ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"], key="tr_st")
            proof_img = st.file_uploader("Upload Ảnh Proof", type=['png', 'jpg'], key="tr_img")
            
            if st.button("Cập nhật Tracking"):
                upd_data = {"status": new_status, "last_update": datetime.now().strftime("%d/%m/%Y")}
                if proof_img:
                    lnk, _ = upload_to_drive_simple(proof_img, "CRM_PROOF", f"PRF_{sel_po}_{int(time.time())}.png")
                    upd_data["proof_image"] = lnk
                
                supabase.table("crm_tracking").update(upd_data).eq("po_no", sel_po).execute()
                st.success("Updated!"); time.sleep(1); st.rerun()

        with c2:
            st.markdown("#### Danh sách đơn hàng")
            st.dataframe(
                df_track, 
                column_config={
                    "proof_image": st.column_config.ImageColumn("Proof"), 
                    "status": st.column_config.TextColumn("Status"),
                    "po_no": "PO No.", "partner": "Partner", "eta": "ETA"
                }, 
                use_container_width=True, 
                hide_index=True
            )
    else: st.info("Chưa có dữ liệu Tracking. Hãy tạo PO ở Tab 4.")

# --- TAB 6: MASTER DATA ---
with t6:
    tc, ts, tt = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    with tc:
        df = load_data("crm_customers"); st.data_editor(df, num_rows="dynamic", use_container_width=True)
        up = st.file_uploader("Import KH", key="uck")
        if up and st.button("Import KH"):
            d = pd.read_excel(up, dtype=str).fillna("")
            recs = []
            for i,r in d.iterrows(): recs.append({"short_name": safe_str(r.iloc[0]), "full_name": safe_str(r.iloc[1]), "address": safe_str(r.iloc[2])})
            supabase.table("crm_customers").insert(recs).execute(); st.rerun()
    with ts:
        df = load_data("crm_suppliers"); st.data_editor(df, num_rows="dynamic", use_container_width=True)
        up = st.file_uploader("Import NCC", key="usn")
        if up and st.button("Import NCC"):
            d = pd.read_excel(up, dtype=str).fillna("")
            recs = []
            for i,r in d.iterrows(): recs.append({"short_name": safe_str(r.iloc[0]), "full_name": safe_str(r.iloc[1]), "address": safe_str(r.iloc[2])})
            supabase.table("crm_suppliers").insert(recs).execute(); st.rerun()
    with tt:
        st.write("Upload Template Excel")
        up_t = st.file_uploader("File Template (.xlsx)", type=["xlsx"])
        t_name = st.text_input("Tên Template (Nhập: AAA-QUOTATION)")
        if up_t and t_name and st.button("Lưu Template"):
            lnk, fid = upload_to_drive_simple(up_t, "CRM_TEMPLATES", f"TMP_{t_name}.xlsx")
            if fid: supabase.table("crm_templates").insert([{"template_name": t_name, "file_id": fid, "last_updated": datetime.now().strftime("%d/%m/%Y")}]).execute(); st.success("OK"); st.rerun()
        st.dataframe(load_data("crm_templates"))
