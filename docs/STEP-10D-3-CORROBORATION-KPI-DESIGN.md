# Step 10D-3 — Corroboration KPI semantics and UI design

**Status: DESIGN ONLY. Nothing in this document is implemented.**
No API, engine, Explain, frontend, KPI, schema, threshold or `systemControl`
change was made. No database write, backfill or recompute was run. The
published KPI still counts perspective labels and still reads **71** on the
live store.

Inputs: `app/engine/comparison_identity.py` (Step 10D-1) and the read-only
measurements of Step 10D-2 (`scripts/shadow_comparison_identity*.py`,
`logs/shadow_comparison_identity*.json`).

---

## 1. Core principle

Three separate statements that the current KPI silently merges:

| Statement | Unit | Today |
|---|---|---|
| "two comparison groups graded this Very High" | peer **identity** | not measured |
| "two perspective labels fired" | perspective **label** | this is the KPI |
| "two independent samples agreed" | **disjoint** peer sets | not measured, never claimed |

Rules the design enforces:

1. **A perspective label is not a comparison identity.** `governorate` and
   `ownership` are two labels that can compare the *same* hospitals; `all` and
   `facility_type` are two labels that, on this store, frequently compare the
   *identical* peer set (540 row-groups in 10D-2).
2. **A temporal perspective is not a peer comparison.** `history` compares the
   hospital to its own past months. It can never corroborate a peer finding,
   and it must never be counted in a peer count (today it is counted as a
   second label in 1 Very-High-only finding).
3. **Distinct identities are not independent evidence.** Two identities are
   *distinct* when their peer lists differ; they are *disjoint* only when they
   share no hospital. Nested and overlapping groups are one population seen
   twice.
4. **No statistical comparison is clinical confirmation.** Every label this
   design publishes is about the *comparison*, never about the patient care
   being correct. Banned vocabulary: "confirmed", "independent evidence",
   "clinically corroborated", "two sources agree".

## 2. Vocabulary (fixed for this stage and the next)

| Term | Definition |
|---|---|
| **Perspective row** | One stored `QualityAlert` row: one perspective × one indicator × one month. The evidence unit (`total_active`, `very_high_rows`). |
| **Issue** | One `(hospital, canonical formula, month)` — `_issue_key`. The finding unit (`total_issues`, `very_high_issues`, every card). |
| **Peer identity** | `comparison_identity.comparison_identity(evidence)` — a SHA-256 over the canonicalised, sorted `peer_ids` of a peer row, or a sentinel for "no peer comparison". Two rows share an identity **iff** they compared the same hospitals. |
| **Distinct peer comparisons** | Count of distinct non-sentinel identities on an issue. Two labels on one identity count **once**. |
| **Relationship** | Pairwise, over those identities: `identical` (impossible between distinct identities), `nested` (one peer set ⊂ the other), `overlapping` (share ≥1, neither contains the other), `disjoint` (share none). |
| **Temporal evidence** | `history` rows with a usable series and a decided verdict. Separate evidence class, never a peer. |
| **Evidence state** | Per row: `complete` / `ambiguous` / `invalid` (§4.2). |

## 3. Proposed classification (mutually exclusive)

Every Very-High-only finding gets **exactly one** primary category.

| # | Category key | Published name | Definition |
|---|---|---|---|
| 1 | `multiple_peer` | **Multiple peer comparisons** | ≥2 distinct valid peer identities, every comparison grading Very High |
| 2 | `single_peer` | **Single peer comparison** | Exactly 1 valid peer identity |
| 3 | `temporal_only` | **Temporal-only** | 0 peer identities, ≥1 valid temporal comparison |
| 4 | `unknown_identity` | **Unknown comparison identity** | 0 peers, 0 valid temporal, ≥1 row whose evidence cannot say what was compared |
| 5 | `invalid_evidence` | **Invalid evidence** | Every row of the issue fails validation; nothing decidable |

### 3.1 Precedence (stated, not implied)

