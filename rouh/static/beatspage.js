/* The heartbeat's beats, a page of their own at /anatomy/behaviour/beats (`rouh/beatlog.py`).

   Petar, 5 October 2026: "Make a separate page, linked from the heartbeat page and
   from each long-running work item, that lists beats as a table." And 20 October 2026:
   "please make the beats list in a separate page. that should be a huge table with
   search, filter, analysis etc". So the heartbeat page no longer lists beats; this is
   the one place they are, and it is laid across the whole width Anatomy has.

   One row a beat, newest first: when, what it was on, what woke it, how far it got
   (skipped by the rules in code, put back to sleep by the wake-up check, or passed on to
   the decision), what the decision did, the messages, approvals and jobs it made, the
   models it asked, its tokens, cost and time, and any error. A press on a row opens it in
   place (`/api/heartbeat/beats/<id>`): the note it was handed, every model request, every
   tool call with what it was asked and answered, and what it made.

   Above the table, the same rows read as numbers: beats a day by how far they got, spend
   a day against the daily cap, tokens a decision took (the context growing shows here
   first), messages a day against the limit, errors a day, the decisions by kind, and each
   model on each step, so whether Luna is enough for the wake-up check and the decision
   can be judged.

   The quest it is filtered to is in the path (`/beats/<quest number>`), the days are asked
   of the server, and everything else - the search, the other filters, the sort, the page
   of rows and the beat opened - is worked out here and kept in the address
   (`RouhBeatsHost.filtered`), so Back, a reload and a link opened in a new tab come to
   the same screen. Export gives the rows the filters pick as CSV.

   Arriving at a beat (`?beat=<id>`, the link a heartbeat's notice carries,
   `heartbeat.beat_address`) brings it into view opened: on the page of rows it is on, on
   its own day if it is older than the days read, and with any yes it waits on drawn as the
   decision it is, answered where it is (`decision.js`). Petar, 29 October 2026
   (fr_7765d34deebf): "the open button gets me to page .../heartbeat and not to the
   specific heartbeat and details and decision".

   A section of Anatomy, drawn into `#beatsBody`; Anatomy tells it when it shows and when
   it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var PAGE = 100;
  var B = { open: false, data: null, busy: false, error: '', said: '', seq: 0, tick: 0,
            work: 'all', start: '', end: '', f: {}, picked: {}, opened: {}, details: {},
            built: false, csv: '', sig: '', land: '', landAsked: '' };

  /* Everything a filter can say, as the address says it, and what it is when it says nothing. */
  var DEFAULTS = { q: '', woke: '', stage: '', kind: '', model: '', msg: '', err: '', cost: '',
                   sort: 'at', dir: 'desc', page: '1', beat: '' };

  var WOKE = [['', 'Anything'], ['timer', 'Timer'], ['event', 'Event'], ['due', 'Its own time'],
              ['now', 'Asked now'], ['answer', 'Your answer'], ['summary', 'Daily summary']];
  var STAGE = [['', 'Any'], ['code', 'Skipped in code'], ['slept', 'Check: nothing to do'],
               ['woke', 'Check: passed on'], ['direct', 'Not checked'], ['decided', 'Reached a decision'],
               ['running', 'Running']];
  var KIND = [['', 'Any'], ['nothing', 'Nothing'], ['note', 'Note'], ['telegram', 'Message'],
              ['work', 'Started work'], ['approval', 'Approval asked'], ['failed', 'Failed']];

  function host() { return window.RouhBeatsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, title) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) b.title = title;
    b.addEventListener('click', act);
    return b;
  }
  function link(text, href, cls) {
    var a = el('a', cls || 'hb-link', text);
    a.href = href;
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      e.preventDefault();
      if (host().go) host().go(href);
    });
    return a;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function count(n, one, many) { return n.toLocaleString('en-GB') + ' ' + (n === 1 ? one : (many || one + 's')); }
  function money(v) {
    if (v == null) return '';
    if (v === 0) return '$0';
    if (Math.abs(v) < 0.01) return '$' + v.toFixed(4).replace(/0+$/, '');
    return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function tokens(n) {
    if (!n) return '0';
    if (n < 1000) return String(n);
    if (n < 1e6) return (n < 1e4 ? (n / 1000).toFixed(1) : Math.round(n / 1000)) + 'k';
    return (n / 1e6).toFixed(n < 1e7 ? 2 : 1) + 'M';
  }
  function seconds(s) {
    if (s == null) return '';
    if (s < 90) return Math.round(s) + ' s';
    var m = Math.floor(s / 60), r = Math.round(s - m * 60);
    return m + ' min' + (r ? ' ' + r + ' s' : '');
  }
  function pct(a, b) { return b ? Math.round(100 * a / b) + '%' : '-'; }
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function dayWords(day) {
    var p = day.split('-');
    return Number(p[2]) + ' ' + MONTHS[Number(p[1]) - 1];
  }

  /* ---- the address ---- */

  function query() {
    var p = new URLSearchParams();
    Object.keys(DEFAULTS).forEach(function (k) {
      if (B.f[k] != null && String(B.f[k]) !== DEFAULTS[k]) p.set(k, String(B.f[k]));
    });
    if (B.start) p.set('from', B.start);
    if (B.end) p.set('to', B.end);
    return p.toString();
  }

  function readQuery(text) {
    var p = new URLSearchParams(String(text || '').replace(/^\?/, ''));
    var f = {};
    Object.keys(DEFAULTS).forEach(function (k) { f[k] = p.get(k) != null ? p.get(k) : DEFAULTS[k]; });
    return { f: f, start: p.get('from') || '', end: p.get('to') || '' };
  }

  /** Tell Anatomy the address changed. @param {boolean} [typing] a search being typed replaces the entry */
  function told(typing) {
    if (host().filtered) host().filtered(B.work, query(), !!typing);
  }

  /* ---- the server ---- */

  function call(method, body) {
    var seq = ++B.seq;
    if (method === 'POST') B.busy = true;
    var url = '/api/heartbeat/beats' + (method === 'GET' ? '?work=' + encodeURIComponent(B.work) +
      '&from=' + encodeURIComponent(B.start) + '&to=' + encodeURIComponent(B.end) : '');
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') B.busy = false;
          if (seq !== B.seq) return j;
          var changed = true;
          if (j && j.beats) {
            var sig = signature(j);
            changed = sig !== B.sig || method === 'POST';
            B.sig = sig;
            if (changed) B.data = j;
            var there = {};
            j.beats.forEach(function (b) { if (B.picked[b.id]) there[b.id] = true; });
            B.picked = there;
          }
          var hadError = !!B.error;
          if (r.ok) {
            B.error = '';
            if (j && j.said) B.said = j.said;
          } else {
            B.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          // Nothing is drawn again when nothing changed (principle B1).
          if (changed || hadError || B.error || (j && j.said)) draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') B.busy = false;
        B.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function signature(d) {
    var b = d.beats;
    var s = d.total + '|' + b.length;
    for (var i = 0; i < Math.min(b.length, 40); i++) s += '|' + b[i].id + b[i].stage + b[i].ended_words + (b[i].cost || 0);
    return s;
  }

  function load() { return call('GET'); }

  function openBeat(id) {
    if (B.details[id]) return;
    B.details[id] = { loading: true };
    fetch('/api/heartbeat/beats/' + id, { credentials: 'same-origin', cache: 'no-store',
                                          headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
        B.details[id] = r.ok ? j : { error: (j && j.error) || 'The server said ' + r.status + '.' };
        paintDetail(id);
      }); })
      .catch(function () {
        B.details[id] = { error: 'Rouh could not be reached.' };
        paintDetail(id);
      });
  }

  /* ---- filtering ---- */

  function matches(b, f) {
    if (f.woke && b.woke !== f.woke) return false;
    if (f.stage) {
      if (f.stage === 'decided' ? !b.decided : b.stage !== f.stage) return false;
    }
    if (f.kind && b.kinds.indexOf(f.kind) < 0) return false;
    if (f.model && b.check_model !== f.model && b.decide_models.indexOf(f.model) < 0) return false;
    if (f.msg === '1' && !b.messages) return false;
    if (f.err === '1' && !b.errors.length) return false;
    if (f.cost !== '' && f.cost != null) {
      var least = parseFloat(f.cost);
      if (!isNaN(least) && !((b.cost || 0) >= least)) return false;
    }
    if (f.q) {
      var words = String(f.q).toLowerCase().split(/\s+/).filter(Boolean);
      var hay = b._hay || (b._hay = [b.id, b.number, b.when, b.work.title, b.woke_words, b.stage_words, b.why,
        b.decision_words, b.ended_words, b.duties.join(' '), b.said, b.errors.join(' '), b.tools.join(' '),
        b.approvals.map(function (a) { return a.what; }).join(' '), b.check_model,
        b.decide_models.join(' ')].join(' \n').toLowerCase());
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function picked() {
    if (!B.data) return [];
    var f = B.f;
    return B.data.beats.filter(function (b) { return matches(b, f); });
  }

  /* ---- the columns ---- */

  var COLUMNS = [
    { key: 'number', head: 'Beat', cls: 'bt-num', title: 'Its number among the beats on the same work', num: true },
    { key: 'at', head: 'Time', cls: 'bt-when', num: true },
    { key: 'work', head: 'On', cls: 'bt-work' },
    { key: 'woke', head: 'Woke by', cls: 'bt-woke' },
    { key: 'stage', head: 'Wake-up check', cls: 'bt-stage' },
    { key: 'decision', head: 'Decision', cls: 'bt-dec' },
    { key: 'said', head: 'What it said, or why it stopped', cls: 'bt-sum' },
    { key: 'messages', head: 'Messages', cls: 'bt-n', num: true },
    { key: 'approvals', head: 'Approvals', cls: 'bt-n', num: true },
    { key: 'started', head: 'Jobs', cls: 'bt-n', num: true, title: 'Jobs and runs it started' },
    { key: 'duties', head: 'Duties', cls: 'bt-duties' },
    { key: 'check_model', head: 'Check model', cls: 'bt-model' },
    { key: 'decide_models', head: 'Decision model', cls: 'bt-model' },
    { key: 'tokens_in', head: 'Tokens in', cls: 'bt-n', num: true, title: 'Every token sent, cached ones included, over all its requests' },
    { key: 'tokens_out', head: 'Out', cls: 'bt-n', num: true, title: 'Tokens the models wrote' },
    { key: 'cost', head: 'Cost', cls: 'bt-n', num: true },
    { key: 'took', head: 'Took', cls: 'bt-n', num: true },
    { key: 'errors', head: 'Errors', cls: 'bt-err', num: true }
  ];

  function sortValue(b, key) {
    switch (key) {
      case 'work': return (b.work.title || '').toLowerCase();
      case 'woke': return b.woke_words.toLowerCase();
      case 'stage': return b.stage_words.toLowerCase();
      case 'decision': return b.decision_words.toLowerCase();
      case 'said': return (b.said || b.why || '').toLowerCase();
      case 'approvals': return b.approvals.length;
      case 'duties': return b.duties.join(', ').toLowerCase();
      case 'decide_models': return b.decide_models.join(', ').toLowerCase();
      case 'check_model': return (b.check_model || '').toLowerCase();
      case 'errors': return b.errors.length;
      default: return b[key];
    }
  }

  function sorted(rows) {
    var key = B.f.sort, sign = B.f.dir === 'asc' ? 1 : -1;
    return rows.slice().sort(function (a, b) {
      var x = sortValue(a, key), y = sortValue(b, key);
      // What has no value goes last either way.
      var xe = x == null || x === '', ye = y == null || y === '';
      if (xe || ye) return xe && ye ? b.at - a.at : xe ? 1 : -1;
      if (x < y) return -sign;
      if (x > y) return sign;
      return b.at - a.at;
    });
  }

  /* ---- drawing ---- */

  function scroller() {
    var n = $('beatsBody');
    while (n && n !== document.body) {
      if (n.scrollHeight > n.clientHeight && /(auto|scroll)/.test(getComputedStyle(n).overflowY)) return n;
      n = n.parentElement;
    }
    return null;
  }

  /* The page's frame, drawn once each time it is shown: the heading, the filters and
     the places the analysis and the table are drawn into. Typing in the search box is
     never interrupted by a redraw. */
  function build() {
    var body = $('beatsBody');
    if (!body) return;
    body.textContent = '';
    var page = el('div', 'hb-page bt-page');
    body.appendChild(page);
    var say = el('p', 'hb-say');
    say.id = 'beatsSay';
    say.setAttribute('role', 'status');
    say.hidden = true;
    page.appendChild(say);

    var head = el('div', 'bt-head');
    // Anatomy's heading above says what the page is; this line says how many.
    var h = el('p', 'bt-title');
    var sub = el('span', 'bt-count');
    sub.id = 'beatsCount';
    h.appendChild(sub);
    var info = el('button', 'bt-i', 'i');
    info.type = 'button';
    info.id = 'beatsInfo';
    info.setAttribute('aria-label', 'How a beat goes');
    info.setAttribute('aria-expanded', 'false');
    h.appendChild(info);
    head.appendChild(h);
    var back = link('The heartbeat', '/settings/heartbeat', 'hb-link bt-back');
    head.appendChild(back);
    page.appendChild(head);
    var about = el('div', 'bt-about');
    about.id = 'beatsAbout';
    about.hidden = true;
    [
      'A beat is first checked against the rules in code: paused, quiet hours, the daily cap, nothing new. ' +
      'Skipped there, no model is asked and it costs nothing.',
      'A beat woken by the timer or an event then goes to the wake-up check, a small model that reads what the ' +
      'beat would be handed and either lets it sleep or passes it on. A beat you asked for, your answer, its own ' +
      'time and the daily summary skip the check.',
      'The decision is the beat’s own turn: it ends with nothing, a silent note, or a message to you, and may ' +
      'start jobs or ask for your approval.',
      'Cost and tokens are every model request the beat made, the check’s included. Deleting beats keeps ' +
      'what they cost in the money totals, because that was really spent.'
    ].forEach(function (t) { about.appendChild(el('p', '', t)); });
    info.addEventListener('click', function () {
      about.hidden = !about.hidden;
      info.setAttribute('aria-expanded', about.hidden ? 'false' : 'true');
    });
    page.appendChild(about);

    // At the daily cap: why no beat runs today and when it beats again, first on the page.
    var paused = el('div', 'hb-capped');
    paused.id = 'beatsPaused';
    paused.setAttribute('role', 'status');
    paused.hidden = true;
    page.appendChild(paused);

    page.appendChild(filters());

    var stats = el('section', 'bt-analysis');
    stats.id = 'beatsAnalysis';
    stats.setAttribute('aria-label', 'Analysis of the beats shown');
    page.appendChild(stats);

    var tableCard = el('section', 'setting-card hb-card bt-card');
    tableCard.setAttribute('aria-label', 'The beats');
    var bar = el('div', 'bt-bar');
    bar.id = 'beatsBar';
    tableCard.appendChild(bar);
    var tab = el('div', 'bt-table-at');
    tab.id = 'beatsTable';
    tableCard.appendChild(tab);
    var pager = el('div', 'bt-pager');
    pager.id = 'beatsPager';
    tableCard.appendChild(pager);
    page.appendChild(tableCard);
    B.built = true;
  }

  function select(id, label, options, key, cls) {
    var lab = el('label', 'hb-field' + (cls ? ' ' + cls : ''));
    lab.appendChild(el('span', '', label));
    var pick = el('select');
    pick.id = id;
    options.forEach(function (o) {
      var op = el('option', '', o[1]);
      op.value = o[0];
      pick.appendChild(op);
    });
    pick.addEventListener('change', function () {
      if (key === 'work') { B.work = pick.value; B.f.page = '1'; refetch(); return; }
      B.f[key] = pick.value;
      B.f.page = '1';
      told();
      paint();
    });
    lab.appendChild(pick);
    return lab;
  }

  function filters() {
    var f = el('div', 'bt-filters');
    f.setAttribute('role', 'search');
    var s = el('label', 'hb-field bt-q');
    s.appendChild(el('span', '', 'Search'));
    var q = el('input');
    q.type = 'search';
    q.id = 'beatsSearch';
    q.placeholder = 'Words in what it said, why, duties, errors…';
    q.autocomplete = 'off';
    var soon = 0;
    q.addEventListener('input', function () {
      clearTimeout(soon);
      soon = setTimeout(function () {
        B.f.q = q.value.trim();
        B.f.page = '1';
        told(true);
        paint();
      }, 180);
    });
    s.appendChild(q);
    f.appendChild(s);

    f.appendChild(select('beatsWork', 'On', [['all', 'Every beat'], ['heartbeat', 'The heartbeat’s own duties']], 'work', 'bt-on'));
    [['From', 'start', 'beatsFrom'], ['To', 'end', 'beatsTo']].forEach(function (p) {
      var l = el('label', 'hb-field bt-day');
      l.appendChild(el('span', '', p[0]));
      var input = el('input');
      input.type = 'date';
      input.id = p[2];
      input.addEventListener('change', function () { B[p[1]] = input.value; B.f.page = '1'; refetch(); });
      l.appendChild(input);
      f.appendChild(l);
    });
    f.appendChild(select('beatsWoke', 'Woke by', WOKE, 'woke'));
    f.appendChild(select('beatsStage', 'Wake-up check', STAGE, 'stage'));
    f.appendChild(select('beatsKind', 'Decision', KIND, 'kind'));
    f.appendChild(select('beatsModel', 'Model', [['', 'Any']], 'model'));
    var c = el('label', 'hb-field bt-cost-f');
    c.appendChild(el('span', '', 'Cost at least ($)'));
    var cost = el('input');
    cost.type = 'number';
    cost.min = '0';
    cost.step = '0.01';
    cost.inputMode = 'decimal';
    cost.id = 'beatsCost';
    cost.addEventListener('change', function () { B.f.cost = cost.value; B.f.page = '1'; told(); paint(); });
    c.appendChild(cost);
    f.appendChild(c);
    var checks = el('div', 'bt-checks');
    [['beatsMsg', 'msg', 'Sent a message'], ['beatsErr', 'err', 'Had an error']].forEach(function (p) {
      var l = el('label', 'hb-check');
      var box = el('input');
      box.type = 'checkbox';
      box.id = p[0];
      box.addEventListener('change', function () { B.f[p[1]] = box.checked ? '1' : ''; B.f.page = '1'; told(); paint(); });
      l.appendChild(box);
      l.appendChild(el('span', '', p[2]));
      checks.appendChild(l);
    });
    var clear = button('Clear filters', 'bt-clear', function () {
      var keep = { sort: B.f.sort, dir: B.f.dir };
      B.f = readQuery('').f;
      B.f.sort = keep.sort; B.f.dir = keep.dir;
      var had = B.start || B.end || B.work !== 'all';
      B.start = ''; B.end = ''; B.work = 'all';
      if (had) refetch(); else { told(); paint(); }
    });
    clear.id = 'beatsClear';
    checks.appendChild(clear);
    f.appendChild(checks);
    return f;
  }

  /* The filters say what the state says: after Back, a reload or a link. */
  function syncControls() {
    var d = B.data;
    var work = $('beatsWork');
    if (work) {
      var opts = [['all', 'Every beat'], ['heartbeat', 'The heartbeat’s own duties']];
      ((d && d.works) || []).forEach(function (w) { opts.push([String(w.id), w.title]); });
      if (B.work !== 'all' && B.work !== 'heartbeat' && !opts.some(function (o) { return o[0] === B.work; })) {
        opts.push([B.work, 'Quest ' + B.work]);
      }
      if (work.options.length !== opts.length) {
        work.textContent = '';
        opts.forEach(function (o) { var op = el('option', '', o[1]); op.value = o[0]; work.appendChild(op); });
      }
      work.value = B.work;
    }
    var model = $('beatsModel');
    if (model && d) {
      var names = {};
      d.beats.forEach(function (b) {
        if (b.check_model) names[b.check_model] = true;
        b.decide_models.forEach(function (m) { names[m] = true; });
      });
      if (B.f.model) names[B.f.model] = true;
      var list = Object.keys(names).sort();
      if (model.options.length !== list.length + 1 || list.some(function (n, i) { return model.options[i + 1].value !== n; })) {
        model.textContent = '';
        [['', 'Any']].concat(list.map(function (n) { return [n, n]; })).forEach(function (o) {
          var op = el('option', '', o[1]); op.value = o[0]; model.appendChild(op);
        });
      }
    }
    var set = function (id, v) { var n = $(id); if (n && document.activeElement !== n) n.value = v; };
    set('beatsSearch', B.f.q);
    set('beatsFrom', B.start);
    set('beatsTo', B.end);
    set('beatsWoke', B.f.woke);
    set('beatsStage', B.f.stage);
    set('beatsKind', B.f.kind);
    set('beatsModel', B.f.model);
    set('beatsCost', B.f.cost);
    if ($('beatsMsg')) $('beatsMsg').checked = B.f.msg === '1';
    if ($('beatsErr')) $('beatsErr').checked = B.f.err === '1';
    var any = B.work !== 'all' || B.start || B.end || ['q', 'woke', 'stage', 'kind', 'model', 'msg', 'err', 'cost']
      .some(function (k) { return B.f[k]; });
    if ($('beatsClear')) $('beatsClear').hidden = !any;
  }

  function draw() {
    if (!B.open) return;
    if (!B.built || !$('beatsAnalysis')) build();
    var say = $('beatsSay');
    if (say) {
      say.textContent = B.error || B.said;
      say.className = 'hb-say' + (B.error ? ' bad' : '');
      say.hidden = !(B.error || B.said);
    }
    paint();
  }

  /* The analysis, the table and the pager, for the rows the filters pick. */
  var CAP_WHY = 'The cap limits what the AI behind the heartbeat may cost in a day, billed to the AI ' +
    'account on the Models page. Nothing more is spent on beats today, and you need do nothing: it starts ' +
    'again by itself.';

  /* The daily cap's pause, said plainly with what the cap is, or nothing. */
  function capped(box, words) {
    if (!box) return;
    box.textContent = '';
    box.hidden = !words;
    if (!words) return;
    box.appendChild(el('p', 'hb-capped-say', words));
    box.appendChild(el('p', 'hb-capped-why', CAP_WHY));
    box.appendChild(link('Change the daily cap', '/settings/heartbeat', 'hb-link'));
  }

  function paint() {
    if (!B.open || !B.built) return;
    syncControls();
    var d = B.data;
    var stats = $('beatsAnalysis'), tab = $('beatsTable'), bar = $('beatsBar'), pager = $('beatsPager');
    if (!stats || !tab) return;
    var keep = scroller(), top = keep ? keep.scrollTop : 0;
    stats.textContent = '';
    tab.textContent = '';
    bar.textContent = '';
    pager.textContent = '';
    if (!d) {
      if (!B.error) tab.appendChild(el('p', 'hb-empty', 'Reading the beats…'));
      return;
    }
    var rows = picked();
    $('beatsCount').textContent = count(rows.length, 'beat') + (rows.length !== d.beats.length ? ' of ' + d.beats.length.toLocaleString('en-GB') : '');
    capped($('beatsPaused'), d.cap_paused);
    if (d.capped) {
      stats.appendChild(el('p', 'hb-note', 'Only the newest ' + d.beats.length.toLocaleString('en-GB') + ' of ' +
        d.total.toLocaleString('en-GB') + ' beats are read. Pick days to read older ones.'));
    }
    if (rows.length) analysis(stats, rows, d);
    actions(bar, rows);
    if (!rows.length) {
      tab.appendChild(el('p', 'hb-empty', d.beats.length ? 'No beats match these filters.' : 'No beats yet.'));
    } else {
      var all = sorted(rows);
      var landAt = B.land ? all.findIndex(function (b) { return String(b.id) === B.land; }) : -1;
      if (landAt >= 0 && String(Math.floor(landAt / PAGE) + 1) !== String(B.f.page || '1')) {
        B.f.page = String(Math.floor(landAt / PAGE) + 1);
        told(true);
      }
      var pages = Math.max(1, Math.ceil(all.length / PAGE));
      var at = Math.min(pages, Math.max(1, parseInt(B.f.page, 10) || 1));
      tab.appendChild(table(all.slice((at - 1) * PAGE, at * PAGE), rows.length));
      if (pages > 1) pagerOf(pager, at, pages, all.length);
    }
    if (keep) keep.scrollTop = top;
    if (B.land) land(d);
  }

  /* The beat the address arrived at, brought into view once. Not among the days read, its
     own day is read; gone, the page says so. */
  function land(d) {
    var id = B.land;
    var row = /** @type {HTMLElement|null} */ (document.querySelector('#beatsTable tr[data-beat="' + id + '"]'));
    if (row) {
      B.land = '';
      row.scrollIntoView({ block: 'start' });
      return;
    }
    if (d.beats.some(function (b) { return String(b.id) === id; })) { B.land = ''; return; }
    if (B.landAsked === id) { B.land = ''; return; }
    B.landAsked = id;
    fetch('/api/heartbeat/beats/' + id, { credentials: 'same-origin', cache: 'no-store',
                                          headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
        if (B.land !== id) return;
        if (!r.ok || !j.day) {
          B.land = '';
          B.error = r.status === 404 ? 'Beat ' + id + ' is no longer kept.' : (j && j.error) || 'The server said ' + r.status + '.';
          draw();
          return;
        }
        B.details[id] = j;
        B.start = j.day;
        B.end = j.day;
        B.f.page = '1';
        refetch();
      }); })
      .catch(function () { B.land = ''; });
  }

  /* ---- the analysis ---- */

  function days(rows, d) {
    var first = rows[rows.length - 1].day, last = rows[0].day;
    rows.forEach(function (b) { if (b.day < first) first = b.day; if (b.day > last) last = b.day; });
    if (B.end && B.end > last && B.end <= d.today) last = B.end;
    if (B.start && B.start < first) first = B.start;
    var out = [], t = Date.UTC(+first.slice(0, 4), +first.slice(5, 7) - 1, +first.slice(8, 10));
    var end = Date.UTC(+last.slice(0, 4), +last.slice(5, 7) - 1, +last.slice(8, 10));
    while (t <= end && out.length < 1200) {
      out.push(new Date(t).toISOString().slice(0, 10));
      t += 86400000;
    }
    return out;
  }

  function analysis(box, rows, d) {
    var dayList = days(rows, d);
    var per = {};
    dayList.forEach(function (k) {
      per[k] = { code: 0, slept: 0, decided: 0, other: 0, cost: 0, tin: 0, nd: 0, msgs: 0, errs: 0 };
    });
    var t = { code: 0, slept: 0, woke: 0, direct: 0, decided: 0, cost: 0, costDecided: 0, msgs: 0, errs: 0,
              tin: 0, tout: 0, kinds: {}, checked: 0 };
    rows.forEach(function (b) {
      var p = per[b.day];
      if (!p) return;
      if (b.stage === 'code') { p.code++; t.code++; }
      else if (b.stage === 'slept') { p.slept++; t.slept++; }
      else if (b.decided) { p.decided++; t.decided++; }
      else p.other++;
      if (b.stage === 'woke') t.woke++;
      if (b.stage === 'direct') t.direct++;
      p.cost += b.cost || 0;
      t.cost += b.cost || 0;
      if (b.decided) {
        p.tin += b.tokens_in; p.nd++;
        t.costDecided += b.cost || 0;
        t.tin += b.tokens_in; t.tout += b.tokens_out;
      }
      p.msgs += b.messages; t.msgs += b.messages;
      if (b.errors.length) { p.errs++; t.errs++; }
      b.kinds.forEach(function (k) { t.kinds[k] = (t.kinds[k] || 0) + 1; });
    });
    t.checked = t.slept + t.woke;

    var tiles = el('div', 'bt-tiles');
    var tile = function (v, l, title) {
      var n = el('div', 'hb-stat bt-tile');
      n.appendChild(el('div', 'hb-stat-v', v));
      n.appendChild(el('div', 'hb-stat-l', l));
      if (title) n.title = title;
      tiles.appendChild(n);
    };
    tile(rows.length.toLocaleString('en-GB'), 'beats, over ' + count(dayList.length, 'day'));
    tile(pct(t.code, rows.length), 'skipped in code');
    tile(t.checked ? pct(t.woke, t.checked) : '-', 'passed on by the wake-up check',
      t.woke + ' of ' + t.checked + ' beats the check read');
    tile(t.decided.toLocaleString('en-GB'), 'reached a decision');
    tile(money(t.cost), 'spent in all');
    tile(t.decided ? money(t.costDecided / t.decided) : '-', 'a decision, on average');
    tile(t.decided ? tokens(Math.round(t.tin / t.decided)) : '-', 'tokens in a decision, on average');
    tile(t.msgs.toLocaleString('en-GB'), 'messages sent');
    tile(t.errs.toLocaleString('en-GB'), 'with an error');
    box.appendChild(tiles);

    var grid = el('div', 'bt-charts');
    var lim = d.limits || {};
    grid.appendChild(chart('Beats a day', dayList, [
      { key: 'decided', name: 'Reached a decision', cls: 's-dec' },
      { key: 'slept', name: 'Check: nothing to do', cls: 's-slept' },
      { key: 'code', name: 'Skipped in code', cls: 's-code' }
    ], per, function (v) { return String(v); }));
    grid.appendChild(chart('Spend a day', dayList, [{ key: 'cost', name: 'Spend', cls: 's-cost' }], per, money,
      lim.daily_cap ? { value: lim.daily_cap, words: 'The daily cap, ' + money(lim.daily_cap) + ' now' } : null));
    grid.appendChild(chart('Tokens in a decision, a day’s average', dayList,
      [{ key: 'tavg', name: 'Tokens in', cls: 's-tok' }], mapDays(per, function (p) { return { tavg: p.nd ? p.tin / p.nd : 0 }; }),
      function (v) { return tokens(Math.round(v)); }));
    grid.appendChild(chart('Messages a day', dayList, [{ key: 'msgs', name: 'Messages', cls: 's-msg' }], per,
      function (v) { return String(v); }, lim.per_day ? { value: lim.per_day, words: 'The limit, ' + lim.per_day + ' a day now' } : null));
    grid.appendChild(chart('Beats with an error, a day', dayList, [{ key: 'errs', name: 'Errors', cls: 's-err' }], per,
      function (v) { return String(v); }));
    grid.appendChild(kinds(t.kinds, t.decided));
    box.appendChild(grid);
    box.appendChild(models(rows));
  }

  function mapDays(per, fn) {
    var out = {};
    Object.keys(per).forEach(function (k) { out[k] = fn(per[k]); });
    return out;
  }

  var SVG = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    var n = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  /* Bars a day, stacked when there is more than one series, and a line for a limit. The
     bars stretch to the width they are given; the words around them are the page's, so
     they never stretch with them. */
  function chart(title, dayList, series, per, fmt, line) {
    var card = el('figure', 'bt-chart');
    var cap = el('figcaption', 'bt-chart-h', title);
    card.appendChild(cap);
    var most = 0, total = 0;
    dayList.forEach(function (k) {
      var sum = 0;
      series.forEach(function (s) { sum += per[k][s.key] || 0; });
      if (series[0].key !== 'tavg') total += sum;
      if (sum > most) most = sum;
    });
    if (line && line.value > most) most = line.value;
    if (series.length > 1) {
      var keyRow = el('div', 'bt-key');
      series.forEach(function (s) {
        var k = el('span', 'bt-key-i');
        k.appendChild(el('i', 'bt-sw ' + s.cls));
        k.appendChild(document.createTextNode(s.name));
        keyRow.appendChild(k);
      });
      card.appendChild(keyRow);
    }
    var plot = el('div', 'bt-plot');
    card.appendChild(plot);
    plot.appendChild(el('span', 'bt-ymax', most ? fmt(most) : ''));
    var n = dayList.length, W = n * 10, H = 100;
    var pic = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', role: 'img',
                           'aria-label': title });
    pic.appendChild(svg('line', { x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5, 'class': 'bt-base', 'vector-effect': 'non-scaling-stroke' }));
    var gap = n > 60 ? 1 : 2;
    dayList.forEach(function (k, i) {
      var y = H, words = [];
      var g = svg('g', {});
      series.forEach(function (s) {
        var v = per[k][s.key] || 0;
        if (series.length > 1 || s.key !== 'tavg' || v) words.push((series.length > 1 ? s.name + ': ' : '') + fmt(v));
        if (!v || !most) return;
        var h = Math.max(1, v / most * (H - 4));
        g.appendChild(svg('rect', { x: i * 10 + gap / 2, y: y - h, width: 10 - gap, height: h, 'class': 'bt-col ' + s.cls }));
        y -= h;
      });
      // The whole day's column answers a hover, not only its bar.
      var hit = svg('rect', { x: i * 10, y: 0, width: 10, height: H, 'class': 'bt-hit' });
      var tip = svg('title', {});
      tip.textContent = dayWords(k) + '\n' + (words.length ? words.join('\n') : 'nothing');
      hit.appendChild(tip);
      g.appendChild(hit);
      pic.appendChild(g);
    });
    if (line && most) {
      var ly = H - line.value / most * (H - 4);
      pic.appendChild(svg('line', { x1: 0, x2: W, y1: ly, y2: ly, 'class': 'bt-limit', 'vector-effect': 'non-scaling-stroke' }));
      var lk = el('div', 'bt-key');
      var li = el('span', 'bt-key-i');
      li.appendChild(el('i', 'bt-dash'));
      li.appendChild(document.createTextNode(line.words));
      lk.appendChild(li);
      card.insertBefore(lk, plot);
    }
    plot.appendChild(pic);
    var axis = el('div', 'bt-axis');
    axis.appendChild(el('span', '', dayWords(dayList[0])));
    if (n > 2) axis.appendChild(el('span', '', dayWords(dayList[Math.floor((n - 1) / 2)])));
    if (n > 1) axis.appendChild(el('span', '', dayWords(dayList[n - 1])));
    card.appendChild(axis);
    if (series[0].key !== 'tavg' && series.length === 1) {
      cap.appendChild(el('span', 'bt-chart-sum', fmt(total) + ' in all'));
    }
    return card;
  }

  function kinds(counts, decided) {
    var card = el('figure', 'bt-chart');
    card.appendChild(el('figcaption', 'bt-chart-h', 'What the decisions did'));
    if (!decided) {
      card.appendChild(el('p', 'hb-empty', 'No beat here reached a decision.'));
      return card;
    }
    var list = el('div', 'bt-hbars');
    var most = 0;
    KIND.slice(1).forEach(function (k) { most = Math.max(most, counts[k[0]] || 0); });
    KIND.slice(1).forEach(function (k) {
      var v = counts[k[0]] || 0;
      var row = el('div', 'bt-hbar' + (v ? '' : ' none'));
      row.appendChild(el('span', 'bt-hbar-n', k[1]));
      var track = el('span', 'bt-hbar-t');
      var fill = el('span', 'bt-hbar-f' + (k[0] === 'failed' ? ' s-err' : ''));
      fill.style.width = most ? (v / most * 100) + '%' : '0';
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el('span', 'bt-hbar-v', v + ' · ' + pct(v, decided)));
      list.appendChild(row);
    });
    card.appendChild(list);
    card.appendChild(el('p', 'hb-note', 'Of ' + count(decided, 'decision') + '. One decision can do more than one of these.'));
    return card;
  }

  /* Each model on each step: what it saw, what it did with it and what that cost. */
  function models(rows) {
    var card = el('figure', 'bt-chart bt-models');
    card.appendChild(el('figcaption', 'bt-chart-h', 'Each model, on each step'));
    var by = {};
    var add = function (step, name) {
      var key = step + '\u0000' + name;
      return by[key] || (by[key] = { step: step, model: name, beats: 0, woke: 0, slept: 0, cost: 0, tin: 0,
                                     tout: 0, took: 0, tookN: 0, errs: 0, msgs: 0, notes: 0, work: 0, asks: 0, nothing: 0 });
    };
    rows.forEach(function (b) {
      if (b.check_model) {
        var c = add('Wake-up check', b.check_model);
        c.beats++;
        if (b.stage === 'slept') c.slept++; else c.woke++;
        c.cost += b.check_cost || 0;
      }
      if (b.decided && b.decide_models.length) {
        var m = add('Decision', b.decide_models.join(' + '));
        m.beats++;
        m.cost += (b.cost || 0) - (b.check_cost || 0);
        m.tin += b.tokens_in; m.tout += b.tokens_out;
        if (b.took != null) { m.took += b.took; m.tookN++; }
        if (b.errors.length) m.errs++;
        m.msgs += b.messages;
        if (b.kinds.indexOf('note') >= 0) m.notes++;
        if (b.kinds.indexOf('work') >= 0) m.work++;
        if (b.kinds.indexOf('approval') >= 0) m.asks++;
        if (b.kinds.indexOf('nothing') >= 0) m.nothing++;
      }
    });
    var list = Object.keys(by).map(function (k) { return by[k]; });
    if (!list.length) {
      card.appendChild(el('p', 'hb-empty', 'No model was asked for these beats.'));
      return card;
    }
    list.sort(function (a, b) { return a.step < b.step ? 1 : a.step > b.step ? -1 : b.beats - a.beats; });
    var wrap = el('div', 'bt-scroll');
    var t = el('table', 'hb-table bt-mtable');
    var head = el('tr');
    ['Step', 'Model', 'Beats', 'What it made of them', 'Tokens in, average', 'Out, average', 'Cost, average', 'Cost in all',
     'Time, average', 'Errors'].forEach(function (h, i) {
      head.appendChild(el('th', i >= 2 && i !== 3 ? 'bt-n' : '', h));
    });
    var th = el('thead');
    th.appendChild(head);
    t.appendChild(th);
    var tb = el('tbody');
    list.forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', '', r.step));
      tr.appendChild(el('td', 'bt-model', r.model));
      tr.appendChild(el('td', 'bt-n', r.beats.toLocaleString('en-GB')));
      var made = r.step === 'Wake-up check'
        ? 'passed on ' + pct(r.woke, r.beats) + ', let sleep ' + pct(r.slept, r.beats)
        : [[r.nothing, 'nothing'], [r.notes, 'a note'], [r.msgs, 'a message'], [r.work, 'started work'], [r.asks, 'asked approval']]
          .filter(function (p) { return p[0]; }).map(function (p) { return p[1] + ' ' + pct(p[0], r.beats); }).join(', ');
      tr.appendChild(el('td', 'bt-made', made));
      tr.appendChild(el('td', 'bt-n', r.step === 'Decision' ? tokens(Math.round(r.tin / r.beats)) : '-'));
      tr.appendChild(el('td', 'bt-n', r.step === 'Decision' ? tokens(Math.round(r.tout / r.beats)) : '-'));
      tr.appendChild(el('td', 'bt-n', money(r.cost / r.beats)));
      tr.appendChild(el('td', 'bt-n', money(r.cost)));
      tr.appendChild(el('td', 'bt-n', r.tookN ? seconds(r.took / r.tookN) : '-'));
      tr.appendChild(el('td', 'bt-n', r.step === 'Decision' ? r.errs + ' · ' + pct(r.errs, r.beats) : '-'));
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    card.appendChild(wrap);
    return card;
  }

  /* ---- what is done to the rows ---- */

  function pickedIds() {
    return Object.keys(B.picked).filter(function (k) { return B.picked[k]; }).map(Number);
  }

  function massDelete() {
    var ids = pickedIds();
    if (!ids.length) return;
    var words = 'Delete ' + count(ids.length, 'beat') + '?\n\n' +
      (ids.length === 1 ? 'It goes' : 'They go') + ' from this table and from the history of the quest or duties ' +
      (ids.length === 1 ? 'it was' : 'they were') + ' on. ' +
      'What ' + (ids.length === 1 ? 'it' : 'they') + ' cost stays in the money totals and in today’s ' +
      'heartbeat spend, because that money was really spent. Only resetting or deleting the quest clears it.';
    if (!window.confirm(words)) return;
    B.said = '';
    call('POST', { act: 'delete', ids: ids, work: B.work, from: B.start, to: B.end });
  }

  function massClear() {
    var ids = pickedIds();
    if (!ids.length) return;
    B.said = '';
    call('POST', { act: 'clear_notes', ids: ids, work: B.work, from: B.start, to: B.end });
  }

  function actions(bar, rows) {
    var ids = pickedIds();
    bar.appendChild(el('span', 'bt-picked', ids.length ? count(ids.length, 'beat') + ' selected' : 'None selected'));
    var del = button('Delete selected', 'danger', massDelete, 'Delete the selected beats');
    del.id = 'beatsDelete';
    del.disabled = !ids.length || B.busy;
    bar.appendChild(del);
    var clear = button('Clear their notes', '', massClear,
      'Take the silent notes these beats left out of Rouh’s next conversation');
    clear.id = 'beatsClearNotes';
    clear.disabled = !ids.length || B.busy;
    bar.appendChild(clear);
    // A plain link, pressed by the person, so every browser saves it.
    var csv = el('a', 'ctl small bt-csv', 'Export CSV');
    csv.id = 'beatsCsv';
    if (B.csv) URL.revokeObjectURL(B.csv);
    B.csv = URL.createObjectURL(new Blob([csvOf(sorted(rows))], { type: 'text/csv;charset=utf-8' }));
    csv.href = B.csv;
    csv.download = 'heartbeat-beats' + (B.start ? '-from-' + B.start : '') + (B.end ? '-to-' + B.end : '') + '.csv';
    csv.title = 'The ' + count(rows.length, 'beat') + ' these filters pick, every column';
    if (!rows.length) csv.setAttribute('aria-disabled', 'true');
    bar.appendChild(csv);
  }

  function csvOf(rows) {
    var cell = function (v) {
      var s = v == null ? '' : String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    var head = ['id', 'beat', 'time', 'started_utc', 'day', 'on', 'woke_by', 'wake_up_check', 'why_it_stopped', 'decision',
                'ended_with', 'said', 'messages', 'approvals', 'jobs_started', 'duties', 'check_model',
                'decision_models', 'requests', 'tokens_in', 'tokens_out', 'cost_usd', 'check_cost_usd',
                'seconds', 'errors', 'tools'];
    var lines = [head.join(',')];
    rows.forEach(function (b) {
      lines.push([b.id, b.number == null ? '' : b.number, b.stamp, new Date(b.at * 1000).toISOString(), b.day, b.work.title,
        b.woke_words, b.stage_words, b.why, b.decision_words, b.ended_words, b.said, b.messages,
        b.approvals.map(function (a) { return (a.decision ? 'Decision ' + a.decision + ' ' : '') + a.what; }).join(' | '), b.started,
        b.duties.join('; '), b.check_model, b.decide_models.join('; '), b.requests, b.tokens_in, b.tokens_out,
        b.cost == null ? '' : b.cost, b.check_cost || 0, b.took == null ? '' : b.took, b.errors.join(' | '),
        b.tools.join('; ')].map(cell).join(','));
    });
    return '﻿' + lines.join('\r\n') + '\r\n';
  }

  /* ---- the table ---- */

  function table(rows, total) {
    var wrap = el('div', 'bt-scroll');
    var t = el('table', 'hb-table bt-table');
    var head = el('tr');
    var th0 = el('th', 'bt-pick');
    var all = el('input');
    all.type = 'checkbox';
    all.id = 'beatsAll';
    all.setAttribute('aria-label', 'Select every beat on this page');
    var n = rows.filter(function (b) { return B.picked[b.id]; }).length;
    all.checked = n > 0 && n === rows.length;
    all.indeterminate = n > 0 && n < rows.length;
    all.addEventListener('change', function () {
      rows.forEach(function (b) { if (all.checked) B.picked[b.id] = true; else delete B.picked[b.id]; });
      paint();
    });
    th0.appendChild(all);
    head.appendChild(th0);
    COLUMNS.forEach(function (c) {
      var th = el('th', c.cls);
      var on = B.f.sort === c.key;
      th.setAttribute('aria-sort', on ? (B.f.dir === 'asc' ? 'ascending' : 'descending') : 'none');
      var b = el('button', 'bt-sort' + (on ? ' on' : ''), c.head);
      b.type = 'button';
      b.title = c.title || 'Sort by ' + c.head.toLowerCase();
      if (on) b.appendChild(el('span', 'bt-arrow', B.f.dir === 'asc' ? '↑' : '↓'));
      b.addEventListener('click', function () {
        if (B.f.sort === c.key) B.f.dir = B.f.dir === 'asc' ? 'desc' : 'asc';
        else { B.f.sort = c.key; B.f.dir = c.num ? 'desc' : 'asc'; }
        B.f.page = '1';
        told();
        paint();
      });
      th.appendChild(b);
      head.appendChild(th);
    });
    var thead = el('thead');
    thead.appendChild(head);
    t.appendChild(thead);
    var tbody = el('tbody');
    rows.forEach(function (b) {
      var open = String(B.f.beat) === String(b.id);
      var tr = el('tr', 'bt-row ' + b.stage + ' ' + b.ended + (B.picked[b.id] ? ' picked' : '') + (open ? ' open' : ''));
      tr.dataset.beat = String(b.id);
      tr.tabIndex = 0;
      tr.setAttribute('aria-expanded', open ? 'true' : 'false');
      var td0 = el('td', 'bt-pick');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = !!B.picked[b.id];
      box.setAttribute('aria-label', 'Select the beat at ' + b.when + (b.number ? ', number ' + b.number : ''));
      box.addEventListener('change', function () {
        if (box.checked) B.picked[b.id] = true; else delete B.picked[b.id];
        paint();
      });
      td0.appendChild(box);
      tr.appendChild(td0);
      tr.appendChild(el('td', 'bt-num', b.number ? String(b.number) : '-'));
      tr.appendChild(el('td', 'bt-when', b.when));
      var tw = el('td', 'bt-work');
      if (b.work.href) tw.appendChild(link(b.work.title, b.work.href, 'hb-raised work'));
      else tw.textContent = b.work.title;
      tr.appendChild(tw);
      tr.appendChild(el('td', 'bt-woke', b.woke_words));
      tr.appendChild(el('td', 'bt-stage', b.stage_words));
      tr.appendChild(el('td', 'bt-dec', b.decision_words || '-'));
      var sum = el('td', 'bt-sum');
      sum.appendChild(el('div', 'bt-sum-text' + (b.said ? '' : ' why'), b.said || b.why || ''));
      tr.appendChild(sum);
      tr.appendChild(el('td', 'bt-n', b.messages || ''));
      tr.appendChild(el('td', 'bt-n', b.approvals.length || ''));
      tr.appendChild(el('td', 'bt-n', b.started || ''));
      tr.appendChild(el('td', 'bt-duties', b.duties.join(', ')));
      tr.appendChild(el('td', 'bt-model', b.check_model));
      tr.appendChild(el('td', 'bt-model', b.decide_models.join(', ')));
      var tin = el('td', 'bt-n', b.requests ? tokens(b.tokens_in) : '');
      if (b.requests) tin.title = b.tokens_in.toLocaleString('en-GB') + ' tokens in ' + count(b.requests, 'request');
      tr.appendChild(tin);
      tr.appendChild(el('td', 'bt-n', b.requests ? tokens(b.tokens_out) : ''));
      tr.appendChild(el('td', 'bt-n', money(b.cost)));
      tr.appendChild(el('td', 'bt-n', b.stage === 'code' ? '' : seconds(b.took)));
      var er = el('td', 'bt-err', b.errors.length ? b.errors.join('\n') : '');
      tr.appendChild(er);
      var toggle = function () {
        B.f.beat = String(B.f.beat) === String(b.id) ? '' : String(b.id);
        told();
        paint();
      };
      tr.addEventListener('click', function (e) {
        var tgt = /** @type {HTMLElement} */ (e.target);
        if (tgt.closest('a, button, input, label')) return;
        if (window.getSelection && String(window.getSelection())) return;
        toggle();
      });
      tr.addEventListener('keydown', function (e) {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === tr) { e.preventDefault(); toggle(); }
      });
      tbody.appendChild(tr);
      if (open) {
        var dr = el('tr', 'bt-detail-row');
        var dc = el('td', 'bt-detail-cell');
        dc.colSpan = COLUMNS.length + 1;
        var inner = el('div', 'bt-detail');
        inner.id = 'beatDetail' + b.id;
        dc.appendChild(inner);
        dr.appendChild(dc);
        tbody.appendChild(dr);
        openBeat(b.id);
        setTimeout(function () { paintDetail(b.id); }, 0);
      }
    });
    t.appendChild(tbody);
    wrap.appendChild(t);
    return wrap;
  }

  function pagerOf(box, at, pages, total) {
    var go = function (p) { B.f.page = String(p); told(); paint(); var t = $('beatsTable'); if (t) t.scrollIntoView({ block: 'start' }); };
    var prev = button('Previous', '', function () { go(at - 1); });
    prev.disabled = at <= 1;
    prev.id = 'beatsPrev';
    box.appendChild(prev);
    box.appendChild(el('span', 'bt-pages', ((at - 1) * PAGE + 1).toLocaleString('en-GB') + '–' +
      Math.min(total, at * PAGE).toLocaleString('en-GB') + ' of ' + total.toLocaleString('en-GB')));
    var next = button('Next', '', function () { go(at + 1); });
    next.disabled = at >= pages;
    next.id = 'beatsNext';
    box.appendChild(next);
  }

  /* ---- one beat, opened ---- */

  function block(title, parts) {
    var s = el('div', 'bt-d-block');
    s.appendChild(el('h5', 'hb-h5', title));
    parts.forEach(function (p) { if (p) s.appendChild(p); });
    return s;
  }

  function closed(summary, text, cls) {
    var d = el('details', 'bt-d-more' + (cls ? ' ' + cls : ''));
    d.appendChild(el('summary', '', summary));
    d.appendChild(el('pre', 'bt-pre', text));
    return d;
  }

  /* A waiting approval is a decision (`rouh/decisions.py`), drawn and answered the one way
     every question is (`decision.js`), as on the Heartbeat page. */
  var cardHost = null, cardsKept = {};
  function decisionHost() {
    if (!cardHost && window.RouhDecision) {
      cardHost = window.RouhDecision.fetchHost({
        go: function (href) { if (host().go) host().go(href); },
        changed: function (dec, what) {
          if (what === 'get') return;
          setTimeout(function () {
            Object.keys(B.details).forEach(function (k) {
              var x = B.details[k];
              if (x && x.decisions && Object.keys(x.decisions).some(function (a) { return x.decisions[a].id === dec.id; })) {
                delete B.details[k];
                if (String(B.f.beat) === k) openBeat(Number(k));
              }
            });
            load();
          }, 1200);
        }
      });
    }
    return cardHost;
  }

  /* Petar's yes or no to an approval with no decision of its own, then the beat read again. */
  function answerAsk(beat, a, word) {
    B.said = '';
    fetch('/api/heartbeat/answer', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                                     headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                                'X-CSRFToken': csrfToken() },
                                     body: JSON.stringify({ id: a.id, answer: word }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.ok) { B.error = ''; B.said = j.said || ''; } else B.error = j.error || 'The server said ' + r.status + '.';
        delete B.details[beat];
        if (String(B.f.beat) === String(beat)) openBeat(beat);
        load();
        draw();
      }); })
      .catch(function () { B.error = 'Rouh could not be reached. Check the connection and try again.'; draw(); });
  }

  function paintDetail(id) {
    var box = $('beatDetail' + id);
    if (!box) return;
    var d = B.details[id];
    var b = B.data && B.data.beats.filter(function (x) { return x.id === id; })[0];
    box.textContent = '';
    // As wide as the table's window, not the table, so it reads without scrolling sideways.
    var view = box.closest('.bt-scroll');
    if (view) box.style.width = Math.max(260, view.clientWidth - 4) + 'px';
    if (!d || d.loading) { box.appendChild(el('p', 'hb-empty', 'Reading the beat…')); return; }
    if (d.error) { box.appendChild(el('p', 'hb-say bad', d.error)); return; }
    var top = el('div', 'bt-d-links');
    if (b && b.chat) top.appendChild(link('Open the chat it ran in', b.chat, 'hb-raised work'));
    (d.runs || []).forEach(function (r) { top.appendChild(link('Run ' + r.id + (r.title ? ': ' + r.title : ''), r.href, 'hb-raised work')); });
    (d.tasks || []).forEach(function (t) { top.appendChild(link('Task ' + t.number + ' ' + t.title, t.href, 'hb-raised work')); });
    if (top.childNodes.length) box.appendChild(top);
    var cols = el('div', 'bt-d-cols');
    if (d.events && d.events.length) {
      var ul = el('ul', 'hb-events');
      d.events.forEach(function (e) { ul.appendChild(el('li', '', e)); });
      cols.appendChild(block('What woke it', [ul]));
    }
    if (d.reason) cols.appendChild(block(b && b.ended === 'failed' ? 'What went wrong' : 'Why it stopped', [el('p', 'bt-d-text', d.reason)]));
    if (d.said) cols.appendChild(block('What it said', [el('p', 'bt-d-text', d.said)]));
    if (d.duties && d.duties.length) {
      var du = el('ul', 'hb-events');
      d.duties.forEach(function (x) { var li = el('li', ''); li.appendChild(el('b', '', x.name + ': ')); li.appendChild(document.createTextNode(x.text)); du.appendChild(li); });
      cols.appendChild(block('Duties it acted on', [du]));
    }
    var asks = (d.approvals || []).filter(function (a) {
      return a.state === 'waiting' && d.decisions && d.decisions[a.id] && window.RouhDecision && decisionHost();
    });
    if (asks.length) {
      box.appendChild(block(asks.length === 1 ? 'It waits on your answer' : 'It waits on your answers',
        asks.map(function (a) {
          return window.RouhDecision.kept(cardsKept, d.decisions[a.id], decisionHost(),
            { place: 'page', here: location.pathname + location.search });
        })));
    }
    var rest = (d.approvals || []).filter(function (a) { return asks.indexOf(a) < 0; });
    if (rest.length) {
      var al = el('ul', 'hb-events');
      rest.forEach(function (a) {
        var li = el('li', '');
        li.appendChild(el('b', '', (a.decision ? 'Decision ' + a.decision + ' ' : '') + ({ waiting: 'Waiting', yes: 'Yes', no: 'No', failed: 'Yes, but it failed' }[a.state] || a.state) + ': '));
        li.appendChild(document.createTextNode(a.what + (a.to_whom ? ' To: ' + a.to_whom + '.' : '') + (a.cost ? ' Cost: ' + a.cost + '.' : '')));
        // Kept back from the decisions (nothing it runs is risky), it is answered here, as on
        // the Heartbeat page.
        if (a.state === 'waiting') {
          var row = el('div', 'hb-ask-do');
          row.appendChild(button('Yes', 'primary', function () { answerAsk(id, a, 'yes'); }, 'Run exactly this, and nothing else'));
          row.appendChild(button('No', '', function () { answerAsk(id, a, 'no'); }, 'Do not do it'));
          li.appendChild(row);
        }
        al.appendChild(li);
      });
      cols.appendChild(block('Approvals it asked for', [al]));
    }
    box.appendChild(cols);
    if (d.requests && d.requests.length) {
      var wrap = el('div', 'bt-scroll');
      var t = el('table', 'hb-table bt-rtable');
      var hr = el('tr');
      ['Step', 'Model', 'Tokens in', 'Cached', 'Out', 'Cost', 'Took', 'Answer'].forEach(function (h, i) {
        hr.appendChild(el('th', i >= 2 && i <= 6 ? 'bt-n' : '', h));
      });
      var th = el('thead');
      th.appendChild(hr);
      t.appendChild(th);
      var tb = el('tbody');
      d.requests.forEach(function (r) {
        var tr = el('tr', r.status === 'error' ? 'bad' : '');
        tr.appendChild(el('td', '', r.purpose));
        tr.appendChild(el('td', 'bt-model', r.model));
        tr.appendChild(el('td', 'bt-n', r.tokens_in.toLocaleString('en-GB')));
        tr.appendChild(el('td', 'bt-n', r.cached.toLocaleString('en-GB')));
        tr.appendChild(el('td', 'bt-n', r.tokens_out.toLocaleString('en-GB')));
        tr.appendChild(el('td', 'bt-n', money(r.cost)));
        tr.appendChild(el('td', 'bt-n', r.ms != null ? seconds(r.ms / 1000) : ''));
        tr.appendChild(el('td', 'bt-ans', r.status === 'error' ? r.error : r.text));
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      wrap.appendChild(t);
      box.appendChild(block('Every model request it made', [wrap]));
    }
    if (d.calls && d.calls.length) {
      var cl = el('ol', 'bt-calls');
      d.calls.forEach(function (c) {
        var li = el('li', c.held ? 'held' : '');
        li.appendChild(el('code', 'bt-call-n', c.name));
        if (c.held) li.appendChild(el('span', 'bt-held', 'refused: needs your yes'));
        if (c.args) li.appendChild(closed('What it asked', c.args));
        if (c.result) li.appendChild(closed('What came back', c.result));
        cl.appendChild(li);
      });
      box.appendChild(block('Tools the decision called', [cl]));
    }
    if (d.note) box.appendChild(closed('The note it was handed', d.note, 'bt-note'));
  }

  /* ---- shown and left ---- */

  function refetch() {
    B.said = '';
    B.data = null;
    B.sig = '';
    told();
    paint();
    load();
  }

  /** @param {string} [work] the quest's number, or 'heartbeat'; '' for all @param {string} [q] the rest of the address */
  function shownNow(work, q) {
    var want = work ? String(work) : 'all';
    var got = readQuery(q || '');
    var refilter = want !== B.work || got.start !== B.start || got.end !== B.end;
    if (got.f.beat && (got.f.beat !== B.f.beat || !B.open)) { B.land = got.f.beat; B.landAsked = ''; }
    B.f = got.f;
    if (refilter) {
      B.work = want; B.start = got.start; B.end = got.end;
      B.picked = {}; B.data = null; B.sig = '';
    }
    if (B.open && !refilter) { paint(); return; }
    if (!B.open) { B.built = false; B.said = ''; }
    B.open = true;
    draw();
    load();
    clearInterval(B.tick);
    B.tick = setInterval(function () { if (B.open && !B.busy && !document.hidden) load(); }, 30000);
  }

  function hiddenNow() {
    B.open = false;
    B.land = '';
    B.built = false;
    clearInterval(B.tick);
  }

  window.RouhBeats = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
