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
except ImportError:
    st.error("⚠️ Cài đặt: pip install pandas openpyxl supabase google-api-python-client google-auth-oauthlib numpy")
    st.stop()

# =============================================================================
# CẤU HÌNH & VERSION
# =============================================================================
APP_VERSION = "V4842 - FULL MATCHING & PROFIT CALCULATION"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="💰")

# --- CSS ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 20px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 15px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    
    [data-testid="stDataFrame"] > div { height: 800px !important; }
    [data-testid="stDataFrame"] table thead th:first-child { display: none; }
    [data-testid="stDataFrame"] table tbody td:first-child { display: none; }
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

# --- MAPPING ---
MAP_PURCHASE = {
    "itemcode": "item_code", "itemname": "item_name", "specs": "specs", "qty": "qty",
    "buyingpricermb": "buying_price_rmb", "totalbuyingpricermb": "total_buying_price_rmb",
    "exchangerate": "exchange_rate", "buyingpricevnd": "buying_price_vnd",
    "totalbuyingpricevnd": "total_buying_price_vnd", "leadtime": "leadtime",
    "supplier": "supplier_name", "type": "type", "nuoc": "nuoc"
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

def save_data_overwrite(table, df, match_col):
    if df.empty: return
    try:
        all_valid_cols = set(list(MAP_PURCHASE.values()) + list(MAP_MASTER.values()) + 
                             ["image_path", "po_number", "order_date", "price_rmb", "total_rmb", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path",
                              "customer", "unit_price", "total_price", "base_buying_vnd", "full_cost_total",
                              "po_no", "partner", "status", "proof_image", "order_type", "last_update", "finished",
                              "invoice_no", "due_date", "paid_date",
                              "history_id", "date", "quote_no", "ap_price", "ap_total_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"])
        
        recs = df.to_dict(orient='records')
        clean_recs = []
        codes_to_del = []
        
        for r in recs:
            clean = {k: safe_str(v) for k,v in r.items() if k in all_valid_cols}
            if clean: 
                clean_recs.append(clean)
                if match_col in clean and clean[match_col]: codes_to_del.append(clean[match_col])
        
        if codes_to_del:
            chunk_size = 500
            for i in range(0, len(codes_to_del), chunk_size):
                supabase.table(table).delete().in_(match_col, codes_to_del[i:i+chunk_size]).execute()
        
        if clean_recs:
            chunk_size = 500
            for i in range(0, len(clean_recs), chunk_size):
                supabase.table(table).insert(clean_recs[i:i+chunk_size]).execute()
            
        st.cache_data.clear()
    except Exception as e: st.error(f"❌ Lưu Lỗi: {e}")

# --- LOGIC MATCHING ĐƠN GIẢN ---
def run_simple_matching(rfq_file, db_df):
    lookup = {}
    for _, row in db_df.iterrows():
        code_key = clean_key(row.get('item_code'))
        if code_key:
            lookup[code_key] = {
                'price_rmb': to_float(row.get('buying_price_rmb')),
                'rate': to_float(row.get('exchange_rate')),
                'lead': safe_str(row.get('leadtime')),
                'supp': safe_str(row.get('supplier_name')),
                'img': safe_str(row.get('image_path')),
                'type': safe_str(row.get('type')),
                'nuoc': safe_str(row.get('nuoc'))
            }

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

        info = lookup.get(clean_key(code))
        if not info:
            info = {'price_rmb': 0, 'rate': 0, 'lead': '', 'supp': '', 'img': '', 'type': '', 'nuoc': ''}
        
        rmb = info['price_rmb']
        rate = info['rate'] if info['rate'] > 0 else 4000
        
        # Thêm các cột cho tính toán lợi nhuận
        row_res = {
            "No": no, "Item code": code, "Item name": name, "Specs": specs, "Q'ty": fmt_num(qty_val),
            "Buying price (RMB)": fmt_num(rmb),
            "Total buying price (RMB)": fmt_num(rmb * qty_val),
            "Exchange rate": fmt_num(rate),
            "Buying price (VND)": fmt_num(rmb * rate),
            "Total buying price (VND)": fmt_num(rmb * qty_val * rate),
            "Leadtime": info['lead'], "Supplier": info['supp'], "Images": info['img'],
            "Type": info['type'], "N/U/O/C": info['nuoc'],
            
            # CÁC CỘT TÍNH LỢI NHUẬN (MẶC ĐỊNH 0)
            "Unit Price (Sell)": "0", "Total Sell": "0", "Gap": "0", "Profit": "0",
            "End User Val": "0", "Buyer Val": "0", "Tax Val": "0", "VAT Val": "0", 
            "Mgmt Val": "0", "Trans Val": "0"
        }
        results.append(row_res)
        
    return pd.DataFrame(results)

# --- INIT STATE ---
if 'init' not in st.session_state:
    st.session_state.init = True
    st.session_state.quote_result = pd.DataFrame()
    st.session_state.temp_supp = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "supplier"])
    st.session_state.temp_cust = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "unit_price", "total_price", "customer"])
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: 
        if f"pct_{k}" not in st.session_state: st.session_state[f"pct_{k}"] = "0"

