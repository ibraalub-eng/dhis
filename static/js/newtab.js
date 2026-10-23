/**
 * newtab.js — open an app screen in a NEW browser tab.
 *
 * The app is a single-page shell: `switchTab(name)` replaces the screen you
 * are looking at. A button inside a modal that leads to another screen used to
 * do exactly that, so the screen the modal belonged to (with its filters,
 * scroll position and open charts) was gone.
 *
 * Those buttons now open `<app>/dashboard?screen=<tab>&…` in a new browser
 * tab. `main.js::applyBootScreen` reads the params when that tab loads,
 * switches to the screen and replays the context (audit hospital/month and
 * scroll target, root-cause hospital/month, audit trail query).
 *
 * Usage (module code):
 *   import { openScreenInNewTab } from './newtab.js';
 *   openScreenInNewTab('audit', { hospital_id: 5, month: '2026-04', mode: 'why' });
 *
 * Usage (inline onclick, no imports):
 *   window.openScreenInNewTab('indicators')
 */

const SCREEN_PATH = '/dashboard';

export function screenUrl(screen, params) {
    const url = new URL(SCREEN_PATH, window.location.origin);
    if (screen) url.searchParams.set('screen', screen);
    Object.keys(params || {}).forEach(function (key) {
        const value = params[key];
        // null/undefined/'' = "no context for this screen", not a filter value
        if (value === undefined || value === null || value === '') return;
        url.searchParams.set(key, String(value));
    });
    return url.toString();
}

export function openScreenInNewTab(screen, params) {
    const url = screenUrl(screen, params);
    // A real anchor with target=_blank is the dependable way to open a new
    // tab. window.open() returns null in several popup / noopener
    // configurations even though the tab really opens, so any "did it work?"
    // fallback on its return value would open a second copy in this tab and
    // lose the screen we are trying to preserve.
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.target = '_blank';
    anchor.rel = 'noopener';
    anchor.style.display = 'none';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    return url;
}

window.screenUrl = screenUrl;
window.openScreenInNewTab = openScreenInNewTab;
