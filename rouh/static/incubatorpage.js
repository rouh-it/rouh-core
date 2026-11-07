/* The Incubator (`rouh/incubator.py`, `rouh/web/incubator.py`): one list of ideas for Rouh's new genes
   and mutations, drawn inside Evolution's layer at `/evolution/incubator`, and one idea's own page at
   `/evolution/incubator/INC-<n>`.

   Redesigned on 7 November 2026 around what Petar does here, in his words: "Make decisions, pick out what
   is valuable, connect things that look the same, quickly grasp what was meant and it's vision as well as
   give my feedback, or chat about the future thing." (task 166, step 166-05; the design standard of task
   169, full tier, one direction; its journeys, structure and states are in that step's `designs/`).

   - Decide: every row has Take (Go: Gene therapy builds it), Park, Drop and Merge, and the keys T, P, D and
     M on the selected row; the row changes at once, a toast says what was done with Undo (and Z), and the
     row stays where it is, dimmed, until the list is put in order again (R). Take waits a few seconds
     before it hands the idea on, so Undo never has to take back a feature request.
   - Pick what is valuable: the score as a bar ranked among the rest, the stars (one press, or 1, 2, 3, 0),
     the size and how often the idea came back, all on the row; grouped by value (Build first, Worth a look,
     Low, Not scored yet), by category or by status; sorted by the score or any part; and "Impact against
     size", a small grid of the ideas in view whose cells filter the list.
   - Connect lookalikes: "Looks like INC-n" on a row, the Lookalikes view, and Compare, a drawer with the two
     side by side and Merge either way, Link, or Not the same (kept, so the pair is not offered again).
   - Grasp it: under the title, "In a line" (`rouh/incubator_gist.py`, written once and kept); "At a
     glance" (the problem, who it helps, what it looks like in use, its vision, where it came from and its
     lookalikes) on hover, Space or the chevron: only what the row does not already show. This replaced the
     old preview, which repeated the row. The score's own breakdown is still on its hover.
   - Feedback and chat: the idea's page leads with its vision and its line, then the decisions, then depth,
     then a place for feedback (kept in its history and notes) and its own chat, kept with it.

   Kept as they were (Petar: "I like the filter mechanics"): status, category, kind and source as the task
   browser's labels (`labels.js`, `labels.css`), a press on a label shows only its ideas, the eye in front
   hides the ideas that carry it, the count is inside it; and everything set on the page is the person's
   own setting on the server (`/api/incubator/prefs`), the same on every device. Every idea and every change
   is the server's; nothing is kept in this browser. `window.RouhIncubator` is what `evolutionpage.js`
   mounts. Decisions here are the person's own presses, sent as them: none is a question in Rouh's list of
   decisions. */
