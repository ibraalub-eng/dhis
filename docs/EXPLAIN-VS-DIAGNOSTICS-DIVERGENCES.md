# The 8 Explain ↔ Diagnostics divergences — read-only investigation (Step 6A)

Status: **investigation only. Nothing was changed, written or re-banded.** The
stored-band fingerprint is identical before and after the session
(`b011d3087075a8816a609b12bb56823af961461c`), no migration or back-fill was run,
and no threshold, cap, policy route or peer grouping was touched.

Scope: the eight cases previously reported as unexplained, where Quality Alert
per-perspective eligibility and Explain's Diagnostics row-level eligibility
disagree.

## 0. What the number 8 is made of

The two tables are folded by **identity** = `(hospital, month, canonical
formula)`, which is how Quality Alerts, the Dashboard and the consistency audit
already group them.

| Measure | Count |
|---|---|
| Shared identities carrying a top band on both sides | **396** |
| Identities whose band still differs after the shared policy | **7** |
| **Alert perspectives** claiming `VERY_HIGH` on such an identity | **8** |

The eight reported cases are the eight alert **perspectives**; they collapse to
seven identities because `h22 2026-07 2.l` stores *two* peer perspectives
(ownership **and** governorate), each of which holds the top band on its own.

This is not a recount of the earlier report: 10 identities were previously
listed, 3 of them (`h6 2026-06 10.i`, `h24 2026-07 sys_clinical_rate_hysterectomy`,
`h26 2026-08 10.a.3.3`) resolve to `HIGH / HIGH` once the approved caps are
applied on both sides, leaving the 7 identities / 8 perspectives below.

## 1. The 8 cases

Every case has the **same shape**: the alert's top band is held by a **peer**
perspective judged by Rule B, while the Diagnostics row's top band is held by its
**own-history** layer and is refused by the top-band gate.

| # | Identity (h / month / code) | Alert row | Perspective · method | Alert stored → shown | Rule B verdict | Diagnostics row | Row stored → shown | Row route · verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | h6 2026-07 `6.d` | #6348 | ownership · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — both scales support | #209819 | `VERY_HIGH` → `HIGH` | history · **ineligible**, `DISPERSION_BAND_BELOW_VERY_HIGH` |
| 2 | h21 2026-04 `8.b` | #4007 | governorate · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — both scales support | #206586 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 3 | h22 2026-07 `2.l` | #6243 | ownership · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — both scales support | #210024 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 4 | h22 2026-07 `2.l` | #6245 | governorate · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — both scales support | #210024 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 5 | h36 2026-06 `9` | #5679 | type · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — only usable scale (IQR) supports | #209556 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 6 | h36 2026-07 `13` | #6090 | type · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **undecided** — scales disagree (MAD supports, IQR refuses); band stands | #210610 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 7 | h36 2026-07 `2.i` | #6224 | type · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — only usable scale (IQR) supports | #210548 | `VERY_HIGH` → `HIGH` | history · **ineligible** |
| 8 | h36 2026-08 `6.d` | #878 | type · `peer_zscore` | `VERY_HIGH` → `VERY_HIGH` | **eligible** — both scales support | #211667 | `VERY_HIGH` → `HIGH` | history · **ineligible** |

`shown` is what the screen returns (`quality_alerts.effective_severity` /
`layered.row_level_assessment`), not the stored band. Every row still stores
`VERY_HIGH`; nothing was rewritten.

## 2. Per-case evidence

Common to all eight: the alert has **no own-history window** (`n = 0`) because a
peer perspective does not store one; the identity's separate `history`
perspective *does* store the same window as the Diagnostics row; the definition
tier is `catalog_only` on every peer row, so `group_comparability_status` is
`not_verified` on all of them.

### Case 1 — h6 2026-07 `6.d` (identity `c4d8db27`)

* **Alert #6348**, ownership peer, 7 peers stored; current 17.0; threshold 2.5.
  Peer group: median 2.0, MAD 2.0 (→ `VERY_HIGH`), IQR 3.5 (→ `VERY_HIGH`),
  zero-share 0.143. Verdict `eligible` (`BOTH_SCALES_SUPPORT`).
