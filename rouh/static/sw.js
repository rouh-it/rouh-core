/* Rouh's service worker: the page, and the person's own copy of what it shows, with no
   connection (`rouh/offline.py`, app/offline.js, card 1457, 12 October 2026).

   Served at /sw.js by `rouh/web/offline.py`, which writes the build and the page's files
   into it, so every deploy is a new worker that the browser installs by itself.

   What it keeps, and for whom:

   - The page's own files, at their hashed addresses (`rouh/web/assets.py`). They are
     the same for everybody and hold nothing of anybody's, so they are kept as they are,
     one cache per build, and the old builds' caches go when a new worker takes over.

   - The page itself, and what the canvas reads (a task's page, the task browser, the
     cards, the decisions), each kept when it was last fetched with a connection and
     handed back only when there is none. These are the signed-in person's own, so they
     are kept sealed - AES-GCM, under the key their own page made and keeps in IndexedDB
     where no script can read it out (app/offline.js) - and only under the person the
     page says it belongs to (`X-Rouh-Owner`). A page served for anybody else clears
     them; signing out clears them and the key with them; nothing of a page shared with
     somebody else (`/p/`, `/shared/`, `/join/`) or anything signed out is kept at all.

   Nothing here runs in the background: it answers the page's own requests, and that is
   all. An iPhone gives a web app no background time, and this does not pretend otherwise. */
'use strict';

var BUILD = "__ROUH_BUILD__";
var SHELL = "__ROUH_SHELL__";
var STATIC = 'rouh-static-' + BUILD;
var PAGE = 'rouh-page';
var DATA = 'rouh-data';
var SHELL_KEY = '/__rouh_shell__';
var DB = 'rouh-offline';
/* A response bigger than this is not kept: a page's pictures belong to the page, not the copy. */
var MOST = 5 * 1024 * 1024;

/* The page's own addresses, which are all one page (`rouh/project/urls.py`). */
var NEVER = /^\/(login|logout|admin|api|auth|hooks|internal|p|shared|join|a|static|healthz|sw\.js|attachments|mail|settings\/mail-alerts\/log|gaps|workspace)(\/|$)/;
/* What the canvas reads, kept for reading with no connection: the task browser, a task's page
   and its steps' pages, the cards, the decisions, Clockwork, the goals, the Control Room, and
   the quests with each quest's own page. */
