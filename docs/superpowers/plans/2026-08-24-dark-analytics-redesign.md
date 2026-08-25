# Dark Analytics Redesign Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the HEALTH-ai dashboard from a light Material-Indigo theme to a dark analytics theme inspired by Bloomberg/Grafana, with CSS custom properties, unified color system, and dark surfaces optimized for data-heavy usage.

**Architecture:** Introduce a `:root` design token system in `styles.css`, replace all hardcoded colors with semantic tokens, and apply a dark palette across all 13 tabs, login page, modals, charts, and inline styles. No framework changes — pure CSS + JS color updates.

**Tech Stack:** CSS custom properties, Chart.js (dark backgrounds), Plotly (dark layouts), vanilla JS i18n

---

## Design Token System

### Color Palette (Dark Analytics)

| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0F1117` | Page background |
| `--bg-surface` | `#1A1D27` | Cards, panels |
| `--bg-surface-hover` | `#222632` | Card hover |
| `--bg-elevated` | `#252A36` | Modals, dropdowns |
| `--bg-input` | `#161921` | Input fields, selects |
| `--border-default` | `#2A2E3B` | Card borders, dividers |
| `--border-focus` | `#4F8CFF` | Focus rings |
| `--text-primary` | `#E8EAED` | Headings, primary text |
| `--text-secondary` | `#9AA0AC` | Labels, descriptions |
| `--text-muted` | `#5C6370` | Placeholders, disabled |
| `--accent-blue` | `#4F8CFF` | Primary actions, links |
| `--accent-teal` | `#2DD4BF` | Hospital values, positive |
| `--accent-purple` | `#A78BFA` | Peer averages, secondary data |
| `--accent-orange` | `#FB923C` | Warning states |
| `--accent-red` | `#F87171` | Critical, errors |
| `--accent-green` | `#4ADE80` | Success, normal |
| `--accent-yellow` | `#FACC15` | Attention |
| `--accent-pink` | `#F472B6` | Clusters, accent |
| `--shadow-sm` | `0 1px 3px rgba(0,0,0,0.4)` | Subtle elevation |
| `--shadow-md` | `0 4px 12px rgba(0,0,0,0.5)` | Card hover |
| `--shadow-lg` | `0 8px 24px rgba(0,0,0,0.6)` | Modals |
| `--glow-blue` | `0 0 16px rgba(79,140,255,0.15)` | Accent glow on hover |
| `--header-gradient` | `linear-gradient(135deg, #0D0F18, #1A1D27)` | Header |
| `--page-gradient` | `#0F1117` | Page background (solid for perf) |

### Typography

| Role | Value |
|---|---|
| Display | `Space Grotesk`, sans-serif (headings) |
| Body | `Inter`, -apple-system, sans-serif (text, labels) |
| Mono | `JetBrains Mono`, Consolas, monospace (data values) |
| Arabic | `IBM Plex Sans Arabic`, Tahoma, sans-serif |

### Severity Colors (Dark-optimized)

| Level | Text | Background | Border |
|---|---|---|---|
| Critical | `#F87171` | `rgba(248,113,113,0.12)` | `rgba(248,113,113,0.3)` |
| Warning | `#FB923C` | `rgba(251,146,60,0.12)` | `rgba(251,146,60,0.3)` |
| Success | `#4ADE80` | `rgba(74,222,128,0.12)` | `rgba(74,222,128,0.3)` |
| Info | `#4F8CFF` | `rgba(79,140,255,0.12)` | `rgba(79,140,255,0.3)` |

### Chart Palette (unified)

```
CHART_COLORS = {
  primary:    '#2DD4BF',   // Teal — hospital values
  secondary:  '#A78BFA',   // Purple — peer average
  accent:     '#F87171',   // Red — critical
  warning:    '#FB923C',   // Orange — high/medium
  success:    '#4ADE80',   // Green — good
  neutral:    '#9AA0AC',   // Gray — text/borders
  background: '#1A1D27',
  grid:       '#2A2E3B',
  ciBand:     'rgba(167,139,250,0.12)',
  clusters:   ['#4F8CFF','#A78BFA','#F472B6','#2DD4BF','#FB923C','#06B6D4','#84CC16']
}
```

---

## File Structure

