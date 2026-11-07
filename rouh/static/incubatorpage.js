/* The Incubator (`rouh/incubator.py`, `rouh/web/incubator.py`): one list of ideas for Rouh's new genes
   and mutations, drawn inside Evolution's layer at `/evolution/incubator`, and one idea at
   `/evolution/incubator/INC-<n>`.

   Petar, 3 November 2026: "list has to have all kinds of filters. make it a table. it has to be super
   presentable and easily understandable by looking at a glance. employ all possible ux ui ideas. hovers,
   column arrangements, filters sorts, etc. chat for that feature only".

   So: a table with a sticky header, sortable columns that can be shown, hidden, dragged into another
   order and resized, remembered for the person on the server (`/api/incubator/prefs`); filters for
   status, category, kind, source and dates and a text search, and saved views; coloured chips for status and category; a preview of the
   whole text on hover; a side panel with the original words in sections, its links, its pages read in
   place, and its history; status and category changed in the row; many rows selected for a status, a
   category or a merge; and the Incubator's own chat, opened beside it. Every idea and every change is
   the server's; nothing is kept in this browser. `window.RouhIncubator` is what `evolutionpage.js`
   mounts.

   And on the same day: "make the filters and labels the same as in the task browser ... an eye icon,
   click it, and hide the stuff that may not be needed. The state of the filter should be saved in the
   database ... The numbers should be in the label". So status, category, kind and source are drawn as
   the task browser's labels (`labels.js`, `labels.css`), a line each: the eye in front hides the ideas
   that carry it, a press on the label shows only those, and its count is inside it. Which labels are
   chosen and hidden, the dates, the search, the sort, the view, the columns and the saved views are all
   the person's settings on the server, saved as they change, so the list is the same on every device.

   And on 4 November 2026, a score for every idea (`rouh/incubator_score.py`): "zero friction on action,
   the bottle neck should be only my decision". Score = Impact² × Confidence × Frequency × Pain × Stars ×
   Clarity ÷ Risk, worked out here from its parts as the server does (`scoreOf`), so a star pressed
   changes the score at once, before the server has said anything. The Score column is coloured from cool
   to warm and is the first sort. A press on a star sets the person's own stars, a press on the same one
   again goes back to Rouh's suggestion, saved at once with nothing asked. Rouh's suggested stars are
   outlines and the person's own are filled. A row under the pointer is the selected row, and 1, 2 and 3
   set its stars, 0 clears them, the arrows (and j and k) move, Enter opens it, and R puts the list back in
   order, which a change never does by itself, so a row never moves from under the pointer. Each part has
   a column of its own, hidden to start with, and can be changed in place there or in the side panel. */
