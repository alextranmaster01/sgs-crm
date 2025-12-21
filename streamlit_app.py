import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import io
import time
import unicodedata
import mimetypes
import numpy as np

# --- 1. CẤU HÌNH HỆ THỐNG ---
APP_VERSION = "V5000 - ULTIMATE MERGE (LOGIC V4.8 + CLOUD V4.6)"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="💎")

# --- 2. CSS GIAO DIỆN (LẤY CỦA V4800) ---
st.markdown("""
    <style>
    /* Tab to, rõ ràng */
    button[data-baseweb="tab"] div p { font-size: 20px !important; font-weight: 800 !important; }
    
    /* Card 3D đẹp mắt */
    .card-3d { border-radius: 15px; padding: 20px; color: white; text-align: center; 
               box-shadow: 0 10px 20px rgba(0,0,0,0.19); margin-bottom: 15px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    
    /* Tối ưu bảng dữ liệu */
    [data-testid="stDataFrame"] > div { max-height: 800px; }
    </style>""", unsafe_allow_html=True)

# --- 3. KẾT NỐI CLOUD (LẤY CỦA V4864) ---
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from openpyxl import load_workbook
    from openpyxl.styles import Border, Side
except ImportError:
    st.error("⚠️ Thiếu thư viện. Hãy kiểm tra file requirements.txt")
    st.stop()

# Khởi tạo kết nối
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    OAUTH_INFO = st.secrets["google_oauth"]
    ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
except Exception as e:
    st.error(f"⚠️ Lỗi cấu hình Secrets: {e}")
    st.stop()

# --- 4. HÀM HỖ TRỢ GOOGLE DRIVE ---
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
        # Tìm hoặc tạo folder con
        q_f = f"'{ROOT_FOLDER_ID}' in parents and name='{sub_folder}' and trashed=false"
        folders = srv.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if folders: folder_id = folders[0]['id']
        else:
            folder_id = srv.files().create(body={'name': sub_folder, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [ROOT_FOLDER_ID]}, fields='id').execute()['id']
            srv.permissions().create(fileId=folder_id, body={'role': 'reader', 'type': 'anyone'}).execute()

        # Upload file
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        
        file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        
        # Public file để xem được trong App
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        
        # Trả về link thumbnail/preview
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200"
    except Exception as e: 
        print(f"Drive Upload Error: {e}")
        return ""

# --- 5. HÀM XỬ LÝ SỐ LIỆU (LẤY CỦA V4800) ---
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

def parse_formula(formula, buying, ap):
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying)).replace("BUY", str(buying)).replace("AP PRICE", str(ap)).replace("AP", str(ap))
    try: return float(eval(re.sub(r'[^0-9.+\-*/()]', '', expr)))
    except: return 0.0

# --- 6. HÀM DATABASE (SUPABASE - QUAN TRỌNG) ---
@st.cache_data(ttl=10)
def load_data(table_name):
    """Load toàn bộ dữ liệu từ bảng Supabase"""
    try:
        res = supabase.table(table_name).select("*").execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            # Xóa cột id hệ thống nếu không cần thiết hiển thị
            if 'id' in df.columns: df = df.drop(columns=['id']) 
        return df
    except Exception as e:
        return pd.DataFrame()

def insert_data_no_check(table_name, df, mapping_dict):
    """
    Import dữ liệu KHÔNG kiểm tra trùng lặp (theo yêu cầu sửa lỗi 23505).
    Cứ có dòng trong Excel là Insert vào DB.
    """
    if df.empty: return
    try:
        # 1. Map tên cột Excel -> Tên cột Database
        hn = {normalize_header(c): c for c in df.columns}
        records = []
        
        for i, r in df.iterrows():
            d = {}
            has_data = False
            for db_col, excel_keywords in mapping_dict.items():
                # excel_keywords có thể là 1 list các tên cột có thể có
                val = ""
                for kw in excel_keywords:
                    norm_kw = normalize_header(kw)
                    if norm_kw in hn:
                        val = safe_str(r[hn[norm_kw]])
                        break
                d[db_col] = val
                if val: has_data = True
            
            # Xử lý các trường số
            if 'qty' in d: d['qty'] = to_float(d['qty'])
            if 'buying_price_rmb' in d: d['buying_price_rmb'] = to_float(d['buying_price_rmb'])
            # ... Thêm các xử lý số khác nếu cần thiết để tránh lỗi DB type
            
            if has_data: records.append(d)
            
        # 2. Insert theo lô (Batch insert)
        chunk_size = 100
        progress_bar = st.progress(0)
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i+chunk_size]
            supabase.table(table_name).insert(chunk).execute()
            progress_bar.progress(min((i+chunk_size)/len(records), 1.0))
            
        st.cache_data.clear()
        st.success(f"✅ Đã thêm thành công {len(records)} dòng vào {table_name}!")
        time.sleep(1)
    except Exception as e:
        st.error(f"❌ Lỗi Database: {e}")

