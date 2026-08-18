## Task 7: Clean Up Plotly.js References

**Files:**
- Modify: `static/js/settings.js`

**Interfaces:**
- Consumes: Verified Chart.js implementation
- Produces: Clean codebase without Plotly.js references

- [ ] **Step 1: Search for Plotly.js references**

Search for any remaining Plotly.js references:
```bash
grep -r "Plotly" static/
grep -r "plotly" static/
```

- [ ] **Step 2: Remove any Plotly.js specific code**

Remove any remaining Plotly.js specific functions or variables.

- [ ] **Step 3: Verify no Plotly.js references remain**

```bash
grep -r "Plotly" static/
# Should return no results
```

- [ ] **Step 4: Commit cleanup**

```bash
git add static/js/settings.js
git commit -m "chore: remove Plotly.js references"
```