* **Row #209819**, `rolling_median_mad`; layer bands `{raw: VERY_HIGH,
  historical: VERY_HIGH, peer: LOW, rate: —, volume: —}`; holders
  `historical, raw`.
* History window n = 6, median 7.5, MAD 2.0, IQR 3.25, std 3.742; current 17.0 →
  dispersion band `LOW`, dispersion score 0.481, `would_be = HIGH`.
* Diagnostics peer layer: 13 stored peer values (median 24.0, MAD 6.0, IQR 13.0),
  peer score 0.267 → `LOW`. The row's peer layer does not hold the top band at
  all, so nothing on the Diagnostics side keeps this identity at `VERY_HIGH`.

### Case 2 — h21 2026-04 `8.b` (identity `27255318`)

* **Alert #4007**, governorate peer, **4 peers** (the minimum), zero-share 0.25;
  current 12.0; MAD 1.5 → `VERY_HIGH`, IQR 2.0 → `VERY_HIGH` → `eligible`.
* **Row #206586**, `rolling_median_mad`; holders `historical, raw`;
  history n = 3, median 5.0, MAD 1.0, IQR 5.5, std 6.083 → dispersion `NONE`,
  score 0.132 → `HIGH`.
* Diagnostics peer layer: 13 values, peer score 0.027 → `NONE`.

### Case 3 — h22 2026-07 `2.l` (identity `cd0afbc9`), ownership perspective

* **Alert #6243**, ownership peer, 6 peers, zero-share 0.5; current 13.0;
  MAD 0.5 → `VERY_HIGH`, IQR 1.75 → `VERY_HIGH` → `eligible`.
* **Row #210024**, history n = 6, median 2.0, MAD 1.0, IQR 6.75 → dispersion
  `NONE`, score 0.211 → `HIGH`.
* Diagnostics peer layer: 12 values, peer score 0.79 → `HIGH` (still not the top
  band).

### Case 4 — h22 2026-07 `2.l`, governorate perspective

Same identity and row; **alert #6245**, governorate peer, 4 peers, MAD 0.5 →
`VERY_HIGH`, IQR 1.5 → `VERY_HIGH` → `eligible`. This is the case that makes the
perspective count 8 while the identity count stays 7.

### Case 5 — h36 2026-06 `9` (identity `0217eba6`)

* **Alert #5679**, type peer, 4 peers, **zero-share 0.75** (3 of 4 peers are 0);
  MAD 0.0 → **not usable**, IQR 0.25 → `VERY_HIGH` → `eligible`
  (`ONLY_AVAILABLE_SCALE_SUPPORTS`).
* **Row #209556**, history n = 4, median 1.5, MAD 1.5, IQR 3.25 → dispersion
  `MODERATE`, score 0.606 → `HIGH`.
* Diagnostics peer layer: 12 values, peer score 0.874 → `HIGH`.

### Case 6 — h36 2026-07 `13` (identity `9abc15a5`)

* **Alert #6090**, type peer, 5 peers, current 344.0; MAD 27.0 → `VERY_HIGH`,
  IQR 67.0 → `MODERATE` → the two usable scales **disagree**, so Rule B returns
  `undecided` (`SCALES_DISAGREE`) and, by the approved policy, **the band stands**.
  This is the only case where the peer claim is not affirmed — it is merely not
  refused.
* **Row #210610**, `iqr`; history n = 6, median 86.5, MAD 37.0, IQR 56.25 →
  dispersion `MODERATE`, score 0.676 → `HIGH`.
* Diagnostics peer layer: 14 values, peer score 0.173 → `NONE`.

### Case 7 — h36 2026-07 `2.i` (identity `bd600f46`)

* **Alert #6224**, type peer, 5 peers, zero-share 0.0; MAD 0.0 → not usable,
  IQR 2.0 → `VERY_HIGH` → `eligible` (only available scale supports).
* **Row #210548**, history n = 6, median 8.5, MAD 1.0, IQR 1.75 → dispersion
  `LOW`, score 0.394 → `HIGH`.
* Diagnostics peer layer: 13 values, peer score 0.239 → `NONE`.

### Case 8 — h36 2026-08 `6.d` (identity `c4d8db27`)

* **Alert #878**, type peer, 6 peers, zero-share 0.0; MAD 0.5 → `VERY_HIGH`,
  IQR 0.75 → `VERY_HIGH` → `eligible`.
* **Row #211667**, history n = 7, median 5.0, MAD 1.0, IQR 3.5 → dispersion
  `MODERATE`, score 0.554 → `HIGH`.
* Diagnostics peer layer: 14 values, peer score 0.109 → `NONE`.

## 3. Do both paths use identical inputs?

No — and where they *do* use identical inputs, they agree.

| Input | Alert peer perspective | Diagnostics row | Identical? |
|---|---|---|---|
| Record | one row **per perspective** of the event | one row **per analysis pass** | **No** (different source records) |
| Peer group | the stratified group: type / ownership / governorate, **4–7 hospitals** | the detection baseline: **12–14 active hospitals** | **No** (different peer groups) |
| Peer values stored | yes (4–7 values) | yes (12–14 values) | — but different groups |
| Own-history window | not stored (`n = 0`) | stored, `n = 3–7` | n/a on the peer row |
| History window, alert's *history* perspective vs the row | `n = 3–7`, same values | same | **Yes** — verified case by case |
| Current value | same (`17.0`, `12.0`, `13.0`, `8.0`, `344.0`, `12.0`) | same | **Yes** |
| Threshold | 2.5 (stored `z_threshold`) | 2.5 (`row_gate_threshold`) | **Yes** |
| Method | `peer_zscore` (Rule B on MAD/IQR of the group) | `rolling_median_mad` / `iqr` (own window) | **No** — different question |
| Rule | Rule B (peer eligibility) | own-history top-band gate | **No** — different policy routes |

The decisive check: for **all 7 identities**, the alert's `history` perspective
and the Diagnostics row carry the **same window, same current value, and return
the same decision** (`ineligible`, `DISPERSION_BAND_BELOW_VERY_HIGH`, `HIGH`).
On every input the two paths actually share, they agree.

## 4. Classification

| Case | Primary | Secondary | Why |
|---|---|---|---|
| 1 | **E** different policy routes | C, A | peer claim judged by Rule B vs own-history gate; groups 7 vs 13 |
| 2 | **E** | C, A | 4-peer governorate group vs 13-hospital baseline |
| 3 | **E** | C, A | ownership group vs all-hospital baseline |
| 4 | **E** | C, A | same identity, second peer perspective |
| 5 | **E** | C, F | only usable scale supports; IQR 0.25 on a 75 %-zero group is thin evidence, and the group is not the row's |
| 6 | **E** | F, C | Rule B is *undecided* (scales disagree) yet the band stands — the weakest of the eight |
| 7 | **E** | C, F | MAD unusable, only IQR supports |
| 8 | **E** | C, A | type group vs all-hospital baseline |

Rejected classifications:

* **B — different input values.** The shared inputs (window, current value,
  threshold) are identical and produce identical decisions. Rejected.
* **D — different statistical methods.** Both sides use the same MAD/IQR
  machinery (`spread_used`, `score_from_mad`, `score_from_iqr`). The methods
  differ only because the *questions* differ, which is E, not D.
* **G — genuine implementation defect.** No case shows one computation producing
  two answers from the same evidence: `same_window = True`,
  `same_current = True`, `same_decision = True` in all 7 identities, and the
  earlier production-parity check found `0 of 1389` alerts and `0 of 517`
  Diagnostics rows where the screen disagrees with the routed rule. Rejected.
* **H — other.** Nothing is left over once A/C/E are named.

## 5. Intentional, or does it need correction?

**Intentional in all eight.** The divergence is the documented consequence of the
routing rule already approved and implemented: the history window judges history
claims, and a peer claim is judged by Rule B — it is *not* re-judged by the
history window, because a peer z already divides by the group's own spread and
asking it the history question would apply a different measurement. Diagnostics
holds one row per analysis and its peer layer does not reach the top band, so it
correctly shows `HIGH` for the history claim it does store; Quality Alerts holds
the peer perspective separately and refuses to erase a band the peer policy
allows.

No band, score, cap or stored row needs correction. Three things are worth a
decision, and none of them is a defect:

1. **The screens do not say this out loud.** Explain's cross-check does state the
   different source layer, but a reader comparing the two *screens* sees
   `VERY_HIGH` beside `HIGH` with no shared sentence explaining that the top band
   belongs to a peer perspective Diagnostics does not store. (Presentation gap.)
2. **Case 6 keeps a top band on an undecided peer verdict.** By policy
   `undecided` leaves the band alone; the effect is that the weakest peer claim
   in the set still reads `VERY_HIGH`.
3. **Cases 5 and 7 rest on a single usable scale**, one of them on a group that is
   75 % zeros (case 5). Rule B permits it (`ONLY_AVAILABLE_SCALE_SUPPORTS`), and
   the zero-share is display-only, but a reviewer may want that stated in the
   popup.

## 6. Proposed remediation (not implemented)

| # | Proposal | Type | Effect on data | Recommendation |
|---|---|---|---|---|
| R1 | Diagnostics' *Why* panel cross-references a peer perspective at the top band on the Quality Alerts side ("this screen does not store that comparison"), read-only lookup by identity | presentation | none | **Recommended** — closes the visible contradiction without moving a band |
| R2 | In the same block, print the peer group size and the Rule B state (`eligible` / `undecided`) beside the perspective name | presentation | none | Recommended with R1 |
| R3 | Record the `zero_share` advisory and "only one usable scale" in the popup text for Rules B rows | presentation | none | Optional; needs the 5C/5D wording rules to stay intact |
| R4 | Require **both** robust scales (or a minimum zero-share) before a peer claim may keep `VERY_HIGH`; `undecided` would then be presented at `HIGH` | **policy** | re-bands cases 5, 6, 7 and any other single-scale/undecided peer rows — needs an impact count first | Not recommended without a separate approval and a measured band delta |
| R5 | Persist peer perspectives as Diagnostics rows so both screens hold the same records | **schema / pipeline** | new rows per perspective, re-scan of affected months | Out of scope for this branch |
| R6 | Re-band the 146 Diagnostics / 163 alert rows the gate refuses | **data write** | permanent band change | Still deliberately excluded; unchanged by this investigation |

R1/R2 are display-only and are the smallest change that removes the reported
contradiction. R4 would be a policy change and must not be bundled with a
presentation fix.

## 7. How this was produced (read-only)

```bash
# aggregate consistency (per-row CSV + narrative)
.venv/Scripts/python.exe scripts/verify_very_high_consistency.py

