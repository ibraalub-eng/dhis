import pandas as pd
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import Hospital, Indicator, IndicatorValue
from app.indicators import INDICATOR_NAME_TO_CODE, INDICATOR_FLAT_LIST
import os
import re
import logging

logger = logging.getLogger(__name__)

HEADER_KEYWORDS = [
    "organisationunitname", "organizationunitname", "orgunit",
    "organisation unit", "organization unit",
    "facility", "hospital", "healthfacility", "health facility",
]


def _extract_month_from_text(text: str) -> Optional[str]:
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
    }
    text_lower = text.lower().strip()
    ym = re.search(r"(\d{4})\s*[-/]\s*(\d{1,2})", text_lower)
    if ym:
        return f"{ym.group(1)}-{ym.group(2).zfill(2)}"
    ym2 = re.search(r"(\d{1,2})\s*[-/]\s*(\d{4})", text_lower)
    if ym2:
        return f"{ym2.group(2)}-{ym2.group(1).zfill(2)}"
    for mname, mnum in month_map.items():
        if mname in text_lower:
            yr = re.search(r"(\d{4})", text)
            if yr:
                return f"{yr.group(1)}-{mnum}"
            yr = re.search(r"(\d{4})", text)
            if yr is None:
                yr2 = re.search(r"(?:^|\D)(\d{2,4})(?:\D|$)", text)
                if yr2:
                    y = int(yr2.group(1))
                    if y < 100:
                        y += 2000
                    return f"{y}-{mnum}"
            break
    ym3 = re.search(r"(\d{4})(\d{2})", text)
    if ym3:
        return f"{ym3.group(1)}-{ym3.group(2)}"
    return None


def _find_header_row(file_path: str, engine: str, sheet_name: str = 0) -> Tuple[int, pd.DataFrame]:
    max_scan = min(20, 20)
    for header_row in range(max_scan):
        try:
            df = pd.read_excel(file_path, engine=engine, sheet_name=sheet_name, header=header_row)
        except Exception:
            continue
        if df.empty and header_row == 0:
            continue
        cols_lower = [str(c).strip().lower() for c in df.columns]
        for kw in HEADER_KEYWORDS:
            if any(kw in c for c in cols_lower):
                logger.info(f"Found header row at index {header_row} (keyword: {kw})")
                return header_row, df
    for header_row in range(max_scan):
        try:
            df = pd.read_excel(file_path, engine=engine, sheet_name=sheet_name, header=header_row)
        except Exception:
            continue
        cols_lower = [str(c).strip().lower() for c in df.columns]
        matched = 0
        for col in cols_lower:
            for ind_name, ind_code in INDICATOR_NAME_TO_CODE.items():
                if ind_name.lower().strip() == col or col in ind_name.lower().strip():
                    matched += 1
                    break
        if matched >= 3:
            logger.info(f"Found header row at index {header_row} ({matched} indicator columns)")
            return header_row, df
    return 0, pd.read_excel(file_path, engine=engine, sheet_name=sheet_name)


def _extract_month_from_sheet(file_path: str, engine: str, header_row: int, sheet_name=0) -> Optional[str]:
    try:
        df_raw = pd.read_excel(file_path, engine=engine, sheet_name=sheet_name, header=None, nrows=header_row + 2)
        for r in range(df_raw.shape[0]):
            for c in range(df_raw.shape[1]):
                cell = df_raw.iloc[r, c]
                if pd.isna(cell):
                    continue
                text = str(cell).strip()
                if not text:
                    continue
                month_str = _extract_month_from_text(text)
                if month_str:
                    logger.info(f"Extracted month '{month_str}' from cell ({r},{c}): '{text}'")
                    return month_str
    except Exception as e:
        logger.warning(f"Could not extract month from title rows: {e}")
    return None


