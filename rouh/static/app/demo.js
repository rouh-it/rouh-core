/* Rouh's page, demo mode: the switch beside the house, what is approved, the purple dots
 * (`rouh/demo.py`, task 155).
 *
 * Petar, 28 October 2026: "the demo toggle should be next to the notifications on the bottom
 * or maybe at the top, next to the house. once in demo that should be recorded as a decision
 * and every device and new tab I open should be also demo." And on how: "just make sure css
 * loads first, and I can freely open new tabs and the loading won't mess up, also if I do
 * refresh. also if internet stops midway".
 *
 * **The style does the hiding, and it is there before anything else.** `html.demo` is put on
 * by the page's first script, in its head, from this browser's last word (localStorage) or the
 * server's cookie, before the first paint (`rouh/demo_style.py`); under it every word that is
 * not the interface is drawn in Rouh Redact, the same soft bar for every letter. This file only
 * keeps that class true: it asks the server, hears the server's `demo` message and the other
 * tabs' word (the `storage` event), and only the server ever takes it off.
 *
 * **What CSS cannot reach is done here**, while demo mode is on: the tab's title is "Rouh"; a
 * native tooltip (`title`) is taken off and put back after; a field remembers nothing; what was
 * approved is marked `data-demo-ok` and drawn as it is, with a purple dot beside it; and a frame
 * handed over by the page itself starts in demo mode too (`demoFrame`).
 */

var KEY = 'rouh.demo';

/** What the server last said: on, the preview, and what is approved. */
export var DEMO = { on: false, preview: false, dots: true, since: 0, changed: 0, known: false,
  stage: {}, stageSeconds: 900, turns: [],
  shown: { numbers: [], chats: [], settings: [], cards: [], chat_upto: {} } };

var root = document.documentElement;
var btn = document.getElementById('demoBtn');
var corner = document.getElementById('demoCorner');
/** The switch the menu was last opened from: beside the house, or in the corner. */
var opener = btn;
var menu = document.getElementById('demoMenu');
var watcher = null;
var offAsked = 0;

/* This browser's word moves towards demo mode by itself and away from it only on the server's. */
function store(on) {
  try { if (on) localStorage.setItem(KEY, '1'); else localStorage.removeItem(KEY); } catch (e) { /* private window */ }
}

function active() { return DEMO.on || DEMO.preview; }

/* ---------- what CSS cannot do --------------------------------------------------------- */

function shownNumber(n) {
  if (!n) return false;
  var list = DEMO.shown.numbers || [];
  return list.indexOf(n) >= 0 || list.indexOf(n.split('-')[0] + '*') >= 0;
}

function chatShown(id) { return !!id && (DEMO.shown.chats || []).indexOf(id) >= 0; }

