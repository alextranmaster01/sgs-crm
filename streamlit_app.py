import streamlit as st
import pandas as pd
import os  # <--- ĐÃ THÊM LẠI THƯ VIỆN NÀY ĐỂ SỬA LỖI
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import io
import time

# --- THƯ VIỆN GOOGLE DRIVE ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# =============================================================================
# 1. CẤU HÌNH HỆ THỐNG
# =============================================================================

# --- !!! QUAN TRỌNG: ĐIỀN ID THƯ MỤC DRIVE CỦA BẠN VÀO DÒNG DƯỚI !!! ---
# (Lấy từ link trình duyệt: drive.google.com/drive/folders/CHUỖI_KÝ_TỰ_NÀY)
DRIVE_FOLDER_ID = "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa?hl=vi" # <--- HÃY DÁN LẠI ID CỦA BẠN VÀO ĐÂY

APP_VERSION = "V5.1 - CLOUD ONLINE (FIXED)"
SCOPES = ['https://www.googleapis.com/auth/drive']

st.set_page_config(page_title=f"CRM CLOUD", layout="wide", page_icon="☁️")

# --- CSS GIAO DIỆN ---
st.markdown("""
    <style>
    .stAlert { font-weight: bold; }
    .card-3d {
        border-radius: 15px; padding: 20px; color: white; text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px;
    }
    .bg-sales { background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); }
    .bg-profit { background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); }
    </style>
    """, unsafe_allow_html=True)

# --- HÀM KẾT NỐI GOOGLE DRIVE (DÙNG SECRETS) ---
@st.cache_resource
def get_drive_service():
    """Kết nối Drive tự động qua Secrets (Cloud) hoặc File (Local)"""
    try:
        creds = None
        # Ưu tiên 1: Lấy từ Secrets trên Cloud
        if "gcp_service_account" in st.secrets:
            creds = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=SCOPES)
        # Ưu tiên 2: Lấy từ file local (nếu chạy trên máy tính cá nhân)
        elif os.path.exists('service_account.json'):
            creds = service_account.Credentials.from_service_account_file(
                'service_account.json', scopes=SCOPES)
        else:
            # Nếu không tìm thấy cả 2, trả về None nhưng không báo lỗi đỏ ngay để tránh spam màn hình
            return None
        
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Lỗi kết nối Drive: {e}")
        return None

# --- CÁC HÀM XỬ LÝ FILE TRÊN DRIVE ---
def get_file_id_by_name(filename):
    service = get_drive_service()
    if not service: return None
    # Tìm file trong folder chỉ định
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    try:
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if not items: return None
        return items[0]['id']
    except: return None

def load_csv_cloud(filename, cols):
    service = get_drive_service()
    if not service: return pd.DataFrame(columns=cols)
    
    file_id = get_file_id_by_name(filename)
    if file_id:
        try:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_csv(fh, dtype=str, on_bad_lines='skip').fillna("")
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols]
        except: return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_csv_cloud(filename, df):
    service = get_drive_service()
    if not service or df is None: return
    try:
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
        csv_buffer.seek(0)
        media = MediaIoBaseUpload(csv_buffer, mimetype='text/csv', resumable=True)
        file_id = get_file_id_by_name(filename)
        if file_id:
            service.files().update_media(media_body=media, fileId=file_id).execute()
        else:
            meta = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
            service.files().create(body=meta, media_body=media, fields='id').execute()
    except Exception as e: st.error(f"Lỗi lưu file: {e}")

def upload_bytes_to_drive(file_obj, filename, mime_type):
    service = get_drive_service()
    if not service: return None
    try:
        media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
        meta = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
        file = service.files().create(body=meta, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"Upload lỗi: {e}")
        return None

def get_file_content_as_bytes(file_id):
    service = get_drive_service()
    if not service or not file_id: return None
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        return fh
    except: return None

# --- HELPER FUNCTIONS ---
def safe_str(val): return str(val).strip() if val else ""
def to_float(val):
    try:
        s = str(val).replace(",", "").replace("¥","").replace("$","").replace("VND","")
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return max([float(n) for n in nums]) if nums else 0.0
    except: return 0.0
def fmt_num(x): 
    try: return "{:,.0f}".format(float(x))
    except: return "0"
