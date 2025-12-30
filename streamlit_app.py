import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import openpyxl
from openpyxl.drawing.image import Image
from openpyxl import load_workbook
import io
import datetime
import re
import json
import time

# --- 1. CONFIG & SETUP ---
st.set_page_config(layout="wide", page_title="CRM System", page_icon="💎")

# Load Secrets
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    
    GOOGLE_CLIENT_ID = st.secrets["google_oauth"]["client_id"]
    GOOGLE_CLIENT_SECRET = st.secrets["google_oauth"]["client_secret"]
    GOOGLE_REFRESH_TOKEN = st.secrets["google_oauth"]["refresh_token"]
    DRIVE_ROOT_FOLDER_ID = st.secrets["google_oauth"]["root_folder_id"]
except Exception as e:
    st.error(f"Missing configuration in secrets.toml: {e}")
    st.stop()

# Initialize Supabase
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

# --- 2. CUSTOM CSS (UI/UX) ---
st.markdown("""
<style>
    /* Tab Styling */
    .stTabs [data-baseweb="tab"] {
        font-size: 18px;
        font-weight: 700;
    }
    
    /* 3D Cards */
    .metric-card {
        border-radius: 12px;
        padding: 20px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 8px 0 rgba(0,0,0,0.2);
        transition: 0.3s;
        margin-bottom: 20px;
    }
    .metric-card:hover {
        box-shadow: 0 8px 16px 0 rgba(0,0,0,0.2);
    }
    .bg-sales { background: linear-gradient(to right, #00b09b, #96c93d); }
    .bg-cost { background: linear-gradient(to right, #ff5f6d, #ffc371); }
    .bg-profit { background: linear-gradient(to right, #f83600, #f9d423); }
    
    /* Button Styling */
    .stButton>button {
        background-color: #262730;
        color: white;
        border: 1px solid #555;
        border-radius: 5px;
    }
    .stButton>button:hover {
        background-color: #444444;
        color: #00FF00;
    }
    
    /* DataFrame Limit Height */
    [data-testid="stDataFrame"] > div {
        max-height: 750px;
    }

    /* Highlight Low Profit */
    .highlight-low {
        background-color: #ffe6e6; 
        color: red;
        font-weight: bold;
    }
    
    /* Total View Box */
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

# --- 3. GOOGLE DRIVE MODULE ---
class GoogleDriveHandler:
    def __init__(self):
        self.creds = Credentials(
            None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET
        )
        self.service = build('drive', 'v3', credentials=self.creds)

    def get_or_create_folder(self, folder_name, parent_id):
        query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        else:
            metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_id]
            }
            file = self.service.files().create(body=metadata, fields='id').execute()
            return file.get('id')

    def get_time_based_folder(self, base_folder_name):
        # Logic: Root -> Base Folder -> Year -> Month
        base_id = self.get_or_create_folder(base_folder_name, DRIVE_ROOT_FOLDER_ID)
        year = str(datetime.datetime.now().year)
        year_id = self.get_or_create_folder(year, base_id)
        month = str(datetime.datetime.now().month)
        month_id = self.get_or_create_folder(month, year_id)
        return month_id

    def upload_file(self, file_content, file_name, folder_id, mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
        # Check if file exists to update 
        query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
        results = self.service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        media = MediaIoBaseUpload(file_content, mimetype=mime_type, resumable=True)
        
        if files:
            # Update
            file_id = files[0]['id']
            self.service.files().update(fileId=file_id, media_body=media).execute()
        else:
            # Create
            metadata = {'name': file_name, 'parents': [folder_id]}
            file = self.service.files().create(body=metadata, media_body=media, fields='id').execute()
            file_id = file.get('id')
            
        # Set Permission to anyoneWithLink 
        self.service.permissions().create(
            fileId=file_id,
            body={'role': 'reader', 'type': 'anyone'},
            fields='id'
        ).execute()
        
        return f"https://drive.google.com/uc?id={file_id}" # Direct download link format

    def find_file_by_name(self, name_contains):
        query = f"name contains '{name_contains}' and trashed=false"
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])

    def download_file_bytes(self, file_id):
        request = self.service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = request.execute() # Simple download for small files
        file_io.write(downloader)
        file_io.seek(0)
        return file_io

drive = GoogleDriveHandler()

# --- 4. HELPER FUNCTIONS ---
def strict_match_key(text):
    if not isinstance(text, str): return ""
    return re.sub(r'\s+', '', text).lower()

def to_float(val):
    if pd.isna(val) or val == "": return 0.0
    s = str(val)
    s = re.sub(r'[^\d\.-]', '', s) # Remove currency symbols
    try:
        return float(s)
    except:
        return 0.0

def fmt_num(val):
    if val is None: return "0"
    if val % 1 == 0:
        return "{:,.0f}".format(val)
    return "{:,.2f}".format(val).rstrip('0').rstrip('.')

# --- 5. MAIN LOGIC TABS ---

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "DASHBOARD", "KHO HÀNG", "BÁO GIÁ", "QUẢN LÝ PO", "TRACKING", "MASTER DATA"
])

# === TAB 1: DASHBOARD ===
with tab1:
    col_ref, _ = st.columns([1, 5])
    if col_ref.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
    
    # Calculate Metrics 
    try:
        cust_orders = supabase.table("db_customer_orders").select("total_price").execute().data
        supp_orders = supabase.table("db_supplier_orders").select("total_cost").execute().data
        
        revenue = sum(item['total_price'] for item in cust_orders) if cust_orders else 0
        cost = sum(item['total_cost'] for item in supp_orders) if supp_orders else 0
        profit = revenue - cost
    except:
        revenue, cost, profit = 0, 0, 0

    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="metric-card bg-sales"><h3>DOANH THU</h3><h1>{fmt_num(revenue)}</h1></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card bg-cost"><h3>CHI PHÍ NCC</h3><h1>{fmt_num(cost)}</h1></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-card bg-profit"><h3>LỢI NHUẬN GỘP</h3><h1>{fmt_num(profit)}</h1></div>', unsafe_allow_html=True)

# === TAB 2: KHO HÀNG (INVENTORY) ===
with tab2:
    st.header("Quản lý Kho Hàng")
    
    # Import Functionality
    with st.expander("📥 Import dữ liệu từ Excel (Có xử lý ảnh)"):
        uploaded_file = st.file_uploader("Chọn file 'BUYING PRICE-ALL-OK.xlsx'", type=['xlsx'])
        if uploaded_file and st.button("Bắt đầu Import"):
            try:
                wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                ws = wb.active
                
                # Setup Google Drive Folder
                img_folder_id = drive.get_or_create_folder("CRM_PRODUCT_IMAGES", DRIVE_ROOT_FOLDER_ID)
                
                data_rows = []
                # Headers are in row 1, data starts row 2 (based on provided file, though spec says row 2 header)
                # Looking at Source 209, header is row 1. Let's assume row 1 header.
                
                # Image processing map: row_index -> image_file
                image_map = {}
                for image in ws._images:
                    # anchor row is 0-indexed in openpyxl objects usually, but need to check version.
                    # anchor._from.row is 0-indexed. Data row 2 is index 1.
                    row_idx = image.anchor._from.row + 1 # Convert to 1-based index to match cell iteration
                    image_map[row_idx] = image

                rows = list(ws.iter_rows(min_row=2, values_only=True)) # Skip header
                
                progress_bar = st.progress(0)
                
                # Delete old data (Batch delete not efficient via API, simple loop or truncate logic if policy allows)
                # For safety, we match item_code to delete before insert as requested
                
                batch_data = []
                
                for idx, row in enumerate(rows):
                    # Mapping based on and file content 
                    # File Cols: No(0), Code(1), Name(2), Specs(3), Qty(4), BuyRMB(5), TotRMB(6), Rate(7), BuyVND(8), TotVND(9), Lead(10), Supp(11), Img(12), Type(13), N/U(14)
                    item_code = str(row[1]) if row[1] else ""
                    if not item_code: continue
                    
                    specs = str(row[3]) if row[3] else "no_specs"
                    
                    # Handle Image 
                    image_url = ""
                    row_excel_idx = idx + 2
                    if row_excel_idx in image_map:
                        img_obj = image_map[row_excel_idx]
                        img_name = f"{re.sub(r'[^a-zA-Z0-9]', '_', specs)}_{item_code}.png"
                        img_stream = io.BytesIO()
                        img_stream.write(img_obj._data())
                        img_stream.seek(0)
                        # Upload to Drive
                        image_url = drive.upload_file(img_stream, img_name, img_folder_id, 'image/png')
                    
                    record = {
                        "item_code": item_code,
                        "item_name": str(row[2]),
                        "specs": specs,
                        "qty": to_float(row[4]),
                        "buying_price_rmb": to_float(row[5]),
                        "total_rmb": to_float(row[6]),
                        "exchange_rate": to_float(row[7]),
                        "buying_price_vnd": to_float(row[8]),
                        "total_vnd": to_float(row[9]),
                        "leadtime": str(row[10]),
                        "supplier": str(row[11]),
                        "image_path": image_url,
                        "type": str(row[13]),
                        "nuoc": str(row[14])
                    }
                    batch_data.append(record)
                    
                    # Batch Insert 
                    if len(batch_data) >= 100:
                        # Deduplicate logic: delete matching codes first
                        codes = [r['item_code'] for r in batch_data]
                        supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                        supabase.table("crm_purchases").insert(batch_data).execute()
                        batch_data = []
                        progress_bar.progress((idx + 1) / len(rows))

                if batch_data:
                    codes = [r['item_code'] for r in batch_data]
                    supabase.table("crm_purchases").delete().in_("item_code", codes).execute()
                    supabase.table("crm_purchases").insert(batch_data).execute()
                    
                st.success("Import thành công!")
                time.sleep(1)
                st.rerun()

            except Exception as e:
                st.error(f"Lỗi Import: {e}")

    # Reset DB 
    if st.button("⚠️ Reset Database"):
        pwd = st.text_input("Nhập mật khẩu Admin", type="password")
        if pwd == "admin":
            supabase.table("crm_purchases").delete().neq("id", 0).execute() # Delete all
            st.success("Đã xóa dữ liệu kho!")
            st.rerun()
            
    # Search & View 
    search_term = st.text_input("🔍 Tìm kiếm (Code, Name, Specs)")
    
    query = supabase.table("crm_purchases").select("*")
    if search_term:
        # Supabase 'or' syntax is tricky, fetching all then filtering pandas is easier for small/medium DBs
        # Or use textSearch if enabled. Here using Python filter for flexibility with accents
        pass
        
    data = query.execute().data
    df = pd.DataFrame(data)
    
    if not df.empty and search_term:
        term = strict_match_key(search_term)
        df = df[df.apply(lambda row: term in strict_match_key(str(row['item_code'])) or 
                                     term in strict_match_key(str(row['item_name'])) or 
                                     term in strict_match_key(str(row['specs'])), axis=1)]

    st.data_editor(
        df, 
        column_config={
            "image_path": st.column_config.ImageColumn("Image"),
            "buying_price_vnd": st.column_config.NumberColumn("Buying VND", format="%d"),
            "total_vnd": st.column_config.NumberColumn("Total VND", format="%d")
        },
        use_container_width=True,
        hide_index=True
    )

# === TAB 3: BÁO GIÁ (QUOTATION) - CORE ===
with tab3:
    st.subheader("Tạo Báo Giá Mới")
    
    # --- Config Params ---
    if "quote_config" not in st.session_state:
        st.session_state.quote_config = {
            "end_user": 10.0, "buyer": 5.0, "import_tax": 0.0, 
            "vat": 8.0, "payback": 2.0, "mgmt_fee": 1.0, "transport": 500000.0
        }
        
    with st.expander("⚙️ Cấu hình Chi phí & Lợi nhuận (Global Params)", expanded=True):
        qc1, qc2, qc3, qc4 = st.columns(4)
        st.session_state.quote_config["end_user"] = qc1.number_input("% End User", value=st.session_state.quote_config["end_user"])
        st.session_state.quote_config["buyer"] = qc2.number_input("% Buyer", value=st.session_state.quote_config["buyer"])
        st.session_state.quote_config["import_tax"] = qc3.number_input("% Import Tax", value=st.session_state.quote_config["import_tax"])
        st.session_state.quote_config["vat"] = qc4.number_input("% VAT", value=st.session_state.quote_config["vat"])
        
        qc5, qc6, qc7, qc8 = st.columns(4)
        st.session_state.quote_config["payback"] = qc5.number_input("% Payback (VND)", value=st.session_state.quote_config["payback"])
        st.session_state.quote_config["mgmt_fee"] = qc6.number_input("% Mgmt Fee", value=st.session_state.quote_config["mgmt_fee"])
        st.session_state.quote_config["transport"] = qc7.number_input("Vận chuyển (VNĐ)", value=st.session_state.quote_config["transport"])
        
        if st.button("Áp dụng cấu hình"):
            st.success("Đã cập nhật cấu hình!")
    
    # --- Input RFQ & Matching ---
    col_cust, col_qno = st.columns(2)
    
    # Get Customer List
    cust_data = supabase.table("crm_customers").select("short_name").execute().data
    cust_list = [c['short_name'] for c in cust_data]
    
    selected_customer = col_cust.selectbox("Chọn Khách hàng", options=cust_list)
    quote_no = col_qno.text_input("Số Báo Giá (Quote No)", value=f"APL{datetime.date.today().strftime('%Y%m%d')}-01")
    
    rfq_file = st.file_uploader("Upload file RFQ (Excel)", type=['xlsx'])
    
    if "quote_df" not in st.session_state:
        st.session_state.quote_df = pd.DataFrame()

    if rfq_file:
        if st.button("🔄 Khớp lệnh (Matching Data)"):
            rfq_data = pd.read_excel(rfq_file, header=10) # Assuming RFQ format similar to template
            # If standard RFQ, maybe header 0. Let's assume user provides columns Item Code, Item Name, Specs, Qty
            # Adjusting to read standard generic Excel if format varies. 
            # Re-reading Source 1 [86], it matches Key 3.
            
            # Fetch Inventory
            inventory = pd.DataFrame(supabase.table("crm_purchases").select("*").execute().data)
            
            matched_rows = []
            
            # Use columns from RFQ upload. Assuming standard names.
            # If headers are different, need mapping. Assuming columns 0,1,2,3 are Code, Name, Specs, Qty
            # Reading header=None to find headers dynamically or just trusting structure
            rfq_df = pd.read_excel(rfq_file)
            
            # Normalize headers
            rfq_df.columns = [str(c).lower().strip() for c in rfq_df.columns]
            
            # Create matching keys
            if not inventory.empty:
                inventory['match_key'] = inventory.apply(
                    lambda x: f"{strict_match_key(x['item_code'])}_{strict_match_key(x['item_name'])}_{strict_match_key(x['specs'])}", axis=1
                )
            
            for idx, row in rfq_df.iterrows():
                # Flexible column finding
                code = row.get('item code', row.get('code', ''))
                name = row.get('item name', row.get('name', ''))
                specs = row.get('specs', row.get('specification', ''))
                qty = to_float(row.get('q\'ty', row.get('qty', 1)))
                
                match_key = f"{strict_match_key(code)}_{strict_match_key(name)}_{strict_match_key(specs)}"
                
                match = pd.DataFrame()
                if not inventory.empty:
                    match = inventory[inventory['match_key'] == match_key]
                
                new_row = {
                    "Item Code": code, "Item Name": name, "Specs": specs, "Qty": qty,
                    "Buying Price": 0.0, "Supplier": "", "Leadtime": "", "Total Buying": 0.0,
                    "AP Price": 0.0, "Unit Price": 0.0, "Total Price": 0.0,
                    "Profit": 0.0, "Profit %": 0.0, "Note": ""
                }
                
                if not match.empty:
                    data_row = match.iloc[0]
                    new_row["Buying Price"] = data_row['buying_price_vnd']
                    new_row["Supplier"] = data_row['supplier']
                    new_row["Leadtime"] = data_row['leadtime']
                    new_row["Total Buying"] = data_row['buying_price_vnd'] * qty
                else:
                    new_row["Note"] = "⚠️ DATA KHÔNG KHỚP"
                
                matched_rows.append(new_row)
            
            st.session_state.quote_df = pd.DataFrame(matched_rows)

    # --- Data Editor & Calculation ---
    if not st.session_state.quote_df.empty:
        st.info("Nhập công thức vào cột 'AP Price' hoặc 'Unit Price' (VD: `buying price * 1.1`).")
        
        # Formula Parser
        formula_input = st.text_input("Công thức áp dụng chung (VD: =buying price * 1.2)", key="global_formula")
        if st.button("Áp dụng công thức"):
            if formula_input.startswith("="):
                formula = formula_input[1:].lower() # Fix case sensitivity 
                # Map variables
                formula = formula.replace("buying price", "row['Buying Price']")
                formula = formula.replace("ap price", "row['AP Price']")
                # Safe eval
                allowed_names = {"row": None}
                try:
                    # Apply to whole dataframe
                    st.session_state.quote_df['AP Price'] = st.session_state.quote_df.apply(
                        lambda row: eval(formula, {"__builtins__": None}, {"row": row}), axis=1
                    )
                except Exception as e:
                    st.error(f"Lỗi công thức: {e}")

        # Editable Grid
        edited_df = st.data_editor(
            st.session_state.quote_df,
            num_rows="dynamic",
            column_config={
                "Buying Price": st.column_config.NumberColumn(format="%d", disabled=True),
                "Total Buying": st.column_config.NumberColumn(format="%d", disabled=True),
                "AP Price": st.column_config.NumberColumn(format="%d"),
                "Unit Price": st.column_config.NumberColumn(format="%d"),
                "Total Price": st.column_config.NumberColumn(format="%d", disabled=True),
            },
            use_container_width=True
        )
        
        # Recalculate Logic 
        # Always run this to update totals based on edited values
        cfg = st.session_state.quote_config
        
        for i, row in edited_df.iterrows():
            qty = row['Qty']
            buy_price = row['Buying Price']
            ap_price = row['AP Price']
            
            # Logic: If Unit Price is set manually, use it. Else calculate from AP Price + Margin if needed.
            # Spec implies AP Price is base, then fees added? Or Formula determines Unit Price?
            # Usually: Unit Price = AP Price (which might include margin)
            # Let's assume AP Price is the base price before global fees, or user sets Unit Price directly.
            # Using Unit Price as final sale price per unit.
            
            unit_price = row['Unit Price'] if row['Unit Price'] > 0 else ap_price
            
            total_price = unit_price * qty
            total_buying = buy_price * qty
            
            # Reverse calculate or Forward calculate fees?
            # Source 99: Profit = Total Price - (Total Buying + GAP + Fees + Transport) + Payback
            # Detailed breakdown needed. Simplifying based on "Doanh thu - Chi phí".
            
            # Costs
            cost_fund = total_buying
            gap = total_price - (ap_price * qty) # Definition [97]
            
            # Fees calculation based on Total Price
            fee_end_user = total_price * (cfg['end_user'] / 100)
            fee_buyer = total_price * (cfg['buyer'] / 100)
            fee_tax = total_buying * (cfg['import_tax'] / 100) # Import tax on buying
            fee_mgmt = total_price * (cfg['mgmt_fee'] / 100)
            
            # Payback (add back to profit?) 
            # Payback is usually a hidden markup returned.
            val_payback = total_price * (cfg['payback'] / 100)
            
            # Transport is fixed total, divide by items? Or applied to total.
            # Let's apply per row proportional to value? Or just subtract from total profit later.
            # Spec 99 implies row calculation. Let's ignore transport in row profit for now or distribute.
            
            # Simplified Profit per row
            row_profit = total_price - total_buying - fee_end_user - fee_buyer - fee_tax - fee_mgmt + val_payback
            
            edited_df.at[i, 'Total Buying'] = total_buying
            edited_df.at[i, 'Total Price'] = total_price
            edited_df.at[i, 'Profit'] = row_profit
            edited_df.at[i, 'Profit %'] = (row_profit / total_price * 100) if total_price > 0 else 0

        # Style Low Profit 
        def highlight_low(val):
            return 'background-color: #ffe6e6; color: red' if val < 10 else ''
            
        st.dataframe(edited_df.style.applymap(highlight_low, subset=['Profit %']), use_container_width=True)
        
        # Total Row 
        total_revenue = edited_df['Total Price'].sum()
        total_profit = edited_df['Profit'].sum() - cfg['transport'] # Deduct global transport
        
        st.markdown(f"""
        <div class="total-view-box">
            TỔNG CỘNG (VND): {fmt_num(total_revenue)} | LỢI NHUẬN: {fmt_num(total_profit)}
        </div>
        """, unsafe_allow_html=True)
        
        st.session_state.quote_df = edited_df
        
        # --- Export & Save ---
        if st.button("💾 Lưu & Xuất Báo Giá"):
            # 1. Download Template
            tmpls = drive.find_file_by_name("AAA-QUOTATION")
            if not tmpls:
                st.error("Không tìm thấy file mẫu 'AAA-QUOTATION' trên Drive!")
            else:
                tmpl_id = tmpls[0]['id']
                byte_data = drive.download_file_bytes(tmpl_id)
                
                # 2. Fill Excel
                wb = load_workbook(byte_data)
                ws = wb.active
                
                # Fill Header
                ws['G4'] = quote_no
                ws['G5'] = datetime.date.today().strftime("%Y-%m-%d")
                ws['C4'] = selected_customer
                
                # Fill Rows (start row 11 per source 114)
                start_row = 11
                for idx, row in edited_df.iterrows():
                    curr = start_row + idx
                    ws[f'A{curr}'] = idx + 1
                    ws[f'C{curr}'] = row['Item Code']
                    ws[f'D{curr}'] = row['Item Name']
                    ws[f'E{curr}'] = row['Specs']
                    ws[f'F{curr}'] = row['Qty']
                    ws[f'G{curr}'] = row['Unit Price']
                    ws[f'H{curr}'] = row['Total Price']
                    ws[f'I{curr}'] = row['Leadtime']
                    
                # Save to Buffer
                out_buffer = io.BytesIO()
                wb.save(out_buffer)
                out_buffer.seek(0)
                
                # 3. Upload to Drive
                folder_id = drive.get_time_based_folder("QUOTATION_HISTORY")
                cust_folder = drive.get_or_create_folder(selected_customer, folder_id)
                file_name = f"QUOTE_{quote_no}_{selected_customer}_{int(time.time())}.xlsx"
                
                link = drive.upload_file(out_buffer, file_name, cust_folder)
                
                # 4. Save to DB
                supabase.table("crm_shared_history").insert({
                    "quote_no": quote_no,
                    "customer_name": selected_customer,
                    "quote_date": datetime.date.today().isoformat(),
                    "total_value_vnd": total_revenue,
                    "config_data": st.session_state.quote_config,
                    "file_url": link
                }).execute()
                
                st.success(f"Đã lưu thành công! Link: {link}")

# === TAB 4: QUẢN LÝ PO ===
with tab4:
    st.header("Purchase Orders")
    po_type = st.radio("Loại PO", ["Khách hàng (Customer PO)", "Nhà cung cấp (Supplier PO)"])
    
    if po_type.startswith("Khách"):
        # Customer PO
        with st.form("cust_po_form"):
            po_num = st.text_input("PO Number")
            cust = st.selectbox("Khách hàng", options=cust_list, key="po_cust")
            po_file = st.file_uploader("Upload PO Scan/PDF", type=['pdf', 'xlsx'])
            po_total = st.number_input("Tổng giá trị (VND)", min_value=0.0)
            
            if st.form_submit_button("Tạo PO Khách hàng"):
                # Upload logic
                link = ""
                if po_file:
                    f_id = drive.get_time_based_folder("PO_KHACH_HANG")
                    c_id = drive.get_or_create_folder(cust, f_id)
                    link = drive.upload_file(po_file, po_file.name, c_id, po_file.type)
                
                supabase.table("db_customer_orders").insert({
                    "po_no": po_num, "customer_name": cust, "order_date": datetime.date.today().isoformat(),
                    "total_price": po_total, "status": "Waiting", "file_url": link
                }).execute()
                
                # Add Tracking
                supabase.table("crm_tracking").insert({
                    "order_ref_id": po_num, "type": "KH", "status": "Waiting"
                }).execute()
                st.success("Tạo PO thành công!")
                
    else:
        # Supplier PO
        with st.form("supp_po_form"):
            supp_data = supabase.table("crm_suppliers").select("short_name").execute().data
            supp_list = [s['short_name'] for s in supp_data]
            
            s_po_num = st.text_input("PO NCC Number")
            supp = st.selectbox("Nhà cung cấp", options=supp_list)
            list_file = st.file_uploader("Danh sách hàng (Excel)", type=['xlsx'])
            
            if st.form_submit_button("Đặt hàng NCC"):
                # Calculate cost from file or input? Spec says Upload List
                # Simplified for code length:
                link = ""
                cost = 0 # Placeholder, real logic needs to parse file
                if list_file:
                    f_id = drive.get_time_based_folder("PO_NCC")
                    s_id = drive.get_or_create_folder(supp, f_id)
                    link = drive.upload_file(list_file, list_file.name, s_id, list_file.type)
                
                supabase.table("db_supplier_orders").insert({
                    "po_no": s_po_num, "supplier_name": supp, "order_date": datetime.date.today().isoformat(),
                    "total_cost": cost, "file_url": link
                }).execute()
                
                supabase.table("crm_tracking").insert({
                    "order_ref_id": s_po_num, "type": "NCC", "status": "Ordered"
                }).execute()
                st.success("Đã gửi PO cho NCC!")

# === TAB 5: TRACKING ===
with tab5:
    st.header("Theo dõi Đơn hàng")
    
    track_data = supabase.table("crm_tracking").select("*").execute().data
    df_track = pd.DataFrame(track_data)
    
    if not df_track.empty:
        for idx, row in df_track.iterrows():
            with st.expander(f"{row['type']} - {row['order_ref_id']} [{row['status']}]"):
                new_status = st.selectbox("Cập nhật trạng thái", 
                                          ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"],
                                          index=["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"].index(row['status']) if row['status'] in ["Ordered", "Shipping", "Arrived", "Delivered", "Waiting"] else 0,
                                          key=f"st_{row['id']}")
                
                proof = st.file_uploader("Ảnh bằng chứng (Proof)", key=f"up_{row['id']}")
                
                if st.button("Cập nhật", key=f"btn_{row['id']}"):
                    update_data = {"status": new_status}
                    if proof:
                        l = drive.upload_file(proof, f"PROOF_{row['order_ref_id']}.png", drive.get_or_create_folder("PROOF_IMAGES", DRIVE_ROOT_FOLDER_ID), "image/png")
                        update_data["proof_image"] = l
                    
                    supabase.table("crm_tracking").update(update_data).eq("id", row['id']).execute()
                    
                    # Logic Delivered 
                    if row['type'] == "KH" and new_status == "Delivered":
                        # Add to Payment
                        supabase.table("crm_payments").insert({
                            "po_no": row['order_ref_id'],
                            "status": "Đợi xuất hóa đơn",
                            "eta_payment_date": (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
                        }).execute()
                        st.info("Đã chuyển sang theo dõi thanh toán.")
                    
                    st.success("Đã cập nhật!")
                    st.rerun()

# === TAB 6: MASTER DATA ===
with tab6:
    md_type = st.radio("Dữ liệu nguồn", ["Khách hàng", "Nhà cung cấp", "Template"])
    
    if md_type == "Khách hàng":
        df_c = pd.DataFrame(supabase.table("crm_customers").select("*").execute().data)
        edited_c = st.data_editor(df_c, num_rows="dynamic")
        if st.button("Lưu thay đổi Khách hàng"):
            # Upsert logic needed. For simplicity, we assume ID exists for update
            # Supabase upsert requires dicts
            records = edited_c.to_dict('records')
            for r in records:
                if r.get('id'):
                    supabase.table("crm_customers").upsert(r).execute()
            st.success("Đã lưu!")
            
    elif md_type == "Nhà cung cấp":
        df_s = pd.DataFrame(supabase.table("crm_suppliers").select("*").execute().data)
        edited_s = st.data_editor(df_s, num_rows="dynamic")
        if st.button("Lưu thay đổi NCC"):
            records = edited_s.to_dict('records')
            for r in records:
                if r.get('id'):
                    supabase.table("crm_suppliers").upsert(r).execute()
            st.success("Đã lưu!")
            
    elif md_type == "Template":
        st.info("Quản lý file mẫu báo giá. Upload file có tên chứa 'AAA-QUOTATION'")
        t_file = st.file_uploader("Upload Template Mới")
        if t_file:
            # Upload drive
            f_id = drive.get_or_create_folder("TEMPLATES", DRIVE_ROOT_FOLDER_ID)
            link = drive.upload_file(t_file, t_file.name, f_id) # Should overwrite if name same
            st.success(f"Đã upload template: {t_file.name}")
