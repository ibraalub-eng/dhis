"""P3.3.0 legacy Confidence parity harness.

Captures the pre-P3.3 engine output for the six approved scenarios under four
representative policy combinations. The fixture is generated deliberately with
``A3_5_WRITE_CONFIDENCE_LEGACY=1`` and is compared byte-for-byte (after JSON
decoding) by ``tests/test_a3_5_confidence_legacy.py``.

The fixture was captured from the pre-P3.3 engine. This replay constructs the
same immutable ``ConfidencePolicy`` values from each captured policy; it does
not regenerate the fixture or read live configuration in the engine.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from app.engine.confidence import calculate_confidence
from app.engine.confidence_policy import ConfidencePolicy
from app.engine.quality import RuleResult, RuleStatus, RuleType, Severity
from app.models import AppConfig, ConfidenceWeights

FIXTURE = Path(__file__).with_name("fixtures") / "a3_5_confidence_legacy_parity.json"

DEFAULT_WEIGHTS = {
    "rule_compliance": 0.55,
    "historical": 0.10,
    "cross_hospital": 0.10,
    "trend": 0.10,
    "completeness": 0.15,
}
EQUAL_WEIGHTS = {key: 0.2 for key in DEFAULT_WEIGHTS}

STANDARD_CUTOFFS = {
    "confidence_high": 80.0,
    "confidence_medium": 50.0,
    "confidence_low": 25.0,
}
HIGH_CUTOFFS = {
    "confidence_high": 95.0,
    "confidence_medium": 55.0,
    "confidence_low": 30.0,
}

HISTORY = {
    f"2025-{month:02d}": {"2": 100.0}
    for month in range(1, 10)
}

CROSS_HOSPITALS = {
    "H": {"3": 1000.0},
    **{f"Peer {i}": {"3": 100.0} for i in range(1, 10)},
}

SCENARIOS: Dict[str, dict] = {
    "present": {
        "values": {"2": 300.0},
        "rule_results": [],
        "historical_data": {},
        "all_hospital_data": {"H": {"2": 300.0}},
        "indicator_map": {"2": "Total Deliveries"},
        "indicator_children": {},
        "indicator_rule_map": {},
        "key_indicator_codes": ["2"],
    },
    "missing": {
        "values": {"2": 300.0},
        "rule_results": [],
        "historical_data": {},
        "all_hospital_data": {"H": {"2": 300.0}},
        "indicator_map": {"2": "Total Deliveries", "16": "NICU admissions"},
        "indicator_children": {},
        "indicator_rule_map": {},
        "key_indicator_codes": ["2", "16"],
    },
    "multi": {
        "values": {"2": 300.0, "3": 200.0, "5": 80.0},
        "rule_results": [],
        "historical_data": {},
        "all_hospital_data": {"H": {"2": 300.0, "3": 200.0, "5": 80.0}},
        "indicator_map": {
            "2": "Total Deliveries",
            "3": "NVD",
            "5": "C-sections",
        },
        "indicator_children": {},
        "indicator_rule_map": {},
        "key_indicator_codes": ["2", "3", "5"],
    },
    "rule_failure": {
        "values": {"2": 300.0},
        "rule_results": [
            RuleResult("R001", "Delivery sum mismatch", RuleStatus.FAIL,
                       Severity.HIGH, RuleType.LOGIC, "Delivery sum mismatch"),
        ],
        "historical_data": {},
        "all_hospital_data": {"H": {"2": 300.0}},
        "indicator_map": {"2": "Total Deliveries"},
        "indicator_children": {},
        "indicator_rule_map": {"2": ["R001"]},
        "key_indicator_codes": ["2"],
    },
    "history_outlier": {
        "values": {"2": 1000.0},
        "rule_results": [],
        "historical_data": HISTORY,
        "all_hospital_data": {"H": {"2": 1000.0}},
        "indicator_map": {"2": "Total Deliveries"},
        "indicator_children": {},
        "indicator_rule_map": {},
        "key_indicator_codes": ["2"],
    },
    "cross_outlier": {
        "values": {"3": 1000.0},
        "rule_results": [],
        "historical_data": {},
        "all_hospital_data": CROSS_HOSPITALS,
        "indicator_map": {"3": "NVD"},
        "indicator_children": {},
        "indicator_rule_map": {},
        "key_indicator_codes": ["3"],
    },
}

POLICIES: Dict[str, dict] = {
    "default_standard_z25": {
        "weights": DEFAULT_WEIGHTS,
        "cutoffs": STANDARD_CUTOFFS,
        "zscore_threshold": 2.5,
        "weights_row": False,
        "cutoffs_row": False,
        "zscore_row": False,
    },
    "default_standard_z99": {
        "weights": DEFAULT_WEIGHTS,
        "cutoffs": STANDARD_CUTOFFS,
        "zscore_threshold": 99.0,
        "weights_row": False,
        "cutoffs_row": False,
        "zscore_row": True,
    },
    "default_high_z25": {
        "weights": DEFAULT_WEIGHTS,
        "cutoffs": HIGH_CUTOFFS,
        "zscore_threshold": 2.5,
        "weights_row": False,
        "cutoffs_row": True,
        "zscore_row": False,
    },
    "default_high_z99": {
        "weights": DEFAULT_WEIGHTS,
        "cutoffs": HIGH_CUTOFFS,
        "zscore_threshold": 99.0,
        "weights_row": False,
        "cutoffs_row": True,
        "zscore_row": True,
    },
    "equal_standard_z25": {
        "weights": EQUAL_WEIGHTS,
        "cutoffs": STANDARD_CUTOFFS,
        "zscore_threshold": 2.5,
        "weights_row": True,
        "cutoffs_row": False,
        "zscore_row": False,
    },
    "equal_standard_z99": {
        "weights": EQUAL_WEIGHTS,
        "cutoffs": STANDARD_CUTOFFS,
        "zscore_threshold": 99.0,
        "weights_row": True,
        "cutoffs_row": False,
        "zscore_row": True,
    },
    "equal_high_z25": {
        "weights": EQUAL_WEIGHTS,
        "cutoffs": HIGH_CUTOFFS,
        "zscore_threshold": 2.5,
        "weights_row": True,
        "cutoffs_row": True,
        "zscore_row": False,
    },
    "equal_high_z99": {
        "weights": EQUAL_WEIGHTS,
        "cutoffs": HIGH_CUTOFFS,
        "zscore_threshold": 99.0,
        "weights_row": True,
        "cutoffs_row": True,
        "zscore_row": True,
    },
}


def _set_weights(db, policy: dict) -> None:
    db.query(ConfidenceWeights).delete(synchronize_session=False)
    if policy["weights_row"]:
        db.add(ConfidenceWeights(**policy["weights"]))
    db.commit()


def _set_thresholds(db, policy: dict) -> None:
    keys = (*policy["cutoffs"].keys(), "zscore_threshold")
    db.query(AppConfig).filter(AppConfig.key.in_(keys)).delete(
        synchronize_session=False)
    if policy["cutoffs_row"]:
        for key, value in policy["cutoffs"].items():
            db.add(AppConfig(key=key, value=float(value), category="thresholds",
                             label=key))
    if policy["zscore_row"]:
        db.add(AppConfig(key="zscore_threshold",
                         value=float(policy["zscore_threshold"]),
                         category="thresholds", label="zscore_threshold"))
    db.commit()


def _policy(policy: dict) -> ConfidencePolicy:
    return ConfidencePolicy(
        **policy["weights"],
        high=policy["cutoffs"]["confidence_high"],
        medium=policy["cutoffs"]["confidence_medium"],
        low=policy["cutoffs"]["confidence_low"],
        zscore_threshold=policy["zscore_threshold"],
    )


def _call(scenario: dict, confidence_policy: ConfidencePolicy):
    return calculate_confidence(
        hospital_name="H",
        month="2026-04",
        values=scenario["values"],
        rule_results=scenario["rule_results"],
        historical_data=scenario["historical_data"],
        all_hospital_data=scenario["all_hospital_data"],
        indicator_map=scenario["indicator_map"],
        indicator_children=scenario["indicator_children"],
        indicator_rule_map=scenario["indicator_rule_map"],
        key_indicator_codes=scenario["key_indicator_codes"],
        confidence_policy=confidence_policy,
        auto_disable_null=False,
    )


def capture(db) -> dict:
    """Return the deterministic pre-P3.3 output matrix.

    The captured policy values are replayed through the immutable
    ``ConfidencePolicy``; the frozen fixture remains the comparison authority.
    """
    results: Dict[str, Dict[str, dict]] = {}
    for policy_name, policy in POLICIES.items():
        _set_weights(db, policy)
        _set_thresholds(db, policy)
        resolved_policy = _policy(policy)
        results[policy_name] = {
            name: _call(scenario, resolved_policy).to_dict()
            for name, scenario in SCENARIOS.items()
        }
    return {
        "fixture_version": "1",
        "engine": "app.engine.confidence.calculate_confidence",
        "engine_note": (
            "Captured before P3.3 consumer changes; legacy SIGNAL_WEIGHTS, "
            "ConfidenceWeights.first(), and thresholds AppConfig reads."
        ),
        "policies": POLICIES,
        "scenarios": {
            name: {
                "values": scenario["values"],
                "key_indicator_codes": scenario["key_indicator_codes"],
                "rule_failure": bool(scenario["rule_results"]),
                "historical_months": sorted(
                    scenario["historical_data"].keys()),
                "peer_hospitals": sorted(
                    scenario["all_hospital_data"].keys()),
            }
            for name, scenario in SCENARIOS.items()
        },
        "results": results,
    }


def dump(capture_data: dict) -> str:
    return json.dumps(capture_data, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
