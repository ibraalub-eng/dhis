# Peer eligibility for the VERY_HIGH bottom band — proposal (not implemented)

Status: **design and read-only simulation only.** No production code, configuration,
threshold, migration or stored row was changed. Nothing in this document is active:
`very_high_eligibility()` still returns `undecided` for a peer-held top band, the peer
policies (`cap_thin_peer`, `cap_zero_spread`) are the rules that judge it today, and
every screen still reads the band it read before.

Reproduce (read-only; scripts were run from a temporary directory, no script was added
to the repository):

```bash
.venv/Scripts/python.exe <temp>/vhpeer/scope.py        # the 1,130 / 723 population
.venv/Scripts/python.exe <temp>/vhpeer/dist.py         # group size, spread, |z|
.venv/Scripts/python.exe <temp>/vhpeer/stability.py    # MAD, leave-one-out
.venv/Scripts/python.exe <temp>/vhpeer/integrity.py    # units, numerator/denominator
.venv/Scripts/python.exe <temp>/vhpeer/policy_final.py # the proposed policy
```

Each script only reads `QualityAlert` / `LayeredOutlierResult`; the stored-band
fingerprint is `b011d3087075a8816a609b12bb56823af961461c` before and after, identical to
the baseline recorded in
[VERY-HIGH-ELIGIBILITY-CONSISTENCY.md](VERY-HIGH-ELIGIBILITY-CONSISTENCY.md).

## 1. Verified scope (recomputed, not assumed)

| quantity | value |
|---|---|
| active alert rows | 5,043 |
| stored `VERY_HIGH` among them | 1,389 |
| **undecided by the history gate** | **1,130** |
| of those: route / method | 1,130 `peer` / 1,130 `peer_zscore` |
| distinct analytical events behind them | 723 |
| rows per event | 1,483 / 2,119 / 3,82 / 4,32 / 5,7 |

So all 1,130 are peer comparisons; none is a volume, raw-count, unit-mismatch or
missing-window case, and none is a duplicate row of another perspective — the five
perspectives of one event are five separate claims, each against its own group.

## 2. What the stored rows already carry

Every one of the 1,130 rows stores, on the row itself:

* `evidence.stats` — `mean`, `std`, `median`, `min`, `max`, `z_provenance`;
* `evidence.comparison_policy.peer` — `group`, `group_label`, `month`, `min_peers`,
  `eligible_count`, `peer_ids` and **`values`** (member hospital → value);
* `evidence.canonical` — the formula key the comparison was made on;
* `evidence.z_threshold` (2.5) and `peer_count`, `current_value`, `numerator`,
  `denominator`, `perspective`.

Recomputing `std` from the stored member values reproduces the stored `std` to a maximum
relative error of 4.8e-05 (4-decimal rounding only), so the evidence is internally
consistent and a simulation can be run without recomputing any peer group.

## 3. Observed peer evidence

Group size (1,130 rows): 4 → 290, 5 → 211, 6 → 95, 7 → 164, 8 → 55, 9 → 23, 10 → 26,
11 → 70, 12 → 78, 13 → 66, 14 → 46, 15 → 6. In buckets: **4–5 → 501 (44.3%)**,
6–8 → 314 (27.8%), 9–11 → 119 (10.5%), 12+ → 196 (17.3%). No row has fewer than 4
peers (the thin-peer cap already refuses those before the gate).

Implied classical |z| (from the stored mean/std): [4.5, 6) → 445 (39.4%),
[6, 10) → 449 (39.7%), [10, 25) → 187 (16.5%), ≥ 25 → 49 (4.3%); median 6.54,
maximum 108.6.

Spread shape: 58.6% of groups contain a peer reporting exactly 0 (expected on count
indicators), 754 groups contain repeated values, `CV > 1` in 603 rows, |skew| > 1 in 370.
`MAD = 0` (more than half the group shares one value) in **413 rows (36.5%)** and
`IQR = 0` in 212 — i.e. for a third of the population there is no robust scale at all.

Stability: removing any single peer drops the classical |z| below the top-band boundary
(4.5) in **180 rows (15.9%)**.

## 4. Comparability and data quality (no invented doubt)

* `0` rows were found with the hospital inside the peers' `[min, max]` — the flag is a
  genuine outside-the-group claim in every case.
* The 59 resolvable rate rows reconcile exactly with `numerator / denominator ×
  multiplier`; `0` mismatches. No negative values on either side.
* `74` rows use legacy `sys_*` analysis codes with no current spec entry
  (`sys_zscore_rate_*`, `sys_forecast_adolescent`, …). Their comparison is still
  verifiable from the persisted `canonical.formula` + `unit` on the row, but a
  read path must not consult the live registry for them or a future registry edit would
  silently change a historical decision.
* **Unit string present on only 133 of 1,130 alerts** (documentation gap; the formula key
  and numerator/denominator are present, so scale identity holds by construction).
* `comparison_policy.peer.min_peers = 2` (the configured group-eligibility floor) is not
  the number that governs the top band: `MIN_PEERS_FOR_TOP_BAND = 4` does. Both are
  approved; the provenance must not be read as "2 peers is enough for VERY_HIGH".
* All 1,130 rows store `z_threshold = 2.5` and policy version `2026-10-24.1`.

## 5. Proposed three-state policy

Each rule reuses an existing constant or an existing engine function. **No new
threshold, cutoff, minimum group size or sigma convention is introduced.**

**Step 1 — applicability (unchanged).** The row is a peer perspective holding the top
band, and the approved peer caps did not already refuse it (`n ≥ 4`, spread > 0).
Otherwise `not_applicable` — never counted as support or refusal.

