<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Health AI - SRMNH Data Quality Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #333; }
        .header { background: linear-gradient(135deg, #1a237e, #283593); color: white; padding: 1.5rem 2rem; display: flex; align-items: center; justify-content: space-between; }
        .header h1 { font-size: 1.5rem; font-weight: 600; }
        .header .subtitle { font-size: 0.85rem; opacity: 0.8; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 1.5rem; margin-bottom: 1.5rem; }
        .card h2 { font-size: 1.1rem; margin-bottom: 1rem; color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: 0.5rem; }
        .card h3 { font-size: 0.95rem; color: #1a237e; margin-bottom: 0.5rem; }
        .upload-area { border: 2px dashed #c5cae9; border-radius: 8px; padding: 2rem; text-align: center; cursor: pointer; transition: border-color 0.3s, background 0.3s; }
        .upload-area:hover { border-color: #3f51b5; background: #e8eaf6; }
        .upload-area.dragover { border-color: #1a237e; background: #c5cae9; }
        .upload-area input[type="file"] { display: none; }
        .file-list { margin-top: 0.8rem; font-size: 0.85rem; color: #666; }
        .file-list div { padding: 0.2rem 0; }
        .btn { background: #3f51b5; color: white; border: none; padding: 0.6rem 1.5rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; }
        .btn:hover { background: #283593; }
        .btn-sm { padding: 0.4rem 1rem; font-size: 0.8rem; }
        .btn-outline { background: white; color: #3f51b5; border: 1px solid #3f51b5; }
        .btn-outline:hover { background: #e8eaf6; }
        select, input { padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }
        .score-circle { width: 120px; height: 120px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 2rem; font-weight: 700; margin: 0 auto; }
        .score-good { background: #e8f5e9; color: #2e7d32; border: 3px solid #4caf50; }
        .score-medium { background: #fff3e0; color: #e65100; border: 3px solid #ff9800; }
        .score-poor { background: #ffebee; color: #c62828; border: 3px solid #f44336; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f5f5f5; font-weight: 600; color: #555; }
        th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
        th.sortable:hover { background: #e8eaf6; }
        th.sort-asc::after { content: ' \u25B2'; font-size: 0.65rem; }
        th.sort-desc::after { content: ' \u25BC'; font-size: 0.65rem; }
        .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 10px; font-size: 0.75rem; font-weight: 600; }
        .badge-pass { background: #e8f5e9; color: #2e7d32; }
        .badge-fail { background: #ffebee; color: #c62828; }
        .badge-low { background: #e3f2fd; color: #1565c0; }
        .badge-medium { background: #fff3e0; color: #e65100; }
        .badge-high { background: #ffebee; color: #c62828; }
        .badge-critical { background: #b71c1c; color: white; }
        .badge-stable { background: #e8f5e9; color: #2e7d32; }
        .badge-increasing { background: #fff3e0; color: #e65100; }
        .badge-decreasing { background: #e3f2fd; color: #1565c0; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
        .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1.5rem; }
        .stat-box { text-align: center; padding: 1rem; }
        .stat-box .value { font-size: 1.8rem; font-weight: 700; color: #1a237e; }
        .stat-box .label { font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }
        .issue-list { list-style: none; padding: 0; }
        .issue-list li { padding: 0.4rem 0; border-bottom: 1px solid #f0f0f0; font-size: 0.85rem; }
        .issue-list li:last-child { border-bottom: none; }
        #status { padding: 0.5rem; margin-top: 0.5rem; border-radius: 4px; font-size: 0.85rem; }
        .status-ok { background: #e8f5e9; color: #2e7d32; }
        .status-err { background: #ffebee; color: #c62828; }
        .status-loading { background: #e3f2fd; color: #1565c0; }
        .hidden { display: none; }
        .reports-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }
        .report-card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 1.2rem; cursor: pointer; transition: box-shadow 0.2s; }
        .report-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .report-card h3 { font-size: 1rem; color: #1a237e; margin-bottom: 0.3rem; }
        .report-card .month { font-size: 0.8rem; color: #888; }
        .report-card .score { font-size: 2rem; font-weight: 700; text-align: center; margin: 0.5rem 0; }
        .progress-bar { height: 6px; border-radius: 3px; background: #e0e0e0; margin-top: 0.5rem; overflow: hidden; }
        .progress-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
        .filter-bar { display: flex; gap: 0.8rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.8rem; }
        .filter-bar label { font-size: 0.8rem; color: #666; }
        .filter-bar select, .filter-bar input { font-size: 0.8rem; padding: 0.3rem 0.5rem; }
        .count-badge { background: #e8eaf6; color: #1a237e; padding: 0.15rem 0.5rem; border-radius: 10px; font-size: 0.7rem; font-weight: 600; margin-left: 0.3rem; }
        .tab-bar { display: flex; gap: 0; margin-bottom: 1rem; border-bottom: 2px solid #e8eaf6; }
        .tab { padding: 0.6rem 1.2rem; font-size: 0.9rem; cursor: pointer; border-bottom: 2px solid transparent; color: #666; transition: all 0.2s; }
        .tab:hover { color: #1a237e; }
        .tab.active { color: #1a237e; border-bottom-color: #3f51b5; font-weight: 600; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .trend-indicator { display: inline-block; font-size: 0.8rem; }
        .trend-up { color: #e65100; }
        .trend-down { color: #1565c0; }
        .trend-flat { color: #2e7d32; }
        .sparkline { display: inline-block; width: 80px; height: 24px; vertical-align: middle; }
        #detailModal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: none; align-items: center; justify-content: center; }
        #detailModal.show { display: flex; }
        .modal-content { background: white; border-radius: 8px; max-width: 950px; width: 92%; max-height: 85vh; overflow-y: auto; padding: 2rem; }
        .modal-close { float: right; background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #888; }
        .modal-close:hover { color: #333; }
            .tree-group { margin-bottom: 0.5rem; }
            .tree-group-header { font-weight: 700; color: #1a237e; padding: 0.4rem 0; font-size: 0.95rem; border-bottom: 1px solid #e0e0e0; margin-bottom: 0.3rem; }
            .tree-node { padding-left: 1.2rem; }
            .tree-details { margin: 0.1rem 0; }
            .tree-summary { cursor: pointer; padding: 0.2rem 0.3rem; border-radius: 3px; font-size: 0.85rem; user-select: none; }
            .tree-summary:hover { background: #f0f2f5; }
            .tree-summary::-webkit-details-marker { color: #888; }
            .tree-leaf { padding: 0.2rem 0.3rem 0.2rem 1.4rem; border-radius: 3px; font-size: 0.85rem; }
            .tree-leaf:hover { background: #f0f2f5; }
            .tree-code { font-family: 'Consolas','Courier New',monospace; color: #1565c0; font-weight: 600; font-size: 0.8rem; }
            .tree-name { color: #444; }
            .tree-val { font-family: 'Consolas','Courier New',monospace; font-weight: 700; color: #2e7d32; margin-left: 0.5rem; }
            .tree-val-sum { color: #1a237e; }
            .tree-val-null { color: #bbb; font-weight: 400; }
            .tree-toggle { display:inline-block; width:1.1rem; height:1.1rem; line-height:1.1rem; text-align:center; border-radius:2px; cursor:pointer; font-size:0.7rem; margin-right:0.4rem; vertical-align:middle; user-select:none; border:1px solid #ccc; }
            .tree-toggle.on { background:#e8f5e9; color:#2e7d32; border-color:#4caf50; }
            .tree-toggle.on:hover { background:#c8e6c9; }
            .tree-toggle.off { background:#ffebee; color:#c62828; border-color:#ef5350; }
            .tree-toggle.off:hover { background:#ffcdd2; }
            .tree-toggle.loading { opacity:0.5; pointer-events:none; }
            .tree-disabled { opacity:0.45; }
            .tree-disabled .tree-code { text-decoration:line-through; }
            .tree-disabled .tree-name { text-decoration:line-through; }
            .tree-branch-badge { display:inline-block; font-size:0.6rem; padding:0.05rem 0.35rem; border-radius:3px; background:#e3f2fd; color:#1565c0; margin-left:0.4rem; vertical-align:middle; font-weight:500; text-transform:uppercase; letter-spacing:0.03em; }
            @media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Health AI - SRMNH Data Quality System</h1>
            <div class="subtitle">Maternal & Neonatal Health Indicator Analysis</div>
        </div>
        <div>
            <span style="font-size:0.8rem;opacity:0.7;">API:</span>
            <input id="apiBase" value="http://localhost:8000" style="width:180px;color:#333;" placeholder="API Base URL">
        </div>
    </div>

    <div class="container">
        <!-- Upload Card -->
        <div class="card">
            <h2>Smart Data Entry
                <button class="btn btn-sm btn-outline" onclick="downloadTemplate()" style="float:right;font-size:0.75rem;">Download Template</button>
            </h2>
            <div style="display:flex;gap:1rem;flex-wrap:wrap;">
                <div style="flex:1;min-width:300px;">
                    <h3>Upload Excel File</h3>
                    <div class="upload-area" id="dropZone" style="padding:1.2rem;">
                        <p style="font-size:0.9rem;font-weight:500;">Drag & drop or click to browse</p>
                        <p style="font-size:0.75rem;color:#888;margin-top:0.3rem;">.xlsx, .xls, .csv | Multi-file supported</p>
                        <input type="file" id="fileInput" accept=".xlsx,.xls,.csv" multiple>
                    </div>
                    <div id="fileList" class="file-list hidden" style="margin-top:0.5rem;"></div>
                </div>
                <div style="flex:1;min-width:300px;">
                    <h3>Quick Manual Entry</h3>
                    <p style="font-size:0.8rem;color:#666;margin-bottom:0.5rem;">Enter data directly for a single hospital/month.</p>
                    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                        <select id="manualHospital" style="flex:1;min-width:140px;font-size:0.8rem;"><option value="">Select Hospital</option></select>
                        <input type="month" id="manualMonth" style="flex:0 0 160px;font-size:0.8rem;">
                        <button class="btn btn-sm" onclick="showManualEntry()" style="font-size:0.8rem;">Edit Data</button>
                    </div>
                    <div id="manualEntryTable" style="margin-top:0.5rem;display:none;max-height:300px;overflow-y:auto;"></div>
                </div>
            </div>
            <div id="previewArea" style="margin-top:1rem;display:none;">
                <h3>Preview Before Import <span id="previewInfo" style="font-size:0.8rem;color:#888;"></span></h3>
                <div style="max-height:300px;overflow-y:auto;border:1px solid #eee;border-radius:4px;">
                    <table id="previewTable" style="font-size:0.78rem;"><thead></thead><tbody></tbody></table>
                </div>
                <div style="margin-top:0.5rem;display:flex;gap:0.5rem;">
                    <button class="btn btn-sm" onclick="confirmImport()">Confirm & Import</button>
                    <button class="btn btn-sm btn-outline" onclick="cancelPreview()">Cancel</button>
                </div>
            </div>
            <div id="status"></div>
            <div id="uploadProgress" class="hidden" style="margin-top:0.5rem;">
                <div class="progress-bar"><div class="progress-bar-fill" id="uploadProgressFill" style="width:0%;background:#3f51b5;"></div></div>
                <p id="uploadProgressText" style="font-size:0.8rem;color:#888;margin-top:0.3rem;"></p>
            </div>
        </div>

        <!-- Saved Files Card -->
        <div class="card" id="savedFilesCard">
            <h2>Previously Uploaded Files
                <span id="savedCount" class="count-badge" style="font-size:0.75rem;"></span>
                <button class="btn btn-sm btn-outline" onclick="refreshSavedFiles()" style="float:right;font-size:0.75rem;">Refresh</button>
            </h2>
            <div id="savedFilesList">
                <p style="font-size:0.85rem;color:#888;">Loading saved files...</p>
            </div>
            <div style="margin-top:0.5rem;display:none;" id="savedActions">
                <button class="btn btn-sm" onclick="analyzeSelectedSaved()" id="analyzeSavedBtn">Analyze Selected</button>
                <button class="btn btn-sm btn-outline" onclick="deleteSelectedSaved()" style="margin-left:0.5rem;">Delete Selected</button>
            </div>
        </div>

        <!-- Results Section -->
        <div id="resultsSection" class="hidden">
            <div class="tab-bar">
                <div class="tab active" data-tab="quality">Quality Reports</div>
                <div class="tab" data-tab="trends">Trend Analysis</div>
                <div class="tab" data-tab="compare">Hospital Comparison</div>
                <div class="tab" data-tab="clinical">Clinical Intelligence</div>
                <div class="tab" data-tab="outliers">Outliers</div>
                <div class="tab" data-tab="rulefailures">Rule Failures</div>
                <div class="tab" data-tab="indicator-tree">Indicator Tree</div>
            </div>

            <!-- Quality Tab -->
            <div id="tab-quality" class="tab-content active">
                <div style="margin-bottom:1rem;display:flex;align-items:center;gap:0.8rem;">
                    <label style="font-size:0.8rem;color:#666;">Filter by Month:</label>
                    <select id="qualityMonthFilter" onchange="filterQualityReports()">
                        <option value="all">All Months</option>
                    </select>
                    <span id="qualityCount" style="font-size:0.8rem;color:#888;"></span>
                </div>
                <div id="reportsGrid" class="reports-grid"></div>
            </div>

            <!-- Trends Tab -->
            <div id="tab-trends" class="tab-content">
                <div class="card">
                    <h2>Historical Trend Analysis</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Detects gradual drift, consecutive trends, and significant changes across months.
                    </p>
                    <div style="margin-bottom:1rem;">
                        <label style="font-size:0.8rem;color:#666;">Select Hospital:</label>
                        <select id="trendHospitalSelect"></select>
                        <button class="btn btn-sm btn-outline" onclick="loadTrendAnalysis()" style="margin-left:0.5rem;">Analyze Trends</button>
                    </div>
                    <div id="trendSummary" class="grid-3" style="margin-bottom:1rem;"></div>
                    <table id="trendTable"><thead><tr>
                        <th>Indicator</th><th>Direction</th><th>Severity</th><th>Slope %/mo</th><th>CV %</th><th>Last vs Mean</th><th>Consecutive</th><th>Findings</th>
                    </tr></thead><tbody id="trendTbody"></tbody></table>
                </div>
            </div>

            <!-- Compare Tab -->
            <div id="tab-compare" class="tab-content">
                <div class="card">
                    <h2>Cross-Hospital Comparison</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Compare indicators across hospitals for a given month. Identifies significantly above/below average hospitals.
                    </p>
                    <div style="margin-bottom:1rem;">
                        <label style="font-size:0.8rem;color:#666;">Select Month:</label>
                        <select id="compareMonthSelect"></select>
                        <button class="btn btn-sm btn-outline" onclick="loadComparison()" style="margin-left:0.5rem;">Compare Hospitals</button>
                    </div>
                    <table id="compareTable"><thead><tr>
                        <th>Hospital</th><th>Indicator</th><th>Value</th><th>Benchmark</th><th>Deviation %</th><th>Percentile</th><th>Assessment</th>
                    </tr></thead><tbody id="compareTbody"></tbody></table>
                </div>
            </div>

            <!-- Clinical Intelligence Tab -->
            <div id="tab-clinical" class="tab-content">
                <div class="card">
                    <h2>Clinical Intelligence</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Evidence-based clinical classification, risk analysis, morbidity-mortality correlation, and recommendations driven by WHO/FIGO standards.
                    </p>
                    <div style="margin-bottom:1rem;">
                        <label style="font-size:0.8rem;color:#666;">Select Hospital:</label>
                        <select id="clinicalHospitalSelect"></select>
                        <label style="font-size:0.8rem;color:#666;margin-left:0.8rem;">Month:</label>
                        <select id="clinicalMonthSelect"></select>
                        <button class="btn btn-sm btn-outline" onclick="loadClinical()" style="margin-left:0.5rem;">Analyze</button>
                    </div>
                    <div id="clinicalResults"></div>
                </div>
            </div>

            <!-- Outliers Tab -->
            <div id="tab-outliers" class="tab-content">
                <div class="card">
                    <h2>Outlier Analysis</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Statistical outliers detected across hospitals and months via Z-score analysis.
                    </p>
                    <div id="outlierSummary" class="grid-4" style="margin-bottom:1rem;display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;"></div>
                    <div class="filter-bar">
                        <label>Hospital:</label>
                        <select id="outlierHospitalFilter" onchange="loadOutliers()"><option value="">All</option></select>
                        <label>Month:</label>
                        <select id="outlierMonthFilter" onchange="loadOutliers()"><option value="">All</option></select>
                        <label>Rate:</label>
                        <select id="outlierRateFilter" onchange="loadOutliers()"><option value="">All</option></select>
                        <span id="outlierCount" style="font-size:0.8rem;color:#888;margin-left:auto;"></span>
                    </div>
                    <table id="outlierTable">
                        <thead><tr>
                            <th class="sortable" data-col="hospital">Hospital</th>
                            <th class="sortable" data-col="month">Month</th>
                            <th class="sortable" data-col="rate_name">Indicator</th>
                            <th class="sortable" data-col="value">Value</th>
                            <th class="sortable" data-col="benchmark">Benchmark</th>
                            <th class="sortable" data-col="z_score">Z-Score</th>
                        </tr></thead>
                        <tbody id="outlierTbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- Rule Failures Tab -->
            <div id="tab-rulefailures" class="tab-content">
                <div class="card">
                    <h2>Rule Failures</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Data quality rule violations across hospitals and months.
                    </p>
                    <div id="ruleFailSummary" class="grid-4" style="margin-bottom:1rem;display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;"></div>
                    <div class="filter-bar">
                        <label>Hospital:</label>
                        <select id="ruleFailHospitalFilter" onchange="loadRuleFailures()"><option value="">All</option></select>
                        <label>Month:</label>
                        <select id="ruleFailMonthFilter" onchange="loadRuleFailures()"><option value="">All</option></select>
                        <label>Severity:</label>
                        <select id="ruleFailSeverityFilter" onchange="loadRuleFailures()"><option value="">All</option><option value="CRITICAL">Critical</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select>
                        <label>Type:</label>
                        <select id="ruleFailTypeFilter" onchange="loadRuleFailures()"><option value="">All</option><option value="LOGIC">Logic</option><option value="CLINICAL">Clinical</option><option value="STATISTICAL">Statistical</option><option value="TREND">Trend</option></select>
                        <span id="ruleFailCount" style="font-size:0.8rem;color:#888;margin-left:auto;"></span>
                    </div>
                    <table id="ruleFailTable">
                        <thead><tr>
                            <th class="sortable" data-col="hospital">Hospital</th>
                            <th class="sortable" data-col="month">Month</th>
                            <th class="sortable" data-col="rule_code">Rule</th>
                            <th class="sortable" data-col="rule_description">Description</th>
                            <th class="sortable" data-col="severity">Severity</th>
                            <th class="sortable" data-col="rule_type">Type</th>
                            <th class="sortable" data-col="details">Details</th>
                        </tr></thead>
                        <tbody id="ruleFailTbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- Indicator Tree Tab -->
            <div id="tab-indicator-tree" class="tab-content">
                <div class="card">
                    <h2>Indicator Tree</h2>
                    <p style="font-size:0.85rem;color:#666;margin-bottom:1rem;">
                        Browse indicators hierarchically with values for a selected hospital and month.
                    </p>
                    <div class="filter-bar">
                        <label>Hospital:</label>
                        <select id="treeHospitalSelect"></select>
                        <label>Month:</label>
                        <select id="treeMonthSelect"></select>
                        <label>Source:</label>
                        <select id="treeSourceSelect">
                            <option value="db">From DB</option>
                            <option value="tree">Hardcoded Tree</option>
                        </select>
                        <button class="btn btn-sm" onclick="loadIndicatorTree()">Load Tree</button>
                        <span id="treeSummary" style="font-size:0.8rem;color:#888;margin-left:auto;"></span>
                    </div>
                    <div id="treeContainer" style="max-height:600px;overflow-y:auto;font-size:0.85rem;margin-top:0.5rem;"></div>
                    <div style="margin-top:0.8rem;font-size:0.75rem;color:#888;border-top:1px solid #eee;padding-top:0.5rem;">
                        <span>✓ Toggle: click to enable/disable a single indicator.</span><br>
                        <span>Branch nodes use <strong>cascade</strong> — disabling a parent disables all its sub-indicators.</span><br>
                        <span>API endpoints for global management:
                            <code>POST /hospitals/indicators</code> (create),
                            <code>PUT /hospitals/indicators/{id}</code> (edit),
                            <code>DELETE /hospitals/indicators/{id}?cascade=true</code> (delete),
                            <code>PUT /hospitals/indicators/{id}/reparent?new_parent_id=N</code> (re-parent)
                        </span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Detail Modal -->
        <div id="detailModal">
            <div class="modal-content">
                <button class="modal-close" onclick="closeModal()">&times;</button>
                <h2 id="modalTitle" style="color:#1a237e;margin-bottom:1rem;"></h2>
                <div id="modalBody"></div>
            </div>
        </div>
    </div>

    <script>
        const API = () => document.getElementById('apiBase').value;
        let uploadedData = null;

        async function apiGet(path) {
            const res = await fetch(API() + path);
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }
        async function apiPost(path, data) {
            const res = await fetch(API() + path, { method: 'POST', body: data });
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                this.classList.add('active');
                document.getElementById('tab-' + this.dataset.tab).classList.add('active');
            });
        });

        // ── Smart Data Entry ──────────────────────────────────────
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const statusDiv = document.getElementById('status');
        const fileListDiv = document.getElementById('fileList');
        let previewFilePath = null;
        let previewFiles = null;
        let previewFileName = null;

        dropZone.addEventListener('click', () => fileInput.click());
        dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('dragover'); if(e.dataTransfer.files.length) showPreview(e.dataTransfer.files); });
        fileInput.addEventListener('change', () => { if(fileInput.files.length) showPreview(fileInput.files); });

        function showPreview(files) {
            // First upload the file to preview endpoint
            const fd = new FormData();
            // Preview only the first file for now
            fd.append('file', files[0]);
            previewFiles = files;
            setStatus('loading', 'Reading file: ' + files[0].name + '...');
            fetch(API() + '/upload/preview', { method: 'POST', body: fd }).then(r => r.json()).then(data => {
                previewFilePath = data.file_path;
                previewFileName = data.filename;
                const area = document.getElementById('previewArea');
                area.style.display = 'block';
                document.getElementById('previewInfo').textContent = data.total_rows + ' rows | ' + data.hospitals.length + ' hospitals | ' + data.months.length + ' months';
                // Build table
                const cols = ['Hospital', 'Month', 'Indicator', 'Value'];
                let thead = '<tr>' + cols.map(c => '<th>' + c + '</th>').join('') + '</tr>';
                let tbody = data.sample_rows.map(r => '<tr><td>' + esc(r.hospital) + '</td><td>' + esc(r.month) + '</td><td>' + esc(r.indicator) + '</td><td>' + (r.value !== null ? r.value : '<span style="color:red;">MISSING</span>') + '</td></tr>').join('');
                document.querySelector('#previewTable thead').innerHTML = thead;
                document.querySelector('#previewTable tbody').innerHTML = tbody;
                setStatus('ok', 'Preview ready — ' + data.total_rows + ' records from ' + data.hospitals.length + ' hospitals across ' + data.months.length + ' months. Scroll to review, then click Confirm.');
            }).catch(err => {
                setStatus('err', 'Preview failed: ' + err.message);
            });
        }

        function confirmImport() {
            if (!previewFileName) return;
            setStatus('loading', 'Importing and analyzing ' + previewFileName + '...');
            const progress = document.getElementById('uploadProgress');
            progress.classList.remove('hidden');
            const fill = document.getElementById('uploadProgressFill');
            const txt = document.getElementById('uploadProgressText');
            fill.style.width = '30%';
            txt.textContent = 'Processing file...';
            fetch(API() + '/analysis/process-preview?filename=' + encodeURIComponent(previewFileName), { method: 'POST' })
                .then(r => { if (!r.ok) return r.text().then(t => { throw new Error(t); }); return r.json(); })
                .then(result => {
                fill.style.width = '100%';
                txt.textContent = 'Analysis complete.';
                setTimeout(() => { progress.classList.add('hidden'); fill.style.width = '0%'; }, 2000);
                uploadedData = result;
                setStatus('ok', result.message);
                displayResults(result);
                document.getElementById('previewArea').style.display = 'none';
                previewFilePath = null;
                previewFiles = null;
                previewFileName = null;
                refreshSavedFiles();
                loadManualHospitals();
            }).catch(e => {
                fill.style.width = '0%';
                progress.classList.add('hidden');
                let detail = e.message;
                try { const m = detail.match(/"detail"\s*:\s*"([^"]+)"/); if (m) detail = m[1]; } catch {}
                setStatus('err', 'Import failed: ' + detail);
            });
        }

        function cancelPreview() {
            document.getElementById('previewArea').style.display = 'none';
            previewFilePath = null;
            previewFiles = null;
            previewFileName = null;
            fileInput.value = '';
        }

        // ── Template Download ─────────────────────────────────────
        function downloadTemplate() {
            window.open(API() + '/upload/template', '_blank');
        }

        // ── Manual Data Entry ─────────────────────────────────────
        function loadManualHospitals() {
            fetch(API() + '/upload/data-entry/options').then(r => r.json()).then(data => {
                const sel = document.getElementById('manualHospital');
                sel.innerHTML = '<option value="">Select Hospital</option>';
                data.hospitals.forEach(h => { sel.innerHTML += '<option value="' + h.id + '">' + esc(h.name) + '</option>'; });
            }).catch(() => {});
        }

        function showManualEntry() {
            const hospId = document.getElementById('manualHospital').value;
            const month = document.getElementById('manualMonth').value;
            if (!hospId || !month) { alert('Please select hospital and month.'); return; }
            setStatus('loading', 'Loading entry form...');
            fetch(API() + '/upload/data-entry/options').then(r => r.json()).then(data => {
                const hosp = data.hospitals.find(h => h.id == hospId);
                const container = document.getElementById('manualEntryTable');
                container.style.display = 'block';
                let html = '<table style="font-size:0.8rem;"><thead><tr><th>Indicator</th><th>Value</th></tr></thead><tbody>';
                data.indicators.forEach(ind => {
                    html += '<tr><td>' + esc(ind.name) + '</td><td><input type="number" class="manual-val" data-code="' + esc(ind.code) + '" style="width:100px;font-size:0.8rem;" placeholder="0"></td></tr>';
                });
                html += '</tbody></table>';
                html += '<button class="btn btn-sm" style="margin-top:0.5rem;" onclick="saveManualEntry(' + hospId + ',\'' + month + '\')">Save to Database</button>';
                container.innerHTML = html;
                setStatus('ok', 'Enter values for ' + esc(hosp.name) + ' / ' + month);
            }).catch(err => setStatus('err', 'Error: ' + err.message));
        }

        async function saveManualEntry(hospitalId, month) {
            const inputs = document.querySelectorAll('.manual-val');
            const data = {};
            let hasValue = false;
            inputs.forEach(inp => {
                const v = inp.value.trim();
                if (v !== '') { data[inp.dataset.code] = parseFloat(v); hasValue = true; }
            });
            if (!hasValue) { alert('Enter at least one value.'); return; }
            setStatus('loading', 'Saving...');
            try {
                const res = await apiGet('/upload/data-entry/save?hospital_id=' + hospitalId + '&month=' + encodeURIComponent(month) + '&data=' + encodeURIComponent(JSON.stringify(data)));
                setStatus('ok', res.message);
                document.getElementById('manualEntryTable').style.display = 'none';
            } catch (e) {
                setStatus('err', 'Save failed: ' + e.message);
            }
        }

        let allQualityReports = [];

        function displayResults(result) {
            const section = document.getElementById('resultsSection');
            section.classList.remove('hidden');

            allQualityReports = result.quality_reports || [];

            // Populate quality month filter
            const qFilter = document.getElementById('qualityMonthFilter');
            qFilter.innerHTML = '<option value="all">All Months</option>';
            const months = [...new Set(allQualityReports.map(r => r.month))].sort();
            months.forEach(m => { qFilter.innerHTML += '<option value="' + m + '">' + m + '</option>'; });

            // Populate other selects
            const hospSelect = document.getElementById('trendHospitalSelect');
            hospSelect.innerHTML = '';
            result.hospitals.forEach(h => { hospSelect.innerHTML += '<option value="' + h.id + '">' + h.name + '</option>'; });
            const monthSelect = document.getElementById('compareMonthSelect');
            monthSelect.innerHTML = '';
            result.months.forEach(m => { monthSelect.innerHTML += '<option value="' + m + '">' + m + '</option>'; });

            // Populate clinical selects
            const clinHosp = document.getElementById('clinicalHospitalSelect');
            clinHosp.innerHTML = '<option value="">All Hospitals</option>';
            result.hospitals.forEach(h => { clinHosp.innerHTML += '<option value="' + h.id + '">' + h.name + '</option>'; });
            const clinMonth = document.getElementById('clinicalMonthSelect');
            clinMonth.innerHTML = '<option value="">All Months</option>';
            result.months.forEach(m => { clinMonth.innerHTML += '<option value="' + m + '">' + m + '</option>'; });

            // Populate tree selects
            const treeHosp = document.getElementById('treeHospitalSelect');
            treeHosp.innerHTML = '';
            result.hospitals.forEach(h => { treeHosp.innerHTML += '<option value="' + h.id + '">' + esc(h.name) + '</option>'; });
            const treeMonth = document.getElementById('treeMonthSelect');
            treeMonth.innerHTML = '';
            result.months.forEach(m => { treeMonth.innerHTML += '<option value="' + m + '">' + m + '</option>'; });

            filterQualityReports();
        }

        function filterQualityReports() {
            const month = document.getElementById('qualityMonthFilter').value;
            const filtered = month === 'all' ? allQualityReports : allQualityReports.filter(r => r.month === month);
            const grid = document.getElementById('reportsGrid');
            grid.innerHTML = '';
            document.getElementById('qualityCount').textContent = filtered.length + ' report' + (filtered.length !== 1 ? 's' : '');
            if (!filtered.length) { grid.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">No reports for selected month.</p>'; return; }
            filtered.forEach(r => {
                const score = r.data_quality_score;
                const scoreColor = score >= 80 ? '#2e7d32' : score >= 50 ? '#e65100' : '#c62828';
                const barColor = score >= 80 ? '#4caf50' : score >= 50 ? '#ff9800' : '#f44336';
                const issueCount = r.issues ? r.issues.length : 0;
                const outlierCount = r.outliers ? r.outliers.length : 0;
                const card = document.createElement('div');
                card.className = 'report-card';
                card.setAttribute('data-hospital', r.hospital);
                card.setAttribute('data-month', r.month);
                card.innerHTML = '<h3>' + r.hospital + '</h3><div class="month">' + r.month + '</div><div class="score" style="color:' + scoreColor + '">' + score + '</div><div class="progress-bar"><div class="progress-bar-fill" style="width:' + score + '%;background:' + barColor + '"></div></div><div style="margin-top:0.7rem;font-size:0.8rem;color:#666;">' + issueCount + ' issues &bull; ' + outlierCount + ' outliers</div>';
                card.addEventListener('click', function() { showDetail(r.hospital, r.month); });
                grid.appendChild(card);
            });
        }

        let currentValidation = [];
        let valSortCol = 'rule_code', valSortDir = 'asc', valFilterStatus = 'all', valFilterSeverity = 'all';
        let anomSortCol = 'rate_name', anomSortDir = 'asc', anomFilterOutlier = 'all';
        let currentAnomalies = [];
        const SEVERITY_ORDER = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1};
        const STATUS_ORDER = {'FAIL': 2, 'PASS': 1};

        async function showDetail(hospitalName, month) {
            const modal = document.getElementById('detailModal');
            const title = document.getElementById('modalTitle');
            const body = document.getElementById('modalBody');
            title.textContent = hospitalName + ' \u2014 ' + month;
            body.innerHTML = '<p style="text-align:center;padding:2rem;">Loading...</p>';
            modal.classList.add('show');
            try {
                const hospitals = await apiGet('/hospitals/');
                const hosp = hospitals.find(h => h.name === hospitalName);
                if (!hosp) throw new Error('Hospital not found');
                const report = await apiGet('/reports/detail/' + hosp.id + '?month=' + month);
                currentValidation = report.validation_results || [];
                currentAnomalies = report.anomaly_results || [];
                renderDetail(body, report);
            } catch(e) {
                body.innerHTML = '<p style="color:#c62828;">Error: ' + e.message + '</p>';
            }
        }

        function sortAndFilterValidation() {
            let data = [...currentValidation];
            if (valFilterStatus !== 'all') data = data.filter(v => v.status === valFilterStatus);
            if (valFilterSeverity !== 'all') data = data.filter(v => v.severity === valFilterSeverity);
            data.sort((a, b) => {
                let va, vb;
                if (valSortCol === 'rule_code') { va = a.rule_code; vb = b.rule_code; }
                else if (valSortCol === 'rule_description') { va = a.rule_description; vb = b.rule_description; }
                else if (valSortCol === 'status') { va = STATUS_ORDER[a.status]||0; vb = STATUS_ORDER[b.status]||0; }
                else if (valSortCol === 'severity') { va = SEVERITY_ORDER[a.severity]||0; vb = SEVERITY_ORDER[b.severity]||0; }
                else { va = a[valSortCol]||''; vb = b[valSortCol]||''; }
                if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
                return va < vb ? (valSortDir==='asc'?-1:1) : va > vb ? (valSortDir==='asc'?1:-1) : 0;
            });
            return data;
        }

        function sortAndFilterAnomalies() {
            let data = [...currentAnomalies];
            if (anomFilterOutlier === 'yes') data = data.filter(a => a.is_outlier === true);
            else if (anomFilterOutlier === 'no') data = data.filter(a => a.is_outlier === false);
            data.sort((a, b) => {
                let va, vb;
                if (anomSortCol === 'rate_name') { va = a.rate_name||''; vb = b.rate_name||''; }
                else if (anomSortCol === 'value') { va = a.value||0; vb = b.value||0; }
                else if (anomSortCol === 'benchmark') { va = a.benchmark||0; vb = b.benchmark||0; }
                else if (anomSortCol === 'z_score') { va = a.z_score||0; vb = b.z_score||0; }
                else if (anomSortCol === 'is_outlier') { va = a.is_outlier?1:0; vb = b.is_outlier?1:0; }
                else { va = a[anomSortCol]||''; vb = b[anomSortCol]||''; }
                if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
                return va < vb ? (anomSortDir==='asc'?-1:1) : va > vb ? (anomSortDir==='asc'?1:-1) : 0;
            });
            return data;
        }

        function sh(text, colKey, curCol, curDir) {
            const isCur = curCol === colKey;
            const cls = isCur ? (curDir==='asc' ? 'sort-asc' : 'sort-desc') : '';
            return '<th class="sortable ' + cls + '" data-col="' + colKey + '">' + text + '</th>';
        }

        function renderDetail(container, r) {
            const score = r.data_quality_score;
            const scoreClass = score >= 80 ? 'score-good' : score >= 50 ? 'score-medium' : 'score-poor';
            let html = '<div class="grid-2"><div style="text-align:center;"><div class="score-circle ' + scoreClass + '" style="margin:0 auto;">' + score + '</div><p style="font-size:0.85rem;color:#888;margin-top:0.5rem;">Data Quality Score</p><div class="grid-3" style="margin-top:1rem;"><div class="stat-box"><div class="value">' + (r.rule_compliance!==null?r.rule_compliance+'%':'--') + '</div><div class="label">Rule Compliance</div></div><div class="stat-box"><div class="value">' + (r.completeness!==null?r.completeness+'%':'--') + '</div><div class="label">Completeness</div></div><div class="stat-box"><div class="value">' + (r.consistency!==null?r.consistency+'%':'--') + '</div><div class="label">Consistency</div></div></div></div><div><h3 style="font-size:0.95rem;color:#1a237e;margin-bottom:0.5rem;">Issues (' + (r.issues?r.issues.length:0) + ')</h3>';
            if (r.issues && r.issues.length > 0) { html += '<ul class="issue-list">'; r.issues.forEach(i => { html += '<li>' + i + '</li>'; }); html += '</ul>'; } else { html += '<p style="color:#2e7d32;font-size:0.85rem;">No issues found</p>'; }
            html += '</div></div>';

            if (r.validation_results && r.validation_results.length > 0) {
                const failC = r.validation_results.filter(v=>v.status==='FAIL').length;
                const passC = r.validation_results.filter(v=>v.status==='PASS').length;
                const highC = r.validation_results.filter(v=>v.severity==='HIGH').length;
                const medC = r.validation_results.filter(v=>v.severity==='MEDIUM').length;
                const lowC = r.validation_results.filter(v=>v.severity==='LOW').length;
                html += '<div style="margin-top:1.5rem;"><h3>Validation Results <span class="count-badge" id="valCount">' + r.validation_results.length + '</span></h3><div class="filter-bar"><label>Status:</label><select id="filterStatus" onchange="valFilterStatus=this.value;rerenderVal();"><option value="all">All (' + r.validation_results.length + ')</option><option value="FAIL">FAIL (' + failC + ')</option><option value="PASS">PASS (' + passC + ')</option></select><label>Severity:</label><select id="filterSeverity" onchange="valFilterSeverity=this.value;rerenderVal();"><option value="all">All</option><option value="HIGH">HIGH (' + highC + ')</option><option value="MEDIUM">MEDIUM (' + medC + ')</option><option value="LOW">LOW (' + lowC + ')</option></select></div><table><thead><tr>' + sh('Rule','rule_code',valSortCol,valSortDir) + sh('Description','rule_description',valSortCol,valSortDir) + sh('Status','status',valSortCol,valSortDir) + sh('Severity','severity',valSortCol,valSortDir) + '<th>Type</th><th>Details</th></tr></thead><tbody id="valTbody"></tbody></table></div>';
            }
            if (r.anomaly_results && r.anomaly_results.length > 0) {
                const outC = r.anomaly_results.filter(a=>a.is_outlier===true).length;
                const normC = r.anomaly_results.filter(a=>a.is_outlier===false).length;
                html += '<div style="margin-top:1.5rem;"><h3>Anomaly Detection <span class="count-badge" id="anomCount">' + r.anomaly_results.length + '</span></h3><div class="filter-bar"><label>Outlier:</label><select id="filterOutlier" onchange="anomFilterOutlier=this.value;rerenderAnom();"><option value="all">All (' + r.anomaly_results.length + ')</option><option value="yes">Outliers (' + outC + ')</option><option value="no">Normal (' + normC + ')</option></select></div><table><thead><tr>' + sh('Rate','rate_name',anomSortCol,anomSortDir) + sh('Value','value',anomSortCol,anomSortDir) + sh('Benchmark','benchmark',anomSortCol,anomSortDir) + sh('Z-Score','z_score',anomSortCol,anomSortDir) + sh('Outlier','is_outlier',anomSortCol,anomSortDir) + '</tr></thead><tbody id="anomTbody"></tbody></table></div>';
            }
            container.innerHTML = html;
            wireTableSort('valTbody', handleValSort);
            wireTableSort('anomTbody', handleAnomSort);
            rerenderVal();
            rerenderAnom();
        }

        function wireTableSort(tbodyId, handler) {
            let tableEl = document.getElementById(tbodyId);
            if (!tableEl) return;
            tableEl = tableEl.closest('table');
            if (!tableEl) return;
            tableEl.querySelectorAll('th.sortable').forEach(th => {
                th.addEventListener('click', function() { handler(this.getAttribute('data-col')); });
            });
        }

        function handleValSort(col) {
            if (valSortCol===col) valSortDir = valSortDir==='asc'?'desc':'asc'; else { valSortCol=col; valSortDir='asc'; }
            rerenderVal();
            let tableEl = document.getElementById('valTbody');
            if (tableEl) { tableEl = tableEl.closest('table'); tableEl.querySelectorAll('th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); if(h.getAttribute('data-col')===valSortCol) h.classList.add(valSortDir==='asc'?'sort-asc':'sort-desc'); }); }
        }
        function handleAnomSort(col) {
            if (anomSortCol===col) anomSortDir = anomSortDir==='asc'?'desc':'asc'; else { anomSortCol=col; anomSortDir='asc'; }
            rerenderAnom();
            let tableEl = document.getElementById('anomTbody');
            if (tableEl) { tableEl = tableEl.closest('table'); tableEl.querySelectorAll('th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); if(h.getAttribute('data-col')===anomSortCol) h.classList.add(anomSortDir==='asc'?'sort-asc':'sort-desc'); }); }
        }
        function rerenderVal() {
            const tbody = document.getElementById('valTbody'); if (!tbody) return;
            const data = sortAndFilterValidation();
            const typeColors = {'LOGIC': '#1565c0', 'CLINICAL': '#6a1b9a', 'BENCHMARK': '#e65100', 'DATA_QUALITY': '#c62828'};
            let html = '';
            data.forEach(v => {
                const sB = v.status==='PASS'?'<span class="badge badge-pass">PASS</span>':'<span class="badge badge-fail">FAIL</span>';
                const sevB = '<span class="badge badge-'+v.severity.toLowerCase()+'">'+v.severity+'</span>';
                const rt = v.rule_type || 'LOGIC';
                const tc = typeColors[rt] || '#666';
                const typeB = '<span class="badge" style="background:'+tc+'22;color:'+tc+';border:1px solid '+tc+'44;">'+rt+'</span>';
                html += '<tr><td>'+v.rule_code+'</td><td>'+v.rule_description+'</td><td>'+sB+'</td><td>'+sevB+'</td><td>'+typeB+'</td><td style="font-size:0.8rem;">'+(v.details||'')+'</td></tr>';
            });
            if (!data.length) html = '<tr><td colspan="6" style="text-align:center;color:#888;">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('valCount'); if (c) c.textContent = data.length;
        }
        function rerenderAnom() {
            const tbody = document.getElementById('anomTbody'); if (!tbody) return;
            const data = sortAndFilterAnomalies();
            let html = '';
            data.forEach(a => {
                const isO = a.is_outlier;
                const rs = isO ? 'style="background:#fff3e0;"':'';
                html += '<tr '+rs+'><td>'+a.rate_name+'</td><td>'+(a.value!==null&&a.value!==undefined?a.value.toFixed(2):'--')+'</td><td>'+(a.benchmark!==null&&a.benchmark!==undefined?a.benchmark.toFixed(2):'--')+'</td><td>'+(a.z_score!==null&&a.z_score!==undefined?a.z_score.toFixed(2):'--')+'</td><td>'+(isO?'<span class="badge badge-fail">YES</span>':'<span class="badge badge-pass">No</span>')+'</td></tr>';
            });
            if (!data.length) html = '<tr><td colspan="5" style="text-align:center;color:#888;">No matching results</td></tr>';
            tbody.innerHTML = html;
            const c = document.getElementById('anomCount'); if (c) c.textContent = data.length;
        }

        // Trend Analysis
        async function loadTrendAnalysis() {
            const hid = document.getElementById('trendHospitalSelect').value;
            if (!hid) { alert('Select a hospital'); return; }
            try {
                const data = await apiGet('/analysis/historical/' + hid);
                renderTrends(data);
            } catch(e) { alert('Error: ' + e.message); }
        }

        function renderTrends(data) {
            const summary = data.summary;
            const sDiv = document.getElementById('trendSummary');
            sDiv.innerHTML = '<div class="stat-box"><div class="value">' + summary.total_rates_analyzed + '</div><div class="label">Rates Analyzed</div></div><div class="stat-box"><div class="value" style="color:#e65100;">' + summary.increasing_trends + '</div><div class="label">Increasing</div></div><div class="stat-box"><div class="value" style="color:#1565c0;">' + summary.decreasing_trends + '</div><div class="label">Decreasing</div></div><div class="stat-box"><div class="value" style="color:#c62828;">' + summary.critical_trends + '</div><div class="label">Critical</div></div><div class="stat-box"><div class="value">' + summary.trend_outliers + '</div><div class="label">Trend Outliers</div></div><div class="stat-box"><div class="value">' + summary.significant_trends + '</div><div class="label">Significant</div></div>';

            const tbody = document.getElementById('trendTbody');
            tbody.innerHTML = '';
            data.trends.forEach(t => {
                const dirBadge = '<span class="badge badge-' + t.trend_direction + '">' + t.trend_direction + '</span>';
                const sevBadge = '<span class="badge badge-' + t.trend_severity.toLowerCase() + '">' + t.trend_severity + '</span>';
                const sparkline = '<span class="trend-indicator">' + renderSparkline(t.values) + '</span>';
                const findings = t.findings.length ? t.findings.slice(0,2).join('; ') : '-';
                tbody.innerHTML += '<tr><td>' + t.rate_name + '<br>' + sparkline + '</td><td>' + dirBadge + '</td><td>' + sevBadge + '</td><td>' + (t.slope_pct >= 0 ? '+' : '') + t.slope_pct.toFixed(1) + '%</td><td>' + t.cv.toFixed(1) + '%</td><td>' + (t.last_vs_mean_pct_change >= 0 ? '+' : '') + t.last_vs_mean_pct_change.toFixed(1) + '%</td><td>' + t.consecutive_count + ' ' + t.consecutive_direction + '</td><td style="font-size:0.8rem;max-width:200px;">' + findings + '</td></tr>';
            });
        }

        function renderSparkline(values) {
            if (!values || values.length < 2) return '';
            const mn = Math.min(...values), mx = Math.max(...values), range = mx - mn || 1;
            let path = '';
            const w = 80, h = 24;
            values.forEach((v, i) => {
                const x = (i / (values.length - 1)) * w;
                const y = h - ((v - mn) / range) * h;
                path += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
            });
            const color = values[values.length-1] > values[0] ? '#e65100' : values[values.length-1] < values[0] ? '#1565c0' : '#2e7d32';
            return '<svg width="' + w + '" height="' + h + '" style="vertical-align:middle;"><path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2"/></svg>';
        }

        // Hospital Comparison
        async function loadComparison() {
            const month = document.getElementById('compareMonthSelect').value;
            if (!month) { alert('Select a month'); return; }
            try {
                const data = await apiGet('/analysis/compare?month=' + month);
                renderComparison(data);
            } catch(e) { alert('Error: ' + e.message); }
        }

        function renderComparison(data) {
            const tbody = document.getElementById('compareTbody');
            tbody.innerHTML = '';
            data.forEach(c => {
                const labelClass = c.comparison_label.includes('critically') ? 'badge-critical' : c.comparison_label.includes('significantly') ? 'badge-high' : c.comparison_label.includes('above') ? 'badge-medium' : c.comparison_label.includes('below') ? 'badge-low' : 'badge-pass';
                tbody.innerHTML += '<tr><td>' + c.hospital + '</td><td>' + c.rate_name + '</td><td>' + c.value.toFixed(2) + '</td><td>' + c.benchmark.toFixed(2) + '</td><td>' + (c.deviation_pct >= 0 ? '+' : '') + c.deviation_pct.toFixed(1) + '%</td><td>' + c.percentile_rank.toFixed(0) + '</td><td><span class="badge ' + labelClass + '">' + c.comparison_label + '</span></td></tr>';
            });
        }

        // Clinical Intelligence
        function loadClinical() {
            const data = uploadedData;
            if (!data || !data.clinical_analyses) { alert('No clinical data available. Upload files first.'); return; }
            renderClinical(data.clinical_analyses);
        }

        function renderClinical(analyses) {
            const container = document.getElementById('clinicalResults');
            if (!analyses || !analyses.length) {
                container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">No clinical analysis data available.</p>';
                return;
            }

            const hospSel = document.getElementById('clinicalHospitalSelect');
            const monthSel = document.getElementById('clinicalMonthSelect');
            const selHosp = hospSel.value;
            const selMonth = monthSel.value;

            let filtered = analyses;
            if (selHosp) filtered = filtered.filter(a => a.hospital === hospSel.options[hospSel.selectedIndex].text);
            if (selMonth) filtered = filtered.filter(a => a.month === selMonth);

            if (!filtered.length) { container.innerHTML = '<p style="color:#888;text-align:center;padding:2rem;">Select a hospital and month.</p>'; return; }

            let html = '';
            filtered.forEach(a => {
                const s = a.summary;
                const overallColor = s.overall_assessment.startsWith('CRITICAL') ? '#b71c1c' : s.overall_assessment.startsWith('ATTENTION') ? '#e65100' : '#2e7d32';
                html += '<div style="border:1px solid #e0e0e0;border-radius:8px;padding:1.2rem;margin-bottom:1rem;">';
                html += '<h3 style="color:#1a237e;">' + a.hospital + ' &mdash; ' + a.month + '</h3>';

                // Overall assessment banner
                html += '<div style="background:' + overallColor + '11;border-left:4px solid ' + overallColor + ';padding:0.8rem;margin:0.8rem 0;border-radius:4px;"><strong style="color:' + overallColor + ';">' + s.overall_assessment + '</strong></div>';

                // Overview
                html += '<p style="font-size:0.9rem;color:#555;margin:0.5rem 0;">' + s.overview + '</p>';

                // Key findings
                if (s.key_findings && s.key_findings.length) {
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Key Findings</h4><ul class="issue-list">';
                    s.key_findings.forEach(f => { html += '<li>' + f + '</li>'; });
                    html += '</ul>';
                }

                // Clinical Indicators
                if (s.clinical_indicators && s.clinical_indicators.length) {
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Clinical Indicators</h4><div class="grid-3" style="margin:0.5rem 0;">';
                    s.clinical_indicators.forEach(ind => {
                        const parts = ind.split(': ');
                        html += '<div class="stat-box"><div class="value" style="font-size:1.2rem;">' + (parts[1]||'') + '</div><div class="label">' + (parts[0]||'') + '</div></div>';
                    });
                    html += '</div>';
                }

                // Classifications table
                if (a.classifications && a.classifications.length) {
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Clinical Classifications</h4>';
                    html += '<div style="max-height:300px;overflow-y:auto;margin:0.5rem 0;"><table><thead><tr><th>Indicator</th><th>Value</th><th>Status</th><th>Narrative</th></tr></thead><tbody>';
                    a.classifications.filter(c => c.value !== null).forEach(c => {
                        const badge = '<span class="badge" style="background:' + c.color + '22;color:' + c.color + ';border:1px solid ' + c.color + '44;">' + c.label + '</span>';
                        html += '<tr><td>' + c.rate_name + '</td><td>' + (c.value !== null && c.value !== undefined ? c.value.toFixed(1) + c.unit : '--') + '</td><td>' + badge + '</td><td style="font-size:0.8rem;">' + c.narrative + '</td></tr>';
                    });
                    html += '</tbody></table></div>';
                }

                // Risk Profile
                const rp = a.risk_profile;
                if (rp && rp.metrics && rp.metrics.length) {
                    const riskColor = rp.overall_risk_level === 'critical' ? '#b71c1c' : rp.overall_risk_level === 'high' ? '#c62828' : rp.overall_risk_level === 'moderate' ? '#e65100' : '#2e7d32';
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Risk Profile <span class="badge" style="background:' + riskColor + '22;color:' + riskColor + ';border:1px solid ' + riskColor + '44;">' + rp.overall_risk_level.toUpperCase() + '</span></h4>';
                    html += '<div style="max-height:250px;overflow-y:auto;margin:0.5rem 0;"><table><thead><tr><th>Metric</th><th>Value</th><th>Severity</th><th>Interpretation</th></tr></thead><tbody>';
                    rp.metrics.forEach(m => {
                        const sevColor = m.severity === 'critical' ? '#b71c1c' : m.severity === 'high' ? '#c62828' : m.severity === 'moderate' ? '#e65100' : '#2e7d32';
                        const sevBadge = '<span class="badge" style="background:' + sevColor + '22;color:' + sevColor + ';">' + m.severity + '</span>';
                        html += '<tr><td>' + m.metric_name + '</td><td>' + (m.value !== null ? m.value.toFixed(1) + m.unit : '--') + '</td><td>' + sevBadge + '</td><td style="font-size:0.8rem;">' + m.interpretation + '</td></tr>';
                    });
                    html += '</tbody></table></div>';
                }

                // Morbidity Profile
                const mp = a.morbidity_profile;
                if (mp && mp.key_findings && mp.key_findings.length) {
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Morbidity-Mortality Assessment</h4>';
                    html += '<p style="font-size:0.85rem;color:#555;">' + s.morbidity_assessment + '</p>';
                    if (mp.mortality_preventability_signals && mp.mortality_preventability_signals.length) {
                        html += '<ul class="issue-list">';
                        mp.mortality_preventability_signals.forEach(sig => { html += '<li style="color:#c62828;">' + sig + '</li>'; });
                        html += '</ul>';
                    }
                }

                if (mp && mp.metrics && mp.metrics.length) {
                    html += '<div style="max-height:250px;overflow-y:auto;margin:0.5rem 0;"><table><thead><tr><th>Metric</th><th>Value</th><th>Severity</th><th>Interpretation</th></tr></thead><tbody>';
                    mp.metrics.forEach(m => {
                        const sevColor = m.severity === 'critical' ? '#b71c1c' : m.severity === 'high' ? '#c62828' : m.severity === 'moderate' ? '#e65100' : '#2e7d32';
                        const sevBadge = '<span class="badge" style="background:' + sevColor + '22;color:' + sevColor + ';">' + m.severity + '</span>';
                        html += '<tr><td>' + m.metric_name + '</td><td>' + (m.value !== null ? m.value.toFixed(1) + m.unit : '--') + '</td><td>' + sevBadge + '</td><td style="font-size:0.8rem;">' + m.interpretation + '</td></tr>';
                    });
                    html += '</tbody></table></div>';
                }

                // Recommendations
                if (a.recommendations && a.recommendations.length) {
                    html += '<h4 style="margin-top:1rem;color:#333;font-size:0.9rem;">Recommendations (' + a.recommendations.length + ')</h4>';
                    a.recommendations.forEach(rec => {
                        const priColor = rec.priority === 'critical' ? '#b71c1c' : rec.priority === 'high' ? '#c62828' : rec.priority === 'medium' ? '#e65100' : '#2e7d32';
                        html += '<div style="border-left:3px solid ' + priColor + ';padding:0.6rem 0.8rem;margin:0.5rem 0;background:#fafafa;border-radius:4px;">';
                        html += '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;"><span class="badge" style="background:' + priColor + '22;color:' + priColor + ';border:1px solid ' + priColor + '44;">' + rec.priority.toUpperCase() + '</span><strong>' + rec.title + '</strong></div>';
                        html += '<p style="font-size:0.8rem;color:#555;">' + rec.description + '</p>';
                        if (rec.action_items && rec.action_items.length) {
                            html += '<ul style="font-size:0.8rem;margin:0.3rem 0 0 1.2rem;color:#666;">';
                            rec.action_items.forEach(ai => { html += '<li>' + ai + '</li>'; });
                            html += '</ul>';
                        }
                        html += '</div>';
                    });
                }

                html += '</div>';
            });
            container.innerHTML = html;
        }

        function closeModal() { document.getElementById('detailModal').classList.remove('show'); }
        document.getElementById('detailModal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
        document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeModal(); });

        // ── Outliers Tab ──────────────────────────────────────────
        function loadOutliers() {
            const hosp = document.getElementById('outlierHospitalFilter').value;
            const mon = document.getElementById('outlierMonthFilter').value;
            const rate = document.getElementById('outlierRateFilter').value;
            let url = API() + '/analysis/outliers?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (rate) url += 'rate_name=' + encodeURIComponent(rate) + '&';
            fetch(url).then(r => r.json()).then(data => {
                updateOutlierUI(data, hosp, mon, rate);
            }).catch(err => {
                document.getElementById('outlierTbody').innerHTML = '<tr><td colspan="6" style="color:red;">Error: ' + err.message + '</td></tr>';
            });
        }

        function updateOutlierUI(data, currentHosp, currentMon, currentRate) {
            const total = data.length;
            document.getElementById('outlierCount').textContent = total + ' outlier(s)';
            // Summary
            const hospCount = new Set(data.map(d => d.hospital)).size;
            const monCount = new Set(data.map(d => d.month)).size;
            const rates = data.map(d => d.rate_name);
            const topRate = rates.length ? rates.sort((a,b)=>rates.filter(v=>v===a).length-rates.filter(v=>v===b).length).pop() : '--';
            const avgZ = data.length ? (data.reduce((s,d)=>s+Math.abs(d.z_score),0)/data.length).toFixed(2) : '--';
            document.getElementById('outlierSummary').innerHTML =
                '<div class="stat-box"><div class="value">' + total + '</div><div class="label">Total Outliers</div></div>' +
                '<div class="stat-box"><div class="value">' + hospCount + '</div><div class="label">Hospitals</div></div>' +
                '<div class="stat-box"><div class="value">' + monCount + '</div><div class="label">Months</div></div>' +
                '<div class="stat-box"><div class="value">' + avgZ + '</div><div class="label">Avg |Z|</div></div>';
            // Build filters
            const hospSel = document.getElementById('outlierHospitalFilter');
            const monSel = document.getElementById('outlierMonthFilter');
            const rateSel = document.getElementById('outlierRateFilter');
            populateSelectOptions(hospSel, [...new Set(data.map(d => d.hospital))], currentHosp);
            populateSelectOptions(monSel, [...new Set(data.map(d => d.month))], currentMon);
            populateSelectOptions(rateSel, [...new Set(data.map(d => d.rate_name))], currentRate);
            // Render table
            const tbody = document.getElementById('outlierTbody');
            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">No outliers found.</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(d => {
                const z = d.z_score !== null && d.z_score !== undefined;
                const zClass = Math.abs(d.z_score) >= 3 ? 'badge-critical' : Math.abs(d.z_score) >= 2 ? 'badge-high' : 'badge-medium';
                return '<tr>' +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td>' + esc(d.rate_name) + '</td>' +
                    '<td>' + (d.value !== null ? Number(d.value).toFixed(2) : '--') + '</td>' +
                    '<td>' + (d.benchmark !== null ? Number(d.benchmark).toFixed(2) : '--') + '</td>' +
                    '<td><span class="badge ' + zClass + '">' + (z ? Number(d.z_score).toFixed(2) : '--') + '</span></td>' +
                    '</tr>';
            }).join('');
            wireOutlierSort();
        }

        function populateSelectOptions(sel, values, currentVal) {
            const prevVal = sel.value;
            sel.innerHTML = '<option value="">All</option>';
            values.sort().forEach(x => {
                const opt = document.createElement('option');
                opt.value = x; opt.textContent = x;
                sel.appendChild(opt);
            });
            sel.value = currentVal && values.includes(currentVal) ? currentVal : (prevVal && values.includes(prevVal) ? prevVal : '');
        }

        let outlierSortCol = null, outlierSortAsc = true;
        function wireOutlierSort() {
            document.querySelectorAll('#outlierTable th.sortable').forEach(th => {
                th.onclick = function() {
                    const col = this.dataset.col;
                    if (outlierSortCol === col) outlierSortAsc = !outlierSortAsc;
                    else { outlierSortCol = col; outlierSortAsc = true; }
                    document.querySelectorAll('#outlierTable th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); });
                    this.classList.add(outlierSortAsc ? 'sort-asc' : 'sort-desc');
                    sortTableRows('outlierTbody', col, outlierSortAsc);
                };
            });
        }

        function sortTableRows(tbodyId, col, asc) {
            const tbody = document.getElementById(tbodyId);
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const colIdx = Array.from(tbody.parentElement.querySelectorAll('thead th')).findIndex(th => th.dataset.col === col);
            if (colIdx < 0) return;
            rows.sort((a, b) => {
                let av = a.cells[colIdx]?.textContent.trim() || '';
                let bv = b.cells[colIdx]?.textContent.trim() || '';
                const an = parseFloat(av), bn = parseFloat(bv);
                if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
                return asc ? av.localeCompare(bv) : bv.localeCompare(av);
            });
            rows.forEach(r => tbody.appendChild(r));
        }

        // ── Rule Failures Tab ──────────────────────────────────────
        function loadRuleFailures() {
            const hosp = document.getElementById('ruleFailHospitalFilter').value;
            const mon = document.getElementById('ruleFailMonthFilter').value;
            const sev = document.getElementById('ruleFailSeverityFilter').value;
            const typ = document.getElementById('ruleFailTypeFilter').value;
            let url = API() + '/analysis/rule-failures?';
            if (hosp) url += 'hospital_id=' + hosp + '&';
            if (mon) url += 'month=' + encodeURIComponent(mon) + '&';
            if (sev) url += 'severity=' + encodeURIComponent(sev) + '&';
            if (typ) url += 'rule_type=' + encodeURIComponent(typ) + '&';
            fetch(url).then(r => r.json()).then(data => {
                updateRuleFailUI(data, hosp, mon);
            }).catch(err => {
                document.getElementById('ruleFailTbody').innerHTML = '<tr><td colspan="7" style="color:red;">Error: ' + err.message + '</td></tr>';
            });
        }

        function updateRuleFailUI(data, currentHosp, currentMon) {
            const total = data.length;
            document.getElementById('ruleFailCount').textContent = total + ' failure(s)';
            // Summary
            const sevCounts = {};
            const typeCounts = {};
            data.forEach(d => {
                sevCounts[d.severity] = (sevCounts[d.severity] || 0) + 1;
                typeCounts[d.rule_type] = (typeCounts[d.rule_type] || 0) + 1;
            });
            const topSev = Object.entries(sevCounts).sort((a,b) => b[1]-a[1]);
            document.getElementById('ruleFailSummary').innerHTML =
                '<div class="stat-box"><div class="value">' + total + '</div><div class="label">Total Failures</div></div>' +
                '<div class="stat-box"><div class="value">' + (topSev[0] ? topSev[0][0] : '--') + '</div><div class="label">Top Severity</div></div>' +
                '<div class="stat-box"><div class="value">' + new Set(data.map(d => d.hospital)).size + '</div><div class="label">Hospitals</div></div>' +
                '<div class="stat-box"><div class="value">' + new Set(data.map(d => d.rule_code)).size + '</div><div class="label">Unique Rules</div></div>';
            // Populate filters
            const hospSel = document.getElementById('ruleFailHospitalFilter');
            const monSel = document.getElementById('ruleFailMonthFilter');
            populateSelectOptions(hospSel, [...new Set(data.map(d => d.hospital))], currentHosp);
            populateSelectOptions(monSel, [...new Set(data.map(d => d.month))], currentMon);
            // Render
            const tbody = document.getElementById('ruleFailTbody');
            if (!data.length) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;">No rule failures found.</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(d => {
                const sevBadge = d.severity === 'CRITICAL' ? 'badge-critical' : d.severity === 'HIGH' ? 'badge-high' : d.severity === 'MEDIUM' ? 'badge-medium' : 'badge-low';
                const typeBadge = d.rule_type === 'LOGIC' ? 'badge-pass' : d.rule_type === 'CLINICAL' ? 'badge-medium' : d.rule_type === 'STATISTICAL' ? 'badge-high' : 'badge-stable';
                return '<tr>' +
                    '<td>' + esc(d.hospital) + '</td>' +
                    '<td>' + esc(d.month) + '</td>' +
                    '<td><code>' + esc(d.rule_code) + '</code></td>' +
                    '<td>' + esc(d.rule_description) + '</td>' +
                    '<td><span class="badge ' + sevBadge + '">' + esc(d.severity) + '</span></td>' +
                    '<td><span class="badge ' + typeBadge + '">' + esc(d.rule_type) + '</span></td>' +
                    '<td style="font-size:0.8rem;color:#666;">' + esc(d.details).substring(0,80) + '</td>' +
                    '</tr>';
            }).join('');
            wireRuleFailSort();
        }

        // ── Indicator Tree ────────────────────────────────────────
        function loadIndicatorTree() {
            let hospId = document.getElementById('treeHospitalSelect').value;
            let month = document.getElementById('treeMonthSelect').value;
            if (!hospId || !month) {
                document.getElementById('treeContainer').innerHTML = '<div style="color:#888;padding:1rem;">Upload data first, then select a hospital and month.</div>';
                return;
            }
            const source = document.getElementById('treeSourceSelect').value;
            const el = document.getElementById('treeContainer');
            el.innerHTML = '<div style="color:#888;padding:1rem;">Loading...</div>';
            const summary = document.getElementById('treeSummary');
            fetch(API() + '/hospitals/' + hospId + '/indicator-tree?month=' + month + '&source=' + source)
                .then(r => r.json())
                .then(data => {
                    el.innerHTML = '';
                    summary.textContent = data.hospital + ' — ' + data.month;
                    const top = document.createElement('div');
                    top.className = 'tree-group';
                    const header = document.createElement('div');
                    header.className = 'tree-group-header';
                    header.textContent = data.indicator_group;
                    top.appendChild(header);
                    data.children.forEach(child => {
                        top.appendChild(renderTreeNodes(child, 1, hospId));
                    });
                    el.appendChild(top);
                })
                .catch(e => {
                    el.innerHTML = '<div style="color:#a00;padding:1rem;">Error: ' + e.message + '</div>';
                });
        }

        function renderTreeNodes(node, depth, hospitalId) {
            const wrapper = document.createElement('div');
            wrapper.className = 'tree-node';
            if (node.is_enabled === false) wrapper.classList.add('tree-disabled');

            const isParent = node.children && node.children.length > 0;

            const toggle = document.createElement('span');
            toggle.className = 'tree-toggle ' + (node.is_enabled !== false ? 'on' : 'off');
            toggle.textContent = node.is_enabled !== false ? '✓' : '✗';
            toggle.title = isParent
                ? (node.is_enabled !== false ? 'Disable entire branch' : 'Enable entire branch (with sub-indicators)')
                : (node.is_enabled !== false ? 'Disable this indicator' : 'Enable this indicator');
            toggle.onclick = function(e) {
                e.stopPropagation();
                if (toggle.classList.contains('loading')) return;
                toggle.classList.add('loading');
                const indicatorId = node.indicator_id;
                if (!indicatorId) { toggle.classList.remove('loading'); alert('Indicator ID not found. Try switching to \"From DB\" source.'); return; }
                const url = API() + '/hospitals/' + hospitalId + '/indicators/' + indicatorId + '/toggle' +
                    (isParent ? '?cascade=true' : '');
                fetch(url, { method: 'PUT' })
                    .then(r => r.json())
                    .then(data => {
                        node.is_enabled = data.is_enabled;
                        loadIndicatorTree();
                    })
                    .catch(e => {
                        toggle.classList.remove('loading');
                        alert('Toggle failed: ' + e.message);
                    });
            };

            if (isParent) {
                const details = document.createElement('details');
                details.className = 'tree-details';
                if (depth <= 2) details.open = true;

                const summary = document.createElement('summary');
                summary.className = 'tree-summary';
                summary.appendChild(toggle);
                summary.insertAdjacentHTML('beforeend', '<span class="tree-code">' + esc(node.code) + '</span> ' +
                    '<span class="tree-name">' + esc(node.name) + '</span>' +
                    (node.value !== null ? ' <span class="tree-val">' + esc(node.value) + '</span>' :
                    node.children_sum !== undefined ? ' <span class="tree-val tree-val-sum">∑ ' + esc(node.children_sum.toFixed(1)) + '</span>' :
                    ' <span class="tree-val tree-val-null">—</span>') +
                    ' <span class="tree-branch-badge">branch</span>');
                details.appendChild(summary);

                node.children.forEach(child => {
                    details.appendChild(renderTreeNodes(child, depth + 1, hospitalId));
                });
                wrapper.appendChild(details);
            } else {
                const line = document.createElement('div');
                line.className = 'tree-leaf';
                line.appendChild(toggle);
                line.insertAdjacentHTML('beforeend', '<span class="tree-code">' + esc(node.code) + '</span> ' +
                    '<span class="tree-name">' + esc(node.name) + '</span>' +
                    (node.value !== null ? ' <span class="tree-val">' + esc(node.value) + '</span>' :
                    ' <span class="tree-val tree-val-null">—</span>');
                wrapper.appendChild(line);
            }
            return wrapper;
        }

        function setStatus(type, msg) {
            const el = document.getElementById('status');
            if (!el) return;
            el.textContent = msg;
            el.className = 'status-' + type;
        }

        function esc(s) { if (s === null || s === undefined) return ''; return String(s).replace(/[&<>"']/g, function(m) {
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
        }); }

        let ruleFailSortCol = null, ruleFailSortAsc = true;
        function wireRuleFailSort() {
            document.querySelectorAll('#ruleFailTable th.sortable').forEach(th => {
                th.onclick = function() {
                    const col = this.dataset.col;
                    if (ruleFailSortCol === col) ruleFailSortAsc = !ruleFailSortAsc;
                    else { ruleFailSortCol = col; ruleFailSortAsc = true; }
                    document.querySelectorAll('#ruleFailTable th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); });
                    this.classList.add(ruleFailSortAsc ? 'sort-asc' : 'sort-desc');
                    sortTableRows('ruleFailTbody', col, ruleFailSortAsc);
                };
            });
        }

        // Load outlier/rule-fail data on tab switch
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                if (this.dataset.tab === 'outliers') loadOutliers();
                if (this.dataset.tab === 'rulefailures') loadRuleFailures();
                if (this.dataset.tab === 'indicator-tree') loadIndicatorTree();
            });
        });

        // ── Saved Files ────────────────────────────────────────────
        function refreshSavedFiles() {
            fetch(API() + '/analysis/saved-files').then(r => r.json()).then(files => {
                const container = document.getElementById('savedFilesList');
                const actions = document.getElementById('savedActions');
                document.getElementById('savedCount').textContent = files.length + ' file(s)';
                if (!files.length) {
                    container.innerHTML = '<p style="font-size:0.85rem;color:#888;">No saved files found.</p>';
                    actions.style.display = 'none';
                    return;
                }
                actions.style.display = 'block';
                container.innerHTML = '<table style="font-size:0.85rem;"><thead><tr>' +
                    '<th style="width:30px;"><input type="checkbox" id="savedSelectAll" onchange="toggleAllSaved(this)"></th>' +
                    '<th>Filename</th><th>Size (KB)</th><th>Last Modified</th><th>Records</th><th></th>' +
                    '</tr></thead><tbody>' +
                    files.map(f => '<tr>' +
                        '<td><input type="checkbox" class="saved-file-cb" value="' + esc(f.filename) + '"></td>' +
                        '<td><code>' + esc(f.filename) + '</code></td>' +
                        '<td>' + f.size_kb + '</td>' +
                        '<td>' + esc(f.last_modified ? f.last_modified.replace('T',' ').substring(0,16) : '') + '</td>' +
                        '<td>' + f.records_in_db + '</td>' +
                        '<td><button class="btn btn-sm btn-outline" onclick="analyzeSingleSaved(\'' + esc(f.filename) + '\')">Analyze</button></td>' +
                        '</tr>').join('') +
                    '</tbody></table>';
            }).catch(err => {
                document.getElementById('savedFilesList').innerHTML = '<p style="font-size:0.85rem;color:red;">Error: ' + err.message + '</p>';
            });
        }

        function toggleAllSaved(master) {
            document.querySelectorAll('.saved-file-cb').forEach(cb => cb.checked = master.checked);
        }

        function analyzeSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { alert('Select at least one file.'); return; }
            runAnalyzeSaved(selected);
        }

        function analyzeSingleSaved(fname) {
            runAnalyzeSaved([fname]);
        }

        async function runAnalyzeSaved(filenames) {
            const btn = document.getElementById('analyzeSavedBtn');
            const originalText = btn.textContent;
            btn.textContent = 'Analyzing...';
            btn.disabled = true;
            setStatus('loading', 'Analyzing ' + filenames.length + ' saved file(s)...');
            try {
                const params = filenames.map(f => 'filenames=' + encodeURIComponent(f)).join('&');
                const res = await fetch(API() + '/analysis/analyze-saved?' + params, { method: 'POST' });
                if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
                const data = await res.json();
                uploadedData = data;
                displayResults(data);
                setStatus('ok', data.message || 'Analysis complete.');
                refreshSavedFiles();
            } catch (err) {
                setStatus('err', 'Analysis failed: ' + err.message);
            } finally {
                btn.textContent = originalText;
                btn.disabled = false;
            }
        }

        function deleteSelectedSaved() {
            const selected = Array.from(document.querySelectorAll('.saved-file-cb:checked')).map(cb => cb.value);
            if (!selected.length) { alert('Select at least one file.'); return; }
            if (!confirm('Delete ' + selected.length + ' file(s) from disk? (data in DB will NOT be removed)')) return;
            fetch(API() + '/analysis/saved-files', { method: 'DELETE', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filenames: selected}) })
                .then(r => r.json()).then(res => {
                    setStatus('ok', res.message || 'Deleted.');
                    refreshSavedFiles();
                }).catch(err => setStatus('err', 'Delete failed: ' + err.message));
        }

        // Load saved files and manual entry options on page load
        document.addEventListener('DOMContentLoaded', function() { refreshSavedFiles(); loadManualHospitals(); });
    </script>
</body>
</html>