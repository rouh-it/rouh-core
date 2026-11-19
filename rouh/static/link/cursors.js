// Live cursors (Rouh Link, task 189, step 189-09): each person's pointer, caret and selection,
// shared live with the others in a space, like Figma. This is only the talking: the page that loads
// it draws (`link/space.js`, `link/livepage.js`).
//
// The page only ever asks its own Rouh (`POST /api/link/spaces/<id>/cursor`): one long request at a
// time listens for the others' cursors, and the person's own goes at most 15 times a second, only
// when it changed. Positions are a part of the space and a place inside it, never screen pixels, so
// they land in the right place on any screen. Nothing of it is kept: the Rouhs relay it live and
// forget it. With "Show my cursor to others" off, the person's own Rouh still knows where they point
// (for "this one"), and sends it to nobody.
(function () {
  'use strict';

  var MOST_A_SECOND = 15;

  function post(path, body) {
    return fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}) }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.error || ('The Rouh answered ' + r.status)); e.status = r.status; throw e; }
        return j;
      });
    });
  }

  function start(opts) {
    var base = opts.base;
    var key = opts.key || 'link-cursor-share';
    var onCursors = opts.onCursors || function () {};
    var sharing = true;
    try { sharing = localStorage.getItem(key) !== 'off'; } catch (e) {}
    // Rising across page loads too (a tenth of a second since 1970, and at most 15 a second after),
    // so the Rouhs never take a new page's cursor for an older one.
    var n = Math.floor(Date.now() / 100);
    var mine = { part: '', x: 0, y: 0 };   // what the page last said
    var sel = null, q = '';
    var sentKey = '', lastSent = 0, timer = null, inFlight = false, again = false;
    var cv = -1, listening = false, stopped = false, stats = {};
    var hidden = document.visibilityState === 'hidden';

    function body(extra) {
      var c = { part: mine.part || '', x: clamp(mine.x), y: clamp(mine.y), n: ++n };
      if (sel) c.sel = sel;
      if (q) c.q = q.slice(0, 300);
      Object.keys(extra || {}).forEach(function (k) { c[k] = extra[k]; });
      return c;
    }
    function clamp(v) { v = Number(v); return isFinite(v) ? Math.max(0, Math.min(1, Math.round(v * 1000) / 1000)) : 0; }

    function take(got) {
      if (!got || typeof got.cv !== 'number') return;
      if (got.stats) stats = got.stats;
      if (got.cv !== cv) { cv = got.cv; onCursors(got.cursors || []); }
    }

    // The person's own: at most 15 a second, only when it changed, one request at a time.
    function flush(extra) {
      if (stopped) return;
      var c = body(extra);
      var k = JSON.stringify([c.part, c.x, c.y, c.sel || null, !!c.tap, !!c.gone, sharing]);
      if (k === sentKey && !extra) { n--; return; }
      if (inFlight) { again = true; n--; return; }
      sentKey = k; lastSent = Date.now(); inFlight = true;
      post(base + '/cursor', { cursor: c, share: sharing, cv: cv, wait: 0 }).then(take).catch(function () {})
        .then(function () { inFlight = false; if (again) { again = false; soon(); } });
    }
    function soon(extra) {
      if (hidden || stopped) return;
      clearTimeout(timer);
      var wait = Math.max(0, 1000 / MOST_A_SECOND - (Date.now() - lastSent));
      if (extra) { timer = null; setTimeout(function () { flush(extra); }, wait); return; }
      timer = setTimeout(function () { timer = null; flush(); }, wait);
    }

    // Others': one long request at a time, while the tab is showing.
    function listen() {
      if (listening || stopped || hidden) return;
      listening = true;
      post(base + '/cursor', { share: sharing, cv: cv, wait: 20 }).then(function (got) {
        listening = false; take(got); listen();
      }).catch(function (e) {
        listening = false;
        // Not here (yet, or any more): ask again now and then rather than every few seconds.
        setTimeout(listen, e && e.status === 404 ? 15000 : 3000);
      });
    }

    function gone() {
      var c = body({ part: '', gone: true });
      sentKey = '';
      // keepalive, so it still goes as the page closes; a fetch, so it carries the CSRF token (csrf.js).
      try {
        fetch(base + '/cursor', { method: 'POST', credentials: 'same-origin', keepalive: true,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cursor: c, share: sharing, cv: cv, wait: 0 }) }).catch(function () {});
      } catch (e) {}
    }

    document.addEventListener('visibilitychange', function () {
      var now = document.visibilityState === 'hidden';
      if (now === hidden) return;
      hidden = now;
      if (hidden) { clearTimeout(timer); gone(); } else { listen(); soon(); }
    });
    window.addEventListener('pagehide', function () { if (!hidden) gone(); });

    listen();

    return {
      move: function (p) {
        if (!p) p = { part: '' };
        var part = String(p.part || '').slice(0, 120);
        mine = { part: part, x: part ? p.x : 0, y: part ? p.y : 0 };
        soon();
      },
      select: function (s, words) {
        sel = s || null;
        q = s ? String(words || '').slice(0, 300) : '';
        soon();
      },
      tap: function (p) {
        if (!p || !p.part) return;
        mine = { part: String(p.part).slice(0, 120), x: p.x, y: p.y };
        // The tap carries its own place, so whatever happens before it goes cannot move it.
        soon({ tap: true, part: mine.part, x: clamp(mine.x), y: clamp(mine.y) });
      },
      share: function (on) {
        on = !!on;
        if (on === sharing) return;
        // Off: the Rouh takes this person's cursor away from the others at once and keeps it for itself.
        sharing = on;
        try { localStorage.setItem(key, on ? 'on' : 'off'); } catch (e) {}
        if (on) soon(); else flush({});
      },
      sharing: function () { return sharing; },
      stats: function () { return stats; }
    };
  }

  window.RouhCursors = { start: start };
})();
