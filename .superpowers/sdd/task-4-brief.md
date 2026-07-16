### Task 4: Frontend — Add CSS for new components

**Files:**
- Modify: `static/css/styles.css` (append at end)

- [ ] Step 1: Append these CSS rules to the end of `static/css/styles.css`:

```css
.ranking-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
}
.ranking-table th {
    padding: 0.5rem 0.4rem;
    text-align: left;
    font-weight: 600;
    color: #555;
    border-bottom: 2px solid #e0e0e0;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
}
.ranking-table th:hover { color: #1a237e; }
.ranking-table th.sort-asc::after { content: ' \25B2'; opacity: 1; }
.ranking-table th.sort-desc::after { content: ' \25BC'; opacity: 1; }
.ranking-table td {
    padding: 0.5rem 0.4rem;
    border-bottom: 1px solid #f0f0f0;
    white-space: nowrap;
}
.ranking-table tr:hover { background: #f5f5ff; }
.ranking-table tr { cursor: pointer; }
.ranking-table .row-a { background: #e8f5e9; }
.ranking-table .row-b { background: #fff8e1; }
.ranking-table .row-c { background: #fff3e0; }
.ranking-table .row-d { background: #ffebee; }
.summary-card { position: relative; }
.sparkline {
    width: 100%;
    height: 24px;
    margin-top: 4px;
    display: block;
}
.trend-up { color: #2e7d32; }
.trend-down { color: #c62828; }
.trend-stable { color: #f9a825; }
.scorecard-kpi-bar {
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
}
.scorecard-kpi-item {
    flex: 1;
    min-width: 100px;
    text-align: center;
    padding: 0.6rem 0.3rem;
    background: #fafafa;
    border-radius: 6px;
    border-top: 3px solid #ccc;
}
.scorecard-grade {
    display: inline-block;
    font-size: 1.8rem;
    font-weight: 700;
    width: 50px;
    height: 50px;
    line-height: 50px;
    text-align: center;
    border-radius: 50%;
    color: #fff;
    margin-right: 0.8rem;
    vertical-align: middle;
}
.scorecard-alert {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0;
    font-size: 0.75rem;
    border-bottom: 1px solid #f0f0f0;
}
```
