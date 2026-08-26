/**
 * table-utils.js — Reusable data-table enhancements
 * Provides: sorting, pagination, score badges, row drill-down
 *
 * Usage:
 *   import { DataTable } from './table-utils.js';
 *   const dt = new DataTable({ id: 'myTable', pageSize: 15 });
 *   dt.render(columns, rows, { onRowClick: (row) => { ... } });
 */

// ── Score Badge ──────────────────────────────────────────
export function scoreBadge(value, opts = {}) {
  if (value == null || isNaN(value)) return '<span class="tb-badge tb-na">N/A</span>';
  const v = parseFloat(value);
  const decimals = opts.decimals ?? 1;
  const showPlus = opts.showPlus && v > 0;
  let cls, label;
  if (v >= 90)      { cls = 'tb-a'; label = 'A'; }
  else if (v >= 75) { cls = 'tb-b'; label = 'B'; }
  else if (v >= 60) { cls = 'tb-c'; label = 'C'; }
  else              { cls = 'tb-d'; label = 'D'; }
  const display = v.toFixed(decimals);
  return `<span class="tb-badge ${cls}" title="Grade ${label} — ${display}%">${display}</span>`;
}

// ── Trend Arrow ──────────────────────────────────────────
export function trendIcon(direction) {
  if (direction === 'up')    return '<span class="tb-trend tb-up">▲</span>';
  if (direction === 'down')  return '<span class="tb-trend tb-down">▼</span>';
  return '<span class="tb-trend tb-stable">●</span>';
}

// ── Confidence Bar ───────────────────────────────────────
export function confidenceBar(value) {
  if (value == null) return '<span class="tb-badge tb-na">N/A</span>';
  const v = Math.min(100, Math.max(0, parseFloat(value)));
  const color = v >= 80 ? 'var(--accent-green)' : v >= 60 ? 'var(--accent-blue)' : v >= 40 ? 'var(--accent-orange)' : 'var(--accent-red)';
  return `<div class="tb-conf-bar"><div class="tb-conf-fill" style="width:${v}%;background:${color};"></div><span class="tb-conf-val">${v.toFixed(1)}</span></div>`;
}

// ── DataTable Class ──────────────────────────────────────
export class DataTable {
  constructor(opts = {}) {
    this.containerId = opts.id;
    this.pageSize = opts.pageSize || 15;
    this.currentPage = 1;
    this.sortCol = opts.defaultSort || null;
    this.sortAsc = opts.defaultAsc ?? true;
    this.columns = [];
    this.rows = [];
    this.onRowClick = opts.onRowClick || null;
    this.onRowDblClick = opts.onRowDblClick || null;
  }

  /** Render the table with columns and data rows. */
  render(columns, rows, opts = {}) {
    this.columns = columns;
    this.rows = rows;
    if (opts.onRowClick) this.onRowClick = opts.onRowClick;
    if (opts.onRowDblClick) this.onRowDblClick = opts.onRowDblClick;
    this.currentPage = 1;
    if (opts.defaultSort) { this.sortCol = opts.defaultSort; this.sortAsc = opts.defaultAsc ?? true; }
    this._render();
  }

  /** Sort by column key (toggle direction). */
  sortBy(colKey) {
    if (this.sortCol === colKey) { this.sortAsc = !this.sortAsc; }
    else { this.sortCol = colKey; this.sortAsc = true; }
    this._render();
  }

