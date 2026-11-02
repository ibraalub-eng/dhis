"""Independent identity of one statistical PEER comparison.

A Quality Alert row is labelled with the perspective that produced it (``all``,
``facility_type``, ``governorate``…). The label says WHY the group was chosen,
not WHICH hospitals were compared. Two rows carrying different labels but the
same peer set are the same statistical sample, and counting them as two
comparisons reports one piece of evidence twice.

This module answers, without touching the database:

* which peer ids a stored alert actually compared (``resolve_peer_ids``);
* whether the row is a peer comparison, a temporal (history) comparison, or
  cannot be classified (``comparison_type``);
* the deterministic identity of the comparison — hospital, canonical formula,
  month and the sorted peer ids (``comparison_identity``);
* how two identities relate by membership alone
  (``pairwise_relationship``).

The perspective name is deliberately NOT part of the identity. Neither are
severity, z-score, peer values, baseline, dispersion, group label or
perspective scope: those are outcomes or provenance of the sample, not the
sample itself, and including them would let a data revision or a re-worded
group masquerade as a second independent comparison.

Pure functions only: no session, no I/O, no caching, no mutation of the alert.
Malformed evidence is reported as ``invalid``/``unknown`` — never repaired and
never guessed from a label.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from app.engine.canonical_identity import alert_identity, identity_key

# Comparison types.
COMPARISON_PEER = "peer"
COMPARISON_TEMPORAL = "temporal"
COMPARISON_UNKNOWN = "unknown"

# Evidence states.
EVIDENCE_VALID = "valid"
EVIDENCE_INVALID = "invalid"
EVIDENCE_UNKNOWN = "unknown"

# Membership relationships between two peer sets.
RELATIONSHIP_IDENTICAL = "identical"
RELATIONSHIP_NESTED = "nested"
RELATIONSHIP_OVERLAPPING = "overlapping"
RELATIONSHIP_DISJOINT = "disjoint"
RELATIONSHIP_UNKNOWN = "unknown"

PERSPECTIVE_HISTORY = "history"

# The top-level ``evidence["peer_ids"]`` list is written truncated at 50 entries
# (engine/quality_alerts.py). A top-level list can therefore only prove
# completeness when the row's peer_count is within that limit.
TOP_LEVEL_PEER_LIMIT = 50


@dataclass(frozen=True)
class PeerEvidence:
    """Outcome of reading the peer ids stored on one alert row.

    ``state`` is ``valid`` (a complete peer group), ``invalid`` (the stored
    evidence contradicts itself) or ``unknown`` (absent or truncated, so no
    group can be established). ``reason`` is a stable machine-readable code.
    """

    state: str
    reason: Optional[str] = None
    peer_ids: Tuple[int, ...] = ()
    source: Optional[str] = None


@dataclass(frozen=True)
class ComparisonIdentity:
    """Identity of one comparison, or the reason there is none."""

    type: str
    state: str
    payload: Optional[dict]
    hash: Optional[str]
    peer_ids: Tuple[int, ...] = ()
    source: Optional[str] = None
    reason: Optional[str] = None
    formula_key: Optional[str] = None


def _evidence(alert: Any) -> Mapping:
    evidence = getattr(alert, "evidence", None)
    return evidence if isinstance(evidence, Mapping) else {}


def _peer_count(alert: Any) -> Optional[int]:
    count = getattr(alert, "peer_count", None)
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    return count


def _validate_ids(raw: Any) -> Tuple[str, Optional[str], Tuple[int, ...]]:
    """Validate a stored id list without repairing it.

    Returns ``(state, reason, ids)`` where state is ``valid``/``invalid``.
    Truncation is decided by the caller, which knows the expected count.
    """
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        return EVIDENCE_INVALID, "peer_ids_not_a_list", ()
    if not raw:
        return EVIDENCE_INVALID, "empty_peer_group", ()
    ids = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            return EVIDENCE_INVALID, "non_integer_peer_id", ()
        ids.append(value)
    if len(set(ids)) != len(ids):
        return EVIDENCE_INVALID, "duplicate_peer_ids", ()
    return EVIDENCE_VALID, None, tuple(ids)


def resolve_peer_ids(alert: Any, *,
                     max_top_level: int = TOP_LEVEL_PEER_LIMIT) -> PeerEvidence:
    """Resolve the complete peer group stored on ``alert``, or say why not.

    Resolution order, fixed by the Step 10C backward-compatibility policy:

    1. a complete nested ``evidence["comparison_policy"]["peer"]["peer_ids"]``;
    2. otherwise the top-level ``evidence["peer_ids"]``, only when it is
       complete and ``peer_count`` is within the truncation limit;
    3. otherwise ``unknown`` (truncated, absent or legacy);
    4. malformed values are ``invalid`` and never fall through to a weaker
       source — nested evidence is preferred, so a broken nested block is an
       error, not an invitation to read the truncated copy.

    History rows carry no peer group by construction and are reported as
    ``unknown`` with reason ``temporal_perspective``; use
    :func:`comparison_type` to classify those as temporal.
    """
    if getattr(alert, "perspective", None) == PERSPECTIVE_HISTORY:
        return PeerEvidence(EVIDENCE_UNKNOWN, "temporal_perspective")

    evidence = _evidence(alert)
    count = _peer_count(alert)
    policy = evidence.get("comparison_policy")

    if policy is not None:
        if not isinstance(policy, Mapping):
            return PeerEvidence(EVIDENCE_UNKNOWN, "malformed_comparison_policy")
        peer = policy.get("peer")
        if not isinstance(peer, Mapping):
            return PeerEvidence(EVIDENCE_UNKNOWN, "missing_peer_block")
        raw = peer.get("peer_ids")
        if raw is None:
            return PeerEvidence(EVIDENCE_UNKNOWN, "missing_nested_peer_ids")
        state, reason, ids = _validate_ids(raw)
        if state != EVIDENCE_VALID:
            return PeerEvidence(state, reason)
        if count is None:
            return PeerEvidence(EVIDENCE_INVALID, "missing_peer_count")
        if len(ids) < count:
            # Stored before the full group was persisted (or written truncated).
            return PeerEvidence(EVIDENCE_UNKNOWN, "truncated_nested_peer_ids")
        if len(ids) > count:
            return PeerEvidence(EVIDENCE_INVALID, "peer_count_mismatch")
        return PeerEvidence(EVIDENCE_VALID, None, ids, "nested")

    raw = evidence.get("peer_ids")
    if raw is None:
        return PeerEvidence(EVIDENCE_UNKNOWN, "missing_peer_evidence")
    state, reason, ids = _validate_ids(raw)
    if state != EVIDENCE_VALID:
        return PeerEvidence(state, reason)
    if count is None:
        return PeerEvidence(EVIDENCE_INVALID, "missing_peer_count")
    if count > max_top_level:
        # The stored top-level list is capped, so completeness cannot be proven.
        return PeerEvidence(EVIDENCE_UNKNOWN, "top_level_truncation_possible")
    if len(ids) < count:
        return PeerEvidence(EVIDENCE_UNKNOWN, "incomplete_top_level_peer_ids")
    if len(ids) > count:
        return PeerEvidence(EVIDENCE_INVALID, "peer_count_mismatch")
    return PeerEvidence(EVIDENCE_VALID, None, ids, "top_level")


def comparison_type(alert: Any) -> str:
    """``peer``, ``temporal`` or ``unknown`` for one stored alert row."""
    if getattr(alert, "perspective", None) == PERSPECTIVE_HISTORY:
        return COMPARISON_TEMPORAL
    evidence = resolve_peer_ids(alert)
    if evidence.state == EVIDENCE_VALID:
        return COMPARISON_PEER
    return COMPARISON_UNKNOWN


def _canonical_payload(alert: Any, peer_ids: Tuple[int, ...]) -> dict:
    """JSON-safe identity payload: scope + canonical formula + peer membership."""
    identity = alert_identity(alert)
    return {
        "hospital_id": getattr(alert, "hospital_id", None),
        "formula_identity": [part if isinstance(part, (int, float, str)) else str(part)
                             for part in identity],
        "month": getattr(alert, "month", None),
        # Sorted and unique: storage order must never change the identity.
        "peer_ids": sorted(set(peer_ids)),
    }


def comparison_identity(alert: Any) -> ComparisonIdentity:
    """Deterministic identity of the comparison behind ``alert``.

    The hash is SHA-256 over a canonical JSON encoding (sorted keys, no
    whitespace), so it is identical across processes and machines. Perspective,
    severity, z-score, peer values, baseline, dispersion, group label and
    perspective scope are all excluded by construction.

    A row that is not a valid peer comparison (history, legacy, truncated or
    malformed evidence) returns ``hash=None`` with its type, state and reason.
    """
    kind = comparison_type(alert)
    if kind != COMPARISON_PEER:
        evidence = resolve_peer_ids(alert)
        return ComparisonIdentity(type=kind, state=evidence.state,
                                  payload=None, hash=None,
                                  peer_ids=evidence.peer_ids,
                                  source=evidence.source,
                                  reason=evidence.reason)

    evidence = resolve_peer_ids(alert)
    payload = _canonical_payload(alert, evidence.peer_ids)
    if payload["hospital_id"] is None or not payload["month"]:
        return ComparisonIdentity(type=COMPARISON_UNKNOWN, state=EVIDENCE_UNKNOWN,
                                  payload=None, hash=None,
                                  peer_ids=evidence.peer_ids,
                                  source=evidence.source,
                                  reason="missing_scope")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return ComparisonIdentity(
        type=COMPARISON_PEER, state=EVIDENCE_VALID, payload=payload,
        hash=digest, peer_ids=evidence.peer_ids, source=evidence.source,
        formula_key=identity_key(alert_identity(alert)),
    )


def pairwise_relationship(left: Optional[ComparisonIdentity],
                          right: Optional[ComparisonIdentity]) -> str:
    """How two comparisons relate by peer-set membership alone.

    ``identical`` (same identity), ``nested`` (one set contains the other),
    ``overlapping`` (share members without containment), ``disjoint`` (no
    shared member), or ``unknown`` when either identity is unavailable.

    No thresholds are applied: overlap is reported as a fact, never converted
    into a similarity score.
    """
    if left is None or right is None:
        return RELATIONSHIP_UNKNOWN
    if left.hash is None or right.hash is None:
        return RELATIONSHIP_UNKNOWN
    if left.hash == right.hash:
        return RELATIONSHIP_IDENTICAL
    left_ids, right_ids = set(left.peer_ids), set(right.peer_ids)
    if left_ids <= right_ids or right_ids <= left_ids:
        return RELATIONSHIP_NESTED
    if left_ids & right_ids:
        return RELATIONSHIP_OVERLAPPING
    return RELATIONSHIP_DISJOINT


__all__ = [
    "COMPARISON_PEER",
    "COMPARISON_TEMPORAL",
    "COMPARISON_UNKNOWN",
    "EVIDENCE_INVALID",
    "EVIDENCE_UNKNOWN",
    "EVIDENCE_VALID",
    "RELATIONSHIP_DISJOINT",
    "RELATIONSHIP_IDENTICAL",
    "RELATIONSHIP_NESTED",
    "RELATIONSHIP_OVERLAPPING",
    "RELATIONSHIP_UNKNOWN",
    "TOP_LEVEL_PEER_LIMIT",
    "ComparisonIdentity",
    "PeerEvidence",
    "comparison_identity",
    "comparison_type",
    "pairwise_relationship",
    "resolve_peer_ids",
]