def parse_excel(file_path: str) -> pd.DataFrame:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return _parse_csv(file_path)

    engines = []
    if ext == ".xls":
        engines = ["xlrd", "openpyxl"]
    elif ext == ".xlsx":
        engines = ["openpyxl", "calamine", "xlrd"]
    else:
        engines = ["openpyxl", "xlrd", "calamine"]

    errors = []

    for engine in engines:
        try:
            xl = pd.ExcelFile(file_path, engine=engine)
        except Exception as e:
            errors.append(f"Engine {engine}: cannot open file - {e}")
            continue

        for sheet_name in xl.sheet_names:
            try:
                header_row, df = _find_header_row(file_path, engine, sheet_name)
                if df.empty:
                    continue
                month_extracted = _extract_month_from_sheet(file_path, engine, header_row, sheet_name)
                df = _rename_columns(df, default_month=month_extracted)
                if "organisationunitname" in df.columns or any(
                    kw in str(c).lower() for c in df.columns for kw in HEADER_KEYWORDS
                ):
                    return df
                indicator_cols = [c for c in df.columns if c in set(ind["code"] for ind in INDICATOR_FLAT_LIST)]
                if len(indicator_cols) >= 3:
                    return df
            except Exception as e:
                errors.append(f"Engine {engine}, sheet {sheet_name}: {e}")
                continue

    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(file_path, sep=sep, encoding="utf-8", encoding_errors="replace")
            if not df.empty and len(df.columns) > 1:
                month_extracted = None
                for col in df.columns[:5]:
                    month_extracted = _extract_month_from_text(str(col))
                    if month_extracted:
                        break
                df = _rename_columns(df, default_month=month_extracted)
                if "organisationunitname" in df.columns:
                    return df
        except Exception:
            pass

    raise ValueError(
        "Could not parse file. Ensure it has a header row with 'organisationunitname' "
        "(or 'hospital'/'facility') and indicator columns. "
        f"Errors: {'; '.join(errors)[:300]}"
    )


def _parse_csv(file_path: str) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1256"]:
        for sep in [",", ";", "\t", "|"]:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding=enc)
                if not df.empty and len(df.columns) > 1:
                    return _rename_columns(df)
            except Exception:
                pass
    raise ValueError("Could not read CSV file. Check encoding and delimiter.")


MONTH_COL_KEYWORDS = [
    "month", "period", "reporting_period", "reporting period",
    "periodname", "period name", "reportingmonth", "reporting month",
]

# Mapping from column-name codes to indicator codes where they differ
CODE_ALIAS_MAP = {
    "17.c.1": "RDS",
    "17.c.2": "Sepsis_preterm",
    "2.l": "2.l",
    "2.L": "2.l",
}


def _extract_code_from_colname(col_name: str) -> Optional[str]:
    """Extract indicator code from column names like 'SRH IPD (10.a.2) Antepartum hemorrhage'.
    Returns the code string (e.g. '10.a.2') or None."""
    m = re.search(r'\(([\w.]+)\)', col_name)
    if m:
        code = m.group(1)
        # Skip codes that are just single letters (not indicator codes)
        if re.match(r'^[a-zA-Z]$', code):
            return None
        # Apply alias mapping
        return CODE_ALIAS_MAP.get(code, code)
    return None


