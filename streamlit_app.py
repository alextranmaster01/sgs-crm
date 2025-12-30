import re
import ast
from datetime import datetime, timedelta

# =============================================================================
# COPIED FUNCTIONS FROM V4800 (CORE LOGIC)
# =============================================================================

def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.startswith("['") and s.endswith("']"):
        try:
            eval_s = ast.literal_eval(s)
            if isinstance(eval_s, list) and len(eval_s) > 0:
                return str(eval_s[0])
        except: pass
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    return "" if s.lower() == 'nan' else s

def safe_filename(s): return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))

def to_float(val):
    try:
        if isinstance(val, (int, float)): return float(val)
        clean = str(val).replace(",", "").replace("%", "").strip()
        if clean == "": return 0.0
        return float(clean)
    except: return 0.0

def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"

def clean_lookup_key(s):
    if s is None: return ""
    s_str = str(s)
    try:
        f = float(s_str)
        if f.is_integer():
            s_str = str(int(f))
    except:
        pass
    return re.sub(r'\s+', '', s_str).lower()

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper().replace(",", "")
    try: return float(s)
    except: pass
    if not s.startswith("="): return 0.0
    expr = s[1:]
    expr = expr.replace("BUYING PRICE", str(buying_price))
    expr = expr.replace("BUY", str(buying_price))
    expr = expr.replace("AP PRICE", str(ap_price))
    expr = expr.replace("AP", str(ap_price))
    allowed = "0123456789.+-*/()"
    for c in expr:
        if c not in allowed: return 0.0
    try: return float(eval(expr))
    except: return 0.0

def calc_eta(order_date_str, leadtime_val):
    try:
        dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_supabase()

# Mapping Table Names (Giả định bạn đã tạo table trên Supabase với schema tương tự CSV)
TABLES = {
    "purchases": "crm_purchases",
    "customers": "crm_customers",
    "suppliers": "crm_suppliers",
    "sales_history": "crm_sales_history",
    "tracking": "crm_order_tracking",
    "payment": "crm_payment_tracking",
    "paid_history": "crm_paid_history",
    "supplier_orders": "db_supplier_orders",
    "customer_orders": "db_customer_orders"
}

def load_data(table_key):
    """Thay thế load_csv"""
    try:
        response = supabase.table(TABLES[table_key]).select("*").execute()
        df = pd.DataFrame(response.data)
        return df
    except Exception as e:
        st.error(f"Lỗi tải dữ liệu {table_key}: {e}")
        return pd.DataFrame()

def save_data(table_key, df, key_col='id'):
    """Thay thế save_csv. Lưu ý: Supabase cần upsert hoặc insert."""
    try:
        data = df.to_dict(orient='records')
        # Xóa dữ liệu cũ hoặc Upsert tùy chiến lược (Ở đây dùng upsert đơn giản)
        supabase.table(TABLES[table_key]).upsert(data).execute()
        st.toast(f"Đã lưu dữ liệu vào {TABLES[table_key]}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# --- GOOGLE DRIVE CONNECTION (OAUTH2) ---
def get_drive_service():
    creds = Credentials(
        None,
        refresh_token=st.secrets["google"]["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=st.secrets["google"]["client_id"],
        client_secret=st.secrets["google"]["client_secret"]
    )
    return build('drive', 'v3', credentials=creds)

def upload_to_drive(file_obj, filename, folder_type="images"):
    try:
        service = get_drive_service()
        folder_id = st.secrets["google"][f"folder_id_{folder_type}"]
        
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype='application/octet-stream')
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        return file.get('webContentLink') # Trả về link file
    except Exception as e:
        st.error(f"Lỗi Upload Drive: {e}")
        return None
    import streamlit as st
import pandas as pd
from datetime import datetime
import backend
import logic  # Import các hàm logic gốc

# Cấu hình trang (Giao diện rộng)
st.set_page_config(page_title="SGS CRM V4800 - ONLINE", layout="wide", page_icon="🪶")

# --- CSS TÙY CHỈNH (Mô phỏng giao diện Tkinter cũ) ---
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #ecf0f1; border-radius: 4px 4px 0 0; padding: 10px 20px; font-weight: bold;
    }
    .stTabs [aria-selected="true"] { background-color: #3498db; color: white; }
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 20px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# --- KHỞI TẠO SESSION STATE ---
if 'quote_df' not in st.session_state:
    st.session_state.quote_df = pd.DataFrame(columns=["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"])

# --- HEADER ---
st.title("SGS CRM V4800 - FINAL FULL FEATURES (ONLINE)")

# --- TABS LAYOUT ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Tổng quan", 
    "💰 Báo giá NCC (DB Giá)", 
    "📝 Báo giá KH", 
    "📦 Đơn đặt hàng", 
    "🚚 Theo dõi & Thanh toán", 
    "⚙️ Master Data"
])

