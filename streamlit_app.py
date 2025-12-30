import streamlit as st
import pandas as pd
import warnings
import re
import json
import ast
import io
from datetime import datetime, timedelta
from copy import copy

# --- THƯ VIỆN ONLINE ---
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =============================================================================
# 1. SETUP & CONFIGURATION
# =============================================================================
st.set_page_config(page_title="SGS CRM V4800 - Cloud Edition", layout="wide", page_icon="🚀")

# Tắt cảnh báo
warnings.filterwarnings("ignore", category=UserWarning)

# --- KHỞI TẠO KẾT NỐI (Blackbox Wrapper) ---
def init_connection():
    # 1. Supabase
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        supabase: Client = create_client(url, key)
    except Exception:
        st.error("Chưa cấu hình Supabase secrets.")
        return None, None

    # 2. Google Drive (OAuth2 Refresh Token)
    try:
        creds = Credentials(
            None, # No access token initially
            refresh_token=st.secrets["google"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets["google"]["client_id"],
            client_secret=st.secrets["google"]["client_secret"]
        )
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception:
        st.warning("Chưa cấu hình Google Drive secrets. Tính năng ảnh/file sẽ bị hạn chế.")
        drive_service = None

    return supabase, drive_service

supabase, drive_service = init_connection()

# =============================================================================
# 2. GLOBAL FUNCTIONS (COPIED 100% FROM ORIGINAL - BLACKBOX)
# =============================================================================
# Các hàm này được coi là thư viện lõi, giữ nguyên logic xử lý.

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

def clean_string_absolute(s): return clean_lookup_key(s)

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

# =============================================================================
# 3. ONLINE DATA HANDLERS (REPLACEMENT FOR CSV IO)
# =============================================================================

TABLE_MAP = {
    "customers_df": "crm_customers",
    "suppliers_df": "crm_suppliers",
    "purchases_df": "crm_purchases",
    "sales_history_df": "crm_sales_history",
    "tracking_df": "crm_order_tracking",
    "payment_df": "crm_payment_tracking",
    "paid_history_df": "crm_paid_history",
    "db_supplier_orders": "db_supplier_orders",
    "db_customer_orders": "db_customer_orders"
}

# Định nghĩa cột giống file cũ
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person", "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate", "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer", "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd", "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
HISTORY_COLS = ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "total_cost", "profit", "supplier", "status", "delivery_date", "po_number"]


@st.cache_data(ttl=60)
def load_data_from_supabase(table_name, cols):
    """Thay thế load_csv"""
    if not supabase: return pd.DataFrame(columns=cols)
    try:
        response = supabase.table(table_name).select("*").execute()
        df = pd.DataFrame(response.data)
        
        # Đảm bảo đủ cột
        for c in cols:
            if c not in df.columns: df[c] = ""
            
        # Clean data (safe_str)
        for c in df.columns:
            df[c] = df[c].apply(safe_str)
            
        return df[cols]
    except Exception as e:
        st.error(f"Lỗi tải data {table_name}: {e}")
        return pd.DataFrame(columns=cols)

def save_data_to_supabase(table_name, df, key_col="id"):
    """Thay thế save_csv. Lưu ý: Supabase cần có cột ID unique hoặc Logic Upsert"""
    if not supabase: return
    try:
        # Chuyển đổi DF sang list of dicts
        data = df.to_dict(orient='records')
        
        # Với demo đơn giản, ta xóa hết và insert lại (Warning: Không tối ưu cho Big Data)
        # Thực tế nên dùng Upsert. Ở đây giả lập hành vi 'overwrite file CSV'
        supabase.table(table_name).delete().neq("no", "THIS_SHOULD_DELETE_ALL").execute() # Hacky way to truncate if needed or use proper truncation
        # Cách an toàn hơn cho demo: Xóa các dòng cũ và insert mới
        # Để đơn giản cho script convert này, ta giả định logic Insert.
        
        # Lưu ý: Supabase giới hạn kích thước insert.
        batch_size = 100
        for i in range(0, len(data), batch_size):
            batch = data[i:i+batch_size]
            supabase.table(table_name).upsert(batch).execute()
            
        st.toast(f"Đã lưu dữ liệu vào {table_name}", icon="💾")
    except Exception as e:
        st.error(f"Lỗi lưu data {table_name}: {e}")

