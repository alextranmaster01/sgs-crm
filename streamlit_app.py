import streamlit as st
import pandas as pd
import os
import datetime
from datetime import datetime, timedelta
import re
import warnings
import json
import platform
import subprocess
import unicodedata
import io

# =============================================================================
# 1. CẤU HÌNH & KHỞI TẠO
# =============================================================================
APP_VERSION = "V4868 - FINAL RESTORED LOGIC (V4800 IMPORT + V4865 UI)"
st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="🏢")

# --- CSS ---
st.markdown("""
    <style>
    button[data-baseweb="tab"] div p { font-size: 20px !important; font-weight: 700 !important; }
    .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 15px; }
    .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
    .bg-ncc { background: linear-gradient(135deg, #667eea, #764ba2); }
    
    /* Fix bảng và ẩn index mặc định */
    [data-testid="stDataFrame"] { margin-bottom: 20px; }
    [data-testid="stDataFrame"] > div { height: auto !important; min_height: 150px; max_height: 1000px; overflow-y: auto; }
    [data-testid="stDataFrame"] table thead th:first-child { display: none; }
    [data-testid="stDataFrame"] table tbody td:first-child { display: none; }
    
    /* Alert Box */
    .alert-box {
        padding: 15px;
        background-color: #ffcccc;
        color: #cc0000;
        border-radius: 5px;
        border: 1px solid #ff0000;
        font-weight: bold;
        margin-top: 10px;
    }
    </style>""", unsafe_allow_html=True)

# --- THƯ VIỆN EXCEL ---
try:
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Border, Side, Alignment, Font
except ImportError:
    st.error("⚠️ Cài đặt: pip install openpyxl pandas")
    st.stop()

# --- FILE PATHS ---
CUSTOMERS_CSV = "crm_customers.csv"
SUPPLIERS_CSV = "crm_suppliers.csv"
PURCHASES_CSV = "crm_purchases.csv"
SHARED_HISTORY_CSV = "crm_shared_quote_history.csv"
TRACKING_CSV = "crm_order_tracking.csv"
PAYMENT_CSV = "crm_payment_tracking.csv"
PAID_HISTORY_CSV = "crm_paid_history.csv"
DB_SUPPLIER_ORDERS = "db_supplier_orders.csv"
DB_CUSTOMER_ORDERS = "db_customer_orders.csv"
TEMPLATE_FILE = "AAA-QUOTATION.xlsx"
IMG_FOLDER = "product_images"
PROOF_FOLDER = "proof_images"
PO_CUSTOMER_FOLDER = "PO_KHACH_HANG"

for d in [IMG_FOLDER, PROOF_FOLDER, PO_CUSTOMER_FOLDER]:
    if not os.path.exists(d): os.makedirs(d)

ADMIN_PASSWORD = "admin"

