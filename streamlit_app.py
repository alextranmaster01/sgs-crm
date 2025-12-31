
# -*- coding: utf-8 -*-
"""
SGS CRM - Streamlit Online Edition (Supabase + Google Drive)

What this is
- A Streamlit rewrite of your Tkinter CRM app so it can run online.
- Data is stored in Supabase Postgres (via SQL / RPC or direct table operations).
- Excel/PDF/Images are stored on Google Drive using OAuth2 Refresh Token (no manual re-login).

What is NOT 1:1
- Tkinter Treeview inline image-in-row and OS-level "open file/folder" actions (os.startfile) are replaced by:
  - thumbnails in Streamlit
  - download links
  - Drive links

Security notes
- Put secrets in .streamlit/secrets.toml (DO NOT hardcode).
- Use Supabase Row Level Security (RLS) to protect data.
"""

from __future__ import annotations

import io
import os
import re
import ast
import json
import math
import time
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# Excel + images
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Border, Side, Alignment

# Images
from PIL import Image

# Supabase
from supabase import create_client, Client as SupabaseClient

# Google Drive
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# =============================================================================
# 1) CONFIG & CONSTANTS (ported from your Tkinter app)
# =============================================================================

APP_TITLE = "SGS CRM V4800 - STREAMLIT ONLINE"

# Columns (kept identical to your code)
MASTER_COLUMNS = ["no", "short_name", "eng_name", "vn_name", "address_1", "address_2", "contact_person",
                  "director", "phone", "fax", "tax_code", "destination", "payment_term"]
PURCHASE_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb",
                    "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "leadtime", "supplier_name", "image_path"]
SUPPLIER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "price_rmb", "total_rmb", "exchange_rate",
                       "price_vnd", "total_vnd", "eta", "supplier", "po_number", "order_date", "pdf_path"]
CUSTOMER_ORDER_COLS = ["no", "item_code", "item_name", "specs", "qty", "unit_price", "total_price", "eta", "customer",
                       "po_number", "order_date", "pdf_path", "base_buying_vnd", "full_cost_total"]
QUOTE_KH_COLUMNS = ["no", "item_code", "item_name", "specs", "qty", "buying_price_rmb", "total_buying_price_rmb",
                    "exchange_rate", "buying_price_vnd", "total_buying_price_vnd", "ap_price", "ap_total_vnd",
                    "unit_price", "total_price_vnd", "gap", "end_user_val", "buyer_val", "import_tax_val", "vat_val",
                    "transportation", "mgmt_fee", "payback_val", "profit_vnd", "profit_pct", "supplier_name", "image_path", "leadtime"]
TRACKING_COLS = ["no", "po_no", "partner", "status", "eta", "proof_image", "order_type", "last_update", "finished"]
PAYMENT_COLS = ["no", "po_no", "customer", "invoice_no", "status", "due_date", "paid_date"]
HISTORY_COLS = ["date", "quote_no", "customer", "item_code", "item_name", "specs", "qty", "total_revenue", "total_cost",
                "profit", "supplier", "status", "delivery_date", "po_number"]

STATUS_NCC = ["Đã đặt hàng", "Đợi hàng từ TQ về VN", "Hàng đã về VN", "Hàng đã nhận ở VP"]
STATUS_CUST = ["Đang đợi hàng về", "Đã giao hàng"]

# Supabase table names (you can rename, but keep consistent with SQL)
TBL_CUSTOMERS = "crm_customers"
TBL_SUPPLIERS = "crm_suppliers"
TBL_PURCHASES = "crm_purchases"
TBL_SALES_HISTORY = "crm_sales_history"
TBL_TRACKING = "crm_order_tracking"
TBL_PAYMENT = "crm_payment_tracking"
TBL_PAID_HISTORY = "crm_paid_history"
TBL_SUPPLIER_ORDERS = "db_supplier_orders"
TBL_CUSTOMER_ORDERS = "db_customer_orders"
TBL_APP_FILES = "crm_files"  # metadata of files stored on Drive (recommended)

DEFAULT_TEMPLATE_NAME = "AAA-QUOTATION.xlsx"
DEFAULT_DRIVE_FOLDER = "SGS_CRM_DATA"  # will be created if missing

# =============================================================================
# 2) HELPERS (ported)
# =============================================================================

def safe_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.startswith("['") and s.endswith("']"):
        try:
            eval_s = ast.literal_eval(s)
            if isinstance(eval_s, list) and len(eval_s) > 0:
                return str(eval_s[0])
        except Exception:
            pass
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    return "" if s.lower() == "nan" else s

def safe_filename(s: Any) -> str:
    return re.sub(r"[\\/:*?\"<>|]+", "_", safe_str(s))

def to_float(val: Any) -> float:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        clean = str(val).replace(",", "").replace("%", "").strip()
        if clean == "":
            return 0.0
        return float(clean)
    except Exception:
        return 0.0

def fmt_num(x: Any) -> str:
    try:
        return "{:,.0f}".format(float(x))
    except Exception:
        return "0"

def clean_lookup_key(s: Any) -> str:
    if s is None:
        return ""
    s_str = str(s)
    try:
        f = float(s_str)
        if f.is_integer():
            s_str = str(int(f))
    except Exception:
        pass
    return re.sub(r"\s+", "", s_str).lower()

