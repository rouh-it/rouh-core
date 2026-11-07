/* Rouh's page, offline: this device's copy, the outbox, and saying which it is
 * (`rouh/offline.py`, card 1457, 12 October 2026).
 *
 * Imports app/settings.js first so that it runs after it and before the
 * socket, which hands it what it hears (`offlineHeard`): app.js says why the
 * order matters. Its top level only reads who is signed in, opens its store
 * and wires its own pill; everything else waits for the socket.
 *
 * Petar, on the plan "Rouh offline, on laptop and phone": "Do it". So the page
 * keeps working with no connection, and what he does with none is kept and
 * carried out once he has one again. Four parts, all here:
 *
 * - **The store.** One IndexedDB database, `rouh-offline`, shared with the
 *   service worker (`rouh/static/sw.js`). Everything of his in it is sealed
 *   with AES-GCM under a key this page makes with WebCrypto as not
 *   extractable, so no script, his own included, can read the key out, and a
 *   copy of the browser's files is ciphertext without the browser that made
 *   it. It belongs to the person the page says it is for (`rouh-owner`): a
 *   page for anybody else clears it before it keeps anything, and signing out
 *   deletes it and the key with it.
 *
 * - **The copy.** What the handshake and the lists after it said (`KEEP`),
 *   so a page opened with no connection draws the chats, the transcript with
 *   its cards, the task list and the canvas exactly as it last saw them, by
 *   handing the same messages to the same code (`offlineReplay`). And the
 *   offline pack, kind by kind in Petar's order (`KINDS`): the server's parts
 *   from `/api/offline/pack/<part>`, and Clockwork, the goals, the quests and
 *   the pages of the tasks kept whole read as their own pages read them, so
 *   the service worker keeps them. The same on every device; one short of room
 *   leaves out the last kinds first and says so. Refreshed while the page is
 *   open (`packRefresh`): when it opens, when it comes back into view, and
 *   every few minutes. Never in the background: a browser on an iPhone gives
 *   a web app none, and the panel says so.
 *
 * - **The outbox.** Every action taken with no connection (`offlineQueue`) -
 *   on the Offline page, and on Clockwork, a goal's or a quest's own page and
 *   the Gene therapy drawer, which hand theirs here (`window.RouhOffline`) -
 *   with an id of its own, this device, the time and the version of what it
 *   acted on, kept until the server says what became of it, and sent the
 *   moment there is a connection (`outboxFlush`).
 *
 * - **Saying so.** One pill says Offline, Evolving or Reconnecting while there
 *   is no connection, turns green and says Alive (Evolved, after a deploy)
 *   for a moment when it is back, and says how many actions wait; it opens the Offline page
 *   (app/offlineview.js), which shows all of the above. Its words are
 *   `CONN_WORDS` in app/socket.js.
 */
import 'app/settings.js';
import { $ } from 'app/helpers.js';
import { notify } from 'app/notices.js';
import { CONN_WORDS, handleMessage, S, setConn } from 'app/socket.js';
import { ADDR, addrOffline } from 'app/address.js';
import { browserOfflineSay } from 'app/cards.js';
import { offlineOpen, offlinePaint, offlineViewing } from 'app/offlineview.js';

var DB_NAME = 'rouh-offline';
//: What the handshake and the lists after it said, kept so the page can be drawn again.
var KEEP = { ready: true, chats: true, objects: true, workspace: true, tasks: true, decisions: true };
//: How often the copy is made again while the page is open, and the least time between two.
var EVERY_MS = 15 * 60 * 1000;
var AGAIN_MS = 2 * 60 * 1000;
//: How long the pill stays green, saying Alive, once the connection is back.
var BACK_MS = 4000;
//: How long the green pill takes to fade, as offline.css has it.
var FADE_MS = 450;

var OFF = {
  owner: '',
  device: { id: '', name: '', kind: 'laptop' },
  //: The socket has said `ready` on this page since it opened (or since it last dropped).
  socketUp: false,
  //: The live server has drawn this page at least once since it opened, so the copy never
  //: is drawn over it (`offlineReplay`).
  live: false,
  //: The page was drawn from the copy, with no connection.
  replayed: false,
  replaying: false,
  db: /** @type {Promise<IDBDatabase|null>|null} */ (null),
  key: /** @type {Promise<CryptoKey|null>|null} */ (null),
  sealed: false,
  //: The outbox: every action of this device's still waiting on what became of it, and the last ones done.
  box: /** @type {any[]} */ ([]),
  //: What became of actions, both devices', by id, newest kept.
  results: /** @type {Record<string, any>} */ ({}),
  since: 0,
  flushing: false,
  //: What the copy holds, kind by kind (`KINDS`): {at, count, of, from, to, range, bytes, urls,
  //: error, left}, `left` saying why a kind was left out.
  meta: /** @type {any} */ ({ parts: {}, refreshedAt: 0, profile: '', why: '', warmed: {} }),
  parts: /** @type {Record<string, any>} */ ({}),
  refreshing: false,
  timer: 0,
  backAt: 0,
  offlineSince: 0,
  ready: /** @type {Promise<void>|null} */ (null),
  storage: /** @type {any} */ (null),
  persisted: false
};

/* ---------------------------------------------------------------- who, and which device */

function ownerOnPage() {
  var m = document.querySelector('meta[name="rouh-owner"]');
  return (m && m.getAttribute('content')) || '';
}

function deviceKind() {
  var ua = navigator.userAgent || '';
  if (/iPhone|iPod|Android.+Mobile|Windows Phone/i.test(ua)) return 'phone';
  var coarse = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
  if (coarse && Math.min(screen.width, screen.height) < 600) return 'phone';
  return 'laptop';
}

function deviceName() {
  var ua = navigator.userAgent || '';
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad/.test(ua)) return 'iPad';
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android phone' : 'Android tablet';
  if (/Macintosh|Mac OS X/.test(ua)) return 'Mac';
  if (/Windows/.test(ua)) return 'Windows PC';
  if (/CrOS/.test(ua)) return 'Chromebook';
  if (/Linux/.test(ua)) return 'Linux computer';
  return 'This device';
}

/* ---------------------------------------------------------------- the store */

function idb() {
  if (OFF.db) return OFF.db;
  OFF.db = new Promise(function (resolve) {
    var req;
    try { req = indexedDB.open(DB_NAME, 1); } catch (e) { resolve(null); return; }
    req.onupgradeneeded = function () {
      var db = req.result;
      if (!db.objectStoreNames.contains('keys')) db.createObjectStore('keys');
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
      if (!db.objectStoreNames.contains('outbox')) db.createObjectStore('outbox');
    };
    req.onsuccess = function () {
      var db = req.result;
      // Another tab deleting the store (signing out) must not be held up by this one.
      db.onversionchange = function () { db.close(); OFF.db = null; };
      resolve(db);
    };
    req.onerror = function () { resolve(null); };
    req.onblocked = function () { resolve(null); };
  });
  return OFF.db;
}

