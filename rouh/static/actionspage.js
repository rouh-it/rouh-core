/* Your part, at /actions: the hands-on things only the person can do, which hold
   up work Rouh is doing (`rouh/actions.py`, `rouh/web/actions.py`).

   The owner, 7 November 2026, of "that waits on Petar's one-minute install check
   (Decision 430)": "this is not a decision. This is a blocker action I need to
   do." So an action has a page of its own that gets him up to speed cold, and a
   list beside Decisions under Now (task 62, step 62-28, whose journeys this
   follows):

   - the list, grouped by the work each action unblocks, the groups holding work
     up first and then the oldest first, each row with its number, what to do in
     one line, how long it takes and its age said plainly;
   - one action in full: what to do, what it unblocks with links, how long, the
     steps ticked one by one with their direct links, Done as the one main button
     (with a note, such as what a command answered), Later, Not doing this (with a
     reason), Do it another way (his words) and Ask (answered in place); then
     what happens after, what waiting costs, how Rouh checks it, the story so far,
     the questions he asked and what came back;
   - Done, Not doing this and Another way get a toast with Undo for the server's
     own window (`decisions.UNDO_SECONDS`); his words go back exactly as he wrote
     them, and the page shows them back;
   - what was put off, and what was done lately (withdrawn by itself included,
     with why and Open again), folded under the list.

   On a desk the list and the action sit side by side; on a phone the list is one
   page and an action another, /actions/<number>, with a way back. The layer, its
   address and its row in the navigation are app/runs.js's (`actionsOpen`),
   handed over through `window.RouhActionsHost`; the count on that row comes over
   the socket (`decisions`, `actions`) and from here. */
