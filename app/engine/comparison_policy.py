"""One explicit temporal + peer-comparison policy for outlier analysis.

Anomaly Diagnostics and Quality Alerts answer different questions, but when
they ask the SAME question they must use the SAME window and the SAME peer
group. This module is the single place that policy lives.

What is (and is not) shared
---------------------------
* **Hospital-history baseline** — both engines use the most recent
  ``window`` *stored reporting months* before the analysed month. Months
  inside that window whose value cannot be computed are skipped, never
  treated as zero, and the baseline is only evaluable when at least
  ``min_observations`` valid points remain (with the per-indicator
  ``minimum_history_period`` acting as a stricter floor).
* **Detection peer group** — every active hospital with a valid value for the
  same month and formula, excluding the analysed hospital itself, with at
  least ``min_peers`` other hospitals. This is the group behind the
  Diagnostics peer layer AND the ``all`` perspective in Quality Alerts.
* **Stratified alert perspectives** (same type / ownership / facility type /
  governorate) are deliberately NOT the detection baseline: they answer a
  narrower question and may legitimately disagree. They use the same minimum
  peer count and are labelled as stratified everywhere they are recorded;
  they never replace or suppress the canonical diagnostic result.

The older behaviour was not a policy at all: Diagnostics used every prior
month ever recorded while Alerts used the last 12. A long history therefore
diluted a recent step enough for one engine to call it a mild deviation while
the other called the same month extreme (the reported 0.11 vs 1.0).
"""
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# Approved defaults. The window is deliberately capped by BOTH the configured
# alert window and the System Control analysis window, so raising one control
# can never make the two engines silently disagree again.
HISTORY_WINDOW_DEFAULT = 12
MIN_HISTORY_OBSERVATIONS_DEFAULT = 3
MIN_PEERS_DEFAULT = 2

DETECTION_PEER_GROUP = "all_active_reporting"
STRATIFIED_PEER_GROUP_PREFIX = "stratified:"

# Persisted in diagnostics/alert provenance so an old row can be explained
# after the policy changes.
COMPARISON_POLICY_VERSION = "2026-10-24.1"


@dataclass(frozen=True)
class HistoryPolicy:
    """Last-N-reporting-months window + minimum valid observations."""

    window: int = HISTORY_WINDOW_DEFAULT
    min_observations: int = MIN_HISTORY_OBSERVATIONS_DEFAULT

    def with_item_minimum(self, minimum_history_period: Optional[int]) -> "HistoryPolicy":
        """Apply a per-indicator floor (the stricter minimum wins)."""
        try:
            floor = int(minimum_history_period or 0)
        except (TypeError, ValueError):
            floor = 0
        return replace(self, min_observations=max(self.min_observations, floor))

    def as_dict(self) -> Dict[str, Any]:
        return {"window": self.window,
                "min_observations": self.min_observations}


@dataclass(frozen=True)
class PeerPolicy:
    """Minimum other hospitals + the canonical group name."""

    min_peers: int = MIN_PEERS_DEFAULT
    group: str = DETECTION_PEER_GROUP

    def as_dict(self) -> Dict[str, Any]:
        return {"min_peers": self.min_peers, "group": self.group}


@dataclass(frozen=True)
class ComparisonPolicy:
    history: HistoryPolicy = HistoryPolicy()
    peer: PeerPolicy = PeerPolicy()
    version: str = COMPARISON_POLICY_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {"version": self.version,
                "history": self.history.as_dict(),
                "peer": self.peer.as_dict()}


@dataclass(frozen=True)
class HistoryWindow:
    """The exact window and valid observations used by one baseline."""

    window: int
    months: List[str]                    # every reporting month in the window
    observations: List[Tuple[str, float]]
    skipped_months: List[str]

    @property
    def values(self) -> List[float]:
        return [value for _month, value in self.observations]

    @property
    def valid_count(self) -> int:
        return len(self.observations)

    def is_sufficient(self, min_observations: int) -> bool:
        return self.valid_count >= max(1, int(min_observations))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "window": self.window,
            "months": list(self.months),
            "observations": [[month, value] for month, value in self.observations],
            "skipped_months": list(self.skipped_months),
            "valid_count": self.valid_count,
        }


