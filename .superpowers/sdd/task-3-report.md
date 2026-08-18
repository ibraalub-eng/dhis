## Task 3: Update Timeline Chart Container

**Status:** DONE

### What I Implemented

Replaced the `<div>` timeline chart container with a `<canvas>` element in `static/tabs/root-cause.html`:

- **Before:** `<div id="rcTimelineChart" style="width:100%;height:320px;"></div>`
- **After:** `<canvas id="rcTimelineChart" style="width:100%;height:320px;"></canvas>`

This change is necessary for Chart.js compatibility — Chart.js requires a `<canvas>` element to render charts, whereas Plotly.js used a `<div>`.

### What I Tested

- Ran the full `test_root_cause_improvements.py` and `test_root_cause.py` suites (72 tests total) — all passing
- The `test_frontend_renders_advanced_sections` test specifically validates the HTML structure and passes
- No tests directly assert the element type (div vs canvas), but the element ID `rcTimelineChart` is preserved, maintaining compatibility with all JavaScript references in `static/js/settings.js`

### Test Results

72/72 passing, output pristine (only standard deprecation warnings from upstream dependencies)

### Files Changed

- `static/tabs/root-cause.html` — Changed line 121: `<div>` → `<canvas>` for the `rcTimelineChart` element

### Self-Review

- **Completeness:** The single required change (div → canvas) is implemented. The `id="rcTimelineChart"` is preserved so all JS references (`getElementById('rcTimelineChart')`) continue to work.
- **Quality:** Minimal change, clean and focused.
- **Discipline:** No over-engineering — this is a single-element swap as specified.

### Commit

- `1a52c1f` — `fix: update timeline chart container to use canvas element`
