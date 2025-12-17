import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection
import re
import io
import time

# =============================================================================
# 1. CẤU HÌNH HỆ THỐNG & HELPER FUNCTIONS (LOGIC GỐC)
# =============================================================================

st.set_page_config(page_title="SGS CRM Online", layout="wide", page_icon="🏢")

# --- GLOBAL FUNCTIONS (GIỮ NGUYÊN TỪ CODE CŨ) ---
def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() == 'nan': return ""
    return s

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
        if f.is_integer(): s_str = str(int(f))
    except: pass
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

# =============================================================================
# 2. KẾT NỐI DATA (GOOGLE SHEETS)
# =============================================================================

conn = st.connection("gsheets", type=GSheetsConnection)

# Mapping tên Sheet trên Google Sheet (Bạn phải tạo file sheet có các tab tên y hệt thế này)
SHEET_MAP = {
    "Purchases": "crm_purchases",      # DB Giá NCC
    "Customers": "crm_customers",      # Danh sách Khách
    "Suppliers": "crm_suppliers",      # Danh sách NCC
    "Orders": "crm_orders",            # Đơn hàng
    "History": "crm_sales_history",    # Lịch sử báo giá
    "Tracking": "crm_tracking",        # Theo dõi vận đơn
    "Payment": "crm_payment"           # Theo dõi thanh toán
}

# Hàm load data có Cache (TTL 10s để chịu tải nhiều user)
@st.cache_data(ttl=10)
def load_data(sheet_key):
    try:
        # Đọc dữ liệu, convert tất cả sang string để tránh lỗi hiển thị số
        df = conn.read(worksheet=SHEET_MAP[sheet_key])
        return df.fillna("")
    except Exception as e:
        # Nếu chưa có sheet, trả về DF rỗng
        return pd.DataFrame()

# Hàm lưu data (Xóa cache sau khi lưu)
def save_data(sheet_key, df):
    try:
        conn.update(worksheet=SHEET_MAP[sheet_key], data=df)
        st.cache_data.clear()
        st.toast(f"Đã lưu dữ liệu vào {SHEET_MAP[sheet_key]} thành công!", icon="✅")
    except Exception as e:
        st.error(f"Lỗi lưu dữ liệu: {e}")

# =============================================================================
# 3. LOGIC TÍNH TOÁN CORE (RECALCULATE)
# =============================================================================
def recalculate_logic(df, params):
    # Lấy tham số toàn cục
    pend = to_float(params.get("end", 0))/100
    pbuy = to_float(params.get("buy", 0))/100
    ptax = to_float(params.get("tax", 0))/100
    pvat = to_float(params.get("vat", 0))/100
    ppay = to_float(params.get("pay", 0))/100
    pmgmt = to_float(params.get("mgmt", 0))/100
    
    use_global_trans = to_float(params.get("trans", -1)) if params.get("trans", "") != "" else -1

    # Duyệt từng dòng để tính toán
    for i, r in df.iterrows():
        qty = to_float(r.get("qty", 0))
        buy_vnd = to_float(r.get("buying_price_vnd", 0))
        ap = to_float(r.get("ap_price", 0))
        unit = to_float(r.get("unit_price", 0))

        # Transportation Logic
        trans_val = to_float(r.get("transportation", 0))
        if use_global_trans >= 0: 
            trans_val = use_global_trans
        
        # Các công thức cốt lõi (Giữ nguyên 100%)
        t_buy = qty * buy_vnd
        ap_tot = ap * qty
        total = unit * qty
        gap = total - ap_tot
        
        tax = t_buy * ptax
        buyer = total * pbuy
        vat = total * pvat
        mgmt = total * pmgmt
        end = ap_tot * pend
        total_trans = trans_val * qty
        pay = gap * ppay
        
        cost = t_buy + gap + end + buyer + tax + vat + mgmt + total_trans
        prof = total - cost + pay
        pct = (prof/total*100) if total else 0
        
        # Gán ngược lại vào DF
        df.at[i, "transportation"] = trans_val
        df.at[i, "total_buying_price_vnd"] = t_buy
        df.at[i, "ap_total_vnd"] = ap_tot
        df.at[i, "total_price_vnd"] = total
        df.at[i, "gap"] = gap
        df.at[i, "end_user_val"] = end
        df.at[i, "buyer_val"] = buyer
        df.at[i, "import_tax_val"] = tax
        df.at[i, "vat_val"] = vat
        df.at[i, "mgmt_fee"] = mgmt
        df.at[i, "payback_val"] = pay
        df.at[i, "profit_vnd"] = prof
        df.at[i, "profit_pct"] = pct

    return df