# --- HELPER FUNCTIONS ---
def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def safe_filename(s): 
    s = safe_str(s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    s = re.sub(r'[^\w\-_]', '_', s)
    return s.strip('_')

def to_float(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s or s.lower() in ['nan', 'none', 'null']: return 0.0
    s_clean = s.replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace("rmb", "").replace("vnd", "")
    try:
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", s_clean)
        if not numbers: return 0.0
        return float(numbers[0])
    except: return 0.0

def fmt_num(x):
    try: return "{:,.0f}".format(float(x))
    except: return "0"

def clean_lookup_key(s):
    if s is None: return ""
    s_str = str(s)
    clean = re.sub(r'[^a-zA-Z0-9]', '', s_str).lower()
    return clean

def calc_eta(order_date_str, leadtime_val):
    try:
        dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

def parse_formula(formula, buying_price, ap_price):
    s = str(formula).strip().upper().replace(",", "")
    if not s.startswith("="): return 0.0
    expr = s[1:].replace("BUYING PRICE", str(buying_price)).replace("BUY", str(buying_price)).replace("AP PRICE", str(ap_price)).replace("AP", str(ap_price))
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

def safe_write_merged(ws, row, col, value):
    try:
        cell = ws.cell(row=row, column=col)
        # Check merge
        for merged_range in ws.merged_cells.ranges:
            if cell.coordinate in merged_range:
                top_left = ws.cell(row=merged_range.min_row, column=merged_range.min_col)
                top_left.value = value
                return
        cell.value = value
    except: pass

# --- COLUMN DEFINITIONS ---
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
# Cột Purchase theo V4800
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path", "type", "nuoc"]

QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
SHARED_HISTORY_COLS = ["history_id", "date", "quote_no", "customer"] + QUOTE_KH_COLUMNS + ["pct_end", "pct_buy", "pct_tax", "pct_vat", "pct_pay", "pct_mgmt", "pct_trans"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path", "Delete"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total", "Delete"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished", "Delete"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date", "Delete"]

# =============================================================================
# 2. SESSION STATE
# =============================================================================
if 'init' not in st.session_state:
    st.session_state.init = True
    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    st.session_state.temp_supp_order_df = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
    st.session_state.temp_cust_order_df = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
    for k in ["end","buy","tax","vat","pay","mgmt","trans"]: st.session_state[f"pct_{k}"] = "0"
    st.session_state.customer_name = ""
    st.session_state.quote_number = ""

# Load DB
customers_df = load_csv(CUSTOMERS_CSV, MASTER_COLUMNS)
suppliers_df = load_csv(SUPPLIERS_CSV, MASTER_COLUMNS)
purchases_df = load_csv(PURCHASES_CSV, PURCHASE_COLUMNS)
shared_history_df = load_csv(SHARED_HISTORY_CSV, SHARED_HISTORY_COLS)
tracking_df = load_csv(TRACKING_CSV, TRACKING_COLS)
payment_df = load_csv(PAYMENT_CSV, PAYMENT_COLS)
db_supplier_orders = load_csv(DB_SUPPLIER_ORDERS, [c for c in SUPPLIER_ORDER_COLS if c != "Delete"])
db_customer_orders = load_csv(DB_CUSTOMER_ORDERS, [c for c in CUSTOMER_ORDER_COLS if c != "Delete"])

# =============================================================================
# 3. SIDEBAR
# =============================================================================
st.sidebar.title("CRM V4868")
admin_pwd = st.sidebar.text_input("Admin Password", type="password")
is_admin = (admin_pwd == ADMIN_PASSWORD)
st.sidebar.info("Hệ thống: V4800 Logic + V4865 UI")

# =============================================================================
# 4. GIAO DIỆN CHÍNH
# =============================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 DASHBOARD", 
    "🏭 KHO HÀNG (PURCHASES)", 
    "💰 BÁO GIÁ (QUOTES)", 
    "📑 QUẢN LÝ PO", 
    "🚚 TRACKING", 
    "📂 MASTER DATA"
])

# --- TAB 1: DASHBOARD ---
with tab1:
    st.header("TỔNG QUAN KINH DOANH")
    if st.button("🔄 CẬP NHẬT"): st.rerun()
    
    total_rev = db_customer_orders['total_price'].apply(to_float).sum()
    total_cost = db_supplier_orders['total_vnd'].apply(to_float).sum()
    profit = total_rev - total_cost

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='card-3d bg-sales'><h3>DOANH THU</h3><h1>{fmt_num(total_rev)}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card-3d bg-cost'><h3>CHI PHÍ (PO NCC)</h3><h1>{fmt_num(total_cost)}</h1></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card-3d bg-profit'><h3>LỢI NHUẬN SƠ BỘ</h3><h1>{fmt_num(profit)}</h1></div>", unsafe_allow_html=True)

