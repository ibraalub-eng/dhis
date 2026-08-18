## Task 1: Set Up Chart.js Dependencies

**Files:**
- Modify: `static/tabs/root-cause.html`

**Interfaces:**
- Consumes: None
- Produces: Chart.js library available globally

- [ ] **Step 1: Locate current Plotly.js CDN link**

Open `static/tabs/root-cause.html` and find the Plotly.js CDN script tag. It should be in the head or before closing body tag.

- [ ] **Step 2: Replace Plotly.js with Chart.js CDN**

Replace the Plotly.js script tag with Chart.js CDN:

```html
<!-- Remove this line -->
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>

<!-- Add this line -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
```

- [ ] **Step 3: Verify Chart.js is loaded**

Add a temporary test in browser console:
```javascript
console.log('Chart.js version:', Chart.version);
```

Expected output: Chart.js version number (e.g., "4.4.0")

- [ ] **Step 4: Commit changes**

```bash
git add static/tabs/root-cause.html
git commit -m "chore: replace Plotly.js with Chart.js CDN"
```