def parse_formula(formula: str, buying_price: float, ap_price: float) -> float:
    s = str(formula).strip().upper().replace(",", "")
    try:
        return float(s)
    except Exception:
        pass
    if not s.startswith("="):
        return 0.0
    expr = s[1:]
    expr = expr.replace("BUYING PRICE", str(buying_price))
    expr = expr.replace("BUY", str(buying_price))
    expr = expr.replace("AP PRICE", str(ap_price))
    expr = expr.replace("AP", str(ap_price))
    allowed = "0123456789.+-*/()"
    for c in expr:
        if c not in allowed:
            return 0.0
    try:
        return float(eval(expr))
    except Exception:
        return 0.0

def calc_eta(order_date_str: str, leadtime_val: Any) -> str:
    try:
        dt_order = datetime.strptime(order_date_str, "%d/%m/%Y")
        lt_str = str(leadtime_val)
        nums = re.findall(r"\d+", lt_str)
        days = int(nums[0]) if nums else 0
        dt_exp = dt_order + timedelta(days=days)
        return dt_exp.strftime("%d/%m/%Y")
    except Exception:
        return ""

def img_to_bytes_thumb(path_or_bytes: Any, max_size: Tuple[int,int]=(120,120)) -> bytes:
    """Return PNG bytes thumbnail."""
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            im = Image.open(io.BytesIO(path_or_bytes)).convert("RGBA")
        else:
            im = Image.open(path_or_bytes).convert("RGBA")
        im.thumbnail(max_size)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return b""

def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()

# =============================================================================
# 3) SECRETS / CLIENTS
# =============================================================================

@dataclass
class AppConfig:
    supabase_url: str
    supabase_key: str

    google_client_id: str
    google_client_secret: str
    google_refresh_token: str

    drive_root_folder: str = DEFAULT_DRIVE_FOLDER
    admin_password: str = "admin"  # you can override in secrets

def load_config() -> AppConfig:
    # Streamlit secrets layout suggestion:
    # [supabase]
    # url="..."
    # key="..."
    # [google]
    # client_id="..."
    # client_secret="..."
    # refresh_token="..."
    # [app]
    # drive_root_folder="SGS_CRM_DATA"
    # admin_password="admin"
    s = st.secrets
    return AppConfig(
        supabase_url=s["supabase"]["url"],
        supabase_key=s["supabase"]["key"],
        google_client_id=s["google"]["client_id"],
        google_client_secret=s["google"]["client_secret"],
        google_refresh_token=s["google"]["refresh_token"],
        drive_root_folder=s.get("app", {}).get("drive_root_folder", DEFAULT_DRIVE_FOLDER),
        admin_password=s.get("app", {}).get("admin_password", "admin"),
    )

@st.cache_resource
def get_supabase(cfg: AppConfig) -> SupabaseClient:
    return create_client(cfg.supabase_url, cfg.supabase_key)

@st.cache_resource
def get_drive_service(cfg: AppConfig):
    creds = Credentials(
        token=None,
        refresh_token=cfg.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

# =============================================================================
# 4) GOOGLE DRIVE STORAGE (folders + upload/download)
# =============================================================================

def drive_find_folder(service, name: str, parent_id: Optional[str]=None) -> Optional[str]:
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name.replace('\'','\\\'')}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def drive_ensure_folder(service, name: str, parent_id: Optional[str]=None) -> str:
    folder_id = drive_find_folder(service, name, parent_id)
    if folder_id:
        return folder_id
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    f = service.files().create(body=metadata, fields="id").execute()
    return f["id"]

def drive_upload_bytes(service, folder_id: str, filename: str, content: bytes, mimetype: str) -> Dict[str,str]:
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=True)
    body = {"name": filename, "parents": [folder_id]}
    f = service.files().create(body=body, media_body=media, fields="id,webViewLink").execute()
    return {"file_id": f["id"], "webViewLink": f.get("webViewLink","")}

def drive_download_bytes(service, file_id: str) -> bytes:
    req = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return fh.getvalue()

# =============================================================================
# 5) SUPABASE DATA ACCESS
# =============================================================================

def sb_fetch_df(sb: SupabaseClient, table: str, columns: List[str]) -> pd.DataFrame:
    try:
        res = sb.table(table).select("*").execute()
        rows = res.data or []
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=columns)
        # normalize to string like original CSV behavior
        for c in df.columns:
            df[c] = df[c].apply(safe_str)
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        return df[columns]
    except Exception as e:
        st.error(f"Supabase load error ({table}): {e}")
        return pd.DataFrame(columns=columns)

def sb_upsert_df(sb: SupabaseClient, table: str, df: pd.DataFrame, pk: str="id") -> None:
    """
    Recommended approach:
    - Add an 'id' UUID column in every table as primary key
    - Upsert by 'id'
    If your existing tables don't have id, you can:
    - create id as generated uuid in DB
    - or create composite keys.
    This function tries best-effort: if no 'id' column, it will delete+insert.
    """
    try:
        if df is None:
            return
        df2 = df.copy()
        # Ensure JSON serializable
        payload = df2.to_dict(orient="records")

        # If table has id, do upsert; else replace
        if pk in df2.columns:
            sb.table(table).upsert(payload).execute()
        else:
            # REPLACE (WARNING: not safe under concurrency)
            sb.table(table).delete().neq("dummy", "dummy").execute()  # delete all
            if payload:
                sb.table(table).insert(payload).execute()
    except Exception as e:
        st.error(f"Supabase save error ({table}): {e}")

