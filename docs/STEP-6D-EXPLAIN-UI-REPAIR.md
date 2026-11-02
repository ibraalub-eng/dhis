# Step 6D — Explain UI repair (presentation and localization only)

Scope: the five Explain defects found in Step 6C — cross-check wrapping, raw machine
identifiers, incomplete Arabic localization, the duplicated cross-check explanation, and the
list-versus-cards confusion. Only presentation code and its tests changed; no analytical
engine, eligibility policy, severity calculation, stored evidence or database row was touched.

## 1. Changed files

| File | Change |
|---|---|
| `static/js/explain.js` | `_kvRows` reflow; new `_codeLabel`, `_humanizeCodes`, `_alreadyShown`; localized labels at each identifier site; duplication guard; scope sentence; detection-layer row reflow |
| `static/js/i18n.js` | Arabic dictionary block for bands, agreement/reason codes, comparability/definition statuses, layer names, route and cap policies, cross-check policy, scope sentence, distinction sentence |
| `tests/test_explain_top_band.py` | Expectations follow the presentation labels (`Very high`, `not verified`, `catalog only`); `_run_note` also loads `_codeLabel`; h22 test asserts three perspectives plus the scope sentence |
| `tests/test_explain_ui_6d.py` | New — 18 tests: wrapping (A), localization (B), duplication (C), perspective scope (D), prose humanization (E) |

No file under `app/`, `alembic/` or `scripts/` changed; no migration, backfill or data write.

## 2. Issues repaired

1. **Cross-check wrapping.** The value span no longer carries `flex-shrink: 0`; both columns
   are `min-width: 0` with `overflow-wrap: anywhere`, the label is `flex: 0 1 auto`, and the
   value is `text-align: end; unicode-bidi: plaintext; max-width: 70%`. No truncation,
   clipping or ellipsis is used anywhere. The same defect existed one block lower in
   **Detection layers** (`flex-shrink: 0; white-space: nowrap`), which squeezed layer names to
   one character per line at 390 px; those rows now wrap and drop the value below the label
   when the two cannot share a line.
2. **Raw identifiers.** One `_codeLabel(code)` maps a code to a localized label when the
   dictionary has one, otherwise makes the code readable (`not_verified` → "not verified",
   `VERY_HIGH` → "Very high"), and never invents a meaning. Applied to comparability,
   definition tier, both scale bands, reason, stored severity, closed status, agreement,
   layer level, outlier level and cross-check severity. `_humanizeCodes()` additionally
   rewrites codes embedded in backend prose (`HISTORICAL_ANOMALY (VERY_HIGH level)` →
   "Historical anomaly (Very high level)", `statistical_only` → "statistical only") on the
   rendered string only; the payload, API field names and enum values are unchanged.
3. **Arabic localization.** Dictionary entries were added for every reason code, band, status,
   layer name and policy sentence shown in Explain; RTL layout was verified with mixed
   Arabic and English numerals.
4. **Duplicated cross-check explanation.** The backend folds `cc.explanation` into `why` for
   the two "differs" agreements, so `_alreadyShown()` suppresses the second copy; unique
   information and the Diagnostics-versus-Quality-Alerts distinction remain.
5. **List versus cards.** The scope sentence is rendered once under the peer block in both
   languages — EN: "Only qualifying top-band peer perspectives are shown as cards. Other
   perspectives may appear in the cross-check list." AR: "تُعرض كبطاقات فقط المنظورات النظيرة
   التي تستوفي شروط مستوى الخطورة الأعلى. وقد تظهر منظورات أخرى في قائمة المقارنة." Case
   h22 / 2026-07 / 2.l still lists three perspectives in the cross-check list and renders
   exactly two cards, none for the stored HIGH type.

## 3. Screenshots

Step 6C "before" evidence: `screenshots/step6c/`. After (final build):

- `screenshots/step6d/10-h22-2l-en-desktop.png` — EN desktop
- `screenshots/step6d/08-h22-2l-en-mobile-layers.png` — EN mobile, detection layers wrapping
- `screenshots/step6d/09-h22-2l-ar-mobile.png` — AR mobile, RTL

## 4. Desktop and mobile verification

Measured in the browser rather than inferred from a screenshot:

- 1280×1000 CSS — `scrollWidth − clientWidth = 0`, popup inside the viewport, no element
  extending past the box, no element with clipped overflow.
- 970 CSS — same; box runs 96→856, nothing clipped or outside.
- 390×844 CSS — overflow 0, box 347 px, 0 elements outside; layer label column 315 px with
  the value wrapped onto the following line (previously a 36 px label beside a 266 px
  nowrap value).

## 5. Arabic and English verification

- **EN** — zero raw codes in rendered text (`VERY_HIGH`, `MODERATE`, `not_verified`,
  `catalog_only`, `SCALES_DISAGREE`, `BOTH_SCALES_SUPPORT`, `HISTORICAL_ANOMALY` all absent),
  two cards, scope sentence present.
- **AR** — `dir=rtl`, right-aligned, overflow 0, 0 elements outside the box, 1 839 Arabic
  characters rendered, zero raw codes, Arabic scope sentence present, Arabic band, reason and
  status labels in cards and cross-check rows.

## 6. Tests

- `test_explain_ui_6d.py`, `test_explain_top_band.py`, `test_layered_ui.py`,
  `test_quality_alerts_ui.py`, `test_ui_explain_digest.py`, `test_quality_alerts_api.py`
  → **199 passed**.
- `test_explain.py`, `test_explain_comparative.py`, `test_explain_covered_missing.py`,
  `test_explain_trail.py`, `test_explain_anomaly_reproduce.py`,
  `test_insufficient_history_policy.py` plus the two Explain files above
  → **165 passed, 1 skipped**.
- `node --check` on both JavaScript files: OK.
- `ruff check` on both touched test files: All checks passed (no suppression added).

## 7. Fingerprint

`b011d3087075a8816a609b12bb56823af961461c` — unchanged, re-read after the last edit.

## 8. Database writes

Zero. No `app/`, `alembic/` or `scripts/` change and no `.db` / `.sqlite` file modified: all
rendering evidence came from the isolated pytest database. `git status --porcelain` shows the
pre-existing entries plus the one new test file; the temporary harness and probe files were
deleted.

## 9. Analytical behaviour

Unchanged: no eligibility, Rule B, severity, score, threshold, cap, peer-grouping or
`systemControl` code was touched, and the API payloads were read-only inputs to the renderer.

## Limitations

- The authenticated app at `127.0.0.1:9090` requires a login that was not available, so the
  pictures come from a harness that runs the real `_renderPayload` and helpers over real API
  payloads from the test database, not from the signed-in app.
- Desktop captures are cropped by the browser pane (wider than the capture surface); the
  desktop proof is therefore the measured overflow figures above together with the mobile
  captures.
- Backend-composed prose (`p.what`, `p.why`, `cc.explanation`, layer details) is still English
  in Arabic mode, because translating it would require editing `app/engine/audit/explain.py`,
  outside this step's authorization. Codes embedded in that prose are humanized, not
  translated.