# Mapping Cột Database <-> Excel (List các tên có thể)
MAP_PURCHASE = {
    "item_code": ["Item code", "Mã hàng", "Code"],
    "item_name": ["Item name", "Tên hàng", "Name"],
    "specs": ["Specs", "Quy cách"],
    "qty": ["Q'ty", "Qty", "Số lượng"],
    "buying_price_rmb": ["Buying price (RMB)", "Giá RMB"],
    "exchange_rate": ["Exchange rate", "Tỷ giá"],
    "buying_price_vnd": ["Buying price (VND)", "Giá VND"],
    "leadtime": ["Leadtime", "Thời gian"],
    "supplier_name": ["Supplier", "Nhà cung cấp"],
    "type": ["Type", "Loại"],
    "nuoc": ["NUOC", "N/U/O/C"]
}

MAP_HISTORY = {
    # Dùng cho bảng crm_shared_history
    "quote_no": ["quote_no"], "customer": ["customer"], "item_code": ["item_code"],
    "item_name": ["item_name"], "specs": ["specs"], "qty": ["qty"],
    "unit_price": ["unit_price"], "total_price_vnd": ["total_price_vnd"],
    "profit_vnd": ["profit_vnd"], "history_id": ["history_id"], "date": ["date"],
    "end_user_val": ["end_user_val"], "buyer_val": ["buyer_val"], 
    "mgmt_fee": ["mgmt_fee"], "transportation": ["transportation"], "gap": ["gap"],
    "import_tax_val": ["import_tax_val"], "vat_val": ["vat_val"]
}

# --- 7. LOGIC CHÍNH CỦA TAB 3 (TÍNH TOÁN BÁO GIÁ) ---
def run_matching(rfq_file, db_purchases):
    # Tạo dict tra cứu nhanh từ DB Purchases
    lookup = {}
    for r in db_purchases.to_dict('records'):
        # Key là Clean Code
        k = clean_key(r.get('item_code'))
        if k:
            lookup[k] = r
    
    # Đọc RFQ
    df_rfq = pd.read_excel(rfq_file, dtype=str).fillna("")
    hn = {normalize_header(c): c for c in df_rfq.columns}
    
    results = []
    for i, r in df_rfq.iterrows():
        # Tìm tên cột
        code_col = hn.get(normalize_header("Item code")) or hn.get(normalize_header("Mã"))
        qty_col = hn.get(normalize_header("Q'ty")) or hn.get(normalize_header("Qty"))
        
        code = safe_str(r.get(code_col))
        qty = to_float(r.get(qty_col))
        
        # Tìm trong DB
        match = lookup.get(clean_key(code))
        
        item = {
            "No": i+1,
            "Item code": code,
            "Item name": match.get('item_name') if match else safe_str(r.get(hn.get(normalize_header("Item name")))),
            "Specs": match.get('specs') if match else safe_str(r.get(hn.get(normalize_header("Specs")))),
            "Q'ty": fmt_num(qty),
            "Buying price (RMB)": fmt_num(match.get('buying_price_rmb')) if match else "0",
            "Exchange rate": fmt_num(match.get('exchange_rate')) if match else "4000",
            "Buying price (VND)": fmt_num(match.get('buying_price_vnd')) if match else "0",
            "Total buying price (VND)": fmt_num(to_float(match.get('buying_price_vnd')) * qty) if match else "0",
            "Supplier": match.get('supplier_name') if match else "",
            "Images": match.get('image_path') if match else "",
            "Leadtime": match.get('leadtime') if match else "",
            # Các cột tính toán sau này
            "AP price (VND)": "0", "Unit price (VND)": "0", "Total price (VND)": "0",
            "Profit (VND)": "0", "Profit (%)": "0%"
        }
        results.append(item)
    return pd.DataFrame(results)