# =============================================================================
# 6) BUSINESS LOGIC (ported core pieces)
# =============================================================================

def purchases_add_clean_keys(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["_clean_code"] = []
        df["_clean_specs"] = []
        df["_clean_name"] = []
        return df
    df = df.copy()
    df["_clean_code"] = df["item_code"].apply(clean_lookup_key)
    df["_clean_specs"] = df["specs"].apply(clean_lookup_key)
    df["_clean_name"] = df["item_name"].apply(clean_lookup_key)
    return df

def find_purchase_match(purchases_df: pd.DataFrame, code_clean: str, specs_clean: str) -> Optional[pd.Series]:
    if purchases_df.empty:
        return None
    candidates = purchases_df[purchases_df["_clean_code"] == code_clean]
    if candidates.empty:
        return None
    if specs_clean != "":
        hit = candidates[candidates["_clean_specs"] == specs_clean]
        if not hit.empty:
            return hit.iloc[0]
        # fallback: both empty specs
        # (original logic: only if excel specs empty)
    if specs_clean == "":
        return candidates.iloc[0]
    return None

def recalc_quote(df: pd.DataFrame, pcts: Dict[str,float], global_trans_per_qty: Optional[float]) -> pd.DataFrame:
    """
    Mirrors your Tkinter recalculate() logic.
    pcts keys: end,buy,tax,vat,pay,mgmt are decimals (0.05 == 5%)
    global_trans_per_qty: if provided, overrides per-row transportation
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=QUOTE_KH_COLUMNS)
    out = df.copy()
    for i, r in out.iterrows():
        qty = to_float(r.get("qty"))
        buy_vnd = to_float(r.get("buying_price_vnd"))
        t_buy = qty * buy_vnd
        ap = to_float(r.get("ap_price"))
        unit = to_float(r.get("unit_price"))

        # transportation
        if global_trans_per_qty is not None:
            trans_per_qty = global_trans_per_qty
        else:
            trans_per_qty = to_float(r.get("transportation"))
        out.at[i, "transportation"] = fmt_num(trans_per_qty)

        ap_tot = ap * qty
        total = unit * qty
        gap = total - ap_tot

        tax = t_buy * pcts["tax"]
        buyer = total * pcts["buy"]
        vat = total * pcts["vat"]
        mgmt = total * pcts["mgmt"]
        end_user = ap_tot * pcts["end"]
        total_trans = trans_per_qty * qty
        payback = gap * pcts["pay"]

        cost = t_buy + gap + end_user + buyer + tax + vat + mgmt + total_trans
        prof = total - cost + payback
        pct = (prof / total * 100) if total else 0

        out.at[i, "total_buying_price_rmb"] = fmt_num(to_float(r.get("buying_price_rmb")) * qty)
        out.at[i, "total_buying_price_vnd"] = fmt_num(t_buy)
        out.at[i, "ap_total_vnd"] = fmt_num(ap_tot)
        out.at[i, "total_price_vnd"] = fmt_num(total)
        out.at[i, "gap"] = fmt_num(gap)

        out.at[i, "end_user_val"] = fmt_num(end_user)
        out.at[i, "buyer_val"] = fmt_num(buyer)
        out.at[i, "import_tax_val"] = fmt_num(tax)
        out.at[i, "vat_val"] = fmt_num(vat)
        out.at[i, "mgmt_fee"] = fmt_num(mgmt)
        out.at[i, "payback_val"] = fmt_num(payback)
        out.at[i, "profit_vnd"] = fmt_num(prof)
        out.at[i, "profit_pct"] = f"{pct:.2f}"

    return out

# =============================================================================
# 7) EXCEL IMPORTS / EXPORTS (purchase DB with embedded images, RFQ import)
# =============================================================================

def import_purchase_excel_with_images(xlsx_bytes: bytes) -> Tuple[pd.DataFrame, Dict[str, bytes]]:
    """
    Returns:
      - purchases_df (PURCHASE_COLUMNS + clean keys later)
      - images_by_pathkey: mapping a generated key -> image bytes
    In online mode, we don't store local paths; we store a Drive file_id later.
    So image_path column will temporarily store a key like "drive:pending:<sha1>"
    """
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    ws = wb.active

    # Extract embedded images by row (same assumption: image column index 12 == 13th col)
    img_map: Dict[int, bytes] = {}
    for img in getattr(ws, "_images", []):
        try:
            r_idx = img.anchor._from.row  # 0-based
            c_idx = img.anchor._from.col
            if c_idx == 12:
                data = img._data()
                # Excel row is 1-based; dataframe data starts at row 2 when header at row 1.
                excel_row_num = r_idx + 1
                img_map[excel_row_num] = data
        except Exception:
            continue

    df = pd.read_excel(io.BytesIO(xlsx_bytes), header=0, dtype=str).fillna("")
    rows = []
    images_by_key: Dict[str, bytes] = {}

    for i, r in df.iterrows():
        excel_row_num = i + 2  # header row is 1
        img_bytes = img_map.get(excel_row_num, b"")
        img_key = ""
        if img_bytes:
            k = sha1_bytes(img_bytes)
            img_key = f"pending:{k}"
            images_by_key[img_key] = img_bytes

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
            "image_path": img_key,  # temp
        }
        if item["item_code"]:
            rows.append(item)

    return pd.DataFrame(rows, columns=PURCHASE_COLUMNS), images_by_key

def import_rfq_excel(xlsx_bytes: bytes, purchases_df: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(xlsx_bytes), header=None, dtype=str).fillna("")
    data = []

    start_row = 1 if safe_str(df.iloc[0, 1]).lower() in ["code", "mã hàng"] else 0

    for _, r in df.iloc[start_row:].iterrows():
        no_raw = safe_str(r.iloc[0])
        c_raw = safe_str(r.iloc[1])
        name_ex = safe_str(r.iloc[2])
        specs_raw = safe_str(r.iloc[3])
        q = to_float(r.iloc[4])

        if not c_raw:
            continue

        it = {k: "" for k in QUOTE_KH_COLUMNS}
        it.update({"no": no_raw, "item_code": c_raw, "item_name": name_ex, "specs": specs_raw, "qty": fmt_num(q)})
        for f in ["ap_price", "unit_price", "transportation", "import_tax_val", "vat_val", "mgmt_fee", "payback_val"]:
            it[f] = "0"

        code_clean = clean_lookup_key(c_raw)
        specs_clean = clean_lookup_key(specs_raw)

        target = find_purchase_match(purchases_df, code_clean, specs_clean)
        if target is not None:
            it.update({
                "buying_price_rmb": safe_str(target.get("buying_price_rmb")),
                "exchange_rate": safe_str(target.get("exchange_rate")),
                "buying_price_vnd": safe_str(target.get("buying_price_vnd")),
                "supplier_name": safe_str(target.get("supplier_name")),
                "image_path": safe_str(target.get("image_path")),
                "leadtime": safe_str(target.get("leadtime")),
            })

        data.append(it)

    out = pd.DataFrame(data, columns=QUOTE_KH_COLUMNS)
    return out

# =============================================================================
# 8) UI PIECES
# =============================================================================

def ui_header():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption("Online Streamlit • Supabase SQL • Google Drive Storage")

def require_login(cfg: AppConfig) -> bool:
    # Lightweight login (not full auth). For production:
    # - Use Supabase Auth and RLS by user_id, or SSO.
    st.sidebar.subheader("🔐 Đăng nhập")
    pwd = st.sidebar.text_input("Admin password", type="password")
    ok = (pwd == cfg.admin_password) if pwd else False
    st.sidebar.success("Đã đăng nhập Admin" if ok else "Chỉ xem (Read-only) / hoặc nhập password")
    return ok

def editable_table(df: pd.DataFrame, key: str, disabled: bool) -> pd.DataFrame:
    if df is None:
        df = pd.DataFrame()
    return st.data_editor(
        df,
        key=key,
        disabled=disabled,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True
    )

def kpi_card(title: str, value: str):
    st.metric(label=title, value=value)

# =============================================================================
# 9) MAIN APP
# =============================================================================

def main():
    ui_header()
    cfg = load_config()
    sb = get_supabase(cfg)
    drive = get_drive_service(cfg)
    drive_root_id = drive_ensure_folder(drive, cfg.drive_root_folder)

    is_admin = require_login(cfg)

    # Load from Supabase
    customers_df = sb_fetch_df(sb, TBL_CUSTOMERS, MASTER_COLUMNS)
    suppliers_df = sb_fetch_df(sb, TBL_SUPPLIERS, MASTER_COLUMNS)
    purchases_df = sb_fetch_df(sb, TBL_PURCHASES, PURCHASE_COLUMNS)
    sales_history_df = sb_fetch_df(sb, TBL_SALES_HISTORY, HISTORY_COLS)
    tracking_df = sb_fetch_df(sb, TBL_TRACKING, TRACKING_COLS)
    payment_df = sb_fetch_df(sb, TBL_PAYMENT, PAYMENT_COLS)
    paid_history_df = sb_fetch_df(sb, TBL_PAID_HISTORY, PAYMENT_COLS)
    db_supplier_orders = sb_fetch_df(sb, TBL_SUPPLIER_ORDERS, SUPPLIER_ORDER_COLS)
    db_customer_orders = sb_fetch_df(sb, TBL_CUSTOMER_ORDERS, CUSTOMER_ORDER_COLS)

    purchases_df = purchases_add_clean_keys(purchases_df)

    # Session quote state
    if "current_quote_df" not in st.session_state:
        st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)

    tabs = st.tabs(["📊 Tổng quan", "💰 Báo giá NCC (DB Giá)", "📝 Báo giá KH", "📦 Quản lý đơn hàng", "🚚 Tracking", "🏷️ Master Data", "⚙️ Cấu hình"])

    # -------------------- TAB 1: Dashboard --------------------
    with tabs[0]:
        st.subheader("DASHBOARD KINH DOANH")
        rev = db_customer_orders["total_price"].apply(to_float).sum() if not db_customer_orders.empty else 0
        profit = sales_history_df["profit"].apply(to_float).sum() if not sales_history_df.empty else 0
        cost = rev - profit
        paid_count = len(paid_history_df)
        unpaid_count = len(payment_df[payment_df["status"] != "Đã thanh toán"]) if not payment_df.empty else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: kpi_card("TỔNG DOANH THU", fmt_num(rev))
        with c2: kpi_card("TỔNG CHI PHÍ", fmt_num(cost))
        with c3: kpi_card("LỢI NHUẬN", fmt_num(profit))
        with c4: kpi_card("PO ĐÃ THANH TOÁN", str(paid_count))
        with c5: kpi_card("PO CHƯA THANH TOÁN", str(unpaid_count))

        st.divider()
        st.write("⚠️ Cảnh báo PO quá hạn (tự tính theo Due Date)")
        alerts = []
        td = datetime.now()
        if not payment_df.empty:
            for _, r in payment_df.iterrows():
                if r.get("status") != "Đã thanh toán":
                    try:
                        due = datetime.strptime(r.get("due_date",""), "%d/%m/%Y")
                        if td > due:
                            alerts.append(f"PO {r.get('po_no')} - {r.get('customer')} (Quá hạn {(td-due).days} ngày)")
                    except Exception:
                        pass
        if alerts:
            st.warning("\n".join(alerts))
        else:
            st.success("Không có PO quá hạn.")

        if is_admin:
            st.divider()
            if st.button("⚠️ RESET DATA (Admin)", type="primary"):
                # WARNING: destructive
                sb.table(TBL_CUSTOMER_ORDERS).delete().neq("dummy", "dummy").execute()
                sb.table(TBL_SUPPLIER_ORDERS).delete().neq("dummy", "dummy").execute()
                sb.table(TBL_SALES_HISTORY).delete().neq("dummy", "dummy").execute()
                sb.table(TBL_TRACKING).delete().neq("dummy", "dummy").execute()
                sb.table(TBL_PAYMENT).delete().neq("dummy", "dummy").execute()
                sb.table(TBL_PAID_HISTORY).delete().neq("dummy", "dummy").execute()
                st.success("Đã reset dữ liệu. Refresh trang để tải lại.")

    # -------------------- TAB 2: Supplier Quote (Purchases DB) --------------------
    with tabs[1]:
        st.subheader("DB Giá NCC")
        left, right = st.columns([2, 1])

        with right:
            st.markdown("### 📥 Import Excel (Làm mới DB)")
            up = st.file_uploader("Chọn file Excel DB Giá (có ảnh embedded)", type=["xlsx"], key="pur_up")
            if up and is_admin:
                xbytes = up.read()
                df_new, images_map = import_purchase_excel_with_images(xbytes)
                df_new = purchases_add_clean_keys(df_new)

                # Upload images to Drive under folder: product_images
                img_folder_id = drive_ensure_folder(drive, "product_images", drive_root_id)
                # Replace image_path with drive file_id
                if images_map:
                    for i, r in df_new.iterrows():
                        ip = safe_str(r.get("image_path"))
                        if ip.startswith("pending:") and ip in images_map:
                            img_bytes = images_map[ip]
                            fileinfo = drive_upload_bytes(
                                drive, img_folder_id,
                                filename=f"{ip.replace('pending:','img_')}.png",
                                content=img_bytes,
                                mimetype="image/png",
                            )
                            df_new.at[i, "image_path"] = f"drive:{fileinfo['file_id']}"
                sb_upsert_df(sb, TBL_PURCHASES, df_new.drop(columns=["_clean_code","_clean_specs","_clean_name"], errors="ignore"))
                st.success("Đã import DB Giá NCC lên Supabase + upload ảnh lên Drive. Refresh trang để thấy dữ liệu mới.")

            st.markdown("### 🔎 Search")
            keyword = st.text_input("Từ khóa (code/name/specs/supplier)", key="pur_kw")
            st.caption("Tip: Search giống như app cũ (lọc theo chuỗi).")

        # Data view + thumbnails
        df_show = purchases_df.copy()
        if keyword:
            kw = keyword.lower()
            mask = df_show.apply(lambda row: kw in " ".join([safe_str(x) for x in row.values]).lower(), axis=1)
            df_show = df_show[mask]

        st.markdown("### Bảng DB Giá")
        edited = editable_table(df_show[ [c for c in PURCHASE_COLUMNS] ], key="pur_table", disabled=not is_admin)

        if is_admin:
            cA, cB = st.columns([1, 1])
            with cA:
                if st.button("💾 Lưu DB (Supabase)", key="pur_save"):
                    sb_upsert_df(sb, TBL_PURCHASES, purchases_add_clean_keys(edited).drop(columns=["_clean_code","_clean_specs","_clean_name"], errors="ignore"))
                    st.success("Đã lưu.")
            with cB:
                if st.button("🗑️ Xóa DB (Admin)", key="pur_clear"):
                    sb.table(TBL_PURCHASES).delete().neq("dummy", "dummy").execute()
                    st.success("Đã xóa DB Giá.")

        st.divider()
        st.markdown("### 🖼️ Xem ảnh dòng đang chọn")
        st.caption("Streamlit không có 'select row' như Treeview; hãy nhập Item Code để xem ảnh.")
        code_view = st.text_input("Nhập Item Code để xem ảnh", key="pur_img_code")
        if code_view:
            row = purchases_df[purchases_df["item_code"].apply(clean_lookup_key) == clean_lookup_key(code_view)]
            if not row.empty:
                imgref = safe_str(row.iloc[0].get("image_path"))
                if imgref.startswith("drive:"):
                    fid = imgref.split("drive:",1)[1]
                    try:
                        b = drive_download_bytes(drive, fid)
                        st.image(b, caption=f"Image for {code_view}", use_container_width=False)
                    except Exception as e:
                        st.error(f"Không tải được ảnh từ Drive: {e}")
                else:
                    st.info("Dòng này chưa có ảnh.")
            else:
                st.info("Không tìm thấy code trong DB.")

    # -------------------- TAB 3: Customer Quote --------------------
    with tabs[2]:
        st.subheader("Báo giá Khách hàng")
        sub1, sub2 = st.tabs(["Tạo Báo Giá", "Tra Cứu Lịch Sử"])

        with sub1:
            st.markdown("#### 1) Thông tin chung")
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                cust_list = customers_df["short_name"].tolist()
                cust = st.selectbox("Khách hàng", options=[""] + cust_list, index=0, key="q_cust")
            with c2:
                quote_name = st.text_input("Tên Báo Giá", key="q_name")
            with c3:
                if st.button("✨ TẠO MỚI (RESET)", key="q_reset"):
                    st.session_state.current_quote_df = pd.DataFrame(columns=QUOTE_KH_COLUMNS)
                    st.success("Đã reset quote hiện tại.")

            st.markdown("#### 2) Tham số chi phí (%) & File")
            pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns(7)
            end_pct = pc1.number_input("End user(%)", value=0.0, step=0.5, key="pct_end")
            buy_pct = pc2.number_input("Buyer(%)", value=0.0, step=0.5, key="pct_buy")
            tax_pct = pc3.number_input("Tax(%)", value=0.0, step=0.5, key="pct_tax")
            vat_pct = pc4.number_input("VAT(%)", value=0.0, step=0.5, key="pct_vat")
            pay_pct = pc5.number_input("Payback(%)", value=0.0, step=0.5, key="pct_pay")
            mgmt_pct = pc6.number_input("Mgmt(%)", value=0.0, step=0.5, key="pct_mgmt")
            global_trans = pc7.number_input("Trans/Qty (VND)", value=0.0, step=1000.0, key="pct_trans")

            rfq_up = st.file_uploader("📂 Import RFQ (Excel)", type=["xlsx"], key="rfq_up")
            if rfq_up:
                qdf = import_rfq_excel(rfq_up.read(), purchases_df)
                # Recalculate immediately
                pcts = {"end": end_pct/100, "buy": buy_pct/100, "tax": tax_pct/100, "vat": vat_pct/100,
                        "pay": pay_pct/100, "mgmt": mgmt_pct/100}
                gtrans = global_trans if global_trans > 0 else None
                qdf = recalc_quote(qdf, pcts, gtrans)
                st.session_state.current_quote_df = qdf
                st.success("Đã nạp RFQ & tìm giá.")

            st.markdown("#### 3) Công cụ & Thao tác")
            fc1, fc2, fc3 = st.columns([1, 1, 2])
            with fc1:
                ap_formula = st.text_input("AP Formula (vd: =BUY*1.05)", key="ap_formula")
                if st.button("Apply AP", key="apply_ap"):
                    dfq = st.session_state.current_quote_df.copy()
                    for i, r in dfq.iterrows():
                        buy = to_float(r.get("buying_price_vnd"))
                        ap = parse_formula(ap_formula, buy, to_float(r.get("ap_price")))
                        dfq.at[i, "ap_price"] = fmt_num(ap)
                    st.session_state.current_quote_df = dfq
            with fc2:
                unit_formula = st.text_input("Unit Formula (vd: =AP*1.1)", key="unit_formula")
                if st.button("Apply Unit", key="apply_unit"):
                    dfq = st.session_state.current_quote_df.copy()
                    for i, r in dfq.iterrows():
                        buy = to_float(r.get("buying_price_vnd"))
                        apv = to_float(r.get("ap_price"))
                        unit = parse_formula(unit_formula, buy, apv)
                        dfq.at[i, "unit_price"] = fmt_num(unit)
                    st.session_state.current_quote_df = dfq
            with fc3:
                if st.button("🔄 Tính Lợi Nhuận", key="recalc_btn"):
                    dfq = st.session_state.current_quote_df
                    pcts = {"end": end_pct/100, "buy": buy_pct/100, "tax": tax_pct/100, "vat": vat_pct/100,
                            "pay": pay_pct/100, "mgmt": mgmt_pct/100}
                    gtrans = global_trans if global_trans > 0 else None
                    st.session_state.current_quote_df = recalc_quote(dfq, pcts, gtrans)
                    st.success("Đã tính lại.")

            st.markdown("#### Bảng báo giá (có thể sửa)")
            dfq_edit = editable_table(st.session_state.current_quote_df, key="quote_table", disabled=not is_admin)
            st.session_state.current_quote_df = dfq_edit

            st.divider()
            st.markdown("#### 💾 Lưu lịch sử / Xuất Excel")
            colx1, colx2, colx3 = st.columns([1,1,2])

            with colx1:
                if st.button("💾 Lưu Lịch sử (Sales History)", disabled=not is_admin):
                    if not cust or not quote_name:
                        st.error("Cần chọn Khách hàng và Tên Báo Giá.")
                    else:
                        now = datetime.now().strftime("%d/%m/%Y")
                        rows = []
                        for _, r in st.session_state.current_quote_df.iterrows():
                            rows.append({
                                "date": now,
                                "quote_no": quote_name,
                                "customer": cust,
                                "item_code": safe_str(r.get("item_code")),
                                "item_name": safe_str(r.get("item_name")),
                                "specs": safe_str(r.get("specs")),
                                "qty": safe_str(r.get("qty")),
                                "total_revenue": safe_str(r.get("total_price_vnd")),
                                "total_cost": safe_str(r.get("total_buying_price_vnd")),
                                "profit": safe_str(r.get("profit_vnd")),
                                "supplier": safe_str(r.get("supplier_name")),
                                "status": "Báo giá",
                                "delivery_date": "",
                                "po_number": "",
                            })
                        hist_add = pd.DataFrame(rows, columns=HISTORY_COLS)
                        hist_all = pd.concat([sales_history_df, hist_add], ignore_index=True)
                        sb_upsert_df(sb, TBL_SALES_HISTORY, hist_all)
                        st.success("Đã lưu Sales History.")
            with colx2:
                if st.button("🧾 Xuất Excel Báo Giá", disabled=st.session_state.current_quote_df.empty):
                    # Create a simple quotation Excel (template-based export can be added here)
                    out = io.BytesIO()
                    with pd.ExcelWriter(out, engine="openpyxl") as writer:
                        st.session_state.current_quote_df.to_excel(writer, index=False, sheet_name="Quotation")
                    out_bytes = out.getvalue()

                    # Upload to Drive under Quotation folder / customer
                    q_folder = drive_ensure_folder(drive, "LICH_SU_BAO_GIA", drive_root_id)
                    cust_folder = drive_ensure_folder(drive, safe_filename(cust) if cust else "Retail", q_folder)
                    fname = safe_filename(f"{quote_name or 'quotation'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                    finfo = drive_upload_bytes(drive, cust_folder, fname, out_bytes,
                                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    st.success("Đã upload Excel lên Drive.")
                    if finfo.get("webViewLink"):
                        st.link_button("Mở file trên Google Drive", finfo["webViewLink"])
                    st.download_button("Download Excel", data=out_bytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with colx3:
                st.caption("Gợi ý: nếu bạn muốn **giữ y hệt template AAA-QUOTATION.xlsx** (merge cells, style, layout), "
                           "mình có thể map chính xác các cell như bản Tkinter. Bản code hiện tại export dạng bảng (tương đương dữ liệu).")

        with sub2:
            st.markdown("#### Tra cứu theo từ khóa")
            kw = st.text_input("Từ khóa (customer/code/name/specs/quote_no/po_no)", key="hist_kw")
            hist_view = sales_history_df.copy()
            if kw:
                kwl = kw.lower()
                mask = hist_view.apply(lambda row: kwl in " ".join([safe_str(x) for x in row.values]).lower(), axis=1)
                hist_view = hist_view[mask]
            st.dataframe(hist_view, use_container_width=True, hide_index=True)

            st.markdown("#### Tra cứu hàng loạt từ Excel (Bulk Check)")
            bulk = st.file_uploader("Import Excel để Check", type=["xlsx"], key="bulk_up")
            if bulk:
                df = pd.read_excel(bulk, header=None, dtype=str).fillna("")
                start_row = 1 if safe_str(df.iloc[0, 1]).lower() in ['code', 'mã hàng'] else 0

                # build clean keys
                sh = sales_history_df.copy()
                co = db_customer_orders.copy()
                if not sh.empty:
                    sh["_clean_code"] = sh["item_code"].apply(clean_lookup_key)
                    sh["_clean_specs"] = sh["specs"].apply(clean_lookup_key)
                if not co.empty:
                    co["_clean_code"] = co["item_code"].apply(clean_lookup_key)
                    co["_clean_specs"] = co["specs"].apply(clean_lookup_key)

                res_rows = []
                for _, r in df.iloc[start_row:].iterrows():
                    c_raw = safe_str(r.iloc[1])
                    name_ex = safe_str(r.iloc[2])
                    specs_raw = safe_str(r.iloc[3])
                    if not c_raw:
                        continue
                    clean_c = clean_lookup_key(c_raw)
                    clean_s = clean_lookup_key(specs_raw)

                    # Sales history matches
                    if not sh.empty:
                        found = sh[sh["_clean_code"] == clean_c]
                        for _, h in found.iterrows():
                            db_s = h["_clean_specs"]
                            match = (db_s == clean_s) or (clean_s and clean_s in db_s) or (db_s and db_s in clean_s)
                            if match:
                                unit_p = 0.0
                                try:
                                    rev = to_float(h["total_revenue"])
                                    qv = to_float(h["qty"])
                                    if qv > 0:
                                        unit_p = rev / qv
                                except Exception:
                                    pass
                                res_rows.append({
                                    "source": "Lịch sử BG",
                                    "date": h["date"],
                                    "customer": h["customer"],
                                    "item_code": h["item_code"],
                                    "item_name": h["item_name"],
                                    "specs": h["specs"],
                                    "qty": h["qty"],
                                    "price": fmt_num(unit_p),
                                    "ref_no": h["quote_no"],
                                })

                    # Customer order matches
                    if not co.empty:
                        found_po = co[co["_clean_code"] == clean_c]
                        for _, po in found_po.iterrows():
                            db_s = po["_clean_specs"]
                            match = (db_s == clean_s) or (clean_s and clean_s in db_s) or (db_s and db_s in clean_s)
                            if match:
                                res_rows.append({
                                    "source": "Đã có PO",
                                    "date": po["order_date"],
                                    "customer": po["customer"],
                                    "item_code": po["item_code"],
                                    "item_name": po["item_name"],
                                    "specs": po["specs"],
                                    "qty": po["qty"],
                                    "price": po["unit_price"],
                                    "ref_no": po["po_number"],
                                })

                res_df = pd.DataFrame(res_rows)
                st.dataframe(res_df, use_container_width=True, hide_index=True)
                st.success("Đã tra cứu xong.")

    # -------------------- TAB 4: Orders Management --------------------
    with tabs[3]:
        st.subheader("Quản lý đơn hàng (PO NCC / PO KH)")
        st.markdown("### PO Nhà cung cấp")
        supp_edit = editable_table(db_supplier_orders, key="supp_orders", disabled=not is_admin)
        if is_admin and st.button("💾 Lưu PO NCC"):
            sb_upsert_df(sb, TBL_SUPPLIER_ORDERS, supp_edit)
            st.success("Đã lưu PO NCC.")

        st.divider()
        st.markdown("### PO Khách hàng")
        cust_edit = editable_table(db_customer_orders, key="cust_orders", disabled=not is_admin)
        if is_admin and st.button("💾 Lưu PO KH"):
            sb_upsert_df(sb, TBL_CUSTOMER_ORDERS, cust_edit)
            st.success("Đã lưu PO KH.")

    # -------------------- TAB 5: Tracking --------------------
    with tabs[4]:
        st.subheader("Tracking đơn hàng")
        st.caption("Bạn có thể đính kèm ảnh proof bằng upload lên Drive, rồi lưu file_id ở cột proof_image.")

        tr_edit = editable_table(tracking_df, key="tracking_tbl", disabled=not is_admin)
        if is_admin and st.button("💾 Lưu Tracking"):
            sb_upsert_df(sb, TBL_TRACKING, tr_edit)
            st.success("Đã lưu Tracking.")

        st.divider()
        st.markdown("### Upload Proof Image")
        proof_up = st.file_uploader("Chọn ảnh proof", type=["png","jpg","jpeg"], key="proof_up")
        if proof_up and is_admin:
            proof_folder = drive_ensure_folder(drive, "proof_images", drive_root_id)
            img_bytes = proof_up.read()
            fname = safe_filename(f"proof_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            finfo = drive_upload_bytes(drive, proof_folder, fname, img_bytes, "image/png")
            st.success("Đã upload proof lên Drive.")
            st.write("Lưu giá trị này vào cột proof_image:", f"drive:{finfo['file_id']}")
            if finfo.get("webViewLink"):
                st.link_button("Mở ảnh trên Drive", finfo["webViewLink"])

    # -------------------- TAB 6: Master Data --------------------
    with tabs[5]:
        st.subheader("Master Data (Customers / Suppliers)")
        cA, cB = st.columns(2)
        with cA:
            st.markdown("### Customers")
            cust_edit = editable_table(customers_df, key="cust_master", disabled=not is_admin)
            if is_admin and st.button("💾 Lưu Customers"):
                sb_upsert_df(sb, TBL_CUSTOMERS, cust_edit)
                st.success("Đã lưu Customers.")
        with cB:
            st.markdown("### Suppliers")
            sup_edit = editable_table(suppliers_df, key="supp_master", disabled=not is_admin)
            if is_admin and st.button("💾 Lưu Suppliers"):
                sb_upsert_df(sb, TBL_SUPPLIERS, sup_edit)
                st.success("Đã lưu Suppliers.")

    # -------------------- TAB 7: Config / SQL Console --------------------
    with tabs[6]:
        st.subheader("Cấu hình & SQL Console (Supabase)")
        st.caption("Bạn có thể gọi RPC hoặc view. Với PostgREST, chạy SQL trực tiếp từ client bị hạn chế; "
                   "cách chuẩn là tạo function (RPC) trên Supabase rồi gọi từ đây.")
        st.markdown("### 1) Chạy RPC (khuyến nghị)")
        rpc_name = st.text_input("Tên function (RPC)", placeholder="vd: my_sql_runner", key="rpc_name")
        rpc_payload = st.text_area("JSON params", value="{}", key="rpc_payload")
        if st.button("▶️ Call RPC", key="rpc_call"):
            try:
                params = json.loads(rpc_payload or "{}")
                res = sb.rpc(rpc_name, params).execute()
                st.success("OK")
                st.write(res.data)
            except Exception as e:
                st.error(f"Lỗi RPC: {e}")

        st.markdown("### 2) Quick export all tables to Excel")
        if st.button("📦 Export data snapshot (Excel)"):
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as w:
                customers_df.to_excel(w, index=False, sheet_name="customers")
                suppliers_df.to_excel(w, index=False, sheet_name="suppliers")
                purchases_df[PURCHASE_COLUMNS].to_excel(w, index=False, sheet_name="purchases")
                sales_history_df.to_excel(w, index=False, sheet_name="sales_history")
                tracking_df.to_excel(w, index=False, sheet_name="tracking")
                payment_df.to_excel(w, index=False, sheet_name="payment")
                paid_history_df.to_excel(w, index=False, sheet_name="paid_history")
                db_supplier_orders.to_excel(w, index=False, sheet_name="po_supplier")
                db_customer_orders.to_excel(w, index=False, sheet_name="po_customer")
            b = out.getvalue()
            fname = f"sgs_crm_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.download_button("Download snapshot", data=b, file_name=fname,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if __name__ == "__main__":
    main()
