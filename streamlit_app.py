# ... (Phần import và setup ban đầu giữ nguyên)

# TAB 2: DB GIÁ NCC
with tab2:
    st.subheader("Database Giá NCC")
    
    col_tool, col_search = st.columns([1, 1])
    with col_tool:
        uploaded_file = st.file_uploader("📥 Import Excel (Có chứa ảnh)", type=['xlsx'], key="uploader_pur")
        
        if uploaded_file and st.button("🚀 BẮT ĐẦU IMPORT", type="primary"):
            status_box = st.status("Đang xử lý...", expanded=True)
            try:
                status_box.write("🖼️ Quét ảnh...")
                uploaded_file.seek(0)
                wb = load_workbook(uploaded_file, data_only=False); ws = wb.active
                image_map = {}
                if hasattr(ws, '_images'):
                    for img in ws._images:
                        image_map[img.anchor._from.row + 1] = img._data()
                
                status_box.write("📖 Đọc dữ liệu...")
                uploaded_file.seek(0)
                # Đọc file, đảm bảo lấy đủ các cột
                df_raw = pd.read_excel(uploaded_file, header=0, dtype=str).fillna("")
                
                data_clean = []
                prog_bar = status_box.progress(0); total = len(df_raw)
                
                for i, row in df_raw.iterrows():
                    prog_bar.progress(min((i + 1) / total, 1.0))
                    excel_row_idx = i + 2
                    
                    code = safe_str(row.iloc[1]) # Cột B - Item code
                    if not code: continue

                    # Xử lý ảnh
                    final_link = ""
                    if excel_row_idx in image_map:
                        status_box.write(f"☁️ Up ảnh: {code}...")
                        link = backend.upload_to_drive(io.BytesIO(image_map[excel_row_idx]), f"{safe_filename(code)}.png", "images")
                        if link: final_link = link
                    else:
                        old = safe_str(row.iloc[12]) if len(row) > 12 else "" # Cột M - Images
                        if "http" in old: final_link = old

                    # Mapping dữ liệu vào dict nội bộ (nhưng sẽ hiển thị tên chuẩn sau)
                    item = {
                        "no": safe_str(row.iloc[0]),                        # A - No
                        "item_code": code,                                  # B - Item code
                        "item_name": safe_str(row.iloc[2]),                 # C - Item name
                        "specs": safe_str(row.iloc[3]),                     # D - Specs
                        "qty": fmt_num(to_float(row.iloc[4])),              # E - Q'ty
                        "buying_price_rmb": fmt_num(to_float(row.iloc[5])), # F - Buying price (RMB)
                        "total_buying_price_rmb": fmt_num(to_float(row.iloc[6])), # G - Total buying price (RMB)
                        "exchange_rate": fmt_num(to_float(row.iloc[7])),    # H - Exchange rate
                        "buying_price_vnd": fmt_num(to_float(row.iloc[8])), # I - Buying price (VND)
                        "total_buying_price_vnd": fmt_num(to_float(row.iloc[9])), # J - Total buying price (VND)
                        "leadtime": safe_str(row.iloc[10]),                 # K - Leadtime
                        "supplier_name": safe_str(row.iloc[11]),            # L - Supplier
                        "image_path": final_link,                           # M - Images
                        "type": safe_str(row.iloc[13]) if len(row) > 13 else "",      # N - Type
                        "nuoc": safe_str(row.iloc[14]) if len(row) > 14 else "",      # O - N/U/O/C
                        
                        # Các trường phụ để search/sort
                        "_clean_code": clean_lookup_key(code), 
                        "_clean_specs": clean_lookup_key(safe_str(row.iloc[3])), 
                        "_clean_name": clean_lookup_key(safe_str(row.iloc[2]))
                    }
                    data_clean.append(item)
                
                if data_clean:
                    backend.save_data("purchases", pd.DataFrame(data_clean))
                    status_box.update(label="✅ Hoàn tất!", state="complete", expanded=False)
                    time.sleep(1); st.rerun()
            except Exception as e: st.error(f"Lỗi: {e}")

    # --- PHẦN HIỂN THỊ CHÍNH ---
    df_pur = backend.load_data("purchases")

    # Layout: Bảng chiếm 8 phần, Ảnh chiếm 2 phần (Ảnh nhỏ đi 50% so với trước)
    col_table, col_gallery = st.columns([8, 2])
    
    selected_row_data = None # Biến lưu dữ liệu dòng đang chọn

    with col_table:
        # Thanh tìm kiếm
        search = st.text_input("🔍 Tìm kiếm...", key="search_pur")
        if search and not df_pur.empty:
            df_pur = df_pur[df_pur.apply(lambda x: x.astype(str).str.contains(search, case=False, na=False)).any(axis=1)]

        # Cấu hình tên cột hiển thị mapping chuẩn 100% theo yêu cầu
        # Key là tên biến trong code, Label là tên hiển thị trên bảng
        column_cfg = {
            "no": st.column_config.TextColumn("No", width="small"),
            "item_code": st.column_config.TextColumn("Item code"),
            "item_name": st.column_config.TextColumn("Item name"),
            "specs": st.column_config.TextColumn("Specs"),
            "qty": st.column_config.TextColumn("Q'ty"),
            "buying_price_rmb": st.column_config.TextColumn("Buying price (RMB)"),
            "total_buying_price_rmb": st.column_config.TextColumn("Total buying price (RMB)"),
            "exchange_rate": st.column_config.TextColumn("Exchange rate"),
            "buying_price_vnd": st.column_config.TextColumn("Buying price (VND)"),
            "total_buying_price_vnd": st.column_config.TextColumn("Total buying price (VND)"),
            "leadtime": st.column_config.TextColumn("Leadtime"),
            "supplier_name": st.column_config.TextColumn("Supplier"),
            "image_path": st.column_config.LinkColumn("Images", display_text="Link"),
            "type": st.column_config.TextColumn("Type"),
            "nuoc": st.column_config.TextColumn("N/U/O/C"),
            
            # Ẩn các cột hệ thống
            "_clean_code": None, "_clean_specs": None, "_clean_name": None, "id": None, "created_at": None
        }

        # Thứ tự hiển thị chuẩn từ A -> O
        display_order = [
            "no", "item_code", "item_name", "specs", "qty", 
            "buying_price_rmb", "total_buying_price_rmb", "exchange_rate", 
            "buying_price_vnd", "total_buying_price_vnd", "leadtime", 
            "supplier_name", "image_path", "type", "nuoc"
        ]
        
        # Bảng dữ liệu có khả năng click chọn dòng (on_select)
        event = st.dataframe(
            df_pur,
            column_config=column_cfg,
            column_order=display_order,
            use_container_width=True,
            height=600,
            hide_index=True,
            on_select="rerun",           # Khi chọn dòng sẽ chạy lại app để update ảnh
            selection_mode="single-row"  # Chỉ chọn 1 dòng
        )

        # Lấy dữ liệu dòng được chọn
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            # Lưu ý: idx này là index của df_pur sau khi đã lọc (nếu có search)
            selected_row_data = df_pur.iloc[idx]

    # KHUNG XEM ẢNH (Bên phải, nhỏ gọn)
    with col_gallery:
        if selected_row_data is not None:
            # Dữ liệu từ dòng được click
            code = selected_row_data['item_code']
            name = selected_row_data['item_name']
            specs = selected_row_data['specs']
            img_link = selected_row_data.get('image_path', '')
            
            st.info(f"📌 **{code}**")
            st.caption(f"{name}")
            
            # Hiển thị ảnh
            if img_link and "http" in str(img_link):
                with st.spinner("Load ảnh..."):
                    img_bytes = backend.get_image_bytes(img_link)
                    if img_bytes:
                        st.image(img_bytes, caption="Ảnh sản phẩm", use_container_width=True)
                    else:
                        st.error("Lỗi tải ảnh.")
            else:
                st.warning("Không có ảnh")
                
            st.markdown("---")
            st.markdown(f"**Thông số:** {specs}")
            st.markdown(f"**Giá VND:** {selected_row_data['buying_price_vnd']}")
        else:
            # Trạng thái chờ khi chưa click
            st.info("👈 Click vào 1 dòng bất kỳ bên trái để xem ảnh.")

# ... (Các tab khác giữ nguyên)