| File | Responsibility |
|---|---|
| `static/css/styles.css` | Design tokens (`:root`), base dark theme, component styles |
| `static/index.html` | Login page inline colors, tab labels, header, modals |
| `static/tabs/*.html` | All tab-specific inline styles (13 files) |
| `static/js/chart-utils.js` | Unified `CHART_COLORS` object |
| `static/js/smart/core.js` | `SMART_COLORS` aligned to chart palette |
| `static/js/smart/advanced.js` | Plotly layout colors (grid, paper, etc.) |
| `static/js/smart/report.js` | Verdict/priority color maps |
| `static/js/smart/hospital.js` | Severity color ternaries |
| `static/js/smart/geo-regional.js` | Severity color ternaries |
| `static/js/smart/decision-board.js` | KPI card colors |
| `static/js/validation.js` | Validation badge colors (heaviest JS) |
| `static/js/settings.js` | Settings page color refs (second heaviest) |
| `static/js/audit.js` | Audit report color maps |
| `static/js/clinical.js` | Clinical status colors |
| `static/js/admin.js` | Admin panel inline styles |
| `static/js/auth.js` | Session warning toast colors |
| `static/js/hospitals.js` | Hospital table colors |
| `static/js/upload.js` | Upload step indicator colors |
| `static/js/outliers.js` | Outlier badge colors |
| `static/js/alerts.js` | Alert toast colors |

---

## Tasks

### Task 1: Create Design Token System in styles.css

**Files:**
- Modify: `static/css/styles.css:1-10` (add `:root` block at top)

**What:** Add a comprehensive `:root` block with all CSS custom properties defined above. This is the foundation — every subsequent task references these tokens.

- [ ] **Step 1: Add `:root` design tokens block**

Insert at the very top of `static/css/styles.css`, before the existing `body` rule:

```css
/* ── Design Tokens (Dark Analytics) ────────────────────── */
:root {
  /* Surfaces */
  --bg-base: #0F1117;
  --bg-surface: #1A1D27;
  --bg-surface-hover: #222632;
  --bg-elevated: #252A36;
  --bg-input: #161921;

  /* Borders */
  --border-default: #2A2E3B;
  --border-focus: #4F8CFF;

  /* Text */
  --text-primary: #E8EAED;
  --text-secondary: #9AA0AC;
  --text-muted: #5C6370;

  /* Accent palette */
  --accent-blue: #4F8CFF;
  --accent-teal: #2DD4BF;
  --accent-purple: #A78BFA;
  --accent-orange: #FB923C;
  --accent-red: #F87171;
  --accent-green: #4ADE80;
  --accent-yellow: #FACC15;
  --accent-pink: #F472B6;

  /* Severity */
  --severity-critical-text: #F87171;
  --severity-critical-bg: rgba(248,113,113,0.12);
  --severity-critical-border: rgba(248,113,113,0.3);
  --severity-warning-text: #FB923C;
  --severity-warning-bg: rgba(251,146,60,0.12);
  --severity-warning-border: rgba(251,146,60,0.3);
  --severity-success-text: #4ADE80;
  --severity-success-bg: rgba(74,222,128,0.12);
  --severity-success-border: rgba(74,222,128,0.3);
  --severity-info-text: #4F8CFF;
  --severity-info-bg: rgba(79,140,255,0.12);
  --severity-info-border: rgba(79,140,255,0.3);

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.5);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.6);
  --glow-blue: 0 0 16px rgba(79,140,255,0.15);

  /* Gradients */
  --header-gradient: linear-gradient(135deg, #0D0F18, #1A1D27);
  --page-bg: #0F1117;

  /* Chart */
  --chart-primary: #2DD4BF;
  --chart-secondary: #A78BFA;
  --chart-grid: #2A2E3B;
}
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/test_auth.py -q --tb=short`
Expected: 34 passed

- [ ] **Step 3: Commit**

```bash
git add static/css/styles.css
git commit -m "feat(dark-theme): add CSS custom property design tokens
Token system for dark analytics redesign: surfaces, borders, text,
accent palette, severity colors, shadows, gradients, and chart tokens."
```

---

### Task 2: Update styles.css Base Rules

**Files:**
- Modify: `static/css/styles.css:1-100` (body, header, cards, inputs, scrollbars)

**What:** Replace all hardcoded colors in the existing CSS rules with the new design tokens. This covers the structural foundation: body background, header, cards, inputs, scrollbar, focus rings, and loader overlay.

- [ ] **Step 1: Update body and html base styles**

Replace existing body rule with:

```css
html {
  background: var(--page-bg);
}
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--page-bg);
  color: var(--text-primary);
  margin: 0;
  padding: 0;
  min-height: 100vh;
}
body.rtl {
  font-family: 'IBM Plex Sans Arabic', 'Segoe UI', 'Arabic Typesetting', 'Traditional Arabic', Tahoma, sans-serif;
}
```

- [ ] **Step 2: Update header styles**

Replace header background with `var(--header-gradient)`, text colors with `var(--text-primary)`.

- [ ] **Step 3: Update card styles**

Replace `.card` background with `var(--bg-surface)`, border with `1px solid var(--border-default)`, box-shadow with `var(--shadow-sm)`, and hover with `var(--bg-surface-hover)` + `var(--shadow-md)`.

- [ ] **Step 4: Update input/select styles**

Replace input backgrounds with `var(--bg-input)`, border with `var(--border-default)`, text color with `var(--text-primary)`, focus border with `var(--border-focus)`.

- [ ] **Step 5: Update scrollbar styles**

Replace scrollbar thumb with `var(--border-default)`, thumb:hover with `var(--text-muted)`.

- [ ] **Step 6: Update loader overlay**

Replace `rgba(255,255,255,0.85)` with `rgba(15,17,23,0.85)` (dark overlay), spinner color with `var(--accent-blue)`.

- [ ] **Step 7: Update modal styles**

Replace `.modal-content` background with `var(--bg-elevated)`, border with `var(--border-default)`, text with `var(--text-primary)`.

- [ ] **Step 8: Update tab bar styles**

Replace active tab indicator with `var(--accent-blue)`, tab text with `var(--text-secondary)`, active text with `var(--text-primary)`.

- [ ] **Step 9: Update severity/status badge styles**

Replace all hardcoded severity colors (`.status-critical`, `.status-warning`, `.status-good`, etc.) with the `--severity-*` tokens.

- [ ] **Step 10: Run full test suite**

Run: `python -m pytest tests/test_auth.py -q --tb=short`
Expected: 34 passed

- [ ] **Step 11: Commit**

```bash
git add static/css/styles.css
git commit -m "feat(dark-theme): migrate styles.css base rules to dark tokens
Body, header, cards, inputs, modals, tabs, scrollbar, loader overlay,
and severity badges all use CSS custom properties."
```

---

### Task 3: Update index.html Login Page and Header

**Files:**
- Modify: `static/index.html:1-60` (login page inline styles)
- Modify: `static/index.html:61-120` (header, tab bar)

**What:** Replace all hardcoded inline colors in the login page and header with CSS custom properties. The login page has ~20 inline color values, the header has ~10.

- [ ] **Step 1: Update login page background**

Replace `linear-gradient(135deg,#f8fafc,#eef2ff)` with `var(--page-bg)`.

- [ ] **Step 2: Update login card styles**

Replace login card background with `var(--bg-surface)`, border with `var(--border-default)`, text colors with tokens.

- [ ] **Step 3: Update login form elements**

Replace input border, label colors, button gradient with tokens. Button gradient: `linear-gradient(135deg, var(--accent-blue), var(--accent-purple))`.

- [ ] **Step 4: Update header inline styles**

Replace header gradient, text colors, button colors with tokens.

- [ ] **Step 5: Update tab bar inline styles**