def upload_file_to_drive(file_obj, filename, folder_id):
    """Thay thế lưu file ảnh local"""
    if not drive_service: return None
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        return file.get('webContentLink')
    except Exception as e:
        st.error(f"Upload Drive lỗi: {e}")
        return None

# =============================================================================
# 4. APP LOGIC & SESSION STATE
# =============================================================================

# Khởi tạo Session State (giống như __init__ trong class)
if 'data_loaded' not in st.session_state:
    st.session_state['data_loaded'] = False

def load_all_data():
    if not st.session_state['data_loaded']:
        with st.spinner('Đang tải dữ liệu từ Cloud...'):
            st.session_state['purchases_df'] = load_data_from_supabase(TABLE_MAP['purchases_df'], PURCHASE_COLUMNS)
            st.session_state['customers_df'] = load_data_from_supabase(TABLE_MAP['customers_df'], MASTER_COLUMNS)
            st.session_state['suppliers_df'] = load_data_from_supabase(TABLE_MAP['suppliers_df'], MASTER_COLUMNS)
            st.session_state['sales_history_df'] = load_data_from_supabase(TABLE_MAP['sales_history_df'], HISTORY_COLS)
            st.session_state['tracking_df'] = load_data_from_supabase(TABLE_MAP['tracking_df'], TRACKING_COLS)
            st.session_state['payment_df'] = load_data_from_supabase(TABLE_MAP['payment_df'], PAYMENT_COLS)
            st.session_state['paid_history_df'] = load_data_from_supabase(TABLE_MAP['paid_history_df'], PAYMENT_COLS)
            st.session_state['db_supplier_orders'] = load_data_from_supabase(TABLE_MAP['db_supplier_orders'], SUPPLIER_ORDER_COLS)
            st.session_state['db_customer_orders'] = load_data_from_supabase(TABLE_MAP['db_customer_orders'], CUSTOMER_ORDER_COLS)
            
            # Temp DataFrames (Memory only)
            st.session_state['current_quote_df'] = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
            st.session_state['temp_supp_order_df'] = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
            st.session_state['temp_cust_order_df'] = pd.DataFrame(columns=CUSTOMER_ORDER_COLS)
            
            # Pre-clean Keys
            df = st.session_state['purchases_df']
            df["_clean_code"] = df["item_code"].apply(clean_lookup_key)
            df["_clean_specs"] = df["specs"].apply(clean_lookup_key)
            df["_clean_name"] = df["item_name"].apply(clean_lookup_key)
            st.session_state['purchases_df'] = df

            st.session_state['data_loaded'] = True

load_all_data()

# =============================================================================
# 5. UI COMPONENTS (Tương ứng các Tabs cũ)
# =============================================================================

def ui_dashboard():
    st.header("📊 Tổng quan Dashboard")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 CẬP NHẬT DATA"):
            st.session_state['data_loaded'] = False
            st.rerun()

    # Calculation Logic (Copied logic)
    try:
        rev = st.session_state['db_customer_orders']['total_price'].apply(to_float).sum()
        profit = st.session_state['sales_history_df']['profit'].apply(to_float).sum()
        cost = rev - profit
        paid_count = len(st.session_state['paid_history_df'])
        unpaid_count = len(st.session_state['payment_df'][st.session_state['payment_df']['status'] != "Đã thanh toán"])
        
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("TỔNG DOANH THU", fmt_num(rev))
        c2.metric("TỔNG CHI PHÍ", fmt_num(cost))
        c3.metric("LỢI NHUẬN", fmt_num(profit))
        c4.metric("PO ĐÃ THANH TOÁN", paid_count)
        c5.metric("PO CHƯA THANH TOÁN", unpaid_count, delta_color="inverse")
        
    except Exception as e:
        st.error(f"Lỗi tính toán Dashboard: {e}")