# =============================================================================
# TAB 1: DASHBOARD
# =============================================================================
with tab1:
    st.subheader("DASHBOARD KINH DOANH")
    col_act, col_reset = st.columns([8, 2])
    with col_act:
        if st.button("🔄 CẬP NHẬT DATA", type="primary"):
            st.cache_data.clear()
            st.rerun()
    
    # Load Data Snapshot
    db_cust_orders = backend.load_data("customer_orders")
    sales_history = backend.load_data("sales_history")
    payment_df = backend.load_data("payment")
    paid_history = backend.load_data("paid_history")

    # Tính toán Metrics (Logic cũ)
    rev = db_cust_orders['total_price'].apply(logic.to_float).sum() if not db_cust_orders.empty else 0
    profit = sales_history['profit'].apply(logic.to_float).sum() if not sales_history.empty else 0
    cost = rev - profit
    paid_count = len(paid_history)
    unpaid_count = len(payment_df[payment_df['status'] != "Đã thanh toán"])

    # Hiển thị (Màu sắc mô phỏng ảnh)
    m1, m2, m3 = st.columns(3)
    m1.info(f"**TỔNG DOANH THU**\n\n# {logic.fmt_num(rev)}")
    m2.warning(f"**TỔNG CHI PHÍ**\n\n# {logic.fmt_num(cost)}")
    m3.success(f"**LỢI NHUẬN**\n\n# {logic.fmt_num(profit)}")

    m4, m5 = st.columns(2)
    m4.success(f"**TỔNG PO ĐÃ THANH TOÁN**: {paid_count}")
    m5.error(f"**TỔNG PO CHƯA THANH TOÁN**: {unpaid_count}")

