import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .definitions import DEFAULT_RULES_POLICY, RULE_REF_CODES, RulesPolicy


_SET_RULES_CONFIG_CALLS = 0


def set_rules_config(config: dict):
    """Deprecated compatibility shim (A3.5) — moves no evaluation state.

    Rule evaluation reads an explicit :class:`RulesPolicy` (``ctx.rules`` and
    ``compute_covered_codes(..., rules=...)``) resolved from the operation's
    ``PolicySnapshot``. This function is kept only so an out-of-tree caller
    does not crash; it records the call and leaves the documented defaults
    untouched, so process history can no longer rewrite them.
    """
    global _SET_RULES_CONFIG_CALLS
    _SET_RULES_CONFIG_CALLS += 1


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RuleType(str, Enum):
    LOGIC = "LOGIC"
    CLINICAL = "CLINICAL"
    DATA_QUALITY = "DATA_QUALITY"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class RuleResult:
    rule_code: str
    description: str
    status: RuleStatus
    severity: Severity
    rule_type: RuleType
    details: str = ""


@dataclass
class ValidationContext:
    values: Dict[str, float]
    hospital_name: str
    month: str
    all_hospital_data: Optional[Dict[str, Dict[str, float]]] = None
    historical_data: Optional[Dict[str, Dict[str, float]]] = None
    disabled_codes: set = field(default_factory=set)
    rules: RulesPolicy = field(default_factory=lambda: DEFAULT_RULES_POLICY)


def _v(ctx: ValidationContext, code: str) -> Optional[float]:
    return ctx.values.get(code)


def _vs(ctx: ValidationContext, codes: List[str]) -> float:
    total = 0.0
    for c in codes:
        val = ctx.values.get(c)
        if val is not None:
            total += val
    return total


def _has_any(ctx: ValidationContext, codes: List[str]) -> bool:
    return any(ctx.values.get(c) is not None for c in codes)


# ── one comparison policy for every comparison type ─────────────────
#
# Every parent/child comparison — the nine legacy types and `compare` — is the
# same question ("operand A <op> operand B") and answers it with ONE policy:
#
# * **Tolerance.** A single epsilon, the rules policy's ``eq_tolerance``, is
#   the only tolerance. For ``=``/``!=`` it is an equality tolerance; for
#   ``>``, ``>=``, ``<``, ``<=`` it is the slack that separates "equal" from
#   "ordered", so ``>`` means "greater by more than epsilon". Nothing is
#   compared bit-exactly: computed sums are rarely bit-exact.
# * **Missing data.** A side that carries no value makes the comparison
#   *not evaluable*, and it PASSes. An unreported total is never silently read
#   as zero, and no data never produces a FAIL.
# * **Zero/zero.** Both sides zero means "no activity" and PASSes for every
#   type.
#
# The retired helpers used to disagree on all three (ge/le/lt compared
# bit-exactly, only some types required data on both sides, and parent_lt
# failed at 0 vs 0). They now route through :func:`_run_comparison`, so the
# nine types and `compare` cannot drift apart again.

def _single(code: str) -> dict:
    return {"codes": [code] if code else [], "agg": "single"}


def _sum(codes: List[str]) -> dict:
    return {"codes": [c for c in (codes or []) if c], "agg": "sum"}


def _operand_value(spec: dict, ctx: ValidationContext):
    """Return (value, has_data) for one comparison side."""
    codes = [c for c in (spec.get("codes") or []) if c]
    if not codes:
        return None, False
    agg = str(spec.get("agg") or ("single" if len(codes) == 1 else "sum")).lower()
    if agg == "single":
        value = _v(ctx, codes[0])
        return value, value is not None
    return _vs(ctx, codes), _has_any(ctx, codes)


def _comparison_holds(left: float, right: float, op: str, epsilon: float) -> bool:
    """Evaluate one comparison; ``epsilon`` is the only tolerance."""
    if op == "=":
        return abs(left - right) <= epsilon
    if op == "!=":
        return abs(left - right) > epsilon
    if op == ">":
        return left - right > epsilon
    if op == ">=":
        return left - right >= -epsilon
    if op == "<":
        return right - left > epsilon
    return right - left >= -epsilon  # '<='


@dataclass
class _Comparison:
    """Outcome of one comparison before it is turned into a RuleResult.

    ``state`` is one of ``skipped`` (a side has no value), ``zero`` (both sides
    zero), ``pass`` or ``fail``. ``left``/``right`` are the raw operand values
    and ``scaled`` is the left side after the optional factor.
    """
    state: str
    left: Optional[float] = None
    right: Optional[float] = None
    scaled: Optional[float] = None


def _run_comparison(left: dict, right: dict, op: str, ctx: ValidationContext,
                    factor: float = 1.0) -> _Comparison:
    """Apply the shared comparison policy to two operands."""
    left_value, left_has = _operand_value(left, ctx)
    right_value, right_has = _operand_value(right, ctx)
    if not left_has or not right_has:
        return _Comparison("skipped", left_value, right_value)
    if left_value == 0 and right_value == 0:
        return _Comparison("zero", left_value, right_value)
    scaled = left_value * factor
    ok = _comparison_holds(scaled, right_value, op, ctx.rules.eq_tolerance)
    return _Comparison("pass" if ok else "fail", left_value, right_value, scaled)