def ui_supplier_quote():
    st.header("💰 Báo giá NCC (Database Giá)")
    
    col_act, col_search = st.columns([2, 1])
    with col_act:
        if st.button("💾 Lưu thay đổi xuống Cloud (DB)", type="primary"):
            save_data_to_supabase(TABLE_MAP['purchases_df'], st.session_state['purchases_df'])
            
    # Thay vì Treeview, dùng Data Editor
    edited_df = st.data_editor(
        st.session_state['purchases_df'],
        column_config={
            "image_path": st.column_config.LinkColumn("Image Link"),
            "qty": st.column_config.NumberColumn("Qty"),
            "buying_price_rmb": st.column_config.NumberColumn("Price RMB")
        },
        num_rows="dynamic",
        key="editor_purchases"
    )
    
    # Logic update calculation when edited (Simplified version of on_purchase_double_click)
    if not edited_df.equals(st.session_state['purchases_df']):
        # Recalculate logic
        for idx, row in edited_df.iterrows():
            q = to_float(row.get("qty", 0))
            p_rmb = to_float(row.get("buying_price_rmb", 0))
            ex = to_float(row.get("exchange_rate", 0))
            
            edited_df.at[idx, "total_buying_price_rmb"] = fmt_num(q * p_rmb)
            edited_df.at[idx, "buying_price_vnd"] = fmt_num(p_rmb * ex)
            edited_df.at[idx, "total_buying_price_vnd"] = fmt_num(q * p_rmb * ex)
            
            # Clean keys
            edited_df.at[idx, "_clean_code"] = clean_lookup_key(row.get("item_code"))
            edited_df.at[idx, "_clean_specs"] = clean_lookup_key(row.get("specs"))
            edited_df.at[idx, "_clean_name"] = clean_lookup_key(row.get("item_name"))
            
        st.session_state['purchases_df'] = edited_df
        # Tự động rerun để refresh view nếu cần, hoặc chờ nút Save

def ui_customer_quote():
    st.header("📝 Báo giá Khách Hàng")
    tab1, tab2 = st.tabs(["Tạo Báo Giá", "Tra Cứu Lịch Sử"])
    
    with tab1:
        # 1. Thông tin chung
        c1, c2, c3 = st.columns(3)
        cust_list = st.session_state['customers_df']["short_name"].tolist()
        sel_cust = c1.selectbox("Khách hàng", cust_list)
        quote_name = c2.text_input("Tên Báo Giá")
        
        if c3.button("✨ Reset Báo Giá"):
             st.session_state['current_quote_df'] = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
             st.rerun()

        # 2. Tham số
        with st.expander("Tham số chi phí (%)"):
            cc1, cc2, cc3, cc4 = st.columns(4)
            p_end = cc1.number_input("End User %", value=0.0)
            p_buy = cc2.number_input("Buyer %", value=0.0)
            p_tax = cc3.number_input("Tax %", value=0.0)
            p_vat = cc4.number_input("VAT %", value=0.0)
            # ... thêm các biến khác nếu cần
        
        # 3. Main Editor
        st.subheader("Chi tiết Báo Giá")
        
        # Helper recalculate (Ported logic)
        def recalculate_quote():
            df = st.session_state['current_quote_df']
            for i, r in df.iterrows():
                qty = to_float(r["qty"]); buy_vnd = to_float(r["buying_price_vnd"]); t_buy = qty * buy_vnd
                ap = to_float(r["ap_price"]); unit = to_float(r["unit_price"])
                ap_tot = ap * qty; total = unit * qty; gap = total - ap_tot
                
                # Chi phí đơn giản hóa cho demo (Copy full logic in real impl)
                tax = t_buy * (p_tax/100)
                prof = gap - tax # Simplified logic form original
                
                df.at[i, "total_price_vnd"] = fmt_num(total)
                df.at[i, "profit_vnd"] = fmt_num(prof)
            st.session_state['current_quote_df'] = df

        edited_quote = st.data_editor(
            st.session_state['current_quote_df'],
            num_rows="dynamic",
            column_config={
                "qty": st.column_config.NumberColumn("Qty"),
                "buying_price_vnd": st.column_config.NumberColumn("Buy VND"),
                "ap_price": st.column_config.NumberColumn("AP Price"),
                "unit_price": st.column_config.NumberColumn("Unit Price")
            },
            key="editor_quote"
        )
        
        if st.button("🔄 Tính Toán Lợi Nhuận"):
            st.session_state['current_quote_df'] = edited_quote
            recalculate_quote()
            st.rerun()

        if st.button("💾 Lưu Lịch Sử (Sales History)"):
            # Logic Save History
            new_hist = []
            d = datetime.now().strftime("%d/%m/%Y")
            for idx, r in edited_quote.iterrows():
                new_hist.append({
                    "date":d, "quote_no":quote_name, "customer":sel_cust,
                    "item_code":r["item_code"], "item_name":r["item_name"],
                    "qty":r["qty"], "total_revenue":r["total_price_vnd"],
                    "profit":r["profit_vnd"], "supplier":r["supplier_name"],
                    "status":"Pending"
                })
            new_df = pd.DataFrame(new_hist)
            # Append to session state
            st.session_state['sales_history_df'] = pd.concat([st.session_state['sales_history_df'], new_df], ignore_index=True)
            # Save to Cloud
            save_data_to_supabase(TABLE_MAP['sales_history_df'], st.session_state['sales_history_df'])
    
    with tab2:
        st.subheader("Tra cứu lịch sử")
        kw = st.text_input("Từ khóa tìm kiếm")
        if kw:
            df_hist = st.session_state['sales_history_df']
            # Simple search logic
            mask = df_hist.apply(lambda x: x.astype(str).str.contains(kw, case=False).any(), axis=1)
            st.dataframe(df_hist[mask])