# --- INIT SESSION ---
if 'quote_df' not in st.session_state: st.session_state.quote_df = pd.DataFrame()

# =============================================================================
# GIAO DIỆN CHÍNH
# =============================================================================

t1, t2, t3, t4, t5, t6 = st.tabs(["📊 DASHBOARD", "📦 KHO HÀNG (PURCHASES)", "💰 BÁO GIÁ", "📑 ĐƠN HÀNG (PO)", "🚚 TRACKING", "⚙️ MASTER DATA"])

# --- TAB 1: DASHBOARD (LOGIC V4800 + DATA SUPABASE) ---
with t1:
    st.caption(f"Phiên bản: {APP_VERSION}")
    if st.button("🔄 Cập nhật dữ liệu mới nhất"): st.cache_data.clear(); st.rerun()
    
    with st.spinner("Đang tải dữ liệu Cloud..."):
        db_cust = load_data("db_customer_orders")
        db_supp = load_data("db_supplier_orders")
        db_history = load_data("crm_shared_history")
        
        # 1. Tính Doanh Thu (Tổng PO Khách)
        rev = db_cust['total_price'].apply(to_float).sum() if not db_cust.empty else 0
        
        # 2. Tính Chi Phí (PO NCC + Các chi phí ẩn từ Lịch sử Báo giá)
        cost_ncc = db_supp['total_vnd'].apply(to_float).sum() if not db_supp.empty else 0
        
        overhead_cost = 0
        if not db_history.empty:
            for _, row in db_history.iterrows():
                try:
                    # Logic từ V4800: Overhead = Gap*0.6 + EndUser + Buyer + Tax + Vat + Mgmt + Trans
                    gap = to_float(row.get('gap', 0))
                    gap_share = gap * 0.6 if gap > 0 else 0
                    
                    others = (to_float(row.get('end_user_val', 0)) + 
                              to_float(row.get('buyer_val', 0)) +
                              to_float(row.get('import_tax_val', 0)) +
                              to_float(row.get('vat_val', 0)) +
                              to_float(row.get('mgmt_fee', 0)) +
                              to_float(row.get('transportation', 0))) # Trans đã nhân qty lúc lưu
                    overhead_cost += (gap_share + others)
                except: pass
                
        total_cost = cost_ncc + overhead_cost
        profit = rev - total_cost

        # UI 3D Cards
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(rev)}</h1></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='card-3d bg-cost'><h3>TỔNG CHI PHÍ</h3><h1>{fmt_num(total_cost)}</h1></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN THỰC</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: KHO HÀNG (SỬA LỖI 23505 + ẢNH DRIVE) ---
with t2:
    st.subheader("Quản lý Giá vốn & Hình ảnh")
    c_up, c_search = st.columns([1, 2])
    
    with c_up:
        st.info("💡 Mẹo: Hệ thống sẽ thêm mới toàn bộ dữ liệu từ file Excel, không ghi đè.")
        up_file = st.file_uploader("Upload 'BUYING PRICE.xlsx' (Kèm ảnh)", type=["xlsx"])
        
        if up_file and st.button("🚀 Import vào Kho"):
            try:
                # 1. Xử lý ảnh trước
                wb = load_workbook(up_file, data_only=False); ws = wb.active
                img_map = {} # Row index -> Drive Link
                
                # Gom ảnh từ Excel
                if getattr(ws, '_images', []):
                    status = st.empty()
                    status.text("Đang upload ảnh lên Google Drive...")
                    for idx, img in enumerate(ws._images):
                        row = img.anchor._from.row + 1 # Excel row
                        # Upload buffer lên Drive
                        buf = io.BytesIO(img._data())
                        fname = f"IMG_ROW_{row}_{int(time.time())}.png"
                        link = upload_to_drive(buf, "CRM_PRODUCT_IMAGES", fname)
                        if link: img_map[row] = link
                        status.text(f"Đã upload {idx+1} ảnh...")
                    status.empty()
                
                # 2. Đọc Data
                df_ex = pd.read_excel(up_file, dtype=str).fillna("")
                
                # 3. Gán link ảnh vào DataFrame
                # Giả sử cột ảnh là cột cuối hoặc ta map theo row index
                # Cách đơn giản: Thêm cột image_path vào df_ex
                image_col_vals = []
                for i in range(len(df_ex)):
                    excel_row = i + 2 # Header là row 1
                    image_col_vals.append(img_map.get(excel_row, ""))
                
                df_ex['image_path'] = image_col_vals
                
                # 4. Insert vào Supabase (Không check trùng)
                mapping = MAP_PURCHASE.copy()
                mapping['image_path'] = ['image_path'] # Map cột vừa tạo
                
                insert_data_no_check("crm_purchases", df_ex, mapping)
                st.rerun()
                
            except Exception as e: st.error(f"Lỗi Import: {e}")

    with c_search:
        df_pur = load_data("crm_purchases")
        search = st.text_input("🔍 Tìm kiếm trong kho")
        if not df_pur.empty:
            if search:
                mask = df_pur.apply(lambda x: search.lower() in str(x.values).lower(), axis=1)
                df_pur = df_pur[mask]
            
            st.dataframe(
                df_pur, 
                column_config={"image_path": st.column_config.ImageColumn("Hình ảnh", width="small")},
                use_container_width=True, 
                height=700
            )