`multiple_peer` > `single_peer` > `temporal_only` > `unknown_identity` >
`invalid_evidence`, evaluated on the issue's **whole** evidence set
(`_evidence_by_issue`), never on the rows a filter let through. The order is a
tie-break for *categorising*, not a licence to discard: everything the losing
category would have said is retained as an orthogonal flag (§6).

### 3.2 Per-row evidence state

| State | Test |
|---|---|
| `complete` | Peer method + `evidence["comparison_policy"]["peer"]["peer_ids"]` well-formed, or `history` + stored series + decided verdict |
| `ambiguous` | Peer method but no resolvable `peer_ids` (missing block, empty list, `peer_ids_truncated`, `peer_count` > 0 with no ids) |
| `invalid` | Evidence not a mapping; unknown perspective key; `len(peer_ids) != peer_count`; peer method with `perspective == "history"` |

An issue is `invalid_evidence` only when **all** rows are `invalid`; a single
invalid row inside a decidable issue is a flag, not a category.

### 3.3 Relationship subcategories (inside `multiple_peer`)

Over the distinct identities' pairwise matrix:

| Subcategory | Definition |
|---|---|
| `all_disjoint` | every pair disjoint |
| `nested_only` | ≥1 nested pair, no overlapping pair, no disjoint pair |
| `overlapping_only` | ≥1 overlapping pair, no nested pair, no disjoint pair |
| `mixed_relationships` | more than one of {disjoint, nested, overlapping} present |

Measured (10D-2): `all_disjoint` 0, `nested_only` 61, `overlapping_only` 9,
`mixed_relationships` 0 → 70.

## 4. Mixed evidence — one category, many flags

The rule: **the primary category answers "how many peer comparisons?"; every
other evidence fact is an attribute of that same finding.** Nothing is dropped
and nothing is counted twice, because attributes never add to a total.

| Mixed shape | Primary category | Flags retained | Why not its own bucket |
|---|---|---|---|
| Peer + temporal | `single_peer` / `multiple_peer` | `temporal_present`, `temporal_band`, `temporal_state` | Two evidence *classes*, one peer count. The peer count is what the KPI states; the trend is shown beside it. |
| Multiple peers + temporal | `multiple_peer` (+relationship) | same | Counting the trend as a third comparison is exactly the label error being fixed. |
| Peer + unknown | peer category | `unknown_present`, `unknown_perspectives` | The peer comparison is still decidable. |
| Peer + invalid | peer category | `invalid_present`, `invalid_perspectives` | Ditto; the invalid row is listed as unusable, not silently normalised. |
| Multiple identities, conflicting statistics | peer category | `statistics_conflict: true`, `conflict_fields` | Identity is decided by the peer set, so a conflict cannot change the count — it changes the *confidence wording* (§9.4). |
| Same peer IDs, different `policy_version` | one identity (**not** two) | `policy_version_mixed: true`, versions list | Same hospitals = same comparison. Different policy versions are a provenance warning, never a second sample. |
| No peer, no trend, nothing decidable | `unknown_identity` / `invalid_evidence` | per-row states | The only two categories that exist *because* evidence is unusable. |

### 4.1 Reconciliation rule (transparent, checkable)

1. Compute per issue: distinct peer identities, relationship matrix, temporal
   state, unknown/invalid row sets, statistics conflicts, policy versions.
2. Assign exactly one primary category by §3.1.
3. Emit flags from §4 that do not alter the count.
4. **Assert** `sum(category counts) == very_high_only_issues` and
   `single_peer + multiple_peer + temporal_only + unknown_identity +
   invalid_evidence == very_high_only_issues`. A failed assertion is a server
   error, never a silently dropped finding.
5. Report the orthogonal overlaps separately (`with_temporal_evidence`, …), so
   a reader can see that the categories partition while the flags overlap.

Measured: **354 = 70 + 225 + 59 + 0 + 0**, overlaps: 62 carry a temporal row,
1 of them is the peer+temporal case, 0 unknown, 0 invalid.

## 5. KPI dictionary (proposed)