def ui_orders():
    st.header("📦 Quản lý Đơn Hàng")
    tab_ncc, tab_kh = st.tabs(["1. Đặt Hàng NCC", "2. PO Khách Hàng"])
    
    with tab_ncc:
        c1, c2 = st.columns(2)
        po_ncc = c1.text_input("Số PO NCC")
        supp_name = c2.selectbox("Nhà Cung Cấp", st.session_state['suppliers_df']["short_name"].tolist())
        
        st.subheader("Danh sách mặt hàng đặt")
        edited_ncc = st.data_editor(st.session_state['temp_supp_order_df'], num_rows="dynamic", key="order_ncc_edit")
        
        if st.button("🚀 Xác nhận Đặt Hàng (Tạo Tracking)"):
            # Logic Action Confirm
            edited_ncc["po_number"] = po_ncc
            edited_ncc["supplier"] = supp_name
            edited_ncc["order_date"] = datetime.now().strftime("%d/%m/%Y")
            
            # Save to DB Orders
            st.session_state['db_supplier_orders'] = pd.concat([st.session_state['db_supplier_orders'], edited_ncc], ignore_index=True)
            save_data_to_supabase(TABLE_MAP['db_supplier_orders'], st.session_state['db_supplier_orders'])
            
            # Create Tracking
            new_tracks = []
            for _, r in edited_ncc.iterrows():
                new_tracks.append({
                    "po_no": po_ncc, "partner": supp_name, "status": "Đã đặt hàng",
                    "order_type": "NCC", "last_update": datetime.now().strftime("%d/%m/%Y"), "finished": "0"
                })
            # Add unique Logic in real app to avoid dupes per item, here simplify per PO
            if len(new_tracks) > 0:
                track_df = pd.DataFrame([new_tracks[0]]) # Track theo PO
                st.session_state['tracking_df'] = pd.concat([st.session_state['tracking_df'], track_df], ignore_index=True)
                save_data_to_supabase(TABLE_MAP['tracking_df'], st.session_state['tracking_df'])
                
            st.success("Đã tạo đơn hàng NCC!")
            st.session_state['temp_supp_order_df'] = pd.DataFrame(columns=SUPPLIER_ORDER_COLS)
            st.rerun()

    with tab_kh:
        st.info("Logic tương tự tab NCC (Map các cột PO Khách Hàng)")
        # Implement similar to above for Customer Orders

