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
APP_VERSION = "V6051 - STABLE FIX"
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
    
    /* CSS CHO CÁC NÚT BẤM */
    div.stButton > button { 
        width: 100%; 
        border-radius: 5px; 
        font-weight: bold; 
        background-color: #262730; 
        color: #ffffff; 
        border: 1px solid #4e4e4e;
    }
    div.stButton > button:hover {
        background-color: #444444;
        color: #ffffff;
        border-color: #ffffff;
    }
    
    .total-view {
        font-size: 20px;
        font-weight: bold;
        color: #00FF00;
        background-color: #262730;
        padding: 10px;
        border-radius: 8px;
        text-align: right;
        margin-top: 10px;
        border: 1px solid #4e4e4e;
    }
    </style>""", unsafe_allow_html=True)

# LIBRARIES & CONNECTIONS
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    from openpyxl import load_workbook, Workbook
except ImportError:
    st.error("⚠️ Thiếu thư viện. Vui lòng chạy lệnh: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl")
    st.stop()

# CONNECT SERVER
try:
    if "supabase" not in st.secrets or "google_oauth" not in st.secrets:
        st.error("⚠️ Chưa cấu hình secrets.toml.")
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

def get_or_create_folder_hierarchy(srv, path_list, parent_id):
    current_parent_id = parent_id
    for folder_name in path_list:
        q = f"'{current_parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = srv.files().list(q=q, fields="files(id)").execute().get('files', [])
        if results: current_parent_id = results[0]['id']
        else:
            file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [current_parent_id]}
            folder = srv.files().create(body=file_metadata, fields='id').execute()
            current_parent_id = folder.get('id')
            try: srv.permissions().create(fileId=current_parent_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            except: pass
    return current_parent_id

def upload_to_drive_structured(file_obj, path_list, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, path_list, ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        return folder_link, file_id
    except: return "", ""

def upload_to_drive_simple(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, [sub_folder], ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200", file_id
    except: return "", ""

def search_file_in_drive_by_name(name_contains):
    srv = get_drive_service()
    if not srv: return None, None, None
    try:
        q = f"name contains '{name_contains}' and trashed=false"
        results = srv.files().list(q=q, fields="files(id, name, parents)").execute().get('files', [])
        if results: return results[0]['id'], results[0]['name'], (results[0]['parents'][0] if 'parents' in results[0] else None)
        return None, None, None
    except: return None, None, None

def download_from_drive(file_id):
    srv = get_drive_service()
    if not srv: return None
    try:
        request = srv.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        fh.seek(0) 
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
        if x is None: return "0"
        val = float(x)
        if val.is_integer(): return "{:,.0f}".format(val)
        else:
            s = "{:,.3f}".format(val)
            return s.rstrip('0').rstrip('.')
    except: return "0"

def fmt_float_1(x):
    try:
        if x is None: return "0.0"
        val = float(x)
        return "{:,.1f}".format(val)
    except: return "0.0"

def clean_key(s): return safe_str(s).lower()

def strict_match_key(val):
    if val is None: return ""
    s = str(val).lower()
    return re.sub(r'\s+', '', s)

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime): dt_order = order_date_str
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
        if table == "crm_purchases": query = query.order("row_order", desc=False)
        else: query = query.order(order_by, desc=not ascending)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if table != "crm_tracking" and table != "crm_payments" and not df.empty and 'id' in df.columns: 
            df = df.drop(columns=['id'])
        return df
    except: return pd.DataFrame()

# =============================================================================
# 3. LOGIC TÍNH TOÁN CORE (Đã Fix Làm Tròn để chống Loop)
# =============================================================================
def recalculate_quote_logic(df, params):
    # Các cột cần chuyển sang số
    cols_to_num = ["Q'ty", "Buying price(VND)", "Buying price(RMB)", "AP price(VND)", "Unit price(VND)", 
                   "Exchange rate", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", "Transportation", 
                   "Management fee(%)", "Payback(%)"]
    
    for c in cols_to_num:
        if c in df.columns: df[c] = df[c].apply(to_float)
    
    # Tính toán
    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]

    gap_positive = df["GAP"].apply(lambda x: x * 0.6 if x > 0 else 0)
    
    cost_ops = (gap_positive + df["End user(%)"] + df["Buyer(%)"] + 
                df["Import tax(%)"] + df["VAT"] + df["Management fee(%)"] + df["Transportation"])
    
    df["Profit(VND)"] = df["Total price(VND)"] - df["Total buying price(VND)"] - cost_ops + df["Payback(%)"]
    
    df["Profit_Pct_Raw"] = df.apply(lambda row: (row["Profit(VND)"] / row["Total price(VND)"] * 100) if row["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    
    def set_warning(row):
        if "KHÔNG KHỚP" in str(row.get("Cảnh báo", "")): return row.get("Cảnh báo", "")
        return "⚠️ LOW" if row["Profit_Pct_Raw"] < 10 else "✅ OK"
    
    if "Cảnh báo" in df.columns: df["Cảnh báo"] = df.apply(set_warning, axis=1)
    else: df["Cảnh báo"] = df.apply(lambda r: "⚠️ LOW" if r["Profit_Pct_Raw"] < 10 else "✅ OK", axis=1)

    # --- FIX QUAN TRỌNG: LÀM TRÒN SỐ ĐỂ TRÁNH VÒNG LẶP ---
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].round(2)
    
    return df

def parse_formula(formula, buying_price, ap_price):
    if not formula: return 0.0
    s = str(formula).strip().upper()
    if s.startswith("="): s = s[1:]
    val_buy = float(buying_price) if buying_price else 0.0
    val_ap = float(ap_price) if ap_price else 0.0
    s = s.replace("BUYING PRICE", str(val_buy)).replace("BUY", str(val_buy))
    s = s.replace("AP PRICE", str(val_ap)).replace("AP", str(val_ap))
    if not all(c in "0123456789.+-*/() " for c in s): return 0.0
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

# --- TAB 2: KHO HÀNG ---
with t2:
    st.subheader("QUẢN LÝ KHO HÀNG")
    c_imp, c_view = st.columns([1, 4])
    with c_imp:
        st.markdown("**📥 Import Kho Hàng**")
        st.caption("Excel cột A->O")
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
                df = pd.read_excel(up_file, header=None, skiprows=1, dtype=str).fillna("")
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                img_map = {}
                for image in getattr(ws, '_images', []):
                    try:
                        row = image.anchor._from.row + 1
                        buf = io.BytesIO(image._data())
                        cell_specs = ws.cell(row=row, column=4).value 
                        specs_val = safe_str(cell_specs)
                        safe_name = re.sub(r'[\\/*?:"<>|]', "", specs_val).strip()
                        if not safe_name: safe_name = f"NO_SPECS_R{row}"
                        link, _ = upload_to_drive_simple(buf, "CRM_PRODUCT_IMAGES", f"{safe_name}.png")
                        img_map[row] = link
                    except: pass
                
                records = []
                cols_map = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", 
                            "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", 
                            "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
                for i, r in df.iterrows():
                    d = {}
                    for idx, field in enumerate(cols_map):
                        if idx < len(r): d[field] = safe_str(r.iloc[idx])
                        else: d[field] = ""
                    if d['item_code'] or d['item_name']:
                        if not d.get('image_path') and (i+2) in img_map: d['image_path'] = img_map[i+2]
                        d['row_order'] = i + 1 
                        d['qty'] = to_float(d.get('qty', 0))
                        d['buying_price_rmb'] = to_float(d['buying_price_rmb'])
                        d['total_buying_price_rmb'] = to_float(d['total_buying_price_rmb'])
                        d['exchange_rate'] = to_float(d['exchange_rate'])
                        d['buying_price_vnd'] = to_float(d['buying_price_vnd'])
                        d['total_buying_price_vnd'] = to_float(d['total_buying_price_vnd'])
                        records.append(d)
                
                if records:
                    codes = [b['item_code'] for b in records if b['item_code']]
                    if codes:
                        for k in range(0, len(codes), 50):
                             try: supabase.table("crm_purchases").delete().in_("item_code", codes[k:k+50]).execute()
                             except: pass
                    count = 0
                    for k in range(0, len(records), 100):
                        try:
                            supabase.table("crm_purchases").insert(records[k:k+100]).execute()
                            count += len(records[k:k+100])
                        except: pass
                    st.success(f"✅ Đã import {count} dòng!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    with c_view:
        df_pur = load_data("crm_purchases", order_by="row_order", ascending=True) 
        if not df_pur.empty:
            df_pur = df_pur.drop(columns=['created_at', 'row_order'], errors='ignore')
            search = st.text_input("🔍 Tìm kiếm", key="search_pur")
            if search: df_pur = df_pur[df_pur.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)]
            for c in ["buying_price_vnd", "total_buying_price_vnd", "buying_price_rmb", "total_buying_price_rmb"]:
                if c in df_pur.columns: df_pur[c] = df_pur[c].apply(fmt_num)
            st.dataframe(df_pur, column_config={"image_path": st.column_config.ImageColumn("Images")}, use_container_width=True, height=700, hide_index=True)

# --- TAB 3: BÁO GIÁ ---
with t3:
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    
    with st.expander("🔎 TRA CỨU & TRẠNG THÁI BÁO GIÁ", expanded=False):
        c_src1, c_src2 = st.columns(2)
        search_kw = c_src1.text_input("Nhập từ khóa", help="Tên Khách, Quote No, Code...")
        up_src = c_src2.file_uploader("Hoặc Import Excel kiểm tra", type=["xlsx"], key="src_up")
        
        if st.button("Kiểm tra trạng thái"):
            df_hist = load_data("crm_shared_history")
            df_po = load_data("db_customer_orders")
            item_map = {clean_key(r['item_code']): f"{safe_str(r['item_name'])} {safe_str(r['specs'])}" for r in load_data("crm_purchases").to_dict('records')}
            po_map = {f"{clean_key(r['customer'])}_{clean_key(r['item_code'])}": r['po_number'] for r in df_po.to_dict('records')}
            
            results = []
            if search_kw and not df_hist.empty:
                found = df_hist[df_hist.astype(str).apply(lambda x: x.str.contains(search_kw, case=False)).any(axis=1)]
                for _, r in found.iterrows():
                    key = f"{clean_key(r['customer'])}_{clean_key(r['item_code'])}"
                    results.append({"Trạng thái": "✅ Đã báo giá", "Customer": r['customer'], "Date": r['date'], "Item Code": r['item_code'], 
                                    "Info": item_map.get(clean_key(r['item_code']), ""), "Unit Price": fmt_float_1(r['unit_price']),
                                    "Quote No": r['quote_no'], "PO No": po_map.get(key, "---")})
            if results: st.dataframe(pd.DataFrame(results), use_container_width=True)
            else: st.info("Không tìm thấy kết quả.")

    with st.expander("📂 XEM CHI TIẾT FILE LỊCH SỬ", expanded=False):
        df_hist_idx = load_data("crm_shared_history", order_by="date")
        if not df_hist_idx.empty:
            df_hist_idx['display'] = df_hist_idx.apply(lambda x: f"{x['date']} | {x['customer']} | Quote: {x['quote_no']}", axis=1)
            sel_quote_hist = st.selectbox("Chọn báo giá cũ:", [""] + df_hist_idx['display'].unique().tolist())
            if sel_quote_hist:
                parts = sel_quote_hist.split(" | ")
                if len(parts) >= 3:
                    q_no = parts[2].replace("Quote: ", "").strip()
                    cust = parts[1].strip()
                    fid, fname, pid = search_file_in_drive_by_name(f"HIST_{q_no}_{cust}")
                    if pid: st.markdown(f"👉 **[Mở Folder Drive](https://drive.google.com/drive/folders/{pid})**", unsafe_allow_html=True)
                    if fid and st.button(f"Tải: {fname}"):
                        fh = download_from_drive(fid)
                        if fh: st.dataframe(pd.read_csv(fh, encoding='utf-8-sig', on_bad_lines='skip'), use_container_width=True)

    st.divider()
    st.subheader("TÍNH TOÁN & LÀM BÁO GIÁ")
    c1, c2, c3 = st.columns([2, 2, 1])
    cust_list = load_data("crm_customers")["short_name"].tolist()
    cust_name = c1.selectbox("Chọn Khách Hàng", [""] + cust_list)
    quote_no = c2.text_input("Số Báo Giá", key="q_no")
    
    c3.markdown('<div class="dark-btn">', unsafe_allow_html=True)
    if c3.button("🔄 Reset Quote"): st.session_state.quote_df = pd.DataFrame(); st.session_state.show_review = False; st.rerun()
    c3.markdown('</div>', unsafe_allow_html=True)

    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        db_records = load_data("crm_purchases").to_dict('records')
        df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
        res = []
        cols_found = {clean_key(c): c for c in df_rfq.columns}
        
        for i, r in df_rfq.iterrows():
            def get_val(keywords):
                for k in keywords:
                    if cols_found.get(k): return safe_str(r[cols_found.get(k)])
                return ""
            code_excel = get_val(["item code", "code", "mã", "part number"])
            name_excel = get_val(["item name", "name", "tên", "description"])
            specs_excel = get_val(["specs", "quy cách", "thông số"])
            qty = to_float(get_val(["q'ty", "qty", "quantity", "số lượng"]) or 1.0)
            
            candidates = [rec for rec in db_records 
                if strict_match_key(rec['item_code']) == strict_match_key(code_excel)
                and strict_match_key(rec['item_name']) == strict_match_key(name_excel)
                and strict_match_key(rec['specs']) == strict_match_key(specs_excel)]
            
            match = candidates[0] if candidates else {}
            buy_rmb = to_float(match.get('buying_price_rmb', 0))
            buy_vnd = to_float(match.get('buying_price_vnd', 0))
            ex_rate = to_float(match.get('exchange_rate', 0))
            
            res.append({
                "Xóa": False, "No": i+1, "Cảnh báo": "" if match else "⚠️ DATA KHÔNG KHỚP", 
                "Item code": code_excel, "Item name": name_excel, "Specs": specs_excel, 
                "Q'ty": qty, "Buying price(RMB)": buy_rmb, "Total buying price(rmb)": buy_rmb * qty,
                "Exchange rate": ex_rate, "Buying price(VND)": buy_vnd, "Total buying price(VND)": buy_vnd * qty,
                "AP price(VND)": 0.0, "AP total price(VND)": 0.0, "Unit price(VND)": 0.0, "Total price(VND)": 0.0,
                "GAP": 0.0, "End user(%)": 0.0, "Buyer(%)": 0.0, "Import tax(%)": 0.0, "VAT": 0.0, "Transportation": 0.0,
                "Management fee(%)": 0.0, "Payback(%)": 0.0, "Profit(VND)": 0.0, "Profit(%)": "0.0%",
                "Supplier": match.get('supplier_name', ''), "Image": match.get('image_path', ''), "Leadtime": match.get('leadtime', '')
            })
        st.session_state.quote_df = pd.DataFrame(res)
    
    c_form1, c_form2, c_del = st.columns([2, 2, 1])
    with c_form1:
        ap_f = st.text_input("Formula AP (vd: =BUY*1.1)", key="f_ap")
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("Apply AP Price"):
            if not st.session_state.quote_df.empty:
                st.session_state.quote_df = st.session_state.quote_df[st.session_state.quote_df["No"] != "TOTAL"]
                for idx, row in st.session_state.quote_df.iterrows():
                    st.session_state.quote_df.at[idx, "AP price(VND)"] = parse_formula(ap_f, row["Buying price(VND)"], row["AP price(VND)"])
                st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, {})
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    with c_form2:
        unit_f = st.text_input("Formula Unit (vd: =AP*1.2)", key="f_unit")
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("Apply Unit Price"):
            if not st.session_state.quote_df.empty:
                st.session_state.quote_df = st.session_state.quote_df[st.session_state.quote_df["No"] != "TOTAL"]
                for idx, row in st.session_state.quote_df.iterrows():
                    st.session_state.quote_df.at[idx, "Unit price(VND)"] = parse_formula(unit_f, row["Buying price(VND)"], row["AP price(VND)"])
                st.session_state.quote_df = recalculate_quote_logic(st.session_state.quote_df, {})
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    with c_del:
        st.write(""); st.write("")
        st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
        if st.button("🗑️ DELETE SELECTED"):
             if not st.session_state.quote_df.empty:
                  st.session_state.quote_df = st.session_state.quote_df[(st.session_state.quote_df["Xóa"] == False) & (st.session_state.quote_df["No"] != "TOTAL")].reset_index(drop=True)
                  st.session_state.quote_df["No"] = st.session_state.quote_df.index + 1
                  st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    if not st.session_state.quote_df.empty:
        st.session_state.quote_df = st.session_state.quote_df[st.session_state.quote_df["No"] != "TOTAL"]
        if "Xóa" not in st.session_state.quote_df.columns: st.session_state.quote_df.insert(0, "Xóa", False)
        
        cols_order = ["Xóa", "Cảnh báo", "No"] + [c for c in st.session_state.quote_df.columns if c not in ["Xóa", "Cảnh báo", "No"]]
        st.session_state.quote_df = st.session_state.quote_df[cols_order]
        df_show = st.session_state.quote_df.drop(columns=["Image", "Profit_Pct_Raw"], errors='ignore')

        cols_to_sum = ["Q'ty", "Buying price(RMB)", "Total buying price(rmb)", "Buying price(VND)", "Total buying price(VND)", 
                       "AP price(VND)", "AP total price(VND)", "Unit price(VND)", "Total price(VND)", "GAP", 
                       "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", "Transportation", "Management fee(%)", "Payback(%)", "Profit(VND)"]
        totals = {c: df_show[c].apply(to_float).sum() for c in cols_to_sum if c in df_show.columns}
        
        total_row = pd.DataFrame([totals])
        for c in df_show.columns: 
            if c not in total_row.columns: total_row[c] = ""
        total_row["No"] = "TOTAL"; total_row["Xóa"] = False 
        
        df_display = pd.concat([df_show, total_row], ignore_index=True)[cols_order]

        column_config = {
            "Xóa": st.column_config.CheckboxColumn("Xóa", width="small"),
            "Cảnh báo": st.column_config.TextColumn("Cảnh báo", width="small", disabled=True),
            "No": st.column_config.TextColumn("No", width="small", disabled=True),
            "Q'ty": st.column_config.NumberColumn("Q'ty", format="%d"),
            "Exchange rate": st.column_config.NumberColumn("Exchange rate", format="%.2f"),
        }
        for c in cols_to_sum: 
             # --- FIX LỖI SPINTF ---
             # Dùng %.1f thay vì %,.1f (bỏ dấu phẩy) để tránh lỗi SyntaxError
             column_config[c] = st.column_config.NumberColumn(c, format="%.1f")

        edited_df_display = st.data_editor(df_display, column_config=column_config, use_container_width=True, height=600, key="quote_editor_main", hide_index=True, num_rows="dynamic")
        
        # --- LOGIC UPDATE (Đã thêm làm tròn để tránh Flash loop) ---
        edited_data_only = edited_df_display[edited_df_display["No"] != "TOTAL"].copy().reset_index(drop=True)
        current_state_data = st.session_state.quote_df.reset_index(drop=True)
        
        # Chỉ update và rerun nếu dữ liệu thực sự thay đổi (đã làm tròn)
        numeric_cols_chk = edited_data_only.select_dtypes(include=[np.number]).columns
        edited_data_only[numeric_cols_chk] = edited_data_only[numeric_cols_chk].round(2)
        current_state_data[numeric_cols_chk] = current_state_data[numeric_cols_chk].round(2)
        
        if not edited_data_only.equals(current_state_data):
            updated_df = recalculate_quote_logic(edited_data_only, {})
            st.session_state.quote_df = updated_df
            st.rerun()

        total_q = totals.get("Total price(VND)", 0)
        st.markdown(f'<div class="total-view">💰 TỔNG GIÁ TRỊ BÁO GIÁ: {fmt_float_1(total_q)} VND</div>', unsafe_allow_html=True)
        st.divider()

        # Review & Export
        c_rev, c_sv = st.columns([1, 1])
        with c_rev:
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("🔍 REVIEW BÁO GIÁ"): st.session_state.show_review = True
            st.markdown('</div>', unsafe_allow_html=True)
        
        if st.session_state.get('show_review', False):
            st.write("### 📋 BẢNG REVIEW")
            df_review = st.session_state.quote_df.copy()
            total_rev = {c: df_review[c].apply(to_float).sum() for c in ["Q'ty", "Unit price(VND)", "Total price(VND)"] if c in df_review.columns}
            total_rev["No"] = "TOTAL"
            df_review = pd.concat([df_review, pd.DataFrame([total_rev])], ignore_index=True)
            
            def highlight_review_total(row): return ['background-color: #ffffcc; font-weight: bold; color: black'] * len(row) if row['No'] == 'TOTAL' else [''] * len(row)
            
            st.dataframe(df_review[["No", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Leadtime"]].style.apply(highlight_review_total, axis=1), 
                         use_container_width=True, hide_index=True, 
                         column_config={"Q'ty": st.column_config.NumberColumn(format="%d"), "Unit price(VND)": st.column_config.NumberColumn(format="%.1f"), "Total price(VND)": st.column_config.NumberColumn(format="%.1f")})
            
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("📤 XUẤT BÁO GIÁ (Excel)"):
                if not cust_name: st.error("Chưa chọn khách!")
                else:
                    try:
                        tmpl = load_data("crm_templates")
                        fid = tmpl[tmpl['template_name'].str.contains("AAA-QUOTATION", case=False)].iloc[0]['file_id']
                        fh = download_from_drive(fid)
                        wb = load_workbook(fh); ws = wb.active; start_row = 11
                        ws['H8'] = safe_str(st.session_state.quote_df.iloc[0]['Leadtime'] if not st.session_state.quote_df.empty else "")
                        for idx, row in st.session_state.quote_df.iterrows():
                            r = start_row + idx
                            ws[f'A{r}'] = row['No']; ws[f'C{r}'] = row['Item code']; ws[f'D{r}'] = row['Item name']; ws[f'E{r}'] = row['Specs']
                            ws[f'F{r}'] = to_float(row["Q'ty"]); ws[f'G{r}'] = to_float(row["Unit price(VND)"]); ws[f'H{r}'] = to_float(row["Total price(VND)"])
                        out = io.BytesIO(); wb.save(out); out.seek(0)
                        fname = f"QUOTE_{quote_no}_{cust_name}_{int(time.time())}.xlsx"
                        lnk, _ = upload_to_drive_structured(out, ["QUOTATION_HISTORY", cust_name, datetime.now().strftime("%Y"), datetime.now().strftime("%b").upper()], fname)
                        st.success("✅ OK"); st.markdown(f"📂 [Link]({lnk})", unsafe_allow_html=True); st.download_button("📥 Tải về", out, fname)
                    except Exception as e: st.error(f"Lỗi: {e}")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with c_sv:
            st.markdown('<div class="dark-btn">', unsafe_allow_html=True)
            if st.button("💾 LƯU LỊCH SỬ"):
                if cust_name:
                    recs = []
                    for r in st.session_state.quote_df.to_dict('records'):
                        if r["No"] == "TOTAL": continue
                        recs.append({
                            "history_id": f"{cust_name}_{int(time.time())}", "date": datetime.now().strftime("%Y-%m-%d"),
                            "quote_no": quote_no, "customer": cust_name, "item_code": r["Item code"], 
                            "qty": to_float(r["Q'ty"]), "unit_price": to_float(r["Unit price(VND)"]),
                            "total_price_vnd": to_float(r["Total price(VND)"]), "profit_vnd": to_float(r["Profit(VND)"]),
                            "config_data": "{}"
                        })
                    try: supabase.table("crm_shared_history").insert(recs).execute()
                    except: 
                        recs_fix = [{k: v for k, v in x.items() if k != 'config_data'} for x in recs]
                        supabase.table("crm_shared_history").insert(recs_fix).execute()
                    
                    csv = io.BytesIO(); st.session_state.quote_df.to_csv(csv, index=False, encoding='utf-8-sig'); csv.seek(0)
                    lnk, _ = upload_to_drive_structured(csv, ["QUOTATION_HISTORY", cust_name, datetime.now().strftime("%Y"), datetime.now().strftime("%b").upper()], f"HIST_{quote_no}_{cust_name}.csv")
                    st.success("✅ Đã lưu!"); st.markdown(f"📂 [Folder]({lnk})", unsafe_allow_html=True)
                else: st.error("Chọn khách!")
            st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 4: PO ---
with t4:
    if 'po_ncc_df' not in st.session_state: st.session_state.po_ncc_df = pd.DataFrame()
    if 'po_cust_df' not in st.session_state: st.session_state.po_cust_df = pd.DataFrame()
    st.markdown("### 🔎 TRA CỨU ĐƠN HÀNG (PO)")
    search_po = st.text_input("Tìm kiếm PO", key="search_po_tab")
    if search_po:
        df1 = load_data("db_customer_orders"); df2 = load_data("db_supplier_orders")
        if not df1.empty: st.dataframe(df1[df1.astype(str).apply(lambda x: x.str.contains(search_po, case=False)).any(axis=1)], use_container_width=True)
        if not df2.empty: st.dataframe(df2[df2.astype(str).apply(lambda x: x.str.contains(search_po, case=False)).any(axis=1)], use_container_width=True)
    
    c_ncc, c_kh = st.columns(2)
    with c_ncc:
        st.subheader("1. ĐẶT HÀNG NCC")
        if st.button("➕ TẠO MỚI (Đặt NCC)"): st.session_state.po_ncc_df = pd.DataFrame(); st.session_state.show_ncc_upload = True; st.rerun()
        if st.session_state.get('show_ncc_upload'):
            po_s = st.text_input("Số PO NCC"); up_s = st.file_uploader("Upload Excel", key="ups")
            if up_s and st.button("Load"):
                df = pd.read_excel(up_s, dtype=str).fillna("")
                lookup = {(strict_match_key(r['item_code']), strict_match_key(r['item_name']), strict_match_key(r['specs'])): r for r in load_data("crm_purchases").to_dict('records')}
                recs = []
                for i, r in df.iterrows():
                    key = (strict_match_key(r.iloc[1]), strict_match_key(r.iloc[2]), strict_match_key(r.iloc[3]))
                    match = lookup.get(key, {})
                    buy = to_float(match.get('buying_price_rmb', 0)); qty = to_float(r.iloc[4])
                    recs.append({"No": r.iloc[0], "Item code": r.iloc[1], "Item name": r.iloc[2], "Specs": r.iloc[3], "Q'ty": qty,
                                 "Buying price(RMB)": fmt_num(buy), "Total buying price(RMB)": fmt_num(buy*qty), "Exchange rate": match.get('exchange_rate', 0),
                                 "Buying price(VND)": fmt_num(match.get('buying_price_vnd', 0)), "Total buying price(VND)": fmt_num(to_float(match.get('buying_price_vnd', 0))*qty),
                                 "Supplier": match.get('supplier_name', ''), "ETA": calc_eta(datetime.now(), match.get('leadtime', 0))})
                st.session_state.po_ncc_df = pd.DataFrame(recs)
            
            if not st.session_state.po_ncc_df.empty:
                st.dataframe(st.session_state.po_ncc_df, use_container_width=True)
                if st.button("💾 XÁC NHẬN PO NCC"):
                    if po_s:
                        for r in st.session_state.po_ncc_df.to_dict('records'):
                            supabase.table("db_supplier_orders").insert({"po_number": po_s, "supplier": r["Supplier"], "order_date": datetime.now().strftime("%d/%m/%Y"),
                                                                         "item_code": r["Item code"], "qty": to_float(r["Q'ty"]), "total_vnd": to_float(r["Total buying price(VND)"])}).execute()
                        supabase.table("crm_tracking").insert({"po_no": f"{po_s}_{r['Supplier']}", "partner": r["Supplier"], "status": "Ordered", "last_update": datetime.now().strftime("%d/%m/%Y")}).execute()
                        st.success("Đã tạo PO NCC!")
    
    with c_kh:
        st.subheader("2. PO KHÁCH HÀNG")
        if st.button("➕ TẠO MỚI (PO Khách)"): st.session_state.po_cust_df = pd.DataFrame(); st.session_state.show_cust_upload = True; st.rerun()
        if st.session_state.get('show_cust_upload'):
            po_c = st.text_input("Số PO Khách"); cust_name = st.selectbox("Khách", [""] + load_data("crm_customers")['short_name'].tolist())
            up_c = st.file_uploader("Upload Excel", key="upc", accept_multiple_files=True)
            if up_c and st.button("Load PO"):
                recs = []
                price_map = {strict_match_key(h['item_code']): to_float(h['unit_price']) for h in load_data("crm_shared_history").to_dict('records') if h['customer'] == cust_name}
                for f in up_c:
                    try:
                        df = pd.read_excel(f, header=None, skiprows=1, dtype=str).fillna("")
                        for i, r in df.iterrows():
                            unit = price_map.get(strict_match_key(r.iloc[1]), 0); qty = to_float(r.iloc[4])
                            recs.append({"Item code": r.iloc[1], "Item name": r.iloc[2], "Specs": r.iloc[3], "Q'ty": qty, "Unit price(VND)": unit, "Total price(VND)": unit*qty, "ETA": ""})
                    except: pass
                st.session_state.po_cust_df = pd.DataFrame(recs)
            
            if not st.session_state.po_cust_df.empty:
                st.dataframe(st.session_state.po_cust_df, use_container_width=True)
                if st.button("💾 LƯU PO KHÁCH"):
                    if po_c and cust_name:
                        for r in st.session_state.po_cust_df.to_dict('records'):
                            supabase.table("db_customer_orders").insert({"po_number": po_c, "customer": cust_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                                                                         "item_code": r["Item code"], "qty": r["Q'ty"], "total_price": r["Total price(VND)"]}).execute()
                        supabase.table("crm_tracking").insert({"po_no": po_c, "partner": cust_name, "status": "Waiting", "last_update": datetime.now().strftime("%d/%m/%Y")}).execute()
                        st.success("Đã lưu PO Khách!")

# --- TAB 5: TRACKING ---
with t5:
    st.subheader("TRACKING")
    t5_1, t5_2 = st.tabs(["ĐƠN HÀNG", "THANH TOÁN"])
    with t5_1:
        if st.button("Refresh"): st.cache_data.clear(); st.rerun()
        df = load_data("crm_tracking", order_by="id")
        if not df.empty:
            df["Xóa"] = False
            edited = st.data_editor(df[["Xóa", "po_no", "partner", "status", "actual_date", "proof_image"]], 
                                    column_config={"Xóa": st.column_config.CheckboxColumn(default=False), "proof_image": st.column_config.ImageColumn()}, 
                                    use_container_width=True, key="track_ed")
            if st.button("Cập nhật / Xóa"):
                for i, r in edited.iterrows():
                    if r["Xóa"]: supabase.table("crm_tracking").delete().eq("po_no", r["po_no"]).execute()
                    else: supabase.table("crm_tracking").update({"status": r["status"]}).eq("po_no", r["po_no"]).execute()
                st.rerun()
    with t5_2:
        df_pay = load_data("crm_payments")
        if not df_pay.empty:
            df_pay["Xóa"] = False
            edited_p = st.data_editor(df_pay[["Xóa", "po_no", "customer", "invoice_no", "status", "payment_date"]], use_container_width=True, key="pay_ed")
            if st.button("Cập nhật Payment"):
                for i, r in edited_p.iterrows():
                    if r["Xóa"]: supabase.table("crm_payments").delete().eq("po_no", r["po_no"]).execute()
                st.rerun()

# --- TAB 6: MASTER DATA ---
with t6:
    for name, table in [("KHÁCH HÀNG", "crm_customers"), ("NHÀ CUNG CẤP", "crm_suppliers")]:
        st.write(f"### {name}")
        st.data_editor(load_data(table), num_rows="dynamic", use_container_width=True, key=f"md_{table}")