(function () {
  'use strict';

  var UNDO_MS = 8000;
  var A = { open: false, id: '', data: null, one: null, error: '', missing: '', seq: 0, timer: 0,
            form: '', note: '', words: '', asking: '', askBusy: false, later: false, busy: false,
            cardError: '', toast: null, toastTimer: 0, confirm: null, folds: {} };

  function host() { return window.RouhActionsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(text, cls, fn) {
    var b = el('button', cls, text);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }
  /** A link: an address in Rouh opens in Rouh, a web address in a new tab. */
  function link(href, text, cls) {
    var a = el('a', cls || 'ac-link', text);
    a.href = href;
    if (/^https?:\/\//.test(href)) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    } else {
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) { return; }
        e.preventDefault();
        if (host().go) { host().go(href); }
      });
    }
    return a;
  }
  function plural(n, one, many) { return n === 1 ? one : many; }
  /** A moment as Rouh says one: "Mon 9 Nov, 08:00". */
  function when(sec) {
    return new Date(sec * 1000).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function minutes(m) {
    if (!m) { return ''; }
    if (m < 60) { return 'about ' + m + ' min'; }
    var h = Math.round(m / 6) / 10;
    return 'about ' + h + (h === 1 ? ' hour' : ' hours');
  }
  function name(d) { return 'Action ' + d.number; }

  /* ---- reading ---- */

  function load() {
    var seq = ++A.seq;
    return fetch('/api/actions', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== A.seq) { return; }
          if (!r.ok || !j) {
            A.error = (j && j.error) || 'Your part could not be read. Try again in a moment.';
          } else {
            A.error = '';
            A.data = j;
            count(j.counts || {});
          }
          if (A.open) { draw(); }
        });
      })
      .catch(function () {
        if (seq !== A.seq) { return; }
        A.error = 'Rouh could not be reached. Check the connection and try again.';
        if (A.open) { draw(); }
      });
  }

  function loadOne(ref) {
    return fetch('/api/actions/at/' + encodeURIComponent(ref), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (out) {
          if (!A.open || A.id !== ref) { return; }
          if (!r.ok || !out || !out.action) {
            A.one = null;
            A.missing = r.status === 404 ? 'There is no Action ' + ref + '.'
              : 'That action could not be read. Try again in a moment.';
          } else {
            A.one = out.action;
            A.missing = '';
          }
          draw();
        });
      }, function () {
        A.missing = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function count(c) {
    if (host().counted) { host().counted(c.open || 0, c.holds || 0); }
  }

  function soon(ms) {
    clearTimeout(A.timer);
    A.timer = setTimeout(function () {
      if (!A.open) { return; }
      load();
      if (A.id) { loadOne(A.id); }
    }, ms == null ? 1200 : ms);
  }

  /* ---- acting ---- */

  function act(id, what, body) {
    return fetch('/api/actions/' + encodeURIComponent(id) + '/act', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ act: what }, body || {}))
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (out) { return { ok: r.ok, status: r.status, out: out }; });
    }, function () {
      return { ok: false, status: 0, out: { error: 'Rouh could not be reached. Check the connection and try again.' } };
    });
  }

  /** The action shown in full: the one at /actions/<number>, else the first in the list. */
  function current() {
    if (A.id) { return A.one; }
    var open = (A.data && A.data.open) || [];
    return open[0] || null;
  }

  function reset() {
    A.form = ''; A.note = ''; A.words = ''; A.later = false; A.cardError = ''; A.confirm = null;
  }

  function answer(d, verb, text, confirm) {
    if (A.busy) { return; }
    A.busy = true;
    A.cardError = '';
    draw();
    act(d.id, verb, { text: text || '', confirm: confirm || '' }).then(function (r) {
      A.busy = false;
      if (!r.ok && r.status === 409 && r.out && r.out.confirm) {
        A.confirm = { verb: verb, text: text, risk: r.out.confirm, note: r.out.error || '' };
        draw();
        return;
      }
      if (!r.ok) {
        A.cardError = (r.out && r.out.error) || 'That did not work. Try again.';
        draw();
        return;
      }
      var said = { done: 'Done', not_doing: 'Not doing this', another: 'Another way' }[verb];
      reset();
      if (r.out.action) { A.one = r.out.action; if (!A.id) { A.id = String(r.out.action.number); } }
      toast(name(d) + ': ' + said + '. It goes back to the work in a few seconds.', d);
      draw();
      soon(UNDO_MS + 1500);
    });
  }

  function toast(words, d) {
    clearInterval(A.toastTimer);
    A.toast = { words: words, d: d, until: Date.now() + UNDO_MS };
    A.toastTimer = setInterval(function () {
      if (!A.toast || Date.now() >= A.toast.until) {
        clearInterval(A.toastTimer);
        A.toast = null;
      }
      drawToast();
    }, 500);
    drawToast();
  }
  function undo() {
    var t = A.toast;
    if (!t) { return; }
    A.toast = null;
    clearInterval(A.toastTimer);
    drawToast();
    act(t.d.id, 'undo').then(function (r) {
      if (!r.ok) {
        A.cardError = (r.out && r.out.error) || 'Too late to undo.';
      } else if (r.out.action) {
        A.one = r.out.action;
      }
      load();
      draw();
    });
  }

  function laterTimes() {
    var now = new Date();
    var evening = new Date(now); evening.setHours(19, 0, 0, 0);
    if (evening <= now) { evening.setDate(evening.getDate() + 1); }
    var morning = new Date(now); morning.setDate(morning.getDate() + 1); morning.setHours(8, 0, 0, 0);
    var week = new Date(now); week.setDate(week.getDate() + ((8 - week.getDay()) % 7 || 7)); week.setHours(8, 0, 0, 0);
    return [['In an hour', now.getTime() + 3600e3], ['This evening', evening.getTime()],
            ['Tomorrow morning', morning.getTime()], ['Next week', week.getTime()]];
  }
  function snooze(d, until, label) {
    A.busy = true;
    act(d.id, 'snooze', { until: until / 1000 }).then(function (r) {
      A.busy = false;
      if (!r.ok) { A.cardError = (r.out && r.out.error) || 'That did not work.'; draw(); return; }
      reset();
      toastPlain(name(d) + ': put off till ' + label.toLowerCase() + '.');
      if (A.id && host().open) { host().open(''); }
      load();
    });
  }
  function toastPlain(words) {
    clearInterval(A.toastTimer);
    A.toast = { words: words, d: null, until: Date.now() + 4000 };
    A.toastTimer = setInterval(function () {
      if (!A.toast || Date.now() >= A.toast.until) { clearInterval(A.toastTimer); A.toast = null; }
      drawToast();
    }, 500);
    drawToast();
  }

  function tick(d, step, on) {
    act(d.id, 'tick', { step: step, on: on }).then(function (r) {
      if (r.ok && r.out.action) {
        if (A.one && A.one.id === d.id) { A.one = r.out.action; }
        var list = (A.data && A.data.open) || [];
        for (var i = 0; i < list.length; i++) { if (list[i].id === d.id) { list[i] = r.out.action; } }
      }
    });
  }

  function ask(d, question) {
    if (!question || A.askBusy) { return; }
    A.askBusy = true;
    A.asking = question;
    draw();
    act(d.id, 'ask', { text: question }).then(function (r) {
      A.askBusy = false;
      if (!r.ok) {
        A.cardError = (r.out && r.out.error) || 'Rouh could not answer that just now.';
      } else {
        A.asking = '';
        A.cardError = '';
        if (r.out.action) {
          A.one = r.out.action;
          var list = (A.data && A.data.open) || [];
          for (var i = 0; i < list.length; i++) { if (list[i].id === d.id) { list[i] = r.out.action; } }
        }
      }
      draw();
      var q = document.querySelector('.ac-qa li:last-child');
      if (q && q.scrollIntoView) { q.scrollIntoView({ block: 'nearest' }); }
    });
  }

  function reopen(d) {
    act(d.id, 'reopen').then(function (r) {
      if (!r.ok) { A.cardError = (r.out && r.out.error) || 'That could not be opened again.'; }
      load();
      draw();
    });
  }
  function wake(d) {
    act(d.id, 'wake').then(function () { load(); });
  }

  /* ---- drawing ---- */

  function headline(data) {
    var c = (data && data.counts) || {};
    if (!c.open) { return 'Nothing needs your hands.'; }
    var words = (c.open === 1 ? '1 thing only you can do' : c.open + ' things only you can do');
    if (c.minutes) { words += ', ' + minutes(c.minutes); }
    if (c.holds) { words += '. ' + (c.holds === c.open ? (c.open === 1 ? 'It holds' : 'They hold') + ' work up.' : c.holds + ' of them hold work up.'); }
    else { words += '.'; }
    return words;
  }

  function draw() {
    var body = $('actionsBody');
    var meta = $('actionsMeta');
    if (!body) { return; }
    if (meta) { meta.textContent = A.data ? headline(A.data) : ''; }
    body.textContent = '';
    var page = el('div', 'ac-page');
    body.appendChild(page);
    if (A.error && !A.data) {
      page.appendChild(el('p', 'ac-error', A.error));
      page.appendChild(button('Try again', 'ac-quiet', load));
      return;
    }
    if (!A.data && !A.one) {
      page.appendChild(el('p', 'ac-wait', 'Reading what only you can do…'));
      return;
    }
    var wide = body.clientWidth >= 760;
    var d = current();
    var desk = el('div', 'ac-desk' + (A.id ? ' ac-one' : ''));
    page.appendChild(desk);
    // At /actions the first action is open at once (journey 1: one click from the row to its
    // first step): beside the list on a wide layer, above the rest of the list on a narrow one.
    // At /actions/<number> on a narrow layer, the action alone, with the way back.
    if (A.id && A.missing) {
      var gone = el('section', 'ac-card');
      gone.appendChild(el('p', 'ac-error', A.missing));
      gone.appendChild(button('All of your part', 'ac-quiet', function () { if (host().open) { host().open(''); } }));
      if (wide) { desk.appendChild(drawList(null)); }
      desk.appendChild(gone);
    } else if (wide) {
      desk.appendChild(drawList(d));
      if (d) { desk.appendChild(drawAction(d, false)); }
    } else if (A.id) {
      if (d) { desk.appendChild(drawAction(d, true)); }
    } else {
      var more = ((A.data && A.data.open) || []).length - 1;
      if (d && more > 0) {
        var jump = button(more === 1 ? '1 more waits below' : more + ' more wait below', 'ac-quiet ac-small ac-jump', function () {
          var to = document.querySelector('#actionsView .ac-list');
          if (to && to.scrollIntoView) { to.scrollIntoView({ block: 'start' }); }
        });
        desk.appendChild(jump);
      }
      if (d) { desk.appendChild(drawAction(d, false)); }
      desk.appendChild(drawList(d, true));
    }
    drawToast();
  }

  /** The list; `under` when it follows the first action on a narrow layer, which it leaves out. */
  function drawList(focus, under) {
    var data = A.data || { open: [], groups: [], snoozed: [], history: [], counts: {} };
    var box = el('section', 'ac-list');
    if (under && data.open.length > 1) { box.appendChild(el('h3', 'ac-h ac-more', 'The rest of your part')); }
    box.setAttribute('aria-label', 'What only you can do');
    if (!data.open.length) {
      var empty = el('div', 'ac-empty');
      empty.appendChild(el('p', 'ac-empty-big', 'Nothing needs your hands.'));
      var off = (data.snoozed || [])[0];
      if (off && off.snoozed_until) {
        empty.appendChild(el('p', 'ac-empty-small', (data.snoozed.length === 1 ? 'One is put off; it comes back '
          : data.snoozed.length + ' are put off; the first comes back ') + when(off.snoozed_until) + '.'));
      }
      var done = (data.history || []).filter(function (h) { return h.status !== 'withdrawn' || h.by_itself; });
      empty.appendChild(el('p', 'ac-empty-small', done.length
        ? 'Everything Rouh needed you to do is done or settled. The last ones are under Done lately.'
        : 'When work Rouh is doing needs something only you can do, it is here, with everything you need to do it.'));
      box.appendChild(empty);
    }
    var byId = {};
    data.open.forEach(function (d) { byId[d.id] = d; });
    (data.groups || []).forEach(function (g) {
      var group = el('div', 'ac-group');
      var head = el('div', 'ac-ghead');
      head.appendChild(el('span', 'ac-gk', g.holds ? 'Unblocks' : 'For'));
      if (g.href) { head.appendChild(link(g.href, g.label, 'ac-glabel')); }
      else { head.appendChild(el('span', 'ac-glabel', g.label)); }
      group.appendChild(head);
      var ul = el('ul', 'ac-rows');
      var shownIds = g.ids.filter(function (id) { return byId[id] && !(under && focus && focus.id === id); });
      if (!shownIds.length) { return; }
      g.ids.forEach(function (id) {
        var d = byId[id];
        if (!d || shownIds.indexOf(id) < 0) { return; }
        var li = el('li');
        var row = el('button', 'ac-row' + (focus && focus.id === d.id ? ' on' : ''));
        row.type = 'button';
        if (focus && focus.id === d.id) { row.setAttribute('aria-current', 'true'); }
        var top = el('span', 'ac-rowtop');
        top.appendChild(el('span', 'ac-num', name(d)));
        if (d.holds) { top.appendChild(el('span', 'ac-flag ac-flag-warn', 'Holds work up')); }
        top.appendChild(el('span', 'ac-age', 'asked ' + d.age));
        row.appendChild(top);
        row.appendChild(el('span', 'ac-rowdo', d.do));
        var bits = [minutes(d.minutes), (d.action && d.action.steps && d.action.steps.length)
          ? d.action.steps.length + plural(d.action.steps.length, ' step', ' steps') : ''].filter(Boolean);
        if (bits.length) { row.appendChild(el('span', 'ac-rowmeta', bits.join(', '))); }
        row.addEventListener('click', function () {
          reset();
          if (host().open) { host().open(String(d.number)); }
        });
        li.appendChild(row);
        ul.appendChild(li);
      });
      group.appendChild(ul);
      box.appendChild(group);
    });
    if ((data.snoozed || []).length) {
      box.appendChild(fold('snoozed', 'Put off (' + data.snoozed.length + ')', function (inner) {
        data.snoozed.forEach(function (d) {
          var r = el('div', 'ac-hrow');
          var w = el('div', 'ac-hwords');
          w.appendChild(el('span', 'ac-num', name(d)));
          w.appendChild(el('span', 'ac-hdo', d.do));
          if (d.snoozed_until) {
            w.appendChild(el('span', 'ac-hmeta', 'Comes back ' + when(d.snoozed_until)));
          }
          r.appendChild(w);
          r.appendChild(button('Bring back', 'ac-quiet ac-small', function () { wake(d); }));
          inner.appendChild(r);
        });
      }));
    }
    var hist = (data.history || []).concat(data.going || []);
    if (hist.length) {
      box.appendChild(fold('history', 'Done lately (' + hist.length + ')', function (inner) {
        hist.forEach(function (d) {
          var r = el('div', 'ac-hrow');
          var w = el('div', 'ac-hwords');
          w.appendChild(el('span', 'ac-num', name(d)));
          w.appendChild(el('span', 'ac-hdo', d.do));
          w.appendChild(el('span', 'ac-hmeta', outcome(d)));
          r.appendChild(w);
          if (d.by_itself && d.status === 'withdrawn') {
            r.appendChild(button('Open again', 'ac-quiet ac-small', function () { reopen(d); }));
          } else {
            r.appendChild(button('Open', 'ac-quiet ac-small', function () { if (host().open) { host().open(String(d.number)); } }));
          }
          inner.appendChild(r);
        });
      }));
    }
    return box;
  }

  function fold(key, title, fill) {
    var det = el('details', 'ac-fold');
    if (A.folds[key]) { det.open = true; }
    det.addEventListener('toggle', function () { A.folds[key] = det.open; });
    det.appendChild(el('summary', 'ac-foldt', title));
    var inner = el('div', 'ac-foldb');
    fill(inner);
    det.appendChild(inner);
    return det;
  }

  /** What he answered, as the button's name and then his own words exactly as he typed them. */
  function said(a) {
    var head = { done: 'Done', not_doing: 'Not doing this', another: 'Do it another way' }[a.verb];
    if (!head) { return a.said || 'Answered'; }
    return a.words ? head + ': \u201c' + a.words + '\u201d' : head;
  }

  /** What became of an answered or closed action, in a line. */
  function outcome(d) {
    var a = d.answer || {};
    if (d.status === 'withdrawn') {
      return d.result || 'Withdrawn: nothing asks it any more.';
    }
    var where = d.channel && d.channel !== 'screen' ? ' (on ' + d.channel + ')' : '';
    var state = { answered: ' Goes back in a moment.', applying: ' Going back to the work now.',
                  applied: '', failed: ' It could not go back: answer it again.' }[d.status] || '';
    return said(a) + where + state;
  }

  function drawAction(d, narrow) {
    var page = d.action || {};
    var card = el('article', 'ac-card');
    card.id = 'actionsFocus';
    card.setAttribute('aria-label', name(d));
    if (narrow) {
      card.appendChild(button('All of your part', 'ac-back', function () { reset(); if (host().open) { host().open(''); } }));
    }
    var top = el('div', 'ac-top');
    top.appendChild(el('span', 'ac-num ac-num-big', name(d)));
    if (d.holds && d.status !== 'applied') { top.appendChild(el('span', 'ac-flag ac-flag-warn', 'Holds work up')); }
    if (d.gated) { top.appendChild(el('span', 'ac-flag ac-flag-bad', d.risk_words)); }
    top.appendChild(el('span', 'ac-age', 'Asked ' + d.age + (d.asked_on && d.age !== 'today' && d.age !== 'yesterday' ? ', on ' + d.asked_on : '')));
    card.appendChild(top);
    card.appendChild(el('h2', 'ac-do', d.do));
    var facts = el('p', 'ac-sub');
    facts.appendChild(el('span', 'ac-time', d.minutes ? 'Takes ' + minutes(d.minutes) + '.' : 'Time not said.'));
    var work = d.work || [];
    if (work.length) {
      facts.appendChild(el('span', 'ac-gk', 'Unblocks'));
      work.forEach(function (w, i) {
        if (i) { facts.appendChild(document.createTextNode(i === work.length - 1 ? ' and ' : '; ')); }
        facts.appendChild(w.href ? link(w.href, w.label) : el('span', '', w.label));
      });
    }
    card.appendChild(facts);

    var open = ['open', 'snoozed', 'failed'].indexOf(d.status) >= 0;
    if (!open) { card.appendChild(drawState(d)); }
    // An action asked days ago is opened by someone who forgot it (journey 2): its story first.
    var cold = (Date.now() / 1000 - (d.created_at || 0)) > 3 * 86400;
    if (cold) { var early = drawStory(d); if (early) { card.appendChild(early); } }

    var steps = page.steps || [];
    if (steps.length) {
      var sec = el('section', 'ac-steps');
      sec.setAttribute('aria-label', 'Steps');
      var ol = el('ol', 'ac-steplist');
      var ticked = page.ticked || [];
      steps.forEach(function (s, i) {
        var li = el('li', 'ac-step' + (ticked.indexOf(s.id) >= 0 ? ' ticked' : ''));
        var lab = el('label', 'ac-check');
        var box = el('input');
        box.type = 'checkbox';
        box.checked = ticked.indexOf(s.id) >= 0;
        box.disabled = !open;
        box.addEventListener('change', function () {
          li.classList.toggle('ticked', box.checked);
          tick(d, s.id, box.checked);
        });
        lab.appendChild(box);
        var words = el('span', 'ac-steptext');
        words.appendChild(el('span', 'ac-stepn', (i + 1) + '. '));
        words.appendChild(document.createTextNode(s.text));
        lab.appendChild(words);
        li.appendChild(lab);
        if (s.href) { li.appendChild(link(s.href, s.link || 'Open it', 'ac-steplink')); }
        if (s.command) { li.appendChild(drawCommand(s.command)); }
        ol.appendChild(li);
      });
      sec.appendChild(ol);
      card.appendChild(sec);
    }

    if (open) { card.appendChild(drawButtons(d)); }
    if (A.cardError) { card.appendChild(el('p', 'ac-error', A.cardError)); }
    var qaBox = drawQuestions(d);
    if (qaBox) { card.appendChild(qaBox); }

    var dl = el('dl', 'ac-facts');
    [['After you do it', page.after || d.then], ['Waiting costs', page.wait || (d.line || {}).wait],
     ['How Rouh checks', checkWords(d)]].forEach(function (f) {
      if (!f[1]) { return; }
      var row = el('div', 'ac-fact');
      row.appendChild(el('dt', '', f[0]));
      row.appendChild(el('dd', '', f[1]));
      dl.appendChild(row);
    });
    if (dl.childNodes.length) { card.appendChild(dl); }

    if (!cold) { var late = drawStory(d); if (late) { card.appendChild(late); } }

    var ev = d.events || [];
    if (ev.length) {
      var det = el('details', 'ac-fold ac-history');
      det.appendChild(el('summary', 'ac-foldt', 'Its history (' + ev.length + ')'));
      var list = el('ul', 'ac-events');
      ev.forEach(function (e) {
        var li = el('li');
        li.appendChild(el('span', 'ac-hmeta', when((e.at || 0))));
        li.appendChild(el('span', '', (e.kind || '') + (e.detail ? ': ' + e.detail : '')));
        list.appendChild(li);
      });
      det.appendChild(list);
      card.appendChild(det);
    }
    return card;
  }

  /** How it is checked, always said: the reader's words, else who checks it. */
  function checkWords(d) {
    return (d.action || {}).check || 'the work that asked checks it when it carries on, and tells you here if it did not work.';
  }

  /** A command to run, exactly as given, with a Copy button. */
  function drawCommand(text) {
    var box = el('div', 'ac-cmd');
    box.appendChild(el('code', 'ac-cmdtext', text));
    var copy = button('Copy', 'ac-quiet ac-small ac-copy', function () {
      var done = function () { copy.textContent = 'Copied'; setTimeout(function () { copy.textContent = 'Copy'; }, 1800); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { copy.textContent = 'Select it and copy'; });
      } else {
        copy.textContent = 'Select it and copy';
      }
    });
    copy.setAttribute('aria-label', 'Copy the command');
    box.appendChild(copy);
    return box;
  }

  function drawStory(d) {
    var story = (d.action || {}).story || d.why || '';
    if (!story) { return null; }
    var st = el('section', 'ac-story');
    st.appendChild(el('h3', 'ac-h', 'The story so far'));
    story.split(/\n+/).forEach(function (p) { if (p.trim()) { st.appendChild(el('p', '', p.trim())); } });
    st.appendChild(el('p', 'ac-asked', 'Asked ' + (d.asked_on ? 'on ' + d.asked_on + ', ' : '') + d.age
      + ((d.work || [])[0] ? ', for ' + d.work[0].label : d.context ? ', by ' + d.context : '') + '.'));
    return st;
  }

  /** The questions he asked here, right under the buttons where he asks them. */
  function drawQuestions(d) {
    var qa = (d.action || {}).qa || [];
    if (!qa.length && !(A.asking && A.askBusy)) { return null; }
    var qs = el('section', 'ac-qasec');
    qs.appendChild(el('h3', 'ac-h', 'Your questions'));
    var ul = el('ul', 'ac-qa');
    function entry(x, into) {
      var li = el('li');
      li.appendChild(el('p', 'ac-q', x.q));
      li.appendChild(el('p', 'ac-a', x.a));
      into.appendChild(li);
    }
    var older = qa.slice(0, Math.max(0, qa.length - 2));
    if (older.length) {
      var det = el('details', 'ac-fold ac-older');
      det.appendChild(el('summary', 'ac-foldt', 'Earlier questions (' + older.length + ')'));
      var oul = el('ul', 'ac-qa');
      older.forEach(function (x) { entry(x, oul); });
      det.appendChild(oul);
      qs.appendChild(det);
    }
    qa.slice(older.length).forEach(function (x) { entry(x, ul); });
    if (A.asking && A.askBusy) {
      var wait = el('li');
      wait.appendChild(el('p', 'ac-q', A.asking));
      wait.appendChild(el('p', 'ac-a ac-wait', 'Rouh is looking into it…'));
      ul.appendChild(wait);
    }
    qs.appendChild(ul);
    return qs;
  }

  /** Where an answered or closed action stands: what he said, and what came back. */
  function drawState(d) {
    var box = el('div', 'ac-state');
    box.setAttribute('role', 'status');
    var a = d.answer || {};
    if (d.status === 'withdrawn') {
      box.appendChild(el('p', 'ac-state-big', d.result || 'Withdrawn: nothing asks it any more.'));
      if ((d.action || {}).stale) { box.appendChild(button('Open again', 'ac-quiet', function () { reopen(d); })); }
      return box;
    }
    box.appendChild(el('p', 'ac-state-big', 'You said: ' + said(a)));
    var went = d.status === 'applied';
    var ol = el('ol', 'ac-progress');
    function stage(on, words) {
      var li = el('li', on ? 'on' : '');
      var dot = el('span', 'ac-dot');
      if (on) {
        dot.innerHTML = '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2.5 6.3l2.3 2.2 4.7-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      }
      li.appendChild(dot);
      li.appendChild(el('span', '', words));
      ol.appendChild(li);
    }
    stage(true, d.status === 'answered' ? 'Your answer, which you can undo for a few seconds' : 'Your answer');
    stage(went, went ? 'Went back to the work' + (d.result ? ': ' + d.result : '')
      : d.status === 'failed' ? 'It could not go back to the work: answer it again' : 'Going back to the work');
    if (a.verb === 'done') {
      var where = ((d.action || {}).task_id && (d.work || [])[0]) ? (d.work[0].label + "'s chat")
        : 'this page, under What came back';
      stage(false, (went ? 'Now being checked: ' : 'Then it is checked: ') + checkWords(d)
        + ' What the check finds is said in ' + where + '.');
    } else {
      stage(false, went ? 'The work goes on without it, or stops, and says which' : 'Then the work goes on its other way, or stops');
    }
    box.appendChild(ol);
    return box;
  }

  function drawButtons(d) {
    var wrap = el('div', 'ac-answers');
    if (A.confirm) {
      var c = el('div', 'ac-confirm');
      c.appendChild(el('p', '', A.confirm.note || 'This one needs your yes to its risk first.'));
      c.appendChild(button('Yes, ' + ({ done: 'it is done', not_doing: 'I am not doing it', another: 'do it that way' }[A.confirm.verb] || 'go on'),
        'ac-main', function () { answer(d, A.confirm.verb, A.confirm.text, A.confirm.risk); }));
      c.appendChild(button('Cancel', 'ac-quiet', function () { A.confirm = null; draw(); }));
      wrap.appendChild(c);
      return wrap;
    }
    // Done, the one main button, with a note that goes with it.
    var doneForm = el('form', 'ac-doneform');
    var noteId = 'acNote' + d.id;
    var lab = el('label', 'ac-label', 'A note with Done (optional)');
    lab.htmlFor = noteId;
    var note = el('input', 'ac-input');
    note.id = noteId;
    note.type = 'text';
    note.placeholder = 'A note for the work';
    note.value = A.note;
    note.addEventListener('input', function () { A.note = note.value; });
    doneForm.appendChild(lab);
    var line = el('div', 'ac-doneline');
    line.appendChild(note);
    var main = el('button', 'ac-main', A.busy ? 'Sending…' : 'Done');
    main.type = 'submit';
    main.disabled = A.busy;
    line.appendChild(main);
    doneForm.appendChild(line);
    doneForm.addEventListener('submit', function (e) { e.preventDefault(); answer(d, 'done', note.value); });
    // A child of the card itself, not of this block, so it can stay in view while the page above it
    // is read (`position: sticky` keeps an element inside its parent).
    var both = document.createDocumentFragment();
    both.appendChild(doneForm);
    both.appendChild(wrap);

    var quiet = el('div', 'ac-quietrow');
    var later = button('Later', 'ac-quiet', function () { A.later = !A.later; A.form = ''; draw(); });
    later.setAttribute('aria-expanded', A.later ? 'true' : 'false');
    quiet.appendChild(later);
    [['not_doing', 'Not doing this'], ['another', 'Do it another way'], ['ask', 'Ask']].forEach(function (f) {
      var b = button(f[1], 'ac-quiet', function () { A.form = A.form === f[0] ? '' : f[0]; A.later = false; A.words = ''; draw(); focusForm(); });
      b.setAttribute('aria-expanded', A.form === f[0] ? 'true' : 'false');
      quiet.appendChild(b);
    });
    wrap.appendChild(quiet);

    if (A.later) {
      var menu = el('div', 'ac-latermenu');
      menu.setAttribute('role', 'group');
      menu.setAttribute('aria-label', 'Put it off till');
      laterTimes().forEach(function (t) {
        menu.appendChild(button(t[0], 'ac-quiet', function () { snooze(d, t[1], t[0]); }));
      });
      wrap.appendChild(menu);
    }
    if (A.form) { wrap.appendChild(drawForm(d)); }
    return both;
  }

  function drawForm(d) {
    var kind = A.form;
    var spec = {
      not_doing: { label: 'Why not? It goes to the work exactly as you write it (optional)', send: 'Send: not doing this',
                   then: 'The work is told, and stops or finds another way. It leaves your list.', need: false },
      another: { label: 'Which other way? It goes to the work exactly as you write it', send: 'Send this way',
                 then: 'The work carries on with your words. It leaves your list.', need: true },
      ask: { label: 'Your question about it', send: 'Send question',
             then: 'Answered here, from what Rouh knows of it. Asking answers nothing and goes nowhere else.', need: true }
    }[kind];
    var form = el('form', 'ac-form');
    var id = 'acForm' + d.id;
    var lab = el('label', 'ac-label', spec.label);
    lab.htmlFor = id;
    form.appendChild(lab);
    var box = el(kind === 'ask' ? 'input' : 'textarea', 'ac-input' + (kind === 'ask' ? '' : ' ac-area'));
    box.id = id;
    if (kind === 'ask') { /** @type {HTMLInputElement} */ (box).type = 'text'; }
    else { box.setAttribute('rows', '3'); }
    /** @type {HTMLInputElement} */ (box).value = A.words;
    box.addEventListener('input', function () { A.words = /** @type {HTMLInputElement} */ (box).value; });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); A.form = ''; draw(); }
    });
    form.appendChild(box);
    form.appendChild(el('p', 'ac-then', spec.then));
    var row = el('div', 'ac-formrow');
    var send = el('button', kind === 'ask' ? 'ac-quiet ac-send' : 'ac-quiet ac-send', A.askBusy && kind === 'ask' ? 'Asking…' : spec.send);
    send.type = 'submit';
    row.appendChild(send);
    row.appendChild(button('Cancel', 'ac-quiet', function () { A.form = ''; A.words = ''; draw(); }));
    form.appendChild(row);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var words = /** @type {HTMLInputElement} */ (box).value.trim();
      if (spec.need && !words) { box.focus(); return; }
      if (kind === 'ask') { A.words = ''; ask(d, words); }
      else { answer(d, kind, words); }
    });
    return form;
  }
  function focusForm() {
    var f = document.querySelector('#actionsView .ac-form .ac-input');
    if (f) { /** @type {HTMLElement} */ (f).focus(); }
  }

  function drawToast() {
    var wrap = document.querySelector('#actionsView .ac-wrap');
    if (!wrap) { return; }
    var t = A.toast;
    var box = wrap.querySelector('.ac-toast');
    if (!t || !A.open) { if (box) { box.remove(); } return; }
    if (!box) {
      box = el('div', 'ac-toast');
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      wrap.appendChild(box);
    }
    box.textContent = '';
    box.appendChild(el('span', 'ac-toast-words', t.words));
    if (t.d) {
      var left = Math.max(0, Math.ceil((t.until - Date.now()) / 1000));
      box.appendChild(button('Undo (' + left + ')', 'ac-undo', undo));
    }
  }

  /* ---- the layer ---- */

  function shown(id) {
    A.open = true;
    var was = A.id;
    A.id = id ? String(id) : '';
    A.missing = '';
    if (A.id !== was) { A.one = null; reset(); }
    draw();
    var body = $('actionsBody');
    if (body && A.id !== was) { body.scrollTop = 0; }
    load();
    if (A.id) { loadOne(A.id); }
  }
  function hidden() {
    A.open = false;
    clearTimeout(A.timer);
    drawToast();
  }
  function moved() { if (A.open && !A.form && !A.askBusy) { soon(); } }

  window.RouhActions = { shown: shown, hidden: hidden, moved: moved, reload: load };

  var x = $('actionsClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
  if (window.ResizeObserver && $('actionsBody')) {
    var lastWide = null;
    new ResizeObserver(function () {
      var wide = $('actionsBody').clientWidth >= 760;
      if (A.open && wide !== lastWide) { lastWide = wide; draw(); }
    }).observe($('actionsBody'));
  }
  if ($('actionsRow')) {
    window.rouhLater(function () {
      fetch('/api/actions', { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Rouh-Later': '1' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j) { if (!A.data) { A.data = j; } count(j.counts || {}); } })
        .catch(function () {});
    });
  }
}());