def ui_tracking_payment():
    st.header("🚚 Theo dõi & Thanh toán")
    
    # 1. Tracking View
    st.subheader("Đang theo dõi (Tracking)")
    track_df = st.session_state['tracking_df']
    active_track = track_df[track_df['finished']=="0"]
    
    edited_track = st.data_editor(
        active_track, 
        column_config={
            "status": st.column_config.SelectboxColumn("Trạng thái", options=["Đã đặt hàng", "Hàng về", "Đã giao hàng"]),
            "proof_image": st.column_config.LinkColumn("Ảnh Proof")
        },
        key="track_editor"
    )
    
    # Upload Image Logic
    uploaded_file = st.file_uploader("Upload ảnh Proof cho dòng đang chọn")
    if uploaded_file and drive_service:
        # Trong Streamlit, việc chọn dòng khó hơn Tkinter.
        # Ta dùng Selectbox để chọn PO cần up ảnh
        po_to_up = st.selectbox("Chọn PO để gán ảnh", active_track["po_no"].unique())
        if st.button("Upload lên Drive"):
            folder_id = st.secrets["google"]["drive_folder_id"]
            link = upload_file_to_drive(uploaded_file, f"proof_{po_to_up}.png", folder_id)
            if link:
                # Update DB
                idx = track_df[track_df["po_no"] == po_to_up].index
                track_df.loc[idx, "proof_image"] = link
                st.session_state['tracking_df'] = track_df
                save_data_to_supabase(TABLE_MAP['tracking_df'], track_df)
                st.success("Upload thành công!")

    if st.button("💾 Cập nhật Trạng Thái Tracking"):
        # Update logic: If status == "Đã giao hàng" -> Move to Payment
        # Merge edited back to main df
        st.session_state['tracking_df'].update(edited_track)
        save_data_to_supabase(TABLE_MAP['tracking_df'], st.session_state['tracking_df'])
        st.success("Đã lưu Tracking")

    st.divider()
    
    # 2. Payment View
    st.subheader("Thanh Toán")
    pay_df = st.session_state['payment_df']
    unpaid = pay_df[pay_df["status"] != "Đã thanh toán"]
    
    st.dataframe(unpaid)
    
    po_pay = st.selectbox("Chọn PO xác nhận thanh toán", unpaid["po_no"].unique() if not unpaid.empty else [])
    if st.button("Xác nhận Đã Thanh Toán"):
        if po_pay:
            mask = st.session_state['payment_df']["po_no"] == po_pay
            st.session_state['payment_df'].loc[mask, "status"] = "Đã thanh toán"
            st.session_state['payment_df'].loc[mask, "paid_date"] = datetime.now().strftime("%d/%m/%Y")
            
            # Move to Paid History
            paid_row = st.session_state['payment_df'][mask]
            st.session_state['paid_history_df'] = pd.concat([st.session_state['paid_history_df'], paid_row], ignore_index=True)
            
            save_data_to_supabase(TABLE_MAP['payment_df'], st.session_state['payment_df'])
            save_data_to_supabase(TABLE_MAP['paid_history_df'], st.session_state['paid_history_df'])
            st.success(f"PO {po_pay} đã thanh toán!")
            st.rerun()

def ui_master_data():
    st.header("⚙️ Master Data")
    tab1, tab2 = st.tabs(["Khách hàng", "Nhà cung cấp"])
    
    with tab1:
        st.data_editor(st.session_state['customers_df'], num_rows="dynamic", key="edit_cust")
        if st.button("Lưu Khách Hàng"):
            save_data_to_supabase(TABLE_MAP['customers_df'], st.session_state['customers_df'])
            
    with tab2:
        st.data_editor(st.session_state['suppliers_df'], num_rows="dynamic", key="edit_supp")
        if st.button("Lưu NCC"):
            save_data_to_supabase(TABLE_MAP['suppliers_df'], st.session_state['suppliers_df'])

# =============================================================================
# 6. MAIN APP LAYOUT
# =============================================================================

menu = ["Dashboard", "Báo giá NCC", "Báo giá KH", "Đơn hàng", "Tracking & Payment", "Master Data"]
choice = st.sidebar.selectbox("Menu", menu)

if choice == "Dashboard":
    ui_dashboard()
elif choice == "Báo giá NCC":
    ui_supplier_quote()
elif choice == "Báo giá KH":
    ui_customer_quote()
elif choice == "Đơn hàng":
    ui_orders()
elif choice == "Tracking & Payment":
    ui_tracking_payment()
elif choice == "Master Data":
    ui_master_data()
