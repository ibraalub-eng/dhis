# Developer Hints Toggle — Design

## Goal
Add a toggle in Settings → Control to show/hide Source code references (file paths, line numbers, function names) below each System Settings control.

## Architecture
- **Storage**: `localStorage` (key: `dev_hints_enabled`, default: `"true"`)
- **Global state**: `window._showDevHints` (boolean)
- **CSS marker class**: `.dev-hint` on Source elements only
- **Scope**: Settings tab only — Calculation and Purpose text is always visible; Source references toggle

## Components

### 1. Checkbox (Control tab, after Structured Logging)
```
<div style="background:#fafafa;padding:0.8rem;border-radius:6px;max-width:700px;margin-top:0.8rem;">
  <label style="display:flex;align-items:flex-start;gap:0.6rem;cursor:pointer;">
    <input type="checkbox" id="cfg_dev_hints" onchange="toggleDevHints(this.checked)" style="margin-top:0.2rem;width:18px;height:18px;">
    <div>
      <strong>Show Developer Hints</strong><br>
      <span style="font-size:0.8rem;color:#666;">
        When enabled, displays source code file references and function names below each setting control.
        Disable before production deployment to hide internal implementation details.
      </span>
    </div>
  </label>
</div>
```

### 2. JS Functions (`settings.js`)

```javascript
// Initialize dev hints state
export function initDevHints() {
    const enabled = localStorage.getItem('dev_hints_enabled') !== 'false';
    window._showDevHints = enabled;
    const cb = document.getElementById('cfg_dev_hints');
    if (cb) cb.checked = enabled;
    applyDevHintsVisibility();
}

export function toggleDevHints(show) {
    window._showDevHints = show;
    localStorage.setItem('dev_hints_enabled', show ? 'true' : 'false');
    applyDevHintsVisibility();
}

function applyDevHintsVisibility() {
    document.querySelectorAll('.dev-hint').forEach(el => {
        el.style.display = window._showDevHints ? '' : 'none';
    });
}
```

### 3. Hint Content Enhancement

Each current hint (e.g. `rules.py:92 → _eq(). Max allowed difference...`) is split into:

**Always visible** (no class needed):
- **Calculation**: How the value is computed (formula/logic)
- **Purpose**: What the control/indicator represents

**Toggle via `.dev-hint`**:
- **Source**: File path, line number, and function name

Example transformation:

**Before:**
```html
<div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
    rules.py:92 → _eq(). Max allowed difference for "equal" check. 187 vs 186.99 passes at 0.01.
</div>
```

**After:**
```html
<div style="font-size:0.75rem;color:#666;margin-top:0.3rem;padding-left:185px;">
    <strong>Calculation:</strong> |a - b| ≤ tolerance → PASS. 187 vs 186.99 passes at 0.01.<br>
    <strong>Purpose:</strong> Controls precision of equality comparison between reported and expected values.<br>
    <span class="dev-hint"><strong>Source:</strong> <code>app/engine/quality/rules.py:92</code> → <code>_eq()</code></span>
</div>
```

### 4. Settings sections affected

All 10 settings sections with `file.py` references:
| Section | File referenced | Change |
|---------|----------------|--------|
| Quality Score | `quality_score.py` | Wrap Source refs in `.dev-hint` |
| Confidence Score | `confidence.py` | Wrap Source refs in `.dev-hint` |
| Thresholds | `config.py`, `anomaly.py`, `trends.py`, `confidence.py` | Wrap Source refs in `.dev-hint` |
| Rules | `rules.py` | Wrap Source refs in `.dev-hint`, add Calculation/Purpose text |
| Clinical | `clinical_thresholds.py` | Wrap Source refs in `.dev-hint` |
| Risk Profile | `clinical_risk.py` | Wrap Source refs in `.dev-hint` |
| Trends | `trends.py` | Wrap Source refs in `.dev-hint`, add Calculation/Purpose text |
| Rate Benchmarks | `anomaly.py` | Wrap Source refs in `.dev-hint` |

### 5. Hook points

- `loadControlSettings()` calls `initDevHints()`  
- `showSettingsTab('control')` calls `initDevHints()`  
- `loadAllSettings()` calls `initDevHints()`  

## Files modified
- `static/tabs/settings.html` — checkbox + expanded hints
- `static/js/settings.js` — `initDevHints()`, `toggleDevHints()`, `applyDevHintsVisibility()`

## Out of scope
- Hints outside Settings page (Dashboard KPIs, Charts, etc.)
- Backend API changes
- Multi-user sync of toggle state