/** @returns {Promise<any>} */
function dbDo(store, mode, work) {
  return idb().then(function (db) {
    if (!db) return undefined;
    return new Promise(function (resolve) {
      var tx;
      try { tx = db.transaction(store, mode); } catch (e) { resolve(undefined); return; }
      var out;
      var req = work(tx.objectStore(store));
      if (req) req.onsuccess = function () { out = req.result; };
      tx.oncomplete = function () { resolve(out); };
      tx.onerror = function () { resolve(undefined); };
      tx.onabort = function () { resolve(undefined); };
    });
  });
}

function dbGet(store, key) { return dbDo(store, 'readonly', function (s) { return s.get(key); }); }
function dbPut(store, key, value) { return dbDo(store, 'readwrite', function (s) { return s.put(value, key); }); }
function dbDel(store, key) { return dbDo(store, 'readwrite', function (s) { return s.delete(key); }); }
function dbAll(store) {
  return dbDo(store, 'readonly', function (s) { return s.getAll(); }).then(function (v) { return v || []; });
}
function dbKeys(store) {
  return dbDo(store, 'readonly', function (s) { return s.getAllKeys(); }).then(function (v) { return v || []; });
}

/* The key the copy is sealed with: made here, never extractable, kept in the store. */
function sealKey() {
  if (OFF.key) return OFF.key;
  OFF.key = dbGet('keys', OFF.owner).then(function (had) {
    if (had) return had;
    if (!window.crypto || !crypto.subtle) return null;
    return crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
      .then(function (k) { return dbPut('keys', OFF.owner, k).then(function () { return k; }); });
  }).then(function (k) { OFF.sealed = !!k; return k; }).catch(function () { return null; });
  return OFF.key;
}

var TEXT_IN = new TextEncoder();
var TEXT_OUT = new TextDecoder();

function seal(value) {
  return sealKey().then(function (key) {
    if (!key) return null;
    var iv = crypto.getRandomValues(new Uint8Array(12));
    return crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv }, key, TEXT_IN.encode(JSON.stringify(value)))
      .then(function (data) { return { iv: iv, data: data, n: data.byteLength }; });
  });
}

function unseal(box) {
  if (!box || !box.iv || !box.data) return Promise.resolve(null);
  return sealKey().then(function (key) {
    if (!key) return null;
    return crypto.subtle.decrypt({ name: 'AES-GCM', iv: box.iv }, key, box.data)
      .then(function (plain) { return JSON.parse(TEXT_OUT.decode(plain)); });
  }).catch(function () { return null; });
}

function kvKey(name) { return OFF.owner + ':' + name; }
function keep(name, value) {
  return seal(value).then(function (box) {
    if (box) return dbPut('kv', kvKey(name), box);
  });
}
function kept(name) { return dbGet('kv', kvKey(name)).then(unseal); }

/* Everything this page keeps, and its key, gone: signing out, or another person's page. */
function forgetAll() {
  OFF.key = null;
  OFF.box = [];
  OFF.parts = {};
  OFF.results = {};
  var sw = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (sw) { try { sw.postMessage({ type: 'rouh-forget' }); } catch (e) { /* nothing to tell */ } }
  return idb().then(function (db) {
    if (db) db.close();
    OFF.db = null;
    return new Promise(function (resolve) {
      var req;
      try { req = indexedDB.deleteDatabase(DB_NAME); } catch (e) { resolve(); return; }
      req.onsuccess = req.onerror = req.onblocked = function () { resolve(); };
    });
  }).then(function () {
    if (!window.caches) return;
    return caches.keys().then(function (names) {
      return Promise.all(names.filter(function (n) { return n === 'rouh-page' || n === 'rouh-data'; })
        .map(function (n) { return caches.delete(n); }));
    });
  });
}

/* ---------------------------------------------------------------- starting */

function start() {
  OFF.owner = ownerOnPage();
  OFF.device.kind = deviceKind();
  OFF.device.name = deviceName();
  if (!OFF.owner || !window.indexedDB) { OFF.ready = Promise.resolve(); return; }
  OFF.ready = dbKeys('keys').then(function (owners) {
    // A key for somebody else is somebody else's copy, and it goes before anything of
    // this person's is kept beside it.
    var others = owners.filter(function (o) { return o !== OFF.owner; });
    return others.length ? forgetAll() : null;
  }).then(function () {
    return Promise.all([dbGet('kv', 'device'), sealKey()]);
  }).then(function (got) {
    var dev = got[0] || {};
    if (!dev.id) {
      dev = { id: 'd' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36), kind: '' };
      dbPut('kv', 'device', dev);
    }
    OFF.device.id = dev.id;
    if (dev.kind === 'laptop' || dev.kind === 'phone') OFF.device.kind = dev.kind;
    return Promise.all([kept('meta'), kept('results'), dbAll('outbox')]);
  }).then(function (got) {
    if (got[0]) OFF.meta = Object.assign(OFF.meta, got[0]);
    if (got[1]) { OFF.results = got[1].byId || {}; OFF.since = got[1].since || 0; }
    var mine = (got[2] || []).filter(function (r) { return r && r.owner === OFF.owner; });
    return Promise.all(mine.map(function (r) {
      return unseal(r.box).then(function (whole) { return whole ? Object.assign(whole, { status: r.status }) : null; });
    }));
  }).then(function (rows) {
    OFF.box = (rows || []).filter(Boolean).sort(function (a, b) { return a.made_at - b.made_at; });
    paint();
  }).catch(function (e) { console.warn('rouh offline: the store could not be opened', e); });
  registerWorker();
  measureStorage();
}

function registerWorker() {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' }).then(function () {
      return navigator.serviceWorker.ready;
    }).then(function (reg) {
      if (reg.active) reg.active.postMessage({ type: 'rouh-owner', owner: OFF.owner });
      // Once the store's key is made, so what the worker keeps is sealed with it.
      (OFF.ready || Promise.resolve()).then(keepThePage);
    }).catch(function (e) { console.warn('rouh offline: the service worker did not start', e); });
  });
}

/* The page itself, kept by the service worker for opening with no connection. */
function keepThePage() {
  var sw = navigator.serviceWorker && navigator.serviceWorker.controller;
  var reg = navigator.serviceWorker ? navigator.serviceWorker.ready : null;
  if (sw) { sw.postMessage({ type: 'rouh-keep-page' }); return; }
  if (reg) reg.then(function (r) { if (r.active) r.active.postMessage({ type: 'rouh-keep-page' }); });
}

function measureStorage() {
  if (!navigator.storage || !navigator.storage.estimate) return;
  navigator.storage.estimate().then(function (e) { OFF.storage = e; paint(); }).catch(function () {});
  if (navigator.storage.persisted) {
    navigator.storage.persisted().then(function (p) { OFF.persisted = !!p; }).catch(function () {});
  }
}

/* ---------------------------------------------------------------- the copy of the screen */

var keepTimers = {};

/* What the socket said, kept for drawing the page again with no connection (`KEEP`). */
function offlineHeard(m) {
  if (!m || !KEEP[m.type] || OFF.replaying || !OFF.owner) return;
  if (m.type === 'ready') {
    OFF.socketUp = true;
    OFF.live = true;
    cameBack();
  }
  clearTimeout(keepTimers[m.type]);
  keepTimers[m.type] = setTimeout(function () {
    var copy = m;
    if (m.type === 'ready') {
      // A turn that was running, a browser that was open and a deploy under way are
      // not true of a page drawn later from this, so none of them is kept.
      copy = Object.assign({}, m, { running: null, browser: null, one_deploying: false });
    }
    (OFF.ready || Promise.resolve()).then(function () {
      keep('snap:' + m.type, { at: Date.now(), m: copy });
    });
  }, m.type === 'ready' ? 50 : 800);
}

