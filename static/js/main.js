        // ── State persistence ─────────────────────────────────────
        export function _saveUIState(tab) {
            const activeTab = tab || document.querySelector('.tab.active')?.dataset?.tab || 'dashboard';
            localStorage.setItem('lastTab', activeTab);
            const mappings = {
                dashboard: [['dashHospital','lastDashHospital'],['dashYear','lastDashYear']],
                quality: [['qualityMonthFilter','lastQualityMonth']],
                'root-cause': [['rcHospital','lastRcHospital'],['rcMonth','lastRcMonth']],
                trends: [['trendHospitalSelect','lastTrendHospital']],
                comparison: [['compareHospital1','lastCompareH1'],['compareHospital2','lastCompareH2'],['compareMonthSelect','lastCompareMonth']],
                clinical: [['clinicalHospitalSelect','lastClinHospital'],['clinicalMonthSelect','lastClinMonth']],
                audit: [['auditHospitalSelect','lastAuditHospital'],['auditMonthSelect','lastAuditMonth']],
                'indicator-tree': [['treeHospitalSelect','lastTreeHospital'],['treeMonthSelect','lastTreeMonth']],
            };
            const map = mappings[activeTab] || [];
            map.forEach(([id, key]) => {
                const el = document.getElementById(id);
                if (el) localStorage.setItem(key, el.value);
            });
        }

        export function _restoreUIState(tab) {
            const mappings = {
                dashboard: [['dashHospital','lastDashHospital'],['dashYear','lastDashYear']],
                quality: [['qualityMonthFilter','lastQualityMonth']],
                'root-cause': [['rcHospital','lastRcHospital'],['rcMonth','lastRcMonth']],
                trends: [['trendHospitalSelect','lastTrendHospital']],
                comparison: [['compareHospital1','lastCompareH1'],['compareHospital2','lastCompareH2'],['compareMonthSelect','lastCompareMonth']],
                clinical: [['clinicalHospitalSelect','lastClinHospital'],['clinicalMonthSelect','lastClinMonth']],
                audit: [['auditHospitalSelect','lastAuditHospital'],['auditMonthSelect','lastAuditMonth']],
                'indicator-tree': [['treeHospitalSelect','lastTreeHospital'],['treeMonthSelect','lastTreeMonth']],
            };
            const map = mappings[tab] || [];
            map.forEach(([id, key]) => {
                const val = localStorage.getItem(key);
                if (val !== null) {
                    const el = document.getElementById(id);
                    if (el) {
                        // Only set if the option exists in the select
                        for (let i = 0; i < el.options.length; i++) {
                            if (el.options[i].value === val) {
                                el.value = val;
                                break;
                            }
                        }
                    }
                }
            });
        }

        export function showLoader(msg) {
            const el = document.getElementById('loaderOverlay');
            document.getElementById('loaderText').textContent = msg || 'Loading...';
            el.classList.add('active');
        }
        export function hideLoader() {
            document.getElementById('loaderOverlay').classList.remove('active');
        }
        export const _tabInited = new Set();
        export function SwitchTab(name) { const t = document.querySelector('.tab[data-tab="' + name + '"]'); if (t) t.click(); }

        export function switchTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const targetTab = document.querySelector('.tab[data-tab="' + name + '"]');
            const targetContent = document.getElementById('tab-' + name);
            if (!targetTab || !targetContent) return;
            targetTab.classList.add('active');
            targetContent.classList.add('active');
            _saveUIState(name);
            if (_tabInited.has(name)) return;
            _tabInited.add(name);
            const src = targetContent.dataset.src;
            if (src && targetContent.dataset.loaded === 'false') {
                fetch(src).then(r => r.text()).then(html => {
                    targetContent.innerHTML = html + targetContent.innerHTML;
                    targetContent.dataset.loaded = 'true';
                    _initTab(name);
                }).catch(() => { _initTab(name); });
            } else {
                _initTab(name);
            }
        }
        function _initTab(name) {
            if (name === 'dashboard') window.initDashboard();
            if (name === 'quality') window.loadQualityReports();
            if (name === 'alerts') window.loadAlerts();
            if (name === 'outliers') window.loadOutliers();
            if (name === 'rulefailures') window.loadRuleFailures();
            if (name === 'settings') window.loadAllSettings();
            if (name === 'root-cause') window.initRootCause();
            if (name === 'trends') window.initTrends();
            if (name === 'compare') window.initCompare();
            if (name === 'clinical') window.initClinical();
            if (name === 'ai-reports') { if (!window.restoreReportData()) window.populateReportMonthSelect(); }
            if (name === 'indicator-tree') window.initIndicatorTree();
            if (name === 'rules-manager') window.loadRulesManager();
            if (name === 'audit') window.initAudit();
            if (name === 'smart-analytics') window.initSmartAnalytics();
            if (name === 'comparative') window.initComparative();
        }

        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                switchTab(this.dataset.tab);
            });
        });

