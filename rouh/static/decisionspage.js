/* Decisions, at /decisions: everything waiting on the person, from every part
   of Rouh that asks (`rouh/decisions.py`, `rouh/web/decisions.py`).

   The owner, 5 October 2026: "one model, one design, one place to look at them and
   make decisions." The owner, 7 November 2026: "This is definitely something I
   avoid always ... redesign the page to serve me fully and quickly and easily
   and intuitively." So since then the page is a desk for clearing them, not a
   list of links (task 62, step 62-27, whose journeys this follows):

   - one decision in focus at a time, with the four things that decide it - what
     it is, what a yes does, what waiting costs, and Rouh's pick as the one big
     button - and the other answers quieter beside it; Later, You decide, Open
     and Dismiss in a quiet row; the whole card (`decision.js`) one press away,
     for items one by one, his own words or several answers;
   - the queue in lanes by the cost of waiting (holding work up, due soon, when
     you have a minute, can wait, probably stale), the same question asked many
     times folded into one row and answered once;
   - an answer moves to the next decision by itself, and a toast keeps Undo for
     the server's own window (`decisions.UNDO_SECONDS`);
   - the keys on a desk: j/k to move, y or Enter for Rouh's pick, 1-9 for the
     other answers, s later, d you decide, o open, e everything, x select, u undo,
     / a number, ? the list of keys;
   - a lane, or what is selected, cleared at once: "Rouh decides these" (only
     what can be changed later and has a pick) or Later for all of them;
   - when nothing waits, the page says so as a finished thing.

   The order inside a lane is the server's (`decisions.line_order`), the same
   order Rouh's tool reads them out in. A decision whose source has no page of
   its own that answers it still has its own page, /decisions/<number>, which
   draws it in full (`decision.js`); one whose source does is forwarded there.

   The layer, its address and its row in the sidebar are app/runs.js's
   (`decisionsOpen`), handed over through `window.RouhDecisionsHost`; the
   count on that row comes over the socket (`decisions`) and from here. */
