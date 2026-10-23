import pandas as pd
from typing import List, Dict, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import Hospital, Indicator, IndicatorValue
from app.indicators import INDICATOR_NAME_TO_CODE, INDICATOR_FLAT_LIST
import os
import re
import logging

logger = logging.getLogger(__name__)

# Test/preview uploads must never auto-create real hospitals. We have twice
# purged a phantom "Test Hospital" that reappeared because the import
# pipeline auto-creates a hospital for every unknown organisationunitname.
# Both the file name and the organisation names are checked so a spreadsheet
# full of "Test Hospital 1..N" rows is rejected too.
_TEST_NAME_PATTERNS = re.compile(
    r"(^|[^a-z\u0600-\u06FF])(test|preview|dummy|sample|fixture)([^a-z\u0600-\u06FF]|$)",
    re.IGNORECASE,
)
_ARABIC_TEST_WORDS = ("اختبار", "تجربة")


# ── Hospital-name matching ───────────────────────────────────────────────────
# DHIS exports carry the full organisation-unit path
# ("وزارة الصحة/مستشفيات/مستشفى الشفاء") while the registry keeps the short
# facility name ("مستشفى الشفاء"). Raw-string matching fails on the path
# words, the "/PRCS"-style org suffixes and spelling variants ("مستشفى" vs
# "مستشفي" — same word, two spellings), and every miss created a *duplicate*
# hospital holding a second copy of the values. Match on a normalised core
# name instead.
_ORG_PATH_SEGMENTS = {
    # Values are compared AFTER _norm_hospital_text(), hence folded spelling.
    "وزاره الصحه", "مستشفيات", "المستشفي", "وزاره", "صحه",
    "ministry of health", "health ministry", "hospitals", "hospital",
}
# Organisation-type tokens that ride along at the end of DHIS names.
_ORG_SUFFIX_TOKENS = {
    "prcs", "imc", "icrc", "msf", "who", "unfpa", "unicef", "ocha", "uk", "med",
}
_ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u0652\u0670\u0640]")  # tashkeel + tatweel
_NON_WORD_RE = re.compile(r"[^0-9a-z\u0600-\u06ff]+")
_ARABIC_FOLD = str.maketrans("أإآٱىة", "اااايه")


def _norm_hospital_text(value) -> str:
    """Case/diacritic/punctuation-insensitive form of a hospital name.

    Unifies alef variants, ta-marbuta and final ya so "مستشفى"/"مستشفي"
    compare equal, strips LTR/RTL marks and zero-width chars, and turns every
    separator (spaces, slashes, dashes) into a single space.
    """
    s = str(value or "")
    s = s.replace("\u200f", "").replace("\u200e", "").replace("\u200d", "").replace("\ufeff", "")
    s = _ARABIC_DIACRITICS_RE.sub("", s)
    s = s.translate(_ARABIC_FOLD).lower()
    return " ".join(_NON_WORD_RE.sub(" ", s).split())


def _hospital_core_name(name) -> str:
    """Facility name without DHIS path words or org-type suffixes.

    "العودة/مستشفيات/مستشفى العودة- جباليا" -> "مستشفى العودة جباليا"
    "مستشفيات/ مستشفي القدس/PRCS"          -> "مستشفي القدس"
    "مستشفى الشفاء"                        -> "مستشفى الشفاء"
    """
    parts = [_norm_hospital_text(p) for p in str(name or "").split("/")]
    parts = [p for p in parts if p and p not in _ORG_PATH_SEGMENTS]
    # The org type can be its own trailing segment ("…/مستشفى القدس/PRCS") —
    # drop pure-suffix segments before taking the facility segment.
    while parts and set(parts[-1].split()) <= _ORG_SUFFIX_TOKENS:
        parts.pop()
    core = parts[-1] if parts else _norm_hospital_text(name)
    tokens = core.split()
    while len(tokens) > 1 and tokens[-1] in _ORG_SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _looks_like_test_upload(filename: str, hospital_names) -> List[str]:
    """Return the reasons this upload looks like test/preview data (empty = OK)."""
    reasons = []
    base = (filename or "").rsplit(".", 1)[0].strip().lower()
    # Filename like preview_test_pt1 / test_tid / test_ua: match 'test'/'preview'
    # as a token inside the base name.
    if _TEST_NAME_PATTERNS.search(base) or any(w in base for w in _ARABIC_TEST_WORDS):
        reasons.append(f"filename '{filename}' contains test/preview markers")
    for name in hospital_names:
        n = str(name or "").strip().lower()
        if not n:
            continue
        if _TEST_NAME_PATTERNS.search(n) or n in ("test hospital", "test") \
                or any(w in n for w in _ARABIC_TEST_WORDS):
            reasons.append(f"organisation name '{name}' looks like a test entry")
    return reasons

