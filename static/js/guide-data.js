// ── The Data-section guide inventory ─────────────────────────────────────────
// One module per screen keeps every guide independently readable and editable;
// this file only fixes their order (the sidebar order of the Data group).
import upload from './guides/upload.js';
import dataTree from './guides/data-tree.js';
import dataGroups from './guides/data-groups.js';
import indicators from './guides/indicators.js';
import rules from './guides/rules.js';
import directionCoverage from './guides/direction-coverage.js';

export const DATA_GUIDES = [
    upload,
    dataTree,
    dataGroups,
    indicators,
    rules,
    directionCoverage,
];

export function guideByKey(key) {
    return DATA_GUIDES.find(g => g.key === key) || null;
}

export function guideIndex(key) {
    return DATA_GUIDES.findIndex(g => g.key === key);
}
