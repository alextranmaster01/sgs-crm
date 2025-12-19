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

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO & VERSION
# =============================================================================
APP_VERSION = "V4800 - UPDATE V3.9 (FIX SAVE PATH & 300% UI)"
RELEASE_NOTE = """
- **UI Upgrade (300%):** Phóng to toàn bộ giao diện Dashboard, Tab, Font chữ và các ô 3D Card lên gấp 3 lần kích thước cũ theo yêu cầu.
- **Critical Fix:** Sửa lỗi đường dẫn lưu file lịch sử báo giá để đảm bảo file luôn được tạo thành công trong thư mục chỉ định.
- **System:** Giữ nguyên toàn bộ logic tính toán và quy trình Import.
"""

st.set_page_config(page_title=f"CRM V4800 - {APP_VERSION}", layout="wide", page_icon="💼")

# --- CSS TÙY CHỈNH (GIAO DIỆN KHỔNG LỒ 300% & 3D CARDS) ---
st.markdown("""
    <style>
    /* Tăng kích thước Tab lên 300% */
    button[data-baseweb="tab"] {
        font-size: 40px !important; /* Gốc 20px -> 60px nhưng chỉnh 40px cho cân đối */
        padding: 30px !important;
        font-weight: 900 !important;
    }
    /* Tăng kích thước tiêu đề */
    h1 { font-size: 96px !important; } /* Gốc 32px */
    h2 { font-size: 84px !important; } /* Gốc 28px */
    h3 { font-size: 72px !important; } /* Gốc 24px */
    
    /* Tăng kích thước chữ chung */
    p, div, label, input, .stTextInput > div > div > input, .stSelectbox > div > div > div {
        font-size: 32px !important; /* Gốc 16px -> Tăng lên cho dễ nhìn */
    }
    
    /* 3D DASHBOARD CARDS CSS - PHIÊN BẢN KHỔNG LỒ */
    .card-3d {
        border-radius: 40px;
        padding: 50px 30px;
        color: white;
        text-align: center;
        box-shadow: 0 20px 50px rgba(0,0,0,0.3), 0 10px 20px rgba(0,0,0,0.2);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        margin-bottom: 50px;
        height: 400px; /* Tăng chiều cao */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        border: 2px solid rgba(255, 255, 255, 0.2);
    }
    .card-3d:hover {
        transform: translateY(-15px);
        box-shadow: 0 30px 60px rgba(0,0,0,0.4);
    }
    .card-title {
        font-size: 36px; /* Tăng 200% */
        font-weight: 700;
        margin-bottom: 20px;
        text-transform: uppercase;
        letter-spacing: 2px;
        opacity: 0.95;
    }
    .card-value {
        font-size: 72px; /* Tăng 200% */
        font-weight: 900;
        text-shadow: 4px 4px 8px rgba(0,0,0,0.4);
    }
    
    /* MÀU SẮC 3D GRADIENT CHO TỪNG LOẠI */
    .bg-sales { background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d 0%, #ffc371 100%); }
    .bg-profit { background: linear-gradient(135deg, #f83600 0%, #f9d423 100%); }
    .bg-ncc { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    .bg-recv { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }
    .bg-del { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
    .bg-pend { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }

    /* Cảnh báo lỗi nổi bật */
    .stAlert { font-weight: bold; font-size: 24px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- THƯ VIỆN XỬ LÝ EXCEL & ĐỒ HỌA ---
try:
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
    from openpyxl.drawing.image import Image as OpenpyxlImage
    from openpyxl.utils import range_boundaries
    import matplotlib.pyplot as plt
except ImportError:
    st.error("""
        ### ⚠️ Thiếu thư viện hỗ trợ
        Hệ thống phát hiện thiếu thư viện: `openpyxl`, `matplotlib`.
        
        Nếu bạn đang chạy trên máy tính (Local), hãy mở Terminal và chạy lệnh:
        `pip install openpyxl matplotlib`
        
        Nếu bạn đang chạy trên Cloud, hãy dùng nút **"Tạo file Requirements"** trong menu Admin bên trái.
    """)
    st.stop()

# Tắt cảnh báo
warnings.filterwarnings("ignore")

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
REQUIREMENTS_FILE = "requirements.txt"

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
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def safe_filename(s): 
    # Loại bỏ ký tự đặc biệt, giữ lại chữ cái, số, dấu gạch ngang, gạch dưới
    # Thay thế khoảng trắng bằng dấu gạch dưới
    s = safe_str(s)
    s = re.sub(r'[\\/*?:"<>|]', '', s) # Loại bỏ ký tự cấm trong tên file Windows
    s = s.replace(' ', '_')
    return s

def to_float(val):
    """
    Chuyển đổi chuỗi sang số float, xử lý mạnh mẽ các trường hợp:
    - Range giá: "1800-2200" -> lấy max là 2200
    - Text lẫn số: "1152RMB" -> 1152
    - Dấu phẩy: "1,152.50" -> 1152.5
    - Số 9 -> 9.0
    """
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s.lower() in ['nan', 'none', 'null']: return 0.0
    
    # Xử lý dọn dẹp sơ bộ các ký tự tiền tệ và dấu phẩy ngàn
    s_clean = s.replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace("rmb", "").replace("vnd", "")
    
    try:
        # Tìm tất cả các số (nguyên hoặc thập phân) trong chuỗi
        # Regex này bắt: 123, 123.45, -123.45
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", s_clean)
        
        if not numbers:
            return 0.0
        
        # Chuyển list string thành list float
        floats = [float(n) for n in numbers]
        
        # Trả về giá trị lớn nhất (Logic: Giá mua an toàn nhất là giá cao nhất trong range)
        return max(floats)
    except:
        return 0.0

def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"

def clean_lookup_key(s):
    """
    Hàm làm sạch khóa tìm kiếm mạnh mẽ hơn.
    Chỉ giữ lại chữ cái và số, bỏ hết dấu cách, gạch ngang, chấm...
    VD: "Item-532" -> "item532", "532 " -> "532"
    """
    if s is None: return ""
    s_str = str(s)
    # Loại bỏ .0 nếu là số nguyên dạng float (vd: 532.0 -> 532)
    try:
        f = float(s_str)
        if f.is_integer(): s_str = str(int(f))
    except: pass
    
    # Chỉ giữ lại a-z, 0-9
    clean = re.sub(r'[^a-zA-Z0-9]', '', s_str).lower()
    return clean

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime):
            dt_order = order_date_str
        else:
            dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

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
    expr = re.sub(r'[^0-9.+\-*/()]', '', expr)
    try: return float(eval(expr))
    except: return 0.0

def load_csv(path, cols):
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype=str, on_bad_lines='skip').fillna("")
            for c in cols:
                if c not in df.columns: df[c] = ""
            return df[cols]
        except: pass
    return pd.DataFrame(columns=cols)

def save_csv(path, df):
    if df is not None:
        try: df.to_csv(path, index=False, encoding="utf-8-sig")
        except: st.error(f"Lỗi lưu file {path}")

def open_folder(path):
    try:
        if platform.system() == "Windows": os.startfile(path)
        elif platform.system() == "Darwin": subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])
    except: pass 
    # st.warning("Không thể mở folder tự động trên Cloud.")

def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        found_merge = False
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                top_left_cell = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                top_left_cell.value = value
                found_merge = True
                break
        if not found_merge: cell.value = value
    except: pass

# --- COLUMN DEFINITIONS ---
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
HISTORY_COLS = ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "total_cost", "profit", "supplier", "status", "delivery_date", "po_number", "gap", "end_user", "buyer", "tax", "vat", "trans", "mgmt"]

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
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]:
        st.session_state[f"pct_{k}"] = "0"

# Load DBs
customers_df = load_csv(CUSTOMERS_CSV, MASTER_COLUMNS)
suppliers_df = load_csv(SUPPLIERS_CSV, MASTER_COLUMNS)
purchases_df = load_csv(PURCHASES_CSV, PURCHASE_COLUMNS)
for c in ["type", "nuoc"]:
    if c not in purchases_df.columns: purchases_df[c] = ""

sales_history_df = load_csv(SALES_HISTORY_CSV, HISTORY_COLS)
tracking_df = load_csv(TRACKING_CSV, TRACKING_COLS)
payment_df = load_csv(PAYMENT_CSV, PAYMENT_COLS)
paid_history_df = load_csv(PAID_HISTORY_CSV, PAYMENT_COLS)
db_supplier_orders = load_csv(DB_SUPPLIER_ORDERS, [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
db_customer_orders = load_csv(DB_CUSTOMER_ORDERS, [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

# =============================================================================
# 3. SIDEBAR (ADMIN & MENU)
# =============================================================================
st.sidebar.title("CRM V4800")
st.sidebar.markdown(f"**Version:** `{APP_VERSION}`")
with st.sidebar.expander("📝 Release Notes"):
    st.markdown(RELEASE_NOTE)

admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)

if is_admin:
    st.sidebar.divider()
    st.sidebar.write("🔧 **Admin Tools**")
    if st.sidebar.button("📦 Tạo file Requirements.txt"):
        req_content = "streamlit\npandas\nopenpyxl\nmatplotlib\nplotly"
        try:
            with open(REQUIREMENTS_FILE, "w") as f:
                f.write(req_content)
            st.sidebar.success(f"Đã tạo {REQUIREMENTS_FILE}! Bạn có thể deploy ngay.")
        except Exception as e:
            st.sidebar.error(f"Lỗi: {e}")

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
    
    col_act1, col_act2 = st.columns([1, 1])
    if col_act1.button("🔄 CẬP NHẬT DỮ LIỆU"): st.rerun()
    if col_act2.button("⚠️ RESET DATA (Admin)"):
        if admin_pwd == ADMIN_PASSWORD:
            for f in [DB_CUSTOMER_ORDERS, DB_SUPPLIER_ORDERS, SALES_HISTORY_CSV, TRACKING_CSV, PAYMENT_CSV, PAID_HISTORY_CSV]:
                 if os.path.exists(f): os.remove(f)
            st.success("Đã reset toàn bộ dữ liệu!")
            st.rerun()
        else: st.error("Sai mật khẩu Admin!")
    
    st.divider()

    # Calculation Logic
    rev = db_customer_orders['total_price'].apply(to_float).sum()
    profit = sales_history_df['profit'].apply(to_float).sum()
    
    cost_cols = ["gap", "end_user", "buyer", "tax", "vat", "trans", "mgmt"]
    for c in cost_cols:
         if c not in sales_history_df.columns: sales_history_df[c] = "0"
    
    total_cost_calc = 0.0
    for _, r in sales_history_df.iterrows():
        try:
             g = to_float(r["gap"]) * 0.6
             e = to_float(r["end_user"])
             b = to_float(r["buyer"])
             t = to_float(r["tax"])
             v = to_float(r["vat"])
             tr = to_float(r["trans"])
             m = to_float(r["mgmt"])
             total_cost_calc += (g + e + b + t + v + tr + m)
        except: pass

    total_purchase_val = db_supplier_orders['total_vnd'].apply(to_float).sum()
    
    po_ordered_ncc = len(tracking_df[tracking_df['order_type'] == 'NCC'])
    po_total_recv = len(db_customer_orders['po_number'].unique())
    po_delivered = len(tracking_df[(tracking_df['order_type'] == 'KH') & (tracking_df['status'] == 'Đã giao hàng')])
    po_pending = po_total_recv - po_delivered

    # --- 3D CARDS DISPLAY ---
    # Row 1: Financial Metrics
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""
        <div class="card-3d bg-sales">
            <div class="card-title">DOANH THU BÁN (VND)</div>
            <div class="card-value">{fmt_num(rev)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="card-3d bg-cost">
            <div class="card-title">TỔNG GIÁ TRỊ MUA (VND)</div>
            <div class="card-value">{fmt_num(total_purchase_val)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="card-3d bg-profit">
            <div class="card-title">LỢI NHUẬN TỔNG (VND)</div>
            <div class="card-value">{fmt_num(profit)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # Row 2: PO Metrics
    c4, c5, c6, c7 = st.columns(4)
    with c4:
        st.markdown(f"""
        <div class="card-3d bg-ncc">
            <div class="card-title">ĐƠN HÀNG ĐÃ ĐẶT NCC</div>
            <div class="card-value">{po_ordered_ncc}</div>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        st.markdown(f"""
        <div class="card-3d bg-recv">
            <div class="card-title">TỔNG PO ĐÃ NHẬN</div>
            <div class="card-value">{po_total_recv}</div>
        </div>
        """, unsafe_allow_html=True)
    with c6:
        st.markdown(f"""
        <div class="card-3d bg-del">
            <div class="card-title">TỔNG PO ĐÃ GIAO</div>
            <div class="card-value">{po_delivered}</div>
        </div>
        """, unsafe_allow_html=True)
    with c7:
        st.markdown(f"""
        <div class="card-3d bg-pend">
            <div class="card-title">TỔNG PO CHƯA GIAO</div>
            <div class="card-value">{po_pending}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    st.metric("TỔNG CHI PHÍ KHÁC (VND)", fmt_num(total_cost_calc))
    st.caption("*Tổng chi phí = (GAP*60%) + EndUser + Buyer + ImportTax + VAT + Trans + MgmtFee")
    st.divider()
    
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
            top_supp_g = top_supp.groupby('supplier')['val'].sum().sort_values(ascending=False).head(10)
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
                wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                img_map = {}
                for img in getattr(ws, '_images', []):
                    r_idx = img.anchor._from.row + 1; c_idx = img.anchor._from.col
                    if c_idx == 12: 
                        img_name = f"img_r{r_idx}_{datetime.now().strftime('%f')}.png"
                        img_path = os.path.join(IMG_FOLDER, img_name)
                        with open(img_path, "wb") as f: f.write(img._data())
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
                        "image_path": im_path,
                        "type": safe_str(r.iloc[13]) if len(r) > 13 else "",
                        "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else ""
                    }
                    if item["item_code"] or item["item_name"]: rows.append(item)
                purchases_df = pd.DataFrame(rows)
                save_csv(PURCHASES_CSV, purchases_df)
                st.success(f"Đã import {len(rows)} dòng và lưu ảnh!")
                st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    with col_p2:
        search_term = st.text_input("🔍 Tìm kiếm hàng hóa (NCC)")
    
    if not purchases_df.empty:
        df_show = purchases_df.copy()
        if search_term:
            mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or 
                                             search_term.lower() in str(x['item_name']).lower() or 
                                             search_term.lower() in str(x['specs']).lower(), axis=1)
            df_show = df_show[mask]
        
        st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Image", help="Ảnh")}, use_container_width=True, hide_index=True)
    else: st.info("Chưa có dữ liệu.")

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
        with c2: quote_name = st.text_input("Tên Báo Giá / Mã BG")
        with c3:
             if st.button("✨ TẠO MỚI (RESET)", type="primary"):
                 st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                 for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"
                 st.rerun()

        st.markdown("**Tham số chi phí (%)**")
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
            uploaded_rfq = st.file_uploader("📂 Import RFQ (Excel)", type=["xlsx"])
            if uploaded_rfq and st.button("Load RFQ"):
                try:
                    # TẠO KHÓA TÌM KIẾM SẠCH CHO DB
                    purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                    purchases_df["_clean_specs"] = purchases_df["specs"].apply(clean_lookup_key)
                    purchases_df["_clean_name"] = purchases_df["item_name"].apply(clean_lookup_key)
                    
                    df_rfq = pd.read_excel(uploaded_rfq, header=None, dtype=str).fillna("")
                    new_data = []
                    
                    for i, r in df_rfq.iloc[1:].iterrows():
                        c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2])
                        s_raw = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                        
                        # Fix Import: Only require Qty > 0 and at least one ID field
                        if qty <= 0: continue
                        if not c_raw and not n_raw and not s_raw: continue

                        # READ PRICES FROM EXCEL IF AVAILABLE (Indices: 5=RMB, 7=ExRate, 8=VND)
                        ex_rmb = to_float(r.iloc[5]) if len(r) > 5 else 0
                        ex_rate = to_float(r.iloc[7]) if len(r) > 7 else 0
                        ex_vnd = to_float(r.iloc[8]) if len(r) > 8 else 0
                        ex_supp = safe_str(r.iloc[11]) if len(r) > 11 else ""
                        ex_lead = safe_str(r.iloc[10]) if len(r) > 10 else ""

                        clean_c = clean_lookup_key(c_raw); clean_s = clean_lookup_key(s_raw); clean_n = clean_lookup_key(n_raw)
                        target_row = None
                        found_in_db = pd.DataFrame()
                        
                        # LOGIC IMPORT QUAN TRỌNG: TÌM TRONG DB NCC
                        # 1. Tìm theo Mã hàng
                        if c_raw:
                            found_in_db = purchases_df[purchases_df["_clean_code"] == clean_c]
                        
                        # 2. Nếu không thấy Mã, Tìm theo Tên hàng (Fallback)
                        if found_in_db.empty and n_raw:
                            found_in_db = purchases_df[purchases_df["_clean_name"] == clean_n]

                        if not found_in_db.empty:
                            # Sắp xếp để lấy dòng có giá cao nhất
                            found_in_db = found_in_db.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False)
                            
                            if s_raw:
                                found_specs = found_in_db[found_in_db["_clean_specs"] == clean_s]
                                if not found_specs.empty:
                                     found_specs = found_specs.sort_values(by="buying_price_rmb", key=lambda x: x.apply(to_float), ascending=False)
                                     target_row = found_specs.iloc[0]
                                else:
                                     target_row = found_in_db.iloc[0]
                            else:
                                target_row = found_in_db.iloc[0]
                        
                        it = {k:"0" if "price" in k or "val" in k or "fee" in k else "" for k in QUOTE_KH_COLUMNS}
                        it.update({
                            "no": safe_str(r.iloc[0]), "item_code": c_raw, "item_name": n_raw, 
                            "specs": s_raw, "qty": fmt_num(qty)
                        })

                        # PRICE LOGIC: Excel Priority -> Then DB -> Default 0
                        # QUAN TRỌNG: Lấy giá từ DB nếu Excel = 0
                        db_rmb = to_float(target_row["buying_price_rmb"]) if target_row is not None else 0
                        db_vnd = to_float(target_row["buying_price_vnd"]) if target_row is not None else 0
                        db_rate = to_float(target_row["exchange_rate"]) if target_row is not None else 0
                        db_supp = target_row["supplier_name"] if target_row is not None else ""
                        db_lead = target_row["leadtime"] if target_row is not None else ""
                        db_img = target_row["image_path"] if target_row is not None else ""

                        # NẾU GIÁ EXCEL = 0 THÌ LẤY GIÁ DB (Dòng này sửa lỗi 532, 533)
                        final_rmb = ex_rmb if ex_rmb > 0 else db_rmb
                        final_vnd = ex_vnd if ex_vnd > 0 else db_vnd
                        final_rate = ex_rate if ex_rate > 0 else db_rate
                        final_supp = ex_supp if ex_supp else db_supp
                        final_lead = ex_lead if ex_lead else db_lead
                        final_img = db_img

                        it.update({
                            "buying_price_rmb": fmt_num(final_rmb),
                            "total_buying_price_rmb": fmt_num(final_rmb * qty),
                            "exchange_rate": fmt_num(final_rate),
                            "buying_price_vnd": fmt_num(final_vnd),
                            "total_buying_price_vnd": fmt_num(final_vnd * qty),
                            "supplier_name": final_supp,
                            "image_path": final_img,
                            "leadtime": final_lead
                        })
                        new_data.append(it)
                    
                    st.session_state.current_quote_df = pd.DataFrame(new_data)
                    st.success(f"Đã load {len(new_data)} dòng từ RFQ và khớp dữ liệu NCC!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi: {e}")
        
        with c_imp2:
             uploaded_hist = st.file_uploader("📂 Load Lịch Sử", type=["xlsx", "csv"])
             if uploaded_hist and st.button("Load Lịch Sử"):
                 try:
                     if uploaded_hist.name.endswith('.csv'): df_h = pd.read_csv(uploaded_hist, dtype=str).fillna("")
                     else: df_h = pd.read_excel(uploaded_hist, dtype=str).fillna("")
                     st.session_state.current_quote_df = df_h
                     for col in QUOTE_KH_COLUMNS:
                         if col not in st.session_state.current_quote_df.columns: st.session_state.current_quote_df[col] = ""
                     
                     found_meta = False
                     for root, dirs, files in os.walk(QUOTE_ROOT_FOLDER):
                         if uploaded_hist.name + ".json" in files:
                             with open(os.path.join(root, uploaded_hist.name + ".json"), "r", encoding='utf-8') as f:
                                 meta = json.load(f)
                                 for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = str(meta.get(f"pct_{k}", "0"))
                                 found_meta = True
                             break
                     if found_meta: st.success("Loaded meta!")
                     st.rerun()
                 except Exception as e: st.error(f"Lỗi: {e}")

        # --- DATA EDITOR ---
        st.markdown("### Chi tiết báo giá")
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        ap_formula = f1.text_input("AP Formula (vd: BUY*1.1)", key="ap_f")
        if f2.button("Apply AP"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r.get("buying_price_vnd", 0)); a = to_float(r.get("ap_price", 0))
                st.session_state.current_quote_df.at[i, "ap_price"] = fmt_num(parse_formula(ap_formula, b, a))
            st.rerun()

        unit_formula = f3.text_input("Unit Formula (vd: AP/0.8)", key="unit_f")
        if f4.button("Apply Unit"):
            for i, r in st.session_state.current_quote_df.iterrows():
                b = to_float(r.get("buying_price_vnd", 0)); a = to_float(r.get("ap_price", 0))
                st.session_state.current_quote_df.at[i, "unit_price"] = fmt_num(parse_formula(unit_formula, b, a))
            st.rerun()

        edited_df = st.data_editor(
            st.session_state.current_quote_df,
            key="quote_editor",
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "image_path": st.column_config.ImageColumn("Img"),
                "qty": st.column_config.NumberColumn("Qty", format="%.0f"),
                "buying_price_rmb": st.column_config.NumberColumn("Buy(RMB)", format="%.2f"),
                "buying_price_vnd": st.column_config.NumberColumn("Buy(VND)", format="%.0f"),
                "profit_pct": st.column_config.TextColumn("%")
            }
        )
        
        # --- AUTO-CALC ---
        pend = to_float(pct_end)/100; pbuy = to_float(pct_buy)/100
        ptax = to_float(pct_tax)/100; pvat = to_float(pct_vat)/100
        ppay = to_float(pct_pay)/100; pmgmt = to_float(pct_mgmt)/100
        global_trans = to_float(val_trans)
        use_global = global_trans > 0
        df_temp = edited_df.copy()
        
        for i, r in df_temp.iterrows():
            qty = to_float(r.get("qty", 0)); buy_vnd = to_float(r.get("buying_price_vnd", 0))
            buy_rmb = to_float(r.get("buying_price_rmb", 0))
            ap = to_float(r.get("ap_price", 0)); unit = to_float(r.get("unit_price", 0))
            
            cur_trans = to_float(r.get("transportation", 0))
            use_trans = global_trans if use_global else cur_trans
            
            t_buy = qty * buy_vnd; ap_tot = ap * qty; total = unit * qty; gap = total - ap_tot
            end_val = ap_tot * pend; buyer_val = total * pbuy; tax_val = t_buy * ptax; vat_val = total * pvat
            mgmt_val = total * pmgmt; pay_val = gap * ppay; tot_trans = use_trans * qty
            
            cost = t_buy + gap + end_val + buyer_val + tax_val + vat_val + mgmt_val + tot_trans
            prof = total - cost + pay_val
            pct = (prof/total*100) if total else 0
            
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

        if not df_temp.equals(st.session_state.current_quote_df):
             st.session_state.current_quote_df = df_temp
             st.rerun()

        st.divider()
        c_rev, c_sav, c_exp = st.columns([1, 1, 1])
        
        with c_rev:
            if st.button("🔍 REVIEW & KIỂM TRA LỢI NHUẬN", type="primary"):
                st.session_state.show_review_table = not st.session_state.get('show_review_table', False)
        
        # --- FULL WIDTH REVIEW ---
        if st.session_state.get('show_review_table', False):
            st.write("### Bảng kiểm tra lợi nhuận")
            def highlight_low_profit(val):
                try:
                    p = float(val.replace("%",""))
                    return 'background-color: #ffcccc; color: red; font-weight: bold' if p < 10 else ''
                except: return ''
            cols_review = ["item_code", "item_name", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]
            df_review = st.session_state.current_quote_df[cols_review].copy()
            st.dataframe(df_review.style.applymap(highlight_low_profit, subset=['profit_pct']), use_container_width=True)
            
            low_profits = []
            for idx, r in df_review.iterrows():
                try:
                    if float(r["profit_pct"].replace("%","")) < 10: low_profits.append(f"{r['item_code']}")
                except: pass
            if low_profits: st.error(f"⚠️ CẢNH BÁO: Các mã sau có lợi nhuận < 10%: {', '.join(low_profits)}")
            else: st.success("✅ Tất cả các mã đều có lợi nhuận > 10%")

        with c_sav:
            if st.button("💾 LƯU LỊCH SỬ & FILE"):
                if not sel_cust or not quote_name: st.error("Thiếu thông tin")
                else:
                    now = datetime.now()
                    # FIX PATH: Dùng safe_filename cho cả tên khách và tên báo giá để tránh ký tự lạ
                    safe_cust = safe_filename(sel_cust)
                    safe_quote = safe_filename(quote_name)
                    
                    base_path = os.path.join(QUOTE_ROOT_FOLDER, safe_cust, now.strftime("%Y"), now.strftime("%b").upper())
                    
                    if not os.path.exists(base_path): 
                        os.makedirs(base_path)
                        
                    csv_name = f"History_{safe_quote}.csv"
                    full_path = os.path.join(base_path, csv_name)
                    
                    try:
                        st.session_state.current_quote_df.to_csv(full_path, index=False, encoding='utf-8-sig')
                        
                        meta_data = {
                            "pct_end": st.session_state.pct_end, "pct_buy": st.session_state.pct_buy,
                            "pct_tax": st.session_state.pct_tax, "pct_vat": st.session_state.pct_vat,
                            "pct_pay": st.session_state.pct_pay, "pct_mgmt": st.session_state.pct_mgmt,
                            "pct_trans": st.session_state.pct_trans, "quote_name": quote_name,
                            "customer": sel_cust, "date": now.strftime("%d/%m/%Y")
                        }
                        
                        json_path = os.path.join(base_path, csv_name + ".json")
                        with open(json_path, "w", encoding='utf-8') as f:
                            json.dump(meta_data, f, ensure_ascii=False, indent=4)

                        d = now.strftime("%d/%m/%Y")
                        new_hist_rows = []
                        for _, r in st.session_state.current_quote_df.iterrows():
                            rev = to_float(r["total_price_vnd"]); prof = to_float(r["profit_vnd"]); cost = rev - prof
                            new_hist_rows.append({
                                "date":d, "quote_no":quote_name, "customer":sel_cust, "item_code":r["item_code"], 
                                "item_name":r["item_name"], "specs":r["specs"], "qty":r["qty"], "total_revenue":fmt_num(rev), 
                                "total_cost":fmt_num(cost), "profit":fmt_num(prof), "supplier":r["supplier_name"], 
                                "status":"Pending", "delivery_date":"", "po_number": "",
                                "gap":r["gap"], "end_user":r["end_user_val"], "buyer":r["buyer_val"], 
                                "tax":r["import_tax_val"], "vat":r["vat_val"], "trans":r["transportation"], "mgmt":r["mgmt_fee"]
                            })
                        sales_history_df = pd.concat([sales_history_df, pd.DataFrame(new_hist_rows)], ignore_index=True)
                        save_csv(SALES_HISTORY_CSV, sales_history_df)
                        
                        st.success(f"✅ Đã lưu thành công!\nFolder: {base_path}\nFile: {csv_name}")
                        st.rerun() # Refresh to show updates
                        
                    except Exception as e:
                        st.error(f"Lỗi khi lưu file: {str(e)}")

        with c_exp:
            if st.button("XUẤT EXCEL"):
                if not os.path.exists(TEMPLATE_FILE): st.error("Thiếu template")
                else:
                    try:
                        now = datetime.now()
                        safe_cust = safe_filename(sel_cust)
                        safe_quote = safe_filename(quote_name)
                        
                        target_dir = os.path.join(QUOTE_ROOT_FOLDER, safe_cust, now.strftime("%Y"), now.strftime("%b").upper())
                        if not os.path.exists(target_dir): os.makedirs(target_dir)
                        
                        fname = f"Quote_{safe_quote}_{now.strftime('%Y%m%d')}.xlsx"
                        save_path = os.path.join(target_dir, fname)
                        
                        wb = load_workbook(TEMPLATE_FILE); ws = wb.active
                        safe_write_merged(ws, 1, 2, sel_cust); safe_write_merged(ws, 2, 8, quote_name)
                        safe_write_merged(ws, 1, 8, now.strftime("%d-%b-%Y"))
                        if not st.session_state.current_quote_df.empty:
                            lt = safe_str(st.session_state.current_quote_df.iloc[0]["leadtime"])
                            safe_write_merged(ws, 8, 8, lt)
                        start_row = 11
                        for idx, r in st.session_state.current_quote_df.iterrows():
                            ri = start_row + idx
                            safe_write_merged(ws, ri, 1, r["no"]); safe_write_merged(ws, ri, 3, r["item_code"])
                            safe_write_merged(ws, ri, 4, r["item_name"]); safe_write_merged(ws, ri, 5, r["specs"])
                            safe_write_merged(ws, ri, 6, to_float(r["qty"])); safe_write_merged(ws, ri, 7, to_float(r["unit_price"]))
                            safe_write_merged(ws, ri, 8, to_float(r["total_price_vnd"]))
                            thin = Side(border_style="thin", color="000000")
                            for ci in [1,3,4,5,6,7,8]:
                                c = ws.cell(row=ri, column=ci); c.border = Border(top=thin, left=thin, right=thin, bottom=thin)
                        wb.save(save_path)
                        st.success(f"Đã xuất file: {save_path}")
                        with open(save_path, "rb") as f: st.download_button("Tải File", f, file_name=fname)
                    except Exception as e: st.error(str(e))

    with tab3_2:
        st.subheader("Tra cứu lịch sử giá")
        search_history_term = st.text_input("🔍 Tra cứu nhanh")
        up_bulk = st.file_uploader("Tra cứu hàng loạt (Excel: No, Code, Name, Specs)", type=["xlsx"])
        if up_bulk and st.button("🔍 Check Bulk"):
            df_check = pd.read_excel(up_bulk, header=None, dtype=str).fillna("")
            results = []
            db_customer_orders["_clean_code"] = db_customer_orders["item_code"].apply(clean_lookup_key)
            sales_history_df["_clean_code"] = sales_history_df["item_code"].apply(clean_lookup_key)
            for i, r in df_check.iloc[1:].iterrows():
                c_raw = safe_str(r.iloc[1]); specs_raw = safe_str(r.iloc[3])
                if not c_raw: continue
                clean_c = clean_lookup_key(c_raw); found = False
                match_po = db_customer_orders[db_customer_orders["_clean_code"]==clean_c]
                for _, po in match_po.iterrows():
                    results.append({"Status":"Đã có PO", "Date":po["order_date"], "Item":po["item_code"], "Price":po["unit_price"], "Ref PO":po["po_number"]}); found = True
                if not found:
                    match_qt = sales_history_df[sales_history_df["_clean_code"]==clean_c]
                    for _, qt in match_qt.iterrows():
                         u = to_float(qt["total_revenue"])/to_float(qt["qty"]) if to_float(qt["qty"]) > 0 else 0
                         results.append({"Status":"Đã báo giá", "Date":qt["date"], "Item":qt["item_code"], "Price":fmt_num(u), "Ref PO":qt["quote_no"]}); found = True
                if not found: results.append({"Status":"Chưa có", "Date":"", "Item":c_raw, "Price":"", "Ref PO":""})
            st.dataframe(pd.DataFrame(results), use_container_width=True)

# --- TAB 4: QUẢN LÝ PO ---
with tab4:
    col_po1, col_po2 = st.columns(2)
    
    with col_po1:
        st.subheader("1. Đặt hàng NCC (PO NCC)")
        po_ncc_no = st.text_input("Số PO NCC"); supp_list = suppliers_df["short_name"].tolist()
        po_ncc_supp = st.selectbox("NCC", [""] + supp_list); po_ncc_date = st.text_input("Ngày đặt", value=datetime.now().strftime("%d/%m/%Y"))
        up_ncc = st.file_uploader("Excel Items NCC", type=["xlsx"], key="up_ncc")
        if up_ncc:
             df_ncc = pd.read_excel(up_ncc, dtype=str).fillna(""); temp_ncc = []
             purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
             for i, r in df_ncc.iterrows():
                 code = safe_str(r.iloc[1]); specs = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                 clean_c = clean_lookup_key(code); found = purchases_df[purchases_df["_clean_code"]==clean_c]
                 it = {"item_code":code, "qty":fmt_num(qty), "specs": specs, "item_name": safe_str(r.iloc[2])}
                 if not found.empty:
                     fr = found.iloc[0]
                     it.update({"item_name":fr["item_name"], "price_rmb":fr["buying_price_rmb"], "total_rmb":fmt_num(to_float(fr["buying_price_rmb"])*qty), "price_vnd":fr["buying_price_vnd"], "total_vnd":fmt_num(to_float(fr["buying_price_vnd"])*qty), "exchange_rate":fr["exchange_rate"], "eta":calc_eta(po_ncc_date, fr["leadtime"]), "supplier":fr["supplier_name"]})
                 else: it.update({"price_rmb":"0", "total_rmb":"0", "price_vnd":"0", "total_vnd":"0", "exchange_rate":"0", "supplier":po_ncc_supp})
                 temp_ncc.append(it)
             st.session_state.temp_supp_order_df = pd.DataFrame(temp_ncc)
        
        # Xóa dòng NCC
        if "Delete" not in st.session_state.temp_supp_order_df.columns: st.session_state.temp_supp_order_df["Delete"] = False
        if st.button("🗑️ Xóa dòng đã chọn (NCC)"):
            st.session_state.temp_supp_order_df = st.session_state.temp_supp_order_df[~st.session_state.temp_supp_order_df["Delete"]]
            st.rerun()

        edited_ncc = st.data_editor(st.session_state.temp_supp_order_df, num_rows="dynamic", key="ed_ncc", use_container_width=True)
        if not edited_ncc.equals(st.session_state.temp_supp_order_df): st.session_state.temp_supp_order_df = edited_ncc; st.rerun()

        if st.button("🚀 XÁC NHẬN PO NCC"):
            if not po_ncc_no: st.error("Thiếu PO"); st.stop()
            final_df = st.session_state.temp_supp_order_df.copy(); 
            if "Delete" in final_df.columns: del final_df["Delete"]
            final_df["po_number"] = po_ncc_no; final_df["order_date"] = po_ncc_date
            db_supplier_orders = pd.concat([db_supplier_orders, final_df], ignore_index=True)
            save_csv(DB_SUPPLIER_ORDERS, db_supplier_orders)
            
            now = datetime.now(); year_str = now.strftime("%Y"); month_str = now.strftime("%b").upper()
            base_po_path = os.path.join(PO_EXPORT_FOLDER, year_str, month_str)
            if not os.path.exists(base_po_path): os.makedirs(base_po_path)
            
            for supp, g in final_df.groupby("supplier"):
                new_track = {"no": len(tracking_df)+1, "po_no": po_ncc_no, "partner": supp, "status": "Đã đặt hàng", "eta": g.iloc[0]["eta"], "proof_image": "", "order_type": "NCC", "last_update": po_ncc_date, "finished": "0"}
                tracking_df = pd.concat([tracking_df, pd.DataFrame([new_track])], ignore_index=True)
                supp_path = os.path.join(base_po_path, safe_filename(supp))
                if not os.path.exists(supp_path): os.makedirs(supp_path)
                wb = Workbook(); ws = wb.active; ws.title = "PO"
                ws.append(["No", "Item code", "Item name", "Specs", "Q'ty", "Buying price(RMB)", "Total(RMB)", "ETA"])
                for idx, r in g.iterrows(): ws.append([r.get("no", idx+1), r["item_code"], r["item_name"], r["specs"], to_float(r["qty"]), to_float(r["price_rmb"]), to_float(r["total_rmb"]), r["eta"]])
                wb.save(os.path.join(supp_path, f"PO_{safe_filename(po_ncc_no)}_{safe_filename(supp)}.xlsx")); open_folder(supp_path)
            save_csv(TRACKING_CSV, tracking_df); st.success("Done!")

    # === PO KHÁCH ===
    with col_po2:
        st.subheader("2. PO Khách Hàng")
        po_cust_no = st.text_input("Số PO Khách"); cust_po_list = customers_df["short_name"].tolist()
        po_cust_name = st.selectbox("Khách Hàng", [""] + cust_po_list); po_cust_date = st.text_input("Ngày nhận", value=datetime.now().strftime("%d/%m/%Y"))
        
        uploaded_files = st.file_uploader("Upload File PO (Nhiều file)", type=["xlsx", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        if "selected_po_files" not in st.session_state: st.session_state.selected_po_files = []
        if uploaded_files:
             for f in uploaded_files:
                 if f.name not in [x.name for x in st.session_state.selected_po_files]: st.session_state.selected_po_files.append(f)
        
        if st.session_state.selected_po_files:
            files_to_keep = []
            for f in st.session_state.selected_po_files:
                c1, c2 = st.columns([8,2]); c1.text(f.name)
                if not c2.button("✖️", key=f"del_{f.name}"): files_to_keep.append(f)
            st.session_state.selected_po_files = files_to_keep
            
            # Auto Parse Excel
            for f in st.session_state.selected_po_files:
                if f.name.endswith('.xlsx'):
                    try:
                         df_c = pd.read_excel(f, dtype=str).fillna(""); temp_c = []
                         purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                         for i, r in df_c.iterrows():
                             code = safe_str(r.iloc[1]); qty = to_float(r.iloc[4]); specs = safe_str(r.iloc[3])
                             price = 0; hist_match = sales_history_df[(sales_history_df["customer"] == po_cust_name) & (sales_history_df["item_code"] == code)]
                             if not hist_match.empty: price = to_float(hist_match.iloc[-1]["total_revenue"]) / to_float(hist_match.iloc[-1]["qty"])
                             eta = ""; clean_code = clean_lookup_key(code); found_pur = purchases_df[purchases_df["_clean_code"] == clean_code]
                             if not found_pur.empty: eta = calc_eta(po_cust_date, found_pur.iloc[0]["leadtime"])
                             temp_c.append({"item_code":code, "item_name":safe_str(r.iloc[2]), "specs":specs, "qty":fmt_num(qty), "unit_price":fmt_num(price), "total_price":fmt_num(price*qty), "eta": eta})
                         st.session_state.temp_cust_order_df = pd.DataFrame(temp_c)
                    except: pass
        
        # Xóa dòng PO Khách
        if "Delete" not in st.session_state.temp_cust_order_df.columns: st.session_state.temp_cust_order_df["Delete"] = False
        if st.button("🗑️ Xóa dòng đã chọn (KH)", key="del_cust_row"):
            st.session_state.temp_cust_order_df = st.session_state.temp_cust_order_df[~st.session_state.temp_cust_order_df["Delete"]]
            st.rerun()

        edited_cust_po = st.data_editor(st.session_state.temp_cust_order_df, num_rows="dynamic", key="ed_cust_po", use_container_width=True)
        if not edited_cust_po.equals(st.session_state.temp_cust_order_df): st.session_state.temp_cust_order_df = edited_cust_po; st.rerun()

        if st.button("💾 LƯU PO KHÁCH"):
             if not po_cust_no: st.error("Thiếu PO"); st.stop()
             final_c = st.session_state.temp_cust_order_df.copy(); 
             if "Delete" in final_c.columns: del final_c["Delete"]
             final_c["po_number"] = po_cust_no; final_c["customer"] = po_cust_name; final_c["order_date"] = po_cust_date
             db_customer_orders = pd.concat([db_customer_orders, final_c], ignore_index=True); save_csv(DB_CUSTOMER_ORDERS, db_customer_orders)
             
             eta_list = [datetime.strptime(x, "%d/%m/%Y") for x in final_c["eta"] if x]
             final_eta = max(eta_list).strftime("%d/%m/%Y") if eta_list else ""
             tracking_df = pd.concat([tracking_df, pd.DataFrame([{"no": len(tracking_df)+1, "po_no": po_cust_no, "partner": po_cust_name, "status": "Đang đợi hàng về", "eta": final_eta, "proof_image": "", "order_type": "KH", "last_update": po_cust_date, "finished": "0"}])], ignore_index=True)
             save_csv(TRACKING_CSV, tracking_df)
             
             now = datetime.now(); path = os.path.join(PO_CUSTOMER_FOLDER, now.strftime("%Y"), now.strftime("%b").upper(), safe_filename(po_cust_name))
             if not os.path.exists(path): os.makedirs(path)
             for f in st.session_state.selected_po_files:
                 with open(os.path.join(path, f.name), "wb") as w: w.write(f.getbuffer())
             if not st.session_state.temp_cust_order_df.empty: st.session_state.temp_cust_order_df.to_excel(os.path.join(path, f"PO_{po_cust_no}_Detail.xlsx"), index=False)
             st.session_state.selected_po_files = []; st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
             st.success("OK"); open_folder(path)

# --- TAB 5: TRACKING ---
with tab5:
    t5_1, t5_2 = st.tabs(["THEO DÕI", "LỊCH SỬ THANH TOÁN"])
    with t5_1:
        c_up, c_view = st.columns(2)
        uploaded_proof = c_up.file_uploader("Upload Ảnh Bằng Chứng", type=["png", "jpg"], key="proof_upl")
        
        st.markdown("#### Tracking Đơn Hàng")
        if "Delete" not in tracking_df.columns: tracking_df["Delete"] = False
        
        if is_admin and st.button("🗑️ Xóa dòng Tracking (Admin)"):
             tracking_df = tracking_df[~tracking_df["Delete"]]
             if "Delete" in tracking_df.columns: del tracking_df["Delete"]
             save_csv(TRACKING_CSV, tracking_df); st.rerun()

        edited_track = st.data_editor(tracking_df[tracking_df["finished"]=="0"], num_rows="dynamic", key="ed_track", use_container_width=True, column_config={"status": st.column_config.SelectboxColumn("Status", options=["Đã đặt hàng", "Đợi hàng từ TQ về VN", "Hàng đã về VN", "Hàng đã nhận ở VP", "Đang đợi hàng về", "Đã giao hàng"], required=True)})

        if st.button("Cập nhật Tracking"):
            to_keep = edited_track
            finished_rows = tracking_df[tracking_df["finished"]=="1"]
            for i, r in to_keep.iterrows():
                if r["status"] in ["Hàng đã nhận ở VP", "Đã giao hàng"]:
                    to_keep.at[i, "finished"] = "1"; to_keep.at[i, "last_update"] = datetime.now().strftime("%d/%m/%Y")
                    if r["order_type"] == "KH":
                        cust = r["partner"]; term = 30
                        f_cust = customers_df[customers_df["short_name"]==cust]
                        if not f_cust.empty: 
                            try: term = int(to_float(f_cust.iloc[0]["payment_term"]))
                            except: pass
                        due = (datetime.now() + timedelta(days=term)).strftime("%d/%m/%Y")
                        payment_df = pd.concat([payment_df, pd.DataFrame([{"no": len(payment_df)+1, "po_no": r["po_no"], "customer": cust, "invoice_no": "", "status": "Chưa thanh toán", "due_date": due, "paid_date": ""}])], ignore_index=True)
                        save_csv(PAYMENT_CSV, payment_df)

            tracking_df = pd.concat([finished_rows, to_keep], ignore_index=True)
            if "Delete" in tracking_df.columns: del tracking_df["Delete"]
            save_csv(TRACKING_CSV, tracking_df); st.success("Updated!"); st.rerun()

        view_id = c_view.text_input("ID Xem/Upload Ảnh")
        if c_view.button("Upload") and uploaded_proof and view_id:
             try:
                 fname = f"proof_{view_id}_{uploaded_proof.name}"; fpath = os.path.join(PROOF_FOLDER, fname)
                 with open(fpath, "wb") as f: f.write(uploaded_proof.getbuffer())
                 idx = tracking_df.index[tracking_df['no'].astype(str) == view_id].tolist()
                 if idx: tracking_df.at[idx[0], "proof_image"] = fpath; save_csv(TRACKING_CSV, tracking_df); st.success("OK")
             except Exception as e: st.error(str(e))
        if c_view.button("Xem") and view_id:
             idx = tracking_df.index[tracking_df['no'].astype(str) == view_id].tolist()
             if idx:
                 p = tracking_df.at[idx[0], "proof_image"]
                 if p and os.path.exists(p): st.image(p)
                 else: st.warning("No Image")

        st.divider(); st.markdown("#### 2. Theo dõi công nợ")
        if "Delete" not in payment_df.columns: payment_df["Delete"] = False
        
        pending_pay = payment_df[payment_df["status"] != "Đã thanh toán"]
        edited_pay = st.data_editor(pending_pay, key="ed_pay", num_rows="dynamic", use_container_width=True, column_config={"invoice_no": st.column_config.TextColumn("Invoice No", width="medium")})
        
        if is_admin and st.button("Xóa dòng Payment (Admin)"):
             payment_df = payment_df[~payment_df["Delete"]]
             save_csv(PAYMENT_CSV, payment_df); st.rerun()

        if st.button("Cập nhật Payment"):
             # Simple merge back
             paid_items = payment_df[payment_df["status"] == "Đã thanh toán"]
             payment_df = pd.concat([paid_items, edited_pay], ignore_index=True)
             if "Delete" in payment_df.columns: del payment_df["Delete"]
             save_csv(PAYMENT_CSV, payment_df); st.success("Updated")

        c1, c2 = st.columns(2)
        pop = c1.selectbox("Chọn PO thanh toán", pending_pay["po_no"].unique())
        if c2.button("Xác nhận ĐÃ THANH TOÁN"):
             idx = payment_df[payment_df["po_no"]==pop].index
             payment_df.loc[idx, "status"] = "Đã thanh toán"
             payment_df.loc[idx, "paid_date"] = datetime.now().strftime("%d/%m/%Y")
             paid_history_df = pd.concat([paid_history_df, payment_df.loc[idx]], ignore_index=True)
             save_csv(PAID_HISTORY_CSV, paid_history_df); save_csv(PAYMENT_CSV, payment_df); st.success("Done!"); st.rerun()

    with t5_2:
        st.subheader("Lịch sử thanh toán")
        if not paid_history_df.empty:
            paid_cust = st.selectbox("Lọc KH", ["All"] + list(paid_history_df["customer"].unique()))
            show = paid_history_df if paid_cust == "All" else paid_history_df[paid_history_df["customer"] == paid_cust]
            st.dataframe(show, use_container_width=True)
            sp = st.selectbox("Xem chi tiết PO", show["po_no"].unique())
            if sp:
                dt = db_customer_orders[db_customer_orders["po_number"] == sp]
                if not dt.empty: st.dataframe(dt[["item_code", "item_name", "specs", "qty", "unit_price", "total_price"]], use_container_width=True)
        else: st.info("Trống.")

# --- TAB 6: MASTER DATA ---
with tab6:
    t6_1, t6_2, t6_3 = st.tabs(["KHÁCH HÀNG", "NHÀ CUNG CẤP", "TEMPLATE"])
    with t6_1:
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

        edited_cust_df = st.data_editor(customers_df, key="ed_cust", num_rows="dynamic", use_container_width=True)
        if st.button("Lưu thay đổi Khách Hàng"):
            if is_admin:
                save_csv(CUSTOMERS_CSV, edited_cust_df)
                st.success("Đã lưu")
            else: st.error("Cần quyền Admin để lưu chỉnh sửa tay.")
            
    with t6_2:
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

        edited_supp_df = st.data_editor(suppliers_df, key="ed_supp", num_rows="dynamic", use_container_width=True)
        if st.button("Lưu thay đổi NCC"):
            if is_admin:
                save_csv(SUPPLIERS_CSV, edited_supp_df)
                st.success("Đã lưu")
            else: st.error("Cần quyền Admin để lưu chỉnh sửa tay.")

    with t6_3:
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