var KEPT = /^\/(api\/(workspace\/(index|task|step)|canvas\/(cards|card|drawn)|decisions(\/[A-Za-z0-9]+)?|reminders|goals|control|quests(\/\d+)?)$|workspace\/)/;

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(STATIC).then(function (cache) {
    // One at a time and each on its own, so one file that fails is one file missing
    // rather than no copy at all.
    return Promise.all((Array.isArray(SHELL) ? SHELL : []).map(function (url) {
      return cache.add(new Request(url, { credentials: 'same-origin' })).catch(function () {});
    }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (n) {
      return n.indexOf('rouh-static-') === 0 && n !== STATIC;
    }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

/* --- whose copy it is, and the key it is sealed with -------------------------------- */

var owner = '';
var ownerRead = null;

function idb() {
  return new Promise(function (resolve, reject) {
    var req = indexedDB.open(DB, 1);
    req.onupgradeneeded = function () {
      var db = req.result;
      if (!db.objectStoreNames.contains('keys')) db.createObjectStore('keys');
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
      if (!db.objectStoreNames.contains('outbox')) db.createObjectStore('outbox');
    };
    req.onsuccess = function () { resolve(req.result); };
    req.onerror = function () { reject(req.error); };
  });
}

function idbGet(store, key) {
  return idb().then(function (db) {
    return new Promise(function (resolve) {
      var tx = db.transaction(store, 'readonly');
      var req = tx.objectStore(store).get(key);
      req.onsuccess = function () { resolve(req.result); db.close(); };
      req.onerror = function () { resolve(undefined); db.close(); };
    });
  }).catch(function () { return undefined; });
}

function idbPut(store, key, value) {
  return idb().then(function (db) {
    return new Promise(function (resolve) {
      var tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).put(value, key);
      tx.oncomplete = function () { resolve(true); db.close(); };
      tx.onerror = function () { resolve(false); db.close(); };
    });
  }).catch(function () { return false; });
}

function currentOwner() {
  if (owner) return Promise.resolve(owner);
  if (!ownerRead) {
    ownerRead = idbGet('kv', 'sw:owner').then(function (o) { owner = o || ''; return owner; });
  }
  return ownerRead;
}

function keyOf(who) {
  if (!who) return Promise.resolve(null);
  return idbGet('keys', who).then(function (k) { return k || null; });
}

function forget() {
  return Promise.all([caches.delete(PAGE), caches.delete(DATA)]);
}

/* A page for another person: what was kept goes, before anything is kept for them. */
function takeOwner(who) {
  return currentOwner().then(function (was) {
    if (was === who) return;
    owner = who;
    ownerRead = Promise.resolve(who);
    return (was ? forget() : Promise.resolve()).then(function () { return idbPut('kv', 'sw:owner', who); });
  });
}

self.addEventListener('message', function (event) {
  var m = event.data || {};
  if (m.type === 'rouh-owner' && typeof m.owner === 'string') {
    event.waitUntil(takeOwner(m.owner));
  } else if (m.type === 'rouh-keep-page') {
    // The page as it is now, kept for opening with no connection. Asked for by the page
    // itself, because the visit that installed this worker was not one it answered.
    event.waitUntil(keepPage());
  } else if (m.type === 'rouh-prime' && typeof m.url === 'string' && KEPT.test(m.url.split('?')[0])
             && typeof m.body === 'string') {
    // What a page reads, as it is after something done on it with no connection, so the page
    // drawn again from the copy shows it (`primeCopy` in app/offline.js). Only an address this
    // worker keeps anyway, sealed the same way.
    event.waitUntil(currentOwner().then(function (who) {
      if (!who) return;
      var res = new Response(m.body, { headers: { 'Content-Type': 'application/json' } });
      return keep(DATA, m.url, res, who);
    }));
  } else if (m.type === 'rouh-forget') {
    // Signed out: the page deletes the store itself, so nothing is written back into it.
    owner = '';
    ownerRead = Promise.resolve('');
    event.waitUntil(forget());
  }
});

function keepPage() {
  return fetch('/', { credentials: 'same-origin', cache: 'no-store' }).then(function (res) {
    var who = res.headers.get('X-Rouh-Owner') || '';
    if (!res.ok || !who || res.redirected) return;
    return takeOwner(who).then(function () { return keep(PAGE, SHELL_KEY, res, who); });
  }).catch(function () {});
}

/* --- sealed keeping ------------------------------------------------------------------ */

function seal(key, response) {
  return response.arrayBuffer().then(function (body) {
    if (body.byteLength > MOST) return null;
    var iv = crypto.getRandomValues(new Uint8Array(12));
    return crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv }, key, body).then(function (sealed) {
      var out = new Uint8Array(12 + sealed.byteLength);
      out.set(iv, 0);
      out.set(new Uint8Array(sealed), 12);
      return new Response(out, { headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream',
        'X-Rouh-Sealed': '1',
        'X-Rouh-Kept': String(Date.now())
      } });
    });
  });
}

function unseal(key, kept) {
  return kept.arrayBuffer().then(function (all) {
    var bytes = new Uint8Array(all);
    return crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.slice(0, 12) }, key, bytes.slice(12));
  }).then(function (body) {
    return new Response(body, { headers: {
      'Content-Type': kept.headers.get('Content-Type') || 'application/octet-stream',
      'X-Rouh-Offline': kept.headers.get('X-Rouh-Kept') || '1'
    } });
  });
}

function keep(cacheName, cacheKey, response, who) {
  return keyOf(who).then(function (key) {
    if (!key) return;
    return seal(key, response).then(function (sealed) {
      if (!sealed) return;
      return caches.open(cacheName).then(function (c) { return c.put(cacheKey, sealed); });
    });
  }).catch(function () {});
}

function kept(cacheName, cacheKey) {
  return currentOwner().then(function (who) {
    if (!who) return null;
    return Promise.all([keyOf(who), caches.open(cacheName).then(function (c) { return c.match(cacheKey); })])
      .then(function (both) {
        if (!both[0] || !both[1]) return null;
        return unseal(both[0], both[1]).catch(function () { return null; });
      });
  });
}