/* The socket dropped, or never opened. With no connection and a copy, the page is drawn
   from the copy, once, exactly as the handshake would have drawn it. */
function offlineSocketDown() {
  // What the device keeps, read into the page now: a chat or a task opened from here on is
  // answered from it (`hasChat`, `wholeTasks`).
  packAll();
  var was = OFF.socketUp;
  OFF.socketUp = false;
  if (!OFF.offlineSince) OFF.offlineSince = Date.now();
  if (was) paint();
  if (!OFF.replayed && !navigator.onLine) offlineReplay();
  else if (!OFF.replayed) setTimeout(function () { if (!OFF.socketUp && !OFF.replayed) offlineReplay(); }, 1500);
  paint();
}

/* Only for a page that has never had a connection since it was opened.

   A page that has been drawn from the live server is already showing the
   newest thing this device has, and a copy kept earlier is older: drawn over
   it, it put back whatever chat was open when the copy was kept. Petar,
   23 October 2026: "when evolving appears, the chat changes from where I am
   to something else" - Evolving is Rouh restarting after a deploy, which
   keeps the socket away long enough for this to run. A page that loses its
   connection keeps its screen, and says it is offline (`setConn`). */
function offlineReplay() {
  if (OFF.replayed || OFF.socketUp || !OFF.owner || OFF.live) return Promise.resolve(false);
  return (OFF.ready || Promise.resolve()).then(function () {
    return Promise.all(Object.keys(KEEP).map(function (t) { return kept('snap:' + t); }));
  }).then(function (snaps) {
    if (OFF.socketUp || OFF.replayed) return false;
    var types = Object.keys(KEEP);
    var ready = snaps[types.indexOf('ready')];
    if (!ready || !ready.m) { paint(); return false; }
    OFF.replayed = true;
    OFF.replaying = true;
    var build = document.querySelector('meta[name="rouh-build"]');
    var said = Object.assign({}, ready.m, { assets: build ? build.getAttribute('content') : ready.m.assets });
    try {
      handleMessage(said);
      // The lists that changed after the handshake, in the order they were said.
      types.map(function (t, i) { return { t: t, s: snaps[i] }; })
        .filter(function (x) { return x.t !== 'ready' && x.s && x.s.m && x.s.at > ready.at; })
        .sort(function (a, b) { return a.s.at - b.s.at; })
        .forEach(function (x) {
          try { handleMessage(x.s.m); } catch (e) { console.warn('rouh offline: ' + x.t + ' could not be drawn', e); }
        });
    } catch (e) {
      console.warn('rouh offline: the copy could not be drawn', e);
    } finally {
      OFF.replaying = false;
    }
    // The socket's own word for itself, which the handshake just set to Connected.
    setConn('offline', 'Offline. Showing what this device keeps, from ' + whenSaid(ready.at));
    // A task browser already open says which tasks are here whole (`browserOfflineSay`).
    browserOfflineSay();
    // An address the server would have answered cannot be answered now. A task's page is
    // opened from the copy (`addrAsk`); anything else lets the loading screen go.
    var want = ADDR.wanted;
    if (want && !ADDR.asked) {
      if (want.kind === 'task' || want.kind === 'project') {
        addrOffline(want);
      } else {
        ADDR.wanted = null;
      }
    }
    paint();
    return true;
  });
}

/* The connection is back: the outbox goes, the copy is made again, and the pill says so. */
function cameBack() {
  var wasOff = OFF.offlineSince || OFF.replayed;
  OFF.offlineSince = 0;
  if (wasOff && !(OFF.backAt && Date.now() - OFF.backAt < BACK_MS)) OFF.backAt = Date.now();
  (OFF.ready || Promise.resolve()).then(function () {
    outboxFlush();
    if (!OFF.meta.refreshedAt || Date.now() - OFF.meta.refreshedAt > AGAIN_MS) {
      // Once the conversation the page is opening has had its moment (`rouhLater`).
      window.rouhLater(function () { setTimeout(function () { packRefresh(false); }, wasOff ? 1500 : 4000); });
    }
  });
  paint();
  if (wasOff) setTimeout(paint, BACK_MS + 100);
}

function whenSaid(at) {
  if (!at) return 'never';
  var d = new Date(at);
  var today = new Date();
  var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return 'today ' + t;
  var y = new Date(today.getTime() - 86400000);
  if (d.toDateString() === y.toDateString()) return 'yesterday ' + t;
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) + ' ' + t;
}

function isOnline() { return navigator.onLine && OFF.socketUp; }

/* Offline as a page should say so: no connection at all, or a socket that went (or never
   came) and left the page on this device's copy. Not a socket still on its way, which every
   page opening is for a moment. */
function isAway() { return !navigator.onLine || (!OFF.socketUp && !!(OFF.replayed || OFF.offlineSince)); }

/* ---------------------------------------------------------------- the pack */

function metered() {
  var c = /** @type {any} */ (navigator).connection;
  if (!c) return '';
  if (c.saveData) return 'the browser is saving data';
  if (c.type === 'cellular') return 'this is a mobile connection';
  if (/(^|-)2g$/.test(c.effectiveType || '')) return 'the connection is slow';
  return '';
}

/* How much more this browser lets Rouh keep here, as far as it says: Infinity when it does
   not say. A reserve stays free for the outbox and the page's own files. */
var RESERVE = 25 * 1024 * 1024;
function roomLeft() {
  if (!navigator.storage || !navigator.storage.estimate) return Promise.resolve(Infinity);
  return navigator.storage.estimate().then(function (e) {
    OFF.storage = e;
    if (!e || !e.quota) return Infinity;
    return e.quota - (e.usage || 0) - RESERVE;
  }, function () { return Infinity; });
}

function packRefresh(asked) {
  if (OFF.refreshing || !OFF.owner) return Promise.resolve();
  if (!isOnline()) {
    if (asked) notify('There is no connection, so the copy cannot be made again now.', { tone: 'warning' });
    return Promise.resolve();
  }
  var why = metered();
  if (why && !asked) {
    OFF.meta.why = 'Not refreshed by itself: ' + why + '. Refresh now does it anyway.';
    paint();
    return Promise.resolve();
  }
  OFF.refreshing = true;
  OFF.meta.why = '';
  paint();
  if (navigator.storage && navigator.storage.persist && !OFF.persisted) {
    navigator.storage.persist().then(function (p) { OFF.persisted = !!p; }).catch(function () {});
  }
  // Petar's order. The room this browser gives the copy is shared out from the top: each kind
  // in turn, as long as what is kept so far and it fit. Once one does not, it and every kind
  // after it are left out, and what they held before goes too, so the room is the higher ones'.
  var full = false;
  var room = { budget: Infinity, used: 0 };
  var chain = budgetOf().then(function (b) { room.budget = b; });
  KINDS.forEach(function (kind) {
    chain = chain.then(function () {
      if (!navigator.onLine) return;
      if (full) return leaveOut(kind, 'there was no room left on this device');
      OFF.meta.parts[kind.id] = Object.assign({}, OFF.meta.parts[kind.id] || {}, { making: true });
      paint();
      return refreshKind(kind, room).then(function (fit) {
        if (fit === false) full = true;
      }, function (e) {
        var had = OFF.meta.parts[kind.id] || {};
        OFF.meta.parts[kind.id] = Object.assign({}, had, { error: String(e && e.message || e), tried: Date.now(),
                                                         making: false });
      }).then(paint);
    });
  });
  return chain.then(function () {
    OFF.meta.refreshedAt = Date.now();
    OFF.meta.profile = 'same';
    return keep('meta', OFF.meta);
  }).then(function () {
    keepThePage();
    OFF.refreshing = false;
    measureStorage();
    paint();
  }, function () { OFF.refreshing = false; paint(); });
}

