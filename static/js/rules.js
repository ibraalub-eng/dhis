        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { EXPR_EXPLANATIONS, rulesManagerData, loadRulesManager } from './settings.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';
import { confirmDestructive } from './confirm-modal.js';

        let ruleEditId = null;
        let _indicatorsCache = [];
        let _vbState = {};

        // ── Indicator loading ──────────────────────────────────────
        export async function loadIndicators() {
            if (_indicatorsCache.length > 0) return _indicatorsCache;
            try {
                const res = await authFetch(API() + '/hospitals/indicators');
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
            html += '<div class="vb-dropzone-label">' + label + (multi ? '' : ' <span style="font-weight:400;color:var(--text-muted);font-size:0.7rem;">(' + __('drop here') + ')</span>') + '</div>';
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
            const isSingle = ['vb_zone_parent','vb_zone_child','vb_zone_numerator','vb_zone_denominator','vb_zone_indicator','vb_zone_target'].includes(zoneId);
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
            _vbState = { _expr: expr, parent:'', child:'', children:[], numerator:'', denominator:'', threshold:80, z_threshold:2.5, indicator:'', factor:2.0, ge_factor:1.1, codes:[], formulaParts:[], target:'' };
        }

        // ── Formula helpers ────────────────────────────────────────
        function _formulaPartsToString(parts) {
            return parts.map(p => {
                if (p.t === 'ind') return '{' + p.code + '}';
                if (p.t === 'num') return String(p.val);
                return p.op;
            }).join(' ');
        }

        function _formulaStringToParts(str) {
            var parts = [];
            var i = 0;
            while (i < str.length) {
                var ch = str[i];
                if (ch === ' ' || ch === '\t') { i++; continue; }
                if (ch === '{') {
                    var j = str.indexOf('}', i + 1);
                    if (j === -1) break;
                    parts.push({ t: 'ind', code: str.slice(i + 1, j) });
                    i = j + 1;
                } else if ('+-*/()'.includes(ch)) {
                    parts.push({ t: 'op', op: ch });
                    i++;
                } else if (ch >= '0' && ch <= '9') {
                    var start = i;
                    while (i < str.length && ((str[i] >= '0' && str[i] <= '9') || str[i] === '.')) i++;
                    parts.push({ t: 'num', val: parseFloat(str.slice(start, i)) });
                } else {
                    i++;
                }
            }
            return parts;
        }

        // ── Build JSON params from visual state ────────────────────
        function _vbBuildParams() {
            const expr = _vbState._expr;
            if (!expr) return '{}';
            switch (expr) {
                case 'ge':
                case 'eq':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [] });
                case 'gt':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [] });
                case 'ge_factor':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [], factor: parseFloat(_vbState.ge_factor) || 1.0 });
                case 'le':
                case 'lt':
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
                case 'formula':
                    return JSON.stringify({ formula: _formulaPartsToString(_vbState.formulaParts || []), target: _vbState.target || '' });
                default:
                    return '{}';
            }
        }

        function _vbUpdateHidden() {
            document.getElementById('ruleEditParams').value = _vbBuildParams();
        }

        // ── Render builders per category ───────────────────────────

        function _buildVBParentChild(expr) {
            const symbols = { ge: '\u2265', eq: '=', le: '\u2264', le_sum: '\u2265', gt: '>', lt: '<', ge_factor: '\u2265' };
            const symbol = symbols[expr] || '?';
            const geClass = ['ge', 'le_sum', 'ge_factor'].includes(expr) ? 'ge' : ['gt', 'lt'].includes(expr) ? (expr === 'gt' ? 'gt' : 'lt') : expr === 'eq' ? 'eq' : 'le';
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();

            if (expr === 'ge' || expr === 'eq' || expr === 'gt' || expr === 'ge_factor') {
                let relText;
                if (expr === 'ge') relText = __('parent \u2265 sum(children)');
                else if (expr === 'gt') relText = __('parent > sum(children)');
                else if (expr === 'ge_factor') relText = __('parent \u00d7 factor \u2265 sum(children)');
                else relText = __('parent = sum(children)');
                html += _vbZoneHTML('vb_zone_parent', __('Parent'), _vbState.parent ? [_vbState.parent] : [], false, __('Drop parent indicator here'));
                html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + geClass + '">' + symbol + '</span> ' + relText + '</div>';
                html += _vbZoneHTML('vb_zone_children', __('Children'), _vbState.children || [], true, __('Drop child indicators here'));
                if (expr === 'ge_factor') {
                    const gf = parseFloat(_vbState.ge_factor) || 1.1;
                    _vbState.ge_factor = gf;
                    html += '<div class="vb-row"><span class="vb-label">' + __('Factor') + '</span>';
                    html += '<input type="number" class="vb-num-input" id="vb_gefactor_input" value="' + gf + '" min="0" max="10" step="0.05" onchange="_vbOnGeFactorChange()"></div>';
                }
            } else if (expr === 'le' || expr === 'lt') {
                const relText = expr === 'le' ? __('child \u2264 parent') : __('child < parent');
                const sym = expr === 'le' ? '\u2264' : '<';
                const symClass = expr === 'le' ? 'le' : 'lt';
                html += _vbZoneHTML('vb_zone_child', __('Child'), _vbState.child ? [_vbState.child] : [], false, __('Drop child indicator here'));
                html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + symClass + '">' + sym + '</span> ' + relText + '</div>';
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
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.4rem;">' + (expr === 'neg_check' ? __('Negative values check') : expr === 'decimal_check' ? __('Decimal values check') : __('All zero check')) + '</div>';
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

        function _buildVBFormula(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.4rem;">' + __('Formula (left side)') + '</div>';
            html += '<div class="vb-dropzone" id="vb_zone_formula" ondragover="_vbDragOver(event)" ondragenter="_vbDragEnter(event)" ondragleave="_vbDragLeave(event)" ondrop="_vbDropFormula(event)">';
            html += '<div class="vb-dropzone-label">' + __('Drop indicators here') + ' <span style="font-weight:400;color:var(--text-muted);font-size:0.7rem;">(' + __('or use buttons below') + ')</span></div>';
            var parts = _vbState.formulaParts || [];
            for (var pi = 0; pi < parts.length; pi++) {
                var p = parts[pi];
                if (p.t === 'ind') {
                    var ind = _indicatorsCache.find(function(x){return x.code === p.code;});
                    var nm = ind ? ind.name : p.code;
                    html += '<span class="vb-drag-chip vb-chip-ind" draggable="true" ondragstart="_vbDragStart(event,\'' + p.code + '\')"><span class="vb-chip-code">' + p.code + '</span> <span class="vb-chip-name">' + nm + '</span> <button class="vb-chip-del" onclick="_vbFormulaRemove(' + pi + ')">\u00d7</button></span>';
                } else if (p.t === 'num') {
                    html += '<span class="vb-drag-chip vb-chip-num"><span class="vb-chip-code">' + p.val + '</span> <button class="vb-chip-del" onclick="_vbFormulaRemove(' + pi + ')">\u00d7</button></span>';
                } else {
                    html += '<span class="vb-drag-chip vb-chip-op"><span class="vb-chip-code">' + p.op + '</span> <button class="vb-chip-del" onclick="_vbFormulaRemove(' + pi + ')">\u00d7</button></span>';
                }
            }
            html += '</div>';
            html += '<div class="vb-formula-toolbar">';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'(\')" title="Open paren">(</button>';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\')\')" title="Close paren">)</button>';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'+\')" title="Add">+</button>';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'-\')" title="Subtract">&minus;</button>';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'*\')" title="Multiply">&times;</button>';
            html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'/\')" title="Divide">&divide;</button>';
            html += '<span style="margin-left:0.4rem;display:inline-flex;align-items:center;gap:0.25rem;"><input type="number" id="vb_formula_num_input" class="vb-num-input" style="width:60px;" value="" placeholder="&#8484;" step="any"><button class="vb-formula-btn" onclick="_vbFormulaAddNum()">+</button></span>';
            html += '<button class="vb-formula-btn vb-formula-btn-danger" onclick="_vbFormulaClear()" title="Clear all">&times; ' + __('Clear') + '</button>';
            html += '</div>';
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol eq">=</span> ' + __('formula result == target indicator') + '</div>';
            html += _vbZoneHTML('vb_zone_target', __('Target Indicator'), _vbState.target ? [_vbState.target] : [], false, __('Drop target indicator here'));
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

        export function _vbOnGeFactorChange() {
            const inp = document.getElementById('vb_gefactor_input');
            _vbState.ge_factor = inp ? parseFloat(inp.value) : 1.1;
            _vbUpdateHidden();
        }

        export function _vbFormulaAddOp(op) {
            if (!_vbState.formulaParts) _vbState.formulaParts = [];
            _vbState.formulaParts.push({ t: 'op', op: op });
            _vbRebuild();
        }

        export function _vbFormulaAddNum() {
            var inp = document.getElementById('vb_formula_num_input');
            if (!inp) return;
            var val = parseFloat(inp.value);
            if (isNaN(val)) return;
            if (!_vbState.formulaParts) _vbState.formulaParts = [];
            _vbState.formulaParts.push({ t: 'num', val: val });
            inp.value = '';
            _vbRebuild();
        }

        export function _vbFormulaAddIndicator(code) {
            if (!_vbState.formulaParts) _vbState.formulaParts = [];
            _vbState.formulaParts.push({ t: 'ind', code: code });
            _vbRebuild();
        }

        export function _vbFormulaRemove(idx) {
            if (!_vbState.formulaParts) return;
            _vbState.formulaParts.splice(idx, 1);
            _vbRebuild();
        }

        export function _vbFormulaClear() {
            _vbState.formulaParts = [];
            _vbRebuild();
        }

        export function _vbDropFormula(ev) {
            ev.preventDefault();
            ev.currentTarget.classList.remove('drag-over');
            var code = _vbDragCode || ev.dataTransfer.getData('text/plain');
            if (!code) return;
            _vbFormulaAddIndicator(code);
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
            const parentChild = ['ge', 'eq', 'gt', 'ge_factor', 'le', 'lt', 'le_sum'];
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
            } else if (expr === 'formula') {
                html = _buildVBFormula(expr);
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
                document.getElementById('ruleExprExplTitle').textContent = __(expl.title);
                document.getElementById('ruleExprExplText').textContent = __(expl.text);
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
            const parentChild = ['ge', 'eq', 'gt', 'ge_factor', 'le', 'lt', 'le_sum'];
            const rateTypes = ['benchmark_rate', 'benchmark_low_rate', 'cross_hospital_rate'];
            const trendTypes = ['month_over', 'month_under'];
            const listTypes = ['neg_check', 'decimal_check', 'all_zero'];

            if (parentChild.includes(expr)) {
                _vbState.parent = params.parent || params.child || '';
                _vbState.child = params.child || '';
                _vbState.children = params.children || [];
                if (expr === 'ge_factor') _vbState.ge_factor = params.factor || 1.1;
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
            } else if (expr === 'formula') {
                _vbState.formulaParts = _formulaStringToParts(params.formula || '');
                _vbState.target = params.target || '';
            }
            buildVisualBuilder(expr);
        }

        export function toggleExprHelp() {
            const content = document.getElementById('exprHelpContent');
            const h2 = document.querySelector('#rulesExprHelp h2');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                h2.innerHTML = '&#x25BC; Expression Types Reference <span style="font-size:0.75rem;font-weight:400;color:var(--text-muted);margin-left:0.5rem;">Click to collapse</span>';
            } else {
                content.style.display = 'none';
                h2.innerHTML = '&#x25B6; Expression Types Reference <span style="font-size:0.75rem;font-weight:400;color:var(--text-muted);margin-left:0.5rem;">Click to expand</span>';
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
            if (!code || !name) { toastWarning(__('Code and Name are required.')); return; }
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
                    res = await authFetch(API() + '/rules/' + ruleEditId, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body),
                    });
                } else {
                    // Create new
                    res = await authFetch(API() + '/rules/', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body),
                    });
                }
                if (!res.ok) throw new Error(await res.text());
                closeRuleModal();
                loadRulesManager();
            } catch(e) {
                toastError('Save failed: ' + e.message);
            }
        }

        export async function deleteRule(ruleId, code) {
            if (!await confirmDestructive({ title: 'Delete Rule', message: 'Delete rule <strong>' + code + '</strong>? This cannot be undone.', okLabel: 'Delete' })) return;
            try {
                const res = await authFetch(API() + '/rules/' + ruleId, { method: 'DELETE' });
                if (!res.ok) throw new Error(await res.text());
                loadRulesManager();
            } catch(e) {
                toastError('Delete failed: ' + e.message);
            }
        }

