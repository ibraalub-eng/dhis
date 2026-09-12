import pytest
import pandas as pd

from app.utils.excel_parser import parse_excel, normalize_data


@pytest.fixture
def sample_excel(tmp_path):
    data = {
        "organisationunitname": ["Hospital A", "Hospital B"],
        "month": ["2026-04", "2026-04"],
        "Total Deliveries": [300, 250],
        "Normal Vaginal Deliveries": [200, 170],
        "Caesarean Sections": [80, 60],
        "Live Births": [290, 240],
        "Maternal Deaths": [1, 0],
        "Neonatal deaths": [5, 3],
    }
    df = pd.DataFrame(data)
    file_path = tmp_path / "test_data.xlsx"
    df.to_excel(str(file_path), index=False, engine="openpyxl")
    return str(file_path)


def test_parse_excel(sample_excel):
    df = parse_excel(sample_excel)
    assert "organisationunitname" in df.columns
    assert "month" in df.columns
    assert "2" in df.columns or "Total Deliveries" in df.columns


def test_normalize_data(sample_excel):
    df = parse_excel(sample_excel)
    records = normalize_data(df)
    assert len(records) > 0
    assert all("hospital_name" in r for r in records)
    assert all("indicator_code" in r for r in records)
    assert all("month" in r for r in records)


def test_normalize_preserves_values(sample_excel):
    df = parse_excel(sample_excel)
    records = normalize_data(df)
    td_records = [r for r in records if r["indicator_code"] == "2"]
    assert len(td_records) == 2
    values = [r["value"] for r in td_records if r["value"] is not None]
    assert 300 in values or 250 in values


@pytest.fixture
def sample_excel_with_title_row(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Monthly Report - April 2026"])
    ws.append([])
    ws.append(["organisationunitname", "month", "Total Deliveries", "Normal Vaginal Deliveries",
                "Caesarean Sections", "Live Births", "Maternal Deaths", "Neonatal deaths"])
    ws.append(["Hospital A", "2026-04", 300, 200, 80, 290, 1, 5])
    ws.append(["Hospital B", "2026-04", 250, 170, 60, 240, 0, 3])
    file_path = tmp_path / "test_title_row.xlsx"
    wb.save(str(file_path))
    return str(file_path)


def test_parse_excel_with_title_row(sample_excel_with_title_row):
    df = parse_excel(sample_excel_with_title_row)
    assert "organisationunitname" in df.columns
    assert "2" in df.columns or "Total Deliveries" in df.columns
    assert len(df) >= 2


def test_normalize_with_title_row(sample_excel_with_title_row):
    df = parse_excel(sample_excel_with_title_row)
    records = normalize_data(df)
    assert len(records) > 0
    hospitals = set(r["hospital_name"] for r in records)
    assert "Hospital A" in hospitals or any("Hospital A" in h for h in hospitals)


@pytest.fixture
def sample_csv(tmp_path):
    data = (
        "organisationunitname,month,Total Deliveries,Normal Vaginal Deliveries,"
        "Caesarean Sections,Live Births,Maternal Deaths,Neonatal deaths\n"
        "Hospital A,2026-04,300,200,80,290,1,5\n"
        "Hospital B,2026-04,250,170,60,240,0,3\n"
    )
    file_path = tmp_path / "test_data.csv"
    file_path.write_text(data, encoding="utf-8")
    return str(file_path)


def test_parse_csv(sample_csv):
    df = parse_excel(sample_csv)
    assert "organisationunitname" in df.columns
    assert len(df) >= 2


# ── Auto-registration of new indicator codes ───────────────────────────────

def _write_new_indicator_csv(tmp_path, filename="new_ind.csv", value=12):
    data = (
        "organisationunitname,month,NewIndicator Alpha (99.a),NewIndicator Beta (99.b)\n"
        f"Hospital A,2026-04,{value},7\n"
    )
    path = tmp_path / filename
    path.write_text(data, encoding="utf-8")
    return str(path)


def test_normalize_recognizes_new_indicator_columns(tmp_path):
    df = parse_excel(_write_new_indicator_csv(tmp_path))
    assert "99.a" in df.columns
    assert "99.b" in df.columns
    codes = {r["indicator_code"] for r in normalize_data(df)}
    assert {"99.a", "99.b"} <= codes


def test_import_auto_registers_new_indicators(db_session, tmp_path):
    from app.models import Indicator, IndicatorValue
    from app.utils.excel_parser import process_excel_upload

    result = process_excel_upload(_write_new_indicator_csv(tmp_path), db_session)
    created = {i["code"] for i in result["new_indicators"]}
    assert {"99", "99.a", "99.b"} <= created

    parent = db_session.query(Indicator).filter(Indicator.code == "99").first()
    child = db_session.query(Indicator).filter(Indicator.code == "99.a").first()
    assert parent is not None and child is not None
    assert child.parent_id == parent.id
    assert child.level == parent.level + 1
    assert db_session.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == child.id).count() == 1


def test_year_column_not_registered_as_indicator(tmp_path):
    """A bare 4-digit year column must not be treated as an indicator code."""
    p = tmp_path / "with_year.csv"
    p.write_text(
        "organisationunitname,month,2026,Total Deliveries\n"
        "Hospital A,2026-04,1,300\n",
        encoding="utf-8",
    )
    df = parse_excel(str(p))
    codes = {r["indicator_code"] for r in normalize_data(df)}
    assert "2026" not in codes
    assert "2" in codes


def test_import_updates_existing_value_in_place(db_session, tmp_path):
    from app.models import Indicator, IndicatorValue
    from app.utils.excel_parser import process_excel_upload

    def _write(name, value):
        p = tmp_path / name
        p.write_text(
            "organisationunitname,month,Total Deliveries\n"
            f"Hospital Upd,2026-05,{value}\n",
            encoding="utf-8",
        )
        return str(p)

    process_excel_upload(_write("u1.csv", 100), db_session)
    process_excel_upload(_write("u2.csv", 250), db_session)

    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    rows = db_session.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == ind.id,
        IndicatorValue.month == "2026-05",
    ).all()
    assert len(rows) == 1
    assert rows[0].value == 250