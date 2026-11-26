// ── User Guide tab: index + per-screen guides with navigation ───────────────
// The guides live in static/js/guides/*.js (one module per screen) and share
// one template from guide-kit.js. This module is the reader: a searchable
// index, a screen page per guide, breadcrumbs, a table of contents for the
// guide, and previous/next navigation. Deep links use the hash
// (#guide/data/upload), so a guide can be opened, refreshed and shared on its
// own; the "open this screen" button switches to the real application tab.
import { switchTab } from './main.js';
import { GUIDE_META, SECTION_ORDER, SECTION_TITLES } from './guide-kit.js';
import { DATA_GUIDES, guideByKey, guideIndex } from './guide-data.js';

const lang = () => (localStorage.getItem('lang') === 'ar' ? 'ar' : 'en');
const tx = (pair) => (pair ? (pair[lang()] || pair.en || '') : '');
const esc = (value) => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

let _query = '';
let _bound = false;
let _lastRoute;

// ── routing ─────────────────────────────────────────────────────────────────

function routeKey() {
    const match = String(location.hash || '').match(/^#guide\/(?:data\/)?([a-z0-9-]+)\s*$/i);
    return match ? match[1] : '';
}

function go(hash) {
    location.hash = hash || '#guide';
}

// ── searchable text ─────────────────────────────────────────────────────────

function collectText(node, out) {
    if (node == null) return out;
    if (typeof node === 'string') { out.push(node); return out; }
    if (Array.isArray(node)) { node.forEach(item => collectText(item, out)); return out; }
    if (typeof node === 'object') {
        Object.keys(node).forEach(key => {
            if (key === 'shot' || key === 'tab' || key === 'key') return;
            collectText(node[key], out);
        });
    }
    return out;
}

function guideText(guide) {
    return collectText(guide, []).join(' ').toLowerCase();
}

// Searching starts from the screen name (title and menu path in both
// languages), so a query like "rules" does not return every guide that merely
// mentions rules in its "related screens" section. Only when no screen name
// matches does the search fall back to the full guide text.
function headText(guide) {
    return [guide.title, guide.menu]
        .map(pair => pair ? String(pair.en || '') + ' ' + String(pair.ar || '') : '')
        .join(' ').toLowerCase();
}

// ── blocks ──────────────────────────────────────────────────────────────────

function blockHtml(block) {
    if (!block) return '';
    if (block.type === 'p') return '<p>' + esc(tx(block.text)) + '</p>';
    if (block.type === 'list') {
        return '<ul>' + block.items.map(item => '<li>' + esc(tx(item)) + '</li>').join('') + '</ul>';
    }
    if (block.type === 'steps') {
        return '<ol class="ug-steps">' + block.items.map(item => '<li>' + esc(tx(item)) + '</li>').join('') + '</ol>';
    }
    if (block.type === 'table') {
        const head = '<tr>' + block.headers.map(h => '<th>' + esc(tx(h)) + '</th>').join('') + '</tr>';
        const body = block.rows.map(row =>
            '<tr>' + row.map(cell => '<td>' + esc(tx(cell)) + '</td>').join('') + '</tr>'
        ).join('');
        return '<div class="ug-table-wrap"><table class="tbl ug-table"><thead>' + head +
            '</thead><tbody>' + body + '</tbody></table></div>';
    }
    return '';
}

// ── index ───────────────────────────────────────────────────────────────────

function matches(guide, needle) {
    if (!needle) return true;
    return guideText(guide).indexOf(needle) >= 0;
}

function cardHtml(guide) {
    return '<a class="ug-card" href="#guide/data/' + esc(guide.key) + '">' +
        '<div class="ug-card-icon" aria-hidden="true">' + esc(guide.icon || '📄') + '</div>' +
        '<div class="ug-card-body">' +
            '<div class="ug-card-title">' + esc(tx(guide.title)) + '</div>' +
            '<div class="ug-card-menu">' + esc(tx(guide.menu)) + '</div>' +
            '<div class="ug-card-purpose">' + esc(tx(guide.sections.overview[0].text)) + '</div>' +
            '<div class="ug-card-foot"><span class="ug-chip">' + esc(tx(GUIDE_META.permission)) +
                ': <code>' + esc(guide.permission) + '</code></span>' +
                '<span class="ug-open">' + esc(tx(GUIDE_META.openScreen)) + ' ↗</span></div>' +
        '</div></a>';
}

function renderList() {
    const list = document.getElementById('ugList');
    if (!list) return;
    const needle = _query.toLowerCase();
    let shown = DATA_GUIDES.filter(guide => !needle || headText(guide).indexOf(needle) >= 0);
    if (needle && !shown.length) shown = DATA_GUIDES.filter(guide => matches(guide, needle));
    const count = document.getElementById('ugCount');
    if (count) {
        count.textContent = shown.length + ' / ' + DATA_GUIDES.length + ' ' +
            tx(GUIDE_META.guideCount);
    }
    list.innerHTML = shown.length
        ? shown.map(cardHtml).join('')
        : '<div class="ug-empty">' + esc(tx(GUIDE_META.noResults)) + '</div>';
}

function renderIndex() {
    const body = document.getElementById('ugBody');
    if (!body) return;
    body.innerHTML =
        '<div class="ug-hero">' +
            '<h3>' + esc(tx(GUIDE_META.hubTitle)) + '</h3>' +
            '<p>' + esc(tx(GUIDE_META.hubSubtitle)) + '</p>' +
            '<p class="ug-hint">' + esc(tx(GUIDE_META.searchHint)) + '</p>' +
            '<div class="ug-count" id="ugCount"></div>' +
        '</div>' +
        '<div id="ugList" class="ug-grid"></div>' +
        '<p class="ug-verified">' + esc(tx(GUIDE_META.verified)) + '</p>';
    renderList();
}

// ── guide page ──────────────────────────────────────────────────────────────

function figureHtml(guide) {
    if (!guide.shot) return '';
    const legend = (guide.shotLegend || []).map(item => '<li>' + esc(tx(item)) + '</li>').join('');
    return '<figure class="ug-shot">' +
        '<img src="/static/guides/img/' + esc(guide.shot) + '" alt="' + esc(tx(guide.shotAlt)) + '" loading="lazy">' +
        '<figcaption>' +
            '<div class="ug-shot-title">' + esc(tx(GUIDE_META.screenshot)) + '</div>' +
            (legend ? '<div class="ug-legend-title">' + esc(tx(GUIDE_META.legend)) + '</div>' +
                '<ol class="ug-legend">' + legend + '</ol>' : '') +
            '<div class="ug-hint">' + esc(tx(GUIDE_META.screenshotsNote)) + '</div>' +
        '</figcaption></figure>';
}

function sectionHtml(guide, key, index) {
    const blocks = guide.sections[key] || [];
    if (!blocks.length) return '';
    return '<section class="ug-section" id="ug-sec-' + esc(key) + '">' +
        '<h4>' + esc(tx(SECTION_TITLES[key])) + '</h4>' +
        blocks.map(blockHtml).join('') +
        '</section>';
}

function pagerHtml(guide) {
    const index = guideIndex(guide.key);
    const previous = DATA_GUIDES[index - 1];
    const next = DATA_GUIDES[index + 1];
    const link = (item, label, dir) => item
        ? '<a class="ug-pager-link" href="#guide/data/' + esc(item.key) + '">' +
            '<span class="ug-pager-dir">' + (dir === 'prev' ? '← ' : '') + esc(label) + (dir === 'next' ? ' →' : '') + '</span>' +
            '<span class="ug-pager-title">' + esc(tx(item.title)) + '</span></a>'
        : '<span class="ug-pager-link is-disabled"></span>';
    return '<nav class="ug-pager" aria-label="' + esc(tx(GUIDE_META.previous)) + ' / ' + esc(tx(GUIDE_META.next)) + '">' +
        link(previous, tx(GUIDE_META.previous), 'prev') +
        '<a class="ug-pager-index" href="#guide">' + esc(tx(GUIDE_META.backToIndex)) + '</a>' +
        link(next, tx(GUIDE_META.next), 'next') +
        '</nav>';
}

function renderGuide(guide) {
    const body = document.getElementById('ugBody');
    if (!body) return;
    const toc = SECTION_ORDER
        .filter(key => (guide.sections[key] || []).length)
        .map(key => '<a href="#ug-sec-' + esc(key) + '" class="ug-toc-link">' + esc(tx(SECTION_TITLES[key])) + '</a>')
        .join('');
    body.innerHTML =
        '<nav class="ug-crumbs">' +
            '<a href="#guide">' + esc(tx(GUIDE_META.backToIndex)) + '</a>' +
            '<span>/</span><span>' + esc(tx({ en: 'Data section', ar: 'قسم البيانات' })) + '</span>' +
            '<span>/</span><strong>' + esc(tx(guide.title)) + '</strong>' +
        '</nav>' +
        '<div class="ug-guide-head">' +
            '<div>' +
                '<h3>' + esc(guide.icon || '') + ' ' + esc(tx(guide.title)) + '</h3>' +
                '<div class="ug-chips">' +
                    '<span class="ug-chip">' + esc(tx(GUIDE_META.menu)) + ': ' + esc(tx(guide.menu)) + '</span>' +
                    '<span class="ug-chip">' + esc(tx(GUIDE_META.permission)) + ': <code>' + esc(guide.permission) + '</code></span>' +
                '</div>' +
            '</div>' +
            '<button type="button" class="btn btn-sm" data-ug-open="' + esc(guide.tab) + '">' +
                esc(tx(GUIDE_META.openScreen)) + ' ↗</button>' +
        '</div>' +
        figureHtml(guide) +
        '<nav class="ug-toc"><span class="ug-toc-title">' + esc(tx(GUIDE_META.onThisPage)) + '</span>' + toc + '</nav>' +
        SECTION_ORDER.map(key => sectionHtml(guide, key)).join('') +
        '<p class="ug-verified">' + esc(tx(GUIDE_META.verified)) + '</p>' +
        pagerHtml(guide);
    body.querySelectorAll('img').forEach(img => {
        img.addEventListener('error', function () {
            const figure = img.closest('figure');
            if (!figure) return;
            figure.innerHTML = '<div class="ug-shot-missing">' + esc(tx(GUIDE_META.screenshotMissing)) + '</div>';
        });
    });
}

// ── render ──────────────────────────────────────────────────────────────────

function render() {
    const key = routeKey();
    _lastRoute = key;
    const root = document.getElementById('ugWrap');
    if (!root) return;
    const guide = key ? guideByKey(key) : null;
    if (key && !guide) { renderIndex(); return; }
    if (guide) renderGuide(guide); else renderIndex();
}

// ── lifecycle ───────────────────────────────────────────────────────────────

function bindOnce() {
    if (_bound) return;
    _bound = true;

    document.addEventListener('input', function (event) {
        const input = event.target;
        if (!input || input.id !== 'ugSearch') return;
        _query = String(input.value || '').trim();
        if (routeKey()) {
            // A search belongs to the index: leave the open guide, then render.
            location.hash = '#guide';
            return;
        }
        renderList();
    });

    window.addEventListener('hashchange', function () {
        if (routeKey() !== _lastRoute) render();
    });

    document.addEventListener('click', function (event) {
        const trigger = event.target.closest('[data-ug-open]');
        if (!trigger) return;
        const tab = trigger.getAttribute('data-ug-open');
        if (tab && document.querySelector('.tab[data-tab="' + tab + '"]')) {
            switchTab(tab);
        }
    });

    // The app re-renders on language toggle by flipping <html dir/lang>; follow
    // it so the open guide switches language in place.
    if (typeof MutationObserver === 'function') {
        const observer = new MutationObserver(function () { render(); });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['dir', 'lang'] });
    }
}

export function initUserGuide() {
    bindOnce();
    render();
}

export function loadUserGuide() {
    return render();
}

window.initUserGuide = initUserGuide;
window.loadUserGuide = loadUserGuide;
