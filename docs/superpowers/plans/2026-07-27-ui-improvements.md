# خطة تنفيذ تحسينات واجهة المستخدم

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** إعادة تصميم واجهة المستخدم مع أقسام قابلة للطي وتنبيهات فورية ولوحة تحكم سريعة

**Architecture:** تحسينات CSS و JavaScript و HTML فقط - لا تغييرات على الباك إند

**Tech Stack:** HTML, CSS, JavaScript, Chart.js, Bootstrap

## Global Constraints
- Python 3.14
- FastAPI
- Arabic language UI
- Bootstrap 4
- Chart.js للرسوم البيانية

---

## File Structure

| الملف | المسؤولية |
|-------|-----------|
| `static/css/styles.css` | إضافة أنماط KPI cards و alerts و collapsible sections |
| `static/js/comparative.js` | إضافة منطق الأقسام القابلة للطي والتنبيهات |
| `static/tabs/comparative.html` | إعادة تصميم بأقسام قابلة للطي |
| `static/index.html` | إضافة لوحة تحكم سريعة |
| `tests/test_comparative.py` | اختبارات جديدة للواجهة |

---

### Task 1: إضافة أنماط CSS جديدة

**Files:**
- Modify: `static/css/styles.css`

- [ ] **Step 1: إضافة أنماط KPI cards**

```css
/* KPI Cards */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.kpi-card { background: white; border-radius: 12px; padding: 1.2rem; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #f0f0f0; transition: transform 0.2s, box-shadow 0.2s; }
.kpi-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
.kpi-card .icon { font-size: 2rem; margin-bottom: 0.5rem; }
.kpi-card .value { font-size: 1.8rem; font-weight: 700; color: #1a237e; line-height: 1.2; }
.kpi-card .label { font-size: 0.8rem; color: #888; margin-top: 0.3rem; }
.kpi-card.danger .value { color: #c62828; }
.kpi-card.warning .value { color: #e65100; }
.kpi-card.success .value { color: #2e7d32; }

/* Collapsible Sections */
.collapsible-section { border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 0.8rem; overflow: hidden; }
.collapsible-header { background: #f8f9fb; padding: 0.8rem 1rem; cursor: pointer; display: flex; align-items: center; justify-content: space-between; font-weight: 600; color: #1a237e; transition: background 0.2s; user-select: none; }
.collapsible-header:hover { background: #eef0f8; }
.collapsible-header .arrow { transition: transform 0.3s; font-size: 0.8rem; }
.collapsible-header.open .arrow { transform: rotate(180deg); }
.collapsible-body { padding: 1rem; display: none; }
.collapsible-body.open { display: block; }

/* Alerts */
.alert-container { position: fixed; top: 80px; right: 20px; z-index: 9999; max-width: 400px; }
.alert-item { padding: 0.8rem 1rem; border-radius: 8px; margin-bottom: 0.5rem; display: flex; align-items: flex-start; gap: 0.5rem; box-shadow: 0 4px 12px rgba(0,0,0,0.1); animation: slideIn 0.3s ease; font-size: 0.85rem; }
.alert-item.danger { background: #ffebee; color: #c62828; border: 1px solid #ffcdd2; }
.alert-item.warning { background: #fff8e1; color: #e65100; border: 1px solid #ffe082; }
.alert-item.info { background: #e3f2fd; color: #1565c0; border: 1px solid #bbdefb; }
.alert-item.success { background: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
.alert-item .close-btn { cursor: pointer; opacity: 0.5; margin-left: auto; font-size: 1.1rem; }
.alert-item .close-btn:hover { opacity: 1; }

@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
```

- [ ] **Step 2: إضافة أنماط بطاقات المؤشرات**

