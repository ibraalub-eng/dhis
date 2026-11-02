"""Read-only detail pass for the Step 10D-2 shadow report.

Answers the questions the main shadow run can only count: what actually
differs between two rows that compared the IDENTICAL peer set, whether a
policy VERSION differs (the version is nested at
``comparison_policy.peer.policy_version``), and how the ``all`` +
``facility_type`` duplicate behaves once collapsed to one comparison identity.

Read-only: SELECTs only, session rolled back, stored rows fingerprinted before
and after.

Usage:
    python scripts/shadow_comparison_identity_detail.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

sys.path.insert(0, ".")

from app.api import quality_alerts as qa  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.engine import comparison_identity as ci  # noqa: E402
from app.models import QualityAlert  # noqa: E402

REPORT_PATH = "logs/shadow_comparison_identity_detail.json"


def _fingerprint(db) -> dict:
    rows = (db.query(QualityAlert.id, QualityAlert.severity, QualityAlert.status,
                     QualityAlert.active, QualityAlert.updated_at,
                     QualityAlert.z_score, QualityAlert.current_value)
            .order_by(QualityAlert.id).all())
    digest = hashlib.sha256()
    for row in rows:
        digest.update(repr(tuple(row)).encode("utf-8"))
    return {"alert_rows": len(rows), "digest": digest.hexdigest()}


def _version_fields(node, prefix: str = "") -> set:
    """Every key anywhere in the policy block whose name mentions a version."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if "version" in str(key).lower():
                found.add(path)
            found |= _version_fields(value, path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found |= _version_fields(value, f"{prefix}[{index}]")
    return found


def main() -> int:
    db = SessionLocal()
    report: dict = {}
    try:
        before = _fingerprint(db)
        evidence = qa._evidence_by_issue(
            db, month=None, hospital_id=None, indicator=None, ownership_id=None,
            governorate_id=None, hospital_type_id=None, indicator_type=None,
            q=None, include_closed=False)

        version_fields = Counter()
        peer_versions = Counter()
        scope_values = Counter()
        group_values = Counter()

        groups_seen = 0
        identical_groups = 0
        differing_peer_keys = Counter()
        differing_policy_keys = Counter()
        version_differs = 0
        scope_differs = 0
        group_differs = 0
        examples: list = []

        identical_issue_scope = Counter()
        identical_issue_category = Counter()
        identical_issue_corroborated = 0
        identical_issues = 0

        all_and_ft_issues = 0
        all_and_ft_same_peers = 0

        for key, rows in evidence.items():
            hid, _formula, month = key
            by_hash: dict = {}
            for row in rows:
                policy = ((row.evidence or {}).get("comparison_policy") or {})
                version_fields.update(_version_fields(policy))
                peer = policy.get("peer") or {}
                if isinstance(peer, dict) and peer.get("policy_version"):
                    peer_versions[str(peer["policy_version"])] += 1
                if policy.get("perspective_scope"):
                    scope_values[str(policy["perspective_scope"])] += 1
                if isinstance(peer, dict) and peer.get("group"):
                    group_values[str(peer["group"])] += 1
                ident = ci.comparison_identity(row)
                if ident.hash:
                    by_hash.setdefault(ident.hash, []).append((row, policy))

            perspectives = {row.perspective for row in rows}
            if {"all", "facility_type"} <= perspectives:
                all_and_ft_issues += 1

            for _digest, group in by_hash.items():
                if len(group) < 2:
                    continue
                identical_groups += 1
                base_row, base_policy = group[0]
                peer_keys = set()
                policy_keys = set()
                versions = set()
                scopes = set()
                group_ids = set()
                for _row, policy in group:
                    peer = policy.get("peer") or {}
                    versions.add(str(peer.get("policy_version")))
                    scopes.add(str(policy.get("perspective_scope")))
                    group_ids.add(str(peer.get("group")))
                    for name in set(base_policy) | set(policy):
                        if (json.dumps(base_policy.get(name), sort_keys=True,
                                       default=str)
                                != json.dumps(policy.get(name), sort_keys=True,
                                              default=str)):
                            policy_keys.add(str(name))
                    for name in set(peer):
                        if (json.dumps(base_policy.get("peer", {}).get(name),
                                       sort_keys=True, default=str)
                                != json.dumps(peer.get(name), sort_keys=True,
                                              default=str)):
                            peer_keys.add(str(name))
                differing_policy_keys.update(policy_keys)
                differing_peer_keys.update(peer_keys)
                if len(versions) > 1:
                    version_differs += 1
                if len(scopes) > 1:
                    scope_differs += 1
                if len(group_ids) > 1:
                    group_differs += 1
                if len(examples) < 3:
                    examples.append({
                        "hospital_id": hid,
                        "month": month,
                        "indicator_code": group[0][0].indicator_code,
                        "alert_ids": sorted(row.id for row, _p in group),
                        "perspectives": sorted(row.perspective for row, _p in group),
                        "peer_count": len(ci.comparison_identity(base_row).peer_ids),
                        "peer_keys_differing": sorted(peer_keys),
                        "policy_keys_differing": sorted(policy_keys),
                        "policy_versions": sorted(versions),
                        "perspective_scopes": sorted(scopes),
                        "groups": sorted(group_ids),
                    })

            peer_hashes = len(by_hash)
            peer_rows = sum(len(g) for g in by_hash.values())
            if peer_hashes == 1 and peer_rows > 1:
                identical_issues += 1
                scope = qa._very_high_scope(rows)
                identical_issue_scope[scope or "no_very_high"] += 1
                record = None
                if scope == "only":
                    record = qa._very_high_corroborated(rows)
                if record:
                    identical_issue_corroborated += 1
                if {"all", "facility_type"} <= perspectives:
                    all_and_ft_same_peers += 1
                # Category, using the same priority order as the shadow run.
                if len(by_hash) >= 2:
                    identical_issue_category["multiple"] += 1
                elif qa._very_high_scope(rows) == "only":
                    identical_issue_category["single_peer"] += 1
                else:
                    identical_issue_category["other"] += 1
            groups_seen += len(by_hash)

        report["policy"] = {
            "version_field_paths": sorted(version_fields),
            "peer_policy_version_rows": dict(peer_versions),
            "perspective_scope_rows": dict(scope_values),
            "peer_group_rows": dict(group_values),
        }
        report["identical_peer_sets"] = {
            "groups_with_2plus_rows": identical_groups,
            "peer_keys_differing": dict(differing_peer_keys),
            "policy_keys_differing": dict(differing_policy_keys),
            "policy_version_differs": version_differs,
            "perspective_scope_differs": scope_differs,
            "peer_group_differs": group_differs,
            "examples": examples,
        }
        report["identical_peer_set_issues"] = {
            "issues": identical_issues,
            "by_scope": dict(identical_issue_scope),
            "currently_corroborated": identical_issue_corroborated,
            "category": dict(identical_issue_category),
        }
        report["all_plus_facility_type"] = {
            "issues_with_both_labels": all_and_ft_issues,
            "issues_where_one_comparison": all_and_ft_same_peers,
        }

        db.rollback()
        after = _fingerprint(db)
        report["fingerprint_before"] = before
        report["fingerprint_after"] = after
        report["zero_writes"] = before["digest"] == after["digest"]
        with open(REPORT_PATH, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, default=str)
    finally:
        db.rollback()
        db.close()

    print(json.dumps(report, indent=2, sort_keys=True, default=str)[:12000])
    return 0 if report["zero_writes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
