"""Pure unit tests for app.engine.comparison_identity.

No database, no fixtures: the helper only reads attributes from an alert-like
object, so these tests build the smallest possible stand-in and pin the Step
10C rules (peer-set identity, nested-before-top-level evidence, no inference
from perspective labels).
"""
from types import SimpleNamespace

from app.engine.comparison_identity import (
    COMPARISON_PEER,
    COMPARISON_TEMPORAL,
    COMPARISON_UNKNOWN,
    EVIDENCE_INVALID,
    EVIDENCE_UNKNOWN,
    EVIDENCE_VALID,
    RELATIONSHIP_DISJOINT,
    RELATIONSHIP_IDENTICAL,
    RELATIONSHIP_NESTED,
    RELATIONSHIP_OVERLAPPING,
    RELATIONSHIP_UNKNOWN,
    comparison_identity,
    comparison_type,
    pairwise_relationship,
    resolve_peer_ids,
)


def nested_evidence(ids, values=None):
    """Stored provenance exactly as the scan writes it."""
    return {
        "comparison_policy": {
            "peer": {
                "group": "all_active_reporting",
                "group_label": "All hospitals",
                "peer_ids": list(ids),
                "values": values if values is not None else {
                    str(i): 1.0 for i in ids},
            },
        },
    }


def make_alert(*, hospital_id=1, month="2026-08", perspective="all",
               peer_count=None, evidence=None, code="RATE",
               formula="NUM / DEN * 100", unit="%"):
    return SimpleNamespace(
        hospital_id=hospital_id, month=month, perspective=perspective,
        peer_count=peer_count, evidence=evidence, indicator_code=code,
        formula=formula, unit=unit,
    )


def peer_alert(ids, *, perspective="all", hospital_id=1, month="2026-08",
               code="RATE", formula="NUM / DEN * 100", unit="%", values=None):
    return make_alert(hospital_id=hospital_id, month=month,
                      perspective=perspective, peer_count=len(ids),
                      evidence=nested_evidence(ids, values), code=code,
                      formula=formula, unit=unit)


# ── Identity ────────────────────────────────────────────────────────────────

def test_all_and_facility_type_with_identical_peers_share_identity():
    all_row = peer_alert([2, 3, 4], perspective="all")
    type_row = peer_alert([2, 3, 4], perspective="facility_type")
    assert comparison_identity(all_row).hash == comparison_identity(type_row).hash


def test_perspective_label_never_participates_in_identity():
    ids = [5, 6, 7, 8]
    hashes = {comparison_identity(peer_alert(ids, perspective=p)).hash
              for p in ("all", "facility_type", "governorate", "ownership",
                        "type")}
    assert len(hashes) == 1


def test_peer_order_does_not_change_identity():
    assert (comparison_identity(peer_alert([9, 4, 7])).hash
            == comparison_identity(peer_alert([4, 7, 9])).hash)


def test_different_hospital_changes_identity():
    a = comparison_identity(peer_alert([2, 3], hospital_id=1))
    b = comparison_identity(peer_alert([2, 3], hospital_id=2))
    assert a.hash != b.hash


def test_different_indicator_changes_identity():
    a = comparison_identity(peer_alert([2, 3], code="RATE_A",
                                       formula="NUM / DEN * 100"))
    b = comparison_identity(peer_alert([2, 3], code="RATE_B",
                                       formula="OTHER / DEN * 100"))
    assert a.hash != b.hash


def test_different_month_changes_identity():
    a = comparison_identity(peer_alert([2, 3], month="2026-07"))
    b = comparison_identity(peer_alert([2, 3], month="2026-08"))
    assert a.hash != b.hash


def test_different_peer_sets_change_identity():
    a = comparison_identity(peer_alert([2, 3, 4]))
    b = comparison_identity(peer_alert([2, 3, 5]))
    assert a.hash != b.hash


def test_peer_values_do_not_change_identity():
    a = comparison_identity(peer_alert([2, 3], values={"2": 1.0, "3": 2.0}))
    b = comparison_identity(peer_alert([2, 3], values={"2": 9.5, "3": 0.25}))
    assert a.hash == b.hash
    assert a.payload["peer_ids"] == [2, 3]


def test_identity_hash_is_deterministic_across_calls():
    alert = peer_alert([12, 3, 8])
    assert comparison_identity(alert).hash == comparison_identity(alert).hash
    assert len(comparison_identity(alert).hash) == 64


# ── Peer evidence resolution ────────────────────────────────────────────────

def test_complete_nested_evidence_is_valid():
    evidence = resolve_peer_ids(peer_alert([2, 3, 4]))
    assert evidence.state == EVIDENCE_VALID
    assert evidence.peer_ids == (2, 3, 4)
    assert evidence.source == "nested"


def test_truncated_nested_evidence_is_unknown():
    alert = make_alert(peer_count=6, evidence=nested_evidence([2, 3, 4]))
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_UNKNOWN
    assert evidence.reason == "truncated_nested_peer_ids"
    assert comparison_identity(alert).hash is None