/* The room the copy may take here: what the browser gives this site, less a reserve, less
   what the site keeps besides the copy (the page's own files). Infinity when it does not say. */
function budgetOf() {
  return roomLeft().then(function (free) {
    var e = OFF.storage;
    if (!isFinite(free) || !e || !e.quota) return Infinity;
    var ours = 0;
    KINDS.forEach(function (k) { ours += (OFF.meta.parts[k.id] || {}).bytes || 0; });
    var besides = Math.max(0, (e.usage || 0) - ours);
    return e.quota - RESERVE - besides;
  });
}

/* One kind, made again and kept, or left out when it does not fit in what is left of `room`
   after the kinds above it: false when it did not. */
function refreshKind(kind, room) {
  room = room || { budget: Infinity, used: 0 };
  var read = kind.part ? readPart(kind) : kind.read();
  return read.then(function (got) {
    return Promise.resolve(room.budget).then(function (budget) {
      if (room.used + got.bytes > budget) {
        return leaveOut(kind, 'it needs ' + size(got.bytes) + ' and the device had room for '
          + size(Math.max(0, budget - room.used))).then(function () { return false; });
      }
      room.used += got.bytes;
      if (kind.part && !OFF.sealed) {
        // Nothing private is kept where it cannot be sealed (the panel says so).
        OFF.meta.parts[kind.id] = { at: 0, count: 0, bytes: 0, urls: [], making: false,
                                    error: 'This browser cannot encrypt it, so it is not kept here.' };
        return true;
      }
      var kept = kind.part ? keep('part:' + kind.id, got.data) : Promise.resolve(true);
      return kept.then(function (ok) {
        if (!ok) {
          return leaveOut(kind, 'the browser would not keep any more here').then(function () { return false; });
        }
        if (kind.part) OFF.parts[kind.id] = got.data;
        OFF.meta.parts[kind.id] = { at: Date.now(), count: got.count, of: got.of || 0, from: got.from || 0,
                                    to: got.to || 0, range: got.range || '', bytes: got.bytes,
                                    urls: got.urls || [], missing: got.missing || [], error: got.error || '', left: '',
                                    making: false };
        if (!kind.after) return true;
        // Pages kept for the canvas, after the part itself: as many as there is room for.
        return kind.after(got.data, room).then(function (warmed) {
          room.used += warmed.bytes;
          var m = OFF.meta.parts[kind.id];
          m.bytes += warmed.bytes;
          m.pageBytes = warmed.bytes;
          m.urls = m.urls.concat(warmed.urls);
          m.missing = (m.missing || []).concat(warmed.missing);
          m.pages = warmed.pages;
          if (warmed.full) {
            m.error = 'Only ' + warmed.pages + ' of its pages were kept: there was no room for more.';
            return false;
          }
          return true;
        });
      });
    });
  });
}

/* Left out: the device keeps nothing of it, and says why on the Offline page. */
function leaveOut(kind, why) {
  var had = OFF.meta.parts[kind.id] || {};
  OFF.meta.parts[kind.id] = { at: 0, count: 0, bytes: 0, urls: [], left: why, tried: Date.now(), making: false };
  delete OFF.parts[kind.id];
  var gone = [dbDel('kv', kvKey('part:' + kind.id))];
  if (window.caches && (had.urls || []).length) {
    var others = [];
    KINDS.forEach(function (k) {
      if (k.id !== kind.id) others = others.concat((OFF.meta.parts[k.id] || {}).urls || []);
    });
    gone.push(caches.open('rouh-data').then(function (c) {
      return Promise.all(had.urls.filter(function (u) { return others.indexOf(u) < 0; })
        .map(function (u) { return c.delete(u); }));
    }).catch(function () {}));
  }
  return Promise.all(gone).then(function () { paint(); });
}

function getJson(url) {
  // The copy is work nobody is waiting on, and says so: the server does it in the lane kept for
  // that, so it never holds up a conversation being opened (`rouh.dbwork.later`).
  return fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Time-Zone': zone(), 'X-Rouh-Later': '1' } })
    .then(function (r) {
      return r.text().then(function (text) {
        var got = {};
        try { got = JSON.parse(text); } catch (e) { got = {}; }
        if (!r.ok) throw new Error(got.error || ('It did not come: ' + r.status));
        return { json: got, bytes: text.length };
      });
    });
}

/* One part of the pack from the server, every page of it, as one. */
function readPart(kind) {
  var q = '/api/offline/pack/' + kind.part + '?device=' + OFF.device.kind;
  return getJson(q).then(function (first) {
    var data = first.json;
    var bytes = first.bytes;
    var pages = kind.paged ? (data.pages || 1) : 1;
    var list = kind.part === 'mail' ? 'messages' : 'chats';
    var chain = Promise.resolve();
    for (var n = 1; n < pages; n++) {
      (function (page) {
        chain = chain.then(function () {
          if (!navigator.onLine) throw new Error('The connection went while the copy was made.');
          return getJson(q + '&page=' + page).then(function (more) {
            data[list] = (data[list] || []).concat(more.json[list] || []);
            data.trouble = (data.trouble || []).concat(more.json.trouble || []);
            if (more.json.from && (!data.from || more.json.from < data.from)) data.from = more.json.from;
            bytes += more.bytes;
          });
        });
      })(n);
    }
    return chain.then(function () {
      return Object.assign({ data: data, bytes: bytes }, countOf(kind.part, data));
    });
  });
}

/* What the copy of one part holds: how many, of how many, and over which days. */
function countOf(part, got) {
  if (part === 'tasks') {
    var tasks = got.tasks || [];
    return { count: tasks.filter(function (t) { return t.whole; }).length, of: tasks.length,
             range: got.why || '' };
  }
  if (part === 'decisions') return { count: (got.open || []).length + (got.snoozed || []).length };
  if (part === 'calendar') return { count: (got.events || []).length, from: got.from, to: got.to, error: got.why || '' };
  if (part === 'contacts') return { count: (got.contacts || []).length };
  if (part === 'mail') {
    return { count: (got.messages || []).length, from: got.from, to: got.to || Date.now() / 1000,
             error: got.why || '' };
  }
  if (part === 'chats') {
    var forks = (got.chats || []).filter(function (c) { return c.fork_of; }).length;
    return { count: (got.chats || []).length, from: got.from, to: got.to,
             range: forks ? forks + (forks === 1 ? ' of them a fork' : ' of them forks') : '' };
  }
  return { count: 0 };
}

