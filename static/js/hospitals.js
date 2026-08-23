import { apiGet, apiPut, apiDelete, apiPostJSON } from './api.js';
import { esc } from './tree.js';

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
        t.style.color = t.dataset.subtab === name ? '#1a237e' : '#888';
        t.style.borderBottom = t.dataset.subtab === name ? '2px solid #1a237e' : '2px solid transparent';
    });
    document.querySelectorAll('.hosp-subtab-content').forEach(d => d.style.display = 'none');
    document.getElementById('hospSub-' + name).style.display = '';
}
window.switchHospSubtab = switchHospSubtab;

function loadHospitalsList() {
    apiGet('/hospitals/?include_inactive=true').then(data => {
        _hospitals = data || [];
        renderHospitals();
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
    const container = document.getElementById('hospList');
    if (!filtered.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No hospitals found.</div>';
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
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
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
            dataHtml = '<span style="color:#c62828;font-weight:600;">No Data</span>';
        } else {
            dataHtml = '<span style="color:#2e7d32;">' + ivCount + ' values</span>' +
                '<br><span style="font-size:0.72rem;color:#888;">' + monthCount + ' months, ' + qsCount + ' scores</span>';
        }
        const statusHtml = '<input type="checkbox" ' + (h.is_active ? 'checked' : '') + ' onchange="toggleHospitalActive(' + h.id + ', this.checked)"> ' + (h.is_active ? 'Active' : 'Inactive');
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(h.name) + (h.address ? '<br><span style="font-size:0.72rem;color:#999;">' + esc(h.address) + '</span>' : '') + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + esc(h.organisation_unit_id || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_ownership_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_type_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(govName) + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(typeName) + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' + dataHtml + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' + statusHtml + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospital(' + h.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospital(' + h.id + ')" style="color:#c62828;">Delete</button></td></tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}
window.filterHospitals = function() { renderHospitals(); };

function loadGovernorates() {
    apiGet('/governorates/').then(data => {
        _governorates = data || [];
        renderGovernorates();
        populateGovDropdowns();
    });
}

function renderGovernorates() {
    const container = document.getElementById('govList');
    if (!_governorates.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No governorates yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _governorates.forEach(g => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(g.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (g.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editGovernorate(' + g.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteGovernorate(' + g.id + ')" style="color:#c62828;">Delete</button></td></tr>';
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
    apiGet('/hospital-types/').then(data => {
        _types = data || [];
        renderHospitalTypes();
        populateTypeDropdowns();
    });
}

function renderHospitalTypes() {
    const container = document.getElementById('typeList');
    if (!_types.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No hospital types yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _types.forEach(t => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editHospitalType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteHospitalType(' + t.id + ')" style="color:#c62828;">Delete</button></td></tr>';
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
    if (!name) { alert('Name is required.'); return; }
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
    }).catch(err => alert('Failed: ' + err));
}
window.saveHospital = saveHospital;

function editHospital(id) {
    const h = _hospitals.find(x => x.id === id);
    if (h) showHospitalModal(h);
}
window.editHospital = editHospital;

function deleteHospital(id) {
    if (!confirm('Delete this hospital? This cannot be undone.')) return;
    apiDelete('/hospitals/' + id).then(() => loadHospitalsList()).catch(err => alert('Failed: ' + err));
}
window.deleteHospital = deleteHospital;

function toggleHospitalActive(id, active) {
    apiPut('/hospitals/' + id + '/toggle-active').then(() => loadHospitalsList()).catch(err => alert('Failed: ' + err));
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
    if (!name) { alert('Name is required.'); return; }
    const promise = _editGovId ? apiPut('/governorates/' + _editGovId, { name: name }) : apiPostJSON('/governorates/', { name: name });
    promise.then(() => {
        closeGovModal();
        loadGovernorates();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveGovernorate = saveGovernorate;

function editGovernorate(id) {
    const g = _governorates.find(x => x.id === id);
    if (g) showGovModal(g);
}
window.editGovernorate = editGovernorate;

function deleteGovernorate(id) {
    if (!confirm('Delete this governorate? Only possible if no hospitals are linked.')) return;
    apiDelete('/governorates/' + id).then(() => loadGovernorates()).catch(err => alert('Failed: ' + err));
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
    if (!name) { alert('Name is required.'); return; }
    const promise = _editTypeId ? apiPut('/hospital-types/' + _editTypeId, { name: name }) : apiPostJSON('/hospital-types/', { name: name });
    promise.then(() => {
        closeTypeModal();
        loadHospitalTypes();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveHospitalType = saveHospitalType;

function editHospitalType(id) {
    const t = _types.find(x => x.id === id);
    if (t) showTypeModal(t);
}
window.editHospitalType = editHospitalType;

function deleteHospitalType(id) {
    if (!confirm('Delete this hospital type? Only possible if no hospitals are linked.')) return;
    apiDelete('/hospital-types/' + id).then(() => loadHospitalTypes()).catch(err => alert('Failed: ' + err));
}
window.deleteHospitalType = deleteHospitalType;

// ── Facility Ownerships ──────────────────────────────────────────

function loadOwnerships() {
    apiGet('/facility-ownerships/').then(data => {
        _ownerships = data || [];
        renderOwnerships();
        populateOwnershipDropdowns();
    });
}

function renderOwnerships() {
    const container = document.getElementById('ownershipList');
    if (!_ownerships.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No facility ownerships yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _ownerships.forEach(o => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(o.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (o.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editOwnership(' + o.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteOwnership(' + o.id + ')" style="color:#c62828;">Delete</button></td></tr>';
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
    if (!name) { alert('Name is required.'); return; }
    const promise = _editOwnId ? apiPut('/facility-ownerships/' + _editOwnId, { name: name }) : apiPostJSON('/facility-ownerships/', { name: name });
    promise.then(() => {
        closeOwnershipModal();
        loadOwnerships();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveOwnership = saveOwnership;

function editOwnership(id) {
    const o = _ownerships.find(x => x.id === id);
    if (o) showOwnershipModal(o);
}
window.editOwnership = editOwnership;

function deleteOwnership(id) {
    if (!confirm('Delete this facility ownership? Only possible if no hospitals are linked.')) return;
    apiDelete('/facility-ownerships/' + id).then(() => loadOwnerships()).catch(err => alert('Failed: ' + err));
}
window.deleteOwnership = deleteOwnership;

// ── Facility Types ───────────────────────────────────────────────

function loadFacilityTypes() {
    apiGet('/facility-types/').then(data => {
        _facilityTypes = data || [];
        renderFacilityTypes();
        populateFacilityTypeDropdowns();
    });
}

function renderFacilityTypes() {
    const container = document.getElementById('facilityTypeList');
    if (!_facilityTypes.length) {
        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No facility types yet.</div>';
        return;
    }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
    _facilityTypes.forEach(t => {
        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
            '<td style="text-align:center;padding:0.4rem;">' +
            '<button class="btn btn-sm btn-outline" onclick="editFacilityType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
            '<button class="btn btn-sm btn-outline" onclick="deleteFacilityType(' + t.id + ')" style="color:#c62828;">Delete</button></td></tr>';
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
    if (!name) { alert('Name is required.'); return; }
    const promise = _editFacTypeId ? apiPut('/facility-types/' + _editFacTypeId, { name: name }) : apiPostJSON('/facility-types/', { name: name });
    promise.then(() => {
        closeFacilityTypeModal();
        loadFacilityTypes();
        loadHospitalsList();
    }).catch(err => alert('Failed: ' + err));
}
window.saveFacilityType = saveFacilityType;

function editFacilityType(id) {
    const t = _facilityTypes.find(x => x.id === id);
    if (t) showFacilityTypeModal(t);
}
window.editFacilityType = editFacilityType;

function deleteFacilityType(id) {
    if (!confirm('Delete this facility type? Only possible if no hospitals are linked.')) return;
    apiDelete('/facility-types/' + id).then(() => loadFacilityTypes()).catch(err => alert('Failed: ' + err));
}
window.deleteFacilityType = deleteFacilityType;

// ── Export CSV ─────────────────────────────────────────────────

function exportHospitalsCSV() {
    if (!_hospitals.length) {
        alert('No hospitals to export.');
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


