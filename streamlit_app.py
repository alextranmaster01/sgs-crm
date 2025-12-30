import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime, date
import time
import xlsxwriter
from io import BytesIO

# =============================================================================
# 1. CẤU HÌNH HỆ THỐNG (SYSTEM CONFIG)
# =============================================================================
st.set_page_config(
    page_title="CRM SYSTEM PRO - HOTWIN VIETNAM",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load Secrets
try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["key"]
    GOOGLE_CLIENT_ID = st.secrets["google_auth"]["client_id"]
    GOOGLE_CLIENT_SECRET = st.secrets["google_auth"]["client_secret"]
    GOOGLE_REFRESH_TOKEN = st.secrets["google_auth"]["refresh_token"]
except Exception as e:
    st.error(f"⚠️ LỖI CẤU HÌNH (secrets.toml): {e}")
    st.stop()

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

def get_drive_service():
    creds = Credentials(
        None, refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET
    )
    return build('drive', 'v3', credentials=creds)

# =============================================================================
# 2. GIAO DIỆN & STYLE (COLORFUL UI TỪ V4800)
# =============================================================================
def load_custom_css():
    st.markdown("""
    <style>
        .stApp { background-color: #f0f4f8; }
        /* Sidebar */
        section[data-testid="stSidebar"] { background-color: #2c3e50; color: white; }
        .css-17lntkn { color: white; }
        
        /* Headers */
        h1 { color: #2c3e50; font-family: 'Arial', sans-serif; font-weight: bold; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
        h2 { color: #e67e22; }
        h3 { color: #16a085; }
        
        /* Cards */
        div.stMetric { background-color: #ffffff; border: 1px solid #dcdcdc; padding: 10px; border-radius: 5px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
        
        /* Tabs */
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #ecf0f1; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
        .stTabs [aria-selected="true"] { background-color: #3498db; color: white; }
        
        /* Tables */
        div[data-testid="stDataFrame"] { background-color: white; border-radius: 10px; padding: 10px; }
    </style>
    """, unsafe_allow_html=True)

load_custom_css()

# =============================================================================
# 3. CORE FUNCTIONS (DATABASE & DRIVE)
# =============================================================================
def fetch_data(table):
    res = supabase.table(table).select("*").execute()
    return pd.DataFrame(res.data)

def upload_image_drive(file_obj):
    try:
        service = get_drive_service()
        folder_name = "CRM_IMAGES"
        q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        files = service.files().list(q=q).execute().get('files', [])
        folder_id = files[0]['id'] if files else service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}).execute()['id']
        
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
        file_meta = {'name': file_obj.name, 'parents': [folder_id]}
        file = service.files().create(body=file_meta, media_body=media, fields='id, webContentLink').execute()
        service.permissions().create(fileId=file['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
        return file.get('webContentLink')
    except: return None

# =============================================================================
# 4. EXCEL ENGINE (LOGIC XUẤT BÁO GIÁ CHUẨN FORM)
# =============================================================================
def generate_excel(quote_info, items_df, customer):
    output = BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = wb.add_worksheet("Báo Giá")
    
    # Formats
    fmt_title = wb.add_format({'bold': True, 'font_size': 18, 'color': 'red', 'align': 'center', 'valign': 'vcenter'})
    fmt_header = wb.add_format({'bold': True, 'bg_color': '#2980b9', 'color': 'white', 'border': 1, 'align': 'center'})
    fmt_cell = wb.add_format({'border': 1, 'valign': 'vcenter'})
    fmt_num = wb.add_format({'border': 1, 'num_format': '#,##0', 'align': 'right'})
    
    # Header Info
    ws.merge_range('A1:F1', "CÔNG TY TNHH ĐIỆN TỬ HOTWIN VIỆT NAM", wb.add_format({'bold': True, 'font_size': 14, 'color': '#2c3e50'}))
    ws.write('A2', "Địa chỉ: KCN Vsip, Bắc Ninh | Tel: 0123.456.789")
    
    ws.merge_range('A4:H4', "BẢNG BÁO GIÁ / QUOTATION", fmt_title)
    
    # Customer Info
    ws.write('A6', f"Kính gửi: {customer.get('ten_cong_ty', '')}")
    ws.write('A7', f"Người LH: {customer.get('nguoi_lien_he', '')} - SĐT: {customer.get('so_dien_thoai', '')}")
    ws.write('F6', f"Số BG: {quote_info['so_bao_gia']}")
    ws.write('F7', f"Ngày: {pd.to_datetime(quote_info['ngay_bao_gia']).strftime('%d/%m/%Y')}")

    # Table Header
    headers = ["STT", "Mã Hàng", "Tên Hàng / Mô Tả", "ĐVT", "SL", "Đơn Giá", "Thành Tiền", "Ghi Chú"]
    ws.set_column('C:C', 30)
    for i, h in enumerate(headers):
        ws.write(9, i, h, fmt_header)

    # Table Data
    row = 10
    total = 0
    for idx, item in items_df.iterrows():
        ws.write(row, 0, idx+1, fmt_cell)
        ws.write(row, 1, item.get('ma_hang', ''), fmt_cell)
        ws.write(row, 2, item.get('dien_giai_tuy_chinh', item.get('ten_hang', '')), fmt_cell)
        ws.write(row, 3, item.get('don_vi', ''), fmt_cell)
        ws.write(row, 4, item.get('so_luong', 0), wb.add_format({'border': 1, 'align': 'center'}))
        ws.write(row, 5, item.get('don_gia_ban', 0), fmt_num)
        ws.write(row, 6, item.get('thanh_tien', 0), fmt_num)
        ws.write(row, 7, "", fmt_cell)
        total += item.get('thanh_tien', 0)
        row += 1

    # Footer
    row += 1
    ws.write(row, 5, "TỔNG CỘNG:", wb.add_format({'bold': True, 'align': 'right'}))
    ws.write(row, 6, total, fmt_num)
    row += 1
    ws.write(row, 5, "VAT (10%):", wb.add_format({'bold': True, 'align': 'right'}))
    ws.write(row, 6, total*0.1, fmt_num)
    row += 1
    ws.write(row, 5, "THANH TOÁN:", wb.add_format({'bold': True, 'align': 'right', 'color': 'red'}))
    ws.write(row, 6, total*1.1, fmt_num)

    wb.close()
    output.seek(0)
    return output

# =============================================================================
# 5. CÁC MODULE CHỨC NĂNG (6 TABS)
# =============================================================================

# --- TAB 2: KHO HÀNG ---
def module_products():
    st.markdown("## 📦 QUẢN LÝ KHO HÀNG")
    tab1, tab2 = st.tabs(["Danh Sách Sản Phẩm", "Thêm Mới / Import"])
    
    with tab1:
        df = fetch_data("products")
        if not df.empty:
            st.dataframe(df[['ma_hang', 'ten_hang_vn', 'gia_mua', 'nha_cung_cap', 'anh_minh_hoa']], 
                         column_config={"anh_minh_hoa": st.column_config.ImageColumn("Ảnh"), "gia_mua": st.column_config.NumberColumn("Giá Mua", format="%d")},
                         use_container_width=True)
        else: st.info("Kho hàng trống.")
        
    with tab2:
        with st.form("add_prod"):
            c1, c2 = st.columns(2)
            ma = c1.text_input("Mã Hàng *")
            ten = c2.text_input("Tên Hàng")
            gia = c1.number_input("Giá Mua", min_value=0.0)
            ncc = c2.text_input("Nhà Cung Cấp")
            img = st.file_uploader("Ảnh SP")
            if st.form_submit_button("Lưu"):
                url = upload_image_drive(img) if img else ""
                supabase.table("products").insert({"ma_hang": ma, "ten_hang_vn": ten, "gia_mua": gia, "nha_cung_cap": ncc, "anh_minh_hoa": url}).execute()
                st.success("Đã thêm!")
                st.rerun()

# --- TAB 3: KHÁCH HÀNG ---
def module_customers():
    st.markdown("## 👥 QUẢN LÝ KHÁCH HÀNG")
    with st.expander("➕ Thêm Khách Hàng"):
        with st.form("add_cust"):
            c1, c2 = st.columns(2)
            ma = c1.text_input("Mã KH *")
            ten = c2.text_input("Tên Công Ty")
            lh = c1.text_input("Người LH")
            dt = c2.text_input("SĐT")
            dc = st.text_input("Địa chỉ")
            if st.form_submit_button("Lưu"):
                supabase.table("customers").insert({"ma_khach_hang": ma, "ten_cong_ty": ten, "nguoi_lien_he": lh, "so_dien_thoai": dt, "dia_chi": dc}).execute()
                st.success("Đã thêm!")
                st.rerun()
    
    df = fetch_data("customers")
    if not df.empty:
        st.dataframe(df, use_container_width=True)

# --- TAB 4: NHÀ CUNG CẤP (NEW) ---
def module_suppliers():
    st.markdown("## 🏭 QUẢN LÝ NHÀ CUNG CẤP")
    
    tab1, tab2 = st.tabs(["Danh Sách NCC", "Thêm Mới NCC"])
    
    with tab1:
        df = fetch_data("suppliers")
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Chưa có dữ liệu nhà cung cấp.")
            
    with tab2:
        with st.form("add_sup"):
            c1, c2 = st.columns(2)
            ma = c1.text_input("Mã NCC *")
            ten = c2.text_input("Tên NCC")
            lh = c1.text_input("Người LH")
            dt = c2.text_input("SĐT")
            email = st.text_input("Email")
            if st.form_submit_button("Lưu Nhà Cung Cấp"):
                supabase.table("suppliers").insert({"ma_nha_cung_cap": ma, "ten_nha_cung_cap": ten, "nguoi_lien_he": lh, "so_dien_thoai": dt, "email": email}).execute()
                st.success("Đã thêm NCC!")
                st.rerun()

# --- TAB 5: TẠO BÁO GIÁ ---
def module_quotation():
    st.markdown("## 📝 TẠO BÁO GIÁ MỚI")
    if 'cart' not in st.session_state: st.session_state.cart = []
    
    # Select Customer
    custs = fetch_data("customers")
    cust_opts = [f"{r['ma_khach_hang']} - {r['ten_cong_ty']}" for i, r in custs.iterrows()] if not custs.empty else []
    sel_cust = st.selectbox("Chọn Khách Hàng:", [""] + cust_opts)
    
    st.divider()
    
    # Add Items
    c1, c2, c3 = st.columns([2, 1, 1])
    prods = fetch_data("products")
    prod_opts = [f"{r['ma_hang']} | {r['ten_hang_vn']}" for i, r in prods.iterrows()] if not prods.empty else []
    sel_prod = c1.selectbox("Chọn SP:", [""] + prod_opts)
    
    if sel_prod:
        ma_hang = sel_prod.split(" | ")[0]
        p_data = prods[prods['ma_hang'] == ma_hang].iloc[0]
        gia_mua = float(p_data['gia_mua'] or 0)
        
        qty = c2.number_input("Số lượng", 1, 1000, 1)
        margin = c3.number_input("Margin (%)", 0.0, 100.0, 20.0)
        gia_ban = gia_mua * (1 + margin/100)
        
        st.info(f"Giá mua: {gia_mua:,.0f} -> Giá bán đề xuất: {gia_ban:,.0f}")
        
        if st.button("➕ Thêm vào List"):
            st.session_state.cart.append({
                "ma_hang": ma_hang, "ten_hang": p_data['ten_hang_vn'], "don_vi": p_data['don_vi'],
                "so_luong": qty, "don_gia_ban": gia_ban, "thanh_tien": qty*gia_ban
            })

    # Cart Review
    if st.session_state.cart:
        df_cart = pd.DataFrame(st.session_state.cart)
        st.dataframe(df_cart, use_container_width=True)
        
        if st.button("💾 LƯU BÁO GIÁ"):
            try:
                # Save Header
                ma_kh = sel_cust.split(" - ")[0] if sel_cust else ""
                so_bg = f"BG-{int(time.time())}"
                total = df_cart['thanh_tien'].sum()
                
                supabase.table("quotations").insert({
                    "so_bao_gia": so_bg, "ma_khach_hang": ma_kh, 
                    "ngay_bao_gia": datetime.now().isoformat(), "tong_tien_sau_vat": total*1.1
                }).execute()
                
                # Save Items
                items = []
                for i, r in df_cart.iterrows():
                    items.append({
                        "so_bao_gia": so_bg, "ma_hang": r['ma_hang'], 
                        "so_luong": r['so_luong'], "don_gia_ban": r['don_gia_ban'], "thanh_tien": r['thanh_tien']
                    })
                supabase.table("quotation_items").insert(items).execute()
                
                st.success(f"Đã lưu: {so_bg}")
                st.session_state.cart = []
                st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

# --- TAB 6: QUẢN LÝ ĐƠN HÀNG (HISTORY) ---
def module_history():
    st.markdown("## 🗂️ LỊCH SỬ BÁO GIÁ")
    
    quotes = fetch_data("quotations")
    if not quotes.empty:
        # Show List
        st.dataframe(quotes[['so_bao_gia', 'ngay_bao_gia', 'ma_khach_hang', 'tong_tien_sau_vat']], use_container_width=True)
        
        # Detail View & Export
        st.divider()
        st.subheader("Chi tiết & Xuất lại Excel")
        sel_bg = st.selectbox("Chọn Số Báo Giá để xem:", quotes['so_bao_gia'].unique())
        
        if sel_bg:
            # Get Items
            items = supabase.table("quotation_items").select("*").eq("so_bao_gia", sel_bg).execute()
            df_items = pd.DataFrame(items.data)
            st.dataframe(df_items)
            
            # Get Info for Excel
            q_info = quotes[quotes['so_bao_gia'] == sel_bg].iloc[0]
            cust_info = supabase.table("customers").select("*").eq("ma_khach_hang", q_info['ma_khach_hang']).execute()
            c_data = cust_info.data[0] if cust_info.data else {}
            
            # Export Button
            excel_data = generate_excel(q_info, df_items, c_data)
            st.download_button("📥 Tải File Excel", excel_data, f"{sel_bg}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Chưa có lịch sử báo giá.")

# =============================================================================
# 6. MAIN APP NAVIGATOR
# =============================================================================
def main():
    with st.sidebar:
        st.title("HOTWIN CRM")
        st.write("---")
        menu = st.radio("CHỨC NĂNG", [
            "🏠 Dashboard", 
            "📦 Kho Hàng (Products)", 
            "👥 Khách Hàng (Customers)", 
            "🏭 Nhà Cung Cấp (Suppliers)", 
            "📝 Tạo Báo Giá (Quotations)",
            "🗂️ Quản Lý Đơn (Orders)"
        ])
    
    if menu == "🏠 Dashboard":
        st.header("TỔNG QUAN HỆ THỐNG")
        try:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sản Phẩm", supabase.table("products").select("id", count="exact").execute().count)
            c2.metric("Khách Hàng", supabase.table("customers").select("id", count="exact").execute().count)
            c3.metric("Nhà Cung Cấp", supabase.table("suppliers").select("id", count="exact").execute().count)
            c4.metric("Đơn Báo Giá", supabase.table("quotations").select("id", count="exact").execute().count)
        except: st.error("Chưa kết nối DB")
        
    elif menu == "📦 Kho Hàng (Products)": module_products()
    elif menu == "👥 Khách Hàng (Customers)": module_customers()
    elif menu == "🏭 Nhà Cung Cấp (Suppliers)": module_suppliers()
    elif menu == "📝 Tạo Báo Giá (Quotations)": module_quotation()
    elif menu == "🗂️ Quản Lý Đơn (Orders)": module_history()

if __name__ == "__main__":
    main()
