import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import time
import json
import re
import datetime
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
import mimetypes

# =============================================================================
# 1. CẤU HÌNH & GIAO DIỆN (UI/UX & CONFIG) [cite: 5, 20]
# =============================================================================
st.set_page_config(layout="wide", page_title="CRM System V6098", page_icon="💎")

# Custom CSS [cite: 22]
st.markdown("""
<style>
    /* Tab Font */
    .stTabs [data-baseweb="tab"] {
        font-size: 18px;
        font-weight: 700;
    }
    
    /* 3D Cards */
    .metric-card {
        border-radius: 12px;
        box-shadow: 0 4px 8px 0 rgba(0,0,0,0.2);
        padding: 20px;
        text-align: center;
        color: white;
        margin-bottom: 20px;
        transition: 0.3s;
    }
    .metric-card:hover {
        box-shadow: 0 8px 16px 0 rgba(0,0,0,0.2);
    }
    .bg-sales { background: linear-gradient(to right, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(to right, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(to right, #f83600, #f9d423); }
    
    /* Button Style [cite: 29] */
    .stButton>button {
        background-color: #262730;
        color: white;
        border: 1px solid #555;
        border-radius: 5px;
    }
    .stButton>button:hover {
        background-color: #444444;
        color: #00FF00;
        border-color: #00FF00;
    }

    /* Highlight Low Profit [cite: 31] */
    .highlight-low {
        background-color: #ffcccc;
        color: red;
        font-weight: bold;
    }
    
    /* Total View Box [cite: 32] */
    .total-view-box {
        background-color: #262730;
        color: #00FF00;
        padding: 10px;
        text-align: right;
        font-weight: bold;
        border-radius: 5px;
        margin-top: 10px;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 2. KẾT NỐI HỆ THỐNG (CONNECTORS) [cite: 15]
# =============================================================================

# 2.1 Supabase Connection [cite: 11, 17]
@st.cache_resource
def init_supabase():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Lỗi kết nối Supabase: {e}")
        st.stop()

supabase = init_supabase()

# 2.2 Google Drive Connection (OAuth2 Refresh Token) [cite: 12, 18, 34]
@st.cache_resource
def init_drive():
    try:
        info = st.secrets["google_auth"]
        creds = Credentials(
            None,
            refresh_token=info["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=info["client_id"],
            client_secret=info["client_secret"]
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Lỗi kết nối Google Drive: {e}")
        st.stop()

drive_service = init_drive()
ROOT_FOLDER_ID = st.secrets["google_auth"]["root_folder_id"]

# =============================================================================
# 3. CÁC HÀM XỬ LÝ LOGIC (HELPER FUNCTIONS) [cite: 175]
# =============================================================================

# 3.1 String Cleaning 
def strict_match_key(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r'\s+', '', text).lower()

# 3.2 Number Handling [cite: 179]
def to_float(val):
    if pd.isna(val) or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    # Xử lý chuỗi tiền tệ
    clean_val = str(val).replace(',', '').replace('¥', '').replace('$', '').replace('VND', '').replace('RMB', '')
    try:
        return float(clean_val)
    except:
        return 0.0

def fmt_num(val): # 
    try:
        if val == int(val):
            return "{:,.0f}".format(val)
        return "{:,.1f}".format(val).rstrip('0').rstrip('.')
    except:
        return "0"

# 3.3 Google Drive Utils [cite: 36, 37, 188]
def get_or_create_folder(folder_name, parent_id=ROOT_FOLDER_ID):
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    else:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        file = drive_service.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')

def upload_file_to_drive(file_content, file_name, folder_id, mime_type='application/octet-stream'):
    # Check duplicate [cite: 40, 189]
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    
    media = MediaIoBaseUpload(file_content, mimetype=mime_type, resumable=True)
    
    if files:
        # Update logic
        file_id = files[0]['id']
        drive_service.files().update(fileId=file_id, media_body=media).execute()
    else:
        # Create logic
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_id = file.get('id')
    
    # Set permission [cite: 41]
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={'role': 'reader', 'type': 'anyone'},
            fields='id'
        ).execute()
    except:
        pass # Ignore if already public
        
    return file_id, f"https://drive.google.com/uc?id={file_id}"

# =============================================================================
# 4. GIAO DIỆN CHÍNH (MAIN APP)
# =============================================================================

# Header
st.title("💎 CRM SYSTEM (V6098)")

# Tabs [cite: 23]
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "DASHBOARD", "KHO HÀNG", "BÁO GIÁ", "QUẢN LÝ PO", "TRACKING", "MASTER DATA"
])

# -----------------------------------------------------------------------------
# TAB 1: DASHBOARD [cite: 43]
# -----------------------------------------------------------------------------
with tab1:
    if st.button("🔄 Refresh Data"): # [cite: 44]
        st.cache_data.clear()
        st.rerun()
    
    # Fetch Data
    try:
        orders = supabase.table("db_customer_orders").select("total_price").execute().data
        costs = supabase.table("db_supplier_orders").select("total_vnd").execute().data
        
        total_revenue = sum([to_float(x['total_price']) for x in orders]) # [cite: 46]
        total_cost = sum([to_float(x['total_vnd']) for x in costs]) # [cite: 47]
        gross_profit = total_revenue - total_cost # [cite: 48]
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-card bg-sales"><h3>DOANH THU</h3><h2>{fmt_num(total_revenue)} VND</h2></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card bg-cost"><h3>CHI PHÍ NCC</h3><h2>{fmt_num(total_cost)} VND</h2></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card bg-profit"><h3>LỢI NHUẬN GỘP</h3><h2>{fmt_num(gross_profit)} VND</h2></div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Lỗi tải Dashboard: {e}")

# -----------------------------------------------------------------------------
# TAB 2: KHO HÀNG (Inventory) [cite: 50]
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("📦 Quản lý Kho Hàng")
    
    col_act1, col_act2 = st.columns([1, 2])
    
    with col_act1:
        # Reset DB [cite: 52]
        with st.expander("⚠️ Reset Database"):
            pwd = st.text_input("Mật khẩu Admin", type="password", key="reset_inv_pwd")
            if st.button("Xóa toàn bộ Kho"):
                if pwd == "admin":
                    supabase.table("crm_purchases").delete().neq("id", 0).execute() # [cite: 54]
                    st.success("Đã xóa dữ liệu kho!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Sai mật khẩu!")

    with col_act2:
        # Import Excel [cite: 55]
        uploaded_file = st.file_uploader("Upload File 'BUYING PRICE-ALL-OK.xlsx'", type=['xlsx'])
        if uploaded_file and st.button("Import Data"):
            try:
                wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                ws = wb.active
                
                # Setup Drive folder for images [cite: 61]
                img_folder_id = get_or_create_folder("CRM_PRODUCT_IMAGES")
                
                # Image mapping dictionary
                image_map = {}
                
                # Extract Images using openpyxl [cite: 58, 59]
                # Logic: Find images anchored to cells
                for image in ws._images:
                    row = image.anchor._from.row + 1 # openpyxl 0-indexed
                    # Col "Images" is M (13th column) in Excel file provided
                    # Assume image anchor is near the row
                    if row not in image_map:
                         image_map[row] = image

                rows_to_insert = []
                # Đọc từ dòng 2 (skip header) [cite: 56]
                for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    # Mapping cột theo file BUYING PRICE [cite: 57]
                    # No(0), Code(1), Name(2), Specs(3), Qty(4), BuyingRMB(5), TotalRMB(6), Rate(7), BuyingVND(8), TotalVND(9), Lead(10), Supp(11), Img(12), Type(13), Cond(14)
                    item_code = str(row[1]) if row[1] else ""
                    specs = str(row[3]) if row[3] else ""
                    
                    if not item_code: continue

                    # Image Processing [cite: 60, 61, 62]
                    img_link = None
                    if idx in image_map:
                        img_obj = image_map[idx]
                        img_bytes = io.BytesIO(img_obj.ref.read())
                        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', specs)[:20]
                        img_name = f"{clean_name}_{int(time.time())}.png"
                        _, img_link = upload_file_to_drive(img_bytes, img_name, img_folder_id, "image/png")

                    data = {
                        "item_code": item_code,
                        "item_name": str(row[2]),
                        "specs": specs,
                        "qty": to_float(row[4]),
                        "buying_price_rmb": to_float(row[5]),
                        "total_buying_price_rmb": to_float(row[6]),
                        "exchange_rate": to_float(row[7]),
                        "buying_price_vnd": to_float(row[8]),
                        "total_buying_price_vnd": to_float(row[9]),
                        "leadtime": str(row[10]),
                        "supplier": str(row[11]),
                        "image_path": img_link, 
                        "type": str(row[13]),
                        "condition": str(row[14])
                    }
                    rows_to_insert.append(data)
                
                # Batch Insert [cite: 65]
                if rows_to_insert:
                    # Remove duplicates first [cite: 64]
                    codes = [r['item_code'] for r in rows_to_insert]
                    supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                    
                    batch_size = 100
                    for i in range(0, len(rows_to_insert), batch_size):
                        batch = rows_to_insert[i:i+batch_size]
                        supabase.table("crm_purchases").insert(batch).execute()
                    
                    st.success(f"Đã import thành công {len(rows_to_insert)} dòng!")
                    st.rerun()
            except Exception as e:
                st.error(f"Lỗi Import: {e}")

    # Search & Display [cite: 66, 67]
    search_term = st.text_input("🔍 Tìm kiếm (Code, Name, Specs)", "")
    
    query = supabase.table("crm_purchases").select("*")
    if search_term:
        # Supabase ilike workaround or simple logic
        pass # Streamlit dataframe filter is easier for UI
    
    data = query.execute().data
    df = pd.DataFrame(data)
    
    if not df.empty:
        if search_term:
            mask = df.apply(lambda x: search_term.lower() in str(x).lower(), axis=1)
            df = df[mask]
        
        # Display with Image Column [cite: 68]
        st.dataframe(
            df,
            column_config={
                "image_path": st.column_config.ImageColumn("Image", help="Product Image"),
                "buying_price_vnd": st.column_config.NumberColumn("Price VND", format="%d"),
            },
            height=600
        )

# -----------------------------------------------------------------------------
# TAB 3: BÁO GIÁ (Quotation) [cite: 69]
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("📝 Tạo & Quản lý Báo giá")
    
    # Session State for Quotation
    if 'quote_df' not in st.session_state:
        st.session_state.quote_df = pd.DataFrame(columns=[
            'Code', 'Name', 'Specs', 'Qty', 'Unit', 'Buying Price', 'ExRate', 
            'Supplier', 'Leadtime', 'Image', 'AP Price', 'Unit Price', 'Total Price', 
            'Markup', 'Tax', 'Profit'
        ])
    
    # A. Config & History
    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown("### ⚙️ Cấu hình Chi phí") # [cite: 81]
        with st.form("quote_config"):
            cust_list = supabase.table("crm_customers").select("short_name").execute().data
            customer = st.selectbox("Khách hàng", [c['short_name'] for c in cust_list])
            quote_no = st.text_input("Quote No (VD: Q20251230-01)")
            
            # Global Params [cite: 82]
            p_end_user = st.number_input("End user (%)", 0.0, 100.0, 10.0)
            p_buyer = st.number_input("Buyer (%)", 0.0, 100.0, 5.0)
            p_import_tax = st.number_input("Import tax (%)", 0.0, 100.0, 8.0)
            p_vat = st.number_input("VAT (%)", 0.0, 100.0, 8.0) # 8% or 10%
            p_payback = st.number_input("Payback (%)", 0.0, 100.0, 0.0)
            p_mgmt = st.number_input("Management fee (%)", 0.0, 100.0, 2.0)
            val_transport = st.number_input("Transportation (VND)", 0, step=10000, value=500000)
            
            apply_btn = st.form_submit_button("Áp dụng cấu hình") # [cite: 83]
    
    with c2:
        st.markdown("### 📥 Matching & Editor")
        # Upload RFQ [cite: 84]
        rfq_file = st.file_uploader("Upload RFQ (Excel)", type=['xlsx'])
        if rfq_file and st.button("Matching Data"):
            try:
                rfq_df = pd.read_excel(rfq_file)
                # Logic: Read Inventory
                inv_data = supabase.table("crm_purchases").select("*").execute().data
                inv_df = pd.DataFrame(inv_data)
                
                # Create Key for matching [cite: 86]
                inv_df['match_key'] = inv_df.apply(lambda x: strict_match_key(f"{x['item_code']}{x['item_name']}{x['specs']}"), axis=1)
                
                matched_rows = []
                for _, row in rfq_df.iterrows():
                    # Assume RFQ has columns: Code, Name, Specs, Qty
                    q_code = str(row.get('Item code', ''))
                    q_name = str(row.get('Item name', ''))
                    q_spec = str(row.get('Specs', ''))
                    q_qty = to_float(row.get("Q'ty", 1))
                    
                    key = strict_match_key(f"{q_code}{q_name}{q_spec}")
                    match = inv_df[inv_df['match_key'] == key]
                    
                    new_row = {
                        'Code': q_code, 'Name': q_name, 'Specs': q_spec, 'Qty': q_qty,
                        'Unit': 'PCS', 'Buying Price': 0, 'ExRate': 4000, 
                        'Supplier': '', 'Leadtime': '', 'Image': '', 'AP Price': 0, 'Unit Price': 0
                    }
                    
                    if not match.empty: # [cite: 87]
                        r = match.iloc[0]
                        new_row['Buying Price'] = r['buying_price_vnd']
                        new_row['ExRate'] = r['exchange_rate']
                        new_row['Supplier'] = r['supplier']
                        new_row['Leadtime'] = r['leadtime']
                        new_row['Image'] = r['image_path']
                    else:
                        st.warning(f"⚠️ DATA KHÔNG KHỚP: {q_code}") # [cite: 88]
                        
                    matched_rows.append(new_row)
                
                st.session_state.quote_df = pd.DataFrame(matched_rows)
            except Exception as e:
                st.error(f"Lỗi Matching: {e}")

        # Formula Parser [cite: 89, 90, 94]
        st.markdown("#### Formula Parser")
        formula_input = st.text_input("Nhập công thức (vd: =buying price*1.1)", key="formula_in")
        if st.button("Áp dụng Công thức"):
            if formula_input.startswith("="):
                expression = formula_input[1:].lower() # [cite: 177] - Lowercase handling
                # Safe eval replacement
                expression = expression.replace("buying price", "x['Buying Price']")
                expression = expression.replace("ap price", "x['AP Price']")
                expression = expression.replace("x", "*").replace(":", "/")
                
                try:
                    # Apply to dataframe
                    st.session_state.quote_df['AP Price'] = st.session_state.quote_df.apply(
                        lambda x: eval(expression, {"x": x, "__builtins__": None}), axis=1
                    ).astype(float)
                    st.success("Đã áp dụng công thức!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi công thức: {e}")

        # Data Editor [cite: 102]
        edited_df = st.data_editor(
            st.session_state.quote_df,
            num_rows="dynamic",
            column_config={
                "Image": st.column_config.ImageColumn(),
                "Buying Price": st.column_config.NumberColumn(format="%d"),
                "AP Price": st.column_config.NumberColumn(format="%d"),
                "Unit Price": st.column_config.NumberColumn(format="%d"),
                "Total Price": st.column_config.NumberColumn(format="%d"),
            },
            key="editor_quote"
        )
        
        # Recalculate Logic [cite: 95]
        if apply_btn or True: # Auto recalc
            # Tính toán chi tiết
            # Total Buying
            edited_df['Total Buying'] = edited_df['Buying Price'] * edited_df['Qty']
            
            # Logic tính giá bán và lợi nhuận [cite: 99]
            # Giả sử Unit Price là giá người dùng chốt bán
            edited_df['Total Price'] = edited_df['Unit Price'] * edited_df['Qty']
            
            # Tính GAP (nếu dùng AP Price làm mốc trung gian)
            edited_df['AP Total'] = edited_df['AP Price'] * edited_df['Qty']
            edited_df['GAP'] = edited_df['Total Price'] - edited_df['AP Total']
            
            # Tính chi phí dựa trên % (Logic đơn giản hóa theo specs)
            total_rev = edited_df['Total Price'].sum()
            
            # Nếu dòng này Profit < 10% -> Highlight [cite: 101]
            # (Thực hiện ở bước hiển thị CSS style pandas nếu cần, ở đây tính toán data)
            
            st.session_state.quote_df = edited_df

        # Total Row [cite: 105]
        total_vnd = st.session_state.quote_df['Total Price'].sum()
        total_buy = st.session_state.quote_df['Total Buying'].sum()
        
        # Tính toán Profit tổng [cite: 99]
        # Profit = Total Price - (Total Buying + GAP + Các loại phí + Vận chuyển) + Payback
        # Note: Logic này cần tinh chỉnh theo thực tế từng dòng hoặc tổng.
        # Ở đây tính tổng quát:
        cost_fees = total_rev * (p_end_user + p_buyer + p_import_tax + p_mgmt)/100
        profit_vnd = total_vnd - (total_buy + cost_fees + val_transport) + (total_vnd * p_payback/100)
        
        st.markdown(f"""
        <div class="total-view-box">
            TỔNG GIÁ TRỊ: {fmt_num(total_vnd)} VND | LỢI NHUẬN ƯỚC TÍNH: {fmt_num(profit_vnd)} VND
        </div>
        """, unsafe_allow_html=True)

    # C. Export & Save [cite: 109]
    st.markdown("---")
    c_ex1, c_ex2 = st.columns(2)
    with c_ex1:
        if st.button("💾 Lưu Lịch sử & JSON"): # [cite: 117]
            config_data = {
                "end_user": p_end_user, "buyer": p_buyer, "transport": val_transport,
                "vat": p_vat
            }
            # Save to DB
            supabase.table("crm_shared_history").insert({
                "quote_no": quote_no,
                "customer_name": customer,
                "total_price_vnd": total_vnd,
                "profit_vnd": profit_vnd,
                "config_data": config_data
            }).execute()
            st.success("Đã lưu lịch sử báo giá!")
            
    with c_ex2:
        if st.button("📤 Xuất Excel (AAA-TEMPLATE)"): # [cite: 112]
            try:
                # 1. Tìm template 
                tpl_query = supabase.table("crm_templates").select("file_id").eq("template_name", "AAA-QUOTATION").execute()
                if not tpl_query.data:
                    st.error("Chưa cấu hình File Template 'AAA-QUOTATION' trong Tab Master Data!")
                else:
                    tpl_id = tpl_query.data[0]['file_id']
                    request = drive_service.files().get_media(fileId=tpl_id)
                    fh = io.BytesIO()
                    downloader = MediaIoBaseUpload(fh, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    # Đơn giản hóa download:
                    content = request.execute()
                    
                    # 2. Fill Data (openpyxl) [cite: 114]
                    wb_out = openpyxl.load_workbook(io.BytesIO(content))
                    ws_out = wb_out.active
                    
                    # Fill Header
                    ws_out['H5'] = quote_no # Quote No
                    ws_out['H6'] = datetime.datetime.now().strftime("%Y-%m-%d") # Date
                    
                    # Fill Items from Row 11
                    start_row = 11
                    for idx, row in st.session_state.quote_df.iterrows():
                        r = start_row + idx
                        ws_out[f'B{r}'] = row['Code']
                        ws_out[f'C{r}'] = row['Name']
                        ws_out[f'D{r}'] = row['Specs']
                        ws_out[f'E{r}'] = row['Qty']
                        ws_out[f'F{r}'] = row['Unit Price']
                        ws_out[f'G{r}'] = row['Total Price']
                        ws_out[f'H{r}'] = row['Leadtime']
                    
                    # 3. Save to Output
                    out_buffer = io.BytesIO()
                    wb_out.save(out_buffer)
                    out_buffer.seek(0)
                    
                    # Upload to Drive History [cite: 115]
                    folder_name = f"QUOTATION_HISTORY/{customer}/{datetime.datetime.now().year}"
                    # Logic tạo folder lồng nhau (đơn giản hóa ở đây là tạo folder năm)
                    hist_folder_id = get_or_create_folder(str(datetime.datetime.now().year)) 
                    file_name = f"QUOTE_{quote_no}_{customer}_{int(time.time())}.xlsx"
                    
                    _, view_link = upload_file_to_drive(out_buffer, file_name, hist_folder_id, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    st.success(f"Xuất file thành công! [Xem trên Drive]({view_link})")
            
            except Exception as e:
                st.error(f"Lỗi xuất Excel: {e}")

# -----------------------------------------------------------------------------
# TAB 4: QUẢN LÝ PO [cite: 120]
# -----------------------------------------------------------------------------
with tab4:
    st.subheader("🛒 Quản lý Đơn hàng (PO)")
    
    po_tab1, po_tab2 = st.tabs(["PO Nhà Cung Cấp", "PO Khách Hàng"])
    
    with po_tab1: # PO NCC [cite: 123]
        if st.button("Reset PO NCC (Admin)"):
            supabase.table("db_supplier_orders").delete().neq("id", 0).execute()
            
        po_ncc_file = st.file_uploader("Upload PO NCC List", type=['xlsx'])
        if po_ncc_file and st.button("Tạo PO NCC"):
            # Logic: Import -> Match Kho -> Save -> Split Files
            df_po = pd.read_excel(po_ncc_file)
            # Giả định cột khớp với file BUYING PRICE
            inserted = []
            grouped = {}
            
            for _, row in df_po.iterrows():
                # Matching logic
                code = str(row.get('Item code', ''))
                # ... match với crm_purchases để lấy supplier ...
                # Save to db_supplier_orders [cite: 130]
                supplier = row.get('Supplier', 'Unknown')
                
                # Group for splitting [cite: 132]
                if supplier not in grouped: grouped[supplier] = []
                grouped[supplier].append(row)
                
                inserted.append({
                    "po_ncc_no": f"PO-{int(time.time())}",
                    "supplier_name": supplier,
                    "item_code": code,
                    "status": "Ordered"
                })
            
            if inserted:
                supabase.table("db_supplier_orders").insert(inserted).execute()
                # Tracking update [cite: 131]
                st.success("Đã tạo PO NCC và cập nhật Tracking!")

    with po_tab2: # PO Khách hàng [cite: 134]
        # Logic tương tự: Upload PO Khách -> Match History (ưu tiên) hoặc Kho -> Save
        pass

# -----------------------------------------------------------------------------
# TAB 5: TRACKING [cite: 143]
# -----------------------------------------------------------------------------
with tab5:
    st.subheader("🚚 Tracking & Thanh toán")
    
    # List Active Orders [cite: 146]
    active_orders = supabase.table("db_customer_orders").select("*").neq("status", "Delivered").execute().data
    
    if active_orders:
        df_track = pd.DataFrame(active_orders)
        st.dataframe(df_track)
        
        # Update Status Form [cite: 148]
        with st.form("update_status"):
            po_select = st.selectbox("Chọn PO", [o['po_no'] for o in active_orders])
            new_status = st.selectbox("Trạng thái mới", ["Ordered", "Shipping", "Arrived", "Delivered"])
            proof_img = st.file_uploader("Ảnh bằng chứng (Proof)", type=['png', 'jpg'])
            
            if st.form_submit_button("Cập nhật"):
                # Upload proof logic [cite: 149]
                proof_link = ""
                if proof_img:
                    f_id, proof_link = upload_file_to_drive(proof_img, f"PROOF_{po_select}.png", ROOT_FOLDER_ID, "image/png")
                
                # Update DB
                supabase.table("db_customer_orders").update({
                    "status": new_status,
                    "proof_image": proof_link
                }).eq("po_no", po_select).execute()
                
                # Trigger Payment [cite: 151]
                if new_status == "Delivered":
                    # Check payment
                    exist = supabase.table("crm_payments").select("*").eq("po_no", po_select).execute().data
                    if not exist:
                        eta = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
                        supabase.table("crm_payments").insert({
                            "po_no": po_select,
                            "status": "Đợi xuất hóa đơn",
                            "eta_payment": eta
                        }).execute() # [cite: 153]
                
                st.success("Cập nhật thành công!")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB 6: MASTER DATA [cite: 165]
# -----------------------------------------------------------------------------
with tab6:
    st.subheader("🗂️ Dữ liệu Nền")
    
    md1, md2, md3 = st.tabs(["Khách hàng", "Nhà cung cấp", "Template"])
    
    with md1: # [cite: 166]
        cust_df = pd.DataFrame(supabase.table("crm_customers").select("*").execute().data)
        edited_cust = st.data_editor(cust_df, num_rows="dynamic", key="editor_cust")
        if st.button("Lưu Khách hàng"):
            # Logic update/upsert basic
            pass
            
    with md3: # Template Management [cite: 170]
        st.markdown("### Quản lý File Mẫu (Template)")
        tpl_file = st.file_uploader("Upload Template (AAA-QUOTATION)", type=['xlsx'])
        if tpl_file and st.button("Lưu Template"):
            # Upload to Drive
            f_id, _ = upload_file_to_drive(tpl_file, "AAA-QUOTATION.xlsx", ROOT_FOLDER_ID, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            # Save ID to DB [cite: 173]
            # Xóa cũ
            supabase.table("crm_templates").delete().eq("template_name", "AAA-QUOTATION").execute()
            supabase.table("crm_templates").insert({
                "template_name": "AAA-QUOTATION",
                "file_id": f_id
            }).execute()
            st.success("Đã lưu Template ID thành công!") # [cite: 173]