Replace tab accent colors (#1565c0 etc.) with `var(--accent-blue)`.

- [ ] **Step 6: Commit**

```bash
git add static/index.html
git commit -m "feat(dark-theme): migrate login page and header to dark tokens"
```

---

### Task 4: Update Tab HTML Inline Styles

**Files:**
- Modify: `static/tabs/settings.html` (656 inline styles — highest effort)
- Modify: `static/tabs/smart-analytics.html` (82 inline styles)
- Modify: `static/tabs/root-cause.html` (78 inline styles)
- Modify: `static/tabs/hospitals.html` (77 inline styles)
- Modify: `static/tabs/analysis.html` (35 inline styles)
- Modify: `static/tabs/rules-manager.html` (31 inline styles)
- Modify: `static/tabs/alerts.html` (27 inline styles)
- Modify: `static/tabs/clinical.html` (22 inline styles)
- Modify: `static/tabs/indicator-tree.html` (22 inline styles)
- Modify: `static/tabs/outliers.html` (19 inline styles)
- Modify: `static/tabs/quality.html` (14 inline styles)
- Modify: `static/tabs/audit.html` (11 inline styles)
- Modify: `static/tabs/dashboard.html` (9 inline styles)

**What:** Systematically replace all hardcoded hex colors and rgba values in inline styles with CSS custom property references. Work from lightest files to heaviest.

**Batch 1 — Light files (Tasks 4a):**

- [ ] **Step 1: Update dashboard.html, audit.html, quality.html, outliers.html**

Replace hardcoded colors with `var(--text-primary)`, `var(--text-secondary)`, `var(--accent-red)`, `var(--bg-surface)`, etc.

- [ ] **Step 2: Update alerts.html, indicator-tree.html, clinical.html**

Same pattern.

- [ ] **Step 3: Update rules-manager.html, analysis.html**

Same pattern.

- [ ] **Step 4: Commit batch 1**

```bash
git add static/tabs/dashboard.html static/tabs/audit.html static/tabs/quality.html static/tabs/outliers.html static/tabs/alerts.html static/tabs/indicator-tree.html static/tabs/clinical.html static/tabs/rules-manager.html static/tabs/analysis.html
git commit -m "feat(dark-theme): migrate light tab inline styles to dark tokens"
```

**Batch 2 — Heavy files (Tasks 4b):**

- [ ] **Step 5: Update hospitals.html (77 inline styles)**

Focus on table styling, badge colors, borders.

- [ ] **Step 6: Update root-cause.html (78 inline styles)**

Heavy teal/purple sub-theme — replace all hardcoded teal/purple values with accent tokens.

- [ ] **Step 7: Update smart-analytics.html (82 inline styles)**

Context bar, selects, KPI cards, modal header. Also update the embedded `<style>` block colors.

- [ ] **Step 8: Commit batch 2**

```bash
git add static/tabs/hospitals.html static/tabs/root-cause.html static/tabs/smart-analytics.html
git commit -m "feat(dark-theme): migrate heavy tab inline styles to dark tokens"
```

**Batch 3 — Settings (Tasks 4c):**

- [ ] **Step 9: Update settings.html (656 inline styles)**

The most complex file. Replace systematically by section:
1. Header/title colors → `var(--text-primary)`
2. Section backgrounds → `var(--bg-surface)`
3. Input fields → `var(--bg-input)`, `var(--border-default)`
4. Labels → `var(--text-secondary)`
5. Status badges → `--severity-*` tokens
6. Divider colors → `var(--border-default)`
7. Button colors → `var(--accent-blue)`, `var(--accent-red)`

- [ ] **Step 10: Commit batch 3**

```bash
git add static/tabs/settings.html
git commit -m "feat(dark-theme): migrate settings.html to dark tokens (656 inline styles)"
```

---

### Task 5: Update JavaScript Color Constants

**Files:**
- Modify: `static/js/chart-utils.js` (CHART_COLORS)
- Modify: `static/js/smart/core.js` (SMART_COLORS)
- Modify: `static/js/smart/advanced.js` (Plotly layout colors)
- Modify: `static/js/smart/report.js` (verdict/priority colors)
- Modify: `static/js/smart/hospital.js` (severity ternaries)
- Modify: `static/js/smart/geo-regional.js` (severity ternaries)
- Modify: `static/js/smart/decision-board.js` (KPI colors)

**What:** Unify all JS color constants to use the new dark chart palette. Replace hardcoded severity ternaries with a shared utility.

- [ ] **Step 1: Update CHART_COLORS in chart-utils.js**

Replace the existing palette with the unified dark chart palette. Update `ciBandPlugin` fillStyle.

- [ ] **Step 2: Update SMART_COLORS in smart/core.js**

Align to the same palette. Remove duplicate cluster colors.

- [ ] **Step 3: Add shared severityColor utility**

Create a shared function (in `smart/core.js` or a new `theme.js`) that maps severity strings to dark-theme colors. Replace all duplicated ternaries across files.

- [ ] **Step 4: Update Plotly layout in advanced.js**

Replace `gridcolor:'#f0f0f0'` with `var(--chart-grid)` equivalent (`'#2A2E3B'`), paper_bgcolor to `'#1A1D27'`, plot_bgcolor to `'#161921'`, font color to `'#9AA0AC'`, marker line colors from `'#fff'` to `'#1A1D27'`.

- [ ] **Step 5: Update report.js verdict/priority color maps**

Replace hardcoded color maps with references to shared palette.

- [ ] **Step 6: Update hospital.js and geo-regional.js severity ternaries**

Replace inline ternary color maps with shared `severityColor()` calls.

- [ ] **Step 7: Update decision-board.js KPI colors**

Replace hardcoded KPI card border/value colors.

- [ ] **Step 8: Commit**

```bash
git add static/js/chart-utils.js static/js/smart/core.js static/js/smart/advanced.js static/js/smart/report.js static/js/smart/hospital.js static/js/smart/geo-regional.js static/js/smart/decision-board.js
git commit -m "feat(dark-theme): unify JS color constants to dark palette
Chart colors, severity ternaries, Plotly layouts, and verdict maps
all aligned to the dark analytics design tokens."
```

---

### Task 6: Update Remaining JS Files

**Files:**
- Modify: `static/js/validation.js` (72 color refs)
- Modify: `static/js/settings.js` (173 color refs)
- Modify: `static/js/audit.js` (54 color refs)
- Modify: `static/js/clinical.js` (48 color refs)
- Modify: `static/js/admin.js` (47 color refs)
- Modify: `static/js/hospitals.js` (35 color refs)
- Modify: `static/js/upload.js` (27 color refs)
- Modify: `static/js/outliers.js` (17 color refs)
- Modify: `static/js/alerts.js` (14 color refs)
- Modify: `static/js/auth.js` (5 color refs)

**What:** Update all remaining JS files that contain hardcoded colors.

- [ ] **Step 1: Update validation.js**

Heaviest JS file. Replace hex-alpha variants (`#c6282888` etc.) with `rgba()` equivalents using dark palette colors.

- [ ] **Step 2: Update settings.js**

Second heaviest. Replace teal/purple palette with dark tokens. Replace `font-family:Consolas` with `var(--font-mono)` equivalent.

- [ ] **Step 3: Update audit.js**

Replace `riskColor()` map and quality-score threshold colors. Update generated report HTML templates.

- [ ] **Step 4: Update clinical.js**

Replace clinical status colors and signal indicators.

- [ ] **Step 5: Update admin.js**

Replace inline `style.background='#f5f5f5'` and all hardcoded admin panel colors.

- [ ] **Step 6: Update hospitals.js, upload.js, outliers.js, alerts.js**

Moderate changes — replace badge/status colors.

- [ ] **Step 7: Update auth.js**

Replace session warning toast colors: `#fff3cd` → `var(--severity-warning-bg)`, `#ffc107` → `var(--accent-yellow)`, `#856404` → `var(--text-primary)`.

- [ ] **Step 8: Commit**

```bash
git add static/js/validation.js static/js/settings.js static/js/audit.js static/js/clinical.js static/js/admin.js static/js/hospitals.js static/js/upload.js static/js/outliers.js static/js/alerts.js static/js/auth.js
git commit -m "feat(dark-theme): migrate remaining JS files to dark palette"
```

---

### Task 7: Verify and Final Cleanup

**Files:**
- All files from Tasks 1-6

**What:** Final verification pass.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All tests pass (830+)

- [ ] **Step 2: Search for any remaining hardcoded light-theme colors**

Run: `rg '#f[0-9a-f]{5}' static/ --include='*.html' --include='*.css' --include='*.js' -g '!vendor'`
Any remaining white/light background colors (`#fff`, `#fafafa`, `#f8f9fb`, etc.) should be replaced.

- [ ] **Step 3: Verify no CSS conflicts**

Check that no two CSS rules override each other's token-based values.

- [ ] **Step 4: Commit final cleanup**

```bash
git add -A
git commit -m "feat(dark-theme): final cleanup — no remaining light-theme colors"
```

---

## Execution Order

```
Task 1 (tokens) → Task 2 (base CSS) → Task 3 (login/header)
  → Task 4a (light tabs) → Task 4b (heavy tabs) → Task 4c (settings)
  → Task 5 (JS constants) → Task 6 (remaining JS)
  → Task 7 (verify)
```

Each task is independently testable: after Task 2, the structural layout is dark; after Task 4, all tabs are dark; after Tasks 5-6, all dynamic content (charts, badges, generated reports) is dark.

## Dark Mode Blockers to Watch

- `rgba(255,255,255,0.85)` loader overlay → must become dark
- Plotly `gridcolor:'#f0f0f0'` and `marker.line.color:'#fff'` → dark equivalents
- `background:white` on all selects/inputs → `var(--bg-input)`
- `.trend-up`/`.trend-down` duplicate definitions (L114-116 vs L370-372) → resolve to single dark-compatible definition
- Alpha-hex colors (`#c6282888`) in validation.js → convert to `rgba()`
