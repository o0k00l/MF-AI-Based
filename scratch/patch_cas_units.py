with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """        col_folio = hdr.get("Folio No.", 3)
        col_inv = hdr.get("Invested Value", 4)
        col_cur = hdr.get("Current Value", 5)

        for row in sheet.iter_rows(min_row=start_row, values_only=True):
            if not row or len(row) <= col_scheme or not row[col_scheme]:
                continue
            s_name = row[col_scheme]
            f_no = row[col_folio] if len(row) > col_folio else ""
            i_val = row[col_inv] if len(row) > col_inv else 0.0
            c_val = row[col_cur] if len(row) > col_cur else 0.0
            try:
                c_float = float(c_val) if c_val else 0.0
                i_float = float(i_val) if i_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float))
    else:
        for r in range(13, sheet.max_row + 1):
            s_name = sheet.cell(row=r, column=1).value
            f_no = sheet.cell(row=r, column=4).value
            i_val = sheet.cell(row=r, column=5).value
            c_val = sheet.cell(row=r, column=6).value
            if not c_val:
                continue
            try:
                c_float = float(c_val)
                i_float = float(i_val) if i_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float))

    for scheme_str, folio_str, invested, current in raw_items:"""

replacement = """        col_folio = hdr.get("Folio No.", 3)
        col_inv = hdr.get("Invested Value", 4)
        col_cur = hdr.get("Current Value", 5)
        col_units = hdr.get("Units", 7)

        for row in sheet.iter_rows(min_row=start_row, values_only=True):
            if not row or len(row) <= col_scheme or not row[col_scheme]:
                continue
            s_name = row[col_scheme]
            f_no = row[col_folio] if len(row) > col_folio else ""
            i_val = row[col_inv] if len(row) > col_inv else 0.0
            c_val = row[col_cur] if len(row) > col_cur else 0.0
            u_val = row[col_units] if len(row) > col_units else 0.0
            try:
                c_float = float(c_val) if c_val else 0.0
                i_float = float(i_val) if i_val else 0.0
                u_float = float(u_val) if u_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                nav_float = round(c_float / u_float, 4) if u_float > 0 else 0.0
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float, u_float, nav_float))
    else:
        for r in range(13, sheet.max_row + 1):
            s_name = sheet.cell(row=r, column=1).value
            f_no = sheet.cell(row=r, column=4).value
            i_val = sheet.cell(row=r, column=5).value
            c_val = sheet.cell(row=r, column=6).value
            u_val = sheet.cell(row=r, column=8).value
            if not c_val:
                continue
            try:
                c_float = float(c_val)
                i_float = float(i_val) if i_val else 0.0
                u_float = float(u_val) if u_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                nav_float = round(c_float / u_float, 4) if u_float > 0 else 0.0
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float, u_float, nav_float))

    for scheme_str, folio_str, invested, current, units_val, nav_val in raw_items:"""

assert target in text, "target not found"
text = text.replace(target, replacement, 1)

# Now update HoldingItem instantiation
target_inst = """                units=0.0,
                nav=0.0,"""

replacement_inst = """                units=units_val,
                nav=nav_val,"""

assert target_inst in text, "target_inst not found"
text = text.replace(target_inst, replacement_inst, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully updated load_holdings_from_cas_excel to read real units and NAV from CAS")

