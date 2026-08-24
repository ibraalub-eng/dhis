        export const API = () => document.getElementById('apiBase').value;
        export let uploadedData = null;

        const _apiCache = new Map();
        const _cacheableEndpoints = ['/hospitals/', '/analysis/months'];
        export async function apiGet(path, opts) {
            const noCache = opts?.noCache || !_cacheableEndpoints.includes(path);
            if (!noCache && _apiCache.has(path)) return _apiCache.get(path);
            const promise = fetch(API() + path).then(async res => {
                if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
                return res.json();
            });
            if (!noCache) promise.then(data => _apiCache.set(path, Promise.resolve(data)), () => _apiCache.delete(path));
            return promise;
        }
        export async function apiPost(path, data) {
            const res = await fetch(API() + path, { method: 'POST', body: data });
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }
        export async function apiPut(path, data) {
            const res = await fetch(API() + path, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }
        export async function apiDelete(path) {
            const res = await fetch(API() + path, { method: 'DELETE' });
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }
        export async function apiPostJSON(path, data) {
            const res = await fetch(API() + path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
            if (!res.ok) throw new Error('HTTP ' + res.status + ': ' + await res.text());
            return res.json();
        }
        export function clearApiCache() {
            _apiCache.clear();
        }