All new fields are **issue** units. Row units stay exactly as published
(`total_active`, `very_high_rows`, `by_perspective`), and no new field mixes
the two.

| Field | Name on screen | Definition | Tooltip (EN, officer-facing) |
|---|---|---|---|
| `very_high_only_issues` | Very High only | every fired comparison graded Very High | "Every comparison that fired graded this indicator Very High, so none disagreed. This says nothing yet about how many different groups of hospitals were used." |
| `very_high_multiple_peer_issues` | Multiple peer comparisons | ≥2 distinct peer identities | "Graded Very High against two or more groups of hospitals. 'Nested' or 'overlapping' means one group shares hospitals with another, so the agreement is not from a second sample." |
| `very_high_single_peer_issues` | Single peer comparison | exactly 1 peer identity | "Only one group of hospitals was used. Nothing else was compared, so nothing could agree or disagree." |
| `very_high_temporal_only_issues` | Temporal-only | no peer, ≥1 trend comparison | "No peer group was used. The value was compared with this hospital's own earlier months." |
| `very_high_unknown_identity_issues` | Unknown comparison identity | evidence cannot name the comparison | "The stored evidence does not say which hospitals were compared, so this cannot be counted as a peer comparison." |
| `very_high_invalid_evidence_issues` | Invalid evidence | evidence fails validation | "The stored comparison record is inconsistent and was not used. Recalculate the month before acting on it." |
| `mixed_severity_issues` | Mixed severity | ≥1 Very High and ≥1 lower band | "At least one comparison graded Very High while another graded lower. The comparisons disagree, so the finding is kept apart." |

Relationship chips (inside Multiple peer comparisons):
`Separate hospital groups` 0 · `Nested groups` 61 · `Overlapping groups` 9 ·
`Mixed relationships` 0.

Arabic keys are added for each English string through `static/js/i18n.js`, keyed
on the English text as the screen already does (e.g. existing
`'Corroborated is part of Very High only — …'`). No sentence is composed by
concatenating translated fragments, and perspective/relationship names are
translated as whole units (the `explain-prose.js` contract).

## 6. The existing label-based KPI

**Recommendation: retain, do not rename in place, demote to a documented legacy
diagnostic.**

* Keep `very_high_only_corroborated_issues` (currently **71**) with its current
  value and semantics for at least one release. Renaming a published key would
  break `dashboard`, `audit_severity_counts.py`, the UI tests and any consumer
  that is not in this repository.
* Add `very_high_only_corroborated_terms: "perspective_labels"` so the unit is
  unambiguous in the payload itself, and document it as *label agreement*, not
  agreement between samples.
* New headline number is `very_high_multiple_peer_issues` (**70**). The legacy
  figure stays visible in the card's tooltip/detail line:
  "Label-based count (legacy): 71 — includes 61 nested and 9 overlapping peer
  groups."
* Rollout in three approvals, never in one:
  1. **Publish only** — new fields added beside the old ones; no card changes.
  2. **Card swap** — headline becomes 70, legacy 71 moves into the tooltip.
  3. **Deprecate** — after ≥1 release, mark the old key deprecated in docs,
     keep returning it, remove only with an explicit decision.
* Optional feature flag for stage 2 (`quality_alerts.comparison_identity_kpi`,
  default **off**) — proposed only; `systemControl` is untouched in this stage.

## 7. UI design

### 7.1 KPI row

`Very High only 354` becomes a **total card** that states its own partition,
same convention as today's `qaKpiOnlySum`:

```
Very High only          354
  70 Multiple peer comparisons   61 nested · 9 overlapping · 0 separate groups
 225 Single peer comparison
  59 Temporal-only
   0 Unknown / invalid
  70 + 225 + 59 = 354
```

Elements: `qaKpiMultiplePeer`, `qaKpiMultiplePeerNested`,
`qaKpiMultiplePeerOverlapping`, `qaKpiMultiplePeerDisjoint`, `qaKpiSinglePeer`,
`qaKpiTemporalOnly`, `qaKpiUnknownInvalid`, `qaKpiOnlySumIdentities`.
The legacy `qaKpiCorroborated` (71) is kept in the DOM but rendered inside the
card's detail line with the "legacy (perspective labels)" tag, not as a
top-level number.

