# Task 4 Review Package

## Commits
1e61a21 feat: extend hospitals UI with ownership, facility type, org unit fields

## Diff Stats
 static/js/hospitals.js     | 186 +++++++++++++++++++++++++++++++++++++++++++++
 static/tabs/hospitals.html |  43 +++++++++++
 2 files changed, 229 insertions(+)

## Full Diff
```
diff --git a/static/js/hospitals.js b/static/js/hospitals.js
index f4b2dd6..d93a3e5 100644
--- a/static/js/hospitals.js
+++ b/static/js/hospitals.js
@@ -1,22 +1,28 @@
 import { apiGet, apiPut, apiDelete, apiPostJSON } from './api.js';
 
 let _hospitals = [];
 let _governorates = [];
 let _types = [];
+let _ownerships = [];
+let _facilityTypes = [];
 let _editHospId = null;
 let _editGovId = null;
 let _editTypeId = null;
+let _editOwnId = null;
+let _editFacTypeId = null;
 
 export function loadHospitalsTab() {
     loadGovernorates();
     loadHospitalTypes();
+    loadOwnerships();
+    loadFacilityTypes();
     loadHospitalsList();
 }
 
 function switchHospSubtab(name) {
     document.querySelectorAll('.hosp-subtab').forEach(t => {
         t.style.color = t.dataset.subtab === name ? '#1a237e' : '#888';
         t.style.borderBottom = t.dataset.subtab === name ? '2px solid #1a237e' : '2px solid transparent';
     });
     document.querySelectorAll('.hosp-subtab-content').forEach(d => d.style.display = 'none');
     document.getElementById('hospSub-' + name).style.display = '';
@@ -27,43 +33,53 @@ function loadHospitalsList() {
     apiGet('/hospitals/?include_inactive=true').then(data => {
         _hospitals = data || [];
         renderHospitals();
     });
 }
 
 function renderHospitals() {
     const search = (document.getElementById('hospSearch').value || '').toLowerCase();
     const filterGov = document.getElementById('hospFilterGov').value;
     const filterType = document.getElementById('hospFilterType').value;
+    const filterOwn = document.getElementById('hospFilterOwnership').value;
+    const filterFacType = document.getElementById('hospFilterFacilityType').value;
     const filtered = _hospitals.filter(h => {
         if (search && !h.name.toLowerCase().includes(search)) return false;
         if (filterGov && String(h.governorate_id) !== filterGov) return false;
         if (filterType && String(h.hospital_type_id) !== filterType) return false;
+        if (filterOwn && String(h.facility_ownership_id) !== filterOwn) return false;
+        if (filterFacType && String(h.facility_type_id) !== filterFacType) return false;
         return true;
     });
     const container = document.getElementById('hospList');
     if (!filtered.length) {
         container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No hospitals found.</div>';
         return;
     }
     let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
         '<th style="text-align:left;padding:0.4rem;">Name</th>' +
+        '<th style="text-align:left;padding:0.4rem;">OrgUnit ID</th>' +
+        '<th style="text-align:left;padding:0.4rem;">Ownership</th>' +
+        '<th style="text-align:left;padding:0.4rem;">Facility Type</th>' +
         '<th style="text-align:left;padding:0.4rem;">Governorate</th>' +
         '<th style="text-align:left;padding:0.4rem;">Type</th>' +
         '<th style="text-align:center;padding:0.4rem;">Status</th>' +
         '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
     filtered.forEach(h => {
         const govName = h.governorate_name || '';
         const typeName = h.hospital_type_name || '';
         const statusHtml = '<input type="checkbox" ' + (h.is_active ? 'checked' : '') + ' onchange="toggleHospitalActive(' + h.id + ', this.checked)"> ' + (h.is_active ? 'Active' : 'Inactive');
         html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
             '<td style="padding:0.4rem;font-weight:600;">' + esc(h.name) + (h.address ? '<br><span style="font-size:0.72rem;color:#999;">' + esc(h.address) + '</span>' : '') + '</td>' +
+            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + esc(h.organisation_unit_id || '') + '</td>' +
+            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_ownership_name || '') + '</td>' +
+            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_type_name || '') + '</td>' +
             '<td style="padding:0.4rem;color:#555;">' + esc(govName) + '</td>' +
             '<td style="padding:0.4rem;color:#555;">' + esc(typeName) + '</td>' +
             '<td style="text-align:center;padding:0.4rem;">' + statusHtml + '</td>' +
             '<td style="text-align:center;padding:0.4rem;">' +
             '<button class="btn btn-sm btn-outline" onclick="editHospital(' + h.id + ')" style="margin-right:0.3rem;">Edit</button>' +
             '<button class="btn btn-sm btn-outline" onclick="deleteHospital(' + h.id + ')" style="color:#c62828;">Delete</button></td></tr>';
     });
     html += '</tbody></table>';
     container.innerHTML = html;
 }
@@ -152,39 +168,45 @@ function populateTypeDropdowns() {
         sel.value = val;
     });
 }
 
 function showHospitalModal(data) {
     _editHospId = data ? data.id : null;
     document.getElementById('hospModalTitle').textContent = data ? 'Edit Hospital' : 'Add Hospital';
     document.getElementById('hospFormName').value = data ? data.name : '';
     document.getElementById('hospFormGov').value = data ? data.governorate_id || '' : '';
     document.getElementById('hospFormType').value = data ? data.hospital_type_id || '' : '';
+    document.getElementById('hospFormOrgUnitId').value = data ? data.organisation_unit_id || '' : '';
+    document.getElementById('hospFormOwnership').value = data ? data.facility_ownership_id || '' : '';
+    document.getElementById('hospFormFacilityType').value = data ? data.facility_type_id || '' : '';
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
+        organisation_unit_id: document.getElementById('hospFormOrgUnitId').value.trim() || null,
+        facility_ownership_id: document.getElementById('hospFormOwnership').value ? parseInt(document.getElementById('hospFormOwnership').value) : null,
+        facility_type_id: document.getElementById('hospFormFacilityType').value ? parseInt(document.getElementById('hospFormFacilityType').value) : null,
         address: document.getElementById('hospFormAddress').value.trim() || null,
     };
     const promise = _editHospId ? apiPut('/hospitals/' + _editHospId, data) : apiPostJSON('/hospitals/', data);
     promise.then(() => {
         closeHospModal();
         loadHospitalsList();
     }).catch(err => alert('Failed: ' + err));
 }
 window.saveHospital = saveHospital;
 
@@ -274,14 +296,178 @@ function editHospitalType(id) {
     if (t) showTypeModal(t);
 }
 window.editHospitalType = editHospitalType;
 
 function deleteHospitalType(id) {
     if (!confirm('Delete this hospital type? Only possible if no hospitals are linked.')) return;
     apiDelete('/hospital-types/' + id).then(() => loadHospitalTypes()).catch(err => alert('Failed: ' + err));
 }
 window.deleteHospitalType = deleteHospitalType;
 
+// ٤?٤? Facility Ownerships ٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?
+
+function loadOwnerships() {
+    apiGet('/facility-ownerships/').then(data => {
+        _ownerships = data || [];
+        renderOwnerships();
+        populateOwnershipDropdowns();
+    });
+}
+
+function renderOwnerships() {
+    const container = document.getElementById('ownershipList');
+    if (!_ownerships.length) {
+        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No facility ownerships yet.</div>';
+        return;
+    }
+    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
+        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
+        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
+        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
+    _ownerships.forEach(o => {
+        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
+            '<td style="padding:0.4rem;font-weight:600;">' + esc(o.name) + '</td>' +
+            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (o.created_at || '') + '</td>' +
+            '<td style="text-align:center;padding:0.4rem;">' +
+            '<button class="btn btn-sm btn-outline" onclick="editOwnership(' + o.id + ')" style="margin-right:0.3rem;">Edit</button>' +
+            '<button class="btn btn-sm btn-outline" onclick="deleteOwnership(' + o.id + ')" style="color:#c62828;">Delete</button></td></tr>';
+    });
+    html += '</tbody></table>';
+    container.innerHTML = html;
+}
+
+function populateOwnershipDropdowns() {
+    const selects = ['hospFormOwnership', 'hospFilterOwnership'];
+    selects.forEach(sid => {
+        const sel = document.getElementById(sid);
+        if (!sel) return;
+        const val = sel.value;
+        sel.innerHTML = '<option value="">' + (sid === 'hospFormOwnership' ? '-- None --' : 'All Ownerships') + '</option>' +
+            _ownerships.map(o => '<option value="' + o.id + '">' + esc(o.name) + '</option>').join('');
+        sel.value = val;
+    });
+}
+
+function showOwnershipModal(data) {
+    _editOwnId = data ? data.id : null;
+    document.getElementById('ownershipModalTitle').textContent = data ? 'Edit Facility Ownership' : 'Add Facility Ownership';
+    document.getElementById('ownershipFormName').value = data ? data.name : '';
+    document.getElementById('ownershipModal').style.display = 'flex';
+}
+window.showOwnershipModal = showOwnershipModal;
+
+function closeOwnershipModal() {
+    document.getElementById('ownershipModal').style.display = 'none';
+    _editOwnId = null;
+}
+window.closeOwnershipModal = closeOwnershipModal;
+
+function saveOwnership() {
+    const name = document.getElementById('ownershipFormName').value.trim();
+    if (!name) { alert('Name is required.'); return; }
+    const promise = _editOwnId ? apiPut('/facility-ownerships/' + _editOwnId, { name: name }) : apiPostJSON('/facility-ownerships/', { name: name });
+    promise.then(() => {
+        closeOwnershipModal();
+        loadOwnerships();
+        loadHospitalsList();
+    }).catch(err => alert('Failed: ' + err));
+}
+window.saveOwnership = saveOwnership;
+
+function editOwnership(id) {
+    const o = _ownerships.find(x => x.id === id);
+    if (o) showOwnershipModal(o);
+}
+window.editOwnership = editOwnership;
+
+function deleteOwnership(id) {
+    if (!confirm('Delete this facility ownership? Only possible if no hospitals are linked.')) return;
+    apiDelete('/facility-ownerships/' + id).then(() => loadOwnerships()).catch(err => alert('Failed: ' + err));
+}
+window.deleteOwnership = deleteOwnership;
+
+// ٤?٤? Facility Types ٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?٤?
+
+function loadFacilityTypes() {
+    apiGet('/facility-types/').then(data => {
+        _facilityTypes = data || [];
+        renderFacilityTypes();
+        populateFacilityTypeDropdowns();
+    });
+}
+
+function renderFacilityTypes() {
+    const container = document.getElementById('facilityTypeList');
+    if (!_facilityTypes.length) {
+        container.innerHTML = '<div style="padding:1rem;text-align:center;color:#888;">No facility types yet.</div>';
+        return;
+    }
+    let html = '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;"><thead><tr style="background:#e8eaf6;">' +
+        '<th style="text-align:left;padding:0.4rem;">Name</th>' +
+        '<th style="text-align:left;padding:0.4rem;">Created</th>' +
+        '<th style="text-align:center;padding:0.4rem;">Actions</th></tr></thead><tbody>';
+    _facilityTypes.forEach(t => {
+        html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
+            '<td style="padding:0.4rem;font-weight:600;">' + esc(t.name) + '</td>' +
+            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + (t.created_at || '') + '</td>' +
+            '<td style="text-align:center;padding:0.4rem;">' +
+            '<button class="btn btn-sm btn-outline" onclick="editFacilityType(' + t.id + ')" style="margin-right:0.3rem;">Edit</button>' +
+            '<button class="btn btn-sm btn-outline" onclick="deleteFacilityType(' + t.id + ')" style="color:#c62828;">Delete</button></td></tr>';
+    });
+    html += '</tbody></table>';
+    container.innerHTML = html;
+}
+
+function populateFacilityTypeDropdowns() {
+    const selects = ['hospFormFacilityType', 'hospFilterFacilityType'];
+    selects.forEach(sid => {
+        const sel = document.getElementById(sid);
+        if (!sel) return;
+        const val = sel.value;
+        sel.innerHTML = '<option value="">' + (sid === 'hospFormFacilityType' ? '-- None --' : 'All Facility Types') + '</option>' +
+            _facilityTypes.map(t => '<option value="' + t.id + '">' + esc(t.name) + '</option>').join('');
+        sel.value = val;
+    });
+}
+
+function showFacilityTypeModal(data) {
+    _editFacTypeId = data ? data.id : null;
+    document.getElementById('facilityTypeModalTitle').textContent = data ? 'Edit Facility Type' : 'Add Facility Type';
+    document.getElementById('facilityTypeFormName').value = data ? data.name : '';
+    document.getElementById('facilityTypeModal').style.display = 'flex';
+}
+window.showFacilityTypeModal = showFacilityTypeModal;
+
+function closeFacilityTypeModal() {
+    document.getElementById('facilityTypeModal').style.display = 'none';
+    _editFacTypeId = null;
+}
+window.closeFacilityTypeModal = closeFacilityTypeModal;
+
+function saveFacilityType() {
+    const name = document.getElementById('facilityTypeFormName').value.trim();
+    if (!name) { alert('Name is required.'); return; }
+    const promise = _editFacTypeId ? apiPut('/facility-types/' + _editFacTypeId, { name: name }) : apiPostJSON('/facility-types/', { name: name });
+    promise.then(() => {
+        closeFacilityTypeModal();
+        loadFacilityTypes();
+        loadHospitalsList();
+    }).catch(err => alert('Failed: ' + err));
+}
+window.saveFacilityType = saveFacilityType;
+
+function editFacilityType(id) {
+    const t = _facilityTypes.find(x => x.id === id);
+    if (t) showFacilityTypeModal(t);
+}
+window.editFacilityType = editFacilityType;
+
+function deleteFacilityType(id) {
+    if (!confirm('Delete this facility type? Only possible if no hospitals are linked.')) return;
+    apiDelete('/facility-types/' + id).then(() => loadFacilityTypes()).catch(err => alert('Failed: ' + err));
+}
+window.deleteFacilityType = deleteFacilityType;
+
 function esc(s) {
     if (!s) return '';
     return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
 }
diff --git a/static/tabs/hospitals.html b/static/tabs/hospitals.html
index 10928f0..d702dec 100644
--- a/static/tabs/hospitals.html
+++ b/static/tabs/hospitals.html
@@ -1,51 +1,72 @@
 <div style="max-width:1000px;">
     <h2 style="color:#1a237e;margin-bottom:0.5rem;">Hospitals Management</h2>
 
     <div style="display:flex;gap:0.3rem;margin-bottom:1rem;border-bottom:2px solid #e0e0e0;">
         <button class="hosp-subtab active" data-subtab="hospitals" onclick="switchHospSubtab('hospitals')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#1a237e;border-bottom:2px solid #1a237e;margin-bottom:-2px;cursor:pointer;">Hospitals</button>
         <button class="hosp-subtab" data-subtab="governorates" onclick="switchHospSubtab('governorates')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Governorates</button>
         <button class="hosp-subtab" data-subtab="types" onclick="switchHospSubtab('types')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Hospital Types</button>
+        <button class="hosp-subtab" data-subtab="ownerships" onclick="switchHospSubtab('ownerships')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Ownerships</button>
+        <button class="hosp-subtab" data-subtab="facilitytypes" onclick="switchHospSubtab('facilitytypes')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Types</button>
     </div>
 
     <div id="hospSub-hospitals" class="hosp-subtab-content">
         <div style="display:flex;gap:0.5rem;margin-bottom:0.8rem;flex-wrap:wrap;align-items:center;">
             <button class="btn" onclick="showHospitalModal()" style="background:#1a237e;color:white;">+ Add Hospital</button>
             <input type="text" id="hospSearch" placeholder="Search by name..." oninput="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;width:200px;">
             <select id="hospFilterGov" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                 <option value="">All Governorates</option>
             </select>
             <select id="hospFilterType" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                 <option value="">All Types</option>
             </select>
+            <select id="hospFilterOwnership" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
+                <option value="">All Ownerships</option>
+            </select>
+            <select id="hospFilterFacilityType" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
+                <option value="">All Facility Types</option>
+            </select>
         </div>
         <div id="hospList" style="font-size:0.85rem;"></div>
     </div>
 
     <div id="hospSub-governorates" class="hosp-subtab-content" style="display:none;">
         <button class="btn" onclick="showGovModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Governorate</button>
         <div id="govList" style="font-size:0.85rem;"></div>
     </div>
 
     <div id="hospSub-types" class="hosp-subtab-content" style="display:none;">
         <button class="btn" onclick="showTypeModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Hospital Type</button>
         <div id="typeList" style="font-size:0.85rem;"></div>
     </div>
+
+    <div id="hospSub-ownerships" class="hosp-subtab-content" style="display:none;">
+        <button class="btn" onclick="showOwnershipModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Ownership</button>
+        <div id="ownershipList" style="font-size:0.85rem;"></div>
+    </div>
+
+    <div id="hospSub-facilitytypes" class="hosp-subtab-content" style="display:none;">
+        <button class="btn" onclick="showFacilityTypeModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Facility Type</button>
+        <div id="facilityTypeList" style="font-size:0.85rem;"></div>
+    </div>
 </div>
 
 <div id="hospModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
     <div style="background:white;border-radius:8px;padding:1.5rem;max-width:500px;width:90%;">
         <h3 id="hospModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Hospital</h3>
         <div style="display:flex;flex-direction:column;gap:0.6rem;">
             <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="hospFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
             <div><label style="font-size:0.8rem;color:#666;">Governorate</label><select id="hospFormGov" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
             <div><label style="font-size:0.8rem;color:#666;">Hospital Type</label><select id="hospFormType" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
+            <div><label style="font-size:0.8rem;color:#666;">Organisation Unit ID</label><input id="hospFormOrgUnitId" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
+            <div><label style="font-size:0.8rem;color:#666;">Facility Ownership</label><select id="hospFormOwnership" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
+            <div><label style="font-size:0.8rem;color:#666;">Facility Type</label><select id="hospFormFacilityType" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
             <div><label style="font-size:0.8rem;color:#666;">Address</label><textarea id="hospFormAddress" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;resize:vertical;" rows="2"></textarea></div>
         </div>
         <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
             <button class="btn btn-outline" onclick="closeHospModal()">Cancel</button>
             <button class="btn" onclick="saveHospital()" style="background:#1a237e;color:white;">Save</button>
         </div>
     </div>
 </div>
 
 <div id="govModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
@@ -61,11 +82,33 @@
 
 <div id="typeModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
     <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
         <h3 id="typeModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Hospital Type</h3>
         <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="typeFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
         <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
             <button class="btn btn-outline" onclick="closeTypeModal()">Cancel</button>
             <button class="btn" onclick="saveHospitalType()" style="background:#1a237e;color:white;">Save</button>
         </div>
     </div>
+</div>
+
+<div id="ownershipModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
+    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
+        <h3 id="ownershipModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Ownership</h3>
+        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="ownershipFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
+        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
+            <button class="btn btn-outline" onclick="closeOwnershipModal()">Cancel</button>
+            <button class="btn" onclick="saveOwnership()" style="background:#1a237e;color:white;">Save</button>
+        </div>
+    </div>
+</div>
+
+<div id="facilityTypeModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
+    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
+        <h3 id="facilityTypeModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Type</h3>
+        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="facilityTypeFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
+        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
+            <button class="btn btn-outline" onclick="closeFacilityTypeModal()">Cancel</button>
+            <button class="btn" onclick="saveFacilityType()" style="background:#1a237e;color:white;">Save</button>
+        </div>
+    </div>
 </div>
\ No newline at end of file
```
