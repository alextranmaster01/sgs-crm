# =============================================================================
# FILE: utils.py
# NỘI DUNG: IMPORT THƯ VIỆN, CẤU HÌNH, KẾT NỐI DB & HÀM HỖ TRỢ
# =============================================================================
import streamlit as st
import pandas as pd
import datetime
from datetime import datetime, timedelta
import re
import io
import time
import json
import mimetypes
import numpy as np

# --- CẤU HÌNH TRANG & CSS ---
APP_VERSION = "V6045 - QUOTE FORMULA & EDITING FIXED"

def init_page_config():
    st.set_page_config(page_title=f"CRM {APP_VERSION}", layout="wide", page_icon="💎")
    st.markdown("""
        <style>
        button[data-baseweb="tab"] div p { font-size: 18px !important; font-weight: 700 !important; }
        .card-3d { border-radius: 12px; padding: 20px; color: white; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.2); margin-bottom: 10px; }
        .bg-sales { background: linear-gradient(135deg, #00b09b, #96c93d); }
        .bg-cost { background: linear-gradient(135deg, #ff5f6d, #ffc371); }
        .bg-profit { background: linear-gradient(135deg, #f83600, #f9d423); }
        [data-testid="stDataFrame"] > div { max-height: 750px; }
        .highlight-low { background-color: #ffcccc !important; color: red !important; font-weight: bold; }
        
        div.stButton > button { 
            width: 100%; 
            border-radius: 5px; 
            font-weight: bold; 
            background-color: #262730; 
            color: #ffffff; 
            border: 1px solid #4e4e4e;
        }
        div.stButton > button:hover {
            background-color: #444444;
            color: #ffffff;
            border-color: #ffffff;
        }
        
        .total-view {
            font-size: 20px;
            font-weight: bold;
            color: #00FF00; 
            background-color: #262730;
            padding: 10px;
            border-radius: 8px;
            text-align: right;
            margin-top: 10px;
            border: 1px solid #4e4e4e;
        }
        </style>""", unsafe_allow_html=True)

# --- THƯ VIỆN & KẾT NỐI ---
try:
    from supabase import create_client, Client
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    from openpyxl import load_workbook, Workbook
    from openpyxl.styles import Border, Side, Alignment, Font
except ImportError:
    st.error("⚠️ Thiếu thư viện. Vui lòng chạy lệnh: pip install streamlit pandas supabase google-api-python-client google-auth-oauthlib openpyxl")
    st.stop()

# Biến global cho kết nối (để các module khác import)
supabase = None
OAUTH_INFO = None
ROOT_FOLDER_ID = "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa" # Default

def init_connections():
    global supabase, OAUTH_INFO, ROOT_FOLDER_ID
    try:
        if "supabase" not in st.secrets or "google_oauth" not in st.secrets:
            st.error("⚠️ Chưa cấu hình secrets.toml. Vui lòng kiểm tra lại file secrets.")
            st.stop()

        SUPABASE_URL = st.secrets["supabase"]["url"]
        SUPABASE_KEY = st.secrets["supabase"]["key"]
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        OAUTH_INFO = st.secrets["google_oauth"]
        ROOT_FOLDER_ID = OAUTH_INFO.get("root_folder_id", "1GLhnSK7Bz7LbTC-Q7aPt_Itmutni5Rqa")
        return supabase
    except Exception as e:
        st.error(f"⚠️ Lỗi Config: {e}"); st.stop()

# --- HÀM HỖ TRỢ (UTILS) ---
def get_drive_service():
    try:
        creds = Credentials(None, refresh_token=OAUTH_INFO["refresh_token"], 
                            token_uri="https://oauth2.googleapis.com/token", 
                            client_id=OAUTH_INFO["client_id"], client_secret=OAUTH_INFO["client_secret"])
        return build('drive', 'v3', credentials=creds)
    except: return None

def get_or_create_folder_hierarchy(srv, path_list, parent_id):
    current_parent_id = parent_id
    for folder_name in path_list:
        q = f"'{current_parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = srv.files().list(q=q, fields="files(id)").execute().get('files', [])
        
        if results:
            current_parent_id = results[0]['id']
        else:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [current_parent_id]
            }
            folder = srv.files().create(body=file_metadata, fields='id').execute()
            current_parent_id = folder.get('id')
            try: srv.permissions().create(fileId=current_parent_id, body={'role': 'reader', 'type': 'anyone'}).execute()
            except: pass
            
    return current_parent_id