### 7.2 Filters

Extend the existing `very_high_scope` parameter (do not add a parallel
mechanism): `only | mixed | multiple_peer | single_peer | temporal_only |
unknown_identity | invalid_evidence | nested_only | overlapping_only |
all_disjoint`. `corroborated` stays accepted and keeps its exact current
meaning during the transition. Card clicks keep the existing
`qualityAlertsToggleVeryHighScope` contract, so the card that was clicked
still shows its own number.

### 7.3 Issue detail — "Comparison evidence" block

One row per **identity**, not per perspective:

| Group | Perspectives on it | Hospitals used | Compared with | Band | Policy |
|---|---|---|---|---|---|
| Governorate peers | Regional peers | 12 | Overlaps ownership peers (4 shared) | Very High (z 4.2) | 2026-10-24.1 |
| Ownership peers | Ownership peers | 7 | Overlaps governorate peers (4 shared) | Very High (z 3.9) | 2026-10-24.1 |

Then, in its own section, never in the peer table:

```
Hospital history (time comparison): Very High · 24 earlier months · not a peer group
```

Details:

* **Peer IDs**: collapsed behind "Which hospitals?" showing up to 10
  `hospital_id`s with names when the catalog resolves them, then "+N more";
  `peer_ids_truncated` shows "group too large to list (N hospitals)".
* **Relationship badge** per identity: `Shares hospitals with …` (nested or
  overlapping) / `No shared hospitals` (disjoint). The word *independent* is
  not used.
* **Evidence quality**: `Complete` / `Comparison group not recorded` /
  `Inconsistent record`, plus the policy version chip; a mixed version set
  shows `Policy versions differ (2)`.
* **Conflicting statistics**: both values shown side by side with
  "These two records disagree about the same comparison; neither is chosen."
  (0 today; the design still renders it.)

### 7.4 Officer sentence (Explain and card detail)

Composed from numbers, translated as whole templates:

> "Very High. Compared with 12 governorate hospitals (z 4.2) and with 7
> hospitals of the same ownership (z 3.9). The ownership group includes 4 of
> those 12 hospitals, so this is one finding seen twice — not two separate
> confirmations. The hospital's own earlier months also graded Very High."

For a disjoint case the last-clause template becomes "These two groups share no
hospitals." — still followed by "A statistical comparison is not a clinical
confirmation."

## 8. Explain design

`_quality_alert_cross_check` (`explain.py` ~2048) currently emits one
`peer_perspectives` card per stored row. Change of presentation only:

1. Group `peer_perspectives` by `comparison_identity` **before** ordering.
2. Group header states `3 stored perspectives · 2 hospital groups`; never
   "corroborated by three perspectives".
3. Inside a group, one band row and a list of the labels that produced it, with
   "same hospital group" stated once.
4. `all` + `facility_type` on the identical peer set (540 row-groups today)
   renders as **one** group with both labels listed.
5. The cross-check intro sentence gains: "Perspectives that compare the same
   hospital group are shown once; they are not separate confirmations."
6. Existing constraints preserved: Diagnostics row untouched, no re-query,
   Rule B verdict reused, closed alerts still labelled as stored-only.

Hard rule enforced in code: any sentence containing an agreement word
("agree", "confirm", "corroborat") must be built from
`peer_comparisons >= 2` **and** `relationship in {all_disjoint}`; otherwise the
sentence uses "graded Very High in N comparisons of overlapping groups".

## 9. Numerical reconciliation (from Step 10D-2, unaltered)

| Figure | Value |
|---|---|
| canonical issues | 2,658 |
| Very-High-only | 354 |
| mixed-severity | 447 |
| no Very High | 1,857 |
| published corroborated (labels) | 71 |
| distinct-peer-identity findings | 70 |
| pairwise-disjoint Very-High-only | **0** |
| single peer comparison | 225 |
| temporal-only | 59 |

