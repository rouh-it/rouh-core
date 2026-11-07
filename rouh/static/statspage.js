/* Settings, Stats, at /settings/stats, and the counting it shows (`rouh/navtaps.py`,
   `rouh/events.py`, `rouh/web/stats.py`).

   Petar, 10 October 2026 (fr_e82bf294e064): "Please make a new feature where I see
   navigation tap counts. Settings should have stats and for now, stats will have just
   each navigation item and the count of taps in a bar chart for total for 30 days
   rolling back."

   And the same evening, of the event log: "For now put an extra tab in the
   settings/stats and show me some basic numbers so I get a feel that we are
   collecting."

   Two tabs, each with an address of its own (`RouhStatsHost.tabbed`):

   1. **Navigation**, `/settings/stats`. Every press of a row of the navigation is
      sent to the server, the row's `data-nav` key and nothing else, with
      `/api/nav/tap`. Listened for on the way down (capture), so a row whose own
      handler stops the click is still counted, and sent with `keepalive`, so a
      row that leaves the page still gets there. A press of the row for where the
      person already is counts too: a press is a press. Drawn as a bar per row,
      most pressed first, over the last 30 days back from now; a row nobody
      pressed is a bar of zero, so the whole list is always there.
   2. **Event log**, `/settings/stats/events`. The person's own numbers from the
      event log (`track.js` and the server's own events), read from its rollups
      by `/api/settings/stats/events`: how much is being collected, per day, of
      what kind, and the first counts of writing, opening, work and tools.

   Petar, 12 October 2026 (fr_0ef0ca151b48): "can you update stats for the
   navigation to take the new double level. we need to have stats for the tabs on
   the left too. and maybe make a chart that shows which flows where." So a press
   of one of the rail's five group boxes is counted too, as `group:<id>`, and
   every press carries the id of this page load (`VISIT`), so the server can
   follow one journey at a time. The Navigation tab draws two cards from it:

   - **Navigation taps**, a box at a time in the rail's order, each with its
     presses in all, then the box itself and the links beside it as bars on the
     one scale, most pressed first; then the area under them that is always
     there (Rouh, Search, Gene therapy).
   - **Where you went next**, the flow, drawn the way Google Analytics draws its
     behaviour flow: a column per step of a journey, a block per place as tall
     as the journeys that were there, a band to each place they went next, and
     a grey strip on a block for the journeys that ended there. By section or
     by link; under it, the commonest moves as bars, which is the same thing as
     a list a screen reader can read.

   Settings tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  var S = { open: false, tab: '', data: null, error: '', seq: 0, level: '',
            log: null, logError: '', logSeq: 0 };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  /* ---- counting ---- */
  /* This page load, so the server can tell one journey from another going on at
     the same time in another tab or on another device. */
  var VISIT = (function () {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (err) {}
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  })();
  function tapped(e) {
    if (e.button) return;
    var t = e.target;
    if (!t || !t.closest) return;
    var item = '';
    var box = t.closest('#sbTabs .sb-tab[data-group]');
    if (box) item = 'group:' + box.getAttribute('data-group');
    else {
      var row = t.closest('#tasksPanel [data-nav]');
      if (row) item = row.getAttribute('data-nav') || '';
    }
    // A shared gene's link comes and goes with the organisation's lab
    // (`rouh/genelab.py`), and is not one of the navigation's own to count.
    if (!item || item.indexOf('shared-') === 0) return;
    try {
      fetch('/api/nav/tap', {
        method: 'POST', credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        body: JSON.stringify({ item: item, visit: VISIT })
      }).catch(function () {});
    } catch (err) { /* a count is never worth an error on the page */ }
  }
  document.addEventListener('click', tapped, true);

  /* ---- reading ---- */
  function load() { return S.tab === 'events' ? loadLog() : loadNav(); }
  function loadLog() {
    var seq = ++S.logSeq;
    var zone = '';
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { zone = ''; }
    return fetch('/api/settings/stats/events', {
      credentials: 'same-origin', cache: 'no-store', headers: zone ? { 'X-Time-Zone': zone } : {}
    })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== S.logSeq) return j;
          if (r.ok) { S.log = j; S.logError = ''; }
          else S.logError = (j && j.error) || 'The server said ' + r.status + '.';
          draw();
          return j;
        });
      })
      .catch(function () {
        if (seq !== S.logSeq) return;
        S.logError = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function loadNav() {
    var seq = ++S.seq;
    return fetch('/api/settings/stats', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== S.seq) return j;
          if (r.ok) { S.data = j; S.error = ''; }
          else S.error = (j && j.error) || 'The server said ' + r.status + '.';
          draw();
          return j;
        });
      })
      .catch(function () {
        if (seq !== S.seq) return;
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  /* ---- drawing ---- */
  function day(seconds) {
    try {
      return new Date(seconds * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    } catch (err) { return ''; }
  }
  function taps(n) { return n === 1 ? '1 tap' : n + ' taps'; }

  function draw() {
    var body = $('statsBody');
    if (!body || !S.open) return;
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    page.appendChild(tabs());
    if (S.tab === 'events') { drawLog(page); return; }
    if (S.error) {
      var say = el('p', 'hb-say bad', S.error);
      say.setAttribute('role', 'status');
      page.appendChild(say);
    }
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the stats…'));
      return;
    }
    if (S.data.navigation) page.appendChild(navCard(S.data.navigation));
    if (S.data.flow) page.appendChild(flowCard(S.data.flow, S.data.navigation));
    fillFlow();
  }

  /* The flow is drawn to the width its card has, once the card is on the page,
     and again when that width changes. */
  function fillFlow() {
    var holder = $('stFlow');
    if (!holder || !S.data || !S.data.flow) return;
    var f = S.data.flow[S.level === 'links' ? 'links' : 'sections'];
    holder.textContent = '';
    holder.appendChild(flowChart(f, holder.clientWidth || 600));
  }
  var resizing = 0;
  window.addEventListener('resize', function () {
    clearTimeout(resizing);
    resizing = setTimeout(function () { if (S.open && S.tab !== 'events') fillFlow(); }, 150);
  });

  function navCard(nav) {
    var s = el('section', 'setting-card hb-card st-card');
    s.setAttribute('aria-labelledby', 'stNavHead');
    var h = el('h4', 'hb-h', 'Navigation taps');
    h.id = 'stNavHead';
    h.appendChild(el('span', 'hb-h-sub', taps(nav.total) + ' in the last ' + nav.days + ' days'));
    s.appendChild(h);
    var boxesFrom = nav.boxes_since > nav.since ? ' The boxes have been counted since ' + day(nav.boxes_since) +
      ' and the links since ' + day(nav.links_since) + ', so a box shows only its presses from then on.' : '';
    s.appendChild(el('p', 'settings-help', 'How often you pressed each group box on the left of the navigation, ' +
      'and each link beside it, on every device you use, from ' + day(nav.since) + ' to today.' + boxesFrom));
    var most = 0;
    function top(n) { if (n > most) most = n; }
    nav.groups.forEach(function (g) { top(g.box); g.items.forEach(function (it) { top(it.taps); }); });
    (nav.dedicated || []).forEach(function (it) { top(it.taps); });

    var list = el('div', 'st-bars st-levels');
    list.setAttribute('role', 'list');
    list.setAttribute('aria-label', 'Taps on each group box and link of the navigation in the last ' +
      nav.days + ' days');
    function bar(name, n, cls, title) {
      var row = el('div', 'st-bar' + (cls ? ' ' + cls : '') + (n ? '' : ' none'));
      row.setAttribute('role', 'listitem');
      row.title = title + ': ' + taps(n) + ' in the last ' + nav.days + ' days';
      row.setAttribute('aria-label', row.title);
      var label = el('span', 'st-name');
      label.appendChild(name);
      row.appendChild(label);
      var track = el('span', 'st-track');
      track.setAttribute('aria-hidden', 'true');
      var fill = el('span', 'st-fill');
      fill.style.width = most ? (100 * n / most) + '%' : '0';
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el('span', 'st-count', n));
      return row;
    }
    function head(id, name, sum, note) {
      var row = el('div', 'st-group');
      row.id = 'stGroup-' + id;
      row.setAttribute('role', 'heading');
      row.setAttribute('aria-level', '5');
      row.appendChild(el('span', 'st-group-name', name));
      row.appendChild(el('span', 'st-group-n', note ? note : taps(sum)));
      return row;
    }
    nav.groups.forEach(function (g) {
      list.appendChild(head(g.id, g.name, g.box + g.links));
      var boxName = document.createDocumentFragment();
      boxName.appendChild(el('span', 'st-box-mark', g.name + ' box'));
      list.appendChild(bar(boxName, g.box, 'st-box', 'The ' + g.name + ' box'));
      g.items.forEach(function (it) {
        list.appendChild(bar(document.createTextNode(it.name), it.taps, 'st-link', it.name));
      });
    });
    if ((nav.dedicated || []).length) {
      var sum = 0;
      nav.dedicated.forEach(function (it) { sum += it.taps; });
      list.appendChild(head('always', 'Always there', sum));
      nav.dedicated.forEach(function (it) {
        list.appendChild(bar(document.createTextNode(it.name), it.taps, 'st-link', it.name));
      });
    }
    s.appendChild(list);
    return s;
  }

  /* ---- where the person went next ---- */
  var SVG = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    var n = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, String(attrs[k])); });
    return n;
  }
  function journeys(n) { return n === 1 ? '1 journey' : n + ' journeys'; }
  var ORDINAL = ['Started at', 'Then', 'Then', 'Then'];

  function flowCard(all, nav) {
    var level = S.level === 'links' ? 'links' : 'sections';
    var f = all[level] || { steps: [], links: [], moves: [], journeys: 0 };
    var s = el('section', 'setting-card hb-card st-card');
    s.setAttribute('aria-labelledby', 'stFlowHead');
    var h = el('h4', 'hb-h', 'Where you went next');
    h.id = 'stFlowHead';
    h.appendChild(el('span', 'hb-h-sub', journeys(f.journeys) + ' in the last ' + nav.days + ' days'));
    s.appendChild(h);

    var seg = el('div', 'st-tabs st-seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'Show the flow');
    [['sections', 'By section'], ['links', 'By link']].forEach(function (o) {
      var b = el('button', 'st-tab' + (level === o[0] ? ' on' : ''), o[1]);
      b.type = 'button';
      b.id = 'stFlow-' + o[0];
      b.setAttribute('aria-pressed', level === o[0] ? 'true' : 'false');
      b.addEventListener('click', function () {
        if (S.level === o[0] || (!S.level && o[0] === 'sections')) return;
        S.level = o[0];
        draw();
        var again = $('stFlow-' + o[0]);
        if (again) again.focus();
      });
      seg.appendChild(b);
    });
    s.appendChild(seg);

    s.appendChild(el('p', 'settings-help', level === 'sections' ?
      'Each journey through the navigation, step by step: a box and the links beside it are one section, ' +
      'and Rouh, Search and Gene therapy are each their own. A journey is one open Rouh tab, until a pause of ' +
      all.pause_minutes + ' minutes. The grey strip on a place is the journeys that ended there.' :
      'Each journey through the navigation, step by step, link by link; pressing a box only shows its links, ' +
      'so it is not a step. A journey is one open Rouh tab, until a pause of ' + all.pause_minutes +
      ' minutes. The grey strip on a place is the journeys that ended there.'));

    if (!f.journeys || !f.steps.length) {
      s.appendChild(el('p', 'hb-empty', 'No journeys yet. They appear here as you move around the navigation.'));
      return s;
    }
    var holder = el('div', 'st-flow');
    holder.id = 'stFlow';
    s.appendChild(holder);
    if (f.moves.length) {
      s.appendChild(el('h5', 'st-sub', 'Commonest moves'));
      s.appendChild(movesList(f.moves, nav.days));
    }
    if (nav.boxes_since > nav.since) {
      s.appendChild(el('p', 'settings-help st-note', 'Presses from before ' + day(nav.boxes_since) + ' carry ' +
        'no tab, so those are read as one journey per pause, from whichever device.'));
    }
    return s;
  }

  function flowChart(f, width) {
    // As many steps as fit with a block wide enough for a name, at least two.
    var GAP = 44, PAD = 6, MIN = 34, DROP = 5, H = 300, TOP = 40, WIDEST = 170;
    var cols = f.steps.length;
    while (cols > 2 && (width - DROP - (cols - 1) * GAP) / cols < 104) cols--;
    var steps = f.steps.slice(0, cols);
    var NW = Math.min(WIDEST, Math.floor((width - DROP - (cols - 1) * GAP) / cols));
    var most = 0;
    steps.forEach(function (st) { var sum = 0; st.nodes.forEach(function (nd) { sum += nd.n; }); if (sum > most) most = sum; });
    var gaps = 0;
    steps.forEach(function (st) { gaps = Math.max(gaps, (st.nodes.length - 1) * PAD); });
    var k = most ? Math.max(0.5, (H - gaps) / most) : 1;
    var at = {}, tall = 0;
    steps.forEach(function (st, i) {
      var y = TOP;
      st.nodes.forEach(function (nd) {
        var hgt = Math.max(MIN, nd.n * k);
        at[i + '|' + nd.key] = { x: i * (NW + GAP), y: y, h: hgt, out: 0, inn: 0, nd: nd };
        y += hgt + PAD;
      });
      if (y > tall) tall = y;
    });
    var W = cols * NW + (cols - 1) * GAP + DROP;
    var HT = tall + DROP + 4;

    var wrap = el('div', 'st-flow');
    var pic = svg('svg', { viewBox: '0 0 ' + W + ' ' + HT, width: W, height: HT, role: 'img' });
    pic.setAttribute('aria-label', 'Flow of journeys through the navigation, step by step. ' +
      'The commonest moves are listed under it.');
    var bands = svg('g', { 'class': 'st-bands' }), blocks = svg('g', {});
    pic.appendChild(bands);
    pic.appendChild(blocks);

    steps.forEach(function (st, i) {
      var x = i * (NW + GAP);
      var t1 = svg('text', { x: x, y: 13, 'class': 'st-flow-step' });
      t1.textContent = ORDINAL[i] || 'Then';
      var t2 = svg('text', { x: x, y: 29, 'class': 'st-flow-sub' });
      t2.textContent = journeys(st.n) + ', ' + st.ended + ' ended';
      blocks.appendChild(t1);
      blocks.appendChild(t2);
    });

    // Bands, out of a block in the order of the next column, into one in the order of the last.
    var order = {};
    steps.forEach(function (st, i) { st.nodes.forEach(function (nd, j) { order[i + '|' + nd.key] = j; }); });
    var shown = f.links.filter(function (l) { return l.step + 1 < cols; });
    var outs = shown.slice().sort(function (a, b) {
      return a.step - b.step || order[a.step + '|' + a.from] - order[b.step + '|' + b.from] ||
        order[(a.step + 1) + '|' + a.to] - order[(b.step + 1) + '|' + b.to];
    });
    var y0 = {};
    outs.forEach(function (l) {
      var a = at[l.step + '|' + l.from];
      if (!a) return;
      y0[l.step + '|' + l.from + '>' + l.to] = a.y + a.out;
      a.out += l.n * k;
    });
    var ins = shown.slice().sort(function (a, b) {
      return a.step - b.step || order[(a.step + 1) + '|' + a.to] - order[(b.step + 1) + '|' + b.to] ||
        order[a.step + '|' + a.from] - order[b.step + '|' + b.from];
    });
    ins.forEach(function (l) {
      var a = at[l.step + '|' + l.from], b = at[(l.step + 1) + '|' + l.to];
      if (!a || !b) return;
      var w = l.n * k, ya = y0[l.step + '|' + l.from + '>' + l.to], yb = b.y + b.inn;
      b.inn += w;
      var x1 = a.x + NW, x2 = b.x, mx = (x1 + x2) / 2;
      var d = 'M' + x1 + ',' + ya + 'C' + mx + ',' + ya + ' ' + mx + ',' + yb + ' ' + x2 + ',' + yb +
        'L' + x2 + ',' + (yb + w) + 'C' + mx + ',' + (yb + w) + ' ' + mx + ',' + (ya + w) + ' ' + x1 + ',' + (ya + w) + 'Z';
      var band = svg('path', { d: d, 'class': 'st-band' });
      var tip = svg('title', {});
      tip.textContent = a.nd.name + ' then ' + b.nd.name + ': ' + journeys(l.n);
      band.appendChild(tip);
      bands.appendChild(band);
    });

    Object.keys(at).forEach(function (key) {
      var a = at[key], nd = a.nd;
      var g = svg('g', { 'class': 'st-node' + (nd.key === '*' ? ' more' : '') });
      var tip = svg('title', {});
      tip.textContent = nd.name + ': ' + journeys(nd.n) + (nd.ended ? ', ' + nd.ended + ' ended here' : '');
      g.appendChild(tip);
      g.appendChild(svg('rect', { x: a.x, y: a.y, width: NW, height: a.h, rx: 4, 'class': 'st-node-box' }));
      g.appendChild(svg('rect', { x: a.x, y: a.y, width: 3, height: a.h, rx: 1.5, 'class': 'st-node-edge' }));
      if (nd.ended) {
        // The journeys that ended here: a grey strip down the foot of the block's right edge.
        var dh = Math.max(3, Math.min(a.h, nd.ended * k));
        g.appendChild(svg('rect', { x: a.x + NW, y: a.y + a.h - dh, width: DROP, height: dh, rx: 1.5, 'class': 'st-drop' }));
      }
      var name = svg('text', { x: a.x + 10, y: a.y + 15, 'class': 'st-node-name' });
      var label = nd.name;
      var fits = Math.max(6, Math.floor((NW - 14) / 7.4));
      if (label.length > fits) label = label.slice(0, fits - 1) + '…';
      name.textContent = label;
      g.appendChild(name);
      var n = svg('text', { x: a.x + 10, y: a.y + 29, 'class': 'st-node-n' });
      n.textContent = nd.n;
      g.appendChild(n);
      blocks.appendChild(g);
    });
    wrap.appendChild(pic);
    return wrap;
  }

  function movesList(moves, days) {
    var most = 0;
    moves.forEach(function (m) { if (m.n > most) most = m.n; });
    var list = el('ol', 'st-bars');
    list.setAttribute('aria-label', 'The commonest moves in the last ' + days + ' days');
    moves.forEach(function (m) {
      var row = el('li', 'st-bar');
      row.title = m.from_name + ' then ' + m.to_name + ': ' + (m.n === 1 ? 'once' : m.n + ' times');
      var name = el('span', 'st-name st-move');
      name.appendChild(el('span', '', m.from_name));
      var arrow = el('span', 'st-arrow', '→');
      arrow.setAttribute('aria-label', 'then');
      name.appendChild(arrow);
      name.appendChild(el('span', '', m.to_name));
      row.appendChild(name);
      var track = el('span', 'st-track');
      track.setAttribute('aria-hidden', 'true');
      var fill = el('span', 'st-fill');
      fill.style.width = most ? (100 * m.n / most) + '%' : '0';
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el('span', 'st-count', m.n));
      list.appendChild(row);
    });
    return list;
  }

  /* ---- the tabs ---- */
  var TABS = [['', 'Navigation'], ['events', 'Event log']];
  function tabs() {
    var bar = el('div', 'st-tabs');
    bar.setAttribute('role', 'tablist');
    bar.setAttribute('aria-label', 'Which stats');
    TABS.forEach(function (t) {
      var on = S.tab === t[0];
      var b = el('button', 'st-tab' + (on ? ' on' : ''), t[1]);
      b.type = 'button';
      b.id = 'stTab' + (t[0] || 'nav');
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.addEventListener('click', function () {
        if (S.tab === t[0]) return;
        pick(t[0]);
        var host = window.RouhStatsHost;
        if (host && host.tabbed) host.tabbed(t[0]);
        var now = $('stTab' + (t[0] || 'nav'));
        if (now) now.focus();
      });
      bar.appendChild(b);
    });
    return bar;
  }
  function pick(tab) {
    S.tab = tab === 'events' ? 'events' : '';
    draw();
    load();
  }

  /* ---- the event log ---- */
  var NAMES = {
    'ui.click': 'Presses', 'ui.open': 'Things opened', 'ui.typed': 'Spells of typing',
    'page.loaded': 'Rouh opened in a tab', 'page.shown': 'Tab back in sight', 'page.hidden': 'Tab out of sight',
    'chat.message_sent': 'Messages sent', 'chat.forked': 'Chats forked', 'turn.finished': 'Answers from Rouh',
    'tool.called': 'Tool calls', 'job.started': 'Jobs started', 'job.finished': 'Jobs finished',
    'run.started': 'Runs started', 'run.finished': 'Run turns finished', 'mail.handled': 'Emails handled',
    'reminder.fired': 'Reminders due', 'decision.answered': 'Decisions answered', 'schedule.ran': 'Scheduled work'
  };
  function num(n) { try { return Number(n || 0).toLocaleString('en-GB'); } catch (err) { return String(n || 0); } }
  function bytes(n) {
    n = Number(n || 0);
    if (n < 1024) return n + ' bytes';
    if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + ' kB';
    if (n < 1024 * 1024 * 1024) return (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB';
    return (n / 1073741824).toFixed(1) + ' GB';
  }
  function span(ms) {
    var s = Math.round(Number(ms || 0) / 1000);
    if (s < 60) return s + ' s';
    var m = Math.round(s / 60);
    if (m < 60) return m + ' min';
    var h = Math.floor(m / 60);
    return h + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
  }
  function when(iso) {
    if (!iso) return 'nothing yet';
    try {
      var d = new Date(iso);
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ', ' +
        d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    } catch (err) { return iso; }
  }
  function card(id, title, sub) {
    var s = el('section', 'setting-card hb-card st-card');
    s.setAttribute('aria-labelledby', id);
    var h = el('h4', 'hb-h', title);
    h.id = id;
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }
  function tile(label, value, id) {
    var t = el('div', 'st-tile');
    var v = el('div', 'st-tile-n', value);
    if (id) v.id = id;
    t.appendChild(v);
    t.appendChild(el('div', 'st-tile-l', label));
    return t;
  }
  /** A bar per row, the navigation card's way: [label, n, title?, href?]. */
  function bars(rows, label, sub) {
    var most = 0;
    rows.forEach(function (r) { if (r[1] > most) most = r[1]; });
    var list = el('ol', 'st-bars');
    list.setAttribute('aria-label', label);
    rows.forEach(function (r) {
      var row = el('li', 'st-bar' + (r[1] ? '' : ' none'));
      row.title = (r[2] || r[0]) + ': ' + num(r[1]);
      var name = el(r[3] ? 'a' : 'span', 'st-name' + (sub ? ' st-name-sub' : ''));
      if (r[3]) { name.href = r[3]; name.setAttribute('data-inapp', ''); }
      name.textContent = r[0];
      if (r[4]) name.appendChild(el('span', 'st-code', r[4]));
      row.appendChild(name);
      var track = el('span', 'st-track');
      track.setAttribute('aria-hidden', 'true');
      var fill = el('span', 'st-fill');
      fill.style.width = most ? (100 * r[1] / most) + '%' : '0';
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el('span', 'st-count', num(r[1])));
      list.appendChild(row);
    });
    return list;
  }
  function perDay(days) {
    var most = 0;
    days.forEach(function (d) { if (d.n > most) most = d.n; });
    var wrap = el('div', 'st-days');
    var cols = el('ol', 'st-cols');
    cols.setAttribute('aria-label', 'Events on each of the last ' + days.length + ' days');
    days.forEach(function (d, i) {
      var day = new Date(d.day + 'T12:00:00');
      var said = day.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
      var li = el('li', 'st-col' + (i === days.length - 1 ? ' today' : '') + (d.n ? '' : ' none'));
      li.title = said + ': ' + num(d.n) + (d.n === 1 ? ' event' : ' events');
      li.setAttribute('aria-label', li.title);
      var bar = el('span', 'st-col-bar');
      bar.style.height = most && d.n ? Math.max(2, 100 * d.n / most) + '%' : '0';
      li.appendChild(bar);
      cols.appendChild(li);
    });
    wrap.appendChild(cols);
    var axis = el('div', 'st-axis');
    axis.setAttribute('aria-hidden', 'true');
    [0, Math.floor(days.length / 2), days.length - 1].forEach(function (i) {
      if (!days[i]) return;
      var d = new Date(days[i].day + 'T12:00:00');
      axis.appendChild(el('span', '', i === days.length - 1 ? 'Today' :
        d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })));
    });
    wrap.appendChild(axis);
    if (most) wrap.appendChild(el('p', 'st-scale', 'Tallest day: ' + num(most) + ' events'));
    return wrap;
  }
  function placeName(type, id) {
    var parts = String(id || '').split('/');
    var last = parts[parts.length - 1] || id;
    var shown = last.replace(/^(\d+(?:-\d+)*)\./, '$1 ').replace(/-/g, ' ');
    return [shown, parts.slice(0, -1).join(' / ')];
  }

  function drawLog(page) {
    if (S.logError) {
      var say = el('p', 'hb-say bad', S.logError);
      say.setAttribute('role', 'status');
      page.appendChild(say);
    }
    var d = S.log;
    if (!d) {
      if (!S.logError) page.appendChild(el('p', 'hb-empty', 'Reading the event log…'));
      return;
    }
    var t = d.totals || {};

    // Is it collecting: the counts, the newest event, and what it takes on disk.
    var c = card('stLogHead', 'Collecting', 'your own events, from every device');
    var tiles = el('div', 'st-tiles');
    tiles.appendChild(tile('Today', num(t.today), 'stToday'));
    tiles.appendChild(tile('This week', num(t.week), 'stWeek'));
    tiles.appendChild(tile('In total', num(t.all), 'stAll'));
    c.appendChild(tiles);
    var facts = el('dl', 'st-facts');
    function fact(k, v) { facts.appendChild(el('dt', '', k)); facts.appendChild(el('dd', '', v)); }
    fact('Most recent event', when(t.last));
    var st = d.storage || {};
    fact('Stored', bytes(st.bytes) + ' for everybody\'s events, in ' + num(st.months) +
      (st.months === 1 ? ' monthly table' : ' monthly tables') + ', ' + num(st.rows) + ' rows; ' +
      bytes(st.rollup_bytes) + ' of daily and hourly counts');
    var w = d.writer || {};
    fact('This server', num(w.written) + ' written since it started, ' + num(w.waiting) + ' waiting' +
      (w.dropped ? ', ' + num(w.dropped) + ' lost' : ', none lost'));
    c.appendChild(facts);
    c.appendChild(el('p', 'settings-help', 'Counts and ids only: what you type or say is never kept. ' +
      'Counting started on 10 October 2026, and the numbers here catch up within a minute.'));
    page.appendChild(c);

    var days = card('stDaysHead', 'Events per day', 'the last ' + d.days + ' days, on your clock');
    days.appendChild(perDay(d.per_day || []));
    page.appendChild(days);

    var kinds = card('stKindsHead', 'What was recorded', 'the last ' + d.days + ' days');
    if ((d.names || []).length) {
      kinds.appendChild(bars(d.names.map(function (n) {
        return [NAMES[n.name] || n.name, n.n, n.name, '', n.name];
      }), 'Events of each kind in the last ' + d.days + ' days', true));
    } else kinds.appendChild(el('p', 'hb-empty', 'Nothing yet.'));
    page.appendChild(kinds);

    var ty = d.typing || {};
    var wr = card('stWriteHead', 'Writing', 'the last ' + d.days + ' days');
    var wt = el('div', 'st-tiles');
    wt.appendChild(tile('Messages sent', num(ty.messages), 'stMessages'));
    wt.appendChild(tile('Letters in them', num(ty.message_chars), 'stMessageChars'));
    wt.appendChild(tile('Characters typed', num(ty.typed_chars), 'stTyped'));
    wt.appendChild(tile('Chats forked', num(d.forks), 'stForks'));
    wr.appendChild(wt);
    wr.appendChild(el('p', 'settings-help', 'Characters typed counts every box on the page, over ' +
      span(ty.typing_ms) + ' of typing. Messages count typed, spoken and Telegram ones.'));
    page.appendChild(wr);

    var op = card('stOpenHead', 'Opened most', 'tasks, steps and projects, the last ' + d.days + ' days');
    if ((d.opened || []).length) {
      op.appendChild(bars(d.opened.map(function (o) {
        var n = placeName(o.type, o.id);
        return [n[0], o.n, o.type + ' ' + o.id, '/' + (o.type === 'project' ? 'project' : 'task') + '/' + o.id, n[1]];
      }), 'Tasks and projects opened most in the last ' + d.days + ' days', true));
    } else op.appendChild(el('p', 'hb-empty', 'Nothing opened yet.'));
    page.appendChild(op);

    var wk = card('stWorkHead', 'Work', 'jobs and runs, the last ' + d.days + ' days');
    if ((d.work || []).length) {
      var table = el('table', 'st-table');
      var head = el('tr');
      ['', 'Started', 'Finished', 'Time'].forEach(function (x) { head.appendChild(el('th', '', x)); });
      var thead = el('thead');
      thead.appendChild(head);
      table.appendChild(thead);
      var tb = el('tbody');
      d.work.forEach(function (r) {
        var tr = el('tr');
        tr.appendChild(el('th', '', (r.kind === 'run' ? 'Runs' : 'Jobs') + ' started by ' +
          (r.actor === 'person' ? 'you' : r.actor === 'rouh' ? 'Rouh' : r.actor)));
        tr.appendChild(el('td', '', num(r.started)));
        tr.appendChild(el('td', '', num(r.finished)));
        tr.appendChild(el('td', '', r.finished ? span(r.duration_ms) : '-'));
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      wk.appendChild(table);
    } else wk.appendChild(el('p', 'hb-empty', 'No jobs or runs yet.'));
    var turns = d.turns || {};
    wk.appendChild(el('p', 'settings-help', num(turns.n) + (turns.n === 1 ? ' answer' : ' answers') +
      ' from Rouh, ' + span(turns.duration_ms) + ' in all.'));
    page.appendChild(wk);

    var tl = card('stToolsHead', 'Tool calls', 'by tool, the last ' + d.days + ' days');
    if ((d.tools || []).length) {
      tl.appendChild(bars(d.tools.map(function (x) { return [x.tool, x.n]; }),
        'Calls of each tool in the last ' + d.days + ' days'));
    } else tl.appendChild(el('p', 'hb-empty', 'No tool calls yet.'));
    page.appendChild(tl);
  }

  /* ---- shown and left ---- */
  function shownNow(tab) {
    var want = tab === 'events' ? 'events' : '';
    if (S.open && S.tab === want) return;
    S.open = true;
    pick(want);
  }
  function hiddenNow() { S.open = false; }

  window.RouhStats = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