/* What a page of Rouh's own reads, read once here so the service worker keeps it sealed: the
   page then opens on it with no connection exactly as it does with one. */
function readUrls(urls, most) {
  var out = { bytes: 0, urls: [], missing: /** @type {string[]} */ ([]), answers: /** @type {Record<string, any>} */ ({}),
              full: false, pages: 0 };
  var queue = urls.slice();
  var lanes = [];
  function next() {
    if (!queue.length || out.full || !navigator.onLine) return Promise.resolve();
    var url = queue.shift();
    return fetch(url, { credentials: 'same-origin', headers: { 'X-Time-Zone': zone(), 'X-Rouh-Later': '1' } }).then(function (r) {
      // An address that answers nothing is remembered too, so it is not what makes its goal or
      // task look unkept every time.
      if (!r.ok) { out.missing.push(url); return; }
      return r.text().then(function (text) {
        out.bytes += text.length;
        out.urls.push(url);
        out.pages += 1;
        // As many as the room left for them (`refreshKind`), and no more.
        if (most !== undefined && out.bytes > most) out.full = true;
        if (/^\/api\//.test(url)) { try { out.answers[url] = JSON.parse(text); } catch (e) { /* not JSON */ } }
      });
    }, function () {}).then(function () {
      // Every so often, whether there is still room: the canvas's pages carry their pictures.
      if (out.pages % 25 !== 0) return;
      return roomLeft().then(function (room) { if (room < 0) out.full = true; });
    }).then(next);
  }
  for (var i = 0; i < 4; i++) lanes.push(next());
  return Promise.all(lanes).then(function () { return out; });
}

// The address the canvas asks for a workspace page it frames (`frameAddress` in app/cards.js):
// the same address marked as one for its own frame, which is the copy it reads offline.
function framed(href) {
  var u = new URL(href, location.href);
  u.searchParams.set('framed', '1');
  u.searchParams.set('hosted', '1');
  return u.pathname + u.search;
}
function relPath(rel) { return String(rel || '').split('/').map(encodeURIComponent).join('/'); }
function taskHref(rel) { return '/workspace/_task/' + relPath(rel) + '/'; }
function pageHref(rel) { return '/workspace/' + relPath(rel); }

/* The pages of every task the device keeps whole, for the canvas: its own page, every step's,
   every page it built, and what the breadcrumb reads. The task browser and the Control Room
   with them, which list every task. A task whose folder has not moved since its pages were last
   kept is not read again. */
function warmTasks(part, room) {
  var tasks = ((part && part.tasks) || []).filter(function (t) { return t.whole; });
  var urls = [framed('/workspace/'), '/api/workspace/index', '/api/control', '/api/decisions'];
  var was = OFF.meta.warmed || {};
  var now = {};
  var kept = ((OFF.meta.parts.tasks && OFF.meta.parts.tasks.urls) || [])
    .concat((OFF.meta.parts.tasks && OFF.meta.parts.tasks.missing) || []);
  var keptUrls = [];
  tasks.forEach(function (t) {
    var mine = [framed(taskHref(t.rel)), '/api/workspace/task?rel=' + encodeURIComponent(t.rel)];
    (t.step_list || []).forEach(function (s) {
      if (!s.rel) return;
      mine.push(framed(taskHref(s.rel)));
      mine.push('/api/workspace/step?rel=' + encodeURIComponent(s.rel));
    });
    (t.pages || []).forEach(function (p) { mine.push(framed(pageHref(p))); });
    now[t.rel] = t.changed || 0;
    var goals = (OFF.meta.parts.goals && OFF.meta.parts.goals.urls) || [];
    if (was[t.rel] && was[t.rel] === now[t.rel]
        && mine.every(function (u) { return kept.indexOf(u) >= 0 || goals.indexOf(u) >= 0; })) {
      keptUrls = keptUrls.concat(mine.filter(function (u) { return goals.indexOf(u) < 0; }));
    } else {
      urls = urls.concat(mine);
    }
  });
  // A page the goals keep already (a goal's steps are its task's steps) is not read twice.
  var goals = (OFF.meta.parts.goals && OFF.meta.parts.goals.urls) || [];
  urls = urls.filter(function (u, i) { return urls.indexOf(u) === i && goals.indexOf(u) < 0; });
  return readUrls(urls, room ? room.budget - room.used : undefined).then(function (got) {
    OFF.meta.warmed = now;
    var had = OFF.meta.parts.tasks || {};
    var wasMissing = had.missing || [];
    got.missing = got.missing.concat(keptUrls.filter(function (u) { return wasMissing.indexOf(u) >= 0; }));
    keptUrls = keptUrls.filter(function (u) { return wasMissing.indexOf(u) < 0; });
    if (keptUrls.length && had.urls && had.urls.length) {
      got.bytes += Math.round((had.pageBytes || 0) * keptUrls.length / had.urls.length);
    }
    got.urls = got.urls.concat(keptUrls);
    got.pages += keptUrls.length;
    return got;
  });
}

/* Clockwork, the goals and the quests, as their own pages read them. */
function readClockwork() {
  return readUrls(['/api/reminders']).then(function (got) {
    var list = ((got.answers['/api/reminders'] || {}).reminders) || [];
    var when = list.map(function (v) { return v.next_at || 0; }).filter(Boolean).sort();
    return { bytes: got.bytes, urls: got.urls, count: list.length,
             from: when[0] || 0, to: when[when.length - 1] || 0,
             range: list.filter(function (v) { return v.state === 'paused'; }).length + ' paused' };
  });
}

function readGoals() {
  return readUrls(['/api/goals']).then(function (got) {
    var goals = ((got.answers['/api/goals'] || {}).goals) || [];
    var was = OFF.meta.goalsSeen || {};
    var seen = {};
    var kept = ((OFF.meta.parts.goals && OFF.meta.parts.goals.urls) || [])
      .concat((OFF.meta.parts.goals && OFF.meta.parts.goals.missing) || []);
    var urls = [], keptUrls = [];
    var steps = 0;
    goals.forEach(function (g) {
      var mine = [];
      if (g.folder) mine.push(framed(taskHref(g.folder) + '?doc=goal.md'), framed(taskHref(g.folder)));
      (function walk(list) {
        (list || []).forEach(function (s) {
          steps += 1;
          [s.page, s.explainer, s.yours_page].forEach(function (u) { if (u) mine.push(framed(u)); });
          walk(s.parts);
        });
      })(g.steps);
      // A goal whose plan reads the same as when its pages were last kept is not read again.
      seen[g.id] = hashOf(goalWords(g));
      if (was[g.id] === seen[g.id] && mine.every(function (u) { return kept.indexOf(u) >= 0; })) {
        keptUrls = keptUrls.concat(mine);
      } else {
        urls = urls.concat(mine);
      }
    });
    urls = urls.filter(function (u, i) { return urls.indexOf(u) === i; });
    return readUrls(urls).then(function (pages) {
      OFF.meta.goalsSeen = seen;
      var wasMissing = (OFF.meta.parts.goals || {}).missing || [];
      var missing = pages.missing.concat(keptUrls.filter(function (u) { return wasMissing.indexOf(u) >= 0; }));
      keptUrls = keptUrls.filter(function (u) { return wasMissing.indexOf(u) < 0; });
      var all = got.urls.concat(pages.urls, keptUrls);
      var had = OFF.meta.parts.goals || {};
      // What was kept before and is kept still keeps the room it took.
      var keptBytes = keptUrls.length && had.urls && had.urls.length
        ? Math.round((had.bytes || 0) * keptUrls.length / had.urls.length) : 0;
      return { bytes: got.bytes + pages.bytes + keptBytes, urls: all, missing: missing, count: goals.length,
               range: steps + (steps === 1 ? ' step' : ' steps') + ', ' + (pages.pages + keptUrls.length) + ' pages' };
    });
  });
}

/* What a goal's pages are drawn from, without the words that move with the clock ("in 5 min"):
   its plan, each step's state and what it holds. */
function goalWords(g) {
  var parts = [g.title, g.stage, g.deadline, JSON.stringify(g.paused || null), JSON.stringify(g.direction || null),
               JSON.stringify(g.streams || null)];
  (function walk(list) {
    (list || []).forEach(function (s) {
      parts.push([s.id, s.title, s.status, s.who, s.kind, s.ask, s.how, s.result, s.note, s.choice, s.done_by,
                  s.rouh_done, s.left, JSON.stringify(s.your_steps || [])].join('|'));
      walk(s.parts);
    });
  })(g.steps);
  return parts.join('\n');
}

function hashOf(text) {
  var h = 0;
  for (var i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return String(h) + ':' + text.length;
}

function readQuests() {
  return readUrls(['/api/quests']).then(function (got) {
    var quests = ((got.answers['/api/quests'] || {}).quests) || [];
    var each = quests.map(function (q) { return '/api/quests/' + encodeURIComponent(q.number); });
    return readUrls(each).then(function (pages) {
      var starts = quests.map(function (q) { return q.start; }).filter(Boolean).sort();
      var ends = quests.map(function (q) { return q.end; }).filter(Boolean).sort();
      return { bytes: got.bytes + pages.bytes, urls: got.urls.concat(pages.urls), count: quests.length,
               from: starts[0] ? Date.parse(starts[0]) / 1000 : 0,
               to: ends.length ? Date.parse(ends[ends.length - 1]) / 1000 : 0,
               range: quests.filter(function (q) { return q.state === 'on'; }).length + ' going on' };
    });
  });
}

//: What this device keeps, in Petar's order, which is also what a device short of room keeps
//: first (12 October 2026): the calendar, the decisions, Clockwork, the goals, the quests, the
//: tasks, the chats, the email; and the contacts after them, for writing to somebody.
var KINDS = [
  { id: 'calendar', name: 'Calendar', part: 'calendar' },
  { id: 'decisions', name: 'Decisions', part: 'decisions' },
  { id: 'clockwork', name: 'Clockwork', read: readClockwork },
  { id: 'goals', name: 'Goals', read: readGoals },
  { id: 'quests', name: 'Quests', read: readQuests },
  { id: 'tasks', name: 'Tasks', part: 'tasks', after: warmTasks },
  { id: 'chats', name: 'Chats', part: 'chats', paged: true },
  { id: 'mail', name: 'Email', part: 'mail', paged: true },
  { id: 'contacts', name: 'People', part: 'contacts' }
];
//: The kinds kept in this page's own store, which the Offline page reads.
var PARTS = KINDS.filter(function (k) { return k.part; }).map(function (k) { return k.id; });

function size(n) {
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB';
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n >= 1024) return Math.round(n / 1024) + ' KB';
  return n + ' B';
}

/* Every part this device keeps, opened, for the Offline page and its search. */
function packAll() {
  return (OFF.ready || Promise.resolve()).then(function () {
    var missing = PARTS.filter(function (p) { return !OFF.parts[p]; });
    return Promise.all(missing.map(function (p) {
      return kept('part:' + p).then(function (got) { if (got) OFF.parts[p] = got; });
    }));
  }).then(function () { return OFF.parts; });
}

/* A copy of what a page of Rouh's reads, as it is after something done here offline, so the
   page drawn again from the copy shows it (`rouh-prime` in sw.js). */
function primeCopy(url, answer) {
  var sw = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (!sw) return;
  try { sw.postMessage({ type: 'rouh-prime', url: url, body: JSON.stringify(answer) }); } catch (e) { /* kept as it was */ }
}

function zone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
}