Partition: **70 + 225 + 59 + 0 + 0 = 354**.

### 9.1 Why 70 and not 71

Exactly one published corroboration pairs two **labels** that resolve to one
**identity**: h6 / 2026-04 / `8.b` / alerts 4006 + 6618 — `history` +
`ownership`. Two labels, one peer group, plus a trend. 71 − 1 = **70**.

### 9.2 Why 70 and not 0

"Distinct" and "disjoint" answer different questions:

* **Distinct identity** — did the two rows use the *same list* of hospitals?
  61 of the 70 use different lists where one contains the other
  (`governorate` ⊂ `ownership` on this store), 9 use lists that partly overlap.
  So: 70 findings have two genuinely different reference populations.
* **Disjoint** — do those lists share *no* hospital? None do. A list that
  contains the other cannot be a separate sample, and partial overlap means
  some z-scores were computed from the same values.

Hence: **70 comparisons, 0 independent comparisons.** Both numbers are true and
they answer different questions; the KPI must publish the first and explain the
second, not pick whichever sounds better.

### 9.3 Why no Very-High-only finding is disjoint

Disjoint multi-identity issues do exist — 41 of them — but they sit entirely in
the mixed (5) and no-Very-High (36) populations. When two genuinely separate
groups are compared, the bands tend to diverge, which puts the issue in
`mixed_severity_issues`. This is a measured property of the store, not a rule;
the design does not assume it will hold after a rescan.

### 9.4 Conflicts and versions

* Identical peer sets with conflicting statistics: **0** in the store. If they
  appear, the identity count does not change; the finding is labelled
  `Inconsistent record` and both values are shown.
* Different `policy_version` on identical peer IDs: **0**. Single version
  `2026-10-24.1` on all 4,086 peer rows. If a second version appears, the same
  peer set still counts once, flagged `Policy versions differ`.
* Mismatch with earlier exploratory figures (73 vs 71 published; 3 vs 1
  `history`-shaped false corroborations) is reported, not reconciled. This
  design uses the 10D-2 live population.

## 10. API design (future implementation)

### 10.1 `GET /quality-alerts/summary` — added

```jsonc
{
  "very_high_only_issues": 354,
  "very_high_multiple_peer_issues": 70,
  "very_high_single_peer_issues": 225,
  "very_high_temporal_only_issues": 59,
  "very_high_unknown_identity_issues": 0,
  "very_high_invalid_evidence_issues": 0,
  "very_high_only_breakdown": {
    "total": 354,
    "multiple_peer": 70, "multiple_peer_pct": 19.8,
    "single_peer": 225, "single_peer_pct": 63.6,
    "temporal_only": 59, "temporal_only_pct": 16.7,
    "unknown_identity": 0, "invalid_evidence": 0,
    "multiple_peer_by_relationship": {
      "all_disjoint": 0, "nested_only": 61,
      "overlapping_only": 9, "mixed_relationships": 0
    },
    "with_temporal_evidence": 62,
    "with_unknown_evidence": 0,
    "with_invalid_evidence": 0,
    "with_statistics_conflict": 0,
    "with_mixed_policy_versions": 0,
    "legacy_corroborated_perspective_labels": 71
  },
  "very_high_only_corroborated_issues": 71,
  "very_high_only_corroborated_terms": "perspective_labels"
}
```

Nothing existing is renamed or removed. `very_high_only_by_perspectives` and
`very_high_single_perspective_by_perspective` stay as the label-level view.

### 10.2 `GET /quality-alerts/issues` — per issue

