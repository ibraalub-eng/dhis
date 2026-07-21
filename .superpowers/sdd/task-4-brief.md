### Task 4: Frontend — Hospitals Page Extension

**Files:**
- Modify: `static/tabs/hospitals.html`
- Modify: `static/js/hospitals.js`

- [ ] **Step 1: Add subtab buttons for Facility Ownerships and Facility Types**

In `static/tabs/hospitals.html`, add two more buttons to the subtab bar (after the "Hospital Types" button):

```html
        <button class="hosp-subtab" data-subtab="ownerships" onclick="switchHospSubtab('ownerships')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Ownerships</button>
        <button class="hosp-subtab" data-subtab="facilitytypes" onclick="switchHospSubtab('facilitytypes')" style="padding:0.4rem 1rem;border:none;background:none;font-weight:600;color:#888;cursor:pointer;">Facility Types</button>
```

- [ ] **Step 2: Add subtab content containers**

After the `#hospSub-types` div, add:

```html
    <div id="hospSub-ownerships" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showOwnershipModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Ownership</button>
        <div id="ownershipList" style="font-size:0.85rem;"></div>
    </div>

    <div id="hospSub-facilitytypes" class="hosp-subtab-content" style="display:none;">
        <button class="btn" onclick="showFacilityTypeModal()" style="background:#1a237e;color:white;margin-bottom:0.8rem;">+ Add Facility Type</button>
        <div id="facilityTypeList" style="font-size:0.85rem;"></div>
    </div>
```

- [ ] **Step 3: Add modals for Ownership and Facility Type**

After the `#typeModal` div, add:

```html
<div id="ownershipModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="ownershipModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Ownership</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="ownershipFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeOwnershipModal()">Cancel</button>
            <button class="btn" onclick="saveOwnership()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>

<div id="facilityTypeModal" class="modal-overlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:white;border-radius:8px;padding:1.5rem;max-width:400px;width:90%;">
        <h3 id="facilityTypeModalTitle" style="color:#1a237e;margin-bottom:1rem;">Add Facility Type</h3>
        <div><label style="font-size:0.8rem;color:#666;">Name</label><input id="facilityTypeFormName" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
        <div style="display:flex;gap:0.5rem;margin-top:1rem;justify-content:flex-end;">
            <button class="btn btn-outline" onclick="closeFacilityTypeModal()">Cancel</button>
            <button class="btn" onclick="saveFacilityType()" style="background:#1a237e;color:white;">Save</button>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Extend hospital form modal with new fields**

In the `#hospModal` section, add fields before the Address field:

```html
            <div><label style="font-size:0.8rem;color:#666;">Organisation Unit ID</label><input id="hospFormOrgUnitId" type="text" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"></div>
            <div><label style="font-size:0.8rem;color:#666;">Facility Ownership</label><select id="hospFormOwnership" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
            <div><label style="font-size:0.8rem;color:#666;">Facility Type</label><select id="hospFormFacilityType" style="width:100%;padding:0.4rem;border:1px solid #ccc;border-radius:4px;"><option value="">-- None --</option></select></div>
```

- [ ] **Step 5: Add new columns to hospitals table**

In `renderHospitals()` JS function, add columns after the "Name" column header:
```javascript
        '<th style="text-align:left;padding:0.4rem;">OrgUnit ID</th>' +
        '<th style="text-align:left;padding:0.4rem;">Ownership</th>' +
        '<th style="text-align:left;padding:0.4rem;">Facility Type</th>' +
```

And add cells in the row render loop (after the name cell):
```javascript
            '<td style="padding:0.4rem;color:#888;font-size:0.78rem;">' + esc(h.organisation_unit_id || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_ownership_name || '') + '</td>' +
            '<td style="padding:0.4rem;color:#555;">' + esc(h.facility_type_name || '') + '</td>' +
```

- [ ] **Step 6: Add ownership dropdown filter**

In the filter bar, add after the type filter:
```html
            <select id="hospFilterOwnership" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Ownerships</option>
            </select>
            <select id="hospFilterFacilityType" onchange="filterHospitals()" style="padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;">
                <option value="">All Facility Types</option>
            </select>
```

And in `renderHospitals()` add filter logic:
```javascript
    const filterOwn = document.getElementById('hospFilterOwnership').value;
    const filterFacType = document.getElementById('hospFilterFacilityType').value;
    // ... add to filter: if (filterOwn && String(h.facility_ownership_id) !== filterOwn) return false;
    // ... if (filterFacType && String(h.facility_type_id) !== filterFacType) return false;
```

- [ ] **Step 7: Add JS CRUD functions for Ownerships**

In `static/js/hospitals.js`, add after `deleteHospitalType()`:

```javascript
// ── Facility Ownerships ──────────────────────────────────────────
let _ownerships = [];
let _editOwnId = null;

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
```

- [ ] **Step 8: Add JS CRUD functions for Facility Types**

Same pattern as Step 7, but for `/facility-types/`:
- `_facilityTypes = []`, `_editFacTypeId = null`
- `loadFacilityTypes()`, `renderFacilityTypes()`, `populateFacilityTypeDropdowns()`
- `showFacilityTypeModal()`, `closeFacilityTypeModal()`, `saveFacilityType()`, `editFacilityType(id)`, `deleteFacilityType(id)`
- Target container: `facilityTypeList`
- Form: `facilityTypeFormName`, `facilityTypeModal`, `facilityTypeModalTitle`
- API: `/facility-types/`

- [ ] **Step 9: Wire hospital form to include new fields**

In `showHospitalModal()` add:
```javascript
    document.getElementById('hospFormOrgUnitId').value = data ? data.organisation_unit_id || '' : '';
    document.getElementById('hospFormOwnership').value = data ? data.facility_ownership_id || '' : '';
    document.getElementById('hospFormFacilityType').value = data ? data.facility_type_id || '' : '';
```

In `saveHospital()` add to the data object:
```javascript
        organisation_unit_id: document.getElementById('hospFormOrgUnitId').value.trim() || null,
        facility_ownership_id: document.getElementById('hospFormOwnership').value ? parseInt(document.getElementById('hospFormOwnership').value) : null,
        facility_type_id: document.getElementById('hospFormFacilityType').value ? parseInt(document.getElementById('hospFormFacilityType').value) : null,
```

- [ ] **Step 10: Wire load functions in `loadHospitalsTab()`**

Add calls at the end of the function:
```javascript
    loadOwnerships();
    loadFacilityTypes();
```

- [ ] **Step 11: Add new filter load in `loadHospitalsTab()` (after populateTypeDropdowns)**

The dropdowns will be populated by `populateOwnershipDropdowns()` and `populateFacilityTypeDropdowns()` which are called from `loadOwnerships()` and `loadFacilityTypes()` respectively. The filter values should reset properly — the existing pattern already handles this via `sel.value = val`.

- [ ] **Step 12: Run full test suite to verify no regressions**

Run: `python -m pytest --tb=short -q`
Expected: all tests pass (should be ~350 with the new test module)

- [ ] **Step 13: Commit**

```bash
git add static/tabs/hospitals.html static/js/hospitals.js
git commit -m "feat: extend hospitals UI with ownership, facility type, org unit fields"
```

---