/* ---------------------------------------------------------------- the outbox */

function newId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return 'a' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
}

function boxSave(entry) {
  return seal(entry).then(function (box) {
    if (!box) return;
    return dbPut('outbox', entry.id, { owner: OFF.owner, status: entry.status, made_at: entry.made_at, box: box });
  });
}

/* Something done with no connection: kept here, and sent the moment there is one.
   With a connection it goes at once, through the same outbox, so it is carried out
   the same way and only once. */
function offlineQueue(kind, payload, base) {
  var entry = { id: newId(), kind: kind, payload: payload || {}, base: base || {}, made_at: Date.now(),
                status: 'waiting', result: '', label: labelOf(kind, payload || {}),
                device: OFF.device.name, device_kind: OFF.device.kind };
  OFF.box.push(entry);
  return (OFF.ready || Promise.resolve()).then(function () { return boxSave(entry); }).then(function () {
    paint();
    if (isOnline()) outboxFlush();
    return entry;
  });
}

function labelOf(kind, p) {
  if (kind === 'decision') return 'Answer: ' + (p.said || p.question || 'a decision');
  if (kind === 'reply') return 'Reply: ' + (p.subject || '');
  if (kind === 'draft') return 'New email: ' + (p.subject || '');
  if (kind === 'page') return 'Edit: ' + (p.where || p.path || '');
  if (kind === 'reminder') return 'Reminder: ' + (p.title || p.what || '');
  if (kind === 'task') return 'New task: ' + (p.title || '');
  if (kind === 'note') return p.audio ? 'Voice note' : 'Note: ' + (p.text || '').slice(0, 80);
  if (kind === 'clock') return p.label || 'A change on Clockwork, a goal or a quest';
  if (kind === 'feedback') return 'Gene therapy: ' + (p.body || '').slice(0, 80);
  return kind;
}

function waiting() {
  return OFF.box.filter(function (e) { return e.status === 'waiting' || e.status === 'sending'; });
}

function outboxFlush() {
  if (OFF.flushing || !navigator.onLine || !OFF.owner) return Promise.resolve();
  var due = waiting();
  if (!due.length) return resultsRead();
  OFF.flushing = true;
  due.forEach(function (e) { e.status = 'sending'; });
  paint();
  var body = { device: OFF.device, actions: due.map(function (e) {
    return { id: e.id, kind: e.kind, payload: e.payload, base: e.base, made_at: e.made_at };
  }) };
  return fetch('/api/offline/outbox', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-Time-Zone': zone() },
    body: JSON.stringify(body)
  }).then(function (r) {
    if (r.status === 401) throw new Error('signed out');
    return r.json().then(function (got) {
      if (!r.ok) throw new Error(got.error || ('The outbox was refused: ' + r.status));
      return got;
    });
  }).then(function (got) {
    offlineResults(got.results || [], true);
  }).catch(function (e) {
    due.forEach(function (x) { if (x.status === 'sending') x.status = 'waiting'; });
    console.warn('rouh offline: the outbox could not be sent', e);
  }).then(function () {
    OFF.flushing = false;
    paint();
    return resultsRead();
  });
}