# --- UI ---
st.title("HỆ THỐNG CRM QUẢN LÝ (FULL CLOUD)")
is_admin = (st.sidebar.text_input("Admin Password", type="password") == "admin")

t1, t2, t3, t4, t5, t6 = st.tabs(["DASHBOARD", "KHO HÀNG (PURCHASES)", "BÁO GIÁ (QUOTES)", "ĐƠN HÀNG (PO)", "TRACKING", "DỮ LIỆU NỀN"])

# --- TAB 1 ---
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
        
        st.divider()
        c4, c5, c6, c7 = st.columns(4)
        with c4: st.markdown(f"<div class='card-3d bg-ncc'><div>ĐƠN ĐẶT NCC</div><h3>{len(track[track['order_type']=='NCC']) if not track.empty else 0}</h3></div>", unsafe_allow_html=True)
        with c5: st.markdown(f"<div class='card-3d bg-recv'><div>ĐƠN KHÁCH</div><h3>{len(db_cust['po_number'].unique()) if not db_cust.empty else 0}</h3></div>", unsafe_allow_html=True)
        with c6: st.markdown(f"<div class='card-3d bg-del'><div>ĐÃ GIAO</div><h3>{len(track[(track['order_type']=='KH') & (track['status']=='Đã giao hàng')]) if not track.empty else 0}</h3></div>", unsafe_allow_html=True)
        with c7: st.markdown(f"<div class='card-3d bg-pend'><div>CHỜ GIAO</div><h3>{len(db_cust['po_number'].unique()) - len(track[(track['order_type']=='KH') & (track['status']=='Đã giao hàng')]) if not db_cust.empty else 0}</h3></div>", unsafe_allow_html=True)

# --- TAB 2 ---
with t2:
    purchases_df = load_data("crm_purchases")
    c1, c2 = st.columns([1, 3])
    with c1:
        st.info("Import file BUYING PRICE-ALL.xlsx")
        up_file = st.file_uploader("Chọn file Excel", type=["xlsx"], key="up_pur")
        if up_file and st.button("🚀 IMPORT & TÍNH TOÁN"):
            try:
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
                
                save_data_overwrite("crm_purchases", pd.DataFrame(rows), match_col='item_code')
                st.success(f"✅ Đã import {len(rows)} mã hàng!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi Import: {e}")
            
        st.divider()
        up_img = st.file_uploader("Update Image", type=["png","jpg"], key="up_img_man")
        code = st.text_input("Item Code")
        if st.button("Upload") and up_img and code:
            url = upload_to_drive(up_img, "CRM_PURCHASE_IMAGES", f"IMG_{safe_filename(code)}.png")
            supabase.table("crm_purchases").update({"image_path": url}).eq("item_code", code).execute()
            st.success("Uploaded!"); st.rerun()

    with c2:
        search = st.text_input("Search", key="search_pur")
        view = purchases_df.copy()
        if search:
            mask = view.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
            view = view[mask]
        st.dataframe(view, column_config={"image_path": st.column_config.ImageColumn("Hình ảnh")}, use_container_width=True, height=800)