HEADER_KEYWORDS = [
    "organisationunitname", "organizationunitname", "orgunit",
    "organisation unit", "organization unit",
    "facility", "hospital", "healthfacility", "health facility",
]

# A column whose header *resolves to a real indicator* is never the facility
# column, however many hospital-ish words its label contains. The DHIS exports
# use headers such as "SRH IPD (11.a) Maternal deaths at the hospital" and
# "SRH IPD (2.k) Deliveries happened at the hospital" — the bare
# HEADER_KEYWORDS substring test used to claim those as organisationunitname,
# and df.columns.duplicated() then silently dropped them, so 2.k/2.l/11.a/11.b
# lost every value on import. Resolve the indicator first; only fall back to the
# keyword test when the header is not an indicator at all.
def _resolves_to_indicator(col: str, code_to_name_lower: Dict[str, str]) -> bool:
    extracted = _extract_code_from_colname(col)
    if extracted and code_to_name_lower.get(extracted.lower()):
        return True
    if col in INDICATOR_NAME_TO_CODE:
        return True
    return _fuzzy_match_indicator(col) is not None


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


def parse_excel(file_path: str, known_code_to_name: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return _parse_csv(file_path, known_code_to_name=known_code_to_name)

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
                df = _rename_columns(df, default_month=month_extracted, known_code_to_name=known_code_to_name)
                if "organisationunitname" in df.columns or any(
                    kw in str(c).lower() for c in df.columns for kw in HEADER_KEYWORDS
                ):
                    return df
                known_codes = set(_known_code_lookup(known_code_to_name).values())
                indicator_cols = [
                    c for c in df.columns
                    if c in known_codes or _is_likely_indicator_code(c)
                ]
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
                df = _rename_columns(df, default_month=month_extracted, known_code_to_name=known_code_to_name)
                if "organisationunitname" in df.columns:
                    return df
        except Exception:
            pass

    raise ValueError(
        "Could not parse file. Ensure it has a header row with 'organisationunitname' "
        "(or 'hospital'/'facility') and indicator columns. "
        f"Errors: {'; '.join(errors)[:300]}"
    )


def _parse_csv(file_path: str, known_code_to_name: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1256"]:
        for sep in [",", ";", "\t", "|"]:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding=enc)
                if not df.empty and len(df.columns) > 1:
                    return _rename_columns(df, known_code_to_name=known_code_to_name)
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


def _display_name_from_colname(col_name: str, indicator_code: str) -> Optional[str]:
    """Extract the human-readable label from a header like
    'SRH IPD (10.h) Cardiac Disorders Requiring CCU or ICU admission'.

    Returns 'Cardiac Disorders Requiring CCU or ICU admission', or None when the
    header carries no usable text beyond the code (so we never overwrite a good
    stored name with a bare code or an empty string).
    """
    # Drop the parenthesised code and any leading dataset/report prefix
    # ("SRH IPD", "SRH", "IPD", ...) that precedes it.
    without_code = re.sub(r"\([^)]*\)", " ", col_name)
    parts = [p for p in re.split(r"\s*\(\s*\w[\w.]*\s*\)\s*", " " + without_code) if p.strip()]
    label = parts[-1] if parts else ""
    # Strip a leading dataset token sequence (SRH IPD, SRH, IPD, ...) left of the
    # code. Matched conservatively: only known report prefixes, never a word that
    # is part of the actual indicator name.
    label = re.sub(
        r"^\s*(?:SRH\s+IPD|SRH\s+OPD|SRH|IPD|OPD|IPD\s+SUMMARY|SUMMARY)\b[\s:,-]*",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(r"\s+", " ", label).strip(" \t:-–—,")
    if not label:
        return None
    # A label that is just the code carries no information.
    if label.lower() == (indicator_code or "").lower():
        return None
    return label


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


# A column header that is itself an indicator code, e.g. "2", "2.a", "5.b.1".
_INDICATOR_CODE_RE = re.compile(r'^\d+(\.[a-zA-Z0-9]+)*$')


def _is_likely_indicator_code(code: str) -> bool:
    """Code-shaped header that is not a bare 4-digit year/period column."""
    code = str(code).strip()
    if not _INDICATOR_CODE_RE.match(code):
        return False
    return not re.fullmatch(r'\d{4}', code)


def _known_code_lookup(known_code_to_name: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Lowercased code -> canonical code, from the static list plus DB codes."""
    lookup = {}
    for ind in INDICATOR_FLAT_LIST:
        lookup[ind["code"].lower()] = ind["code"]
    if known_code_to_name:
        for code in known_code_to_name:
            lookup.setdefault(str(code).lower(), str(code))
    return lookup


def _rename_columns(
    df: pd.DataFrame,
    default_month: Optional[str] = None,
    known_code_to_name: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    month_found = False
    # Track which indicator codes have already been mapped (avoid duplicates)
    mapped_codes = set()
    # Indicator codes found in the file that are not in the catalog yet.
    new_indicators: Dict[str, str] = {}
    # Existing indicator codes whose label in the uploaded file differs from the
    # stored name — the file is authoritative for wording.
    renamed_indicators: Dict[str, str] = {}

    # Build code-to-name lookup (case-insensitive), including DB-only codes
    code_to_name_lower = _known_code_lookup(known_code_to_name)

    # Lowercased code -> current stored display name, used to detect a rename.
    code_to_name: Dict[str, str] = {ind["code"].lower(): ind["name"] for ind in INDICATOR_FLAT_LIST}
    for code, name in (known_code_to_name or {}).items():
        code_to_name[str(code).lower()] = name

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

        # 1. Month/period column (never ambiguous: period labels carry no
        #    indicator code)
        if any(cl == kw or cl == kw.replace("_", "").replace(" ", "") for kw in MONTH_COL_KEYWORDS):
            col_map[col] = "month"
            month_found = True
            continue
        if any(kw in cl for kw in MONTH_COL_KEYWORDS):
            col_map[col] = "month"
            month_found = True
            continue

        # 2. Hospital name column — but only if this header is not itself an
        #    indicator. See _resolves_to_indicator.
        if any(kw in cl for kw in HEADER_KEYWORDS) \
                and not _resolves_to_indicator(col, code_to_name_lower):
            col_map[col] = "organisationunitname"
            continue

        # 3. Try to extract indicator code from parenthesized number, e.g. (10.a.2)
        extracted_code = _extract_code_from_colname(col)
        if extracted_code:
            # Case-insensitive lookup
            matched = code_to_name_lower.get(extracted_code.lower())
            if matched:
                if _try_map(col, matched):
                    # The header can carry a label newer than the stored name
                    # ("SRH IPD (10.h) Cardiac Disorders Requiring CCU or ICU
                    # admission"). Record it so the name follows the uploaded
                    # file instead of staying frozen at the catalog default.
                    label = _display_name_from_colname(col, matched)
                    current = code_to_name.get(matched.lower(), "")
                    if label and label.lower() != str(current).strip().lower():
                        renamed_indicators[matched] = label
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

        # 6. New indicator: a code embedded in the header like "(99.a) New metric",
        #    or a header that is itself a code-like token. Recognise it so its
        #    values import and the indicator is auto-created on save.
        embedded = _extract_code_from_colname(col)
        candidate = embedded
        if not candidate:
            token = cl.strip()
            if _is_likely_indicator_code(token):
                candidate = CODE_ALIAS_MAP.get(token, token)
        if candidate and candidate.lower() not in code_to_name_lower and candidate not in mapped_codes:
            if _try_map(col, candidate):
                display = _display_name_from_colname(col, candidate) if embedded else None
                new_indicators[candidate] = display or candidate
                continue

    df = df.rename(columns=col_map)
    # Renaming can still collide (two distinct headers resolving to one code).
    # de-duplicating is required, but it must never be silent: a dropped column
    # means an indicator silently loses every value for the month.
    collided = [c for c in df.columns[df.columns.duplicated()].unique()]
    if collided:
        logger.warning(
            "Column rename collision — dropping %d duplicate column(s): %s",
            int(df.columns.duplicated().sum()), collided,
        )
    df = df.loc[:, ~df.columns.duplicated()]
    df.attrs["new_indicators"] = new_indicators
    df.attrs["renamed_indicators"] = renamed_indicators
    if renamed_indicators:
        logger.info(
            "Indicator name changes from file (%d): %s",
            len(renamed_indicators), sorted(renamed_indicators.items()),
        )
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


def normalize_data(df: pd.DataFrame, known_code_to_name: Optional[Dict[str, str]] = None) -> List[Dict]:
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
    known_codes = set(_known_code_lookup(known_code_to_name).values())
    new_codes = set((df.attrs.get("new_indicators") or {}).keys())
    value_cols = []
    for c in df.columns:
        if c in ("organisationunitname", "month"):
            continue
        if c in known_codes or c in new_codes or _is_likely_indicator_code(c):
            value_cols.append(c)
    if not value_cols:
        raise ValueError(
            "No recognized indicator columns found. "
            "Column names must match the SRMNH indicator names or codes. "
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
            rec = {
                    "hospital_name": hospital_name,
                    "indicator_code": code,
                    "month": month,
                    "value": numeric_val,
                }
            # Include org ID if column exists
            raw_org = row.get("organisationunitid", row.get("OrganisationUnitID", ""))
            if not pd.isna(raw_org) and str(raw_org).strip():
                rec["organisation_unit_id"] = str(raw_org).strip()
            records.append(rec)
    if not records:
        logger.warning(
            "No data records extracted. DataFrame shape: %s, Columns: %s",
            df.shape, list(df.columns[:20])
        )
    return records


def import_data_to_db(
    records: List[Dict],
    session: Session,
    source_file: str = "",
    new_indicator_names: Optional[Dict[str, str]] = None,
    renamed_indicator_names: Optional[Dict[str, str]] = None,
) -> Tuple[int, int, List[Dict], List[Dict]]:
    hospitals_cache = {}   # name -> id
    org_id_cache = {}      # org_id -> id
    norm_cache = {}        # normalised full name -> Hospital
    core_cache = {}        # normalised core name -> Hospital (lowest id wins)
    token_candidates = []  # (frozenset(tokens), Hospital) sorted by id
    indicators_cache = {}
    for ind in session.query(Indicator).all():
        indicators_cache[ind.code] = ind.id

    new_indicator_names = new_indicator_names or {}
    renamed_indicator_names = renamed_indicator_names or {}
    created_indicators: List[Dict] = []
    max_sort = session.query(func.max(Indicator.sort_order)).scalar() or 0

    def _apply_indicator_renames() -> List[Dict]:
        """Update existing indicator names to the wording used in the upload.

        The uploaded file is authoritative for indicator labels: the header
        "SRH IPD (10.h) Cardiac Disorders Requiring CCU or ICU admission" means
        10.h is *named* that, not merely that it resolves to a known code.
        Without this, uploading a renamed sheet silently kept the old label.
        """
        applied = []
        if not renamed_indicator_names:
            return applied
        for code, name in renamed_indicator_names.items():
            if not name or not str(name).strip():
                continue
            ind = session.query(Indicator).filter(Indicator.code == code).first()
            if ind is None:
                continue
            new_name = str(name).strip()
            if not new_name or new_name.lower() == str(ind.name or "").strip().lower():
                continue
            previous = ind.name
            ind.name = new_name
            applied.append({"code": code, "previous_name": previous, "name": new_name})
            logger.info("Renamed indicator %s: %r -> %r", code, previous, new_name)
        return applied

    def _ensure_indicator(code: str, name: Optional[str] = None) -> int:
        """Create the indicator (and any missing ancestors); return its id.

        Ancestors are auto-created so the tree nests the new indicator instead
        of orphaning it at the root.
        """
        if code in indicators_cache:
            return indicators_cache[code]
        parent_id, level = None, 0
        if "." in code:
            parent_code = code.rsplit(".", 1)[0]
            parent_id = _ensure_indicator(parent_code, parent_code)
            level = (session.query(Indicator.level).filter(Indicator.id == parent_id).scalar() or 0) + 1
        nonlocal max_sort
        max_sort += 1
        ind = Indicator(
            code=code,
            name=name or code,
            parent_id=parent_id,
            level=level,
            group_name="SRMNH Inpatient Indicators",
            sort_order=max_sort,
        )
        session.add(ind)
        session.flush()
        indicators_cache[code] = ind.id
        created_indicators.append({"code": code, "name": ind.name})
        return ind.id
    def _index_hospital(hosp):
        norm_cache.setdefault(_norm_hospital_text(hosp.name), hosp)
        core = _hospital_core_name(hosp.name)
        # Lowest id wins so repeated uploads resolve to the same hospital.
        core_cache.setdefault(core, hosp)
        token_candidates.append((frozenset(core.split()), hosp))

    for hosp in session.query(Hospital).order_by(Hospital.id).all():
        hospitals_cache[hosp.name] = hosp.id
        if hosp.organisation_unit_id:
            org_id_cache[str(hosp.organisation_unit_id).strip()] = hosp.id
        _index_hospital(hosp)

    def _find_hospital(name, org_id=None):
        """Find hospital by org ID, exact/normalised name, then token match.

        The file may carry the full DHIS path where the registry stores the
        short name (or vice versa); matching on the normalised *core* name
        resolves that without creating a duplicate. The old substring
        fallback missed "وزارة الصحة/مستشفيات/عبدالعزيز الرنتيسي" vs
        "مستشفى عبدالعزيز الرنتيسي" ("مستشفيات" is not "مستشفى") and
        duplicated the hospital on every upload.
        """
        # 1. Try org ID match
        if org_id:
            oid = str(org_id).strip()
            if oid in org_id_cache:
                return org_id_cache[oid]
        # 2. Try exact name match
        if name in hospitals_cache:
            return hospitals_cache[name]
        # 3. Normalised full name, then normalised core name
        h = norm_cache.get(_norm_hospital_text(name))
        if h is None:
            h = core_cache.get(_hospital_core_name(name))
        # 4. Token containment on core names: the same facility when the
        #    shorter core's tokens are all contained in the longer one (extra
        #    tokens are path/org words or a locality qualifier such as
        #    "خانيونس"). Smallest token delta wins; ties break on lowest id.
        if h is None:
            tokens = set(_hospital_core_name(name).split())
            best = None
            for cand_tokens, cand in token_candidates:
                shorter, longer = ((cand_tokens, tokens) if len(cand_tokens) <= len(tokens)
                                   else (tokens, cand_tokens))
                if len(shorter) < 2 or not shorter.issubset(longer):
                    continue
                delta = len(cand_tokens ^ tokens)
                if best is None or delta < best[0]:
                    best = (delta, cand)
            h = best[1] if best else None
        if h is None:
            return None
        hospitals_cache[name] = h.id  # cache for next time
        return h.id

    new_hospitals = 0
    processed = 0
    hospitals_with_values = set()  # hospitals that received at least one real value
    for rec in records:
        hosp_name = rec["hospital_name"]
        org_id = rec.get("organisation_unit_id", "")
        hosp_id = _find_hospital(hosp_name, org_id)
        if hosp_id is None:
            hosp = Hospital(name=hosp_name, organisation_unit_id=str(org_id).strip() if org_id else None)
            session.add(hosp)
            session.flush()
            hospitals_cache[hosp_name] = hosp.id
            if org_id:
                org_id_cache[str(org_id).strip()] = hosp.id
            _index_hospital(hosp)
            new_hospitals += 1
        indicator_code = rec["indicator_code"]
        if indicator_code not in indicators_cache:
            # Auto-register indicators that only exist in this uploaded file.
            _ensure_indicator(indicator_code, new_indicator_names.get(indicator_code))
        ind_id = indicators_cache[indicator_code]
        hosp_id = hospitals_cache[hosp_name]
        if rec["value"] is not None:
            hospitals_with_values.add(hosp_id)
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
    # A hospital that reports at least one real value is active again: the
    # startup pass deactivates hospitals whose data is all empty cells, and
    # an import carrying real values must undo that flag or the freshly
    # imported data stays invisible to the analysis screens.
    if hospitals_with_values:
        (session.query(Hospital)
         .filter(Hospital.id.in_(hospitals_with_values),
                 Hospital.is_active.isnot(True))
         .update({Hospital.is_active: True}, synchronize_session=False))
    renamed = _apply_indicator_renames()
    session.commit()
    return new_hospitals, processed, created_indicators, renamed


def process_excel_upload(file_path: str, session: Session) -> Dict:
    filename = os.path.basename(file_path)
    known_code_to_name = {ind.code: ind.name for ind in session.query(Indicator).all()}
    df = parse_excel(file_path, known_code_to_name=known_code_to_name)
    records = normalize_data(df, known_code_to_name=known_code_to_name)
    if not records:
        raise ValueError(
            f"No data records found in '{filename}'. "
            "Please check that the file has hospital names in an 'organisationunitname' column "
            "(or 'hospital'/'facility'), indicator columns matching SRMNH names, "
            "and a 'month' column or a title row with the reporting period."
        )
    # ── Guard: reject test/preview uploads before ANY hospital/indicator/value
    # is created (the ghost-doctrine equivalent for the organisation registry).
    test_reasons = _looks_like_test_upload(
        filename, {r["hospital_name"] for r in records}
    )
    if test_reasons:
        logger.warning("Rejected probable test upload '%s': %s", filename, "; ".join(test_reasons))
        raise ValueError(
            f"Upload rejected: '{filename}' looks like a test/preview file "
            f"({'; '.join(sorted(set(test_reasons)))}). "
            "Test uploads must not create real hospitals. Rename the file and use "
            "real facility names from the SRMNH registry, then try again."
        )
    new_indicator_names = df.attrs.get("new_indicators") or {}
    renamed_indicator_names = df.attrs.get("renamed_indicators") or {}
    new_hospitals, new_values, new_indicators, renamed_indicators = import_data_to_db(
        records,
        session,
        source_file=filename,
        new_indicator_names=new_indicator_names,
        renamed_indicator_names=renamed_indicator_names,
    )

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
        "new_indicators": new_indicators,
        "renamed_indicators": renamed_indicators,
        "message": f"Processed {new_values} indicator values for {len(hospital_names)} hospitals",
        "hospitals": hospitals_list,
        "months": months,
    }