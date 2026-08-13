// @odoo-module ignore
/* eslint-disable no-restricted-globals */
/* eslint-disable no-undef */

// Cache that holds POS app-shell assets (same name as stock SW so the existing
// cache is reused on upgrade — no cold-start gap when dukaku_offline installs).
const CACHE_NAME = "odoo-pos-cache";

// Separate metadata cache: persists the urlsToCache list across SW restarts so
// the install event can pre-cache without waiting for the page to mount.
const CONFIG_CACHE = "dukaku-pos-config";
const CONFIG_KEY = "urlsToCache";

// ── Install: pre-cache app shell from last known URL list ─────────────────────
// Runs when the SW is first installed or after an update.  On the very first
// install (no prior session) the CONFIG_CACHE is empty and we skip gracefully.
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CONFIG_CACHE).then(async (configCache) => {
            const stored = await configCache.match(CONFIG_KEY);
            if (!stored) {
                return; // first-ever install, nothing stored yet
            }
            let urls;
            try {
                urls = await stored.json();
            } catch {
                return;
            }
            if (!Array.isArray(urls) || !urls.length) {
                return;
            }
            const appCache = await caches.open(CACHE_NAME);
            await Promise.allSettled(
                urls.map((url) =>
                    appCache.add(url).catch((err) => {
                        // Auth-gated URLs may 302 to login during SW install;
                        // log and continue — the fetch handler will repopulate
                        // once the user is authenticated.
                        console.info("[dukaku-sw] pre-cache skipped", url, err);
                    })
                )
            );
        })
    );
});

// ── Activate: take control immediately so updated SW serves current tabs ──────
self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

// Deep POS URLs are /pos/ui/<config_id>[/<subpath>]; the cached shell for
// that config is always the bare /pos/ui/<config_id> (see pos_config.py
// _get_url_to_cache — matches the manifest start_url character-for-character).
// Parsing config_id out of the failed request keeps this multi-config safe
// with no hardcoding, consistent with the rest of this addon.
const getShellUrlForRequest = (requestUrl) => {
    const { origin, pathname } = new URL(requestUrl);
    const match = pathname.match(/^\/pos\/ui\/(\d+)(?:\/|$)/);
    return match ? `${origin}/pos/ui/${match[1]}` : null;
};

// ── Fetch: network-first with cache fallback (stock strategy, unchanged) ─────
// Data calls (web/dataset) are explicitly excluded — the SW handles assets
// only; the IndexedDB queue handles data.  This boundary must not change.
const fetchCacheRespond = async (event) => {
    const cache = await caches.open(CACHE_NAME);
    try {
        const response = await fetch(event.request);
        // Only cache successful responses — never cache 4xx/5xx/redirects.
        // Caching error responses caused a hard-to-diagnose manifest 404
        // getting served from cache indefinitely after the route was fixed.
        if (response.ok) {
            const clone = response.clone();
            const cloneHeaders = new Headers(response.headers);
            cloneHeaders.delete('cache-control');
            cloneHeaders.delete('content-encoding');
            cloneHeaders.delete('transfer-encoding');
            event.waitUntil(
                clone.arrayBuffer().then(buf =>
                    cache.put(event.request, new Response(buf, {
                        status: response.status,
                        statusText: response.statusText,
                        headers: cloneHeaders,
                    }))
                )
            );
        }
        // Always return the network response regardless of status — the fetch
        // handler must never return undefined.
        return response;
    } catch {
        // Offline path: return cached copy if available, otherwise a proper
        // 504 Response.  cache.match returns undefined on a miss, and a fetch
        // handler returning undefined throws TypeError in all browsers.
        const cached = await cache.match(event.request);
        if (cached) {
            return cached;
        }
        // Navigation-only shell fallback: a real page navigation (not a
        // sub-resource fetch) to a deep URL never cached verbatim, e.g.
        // /pos/ui/1/product/<uuid>.  event.request.mode is "navigate" only
        // for top-level document loads, so this branch is unreachable for
        // JS/CSS/image/API sub-resource requests — they keep failing
        // normally below instead of silently getting shell content.
        if (event.request.mode === "navigate") {
            const shellUrl = getShellUrlForRequest(event.request.url);
            if (shellUrl) {
                const shell = await cache.match(shellUrl);
                if (shell) {
                    return shell;
                }
            }
        }
        return new Response("", {
            status: 504,
            statusText: "Offline and not cached",
        });
    }
};

const cacheResources = async (event) => {
    const url = event.request.url;
    try {
        const cache = await caches.open(CACHE_NAME);
        await cache.add(url);
    } catch (error) {
        console.info("[dukaku-sw] failed to cache resource", url, error);
    }
};

self.addEventListener("fetch", (event) => {
    const url = event.request.url;

    // Exclusions carried over from stock SW verbatim.
    if (
        url.includes("extension") ||
        url.includes("web/dataset") ||
        url.includes("hw_proxy/hello") ||
        url.includes("Cashdro3WS/index3.php") ||
        event.request.method !== "GET"
    ) {
        return;
    }

    event.respondWith(fetchCacheRespond(event));
});

// ── Message: cache urlsToCache AND persist the list for future install events ─
self.addEventListener("message", (event) => {
    const data = event.data;
    if (data.urlsToCache && navigator.onLine) {
        event.waitUntil((async () => {
            // Persist the list so the install event can pre-cache after a SW update.
            const configCache = await caches.open(CONFIG_CACHE);
            await configCache.put(
                CONFIG_KEY,
                new Response(JSON.stringify(data.urlsToCache), {
                    headers: { "Content-Type": "application/json" },
                })
            );
            // Cache each URL now (stock behaviour).
            await Promise.allSettled(
                data.urlsToCache.map((url) => cacheResources({ request: { url } }))
            );
        })());
    }
});
