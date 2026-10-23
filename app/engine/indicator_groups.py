"""Canonical indicator groups — suitable clinical domains, not site labels.

The registry previously labelled system definitions with the technical site
key ("System indicators / zscore"), which meant nothing to a reader and
could not be reused as a work unit. These groups replace that: every system
rate belongs to ONE clinical domain, and the domain is what other screens
(audit scopes, outlier sets, report sections, forecast boards…) select when
they ask for "a group of indicators" — one stable name that works in any
job.

Groups are data, not code: user-created definitions carry their own
``group_name`` and simply join the same namespace, and the
``GET /indicators/groups`` endpoint reports whatever the active catalog
contains. The mapping here only decides the DEFAULT group a system
definition is seeded with (and re-synced to on drift, versioned with full
history like every other content change).
"""

from typing import Optional, Tuple

GROUP_DELIVERY = "Delivery & Surgery"
GROUP_MATERNAL = "Maternal Outcomes"
GROUP_NEWBORN = "Newborn Outcomes"
GROUP_NEWBORN_CARE = "Newborn Care"
GROUP_RISK = "Risk Factors"
DEFAULT_GROUP = "System Rates"

# Stable display order for the canonical groups; anything else sorts after.
GROUP_ORDER = [GROUP_DELIVERY, GROUP_MATERNAL, GROUP_NEWBORN,
               GROUP_NEWBORN_CARE, GROUP_RISK, DEFAULT_GROUP]

# (site, rate_code) -> clinical domain. Covers the zscore, clinical and
# forecast slices; an unmapped rate falls back to DEFAULT_GROUP rather than
# inventing a label.
GROUP_BY_RATE: dict = {
    # zscore slice (anomaly monitoring rates)
    ("zscore", "rate_cs"): GROUP_DELIVERY,
    ("zscore", "rate_mmr"): GROUP_MATERNAL,
    ("zscore", "rate_smm"): GROUP_MATERNAL,
    ("zscore", "rate_nmr"): GROUP_NEWBORN,
    ("zscore", "rate_stillbirth"): GROUP_NEWBORN,
    ("zscore", "rate_nicu"): GROUP_NEWBORN,
    ("zscore", "rate_preterm"): GROUP_NEWBORN,
    # clinical slice (classification rates)
    ("clinical", "rate_cs"): GROUP_DELIVERY,
    ("clinical", "rate_avd"): GROUP_DELIVERY,
    ("clinical", "rate_hysterectomy"): GROUP_DELIVERY,
    ("clinical", "rate_mmr"): GROUP_MATERNAL,
    ("clinical", "rate_smm"): GROUP_MATERNAL,
    ("clinical", "rate_smm_hemorrhage_proportion"): GROUP_MATERNAL,
    ("clinical", "rate_smm_hypertensive_proportion"): GROUP_MATERNAL,
    ("clinical", "rate_nmr"): GROUP_NEWBORN,
    ("clinical", "rate_stillbirth"): GROUP_NEWBORN,
    ("clinical", "rate_nicu"): GROUP_NEWBORN,
    ("clinical", "rate_lbw"): GROUP_NEWBORN,
    ("clinical", "rate_preterm"): GROUP_NEWBORN,
    ("clinical", "rate_bf"): GROUP_NEWBORN_CARE,
    ("clinical", "rate_adolescent"): GROUP_RISK,
    ("clinical", "rate_high_risk"): GROUP_RISK,
    # forecast slice (forecasting rates)
    ("forecast", "cs_rate"): GROUP_DELIVERY,
    ("forecast", "smm_per_1000"): GROUP_MATERNAL,
    ("forecast", "smm_per_1000_deliveries"): GROUP_MATERNAL,
    ("forecast", "mat_mortality_rate"): GROUP_MATERNAL,
    ("forecast", "stillbirth_rate"): GROUP_NEWBORN,
    ("forecast", "preterm_rate"): GROUP_NEWBORN,
    ("forecast", "lbw_rate"): GROUP_NEWBORN,
    ("forecast", "nd_per_1000"): GROUP_NEWBORN,
    ("forecast", "high_risk_rate"): GROUP_RISK,
    ("forecast", "adolescent_rate"): GROUP_RISK,
}


def system_group_name(site: Optional[str], rate_code: Optional[str]) -> str:
    """Default group for a system definition keyed by (site, rate_code)."""
    return GROUP_BY_RATE.get((site or "", rate_code or ""), DEFAULT_GROUP)


def group_sort_key(name: str) -> Tuple[int, str]:
    """Canonical groups in display order, then everything else alphabetically."""
    try:
        return (GROUP_ORDER.index(name), "")
    except ValueError:
        return (len(GROUP_ORDER), name)
