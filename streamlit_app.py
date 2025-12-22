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
APP_VERSION = "V5800 - FINAL MERGED LOGIC (V4800 CORE)"
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
def clean_key(s): return re.sub(r'[^a-zA-Z0-9]', '', safe_str(s)).lower()
def normalize_header(h): return re.sub(r'[^a-zA-Z0-9]', '', str(h).lower())

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

# HÀM PARSE FORMULA CHUẨN (TỪ V4800)
def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper()
    # Xử lý ký tự thay thế cho user tiện nhập
    s = s.replace(",", ".") # 1,1 -> 1.1
    s = s.replace("%", "/100") # 10% -> /100
    s = s.replace("X", "*") # X -> *
    
    if s.startswith("="): s = s[1:]
    
    # Thay thế biến
    s = s.replace("BUYING PRICE", str(buying_price))
    s = s.replace("BUY", str(buying_price))
    s = s.replace("AP PRICE", str(ap_price))
    s = s.replace("AP", str(ap_price))
    
    # Chỉ giữ lại ký tự toán học an toàn
    s = re.sub(r'[^0-9.+\-*/()]', '', s)
    
    try: return float(eval(s))
    except: return 0.0

# MAPPING
MAP_PURCHASE = {
    "item_code": ["Item code", "Mã hàng", "Code"], "item_name": ["Item name", "Tên hàng", "Name"],
    "specs": ["Specs", "Quy cách"], "qty": ["Q'ty", "Qty"],
    "buying_price_rmb": ["Buying price (RMB)", "Giá RMB"], "exchange_rate": ["Exchange rate", "Tỷ giá"],
    "buying_price_vnd": ["Buying price (VND)", "Giá VND"], "leadtime": ["Leadtime"],
    "supplier_name": ["Supplier"], "image_path": ["image_path"], "type": ["Type"], "nuoc": ["NUOC"]
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
        st.write("📥 **Import / Ghi đè (Update)**")
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
                codes_to_del = []
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
                    
                    d['total_buying_price_rmb'] = p_rmb * qty
                    d['total_buying_price_vnd'] = p_vnd * qty
                    
                    if d.get('item_code'):
                        records.append(d)
                        if d['item_code'] not in codes_to_del:
                            codes_to_del.append(d['item_code'])
                    
                    prog.progress((i + 1) / len(df))

                if codes_to_del:
                    chunk = 50
                    for k in range(0, len(codes_to_del), chunk):
                        batch = codes_to_del[k:k+chunk]
                        supabase.table("crm_purchases").delete().in_("item_code", batch).execute()
                    
                    chunk_ins = 100
                    for k in range(0, len(records), chunk_ins):
                        supabase.table("crm_purchases").insert(records[k:k+chunk_ins]).execute()
                        
                    st.success(f"Đã import đủ {len(records)} dòng (trên tổng {len(df)} dòng Excel)!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
                    
            except Exception as e: st.error(f"Lỗi: {e}")

    with c_view:
        df_pur = load_data("crm_purchases", order_by="row_order")
        search = st.text_input("Tìm kiếm...", key="search_pur")
        st.caption(f"Tổng số item hiện có: {len(df_pur)}")
        if not df_pur.empty:
            if search:
                mask = df_pur.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
                df_pur = df_pur[mask]
            st.dataframe(df_pur, column_config={"image_path": st.column_config.ImageColumn("Ảnh")}, use_container_width=True, height=600)

# --- TAB 3: BÁO GIÁ (LOGIC V4800 MERGED) ---
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
        for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
             if f"pct_{k}" in st.session_state: del st.session_state[f"pct_{k}"]
        st.rerun()

    # THAM SỐ CHI PHÍ
    with st.expander("Cấu hình chi phí (%)", expanded=True):
        cols = st.columns(7)
        keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
        params = {}
        for i, k in enumerate(keys):
            # Lấy giá trị mặc định từ session state nếu có
            default_val = st.session_state.get(f"pct_{k}", "0")
            val = cols[i].text_input(k.upper(), default_val, key=f"input_{k}")
            st.session_state[f"pct_{k}"] = val
            params[k] = to_float(val)

    # Matching RFQ
    cf1, cf2 = st.columns([1, 2])
    rfq = cf1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and cf2.button("🔍 Matching"):
        st.session_state.quote_df = pd.DataFrame()
        
        db = load_data("crm_purchases")
        if db.empty: st.error("Kho rỗng!")
        else:
            lookup = {clean_key(r['item_code']): r for r in db.to_dict('records')}
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            hn = {normalize_header(c): c for c in df_rfq.columns}
            
            for i, r in df_rfq.iterrows():
                code = safe_str(r.get(hn.get(normalize_header("itemcode")) or hn.get(normalize_header("mã"))))
                qty = to_float(r.get(hn.get(normalize_header("qty"))))
                match = lookup.get(clean_key(code))
                
                buy_rmb = to_float(match.get('buying_price_rmb')) if match else 0
                buy_vnd = to_float(match.get('buying_price_vnd')) if match else 0
                ex_rate = to_float(match.get('exchange_rate')) if match else 0
                
                item = {
                    "No": i+1,
                    "Cảnh báo": "",
                    "Item code": code,
                    "Item name": match.get('item_name') if match else "",
                    "Specs": match.get('specs') if match else "",
                    "Q'ty": qty, 
                    "Buying price(RMB)": fmt_num(buy_rmb),
                    "Total buying price(rmb)": fmt_num(buy_rmb * qty),
                    "Exchange rate": fmt_num(ex_rate),
                    "Buying price(VND)": fmt_num(buy_vnd),
                    "Total buying price(VND)": fmt_num(buy_vnd * qty),
                    "AP price(VND)": "0",
                    "AP total price(VND)": "0",
                    "Unit price(VND)": "0",
                    "Total price(VND)": "0",
                    "GAP": "0",
                    "End user(%)": "0",
                    "Buyer(%)": "0",
                    "Import tax(%)": "0",
                    "VAT": "0",
                    "Transportation": "0",
                    "Management fee(%)": "0",
                    "Payback(%)": "0",
                    "Profit(VND)": "0",
                    "Profit(%)": "0%",
                    "Supplier": match.get('supplier_name') if match else "",
                    "Image": match.get('image_path') if match else "",
                    "Leadtime": match.get('leadtime') if match else ""
                }
                res.append(item)
            st.session_state.quote_df = pd.DataFrame(res)
            st.rerun()

    # INPUT FORMULA & BUTTONS
    # Logic: Button click -> Tính toán vào State -> Rerun -> Editor hiển thị số mới
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
    
    # DATA EDITOR & AUTO-RECALCULATE LOOP
    if not st.session_state.quote_df.empty:
        # 1. Hiển thị Editor
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
        
        # 2. Logic tính toán tự động (Giống V4800)
        # Nếu user sửa trên Editor -> edited_df thay đổi -> Tính lại -> Update State -> Rerun
        
        # Lấy tham số
        pend = params['end']/100; pbuy = params['buy']/100
        ptax = params['tax']/100; pvat = params['vat']/100
        ppay = params['pay']/100; pmgmt = params['mgmt']/100
        val_trans = params['trans']
        
        df_temp = edited_df.copy()
        has_change = False
        
        for i, r in df_temp.iterrows():
            # Lấy giá trị (Clean)
            qty = to_float(r.get("Q'ty", 0))
            buy_vnd = to_float(r.get("Buying price(VND)", 0))
            buy_rmb = to_float(r.get("Buying price(RMB)", 0))
            ap = to_float(r.get("AP price(VND)", 0))
            unit = to_float(r.get("Unit price(VND)", 0))
            
            # Tính toán
            t_buy = qty * buy_vnd
            ap_tot = ap * qty
            total = unit * qty
            gap = total - ap_tot
            
            end_val = ap_tot * pend
            buyer_val = total * pbuy
            tax_val = t_buy * ptax
            vat_val = total * pvat
            mgmt_val = total * pmgmt
            pay_val = gap * ppay
            
            # Logic Trans: Nếu Global > 0 thì dùng Global, không thì dùng từng dòng (nếu có logic dòng)
            # Ở đây dùng logic: Trans Global * Qty
            tot_trans = val_trans * qty
            
            # Cost & Profit
            # Cost = Total Buy + (Gap*0.6 if Gap>0) + End + Buyer + Tax + VAT + Mgmt + Trans
            gap_share = gap * 0.6 if gap > 0 else 0
            cost_ops = gap_share + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
            
            prof = total - t_buy - cost_ops + pay_val
            pct = (prof / total * 100) if total > 0 else 0
            
            # Cảnh báo
            alert = "⚠️ LOW" if pct < 10 else "✅ OK"
            
            # Cập nhật lại dòng (Format string)
            df_temp.at[i, "Transportation"] = fmt_num(tot_trans)
            df_temp.at[i, "Total buying price(rmb)"] = fmt_num(buy_rmb * qty)
            df_temp.at[i, "Total buying price(VND)"] = fmt_num(t_buy)
            df_temp.at[i, "AP total price(VND)"] = fmt_num(ap_tot)
            df_temp.at[i, "Total price(VND)"] = fmt_num(total)
            df_temp.at[i, "GAP"] = fmt_num(gap)
            df_temp.at[i, "End user(%)"] = fmt_num(end_val)
            df_temp.at[i, "Buyer(%)"] = fmt_num(buyer_val)
            df_temp.at[i, "Import tax(%)"] = fmt_num(tax_val)
            df_temp.at[i, "VAT"] = fmt_num(vat_val)
            df_temp.at[i, "Management fee(%)"] = fmt_num(mgmt_val)
            df_temp.at[i, "Payback(%)"] = fmt_num(pay_val)
            df_temp.at[i, "Profit(VND)"] = fmt_num(prof)
            df_temp.at[i, "Profit(%)"] = f"{pct:.1f}%"
            df_temp.at[i, "Cảnh báo"] = alert

        # So sánh xem có thay đổi so với State không
        # Lưu ý: Convert to dict để so sánh tránh lỗi NaN/Float lệch nhẹ
        if not df_temp.equals(st.session_state.quote_df):
             st.session_state.quote_df = df_temp
             st.rerun()

        # Cảnh báo Lợi nhuận thấp UI
        low_profits = st.session_state.quote_df[st.session_state.quote_df["Cảnh báo"] == "⚠️ LOW"]
        if not low_profits.empty:
            st.error(f"⚠️ CÓ {len(low_profits)} MỤC LỢI NHUẬN THẤP (<10%)")

        # EXPORT & SAVE
        st.divider()
        c_sv, c_ex = st.columns(2)
        with c_ex:
            tmps = load_data("crm_templates")
            t_list = tmps['template_name'].tolist() if not tmps.empty else []
            sel_t = st.selectbox("Chọn Template Export", t_list)
            
            if st.button("📤 Export Excel"):
                if not sel_t: st.error("Chưa có Template")
                else:
                    fid = tmps[tmps['template_name'] == sel_t].iloc[0]['file_id']
                    bio = download_from_drive(fid)
                    if bio:
                        try:
                            wb = load_workbook(bio); ws = wb.active
                            ws['B5'] = cust_name; ws['G5'] = quote_no
                            ws['G6'] = datetime.now().strftime("%d/%m/%Y")
                            thin = Side(border_style="thin", color="000000")
                            border = Border(top=thin, left=thin, right=thin, bottom=thin)
                            for idx, r in st.session_state.quote_df.iterrows():
                                ri = 12 + idx
                                ws.cell(row=ri, column=1, value=idx+1).border = border
                                ws.cell(row=ri, column=2, value=r["Item code"]).border = border
                                ws.cell(row=ri, column=3, value=r.get("Item name")).border = border
                                ws.cell(row=ri, column=4, value=r.get("Specs")).border = border
                                ws.cell(row=ri, column=5, value=to_float(r["Q'ty"])).border = border
                                ws.cell(row=ri, column=6, value=to_float(r["Unit price(VND)"])).border = border
                                ws.cell(row=ri, column=7, value=to_float(r["Total price(VND)"])).border = border
                                ws.cell(row=ri, column=8, value=r.get("Leadtime")).border = border
                            out = io.BytesIO(); wb.save(out)
                            st.download_button("⬇️ Tải File", out.getvalue(), f"Quote_{quote_no}.xlsx")
                        except Exception as e: st.error(f"Lỗi Template: {e}")

        with c_sv:
            csv = st.session_state.quote_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("⬇️ Tải file CSV", csv, f"Quote_{quote_no}.csv", "text/csv")
            
            if st.button("💾 Lưu Lịch sử (Cloud)"):
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
                else: st.error("Chọn khách hàng!")

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
        t_name = st.text_input("Tên Template")
        if up_t and t_name and st.button("Lưu Template"):
            lnk, fid = upload_to_drive(up_t, "CRM_TEMPLATES", f"TMP_{t_name}.xlsx")
            if fid: supabase.table("crm_templates").insert([{"template_name": t_name, "file_id": fid, "last_updated": datetime.now().strftime("%d/%m/%Y")}]).execute(); st.success("OK"); st.rerun()
        st.dataframe(load_data("crm_templates"))
