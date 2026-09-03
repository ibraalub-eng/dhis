import { apiGet, apiPut, apiDelete, apiPostJSON, apiPost } from './api.js';
import { esc } from './tree.js';
import { toastSuccess, toastError, toastWarning } from './toast.js';

window._clearHospData = function(id, btn) {
    const name = btn.getAttribute('data-hosp-name') || '';
    clearHospitalData(id, name);
};

let _hospitals = [];
let _governorates = [];
let _types = [];
let _ownerships = [];
let _facilityTypes = [];
let _editHospId = null;
let _editGovId = null;
let _editTypeId = null;
let _editOwnId = null;
let _editFacTypeId = null;

export function loadHospitalsTab() {
    loadGovernorates();
    loadHospitalTypes();
    loadOwnerships();
    loadFacilityTypes();
    loadHospitalsList();
}

function switchHospSubtab(name) {
    document.querySelectorAll('.hosp-subtab').forEach(t => {
        t.style.color = t.dataset.subtab === name ? 'var(--accent-blue)' : 'var(--text-muted)';
        t.style.borderBottom = t.dataset.subtab === name ? '2px solid var(--accent-blue)' : '2px solid transparent';
    });
    document.querySelectorAll('.hosp-subtab-content').forEach(d => d.style.display = 'none');
    document.getElementById('hospSub-' + name).style.display = '';
}
window.switchHospSubtab = switchHospSubtab;

function loadHospitalsList() {
    var sp = document.getElementById('hospLoading');
    if (sp) sp.style.display = '';
    var ct = document.getElementById('hospList');
    if (ct) ct.style.display = 'none';
    apiGet('/hospitals/?include_inactive=true').then(data => {
        _hospitals = data || [];
        if (sp) sp.style.display = 'none';
        if (ct) ct.style.display = '';
        renderHospitals();
    }).catch(function() {
        if (sp) sp.style.display = 'none';
        if (ct) { ct.style.display = ''; ct.innerHTML = '<div style="padding:1rem;color:var(--accent-red);">Failed to load hospitals.</div>'; }
    });
}

function renderHospitals() {
    const search = (document.getElementById('hospSearch').value || '').toLowerCase();
    const filterGov = document.getElementById('hospFilterGov').value;
    const filterType = document.getElementById('hospFilterType').value;
    const filterOwn = document.getElementById('hospFilterOwnership').value;
    const filterFacType = document.getElementById('hospFilterFacilityType').value;
    const filtered = _hospitals.filter(h => {
        if (search && !h.name.toLowerCase().includes(search)) return false;
        if (filterGov && String(h.governorate_id) !== filterGov) return false;
        if (filterType && String(h.hospital_type_id) !== filterType) return false;
        if (filterOwn && String(h.facility_ownership_id) !== filterOwn) return false;
        if (filterFacType && String(h.facility_type_id) !== filterFacType) return false;
        return true;
    });
    // Sort: active hospitals first, then inactive
    filtered.sort((a, b) => {
        if (a.is_active && !b.is_active) return -1;
        if (!a.is_active && b.is_active) return 1;
        return a.name.localeCompare(b.name, 'ar');
    });
    const container = document.getElementById('hospList');
    if (!filtered.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">No hospitals found.</div>';
        return;
    }
    // Fetch data status to show indicator/score counts
    apiGet('/hospitals/data-status').then(statuses => {
        const statusMap = {};
        (statuses || []).forEach(s => { statusMap[s.id] = s; });
        renderHospitalsTable(filtered, statusMap);
    }).catch(() => {
        renderHospitalsTable(filtered, {});
    });
}