```jsonc
{
  "comparison_evidence": {
    "classification": "multiple_peer",
    "relationship_class": "nested_only",
    "distinct_peer_comparisons": 2,
    "temporal_present": true,
    "temporal": {"band": "VERY_HIGH", "months": 24, "state": "complete"},
    "statistics_conflict": false,
    "policy_versions": ["2026-10-24.1"],
    "identities": [
      {"identity": "a1b2c3d4e5f6", "perspectives": ["governorate"],
       "label": "Regional peers (governorate)", "peer_count": 12,
       "peer_ids": [12, 41, 63], "peer_ids_truncated": false,
       "peer_group": "stratified:governorate",
       "policy_version": "2026-10-24.1",
       "band": "VERY_HIGH", "z": 4.2, "state": "complete",
       "relations": [{"identity": "f6e5d4c3b2a1", "relation": "nested_inside",
                      "shared_peers": 4}]}
    ]
  }
}
```

### 10.3 Per-perspective row (`_alert_dict`) — added

`comparison_identity` (12-char prefix), `identity_shared_with` (perspective
keys on the same identity), `counts_as_peer_comparison` (false for `history`),
`peer_ids_truncated`, `evidence_state`.

All are additive; `perspective`, `perspective_label`, `peer_count`,
`comparison_policy` keep their current meaning.

## 11. Consuming functions (inventory, not changed)

| Layer | Functions |
|---|---|
| Pure helper (already exists) | `comparison_identity.resolve_peer_ids`, `comparison_type`, `comparison_identity`, `pairwise_relationship` |
| Backend calculation | new `_issue_comparison_evidence(rows)` in `app/api/quality_alerts.py`, built on the helper; `_effective_severity` reused unchanged for the band |
| Summary aggregation | `get_summary` (new breakdown block), `_very_high_only_breakdown` (extended), `_very_high_corroborated` superseded by category assignment but kept as the legacy predicate |
| Issue list | `_group_alerts`, `_alert_dict`, `_evidence_by_issue` (unchanged inputs) |
| Explain | `_quality_alert_cross_check`, `_peer_perspective_view`, `_PEER_PERSPECTIVE_ORDER` (`app/engine/audit/explain.py`) |
| Frontend | `_renderKpis`, `_renderVeryHighOnlyBreakdown`, `_VH_SCOPE_HELP`, `_renderScopeCards`, issue evidence renderer (`static/js/quality-alerts.js` ~1111, ~1206), `_renderPeerCrossCheck` (`static/js/explain.js` ~518) |
| Localization | `static/js/i18n.js` (quality-alerts section ~104–180), `static/js/explain-prose.js` sentence builders |

Complexity: ≤4 identities per issue, 2,658 issues — the pairwise step is
trivial and stays pure, with no extra query and no persisted identity.

## 12. Acceptance criteria for the future implementation

1. Every Very-High-only finding has exactly one category; the five counts sum
   to `very_high_only_issues` (asserted server-side).
2. `multiple_peer_by_relationship` sums to `multiple_peer`.
3. Peer+temporal, peer+unknown, peer+invalid, conflicts and version mixes are
   visible as flags, never dropped and never double counted.
4. Two perspectives on one identity count once — `all` + `facility_type`
   identical sets never read as two comparisons.
5. No string (API, UI, Explain, i18n) calls a nested or overlapping group
   independent, and none calls a statistical comparison clinical confirmation.
6. Temporal evidence never appears in the peer list or the peer count.
7. `very_high_only_corroborated_issues` still returns **71** until an explicit
   approval changes it; card swap is a separate, approved step.
8. Reported figures reconcile with 10D-2: 354, 70, 225, 59, 0, 71, 447, 2,658.
9. Issue counts and perspective-row counts remain separate fields and separate
   cards; no card adds a row count to an issue count.

## 13. Open decisions requiring approval (not taken here)

1. Stage-2 card swap and whether the legacy 71 stays on the card or only in the
   tooltip.
2. Whether `statistics_conflict` should *suppress* the corroboration wording
   entirely (design says: keep the count, change the wording).
3. Whether `unknown_identity` findings should be excluded from the Very High
   total or shown as a "cannot assess" line (design says: show, never subtract).
4. Whether the UI should display peer hospital names or only IDs (privacy and
   misreading risk).
5. Whether `history` should ever be shown with an "agrees/confirms" verb at all
   (design says no — it is a different evidence class).