def upload_to_drive_structured(file_obj, path_list, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, path_list, ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        return folder_link, file_id
    except Exception as e: 
        st.error(f"Lỗi upload Drive: {e}")
        return "", ""

def upload_to_drive_simple(file_obj, sub_folder, file_name):
    srv = get_drive_service()
    if not srv: return "", ""
    try:
        folder_id = get_or_create_folder_hierarchy(srv, [sub_folder], ROOT_FOLDER_ID)
        media = MediaIoBaseUpload(file_obj, mimetype=mimetypes.guess_type(file_name)[0] or 'application/octet-stream', resumable=True)
        file_meta = {'name': file_name, 'parents': [folder_id]}
        q_ex = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
        exists = srv.files().list(q=q_ex, fields="files(id)").execute().get('files', [])
        if exists:
            file_id = exists[0]['id']
            srv.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_id = srv.files().create(body=file_meta, media_body=media, fields='id').execute()['id']
        try: srv.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()
        except: pass
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w200", file_id
    except: return "", ""

def search_file_in_drive_by_name(name_contains):
    srv = get_drive_service()
    if not srv: return None, None, None
    try:
        q = f"name contains '{name_contains}' and trashed=false"
        results = srv.files().list(q=q, fields="files(id, name, parents)").execute().get('files', [])
        if results:
            return results[0]['id'], results[0]['name'], (results[0]['parents'][0] if 'parents' in results[0] else None)
        return None, None, None
    except: return None, None, None

def download_from_drive(file_id):
    srv = get_drive_service()
    if not srv: return None
    try:
        request = srv.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        fh.seek(0) 
        return fh
    except: return None

def safe_str(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', 'nat', '']: return ""
    return s

def to_float(val):
    if val is None: return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace(",", "").replace("¥", "").replace("$", "").replace("RMB", "").replace("VND", "").replace(" ", "").upper()
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
        return float(nums[0]) if nums else 0.0
    except: return 0.0

def fmt_num(x): 
    try:
        if x is None: return "0"
        val = float(x)
        if val.is_integer(): return "{:,.0f}".format(val)
        else:
            s = "{:,.3f}".format(val)
            return s.rstrip('0').rstrip('.')
    except: return "0"

def fmt_float_1(x):
    try:
        if x is None: return "0.0"
        val = float(x)
        return "{:,.1f}".format(val)
    except: return "0.0"

def clean_key(s): return safe_str(s).lower()

def strict_match_key(val):
    if val is None: return ""
    s = str(val).lower()
    return re.sub(r'\s+', '', s)

def calc_eta(order_date_str, leadtime_val):
    try:
        if isinstance(order_date_str, datetime): dt_order = order_date_str
        else:
            try: dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
            except: dt_order = datetime.now()
        lt_str = str(leadtime_val)
        nums = re.findall(r'\d+', lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except: return ""

def load_data(table, order_by="id", ascending=True):
    try:
        query = supabase.table(table).select("*")
        if table == "crm_purchases": query = query.order("row_order", desc=False)
        else: query = query.order(order_by, desc=not ascending)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if table != "crm_tracking" and table != "crm_payments" and not df.empty and 'id' in df.columns: 
            df = df.drop(columns=['id'])
        return df
    except: return pd.DataFrame()

def recalculate_quote_logic(df, params):
    cols_to_num = ["Q'ty", "Buying price(VND)", "Buying price(RMB)", "AP price(VND)", "Unit price(VND)", 
                   "Exchange rate", "End user(%)", "Buyer(%)", "Import tax(%)", "VAT", "Transportation", 
                   "Management fee(%)", "Payback(%)"]
    
    for c in cols_to_num:
        if c in df.columns: df[c] = df[c].apply(to_float)
    
    df["Total buying price(VND)"] = df["Buying price(VND)"] * df["Q'ty"]
    df["Total buying price(rmb)"] = df["Buying price(RMB)"] * df["Q'ty"]
    df["AP total price(VND)"] = df["AP price(VND)"] * df["Q'ty"]
    df["Total price(VND)"] = df["Unit price(VND)"] * df["Q'ty"]
    df["GAP"] = df["Total price(VND)"] - df["AP total price(VND)"]

    gap_positive = df["GAP"].apply(lambda x: x * 0.6 if x > 0 else 0)
    
    cost_ops = (gap_positive + 
                df["End user(%)"] + 
                df["Buyer(%)"] + 
                df["Import tax(%)"] + 
                df["VAT"] + 
                df["Management fee(%)"] + 
                df["Transportation"])
    
    df["Profit(VND)"] = df["Total price(VND)"] - df["Total buying price(VND)"] - cost_ops + df["Payback(%)"]
    df["Profit_Pct_Raw"] = df.apply(lambda row: (row["Profit(VND)"] / row["Total price(VND)"] * 100) if row["Total price(VND)"] > 0 else 0, axis=1)
    df["Profit(%)"] = df["Profit_Pct_Raw"].apply(lambda x: f"{x:.1f}%")
    
    def set_warning(row):
        if "KHÔNG KHỚP" in str(row.get("Cảnh báo", "")): return row.get("Cảnh báo", "")
        return "⚠️ LOW" if row["Profit_Pct_Raw"] < 10 else "✅ OK"
    
    if "Cảnh báo" in df.columns:
        df["Cảnh báo"] = df.apply(set_warning, axis=1)
    else:
        df["Cảnh báo"] = df.apply(lambda r: "⚠️ LOW" if r["Profit_Pct_Raw"] < 10 else "✅ OK", axis=1)

    return df

def parse_formula(formula, buying_price, ap_price):
    if not formula: return 0.0
    s = str(formula).strip().upper()
    if s.startswith("="): s = s[1:]
    val_buy = float(buying_price) if buying_price else 0.0
    val_ap = float(ap_price) if ap_price else 0.0
    s = s.replace("BUYING PRICE", str(val_buy))
    s = s.replace("BUY", str(val_buy))
    s = s.replace("AP PRICE", str(val_ap))
    s = s.replace("AP", str(val_ap))
    allowed_chars = "0123456789.+-*/() "
    if not all(c in allowed_chars for c in s):
        return 0.0
    try:
        return float(eval(s))
    except:
        return 0.0