function renderHospitalsTable(filtered, statusMap) {
    const container = document.getElementById('hospList');
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:var(--bg-elevated);">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">OrgUnit ID</th>' +
        '<th style="text-align:left;padding:0.4rem;">Ownership</th>' +
        '<th style="text-align:left;padding:0.4rem;">Facility Type</th>' +
        '<th style="text-align:left;padding:0.4rem;">Governorate</th>' +
        '<th style="text-align:left;padding:0.4rem;">Type</th>' +
        '<th style="text-align:center;padding:0.4rem;">Data</th>' +
        '<th style="text-align:center;padding:0.4rem;">Status</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    filtered.forEach(h => {
        const govName = h.governorate_name || '';
        const typeName = h.hospital_type_name || '';
        const st = statusMap[h.id];
        const ivCount = st ? st.indicator_values : 0;
        const qsCount = st ? st.quality_scores : 0;
        const monthCount = st ? st.months.length : 0;
        let dataHtml;
        if (ivCount === 0) {
            dataHtml = '<span style="color:var(--accent-red);font-weight:600;">No Data</span>';
        } else {
            dataHtml = '<span style="color:#2e7d32;">' + ivCount + ' values</span>' +
                '<br><span style="font-size:0.72rem;color:var(--text-muted);">' + monthCount + ' months, ' + qsCount + ' scores</span>';
        }
        const statusHtml = '<input type="checkbox" ' + (h.is_active ? 'checked' : '') + ' onchange="toggleHospitalActive(' + h.id + ', this.checked)"> ' + (h.is_active ? 'Active' : 'Inactive');
        html += '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(h.name) + (h.address ? '<br><span style="font-size:0.72rem;color:var(--text-muted);">' + esc(h.address) + '</span>' : '') + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-muted);font-size:0.78rem;">' + esc(h.organisation_unit_id || '') + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-secondary);">' + esc(h.facility_ownership_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-secondary);">' + esc(h.facility_type_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-secondary);">' + esc(govName) + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-secondary);">' + esc(typeName) + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' + dataHtml + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' + statusHtml + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospital(' + h.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="window._clearHospData(' + h.id + ', this)" data-hosp-name="' + esc(h.name) + '" style="color:#d97706;margin-right:0.3rem;">Clear Data</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospital(' + h.id + ')" style="color:var(--accent-red);">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}
window.filterHospitals = function() { renderHospitals(); };

function loadGovernorates() {
    var sp = document.getElementById('govLoading');
    if (sp) sp.style.display = '';
    var ct = document.getElementById('govList');
    if (ct) ct.style.display = 'none';
    apiGet('/governorates/').then(data => {
        _governorates = data || [];
        if (sp) sp.style.display = 'none';
        if (ct) ct.style.display = '';
        renderGovernorates();
        populateGovDropdowns();
    }).catch(function() {
        if (sp) sp.style.display = 'none';
        if (ct) { ct.style.display = ''; ct.innerHTML = '<div style="padding:1rem;color:var(--accent-red);">Failed to load.</div>'; }
    });
}

