# Layered Outlier Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-shot peer z-score outlier detection with a sequential multi-layer pipeline (raw value → rate → hospital history → volume/denominator → peer → classification) that persists explainable results in a new `layered_outlier_results` table, surfaces them through new API endpoints, a `kind=layered_outlier` explain payload, a Classification column on the Outliers tab, and a new Layered Analysis tab — without changing `anomaly_results`, the Quality Score, or the numbers produced by the 4 existing hardcoded rate-definition sites.

**Architecture:** Pure-function engine (`app/engine/anomaly/layered.py` + `classify.py`) driven by a central rate registry (`app/engine/rate_config.py`) that currently holds verbatim copies of all 4 hardcoded rate sites (keyed per site so disagreements stay visible). The pipeline persists results inside `_compute_full_analysis`; FastAPI endpoints and the explain dispatcher read them back; vanilla-ES-module frontend renders them.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy ORM, Alembic, pytest, numpy/scipy (existing), vanilla JS ES modules. Lint: `ruff check` (line-length 120, per `pyproject.toml`).

**Spec:** `docs/superpowers/specs/2026-10-08-layered-outlier-analysis-design.md` — the plan argues from the spec; executors must read it (all sections, including the three 2026-10-08 amendments and the rule-2 magnitude guard).

## Global Constraints

- `anomaly_results`, `quality_scores`, `hospital_indicator_config` behavior stays exactly as-is; the Data Quality Score and its `outlier_penalty` are untouched (spec §2 Q3, §12).
- The 4 migrated rate sites must produce **identical numbers** before/after migration — every spec in `BUILTIN_RATE_SPECS` copies its source values verbatim, including the known disagreements (MMR denominator `2` in zscore/clinical vs `6` in rules; stillbirth denominator `2` in zscore/clinical/rules vs `6` in forecast; multipliers ×1/×100/×1000). Do NOT reconcile them (spec §4 amendment).
- New `Indicator` columns and all new-table columns must be **nullable or server-defaulted** so `app/main.py::_ensure_required_columns` (which skips `not col.nullable` columns at line 343) can self-heal drifted DBs (spec §3.4).
- Alembic current head is `a9c8e7d6f5b4`; the new revision id is `b1c2d3e4f5a6`, written in the idempotent style of `alembic/versions/a9c8e7d6f5b4_add_indicator_groups.py` (table-exists / column-exists guards, `server_default` backfill + SQLite `UPDATE`).
- No new threshold knobs beyond `zscore_threshold` and the config fields in spec §3.2/§3.3. `minimum_denominator` seeds as `NULL` (guard dormant) (spec §12).
- Runners (Windows PowerShell; repo venv — the system `python` lacks the project deps): tests `.venv\Scripts\python.exe -m pytest ...`; lint `.venv\Scripts\ruff.exe check <paths>`. Test DB is file-backed SQLite per `tests/conftest.py::db_session` (schema via `Base.metadata.create_all` + `seed_indicators` + `seed_rules` + `seed_menu`).
- The working tree has many pre-existing unrelated modified files — **commit only the files each task touches** (`git add <explicit paths>`; never `git add -A`).
- Interpretation text is generated server-side in English; UI chrome uses `data-i18n` keys with en/ar entries in `static/js/i18n.js`.
- Commit messages: `feat(...)` / `test(...)` / `refactor(...)` conventional style, one line.

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `app/engine/rate_config.py` | `RateSpec` dataclass, `BUILTIN_RATE_SPECS` (verbatim registry of all 4 sites), `compute_rate`, `iter_site`, `load_rate_specs`/`get_spec` (DB-over-builtin), cache invalidation |
| `app/engine/anomaly/layered.py` | Pure scoring core, layer functions, `AnalysisSpec`, `build_analysis_specs`, `analyze_layered_entry`, `run_layered_analysis` |
| `app/engine/anomaly/classify.py` | Deterministic rule table (10 rules), `build_interpretation`, level caps, routes |
| `alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py` | `layered_outlier_results` + `rate_config` tables, `indicators` config columns |
| `tests/test_rate_config.py` | Registry literals, `compute_rate`, parity per site, DB seed parity |
| `tests/test_layered_engine.py` | Scoring, layers, end-to-end scenarios 1–13, 16 of spec §11 |
| `tests/test_layered_schema.py` | Models, migration guards, self-heal, seed idempotency |
| `tests/test_layered_pipeline.py` | Persistence, purge/reanalyze lifecycle, cache key |
| `tests/test_layered_api.py` | `/analysis/layered`, `/summary`, outliers join, explain contract (scenarios 14–15) |
| `tests/test_layered_ui.py` | Static tests: classification column, tab registration, i18n |
| `static/tabs/layered.html` | Layered Analysis tab markup |
| `static/js/layered.js` | Layered Analysis tab logic (mirrors `outliers.js` idiom) |

**Modified files**

| File | Change |
|---|---|
| `app/engine/anomaly/zscore.py` | `RATE_DEFINITIONS` + `compute_rate` become registry views (Task 2) |
| `app/engine/clinical/thresholds.py` | `CLINICAL_THRESHOLDS` built from registry clinical slice; `compute_rate` multiplier from registry (Task 3) |
| `app/engine/smart/indicator_forecast.py` | `INDICATOR_DEFS` built from registry forecast slice (Task 4) |
| `app/engine/quality/rules.py` | R043–R050 iterate registry rules slice (Task 5) |
| `app/models.py` | `Indicator` 5 config columns; `RateConfig`; `LayeredOutlierResult` (Task 6) |
| `scripts/seed_indicators.py` | `seed_rate_config()` idempotent seeding (Task 6) |
| `app/main.py` | startup `seed_rate_config` backfill after the menu backfill (Task 6); `_ensure_required_columns` self-heals the new nullable columns automatically (no code change) |
| `tests/conftest.py` | autouse rate-spec cache reset fixture (Task 6) |
| `app/engine/pipeline.py` | `_save_layered_results`, call site, purge tuple, empty-values delete (Task 13) |
| `app/api/analysis.py` | `GET /analysis/layered`, `GET /analysis/layered/summary`, outliers join, cache key `v3`→`v4` (Task 14) |
| `app/engine/audit/explain.py` | `explain_layered_outlier` + dispatcher branch (Task 15) |
| `app/api/audit.py` | kind description string (Task 15) |
| `static/tabs/outliers.html`, `static/js/outliers.js` | Classification column + badge (Task 16) |
| `app/menu_registry.py`, `static/index.html`, `static/js/main.js`, `static/js/app.js`, `static/js/auth.js`, `static/js/renderSidebar.js`, `static/js/i18n.js` | Layered tab registration (Task 17) |

---

### Task 1: Rate registry core

**Files:**
- Create: `app/engine/rate_config.py`
- Test: `tests/test_rate_config.py`

**Interfaces:**
- Consumes: nothing (leaf module; must not import `app.models` or any engine module — prevents cycles).
- Produces (every later task depends on these exact names):
  - `RateSpec` frozen dataclass with fields `spec_key, site, rate_code, rate_name, indicator_code, indicator_type, numerator_codes: Tuple[str, ...], denominator_codes: Tuple[str, ...], rate_multiplier: float, unit: str, typical_pct: Optional[float], minimum_denominator: Optional[float], minimum_history_period: int, outlier_method: str, historical_enabled: bool, peer_comparison_enabled: bool, is_active: bool`; property `is_rate -> bool`.
  - `BUILTIN_RATE_SPECS: Dict[str, RateSpec]` keyed by `spec_key`.
  - `iter_site(site: str) -> List[RateSpec]` — insertion order for `"zscore" | "clinical" | "forecast" | "rules"`.
  - `zscore_specs() -> List[RateSpec]`; `zscore_spec_for(numerator_code, denominator_code) -> Optional[RateSpec]`.
  - `compute_rate(values: Dict[str, float], numerator_codes, denominator_codes, rate_multiplier) -> Optional[float]`.
  - `compute_spec_rate(spec: RateSpec, values: Dict[str, float]) -> Optional[float]`.
  - `multiplier_for_unit(unit: str) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rate_config.py`:

```python
"""Central rate registry: verbatim literals, compute_rate, per-site parity."""
from app.engine.rate_config import (
    BUILTIN_RATE_SPECS,
    RateSpec,
    compute_rate,
    compute_spec_rate,
    iter_site,
    multiplier_for_unit,
    zscore_spec_for,
    zscore_specs,
)

# Exact current values of the four hardcoded sites (copied from source before
# migration). Any drift in the registry breaks one of these assertions.
# (name, numerator, denominator, typical_pct, rate_code, unit) — zscore slice.
# unit for the mortality trio is the plan's "per 100" (the Task 6 inherited-base
# assertion pins it), NOT the clinical slice's "per 100,000"/"per 1,000": the
# zscore site has no unit field at all, so this is registry metadata, not a
# verbatim source copy.
ZSCORE_LITERALS = [
    ("C-section rate", "5", "2", 50.0, "rate_cs", "%"),
    ("Maternal mortality ratio", "11", "2", 1.0, "rate_mmr", "per 100"),
    ("Neonatal mortality rate", "17", "6", 30.0, "rate_nmr", "per 100"),
    ("Preterm birth rate", "6.f", "6", 15.0, "rate_preterm", "%"),
    ("SMM rate", "10", "2", 10.0, "rate_smm", "%"),
    ("Stillbirth rate", "7", "2", 5.0, "rate_stillbirth", "per 100"),
    ("NICU admission rate", "16", "6", 20.0, "rate_nicu", "%"),
]

# (rate_code, numerator_codes, denominator_code, multiplier, unit) — clinical
# slice values exactly as in thresholds.py CLINICAL_THRESHOLDS (line 20-216),
# multiplier derived by the current rule `100 if "%" in unit else 1`.
CLINICAL_LITERALS = [
    ("rate_cs", ("5",), "2", 100.0, "%"),
    ("rate_mmr", ("11",), "2", 1.0, "per 100,000"),
    ("rate_nmr", ("17",), "6", 1.0, "per 1,000"),
    ("rate_preterm", ("6.f",), "6", 100.0, "%"),
    ("rate_smm", ("10",), "2", 100.0, "%"),
    ("rate_stillbirth", ("7",), "2", 1.0, "per 1,000"),
    ("rate_nicu", ("16",), "6", 100.0, "%"),
    ("rate_lbw", ("6.g",), "6", 100.0, "%"),
    ("rate_bf", ("13",), "6", 100.0, "%"),
    ("rate_avd", ("4",), "2", 100.0, "%"),
    ("rate_smm_hemorrhage_proportion", ("10.a",), "10", 100.0, "%"),
    ("rate_smm_hypertensive_proportion", ("10.e",), "10", 100.0, "%"),
    ("rate_adolescent", ("2.c", "2.d"), "2", 100.0, "%"),
    ("rate_high_risk", ("2.n",), "2", 100.0, "%"),
    ("rate_hysterectomy", ("10.d",), "2", 1.0, "per 1,000"),
]

# forecast INDICATOR_DEFS: (key, numerator, denominator-or-None, per/unit)
FORECAST_LITERALS = [
    ("cs_rate", ("5",), ("2",), 100.0),
    ("stillbirth_rate", ("7",), ("6",), 1000.0),
    ("preterm_rate", ("6.f",), ("6",), 100.0),
    ("lbw_rate", ("6.g",), ("6",), 100.0),
    ("high_risk_rate", ("2.n",), ("6",), 100.0),
    ("adolescent_rate", ("2.c", "2.d"), ("6",), 100.0),
    ("total_births", ("6",), None, 1.0),
]

# rules R043-R050: (rule code, numerator, denominator) — R045 MMR uses
# denominator "6" here (disagrees with zscore/clinical "2"); that disagreement
# is the point of the per-site registry.
RULES_LITERALS = [
    ("R043", "6.f", "6"),
    ("R044", "6.g", "6"),
    ("R045", "11", "6"),
    ("R046", "17", "6"),
    ("R047", "7", "2"),
    ("R048", "16", "6"),
    ("R049", "10", "2"),
    ("R050", "10.a", "2"),
]


def test_zscore_slice_matches_rate_definitions_literals():
    specs = zscore_specs()
    assert len(specs) == 7
    for spec, (name, num, den, pct, code, unit) in zip(specs, ZSCORE_LITERALS, strict=False):
        assert spec.rate_name == name
        assert spec.numerator_codes == (num,)
        assert spec.denominator_codes == (den,)
        assert spec.typical_pct == pct
        assert spec.rate_code == code
        assert spec.unit == unit
        assert spec.rate_multiplier == 100.0  # zscore.compute_rate hardcodes x100
        assert spec.site == "zscore"


def test_clinical_slice_matches_threshold_literals():
    specs = iter_site("clinical")
    assert len(specs) == 15
    for spec, (code, num, den, mult, unit) in zip(specs, CLINICAL_LITERALS, strict=False):
        assert spec.rate_code == code
        assert spec.numerator_codes == num
        assert spec.denominator_codes == (den,)
        assert spec.rate_multiplier == mult
        assert spec.unit == unit


def test_forecast_slice_matches_indicator_defs_literals():
    specs = iter_site("forecast")
    assert len(specs) == 7
    for spec, (key, num, den, per) in zip(specs, FORECAST_LITERALS, strict=False):
        assert spec.rate_code == key
        assert spec.numerator_codes == num
        assert spec.denominator_codes == (() if den is None else den)
        assert spec.rate_multiplier == per
    assert iter_site("forecast")[-1].is_rate is False  # total_births = count


def test_rules_slice_matches_cross_hospital_rule_literals():
    specs = iter_site("rules")
    assert len(specs) == 8
    for spec, (code, num, den) in zip(specs, RULES_LITERALS, strict=False):
        assert spec.spec_key == f"rules:{code}"
        assert spec.numerator_codes == (num,)
        assert spec.denominator_codes == (den,)
        assert spec.rate_multiplier == 100.0  # rules._rate hardcodes x100


def test_registry_keys_are_site_scoped():
    keys = list(BUILTIN_RATE_SPECS)
    assert len(keys) == len(set(keys))
    # The known disagreements must coexist under separate keys.
    assert BUILTIN_RATE_SPECS["zscore:Maternal mortality ratio"].denominator_codes == ("2",)
    assert BUILTIN_RATE_SPECS["rules:R045"].denominator_codes == ("6",)
    assert BUILTIN_RATE_SPECS["zscore:Stillbirth rate"].denominator_codes == ("2",)
    assert BUILTIN_RATE_SPECS["forecast:stillbirth_rate"].denominator_codes == ("6",)


def test_compute_rate_sums_codes_and_applies_multiplier():
    values = {"5": 80.0, "2": 300.0}
    assert compute_rate(values, ("5",), ("2",), 100.0) == 80.0 / 300.0 * 100


def test_compute_rate_multi_code_numerator():
    values = {"2.c": 40.0, "2.d": 20.0, "2": 300.0}
    assert compute_rate(values, ("2.c", "2.d"), ("2",), 100.0) == 20.0


def test_compute_rate_missing_or_zero_denominator_is_none():
    assert compute_rate({"5": 1}, ("5",), ("2",), 100.0) is None
    assert compute_rate({"5": 1, "2": 0}, ("5",), ("2",), 100.0) is None
    assert compute_rate({"2": 100}, ("5",), ("2",), 100.0) is None


def test_compute_spec_rate_uses_spec_multiplier():
    spec = BUILTIN_RATE_SPECS["zscore:C-section rate"]
    assert compute_spec_rate(spec, {"5": 30, "2": 300}) == 10.0
    spec_mmr = BUILTIN_RATE_SPECS["clinical:rate_mmr"]  # x1, per 100,000
    assert compute_spec_rate(spec_mmr, {"11": 2, "2": 300}) == 2 / 300 * 1


def test_zscore_spec_for_lookup_and_miss():
    spec = zscore_spec_for("5", "2")
    assert spec is not None and spec.rate_code == "rate_cs"
    assert zscore_spec_for("999", "2") is None


def test_multiplier_for_unit():
    assert multiplier_for_unit("%") == 100.0
    assert multiplier_for_unit("per 1,000") == 1.0
    assert multiplier_for_unit("per 100,000") == 1.0
    assert multiplier_for_unit("") == 1.0
    assert multiplier_for_unit(None) == 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.rate_config'`

- [ ] **Step 3: Write the implementation**

Create `app/engine/rate_config.py`:

```python
"""Central rate-definition registry.

The four hardcoded rate sites (anomaly/zscore, clinical/thresholds,
smart/indicator_forecast, quality/rules) disagree today — MMR denominator 2
vs 6, stillbirth denominator 2 vs 6, multipliers x1 / x100 / x1000. This
registry therefore guarantees one MECHANISM and LOCATION, not one value:
every spec is stored VERBATIM under a site-scoped key so the disagreements
sit side by side and can be reconciled later without silent behavior change
(design spec 2026-10-08, section 4 amendment).

Leaf module: imports nothing from app.models or the engine (avoids cycles).
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SITE_ZSCORE = "zscore"
SITE_CLINICAL = "clinical"
SITE_FORECAST = "forecast"
SITE_RULES = "rules"


@dataclass(frozen=True)
class RateSpec:
    spec_key: str                  # "zscore:C-section rate" | "clinical:rate_cs" | ...
    site: str                      # one of the SITE_* constants above
    rate_code: str                 # synthetic analysis code ("rate_cs", "cs_rate", "rules_r043")
    rate_name: str                 # display name (verbatim from its source site)
    indicator_code: str            # primary (first numerator) code, "" when not applicable
    indicator_type: str            # rate | ratio | percentage | count
    numerator_codes: Tuple[str, ...]
    denominator_codes: Tuple[str, ...]   # empty tuple = count-type
    rate_multiplier: float
    unit: str                      # "%" | "per 100" | "per 1,000" | "per 100,000" | "count" | ""
    typical_pct: Optional[float] = None          # zscore slice only (legacy benchmark)
    minimum_denominator: Optional[float] = None  # NULL = guard dormant (spec 12)
    minimum_history_period: int = 3
    outlier_method: str = "auto"
    historical_enabled: bool = True
    peer_comparison_enabled: bool = True
    is_active: bool = True

    @property
    def is_rate(self) -> bool:
        return bool(self.denominator_codes)


def _spec(site: str, spec_id: str, rate_code: str, rate_name: str,
          indicator_type: str, num: Sequence[str], den: Sequence[str],
          multiplier: float, unit: str, indicator_code: str = "",
          typical_pct: Optional[float] = None, **overrides) -> RateSpec:
    return RateSpec(
        spec_key=f"{site}:{spec_id}",
        site=site,
        rate_code=rate_code,
        rate_name=rate_name,
        indicator_code=indicator_code or (num[0] if num else ""),
        indicator_type=indicator_type,
        numerator_codes=tuple(num),
        denominator_codes=tuple(den),
        rate_multiplier=float(multiplier),
        unit=unit,
        typical_pct=typical_pct,
        **overrides,
    )


def _build_builtin() -> Dict[str, RateSpec]:
    specs: List[RateSpec] = []

    # ── zscore slice — app/engine/anomaly/zscore.py:37 RATE_DEFINITIONS ──
    # compute_rate there hardcodes x100 for every rate; typical_pct verbatim.
    zs = [
        ("rate_cs", "C-section rate", "5", "2", 50.0, "%"),
        ("rate_mmr", "Maternal mortality ratio", "11", "2", 1.0, "per 100"),
        ("rate_nmr", "Neonatal mortality rate", "17", "6", 30.0, "per 100"),
        ("rate_preterm", "Preterm birth rate", "6.f", "6", 15.0, "%"),
        ("rate_smm", "SMM rate", "10", "2", 10.0, "%"),
        ("rate_stillbirth", "Stillbirth rate", "7", "2", 5.0, "per 100"),
        ("rate_nicu", "NICU admission rate", "16", "6", 20.0, "%"),
    ]
    for code, name, num, den, pct, unit in zs:
        itype = "percentage" if unit == "%" else "rate"
        specs.append(_spec(SITE_ZSCORE, name, code, name, itype,
                           (num,), (den,), 100.0, unit, typical_pct=pct))

    # ── clinical slice — thresholds.py CLINICAL_THRESHOLDS (lines 20-216) ──
    # multiplier = the current `100 if "%" in unit else 1` rule, made explicit.
    cl = [
        ("rate_cs", "C-Section Rate", ("5",), "2", "%", 100.0),
        ("rate_mmr", "Maternal Mortality Ratio", ("11",), "2", "per 100,000", 1.0),
        ("rate_nmr", "Neonatal Mortality Rate", ("17",), "6", "per 1,000", 1.0),
        ("rate_preterm", "Preterm Birth Rate", ("6.f",), "6", "%", 100.0),
        ("rate_smm", "Severe Maternal Morbidity Rate", ("10",), "2", "%", 100.0),
        ("rate_stillbirth", "Stillbirth Rate", ("7",), "2", "per 1,000", 1.0),
        ("rate_nicu", "NICU Admission Rate", ("16",), "6", "%", 100.0),
        ("rate_lbw", "Low Birth Weight Rate", ("6.g",), "6", "%", 100.0),
        ("rate_bf", "Breastfeeding within 1 Hour", ("13",), "6", "%", 100.0),
        ("rate_avd", "Assisted Vaginal Delivery Rate", ("4",), "2", "%", 100.0),
        ("rate_smm_hemorrhage_proportion", "Hemorrhage Proportion of SMM", ("10.a",), "10", "%", 100.0),
        ("rate_smm_hypertensive_proportion", "Hypertensive Proportion of SMM", ("10.e",), "10", "%", 100.0),
        ("rate_adolescent", "Adolescent Pregnancy Rate (10-19)", ("2.c", "2.d"), "2", "%", 100.0),
        ("rate_high_risk", "High-Risk Delivery Rate", ("2.n",), "2", "%", 100.0),
        ("rate_hysterectomy", "Hysterectomy per 1,000 Deliveries", ("10.d",), "2", "per 1,000", 1.0),
    ]
    for code, name, num, den, unit, mult in cl:
        itype = "percentage" if unit == "%" else "rate"
        specs.append(_spec(SITE_CLINICAL, code, code, name, itype,
                           num, (den,), mult, unit))

    # ── forecast slice — indicator_forecast.py INDICATOR_DEFS (lines 48-105) ──
    # denominator None maps to a count-type spec (empty denominator_codes).
    fc = [
        ("cs_rate", "C-section rate", "معدل العمليات القيصارية", ("5",), ("2",), 100.0, "%"),
        ("stillbirth_rate", "Stillbirth rate", "معدل الولادات الميتة", ("7",), ("6",), 1000.0, "per 1000"),
        ("preterm_rate", "Preterm birth rate", "معدل الولادات المبكرة", ("6.f",), ("6",), 100.0, "%"),
        ("lbw_rate", "Low birth weight rate", "معدل نقص وزن الولادة", ("6.g",), ("6",), 100.0, "%"),
        ("high_risk_rate", "High-risk share", "نسبة حالات الخطر العالي", ("2.n",), ("6",), 100.0, "%"),
        ("adolescent_rate", "Adolescent share", "نسبة حالات المراهقات", ("2.c", "2.d"), ("6",), 100.0, "%"),
        ("total_births", "Total live births", "إجمالي المواليد الأحياء", ("6",), (), 1.0, "count"),
    ]
    for key, en, _ar, num, den, per, unit in fc:
        itype = "count" if not den else ("percentage" if unit == "%" else "rate")
        specs.append(_spec(SITE_FORECAST, key, key, en, itype,
                           num, den, per, unit))

    # ── rules slice — quality/rules.py R043-R050 (lines 515-522) ──
    # _rate/_cross_hospital_rate hardcode x100. R045 MMR uses denominator "6"
    # here — the documented disagreement with zscore/clinical "2".
    rl = [
        ("R043", "Preterm Birth Rate outlier across hospitals", "6.f", "6"),
        ("R044", "Low Birth Weight Rate outlier across hospitals", "6.g", "6"),
        ("R045", "Maternal Mortality Ratio outlier across hospitals", "11", "6"),
        ("R046", "Neonatal Mortality Rate outlier across hospitals", "17", "6"),
        ("R047", "Stillbirth Rate outlier across hospitals", "7", "2"),
        ("R048", "NICU Admission Rate outlier across hospitals", "16", "6"),
        ("R049", "SMM Rate outlier across hospitals", "10", "2"),
        ("R050", "Hemorrhage Rate outlier across hospitals", "10.a", "2"),
    ]
    for code, desc, num, den in rl:
        specs.append(_spec(SITE_RULES, code, f"rules_{code.lower()}", desc,
                           "percentage", (num,), (den,), 100.0, "%"))

    return {s.spec_key: s for s in specs}


BUILTIN_RATE_SPECS: Dict[str, RateSpec] = _build_builtin()


def iter_site(site: str) -> List[RateSpec]:
    """All specs of one site, in registry (source-file) order."""
    return [s for s in BUILTIN_RATE_SPECS.values() if s.site == site]


def zscore_specs() -> List[RateSpec]:
    return iter_site(SITE_ZSCORE)


def zscore_spec_for(numerator_code: str, denominator_code: str) -> Optional[RateSpec]:
    for s in zscore_specs():
        if s.numerator_codes == (numerator_code,) and s.denominator_codes == (denominator_code,):
            return s
    return None


def multiplier_for_unit(unit: Optional[str]) -> float:
    """100 for percent units, 1 otherwise — derived from the clinical slice
    (registry values), replacing the hardcoded `100 if "%" in unit` test."""
    if not unit:
        return 1.0
    for s in iter_site(SITE_CLINICAL):
        if s.unit == unit:
            return s.rate_multiplier
    return 100.0 if "%" in unit else 1.0


def compute_rate(values: Dict[str, float],
                 numerator_codes: Sequence[str],
                 denominator_codes: Sequence[str],
                 rate_multiplier: float) -> Optional[float]:
    """The one rate computation: sum(num)/sum(den)*multiplier.

    None when any numerator or denominator code is missing, or the summed
    denominator is zero — missing data is never a silent 0.
    """
    num = 0.0
    for code in numerator_codes:
        v = values.get(code)
        if v is None:
            return None
        num += float(v)
    den = 0.0
    for code in denominator_codes:
        v = values.get(code)
        if v is None:
            return None
        den += float(v)
    if den == 0:
        return None
    return (num / den) * float(rate_multiplier)


def compute_spec_rate(spec: RateSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    return compute_rate(values, spec.numerator_codes, spec.denominator_codes,
                        spec.rate_multiplier)
```

Note: the Arabic `label_ar` strings from `INDICATOR_DEFS` are **display metadata, not rate definitions** — they stay in `indicator_forecast.py` (Task 4) keyed by `rate_code`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py -v`
Expected: all PASS

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/rate_config.py tests/test_rate_config.py`
Expected: no errors.

```bash
git add app/engine/rate_config.py tests/test_rate_config.py
git commit -m "feat(rate-config): central verbatim rate registry for all 4 hardcoded sites"
```

---

### Task 2: Migrate `zscore.py` (site 1 of 4) to the registry

**Files:**
- Modify: `app/engine/anomaly/zscore.py:29-45` (`compute_rate`, `RATE_DEFINITIONS`)
- Test: `tests/test_rate_config.py` (append)

**Interfaces:**
- Consumes: Task 1 `zscore_specs()`, `zscore_spec_for()`, `compute_rate()` from `app.engine.rate_config`.
- Produces: unchanged public API — `zscore.compute_rate(values, numerator_code, denominator_code)` and `RATE_DEFINITIONS` as a list of 4-tuples `(rate_name, numerator_code, denominator_code, typical_pct)`; `app/engine/anomaly/__init__.py` re-exports stay valid; `explain.py:497-501` and `trends.py`/`comparison.py`/`confidence.py` callers keep working untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rate_config.py`:

```python
def test_rate_definitions_is_a_view_over_the_zscore_slice():
    from app.engine.anomaly.zscore import RATE_DEFINITIONS
    expected = [(name, num, den, pct)
                for (name, num, den, pct, _code) in ZSCORE_LITERALS]
    assert RATE_DEFINITIONS == expected


def test_zscore_compute_rate_keeps_signature_and_x100_parity():
    from app.engine.anomaly.zscore import compute_rate
    assert compute_rate({"5": 80, "2": 300}, "5", "2") == 80 / 300 * 100
    assert compute_rate({"11": 3, "2": 300}, "11", "2") == 3 / 300 * 100
    assert compute_rate({"5": 80}, "5", "2") is None
    assert compute_rate({"5": 80, "2": 0}, "5", "2") is None
    # unknown pair keeps the historical x100 default (never regresses to None)
    assert compute_rate({"99": 1, "2": 4}, "99", "2") == 25.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py::test_rate_definitions_is_a_view_over_the_zscore_slice -v`
Expected: FAIL — current `RATE_DEFINITIONS` is the literal list (test should actually pass already for the view test; the parity tests must pass too — this task's real gate is the existing suite + the source change). Confirm the current source is still hardcoded: `app/engine/anomaly/zscore.py` lines 29-45 contain `(num / den) * 100` and a literal list.

- [ ] **Step 3: Rewrite `compute_rate` and `RATE_DEFINITIONS` as registry views**

In `app/engine/anomaly/zscore.py`, add the import and replace lines 29-45 with:

```python
from app.engine.rate_config import (
    compute_rate as _registry_compute_rate,
    zscore_spec_for,
    zscore_specs,
)


def compute_rate(values: Dict[str, float], numerator_code: str, denominator_code: str) -> Optional[float]:
    spec = zscore_spec_for(numerator_code, denominator_code)
    multiplier = spec.rate_multiplier if spec else 100.0
    return _registry_compute_rate(values, (numerator_code,), (denominator_code,), multiplier)


