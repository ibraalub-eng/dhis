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


# ── Uploads are authoritative for indicator names ────────────────────────────

def _write_renamed_indicator_csv(tmp_path, filename="renamed.csv",
                                 label="Cardiac Disorders Requiring CCU or ICU admission"):
    data = (
        "organisationunitname,month,"
        f"SRH IPD (10.h) {label}\n"
        "Hospital A,2026-04,4\n"
    )
    path = tmp_path / filename
    path.write_text(data, encoding="utf-8")
    return str(path)


def test_display_name_from_colname_strips_code_and_dataset_prefix():
    from app.utils.excel_parser import _display_name_from_colname
    got = _display_name_from_colname(
        "SRH IPD (10.h) Cardiac Disorders Requiring CCU or ICU admission", "10.h")
    assert got == "Cardiac Disorders Requiring CCU or ICU admission"


def test_display_name_returns_none_when_header_has_no_label():
    """A header that is only a code carries no wording; returning None stops a
    good stored name from being overwritten with the bare code."""
    from app.utils.excel_parser import _display_name_from_colname
    assert _display_name_from_colname("SRH IPD (10.h)", "10.h") is None
    assert _display_name_from_colname("(10.h)", "10.h") is None
    assert _display_name_from_colname("10.h", "10.h") is None


def test_rename_detected_for_known_code(tmp_path):
    """The bug: a known code whose header wording changed must register a
    rename instead of silently keeping the catalog name."""
    df = parse_excel(_write_renamed_indicator_csv(tmp_path))
    assert "10.h" in df.columns
    renamed = df.attrs["renamed_indicators"]
    assert renamed["10.h"] == "Cardiac Disorders Requiring CCU or ICU admission"
    # A known code must not be treated as a brand-new indicator.
    assert "10.h" not in (df.attrs["new_indicators"] or {})


def test_no_rename_when_header_matches_stored_name(tmp_path):
    df = parse_excel(
        _write_renamed_indicator_csv(tmp_path, filename="same.csv",
                                     label="Cardiac ICU admission"))
    assert "10.h" not in (df.attrs["renamed_indicators"] or {})


def test_upload_applies_indicator_rename(db_session, tmp_path):
    """End-to-end: after upload, Indicator.name reflects the file's wording."""
    from app.models import Indicator
    from app.utils.excel_parser import process_excel_upload

    result = process_excel_upload(_write_renamed_indicator_csv(tmp_path), db_session)
    renamed = {r["code"]: r for r in result["renamed_indicators"]}
    assert "10.h" in renamed
    assert renamed["10.h"]["name"] == "Cardiac Disorders Requiring CCU or ICU admission"
    assert renamed["10.h"]["previous_name"] == "Cardiac ICU admission"

    stored = db_session.query(Indicator).filter(Indicator.code == "10.h").first()
    assert stored.name == "Cardiac Disorders Requiring CCU or ICU admission"


def test_rename_does_not_disturb_values_or_other_indicators(db_session, tmp_path):
    """A rename must only touch the label — values and sibling names hold."""
    from app.models import Indicator, IndicatorValue
    from app.utils.excel_parser import process_excel_upload

    before_2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
    name_before = before_2.name
    process_excel_upload(_write_renamed_indicator_csv(tmp_path), db_session)

    assert db_session.query(Indicator).filter(Indicator.code == "2").first().name == name_before
    ind_h = db_session.query(Indicator).filter(Indicator.code == "10.h").first()
    assert db_session.query(IndicatorValue).filter(
        IndicatorValue.indicator_id == ind_h.id).count() == 1


def test_upload_worker_result_carries_indicator_renames(db_session, tmp_path,
                                                       monkeypatch):
    """The endpoint the upload screen actually calls must report the rename.

    `process_excel_upload` returns `renamed_indicators`, but
    /analysis/process-preview's worker built its own result dict and dropped
    both it and `new_indicators` — so the catalog was rewritten (every report,
    tree and drilldown then shows the new label) with nothing in the API
    response, the UI, or the logs to show that it happened.
    """
    import app.api.file_ops as file_ops

    def _fake_process(file_path, db):
        return {
            "filename": "renamed.csv", "rows_imported": 1, "months": ["2026-04"],
            "hospitals": [], "new_indicators": [{"code": "99.z", "name": "Brand new"}],
            "renamed_indicators": [
                {"code": "10.h", "previous_name": "Cardiac ICU admission",
                 "name": "Cardiac Disorders Requiring CCU or ICU admission"},
            ],
        }

    monkeypatch.setattr(file_ops, "process_excel_upload", _fake_process)
    monkeypatch.setattr(file_ops, "_get_hospitals_from_ids", lambda db, ids: [])
    monkeypatch.setattr(file_ops, "_run_quality_reports", lambda *a, **k: [])
    monkeypatch.setattr(file_ops, "_run_trend_analyses", lambda *a, **k: [])
    monkeypatch.setattr(file_ops, "_run_hospital_comparisons", lambda *a, **k: {})
    monkeypatch.setattr(file_ops, "_run_clinical_analyses", lambda *a, **k: {})

    out = file_ops._process_preview_worker("renamed.csv")
    assert out["renamed_indicators"] == [
        {"code": "10.h", "previous_name": "Cardiac ICU admission",
         "name": "Cardiac Disorders Requiring CCU or ICU admission"},
    ]
    assert out["new_indicators"] == [{"code": "99.z", "name": "Brand new"}]