/* What became of actions from both devices since this one last asked: the other
   device's are shown too, so something done on the phone shows as done here. */
function resultsRead() {
  if (!navigator.onLine || !OFF.owner) return Promise.resolve();
  return fetch('/api/offline/outbox?since=' + encodeURIComponent(String(OFF.since || 0)),
    { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : { results: [] }; })
    .then(function (got) { offlineResults(got.results || [], false); })
    .catch(function () {});
}

var SETTLED = { done: true, dropped: true, failed: true };

/** @param {import('./protocol').OfflineResult[]} rows */
function offlineResults(rows, fromFlush) {
  if (!rows || !rows.length) return;
  var done = 0, asking = 0, failed = 0;
  rows.forEach(function (r) {
    if (!r || !r.id) return;
    OFF.results[r.id] = r;
    if (r.updated_at && r.updated_at > OFF.since) OFF.since = r.updated_at;
    var mine = OFF.box.filter(function (e) { return e.id === r.id; })[0];
    if (!mine) return;
    var was = mine.status;
    mine.status = r.status;
    mine.result = r.result || '';
    mine.outcome = r.outcome || {};
    if (was !== r.status) {
      if (r.status === 'done') done++;
      else if (r.status === 'clash' || r.status === 'held') asking++;
      else if (r.status === 'failed') failed++;
    }
    boxSave(mine);
  });
  // Keep the newest hundred results, and every entry of this device's for a day after
  // it settled; older settled ones leave the outbox.
  var ids = Object.keys(OFF.results).sort(function (a, b) {
    return (OFF.results[b].updated_at || 0) - (OFF.results[a].updated_at || 0);
  });
  ids.slice(100).forEach(function (id) { delete OFF.results[id]; });
  var dayAgo = Date.now() - 86400000;
  OFF.box = OFF.box.filter(function (e) {
    var gone = SETTLED[e.status] && e.made_at < dayAgo;
    if (gone) dbDel('outbox', e.id);
    return !gone;
  });
  keep('results', { byId: OFF.results, since: OFF.since });
  if (fromFlush && (done || asking || failed)) {
    var words = [];
    if (done) words.push(done + (done === 1 ? ' thing you did offline was' : ' things you did offline were') + ' carried out');
    if (asking) words.push(asking + (asking === 1 ? ' needs you: it is in Decisions' : ' need you: they are in Decisions'));
    if (failed) words.push(failed + ' could not be done; the Offline page says why');
    notify(words.join('. ') + '.', { tone: asking || failed ? 'warning' : 'success' });
  }
  // A decision answered elsewhere: the copy of the decisions is read again.
  if (rows.some(function (r) { return r.kind === 'decision'; }) && isOnline()) refreshPart('decisions');
  paint();
}

/* One kind made again on its own, as when a decision was answered elsewhere. */
function refreshPart(part) {
  var kind = KINDS.filter(function (k) { return k.id === part; })[0];
  if (!kind || OFF.refreshing || (OFF.meta.parts[part] || {}).left) return Promise.resolve();
  return refreshKind(kind).then(function () { paint(); return keep('meta', OFF.meta); }, function () {});
}

/* A decision answered with no connection, from the Decisions page, a task's page or the
   Offline page: the same body the answer path takes, with what the question was.
   @returns {Promise<{ok: boolean, status: number, out: any}>} */
function answerDecision(id, what, body, d) {
  if (what !== 'answer') {
    return Promise.resolve({ ok: false, status: 0, out: { error: 'With no connection a decision can be answered, and that is all. The rest waits for a connection.' } });
  }
  return packAll().then(/** @returns {any} */ function () {
    var known = d || findDecision(id);
    if (!known) {
      return { ok: false, status: 0, out: { error: 'This device has no copy of that decision, so it cannot be answered offline.' } };
    }
    var said = sayAnswer(known, body);
    var payload = { decision: known.id, choice: body.choice || [], text: body.text || '', said: said,
                    question: known.question || '' };
    if (body.items) payload.items = body.items;
    if (body.confirm) payload.confirm = body.confirm;
    var base = { question: known.question || '', options: (known.options || []).map(function (o) { return o.id; }),
                 status: known.status, updated_at: known.updated_at };
    return offlineQueue('decision', payload, base).then(function (entry) {
      var shown = Object.assign({}, known, { status: 'queued', answer: { choice: payload.choice, text: payload.text, said: said },
                                             queued: entry.id });
      markDecision(known.id, shown);
      return { ok: true, status: 202, out: { decision: shown, queued: entry.id } };
    });
  });
}

function sayAnswer(d, body) {
  var labels = (d.options || []).filter(function (o) { return (body.choice || []).indexOf(o.id) >= 0; })
    .map(function (o) { return o.label; });
  var text = String(body.text || '').trim();
  return labels.concat(text ? ['“' + text + '”'] : []).join(', ') || 'answered';
}

function findDecision(id) {
  var dp = OFF.parts.decisions || {};
  var all = (dp.open || []).concat(dp.snoozed || [], dp.going || []);
  for (var i = 0; i < all.length; i++) { if (String(all[i].id) === String(id)) return all[i]; }
  return null;
}

function markDecision(id, shown) {
  var dp = OFF.parts.decisions;
  if (!dp) return;
  ['open', 'snoozed'].forEach(function (k) {
    dp[k] = (dp[k] || []).map(function (d) { return String(d.id) === String(id) ? shown : d; });
  });
  keep('part:decisions', dp);
}

/* ---------------------------------------------------------------- saying so */

var pill = $('offPill');
var pillFade = 0;

/* One pill, in one place, from the drop to the return: amber while it is away,
   green once it is live, and then gone. Its states are `pill-` classes rather
   than `off-` ones because `.off-back` is the Offline page's back link, whose
   `all: unset` once took the green pill out of its place and up to the very top
   of the page, above the top bar. */
function pillSay(kind, text) {
  if (!pill) return;
  // The Offline page says all of it already, at the top of itself.
  if (offlineViewing()) kind = '';
  if (!kind) {
    if (pill.hidden || pill.classList.contains('pill-going')) return;
    if (!pill.classList.contains('pill-live')) { pill.hidden = true; return; }
    // Live fades rather than blinking out.
    pill.classList.add('pill-going');
    pillFade = window.setTimeout(function () {
      pill.hidden = true;
      pill.classList.remove('pill-going');
    }, FADE_MS);
    return;
  }
  clearTimeout(pillFade);
  pill.hidden = false;
  pill.className = 'off-pill pill-' + kind;
  pillPlace();
  var words = $('offPillText');
  if (words) words.textContent = text;
  pill.setAttribute('aria-label', text + '. Open the Offline page');
  pill.title = text;
}

/* Below a notice on screen rather than under it. Both sit at the top in the
   middle, and the notices are drawn over the page, so a run's Done notice -
   on screen exactly when its deploy restarts Rouh - hid Evolving altogether
   (fr_4ba66bbb733a). Put there as it is said, and again whenever the notice
   changes while it is up. */
