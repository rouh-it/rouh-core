/* Decisions, at /decisions: everything waiting on the person, from every part
   of Rouh that asks (`rouh/decisions.py`, `rouh/web/decisions.py`).

   Petar, 5 October 2026: "one model, one design, one place to look at them and
   make decisions. they can also be appearing contextually in their places but
   also in this one place."

   Petar, 18 October 2026: the page is a short list of lines, with no decision
   drawn on it. Each line is one link to the item's own page, where the
   decision is made with everything there is to know: a mail case at its step,
   a gene's page in Mutations, a goal step, a task, a run. Each says only what
   tells whether it needs him now: what it is, what a yes would do, what
   waiting costs, a few tags, Rouh's recommendation and its number to say,
   "Decision 42" (`decision_numbers.py`). The
   server writes each line (`decisions.line_of`) and Rouh's tool reads out the
   same ones, in the same order (`decisions.line_order`): what is dated or
   holds something up first, then the rest, newest first.

   A decision whose source has no page of its own that answers it opens its
   own, /decisions/<number>, which draws it in full (`decision.js`); one whose
   source does is forwarded there, so a Telegram link to a number still lands
   where it is answered. What he put off and what was answered lately are in
   brown toggles under the list.

   The layer, its address and its row in the sidebar are app/runs.js's
   (`decisionsOpen`), handed over through `window.RouhDecisionsHost`; the
   count on that row comes over the socket (`decisions`) and from here. */