  _getSorted() {
    if (!this.sortCol) return [...this.rows];
    const col = this.columns.find(c => c.key === this.sortCol);
    if (!col) return [...this.rows];
    const asc = this.sortAsc;
    return [...this.rows].sort((a, b) => {
      let av = col.getValue ? col.getValue(a) : a[this.sortCol];
      let bv = col.getValue ? col.getValue(b) : b[this.sortCol];
      if (av == null) av = '';
      if (bv == null) bv = '';
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
  }

  _render() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    const sorted = this._getSorted();
    const totalPages = Math.max(1, Math.ceil(sorted.length / this.pageSize));
    if (this.currentPage > totalPages) this.currentPage = totalPages;
    const start = (this.currentPage - 1) * this.pageSize;
    const pageRows = sorted.slice(start, start + this.pageSize);

    let html = '<div class="tb-wrap">';

    // Table
    html += '<div class="tb-scroll"><table class="tb-table"><thead><tr>';
    this.columns.forEach(col => {
      const sortable = col.sortable !== false;
      let cls = sortable ? 'tb-th sortable' : 'tb-th';
      if (this.sortCol === col.key) cls += this.sortAsc ? ' sort-asc' : ' sort-desc';
      const arrow = this.sortCol === col.key ? (this.sortAsc ? ' ▲' : ' ▼') : '';
      html += `<th class="${cls}" data-col="${col.key}" style="${col.width ? 'width:' + col.width : ''}">${col.label}${arrow}</th>`;
    });
    html += '</tr></thead><tbody>';

    if (pageRows.length === 0) {
      const colSpan = this.columns.length;
      html += `<tr><td colspan="${colSpan}" class="tb-empty"><div class="tb-empty-icon">📊</div><div>No data available</div></td></tr>`;
    } else {
      pageRows.forEach(row => {
        const clickable = this.onRowClick ? ' tb-clickable' : '';
        const dataId = row.id ? ` data-id="${row.id}"` : '';
        html += `<tr class="${clickable}"${dataId}>`;
        this.columns.forEach(col => {
          const val = col.render ? col.render(row) : (row[col.key] ?? '—');
          html += `<td>${val}</td>`;
        });
        html += '</tr>';
      });
    }
    html += '</tbody></table></div>';

    // Pagination footer
    html += '<div class="tb-footer">';
    html += `<span class="tb-count">${sorted.length} row${sorted.length !== 1 ? 's' : ''}</span>`;
    html += '<div class="tb-pager">';
    html += `<button class="tb-page-btn" data-page="first" title="First page" ${this.currentPage <= 1 ? 'disabled' : ''}>«</button>`;
    html += `<button class="tb-page-btn" data-page="prev" title="Previous page" ${this.currentPage <= 1 ? 'disabled' : ''}>‹</button>`;
    html += `<span class="tb-page-info">Page ${this.currentPage} of ${totalPages}</span>`;
    html += `<button class="tb-page-btn" data-page="next" title="Next page" ${this.currentPage >= totalPages ? 'disabled' : ''}>›</button>`;
    html += `<button class="tb-page-btn" data-page="last" title="Last page" ${this.currentPage >= totalPages ? 'disabled' : ''}>»</button>`;
    html += '</div>';

    // Page size selector
    html += '<select class="tb-page-size">';
    [10, 15, 25, 50, 100].forEach(n => {
      html += `<option value="${n}" ${n === this.pageSize ? 'selected' : ''}>${n}</option>`;
    });
    html += '</select>';
    html += '</div></div>';

    container.innerHTML = html;
    this._bind(container);
  }

  _bind(container) {
    const self = this;
    // Sort headers
    container.querySelectorAll('th.sortable').forEach(th => {
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => self.sortBy(th.dataset.col));
    });
    // Pagination buttons
    container.querySelectorAll('.tb-page-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.page;
        const totalPages = Math.ceil(self.rows.length / self.pageSize);
        if (action === 'first') self.currentPage = 1;
        else if (action === 'prev') self.currentPage = Math.max(1, self.currentPage - 1);
        else if (action === 'next') self.currentPage = Math.min(totalPages, self.currentPage + 1);
        else if (action === 'last') self.currentPage = totalPages;
        self._render();
      });
    });
    // Page size
    const sizeSelect = container.querySelector('.tb-page-size');
    if (sizeSelect) {
      sizeSelect.addEventListener('change', () => {
        self.pageSize = parseInt(sizeSelect.value, 10);
        self.currentPage = 1;
        self._render();
      });
    }
    // Row clicks
    if (self.onRowClick) {
      container.querySelectorAll('tr.tb-clickable').forEach(tr => {
        tr.addEventListener('click', () => {
          const id = tr.dataset.id ? parseInt(tr.dataset.id) : null;
          const row = id != null ? self.rows.find(r => r.id === id) : null;
          if (row) self.onRowClick(row);
        });
      });
    }
    if (self.onRowDblClick) {
      container.querySelectorAll('tr.tb-clickable').forEach(tr => {
        tr.addEventListener('dblclick', () => {
          const id = tr.dataset.id ? parseInt(tr.dataset.id) : null;
          const row = id != null ? self.rows.find(r => r.id === id) : null;
          if (row) self.onRowDblClick(row);
      });
    });
  }
}
}

// ── Standalone makeSortable ────────────────────────────────
export function makeSortable(tableId, opts = {}) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const numericCols = new Set(opts.numericColumns || []);
  let sortCol = opts.defaultSortCol ?? null;
  let sortAsc = opts.defaultAsc ?? true;

  const headers = table.querySelectorAll('thead th');
  const tbody = table.querySelector('tbody');
  if (!tbody) return;

  headers.forEach((th, idx) => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      if (sortCol === idx) {
        sortAsc = !sortAsc;
      } else {
        sortCol = idx;
        sortAsc = true;
      }
      applySort();
    });
  });

  function applySort() {
    const rows = Array.from(tbody.querySelectorAll('tr'));

    rows.sort((a, b) => {
      const aCell = a.children[sortCol];
      const bCell = b.children[sortCol];
      let av = aCell ? aCell.textContent.trim() : '';
      let bv = bCell ? bCell.textContent.trim() : '';

      if (numericCols.has(sortCol)) {
        const an = parseFloat(av.replace(/[^\d.\-]/g, '')) || 0;
        const bn = parseFloat(bv.replace(/[^\d.\-]/g, '')) || 0;
        return sortAsc ? an - bn : bn - an;
      }

      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    });

    rows.forEach(r => tbody.appendChild(r));
    updateHeaders();
  }

  function updateHeaders() {
    headers.forEach((th, idx) => {
      const arrow = idx === sortCol ? (sortAsc ? ' ▲' : ' ▼') : '';
      const base = th.textContent.replace(/\s*[▲▼]\s*$/, '');
      th.textContent = base + arrow;
    });
  }

  if (sortCol != null) applySort();
}