(function () {
  'use strict';

  /** How long an answer can be taken back: the server's `UNDO_SECONDS`. */
  var UNDO_MS = 8000;

  var D = { open: false, id: '', data: null, one: null, error: '', seq: 0, timer: 0, loading: false,
            find: '', missing: '', view: 'desk', focus: '', confirming: '', later: false, full: '',
            selecting: false, picked: {}, toast: null, toastTimer: 0, tick: 0, busy: '',
            gone: {}, folds: {}, keys: false, cardError: '', finding: false };

  function host() { return window.RouhDecisionsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function btn(text, cls, fn, key) {
    var b = el('button', cls);
    b.type = 'button';
    b.appendChild(el('span', 'dc-bt', text));
    if (key) {
      var k = el('kbd', 'dc-key', key);
      k.setAttribute('aria-hidden', 'true');
      b.appendChild(k);
      b.setAttribute('aria-keyshortcuts', key === 'Y' ? 'y Enter' : key.toLowerCase());
    }
    b.addEventListener('click', fn);
    return b;
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
    D.finding = false;
    // One waiting here is put in focus on the desk; any other opens its own page.
    var g = groupOfNumber(Number(number));
    if (g && !D.id) {
      D.missing = '';
      D.view = 'desk';
      focusOn(g.key, true);
      return;
    }
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
            took(j);
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
          if (j) { D.error = ''; took(j); }
          else { D.error = 'Rouh could not be reached. Check the connection and try again.'; }
          if (D.open) { draw(); }
        });
      });
  }

  /* A fresh list: what was answered from here and has since left the list is forgotten. */
  function took(j) {
    D.data = j;
    var still = {};
    (j.open || []).forEach(function (d) { still[d.id] = true; });
    Object.keys(D.gone).forEach(function (id) { if (!still[id]) { delete D.gone[id]; } });
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

  function soon(ms) {
    clearTimeout(D.timer);
    D.timer = setTimeout(function () {
      if (!D.open) { return; }
      if (D.id) { loadOne(D.id); } else { load(); }
    }, ms == null ? 1200 : ms);
  }

  /* ---- acting ---- */

  function act(id, what, body) {
    return fetch('/api/decisions/' + encodeURIComponent(id) + '/act', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ act: what }, body || {}))
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (out) { return { ok: r.ok, status: r.status, out: out }; });
    }, function () {
      return { ok: false, status: 0, out: { error: 'Rouh could not be reached. Check the connection and try again.' } };
    });
  }

  /* The same act on every decision in a list, one after another; what came back for each. */
  function actAll(ds, what, body) {
    var got = [];
    return ds.reduce(function (p, d) {
      return p.then(function () {
        return act(d.id, what, typeof body === 'function' ? body(d) : body).then(function (r) { got.push({ d: d, r: r }); });
      });
    }, Promise.resolve()).then(function () { return got; });
  }

  /* After a press: the ones that went are hidden at once and the next one comes up; a toast
     keeps Undo. `undo` is the act that takes each one back, or '' when nothing can. */
  function after(g, got, words, undo) {
    D.busy = '';
    var ok = got.filter(function (x) { return x.r.ok; });
    var bad = got.filter(function (x) { return !x.r.ok; });
    if (bad.length && bad[0].r.status === 409 && bad[0].r.out && bad[0].r.out.confirm) {
      D.confirming = g ? g.key : '';
    } else if (bad.length) {
      D.cardError = (bad[0].r.out && bad[0].r.out.error) || 'That did not work. Try again.';
    }
    if (ok.length) {
      var next = nextAfter(ok.map(function (x) { return x.d.id; }));
      ok.forEach(function (x) { D.gone[x.d.id] = true; });
      D.confirming = '';
      D.later = false;
      D.full = '';
      if (!bad.length) { D.cardError = ''; }
      D.focus = next;
      // One question: its number, and how many copies went. Several: how many answers.
      var keys = {};
      ok.forEach(function (x) { keys[sameKey(x.d)] = true; });
      var answersN = Object.keys(keys).length;
      var n0 = answersN === 1 ? ok[0].d.number : 0;
      var tail = answersN > 1 ? ', ' + answersN + ' answers' : ok.length > 1 ? ', ' + ok.length + ' times' : '';
      say({ words: (n0 ? 'Decision ' + n0 + '. ' : '') + words + tail + '.',
            ids: ok.map(function (x) { return x.d.id; }), undo: undo });
      soon(600);
    }
    draw();
    focusCard();
  }

  function accept(g, optionId, confirmed) {
    if (D.busy) { return; }
    var lead = g.items[0];
    var o = optionOf(lead, optionId);
    if (!o) { return; }
    if (o.href) { go(o.href); return; }
    if (lead.gated && o.go && !confirmed) {
      D.confirming = g.key + ':' + o.id;
      dropToast();
      draw();
      var yes = document.querySelector('.dc-confirm .dc-yes');
      if (yes) { yes.focus(); }
      return;
    }
    D.busy = g.key;
    draw();
    var body = { choice: [o.id], text: '' };
    if (confirmed) { body.confirm = lead.risk; }
    actAll(g.items, 'answer', body).then(function (got) { after(g, got, 'Answered: ' + o.label, 'undo'); });
  }

  function delegate(groups) {
    var ds = [];
    groups.forEach(function (g) { if (canDelegate(g)) { ds = ds.concat(g.items); } });
    if (!ds.length || D.busy) { return; }
    D.busy = groups.length === 1 ? groups[0].key : 'many';
    draw();
    actAll(ds, 'delegate', {}).then(function (got) {
      after(groups.length === 1 ? groups[0] : null, got, groups.length === 1 ? 'Rouh decides it: '
        + (optionOf(groups[0].items[0], groups[0].items[0].recommended) || {}).label : 'Rouh decides them', 'undo');
    });
  }

  function snooze(groups, until, words) {
    var ds = [];
    groups.forEach(function (g) { ds = ds.concat(g.items); });
    if (!ds.length || D.busy) { return; }
    D.busy = groups.length === 1 ? groups[0].key : 'many';
    draw();
    actAll(ds, 'snooze', { until: until }).then(function (got) {
      after(groups.length === 1 ? groups[0] : null, got, 'Later: ' + words.toLowerCase(), 'wake');
    });
  }

  function dismiss(g) {
    if (D.busy || !g.items[0].can_dismiss) { return; }
    D.busy = g.key;
    draw();
    actAll(g.items, 'dismiss', {}).then(function (got) { after(g, got, 'Dismissed, nothing was done', ''); });
  }

  function undoToast() {
    var t = D.toast;
    if (!t || !t.undo || t.undoing) { return; }
    t.undoing = true;
    draw();
    actAll(t.ids.map(function (id) { return { id: id }; }), t.undo, {}).then(function (got) {
      var ok = got.filter(function (x) { return x.r.ok; }).length;
      t.ids.forEach(function (id) { delete D.gone[id]; });
      var bad = got.filter(function (x) { return !x.r.ok; })[0];
      say({ words: ok ? 'Undone. ' + (ok === 1 ? 'It waits' : 'They wait') + ' on you again.'
        : ((bad && bad.r.out && bad.r.out.error) || 'Too late to undo.'), ids: [], undo: '' });
      // Back in the queue, and in focus again once the list says so.
      load().then(function () {
        var g = ok && t.ids.length ? groupOfId(t.ids[0]) : null;
        if (g) { D.focus = g.key; draw(); }
        focusCard(true);
      });
    });
  }

  function dropToast() {
    clearTimeout(D.toastTimer);
    clearInterval(D.tick);
    D.toast = null;
    drawToast();
  }

  function say(t) {
    clearTimeout(D.toastTimer);
    clearInterval(D.tick);
    t.until = Date.now() + (t.undo ? UNDO_MS : 4000);
    D.toast = t;
    D.toastTimer = setTimeout(function () { D.toast = null; clearInterval(D.tick); drawToast(); }, t.until - Date.now());
    if (t.undo) { D.tick = setInterval(drawToast, 1000); }
    drawToast();
  }

  function go(href) { if (href && host().go) { host().go(href); } }

  /* When "later" means. */
  function at(h, days) {
    var t = new Date();
    t.setDate(t.getDate() + days);
    t.setHours(h, 0, 0, 0);
    return t.getTime() / 1000;
  }
  function laterTimes() {
    var evening = new Date().getHours() < 17;
    return [
      ['In an hour', Date.now() / 1000 + 3600],
      evening ? ['This evening', at(18, 0)] : null,
      ['Tomorrow morning', at(9, 1)],
      ['Next week', at(9, 7)]
    ].filter(Boolean);
  }

  /* ---- shaping the list ---- */

  function optionOf(d, id) {
    var os = d.options || [];
    for (var i = 0; i < os.length; i++) { if (os[i].id === id) { return os[i]; } }
    return null;
  }

  /* Rouh's pick can be given with one press: there is one, it is a plain answer, and the
     question is one answer, not several or words. */
  function oneTap(d) {
    var o = optionOf(d, d.recommended);
    return !!(o && !o.href && d.answer_type !== 'multi' && d.answer_type !== 'text'
              && d.answer_type !== 'date' && d.status !== 'answered');
  }
  function canDelegate(g) { return g.items.every(function (d) { return d.can_delegate; }); }

  var LANES = [
    ['blocks', 'Holding work up'],
    ['due', 'Due soon'],
    ['minute', 'When you have a minute'],
    ['wait', 'Can wait'],
    ['stale', 'Probably stale']
  ];
  /* Folded to their heading until opened: what can wait, and what is probably stale. */
  var FOLDED = { wait: true, stale: true };
  var LOW = { dream: true };

  function laneOf(d) {
    var l = d.line || {};
    if (d.status === 'failed' || l.blocks || d.urgency === 'now') { return 'blocks'; }
    if (d.stale && !d.gated) { return 'stale'; }
    if (d.due_at || d.urgency === 'today' || d.gated) { return 'due'; }
    if (d.urgency === 'whenever' || LOW[d.source]) { return 'wait'; }
    return 'minute';
  }

  /* The same question asked more than once is one issue: the same source, the same words
     and the same answers. One answer goes to all of them. */
  function sameKey(d) {
    var words = String(d.title || d.question || '').toLowerCase().replace(/\s+/g, ' ').trim();
    var opts = (d.options || []).map(function (o) { return o.id; }).join(',');
    return d.source + '|' + words + '|' + opts + '|' + (d.recommended || '');
  }

  /* The open decisions as issues, in lanes: [{key, lane, items: [decisions]}], in the
     server's order, the soonest due first in Due soon. */
  function shape() {
    var all = ((D.data && D.data.open) || []).filter(function (d) { return !D.gone[d.id]; });
    var by = {}, groups = [];
    all.forEach(function (d) {
      var k = sameKey(d);
      if (!by[k]) { by[k] = { key: 'g' + d.id, lane: laneOf(d), items: [] }; groups.push(by[k]); }
      by[k].items.push(d);
    });
    groups.forEach(function (g) {
      // The most pressing copy sets its lane.
      g.items.forEach(function (d) {
        var l = laneOf(d);
        if (laneIndex(l) < laneIndex(g.lane)) { g.lane = l; }
      });
    });
    var lanes = LANES.map(function (l) {
      var these = groups.filter(function (g) { return g.lane === l[0]; });
      if (l[0] === 'due') {
        these.sort(function (a, b) { return (a.items[0].due_at || Infinity) - (b.items[0].due_at || Infinity); });
      }
      return { key: l[0], label: l[1], groups: these, count: these.length };
    }).filter(function (l) { return l.groups.length; });
    return { all: all, lanes: lanes };
  }
  function laneIndex(k) { for (var i = 0; i < LANES.length; i++) { if (LANES[i][0] === k) { return i; } } return 9; }

  /* Every issue in the order the desk walks them: the lanes that are open, then those folded. */
  function walk(s) {
    var out = [];
    s.lanes.forEach(function (l) { if (!FOLDED[l.key] || D.folds[l.key]) { out = out.concat(l.groups); } });
    s.lanes.forEach(function (l) { if (FOLDED[l.key] && !D.folds[l.key]) { out = out.concat(l.groups); } });
    return out;
  }
  function current(s) {
    var order = walk(s);
    for (var i = 0; i < order.length; i++) { if (order[i].key === D.focus) { return order[i]; } }
    return order[0] || null;
  }
  function groupOfId(id) {
    var s = shape();
    var order = walk(s);
    for (var i = 0; i < order.length; i++) {
      if (order[i].items.some(function (d) { return d.id === id; })) { return order[i]; }
    }
    return null;
  }
  function groupOfNumber(n) {
    var order = walk(shape());
    for (var i = 0; i < order.length; i++) {
      if (order[i].items.some(function (d) { return d.number === n; })) { return order[i]; }
    }
    return null;
  }
  /* The issue to put in focus once these ids have gone: the one after, else the one before. */
  function nextAfter(ids) {
    var order = walk(shape());
    var at = -1;
    for (var i = 0; i < order.length; i++) {
      if (order[i].items.some(function (d) { return ids.indexOf(d.id) >= 0; })) { at = i; break; }
    }
    if (at < 0) { return D.focus; }
    for (var j = at + 1; j < order.length; j++) {
      if (!order[j].items.some(function (d) { return ids.indexOf(d.id) >= 0; })) { return order[j].key; }
    }
    for (var k = at - 1; k >= 0; k--) {
      if (!order[k].items.some(function (d) { return ids.indexOf(d.id) >= 0; })) { return order[k].key; }
    }
    return '';
  }

  /* About how long the list takes: a one-press pick a few seconds, a confirmed risk a few
     more, a question to read and answer in full most of a minute. */
  function seconds(groups) {
    return groups.reduce(function (n, g) {
      var d = g.items[0];
      return n + (oneTap(d) ? (d.gated ? 15 : 8) : 40);
    }, 0);
  }
  function minutes(s) {
    if (s < 50) { return 'under a minute'; }
    var m = Math.round(s / 60);
    return 'about ' + (m <= 1 ? '1 min' : m + ' min');
  }

  function today(t) {
    if (!t) { return false; }
    var a = new Date(t * 1000), b = new Date();
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }
  function clearedToday() {
    var these = ((D.data && D.data.going) || []).concat(((D.data && D.data.history) || []).filter(function (d) {
      // His own answers, and Rouh's for him: what a delegate decided is theirs.
      return today(d.resolved_at || d.answered_at) && !d.decided_by && !d.by_itself
        && ['applied', 'dismissed', 'answered', 'applying'].indexOf(d.status) >= 0;
    }));
    return folds(these).length;
  }
  /* The same question answered the same way at once is one answer, "4 times". */
  function folds(list) {
    var rows = [];
    list.forEach(function (d) {
      var last = rows[rows.length - 1];
      var said = (d.answer || {}).said || d.status;
      if (last && sameKey(last.d) === sameKey(d) && last.said === said && last.d.status === d.status) {
        last.n += 1;
      } else {
        rows.push({ d: d, said: said, n: 1 });
      }
    });
    return rows;
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('decisionsBody');
    if (!body) { return; }
    var meta = $('decisionsMeta');
    if (meta) { meta.textContent = ''; }
    var had = body.scrollTop;
    var queue = body.querySelector('.dc-queue');
    var qs = queue ? queue.scrollTop : 0;
    body.textContent = '';
    var page = el('div', 'dc-page');
    if (D.id) {
      drawOne(page);
    } else if (D.view === 'history') {
      drawHistory(page);
    } else {
      drawDesk(page);
    }
    body.appendChild(page);
    body.scrollTop = had;
    var q2 = body.querySelector('.dc-queue');
    if (q2) { q2.scrollTop = qs; }
    drawToast();
  }

  function drawDesk(page) {
    var data = D.data;
    page.appendChild(head());
    say2(page);
    if (!data) {
      if (!D.error) { page.appendChild(el('p', 'dc-quiet', 'Reading your decisions…')); }
      return;
    }
    var s = shape();
    var meta = $('decisionsMeta');
    if (meta) { meta.textContent = verdict(s); }
    if (!s.all.length) {
      page.appendChild(finished());
      return;
    }
    var g = current(s);
    if (g) { D.focus = g.key; }
    var desk = el('div', 'dc-desk');
    desk.appendChild(focusCard_(g, s));
    desk.appendChild(queueOf(s, g));
    page.appendChild(desk);
  }

  /* The line under the page's name: how many, how long, and what holds work up. The number
     is the same as on the sidebar's row and on Now (`counts.open`). */
  function verdict(s) {
    var n = s.all.length;
    if (!n) { return 'Nothing waits on you'; }
    var issues = walk(s).length;
    var repeats = walk(s).filter(function (g) { return g.items.length > 1; });
    var said = repeats.map(function (g) { return g.items.length + ' times'; });
    if (!repeats.length) { return (n === 1 ? '1 decision waits' : n + ' decisions wait') + ' on you'; }
    return repeats.length === 1 ? 'One decision is asked ' + said[0] + ', answered once'
      : repeats.length + ' decisions are asked more than once (' + said.join(', ') + '), each answered once';
  }

  /* The top of the desk: progress, and the ways to the rest. */
  function head() {
    var bar = el('div', 'dc-head');
    var s = D.data ? shape() : { all: [], lanes: [] };
    var done = D.data ? clearedToday() : 0;
    var order = D.data ? walk(s) : [];
    var left = order.length;
    var prog = el('div', 'dc-progress');
    var blocks = 0;
    s.lanes.forEach(function (l) { if (l.key === 'blocks') { blocks = l.groups.length; } });
    var words = el('p', 'dc-progress-words');
    if (left) {
      var nd = s.all.length;
      words.appendChild(el('strong', null, (left === 1 ? '1 answer' : left + ' answers') + ' to give'
        + (nd > left ? ' (' + nd + ' decisions)' : '') + ', ' + minutes(seconds(order))));
      words.appendChild(document.createTextNode(
        (blocks ? ' · ' + blocks + ' holding work up' : '') + (done ? ' · ' + done + ' answered today' : '')));
    } else {
      words.appendChild(el('strong', null, done ? (done === 1 ? '1 answer' : done + ' answers') + ' given today' : 'All clear'));
    }
    prog.appendChild(words);
    var track = el('div', 'dc-track');
    track.setAttribute('role', 'progressbar');
    track.setAttribute('aria-label', 'Cleared today');
    track.setAttribute('aria-valuemin', '0');
    track.setAttribute('aria-valuemax', String(done + left));
    track.setAttribute('aria-valuenow', String(done));
    var fill = el('span', 'dc-fill');
    fill.style.width = (done + left ? Math.round(100 * done / (done + left)) : 100) + '%';
    track.appendChild(fill);
    prog.appendChild(track);
    bar.appendChild(prog);

    var tools = el('div', 'dc-tools');
    if (D.finding) {
      tools.appendChild(findBox());
    } else {
      tools.appendChild(btn('Go to number', 'dc-tool', function () { D.finding = true; draw(); focusFind(); }, '/'));
    }
    var past = folds(((D.data && D.data.going) || []).concat((D.data && D.data.history) || [])).length;
    var lately = btn('Decided lately', 'dc-tool', function () { D.view = 'history'; draw(); top(); });
    if (past) { lately.appendChild(el('span', 'dc-n', String(Math.min(past, 40)))); }
    tools.appendChild(lately);
    var keys = btn('Keys', 'dc-tool dc-desk-only', function () { D.keys = !D.keys; draw(); }, '?');
    keys.setAttribute('aria-expanded', D.keys ? 'true' : 'false');
    tools.appendChild(keys);
    bar.appendChild(tools);
    if (D.keys) { bar.appendChild(keyList()); }
    return bar;
  }

  function keyList() {
    var box = el('div', 'dc-keys');
    box.setAttribute('aria-label', 'Keys on this page');
    [['J  K', 'next and previous'], ['Y  Enter', "Rouh's pick"], ['1 - 9', 'another answer'],
     ['S, then 1 - 4', 'later, and when'], ['D', 'you decide'], ['O', 'open where it came from'], ['E', 'show everything'],
     ['X', 'select'], ['U', 'undo'], ['/', 'go to a number'], ['Esc', 'close what is open']]
      .forEach(function (k) {
        var row = el('span', 'dc-keyrow');
        row.appendChild(el('kbd', 'dc-key', k[0]));
        row.appendChild(el('span', null, k[1]));
        box.appendChild(row);
      });
    return box;
  }

  /* The page when nothing waits: finished, with what comes next. */
  function finished() {
    var box = el('section', 'dc-done');
    box.setAttribute('aria-label', 'Nothing waits on you');
    var mark = el('span', 'dc-done-mark');
    mark.setAttribute('aria-hidden', 'true');
    box.appendChild(mark);
    box.appendChild(el('h4', 'dc-done-title', 'Nothing waits on you.'));
    var done = clearedToday();
    var lines = [];
    if (done) { lines.push((done === 1 ? 'One answer' : done + ' answers') + ' given today; ' + (done === 1 ? 'it is' : 'they are') + ' in Decided lately.'); }
    var later = ((D.data && D.data.snoozed) || []).slice().sort(function (a, b) {
      return (a.snoozed_until || 0) - (b.snoozed_until || 0);
    });
    if (later.length) {
      var nLater = {};
      later.forEach(function (d) { nLater[sameKey(d)] = true; });
      var kept = Object.keys(nLater).length;
      lines.push((kept === 1 ? 'One you put off comes back ' : kept + ' you put off; the first comes back ')
        + when(later[0].snoozed_until) + '.');
    }
    var theirs = (D.data && D.data.theirs) || [];
    if (theirs.length) { lines.push(theirs.length + (theirs.length === 1 ? ' is' : ' are') + ' with your delegates.'); }
    if (!lines.length) { lines.push('Rouh brings the next one here, and to your phone if it is urgent.'); }
    lines.forEach(function (t) { box.appendChild(el('p', 'dc-done-line', t)); });
    var after = el('div', 'dc-after');
    if (later.length) { after.appendChild(folded('later', 'Put off', later, laterRow)); }
    if (theirs.length) { after.appendChild(folded('theirs', 'Your delegates decide', theirs, theirRow)); }
    if (after.firstChild) { box.appendChild(after); }
    return box;
  }

  /* ---- the card in focus ---- */

  function focusCard_(g, s) {
    // With Later open, 1 to 4 are its times: the answers' number keys step aside.
    var card = el('section', 'dc-card' + (D.later ? ' dc-later-open' : ''));
    card.id = 'decisionsFocus';
    card.tabIndex = -1;
    if (!g) { return card; }
    var d = g.items[0];
    var l = d.line || {};
    card.setAttribute('aria-label', 'Decision ' + (d.number || '') + ': ' + (l.what || d.title));
    card.setAttribute('data-decision', String(d.id));

    // Where it is in the walk, for the phone where the queue is below.
    var order = walk(s);
    var place = order.indexOf(g) + 1;
    var top = el('div', 'dc-card-top');
    var kind = el('span', 'dc-kind');
    if (window.RouhDecision && window.RouhDecision.sourceIcon) { kind.appendChild(window.RouhDecision.sourceIcon(d.source)); }
    kind.appendChild(el('span', null, l.kind || d.source_label || d.source));
    top.appendChild(kind);
    if (d.number) { top.appendChild(el('span', 'dc-num', 'Decision ' + d.number)); }
    if (d.status === 'failed') { top.appendChild(flag('dc-flag-bad', 'Did not go through')); }
    else if (l.blocks) { top.appendChild(flag('dc-flag-warn', 'Holding work up')); }
    if (d.gated) { top.appendChild(flag('dc-flag-bad', d.risk_words || 'Needs your word')); }
    if (l.due) { top.appendChild(flag(d.due_at < Date.now() / 1000 ? 'dc-flag-warn' : 'dc-flag', l.due)); }
    top.appendChild(el('span', 'dc-place', place + ' of ' + order.length));
    card.appendChild(top);

    var h = el('h4', 'dc-what', l.what || d.title);
    h.id = 'decisionsFocusTitle';
    card.appendChild(h);
    if (l.about) { card.appendChild(el('p', 'dc-about', l.about)); }

    var facts = el('dl', 'dc-facts');
    fact(facts, 'Yes does', l.yes || d.then || '');
    var wait = [l.wait, d.stale].filter(Boolean).join(' ');
    fact(facts, 'Waiting costs', wait || (d.urgency === 'whenever' ? 'Nothing much; it can wait.' : ''));
    if (g.items.length > 1) {
      fact(facts, 'Asked ' + g.items.length + ' times', 'One answer goes to all of them: '
        + g.items.map(function (x) { return x.context || ('Decision ' + x.number); }).join(', ') + '.');
    }
    if (d.decider) { fact(facts, 'Delegate', d.decider + ' may decide this too.'); }
    if (!facts.firstChild) { fact(facts, 'The question', d.question); }
    card.appendChild(facts);
    (d.delegate_notes || []).forEach(function (n) {
      var p = el('p', 'dc-note');
      p.appendChild(el('strong', null, (n.by || n.name || 'Your delegate') + ': '));
      p.appendChild(document.createTextNode(n.text || n.words || ''));
      card.appendChild(p);
    });

    // Show everything: the whole card replaces the quick answers, so nothing is offered twice.
    var whole = D.full === g.key && window.RouhDecision;
    if (!whole) { card.appendChild(answers(g)); }

    if (D.cardError && D.focus === g.key) {
      var err = el('p', 'dc-error', D.cardError);
      err.setAttribute('role', 'alert');
      card.appendChild(err);
    }
    if (whole) {
      card.appendChild(btn('Show less', 'dc-q dc-less', function () { D.full = ''; draw(); focusCard(); }, 'E'));
    } else {
      card.appendChild(quiet(g));
    }
    if (whole) {
      var full = el('div', 'dc-full');
      full.appendChild(window.RouhDecision.card(d, decisionHost(), { place: 'page' }));
      card.appendChild(full);
    }
    return card;
  }

  function flag(cls, text) { return el('span', 'dc-flag ' + cls, text); }
  function fact(dl, k, v) {
    if (!v) { return; }
    var row = el('div', 'dc-fact');
    row.appendChild(el('dt', null, k));
    row.appendChild(el('dd', null, v));
    dl.appendChild(row);
  }

  /* Rouh's pick as the one big button, its reason under it, and the other answers beside. */
  function answers(g) {
    var d = g.items[0];
    var box = el('div', 'dc-answers');
    var busy = D.busy === g.key;
    var conf = D.confirming && D.confirming.indexOf(g.key + ':') === 0 ? D.confirming.slice(g.key.length + 1) : '';
    if (conf) {
      var o = optionOf(d, conf) || {};
      var c = el('div', 'dc-confirm');
      c.setAttribute('role', 'group');
      c.setAttribute('aria-label', 'Confirm');
      c.appendChild(el('p', 'dc-confirm-words', (d.risk_note || d.risk_words || 'This cannot be taken back.')
        + (g.items.length > 1 ? ' (' + g.items.length + ' times)' : '')));
      var yes = btn({ money: 'Yes, spend it', sending: 'Yes, send it', publishing: 'Yes, publish it' }[d.risk]
        || 'Yes, I understand', 'dc-main dc-yes', function () { accept(g, o.id, true); }, 'Y');
      yes.disabled = busy;
      c.appendChild(yes);
      c.appendChild(btn('Cancel', 'dc-alt', function () { D.confirming = ''; draw(); focusCard(); }, 'Esc'));
      box.appendChild(c);
      return box;
    }
    var rec = oneTap(d) ? optionOf(d, d.recommended) : null;
    if (rec) {
      var main = btn(rec.label, 'dc-main', function () { accept(g, rec.id); }, 'Y');
      main.disabled = busy;
      var label = main.querySelector('.dc-bt');
      if (busy) { label.textContent = 'Sending…'; }
      // "Rouh's pick" inside the button, over its words: one target, and the card shorter.
      var said = el('span', 'dc-main-words');
      said.appendChild(el('span', 'dc-pick-k', "Rouh's pick"));
      main.insertBefore(said, label);
      said.appendChild(label);
      var pick = el('div', 'dc-pick');
      pick.appendChild(main);
      if (d.recommended_why) { pick.appendChild(el('p', 'dc-why', d.recommended_why)); }
      else if (rec.detail) { pick.appendChild(el('p', 'dc-why', rec.detail)); }
      box.appendChild(pick);
    } else {
      var why = d.answer_type === 'multi' ? 'This one takes more than one answer.'
        : d.answer_type === 'text' || !(d.options || []).length ? 'This one wants your own words.'
        : !d.recommended ? 'Rouh has no pick for this one; it is yours.'
        : "Rouh's pick opens a page.";
      box.appendChild(el('p', 'dc-nopick', why));
    }
    var others = alternatives(d, rec);
    if (others.length || !rec) {
      var alts = el('div', 'dc-alts');
      alts.setAttribute('role', 'group');
      alts.setAttribute('aria-label', rec ? 'Other answers' : 'Answers');
      others.forEach(function (o, i) {
        var b = btn(o.label, 'dc-alt', function () { accept(g, o.id); }, i < 9 ? String(i + 1) : '');
        b.disabled = busy;
        if (o.detail) { b.title = o.detail; }
        alts.appendChild(b);
      });
      if (d.answer_type === 'multi' || d.answer_type === 'text' || (d.allow_other && !others.length)
          || (d.items && d.items.length)) {
        alts.appendChild(btn(d.items && d.items.length ? 'One by one' : 'Answer in full', 'dc-alt',
          function () { D.full = D.full === g.key ? '' : g.key; draw(); }, 'E'));
      }
      box.appendChild(alts);
    }
    return box;
  }

  /* The answers other than the pick, plain ones in a question that takes one answer. */
  function alternatives(d, rec) {
    if (d.answer_type === 'multi') { return []; }
    return (d.options || []).filter(function (o) { return !rec || o.id !== rec.id; });
  }

  /* Later, You decide, Open, Dismiss and Show everything: quiet, in one row. */
  function quiet(g) {
    var d = g.items[0];
    var row = el('div', 'dc-quietrow');
    var later = btn('Later', 'dc-q', function () { D.later = !D.later; draw(); laterFocus(); }, 'S');
    later.setAttribute('aria-expanded', D.later ? 'true' : 'false');
    later.setAttribute('aria-haspopup', 'true');
    row.appendChild(later);
    if (canDelegate(g)) {
      var dl = btn('You decide', 'dc-q', function () { delegate([g]); }, 'D');
      dl.title = 'Rouh answers with its pick. Only for what can be changed later.';
      row.appendChild(dl);
    }
    var href = (d.line || {}).href;
    if (href) { row.appendChild(btn('Open', 'dc-q', function () { go(href); }, 'O')); }
    row.appendChild(btn(D.full === g.key ? 'Show less' : 'Show everything', 'dc-q',
      function () { D.full = D.full === g.key ? '' : g.key; draw(); }, 'E'));
    if (d.can_dismiss) { row.appendChild(btn('Dismiss', 'dc-q', function () { dismiss(g); })); }
    var wrap = el('div', 'dc-quietwrap');
    wrap.appendChild(row);
    if (D.later) {
      var m = el('div', 'dc-latermenu');
      m.setAttribute('role', 'group');
      m.setAttribute('aria-label', 'Later, until');
      laterTimes().forEach(function (t, i) {
        m.appendChild(btn(t[0], 'dc-q dc-when', function () { snooze([g], t[1], t[0]); }, String(i + 1)));
      });
      wrap.appendChild(m);
    }
    return wrap;
  }

  /* ---- the queue ---- */

  function queueOf(s, g) {
    var q = el('nav', 'dc-queue');
    q.setAttribute('aria-label', 'The queue');
    var qh = el('div', 'dc-qhead');
    qh.appendChild(el('h4', 'dc-qtitle', 'The queue'));
    var sel = btn(D.selecting ? 'Done selecting' : 'Select', 'dc-q dc-small', function () {
      D.selecting = !D.selecting;
      D.picked = {};
      draw();
    }, 'X');
    sel.setAttribute('aria-pressed', D.selecting ? 'true' : 'false');
    qh.appendChild(sel);
    q.appendChild(qh);
    if (D.selecting) { q.appendChild(bulkBar(s)); }
    s.lanes.forEach(function (lane) {
      var sec = el('section', 'dc-lane dc-lane-' + lane.key);
      var lh = el('div', 'dc-lhead');
      var folded = FOLDED[lane.key] && !D.folds[lane.key];
      var title = el('button', 'dc-ltitle');
      title.type = 'button';
      title.setAttribute('aria-expanded', folded ? 'false' : 'true');
      title.appendChild(el('span', 'dc-chev', folded ? '+' : '−'));
      title.appendChild(el('span', null, lane.label));
      title.appendChild(el('span', 'dc-n', String(lane.count)));
      title.addEventListener('click', function () { D.folds[lane.key] = folded; draw(); });
      lh.appendChild(title);
      if (lane.key === 'wait' || lane.key === 'stale') { lh.appendChild(laneActs(lane)); }
      sec.appendChild(lh);
      if (!folded) {
        var ul = el('ul', 'dc-rows');
        lane.groups.forEach(function (x) { ul.appendChild(rowOf(x, x === g)); });
        sec.appendChild(ul);
      }
      q.appendChild(sec);
    });
    var later = (D.data && D.data.snoozed) || [];
    if (later.length) { q.appendChild(folded('later', 'Put off', later, laterRow)); }
    var theirs = (D.data && D.data.theirs) || [];
    if (theirs.length) { q.appendChild(folded('theirs', 'Your delegates decide', theirs, theirRow)); }
    return q;
  }

  function laneActs(lane) {
    var box = el('span', 'dc-lacts');
    var mine = lane.groups.filter(canDelegate);
    if (mine.length) {
      box.appendChild(btn('Rouh decides ' + mine.length, 'dc-q dc-small', function () { delegate(mine); }));
    }
    box.appendChild(btn('Later, all', 'dc-q dc-small', function () {
      snooze(lane.groups, at(9, 7), 'Next week');
    }));
    return box;
  }

  function rowOf(g, on) {
    var d = g.items[0];
    var l = d.line || {};
    var li = el('li', 'dc-row' + (on ? ' on' : ''));
    if (D.selecting) {
      var box = el('input', 'dc-check');
      box.type = 'checkbox';
      box.checked = !!D.picked[g.key];
      box.setAttribute('aria-label', 'Select ' + (l.what || d.title));
      box.addEventListener('change', function () {
        if (box.checked) { D.picked[g.key] = true; } else { delete D.picked[g.key]; }
        draw();
      });
      li.appendChild(box);
    }
    var b = el('button', 'dc-rowbtn');
    b.type = 'button';
    if (on) { b.setAttribute('aria-current', 'true'); }
    var t = el('span', 'dc-rowtop');
    var k = el('span', 'dc-rowkind');
    if (window.RouhDecision && window.RouhDecision.sourceIcon) { k.appendChild(window.RouhDecision.sourceIcon(d.source)); }
    k.appendChild(el('span', null, l.kind || d.source_label || d.source));
    t.appendChild(k);
    if (d.number) { t.appendChild(el('span', 'dc-rownum', String(d.number))); }
    if (g.items.length > 1) { t.appendChild(el('span', 'dc-times', 'asked ' + g.items.length + ' times')); }
    if (d.gated) { t.appendChild(el('span', 'dc-risk', riskShort(d.risk))); }
    b.appendChild(t);
    b.appendChild(el('span', 'dc-rowwhat', l.what || d.title));
    var sub = d.stale || l.due || (l.blocks ? l.wait : '') || '';
    if (sub) { b.appendChild(el('span', 'dc-rowsub', sub)); }
    b.addEventListener('click', function () { focusOn(g.key, true); });
    li.appendChild(b);
    return li;
  }
  function riskShort(r) {
    return { money: 'Spends', sending: 'Sends', publishing: 'Publishes', irreversible: 'For good' }[r] || 'Risk';
  }

  function bulkBar(s) {
    var picked = walk(s).filter(function (g) { return D.picked[g.key]; });
    var bar = el('div', 'dc-bulk');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'With what is selected');
    var n = picked.length;
    bar.appendChild(el('span', 'dc-bulk-n', n ? n + ' selected' : 'Pick the ones to clear'));
    var all = btn('All', 'dc-q dc-small', function () {
      walk(s).forEach(function (g) { D.picked[g.key] = true; });
      draw();
    });
    bar.appendChild(all);
    if (n) {
      var mine = picked.filter(canDelegate);
      var dl = btn('Rouh decides ' + mine.length, 'dc-q dc-small',
        function () { D.selecting = false; D.picked = {}; delegate(mine); });
      dl.disabled = !mine.length;
      if (!mine.length) { dl.title = 'Rouh decides only what can be changed later and has a pick.'; }
      bar.appendChild(dl);
      bar.appendChild(btn('Later, next week', 'dc-q dc-small', function () {
        D.selecting = false; D.picked = {}; snooze(picked, at(9, 7), 'Next week');
      }));
    }
    return bar;
  }

  /* A fold under the queue: what he put off, and what his delegates decide. */
  function folded(key, title, list, row) {
    // One row per question, as the queue: repeats once, with how many.
    var by = {}, one = [];
    list.forEach(function (d) {
      var k = sameKey(d);
      if (by[k]) { by[k]._n += 1; by[k]._ids.push(d.id); return; }
      by[k] = Object.assign({}, d, { _n: 1, _ids: [d.id] });
      one.push(by[k]);
    });
    list = one;
    var det = el('details', 'dc-fold');
    det.open = !!D.folds['f' + key];
    det.addEventListener('toggle', function () { D.folds['f' + key] = det.open; });
    var sum = el('summary', null, title);
    sum.appendChild(el('span', 'dc-n', String(list.length)));
    det.appendChild(sum);
    var ul = el('ul', 'dc-mini');
    list.forEach(function (d) { ul.appendChild(row(d)); });
    det.appendChild(ul);
    return det;
  }
  function laterRow(d) {
    var li = el('li', 'dc-minirow');
    var main = el('span', 'dc-minimain');
    main.appendChild(el('span', 'dc-minititle', (d.line || {}).what || d.title));
    main.appendChild(el('span', 'dc-minisub', (d.number ? 'Decision ' + d.number + ' · ' : '') + (d._n > 1 ? 'asked ' + d._n + ' times · ' : '') + 'back ' + when(d.snoozed_until)));
    li.appendChild(main);
    li.appendChild(btn('Bring back', 'dc-q dc-small', function () {
      actAll((d._ids || [d.id]).map(function (id) { return { id: id }; }), 'wake', {}).then(function (got) {
        var r = got[0].r;
        if (r.ok) { D.focus = 'g' + d.id; say({ words: 'Back in the queue.', ids: [], undo: '' }); }
        else { say({ words: (r.out && r.out.error) || 'That did not work.', ids: [], undo: '' }); }
        load();
      });
    }));
    return li;
  }
  function theirRow(d) {
    var li = el('li', 'dc-minirow');
    var main = el('span', 'dc-minimain');
    main.appendChild(el('span', 'dc-minititle', (d.line || {}).what || d.title));
    main.appendChild(el('span', 'dc-minisub', (d.decider || 'Your delegate') + ' decides this'
      + (d.number ? ' · Decision ' + d.number : '')));
    li.appendChild(main);
    var href = (d.line || {}).href;
    if (href) { li.appendChild(btn('Open', 'dc-q dc-small', function () { go(href); })); }
    return li;
  }

  /* ---- decided lately ---- */

  function drawHistory(page) {
    var bar = el('div', 'dc-hhead');
    bar.appendChild(btn('Back to the queue', 'dc-tool', function () { D.view = 'desk'; draw(); top(); }, 'Esc'));
    page.appendChild(bar);
    say2(page);
    var meta = $('decisionsMeta');
    var past = ((D.data && D.data.history) || []).slice(0, 40);
    var going = (D.data && D.data.going) || [];
    if (meta) { meta.textContent = 'Decided lately'; }
    if (!past.length && !going.length) {
      page.appendChild(el('p', 'dc-quiet', 'Nothing decided lately.'));
      return;
    }
    var ul = el('ul', 'dc-hist');
    ul.setAttribute('aria-label', 'Decided lately');
    folds(going.concat(past)).forEach(function (x) { ul.appendChild(histRow(x.d, x.n)); });
    page.appendChild(ul);
  }

  function histRow(d, n) {
    var li = el('li', 'dc-hrow');
    var main = el('div', 'dc-hmain');
    var top = el('span', 'dc-htop');
    top.appendChild(el('span', 'dc-hwho', whoDecided(d)));
    if (n > 1) { top.appendChild(el('span', 'dc-times', n + ' times')); }
    top.appendChild(el('span', 'dc-hwhen', ended(d)));
    main.appendChild(top);
    main.appendChild(el('span', 'dc-htitle', (d.line || {}).what || d.title));
    var said = (d.answer || {}).said || '';
    var res = said ? said + (d.result && d.status !== 'cleared' ? ' · ' + d.result : '')
      : (d.result || '');
    if (res) { main.appendChild(el('span', 'dc-hsaid', res)); }
    li.appendChild(main);
    var acts = el('div', 'dc-hacts');
    if (d.status === 'answered' && (d.undo_left || 0) > 0) {
      acts.appendChild(btn('Undo', 'dc-q dc-small', function () {
        act(d.id, 'undo', {}).then(function (r) {
          say({ words: r.ok ? 'Undone. It waits on you again.' : ((r.out && r.out.error) || 'Too late to undo.'), ids: [], undo: '' });
          load();
        });
      }));
    } else if (d.can_reopen) {
      acts.appendChild(btn(d.cleared ? 'Open again' : 'Undo', 'dc-q dc-small', function () {
        act(d.id, 'reopen', {}).then(function (r) {
          say({ words: r.ok ? ((r.out && r.out.said) || 'Open again.') : ((r.out && r.out.error) || 'That did not work.'), ids: [], undo: '' });
          load();
        });
      }));
    }
    var href = d.number ? '/decisions/' + d.number : (d.line || {}).href;
    if (href) {
      var a = el('a', 'dc-q dc-small dc-link', 'Open');
      a.href = href;
      a.setAttribute('data-inapp', '');
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0 || !host().go) { return; }
        e.preventDefault();
        host().go(href);
      });
      acts.appendChild(a);
    }
    li.appendChild(acts);
    return li;
  }

  function whoDecided(d) {
    var going = d.status === 'answered' || d.status === 'applying' ? ', going now' : '';
    if (d.decided_by) { return d.decided_by + ' decided' + going; }
    if (d.answered_by === 'rouh') { return 'Rouh decided for you' + going; }
    if (going) { return 'You decided' + going; }
    if (d.by_itself) { return 'Closed by itself'; }
    if (d.status === 'cleared') { return 'Cleared by Rouh'; }
    if (d.status === 'dismissed') { return 'You dismissed'; }
    if (d.status === 'expired') { return 'Ran out of time'; }
    if (d.status === 'withdrawn') { return 'Not asked any more'; }
    return 'You decided';
  }

  /* When it ended, and where it was answered. */
  function ended(d) {
    var ch = { telegram: 'on Telegram', voice: 'by voice', email: 'by email', offline: 'offline' }[d.channel] || '';
    var t = d.resolved_at || d.answered_at || d.updated_at;
    return [ch, t ? when(t) : ''].filter(Boolean).join(', ');
  }

  function when(t) {
    try {
      var day = new Date(t * 1000);
      var clock = day.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
      if (today(t)) { return 'today, ' + clock; }
      if (today(t - 86400)) { return 'tomorrow, ' + clock; }
      if (today(t + 86400)) { return 'yesterday, ' + clock; }
      return day.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '')
        + ', ' + clock;
    } catch (err) { return ''; }
  }

  /* ---- one decision on its own page ---- */

  function drawOne(page) {
    var back = el('a', 'dc-back', '← All decisions');
    back.href = '/decisions';
    back.setAttribute('data-inapp', '');
    back.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
      if (!host().open) { return; }
      e.preventDefault();
      host().open('');
    });
    page.appendChild(back);
    say2(page);
    if (!D.one) {
      if (!D.missing && !D.error) { page.appendChild(el('p', 'dc-quiet', 'Reading…')); }
      return;
    }
    page.appendChild(window.RouhDecision.card(D.one, decisionHost(), { place: 'page' }));
  }

  function say2(page) {
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
    input.placeholder = 'Number, e.g. 42';
    input.value = D.find;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('aria-label', 'Find a decision by its number');
    input.inputMode = 'numeric';
    input.setAttribute('enterkeyhint', 'go');
    form.appendChild(input);
    var goB = el('button', 'dc-tool', 'Go');
    goB.type = 'submit';
    form.appendChild(goB);
    form.addEventListener('submit', function (e) { e.preventDefault(); find(input.value); });
    input.addEventListener('input', function () { D.find = input.value; });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); D.finding = false; D.missing = ''; draw(); focusCard(); }
    });
    return form;
  }
  function focusFind() { var i = $('decisionsFind'); if (i) { i.focus(); } }

  /* ---- the toast ---- */

  function drawToast() {
    var wrap = document.querySelector('#decisionsView .dc-wrap');
    if (!wrap) { return; }
    var t = D.toast;
    var box = wrap.querySelector('.dc-toast');
    if (!t || !D.open) { if (box) { box.remove(); } return; }
    if (!box) {
      box = el('div', 'dc-toast');
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      wrap.appendChild(box);
    }
    box.textContent = '';
    box.appendChild(el('span', 'dc-toast-words', t.words));
    if (t.undo && !t.undoing) {
      var left = Math.max(0, Math.ceil((t.until - Date.now()) / 1000));
      var u = btn('Undo', 'dc-undo', undoToast, 'U');
      u.appendChild(el('span', 'dc-count', String(left)));
      box.appendChild(u);
    }
  }

  /* ---- moving about ---- */

  function focusOn(key, show) {
    D.focus = key;
    D.confirming = '';
    D.later = false;
    D.full = '';
    D.cardError = '';
    // A row in a folded lane opens its lane.
    var s = shape();
    s.lanes.forEach(function (l) {
      if (l.groups.some(function (g) { return g.key === key; }) && FOLDED[l.key]) { D.folds[l.key] = true; }
    });
    draw();
    if (show) { focusCard(true); }
  }
  /* Put the card in focus for the keys, and in sight on a phone where the queue is below it. */
  function focusCard(scroll) {
    var c = $('decisionsFocus');
    if (!c) { return; }
    var t = document.activeElement;
    if (!t || t === document.body || $('decisionsView').contains(t)) { c.focus({ preventScroll: true }); }
    if (scroll) {
      var body = $('decisionsBody');
      var r = c.getBoundingClientRect(), b = body.getBoundingClientRect();
      if (r.top < b.top || r.top > b.top + b.height * 0.5) { body.scrollTop += r.top - b.top - 8; }
    }
  }
  function top() { var b = $('decisionsBody'); if (b) { b.scrollTop = 0; } }
  function laterFocus() {
    var m = document.querySelector('.dc-latermenu button');
    if (m) { m.focus(); }
  }
  function move(by) {
    var order = walk(shape());
    if (!order.length) { return; }
    var i = 0;
    for (var k = 0; k < order.length; k++) { if (order[k].key === D.focus) { i = k; break; } }
    i = Math.max(0, Math.min(order.length - 1, i + by));
    focusOn(order[i].key, false);
    var on = document.querySelector('.dc-row.on');
    if (on && on.scrollIntoView) { on.scrollIntoView({ block: 'nearest' }); }
    focusCard(true);
  }

  /* The keys on a desk: only while the page is open, nothing is being typed, and the
     press is on this page (or on nothing). */
  function onKey(e) {
    if (!D.open || D.id || e.altKey || e.ctrlKey || e.metaKey) { return; }
    var t = /** @type {HTMLElement} */ (e.target);
    var view = $('decisionsView');
    if (!view || view.hidden) { return; }
    if (t && t !== document.body && !view.contains(t)) { return; }
    if (t && t.closest && t.closest('input, textarea, select, [contenteditable="true"]')) { return; }
    var k = e.key;
    if (k === 'Escape') {
      if (D.keys || D.later || D.confirming || D.full || D.finding || D.selecting || D.view === 'history') {
        e.preventDefault();
        e.stopPropagation();
        if (D.confirming) { D.confirming = ''; } else if (D.later) { D.later = false; }
        else if (D.keys) { D.keys = false; } else if (D.full) { D.full = ''; }
        else if (D.finding) { D.finding = false; } else if (D.selecting) { D.selecting = false; D.picked = {}; }
        else { D.view = 'desk'; }
        draw();
        focusCard();
      }
      return;
    }
    if (k === '?') { e.preventDefault(); D.keys = !D.keys; draw(); return; }
    if (k === '/') { e.preventDefault(); D.finding = true; draw(); focusFind(); return; }
    if ((k === 'u' || k === 'U') && D.toast && D.toast.undo) { e.preventDefault(); undoToast(); return; }
    if (D.view !== 'desk') { return; }
    var s = shape();
    var g = current(s);
    if (k === 'j' || k === 'ArrowDown') { e.preventDefault(); move(1); return; }
    if (k === 'k' || k === 'ArrowUp') { e.preventDefault(); move(-1); return; }
    if (!g) { return; }
    var onControl = t && t.closest && t.closest('button, a, summary, details');
    var d = g.items[0];
    if (k === 'y' || k === 'Y' || (k === 'Enter' && !onControl)) {
      e.preventDefault();
      if (D.confirming) {
        var c = D.confirming.slice(g.key.length + 1);
        if (c) { accept(g, c, true); }
      } else if (oneTap(d)) {
        accept(g, d.recommended);
      }
      return;
    }
    if (/^[1-9]$/.test(k) && D.later) {
      var times = laterTimes()[Number(k) - 1];
      if (times) { e.preventDefault(); snooze([g], times[1], times[0]); }
      return;
    }
    if (/^[1-9]$/.test(k)) {
      var rec = oneTap(d) ? optionOf(d, d.recommended) : null;
      var o = alternatives(d, rec)[Number(k) - 1];
      if (o) { e.preventDefault(); accept(g, o.id); }
      return;
    }
    if (k === 's' || k === 'S') { e.preventDefault(); D.later = !D.later; draw(); if (D.later) { laterFocus(); } return; }
    if (k === 'd' || k === 'D') { if (canDelegate(g)) { e.preventDefault(); delegate([g]); } return; }
    if (k === 'o' || k === 'O') { if ((d.line || {}).href) { e.preventDefault(); go(d.line.href); } return; }
    if (k === 'e' || k === 'E') { e.preventDefault(); D.full = D.full === g.key ? '' : g.key; draw(); return; }
    if (k === 'x' || k === 'X') {
      e.preventDefault();
      if (!D.selecting) { D.selecting = true; D.picked = {}; }
      if (D.picked[g.key]) { delete D.picked[g.key]; } else { D.picked[g.key] = true; }
      draw();
    }
  }
  document.addEventListener('keydown', onKey, true);

  /* ---- the layer ---- */

  /* At /decisions, the desk; at /decisions/<number>, that one. */
  function shown(id) {
    D.open = true;
    var was = D.id;
    D.id = id ? String(id) : '';
    D.missing = '';
    if (D.id !== was) { D.one = null; D.view = 'desk'; }
    draw();
    var body = $('decisionsBody');
    if (body && D.id !== was) { body.scrollTop = 0; }
    if (D.id) { loadOne(D.id); } else { load(); }
  }
  function hidden() {
    D.open = false;
    clearTimeout(D.timer);
    drawToast();
  }
  /* The socket says the count moved (an answer on Telegram or by voice, a new one): read the
     list again when it is open. */
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