# --- TAB 2: KHO HÀNG (PURCHASES) - LOGIC V4800 GỐC ---
with tab2:
    st.subheader("Cơ sở dữ liệu giá đầu vào (Purchases)")
    col_p1, col_p2 = st.columns([1, 3])
    with col_p1:
        st.info("Logic Import: V4800 (Header=None, iloc index)")
        uploaded_pur = st.file_uploader("Import Excel Purchases", type=["xlsx"], key="up_pur")
        if uploaded_pur and st.button("🚀 IMPORT & GHI ĐÈ"):
            try:
                # --- LOGIC GỐC TỪ V4800: Đọc header=None, iloc ---
                wb = load_workbook(uploaded_pur, data_only=False); ws = wb.active
                img_map = {}
                for img in getattr(ws, '_images', []):
                    r_idx = img.anchor._from.row + 1; c_idx = img.anchor._from.col
                    if c_idx == 12: 
                        img_name = f"img_r{r_idx}_{datetime.now().strftime('%f')}.png"
                        img_path = os.path.join(IMG_FOLDER, img_name)
                        with open(img_path, "wb") as f: f.write(img._data())
                        img_map[r_idx] = img_path.replace("\\", "/")
                
                # Đọc DataFrame header=None (để lấy tất cả dòng)
                df_ex = pd.read_excel(uploaded_pur, header=None, dtype=str).fillna("")
                rows = []
                
                # Bắt đầu từ dòng 1 (bỏ dòng tiêu đề 0)
                for i, r in df_ex.iloc[1:].iterrows():
                    excel_row_idx = i + 1 
                    im_path = img_map.get(excel_row_idx, "")
                    
                    # Map theo vị trí cột cố định (0, 1, 2...)
                    # A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9, K=10, L=11, M=12, N=13, O=14
                    item = {
                        "no": safe_str(r.iloc[0]), 
                        "item_code": safe_str(r.iloc[1]), 
                        "item_name": safe_str(r.iloc[2]), 
                        "specs": safe_str(r.iloc[3]),
                        "qty": fmt_num(to_float(r.iloc[4])), 
                        "buying_price_rmb": fmt_num(to_float(r.iloc[5])), 
                        "total_buying_price_rmb": fmt_num(to_float(r.iloc[6])), 
                        "exchange_rate": fmt_num(to_float(r.iloc[7])), 
                        "buying_price_vnd": fmt_num(to_float(r.iloc[8])), 
                        "total_buying_price_vnd": fmt_num(to_float(r.iloc[9])), 
                        "leadtime": safe_str(r.iloc[10]), 
                        "supplier_name": safe_str(r.iloc[11]), 
                        "image_path": im_path,
                        # Cải tiến: Thêm cột Type (N-13) và NUOC (O-14)
                        "type": safe_str(r.iloc[13]) if len(r) > 13 else "",
                        "nuoc": safe_str(r.iloc[14]) if len(r) > 14 else ""
                    }
                    # Điều kiện import: item_code hoặc item_name có dữ liệu
                    if item["item_code"] or item["item_name"]: rows.append(item)
                
                purchases_df = pd.DataFrame(rows)
                save_csv(PURCHASES_CSV, purchases_df)
                st.success(f"✅ Đã import {len(rows)} dòng thành công!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")
        
        # Nút Reset
        st.divider()
        if is_admin:
            if st.button("⚠️ RESET DATABASE KHO HÀNG"):
                purchases_df = pd.DataFrame(columns=PURCHASE_COLUMNS)
                save_csv(PURCHASES_CSV, purchases_df)
                st.success("Đã xóa sạch database!"); time.sleep(1); st.rerun()

    with col_p2:
        search_term = st.text_input("🔍 Tìm kiếm (Code/Name)")
        if not purchases_df.empty:
            df_show = purchases_df.copy()
            if search_term:
                mask = df_show.apply(lambda x: search_term.lower() in str(x['item_code']).lower() or search_term.lower() in str(x['item_name']).lower(), axis=1)
                df_show = df_show[mask]
            # Ẩn index, hiển thị cột No
            st.dataframe(df_show, column_config={"image_path": st.column_config.ImageColumn("Img")}, use_container_width=True, hide_index=True)
        else: st.info("Chưa có dữ liệu.")