(function () {
  'use strict';

  var D = { open: false, id: '', data: null, one: null, error: '', seq: 0, timer: 0, loading: false,
            find: '', missing: '', folds: {}, only: 'all' };

  /* What kind of thing each one is, at a glance (Petar, 18 October 2026: "I need to have a good
     visual sense what type they are. Gene mutation, person communication"): a family of
     sources, each with its colour and its name in the filter. The line's badge is its source's
     own icon and word (`line.kind`), in its family's colour. */
  var FAMILY = { genes: 'gene', nightly: 'gene', mail: 'person', delegate: 'person',
                 promise: 'person', meeting: 'person', after_meeting: 'person', task: 'work',
                 goal: 'work', approval: 'approval', run: 'run', job: 'run', conflict: 'run',
                 dream: 'memory', casefix: 'run', offline: 'run' };
  var FAMILIES = [['person', 'People'], ['gene', 'Genes'], ['work', 'Tasks and goals'],
                  ['approval', 'Approvals'], ['run', 'Runs and fixes'], ['memory', 'Memory']];
  function familyOf(d) { return FAMILY[d.source] || 'run'; }

  function host() { return window.RouhDecisionsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }

  var cardHost = null;
  function decisionHost() {
    if (!cardHost && window.RouhDecision) {
      cardHost = window.RouhDecision.fetchHost({
        go: function (href) { if (host().go) { host().go(href); } },
        changed: function (d, what) { if (what !== 'get') { soon(); } }
      });
    }
    return cardHost;
  }

  /* ---- numbers ---- */

  /* A decision's number as it was typed - "42", "#42", "Decision 42" - or ''. */
  function readNumber(text) {
    var m = /^(?:decision|no\.?|number)?\s*#?\s*0*([1-9]\d{0,6})$/i.exec(String(text || '').trim());
    return m ? m[1] : '';
  }
  function find(text) {
    var ref = String(text || '').trim();
    if (!ref) { return; }
    var number = readNumber(ref);
    if (!number) {
      D.find = ref;
      D.missing = 'Decisions are found by their number, such as 42.';
      draw();
      return;
    }
    D.find = '';
    if (host().open) { host().open(number); }
  }

  /* ---- reading ---- */

  function load() {
    var seq = ++D.seq;
    D.loading = true;
    return fetch('/api/decisions', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== D.seq) { return; }
          D.loading = false;
          if (!r.ok || !j) {
            D.error = (j && j.error) || 'Your decisions could not be read. Try again in a moment.';
          } else {
            D.error = '';
            D.data = j;
            count(j.counts || {});
          }
          if (D.open) { draw(); }
        });
      })
      .catch(function () {
        // With no connection, this device's copy of them (app/offline.js).
        var copy = window.RouhOffline && window.RouhOffline.decisions ? window.RouhOffline.decisions() : null;
        return Promise.resolve(copy).then(function (j) {
          if (seq !== D.seq) { return; }
          D.loading = false;
          if (j) { D.error = ''; D.data = j; }
          else { D.error = 'Rouh could not be reached. Check the connection and try again.'; }
          if (D.open) { draw(); }
        });
      });
  }

  /* One decision, for its own page at /decisions/<number>: read by its number, and acted
     on after by its row's own id, as every card is. */
  function loadOne(ref) {
    var seq = ++D.seq;
    return fetch('/api/decisions/at/' + encodeURIComponent(ref), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (out) { return { ok: r.ok, status: r.status, out: out }; });
      }, function () { return { ok: false, status: 0, out: {} }; })
      .then(function (r) {
        if (!r || seq !== D.seq || !D.open || D.id !== ref) { return; }
        var d = r.ok && r.out ? r.out.decision : null;
        if (!d) {
          D.one = null;
          D.missing = r.status === 404 ? 'There is no Decision ' + ref + '.'
            : 'That decision could not be read. Try again in a moment.';
          draw();
          return;
        }
        var line = d.line || {};
        // Its source's own page answers it: that is where it opens, in place of this
        // address, so Back goes to where he was before.
        // One Rouh cleared is drawn here, with Open again, whatever its source.
        if (line.own_page && line.href && d.status !== 'cleared' && host().forward) {
          host().forward(line.href);
          return;
        }
        D.one = d;
        D.missing = '';
        draw();
      });
  }

  function count(c) {
    if (host().counted) { host().counted(c.open || 0, c.now || 0); }
  }

  function soon() {
    clearTimeout(D.timer);
    D.timer = setTimeout(function () {
      if (!D.open) { return; }
      if (D.id) { loadOne(D.id); } else { load(); }
    }, 1200);
  }

  /* ---- the line ---- */

  /* The one drawing of a decision as a line, the same at every width: a single link to
     where it is decided. Long words wrap; nothing is cut. */
  function lineOf(d, done) {
    var l = d.line || {};
    var li = el('li', 'dl dl-f-' + familyOf(d) + (done ? ' dl-done' : ''));
    li.setAttribute('data-decision', String(d.id));
    var a = el('a', 'dl-a');
    var own = d.number ? '/decisions/' + d.number : '/decisions';
    var href = d.status === 'cleared' ? own : (l.href || own);
    a.href = href;
    a.setAttribute('data-inapp', '');
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
      if (!host().go) { return; }
      e.preventDefault();
      host().go(href);
    });
    var kind = el('span', 'dl-kind');
    if (window.RouhDecision && window.RouhDecision.sourceIcon) { kind.appendChild(window.RouhDecision.sourceIcon(d.source)); }
    kind.appendChild(el('span', '', l.kind || d.source_label || d.source));
    var top = el('span', 'dl-top');
    top.appendChild(kind);
    if (d.number) { top.appendChild(el('span', 'dq-number dl-number', 'Decision ' + d.number)); }
    a.appendChild(top);
    a.appendChild(el('span', 'dl-what', l.what || d.title));
    if (l.about) { a.appendChild(el('span', 'dl-about', l.about)); }
    if (done) {
      a.appendChild(row('dl-ended', '', ended(d)));
    } else {
      if (l.yes) { a.appendChild(row('dl-yes', 'A yes', l.yes)); }
      var wait = [l.due, l.wait].filter(Boolean).join(' · ');
      if (wait) { a.appendChild(row('dl-wait' + (l.due || l.blocks ? ' dl-held' : ''), 'Waiting', wait)); }
      if (d.status === 'snoozed' && d.snoozed_until) {
        a.appendChild(row('dl-wait', 'Put off', 'until ' + when(d.snoozed_until)));
      }
    }
    var foot = el('span', 'dl-foot');
    (l.tags || []).forEach(function (t) { foot.appendChild(el('span', 'dl-tag', t)); });
    if (l.rec && !done) {
      var rec = el('span', 'dl-rec');
      rec.appendChild(el('span', 'dl-k', 'Rouh: '));
      rec.appendChild(document.createTextNode(l.rec));
      foot.appendChild(rec);
    }
    if (foot.firstChild) { a.appendChild(foot); }
    li.appendChild(a);
    return li;
  }

  function row(cls, label, text) {
    var p = el('span', 'dl-row ' + cls);
    if (label) { p.appendChild(el('span', 'dl-k', label)); }
    p.appendChild(el('span', 'dl-v', text));
    return p;
  }

  /* How one in the history ended, in a few words. */
  function ended(d) {
    var said = (d.answer || {}).said || '';
    var words = { applied: said ? 'Answered: ' + said : 'Answered', dismissed: 'Dismissed',
                  expired: 'Ran out of time', withdrawn: 'Not asked any more',
                  cleared: 'Cleared by Rouh' }[d.status] || d.status;
    var where = d.channel && d.channel !== 'screen' && said ? ' (' + d.channel + ')' : '';
    var at = d.resolved_at || d.updated_at;
    return words + where + (at ? ', ' + when(at) : '');
  }

  function when(t) {
    try {
      var day = new Date(t * 1000);
      return day.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
        + ', ' + day.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch (err) { return ''; }
  }

  /* The order the server gives (`decisions.line_order`), kept for a copy read offline. */
  function ordered(list) {
    function key(d) {
      var l = d.line || {};
      var first = !!(d.due_at || l.blocks);
      return [first ? 0 : 1, first ? (d.due_at || Infinity) : 0, -(d.created_at || 0)];
    }
    return list.slice().sort(function (a, b) {
      var x = key(a), y = key(b);
      for (var i = 0; i < x.length; i++) { if (x[i] !== y[i]) { return x[i] < y[i] ? -1 : 1; } }
      return 0;
    });
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('decisionsBody');
    if (!body) { return; }
    var meta = $('decisionsMeta');
    if (meta) { meta.textContent = ''; }
    body.textContent = '';
    var page = el('div', 'dc-page');
    if (D.id) {
      drawOne(page);
    } else {
      drawList(page);
    }
    body.appendChild(page);
  }

  function drawList(page) {
    var data = D.data;
    var bar = el('div', 'dc-bar');
    bar.appendChild(findBox());
    page.appendChild(bar);
    say(page);
    if (!data) {
      if (!D.error) { page.appendChild(el('p', 'dc-quiet', 'Reading…')); }
      return;
    }
    var all = ordered(data.open || []);
    // The total under the page's name, the same number as on Now and on the circle: a
    // person counting a long list by scrolling is what the first trials found (4 November
    // 2026).
    var meta = $('decisionsMeta');
    if (meta) {
      var urgent = all.filter(function (d) { return d.urgency === 'now'; }).length;
      meta.textContent = !all.length ? 'Nothing waiting on you'
        : (all.length === 1 ? '1 decision' : all.length + ' decisions') + ' waiting on you'
          + (urgent ? ', ' + urgent + ' urgent' : '');
    }
    var bar2 = filter(all);
    if (bar2) { page.firstChild.insertBefore(bar2, page.firstChild.firstChild); }
    var waiting = all.filter(function (d) { return D.only === 'all' || familyOf(d) === D.only; });
    if (!all.length) {
      page.appendChild(el('p', 'dc-quiet', 'Nothing waits on you.'));
    } else if (!waiting.length) {
      page.appendChild(el('p', 'dc-quiet', 'None of these wait on you.'));
    } else {
      var ul = el('ul', 'dl-list');
      ul.setAttribute('aria-label', 'Waiting on you');
      waiting.forEach(function (d) { ul.appendChild(lineOf(d)); });
      page.appendChild(ul);
    }
    var later = data.snoozed || [];
    if (later.length) { page.appendChild(toggle('later', 'Put off till later', later, false)); }
    var past = data.history || [];
    if (past.length) { page.appendChild(toggle('history', 'Answered lately', past, true)); }
  }

  /* Show only one kind: each kind waiting, with its count, in its colour. */
  function filter(all) {
    var n = {};
    all.forEach(function (d) { var f = familyOf(d); n[f] = (n[f] || 0) + 1; });
    var kinds = FAMILIES.filter(function (f) { return n[f[0]]; });
    if (D.only !== 'all' && !n[D.only]) { D.only = 'all'; }
    if (kinds.length < 2) { return null; }
    var box = el('div', 'dc-filter');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Show only');
    [['all', 'All', all.length]].concat(kinds.map(function (f) { return [f[0], f[1], n[f[0]]]; }))
      .forEach(function (f) {
        var b = el('button', 'dc-chip' + (f[0] === 'all' ? '' : ' dl-f-' + f[0]) + (D.only === f[0] ? ' on' : ''));
        b.type = 'button';
        b.setAttribute('aria-pressed', D.only === f[0] ? 'true' : 'false');
        b.appendChild(el('span', 'dc-chip-dot'));
        b.appendChild(el('span', '', f[1]));
        b.appendChild(el('span', 'dc-chip-n', String(f[2])));
        b.addEventListener('click', function () { D.only = f[0]; draw(); });
        box.appendChild(b);
      });
    return box;
  }

  /* A brown toggle (AGENTS.md): closed until pressed, a line each inside. */
  function toggle(key, title, list, done) {
    var det = el('details', 'brown-toggle dc-toggle');
    det.open = !!D.folds[key];
    det.addEventListener('toggle', function () { D.folds[key] = det.open; });
    det.appendChild(el('summary', null, title + ' · ' + list.length));
    var inside = el('div', 'brown-toggle-body');
    var ul = el('ul', 'dl-list');
    list.forEach(function (d) { ul.appendChild(lineOf(d, done)); });
    inside.appendChild(ul);
    det.appendChild(inside);
    return det;
  }

  /* One decision on its own page: what has no page of its own elsewhere. */
  function drawOne(page) {
    var back = el('a', 'dc-back', '← Decisions');
    back.href = '/decisions';
    back.setAttribute('data-inapp', '');
    back.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
      if (!host().open) { return; }
      e.preventDefault();
      host().open('');
    });
    page.appendChild(back);
    say(page);
    if (!D.one) {
      if (!D.missing && !D.error) { page.appendChild(el('p', 'dc-quiet', 'Reading…')); }
      return;
    }
    page.appendChild(window.RouhDecision.card(D.one, decisionHost(), { place: 'page' }));
  }

  function say(page) {
    [D.error, D.missing].forEach(function (words, i) {
      if (!words) { return; }
      var p = el('p', 'dc-error', words);
      p.setAttribute('role', i ? 'status' : 'alert');
      page.appendChild(p);
    });
  }

  /* Find one by its number, as it is said out loud. */
  function findBox() {
    var form = el('form', 'dc-find');
    form.setAttribute('role', 'search');
    var input = el('input');
    input.id = 'decisionsFind';
    input.type = 'search';
    input.placeholder = 'e.g. 42';
    input.value = D.find;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('aria-label', 'Find a decision by its number');
    input.inputMode = 'numeric';
    input.setAttribute('enterkeyhint', 'go');
    form.appendChild(input);
    var go = el('button', 'ctl small', 'Find');
    go.type = 'submit';
    form.appendChild(go);
    form.addEventListener('submit', function (e) { e.preventDefault(); find(input.value); });
    input.addEventListener('input', function () { D.find = input.value; });
    return form;
  }

  /* ---- the layer ---- */

  /* At /decisions, the lines; at /decisions/<number>, that one. */
  function shown(id) {
    D.open = true;
    var was = D.id;
    D.id = id ? String(id) : '';
    D.missing = '';
    if (D.id !== was) { D.one = null; }
    draw();
    var body = $('decisionsBody');
    if (body && D.id !== was) { body.scrollTop = 0; }
    if (D.id) { loadOne(D.id); } else { load(); }
  }
  function hidden() {
    D.open = false;
    clearTimeout(D.timer);
  }
  /* The socket says the count moved: read the list again when it is open. */
  function moved() {
    if (D.open) { soon(); }
  }

  window.RouhDecisions = { shown: shown, hidden: hidden, moved: moved, reload: load };

  var x = $('decisionsClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
  // The count for the sidebar's row, once, at load; the socket keeps it after.
  // Once the conversation the page is opening is on the screen (index.html), and in the lane
  // kept for work nobody is waiting on (`rouh.dbwork.later`).
  if ($('decisionsRow')) {
    window.rouhLater(function () {
      fetch('/api/decisions', { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Rouh-Later': '1' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j) { if (!D.data) { D.data = j; } count(j.counts || {}); } })
        .catch(function () {});
    });
  }
}());
