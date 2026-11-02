# Step 6B — Explain cross-perspective evidence (verification record)

Status: **presentation only.** The Step 6B code was already in the working tree;
this session verified it against the Step 6B specification and recorded the
result. No Rule B logic, historical eligibility, severity, score, threshold,
cap, peer grouping, `systemControl` value, Diagnostics calculation, stored band,
database row, migration or back-fill was changed. The stored-band fingerprint is
`b011d3087075a8816a609b12bb56823af961461c` before and after, unchanged.

## 1. Files carrying Step 6B

| File | Role |
|---|---|
| `app/engine/audit/explain.py` | `peer_perspectives` collection inside the existing `_quality_alert_cross_check`; `_PEER_PERSPECTIVE_ORDER`, `_peer_scale_evidence`, `_peer_perspective_view` |
| `static/js/explain.js` | `_renderPeerPerspectives` plus `_peerPerspectiveReason` / `_peerScaleLine`, rendered under the cross-check |
| `static/js/i18n.js` | English + Arabic keys for the heading, distinction sentence, reason sentences, scales, comparability, zero share and perspective names |
| `tests/test_explain_top_band.py` | Step 6B matrix: seven identities / eight perspectives, renderer and i18n tests |

The cross-check reuses its single identity match — `hospital + month + canonical
formula` — so there is no second query and no second matcher. Peer statistics,
scores, bands, eligibility, groups, severity and caps are never recomputed.

## 2. Payload shape

Only stored evidence is exposed. `mad` and `iqr` are objects
`{value, band, usable}`; stored `0.0` and `false` survive as values, and a
missing field stays `null` rather than being defaulted.

`h36 / 2026-07 / 13` — alert `#6090`, type perspective (undecided scales):

```json
[{
  "source": "quality_alerts",
  "alert_id": 6090,
  "perspective": "type",
  "label": "Similar hospitals (type)",
  "peer_count": 5,
  "current": 344.0,
  "threshold": 2.5,
  "verdict": "undecided",
  "reason_code": "SCALES_DISAGREE",
  "mad": {"value": 27.0, "band": "VERY_HIGH", "usable": true},
  "iqr": {"value": 67.0, "band": "MODERATE", "usable": true},
  "scales_supporting": null,
  "group_comparability_status": "not_verified",
  "zero_share": 0.0,
  "zero_share_warning": false
}]
```

`h36 / 2026-06 / 9` — alert `#5679`, single usable scale and a zero-heavy group:

```json
[{
  "source": "quality_alerts", "alert_id": 5679, "perspective": "type",
  "label": "Similar hospitals (type)", "peer_count": 4,
  "current": 8.0, "threshold": 2.5,
  "verdict": "eligible", "reason_code": "ONLY_AVAILABLE_SCALE_SUPPORTS",
  "mad": {"value": 0.0, "band": null, "usable": false},
  "iqr": {"value": 0.25, "band": "VERY_HIGH", "usable": true},
  "scales_supporting": null,
  "group_comparability_status": "not_verified",
  "zero_share": 0.75, "zero_share_warning": true
}]
```

`h22 / 2026-07 / 2.l` returns two cards — ownership `#6243`, then governorate
`#6245`. The lower-band row `#6242` is deliberately absent.

## 3. Rendering rules

- One block under the cross-check headed **Quality Alerts — Peer Perspectives**,
  with the fixed distinction paragraph: Diagnostics shows this analysis row and
  its own analytical layers; Quality Alerts may hold separate peer perspectives
  for the same hospital, month and indicator, evaluated under a different
  policy; a peer `VERY_HIGH` does not imply the historical assessment is
  `VERY_HIGH`.
- One card per perspective, ordered type → ownership → governorate, then by
  alert id. Cards are never merged and none is presented as the definitive
  result.
- The verdict is always read together with `reason_code`. `undecided` never
  reads as a confirmation; a `verdict`/`reason_code` pair that disagrees is
  reported as *not interpreted* rather than defaulted.
- Covered reasons: `BOTH_SCALES_SUPPORT`, `ONLY_AVAILABLE_SCALE_SUPPORTS`,
  `SCALES_DISAGREE`, `ONLY_AVAILABLE_SCALE_REFUSES`,
  `DEFINITION_NOT_ESTABLISHABLE`, `NO_ROBUST_SCALE`,
  `BOTH_USABLE_SCALES_REFUSE`, `NO_STORED_PEER_VALUES`,
  `INSUFFICIENT_PEER_VALUES`, `CURRENT_VALUE_MISSING`.
- MAD and IQR are shown independently as usable / unusable / unavailable. An
  unusable scale is never described as refusing the top band.
- Zero share is informational only, flagged at the existing 50% display
  threshold. It never affects eligibility, verdict or band.
- Comparability is shown as verified / not verified / unavailable; a missing
  stored status is never upgraded to "not verified".

## 4. Field availability

| Field | Source | When absent |
|---|---|---|
| `alert_id`, `perspective`, `peer_count`, `current` | Quality Alert row | `unavailable` |
| `threshold` | stored Rule B evidence | `unavailable` |
| `verdict`, `reason_code` | stored comparison policy | `unavailable`, never defaulted |
| `mad`, `iqr` | stored robust-scale evidence | `unavailable` |
| `scales_supporting` | **not stored anywhere** | always `null` → `unavailable`, never reconstructed from `reason_code` |
| `group_comparability_status` | stored gate evidence | `unavailable`; shown only for groups that were actually judged (hidden for `NO_STORED_PEER_VALUES` and `PEER_POLICY`) |
| `zero_share`, `zero_share_warning` | stored evidence | `unavailable`; the 50% flag is a display fallback only |
| `label` | `PERSPECTIVE_LABELS` display map | not analytical evidence |

## 5. Verification run

| Check | Result |
|---|---|
| `tests/test_explain_top_band.py` | 63 passed — all 7 identities / 8 perspectives, h22 two-card order, h36 `SCALES_DISAGREE`, zero-share 0.75 + IQR-only, MAD-unusable + IQR-only, missing peer evidence, identity no-cross-match, Diagnostics invariance |
| `tests/test_explain.py`, `test_explain_comparative.py`, `test_explain_covered_missing.py`, `test_explain_trail.py` | 72 passed, 1 skipped — Step 5B–5D wording intact |
| `tests/test_insufficient_history_policy.py` | 10 passed |
| `ruff check app/engine/audit/explain.py` | clean |
| `node --check static/js/explain.js`, `static/js/i18n.js` | exit 0 |
| Stored-band fingerprint | `b011d3087075a8816a609b12bb56823af961461c`, unchanged |
| Database writes | none — every run used the isolated SQLite fixture |
| Working tree | unchanged apart from this document; no pre-existing modification lost |

The renderer is verified by executing the real JS helpers in node against real
payloads; no screenshot was captured.