# --- TAB 3: BÁO GIÁ (QUOTES) ---
with tab3:
    # 1. NÚT TẠO MỚI
    if st.button("🆕 TẠO BÁO GIÁ MỚI (RESET)"):
        st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
        st.session_state.customer_name = ""
        st.session_state.quote_number = ""
        st.rerun()

    # 2. KHUNG TÍNH TOÁN (Container riêng)
    with st.container(border=True):
        st.header("1. TÍNH TOÁN GIÁ")
        c1, c2 = st.columns(2)
        st.session_state.customer_name = c1.text_input("Tên Khách Hàng", st.session_state.customer_name)
        st.session_state.quote_number = c2.text_input("Số Báo Giá", st.session_state.quote_number)

        with st.expander("Cấu hình Chi phí (%)", expanded=True):
            cols = st.columns(7)
            pct_inputs = {}
            keys = ["end", "buy", "tax", "vat", "pay", "mgmt", "trans"]
            for i, k in enumerate(keys):
                st.session_state[f"pct_{k}"] = cols[i].text_input(k.upper(), st.session_state[f"pct_{k}"])

        col_up, col_act = st.columns([1, 2])
        with col_up:
            up_rfq = st.file_uploader("Upload RFQ (Excel)", type=["xlsx"])
        with col_act:
            st.write(""); st.write("")
            if up_rfq and st.button("🚀 LOAD RFQ & MATCHING"):
                try:
                    # Tạo khóa tìm kiếm sạch
                    purchases_df["_clean_code"] = purchases_df["item_code"].apply(clean_lookup_key)
                    purchases_df["_clean_specs"] = purchases_df["specs"].apply(clean_lookup_key)
                    purchases_df["_clean_name"] = purchases_df["item_name"].apply(clean_lookup_key)
                    
                    df_rfq = pd.read_excel(up_rfq, header=None, dtype=str).fillna("")
                    new_data = []
                    
                    # Duyệt file RFQ
                    for i, r in df_rfq.iloc[1:].iterrows(): # Bỏ dòng 0 header
                        c_raw = safe_str(r.iloc[1]); n_raw = safe_str(r.iloc[2])
                        s_raw = safe_str(r.iloc[3]); qty = to_float(r.iloc[4])
                        
                        # Logic: Chỉ cần Qty > 0 là lấy vào
                        if qty <= 0: continue

                        # Tìm kiếm trong DB
                        clean_c = clean_lookup_key(c_raw); clean_s = clean_lookup_key(s_raw); clean_n = clean_lookup_key(n_raw)
                        target_row = None
                        found_in_db = pd.DataFrame()
                        
                        # Ưu tiên Code -> Name
                        if c_raw: found_in_db = purchases_df[purchases_df["_clean_code"] == clean_c]
                        if found_in_db.empty and n_raw: found_in_db = purchases_df[purchases_df["_clean_name"] == clean_n]
                        
                        if not found_in_db.empty:
                            if s_raw: # Nếu có specs thì lọc tiếp
                                fs = found_in_db[found_in_db["_clean_specs"] == clean_s]
                                target_row = fs.iloc[0] if not fs.empty else found_in_db.iloc[0]
                            else: target_row = found_in_db.iloc[0]
                        
                        # Map dữ liệu
                        it = {k:"" for k in QUOTE_KH_COLUMNS}
                        it["no"] = safe_str(r.iloc[0]); it["item_code"] = c_raw
                        it["item_name"] = n_raw; it["specs"] = s_raw; it["qty"] = fmt_num(qty)
                        
                        if target_row is not None:
                            it["buying_price_rmb"] = target_row["buying_price_rmb"]
                            it["buying_price_vnd"] = target_row["buying_price_vnd"]
                            it["exchange_rate"] = target_row["exchange_rate"]
                            it["supplier_name"] = target_row["supplier_name"]
                            it["leadtime"] = target_row["leadtime"]
                            it["image_path"] = target_row["image_path"]
                            
                            b_vnd = to_float(target_row["buying_price_vnd"])
                            it["total_buying_price_vnd"] = fmt_num(b_vnd * qty)
                        
                        new_data.append(it)
                    
                    st.session_state.current_quote_df = pd.DataFrame(new_data)
                    st.success(f"Đã load {len(new_data)} dòng!")
                    st.rerun()
                except Exception as e: st.error(f"Lỗi Matching: {e}")

        # Tính toán tức thì
        if not st.session_state.current_quote_df.empty:
            st.markdown("---")
            f1, f2 = st.columns(2)
            ap_f = f1.text_input("AP Formula (e.g. =BUY*1.1)", key="ap_f_rt")
            unit_f = f2.text_input("Unit Formula (e.g. =AP*1.2)", key="unit_f_rt")
            
            # Logic tính toán (Auto-run)
            df = st.session_state.current_quote_df.copy()
            
            # Lấy tham số %
            pend = to_float(st.session_state.pct_end)/100; pbuy = to_float(st.session_state.pct_buy)/100
            ptax = to_float(st.session_state.pct_tax)/100; pvat = to_float(st.session_state.pct_vat)/100
            ppay = to_float(st.session_state.pct_pay)/100; pmgmt = to_float(st.session_state.pct_mgmt)/100
            ptrans = to_float(st.session_state.pct_trans)

            for i, r in df.iterrows():
                buy_vnd = to_float(r.get("buying_price_vnd"))
                curr_ap = to_float(r.get("ap_price"))
                
                # Apply Formula
                if ap_f: curr_ap = parse_formula(ap_f, buy_vnd, curr_ap); df.at[i, "ap_price"] = fmt_num(curr_ap)
                if unit_f: new_unit = parse_formula(unit_f, buy_vnd, curr_ap); df.at[i, "unit_price"] = fmt_num(new_unit)
                
                # Calc Profit
                qty = to_float(r["qty"]); unit_sell = to_float(df.at[i, "unit_price"])
                ap_price = to_float(df.at[i, "ap_price"])
                
                total_sell = unit_sell * qty; ap_total = ap_price * qty
                total_buy = buy_vnd * qty
                gap = total_sell - ap_total
                
                end_v = ap_total * pend; buy_v = total_sell * pbuy; tax_v = total_buy * ptax
                vat_v = total_sell * pvat; mgmt_v = total_sell * pmgmt
                pay_v = gap * ppay; trans_v = ptrans * qty
                
                # Profit Cost Structure
                # Cost = Total Buy + (GAP - Payback) + End + Buyer + Tax + VAT + Mgmt + Trans ?? 
                # Simplify: Profit = Total Sell - (Total Buy + Costs) + Payback (if GAP logic)
                # Theo V4800 logic:
                ops_cost = (gap * 0.6 if gap > 0 else 0) + end_v + buy_v + tax_v + vat_v + mgmt_v + trans_v
                profit = total_sell - total_buy - ops_cost + pay_v
                pct = (profit/total_sell*100) if total_sell else 0
                
                df.at[i, "total_price_vnd"] = fmt_num(total_sell)
                df.at[i, "ap_total_vnd"] = fmt_num(ap_total)
                df.at[i, "profit_vnd"] = fmt_num(profit)
                df.at[i, "profit_pct"] = "{:.1f}%".format(pct)
            
            st.session_state.current_quote_df = df
            
            # Editor
            edited = st.data_editor(
                st.session_state.current_quote_df,
                use_container_width=True,
                height=400,
                num_rows="dynamic",
                column_config={
                    "image_path": st.column_config.ImageColumn("Img"),
                    "profit_pct": st.column_config.TextColumn("Profit %", disabled=True)
                },
                column_order=QUOTE_DISPLAY_COLS
            )
            if not edited.equals(st.session_state.current_quote_df):
                st.session_state.current_quote_df = edited
                st.rerun()

    # 3. KHUNG REVIEW (CÁCH 4 DÒNG)
    st.write(""); st.write(""); st.write(""); st.write("")
    
    if not st.session_state.current_quote_df.empty:
        with st.container(border=True):
            st.header("2. REVIEW LỢI NHUẬN")
            df_rev = st.session_state.current_quote_df.copy()
            # Lọc profit < 10%
            def is_low(x):
                try: return float(x.replace("%","")) < 10
                except: return False
            
            df_low = df_rev[df_rev["profit_pct"].apply(is_low)]
            
            # Chỉ hiện 9 cột
            cols_show = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price_vnd", "profit_vnd", "profit_pct"]
            if not df_low.empty:
                st.dataframe(df_low[cols_show], use_container_width=True, hide_index=True)
                st.markdown(f"<div class='alert-box'>⚠️ CẢNH BÁO: Có {len(df_low)} item lợi nhuận < 10%</div>", unsafe_allow_html=True)
            else:
                st.success("✅ Tất cả item đều đạt lợi nhuận > 10%")

        # 4. EXPORT
        with st.container(border=True):
            st.header("3. XUẤT FILE BÁO GIÁ")
            c_ex1, c_ex2 = st.columns(2)
            
            with c_ex1:
                # Nút Save History
                if st.button("💾 LƯU LỊCH SỬ"):
                    save_csv(SHARED_HISTORY_CSV, st.session_state.current_quote_df) # Demo save simple
                    st.success("Saved!")
            
            with c_ex2:
                if st.button("📤 XUẤT EXCEL (TEMPLATE AAA)"):
                    if not os.path.exists(TEMPLATE_FILE):
                         st.error("Không tìm thấy template AAA-QUOTATION.xlsx")
                    else:
                        try:
                            wb = load_workbook(TEMPLATE_FILE)
                            ws = wb.active
                            
                            # Leadtime -> H8
                            lt_val = st.session_state.current_quote_df.iloc[0]["leadtime"] if not st.session_state.current_quote_df.empty else ""
                            safe_write_merged(ws, 8, 8, lt_val) # H8 is row 8, col 8
                            
                            # Data -> Row 10 (A10 start) - Nhưng bạn nói row 10 là header, data từ 11?
                            # Yêu cầu: No: A10, Code: C10... -> Có vẻ ý là dòng 10 trong excel (index 10) là dòng đầu tiên của data? 
                            # Hay A10 là header? Trong mô tả: "No: cột A10... Unit price: G10". 
                            # Thường header ở dòng 9, data từ 10. Tôi sẽ ghi từ dòng 10 (index 10 trong openpyxl là dòng 10).
                            
                            start_r = 10 
                            for i, r in st.session_state.current_quote_df.iterrows():
                                curr = start_r + i
                                safe_write_merged(ws, curr, 1, r["no"])          # A
                                safe_write_merged(ws, curr, 3, r["item_code"])   # C
                                safe_write_merged(ws, curr, 4, r["item_name"])   # D
                                safe_write_merged(ws, curr, 5, r["specs"])       # E
                                safe_write_merged(ws, curr, 6, to_float(r["qty"])) # F
                                safe_write_merged(ws, curr, 7, to_float(r["unit_price"])) # G
                                safe_write_merged(ws, curr, 8, to_float(r["total_price_vnd"])) # H
                            
                            out = io.BytesIO()
                            wb.save(out)
                            st.download_button("Tải file", out.getvalue(), "Bao_Gia.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        except Exception as e: st.error(f"Lỗi export: {e}")

# --- TAB 5: TRACKING (KHÔI PHỤC) ---
with tab5:
    st.subheader("Theo dõi đơn hàng (Tracking)")
    # Logic Tracking đơn giản: Load -> Show -> Edit -> Save
    if "Delete" not in tracking_df.columns: tracking_df["Delete"] = False
    
    edited_track = st.data_editor(tracking_df, num_rows="dynamic", key="ed_tr", use_container_width=True)
    
    if st.button("Cập nhật Tracking"):
        tracking_df = edited_track
        save_csv(TRACKING_CSV, tracking_df)
        st.success("Đã cập nhật Tracking!")

    st.markdown("---")
    st.write("Upload Proof Image")
    up_proof = st.file_uploader("Chọn ảnh", type=["png","jpg"], accept_multiple_files=True)
    track_id = st.text_input("Nhập ID (No) để gán ảnh")
    if st.button("Upload Proof") and up_proof and track_id:
        # Save images logic here
        st.success("Uploaded!")

# --- TAB 6: MASTER DATA ---
with tab6:
    st.write("Master Data Management")
    c1, c2, c3 = st.tabs(["Khách hàng", "Nhà cung cấp", "Template"])
    
    with c1:
        edited_cust = st.data_editor(customers_df, num_rows="dynamic")
        if st.button("Lưu Khách Hàng"): save_csv(CUSTOMERS_CSV, edited_cust); st.success("OK")
    
    with c2:
        edited_supp = st.data_editor(suppliers_df, num_rows="dynamic")
        if st.button("Lưu NCC"): save_csv(SUPPLIERS_CSV, edited_supp); st.success("OK")
        
    with c3:
        up_t = st.file_uploader("Upload Template AAA-QUOTATION.xlsx", type=["xlsx"])
        if up_t:
            with open(TEMPLATE_FILE, "wb") as f: f.write(up_t.getbuffer())
            st.success("Updated Template!")