def _rename_columns(df: pd.DataFrame, default_month: Optional[str] = None) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    month_found = False
    # Track which indicator codes have already been mapped (avoid duplicates)
    mapped_codes = set()

    # Build code-to-name lookup (case-insensitive)
    code_to_name_lower = {}
    for ind in INDICATOR_FLAT_LIST:
        code_to_name_lower[ind["code"].lower()] = ind["code"]

    def _try_map(col: str, indicator_code: str) -> bool:
        """Map a column to an indicator code if not already taken. Returns True if mapped."""
        if indicator_code in mapped_codes:
            return False
        col_map[col] = indicator_code
        mapped_codes.add(indicator_code)
        return True

    for col in df.columns:
        cl = col.lower().strip()

        # Skip deleted/NA columns
        if "deleted" in cl or "(na)" in cl:
            continue

        # 1. Hospital name column
        if any(kw in cl for kw in HEADER_KEYWORDS):
            col_map[col] = "organisationunitname"
            continue

        # 2. Month/period column
        if any(cl == kw or cl == kw.replace("_", "").replace(" ", "") for kw in MONTH_COL_KEYWORDS):
            col_map[col] = "month"
            month_found = True
            continue
        if any(kw in cl for kw in MONTH_COL_KEYWORDS):
            col_map[col] = "month"
            month_found = True
            continue

        # 3. Try to extract indicator code from parenthesized number, e.g. (10.a.2)
        extracted_code = _extract_code_from_colname(col)
        if extracted_code:
            # Case-insensitive lookup
            matched = code_to_name_lower.get(extracted_code.lower())
            if matched:
                if _try_map(col, matched):
                    continue

        # 4. Exact name match
        matched = INDICATOR_NAME_TO_CODE.get(col)
        if matched:
            if _try_map(col, matched):
                continue

        # 5. Fuzzy name match
        best = _fuzzy_match_indicator(col)
        if best:
            if _try_map(col, best):
                continue

    df = df.rename(columns=col_map)
    df = df.loc[:, ~df.columns.duplicated()]
    if not month_found and default_month:
        df["month"] = default_month
        logger.info(f"Added month column from title row: {default_month}")
    df = df.dropna(subset=["organisationunitname"], how="all") if "organisationunitname" in df.columns else df
    for col in df.columns:
        if col == "organisationunitname" or col == "month":
            s = df[col]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            df[col] = s.astype(str).str.strip().replace("nan", "")
    return df


def _fuzzy_match_indicator(col_name: str) -> Optional[str]:
    cleaned = col_name.strip().lower()
    exact_matches = []
    partial_matches = []
    for name, code in INDICATOR_NAME_TO_CODE.items():
        name_lower = name.lower().strip()
        if name_lower == cleaned:
            return code
        if cleaned in name_lower:
            exact_matches.append((code, name, len(name)))
        if name_lower in cleaned:
            partial_matches.append((code, name, len(name)))
    if exact_matches:
        exact_matches.sort(key=lambda x: x[2])
        return exact_matches[0][0]
    if partial_matches:
        partial_matches.sort(key=lambda x: x[2])
        return partial_matches[0][0]
    cleaned_stripped = re.sub(r"[^a-z0-9]", "", cleaned)
    for name, code in INDICATOR_NAME_TO_CODE.items():
        name_stripped = re.sub(r"[^a-z0-9]", "", name.lower().strip())
        if name_stripped == cleaned_stripped:
            return code
    return None