function pillPlace() {
  if (!pill) return;
  var box = $('notices'), panel = $('ntPanel');
  var under = 0;
  if (box && !box.hidden && box.getAttribute('data-mode') === 'stack' && panel && !panel.hidden) {
    under = panel.getBoundingClientRect().bottom;
  }
  pill.style.top = under > 0 ? Math.round(under + 8) + 'px' : '';
}

function paint() {
  var n = waiting().length;
  var back = OFF.backAt && Date.now() - OFF.backAt < BACK_MS;
  // The page went on from the copy, and Rouh has not said hello again yet.
  var away = !OFF.socketUp && (OFF.replayed || OFF.offlineSince);
  var done = doneSinceBack();
  // Back from a deploy says so, and back from anything else says Alive.
  var live = S.evolved ? CONN_WORDS.evolved : CONN_WORDS.live;
  if (!navigator.onLine) {
    pillSay('away', n ? 'Offline · ' + n + ' waiting to send' : 'Offline · using this device’s copy');
  } else if (OFF.flushing && n) {
    pillSay('live', live + ' · sending ' + n);
  } else if (back) {
    pillSay(n ? 'away' : 'live', live + (done ? ' · ' + done + ' carried out' : '')
      + (n ? ' · ' + n + ' waiting to send' : ''));
  } else if (away && S.dropUnsure && !n) {
    // Gone with no word why, and `/healthz` not yet answered whether Rouh is
    // starting again (`probeDrop`): no word rather than a wrong one.
    pillSay('', '');
  } else if (away) {
    // Why it went, when Rouh said so as it went (`S.renewing`); a plain word when it did not.
    var word = S.renewing ? CONN_WORDS.renewing : CONN_WORDS.reconnecting;
    pillSay('away', n ? word + ' · ' + n + ' waiting to send' : word + '…');
  } else if (n) {
    pillSay('away', n + ' waiting to send');
  } else {
    pillSay('', '');
  }
  offlinePaint();
}

/* How many of this device's actions were carried out since the connection came back. */
function doneSinceBack() {
  if (!OFF.backAt) return 0;
  var since = OFF.backAt - 60000;
  return OFF.box.filter(function (e) {
    var r = OFF.results[e.id];
    return e.status === 'done' && r && (r.updated_at || 0) * 1000 >= since;
  }).length;
}

if (pill) pill.addEventListener('click', function () { offlineOpen(''); });
// A notice that comes, goes or grows while the pill is up moves it with it.
(function () {
  var panel = $('ntPanel'), box = $('notices');
  if (!pill || !panel || typeof ResizeObserver !== 'function') return;
  var again = function () { if (!pill.hidden) pillPlace(); };
  new ResizeObserver(again).observe(panel);
  if (box) new MutationObserver(again).observe(box, { attributes: true, attributeFilter: ['data-mode', 'hidden'] });
})();

window.addEventListener('online', function () {
  // Back from no connection: the pill says so from now, not from when Rouh answers.
  if (OFF.offlineSince || OFF.replayed) {
    OFF.backAt = Date.now();
    setTimeout(paint, BACK_MS + 100);
  }
  paint();
  // The socket reconnects by itself; the outbox does not wait for it.
  setTimeout(function () { outboxFlush(); }, 1200);
});
window.addEventListener('offline', function () {
  if (!OFF.offlineSince) OFF.offlineSince = Date.now();
  paint();
});

/* Coming back to the page is when an iPhone lets it do anything at all. */
document.addEventListener('visibilitychange', function () {
  if (document.visibilityState !== 'visible') return;
  if (isOnline()) {
    outboxFlush();
    if (Date.now() - (OFF.meta.refreshedAt || 0) > AGAIN_MS) packRefresh(false);
  }
});
OFF.timer = window.setInterval(function () {
  if (document.visibilityState === 'visible' && isOnline()) packRefresh(false);
}, EVERY_MS);

/* Signing out takes the copy with it, before the form goes. */
document.addEventListener('submit', function (e) {
  var form = /** @type {HTMLFormElement} */ (e.target);
  if (!form || !form.action || !/\/logout$/.test(new URL(form.action, location.href).pathname)) return;
  if (form.dataset.forgotten) return;
  var n = waiting().length;
  if (n && !window.confirm(n + (n === 1 ? ' thing you did offline has' : ' things you did offline have')
      + ' not been sent to Rouh yet. Signing out deletes this device\u2019s copy and throws '
      + (n === 1 ? 'it' : 'them') + ' away. Sign out anyway?')) {
    e.preventDefault();
    return;
  }
  e.preventDefault();
  var go = function () { form.dataset.forgotten = '1'; form.submit(); };
  var late = setTimeout(go, 2000);
  forgetAll().then(function () { clearTimeout(late); go(); }, function () { clearTimeout(late); go(); });
}, true);

/* The decisions this device keeps, in the shape the Decisions page reads, for when it
   cannot read them from Rouh. */
function decisionsCopy() {
  return packAll().then(function (parts) {
    var dp = parts.decisions;
    if (!dp) return null;
    return Object.assign({ open: [], snoozed: [], going: [], history: [], sources: [], counts: {} }, dp,
                         { history: [], offline: true });
  });
}

/* Whether the device keeps a chat, for a chat opened with no connection (app/chats.js). */
function hasChat(id) {
  var chats = (OFF.parts.chats && OFF.parts.chats.chats) || [];
  return chats.some(function (c) { return c.id === id; });
}

/* The folders of the tasks whose pages open on this device with no connection, for the task
   browser (app/cards.js): the ones the copy keeps whole, and any other the service worker kept
   when it was last opened with one. */
function wholeTasks() {
  var have = /** @type {Record<string, boolean>} */ ({});
  ((OFF.parts.tasks && OFF.parts.tasks.tasks) || []).forEach(function (t) { if (t.whole) have[t.rel] = true; });
  if (!window.caches) return Promise.resolve(Object.keys(have));
  return caches.open('rouh-data').then(function (c) { return c.keys(); }).then(function (kept) {
    kept.forEach(function (req) {
      var u = new URL(req.url);
      var found = /^\/workspace\/_task\/(.+?)\/$/.exec(u.pathname);
      if (!found || !u.searchParams.get('hosted')) return;
      try { have[decodeURIComponent(found[1])] = true; } catch (e) { /* not an address of ours */ }
    });
    return Object.keys(have);
  }, function () { return Object.keys(have); });
}

window.RouhOffline = {
  answerDecision: answerDecision,
  decisions: decisionsCopy,
  queue: offlineQueue,
  online: isOnline,
  away: isAway,
  //: How many of this device's actions wait to be sent.
  waiting: function () { return waiting().length; },
  prime: primeCopy,
  hasChat: hasChat,
  wholeTasks: wholeTasks,
  open: function (tab, id) { offlineOpen(tab || '', id || ''); }
};

start();

export { answerDecision, isOnline, KINDS, OFF, paint as offlineRepaint, offlineHeard, offlineQueue, offlineResults,
  offlineSocketDown, outboxFlush, packAll, packRefresh, size, waiting, whenSaid };