# --- TAB 3: QUOTES & PROFIT ---
with t3:
    st.subheader("BÁO GIÁ & TÍNH LỢI NHUẬN")
    
    # 1. INPUT PARAMS (GLOBAL BUTTONS) - PHỤC HỒI
    st.write("CẤU HÌNH TÍNH TOÁN (%)")
    cols = st.columns(7)
    pct_inputs = {}
    labels = ["END USER(%)", "BUYER(%)", "TAX(%)", "VAT(%)", "PAYBACK(%)", "MGMT(%)", "TRANS(VND)"]
    keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
    
    for i, (label, key) in enumerate(zip(labels, keys)):
        val = st.session_state.get(f"pct_{key}", "0")
        pct_inputs[key] = cols[i].text_input(label, val)
        st.session_state[f"pct_{key}"] = pct_inputs[key] # Lưu lại state

    st.divider()

    # 2. UPLOAD & MATCHING
    col_up, col_act = st.columns([1, 2])
    with col_up:
        up_rfq = st.file_uploader("Upload 'RFQ-38 FROM ALL.xlsx'", type=["xlsx"], key="up_rfq")
    
    with col_act:
        st.write(""); st.write("")
        if up_rfq and st.button("🚀 BƯỚC 1: LẤY GIÁ VỐN (MATCHING)"):
            if purchases_df.empty:
                st.error("Chưa có dữ liệu Kho (Tab 2).")
            else:
                try:
                    st.session_state.quote_result = run_simple_matching(up_rfq, purchases_df)
                    st.success("Đã lấy được giá vốn! Hãy nhập Giá Bán bên dưới rồi nhấn Tính Lợi Nhuận.")
                except Exception as e: st.error(f"Lỗi: {e}")

    # 3. HIỂN THỊ & TÍNH TOÁN
    if 'quote_result' in st.session_state and not st.session_state.quote_result.empty:
        st.write("### BẢNG TÍNH GIÁ")
        
        # Nút tính lợi nhuận
        if st.button("🔄 BƯỚC 2: TÍNH LỢI NHUẬN (APPLY %)"):
            df = st.session_state.quote_result
            
            p_end = to_float(st.session_state.pct_end)/100
            p_buy = to_float(st.session_state.pct_buy)/100
            p_tax = to_float(st.session_state.pct_tax)/100
            p_vat = to_float(st.session_state.pct_vat)/100
            p_pay = to_float(st.session_state.pct_pay)/100
            p_mgmt = to_float(st.session_state.pct_mgmt)/100
            trans = to_float(st.session_state.pct_trans)
            
            for i, r in df.iterrows():
                qty = to_float(r["Q'ty"])
                buy_total = to_float(r["Total buying price (VND)"])
                
                # Lấy giá bán từ bảng (người dùng nhập)
                unit_sell = to_float(r.get("Unit Price (Sell)", 0))
                total_sell = unit_sell * qty
                
                gap = total_sell - buy_total
                gap_share = gap * 0.6 if gap > 0 else 0 # GAP 60%
                
                # Tính chi phí dựa trên Giá Bán (Revenue) hoặc Gap tùy logic
                # Ở đây áp dụng logic phổ biến: % trên Doanh thu
                v_end = total_sell * p_end
                v_buy = total_sell * p_buy
                v_tax = total_sell * p_tax
                v_vat = total_sell * p_vat
                v_mgmt = total_sell * p_mgmt
                v_trans = trans * qty
                
                # Tổng chi phí (Theo yêu cầu: Gap*60% + các loại phí)
                total_ops = gap_share + v_end + v_buy + v_tax + v_vat + v_mgmt + v_trans
                
                profit = gap - total_ops
                
                # Cập nhật lại DataFrame
                df.at[i, "Total Sell"] = fmt_num(total_sell)
                df.at[i, "Gap"] = fmt_num(gap)
                df.at[i, "Profit"] = fmt_num(profit)
                df.at[i, "End User Val"] = fmt_num(v_end)
                df.at[i, "Buyer Val"] = fmt_num(v_buy)
                # ... Cập nhật các cột khác nếu cần hiển thị
            
            st.session_state.quote_result = df
            st.success("Đã tính toán xong!")

        # Bảng dữ liệu (Cho phép sửa Giá Bán)
        edited_quote = st.data_editor(
            st.session_state.quote_result,
            column_config={
                "Images": st.column_config.ImageColumn("Hình ảnh", width="small"),
                "Buying price (RMB)": st.column_config.TextColumn("Giá Vốn RMB", disabled=True),
                "Buying price (VND)": st.column_config.TextColumn("Giá Vốn VND", disabled=True),
                "Unit Price (Sell)": st.column_config.TextColumn("GIÁ BÁN (VND)", required=True), # Cột quan trọng để nhập
                "Total Sell": st.column_config.TextColumn("Thành Tiền Bán", disabled=True),
                "Profit": st.column_config.TextColumn("LỢI NHUẬN", disabled=True),
            },
            use_container_width=True,
            height=600,
            num_rows="dynamic"
        )
        
        # Cập nhật lại session state khi edit
        if not edited_quote.equals(st.session_state.quote_result):
            st.session_state.quote_result = edited_quote

        csv = edited_quote.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Tải kết quả (CSV)", csv, "RFQ_Result.csv", "text/csv")
        
        if st.button("💾 Lưu vào Lịch sử"):
            to_save = edited_quote.copy()
            rename_map = {
                "Item code": "item_code", "Item name": "item_name", "Specs": "specs", "Q'ty": "qty",
                "Buying price (RMB)": "buying_price_rmb", "Total buying price (RMB)": "total_buying_price_rmb",
                "Exchange rate": "exchange_rate", "Buying price (VND)": "buying_price_vnd",
                "Total buying price (VND)": "total_buying_price_vnd", "Leadtime": "leadtime",
                "Supplier": "supplier_name", "Images": "image_path",
                "Unit Price (Sell)": "unit_price", "Total Sell": "total_price_vnd", "Profit": "profit_vnd"
            }
            to_save = to_save.rename(columns=rename_map)
            to_save["history_id"] = f"QUOTE_{int(time.time())}"
            to_save["date"] = datetime.now().strftime("%d/%m/%Y")
            save_data_overwrite("crm_shared_history", to_save, "history_id")
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
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "price_rmb": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_supp = pd.DataFrame(recs)
        
        ed_s = st.data_editor(st.session_state.temp_supp, num_rows="dynamic", use_container_width=True, key="editor_po_supp", hide_index=True)
        if st.button("Save PO NCC"):
            s_data = ed_s.copy()
            s_data['po_number'] = po_s; s_data['supplier'] = sup; s_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data_overwrite("db_supplier_orders", s_data, "id")
            save_data_overwrite("crm_tracking", pd.DataFrame([{"po_no": po_s, "partner": sup, "status": "Ordered", "order_type": "NCC"}]), "po_no")
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
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "unit_price": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_cust = pd.DataFrame(recs)
            
        ed_c = st.data_editor(st.session_state.temp_cust, num_rows="dynamic", use_container_width=True, key="editor_po_cust", hide_index=True)
        if st.button("Save PO Cust"):
            c_data = ed_c.copy()
            c_data['po_number'] = po_c; c_data['customer'] = cus; c_data['order_date'] = datetime.now().strftime("%d/%m/%Y")
            save_data_overwrite("db_customer_orders", c_data, "id")
            save_data_overwrite("crm_tracking", pd.DataFrame([{"po_no": po_c, "partner": cus, "status": "Waiting", "order_type": "KH"}]), "po_no")
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
                save_data_overwrite("crm_tracking", ed_t, "po_no")
                for i, r in ed_t.iterrows():
                    if r['status'] == 'Delivered' and r['order_type'] == 'KH':
                        save_data_overwrite("crm_payment", pd.DataFrame([{"po_no": r['po_no'], "customer": r['partner'], "status": "Pending"}]), "po_no")
                st.success("Updated")
            
            pk = st.text_input("Proof for PO")
            prf = st.file_uploader("Proof Img", accept_multiple_files=True, key="up_proof")
            if st.button("Upload Proof") and pk and prf:
                urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"PRF_{pk}_{f.name}") for f in prf]
                if urls: supabase.table("crm_tracking").update({"proof_image": urls[0]}).eq("po_no", pk).execute()
                st.success("Uploaded")

    with c2:
        st.subheader("Payment")
        if not payment_df.empty:
            ed_p = st.data_editor(payment_df, key="editor_payment_main", height=600, hide_index=True)
            if st.button("Update Payment"):
                save_data_overwrite("crm_payment", ed_p, "po_no")
                st.success("Updated")

# --- TAB 6: MASTER DATA ---
with t6:
    if is_admin:
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
                save_data_overwrite("crm_customers", pd.DataFrame(rows), "short_name")
                st.success("Imported"); st.rerun()
            
            ed_k = st.data_editor(customers_df, num_rows="dynamic", key="editor_master_cust", height=600, hide_index=True)
            if st.button("Save Cust"): save_data_overwrite("crm_customers", ed_k, "short_name"); st.success("OK")

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
                save_data_overwrite("crm_suppliers", pd.DataFrame(rows), "short_name")
                st.success("Imported"); st.rerun()
            
            ed_s = st.data_editor(suppliers_df, num_rows="dynamic", key="editor_master_supp", height=600, hide_index=True)
            if st.button("Save Supp"): save_data_overwrite("crm_suppliers", ed_s, "short_name"); st.success("OK")
    else: st.warning("Admin Only")