# =============================================================================
# 4. GIAO DIỆN CHÍNH (UI)
# =============================================================================

def main():
    st.title("SGS CRM CLOUD V1.0 ☁️")
    
    # Load Data ban đầu
    with st.spinner("Đang tải dữ liệu từ Google Sheets..."):
        df_cust = load_data("Customers")
        df_supp = load_data("Suppliers")
        df_pur = load_data("Purchases")
        df_hist = load_data("History")
        df_orders = load_data("Orders")
        df_track = load_data("Tracking")
        df_pay = load_data("Payment")

    # Tạo Tabs chính
    tab_dashboard, tab_quote, tab_orders, tab_tracking, tab_master = st.tabs([
        "📊 Tổng quan", "📝 Báo Giá KH", "📦 Đơn Hàng", "🚚 Tracking & Payment", "⚙️ Master Data"
    ])

    # --- TAB 1: DASHBOARD ---
    with tab_dashboard:
        st.header("Dashboard Kinh Doanh")
        col1, col2, col3, col4 = st.columns(4)
        
        # Tính toán sơ bộ
        rev = 0
        prof = 0
        if not df_orders.empty:
            df_orders["total_price"] = pd.to_numeric(df_orders["total_price"], errors='coerce').fillna(0)
            rev = df_orders["total_price"].sum()
        
        if not df_hist.empty:
            df_hist["profit"] = pd.to_numeric(df_hist["profit"], errors='coerce').fillna(0)
            prof = df_hist["profit"].sum()
            
        unpaid_count = 0
        if not df_pay.empty:
            unpaid_count = len(df_pay[df_pay["status"] != "Đã thanh toán"])

        col1.metric("Tổng Doanh Thu (Orders)", fmt_num(rev))
        col2.metric("Tổng Lợi Nhuận (History)", fmt_num(prof))
        col3.metric("Đơn chưa thanh toán", str(unpaid_count))
        col4.metric("Số lượng Khách", str(len(df_cust)))
        
        st.divider()
        if st.button("Làm mới dữ liệu toàn hệ thống"):
            st.cache_data.clear()
            st.rerun()

    # --- TAB 2: BÁO GIÁ KHÁCH HÀNG (CORE FEATURE) ---
    with tab_quote:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.subheader("1. Thông tin")
            cust_opts = df_cust["short_name"].unique().tolist() if not df_cust.empty else []
            sel_cust = st.selectbox("Khách hàng:", [""] + cust_opts)
            quote_name = st.text_input("Tên Báo Giá:", value=f"BG-{datetime.now().strftime('%d%m%y')}")
            
            with st.expander("2. Tham số Chi Phí (%)", expanded=True):
                col_p1, col_p2 = st.columns(2)
                p_end = col_p1.text_input("End user (%)", "0")
                p_buy = col_p2.text_input("Buyer (%)", "0")
                p_tax = col_p1.text_input("Tax (%)", "0")
                p_vat = col_p2.text_input("VAT (%)", "0")
                p_pay = col_p1.text_input("Payback (%)", "0")
                p_mgmt = col_p2.text_input("Mgmt (%)", "0")
                p_trans = st.text_input("Trans Global (VND/item)", "") # Để trống là dùng theo item

        with c2:
            st.subheader("3. Chi tiết Báo Giá")
            
            # Init Session State
            if "quote_df" not in st.session_state:
                st.session_state.quote_df = pd.DataFrame(columns=[
                    "item_code", "item_name", "specs", "qty", 
                    "buying_price_vnd", "ap_price", "unit_price", "transportation",
                    "total_price_vnd", "profit_vnd", "profit_pct", "supplier_name", "leadtime"
                ])
                # Thêm các cột ẩn để tính toán
                cols_hidden = ["total_buying_price_vnd", "ap_total_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val", "mgmt_fee", "payback_val"]
                for c in cols_hidden:
                    if c not in st.session_state.quote_df.columns:
                        st.session_state.quote_df[c] = 0

            # --- SEARCH ENGINE ---
            st.write("🔍 **Tìm kiếm từ DB Giá NCC:**")
            search_col1, search_col2 = st.columns([3, 1])
            kw = search_col1.text_input("Nhập Mã, Tên hoặc Thông số:", placeholder="Ví dụ: MCB 10A...", key="kw_search")
            
            if kw and not df_pur.empty:
                # Logic Clean Key Search
                clean_k = clean_lookup_key(kw)
                mask = (
                    df_pur["item_code"].astype(str).apply(clean_lookup_key).str.contains(clean_k) |
                    df_pur["item_name"].astype(str).apply(clean_lookup_key).str.contains(clean_k) |
                    df_pur["specs"].astype(str).apply(clean_lookup_key).str.contains(clean_k)
                )
                found_df = df_pur[mask].head(5) # Chỉ hiện 5 kết quả đầu
                
                if not found_df.empty:
                    st.success(f"Tìm thấy {len(found_df)} kết quả.")
                    # Hiển thị kết quả rút gọn để chọn
                    display_cols = ["item_code", "item_name", "specs", "buying_price_vnd", "supplier_name"]
                    
                    # Dùng data_editor để chọn (Checkbox trick)
                    found_df["CHỌN"] = False
                    selected_df = st.data_editor(
                        found_df[["CHỌN"] + display_cols], 
                        column_config={"CHỌN": st.column_config.CheckboxColumn(required=True)},
                        disabled=display_cols,
                        key="search_res"
                    )
                    
                    if st.button("⬇️ Thêm hàng đã chọn vào Báo Giá"):
                        items_to_add = selected_df[selected_df["CHỌN"] == True]
                        if not items_to_add.empty:
                            new_rows = []
                            for _, row in items_to_add.iterrows():
                                new_rows.append({
                                    "item_code": row["item_code"],
                                    "item_name": row["item_name"],
                                    "specs": row["specs"],
                                    "qty": 1,
                                    "buying_price_vnd": to_float(row["buying_price_vnd"]),
                                    "ap_price": 0, "unit_price": 0, "transportation": 0,
                                    "supplier_name": row["supplier_name"],
                                    "total_price_vnd": 0, "profit_vnd": 0, "profit_pct": 0
                                })
                            st.session_state.quote_df = pd.concat([st.session_state.quote_df, pd.DataFrame(new_rows)], ignore_index=True)
                            st.rerun()
                else:
                    st.warning("Không tìm thấy sản phẩm nào.")

            st.divider()
            
            # --- MAIN QUOTE TABLE (EDITABLE) ---
            st.write("📋 **Bảng tính Báo Giá (Sửa trực tiếp bên dưới):**")
            
            grid_df = st.data_editor(
                st.session_state.quote_df,
                num_rows="dynamic",
                column_config={
                    "qty": st.column_config.NumberColumn("Số lượng", min_value=1),
                    "buying_price_vnd": st.column_config.NumberColumn("Giá Mua", format="%d"),
                    "ap_price": st.column_config.NumberColumn("AP Price", format="%d"),
                    "unit_price": st.column_config.NumberColumn("Giá Bán", format="%d"),
                    "transportation": st.column_config.NumberColumn("Trans", format="%d"),
                    "total_price_vnd": st.column_config.NumberColumn("Thành Tiền", format="%d", disabled=True),
                    "profit_vnd": st.column_config.NumberColumn("Lãi VND", format="%d", disabled=True),
                    "profit_pct": st.column_config.NumberColumn("% Lãi", format="%.2f%%", disabled=True),
                },
                use_container_width=True,
                height=400,
                key="editor_quote"
            )
            
            # --- AUTO RECALCULATE LOGIC ---
            # Logic: Mỗi khi User sửa bảng grid_df, ta chạy hàm tính toán và update lại session_state
            params = {
                "end": p_end, "buy": p_buy, "tax": p_tax, 
                "vat": p_vat, "pay": p_pay, "mgmt": p_mgmt, "trans": p_trans
            }
            
            # Nút Tính Toán Thủ Công (Để tiết kiệm resource, không tính realtime liên tục)
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("🔄 TÍNH TOÁN LỢI NHUẬN", type="primary"):
                    calced_df = recalculate_logic(grid_df, params)
                    st.session_state.quote_df = calced_df
                    st.rerun()
            
            with col_act2:
                if st.button("🗑️ Xóa Trắng Báo Giá"):
                    st.session_state.quote_df = st.session_state.quote_df.iloc[0:0]
                    st.rerun()

            # --- FOOTER & SAVE ---
            if not st.session_state.quote_df.empty:
                total_val = st.session_state.quote_df["total_price_vnd"].sum()
                total_prof = st.session_state.quote_df["profit_vnd"].sum()
                
                st.info(f"💰 TỔNG GIÁ TRỊ: {fmt_num(total_val)} VND | LỢI NHUẬN: {fmt_num(total_prof)} VND")
                
                if st.button("💾 LƯU LỊCH SỬ BÁO GIÁ"):
                    if not sel_cust:
                        st.error("Vui lòng chọn Khách Hàng!")
                    else:
                        save_df = st.session_state.quote_df.copy()
                        save_df["customer"] = sel_cust
                        save_df["quote_no"] = quote_name
                        save_df["date"] = datetime.now().strftime("%d/%m/%Y")
                        save_df["profit"] = save_df["profit_vnd"] # Map column name for dashboard
                        save_df["total_revenue"] = save_df["total_price_vnd"]
                        
                        # Chỉ giữ lại các cột cần thiết để lưu history nhẹ
                        cols_to_save = ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "profit", "supplier_name"]
                        # Đảm bảo cột tồn tại
                        for c in cols_to_save:
                            if c not in save_df.columns: save_df[c] = ""
                            
                        final_save = save_df[cols_to_save]
                        
                        current_hist = load_data("History")
                        updated_hist = pd.concat([current_hist, final_save], ignore_index=True)
                        save_data("History", updated_hist)

                # Export Excel (Basic)
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    st.session_state.quote_df.to_excel(writer, sheet_name='Quote', index=False)
                
                st.download_button(
                    label="📥 Tải file Excel",
                    data=buffer,
                    file_name=f"Quote_{quote_name}.xlsx",
                    mime="application/vnd.ms-excel"
                )

    # --- TAB 3: ĐƠN HÀNG (ORDERS) ---
    with tab_orders:
        st.subheader("Quản lý Đơn Hàng")
        st.info("Chức năng tạo Đơn hàng Khách (PO) và lưu vào hệ thống.")
        
        o_col1, o_col2 = st.columns(2)
        with o_col1:
            o_cust = st.selectbox("Khách Hàng:", [""] + df_cust["short_name"].unique().tolist(), key="o_cust")
            o_po = st.text_input("Số PO Khách:", key="o_po")
            o_date = st.date_input("Ngày đặt:", datetime.now())
        
        with o_col2:
            st.write("Nhập chi tiết đơn hàng:")
            if "order_temp_df" not in st.session_state:
                st.session_state.order_temp_df = pd.DataFrame(columns=["item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta"])
            
            o_grid = st.data_editor(
                st.session_state.order_temp_df,
                num_rows="dynamic",
                key="order_editor"
            )
        
        if st.button("Lưu Đơn Hàng"):
            if not o_cust or not o_po:
                st.error("Thiếu thông tin Khách hoặc PO")
            elif o_grid.empty:
                st.error("Chưa có hàng hóa")
            else:
                o_save = o_grid.copy()
                o_save["customer"] = o_cust
                o_save["po_number"] = o_po
                o_save["order_date"] = o_date.strftime("%d/%m/%Y")
                # Auto calc total
                o_save["qty"] = pd.to_numeric(o_save["qty"], errors='coerce').fillna(0)
                o_save["unit_price"] = pd.to_numeric(o_save["unit_price"], errors='coerce').fillna(0)
                o_save["total_price"] = o_save["qty"] * o_save["unit_price"]
                
                current_orders = load_data("Orders")
                updated_orders = pd.concat([current_orders, o_save], ignore_index=True)
                save_data("Orders", updated_orders)
                
                # Auto create Tracking
                new_track = pd.DataFrame([{
                    "po_no": o_po, "partner": o_cust, "status": "Đang đợi hàng về",
                    "eta": "", "last_update": datetime.now().strftime("%d/%m/%Y"),
                    "order_type": "KH"
                }])
                current_track = load_data("Tracking")
                updated_track = pd.concat([current_track, new_track], ignore_index=True)
                save_data("Tracking", updated_track)

                st.session_state.order_temp_df = pd.DataFrame(columns=st.session_state.order_temp_df.columns)
                st.rerun()
        
        st.divider()
        st.write("Danh sách Đơn hàng gần đây:")
        st.dataframe(df_orders.tail(10))

    # --- TAB 4: TRACKING & PAYMENT ---
    with tab_tracking:
        t1, t2 = st.columns(2)
        with t1:
            st.subheader("🚚 Theo dõi Vận Đơn")
            if not df_track.empty:
                # Edit status directly
                track_editor = st.data_editor(
                    df_track,
                    column_config={
                        "status": st.column_config.SelectboxColumn(
                            "Trạng thái",
                            options=["Đang đợi hàng về", "Đã giao hàng", "Hàng đã về VN", "Đã đặt hàng"]
                        )
                    },
                    key="track_edit"
                )
                if st.button("Cập nhật Tracking"):
                    save_data("Tracking", track_editor)
        
        with t2:
            st.subheader("💰 Theo dõi Thanh Toán")
            # Logic: Lọc các đơn từ Tracking đã giao hàng -> Đẩy sang Payment (Giả lập)
            # Ở đây hiển thị bảng Payment mẫu
            if not df_pay.empty:
                pay_editor = st.data_editor(
                    df_pay,
                    column_config={
                        "status": st.column_config.SelectboxColumn(
                            "Trạng thái",
                            options=["Chưa thanh toán", "Đã thanh toán", "Quá hạn"]
                        )
                    },
                    key="pay_edit"
                )
                if st.button("Cập nhật Thanh Toán"):
                    save_data("Payment", pay_editor)

    # --- TAB 5: MASTER DATA ---
    with tab_master:
        st.warning("⚠️ Khu vực dành cho Admin. Thay đổi ở đây sẽ ảnh hưởng toàn hệ thống.")
        
        m_opt = st.radio("Chọn Data:", ["Sản Phẩm (Purchases)", "Khách Hàng (Customers)", "NCC (Suppliers)"])
        
        if m_opt == "Sản Phẩm (Purchases)":
            edited_pur = st.data_editor(df_pur, num_rows="dynamic", key="edit_pur")
            if st.button("Lưu thay đổi DB Sản Phẩm"):
                save_data("Purchases", edited_pur)
                
        elif m_opt == "Khách Hàng (Customers)":
            edited_cust = st.data_editor(df_cust, num_rows="dynamic", key="edit_cust")
            if st.button("Lưu thay đổi DB Khách"):
                save_data("Customers", edited_cust)

        elif m_opt == "NCC (Suppliers)":
            edited_supp = st.data_editor(df_supp, num_rows="dynamic", key="edit_supp")
            if st.button("Lưu thay đổi DB NCC"):
                save_data("Suppliers", edited_supp)

if __name__ == "__main__":
    main()