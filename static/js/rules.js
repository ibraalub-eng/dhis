        import { API } from './api.js';
        import { __ } from './i18n.js';
        import { EXPR_EXPLANATIONS, rulesManagerData, loadRulesManager } from './settings.js';
import { toastSuccess, toastError, toastWarning, toastInfo } from './toast.js';
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
            const isSingle = ['vb_zone_parent','vb_zone_child','vb_zone_indicator','vb_zone_target'].includes(zoneId);
            if (isSingle) {
                _vbState[zoneId.replace('vb_zone_', '')] = code;
            } else if (zoneId === 'vb_zone_children' || zoneId === 'vb_zone_codes'
                    || zoneId === 'vb_zone_left' || zoneId === 'vb_zone_right') {
                const key = {vb_zone_children:'children', vb_zone_codes:'codes',
                             vb_zone_left:'leftCodes', vb_zone_right:'rightCodes'}[zoneId];
                if (!_vbState[key]) _vbState[key] = [];
                if (!_vbState[key].includes(code)) _vbState[key].push(code);
            }
            _vbRebuild();
        }

        export function _vbRemoveFromZone(zoneId, code) {
            const key = {vb_zone_children:'children', vb_zone_codes:'codes',
                         vb_zone_left:'leftCodes', vb_zone_right:'rightCodes'}[zoneId]
                || zoneId.replace('vb_zone_', '');
            if (['children', 'codes', 'leftCodes', 'rightCodes'].includes(key)) {
                if (_vbState[key]) _vbState[key] = _vbState[key].filter(c => c !== code);
            } else {
                _vbState[key] = '';
            }
            _vbRebuild();
        }

        function _vbStateReset(expr) {
            _vbState = { _expr: expr, parent:'', child:'', children:[], indicator:'', factor:2.0, ge_factor:1.1, codes:[], formulaParts:[], rhsParts:[], target:'', op:'=', leftCodes:[], rightCodes:[], leftAgg:'single', rightAgg:'single', compareOp:'>=', compareFactor:1 };
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
                case '!=': return __('left side \u2260 right side');
                case '>':  return __('left side > right side');
                case '<':  return __('left side < right side');
                case '>=': return __('left side \u2265 right side');
                case '<=': return __('left side \u2264 right side');
                default:   return __('left side = right side');
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

        // Parses an expression the way the engine does: {code} references,
        // "Name (code)" references (the name is a dropped label, so a name may
        // contain digits and signs like "Stillbirths >24w (7)"), numbers,
        // + - * / and () / [] grouping. Unicode −, ×, ÷ normalize to - * /.
        function _formulaStringToParts(str) {
            var parts = [];
            var i = 0;
            var text = String(str || '')
                .replace(/\u2212/g, '-').replace(/\u2013/g, '-').replace(/\u2014/g, '-')
                .replace(/\u00d7/g, '*').replace(/\u00f7/g, '/');
            while (i < text.length) {
                var ch = text[i];
                if (ch === ' ' || ch === '\t' || ch === '\u00a0') { i++; continue; }
                if (ch === '{') {
                    var j = text.indexOf('}', i + 1);
                    if (j === -1) break;
                    parts.push({ t: 'ind', code: text.slice(i + 1, j).trim() });
                    i = j + 1;
                } else if ('+-*/()[]'.includes(ch)) {
                    parts.push({ t: 'op', op: ch });
                    i++;
                } else if (ch >= '0' && ch <= '9') {
                    var start = i;
                    while (i < text.length && ((text[i] >= '0' && text[i] <= '9') || text[i] === '.')) i++;
                    parts.push({ t: 'num', val: parseFloat(text.slice(start, i)) });
                } else {
                    // "Babies from multiples (6.e)" → the code in parentheses.
                    var k = i;
                    while (k < text.length && '+-*/()[]{}'.indexOf(text[k]) === -1) k++;
                    var m = k;
                    while (m < text.length && /\s/.test(text[m])) m++;
                    var end = text[m] === '(' ? text.indexOf(')', m + 1) : -1;
                    if (end !== -1) {
                        var inner = text.slice(m + 1, end).trim();
                        if (inner && !/[\s()+\-*/]/.test(inner)) {
                            parts.push({ t: 'ind', code: inner });
                            i = end + 1;
                            continue;
                        }
                    }
                    i = k > i ? k : i + 1;
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
                case 'gt':
                case 'parent_le':
                case 'parent_lt':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [] });
                case 'ge_factor':
                    return JSON.stringify({ parent: _vbState.parent || '', children: _vbState.children || [], factor: parseFloat(_vbState.ge_factor) || 1.0 });
                case 'le':
                case 'lt':
                    return JSON.stringify({ child: _vbState.child || '', parent: _vbState.parent || '' });
                case 'le_sum':
                    return JSON.stringify({ child: _vbState.child || '', children: _vbState.children || [] });
                case 'month_over':
                case 'month_under':
                    return JSON.stringify({ code: _vbState.indicator || '', factor: parseFloat(_vbState.factor) || 1.0 });
                case 'compare': {
                    const side = function(codes, savedAgg) {
                        return { codes: codes || [], agg: (codes && codes.length > 1) ? 'sum' : (savedAgg || 'single') };
                    };
                    const params = {
                        left: side(_vbState.leftCodes, _vbState.leftAgg),
                        right: side(_vbState.rightCodes, _vbState.rightAgg),
                        op: _vbState.compareOp || '>=',
                    };
                    const factor = parseFloat(_vbState.compareFactor) || 1;
                    if (factor !== 1) params.factor = factor;
                    return JSON.stringify(params);
                }
                case 'trend': {
                    const direction = _vbState.direction || 'over';
                    const fallback = direction === 'under' ? 0.5 : 2.0;
                    return JSON.stringify({
                        direction: direction,
                        factor: parseFloat(_vbState.factor) || fallback,
                        codes: _vbState.indicator ? [_vbState.indicator] : [],
                    });
                }
                case 'neg_check':
                case 'decimal_check':
                case 'all_zero':
                    return JSON.stringify({ codes: _vbState.codes || [] });
                case 'missing':
                    return JSON.stringify({ code: _vbState.indicator || '' });
                case 'value_check':
                    // A value_check is a list of checks, not one relation, so it
                    // is edited as JSON. The textarea is the source of truth and
                    // is stored verbatim.
                    return _vbState.rawParams || '{}';
                case 'formula': {
                    // A single indicator on the right keeps the legacy `target`
                    // param (every existing formula rule and the drawer read it);
                    // any wider expression is stored as `rhs`.
                    const rhsParts = _vbState.rhsParts || [];
                    const rhs = _formulaPartsToString(rhsParts);
                    const singleTarget = (rhsParts.length === 1 && rhsParts[0].t === 'ind') ? rhsParts[0].code : '';
                    const params = {
                        formula: _formulaPartsToString(_vbState.formulaParts || []),
                        target: singleTarget || _vbState.target || '',
                        op: _vbState.op || '=',
                    };
                    if (rhs && !singleTarget) params.rhs = rhs;
                    return JSON.stringify(params);
                }
                default:
                    return '{}';
            }
        }

        // ── Nested-children guard ──────────────────────────────────────
        // Indicator codes are dotted paths (10.a.1.2), so ancestry is decidable
        // from the code alone. Summing a parent together with its own
        // descendants counts the same cases several times, which silently
        // inflates the sum and makes the rule mean something other than what
        // the chip list shows. Surface it instead of quietly accepting it.
        export function _vbNestedChildren(codes) {
            const list = (codes || []).filter(Boolean);
            const out = [];
            for (let i = 0; i < list.length; i++) {
                for (let j = 0; j < list.length; j++) {
                    if (i === j) continue;
                    if (list[j].indexOf(list[i] + '.') === 0) out.push([list[i], list[j]]);
                }
            }
            return out;
        }

        function _vbNestingWarningHTML(codes) {
            const pairs = _vbNestedChildren(codes);
            if (!pairs.length) return '';
            const uniq = [];
            pairs.forEach(function(p) { if (uniq.indexOf(p[0]) === -1) uniq.push(p[0]); });
            return '<div style="margin-top:0.4rem;padding:0.4rem 0.55rem;border:1px solid var(--accent-orange);'
                + 'border-radius:6px;background:var(--accent-orange)14;font-size:0.72rem;color:var(--text-primary);">'
                + '<strong>' + __('Warning:') + '</strong> '
                + __('these indicators contain a parent and its own children, so they will be counted more than once in the sum:')
                + ' <code>' + uniq.map(esc).join('</code>, <code>') + '</code>. '
                + __('Use either the parent or its children, not both.')
                + '</div>';
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
            // Indicator chips reuse the drawer's clickable chip (jumps to the
            // Indicator Tree) when rules-manager.js has loaded; fall back to a
            // plain chip so the preview still renders on a stale module chain.
            const chipOf = function(v) {
                if (!v) return '<em>…</em>';
                return (typeof window._ruleChip === 'function') ? window._ruleChip(v) : '<span class="rule-ref-chip">' + esc(v) + '</span>';
            };
            const chips = function(list) { return (list || []).map(chipOf).join(' + ') || '<em>…</em>'; };
            const chip = function(v) { return chipOf(v); };
            const num = function(v) { return (v !== undefined && v !== null && v !== '') ? esc(v) : '<em>…</em>'; };
            let cond = '';
            switch (expr) {
                case 'ge': cond = chip(p.parent) + ' ≥ ' + chips(p.children); break;
                case 'gt': cond = chip(p.parent) + ' > ' + chips(p.children); break;
                case 'parent_le': cond = chip(p.parent) + ' ≤ ' + chips(p.children); break;
                case 'parent_lt': cond = chip(p.parent) + ' < ' + chips(p.children); break;
                case 'ge_factor': cond = chip(p.parent) + ' × ' + num(p.factor) + ' ≥ ' + chips(p.children); break;
                case 'eq': cond = chip(p.parent) + ' = ' + chips(p.children); break;
                case 'le': cond = chip(p.child) + ' ≤ ' + chip(p.parent); break;
                case 'lt': cond = chip(p.child) + ' < ' + chip(p.parent); break;
                case 'le_sum': cond = chip(p.child) + ' ≥ ' + chips(p.children); break;
                case 'month_over': cond = chip(p.code) + ' ≤ ' + num(p.factor) + ' × ' + __('previous month'); break;
                case 'month_under': cond = chip(p.code) + ' ≥ ' + num(p.factor) + ' × ' + __('previous month'); break;
                case 'trend': cond = chips(p.codes) + ' ' + (p.direction === 'under' ? '≥' : '≤') + ' ' + num(p.factor) + ' × ' + __('previous month'); break;
                case 'compare': {
                    const lhs = chips((p.left && p.left.codes) || []);
                    const rhs = chips((p.right && p.right.codes) || []);
                    const factor = parseFloat(p.factor) || 1;
                    cond = (factor !== 1 ? num(factor) + ' × ' : '') + lhs
                        + ' ' + (p.op === '!=' ? '≠' : (p.op || '>=')) + ' ' + rhs;
                    break;
                }
                case 'neg_check': cond = chips(p.codes) + ' ≥ 0'; break;
                case 'decimal_check': cond = chips(p.codes) + ' ∈ ℤ'; break;
                case 'missing': cond = chip(p.code) + ' ' + __('has a value'); break;
                case 'all_zero': cond = chips(p.codes) + ' ≠ 0 (' + __('at least one') + ')'; break;
                case 'formula': {
                    const opSym = _formulaOpDef(p.op || '=').sym;
                    const side = function(text) {
                        return '<span class="rule-ref-chip" style="font-family:Consolas,monospace;">' + esc(text || '…') + '</span>';
                    };
                    cond = side(p.formula) + ' <strong style="color:var(--text-primary);">' + esc(opSym) + '</strong> ' + side(p.rhs || p.target);
                    break;
                }
                default: cond = '';
            }
            if (!cond) { box.style.display = 'none'; return; }
            textEl.innerHTML = cond;
            box.style.display = 'block';
            // Warn about parent/child nesting in any summed indicator list. Every
            // sum-based expression (ge, gt, eq, ge_factor, parent_le, le_sum)
            // reads `children`; the set-based ones (all_zero, neg_check,
            // decimal_check) read `codes`. Check whichever the current
            // expression actually populates.
            const lists = [p.children, p.codes].filter(function(l) { return Array.isArray(l) && l.length; });
            const warned = lists.find(function(l) { return _vbNestedChildren(l).length; });
            let warnEl = document.getElementById('ruleExprPreviewWarn');
            if (!warnEl) {
                warnEl = document.createElement('div');
                warnEl.id = 'ruleExprPreviewWarn';
                box.appendChild(warnEl);
            }
            const warnHTML = _vbNestingWarningHTML(warned);
            if (warnEl.innerHTML !== warnHTML) warnEl.innerHTML = warnHTML;
        };

        // ── Render builders per category ───────────────────────────

        function _buildVBParentChild(expr) {
            const symbols = { ge: '\u2265', eq: '=', le: '\u2264', le_sum: '\u2265', parent_le: '\u2264', parent_lt: '<', gt: '>', lt: '<', ge_factor: '\u2265' };
            const symbol = symbols[expr] || '?';
            const geClass = ['ge', 'le_sum', 'ge_factor'].includes(expr) ? 'ge' : ['gt', 'lt', 'parent_lt'].includes(expr) ? (expr === 'gt' ? 'gt' : 'lt') : expr === 'eq' ? 'eq' : 'le';
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();

            if (expr === 'ge' || expr === 'eq' || expr === 'gt' || expr === 'ge_factor' || expr === 'parent_le' || expr === 'parent_lt') {
                let relText;
                if (expr === 'ge') relText = __('parent \u2265 sum(children)');
                else if (expr === 'gt') relText = __('parent > sum(children)');
                else if (expr === 'ge_factor') relText = __('parent \u00d7 factor \u2265 sum(children)');
                else if (expr === 'parent_le') relText = __('parent \u2264 sum(children)');
                else if (expr === 'parent_lt') relText = __('parent < sum(children)');
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

        function _buildVBTrend(expr) {
            const isTrend = expr === 'trend';
            const direction = isTrend ? (_vbState.direction || 'over')
                : (expr === 'month_over' ? 'over' : 'under');
            _vbState.direction = direction;
            const isOver = direction !== 'under';
            const cssClass = isOver ? 'gt' : 'lt';
            const symbol = isOver ? '>' : '<';
            const factor = parseFloat(_vbState.factor) || (isOver ? 2.0 : 0.5);
            _vbState.factor = factor;
            let relText = isOver ? __('current > factor \u00d7 previous') : __('current < factor \u00d7 previous');

            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            if (isTrend) {
                html += '<div class="vb-row"><span class="vb-label">' + __('Direction') + '</span>';
                html += '<select id="vb_direction_input" onchange="_vbOnDirectionChange()">';
                html += '<option value="over"' + (isOver ? ' selected' : '') + '>' + __('over — FAIL above factor × previous') + '</option>';
                html += '<option value="under"' + (!isOver ? ' selected' : '') + '>' + __('under — FAIL below factor × previous') + '</option>';
                html += '</select></div>';
            }
            html += _vbZoneHTML('vb_zone_indicator', __('Indicator'), _vbState.indicator ? [_vbState.indicator] : [], false, __('Drop indicator here'));
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + cssClass + '">' + symbol + '</span> ' + relText + '</div>';
            html += '<div class="vb-row"><span class="vb-label">' + __('Factor') + '</span>';
            html += '<input type="number" class="vb-num-input" id="vb_factor_input" value="' + factor + '" min="0" max="100" step="0.1" onchange="_vbOnFactorChange()"></div>';
            html += '</div>';
            return html;
        }

        window._vbOnDirectionChange = function() {
            const field = document.getElementById('vb_direction_input');
            if (!field) return;
            _vbState.direction = field.value === 'under' ? 'under' : 'over';
            // Each direction has its own natural threshold (2x vs half).
            if (!parseFloat(_vbState.factor)) {
                _vbState.factor = _vbState.direction === 'under' ? 0.5 : 2.0;
            }
            buildVisualBuilder(_vbState._expr);
            updateRuleExprPreview();
        };

        function _buildVBList(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.4rem;">' + (expr === 'neg_check' ? __('Negative values check') : expr === 'decimal_check' ? __('Decimal values check') : __('All zero check')) + '</div>';
            html += _vbZoneHTML('vb_zone_codes', __('Indicators'), _vbState.codes || [], true, __('Drop indicators here'));
            html += '</div>';
            return html;
        }

        // value_check spans several checks, so it is edited as JSON rather than
        // as one relation. The textarea keeps every check intact (a migrated
        // rule opened for edit must not lose its params).
        function _buildVBJson(expr) {
            const raw = _vbState.rawParams || '{\n  "checks": [\n    {"kind": "negative", "codes": ["2"]}\n  ]\n}';
            let html = '<div class="vb-card">';
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin-bottom:0.4rem;">' + __('Value checks (JSON)') + '</div>';
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-bottom:0.4rem;">' + __('Checks run in order; kinds: negative, decimal, missing, all_zero.') + '</div>';
            html += '<textarea id="vbJsonParams" style="width:100%;min-height:150px;font-family:Consolas,monospace;font-size:0.75rem;background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:6px;padding:0.5rem;" oninput="_vbOnJsonParams()">' + esc(raw) + '</textarea>';
            html += '</div>';
            return html;
        }

        window._vbOnJsonParams = function() {
            const field = document.getElementById('vbJsonParams');
            if (!field) return;
            _vbState.rawParams = field.value;
            _vbUpdateHidden();
        };

        // compare is one relation between two operands, each a single indicator
        // or a list that is summed. Legacy comparison rules are converted to
        // this shape when they are opened for editing.
        function _buildVBCompare() {
            const op = _vbState.compareOp || '>=';
            const factor = parseFloat(_vbState.compareFactor) || 1;
            const opClass = (op === '=' || op === '!=') ? 'eq' : ((op === '>' || op === '>=') ? 'ge' : 'le');
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += '<div class="vb-row" style="margin-bottom:0.4rem;"><span class="vb-label">' + __('Operator') + '</span>';
            html += '<select id="vb_compare_op" onchange="_vbOnCompareOp()">';
            ['=', '!=', '>', '>=', '<', '<='].forEach(function(o) {
                html += '<option value="' + o + '"' + (op === o ? ' selected' : '') + '>' + o + '</option>';
            });
            html += '</select>';
            html += '<span class="vb-label" style="margin-left:0.6rem;">' + __('Factor') + '</span>';
            html += '<input type="number" class="vb-num-input" id="vb_compare_factor" value="' + factor + '" min="0.01" max="10" step="0.01" onchange="_vbOnCompareFactor()">';
            html += '</div>';
            html += _vbZoneHTML('vb_zone_left', __('Left side'), _vbState.leftCodes || [], true, __('Drop the left indicator(s) here'));
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + opClass + '">' + op + '</span> ' + __('left side compared with the right side') + '</div>';
            html += _vbZoneHTML('vb_zone_right', __('Right side'), _vbState.rightCodes || [], true, __('Drop the right indicator(s) here'));
            html += '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.35rem;">'
                + __('One indicator on a side is read as it is; two or more are summed.') + '</div>';
            html += '</div>';
            return html;
        }

        window._vbOnCompareOp = function() {
            const field = document.getElementById('vb_compare_op');
            if (!field) return;
            _vbState.compareOp = field.value;
            _vbUpdateHidden();
            buildVisualBuilder(_vbState._expr);
        };

        window._vbOnCompareFactor = function() {
            const field = document.getElementById('vb_compare_factor');
            if (!field) return;
            _vbState.compareFactor = parseFloat(field.value) || 1;
            _vbUpdateHidden();
        };

        function _buildVBSingle(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            html += _vbZoneHTML('vb_zone_indicator', __('Indicator'), _vbState.indicator ? [_vbState.indicator] : [], false, __('Drop indicator here'));
            html += '</div>';
            return html;
        }

        // One side of a formula rule: dropzone + operator toolbar + a text field
        // for typing or pasting the whole expression, e.g.
        // "Live births (6) + Stillbirths >24w (7)".
        function _vbFormulaSideHTML(side, parts) {
            const isRhs = side === 'rhs';
            const glyphs = { '(': '(', ')': ')', '+': '+', '-': '&minus;', '*': '&times;', '/': '&divide;' };
            let html = '<div class="vb-formula-side" data-side="' + side + '">';
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--text-secondary);margin:0.35rem 0 0.25rem;">'
                + (isRhs ? __('Right side expression') : __('Left side expression')) + '</div>';
            html += '<div class="vb-dropzone" id="vb_zone_formula_' + side + '" data-side="' + side + '"'
                + ' ondragover="_vbDragOver(event)" ondragenter="_vbDragEnter(event)" ondragleave="_vbDragLeave(event)" ondrop="_vbDropFormula(event)">';
            html += '<div class="vb-dropzone-label">' + __('Drop indicators here')
                + ' <span style="font-weight:400;color:var(--text-muted);font-size:0.7rem;">(' + __('or use buttons below') + ')</span></div>';
            for (let pi = 0; pi < parts.length; pi++) {
                const p = parts[pi];
                const del = '<button class="vb-chip-del" onclick="_vbFormulaRemove(' + pi + ',\'' + side + '\')">\u00d7</button>';
                if (p.t === 'ind') {
                    const ind = _indicatorsCache.find(function(x){return x.code === p.code;});
                    const nm = ind ? ind.name : p.code;
                    html += '<span class="vb-drag-chip vb-chip-ind" draggable="true" ondragstart="_vbDragStart(event,\'' + p.code + '\')"><span class="vb-chip-code">' + p.code + '</span> <span class="vb-chip-name">' + nm + '</span> ' + del + '</span>';
                } else if (p.t === 'num') {
                    html += '<span class="vb-drag-chip vb-chip-num"><span class="vb-chip-code">' + p.val + '</span> ' + del + '</span>';
                } else {
                    html += '<span class="vb-drag-chip vb-chip-op"><span class="vb-chip-code">' + p.op + '</span> ' + del + '</span>';
                }
            }
            html += '</div>';
            html += '<div class="vb-formula-toolbar">';
            ['(', ')', '+', '-', '*', '/'].forEach(function(o) {
                html += '<button class="vb-formula-btn" onclick="_vbFormulaAddOp(\'' + o + '\',\'' + side + '\')" title="' + esc(o) + '">' + glyphs[o] + '</button>';
            });
            html += '<span style="margin-left:0.4rem;display:inline-flex;align-items:center;gap:0.25rem;"><input type="number" id="vb_formula_num_' + side + '" class="vb-num-input" style="width:60px;" value="" placeholder="&#8484;" step="any"><button class="vb-formula-btn" onclick="_vbFormulaAddNum(\'' + side + '\')">+</button></span>';
            html += '<button class="vb-formula-btn vb-formula-btn-danger" onclick="_vbFormulaClear(\'' + side + '\')" title="' + __('Clear') + '">&times; ' + __('Clear') + '</button>';
            html += '</div>';
            html += '<input type="text" id="vb_formula_text_' + side + '" style="width:100%;margin-top:0.35rem;font-family:Consolas,monospace;font-size:0.75rem;padding:0.25rem 0.4rem;background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;direction:ltr;" value="' + esc(_formulaPartsToString(parts)) + '" placeholder="' + __('Type or paste an expression, e.g. Live births (6) + Stillbirths >24w (7)') + '" onchange="_vbFormulaTextChange(\'' + side + '\')">';
            html += '</div>';
            return html;
        }

        function _buildVBFormula(expr) {
            let html = '<div class="vb-card">' + _vbPaletteHeaderHTML();
            const op = _vbState.op || '=';
            const def = _formulaOpDef(op);
            html += _vbFormulaSideHTML('lhs', _vbState.formulaParts || []);
            html += '<div class="vb-relation-box"><span class="vb-relation-symbol ' + def.cls + '" id="vb_op_symbol">' + def.sym + '</span> ';
            html += '<select id="vb_op_select" style="font-size:0.78rem;padding:0.15rem 0.3rem;background:var(--bg-elevated);color:var(--text-primary);border:1px solid var(--border-default);border-radius:4px;" onchange="_vbOnOpChange()" title="' + __('Comparison operator') + '">';
            html += _FORMULA_OP_ORDER.map(function(o) {
                return '<option value="' + o + '"' + (o === op ? ' selected' : '') + '>' + _formulaRelText(o) + '</option>';
            }).join('');
            html += '</select></div>';
            html += _vbFormulaSideHTML('rhs', _vbState.rhsParts || []);
            html += '<div style="margin-top:0.4rem;font-size:0.7rem;color:var(--text-muted);">'
                + __('Either side accepts {code} or Name (code) indicator references, + - * / and [ ] grouping.') + '</div>';
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

        // Formula builders hold two independent part lists: the left side in
        // formulaParts, the right side in rhsParts. Every handler takes the side
        // so one set of buttons drives both.
        function _vbFormulaParts(side) {
            if (side === 'rhs') {
                if (!_vbState.rhsParts) _vbState.rhsParts = [];
                return _vbState.rhsParts;
            }
            if (!_vbState.formulaParts) _vbState.formulaParts = [];
            return _vbState.formulaParts;
        }

        export function _vbFormulaAddOp(op, side) {
            _vbFormulaParts(side).push({ t: 'op', op: op });
            _vbRebuild();
        }

        export function _vbFormulaAddNum(side) {
            var s = side === 'rhs' ? 'rhs' : 'lhs';
            var inp = document.getElementById('vb_formula_num_' + s);
            if (!inp) return;
            var val = parseFloat(inp.value);
            if (isNaN(val)) return;
            _vbFormulaParts(s).push({ t: 'num', val: val });
            inp.value = '';
            _vbRebuild();
        }

        export function _vbFormulaAddIndicator(code, side) {
            _vbFormulaParts(side).push({ t: 'ind', code: code });
            _vbRebuild();
        }

        export function _vbFormulaRemove(idx, side) {
            _vbFormulaParts(side).splice(idx, 1);
            _vbRebuild();
        }

        export function _vbFormulaClear(side) {
            if (side === 'rhs') _vbState.rhsParts = [];
            else _vbState.formulaParts = [];
            _vbRebuild();
        }

        // Typed/pasted text replaces that side's chips. Accepts the same
        // syntax the engine does, so "Name (code)" works as well as {code}.
        export function _vbFormulaTextChange(side) {
            var s = side === 'rhs' ? 'rhs' : 'lhs';
            var inp = document.getElementById('vb_formula_text_' + s);
            if (!inp) return;
            var parts = _formulaStringToParts(inp.value);
            if (s === 'rhs') {
                _vbState.rhsParts = parts;
                _vbState.target = '';
            } else {
                _vbState.formulaParts = parts;
            }
            _vbRebuild();
        }

        export function _vbDropFormula(ev) {
            ev.preventDefault();
            ev.currentTarget.classList.remove('drag-over');
            var code = _vbDragCode || ev.dataTransfer.getData('text/plain');
            if (!code) return;
            var side = (ev.currentTarget.dataset && ev.currentTarget.dataset.side) || 'lhs';
            _vbFormulaAddIndicator(code, side);
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
            const parentChild = ['ge', 'eq', 'gt', 'ge_factor', 'le', 'lt', 'le_sum', 'parent_le', 'parent_lt'];
            const trendTypes = ['month_over', 'month_under', 'trend'];
            const listTypes = ['neg_check', 'decimal_check', 'all_zero'];
            if (parentChild.includes(expr)) {
                html = _buildVBParentChild(expr);
            } else if (trendTypes.includes(expr)) {
                html = _buildVBTrend(expr);
            } else if (listTypes.includes(expr)) {
                html = _buildVBList(expr);
            } else if (expr === 'missing') {
                html = _buildVBSingle(expr);
            } else if (expr === 'value_check') {
                html = _buildVBJson(expr);
            } else if (expr === 'compare') {
                html = _buildVBCompare();
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

        // Stage 2 of the comparison merge: the legacy comparison types are no
        // longer offered in Expression Type, but a stored rule must open in the
        // compare builder with exactly its old meaning. This table mirrors the
        // engine's _LEGACY_COMPARE_BLUEPRINT (left role, right role, operator,
        // factor key); tests/test_compare_expression.py checks the two agree.
        const LEGACY_COMPARE_BUILDER = {
            ge:        ['parent', 'children', '>=', null],
            gt:        ['parent', 'children', '>', null],
            eq:        ['parent', 'children', '=', null],
            ge_factor: ['parent', 'children', '>=', 'factor'],
            le:        ['child', 'parent', '<=', null],
            lt:        ['child', 'parent', '<', null],
            le_sum:    ['child', 'children', '>=', null],
            parent_le: ['parent', 'children', '<=', null],
            parent_lt: ['parent', 'children', '<', null],
        };

        export function _compareParamsFromLegacy(expr, params) {
            const spec = LEGACY_COMPARE_BUILDER[expr];
            if (!spec) return null;
            let p = params;
            if (typeof p === 'string') {
                try { p = JSON.parse(p || '{}'); } catch (e) { p = {}; }
            }
            p = p || {};
            const side = function(role) {
                if (role === 'children') {
                    return { codes: (p.children || []).filter(Boolean), agg: 'sum' };
                }
                return { codes: p[role] ? [p[role]] : [], agg: 'single' };
            };
            const out = { left: side(spec[0]), right: side(spec[1]), op: spec[2] };
            if (spec[3]) out.factor = parseFloat(p[spec[3]]) || 1.0;
            return out;
        }

        function _vbLoadExistingParams(expr, paramsStr) {
            let params = {};
            try { params = typeof paramsStr === 'string' ? JSON.parse(paramsStr) : paramsStr; } catch(e) {}
            _vbStateReset(expr);
            const parentChild = ['ge', 'eq', 'gt', 'ge_factor', 'le', 'lt', 'le_sum', 'parent_le', 'parent_lt'];
            const trendTypes = ['month_over', 'month_under'];
            const listTypes = ['neg_check', 'decimal_check', 'all_zero'];

            if (parentChild.includes(expr)) {
                _vbState.parent = params.parent || params.child || '';
                _vbState.child = params.child || '';
                _vbState.children = params.children || [];
                if (expr === 'ge_factor') _vbState.ge_factor = params.factor || 1.1;
            } else if (trendTypes.includes(expr)) {
                _vbState.direction = params.direction || (expr === 'month_under' ? 'under' : 'over');
                _vbState.indicator = (params.codes && params.codes[0]) || params.code || '';
                _vbState.factor = params.factor || (_vbState.direction === 'under' ? 0.5 : 2.0);
            } else if (listTypes.includes(expr) || expr === 'missing') {
                _vbState.codes = params.codes || [];
                _vbState.indicator = params.code || '';
            } else if (expr === 'value_check') {
                _vbState.rawParams = JSON.stringify(params || {}, null, 2);
            } else if (expr === 'compare') {
                _vbState.leftCodes = ((params.left && params.left.codes) || []).filter(Boolean);
                _vbState.rightCodes = ((params.right && params.right.codes) || []).filter(Boolean);
                _vbState.leftAgg = (params.left && params.left.agg) || 'single';
                _vbState.rightAgg = (params.right && params.right.agg) || 'single';
                _vbState.compareOp = params.op || '>=';
                _vbState.compareFactor = parseFloat(params.factor) || 1;
            } else if (expr === 'formula') {
                _vbState.formulaParts = _formulaStringToParts(params.formula || '');
                _vbState.op = params.op || '=';
                _vbState.target = params.target || '';
                // Legacy rules carry a single target code; show it as the right side.
                _vbState.rhsParts = _formulaStringToParts(params.rhs || (params.target ? '{' + params.target + '}' : ''));
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
                case 'parent_le':
                    if (!_vbState.parent || !(_vbState.children || []).length) return '';
                    return parent + ' <= ' + joinNames(_vbState.children);
                case 'parent_lt':
                    if (!_vbState.parent || !(_vbState.children || []).length) return '';
                    return parent + ' < ' + joinNames(_vbState.children);
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
                case 'trend':
                    if (!_vbState.indicator) return '';
                    return indName(_vbState.indicator) + (_vbState.direction === 'under' ? ' < ' : ' > ')
                        + (parseFloat(_vbState.factor) || (_vbState.direction === 'under' ? 0.5 : 2.0))
                        + 'x previous month';
                case 'compare': {
                    const leftNames = listNames(_vbState.leftCodes || []);
                    const rightNames = listNames(_vbState.rightCodes || []);
                    if (!leftNames || !rightNames) return '';
                    const factor = parseFloat(_vbState.compareFactor) || 1;
                    return (factor !== 1 ? factor + 'x ' : '') + leftNames
                        + ' ' + (_vbState.compareOp || '>=') + ' ' + rightNames;
                }
                case 'formula': {
                    const namesOf = function(parts) {
                        return (parts || []).map(function(p) {
                            if (p.t === 'ind') return indName(p.code);
                            if (p.t === 'num') return String(p.val);
                            return p.op;
                        }).filter(Boolean).join(' ');
                    };
                    const leftName = namesOf(_vbState.formulaParts);
                    const rightName = namesOf(_vbState.rhsParts) || indName(_vbState.target);
                    if (!leftName || !rightName) return '';
                    return leftName + ' ' + _formulaOpDef(_vbState.op || '=').sym + ' ' + rightName;
                }
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
            document.getElementById('ruleEditExpr').value = 'compare';
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
                // A rule saved with a retired comparison type opens as its
                // compare equivalent; saving then stores the merged shape.
                let editExpr = rule.expression_type;
                let editParams = rule.params;
                const converted = _compareParamsFromLegacy(editExpr, editParams);
                if (converted) {
                    editExpr = 'compare';
                    editParams = JSON.stringify(converted);
                }
                document.getElementById('ruleEditExpr').value = editExpr;
                document.getElementById('ruleEditEnabled').value = rule.enabled ? 'true' : 'false';
                document.getElementById('ruleEditDesc').value = rule.description || '';
                document.getElementById('ruleEditCode').disabled = true;
                // Load existing params into visual builder
                _vbLoadExistingParams(editExpr, editParams);
                // Keep the explanation in step with what the builder shows: a
                // retired type is now explained as compare.
                const editExpl = EXPR_EXPLANATIONS[editExpr];
                const explPanel = document.getElementById('ruleExprExplanation');
                if (explPanel) {
                    if (editExpl) {
                        document.getElementById('ruleExprExplTitle').textContent = __(editExpl.title);
                        document.getElementById('ruleExprExplText').textContent = __(editExpl.text);
                        explPanel.style.display = 'block';
                    } else {
                        explPanel.style.display = 'none';
                    }
                }
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
                    msel.innerHTML = '<option value="">Select month</option>' + months.filter(m => /^\d{4}-\d{2}$/.test(String(m))).map(m => '<option value="' + m + '">' + m + '</option>').join('');
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

        // ── Rule-change recompute notice ──────────────────────────────
        // A rule edit changes the stored ValidationResult rows (the Validation
        // Alerts screen) and the rule-dependent Quality Score, so the server
        // re-applies the rules to every recorded month in the background. Poll
        // the task, then refresh the screens that read those stored snapshots —
        // otherwise the Alerts tab and the dashboard keep showing pre-edit
        // numbers until the page is reloaded.
        let _recomputePollTimer = null;

        // Refresh a tab only when it has been loaded into the DOM; calling a
        // loader for an unopened tab would hit missing elements.
        function _refreshLoadedTab(tab, fnName) {
            var panel = document.getElementById('tab-' + tab);
            if (!panel || panel.dataset.loaded !== 'true') return;
            var fn = window[fnName];
            if (typeof fn === 'function') {
                try { fn(); } catch (e) { /* one screen must not stop the rest */ }
            }
        }

        function _refreshAlertSurfaces() {
            if (typeof loadRulesManager === 'function') loadRulesManager();
            _refreshLoadedTab('alerts', 'loadAlerts');
            _refreshLoadedTab('alerts', 'loadRuleFailures');
            _refreshLoadedTab('dashboard', 'loadDashboard');
            _refreshLoadedTab('quality', 'loadQualityReports');
        }
        window._refreshAlertSurfaces = _refreshAlertSurfaces;

        export function _watchRuleRecompute() {
            try { if (typeof clearTimeout === 'function') clearTimeout(_recomputePollTimer); } catch (e) {}
            let waited = 0;
            const poll = async function() {
                waited += 1500;
                try {
                    const res = await authFetch(API() + '/rules/recompute-status');
                    if (!res.ok) throw new Error('HTTP ' + res.status);
                    const st = await res.json();
                    // `pending` = another edit queued behind the running pass;
                    // keep waiting so the last edit is never reported as done
                    // before it has been applied.
                    if (st && (st.running || st.pending)) {
                        if (waited === 1500 && typeof toastInfo === 'function') {
                            toastInfo(__('Updating validation alerts and quality scores...'));
                        }
                        if (waited < 180000) { _recomputePollTimer = setTimeout(poll, 1500); return; }
                        return;
                    }
                    if (waited > 1500 && typeof toastSuccess === 'function') {
                        toastSuccess(__('Validation alerts and quality scores updated.'));
                        _refreshAlertSurfaces();
                    }
                } catch (e) { /* status is advisory only */ }
            };
            _recomputePollTimer = setTimeout(poll, 1500);
        }
        window._watchRuleRecompute = _watchRuleRecompute;

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
                // Stored ValidationResult / QualityScore rows are snapshots, so
                // the server re-runs the latest month in the background after a
                // rule change. Say so instead of letting the hospital card keep
                // showing a pre-edit score.
                _watchRuleRecompute();
                // The impact map (referenced indicators, affected hospitals)
                // is memoized server-side for 5 minutes — force a recompute
                // so the drawer/table show the new definition immediately.
                if (typeof window.forceRulesImpactRefresh === 'function') window.forceRulesImpactRefresh();
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
                if (typeof window.forceRulesImpactRefresh === 'function') window.forceRulesImpactRefresh();
                loadRulesManager();
                // Deleting a rule removes its stored failures — refresh the
                // alerts that were driven by it.
                _watchRuleRecompute();
            } catch(e) {
                toastError('Delete failed: ' + e.message);
            }
        }