```css
/* Indicator Cards */
.indicator-card { background: white; border-radius: 8px; padding: 1rem; border: 1px solid #f0f0f0; margin-bottom: 0.5rem; display: flex; align-items: center; justify-content: space-between; }
.indicator-card .name { font-weight: 500; color: #333; }
.indicator-card .value { font-size: 1.2rem; font-weight: 700; color: #1a237e; }
.indicator-card .trend { font-size: 0.8rem; padding: 0.2rem 0.5rem; border-radius: 4px; }
.indicator-card .trend.up { background: #ffebee; color: #c62828; }
.indicator-card .trend.down { background: #e8f5e9; color: #2e7d32; }
.indicator-card .trend.stable { background: #e3f2fd; color: #1565c0; }
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS (لا تغييرات متوقعة)

- [ ] **Step 4: Commit**

```bash
git add static/css/styles.css
git commit -m "ui: add KPI cards, collapsible sections, and alerts styles"
```

---

### Task 2: إعادة تصميم واجهة التقرير بأقسام قابلة للطي

**Files:**
- Modify: `static/tabs/comparative.html`
- Modify: `static/js/comparative.js`

- [ ] **Step 1: تعديل comparative.html**

```html
<!-- static/tabs/comparative.html -->
<div id="comparative-tab" class="tab-content" style="display:none;">
    <div class="container-fluid">
        <h2>التحليل المقارن المتقدم</h2>
        
        <!-- KPI Dashboard -->
        <div id="kpi-dashboard" class="kpi-grid" style="display:none;">
            <div class="kpi-card">
                <div class="icon">🏥</div>
                <div class="value" id="kpi-total-hospitals">-</div>
                <div class="label">إجمالي المستشفيات</div>
            </div>
            <div class="kpi-card danger">
                <div class="icon">⚠️</div>
                <div class="value" id="kpi-anomalies">-</div>
                <div class="label">مستشفيات شاذة</div>
            </div>
            <div class="kpi-card warning">
                <div class="icon">📊</div>
                <div class="value" id="kpi-confidence">-</div>
                <div class="label">نسبة الثقة</div>
            </div>
            <div class="kpi-card success">
                <div class="icon">✅</div>
                <div class="value" id="kpi-quality">-</div>
                <div class="label">جودة البيانات</div>
            </div>
        </div>
        
        <!-- اختيار الشهر وطريقة المقارنة -->
        <div class="row mb-3">
            <div class="col-md-3">
                <label>الشهر:</label>
                <select id="comparative-month" class="form-control">
                </select>
            </div>
            <div class="col-md-3">
                <label>طريقة المقارنة:</label>
                <select id="comparison-type" class="form-control">
                    <option value="all">جميع المستشفيات</option>
                    <option value="governorate">نفس المحافظة</option>
                    <option value="type">نفس النوع</option>
                </select>
            </div>
            <div class="col-md-3">
                <label>المستشفى:</label>
                <select id="hospital-select" class="form-control">
                    <option value="">جميع المستشفيات</option>
                </select>
            </div>
            <div class="col-md-3">
                <label>&nbsp;</label>
                <button id="comparative-generate" class="btn btn-primary btn-block">
                    توليد التقرير الذكي
                </button>
            </div>
        </div>
        
        <!-- شريط التحميل -->
        <div id="comparative-loading" style="display:none;" class="text-center my-4">
            <div class="spinner-border text-primary" role="status">
                <span class="sr-only">جاري التحميل...</span>
            </div>
            <p>جاري توليد التقرير الذكي...</p>
        </div>
        
        <!-- منطقة عرض التقرير بأقسام قابلة للطي -->
        <div id="comparative-report-output" style="display:none;">
            <!-- الملخص التنفيذي (دائماً مفتوح) -->
            <div class="collapsible-section">
                <div class="collapsible-header open" onclick="toggleSection(this)">
                    <span>📋 الملخص التنفيذي</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body open">
                    <div id="report-executive-summary" style="white-space: pre-wrap; direction: rtl; text-align: right;"></div>
                </div>
            </div>
            
            <!-- تحليل المؤشرات -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span>📊 تحليل المؤشرات</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-indicators"></div>
                </div>
            </div>
            
            <!-- تحليل الشذوذ -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span>🔍 تحليل الشذوذ</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-anomalies"></div>
                </div>
            </div>
            
            <!-- التجميع والارتباطات -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span>🔗 التجميع والارتباطات</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-clustering"></div>
                </div>
            </div>
            
            <!-- المقارنة الطبقية -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span>📈 المقارنة الطبقية</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-stratified"></div>
                </div>
            </div>
            
            <!-- التوصيات الإجرائية -->
            <div class="collapsible-section">
                <div class="collapsible-header" onclick="toggleSection(this)">
                    <span>💡 التوصيات الإجرائية</span>
                    <span class="arrow">▼</span>
                </div>
                <div class="collapsible-body">
                    <div id="report-recommendations"></div>
                </div>
            </div>
        </div>
        
        <!-- الرسم البياني للمقارنة -->
        <div id="comparison-chart-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5>مقارنة أداء المستشفيات عبر الأشهر</h5>
                <canvas id="comparison-chart"></canvas>
            </div>
        </div>
        
        <!-- جدول مقارنة الأقران -->
        <div id="peer-comparison-container" class="card mt-4" style="display:none;">
            <div class="card-body">
                <h5>مقارنة المستشفيات ببعضها</h5>
                <table id="peer-comparison-table" class="table table-striped">
                    <thead>
                        <tr>
                            <th>الترتيب</th>
                            <th>المستشفى</th>
                            <th>النسبة المئوية</th>
                            <th>التقييم</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: تعديل comparative.js - إضافة دوال الأقسام والتنبيهات**

