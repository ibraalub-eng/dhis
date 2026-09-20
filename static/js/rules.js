        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { EXPR_EXPLANATIONS, rulesManagerData, loadRulesManager } from './settings.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';
import { confirmDestructive } from './confirm-modal.js';

        let ruleEditId = null;
        let _indicatorsCache = [];
        let _vbState = {};

        // ── Edit-modal keyboard polish ─────────────────────────────
        // ESC closes the edit modal when it is open — bound in the CAPTURE
        // phase so it runs before the rules dialogs' bubble-phase ESC handler
        // (rules-manager.js). That gives proper one-press-per-layer stacking:
        // with the drawer open underneath, ESC closes the modal first and a
        // second press closes the drawer — never both at once, and never the
        // drawer while the modal on top of it stays open. The confirm dialog
        // (confirm-modal.js) owns ESC whenever it is visible, so hands off.
        if (!window._ruleEditModalEscBound) {
            document.addEventListener('keydown', function(e) {
                if (e.key !== 'Escape') return;
                const modal = document.getElementById('ruleEditModal');
                if (!modal || !modal.classList.contains('show')) return;
                if (document.getElementById('confirm-modal-overlay')?.classList.contains('cm-visible')) return;
                e.preventDefault();
                e.stopPropagation();
                closeRuleModal();
            }, true);
            window._ruleEditModalEscBound = true;
        }

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
            _vbState = { _expr: expr, parent:'', child:'', children:[], numerator:'', denominator:'', threshold:80, z_threshold:2.5, indicator:'', factor:2.0, ge_factor:1.1, codes:[], formulaParts:[], target:'', op:'=' };
        }

        // ── Formula comparison operator helpers ────────────────────
        const _FORMULA_OP_ORDER = ['=', '!=', '>', '<', '>=', '<='];

        function _formulaOpDef(op) {
            const syms = { '=': '=', '!=': '\u2260', '>': '>', '<': '<', '>=': '\u2265', '<=': '\u2264' };
            const cls = (op === '=' || op === '!=') ? 'eq' : (op === '>' || op === '>=') ? 'gt' : 'lt';
            return { sym: syms[op] || '=', cls: cls };
        }

        function _formulaRelText(op) {
            switch (op) {
                case '!=': return __('formula result \u2260 target indicator');
                case '>':  return __('formula result > target indicator');
                case '<':  return __('formula result < target indicator');
                case '>=': return __('formula result \u2265 target indicator');
                case '<=': return __('formula result \u2264 target indicator');
                default:   return __('formula result == target indicator');
            }
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
                    return JSON.stringify({ formula: _formulaPartsToString(_vbState.formulaParts || []), target: _vbState.target || '', op: _vbState.op || '=' });
                default:
                    return '{}';
            }
        }

        function _vbUpdateHidden() {
            document.getElementById('ruleEditParams').value = _vbBuildParams();
            updateRuleExprPreview();
        }

        // Live plain-language preview of the rule being built. Reads the same
        // params the save path will send, so the sentence always matches what
        // will actually be stored. Language-neutral symbol form with indicator
        // code chips; missing values render as ellipses.
        window.updateRuleExprPreview = function() {
            const box = document.getElementById('ruleExprPreview');
            const textEl = document.getElementById('ruleExprPreviewText');
            if (!box || !textEl) return;
            const expr = document.getElementById('ruleEditExpr').value;
            let p = {};
            try { p = JSON.parse(_vbBuildParams() || '{}'); } catch (e) { p = {}; }
            const chips = function(list) { return (list || []).map(c => '<span class="rule-ref-chip">' + esc(c) + '</span>').join(' + ') || '<em>…</em>'; };
            const chip = function(v) { return v ? '<span class="rule-ref-chip">' + esc(v) + '</span>' : '<em>…</em>'; };
            const num = function(v) { return (v !== undefined && v !== null && v !== '') ? esc(v) : '<em>…</em>'; };
            let cond = '';
            switch (expr) {
                case 'ge': cond = chip(p.parent) + ' ≥ ' + chips(p.children); break;
                case 'gt': cond = chip(p.parent) + ' > ' + chips(p.children); break;
                case 'ge_factor': cond = chip(p.parent) + ' × ' + num(p.factor) + ' ≥ ' + chips(p.children); break;
                case 'eq': cond = chip(p.parent) + ' = ' + chips(p.children); break;
                case 'le': cond = chip(p.child) + ' ≤ ' + chip(p.parent); break;
                case 'lt': cond = chip(p.child) + ' < ' + chip(p.parent); break;
                case 'le_sum': cond = chip(p.child) + ' ≥ ' + chips(p.children); break;
                case 'benchmark_rate': cond = '(' + chip(p.num_code) + ' ÷ ' + chip(p.den_code) + ') × 100 ≤ ' + num(p.threshold) + '%'; break;
                case 'benchmark_low_rate': cond = '(' + chip(p.num_code) + ' ÷ ' + chip(p.den_code) + ') × 100 ≥ ' + num(p.threshold) + '%'; break;
                case 'cross_hospital_rate': cond = '|z(' + chip(p.num_code) + ' ÷ ' + chip(p.den_code) + ')| ≤ ' + num(p.z_threshold); break;
                case 'month_over': cond = chip(p.code) + ' ≤ ' + num(p.factor) + ' × ' + __('previous month'); break;
                case 'month_under': cond = chip(p.code) + ' ≥ ' + num(p.factor) + ' × ' + __('previous month'); break;
                case 'neg_check': cond = chips(p.codes) + ' ≥ 0'; break;
                case 'decimal_check': cond = chips(p.codes) + ' ∈ ℤ'; break;
                case 'missing': cond = chip(p.code) + ' ' + __('has a value'); break;
                case 'all_zero': cond = chips(p.codes) + ' ≠ 0 (' + __('at least one') + ')'; break;
                case 'formula': cond = '<span class="rule-ref-chip" style="font-family:Consolas,monospace;">' + esc(p.formula || '…') + '</span> ' + esc(p.op || '=') + ' ' + chip(p.target); break;
                default: cond = '';
            }
            if (!cond) { box.style.display = 'none'; return; }
            textEl.innerHTML = cond;
            box.style.display = 'block';
        };

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
            const op = _vbState.op || '=';
            const def = _formulaOpDef(op);
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
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + def.cls + '" id="vb_op_symbol">' + def.sym + '</span> ';
            html += '<select id="vb_op_select" style="font-size:0.78rem;padding:0.15rem 0.3rem;background:var(--bg-elevated);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;" onchange="_vbOnOpChange()" title="' + __('Comparison operator') + '">';
            html += _FORMULA_OP_ORDER.map(function(o) {
                return '<option value="' + o + '"' + (o === op ? ' selected' : '') + '>' + _formulaRelText(o) + '</option>';
            }).join('');
            html += '</select></div>';
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

        export function _vbOnOpChange() {
            const sel = document.getElementById('vb_op_select');
            if (!sel) return;
            _vbState.op = sel.value;
            _vbUpdateHidden();
            const def = _formulaOpDef(_vbState.op);
            const symEl = document.getElementById('vb_op_symbol');
            if (symEl) { symEl.textContent = def.sym; symEl.className = 'vb-relation-symbol ' + def.cls; }
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
            updateRuleNameSuggestion();
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
            updateRuleExprPreview();
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
                _vbState.op = params.op || '=';
            }
            buildVisualBuilder(expr);
        }

        // ── Rule-name suggestion (New Rule modal) ──────────────────
        // Builds a human-readable name from the indicator names the user has
        // dropped into the visual builder, matching the seeded catalog style
        // (e.g. "Total Deliveries >= Normal Vaginal + Assisted Vaginal + ...").
        export function suggestRuleName() {
            const expr = _vbState._expr;
            if (!expr) return '';
            const indName = (code) => {
                if (!code) return '';
                const ind = _indicatorsCache.find(i => i.code === code);
                return ind ? ind.name : code;
            };
            const joinNames = (codes) => (codes || []).map(indName).filter(Boolean).join(' + ');
            const listNames = (codes) => (codes || []).map(indName).filter(Boolean).join(', ');
            const parent = indName(_vbState.parent);
            const child = indName(_vbState.child);
            switch (expr) {
                case 'ge':
                case 'gt':
                    if (!_vbState.parent || !(_vbState.children || []).length) return '';
                    return parent + (expr === 'gt' ? ' > ' : ' >= ') + joinNames(_vbState.children);
                case 'ge_factor':
                    if (!_vbState.parent || !(_vbState.children || []).length) return '';
                    return joinNames(_vbState.children) + ' <= ' + (Math.round((parseFloat(_vbState.ge_factor) || 1) * 100)) + '% of ' + parent;
                case 'eq':
                    if (!_vbState.parent || !(_vbState.children || []).length) return '';
                    return joinNames(_vbState.children) + ' = ' + parent;
                case 'le':
                case 'lt':
                    if (!_vbState.child || !_vbState.parent) return '';
                    return child + (expr === 'lt' ? ' < ' : ' <= ') + parent;
                case 'le_sum':
                    if (!_vbState.child || !(_vbState.children || []).length) return '';
                    return child + ' >= ' + joinNames(_vbState.children);
                case 'benchmark_rate':
                case 'benchmark_low_rate':
                    if (!_vbState.numerator || !_vbState.denominator) return '';
                    return indName(_vbState.numerator) + ' Rate ' + (expr === 'benchmark_low_rate' ? '< ' : '> ') + (parseFloat(_vbState.threshold) || (expr === 'benchmark_low_rate' ? 10 : 80)) + '% alert';
                case 'cross_hospital_rate':
                    if (!_vbState.numerator || !_vbState.denominator) return '';
                    return indName(_vbState.numerator) + '/' + indName(_vbState.denominator) + ' rate outlier across hospitals';
                case 'month_over':
                case 'month_under':
                    if (!_vbState.indicator) return '';
                    return indName(_vbState.indicator) + (expr === 'month_over' ? ' > ' : ' < ') + (expr === 'month_over'
                        ? (parseFloat(_vbState.factor) || 2) + 'x previous month'
                        : (Math.round((parseFloat(_vbState.factor) || 0.5) * 100)) + '% of previous month');
                case 'neg_check':
                case 'decimal_check':
                case 'all_zero':
                    if (!(_vbState.codes || []).length) return '';
                    const label = expr === 'neg_check' ? 'Negative values: '
                        : expr === 'decimal_check' ? 'Decimal values: '
                        : 'All zero check: ';
                    return label + listNames(_vbState.codes);
                case 'missing':
                    if (!_vbState.indicator) return '';
                    return 'Missing ' + indName(_vbState.indicator);
                case 'formula':
                    if (!_vbState.target) return '';
                    const op = _formulaOpDef(_vbState.op || '=').sym;
                    return 'Formula result ' + op + ' ' + indName(_vbState.target);
                default:
                    return '';
            }
        }

        function updateRuleNameSuggestion() {
            const wrap = document.getElementById('ruleNameSuggestionWrap');
            const preview = document.getElementById('ruleNameSuggestion');
            if (!wrap || !preview) return;
            // Only ever suggest names for brand-new rules — never overwrite an
            // existing rule's hand-written name while editing.
            if (ruleEditId) { wrap.style.display = 'none'; return; }
            const s = suggestRuleName();
            if (s) {
                preview.textContent = s;
                wrap.style.display = 'flex';
            } else {
                wrap.style.display = 'none';
            }
        }

        export function applyRuleNameSuggestion() {
            const nameInput = document.getElementById('ruleEditName');
            if (!nameInput || ruleEditId) return;
            const s = suggestRuleName();
            if (!s) return;
            nameInput.value = s;
            updateRuleNameSuggestion();
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
            _populateRuleTestSelects();
        }

        function _populateRuleTestSelects() {
            const hsel = document.getElementById('ruleTestHospital');
            const msel = document.getElementById('ruleTestMonth');
            const rsel = document.getElementById('ruleTestResult');
            if (!hsel || !msel) return;
            if (hsel.options.length <= 1) {
                apiGet('/hospitals/').then(data => {
                    const list = data.value || data || [];
                    hsel.innerHTML = '<option value="">Select hospital</option>' + list.map(h => '<option value="' + h.id + '">' + h.name + '</option>').join('');
                }).catch(() => {});
            }
            if (msel.options.length <= 1) {
                apiGet('/analysis/months').then(months => {
                    msel.innerHTML = '<option value="">Select month</option>' + months.map(m => '<option value="' + m + '">' + m + '</option>').join('');
                }).catch(() => {});
            }
            if (rsel) rsel.innerHTML = '';
        }

        function _wireHospitalRowClicks(container, ruleCode) {
            container.querySelectorAll('.rule-test-hospital-row').forEach(function(row) {
                row.addEventListener('click', function() {
                    const hid = this.dataset.hid;
                    const hname = this.dataset.hname;
                    const detailEl = container.querySelector('.rule-test-hospital-detail[data-hid="' + hid + '"]');
                    if (!detailEl) return;
                    if (detailEl.style.display !== 'none') {
                        detailEl.style.display = 'none';
                        this.querySelector('span').textContent = hname + ' ➤';
                        return;
                    }
                    detailEl.style.display = '';
                    detailEl.innerHTML = '<span class="spinner"></span>';
                    authFetch(API() + '/rules/failures?rule_code=' + encodeURIComponent(ruleCode) + '&hospital_id=' + hid)
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            const months = (d.months || []);
                            if (!months.length) {
                                detailEl.innerHTML = '<em>No recorded failures for this rule yet.</em>';
                                return;
                            }
                            let mhtml = '<div style="font-weight:600;color:var(--text-secondary);margin-bottom:2px;">Failed in ' + months.length + ' month(s):</div>';
                            months.forEach(function(m) {
                                const hospInMonth = (m.hospitals || []).find(function(x) { return x.hospital_id == hid; });
                                const details = hospInMonth && hospInMonth.details ? ' — ' + hospInMonth.details : '';
                                mhtml += '<div style="padding:1px 0;"><strong style="color:var(--accent-red);">' + m.month + '</strong>' + details + '</div>';
                            });
                            detailEl.innerHTML = mhtml;
                            row.querySelector('span').textContent = hname + ' ▾';
                        })
                        .catch(function() {
                            detailEl.innerHTML = '<em>Could not load failure history.</em>';
                        });
                });
            });
        }

        export async function testRuleForHospital() {
            const code = document.getElementById('ruleEditCode').value.trim();
            const name = document.getElementById('ruleEditName').value.trim();
            const hid = document.getElementById('ruleTestHospital').value;
            const month = document.getElementById('ruleTestMonth').value;
            const rsel = document.getElementById('ruleTestResult');
            if (!rsel) return;
            if (!code || !name) { rsel.innerHTML = '<span style="color:var(--accent-orange);">Set Code and Name first.</span>'; return; }
            const scopeLabel = hid && month ? 'single hospital' : hid ? 'all hospitals, latest month' : month ? 'all hospitals' : 'all hospitals, latest month';
            rsel.innerHTML = '<span class="spinner"></span> Evaluating against ' + scopeLabel + '...';
            const paramsRaw = _vbBuildParams();
            const body = {
                code: code,
                name: name,
                rule_type: document.getElementById('ruleEditType').value,
                severity: document.getElementById('ruleEditSeverity').value,
                expression_type: document.getElementById('ruleEditExpr').value,
                params: paramsRaw,
            };
            if (hid) body.hospital_id = hid;
            if (month) body.month = month;
            try {
                const res = await authFetch(API() + '/rules/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                const d = await res.json();
                if (!res.ok) { rsel.innerHTML = '<span style="color:var(--accent-red);">' + __(d.detail || 'Test failed') + '</span>'; return; }
                const ok = d.status === 'PASS';
                const color = ok ? 'var(--accent-green)' : d.status === 'FAIL' ? 'var(--accent-red)' : 'var(--accent-orange)';
                let html = '<div style="padding:0.4rem 0.6rem;border:1px solid ' + color + '66;border-radius:4px;background:' + color + '11;">';
                if (d.scope === 'all') {
                    const barMax = d.total || 1;
                    const passedPct = Math.round(((d.passed || 0) / barMax) * 100);
                    const failedPct = Math.round(((d.failed || 0) / barMax) * 100);
                    const ndPct = 100 - passedPct - failedPct;
                    html += '<strong style="color:' + color + ';">' + d.status + '</strong> <span style="color:var(--text-secondary);font-size:0.72rem;">' + d.month + '</span><br>' +
                        '<span style="color:var(--text-secondary);font-size:0.74rem;">' + __(d.details) + '</span>';
                    html += '<div style="margin-top:0.3rem;display:flex;height:10px;border-radius:4px;overflow:hidden;">' +
                        '<div style="width:' + passedPct + '%;background:var(--accent-green);"></div>' +
                        '<div style="width:' + failedPct + '%;background:var(--accent-red);"></div>' +
                        '<div style="width:' + ndPct + '%;background:var(--bg-surface-hover);"></div></div>';
                    html += '<div style="margin-top:0.25rem;font-size:0.68rem;display:flex;gap:0.7rem;">' +
                        '<span style="color:var(--accent-green);">' + (d.passed || 0) + ' passed</span>' +
                        '<span style="color:var(--accent-red);">' + (d.failed || 0) + ' failed</span>' +
                        '<span style="color:var(--text-muted);">' + (d.no_data || 0) + ' no data</span>' +
                        '</div>';
                    if (d.hospitals && d.hospitals.length) {
                        html += '<div style="margin-top:0.4rem;max-height:150px;overflow-y:auto;font-size:0.7rem;border-top:1px solid ' + color + '33;padding-top:0.3rem;">';
                        const maxShow = 50;
                        d.hospitals.forEach(function(h) {
                            const hs = h.status || 'NO_DATA';
                            const hc = hs === 'PASS' ? 'var(--accent-green)' : hs === 'FAIL' ? 'var(--accent-red)' : 'var(--text-muted)';
                            html += '<div class="rule-test-hospital-row" data-hid="' + h.hospital_id + '" data-hname="' + esc(h.hospital) + '" data-mstatus="' + hs + '" style="display:flex;justify-content:space-between;align-items:center;padding:3px 4px;border-radius:3px;cursor:pointer;" title="Click to see failed months">' +
                                '<span style="font-weight:600;color:var(--accent-blue);">' + esc(h.hospital) + ' ➤</span>' +
                                '<span style="color:' + hc + ';font-weight:600;margin-left:0.5rem;">' + hs + '</span></div>' +
                                '<div class="rule-test-hospital-detail" data-hid="' + h.hospital_id + '" style="display:none;padding:3px 4px 6px;font-size:0.66rem;color:var(--text-muted);"></div>';
                        });
                        if (d.hospitals.length > maxShow) html += '<div style="color:var(--text-muted);">... and ' + (d.hospitals.length - maxShow) + ' more</div>';
                        html += '</div>';
                    }
                } else {
                    html += '<strong style="color:' + color + ';">' + d.status + '</strong> <span style="color:var(--text-secondary);font-size:0.72rem;">' + (d.hospital || '') + ' · ' + d.month + '</span><br>' +
                        '<span style="color:var(--text-secondary);font-size:0.74rem;">' + __(d.details) + '</span>';
                    const hospResult = (d.hospitals && d.hospitals[0]) || {};
                    const rvs = hospResult.ref_values || d.ref_values || {};
                    const keys = Object.keys(rvs);
                    if (keys.length) {
                        html += '<div style="margin-top:0.3rem;font-size:0.7rem;color:var(--text-secondary);"><strong>Indicator values:</strong> ';
                        keys.forEach(function(k) {
                            html += '<span style="margin-right:0.5rem;">' + k + ' (' + __(rvs[k].name) + ') = <strong>' + rvs[k].value + '</strong></span>';
                        });
                        html += '</div>';
                    }
                }
                html += '</div>';
                rsel.innerHTML = html;
                _wireHospitalRowClicks(rsel, body.code);
            } catch(e) {
                rsel.innerHTML = '<span style="color:var(--accent-red);">' + __(e.message || 'Test failed') + '</span>';
            }
        }

        export async function validateAndSaveRule() {
            const code = document.getElementById('ruleEditCode').value.trim();
            const name = document.getElementById('ruleEditName').value.trim();
            if (!code || !name) { toastWarning(__('Code and Name are required.')); return; }
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
            if (ruleEditId) body.exclude_id = ruleEditId;
            try {
                const res = await authFetch(API() + '/rules/validate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                const d = await res.json();
                const errors = d.errors || [];
                const warnings = d.warnings || [];
                if (errors.length) {
                    toastError(errors[0]);
                    return;
                }
                if (warnings.length) {
                    if (!await confirmDestructive({ title: 'Possible Conflicts', message: warnings[0], okLabel: 'Save Anyway' })) return;
                }
                saveRule();
            } catch(e) {
                toastError('Validation failed: ' + e.message);
            }
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

