import streamlit as st
import pandas as pd
import os
import shutil
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import platform
import subprocess
from copy import copy

# --- THƯ VIỆN XỬ LÝ EXCEL & ĐỒ HỌA ---
try:
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
    from openpyxl.drawing.image import Image as OpenpyxlImage
    from openpyxl.utils import range_boundaries
    import matplotlib.pyplot as plt
except ImportError:
    st.error("Thiếu thư viện. Vui lòng chạy: pip install openpyxl matplotlib")

# Tắt cảnh báo
warnings.filterwarnings("ignore")

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO & VERSION
# =============================================================================
APP_VERSION = "V4800 - UPDATE V2.3 (FIXED)"
RELEASE_NOTE = """
- **Dashboard:** Hiển thị Tổng giá trị mua hàng & Chi tiết tiền mua theo NCC.
- **Báo giá Khách:** Fix Import hiển thị đúng giá trị, fix lỗi hiển thị None.
- **PO:** Fix lỗi lưu file PO Khách hàng (NameError).
- **Tracking:** Tab Lịch sử thanh toán & Edit Invoice.
"""

st.set_page_config(page_title=f"CRM V4800 - {APP_VERSION}", layout="wide", page_icon="💼")

# --- CSS TÙY CHỈNH (GIAO DIỆN LỚN) ---
st.markdown("""
    <style>
    /* Tăng kích thước Tab */
    button[data-baseweb="tab"] {
        font-size: 24px !important;
        padding: 20px !important;
        font-weight: bold !important;
    }
    /* Tăng kích thước tiêu đề */
    h1 { font-size: 40px !important; }
    h2 { font-size: 36px !important; }
    h3 { font-size: 30px !important; }
    /* Tăng kích thước chữ chung */
    p, div, label, input, .stTextInput > div > div > input, .stSelectbox > div > div > div {
        font-size: 20px !important;
    }
    /* Tăng kích thước bảng */
    .stDataFrame { font-size: 20px !important; }
    /* Tăng kích thước nút bấm */
    .stButton > button {
        font-size: 20px !important;
        padding: 10px 24px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- FILE PATHS ---
BASE_DIR = os.getcwd()
CUSTOMERS_CSV = "crm_customers.csv"
SUPPLIERS_CSV = "crm_suppliers.csv"
PURCHASES_CSV = "crm_purchases.csv"
SALES_HISTORY_CSV = "crm_sales_history_v2.csv"
TRACKING_CSV = "crm_order_tracking.csv"
PAYMENT_CSV = "crm_payment_tracking.csv"
PAID_HISTORY_CSV = "crm_paid_history.csv"
DB_SUPPLIER_ORDERS = "db_supplier_orders.csv"
DB_CUSTOMER_ORDERS = "db_customer_orders.csv"
TEMPLATE_FILE = "AAA-QUOTATION.xlsx"

# Tạo các thư mục cần thiết
FOLDERS = [
    "LICH_SU_BAO_GIA", 
    "PO_NCC", 
    "PO_KHACH_HANG", 
    "product_images", 
    "proof_images"
]

for d in FOLDERS:
    if not os.path.exists(d):
        os.makedirs(d)

# Map tên biến global cho folder
QUOTE_ROOT_FOLDER = "LICH_SU_BAO_GIA"
PO_EXPORT_FOLDER = "PO_NCC"
PO_CUSTOMER_FOLDER = "PO_KHACH_HANG"
IMG_FOLDER = "product_images"
PROOF_FOLDER = "proof_images"

ADMIN_PASSWORD = "admin"

# --- GLOBAL HELPER FUNCTIONS ---
def safe_str(val):
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat']:
        return ""
    return s

def safe_filename(s):
    return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))

def to_float(val):
    try:
        s = str(val).strip()
        if s.lower() in ['nan', 'none', '', 'null']:
            return 0.0
        clean = s.replace(",", "").replace("%", "")
        return float(clean)
    except:
        return 0.0

def fmt_num(x):
    try:
        return "{:,.0f}".format(float(x))
    except:
        return "0"

def clean_lookup_key(s):
    if s is None:
        return ""
    s_str = str(s)
    try:
        f = float(s_str)
        if f.is_integer():
            s_str = str(int(f))
    except:
        pass
    return re.sub(r'\s+', '', s_str).lower()

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime):
            dt_order = order_date_str
        else:
            dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        if nums:
            days = int(nums[0])
        else:
            days = 0
            
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except:
        return ""

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper().replace(",", "")
    try:
        return float(s)
    except:
        pass
    
    if not s.startswith("="):
        return 0.0
    
    expr = s[1:]
    expr = expr.replace("BUYING PRICE", str(buying_price))
    expr = expr.replace("BUY", str(buying_price))
    expr = expr.replace("AP PRICE", str(ap_price))
    expr = expr.replace("AP", str(ap_price))
    
    # Chỉ giữ lại các ký tự cho phép để tránh eval unsafe code
    expr = re.sub(r'[^0-9.+\-*/()]', '', expr)
    
    try:
        return float(eval(expr))
    except:
        return 0.0

def load_csv(path, cols):
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str, on_bad_lines='skip').fillna("")
            for c in cols:
                if c not in df.columns:
                    df[c] = ""
            return df[cols]
        except:
            pass
    return pd.DataFrame(columns=cols)

def save_csv(path, df):
    if df is not None:
        if isinstance(df, dict):
            st.error(f"Lỗi Code: Đang cố gắng lưu Dictionary vào file {path}.")
            return
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception as e:
            st.error(f"Không thể lưu file {path}: {e}")

def open_folder(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        st.warning(f"Không thể tự động mở folder: {e}")

# --- NEW: SAFE EXCEL WRITER (FIX MERGED CELL ERROR) ---
def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        found_merge = False
        # Kiểm tra xem ô có nằm trong vùng merged không
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                # Tìm ô trên cùng bên trái của vùng merge để ghi trị
                top_left_cell = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                top_left_cell.value = value
                found_merge = True
                break
        if not found_merge:
            cell.value = value
    except Exception as e:
        print(f"Write Error at {row},{col}: {e}")

# --- COLUMN DEFINITIONS ---
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
HISTORY_COLS = ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "total_cost", "profit", "supplier", "status", "delivery_date", "po_number"]

# =============================================================================
# 2. SESSION STATE MANAGEMENT
# =============================================================================
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    st.session_state.uploaded_po_files = [] 
    st.session_state.selected_po_files = []
    st.session_state.show_review_table = False
    
    # Quote params initialization
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
        st.session_state[f"pct_{k}"] = "0"

# Load DBs
customers_df = load_csv(CUSTOMERS_CSV, MASTER_COLUMNS)
suppliers_df = load_csv(SUPPLIERS_CSV, MASTER_COLUMNS)
purchases_df = load_csv(PURCHASES_CSV, PURCHASE_COLUMNS)
sales_history_df = load_csv(SALES_HISTORY_CSV, HISTORY_COLS)
tracking_df = load_csv(TRACKING_CSV, TRACKING_COLS)
payment_df = load_csv(PAYMENT_CSV, PAYMENT_COLS)
paid_history_df = load_csv(PAID_HISTORY_CSV, PAYMENT_COLS)
db_supplier_orders = load_csv(DB_SUPPLIER_ORDERS, SUPPLIER_ORDER_COLS)
db_customer_orders = load_csv(DB_CUSTOMER_ORDERS, CUSTOMER_ORDER_COLS)

# =============================================================================
# 3. SIDEBAR (ADMIN & MENU)
# =============================================================================
st.sidebar.title("CRM V4800")
st.sidebar.markdown(f"**Version:** `{APP_VERSION}`")
with st.sidebar.expander("📝 Release Notes"):
    st.markdown(RELEASE_NOTE)

admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)

st.sidebar.divider()
st.sidebar.info("Hệ thống quản lý: Báo giá - Đơn hàng - Tracking - Doanh số")

# =============================================================================
# 4. GIAO DIỆN CHÍNH (TABS)
# =============================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", 
    "🏭 BÁO GIÁ NCC", 
    "💰 BÁO GIÁ KHÁCH", 
    "📑 QUẢN LÝ PO", 
    "🚚 TRACKING & THANH TOÁN", 
    "📂 MASTER DATA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH")
    
    # Nút Cập Nhật & Reset Data
    col_act1, col_act2 = st.columns([1, 1])
    if col_act1.button("🔄 CẬP NHẬT DỮ LIỆU"):
        st.rerun()
        
    if col_act2.button("⚠️ RESET DATA (Admin)"):
        if admin_pwd == ADMIN_PASSWORD:
            # Xóa data các bảng giao dịch
            db_customer_orders = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
            db_supplier_orders = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
            sales_history_df = pd.DataFrame(columns=HISTORY_COLS)
            tracking_df = pd.DataFrame(columns=TRACKING_COLS)
            payment_df = pd.DataFrame(columns=PAYMENT_COLS)
            paid_history_df = pd.DataFrame(columns=PAYMENT_COLS)
            
            save_csv(DB_CUSTOMER_ORDERS, db_customer_orders)
            save_csv(DB_SUPPLIER_ORDERS, db_supplier_orders)
            save_csv(SALES_HISTORY_CSV, sales_history_df)
            save_csv(TRACKING_CSV, tracking_df)
            save_csv(PAYMENT_CSV, payment_df)
            save_csv(PAID_HISTORY_CSV, paid_history_df)
            st.success("Đã reset toàn bộ dữ liệu!")
            st.rerun()
        else:
            st.error("Sai mật khẩu Admin!")
    
    st.divider()

    # 1. KPIs
    rev = db_customer_orders['total_price'].apply(to_float).sum()
    profit = sales_history_df['profit'].apply(to_float).sum()
    cost = rev - profit
    
    # Calculate Total Purchase Value from Supplier Orders
    # Fix: Sum total_vnd column
    total_purchase_val = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    # Metrics Rows
    c1, c2, c3 = st.columns(3)
    c1.metric("DOANH THU BÁN (VND)", fmt_num(rev))
    c2.metric("TỔNG GIÁ TRỊ MUA (VND)", fmt_num(total_purchase_val))
    c3.metric("LỢI NHUẬN TỔNG (VND)", fmt_num(profit), delta_color="normal")
    
    st.divider()
    
    # Count POs
    po_received_count = len(tracking_df[
        (tracking_df['order_type'] == 'NCC') & 
        (tracking_df['status'].isin(['Hàng đã về VN', 'Hàng đã nhận ở VP']))
    ])
    po_delivered_count = len(tracking_df[
        (tracking_df['order_type'] == 'KH') & 
        (tracking_df['status'] == 'Đã giao hàng')
    ])
    
    c4, c5 = st.columns(2)
    c4.metric("SỐ PO ĐÃ NHẬN (NCC)", po_received_count)
    c5.metric("SỐ PO ĐÃ GIAO (KHÁCH)", po_delivered_count)

    st.divider()
    
    # 2. CHARTS
    c_chart1, c_chart2 = st.columns(2)
    if not db_customer_orders.empty:
        df_chart = db_customer_orders.copy()
        df_chart['total_price'] = df_chart['total_price'].apply(to_float)
        df_chart['order_date_dt'] = pd.to_datetime(df_chart['order_date'], format='%d/%m/%Y', errors='coerce')
        df_chart['Month'] = df_chart['order_date_dt'].dt.strftime('%Y-%m')
        
        with c_chart1:
            st.subheader("📈 Doanh thu theo Tháng")
            monthly_rev = df_chart.groupby('Month')['total_price'].sum()
            st.bar_chart(monthly_rev)
            
        with c_chart2:
            st.subheader("🏆 Top Khách Hàng (Contribution %)")
            cust_rev = df_chart.groupby('customer')['total_price'].sum().sort_values(ascending=False).head(10)
            if not cust_rev.empty:
                fig, ax = plt.subplots()
                ax.pie(cust_rev, labels=cust_rev.index, autopct='%1.1f%%', startangle=90)
                ax.axis('equal') 
                st.pyplot(fig)

    st.divider()
    
    # 3. TOP LISTS
    c_top1, c_top2 = st.columns(2)
    
    with c_top1:
        st.subheader("🥇 Top Khách Hàng (Doanh Số)")
        if not db_customer_orders.empty:
            top_cust = db_customer_orders.copy()
            top_cust['val'] = top_cust['total_price'].apply(to_float)
            top_cust_g = top_cust.groupby('customer')['val'].sum().sort_values(ascending=False).head(10)
            st.dataframe(top_cust_g.apply(fmt_num), use_container_width=True)
            
    with c_top2:
        st.subheader("🏭 Top Nhà Cung Cấp (Mua Nhiều)")
        if not db_supplier_orders.empty:
            top_supp = db_supplier_orders.copy()
            top_supp['val'] = top_supp['total_vnd'].apply(to_float)
            
            # Group by supplier and sum 'val' to show total money spent per supplier
            top_supp_g = top_supp.groupby('supplier')['val'].sum().sort_values(ascending=False).head(10)
            
            # Convert Series to DataFrame to show values clearly with Column Name
            df_top_supp = top_supp_g.to_frame(name="Tổng tiền mua (VND)")
            df_top_supp["Tổng tiền mua (VND)"] = df_top_supp["Tổng tiền mua (VND)"].apply(fmt_num)
            
            st.dataframe(df_top_supp, use_container_width=True)

# --- TAB 2: BÁO GIÁ NCC ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        uploaded_pur = st.file_uploader("Import Excel Purchases (Kèm ảnh)", type=["xlsx"])
        if uploaded_pur and st.button("Thực hiện Import"):
            try:
                wb = load_workbook(uploaded_pur, data_only=False)
                ws = wb.active
                img_map = {}
                for img in getattr(ws, '_images', []):
                    r_idx = img.anchor._from.row + 1 
                    if img.anchor._from.col == 12: 
                        img_name = f"img_r{r_idx}_{datetime.now().strftime('%f')}.png"
                        img_path = os.path.join(IMG_FOLDER, img_name)
                        with open(img_path, "wb") as f:
                            f.write(img._data())
                        img_map[r_idx] = img_path.replace("\\", "/")
                
                df_ex = pd.read_excel(uploaded_pur, header=0, dtype=str).fillna("")
                rows = []
                for i, r in df_ex.iterrows():
                    excel_row_idx = i + 2
                    im_path = img_map.get(excel_row_idx, "")
                    item = {
                        "no": safe_str(r.iloc[0]), "item_code": safe_str(r.iloc[1]), 
                        "item_name": safe_str(r.iloc[2]), "specs": safe_str(r.iloc[3]),
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(r.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                        "leadtime": safe_str(r.iloc[10]), "supplier_name": safe_str(r.iloc[11]), 
                        "image_path": im_path
                    }
                    if item["item_code"]: rows.append(item)
                
                purchases_df = pd.DataFrame(rows)
                save_csv(PURCHASES_CSV, purchases_df)
                st.success(f"Đã import {len(rows)} dòng và lưu ảnh!")
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi: {e}")

    with col_p2:
        search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC) - (Gõ: V12, Code, Name...)")
    
    # Hiển thị bảng kèm ảnh
    if not purchases_df.empty:
        # Filter Logic Cải Tiến: Tìm chứa chuỗi (contains) thay vì so sánh
        df_show = purchases_df.copy()
        if search_term:
            # Tạo mask tìm kiếm trên nhiều cột quan trọng
            mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or 
                                           search_term.lower() in str(x['item_name']).lower() or 
                                           search_term.lower() in str(x['specs']).lower(), axis=1)
            df_show = df_show[mask]
        
        st.dataframe(
            df_show,
            column_config={
                "image_path": st.column_config.ImageColumn("Image", help="Ảnh sản phẩm"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Chưa có dữ liệu.")

    if is_admin and st.button("Xóa Database Mua Hàng"):
        purchases_df = pd.DataFrame(columns=PURCHASE_COLUMNS)
        save_csv(PURCHASES_CSV, purchases_df)
        st.rerun()

# --- TAB 3: BÁO GIÁ KHÁCH HÀNG ---
with tab3:
    tab3_1, tab3_2 = st.tabs(["TẠO BÁO GIÁ", "TRA CỨU LỊCH SỬ"])
    
    with tab3_1:
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            cust_list = customers_df["short_name"].tolist()
            sel_cust = st.selectbox("Khách hàng", [""] + cust_list)
        with c2:
            quote_name = st.text_input("Tên Báo Giá / Mã BG")
        with c3:
             if st.button("✨ TẠO MỚI (RESET)", type="primary"):
                 st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                 # Reset params
                 for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
                     st.session_state[f"pct_{k}"] = "0"
                 st.rerun()

        st.markdown("**Tham số chi phí (%) - Nhập số (VD: 10, 5.5)**")
        # Chia cột để tất cả hiển thị trên 1 dòng
        col_params = st.columns(8)
        pct_end = col_params[0].text_input("EndUser(%)", st.session_state.pct_end)
        pct_buy = col_params[1].text_input("Buyer(%)", st.session_state.pct_buy)
        pct_tax = col_params[2].text_input("Tax(%)", st.session_state.pct_tax)
        pct_vat = col_params[3].text_input("VAT(%)", st.session_state.pct_vat)
        pct_pay = col_params[4].text_input("Payback(%)", st.session_state.pct_pay)
        pct_mgmt = col_params[5].text_input("Mgmt(%)", st.session_state.pct_mgmt)
        val_trans = col_params[6].text_input("Trans(VND)", st.session_state.pct_trans)
        
        st.session_state.pct_end = pct_end; st.session_state.pct_buy = pct_buy
        st.session_state.pct_tax = pct_tax; st.session_state.pct_vat = pct_vat
        st.session_state.pct_pay = pct_pay; st.session_state.pct_mgmt = pct_mgmt
        st.session_state.pct_trans = val_trans

        c_imp1, c_imp2 = st.columns(2)
        with c_imp1:
            uploaded_rfq = st.file_uploader("📂 Import RFQ (Excel: No, Code, Name, Specs, Qty)", type=["xlsx"])
            if uploaded_rfq and st.button("Load RFQ"):
                try:
                    # Pre-clean DB for matching
                    purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                    purchases_df["_clean_specs"] = purchases_df["specs"].apply(clean_lookup_key)
                    
                    df_rfq = pd.read_excel(uploaded_rfq, header=None, dtype=str).fillna("")
                    new_data = []
                    
                    for i, r in df_rfq.iloc[1:].iterrows():
                        c_raw = safe_str(r.iloc[1])
                        n_raw = safe_str(r.iloc[2]) # Name
                        s_raw = safe_str(r.iloc[3]) # Specs
                        qty = to_float(r.iloc[4])
                        
                        # --- FIX IMPORT LOGIC: Require Qty > 0 AND (Code OR Name OR Specs) ---
                        if qty <= 0:
                            continue
                        if not c_raw and not n_raw and not s_raw:
                            continue

                        clean_c = clean_lookup_key(c_raw)
                        clean_s = clean_lookup_key(s_raw)
                        target_row = None

                        if c_raw:
                            found_code = purchases_df[purchases_df["_clean_code"] == clean_c]
                            if not found_code.empty:
                                found_specs = found_code[found_code["_clean_specs"] == clean_s]
                                if not found_specs.empty:
                                    target_row = found_specs.iloc[0]
                        
                        it = {k:"" for k in QUOTE_KH_COLUMNS}
                        it.update({
                            "no": safe_str(r.iloc[0]), 
                            "item_code": c_raw, 
                            "item_name": n_raw, 
                            "specs": s_raw, 
                            "qty": fmt_num(qty), 
                            "ap_price": "0", 
                            "unit_price": "0",
                            "transportation": "0", 
                            "import_tax_val": "0", 
                            "vat_val": "0", 
                            "mgmt_fee": "0", 
                            "payback_val": "0"
                        })
                        
                        if target_row is not None:
                             buy_rmb = to_float(target_row["buying_price_rmb"])
                             buy_vnd = to_float(target_row["buying_price_vnd"])
                             total_rmb = buy_rmb * qty
                             total_vnd = buy_vnd * qty

                             it.update({
                                "buying_price_rmb": target_row["buying_price_rmb"],
                                "total_buying_price_rmb": fmt_num(total_rmb),
                                "exchange_rate": target_row["exchange_rate"],
                                "buying_price_vnd": target_row["buying_price_vnd"],
                                "total_buying_price_vnd": fmt_num(total_vnd),
                                "supplier_name": target_row["supplier_name"],
                                "image_path": target_row["image_path"],
                                "leadtime": target_row["leadtime"]
                            })
                        else:
                             # Default zero if not found
                             it.update({
                                "buying_price_rmb": "0", "total_buying_price_rmb": "0", 
                                "exchange_rate": "0", "buying_price_vnd": "0", 
                                "total_buying_price_vnd": "0", "supplier_name": "", 
                                "image_path": "", "leadtime": ""
                            })
                        
                        new_data.append(it)
                    
                    st.session_state.current_quote_df = pd.DataFrame(new_data)
                    st.success(f"Đã load {len(new_data)} dòng từ RFQ!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")
        
        with c_imp2:
             # Nút load lịch sử
             uploaded_hist = st.file_uploader("📂 Load Lịch sử Báo giá (CSV/Excel)", type=["xlsx", "csv"])
             if uploaded_hist and st.button("Load Lịch Sử"):
                 try:
                     if uploaded_hist.name.endswith('.csv'):
                         df_h = pd.read_csv(uploaded_hist, dtype=str).fillna("")
                     else:
                         df_h = pd.read_excel(uploaded_hist, dtype=str).fillna("")
                     
                     st.session_state.current_quote_df = df_h
                     
                     # --- AUTO LOAD METADATA PARAMETERS ---
                     original_filename = uploaded_hist.name
                     found_meta = False
                     for root, dirs, files in os.walk(QUOTE_ROOT_FOLDER):
                         if original_filename + ".json" in files:
                             meta_path = os.path.join(root, original_filename + ".json")
                             with open(meta_path, "r", encoding='utf-8') as f:
                                 meta = json.load(f)
                                 st.session_state.pct_end = str(meta.get("pct_end", "0"))
                                 st.session_state.pct_buy = str(meta.get("pct_buy", "0"))
                                 st.session_state.pct_tax = str(meta.get("pct_tax", "0"))
                                 st.session_state.pct_vat = str(meta.get("pct_vat", "0"))
                                 st.session_state.pct_pay = str(meta.get("pct_pay", "0"))
                                 st.session_state.pct_mgmt = str(meta.get("pct_mgmt", "0"))
                                 st.session_state.pct_trans = str(meta.get("pct_trans", "0"))
                                 found_meta = True
                             break
                     
                     if found_meta:
                         st.success("Đã load dữ liệu và KHÔI PHỤC THAM SỐ chi phí!")
                     else:
                         st.warning("Đã load dữ liệu, nhưng không tìm thấy file cấu hình tham số cũ.")
                     
                     st.rerun()
                 except Exception as e: st.error(f"Lỗi load lịch sử: {e}")

        # --- DATA EDITOR (EDITABLE TABLE) ---
        st.markdown("### Chi tiết báo giá")
        
        # Công cụ Formula
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        ap_formula = f1.text_input("AP Formula (vd: BUY*1.1)", key="ap_f")
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r["buying_price_vnd"])
                a = to_float(r["ap_price"])
                st.session_state.current_quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_formula, b, a))
            st.rerun()

        unit_formula = f3.text_input("Unit Formula (vd: AP/0.8)", key="unit_f")
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r["buying_price_vnd"])
                a = to_float(r["ap_price"])
                st.session_state.current_quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_formula, b, a))
            st.rerun()

        # Hiển thị bảng cho phép sửa
        # QUAN TRỌNG: Lấy dữ liệu đã chỉnh sửa từ data_editor
        # Format số liệu hiển thị (RMB, VND)
        
        edited_df = st.data_editor(
            st.session_state.current_quote_df,
            key="quote_editor",
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "image_path": st.column_config.ImageColumn("Img"),
                "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                "buying_price_rmb": st.column_config.NumberColumn("Buy(RMB)", format="%.2f", disabled=False),
                "buying_price_vnd": st.column_config.NumberColumn("Buy(VND)", format="%.0f", disabled=True),
                "total_buying_price_rmb": st.column_config.NumberColumn("Total Buy(RMB)", format="%.2f", disabled=True),
                "total_buying_price_vnd": st.column_config.NumberColumn("Total Buy(VND)", format="%.0f", disabled=True),
                "ap_price": st.column_config.TextColumn("AP Price"),
                "unit_price": st.column_config.TextColumn("Unit Price"),
                "transportation": st.column_config.TextColumn("Trans"),
                "profit_vnd": st.column_config.TextColumn("Profit", disabled=True),
                "profit_pct": st.column_config.TextColumn("%", disabled=True),
            }
        )
        
        # --- AUTO-CALC ---
        need_recalc = False
        
        # Tính toán lại toàn bộ dựa trên edited_df
        pend = to_float(pct_end)/100; pbuy = to_float(pct_buy)/100
        ptax = to_float(pct_tax)/100; pvat = to_float(pct_vat)/100
        ppay = to_float(pct_pay)/100; pmgmt = to_float(pct_mgmt)/100
        global_trans = to_float(val_trans)
        use_global = global_trans > 0
        
        df_temp = edited_df.copy()
        
        for i, r in df_temp.iterrows():
            qty = to_float(r["qty"]); buy_vnd = to_float(r["buying_price_vnd"])
            buy_rmb = to_float(r["buying_price_rmb"])
            ap = to_float(r["ap_price"]); unit = to_float(r["unit_price"])
            
            # Trans
            cur_trans = to_float(r["transportation"])
            use_trans = global_trans if use_global else cur_trans
            
            t_buy = qty * buy_vnd
            ap_tot = ap * qty; total = unit * qty; gap = total - ap_tot
            
            end_val = ap_tot * pend; buyer_val = total * pbuy
            tax_val = t_buy * ptax; vat_val = total * pvat
            mgmt_val = total * pmgmt; pay_val = gap * ppay
            tot_trans = use_trans * qty
            
            cost = t_buy + gap + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
            prof = total - cost + pay_val
            pct = (prof/total*100) if total else 0
            
            # Update values
            df_temp.at[i, "transportation"] = fmt_num(use_trans)
            df_temp.at[i, "total_buying_price_rmb"] = fmt_num(buy_rmb * qty)
            df_temp.at[i, "total_buying_price_vnd"] = fmt_num(t_buy)
            df_temp.at[i, "ap_total_vnd"] = fmt_num(ap_tot)
            df_temp.at[i, "total_price_vnd"] = fmt_num(total)
            df_temp.at[i, "gap"] = fmt_num(gap)
            df_temp.at[i, "end_user_val"] = fmt_num(end_val)
            df_temp.at[i, "buyer_val"] = fmt_num(buyer_val)
            df_temp.at[i, "import_tax_val"] = fmt_num(tax_val)
            df_temp.at[i, "vat_val"] = fmt_num(vat_val)
            df_temp.at[i, "mgmt_fee"] = fmt_num(mgmt_val)
            df_temp.at[i, "payback_val"] = fmt_num(pay_val)
            df_temp.at[i, "profit_vnd"] = fmt_num(prof)
            df_temp.at[i, "profit_pct"] = "{:.2f}%".format(pct)

        # Check if values changed significantly compared to session state to trigger update
        if not df_temp.equals(st.session_state.current_quote_df):
             st.session_state.current_quote_df = df_temp
             st.rerun()

        # REVIEW & SAVE
        st.divider()
        c_rev, c_sav, c_exp = st.columns([1, 1, 1])
        
        with c_rev:
            # --- REVIEW FEATURE ---
            if st.button("🔍 REVIEW & KIỂM TRA LỢI NHUẬN", type="primary"):
                st.session_state.show_review_table = not st.session_state.get('show_review_table', False)
        
        # --- FIX: Bảng Review Full width ---
        if st.session_state.get('show_review_table', False):
            st.write("### Bảng kiểm tra lợi nhuận")
            
            def highlight_low_profit(val):
                try:
                    p = float(val.replace("%",""))
                    return 'background-color: #ffcccc; color: red; font-weight: bold' if p < 10 else ''
                except: return ''

            # Chỉ hiện các cột quan trọng
            cols_review = ["item_code", "item_name", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]
            df_review = st.session_state.current_quote_df[cols_review].copy()
            
            # FIX: Tăng kích thước bảng Review
            st.dataframe(
                df_review.style.applymap(highlight_low_profit, subset=['profit_pct']),
                use_container_width=True,
                height=600  # Tăng chiều cao lên 600px
            )
            
            # Cảnh báo text
            low_profits = []
            for idx, r in df_review.iterrows():
                try:
                    if float(r["profit_pct"].replace("%","")) < 10:
                        low_profits.append(f"{r['item_code']}")
                except: pass
            
            if low_profits:
                st.error(f"⚠️ CẢNH BÁO: Các mã sau có lợi nhuận < 10%: {', '.join(low_profits)}")
            else:
                st.success("✅ Tất cả các mã đều có lợi nhuận > 10%")

        with c_sav:
            if st.button("💾 LƯU LỊCH SỬ & FILE"):
                if not sel_cust or not quote_name:
                    st.error("Thiếu tên Khách hoặc Mã BG")
                else:
                    # Save path: LICH_SU_BAO_GIA / YEAR / MONTH / ...
                    now = datetime.now()
                    year_str = now.strftime("%Y")
                    month_str = now.strftime("%b").upper()
                    base_path = os.path.join(QUOTE_ROOT_FOLDER, safe_filename(sel_cust), year_str, month_str)
                    if not os.path.exists(base_path): os.makedirs(base_path)
                    
                    # Save CSV
                    csv_name = f"History_{safe_filename(quote_name)}.csv"
                    full_path = os.path.join(base_path, csv_name)
                    st.session_state.current_quote_df.to_csv(full_path, index=False, encoding='utf-8-sig')
                    
                    # --- SAVE METADATA (JSON) ---
                    meta_data = {
                        "pct_end": st.session_state.pct_end,
                        "pct_buy": st.session_state.pct_buy,
                        "pct_tax": st.session_state.pct_tax,
                        "pct_vat": st.session_state.pct_vat,
                        "pct_pay": st.session_state.pct_pay,
                        "pct_mgmt": st.session_state.pct_mgmt,
                        "pct_trans": st.session_state.pct_trans,
                        "quote_name": quote_name,
                        "customer": sel_cust,
                        "date": now.strftime("%d/%m/%Y")
                    }
                    json_path = os.path.join(base_path, csv_name + ".json")
                    with open(json_path, "w", encoding='utf-8') as f:
                        json.dump(meta_data, f, ensure_ascii=False, indent=4)

                    # Save DB Sales History
                    d = now.strftime("%d/%m/%Y")
                    new_hist_rows = []
                    for _, r in st.session_state.current_quote_df.iterrows():
                        rev = to_float(r["total_price_vnd"]); prof = to_float(r["profit_vnd"])
                        cost = rev - prof
                        new_hist_rows.append({
                            "date":d, "quote_no":quote_name, "customer":sel_cust, 
                            "item_code":r["item_code"], "item_name":r["item_name"], "specs":r["specs"], 
                            "qty":r["qty"], "total_revenue":fmt_num(rev), "total_cost":fmt_num(cost), 
                            "profit":fmt_num(prof), "supplier":r["supplier_name"], "status":"Pending", 
                            "delivery_date":"", "po_number": ""
                        })
                    sales_history_df = pd.concat([sales_history_df, pd.DataFrame(new_hist_rows)], ignore_index=True)
                    save_csv(SALES_HISTORY_CSV, sales_history_df)
                    st.success(f"Đã lưu lịch sử và tham số vào {base_path}")

        with c_exp:
            # Logic Xuất Excel Format AAA
            if st.button("XUẤT EXCEL"):
                if not os.path.exists(TEMPLATE_FILE):
                    st.error("Không tìm thấy file mẫu AAA-QUOTATION.xlsx")
                else:
                    try:
                        now = datetime.now()
                        year_str = now.strftime("%Y")
                        month_str = now.strftime("%b").upper()
                        target_dir = os.path.join(QUOTE_ROOT_FOLDER, safe_filename(sel_cust), year_str, month_str)
                        if not os.path.exists(target_dir): os.makedirs(target_dir)
                        
                        fname = f"Quote_{safe_filename(quote_name)}_{now.strftime('%Y%m%d')}.xlsx"
                        save_path = os.path.join(target_dir, fname)
                        
                        wb = load_workbook(TEMPLATE_FILE)
                        ws = wb.active
                        
                        # --- SAFE WRITE HEADER ---
                        safe_write_merged(ws, 1, 2, sel_cust) # B1
                        safe_write_merged(ws, 1, 8, now.strftime("%d-%b-%Y")) # H1
                        safe_write_merged(ws, 2, 8, quote_name) # H2
                        
                        if not st.session_state.current_quote_df.empty:
                            lt = safe_str(st.session_state.current_quote_df.iloc[0]["leadtime"])
                            safe_write_merged(ws, 8, 8, lt) # H8
                        
                        # FIX: Start data from Row 11 as requested
                        start_row = 11
                        
                        for idx, r in st.session_state.current_quote_df.iterrows():
                            ri = start_row + idx
                            # Mapping: No(A), Code(C), Name(D), Specs(E), Qty(F), Unit(G), Total(H)
                            
                            safe_write_merged(ws, ri, 1, r["no"])
                            safe_write_merged(ws, ri, 3, r["item_code"])
                            safe_write_merged(ws, ri, 4, r["item_name"])
                            safe_write_merged(ws, ri, 5, r["specs"])
                            safe_write_merged(ws, ri, 6, to_float(r["qty"]))
                            safe_write_merged(ws, ri, 7, to_float(r["unit_price"]))
                            safe_write_merged(ws, ri, 8, to_float(r["total_price_vnd"]))
                            
                            # Style
                            thin = Side(border_style="thin", color="000000")
                            align_center = Alignment(vertical='center', wrap_text=True)
                            
                            for c_idx in [1,3,4,5,6,7,8]:
                                cell = ws.cell(row=ri, column=c_idx)
                                final_cell = cell
                                for mr in ws.merged_cells.ranges:
                                    if cell.coordinate in mr:
                                        final_cell = ws.cell(row=mr.min_row, column=mr.min_col)
                                        break
                                
                                final_cell.alignment = align_center
                                final_cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)

                        wb.save(save_path)
                        st.success(f"Đã xuất file tại: {save_path}")
                        with open(save_path, "rb") as f:
                            st.download_button("Tải File Excel về", f, file_name=fname)
                    except Exception as e: st.error(f"Lỗi xuất Excel: {e}")

    # --- SUBTAB 3.2: TRA CỨU LỊCH SỬ ---
    with tab3_2:
        st.subheader("Tra cứu lịch sử giá")
        
        search_history_term = st.text_input("🔍 Tra cứu nhanh (Item Code, Name, Specs)")
        
        up_bulk = st.file_uploader("Tra cứu hàng loạt (Excel: No, Code, Name, Specs)", type=["xlsx"])
        if up_bulk and st.button("🔍 Check Bulk"):
            df_check = pd.read_excel(up_bulk, header=None, dtype=str).fillna("")
            results = []
            
            # Prep data
            db_customer_orders["_clean_code"] = db_customer_orders["item_code"].apply(clean_lookup_key)
            db_customer_orders["_clean_specs"] = db_customer_orders["specs"].apply(clean_lookup_key)
            sales_history_df["_clean_code"] = sales_history_df["item_code"].apply(clean_lookup_key)
            sales_history_df["_clean_specs"] = sales_history_df["specs"].apply(clean_lookup_key)

            for i, r in df_check.iloc[1:].iterrows():
                c_raw = safe_str(r.iloc[1]); specs_raw = safe_str(r.iloc[3])
                if not c_raw: continue
                clean_c = clean_lookup_key(c_raw); clean_s = clean_lookup_key(specs_raw)
                
                found = False
                
                # Check PO
                match_po = db_customer_orders[db_customer_orders["_clean_code"]==clean_c]
                for _, po in match_po.iterrows():
                    db_s = po["_clean_specs"]
                    if (clean_s == db_s) or (clean_s in db_s) or (db_s in clean_s):
                        results.append({"Status":"Đã có PO", "Date":po["order_date"], "Item":po["item_code"], "Price":po["unit_price"], "Ref PO":po["po_number"]})
                        found = True
                
                # Check Quote
                if not found:
                    match_qt = sales_history_df[sales_history_df["_clean_code"]==clean_c]
                    for _, qt in match_qt.iterrows():
                         db_s = qt["_clean_specs"]
                         if (clean_s == db_s) or (clean_s in db_s) or (db_s in clean_s):
                             rev = to_float(qt["total_revenue"]); q = to_float(qt["qty"])
                             u = rev/q if q>0 else 0
                             results.append({"Status":"Đã báo giá", "Date":qt["date"], "Item":qt["item_code"], "Price":fmt_num(u), "Ref PO":qt["quote_no"]})
                             found = True
                
                if not found:
                    results.append({"Status":"Chưa có", "Date":"", "Item":c_raw, "Price":"", "Ref PO":""})
            
            st.dataframe(pd.DataFrame(results))
        
        elif search_history_term:
            mask = sales_history_df.apply(lambda x: search_history_term.lower() in str(x['item_code']).lower() or 
                                           search_history_term.lower() in str(x['item_name']).lower() or 
                                           search_history_term.lower() in str(x['specs']).lower(), axis=1)
            filtered_df = sales_history_df[mask].copy()
            
            # Auto Update Status
            for idx, row in filtered_df.iterrows():
                code = row['item_code']
                po_match = db_customer_orders[db_customer_orders['item_code'] == code]
                if not po_match.empty:
                    last_po = po_match.iloc[-1]
                    filtered_df.at[idx, 'po_number'] = last_po['po_number']
                    
                    track_match = tracking_df[(tracking_df['po_no'] == last_po['po_number']) & (tracking_df['order_type'] == 'KH')]
                    if not track_match.empty:
                        last_track = track_match.iloc[-1]
                        filtered_df.at[idx, 'status'] = last_track['status']
                        if last_track['finished'] == '1':
                             filtered_df.at[idx, 'delivery_date'] = last_track['last_update']
                    else:
                        filtered_df.at[idx, 'status'] = "Đã có PO"
                else:
                    filtered_df.at[idx, 'status'] = "Chờ PO"

            st.write(f"Tìm thấy {len(filtered_df)} kết quả:")
            st.dataframe(filtered_df, use_container_width=True)

# --- TAB 4: QUẢN LÝ PO ---
with tab4:
    col_po1, col_po2 = st.columns(2)
    
    # === PO NCC ===
    with col_po1:
        st.subheader("1. Đặt hàng NCC (PO NCC)")
        po_ncc_no = st.text_input("Số PO NCC")
        supp_list = suppliers_df["short_name"].tolist()
        po_ncc_supp = st.selectbox("NCC", [""] + supp_list)
        po_ncc_date = st.text_input("Ngày đặt", value=datetime.now().strftime("%d/%m/%Y"))
        
        up_ncc = st.file_uploader("Excel Items NCC", type=["xlsx"], key="up_ncc")
        if up_ncc:
             df_ncc = pd.read_excel(up_ncc, dtype=str).fillna("")
             temp_ncc = []
             purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
             purchases_df["_clean_specs"] = purchases_df["specs"].apply(clean_lookup_key)
             
             for i, r in df_ncc.iterrows():
                 code = safe_str(r.iloc[1] if len(r)>1 else "")
                 specs = safe_str(r.iloc[3] if len(r)>3 else "")
                 qty = to_float(r.iloc[4] if len(r)>4 else 1)
                 
                 clean_c = clean_lookup_key(code); clean_s = clean_lookup_key(specs)
                 found = purchases_df[(purchases_df["_clean_code"]==clean_c) & (purchases_df["_clean_specs"]==clean_s)]
                 
                 it = {"item_code":code, "qty":fmt_num(qty), "specs": specs, "item_name": safe_str(r.iloc[2])}
                 if not found.empty:
                     fr = found.iloc[0]
                     it.update({
                         "item_name": fr["item_name"], "price_rmb":fr["buying_price_rmb"],
                         "total_rmb": fmt_num(to_float(fr["buying_price_rmb"])*qty),
                         "price_vnd": fr["buying_price_vnd"],
                         "total_vnd": fmt_num(to_float(fr["buying_price_vnd"])*qty),
                         "exchange_rate": fr["exchange_rate"],
                         "eta": calc_eta(po_ncc_date, fr["leadtime"]),
                         "supplier": fr["supplier_name"]
                     })
                 else:
                     it.update({"price_rmb":"0", "total_rmb":"0", "price_vnd":"0", "total_vnd":"0", "exchange_rate":"0", "supplier":po_ncc_supp})
                 temp_ncc.append(it)
             
             st.session_state.temp_supp_order_df = pd.DataFrame(temp_ncc)
        
        # New Review Section
        st.write("#### Review Đơn Hàng NCC")
        st.dataframe(st.session_state.temp_supp_order_df)
        
        if st.button("🚀 XÁC NHẬN ĐÃ ĐẶT NCC & XUẤT PO"):
            if not po_ncc_no: st.error("Thiếu số PO")
            else:
                final_df = st.session_state.temp_supp_order_df.copy()
                final_df["po_number"] = po_ncc_no
                final_df["order_date"] = po_ncc_date
                
                db_supplier_orders = pd.concat([db_supplier_orders, final_df], ignore_index=True)
                save_csv(DB_SUPPLIER_ORDERS, db_supplier_orders)
                
                # --- AUTO EXPORT EXCEL & OPEN FOLDER (PO_NCC/YEAR/MONTH/Supplier) ---
                now = datetime.now()
                year_str = now.strftime("%Y")
                month_str = now.strftime("%b").upper()
                base_po_path = os.path.join(PO_EXPORT_FOLDER, year_str, month_str)
                if not os.path.exists(base_po_path): os.makedirs(base_po_path)
                
                # Tracking
                for supp, g in final_df.groupby("supplier"):
                    # 1. Create Tracking
                    new_track = {
                        "no": len(tracking_df)+1, "po_no": po_ncc_no, "partner": supp, 
                        "status": "Đã đặt hàng", "eta": g.iloc[0]["eta"], "proof_image": "", 
                        "order_type": "NCC", "last_update": po_ncc_date, "finished": "0"
                    }
                    tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
                    
                    # 2. Create Excel File
                    supp_path = os.path.join(base_po_path, safe_filename(supp))
                    if not os.path.exists(supp_path): os.makedirs(supp_path)
                    
                    wb = Workbook(); ws = wb.active; ws.title = "PO"
                    headers = ["No", "Item code", "Item name", "Specs", "Q'ty", "Buying price(RMB)", "Total(RMB)", "ETA"]
                    ws.append(headers)
                    for idx, r in g.iterrows():
                        r_no = r.get("no", idx + 1)
                        ws.append([r_no, r["item_code"], r["item_name"], r["specs"], to_float(r["qty"]), to_float(r["price_rmb"]), to_float(r["total_rmb"]), r["eta"]])
                    
                    po_filename = f"PO_{safe_filename(po_ncc_no)}_{safe_filename(supp)}.xlsx"
                    wb.save(os.path.join(supp_path, po_filename))
                    
                    # Open only the first supplier folder for demo purpose or open base path
                    open_folder(supp_path)

                save_csv(TRACKING_CSV, tracking_df)
                st.success(f"Đã tạo PO NCC, lưu Tracking và xuất file vào {base_po_path}")

    # === PO KHÁCH ===
    with col_po2:
        st.subheader("2. PO Khách Hàng")
        po_cust_no = st.text_input("Số PO Khách")
        cust_po_list = customers_df["short_name"].tolist()
        po_cust_name = st.selectbox("Khách Hàng", [""] + cust_po_list)
        po_cust_date = st.text_input("Ngày nhận", value=datetime.now().strftime("%d/%m/%Y"))
        
        # Multiple File Upload
        uploaded_files = st.file_uploader("Upload File PO (Chọn nhiều file)", type=["xlsx", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        # Display selected files with Remove option
        if "selected_po_files" not in st.session_state: st.session_state.selected_po_files = []
        if uploaded_files:
             # Merge new uploads into session state list (avoid duplicates if possible or just append)
             for f in uploaded_files:
                 if f.name not in [x.name for x in st.session_state.selected_po_files]:
                     st.session_state.selected_po_files.append(f)
        
        # UI to remove files
        if st.session_state.selected_po_files:
            st.write("Danh sách file đã chọn:")
            files_to_keep = []
            for f in st.session_state.selected_po_files:
                c_f1, c_f2 = st.columns([8, 2])
                c_f1.text(f"📄 {f.name}")
                if not c_f2.button("✖️ Xóa", key=f"del_{f.name}"):
                    files_to_keep.append(f)
            st.session_state.selected_po_files = files_to_keep
        
        # Processing Logic (Auto-parse Excel files)
        if st.session_state.selected_po_files:
            for f in st.session_state.selected_po_files:
                if f.name.endswith('.xlsx'):
                    try:
                         df_c = pd.read_excel(f, dtype=str).fillna("")
                         temp_c = []
                         purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                         for i, r in df_c.iterrows():
                             code = safe_str(r.iloc[1]); qty = to_float(r.iloc[4]); specs = safe_str(r.iloc[3])
                             price = 0
                             hist_match = sales_history_df[(sales_history_df["customer"] == po_cust_name) & (sales_history_df["item_code"] == code)]
                             if not hist_match.empty:
                                 price = to_float(hist_match.iloc[-1]["total_revenue"]) / to_float(hist_match.iloc[-1]["qty"])
                             
                             eta = ""
                             clean_code = clean_lookup_key(code)
                             found_pur = purchases_df[purchases_df["_clean_code"] == clean_code]
                             if not found_pur.empty:
                                 lt = found_pur.iloc[0]["leadtime"]
                                 eta = calc_eta(po_cust_date, lt)

                             temp_c.append({
                                 "item_code":code, "item_name":safe_str(r.iloc[2]), "specs":specs,
                                 "qty":fmt_num(qty), "unit_price":fmt_num(price), 
                                 "total_price":fmt_num(price*qty), "eta": eta
                             })
                         # Update/Merge to temp df (simple overwrite for now, or append)
                         st.session_state.temp_cust_order_df = pd.DataFrame(temp_c)
                    except: pass
        
        if not st.session_state.temp_cust_order_df.empty:
             st.dataframe(st.session_state.temp_cust_order_df)

        if st.button("💾 LƯU PO KHÁCH"):
            if not po_cust_no or not po_cust_name: st.error("Thiếu thông tin")
            else:
                final_eta = ""
                if not st.session_state.temp_cust_order_df.empty:
                    final_c = st.session_state.temp_cust_order_df.copy()
                    final_c["po_number"] = po_cust_no
                    final_c["customer"] = po_cust_name
                    final_c["order_date"] = po_cust_date
                    
                    db_customer_orders = pd.concat([db_customer_orders, final_c], ignore_index=True)
                    save_csv(DB_CUSTOMER_ORDERS, db_customer_orders)
                    
                    eta_list = [datetime.strptime(x, "%d/%m/%Y") for x in final_c["eta"] if x]
                    final_eta = max(eta_list).strftime("%d/%m/%Y") if eta_list else ""
                else:
                    final_eta = "" # Trường hợp upload PDF/Ảnh ko parse được data

                # Tracking
                new_track = {
                    "no": len(tracking_df)+1, "po_no": po_cust_no, "partner": po_cust_name, 
                    "status": "Đang đợi hàng về", "eta": final_eta, "proof_image": "", 
                    "order_type": "KH", "last_update": po_cust_date, "finished": "0"
                }
                tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
                save_csv(TRACKING_CSV, tracking_df)
                
                # --- SAVE FILE & OPEN FOLDER (PO_KHACH_HANG/YEAR/MONTH/Customer/File) ---
                now = datetime.now()
                year_str = now.strftime("%Y")
                month_str = now.strftime("%b").upper()
                path = os.path.join(PO_CUSTOMER_FOLDER, year_str, month_str, safe_filename(po_cust_name))
                if not os.path.exists(path): os.makedirs(path)
                
                # Save all uploaded files from session state list
                # FIX: Use loop over selected_po_files
                for f in st.session_state.selected_po_files:
                    with open(os.path.join(path, f.name), "wb") as w:
                        w.write(f.getbuffer())
                
                # Save Excel detail if dataframe exists
                if not st.session_state.temp_cust_order_df.empty:
                    st.session_state.temp_cust_order_df.to_excel(os.path.join(path, f"PO_{po_cust_no}_Detail.xlsx"), index=False)
                
                # Reset state
                st.session_state.selected_po_files = []
                st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
                
                st.success(f"Đã lưu PO và Tracking. Folder: {path}")
                open_folder(path)

# --- TAB 5: TRACKING & PAYMENT ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI & CÔNG NỢ", "LỊCH SỬ THANH TOÁN"])
    
    with t5_1:
        st.subheader("Theo dõi trạng thái & Thanh toán")
        st.markdown("#### 1. Tracking Đơn Hàng")
        edited_tracking = st.data_editor(
            tracking_df[tracking_df["finished"]=="0"],
            column_config={
                "status": st.column_config.SelectboxColumn("Status", options=[
                    "Đã đặt hàng", "Đợi hàng từ TQ về VN", "Hàng đã về VN", "Hàng đã nhận ở VP", # NCC
                    "Đang đợi hàng về", "Đã giao hàng" # KH
                ], required=True)
            }, use_container_width=True, key="editor_tracking"
        )
        
        if st.button("Cập nhật Tracking"):
            for i, r in edited_tracking.iterrows():
                tracking_df.loc[tracking_df["no"]==r["no"], "status"] = r["status"]
                tracking_df.loc[tracking_df["no"]==r["no"], "last_update"] = datetime.now().strftime("%d/%m/%Y")
                if r["status"] in ["Hàng đã nhận ở VP", "Đã giao hàng"]:
                    tracking_df.loc[tracking_df["no"]==r["no"], "finished"] = "1"
                    if r["order_type"] == "KH":
                        cust = r["partner"]; term = 30
                        f_cust = customers_df[customers_df["short_name"]==cust]
                        if not f_cust.empty: 
                            try: term = int(f_cust.iloc[0]["payment_term"])
                            except: pass
                        due = (datetime.now() + timedelta(days=term)).strftime("%d/%m/%Y")
                        new_pay = {
                            "no": len(payment_df)+1, "po_no": r["po_no"], "customer": cust,
                            "invoice_no": "", "status": "Chưa thanh toán", "due_date": due, "paid_date": ""
                        }
                        payment_df = pd.concat([payment_df, pd.DataFrame([new_pay])], ignore_index=True)
                        save_csv(PAYMENT_CSV, payment_df)
            save_csv(TRACKING_CSV, tracking_df)
            st.success("Đã cập nhật tracking!")
            st.rerun()

        st.divider()
        st.markdown("#### 2. Theo dõi công nợ (Payment)")
        
        pending_pay = payment_df[payment_df["status"] != "Đã thanh toán"]
        if not pending_pay.empty:
            # Editable Invoice No
            edited_pay = st.data_editor(
                pending_pay,
                column_config={
                    "invoice_no": st.column_config.TextColumn("Invoice No", width="medium"),
                    "no": st.column_config.Column(disabled=True),
                    "po_no": st.column_config.Column(disabled=True),
                    "customer": st.column_config.Column(disabled=True),
                    "status": st.column_config.Column(disabled=True),
                    "due_date": st.column_config.Column(disabled=True),
                },
                key="editor_pay",
                use_container_width=True
            )
            
            if st.button("Cập nhật Invoice"):
                for i, r in edited_pay.iterrows():
                    payment_df.loc[payment_df["no"]==r["no"], "invoice_no"] = r["invoice_no"]
                save_csv(PAYMENT_CSV, payment_df)
                st.success("Đã cập nhật số Invoice")
            
            c_pay1, c_pay2 = st.columns(2)
            po_pay = c_pay1.selectbox("Chọn PO để xác nhận thanh toán", pending_pay["po_no"].unique())
            if c_pay2.button("Xác nhận ĐÃ THANH TOÁN"):
                idx = payment_df[payment_df["po_no"]==po_pay].index
                payment_df.loc[idx, "status"] = "Đã thanh toán"
                payment_df.loc[idx, "paid_date"] = datetime.now().strftime("%d/%m/%Y")
                
                paid_history_df = pd.concat([paid_history_df, payment_df.loc[idx]], ignore_index=True)
                save_csv(PAID_HISTORY_CSV, paid_history_df)
                save_csv(PAYMENT_CSV, payment_df)
                st.success(f"PO {po_pay} đã thanh toán! Đã chuyển sang Lịch Sử.")
                st.rerun()
        else: st.success("Không có công nợ quá hạn.")

    with t5_2:
        st.subheader("Lịch sử thanh toán")
        if not paid_history_df.empty:
            paid_cust = st.selectbox("Lọc theo Khách Hàng", ["Tất cả"] + list(paid_history_df["customer"].unique()))
            df_show_paid = paid_history_df if paid_cust == "Tất cả" else paid_history_df[paid_history_df["customer"] == paid_cust]
            st.dataframe(df_show_paid, use_container_width=True)
            
            # Show Detail
            st.write("---")
            st.write("#### Chi tiết đơn hàng đã thanh toán")
            selected_po = st.selectbox("Chọn PO để xem chi tiết item", df_show_paid["po_no"].unique())
            if selected_po:
                detail_items = db_customer_orders[db_customer_orders["po_number"] == selected_po]
                if not detail_items.empty:
                    st.dataframe(detail_items[["item_code", "item_name", "specs", "qty", "unit_price", "total_price"]], use_container_width=True)
                else: st.warning("Không tìm thấy dữ liệu chi tiết item cho PO này.")
        else: st.info("Chưa có dữ liệu thanh toán.")

# --- TAB 6: MASTER DATA ---
with tab6:
    t6_1, t6_2, t6_3 = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    
    with t6_1:
        st.markdown("#### Danh sách Khách Hàng")
        up_cust_master = st.file_uploader("Upload File Excel Khách Hàng (Ghi đè)", type=["xlsx"], key="cust_imp")
        if up_cust_master and st.button("Thực hiện Import (KH)"):
            try:
                df_new = pd.read_excel(up_cust_master, dtype=str).fillna("")
                cols_to_use = MASTER_COLUMNS
                for c in cols_to_use:
                    if c not in df_new.columns: df_new[c] = ""
                customers_df = df_new[cols_to_use]
                save_csv(CUSTOMERS_CSV, customers_df)
                st.success("Đã import danh sách Khách hàng mới!")
                st.rerun()
            except Exception as e: st.error(f"Lỗi import: {e}")

        if is_admin and st.button("⚠️ XÓA TOÀN BỘ DATA KHÁCH HÀNG"):
            customers_df = pd.DataFrame(columns=MASTER_COLUMNS)
            save_csv(CUSTOMERS_CSV, customers_df)
            st.rerun()

        edited_cust_df = st.data_editor(customers_df, key="ed_cust", num_rows="dynamic")
        if st.button("Lưu thay đổi Khách Hàng"):
            if is_admin:
                save_csv(CUSTOMERS_CSV, edited_cust_df)
                st.success("Đã lưu")
            else: st.error("Cần quyền Admin để lưu chỉnh sửa tay.")
            
    with t6_2:
        st.markdown("#### Danh sách Nhà Cung Cấp")
        up_supp_master = st.file_uploader("Upload File Excel NCC (Ghi đè)", type=["xlsx"], key="supp_imp")
        if up_supp_master and st.button("Thực hiện Import (NCC)"):
            try:
                df_new = pd.read_excel(up_supp_master, dtype=str).fillna("")
                cols_to_use = MASTER_COLUMNS
                for c in cols_to_use:
                    if c not in df_new.columns: df_new[c] = ""
                suppliers_df = df_new[cols_to_use]
                save_csv(SUPPLIERS_CSV, suppliers_df)
                st.success("Đã import danh sách NCC mới!")
                st.rerun()
            except Exception as e: st.error(f"Lỗi import: {e}")

        if is_admin and st.button("⚠️ XÓA TOÀN BỘ DATA NCC"):
            suppliers_df = pd.DataFrame(columns=MASTER_COLUMNS)
            save_csv(SUPPLIERS_CSV, suppliers_df)
            st.rerun()

        edited_supp_df = st.data_editor(suppliers_df, key="ed_supp", num_rows="dynamic")
        if st.button("Lưu thay đổi NCC"):
            if is_admin:
                save_csv(SUPPLIERS_CSV, edited_supp_df)
                st.success("Đã lưu")
            else: st.error("Cần quyền Admin để lưu chỉnh sửa tay.")

    with t6_3:
        st.markdown(f"#### Quản lý Template Báo Giá ({TEMPLATE_FILE})")
        if st.button("🗑️ Xóa Template Cũ"):
            if is_admin:
                if os.path.exists(TEMPLATE_FILE):
                    os.remove(TEMPLATE_FILE)
                    st.success("Đã xóa file template cũ.")
                else: st.warning("Không tìm thấy file template.")
            else: st.error("Yêu cầu quyền Admin để xóa Template!")
        
        up_tpl = st.file_uploader("Upload Template Mới (Ghi đè)", type=["xlsx"], key="tpl_imp")
        if up_tpl and st.button("Lưu Template"):
            with open(TEMPLATE_FILE, "wb") as f:
                f.write(up_tpl.getbuffer())
            st.success("Đã cập nhật template mới!")

# =============================================================================
# RUN INFO
# =============================================================================
# Run: streamlit run main.py
