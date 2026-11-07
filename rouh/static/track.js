/* The page's half of the event log: how Rouh is used, from this tab, sent to
   `/api/events` in batches (`rouh/events.py`, `EVENTS.md`).

   Petar, 10 October 2026: "For now track everything in the way we should to be
   able to take full advantage of it." So, without anybody marking anything:

   - **Every press of a control** (`ui.click`): which control, by its key (its
     data-track, data-nav, id, data-act ...), the region it is in, and the card,
     chat, run or project it was pressed on. A link out of Rouh says its host only.
   - **Everything opened** (`ui.open`): every time the address changes, its path,
     and the chat beside it. The server reads what the path names. Nothing else
     of the address goes, so a search typed into it never does.
   - **Typing** (`ui.typed`): per spell of typing in one field, how many
     characters were typed, deleted and pasted, and for how long. Counted as the
     field grows and shrinks; **what is typed is never read, kept or sent**, and a
     password field is not counted at all.
   - **The tab** (`page.loaded`, `page.shown`, `page.hidden`): opened, in sight,
     out of sight, and how long it was in sight.

   Events wait in memory and go every few seconds, a batch at a time, and at once
   when the tab is hidden or closed, with `keepalive` so a closing tab still gets
   them there. A batch that could not be sent is tried once more with the next;
   after that it is let go. Losing an event never shows on the page, and nothing
   here ever throws into it. */
