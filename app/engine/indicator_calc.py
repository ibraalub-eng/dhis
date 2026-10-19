"""Derived-indicator calculation engine (Indicators tab, 2026-10-18).

Computes MANAGED derived indicators (app.models.IndicatorDefinition) from
the RAW IndicatorValue rows written by uploads/manual entry. Hard rules:

* Raw data is read-only here — results go to indicator_results, never to
  indicator_values, so imports, completeness, Data Tree and every existing
  dashboard are untouched.
* User formulas are NEVER executed. ``expression`` strings are parsed by a
  fixed-grammar recursive-descent parser (the same language family as the
  validation-rule formulas in app/engine/quality/rules.py): numbers,
  ``{code}`` references, ``+ - * /`` and parentheses only. Any other
  character, unbalanced paren or trailing token raises FormulaError at
  validation time — nothing unsafe can reach evaluation.
* Missing values and zero are different things: a reported 0.0 is a
  legitimate value, a missing row is not. Division by zero yields the
  ``zero_denominator`` status with a NULL value — never an exception, never
  a silent 0.
* Evaluation is deterministic and side-effect free; persistence is a
  separate explicit step (compute_and_store / recompute), so editing a
  definition can never silently rewrite historical results.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ── vocabularies (single source of truth for API validation + UI selects) ────
FORMULA_TYPES = ("ratio", "expression")
AGGREGATIONS = ("sum", "avg", "max", "min")
OPERATORS = ("/", "*", "+", "-")
RESULT_TYPES = ("percentage", "rate", "ratio", "count")
DIRECTIONS = ("none", "higher_is_better", "lower_is_better", "target_range")
ROUNDING_MODES = ("half_up", "half_even", "down")
MAX_PRECISION = 6                        # decimal places a definition may pin

# ── result statuses ─────────────────────────────────────────────────────────
STATUS_OK = "ok"                        # value computed
STATUS_MISSING = "missing_data"         # a referenced element has no value
STATUS_ZERO_DENOMINATOR = "zero_denominator"   # divisor evaluated to 0
STATUS_NO_DATA = "no_data"              # the hospital reported nothing at all this month
STATUS_ERROR = "error"                  # unexpected failure (kept, never raised)

STATUS_ALL = (STATUS_OK, STATUS_MISSING, STATUS_ZERO_DENOMINATOR,
              STATUS_NO_DATA, STATUS_ERROR)

_CODE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,50}$")


# ═══════════════════════════════════════════════════════════════════════════
# Safe expression parser — tokenizer + recursive-descent AST
# ═══════════════════════════════════════════════════════════════════════════

class FormulaError(ValueError):
    """Raised when a formula string fails strict syntax validation."""


def tokenize(expr: str) -> List[Tuple[str, object]]:
    """Split a formula into ('num', float) | ('code', str) | ('op', str)."""
    if not isinstance(expr, str) or not expr.strip():
        raise FormulaError("Formula is empty")
    tokens: List[Tuple[str, object]] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            j = expr.find("}", i + 1)
            if j == -1:
                raise FormulaError("Unclosed '{' in formula")
            code = expr[i + 1:j].strip()
            if not code:
                raise FormulaError("Empty '{}' reference in formula")
            tokens.append(("code", code))
            i = j + 1
            continue
        if ch in "+-*/()":
            tokens.append(("op", ch))
            i += 1
            continue
        if ch.isdigit() or ch == ".":
            j = i
            seen_digit = False
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                if expr[j].isdigit():
                    seen_digit = True
                j += 1
            lit = expr[i:j]
            if not seen_digit or lit.count(".") > 1:
                raise FormulaError(f"Malformed number '{lit}' in formula")
            tokens.append(("num", float(lit)))
            i = j
            continue
        raise FormulaError(f"Unexpected character '{ch}' in formula")
    if not tokens:
        raise FormulaError("Formula is empty")
    return tokens


def parse_expression(expr: str) -> dict:
    """Validate and compile a formula string into a structured AST.

    Grammar (fixed, no functions, no identifiers outside {code}, no eval):
        expr    := term (('+' | '-') term)*
        term    := unary (('*' | '/') unary)*
        unary   := '-' unary | primary
        primary := number | '{code}' | '(' expr ')'
    """
    tokens = tokenize(expr)
    pos = 0

    def _peek() -> Optional[Tuple[str, object]]:
        return tokens[pos] if pos < len(tokens) else None

    def _expect_op(expected: str) -> None:
        nonlocal pos
        tok = _peek()
        if tok is None or tok[0] != "op" or tok[1] != expected:
            raise FormulaError(f"Expected '{expected}' in formula")
        pos += 1

    def _parse_expr() -> dict:
        nonlocal pos
        node = _parse_term()
        while True:
            tok = _peek()
            if tok and tok[0] == "op" and tok[1] in ("+", "-"):
                pos += 1
                node = {"op": tok[1], "args": [node, _parse_term()]}
            else:
                return node

    def _parse_term() -> dict:
        nonlocal pos
        node = _parse_unary()
        while True:
            tok = _peek()
            if tok and tok[0] == "op" and tok[1] in ("*", "/"):
                pos += 1
                node = {"op": tok[1], "args": [node, _parse_unary()]}
            else:
                return node

    def _parse_unary() -> dict:
        nonlocal pos
        tok = _peek()
        if tok and tok[0] == "op" and tok[1] == "-":
            pos += 1
            return {"op": "neg", "args": [_parse_unary()]}
        return _parse_primary()

    def _parse_primary() -> dict:
        nonlocal pos
        tok = _peek()
        if tok is None:
            raise FormulaError("Unexpected end of formula")
        kind, val = tok
        if kind == "num":
            pos += 1
            return {"num": val}
        if kind == "code":
            pos += 1
            return {"code": val}
        if kind == "op" and val == "(":
            pos += 1
            node = _parse_expr()
            _expect_op(")")
            return node
        if kind == "op" and val == ")":
            raise FormulaError("Unbalanced parentheses in formula")
        raise FormulaError(f"Unexpected token '{val}' in formula")

    ast = _parse_expr()
    if pos != len(tokens):
        raise FormulaError("Unexpected trailing tokens in formula")
    return ast


def ast_codes(ast: dict) -> List[str]:
    """All {code} references in an AST, in source order (deduplicated)."""
    out: List[str] = []

    def _walk(node: dict) -> None:
        if "code" in node:
            if node["code"] not in out:
                out.append(node["code"])
        for arg in node.get("args", []) or []:
            _walk(arg)

    _walk(ast)
    return out


def render_expression(ast: dict) -> str:
    """Deterministic, auditable string form of an AST."""
    if "num" in ast:
        return _render_num(ast["num"])
    if "code" in ast:
        return "{%s}" % ast["code"]
    op = ast.get("op")
    args = ast.get("args", [])
    if op == "neg":
        return "-" + render_expression(args[0])
    left = render_expression(args[0])
    right = render_expression(args[1])
    return f"({left} {op} {right})"


def _render_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class _Missing:
    """Sentinel: a referenced element has no value this period."""


class _ZeroDenominator(Exception):
    """Raised inside evaluation when a divisor evaluates to 0."""


def evaluate(ast: dict, values: Dict[str, float]) -> Tuple[Optional[float], str]:
    """Evaluate a validated AST against code->value mappings.

    Returns (value, status). ``values`` only contains codes that actually
    have numeric data — an absent key propagates STATUS_MISSING, a reported
    0.0 is an ordinary number.
    """
    def _eval(node: dict):
        if "num" in node:
            return float(node["num"])
        if "code" in node:
            code = node["code"]
            if code not in values:
                return _Missing
            return float(values[code])
        op = node.get("op")
        if op == "neg":
            v = _eval(node["args"][0])
            return _Missing if isinstance(v, _Missing) else -v
        left = _eval(node["args"][0])
        if isinstance(left, _Missing):
            return _Missing
        right = _eval(node["args"][1])
        if isinstance(right, _Missing):
            return _Missing
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise _ZeroDenominator
            return left / right
        raise FormulaError(f"Unknown operator '{op}'")

    try:
        result = _eval(ast)
    except _ZeroDenominator:
        return None, STATUS_ZERO_DENOMINATOR
    except FormulaError as exc:
        logger.warning("indicator expression evaluation failed: %s", exc)
        return None, STATUS_ERROR
    if isinstance(result, _Missing):
        return None, STATUS_MISSING
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        return None, STATUS_ERROR
    return float(result), STATUS_OK


# ═══════════════════════════════════════════════════════════════════════════
# Aggregation + ratio/expression computation (pure functions)
# ═══════════════════════════════════════════════════════════════════════════

def aggregate(codes: Sequence[str], values: Dict[str, float],
              how: str = "sum") -> Tuple[Optional[float], List[str]]:
    """Combine several raw elements into one part.

    Returns (aggregate, missing_codes). Strict on purpose: ONE missing
    element invalidates the whole part (the same doctrine as
    rate_config.compute_rate) — a partial sum would silently understate
    clinical rates. Reported zeros aggregate like any other number.
    """
    codes = [c for c in (codes or []) if c]
    if not codes:
        return None, []
    missing = [c for c in codes if c not in values]
    if missing:
        return None, missing
    nums = [float(values[c]) for c in codes]
    if how == "avg":
        return sum(nums) / len(nums), []
    if how == "max":
        return max(nums), []
    if how == "min":
        return min(nums), []
    if how == "sum":
        return sum(nums), []
    raise FormulaError(f"Unknown aggregation '{how}'")


@dataclass
class ComputeOutcome:
    value: Optional[float] = None
    status: str = STATUS_NO_DATA
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    inputs: Dict[str, Optional[float]] = field(default_factory=dict)
    missing_codes: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


_ROUND_QUANTS = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
}


def round_value(value: Optional[float], precision: Optional[int],
                rounding: Optional[str] = "half_up") -> Optional[float]:
    """Apply a definition's configured precision/rounding to a computed
    value. precision None / out of range / unknown mode → value unchanged,
    so legacy definitions (no precision) keep their exact float results.
    Decimal is used so half_up is true ROUND_HALF_UP (Python's round() is
    banker's rounding, which users do not expect from a "half up" label).
    """
    if value is None:
        return None
    if precision is None or not (0 <= int(precision) <= MAX_PRECISION):
        return value
    quant = Decimal(1).scaleb(-int(precision))
    mode = _ROUND_QUANTS.get(rounding or "half_up", ROUND_HALF_UP)
    return float(Decimal(repr(float(value))).quantize(quant, rounding=mode))


def definition_codes(definition) -> List[str]:
    """Every raw data-element code a definition depends on."""
    if getattr(definition, "formula_type", "ratio") == "expression":
        expr = getattr(definition, "expression", None) or ""
        return ast_codes(parse_expression(expr))
    num = list(getattr(definition, "numerator_codes", None) or [])
    den = list(getattr(definition, "denominator_codes", None) or [])
    out: List[str] = []
    for c in num + den:
        if c and c not in out:
            out.append(c)
    return out


def build_ratio_expression(numerator_codes: Sequence[str],
                           denominator_codes: Sequence[str],
                           operator: str = "/",
                           multiplier: float = 1.0) -> str:
    """Canonical parseable formula string for the ratio shape — stored on
    the definition for auditability and echoed in previews."""
    num = [c for c in (numerator_codes or []) if c]
    den = [c for c in (denominator_codes or []) if c]
    left = " + ".join("{%s}" % c for c in num) or "0"
    if len(num) > 1:
        left = "(" + left + ")"
    right = " + ".join("{%s}" % c for c in den)
    if den:
        if len(den) > 1:
            right = "(" + right + ")"
        core = f"{left} {operator} {right}"
        if operator != "/":
            core = f"({core})"
    else:
        core = left
    mult = float(multiplier or 1.0)
    if mult != 1.0:
        core = f"{core} * {_render_num(mult)}"
    return core


def evaluate_definition(definition, raw: Dict[str, Optional[float]]) -> ComputeOutcome:
    """Pure evaluation of a definition against raw rows of ONE hospital+month.

    ``raw`` maps every REFERENCED code that has a stored row to its value
    (a row exists with value NULL → key present with None). A code absent
    from the map has no row at all for that period.
    """
    formula_type = getattr(definition, "formula_type", "ratio") or "ratio"
    agg = getattr(definition, "aggregation", "sum") or "sum"
    multiplier = float(getattr(definition, "multiplier", 1.0) or 1.0)

    outcome = ComputeOutcome()
    try:
        codes = definition_codes(definition)
    except FormulaError as exc:
        outcome.status = STATUS_ERROR
        outcome.message = str(exc)
        return outcome
    if not codes:
        outcome.status = STATUS_ERROR
        outcome.message = "Definition references no data elements"
        return outcome
    outcome.inputs = {c: raw.get(c) for c in codes}

    rows_present = [c for c in codes if c in raw]
    if not rows_present:
        outcome.status = STATUS_NO_DATA
        outcome.message = "No data reported for this period"
        return outcome

    values = {c: float(v) for c, v in raw.items() if v is not None}
    if not values:
        outcome.status = STATUS_MISSING
        outcome.missing_codes = list(codes)
        outcome.message = "Reported rows contain no values"
        return outcome

    if formula_type == "expression":
        try:
            ast = parse_expression(getattr(definition, "expression", "") or "")
        except FormulaError as exc:
            outcome.status = STATUS_ERROR
            outcome.message = str(exc)
            return outcome
        missing = [c for c in ast_codes(ast) if c not in values]
        if missing:
            outcome.status = STATUS_MISSING
            outcome.missing_codes = missing
            outcome.message = "Missing value for: " + ", ".join(missing)
            return outcome
        value, status = evaluate(ast, values)
        if status == STATUS_ZERO_DENOMINATOR:
            outcome.status = status
            outcome.message = "Division by zero in formula"
            return outcome
        if status != STATUS_OK:
            outcome.status = status
            outcome.message = "Missing value in formula"
            outcome.missing_codes = missing
            return outcome
        outcome.value = round_value(
            value * multiplier,
            getattr(definition, "precision", None),
            getattr(definition, "rounding", "half_up"))
        outcome.status = STATUS_OK
        return outcome

    # ── ratio shape ────────────────────────────────────────────────────────
    operator = getattr(definition, "operator", "/") or "/"
    num_codes = [c for c in (getattr(definition, "numerator_codes", None) or []) if c]
    den_codes = [c for c in (getattr(definition, "denominator_codes", None) or []) if c]
    if not num_codes:
        outcome.status = STATUS_ERROR
        outcome.message = "Numerator is empty"
        return outcome

    numerator, num_missing = aggregate(num_codes, values, agg)
    if numerator is None:
        outcome.status = STATUS_MISSING
        outcome.missing_codes = num_missing
        outcome.message = "Missing numerator value for: " + ", ".join(num_missing)
        return outcome
    outcome.numerator = numerator

    denominator: Optional[float] = None
    if den_codes:
        denominator, den_missing = aggregate(den_codes, values, agg)
        if denominator is None:
            outcome.status = STATUS_MISSING
            outcome.missing_codes = den_missing
            outcome.message = "Missing denominator value for: " + ", ".join(den_missing)
            return outcome
        outcome.denominator = denominator

    if operator == "/":
        if denominator is None:
            outcome.status = STATUS_ERROR
            outcome.message = "Division requires a denominator"
            return outcome
        if denominator == 0:
            outcome.status = STATUS_ZERO_DENOMINATOR
            outcome.message = "Denominator is zero"
            return outcome
        base = numerator / denominator
    elif operator == "*":
        base = numerator * (denominator if denominator is not None else 1.0)
    elif operator == "+":
        base = numerator + (denominator if denominator is not None else 0.0)
    elif operator == "-":
        base = numerator - (denominator if denominator is not None else 0.0)
    else:
        outcome.status = STATUS_ERROR
        outcome.message = f"Unknown operator '{operator}'"
        return outcome

    outcome.value = round_value(
        base * multiplier,
        getattr(definition, "precision", None),
        getattr(definition, "rounding", "half_up"))
    outcome.status = STATUS_OK
    return outcome


def evaluate_ratio_values(
    numerator_codes: Sequence[str],
    denominator_codes: Sequence[str],
    raw: Dict[str, Optional[float]],
    multiplier: float = 1.0,
    aggregation: str = "sum",
    operator: str = "/",
) -> ComputeOutcome:
    """Evaluate a ratio-shaped definition through the shared formula engine."""
    from types import SimpleNamespace

    return evaluate_definition(
        SimpleNamespace(
            formula_type="ratio",
            expression=None,
            numerator_codes=list(numerator_codes or ()),
            denominator_codes=list(denominator_codes or ()),
            multiplier=multiplier,
            aggregation=aggregation,
            operator=operator,
            precision=None,
            rounding="half_up",
        ),
        raw,
    )


# ═══════════════════════════════════════════════════════════════════════════
# DB access — raw rows in, stored results out
# ═══════════════════════════════════════════════════════════════════════════

def load_raw_values(db, codes: Sequence[str], hospital_id: int,
                    month: str) -> Dict[str, Optional[float]]:
    """Stored raw rows for the referenced codes at one hospital+month.

    Returned map only contains codes with an actual row; a NULL value
    appears as None (present-but-empty), an unreported code is absent.
    """
    codes = [c for c in (codes or []) if c]
    if not codes:
        return {}
    from app.models import Indicator, IndicatorValue
    rows = (
        db.query(Indicator.code, IndicatorValue.value)
        .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
        .filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.month == month,
            Indicator.code.in_(list(codes)),
        )
        .all()
    )
    return {code: (None if val is None else float(val)) for code, val in rows}


def compute_for_hospital_month(db, definition, hospital_id: int,
                               month: str) -> ComputeOutcome:
    """Read raw data for one hospital+month and evaluate the definition."""
    try:
        codes = definition_codes(definition)
    except FormulaError as exc:
        outcome = ComputeOutcome(status=STATUS_ERROR, message=str(exc))
        return outcome
    raw = load_raw_values(db, codes, hospital_id, month)
    return evaluate_definition(definition, raw)


def compute_and_store(db, definition, hospital_id: int, month: str):
    """Evaluate and upsert the IndicatorResult row (caller commits).

    Stored rows stamp the definition_version used, so a later formula edit
    leaves them visibly stale until an explicit recompute.
    """
    from app.models import IndicatorResult
    outcome = compute_for_hospital_month(db, definition, hospital_id, month)
    import json
    row = db.query(IndicatorResult).filter(
        IndicatorResult.definition_id == definition.id,
        IndicatorResult.hospital_id == hospital_id,
        IndicatorResult.month == month,
    ).first()
    if row is None:
        row = IndicatorResult(
            definition_id=definition.id,
            definition_code=definition.code,
            hospital_id=hospital_id,
            month=month,
        )
        db.add(row)
    row.value = outcome.value
    row.status = outcome.status
    row.numerator = outcome.numerator
    row.denominator = outcome.denominator
    row.inputs = json.dumps(
        {c: outcome.inputs.get(c) for c in sorted(outcome.inputs)},
        default=str,
    )
    row.definition_version = int(getattr(definition, "version", 1) or 1)
    from datetime import datetime
    row.computed_at = datetime.utcnow()
    return outcome


def latest_data_month(db) -> Optional[str]:
    from app.models import IndicatorValue
    row = db.query(IndicatorValue.month).order_by(IndicatorValue.month.desc()).first()
    return row[0] if row else None


def recompute(db, month: Optional[str] = None, hospital_id: Optional[int] = None,
              definition_id: Optional[int] = None,
              active_only: bool = True) -> Dict[str, object]:
    """Explicit recompute of stored results (never runs implicitly).

    Returns a summary with per-status counts. Rows keep the version they
    were computed with — only this call rewrites them.
    """
    from app.models import Hospital, IndicatorDefinition

    month = month or latest_data_month(db)
    if not month:
        return {"month": None, "computed": 0, "message": "No data available"}

    q = db.query(IndicatorDefinition)
    if definition_id is not None:
        q = q.filter(IndicatorDefinition.id == definition_id)
    q = q.filter(IndicatorDefinition.is_system.is_(False))
    if active_only:
        q = q.filter(IndicatorDefinition.is_active.is_(True))
    definitions = q.order_by(IndicatorDefinition.code).all()

    hq = db.query(Hospital).filter(Hospital.is_active.is_(True))
    if hospital_id is not None:
        hq = hq.filter(Hospital.id == hospital_id)
    hospitals = hq.all()
    if hospital_id is not None and not hospitals:
        return {"month": month, "computed": 0, "message": "Hospital not found"}

    counts: Dict[str, int] = {s: 0 for s in STATUS_ALL}
    computed = 0
    for definition in definitions:
        for hospital in hospitals:
            outcome = compute_and_store(db, definition, hospital.id, month)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            computed += 1
    db.commit()
    return {
        "month": month,
        "computed": computed,
        "definitions": len(definitions),
        "hospitals": len(hospitals),
        "counts": counts,
        "message": f"Computed {computed} result(s) for {month}",
    }


def codes_with_data(db, codes: Sequence[str], month: str,
                    hospital_id: Optional[int] = None) -> Dict[str, int]:
    """Row counts per code for a period — period-applicability validation."""
    from app.models import Indicator, IndicatorValue
    codes = [c for c in (codes or []) if c]
    if not codes:
        return {}
    q = (
        db.query(Indicator.code, IndicatorValue.id)
        .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
        .filter(IndicatorValue.month == month,
                Indicator.code.in_(list(codes)))
    )
    if hospital_id is not None:
        q = q.filter(IndicatorValue.hospital_id == hospital_id)
    out = {c: 0 for c in codes}
    for code, _id in q.all():
        out[code] = out.get(code, 0) + 1
    return out