function renderGovernorates() {
    const container = document.getElementById('govList');
    if (!_governorates.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">No governorates yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:var(--bg-elevated);">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _governorates.forEach(g => {
        html += '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(g.name) + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-muted);font-size:0.78rem;">' + (g.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editGovernorate(' + g.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteGovernorate(' + g.id + ')" style="color:var(--accent-red);">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateGovDropdowns() {
    const selects = ['hospFormGov', 'hospFilterGov'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormGov' ? '-- None --' : 'All Governorates') + '</option>' +
            _governorates.map(g => '<option value="' + g.id + '">' + esc(g.name) + '</option>').join('');
        sel.value = val;
    });
}

function loadHospitalTypes() {
    var sp = document.getElementById('typeLoading');
    if (sp) sp.style.display = '';
    var ct = document.getElementById('typeList');
    if (ct) ct.style.display = 'none';
    apiGet('/hospital-types/').then(data => {
        _types = data || [];
        if (sp) sp.style.display = 'none';
        if (ct) ct.style.display = '';
        renderHospitalTypes();
        populateTypeDropdowns();
    }).catch(function() {
        if (sp) sp.style.display = 'none';
        if (ct) { ct.style.display = ''; ct.innerHTML = '<div style="padding:1rem;color:var(--accent-red);">Failed to load.</div>'; }
    });
}

function renderHospitalTypes() {
    const container = document.getElementById('typeList');
    if (!_types.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">No hospital types yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:var(--bg-elevated);">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _types.forEach(t => {
        html += '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-muted);font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospitalType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospitalType(' + t.id + ')" style="color:var(--accent-red);">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateTypeDropdowns() {
    const selects = ['hospFormType', 'hospFilterType'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormType' ? '-- None --' : 'All Types') + '</option>' +
            _types.map(t => '<option value="' + t.id + '">' + esc(t.name) + '</option>').join('');
        sel.value = val;
    });
}

function showHospitalModal(data) {
    _editHospId = data ? data.id : null;
    document.getElementById('hospModalTitle').textContent = data ? 'Edit Hospital' : 'Add Hospital';
    document.getElementById('hospFormName').value = data ? data.name : '';
    document.getElementById('hospFormGov').value = data ? data.governorate_id || '' : '';
    document.getElementById('hospFormType').value = data ? data.hospital_type_id || '' : '';
    document.getElementById('hospFormOrgUnitId').value = data ? data.organisation_unit_id || '' : '';
    document.getElementById('hospFormOwnership').value = data ? data.facility_ownership_id || '' : '';
    document.getElementById('hospFormFacilityType').value = data ? data.facility_type_id || '' : '';
    document.getElementById('hospFormAddress').value = data ? data.address || '' : '';
    document.getElementById('hospModal').style.display = 'flex';
}
window.showHospitalModal = showHospitalModal;

function closeHospModal() {
    document.getElementById('hospModal').style.display = 'none';
    _editHospId = null;
}
window.closeHospModal = closeHospModal;

function saveHospital() {
    const name = document.getElementById('hospFormName').value.trim();
    if (!name) { toastWarning('Name is required.'); return; }
    const data = {
        name: name,
        region: '',
        governorate_id: document.getElementById('hospFormGov').value ? parseInt(document.getElementById('hospFormGov').value) : null,
        hospital_type_id: document.getElementById('hospFormType').value ? parseInt(document.getElementById('hospFormType').value) : null,
        organisation_unit_id: document.getElementById('hospFormOrgUnitId').value.trim() || null,
        facility_ownership_id: document.getElementById('hospFormOwnership').value ? parseInt(document.getElementById('hospFormOwnership').value) : null,
        facility_type_id: document.getElementById('hospFormFacilityType').value ? parseInt(document.getElementById('hospFormFacilityType').value) : null,
        address: document.getElementById('hospFormAddress').value.trim() || null,
    };
    const promise = _editHospId ? apiPut('/hospitals/' + _editHospId, data) : apiPostJSON('/hospitals/', data);
    promise.then(() => {
        closeHospModal();
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.saveHospital = saveHospital;

function editHospital(id) {
    const h = _hospitals.find(x => x.id === id);
    if (h) showHospitalModal(h);
}
window.editHospital = editHospital;

async function deleteHospital(id) {
    if (!await confirmDestructive({ title: 'Delete Hospital', message: 'Delete this hospital? This cannot be undone.', okLabel: 'Delete' })) return;
    apiDelete('/hospitals/' + id).then(() => loadHospitalsList()).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.deleteHospital = deleteHospital;

function toggleHospitalActive(id, active) {
    apiPut('/hospitals/' + id + '/toggle-active').then(() => {
        loadHospitalsList();
        // Auto-refresh dashboard and recalculate scores
        if (typeof window.loadDashboard === 'function') window.loadDashboard();
        apiPost('/dashboard/recalculate-completeness').catch(() => {});
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.toggleHospitalActive = toggleHospitalActive;

function showGovModal(data) {
    _editGovId = data ? data.id : null;
    document.getElementById('govModalTitle').textContent = data ? 'Edit Governorate' : 'Add Governorate';
    document.getElementById('govFormName').value = data ? data.name : '';
    document.getElementById('govModal').style.display = 'flex';
}
window.showGovModal = showGovModal;

function closeGovModal() {
    document.getElementById('govModal').style.display = 'none';
    _editGovId = null;
}
window.closeGovModal = closeGovModal;

function saveGovernorate() {
    const name = document.getElementById('govFormName').value.trim();
    if (!name) { toastWarning('Name is required.'); return; }
    const promise = _editGovId ? apiPut('/governorates/' + _editGovId, { name: name }) : apiPostJSON('/governorates/', { name: name });
    promise.then(() => {
        closeGovModal();
        loadGovernorates();
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.saveGovernorate = saveGovernorate;

function editGovernorate(id) {
    const g = _governorates.find(x => x.id === id);
    if (g) showGovModal(g);
}
window.editGovernorate = editGovernorate;

async function deleteGovernorate(id) {
    if (!await confirmDestructive({ title: 'Delete Governorate', message: 'Delete this governorate? Only possible if no hospitals are linked.', okLabel: 'Delete' })) return;
    apiDelete('/governorates/' + id).then(() => loadGovernorates()).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.deleteGovernorate = deleteGovernorate;

function showTypeModal(data) {
    _editTypeId = data ? data.id : null;
    document.getElementById('typeModalTitle').textContent = data ? 'Edit Hospital Type' : 'Add Hospital Type';
    document.getElementById('typeFormName').value = data ? data.name : '';
    document.getElementById('typeModal').style.display = 'flex';
}
window.showTypeModal = showTypeModal;

function closeTypeModal() {
    document.getElementById('typeModal').style.display = 'none';
    _editTypeId = null;
}
window.closeTypeModal = closeTypeModal;

function saveHospitalType() {
    const name = document.getElementById('typeFormName').value.trim();
    if (!name) { toastWarning('Name is required.'); return; }
    const promise = _editTypeId ? apiPut('/hospital-types/' + _editTypeId, { name: name }) : apiPostJSON('/hospital-types/', { name: name });
    promise.then(() => {
        closeTypeModal();
        loadHospitalTypes();
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.saveHospitalType = saveHospitalType;

function editHospitalType(id) {
    const t = _types.find(x => x.id === id);
    if (t) showTypeModal(t);
}
window.editHospitalType = editHospitalType;

async function deleteHospitalType(id) {
    if (!await confirmDestructive({ title: 'Delete Hospital Type', message: 'Delete this hospital type? Only possible if no hospitals are linked.', okLabel: 'Delete' })) return;
    apiDelete('/hospital-types/' + id).then(() => loadHospitalTypes()).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.deleteHospitalType = deleteHospitalType;

// ── Facility Ownerships ──────────────────────────────────────────

function loadOwnerships() {
    var sp = document.getElementById('ownershipLoading');
    if (sp) sp.style.display = '';
    var ct = document.getElementById('ownershipList');
    if (ct) ct.style.display = 'none';
    apiGet('/facility-ownerships/').then(data => {
        _ownerships = data || [];
        if (sp) sp.style.display = 'none';
        if (ct) ct.style.display = '';
        renderOwnerships();
        populateOwnershipDropdowns();
    }).catch(function() {
        if (sp) sp.style.display = 'none';
        if (ct) { ct.style.display = ''; ct.innerHTML = '<div style="padding:1rem;color:var(--accent-red);">Failed to load.</div>'; }
    });
}

function renderOwnerships() {
    const container = document.getElementById('ownershipList');
    if (!_ownerships.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">No facility ownerships yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:var(--bg-elevated);">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _ownerships.forEach(o => {
        html += '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(o.name) + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-muted);font-size:0.78rem;">' + (o.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editOwnership(' + o.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteOwnership(' + o.id + ')" style="color:var(--accent-red);">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateOwnershipDropdowns() {
    const selects = ['hospFormOwnership', 'hospFilterOwnership'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormOwnership' ? '-- None --' : 'All Ownerships') + '</option>' +
            _ownerships.map(o => '<option value="' + o.id + '">' + esc(o.name) + '</option>').join('');
        sel.value = val;
    });
}

function showOwnershipModal(data) {
    _editOwnId = data ? data.id : null;
    document.getElementById('ownershipModalTitle').textContent = data ? 'Edit Facility Ownership' : 'Add Facility Ownership';
    document.getElementById('ownershipFormName').value = data ? data.name : '';
    document.getElementById('ownershipModal').style.display = 'flex';
}
window.showOwnershipModal = showOwnershipModal;

function closeOwnershipModal() {
    document.getElementById('ownershipModal').style.display = 'none';
    _editOwnId = null;
}
window.closeOwnershipModal = closeOwnershipModal;

function saveOwnership() {
    const name = document.getElementById('ownershipFormName').value.trim();
    if (!name) { toastWarning('Name is required.'); return; }
    const promise = _editOwnId ? apiPut('/facility-ownerships/' + _editOwnId, { name: name }) : apiPostJSON('/facility-ownerships/', { name: name });
    promise.then(() => {
        closeOwnershipModal();
        loadOwnerships();
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.saveOwnership = saveOwnership;

function editOwnership(id) {
    const o = _ownerships.find(x => x.id === id);
    if (o) showOwnershipModal(o);
}
window.editOwnership = editOwnership;

async function deleteOwnership(id) {
    if (!await confirmDestructive({ title: 'Delete Ownership', message: 'Delete this facility ownership? Only possible if no hospitals are linked.', okLabel: 'Delete' })) return;
    apiDelete('/facility-ownerships/' + id).then(() => loadOwnerships()).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.deleteOwnership = deleteOwnership;

// ── Facility Types ───────────────────────────────────────────────

function loadFacilityTypes() {
    var sp = document.getElementById('facilityTypeLoading');
    if (sp) sp.style.display = '';
    var ct = document.getElementById('facilityTypeList');
    if (ct) ct.style.display = 'none';
    apiGet('/facility-types/').then(data => {
        _facilityTypes = data || [];
        if (sp) sp.style.display = 'none';
        if (ct) ct.style.display = '';
        renderFacilityTypes();
        populateFacilityTypeDropdowns();
    }).catch(function() {
        if (sp) sp.style.display = 'none';
        if (ct) { ct.style.display = ''; ct.innerHTML = '<div style="padding:1rem;color:var(--accent-red);">Failed to load.</div>'; }
    });
}

function renderFacilityTypes() {
    const container = document.getElementById('facilityTypeList');
    if (!_facilityTypes.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--text-muted);">No facility types yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:var(--bg-elevated);">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _facilityTypes.forEach(t => {
        html += '<tr style="border-bottom:1px solid var(--border-default);">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
            '<td style="padding:0.4rem;color:var(--text-muted);font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editFacilityType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteFacilityType(' + t.id + ')" style="color:var(--accent-red);">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function populateFacilityTypeDropdowns() {
    const selects = ['hospFormFacilityType', 'hospFilterFacilityType'];
    selects.forEach(sid => {
        const sel = document.getElementById(sid);
        if (!sel) return;
        const val = sel.value;
        sel.innerHTML = '<option value="">' + (sid === 'hospFormFacilityType' ? '-- None --' : 'All Facility Types') + '</option>' +
            _facilityTypes.map(t => '<option value="' + t.id + '">' + esc(t.name) + '</option>').join('');
        sel.value = val;
    });
}

function showFacilityTypeModal(data) {
    _editFacTypeId = data ? data.id : null;
    document.getElementById('facilityTypeModalTitle').textContent = data ? 'Edit Facility Type' : 'Add Facility Type';
    document.getElementById('facilityTypeFormName').value = data ? data.name : '';
    document.getElementById('facilityTypeModal').style.display = 'flex';
}
window.showFacilityTypeModal = showFacilityTypeModal;

function closeFacilityTypeModal() {
    document.getElementById('facilityTypeModal').style.display = 'none';
    _editFacTypeId = null;
}
window.closeFacilityTypeModal = closeFacilityTypeModal;

function saveFacilityType() {
    const name = document.getElementById('facilityTypeFormName').value.trim();
    if (!name) { toastWarning('Name is required.'); return; }
    const promise = _editFacTypeId ? apiPut('/facility-types/' + _editFacTypeId, { name: name }) : apiPostJSON('/facility-types/', { name: name });
    promise.then(() => {
        closeFacilityTypeModal();
        loadFacilityTypes();
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.saveFacilityType = saveFacilityType;

function editFacilityType(id) {
    const t = _facilityTypes.find(x => x.id === id);
    if (t) showFacilityTypeModal(t);
}
window.editFacilityType = editFacilityType;

async function deleteFacilityType(id) {
    if (!await confirmDestructive({ title: 'Delete Facility Type', message: 'Delete this facility type? Only possible if no hospitals are linked.', okLabel: 'Delete' })) return;
    apiDelete('/facility-types/' + id).then(() => loadFacilityTypes()).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.deleteFacilityType = deleteFacilityType;

// ── Clear Data ──────────────────────────────────────────────

async function clearHospitalData(id, name) {
    if (!await confirmDestructive({ title: 'Clear Hospital Data', message: 'Clear ALL indicator data for <strong>' + name + '</strong>?', details: 'This will remove indicator values, quality scores, validation results, and clinical results. The hospital will become inactive.', okLabel: 'Clear Data' })) return;
    apiPut('/hospitals/' + id + '/clear-data').then(res => {
        if (res.message) toastSuccess(res.message);
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.clearHospitalData = clearHospitalData;

async function clearAllData() {
    if (!await confirmDestructive({ title: 'Nuclear Option', message: 'Clear ALL indicator data for ALL hospitals?', details: 'This will remove everything. All hospitals will become inactive. You can re-upload data after clearing.', okLabel: 'Clear Everything' })) return;
    if (!await confirmDestructive({ title: 'Final Confirmation', message: 'Are you REALLY sure? This cannot be undone.', confirmText: 'DELETE' })) return;
    apiDelete('/hospitals/clear-all-data').then(res => {
        if (res.message) toastSuccess(res.message);
        loadHospitalsList();
    }).catch(err => toastError('Failed: ' + (err.message || err)));
}
window.clearAllData = clearAllData;

// ── Export CSV ─────────────────────────────────────────────────

function exportHospitalsCSV() {
    if (!_hospitals.length) {
        toastWarning('No hospitals to export.');
        return;
    }
    const headers = ['ID', 'Name', 'OrgUnit ID', 'Ownership', 'Facility Type', 'Governorate', 'Type', 'Address', 'Status'];
    const rows = _hospitals.map(h => [
        h.id,
        '"' + (h.name || '').replace(/"/g, '""') + '"',
        h.organisation_unit_id || '',
        '"' + (h.facility_ownership_name || '') + '"',
        '"' + (h.facility_type_name || '') + '"',
        '"' + (h.governorate_name || '') + '"',
        '"' + (h.hospital_type_name || '') + '"',
        '"' + (h.address || '').replace(/"/g, '""') + '"',
        h.is_active ? 'Active' : 'Inactive'
    ]);
    const csv = '\ufeff' + headers.join(',') + '\n' + rows.map(r => r.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'hospitals_export_' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(a.href);
}
window.exportHospitalsCSV = exportHospitalsCSV;