def test_complete_top_level_evidence_at_limit_is_valid():
    alert = make_alert(peer_count=3, evidence={"peer_ids": [7, 8, 9]})
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_VALID
    assert evidence.source == "top_level"
    assert evidence.peer_ids == (7, 8, 9)


def test_top_level_evidence_at_exactly_fifty_peers_is_valid():
    ids = list(range(1, 51))
    alert = make_alert(peer_count=50, evidence={"peer_ids": ids})
    assert resolve_peer_ids(alert).state == EVIDENCE_VALID


def test_top_level_evidence_above_limit_is_unknown():
    alert = make_alert(peer_count=51, evidence={"peer_ids": list(range(1, 52))})
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_UNKNOWN
    assert evidence.reason == "top_level_truncation_possible"


def test_incomplete_top_level_evidence_is_unknown():
    alert = make_alert(peer_count=5, evidence={"peer_ids": [1, 2, 3]})
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_UNKNOWN
    assert evidence.reason == "incomplete_top_level_peer_ids"
    assert comparison_identity(alert).hash is None


def test_history_row_is_temporal_not_peer():
    alert = make_alert(perspective="history", peer_count=None,
                       evidence={"history": {"window": 6}})
    assert comparison_type(alert) == COMPARISON_TEMPORAL
    identity = comparison_identity(alert)
    assert identity.type == COMPARISON_TEMPORAL
    assert identity.hash is None


def test_missing_evidence_is_unknown_legacy():
    alert = make_alert(peer_count=None, evidence=None)
    assert comparison_type(alert) == COMPARISON_UNKNOWN
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_UNKNOWN
    assert evidence.reason == "missing_peer_evidence"


def test_duplicate_peer_ids_are_invalid():
    alert = make_alert(peer_count=3,
                       evidence=nested_evidence([2, 2, 4]))
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_INVALID
    assert evidence.reason == "duplicate_peer_ids"
    assert comparison_identity(alert).hash is None


def test_non_integer_peer_ids_are_invalid():
    alert = make_alert(peer_count=2,
                       evidence=nested_evidence(["2", 3]))
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_INVALID
    assert evidence.reason == "non_integer_peer_id"


def test_boolean_peer_id_is_invalid():
    alert = make_alert(peer_count=2, evidence=nested_evidence([True, 3]))
    assert resolve_peer_ids(alert).state == EVIDENCE_INVALID


def test_missing_peer_count_is_invalid():
    ids = [2, 3]
    alert = make_alert(peer_count=None, evidence=nested_evidence(ids))
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_INVALID
    assert evidence.reason == "missing_peer_count"


def test_empty_peer_group_is_invalid():
    alert = make_alert(peer_count=0, evidence=nested_evidence([]))
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_INVALID
    assert evidence.reason == "empty_peer_group"


def test_nested_evidence_is_preferred_over_top_level():
    alert = make_alert(peer_count=2, evidence={
        "comparison_policy": {"peer": {"peer_ids": [2, 3]}},
        "peer_ids": [99],
    })
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_VALID
    assert evidence.source == "nested"
    assert evidence.peer_ids == (2, 3)


def test_broken_nested_block_does_not_fall_back_to_top_level():
    alert = make_alert(peer_count=2, evidence={
        "comparison_policy": {"peer": {}},
        "peer_ids": [2, 3],
    })
    evidence = resolve_peer_ids(alert)
    assert evidence.state == EVIDENCE_UNKNOWN
    assert evidence.reason == "missing_nested_peer_ids"


# ── Pairwise relationships ──────────────────────────────────────────────────

def test_relationship_identical():
    a = comparison_identity(peer_alert([2, 3, 4], perspective="all"))
    b = comparison_identity(peer_alert([2, 3, 4], perspective="facility_type"))
    assert pairwise_relationship(a, b) == RELATIONSHIP_IDENTICAL


def test_relationship_nested():
    a = comparison_identity(peer_alert([2, 3]))
    b = comparison_identity(peer_alert([2, 3, 4, 5]))
    assert pairwise_relationship(a, b) == RELATIONSHIP_NESTED
    assert pairwise_relationship(b, a) == RELATIONSHIP_NESTED


def test_relationship_overlapping():
    a = comparison_identity(peer_alert([2, 3, 4]))
    b = comparison_identity(peer_alert([4, 5, 6]))
    assert pairwise_relationship(a, b) == RELATIONSHIP_OVERLAPPING


def test_relationship_disjoint():
    a = comparison_identity(peer_alert([2, 3, 4]))
    b = comparison_identity(peer_alert([5, 6, 7]))
    assert pairwise_relationship(a, b) == RELATIONSHIP_DISJOINT


def test_relationship_unknown_when_identity_unavailable():
    a = comparison_identity(peer_alert([2, 3]))
    legacy = comparison_identity(make_alert(evidence=None))
    assert pairwise_relationship(a, legacy) == RELATIONSHIP_UNKNOWN
    assert pairwise_relationship(a, None) == RELATIONSHIP_UNKNOWN
    assert pairwise_relationship(None, None) == RELATIONSHIP_UNKNOWN


def test_comparison_type_peer_for_valid_group():
    assert comparison_type(peer_alert([2, 3])) == COMPARISON_PEER
