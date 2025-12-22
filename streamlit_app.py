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
APP_VERSION = "V6002 - FIX MATCHING PRICE"
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
    from openpyxl import load_workbook
    from openpyxl.styles import Border, Side
except ImportError:
    st.error("⚠️ Thiếu thư viện. Vui lòng cài: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl")
    st.stop()

# CONNECT SERVER
try:
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

def upload_to_drive(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        q_f = f"'{ROOT_FOLDER_ID}' in parents and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if folders: folder_id = folders[0]['id']
        else:
            folder_id = srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
            srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

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

def fmt_num(x): return "{:,.0f}".format(x) if x else "0"

# --- FIX QUAN TRỌNG: SỬA HÀM CLEAN KEY ĐỂ HỖ TRỢ TIẾNG VIỆT ---
def clean_key(s): 
    # Chỉ lowercase và strip, KHÔNG dùng regex xóa ký tự lạ để giữ tiếng Việt
    return safe_str(s).lower()

def normalize_header(h): return re.sub(r'[^a-zA-Z0-9]', '', str(h).lower())

def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                top_left = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                top_left.value = value
                return
        cell.value = value
    except Exception:
        pass

def load_data(table, order_by="id", ascending=True):
    try:
        query = supabase.table(table).select("*")
        if table == "crm_purchases":
            query = query.order("row_order", desc=False)
        else:
            query = query.order(order_by, desc=not ascending)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if table != "crm_tracking" and not df.empty and 'id' in df.columns: 
            df = df.drop(columns=['id'])
        return df
    except: return pd.DataFrame()

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper()
    s = s.replace(",", ".") 
    s = s.replace("%", "/100")
    s = s.replace("X", "*")
    if s.startswith("="): s = s[1:]
    s = s.replace("BUYING PRICE", str(buying_price))
    s = s.replace("BUY", str(buying_price))
    s = s.replace("AP PRICE", str(ap_price))
    s = s.replace("AP", str(ap_price))
    s = re.sub(r'[^0-9.+\-*/()]', '', s)
    try: return float(eval(s))
    except: return 0.0

# LOGIC TÍNH TOÁN CORE
def recalculate_quote_logic(df, params):
    cols_to_num = ["Q'ty", "Buying price(VND)", "Buying price(RMB)", "AP price(VND)", "Unit price(VND)"]
    for c in cols_to_num:
        if c in df.columns:
            df[c] = df[c].apply(to_float)
    
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

MAP_PURCHASE = {
    "item_code": ["Item code", "Mã hàng", "Code", "Mã"], 
    "item_name": ["Item name", "Tên hàng", "Name", "Tên"],
    "specs": ["Specs", "Quy cách", "Thông số"], 
    "qty": ["Q'ty", "Qty", "Số lượng"],
    "buying_price_rmb": ["Buying price (RMB)", "Giá RMB", "Buying RMB"], 
    "exchange_rate": ["Exchange rate", "Tỷ giá"],
    "buying_price_vnd": ["Buying price (VND)", "Giá VND", "Buying VND"], 
    "leadtime": ["Leadtime", "Thời gian giao hàng"],
    "supplier_name": ["Supplier", "Nhà cung cấp"], 
    "image_path": ["image_path", "Hình ảnh", "Ảnh"], 
    "type": ["Type", "Loại"], 
    "nuoc": ["NUOC", "Nước"]
}

# =============================================================================
# 3. GIAO DIỆN CHÍNH
# =============================================================================
t1, t2, t3, t4, t5, t6 = st.tabs(["📊 DASHBOARD", "📦 KHO HÀNG", "💰 BÁO GIÁ", "📑 QUẢN LÝ PO", "🚚 TRACKING", "⚙️ MASTER DATA"])

# --- TAB 1: DASHBOARD ---
with t1:
    if st.button("🔄 REFRESH"): st.cache_data.clear(); st.rerun()
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
    c_imp, c_view = st.columns([1, 2])
    
    with c_imp:
        with st.expander("🛠️ Admin Reset Database"):
            adm_pass = st.text_input("Admin Password", type="password")
            if st.button("⚠️ XÓA SẠCH KHO HÀNG"):
                if adm_pass == "admin":
                    supabase.table("crm_purchases").delete().neq("id", 0).execute()
                    st.success("Đã xóa sạch!"); time.sleep(1); st.rerun()
                else: st.error("Sai mật khẩu!")
        
        st.divider()
        st.write("📥 **Import / Ghi đè (Smart Upsert)**")
        up_file = st.file_uploader("Upload File Excel (Đảm bảo đủ dòng)", type=["xlsx"])
        
        if up_file and st.button("🚀 Import"):
            try:
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                img_map = {}
                for image in getattr(ws, '_images', []):
                    row = image.anchor._from.row + 1
                    buf = io.BytesIO(image._data())
                    fname = f"IMG_R{row}_{int(time.time())}.png"
                    link, _ = upload_to_drive(buf, "CRM_PRODUCT_IMAGES", fname)
                    img_map[row] = link
                
                df = pd.read_excel(up_file, dtype=str).fillna("")
                hn = {normalize_header(c): c for c in df.columns}
                
                records = []
                prog = st.progress(0)
                
                for i, r in df.iterrows():
                    d = {}
                    for db_col, list_ex in MAP_PURCHASE.items():
                        val = ""
                        for kw in list_ex:
                            if normalize_header(kw) in hn:
                                val = safe_str(r[hn[normalize_header(kw)]])
                                break
                        d[db_col] = val
                    
                    if not d.get('image_path'): d['image_path'] = img_map.get(i+2, "")
                    d['row_order'] = i + 1 
                    
                    qty = to_float(d.get('qty', 0))
                    p_rmb = to_float(d.get('buying_price_rmb', 0))
                    p_vnd = to_float(d.get('buying_price_vnd', 0))
                    
                    d['qty'] = qty
                    d['buying_price_rmb'] = p_rmb
                    d['buying_price_vnd'] = p_vnd
                    d['total_buying_price_rmb'] = p_rmb * qty
                    d['total_buying_price_vnd'] = p_vnd * qty
                    
                    if d.get('item_code'):
                        records.append(d)
                    prog.progress((i + 1) / len(df))

                if records:
                    chunk_ins = 100
                    for k in range(0, len(records), chunk_ins):
                        batch = records[k:k+chunk_ins]
                        try:
                            supabase.table("crm_purchases").upsert(batch, on_conflict="item_code").execute()
                        except:
                             codes = [b['item_code'] for b in batch]
                             supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                             supabase.table("crm_purchases").insert(batch).execute()
                    st.success(f"✅ Import thành công {len(records)} dòng!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")

    with c_view:
        df_pur = load_data("crm_purchases", order_by="row_order")
        search = st.text_input("Tìm kiếm...", key="search_pur")
        st.caption(f"Tổng số item hiện có: {len(df_pur)}")
        if not df_pur.empty:
            if search:
                mask = df_pur.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
                df_pur = df_pur[mask]
            st.dataframe(df_pur, column_config={"image_path": st.column_config.ImageColumn("Ảnh")}, use_container_width=True, height=600)

# --- TAB 3: BÁO GIÁ (ĐÃ FIX MATCHING) ---
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

    # --- LOGIC MATCHING ĐÃ SỬA ---
    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        db = load_data("crm_purchases")
        
        if db.empty: st.error("Kho rỗng!")
        else:
            # Tạo Dictionary tra cứu (Dùng hàm clean_key mới hỗ trợ tiếng Việt)
            lookup_code = {clean_key(r['item_code']): r for r in db.to_dict('records')}
            lookup_name = {clean_key(r['item_name']): r for r in db.to_dict('records')}
            
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            hn = {normalize_header(c): c for c in df_rfq.columns}
            
            for i, r in df_rfq.iterrows():
                code_excel = safe_str(r.get(hn.get("itemcode") or hn.get("code") or hn.get("mã") or hn.get("ma")))
                name_excel = safe_str(r.get(hn.get("itemname") or hn.get("name") or hn.get("tên")))
                specs_excel = safe_str(r.get(hn.get("specs") or hn.get("quycach")))
                qty = to_float(r.get(hn.get("qty") or hn.get("q'ty") or hn.get("quantity") or hn.get("soluong") or hn.get("sốlượng")))
                if qty == 0: qty = 1.0 

                match = None
                # 1. Tra cứu theo Code
                if code_excel:
                    match = lookup_code.get(clean_key(code_excel))
                # 2. Tra cứu theo Name (nếu không có Code)
                if not match and name_excel:
                    match = lookup_name.get(clean_key(name_excel))
                
                # Lấy dữ liệu (Nếu tìm thấy)
                if match:
                    # Đảm bảo lấy đúng tên cột trong DB
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
                    # Nếu không tìm thấy
                    buy_rmb = 0; buy_vnd = 0; ex_rate = 0
                    final_code = code_excel # Giữ nguyên cái user nhập để biết
                    final_name = name_excel
                    final_specs = specs_excel
                    supplier = ""; image = ""; leadtime = ""

                item = {
                    "No": i+1,
                    "Cảnh báo": "",
                    "Item code": final_code,
                    "Item name": final_name,
                    "Specs": final_specs,
                    "Q'ty": qty, 
                    "Buying price(RMB)": fmt_num(buy_rmb),
                    "Total buying price(rmb)": fmt_num(buy_rmb * qty),
                    "Exchange rate": fmt_num(ex_rate),
                    "Buying price(VND)": fmt_num(buy_vnd),
                    "Total buying price(VND)": fmt_num(buy_vnd * qty),
                    "AP price(VND)": "0", "AP total price(VND)": "0",
                    "Unit price(VND)": "0", "Total price(VND)": "0",
                    "GAP": "0", "End user(%)": "0", "Buyer(%)": "0",
                    "Import tax(%)": "0", "VAT": "0", "Transportation": "0",
                    "Management fee(%)": "0", "Payback(%)": "0",
                    "Profit(VND)": "0", "Profit(%)": "0%",
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

        low_profits = st.session_state.quote_df[st.session_state.quote_df["Cảnh báo"] == "⚠️ LOW"]
        if not low_profits.empty: st.error(f"⚠️ CÓ {len(low_profits)} MỤC LỢI NHUẬN THẤP (<10%)")

        st.divider()
        c_rev, c_sv, c_exp = st.columns([1, 1, 1])
        with c_rev:
            if st.button("🔍 REVIEW BÁO GIÁ"): st.session_state.show_review = True
        
        if st.session_state.get('show_review', False):
            st.write("### 📋 BẢNG REVIEW TRƯỚC KHI XUẤT")
            cols_review = ["No", "Item code", "Item name", "Specs", "Q'ty", "Unit price(VND)", "Total price(VND)", "Leadtime"]
            valid_cols = [c for c in cols_review if c in st.session_state.quote_df.columns]
            st.dataframe(st.session_state.quote_df[valid_cols], use_container_width=True)
            
            if st.button("📤 XUẤT FILE BÁO GIÁ (EXCEL)"):
                tmps = load_data("crm_templates")
                aaa_temp = tmps[tmps['template_name'].str.contains("AAA-QUOTATION", case=False, na=False)]
                if aaa_temp.empty: st.error("⚠️ Thiếu template 'AAA-QUOTATION'!")
                else:
                    fid = aaa_temp.iloc[0]['file_id']
                    bio = download_from_drive(fid)
                    if bio:
                        try:
                            wb = load_workbook(bio); ws = wb.active
                            safe_write_merged(ws, 5, 2, cust_name)
                            safe_write_merged(ws, 5, 7, quote_no)
                            safe_write_merged(ws, 6, 7, datetime.now().strftime("%d/%m/%Y"))
                            
                            thin = Side(border_style="thin", color="000000")
                            border = Border(top=thin, left=thin, right=thin, bottom=thin)
                            
                            start_row = 10
                            for idx, r in st.session_state.quote_df.iterrows():
                                current_row = start_row + idx
                                safe_write_merged(ws, current_row, 1, r["No"])
                                ws.cell(row=current_row, column=1).border = border
                                safe_write_merged(ws, current_row, 3, r["Item code"])
                                ws.cell(row=current_row, column=3).border = border
                                safe_write_merged(ws, current_row, 4, r["Item name"])
                                ws.cell(row=current_row, column=4).border = border
                                safe_write_merged(ws, current_row, 5, r["Specs"])
                                ws.cell(row=current_row, column=5).border = border
                                safe_write_merged(ws, current_row, 6, to_float(r["Q'ty"]))
                                ws.cell(row=current_row, column=6).border = border
                                safe_write_merged(ws, current_row, 7, to_float(r["Unit price(VND)"]))
                                ws.cell(row=current_row, column=7).border = border
                                safe_write_merged(ws, current_row, 8, to_float(r["Total price(VND)"]))
                                ws.cell(row=current_row, column=8).border = border
                                
                            if not st.session_state.quote_df.empty:
                                lt_val = st.session_state.quote_df.iloc[0]["Leadtime"]
                                safe_write_merged(ws, 8, 8, lt_val)

                            out = io.BytesIO(); wb.save(out)
                            st.download_button("⬇️ TẢI FILE BÁO GIÁ", out.getvalue(), f"Quote_{quote_no}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        except Exception as e: st.error(f"Lỗi Xuất: {e}")

        with c_sv:
            if st.button("💾 LƯU LỊCH SỬ"):
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
                    supabase.table("crm_shared_history").insert(recs).execute(); st.success("Saved!")
                else: st.error("Chọn khách!")

# --- TAB 4: PO ---
with t4:
    c_ncc, c_kh = st.columns(2)
    with c_ncc:
        st.subheader("PO NHÀ CUNG CẤP")
        po_s_no = st.text_input("Số PO NCC"); 
        supps = load_data("crm_suppliers")
        s_name = st.selectbox("Chọn NCC", [""] + supps['short_name'].tolist() if not supps.empty else [])
        up_s = st.file_uploader("Upload PO NCC", key="ups")
        if up_s:
            dfs = pd.read_excel(up_s, dtype=str).fillna("")
            if st.button("Lưu PO NCC"):
                recs = []
                for i, r in dfs.iterrows():
                    recs.append({"po_number": po_s_no, "supplier": s_name, "order_date": datetime.now().strftime("%d/%m/%Y"), "item_code": safe_str(r.iloc[1]), "qty": to_float(r.iloc[4]), "total_vnd": to_float(r.iloc[6])})
                supabase.table("db_supplier_orders").insert(recs).execute()
                supabase.table("crm_tracking").insert([{"po_no": po_s_no, "partner": s_name, "status": "Ordered", "order_type": "NCC", "last_update": datetime.now().strftime("%d/%m/%Y")}]).execute()
                st.success("OK")
    with c_kh:
        st.subheader("PO KHÁCH HÀNG")
        po_c_no = st.text_input("Số PO Khách"); 
        custs = load_data("crm_customers")
        c_name = st.selectbox("Chọn Khách", [""] + custs['short_name'].tolist() if not custs.empty else [])
        up_c = st.file_uploader("Upload PO KH", key="upc")
        if up_c:
            dfc = pd.read_excel(up_c, dtype=str).fillna("")
            if st.button("Lưu PO KH"):
                recs = []
                for i, r in dfc.iterrows():
                    recs.append({"po_number": po_c_no, "customer": c_name, "order_date": datetime.now().strftime("%d/%m/%Y"), "item_code": safe_str(r.iloc[1]), "qty": to_float(r.iloc[4]), "total_price": to_float(r.iloc[6])})
                supabase.table("db_customer_orders").insert(recs).execute()
                supabase.table("crm_tracking").insert([{"po_no": po_c_no, "partner": c_name, "status": "Waiting", "order_type": "KH", "last_update": datetime.now().strftime("%d/%m/%Y")}]).execute()
                st.success("OK")

# --- TAB 5: TRACKING ---
with t5:
    st.subheader("TRACKING")
    df_track = load_data("crm_tracking", order_by="id")
    if not df_track.empty:
        c1, c2 = st.columns(2)
        po = c1.selectbox("Chọn PO Proof", df_track['po_no'].unique())
        img = c2.file_uploader("Proof Image", type=['png','jpg'])
        if c2.button("Update Proof"):
            lnk, _ = upload_to_drive(img, "CRM_PROOF", f"PRF_{po}.png")
            supabase.table("crm_tracking").update({"proof_image": lnk}).eq("po_no", po).execute()
            st.success("Uploaded!")
        
        edited_df = st.data_editor(
            df_track, column_config={
                "proof_image": st.column_config.ImageColumn("Proof"), 
                "status": st.column_config.SelectboxColumn("Status", options=["Ordered", "Waiting", "Delivered"])
            }, use_container_width=True, key="ed_tr"
        )
        if st.button("💾 LƯU THAY ĐỔI TRACKING"):
            recs = edited_df.to_dict('records')
            prog = st.progress(0)
            for idx, row in enumerate(recs):
                supabase.table("crm_tracking").update({
                    "status": row['status'], "last_update": datetime.now().strftime("%d/%m/%Y")
                }).eq("po_no", row['po_no']).execute()
                prog.progress((idx+1)/len(recs))
            st.success("Updated!"); time.sleep(1); st.rerun()

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
            lnk, fid = upload_to_drive(up_t, "CRM_TEMPLATES", f"TMP_{t_name}.xlsx")
            if fid: supabase.table("crm_templates").insert([{"template_name": t_name, "file_id": fid, "last_updated": datetime.now().strftime("%d/%m/%Y")}]).execute(); st.success("OK"); st.rerun()
        st.dataframe(load_data("crm_templates"))