(function () {
  'use strict';

  var SEND_EVERY = 5000;   // ms between batches
  var MOST = 100;          // events in one request
  var KEEP = 2000;         // the most that wait; the oldest go first
  var IDLE = 4000;         // a pause in typing this long ends the spell
  var Q = [];
  var session = uuid7();
  var sending = false;
  var shownAt = Date.now();

  function uuid7() {
    var b = new Uint8Array(16);
    try { crypto.getRandomValues(b); } catch (e) { for (var r = 0; r < 16; r++) b[r] = Math.floor(Math.random() * 256); }
    var ms = Date.now();
    for (var i = 5; i >= 0; i--) { b[i] = ms % 256; ms = Math.floor(ms / 256); }
    b[6] = (b[6] & 0x0f) | 0x70;
    b[8] = (b[8] & 0x3f) | 0x80;
    var h = '';
    for (var j = 0; j < 16; j++) {
      h += (b[j] < 16 ? '0' : '') + b[j].toString(16);
      if (j === 3 || j === 5 || j === 7 || j === 9) h += '-';
    }
    return h;
  }
  function short(v, n) { return v == null ? '' : String(v).slice(0, n || 120); }
  function token() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  /** Queue one event. `f`: object_type, object_id, count, duration_ms, chat_id, props. */
  function event(name, f) {
    try {
      f = f || {};
      var e = { id: uuid7(), name: name, at: Date.now() };
      if (f.object_type) { e.object_type = short(f.object_type, 24); e.object_id = short(f.object_id, 300); }
      if (f.count != null) e.count = f.count;
      if (f.duration_ms != null) e.duration_ms = Math.round(f.duration_ms);
      if (f.chat_id) e.chat_id = short(f.chat_id, 128);
      if (f.props) e.props = f.props;
      Q.push(e);
      if (Q.length > KEEP) Q.splice(0, Q.length - KEEP);
    } catch (err) { /* an event is never worth an error on the page */ }
  }

  /* ---- sending ---- */
  function send(closing) {
    if (sending && !closing) return;
    if (!Q.length) return;
    var batch = Q.splice(0, MOST);
    var body;
    try { body = JSON.stringify({ session: session, events: batch }); } catch (e) { return; }
    var back = function () {
      // Tried once more with the next batch, then let go.
      var again = batch.filter(function (e) { e.tries = (e.tries || 0) + 1; return e.tries < 2; });
      Q = again.concat(Q).slice(-KEEP);
    };
    sending = true;
    try {
      fetch('/api/events', {
        method: 'POST', credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token(), 'X-Rouh-Later': '1' },
        body: body
      }).then(function (r) {
        sending = false;
        // Refused for what it is (signed out, a bad batch): sending it again would not help.
        if (r.status >= 500) back();
        else if (Q.length && !closing) send(false);
      }, function () { sending = false; back(); });
    } catch (err) { sending = false; back(); }
    if (closing && Q.length) send(true);
  }
  setInterval(function () { finishTyping(false); send(false); }, SEND_EVERY);

  /* ---- presses ---- */
  // A label is left out: pressing one presses its box as well, and that is the press.
  var CONTROL = 'a[href],button,summary,select,input[type="checkbox"],input[type="radio"],' +
    '[role="button"],[role="tab"],[role="menuitem"],[role="menuitemradio"],[role="option"],' +
    '[role="link"],[role="switch"],[role="checkbox"],[role="treeitem"],' +
    '[data-track],[data-nav],[data-act]';
  var ON = [['data-card', 'card'], ['data-run', 'run'], ['data-chat', 'chat'], ['data-project', 'project']];

  function keyOf(el) {
    var a = el.getAttribute('data-track') || el.getAttribute('data-nav') && 'nav:' + el.getAttribute('data-nav') ||
      el.id || el.getAttribute('data-act') && 'act:' + el.getAttribute('data-act') ||
      el.getAttribute('data-group') && 'group:' + el.getAttribute('data-group') ||
      el.getAttribute('data-pane') && 'pane:' + el.getAttribute('data-pane');
    if (a) return short(a);
    var cls = (el.className && typeof el.className === 'string') ? el.className.trim().split(/\s+/)[0] : '';
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '') + (el.getAttribute('role') ? '[' + el.getAttribute('role') + ']' : '');
  }
  function areaOf(el) {
    for (var n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      if (n.id) return short(n.id, 60);
    }
    return '';
  }
  function pressed(e) {
    try {
      if (e.button) return;
      var t = e.target;
      var el = t && t.closest ? t.closest(CONTROL) : null;
      if (!el) return;
      var props = { area: areaOf(el) };
      for (var i = 0; i < ON.length; i++) {
        var on = el.closest('[' + ON[i][0] + ']');
        if (on) { props.on_type = ON[i][1]; props.on_id = short(on.getAttribute(ON[i][0]), 200); break; }
      }
      if (el.tagName === 'A' && el.getAttribute('href')) {
        var to = new URL(el.getAttribute('href'), location.href);
        if (to.origin === location.origin) props.to = short(to.pathname, 200);
        else props.host = short(to.hostname, 120);
      }
      if (el.getAttribute('aria-expanded')) props.was_open = el.getAttribute('aria-expanded') === 'true';
      // From the keyboard, or by the page itself, rather than a pointer.
      if (e.detail === 0) props.no_pointer = true;
      event('ui.click', { object_type: 'control', object_id: keyOf(el), props: props });
    } catch (err) { /* never the page's problem */ }
  }
  document.addEventListener('click', pressed, true);

  /* ---- what is open ---- */
  var was = '';
  function chatOf() {
    var found = /[?&]chat=([^&#]*)/.exec(location.search || '');
    if (!found) return '';
    try { return decodeURIComponent(found[1]); } catch (e) { return found[1]; }
  }
  function changed() {
    try {
      var path = location.pathname, chat = chatOf();
      var now = path + '|' + chat;
      if (now === was) return;
      var pathMoved = was.split('|')[0] !== path;
      was = now;
      var props = { path: short(path, 300) };
      if (chat) props.chat = short(chat, 128);
      // A chat opened beside what is already on the canvas is the chat that was opened.
      if (!pathMoved && chat) event('ui.open', { object_type: 'chat', object_id: chat, props: props });
      else event('ui.open', { props: props });
    } catch (err) { /* never the page's problem */ }
  }
  ['pushState', 'replaceState'].forEach(function (name) {
    var first = history[name];
    if (typeof first !== 'function') return;
    history[name] = function () {
      var r = first.apply(this, arguments);
      changed();
      return r;
    };
  });
  window.addEventListener('popstate', changed);

  /* ---- typing: how much, never what ---- */
  var spells = [];
  function counted(el) {
    if (!el || el.closest && el.closest('[data-no-track]')) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    var type = (el.getAttribute('type') || 'text').toLowerCase();
    if (el.getAttribute('autocomplete') === 'one-time-code') return false;
    return ['text', 'search', 'email', 'url', 'tel', 'number', ''].indexOf(type) >= 0;
  }
  // The length of what is in the field, and nothing else of it.
  function lengthOf(el) {
    return el.isContentEditable ? (el.textContent || '').length : String(el.value || '').length;
  }
  function spellFor(el) {
    for (var i = 0; i < spells.length; i++) if (spells[i].el === el) return spells[i];
    var s = { el: el, key: keyOf(el), typed: 0, deleted: 0, pasted: 0, active: 0, last: 0, len: lengthOf(el) };
    spells.push(s);
    return s;
  }
  function typed(e) {
    try {
      var el = e.target;
      if (!counted(el)) return;
      var s = spellFor(el);
      var len = lengthOf(el), d = len - s.len, how = e.inputType || '';
      s.len = len;
      if (/^insertFrom(Paste|Drop)/.test(how)) { if (d > 0) s.pasted += d; }
      else if (how === 'insertText' || how === 'insertReplacementText') {
        var n = e.data ? e.data.length : Math.max(d, 0);
        s.typed += n;
        if (n > d) s.deleted += n - d;
      } else if (d > 0) s.typed += d;
      else s.deleted += -d;
      var now = Date.now();
      if (s.last && now - s.last < IDLE) s.active += now - s.last;
      s.last = now;
    } catch (err) { /* never the page's problem */ }
  }
  function finish(s) {
    if (s.typed || s.deleted || s.pasted) {
      event('ui.typed', { object_type: 'field', object_id: s.key, count: s.typed, duration_ms: s.active,
                          props: { deleted: s.deleted, pasted: s.pasted, area: areaOf(s.el) } });
    }
  }
  /** End every spell that is over: left, idle, emptied (sent), or gone. All of them when closing. */
  function finishTyping(all) {
    var now = Date.now();
    spells = spells.filter(function (s) {
      var over = all || !s.el.isConnected || document.activeElement !== s.el ||
        now - s.last > IDLE || lengthOf(s.el) === 0;
      if (over) finish(s);
      return !over;
    });
  }
  document.addEventListener('input', typed, true);
  document.addEventListener('focusout', function () { setTimeout(function () { finishTyping(false); }, 0); }, true);

  /* ---- the tab ---- */
  function hidden() {
    finishTyping(true);
    if (shownAt) event('page.hidden', { duration_ms: Date.now() - shownAt });
    shownAt = 0;
    send(true);
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') hidden();
    else if (!shownAt) { shownAt = Date.now(); event('page.shown'); }
  });
  window.addEventListener('pagehide', function () { if (shownAt) hidden(); else send(true); });

  event('page.loaded', { props: {
    width: window.innerWidth, height: window.innerHeight,
    touch: !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches),
    standalone: !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches),
    path: short(location.pathname, 300)
  } });
  changed();

  window.RouhTrack = { event: event, send: function () { finishTyping(false); send(false); },
                       waiting: function () { return Q.length; } };
})();