def _bounded_int(value, default: int, minimum: int, maximum: int = 120) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def resolve_comparison_policy(
    alerts_config: Optional[Mapping[str, Any]] = None,
    trend_window: Optional[int] = None,
) -> ComparisonPolicy:
    """Resolve the approved policy from saved settings.

    The effective history window is the SHORTER of the alert window and the
    System Control trend analysis window. Both default to 12, so a fresh
    install uses the last 12 reporting months; tightening either control
    tightens both engines together.

    ``alerts_min_history`` is the system floor for valid observations and
    ``alerts_min_peers`` the floor for other hospitals in a comparison. Both
    are clamped to the documented safe minimums (2 observations, 2 peers).
    """
    cfg = alerts_config or {}
    alert_window = _bounded_int(
        cfg.get("alerts_history_window"), HISTORY_WINDOW_DEFAULT, 1)
    analysis_window = _bounded_int(
        trend_window, HISTORY_WINDOW_DEFAULT, 1)
    min_history = _bounded_int(
        cfg.get("alerts_min_history"), MIN_HISTORY_OBSERVATIONS_DEFAULT, 2, 24)
    min_peers = _bounded_int(
        cfg.get("alerts_min_peers"), MIN_PEERS_DEFAULT, 2, 100)
    return ComparisonPolicy(
        history=HistoryPolicy(
            window=min(alert_window, analysis_window),
            min_observations=min_history,
        ),
        peer=PeerPolicy(min_peers=min_peers),
    )


def load_comparison_policy(db) -> ComparisonPolicy:
    """Database-backed policy (AppConfig alerts + System Control trend window)."""
    from app.config_utils import get_config_dict

    alerts_cfg = get_config_dict(db, "alerts")
    trend_window = HISTORY_WINDOW_DEFAULT
    try:
        from app.engine.severity import load_analysis_config
        trend_window = load_analysis_config(db).trend.window
    except Exception:  # config unreadable -> documented default window
        pass
    return resolve_comparison_policy(alerts_cfg, trend_window)


def history_window_months(history: Mapping[str, Any], current_month: str,
                          window: int) -> List[str]:
    """The last ``window`` reporting months strictly before ``current_month``.

    "Reporting months" are the months the hospital actually has in
    ``history``. A calendar month with no stored data is not invented; the
    window slides over the months that exist, exactly as before, but is now
    bounded.
    """
    months = sorted(month for month in history if month < current_month)
    if window > 0:
        months = months[-window:]
    return months


def history_window(
    history: Mapping[str, Any],
    current_month: str,
    policy: HistoryPolicy,
    value_for_month: Callable[[str], Optional[float]],
) -> HistoryWindow:
    """Apply the policy and keep the exact valid observations.

    ``value_for_month`` computes the indicator's value from that month's raw
    values. None / non-finite results are recorded as skipped, not coerced.
    """
    import math

    months = history_window_months(history, current_month, policy.window)
    observations: List[Tuple[str, float]] = []
    skipped: List[str] = []
    for month in months:
        value = value_for_month(month)
        try:
            numeric = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric = None
        if numeric is None or not math.isfinite(numeric):
            skipped.append(month)
            continue
        observations.append((month, numeric))
    return HistoryWindow(window=policy.window, months=months,
                         observations=observations,
                         skipped_months=skipped)


def stratified_peer_group(name: str) -> str:
    """Canonical group id for an intentionally narrower comparison."""
    return f"{STRATIFIED_PEER_GROUP_PREFIX}{name}"


def peer_group_label(group: str) -> str:
    """Human label for a persisted peer-group id."""
    if group == DETECTION_PEER_GROUP:
        return "All active reporting hospitals"
    if group.startswith(STRATIFIED_PEER_GROUP_PREFIX):
        return group[len(STRATIFIED_PEER_GROUP_PREFIX):]
    return group


__all__ = [
    "COMPARISON_POLICY_VERSION",
    "DETECTION_PEER_GROUP",
    "HISTORY_WINDOW_DEFAULT",
    "MIN_HISTORY_OBSERVATIONS_DEFAULT",
    "MIN_PEERS_DEFAULT",
    "ComparisonPolicy",
    "HistoryPolicy",
    "HistoryWindow",
    "PeerPolicy",
    "history_window",
    "history_window_months",
    "load_comparison_policy",
    "peer_group_label",
    "resolve_comparison_policy",
    "stratified_peer_group",
]