def _ge(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """parent >= sum(children), within the comparison epsilon."""
    out = _run_comparison(_single(parent), _sum(children), ">=", ctx)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both sides are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={out.left} but children sum={out.right}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={out.left} >= children sum={out.right}")


def _gt(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """Strict greater-than: FAIL when parent <= sum of children (within epsilon)."""
    out = _run_comparison(_single(parent), _sum(children), ">", ctx)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both parent and children sum are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={out.left} but children sum={out.right} (parent must be strictly greater)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={out.left} > children sum={out.right}")


def _ge_factor(parent: str, children: List[str], factor: float, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """Factor tolerance: FAIL when sum of children > parent * factor (within epsilon)."""
    out = _run_comparison(_single(parent), _sum(children), ">=", ctx, factor)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both sides are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}x{factor}={out.scaled:.2f} but children sum={out.right}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}x{factor}={out.scaled:.2f} >= children sum={out.right}")


def _parent_le(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """Reverse of ge: FAIL when the parent value exceeds the sum of its children.

    Complements _gt exactly — _gt FAILs when cs >= pv - eps, this FAILs when
    pv > cs + eps — so the two together reconcile a parent against a breakdown.
    """
    out = _run_comparison(_single(parent), _sum(children), "<=", ctx)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both sides are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={out.left} but children sum={out.right} (parent must not exceed)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={out.left} <= children sum={out.right}")


def _parent_lt(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """Strict reverse of ge: FAIL when the parent value is >= the sum of its children.

    Strict companion of parent_le — parent_le allows equality within epsilon,
    parent_lt requires the parent to be smaller by more than epsilon.
    """
    out = _run_comparison(_single(parent), _sum(children), "<", ctx)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both sides are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={out.left} >= children sum={out.right} (parent must be strictly less)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={out.left} < children sum={out.right}")


def _lt(child: str, parent: str, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """Strict less-than: FAIL when child >= parent (within epsilon)."""
    out = _run_comparison(_single(child), _single(parent), "<", ctx)
    if out.state == "skipped":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Missing data")
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both child and parent are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{child}={out.left} >= {parent}={out.right} (child must be strictly less)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{child}={out.left} < {parent}={out.right}")


def _eq(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """parent == sum(children), within the comparison epsilon."""
    out = _run_comparison(_single(parent), _sum(children), "=", ctx)
    if out.state == "skipped":
        detail = "No data available" if out.left is None else "No child data to compare"
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, detail)
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both sides are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype,
                          f"{parent}={out.left} but children sum={out.right}, diff={abs(out.left - out.right):.2f}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={out.left} == children sum={out.right}")


def _le(child: str, parent: str, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    """child <= parent, within the comparison epsilon."""
    out = _run_comparison(_single(child), _single(parent), "<=", ctx)
    if out.state == "skipped":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Missing data")
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Both child and parent are zero (no activity)")
    if out.state == "fail":
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{child}={out.left} > {parent}={out.right}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{child}={out.left} <= {parent}={out.right}")


def _month_over(month_code: str, prev_data: Optional[Dict[str, float]], factor: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    cur = _v(ctx, month_code)
    if cur is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No current data")
    if prev_data is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No previous month data")
    prev = prev_data.get(month_code)
    if prev is None or prev == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value missing or zero")
    if prev < 0:
        # A negative baseline makes the percentage change meaningless (the sign
        # flips), so it is not evidence of a spike. The negative value itself is
        # a data-quality problem for the value checks, not for the trend.
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value is negative")
    change_pct = ((cur - prev) / prev) * 100
    if change_pct > factor * 100:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{cur} is {change_pct:+.0f}% vs previous {prev} (>{factor*100:.0f}%)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"Change {change_pct:+.0f}% (OK)")


def _month_under(month_code: str, prev_data: Optional[Dict[str, float]], factor: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    cur = _v(ctx, month_code)
    if cur is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No current data")
    if prev_data is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No previous month data")
    prev = prev_data.get(month_code)
    if prev is None or prev == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value missing or zero")
    if prev < 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value is negative")
    change_pct = ((prev - cur) / prev) * 100
    if change_pct > factor * 100:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{cur} is {-(change_pct):.0f}% drop vs previous {prev} (<{factor*100:.0f}%)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"Change {((cur-prev)/prev)*100:+.0f}% (OK)")


# ── trend: one type for the month-over-month checks ──────────────────
#
# month_over and month_under ask the same question — how did this month move
# against the previous one — and differed only in direction and threshold:
#
#   {"direction": "over", "factor": 2.0, "codes": ["2"]}
#
# "over"  FAILs when the current value exceeds factor x previous (2.0 = +100%).
# "under" FAILs when it drops below factor x previous (0.5 = half).
# `codes` may list several indicators; the first failing one is reported.
#
# A baseline that is missing, zero or negative makes the percentage change
# meaningless, so the check PASSes: absence of a baseline is never evidence of
# a spike or a drop, and a negative baseline would flip the sign.

_TREND_DIRECTIONS = ("over", "under")
_TREND_DEFAULT_FACTORS = {"over": 2.0, "under": 0.5}

#: Legacy type -> direction. These types keep working as aliases.
_LEGACY_TREND_TYPES = {"month_over": "over", "month_under": "under"}

_TREND_DIRECTION_ALIASES = {
    "over": "over", "above": "over", "increase": "over", "up": "over",
    "month_over": "over",
    "under": "under", "below": "under", "decrease": "under", "down": "under",
    "month_under": "under",
}


def _trend_codes(raw) -> List[str]:
    if isinstance(raw, str):
        return [raw] if raw else []
    return [c for c in (raw or []) if c]


def _trend_factor(raw, direction: str) -> float:
    """Read the factor, falling back to the direction's documented default."""
    try:
        factor = float(raw)
    except (TypeError, ValueError):
        return _TREND_DEFAULT_FACTORS[direction]
    return factor if factor > 0 else _TREND_DEFAULT_FACTORS[direction]


def normalize_trend_params(expr: str, params: dict) -> Optional[dict]:
    """Translate a legacy month_over/month_under rule into the `trend` shape.

    Returns ``None`` when ``expr`` is not one of the two aliased types or when
    it names no indicator. Used by the alias dispatch and the tests, so both
    paths agree on the conversion.
    """
    direction = _LEGACY_TREND_TYPES.get(str(expr or "").strip().lower())
    if direction is None:
        return None
    params = params or {}
    codes = _trend_codes(params.get("codes") if params.get("codes") else params.get("code"))
    if not codes:
        return None
    return {"direction": direction,
            "factor": _trend_factor(params.get("factor"), direction),
            "codes": codes}


def trend_params(params: dict) -> Optional[dict]:
    """Normalize a `trend` rule's params, or None when direction/codes are unusable.

    Accepts ``{"direction": …, "factor": …, "codes": […]}`` and the one-code
    shorthand ``{"direction": …, "code": "2"}``. An unknown direction is
    rejected rather than guessed; a missing/zero factor falls back to the
    direction's default (2.0 over, 0.5 under).
    """
    params = params or {}
    raw_direction = str(params.get("direction") or params.get("type") or "").strip().lower()
    direction = _TREND_DIRECTION_ALIASES.get(raw_direction)
    if direction is None:
        return None
    codes = _trend_codes(params.get("codes") if params.get("codes") else params.get("code"))
    if not codes:
        return None
    return {"direction": direction,
            "factor": _trend_factor(params.get("factor"), direction),
            "codes": codes}


def _trend(normalized: dict, code: str, desc: str, sev: Severity,
           ctx: ValidationContext) -> RuleResult:
    """Run the month-over-month check for each indicator; first failure wins."""
    results = []
    many = len(normalized["codes"]) > 1
    for target in normalized["codes"]:
        if normalized["direction"] == "over":
            result = _month_over(target, ctx.historical_data, normalized["factor"],
                                 code, desc, sev, ctx)
        else:
            result = _month_under(target, ctx.historical_data, normalized["factor"],
                                  code, desc, sev, ctx)
        if many:
            result.details = f"[{target}] {result.details}"
        if result.status == RuleStatus.FAIL:
            return result
        results.append(result)
    if len(results) == 1:
        return results[0]
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY,
                      f"All {len(results)} trend checks passed")


def _neg_check(codes: List[str], code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    for c in codes:
        val = _v(ctx, c)
        if val is not None and val < 0:
            return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{c}={val} is negative")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "All values non-negative")


def _decimal_check(codes: List[str], code: str, desc: str, ctx: ValidationContext) -> RuleResult:
    for c in codes:
        val = _v(ctx, c)
        if val is not None and val != int(val):
            return RuleResult(code, desc, RuleStatus.FAIL, Severity.LOW, RuleType.DATA_QUALITY, f"{c}={val} is decimal (counts should be integers)")
    return RuleResult(code, desc, RuleStatus.PASS, Severity.LOW, RuleType.DATA_QUALITY, "All values are integers")


def _missing(indicator_code: str, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    val = _v(ctx, indicator_code)
    if val is None:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"Missing value for indicator {indicator_code}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"{indicator_code}={val}")


# Indicator codes are the dotted numbers of the data tree: 6, 6.e, 10.a.1.2.
_CODE_PATTERN = re.compile(r"^[0-9][0-9A-Za-z]*(?:\.[0-9A-Za-z]+)*$")

# Unicode signs typed or pasted from Word/Excel normalize to the ASCII operators
# the parser understands.
_UNICODE_OPERATORS = {
    "\u2212": "-",  # minus sign
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00d7": "*",  # multiplication sign
    "\u00f7": "/",  # division sign
}

_FORMULA_STRUCTURE = "+-*/()[]{}"


def _normalize_formula_text(formula: str) -> str:
    """Map Unicode arithmetic signs and non-breaking spaces to their ASCII form."""
    text = formula or ""
    for source, target in _UNICODE_OPERATORS.items():
        text = text.replace(source, target)
    return text.replace("\u00a0", " ")


def _parse_formula_tokens(formula: str):
    """Tokenize an expression into code references, numbers, operators and brackets.

    Two spellings of an indicator reference are accepted:

    * ``{6.e}`` — the canonical stored form.
    * ``Babies from multiples (6.e)`` — the human-readable form typed on the Rule
      Validation screen: the indicator's name followed by its code in
      parentheses. The name is only a label and is dropped, so it may contain
      digits and signs, as in ``Stillbirths >24w (7)``.

    ``[...]`` groups exactly like ``(...)``, and the Unicode signs ``−``, ``×``
    and ``÷`` are accepted for ``-``, ``*`` and ``/``.
    """
    text = _normalize_formula_text(formula)
    tokens = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '{':
            j = text.find('}', i + 1)
            if j == -1:
                raise ValueError("Unclosed '{' in formula")
            tokens.append(('code', text[i + 1:j].strip()))
            i = j + 1
        elif ch in _FORMULA_STRUCTURE:
            tokens.append(('op', ch))
            i += 1
        elif ch.isdigit():
            j = i
            while j < len(text) and (text[j].isdigit() or text[j] == '.'):
                j += 1
            tokens.append(('num', float(text[i:j])))
            i = j
        else:
            # Human-readable reference: an indicator name followed by "(code)".
            j = i
            while j < len(text) and text[j] not in _FORMULA_STRUCTURE:
                j += 1
            k = j
            while k < len(text) and text[k].isspace():
                k += 1
            if k < len(text) and text[k] == '(':
                m = text.find(')', k + 1)
                if m != -1:
                    code = text[k + 1:m].strip()
                    if code and _CODE_PATTERN.match(code):
                        tokens.append(('code', code))
                        i = m + 1
                        continue
            raise ValueError(
                f"Unexpected text '{text[i:j].strip() or text[i]}' at position {i} "
                "(write an indicator as {code} or as Name (code))"
            )
    return tokens


_BINARY_OPERATORS = ("+", "-", "*", "/")
_OPEN_BRACKETS = {"(": ")", "[": "]"}


def validate_formula_expression(expr: str) -> Optional[str]:
    """Return why an expression cannot be parsed or is incomplete, else None.

    Catches the two mistakes a stored rule must never contain — an unknown
    character/label (raised by the tokenizer) and a structure the parser can
    only return None for: a dangling operator, an operator without a left
    operand, or unbalanced parentheses/brackets.
    """
    if expr is None or not str(expr).strip():
        return "the expression is empty"
    try:
        tokens = _parse_formula_tokens(str(expr))
    except ValueError as exc:
        return str(exc)
    if not tokens:
        return "the expression is empty"
    depth = []
    last = None
    for kind, value in tokens:
        if kind == 'op':
            if value in _OPEN_BRACKETS:
                depth.append(_OPEN_BRACKETS[value])
            elif value in (')', ']'):
                if not depth or depth.pop() != value:
                    return "the parentheses / brackets are unbalanced"
            else:
                has_left = last is not None and (last[0] in ('num', 'code') or last[1] in (')', ']'))
                if not has_left and value != "-":
                    return f"operator '{value}' has no left operand"
        elif last is not None and last[0] in ('num', 'code'):
            return "two values follow each other without an operator"
        last = (kind, value)
    if depth:
        return "the parentheses / brackets are unbalanced"
    if last[0] == 'op' and last[1] in _BINARY_OPERATORS:
        return f"the expression ends with the operator '{last[1]}'"
    return None


def formula_referenced_codes(expr: str) -> list:
    """Indicator codes an expression references, in order of appearance.

    Understands both the ``{code}`` and the ``Name (code)`` spellings. A string
    the parser rejects falls back to the brace scan so a half-written rule still
    reports the codes it already names.
    """
    if not expr:
        return []
    try:
        return [tok[1] for tok in _parse_formula_tokens(str(expr)) if tok[0] == 'code']
    except Exception:
        return [c for c in re.findall(r'\{([^}]+)\}', str(expr)) if c.strip()]


def _eval_formula(expr_str: str, values: Dict[str, float]) -> Optional[float]:
    """Evaluate a math expression with {indicator} codes, constants, and operators +,-,*,/,().

    Codes referenced as {code} resolve from the values dict; a missing code yields None.
    Returns None if any referenced indicator is missing or on error.
    """
    try:
        tokens = _parse_formula_tokens(expr_str)
    except Exception:
        return None
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume():
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def parse_expr():
        result = parse_term()
        while peek() and peek()[1] in ('+', '-'):
            op = consume()[1]
            right = parse_term()
            if result is None or right is None:
                return None
            result = result + right if op == '+' else result - right
        return result

    def parse_term():
        result = parse_factor()
        while peek() and peek()[1] in ('*', '/'):
            op = consume()[1]
            right = parse_factor()
            if result is None or right is None:
                return None
            if op == '/' and right == 0:
                return None
            result = result * right if op == '*' else result / right
        return result

    def parse_factor():
        tok = peek()
        if tok is None:
            return None
        if tok[0] == 'num':
            consume()
            return tok[1]
        if tok[0] == 'code':
            consume()
            return values.get(tok[1])
        if tok[1] in ('(', '['):
            consume()
            result = parse_expr()
            if peek() is None or peek()[1] not in (')', ']'):
                raise ValueError("Unbalanced parentheses in formula")
            consume()
            return result
        if tok[1] == '-':
            consume()
            result = parse_factor()
            return -result if result is not None else None
        return None

    try:
        result = parse_expr()
        if pos[0] != len(tokens):
            raise ValueError("Unexpected trailing tokens in formula")
        return result
    except Exception:
        return None


_COMPARE_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


def _formula(formula_str: str, target_code: str, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext, op: str = "=", rhs: Optional[str] = None) -> RuleResult:
    """Compare a left-side expression with a right side using a comparison operator.

    The right side is either ``rhs`` — a second arithmetic expression over
    indicator codes, for two-sided rules such as
    ``Live births (6) + Stillbirths >24w (7) = Total deliveries (2) + [Babies from
    multiples (6.e) − Multiple pregnancies (6.d)]`` — or, when ``rhs`` is absent,
    a single target indicator code (the legacy ``target`` param).

    Supported ops: =, !=, >, <, >=, <=. Unknown ops fall back to '='.
    """
    if op not in _COMPARE_OPS:
        op = "="
    compare = _COMPARE_OPS[op]
    shown = "==" if op == "=" else op
    lhs_val = _eval_formula(formula_str, ctx.values)
    rhs_expr = (rhs or "").strip()

    if rhs_expr:
        rhs_val = _eval_formula(rhs_expr, ctx.values)
        if lhs_val is None or rhs_val is None:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Expression could not be evaluated (missing data)")
        if compare(lhs_val, rhs_val):
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Left={lhs_val} {shown} Right={rhs_val}")
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype,
                          f"Left={lhs_val} {op} Right={rhs_val} (diff={abs(lhs_val - rhs_val):.2f})")

    target_val = _v(ctx, target_code) if target_code else None
    if lhs_val is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Formula could not be evaluated (missing data)")
    if target_val is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Target indicator {target_code} missing")
    if compare(lhs_val, target_val):
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Formula={lhs_val} {shown} {target_code}={target_val}")
    return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"Formula={lhs_val} {op} {target_code}={target_val}")


# ── compare: one comparison type for the parent/child family ────────
#
# ge, gt, eq, ge_factor, le, lt, le_sum, parent_le and parent_lt are all the
# same comparison — "operand A <op> operand B" — differing only in which side
# is the parent, the tolerance policy and the strictness. `compare` states all
# of that directly:
#
#   {"left":  {"codes": ["2"],          "agg": "single"},
#    "right": {"codes": ["6.e", "6.d"], "agg": "sum"},
#    "op": ">=", "factor": 1.1}
#
# Only left, right and op are required (plus ``factor`` for a factored bound).
# Tolerance, the missing-data rule and the 0/0 exemption are NOT per-rule
# switches: every comparison type shares the single policy documented above,
# so `compare` and the nine legacy types cannot evaluate differently.

_COMPARE_OPERATORS = ("=", "!=", ">", ">=", "<", "<=")

#: Legacy type -> (left role, right role, op, factor key). Roles, operator and
#: factor are the only things that ever differed; everything else is shared.
_LEGACY_COMPARE_BLUEPRINT = {
    "ge":        ("parent", "children", ">=", None),
    "gt":        ("parent", "children", ">",  None),
    "eq":        ("parent", "children", "=",  None),
    "ge_factor": ("parent", "children", ">=", "factor"),
    "le":        ("child",  "parent",   "<=", None),
    "lt":        ("child",  "parent",   "<",  None),
    "le_sum":    ("child",  "children", ">=", None),
    "parent_le": ("parent", "children", "<=", None),
    "parent_lt": ("parent", "children", "<",  None),
}

#: The comparison types `compare` replaces, in dropdown order.
LEGACY_COMPARE_TYPES = tuple(_LEGACY_COMPARE_BLUEPRINT)


def _compare_operand(role: str, params: dict) -> dict:
    """Build one compare side from a legacy role name."""
    if role == "children":
        return _sum(params.get("children") or [])
    return _single(params.get(role))


def normalize_compare_params(expr: str, params: dict) -> Optional[dict]:
    """Translate a legacy comparison rule's params into the `compare` shape.

    Returns ``None`` when ``expr`` is not one of the nine replaced types or
    when its params cannot name both sides. Only the roles, the operator and
    the optional factor are translated; tolerance, missing data and the 0/0
    exemption are the shared comparison policy, not per-rule settings, so the
    converted rule evaluates exactly as its legacy type does.
    """
    blueprint = _LEGACY_COMPARE_BLUEPRINT.get(str(expr or "").strip().lower())
    if blueprint is None:
        return None
    left_role, right_role, op, factor_key = blueprint
    params = params or {}
    left = _compare_operand(left_role, params)
    right = _compare_operand(right_role, params)
    if not left["codes"] or not right["codes"]:
        return None
    normalized = {"left": left, "right": right, "op": op}
    if factor_key:
        normalized["factor"] = float(params.get(factor_key) or 1.0)
    return normalized


def compare_params(params: dict) -> Optional[dict]:
    """Normalize a `compare` rule's params, or None when a side is missing.

    A rule whose params still carry the legacy keys can be evaluated as compare
    by naming its old type explicitly — ``{"legacy": "ge", "parent": …}`` —
    which is what a migration that only renames expression_type leaves behind.

    Per-rule ``tolerance`` / ``require_right`` / ``zero_passes`` keys are
    dropped rather than honoured: the comparison policy is shared, so a stored
    payload cannot reintroduce a divergent rule.
    """
    params = params or {}
    if not params.get("left") and params.get("legacy"):
        return normalize_compare_params(params.get("legacy"), params)

    def _side(value):
        return value if isinstance(value, dict) else _single(value)

    if not params.get("left") or not params.get("right"):
        return None
    out = dict(params)
    out["left"] = _side(params["left"])
    out["right"] = _side(params["right"])
    op = str(out.get("op") or ">=").strip()
    out["op"] = "=" if op == "==" else op
    if out["op"] not in _COMPARE_OPERATORS:
        out["op"] = ">="
    for stale in ("tolerance", "require_right", "zero_passes"):
        out.pop(stale, None)
    try:
        out["factor"] = float(out.get("factor") or 1.0)
    except (TypeError, ValueError):
        out["factor"] = 1.0
    return out


def _fmt_num(value: float) -> str:
    """Render a comparison value without a trailing '.0' (105, not 105.0)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:g}" if isinstance(value, float) else str(value)


def _compare(normalized: dict, code: str, desc: str, sev: Severity, rtype: RuleType,
             ctx: ValidationContext) -> RuleResult:
    """Compare two operands (a single indicator or a sum of indicators)."""
    factor = normalized.get("factor") or 1.0
    op = normalized["op"]
    out = _run_comparison(normalized["left"], normalized["right"], op, ctx, factor)
    if out.state == "skipped":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                          "Comparison could not be evaluated (missing data)")
    if out.state == "zero":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                          "Both sides are zero (no activity)")
    shown_left = _fmt_num(out.left) + (f"x{_fmt_num(factor)}" if factor != 1.0 else "")
    if out.state == "pass":
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                          f"Left={shown_left} {op} Right={_fmt_num(out.right)}")
    return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype,
                      f"Left={shown_left} {op} Right={_fmt_num(out.right)} does not hold")


ALL_ZERO_DEFAULT_CODES = ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]


def _all_zero_check(ctx: ValidationContext, code: str, desc: str,
                    codes: Optional[List[str]] = None) -> RuleResult:
    """FAIL when every code in ``codes`` is zero.

    ``codes`` comes from the rule's params so a rule built in the Rules Manager
    is evaluated against exactly the indicators it displays. It previously
    ignored params entirely and always used the hardcoded key-indicator list, so
    a rule defined as codes ["2","3","4","5","6"] silently tested eleven
    indicators and could contradict its own definition.
    """
    key_codes = list(codes) if codes else ALL_ZERO_DEFAULT_CODES
    all_zero = True
    has_data = False
    for c in key_codes:
        val = _v(ctx, c)
        if val is not None:
            has_data = True
            if val != 0:
                all_zero = False
                break
    if not has_data:
        return RuleResult(code, desc, RuleStatus.PASS, Severity.CRITICAL, RuleType.DATA_QUALITY, "No indicator data available")
    if all_zero:
        return RuleResult(code, desc, RuleStatus.FAIL, Severity.CRITICAL, RuleType.DATA_QUALITY, "All key indicators are zero - facility may be non-operational or data missing")
    return RuleResult(code, desc, RuleStatus.PASS, Severity.CRITICAL, RuleType.DATA_QUALITY, "Facility has non-zero indicator data")


# ── value_check: one type for the four indicator-value checks ────────
#
# neg_check, decimal_check, missing and all_zero all ask a question about the
# values of a list of indicators, not about how they relate to each other.
# `value_check` states the questions directly:
#
#   {"checks": [
#       {"kind": "negative", "codes": ["2", "3"]},
#       {"kind": "decimal",  "codes": ["2", "6"]},
#       {"kind": "missing",  "codes": ["2"]},
#       {"kind": "all_zero", "codes": ["2", "3"]}]}
#
# Checks run in order and the first failing one is reported, so a single-check
# rule reproduces its legacy type's message exactly. `missing` and `all_zero`
# accept several codes; `all_zero` with no codes keeps the key-indicator
# default. Severity is intrinsic to the kind — decimal is LOW and all_zero
# CRITICAL as before, negative and missing use the rule's severity.

_VALUE_CHECK_KINDS = ("negative", "decimal", "missing", "all_zero")

#: Legacy type -> check kind. These types keep working as aliases.
_LEGACY_VALUE_CHECK_TYPES = {
    "neg_check": "negative",
    "decimal_check": "decimal",
    "missing": "missing",
    "all_zero": "all_zero",
}

_VALUE_CHECK_KIND_ALIASES = {
    "neg": "negative",
    "neg_check": "negative",
    "negative": "negative",
    "decimal": "decimal",
    "decimal_check": "decimal",
    "missing": "missing",
    "all_zero": "all_zero",
    "allzero": "all_zero",
}


def _value_check_codes(raw) -> List[str]:
    """Read a check's codes, accepting one code or a list."""
    if isinstance(raw, str):
        return [raw] if raw else []
    return [c for c in (raw or []) if c]


def normalize_value_check_params(expr: str, params: dict) -> Optional[dict]:
    """Translate a legacy value-check rule's params into the `value_check` shape.

    Returns ``None`` when ``expr`` is not one of the four aliased types or when
    its params name no code (`all_zero` may legitimately name none and keeps
    the key-indicator default). Used by the alias dispatch, the migration
    script and the tests, so all three agree on the conversion.
    """
    kind = _LEGACY_VALUE_CHECK_TYPES.get(str(expr or "").strip().lower())
    if kind is None:
        return None
    params = params or {}
    if kind == "missing":
        raw = params.get("codes") if params.get("codes") else params.get("code")
    else:
        raw = params.get("codes")
    codes = _value_check_codes(raw)
    if not codes and kind != "all_zero":
        return None
    return {"checks": [{"kind": kind, "codes": codes}]}


def value_check_params(params: dict) -> Optional[list]:
    """Normalize a `value_check` rule's params into a list of checks, or None.

    Accepts the canonical ``{"checks": […]}`` and the one-check shorthand
    ``{"kind": …, "codes": […]}`` / ``{"kind": "missing", "code": "2"}``.
    Unknown or codeless kinds are dropped; a payload with no usable check
    returns ``None`` so the caller can report it instead of passing silently.
    """
    params = params or {}
    raw_checks = params.get("checks")
    if raw_checks is None and params.get("kind"):
        raw_checks = [params]
    checks = []
    for raw in raw_checks or []:
        if not isinstance(raw, dict):
            continue
        kind = _VALUE_CHECK_KIND_ALIASES.get(
            str(raw.get("kind") or raw.get("type") or "").strip().lower())
        if kind is None:
            continue
        codes = _value_check_codes(raw.get("codes") if raw.get("codes") else raw.get("code"))
        if not codes and kind != "all_zero":
            continue
        checks.append({"kind": kind, "codes": codes})
    return checks or None


def _value_check(checks: list, code: str, desc: str, sev: Severity,
                 ctx: ValidationContext) -> RuleResult:
    """Run the value checks in order; the first failure is the rule's result."""
    results = []
    for check in checks:
        kind = check["kind"]
        codes = check["codes"]
        if kind == "negative":
            results.append(_neg_check(codes, code, desc, sev, ctx))
        elif kind == "decimal":
            results.append(_decimal_check(codes, code, desc, ctx))
        elif kind == "all_zero":
            results.append(_all_zero_check(ctx, code, desc, codes or None))
        else:  # missing — one result per code, first missing value fails
            for indicator in codes:
                results.append(_missing(indicator, code, desc, sev, ctx))
    failed = next((r for r in results if r.status == RuleStatus.FAIL), None)
    if failed is not None:
        return failed
    if len(results) == 1:
        return results[0]
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY,
                      f"All {len(results)} value checks passed")


ALL_RULES = []


# Single source of truth for parent/child sum rules (eq: parent == sum of children,
# ge: parent >= sum of children). Used both to register compiled rules and to compute
# "covered" children whose absence is already explained by a reported total.
SUM_RULE_SPECS = [
    ("R001", "ge", "2", ["3", "4", "5"], "Total Deliveries >= NVD + Assisted + C-sections", Severity.HIGH, RuleType.LOGIC),
    ("R002", "eq", "2", ["2.a", "2.b"], "Primigravida + Multigravida ≈ Total Deliveries", Severity.MEDIUM, RuleType.LOGIC),
    ("R003", "eq", "2", ["2.c", "2.d", "2.e", "2.f", "2.g", "2.h", "2.i", "2.j"], "Age group sum ≈ Total Deliveries", Severity.LOW, RuleType.LOGIC),
    ("R004", "eq", "2", ["2.k", "2.l"], "In-facility + Out-of-facility ≈ Total Deliveries", Severity.HIGH, RuleType.LOGIC),
    ("R005", "eq", "2", ["2.m", "2.n"], "Low Risk + High Risk ≈ Total Deliveries", Severity.MEDIUM, RuleType.LOGIC),
    ("R006", "eq", "5", ["5.b.1", "5.b.2"], "Emergency + Planned C/S = Total C-sections", Severity.HIGH, RuleType.LOGIC),
    ("R007", "eq", "5", ["5.c", "5.d"], "Primary + Repeat C/S = Total C-sections", Severity.HIGH, RuleType.LOGIC),
    ("R011", "eq", "6", ["6.a", "6.b", "6.c"], "Male + Female + Unknown sex = Live Births", Severity.HIGH, RuleType.LOGIC),
    ("R016", "eq", "7", ["7.a", "7.b"], "Fresh + Macerated Stillbirth = Fetal Deaths >24w", Severity.HIGH, RuleType.LOGIC),
    ("R017", "eq", "8", ["8.a", "8.b"], "First + Second Trimester = Abortions", Severity.MEDIUM, RuleType.LOGIC),
    ("R024", "eq", "10.a.1", ["10.a.1.1", "10.a.1.2"], "Primary + Secondary Severe = Postpartum Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL),
    ("R025", "eq", "10.a.2", ["10.a.2.1", "10.a.2.2"], "Placental Abruption + Previa/Accreta = Antepartum Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL),
    ("R026", "eq", "10.a.3", ["10.a.3.1", "10.a.3.2", "10.a.3.3"], "Ectopic + Abortion Bleeding + Molar = Early Pregnancy Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL),
    ("R030", "eq", "10.e", ["10.e.1", "10.e.2", "10.e.3"], "Severe Preeclampsia + HELLP + Eclampsia = Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL),
    ("R061", "eq", "10", ["10.a", "10.b", "10.c", "10.d", "10.e", "10.f", "10.g", "10.h", "10.i", "10.j", "10.k", "10.l", "10.m", "10.n", "10.o"], "Severe Maternal Morbidity (SMM) = Hemorrhage + Uterine Rupture + Relaparotomy + Hysterectomy + Hypertensive Disorders + Sepsis + Respiratory Failure + Cardiac ICU + Renal Failure + Thromboembolism + Neurological Complications + Anaesthesia Complications + Unplanned ICU + Self-Harm/Suicide + Other Morbidity", Severity.HIGH, RuleType.CLINICAL),
    ("R067", "eq", "10.a", ["10.a.1", "10.a.2", "10.a.3", "10.a.5", "10.a.6"], "Hemorrhage = Postpartum + Antepartum + Early Pregnancy Hemorrhage + Non-Obstetric Bleeding + Uterine Inversion/Other", Severity.HIGH, RuleType.CLINICAL),
    ("R068", "eq", "10.j", ["10.j.1", "10.j.2", "10.j.3"], "Thromboembolism = Pulmonary Embolism + Confirmed Embolism + Amniotic Fluid Embolism", Severity.HIGH, RuleType.CLINICAL),
]


def _build_rules():
    for code, expr, parent, children, desc, sev, rtype in SUM_RULE_SPECS:
        if expr == "ge":
            ALL_RULES.append(lambda ctx, p=parent, ch=children, c=code, d=desc, s=sev, t=rtype: _ge(p, ch, c, d, s, t, ctx))
        else:
            ALL_RULES.append(lambda ctx, p=parent, ch=children, c=code, d=desc, s=sev, t=rtype: _eq(p, ch, c, d, s, t, ctx))

    ALL_RULES.append(lambda ctx: _le("5.b.1", "5", "R008", "Emergency C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("5.b.2", "5", "R009", "Planned C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("5.d", "5", "R010", "Repeat C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))

    ALL_RULES.append(lambda ctx: _le("6.d", "6", "R012", "Multiple Pregnancy <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.e", "6", "R013", "Twins/Multiples count <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.f", "6", "R014", "Preterm Births <= Live Births", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.g", "6", "R015", "Low Birth Weight <= Live Births", Severity.HIGH, RuleType.LOGIC, ctx))

    ALL_RULES.append(lambda ctx: _le("7", "2", "R018", "Fetal Deaths <= Total Deliveries", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("8", "2", "R019", "Abortions <= Total Deliveries", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("9", "6", "R020", "Congenital Anomalies <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))

    ALL_RULES.append(lambda ctx: _le("10.a.1", "10.a", "R021", "Postpartum Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.a.2", "10.a", "R022", "Antepartum Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.a.3", "10.a", "R023", "Early Pregnancy Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))

    ALL_RULES.append(lambda ctx: _le("10.e.1", "10.e", "R027", "Severe Preeclampsia <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e.2", "10.e", "R028", "HELLP Syndrome <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e.3", "10.e", "R029", "Eclampsia <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))

    ALL_RULES.append(lambda ctx: _le("10.a", "10", "R031", "Hemorrhage <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e", "10", "R032", "Hypertensive Disorders <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.f", "10", "R033", "Sepsis <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.m", "10", "R034", "Unplanned ICU Admission <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.d", "10", "R035", "Hysterectomy <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.c", "10", "R036", "Relaparotomy <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.b", "10", "R037", "Uterine Rupture <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.l", "10", "R038", "Anaesthesia Complications <= SMM", Severity.MEDIUM, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.h", "10", "R039", "Cardiac ICU Admission <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.i", "10", "R040", "Renal Failure/Dialysis <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))

    ALL_RULES.append(lambda ctx: _le("10.g", "10", "R062", "Respiratory Failure/ICU Ventilation <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.j", "10", "R063", "Thromboembolism <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.k", "10", "R064", "Neurological Complications <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.n", "10", "R065", "Self-Harm/Suicide Attempt <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.o", "10", "R066", "Other Morbidity <= SMM", Severity.MEDIUM, RuleType.CLINICAL, ctx))

    ALL_RULES.append(lambda ctx: _month_over("2", ctx.historical_data, ctx.rules.month_over_factor, "R051", "Deliveries > 2x previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_under("2", ctx.historical_data, ctx.rules.month_under_factor, "R052", "Deliveries < 50% of previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_over("6", ctx.historical_data, ctx.rules.month_over_factor, "R053", "Live Births > 2x previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_over("11", ctx.historical_data, ctx.rules.maternal_over_factor, "R054", "Maternal Deaths increased by >300%", Severity.CRITICAL, ctx))
    ALL_RULES.append(lambda ctx: _month_over("17", ctx.historical_data, ctx.rules.neonatal_over_factor, "R055", "Neonatal Deaths increased by >300%", Severity.CRITICAL, ctx))

    KEY_INDICATORS = ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]
    ALL_RULES.append(lambda ctx: _neg_check(KEY_INDICATORS, "R056", "Negative indicator value found", Severity.HIGH, ctx))

    ALL_RULES.append(lambda ctx: _decimal_check(["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"], "R057", "Decimal value found for count indicator", ctx))

    ALL_RULES.append(lambda ctx: _missing("2", "R058", "Missing Total Deliveries", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _missing("6", "R059", "Missing Live Births", Severity.HIGH, ctx))

    ALL_RULES.append(lambda ctx: _all_zero_check(ctx, "R060", "All indicators are zero for a working facility"))


_build_rules()


def run_all_rules(ctx: ValidationContext) -> List[RuleResult]:
    results = []
    for rule_func in ALL_RULES:
        result = rule_func(ctx)
        ref_codes = RULE_REF_CODES.get(result.rule_code)
        if ref_codes is not None and ctx.disabled_codes:
            all_disabled = True
            for c in ref_codes:
                if c.strip() not in ctx.disabled_codes:
                    all_disabled = False
                    break
            if all_disabled:
                continue
        results.append(result)
    return results


def load_rules_from_db(session: Session) -> list:
    from sqlalchemy import func
    from app.models import Rule
    return (
        session.query(Rule)
        .filter(
            Rule.enabled,
            func.upper(Rule.rule_type) != "BENCHMARK",
            func.upper(Rule.category) != "STATISTICAL_BENCHMARK",
            func.lower(Rule.expression_type).notin_(
                ("benchmark_rate", "benchmark_low_rate", "cross_hospital_rate")
            ),
        )
        .order_by(Rule.sort_order, Rule.code)
        .all()
    )


def _iter_sum_rules(session: Session = None):
    """Yield (op, parent, children) for every active sum-rule.

    Uses DB rules (expression_type ge/eq/le_sum) when present, else falls back to
    the compiled SUM_RULE_SPECS. Keeps a single source of truth with _build_rules.
    """
    if session is not None:
        try:
            db_rules = load_rules_from_db(session)
        except Exception:
            db_rules = []
        if db_rules:
            for rule in db_rules:
                # gt/ge_factor are containment sums too (e.g. R080: 6 > 6.d+6.f+6.g
                # — categories within the parent) and drive coverage the same way.
                # parent_le/parent_lt (children must account for the parent) are
                # also sum-driven: unreported siblings are covered when the
                # reported ones already reconcile the rule (see
                # compute_covered_codes), otherwise completeness would wrongly
                # penalize them (incident 5.2 — R061).
                if rule.expression_type not in ("ge", "eq", "le_sum", "gt", "ge_factor", "parent_le", "parent_lt", "compare"):
                    continue
                params = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
                if rule.expression_type == "compare":
                    # Same doctrine as the legacy types: only a single left side
                    # against a summed right side describes containment or
                    # parent accounting for the coverage pass.
                    normalized = compare_params(params) or {}
                    left = normalized.get("left") or {}
                    right = normalized.get("right") or {}
                    op_name = {">=": "ge", ">": "gt", "=": "eq",
                               "<=": "parent_le", "<": "parent_lt"}.get(normalized.get("op"))
                    left_codes = left.get("codes") or []
                    right_codes = right.get("codes") or []
                    if (op_name and len(left_codes) == 1
                            and (left.get("agg") or "single") == "single"
                            and (right.get("agg") or "single") == "sum" and right_codes):
                        yield (op_name, left_codes[0], right_codes)
                    continue
                if rule.expression_type == "le_sum":
                    parent = params.get("child")
                else:
                    parent = params.get("parent")
                children = params.get("children") or []
                if parent and children:
                    yield (rule.expression_type, parent, children)
            return
    for _code, expr, parent, children, *_ in SUM_RULE_SPECS:
        yield (expr, parent, children)


def compute_covered_codes(values: Dict[str, float], disabled_codes: set,
                          session: Session = None,
                          rules: Optional[RulesPolicy] = None) -> set:
    """Return sibling child *codes* whose absence is already explained by a total.

    Two doctrines, matching how the validation rules themselves treat totals:

    1. **Exhaustive sums (eq / le_sum):** when the reported children already add
       up to the parent within tolerance, any unreported sibling is "covered" —
       it should not be flagged as missing nor penalize completeness.
    2. **Containment sums (gt / ge / ge_factor):** these rules (e.g. R080
       "6 > 6.d + 6.f + 6.g") define a NON-EXHAUSTIVE subset: the children are
       categories *within* the parent, and zero/unreported is a legitimate
       "no activity in that category" answer. When the parent is reported and
       the children that ARE reported stay within the parent (rule PASSes),
       unreported siblings are covered — the facility simply had no such cases
       and total-based checks (like R012's total-covered sweep or the upload
       sheet) already account for them via the parent total.

    3. **Parent-accounting sums (parent_le / parent_lt):** the children must
       *account for at least* the whole parent (parent <= sum(children)). When
       the parent is reported and the children that ARE reported already reach
       the parent's value (rule PASSes), unreported siblings are covered —
       the reported ones already satisfy "at least the parent", so absence of
       the rest is a legitimate "no such cases" answer. When the reported
       children fall SHORT of the parent (rule FAILs), the gap may be exactly
       the missing siblings, and they stay flagged.

    Unreported children of a containment rule are covered ONLY when the
    reported ones do not overflow the parent — otherwise the missing siblings
    may be exactly the reason the rule cannot reconcile, and stay flagged.
    """
    # Explicit policy only: no process-global table, so two concurrent
    # operations cannot cover different children with each other's tolerance.
    tolerance = (rules or DEFAULT_RULES_POLICY).eq_tolerance
    covered = set()
    disabled_codes = disabled_codes or set()
    for op, parent, children in _iter_sum_rules(session):
        pv = values.get(parent)
        if pv is None:
            continue
        cs = sum(values.get(c) or 0 for c in children)
        if op in ("gt", "ge", "ge_factor"):
            # Containment: reported children must fit within the parent.
            # _vs/_v treat missing as 0, mirroring the rule execution itself.
            if cs <= pv + tolerance:
                for c in children:
                    if values.get(c) is None and c not in disabled_codes:
                        covered.add(c)
        elif op in ("parent_le", "parent_lt"):
            # Parent accounting: reported children must reach the parent.
            # Coverage mirrors the rule's own pass condition — parent_le allows
            # equality, parent_lt requires a strict exceedance.
            ok = cs >= pv - tolerance if op == "parent_le" else cs > pv + tolerance
            if ok:
                for c in children:
                    if values.get(c) is None and c not in disabled_codes:
                        covered.add(c)
        elif abs(pv - cs) <= tolerance:
            for c in children:
                if values.get(c) is None and c not in disabled_codes:
                    covered.add(c)
    return covered


def get_covered_child_codes(ctx: ValidationContext, session: Session = None,
                            rules: Optional[RulesPolicy] = None) -> set:
    """Return sibling child codes whose absence is already explained by a total.

    Thin wrapper over :func:`compute_covered_codes` using the context's values and
    disabled codes.
    """
    return compute_covered_codes(ctx.values, ctx.disabled_codes, session,
                                 rules=rules or ctx.rules)


def _get_rule_ref_codes_from_expr(expr: str, params: dict) -> list:
    if expr in ("ge", "eq", "gt", "ge_factor", "parent_le", "parent_lt"):
        codes = [params.get("parent")]
        codes.extend(params.get("children", []))
        return [c for c in codes if c]
    if expr == "le_sum":
        # child >= sum(children): both the child and every summed child are
        # referenced — parity with RULE_REF_CODES entries and the confidence
        # engine's _extract_codes_from_params.
        codes = [params.get("child")]
        codes.extend(params.get("children", []))
        return [c for c in codes if c]
    if expr in ("le", "lt"):
        return [params.get("child"), params.get("parent")] if params.get("parent") else [params.get("child")]
    if expr == "compare":
        normalized = compare_params(params) or {}
        codes = []
        for side in ("left", "right"):
            codes.extend((normalized.get(side) or {}).get("codes") or [])
        return [c for c in codes if c]
    if expr in ("month_over", "month_under", "missing"):
        return [params.get("code")]
    if expr == "trend":
        return (trend_params(params) or {}).get("codes") or []
    if expr in ("neg_check", "decimal_check"):
        return params.get("codes", [])
    if expr == "all_zero":
        return params.get("codes") or ALL_ZERO_DEFAULT_CODES
    if expr == "value_check":
        codes = []
        for check in value_check_params(params) or []:
            if check["codes"]:
                codes.extend(check["codes"])
            elif check["kind"] == "all_zero":
                codes.extend(ALL_ZERO_DEFAULT_CODES)
        return list(dict.fromkeys(codes))
    if expr == "formula":
        codes = formula_referenced_codes(params.get("formula", ""))
        rhs = params.get("rhs")
        if rhs:
            codes += formula_referenced_codes(rhs)
        target = params.get("target", "")
        return codes + ([target] if target and target not in codes else [])
    return []


def _all_codes_disabled(ctx: ValidationContext, codes: list) -> bool:
    if not codes or not ctx.disabled_codes:
        return False
    for c in codes:
        if c not in ctx.disabled_codes:
            return False
    return True


def dispatch_rule(rule, ctx: ValidationContext) -> Optional[RuleResult]:
    params = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
    code = rule.code
    desc = rule.name
    sev = Severity(rule.severity)
    expr = rule.expression_type
    rule_type = getattr(rule.rule_type, "value", rule.rule_type)
    if (
        str(rule_type).upper() == "BENCHMARK"
        or str(getattr(rule, "category", "")).upper() == "STATISTICAL_BENCHMARK"
        or expr in {"benchmark_rate", "benchmark_low_rate", "cross_hospital_rate"}
    ):
        return None
    rtype = RuleType(rule.rule_type)

    ref_codes = _get_rule_ref_codes_from_expr(expr, params)
    if _all_codes_disabled(ctx, ref_codes):
        return None

    if expr == "ge":
        return _ge(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "eq":
        return _eq(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "gt":
        return _gt(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "ge_factor":
        return _ge_factor(params["parent"], params["children"], float(params.get("factor", 1.0)), code, desc, sev, rtype, ctx)
    elif expr == "le":
        return _le(params["child"], params["parent"], code, desc, sev, rtype, ctx)
    elif expr == "lt":
        return _lt(params["child"], params["parent"], code, desc, sev, rtype, ctx)
    elif expr == "le_sum":
        return _ge(params["child"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "parent_le":
        return _parent_le(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "parent_lt":
        return _parent_lt(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "trend":
        normalized = trend_params(params)
        if normalized is None:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                              "trend needs a direction (over or under) and the indicator code(s) it watches")
        return _trend(normalized, code, desc, sev, ctx)
    elif expr in _LEGACY_TREND_TYPES:
        # Aliases: the retired types keep working, through the same engine.
        normalized = normalize_trend_params(expr, params)
        if normalized is None:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                              f"{expr} needs the indicator code it watches")
        return _trend(normalized, code, desc, sev, ctx)
    elif expr == "value_check":
        checks = value_check_params(params)
        if not checks:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                              "value_check needs at least one check (negative, decimal, missing, all_zero) with its codes")
        return _value_check(checks, code, desc, sev, ctx)
    elif expr in _LEGACY_VALUE_CHECK_TYPES:
        # Aliases: the retired types keep working, through the same engine.
        normalized = normalize_value_check_params(expr, params)
        if normalized is None:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                              f"{expr} needs the indicator code(s) it checks")
        return _value_check(normalized["checks"], code, desc, sev, ctx)
    elif expr == "formula":
        return _formula(params["formula"], params.get("target"), code, desc, sev, rtype, ctx,
                        op=params.get("op", "="), rhs=params.get("rhs"))
    elif expr == "compare":
        normalized = compare_params(params)
        if normalized is None:
            return RuleResult(code, desc, RuleStatus.PASS, sev, rtype,
                              "compare needs both sides: left and right")
        return _compare(normalized, code, desc, sev, rtype, ctx)
    else:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Unknown expression type: {expr}")


def run_rules_from_db(session: Session, ctx: ValidationContext) -> List[RuleResult]:
    results = []
    db_rules = load_rules_from_db(session)
    for rule in db_rules:
        try:
            result = dispatch_rule(rule, ctx)
            if result is not None:
                results.append(result)
        except Exception as e:
            results.append(RuleResult(rule.code, rule.name, RuleStatus.PASS, Severity(rule.severity), RuleType(rule.rule_type), f"Execution error: {e}"))
    return results