def normalize_data(df: pd.DataFrame) -> List[Dict]:
    records = []
    if "organisationunitname" not in df.columns:
        raise ValueError(
            "Excel file must contain a column for organisationunitname (hospital name). "
            f"Found columns: {list(df.columns[:20])}"
        )
    if "month" not in df.columns:
        raise ValueError(
            "Excel file must contain a 'month' column (YYYY-MM format), "
            "or a title row with the month name (e.g., 'January 2026'). "
            f"Found columns: {list(df.columns[:20])}"
        )
    indicator_codes = set(ind["code"] for ind in INDICATOR_FLAT_LIST)
    value_cols = [c for c in df.columns if c in indicator_codes]
    if not value_cols:
        raise ValueError(
            "No recognized indicator columns found. "
            "Column names must match the SRMNH indicator names. "
            f"Found columns: {list(df.columns[:20])}"
        )
    for _, row in df.iterrows():
        raw_hosp = row.get("organisationunitname", "")
        if isinstance(raw_hosp, pd.Series):
            raw_hosp = raw_hosp.iloc[0] if len(raw_hosp) > 0 else ""
        hospital_name = "" if pd.isna(raw_hosp) else str(raw_hosp).strip()
        raw_month = row.get("month", "")
        if isinstance(raw_month, pd.Series):
            raw_month = raw_month.iloc[0] if len(raw_month) > 0 else ""
        month = "" if pd.isna(raw_month) else str(raw_month).strip()
        if re.match(r'^\d{4}-\d{2}$', month):
            pass
        elif month:
            extracted = _extract_month_from_text(month)
            if extracted:
                month = extracted
        if not hospital_name or not month:
            continue
        if hospital_name.lower() in ("", "nan", "none", "total", "summary"):
            continue
        for code in value_cols:
            val = row.get(code)
            if pd.isna(val) or val == "" or val is None:
                numeric_val = None
            else:
                try:
                    numeric_val = float(val)
                except (ValueError, TypeError):
                    numeric_val = None
            records.append(
                {
                    "hospital_name": hospital_name,
                    "indicator_code": code,
                    "month": month,
                    "value": numeric_val,
                }
            )
    if not records:
        logger.warning(
            "No data records extracted. DataFrame shape: %s, Columns: %s",
            df.shape, list(df.columns[:20])
        )
    return records


def import_data_to_db(records: List[Dict], session: Session, source_file: str = "") -> Tuple[int, int]:
    hospitals_cache = {}
    indicators_cache = {}
    for ind in session.query(Indicator).all():
        indicators_cache[ind.code] = ind.id
    for hosp in session.query(Hospital).all():
        hospitals_cache[hosp.name] = hosp.id
    new_hospitals = 0
    processed = 0
    for rec in records:
        hosp_name = rec["hospital_name"]
        if hosp_name not in hospitals_cache:
            hosp = Hospital(name=hosp_name)
            session.add(hosp)
            session.flush()
            hospitals_cache[hosp_name] = hosp.id
            new_hospitals += 1
        indicator_code = rec["indicator_code"]
        if indicator_code not in indicators_cache:
            continue
        ind_id = indicators_cache[indicator_code]
        hosp_id = hospitals_cache[hosp_name]
        existing = (
            session.query(IndicatorValue)
            .filter(
                IndicatorValue.hospital_id == hosp_id,
                IndicatorValue.indicator_id == ind_id,
                IndicatorValue.month == rec["month"],
            )
            .first()
        )
        if existing:
            existing.value = rec["value"]
            if source_file:
                existing.source_file = source_file
        else:
            iv = IndicatorValue(
                hospital_id=hosp_id,
                indicator_id=ind_id,
                month=rec["month"],
                value=rec["value"],
                source_file=source_file if source_file else None,
            )
            session.add(iv)
        processed += 1
    session.commit()
    return new_hospitals, processed


def process_excel_upload(file_path: str, session: Session) -> Dict:
    filename = os.path.basename(file_path)
    df = parse_excel(file_path)
    records = normalize_data(df)
    if not records:
        raise ValueError(
            f"No data records found in '{filename}'. "
            "Please check that the file has hospital names in an 'organisationunitname' column "
            "(or 'hospital'/'facility'), indicator columns matching SRMNH names, "
            "and a 'month' column or a title row with the reporting period."
        )
    new_hospitals, new_values = import_data_to_db(records, session, source_file=filename)

    hospital_names = sorted(set(r["hospital_name"] for r in records))
    months = sorted(set(r["month"] for r in records))

    hosp_records = (
        session.query(Hospital)
        .filter(Hospital.name.in_(hospital_names))
        .all()
    )
    hospitals_list = [{"id": h.id, "name": h.name} for h in hosp_records]

    return {
        "filename": filename,
        "hospitals_processed": len(hospital_names),
        "rows_imported": new_values,
        "new_hospitals": new_hospitals,
        "message": f"Processed {new_values} indicator values for {len(hospital_names)} hospitals",
        "hospitals": hospitals_list,
        "months": months,
    }