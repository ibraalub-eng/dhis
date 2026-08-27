        // ── State persistence ─────────────────────────────────────
        export function _saveUIState(tab) {
            const activeTab = tab || document.querySelector('.tab.active')?.dataset?.tab || 'dashboard';
            localStorage.setItem('lastTab', activeTab);
            const mappings = {
                dashboard: [['dashHospital','lastDashHospital'],['dashYear','lastDashYear']],
                quality: [['qualityMonthFilter','lastQualityMonth']],
                'root-cause': [['rcHospital','lastRcHospital'],['rcMonth','lastRcMonth']],
                trends: [['trendHospitalSelect','lastTrendHospital']],
                analysis: [['trendHospitalSelect','lastTrendHospital'],['compareMonthSelect','lastCompareMonth']],
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
                analysis: [['trendHospitalSelect','lastTrendHospital'],['compareMonthSelect','lastCompareMonth']],
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
            targetContent.classList.add('active'); updateBreadcrumb(name);
            _saveUIState(name);
            if (_tabInited.has(name)) return;
            _tabInited.add(name);
            const src = targetContent.dataset.src;
            if (src && targetContent.dataset.loaded === 'false') {
                // Show spinner while fetching tab content
                targetContent.innerHTML = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:3rem 1rem;color:var(--text-muted);"><div class="spinner spinner-lg" style="margin-bottom:0.8rem;"></div><span style="font-size:0.9rem;">' + (__ ? __('Loading...') : 'Loading...') + '</span></div>';
                fetch(src).then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.text();
                }).then(html => {
                    targetContent.innerHTML = html;
                    targetContent.dataset.loaded = 'true';
                    _initTab(name);
                    // Re-apply translations to newly loaded content
                    if (typeof window.applyLang === 'function') window.applyLang();
                }).catch((err) => {
                    targetContent.dataset.loaded = 'false';
                    _tabInited.delete(name);
                    targetContent.innerHTML = '<div style="padding:2rem;text-align:center;">' +
                        '<div style="font-size:1.5rem;margin-bottom:0.5rem;">⚠️</div>' +
                        '<div style="color:var(--accent-red);font-size:0.9rem;font-weight:600;margin-bottom:0.3rem;">Tab Failed to Load</div>' +
                        '<div style="color:var(--text-muted);font-size:0.78rem;margin-bottom:1rem;">' + (err.message || 'Network error') + '</div>' +
                        '<button class="btn btn-sm" onclick="window._retryTab(\'' + name + '\')" style="background:var(--accent-blue);color:white;">↻ Retry</button>' +
                        '</div>';
                });
            } else {
                _initTab(name);
            }
        }
        function _initTab(name) {
            // Always read from window[name] so we get the latest replacement
            function _tryInit(name, retries) {
                var fn = window[name];
                if (typeof fn === 'function' && fn.toString().indexOf('Module not loaded') === -1) {
                    fn();
                } else if (retries > 0) {
                    setTimeout(function() { _tryInit(name, retries - 1); }, 300);
                }
            }
            if (name === 'dashboard') _tryInit('initDashboard', 10);
            if (name === 'quality') _tryInit('loadQualityReports', 10);
            if (name === 'alerts') { _tryInit('loadAlerts', 10); _tryInit('loadRuleFailures', 10); }
            if (name === 'outliers') _tryInit('loadOutliers', 10);
            if (name === 'settings') _tryInit('loadAllSettings', 10);
            if (name === 'root-cause') _tryInit('initRootCause', 10);
            if (name === 'analysis') _tryInit('initAnalysis', 10);
            if (name === 'clinical') _tryInit('initClinical', 10);
            if (name === 'indicator-tree') _tryInit('initIndicatorTree', 10);
            if (name === 'rules-manager') _tryInit('loadRulesManager', 10);
            if (name === 'audit') _tryInit('initAudit', 10);
            if (name === 'smart-analytics') _tryInit('initSmartAnalytics', 10);
            if (name === 'admin') _tryInit('loadAdminPanel', 10);
        }

        window._retryTab = function(name) {
            var targetContent = document.getElementById('tab-' + name);
            if (!targetContent) return;
            targetContent.dataset.loaded = 'false';
            _tabInited.delete(name);
            switchTab(name);
        };

        // -- Skeleton Loading Component --
        export function skeletonCard(lines){var n=lines||4;var h='<div class="skeleton-card"><div class="skeleton skeleton-title"></div>';for(var i=0;i<n;i++){var w=i===n-1?'short':(i%3===0?'medium':'');h+='<div class="skeleton skeleton-line "+w+"></div>';}return h+'</div>';}
        export function skeletonTable(rows,cols){var r=rows||5;var c=cols||4;var h='<div class="skeleton-card"><div class="skeleton-table">';for(var i=0;i<r;i++){h+='<div class="skeleton-table-row">';for(var j=0;j<c;j++)h+='<div class="skeleton skeleton-table-cell"></div>';h+='</div>';}return h+'</div></div>';}
        export function skeletonChart(){return '<div class="skeleton-card"><div class="skeleton skeleton-chart"></div></div>';}
        window.skeletonCard=skeletonCard;window.skeletonTable=skeletonTable;window.skeletonChart=skeletonChart;

        // -- Breadcrumb Navigation --
        var _tabLabels = { dashboard: 'Dashboard', quality: 'Quality Reports', analysis: 'Comparative Analysis', clinical: 'Clinical Intelligence', outliers: 'Outliers', alerts: 'Alerts', 'indicator-tree': 'Indicator Tree', 'rules-manager': 'Rules Manager', 'root-cause': 'Root Cause', audit: 'Audit Log', admin: 'Admin Panel', settings: 'System Settings', 'smart-analytics': 'Smart Analytics' };
        var _tabIcons = { dashboard: '📊', quality: '⭐', analysis: '📈', clinical: '🩺', outliers: '⚠', alerts: '🔔', 'indicator-tree': '🌳', 'rules-manager': '📝', 'root-cause': '🔍', audit: '📋', admin: '🛡', settings: '⚙', 'smart-analytics': '🧠' };
        export function updateBreadcrumb(tabName) { var el = document.getElementById('bcCurrent'); if (!el) return; el.textContent = (_tabIcons[tabName]||'')+' '+(_tabLabels[tabName]||tabName); }
        window.updateBreadcrumb = updateBreadcrumb;

        // -- Global Search (Ctrl+K) --
        var _searchItems = [ {tab:'dashboard',kw:'dashboard home ranking overview'},{tab:'quality',kw:'quality scores reports'},{tab:'analysis',kw:'analysis comparative trends peers'},{tab:'clinical',kw:'clinical maternal neonatal'},{tab:'outliers',kw:'outliers anomalies'},{tab:'alerts',kw:'alerts warnings rule failures'},{tab:'indicator-tree',kw:'indicator tree hierarchy'},{tab:'rules-manager',kw:'rules validation'},{tab:'root-cause',kw:'root cause analysis'},{tab:'audit',kw:'audit log history'},{tab:'admin',kw:'admin users roles permissions'},{tab:'settings',kw:'settings config thresholds AI'},{tab:'smart-analytics',kw:'smart analytics AI ML'} ];
        var _searchIdx = 0;
        function openSearch() { var ov=document.getElementById('searchOverlay'); var inp=document.getElementById('searchInput'); if(!ov||!inp)return; ov.classList.add('active'); inp.value=''; inp.focus(); _showSearchResults(''); }
        function closeSearch() { var ov=document.getElementById('searchOverlay'); if(ov)ov.classList.remove('active'); }
        window.openSearch=openSearch; window.closeSearch=closeSearch;
        function _showSearchResults(query) {
            var el=document.getElementById('searchResults');
            if(!el)return;
            var q=query.toLowerCase().trim();
            var items=q?_searchItems.filter(function(i){return i.tab.indexOf(q)>=0||i.kw.indexOf(q)>=0;}):_searchItems;
            _searchIdx=0;
            if(!items.length){el.innerHTML='<div style="padding:1rem;text-align:center;color:var(--text-muted)">No results</div>';return;}
            var html = '';
            items.forEach(function(item,i){
                var icon=_tabIcons[item.tab]||'';
                var label=_tabLabels[item.tab]||item.tab;
                var cls='search-result-item'+(i===0?' selected':'');
                html+='<div class="'+cls+'" data-tab="'+item.tab+'"><span class="sr-icon">'+icon+'</span><span>'+label+'</span></div>';
            });
            el.innerHTML=html;
            el.querySelectorAll('.search-result-item').forEach(function(el){
                el.onclick=function(){switchTab(this.dataset.tab);closeSearch();};
            });
        }
                // ── State persistence ─────────────────────────────────────// -- Keyboard Navigation --
        document.addEventListener('keydown', function(e) { var a=document.activeElement; var isInput=a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA'||a.tagName==='SELECT'); if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();var ov=document.getElementById('searchOverlay');if(ov&&ov.classList.contains('active'))closeSearch();else openSearch();return;} if(e.key==='Escape'){var s=document.getElementById('searchOverlay');if(s&&s.classList.contains('active')){closeSearch();return;} var dm=document.getElementById('detailModal');if(dm&&dm.classList.contains('show')){closeModal();return;} if(typeof closeRuleModal==='function'){closeRuleModal();}} var so=document.getElementById('searchOverlay'); if(so&&so.classList.contains('active')){if(e.key==='ArrowDown'){e.preventDefault();_searchNav(1);return;}if(e.key==='ArrowUp'){e.preventDefault();_searchNav(-1);return;}if(e.key==='Enter'){var sel=document.querySelector('.search-result-item.selected');if(sel){switchTab(sel.dataset.tab);closeSearch();}return;}} if(!isInput&&(e.key==='ArrowLeft'||e.key==='ArrowRight')){var tabs=Array.from(document.querySelectorAll('.tab'));var idx=tabs.findIndex(function(t){return t.classList.contains('active');});if(idx<0)return;var d=e.key==='ArrowRight'?1:-1;var n=idx+d;while(n>=0&&n<tabs.length){if(tabs[n].offsetParent!==null){tabs[n].click();break;}n+=d;}} });
        document.addEventListener('input', function(e){if(e.target.id==='searchInput')_showSearchResults(e.target.value);});
        document.addEventListener('click', function(e){var ov=document.getElementById('searchOverlay');if(ov&&ov.classList.contains('active')&&e.target===ov)closeSearch();});

        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                switchTab(this.dataset.tab);
            });
        });