def clean_lookup_key(s): return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower() if s else ""
def calc_eta(date_str, lead):
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        d = int(re.findall(r'\d+', str(lead))[0]) if re.findall(r'\d+', str(lead)) else 0
        return (dt + timedelta(days=d)).strftime("%d/%m/%Y")
    except: return ""

try: from openpyxl import load_workbook
except: pass 

# --- TÊN FILE DỮ LIỆU ---
CUSTOMERS_CSV = "crm_customers.csv"
SUPPLIERS_CSV = "crm_suppliers.csv"
PURCHASES_CSV = "crm_purchases.csv"
SHARED_HISTORY_CSV = "crm_shared_quote_history.csv" 
TRACKING_CSV = "crm_order_tracking.csv"
PAYMENT_CSV = "crm_payment_tracking.csv"
PAID_HISTORY_CSV = "crm_paid_history.csv"
DB_SUPPLIER_ORDERS = "db_supplier_orders.csv"
DB_CUSTOMER_ORDERS = "db_customer_orders.csv"
TEMPLATE_FILE_NAME = "AAA-QUOTATION.xlsx"

# --- ĐỊNH NGHĨA CỘT ---
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SHARED_HISTORY_COLS = ["history_id", "date", "quote_no", "customer"] + QUOTE_KH_COLUMNS + ["pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]

# =============================================================================
# KHỞI TẠO STATE & LOAD DATA
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
        st.session_state[f"pct_{k}"] = "0"

# LOAD DỮ LIỆU TỪ DRIVE
customers_df = load_csv_cloud(CUSTOMERS_CSV, MASTER_COLUMNS)
suppliers_df = load_csv_cloud(SUPPLIERS_CSV, MASTER_COLUMNS)
purchases_df = load_csv_cloud(PURCHASES_CSV, PURCHASE_COLUMNS)
shared_history_df = load_csv_cloud(SHARED_HISTORY_CSV, SHARED_HISTORY_COLS)
tracking_df = load_csv_cloud(TRACKING_CSV, TRACKING_COLS)
payment_df = load_csv_cloud(PAYMENT_CSV, PAYMENT_COLS)
paid_history_df = load_csv_cloud(PAID_HISTORY_CSV, PAYMENT_COLS)
db_supplier_orders = load_csv_cloud(DB_SUPPLIER_ORDERS, [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
db_customer_orders = load_csv_cloud(DB_CUSTOMER_ORDERS, [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

# =============================================================================
# GIAO DIỆN CHÍNH
# =============================================================================
st.sidebar.title("CRM CLOUD")
admin_pwd = st.sidebar.text_input("Mật khẩu Admin", type="password")
is_admin = (admin_pwd == "admin")

if st.sidebar.button("🔄 LÀM MỚI DỮ LIỆU"): st.rerun()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", "🏭 KHO DATA & GIÁ", "💰 BÁO GIÁ", 
    "📑 QUẢN LÝ PO", "🚚 TRACKING", "📂 CẤU HÌNH"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH (REAL-TIME)")
    
    total_revenue = db_customer_orders['total_price'].apply(to_float).sum()
    total_po_ncc_cost = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    total_other_costs = 0.0
    if not shared_history_df.empty:
        for _, r in shared_history_df.iterrows():
            try:
                gap = to_float(r['gap']) * 0.6
                others = to_float(r['end_user_val']) + to_float(r['buyer_val']) + \
                         to_float(r['import_tax_val']) + to_float(r['vat_val']) + \
                         to_float(r['mgmt_fee']) + (to_float(r['transportation']) * to_float(r['qty']))
                total_other_costs += (gap + others)
            except: pass
            
    total_profit = total_revenue - (total_po_ncc_cost + total_other_costs)

    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="card-3d bg-sales"><h3>DOANH THU</h3><h1>{fmt_num(total_revenue)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="card-3d bg-cost"><h3>CHI PHÍ & MUA HÀNG</h3><h1>{fmt_num(total_po_ncc_cost + total_other_costs)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="card-3d bg-profit"><h3>LỢI NHUẬN</h3><h1>{fmt_num(total_profit)}</h1></div>', unsafe_allow_html=True)

# --- TAB 2: KHO DATA ---
with tab2:
    col_p1, col_p2 = st.columns([1, 2])
    with col_p1:
        st.info("💡 Upload file Excel hàng hóa (kèm ảnh)")
        uploaded_pur = st.file_uploader("Import Excel Purchases", type=["xlsx"])
        
        if uploaded_pur and st.button("Bắt đầu Import"):
            with st.spinner("Đang upload dữ liệu lên Drive..."):
                try:
                    wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                    img_map = {}
                    # Xử lý ảnh trong Excel
                    for img in getattr(ws, '_images', []):
                        r_idx = img.anchor._from.row + 1
                        img_bytes = io.BytesIO(img._data())
                        img_name = f"img_row_{r_idx}_{int(time.time())}.png"
                        fid = upload_bytes_to_drive(img_bytes, img_name, "image/png")
                        if fid: img_map[r_idx] = fid

                    # Xử lý dữ liệu
                    uploaded_pur.seek(0)
                    df_ex = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                    rows = []
                    for i, r in df_ex.iterrows():
                        r_idx = i + 2
                        item = {
                            "no": safe_str(r.iloc[0]), "item_code": safe_str(r.iloc[1]), 
                            "item_name": safe_str(r.iloc[2]), "specs": safe_str(r.iloc[3]),
                            "qty": fmt_num(to_float(r.iloc[4])), "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                            "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                            "buying_price_vnd": fmt_num(to_float(r.iloc[8])), "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                            "leadtime": safe_str(r.iloc[10]), "supplier_name": safe_str(r.iloc[11]), 
                            "image_path": img_map.get(r_idx, ""),
                            "type": safe_str(r.iloc[13]) if len(r)>13 else "", "nuoc": safe_str(r.iloc[14]) if len(r)>14 else ""
                        }
                        if item["item_code"]: rows.append(item)
                    
                    purchases_df = pd.DataFrame(rows)
                    save_csv_cloud(PURCHASES_CSV, purchases_df)
                    st.success(f"✅ Đã import {len(rows)} sản phẩm!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")

        st.divider(); st.write("📸 Cập nhật ảnh lẻ")
        up_img = st.file_uploader("Chọn ảnh", type=["png","jpg"])
        code_up = st.text_input("Mã Item cần gán ảnh")
        if st.button("Upload Ảnh") and up_img and code_up:
            fid = upload_bytes_to_drive(up_img, f"prod_{code_up}.png", up_img.type)
            if fid:
                mask = purchases_df['item_code'] == code_up
                if mask.any():
                    purchases_df.loc[mask, 'image_path'] = fid
                    save_csv_cloud(PURCHASES_CSV, purchases_df)
                    st.success("Đã cập nhật ảnh!")

    with col_p2:
        search = st.text_input("🔍 Tìm kiếm hàng hóa")
        df_show = purchases_df.copy()
        if search:
            df_show = df_show[df_show['item_code'].str.contains(search, case=False) | df_show['item_name'].str.contains(search, case=False)]
        st.dataframe(df_show.drop(columns=['image_path']), use_container_width=True, hide_index=True)
        
        st.write("🖼️ **Xem ảnh sản phẩm:**")
        sel_code = st.selectbox("Chọn mã để xem ảnh:", [""] + df_show['item_code'].unique().tolist())
        if sel_code:
            row = df_show[df_show['item_code'] == sel_code]
            if not row.empty:
                iid = row.iloc[0]['image_path']
                if iid:
                    ibytes = get_file_content_as_bytes(iid)
                    if ibytes: st.image(ibytes, width=300)
                    else: st.warning("Lỗi tải ảnh")
                else: st.info("Chưa có ảnh")

# --- TAB 3: BÁO GIÁ ---
with tab3:
    c1, c2 = st.columns([2, 1])
    with c1:
        sel_cust = st.selectbox("Khách hàng", [""] + customers_df["short_name"].tolist())
        quote_name = st.text_input("Tên Báo Giá")
    
    # Tham số
    c_p = st.columns(7)
    pct_end = c_p[0].text_input("EndUser %", st.session_state.pct_end)
    pct_buy = c_p[1].text_input("Buyer %", st.session_state.pct_buy)
    pct_tax = c_p[2].text_input("Tax %", st.session_state.pct_tax)
    pct_vat = c_p[3].text_input("VAT %", st.session_state.pct_vat)
    pct_pay = c_p[4].text_input("Payback %", st.session_state.pct_pay)
    pct_mgmt = c_p[5].text_input("Mgmt %", st.session_state.pct_mgmt)
    val_trans = c_p[6].text_input("Trans (VND)", st.session_state.pct_trans)
    
    st.session_state.pct_end = pct_end; st.session_state.pct_buy = pct_buy
    st.session_state.pct_tax = pct_tax; st.session_state.pct_vat = pct_vat
    st.session_state.pct_pay = pct_pay; st.session_state.pct_mgmt = pct_mgmt
    st.session_state.pct_trans = val_trans

    # Bảng báo giá
    if st.button("✨ Reset Bảng"): st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS); st.rerun()
    edited_quote = st.data_editor(st.session_state.current_quote_df, num_rows="dynamic", use_container_width=True, key="quote_editor")
    
    # Tính toán tự động
    pend=to_float(pct_end)/100; pbuy=to_float(pct_buy)/100; ptax=to_float(pct_tax)/100
    pvat=to_float(pct_vat)/100; ppay=to_float(pct_pay)/100; pmgmt=to_float(pct_mgmt)/100
    gtrans=to_float(val_trans)
    
    df_temp = edited_quote.copy()
    for i, r in df_temp.iterrows():
        qty=to_float(r.get("qty",0)); buy=to_float(r.get("buying_price_vnd",0))
        ap=to_float(r.get("ap_price",0)); unit=to_float(r.get("unit_price",0))
        trans = gtrans if gtrans > 0 else to_float(r.get("transportation",0))
        
        t_buy=qty*buy; ap_tot=ap*qty; total=unit*qty; gap=total-ap_tot
        end_val=ap_tot*pend; buyer_val=total*pbuy; tax_val=t_buy*ptax; vat_val=total*pvat
        mgmt_val=total*pmgmt; pay_val=gap*ppay; tot_trans=trans*qty
        
        cost = t_buy + gap + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
        prof = total - cost + pay_val
        pct = (prof/total*100) if total else 0
        
        df_temp.at[i,"transportation"]=fmt_num(trans); df_temp.at[i,"total_price_vnd"]=fmt_num(total)
        df_temp.at[i,"profit_vnd"]=fmt_num(prof); df_temp.at[i,"profit_pct"]="{:.2f}%".format(pct)
        df_temp.at[i,"total_buying_price_vnd"]=fmt_num(t_buy)

    if not df_temp.equals(st.session_state.current_quote_df):
        st.session_state.current_quote_df = df_temp; st.rerun()

    c_btn1, c_btn2 = st.columns(2)
    if c_btn1.button("💾 LƯU LỊCH SỬ (CLOUD)"):
        if not quote_name: st.error("Nhập tên báo giá!")
        else:
            new_row = st.session_state.current_quote_df.copy()
            new_row["history_id"] = f"{quote_name}_{int(time.time())}"
            new_row["date"] = datetime.now().strftime("%d/%m/%Y")
            new_row["quote_no"] = quote_name; new_row["customer"] = sel_cust
            new_row["pct_end"]=pct_end; new_row["pct_buy"]=pct_buy; new_row["pct_trans"]=val_trans
            
            upd = pd.concat([shared_history_df, new_row], ignore_index=True)
            save_csv_cloud(SHARED_HISTORY_CSV, upd)
            st.success("Đã lưu lên Cloud! Mọi người đều thấy.")

    if c_btn2.button("📥 XUẤT FILE EXCEL"):
        # Logic xuất file (giản lược)
        out = io.BytesIO()
        st.session_state.current_quote_df.to_excel(out, index=False)
        st.download_button("Tải file", out.getvalue(), f"Quote_{quote_name}.xlsx")

# --- TAB 4: PO & TRACKING ---
with tab4:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("PO NCC")
        po_ncc = st.text_input("Số PO NCC"); supp = st.selectbox("Nhà cung cấp", [""]+suppliers_df["short_name"].tolist())
        # Đã thêm key để tránh lỗi Duplicate
        edited_ncc = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", key="po_ncc_editor")
        if st.button("Xác nhận PO NCC"):
            if po_ncc:
                final = edited_ncc.copy(); final["po_number"]=po_ncc; final["supplier"]=supp
                final["total_vnd"] = final.apply(lambda x: fmt_num(to_float(x["qty"])*to_float(x["price_vnd"])), axis=1)
                
                db_supplier_orders = pd.concat([db_supplier_orders, final], ignore_index=True)
                save_csv_cloud(DB_SUPPLIER_ORDERS, db_supplier_orders)
                st.success("Đã lưu PO NCC")

    with c2:
        st.subheader("PO Khách Hàng")
        po_cust = st.text_input("Số PO Khách"); cust = st.selectbox("Khách hàng PO", [""]+customers_df["short_name"].tolist())
        po_files = st.file_uploader("Upload File PO", accept_multiple_files=True)
        
        if st.button("Lưu PO Khách") and po_cust:
            fids = []
            for f in po_files:
                fid = upload_bytes_to_drive(f, f"PO_{po_cust}_{f.name}", f.type)
                if fid: fids.append(fid)
            
            new_po = pd.DataFrame([{"po_number": po_cust, "customer": cust, "order_date": datetime.now().strftime("%d/%m/%Y"), "pdf_path": json.dumps(fids), "total_price": "0"}])
            db_customer_orders = pd.concat([db_customer_orders, new_po], ignore_index=True)
            save_csv_cloud(DB_CUSTOMER_ORDERS, db_customer_orders)
            
            new_trk = pd.DataFrame([{"po_no": po_cust, "partner": cust, "status": "Đang đợi hàng về", "finished": "0"}])
            tracking_df = pd.concat([tracking_df, new_trk], ignore_index=True)
            save_csv_cloud(TRACKING_CSV, tracking_df)
            st.success("Đã lưu PO Khách & Tạo Tracking")

# --- TAB 5: TRACKING ---
with tab5:
    st.subheader("Theo dõi đơn hàng")
    edt_track = st.data_editor(tracking_df[tracking_df["finished"]=="0"], num_rows="dynamic", key="trk_edt")
    if st.button("Cập nhật trạng thái"):
        save_csv_cloud(TRACKING_CSV, edt_track); st.success("Đã cập nhật!")
    
    st.divider(); st.write("📸 Upload Proof")
    tid = st.text_input("ID Tracking (cột 'no')")
    pfiles = st.file_uploader("Ảnh bằng chứng", accept_multiple_files=True)
    if st.button("Upload Proof") and tid and pfiles:
        idx = tracking_df.index[tracking_df['no']==tid].tolist()
        if idx:
            cur = tracking_df.at[idx[0], "proof_image"]
            lst = json.loads(cur) if cur else []
            for f in pfiles:
                fid = upload_bytes_to_drive(f, f"PROOF_{tid}_{f.name}", f.type)
                if fid: lst.append(fid)
            tracking_df.at[idx[0], "proof_image"] = json.dumps(lst)
            save_csv_cloud(TRACKING_CSV, tracking_df); st.success("OK")

    if st.button("Xem Proof") and tid:
        idx = tracking_df.index[tracking_df['no']==tid].tolist()
        if idx:
            try:
                for i in json.loads(tracking_df.at[idx[0], "proof_image"]):
                    st.image(get_file_content_as_bytes(i), width=200)
            except: st.warning("Không có ảnh")

# --- TAB 6: CẤU HÌNH ---
with tab6:
    st.info(f"Đang kết nối Drive Folder ID: {DRIVE_FOLDER_ID}")
    c1, c2 = st.columns(2)
    with c1:
        st.write("Khách hàng")
        # Đã thêm key để tránh lỗi Duplicate
        ed_c = st.data_editor(customers_df, num_rows="dynamic", key="cust_master_editor")
        if is_admin and st.button("Lưu KH"): save_csv_cloud(CUSTOMERS_CSV, ed_c); st.success("Saved")
    with c2:
        st.write("Nhà cung cấp")
        # Đã thêm key để tránh lỗi Duplicate
        ed_s = st.data_editor(suppliers_df, num_rows="dynamic", key="supp_master_editor")
        if is_admin and st.button("Lưu NCC"): save_csv_cloud(SUPPLIERS_CSV, ed_s); st.success("Saved")
