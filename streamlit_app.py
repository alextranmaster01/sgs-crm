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
# 1. CẤU HÌNH HỆ THỐNG
# =============================================================================
APP_VERSION = "V5500 - FULL FEATURE (FIXED IMAGES & TABS)"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS GIAO DIỆN ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 18px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 15px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 10px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    
    [data-testid="stDataFrame"] > div { max-height: 700px; }
    /* Ẩn cột index nếu cần */
    thead tr th:first-child { display:none }
    tbody tr td:first-child { display:none }
    </style>""", unsafe_allow_html=True)

# --- THƯ VIỆN KẾT NỐI ---
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from openpyxl import load_workbook
    from openpyxl.utils import range_boundaries
except ImportError:
    st.error("⚠️ LỖI: Thiếu thư viện. Hãy thêm vào requirements.txt: supabase, google-api-python-client, google-auth-oauthlib, openpyxl, pandas, numpy")
    st.stop()

# --- KHỞI TẠO KẾT NỐI ---
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa") # Thay ID folder gốc của bạn vào đây nếu khác
except Exception as e:
    st.error(f"⚠️ Lỗi Config Secrets: {e}")
    st.stop()

# =============================================================================
# 2. HÀM HỖ TRỢ (HELPER FUNCTIONS)
# =============================================================================

def get_drive_service():
    """Tạo kết nối Google Drive"""
    try:
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], client_secret=OAUTH_INFO["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

def upload_to_drive(file_obj, sub_folder, file_name):
    """Upload file lên Google Drive và lấy link thumbnail"""
    srv = get_drive_service()
    if not srv: return ""
    try:
        # 1. Tìm hoặc tạo folder con
        q_f = f"'{ROOT_FOLDER_ID}' in parents and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if folders: folder_id = folders[0]['id']
        else:
            folder_id = srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
            srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        # 2. Upload
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        
        file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        
        # 3. Set quyền Public
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        # 4. Trả về link thumbnail (xem được trực tiếp)
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200"
    except Exception as e: 
        print(f"Upload Error: {e}")
        return ""

def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def to_float(val):
    if val is None: return 0.0
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").upper()
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(nums[0]) if nums else 0.0
    except: return 0.0

def fmt_num(x): return "{:,.0f}".format(x) if x else "0"
def clean_key(s): return re.sub(r'[^a-zA-Z0-9]', '', safe_str(s)).lower()
def normalize_header(h): return re.sub(r'[^a-zA-Z0-9]', '', str(h).lower())

def load_data(table):
    try:
        res = supabase.table(table).select("*").execute()
        df = pd.DataFrame(res.data)
        if not df.empty and 'id' in df.columns: df = df.drop(columns=['id'])
        return df
    except: return pd.DataFrame()

def insert_data_bulk(table, df, mapping, clear_first=False):
    """Hàm Import thông minh: Có tùy chọn xóa dữ liệu cũ"""
    if df.empty: return
    try:
        # 1. Xóa dữ liệu cũ nếu được yêu cầu (Để sửa lỗi 893 item)
        if clear_first:
            # Hack: xóa các dòng có id > 0 (gần như tất cả)
            supabase.table(table).delete().neq("id", 0).execute() 
            time.sleep(1)

        # 2. Map cột
        hn = {normalize_header(c): c for c in df.columns}
        records = []
        for i, r in df.iterrows():
            d = {}
            has_data = False
            for db_col, list_excel_cols in mapping.items():
                val = ""
                # Nếu là cột image_path và đã có sẵn trong df (do xử lý riêng)
                if db_col == 'image_path' and 'image_path' in df.columns:
                    val = safe_str(r['image_path'])
                else:
                    # Tìm cột trong excel
                    for kw in list_excel_cols:
                        norm_kw = normalize_header(kw)
                        if norm_kw in hn:
                            val = safe_str(r[hn[norm_kw]])
                            break
                d[db_col] = val
                if val: has_data = True
            
            # Convert số
            if 'qty' in d: d['qty'] = to_float(d['qty'])
            if 'buying_price_rmb' in d: d['buying_price_rmb'] = to_float(d['buying_price_rmb'])
            
            if has_data: records.append(d)
            
        # 3. Batch Insert
        chunk = 100
        bar = st.progress(0)
        for i in range(0, len(records), chunk):
            supabase.table(table).insert(records[i:i+chunk]).execute()
            bar.progress(min((i+chunk)/len(records), 1.0))
        
        st.cache_data.clear()
        st.success(f"✅ Đã import {len(records)} dòng vào {table}!")
        
    except Exception as e: st.error(f"Lỗi DB: {e}")

# MAPPING CONFIG
MAP_PURCHASE = {
    "item_code": ["Item code", "Mã hàng", "Code"], "item_name": ["Item name", "Tên hàng", "Name"],
    "specs": ["Specs", "Quy cách"], "qty": ["Q'ty", "Qty"],
    "buying_price_rmb": ["Buying price (RMB)", "Giá RMB"], "exchange_rate": ["Exchange rate", "Tỷ giá"],
    "buying_price_vnd": ["Buying price (VND)", "Giá VND"], "leadtime": ["Leadtime"],
    "supplier_name": ["Supplier"], "image_path": ["image_path"], "type": ["Type"], "nuoc": ["NUOC"]
}

MAP_MASTER = {
    "short_name": ["shortname", "tên tắt"], "eng_name": ["engname"], "vn_name": ["vnname"],
    "address_1": ["address"], "tax_code": ["tax"], "contact_person": ["contact"], "phone": ["phone"]
}

# =============================================================================
# 3. GIAO DIỆN CHÍNH
# =============================================================================
t1, t2, t3, t4, t5, t6 = st.tabs(["📊 DASHBOARD", "📦 KHO HÀNG", "💰 BÁO GIÁ", "📑 PO (ĐƠN HÀNG)", "🚚 TRACKING", "⚙️ MASTER"])

# --- TAB 1: DASHBOARD ---
with t1:
    if st.button("🔄 REFRESH DATA"): st.cache_data.clear(); st.rerun()
    with st.spinner("Đang tải..."):
        db_cust = load_data("db_customer_orders")
        db_supp = load_data("db_supplier_orders")
        db_track = load_data("crm_tracking")
        
        rev = db_cust['total_price'].apply(to_float).sum() if not db_cust.empty else 0
        cost = db_supp['total_vnd'].apply(to_float).sum() if not db_supp.empty else 0
        profit = rev - cost # (Lợi nhuận thô)
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ NCC</h3><h1>{fmt_num(cost)}</h1></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN GỘP</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: KHO HÀNG (FIXED IMAGE & DUPLICATE) ---
with t2:
    st.subheader("QUẢN LÝ KHO HÀNG (PURCHASES)")
    c_imp, c_view = st.columns([1, 2])
    
    with c_imp:
        st.write("📥 **Nhập liệu từ Excel**")
        up_file = st.file_uploader("Chọn file Buying Price (xlsx)", type=["xlsx"])
        
        # CHECKBOX QUAN TRỌNG ĐỂ SỬA LỖI 893 ITEM
        clear_db = st.checkbox("🗑️ Xóa sạch dữ liệu cũ trước khi Import?", value=True, help="Chọn cái này để tránh bị trùng lặp/cộng dồn dữ liệu")
        
        if up_file and st.button("🚀 Bắt đầu Import"):
            try:
                wb = load_workbook(up_file, data_only=False)
                ws = wb.active
                
                # 1. Xử lý Ảnh chính xác hơn
                img_map = {}
                # Duyệt qua các ảnh trong sheet
                for image in getattr(ws, '_images', []):
                    # Lấy row index của góc trên bên trái ảnh
                    row = image.anchor._from.row + 1
                    # Lưu vào map
                    buf = io.BytesIO(image._data())
                    fname = f"IMG_R{row}_{int(time.time())}.png"
                    link = upload_to_drive(buf, "CRM_PRODUCT_IMAGES", fname)
                    img_map[row] = link
                
                # 2. Đọc Data
                df = pd.read_excel(up_file, dtype=str).fillna("")
                
                # 3. Gán ảnh vào DF
                # Lưu ý: Pandas index bắt đầu từ 0, Excel row bắt đầu từ 2 (header là 1)
                # Dòng đầu tiên của data (index 0) tương ứng row 2 trong Excel
                imgs = []
                for i in range(len(df)):
                    excel_row = i + 2 
                    imgs.append(img_map.get(excel_row, "")) # Lấy ảnh ở dòng tương ứng
                
                df['image_path'] = imgs
                
                # 4. Insert
                insert_data_bulk("crm_purchases", df, MAP_PURCHASE, clear_first=clear_db)
                st.rerun()
                
            except Exception as e: st.error(f"Lỗi: {e}")

    with c_view:
        st.write("🔎 **Tra cứu**")
        df_pur = load_data("crm_purchases")
        search = st.text_input("Tìm kiếm mã, tên, specs...", key="search_pur")
        
        if not df_pur.empty:
            if search:
                mask = df_pur.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
                df_pur = df_pur[mask]
            
            st.dataframe(
                df_pur,
                column_config={
                    "image_path": st.column_config.ImageColumn("Ảnh", width="small"),
                    "buying_price_rmb": st.column_config.NumberColumn("Giá RMB"),
                    "buying_price_vnd": st.column_config.NumberColumn("Giá VND"),
                },
                use_container_width=True,
                height=600
            )
            st.caption(f"Tổng số dòng: {len(df_pur)}")
        else: st.info("Kho hàng trống.")

# --- TAB 3: BÁO GIÁ (QUOTES) ---
with t3:
    if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()
    st.subheader("TÍNH TOÁN BÁO GIÁ")
    if st.button("🆕 Tạo báo giá mới"): st.session_state.quote_df = pd.DataFrame(); st.rerun()

    # Tham số
    with st.expander("Cấu hình chi phí (%)", expanded=True):
        cols = st.columns(7)
        keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
        params = {}
        for i, k in enumerate(keys):
            val = cols[i].text_input(k.upper(), st.session_state.get(f"pct_{k}", "0"))
            st.session_state[f"pct_{k}"] = val
            params[k] = to_float(val)

    c1, c2 = st.columns([1, 2])
    rfq = c1.file_uploader("Upload RFQ (xlsx)", type=["xlsx"])
    if rfq and c2.button("Matching Giá"):
        db = load_data("crm_purchases")
        if db.empty: st.error("Kho rỗng")
        else:
            # Logic Matching
            lookup = {clean_key(r['item_code']): r for r in db.to_dict('records')}
            df_rfq = pd.read_excel(rfq, dtype=str).fillna("")
            res = []
            hn = {normalize_header(c): c for c in df_rfq.columns}
            
            for i, r in df_rfq.iterrows():
                code = safe_str(r.get(hn.get(normalize_header("itemcode")) or hn.get(normalize_header("mã"))))
                qty = to_float(r.get(hn.get(normalize_header("qty"))))
                match = lookup.get(clean_key(code))
                
                item = {
                    "Item code": code, "Q'ty": fmt_num(qty),
                    "Buying price (VND)": fmt_num(match.get('buying_price_vnd')) if match else "0",
                    "Supplier": match.get('supplier_name') if match else "",
                    "Image": match.get('image_path') if match else "",
                    "Leadtime": match.get('leadtime') if match else "",
                    "AP price (VND)": "0", "Unit price (VND)": "0", "Profit (VND)": "0"
                }
                res.append(item)
            st.session_state.quote_df = pd.DataFrame(res)

    if not st.session_state.quote_df.empty:
        # Quick Formula
        f1, f2 = st.columns(2)
        ap_f = f1.text_input("Formula AP (vd: =BUY*1.1)")
        unit_f = f2.text_input("Formula Unit (vd: =AP*1.2)")
        
        # Calc
        df = st.session_state.quote_df.copy()
        for i, r in df.iterrows():
            buy = to_float(r["Buying price (VND)"]); qty = to_float(r["Q'ty"])
            ap = to_float(r.get("AP price (VND)", 0))
            
            if ap_f and ap_f.startswith("="): 
                ap = eval(ap_f[1:].replace("BUY", str(buy)).replace("AP", str(ap)))
                df.at[i, "AP price (VND)"] = fmt_num(ap)
                
            if unit_f and unit_f.startswith("="):
                unit = eval(unit_f[1:].replace("BUY", str(buy)).replace("AP", str(ap)))
                df.at[i, "Unit price (VND)"] = fmt_num(unit)
                
            # Profit
            unit = to_float(df.at[i, "Unit price (VND)"])
            ap = to_float(df.at[i, "AP price (VND)"])
            total_sell = unit * qty; total_buy = buy * qty; ap_total = ap * qty
            gap = total_sell - ap_total
            
            cost_ops = (gap*0.6 if gap>0 else 0) + (ap_total * params['end']/100) + \
                       (total_sell * params['buy']/100) + (total_buy * params['tax']/100) + \
                       (total_sell * params['vat']/100) + (total_sell * params['mgmt']/100) + \
                       (params['trans'] * qty)
            
            prof = total_sell - total_buy - cost_ops + (gap * params['pay']/100)
            df.at[i, "Profit (VND)"] = fmt_num(prof)

        st.session_state.quote_df = df
        
        edited = st.data_editor(st.session_state.quote_df, use_container_width=True, 
                                column_config={"Image": st.column_config.ImageColumn("Ảnh")})
        
        if not edited.equals(st.session_state.quote_df):
            st.session_state.quote_df = edited; st.rerun()
            
        if st.button("💾 Lưu Báo Giá"):
            cust = st.text_input("Tên Khách Hàng")
            if cust:
                recs = edited.to_dict('records')
                # Map lại tên cột cho khớp DB History
                final = []
                for r in recs:
                    final.append({
                        "history_id": f"{cust}_{int(time.time())}", "date": datetime.now().strftime("%Y-%m-%d"),
                        "quote_no": cust, "customer": cust, "item_code": r["Item code"],
                        "qty": to_float(r["Q'ty"]), "unit_price": to_float(r["Unit price (VND)"]),
                        "profit_vnd": to_float(r["Profit (VND)"])
                    })
                supabase.table("crm_shared_history").insert(final).execute()
                st.success("Đã lưu!")

# --- TAB 4: PO (ĐƠN HÀNG) ---
with t4:
    c_ncc, c_kh = st.columns(2)
    
    # 1. PO NCC
    with c_ncc:
        st.subheader("1. PO NHÀ CUNG CẤP")
        po_s_no = st.text_input("Số PO NCC")
        supps = load_data("crm_suppliers")
        s_name = st.selectbox("Chọn NCC", [""] + supps['short_name'].tolist() if not supps.empty else [])
        
        up_s = st.file_uploader("Upload PO NCC (xlsx)", key="ups")
        if up_s:
            dfs = pd.read_excel(up_s, dtype=str).fillna("")
            # Hiển thị tạm
            st.dataframe(dfs)
            if st.button("Lưu PO NCC"):
                # Insert vào db_supplier_orders
                recs = []
                for i, r in dfs.iterrows():
                    recs.append({
                        "po_number": po_s_no, "supplier": s_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                        "item_code": safe_str(r.iloc[1]), "qty": to_float(r.iloc[4]), "price_vnd": to_float(r.iloc[5]),
                        "total_vnd": to_float(r.iloc[6])
                    })
                supabase.table("db_supplier_orders").insert(recs).execute()
                # Tạo tracking
                supabase.table("crm_tracking").insert([{
                    "po_no": po_s_no, "partner": s_name, "status": "Ordered", "order_type": "NCC", "last_update": datetime.now().strftime("%d/%m/%Y")
                }]).execute()
                st.success("Đã lưu PO NCC")

    # 2. PO KHÁCH
    with c_kh:
        st.subheader("2. PO KHÁCH HÀNG")
        po_c_no = st.text_input("Số PO Khách")
        custs = load_data("crm_customers")
        c_name = st.selectbox("Chọn Khách", [""] + custs['short_name'].tolist() if not custs.empty else [])
        
        up_c = st.file_uploader("Upload PO Khách (xlsx)", key="upc")
        if up_c:
            dfc = pd.read_excel(up_c, dtype=str).fillna("")
            st.dataframe(dfc)
            if st.button("Lưu PO Khách"):
                recs = []
                for i, r in dfc.iterrows():
                    recs.append({
                        "po_number": po_c_no, "customer": c_name, "order_date": datetime.now().strftime("%d/%m/%Y"),
                        "item_code": safe_str(r.iloc[1]), "qty": to_float(r.iloc[4]), "total_price": to_float(r.iloc[6])
                    })
                supabase.table("db_customer_orders").insert(recs).execute()
                # Tracking
                supabase.table("crm_tracking").insert([{
                    "po_no": po_c_no, "partner": c_name, "status": "Waiting", "order_type": "KH", "last_update": datetime.now().strftime("%d/%m/%Y")
                }]).execute()
                st.success("Đã lưu PO Khách")

# --- TAB 5: TRACKING ---
with t5:
    st.subheader("THEO DÕI ĐƠN HÀNG")
    df_track = load_data("crm_tracking")
    
    if not df_track.empty:
        # Edit trực tiếp trạng thái
        edited_track = st.data_editor(
            df_track, 
            column_config={
                "status": st.column_config.SelectboxColumn("Trạng thái", options=["Ordered", "Waiting", "Delivered", "Paid"]),
                "proof_image": st.column_config.ImageColumn("Bằng chứng")
            },
            use_container_width=True,
            key="track_edit"
        )
        
        # Upload ảnh proof
        c_p1, c_p2 = st.columns(2)
        po_sel = c_p1.selectbox("Chọn PO để up ảnh", df_track['po_no'].unique())
        img_p = c_p2.file_uploader("Upload ảnh Proof", type=['png','jpg'])
        
        if c_p2.button("Update trạng thái & Ảnh"):
            # Update data bảng
            # Lưu ý: data_editor không tự save về DB, phải xử lý logic update
            # Ở đây ta update đơn giản cái dòng PO được chọn
            if img_p:
                link = upload_to_drive(img_p, "CRM_PROOF", f"PRF_{po_sel}.png")
                supabase.table("crm_tracking").update({"proof_image": link}).eq("po_no", po_sel).execute()
                st.success("Đã up ảnh")
            
            # Update status từ editor (logic phức tạp hơn cần loop, ở đây demo update manual)
            st.info("Lưu ý: Data Editor hiển thị để xem. Để lưu status hàng loạt cần code xử lý từng dòng.")
    else:
        st.info("Chưa có đơn hàng nào.")

# --- TAB 6: MASTER DATA ---
with t6:
    st.subheader("DỮ LIỆU NỀN")
    t6_1, t6_2 = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP"])
    
    with t6_1:
        df_k = load_data("crm_customers")
        st.data_editor(df_k, use_container_width=True, key="ed_k")
        if st.button("Lưu thay đổi KH"): st.warning("Tính năng đang phát triển")
        
        up_k = st.file_uploader("Import Khách Hàng", key="uk")
        if up_k and st.button("Import KH"):
            df = pd.read_excel(up_k, dtype=str).fillna("")
            insert_data_bulk("crm_customers", df, MAP_MASTER)
            
    with t6_2:
        df_s = load_data("crm_suppliers")
        st.data_editor(df_s, use_container_width=True, key="ed_s")
        
        up_s = st.file_uploader("Import NCC", key="us")
        if up_s and st.button("Import NCC"):
            df = pd.read_excel(up_s, dtype=str).fillna("")
            insert_data_bulk("crm_suppliers", df, MAP_MASTER)