(function () {
  'use strict';

  var API = '/api/incubator';
  /* Every column the table can show: its key, its heading, its width to start with, and whether it is
     shown to start with. Title is always shown. */
  var COLUMNS = [
    { key: 'code', name: 'No.', w: 78, on: true },
    { key: 'score', name: 'Score', w: 156, on: true, high: true },
    { key: 'title', name: 'Idea', w: 360, on: true, fixed: true },
    { key: 'status', name: 'Status', w: 124, on: true },
    { key: 'category', name: 'Category', w: 170, on: true },
    { key: 'kind', name: 'Kind', w: 112, on: true },
    { key: 'source', name: 'Source', w: 150, on: true },
    { key: 'ref', name: 'In its source', w: 110, on: false },
    { key: 'gene', name: 'Gene', w: 150, on: false },
    { key: 'tags', name: 'Tags', w: 150, on: false },
    { key: 'links', name: 'Links', w: 74, on: true },
    { key: 'length', name: 'Words', w: 80, on: false },
    { key: 'created_at', name: 'Added', w: 104, on: true },
    { key: 'updated_at', name: 'Changed', w: 104, on: false },
    // The parts of the score, each a column of its own, hidden until shown in Columns.
    { key: 'impact', name: 'Impact', w: 150, on: false, part: true, high: true },
    { key: 'confidence', name: 'Confidence', w: 110, on: false, part: true, high: true },
    { key: 'frequency', name: 'Frequency', w: 150, on: false, part: true, high: true },
    { key: 'pain', name: 'Pain', w: 160, on: false, part: true, high: true },
    { key: 'stars', name: 'Stars', w: 120, on: false, high: true },
    { key: 'clarity', name: 'Clarity', w: 90, on: false, part: true, high: true },
    { key: 'risk', name: 'Risk', w: 84, on: false, part: true, high: true }
  ];
  /* What Sort by offers, whether or not its column is shown. */
  var SORTS = ['score', 'impact', 'stars', 'confidence', 'frequency', 'pain', 'clarity', 'risk', 'code', 'created_at'];
  var PARTS = ['impact', 'confidence', 'frequency', 'pain', 'clarity', 'risk'];
  var STAR_FACTOR = { 1: 1, 2: 1.5, 3: 2 };
  /* The page's settings are read as of this version: before 2, there was no Score column to show. */
  var PREFS_V = 2;
  var BYKEY = {};
  COLUMNS.forEach(function (c) { BYKEY[c.key] = c; });
  /* The views every Incubator has; the person's own come after them. */
  var VIEWS = [
    { id: 'all', name: 'All', f: {} },
    { id: 'new', name: 'New', f: { status: ['new'] } },
    { id: 'go', name: 'Go and in build', f: { status: ['go', 'in_build'] } },
    { id: 'nightly', name: 'From nightly', f: { source: ['nightly'] } },
    { id: 'open', name: 'Still open', f: { status: ['new', 'triaged', 'parked'] } }
  ];
  var FILTERS = [['status', 'Status'], ['category', 'Category'], ['kind', 'Kind'], ['source', 'Source']];
  var FACTS = { status: 'statuses', category: 'categories', kind: 'kinds', source: 'sources' };
  /* A label's colour (`--cc` in `labels.css`): a status's and a category's tone, and Rouh's accent for a
     kind and a source, which have none. */
  var TONE_VAR = { blue: '--cat-blue', amber: '--cat-amber', teal: '--cat-teal', rose: '--cat-rose', violet: '--cat-violet',
                   green: '--cat-green', slate: '--cat-slate', none: '--dim', accent: '--accent', user: '--user' };
  var STATUS_TONE = { new: 'blue', triaged: 'violet', go: 'amber', in_build: 'amber', built: 'green',
                      parked: 'slate', rejected: 'rose', merged: 'none' };
  var CAT_TONE = { ux: 'blue', communication: 'teal', memory: 'violet', autonomy: 'amber', integrations: 'green',
                   security: 'rose', stability: 'slate', speed: 'accent', cost: 'user', platform: 'none' };

  var S = { root: null, data: null, error: '', loading: false, seq: 0, host: null,
            q: '', f: {}, hide: {}, view: 'all', sort: { key: 'score', dir: -1 }, cols: null, widths: {},
            picked: {}, open: 0, idea: null, reading: '', said: '', menu: '', views: [], saveT: 0,
            // The selected row (its number), the order held while the person works, and the legend.
            sel: 0, hold: false, rank: null, legend: true, mx: -1, my: -1, scale: [] };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text, title) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    return b;
  }
  function call(path, body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) {
      init.method = 'POST';
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    return fetch(API + path, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that just now. Try again in a moment.'); }
        return j;
      });
    });
  }
  function go(href) { if (S.host && S.host.go) { S.host.go(href); } else { location.href = href; } }
  function moved(sub, title) { if (S.host && S.host.moved) { S.host.moved('incubator', sub, title || ''); } }

  /* ---- what the server said ---- */

  function facts(kind) { return (S.data && S.data.facts && S.data.facts[kind]) || []; }
  function nameOf(kind, id) {
    var list = facts(kind);
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) { return list[i].name; } }
    return id || '';
  }
  function lineOf(kind, id) {
    var list = facts(kind);
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) { return list[i].line || ''; } }
    return '';
  }
  function day(t) {
    if (!t) { return ''; }
    var d = new Date(t * 1000);
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: '2-digit' });
  }
  function when(t) { return t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''; }

  /* ---- the score (`rouh/incubator_score.py`) ---- */

  function partOf(v, key) {
    var p = (v.parts || {})[key];
    if (!p) { return null; }
    return p.mine != null ? p.mine : (p.rouh != null ? p.rouh : null);
  }
  /* The score from its parts, exactly as the server works it out (`incubator_score.compute`). */
  function scoreOf(v) {
    var g = {};
    for (var i = 0; i < PARTS.length; i++) { g[PARTS[i]] = partOf(v, PARTS[i]); if (g[PARTS[i]] == null) { return null; } }
    var stars = v.stars_mine || v.stars_suggested;
    if (!stars) { return null; }
    return g.impact * g.impact * g.confidence * g.frequency * g.pain * (STAR_FACTOR[stars] || 1) * g.clarity / Math.max(1, g.risk);
  }
  /* Its parts' values, its stars and its score, after anything of them changed. */
  function recalc(v) {
    PARTS.forEach(function (k) { if (v.parts && v.parts[k]) { v.parts[k].v = partOf(v, k); } });
    v.stars = v.stars_mine || v.stars_suggested || null;
    v.score = scoreOf(v);
  }
  function anyMine(v) {
    if (v.stars_mine) { return true; }
    return PARTS.some(function (k) { return v.parts && v.parts[k] && v.parts[k].mine != null; });
  }
  function partFacts(key) {
    var list = (S.data && S.data.facts && S.data.facts.score && S.data.facts.score.parts) || [];
    for (var i = 0; i < list.length; i++) { if (list[i].id === key) { return list[i]; } }
    return null;
  }
  /* A part's value in words: 80%, 3 · weekly, ×1.5, ÷1.25. */
  function shownPart(key, x) {
    if (x == null) { return '–'; }
    var f = partFacts(key), word = f && f.words ? f.words[String(x)] : '';
    if (key === 'confidence') { return Math.round(x * 100) + '%'; }
    if (key === 'impact' || key === 'frequency') { return String(x) + (word ? ' · ' + word : ''); }
    if (key === 'pain') { return '×' + x + (word ? ' · ' + word : ''); }
    if (key === 'risk') { return '÷' + x; }
    return '×' + x;
  }
  /* The values a part can be set to, for its menu. */
  function partChoices(key) {
    var f = partFacts(key);
    if (!f) { return []; }
    if (f.values) { return f.values.slice(); }
    var out = [];
    for (var x = f.min; x <= f.max + 1e-9; x += f.step) { out.push(Math.round(x * 100) / 100); }
    return out;
  }
  /* The score's colour, from cool for the lowest to warm for the highest, by where it stands among them. */
  function hueOf(score) {
    var sc = S.scale, n = sc.length;
    if (score == null || !n) { return null; }
    var lo = 0, hi = n;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (sc[mid] < score) { lo = mid + 1; } else { hi = mid; } }
    var t = n > 1 ? Math.min(1, lo / (n - 1)) : 1;
    return Math.round(215 - t * 200);
  }
  function numbersOfScore(v) {
    var g = {};
    for (var i = 0; i < PARTS.length; i++) { g[PARTS[i]] = partOf(v, PARTS[i]); if (g[PARTS[i]] == null) { return ''; } }
    if (!v.stars) { return ''; }
    return g.impact + '² × ' + g.confidence + ' × ' + g.frequency + ' × ' + g.pain + ' × ' + STAR_FACTOR[v.stars] +
      ' × ' + g.clarity + ' ÷ ' + g.risk + ' = ' + Math.round(v.score);
  }

  var STAR_PATH = 'M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 16.83l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9z';
  /* Three stars: Rouh's suggestion drawn as outlines, the person's own filled. A press sets the person's
     stars, and a press on the number they already have takes theirs away again. */
  function starsEl(v, big) {
    var wrap = el('span', 'inc-stars' + (big ? ' big' : '') + (v.stars_mine ? ' mine' : ''));
    // Over the stars the row's preview would only be in the way of the next press.
    wrap.addEventListener('mouseenter', function () { clearTimeout(S.tipT); hideTip(); });
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Stars of ' + v.code + ': ' + (v.stars_mine ? v.stars_mine + ', yours' :
      v.stars_suggested ? v.stars_suggested + ', suggested by Rouh' : 'none yet'));
    for (var k = 1; k <= 3; k++) {
      (function (k) {
        var on = (v.stars || 0) >= k;
        var b = button('inc-star' + (on ? (v.stars_mine ? ' full' : ' hint') : ''), '');
        b.setAttribute('aria-pressed', v.stars_mine === k ? 'true' : 'false');
        b.title = v.stars_mine === k ? 'Your ' + k + (k > 1 ? ' stars' : ' star') + '. Press again to go back to Rouh’s ' + (v.stars_suggested || '–') :
          k + (k > 1 ? ' stars' : ' star') + (v.stars_mine ? '' : (v.stars_suggested ? ' (Rouh suggests ' + v.stars_suggested + ')' : ''));
        b.setAttribute('aria-label', b.title);
        b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + STAR_PATH + '"/></svg>';
        b.addEventListener('click', function (e) { e.stopPropagation(); setStars(v, v.stars_mine === k ? null : k); });
        wrap.appendChild(b);
      }(k));
    }
    return wrap;
  }
  function scoreChip(v) {
    var c = el('span', 'inc-score' + (v.score == null ? ' none' : '') + (anyMine(v) ? ' mine' : ''),
               v.score == null ? '–' : String(Math.round(v.score)));
    var h = hueOf(v.score);
    if (h != null) { c.style.setProperty('--h', String(h)); }
    c.setAttribute('aria-label', v.score == null ? 'Not scored yet' : 'Score ' + Math.round(v.score) + (anyMine(v) ? ', with your changes' : ''));
    return c;
  }

  /* ---- changing a score: at once on the screen, then on the server, with nothing asked ---- */

  function saveScore(v, body, undo) {
    var seq = v._seq = (v._seq || 0) + 1;
    S.hold = true;
    recalc(v);
    repaint(v);
    call('/' + v.number + '/score', body).then(function (j) {
      if (v._seq !== seq || !j || !j.idea) { return; }
      v.stars_mine = j.idea.stars_mine; v.stars_suggested = j.idea.stars_suggested; v.parts = j.idea.parts;
      recalc(v);
      repaint(v);
    }, function (err) {
      if (v._seq === seq) { undo(); recalc(v); repaint(v); }
      S.error = String((err && err.message) || err);
      var e = S.root && S.root.querySelector('.inc-err-live');
      if (e) { e.textContent = S.error; e.hidden = false; }
    });
  }
  function setStars(v, n) {
    var was = v.stars_mine;
    v.stars_mine = n || null;
    saveScore(v, { stars: n || null }, function () { v.stars_mine = was; });
  }
  function setPart(v, key, x) {
    v.parts = v.parts || {};
    var p = v.parts[key] = v.parts[key] || {};
    var was = p.mine;
    if (x == null) { delete p.mine; delete p.by; } else { p.mine = x; p.by = 'you'; }
    saveScore(v, { part: key, value: x }, function () { if (was == null) { delete p.mine; } else { p.mine = was; } });
  }
  /* The row drawn again where it is, and the panel if it is this idea's, without the list moving. */
  function repaint(v) {
    var tr = S.root && S.root.querySelector('tr[data-n="' + v.number + '"]');
    if (tr) { var n = row(v); tr.replaceWith(n); }
    if (S.idea && S.idea.number === v.number) {
      S.idea.stars_mine = v.stars_mine; S.idea.stars_suggested = v.stars_suggested; S.idea.stars = v.stars;
      S.idea.parts = v.parts; S.idea.score = v.score;
      var old = S.root && S.root.querySelector('.inc-panel');
      if (old) { var top = old.scrollTop; var fresh = drawPanel(); old.replaceWith(fresh); fresh.scrollTop = top; }
    }
    paintNote();
  }
  function paintNote() {
    var n = S.root && S.root.querySelector('.inc-resort');
    if (n) { n.hidden = !S.hold; }
  }
  function resort() { S.hold = false; draw(); }

  /* ---- the selected row: the one under the pointer, or moved to with the keys ---- */

  function select(number, scroll) {
    S.sel = number;
    if (!S.root) { return; }
    S.root.querySelectorAll('tr.sel').forEach(function (t) { if (t.getAttribute('data-n') !== String(number)) { t.classList.remove('sel'); } });
    var tr = S.root.querySelector('tr[data-n="' + number + '"]');
    if (tr) {
      tr.classList.add('sel');
      if (scroll) {
        hideTip();
        var sc = S.root.querySelector('.inc-scroll'), head = sc && sc.querySelector('thead');
        if (sc) {
          var top = tr.offsetTop - (head ? head.offsetHeight : 0), bottom = tr.offsetTop + tr.offsetHeight;
          if (top < sc.scrollTop) { sc.scrollTop = top; }
          else if (bottom > sc.scrollTop + sc.clientHeight) { sc.scrollTop = bottom - sc.clientHeight; }
        }
      }
    }
  }
  function selectedIdea() {
    if (!S.sel || !S.data) { return null; }
    for (var i = 0; i < S.data.ideas.length; i++) { if (S.data.ideas[i].number === S.sel) { return S.data.ideas[i]; } }
    return null;
  }
  function stepSelection(by) {
    var rows = S.root ? Array.prototype.slice.call(S.root.querySelectorAll('.inc-table tbody tr[data-n]')) : [];
    if (!rows.length) { return; }
    var at = -1;
    for (var i = 0; i < rows.length; i++) { if (rows[i].getAttribute('data-n') === String(S.sel)) { at = i; break; } }
    var to = at < 0 ? (by > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, at + by));
    var n = Number(rows[to].getAttribute('data-n'));
    select(n, true);
    if (S.open && S.open !== n) { openIdea(n, true); }
  }

  function load() {
    var seq = ++S.seq;
    S.loading = !S.data;
    S.error = '';
    if (S.loading) { draw(); }
    return call('').then(function (j) {
      if (seq !== S.seq || !j) { return; }
      S.data = j;
      S.loading = false;
      (j.ideas || []).forEach(recalc);
      S.scale = (j.ideas || []).map(function (v) { return v.score; }).filter(function (x) { return x != null; })
        .sort(function (a, b) { return a - b; });
      takePrefs(j.prefs || {});
      draw();
      if (S.open && (!S.idea || S.idea.number !== S.open)) { openIdea(S.open, true); }
    }, function (err) {
      if (seq !== S.seq) { return; }
      S.loading = false;
      S.error = String((err && err.message) || err);
      draw();
    });
  }

  /* ---- the person's own settings for the page ---- */

  function takePrefs(p) {
    if (S.cols) { return; }
    var keys = Array.isArray(p.cols) ? p.cols.filter(function (k) { return BYKEY[k]; }) : null;
    S.cols = keys && keys.length ? keys : COLUMNS.filter(function (c) { return c.on; }).map(function (c) { return c.key; });
    var old = (Number(p.v) || 1) < PREFS_V;
    // Settings kept before there were scores: the Score column is put in after the number, and the list
    // is sorted by it, once; after that the person's own choice stands.
    if (old && keys && keys.length && S.cols.indexOf('score') < 0) { S.cols.splice(Math.max(0, S.cols.indexOf('code') + 1), 0, 'score'); }
    if (S.cols.indexOf('title') < 0) { S.cols.splice(1, 0, 'title'); }
    S.widths = (p.widths && typeof p.widths === 'object') ? p.widths : {};
    S.views = Array.isArray(p.views) ? p.views.filter(function (v) { return v && v.id && v.name; }) : [];
    if (p.sort && BYKEY[p.sort.key] && !old) { S.sort = { key: p.sort.key, dir: p.sort.dir === -1 ? -1 : 1 }; }
    S.legend = p.legend !== false;
    if (old && Object.keys(p).length) { savePrefs(); }
    // The filters as they were left, on whichever device.
    S.f = cleanFilters(p.f);
    S.hide = cleanHide(p.hide);
    S.q = typeof p.q === 'string' ? p.q.slice(0, 200) : '';
    S.view = typeof p.view === 'string' && (p.view === '' || allViews().some(function (v) { return v.id === p.view; })) ? p.view : 'all';
  }
  function cleanFilters(f) {
    var out = {};
    if (!f || typeof f !== 'object') { return out; }
    FILTERS.forEach(function (pair) {
      var got = f[pair[0]];
      if (Array.isArray(got)) {
        got = got.filter(function (x) { return typeof x === 'string'; });
        if (got.length) { out[pair[0]] = got; }
      }
    });
    ['from', 'to'].forEach(function (k) { if (typeof f[k] === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(f[k])) { out[k] = f[k]; } });
    return out;
  }
  function cleanHide(h) {
    var out = {};
    if (!h || typeof h !== 'object') { return out; }
    Object.keys(h).forEach(function (k) { if (h[k] && /^(status|category|kind|source):/.test(k)) { out[k] = true; } });
    return out;
  }
  /* Everything the person set on the page goes to the server half a second after the last change. */
  function savePrefs() {
    clearTimeout(S.saveT);
    S.saveT = setTimeout(function () {
      call('/prefs', { prefs: { v: PREFS_V, cols: S.cols, widths: S.widths, views: S.views, sort: S.sort,
                                f: S.f, hide: S.hide, q: S.q, view: S.view, legend: S.legend } }).catch(function () {});
    }, 500);
  }
  /* A filter, a view or the sort changed: the list is put in its order again. */
  function changed() { S.hold = false; savePrefs(); draw(); }
  function width(key) { return Math.max(56, Number(S.widths[key]) || BYKEY[key].w); }

  /* ---- filtering and sorting ---- */

  function allViews() { return VIEWS.concat(S.views); }
  function matches(v, f, q) {
    for (var i = 0; i < FILTERS.length; i++) {
      var key = FILTERS[i][0], want = f[key];
      if (want && want.length && want.indexOf(v[key] || '') < 0) { return false; }
    }
    if (f.from && v.created_at < Date.parse(f.from) / 1000) { return false; }
    if (f.to && v.created_at > Date.parse(f.to) / 1000 + 86400) { return false; }
    if (q) {
      var hay = (v.code + ' ' + v.title + ' ' + v.ref + ' ' + v.gene + ' ' + (v.tags || []).join(' ') + ' ' +
                 v.notes + ' ' + v.preview).toLowerCase();
      var words = q.toLowerCase().split(/\s+/);
      for (var j = 0; j < words.length; j++) { if (words[j] && hay.indexOf(words[j]) < 0) { return false; } }
    }
    return true;
  }
  function sortValue(v, key) {
    if (key === 'code') { return v.number; }
    if (key === 'score') { return v.score; }
    if (key === 'stars') { return v.stars; }
    if (PARTS.indexOf(key) >= 0) { return partOf(v, key); }
    if (key === 'links') { return (v.links || []).length; }
    if (key === 'tags') { return (v.tags || []).join(' '); }
    if (key === 'status') { return facts('statuses').map(function (s) { return s.id; }).indexOf(v.status); }
    if (key === 'category') { return v.category_name; }
    if (key === 'kind') { return v.kind_name; }
    if (key === 'source') { return v.source_name; }
    return v[key] == null ? '' : v[key];
  }
  /* Left out by a crossed eye: an idea any of whose labels is hidden, unless that label is also chosen,
     since choosing it is asking for its ideas (the task browser's rule, `eyeHidden` there). `skip` is a
     group whose eyes are not asked, for that group's own counts. */
  function eyeHidden(v, hide, f, skip) {
    for (var i = 0; i < FILTERS.length; i++) {
      var key = FILTERS[i][0], id = v[key] || '';
      if (key === skip || !hide[key + ':' + id]) { continue; }
      if ((f[key] || []).indexOf(id) < 0) { return true; }
    }
    return false;
  }
  function shown() {
    var ideas = (S.data && S.data.ideas) || [];
    var out = ideas.filter(function (v) { return matches(v, S.f, S.q) && !eyeHidden(v, S.hide, S.f); });
    var key = S.sort.key, dir = S.sort.dir;
    function order(a, b) {
      var x = sortValue(a, key), y = sortValue(b, key);
      // An idea with nothing to sort by (not scored yet) goes last, whichever way the list is turned.
      if (x == null || y == null) { return (x == null ? 1 : 0) - (y == null ? 1 : 0) || a.number - b.number; }
      if (typeof x === 'string' || typeof y === 'string') { x = String(x).toLowerCase(); y = String(y).toLowerCase(); }
      return (x < y ? -1 : x > y ? 1 : 0) * dir || a.number - b.number;
    }
    if (S.hold && S.rank) {
      // While the person works, every row stays where it was; a row new to the list goes where it sorts.
      var rank = S.rank;
      out.sort(function (a, b) {
        var x = rank[a.id], y = rank[b.id];
        if (x != null && y != null) { return x - y; }
        if (x == null && y == null) { return order(a, b); }
        return x == null ? 1 : -1;
      });
      return out;
    }
    out.sort(order);
    S.rank = {};
    out.forEach(function (v, i) { S.rank[v.id] = i; });
    return out;
  }
  /* How many ideas each label of one group carries, with every other filter as it is: the search, the
     dates, the other groups' choices and their crossed eyes. A label's own eye leaves its count alone,
     as a project's does in the task browser, so a hidden label still says how many it hides. */
  function countsFor(key) {
    var other = {};
    Object.keys(S.f).forEach(function (k) { if (k !== key) { other[k] = S.f[k]; } });
    var out = {};
    ((S.data && S.data.ideas) || []).forEach(function (v) {
      if (matches(v, other, S.q) && !eyeHidden(v, S.hide, S.f, key)) { out[v[key] || ''] = (out[v[key] || ''] || 0) + 1; }
    });
    return out;
  }
  function setFilter(key, values) {
    if (values && values.length) { S.f[key] = values; } else { delete S.f[key]; }
    S.view = '';
    changed();
  }
  /* An eye pressed: the ideas with that label out of the list, or back in. The list is then no longer
     the view it was, so it can be saved as one of its own, eyes and all, as the task browser's can. */
  function toggleEye(key) {
    if (S.hide[key]) { delete S.hide[key]; } else { S.hide[key] = true; }
    S.view = '';
    changed();
  }
  function clearAll() { S.f = {}; S.q = ''; S.hide = {}; S.view = 'all'; changed(); }
  function toggle(key, id) {
    var now = (S.f[key] || []).slice();
    var at = now.indexOf(id);
    if (at < 0) { now.push(id); } else { now.splice(at, 1); }
    setFilter(key, now);
  }

  /* ---- drawing ---- */

  function chip(tone, text, title) {
    var c = el('span', 'inc-chip inc-tone-' + (tone || 'none'), text);
    if (title) { c.title = title; }
    return c;
  }
  function statusChip(v) { return chip(STATUS_TONE[v.status], v.status_name, lineOf('statuses', v.status)); }
  function catChip(v) { return chip(CAT_TONE[v.category], v.category_name, lineOf('categories', v.category)); }

  function draw() {
    var root = S.root;
    if (!root || !root.isConnected) { return; }
    var keepScroll = root.querySelector('.inc-scroll');
    var top = keepScroll ? keepScroll.scrollTop : 0, left = keepScroll ? keepScroll.scrollLeft : 0;
    root.textContent = '';
    root.appendChild(drawHead());
    if (S.error) { root.appendChild(el('p', 'evo-error', S.error)); }
    if (S.said) { root.appendChild(el('p', 'evo-said', S.said)); }
    if (S.loading) {
      var sk = el('div', 'inc-skeleton');
      sk.setAttribute('aria-busy', 'true');
      sk.appendChild(el('p', 'evo-loading', 'Reading the Incubator…'));
      for (var i = 0; i < 8; i++) { sk.appendChild(el('div', 'inc-skel-row')); }
      root.appendChild(sk);
      return;
    }
    if (!S.data) { return; }
    root.appendChild(drawFilters());
    var rows = shown();
    root.appendChild(drawBulk());
    if (!S.data.ideas.length) {
      var e = el('div', 'inc-empty');
      e.appendChild(el('b', '', 'No ideas yet.'));
      e.appendChild(el('p', '', 'An idea added here, or in the Incubator’s chat, waits in this list until it is built as a gene or a mutation.'));
      var add = button('ctl', 'Add an idea');
      add.addEventListener('click', newIdea);
      e.appendChild(add);
      root.appendChild(e);
    } else if (!rows.length) {
      var none = el('div', 'inc-empty');
      none.appendChild(el('b', '', 'No idea matches.'));
      var clear = button('ctl', 'Show every idea');
      clear.addEventListener('click', clearAll);
      none.appendChild(clear);
      root.appendChild(none);
    } else {
      root.appendChild(drawTable(rows));
    }
    var sc = root.querySelector('.inc-scroll');
    if (sc) { sc.scrollTop = top; sc.scrollLeft = left; }
    if (S.open) { root.appendChild(drawPanel()); }
  }

  function drawHead() {
    var head = el('div', 'inc-head');
    var c = (S.data && S.data.counts) || { all: 0, status: {} };
    var lede = el('p', 'evo-lede inc-lede');
    lede.textContent = S.data ? (c.all + ' ideas for new genes and mutations, kept in the words they were written in, until they hatch.') :
      'Ideas for new genes and mutations, kept until they hatch.';
    head.appendChild(lede);
    var tools = el('div', 'inc-tools');
    var search = el('input', 'inc-search');
    search.type = 'search';
    search.placeholder = 'Search titles, words, numbers (I-028, 70-01)…';
    search.setAttribute('aria-label', 'Search the ideas');
    search.value = S.q;
    search.addEventListener('input', function () {
      S.q = search.value;
      clearTimeout(S.qT);
      S.qT = setTimeout(function () { changed(); var s = S.root && S.root.querySelector('.inc-search'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 180);
    });
    tools.appendChild(search);
    var add = button('ctl', '+ Idea', 'Add an idea');
    add.addEventListener('click', newIdea);
    tools.appendChild(add);
    var cols = button('ctl', 'Columns', 'Show, hide and order the columns');
    cols.setAttribute('aria-expanded', S.menu === 'cols' ? 'true' : 'false');
    cols.addEventListener('click', function (e) { e.stopPropagation(); S.menu = S.menu === 'cols' ? '' : 'cols'; draw(); });
    var colWrap = el('div', 'inc-pop-wrap');
    colWrap.appendChild(cols);
    if (S.menu === 'cols') { colWrap.appendChild(drawColumnsMenu()); }
    tools.appendChild(colWrap);
    // Sort by any part of the score, whether or not its column is shown, and which way round.
    var sortWrap = el('label', 'inc-sortby');
    sortWrap.appendChild(el('span', '', 'Sort by'));
    var sb = el('select', 'inc-sel');
    sb.setAttribute('aria-label', 'Sort by');
    SORTS.forEach(function (k) { sb.appendChild(new Option(k === 'code' ? 'Number' : BYKEY[k].name, k, false, S.sort.key === k)); });
    if (SORTS.indexOf(S.sort.key) < 0) { sb.appendChild(new Option(BYKEY[S.sort.key].name, S.sort.key, true, true)); }
    sb.addEventListener('change', function () {
      var k = sb.value;
      S.sort = { key: k, dir: BYKEY[k].high || k === 'created_at' ? -1 : 1 };
      changed();
    });
    sortWrap.appendChild(sb);
    tools.appendChild(sortWrap);
    var sk = S.sort.key, down = S.sort.dir === -1;
    var dirB = button('ctl small inc-dir', sk === 'created_at' || sk === 'updated_at' ? (down ? 'Newest first' : 'Oldest first') :
      BYKEY[sk].high || sk === 'code' || sk === 'links' || sk === 'length' ? (down ? 'Highest first' : 'Lowest first') :
      (down ? 'Z to A' : 'A to Z'), 'Turn the order round');
    dirB.addEventListener('click', function () { S.sort = { key: S.sort.key, dir: -S.sort.dir }; changed(); });
    tools.appendChild(dirB);
    var how = button('ctl small', 'How scores work', 'What the score is made of');
    how.setAttribute('aria-expanded', S.menu === 'how' ? 'true' : 'false');
    how.addEventListener('click', function (e) { e.stopPropagation(); S.menu = S.menu === 'how' ? '' : 'how'; draw(); });
    var howWrap = el('div', 'inc-pop-wrap');
    howWrap.appendChild(how);
    if (S.menu === 'how' && S.data) { howWrap.appendChild(drawHow()); }
    tools.appendChild(howWrap);
    var talk = button('ctl inc-talk', 'Chat about it', 'Open the Incubator’s own chat beside the list');
    talk.addEventListener('click', openChat);
    tools.appendChild(talk);
    head.appendChild(tools);
    // The views: every Incubator's, then the person's own, each with how many it shows. Not while the
    // list is still being read, when every count would say nought.
    if (!S.data) { return head; }
    var views = el('div', 'inc-views');
    views.setAttribute('role', 'tablist');
    views.setAttribute('aria-label', 'Saved views');
    allViews().forEach(function (v) {
      var vh = v.hide || S.hide;
      var n = ((S.data && S.data.ideas) || []).filter(function (i) { return matches(i, v.f, '') && !eyeHidden(i, vh, v.f); }).length;
      var b = button('inc-view' + (S.view === v.id ? ' on' : ''), '');
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', S.view === v.id ? 'true' : 'false');
      b.appendChild(el('span', '', v.name));
      b.appendChild(el('span', 'inc-n', n));
      b.addEventListener('click', function () {
        S.view = v.id;
        S.f = JSON.parse(JSON.stringify(v.f));
        if (v.hide) { S.hide = cleanHide(v.hide); }
        changed();
      });
      if (v.mine) {
        var x = el('span', 'inc-view-x', '×');
        x.title = 'Delete the view ' + v.name;
        x.addEventListener('click', function (e) {
          e.stopPropagation();
          S.views = S.views.filter(function (w) { return w.id !== v.id; });
          if (S.view === v.id) { S.view = 'all'; S.f = {}; }
          changed();
        });
        b.appendChild(x);
      }
      views.appendChild(b);
    });
    if ((Object.keys(S.f).length || Object.keys(S.hide).length) && !S.view) {
      var save = button('inc-view inc-view-save', '+ Save this view');
      save.addEventListener('click', function () {
        var name = (window.prompt('Name this view', '') || '').trim();
        if (!name) { return; }
        var id = 'v' + Date.now().toString(36);
        S.views.push({ id: id, name: name.slice(0, 40), f: JSON.parse(JSON.stringify(S.f)),
                       hide: JSON.parse(JSON.stringify(S.hide)), mine: true });
        S.view = id;
        changed();
      });
      views.appendChild(save);
    }
    head.appendChild(views);
    return head;
  }

  /* The labels, a line for each group, drawn as the task browser draws its own (`labels.js`): the eye in
     front, then the label with its count inside it. Under them, the dates, how many are shown and a way
     back to every idea. */
  function drawFilters() {
    var bar = el('div', 'inc-filters');
    var labs = el('div', 'inc-labels');
    var html = '';
    FILTERS.forEach(function (pair) {
      var key = pair[0], n = countsFor(key), chosen = S.f[key] || [];
      html += '<div class="inc-line" role="group" aria-label="' + pair[1] + '"><span class="inc-line-name">' + pair[1] + '</span>';
      facts(FACTS[key]).forEach(function (item) {
        var lk = key + ':' + item.id, on = chosen.indexOf(item.id) >= 0, count = n[item.id] || 0;
        var tone = key === 'status' ? STATUS_TONE[item.id] : key === 'category' ? CAT_TONE[item.id] : 'accent';
        var style = '--cc:var(' + (TONE_VAR[tone] || '--accent') + ')';
        var tip = (on ? 'Showing only ' : 'Only ') + item.name + (item.line ? ': ' + item.line : '') + (on ? '. Press again to show the rest' : '');
        var btn = '<button type="button" class="rl-chip inc-lab' + (on ? ' on' : '') + (count ? '' : ' zero') +
          '" data-group="' + key + '" data-id="' + escAttr(item.id) + '" aria-pressed="' + on + '" title="' + escAttr(tip) + '">' +
          (key === 'status' || key === 'category' ? '<i class="rl-dot"></i>' : '') +
          '<span class="lbl">' + escAttr(item.name) + '</span> <span class="c">' + count + '</span></button>';
        html += window.RouhLabels.html(lk, btn, { eye: true, style: style });
      });
      html += '</div>';
    });
    labs.innerHTML = html;
    labs.querySelectorAll('.rl-lab').forEach(function (l) {
      var key = l.getAttribute('data-lab'), at = key.indexOf(':'), group = key.slice(0, at), id = key.slice(at + 1);
      window.RouhLabels.paint(l, { off: !!S.hide[key], name: nameOf(FACTS[group], id), what: 'the ideas that are',
                                   bright: (S.f[group] || []).indexOf(id) >= 0 });
    });
    labs.addEventListener('click', function (e) {
      var t = /** @type {Element} */ (e.target);
      var eye = t.closest && t.closest('.rl-eye');
      if (eye) { toggleEye(eye.getAttribute('data-eye')); return; }
      var b = t.closest && t.closest('.inc-lab');
      if (b) { toggle(b.getAttribute('data-group'), b.getAttribute('data-id')); }
    });
    bar.appendChild(labs);
    var line = el('div', 'inc-active');
    // Dates: added from and to.
    var dates = el('div', 'inc-pop-wrap');
    var don = S.f.from || S.f.to;
    var db = button('inc-filter inc-caret' + (don ? ' on' : ''), 'Added' + (don ? ' · ' + (S.f.from || '…') + ' – ' + (S.f.to || '…') : ''));
    db.addEventListener('click', function (e) { e.stopPropagation(); S.menu = S.menu === 'dates' ? '' : 'dates'; draw(); });
    dates.appendChild(db);
    if (S.menu === 'dates') {
      var pop = el('div', 'inc-pop inc-pop-dates');
      pop.addEventListener('click', function (e) { e.stopPropagation(); });
      [['from', 'From'], ['to', 'To']].forEach(function (p) {
        var l = el('label', 'inc-pop-row');
        l.appendChild(el('span', '', p[1]));
        var i = el('input');
        i.type = 'date';
        i.value = S.f[p[0]] || '';
        i.addEventListener('change', function () { if (i.value) { S.f[p[0]] = i.value; } else { delete S.f[p[0]]; } S.view = ''; changed(); });
        l.appendChild(i);
        pop.appendChild(l);
      });
      dates.appendChild(pop);
    }
    line.appendChild(dates);
    var rows = shown().length, all = S.data.ideas.length;
    var hid = S.data.ideas.filter(function (v) { return matches(v, S.f, S.q) && eyeHidden(v, S.hide, S.f); }).length;
    line.appendChild(el('span', 'inc-count', rows + ' of ' + all + ' shown' +
      (hid ? ', ' + hid + ' hidden by a crossed eye' : '')));
    // A change never moves a row from under the pointer: the list says its order changed, and R (or a
    // press here) puts it back in order.
    var note = button('inc-resort', 'Order changed · R to re-sort', 'Put the list in order again');
    note.hidden = !S.hold;
    note.addEventListener('click', resort);
    line.appendChild(note);
    var sc = S.data.scoring || {};
    if (sc.running) {
      line.appendChild(el('span', 'inc-count inc-scoring', 'Rouh is scoring the ideas: ' + (sc.done || 0) + ' of ' + sc.total + ' so far.'));
    } else if (sc.all && sc.scored < sc.all) {
      var go = button('inc-clear', 'Score the ' + (sc.all - sc.scored) + ' ideas without a score', 'Rouh scores them now, in the background');
      go.addEventListener('click', function () {
        go.disabled = true;
        call('/scoring', {}).then(function (j) { S.data.scoring = j.scoring; draw(); }, fail);
      });
      line.appendChild(go);
    }
    if (Object.keys(S.f).length || Object.keys(S.hide).length || S.q) {
      var clear = button('inc-clear', 'Show every idea', 'Take off every filter, the search and every crossed eye');
      clear.addEventListener('click', clearAll);
      line.appendChild(clear);
    }
    bar.appendChild(line);
    var err = el('p', 'evo-error inc-err-live');
    err.hidden = true;
    bar.appendChild(err);
    // The keys, once, until closed; never on a screen with no keys to press.
    if (S.legend) {
      var lg = el('div', 'inc-legend');
      lg.setAttribute('aria-label', 'Keys');
      [['Hover', 'a row'], ['1 2 3', 'stars'], ['0', 'clears them'], ['↑ ↓ j k', 'move'], ['Enter', 'opens'], ['R', 're-sorts']].forEach(function (k) {
        var it = el('span', 'inc-key');
        it.appendChild(el('kbd', '', k[0]));
        it.appendChild(document.createTextNode(' ' + k[1]));
        lg.appendChild(it);
      });
      var lx = button('inc-legend-x', '×', 'Close the keys');
      lx.addEventListener('click', function () { S.legend = false; savePrefs(); draw(); });
      lg.appendChild(lx);
      bar.appendChild(lg);
    }
    return bar;
  }
  function escAttr(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  /* "How scores work": the formula, each part's scale, and what the stars and keys do. */
  function drawHow() {
    var pop = el('div', 'inc-pop inc-pop-how');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'How scores work');
    pop.addEventListener('click', function (e) { e.stopPropagation(); });
    var f = S.data.facts.score || {};
    pop.appendChild(el('b', 'inc-how-h', 'How scores work'));
    pop.appendChild(el('div', 'inc-formula', 'Score = ' + (f.formula || '')));
    var ul = el('ul', 'inc-how-l');
    (f.parts || []).forEach(function (p) {
      var li = el('li');
      li.appendChild(el('b', '', p.name + ' '));
      var scale = p.values ? p.values.map(function (x) { return '×' + x + (p.words && p.words[String(x)] ? ' ' + p.words[String(x)] : ''); }).join(', ')
        : p.id === 'confidence' ? '50% to 100%' : p.id === 'risk' ? '÷' + p.min + ' to ÷' + p.max : p.id === 'clarity' ? '×' + p.min + ' to ×' + p.max
        : p.min + ' to ' + p.max + (p.words ? ' (' + Object.keys(p.words).map(function (k) { return k + ' ' + p.words[k]; }).join(', ') + ')' : '');
      li.appendChild(el('span', '', scale + '. ' + p.line + (p.id === 'frequency' ? ' Demand, an idea that came back (merged duplicates, other sources, chats, a nightly run proposing it again), raises it.' : '')));
      ul.appendChild(li);
    });
    var st = el('li');
    st.appendChild(el('b', '', 'Stars '));
    st.appendChild(el('span', '', '1, 2 or 3, ×1, ×1.5 or ×2. Rouh suggests stars for every idea, drawn as outlines; yours are filled, and win. Press a star to set yours, the same one again to go back to Rouh’s.'));
    ul.appendChild(st);
    pop.appendChild(ul);
    pop.appendChild(el('p', 'inc-how-p', 'There is no part for effort. Rouh writes every part with a one-line reason; a part you change is yours, and Rouh never changes it when it scores again. Hover a score to see it taken apart.'));
    pop.appendChild(el('p', 'inc-how-p', 'Keys: hover a row (or move with ↑ ↓, j k), then 1, 2, 3 for its stars, 0 to clear them, Enter to open it, R to put the list back in order.'));
    return pop;
  }

  function drawColumnsMenu() {
    var pop = el('div', 'inc-pop inc-pop-cols');
    pop.addEventListener('click', function (e) { e.stopPropagation(); });
    pop.appendChild(el('p', 'inc-pop-h', 'Columns: tick to show, arrows to move. Drag a heading to move it, its edge to widen it.'));
    var order = S.cols.concat(COLUMNS.map(function (c) { return c.key; }).filter(function (k) { return S.cols.indexOf(k) < 0; }));
    order.forEach(function (key) {
      var c = BYKEY[key];
      var row = el('div', 'inc-pop-row');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = S.cols.indexOf(key) >= 0;
      box.disabled = !!c.fixed;
      box.id = 'incCol-' + key;
      box.addEventListener('change', function () {
        if (box.checked) { S.cols.push(key); } else { S.cols = S.cols.filter(function (k) { return k !== key; }); }
        savePrefs(); draw();
      });
      var l = el('label', '', c.name);
      l.htmlFor = box.id;
      row.appendChild(box);
      row.appendChild(l);
      var at = S.cols.indexOf(key);
      if (at >= 0) {
        var up = button('inc-mv', '↑', 'Move ' + c.name + ' left');
        up.disabled = at === 0;
        up.addEventListener('click', function () { move(key, at - 1); });
        var dn = button('inc-mv', '↓', 'Move ' + c.name + ' right');
        dn.disabled = at === S.cols.length - 1;
        dn.addEventListener('click', function () { move(key, at + 1); });
        row.appendChild(up);
        row.appendChild(dn);
      }
      pop.appendChild(row);
    });
    var reset = button('ctl small', 'Put the columns back');
    reset.addEventListener('click', function () {
      S.cols = COLUMNS.filter(function (c) { return c.on; }).map(function (c) { return c.key; });
      S.widths = {};
      savePrefs(); draw();
    });
    pop.appendChild(reset);
    return pop;
  }
  function move(key, to) {
    var from = S.cols.indexOf(key);
    if (from < 0 || to < 0 || to >= S.cols.length) { return; }
    S.cols.splice(from, 1);
    S.cols.splice(to, 0, key);
    savePrefs(); draw();
  }

  function drawBulk() {
    var ids = Object.keys(S.picked).filter(function (k) { return S.picked[k]; }).map(Number);
    var bar = el('div', 'inc-bulk');
    bar.hidden = !ids.length;
    if (!ids.length) { return bar; }
    bar.appendChild(el('b', '', ids.length + ' chosen'));
    var st = el('select', 'inc-sel');
    st.setAttribute('aria-label', 'Set the status of the chosen ideas');
    st.appendChild(new Option('Set status…', ''));
    facts('statuses').forEach(function (s) { if (s.id !== 'merged') { st.appendChild(new Option(s.name, s.id)); } });
    st.addEventListener('change', function () {
      if (!st.value) { return; }
      if (st.value === 'go' && !window.confirm('Hand ' + ids.length + ' ideas to Gene therapy to be built?')) { st.value = ''; return; }
      bulk({ ids: ids, status: st.value });
    });
    bar.appendChild(st);
    var ct = el('select', 'inc-sel');
    ct.setAttribute('aria-label', 'Set the category of the chosen ideas');
    ct.appendChild(new Option('Set category…', ''));
    facts('categories').forEach(function (c) { ct.appendChild(new Option(c.name, c.id)); });
    ct.addEventListener('change', function () { if (ct.value) { bulk({ ids: ids, category: ct.value }); } });
    bar.appendChild(ct);
    var mg = button('ctl small', 'Merge…', 'Merge the chosen ideas into one');
    mg.addEventListener('click', function () {
      var into = (window.prompt('Merge them into which idea? Its number, such as INC-12', 'INC-' + Math.min.apply(null, numbersOf(ids))) || '').trim();
      if (!into) { return; }
      var n = Number(into.replace(/^INC-/i, ''));
      bulk({ ids: numbersOf(ids).filter(function (x) { return x !== n; }), into: n });
    });
    bar.appendChild(mg);
    var none = button('ctl small', 'Clear');
    none.addEventListener('click', function () { S.picked = {}; draw(); });
    bar.appendChild(none);
    return bar;
  }
  function numbersOf(ids) {
    var by = {};
    S.data.ideas.forEach(function (v) { by[v.id] = v.number; });
    return ids.map(function (i) { return by[i]; });
  }
  function bulk(body) {
    body.ids = body.into ? body.ids : numbersOf(body.ids);
    call('/bulk', body).then(function (j) {
      S.said = j.done.length + ' changed' + (j.failed.length ? '; ' + j.failed.length + ' not: ' + j.failed.map(function (f) { return f.id + ' (' + f.why + ')'; }).join(', ') : '.');
      S.picked = {};
      load();
    }, fail);
  }
  function fail(err) { S.error = String((err && err.message) || err); draw(); }

  function drawTable(rows) {
    var scroll = el('div', 'inc-scroll');
    var table = el('table', 'inc-table');
    table.setAttribute('aria-rowcount', String(rows.length));
    var cg = el('colgroup');
    var c0 = el('col');
    c0.style.width = '36px';
    cg.appendChild(c0);
    S.cols.forEach(function (k) { var c = el('col'); c.style.width = width(k) + 'px'; cg.appendChild(c); });
    table.appendChild(cg);
    var total = 36;
    S.cols.forEach(function (k) { total += width(k); });
    table.style.width = total + 'px';
    var thead = el('thead');
    var hr = el('tr');
    var all = el('th', 'inc-pick');
    var allBox = el('input');
    allBox.type = 'checkbox';
    allBox.setAttribute('aria-label', 'Choose every idea shown');
    allBox.checked = rows.length > 0 && rows.every(function (v) { return S.picked[v.id]; });
    allBox.addEventListener('change', function () { rows.forEach(function (v) { S.picked[v.id] = allBox.checked; }); draw(); });
    all.appendChild(allBox);
    hr.appendChild(all);
    S.cols.forEach(function (k) { hr.appendChild(headCell(k)); });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tb = el('tbody');
    rows.forEach(function (v) { tb.appendChild(row(v)); });
    table.appendChild(tb);
    scroll.appendChild(table);
    return scroll;
  }

  function headCell(key) {
    var c = BYKEY[key];
    var th = el('th', 'inc-th');
    th.setAttribute('scope', 'col');
    var on = S.sort.key === key;
    th.setAttribute('aria-sort', on ? (S.sort.dir === 1 ? 'ascending' : 'descending') : 'none');
    var b = button('inc-sort', c.name + (on ? (S.sort.dir === 1 ? ' ↑' : ' ↓') : ''), 'Sort by ' + c.name +
      (partFacts(key) ? ': ' + partFacts(key).line : key === 'score' ? ': ' + ((S.data && S.data.facts.score) || {}).formula : ''));
    b.addEventListener('click', function () {
      S.sort = { key: key, dir: on ? -S.sort.dir : (c.high || key === 'created_at' || key === 'updated_at' || key === 'links' || key === 'length' ? -1 : 1) };
      changed();
    });
    th.appendChild(b);
    // Dragged onto another heading, a column moves there.
    th.draggable = true;
    th.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/plain', key); th.classList.add('dragging'); });
    th.addEventListener('dragend', function () { th.classList.remove('dragging'); });
    th.addEventListener('dragover', function (e) { e.preventDefault(); th.classList.add('drop'); });
    th.addEventListener('dragleave', function () { th.classList.remove('drop'); });
    th.addEventListener('drop', function (e) {
      e.preventDefault();
      var from = e.dataTransfer.getData('text/plain');
      if (from && from !== key && BYKEY[from]) { move(from, S.cols.indexOf(key)); }
    });
    // Its right edge widens it.
    var grip = el('span', 'inc-grip');
    grip.setAttribute('aria-hidden', 'true');
    grip.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      e.stopPropagation();
      th.draggable = false;
      var x0 = e.clientX, w0 = width(key);
      var col = th.closest('table').querySelectorAll('col')[S.cols.indexOf(key) + 1];
      function at(ev) { S.widths[key] = Math.max(56, Math.min(900, w0 + ev.clientX - x0)); if (col) { col.style.width = S.widths[key] + 'px'; } }
      function up() { document.removeEventListener('pointermove', at); document.removeEventListener('pointerup', up); th.draggable = true; savePrefs(); draw(); }
      document.addEventListener('pointermove', at);
      document.addEventListener('pointerup', up);
    });
    th.appendChild(grip);
    return th;
  }

  function cell(v, key) {
    var td = el('td', 'inc-td inc-c-' + key);
    if (key === 'code') { td.appendChild(el('span', 'inc-code', v.code)); }
    else if (key === 'score') {
      td.appendChild(starsEl(v));
      var chip = scoreChip(v);
      chip.addEventListener('mouseenter', function (e) { clearTimeout(S.tipT); S.hx = e.clientX; S.hy = e.clientY; S.tipT = setTimeout(function () { showBreakdown(v); }, 120); });
      chip.addEventListener('mouseleave', hideTip);
      td.appendChild(chip);
    } else if (key === 'stars') {
      td.appendChild(starsEl(v));
      td.appendChild(el('span', 'inc-pv', v.stars ? '×' + STAR_FACTOR[v.stars] : ''));
    } else if (PARTS.indexOf(key) >= 0) {
      td.appendChild(partSelect(v, key));
    }
    else if (key === 'title') {
      var t = el('span', 'inc-title', v.title);
      td.appendChild(t);
      if (v.merged_into) { td.appendChild(el('span', 'inc-sub', 'merged into ' + v.merged_into.code)); }
      else if (v.notes) { td.appendChild(el('span', 'inc-sub', v.notes.split('\n')[0].slice(0, 140))); }
    } else if (key === 'status') {
      td.appendChild(inlineSelect(v, 'status', facts('statuses').filter(function (s) { return s.id !== 'merged' || v.status === 'merged'; }), statusChip(v)));
    } else if (key === 'category') {
      td.appendChild(inlineSelect(v, 'category', facts('categories'), catChip(v)));
    } else if (key === 'kind') { td.textContent = v.kind ? v.kind_name : '–'; td.title = v.kind_name; }
    else if (key === 'source') {
      td.textContent = v.source_name;
      if ((v.sources || []).length > 1) { td.appendChild(el('span', 'inc-more', '+' + (v.sources.length - 1))); td.title = v.sources.map(function (s) { return nameOf('sources', s); }).join(', '); }
    } else if (key === 'links') {
      var n = (v.links || []).length;
      td.textContent = n ? String(n) : '–';
      td.title = (v.links || []).map(function (l) { return l.kind; }).filter(function (x, i, a) { return a.indexOf(x) === i; }).join(', ');
    } else if (key === 'tags') { (v.tags || []).forEach(function (t) { td.appendChild(el('span', 'inc-tag', t)); }); }
    else if (key === 'length') { td.textContent = v.length ? Math.max(1, Math.round(v.length / 6)).toLocaleString() : '–'; }
    else if (key === 'created_at' || key === 'updated_at') { td.textContent = day(v[key]); td.title = when(v[key]); }
    else { td.textContent = v[key] || '–'; td.title = v[key] || ''; }
    return td;
  }

  /* A part's value, with a menu underneath: a choice is the person's, saved at once; "Rouh's" gives it back. */
  function partSelect(v, key) {
    var p = (v.parts || {})[key] || {};
    var mine = p.mine != null;
    var wrap = el('span', 'inc-inline inc-part' + (mine ? ' mine' : ''));
    wrap.appendChild(el('span', 'inc-pv', shownPart(key, partOf(v, key))));
    wrap.title = (partFacts(key) || {}).name + ': ' + (mine ? 'yours' + (p.by && p.by !== 'you' ? ' (set by ' + p.by + ')' : '') +
      '; Rouh said ' + shownPart(key, p.rouh) : 'Rouh’s') + (p.why ? '. ' + p.why : '');
    var sel = el('select', 'inc-inline-sel');
    sel.setAttribute('aria-label', (partFacts(key) || {}).name + ' of ' + v.code);
    sel.appendChild(new Option('Rouh’s: ' + shownPart(key, p.rouh), '', false, !mine));
    var choices = partChoices(key);
    if (mine && choices.indexOf(p.mine) < 0) { choices.push(p.mine); }
    choices.forEach(function (x) { sel.appendChild(new Option(shownPart(key, x), String(x), false, mine && x === p.mine)); });
    sel.addEventListener('click', function (e) { e.stopPropagation(); });
    sel.addEventListener('keydown', function (e) { e.stopPropagation(); });
    sel.addEventListener('change', function () { setPart(v, key, sel.value === '' ? null : Number(sel.value)); });
    wrap.appendChild(sel);
    return wrap;
  }

  /* A chip that is a select underneath: pressed, it offers the other choices, and a choice is saved. */
  function inlineSelect(v, field, list, face) {
    var wrap = el('span', 'inc-inline');
    wrap.appendChild(face);
    var sel = el('select', 'inc-inline-sel');
    sel.setAttribute('aria-label', (field === 'status' ? 'Status of ' : 'Category of ') + v.code);
    list.forEach(function (o) { sel.appendChild(new Option(o.name, o.id, false, o.id === v[field])); });
    sel.addEventListener('click', function (e) { e.stopPropagation(); });
    sel.addEventListener('change', function () {
      var want = sel.value;
      if (field === 'status' && want === 'go' && !window.confirm('Hand ' + v.code + ' to Gene therapy to be built?')) { sel.value = v.status; return; }
      var done = field === 'status' ? call('/' + v.number + '/status', { status: want }) : call('/' + v.number, { category: want });
      done.then(function (j) { S.said = j.said || ''; load(); if (S.open === v.number) { openIdea(v.number, true); } }, fail);
    });
    wrap.appendChild(sel);
    return wrap;
  }

  function row(v) {
    var tr = el('tr', 'inc-tr' + (S.open === v.number ? ' open' : '') + (S.picked[v.id] ? ' picked' : '') +
      (v.status === 'merged' ? ' merged' : '') + (S.sel === v.number ? ' sel' : ''));
    tr.setAttribute('data-n', String(v.number));
    tr.tabIndex = 0;
    tr.setAttribute('aria-label', v.code + ' ' + v.title + ', ' + v.status_name);
    var pick = el('td', 'inc-pick');
    var box = el('input');
    box.type = 'checkbox';
    box.checked = !!S.picked[v.id];
    box.setAttribute('aria-label', 'Choose ' + v.code);
    box.addEventListener('click', function (e) { e.stopPropagation(); });
    box.addEventListener('change', function () { S.picked[v.id] = box.checked; draw(); });
    pick.appendChild(box);
    tr.appendChild(pick);
    S.cols.forEach(function (k) { tr.appendChild(cell(v, k)); });
    tr.addEventListener('click', function () { openIdea(v.number); });
    tr.addEventListener('keydown', function (e) { if (e.key === 'Enter') { openIdea(v.number); } });
    tr.addEventListener('mouseenter', function (e) { hoverSoon(v, e); });
    tr.addEventListener('mousemove', function (e) {
      S.hx = e.clientX; S.hy = e.clientY; placeTip();
      // The row under the pointer is the selected one, but only when the pointer moved: a list scrolled
      // by the keys slides rows under a pointer that stood still.
      if (e.screenX === S.mx && e.screenY === S.my) { return; }
      S.mx = e.screenX; S.my = e.screenY;
      if (S.sel !== v.number) { select(v.number); }
    });
    tr.addEventListener('mouseleave', hideTip);
    return tr;
  }

  /* ---- the preview on hover ---- */

  var tip = null;
  function hoverSoon(v, e) {
    clearTimeout(S.tipT);
    S.hx = e.clientX; S.hy = e.clientY;
    S.tipT = setTimeout(function () { showTip(v); }, 380);
  }
  function showTip(v) {
    if (!tip) { tip = el('div', 'inc-tip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    tip.textContent = '';
    tip.classList.remove('inc-tip-score');
    var h = el('div', 'inc-tip-h');
    h.appendChild(el('span', 'inc-code', v.code));
    h.appendChild(statusChip(v));
    h.appendChild(catChip(v));
    tip.appendChild(h);
    tip.appendChild(el('b', 'inc-tip-t', v.title));
    tip.appendChild(el('div', 'inc-tip-x', v.preview || 'No words kept beyond its title.'));
    tip.appendChild(el('div', 'inc-tip-f', v.source_name + (v.ref ? ' · ' + v.ref : '') + ' · ' + (v.links || []).length + ' links · click to open'));
    tip.hidden = false;
    placeTip();
  }
  /* The score taken apart: each part, its value, whose it is and why, and the formula with its numbers. */
  function showBreakdown(v) {
    if (!tip) { tip = el('div', 'inc-tip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    tip.textContent = '';
    tip.classList.add('inc-tip-score');
    var h = el('div', 'inc-tip-h');
    h.appendChild(el('span', 'inc-code', v.code));
    h.appendChild(scoreChip(v));
    if (anyMine(v)) { h.appendChild(el('span', 'inc-n', 'with your changes')); }
    tip.appendChild(h);
    if (v.score == null) {
      tip.appendChild(el('div', 'inc-tip-x', 'Not scored yet: Rouh scores every idea in the background, a moment after it is added.'));
    } else {
      tip.appendChild(breakdownTable(v));
      tip.appendChild(el('div', 'inc-formula', ((S.data.facts.score || {}).formula || '') + '\n' + numbersOfScore(v)));
    }
    tip.hidden = false;
    placeTip();
  }
  function breakdownTable(v) {
    var t = el('table', 'inc-bd');
    PARTS.concat(['stars']).forEach(function (key) {
      var tr = el('tr');
      var name = key === 'stars' ? 'Stars' : (partFacts(key) || {}).name;
      tr.appendChild(el('th', '', name));
      var p = key === 'stars' ? null : (v.parts || {})[key] || {};
      var mine = key === 'stars' ? !!v.stars_mine : p.mine != null;
      var val = key === 'stars' ? (v.stars ? v.stars + ' · ×' + STAR_FACTOR[v.stars] : '–') : shownPart(key, partOf(v, key));
      var td = el('td', 'inc-bd-v' + (mine ? ' mine' : ''), val);
      tr.appendChild(td);
      var why = key === 'stars' ? (v.stars_mine ? 'Yours; Rouh suggests ' + (v.stars_suggested || '–') + '. ' : 'Rouh’s suggestion. ') + (v.stars_why || '')
        : (mine ? 'Yours; Rouh said ' + shownPart(key, p.rouh) + '. ' : '') + (p.why || '');
      tr.appendChild(el('td', 'inc-bd-why', why));
      t.appendChild(tr);
    });
    return t;
  }
  function placeTip() {
    if (!tip || tip.hidden) { return; }
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.min(window.innerWidth - w - 12, (S.hx || 0) + 18);
    var y = (S.hy || 0) + 18;
    if (y + h > window.innerHeight - 8) { y = Math.max(8, (S.hy || 0) - h - 14); }
    tip.style.left = Math.max(8, x) + 'px';
    tip.style.top = y + 'px';
  }
  function hideTip() { clearTimeout(S.tipT); if (tip) { tip.hidden = true; } }

  /* ---- one idea, in the side panel ---- */

  function openIdea(number, quiet) {
    hideTip();
    S.open = number;
    S.reading = '';
    if (!quiet || !S.idea || S.idea.number !== number) { S.idea = null; }
    draw();
    call('/' + number).then(function (j) {
      if (S.open !== number) { return; }
      S.idea = j.idea;
      moved('INC-' + number, j.idea.title);
      draw();
      var p = S.root && S.root.querySelector('.inc-panel');
      if (p && !quiet) { p.focus({ preventScroll: true }); }
    }, function (err) {
      if (S.open !== number) { return; }
      S.idea = { error: String((err && err.message) || err), number: number };
      draw();
    });
  }
  function closeIdea() {
    S.open = 0; S.idea = null; S.reading = '';
    moved('', '');
    draw();
  }

  function drawPanel() {
    var p = el('aside', 'inc-panel');
    p.tabIndex = -1;
    p.setAttribute('aria-label', 'One idea');
    var x = button('layer-x inc-panel-x', '×', 'Close the idea');
    x.addEventListener('click', closeIdea);
    p.appendChild(x);
    var v = S.idea;
    if (!v) { p.appendChild(el('p', 'evo-loading', 'Reading INC-' + S.open + '…')); return p; }
    if (v.error) { p.appendChild(el('p', 'evo-error', v.error)); return p; }
    var head = el('div', 'inc-p-head');
    head.appendChild(el('span', 'inc-code', v.code));
    head.appendChild(statusChip(v));
    head.appendChild(catChip(v));
    if (v.kind) { head.appendChild(chip('none', v.kind_name + (v.gene ? ': ' + v.gene : ''))); }
    p.appendChild(head);
    var title = el('h4', 'inc-p-title', v.title);
    p.appendChild(title);
    var meta = el('p', 'inc-p-meta');
    meta.textContent = 'From ' + v.sources.map(function (s) { return nameOf('sources', s); }).join(' and ') +
      (v.ref ? ', as ' + (/^\d+$/.test(v.ref) ? 'task ' : /^\d+-\d+$/.test(v.ref) ? 'step ' : '') + v.ref : '') +
      (v.source_status ? ' (' + v.source_status + ')' : '') +
      '. Added ' + when(v.created_at) + '.';
    p.appendChild(meta);
    if (v.merged_into) {
      var mi = el('p', 'evo-said');
      mi.textContent = 'Merged into ' + v.merged_into.code + '. ';
      var mo = button('inc-a', 'Open ' + v.merged_into.code);
      mo.addEventListener('click', function () { openIdea(Number(v.merged_into.code.replace(/^INC-/, ''))); });
      mi.appendChild(mo);
      p.appendChild(mi);
    }
    // What can be done with it.
    var acts = el('div', 'inc-p-acts');
    if (['go', 'in_build', 'built', 'merged'].indexOf(v.status) < 0) {
      var gob = button('ctl inc-go', 'Go: build it', 'Hand it to Gene therapy, the one way Rouh builds a gene or a mutation');
      gob.addEventListener('click', function () {
        if (!window.confirm('Hand ' + v.code + ' to Gene therapy to be built?')) { return; }
        gob.disabled = true;
        call('/' + v.number + '/status', { status: 'go' }).then(function (j) { S.said = j.said || ''; load(); openIdea(v.number, true); }, fail);
      });
      acts.appendChild(gob);
    }
    var st = el('select', 'inc-sel');
    st.setAttribute('aria-label', 'Status of ' + v.code);
    facts('statuses').forEach(function (s) { if (s.id !== 'merged' && s.id !== 'go') { st.appendChild(new Option(s.name, s.id, false, s.id === v.status)); } });
    if (v.status === 'go' || v.status === 'merged') { st.insertBefore(new Option(v.status_name, v.status, true, true), st.firstChild); }
    st.addEventListener('change', function () { call('/' + v.number + '/status', { status: st.value }).then(function () { load(); openIdea(v.number, true); }, fail); });
    acts.appendChild(st);
    var ct = el('select', 'inc-sel');
    ct.setAttribute('aria-label', 'Category of ' + v.code);
    facts('categories').forEach(function (c) { ct.appendChild(new Option(c.name, c.id, false, c.id === v.category)); });
    ct.addEventListener('change', function () { call('/' + v.number, { category: ct.value }).then(function () { load(); openIdea(v.number, true); }, fail); });
    acts.appendChild(ct);
    if (v.status !== 'merged') {
      var mg = button('ctl small', 'Merge into…');
      mg.addEventListener('click', function () {
        var into = (window.prompt('Merge ' + v.code + ' into which idea? Its number, such as INC-12', '') || '').trim();
        if (!into) { return; }
        call('/' + v.number + '/merge', { into: into.replace(/^INC-/i, '') }).then(function () { load(); openIdea(v.number, true); }, fail);
      });
      acts.appendChild(mg);
    }
    var ask = button('ctl small', 'Ask about it', 'Open the Incubator’s chat about this idea');
    ask.addEventListener('click', function () { openChat(v.code + ' '); });
    acts.appendChild(ask);
    p.appendChild(acts);
    p.appendChild(drawScorePanel(v));
    if (v.built_as) { p.appendChild(el('p', 'inc-p-meta', 'Became: ' + v.built_as)); }
    if (v.request_id) { p.appendChild(el('p', 'inc-p-meta', 'Feature request ' + v.request_id + ' in Gene therapy.')); }
    // Notes, the only words of it that can be changed.
    var nd = el('details', 'inc-notes');
    nd.open = !!v.notes;
    nd.appendChild(el('summary', '', v.notes ? 'Notes' : 'Add a note'));
    var ta = el('textarea', 'inc-notes-ta');
    ta.value = v.notes || '';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'Notes on ' + v.code);
    var sv = button('ctl small', 'Save the note');
    sv.addEventListener('click', function () { call('/' + v.number, { notes: ta.value }).then(function () { load(); openIdea(v.number, true); }, fail); });
    nd.appendChild(ta);
    nd.appendChild(sv);
    p.appendChild(nd);
    // A page, read in place.
    if (S.reading) {
      var rd = el('div', 'inc-reader');
      var rh = el('div', 'inc-reader-h');
      rh.appendChild(el('b', '', S.readingName || 'Page'));
      var ro = el('a', 'inc-a', 'Open on its own');
      ro.href = S.reading; ro.target = '_blank'; ro.rel = 'noopener';
      rh.appendChild(ro);
      var rc = button('inc-a', 'Close');
      rc.addEventListener('click', function () { S.reading = ''; draw(); });
      rh.appendChild(rc);
      rd.appendChild(rh);
      var fr = el('iframe', 'inc-frame');
      fr.src = S.reading;
      fr.title = S.readingName || 'Page';
      fr.setAttribute('sandbox', 'allow-same-origin allow-scripts allow-popups');
      rd.appendChild(fr);
      p.appendChild(rd);
    }
    // Links, by kind.
    var groups = [['task', 'Task'], ['step', 'Step'], ['chat', 'Chat'], ['page', 'Pages'], ['request', 'Feature request'],
                  ['gene', 'Gene'], ['idea', 'Ideas'], ['file', 'Files'], ['link', 'Links']];
    groups.forEach(function (g) {
      var mine = (v.links || []).filter(function (l) { return l.kind === g[0]; });
      if (!mine.length) { return; }
      var box = el('div', 'inc-links');
      box.appendChild(el('span', 'inc-links-h', g[1] + (mine.length > 1 ? ' · ' + mine.length : '')));
      var list = el('ul', 'inc-links-l' + (mine.length > 8 ? ' long' : ''));
      mine.forEach(function (l) {
        var li = el('li');
        if (g[0] === 'page') {
          var rb = button('inc-a', l.label, 'Read it here');
          rb.addEventListener('click', function () { S.reading = l.href; S.readingName = l.label; draw(); });
          li.appendChild(rb);
        } else if (g[0] === 'idea' && /^#INC-\d+$/.test(l.href || '')) {
          var ib = button('inc-a', l.label);
          ib.addEventListener('click', function () { openIdea(Number(l.href.replace('#INC-', ''))); });
          li.appendChild(ib);
        } else if (l.href) {
          var a = el('a', 'inc-a', l.label);
          a.href = l.href;
          if (/^\/(task|gene-therapy|evolution|\?)/.test(l.href) || l.href.indexOf('?chat=') >= 0) {
            a.addEventListener('click', function (e) { if (e.metaKey || e.ctrlKey) { return; } e.preventDefault(); go(l.href); });
          } else { a.target = '_blank'; a.rel = 'noopener'; }
          li.appendChild(a);
        } else { li.textContent = l.label; }
        list.appendChild(li);
      });
      box.appendChild(list);
      p.appendChild(box);
    });
    if ((v.merged_here || []).length) {
      var mh = el('div', 'inc-links');
      mh.appendChild(el('span', 'inc-links-h', 'Merged into this one'));
      var ml = el('ul', 'inc-links-l');
      v.merged_here.forEach(function (m) {
        var li = el('li');
        var b = button('inc-a', m.code + ': ' + m.title + ' (' + m.source_name + (m.ref ? ' ' + m.ref : '') + ')');
        b.addEventListener('click', function () { openIdea(Number(m.code.replace(/^INC-/, ''))); });
        li.appendChild(b);
        ml.appendChild(li);
      });
      mh.appendChild(ml);
      p.appendChild(mh);
    }
    // The original words, exactly as written, in sections.
    var secs = (v.sections || []).length ? v.sections : [{ title: 'The idea', text: v.original || '' }];
    p.appendChild(el('h5', 'inc-p-h', 'As it was written' + (secs.length > 1 ? ' · ' + secs.length + ' parts' : '')));
    secs.forEach(function (s, i) {
      var d = el('details', 'inc-sec');
      d.open = i === 0 || secs.length <= 2;
      var sm = el('summary', '');
      sm.appendChild(el('span', '', s.title || 'Part ' + (i + 1)));
      sm.appendChild(el('span', 'inc-n', Math.max(1, Math.round((s.text || '').length / 6)).toLocaleString() + ' words'));
      d.appendChild(sm);
      var body = el('div', 'inc-text');
      var md = S.host && S.host.markdown;
      if (md && (s.text || '').length < 200000) {
        try { var html = md(s.text || ''); if (typeof html === 'string') { body.innerHTML = html; } else if (html && html.nodeType) { body.appendChild(html); } else { body.textContent = s.text || ''; } }
        catch (e) { body.textContent = s.text || ''; }
      } else { body.textContent = s.text || ''; }
      var raw = button('inc-a inc-raw', 'Show the exact characters');
      raw.addEventListener('click', function () {
        var pre = el('pre', 'inc-pre', s.text || '');
        body.replaceWith(pre);
        raw.remove();
      });
      d.appendChild(raw);
      d.appendChild(body);
      p.appendChild(d);
    });
    // Its history.
    var hd = el('details', 'inc-sec');
    hd.appendChild(el('summary', '', 'History · ' + (v.history || []).length));
    var hl = el('ol', 'inc-hist');
    (v.history || []).slice().reverse().forEach(function (h) {
      var li = el('li');
      li.appendChild(el('span', 'inc-n', when(h.at)));
      li.appendChild(el('span', '', ' ' + h.what + (h.after && h.after.status ? ': ' + nameOf('statuses', h.after.status) : '') +
        (h.after && h.after.category && !h.after.status ? ': ' + nameOf('categories', h.after.category) : '') + (h.by ? ', by ' + h.by : '') + (h.note ? '. ' + h.note : '')));
      hl.appendChild(li);
    });
    hd.appendChild(hl);
    p.appendChild(hd);
    return p;
  }

  /* The score in the panel: the stars, every part with its menu, its reason and whose it is, the formula
     with the numbers, how often it came back, and Score again. */
  function drawScorePanel(v) {
    var box = el('section', 'inc-p-score');
    box.setAttribute('aria-label', 'Score of ' + v.code);
    var top = el('div', 'inc-p-score-h');
    top.appendChild(el('b', '', 'Score'));
    top.appendChild(scoreChip(v));
    top.appendChild(starsEl(v, true));
    top.appendChild(el('span', 'inc-n', v.stars_mine ? 'your stars; Rouh suggests ' + (v.stars_suggested || '–') :
      v.stars_suggested ? 'Rouh’s suggested stars' : ''));
    var again = button('inc-a', 'Score again', 'Rouh scores it again now; what you set stays');
    again.addEventListener('click', function () {
      again.disabled = true; again.textContent = 'Scoring…';
      call('/' + v.number + '/score', { rescore: true }).then(function (j) {
        var row = (S.data.ideas || []).filter(function (x) { return x.number === v.number; })[0];
        if (row) { row.parts = j.idea.parts; row.stars_suggested = j.idea.stars_suggested; row.stars_mine = j.idea.stars_mine; row.stars_why = j.idea.stars_why; recalc(row); }
        S.idea = j.idea; recalc(S.idea); S.hold = true;
        if (row) { repaint(row); } else { draw(); }
      }, fail);
    });
    top.appendChild(again);
    box.appendChild(top);
    if (v.score == null && !v.scored_at) {
      box.appendChild(el('p', 'inc-p-meta', 'Not scored yet: Rouh scores it in the background, a moment after it is added.'));
      return box;
    }
    var t = el('table', 'inc-bd inc-bd-panel');
    PARTS.forEach(function (key) {
      var p = (v.parts || {})[key] || {}, mine = p.mine != null, tr = el('tr');
      tr.appendChild(el('th', '', (partFacts(key) || {}).name));
      var td = el('td');
      var sel = el('select', 'inc-sel' + (mine ? ' mine' : ''));
      sel.setAttribute('aria-label', (partFacts(key) || {}).name + ' of ' + v.code);
      sel.appendChild(new Option('Rouh’s: ' + shownPart(key, p.rouh), '', false, !mine));
      var choices = partChoices(key);
      if (mine && choices.indexOf(p.mine) < 0) { choices.push(p.mine); }
      choices.forEach(function (x) { sel.appendChild(new Option(shownPart(key, x), String(x), false, mine && x === p.mine)); });
      sel.addEventListener('keydown', function (e) { e.stopPropagation(); });
      sel.addEventListener('change', function () {
        var row = (S.data.ideas || []).filter(function (x) { return x.number === v.number; })[0];
        if (row) { setPart(row, key, sel.value === '' ? null : Number(sel.value)); }
      });
      td.appendChild(sel);
      tr.appendChild(td);
      var who = el('td', 'inc-bd-who' + (mine ? ' mine' : ''), mine ? (p.by && p.by !== 'you' ? 'set by ' + p.by : 'yours') : 'Rouh’s');
      tr.appendChild(who);
      tr.appendChild(el('td', 'inc-bd-why', (mine ? 'Rouh said ' + shownPart(key, p.rouh) + '. ' : '') + (p.why || '')));
      t.appendChild(tr);
    });
    var srow = el('tr');
    srow.appendChild(el('th', '', 'Stars'));
    srow.appendChild(el('td', 'inc-bd-v', v.stars ? v.stars + ' · ×' + STAR_FACTOR[v.stars] : '–'));
    srow.appendChild(el('td', 'inc-bd-who' + (v.stars_mine ? ' mine' : ''), v.stars_mine ? 'yours' : 'Rouh’s'));
    srow.appendChild(el('td', 'inc-bd-why', (v.stars_mine ? 'Rouh suggests ' + (v.stars_suggested || '–') + '. ' : '') + (v.stars_why || '')));
    t.appendChild(srow);
    box.appendChild(t);
    box.appendChild(el('div', 'inc-formula', ((S.data.facts.score || {}).formula || '') + '\n' + numbersOfScore(v)));
    var cb = v.came_back || {};
    var bits = [];
    if (cb.merged) { bits.push(cb.merged + ' merged into it'); }
    if (cb.sources) { bits.push(cb.sources + ' other ' + (cb.sources > 1 ? 'sources' : 'source')); }
    if (cb.chats) { bits.push(cb.chats + (cb.chats > 1 ? ' chats' : ' chat')); }
    if (cb.proposed) { bits.push('proposed again ' + cb.proposed + (cb.proposed > 1 ? ' times' : ' time')); }
    box.appendChild(el('p', 'inc-p-meta', (bits.length ? 'It came back: ' + bits.join(', ') + '. ' : '') +
      (v.scored_at ? 'Scored by Rouh ' + when(v.scored_at) + (v.scored_model ? ', with ' + v.scored_model : '') + '.' : '')));
    return box;
  }

  /* ---- adding, and the chat ---- */

  function newIdea() {
    var title = (window.prompt('The idea, in a few words', '') || '').trim();
    if (!title) { return; }
    var text = (window.prompt('Say it whole, as you would say it (or leave it as the title)', title) || title);
    call('/new', { title: title, text: text }).then(function (j) { S.said = 'Added ' + j.idea.code + '.'; load(); openIdea(j.idea.number); }, fail);
  }
  function openChat(words) {
    call('/chat', {}).then(function (j) {
      var addr = '/evolution/incubator' + (S.open ? '/INC-' + S.open : '') + '?chat=' + encodeURIComponent(j.chat);
      go(addr);
      /* An empty chat, opened, folds the canvas away, and this layer is on the canvas: once the conversation
         has switched, both are asked for side by side. */
      [400, 1000, 2200].forEach(function (ms) {
        setTimeout(function () {
          var app = document.getElementById('app');
          if (app && app.classList.contains('no-canvas') && S.host && S.host.beside) { S.host.beside(); }
        }, ms);
      });
      if (typeof words === 'string' && words) {
        setTimeout(function () {
          var box = /** @type {HTMLTextAreaElement|null} */ ($('input'));
          if (box) { box.value = words; box.dispatchEvent(new Event('input', { bubbles: true })); box.focus(); }
        }, 400);
      }
    }, fail);
  }

  document.addEventListener('click', function () { if (S.menu) { S.menu = ''; draw(); } });
  /* Escape closes the innermost thing open: a menu, then the idea's panel, and only then the layer. Taken
     before the layer's own Escape, which would close the whole Incubator. */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !S.root || !S.root.isConnected || S.root.closest('[hidden]')) { return; }
    if (S.menu) { S.menu = ''; draw(); }
    else if (S.open) { closeIdea(); }
    else { return; }
    e.stopPropagation();
    e.preventDefault();
  }, true);

  /* The keys of the list: 1, 2 and 3 set the selected row's stars and 0 clears them, the arrows and j and k
     move the selection, Enter opens it and R puts the list in order. Never while something is being typed,
     in a field or in the chat, and never with Ctrl, Alt or Cmd held. */
  document.addEventListener('keydown', function (e) {
    if (!S.root || !S.root.isConnected || S.root.closest('[hidden]') || !S.data || e.defaultPrevented) { return; }
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    var t = /** @type {Element} */ (e.target);
    if (t && t.closest && t.closest('input, textarea, select, button, a[href], [contenteditable=""], [contenteditable="true"], dialog')) {
      if (!(t.closest('.inc-stars') && /^[0-3]$/.test(e.key))) { return; }
    }
    var k = e.key, v = selectedIdea();
    if (/^[0-3]$/.test(k)) {
      if (!v) { return; }
      var n = Number(k);
      if ((v.stars_mine || 0) !== n) { setStars(v, n || null); }
    } else if (k === 'ArrowDown' || k === 'j') { stepSelection(1); }
    else if (k === 'ArrowUp' || k === 'k') { stepSelection(-1); }
    else if (k === 'Enter') { if (!v || (t && t.closest && t.closest('tr[data-n]'))) { return; } openIdea(v.number); }
    else if (k === 'r' || k === 'R') { resort(); }
    else { return; }
    e.preventDefault();
  });

  window.RouhIncubator = {
    /* Drawn into `wrap` by Evolution's layer, at `sub`: '' for the list, 'INC-<n>' for one idea. */
    mount: function (wrap, sub, host) {
      S.host = host || null;
      S.root = el('div', 'inc');
      wrap.appendChild(S.root);
      var n = /^INC-(\d+)$/i.exec(sub || '');
      var want = n ? Number(n[1]) : 0;
      if (want !== S.open) { S.open = want; S.idea = null; if (want) { openIdea(want, true); } }
      draw();
      if (!S.data || !S.fresh) { S.fresh = true; load(); }
    },
    hidden: function () { S.fresh = false; hideTip(); },
    heard: function () { if (S.root && S.root.isConnected) { load(); if (S.open) { openIdea(S.open, true); } } }
  };
}());
