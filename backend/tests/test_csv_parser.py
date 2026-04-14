import pytest
from backend.worker.csv_parser import parse_csv

def test_parse_standard_csv():
    content = b"GSE,title,summary\nGSE001,Study A,A human study\nGSE002,Study B,A mouse study\n"
    rows = parse_csv(content)
    assert len(rows) == 2
    assert rows[0]["id"] == "GSE001"
    assert rows[0]["title"] == "Study A"
    assert rows[0]["description"] == "A human study"

def test_parse_bom_csv():
    content = "\ufeffGSE,title,summary\nGSE003,Study C,desc\n".encode("utf-8-sig")
    rows = parse_csv(content)
    assert rows[0]["id"] == "GSE003"

def test_parse_missing_id_column():
    content = b"name,description\nfoo,bar\n"
    with pytest.raises(ValueError, match="missing ID column"):
        parse_csv(content)

def test_parse_skips_empty_ids():
    content = b"GSE,title\nGSE001,A\n,B\nGSE002,C\n"
    rows = parse_csv(content)
    assert len(rows) == 2