/* The chat on the screen, from the address or the conversation's own element. */
function chatHere() {
  var m = /^\/chat\/([^/?#]+)/.exec(location.pathname);
  if (m) return decodeURIComponent(m[1]);
  var t = document.getElementById('transcript');
  return (t && t.getAttribute('data-chat')) || '';
}

/* Said on the stage: in a turn asked at a tab while demo mode was on (`demo.stage_turn`). */
function onStage(chat, at) {
  var began = (DEMO.stage || {})[chat] || [];
  for (var i = 0; i < began.length; i++) {
    if (at >= began[i] - 5 && at <= began[i] + DEMO.stageSeconds) return true;
  }
  return false;
}

function ok(el, yes) {
  if (yes) { if (!el.hasAttribute('data-demo-ok')) el.setAttribute('data-demo-ok', ''); }
  else if (el.hasAttribute('data-demo-ok')) el.removeAttribute('data-demo-ok');
}

/* Everything approved, marked, and a dot beside it; everything else not. */
function mark() {
  if (!active()) return;
  var chat = chatHere(), upto = (DEMO.shown.chat_upto || {})[chat];
  var whole = chatShown(chat) && !upto;
  Array.prototype.forEach.call(document.querySelectorAll('#transcript .turn'), function (t) {
    var id = Number(t.getAttribute('data-msg') || 0), at = Number(t.getAttribute('data-at') || 0);
    var turnId = t.getAttribute('data-turn') || t.getAttribute('data-trace') || '';
    var yes = whole || (chatShown(chat) && id && id <= upto) || (at && onStage(chat, at))
      || (!!turnId && (DEMO.turns || []).indexOf(turnId) >= 0) || t.hasAttribute('data-demo-here');
    ok(t, yes && !t.classList.contains('notice'));
  });
  // A task's or a step's name in the breadcrumb, shown when it was approved.
  Array.prototype.forEach.call(document.querySelectorAll('.tcrumb-chip:not(.home)'), function (c) {
    var n = c.querySelector('.tcrumb-n');
    var num = /(\d+(?:-\d+)*)/.exec((n && n.textContent) || '');
    ok(c, !!num && shownNumber(num[1]));
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-card]'), function (c) {
    ok(c, (DEMO.shown.cards || []).indexOf(c.getAttribute('data-card') || '') >= 0);
  });
  var section = /^\/anatomy\/[^/]+\/([^/]+)$/.exec(location.pathname);
  var sv = document.getElementById('settingsView');
  if (sv) ok(sv, !!section && (DEMO.shown.settings || []).indexOf(section[1]) >= 0);
  // A native tooltip is not CSS's to blur: it goes while demo mode is on, and comes back after.
  Array.prototype.forEach.call(document.querySelectorAll('[title]'), function (el) {
    if (el.closest('[data-demo-ok], [data-ui], .sb-tool, .menu')) return;
    el.setAttribute('data-demo-title', el.getAttribute('title') || '');
    el.removeAttribute('title');
  });
  // A field remembers nothing and suggests nothing.
  Array.prototype.forEach.call(document.querySelectorAll('input:not([autocomplete="off"]), textarea:not([autocomplete="off"])'),
    function (el) {
      el.setAttribute('data-demo-auto', el.getAttribute('autocomplete') || '');
      el.setAttribute('autocomplete', 'off');
      if (el.hasAttribute('list')) { el.setAttribute('data-demo-list', el.getAttribute('list') || ''); el.removeAttribute('list'); }
    });
  dots();
  if (document.title !== 'Rouh') document.title = 'Rouh';
}

/* What demo mode took away, given back when it ends. */
function unmark() {
  Array.prototype.forEach.call(document.querySelectorAll('[data-demo-title]'), function (el) {
    el.setAttribute('title', el.getAttribute('data-demo-title') || '');
    el.removeAttribute('data-demo-title');
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-demo-auto]'), function (el) {
    var was = el.getAttribute('data-demo-auto');
    if (was) el.setAttribute('autocomplete', was); else el.removeAttribute('autocomplete');
    el.removeAttribute('data-demo-auto');
    if (el.hasAttribute('data-demo-list')) { el.setAttribute('list', el.getAttribute('data-demo-list') || ''); el.removeAttribute('data-demo-list'); }
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-demo-ok]'), function (el) { el.removeAttribute('data-demo-ok'); });
  Array.prototype.forEach.call(document.querySelectorAll('.demo-dot:not(.keep)'), function (d) { d.remove(); });
}

/* A purple dot on every link to something approved, while demo mode is on. */
function dots() {
  var want = active() && DEMO.dots;
  Array.prototype.forEach.call(document.querySelectorAll('a[href^="/task/"], a[href^="/chat/"], [data-chat]'), function (el) {
    var has = el.querySelector(':scope > .demo-dot');
    var href = el.getAttribute('href') || '';
    var t = /^\/(?:task|project)\/(?:[^?#]*\/)?(\d+(?:-\d+)*)\.[^/?#]*\/?(?:[?#].*)?$/.exec(href);
    var c = /^\/chat\/([^/?#]+)/.exec(href);
    var yes = want && ((t && shownNumber(t[1])) || (c && chatShown(c[1])) || chatShown(el.getAttribute('data-chat') || ''));
    if (yes && !has) {
      var dot = document.createElement('i');
      dot.className = 'demo-dot';
      dot.setAttribute('data-ui', '');
      el.appendChild(dot);
    } else if (!yes && has) has.remove();
  });
}

var marking = 0;
function watch(on) {
  if (on && !watcher) {
    watcher = new MutationObserver(function () {
      if (marking) return;
      marking = requestAnimationFrame(function () { marking = 0; mark(); });
    });
    watcher.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });
    var t = document.querySelector('title');
    if (t) watcher.observe(t, { childList: true, characterData: true, subtree: true });
    mark();
  } else if (!on && watcher) {
    watcher.disconnect();
    watcher = null;
    unmark();
  }
}

/** A page this page writes into a frame itself, in demo mode while demo mode is on: a frame is
 *  a document of its own, which the shell's style does not reach (`rouh/demo_style.py`). */
export function demoFrame(html) {
  if (!active() || typeof html !== 'string' || html.indexOf('id="demoStyle"') >= 0) return html;
  var style = document.getElementById('demoStyle');
  if (!style) return html;
  var put = style.outerHTML + '<script>document.documentElement.classList.add("demo","demo-font")<\/script>';
  var out = /<html(\s[^>]*)?>/i.test(html)
    ? html.replace(/<html(\s[^>]*)?>/i, function (m) { return m.replace(/^<html/i, '<html class="demo demo-font"'); })
    : '<html class="demo demo-font">' + html;
  var head = /<head(\s[^>]*)?>/i.exec(out);
  return head ? out.slice(0, head.index + head[0].length) + put + out.slice(head.index + head[0].length) : put + out;
}

/* ---------- the state ------------------------------------------------------------------- */

/** What the server says, from the socket's `demo` message or an answer of /api/demo. */
export function demoHeard(m) {
  if (!m || typeof m.on !== 'boolean') return;
  var was = active();
  DEMO.on = m.on;
  DEMO.preview = !!m.preview;
  DEMO.dots = m.dots !== false;
  DEMO.since = m.since || 0;
  DEMO.changed = m.changed || 0;
  DEMO.stage = m.stage || {};
  DEMO.stageSeconds = m.stage_seconds || 900;
  DEMO.turns = m.turns || [];
  DEMO.shown = Object.assign({ numbers: [], chats: [], settings: [], cards: [], chat_upto: {} }, m.shown || {});
  DEMO.known = true;
  store(m.on);
  root.classList.toggle('demo', active());
  root.classList.toggle('demo-preview', DEMO.preview);
  watch(active());
  if (active()) mark();
  draw();
  tellFrames();
  // A page in a frame was handed over in one state or the other: it is drawn again in the new one.
  if (was !== active() && window.rouhCanvasRedraw) window.rouhCanvasRedraw();
}

/** Ask the server, on load and whenever the socket comes back. */
export function demoAsk() {
  return fetch('/api/demo', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (m) { if (m) demoHeard(m); })
    .catch(function () { /* no connection: the page stays as it was, in demo mode if it was */ });
}

function post(url, body) {
  return fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok) throw new Error(j.error || 'That did not work.');
      return j;
    });
  });
}