# per-case evidence used by this document: an inline read-only session that
#  * loads the audit script's own view builders
#    (vc._alert_view / vc._layered_view) so no second copy of the policy exists,
#  * folds both sides by identity and keeps the identities whose production
#    band still differs,
#  * prints, per case, the alert perspective, its Rule B verdict (median, MAD,
#    IQR, usable scales, zero-share, peer count), and the Diagnostics row's
#    layer bands, holders, history window, peer group, scores and gate reason,
#  * re-reads the stored-band fingerprint at the end.
```

Verified invariants this session:

| Invariant | Result |
|---|---|
| stored-band fingerprint before / after | `b011d308…61c` / `b011d308…61c` — unchanged |
| rows written, migrations, back-fills | none |
| thresholds, caps, peer grouping, Rule B | untouched |
| Diagnostics / Explain code | untouched |
| uncommitted work | preserved (`git status` unchanged) |

Limitation: the per-case peer groups are read from what each side **stored**
(alert `evidence.comparison_policy.peer.values`, row `peer_provenance.values`).
Alert peer rows store member values for these eight, so Rule B could be re-run
exactly; the 1,130 peer alert rows that predate that block can only be judged on
their stored stats and peer count, which is the tolerance documented in
`docs/VERY-HIGH-ELIGIBILITY-CONSISTENCY.md` §6.
