import pathlib

p = pathlib.Path('core/eligibility.py')
t = p.read_text()

# Fix Gate 6: riskometer_score
old = 'riskometer_score = int(fund_data.get("riskometer_score", 6))'
new = '''riskometer_raw = fund_data.get("riskometer_score")
    if riskometer_raw is None:
        failed.append("Gate 6 [Riskometer]: riskometer_score field missing - cannot verify suitability (fail-closed)")
        riskometer_score = 6
        mandate_ok = False
    else:
        riskometer_score = int(riskometer_raw)
        mandate_ok = True'''
t = t.replace(old, new)

# Fix Gate 6: mandate_suitable
old2 = 'mandate_ok = fund_data.get("mandate_suitable", True)'
new2 = '''mandate_suitable_raw = fund_data.get("mandate_suitable")
    if mandate_suitable_raw is None:
        failed.append("Gate 6 [Mandate Suitability]: mandate_suitable field missing - cannot verify (fail-closed)")
        mandate_ok = False
    elif not mandate_suitable_raw:
        mandate_ok = False'''
t = t.replace(old2, new2)

# Fix Gate 7: confidence_score and data_complete
old3 = '''confidence_score = float(provenance.get("confidence_score", fund_data.get("confidence_score", 1.0)) or 1.0)
    data_complete = fund_data.get("data_complete", True)
    data_ok = (confidence_score >= min_confidence_score) and data_complete
    if not data_ok:
        failed.append(f"Gate 7 [Data Integrity]: Confidence score {confidence_score:.2f} < {min_confidence_score:.2f} or incomplete factsheet")'''
new3 = '''if "confidence_score" not in provenance:
        failed.append("Gate 7 [Data Integrity]: confidence_score missing from _provenance - cannot verify (fail-closed)")
        confidence_score = 0.0
        data_ok = False
    else:
        confidence_score = float(provenance.get("confidence_score", 0.0) or 0.0)
        data_ok = confidence_score >= min_confidence_score
        if not data_ok:
            failed.append(f"Gate 7 [Data Integrity]: Confidence score {confidence_score:.2f} < {min_confidence_score:.2f}")
    
    if "data_complete" not in fund_data:
        failed.append("Gate 7 [Data Integrity]: data_complete field missing - cannot verify (fail-closed)")
        data_ok = False
    elif not fund_data.get("data_complete", False):
        failed.append("Gate 7 [Data Integrity]: data_complete is False - factsheet incomplete")
        data_ok = False'''
t = t.replace(old3, new3)

# Fix Gate 8: manager_tenure_years
old4 = 'tenure = float(fund_data.get("manager_tenure_years", fund_data.get("tenure", 3.0)) or 0.0)'
new4 = '''if "manager_tenure_years" not in fund_data and "tenure" not in fund_data:
        failed.append("Gate 8 [Manager Tenure]: manager_tenure_years field missing - cannot verify (fail-closed)")
        tenure = 0.0
    else:
        tenure = float(fund_data.get("manager_tenure_years", fund_data.get("tenure", 0.0)) or 0.0)'''
t = t.replace(old4, new4)

# Fix Gate 8: track_record_years
old5 = 'scheme_track_record = float(fund_data.get("track_record_years", fund_data.get("track_record", 5.0)) or 5.0)'
new5 = '''if "track_record_years" not in fund_data and "track_record" not in fund_data:
        failed.append("Gate 8 [Track Record]: track_record_years field missing - cannot verify (fail-closed)")
        scheme_track_record = 0.0
    else:
        scheme_track_record = float(fund_data.get("track_record_years", fund_data.get("track_record", 0.0)) or 0.0)'''
t = t.replace(old5, new5)

p.write_text(t)
print("Done - all eligibility gate defaults fixed")