function turn(on) {
  // On at once, in this tab and the others of this browser, before the server has answered.
  if (on) { store(true); root.classList.add('demo'); DEMO.on = true; watch(true); draw(); }
  return post('/api/demo', { on: on, address: location.pathname }).then(function (m) {
    demoHeard(m);
  }).catch(function (err) { say(err.message); });
}

/* ---------- the switch and its menu ------------------------------------------------------ */

function draw() {
  [btn, corner].forEach(drawOne);
}

function drawOne(btn) {
  if (!btn) return;
  btn.classList.toggle('on', DEMO.on);
  btn.classList.toggle('preview', DEMO.preview);
  btn.setAttribute('aria-pressed', String(DEMO.on));
  btn.title = DEMO.on ? 'Demo mode is on: your content is blurred on every device. Press for more'
    : DEMO.preview ? 'Preview of demo mode, in this browser only. Press for more'
      : 'Demo mode: blur your content everywhere. Right-click for more';
  btn.setAttribute('aria-label', DEMO.on ? 'Demo mode is on' : DEMO.preview ? 'Demo preview' : 'Turn on demo mode');
  var pill = btn.querySelector('.demo-word');
  if (pill) pill.textContent = DEMO.on ? 'Demo' : DEMO.preview ? 'Preview' : '';
}