```javascript
// إضافة إلى comparative.js

function toggleSection(header) {
    header.classList.toggle('open');
    const body = header.nextElementSibling;
    body.classList.toggle('open');
}

function showAlert(message, type = 'info') {
    const container = document.getElementById('alert-container');
    if (!container) {
        const div = document.createElement('div');
        div.id = 'alert-container';
        div.className = 'alert-container';
        document.body.appendChild(div);
    }
    
    const alert = document.createElement('div');
    alert.className = `alert-item ${type}`;
    alert.innerHTML = `
        <span>${message}</span>
        <span class="close-btn" onclick="this.parentElement.remove()">✕</span>
    `;
    
    document.getElementById('alert-container').appendChild(alert);
    
    // إزالة التنبيه بعد 5 ثوان
    setTimeout(() => {
        if (alert.parentElement) {
            alert.remove();
        }
    }, 5000);
}

function updateKPIDashboard(data) {
    const dashboard = document.getElementById('kpi-dashboard');
    if (!dashboard || !data) {
        dashboard.style.display = 'none';
        return;
    }
    
    document.getElementById('kpi-total-hospitals').textContent = data.total_hospitals || '-';
    document.getElementById('kpi-anomalies').textContent = data.anomaly_count || '0';
    document.getElementById('kpi-confidence').textContent = data.confidence_score || '-';
    document.getElementById('kpi-quality').textContent = data.quality_score || '-';
    dashboard.style.display = 'grid';
    
    // تنبيهات
    if (data.anomaly_count > 0) {
        showAlert(`يوجد ${data.anomaly_count} مستشفى بحاجة للانتباه`, 'warning');
    }
    if (data.critical_anomalies > 0) {
        showAlert(`يوجد ${data.critical_anomalies} حالة حرجة!`, 'danger');
    }
}

function parseReportSections(reportText) {
    const sections = {};
    const sectionNames = {
        'الملخص التنفيذي': 'report-executive-summary',
        'تحليل المؤشرات': 'report-indicators',
        'تحليل الشذوذ': 'report-anomalies',
        'التجميع': 'report-clustering',
        'الارتباطات': 'report-clustering',
        'المقارنة الطبقية': 'report-stratified',
        'التوصيات': 'report-recommendations',
    };
    
    let currentSection = 'report-executive-summary';
    const lines = reportText.split('\n');
    
    lines.forEach(line => {
        const trimmed = line.trim();
        for (const [name, id] of Object.entries(sectionNames)) {
            if (trimmed.includes(name)) {
                currentSection = id;
                return;
            }
        }
        
        if (!sections[currentSection]) {
            sections[currentSection] = [];
        }
        sections[currentSection].push(line);
    });
    
    return sections;
}

function renderReportSections(reportText) {
    const sections = parseReportSections(reportText);
    
    for (const [id, lines] of Object.entries(sections)) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = lines.join('\n');
        }
    }
    
    document.getElementById('comparative-report-output').style.display = 'block';
}

async function generateComprehensiveReport(month) {
    comparativeCurrentMonth = month;
    document.getElementById('comparative-loading').style.display = 'block';
    document.getElementById('comparative-report-output').style.display = 'none';
    
    try {
        const result = await apiComparativeGet(`/comparative/comprehensive-report/${month}`);
        
        // عرض التقرير بأقسام
        renderReportSections(result.report);
        
        // تحديث لوحة التحكم
        if (result.data) {
            updateKPIDashboard(result.data.kpi);
        }
        
        showAlert('تم توليد التقرير بنجاح', 'success');
    } catch (e) {
        document.getElementById('comparative-report-output').style.display = 'block';
        showAlert('خطأ في توليد التقرير: ' + e.message, 'danger');
    } finally {
        document.getElementById('comparative-loading').style.display = 'none';
    }
}
```

- [ ] **Step 3: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add static/tabs/comparative.html static/js/comparative.js
git commit -m "ui: add collapsible sections and alert system"
```

---

### Task 3: إضافة اختبارات الواجهة (JavaScript unit tests)

**Files:**
- Modify: `tests/test_comparative.py`
- Create: `tests/test_frontend.js`

**Note:** Since this is a Python project with pytest, we'll add Python tests that verify the HTML/JS structure is correct.

- [ ] **Step 1: إضافة اختبارات لفحص بنية HTML**

```python
# tests/test_comparative.py
import os
from bs4 import BeautifulSoup


def test_comparative_html_has_collapsible_sections():
    """اختبار أن HTML يحتوي على أقسام قابلة للطي"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'comparative.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    # التحقق من وجود الأقسام
    sections = soup.find_all('div', class_='collapsible-section')
    assert len(sections) >= 5  # 5 أقسام على الأقل
    

def test_comparative_html_has_kpi_dashboard():
    """اختبار أن HTML يحتوي على لوحة تحكم"""
    html_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'tabs', 'comparative.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    kpi_grid = soup.find('div', id='kpi-dashboard')
    assert kpi_grid is not None
    

def test_comparative_js_has_toggle_function():
    """اختبار أن JavaScript يحتوي على دالة toggleSection"""
    js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'comparative.js')
    with open(js_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'function toggleSection' in content
    assert 'function showAlert' in content
    assert 'function updateKPIDashboard' in content
    assert 'function renderReportSections' in content
```

- [ ] **Step 2: تشغيل الاختبارات**

Run: `pytest tests/test_comparative.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_comparative.py
git commit -m "test: add frontend structure tests"
```

---

### Task 4: تشغيل جميع الاختبارات والتحقق

- [ ] **Step 1: تشغيل اختبارات المقارنة**

Run: `python -m pytest tests/test_comparative.py -v --tb=short`
Expected: PASS (جميع الاختبارات)

- [ ] **Step 2: Commit النهائي**

```bash
git add .
git commit -m "feat: complete UI improvements - collapsible sections, alerts, KPI dashboard"
```
