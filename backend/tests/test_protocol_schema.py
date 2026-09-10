from backend.protocol_schema import COLUMNS, validate_extraction, to_tsv


def source():
    return {7: {"name": "methods.pdf", "pages": [{"page": 2, "text": "Cells received CHIR99021 at 3 uM from day 0 to day 3."}]}}


def event(**overrides):
    row = {key: "NA" for key in COLUMNS}
    row.update(GSE_id="GSE1", GSM_id="GSM1", Stage_name="differentiation", Stage_order="1",
               Pert_name="CHIR99021", Addition_context="perturbation", Pert_type="small_molecule",
               dose_value="3", dose_unit="uM", time_pert_start="D0", time_pert_end="D3",
               duration_pert="3", time_unit="days", time_collection="D3")
    return {"protocol_name": "Neural differentiation", "values": row,
            "evidence": [{"document_id": 7, "page": 2, "quote": "CHIR99021 at 3 uM from day 0 to day 3"}], **overrides}


def test_valid_events_keep_24_column_contract_and_evidence():
    result = validate_extraction({"outcome": "extracted", "events": [event()]}, source(), "GSE1", ["GSM1"])
    assert not result["blockers"]
    assert len(COLUMNS) == 24
    assert to_tsv(result["events"]).splitlines()[0].split('\t') == COLUMNS


def test_invented_evidence_and_unknown_sample_are_blocked():
    item = event(evidence=[{"document_id": 7, "page": 2, "quote": "BMP4 100 ng/ml"}])
    item['values']['GSM_id'] = 'GSM999'
    result = validate_extraction({"outcome": "extracted", "events": [item]}, source(), "GSE1", ["GSM1"])
    assert any('证据' in issue for issue in result['blockers'])
    assert any('GSM999' in issue for issue in result['blockers'])


def test_impossible_times_and_duration_are_blocked():
    item = event()
    item['values'].update(time_pert_end='D5', duration_pert='3')
    result = validate_extraction({"outcome": "extracted", "events": [item]}, source(), "GSE1", ['GSM1'])
    assert len(result['blockers']) >= 2


def test_missing_fields_normalize_to_na_but_missing_events_is_not_success():
    import pytest
    with pytest.raises(ValueError):
        validate_extraction({}, source(), 'GSE1', [])
    item = event(); del item['values']['pubchem_cid']
    result = validate_extraction({'outcome': 'extracted', 'events': [item]}, source(), 'GSE1', ['GSM1'])
    assert result['events'][0]['values']['pubchem_cid'] == 'NA'


def test_known_type_spacing_and_missing_value_variants_are_normalized():
    row = event()
    row['values'].update(Pert_type='small molecule',Collection_methods='none')
    result = validate_extraction({'outcome':'extracted','events':[row]}, source(), 'GSE1', ['GSM1'])
    assert result['events'][0]['values']['Pert_type'] == 'small_molecule'
    assert result['events'][0]['values']['Collection_methods'] == 'NA'
    assert not result['blockers']