/* A kept page is handed back only when it carries demo mode's style and first script in its
   head (`rouh/demo_style.py`): a page kept before they were there would open with no
   connection and nothing to blur it, whatever demo mode this browser is in. */
function withDemoHead(hit) {
  if (!hit) return null;
  return hit.text().then(function (body) {
    if (body.indexOf('id="demoStyle"') < 0) return null;
    return new Response(body, { headers: { 'Content-Type': hit.headers.get('Content-Type') || 'text/html; charset=utf-8',
      'X-Rouh-Offline': hit.headers.get('X-Rouh-Offline') || '1' } });
  }).catch(function () { return null; });
}

/* --- answering ----------------------------------------------------------------------- */

var NO_COPY = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  + '<title>Rouh</title><body style="background:#0a0c10;color:#e8ecf1;font:16px system-ui;padding:40px 20px;max-width:34em;margin:auto">'
  + '<h1 style="font-size:20px">Rouh is offline</h1><p>There is no connection, and this device has no copy of Rouh '
  + 'yet. Open Rouh once with a connection, signed in, and it keeps one from then on.</p>'
  + '<p><button onclick="location.reload()" style="font:inherit;padding:8px 14px;border-radius:8px">Try again</button></p>';

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  var path = url.pathname;

  // The page's own files: the copy first, and the network for one not kept yet. Looked for
  // in this build's own cache alone: `caches.match` searches every cache, the copy's hundreds
  // of sealed pages too, and with the query ignored that is a scan of each, for each of the
  // page's hundred files. Every other request the page made as it opened - the canvas's
  // cards among them - waited in line behind those scans: a second and a half for an answer
  // the server gave in ten milliseconds (23 October 2026).
  if (path.indexOf('/a/') === 0) {
    event.respondWith(caches.open(STATIC).then(function (c) {
      return c.match(req, { ignoreSearch: true });
    }).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        if (res.ok && (res.headers.get('Cache-Control') || '').indexOf('immutable') >= 0) {
          var copy = res.clone();
          caches.open(STATIC).then(function (c) { c.put(req, copy); });
        }
        return res;
      });
    }));
    return;
  }

  // The page, at any of its addresses: the network first, and the person's own copy of it
  // when there is none.
  if (req.mode === 'navigate' && !NEVER.test(path)) {
    event.respondWith(fetch(req).then(function (res) {
      var who = res.headers.get('X-Rouh-Owner') || '';
      if (res.ok && who && !res.redirected) {
        var copy = res.clone();
        event.waitUntil(takeOwner(who).then(function () { return keep(PAGE, SHELL_KEY, copy, who); }));
      }
      return res;
    }).catch(function () {
      return kept(PAGE, SHELL_KEY).then(withDemoHead).then(function (hit) {
        return hit || new Response(NO_COPY, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      });
    }));
    return;
  }

  // What the canvas reads: the network first, the sealed copy with no connection. Not a whole
  // tab opened onto a page's file - a link on a task's page pressed with the middle button, or
  // Open link in new tab: the server sends that on to Rouh's own address for it only when the
  // browser says it is a tab's own load (`_opened_in_a_tab` in rouh/web/views.py), which a
  // fetch from here does not, so the tab was left on the bare page (fr_7407619a2fbc).
  if (KEPT.test(path) && !(req.mode === 'navigate' && req.destination === 'document')) {
    event.respondWith(fetch(req).then(function (res) {
      if (res.ok && res.status === 200 && !res.redirected) {
        var copy = res.clone();
        // A page on the canvas that names its pictures by their own addresses
        // (`rouh/picturelinks.py`) is no copy to read with no connection, whose
        // pictures could not load: it is kept only where there is no copy at all,
        // and never over the whole one the device reads for itself (`offline.js`).
        var linked = res.headers.get('X-Rouh-Pictures') === 'linked';
        event.waitUntil(currentOwner().then(function (who) {
          if (!who) return;
          if (!linked) return keep(DATA, url.pathname + url.search, copy, who);
          return caches.open(DATA).then(function (c) { return c.match(url.pathname + url.search); })
            .then(function (had) { if (!had) return keep(DATA, url.pathname + url.search, copy, who); });
        }));
      }
      return res;
    }).catch(function (err) {
      return kept(DATA, url.pathname + url.search).then(function (hit) {
        if (hit) return hit;
        throw err;
      });
    }));
  }
});
