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

# --- 1. THƯ VIỆN & KẾT NỐI ---
try:
    from openpyxl import load_workbook
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
except ImportError:
    st.error("⚠️ Cài đặt thư viện: pip install pandas openpyxl supabase google-api-python-client google-auth-oauthlib")
    st.stop()

APP_VERSION = "V4808 - FULL CLOUD (STRICT OVERWRITE + MULTI-USER)"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 18px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 10px; padding: 15px; color: white; text-align: center; margin-bottom: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); } 
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); } 
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); } 
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    </style>""", unsafe_allow_html=True)

# --- CONFIG ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi Config: {e}")
    st.stop()

# --- GOOGLE DRIVE ---
def get_drive_service():
    try:
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], 
                            client_secret=OAUTH_INFO["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

def upload_to_drive(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return ""
    try:
        # Tìm/Tạo Folder
        q_folder = f"'{ROOT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_folder, fields="files(id)").execute().get('files', [])
        if folders: folder_id = folders[0]['id']
        else:
            folder_id = srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
            srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        # Kiểm tra file trùng để Ghi Đè (Overwrite)
        q_file = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        existing = srv.files().list(q=q_file, fields='files(id)').execute().get('files', [])
        
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        
        if existing:
            file_id = existing[0]['id']
            srv.files().update(fileId=file_id, media_body=media, fields='id').execute() # GHI ĐÈ
        else:
            file_id = srv.files().create(body={'name': file_name, 'parents': [folder_id]}, media_body=media, fields='id').execute()['id']
            try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            except: pass
            
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    except Exception as e: print(f"Upload Err: {e}"); return ""

# --- HELPERS ---
def safe_str(val): return str(val).strip() if val is not None and str(val).lower() not in ['nan', 'none', 'null', ''] else ""
def safe_filename(s): return re.sub(r'[^\w\-_]', '_', unicodedata.normalize('NFKD', safe_str(s)).encode('ascii', 'ignore').decode('utf-8')).strip('_')
def to_float(val):
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "")
    try: return max([float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", s)])
    except: return 0.0
def fmt_num(x): return "{:,.0f}".format(float(x)) if x else "0"
def clean_lookup_key(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()
def parse_formula(formula, buying, ap):
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying)).replace("BUY", str(buying)).replace("AP PRICE", str(ap)).replace("AP", str(ap))
    try: return float(eval(re.sub(r'[^0-9.+\-*/()]', '', expr)))
    except: return 0.0

# --- DATA MAPPING (EXCEL -> DB) ---
# Map đúng cột trong file Excel của bạn sang DB
PURCHASE_MAP = {
    "Item code": "item_code", "Item name": "item_name", "Specs": "specs", "Q'ty": "qty",
    "Buying price\n(RMB)": "buying_price_rmb", "Total buying price\n(RMB)": "total_buying_price_rmb",
    "Exchange rate": "exchange_rate", "Buying price\n(VND)": "buying_price_vnd",
    "Total buying price\n(VND)": "total_buying_price_vnd", "Leadtime": "leadtime",
    "Supplier": "supplier_name", "Type": "type", "N/U/O/C": "nuoc"
}
CUSTOMER_MAP = {
    "short_name": "short_name", "eng_name": "eng_name", "vn_name": "vn_name",
    "address_1": "address_1", "address_2": "address_2", "contact_person": "contact_person",
    "director": "director", "phone": "phone", "fax": "fax", "tax_code": "tax_code",
    "destination": "destination", "payment_term": "payment_term"
}

# --- DB FUNCTIONS ---
def load_data(table):
    try:
        # Load dữ liệu từ Supabase (Stateless cho 100 User)
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        if not df.empty and 'no' not in df.columns: 
            df.insert(0, 'no', range(1, len(df)+1)) # Tạo cột STT ảo
        return df
    except: return pd.DataFrame()

def save_data(table, df, unique_key=None):
    if df.empty: return
    try:
        # WHITELIST: Chỉ cho phép các cột chuẩn đi qua, lọc bỏ rác
        WHITELIST = {
            "crm_purchases": ["item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc", "_clean_code", "_clean_specs", "_clean_name"],
            "crm_customers": list(CUSTOMER_MAP.values()),
            "crm_suppliers": list(CUSTOMER_MAP.values()),
            "db_supplier_orders": ["po_number", "order_date", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "pdf_path"],
            "db_customer_orders": ["po_number", "order_date", "customer", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "base_buying_vnd", "full_cost_total", "pdf_path"],
            "crm_tracking": ["po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"],
            "crm_payment": ["po_no", "customer", "invoice_no", "status", "due_date", "paid_date"],
            "crm_shared_history": ["history_id", "date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime", "pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
        }
        
        valid_cols = WHITELIST.get(table, df.columns.tolist())
        recs = df.to_dict(orient='records')
        clean_recs = []
        for r in recs:
            # Ép kiểu string cho tất cả để tránh lỗi format
            clean_r = {k: str(v) if v is not None and str(v)!='nan' else None for k, v in r.items() if k in valid_cols}
            if clean_r: clean_recs.append(clean_r)
            
        if unique_key:
            # GHI ĐÈ (Upsert) dựa trên khóa duy nhất (ví dụ item_code)
            supabase.table(table).upsert(clean_recs, on_conflict=unique_key).execute()
        else:
            supabase.table(table).upsert(clean_recs).execute()
    except Exception as e: st.error(f"❌ Save Error ({table}): {e}")

# --- INIT ---
if 'init' not in st.session_state:
    st.session_state.init = True
    st.session_state.quote_df = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "buying_price_vnd", "buying_price_rmb", "exchange_rate", "ap_price", "unit_price", "total_price_vnd", "supplier_name", "image_path", "leadtime", "transportation"])
    st.session_state.temp_supp = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "supplier"])
    st.session_state.temp_cust = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "unit_price", "total_price", "customer"])
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"

# --- LOAD ---
with st.spinner("Loading Cloud Data..."):
    if not get_drive_service(): st.stop()
    purchases_df = load_data("crm_purchases")
    customers_df = load_data("crm_customers")
    suppliers_df = load_data("crm_suppliers")
    shared_history_df = load_data("crm_shared_history")
    tracking_df = load_data("crm_tracking")
    payment_df = load_data("crm_payment")
    db_supplier_orders = load_data("db_supplier_orders")
    db_customer_orders = load_data("db_customer_orders")

# --- UI ---
st.title("CRM MANAGER (V4808)")
is_admin = (st.sidebar.text_input("Admin Password", type="password") == "admin")

t1, t2, t3, t4, t5, t6 = st.tabs(["DASHBOARD", "PURCHASES", "QUOTES", "PO", "TRACKING", "MASTER"])

# --- TAB 1: DASHBOARD ---
with t1:
    rev = db_customer_orders['total_price'].apply(to_float).sum() if not db_customer_orders.empty else 0
    cost = db_supplier_orders['total_vnd'].apply(to_float).sum() if not db_supplier_orders.empty else 0
    
    # Logic tính chi phí phụ (như V4800)
    other_cost = 0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            gap = to_float(r.get('gap', 0))
            other_cost += (gap * 0.6) + to_float(r.get('end_user_val',0)) + to_float(r.get('buyer_val',0)) + to_float(r.get('import_tax_val',0)) + to_float(r.get('vat_val',0)) + to_float(r.get('mgmt_fee',0)) + (to_float(r.get('transportation',0)) * to_float(r.get('qty',0)))
    
    profit = rev - (cost + other_cost)
    
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><h3>REVENUE</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><h3>COST (NCC + OPS)</h3><h1>{fmt_num(cost + other_cost)}</h1></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><h3>NET PROFIT</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: PURCHASES ---
with t2:
    col_up, col_view = st.columns([1, 3])
    with col_up:
        up_p = st.file_uploader("Import BUYING PRICE (Excel)", type=["xlsx"])
        if up_p and st.button("Import Purchases"):
            try:
                df = pd.read_excel(up_p, header=0, dtype=str).fillna("")
                # Load images
                img_map = {}
                try:
                    wb = load_workbook(up_p, data_only=False); ws = wb.active
                    for img in getattr(ws, '_images', []):
                        img_map[img.anchor._from.row + 1] = img
                except: pass
                
                rows = []
                bar = st.progress(0)
                for i, r in df.iterrows():
                    row_data = {}
                    # Map cột Excel -> DB (Auto map)
                    for excel_col, db_col in PURCHASE_MAP.items():
                        val = ""
                        if excel_col in df.columns: val = r[excel_col]
                        elif excel_col.replace("\n", " ") in df.columns: val = r[excel_col.replace("\n", " ")]
                        row_data[db_col] = safe_str(val)
                    
                    if not row_data.get("item_code"): continue
                    
                    # Ảnh Overwrite
                    img_url = ""
                    if (i+2) in img_map:
                        try:
                            buf = io.BytesIO(img_map[i+2]._data())
                            fname = f"IMG_{safe_filename(row_data['item_code'])}.png"
                            img_url = upload_to_drive(buf, "CRM_PURCHASE_IMAGES", fname)
                        except: pass
                    row_data["image_path"] = img_url
                    
                    # Dữ liệu sạch cho tìm kiếm
                    row_data["_clean_code"] = clean_lookup_key(row_data["item_code"])
                    row_data["_clean_name"] = clean_lookup_key(row_data["item_name"])
                    row_data["_clean_specs"] = clean_lookup_key(row_data["specs"])
                    
                    # Format số
                    for num_col in ["qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd"]:
                        row_data[num_col] = fmt_num(to_float(row_data.get(num_col, 0)))
                        
                    rows.append(row_data)
                    bar.progress((i+1)/len(df))
                
                # GHI ĐÈ dựa vào item_code
                save_data("crm_purchases", pd.DataFrame(rows), unique_key="item_code")
                st.success(f"Upserted {len(rows)} items!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Err: {e}")

        st.write("---")
        st.write("Manual Image Update")
        up_img = st.file_uploader("Image File", type=["png","jpg"])
        code_img = st.text_input("Item Code to update")
        if st.button("Update Image") and up_img and code_img:
            fname = f"IMG_{safe_filename(code_img)}.png"
            url = upload_to_drive(up_img, "CRM_PURCHASE_IMAGES", fname)
            supabase.table("crm_purchases").update({"image_path": url}).eq("item_code", code_img).execute()
            st.success("Updated"); st.rerun()

    with col_view:
        search = st.text_input("Search Item (Code/Name/Specs)")
        df_show = purchases_df.copy()
        if search:
            mask = df_show.apply(lambda x: search.lower() in str(x['item_code']).lower() or search.lower() in str(x['item_name']).lower(), axis=1)
            df_show = df_show[mask]
        st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Img")}, use_container_width=True, hide_index=True)

# --- TAB 3: QUOTES ---
with t3:
    c1, c2 = st.columns([3,1])
    with c1:
        cust_list = customers_df["short_name"].tolist() if not customers_df.empty else []
        cust = st.selectbox("Customer", [""] + cust_list)
        q_ref = st.text_input("Quote Reference")
    with c2:
        if st.button("RESET"):
            st.session_state.quote_df = pd.DataFrame(columns=st.session_state.quote_df.columns)
            st.rerun()
    
    cols = st.columns(7)
    pcts = {}
    for i, k in enumerate(["end","buy","tax","vat","pay","mgmt","trans"]):
        pcts[k] = cols[i].text_input(k.upper(), st.session_state[f"pct_{k}"])
        st.session_state[f"pct_{k}"] = pcts[k]

    up_rfq = st.file_uploader("Import RFQ (Excel)", type=["xlsx"])
    if up_rfq and st.button("Process RFQ"):
        try:
            # Tra cứu nhanh
            p_map = {}
            if not purchases_df.empty:
                for _, r in purchases_df.iterrows():
                    p_map[r['_clean_code']] = r
                    p_map[r['_clean_name']] = r
            
            rfq = pd.read_excel(up_rfq, header=None, dtype=str).fillna("")
            new_rows = []
            for i, r in rfq.iloc[1:].iterrows(): 
                c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2])
                if not c_raw and not n_raw: continue
                
                target = p_map.get(clean_lookup_key(c_raw)) or p_map.get(clean_lookup_key(n_raw))
                
                item = {
                    "item_code": c_raw, "item_name": n_raw, "specs": safe_str(r.iloc[3]), 
                    "qty": fmt_num(to_float(r.iloc[4])),
                    "buying_price_vnd": "0", "buying_price_rmb": "0", "exchange_rate": "0",
                    "unit_price": "0", "ap_price": "0", "supplier_name": "", "image_path": "", "leadtime": "", "transportation": "0"
                }
                if target is not None:
                    item.update({
                        "buying_price_vnd": target["buying_price_vnd"],
                        "buying_price_rmb": target["buying_price_rmb"],
                        "exchange_rate": target["exchange_rate"],
                        "supplier_name": target["supplier_name"],
                        "image_path": target["image_path"],
                        "leadtime": target["leadtime"]
                    })
                new_rows.append(item)
            st.session_state.quote_df = pd.DataFrame(new_rows)
            st.rerun()
        except Exception as e: st.error(f"RFQ Err: {e}")

    f1, f2, f3, f4 = st.columns(4)
    ap_f = f1.text_input("AP Formula")
    if f2.button("Apply AP"):
        for i, r in st.session_state.quote_df.iterrows():
            st.session_state.quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_f, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
        st.rerun()
    unit_f = f3.text_input("Unit Formula")
    if f4.button("Apply Unit"):
        for i, r in st.session_state.quote_df.iterrows():
            st.session_state.quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_f, to_float(r["buying_price_vnd"]), to_float(r["ap_price"])))
        st.rerun()

    edited = st.data_editor(st.session_state.quote_df, num_rows="dynamic", use_container_width=True, column_config={"image_path": st.column_config.ImageColumn()})
    
    final = edited.copy()
    for i, r in final.iterrows():
        q = to_float(r.get('qty',0))
        buy = to_float(r.get('buying_price_vnd',0))
        unit = to_float(r.get('unit_price',0))
        ap = to_float(r.get('ap_price',0))
        trans = to_float(pcts['trans'])
        
        total_buy = q * buy
        total_sell = q * unit
        ap_total = q * ap
        gap = total_sell - ap_total
        
        v_end = to_float(pcts['end'])/100 * ap_total
        v_buy = to_float(pcts['buy'])/100 * total_sell
        v_tax = to_float(pcts['tax'])/100 * total_buy
        v_vat = to_float(pcts['vat'])/100 * total_sell
        v_pay = to_float(pcts['pay'])/100 * gap
        v_mgmt = to_float(pcts['mgmt'])/100 * total_sell
        
        ops_cost = (gap * 0.6) + v_end + v_buy + v_tax + v_vat + (trans * q) + v_mgmt
        profit = total_sell - (total_buy + ops_cost) + v_pay
        
        final.at[i, "total_price_vnd"] = fmt_num(total_sell)
        final.at[i, "total_buying_price_vnd"] = fmt_num(total_buy)
        final.at[i, "gap"] = fmt_num(gap)
        final.at[i, "profit_vnd"] = fmt_num(profit)
        final.at[i, "profit_pct"] = f"{(profit/total_sell*100):.1f}%" if total_sell else "0%"
        final.at[i, "end_user_val"] = fmt_num(v_end)
        final.at[i, "buyer_val"] = fmt_num(v_buy)
        final.at[i, "import_tax_val"] = fmt_num(v_tax)
        final.at[i, "vat_val"] = fmt_num(v_vat)
        final.at[i, "payback_val"] = fmt_num(v_pay)
        final.at[i, "mgmt_fee"] = fmt_num(v_mgmt)
        final.at[i, "transportation"] = fmt_num(trans)

    if not final.equals(st.session_state.quote_df):
        st.session_state.quote_df = final; st.rerun()

    if st.button("SAVE QUOTE TO HISTORY"):
        if not cust or not q_ref: st.error("Missing Info"); st.stop()
        save = final.copy()
        save["history_id"] = f"{q_ref}_{int(time.time())}"
        save["quote_no"] = q_ref; save["customer"] = cust; save["date"] = datetime.now().strftime("%d/%m/%Y")
        for k, v in pcts.items(): save[f"pct_{k}"] = v
        save_data("crm_shared_history", save)
        st.success("Saved!"); st.rerun()

# --- TAB 4: PO ---
with t4:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("PO SUPPLIER")
        sup_list = suppliers_df["short_name"].tolist() if not suppliers_df.empty else []
        po_s = st.text_input("PO NCC No")
        sup = st.selectbox("Supplier", [""] + sup_list)
        up_s = st.file_uploader("Upload PO NCC", type=["xlsx"])
        if up_s:
            df = pd.read_excel(up_s, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "price_rmb": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_supp = pd.DataFrame(recs)
        
        ed_s = st.data_editor(st.session_state.temp_supp, num_rows="dynamic", use_container_width=True, key="ed_s")
        if st.button("Save PO NCC"):
            save = ed_s.copy()
            save["po_number"] = po_s; save["supplier"] = sup; save["order_date"] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_supplier_orders", save)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_s, "partner": sup, "status": "Ordered", "order_type": "NCC"}]))
            st.success("Saved")

    with c2:
        st.subheader("PO CUSTOMER")
        po_c = st.text_input("PO Customer No")
        cus = st.selectbox("Customer PO", [""] + (customers_df["short_name"].tolist() if not customers_df.empty else []))
        up_c = st.file_uploader("Upload PO Cust", type=["xlsx"])
        if up_c:
            df = pd.read_excel(up_c, dtype=str).fillna("")
            recs = []
            for i, r in df.iterrows():
                recs.append({"item_code": safe_str(r.iloc[1]), "item_name": safe_str(r.iloc[2]), "qty": fmt_num(to_float(r.iloc[4])), "unit_price": fmt_num(to_float(r.iloc[5]))})
            st.session_state.temp_cust = pd.DataFrame(recs)
            
        ed_c = st.data_editor(st.session_state.temp_cust, num_rows="dynamic", use_container_width=True, key="ed_c")
        if st.button("Save PO Cust"):
            save = ed_c.copy()
            save["po_number"] = po_c; save["customer"] = cus; save["order_date"] = datetime.now().strftime("%d/%m/%Y")
            save_data("db_customer_orders", save)
            save_data("crm_tracking", pd.DataFrame([{"po_no": po_c, "partner": cus, "status": "Waiting", "order_type": "KH"}]))
            st.success("Saved")

# --- TAB 5: TRACKING ---
with t5:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Tracking")
        if not tracking_df.empty:
            ed_t = st.data_editor(tracking_df, key="ed_t")
            if st.button("Update Tracking"):
                # Dùng id ẩn làm khóa duy nhất để update
                save_data("crm_tracking", ed_t, unique_key="id") 
                # Tự động chuyển sang Payment khi giao hàng xong
                for i, r in ed_t.iterrows():
                    if r['status'] == 'Delivered' and r['order_type'] == 'KH':
                        save_data("crm_payment", pd.DataFrame([{"po_no": r['po_no'], "customer": r['partner'], "status": "Pending"}]))
                st.success("Updated")
                
            pk = st.text_input("Enter PO No for Proof")
            prf = st.file_uploader("Proof Image", accept_multiple_files=True)
            if st.button("Upload Proof") and pk and prf:
                urls = [upload_to_drive(f, "CRM_PROOF_IMAGES", f"PRF_{pk}_{f.name}") for f in prf]
                supabase.table("crm_tracking").update({"proof_image": json.dumps(urls)}).eq("po_no", pk).execute()
                st.success("Uploaded")

    with c2:
        st.subheader("Payment")
        if not payment_df.empty:
            ed_p = st.data_editor(payment_df, key="ed_p")
            if st.button("Update Payment"):
                save_data("crm_payment", ed_p, unique_key="id")
                st.success("Updated")

# --- TAB 6: MASTER ---
with t6:
    if is_admin:
        c1, c2 = st.columns(2)
        with c1:
            st.write("Customers")
            up_cust = st.file_uploader("Import Customers", type=["xlsx", "csv"])
            if up_cust and st.button("Import Cust"):
                if up_cust.name.endswith('.csv'): df = pd.read_csv(up_cust, dtype=str).fillna("")
                else: df = pd.read_excel(up_cust, header=0, dtype=str).fillna("")
                rows = []
                for _, r in df.iterrows():
                    d = {v: safe_str(r.get(k) or r.get(k.upper()) or "") for k, v in CUSTOMER_MAP.items()}
                    if d['short_name']: rows.append(d)
                # GHI ĐÈ dựa trên short_name
                save_data("crm_customers", pd.DataFrame(rows), unique_key="short_name")
                st.success("Imported"); st.rerun()
                
            ed_cust = st.data_editor(customers_df, num_rows="dynamic", key="ed_cust")
            if st.button("Save Cust"): save_data("crm_customers", ed_cust, unique_key="short_name"); st.success("OK")

        with c2:
            st.write("Suppliers")
            up_supp = st.file_uploader("Import Suppliers", type=["xlsx", "csv"])
            if up_supp and st.button("Import Supp"):
                if up_supp.name.endswith('.csv'): df = pd.read_csv(up_supp, dtype=str).fillna("")
                else: df = pd.read_excel(up_supp, header=0, dtype=str).fillna("")
                rows = []
                for _, r in df.iterrows():
                    d = {v: safe_str(r.get(k) or r.get(k.upper()) or "") for k, v in CUSTOMER_MAP.items()} 
                    if d['short_name']: rows.append(d)
                # GHI ĐÈ dựa trên short_name
                save_data("crm_suppliers", pd.DataFrame(rows), unique_key="short_name")
                st.success("Imported"); st.rerun()

            ed_supp = st.data_editor(suppliers_df, num_rows="dynamic", key="ed_supp")
            if st.button("Save Supp"): save_data("crm_suppliers", ed_supp, unique_key="short_name"); st.success("OK")
    else: st.warning("Admin only")
