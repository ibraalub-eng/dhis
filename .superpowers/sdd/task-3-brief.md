## Task 3: Update Timeline Chart Container

**Files:**
- Modify: `static/tabs/root-cause.html`

**Interfaces:**
- Consumes: None
- Produces: Updated chart container with proper styling

- [ ] **Step 1: Locate timeline chart container**

Find the timeline chart section in `static/tabs/root-cause.html`:

```html
<div id="rcTimelineChart" style="width:100%;height:320px;"></div>
```

- [ ] **Step 2: Add canvas element for Chart.js**

Replace the div with a canvas element:

```html
<!-- Replace this line -->
<div id="rcTimelineChart" style="width:100%;height:320px;"></div>

<!-- With this canvas element -->
<canvas id="rcTimelineChart" style="width:100%;height:320px;"></canvas>
```

- [ ] **Step 3: Verify container exists**

Add temporary console.log to verify:
```javascript
console.log('Chart canvas:', document.getElementById('rcTimelineChart'));
```

- [ ] **Step 4: Commit changes**

```bash
git add static/tabs/root-cause.html
git commit -m "fix: update timeline chart container to use canvas element"
```