# View over the registry's "zscore:*" slice — tuple shape kept so explain.py
# (line 497-501), trends.py, comparison.py and confidence.py keep working.
RATE_DEFINITIONS = [
    (s.rate_name, s.numerator_codes[0], s.denominator_codes[0], s.typical_pct)
    for s in zscore_specs()
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py tests/test_anomaly.py tests/test_benchmark.py tests/test_confidence.py -v`
Expected: all PASS (identical numbers: multiplier comes from the registry, default still ×100).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/zscore.py tests/test_rate_config.py`

```bash
git add app/engine/anomaly/zscore.py tests/test_rate_config.py
git commit -m "refactor(anomaly): RATE_DEFINITIONS and compute_rate view over central registry"
```

---

### Task 3: Migrate `clinical/thresholds.py` (site 2 of 4) to the registry

**Files:**
- Modify: `app/engine/clinical/thresholds.py` (imports, `CLINICAL_THRESHOLDS` construction, `compute_rate` at :291)
- Test: `tests/test_rate_config.py` (append)

**Interfaces:**
- Consumes: Task 1 `iter_site("clinical")`, `multiplier_for_unit()`.
- Produces: unchanged public API — `ClinicalThreshold` dataclass fields, `CLINICAL_THRESHOLDS` (15 entries, source order), `get_threshold(rate_name)`, `classify_rate`, `compute_rate(numerator_total, denominator, unit="")` with the same `None` semantics.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rate_config.py`:

```python
def test_clinical_thresholds_built_from_registry_slice():
    from app.engine.clinical.thresholds import CLINICAL_THRESHOLDS
    assert len(CLINICAL_THRESHOLDS) == 15
    for th, (code, num, den, mult, unit) in zip(CLINICAL_THRESHOLDS, CLINICAL_LITERALS):
        assert th.indicator_code == code
        assert th.numerator_codes == list(num)
        assert th.denominator_code == den
        assert th.unit == unit


def test_clinical_threshold_ranges_and_guidelines_spot_check():
    from app.engine.clinical.thresholds import get_threshold
    cs = get_threshold("C-Section Rate")
    assert (cs.normal_range, cs.elevated_range, cs.high_range) == ((10, 15), (15, 25), (25, 40))
    assert cs.critical_threshold == 40
    assert cs.clinical_guideline == "WHO: 10-15% optimal C-section rate"
    assert cs.higher_is_worse is True
    bf = get_threshold("Breastfeeding within 1 Hour")
    assert bf.normal_range == (80, 100) and bf.higher_is_worse is False
    mmr = get_threshold("Maternal Mortality Ratio")
    assert mmr.clinical_guideline == "WHO/SDG 3.1: <70 per 100,000 by 2030"
    assert get_threshold("No Such Rate") is None


def test_clinical_compute_rate_multiplier_comes_from_registry():
    from app.engine.clinical.thresholds import compute_rate
    assert compute_rate(80, 300, "%") == 80 / 300 * 100
    assert compute_rate(2, 300, "per 1,000") == 2 / 300
    assert compute_rate(2, 300, "per 100,000") == 2 / 300
    assert compute_rate(5, 0, "%") is None
    assert compute_rate(5, None, "%") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py::test_clinical_thresholds_built_from_registry_slice -v`
Expected: FAIL — `CLINICAL_THRESHOLDS` is still a literal list of 15 `ClinicalThreshold(...)` calls.

- [ ] **Step 3: Move ranges/guidelines to a local meta table, build from the registry**

In `app/engine/clinical/thresholds.py`:

1. Add imports at the top:

```python
from app.engine.rate_config import iter_site, multiplier_for_unit
```

2. Delete the literal `CLINICAL_THRESHOLDS: List[ClinicalThreshold] = [ ... ]` block (lines 20-216) and replace it with the meta table + builder (ranges/guidelines stay in this module, per spec §4.1):

```python
# Clinical ranges/guidelines are display/classification metadata, NOT rate
# definitions — they live here; numerator/denominator/unit come from the
# central registry (rate_config, site "clinical").
_CLINICAL_META = {
    "rate_cs":  dict(normal_range=(10, 15), elevated_range=(15, 25), high_range=(25, 40),
                     critical_threshold=40, clinical_guideline="WHO: 10-15% optimal C-section rate",
                     higher_is_worse=True),
    "rate_mmr": dict(normal_range=(0, 50), elevated_range=(50, 150), high_range=(150, 300),
                     critical_threshold=300, clinical_guideline="WHO/SDG 3.1: <70 per 100,000 by 2030",
                     higher_is_worse=True),
    "rate_nmr": dict(normal_range=(0, 15), elevated_range=(15, 30), high_range=(30, 45),
                     critical_threshold=45, clinical_guideline="WHO/SDG: <12 per 1,000 live births",
                     higher_is_worse=True),
    "rate_preterm": dict(normal_range=(0, 10), elevated_range=(10, 15), high_range=(15, 20),
                         critical_threshold=20, clinical_guideline="WHO: <10% of live births",
                         higher_is_worse=True),
    "rate_smm": dict(normal_range=(0, 2), elevated_range=(2, 5), high_range=(5, 10),
                     critical_threshold=10, clinical_guideline="Published literature: <2% of deliveries",
                     higher_is_worse=True),
    "rate_stillbirth": dict(normal_range=(0, 12), elevated_range=(12, 22), high_range=(22, 35),
                            critical_threshold=35, clinical_guideline="WHO: <12 per 1,000 total births",
                            higher_is_worse=True),
    "rate_nicu": dict(normal_range=(0, 15), elevated_range=(15, 25), high_range=(25, 40),
                      critical_threshold=40, clinical_guideline="Literature: 10-15% of live births typical",
                      higher_is_worse=True),
    "rate_lbw": dict(normal_range=(0, 10), elevated_range=(10, 15), high_range=(15, 20),
                     critical_threshold=20, clinical_guideline="WHO: <10% of live births",
                     higher_is_worse=True),
    "rate_bf": dict(normal_range=(80, 100), elevated_range=(60, 80), high_range=(40, 60),
                    critical_threshold=40, clinical_guideline="WHO: >80% initiation within 1 hour",
                    higher_is_worse=False),
    "rate_avd": dict(normal_range=(5, 15), elevated_range=(15, 20), high_range=(20, 30),
                     critical_threshold=30, clinical_guideline="WHO: 5-15% of deliveries",
                     higher_is_worse=True),
    "rate_smm_hemorrhage_proportion": dict(normal_range=(0, 40), elevated_range=(40, 55), high_range=(55, 70),
                                            critical_threshold=70,
                                            clinical_guideline="Literature: Hemorrhage ~35-40% of SMM cases",
                                            higher_is_worse=True),
    "rate_smm_hypertensive_proportion": dict(normal_range=(0, 25), elevated_range=(25, 40), high_range=(40, 55),
                                              critical_threshold=55,
                                              clinical_guideline="Literature: Hypertensive ~20-25% of SMM cases",
                                              higher_is_worse=True),
    "rate_adolescent": dict(normal_range=(0, 10), elevated_range=(10, 20), high_range=(20, 30),
                            critical_threshold=30,
                            clinical_guideline="WHO: Reducing adolescent pregnancy is SDG target",
                            higher_is_worse=True),
    "rate_high_risk": dict(normal_range=(0, 20), elevated_range=(20, 35), high_range=(35, 50),
                           critical_threshold=50,
                           clinical_guideline="Depends on referral level; tertiary >30% expected",
                           higher_is_worse=True),
    "rate_hysterectomy": dict(normal_range=(0, 0.5), elevated_range=(0.5, 1), high_range=(1, 2),
                              critical_threshold=2,
                              clinical_guideline="Literature: 0.3-0.5 per 1,000 deliveries",
                              higher_is_worse=True),
}


def _build_clinical_thresholds() -> List[ClinicalThreshold]:
    out = []
    for spec in iter_site("clinical"):
        out.append(ClinicalThreshold(
            indicator_code=spec.rate_code,
            rate_name=spec.rate_name,
            numerator_codes=list(spec.numerator_codes),
            denominator_code=spec.denominator_codes[0],
            unit=spec.unit,
            **_CLINICAL_META[spec.rate_code],
        ))
    return out


CLINICAL_THRESHOLDS: List[ClinicalThreshold] = _build_clinical_thresholds()
```

3. Replace `compute_rate` (line 291-294) with:

```python
def compute_rate(numerator_total: float, denominator: float, unit: str = "") -> Optional[float]:
    if denominator is None or denominator == 0:
        return None
    return (numerator_total / denominator) * multiplier_for_unit(unit)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py tests/test_clinical.py -v`
Expected: all PASS (output parity: `multiplier_for_unit` returns 100 for `%`, 1 otherwise — identical to the old `100 if "%" in unit else 1`).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/clinical/thresholds.py tests/test_rate_config.py`

```bash
git add app/engine/clinical/thresholds.py tests/test_rate_config.py
git commit -m "refactor(clinical): thresholds built from central rate registry"
```

---

### Task 4: Migrate `indicator_forecast.py` (site 3 of 4) to the registry

**Files:**
- Modify: `app/engine/smart/indicator_forecast.py:48-105` (`INDICATOR_DEFS`)
- Test: `tests/test_rate_config.py` (append)

**Interfaces:**
- Consumes: Task 1 `iter_site("forecast")`.
- Produces: unchanged `INDICATOR_DEFS: Dict[str, Dict]` with keys in the original order (`cs_rate`, `stillbirth_rate`, `preterm_rate`, `lbw_rate`, `high_risk_rate`, `adolescent_rate`, `total_births`) and values `{label_ar, label_en, unit, numerator (tuple), denominator (tuple|None), per (float)}`; `available_indicators()` and `indicator_rate_from_values()` unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rate_config.py`:

```python
def test_forecast_indicator_defs_built_from_registry_slice():
    from app.engine.smart.indicator_forecast import INDICATOR_DEFS
    assert list(INDICATOR_DEFS.keys()) == [
        "cs_rate", "stillbirth_rate", "preterm_rate", "lbw_rate",
        "high_risk_rate", "adolescent_rate", "total_births",
    ]
    assert INDICATOR_DEFS["cs_rate"] == {
        "label_ar": "معدل العمليات القيصارية", "label_en": "C-section rate",
        "unit": "%", "numerator": ("5",), "denominator": ("2",), "per": 100.0,
    }
    assert INDICATOR_DEFS["stillbirth_rate"]["per"] == 1000.0
    assert INDICATOR_DEFS["stillbirth_rate"]["denominator"] == ("6",)
    assert INDICATOR_DEFS["adolescent_rate"]["numerator"] == ("2.c", "2.d")
    assert INDICATOR_DEFS["total_births"]["denominator"] is None
    assert INDICATOR_DEFS["total_births"]["per"] == 1.0


def test_forecast_rate_computation_parity():
    from app.engine.smart.indicator_forecast import available_indicators, indicator_rate_from_values
    assert [i["key"] for i in available_indicators()] == list(
        ["cs_rate", "stillbirth_rate", "preterm_rate", "lbw_rate",
         "high_risk_rate", "adolescent_rate", "total_births"])
    assert indicator_rate_from_values("cs_rate", {"5": 80, "2": 300}) == 80 / 300 * 100
    assert indicator_rate_from_values("stillbirth_rate", {"7": 6, "6": 300}) == 6 / 300 * 1000
    assert indicator_rate_from_values("total_births", {"6": 300}) == 300.0
    assert indicator_rate_from_values("adolescent_rate", {"2.c": 40, "2.d": 20, "6": 300}) == 60 / 300 * 100
    assert indicator_rate_from_values("cs_rate", {"5": 80}) is None
    assert indicator_rate_from_values("cs_rate", {"5": 80, "2": 0}) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py::test_forecast_indicator_defs_built_from_registry_slice -v`
Expected: FAIL — `INDICATOR_DEFS` is still a hardcoded dict literal.

- [ ] **Step 3: Build `INDICATOR_DEFS` from the registry**

In `app/engine/smart/indicator_forecast.py`, keep the Arabic display labels local (display metadata, not rate definitions) and replace the dict literal (lines 48-105) with:

```python
from app.engine.rate_config import iter_site

# Arabic display labels — keyed by the registry's forecast rate_code.
_FORECAST_LABEL_AR = {
    "cs_rate": "معدل العمليات القيصارية",
    "stillbirth_rate": "معدل الولادات الميتة",
    "preterm_rate": "معدل الولادات المبكرة",
    "lbw_rate": "معدل نقص وزن الولادة",
    "high_risk_rate": "نسبة حالات الخطر العالي",
    "adolescent_rate": "نسبة حالات المراهقات",
    "total_births": "إجمالي المواليد الأحياء",
}

# numerator/denominator/multiplier come from the central registry
# (rate_config, site "forecast"); denominator None => count-type.
INDICATOR_DEFS: Dict[str, Dict] = {
    s.rate_code: {
        "label_ar": _FORECAST_LABEL_AR[s.rate_code],
        "label_en": s.rate_name,
        "unit": s.unit,
        "numerator": s.numerator_codes,
        "denominator": s.denominator_codes or None,
        "per": s.rate_multiplier,
    }
    for s in iter_site("forecast")
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py tests/test_smart_indicator_forecast.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/smart/indicator_forecast.py tests/test_rate_config.py`

```bash
git add app/engine/smart/indicator_forecast.py tests/test_rate_config.py
git commit -m "refactor(forecast): INDICATOR_DEFS built from central rate registry"
```

---

### Task 5: Migrate rules R043–R050 (site 4 of 4) to the registry

**Files:**
- Modify: `app/engine/quality/rules.py:515-522` (inside `_build_rules()`, defined at :468)
- Test: `tests/test_rate_config.py` (append)

**Interfaces:**
- Consumes: Task 1 `iter_site("rules")` (8 specs in R043→R050 order, each with `numerator_codes`, `denominator_codes`).
- Produces: unchanged behavior of `ALL_RULES` — the 8 `_cross_hospital_rate(...)` lambdas keep their rule codes, descriptions, severities and `_RULES_CONFIG["zscore_threshold"]` knob; only the numerator/denominator literals move to the registry. Rule code/description/severity are rule metadata and stay in `rules.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_rate_config.py`:

```python
def _quality_ctx(values, all_hospital_data, month="2026-01"):
    from app.engine.quality import ValidationContext
    return ValidationContext(
        values=values,
        hospital_name="General Hospital",
        month=month,
        all_hospital_data=all_hospital_data,
        historical_data={},
        disabled_codes=set(),
    )


def test_r043_to_r050_exist_and_use_registry_rates():
    """R045 (MMR) must use denominator "6" — the rules-site value that
    disagrees with zscore/clinical "2" — proving the loop reads the registry."""
    from app.engine.quality import run_all_rules
    values = {"11": 6, "6": 300, "2": 100, "7": 3, "10": 4, "10.a": 2,
              "16": 8, "17": 5, "6.f": 20, "6.g": 30}
    peers = {
        "General Hospital": dict(values),
        "Central Medical": dict(values, **{"11": 12, "6": 600}),
        "Community Clinic": dict(values, **{"11": 3, "6": 150}),
    }
    results = run_all_rules(_quality_ctx(values, peers))
    by_code = {r.rule_code: r for r in results}
    for code in ("R043", "R044", "R045", "R046", "R047", "R048", "R049", "R050"):
        assert code in by_code, code
    # R045: 6/300*100 = 2.0 with the rules denominator "6"
    # (the zscore/clinical denominator "2" would give 6.0).
    assert "Rate=2.0%" in by_code["R045"].details, by_code["R045"].details
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py::test_r043_to_r050_exist_and_use_registry_rates -v`
Expected: FAIL (`KeyError`/`assert` — first run proves the test exercises R045; the test passes against the current hardcoded code too. Its purpose is to pin the values BEFORE the edit; run it now to confirm it passes on the old code, i.e. it is a parity guard, then re-run after Step 3.)

- [ ] **Step 3: Replace the hardcoded R043–R050 appends with a registry loop**

In `app/engine/quality/rules.py`:

1. Add the import at the top (safe: `rate_config` is a leaf module):

```python
from app.engine.rate_config import iter_site
```

2. In `_build_rules()`, replace the 8 `ALL_RULES.append(lambda ctx: _cross_hospital_rate(...))` lines (515-522) with:

```python
    # Numerator/denominator pairs live in the central registry (rate_config,
    # site "rules"); code/description/severity are rule metadata and stay here.
    _rule_rate_meta = [
        ("R043", "Preterm Birth Rate outlier across hospitals", Severity.MEDIUM),
        ("R044", "Low Birth Weight Rate outlier across hospitals", Severity.MEDIUM),
        ("R045", "Maternal Mortality Ratio outlier across hospitals", Severity.HIGH),
        ("R046", "Neonatal Mortality Rate outlier across hospitals", Severity.HIGH),
        ("R047", "Stillbirth Rate outlier across hospitals", Severity.MEDIUM),
        ("R048", "NICU Admission Rate outlier across hospitals", Severity.MEDIUM),
        ("R049", "SMM Rate outlier across hospitals", Severity.HIGH),
        ("R050", "Hemorrhage Rate outlier across hospitals", Severity.HIGH),
    ]
    for spec, (code, desc, sev) in zip(iter_site("rules"), _rule_rate_meta):
        ALL_RULES.append(lambda ctx, s=spec, c=code, d=desc, v=sev:
                         _cross_hospital_rate(s.numerator_codes[0], s.denominator_codes[0],
                                              _RULES_CONFIG["zscore_threshold"], c, d, v, ctx))
```

Order is preserved (registry insertion order == R043→R050, pinned by Task 1's `test_rules_slice_matches_cross_hospital_rule_literals`), and the default-argument capture avoids the classic lambda closure bug.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rate_config.py tests/test_rules.py tests/test_quality_score.py tests/test_formula_rules.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/quality/rules.py tests/test_rate_config.py`

```bash
git add app/engine/quality/rules.py tests/test_rate_config.py
git commit -m "refactor(rules): R043-R050 cross-hospital rates from central registry"
```

---

### Task 6: Schema — models, migration, seeding, DB-over-builtin specs

**Files:**
- Modify: `app/models.py` (add `text` to the `sqlalchemy` import at lines 3-16; 5 `Indicator` columns after `requirement_type` at line 104; new `RateConfig` + `LayeredOutlierResult` classes after `AnomalyResult` at line 299)
- Create: `alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py`
- Modify: `scripts/seed_indicators.py` (`seed_rate_config`)
- Modify: `app/main.py` (import at line 60; always-run backfill after the `seed_menu` block at lines 660-669)
- Modify: `tests/conftest.py` (import at line 8, `db_session` seeding at line 186, autouse cache-reset fixture)
- Modify: `app/engine/rate_config.py` (append `load_rate_specs` / `get_spec` / `invalidate_rate_specs_cache`)
- Test: `tests/test_layered_schema.py` (new)

**Interfaces:**
- Consumes: Task 1 `RateSpec`, `zscore_specs()`, `SITE_ZSCORE`.
- Produces (later tasks depend on these exact names):
  - `Indicator.indicator_type / minimum_history_period / outlier_method / historical_enabled / peer_comparison_enabled` — all **nullable** with server defaults `count / 3 / auto / true / true`, so `app/main.py:_ensure_required_columns` (line 343 skips `not col.nullable`) self-heals drifted DBs.
  - ORM `RateConfig` (spec §3.3) and `LayeredOutlierResult` (spec §3.1) — unique `(hospital_id, analysis_code, month)`; indexes `(hospital_id, month)`, `(month, outlier_type)`.
  - `seed_rate_config(session) -> int` — insert-if-missing of the 7 `zscore:*` specs (spec §4.2); returns rows added; invalidates the spec cache.
  - `load_rate_specs(db) -> Dict[str, RateSpec]` keyed by `rate_code` (DB rows merged over the builtin zscore slice; empty table → builtin), `get_spec(db, rate_code)`, `invalidate_rate_specs_cache()`.

**Two verified gotchas baked into the code below:** (1) Boolean server defaults MUST be `sa.text("true")`/`sa.text("false")` — a plain-string `server_default="false"` renders `DEFAULT 'false'`, which SQLite stores as *text* `'false'` and SQLAlchemy's Boolean reader then converts to **True** (verified with a scratch DB). (2) SQLite `ADD COLUMN ... DEFAULT` makes pre-existing rows read the default (`'count'`, `1`), so the self-heal test below asserts real default reads, not NULLs. String/integer server defaults keep the plain-string precedent of `requirement_type`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_layered_schema.py`:

```python
"""Schema layer: models, migration revision, rate_config seeding, DB-over-builtin specs."""
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.engine.rate_config import (
    get_spec,
    invalidate_rate_specs_cache,
    load_rate_specs,
    zscore_specs,
)
from app.main import _ensure_required_columns
from app.models import Indicator, LayeredOutlierResult, RateConfig
from scripts.seed_indicators import seed_rate_config

OLD_SHAPE_INDICATORS = """
CREATE TABLE indicators (
    id INTEGER NOT NULL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(500) NOT NULL,
    parent_id INTEGER,
    level INTEGER,
    sort_order INTEGER,
    group_name VARCHAR(100),
    formula TEXT,
    default_weight FLOAT,
    requirement_type VARCHAR(10) NOT NULL DEFAULT 'Required'
)
"""


def test_indicator_layer_config_columns_exist_with_defaults():
    cols = Indicator.__table__.columns
    for name in ("indicator_type", "minimum_history_period", "outlier_method",
                 "historical_enabled", "peer_comparison_enabled"):
        assert name in cols, name
        # nullable so the startup self-heal path (skips NOT NULL) can add it
        assert cols[name].nullable is True, name
    assert cols["indicator_type"].default.arg == "count"
    assert cols["minimum_history_period"].default.arg == 3
    assert cols["outlier_method"].default.arg == "auto"
    assert cols["historical_enabled"].default.arg is True
    assert cols["peer_comparison_enabled"].default.arg is True


def test_new_indicator_row_gets_layer_config_defaults(db_session):
    ind = Indicator(code="test.layered.cfg", name="Layered Config Test")
    db_session.add(ind)
    db_session.flush()
    assert ind.indicator_type == "count"
    assert ind.minimum_history_period == 3
    assert ind.outlier_method == "auto"
    assert ind.historical_enabled is True
    assert ind.peer_comparison_enabled is True
    db_session.rollback()


def test_ensure_required_columns_heals_old_shape_indicators():
    """Old-shape indicators table stamped at head must gain the 5 new columns;
    the pre-existing row reads the server defaults (never NULL)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(OLD_SHAPE_INDICATORS)
            conn.exec_driver_sql(
                "INSERT INTO indicators (id, code, name, requirement_type) "
                "VALUES (1, '5', 'C-sections', 'Required')"
            )
        with pytest.raises(Exception, match="no such column"):
            with engine.connect() as conn:
                conn.execute(select(Indicator.indicator_type)).all()

        _ensure_required_columns(engine)

        from sqlalchemy import inspect as sa_inspect
        got = {c["name"] for c in sa_inspect(engine).get_columns("indicators")}
        for name in ("indicator_type", "minimum_history_period", "outlier_method",
                     "historical_enabled", "peer_comparison_enabled"):
            assert name in got, name
        with engine.connect() as conn:
            row = conn.execute(select(
                Indicator.indicator_type, Indicator.minimum_history_period,
                Indicator.outlier_method, Indicator.historical_enabled,
            )).first()
        assert row == ("count", 3, "auto", True)
        # idempotent: a second run must not raise
        _ensure_required_columns(engine)
    finally:
        engine.dispose()


def test_layered_outlier_results_columns_match_spec():
    cols = LayeredOutlierResult.__table__.columns
    expected = {
        "id", "hospital_id", "indicator_id", "analysis_code", "month",
        "raw_value", "previous_value", "numerator", "denominator", "rate",
        "previous_denominator", "denominator_change_percent",
        "historical_mean", "historical_median", "historical_std",
        "historical_z_score", "historical_change_percent",
        "raw_value_outlier_score", "rate_outlier_score", "historical_outlier_score",
        "volume_anomaly_score", "peer_outlier_score", "peer_mean", "peer_count",
        "outlier_level", "outlier_type", "outlier_method", "interpretation",
        "investigation_required", "investigation_route", "created_at",
    }
    assert set(cols.keys()) == expected
    assert cols["hospital_id"].nullable is False
    assert cols["analysis_code"].nullable is False
    assert cols["month"].nullable is False
    assert cols["indicator_id"].nullable is True
    names = {c.name for c in LayeredOutlierResult.__table_args__
             if c.__class__.__name__ == "UniqueConstraint"}
    assert names == {"uq_layered_hosp_code_month"}
    idx = {i.name for i in LayeredOutlierResult.__table__.indexes}
    assert {"ix_lr_hosp_month", "ix_lr_month_type"} <= idx


def test_layered_outlier_results_unique_key(db_session):
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-01", outlier_level="NONE",
                                        outlier_type="NORMAL"))
    db_session.flush()
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-01"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    # same analysis_code, different month/hospital is fine
    db_session.add(LayeredOutlierResult(hospital_id=1, analysis_code="5",
                                        month="2026-02"))
    db_session.add(LayeredOutlierResult(hospital_id=2, analysis_code="5",
                                        month="2026-01"))
    db_session.flush()
    db_session.rollback()


def test_rate_config_columns_match_spec():
    cols = RateConfig.__table__.columns
    expected = {
        "id", "rate_code", "rate_name", "indicator_type", "numerator_codes",
        "denominator_codes", "rate_multiplier", "minimum_denominator",
        "minimum_history_period", "outlier_method", "historical_enabled",
        "peer_comparison_enabled", "is_active",
    }
    assert set(cols.keys()) == expected
    assert cols["rate_code"].nullable is False
    assert cols["minimum_denominator"].nullable is True  # NULL = guard dormant (§12)
    names = {c.name for c in RateConfig.__table_args__
             if c.__class__.__name__ == "UniqueConstraint"}
    assert names == {"uq_rate_config_code"}


def test_seed_rate_config_parity_with_zscore_slice(db_session):
    rows = {r.rate_code: r for r in db_session.query(RateConfig).all()}
    specs = zscore_specs()
    assert set(rows) == {s.rate_code for s in specs}   # seeded by conftest
    for spec in specs:
        row = rows[spec.rate_code]
        assert row.rate_name == spec.rate_name
        assert row.indicator_type == spec.indicator_type
        assert row.numerator_codes == list(spec.numerator_codes)
        assert row.denominator_codes == list(spec.denominator_codes)
        assert row.rate_multiplier == spec.rate_multiplier == 100
        assert row.minimum_denominator is None      # dormant guard (§12)
        assert row.minimum_history_period == 3
        assert row.outlier_method == "auto"
        assert row.historical_enabled is True
        assert row.peer_comparison_enabled is True
        assert row.is_active is True


def test_seed_rate_config_is_idempotent(db_session):
    db_session.query(RateConfig).delete()
    db_session.commit()
    assert seed_rate_config(db_session) == 7
    assert seed_rate_config(db_session) == 0
    assert db_session.query(RateConfig).count() == 7


def test_load_rate_specs_falls_back_to_builtin_when_table_empty(db_session):
    db_session.query(RateConfig).delete()
    db_session.commit()
    invalidate_rate_specs_cache()
    specs = load_rate_specs(db_session)
    assert set(specs) == {s.rate_code for s in zscore_specs()}
    assert specs["rate_mmr"].denominator_codes == ("2",)  # zscore-slice value


def test_load_rate_specs_db_rows_override_builtin(db_session):
    invalidate_rate_specs_cache()
    row = db_session.query(RateConfig).filter_by(rate_code="rate_mmr").one()
    row.rate_multiplier = 100000
    row.minimum_denominator = 6
    db_session.commit()
    specs = load_rate_specs(db_session)
    assert specs["rate_mmr"].rate_multiplier == 100000.0
    assert specs["rate_mmr"].minimum_denominator == 6
    assert specs["rate_mmr"].unit == "per 100"          # inherited from builtin base
    assert specs["rate_mmr"].typical_pct == 1.0
    assert specs["rate_cs"].rate_multiplier == 100.0     # untouched row unchanged
    db_session.rollback()


def test_load_rate_specs_inactive_row_is_flagged_not_dropped(db_session):
    invalidate_rate_specs_cache()
    db_session.query(RateConfig).filter_by(rate_code="rate_nicu").one().is_active = False
    db_session.commit()
    specs = load_rate_specs(db_session)
    assert specs["rate_nicu"].is_active is False   # engine filters; builtin must not resurrect it
    db_session.rollback()


def test_load_rate_specs_caches_until_invalidated(db_session):
    invalidate_rate_specs_cache()
    first = load_rate_specs(db_session)
    db_session.query(RateConfig).filter_by(rate_code="rate_cs").one().rate_multiplier = 1
    db_session.commit()
    assert load_rate_specs(db_session) is first
    assert first["rate_cs"].rate_multiplier == 100.0
    invalidate_rate_specs_cache()
    assert load_rate_specs(db_session)["rate_cs"].rate_multiplier == 1.0
    db_session.rollback()


def test_get_spec_lookup_and_miss(db_session):
    invalidate_rate_specs_cache()
    spec = get_spec(db_session, "rate_cs")
    assert spec is not None and spec.rate_code == "rate_cs"
    assert get_spec(db_session, "no_such_rate") is None


def test_migration_revision_is_new_head():
    from alembic.config import Config as AlembicConfig
    from alembic.script import ScriptDirectory
    from app.config import BASE_DIR
    script = ScriptDirectory.from_config(AlembicConfig(os.path.join(BASE_DIR, "alembic.ini")))
    assert script.get_current_head() == "b1c2d3e4f5a6"
    assert script.get_revision("b1c2d3e4f5a6").down_revision == "a9c8e7d6f5b4"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_schema.py -v`
Expected: collection FAILS with `ImportError: cannot import name 'LayeredOutlierResult' from 'app.models'`.

- [ ] **Step 3: Add the models**

In `app/models.py`:

1. Add `text` to the `sqlalchemy` import block (lines 3-16, alphabetical: between `Table` and `Text`).
2. In class `Indicator`, after `requirement_type` (line 104), add:

```python
    # Layered-outlier analysis config (design spec 2026-10-08 §3.2): count /
    # raw-layer settings only — numerator/denominator/multiplier live in the
    # rate_config table. All nullable + server-defaulted so the startup
    # _ensure_required_columns() self-heal path can add them safely, and so
    # rows predating the migration read the same defaults.
    indicator_type = Column(String(20), nullable=True, server_default="count", default="count")
    minimum_history_period = Column(Integer, nullable=True, server_default="3", default=3)
    outlier_method = Column(String(30), nullable=True, server_default="auto", default="auto")
    historical_enabled = Column(Boolean, nullable=True, server_default=text("true"), default=True)
    peer_comparison_enabled = Column(Boolean, nullable=True, server_default=text("true"), default=True)
```

3. After class `AnomalyResult` (line 299), add the two new classes:

```python
class RateConfig(Base):
    """Rate definitions & layered-engine tuning (design spec 2026-10-08 §3.3).

    Rows are seeded insert-if-missing from the registry's zscore slice
    (scripts/seed_indicators.py::seed_rate_config) and merged over the
    builtin defaults by app/engine/rate_config.py::load_rate_specs.
    """
    __tablename__ = "rate_config"

    id = Column(Integer, primary_key=True, index=True)
    rate_code = Column(String(50), nullable=False, index=True)
    rate_name = Column(String(200), nullable=True)
    indicator_type = Column(String(20), nullable=True)          # rate | ratio | percentage
    numerator_codes = Column(JSON, nullable=True)               # ["5"]
    denominator_codes = Column(JSON, nullable=True)             # ["2"]
    rate_multiplier = Column(Integer, nullable=True)            # 100 / 1000 / 1
    minimum_denominator = Column(Integer, nullable=True)        # NULL = guard dormant (§12)
    minimum_history_period = Column(Integer, nullable=True, server_default="3")
    outlier_method = Column(String(30), nullable=True, server_default="auto")
    historical_enabled = Column(Boolean, nullable=True, server_default=text("true"))
    peer_comparison_enabled = Column(Boolean, nullable=True, server_default=text("true"))
    is_active = Column(Boolean, nullable=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("rate_code", name="uq_rate_config_code"),
    )


class LayeredOutlierResult(Base):
    """One row per hospital x analysis unit x month (design spec 2026-10-08 §3.1).

    analysis_code is the row's analysis unit: the data-element code for count
    rows, the synthetic rate code (rate_cs, ...) for rate rows. Written by
    app/engine/pipeline.py::_save_layered_results; never mutated afterwards.
    """
    __tablename__ = "layered_outlier_results"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=True)
    analysis_code = Column(String(50), nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    raw_value = Column(Float, nullable=True)
    previous_value = Column(Float, nullable=True)
    numerator = Column(Float, nullable=True)
    denominator = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    previous_denominator = Column(Float, nullable=True)
    denominator_change_percent = Column(Float, nullable=True)
    historical_mean = Column(Float, nullable=True)
    historical_median = Column(Float, nullable=True)
    historical_std = Column(Float, nullable=True)
    historical_z_score = Column(Float, nullable=True)
    historical_change_percent = Column(Float, nullable=True)
    raw_value_outlier_score = Column(Float, nullable=True)
    rate_outlier_score = Column(Float, nullable=True)
    historical_outlier_score = Column(Float, nullable=True)
    volume_anomaly_score = Column(Float, nullable=True)
    peer_outlier_score = Column(Float, nullable=True)
    peer_mean = Column(Float, nullable=True)
    peer_count = Column(Integer, nullable=True)
    outlier_level = Column(String(20), nullable=True)           # NONE/LOW/MODERATE/HIGH/VERY_HIGH
    outlier_type = Column(String(40), nullable=True)            # classification enum (§3.1)
    outlier_method = Column(String(30), nullable=True)
    interpretation = Column(Text, nullable=True)
    investigation_required = Column(Boolean, nullable=True, server_default=text("false"))
    investigation_route = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("Hospital")
    indicator = relationship("Indicator")

    __table_args__ = (
        UniqueConstraint("hospital_id", "analysis_code", "month", name="uq_layered_hosp_code_month"),
        Index("ix_lr_hosp_month", "hospital_id", "month"),
        Index("ix_lr_month_type", "month", "outlier_type"),
    )
```

- [ ] **Step 4: Sanity-check the models (tests still fail at collection — expected)**

The test module imports `load_rate_specs`/`get_spec` (Step 7) and `seed_rate_config` (Step 6), which do not exist yet, so pytest still fails at collection. Verify the models directly instead:

Run: `.venv\Scripts\python.exe -c "from app.models import RateConfig, LayeredOutlierResult, Indicator; print(len(RateConfig.__table__.columns), len(LayeredOutlierResult.__table__.columns), Indicator.__table__.columns['indicator_type'].server_default.arg)"`
Expected: `13 31 count`

- [ ] **Step 5: Write the alembic revision**

Create `alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py`:

```python
"""add layered outlier analysis schema

Revision ID: b1c2d3e4f5a6
Revises: a9c8e7d6f5b4
Create Date: 2026-10-08

Layered Outlier Analysis (design spec 2026-10-08):
  * layered_outlier_results — one row per hospital x analysis unit x month,
    unique (hospital_id, analysis_code, month).
  * rate_config — rate definitions & layered-engine tuning rows; seeded from
    the registry zscore slice (seed_indicators.py::seed_rate_config).
  * indicators.{indicator_type,minimum_history_period,outlier_method,
    historical_enabled,peer_comparison_enabled} — count/raw-layer config.

Idempotent, same style as a9c8e7d6f5b4: fresh DBs bootstrap via
Base.metadata.create_all + stamp head, so a bare `upgrade head` on an
empty/partial DB must not crash or double-create. Boolean server defaults
use sa.text('true'/'false') — a QUOTED string default ('false') is stored
as text by SQLite and reads back as True through SQLAlchemy's Boolean
converter.
"""
import sqlalchemy as sa
from alembic import op

revision = 'b1c2d3e4f5a6'
down_revision = 'a9c8e7d6f5b4'
branch_labels = None
depends_on = None


def _table_state(bind, table):
    from sqlalchemy import inspect
    insp = inspect(bind)
    if table not in set(insp.get_table_names()):
        return False, set()
    return True, {c["name"] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()

    have_lor, _ = _table_state(bind, "layered_outlier_results")
    if not have_lor:
        op.create_table(
            'layered_outlier_results',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('indicator_id', sa.Integer(), sa.ForeignKey('indicators.id'), nullable=True),
            sa.Column('analysis_code', sa.String(length=50), nullable=False),
            sa.Column('month', sa.String(length=7), nullable=False),
            sa.Column('raw_value', sa.Float(), nullable=True),
            sa.Column('previous_value', sa.Float(), nullable=True),
            sa.Column('numerator', sa.Float(), nullable=True),
            sa.Column('denominator', sa.Float(), nullable=True),
            sa.Column('rate', sa.Float(), nullable=True),
            sa.Column('previous_denominator', sa.Float(), nullable=True),
            sa.Column('denominator_change_percent', sa.Float(), nullable=True),
            sa.Column('historical_mean', sa.Float(), nullable=True),
            sa.Column('historical_median', sa.Float(), nullable=True),
            sa.Column('historical_std', sa.Float(), nullable=True),
            sa.Column('historical_z_score', sa.Float(), nullable=True),
            sa.Column('historical_change_percent', sa.Float(), nullable=True),
            sa.Column('raw_value_outlier_score', sa.Float(), nullable=True),
            sa.Column('rate_outlier_score', sa.Float(), nullable=True),
            sa.Column('historical_outlier_score', sa.Float(), nullable=True),
            sa.Column('volume_anomaly_score', sa.Float(), nullable=True),
            sa.Column('peer_outlier_score', sa.Float(), nullable=True),
            sa.Column('peer_mean', sa.Float(), nullable=True),
            sa.Column('peer_count', sa.Integer(), nullable=True),
            sa.Column('outlier_level', sa.String(length=20), nullable=True),
            sa.Column('outlier_type', sa.String(length=40), nullable=True),
            sa.Column('outlier_method', sa.String(length=30), nullable=True),
            sa.Column('interpretation', sa.Text(), nullable=True),
            sa.Column('investigation_required', sa.Boolean(), nullable=True,
                      server_default=sa.text('false')),
            sa.Column('investigation_route', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('hospital_id', 'analysis_code', 'month',
                                name='uq_layered_hosp_code_month'),
        )
        op.create_index('ix_layered_outlier_results_id', 'layered_outlier_results', ['id'])
        op.create_index('ix_layered_outlier_results_hospital_id', 'layered_outlier_results', ['hospital_id'])
        op.create_index('ix_layered_outlier_results_analysis_code', 'layered_outlier_results', ['analysis_code'])
        op.create_index('ix_layered_outlier_results_month', 'layered_outlier_results', ['month'])
        op.create_index('ix_lr_hosp_month', 'layered_outlier_results', ['hospital_id', 'month'])
        op.create_index('ix_lr_month_type', 'layered_outlier_results', ['month', 'outlier_type'])

    have_rc, _ = _table_state(bind, "rate_config")
    if not have_rc:
        op.create_table(
            'rate_config',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('rate_code', sa.String(length=50), nullable=False),
            sa.Column('rate_name', sa.String(length=200), nullable=True),
            sa.Column('indicator_type', sa.String(length=20), nullable=True),
            sa.Column('numerator_codes', sa.JSON(), nullable=True),
            sa.Column('denominator_codes', sa.JSON(), nullable=True),
            sa.Column('rate_multiplier', sa.Integer(), nullable=True),
            sa.Column('minimum_denominator', sa.Integer(), nullable=True),
            sa.Column('minimum_history_period', sa.Integer(), nullable=True,
                      server_default='3'),
            sa.Column('outlier_method', sa.String(length=30), nullable=True,
                      server_default='auto'),
            sa.Column('historical_enabled', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.Column('peer_comparison_enabled', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.Column('is_active', sa.Boolean(), nullable=True,
                      server_default=sa.text('true')),
            sa.UniqueConstraint('rate_code', name='uq_rate_config_code'),
        )
        op.create_index('ix_rate_config_id', 'rate_config', ['id'])
        op.create_index('ix_rate_config_rate_code', 'rate_config', ['rate_code'])

    have_ind, ind_cols = _table_state(bind, "indicators")
    if have_ind:
        new_cols = {
            "indicator_type": sa.Column('indicator_type', sa.String(length=20),
                                        nullable=True, server_default='count'),
            "minimum_history_period": sa.Column('minimum_history_period', sa.Integer(),
                                                nullable=True, server_default='3'),
            "outlier_method": sa.Column('outlier_method', sa.String(length=30),
                                        nullable=True, server_default='auto'),
            "historical_enabled": sa.Column('historical_enabled', sa.Boolean(),
                                            nullable=True, server_default=sa.text('true')),
            "peer_comparison_enabled": sa.Column('peer_comparison_enabled', sa.Boolean(),
                                                 nullable=True, server_default=sa.text('true')),
        }
        for name, col in new_cols.items():
            if name not in ind_cols:
                op.add_column('indicators', col)


def downgrade():
    bind = op.get_bind()
    have_ind, ind_cols = _table_state(bind, "indicators")
    if have_ind:
        for name in ("peer_comparison_enabled", "historical_enabled", "outlier_method",
                     "minimum_history_period", "indicator_type"):
            if name in ind_cols:
                op.drop_column('indicators', name)
    have_rc, _ = _table_state(bind, "rate_config")
    if have_rc:
        op.drop_table('rate_config')
    have_lor, _ = _table_state(bind, "layered_outlier_results")
    if have_lor:
        op.drop_table('layered_outlier_results')
```

- [ ] **Step 6: Seed function, startup backfill, conftest wiring**

1. `scripts/seed_indicators.py` — append after `seed_indicators()`:

```python
def seed_rate_config(session):
    """Insert-if-missing the registry's zscore slice into rate_config.

    Spec 2026-10-08 §4.2: DB rows are seeded from the builtin zscore slice
    (rate_multiplier 100 for all 7 rates, minimum_denominator NULL = guard
    dormant); the engine merges DB tunables over builtin defaults. Returns
    the number of rows added; invalidates the in-process spec cache.
    """
    from app.engine.rate_config import invalidate_rate_specs_cache, zscore_specs
    from app.models import RateConfig

    existing = {code for (code,) in session.query(RateConfig.rate_code).all()}
    added = 0
    for spec in zscore_specs():
        if spec.rate_code in existing:
            continue
        session.add(RateConfig(
            rate_code=spec.rate_code,
            rate_name=spec.rate_name,
            indicator_type=spec.indicator_type,
            numerator_codes=list(spec.numerator_codes),
            denominator_codes=list(spec.denominator_codes),
            rate_multiplier=int(spec.rate_multiplier),
            minimum_denominator=None,
            minimum_history_period=spec.minimum_history_period,
            outlier_method=spec.outlier_method,
            historical_enabled=spec.historical_enabled,
            peer_comparison_enabled=spec.peer_comparison_enabled,
            is_active=spec.is_active,
        ))
        added += 1
    if added:
        session.commit()
    invalidate_rate_specs_cache()
    return added
```

2. `app/main.py`:
   - Line 60: `from scripts.seed_indicators import seed_indicators  # noqa: E402` → `from scripts.seed_indicators import seed_indicators, seed_rate_config  # noqa: E402`
   - After the menu-backfill block (lines 660-669), before the hospital-metadata block, insert:

```python
            # Seed layered rate_config rows from the central registry
            # (idempotent insert-if-missing — same every-startup pattern as
            # the menu backfill above). The engine falls back to the builtin
            # registry when the table is empty, so a seed failure is non-fatal.
            try:
                seeded = seed_rate_config(session)
                if seeded:
                    print(f"[startup] Rate config seeded: {seeded} rows.")
            except Exception as e:
                print(f"[startup] Rate config seed error (non-fatal): {e}")
```

3. `tests/conftest.py`:
   - Line 8: `from scripts.seed_indicators import seed_indicators` → `from scripts.seed_indicators import seed_indicators, seed_rate_config`
   - In `db_session`, after `seed_indicators(session)` (line 186): add `seed_rate_config(session)`
   - Append the autouse cache reset (anywhere at module level):

```python
@pytest.fixture(autouse=True)
def _reset_rate_specs_cache():
    """load_rate_specs caches the DB-merged spec set in-process; reset it
    around every test so one test's rate_config rows can never leak into the
    next test (each test gets its own SQLite file, the cache does not)."""
    from app.engine.rate_config import invalidate_rate_specs_cache
    invalidate_rate_specs_cache()
    yield
    invalidate_rate_specs_cache()
```

- [ ] **Step 7: Add the DB-over-builtin loader to `rate_config.py`**

Append to `app/engine/rate_config.py`:

```python
# ── DB layer (design spec §4): rate_config rows merged over builtin ──────────

_RATE_SPECS_CACHE: Optional[Dict[str, RateSpec]] = None


def invalidate_rate_specs_cache() -> None:
    """Drop the DB-merged spec cache (seed_rate_config and any future
    rate_config save call this; tests reset it around every test)."""
    global _RATE_SPECS_CACHE
    _RATE_SPECS_CACHE = None


def _pick(value, fallback):
    return fallback if value is None else value


def _spec_from_rate_config_row(row, base: Optional[RateSpec]) -> RateSpec:
    """DB row over its builtin base. unit/typical_pct are not stored in the
    table (spec §3.3) — inherited from the builtin zscore-slice spec with the
    same rate_code; unknown rate_codes get empty unit."""
    numerator = tuple(row.numerator_codes or ())
    denominator = tuple(row.denominator_codes or ())
    multiplier = row.rate_multiplier if row.rate_multiplier is not None else (
        base.rate_multiplier if base else 1.0)
    return RateSpec(
        spec_key=f"db:{row.rate_code}",
        site=SITE_ZSCORE,
        rate_code=row.rate_code,
        rate_name=row.rate_name or (base.rate_name if base else row.rate_code),
        indicator_code=numerator[0] if numerator else (base.indicator_code if base else ""),
        indicator_type=row.indicator_type or (base.indicator_type if base else "rate"),
        numerator_codes=numerator,
        denominator_codes=denominator,
        rate_multiplier=float(multiplier),
        unit=base.unit if base else "",
        typical_pct=base.typical_pct if base else None,
        minimum_denominator=row.minimum_denominator,
        minimum_history_period=_pick(
            row.minimum_history_period,
            base.minimum_history_period if base else 3),
        outlier_method=row.outlier_method or (base.outlier_method if base else "auto"),
        historical_enabled=_pick(
            row.historical_enabled,
            base.historical_enabled if base else True),
        peer_comparison_enabled=_pick(
            row.peer_comparison_enabled,
            base.peer_comparison_enabled if base else True),
        is_active=_pick(row.is_active, True),
    )


def load_rate_specs(db) -> Dict[str, RateSpec]:
    """The layered engine's spec set, keyed by rate_code: DB rate_config rows
    (runtime tunables) merged over the builtin zscore-slice defaults.

    Falls back entirely to the builtin slice when the table is empty
    (pre-seed operation) or unreadable. In-process cache — call
    invalidate_rate_specs_cache() after seeding/saving rate_config rows.
    """
    global _RATE_SPECS_CACHE
    if _RATE_SPECS_CACHE is not None:
        return _RATE_SPECS_CACHE
    specs: Dict[str, RateSpec] = {s.rate_code: s for s in zscore_specs()}
    try:
        from app.models import RateConfig  # local: this module stays leaf-importable
        rows = db.query(RateConfig).order_by(RateConfig.rate_code).all()
    except Exception as exc:
        logger.warning("rate_config unreadable (%s); using builtin zscore slice", exc)
        rows = []
    for row in rows:
        specs[row.rate_code] = _spec_from_rate_config_row(row, specs.get(row.rate_code))
    _RATE_SPECS_CACHE = specs
    return specs


def get_spec(db, rate_code: str) -> Optional[RateSpec]:
    return load_rate_specs(db).get(rate_code)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_schema.py -v`
Expected: all PASS.

- [ ] **Step 9: Lint, regression, commit**

Run: `.venv\Scripts\ruff.exe check app/models.py app/main.py app/engine/rate_config.py scripts/seed_indicators.py tests/conftest.py tests/test_layered_schema.py alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py`
Run: `.venv\Scripts\python.exe -m pytest tests/test_migrations.py tests/test_migration_guard.py tests/test_indicator_groups.py tests/test_rate_config.py -v`
Expected: no lint errors; all PASS (the migration chain still resolves to the new head; registry untouched).

```bash
git add app/models.py app/main.py app/engine/rate_config.py scripts/seed_indicators.py tests/conftest.py tests/test_layered_schema.py alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py
git commit -m "feat(schema): layered_outlier_results + rate_config tables, indicator layer config"
```

---

### Task 7: Layered engine — scoring core, bands, method selection

**Files:**
- Create: `app/engine/anomaly/layered.py` (scoring core only; layers come in Tasks 8-10, entry point in Task 12)
- Create: `tests/test_layered_engine.py`

**Interfaces:**
- Consumes: nothing (stdlib only — `math`, `statistics`, `dataclasses`; no app imports at module level).
- Produces (Tasks 8-12 depend on these exact names):
  - Levels: `LEVEL_NONE/LOW/MODERATE/HIGH/VERY_HIGH`, `LEVELS`, `LEVEL_RANK`, `BAND_CUTOFFS`, `level_for_score(score) -> Optional[str]`, `level_rank`, `level_gte(level, minimum) -> bool` (None-safe), `max_level(levels) -> str` (NONE when nothing applicable).
  - Methods: `METHOD_AUTO/ZSCORE/IQR/ROLLING_MEDIAN_MAD/PCT_CHANGE/TREND_DEVIATION/PEER_ZSCORE/INSUFFICIENT_HISTORY`.
  - Constants: `CV_MAX=0.5`, `MIN_IQR_POINTS=6`, `MIN_TREND_POINTS=6`, `RARE_EVENT_MEAN_MAX=10.0`, `MAD_SCALE=1.4826`, `DEFAULT_MINIMUM_HISTORY=3`, `PEER_Z_THRESHOLD_DEFAULT=2.5`.
  - `Thresholds` frozen dataclass (`peer_z_threshold=2.5`); `AnalysisSpec` frozen dataclass (fields: `analysis_code, name, indicator_type="count", indicator_id=None, numerator_codes=(), denominator_codes=(), rate_multiplier=1.0, unit="", minimum_denominator=None, minimum_history_period=3, outlier_method="auto", historical_enabled=True, peer_comparison_enabled=True`; property `is_rate`).
  - Stats helpers: `mean, median, std (ddof=1, None when <2 pts), mad, quartiles (inclusive; (v,v,v) for 1 pt), coefficient_of_variation (mean==0 → inf), percent_change(current, previous) (None when previous missing/0)`.
  - Score builders (spec §5 formulas verbatim): `score_from_z(z, threshold)` → `min(1, |z|/(2×threshold))`; `score_from_pct_change(pct)` → `min(1, |pct|/100)`; `score_from_mad(value, center, mad_value)` → `min(1, |v−c|/(3×1.4826×MAD))`, MAD 0 → 1.0 iff unequal; `score_from_iqr(value, q1, q3)` → tukey-fence distance / (2×IQR), 0 inside fences, IQR 0 → 1.0 iff outside [q1,q3]; `score_from_trend(actual, projected, residual_std)` → `min(1, |a−p|/(2×std))`, std ≤0 → 1.0 iff unequal.
  - `select_method(configured, series, indicator_type)` — explicit config wins; `auto`: rare-event (`indicator_type=="count"` and mean < `RARE_EVENT_MEAN_MAX`, n≥3) → `rolling_median_mad`; CV < 0.5 (n≥3) → `pct_change`; n≥6 → `iqr`; else `zscore`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_layered_engine.py`:

```python
"""Layered outlier engine: scoring core (Task 7), layers (Tasks 8-10),
classification (Task 11), end-to-end scenarios (Task 12) — spec sections 5/6/11."""
import math

import pytest

from app.engine.anomaly.layered import (
    METHOD_AUTO,
    METHOD_IQR,
    METHOD_PCT_CHANGE,
    METHOD_ROLLING_MEDIAN_MAD,
    METHOD_ZSCORE,
    RARE_EVENT_MEAN_MAX,
    AnalysisSpec,
    LEVELS,
    Thresholds,
    coefficient_of_variation,
    level_for_score,
    level_gte,
    max_level,
    median,
    percent_change,
    quartiles,
    score_from_iqr,
    score_from_mad,
    score_from_pct_change,
    score_from_trend,
    score_from_z,
    select_method,
    std,
)


# ── Severity bands (spec §5 table: <0.25 NONE, <0.50 LOW, <0.75 MODERATE,
#    <0.90 HIGH, >=0.90 VERY_HIGH) ─────────────────────────────────────────

@pytest.mark.parametrize("score,level", [
    (0.0, "NONE"), (0.24, "NONE"), (0.2499, "NONE"),
    (0.25, "LOW"), (0.49, "LOW"), (0.4999, "LOW"),
    (0.50, "MODERATE"), (0.74, "MODERATE"),
    (0.75, "HIGH"), (0.89, "HIGH"),
    (0.90, "VERY_HIGH"), (1.0, "VERY_HIGH"),
])
def test_band_cutoffs(score, level):
    assert level_for_score(score) == level


def test_level_for_score_none_and_negative():
    assert level_for_score(None) is None
    assert level_for_score(-0.5) == "NONE"


def test_levels_ordering_and_helpers():
    assert LEVELS == ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH")
    assert level_gte("HIGH", "MODERATE") is True
    assert level_gte("LOW", "MODERATE") is False
    assert level_gte("HIGH", "HIGH") is True
    assert level_gte(None, "LOW") is False          # None never satisfies a minimum
    assert max_level([None, None]) == "NONE"
    assert max_level([]) == "NONE"
    assert max_level([None, "LOW", "HIGH", "MODERATE"]) == "HIGH"


def test_score_builders_match_spec_formulae():
    # z-based: |z| = threshold => 0.5; |z| = 2*threshold => 1.0
    assert score_from_z(2.5, 2.5) == 0.5
    assert score_from_z(5.0, 2.5) == 1.0
    assert score_from_z(-3.0, 2.5) == pytest.approx(0.6)
    assert score_from_z(0.0, 2.5) == 0.0
    # percentage change: 100% => 1.0
    assert score_from_pct_change(100.0) == 1.0
    assert score_from_pct_change(-150.0) == 1.0
    assert score_from_pct_change(25.0) == 0.25
    # rolling median + MAD: 3 * 1.4826 * MAD scaling; zero MAD edge cases
    assert score_from_mad(10.0, 5.0, 2.0) == pytest.approx(5.0 / (3 * 1.4826 * 2))
    assert score_from_mad(5.0, 5.0, 0.0) == 0.0
    assert score_from_mad(7.0, 5.0, 0.0) == 1.0
    # IQR tukey fences: q1=10 q3=20 => fences -5 / 35, 2*IQR = 20
    assert score_from_iqr(15.0, 10.0, 20.0) == 0.0                    # inside fences
    assert score_from_iqr(40.0, 10.0, 20.0) == pytest.approx(5.0 / 20.0)
    assert score_from_iqr(55.0, 10.0, 20.0) == 1.0                    # distance 20
    assert score_from_iqr(35.0, 10.0, 20.0) == 0.0                    # exactly on fence
    # trend deviation: |actual-projected| / (2 * residual_std)
    assert score_from_trend(12.0, 8.0, 2.0) == 1.0
    assert score_from_trend(9.0, 8.0, 2.0) == 0.25
    assert score_from_trend(8.0, 8.0, 0.0) == 0.0
    assert score_from_trend(9.0, 8.0, 0.0) == 1.0


def test_statistics_helpers():
    assert median([3, 1, 2]) == 2
    assert std([1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert std([1.0]) is None
    assert quartiles([1, 2, 3, 4]) == (1.75, 2.5, 3.25)   # inclusive method
    assert quartiles([7]) == (7.0, 7.0, 7.0)
    assert coefficient_of_variation([0.0, 0.0]) == math.inf
    assert coefficient_of_variation([100.0, 105.0, 98.0]) < 0.5
    assert percent_change(150, 100) == 50.0
    assert percent_change(50, 100) == -50.0
    assert percent_change(10, 0) is None
    assert percent_change(10, None) is None
    assert percent_change(None, 10) is None


# ── Method selection (spec §5 Layer 1 + rare-event rule) ──────────────────

def test_select_method_explicit_config_wins():
    assert select_method("iqr", [1.0, 2.0], "count") == METHOD_IQR
    assert select_method("pct_change", [], "rate") == METHOD_PCT_CHANGE
    assert select_method(None, [1.0, 2.0], "count") == METHOD_ZSCORE


def test_select_method_auto_chain():
    assert RARE_EVENT_MEAN_MAX == 10.0
    # rare-event counts (low mean): rolling median + MAD, never plain z
    rare = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    assert select_method(METHOD_AUTO, rare, "count") == METHOD_ROLLING_MEDIAN_MAD
    # identical series is NOT rare-event as a rate type -> falls to iqr (n>=6)
    assert select_method(METHOD_AUTO, rare, "rate") == METHOD_IQR
    # stable series (CV < 0.5, n >= 3) -> pct_change
    stable = [100.0, 105.0, 98.0, 103.0]
    assert select_method(METHOD_AUTO, stable, "count") == METHOD_PCT_CHANGE
    # volatile series with >= 6 points -> iqr
    volatile6 = [10.0, 100.0, 12.0, 90.0, 15.0, 80.0]
    assert select_method(METHOD_AUTO, volatile6, "rate") == METHOD_IQR
    # volatile series with < 6 points -> zscore fallback
    assert select_method(METHOD_AUTO, [10.0, 90.0], "rate") == METHOD_ZSCORE
    assert select_method(METHOD_AUTO, [10.0, 90.0, 15.0], "rate") == METHOD_ZSCORE
    # empty series -> zscore (scored None by the layer functions later)
    assert select_method(METHOD_AUTO, [], "rate") == METHOD_ZSCORE


def test_analysis_spec_defaults_and_rate_flag():
    spec = AnalysisSpec(analysis_code="5", name="C-sections")
    assert spec.is_rate is False
    assert spec.indicator_type == "count"
    assert spec.minimum_history_period == 3
    assert spec.outlier_method == METHOD_AUTO
    rate_spec = AnalysisSpec(
        analysis_code="rate_cs", name="C-section rate",
        indicator_type="percentage", numerator_codes=("5",),
        denominator_codes=("2",), rate_multiplier=100.0, unit="%",
    )
    assert rate_spec.is_rate is True


def test_thresholds_default_matches_appconfig():
    assert Thresholds().peer_z_threshold == 2.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.anomaly.layered'`

- [ ] **Step 3: Write the implementation**

Create `app/engine/anomaly/layered.py`:

```python
"""Layered outlier analysis engine — scoring core (design spec 2026-10-08 §5).

Pure functions and constants; no DB access, no I/O, no app imports at module
level. The pipeline (app/engine/pipeline.py) gathers history/peers and
persists results; classification lives in app/engine/anomaly/classify.py.

Every layer maps a deviation to a 0-1 score which maps to a severity band:
<0.25 NONE | <0.50 LOW | <0.75 MODERATE | <0.90 HIGH | >=0.90 VERY_HIGH.
"""
import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

# ── Severity bands (spec §5) ───────────────────────────────────────────────
LEVEL_NONE = "NONE"
LEVEL_LOW = "LOW"
LEVEL_MODERATE = "MODERATE"
LEVEL_HIGH = "HIGH"
LEVEL_VERY_HIGH = "VERY_HIGH"
LEVELS = (LEVEL_NONE, LEVEL_LOW, LEVEL_MODERATE, LEVEL_HIGH, LEVEL_VERY_HIGH)
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
# (exclusive upper bound, level): a score maps to the first bound it is <.
BAND_CUTOFFS: Tuple[Tuple[float, str], ...] = (
    (0.25, LEVEL_NONE),
    (0.50, LEVEL_LOW),
    (0.75, LEVEL_MODERATE),
    (0.90, LEVEL_HIGH),
    (math.inf, LEVEL_VERY_HIGH),
)

# ── Detection methods (spec §3.1 outlier_method enum) ─────────────────────
METHOD_AUTO = "auto"
METHOD_ZSCORE = "zscore"
METHOD_IQR = "iqr"
METHOD_ROLLING_MEDIAN_MAD = "rolling_median_mad"
METHOD_PCT_CHANGE = "pct_change"
METHOD_TREND_DEVIATION = "trend_deviation"
METHOD_PEER_ZSCORE = "peer_zscore"
METHOD_INSUFFICIENT_HISTORY = "insufficient_history"

# ── Method-selection constants (spec §5 "Thresholds": no new knobs) ───────
CV_MAX = 0.5                     # auto -> pct_change when CV below this
MIN_IQR_POINTS = 6               # auto -> iqr needs at least this many points
MIN_TREND_POINTS = 6             # trend_deviation / Theil-Sen need this many
RARE_EVENT_MEAN_MAX = 10.0       # count mean below this: MAD, never plain z
MAD_SCALE = 1.4826               # normal-consistent MAD -> sigma
DEFAULT_MINIMUM_HISTORY = 3      # Indicator.minimum_history_period default
PEER_Z_THRESHOLD_DEFAULT = 2.5   # AppConfig zscore_threshold default


@dataclass(frozen=True)
class Thresholds:
    """Runtime thresholds handed to the engine by the orchestrator."""
    peer_z_threshold: float = PEER_Z_THRESHOLD_DEFAULT


@dataclass(frozen=True)
class AnalysisSpec:
    """One analysis unit: a count-indicator row or a synthetic rate row.

    Built by build_analysis_specs() (Task 12) from Indicator rows (count)
    plus load_rate_specs() (rate). analysis_code is the
    layered_outlier_results row key.
    """
    analysis_code: str
    name: str
    indicator_type: str = "count"        # count | rate | ratio | percentage
    indicator_id: Optional[int] = None
    numerator_codes: Tuple[str, ...] = ()
    denominator_codes: Tuple[str, ...] = ()
    rate_multiplier: float = 1.0
    unit: str = ""
    minimum_denominator: Optional[float] = None   # None = guard dormant
    minimum_history_period: int = DEFAULT_MINIMUM_HISTORY
    outlier_method: str = METHOD_AUTO
    historical_enabled: bool = True
    peer_comparison_enabled: bool = True

    @property
    def is_rate(self) -> bool:
        return bool(self.denominator_codes)


# ── Statistics helpers ─────────────────────────────────────────────────────

def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values)


def median(values: Sequence[float]) -> float:
    return statistics.median(values)


def std(values: Sequence[float]) -> Optional[float]:
    """Sample std (ddof=1); None when fewer than 2 points."""
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def mad(values: Sequence[float]) -> float:
    """Median absolute deviation (unscaled)."""
    center = statistics.median(values)
    return statistics.median([abs(v - center) for v in values])


def quartiles(values: Sequence[float]) -> Tuple[float, float, float]:
    """(q1, median, q3), inclusive (numpy-percentile-compatible) method."""
    if not values:
        raise ValueError("quartiles() of empty series")
    if len(values) == 1:
        v = float(values[0])
        return v, v, v
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q1, q2, q3


def coefficient_of_variation(values: Sequence[float]) -> float:
    if not values:
        return math.inf
    m = statistics.fmean(values)
    if m == 0:
        return math.inf          # mean 0 => never pct_change
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / abs(m)


def percent_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Signed % change against |previous|; None when previous missing/zero."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100.0


# ── Score builders (spec §5 "Score construction per method") ──────────────

def score_from_z(z: float, threshold: float) -> float:
    """|z| == threshold => 0.5 (MODERATE); |z| == 2*threshold => 1.0."""
    if threshold <= 0:
        threshold = PEER_Z_THRESHOLD_DEFAULT
    return min(1.0, abs(z) / (2.0 * threshold))


def score_from_pct_change(pct: float) -> float:
    return min(1.0, abs(pct) / 100.0)


def score_from_mad(value: float, center: float, mad_value: float) -> float:
    """Scaled by 3 * 1.4826 * MAD; MAD == 0 => 1.0 unless value == center."""
    if mad_value == 0:
        return 0.0 if value == center else 1.0
    return min(1.0, abs(value - center) / (3.0 * MAD_SCALE * mad_value))


def score_from_iqr(value: float, q1: float, q3: float) -> float:
    """Tukey-fence distance over 2*IQR; 0 inside the fences."""
    iqr = q3 - q1
    if iqr == 0:
        return 0.0 if q1 <= value <= q3 else 1.0
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    if value < lower:
        distance = lower - value
    elif value > upper:
        distance = value - upper
    else:
        return 0.0
    return min(1.0, distance / (2.0 * iqr))


def score_from_trend(actual: float, projected: float,
                      residual_std: Optional[float]) -> float:
    if residual_std is None or residual_std <= 0:
        return 0.0 if actual == projected else 1.0
    return min(1.0, abs(actual - projected) / (2.0 * residual_std))


# ── Bands ──────────────────────────────────────────────────────────────────

def level_for_score(score: Optional[float]) -> Optional[str]:
    """Band for a 0-1 score; None => layer not applicable (stays NULL)."""
    if score is None:
        return None
    s = max(0.0, float(score))
    for upper, name in BAND_CUTOFFS:
        if s < upper:
            return name
    return LEVEL_VERY_HIGH


def level_rank(level: Optional[str]) -> Optional[int]:
    return LEVEL_RANK.get(level) if level else None


def level_gte(level: Optional[str], minimum: str) -> bool:
    """None-safe: a not-applicable layer never satisfies a minimum."""
    rank = LEVEL_RANK.get(level) if level else None
    return rank is not None and rank >= LEVEL_RANK[minimum]


def max_level(levels: Iterable[Optional[str]]) -> str:
    """Highest applicable level; NONE when nothing is applicable."""
    best = LEVEL_NONE
    for level in levels:
        if level is not None and LEVEL_RANK[level] > LEVEL_RANK[best]:
            best = level
    return best


# ── Method selection (spec §5 Layer 1) ────────────────────────────────────

def select_method(configured: Optional[str], series: Sequence[float],
                  indicator_type: str) -> str:
    """Pick the detection method for one series.

    auto: rare-event counts (mean < RARE_EVENT_MEAN_MAX) use rolling
    median + MAD — never plain z on small counts; then CV < CV_MAX =>
    pct_change; >= MIN_IQR_POINTS => iqr; else zscore. An explicit
    configured method always wins.
    """
    if configured and configured != METHOD_AUTO:
        return configured
    values = [float(v) for v in series]
    n = len(values)
    if n == 0:
        return METHOD_ZSCORE
    if (indicator_type == "count" and n >= 3
            and statistics.fmean(values) < RARE_EVENT_MEAN_MAX):
        return METHOD_ROLLING_MEDIAN_MAD
    if n >= 3 and coefficient_of_variation(values) < CV_MAX:
        return METHOD_PCT_CHANGE
    if n >= MIN_IQR_POINTS:
        return METHOD_IQR
    return METHOD_ZSCORE
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/layered.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/layered.py tests/test_layered_engine.py
git commit -m "feat(layered): scoring core, severity bands, auto method selection"
```

---

### Task 8: Layers 1 + 3 — raw value and historical baseline

**Files:**
- Modify: `app/engine/anomaly/layered.py` (append helpers, `RawLayer`/`HistoricalLayer` dataclasses, `compute_raw_layer`, `compute_historical_layer`)
- Modify: `tests/test_layered_engine.py` (extend the import block + append tests)

**Interfaces:**
- Consumes: Task 7 core (`select_method`, `score_from_*`, `level_for_score`, constants, `AnalysisSpec`); `scipy.stats.theil_slopes` (scipy is an existing dependency — see `app/engine/anomaly/trends.py`).
- Produces (Tasks 12-13 depend on these):
  - Input helpers: `prior_months(history, current_month) -> List[str]` (sorted, strictly before), `raw_analysis_value(spec, values)` (summed numerator for rate rows, `values[analysis_code]` for count rows), `rate_analysis_value(spec, values)` (None for count rows), `denominator_analysis_value(spec, values)` (None for count rows), `_sum_codes` internal.
  - `RawLayer` dataclass: `value, previous, change_percent, score, method` + property `level`.
  - `HistoricalLayer` dataclass: `history_ok, series, current, mean, median, std, z_score, change_percent, score, method, trend_slope, trend_projected, trend_residual_std` + property `level`.
  - `compute_raw_layer(spec, prior, current, history_ok, threshold=PEER_Z_THRESHOLD_DEFAULT) -> RawLayer`
  - `compute_historical_layer(spec, prior, current, history_ok, threshold=PEER_Z_THRESHOLD_DEFAULT) -> HistoricalLayer`
- Behavioral contract (tests pin every clause):
  - `previous` = most recent non-None prior value (gap-tolerant); `change_percent` = % vs `previous`.
  - Not computable (`history_ok=False` or `current is None`) → `score=None`, `method=METHOD_INSUFFICIENT_HISTORY` (the enum's catch-all; classification rule 1 handles `history_ok=False`).
  - `historical_enabled=False` → `score=None` but `history_ok` passes through unchanged (the entry point passes `True` so rule 1 stays waived; other layers still classify).
  - Historical baseline stats over `prior` only; `z_score` stored as `None` when `std` is `None`/`0` (never inf in the DB); `change_percent` vs the baseline **mean** (this is the spec's "+125% above baseline" and rule 2's "+300% vs baseline" input).
  - `spec.outlier_method == "trend_deviation"`: Theil-Sen over ≥ `MIN_TREND_POINTS` (6) prior points → blend `max(window_score, trend_score)`, `method=METHOD_TREND_DEVIATION`; below 6 points → fall back to `select_method(METHOD_AUTO, ...)` window scoring.
  - z-based scoring threshold: the one shared knob (`Thresholds.peer_z_threshold`, default 2.5) — passed as `threshold`.

- [ ] **Step 1: Write the failing tests**

Extend the import block at the top of `tests/test_layered_engine.py` with:

```python
from app.engine.anomaly.layered import (
    METHOD_INSUFFICIENT_HISTORY,
    METHOD_TREND_DEVIATION,
    compute_historical_layer,
    compute_raw_layer,
    denominator_analysis_value,
    prior_months,
    rate_analysis_value,
    raw_analysis_value,
)
```

Append the tests:

```python
# ── Input helpers (Task 8) ─────────────────────────────────────────────────

def test_prior_months_sorted_and_strictly_before_current():
    history = {"2026-04": {}, "2026-02": {}, "2026-01": {}, "2026-03": {}}
    assert prior_months(history, "2026-03") == ["2026-01", "2026-02"]
    assert prior_months(history, "2026-01") == []
    assert prior_months({}, "2026-03") == []


def test_analysis_value_helpers_split_rate_and_count_rows():
    rate_spec = AnalysisSpec(analysis_code="rate_cs", name="C-section rate",
                             indicator_type="percentage", numerator_codes=("5",),
                             denominator_codes=("2",), rate_multiplier=100.0, unit="%")
    count_spec = AnalysisSpec(analysis_code="5", name="C-sections")
    values = {"5": 80.0, "2": 300.0, "6": 250.0}
    assert raw_analysis_value(rate_spec, values) == 80.0          # numerator
    assert rate_analysis_value(rate_spec, values) == pytest.approx(80 / 300 * 100)
    assert denominator_analysis_value(rate_spec, values) == 300.0
    assert raw_analysis_value(count_spec, values) == 80.0         # the element itself
    assert rate_analysis_value(count_spec, values) is None
    assert denominator_analysis_value(count_spec, values) is None
    assert raw_analysis_value(count_spec, {"2": 1}) is None


# ── Layer 1: raw value (spec §5) ──────────────────────────────────────────

def _count_spec(**kw):
    return AnalysisSpec(analysis_code="5", name="C-sections", **kw)


def test_raw_layer_normal_series_is_none_band():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=10.0, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE      # CV = 0 < 0.5
    assert layer.score == 0.0
    assert layer.level == "NONE"
    assert layer.previous == 10.0
    assert layer.change_percent == 0.0
    assert layer.value == 10.0


def test_raw_layer_jump_is_very_high_and_records_method():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=25.0, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE
    assert layer.change_percent == 150.0
    assert layer.score == 1.0                    # |150%| / 100 capped at 1
    assert layer.level == "VERY_HIGH"


def test_raw_layer_boundary_score_maps_to_moderate():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                              current=15.0, history_ok=True)
    assert layer.score == 0.5                    # +50% / 100
    assert layer.level == "MODERATE"             # 0.50 is not < 0.50


def test_raw_layer_insufficient_history_is_not_applicable():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 11.0], current=12.0,
                              history_ok=False)
    assert layer.score is None
    assert layer.level is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
    assert layer.value == 12.0 and layer.previous == 11.0   # values still reported


def test_raw_layer_volatile_series_uses_iqr():
    layer = compute_raw_layer(_count_spec(),
                              prior=[10.0, 100.0, 12.0, 90.0, 15.0, 80.0],
                              current=12.0, history_ok=True)
    assert layer.method == METHOD_IQR
    assert layer.score == 0.0                    # inside tukey fences


def test_raw_layer_missing_current_value():
    layer = compute_raw_layer(_count_spec(), prior=[10.0, 10.0, 10.0],
                              current=None, history_ok=True)
    assert layer.score is None and layer.value is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_raw_layer_zscore_method_and_shared_threshold():
    spec = _count_spec(outlier_method="zscore")
    layer = compute_raw_layer(spec, prior=[10.0, 12.0, 14.0, 16.0], current=20.0,
                              history_ok=True)
    assert layer.method == METHOD_ZSCORE
    # mean 13, stdev sqrt(20/3) => z ~ 2.7111; score = z / (2 * 2.5)
    assert layer.score == pytest.approx(2.7110552764 / 5.0)
    assert layer.level == "MODERATE"


# ── Layer 3: historical baseline (spec §5) ────────────────────────────────

def test_historical_layer_window_stats_and_pct_change_vs_mean():
    layer = compute_historical_layer(_count_spec(), prior=[10.0, 10.0, 10.0, 10.0],
                                     current=25.0, history_ok=True)
    assert layer.mean == 10.0 and layer.median == 10.0
    assert layer.std == 0.0
    assert layer.z_score is None                  # std 0 -> no z in the DB
    assert layer.change_percent == 150.0          # vs baseline mean
    assert layer.method == METHOD_PCT_CHANGE
    assert layer.score == 1.0
    assert layer.level == "VERY_HIGH"
    assert layer.history_ok is True


def test_historical_layer_mean_zero_change_is_none():
    layer = compute_historical_layer(
        _count_spec(outlier_method="zscore"), prior=[0.0, 0.0, 0.0], current=5.0,
        history_ok=True)
    assert layer.mean == 0.0
    assert layer.change_percent is None           # never divide by zero
    assert layer.z_score is None                  # std 0
    assert layer.score == 1.0                     # std 0 but value != mean


def test_historical_layer_rare_event_uses_mad_path():
    spec = _count_spec()                          # count, mean < 10 => MAD
    layer = compute_historical_layer(spec, prior=[0.0, 1.0, 0.0, 1.0, 0.0],
                                     current=5.0, history_ok=True)
    assert layer.method == METHOD_ROLLING_MEDIAN_MAD
    assert layer.median == 0.0
    assert layer.score == 1.0                     # MAD 0, value != median
    layer_zero = compute_historical_layer(spec, prior=[0.0, 1.0, 0.0, 1.0, 0.0],
                                          current=0.0, history_ok=True)
    assert layer_zero.score == 0.0                # MAD 0, value == median


def test_historical_layer_insufficient_history():
    layer = compute_historical_layer(_count_spec(), prior=[10.0, 11.0],
                                     current=12.0, history_ok=False)
    assert layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
    assert layer.history_ok is False
    assert layer.mean == 10.5                     # stats still reported


def test_historical_layer_disabled_config_keeps_stats_but_no_score():
    spec = _count_spec(historical_enabled=False)
    layer = compute_historical_layer(spec, prior=[10.0, 10.0, 10.0],
                                     current=40.0, history_ok=True)
    assert layer.score is None                    # layer suppressed by config
    assert layer.history_ok is True               # entry waives rule 1 for it
    assert layer.mean == 10.0
    assert layer.change_percent == 300.0


def test_historical_trend_deviation_blended_with_window_score():
    spec = _count_spec(outlier_method="trend_deviation")
    layer = compute_historical_layer(spec, prior=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
                                     current=40.0, history_ok=True)
    assert layer.method == METHOD_TREND_DEVIATION
    assert layer.trend_projected == pytest.approx(16.0)   # Theil-Sen slope 1, intercept 10
    assert layer.trend_residual_std == pytest.approx(0.0)
    assert layer.score == 1.0                     # max(window, trend); trend = 1


def test_historical_trend_deviation_falls_back_below_six_points():
    spec = _count_spec(outlier_method="trend_deviation")
    layer = compute_historical_layer(spec, prior=[10.0, 11.0, 12.0],
                                     current=12.5, history_ok=True)
    assert layer.method != METHOD_TREND_DEVIATION
    assert layer.trend_projected is None
    assert layer.score is not None and layer.score <= 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_raw_layer' from 'app.engine.anomaly.layered'` (Task 7 tests in the same file still pass).

- [ ] **Step 3: Append the helpers, dataclasses and layer functions to `layered.py`**

Append to `app/engine/anomaly/layered.py`:

```python
# ── Input helpers: month history -> per-layer series ───────────────────────

def prior_months(history: Dict[str, Dict[str, float]], current_month: str) -> List[str]:
    """Sorted months strictly before current_month."""
    return sorted(m for m in history if m < current_month)


def _sum_codes(values: Dict[str, float], codes: Sequence[str]) -> Optional[float]:
    total = 0.0
    for code in codes:
        v = values.get(code)
        if v is None:
            return None
        total += float(v)
    return total


def raw_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    """Raw analysis value for one month: summed numerator for rate rows,
    the indicator's own value for count rows."""
    if spec.is_rate:
        return _sum_codes(values, spec.numerator_codes)
    return values.get(spec.analysis_code)


def rate_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    num = _sum_codes(values, spec.numerator_codes)
    den = _sum_codes(values, spec.denominator_codes)
    if num is None or den is None or den == 0:
        return None
    return (num / den) * float(spec.rate_multiplier)


def denominator_analysis_value(spec: AnalysisSpec, values: Dict[str, float]) -> Optional[float]:
    if not spec.is_rate:
        return None
    return _sum_codes(values, spec.denominator_codes)


def _score_window(method: str, series: Sequence[float], current: float,
                  previous: Optional[float], threshold: float) -> Optional[float]:
    """Score `current` against the prior window with the chosen method."""
    if method == METHOD_PCT_CHANGE:
        pct = percent_change(current, previous if previous is not None else mean(series))
        return None if pct is None else score_from_pct_change(pct)
    if method == METHOD_ROLLING_MEDIAN_MAD:
        return score_from_mad(current, median(series), mad(series))
    if method == METHOD_IQR:
        q1, _q2, q3 = quartiles(series)
        return score_from_iqr(current, q1, q3)
    # zscore (and any unknown value) — one shared threshold knob
    center = mean(series)
    sigma = std(series)
    if sigma is None:
        return score_from_mad(current, center, mad(series))
    if sigma == 0:
        return 0.0 if current == center else 1.0
    return score_from_z((current - center) / sigma, threshold)


def _theil_sen(series: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """(slope, projected_next, residual_std) via Theil-Sen; None below
    MIN_TREND_POINTS. Residual std is 0 for a perfect line."""
    if len(series) < MIN_TREND_POINTS:
        return None
    x = list(range(len(series)))
    slope, intercept, _, _ = scipy_stats.theil_slopes(list(series), x)
    residuals = [y - (intercept + slope * i) for i, y in enumerate(series)]
    rstd = statistics.pstdev(residuals) if len(residuals) >= 2 else 0.0
    projected = intercept + slope * len(series)
    return float(slope), float(projected), float(rstd)


# ── Layer 1: raw value (spec §5) ──────────────────────────────────────────

@dataclass
class RawLayer:
    value: Optional[float]            # current raw analysis value
    previous: Optional[float]         # most recent non-None prior value
    change_percent: Optional[float]   # vs previous
    score: Optional[float]            # None = not applicable / not computable
    method: str

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_raw_layer(spec: AnalysisSpec, prior: Sequence[Optional[float]],
                      current: Optional[float], history_ok: bool,
                      threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> RawLayer:
    """Layer 1 on the raw analysis value (numerator for rate rows).

    Not computable (history_ok False or current None) => score None and
    method insufficient_history; values are still reported for the row.
    """
    values = [float(v) for v in prior if v is not None]
    previous = values[-1] if values else None
    change = percent_change(current, previous)
    if not history_ok or current is None:
        return RawLayer(value=current, previous=previous, change_percent=change,
                        score=None, method=METHOD_INSUFFICIENT_HISTORY)
    if not values:
        return RawLayer(value=current, previous=None, change_percent=None,
                        score=None, method=METHOD_INSUFFICIENT_HISTORY)
    method = select_method(spec.outlier_method, values, spec.indicator_type)
    score = _score_window(method, values, float(current), previous, threshold)
    return RawLayer(value=current, previous=previous, change_percent=change,
                    score=score, method=method)


# ── Layer 3: historical baseline (spec §5) ────────────────────────────────

@dataclass
class HistoricalLayer:
    history_ok: bool
    series: List[float]               # baseline series (rate series for rate rows)
    current: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    std: Optional[float]
    z_score: Optional[float]          # None when std is None/0 (never inf)
    change_percent: Optional[float]   # current vs baseline mean
    score: Optional[float]
    method: str
    trend_slope: Optional[float] = None
    trend_projected: Optional[float] = None
    trend_residual_std: Optional[float] = None

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_historical_layer(spec: AnalysisSpec, prior: Sequence[float],
                             current: Optional[float], history_ok: bool,
                             threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> HistoricalLayer:
    """Layer 3 over the baseline series: window stats + method score, with
    optional Theil-Sen trend_deviation blending (spec §5 Layer 3)."""
    series = [float(v) for v in prior if v is not None]
    win_mean = statistics.fmean(series) if series else None
    win_median = statistics.median(series) if series else None
    win_std = std(series)
    z: Optional[float] = None
    if win_std not in (None, 0) and current is not None and win_mean is not None:
        z = (float(current) - win_mean) / win_std
    change = percent_change(current, win_mean)

    if not spec.historical_enabled:
        return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                               mean=win_mean, median=win_median, std=win_std,
                               z_score=z, change_percent=change, score=None,
                               method=METHOD_INSUFFICIENT_HISTORY)
    if not history_ok or current is None or not series:
        return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                               mean=win_mean, median=win_median, std=win_std,
                               z_score=z, change_percent=change, score=None,
                               method=METHOD_INSUFFICIENT_HISTORY)

    window_method = select_method(spec.outlier_method, series, spec.indicator_type)
    window_score = _score_window(window_method, series, float(current),
                                 series[-1], threshold)
    method, score = window_method, window_score

    if spec.outlier_method == METHOD_TREND_DEVIATION:
        trend = _theil_sen(series)
        if trend is not None:
            _slope, projected, rstd = trend
            trend_score = score_from_trend(float(current), projected, rstd)
            score = max(window_score if window_score is not None else 0.0, trend_score)
            return HistoricalLayer(
                history_ok=history_ok, series=series, current=current,
                mean=win_mean, median=win_median, std=win_std, z_score=z,
                change_percent=change, score=score,
                method=METHOD_TREND_DEVIATION,
                trend_slope=_slope, trend_projected=projected,
                trend_residual_std=rstd)
        # < MIN_TREND_POINTS: window stats only (documented fallback)
        window_method = select_method(METHOD_AUTO, series, spec.indicator_type)
        method = window_method
        score = _score_window(window_method, series, float(current),
                              series[-1], threshold)

    return HistoricalLayer(history_ok=history_ok, series=series, current=current,
                           mean=win_mean, median=win_median, std=win_std,
                           z_score=z, change_percent=change, score=score,
                           method=method)
```

Also add to the module imports at the top of `layered.py`: `from typing import Dict, List, Optional, Sequence, Tuple` (extend the existing `typing` import) and after the stdlib imports:

```python
from scipy import stats as scipy_stats
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS (Task 7 + Task 8 tests).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/layered.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/layered.py tests/test_layered_engine.py
git commit -m "feat(layered): raw-value and historical-baseline layers with trend blending"
```

---

### Task 9: Layers 2 + 4 — rate and volume/denominator

**Files:**
- Modify: `app/engine/anomaly/layered.py` (append `RateLayer`/`VolumeLayer`, their compute functions, and the small-denominator guard predicate)
- Modify: `tests/test_layered_engine.py` (extend import block + append tests)

**Interfaces:**
- Consumes: Task 7 core + Task 8 helpers (`percent_change`, `score_from_pct_change`, `select_method`, `_score_window`).
- Produces (Tasks 11-13 depend on these):
  - `RateLayer(rate, score, method)` + `level` property.
  - `compute_rate_layer(spec, prior_rates, current_rate, history_ok, threshold=PEER_Z_THRESHOLD_DEFAULT) -> RateLayer`
  - `VolumeLayer(denominator, previous, change_percent, score, den_ok)` + `level` property.
  - `compute_volume_layer(spec, prior_denominators, current_denominator) -> Optional[VolumeLayer]`
  - `is_small_denominator(spec, denominator) -> bool` — spec §5 guard predicate (False when `minimum_denominator is None`).
- Behavioral contract (tests pin every clause):
  - Count rows (`not spec.is_rate`): rate layer `rate=None, score=None, method=insufficient_history`; volume layer returns **`None`** — the entry records `rate=NULL, volume_anomaly_score=NULL` and sets `den_ok=True` (no denominator concept, nothing wrong).
  - `RateLayer.rate` is always the observed rate (stored even when the score is not computable — rule 1 rows still show their rate); only `score`/`method` gate on `history_ok`.
  - Not computable rate (`history_ok=False` or `current_rate=None`, i.e. missing/zero denominator) → `score=None`, `method=insufficient_history`.
  - `den_ok = denominator is not None and denominator > 0` — the classification input distinguishing "missing denominator → not computable" from a real value (spec scenarios 9/10: never NORMAL, never an outlier).
  - Volume score = `score_from_pct_change` of the denominator change vs the most recent prior month with a denominator (gap-tolerant); no prior denominator → `score=None`, `den_ok=True` (nothing to compare, denominator itself fine).
  - `is_small_denominator`: `minimum_denominator is None` → False (guard dormant); `denominator >= minimum_denominator` → False (equal passes); `denominator is None` → False (not-computable path already handled by `den_ok`).

- [ ] **Step 1: Write the failing tests**

Extend the import block at the top of `tests/test_layered_engine.py` with:

```python
from app.engine.anomaly.layered import (
    RateLayer,
    VolumeLayer,
    compute_rate_layer,
    compute_volume_layer,
    is_small_denominator,
)
```

Append the tests:

```python
# ── Layer 2: rate (spec §5) ───────────────────────────────────────────────

def _rate_spec(**kw):
    return AnalysisSpec(analysis_code="rate_cs", name="C-section rate",
                        indicator_type="percentage",
                        numerator_codes=("5",), denominator_codes=("2",),
                        rate_multiplier=100.0, unit="%", **kw)


def test_rate_layer_null_for_count_rows():
    layer = compute_rate_layer(_count_spec(), prior_rates=[10.0, 11.0],
                               current_rate=12.0, history_ok=True)
    assert layer.rate is None and layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_rate_layer_normal_series_is_none_band():
    layer = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7, 26.7, 26.7],
                               current_rate=26.7, history_ok=True)
    assert layer.method == METHOD_PCT_CHANGE       # CV = 0 < 0.5
    assert layer.score == 0.0
    assert layer.level == "NONE"
    assert layer.rate == 26.7


def test_rate_layer_jump_is_very_high():
    layer = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7, 26.7, 26.7],
                               current_rate=375.0, history_ok=True)
    assert layer.score == 1.0                      # +1300% capped at 1
    assert layer.level == "VERY_HIGH"


def test_rate_layer_still_reports_rate_when_history_insufficient():
    gated = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7],
                               current_rate=40.0, history_ok=False)
    assert gated.rate == 40.0                      # value stored for the row
    assert gated.score is None
    assert gated.method == METHOD_INSUFFICIENT_HISTORY
    missing = compute_rate_layer(_rate_spec(), prior_rates=[26.7, 26.7],
                                 current_rate=None, history_ok=True)
    assert missing.rate is None and missing.score is None
    assert missing.method == METHOD_INSUFFICIENT_HISTORY


def test_rate_layer_respects_configured_zscore_method():
    layer = compute_rate_layer(_rate_spec(outlier_method="zscore"),
                               prior_rates=[20.0, 22.0, 24.0, 26.0],
                               current_rate=30.0, history_ok=True)
    assert layer.method == METHOD_ZSCORE
    # mean 23, stdev sqrt(20/3) ~= 2.5819889 => z ~= 2.7110553; score = z / (2 * 2.5)
    assert layer.score == pytest.approx(2.7110552764 / 5.0)


# ── Layer 4: volume / denominator (spec §5) ───────────────────────────────

def test_volume_layer_is_none_for_count_rows():
    assert compute_volume_layer(_count_spec(), prior=[900.0], current=1000.0) is None


def test_volume_layer_missing_and_zero_denominator_are_not_ok():
    missing = compute_volume_layer(_rate_spec(), prior=[900.0], current=None)
    assert missing.den_ok is False and missing.score is None
    assert missing.denominator is None
    zero = compute_volume_layer(_rate_spec(), prior=[900.0], current=0.0)
    assert zero.den_ok is False and zero.score is None
    assert zero.denominator == 0.0                 # actual value reported


def test_volume_layer_stable_denominator_is_none_band():
    layer = compute_volume_layer(_rate_spec(), prior=[900.0], current=1000.0)
    assert layer.den_ok is True
    assert layer.previous == 900.0
    assert layer.change_percent == pytest.approx(11.1111, rel=1e-4)
    assert layer.score == pytest.approx(0.1111, rel=1e-4)
    assert layer.level == "NONE"


def test_volume_layer_exploding_denominator_is_very_high():
    layer = compute_volume_layer(_rate_spec(), prior=[100.0], current=2000.0)
    assert layer.change_percent == 1900.0
    assert layer.score == 1.0                      # +1900% capped at 1
    assert layer.level == "VERY_HIGH"


def test_volume_layer_without_previous_denominator():
    layer = compute_volume_layer(_rate_spec(), prior=[], current=900.0)
    assert layer.den_ok is True                    # denominator itself is fine
    assert layer.previous is None
    assert layer.change_percent is None and layer.score is None


def test_small_denominator_guard_predicate():
    strict = _rate_spec(minimum_denominator=10)
    assert is_small_denominator(strict, 5) is True
    assert is_small_denominator(strict, 10) is False   # equal passes the guard
    assert is_small_denominator(strict, 900) is False
    assert is_small_denominator(strict, None) is False
    dormant = _rate_spec()                         # minimum_denominator None
    assert is_small_denominator(dormant, 0) is False   # guard dormant
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'RateLayer' from 'app.engine.anomaly.layered'`.

- [ ] **Step 3: Append the layer implementations to `layered.py`**

Append to `app/engine/anomaly/layered.py`:

```python
# ── Layer 2: rate (spec §5) ───────────────────────────────────────────────

@dataclass
class RateLayer:
    rate: Optional[float]            # observed rate for the month (always stored)
    score: Optional[float]           # None = not applicable / not computable
    method: str

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_rate_layer(spec: AnalysisSpec, prior_rates: Sequence[Optional[float]],
                       current_rate: Optional[float], history_ok: bool,
                       threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> RateLayer:
    """Layer 2: score the current rate against the hospital's own historical
    rates with the same method-selection logic as Layer 1. NULL layer for
    count rows; missing rate / insufficient history => score None."""
    if not spec.is_rate:
        return RateLayer(rate=None, score=None, method=METHOD_INSUFFICIENT_HISTORY)
    series = [float(v) for v in prior_rates if v is not None]
    if not history_ok or current_rate is None or not series:
        return RateLayer(rate=current_rate, score=None,
                         method=METHOD_INSUFFICIENT_HISTORY)
    method = select_method(spec.outlier_method, series, spec.indicator_type)
    score = _score_window(method, series, float(current_rate), series[-1], threshold)
    return RateLayer(rate=current_rate, score=score, method=method)


# ── Layer 4: volume / denominator (spec §5) ───────────────────────────────

@dataclass
class VolumeLayer:
    denominator: Optional[float]
    previous: Optional[float]       # most recent prior month with a denominator
    change_percent: Optional[float]
    score: Optional[float]
    den_ok: bool                    # denominator present and > 0

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_volume_layer(spec: AnalysisSpec,
                         prior_denominators: Sequence[Optional[float]],
                         current_denominator: Optional[float]) -> Optional[VolumeLayer]:
    """Layer 4: severity of the denominator shift. Returns None for count
    rows (no denominator concept — the entry records NULL and den_ok=True).
    Missing/zero denominator => den_ok False, score None: rate-dependent
    layers are not computable (never normal, never an outlier)."""
    if not spec.is_rate:
        return None
    series = [float(v) for v in prior_denominators if v is not None]
    previous = series[-1] if series else None
    if current_denominator is None:
        return VolumeLayer(denominator=None, previous=previous,
                           change_percent=None, score=None, den_ok=False)
    if float(current_denominator) <= 0:
        return VolumeLayer(denominator=float(current_denominator), previous=previous,
                           change_percent=None, score=None, den_ok=False)
    change = percent_change(float(current_denominator), previous)
    score = score_from_pct_change(change) if change is not None else None
    return VolumeLayer(denominator=float(current_denominator), previous=previous,
                       change_percent=change, score=score, den_ok=True)


def is_small_denominator(spec: AnalysisSpec, denominator: Optional[float]) -> bool:
    """Spec §5 small-denominator guard predicate. Dormant (False) until a
    minimum_denominator is configured on the spec."""
    if denominator is None or spec.minimum_denominator is None:
        return False
    return float(denominator) < float(spec.minimum_denominator)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS (Tasks 7-9 tests).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/layered.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/layered.py tests/test_layered_engine.py
git commit -m "feat(layered): rate and volume/denominator layers with small-denominator guard"
```

---

### Task 10: Layer 5 — peer comparison

**Files:**
- Modify: `app/engine/anomaly/layered.py` (append `PeerLayer` + `compute_peer_layer`)
- Modify: `tests/test_layered_engine.py` (extend import block + append tests)

**Interfaces:**
- Consumes: Task 7 core (`score_from_z`, `level_for_score`, `METHOD_PEER_ZSCORE`, `PEER_Z_THRESHOLD_DEFAULT`).
- Produces (Tasks 11-13 depend on these):
  - `PeerLayer(peer_mean, peer_count, score, method, tier)` + `level` property.
  - `compute_peer_layer(spec, self_id, current_value, peer_tiers, threshold=PEER_Z_THRESHOLD_DEFAULT) -> PeerLayer`
  - `peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]]` — ordered `(tier_name, {hospital_id: value})` pairs, **first tier with ≥ 2 members other than this hospital wins** (type → ownership → governorate → all; the orchestrator in Task 12 builds the order from the hospital records already fetched for `detect_anomalies`). Peer statistics are computed over the *other* hospitals' values only (`self_id` excluded); `statistics.stdev` gives the spec's `ddof=1`.
  - Peer value = rate for rate rows, raw value for count rows — the entry point passes the right value in.
- Behavioral contract (tests pin every clause):
  - Layer runs **after** the history layers (spec §5 Layer 5) — ordering is enforced by the entry point in Task 12, documented here.
  - `peer_comparison_enabled=False` → unavailable (`score=None, peer_count=0, peer_mean=None, method=insufficient_history`).
  - No tier with ≥2 others in *every* tier → same unavailable shape (spec: "never force an outlier from no peers"); `tier=None`.
  - Peer spread of 0 (`stdev == 0`): score `0.0` if current equals peer mean, else `1.0` (same zero-MAD convention as the other layers — no division by zero, never inf).
  - `current_value=None` → unavailable shape (score None; nothing computed).
  - `tier` is kept on the result for interpretation/tests but is not persisted (no DB column for it).

- [ ] **Step 1: Write the failing tests**

Extend the import block at the top of `tests/test_layered_engine.py` with:

```python
from app.engine.anomaly.layered import (
    METHOD_PEER_ZSCORE,
    PeerLayer,
    compute_peer_layer,
)
```

Append the tests:

```python
# ── Layer 5: peer comparison (spec §5) ────────────────────────────────────

def test_peer_layer_excludes_self_and_scores_z():
    spec = _count_spec()
    tiers = [("type:general", {1: 8.0, 2: 12.0, 3: 16.0})]     # 3 = self
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.method == METHOD_PEER_ZSCORE
    assert layer.tier == "type:general"
    assert layer.peer_count == 2
    # others [8, 12]: mean 10, stdev sqrt(8) ~= 2.8284271, z = 6/2.8284271 ~= 2.1213203
    # score = z / (2 * 2.5) ~= 0.4242641 -> LOW
    assert layer.score == pytest.approx(0.4242640687)
    assert layer.level == "LOW"
    assert layer.peer_mean == 10.0


def test_peer_layer_first_sufficient_tier_wins():
    spec = _count_spec()
    tiers = [
        ("type:general", {1: 10.0, 2: 10.0, 3: 16.0}),        # 2 others -> wins
        ("all", {1: 100.0, 2: 100.0, 3: 16.0}),                # never consulted
    ]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.tier == "type:general"
    assert layer.peer_mean == 10.0
    assert layer.peer_count == 2
    assert layer.score == 1.0                   # zero spread, value != mean
    assert layer.level == "VERY_HIGH"


def test_peer_layer_skips_thin_tiers():
    spec = _count_spec()
    tiers = [
        ("type:general", {3: 16.0}),                               # self only
        ("ownership:ministry", {1: 9.0, 3: 16.0}),                 # 1 other
        ("governorate:cairo", {1: 8.0, 2: 12.0, 3: 16.0}),         # 2 others
    ]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.tier == "governorate:cairo"
    assert layer.peer_count == 2
    assert layer.score == pytest.approx(0.4242640687)


def test_peer_layer_no_sufficient_tier_is_null():
    spec = _count_spec()
    tiers = [("all", {1: 10.0, 3: 16.0})]                          # 1 other only
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.score is None and layer.level is None
    assert layer.peer_mean is None and layer.peer_count == 0
    assert layer.tier is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_peer_layer_disabled_by_config():
    spec = _count_spec(peer_comparison_enabled=False)
    tiers = [("all", {1: 8.0, 2: 12.0, 3: 16.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=16.0, peer_tiers=tiers)
    assert layer.score is None and layer.peer_count == 0
    assert layer.method == METHOD_INSUFFICIENT_HISTORY


def test_peer_layer_zero_spread_at_mean_is_zero_score():
    spec = _count_spec()
    tiers = [("all", {1: 10.0, 2: 10.0, 3: 10.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=10.0, peer_tiers=tiers)
    assert layer.score == 0.0
    assert layer.level == "NONE"


def test_peer_layer_missing_current_value():
    spec = _count_spec()
    tiers = [("all", {1: 8.0, 2: 12.0})]
    layer = compute_peer_layer(spec, self_id=3, current_value=None, peer_tiers=tiers)
    assert layer.score is None
    assert layer.method == METHOD_INSUFFICIENT_HISTORY
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'PeerLayer' from 'app.engine.anomaly.layered'`.

- [ ] **Step 3: Append the peer layer to `layered.py`**

Append to `app/engine/anomaly/layered.py`:

```python
# ── Layer 5: peer comparison (spec §5) ────────────────────────────────────

@dataclass
class PeerLayer:
    peer_mean: Optional[float]
    peer_count: int
    score: Optional[float]           # None = unavailable (no peers / disabled)
    method: str
    tier: Optional[str] = None       # tier that supplied the stats (not persisted)

    @property
    def level(self) -> Optional[str]:
        return level_for_score(self.score)


def compute_peer_layer(spec: AnalysisSpec, self_id: Any,
                       current_value: Optional[float],
                       peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]],
                       threshold: float = PEER_Z_THRESHOLD_DEFAULT) -> PeerLayer:
    """Layer 5: z-score of this hospital's value against OTHER active
    hospitals, first tier with >= 2 other members wins (type -> ownership ->
    governorate -> all). Never forces an outlier from no peers."""
    if not spec.peer_comparison_enabled or current_value is None:
        return PeerLayer(peer_mean=None, peer_count=0, score=None,
                         method=METHOD_INSUFFICIENT_HISTORY, tier=None)
    for tier_name, tier_map in peer_tiers:
        others = [float(v) for hid, v in tier_map.items()
                  if hid != self_id and v is not None]
        if len(others) >= 2:
            peer_mean = statistics.fmean(others)
            peer_std = statistics.stdev(others)      # ddof=1 per spec
            if peer_std == 0:
                score = 0.0 if float(current_value) == peer_mean else 1.0
            else:
                score = score_from_z((float(current_value) - peer_mean) / peer_std,
                                     threshold)
            return PeerLayer(peer_mean=peer_mean, peer_count=len(others),
                             score=score, method=METHOD_PEER_ZSCORE, tier=tier_name)
    return PeerLayer(peer_mean=None, peer_count=0, score=None,
                     method=METHOD_INSUFFICIENT_HISTORY, tier=None)
```

Also add `Any` to the `typing` import at the top of `layered.py` (`Dict, List, Optional, Sequence, Tuple` from Task 8).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS (Tasks 7-10 tests).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/layered.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/layered.py tests/test_layered_engine.py
git commit -m "feat(layered): peer-comparison layer with tier fallback"
```

---

### Task 11: Classification + interpretation

**Files:**
- Create: `app/engine/anomaly/classify.py`
- Modify: `tests/test_layered_engine.py` (extend import block + append tests)

**Interfaces:**
- Consumes: Task 7-10 layer outputs (`level_for_score`, `LEVEL_RANK`, `is_small_denominator`, method constants).
- Produces (Tasks 12-13 depend on these):
  - Type constants: `TYPE_NORMAL`, `TYPE_RAW_VALUE_ANOMALY`, `TYPE_RATE_ANOMALY`, `TYPE_HISTORICAL_ANOMALY`, `TYPE_VOLUME_DRIVEN_ANOMALY`, `TYPE_PEER_ANOMALY`, `TYPE_POSSIBLE_DATA_ENTRY_ERROR`, `TYPE_CLINICAL_INVESTIGATION_REQUIRED` (exact DB enum strings from spec §3.1).
  - `InterpretationNumbers` frozen dataclass — the actual numbers fed to the text builder (`raw_value, previous_value, raw_change_percent, rate, denominator, denominator_change_percent, historical_mean, historical_change_percent, peer_mean, peer_count`).
  - `Classification` frozen dataclass: `outlier_type, outlier_level, investigation_required, investigation_route, rule_number, method, interpretation`.
  - `classify_layered(spec, *, raw_score, rate_score, hist_score, volume_score, peer_score, den_ok, history_ok, change_percent=None, denominator=None, raw_method=..., rate_method=..., hist_method=..., numbers=None) -> Classification`
  - `build_interpretation(spec, outlier_type, rule_number, *, den_ok, numbers) -> str` — pure, content-asserted by tests.
- Design notes (spec §6):
  - **Rule table:** the 10 rules in exact spec order, first match wins. Score comparisons via helpers: `_at_least(score, level)` = score present and its band ≥ level; `_at_most(score, level)` = **score absent or** band ≤ level (not-computable counts as "not above", never as evidence). `_at_least_any(...)` = any of several scores ≥ level.
  - **Rule 2's magnitude guard** needs the actual rate change, which the spec's rule table references but its input list omits — `change_percent` is added as an explicit input (= `HistoricalLayer.change_percent`, i.e. rate vs baseline mean for rate rows). `RULE2_MIN_CHANGE_PERCENT = 300.0` (≥ 4× baseline). `den_ok` also gates rules 2/4/9 explicitly (spec §5 Layer 4: rate-dependent rules need a usable denominator).
  - **Level:** `outlier_level` = max band across all non-None layer scores (rule 1 forces `NONE`), then the small-denominator guard caps at `LOW` **only for rate-based types** (`RATE_ANOMALY`, `VOLUME_DRIVEN_ANOMALY`, `POSSIBLE_DATA_ENTRY_ERROR`, `CLINICAL_INVESTIGATION_REQUIRED`).
  - **Method** by rule: 1 → `insufficient_history`; 2/4/9 → rate method; 5 → hist method; 6/7 → `peer_zscore`; 3/8/10 → raw method.
  - **Routes:** 2 → `data_quality`; 4 → `clinical`; 3,5,6,7,8,9 → `contextual` (spec lists contextual for 5-9 and omits rule 3; volume-driven is a contextual review, not an investigation — `investigation_required=False` per spec); 1,10 → `none`. `investigation_required=True` for rules 2,4,6,7 only.
  - **Interpretation:** English, composed from actual numbers (spec §6 example style). Lead sentence per type/rule; numeric tails appended only when present: `{name} {raw} vs {prev} ({change:+}% vs previous month)`, `+{h}% above/below baseline mean {mean}`, `rate {rate:.1f}{unit}`, `denominator {den} ({change:+}% vs previous)`, `peer average {mean} across {n} hospitals`; plus disclosure tails: `denominator missing or zero - rate layers not computable` when `den_ok=False`, and `small denominator ({den} < {min}) - confidence lowered, level capped at LOW` when the guard fires. i18n is **not** applied to this free text (spec: interpretation text English; chrome keys get i18n in Task 17).

- [ ] **Step 1: Write the failing tests**

Extend the import block at the top of `tests/test_layered_engine.py` with:

```python
from app.engine.anomaly.classify import (
    InterpretationNumbers,
    TYPE_CLINICAL_INVESTIGATION_REQUIRED,
    TYPE_HISTORICAL_ANOMALY,
    TYPE_NORMAL,
    TYPE_PEER_ANOMALY,
    TYPE_POSSIBLE_DATA_ENTRY_ERROR,
    TYPE_RATE_ANOMALY,
    TYPE_RAW_VALUE_ANOMALY,
    TYPE_VOLUME_DRIVEN_ANOMALY,
    build_interpretation,
    classify_layered,
)
```

Append the tests:

```python
# ── Classification (spec §6) ───────────────────────────────────────────────

def _classify(**kw):
    defaults = dict(spec=_rate_spec(), raw_score=None, rate_score=None,
                    hist_score=None, volume_score=None, peer_score=None,
                    den_ok=True, history_ok=True)
    defaults.update(kw)
    return classify_layered(**defaults)


def test_classification_rule1_insufficient_history_is_first_match():
    c = _classify(history_ok=False, raw_score=0.95, hist_score=0.95)
    assert c.rule_number == 1
    assert c.outlier_type == TYPE_NORMAL
    assert c.outlier_level == "NONE"
    assert c.method == METHOD_INSUFFICIENT_HISTORY
    assert c.investigation_required is False
    assert c.investigation_route == "none"
    assert "Not enough history" in c.interpretation
    assert "3 prior months" in c.interpretation


def test_classification_rule2_possible_data_entry_error():
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=1300.0,
                  rate_method="pct_change")
    assert c.rule_number == 2
    assert c.outlier_type == TYPE_POSSIBLE_DATA_ENTRY_ERROR
    assert c.investigation_required is True
    assert c.investigation_route == "data_quality"
    assert c.outlier_level == "VERY_HIGH"
    assert c.method == "pct_change"
    assert "data-entry error" in c.interpretation


def test_classification_rule2_magnitude_guard_boundary():
    base = dict(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                volume_score=0.10)
    assert _classify(**base, change_percent=300.0).rule_number == 2
    assert _classify(**base, change_percent=299.9).rule_number == 4
    assert _classify(**base, change_percent=None).rule_number == 4


def test_classification_rule4_clinical_when_guard_fails():
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=125.0)
    assert c.rule_number == 4
    assert c.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert c.investigation_required is True
    assert c.investigation_route == "clinical"


def test_classification_rule3_volume_driven():
    c = _classify(raw_score=0.95, rate_score=0.40, hist_score=0.30,
                  volume_score=0.95)
    assert c.rule_number == 3
    assert c.outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY
    assert c.investigation_required is False    # spec: only rules 2/4/6/7
    assert c.investigation_route == "contextual"


def test_classification_rule5_historical_anomaly():
    c = _classify(raw_score=0.30, rate_score=0.30, hist_score=0.85,
                  volume_score=0.10, peer_score=0.20, hist_method="iqr")
    assert c.rule_number == 5
    assert c.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert c.investigation_route == "contextual"
    assert c.method == "iqr"


def test_classification_rule6_peer_anomaly_never_data_error():
    c = _classify(raw_score=0.20, hist_score=0.10, peer_score=0.95)
    assert c.rule_number == 6
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.investigation_required is True
    assert c.method == METHOD_PEER_ZSCORE
    assert "case mix" in c.interpretation
    assert "data-entry error" not in c.interpretation   # never a data-error claim


def test_classification_rule7_peer_plus_history_combined():
    c = _classify(raw_score=0.20, hist_score=0.60, peer_score=0.95)
    assert c.rule_number == 7
    assert c.outlier_type == TYPE_PEER_ANOMALY
    assert c.investigation_required is True
    assert "and from its own recent history" in c.interpretation


def test_classification_rule8_raw_value_anomaly():
    c = _classify(raw_score=0.55, hist_score=0.30, peer_score=0.20)
    assert c.rule_number == 8
    assert c.outlier_type == TYPE_RAW_VALUE_ANOMALY
    assert c.outlier_level == "MODERATE"
    assert c.investigation_route == "contextual"


def test_classification_rule9_rate_anomaly():
    c = _classify(rate_score=0.55, raw_score=0.30, hist_score=0.30,
                  volume_score=0.10)
    assert c.rule_number == 9
    assert c.outlier_type == TYPE_RATE_ANOMALY
    assert c.outlier_level == "MODERATE"


def test_classification_rule10_normal_when_nothing_exceeds():
    c = _classify(raw_score=0.10, rate_score=0.10, hist_score=0.10,
                  volume_score=0.05, peer_score=0.10)
    assert c.rule_number == 10
    assert c.outlier_type == TYPE_NORMAL
    assert c.outlier_level == "NONE"
    assert c.investigation_required is False
    assert c.investigation_route == "none"
    assert "No layer exceeded its threshold" in c.interpretation


def test_classification_count_row_volume_rule_never_fires():
    c = _classify(spec=_count_spec(), raw_score=0.95, hist_score=0.40,
                  peer_score=0.30)              # volume_score stays None
    assert c.rule_number == 8                   # rule 3 needs volume >= HIGH
    assert c.outlier_type == TYPE_RAW_VALUE_ANOMALY
    assert c.outlier_level == "VERY_HIGH"


def test_classification_small_denominator_caps_rate_based_types():
    spec = _rate_spec(minimum_denominator=10)
    c = _classify(spec=spec, raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=125.0, denominator=5)
    assert c.rule_number == 4
    assert c.outlier_level == "LOW"             # capped from VERY_HIGH
    assert "small denominator (5 < 10)" in c.interpretation
    assert "level capped at LOW" in c.interpretation


def test_classification_non_rate_type_not_capped_by_small_denominator():
    spec = _rate_spec(minimum_denominator=10)
    c = _classify(spec=spec, raw_score=0.20, rate_score=0.10, hist_score=0.30,
                  volume_score=0.10, peer_score=0.95, denominator=5)
    assert c.rule_number == 6                   # PEER_ANOMALY: not rate-based
    assert c.outlier_level == "VERY_HIGH"        # cap does not apply


def test_classification_missing_denominator_disclosed_not_computable():
    c = _classify(den_ok=False, raw_score=0.30, denominator=None)
    assert c.rule_number == 10
    assert c.outlier_type == TYPE_NORMAL         # computable layers are low
    assert "denominator missing or zero" in c.interpretation
    assert "not computable" in c.interpretation


def test_interpretation_composed_from_actual_numbers():
    numbers = InterpretationNumbers(
        raw_value=25.0, previous_value=10.0, raw_change_percent=150.0,
        rate=375.0, denominator=900.0, denominator_change_percent=11.0,
        historical_mean=26.7, historical_change_percent=1300.0,
        peer_mean=12.1, peer_count=18)
    c = _classify(raw_score=0.95, rate_score=0.95, hist_score=0.95,
                  volume_score=0.10, change_percent=1300.0, numbers=numbers)
    text = c.interpretation
    assert "+1300% above baseline mean 26.7" in text
    assert "rate 375.0%" in text
    assert "peer average 12.1 across 18 hospitals" in text
    assert "C-section rate 25 vs 10 (+150% vs previous month)" in text
    assert "denominator 900 (+11% vs previous)" in text


def test_build_interpretation_below_baseline_direction():
    numbers = InterpretationNumbers(historical_mean=50.0,
                                    historical_change_percent=-40.0)
    text = build_interpretation(_rate_spec(), TYPE_NORMAL, 10, den_ok=True,
                                numbers=numbers)
    assert "+40% below baseline mean 50" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.anomaly.classify'`.

- [ ] **Step 3: Create `app/engine/anomaly/classify.py`**

```python
"""Layered classification: deterministic priority rule table over layer
outputs (spec section 6).

Detection -> Interpretation -> Investigation only. Never modifies the Data
Quality Score. First rule match wins; not-computable layers (None scores)
never count as evidence for a >= comparison, and always count as 'not above'
for <= comparisons.
"""
from dataclasses import dataclass
from typing import Optional

from app.engine.anomaly.layered import (
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_NONE,
    LEVEL_RANK,
    METHOD_INSUFFICIENT_HISTORY,
    METHOD_PEER_ZSCORE,
    AnalysisSpec,
    is_small_denominator,
    level_for_score,
)

# ── Classification enum (spec section 3.1) ────────────────────────────────
TYPE_NORMAL = "NORMAL"
TYPE_RAW_VALUE_ANOMALY = "RAW_VALUE_ANOMALY"
TYPE_RATE_ANOMALY = "RATE_ANOMALY"
TYPE_HISTORICAL_ANOMALY = "HISTORICAL_ANOMALY"
TYPE_VOLUME_DRIVEN_ANOMALY = "VOLUME_DRIVEN_ANOMALY"
TYPE_PEER_ANOMALY = "PEER_ANOMALY"
TYPE_POSSIBLE_DATA_ENTRY_ERROR = "POSSIBLE_DATA_ENTRY_ERROR"
TYPE_CLINICAL_INVESTIGATION_REQUIRED = "CLINICAL_INVESTIGATION_REQUIRED"

_RATE_BASED_TYPES = frozenset({
    TYPE_RATE_ANOMALY,
    TYPE_VOLUME_DRIVEN_ANOMALY,
    TYPE_POSSIBLE_DATA_ENTRY_ERROR,
    TYPE_CLINICAL_INVESTIGATION_REQUIRED,
})

# Rule 2 magnitude guard: rate change >= +300% vs baseline (>= 4x baseline)
RULE2_MIN_CHANGE_PERCENT = 300.0

_INVESTIGATION_RULES = frozenset({2, 4, 6, 7})
_ROUTE_BY_RULE = {
    1: "none", 2: "data_quality", 3: "contextual", 4: "clinical",
    5: "contextual", 6: "contextual", 7: "contextual", 8: "contextual",
    9: "contextual", 10: "none",
}


@dataclass(frozen=True)
class InterpretationNumbers:
    """Actual numbers the text builder may cite (spec section 6)."""
    raw_value: Optional[float] = None
    previous_value: Optional[float] = None
    raw_change_percent: Optional[float] = None
    rate: Optional[float] = None
    denominator: Optional[float] = None
    denominator_change_percent: Optional[float] = None
    historical_mean: Optional[float] = None
    historical_change_percent: Optional[float] = None
    peer_mean: Optional[float] = None
    peer_count: int = 0


@dataclass(frozen=True)
class Classification:
    outlier_type: str
    outlier_level: str
    investigation_required: bool
    investigation_route: str
    rule_number: int
    method: str
    interpretation: str


def _at_least(score: Optional[float], min_level: str) -> bool:
    if score is None:
        return False
    return LEVEL_RANK[level_for_score(score)] >= LEVEL_RANK[min_level]


def _at_most(score: Optional[float], max_level: str) -> bool:
    if score is None:
        return True                      # not computable => not above
    return LEVEL_RANK[level_for_score(score)] <= LEVEL_RANK[max_level]


def _at_least_any(scores: tuple, min_level: str) -> bool:
    return any(_at_least(s, min_level) for s in scores)


def _max_level(*scores: Optional[float]) -> str:
    best = LEVEL_NONE
    for s in scores:
        if s is None:
            continue
        lvl = level_for_score(s)
        if LEVEL_RANK[lvl] > LEVEL_RANK[best]:
            best = lvl
    return best


def _method_for_rule(rule: int, raw_method: str, rate_method: str,
                     hist_method: str) -> str:
    if rule == 1:
        return METHOD_INSUFFICIENT_HISTORY
    if rule in (2, 4, 9):
        return rate_method
    if rule == 5:
        return hist_method
    if rule in (6, 7):
        return METHOD_PEER_ZSCORE
    return raw_method                      # rules 3, 8, 10


def build_interpretation(spec: AnalysisSpec, outlier_type: str,
                         rule_number: int, *, den_ok: bool,
                         numbers: InterpretationNumbers) -> str:
    """Compose the human-readable explanation from actual numbers (English;
    chrome i18n happens in the frontend, not here)."""
    if rule_number == 1:
        lead = (f"Not enough history: needs at least "
                f"{spec.minimum_history_period} prior months")
    elif rule_number == 10:
        lead = "No layer exceeded its threshold"
    elif outlier_type == TYPE_POSSIBLE_DATA_ENTRY_ERROR:
        lead = ("All layers spike together while the denominator is stable "
                "- consistent with a data-entry error; verify source values "
                "before acting")
    elif outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED:
        lead = ("Rate and history are both high with a stable denominator "
                "- consistent with a genuine clinical change; investigate "
                "clinically")
    elif outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY:
        lead = ("The jump tracks a denominator (activity-volume) shift "
                "- volume-driven, not a per-case change")
    elif outlier_type == TYPE_HISTORICAL_ANOMALY:
        lead = "Deviation from this hospital's own recent baseline"
    elif outlier_type == TYPE_PEER_ANOMALY and rule_number == 7:
        lead = ("Differs from peers and from its own recent history; both "
                "deviations are stated below")
    elif outlier_type == TYPE_PEER_ANOMALY:
        lead = ("Consistently differs from peers; review case mix, referral "
                "pattern, and indicator definition")
    elif outlier_type == TYPE_RATE_ANOMALY:
        lead = "Rate deviates from its recent pattern"
    else:
        lead = "Raw value deviates from its recent pattern"

    tails = []
    if numbers.raw_value is not None:
        if (numbers.previous_value is not None
                and numbers.raw_change_percent is not None):
            tails.append(
                f"{spec.name} {numbers.raw_value:g} vs "
                f"{numbers.previous_value:g} "
                f"({numbers.raw_change_percent:+.0f}% vs previous month)")
        else:
            tails.append(f"{spec.name} {numbers.raw_value:g}")
    if (numbers.historical_mean is not None
            and numbers.historical_change_percent is not None):
        direction = ("above" if numbers.historical_change_percent >= 0
                     else "below")
        tails.append(
            f"{abs(numbers.historical_change_percent):+.0f}% {direction} "
            f"baseline mean {numbers.historical_mean:g}")
    if numbers.rate is not None:
        tails.append(f"rate {numbers.rate:.1f}{spec.unit}")
    if numbers.denominator is not None:
        if numbers.denominator_change_percent is not None:
            tails.append(
                f"denominator {numbers.denominator:g} "
                f"({numbers.denominator_change_percent:+.0f}% vs previous)")
        else:
            tails.append(f"denominator {numbers.denominator:g}")
    if numbers.peer_mean is not None and numbers.peer_count:
        tails.append(f"peer average {numbers.peer_mean:.1f} across "
                     f"{numbers.peer_count} hospitals")
    if not den_ok:
        tails.append("denominator missing or zero - rate layers not "
                     "computable")
    if is_small_denominator(spec, numbers.denominator):
        tails.append(
            f"small denominator ({numbers.denominator:g} < "
            f"{spec.minimum_denominator:g}) - confidence lowered, level "
            f"capped at LOW")

    if tails:
        return f"{lead}. " + "; ".join(tails) + "."
    return lead + "."


def classify_layered(
    spec: AnalysisSpec,
    *,
    raw_score: Optional[float],
    rate_score: Optional[float],
    hist_score: Optional[float],
    volume_score: Optional[float],
    peer_score: Optional[float],
    den_ok: bool,
    history_ok: bool,
    change_percent: Optional[float] = None,
    denominator: Optional[float] = None,
    raw_method: str = METHOD_INSUFFICIENT_HISTORY,
    rate_method: str = METHOD_INSUFFICIENT_HISTORY,
    hist_method: str = METHOD_INSUFFICIENT_HISTORY,
    numbers: Optional[InterpretationNumbers] = None,
) -> Classification:
    """Spec section 6 rule table: first match wins."""
    if not history_ok:
        rule, outlier_type = 1, TYPE_NORMAL
    elif (den_ok
          and _at_least(raw_score, LEVEL_HIGH)
          and _at_least(rate_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_HIGH)
          and _at_most(volume_score, LEVEL_LOW)
          and change_percent is not None
          and change_percent >= RULE2_MIN_CHANGE_PERCENT):
        rule, outlier_type = 2, TYPE_POSSIBLE_DATA_ENTRY_ERROR
    elif (_at_least(raw_score, LEVEL_HIGH)
          and _at_least(volume_score, LEVEL_HIGH)
          and _at_most(rate_score, LEVEL_MODERATE)):
        rule, outlier_type = 3, TYPE_VOLUME_DRIVEN_ANOMALY
    elif (den_ok
          and _at_least(rate_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_HIGH)
          and _at_most(volume_score, LEVEL_LOW)):
        rule, outlier_type = 4, TYPE_CLINICAL_INVESTIGATION_REQUIRED
    elif _at_least(hist_score, LEVEL_HIGH):
        rule, outlier_type = 5, TYPE_HISTORICAL_ANOMALY
    elif (_at_least(peer_score, LEVEL_HIGH)
          and _at_most(hist_score, LEVEL_LOW)):
        rule, outlier_type = 6, TYPE_PEER_ANOMALY
    elif (_at_least(peer_score, LEVEL_HIGH)
          and _at_least(hist_score, LEVEL_MODERATE)):
        rule, outlier_type = 7, TYPE_PEER_ANOMALY
    elif (_at_least(raw_score, LEVEL_MODERATE)
          and not _at_least_any((rate_score, hist_score, volume_score,
                                 peer_score), LEVEL_HIGH)):
        rule, outlier_type = 8, TYPE_RAW_VALUE_ANOMALY
    elif (_at_least(rate_score, LEVEL_MODERATE)
          and not _at_least_any((raw_score, hist_score, volume_score,
                                 peer_score), LEVEL_HIGH)):
        rule, outlier_type = 9, TYPE_RATE_ANOMALY
    else:
        rule, outlier_type = 10, TYPE_NORMAL

    level = LEVEL_NONE if rule == 1 else _max_level(
        raw_score, rate_score, hist_score, volume_score, peer_score)
    if (outlier_type in _RATE_BASED_TYPES
            and is_small_denominator(spec, denominator)):
        if LEVEL_RANK[level] > LEVEL_RANK[LEVEL_LOW]:
            level = LEVEL_LOW

    return Classification(
        outlier_type=outlier_type,
        outlier_level=level,
        investigation_required=rule in _INVESTIGATION_RULES,
        investigation_route=_ROUTE_BY_RULE[rule],
        rule_number=rule,
        method=_method_for_rule(rule, raw_method, rate_method, hist_method),
        interpretation=build_interpretation(
            spec, outlier_type, rule, den_ok=den_ok,
            numbers=numbers or InterpretationNumbers()),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS (Tasks 7-11 tests, including the classification suite).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/classify.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/classify.py tests/test_layered_engine.py
git commit -m "feat(layered): classification rule table and number-based interpretation"
```

---

### Task 12: Entry point, orchestration, scenario tests

**Files:**
- Modify: `app/engine/anomaly/layered.py` (append `LayerResult`, `analyze_layered_entry`, `build_peer_tiers`, `run_layered_analysis`, `should_persist`, `build_analysis_specs`)
- Modify: `tests/test_layered_engine.py` (extend import block + append spec §11 scenario tests 1-13 and 16)

**Interfaces:**
- Consumes: Tasks 7-11 (`classify_layered` via **deferred local import** — classify imports layered at module top, so the entry imports classify inside the function body; `load_rate_specs` from Task 6; `SYNTHETIC_INDICATOR_CODES` from `app/indicators.py:25`; `Indicator` from `app.models`).
- Produces (Tasks 13-14 depend on these exact shapes):
  - `LayerResult` dataclass: `spec, month, history_ok, raw: RawLayer, rate: RateLayer, historical: HistoricalLayer, volume: Optional[VolumeLayer], peer: PeerLayer, classification: "Classification"` (annotate via `TYPE_CHECKING` import + quoted forward reference; the value is set at runtime by the deferred import).
  - `analyze_layered_entry(spec, history, current_month, peer_tiers, thresholds, *, self_id=None) -> LayerResult` — spec §5 entry. `history` may include `current_month` (entry splits via `prior_months`); layers run in order raw → rate → volume → historical → peer → classification.
    - Count rows: `rate` = NULL `RateLayer` object, `volume = None`, `den_ok=True`, baseline series = raw series.
    - Rate rows: raw layer on **numerator** values; baseline series for the historical layer = **rate** series (spec §5 Layer 3); `den_ok`/`denominator`/`denominator_change_percent` from the volume layer; rule-2 `change_percent` = `historical.change_percent` (rate vs baseline mean).
    - `InterpretationNumbers` assembled from the actual layer values and passed to classification.
  - `build_peer_tiers(spec, self_id, unit_values, peer_attributes) -> List[Tuple[str, Dict]]` — tier order `type` → `ownership` → `governorate` → `all` (`_PEER_TIER_KEYS`); a typed tier is **skipped when the hospital's own attribute is None**; tier names `f"{label}:{value}"`; all active hospitals in `unit_values` participate (`None` unit values are ignored downstream by `compute_peer_layer`); returns `[]` when `peer_comparison_enabled=False`.
  - `run_layered_analysis(specs, history, current_month, hospital_id, peer_values_by_hospital, peer_attributes, thresholds) -> List[LayerResult]` — one result **per spec** for the analyzed hospital (matches `_compute_full_analysis`'s per-hospital model); per spec it computes each hospital's current-month unit value from `peer_values_by_hospital[hid].get(current_month, {})` and builds tiers with `build_peer_tiers`.
  - `should_persist(result) -> bool` = `result.raw.value is not None` — hospitals with no observed data for the analysis unit this month are not written (spec row must reflect something observed; numerator present with missing denominator still persists — scenario 9).
  - `build_analysis_specs(session) -> List[AnalysisSpec]` — non-synthetic `Indicator` rows (count specs; `indicator_id` set; config fields with `or`/`is not False` fallbacks for drifted DBs) followed by active `load_rate_specs(session)` values (rate specs; `analysis_code=rate_code`).
- Runtime shape note for Task 13: `Thresholds` is constructed from `AppConfig zscore_threshold` by the pipeline (not here); `peer_values_by_hospital` maps hospital id → month → raw values (only `current_month` is read).

- [ ] **Step 1: Write the failing tests**

Extend the import block at the top of `tests/test_layered_engine.py` with:

```python
from app.engine.anomaly.layered import (
    analyze_layered_entry,
    build_analysis_specs,
    build_peer_tiers,
    run_layered_analysis,
    should_persist,
)
```

Append the scenario helpers and tests:

```python
# ── End-to-end engine scenarios (spec §11) ────────────────────────────────

MONTHS5 = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
CURRENT = "2026-06"


def _history(prior_values, current, code="5"):
    h = {m: {code: float(v)} for m, v in zip(MONTHS5, prior_values)}
    h[CURRENT] = {code: float(current)}
    return h


def _rate_history(prior_pairs, current_pair, num="5", den="2"):
    h = {m: {num: float(n), den: float(d)} for m, (n, d) in zip(MONTHS5, prior_pairs)}
    n, d = current_pair
    cur = {num: float(n)}
    if d is not None:
        cur[den] = float(d)
    h[CURRENT] = cur
    return h


def _entry(spec, history, tiers=None, self_id=1, thresholds=None):
    return analyze_layered_entry(spec, history, CURRENT,
                                 tiers or [("all", {})],
                                 thresholds or Thresholds(), self_id=self_id)


def test_scenario1_normal_value_is_normal_with_low_scores():
    result = _entry(_count_spec(), _history([10] * 5, 10))
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.classification.outlier_level == "NONE"
    assert result.raw.score == 0.0
    assert result.historical.score == 0.0
    assert result.raw.method == METHOD_PCT_CHANGE
    assert result.history_ok is True


def test_scenario2_raw_value_outlier_records_high_score_and_method():
    result = _entry(_count_spec(), _history([10] * 5, 25))
    assert level_gte(result.raw.level, "HIGH")
    assert result.raw.method == METHOD_PCT_CHANGE
    assert result.raw.value == 25.0
    assert result.raw.previous == 10.0
    assert result.raw.change_percent == 150.0


def test_scenario3_rate_outlier_with_stable_denominator():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 1000)))
    assert level_gte(result.rate.level, "HIGH")
    assert result.rate.rate == pytest.approx(2.5)
    assert result.volume is not None
    assert not level_gte(result.volume.level, "MODERATE")   # stable denominator


def test_scenario4_high_numerator_and_denominator_is_volume_driven():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 2000)))
    assert result.classification.outlier_type == TYPE_VOLUME_DRIVEN_ANOMALY
    assert "volume" in result.classification.interpretation.lower()
    assert level_gte(result.raw.level, "HIGH")
    assert level_gte(result.volume.level, "HIGH")


def test_scenario5_high_numerator_stable_denominator_is_clinical():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 1000)))
    assert result.classification.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert result.classification.investigation_route == "clinical"
    assert result.classification.investigation_required is True


def test_scenario6_small_denominator_caps_level_and_keeps_row():
    spec = _rate_spec(minimum_denominator=10)
    result = _entry(spec, _rate_history([(1, 5)] * 5, (2, 5)))
    assert result.classification.outlier_type == TYPE_CLINICAL_INVESTIGATION_REQUIRED
    assert result.classification.outlier_level == "LOW"
    assert "small denominator (5 < 10)" in result.classification.interpretation
    assert "confidence lowered" in result.classification.interpretation
    assert should_persist(result) is True


def test_scenario7_historical_outlier_with_normal_peer():
    tiers = [("type:general", {1: 25.0, 2: 24.0, 3: 25.0, 4: 26.0})]
    result = _entry(_count_spec(), _history([10] * 5, 25), tiers=tiers)
    assert result.classification.outlier_type == TYPE_HISTORICAL_ANOMALY
    assert result.peer.score is not None
    assert not level_gte(result.peer.level, "MODERATE")     # peers near self


def test_scenario8_peer_outlier_never_says_data_error():
    tiers = [("type:general", {1: 10.0, 2: 30.0, 3: 30.0})]
    result = _entry(_count_spec(), _history([10] * 5, 10), tiers=tiers)
    assert result.classification.outlier_type == TYPE_PEER_ANOMALY
    assert result.classification.rule_number == 6
    text = result.classification.interpretation.lower()
    assert "differs from peers" in text
    assert "error" not in text


def test_scenario9_missing_denominator_rate_layers_not_computable():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, None)))
    assert result.rate.rate is None
    assert result.rate.score is None
    assert result.volume is not None
    assert result.volume.den_ok is False
    assert result.volume.score is None
    assert result.historical.score is None
    assert result.classification.outlier_type != TYPE_RATE_ANOMALY
    assert "not computable" in result.classification.interpretation


def test_scenario10_zero_denominator_no_division_by_zero():
    result = _entry(_rate_spec(), _rate_history([(10, 900)] * 5, (25, 0)))
    assert result.volume.denominator == 0.0
    assert result.volume.den_ok is False
    assert result.rate.rate is None and result.rate.score is None
    assert "not computable" in result.classification.interpretation


def test_scenario11_missing_historical_data_insufficient_history():
    result = _entry(_count_spec(), {CURRENT: {"5": 10.0}})
    assert result.history_ok is False
    assert result.classification.rule_number == 1
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.classification.outlier_level == "NONE"
    assert result.classification.method == METHOD_INSUFFICIENT_HISTORY
    assert result.raw.method == METHOD_INSUFFICIENT_HISTORY
    assert result.raw.score is None
    assert should_persist(result) is True


def test_scenario12_first_months_below_minimum_history():
    history = {"2026-05": {"5": 10.0}, CURRENT: {"5": 25.0}}
    result = _entry(_count_spec(), history)
    assert result.history_ok is False
    assert result.classification.rule_number == 1
    assert result.classification.outlier_type == TYPE_NORMAL
    assert result.raw.score is None            # not judged, never an outlier
    assert result.raw.value == 25.0            # value still reported


def test_scenario13_rare_event_indicator_uses_mad_not_z():
    history = {m: {"5": float(v)} for m, v in zip(MONTHS5, [0, 1, 0, 1, 0])}
    history[CURRENT] = {"5": 1.0}
    result = _entry(_count_spec(), history)
    assert result.raw.method == METHOD_ROLLING_MEDIAN_MAD
    assert result.historical.method == METHOD_ROLLING_MEDIAN_MAD
    assert result.raw.score == 1.0             # MAD 0, value != median
    assert result.classification.method == METHOD_ROLLING_MEDIAN_MAD


def test_entry_splits_current_month_from_history():
    h = _history([10] * 5, 10)
    del h[CURRENT]
    result = _entry(_count_spec(), h)
    assert result.raw.value is None            # no current-month data
    assert result.history_ok is True           # 5 priors still counted
    assert should_persist(result) is False


def test_scenario16_peer_fallback_tier_order_and_null_without_peers():
    unit_values = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0}
    attrs = {
        1: {"type": 1, "ownership": 7, "governorate": 100},
        2: {"type": 2, "ownership": 7, "governorate": 100},
        3: {"type": 2, "ownership": 8, "governorate": 101},
        4: {"type": None, "ownership": None, "governorate": None},
    }
    spec = _count_spec()
    tiers = build_peer_tiers(spec, 1, unit_values, attrs)
    assert [n for n, _ in tiers] == ["type:1", "ownership:7", "governorate:100", "all"]
    # typed tiers each hold only self + 1 other (<2 others) -> "all" fallback
    layer = compute_peer_layer(spec, 1, 10.0, tiers)
    assert layer.tier == "all"
    assert layer.peer_count == 3
    assert layer.peer_mean == pytest.approx(30.0)

    # first sufficient tier wins: type has 2 others (mean 25, not all's 30)
    attrs2 = {1: {"type": 1}, 2: {"type": 1}, 3: {"type": 1}, 4: {"type": 2}}
    tiers2 = build_peer_tiers(spec, 1, unit_values, attrs2)
    assert [n for n, _ in tiers2] == ["type:1", "all"]
    layer2 = compute_peer_layer(spec, 1, 10.0, tiers2)
    assert layer2.tier == "type:1"
    assert layer2.peer_mean == pytest.approx(25.0)

    # hospital with no attributes typed -> typed tiers skipped entirely
    tiers3 = build_peer_tiers(spec, 9, {9: 10.0}, {9: {"type": 1}})
    assert [n for n, _ in tiers3] == ["type:1", "all"]
    layer3 = compute_peer_layer(spec, 9, 10.0, tiers3)
    assert layer3.score is None and layer3.peer_count == 0   # <2 everywhere

    disabled = _count_spec(peer_comparison_enabled=False)
    assert build_peer_tiers(disabled, 1, unit_values, attrs) == []


def test_run_layered_analysis_one_result_per_spec_for_analyzed_hospital():
    spec = _count_spec()
    history = _history([10] * 5, 10)
    peers = {1: history, 2: {CURRENT: {"5": 10.0}}, 3: {CURRENT: {"5": 12.0}}}
    attrs = {hid: {"type": 1, "ownership": 1, "governorate": 1} for hid in (1, 2, 3)}
    results = run_layered_analysis([spec], history, CURRENT, 1, peers, attrs,
                                   Thresholds())
    assert len(results) == 1
    r = results[0]
    assert r.classification.outlier_type == TYPE_NORMAL
    assert r.peer.peer_count == 2
    assert r.peer.peer_mean == pytest.approx(11.0)


def test_build_analysis_specs_combines_indicators_and_rate_config(db_session):
    specs = build_analysis_specs(db_session)
    codes = [s.analysis_code for s in specs]
    assert "0" not in codes                    # synthetic label excluded
    assert "rate_cs" in codes                  # rate_config seed present
    rate = next(s for s in specs if s.analysis_code == "rate_cs")
    assert rate.is_rate
    assert rate.numerator_codes and rate.denominator_codes
    count = next(s for s in specs if not s.is_rate)
    assert count.indicator_id is not None
    assert not count.denominator_codes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'analyze_layered_entry' from 'app.engine.anomaly.layered'`.

- [ ] **Step 3: Append the entry point and orchestration to `layered.py`**

Add `TYPE_CHECKING` to the `typing` import at the top of `layered.py` and, after the existing imports, add:

```python
if TYPE_CHECKING:
    from app.engine.anomaly.classify import Classification
```

Append to the end of `app/engine/anomaly/layered.py`:

```python
# ── Entry point (spec §5) ──────────────────────────────────────────────────

@dataclass
class LayerResult:
    """All layer outputs + classification for one hospital x spec x month."""
    spec: AnalysisSpec
    month: str
    history_ok: bool
    raw: RawLayer
    rate: RateLayer
    historical: HistoricalLayer
    volume: Optional[VolumeLayer]       # None for count rows
    peer: PeerLayer
    classification: "Classification"


def analyze_layered_entry(
    spec: AnalysisSpec,
    history: Dict[str, Dict[str, float]],
    current_month: str,
    peer_tiers: Sequence[Tuple[str, Dict[Any, Optional[float]]]],
    thresholds: Thresholds,
    *,
    self_id: Any = None,
) -> LayerResult:
    """Run the sequential layer pipeline for one analysis unit.

    `history` maps month -> indicator values and may include current_month
    (prior_months splits it). Layers run raw -> rate/volume -> historical ->
    peer -> classification (spec §5 ordering: peer never runs first).
    """
    # Deferred: classify.py imports this module at top level.
    from app.engine.anomaly.classify import (InterpretationNumbers,
                                             classify_layered)

    months = prior_months(history, current_month)
    current_values = history.get(current_month, {})
    history_ok = len(months) >= spec.minimum_history_period

    # Layer 1 — raw analysis value (numerator for rate rows).
    raw_series = [raw_analysis_value(spec, history[m]) for m in months]
    raw_value = raw_analysis_value(spec, current_values)
    raw = compute_raw_layer(spec, raw_series, raw_value, history_ok,
                            thresholds.peer_z_threshold)

    # Layers 2 + 4 — rate and denominator (rate rows only).
    if spec.is_rate:
        rate_series = [rate_analysis_value(spec, history[m]) for m in months]
        current_rate = rate_analysis_value(spec, current_values)
        rate_layer = compute_rate_layer(spec, rate_series, current_rate,
                                        history_ok, thresholds.peer_z_threshold)
        den_series = [denominator_analysis_value(spec, history[m])
                      for m in months]
        current_den = denominator_analysis_value(spec, current_values)
        volume = compute_volume_layer(spec, den_series, current_den)
        baseline_series, baseline_current = rate_series, current_rate
        den_ok = volume.den_ok                 # volume is not None for rates
        denominator_value = volume.denominator
        denominator_change = volume.change_percent
        rate_value = rate_layer.rate
    else:
        rate_layer = compute_rate_layer(spec, [], None, history_ok)
        volume = None
        baseline_series, baseline_current = raw_series, raw_value
        den_ok = True
        denominator_value = None
        denominator_change = None
        rate_value = None

    # Layer 3 — historical baseline (rate history when the spec has a rate).
    historical = compute_historical_layer(spec, baseline_series,
                                          baseline_current, history_ok,
                                          thresholds.peer_z_threshold)

    # Layer 5 — peer comparison on this month's unit value.
    unit_value = rate_value if spec.is_rate else raw_value
    peer = compute_peer_layer(spec, self_id, unit_value, peer_tiers,
                              thresholds.peer_z_threshold)

    numbers = InterpretationNumbers(
        raw_value=raw_value,
        previous_value=raw.previous,
        raw_change_percent=raw.change_percent,
        rate=rate_value,
        denominator=denominator_value,
        denominator_change_percent=denominator_change,
        historical_mean=historical.mean,
        historical_change_percent=historical.change_percent,
        peer_mean=peer.peer_mean,
        peer_count=peer.peer_count,
    )
    classification = classify_layered(
        spec,
        raw_score=raw.score,
        rate_score=rate_layer.score,
        hist_score=historical.score,
        volume_score=volume.score if volume else None,
        peer_score=peer.score,
        den_ok=den_ok,
        history_ok=history_ok,
        change_percent=historical.change_percent,
        denominator=denominator_value,
        raw_method=raw.method,
        rate_method=rate_layer.method,
        hist_method=historical.method,
        numbers=numbers,
    )
    return LayerResult(spec=spec, month=current_month, history_ok=history_ok,
                       raw=raw, rate=rate_layer, historical=historical,
                       volume=volume, peer=peer, classification=classification)


# ── Orchestration (spec §7: pipeline calls this per hospital/month) ────────

_PEER_TIER_KEYS = (("type", "type"), ("ownership", "ownership"),
                   ("governorate", "governorate"))


def build_peer_tiers(spec: AnalysisSpec, self_id: Any,
                     unit_values: Dict[Any, Optional[float]],
                     peer_attributes: Dict[Any, Dict[str, Any]]
                     ) -> List[Tuple[str, Dict[Any, Optional[float]]]]:
    """Ordered tier list type -> ownership -> governorate -> all.

    A typed tier is skipped when the hospital's own attribute is None; all
    hospitals in unit_values belong to the 'all' tier. Returns [] when the
    spec disables peer comparison.
    """
    if not spec.peer_comparison_enabled:
        return []
    attrs_self = peer_attributes.get(self_id, {})
    tiers: List[Tuple[str, Dict[Any, Optional[float]]]] = []
    for key, label in _PEER_TIER_KEYS:
        value = attrs_self.get(key)
        if value is None:
            continue
        members = {
            hid: unit_values.get(hid)
            for hid in unit_values
            if peer_attributes.get(hid, {}).get(key) == value
        }
        tiers.append((f"{label}:{value}", members))
    tiers.append(("all", dict(unit_values)))
    return tiers


def run_layered_analysis(
    specs: Sequence[AnalysisSpec],
    history: Dict[str, Dict[str, float]],
    current_month: str,
    hospital_id: Any,
    peer_values_by_hospital: Dict[Any, Dict[str, Dict[str, float]]],
    peer_attributes: Dict[Any, Dict[str, Any]],
    thresholds: Thresholds,
) -> List[LayerResult]:
    """One LayerResult per spec for the analyzed hospital (the pipeline's
    per-hospital model). peer_values_by_hospital supplies the current-month
    values used to build each spec's peer tiers."""
    results: List[LayerResult] = []
    for spec in specs:
        unit_values: Dict[Any, Optional[float]] = {}
        for hid, months_values in peer_values_by_hospital.items():
            current_values = months_values.get(current_month, {})
            if spec.is_rate:
                unit_values[hid] = rate_analysis_value(spec, current_values)
            else:
                unit_values[hid] = raw_analysis_value(spec, current_values)
        tiers = build_peer_tiers(spec, hospital_id, unit_values,
                                 peer_attributes)
        results.append(analyze_layered_entry(spec, history, current_month,
                                             tiers, thresholds,
                                             self_id=hospital_id))
    return results


def should_persist(result: LayerResult) -> bool:
    """Keep rows where something was observed this month: the raw analysis
    value (numerator for rate rows) exists. A present numerator with a
    missing denominator still persists (scenario 9)."""
    return result.raw.value is not None


def build_analysis_specs(session) -> List[AnalysisSpec]:
    """Count specs from non-synthetic Indicator rows + rate specs from the
    rate_config registry (Task 6)."""
    from app.engine.rate_config import load_rate_specs
    from app.indicators import SYNTHETIC_INDICATOR_CODES
    from app.models import Indicator

    specs: List[AnalysisSpec] = []
    indicators = (
        session.query(Indicator)
        .filter(~Indicator.code.in_(SYNTHETIC_INDICATOR_CODES))
        .order_by(Indicator.id)
        .all()
    )
    for ind in indicators:
        specs.append(AnalysisSpec(
            analysis_code=ind.code,
            name=ind.name,
            indicator_type=ind.indicator_type or "count",
            indicator_id=ind.id,
            minimum_history_period=(ind.minimum_history_period
                                    or DEFAULT_MINIMUM_HISTORY),
            outlier_method=ind.outlier_method or METHOD_AUTO,
            historical_enabled=ind.historical_enabled is not False,
            peer_comparison_enabled=ind.peer_comparison_enabled is not False,
        ))
    for rs in load_rate_specs(session).values():
        if not rs.is_active:
            continue
        specs.append(AnalysisSpec(
            analysis_code=rs.rate_code,
            name=rs.rate_name,
            indicator_type=rs.indicator_type,
            numerator_codes=tuple(rs.numerator_codes),
            denominator_codes=tuple(rs.denominator_codes),
            rate_multiplier=rs.rate_multiplier,
            unit=rs.unit,
            minimum_denominator=rs.minimum_denominator,
            minimum_history_period=rs.minimum_history_period,
            outlier_method=rs.outlier_method,
            historical_enabled=rs.historical_enabled,
            peer_comparison_enabled=rs.peer_comparison_enabled,
        ))
    return specs
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_engine.py -v`
Expected: all PASS (Tasks 7-12, including all spec §11 scenarios except 14-15 which are API tests in Task 14).

- [ ] **Step 5: Lint and commit**

Run: `.venv\Scripts\ruff.exe check app/engine/anomaly/layered.py tests/test_layered_engine.py`

```bash
git add app/engine/anomaly/layered.py tests/test_layered_engine.py
git commit -m "feat(layered): entry point, peer tier builder, orchestration, scenario tests"
```

---

### Task 13: Pipeline persistence — compute, store, purge

**Files:**
- Modify: `app/engine/pipeline.py`
- Create: `tests/test_layered_pipeline.py`

**Interfaces:**
- Consumes (Tasks 6, 12): `LayeredOutlierResult`, `build_analysis_specs`, `run_layered_analysis`, `Thresholds`, `should_persist`, `LayerResult` fields.
- Produces (Tasks 14-15): `layered_outlier_results` rows keyed `(hospital_id, analysis_code, month)` — the join source for the outliers endpoint and the payload source for `kind=layered_outlier` explain.

**Context:**
- `_compute_full_analysis` (pipeline.py:286) already has everything needed in scope: `values` (:310), `all_hospital_data` (:337, keyed by hospital **name**), `historical` (:338, **excludes the current month** — `get_historical_months` :262), and `anomaly_config["zscore_threshold"]` (:367, the same z-knob `detect_anomalies` uses, so the peer z-threshold stays shared).
- The layered call is wrapped in `try/except` + `session.rollback()`: validation/anomaly/quality/confidence rows are already committed at that point (`_save_*` each commit), so a layered failure must be swallowed — otherwise `run_full_analysis`'s outer handler (pipeline.py:540) would replace the real score with the zero-score "Analysis failed during report generation" fallback.
- Lifecycle: `purge_derived_results` (:579) is the single purge used by Remove Data (`api/hospitals.py:161,244`), file ops (`api/file_ops.py:665`) and `recompute_hospital_months` (:621) — the new table joins its tuple. The empty-values force path (:311-328) clears stale rows for months that lost their data. The cached path returns before this code, so already-persisted rows are left alone.
- Disabled indicators need no special handling: `history` and current `values` both come from `get_enabled_values_for_hospital_month`, so a disabled code simply has no value → `should_persist` drops the row.
- Existing installs gain layered rows for old months only on the next analysis (recompute / re-analysis / new upload) — expected per spec §7; quality scores are untouched (Q3).

- [ ] **Step 1: Add the model import**

Edit the models import block at `app/engine/pipeline.py:9-14`:

```python
from app.models import (
    Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig,
    IndicatorDefaultConfig,
    ValidationResult, AnomalyResult, QualityScore, ConfidenceScore,
    ClinicalInsight, LayeredOutlierResult,
)
```

(The block is not isort-sorted — that pre-existing I001 is fixed by `ruff --fix` in Step 7.)

- [ ] **Step 2: Run layered analysis at the end of `_compute_full_analysis`**

Anchor on the confidence block (`app/engine/pipeline.py:457-463`) and insert the layered call between the confidence save and the `outliers = []` assembly:

```python
    if confidence_data:
        try:
            _save_confidence_score(session, hospital_id, month, confidence_data)
        except Exception:
            logger.exception("Saving confidence score failed for %s/%s", hospital.name, month)

    try:
        _run_and_save_layered_results(
            session, hospital_id, month, values,
            historical if historical else {},
            all_hospital_data,
            anomaly_config["zscore_threshold"],
        )
    except Exception:
        # Layered rows are additive (spec §7): never discard the quality/
        # validation/anomaly results already committed above, and never trip
        # run_full_analysis's zero-score fallback report.
        session.rollback()
        logger.exception(
            "Layered analysis failed for %s/%s; continuing without layered results",
            hospital.name, month,
        )

    outliers = []
```

- [ ] **Step 3: Add the layered save helpers**

Insert between `_save_anomaly_results` (ends `session.commit()` at pipeline.py:681) and `def _save_quality_score(` (:684):

```python
def _run_and_save_layered_results(session: Session, hospital_id: int, month: str,
                                  values: Dict, historical: Dict,
                                  all_hospital_data: Dict,
                                  zscore_threshold: float) -> None:
    """Run the layered outlier pipeline (spec §7) for the analyzed hospital
    and persist the resulting rows.

    get_historical_months() excludes the current month (pipeline.py:262), so
    the current month's enabled values are merged in — analyze_layered_entry
    splits history itself. peer inputs arrive name-keyed from
    get_all_hospital_data_for_month() and are re-keyed by hospital id here;
    tier attributes come straight from the Hospital columns.
    """
    from app.engine.anomaly.layered import (
        Thresholds,
        build_analysis_specs,
        run_layered_analysis,
        should_persist,
    )

    specs = build_analysis_specs(session)
    hospitals = (
        session.query(
            Hospital.id, Hospital.name, Hospital.hospital_type_id,
            Hospital.facility_ownership_id, Hospital.governorate_id,
        )
        .filter(Hospital.is_active.is_(True))
        .all()
    )
    peer_values_by_hospital = {
        h.id: {month: all_hospital_data.get(h.name, {})}
        for h in hospitals
    }
    peer_attributes = {
        h.id: {
            "type": h.hospital_type_id,
            "ownership": h.facility_ownership_id,
            "governorate": h.governorate_id,
        }
        for h in hospitals
    }
    history = dict(historical)
    history[month] = values

    results = run_layered_analysis(
        specs, history, month, hospital_id,
        peer_values_by_hospital, peer_attributes,
        Thresholds(peer_z_threshold=float(zscore_threshold)),
    )
    _save_layered_results(
        session, hospital_id, month,
        [r for r in results if should_persist(r)],
    )


def _save_layered_results(session: Session, hospital_id: int, month: str, results: list):
    session.query(LayeredOutlierResult).filter(
        LayeredOutlierResult.hospital_id == hospital_id,
        LayeredOutlierResult.month == month,
    ).delete()
    for r in results:
        c = r.classification
        session.add(LayeredOutlierResult(
            hospital_id=hospital_id,
            indicator_id=r.spec.indicator_id,
            analysis_code=r.spec.analysis_code,
            month=month,
            raw_value=float(r.raw.value) if r.raw.value is not None else None,
            previous_value=float(r.raw.previous) if r.raw.previous is not None else None,
            numerator=float(r.raw.value) if (r.spec.is_rate and r.raw.value is not None) else None,
            denominator=(float(r.volume.denominator)
                         if r.volume and r.volume.denominator is not None else None),
            rate=float(r.rate.rate) if r.rate.rate is not None else None,
            previous_denominator=(float(r.volume.previous)
                                  if r.volume and r.volume.previous is not None else None),
            denominator_change_percent=(float(r.volume.change_percent)
                                        if r.volume and r.volume.change_percent is not None else None),
            historical_mean=(float(r.historical.mean)
                             if r.historical.mean is not None else None),
            historical_median=(float(r.historical.median)
                               if r.historical.median is not None else None),
            historical_std=(float(r.historical.std)
                            if r.historical.std is not None else None),
            historical_z_score=(float(r.historical.z_score)
                                if r.historical.z_score is not None else None),
            historical_change_percent=(float(r.historical.change_percent)
                                       if r.historical.change_percent is not None else None),
            raw_value_outlier_score=(float(r.raw.score)
                                     if r.raw.score is not None else None),
            rate_outlier_score=(float(r.rate.score)
                                if r.rate.score is not None else None),
            historical_outlier_score=(float(r.historical.score)
                                      if r.historical.score is not None else None),
            volume_anomaly_score=(float(r.volume.score)
                                  if r.volume and r.volume.score is not None else None),
            peer_outlier_score=(float(r.peer.score)
                                if r.peer.score is not None else None),
            peer_mean=float(r.peer.peer_mean) if r.peer.peer_mean is not None else None,
            peer_count=r.peer.peer_count,
            outlier_level=c.outlier_level,
            outlier_type=c.outlier_type,
            outlier_method=c.method,
            interpretation=c.interpretation,
            investigation_required=c.investigation_required,
            investigation_route=c.investigation_route,
        ))
    session.commit()
```

Notes:
- `r.rate` is always a `RateLayer` (count rows get `rate=None, score=None` — Task 9); `r.volume` is `None` for count rows, hence the guards.
- Delete-then-insert honors the `(hospital_id, analysis_code, month)` unique constraint — re-analysis replaces rows instead of duplicating them.
- `peer_count` is `0` (not `NULL`) when no usable peer tier exists — `PeerLayer`'s no-tier shape (Task 10).

- [ ] **Step 4: Wire the purge lifecycle**

4a. In `purge_derived_results` (pipeline.py:587-593), extend the tuple:

```python
    for key, model in (
        ("quality_scores", QualityScore),
        ("validation_results", ValidationResult),
        ("anomaly_results", AnomalyResult),
        ("confidence_scores", ConfidenceScore),
        ("clinical_insights", ClinicalInsight),
        ("layered_outlier_results", LayeredOutlierResult),
    ):
```

4b. In the empty-values force path (pipeline.py:316-328), add the layered delete before the commit:

```python
        if force:
            session.query(ValidationResult).filter(
                ValidationResult.hospital_id == hospital_id,
                ValidationResult.month == month,
            ).delete(synchronize_session=False)
            session.query(AnomalyResult).filter(
                AnomalyResult.hospital_id == hospital_id,
                AnomalyResult.month == month,
            ).delete(synchronize_session=False)
            session.query(ConfidenceScore).filter(
                ConfidenceScore.hospital_id == hospital_id,
                ConfidenceScore.month == month,
            ).delete(synchronize_session=False)
            session.query(LayeredOutlierResult).filter(
                LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month,
            ).delete(synchronize_session=False)
            session.commit()
```

- [ ] **Step 5: Write the tests**

Create `tests/test_layered_pipeline.py`:

```python
"""Persistence and lifecycle of layered_outlier_results (design spec §7).

The layered engine itself is covered by tests/test_layered_engine.py; these
tests prove the pipeline writes, replaces, purges and isolates the rows.
"""
import pytest

from app.models import (
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
)


PRIOR_MONTHS = ["2027-01", "2027-02", "2027-03", "2027-04", "2027-05"]
CURRENT = "2027-06"


def _seed_values(db, hospital_id, month, values):
    code_to_ind = {i.code: i for i in db.query(Indicator).all()}
    for code, val in values.items():
        ind = code_to_ind.get(code)
        if ind is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital_id, indicator_id=ind.id,
                              month=month, value=val))
    db.commit()


def _seed_history(db, name, current_values, prior_values=None):
    """Active hospital with five prior months of history plus CURRENT."""
    prior_values = prior_values or {"2": 100, "5": 10}
    hosp = Hospital(name=name, region="Region A")
    db.add(hosp)
    db.flush()
    for month in PRIOR_MONTHS:
        _seed_values(db, hosp.id, month, prior_values)
    _seed_values(db, hosp.id, CURRENT, current_values)
    return hosp


def _rows(db, hospital_id, month=CURRENT):
    return (
        db.query(LayeredOutlierResult)
        .filter(LayeredOutlierResult.hospital_id == hospital_id,
                LayeredOutlierResult.month == month)
        .all()
    )


def test_pipeline_persists_layered_rows(db_session):
    """Full analysis writes one row per observed analysis unit with scores,
    classification and interpretation attached (spec §7)."""
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Persist", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)

    rows = _rows(db_session, hosp.id)
    assert len(rows) >= 3
    by_code = {r.analysis_code: r for r in rows}

    rate_row = by_code["rate_cs"]
    assert rate_row.rate == pytest.approx(25.0)
    assert rate_row.numerator == pytest.approx(25.0)
    assert rate_row.denominator == pytest.approx(100.0)
    assert rate_row.previous_value == pytest.approx(10.0)
    assert rate_row.previous_denominator == pytest.approx(100.0)
    assert rate_row.denominator_change_percent == pytest.approx(0.0)
    assert rate_row.historical_mean == pytest.approx(10.0)
    assert rate_row.historical_median == pytest.approx(10.0)
    assert rate_row.historical_change_percent == pytest.approx(150.0)
    assert rate_row.raw_value_outlier_score == pytest.approx(1.0)
    assert rate_row.rate_outlier_score >= 0.75        # rule 4 premise (HIGH)
    assert rate_row.historical_outlier_score >= 0.75
    assert rate_row.volume_anomaly_score == pytest.approx(0.0)
    assert rate_row.peer_mean is None                 # sole reporting hospital
    assert rate_row.peer_count == 0
    assert rate_row.outlier_type == "CLINICAL_INVESTIGATION_REQUIRED"
    assert rate_row.outlier_level == "VERY_HIGH"
    assert rate_row.investigation_required is True
    assert rate_row.investigation_route == "clinical"
    assert rate_row.outlier_method
    assert "25" in rate_row.interpretation            # actual numbers in text

    count_row = by_code["5"]
    assert count_row.indicator_id is not None
    assert count_row.rate is None
    assert count_row.volume_anomaly_score is None     # volume layer: count rows
    assert count_row.raw_value == pytest.approx(25.0)
    assert count_row.previous_value == pytest.approx(10.0)
    assert count_row.outlier_type == "HISTORICAL_ANOMALY"
    assert count_row.outlier_level == "VERY_HIGH"
    assert count_row.investigation_required is False
    assert count_row.investigation_route == "contextual"
    assert "own recent baseline" in count_row.interpretation

    normal_row = by_code["2"]
    assert normal_row.outlier_type == "NORMAL"
    assert normal_row.outlier_level == "NONE"
    assert normal_row.raw_value == pytest.approx(100.0)
    assert normal_row.investigation_route == "none"
    assert "No layer exceeded its threshold" in normal_row.interpretation

    # Core quality score is written alongside — layered rows are additive (Q3).
    qs = (db_session.query(QualityScore)
          .filter_by(hospital_id=hosp.id, month=CURRENT).first())
    assert qs is not None


def test_reanalysis_replaces_rows_without_duplicates(db_session):
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Dup", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    first = sorted(r.analysis_code for r in _rows(db_session, hosp.id))
    assert first

    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    second = _rows(db_session, hosp.id)
    assert sorted(r.analysis_code for r in second) == first
    ids = [r.id for r in second]
    assert len(ids) == len(set(ids))


def test_peer_inputs_flow_into_persisted_rows(db_session):
    """Peer tiers are built from all_hospital_data re-keyed by hospital id
    (tier attributes straight from the Hospital columns)."""
    from app.engine.pipeline import run_full_analysis

    target = _seed_history(db_session, "PeerFlow Target", {"2": 100, "5": 25})
    for name, csections in (("PeerFlow B", 10), ("PeerFlow C", 10)):
        peer = Hospital(name=name, region="Region A")
        db_session.add(peer)
        db_session.flush()
        _seed_values(db_session, peer.id, CURRENT, {"2": 100, "5": csections})
    db_session.commit()

    run_full_analysis(db_session, target.id, CURRENT, force=True)

    rate_row = {r.analysis_code: r
                for r in _rows(db_session, target.id)}["rate_cs"]
    assert rate_row.peer_count == 2
    assert rate_row.peer_mean == pytest.approx(10.0)
    assert rate_row.peer_outlier_score == pytest.approx(1.0)  # stdev 0, 25 != 10
    # The peer layer never rescues the clinical rule: rate + history high
    # with a stable denominator still classifies as clinical (rule 4 first).
    assert rate_row.outlier_type == "CLINICAL_INVESTIGATION_REQUIRED"


def test_purge_derived_results_includes_layered_rows(db_session):
    from app.engine.pipeline import purge_derived_results, run_full_analysis

    hosp = _seed_history(db_session, "Layered Purge", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    n = len(_rows(db_session, hosp.id))
    assert n > 0

    counts = purge_derived_results(db_session, hosp.id, CURRENT)
    assert counts["layered_outlier_results"] == n
    assert _rows(db_session, hosp.id) == []


def test_force_recompute_with_no_data_clears_layered_rows(db_session):
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Empty", {"2": 100, "5": 25})
    run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    assert _rows(db_session, hosp.id)

    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hosp.id
    ).delete(synchronize_session=False)
    db_session.commit()

    result = run_full_analysis(db_session, hosp.id, CURRENT, force=True)
    assert result["data_quality_score"] == 0
    assert _rows(db_session, hosp.id) == []


def test_layered_failure_does_not_break_core_analysis(db_session, monkeypatch):
    """A crash inside layered persistence must not fall back to the zero-score
    error report (run_full_analysis's outer handler) — the layered try/except
    inside _compute_full_analysis isolates it."""
    import app.engine.anomaly.layered as layered_mod
    from app.engine.pipeline import run_full_analysis

    hosp = _seed_history(db_session, "Layered Isolated", {"2": 100, "5": 25})

    def _boom(session):
        raise RuntimeError("injected layered failure")

    monkeypatch.setattr(layered_mod, "build_analysis_specs", _boom)
    result = run_full_analysis(db_session, hosp.id, CURRENT, force=True)

    assert "Analysis failed during report generation" not in (result.get("issues") or [])
    assert _rows(db_session, hosp.id) == []
    assert (db_session.query(QualityScore)
            .filter_by(hospital_id=hosp.id, month=CURRENT).first()) is not None
```

Expected outcomes, pinned against the T11/T12 scenarios (constant priors `[10]*5`, current `25` → raw/pct window score exactly 1.0; scenario 5 proves the same rate shape classifies `CLINICAL_INVESTIGATION_REQUIRED`, scenario 7 the count shape `HISTORICAL_ANOMALY`, scenario 1 the stable shape `NORMAL`):

- rate row: rule 4 (rate + history HIGH, denominator stable, change +150% < 300% guard) → clinical, `VERY_HIGH`, peer absent for a sole reporter (`peer_count == 0`).
- count row `5`: rules 2-4 need rate/volume layers (absent for counts) → rule 5 historical.
- count row `2`: all layers zero → rule 10 `NORMAL` / `NONE`.
- peer test: only the `all` tier has ≥2 non-self members with values (seeded hospitals have `type/ownership/governorate = None`, and `build_peer_tiers` skips typed tiers when the target's own attribute is None), `stdev([10, 10]) == 0` with an unequal current value → score exactly 1.0.

- [ ] **Step 6: Run the tests (layered + pipeline regression)**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_pipeline.py tests/test_pipeline.py tests/test_remove_data.py -v`

Expected: all PASS. `test_remove_data.py` proves the extended purge tuple is transparent to its callers (it asserts specific count keys, never the full set); `test_pipeline.py` guards the surrounding pipeline behavior.

- [ ] **Step 7: Lint and commit**

`app/engine/pipeline.py` carries a **pre-existing I001** (unsorted import block — present before this task). Let ruff fix it; the auto-fix only reorders that import block:

```bash
.venv\Scripts\ruff.exe check --fix app/engine/pipeline.py
.venv\Scripts\ruff.exe check app/engine/pipeline.py tests/test_layered_pipeline.py
```

Expected: `All checks passed!`

```bash
git add app/engine/pipeline.py tests/test_layered_pipeline.py
git commit -m "feat(layered): compute and persist layered outlier rows in the analysis pipeline"
```

---

### Task 14: API — layered endpoints, outliers classification join

**Files:**
- Modify: `app/api/analysis.py`
- Create: `tests/test_layered_api.py`

**Interfaces:**
- Consumes (Tasks 6, 7): `LayeredOutlierResult` (31 columns), `load_rate_specs(db)` → `{rate_code: RateSpec}` (`spec.rate_name`, `spec.rate_code`), `LEVELS`, `build_analysis_specs(session)` (`spec.analysis_code`, `spec.name`, `spec.indicator_type`).
- Produces (Tasks 16, 17): `GET /analysis/layered` + `GET /analysis/layered/summary` for the Layered tab; `layered_type` / `layered_level` / `layered_interpretation` on every `GET /analysis/outliers` row for the Outliers tab's classification column and tooltip.

**Context:**
- Permissions come free: the whole `/analysis` router carries `dependencies=[Depends(require_permission("analysis.read"))]` (analysis.py:45), and `require_permission` raises **403** (`deps.py:40`) for a non-superuser missing the codename — new routes inherit both.
- Cache mechanics (`app/cache.py`): `make_key(path, **params)` (:188) returns `"v2|<path>|k=v|..."` with `None` params dropped (:193), so prefix invalidation must include the `v2|` segment — memory matches `key.startswith(prefix)` (:143) and files match `_safe_filename(prefix)` (:149, char-wise `→ "_"` so the prefix stays prefix-preserving). The outliers key bumps **v3 → v4**: a cached v3 payload predates the layered fields and would silently hide the classification column for up to 24h after deploy. `cache.invalidate()` in `_run_reanalyze_all` (analysis.py:670) is a full flush that already clears both new namespaces after reanalysis, and `config_api.py:189-190` flushes `v2|analysis:` on config writes.
- Test isolation comes from conftest, not from the tests: `_isolate_cache_dir` (autouse, function-scoped, conftest.py:135-163) points `_CACHE_DIR` at a fresh tmp dir and clears the in-memory dict for **every** test — so no test needs a startup invalidate; only the cache-lifecycle test invalidates mid-test on purpose.
- The "LEFT JOIN" is application-level on purpose: `anomaly_results` outlier rows are **rate rows** (`indicator_code` = numerator code, `rate_name` = e.g. "C-section rate", zscore.py:82), while the layered table keys on `analysis_code`. Translating `rate_name → rate_code` goes through the registry (`load_rate_specs`), which no SQL join can do — so two queries + a dict lookup keyed `(hospital_id, month, analysis_code)`. The numeric fallback (`or r.indicator_code`) matches the count row for the same numerator when a rate name is missing from the registry (renamed/removed rate); rows with no layered counterpart stay `None` (LEFT JOIN semantics — never `NORMAL`).
- Param spelling follows spec §8.1 exactly: `month`, **`hospital`** (not `hospital_id` — that is the outliers spelling), `indicator`, `classification`, `level`, `page`, `page_size`; §10B's route filtering is server-side (the table pages), so it becomes an extra `investigation` param, and "server-side sort" becomes `sort`/`order` with the whitelist fallback month desc.
- Display metadata (`indicator_name`/`indicator_type`) comes from `build_analysis_specs(db)` — the *same* source the engine writes with — instead of a second hand-rolled Indicator/rate_config lookup that could drift.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_layered_api.py`:

```python
"""API tests for the layered-outlier endpoints (design spec 2026-10-08 §8).

Rows are inserted directly: pipeline → table persistence is Task 13's
coverage; this module reads the API surface (filters, paging, summary,
the outliers join, cache lifecycle, permissions)."""
import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    LayeredOutlierResult,
    Permission,
    Role,
    User,
)


@pytest.fixture
def client(app):
    """TestClient over the conftest app — `_bypass_auth` already overrides
    get_current_user (superadmin) and get_db (db_session)."""
    return TestClient(app)


@pytest.fixture
def real_auth(app, _bypass_auth):
    """Strip the FakeSuperAdmin override so real JWT permission checks run."""
    app.dependency_overrides.pop(get_current_user, None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _login(client, username, password="test123"):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _add_layered(db, hospital_id, month, *, analysis_code="rate_cs", **overrides):
    fields = dict(
        hospital_id=hospital_id,
        analysis_code=analysis_code,
        month=month,
        raw_value=25.0,
        previous_value=10.0,
        denominator=100.0,
        rate=25.0,
        raw_value_outlier_score=1.0,
        rate_outlier_score=1.0,
        historical_outlier_score=1.0,
        volume_anomaly_score=0.0,
        outlier_level="VERY_HIGH",
        outlier_type="CLINICAL_INVESTIGATION_REQUIRED",
        outlier_method="pct_change",
        interpretation="Rate and history both exceed their thresholds.",
        investigation_route="clinical",
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def test_layered_endpoint_filters_by_month(db_session, client):
    """Scenario 14: only the requested month comes back."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-05")
    _add_layered(db_session, h.id, "2027-06")

    resp = client.get("/analysis/layered?month=2027-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [row["month"] for row in body["data"]] == ["2027-06"]


def test_layered_endpoint_filters_by_hospital(db_session, client):
    """Scenario 15: only the requested hospital comes back."""
    h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    _add_layered(db_session, h1.id, "2027-06")
    _add_layered(db_session, h2.id, "2027-06")

    resp = client.get(f"/analysis/layered?month=2027-06&hospital={h1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert {row["hospital_id"] for row in body["data"]} == {h1.id}


def test_layered_endpoint_filters_classification_level_and_route(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06")
    _add_layered(db_session, h.id, "2027-06", analysis_code="5",
                 outlier_type="HISTORICAL_ANOMALY", outlier_level="HIGH",
                 investigation_route="contextual")
    _add_layered(db_session, h.id, "2027-06", analysis_code="2",
                 outlier_type="NORMAL", outlier_level="NONE",
                 investigation_route="none")

    resp = client.get("/analysis/layered?month=2027-06&classification=NORMAL")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "2"

    resp = client.get("/analysis/layered?month=2027-06&level=VERY_HIGH")
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "rate_cs"

    resp = client.get("/analysis/layered?month=2027-06&investigation=contextual")
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "5"

    # Display metadata comes from build_analysis_specs — same source the
    # engine persisted with (registry name for rate rows, Indicator name
    # for count rows).
    by_code = {row["analysis_code"]: row
               for row in client.get("/analysis/layered?month=2027-06").json()["data"]}
    assert by_code["rate_cs"]["indicator_name"] == "C-section rate"
    assert by_code["rate_cs"]["indicator_type"] is not None
    ind2 = db_session.query(Indicator).filter_by(code="2").first()
    assert by_code["2"]["indicator_name"] == ind2.name


def test_layered_endpoint_paginates_and_sorts(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06", analysis_code="a", raw_value=10.0)
    _add_layered(db_session, h.id, "2027-06", analysis_code="b", raw_value=30.0)
    _add_layered(db_session, h.id, "2027-06", analysis_code="c", raw_value=20.0)

    page1 = client.get(
        "/analysis/layered?month=2027-06&sort=raw_value&order=asc&page=1&page_size=2"
    ).json()
    assert page1["total"] == 3
    assert page1["page_size"] == 2
    assert [row["analysis_code"] for row in page1["data"]] == ["a", "c"]

    page2 = client.get(
        "/analysis/layered?month=2027-06&sort=raw_value&order=asc&page=2&page_size=2"
    ).json()
    assert [row["analysis_code"] for row in page2["data"]] == ["b"]


def test_layered_summary_counts_classifications_and_hospitals(db_session, client):
    h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    _add_layered(db_session, h1.id, "2027-06")
    _add_layered(db_session, h1.id, "2027-06", analysis_code="5",
                 outlier_type="HISTORICAL_ANOMALY", outlier_level="HIGH",
                 investigation_route="contextual")
    _add_layered(db_session, h2.id, "2027-06",
                 outlier_type="NORMAL", outlier_level="NONE",
                 investigation_route="none")
    _add_layered(db_session, h1.id, "2027-05")

    resp = client.get("/analysis/layered/summary?month=2027-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert {c["outlier_type"]: c["count"] for c in body["by_classification"]} == {
        "CLINICAL_INVESTIGATION_REQUIRED": 1,
        "HISTORICAL_ANOMALY": 1,
        "NORMAL": 1,
    }
    assert {row["hospital_id"]: row["count"] for row in body["by_hospital"]} == {
        h1.id: 2,
        h2.id: 1,
    }
    assert all(row["hospital"] for row in body["by_hospital"])

    all_months = client.get("/analysis/layered/summary").json()
    assert all_months["total"] == 4


def test_outliers_endpoint_includes_layered_classification(db_session, client):
    h = db_session.query(Hospital).first()
    # rate_name "C-section rate" → registry rate_code "rate_cs"; the layered
    # row must be keyed by that code for the join to find it.
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs",
                 outlier_type="CLINICAL_INVESTIGATION_REQUIRED",
                 outlier_level="VERY_HIGH",
                 interpretation="Rate and history both exceed their thresholds.")
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2027-06", indicator_code="5",
        rate_name="C-section rate", value=90.0, benchmark=40.0,
        z_score=3.1, is_outlier=True,
    ))
    db_session.add(AnomalyResult(  # no layered row for this month
        hospital_id=h.id, month="2027-05", indicator_code="5",
        rate_name="C-section rate", value=60.0, benchmark=40.0,
        z_score=2.8, is_outlier=True,
    ))
    db_session.commit()

    resp = client.get("/analysis/outliers")
    assert resp.status_code == 200
    rows = {row["month"]: row for row in resp.json()["data"]}

    joined = rows["2027-06"]
    assert joined["layered_type"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert joined["layered_level"] == "VERY_HIGH"
    assert "threshold" in joined["layered_interpretation"]

    # LEFT JOIN semantics: no layered row → nulls, never a fake classification.
    assert rows["2027-05"]["layered_type"] is None
    assert rows["2027-05"]["layered_level"] is None
    assert rows["2027-05"]["layered_interpretation"] is None


def test_layered_cache_lifecycle_within_a_request_cycle(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs")

    first = client.get("/analysis/layered?month=2027-06").json()
    assert first["total"] == 1

    _add_layered(db_session, h.id, "2027-06", analysis_code="5")
    cached = client.get("/analysis/layered?month=2027-06").json()
    assert cached["total"] == 1  # still cached — the new row is invisible

    # Prefix must include the "v2|" segment make_key() prepends (cache.py:193).
    cache.invalidate("v2|analysis:layered")
    fresh = client.get("/analysis/layered?month=2027-06").json()
    assert fresh["total"] == 2


def test_layered_endpoints_enforce_analysis_read(db_session, client, real_auth):
    perm = db_session.query(Permission).filter_by(codename="analysis.read").first()
    if perm is None:
        perm = Permission(codename="analysis.read")
        db_session.add(perm)
        db_session.flush()

    reader_role = Role(name="layered_reader")
    reader_role.permissions.append(perm)
    db_session.add(reader_role)
    db_session.add_all([
        User(username="layered_noperm", email="layered_np@test.local",
             full_name="No Perm", password_hash=hash_password("test123")),
        User(username="layered_reader", email="layered_r@test.local",
             full_name="Reader", password_hash=hash_password("test123"),
             roles=[reader_role]),
    ])
    db_session.commit()

    no_perm_token = _login(client, "layered_noperm")
    resp = client.get("/analysis/layered",
                      headers={"Authorization": f"Bearer {no_perm_token}"})
    assert resp.status_code == 403
    resp = client.get("/analysis/layered/summary",
                      headers={"Authorization": f"Bearer {no_perm_token}"})
    assert resp.status_code == 403

    ok_token = _login(client, "layered_reader")
    resp = client.get("/analysis/layered",
                      headers={"Authorization": f"Bearer {ok_token}"})
    assert resp.status_code == 200
    assert "data" in resp.json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_api.py -v`

Expected: all FAIL — `/analysis/layered` and `/analysis/layered/summary` do not exist yet (404 where 200 is asserted, 404 where 403 is asserted), and the outliers-join test dies on `KeyError: 'layered_type'`. Collection itself must succeed (the `LayeredOutlierResult` model exists from Task 6).

- [ ] **Step 3: Implement the endpoints and the outliers join**

**3a.** In the models import block (analysis.py:27-36), add `LayeredOutlierResult` (keeps the block alphabetical — `IndicatorValue < LayeredOutlierResult < QualityScore`):

```python
from app.models import (
    AnomalyResult,
    Hospital,
    HospitalIndicatorConfig,
    Indicator,
    IndicatorDefaultConfig,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    ValidationResult,
)
```

**3b.** analysis.py:8 gains `func` (used by the summary group-by):

```python
from sqlalchemy import case, func, or_
```

**3c.** Insert the two new endpoints between `list_outliers`'s final `return result` and `@router.get("/ml")` (analysis.py:405-408):

```python
    result = {"total": total, "skip": skip, "limit": limit, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/layered")
def list_layered(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital: Optional[int] = Query(None, description="Filter by hospital ID"),
    indicator: Optional[str] = Query(None, description="Filter by analysis code (indicator or rate code)"),
    classification: Optional[str] = Query(None, description="Filter by outlier_type"),
    level: Optional[str] = Query(None, description="Filter by outlier_level (NONE..VERY_HIGH)"),
    investigation: Optional[str] = Query(None, description="Filter by investigation_route (none|data_quality|clinical|contextual)"),
    sort: str = Query("month", description="Sort key: month | level | type | raw_value | rate | denominator"),
    order: str = Query("desc", description="Sort direction: asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Persisted layered-outlier rows, paged (design spec 2026-10-08 §8.1)."""
    from app.engine.anomaly.layered import LEVELS, build_analysis_specs

    cache_key = cache.make_key(
        "analysis:layered_v1",
        month=month,
        hospital=hospital,
        indicator=indicator,
        classification=classification,
        level=level,
        investigation=investigation,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .options(selectinload(LayeredOutlierResult.hospital))
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)
    if hospital:
        query = query.filter(LayeredOutlierResult.hospital_id == hospital)
    if indicator:
        query = query.filter(LayeredOutlierResult.analysis_code == indicator)
    if classification:
        query = query.filter(LayeredOutlierResult.outlier_type == classification)
    if level:
        query = query.filter(LayeredOutlierResult.outlier_level == level)
    if investigation:
        query = query.filter(LayeredOutlierResult.investigation_route == investigation)

    total = query.count()

    sort_columns = {
        "month": LayeredOutlierResult.month,
        "raw_value": LayeredOutlierResult.raw_value,
        "rate": LayeredOutlierResult.rate,
        "denominator": LayeredOutlierResult.denominator,
        "type": LayeredOutlierResult.outlier_type,
        # Rank NONE < LOW < MODERATE < HIGH < VERY_HIGH for ordering.
        "level": case({name: i for i, name in enumerate(LEVELS)}, value=LayeredOutlierResult.outlier_level),
    }
    sort_column = sort_columns.get(sort, LayeredOutlierResult.month)
    direction = sort_column.asc() if order == "asc" else sort_column.desc()
    rows = (
        query.order_by(direction, LayeredOutlierResult.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    spec_meta = {spec.analysis_code: (spec.name, spec.indicator_type)
                 for spec in build_analysis_specs(db)}
    output = []
    for r in rows:
        row = {c.name: getattr(r, c.name) for c in LayeredOutlierResult.__table__.columns}
        row.pop("created_at", None)
        name, itype = spec_meta.get(r.analysis_code, (None, None))
        row["hospital"] = r.hospital.name if r.hospital else "Unknown"
        row["indicator_name"] = name
        row["indicator_type"] = itype
        output.append(row)

    result = {"total": total, "page": page, "page_size": page_size, "data": output}
    cache.set(cache_key, result)
    return result


@router.get("/layered/summary")
def layered_summary(
    month: Optional[str] = Query(None, description="Month YYYY-MM (all months when omitted)"),
    db: Session = Depends(get_db),
):
    """Classification counts + per-hospital rollup for the Layered tab chips
    (design spec 2026-10-08 §8.2)."""
    cache_key = cache.make_key("analysis:layered_summary_v1", month=month)
    cached = cache.get(cache_key)
    if cached:
        return cached

    query = (
        db.query(LayeredOutlierResult)
        .join(Hospital, LayeredOutlierResult.hospital_id == Hospital.id)
        .filter(Hospital.is_active.is_(True))
    )
    if month:
        query = query.filter(LayeredOutlierResult.month == month)

    groups = (
        query.with_entities(
            LayeredOutlierResult.hospital_id,
            LayeredOutlierResult.outlier_type,
            func.count(LayeredOutlierResult.id),
        )
        .group_by(LayeredOutlierResult.hospital_id, LayeredOutlierResult.outlier_type)
        .all()
    )

    by_classification = {}
    by_hospital_counts = {}
    total = 0
    for hosp_id, otype, count in groups:
        count = int(count)
        total += count
        otype = otype or "UNKNOWN"
        by_classification[otype] = by_classification.get(otype, 0) + count
        by_hospital_counts[hosp_id] = by_hospital_counts.get(hosp_id, 0) + count

    hospital_names = {}
    if by_hospital_counts:
        hospital_names = dict(
            db.query(Hospital.id, Hospital.name)
            .filter(Hospital.id.in_(by_hospital_counts))
            .all()
        )

    result = {
        "month": month,
        "total": total,
        "by_classification": [
            {"outlier_type": t, "count": c}
            for t, c in sorted(by_classification.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_hospital": [
            {"hospital_id": hid, "hospital": hospital_names.get(hid, "Unknown"), "count": c}
            for hid, c in sorted(by_hospital_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
    cache.set(cache_key, result)
    return result


@router.get("/ml")
```

**3d.** Outliers cache key bump (analysis.py:362) — the cached payload shape changed:

```python
    # v4: layered_type/layered_level/layered_interpretation added below — a
    # cached v3 payload would hide the classification column for up to 24h.
    cache_key = cache.make_key("analysis:outliers_v4", month=month, hospital_id=hospital_id, rate_name=rate_name, skip=skip, limit=limit)
```

**3e.** Outliers join — replace everything from `total = query.count()` through the closing `})` of the output dict (analysis.py:378-402):

```python
    total = query.count()
    results = query.order_by(AnomalyResult.z_score.desc()).offset(skip).limit(limit).all()

    layered_by_key = {}
    rate_code_by_name = {}
    if results:
        from app.engine.rate_config import load_rate_specs

        rate_code_by_name = {spec.rate_name: spec.rate_code for spec in load_rate_specs(db)}
        layered_rows = (
            db.query(LayeredOutlierResult)
            .filter(
                LayeredOutlierResult.hospital_id.in_({r.hospital_id for r in results}),
                LayeredOutlierResult.month.in_({r.month for r in results}),
            )
            .all()
        )
        layered_by_key = {
            (lr.hospital_id, lr.month, lr.analysis_code): lr for lr in layered_rows
        }

    output = []
    for r in results:
        hosp = r.hospital
        layered_code = rate_code_by_name.get(r.rate_name) or r.indicator_code
        lr = layered_by_key.get((r.hospital_id, r.month, layered_code))
        output.append({
            "id": r.id,
            "hospital_id": r.hospital_id,
            "hospital": hosp.name if hosp else "Unknown",
            "month": r.month,
            "indicator_code": r.indicator_code,
            "rate_name": r.rate_name,
            "value": r.value,
            "benchmark": r.benchmark,
            "z_score": r.z_score,
            "is_outlier": r.is_outlier,
            # Peer metadata — same numbers the audit benchmark screen shows
            # (NULL for trend rows / rows computed before this field existed).
            "peer_count": r.peer_count,
            "peer_std": r.peer_std,
            "peer_min": r.peer_min,
            "peer_max": r.peer_max,
            "peer_median": r.peer_median,
            "peers_detail": r.peers_detail,
            # Layered classification (application-level LEFT JOIN — None when
            # no layered row exists for this hospital/month/analysis unit).
            "layered_type": lr.outlier_type if lr else None,
            "layered_level": lr.outlier_level if lr else None,
            "layered_interpretation": lr.interpretation if lr else None,
        })
```

The two-query shape is deliberate: the `rate_name → analysis_code` translation runs through the registry, so a SQL LEFT JOIN on `(hospital_id, month)` alone would mis-attach rows and a join on a computed key is impossible. The `.in_` pair filters may pull a few extra cross-month/cross-hospital rows — harmless, the lookup key is exact.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_api.py tests/test_anomaly.py tests/test_reanalyze_permissions.py -v`

Expected: all PASS. `test_anomaly.py` guards the modified `/analysis/outliers` payload (its assertions are subset-style, so the three new keys are additive), `test_reanalyze_permissions.py` guards the router-level permission the new routes inherit.

- [ ] **Step 5: Lint and commit**

`app/api/analysis.py` passes ruff cleanly today (verified before this task), so no `--fix` pass — any finding here is from the new code:

```bash
.venv\Scripts\ruff.exe check app/api/analysis.py tests/test_layered_api.py
```

Expected: `All checks passed!`

```bash
git add app/api/analysis.py tests/test_layered_api.py
git commit -m "feat(layered): add layered analysis endpoints and outliers classification join"
```

---

### Task 15: Explain — `kind=layered_outlier` payload and dispatcher branch

**Files:**
- Modify: `app/engine/audit/explain.py`
- Modify: `app/api/audit.py`
- Modify: `tests/test_layered_api.py`

**Interfaces:**
- Consumes (Tasks 6, 7, 11, 12, 13): the persisted `LayeredOutlierResult` row (layer scores, `historical_change_percent`, `investigation_route`, `interpretation`, `outlier_method`), `build_analysis_specs(db)` → `{analysis_code: AnalysisSpec}`, `prior_months` / `level_for_score` / `LEVEL_NONE` (`app/engine/anomaly/layered.py`, plan :1849/:2308), `get_historical_months` (`app/engine/pipeline.py:262`), `classify_layered` (pure re-run, plan :3365), `RULE2_MIN_CHANGE_PERCENT`.
- Produces (Tasks 16, 17): `GET /audit/explain?kind=layered_outlier&hospital_id=…&month=…&indicator_code=<analysis_code>` returning the spec §9 payload; `rule_number`, `layers` and `reproduce` feed the Why popup for both the Outliers classification badge and the Layered tab.

**Context:**
- Spec §8.4 + §9: one dispatcher branch + one function; the payload reuses the `what/where/why/how/reproduce/chain/classification` contract. `static/js/explain.js` already wires it with **zero client changes**: the object form of `showWhyPopup` (explain.js:373-379) forwards `indicatorCode` and the query builder already appends `&indicator_code=` (explain.js:336) — callers simply pass `{kind: 'layered_outlier', hospitalId, month, indicatorCode: analysis_code}`.
- No new API parameter: for this kind the analysis unit rides on the existing `indicator_code` (documented in the dispatcher comment). Any `{"error": …}` return already becomes HTTP 404 (audit.py:51-52), so missing row / missing spec / missing code all 404 without touching the API layer — the only `app/api/audit.py` edit is the `kind` Query description (audit.py:20).
- The **row is the source of truth** (type, level, route, interpretation — exactly what the dashboards show). `rule_number` is the one thing not persisted, so it is recovered by re-running the pure `classify_layered` (plan :3365) over the stored scores; `raw_method`/`rate_method`/`hist_method`/`numbers` take their defaults and the returned `method`/`interpretation` are discarded. `verified = recomputed type AND level match the row`; on mismatch the payload sets `rule_number=None` and says "recalculate this month" — never invent a rule for a stale row (ghost doctrine).
- The re-run uses the exact inputs the engine used: `history_ok = len(prior_months(get_historical_months(db, hospital_id, month), month)) >= spec.minimum_history_period` (pipeline.py:262 excludes the current month; split + threshold mirror plan :3767-3769), `den_ok` mirrors plan :3778-3796 (rate rows: stored denominator not None and > 0; count rows: True), `change_percent` = stored `historical_change_percent` (percent vs baseline mean — the classify call at plan :3823-3838; the percent vs previous month is derived fresh for display).
- Spec lookup goes through `build_analysis_specs(db)` — the same source the engine and the Task 14 endpoints use, so `rate_cs` resolves to "C-section rate" without a second rate-config read path.
- §9's dashboard block (spec :309-320) becomes the structured `layers` array (raw → rate → historical → volume → peer, each with `key`/`name`/`value`/`score`/`level`/`detail`); the anomaly payload already carries extra keys beyond the contract (explain.py:707-710), so `layers`, `rule_number`, `outlier_level`, `investigation_route`, `investigation_required` are render-safe additions for explain.js.
- Per-layer detection methods are not persisted (only the fired rule's method is, as `outlier_method`), so the payload reports `spec.outlier_method` under `how.thresholds` and the recorded rule method inside `how.inputs.recorded_method` plus the chain — no fabricated per-layer numbers.
- Lint baseline (verified): `app/api/audit.py` has a pre-existing `I001`; `app/engine/audit/explain.py` has a pre-existing `F401` (unused `numpy` at :1098) plus 3 pre-existing `B905` (`zip()` without `strict=` at :1573/:1576/:1593) — same situation Task 13 fixed for `pipeline.py`: clean them in this task so both files gate on `All checks passed!`.

- [ ] **Step 1: Write the failing tests**

Two edits to `tests/test_layered_api.py`.

**Edit 1 — add `IndicatorValue` to the models import** (history seeding for the contract test):

```python
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    LayeredOutlierResult,
    Permission,
    Role,
    User,
)
```

becomes

```python
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    Permission,
    Role,
    User,
)
```

**Edit 2 — append after the last test** (anchor: the permission test's closing `assert "data" in resp.json()` and the fence that follows it):

```python
# ───────────────────────── explain (kind=layered_outlier) ─────────────────────

def _add_history_values(db, hospital_id, months, code="2", value=100.0):
    """Prior-month values so get_historical_months finds a real baseline."""
    ind = db.query(Indicator).filter(Indicator.code == str(code)).first()
    assert ind is not None, f"seeded indicator {code} missing"
    for m in months:
        db.add(IndicatorValue(
            hospital_id=hospital_id, indicator_id=ind.id, month=m, value=value,
        ))
    db.commit()


def test_explain_layered_outlier_contract(db_session, client):
    """Spec §9: full contract payload; stored scores + current history
    reproduce rule 4's clinical classification."""
    h = db_session.query(Hospital).first()
    _add_history_values(db_session, h.id, ["2027-03", "2027-04", "2027-05"])
    _add_layered(db_session, h.id, "2027-06")

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "layered_outlier"
    assert p["data_epoch"]
    for key in ("what", "where", "why", "how", "reproduce", "chain", "classification"):
        assert key in p, f"contract key {key!r} missing"
    assert p["what"]
    assert p["classification"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert p["where"]["analysis_code"] == "rate_cs"
    assert p["where"]["indicator_name"] == "C-section rate"
    # Full-precision inputs behind every displayed number.
    inputs = p["how"]["inputs"]
    assert inputs["raw_value"] == 25.0
    assert inputs["raw_change_percent"] == 150.0
    assert inputs["denominator"] == 100.0
    assert inputs["scores"]["rate"] == 1.0
    assert inputs["scores"]["volume"] == 0.0
    assert p["how"]["thresholds"]["minimum_history_period"] == 3
    # 3 prior months >= minimum_history_period → history_ok; the re-run over
    # the stored scores reproduces rule 4 (rate HIGH + history HIGH + volume LOW).
    assert p["reproduce"]["history_ok"] is True
    assert p["reproduce"]["verified"] is True
    assert p["rule_number"] == 4
    # §9 dashboard block: one entry per layer, engine order.
    assert [lay["key"] for lay in p["layers"]] == ["raw", "rate", "historical", "volume", "peer"]
    assert p["layers"][2]["score"] == 1.0 and p["layers"][2]["level"] == "VERY_HIGH"
    # The stored interpretation is the conclusion paragraph.
    assert "Rate and history both exceed their thresholds." in p["why"]
    assert any("/analysis/layered" in (n.get("endpoint") or "") for n in p["chain"])


def test_explain_layered_outlier_missing_row_404s(db_session, client):
    h = db_session.query(Hospital).first()

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 404
    assert "layered outlier row" in resp.json()["detail"]

    # The analysis unit travels on the existing indicator_code parameter.
    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}&month=2027-06"
    )
    assert resp.status_code == 404
    assert "indicator_code" in resp.json()["detail"]


def test_explain_layered_outlier_flags_changed_history(db_session, client):
    """Row written under a different history → honest 'recalculate' note,
    stored classification still displayed, no invented rule number."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06")     # no IndicatorValue history

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["classification"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert p["reproduce"]["history_ok"] is False
    assert p["reproduce"]["verified"] is False
    assert p["rule_number"] is None
    assert "recalculate" in p["why"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_api.py -v`

Expected: the 8 Task 14 tests still PASS; the 3 new tests FAIL — the dispatcher has no branch yet and falls through to `Unknown explanation kind: 'layered_outlier'` → 404, so the contract test dies on `assert resp.status_code == 200`.

- [ ] **Step 3: Implement the dispatcher branch and the payload**

**3a — add the model to the import** (explain.py:45-53, alphabetical placement):

```python
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    Rule,
    ValidationResult,
)
```

**3b — dispatcher branch** (explain.py:1697 — insert between the `kind == "anomaly"` and `kind == "heatmap_cell"` branches):

```python
    if kind == "anomaly":
        return explain_anomaly(db, hospital_id, month, rate_name=rate_name, indicator_code=indicator_code)
    if kind == "layered_outlier":
        # The analysis unit rides on indicator_code for this kind — no new
        # query param (spec §8.4: extend the dispatcher, not the API).
        if not indicator_code:
            return {"error": "kind=layered_outlier requires indicator_code (the row's analysis_code)"}
        return explain_layered_outlier(db, hospital_id, month, indicator_code)
    if kind == "heatmap_cell":
```

**3c — the payload function** (explain.py — place after `explain_trend_row`'s closing `}` at :1660, immediately before `def build_explanation(` at :1662):

```python
def explain_layered_outlier(db: Session, hospital_id: int, month: str,
                            analysis_code: str) -> dict:
    """Layered-outlier row explanation (design spec §9).

    The persisted row is the source of truth for type/level/route/
    interpretation — exactly what the dashboards show. The rule NUMBER is
    not persisted, so it is recovered by re-running the pure classification
    function over the stored layer scores; when the re-run no longer matches
    the row (history changed since the analysis ran) the payload says so
    instead of inventing a rule."""
    from app.engine.anomaly.classify import (RULE2_MIN_CHANGE_PERCENT,
                                             classify_layered)
    from app.engine.anomaly.layered import (LEVEL_NONE, build_analysis_specs,
                                            level_for_score, prior_months)
    from app.engine.pipeline import get_historical_months

    row = (
        db.query(LayeredOutlierResult)
        .filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.month == month,
            LayeredOutlierResult.analysis_code == analysis_code,
        )
        .first()
    )
    if row is None:
        return {"error": (f"No layered outlier row for hospital {hospital_id}, "
                          f"{month}, {analysis_code!r}")}

    spec = build_analysis_specs(db).get(analysis_code)
    if spec is None:
        return {"error": f"Unknown analysis code: {analysis_code!r}"}

    hosp = _hospital(db, hospital_id)

    # Same pair, same threshold the engine used (prior_months splits off the
    # current month; get_historical_months excludes it — plan Task 12).
    history = get_historical_months(db, hospital_id, month)
    prior = prior_months(history, month)
    history_ok = len(prior) >= spec.minimum_history_period
    den_ok = (row.denominator is not None and row.denominator > 0) if spec.is_rate else True

    recomputed = classify_layered(
        spec,
        raw_score=row.raw_value_outlier_score,
        rate_score=row.rate_outlier_score,
        hist_score=row.historical_outlier_score,
        volume_score=row.volume_anomaly_score,
        peer_score=row.peer_outlier_score,
        den_ok=den_ok,
        history_ok=history_ok,
        change_percent=row.historical_change_percent,
        denominator=row.denominator,
    )
    verified = (recomputed.outlier_type == row.outlier_type
                and recomputed.outlier_level == row.outlier_level)
    rule_number = recomputed.rule_number if verified else None

    raw_change_percent = None
    if row.raw_value is not None and row.previous_value:
        raw_change_percent = ((float(row.raw_value) - float(row.previous_value))
                              / float(row.previous_value) * 100.0)
    den_change_percent = None
    if spec.is_rate and row.denominator is not None and row.previous_denominator:
        den_change_percent = ((float(row.denominator) - float(row.previous_denominator))
                              / float(row.previous_denominator) * 100.0)
    rate_change_percent = None
    if spec.is_rate and row.rate is not None and row.previous_value is not None and row.previous_denominator:
        previous_rate = float(row.previous_value) / float(row.previous_denominator) * spec.rate_multiplier
        if previous_rate:
            rate_change_percent = (float(row.rate) - previous_rate) / previous_rate * 100.0

    inputs = {
        "raw_value": row.raw_value,
        "previous_value": row.previous_value,
        "raw_change_percent": raw_change_percent,
        "rate": row.rate,
        "rate_change_percent": rate_change_percent,
        "denominator": row.denominator,
        "previous_denominator": row.previous_denominator,
        "denominator_change_percent": den_change_percent,
        "historical_mean": row.historical_mean,
        "historical_median": row.historical_median,
        "historical_std": row.historical_std,
        "historical_z_score": row.historical_z_score,
        "historical_change_percent": row.historical_change_percent,
        "peer_mean": row.peer_mean,
        "peer_count": row.peer_count,
        "recorded_method": row.outlier_method,
        "scores": {
            "raw": row.raw_value_outlier_score,
            "rate": row.rate_outlier_score,
            "historical": row.historical_outlier_score,
            "volume": row.volume_anomaly_score,
            "peer": row.peer_outlier_score,
        },
    }

    if spec.is_rate:
        num = " + ".join(spec.numerator_codes)
        den = " + ".join(spec.denominator_codes)
        formula = f"({num}) / ({den}) × {spec.rate_multiplier:g}"
        formula_readable = f"{spec.name} = ({num}) / ({den}) × {spec.rate_multiplier:g}"
    else:
        formula = f"count({analysis_code})"
        formula_readable = f"{spec.name} = count of indicator {analysis_code}"

    def _layer(key, name, value, score, detail):
        return {
            "key": key,
            "name": name,
            "value": value,
            "score": score,
            "level": LEVEL_NONE if score is None else level_for_score(score),
            "detail": detail,
        }

    if row.raw_value is None:
        raw_value_text = "not computable"
    elif row.previous_value:
        raw_value_text = (f"{row.raw_value:g} (previous {row.previous_value:g}, "
                          f"{raw_change_percent:+.1f}%)")
    else:
        raw_value_text = f"{row.raw_value:g}"

    if not spec.is_rate:
        rate_value_text = "not applicable (count indicator)"
        volume_value_text = "not applicable (count indicator)"
    elif row.rate is None or not den_ok:
        rate_value_text = "not computable (denominator missing or zero)"
        volume_value_text = "not computable (denominator missing or zero)"
    else:
        rate_value_text = f"{row.rate:g}{(' ' + spec.unit) if spec.unit else ''}"
        if row.previous_denominator and den_change_percent is not None:
            volume_value_text = (f"{row.denominator:g} (previous "
                                 f"{row.previous_denominator:g}, {den_change_percent:+.1f}%)")
        else:
            volume_value_text = f"{row.denominator:g}"

    if row.historical_mean is None:
        historical_value_text = "insufficient history"
    elif row.historical_change_percent is not None:
        historical_value_text = (f"{row.historical_change_percent:+.1f}% vs baseline "
                                 f"mean {row.historical_mean:g}")
    else:
        historical_value_text = f"{row.historical_mean:g}"

    if row.peer_mean is not None and row.peer_count:
        peer_value_text = f"{row.peer_mean:g} across {row.peer_count} peer hospitals"
    else:
        peer_value_text = "no peer tier with at least 2 hospitals"

    layers = [
        _layer("raw", "Raw value", raw_value_text, row.raw_value_outlier_score,
               "this month's analysis value vs its own recent distribution"),
        _layer("rate", "Rate", rate_value_text, row.rate_outlier_score,
               "rate vs its own recent distribution" if spec.is_rate
               else "count indicators have no separate rate layer"),
        _layer("historical", "Historical baseline", historical_value_text,
               row.historical_outlier_score,
               f"{len(prior)} prior months against a {spec.minimum_history_period}-month minimum"),
        _layer("volume", "Patient volume", volume_value_text, row.volume_anomaly_score,
               "denominator change guards against volume-driven spikes" if spec.is_rate
               else "count indicators have no denominator layer"),
        _layer("peer", "Peer comparison", peer_value_text, row.peer_outlier_score,
               "first tier (type → ownership → governorate → all) with ≥ 2 hospitals"),
    ]

    if row.raw_value is not None and raw_change_percent is not None:
        what = (f"{spec.name} {row.raw_value:g} vs {row.previous_value:g} previous "
                f"({raw_change_percent:+.0f}%) — {row.outlier_type} "
                f"({row.outlier_level} level)")
    else:
        what = f"{spec.name} — {row.outlier_type} ({row.outlier_level} level)"

    if verified and rule_number is not None:
        why = (f"Rule {rule_number} of the layered rule table fired → "
               f"{row.outlier_type}. {row.interpretation}")
    else:
        why = ("The stored classification no longer matches the current history "
               f"(recomputed: {recomputed.outlier_type}) — recalculate this month. "
               f"Stored interpretation: {row.interpretation}")

    reproduce = {
        "inputs": inputs,
        "history_ok": history_ok,
        "history_months": len(prior),
        "rule_number": rule_number,
        "recomputed_type": recomputed.outlier_type,
        "recomputed_level": recomputed.outlier_level,
        "verified": verified,
        "note": ("Stored layer scores and the current history reproduce the "
                 "stored classification."
                 if verified else
                 "Re-running the rule table over the stored scores with the "
                 "CURRENT history gives a different result — the history "
                 "changed since this row was written; recalculate this month."),
    }

    return {
        "kind": "layered_outlier",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": what,
        "where": {
            "hospital_id": hospital_id,
            "hospital": hosp.name if hosp else str(hospital_id),
            "month": month,
            "analysis_code": analysis_code,
            "indicator_name": spec.name,
            "indicator_type": spec.indicator_type,
            "outlier_type": row.outlier_type,
        },
        "why": why,
        "how": {
            "formula": formula,
            "formula_readable": formula_readable,
            "thresholds": {
                "peer_z_threshold": _zscore_threshold(db),
                "minimum_history_period": spec.minimum_history_period,
                "minimum_denominator": spec.minimum_denominator,
                "outlier_method": spec.outlier_method,
                "rule2_min_change_percent": RULE2_MIN_CHANGE_PERCENT,
            },
            "inputs": inputs,
        },
        "reproduce": reproduce,
        "classification": row.outlier_type,
        "outlier_level": row.outlier_level,
        "investigation_required": bool(row.investigation_required),
        "investigation_route": row.investigation_route,
        "rule_number": rule_number,
        "layers": layers,
        "chain": [
            {"step": "Source Data",
             "detail": f"Uploaded indicator values for {month}",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Layer computation",
             "detail": ("raw → rate/volume → historical → peer "
                        f"(recorded method: {row.outlier_method})"),
             "endpoint": f"/audit/benchmark/{hospital_id}?month={month}"},
            {"step": "Classification",
             "detail": (f"Rule {rule_number if rule_number is not None else '—'}: "
                        f"{row.outlier_type} at {row.outlier_level}, route "
                        f"{row.investigation_route}"),
             "endpoint": f"/analysis/outliers?hospital_id={hospital_id}&month={month}"},
            {"step": "Finding",
             "detail": f"layered_outlier_results row #{row.id}",
             "endpoint": f"/analysis/layered?hospital={hospital_id}&month={month}"},
        ],
    }
```

**3d — kind list** (audit.py:20 — insert `layered_outlier` after `anomaly`):

```python
    kind: str = Query(..., description="quality_score | anomaly | layered_outlier | heatmap_cell | rule | comparison_row | historical_trend | governorate_row | indicator_aggregate | ranking_entry | time_period_point | trend_row"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_api.py tests/test_explain.py -v`

Expected: all PASS. `test_explain.py` is the dispatcher regression suite (unknown kinds still 404, contract keys unchanged for every other kind), and the 8 Task 14 endpoint tests must stay green.

- [ ] **Step 5: Lint and commit**

Pre-existing findings in the two modified files (verified above): `I001` in `app/api/audit.py`; `F401` + 3× `B905` in `app/engine/audit/explain.py`. Auto-fix what ruff can, then the three `zip()` lines by hand (`strict=False` is exactly today's default — behavior-neutral):

```bash
.venv\Scripts\ruff.exe check --fix app/api/audit.py app/engine/audit/explain.py
```

Manual edits (B905 is not auto-fixable), in `app/engine/audit/explain.py`:

```python
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, vals, strict=False)) / sum((xi - mx) ** 2 for xi in x)
```

```python
    ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, vals, strict=False))
```

```python
        for m, v in zip(row.months, vals, strict=False)
```

Then the gate:

```bash
.venv\Scripts\ruff.exe check app/engine/audit/explain.py app/api/audit.py tests/test_layered_api.py
```

Expected: `All checks passed!`

```bash
git add app/engine/audit/explain.py app/api/audit.py tests/test_layered_api.py
git commit -m "feat(layered): add layered_outlier explain payload with rule reproduction"
```

---

### Task 16: Outliers tab — classification column with typed badges

**Files:**
- Modify: `static/tabs/outliers.html`
- Modify: `static/js/outliers.js`
- Modify: `static/css/styles.css`
- Modify: `static/js/i18n.js`
- Create: `tests/test_layered_ui.py`

**Interfaces:**
- Consumes (Task 14): every `GET /analysis/outliers` row carries `layered_type` / `layered_level` / `layered_interpretation` (the application-level join; `None` when the row has no layered counterpart).
- Produces (Task 17): `export function classificationBadge(type, interpretation)` from `outliers.js` — the Layered tab imports it so both tabs render the identical badge (no copy-paste drift).

**Context:**
- Spec §10A: Classification column from `layered_type`, colored badge per type — `POSSIBLE_DATA_ENTRY_ERROR` red, `CLINICAL_INVESTIGATION_REQUIRED` orange, `PEER_ANOMALY` blue, `VOLUME_DRIVEN_ANOMALY` amber, `NORMAL`/unmatched gray — with `title` tooltip = the one-line interpretation. Existing Z-badge, peers popover and Why button stay untouched.
- Unmatched (no layered row → all three keys `None`) renders a gray `--` badge — grouped with NORMAL exactly as spec §10A says, and never coerced to `NORMAL` (ghost doctrine: a missing joined row is missing, not a verdict). The badge label is the raw type constant: that is this codebase's badge idiom (severity `CRITICAL`, rule_type `LOGIC` are shown raw) and keeps the label byte-identical to the API and the spec.
- Sorting is free: the header click path is `wireOutlierSort` → generic `sortTableRows` (outliers.js:359-372), which maps `data-col` to the header index and sorts by `textContent` (numeric-aware, then `localeCompare`) — a `class="sortable" data-col="layered_type"` `<th>` needs no new JS.
- Colors: the existing palette covers red/orange/blue (`badge-critical`/`badge-medium`/`badge-low`, styles.css:184-186); amber and gray do not exist yet → two new classes appended to the badge block (:180-189). Spec enumerates five buckets; the engine's other types (`HISTORICAL_ANOMALY`, `RAW_VALUE_ANOMALY`, `RATE_ANOMALY`) fall to the gray default — the label text stays fully readable and no color promises an investigation the spec did not define.
- The Why button keeps opening the **anomaly** explanation (`showWhyPopup('anomaly', …)`, outliers.js:208) per §10A "Why button unchanged"; the Task 15 layered payload is reached from the Layered tab's Why (Task 17), and the badge tooltip carries the persisted interpretation without any popup change.
- The three `colspan="9"` sites (loading :139, error :149, empty :189) grow to 10; every other colspan in the file is `8` (rule-failures table), so a replace of `colspan="9"` hits exactly those three lines.
- CSV export is additive: one `Classification` header + `d.layered_type` cell appended — existing columns untouched (their tests assert membership, not counts).
- The badge `title` is built with `esc()` from `tree.js` and the file contains no literal tabs, so `test_outliers_js.py`'s `"\ttitle=" not in js` guard (native row tooltip ban) stays green.
- i18n: English IS the key (ar map only); no `'Classification'` key exists yet (verified) — insert into the `// Outliers Tab` section of i18n.js (:337-349).
- Test idiom mirrors `tests/test_outliers_js.py` (spec §11: `test_layered_ui.py` mirrors it) — pure file-content assertions; Task 17 appends the tab-registration tests to this same file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_layered_ui.py`:

```python
"""Static tests for the layered classification UI (design spec 2026-10-08 §10A/§10B).

Outliers-tab classification column first; the Layered tab (§10B) appends its
tab-registration tests here. Mirrors the test_outliers_js.py idiom: the tabs
are plain HTML/JS, so the contract lives in the file contents."""
import os


def _read(*parts):
    path = os.path.join(os.path.dirname(__file__), "..", "static", *parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_outliers_table_has_classification_column_before_why():
    html = _read("tabs", "outliers.html")
    assert 'data-col="layered_type"' in html
    assert html.index('data-col="layered_type"') < html.index('data-i18n="Why"')
    # Column header + legend entry both carry the i18n key.
    assert html.count('data-i18n="Classification"') >= 2


def test_classification_badge_colors_follow_spec():
    """Spec §10A: red / orange / blue / amber, gray for NORMAL + unmatched."""
    js = _read("js", "outliers.js")
    assert "export function classificationBadge" in js
    for type_name, css_class in (
        ("POSSIBLE_DATA_ENTRY_ERROR", "badge-critical"),
        ("CLINICAL_INVESTIGATION_REQUIRED", "badge-medium"),
        ("PEER_ANOMALY", "badge-low"),
        ("VOLUME_DRIVEN_ANOMALY", "badge-amber"),
    ):
        assert type_name in js, type_name
        assert css_class in js, css_class
    assert "badge-muted" in js                      # NORMAL / unmatched / other
    assert "layered_type" in js and "layered_interpretation" in js


def test_outliers_colspan_grew_to_ten_columns():
    js = _read("js", "outliers.js")
    assert js.count('colspan="9"') == 0
    assert js.count('colspan="10"') == 3            # loading, error, empty rows


def test_outliers_csv_carries_classification():
    js = _read("js", "outliers.js")
    assert "'Classification'" in js
    assert "d.layered_type" in js


def test_outliers_why_button_still_opens_anomaly_explanation():
    """Spec §10A: the Why button is unchanged — classification rides in the
    badge tooltip (the one-line interpretation), not in a new popup path."""
    js = _read("js", "outliers.js")
    assert "showWhyPopup(\\'anomaly\\'" in js


def test_classification_badge_styles_exist():
    css = _read("css", "styles.css")
    assert ".badge-amber" in css
    assert ".badge-muted" in css


def test_classification_label_is_translated():
    i18n = _read("js", "i18n.js")
    assert "'Classification': '" in i18n
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_ui.py -v`

Expected: all FAIL — no `data-col="layered_type"`, no `classificationBadge`, still three `colspan="9"`, no `.badge-amber`/`.badge-muted`, no i18n key. `test_outliers_why_button_still_opens_anomaly_explanation` already PASSES (unchanged code).

- [ ] **Step 3: Implement the column**

**3a — header + legend** (`static/tabs/outliers.html`).

Edit A — add the `<th>` between Peer Range and Why (:48-49):

```html
                                    <th class="sortable" data-col="peer_range" data-i18n="Peer Range">Peer Range</th>
                                    <th class="sortable" data-col="layered_type" data-i18n="Classification">Classification</th>
                                    <th data-i18n="Why">Why</th>
```

Edit B — append the legend entry after the Z-Score line (:17):

```html
                            <div><strong data-i18n="Z-Score">Z-Score</strong> <span data-i18n="— how many standard deviations the value sits from the benchmark mean. |z| ≥ 2 = unusual, |z| ≥ 3 = severe outlier.">— how many standard deviations the value sits from the benchmark mean. |z| ≥ 2 = unusual, |z| ≥ 3 = severe outlier.</span></div>
                            <div><strong data-i18n="Classification">Classification</strong> <span data-i18n="— layered verdict for this row (raw value → rate → history → volume → peer layers); an outlier alone is never proof of a data error.">— layered verdict for this row (raw value → rate → history → volume → peer layers); an outlier alone is never proof of a data error.</span></div>
```

**3b — badge helper, row cell, colspans, CSV** (`static/js/outliers.js`).

Edit C — export the badge builder just above the `// ── Outliers Tab` section header (:130), so Task 17 can import it:

```js
        // Spec §10A: classification badge colors. Gray covers NORMAL, the
        // unmatched case (no layered row) and the types the spec does not
        // enumerate; the tooltip is the one-line interpretation persisted
        // with the row.
        export function classificationBadge(type, interpretation) {
            const cls = type === 'POSSIBLE_DATA_ENTRY_ERROR' ? 'badge-critical'
                : type === 'CLINICAL_INVESTIGATION_REQUIRED' ? 'badge-medium'
                : type === 'PEER_ANOMALY' ? 'badge-low'
                : type === 'VOLUME_DRIVEN_ANOMALY' ? 'badge-amber'
                : 'badge-muted';
            const label = type || '--';
            return '<span class="badge ' + cls + '" title="' + esc(interpretation || '') + '">' + esc(label) + '</span>';
        }
```

Edit D — replace all three `colspan="9"` with `colspan="10"` (exactly the loading :139, error :149 and empty :189 rows).

Edit E — insert the cell between Peer Range and Why (:219-220):

```js
                    '<td>' + peerRange + '</td>' +
                    '<td>' + classificationBadge(d.layered_type, d.layered_interpretation) + '</td>' +
                    '<td>' + whyBtn + '</td>' +
```

Edit F — CSV header (:22):

```js
            const headers = ['Hospital', 'Month', 'Indicator', 'Value', 'Benchmark', 'Z-Score', 'Peers', 'Peer Std', 'Peer Range', 'Peer Median', 'Severity', 'Features', 'Classification'];
```

Edit G — CSV row (the bare `features` entry, :39):

```js
                    features,
                    d.layered_type || ''
```

**3c — badge classes** (`static/css/styles.css`, after `.badge-decreasing` :189):

```css
.badge-amber { background: var(--severity-warning-bg); color: #B45309; }
.badge-muted { background: var(--bg-surface-hover); color: var(--text-muted); }
```

**3d — i18n** (`static/js/i18n.js`, inside the `// Outliers Tab` section after the Z-score legend key :349):

```js
            'Classification': 'التصنيف',
            '— layered verdict for this row (raw value → rate → history → volume → peer layers); an outlier alone is never proof of a data error.': '— الحكم متعدد الطبقات لهذا الصف (القيمة الخام ← المعدل ← التاريخ ← الحجم ← النظراء)؛ الشذوذ وحده ليس دليلاً على خطأ في البيانات.',
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_ui.py tests/test_outliers_js.py -v`

Expected: all PASS. `test_outliers_js.py` is the regression suite for everything §10A says must NOT change: exports, no native row tooltip, clickable peers cell, fractional peer rates, CSV column membership.

- [ ] **Step 5: Lint and commit**

No JS/CSS linter in this repo — the gate is the Python test file:

```bash
.venv\Scripts\ruff.exe check tests/test_layered_ui.py
```

Expected: `All checks passed!`

```bash
git add static/tabs/outliers.html static/js/outliers.js static/css/styles.css static/js/i18n.js tests/test_layered_ui.py
git commit -m "feat(layered): classification column with typed badges in the outliers tab"
```

---

### Task 17: Layered Analysis tab — registration and screen

**Files:**
- Create: `static/tabs/layered.html`
- Create: `static/js/layered.js`
- Modify: `app/menu_registry.py`
- Modify: `static/index.html`
- Modify: `static/js/auth.js`
- Modify: `static/js/main.js`
- Modify: `static/js/app.js`
- Modify: `static/js/renderSidebar.js`
- Modify: `static/js/i18n.js`
- Modify: `tests/test_menu_api.py`
- Modify: `tests/test_layered_ui.py` (append — Task 16 created the file)

**Interfaces:**
- Consumes (Task 14): `GET /analysis/layered` — paged `{"total", "page", "page_size", "data"}`, sort whitelist `month | level | type | raw_value | rate | denominator` (analysis.py:4767), `page_size` cap 500 (analysis.py:4771); `GET /analysis/layered/summary` — `{"month", "total", "by_classification": [{"outlier_type", "count"}], "by_hospital": [{"hospital_id", "hospital", "count"}]}`; rows carry `hospital`, `indicator_name`, `indicator_type` display fields.
- Consumes (Task 15): `window.showWhyPopup({kind: 'layered_outlier', hospitalId, month, indicatorCode})` — the object form explain.js:367-379 accepts; `indicatorCode` rides as `&indicator_code=` (explain.js:336) into the Task 15 dispatcher branch.
- Consumes (Task 16): `export function classificationBadge(type, interpretation)` from `outliers.js` — the Layered tab renders the identical badge, so both screens can never drift.
- Produces (Task 18): nothing — the last implementation task; Task 18 only runs the full regression.

**Context:**
- Registration is nine touchpoints, every one pattern-matched from the `outliers` tab: registry entry in `TAB_REGISTRY` (menu_registry.py:15 area), `"layered"` in the `Oversight` group's `items` right after `"outliers"` (menu_registry.py:26), `index.html` tab div right after the outliers div (:127), `auth.js` `_TAB_PERMISSIONS` entry (:486-501), `main.js` `_initTab` hook `if (name === 'layered') _tryInit('loadLayered', 10)` (:234-248), `_tabLabels` + `_tabIcons` + `_searchItems` (:266-272), `app.js` stubs (:61-63) + `mods` entry (:191) + `_bindAll` case (:235), `renderSidebar.js` fallback `fb-4` Oversight list (:152-155).
- Permission is **`analysis.read`** — the same codename the whole `/analysis` router already guards with (analysis.py:45), so no new permission needs seeding and `require_permission` 403s for users who lack it (deps.py:40). The drift-guard tests derive everything from `TAB_REGISTRY` (`test_admin_drift_guards.py:42,53-56`) and the visibility matrix computes access from role permission codes (admin.py:543-546) — both stay green with zero edits; a role that can open Comparative Analysis can open this tab.
- Menu seeding is automatic: `scripts/seed_menu.py::_backfill_new_tabs` appends any registry tab missing from the DB into its `DEFAULT_GROUPS` group (fresh seeds and existing databases both covered), and `test_menu_seed_backfill.py:38,70` compares against `set(TAB_REGISTRY.keys())` / `len(TAB_REGISTRY)` dynamically.
- **One existing assertion must grow**: `tests/test_menu_api.py:47` pins `len(tabs) == 15` — the registry gains a member, so it becomes `16` (plus a `assert "layered" in keys`). That is the only existing test this task touches; `test_get_menu_returns_seeded_groups` counts *groups* (5, unchanged), not items.
- The screen copies the Outliers skeleton (header → chips → filter card → paged table) but **sorting and paging are server-side**: rows page server-side (`offset/limit`, analysis.py:4828-4829), so a DOM sort would only order the loaded 50 rows — exactly the bug `wireRuleFailSort` fixed for rule failures (outliers.js:340-357). `wireLayeredSort` mirrors that handler: header click → set `_sort`/`_order` → `_page = 1` → `loadLayered()`; first click on Month = desc (newest first), first click elsewhere = asc; arrows sync via the existing `.sort-asc`/`.sort-desc` classes. The only sortable headers are the whitelist keys, carried 1:1 in `data-col` (`month`, `raw_value`, `rate`, `denominator`, `level`, `type`); `type` is the Classification column's server key (analysis.py:4813). Hospital / Indicator / Peer / Why stay unsortable — no server key exists for them.
- Filter bootstrap: **months** from `GET /analysis/months` (IndicatorValue-derived, analysis.py:587 — the same endpoint admin.js:1721 uses) and **hospitals** from `GET /hospitals/` (hospitals.py:29) are complete lists, fetched once per tab session, each in its own `.catch` so a failed bootstrap (e.g. a user without `hospitals.read`) degrades to an empty dropdown instead of a dead tab. **Classification / Level / Investigation** options are static enums inline in the HTML: the eight type constants (layered:3196-3203), `LEVELS` (`NONE..VERY_HIGH`), and the `_ROUTE_BY_RULE` values `none | data_quality | clinical | contextual` (layered:3210-3214) — raw constants, because that is what the badge labels and the API's `investigation` param (analysis.py:4763) speak. The **Indicator** dropdown accumulates `analysis_code → indicator_name` pairs from every load response (a module-scope `Map`): analysis codes come from `build_analysis_specs` (count = `Indicator.code`, rate = `rate_*`, layered:3474) and have no dedicated endpoint, so the rows themselves — which already carry `indicator_name` — are the honest source; the map only grows, so revisiting months keeps prior options.
- Δ% cells (spec §10B `Raw value (Δ%), Rate (Δ%), Denominator (Δ%)`) each read their own persisted change field, so no column can show another column's delta: raw value appends the change vs the **previous month** (`previous_value`; guard `null` and `previous_value === 0`), rate appends vs **baseline** (`historical_change_percent` — the very field the Task 11 rule-2 magnitude guard reads), denominator appends vs **previous denominator** (`denominator_change_percent`). A null change field renders the bare value; count rows have no rate/denominator at all → `--`, so nothing is ever cross-assigned.
- Classification cell and chips reuse `classificationBadge` (Task 16) — same colors, same raw-constant labels, `null`/unmatched → gray `--` (never coerced to `NORMAL`, the ghost doctrine). Level cell maps `NONE→badge-muted, LOW→badge-low, MODERATE→badge-medium, HIGH→badge-high, VERY_HIGH→badge-critical` — the palette Task 16 completed.
- Why button: `window.showWhyPopup({kind:'layered_outlier', hospitalId, month, indicatorCode})`, string args embedded with `JSON.stringify(...).replace(/"/g, '&quot;')` exactly like outliers.js:208 — never the positional `'anomaly'` path (asserted by a test). The Task 15 payload (layers, chain, thresholds) is what the popup renders.
- Export mirrors `exportRuleFailuresCSV` (outliers.js:84-100): re-query `page=1&page_size=500` (endpoint cap) with the active filters + sort, busy state on `#layeredExportBtn`, fall back to `window._lastLayeredData` if the re-query fails. Headers cover every table column plus `Interpretation` and `Hospital ID` for pivoting.
- i18n: English **is** the key (the ar map only), and `test_smart_core_js.py` sweeps every tab: all `data-i18n` keys in `layered.html` must exist as `'key':` in i18n.js (:471-492), must equal the element's displayed English text, and must contain no underscore (:627-669). New keys go right after the `// Outliers Tab` block (i18n.js:349, before `// Audit & Verification Tab`); `'Classification'` arrives with Task 16. Every `__()` literal in `layered.js` gets an entry too (the `Exporting data...` key already exists at i18n.js:978).
- `layered.js` talks to the API only through `apiGet` — a literal `fetch(` anywhere in the file fails `test_no_raw_api_fetches_outside_auth_layer` (test_smart_core_js.py:526-560).
- Row markup never writes a literal tab before `title=` (keeps the habit behind `test_outliers_js.py`'s native-tooltip guard; the only `title=` in the new files is built with `+` concatenation).
- Icons: `🧱` for the registry entry, `_tabIcons`, and the renderSidebar fallback — three places must match.

- [ ] **Step 1: Append the failing tests**

First, grow the tab-count assertion in `tests/test_menu_api.py` — `test_list_tabs` (the registry gains the `layered` member):

```python
    resp = client.get("/menu/tabs")
    assert resp.status_code == 200
    tabs = resp.json()["tabs"]
    assert len(tabs) == 16
    keys = [t["key"] for t in tabs]
    assert "dashboard" in keys
    assert "smart-analytics" in keys
    assert "indicator-groups" in keys
    assert "layered" in keys
```

Then append to `tests/test_layered_ui.py` (after `test_classification_label_is_translated`):

```python

# ── Task 17: Layered Analysis tab (§10B) ─────────────────────────────

def test_index_has_layered_tab_div():
    html = _read("index.html")
    assert 'id="tab-layered"' in html
    div = html.split('id="tab-layered"')[1].split("</div>")[0]
    assert "/static/tabs/layered.html" in div
    assert 'data-loaded="false"' in div


def test_menu_registry_registers_layered_tab():
    from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY

    spec = TAB_REGISTRY["layered"]
    assert spec["label"] == "Layered Analysis"
    assert spec["permission"] == "analysis.read"
    oversight = next(g for g in DEFAULT_GROUPS if g["name"] == "Oversight")
    assert oversight["items"].index("layered") == oversight["items"].index("outliers") + 1


def test_auth_maps_layered_tab_to_analysis_permission():
    js = _read("js", "auth.js")
    assert "'tab-layered': 'analysis.read'" in js


def test_main_inits_labels_and_searches_the_layered_tab():
    js = _read("js", "main.js")
    assert "_tryInit('loadLayered', 10)" in js
    assert "layered: 'Layered Analysis'" in js
    assert "{tab:'layered'" in js


def test_app_binds_the_layered_module():
    js = _read("js", "app.js")
    assert "['layered'" in js
    assert "import('./layered.js')" in js
    assert "window.loadLayered = _stub('loadLayered')" in js
    assert "_bind(mod, 'loadLayered')" in js
    assert "_bind(mod, 'exportLayeredCSV')" in js


def test_sidebar_fallback_lists_layered_in_oversight():
    js = _read("js", "renderSidebar.js")
    assert "tab_key:'layered'" in js
    assert js.index("tab_key:'layered'") > js.index("tab_key:'outliers'")


def test_layered_tab_html_shape():
    html = _read("tabs", "layered.html")
    for el_id in ("layeredHospitalFilter", "layeredMonthFilter", "layeredIndicatorFilter",
                  "layeredClassificationFilter", "layeredLevelFilter", "layeredInvestigationFilter",
                  "layeredSummary", "layeredTbody", "layeredCount", "layeredPageInfo",
                  "layeredExportBtn", "layeredLoading"):
        assert f'id="{el_id}"' in html, el_id


def test_layered_columns_follow_spec_order():
    """Spec §10B: Hospital, Month, Indicator, Raw value (Δ%), Rate (Δ%),
    Denominator (Δ%), Peer, Level, Classification, Why."""
    html = _read("tabs", "layered.html")
    thead = html.split("<thead>")[1].split("</thead>")[0]
    order = [
        'data-i18n="Hospital"', 'data-i18n="Month"', 'data-i18n="Indicator"',
        'data-i18n="Raw value (Δ%)"', 'data-i18n="Rate (Δ%)"',
        'data-i18n="Denominator (Δ%)"', 'data-i18n="Peer"',
        'data-i18n="Level"', 'data-i18n="Classification"', 'data-i18n="Why"',
    ]
    pos = [thead.index(tok) for tok in order]
    assert pos == sorted(pos), pos


def test_layered_sortable_headers_use_endpoint_sort_keys():
    """The table pages server-side, so only endpoint whitelist keys may be
    sortable (month|level|type|raw_value|rate|denominator); DOM sorting the
    loaded page would order at most 50 rows."""
    html = _read("tabs", "layered.html")
    thead = html.split("<thead>")[1].split("</thead>")[0]
    for col in ("month", "raw_value", "rate", "denominator", "level", "type"):
        assert f'data-col="{col}"' in thead, col
    for col in ("hospital", "indicator", "peer"):
        assert f'data-col="{col}"' not in thead, col


def test_layered_static_filter_options_cover_the_enums():
    html = _read("tabs", "layered.html")
    for type_name in ("NORMAL", "RAW_VALUE_ANOMALY", "RATE_ANOMALY", "HISTORICAL_ANOMALY",
                      "VOLUME_DRIVEN_ANOMALY", "PEER_ANOMALY",
                      "POSSIBLE_DATA_ENTRY_ERROR", "CLINICAL_INVESTIGATION_REQUIRED"):
        assert f'value="{type_name}"' in html, type_name
    for lvl in ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH"):
        assert f'value="{lvl}"' in html, lvl
    for route in ("none", "data_quality", "clinical", "contextual"):
        assert f'value="{route}"' in html, route


def test_layered_js_contract():
    js = _read("js", "layered.js")
    for fn in ("export async function loadLayered", "export function layeredFilterChange",
               "export function layeredPage", "export async function exportLayeredCSV"):
        assert fn in js, fn
    assert "'/analysis/layered?'" in js
    assert "'/analysis/layered/summary?'" in js
    assert "'/analysis/months'" in js
    assert "'/hospitals/'" in js
    assert "page_size=500" in js                # export re-query at the endpoint cap
    assert "classificationBadge" in js           # one badge implementation (Task 16)
    assert "fetch(" not in js                    # apiGet only; the global fetch sweep also checks


def test_layered_why_opens_the_layered_explanation():
    js = _read("js", "layered.js")
    # The source escapes the quotes (the onclick attribute is one JS string),
    # exactly like outliers.js:208 — hence the doubled backslashes here.
    assert "showWhyPopup({kind:\\'layered_outlier\\'" in js
    assert "indicatorCode" in js
    assert "anomaly" not in js    # the Task 15 dispatcher is kind-specific


def test_layered_i18n_keys_exist():
    import re

    html = _read("tabs", "layered.html")
    i18n = _read("js", "i18n.js")
    for key in re.findall(r'data-i18n="([^"]+)"', html):
        assert f"'{key}':" in i18n, key
    for key in ("'Layered Analysis'", "'Raw value (Δ%)'", "'Rate (Δ%)'",
                "'Denominator (Δ%)'", "'Peer'", "'No layered findings for the selected criteria.'"):
        assert f"{key}:" in i18n, key
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_ui.py tests/test_menu_api.py -v`

Expected: every Task 17 test FAILS — `static/tabs/layered.html` and `static/js/layered.js` do not exist, none of the nine registration sites are edited, and none of the i18n keys are in i18n.js yet. `test_menu_api.py::test_list_tabs` FAILS on `len(tabs) == 16` (the registry still has 15 members). Task 16's tests in the same file already PASS (Task 16 ran first), and the rest of `test_menu_api.py` stays green — `test_get_menu_returns_seeded_groups` counts groups (5, unchanged), not items.

- [ ] **Step 3: Implement the tab**

**3a — Register the tab** (each edit sitting next to the `outliers` line it mirrors).

`app/menu_registry.py` — new `TAB_REGISTRY` entry between `outliers` and `alerts`, then the `Oversight` group gains the item right after `outliers`:

```python
    ("outliers",        {"label": "Outliers",              "icon": "⚠️", "permission": "outliers.read"}),
    ("layered",         {"label": "Layered Analysis",      "icon": "🧱", "permission": "analysis.read"}),
    ("alerts",          {"label": "Alerts",                "icon": "🔔", "permission": "alerts.read"}),
```

```python
    {"name": "Oversight", "icon": "🛡️", "items": ["quality", "outliers", "layered", "alerts", "audit"]},
```

`static/index.html` — tab-content div right after the outliers div (:127):

```html
        <div id="tab-layered" class="tab-content" data-loaded="false" role="tabpanel" aria-labelledby="tab-layered" data-src="/static/tabs/layered.html"></div>
```

`static/js/auth.js` — one line in `_TAB_PERMISSIONS` after `tab-outliers` (:489):

```js
    'tab-layered': 'analysis.read',
```

`static/js/main.js` — three spots: the `_initTab` hook after `outliers` (:238),

```js
            if (name === 'layered') _tryInit('loadLayered', 10);
```

then inside the single-line maps — `_tabLabels` (:266) gains `layered: 'Layered Analysis',` immediately after `outliers: 'Outliers',`; `_tabIcons` (:267) gains `layered: '🧱',` immediately after `outliers: '⚠',`; `_searchItems` (:272) gains the entry after the outliers item:

```js
{tab:'layered',kw:'layered analysis classification investigation data quality clinical'},
```

`static/js/app.js` — three spots: the placeholder stubs after `window.exportRuleFailuresCSV` (:64),

```js
window.loadLayered = _stub('loadLayered');
window.layeredFilterChange = _stub('layeredFilterChange');
window.layeredPage = _stub('layeredPage');
window.exportLayeredCSV = _stub('exportLayeredCSV');
```

the `mods` list after the `outliers` entry (:191),

```js
    ['layered',    () => import('./layered.js')],
```

and the `_bindAll` switch after the `case 'outliers'` block (:235-239),

```js
    case 'layered':
      _bind(mod, 'loadLayered'); _bind(mod, 'layeredFilterChange');
      _bind(mod, 'layeredPage'); _bind(mod, 'exportLayeredCSV');
      break;
```

`static/js/renderSidebar.js` — fallback `fb-4` (Oversight) item after the outliers line (:153):

```js
            {tab_key:'layered', label:'Layered Analysis', icon:'🧱', permission:'analysis.read'},
```

`static/js/i18n.js` — new section between `// Outliers Tab` and `// Audit & Verification Tab` (:350). English IS the key; every value is the Arabic rendering:

```js
            // Layered Analysis Tab
            'Layered Analysis': 'التحليل المتدرج',
            'Every signal is a question, not a verdict: raw value, rate, history, volume, then peers.': 'كل إشارة سؤال لا حكم مسبق: القيمة الخام، النسبة، التاريخ، الحجم، ثم النظراء.',
            'Raw value (Δ%)': 'القيمة الخام (Δ%)',
            'Rate (Δ%)': 'النسبة (Δ%)',
            'Denominator (Δ%)': 'المقام (Δ%)',
            'Peer': 'النظراء',
            'No layered findings for the selected criteria.': 'لا توجد نتائج متدرجة للمعايير المحددة.',
```

(`'Classification'` already arrived with Task 16; `Hospital`/`Month`/`Indicator`/`Level`/`Denominator`/`Why`/`Exporting data...` already existed — the Step 4 run proves it via the tab sweep.)

**3b — Create `static/tabs/layered.html`.** Same skeleton as outliers.html (header + chips → filter card → paged table). Every `data-i18n` key equals the displayed English text (the `test_smart_core_js.py` sweep); only the six whitelist columns carry `class="sortable"` + `data-col`; the three static enum selects hold the raw constants:

```html
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
    <div>
        <h2 style="margin:0;" data-i18n="Layered Analysis">Layered Analysis</h2>
        <span style="font-size:0.82rem;color:var(--text-muted);" data-i18n="Every signal is a question, not a verdict: raw value, rate, history, volume, then peers.">Every signal is a question, not a verdict: raw value, rate, history, volume, then peers.</span>
    </div>
    <div id="layeredSummary" style="display:flex;gap:0.4rem;flex-wrap:wrap;"></div>
</div>
<div class="card" style="padding:0.6rem 0.8rem;">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem;">
        <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
            <label style="font-size:0.75rem;color:var(--text-secondary);">Hospital:</label>
            <select id="layeredHospitalFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;"><option value="">All</option></select>
            <label style="font-size:0.75rem;color:var(--text-secondary);">Month:</label>
            <select id="layeredMonthFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;"><option value="">All</option></select>
            <label style="font-size:0.75rem;color:var(--text-secondary);">Indicator:</label>
            <select id="layeredIndicatorFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;"><option value="">All</option></select>
            <label style="font-size:0.75rem;color:var(--text-secondary);">Classification:</label>
            <select id="layeredClassificationFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;">
                <option value="">All</option>
                <option value="NORMAL">NORMAL</option>
                <option value="RAW_VALUE_ANOMALY">RAW_VALUE_ANOMALY</option>
                <option value="RATE_ANOMALY">RATE_ANOMALY</option>
                <option value="HISTORICAL_ANOMALY">HISTORICAL_ANOMALY</option>
                <option value="VOLUME_DRIVEN_ANOMALY">VOLUME_DRIVEN_ANOMALY</option>
                <option value="PEER_ANOMALY">PEER_ANOMALY</option>
                <option value="POSSIBLE_DATA_ENTRY_ERROR">POSSIBLE_DATA_ENTRY_ERROR</option>
                <option value="CLINICAL_INVESTIGATION_REQUIRED">CLINICAL_INVESTIGATION_REQUIRED</option>
            </select>
            <label style="font-size:0.75rem;color:var(--text-secondary);">Level:</label>
            <select id="layeredLevelFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;">
                <option value="">All</option>
                <option value="NONE">NONE</option>
                <option value="LOW">LOW</option>
                <option value="MODERATE">MODERATE</option>
                <option value="HIGH">HIGH</option>
                <option value="VERY_HIGH">VERY_HIGH</option>
            </select>
            <label style="font-size:0.75rem;color:var(--text-secondary);">Investigation:</label>
            <select id="layeredInvestigationFilter" onchange="layeredFilterChange()" style="font-size:0.78rem;padding:0.2rem 0.4rem;">
                <option value="">All</option>
                <option value="none">none</option>
                <option value="data_quality">data_quality</option>
                <option value="clinical">clinical</option>
                <option value="contextual">contextual</option>
            </select>
        </div>
        <div style="display:flex;align-items:center;gap:0.4rem;">
            <span id="layeredCount" style="font-size:0.75rem;color:var(--text-muted);"></span>
            <span id="layeredLoading" class="hidden" style="font-size:0.75rem;color:var(--text-muted);"><span class="spinner"></span></span>
            <button onclick="layeredPage(-1)" style="background:var(--bg-surface-hover);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;cursor:pointer;">&#8249; Prev</button>
            <span id="layeredPageInfo" style="font-size:0.75rem;color:var(--text-muted);"></span>
            <button onclick="layeredPage(1)" style="background:var(--bg-surface-hover);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;cursor:pointer;">Next &#8250;</button>
            <button id="layeredExportBtn" onclick="exportLayeredCSV()" style="background:var(--bg-surface-hover);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;padding:0.2rem 0.6rem;font-size:0.75rem;cursor:pointer;">Export CSV</button>
        </div>
    </div>
    <div style="max-height:500px;overflow-y:auto;">
        <table id="layeredTable">
            <thead><tr>
                <th data-i18n="Hospital">Hospital</th>
                <th class="sortable" data-col="month" data-i18n="Month">Month</th>
                <th data-i18n="Indicator">Indicator</th>
                <th class="sortable" data-col="raw_value" data-i18n="Raw value (Δ%)">Raw value (Δ%)</th>
                <th class="sortable" data-col="rate" data-i18n="Rate (Δ%)">Rate (Δ%)</th>
                <th class="sortable" data-col="denominator" data-i18n="Denominator (Δ%)">Denominator (Δ%)</th>
                <th data-i18n="Peer">Peer</th>
                <th class="sortable" data-col="level" data-i18n="Level">Level</th>
                <th class="sortable" data-col="type" data-i18n="Classification">Classification</th>
                <th data-i18n="Why">Why</th>
            </tr></thead>
            <tbody id="layeredTbody"></tbody>
        </table>
    </div>
</div>
```

Note the `data-col="type"` on Classification — `type` is the endpoint's sort key for `outlier_type` (analysis.py:4813), and Hospital/Indicator/Peer/Why carry no `data-col` at all because no server sort key exists for them.

**3c — Create `static/js/layered.js`.** The outliers idiom with three deliberate differences: paging state is module-local (`_page`, server-side `offset/limit` — a DOM sort would only order the loaded 50 rows), the filter dropdowns bootstrap from `/analysis/months` + `/hospitals/` + accumulated rows, and the Why button opens `kind:'layered_outlier'` (object form, Task 15's dispatcher). Δ% semantics: raw vs `previous_value`, rate vs `historical_change_percent` (baseline), denominator vs `denominator_change_percent` — each column reads only its own change field.

```js
import { apiGet } from './api.js';
import { __ } from './i18n.js';
import { esc } from './tree.js';
import { classificationBadge } from './outliers.js';

// ── CSV export utility (same shape as outliers.js) ─────────────────
function downloadCSV(filename, headers, rows) {
    const csvContent = [headers.join(','), ...rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
}

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

const PAGE_SIZE = 50;
let _page = 1;
let _sort = 'month';
let _order = 'desc';
let _filtersInited = false;
const _indicatorOpts = new Map();

const _LEVEL_BADGES = {
    NONE: 'badge-muted', LOW: 'badge-low', MODERATE: 'badge-medium',
    HIGH: 'badge-high', VERY_HIGH: 'badge-critical',
};

function _filterQuery() {
    const hosp = document.getElementById('layeredHospitalFilter').value;
    const mon = document.getElementById('layeredMonthFilter').value;
    const ind = document.getElementById('layeredIndicatorFilter').value;
    const cls = document.getElementById('layeredClassificationFilter').value;
    const lvl = document.getElementById('layeredLevelFilter').value;
    const inv = document.getElementById('layeredInvestigationFilter').value;
    let q = '';
    if (hosp) q += 'hospital=' + hosp + '&';
    if (mon) q += 'month=' + encodeURIComponent(mon) + '&';
    if (ind) q += 'indicator=' + encodeURIComponent(ind) + '&';
    if (cls) q += 'classification=' + encodeURIComponent(cls) + '&';
    if (lvl) q += 'level=' + encodeURIComponent(lvl) + '&';
    if (inv) q += 'investigation=' + encodeURIComponent(inv) + '&';
    return q;
}

function _fmt(v) {
    return (v !== null && v !== undefined) ? Number(v).toFixed(2) : '--';
}

function _rawDelta(d) {
    if (d.raw_value === null || d.raw_value === undefined) return null;
    if (d.previous_value === null || d.previous_value === undefined || d.previous_value === 0) return null;
    return (d.raw_value - d.previous_value) / Math.abs(d.previous_value) * 100;
}

function _fmtDelta(v) {
    if (v === null || v === undefined) return '';
    return ' (' + (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%)';
}

function _deltaCsv(v) {
    if (v === null || v === undefined) return '';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(1);
}

function _levelBadge(level) {
    const cls = _LEVEL_BADGES[level] || 'badge-muted';
    return '<span class="badge ' + cls + '">' + esc(level || 'NONE') + '</span>';
}

function populateSelectOptions(sel, values, currentVal) {
    const prevVal = sel.value;
    sel.innerHTML = '<option value="">All</option>';
    values.slice().sort().forEach(x => {
        const opt = document.createElement('option');
        opt.value = x; opt.textContent = x;
        sel.appendChild(opt);
    });
    sel.value = currentVal && values.includes(currentVal) ? currentVal : (prevVal && values.includes(prevVal) ? prevVal : '');
}

// Bootstrap the complete dropdowns once per tab session. Each fetch is
// isolated: a user without hospitals.read still gets months + rows, just an
// unpopulated hospital dropdown (all hospitals).
async function _initFilters() {
    if (_filtersInited) return;
    _filtersInited = true;
    try {
        const months = await apiGet('/analysis/months');
        if (Array.isArray(months)) {
            populateSelectOptions(document.getElementById('layeredMonthFilter'), months, '');
        }
    } catch (err) {
        console.warn('Layered month filter failed:', err);
    }
    try {
        const hosps = await apiGet('/hospitals/');
        const list = Array.isArray(hosps) ? hosps : [];
        const sel = document.getElementById('layeredHospitalFilter');
        const prevVal = sel.value;
        sel.innerHTML = '<option value="">All</option>';
        list.slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''))).forEach(h => {
            const opt = document.createElement('option');
            opt.value = h.id; opt.textContent = h.name;
            sel.appendChild(opt);
        });
        sel.value = prevVal;
    } catch (err) {
        console.warn('Layered hospital filter failed:', err);
    }
}

// The indicator select has no endpoint: analysis codes come from
// build_analysis_specs (count = Indicator.code, rate = rate_*), so the rows
// themselves — which carry indicator_name — are the source. The map only
// grows, so returning to an earlier month keeps its options.
function _updateIndicatorOpts(data) {
    data.forEach(d => {
        if (d.analysis_code) _indicatorOpts.set(d.analysis_code, d.indicator_name || d.analysis_code);
    });
    const sel = document.getElementById('layeredIndicatorFilter');
    const prevVal = sel.value;
    sel.innerHTML = '<option value="">All</option>';
    Array.from(_indicatorOpts.entries())
        .sort((a, b) => a[1].localeCompare(b[1]))
        .forEach(([code, name]) => {
            const opt = document.createElement('option');
            opt.value = code; opt.textContent = name;
            sel.appendChild(opt);
        });
    sel.value = _indicatorOpts.has(prevVal) ? prevVal : '';
}

function _renderSummary(sum) {
    const el = document.getElementById('layeredSummary');
    if (!el) return;
    if (!sum || !sum.by_classification || !sum.by_classification.length) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = sum.by_classification.map(e =>
        '<span style="display:inline-flex;align-items:center;gap:0.3rem;">'
        + classificationBadge(e.outlier_type, '')
        + '<span style="font-weight:700;color:var(--text-muted);">' + e.count + '</span></span>'
    ).join('');
}

// Server-side sort: header click -> sort/order state -> re-query. First click
// on Month = newest first, first click elsewhere = asc (rule-failures idiom).
function wireLayeredSort() {
    document.querySelectorAll('#layeredTable th.sortable').forEach(th => {
        th.onclick = function () {
            const col = this.dataset.col;
            if (_sort === col) {
                _order = _order === 'asc' ? 'desc' : 'asc';
            } else {
                _sort = col;
                _order = col === 'month' ? 'desc' : 'asc';
            }
            _page = 1;
            loadLayered();
        };
    });
    document.querySelectorAll('#layeredTable th.sortable').forEach(h => {
        h.classList.remove('sort-asc', 'sort-desc');
        if (h.dataset.col === _sort) h.classList.add(_order === 'asc' ? 'sort-asc' : 'sort-desc');
    });
}

export function layeredFilterChange() {
    _page = 1;
    loadLayered();
}

export function layeredPage(delta) {
    const next = _page + delta;
    if (next < 1) return;
    _page = next;
    loadLayered();
}

export async function loadLayered() {
    _initFilters();   // fire-and-forget; selections are read independently
    const loadingEl = document.getElementById('layeredLoading');
    if (loadingEl) loadingEl.classList.remove('hidden');
    const tbody = document.getElementById('layeredTbody');
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--text-muted);">Loading layered findings...</td></tr>';
    const month = document.getElementById('layeredMonthFilter').value;
    const url = '/analysis/layered?' + _filterQuery()
        + 'page=' + _page + '&page_size=' + PAGE_SIZE
        + '&sort=' + encodeURIComponent(_sort) + '&order=' + _order;
    try {
        const rows = await apiGet(url);
        let sum = null;
        try {
            sum = await apiGet('/analysis/layered/summary?' + (month ? 'month=' + encodeURIComponent(month) : ''));
        } catch (err) {
            console.warn('Layered summary failed:', err);
        }
        const data = rows.data || rows;
        window._lastLayeredData = data;
        _renderSummary(sum);
        _updateIndicatorOpts(data);
        const total = rows.total !== undefined ? rows.total : data.length;
        const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        if (!data.length && _page > 1) {
            // The requested page ran past the end (rows changed under us):
            // land on the last real page instead of showing a phantom empty.
            _page = pages;
            return loadLayered();
        }
        document.getElementById('layeredCount').textContent = total + ' finding(s)';
        document.getElementById('layeredPageInfo').textContent = _page + ' / ' + pages;
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);">' + __('No layered findings for the selected criteria.') + '</td></tr>';
            wireLayeredSort();
            return;
        }
        tbody.innerHTML = data.map(d => {
            const rawCell = (d.raw_value !== null && d.raw_value !== undefined)
                ? _fmt(d.raw_value) + _fmtDelta(_rawDelta(d)) : '--';
            const rateCell = (d.rate !== null && d.rate !== undefined)
                ? _fmt(d.rate) + _fmtDelta(d.historical_change_percent) : '--';
            const denCell = (d.denominator !== null && d.denominator !== undefined)
                ? _fmt(d.denominator) + _fmtDelta(d.denominator_change_percent) : '--';
            const peerCell = (d.peer_outlier_score !== null && d.peer_outlier_score !== undefined)
                ? _fmt(d.peer_outlier_score) : '--';
            // Object form: the Task 15 dispatcher keys on kind + indicator_code.
            const whyBtn = '<button onclick="window.showWhyPopup({kind:\'layered_outlier\',hospitalId:'
                + Number(d.hospital_id)
                + ',month:' + JSON.stringify(String(d.month)).replace(/"/g, '&quot;')
                + ',indicatorCode:' + JSON.stringify(String(d.analysis_code)).replace(/"/g, '&quot;')
                + '})" title="' + __('Why') + '"'
                + ' style="background:none;border:1px solid var(--border-default,#ccc);border-radius:4px;padding:1px 7px;font-size:0.7rem;cursor:pointer;color:var(--accent-blue,#1565c0);font-weight:600;">\u2139\ufe0f ' + __('Why') + '</button>';
            return '<tr>' +
                '<td>' + esc(d.hospital) + '</td>' +
                '<td>' + esc(d.month) + '</td>' +
                '<td>' + esc(d.indicator_name || d.analysis_code || '') + '</td>' +
                '<td>' + rawCell + '</td>' +
                '<td>' + rateCell + '</td>' +
                '<td>' + denCell + '</td>' +
                '<td>' + peerCell + '</td>' +
                '<td>' + _levelBadge(d.outlier_level) + '</td>' +
                '<td>' + classificationBadge(d.outlier_type, d.interpretation) + '</td>' +
                '<td>' + whyBtn + '</td>' +
                '</tr>';
        }).join('');
        wireLayeredSort();
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="10" style="color:red;">Error: ' + err.message + '</td></tr>';
    } finally {
        if (loadingEl) loadingEl.classList.add('hidden');
    }
}

export async function exportLayeredCSV() {
    const btn = document.getElementById('layeredExportBtn');
    const label = btn ? btn.textContent : null;
    if (btn) { btn.disabled = true; btn.textContent = __('Exporting data...'); }
    // Re-query at the endpoint cap so the CSV is not silently truncated to
    // the loaded page (the rule-failures export pattern).
    const q = _filterQuery() + 'page=1&page_size=500&sort=' + encodeURIComponent(_sort) + '&order=' + _order;
    let data = window._lastLayeredData;
    try {
        const resp = await apiGet('/analysis/layered?' + q);
        const fetched = resp.data || resp;
        if (fetched.length) data = fetched;
    } catch (err) {
        console.warn('Layered export: full fetch failed, exporting loaded rows', err);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = label || 'Export CSV'; }
    }
    if (!data || !data.length) return;
    const headers = ['Hospital ID', 'Hospital', 'Month', 'Indicator', 'Indicator Name', 'Type',
        'Raw Value', 'Raw Delta %', 'Rate', 'Rate Delta %', 'Denominator', 'Denominator Delta %',
        'Peer Score', 'Level', 'Investigation', 'Interpretation'];
    const rows = data.map(d => [
        d.hospital_id || '',
        d.hospital || '',
        d.month || '',
        d.analysis_code || '',
        d.indicator_name || '',
        d.outlier_type || '',
        (d.raw_value !== null && d.raw_value !== undefined) ? Number(d.raw_value).toFixed(2) : '',
        _deltaCsv(_rawDelta(d)),
        (d.rate !== null && d.rate !== undefined) ? Number(d.rate).toFixed(2) : '',
        _deltaCsv(d.historical_change_percent),
        (d.denominator !== null && d.denominator !== undefined) ? Number(d.denominator).toFixed(2) : '',
        _deltaCsv(d.denominator_change_percent),
        (d.peer_outlier_score !== null && d.peer_outlier_score !== undefined) ? Number(d.peer_outlier_score).toFixed(2) : '',
        d.outlier_level || '',
        d.investigation_route || '',
        d.interpretation || ''
    ]);
    downloadCSV('layered_' + todayStr() + '.csv', headers, rows);
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_layered_ui.py -v`

Expected: all PASS — every Task 17 test plus Task 16's seven.

Then the registration + sweep regression net (the tab ripples into menu, admin, i18n and the raw-fetch guard):

Run: `.venv\Scripts\python.exe -m pytest tests/test_menu_api.py tests/test_menu_seed_backfill.py tests/test_admin_drift_guards.py tests/test_smart_core_js.py tests/test_outliers_js.py -v`

Expected: all PASS except one pre-existing failure that is already red before this plan starts: `test_smart_core_js.py::test_audit_screen_all_strings_translated` (the in-flight `audit.js` uses `'Why this rule failed?'`, which the current `i18n.js` does not define — recorded in the execution ledger as a baseline failure). Everything else in these five files must pass. Specifically:

- `test_menu_api.py::test_list_tabs` finds 16 tabs including `layered`; the group-count tests are untouched (5 groups — a tab is an *item*, not a group).
- `test_menu_seed_backfill.py` seeds and backfills `layered` through `TAB_REGISTRY`/`DEFAULT_GROUPS` — all its assertions are dynamic (`set(TAB_REGISTRY.keys())`, `len(TAB_REGISTRY)`), so the new member flows through unchanged.
- `test_admin_drift_guards.py` visibility matrix derives the tab from `TAB_REGISTRY` (label `🧱 Layered Analysis`, permission `analysis.read`) — `test_visibility_tabs_match_registry` and `test_visibility_tabs_labels_and_permissions_from_registry` stay green with zero edits.
- `test_smart_core_js.py`'s two i18n sweeps now walk the new `layered.html`: every `data-i18n` key resolves in i18n.js, equals its displayed English text, and carries no underscore; `test_no_raw_api_fetches_outside_auth_layer` sees no `fetch(` in `layered.js`.
- `test_outliers_js.py` re-guards everything Task 16 deliberately left alone.

- [ ] **Step 5: Lint and commit**

No JS linter in this repo — the gate is the Python test files:

```bash
.venv\Scripts\ruff.exe check tests/test_layered_ui.py tests/test_menu_api.py
```

Expected: `All checks passed!`

```bash
git add app/menu_registry.py static/index.html static/js/auth.js static/js/main.js static/js/app.js static/js/renderSidebar.js static/js/i18n.js static/tabs/layered.html static/js/layered.js tests/test_layered_ui.py tests/test_menu_api.py
git commit -m "feat(layered): add the Layered Analysis tab with registration, filters and paging"
```

### Task 18: Full regression — every test together

**Files:**
- Create: none — this task only runs and verifies.

**Interfaces:**
- Consumes: the test suites written by Tasks 1–17.
- Produces: nothing — the final gate; T17's Interfaces block already says so.

**Context:**
- Spec §11 + §12: the layered feature's own tests must pass **and** every pre-existing suite must stay green — the migration and its idempotency guards, the schema self-heal, the two new cache keys, the menu registry (16 tabs), the i18n sweeps over the new `layered.html`, and the raw-fetch guard over `layered.js` were each only exercised inside their own task's slice. This run is where they meet.
- The suite is order-independent by construction: `tests/conftest.py` gives every test an isolated SQLite schema (`Base.metadata.create_all` + `seed_indicators` + `seed_rules` + `seed_menu`) and an isolated cache directory (`_isolate_cache_dir`), so a full-file run is the honest gate rather than a formality.
- Runner rules from Global Constraints apply verbatim: `.venv\Scripts\python.exe -m pytest ...` and `.venv\Scripts\ruff.exe check ...` — the system `python` has none of the project deps, and there is no server to start (tests use `TestClient` against the fixture DB).
- Nothing here changes files except the optional plan-doc commit in Step 5 — all implementation code already landed with its task's commit (Tasks 1–17, one `feat(...)`/`test(...)`/`refactor(...)` commit each; commit only those files, never `git add -A`).

- [ ] **Step 1: Run the entire test suite**

Run: `.venv\Scripts\python.exe -m pytest -v`

Expected: **all tests pass, except the two pre-existing baseline failures** recorded before Task 1 ran (`baseline-out.txt` in the execution ledger):

1. `tests/test_deploy_cloudrun_supabase.py::test_script_is_valid_bash` — `FileNotFoundError` because `bash`/`sh` is not on this Windows machine's PATH (environment artifact).
2. `tests/test_smart_core_js.py::test_audit_screen_all_strings_translated` — the in-flight `audit.js` uses `'Why this rule failed?'`, missing from the current `i18n.js` (pre-existing content gap).

No other test may fail. Specifically including:

- The six layered suites: `tests/test_rate_config.py`, `tests/test_layered_schema.py`, `tests/test_layered_engine.py`, `tests/test_layered_pipeline.py`, `tests/test_layered_api.py`, `tests/test_layered_ui.py`.
- The pre-existing suites this plan brushed: `tests/test_menu_api.py` (now 16 tabs, `layered` present), `tests/test_menu_seed_backfill.py`, `tests/test_admin_drift_guards.py`, `tests/test_outliers_js.py`, `tests/test_smart_core_js.py` (its i18n sweeps walk the new `layered.html`; its raw-fetch guard sees no `fetch(` in `layered.js`), `tests/test_export.py`, `tests/test_i18n_expressions.py`.
- The regression set the spec names explicitly (§11): `tests/test_anomaly.py`, `tests/test_quality_score.py`, `tests/test_explain*.py`, `tests/test_pipeline.py`, `tests/test_migrations.py`, `tests/test_migration_guard.py` — `anomaly_results`, the Data Quality Score and the Alembic history are exactly what §12 puts off-limits.
- The untouched majority — quality-score, anomaly-results, clinical/smart/rules, API smoke tests — proof of the Global Constraints: `anomaly_results` and the Data Quality Score untouched (spec §2 Q3), and the 4 migrated rate sites still producing identical numbers (spec §4).

The full run takes a few minutes and its output may be large — it lands in a file if the terminal truncates; search it rather than scrolling.

- [ ] **Step 2: Triage any failure**

- **A failure that is one of the two recorded baseline failures above** → not this plan's regression: record it and continue.
- **A layered test fails** → the task that owns it regressed: re-read that task's Context block (it carries the exact expectation and spec citation), fix the owning file, re-run that file, then repeat Step 1 in full.
- **A pre-existing test fails in a file the plan modified** (`menu_registry.py`, `analysis.py`, `explain.py`, `audit.py`, `pipeline.py`, `models.py`, `outliers.js`, `i18n.js`, `main.js`, `app.js`, `auth.js`, `index.html`, `renderSidebar.js`, `conftest.py`, `seed_indicators.py`, `test_menu_api.py`) → treat it as a plan regression by default; `git log --oneline -- <file>` shows which plan task touched it, and that task's plan text is the contract.
- **A failure in a module the plan never touched** → check whether the failing test imports/reads anything the plan did change. If genuinely unrelated, record the failure output as pre-existing and report it — do not silently skip it, and do not modify unrelated code to force it green. Everything the plan touched must pass.

- [ ] **Step 3: Lint every Python file the plan touched**

Run:

```bash
.venv\Scripts\ruff.exe check app/engine/rate_config.py app/engine/anomaly/zscore.py app/engine/clinical/thresholds.py app/engine/smart/indicator_forecast.py app/engine/quality/rules.py app/engine/anomaly/layered.py app/engine/anomaly/classify.py app/models.py app/main.py app/engine/pipeline.py app/api/analysis.py app/engine/audit/explain.py app/api/audit.py app/menu_registry.py scripts/seed_indicators.py tests/conftest.py alembic/versions/b1c2d3e4f5a6_add_layered_outlier_analysis.py tests/test_rate_config.py tests/test_layered_schema.py tests/test_layered_engine.py tests/test_layered_pipeline.py tests/test_layered_api.py tests/test_layered_ui.py tests/test_menu_api.py
```

Expected: `All checks passed!` (line-length 120, per `pyproject.toml`.)

- [ ] **Step 4: Confirm the tree holds only the plan's commits**

Run: `git status --short` and `git log --oneline -18`

Expected: `git log` shows the 17 plan commits (one per Task 1–17, conventional `feat`/`test`/`refactor` subjects) on top of the pre-plan history; `git status --short` shows only the pre-existing unrelated modifications — no `app/engine/anomaly/`, `app/engine/rate_config.py`, `static/tabs/layered.html`, `static/js/layered.js`, `tests/test_layered_*` or the migration file lingering uncommitted.

- [ ] **Step 5: Commit the plan document**

```bash
git add docs/superpowers/plans/2026-10-08-layered-outlier-analysis.md
git commit -m "docs(plan): layered outlier analysis implementation plan"
```

Expected: one new commit; `git status --short` afterwards shows only the pre-existing unrelated files.

**Plan complete.** Implementation is handed off per the header: `superpowers:subagent-driven-development` (a fresh subagent per task with review between tasks) or `superpowers:executing-plans`.
