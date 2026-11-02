"""Audit the Very High issues that fired on hospital history ALONE.

Read-only. Answers one question: for each issue whose only perspective is
``history`` and whose only band is VERY_HIGH, is the history comparison strong
enough to justify the top band — or is the band an artefact of a thin window, a
noisy count, a tiny baseline, or a trend the method does not model?

The checks are not opinions: each one is either the engine's own rule
(``app/engine/anomaly/layered.py``) or a standard noise model.

Each check is a FLAG: ``material_concern`` is true when any flag fires, and
``verdict`` is the single most damning flag. Flags overlap heavily, so flag
counts must never be summed to a number of issues — 37 issues carry
``within_observed_range`` while only 8 reach the ``seen`` verdict, because 24
were absorbed by ``noise``, 3 by ``thin`` and 2 by ``tiny``. The reconciliation
table printed by ``main`` is the authoritative cross-tab; the CSV carries every
flag row-wise so any regrouping can be recomputed.

* ``thin_history``      n < 4: the engine's ``min_observations`` is 3, so a
                        sample std can come from three points or fewer.
* ``dispersion_noise``  a COUNT whose jump is compatible with the window's own
                        over-dispersed noise (window dispersion index
                        phi = var/mean, z < 2.326), or a RATE whose jump is
                        compatible with one binomial draw at the historical
                        rate (p >= 1%). See "Why not Poisson" below.
* ``counting_noise``    the same question asked with plain Poisson (phi = 1).
                        Kept only as a SENSITIVITY column: the empirical
                        windows are over-dispersed (median phi ~2, half above
                        phi 2), so Poisson understates noise and is the more
                        generous reading of the finding.
* ``tiny_scale``        count series whose median is <= 2, where 1 -> 3 is a
                        +200% change with no information in it.
* ``trend_continuation``the series moves monotonically and the current value
                        sits inside the trend's own residual band: the top band
                        was earned by a MAD/z centre that ignores the trend.
* ``within_observed_range`` the current value sits inside the range the
                        hospital already produced in its own window, so the
                        "outlier" is not even the most extreme value on record.
* ``low_confidence``    the row is already marked low confidence by the scan
                        (fewer than 4 observations), so "Skip low confidence"
                        removes it from the screen.

``unstable_series`` (CV >= 0.5, the engine's own cut for "too variable for a
percentage change") is reported but is NOT a disqualifier: a MAD or IQR method
expects a moving series and grades the distance from the centre, so a high CV
alone does not make the band wrong.

Separately from the evidence checks, ``vh_eligible`` answers a policy question
and never changes ``verdict``: would the SAME window's dispersion-aware score
(``layered.dispersion_score``, the very function the percentage-change cap
already uses) also reach VERY_HIGH? No new threshold is introduced — the band
comes from ``level_for_score`` at the configured z threshold — so the column
measures how far the band depends on which scale is trusted, not on a new rule.

## Why not Poisson

Counts in this dataset are not Poisson draws: the dispersion index of the
comparison windows is median ~2.1, and half the windows exceed 2. Poisson's
sqrt(mean) therefore understates the noise, so a Poisson-only audit is
anti-conservative about the alerts (it excuses fewer of them than it should).
Every row reports phi and both tests so the direction of the sensitivity is
visible.

Usage:  .venv/Scripts/python.exe scripts/audit_history_only_very_high.py
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scipy import stats as scipy_stats  # noqa: E402

from app.api.quality_alerts import _issue_key  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.engine.anomaly.layered import very_high_eligibility  # noqa: E402
from app.engine.quality_alerts import (  # noqa: E402
    cap_thin_peer,
    cap_zero_spread,
    stored_series,
)
from app.models import Hospital, QualityAlert  # noqa: E402

VERY_HIGH = "VERY_HIGH"
HISTORY = "history"

# Poisson tail probability at which a count jump is treated as explainable by
# counting noise. 1% is deliberately generous to the finding: only jumps that
# are unlikely under the same rate are called "real".
NOISE_P = 0.01
# One-sided 1% normal quantile, for the dispersion-adjusted count test.
NOISE_Z = 2.326
# The engine's own variability cut (layered.CV_MAX).
CV_MAX = 0.5
TINY_SCALE = 2.0
# The engine's configured z threshold (systemControl default); only used to ask
# what band the dispersion-aware score would give. Not a new policy knob.
Z_THRESHOLD = 2.5


def _flags(alert: QualityAlert) -> Dict[str, Any]:
    """Every audit measurement for one stored history row."""
    evidence = alert.evidence or {}
    history = [(m, float(v)) for m, v in (evidence.get("history") or [])
               if v is not None]
    values = [v for _, v in history]
    stats = evidence.get("stats") or {}
    current = alert.current_value
    numerator = evidence.get("numerator")
    denominator = evidence.get("denominator")
    is_rate = denominator is not None
    mean = float(stats.get("mean")) if stats.get("mean") is not None else (
        statistics.fmean(values) if values else None)
    std = float(stats["std"]) if stats.get("std") is not None else (
        statistics.stdev(values) if len(values) > 1 else None)
    n = len(values)
    cv = abs(std / mean) if (std is not None and mean) else None

    poisson_p = None
    poisson_z = None
    binom_p = None
    delta_pp = None
    rel_change = None
    if current is not None and mean:
        delta_pp = float(current) - float(mean)
        rel_change = delta_pp / abs(float(mean))
    if (is_rate and denominator and numerator is not None
            and "%" in (alert.unit or "")):
        # One binomial draw at the hospital's own historical rate: the honest
        # noise model for a percentage, where Poisson does not apply.
        p0 = float(mean) / 100.0
        if 0.0 < p0 < 1.0:
            trials = int(round(float(denominator)))
            hits = int(round(float(numerator)))
            binom_p = float(
                scipy_stats.binom.sf(hits - 1, trials, p0) if hits >= trials * p0
                else scipy_stats.binom.cdf(hits, trials, p0))
    if not is_rate and values:
        lam = max(mean or 0.0, 1e-9)
        # Probability of seeing a value at least this far from the mean under
        # the same rate; counts are integers, so round toward the mean.
        cur = float(current or 0.0)
        if cur >= lam:
            poisson_p = float(scipy_stats.poisson.sf(round(cur) - 1, lam))
        else:
            poisson_p = float(scipy_stats.poisson.cdf(round(cur), lam))
        # How many counting sigmas the month is from its own rate: sqrt(lambda)
        # is the Poisson standard deviation, so this is the honest "is the
        # volume even out of line?" scale for a count.
        poisson_z = abs(cur - lam) / (lam ** 0.5) if lam > 0 else None

    # Trend check: a monotone series that is still moving in the same direction
    # makes the current month the trend's next point, not an outlier.
    slope = None
    residual_std = None
    rho = None
    if n >= 4:
        xs = list(range(n))
        rho = float(scipy_stats.spearmanr(xs, values).statistic)
        denom = sum((x - statistics.fmean(xs)) ** 2 for x in xs) or 1.0
        slope = sum((x - statistics.fmean(xs)) * (v - statistics.fmean(values))
                    for x, v in zip(xs, values, strict=True)) / denom
        intercept = statistics.fmean(values) - slope * statistics.fmean(xs)
        residuals = [v - (intercept + slope * x)
                     for x, v in zip(xs, values, strict=True)]
        residual_std = (statistics.stdev(residuals) if len(residuals) > 1
                        else 0.0)
    projected = None
    trend_gap = None
    if slope is not None and values:
        xs = list(range(n))
        intercept = statistics.fmean(values) - slope * statistics.fmean(xs)
        projected = intercept + slope * n          # next point after the window
        trend_gap = abs(float(current or 0.0) - projected)

    # Dispersion-aware view: the window's own variability, not sqrt(mean).
    # For a count that is a quasi-Poisson z (phi = var/mean, floored at 1 so an
    # under-dispersed window is never credited with extra precision); for a
    # rate the binomial test above already uses the denominator.
    phi = None
    dispersion_z = None
    if not is_rate and values and mean:
        phi = max(1.0, statistics.variance(values) / float(mean))
        dispersion_z = abs(float(current or 0.0) - float(mean)) / (
            (phi * float(mean)) ** 0.5)
    dispersion_noise = (
        (dispersion_z is not None and dispersion_z < NOISE_Z)
        or (binom_p is not None and binom_p >= NOISE_P))
    # The approved top-band gate, from the engine's own function
    # (layered.very_high_eligibility), so the audit and any screen that adopts
    # the gate can never disagree about a row.
    assessment = very_high_eligibility(VERY_HIGH, values, current, Z_THRESHOLD)

    flags = {
        "n": n,
        "method": alert.method,
        "dispersion_phi": phi,
        "dispersion_z": dispersion_z,
        "dispersion_score": assessment["dispersion_score"],
        "dispersion_band": assessment["dispersion_band"],
        "vh_eligible": assessment["eligible"],
        "eligibility_reason": assessment["reason"],
        "final_band": assessment["final_band"],
        "is_rate": is_rate,
        "mean": mean,
        "median": float(stats.get("median")) if stats.get("median") is not None
        else (statistics.median(values) if values else None),
        "std": std,
        "cv": cv,
        "current": current,
        "numerator": numerator,
        "denominator": denominator,
        "poisson_p": poisson_p,
        "poisson_z": poisson_z,
        "binom_p": binom_p,
        "delta_pp": delta_pp,
        "rel_change": rel_change,
        "spearman": rho,
        "projected": projected,
        "trend_gap": trend_gap,
        "residual_std": residual_std,
        "confidence": alert.confidence,
        "min_seen": min(values) if values else None,
        "max_seen": max(values) if values else None,
        "thin_history": n < 4,
        "marginal_history": 4 <= n < 6,
        "counting_noise": ((poisson_p is not None and poisson_p >= NOISE_P)
                           or (binom_p is not None and binom_p >= NOISE_P)),
        "dispersion_noise": dispersion_noise,
        "tiny_scale": (not is_rate and (statistics.median(values)
                                        if values else 0) <= TINY_SCALE),
        "unstable_series": cv is not None and cv >= CV_MAX,
        "trend_continuation": bool(
            rho is not None and abs(rho) >= 0.8 and projected is not None
            and trend_gap is not None
            and trend_gap <= 2.0 * (residual_std or 0.0)
            # and the trend actually reaches the value: the projection must not
            # be wildly off in magnitude either
        ),
        "low_confidence": (alert.confidence or "") == "low",
    }
    # A value the hospital has already matched or exceeded in the comparison
    # window is not an unprecedented outcome; it is at most a repeat. This
    # catches robust-method rows whose band rests on a small MAD while an
    # earlier month was just as extreme (std large, MAD small).
    flags["within_observed_range"] = bool(
        values and current is not None
        and min(values) <= float(current) <= max(values))
    # Verdict, most damning first. A count jump indistinguishable from counting
    # noise is the strongest reason to distrust the band; a high CV is not one
    # (see module docstring), so it never decides the verdict.
    if flags["dispersion_noise"]:
        flags["verdict"] = "noise"
    elif flags["thin_history"]:
        flags["verdict"] = "thin"
    elif flags["tiny_scale"]:
        flags["verdict"] = "tiny"
    elif flags["trend_continuation"]:
        flags["verdict"] = "trend"
    elif flags["within_observed_range"]:
        flags["verdict"] = "seen"
    else:
        flags["verdict"] = "supported"
    flags["material_concern"] = flags["verdict"] != "supported"
    return flags


def _issues(db) -> List[List[QualityAlert]]:
    rows = (db.query(QualityAlert)
            .filter(QualityAlert.active.is_(True))
            .all())
    grouped: Dict[tuple, List[QualityAlert]] = defaultdict(list)
    for alert in rows:
        grouped[_issue_key(alert)].append(alert)
    picked = []
    for group in grouped.values():
        if {a.perspective for a in group} != {HISTORY}:
            continue
        # The population is the band STORED on the rows, not the band the
        # policy currently allows: `_effective_severity` now applies the gate
        # this audit measures, so selecting on it would hide the very rows the
        # gate refuses.
        if {a.severity for a in group} != {VERY_HIGH}:
            continue
        picked.append(group)
    return picked


def _acceptance(db) -> Dict[str, Any]:
    """Run the gate over EVERY active alert: only VERY_HIGH rows may move.

    Read-only. This is the rule the gate exists to guarantee — a policy written
    to refuse the top band must not re-grade HIGH or lower rows, so the check
    covers the whole table, not the 182 issues under audit.
    """
    changed = []
    checked = 0
    for alert in (db.query(QualityAlert)
                  .filter(QualityAlert.active.is_(True)).all()):
        evidence = alert.evidence or {}
        # The band BEFORE this gate: the two spread caps, which is what every
        # reader reported until the gate is wired in.
        series = stored_series(evidence)
        base, _ = cap_zero_spread(alert.severity, evidence.get("stats"),
                                  alert.method, series)
        base, _ = cap_thin_peer(base, alert.peer_count, alert.method)
        values = [float(v) for _m, v in (evidence.get("history") or [])
                  if v is not None]
        assessment = very_high_eligibility(base, values, alert.current_value,
                                           Z_THRESHOLD)
        checked += 1
        if assessment["final_band"] != base:
            changed.append((base, assessment["final_band"]))
    return {"checked": checked, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="outbox/history-only-very-high.csv",
                        help="where to write the per-issue audit rows")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        groups = _issues(db)
        names = {h.id: h.name for h in db.query(Hospital).all()}
        records = []
        for group in groups:
            alert = sorted(group, key=lambda a: a.id)[0]
            record = {
                "month": alert.month,
                "hospital_id": alert.hospital_id,
                "hospital": names.get(alert.hospital_id, ""),
                "indicator_code": alert.indicator_code,
                "indicator_name": alert.indicator_name or "",
                "unit": alert.unit or "",
                "score": alert.score,
                **_flags(alert),
            }
            records.append(record)
        acceptance = _acceptance(db)
    finally:
        db.close()

    total = len(records)
    if not total:
        print("no history-only Very High issues found")
        return 0

    verdicts = Counter(r["verdict"] for r in records)
    weak = sum(1 for r in records if r["material_concern"])
    print(f"history-only Very High issues: {total}")
    print(f"with a material concern: {weak} ({weak / total:.1%})\n")
    print("verdicts (EXCLUSIVE, most damning concern wins; they sum to total):")
    for verdict, count in verdicts.most_common():
        print(f"  {verdict:<10} {count:>4}  ({count / total:5.1%})")

    flags = ("dispersion_noise", "counting_noise", "thin_history",
             "tiny_scale", "trend_continuation", "within_observed_range",
             "low_confidence", "marginal_history", "unstable_series")
    print("\nflags (OVERLAPPING - never sum these; one issue can carry several):")
    for flag in flags:
        count = sum(1 for r in records if r[flag])
        print(f"  {flag:<22} {count:>4}  ({count / total:5.1%})")

    # Reconciliation: which verdict absorbs each flag. This is the table that
    # keeps a flag count from being read as a number of issues.
    print("\nflag -> verdict reconciliation (rows are flags, columns are verdicts):")
    header = "  {:<22}".format("flag") + "".join(
        f"{v:>10}" for v in ("noise", "thin", "tiny", "trend", "seen",
                             "supported")) + f"{'total':>7}"
    print(header)
    for flag in ("within_observed_range", "dispersion_noise",
                 "counting_noise", "thin_history", "tiny_scale",
                 "trend_continuation", "low_confidence"):
        cells = Counter(r["verdict"] for r in records if r[flag])
        line = "  {:<22}".format(flag) + "".join(
            f"{cells.get(v, 0):>10}" for v in ("noise", "thin", "tiny",
                                               "trend", "seen",
                                               "supported"))
        print(line + f"{sum(cells.values()):>7}")
    overlaps = Counter(
        sum(1 for flag in ("dispersion_noise", "thin_history", "tiny_scale",
                           "trend_continuation", "within_observed_range")
            if r[flag])
        for r in records)
    print("  concerns per issue:", dict(sorted(overlaps.items())))

    # What the numbers actually are: volumes and magnitudes.
    counts = [r for r in records if not r["is_rate"]]
    rates = [r for r in records if r["is_rate"]]
    print(f"\ncount rows: {len(counts)}   rate rows: {len(rates)}")
    if counts:
        vols = sorted(float(r["current"] or 0) for r in counts)
        print("  count values: min={:.0f} p25={:.0f} median={:.0f} "
              "p75={:.0f} max={:.0f}".format(
                  vols[0], vols[len(vols) // 4], vols[len(vols) // 2],
                  vols[3 * len(vols) // 4], vols[-1]))
        small = sum(1 for v in vols if v < 5)
        print(f"  count values below 5: {small} ({small / len(counts):.1%})")
    if rates:
        dens = sorted(float(r["denominator"]) for r in rates
                      if r["denominator"] is not None)
        if dens:
            print("  rate denominators: min={:.0f} p25={:.0f} median={:.0f} "
                  "max={:.0f}".format(dens[0], dens[len(dens) // 4],
                                      dens[len(dens) // 2], dens[-1]))
            sub30 = sum(1 for v in dens if v < 30)
            print(f"  denominators below 30: {sub30} ({sub30 / len(dens):.1%})")

    rates_trivial = [r for r in records if r["is_rate"]
                     and r["delta_pp"] is not None
                     and abs(r["delta_pp"]) < 1.0]
    if rates_trivial:
        print(f"  rate rows moving less than 1 percentage point: "
              f"{len(rates_trivial)}")

    for verdict in ("noise", "tiny", "supported"):
        for key, label in (("poisson_z", "poisson"),
                           ("dispersion_z", "dispersion-aware")):
            zs = sorted(r[key] for r in records
                        if r["verdict"] == verdict and r[key] is not None)
            if zs:
                print(f"  {verdict:<10} {label:<16} sigmas: "
                      f"median={zs[len(zs) // 2]:.1f} "
                      f"p90={zs[9 * len(zs) // 10]:.1f} (n={len(zs)})")

    # Is the window even Poisson? (sensitivity of the noise test)
    phis = sorted(r["dispersion_phi"] for r in records
                  if r["dispersion_phi"] is not None)
    if phis:
        def pct(p):
            return phis[min(len(phis) - 1, int(p * len(phis)))]
        print("\ndispersion index of count windows (var/mean, 1.0 = Poisson):")
        print(f"  median={pct(.5):.2f} p25={pct(.25):.2f} p75={pct(.75):.2f} "
              f"p90={pct(.9):.2f}")
        print(f"  phi>1.5: {sum(1 for p in phis if p > 1.5)}/{len(phis)}"
              f"   phi>2.0: {sum(1 for p in phis if p > 2.0)}/{len(phis)}")
        print("  => Poisson (phi=1) understates noise; the dispersion test is "
              "the stricter one.")

    # ── Reclassification under the top-band gate (read-only) ──────────────
    # The gate never re-grades: a refused VERY_HIGH falls to HIGH, never lower.
    eligible = [r for r in records if r["vh_eligible"] is True]
    refused = [r for r in records if r["vh_eligible"] is False]
    undecided = [r for r in records if r["vh_eligible"] is None]
    print("\nVERY_HIGH eligibility (top-band gate, from"
          " layered.very_high_eligibility):")
    print(f"  eligible: {len(eligible)}/{total} ({len(eligible) / total:.1%})")
    print(f"  refused:  {len(refused)} -> {dict(Counter(
        r['final_band'] for r in refused).most_common())}")
    print(f"  undecided (no measurable window): {len(undecided)} "
          f"{dict(Counter(r['eligibility_reason'] for r in undecided))}")
    print("  refused by method:", dict(Counter(
        r["method"] for r in refused).most_common()))
    print("  refused but evidence-supported:",
          sum(1 for r in refused if r["verdict"] == "supported"))
    print("  final band across the 182 (all original VERY_HIGH):",
          dict(Counter(r["final_band"] for r in records).most_common()))

    # The rows the dispersion scale calls NONE are the ones to read by hand:
    # the gate still shows HIGH, but these are where the two scales disagree
    # most, so each needs a human verdict before the gate is adopted.
    none_rows = [r for r in records if r["dispersion_band"] == "NONE"]
    print(f"\nreview list - dispersion band NONE ({len(none_rows)}), gate keeps"
          " HIGH:")
    for r in sorted(none_rows, key=lambda r: (r["month"], r["hospital_id"])):
        print(f"  {r['month']} h{r['hospital_id']:<3} {r['indicator_code']:<28}"
              f" current={r['current']} mean={r['mean']} "
              f"median={r['median']} n={r['n']} method={r['method']}")

    # Acceptance: over EVERY active alert, only VERY_HIGH rows may move.
    print(f"\nacceptance over every active alert ({acceptance['checked']} rows):")
    moves = Counter(acceptance["changed"])
    print("  rows that changed band:", sum(moves.values()))
    print("  by (original -> final):", dict(moves.most_common()))
    below = [pair for pair in acceptance["changed"] if pair[0] != VERY_HIGH]
    print(f"  rows below VERY_HIGH that moved: {len(below)} (must be 0)")

    n_hist = Counter(r["n"] for r in records)
    print("\nhistory window sizes:", dict(sorted(n_hist.items())))
    print("methods:", dict(Counter(r["method"] for r in records).most_common()))
    print("bands already low confidence:",
          sum(1 for r in records if r["low_confidence"]))

    indicators = Counter(r["indicator_code"] for r in records)
    print("\ntop indicators (issues):")
    for code, count in indicators.most_common(10):
        print(f"  {code:<42} {count}")

    # Worked examples for each verdict, strongest first.
    print("\nexamples:")
    for verdict in ("noise", "thin", "tiny", "trend", "seen", "supported"):
        sample = next((r for r in records if r["verdict"] == verdict), None)
        if not sample:
            continue
        detail = (f"  [{verdict}] {sample['month']} h{sample['hospital_id']} "
                  f"{sample['indicator_code']} current={sample['current']} "
                  f"mean={sample['mean']} n={sample['n']} "
                  f"method={sample['method']}")
        if sample["poisson_p"] is not None:
            detail += f" poisson_p={sample['poisson_p']:.3g}"
        print(detail)

    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["month", "hospital_id", "hospital", "indicator_code",
              "indicator_name", "unit", "method", "score", "n", "current",
              "mean", "median", "std", "cv", "numerator", "denominator",
              "is_rate", "poisson_p", "poisson_z", "binom_p", "delta_pp",
              "rel_change", "spearman", "projected",
              "trend_gap", "min_seen", "max_seen", "confidence",
              "dispersion_phi", "dispersion_z", "dispersion_score",
              "dispersion_band", "vh_eligible", "eligibility_reason",
              "final_band",
              "verdict", "material_concern", "dispersion_noise",
              "counting_noise", "thin_history",
              "tiny_scale", "unstable_series", "trend_continuation",
              "within_observed_range", "low_confidence"]
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"\nwrote {out} ({total} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