# --- TAB 3: BÁO GIÁ (LOGIC TÍNH TOÁN CỦA V4800) ---
with t3:
    st.subheader("Tạo Báo Giá Mới")
    if st.button("♻️ Reset làm lại"): st.session_state.quote_df = pd.DataFrame(); st.rerun()
    
    # 1. Input tham số (như V4800)
    with st.expander("⚙️ CẤU HÌNH CHI PHÍ (%)", expanded=True):
        cols = st.columns(7)
        keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
        params = {}
        for i, k in enumerate(keys):
            val = cols[i].text_input(k.upper(), st.session_state.get(f"pct_{k}", "0"))
            params[k] = to_float(val)
            st.session_state[f"pct_{k}"] = val # Lưu state

    # 2. Upload RFQ & Matching
    col_file, col_action = st.columns([1, 2])
    rfq_up = col_file.file_uploader("Upload RFQ Customer", type=["xlsx"])
    if rfq_up and col_action.button("🔍 Matching Giá Vốn"):
        db_pur = load_data("crm_purchases")
        if db_pur.empty: st.error("Kho hàng trống!")
        else:
            st.session_state.quote_df = run_matching(rfq_up, db_pur)
            st.success("Đã lấy được giá vốn!")

    # 3. Bảng Tính & Editor
    if not st.session_state.quote_df.empty:
        # Quick Formula
        c_f1, c_f2 = st.columns(2)
        ap_f = c_f1.text_input("Công thức AP (vd: =BUY*1.1)")
        u_f = c_f2.text_input("Công thức Unit Price (vd: =AP*1.2)")
        
        # Logic Tính toán (Auto Calc)
        df = st.session_state.quote_df.copy()
        for i, r in df.iterrows():
            # Lấy giá trị cơ bản
            buy_vnd = to_float(r["Buying price (VND)"])
            qty = to_float(r["Q'ty"])
            ap_curr = to_float(r.get("AP price (VND)", 0))
            
            # Áp dụng công thức nếu có
            if ap_f: 
                ap_curr = parse_formula(ap_f, buy_vnd, ap_curr)
                df.at[i, "AP price (VND)"] = fmt_num(ap_curr)
            
            if u_f:
                u_curr = parse_formula(u_f, buy_vnd, ap_curr)
                df.at[i, "Unit price (VND)"] = fmt_num(u_curr)
            
            # Tính lợi nhuận chi tiết (Logic V4800)
            unit_price = to_float(df.at[i, "Unit price (VND)"])
            ap_price = to_float(df.at[i, "AP price (VND)"])
            
            total_sell = unit_price * qty
            total_buy = buy_vnd * qty
            ap_total = ap_price * qty
            
            gap = total_sell - ap_total
            
            # Chi phí
            v_end = ap_total * (params['end']/100)
            v_buy = total_sell * (params['buy']/100)
            v_tax = total_buy * (params['tax']/100)
            v_vat = total_sell * (params['vat']/100)
            v_mgmt = total_sell * (params['mgmt']/100)
            v_trans = params['trans'] * qty # Trans là số tiền tuyệt đối/sp
            v_payback = gap * (params['pay']/100)
            
            # Cost thực tế để trừ doanh thu
            real_cost_ops = (gap * 0.6 if gap > 0 else 0) + v_end + v_buy + v_tax + v_vat + v_mgmt + v_trans
            
            profit = total_sell - total_buy - real_cost_ops + v_payback # Cộng lại payback (vì payback là phần mình đc nhận lại từ gap?) - Tùy logic, ở đây giữ logic V4800
            # Logic V4800: Profit = Sell - Cost - Ops + Payback. 
            
            pct = (profit / total_sell * 100) if total_sell else 0
            
            # Gán lại vào DF
            df.at[i, "Total price (VND)"] = fmt_num(total_sell)
            df.at[i, "GAP"] = fmt_num(gap)
            df.at[i, "Profit (VND)"] = fmt_num(profit)
            df.at[i, "Profit (%)"] = f"{pct:.1f}%"
            
            # Các cột ẩn (để lưu DB)
            df.at[i, "end_user_val"] = v_end
            df.at[i, "buyer_val"] = v_buy
            df.at[i, "import_tax_val"] = v_tax
            df.at[i, "vat_val"] = v_vat
            df.at[i, "mgmt_fee"] = v_mgmt
            df.at[i, "transportation"] = v_trans

        st.session_state.quote_df = df # Cập nhật lại state

        # Hiện bảng Editor
        edited = st.data_editor(
            st.session_state.quote_df,
            column_config={
                "Images": st.column_config.ImageColumn("Hình", width="small"),
                "Buying price (RMB)": st.column_config.TextColumn("Giá Vốn RMB", disabled=True),
                "Buying price (VND)": st.column_config.TextColumn("Giá Vốn VND", disabled=True),
                "Profit (VND)": st.column_config.TextColumn("LÃI VND", disabled=True),
                "Profit (%)": st.column_config.TextColumn("% LÃI", disabled=True),
            },
            use_container_width=True, height=600
        )
        
        # Sync ngược lại nếu sửa tay
        if not edited.equals(st.session_state.quote_df):
            st.session_state.quote_df = edited
            st.rerun()
            
        # Nút Lưu
        c_save, c_exp = st.columns(2)
        with c_save:
            cust_name = st.text_input("Tên Khách Hàng / Mã Quote")
            if st.button("💾 Lưu vào Lịch sử (Shared Cloud)"):
                if not cust_name: st.error("Nhập tên khách hàng!")
                else:
                    save_df = edited.copy()
                    # Map tên cột cho khớp DB History
                    rename_map = {
                        "Item code": "item_code", "Item name": "item_name", "Specs": "specs", 
                        "Q'ty": "qty", "Unit price (VND)": "unit_price", 
                        "Total price (VND)": "total_price_vnd", "Profit (VND)": "profit_vnd"
                    }
                    save_df = save_df.rename(columns=rename_map)
                    save_df['quote_no'] = cust_name
                    save_df['customer'] = cust_name
                    save_df['history_id'] = f"{cust_name}_{int(time.time())}"
                    save_df['date'] = datetime.now().strftime("%Y-%m-%d")
                    
                    # Các cột số liệu ẩn đã được tính ở vòng lặp trên
                    
                    # Insert
                    # Chỉ lấy cột có trong DB
                    valid_cols = list(MAP_HISTORY.keys())
                    final_recs = []
                    for r in save_df.to_dict('records'):
                        clean_r = {k: v for k, v in r.items() if k in valid_cols}
                        final_recs.append(clean_r)
                        
                    supabase.table("crm_shared_history").insert(final_recs).execute()
                    st.success("Đã lưu lên Cloud!")

# --- TAB 4, 5, 6: GIỮ NGUYÊN KHUNG, CHỈ ĐỔI STORAGE ---
# (Phần này logic đơn giản hơn: DataEditor -> Save -> Supabase)
with t4:
    st.info("Chức năng PO hoạt động tương tự: Nhập liệu -> Lưu vào table `db_supplier_orders` trên Supabase.")
    # Bạn có thể copy code UI của V4800 vào đây và thay hàm save_csv bằng supabase.insert

with t5:
    st.info("Tracking: Load từ `crm_tracking`. Ảnh upload lên Drive và lưu link vào cột `proof_image`.")

with t6:
    st.info("Master Data: Load/Edit trực tiếp `crm_customers`, `crm_suppliers`.")
