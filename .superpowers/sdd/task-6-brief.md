## Task 6: Test Chart Migration

**Files:**
- Test: Browser console

**Interfaces:**
- Consumes: All previous tasks
- Produces: Verified chart functionality

- [ ] **Step 1: Open browser and navigate to root cause tab**

Navigate to the root cause analysis tab in the application.

- [ ] **Step 2: Select a hospital and month**

Choose a hospital and month from the dropdowns to trigger chart loading.

- [ ] **Step 3: Verify chart renders**

Check that:
- Chart displays with two lines (teal for hospital, purple for peer)
- CI band renders as purple shaded area
- Legend shows both datasets
- Tooltips appear on hover

- [ ] **Step 4: Test interactive features**

Test:
- Legend toggle (click to hide/show datasets)
- Hover effects (points enlarge on hover)
- Responsive behavior (resize browser window)

- [ ] **Step 5: Check console for errors**

Open browser console and verify no JavaScript errors.

- [ ] **Step 6: Commit final changes**

```bash
git add -A
git commit -m "test: verify Chart.js migration works correctly"
```