### Task 4: Frontend — Hospitals Page Extension

**Status:** DONE

**Commits:**
- `1e61a21` — `feat: extend hospitals UI with ownership, facility type, org unit fields`

**Test Results:**
- `python -m pytest --tb=short -q` — **353 passed**, 0 failed

**Changes Made:**

`static/tabs/hospitals.html` (71 → 114 lines):
- Added 2 subtab buttons: Facility Ownerships, Facility Types
- Added 2 subtab content containers: `#hospSub-ownerships`, `#hospSub-facilitytypes`
- Added 2 filter dropdowns: `#hospFilterOwnership`, `#hospFilterFacilityType`
- Added 3 new fields to hospital form: OrgUnit ID (text), Facility Ownership (select), Facility Type (select)
- Added 2 modals: `#ownershipModal`, `#facilityTypeModal`

`static/js/hospitals.js` (287 → 473 lines):
- Added state variables: `_ownerships`, `_facilityTypes`, `_editOwnId`, `_editFacTypeId`
- `loadHospitalsTab()` now calls `loadOwnerships()` and `loadFacilityTypes()`
- `renderHospitals()` extended with 3 new columns (OrgUnit ID, Ownership, Facility Type) and 2 new filter conditions
- `showHospitalModal()` populates new fields from hospital data
- `saveHospital()` sends `organisation_unit_id`, `facility_ownership_id`, `facility_type_id` to API
- Added full CRUD for Facility Ownerships: `loadOwnerships`, `renderOwnerships`, `populateOwnershipDropdowns`, `showOwnershipModal`, `closeOwnershipModal`, `saveOwnership`, `editOwnership`, `deleteOwnership`
- Added full CRUD for Facility Types: `loadFacilityTypes`, `renderFacilityTypes`, `populateFacilityTypeDropdowns`, `showFacilityTypeModal`, `closeFacilityTypeModal`, `saveFacilityType`, `editFacilityType`, `deleteFacilityType`
- All new functions properly exposed via `window.*` for onclick handlers

**Concerns:** None. All patterns followed existing conventions exactly. All tests pass.