**Step 2 — comparability.** Require the persisted formula key, the stored member values,
`n ≥ MIN_PEERS_FOR_TOP_BAND`, and, for a rate row, `current = numerator/denominator ×
multiplier`. Fail → `undecided`, reason `PROVENANCE_OR_UNIT_INCOMPLETE` (0 rows today;
this guards future scans).

**Step 3 — robust-scale agreement.** Score the same group with the engine's own robust
scorers, `score_from_mad` / `score_from_iqr`, and band them with `level_for_score`:

* MAD scale available (`MAD > 0`) and its level is not `VERY_HIGH` → **`ineligible`**.
* MAD level is `VERY_HIGH` but the IQR level is lower → `undecided`
  (`SCALES_DISAGREE`). Both estimators are the engine's; nothing says which is right, so
  the band is neither confirmed nor refused.
* MAD unavailable (`MAD = 0`): the IQR level decides support — `VERY_HIGH` → eligible
  basis, lower → `undecided` (`SECONDARY_SCALE_REFUSES_NO_PRIMARY`).
  The IQR score is **not** allowed to refuse on its own: with small integer counts and
  ties it reports `LOW` for a value of 3 against a group of `[0, 0, 0, 0, 1, 1, 1]`,
  which is plainly not "not extreme".
* No robust scale at all (`MAD = IQR = 0`) → `undecided` (`NO_ROBUST_SCALE`).

**Step 4 — single-peer stability.** Recompute the classical |z| with each peer removed;
if any removal drops it below the existing top-band boundary (4.5 = 0.90 × 2 × 2.5), the
band rests on one hospital → `undecided` (`BAND_RESTS_ON_ONE_PEER`).

Otherwise → **`eligible`** (`SUPPORTED_BY_MAD_AND_STABLE` / `SUPPORTED_BY_IQR_ONLY`).

`eligible` and `undecided` both leave the displayed band at `VERY_HIGH`; only
`ineligible` would read `HIGH`, and it never reads lower. The policy can therefore never
lower a band below `HIGH`, never touches a row that is not `VERY_HIGH`, and is idempotent
(it reads only stored evidence).

## 6. Simulation (read-only, on the isolated store)

| candidate | eligible | ineligible → HIGH | undecided |
|---|---|---|---|
| A. current policy | 0 | 0 | 1,130 |
| **P′. proposed** | **680 (60.2%)** | **1 (0.1%)** | **449 (39.7%)** |
| B. σ-consistent z_MAD ≥ 4.5 (experimental) | 705 | 84 (7.4%) | 341 |
| C. P′ + minimum group of 6 (experimental) | 359 | 430 (38.1%) | 341 |

P′ reasons among the 449 undecided: `NO_ROBUST_SCALE` 212, `BAND_RESTS_ON_ONE_PEER` 117,
`SCALES_DISAGREE` 108, `SECONDARY_SCALE_REFUSES_NO_PRIMARY` 12.

P′ by perspective: governorate 74.9% supported, ownership 71.3%, type 52.9%,
facility_type 42.3%, `all` 42.3%. By group size: 4–5 → 68.1%, 6–8 → 64.3%, 9+ → 43.5%
(larger groups have more spread, so the same value is less extreme on a robust scale —
the opposite of the intuition that bigger groups decide better).

Event level (723): 482 supported by at least one perspective, 240 where no perspective
supports the band, 1 refused by every perspective. 64 events carry mixed verdicts across
perspectives; 163 events have a canonical `all` row, and in 96 of them a narrower
perspective supports the band while `all` does not.

## 7. Risks and limitations

1. **The refusal branch is effectively empty (1 row).** On today's evidence the peer
   top band is *not* refutable; the value of the policy is that it turns 60% of a
   blanket `undecided` into an affirmative, auditable support and names why the rest
   cannot be measured. It must not be sold as a cap.
2. **Candidate B must not ship as-is.** Its 84 refusals depend on a *new* sigma
   convention; 63% of them sit within 10% of the boundary, and 39% belong to one
   hospital (33 rows), which is indistinguishable from a manual exception.
3. **Candidate C contradicts an approved control.** A minimum of 6 raises the effective
   `MIN_PEERS_FOR_TOP_BAND = 4` without approval and refuses 346 otherwise supported
   rows; 63% of them are governorate comparisons, i.e. the thinnest real peer sets.
4. **A third of the population has no robust scale**, almost all of them count
   indicators whose peer groups are mostly zeros (211 of 212 have peer mean < 5). Their
   classical |z| median is 8.9, so they are strongly outside the group; they stay
   `undecided` by design, not because the flag is doubtful.
5. **The unit string is missing on 1,000 rows.** Comparability currently rests on the
   persisted formula key; writing `unit` on new scans would remove the inference.
6. **Perspective-level verdicts differ legitimately.** A stratified group can support a
   band that the canonical `all` group does not; the documented comparison policy says
   stratified comparisons never suppress the canonical result, so no agreement is
   enforced — the screen must name the group instead.

## 8. Questions requiring approval (not decided here)

1. Approve P′ as an audit/report-only policy first, and only then decide whether it may
   reach the screens — the same two-step used for the history gate?
2. Should `SCALES_DISAGREE` (108 rows) stay `undecided`, or is a robust-vs-classical
   tie-break rule wanted? Any such rule is a new statistical convention and needs its
   own evidence.
3. Should a stratified `VERY_HIGH` require the canonical `all` group to agree (96 events
   would lose support)? This contradicts the documented comparison policy as written.
4. Is a larger minimum group for the top band worth reopening `MIN_PEERS_FOR_TOP_BAND`?
   If yes, it is a configuration decision with a documented impact (candidate C).

## 9. Not done (deliberately)

No production integration, no new module, no test file, no migration, no configuration
change, no stored-row update, no severity reclassification, no server start.