(function () {
  'use strict';

  var API = '/api/incubator';
  var PARTS = ['impact', 'confidence', 'frequency', 'pain', 'clarity', 'risk'];
  var STAR_FACTOR = { 1: 1, 2: 1.5, 3: 2 };
  /* The page's settings are read as of this version: 3 is the redesign, which opens on To decide once. */
  var PREFS_V = 3;
  var SORTS = [['score', 'Score'], ['impact', 'Impact'], ['stars', 'Stars'], ['frequency', 'Frequency'],
               ['pain', 'Pain'], ['confidence', 'Confidence'], ['clarity', 'Clarity'], ['risk', 'Risk'],
               ['size', 'Size, smallest first'], ['asked', 'How often it came back'], ['code', 'Number'],
               ['created_at', 'Newest']];
  var HIGH = { score: 1, impact: 1, stars: 1, frequency: 1, pain: 1, confidence: 1, clarity: 1, risk: 1, asked: 1, created_at: 1 };
  var GROUPS = [['value', 'Value'], ['category', 'Category'], ['status', 'Status'], ['none', 'Nothing']];
  /* The views every Incubator has; the person's own come after them. `alike` is not a label filter. */
  var VIEWS = [
    { id: 'decide', name: 'To decide', f: { status: ['new', 'triaged'] } },
    { id: 'alike', name: 'Lookalikes', f: {}, alike: true },
    { id: 'go', name: 'Go and in build', f: { status: ['go', 'in_build'] } },
    { id: 'open', name: 'Still open', f: { status: ['new', 'triaged', 'parked'] } },
    { id: 'nightly', name: 'From nightly', f: { source: ['nightly'] } },
    { id: 'all', name: 'All', f: {} }
  ];
  var FILTERS = [['status', 'Status'], ['category', 'Category'], ['kind', 'Kind'], ['source', 'Source']];
  var FACTS = { status: 'statuses', category: 'categories', kind: 'kinds', source: 'sources' };
  var TONE_VAR = { blue: '--cat-blue', amber: '--cat-amber', teal: '--cat-teal', rose: '--cat-rose', violet: '--cat-violet',
                   green: '--cat-green', slate: '--cat-slate', none: '--dim', accent: '--accent', user: '--user' };
  var STATUS_TONE = { new: 'blue', triaged: 'violet', go: 'amber', in_build: 'amber', built: 'green',
                      parked: 'slate', rejected: 'rose', merged: 'none' };
  var CAT_TONE = { ux: 'blue', communication: 'teal', memory: 'violet', autonomy: 'amber', integrations: 'green',
                   security: 'rose', stability: 'slate', speed: 'accent', cost: 'user', platform: 'none' };
  var SIZE_NAME = { small: 'Small', medium: 'Medium', large: 'Large' };
  var SIZE_LINE = { small: 'a day or less to build', medium: 'a few days to build', large: 'a week or more to build' };
  var SIZE_ORDER = { small: 1, medium: 2, large: 3 };
  /* The decisions on a row: what they set, their key, and what the toast says. Take is Go. */
  var DECIDE = [
    { id: 'take', name: 'Take', key: 't', status: 'go', said: 'goes to Gene therapy to be built', line: 'Build it: hand it to Gene therapy' },
    { id: 'park', name: 'Park', key: 'p', status: 'parked', said: 'parked', line: 'Not now: keep it for later' },
    { id: 'drop', name: 'Drop', key: 'd', status: 'rejected', said: 'dropped', line: 'Not to be built: it is set to Rejected' },
    { id: 'merge', name: 'Merge', key: 'm', status: 'merged', said: 'merged', line: 'The same as another idea: compare and merge' }
  ];
  /* How long Take waits before it hands the idea on, so Undo never has to take back a request. */
  var TAKE_WAIT = 6000;

  var S = { root: null, data: null, error: '', loading: false, seq: 0, host: null,
            q: '', f: {}, hide: {}, view: 'decide', sort: { key: 'score', dir: -1 }, group: 'value',
            views: [], apart: [], cell: '', filtersOpen: null, legend: true, saveT: 0,
            picked: {}, open: 0, idea: null, reading: '', menu: '', said: '',
            sel: 0, hold: false, rank: null, left: {}, mx: -1, my: -1, scale: [], bands: null,
            expanded: {}, toast: null, undo: null, pending: {}, compare: null, fb: '' };

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
    // The title is the hint on hover; a button with words is named by its words, and only one without
    // any (an icon, a star) by its title.
    if (title) { b.title = title; if (!text) { b.setAttribute('aria-label', title); } }
    return b;
  }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function call(path, body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) {
      init.method = 'POST';
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
      init.keepalive = true;
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
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  var SVG = {
    chev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    take: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    park: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6v12M15 6v12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    drop: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7L7 17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    merge: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5v4a5 5 0 005 5h0a5 5 0 015 5v0M17 5v4a5 5 0 01-5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  function icon(name) { var s = el('span', 'inc-ic'); s.innerHTML = SVG[name]; return s; }

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
  function when(t) { return t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''; }
  function day(t) { return t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function ideaByNumber(n) {
    var all = (S.data && S.data.ideas) || [];
    for (var i = 0; i < all.length; i++) { if (all[i].number === n) { return all[i]; } }
    return null;
  }
  function asked(v) { return (v.came_back && v.came_back.total) || 0; }
  function sizeOf(v) { return (v.gist && v.gist.size) || ''; }
  function isOpen(v) { return v.status === 'new' || v.status === 'triaged'; }

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
  function shownPart(key, x) {
    if (x == null) { return '–'; }
    var f = partFacts(key), word = f && f.words ? f.words[String(x)] : '';
    if (key === 'confidence') { return Math.round(x * 100) + '%'; }
    if (key === 'impact' || key === 'frequency') { return String(x) + (word ? ' · ' + word : ''); }
    if (key === 'pain') { return '×' + x + (word ? ' · ' + word : ''); }
    if (key === 'risk') { return '÷' + x; }
    return '×' + x;
  }
  function partChoices(key) {
    var f = partFacts(key);
    if (!f) { return []; }
    if (f.values) { return f.values.slice(); }
    var out = [];
    for (var x = f.min; x <= f.max + 1e-9; x += f.step) { out.push(Math.round(x * 100) / 100); }
    return out;
  }
  /* Where a score stands among every scored idea, 0 for the lowest to 1 for the highest. */
  function rankOf(score) {
    var sc = S.scale, n = sc.length;
    if (score == null || !n) { return null; }
    var lo = 0, hi = n;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (sc[mid] < score) { lo = mid + 1; } else { hi = mid; } }
    return n > 1 ? Math.min(1, lo / (n - 1)) : 1;
  }
  function numbersOfScore(v) {
    var g = {};
    for (var i = 0; i < PARTS.length; i++) { g[PARTS[i]] = partOf(v, PARTS[i]); if (g[PARTS[i]] == null) { return ''; } }
    if (!v.stars) { return ''; }
    return g.impact + '² × ' + g.confidence + ' × ' + g.frequency + ' × ' + g.pain + ' × ' + STAR_FACTOR[v.stars] +
      ' × ' + g.clarity + ' ÷ ' + g.risk + ' = ' + Math.round(v.score);
  }
  /* The value bands, from where a score stands among every scored idea that is not merged. */
  function bandOf(v) {
    if (v.score == null) { return 'none'; }
    var r = rankOf(v.score);
    return r >= 0.85 ? 'first' : r >= 0.5 ? 'look' : 'low';
  }
  var BANDS = [['first', 'Build first', 'scores in the top 15% of every idea'], ['look', 'Worth a look', 'scores in the next 35%'],
               ['low', 'Low', 'scores in the lower half'], ['none', 'Not scored yet', 'Rouh scores them in the background']];

  var STAR_PATH = 'M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 16.83l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9z';
  /* Three stars: Rouh's suggestion drawn as outlines, the person's own filled. A press sets the person's
     stars, and a press on the number they already have gives them back to Rouh's. */
  function starsEl(v, big) {
    var wrap = el('span', 'inc-stars' + (big ? ' big' : '') + (v.stars_mine ? ' mine' : ''));
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
  /* The score as a bar: its length and its warmth are where it stands among the rest, its number beside. */
  function scoreBar(v) {
    var r = rankOf(v.score);
    var box = el('span', 'inc-sbar' + (v.score == null ? ' none' : '') + (anyMine(v) ? ' mine' : ''));
    var track = el('span', 'inc-sbar-t');
    var fill = el('span', 'inc-sbar-f');
    if (r != null) {
      var most = S.scale.length ? S.scale[S.scale.length - 1] : 0;
      fill.style.width = Math.max(4, Math.round((most ? v.score / most : 1) * 100)) + '%';
      fill.style.setProperty('--o', String(Math.round((0.35 + 0.65 * r) * 100) / 100));
    }
    track.appendChild(fill);
    box.appendChild(track);
    box.appendChild(el('span', 'inc-sbar-n', v.score == null ? 'Not scored' : String(Math.round(v.score))));
    box.setAttribute('aria-label', v.score == null ? 'Not scored yet' :
      'Score ' + Math.round(v.score) + ' of the highest ' + Math.round(S.scale[S.scale.length - 1] || 0) + ', higher than ' + Math.round((r || 0) * 100) + '% of the ideas' + (anyMine(v) ? ', with your changes' : ''));
    box.addEventListener('mouseenter', function (e) { hoverCard(null); S.hx = e.clientX; S.hy = e.clientY; clearTimeout(S.tipT); S.tipT = setTimeout(function () { showBreakdown(v, box); }, 150); });
    box.addEventListener('mouseleave', hideTip);
    return box;
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
      toast(String((err && err.message) || err));
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
  /* A row drawn again where it is, and the idea's page if it is this idea's, without the list moving. */
  function repaint(v) {
    var li = S.root && S.root.querySelector('.inc-row[data-n="' + v.number + '"]');
    if (li) { li.replaceWith(row(v)); }
    if (S.idea && S.idea.number === v.number) {
      ['stars_mine', 'stars_suggested', 'stars', 'parts', 'score', 'status', 'status_name'].forEach(function (k) { S.idea[k] = v[k]; });
      draw();
    }
    paintNote();
  }
  function paintNote() {
    var n = S.root && S.root.querySelector('.inc-resort');
    if (n) { n.hidden = !S.hold; }
    // The order is held until R; the counts are not: the headline and the views follow at once.
    var hero = S.root && S.root.querySelector('.inc-hero');
    if (hero && S.data && !S.open) { hero.replaceWith(drawHead()); }
  }
  function resort() { S.hold = false; S.left = {}; draw(); }

  /* ---- loading ---- */

  function load() {
    var seq = ++S.seq;
    S.loading = !S.data;
    S.error = '';
    if (S.loading) { draw(); }
    return call('').then(function (j) {
      if (seq !== S.seq || !j) { return; }
      // A Take still waiting keeps its row as the person left it, until it is sent or undone.
      (j.ideas || []).forEach(function (v) { if (S.pending[v.number]) { v.status = 'go'; v.status_name = nameOf('statuses', 'go'); v._pending = true; } });
      S.data = j;
      S.loading = false;
      (j.ideas || []).forEach(recalc);
      S.scale = (j.ideas || []).filter(function (v) { return v.status !== 'merged'; }).map(function (v) { return v.score; })
        .filter(function (x) { return x != null; }).sort(function (a, b) { return a - b; });
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
    if (S.prefsRead) { return; }
    S.prefsRead = true;
    var old = (Number(p.v) || 1) < PREFS_V;
    S.views = Array.isArray(p.views) ? p.views.filter(function (v) { return v && v.id && v.name; }) : [];
    if (p.sort && typeof p.sort.key === 'string' && SORTS.some(function (s) { return s[0] === p.sort.key; })) {
      S.sort = { key: p.sort.key, dir: p.sort.dir === 1 ? 1 : -1 };
    }
    S.group = GROUPS.some(function (g) { return g[0] === p.group; }) ? p.group : 'value';
    S.legend = p.legend !== false;
    S.apart = Array.isArray(p.apart) ? p.apart.filter(function (x) { return /^\d+-\d+$/.test(x); }) : [];
    S.filtersOpen = p.filtersOpen && typeof p.filtersOpen === 'object' ? p.filtersOpen : null;
    S.f = cleanFilters(p.f);
    S.hide = cleanHide(p.hide);
    S.q = typeof p.q === 'string' ? p.q.slice(0, 200) : '';
    S.cell = typeof p.cell === 'string' && /^[1-5]-(small|medium|large)$/.test(p.cell) ? p.cell : '';
    S.view = typeof p.view === 'string' && (p.view === '' || allViews().some(function (v) { return v.id === p.view; })) ? p.view : 'decide';
    // Settings kept before the redesign: a list left on All with nothing chosen opens on To decide, once.
    if (old && (S.view === 'all' || !p.view) && !Object.keys(S.f).length && !Object.keys(S.hide).length && !S.q) {
      S.view = 'decide';
      S.f = JSON.parse(JSON.stringify(VIEWS[0].f));
    }
    if (old && Object.keys(p).length) { savePrefs(); }
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
  function savePrefs() {
    clearTimeout(S.saveT);
    S.saveT = setTimeout(function () {
      call('/prefs', { prefs: { v: PREFS_V, views: S.views, sort: S.sort, group: S.group, f: S.f, hide: S.hide, q: S.q,
                                view: S.view, legend: S.legend, apart: S.apart, cell: S.cell, filtersOpen: S.filtersOpen } }).catch(function () {});
    }, 500);
  }
  function changed() { S.hold = false; S.left = {}; savePrefs(); draw(); }

  /* ---- filtering, sorting, grouping ---- */

  function allViews() { return VIEWS.concat(S.views); }
  function viewOf(id) { var all = allViews(); for (var i = 0; i < all.length; i++) { if (all[i].id === id) { return all[i]; } } return null; }
  function matches(v, f, q) {
    for (var i = 0; i < FILTERS.length; i++) {
      var key = FILTERS[i][0], want = f[key];
      if (want && want.length && want.indexOf(v[key] || '') < 0) { return false; }
    }
    if (f.from && v.created_at < Date.parse(f.from) / 1000) { return false; }
    if (f.to && v.created_at > Date.parse(f.to) / 1000 + 86400) { return false; }
    if (q) {
      var g = v.gist || {};
      var hay = (v.code + ' ' + v.title + ' ' + v.ref + ' ' + v.gene + ' ' + (v.tags || []).join(' ') + ' ' +
                 v.notes + ' ' + v.preview + ' ' + (g.line || '') + ' ' + (g.problem || '')).toLowerCase();
      var words = q.toLowerCase().split(/\s+/);
      for (var j = 0; j < words.length; j++) { if (words[j] && hay.indexOf(words[j]) < 0) { return false; } }
    }
    return true;
  }
  function eyeHidden(v, hide, f, skip) {
    for (var i = 0; i < FILTERS.length; i++) {
      var key = FILTERS[i][0], id = v[key] || '';
      if (key === skip || !hide[key + ':' + id]) { continue; }
      if ((f[key] || []).indexOf(id) < 0) { return true; }
    }
    return false;
  }
  function cellOf(v) {
    var imp = partOf(v, 'impact'), sz = sizeOf(v);
    return imp && sz ? imp + '-' + sz : '';
  }
  /* Everything that decides whether an idea is in the list, but the impact-against-size cell: the view's
     lookalikes, the labels, the eyes and the search. */
  function inList(v, skipCell) {
    var vw = viewOf(S.view);
    if (vw && vw.alike && !(v.alike || []).length) { return false; }
    if (!matches(v, S.f, S.q) || eyeHidden(v, S.hide, S.f)) { return false; }
    if (!skipCell && S.cell && cellOf(v) !== S.cell) { return false; }
    return true;
  }
  function sortValue(v, key) {
    if (key === 'code') { return v.number; }
    if (key === 'score') { return v.score; }
    if (key === 'stars') { return v.stars; }
    if (key === 'asked') { return asked(v); }
    if (key === 'size') { return SIZE_ORDER[sizeOf(v)] || null; }
    if (PARTS.indexOf(key) >= 0) { return partOf(v, key); }
    return v[key] == null ? '' : v[key];
  }
  function shown() {
    var ideas = (S.data && S.data.ideas) || [];
    var out = ideas.filter(function (v) { return inList(v) || (S.hold && S.left[v.number]); });
    var key = S.sort.key, dir = S.sort.dir;
    function order(a, b) {
      var x = sortValue(a, key), y = sortValue(b, key);
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
  /* The rows in their groups: [{id, name, line, rows}], in the order the groups are read in. */
  function grouped(rows) {
    if (S.group === 'none') { return [{ id: 'all', name: '', line: '', rows: rows }]; }
    var order, name, line, keyOf;
    if (S.group === 'value') {
      order = BANDS.map(function (b) { return b[0]; });
      name = function (k) { return BANDS[order.indexOf(k)][1]; };
      line = function (k) { return BANDS[order.indexOf(k)][2]; };
      keyOf = function (v) { return v._band || bandOf(v); };
    } else {
      var kind = S.group === 'status' ? 'statuses' : 'categories';
      order = facts(kind).map(function (x) { return x.id; }).concat(['']);
      name = function (k) { return k ? nameOf(kind, k) : 'None'; };
      line = function (k) { return lineOf(kind, k); };
      keyOf = function (v) { return v[S.group] || ''; };
    }
    var by = {};
    rows.forEach(function (v) { var k = keyOf(v); (by[k] = by[k] || []).push(v); });
    return order.filter(function (k) { return by[k]; }).map(function (k) { return { id: k, name: name(k), line: line(k), rows: by[k] }; });
  }
  function countsFor(key) {
    var other = {};
    Object.keys(S.f).forEach(function (k) { if (k !== key) { other[k] = S.f[k]; } });
    var out = {};
    var vw = viewOf(S.view);
    ((S.data && S.data.ideas) || []).forEach(function (v) {
      if (vw && vw.alike && !(v.alike || []).length) { return; }
      if (matches(v, other, S.q) && !eyeHidden(v, S.hide, S.f, key) && (!S.cell || cellOf(v) === S.cell)) {
        out[v[key] || ''] = (out[v[key] || ''] || 0) + 1;
      }
    });
    return out;
  }
  function setFilter(key, values) {
    if (values && values.length) { S.f[key] = values; } else { delete S.f[key]; }
    S.view = '';
    changed();
  }
  function toggleEye(key) {
    if (S.hide[key]) { delete S.hide[key]; } else { S.hide[key] = true; }
    S.view = '';
    changed();
  }
  function clearAll() { S.f = {}; S.q = ''; S.hide = {}; S.cell = ''; S.view = 'all'; changed(); }
  function toggle(key, id) {
    var now = (S.f[key] || []).slice();
    var at = now.indexOf(id);
    if (at < 0) { now.push(id); } else { now.splice(at, 1); }
    setFilter(key, now);
  }
  function viewCount(v) {
    var vh = v.hide || S.hide;
    return ((S.data && S.data.ideas) || []).filter(function (i) {
      return (!v.alike || (i.alike || []).length) && matches(i, v.f, '') && !eyeHidden(i, vh, v.f);
    }).length;
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
    hideTip();
    hoverCard(null);
    var sc = scroller();
    var keep = sc ? sc.scrollTop : 0;
    root.textContent = '';
    root.classList.toggle('inc-on-idea', !!S.open);
    if (S.error) { root.appendChild(el('p', 'evo-error', S.error)); }
    if (S.loading) {
      var sk = el('div', 'inc-skeleton');
      sk.setAttribute('aria-busy', 'true');
      sk.appendChild(el('p', 'evo-loading', 'Reading the Incubator…'));
      for (var i = 0; i < 8; i++) { sk.appendChild(el('div', 'inc-skel-row')); }
      root.appendChild(sk);
      return;
    }
    if (!S.data) { return; }
    if (S.open) { root.appendChild(drawIdea()); }
    else { drawList(root); }
    // The drawer and the keys are put on the page's body: the Incubator is laid out by its own width (a
    // CSS container), which holds anything fixed inside it to its own box, under Rouh's columns.
    var over = $('incOverlay');
    if (!over) { over = el('div', 'inc-overlay'); over.id = 'incOverlay'; document.body.appendChild(over); }
    over.textContent = '';
    if (S.compare) { over.appendChild(drawCompare()); }
    if (S.menu === 'keys') { over.appendChild(drawKeys()); }
    if (sc && !S.scrollTop) { var now = scroller(); if (now) { now.scrollTop = keep; } }
    S.scrollTop = false;
  }
  /* What scrolls the page: Evolution's layer body. */
  function scroller() { return $('evolutionBody'); }

  function drawList(root) {
    var all = S.data.ideas;
    root.appendChild(drawHead());
    root.appendChild(drawTools());
    if (S.adding) { root.appendChild(drawNew()); }
    root.appendChild(drawFilters());
    root.appendChild(drawBulk());
    var rows = shown();
    if (!all.length) {
      var e = el('div', 'inc-empty');
      e.appendChild(el('b', '', 'No ideas yet.'));
      e.appendChild(el('p', '', 'An idea added here, or in the Incubator’s chat, waits in this list until it is built as a gene or a mutation.'));
      var add = button('ctl', 'Add an idea');
      add.addEventListener('click', newIdea);
      e.appendChild(add);
      root.appendChild(e);
      return;
    }
    if (!rows.length) {
      var none = el('div', 'inc-empty');
      var vw = viewOf(S.view);
      none.appendChild(el('b', '', vw && vw.id === 'decide' && !S.q && !S.cell ? 'Nothing waits for your decision.' : 'No idea matches.'));
      none.appendChild(el('p', '', vw && vw.id === 'decide' && !S.q && !S.cell ? 'Every new idea has been taken, parked, dropped or merged.' :
        'The view, the labels, the search or the grid leave no idea in the list.'));
      var clear = button('ctl', 'Show every idea');
      clear.addEventListener('click', clearAll);
      none.appendChild(clear);
      root.appendChild(none);
      return;
    }
    if (!S.sel || !rows.some(function (v) { return v.number === S.sel; })) { S.sel = rows[0].number; }
    var list = el('div', 'inc-list');
    list.setAttribute('role', 'list');
    list.setAttribute('aria-label', 'Ideas');
    grouped(rows).forEach(function (g) {
      if (g.name) {
        var h = el('h3', 'inc-group');
        h.appendChild(el('span', 'inc-group-name', g.name));
        h.appendChild(el('span', 'inc-group-n', String(g.rows.length)));
        if (g.line) { h.appendChild(el('span', 'inc-group-line', g.line)); }
        list.appendChild(h);
      }
      g.rows.forEach(function (v) { list.appendChild(row(v)); });
    });
    root.appendChild(list);
    root.appendChild(el('p', 'inc-foot', rows.length + ' of ' + all.length + ' ideas shown.'));
  }

  /* The headline: what waits for the person, in one sentence, and the grid of impact against size. */
  function drawHead() {
    var head = el('section', 'inc-hero');
    var all = S.data.ideas;
    var decide = all.filter(isOpen).length;
    var words = el('div', 'inc-hero-words');
    var top = el('div', 'inc-hero-top');
    var h = el('h2', 'inc-verdict');
    h.textContent = decide ? plural(decide, 'idea waits', 'ideas wait') + ' for your decision.' : 'Nothing waits for your decision.';
    top.appendChild(h);
    var acts = el('div', 'inc-hero-acts');
    var add = button('ctl inc-add', 'Add an idea');
    add.addEventListener('click', newIdea);
    acts.appendChild(add);
    var talk = button('ctl', 'Chat about the list', 'Open the Incubator’s own chat beside the list');
    talk.addEventListener('click', function () { openChat(''); });
    acts.appendChild(talk);
    var keys = button('ctl inc-keysb', '?', 'The keys of the list (?)');
    keys.addEventListener('click', function (e) { e.stopPropagation(); S.menu = S.menu === 'keys' ? '' : 'keys'; draw(); });
    acts.appendChild(keys);
    top.appendChild(acts);
    words.appendChild(top);
    // What Rouh is still writing in the background, on one line, each with a way to have it now.
    var gs = S.data.gists || {}, sc = S.data.scoring || {};
    var notes = el('p', 'inc-hero-note');
    if (gs.all && gs.written < gs.all) {
      var gw = el('span', '');
      gw.appendChild(document.createTextNode(gs.running ? 'Writing summaries: ' + gs.written + ' of ' + gs.all + '. ' :
        plural(gs.all - gs.written, 'idea') + ' not summed up yet. '));
      if (!gs.running) {
        var gb = button('inc-link', 'Sum them up now', 'Rouh writes every missing summary now, in the background, those to decide first');
        gb.addEventListener('click', function () {
          gb.disabled = true;
          call('/gists', {}).then(function (j) { S.data.gists = j.gists; draw(); }, fail);
        });
        gw.appendChild(gb);
      }
      notes.appendChild(gw);
    }
    if (sc.running || (sc.all && sc.scored < sc.all)) {
      var sw = el('span', '');
      sw.appendChild(document.createTextNode(sc.running ? 'Scoring: ' + (sc.done || 0) + ' of ' + sc.total + '. ' :
        plural(sc.all - sc.scored, 'idea') + ' not scored yet. '));
      if (!sc.running) {
        var sb = button('inc-link', 'Score them now', 'Rouh scores them now, in the background');
        sb.addEventListener('click', function () {
          sb.disabled = true;
          call('/scoring', {}).then(function (j) { S.data.scoring = j.scoring; draw(); }, fail);
        });
        sw.appendChild(sb);
      }
      notes.appendChild(sw);
    }
    if (notes.childNodes.length) { words.appendChild(notes); }
    var views = drawViews();
    words.appendChild(views);
    head.appendChild(words);
    // Beside the conversation the grid folds into the end of the views' line; wider, it stands at the right.
    if (S.root && S.root.clientWidth < 1000 && S.root.clientWidth >= 640) { var gr = drawGrid(); gr.classList.add('inline'); views.appendChild(gr); }
    else { head.appendChild(drawGrid()); }
    return head;
  }

  /* Impact against size: the ideas in the list as it is (but this grid's own cell), counted by their
     impact (1 to 5, up) and their size (small to large, across). A press on a cell shows only its ideas. */
  function drawGrid() {
    // A details, open on a desk and folded on a phone, where it would push the ideas down a screen.
    var box = el('details', 'inc-grid');
    box.open = !!S.cell || !(S.root && S.root.clientWidth < 1000);
    var cap = el('summary', 'inc-grid-cap');
    cap.appendChild(el('b', '', 'Impact against size'));
    cap.appendChild(el('span', '', S.cell ? 'one cell chosen' : 'press a cell'));
    box.appendChild(cap);
    var counts = {}, most = 0;
    S.data.ideas.forEach(function (v) {
      if (!inList(v, true)) { return; }
      var c = cellOf(v);
      if (c) { counts[c] = (counts[c] || 0) + 1; most = Math.max(most, counts[c]); }
    });
    var t = el('div', 'inc-grid-t');
    t.setAttribute('role', 'group');
    t.setAttribute('aria-label', 'Impact against size: press a cell to see only its ideas');
    t.appendChild(el('span', 'inc-grid-ax inc-grid-y', 'Impact'));
    [5, 4, 3, 2, 1].forEach(function (imp) {
      t.appendChild(el('span', 'inc-grid-l', String(imp)));
      ['small', 'medium', 'large'].forEach(function (sz) {
        var k = imp + '-' + sz, n = counts[k] || 0;
        var b = button('inc-cell' + (S.cell === k ? ' on' : '') + (n ? '' : ' zero'), n ? String(n) : '');
        b.style.setProperty('--a', String(n && most ? 0.12 + 0.6 * n / most : 0));
        if (imp >= 4 && sz === 'small') { b.classList.add('win'); }
        var said = plural(n, 'idea') + ' of impact ' + imp + ' and ' + SIZE_NAME[sz].toLowerCase() + ' size' + (imp >= 4 && sz === 'small' ? ': quick wins' : '');
        b.title = S.cell === k ? said + '. Press again to show them all' : said;
        b.setAttribute('aria-label', said);
        b.setAttribute('aria-pressed', S.cell === k ? 'true' : 'false');
        b.addEventListener('click', function () { S.cell = S.cell === k ? '' : k; S.hold = false; S.left = {}; savePrefs(); draw(); });
        t.appendChild(b);
      });
    });
    t.appendChild(el('span', ''));
    ['Small', 'Medium', 'Large'].forEach(function (s) { t.appendChild(el('span', 'inc-grid-l inc-grid-x', s)); });
    box.appendChild(t);
    return box;
  }

  function drawViews() {
    var views = el('div', 'inc-views');
    views.setAttribute('role', 'tablist');
    views.setAttribute('aria-label', 'Views');
    allViews().forEach(function (v) {
      var b = button('inc-view' + (S.view === v.id ? ' on' : ''), '');
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', S.view === v.id ? 'true' : 'false');
      b.appendChild(el('span', '', v.name));
      b.appendChild(el('span', 'inc-n', viewCount(v)));
      b.addEventListener('click', function () {
        S.view = v.id;
        S.f = JSON.parse(JSON.stringify(v.f));
        S.hide = v.hide ? cleanHide(v.hide) : {};
        S.cell = '';
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
    return views;
  }

  function drawTools() {
    var tools = el('div', 'inc-tools');
    var sw = el('label', 'inc-searchwrap');
    sw.appendChild(el('span', 'inc-vh', 'Search the ideas'));
    var search = el('input', 'inc-search');
    search.type = 'search';
    search.placeholder = 'Search words or numbers ( / )';
    search.title = 'Search titles, lines, words and notes, or a number: INC-12, or its old name such as I-028 or 70-01';
    search.value = S.q;
    search.addEventListener('input', function () {
      S.q = search.value;
      clearTimeout(S.qT);
      S.qT = setTimeout(function () {
        changed();
        var s = S.root && S.root.querySelector('.inc-search');
        if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
      }, 180);
    });
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { var first = shown()[0]; if (first) { e.preventDefault(); openIdea(first.number); } }
      if (e.key === 'Escape' && search.value) { e.stopPropagation(); search.value = ''; S.q = ''; changed(); }
    });
    sw.appendChild(search);
    tools.appendChild(sw);
    var fs = filtersOpen(), names = filtersOn();
    var fb = button('ctl inc-filtersb' + (names.length ? ' on' : ''), '', 'The labels: status, category, kind and source, each with its eye');
    fb.setAttribute('aria-expanded', fs.open ? 'true' : 'false');
    fb.setAttribute('aria-controls', 'incFilters');
    fb.appendChild(el('span', 'inc-filtersb-ch'));
    fb.appendChild(el('span', '', 'Filters'));
    fb.appendChild(el('span', 'inc-n', names.length ? names.slice(0, 3).join(', ') + (names.length > 3 ? ' +' + (names.length - 3) : '') : 'none'));
    fb.addEventListener('click', function () { fs.fo[fs.k] = !fs.open; S.filtersOpen = fs.fo; savePrefs(); draw(); });
    tools.appendChild(fb);
    tools.appendChild(selectBox('Group by', GROUPS, S.group, function (val) { S.group = val; changed(); }));
    tools.appendChild(selectBox('Sort by', SORTS, S.sort.key, function (val) { S.sort = { key: val, dir: HIGH[val] ? -1 : 1 }; changed(); }));
    var note = button('inc-resort', 'Order changed · R to re-sort', 'Put the list in order again');
    note.hidden = !S.hold;
    note.addEventListener('click', resort);
    tools.appendChild(note);
    return tools;
  }
  function selectBox(label, list, value, on) {
    var w = el('label', 'inc-selbox');
    w.appendChild(el('span', '', label));
    var s = el('select', 'inc-sel');
    list.forEach(function (o) { s.appendChild(new Option(o[1], o[0], false, o[0] === value)); });
    s.addEventListener('change', function () { on(s.value); });
    w.appendChild(s);
    return w;
  }

  /* The labels, a line for each group, drawn as the task browser draws its own (`labels.js`): the eye in
     front, then the label with its count inside it. Folded on a phone, with how many filters are on. */
  /* How many filters are on, and their names, for the Filters button. */
  function filtersOn() {
    var names = [];
    FILTERS.forEach(function (pair) { (S.f[pair[0]] || []).forEach(function (id) { names.push(nameOf(FACTS[pair[0]], id)); }); });
    Object.keys(S.hide).forEach(function (k) { var at = k.indexOf(':'); names.push('not ' + nameOf(FACTS[k.slice(0, at)], k.slice(at + 1))); });
    if (S.f.from || S.f.to) { names.push('dates'); }
    if (S.cell) { names.push('one cell'); }
    return names;
  }
  function filtersOpen() {
    var fo = S.filtersOpen && typeof S.filtersOpen === 'object' ? S.filtersOpen : {};
    var k = S.root && S.root.clientWidth < 640 ? 'phone' : 'desk';
    return { fo: fo, k: k, open: fo[k] === true };
  }
  function drawFilters() {
    var st = filtersOpen();
    var box = el('div', 'inc-filterbox');
    box.id = 'incFilters';
    box.hidden = !st.open;
    if (!st.open) { return box; }
    var labs = el('div', 'inc-labels');
    var html = '';
    FILTERS.forEach(function (pair) {
      var key = pair[0], n = countsFor(key), chosen = S.f[key] || [];
      html += '<div class="inc-line" role="group" aria-label="' + pair[1] + '"><span class="inc-line-name">' + pair[1] + '</span>';
      facts(FACTS[key]).forEach(function (item) {
        var lk = key + ':' + item.id, isOn = chosen.indexOf(item.id) >= 0, count = n[item.id] || 0;
        var tone = key === 'status' ? STATUS_TONE[item.id] : key === 'category' ? CAT_TONE[item.id] : 'accent';
        var style = '--cc:var(' + (TONE_VAR[tone] || '--accent') + ')';
        var tip = (isOn ? 'Showing only ' : 'Only ') + item.name + (item.line ? ': ' + item.line : '') + (isOn ? '. Press again to show the rest' : '');
        var btn = '<button type="button" class="rl-chip inc-lab' + (isOn ? ' on' : '') + (count ? '' : ' zero') +
          '" data-group="' + key + '" data-id="' + esc(item.id) + '" aria-pressed="' + isOn + '" title="' + esc(tip) + '">' +
          (key === 'status' || key === 'category' ? '<i class="rl-dot"></i>' : '') +
          '<span class="lbl">' + esc(item.name) + '</span> <span class="c">' + count + '</span></button>';
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
    box.appendChild(labs);
    var line = el('div', 'inc-active');
    var on = filtersOn().length;
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
    var hid = S.data.ideas.filter(function (v) { return matches(v, S.f, S.q) && eyeHidden(v, S.hide, S.f); }).length;
    if (hid) { line.appendChild(el('span', 'inc-count', plural(hid, 'idea') + ' hidden by a crossed eye')); }
    if (S.cell) {
      var p = S.cell.split('-');
      var cc = button('inc-filter on', 'Impact ' + p[0] + ', ' + SIZE_NAME[p[1]].toLowerCase() + ' ×', 'Show every cell of the grid again');
      cc.addEventListener('click', function () { S.cell = ''; changed(); });
      line.appendChild(cc);
    }
    if (on || S.q || S.view !== 'all') {
      var clear = button('inc-link', 'Show every idea', 'Take off every filter, the search and every crossed eye');
      clear.addEventListener('click', clearAll);
      line.appendChild(clear);
    }
    box.appendChild(line);
    return box;
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
      toast(j.done.length + ' changed' + (j.failed.length ? '; ' + j.failed.length + ' not: ' + j.failed.map(function (f) { return f.id + ' (' + f.why + ')'; }).join(', ') : '.'));
      S.picked = {};
      load();
    }, fail);
  }
  function fail(err) { toast(String((err && err.message) || err)); }

  /* ---- one row ---- */

  function row(v) {
    var g = v.gist || {};
    var decided = S.left[v.number];
    var li = el('div', 'inc-row' + (S.picked[v.id] ? ' picked' : '') + (v.status === 'merged' ? ' merged' : '') +
      (S.sel === v.number ? ' sel' : '') + (decided ? ' decided' : '') + (S.expanded[v.number] ? ' expanded' : ''));
    li.setAttribute('role', 'listitem');
    li.setAttribute('data-n', String(v.number));
    var pick = el('label', 'inc-pick');
    var box = el('input');
    box.type = 'checkbox';
    box.checked = !!S.picked[v.id];
    box.setAttribute('aria-label', 'Choose ' + v.code);
    box.addEventListener('change', function () { S.picked[v.id] = box.checked; draw(); });
    pick.appendChild(box);
    li.appendChild(pick);
    var val = el('div', 'inc-val');
    val.appendChild(scoreBar(v));
    val.appendChild(starsEl(v));
    li.appendChild(val);
    var main = el('div', 'inc-main');
    var top = el('div', 'inc-top');
    var a = el('a', 'inc-title');
    a.href = '/evolution/incubator/' + v.code;
    a.appendChild(el('span', 'inc-code', v.code));
    a.appendChild(document.createTextNode(' ' + v.title));
    a.addEventListener('click', function (e) { if (e.metaKey || e.ctrlKey || e.shiftKey) { return; } e.preventDefault(); openIdea(v.number); });
    top.appendChild(a);
    main.appendChild(top);
    var line = el('p', 'inc-line1' + (g.line ? '' : ' wait'));
    line.textContent = g.line ? g.line : (v.merged_into ? 'Merged into ' + v.merged_into.code + '.' :
      'Rouh is writing its summary. Its first words: ' + (firstWords(v.preview) || 'none beyond its title.'));
    main.appendChild(line);
    var marks = el('div', 'inc-marks');
    marks.appendChild(statusChip(v));
    marks.appendChild(catChip(v));
    if (g.size) { marks.appendChild(chip('size', SIZE_NAME[g.size], SIZE_NAME[g.size] + ': ' + SIZE_LINE[g.size] + (g.size_why ? '. ' + g.size_why : ''))); }
    if (asked(v)) { marks.appendChild(chip('asked', 'came back ' + plural(asked(v), 'time'), 'How often this idea came back: merged into it, other sources, chats, proposed again')); }
    (v.alike || []).slice(0, 2).forEach(function (o) {
      var b = button('inc-alike', 'Looks like ' + o.code, 'Compare ' + v.code + ' with ' + o.code + ': ' + o.title);
      b.addEventListener('click', function (e) { e.stopPropagation(); openCompare(v.number, o.number); });
      marks.appendChild(b);
    });
    if (decided) { marks.appendChild(el('span', 'inc-decided', decided)); }
    var foot = el('div', 'inc-foot-row');
    foot.appendChild(marks);
    main.appendChild(foot);
    li.appendChild(main);
    var acts = el('div', 'inc-acts');
    acts.setAttribute('role', 'group');
    acts.setAttribute('aria-label', 'Decide ' + v.code);
    DECIDE.forEach(function (d) {
      var can = canDecide(v, d.id);
      var b = button('inc-act inc-act-' + d.id + (v.status === d.status ? ' now' : ''), '', d.name + ' ' + v.code + ': ' + d.line + ' (' + d.key.toUpperCase() + ')');
      b.appendChild(icon(d.id));
      b.appendChild(el('span', 'inc-act-w', d.name));
      b.disabled = !can;
      b.addEventListener('click', function (e) { e.stopPropagation(); select(v.number); decide(v, d.id); });
      acts.appendChild(b);
    });
    var more = button('inc-more' + (S.expanded[v.number] ? ' on' : ''), '', (S.expanded[v.number] ? 'Fold ' : 'At a glance: ') + v.code + ' (Space)');
    more.setAttribute('aria-expanded', S.expanded[v.number] ? 'true' : 'false');
    more.appendChild(icon('chev'));
    more.addEventListener('click', function (e) { e.stopPropagation(); toggleExpand(v.number); });
    acts.appendChild(more);
    foot.appendChild(acts);
    if (S.expanded[v.number]) { li.appendChild(glance(v, false)); }
    li.addEventListener('click', function (e) {
      var t = /** @type {Element} */ (e.target);
      if (t.closest && t.closest('button, a, input, select, label, .inc-glance')) { return; }
      openIdea(v.number);
    });
    li.addEventListener('mouseenter', function () { hoverSoon(v, li); });
    li.addEventListener('mousemove', function (e) {
      if (e.screenX === S.mx && e.screenY === S.my) { return; }
      S.mx = e.screenX; S.my = e.screenY;
      if (S.sel !== v.number) { select(v.number); }
    });
    li.addEventListener('mouseleave', function (e) {
      clearTimeout(S.cardT);
      var to = /** @type {Element} */ (e.relatedTarget);
      if (!(to && to.closest && to.closest('.inc-card'))) { S.cardT = setTimeout(function () { hoverCard(null); }, 160); }
    });
    return li;
  }
  function firstWords(t) {
    t = String(t || '').replace(/[#*_>`]+/g, ' ').replace(/\s+/g, ' ').trim();
    return t.length > 160 ? t.slice(0, 157).replace(/\s+\S*$/, '') + '…' : t;
  }
  function canDecide(v, what) {
    if (v.status === 'merged') { return false; }
    if (what === 'take') { return ['go', 'in_build', 'built'].indexOf(v.status) < 0; }
    if (what === 'park') { return ['parked', 'go', 'in_build', 'built'].indexOf(v.status) < 0 || !!v._pending; }
    if (what === 'drop') { return ['rejected', 'go', 'in_build', 'built'].indexOf(v.status) < 0 || !!v._pending; }
    return true;
  }

  /* ---- at a glance: only what the row does not already say ---- */

  function glance(v, floating) {
    var g = v.gist || {};
    var box = el('div', 'inc-glance' + (floating ? ' card' : ''));
    if (!floating) { box.id = 'incGlance-' + v.number; }
    if (g.vision) {
      var vis = el('p', 'inc-vision');
      vis.appendChild(el('span', 'inc-p-k', 'Vision'));
      vis.appendChild(document.createTextNode(g.vision));
      box.appendChild(vis);
    }
    var grid = el('dl', 'inc-glance-g');
    [['problem', 'The problem'], ['helps', 'Who it helps'], ['in_use', 'In use']].forEach(function (p) {
      if (!g[p[0]]) { return; }
      var d = el('div', 'inc-gi');
      d.appendChild(el('dt', '', p[1]));
      d.appendChild(el('dd', '', g[p[0]]));
      grid.appendChild(d);
    });
    var from = el('div', 'inc-gi');
    from.appendChild(el('dt', '', 'Came from'));
    from.appendChild(el('dd', '', originLine(v)));
    grid.appendChild(from);
    if (g.size) {
      var sz = el('div', 'inc-gi');
      sz.appendChild(el('dt', '', 'Size'));
      sz.appendChild(el('dd', '', SIZE_NAME[g.size] + ', ' + SIZE_LINE[g.size] + (g.size_why ? '. ' + g.size_why : '.')));
      grid.appendChild(sz);
    }
    box.appendChild(grid);
    if (!g.line) { box.appendChild(el('p', 'inc-glance-wait', 'Rouh has not summed this idea up yet: its problem, who it helps and its vision come once it has. Open it to read its own words.')); }
    if ((v.alike || []).length) {
      var al = el('div', 'inc-glance-alike');
      al.appendChild(el('span', 'inc-glance-h', 'Looks like'));
      v.alike.forEach(function (o) {
        var b = button('inc-alike', o.code + ' ' + o.title, 'Compare ' + v.code + ' with ' + o.code);
        b.addEventListener('click', function (e) { e.stopPropagation(); hoverCard(null); openCompare(v.number, o.number); });
        al.appendChild(b);
      });
      box.appendChild(al);
    }
    return box;
  }
  /* Where it came from, in words: its sources, its name there, and what it is linked to. */
  function originLine(v) {
    var bits = (v.sources || [v.source]).map(function (s) { return nameOf('sources', s); });
    var s = bits.join(' and ') + (v.ref ? ', as ' + (/^\d+$/.test(v.ref) ? 'task ' : /^\d+-\d+$/.test(v.ref) ? 'step ' : '') + v.ref : '');
    var kinds = {};
    (v.links || []).forEach(function (l) { kinds[l.kind] = (kinds[l.kind] || 0) + 1; });
    var named = { chat: 'chat', task: 'task', step: 'step', page: 'page', file: 'file', request: 'feature request', gene: 'gene', idea: 'linked idea' };
    var ls = Object.keys(kinds).filter(function (k) { return named[k]; }).map(function (k) { return plural(kinds[k], named[k]); });
    return s + (ls.length ? '; with ' + ls.join(', ') : '') + '. Added ' + day(v.created_at) + '.';
  }
  function toggleExpand(n) {
    if (S.expanded[n]) { delete S.expanded[n]; } else { S.expanded[n] = true; }
    hoverCard(null);
    var v = ideaByNumber(n);
    if (v) { repaint(v); }
  }

  /* The card on hover, on a desk: At a glance, under the row, after the pointer rests a moment. */
  var card = null;
  function hoverSoon(v, li) {
    clearTimeout(S.cardT);
    // Only with a mouse, and only where there is room beside the words: at a phone's width the row's arrow opens it.
    if (S.expanded[v.number] || !window.matchMedia('(hover: hover) and (pointer: fine)').matches || (S.root && S.root.clientWidth < 640)) { return; }
    S.cardT = setTimeout(function () { if (li.isConnected && li.matches(':hover')) { hoverCard(v, li); } }, 450);
  }
  function hoverCard(v, li) {
    if (!v) {
      clearTimeout(S.cardT);
      if (card) { card.remove(); card = null; }
      return;
    }
    if (card) { card.remove(); }
    card = el('div', 'inc-card');
    card.setAttribute('role', 'tooltip');
    card.appendChild(glance(v, true));
    card.addEventListener('mouseleave', function (e) {
      var to = /** @type {Element} */ (e.relatedTarget);
      if (!(to && to.closest && to.closest('.inc-row[data-n="' + v.number + '"]'))) { hoverCard(null); }
    });
    document.body.appendChild(card);
    var main = li.querySelector('.inc-main') || li;
    var r = main.getBoundingClientRect(), rr = li.getBoundingClientRect();
    var w = Math.min(560, window.innerWidth - 24);
    card.style.width = w + 'px';
    var x = Math.max(12, Math.min(window.innerWidth - w - 12, r.left));
    var below = window.innerHeight - rr.bottom - 12, above = rr.top - 12;
    var h = card.offsetHeight, y;
    if (h <= below || below >= above) { y = rr.bottom + 4; card.style.maxHeight = Math.max(120, below) + 'px'; }
    else { card.style.maxHeight = Math.max(120, above) + 'px'; h = card.offsetHeight; y = Math.max(8, rr.top - h - 4); }
    card.style.left = x + 'px';
    card.style.top = y + 'px';
  }

  /* The score taken apart on its hover: each part, its value, whose it is and why, and the formula. */
  var tip = null;
  function showBreakdown(v, anchor) {
    if (!tip) { tip = el('div', 'inc-tip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    tip.textContent = '';
    var h = el('div', 'inc-tip-h');
    h.appendChild(el('b', '', v.code + ' · score ' + (v.score == null ? 'none yet' : Math.round(v.score))));
    if (anyMine(v)) { h.appendChild(el('span', 'inc-n', 'with your changes')); }
    tip.appendChild(h);
    if (v.score == null) {
      tip.appendChild(el('div', 'inc-tip-x', 'Not scored yet: Rouh scores every idea in the background, a moment after it is added.'));
    } else {
      tip.appendChild(breakdownTable(v));
      tip.appendChild(el('div', 'inc-formula', ((S.data.facts.score || {}).formula || '') + '\n' + numbersOfScore(v)));
    }
    tip.hidden = false;
    var r = anchor.getBoundingClientRect();
    var w = tip.offsetWidth, hh = tip.offsetHeight;
    var x = Math.max(8, Math.min(window.innerWidth - w - 12, r.left));
    var y = r.bottom + 6;
    if (y + hh > window.innerHeight - 8) { y = Math.max(8, r.top - hh - 6); }
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
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
      tr.appendChild(el('td', 'inc-bd-v' + (mine ? ' mine' : ''), val));
      var why = key === 'stars' ? (v.stars_mine ? 'Yours; Rouh suggests ' + (v.stars_suggested || '–') + '. ' : 'Rouh’s suggestion. ') + (v.stars_why || '')
        : (mine ? 'Yours; Rouh said ' + shownPart(key, p.rouh) + '. ' : '') + (p.why || '');
      tr.appendChild(el('td', 'inc-bd-why', why));
      t.appendChild(tr);
    });
    return t;
  }
  function hideTip() { clearTimeout(S.tipT); if (tip) { tip.hidden = true; } }

  /* ---- deciding: at once on the screen, the toast with Undo ---- */

  function decide(v, what) {
    if (!v || !canDecide(v, what)) { return; }
    if (what === 'merge') { openCompare(v.number, (v.alike || [])[0] ? v.alike[0].number : 0); return; }
    var d = DECIDE.filter(function (x) { return x.id === what; })[0];
    // Undoing a Take that is still waiting is all a Park or a Drop of it needs first.
    if (v._pending) { cancelTake(v); }
    var was = { status: v.status, status_name: v.status_name };
    hold(v, d.name === 'Take' ? 'Taken' : d.name === 'Park' ? 'Parked' : 'Dropped');
    v.status = d.status; v.status_name = nameOf('statuses', d.status);
    if (what === 'take') { v._pending = true; }
    repaint(v);
    S.sel = v.number;
    stepSelection(1, true);
    if (what === 'take') {
      v._pending = true;
      S.pending[v.number] = setTimeout(function () {
        delete S.pending[v.number];
        call('/' + v.number + '/status', { status: 'go' }).then(function (j) {
          v._pending = false;
          if (j.idea) { Object.assign(v, j.idea); recalc(v); }
          toast(v.code + ' is in Gene therapy. It moves to In build once its feature request is written.');
          refreshIdea(v);
        }, function (err) {
          v._pending = false;
          v.status = was.status; v.status_name = was.status_name; delete S.left[v.number];
          repaint(v);
          toast(String((err && err.message) || err));
        });
      }, TAKE_WAIT);
      toast(v.code + ' ' + d.said + ' in ' + Math.round(TAKE_WAIT / 1000) + ' seconds.', function () {
        cancelTake(v);
        v.status = was.status; v.status_name = was.status_name; delete S.left[v.number];
        repaint(v);
        refreshIdea(v);
      });
      refreshIdea(v);
      return;
    }
    call('/' + v.number + '/status', { status: d.status }).then(function () { refreshIdea(v); }, function (err) {
      v.status = was.status; v.status_name = was.status_name; delete S.left[v.number];
      repaint(v);
      toast(String((err && err.message) || err));
    });
    toast(v.code + ' ' + d.said + '.', function () {
      v.status = was.status; v.status_name = was.status_name; delete S.left[v.number];
      repaint(v);
      call('/' + v.number + '/status', { status: was.status }).then(function () { refreshIdea(v); }, fail);
    });
    refreshIdea(v);
  }
  function cancelTake(v) {
    clearTimeout(S.pending[v.number]);
    delete S.pending[v.number];
    v._pending = false;
  }
  /* A decided row stays where it was, dimmed and saying what was done, until the list is put in order. */
  function hold(v, word) {
    if (!S.hold) { S.hold = true; }
    S.left[v.number] = word;
  }
  function refreshIdea(v) { if (S.idea && S.idea.number === v.number) { S.idea.status = v.status; S.idea.status_name = v.status_name; draw(); } }

  function toast(text, undo) {
    S.undo = undo || null;
    var t = $('incToast');
    if (!t) {
      t = el('div', 'inc-toast');
      t.id = 'incToast';
      t.setAttribute('role', 'status');
      t.setAttribute('aria-live', 'polite');
      document.body.appendChild(t);
    }
    t.textContent = '';
    t.appendChild(el('span', '', text));
    if (undo) {
      var u = button('inc-toast-undo', 'Undo', 'Undo it (Z)');
      u.addEventListener('click', doUndo);
      t.appendChild(u);
    }
    t.hidden = false;
    t.classList.remove('gone');
    clearTimeout(S.toastT);
    S.toastT = setTimeout(function () { t.classList.add('gone'); S.undo = null; setTimeout(function () { t.hidden = true; }, 200); },
      undo ? TAKE_WAIT + 1500 : 4500);
  }
  function doUndo() {
    var u = S.undo;
    if (!u) { return; }
    S.undo = null;
    u();
    toast('Undone.');
  }

  /* ---- the selected row ---- */

  function select(number, scroll) {
    S.sel = number;
    if (!S.root) { return; }
    S.root.querySelectorAll('.inc-row.sel').forEach(function (t) { if (t.getAttribute('data-n') !== String(number)) { t.classList.remove('sel'); } });
    var li = S.root.querySelector('.inc-row[data-n="' + number + '"]');
    if (li) {
      li.classList.add('sel');
      if (scroll) {
        hoverCard(null);
        var sc = scroller();
        if (sc) {
          var r = li.getBoundingClientRect(), b = sc.getBoundingClientRect();
          if (r.top < b.top + 8) { sc.scrollTop -= (b.top + 8 - r.top); }
          else if (r.bottom > b.bottom - 8) { sc.scrollTop += (r.bottom - b.bottom + 8); }
        }
      }
    }
  }
  function selectedIdea() { return S.sel ? ideaByNumber(S.sel) : null; }
  function stepSelection(by, quiet) {
    if (S.open) {
      var order = shown(), at = -1;
      for (var i = 0; i < order.length; i++) { if (order[i].number === S.open) { at = i; break; } }
      var next = order[Math.max(0, Math.min(order.length - 1, at + by))];
      if (next && next.number !== S.open) { openIdea(next.number, true); }
      return;
    }
    var rows = S.root ? Array.prototype.slice.call(S.root.querySelectorAll('.inc-row[data-n]')) : [];
    if (!rows.length) { return; }
    var pos = -1;
    for (var j = 0; j < rows.length; j++) { if (rows[j].getAttribute('data-n') === String(S.sel)) { pos = j; break; } }
    var to = pos < 0 ? (by > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, pos + by));
    select(Number(rows[to].getAttribute('data-n')), true);
    if (quiet) { return; }
  }

  /* ---- comparing two lookalikes ---- */

  function openCompare(a, b) { hoverCard(null); S.compare = { a: a, b: b, q: '' }; draw(); setTimeout(function () { var d = document.querySelector('#incOverlay .inc-cmp'); if (d) { d.focus(); } }, 0); }
  function closeCompare() { S.compare = null; draw(); }
  function drawCompare() {
    var c = S.compare;
    var wrap = el('div', 'inc-cmp-wrap');
    var scrim = el('div', 'inc-scrim');
    scrim.addEventListener('click', closeCompare);
    wrap.appendChild(scrim);
    var d = el('section', 'inc-cmp');
    d.tabIndex = -1;
    d.setAttribute('role', 'dialog');
    d.setAttribute('aria-modal', 'true');
    d.setAttribute('aria-label', 'Compare two ideas');
    var head = el('div', 'inc-cmp-h');
    head.appendChild(el('h3', '', 'Are these the same idea?'));
    var x = button('inc-x', '×', 'Close the comparison');
    x.addEventListener('click', closeCompare);
    head.appendChild(x);
    d.appendChild(head);
    var A = ideaByNumber(c.a), B = c.b ? ideaByNumber(c.b) : null;
    if (!A) { d.appendChild(el('p', 'evo-error', 'That idea is not in the list any more.')); wrap.appendChild(d); return wrap; }
    if (!B) {
      // No lookalike named: pick the other idea by its words or number.
      d.appendChild(el('p', 'inc-cmp-lede', 'Which idea is ' + A.code + ' the same as? Type its words or its number.'));
      var lab = el('label', 'inc-searchwrap');
      lab.appendChild(el('span', 'inc-vh', 'Find the other idea'));
      var inp = el('input', 'inc-search');
      inp.type = 'search';
      inp.placeholder = 'Words or INC-12';
      inp.value = c.q;
      lab.appendChild(inp);
      d.appendChild(lab);
      var res = el('div', 'inc-cmp-pick');
      var fill = function () {
        res.textContent = '';
        var q = inp.value.trim().toLowerCase();
        var hits = S.data.ideas.filter(function (v) {
          if (v.number === A.number || v.status === 'merged' || joined(A, v)) { return false; }
          if (!q) { return v.category === A.category && v.status !== 'built' && v.status !== 'rejected'; }
          var hay = (v.code + ' ' + v.title + ' ' + ((v.gist || {}).line || '') + ' ' + v.ref).toLowerCase();
          return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
        }).slice(0, 8);
        hits.forEach(function (v) {
          var b = button('inc-cmp-hit', '');
          b.appendChild(el('b', '', v.code + ' ' + v.title));
          b.appendChild(el('span', '', (v.gist || {}).line || nameOf('statuses', v.status)));
          b.addEventListener('click', function () { S.compare.b = v.number; draw(); });
          res.appendChild(b);
        });
        if (!q && hits.length) { res.insertBefore(el('p', 'inc-n', 'Open ideas in the same category, ' + nameOf('categories', A.category) + ':'), res.firstChild); }
        if (!hits.length) { res.appendChild(el('p', 'inc-n', q ? 'No idea matches.' : 'Type to find it.')); }
      };
      inp.addEventListener('input', function () { c.q = inp.value; fill(); });
      fill();
      d.appendChild(res);
      wrap.appendChild(d);
      setTimeout(function () { inp.focus(); }, 0);
      return wrap;
    }
    var cols = el('div', 'inc-cmp-cols');
    cols.appendChild(compareCol(A));
    cols.appendChild(compareCol(B));
    d.appendChild(cols);
    var keep = B.score != null && (A.score == null || B.score > A.score) ? B : A;
    var lose = keep === A ? B : A;
    var acts = el('div', 'inc-cmp-acts');
    var m1 = button('ctl primary inc-primary', 'Merge ' + lose.code + ' into ' + keep.code, 'Keep ' + keep.code + ' (higher score); ' + lose.code + ' is merged into it, with its sources and links');
    m1.addEventListener('click', function () { doMerge(lose, keep); });
    acts.appendChild(m1);
    var m2 = button('ctl', 'Merge ' + keep.code + ' into ' + lose.code);
    m2.addEventListener('click', function () { doMerge(keep, lose); });
    acts.appendChild(m2);
    var lk = button('ctl', 'Link them', 'Related but different ideas: each lists the other');
    lk.addEventListener('click', function () { doLink(A, B); });
    acts.appendChild(lk);
    var ns = button('ctl', 'Not the same', 'They are different ideas: never offered as lookalikes again');
    ns.addEventListener('click', function () { doApart(A, B); });
    acts.appendChild(ns);
    d.appendChild(acts);
    d.appendChild(el('p', 'inc-n inc-cmp-note', 'Merging keeps both ideas’ words; the one merged opens from the one it is in, and its sources and links move with it. Undo is in the message that follows.'));
    wrap.appendChild(d);
    return wrap;
  }
  function compareCol(v) {
    var g = v.gist || {};
    var col = el('article', 'inc-cmp-col');
    var top = el('div', 'inc-cmp-top');
    top.appendChild(el('span', 'inc-code', v.code));
    top.appendChild(statusChip(v));
    top.appendChild(scoreBar(v));
    col.appendChild(top);
    var t = el('a', 'inc-cmp-title', v.title);
    t.href = '/evolution/incubator/' + v.code;
    t.addEventListener('click', function (e) { e.preventDefault(); S.compare = null; openIdea(v.number); });
    col.appendChild(t);
    col.appendChild(el('p', 'inc-line1' + (g.line ? '' : ' wait'), g.line || firstWords(v.preview) || 'No words beyond its title.'));
    [['problem', 'The problem'], ['in_use', 'In use'], ['vision', 'Vision']].forEach(function (p) {
      if (!g[p[0]]) { return; }
      col.appendChild(el('h4', '', p[1]));
      col.appendChild(el('p', '', g[p[0]]));
    });
    col.appendChild(el('h4', '', 'Came from'));
    col.appendChild(el('p', '', originLine(v)));
    return col;
  }
  function doMerge(from, into) {
    var was = { status: from.status, status_name: from.status_name };
    call('/' + from.number + '/merge', { into: into.number }).then(function () {
      S.compare = null;
      hold(from, 'Merged into ' + into.code);
      toast(from.code + ' merged into ' + into.code + '.', function () {
        call('/' + from.number + '/status', { status: was.status }).then(function () { delete S.left[from.number]; load(); }, fail);
      });
      load();
    }, fail);
  }
  function doLink(a, b) {
    call('/' + a.number + '/link', { kind: 'idea', label: b.code + ': ' + b.title, href: '#' + b.code })
      .then(function () { return call('/' + b.number + '/link', { kind: 'idea', label: a.code + ': ' + a.title, href: '#' + a.code }); })
      .then(function () { S.compare = null; toast(a.code + ' and ' + b.code + ' are linked: each lists the other.'); load(); }, fail);
  }
  function pairKey(a, b) { return Math.min(a.number, b.number) + '-' + Math.max(a.number, b.number); }
  /* Two ideas already joined: one said not to be the same as the other, or linked to it. */
  function joined(a, b) {
    if (S.apart.indexOf(pairKey(a, b)) >= 0) { return true; }
    var linked = function (x, y) { return (x.links || []).some(function (l) { return l.kind === 'idea' && l.href === '#' + y.code; }); };
    return linked(a, b) || linked(b, a);
  }
  function doApart(a, b) {
    var k = pairKey(a, b);
    if (S.apart.indexOf(k) < 0) { S.apart.push(k); }
    S.compare = null;
    // Saved at once, then read again, so the pair is gone from both rows.
    clearTimeout(S.saveT);
    savePrefsNow().then(load);
    toast(a.code + ' and ' + b.code + ' are not the same: not offered again.', function () {
      S.apart = S.apart.filter(function (x) { return x !== k; });
      savePrefsNow().then(load);
    });
  }
  function savePrefsNow() {
    return call('/prefs', { prefs: { v: PREFS_V, views: S.views, sort: S.sort, group: S.group, f: S.f, hide: S.hide, q: S.q,
                                     view: S.view, legend: S.legend, apart: S.apart, cell: S.cell, filtersOpen: S.filtersOpen } }).catch(function () {});
  }

  /* ---- the keys ---- */

  var KEYS = [['↑ ↓  j k', 'move between ideas'], ['Space', 'At a glance, open or fold'], ['Enter', 'open the idea'],
              ['T', 'Take: Gene therapy builds it'], ['P', 'Park'], ['D', 'Drop'], ['M', 'Merge: compare with its lookalike'],
              ['Z', 'Undo the last decision'], ['1 2 3', 'your stars'], ['0', 'back to Rouh’s stars'], ['/', 'search'],
              ['R', 'put the list in order again'], ['Esc', 'close, then back to the list'], ['?', 'these keys']];
  function drawKeys() {
    var pop = el('div', 'inc-keys');
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Keys');
    pop.addEventListener('click', function (e) { e.stopPropagation(); });
    var h = el('div', 'inc-keys-h');
    h.appendChild(el('b', '', 'Keys'));
    var x = button('inc-x', '×', 'Close the keys');
    x.addEventListener('click', function () { S.menu = ''; draw(); });
    h.appendChild(x);
    pop.appendChild(h);
    var dl = el('dl', '');
    KEYS.forEach(function (k) {
      var d = el('div', 'inc-key');
      var dt = el('dt', '');
      k[0].split('  ').forEach(function (part) { dt.appendChild(el('kbd', '', part)); });
      d.appendChild(dt);
      d.appendChild(el('dd', '', k[1]));
      dl.appendChild(d);
    });
    pop.appendChild(dl);
    pop.appendChild(el('p', 'inc-n', 'The row under the pointer is the selected one. None of the keys work while you type in a field or the chat.'));
    return pop;
  }

  /* ---- one idea's page ---- */

  function openIdea(number, quiet) {
    hideTip();
    hoverCard(null);
    var first = !S.open;
    if (first) { S.listTop = scroller() ? scroller().scrollTop : 0; }
    S.open = number;
    S.sel = number;
    S.reading = '';
    S.fb = '';
    if (!S.idea || S.idea.number !== number) { S.idea = null; }
    S.scrollTop = true;
    draw();
    var sc = scroller();
    if (sc) { sc.scrollTop = 0; }
    call('/' + number).then(function (j) {
      if (S.open !== number) { return; }
      S.idea = j.idea;
      recalc(S.idea);
      moved('INC-' + number, j.idea.title);
      S.scrollTop = true;
      draw();
      var h = S.root && S.root.querySelector('.inc-p-title');
      if (h && !quiet) { h.focus({ preventScroll: true }); }
    }, function (err) {
      if (S.open !== number) { return; }
      S.idea = { error: String((err && err.message) || err), number: number };
      draw();
    });
  }
  function closeIdea() {
    var n = S.open;
    S.open = 0; S.idea = null; S.reading = '';
    moved('', '');
    S.scrollTop = true;
    draw();
    var sc = scroller();
    if (sc) { sc.scrollTop = S.listTop || 0; }
    if (n) { select(n, true); }
  }

  function drawIdea() {
    var p = el('article', 'inc-page');
    p.setAttribute('aria-label', 'One idea');
    var bar = el('div', 'inc-p-bar');
    var back = button('inc-back', '', 'Back to the list (Esc)');
    back.appendChild(icon('back'));
    back.appendChild(el('span', '', 'All ideas'));
    back.addEventListener('click', closeIdea);
    bar.appendChild(back);
    var order = shown(), at = -1;
    for (var i = 0; i < order.length; i++) { if (order[i].number === S.open) { at = i; break; } }
    if (at >= 0) {
      var nav = el('div', 'inc-p-nav');
      var prev = button('inc-navb', 'Previous', 'The idea before this one in the list (k)');
      prev.disabled = at === 0;
      prev.addEventListener('click', function () { stepSelection(-1); });
      nav.appendChild(prev);
      nav.appendChild(el('span', 'inc-n', (at + 1) + ' of ' + order.length));
      var next = button('inc-navb', 'Next', 'The idea after this one in the list (j)');
      next.disabled = at === order.length - 1;
      next.addEventListener('click', function () { stepSelection(1); });
      nav.appendChild(next);
      bar.appendChild(nav);
    }
    p.appendChild(bar);
    var v = S.idea;
    if (!v) { p.appendChild(el('p', 'evo-loading', 'Reading INC-' + S.open + '…')); return p; }
    if (v.error) { p.appendChild(el('p', 'evo-error', v.error)); return p; }
    var row = ideaByNumber(v.number) || v;
    var g = v.gist || {};

    // 1. What it is: its vision and its line, first.
    var hero = el('header', 'inc-p-hero');
    var meta = el('div', 'inc-p-meta');
    meta.appendChild(el('span', 'inc-code', v.code));
    meta.appendChild(statusChip(row));
    meta.appendChild(catChip(v));
    if (v.kind) { meta.appendChild(chip('none', v.kind_name + (v.gene ? ': ' + v.gene : ''))); }
    if (g.size) { meta.appendChild(chip('size', SIZE_NAME[g.size], SIZE_LINE[g.size])); }
    hero.appendChild(meta);
    var title = el('h2', 'inc-p-title', v.title);
    title.tabIndex = -1;
    hero.appendChild(title);
    if (g.vision) {
      var vis = el('p', 'inc-p-vision');
      vis.appendChild(el('span', 'inc-p-k', 'Vision'));
      vis.appendChild(document.createTextNode(g.vision));
      hero.appendChild(vis);
    }
    hero.appendChild(el('p', 'inc-p-line' + (g.line ? '' : ' wait'), g.line || 'Rouh has not summed this idea up yet; it does so in the background, those to decide first. Its own words are below.'));
    if (v.merged_into) {
      var mi = el('p', 'inc-p-merged');
      mi.appendChild(document.createTextNode('Merged into ' + v.merged_into.code + '. '));
      var mo = button('inc-link', 'Open ' + v.merged_into.code);
      mo.addEventListener('click', function () { openIdea(Number(v.merged_into.code.replace(/^INC-/, ''))); });
      mi.appendChild(mo);
      hero.appendChild(mi);
    }
    p.appendChild(hero);

    // 2. The decision.
    var dec = el('section', 'inc-p-decide');
    dec.setAttribute('aria-label', 'Decide');
    DECIDE.forEach(function (d) {
      var b = button(d.id === 'take' ? 'ctl primary inc-primary' : 'ctl', '', d.name + ': ' + d.line + ' (' + d.key.toUpperCase() + ')');
      b.appendChild(icon(d.id));
      b.appendChild(el('span', '', d.id === 'take' ? 'Take: build it' : d.name));
      b.disabled = !canDecide(row, d.id);
      b.addEventListener('click', function () { decide(row, d.id); });
      dec.appendChild(b);
    });
    var more = el('div', 'inc-p-sels');
    var st = el('select', 'inc-sel');
    st.setAttribute('aria-label', 'Status of ' + v.code);
    facts('statuses').forEach(function (s) { if (s.id !== 'merged' && s.id !== 'go') { st.appendChild(new Option(s.name, s.id, false, s.id === row.status)); } });
    if (row.status === 'go' || row.status === 'merged') { st.insertBefore(new Option(row.status_name, row.status, true, true), st.firstChild); }
    st.addEventListener('change', function () {
      var was = row.status;
      call('/' + v.number + '/status', { status: st.value }).then(function () {
        toast(v.code + ' is ' + nameOf('statuses', st.value) + ' now.', function () { call('/' + v.number + '/status', { status: was }).then(function () { load(); openIdea(v.number, true); }, fail); });
        load(); openIdea(v.number, true);
      }, fail);
    });
    more.appendChild(labelled('Status', st));
    var ct = el('select', 'inc-sel');
    ct.setAttribute('aria-label', 'Category of ' + v.code);
    facts('categories').forEach(function (c) { ct.appendChild(new Option(c.name, c.id, false, c.id === v.category)); });
    ct.addEventListener('change', function () { call('/' + v.number, { category: ct.value }).then(function () { load(); openIdea(v.number, true); }, fail); });
    more.appendChild(labelled('Category', ct));
    dec.appendChild(more);
    if (row._pending) { dec.appendChild(el('p', 'inc-n', 'Going to Gene therapy in a few seconds: Undo is in the message at the bottom.')); }
    if (v.request_id) { dec.appendChild(el('p', 'inc-n', 'Feature request ' + v.request_id + ' in Gene therapy.')); }
    if (v.built_as) { dec.appendChild(el('p', 'inc-n', 'Became: ' + v.built_as)); }
    p.appendChild(dec);

    // 3. Depth: at a glance, then its value, its lookalikes and where it came from.
    var depth = el('div', 'inc-p-cols');
    var left = el('div', 'inc-p-col');
    var gl = el('section', 'inc-p-sec inc-o1');
    gl.appendChild(el('h3', 'inc-p-h', 'At a glance'));
    var dl = el('dl', 'inc-glance-g');
    [['problem', 'The problem'], ['helps', 'Who it helps'], ['in_use', 'What it looks like in use'], ['size_why', 'How big']].forEach(function (pp) {
      if (!g[pp[0]]) { return; }
      var d = el('div', 'inc-gi');
      d.appendChild(el('dt', '', pp[1]));
      d.appendChild(el('dd', '', pp[0] === 'size_why' ? SIZE_NAME[g.size] + ': ' + g.size_why : g[pp[0]]));
      dl.appendChild(d);
    });
    if (!dl.childNodes.length) { gl.appendChild(el('p', 'inc-n', 'Not summed up yet: the problem, who it helps and what it looks like in use come once Rouh has read it.')); }
    else { gl.appendChild(dl); }
    left.appendChild(gl);
    left.appendChild(drawFeedback(v));
    left.appendChild(drawWords(v));
    depth.appendChild(left);
    var right = el('div', 'inc-p-col');
    right.appendChild(drawScorePanel(row, v));
    right.appendChild(drawRelated(v));
    right.appendChild(drawOrigin(v));
    depth.appendChild(right);
    p.appendChild(depth);
    p.appendChild(drawHistory(v));
    return p;
  }
  function labelled(text, control) {
    var l = el('label', 'inc-selbox');
    l.appendChild(el('span', '', text));
    l.appendChild(control);
    return l;
  }

  /* Feedback and its own chat, kept with the idea. */
  function drawFeedback(v) {
    var s = el('section', 'inc-p-sec inc-p-fb inc-o3');
    s.appendChild(el('h3', 'inc-p-h', 'Your feedback, and its chat'));
    var lab = el('label', 'inc-fb-l');
    lab.appendChild(el('span', 'inc-vh', 'Your feedback on ' + v.code));
    var ta = el('textarea', 'inc-fb');
    ta.rows = 3;
    ta.placeholder = 'What you think of it, what to change, what it must not do…';
    ta.value = S.fb || '';
    ta.addEventListener('input', function () { S.fb = ta.value; });
    lab.appendChild(ta);
    s.appendChild(lab);
    var row = el('div', 'inc-fb-acts');
    var save = button('ctl', 'Save feedback');
    save.addEventListener('click', function () {
      var text = ta.value.trim();
      if (!text) { ta.focus(); return; }
      save.disabled = true;
      call('/' + v.number + '/feedback', { text: text }).then(function (j) {
        S.fb = '';
        S.idea = j.idea; recalc(S.idea);
        toast('Feedback kept with ' + v.code + '.');
        draw();
      }, function (err) { save.disabled = false; fail(err); });
    });
    row.appendChild(save);
    var chat = button('ctl', 'Chat about this idea', 'Open ' + v.code + '’s own chat beside the page; Rouh knows the idea there');
    chat.addEventListener('click', function () { openChat('', v.number); });
    row.appendChild(chat);
    s.appendChild(row);
    var fb = v.feedback || [];
    if (fb.length) {
      var ol = el('ol', 'inc-fb-list');
      fb.forEach(function (h) {
        var li = el('li');
        li.appendChild(el('span', 'inc-n', day(h.at) + (h.by && h.by !== 'you' ? ', ' + h.by : '')));
        li.appendChild(el('p', '', h.note));
        ol.appendChild(li);
      });
      s.appendChild(ol);
    }
    // Notes that are not feedback: what Rouh or a run wrote while checking it.
    var other = String(v.notes || '').split(/\n\n+/).filter(function (x) { return x && !/^Feedback, /.test(x); });
    if (other.length) {
      var nd = el('details', 'inc-sec');
      nd.appendChild(el('summary', '', 'Notes · ' + other.length));
      other.forEach(function (n) { nd.appendChild(el('p', 'inc-note', n)); });
      s.appendChild(nd);
    }
    return s;
  }

  function drawRelated(v) {
    var s = el('section', 'inc-p-sec inc-o4');
    s.appendChild(el('h3', 'inc-p-h', 'Looks like, linked and merged'));
    var any = false;
    (v.alike || []).forEach(function (o) {
      any = true;
      var r = el('div', 'inc-rel');
      r.appendChild(el('span', 'inc-rel-k', o.why === 'rouh' ? 'Rouh says it is the same' : 'Close in its words'));
      r.appendChild(el('span', 'inc-rel-t', o.code + ' ' + o.title));
      var b = button('ctl small', 'Compare');
      b.addEventListener('click', function () { openCompare(v.number, o.number); });
      r.appendChild(b);
      s.appendChild(r);
    });
    (v.links || []).filter(function (l) { return l.kind === 'idea'; }).forEach(function (l) {
      any = true;
      var r = el('div', 'inc-rel');
      r.appendChild(el('span', 'inc-rel-k', 'Linked'));
      var b = button('inc-link inc-rel-t', l.label);
      b.addEventListener('click', function () { var m = /INC-(\d+)/.exec(l.href || l.label); if (m) { openIdea(Number(m[1])); } });
      r.appendChild(b);
      s.appendChild(r);
    });
    (v.merged_here || []).forEach(function (m) {
      any = true;
      var r = el('div', 'inc-rel');
      r.appendChild(el('span', 'inc-rel-k', 'Merged into this one'));
      var b = button('inc-link inc-rel-t', m.code + ' ' + m.title + ' (' + m.source_name + (m.ref ? ' ' + m.ref : '') + ')');
      b.addEventListener('click', function () { openIdea(Number(m.code.replace(/^INC-/, ''))); });
      r.appendChild(b);
      s.appendChild(r);
    });
    if (!any) { s.appendChild(el('p', 'inc-n', 'No idea looks like this one, and none is linked or merged into it.')); }
    var find = button('inc-link', 'Compare with another idea…');
    find.addEventListener('click', function () { openCompare(v.number, 0); });
    s.appendChild(find);
    return s;
  }

  function drawOrigin(v) {
    var s = el('section', 'inc-p-sec inc-o5');
    s.appendChild(el('h3', 'inc-p-h', 'Where it came from'));
    s.appendChild(el('p', 'inc-p-from', originLine(v) + (v.source_status ? ' Its status there: ' + v.source_status + '.' : '')));
    var groups = [['task', 'Task'], ['step', 'Step'], ['chat', 'Chats'], ['page', 'Pages'], ['request', 'Feature request'],
                  ['gene', 'Gene'], ['file', 'Files'], ['link', 'Links']];
    groups.forEach(function (gg) {
      var mine = (v.links || []).filter(function (l) { return l.kind === gg[0]; });
      if (!mine.length) { return; }
      var box = el('div', 'inc-links');
      box.appendChild(el('span', 'inc-links-h', gg[1] + (mine.length > 1 ? ' · ' + mine.length : '')));
      var list = el('ul', 'inc-links-l' + (mine.length > 8 ? ' long' : ''));
      mine.forEach(function (l) {
        var li = el('li');
        if (gg[0] === 'page') {
          var rb = button('inc-link', l.label, 'Read it here');
          rb.addEventListener('click', function () { S.reading = l.href; S.readingName = l.label; draw(); var r = S.root.querySelector('.inc-reader'); if (r) { r.scrollIntoView({ block: 'start' }); } });
          li.appendChild(rb);
        } else if (l.href) {
          var a = el('a', 'inc-link', l.label);
          a.href = l.href;
          if (/^\/(task|gene-therapy|evolution|\?)/.test(l.href) || l.href.indexOf('?chat=') >= 0) {
            a.addEventListener('click', function (e) { if (e.metaKey || e.ctrlKey) { return; } e.preventDefault(); go(l.href); });
          } else { a.target = '_blank'; a.rel = 'noopener'; }
          li.appendChild(a);
        } else { li.textContent = l.label; }
        list.appendChild(li);
      });
      box.appendChild(list);
      s.appendChild(box);
    });
    if (S.reading) {
      var rd = el('div', 'inc-reader');
      var rh = el('div', 'inc-reader-h');
      rh.appendChild(el('b', '', S.readingName || 'Page'));
      var ro = el('a', 'inc-link', 'Open on its own');
      ro.href = S.reading; ro.target = '_blank'; ro.rel = 'noopener';
      rh.appendChild(ro);
      var rc = button('inc-link', 'Close');
      rc.addEventListener('click', function () { S.reading = ''; draw(); });
      rh.appendChild(rc);
      rd.appendChild(rh);
      var fr = el('iframe', 'inc-frame');
      fr.src = S.reading;
      fr.title = S.readingName || 'Page';
      fr.setAttribute('sandbox', 'allow-same-origin allow-scripts allow-popups');
      rd.appendChild(fr);
      s.appendChild(rd);
    }
    return s;
  }

  /* The original words, exactly as written, in sections. */
  function drawWords(v) {
    var s = el('section', 'inc-p-sec inc-o6');
    var secs = (v.sections || []).length ? v.sections : [{ title: 'The idea', text: v.original || '' }];
    s.appendChild(el('h3', 'inc-p-h', 'As it was written' + (secs.length > 1 ? ' · ' + secs.length + ' parts' : '')));
    secs.forEach(function (sec, i) {
      var d = el('details', 'inc-sec');
      d.open = i === 0 && (sec.text || '').length < 6000;
      var sm = el('summary', '');
      sm.appendChild(el('span', '', sec.title || 'Part ' + (i + 1)));
      sm.appendChild(el('span', 'inc-n', Math.max(1, Math.round((sec.text || '').length / 6)).toLocaleString() + ' words'));
      d.appendChild(sm);
      var fillIn = function () {
        if (d.querySelector('.inc-text, .inc-pre')) { return; }
        var body = el('div', 'inc-text');
        var md = S.host && S.host.markdown;
        if (md && (sec.text || '').length < 200000) {
          try { var html = md(sec.text || ''); if (typeof html === 'string') { body.innerHTML = html; } else if (html && html.nodeType) { body.appendChild(html); } else { body.textContent = sec.text || ''; } }
          catch (e) { body.textContent = sec.text || ''; }
        } else { body.textContent = sec.text || ''; }
        var raw = button('inc-link inc-raw', 'Show the exact characters');
        raw.addEventListener('click', function () { body.replaceWith(el('pre', 'inc-pre', sec.text || '')); raw.remove(); });
        d.appendChild(raw);
        d.appendChild(body);
      };
      if (d.open) { fillIn(); }
      d.addEventListener('toggle', function () { if (d.open) { fillIn(); } });
      s.appendChild(d);
    });
    return s;
  }

  function drawHistory(v) {
    var hd = el('details', 'inc-sec inc-p-hist');
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
    return hd;
  }

  /* Its value: the stars, every part with its menu, its reason and whose it is, the formula, how often it
     came back, and Score again. */
  function drawScorePanel(row, v) {
    var box = el('section', 'inc-p-sec inc-p-score inc-o2');
    box.setAttribute('aria-label', 'Value of ' + v.code);
    box.appendChild(el('h3', 'inc-p-h', 'Its value'));
    var top = el('div', 'inc-p-score-h');
    top.appendChild(scoreBar(row));
    top.appendChild(starsEl(row, true));
    top.appendChild(el('span', 'inc-n', row.stars_mine ? 'your stars; Rouh suggests ' + (row.stars_suggested || '–') :
      row.stars_suggested ? 'Rouh’s suggested stars' : ''));
    box.appendChild(top);
    var cb = v.came_back || {};
    var bits = [];
    if (cb.merged) { bits.push(cb.merged + ' merged into it'); }
    if (cb.sources) { bits.push(plural(cb.sources, 'other source')); }
    if (cb.chats) { bits.push(plural(cb.chats, 'chat')); }
    if (cb.proposed) { bits.push('proposed again ' + plural(cb.proposed, 'time')); }
    box.appendChild(el('p', 'inc-n', bits.length ? 'It came back: ' + bits.join(', ') + '.' : 'It has not come back from anywhere else yet.'));
    if (row.score == null && !v.scored_at) {
      box.appendChild(el('p', 'inc-n', 'Not scored yet: Rouh scores it in the background, a moment after it is added.'));
    } else {
      var t = el('table', 'inc-bd inc-bd-panel');
      PARTS.forEach(function (key) {
        var pp = (row.parts || {})[key] || {}, mine = pp.mine != null, tr = el('tr');
        tr.appendChild(el('th', '', (partFacts(key) || {}).name));
        var td = el('td');
        var sel = el('select', 'inc-sel' + (mine ? ' mine' : ''));
        sel.setAttribute('aria-label', (partFacts(key) || {}).name + ' of ' + v.code);
        sel.appendChild(new Option('Rouh’s: ' + shownPart(key, pp.rouh), '', false, !mine));
        var choices = partChoices(key);
        if (mine && choices.indexOf(pp.mine) < 0) { choices.push(pp.mine); }
        choices.forEach(function (x) { sel.appendChild(new Option(shownPart(key, x), String(x), false, mine && x === pp.mine)); });
        sel.addEventListener('keydown', function (e) { e.stopPropagation(); });
        sel.addEventListener('change', function () { setPart(row, key, sel.value === '' ? null : Number(sel.value)); });
        td.appendChild(sel);
        tr.appendChild(td);
        tr.appendChild(el('td', 'inc-bd-why', (mine ? 'Yours; Rouh said ' + shownPart(key, pp.rouh) + '. ' : '') + (pp.why || '')));
        t.appendChild(tr);
      });
      var det = el('details', 'inc-sec');
      det.appendChild(el('summary', '', 'Its parts, and why'));
      det.appendChild(t);
      det.appendChild(el('div', 'inc-formula', ((S.data.facts.score || {}).formula || '') + '\n' + numbersOfScore(row)));
      det.appendChild(el('p', 'inc-n', 'There is no part for effort: the size above is shown beside the score, never in it.' +
        (v.scored_at ? ' Scored by Rouh ' + when(v.scored_at) + (v.scored_model ? ', with ' + v.scored_model : '') + '.' : '')));
      box.appendChild(det);
    }
    var again = button('inc-link', 'Score it again', 'Rouh scores it again now; what you set stays');
    again.addEventListener('click', function () {
      again.disabled = true; again.textContent = 'Scoring…';
      call('/' + v.number + '/score', { rescore: true }).then(function (j) {
        var r = ideaByNumber(v.number);
        if (r) { r.parts = j.idea.parts; r.stars_suggested = j.idea.stars_suggested; r.stars_mine = j.idea.stars_mine; r.stars_why = j.idea.stars_why; recalc(r); }
        S.idea = j.idea; recalc(S.idea); S.hold = true;
        draw();
      }, function (err) { again.disabled = false; again.textContent = 'Score it again'; fail(err); });
    });
    box.appendChild(again);
    return box;
  }

  /* ---- adding, and the chats ---- */

  function newIdea() { S.adding = !S.adding; draw(); var t = S.root && S.root.querySelector('.inc-new-t'); if (t) { t.focus(); } }
  function drawNew() {
    var f = el('form', 'inc-new');
    f.setAttribute('aria-label', 'Add an idea');
    var l1 = el('label', 'inc-new-l');
    l1.appendChild(el('span', '', 'The idea, in a few words'));
    var t = el('input', 'inc-search inc-new-t');
    t.required = true;
    t.maxLength = 300;
    l1.appendChild(t);
    f.appendChild(l1);
    var l2 = el('label', 'inc-new-l');
    l2.appendChild(el('span', '', 'Say it whole, as you would say it (optional)'));
    var w = el('textarea', 'inc-fb');
    w.rows = 3;
    l2.appendChild(w);
    f.appendChild(l2);
    var row = el('div', 'inc-fb-acts');
    var add = el('button', 'ctl', 'Add it');
    add.type = 'submit';
    row.appendChild(add);
    var no = button('ctl', 'Cancel');
    no.addEventListener('click', function () { S.adding = false; draw(); });
    row.appendChild(no);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var title = t.value.trim();
      if (!title) { t.focus(); return; }
      add.disabled = true;
      call('/new', { title: title, text: w.value.trim() || title }).then(function (j) {
        S.adding = false;
        toast('Added ' + j.idea.code + '. Rouh scores it and sums it up in a moment.');
        load(); openIdea(j.idea.number);
      }, function (err) { add.disabled = false; fail(err); });
    });
    return f;
  }
  /* The Incubator's own chat, or one idea's own chat, beside the page. */
  function openChat(words, number) {
    call(number ? '/' + number + '/chat' : '/chat', {}).then(function (j) {
      var addr = '/evolution/incubator' + (S.open ? '/INC-' + S.open : '') + '?chat=' + encodeURIComponent(j.chat);
      go(addr);
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

  /* ---- the keys and Escape ---- */

  function live() { return S.root && S.root.isConnected && !S.root.closest('[hidden]') && S.data; }
  document.addEventListener('click', function () { if (S.menu) { S.menu = ''; draw(); } });
  /* Escape closes the innermost thing open: a menu, the comparison, the idea's page, and only then the
     layer. Taken before the layer's own Escape, which would close the whole Incubator. */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !live()) { return; }
    var t = /** @type {Element} */ (e.target);
    if (t && t.closest && t.closest('#input')) { return; }
    if (S.menu) { S.menu = ''; draw(); }
    else if (S.compare) { closeCompare(); }
    else if (card) { hoverCard(null); }
    else if (S.open) { closeIdea(); }
    else { return; }
    e.stopPropagation();
    e.preventDefault();
  }, true);

  document.addEventListener('keydown', function (e) {
    if (!live() || e.defaultPrevented || S.compare) { return; }
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    var t = /** @type {Element} */ (e.target);
    if (t && t.closest && t.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], dialog')) { return; }
    var onControl = t && t.closest && t.closest('button, a[href]');
    if (onControl && (e.key === 'Enter' || e.key === ' ')) { return; }
    var k = e.key, v = S.open ? (ideaByNumber(S.open) || null) : selectedIdea();
    if (/^[0-3]$/.test(k)) {
      if (!v) { return; }
      var n = Number(k);
      if ((v.stars_mine || 0) !== n) { setStars(v, n || null); }
    } else if (k === 'ArrowDown' || k === 'j') { stepSelection(1); }
    else if (k === 'ArrowUp' || k === 'k') { stepSelection(-1); }
    else if (k === 'Enter' || k === 'o') { if (!v || S.open) { return; } openIdea(v.number); }
    else if (k === ' ' || k === 'ArrowRight' || k === 'ArrowLeft') {
      if (!v || S.open) { return; }
      if ((k === 'ArrowRight') === !!S.expanded[v.number] && k !== ' ') { return; }
      toggleExpand(v.number);
    }
    else if (k === 't' || k === 'p' || k === 'd' || k === 'm') {
      if (!v) { return; }
      decide(v, { t: 'take', p: 'park', d: 'drop', m: 'merge' }[k]);
    }
    else if (k === 'z' || k === 'u') { doUndo(); }
    else if (k === '/') { if (S.open) { return; } var s = S.root.querySelector('.inc-search'); if (s) { s.focus(); s.select(); } }
    else if (k === 'r' || k === 'R') { resort(); }
    else if (k === '?') { S.menu = S.menu === 'keys' ? '' : 'keys'; draw(); }
    else { return; }
    e.preventDefault();
  });
  window.addEventListener('scroll', function () { hoverCard(null); hideTip(); }, true);
  /* A Take still waiting when the page goes away is sent then, as the person left it. */
  window.addEventListener('pagehide', function () {
    Object.keys(S.pending).forEach(function (n) {
      clearTimeout(S.pending[n]);
      delete S.pending[n];
      try { fetch(API + '/' + n + '/status', { method: 'POST', credentials: 'same-origin', keepalive: true,
                                               headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'go' }) }); } catch (err) { /* nothing more to do */ }
    });
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
    hidden: function () {
      S.fresh = false; hideTip(); hoverCard(null);
      S.compare = null; if (S.menu === 'keys') { S.menu = ''; }
      var over = $('incOverlay'); if (over) { over.textContent = ''; }
    },
    heard: function () { if (S.root && S.root.isConnected) { load(); if (S.open) { openIdea(S.open, true); } } }
  };
}());
