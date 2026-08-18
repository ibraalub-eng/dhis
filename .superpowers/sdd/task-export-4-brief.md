### Task 4: Export Buttons on Both Pages

**Files:**
- Modify: `static/tabs/smart-analytics.html` (controls bar, after the refresh button div at lines 23-25)
- Modify: `static/tabs/comparative.html` (controls bar, after the generate button div at lines 39-41)
- Modify: `static/js/smart-analytics.js` (append `smartExportData`)
- Modify: `static/js/comparative.js` (append `comparativeExportData`)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `GET /export/full-data?month=<YYYY-MM|all>&lang=<ar|en>` from Task 3.
- Produces: `window.smartExportData()` and `window.comparativeExportData()` invoked via inline `onclick`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# --- Frontend structure ---

def test_smart_page_has_export_button():
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-export-btn") is not None
    assert soup.find(id="smart-export-scope") is not None


def test_comparative_page_has_export_button():
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "comparative.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="comparative-export-btn") is not None
    assert soup.find(id="comparative-export-scope") is not None


def test_smart_js_has_export_handler():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function smartExportData" in content
    assert "/export/full-data?month=" in content
    assert "lang=ar" in content


def test_comparative_js_has_export_handler():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "comparative.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function comparativeExportData" in content
    assert "/export/full-data?month=" in content
    assert "lang=${reportLang}" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "page_has_export or js_has_export" -q`
Expected: FAIL — buttons/handlers don't exist yet.

- [ ] **Step 3: Add the export controls to the smart analytics page**

Modify `static/tabs/smart-analytics.html`. After the refresh button `</div>` (line 25, immediately before the `<div style="align-self:flex-end;">` containing `#smart-status`), insert:

```html
    <div style="align-self:flex-end;">
      <select id="smart-export-scope" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;font-size:0.82rem;background:white;">
        <option value="current">الشهر المحدد</option>
        <option value="all">كل الأشهر</option>
      </select>
      <button id="smart-export-btn" class="btn btn-sm" onclick="smartExportData()" style="background:linear-gradient(135deg,#1a237e,#312e81);color:white;padding:0.5rem 1.2rem;border-radius:6px;font-weight:600;">تصدير البيانات</button>
    </div>
```

- [ ] **Step 4: Add the export controls to the comparative page**

Modify `static/tabs/comparative.html`. After the generate button `</div>` (line 41, immediately before the `<div style="align-self:flex-end;">` containing `#comparative-status`), insert:

```html
    <div style="align-self:flex-end;">
      <select id="comparative-export-scope" style="padding:0.45rem 0.6rem;border-radius:6px;border:1px solid #c7d2fe;font-size:0.82rem;background:white;">
        <option value="current">الشهر المحدد</option>
        <option value="all">كل الأشهر</option>
      </select>
      <button id="comparative-export-btn" class="btn btn-sm" onclick="comparativeExportData()" style="background:linear-gradient(135deg,#1a237e,#312e81);color:white;padding:0.5rem 1.2rem;border-radius:6px;font-weight:600;">تصدير البيانات</button>
    </div>
```

- [ ] **Step 5: Add the smart export handler**

Append to `static/js/smart-analytics.js`:

```javascript
async function smartExportData() {
  const scope = document.getElementById('smart-export-scope')?.value || 'current';
  const month = scope === 'all' ? 'all' : (smartCurrentMonth || document.getElementById('smart-month-select')?.value || '');
  const base = document.getElementById('apiBase')?.value || '';
  const url = `${base}/export/full-data?month=${encodeURIComponent(month)}&lang=ar`;
  document.getElementById('smart-status').textContent = 'جاري تصدير البيانات...';
  smartShowLoading();
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `health_export_${month}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    document.getElementById('smart-status').textContent = 'تم تصدير البيانات بنجاح';
  } catch (e) {
    document.getElementById('smart-status').textContent = 'خطأ في التصدير: ' + e.message;
  } finally {
    smartHideLoading();
  }
}
```

- [ ] **Step 6: Add the comparative export handler**

Append to `static/js/comparative.js`:

```javascript
async function comparativeExportData() {
  const scope = document.getElementById('comparative-export-scope')?.value || 'current';
  const month = scope === 'all' ? 'all' : (comparativeCurrentMonth || document.getElementById('comparative-month')?.value || '');
  const base = document.getElementById('apiBase')?.value || '';
  const url = `${base}/export/full-data?month=${encodeURIComponent(month)}&lang=${reportLang}`;
  document.getElementById('comparative-status').textContent = reportLang === 'ar' ? 'جاري تصدير البيانات...' : 'Exporting data...';
  compShowLoading();
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `health_export_${month}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    document.getElementById('comparative-status').textContent = reportLang === 'ar' ? 'تم تصدير البيانات بنجاح' : 'Data exported successfully';
  } catch (e) {
    showAlert((reportLang === 'ar' ? 'خطأ في التصدير: ' : 'Export error: ') + e.message, 'danger');
  } finally {
    compHideLoading();
  }
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -k "page_has_export or js_has_export" -q`
Expected: 4 passed

- [ ] **Step 8: Run the full export suite**

Run: `python -m pytest tests/test_export.py -q`
Expected: all pass (23 total)

- [ ] **Step 9: Run the regression suites**

Run: `python -m pytest tests/test_comparative.py tests/test_smart_analytics.py -q`
Expected: all pass (existing behavior unchanged)

- [ ] **Step 10: Commit**

```bash
git add static/tabs/smart-analytics.html static/tabs/comparative.html static/js/smart-analytics.js static/js/comparative.js tests/test_export.py
git commit -m "feat: add export data buttons to smart and comprehensive report pages"
```


## Self-Review Notes

- **Spec coverage:** All spec sections map to tasks — engine helpers (T1), smart analysis + cache-only report + package build (T2), endpoint + 404/422 + registration (T3), both pages' buttons + scope selector + handlers (T4), testing (all). Non-goals respected: no AI generation (tested in `test_export_never_calls_ai`), JSON only.
- **Type consistency:** `build_full_export(session, month, lang)` signature identical across T2/T3. `get_stored_report`/`run_smart_analytics` names match the real modules. `NoDataError` raised in T2, caught in T3.
- **Numpy handling:** `_sanitize` checks `tolist()` before `.item()` (learned from prior review), so multi-element arrays become lists, single-element numpy scalars become native.
- **The `client` fixture in `tests/test_export.py`** reuses the exact `db_session` override pattern from `tests/test_comparative.py:72-87`.
