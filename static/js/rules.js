        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { EXPR_EXPLANATIONS, rulesManagerData, loadRulesManager } from './settings.js';

        let ruleEditId = null;
        let _indicatorsCache = [];
        let _vbState = {};

        // ── Indicator loading ──────────────────────────────────────
        export async function loadIndicators() {
            if (_indicatorsCache.length > 0) return _indicatorsCache;
            try {
                const res = await fetch(API() + '/hospitals/indicators');
                _indicatorsCache = await res.json();
                return _indicatorsCache;
            } catch(e) {
                console.warn('Could not load indicators', e);
                return [];
            }
        }

        // ── Drag & Drop Helpers ──────────────────────────────────
        let _vbDragCode = null;
        let _vbPaletteFilter = '';

        function _vbPaletteHeaderHTML() {
            return '<div class="vb-palette"><div class="vb-palette-header" style="display:flex;gap:0.5rem;align-items:center;">'
                + '<span>' + __('Drag indicators') + '</span>'
                + '<input type="text" id="vb_palette_search" placeholder="' + __('Filter indicators...') + '" class="vb-search" oninput="_vbOnPaletteSearch()">'
                + '</div>'
                + '<div class="vb-palette-items" id="vb_palette_items">'
                + _vbPaletteItemsHTML()
                + '</div></div>';
        }

        function _vbPaletteItemsHTML() {
            const filter = _vbPaletteFilter.toLowerCase();
            let html = '';
            for (const ind of _indicatorsCache) {
                if (filter && !ind.code.toLowerCase().includes(filter) && !ind.name.toLowerCase().includes(filter)) continue;
                const prefix = '\u00A0'.repeat(ind.level * 2);
                const label = ind.code + ' \u2014 ' + ind.name;
                html += '<span class="vb-pill" draggable="true" ondragstart="_vbDragStart(event,\'' + ind.code + '\')" title="' + label + '">' + prefix + '<span class="vb-pill-code">' + ind.code + '</span> <span class="vb-pill-name">' + ind.name + '</span></span>';
            }
            return html;
        }

        function _vbZoneHTML(id, label, items, multi, emptyText) {
            let html = '<div class="vb-dropzone" id="' + id + '" ondragover="_vbDragOver(event)" ondragenter="_vbDragEnter(event)" ondragleave="_vbDragLeave(event)" ondrop="_vbDrop(event)">';
            html += '<div class="vb-dropzone-label">' + label + (multi ? '' : ' <span style="font-weight:400;color:#999;font-size:0.7rem;">(' + __('drop here') + ')</span>') + '</div>';
            if (items && items.length > 0) {
                for (const code of items) {
                    const ind = _indicatorsCache.find(i => i.code === code);
                    const name = ind ? ind.name : code;
                    html += '<span class="vb-drag-chip" draggable="true" ondragstart="_vbDragStart(event,\'' + code + '\')"><span class="vb-chip-code">' + code + '</span> <span class="vb-chip-name">' + name + '</span> <button class="vb-chip-del" onclick="_vbRemoveFromZone(\'' + id + '\',\'' + code + '\')">\u00d7</button></span>';
                }
            } else if (emptyText) {
                html += '<div class="vb-dropzone-empty">' + emptyText + '</div>';
            }
            html += '</div>';
            return html;
        }

        // ── Drag Event Handlers ──────────────────────────────────
        export function _vbDragStart(ev, code) {
            _vbDragCode = code;
            ev.dataTransfer.effectAllowed = 'move';
            ev.dataTransfer.setData('text/plain', code);
        }

        export function _vbDragOver(ev) {
            ev.preventDefault();
            ev.dataTransfer.dropEffect = 'move';
        }

        export function _vbDragEnter(ev) {
            ev.currentTarget.classList.add('drag-over');
        }

        export function _vbDragLeave(ev) {
            ev.currentTarget.classList.remove('drag-over');
        }

        export function _vbDrop(ev) {
            ev.preventDefault();
            ev.currentTarget.classList.remove('drag-over');
            const code = _vbDragCode || ev.dataTransfer.getData('text/plain');
            if (!code) return;
            const zoneId = ev.currentTarget.id;
            _vbHandleDrop(zoneId, code);
        }

        function _vbHandleDrop(zoneId, code) {
            const isSingle = ['vb_zone_parent','vb_zone_child','vb_zone_numerator','vb_zone_denominator','vb_zone_indicator'].includes(zoneId);
            if (isSingle) {
                _vbState[zoneId.replace('vb_zone_', '')] = code;
            } else if (zoneId === 'vb_zone_children' || zoneId === 'vb_zone_codes') {
                const key = zoneId === 'vb_zone_children' ? 'children' : 'codes';
                if (!_vbState[key]) _vbState[key] = [];
                if (!_vbState[key].includes(code)) _vbState[key].push(code);
            }
            _vbRebuild();
        }

        export function _vbRemoveFromZone(zoneId, code) {
            const key = zoneId === 'vb_zone_children' ? 'children' : zoneId === 'vb_zone_codes' ? 'codes' : zoneId.replace('vb_zone_', '');
            if (key === 'children' || key === 'codes') {
                if (_vbState[key]) _vbState[key] = _vbState[key].filter(c => c !== code);
            } else {
                _vbState[key] = '';
            }
            _vbRebuild();
        }

        function _vbStateReset(expr) {
            _vbState = { _expr: expr, parent:'', child:'', children:[], numerator:'', denominator:'', threshold:80, z_threshold:2.5, indicator:'', factor:2.0, codes:[] };
        }

        // ── Build JSON params from visual state ────────────────────
        function _vbBuildParams() {
            const expr = _vbState._expr;
            if (!expr) return '{}';
            switch (expr) {
                case 'ge':
                case 'eq':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [] });
                case 'le':
                    return JSON.stringify({ child: _vbState.child || '', parent: _vbState.parent || '' });
                case 'le_sum':
                    return JSON.stringify({ child: _vbState.child || '', children: _vbState.children || [] });
                case 'benchmark_rate':
                case 'benchmark_low_rate':
                    return JSON.stringify({ num_code: _vbState.numerator || '', den_code: _vbState.denominator || '', threshold: parseFloat(_vbState.threshold) || 80 });
                case 'cross_hospital_rate':
                    return JSON.stringify({ num_code: _vbState.numerator || '', den_code: _vbState.denominator || '', z_threshold: parseFloat(_vbState.z_threshold) || 2.5 });
                case 'month_over':
                case 'month_under':
                    return JSON.stringify({ code: _vbState.indicator || '', factor: parseFloat(_vbState.factor) || 1.0 });
                case 'neg_check':
                case 'decimal_check':
                case 'all_zero':
                    return JSON.stringify({ codes: _vbState.codes || [] });
                case 'missing':
                    return JSON.stringify({ code: _vbState.indicator || '' });
                default:
                    return '{}';
            }
        }

        function _vbUpdateHidden() {
            document.getElementById('ruleEditParams').value = _vbBuildParams();
        }

        // ── Render builders per category ───────────────────────────

        function _buildVBParentChild(expr) {
            const symbols = { ge: '\u2265', eq: '=', le: '\u2264', le_sum: '\u2265' };
            const symbol = symbols[expr] || '?';
            const geClass = expr === 'ge' || expr === 'le_sum' ? 'ge' : expr === 'eq' ? 'eq' : 'le';
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();

            if (expr === 'ge' || expr === 'eq') {
                let relText = expr === 'ge' ? __('parent \u2265 sum(children)') : __('parent = sum(children)');
                html += _vbZoneHTML('vb_zone_parent', __('Parent'), _vbState.parent ? [_vbState.parent] : [], false, __('Drop parent indicator here'));
                html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + geClass + '">' + symbol + '</span> ' + relText + '</div>';
                html += _vbZoneHTML('vb_zone_children', __('Children'), _vbState.children || [], true, __('Drop child indicators here'));
            } else if (expr === 'le') {
                html += _vbZoneHTML('vb_zone_child', __('Child'), _vbState.child ? [_vbState.child] : [], false, __('Drop child indicator here'));
                html += '<div class="vb-relation-box"><span class="vb-relation-symbol le">' + symbol + '</span> ' + __('child \u2264 parent') + '</div>';
                html += _vbZoneHTML('vb_zone_parent', __('Parent'), _vbState.parent ? [_vbState.parent] : [], false, __('Drop parent indicator here'));
            } else if (expr === 'le_sum') {
                html += _vbZoneHTML('vb_zone_child', __('Child'), _vbState.child ? [_vbState.child] : [], false, __('Drop child indicator here'));
                html += '<div class="vb-relation-box"><span class="vb-relation-symbol ge">' + symbol + '</span> ' + __('child \u2265 sum(children)') + '</div>';
                html += _vbZoneHTML('vb_zone_children', __('Children'), _vbState.children || [], true, __('Drop child indicators here'));
            }

            html += '</div>';
            return html;
        }

        function _buildVBRate(expr) {
            const isLow = expr === 'benchmark_low_rate';
            const cssClass = isLow ? 'lt' : 'ge';
            const symbol = isLow ? '\u2264' : '\u2265';
            const th = parseFloat(_vbState.threshold) || (isLow ? 10 : 80);
            _vbState.threshold = th;
            let relText = isLow ? __('rate <= threshold') : __('rate >= threshold');

            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += '<div style="display:flex;gap:0.75rem;">';
            html += _vbZoneHTML('vb_zone_numerator', __('Numerator'), _vbState.numerator ? [_vbState.numerator] : [], false, __('Drop numerator'));
            html += _vbZoneHTML('vb_zone_denominator', __('Denominator'), _vbState.denominator ? [_vbState.denominator] : [], false, __('Drop denominator'));
            html += '</div>';
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + cssClass + '">' + symbol + '</span> ' + relText + '</div>';
            html += '<div class="vb-row"><span class="vb-label">' + __('Threshold') + '%</span>';
            html += '<input type="number" class="vb-num-input" id="vb_threshold_input" value="' + th + '" min="0" max="100" step="0.1" onchange="_vbOnThresholdChange()">';
            html += '<div class="vb-threshold-track"><div class="vb-threshold-fill" style="width:' + th + '%"></div><div class="vb-threshold-dot" style="left:' + th + '%"></div></div></div>';

            if (expr === 'cross_hospital_rate') {
                const zth = parseFloat(_vbState.z_threshold) || 2.5;
                _vbState.z_threshold = zth;
                html += '<div class="vb-row"><span class="vb-label">z-threshold</span>';
                html += '<input type="number" class="vb-num-input" id="vb_zthreshold_input" value="' + zth + '" min="0" max="10" step="0.1" onchange="_vbOnZThresholdChange()"></div>';
            }

            html += '</div>';
            return html;
        }

        function _buildVBTrend(expr) {
            const isOver = expr === 'month_over';
            const cssClass = isOver ? 'gt' : 'lt';
            const symbol = isOver ? '>' : '<';
            const factor = parseFloat(_vbState.factor) || (isOver ? 2.0 : 0.5);
            _vbState.factor = factor;
            let relText = isOver ? __('current > factor \u00d7 previous') : __('current < factor \u00d7 previous');

            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += _vbZoneHTML('vb_zone_indicator', __('Indicator'), _vbState.indicator ? [_vbState.indicator] : [], false, __('Drop indicator here'));
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + cssClass + '">' + symbol + '</span> ' + relText + '</div>';
            html += '<div class="vb-row"><span class="vb-label">' + __('Factor') + '</span>';
            html += '<input type="number" class="vb-num-input" id="vb_factor_input" value="' + factor + '" min="0" max="100" step="0.1" onchange="_vbOnFactorChange()"></div>';
            html += '</div>';
            return html;
        }

        function _buildVBList(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += '<div style="font-size:0.78rem;font-weight:600;color:#555;margin-bottom:0.4rem;">' + (expr === 'neg_check' ? __('Negative values check') : expr === 'decimal_check' ? __('Decimal values check') : __('All zero check')) + '</div>';
            html += _vbZoneHTML('vb_zone_codes', __('Indicators'), _vbState.codes || [], true, __('Drop indicators here'));
            html += '</div>';
            return html;
        }

        function _buildVBSingle(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += _vbZoneHTML('vb_zone_indicator', __('Indicator'), _vbState.indicator ? [_vbState.indicator] : [], false, __('Drop indicator here'));
            html += '</div>';
            return html;
        }

        // ── Event handlers ─────────────────────────────────────────
        export function _vbOnPaletteSearch() {
            const inp = document.getElementById('vb_palette_search');
            _vbPaletteFilter = inp ? inp.value : '';
            const itemsContainer = document.getElementById('vb_palette_items');
            if (itemsContainer) itemsContainer.innerHTML = _vbPaletteItemsHTML();
        }

        export function _vbOnThresholdChange() {
            const inp = document.getElementById('vb_threshold_input');
            _vbState.threshold = inp ? parseFloat(inp.value) : 80;
            _vbUpdateHidden();
        }

        export function _vbOnZThresholdChange() {
            const inp = document.getElementById('vb_zthreshold_input');
            _vbState.z_threshold = inp ? parseFloat(inp.value) : 2.5;
            _vbUpdateHidden();
        }

        export function _vbOnFactorChange() {
            const inp = document.getElementById('vb_factor_input');
            _vbState.factor = inp ? parseFloat(inp.value) : 1.0;
            _vbUpdateHidden();
        }

        function _vbRebuild() {
            buildVisualBuilder(_vbState._expr);
        }

        // ── Main builder entry point ───────────────────────────────
        function buildVisualBuilder(expr) {
            const container = document.getElementById('ruleVisualBuilder');
            if (!container) return;
            _vbState._expr = expr;
            let html = '';
            const parentChild = ['ge', 'eq', 'le', 'le_sum'];
            const rateTypes = ['benchmark_rate', 'benchmark_low_rate', 'cross_hospital_rate'];
            const trendTypes = ['month_over', 'month_under'];
            const listTypes = ['neg_check', 'decimal_check', 'all_zero'];
            if (parentChild.includes(expr)) {
                html = _buildVBParentChild(expr);
            } else if (rateTypes.includes(expr)) {
                html = _buildVBRate(expr);
            } else if (trendTypes.includes(expr)) {
                html = _buildVBTrend(expr);
            } else if (listTypes.includes(expr)) {
                html = _buildVBList(expr);
            } else if (expr === 'missing') {
                html = _buildVBSingle(expr);
            }
            container.innerHTML = html;
            _vbUpdateHidden();
        }

        // ── Expr template (called on change, also builds visual) ───
        export function ruleExprTemplate() {
            const expr = document.getElementById('ruleEditExpr').value;
            _vbStateReset(expr);
            const expl = EXPR_EXPLANATIONS[expr];
            const panel = document.getElementById('ruleExprExplanation');
            if (expl) {
                document.getElementById('ruleExprExplTitle').textContent = expl.title;
                document.getElementById('ruleExprExplText').textContent = expl.text;
                panel.style.display = 'block';
            } else {
                panel.style.display = 'none';
            }
            buildVisualBuilder(expr);
        }

        function _vbLoadExistingParams(expr, paramsStr) {
            let params = {};
            try { params = typeof paramsStr === 'string' ? JSON.parse(paramsStr) : paramsStr; } catch(e) {}
            _vbStateReset(expr);
            const parentChild = ['ge', 'eq', 'le', 'le_sum'];
            const rateTypes = ['benchmark_rate', 'benchmark_low_rate', 'cross_hospital_rate'];
            const trendTypes = ['month_over', 'month_under'];
            const listTypes = ['neg_check', 'decimal_check', 'all_zero'];

            if (parentChild.includes(expr)) {
                _vbState.parent = params.parent || params.child || '';
                _vbState.child = params.child || '';
                _vbState.children = params.children || [];
            } else if (rateTypes.includes(expr)) {
                _vbState.numerator = params.num_code || '';
                _vbState.denominator = params.den_code || '';
                _vbState.threshold = params.threshold || (expr === 'benchmark_low_rate' ? 10 : 80);
                if (expr === 'cross_hospital_rate') _vbState.z_threshold = params.z_threshold || 2.5;
            } else if (trendTypes.includes(expr)) {
                _vbState.indicator = params.code || '';
                _vbState.factor = params.factor || (expr === 'month_over' ? 2.0 : 0.5);
            } else if (listTypes.includes(expr) || expr === 'missing') {
                _vbState.codes = params.codes || [];
                _vbState.indicator = params.code || '';
            }
            buildVisualBuilder(expr);
        }

        export function toggleExprHelp() {
            const content = document.getElementById('exprHelpContent');
            const h2 = document.querySelector('#rulesExprHelp h2');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                h2.innerHTML = '&#x25BC; Expression Types Reference <span style="font-size:0.75rem;font-weight:400;color:#888;margin-left:0.5rem;">Click to collapse</span>';
            } else {
                content.style.display = 'none';
                h2.innerHTML = '&#x25B6; Expression Types Reference <span style="font-size:0.75rem;font-weight:400;color:#888;margin-left:0.5rem;">Click to expand</span>';
            }
        }

        export async function openRuleModal(ruleId) {
            ruleEditId = ruleId;
            document.getElementById('ruleEditTitle').textContent = ruleId ? __('Edit Rule') : __('New Rule');
            // Load indicators and reset form
            await loadIndicators();
            document.getElementById('ruleEditCode').value = '';
            document.getElementById('ruleEditName').value = '';
            document.getElementById('ruleEditType').value = 'LOGIC';
            document.getElementById('ruleEditSeverity').value = 'HIGH';
            document.getElementById('ruleEditCategory').value = 'BASIC_LOGIC';
            document.getElementById('ruleEditExpr').value = 'ge';
            document.getElementById('ruleEditEnabled').value = 'true';
            document.getElementById('ruleEditDesc').value = '';

            if (ruleId) {
                const rule = rulesManagerData.find(r => r.id == ruleId);
                if (!rule) return;
                document.getElementById('ruleEditCode').value = rule.code;
                document.getElementById('ruleEditName').value = rule.name;
                document.getElementById('ruleEditType').value = rule.rule_type;
                document.getElementById('ruleEditSeverity').value = rule.severity;
                document.getElementById('ruleEditCategory').value = rule.category;
                document.getElementById('ruleEditExpr').value = rule.expression_type;
                document.getElementById('ruleEditEnabled').value = rule.enabled ? 'true' : 'false';
                document.getElementById('ruleEditDesc').value = rule.description || '';
                document.getElementById('ruleEditCode').disabled = true;
                // Load existing params into visual builder
                _vbLoadExistingParams(rule.expression_type, rule.params);
            } else {
                document.getElementById('ruleEditCode').disabled = false;
                ruleExprTemplate();
            }
            document.getElementById('ruleEditModal').classList.add('show');
        }

        export function closeRuleModal() {
            document.getElementById('ruleEditModal').classList.remove('show');
            ruleEditId = null;
        }

        export async function saveRule() {
            const code = document.getElementById('ruleEditCode').value.trim();
            const name = document.getElementById('ruleEditName').value.trim();
            if (!code || !name) { alert(__('Code and Name are required.')); return; }
            // Build params from visual builder
            const paramsRaw = _vbBuildParams();
            const body = {
                code: code,
                name: name,
                rule_type: document.getElementById('ruleEditType').value,
                severity: document.getElementById('ruleEditSeverity').value,
                category: document.getElementById('ruleEditCategory').value,
                expression_type: document.getElementById('ruleEditExpr').value,
                params: paramsRaw,
                description: document.getElementById('ruleEditDesc').value.trim(),
                enabled: document.getElementById('ruleEditEnabled').value === 'true',
            };
            try {
                let res;
                if (ruleEditId) {
                    // Update existing
                    res = await fetch(API() + '/rules/' + ruleEditId, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body),
                    });
                } else {
                    // Create new
                    res = await fetch(API() + '/rules/', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body),
                    });
                }
                if (!res.ok) throw new Error(await res.text());
                closeRuleModal();
                loadRulesManager();
            } catch(e) {
                alert('Save failed: ' + e.message);
            }
        }

        export async function deleteRule(ruleId, code) {
            if (!confirm('Delete rule ' + code + '? This cannot be undone.')) return;
            try {
                const res = await fetch(API() + '/rules/' + ruleId, { method: 'DELETE' });
                if (!res.ok) throw new Error(await res.text());
                loadRulesManager();
            } catch(e) {
                alert('Delete failed: ' + e.message);
            }
        }

