"""Read-only shadow comparison: perspective labels vs comparison identity.

Step 10D-2. Measures what the published corroboration KPI would become if it
counted independent peer comparisons instead of perspective LABELS, without
changing anything that is published.

Nothing here writes. The script only SELECTs, imports the published helpers so
the "current" side is literally the live code, and rolls the session back. It
recomputes a fingerprint of every alert row before and after the run and prints
both, so "zero writes" is demonstrated rather than asserted.

Usage:
    python scripts/shadow_comparison_identity.py [--limit 3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from itertools import combinations

sys.path.insert(0, ".")

from app.api import quality_alerts as qa  # noqa: E402
from app.config import DATABASE_URL  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.engine import comparison_identity as ci  # noqa: E402
from app.models import QualityAlert  # noqa: E402

REPORT_PATH = "logs/shadow_comparison_identity.json"

# Issue categories, in the priority order used to make them disjoint. A row
# that contradicts itself (invalid) outranks a row whose evidence is merely
# missing (unknown), because the two need different operator action.
CAT_MULTI_DISJOINT = "multiple_disjoint"
CAT_MULTI_OVERLAP = "multiple_overlapping"
CAT_SINGLE_PEER = "single_peer"
CAT_TEMPORAL = "temporal_only"
CAT_UNKNOWN = "unknown_identity"
CAT_INVALID = "invalid_evidence"
CATEGORIES = (CAT_MULTI_DISJOINT, CAT_MULTI_OVERLAP, CAT_SINGLE_PEER,
              CAT_TEMPORAL, CAT_UNKNOWN, CAT_INVALID)


def _say(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _fingerprint(db) -> dict:
    """Digest of every stored alert row, for the before/after zero-write check."""
    rows = (db.query(QualityAlert.id, QualityAlert.severity, QualityAlert.status,
                     QualityAlert.active, QualityAlert.updated_at,
                     QualityAlert.z_score, QualityAlert.current_value)
            .order_by(QualityAlert.id).all())
    digest = hashlib.sha256()
    for row in rows:
        digest.update(repr(tuple(row)).encode("utf-8"))
    return {
        "alert_rows": len(rows),
        "active_rows": sum(1 for row in rows if row[3]),
        "stored_severity": dict(Counter(row[1] for row in rows)),
        "digest": digest.hexdigest(),
    }


def _issue_record(key: tuple, rows: list) -> dict:
    """Classify one canonical issue under BOTH the published and shadow logic."""
    hid, formula_key, month = key
    scope = qa._very_high_scope(rows)
    current_corroborated = qa._very_high_corroborated(rows)

    identities = [ci.comparison_identity(row) for row in rows]
    kinds = Counter()
    reasons = Counter()
    peer: dict = {}
    for ident in identities:
        if ident.type == ci.COMPARISON_PEER and ident.hash:
            kinds["peer"] += 1
            peer.setdefault(ident.hash, ident)
        elif ident.type == ci.COMPARISON_TEMPORAL:
            kinds["temporal"] += 1
            reasons[ident.reason] += 1
        elif ident.state == ci.EVIDENCE_INVALID:
            kinds["invalid"] += 1
            reasons[ident.reason] += 1
        else:
            kinds["unknown"] += 1
            reasons[ident.reason] += 1

    hashes = sorted(peer)
    pairs = [ci.pairwise_relationship(peer[left], peer[right])
             for left, right in combinations(hashes, 2)]
    rel_counter = Counter(pairs)
    if len(hashes) >= 2:
        relationship = (ci.RELATIONSHIP_DISJOINT
                        if rel_counter[ci.RELATIONSHIP_DISJOINT] == len(pairs)
                        else ci.RELATIONSHIP_OVERLAPPING)
    elif len(hashes) == 1:
        relationship = "single"
    else:
        relationship = "none"

    if len(hashes) >= 2:
        category = (CAT_MULTI_DISJOINT if relationship == ci.RELATIONSHIP_DISJOINT
                    else CAT_MULTI_OVERLAP)
    elif len(hashes) == 1:
        category = CAT_SINGLE_PEER
    elif kinds["invalid"]:
        category = CAT_INVALID
    elif kinds["temporal"] and not kinds["unknown"]:
        category = CAT_TEMPORAL
    else:
        category = CAT_UNKNOWN

    return {
        "hospital_id": hid,
        "month": month,
        "canonical_key": formula_key,
        "indicator_codes": sorted({row.indicator_code for row in rows}),
        "alert_ids": sorted(row.id for row in rows),
        "perspectives": sorted({row.perspective for row in rows}),
        "scope": scope,
        "current_corroborated": current_corroborated,
        "peer": len(hashes),
        "peer_rows": kinds["peer"],
        "temporal_rows": kinds["temporal"],
        "unknown_rows": kinds["unknown"],
        "invalid_rows": kinds["invalid"],
        "reasons": dict(reasons),
        "pairs": dict(rel_counter),
        "relationship": relationship,
        "category": category,
        "shadow_strict": bool(scope == "only" and len(hashes) >= 2
                              and relationship == ci.RELATIONSHIP_DISJOINT),
        "shadow_loose": bool(scope == "only" and len(hashes) >= 2),
    }


def _composition(record: dict) -> str:
    """WHAT the stored evidence actually is, for one issue.

    ``peer == 1`` is unambiguous only when the label count is also 1: with two
    labels it means either two rows that compared the identical peer set
    (``all`` beside the one subgroup equal to it) or one peer row beside a
    history row. Those are different defects and are named apart here.
    """
    if record["peer"] >= 2:
        if (record["pairs"].get(ci.RELATIONSHIP_NESTED)
                and not record["pairs"].get(ci.RELATIONSHIP_OVERLAPPING)):
            return "multi_nested_only"
        return "multi_overlapping"
    if record["peer"] == 1 and record["peer_rows"] > 1:
        return "identical_peer_sets"
    if record["peer"] == 1 and record["temporal_rows"]:
        return "single_peer_plus_temporal"
    if record["peer"] == 1:
        return "single_peer"
    if record["temporal_rows"] and not record["unknown_rows"] \
            and not record["invalid_rows"]:
        return "temporal_only"
    if record["invalid_rows"]:
        return "invalid_evidence"
    return "unknown_identity"


def _example(record: dict) -> dict:
    return {
        "hospital_id": record["hospital_id"],
        "month": record["month"],
        "indicator_code": (record["indicator_codes"] or [None])[0],
        "perspectives": record["perspectives"],
        "alert_ids": record["alert_ids"][:6],
        "peer_comparisons": record["peer"],
        "relationship": record["relationship"],
        "category": record["category"],
        "scope": record["scope"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3,
                        help="examples to keep per relationship / change class")
    args = parser.parse_args()

    db = SessionLocal()
    report: dict = {"database": DATABASE_URL.split(":", 1)[0],
                    "limit": args.limit}
    try:
        before = _fingerprint(db)
        report["fingerprint_before"] = before

        # ── Published KPIs, from the live endpoint function ──────────────
        summary = qa.get_summary(
            db=db, month=None, hospital_id=None, indicator=None,
            severity=None, perspective=None, status=None, ownership_id=None,
            governorate_id=None, hospital_type_id=None, confidence=None,
            indicator_type=None, very_high_scope=None, q=None,
            include_closed=False)
        report["published"] = {
            "total_active_rows": summary["total_active"],
            "total_issues": summary["total_issues"],
            "very_high_rows": summary["very_high_rows"],
            "very_high_issues": summary["very_high_issues"],
            "very_high_only_issues": summary["very_high_only_issues"],
            "very_high_only_corroborated_issues":
                summary["very_high_only_corroborated_issues"],
            "very_high_single_perspective_issues":
                summary["very_high_single_perspective_issues"],
            "very_high_single_perspective_by_perspective":
                summary["very_high_single_perspective_by_perspective"],
            "mixed_severity_issues": summary["mixed_severity_issues"],
            "very_high_only_breakdown": summary["very_high_only_breakdown"],
            "very_high_only_by_perspectives":
                summary["very_high_only_by_perspectives"],
            "by_perspective": summary["by_perspective"],
            "by_severity": summary["by_severity"],
        }

        # ── The SAME issue population, from the published grouping ──────
        evidence = qa._evidence_by_issue(
            db, month=None, hospital_id=None, indicator=None, ownership_id=None,
            governorate_id=None, hospital_type_id=None, indicator_type=None,
            q=None, include_closed=False)
        report["grouping_matches_published"] = (
            len(evidence) == summary["total_issues"])

        records = [_issue_record(key, rows) for key, rows in evidence.items()]
        report["issues_seen"] = len(records)

        # ── Current vs shadow ───────────────────────────────────────────
        only = [r for r in records if r["scope"] == "only"]
        mixed = [r for r in records if r["scope"] == "mixed"]
        neither = [r for r in records if r["scope"] is None]
        current_corroborated = [r for r in only if r["current_corroborated"]]
        strict = [r for r in only if r["shadow_strict"]]
        loose = [r for r in only if r["shadow_loose"]]

        report["shadow"] = {
            "scope_split": {"only": len(only), "mixed": len(mixed),
                            "no_very_high": len(neither)},
            "current_corroborated_issues": len(current_corroborated),
            "shadow_corroborated_strict": len(strict),
            "shadow_corroborated_disjoint_or_multi": len(loose),
            "difference_strict": len(strict) - len(current_corroborated),
            "difference_strict_pct": round(
                100.0 * (len(strict) - len(current_corroborated))
                / len(current_corroborated), 2) if current_corroborated else None,
            "difference_loose": len(loose) - len(current_corroborated),
            "current_matches_published_kpi":
                len(current_corroborated)
                == summary["very_high_only_corroborated_issues"],
        }

        # Reconciliation of the Very-High-only population.
        recon = {cat: 0 for cat in CATEGORIES}
        for record in only:
            recon[record["category"]] += 1
        report["reconciliation"] = {
            "very_high_only": len(only),
            "by_category": recon,
            "sum_of_categories": sum(recon.values()),
            "balances": sum(recon.values()) == len(only),
            # Categories are made disjoint by priority, so the underlying
            # evidence states overlap; that overlap is reported, not summed.
            "overlap": {
                "has_invalid_row": sum(1 for r in only if r["invalid_rows"]),
                "has_unknown_row": sum(1 for r in only if r["unknown_rows"]),
                "has_temporal_row": sum(1 for r in only if r["temporal_rows"]),
                "peer_plus_temporal": sum(
                    1 for r in only if r["peer"] == 1 and r["temporal_rows"]),
                "multi_disjoint_plus_temporal": sum(
                    1 for r in only
                    if r["category"] == CAT_MULTI_DISJOINT
                    and r["temporal_rows"]),
                "multi_disjoint_plus_invalid": sum(
                    1 for r in only
                    if r["category"] == CAT_MULTI_DISJOINT and r["invalid_rows"]),
            },
            "all_issues_split": {
                "very_high_only": len(only),
                "mixed_severity": len(mixed),
                "no_very_high": len(neither),
                "total": len(records),
            },
        }

        # ── Relationship distribution (issues with 2+ identities) ───────
        multi = [r for r in records if r["peer"] >= 2]
        pair_totals = Counter()
        for record in multi:
            pair_totals.update(record["pairs"])
        rel_examples: dict = {}
        for name in (ci.RELATIONSHIP_IDENTICAL, ci.RELATIONSHIP_NESTED,
                     ci.RELATIONSHIP_OVERLAPPING, ci.RELATIONSHIP_DISJOINT,
                     ci.RELATIONSHIP_UNKNOWN):
            hits = [r for r in multi if r["pairs"].get(name, 0) > 0]
            rel_examples[name] = {
                "issues": len(hits),
                "examples": [_example(r) for r in hits[:args.limit]],
            }
        report["relationships"] = {
            "issues_with_multiple_identities": len(multi),
            "issue_level": {
                "all_pairs_disjoint": sum(
                    1 for r in multi
                    if r["relationship"] == ci.RELATIONSHIP_DISJOINT),
                "any_overlap_or_nesting": sum(
                    1 for r in multi
                    if r["relationship"] == ci.RELATIONSHIP_OVERLAPPING),
            },
            "pair_level": dict(pair_totals),
            "by_relationship": rel_examples,
        }

        # ── Classification changes ──────────────────────────────────────
        current_keys = {tuple(r["alert_ids"]) for r in current_corroborated}
        strict_keys = {tuple(r["alert_ids"]) for r in strict}
        lost = [r for r in current_corroborated
                if tuple(r["alert_ids"]) not in strict_keys]
        gained = [r for r in strict if tuple(r["alert_ids"]) not in current_keys]
        kept = [r for r in current_corroborated
                if tuple(r["alert_ids"]) in strict_keys]
        report["changes"] = {
            "corroborated_to_not": {
                "issues": len(lost),
                "examples": [_example(r) for r in lost[:args.limit]],
            },
            "not_to_corroborated": {
                "issues": len(gained),
                "examples": [_example(r) for r in gained[:args.limit]],
            },
            "unchanged_corroborated": len(kept),
            "unchanged_not_corroborated": len(only) - len(current_corroborated)
            - len(gained),
            "lost_composition": dict(Counter(_composition(r) for r in lost)),
        }

        # ── Evidence quality by source ─────────────────────────────────
        source_rows = Counter()
        source_issues = Counter()
        for record in records:
            seen = set()
            for row in evidence[(record["hospital_id"], record["canonical_key"],
                                 record["month"])]:
                ident = ci.comparison_identity(row)
                if ident.type == ci.COMPARISON_PEER and ident.hash:
                    name = ident.source or "peer_unknown_source"
                    source_rows[name] += 1
                    seen.add(name)
                elif ident.type == ci.COMPARISON_TEMPORAL:
                    source_rows["temporal"] += 1
                    seen.add("temporal")
                elif ident.state == ci.EVIDENCE_INVALID:
                    source_rows["invalid"] += 1
                    seen.add("invalid")
                else:
                    source_rows["unknown"] += 1
                    seen.add("unknown")
            for name in seen:
                source_issues[name] += 1
        report["evidence_quality"] = {"rows": dict(source_rows),
                                      "issues": dict(source_issues),
                                      "row_total": sum(source_rows.values())}

        # ── Required special cases ─────────────────────────────────────
        specials: dict = {}

        def _pick(predicate):
            hits = [r for r in records if predicate(r)]
            return {"issues": len(hits),
                    "examples": [_example(r) for r in hits[:args.limit]]}

        specials["all_plus_facility_type_same_peers"] = _pick(
            lambda r: {"all", "facility_type"} <= set(r["perspectives"])
            and r["peer"] == 1)
        specials["all_plus_governorate_disjoint_peers"] = _pick(
            lambda r: {"all", "governorate"} <= set(r["perspectives"])
            and r["peer"] >= 2 and r["relationship"] == ci.RELATIONSHIP_DISJOINT)
        specials["history_plus_one_peer"] = _pick(
            lambda r: r["peer"] == 1 and r["temporal_rows"] >= 1)
        specials["multiple_overlapping_groups"] = _pick(
            lambda r: r["peer"] >= 2
            and r["relationship"] == ci.RELATIONSHIP_OVERLAPPING)
        specials["legacy_rows_no_peer_ids"] = _pick(
            lambda r: (r["unknown_rows"] or r["invalid_rows"])
            and not r["peer_rows"] and not r["temporal_rows"])
        specials["mixed_very_high_and_lower"] = _pick(
            lambda r: r["scope"] == "mixed")

        # Same peer ids, conflicting statistics.
        conflicts = []
        for key, rows in evidence.items():
            by_hash: dict = {}
            for row in rows:
                ident = ci.comparison_identity(row)
                if ident.hash:
                    by_hash.setdefault(ident.hash, []).append(row)
            for _digest, group in by_hash.items():
                if len(group) < 2:
                    continue
                outcomes = {(qa._effective_severity(row), row.severity,
                             round(row.z_score or 0.0, 4),
                             round(row.current_value or 0.0, 4),
                             row.direction, row.method)
                            for row in group}
                if len(outcomes) > 1:
                    conflicts.append({
                        "hospital_id": key[0], "month": key[2],
                        "indicator_code": group[0].indicator_code,
                        "alert_ids": sorted(row.id for row in group),
                        "perspectives": sorted({row.perspective for row in group}),
                        "effective_severity": sorted(
                            {qa._effective_severity(row) for row in group}),
                        "stored_severity": sorted({row.severity for row in group}),
                        "z_score": sorted({row.z_score for row in group}),
                        "current_value": sorted({row.current_value for row in group}),
                        "method": sorted({row.method for row in group}),
                    })
        report["same_peers_conflicting_statistics"] = {
            "issues": len(conflicts), "examples": conflicts[:args.limit]}

        # Policy blocks with identical peer ids: what actually differs?
        policy_shapes = Counter()
        policy_conflicts = []
        policy_diff_keys: Counter = Counter()
        version_keys = set()
        for key, rows in evidence.items():
            by_hash: dict = {}
            for row in rows:
                policy = ((row.evidence or {}).get("comparison_policy") or {})
                for name in policy:
                    if "version" in str(name).lower():
                        version_keys.add(str(name))
                policy_shapes[json.dumps(policy, sort_keys=True, default=str)] += 1
                ident = ci.comparison_identity(row)
                if ident.hash:
                    by_hash.setdefault(ident.hash, []).append((row, policy))
            for _digest, group in by_hash.items():
                if len(group) < 2:
                    continue
                signatures = {json.dumps(policy, sort_keys=True, default=str)
                              for _row, policy in group}
                if len(signatures) < 2:
                    continue
                differing = set()
                base = group[0][1]
                for _row, other in group[1:]:
                    for name in set(base) | set(other):
                        if (json.dumps(base.get(name), sort_keys=True, default=str)
                                != json.dumps(other.get(name), sort_keys=True,
                                              default=str)):
                            differing.add(str(name))
                policy_diff_keys.update(differing)
                policy_conflicts.append({
                    "hospital_id": key[0], "month": key[2],
                    "indicator_code": group[0][0].indicator_code,
                    "alert_ids": sorted(row.id for row, _p in group),
                    "perspectives": sorted(row.perspective for row, _p in group),
                    "policy_variants": len(signatures),
                    "differing_keys": sorted(differing),
                    "sample": json.loads(sorted(signatures)[0]) if signatures else None,
                })
        report["policy_versions"] = {
            "version_field_names": sorted(version_keys),
            "distinct_policy_blocks": len(policy_shapes),
            "same_peers_different_policy": {
                "issues": len(policy_conflicts),
                "differing_keys": dict(policy_diff_keys),
                "examples": policy_conflicts[:args.limit],
            },
            "top_policy_shapes": [
                {"rows": count, "keys": sorted(json.loads(shape).keys())}
                for shape, count in policy_shapes.most_common(5)],
        }

        report["specials"] = specials

        # ── Diagnostics: labels vs comparisons ─────────────────────────
        label_vs_identity = Counter()
        label_vs_comparison = Counter()
        for record in only:
            labels = len(record["perspectives"])
            label_vs_identity[(labels, record["peer"])] += 1
            label_vs_comparison[(labels, record["peer"]
                                 + record["temporal_rows"])] += 1
        report["label_vs_identity"] = {
            "very_high_only": [
                {"labels": labels, "peer_identities": peers, "issues": count}
                for (labels, peers), count in sorted(label_vs_identity.items())],
            "very_high_only_including_temporal": [
                {"labels": labels, "comparisons": comps, "issues": count}
                for (labels, comps), count in sorted(label_vs_comparison.items())],
        }

        multi_disjoint = [r for r in multi
                          if r["relationship"] == ci.RELATIONSHIP_DISJOINT]
        report["multi_disjoint_issues_by_scope"] = dict(Counter(
            r["scope"] or "no_very_high" for r in multi_disjoint))
        report["scope_counts"] = dict(Counter(
            r["scope"] or "no_very_high" for r in records))

        gov = [r for r in records
               if {"all", "governorate"} <= set(r["perspectives"])]
        report["all_plus_governorate"] = {
            "issues": len(gov),
            "relationships": dict(Counter(r["relationship"] for r in gov)),
            "peer_counts": dict(Counter(r["peer"] for r in gov)),
            "examples": [_example(r) for r in gov[:args.limit]],
        }

        # ── Zero-write proof ────────────────────────────────────────────
        db.rollback()
        report["fingerprint_after"] = _fingerprint(db)
        report["zero_writes"] = (
            report["fingerprint_after"]["digest"]
            == report["fingerprint_before"]["digest"])

        with open(REPORT_PATH, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, default=str)
    finally:
        db.rollback()
        db.close()

    _say("Dataset")
    print(f"database              : {report['database']}")
    print(f"alert rows            : {report['fingerprint_before']['alert_rows']}"
          f" (active {report['fingerprint_before']['active_rows']})")
    print(f"published total_active: {report['published']['total_active_rows']}")
    print(f"published issues      : {report['published']['total_issues']}"
          f"   shadow grouping: {report['issues_seen']}"
          f"   match: {report['grouping_matches_published']}")

    _say("Published KPIs (live endpoint code)")
    for name in ("very_high_rows", "very_high_issues", "very_high_only_issues",
                 "very_high_only_corroborated_issues",
                 "very_high_single_perspective_issues",
                 "mixed_severity_issues"):
        print(f"{name:38}: {report['published'][name]}")

    _say("Shadow")
    for name in ("current_corroborated_issues", "shadow_corroborated_strict",
                 "shadow_corroborated_disjoint_or_multi", "difference_strict",
                 "difference_strict_pct", "difference_loose",
                 "current_matches_published_kpi"):
        print(f"{name:38}: {report['shadow'][name]}")

    _say("Reconciliation (Very-High-only)")
    for cat in CATEGORIES:
        print(f"{cat:38}: {report['reconciliation']['by_category'][cat]}")
    print(f"{'sum':38}: {report['reconciliation']['sum_of_categories']}"
          f"   balances: {report['reconciliation']['balances']}")
    print(f"{'all issues':38}: {report['reconciliation']['all_issues_split']}")
    print(f"overlap: {report['reconciliation']['overlap']}")

    _say("Relationships (2+ identities)")
    print(f"issues: {report['relationships']['issues_with_multiple_identities']}")
    print(f"issue level: {report['relationships']['issue_level']}")
    print(f"pair level : {report['relationships']['pair_level']}")

    _say("Changes")
    print(f"corroborated -> not : {report['changes']['corroborated_to_not']['issues']}"
          f"   {report['changes']['lost_composition']}")
    print(f"not -> corroborated : {report['changes']['not_to_corroborated']['issues']}")
    print(f"unchanged yes/no    : {report['changes']['unchanged_corroborated']}"
          f" / {report['changes']['unchanged_not_corroborated']}")

    _say("Labels vs peer identities (Very-High-only)")
    for row in report["label_vs_identity"]["very_high_only"]:
        print(f"labels={row['labels']} peer_identities={row['peer_identities']}"
              f" -> {row['issues']} issues")
    print("including temporal:")
    for row in report["label_vs_identity"]["very_high_only_including_temporal"]:
        print(f"labels={row['labels']} comparisons={row['comparisons']}"
              f" -> {row['issues']} issues")

    _say("Evidence quality by source")
    print(f"rows  : {report['evidence_quality']['rows']}")
    print(f"issues: {report['evidence_quality']['issues']}")
    print(f"multi-identity issues with all-disjoint pairs, by scope: "
          f"{report['multi_disjoint_issues_by_scope']}")
    print(f"all+governorate issues: {report['all_plus_governorate']}")

    _say("Special cases")
    for name, payload in report["specials"].items():
        print(f"{name:44}: {payload['issues']}")
    print(f"{'same peers, conflicting statistics':44}: "
          f"{report['same_peers_conflicting_statistics']['issues']}")
    print(f"{'same peers, different policy block':44}: "
          f"{report['policy_versions']['same_peers_different_policy']['issues']}"
          f"  differing keys: "
          f"{report['policy_versions']['same_peers_different_policy']['differing_keys']}")
    print(f"{'policy version field names':44}: "
          f"{report['policy_versions']['version_field_names'] or 'none'}")

    _say("Zero writes")
    print(f"digest before: {report['fingerprint_before']['digest']}")
    print(f"digest after : {report['fingerprint_after']['digest']}")
    print(f"unchanged    : {report['zero_writes']}")
    print(f"\nreport written to {REPORT_PATH}")
    return 0 if report["zero_writes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