def test_upload_status_summarises_catalog_changes():
    """The rename must reach the uploader's screen: a silent catalog rewrite
    (or a typo'd header) is not auditable afterwards."""
    import json
    import os
    import subprocess
    import tempfile

    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "static", "js", "upload.js"),
            encoding="utf-8") as f:
        js = f.read()
    start = js.index("function _catalogChangeSummary(")
    src = js[start:]
    i = src.index("{")
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                src = src[:j + 1]
                break

    def _summary(result):
        script = ("function __(s){return s;}\n" + src + "\n"
                  "process.stdout.write(JSON.stringify(_catalogChangeSummary("
                  + json.dumps(result) + ")));")
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8",
                                         delete=False) as fh:
            fh.write(script)
            path = fh.name
        try:
            res = subprocess.run(["node", path], capture_output=True, text=True,
                                 encoding="utf-8")
        finally:
            os.unlink(path)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)

    # nothing changed → the success message stays exactly as it was
    assert _summary({"renamed_indicators": [], "new_indicators": []}) == ""
    text = _summary({"renamed_indicators": [
        {"code": "10.h", "previous_name": "Cardiac ICU admission",
         "name": "Cardiac Disorders Requiring CCU or ICU admission"}],
        "new_indicators": []})
    assert "10.h" in text and "Cardiac ICU admission" in text
    assert "Cardiac Disorders Requiring CCU or ICU admission" in text


def test_year_column_not_registered_as_indicator(tmp_path):
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


# ─────────────────── test/preview upload guard ───────────────────────

def _write_testish(tmp_path, filename, org):
    p = tmp_path / filename
    p.write_text(
        "organisationunitname,month,Total Deliveries\n"
        f"{org},2026-04,300\n",
        encoding="utf-8",
    )
    return str(p)


def test_guard_rejects_preview_filename(db_session, tmp_path):
    """A preview_*/test_* file must never auto-create hospitals (this exact
    file recreated a phantom 'Test Hospital' twice)."""
    from app.models import Hospital
    from app.utils.excel_parser import process_excel_upload

    with pytest.raises(ValueError, match="test/preview"):
        process_excel_upload(
            _write_testish(tmp_path, "preview_test_pt1.csv", "Test Hospital"), db_session
        )
    assert db_session.query(Hospital).filter(Hospital.name == "Test Hospital").count() == 0


def test_guard_rejects_test_organisation_name(db_session, tmp_path):
    """A legit-looking filename whose organisation rows are test entries is
    also rejected — the file content is what creates the ghost."""
    from app.models import Hospital
    from app.utils.excel_parser import process_excel_upload

    with pytest.raises(ValueError, match="test entry"):
        process_excel_upload(
            _write_testish(tmp_path, "monthly_report.csv", "Test Hospital"), db_session
        )
    assert db_session.query(Hospital).filter(Hospital.name == "Test Hospital").count() == 0


def test_guard_rejects_arabic_test_name(db_session, tmp_path):
    from app.models import Hospital
    from app.utils.excel_parser import process_excel_upload

    with pytest.raises(ValueError, match="test"):
        process_excel_upload(
            _write_testish(tmp_path, "report.csv", "مستشفى اختبار"), db_session
        )
    assert db_session.query(Hospital).filter(Hospital.name == "مستشفى اختبار").count() == 0


def test_guard_allows_real_hospitals(db_session, tmp_path):
    """Real facility names must pass untouched (no false positives on names
    that merely contain 'latest'/'contest'-style substrings)."""
    from app.models import Hospital
    from app.utils.excel_parser import process_excel_upload

    result = process_excel_upload(
        _write_testish(tmp_path, "monthly_data.csv", "Al-Shifa Hospital"), db_session
    )
    assert result["new_hospitals"] == 1
    assert db_session.query(Hospital).filter(Hospital.name == "Al-Shifa Hospital").count() == 1