/** What the screen is showing now, that could be approved: a task, a step, a chat, a section. */
function here() {
  var path = decodeURIComponent(location.pathname);
  var t = /^\/(?:task|project)\/(.+?)\/?$/.exec(path);
  if (t) {
    var parts = t[1].split('/'), last = parts[parts.length - 1];
    var num = (/^(\d+(?:-\d+)*)\./.exec(last) || [])[1] || '';
    if (/\.(html|md)$/.test(last) && parts.length > 1) {
      last = parts[parts.length - 2];
      num = (/^(\d+(?:-\d+)*)\./.exec(last) || [])[1] || num;
    }
    if (num) return { kind: num.indexOf('-') > 0 ? 'step' : 'task', ref: num, label: (num.indexOf('-') > 0 ? 'step ' : 'task ') + num };
  }
  var c = /^\/chat\/([^/?#]+)/.exec(path);
  if (c) return { kind: 'chat', ref: c[1], label: 'this chat' };
  var s = /^\/anatomy\/[^/]+\/([^/]+)$/.exec(path);
  if (s) return { kind: 'setting', ref: s[1], label: 'this section' };
  return null;
}

function isShown(h) {
  if (!h) return false;
  if (h.kind === 'task' || h.kind === 'step') return shownNumber(h.ref);
  if (h.kind === 'chat') return (DEMO.shown.chats || []).indexOf(h.ref) >= 0;
  if (h.kind === 'setting') return (DEMO.shown.settings || []).indexOf(h.ref) >= 0;
  return false;
}

function item(label, act, opts) {
  var b = document.createElement('button');
  b.type = 'button';
  b.className = 'menu-item' + (opts && opts.danger ? ' danger' : '');
  b.setAttribute('role', 'menuitem');
  b.setAttribute('data-icon', (opts && opts.icon) || 'demo');
  b.textContent = label;
  if (opts && opts.note) {
    var n = document.createElement('span');
    n.className = 'menu-note';
    n.textContent = opts.note;
    b.appendChild(n);
  }
  b.addEventListener('click', function (e) { e.stopPropagation(); act(b); });
  return b;
}

function openMenu() {
  if (!menu || !opener) return;
  menu.innerHTML = '';
  var h = here();
  if (DEMO.on) {
    menu.appendChild(item('Turn off demo mode', function (b) {
      if (Date.now() - offAsked < 4000) { closeMenu(); turn(false); return; }
      offAsked = Date.now();
      var words = b.querySelector('.menu-name');
      if (window.RouhMenu && words) window.RouhMenu.label(b, 'Press again to show everything');
      else b.textContent = 'Press again to show everything';
      b.classList.add('asking');
    }, { danger: true, note: 'on every device' }));
  } else if (DEMO.preview) {
    menu.appendChild(item('End the preview', function () { closeMenu(); preview(false); }));
    menu.appendChild(item('Turn on demo mode', function () { closeMenu(); preview(false).then(function () { turn(true); }); },
      { note: 'on every device' }));
  } else {
    menu.appendChild(item('Turn on demo mode', function () { closeMenu(); turn(true); }, { note: 'on every device' }));
    menu.appendChild(item('See what the audience sees', function () { closeMenu(); preview(true); },
      { note: 'this browser only' }));
  }
  if (h) {
    var shown = isShown(h);
    menu.appendChild(item((shown ? 'Show again as it is now: ' : 'Show in demo: ') + h.label, function () {
      closeMenu();
      approve(h.kind, h.ref, true);
    }, { note: h.kind === 'task' ? 'with its steps' : '' }));
    if (shown) {
      menu.appendChild(item('Hide in demo: ' + h.label, function () { closeMenu(); approve(h.kind, h.ref, false); }));
    }
    if (h.kind === 'task') {
      menu.appendChild(item('Make a demo copy of task ' + h.ref, function () { closeMenu(); copy(h.ref); },
        { note: 'shown only in demo mode' }));
    }
  }
  menu.appendChild(item('Everything shown in demo' + (DEMO.changed ? ' (' + DEMO.changed + ' changed since)' : ''),
    function () { closeMenu(); location.href = '/tasks?view=demo'; }, { icon: 'list' }));
  if (active()) {
    menu.appendChild(item(DEMO.dots ? 'Hide the purple dots' : 'Show the purple dots', function () {
      closeMenu();
      post('/api/demo/dots', { dots: !DEMO.dots }).then(demoHeard);
    }));
  }
  if (window.RouhMenu) window.RouhMenu.dress(menu);
  menu.hidden = false;
  if (window.RouhMenu) window.RouhMenu.place(menu, opener, 'start');
  opener.setAttribute('aria-expanded', 'true');
  var first = /** @type {HTMLElement | null} */ (menu.querySelector('.menu-item'));
  if (first) first.focus();
}

function closeMenu() {
  if (!menu) return;
  menu.hidden = true;
  offAsked = 0;
  [btn, corner].forEach(function (b) { if (b) b.setAttribute('aria-expanded', 'false'); });
}

function preview(on) {
  return post('/api/demo/preview', { on: on }).then(demoHeard).catch(function (err) { say(err.message); });
}

function approve(kind, ref, on) {
  return post('/api/demo/approve', { kind: kind, ref: ref, on: on }).then(function () {
    say(on ? 'Shown in demo mode, as it is now.' : 'Hidden in demo mode again.');
    return demoAsk();
  }).then(redrawCanvas).catch(function (err) { say(err.message); });
}

/* What is on the canvas, handed over again with the new approvals. */
function redrawCanvas() {
  if (active() && window.rouhCanvasRedraw) window.rouhCanvasRedraw();
}

function copy(ref) {
  return post('/api/demo/copy', { task: ref }).then(function (m) {
    say('Demo copy made: task ' + m.number + '. It shows only in demo mode.');
    demoAsk().then(redrawCanvas);
    return m;
  }).catch(function (err) { say(err.message); });
}

var saidTimer = 0;
function say(text) {
  var t = document.getElementById('demoSaid');
  if (!t) return;
  t.textContent = text;
  t.hidden = false;
  clearTimeout(saidTimer);
  saidTimer = setTimeout(function () { t.hidden = true; }, 4000);
}

[btn, corner].forEach(function (b) {
  if (!b) return;
  b.addEventListener('click', function (e) {
    e.preventDefault();
    e.stopPropagation();
    if (menu && !menu.hidden) { closeMenu(); return; }
    opener = b;
    // Turning it on is one press and nothing to confirm; everything else is in the menu.
    if (!DEMO.on && !DEMO.preview) { turn(true); return; }
    openMenu();
  });
  b.addEventListener('contextmenu', function (e) { e.preventDefault(); opener = b; openMenu(); });
  var held = 0;
  b.addEventListener('touchstart', function () {
    held = setTimeout(function () { held = -1; opener = b; openMenu(); }, 550);
  }, { passive: true });
  b.addEventListener('touchend', function (e) {
    if (held === -1) { e.preventDefault(); }
    clearTimeout(held); held = 0;
  });
});
document.addEventListener('click', function (e) {
  var target = /** @type {Node} */ (e.target);
  if (menu && !menu.hidden && !menu.contains(target) && !(opener && opener.contains(target))) closeMenu();
});
document.addEventListener('keydown', function (e) {
  if (!menu || menu.hidden) return;
  if (e.key === 'Escape') { e.preventDefault(); closeMenu(); if (opener) opener.focus(); return; }
  if (window.RouhMenu) window.RouhMenu.keys(menu, e);
}, true);

/* ---------- the pages in frames, and the offline copy ------------------------------------ */

/* A task browser or a task's page asking to approve, take back or copy (`taskbrowser.js`). */
window.addEventListener('message', function (e) {
  var m = e.data;
  if (!m || m.type !== 'rouh-page-demo') return;
  var ok = Array.prototype.some.call(document.querySelectorAll('iframe'), function (f) {
    try { return f.contentWindow === e.source; } catch (err) { return false; }
  });
  if (!ok) return;
  var ref = String(m.ref || '');
  var done = m.act === 'copy' ? copy(ref) : approve(m.kind || 'task', ref, m.act !== 'unapprove');
  Promise.resolve(done).then(tellFrames);
});

function tellFrames() {
  var shown = (DEMO.shown && DEMO.shown.numbers) || [];
  Array.prototype.forEach.call(document.querySelectorAll('iframe'), function (f) {
    try { f.contentWindow.postMessage({ type: 'rouh-frame-demo', on: active() && DEMO.dots, shown: shown }, '*'); }
    catch (err) { /* gone */ }
  });
}

// Another tab of this browser turned it on: this one follows at once, before the server says so.
window.addEventListener('storage', function (e) {
  if (e.key !== KEY) return;
  if (e.newValue === '1') {
    root.classList.add('demo');
    DEMO.on = true;
    watch(true);
    draw();
  }
  demoAsk();
});

// The page's first script has already put the page in demo mode if this browser or the cookie
// said so; the marking starts with it, and the server is asked which it is.
if (root.classList.contains('demo')) {
  DEMO.on = true;
  draw();
  watch(true);
}
demoAsk();