# =============================================================================
# TAB 2: BÁO GIÁ NCC (DB GIÁ) - AUTO EXTRACT & UPLOAD IMAGES
# =============================================================================
with tab2:
    import time
    import io
    from openpyxl import load_workbook

    st.subheader("Database Giá Nhà Cung Cấp (Tự động tách ảnh từ Excel)")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file:
            if st.button("🚀 BẮT ĐẦU IMPORT & TÁCH ẢNH", type="primary"):
                status_box = st.status("Đang xử lý file Excel...", expanded=True)
                try:
                    # 1. Đọc dữ liệu văn bản bằng Pandas
                    status_box.write("📖 Đang đọc dữ liệu văn bản...")
                    df_raw = pd.read_excel(uploaded_file, header=None, dtype=str).fillna("")
                    
                    # Tìm dòng tiêu đề
                    start_row = 0
                    for i in range(min(20, len(df_raw))):
                        row_str = str(df_raw.iloc[i].values).lower()
                        if 'item code' in row_str or 'mã hàng' in row_str:
                            start_row = i + 1
                            break
                    
                    # 2. Đọc hình ảnh bằng Openpyxl
                    status_box.write("🖼️ Đang quét và tách hình ảnh từ file Excel...")
                    uploaded_file.seek(0) 
                    wb = load_workbook(uploaded_file, data_only=True)
                    ws = wb.active
                    
                    image_map = {}
                    if hasattr(ws, '_images'):
                        for img in ws._images:
                            row_idx = img.anchor._from.row
                            img_bytes = img._data()
                            image_map[row_idx] = img_bytes
                            
                    status_box.write(f"✅ Đã tìm thấy {len(image_map)} ảnh trong file.")

                    # 3. Ghép dữ liệu & Upload ảnh
                    data_clean = []
                    total_rows = len(df_raw) - start_row
                    prog_bar = status_box.progress(0)
                    
                    for idx, i in enumerate(range(start_row, len(df_raw))):
                        prog_bar.progress((idx + 1) / total_rows)
                        row = df_raw.iloc[i]
                        
                        def get(col_idx): 
                            return logic.safe_str(row[col_idx]) if col_idx < len(row) else ""
                        
                        code_val = get(1) # Cột B
                        if not code_val: continue 

                        # --- XỬ LÝ ẢNH ---
                        final_img_link = ""
                        
                        # Ưu tiên 1: Ảnh dán trong Excel (Embedded)
                        if i in image_map:
                            img_data = image_map[i]
                            filename = f"{logic.safe_filename(code_val)}.png"
                            file_obj = io.BytesIO(img_data)
                            
                            status_box.write(f"☁️ Upload ảnh: {code_val}...")
                            link = backend.upload_to_drive(file_obj, filename) # Upload lên Drive
                            if link: final_img_link = link
                        
                        # Ưu tiên 2: Link ảnh cũ (nếu không có ảnh mới)
                        else:
                            old_path = get(12)
                            if "http" in old_path: # Chỉ lấy nếu là link online
                                final_img_link = old_path

                        # --- TẠO ITEM ---
                        item = {
                            "no": get(0),                     # A
                            "item_code": code_val,            # B
                            "item_name": get(2),              # C
                            "specs": get(3),                  # D
                            "qty": logic.fmt_num(logic.to_float(get(4))),           # E
                            "buying_price_rmb": logic.fmt_num(logic.to_float(get(5))), # F
                            "total_buying_price_rmb": logic.fmt_num(logic.to_float(get(6))), # G
                            "exchange_rate": logic.fmt_num(logic.to_float(get(7))),    # H
                            "buying_price_vnd": logic.fmt_num(logic.to_float(get(8))), # I
                            "total_buying_price_vnd": logic.fmt_num(logic.to_float(get(9))), # J
                            "leadtime": get(10),              # K
                            "supplier_name": get(11),         # L
                            "image_path": final_img_link,     # M (Link ảnh để hiển thị)
                            
                            "_clean_code": logic.clean_lookup_key(code_val),
                            "_clean_specs": logic.clean_lookup_key(get(3)),
                            "_clean_name": logic.clean_lookup_key(get(2))
                        }
                        data_clean.append(item)
                    
                    # 4. Lưu vào Database
                    if data_clean:
                        df_final = pd.DataFrame(data_clean)
                        backend.save_data("purchases", df_final)
                        
                        status_box.update(label="✅ Import hoàn tất!", state="complete", expanded=False)
                        st.success(f"Đã xử lý xong {len(df_final)} dòng.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        status_box.update(label="⚠️ Lỗi dữ liệu", state="error")
                        st.error("Không tìm thấy dữ liệu hợp lệ.")

                except Exception as e:
                    st.error(f"❌ Lỗi: {e}") 

    # Load Data & Hiển thị
    df_pur = backend.load_data("purchases")
    
    # Tìm kiếm
    search_term = st.text_input("🔍 Tìm kiếm code, tên...", key="search_pur")
    if search_term and not df_pur.empty:
        mask = df_pur.apply(lambda x: x.astype(str).str.contains(search_term, case=False, na=False)).any(axis=1)
        df_pur = df_pur[mask]

    # --- CẤU HÌNH HIỂN THỊ CỘT (QUAN TRỌNG NHẤT) ---
    column_cfg = {
        # Cấu hình cột image_path thành dạng ImageColumn để hiện ảnh
        "image_path": st.column_config.ImageColumn(
            "Images", # Tên cột hiển thị
            help="Hình ảnh sản phẩm",
            width="small" # Kích thước ảnh (small, medium, large)
        ),
        "total_buying_price_vnd": st.column_config.NumberColumn("Total VND", format="%d"),
        "buying_price_vnd": st.column_config.NumberColumn("Price VND", format="%d"),
         "_clean_code": None, "_clean_specs": None, "_clean_name": None # Ẩn cột rác
    }

    # Thứ tự cột hiển thị (Đúng 100% theo Excel: No -> Code ... -> Images)
    cols_order = [
        "no", "item_code", "item_name", "specs", "qty", 
        "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
        "buying_price_vnd", "total_buying_price_vnd", "leadtime", 
        "supplier_name", "image_path"
    ]

    edited_pur = st.data_editor(
        df_pur, 
        num_rows="dynamic", 
        use_container_width=True,
        key="editor_pur",
        column_config=column_cfg, # Áp dụng config ảnh
        column_order=cols_order   # Áp dụng thứ tự cột
    )
    
    if st.button("💾 Lưu thay đổi DB NCC", type="primary"):
        backend.save_data("purchases", edited_pur)
# =============================================================================
# TAB 3: BÁO GIÁ KHÁCH HÀNG (CORE LOGIC)
# =============================================================================
with tab3:
    t3_sub1, t3_sub2 = st.tabs(["Tạo Báo Giá", "Tra Cứu Lịch Sử"])
    
    with t3_sub1:
        # 1. Thông tin chung
        with st.expander("1. Thông tin chung & Tham số", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            cust_list = backend.load_data("customers")["short_name"].tolist() if not backend.load_data("customers").empty else []
            curr_cust = c1.selectbox("Khách hàng:", options=[""] + cust_list)
            quote_name = c2.text_input("Tên Báo Giá:")
            
            # Param inputs
            c3.markdown("**Chi phí (%)**")
            p_end = c3.number_input("End User (%)", value=0.0)
            p_buy = c3.number_input("Buyer (%)", value=0.0)
            p_tax = c3.number_input("Tax (%)", value=0.0)
            
            c4.markdown("**Chi phí khác**")
            p_vat = c4.number_input("VAT (%)", value=0.0)
            p_trans = c4.number_input("Trans (VND)", value=0)

        # 2. Tools
        col_func, col_calc = st.columns([1, 1])
        with col_func:
            if st.button("✨ TẠO MỚI (RESET)"):
                st.session_state.quote_df = pd.DataFrame(columns=st.session_state.quote_df.columns)
                st.rerun()
            uploaded_rfq = st.file_uploader("📂 Import RFQ (Excel)", type=['xlsx'])
            if uploaded_rfq:
                 # Logic Import RFQ (Simulated from original code)
                 df_rfq = pd.read_excel(uploaded_rfq, header=None).fillna("")
                 # ... (Adapt mapping logic here) ...
                 st.success("Đã load RFQ (Logic mapping cần được active)")

        # 3. Main Quote Table (Editable)
        st.write("### Chi tiết Báo Giá")
        edited_quote = st.data_editor(st.session_state.quote_df, num_rows="dynamic", use_container_width=True)
        st.session_state.quote_df = edited_quote

        # 4. Calculation Button (Triggering logic.recalculate equivalent)
        if st.button("🔄 TÍNH LỢI NHUẬN", type="primary"):
            # Apply Recalculate Logic (Copied logic adapted to Iterate DataFrame)
            df = st.session_state.quote_df
            for i, r in df.iterrows():
                qty = logic.to_float(r["qty"])
                buy_vnd = logic.to_float(r["buying_price_vnd"])
                t_buy = qty * buy_vnd
                
                # Logic Trans
                use_trans = p_trans if p_trans > 0 else logic.to_float(r["transportation"])
                
                # Calculate Costs based on Inputs
                ap_price = logic.to_float(r["ap_price"])
                unit_price = logic.to_float(r["unit_price"])
                
                ap_tot = ap_price * qty
                total_sell = unit_price * qty
                gap = total_sell - ap_tot
                
                tax_val = t_buy * (p_tax/100)
                buyer_val = total_sell * (p_buy/100)
                vat_val = total_sell * (p_vat/100)
                end_val = ap_tot * (p_end/100)
                trans_total = use_trans * qty
                
                # Update DF
                df.at[i, "total_price_vnd"] = logic.fmt_num(total_sell)
                df.at[i, "profit_vnd"] = logic.fmt_num(total_sell - (t_buy + gap + end_val + buyer_val + tax_val + vat_val + trans_total))
                
            st.session_state.quote_df = df
            st.success("Đã tính toán xong!")
            st.rerun()

    with t3_sub2:
        st.write("Tra cứu lịch sử (Kết nối Supabase `crm_sales_history`)")
        # Logic search history implementation...

# =============================================================================
# TAB 4: ĐƠN ĐẶT HÀNG
# =============================================================================
with tab4:
    t4_sub1, t4_sub2 = st.tabs(["1. Đặt hàng NCC (Chi phí)", "2. PO Khách Hàng (Doanh thu)"])
    
    with t4_sub1:
        st.info("Module tạo PO cho Nhà Cung Cấp")
        col_po1, col_po2 = st.columns(2)
        po_ncc_num = col_po1.text_input("Số PO NCC")
        supp_select = col_po2.selectbox("Chọn NCC", backend.load_data("suppliers")["short_name"].tolist())
        
        # Temp Order Editor
        if 'temp_supp_order' not in st.session_state:
            st.session_state.temp_supp_order = pd.DataFrame(columns=["item_code", "qty", "price_rmb", "total_rmb", "eta"])
            
        edited_supp_order = st.data_editor(st.session_state.temp_supp_order, num_rows="dynamic")
        st.session_state.temp_supp_order = edited_supp_order
        
        if st.button("🚀 Đã Đặt Hàng NCC (Tạo Tracking)"):
            # Logic Save to `db_supplier_orders` & `crm_order_tracking`
            st.toast("Đã đặt hàng thành công!")

    with t4_sub2:
        st.info("Module tạo PO Khách Hàng")
        # Tương tự NCC nhưng mapping với `db_customer_orders`

# =============================================================================
# TAB 5: THEO DÕI & THANH TOÁN
# =============================================================================
with tab5:
    st.subheader("Trạng thái đơn hàng")
    
    # Load Tracking Data
    df_track = backend.load_data("tracking")
    
    # Filter
    status_filter = st.multiselect("Lọc trạng thái", options=df_track["status"].unique())
    if status_filter:
        df_track = df_track[df_track["status"].isin(status_filter)]
        
    edited_track = st.data_editor(df_track, key="tracking_editor", num_rows="dynamic")
    
    if st.button("Cập nhật Tracking"):
        backend.save_data("tracking", edited_track)
        
    st.divider()
    st.subheader("Quản lý Thanh Toán")
    df_pay = backend.load_data("payment")
    # Color highlighting logic for late payments
    st.dataframe(df_pay.style.apply(lambda x: ['background-color: #ffcccc' if x['status'] != 'Đã thanh toán' else '' for i in x], axis=1))

# =============================================================================
# TAB 6: MASTER DATA
# =============================================================================
with tab6:
    st.write("Quản lý danh mục Khách hàng & NCC")
    t6_1, t6_2 = st.tabs(["Khách Hàng", "Nhà Cung Cấp"])
    
    with t6_1:
        df_c = backend.load_data("customers")
        edited_c = st.data_editor(df_c, num_rows="dynamic", key="editor_cust")
        if st.button("Lưu Master KH"): backend.save_data("customers", edited_c)
        
    with t6_2:
        df_s = backend.load_data("suppliers")
        edited_s = st.data_editor(df_s, num_rows="dynamic", key="editor_supp")
        if st.button("Lưu Master NCC"): backend.save_data("suppliers", edited_s)







