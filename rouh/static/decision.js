/* One decision, drawn the one way it is drawn everywhere (`rouh/decisions.py`).

   Petar, 5 October 2026: "one model, one design, one place to look at them and
   make decisions. they can also be appearing contextually in their places but
   also in this one place." So this is the only drawing of a question waiting on
   him: the Decisions page lays these out one under another, and a task's page,
   a goal step's page, the Heartbeat and quest pages and a run's card each put
   the one that belongs to them in place. The same buttons, the same words, the
   same way back.

   What a card says, top to bottom:
   - its number, "Decision 42" ("#42" in a history line), which is what the
     person says to name it to Rouh (`decision_numbers.py`);
   - where it came from (a task, a goal step, an approval, a run, a landing),
     with the way to its context, how soon it matters and, where answering it
     spends money, sends, publishes or cannot be undone, that risk by name;
   - the question in plain words, why it matters, and what Rouh already
     prepared for it, so it is never asked cold; where a yes does several
     things one after another (a message's A, the reply that goes at once, B,
     the action, C, the reply with the result), each of them, in sight;
   - Rouh's recommendation and its one-line reason - drawn, never picked;
   - the answers as large buttons, each with what it means under it, and
     "Something else" for his own words where the question allows them;
   - what happens next; and Later, "Rouh, decide this one" (only on a question
     that can be changed later and has a recommendation), Dismiss where the
     source has the idea, and Show me the context.

   A decision that holds many small ones (`items`: one night of Synapse's link
   changes, say) answers them all at once with its options ("Approve all 32"),
   or one by one in its list, "Decide them one by one": an answer for each item
   picked, then one Send for those; what is left waits on in the same card.

   An answer that carries a gated risk asks once more, naming the risk, before
   it is sent; the server refuses it otherwise (409, `decisions.NeedsConfirm`).
   An answer is held for a few seconds with Undo before it goes back to the
   source that asked.

   It is a plain script, put into Rouh's page and into the sandboxed task pages
   alike, and it asks nothing of either beyond a `host`:
     host.act(id, act, body) -> Promise<{ok, status, out}>
     host.go(href)           open a context link
     host.changed(d)         a decision moved (optional)
   `RouhDecision.fetchHost()` is the host for Rouh's own page, signed in;
   `RouhDecision.frameHost()` hands every press up to it from a framed page. */
(function () {
  'use strict';

  var SOURCE_ICON = {
    task: '<path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/>',
    goal: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    approval: '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/><path d="M9 12l2 2 4-4"/>',
    run: '<path d="M4 17l6-6-6-6"/><path d="M12 19h8"/>',
    conflict: '<path d="M6 3v12"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    job: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    dream: '<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="M8.2 8.1l2.6 7.6M15.9 7.6l-2.7 8.1M8.4 7l7.2-.8"/>',
    nightly: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    meeting: '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.4"/><path d="M15.5 14.2A5 5 0 0 1 21 19"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.8 6.6l8.2 6.2 8.2-6.2"/>',
    offline: '<path d="M7 18h10a4 4 0 0 0 .7-7.9A6 6 0 0 0 6.2 9.3 4.4 4.4 0 0 0 7 18z"/><path d="M3 3l18 18"/>',
    promise: '<path d="M7 11V7a5 5 0 0 1 10 0v4"/><path d="M4 11h16v4a8 8 0 0 1-16 0z"/><path d="M12 14v3"/>',
    // A double helix: a gene the nightly run built.
    genes: '<path d="M7 3c0 6 10 6 10 12s-10 6-10 6"/><path d="M17 3c0 6-10 6-10 12s10 6 10 6"/><path d="M8.5 6.5h7M8.5 17.5h7"/>',
    casefix: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
    delegate: '<circle cx="8" cy="8" r="3"/><path d="M2.5 20a5.5 5.5 0 0 1 11 0"/><path d="M15 9h6M18 6l3 3-3 3"/>'
  };
  SOURCE_ICON.nightly = SOURCE_ICON.genes;
  SOURCE_ICON.after_meeting = SOURCE_ICON.meeting;
  /* Pages the server draws by itself, outside Rouh's page (a case's files): followed as plain
     links, since Rouh's page has no place of its own for them. A case itself,
     `/mail/case/<key>`, is Rouh's own since 15 October 2026 (`approvalspage.js`). */
  var SERVER_PAGE = /^\/mail\/case\/[^/?#]+\/./;
  var CONFIRM_WORDS = {
    money: 'Yes, spend it', sending: 'Yes, send it', publishing: 'Yes, publish it',
    irreversible: 'Yes, I understand'
  };
  /* Which answers' folds are open, by decision and answer, so a card drawn afresh when the
     list moves keeps them open. */
  var MORE_OPEN = {};
  /* How many of a decision's items its list shows at a time. */
  var ITEMS_SHOWN = 15;
  var LATER = [
    ['In an hour', function () { return Date.now() / 1000 + 3600; }],
    ['This evening', function () { return at(18, 0, 0); }],
    ['Tomorrow morning', function () { return at(9, 0, 1); }],
    ['Next week', function () { return at(9, 0, 7); }]
  ];

  function at(h, m, days) {
    var d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(h, m, 0, 0);
    if (d.getTime() <= Date.now() + 60000) { d.setDate(d.getDate() + 1); }
    return d.getTime() / 1000;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function icon(paths, cls) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.8');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    if (cls) { s.setAttribute('class', cls); }
    s.innerHTML = paths;
    return s;
  }
  function button(text, cls, act, title) {
    var b = el('button', 'dq-btn' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) { b.title = title; }
    if (act) { b.addEventListener('click', act); }
    return b;
  }
  /* Somewhere to go, as a link: a plain press goes there in this tab through the host;
     Cmd, Ctrl, Shift or the middle button are the browser's, for a new tab. A page the host
     has no place for is followed as a plain link; Rouh's page keeps the browser off every
     plain press on an in-app link (`app/helpers.js`), so there it is gone to from here. */
  function goLink(text, cls, href, host) {
    var a = el('a', cls, text);
    a.href = href;
    if (/^https?:\/\//i.test(href)) {
      // Somewhere outside Rouh - a message in Slack - in a tab of its own.
      a.target = '_blank';
      a.rel = 'noopener';
      return a;
    }
    a.setAttribute('data-inapp', '');
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) { return; }
      if (!host.go || SERVER_PAGE.test(href)) {
        if (e.defaultPrevented) { window.location.href = href; }
        return;
      }
      e.preventDefault();
      host.go(href);
    });
    return a;
  }
  /* A decision's prepared list holds the parts of what a yes does (`part`), drawn in sight,
     and the rest, folded under What Rouh prepared. */
  function partsOf(d) { return (d.prepared || []).filter(function (p) { return p && p.part; }); }
  function restOf(d) { return (d.prepared || []).filter(function (p) { return p && !p.part; }); }
  function ago(ts) {
    if (!ts) { return ''; }
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 90) { return 'just now'; }
    if (s < 3600) { return Math.round(s / 60) + ' min ago'; }
    if (s < 86400 * 2) { return Math.round(s / 3600) + ' h ago'; }
    return Math.round(s / 86400) + ' days ago';
  }
  function when(ts) {
    if (!ts) { return ''; }
    var d = new Date(ts * 1000), now = new Date();
    var t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) { return 'today ' + t; }
    var tom = new Date(now.getTime() + 86400000);
    if (d.toDateString() === tom.toDateString()) { return 'tomorrow ' + t; }
    return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) + ' ' + t;
  }
  function waiting(d) { return d.status === 'open' || d.status === 'snoozed' || d.status === 'failed'; }
  /* Its number, which is how the person names it out loud: "Decision 42", or "#42"
     where there is little room (`short`). */
  function numberTag(d, short) {
    if (!d.number) { return null; }
    var t = el('span', 'dq-number', short ? '#' + d.number : 'Decision ' + d.number);
    t.title = 'Say “decision ' + d.number + '” to Rouh to name this one';
    if (short) { t.setAttribute('aria-label', 'Decision ' + d.number); }
    return t;
  }
  function labelOf(d, id) {
    for (var i = 0; i < d.options.length; i++) { if (d.options[i].id === id) { return d.options[i].label; } }
    return '';
  }

  /* One decision. `opts.place` is 'page' on the Decisions page and 'context' where
     it arose; `opts.index` numbers it for the keyboard. */
  function card(d, host, opts) {
    opts = opts || {};
    var root = el('article', 'dq dq-' + d.status + ' dq-u-' + d.urgency + (d.gated ? ' dq-gated' : '')
      + (opts.place === 'context' ? ' dq-context' : ''));
    root.setAttribute('data-decision', String(d.id));
    root.tabIndex = -1;
    // A question answered only in words has its box open from the start.
    var state = { d: d, picked: [], confirming: null, other: !d.options.length && d.allow_other,
                  busy: false, error: '', timer: 0, each: {}, itemsOpen: false, itemsShown: ITEMS_SHOWN,
                  prefill: '' };
    root._dq = { state: state, pick: pickByNumber, other: openOther, later: openLater,
                 delegate: delegateIt, undo: undoIt, context: goContext };

    function act(what, body) {
      state.busy = true;
      state.error = '';
      draw();
      return host.act(d.id, what, body || {}).then(function (r) {
        state.busy = false;
        var out = (r && r.out) || {};
        if (out.decision) { state.d = out.decision; d = out.decision; }
        if (r && r.status === 409 && out.confirm) {
          // The server wants the risk itself confirmed: ask it, naming it.
          state.confirming = { body: body };
        } else if (!r || !r.ok) {
          state.error = out.error || 'That did not work. Try again.';
        } else {
          state.confirming = null;
          state.picked = [];
          state.each = {};
          state.other = false;
          if (host.changed) { host.changed(state.d, what); }
        }
        draw();
        return r;
      }, function () {
        state.busy = false;
        state.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
    }

    function answer(choice, text) {
      var body = { choice: choice, text: text || '' };
      if (d.gated && goes(choice, text)) {
        state.confirming = { body: body };
        draw();
        return;
      }
      act('answer', body);
    }
    function goes(choice, text) {
      for (var i = 0; i < d.options.length; i++) {
        if (choice.indexOf(d.options[i].id) >= 0 && d.options[i].go) { return true; }
      }
      return !!(text && d.text_acts);
    }
    function confirmIt() {
      var body = state.confirming.body;
      body.confirm = d.risk;
      act('answer', body);
    }
    function pickByNumber(n) {
      var o = d.options[n - 1];
      if (!o || !waiting(d) || state.busy) { return false; }
      if (d.answer_type === 'multi') {
        togglePick(o.id);
      } else {
        answer([o.id], '');
      }
      return true;
    }
    function togglePick(id) {
      var i = state.picked.indexOf(id);
      if (i >= 0) { state.picked.splice(i, 1); } else { state.picked.push(id); }
      draw();
    }
    function openOther() {
      if (!d.allow_other || !waiting(d)) { return false; }
      state.other = true;
      draw();
      var t = root.querySelector('.dq-other textarea');
      if (t) { t.focus(); }
      return true;
    }
    function openLater() {
      if (!waiting(d)) { return false; }
      var m = root.querySelector('.dq-later-menu');
      if (m) { m.hidden = !m.hidden; if (!m.hidden && m.firstChild) { m.firstChild.focus(); } }
      return true;
    }
    function delegateIt() {
      if (!d.can_delegate) { return false; }
      act('delegate', {});
      return true;
    }
    function undoIt() {
      if (d.status !== 'answered') { return false; }
      act('undo', {});
      return true;
    }
    function goContext() {
      if (d.link && SERVER_PAGE.test(d.link)) { window.location.href = d.link; return true; }
      if (d.link && host.go) { host.go(d.link); return true; }
      return false;
    }

    function draw() {
      d = state.d;
      clearTimeout(state.timer);
      root.className = 'dq dq-' + d.status + ' dq-u-' + d.urgency + (d.gated ? ' dq-gated' : '')
        + (opts.place === 'context' ? ' dq-context' : '') + (state.busy ? ' dq-busy' : '');
      root.textContent = '';
      root.appendChild(head());
      var body = el('div', 'dq-body');
      // The title, when the context line above does not already say it.
      // A title that already holds the question (a line's "Task 19, Pricing: Which price…")
      // is not drawn again above it.
      if (d.title && d.title.indexOf(d.question) < 0 && opts.place !== 'context'
          && String(d.context || '').indexOf(d.title) < 0) {
        body.appendChild(el('div', 'dq-title', d.title));
      }
      var q = el('p', 'dq-q', d.question);
      q.id = 'dq-q-' + d.id;
      body.appendChild(q);
      if (d.why) { body.appendChild(el('p', 'dq-why', d.why)); }
      // Somebody he gave authority over this decides it (`rouh/delegation.py`); he can
      // still answer first. And what a delegate recommended on one that stays his.
      if (d.decider && waiting(d)) {
        body.appendChild(el('p', 'dq-delegate', d.decider + ' decides this, by your grant' +
          (d.decider_told ? ', and was emailed it.' : '; Rouh emails it to them.') + ' You can still answer it first.'));
      }
      (d.delegate_notes || []).forEach(function (n) {
        var p = el('p', 'dq-delegate dq-delegate-note');
        p.appendChild(el('strong', '', n.name + ' recommends: '));
        p.appendChild(document.createTextNode(String(n.said || '').replace(n.name + ' recommends: ', '')));
        if (n.words) { p.appendChild(el('span', 'dq-delegate-words', ' \u201c' + n.words + '\u201d')); }
        if (n.why) { p.appendChild(el('span', 'dq-delegate-why', ' It is yours: ' + n.why + '.')); }
        body.appendChild(p);
      });
      root.appendChild(body);
      if (waiting(d)) {
        if (d.status === 'snoozed' && d.snoozed_until * 1000 > Date.now()) {
          var sn = el('div', 'dq-state dq-state-snoozed');
          sn.appendChild(el('span', '', 'Later: it comes back ' + when(d.snoozed_until) + '.'));
          sn.appendChild(button('Bring it back now', 'small', function () { act('wake', {}); }));
          root.appendChild(sn);
        }
        if (d.status === 'failed') {
          root.appendChild(el('div', 'dq-state dq-state-failed',
            'Your last answer could not be carried out: ' + (d.result || 'it failed') + ' Answer it again.'));
        }
        if (d.stale) {
          root.appendChild(el('div', 'dq-state dq-state-stale', 'Probably stale: ' + d.stale));
        }
        if (d.result && d.items && d.items.length && d.status === 'open') {
          // A group answered in part: what was done, and that the rest still wait.
          root.appendChild(el('div', 'dq-state dq-state-partly', 'Last answer: ' + d.result));
        } else if (d.result && d.status === 'open') {
          // Open again after an answer (`Applied.reopen`): what that answer did and who still
          // waits, or what Rouh asks back when the words fitted more than one answer.
          var back = el('div', 'dq-state dq-state-back', d.result);
          back.setAttribute('role', 'status');
          root.appendChild(back);
        }
        // What he already said in a chat that answers it (`rouh/answered_in_chat.py`).
        if (d.said && !state.confirming) { root.appendChild(saidBox(d.said)); }
        if (restOf(d).length) { root.appendChild(prepared()); }
        if (d.recommended) { root.appendChild(recommendation()); }
        if (state.confirming) {
          root.appendChild(confirmBar());
        } else {
          root.appendChild(options());
          if (d.items && d.items.length > 1) { root.appendChild(itemsBox()); }
          if (d.allow_other) { root.appendChild(other()); }
        }
        // Below the question and the answers, never above them (Petar, 8 October 2026).
        if (partsOf(d).length) { root.appendChild(partsList()); }
        if (d.then) { root.appendChild(el('p', 'dq-then', d.then)); }
        root.appendChild(foot());
      } else {
        root.appendChild(outcome());
      }
      if (state.error) {
        var e = el('p', 'dq-error', state.error);
        e.setAttribute('role', 'alert');
        root.appendChild(e);
      }
      if (d.status === 'answered' && d.apply_at) {
        // The undo window counting down, and the card read again once it has gone.
        state.timer = setTimeout(function () {
          if (!root.isConnected) { return; }
          if (d.apply_at * 1000 > Date.now()) { draw(); return; }
          host.act(d.id, 'get', {}).then(function (r) {
            var out = (r && r.out) || {};
            if (out.decision) { state.d = out.decision; if (host.changed) { host.changed(state.d, 'get'); } }
            if (root.isConnected) {
              if (out.decision && (out.decision.status === 'answered' || out.decision.status === 'applying')) {
                state.timer = setTimeout(draw, 1500);
              }
              draw();
            }
          });
        }, 1000);
      } else if (d.status === 'applying') {
        state.timer = setTimeout(function () {
          if (!root.isConnected) { return; }
          host.act(d.id, 'get', {}).then(function (r) {
            var out = (r && r.out) || {};
            if (out.decision) { state.d = out.decision; if (host.changed) { host.changed(state.d, 'get'); } }
            if (root.isConnected) { draw(); }
          });
        }, 1500);
      }
    }

    function head() {
      var h = el('header', 'dq-head');
      var tag = numberTag(d);
      if (tag) { h.appendChild(tag); }
      var src = el('span', 'dq-src');
      src.appendChild(icon(SOURCE_ICON[d.source] || SOURCE_ICON.task));
      src.appendChild(el('span', '', d.source_label));
      h.appendChild(src);
      if (d.context && opts.place !== 'context') {
        if (d.link && host.go) {
          h.appendChild(goLink(d.context, 'dq-ctx', d.link, host));
        } else {
          h.appendChild(el('span', 'dq-ctx', d.context));
        }
      }
      var pills = el('span', 'dq-pills');
      if (waiting(d) && (d.urgency === 'now' || d.urgency === 'today')) {
        pills.appendChild(el('span', 'dq-pill dq-pill-' + d.urgency, d.urgency_words));
      }
      if (d.items && d.items.length > 1) {
        pills.appendChild(el('span', 'dq-pill dq-pill-items', d.items.length + ' in one'));
      }
      if (d.gated) {
        var r = el('span', 'dq-pill dq-pill-risk', d.risk_words);
        r.title = d.risk_note || d.risk_words;
        pills.appendChild(r);
      }
      if (d.created_at && opts.place !== 'context') { pills.appendChild(el('span', 'dq-age', ago(d.created_at))); }
      h.appendChild(pills);
      return h;
    }

    /* What the sender already had, then what a yes does, part by part in the order it
       happens - a message's A, the reply that goes at once, B, the action, and C, the
       reply with the result (Petar, 8 October 2026). Each in a fold of its own, closed,
       its line saying what it is and a hint of what is inside; each cut short, the case's
       own page holding them whole. */
    function partsList() {
      var wrap = el('div', 'dq-parts');
      var all = partsOf(d);
      var sent = all.filter(function (p) { return p.part === 'sent'; });
      if (sent.length) {
        var box = fold('', sent[0].label, sent.length + (sent.length === 1 ? ' message' : ' messages')
          + ', the last ' + (String(sent[sent.length - 1].when || '').split(' · ')[2] || ''), 'sent');
        var ol = el('ol', 'dq-sent');
        sent.forEach(function (p) {
          var li = el('li');
          li.appendChild(el('span', 'dq-part-when', p.when));
          li.appendChild(el('p', 'dq-part-text', p.text));
          ol.appendChild(li);
        });
        box.appendChild(ol);
        wrap.appendChild(box);
      }
      all.forEach(function (p) {
        if (p.part === 'sent') { return; }
        var label = String(p.label || '').replace(/^[A-Z], /, '');
        var box = fold(p.part, label, p.hint || '', p.part);
        var body = el('div', 'dq-part-body');
        if (p.when) { body.appendChild(el('span', 'dq-part-when', p.when)); }
        body.appendChild(p.text ? el('p', 'dq-part-text', p.text) : el('p', 'dq-part-none', 'None written.'));
        if (p.files && p.files.length) {
          body.appendChild(el('p', 'dq-part-files', 'With ' + p.files.join(', ')));
        }
        box.appendChild(body);
        wrap.appendChild(box);
      });
      return wrap;
    }
    function fold(key, label, hint, part) {
      var box = el('details', 'dq-part');
      box.setAttribute('data-part', part);
      var sum = el('summary', 'dq-part-sum');
      if (key) { sum.appendChild(el('span', 'dq-part-key', key)); }
      sum.appendChild(el('span', 'dq-part-label', label));
      if (hint) { sum.appendChild(el('span', 'dq-part-hint', hint)); }
      box.appendChild(sum);
      return box;
    }

    function prepared() {
      var box = el('details', 'dq-prep');
      var s = el('summary', '', 'What Rouh prepared');
      box.appendChild(s);
      var ul = el('ul');
      restOf(d).forEach(function (p) {
        var li = el('li');
        if (p.href) {
          li.appendChild(goLink(p.label, '', p.href, host));
        } else {
          li.appendChild(el('span', 'dq-prep-label', p.label));
        }
        if (p.text) { li.appendChild(el('pre', 'dq-prep-text', p.text)); }
        ul.appendChild(li);
      });
      box.appendChild(ul);
      return box;
    }

    /* Above the answers: a message of his, in a chat since it was asked, that answers it
       (`rouh/answered_in_chat.py`): where and when, his words, what they answer, and two
       presses. Answer with that gives the offered answer his words amount to, the usual way
       (its undo, and its second press where a yes spends, sends or publishes); words of his
       own open Something else with them written in, for him to read and send. Not this keeps
       the question and never offers those words for it again. Nothing is answered unpressed. */
    function saidBox(s) {
      var box = el('section', 'dq-said');
      box.setAttribute('aria-label', 'You may have answered this already');
      var head = el('div', 'dq-said-head');
      head.appendChild(icon('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/><path d="M8.5 12l2.3 2.3 4.7-4.6"/>', 'dq-said-i'));
      head.appendChild(el('span', '', 'You may have answered this already'));
      box.appendChild(head);
      var where = el('p', 'dq-said-where');
      where.appendChild(document.createTextNode('In '));
      where.appendChild(goLink('\u201c' + (s.chat_title || 'a chat') + '\u201d', 'dq-said-chat', s.link, host));
      where.appendChild(document.createTextNode(', ' + when(s.at) + ', you said:'));
      box.appendChild(where);
      box.appendChild(el('blockquote', 'dq-said-quote', s.quote));
      var gives = el('p', 'dq-said-gives');
      if (s.option && s.option_label) {
        gives.appendChild(el('strong', '', 'That answers it: '));
        gives.appendChild(document.createTextNode(s.option_label + '.'));
        box.appendChild(gives);
      } else if (bare(s.answer) && bare(s.answer) !== bare(s.quote)) {
        // His answer put together from more than the words quoted; the same words once only.
        gives.appendChild(el('strong', '', 'Your answer, in your words: '));
        gives.appendChild(document.createTextNode(s.answer));
        box.appendChild(gives);
      }
      if (s.why) { box.appendChild(el('p', 'dq-said-why', s.why)); }
      var row = el('div', 'dq-said-row');
      var canPick = !!(s.option && s.option_label);
      var canSay = !canPick && d.allow_other && !!s.answer;
      if (canPick || canSay) {
        var use = button('Answer with that', 'primary dq-said-use', function () {
          if (canPick) {
            if (d.answer_type === 'multi') { state.picked = [s.option]; draw(); return; }
            // His own words go with the answer they amount to, where the question takes words.
            answer([s.option], d.allow_other ? (s.answer || '') : '');
            return;
          }
          state.prefill = s.answer;
          openOther();
        }, canPick ? 'Answer ' + s.option_label : 'Open your own words with this written in, to read and send');
        use.disabled = state.busy;
        row.appendChild(use);
      }
      var no = button('Not this', 'ghost dq-said-no', function () { act('not_this', {}); },
        'It stays open, and these words are not offered for it again');
      no.disabled = state.busy;
      row.appendChild(no);
      box.appendChild(row);
      return box;
    }

    function bare(t) { return String(t || '').replace(/[\s\u201c\u201d"]+/g, ' ').trim().toLowerCase(); }

    function recommendation() {
      var r = el('p', 'dq-rec');
      r.appendChild(icon('<path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z"/>', 'dq-rec-i'));
      var t = el('span');
      t.appendChild(el('strong', '', 'Rouh recommends ' + labelOf(d, d.recommended)));
      if (d.recommended_why) { t.appendChild(document.createTextNode(': ' + d.recommended_why)); }
      r.appendChild(t);
      return r;
    }

    function options() {
      var wrap = el('div', 'dq-opts');
      wrap.setAttribute('role', 'group');
      wrap.setAttribute('aria-labelledby', 'dq-q-' + d.id);
      var multi = d.answer_type === 'multi';
      d.options.forEach(function (o, i) {
        if (o.href) {
          /* A link, not an answer: it opens a page, such as a mail case's own. */
          var a = goLink('', 'dq-opt dq-opt-link', o.href, host);
          var at = el('span', 'dq-opt-top');
          at.appendChild(el('span', 'dq-opt-label', o.label));
          a.appendChild(at);
          if (o.detail) { a.appendChild(el('span', 'dq-opt-detail', o.detail)); }
          wrap.appendChild(a);
          return;
        }
        var b = el('button', 'dq-opt' + (o.id === d.recommended ? ' dq-opt-rec' : '')
          + (o.go && d.gated ? ' dq-opt-go' : ''));
        b.type = 'button';
        b.disabled = state.busy;
        if (multi) { b.setAttribute('aria-pressed', state.picked.indexOf(o.id) >= 0 ? 'true' : 'false'); }
        var top = el('span', 'dq-opt-top');
        if (opts.index != null && i < 9) { top.appendChild(el('kbd', 'dq-key', String(i + 1))); }
        top.appendChild(el('span', 'dq-opt-label', o.label));
        if (o.id === d.recommended) { top.appendChild(el('span', 'dq-opt-tag', 'Recommended')); }
        b.appendChild(top);
        if (o.detail) { b.appendChild(el('span', 'dq-opt-detail', o.detail)); }
        b.addEventListener('click', function () {
          if (multi) { togglePick(o.id); } else { answer([o.id], ''); }
        });
        if (o.more) {
          var box = el('div', 'dq-optw');
          box.appendChild(b);
          box.appendChild(moreOf(o));
          wrap.appendChild(box);
        } else {
          wrap.appendChild(b);
        }
      });
      if (multi) {
        var n = state.picked.length;
        var send = button(n ? 'Send the ' + (n === 1 ? 'one' : n) + ' picked' : 'Pick one or more',
          'primary dq-send-picked', function () {
            var t = root.querySelector('.dq-other textarea');
            answer(state.picked.slice(), t ? t.value.trim() : '');
          });
        send.disabled = !n || state.busy;
        wrap.appendChild(send);
      }
      return wrap;
    }

    /* What there is to read about one answer before picking it, folded under its button:
       opening it picks nothing, and each opens on its own (Petar, 9 October 2026, of two
       LinkedIn profiles: "I should be able to expand them and see the rest of the
       information you have on them"). */
    function moreOf(o) {
      var box = el('details', 'dq-more');
      var key = d.id + ':' + o.id;
      box.open = !!MORE_OPEN[key];
      box.addEventListener('toggle', function () {
        if (box.open) { MORE_OPEN[key] = true; } else { delete MORE_OPEN[key]; }
      });
      var sum = el('summary', 'dq-more-sum', 'More about ' + o.label);
      box.appendChild(sum);
      var body = el('div', 'dq-more-body');
      if (o.more.photo) {
        var img = document.createElement('img');
        img.className = 'dq-more-photo';
        img.alt = 'Photo on the profile';
        img.setAttribute('referrerpolicy', 'no-referrer');
        img.setAttribute('decoding', 'async');
        img.loading = 'lazy';
        img.addEventListener('error', function () { img.remove(); });
        img.src = o.more.photo;
        body.appendChild(img);
      }
      var dl = el('dl', 'dq-more-facts');
      (o.more.facts || []).forEach(function (f) {
        dl.appendChild(el('dt', '', f[0]));
        dl.appendChild(el('dd', '', f[1]));
      });
      body.appendChild(dl);
      if (o.more.href) {
        var a = el('a', 'dq-more-link', o.more.href_label || 'Open it');
        a.href = o.more.href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        body.appendChild(a);
      }
      box.appendChild(body);
      return box;
    }

    /* The small questions it holds, to answer one by one: each with its own Approve or
       Reject (the decision's options, by their `each` name), then one Send for the ones
       picked. Long lists show a page at a time. */
    function itemsBox() {
      var n = d.items.length;
      var box = el('details', 'dq-items');
      box.open = state.itemsOpen;
      box.addEventListener('toggle', function () { state.itemsOpen = box.open; });
      // A decision whose answers are all links (Mutations' line) holds items to open,
      // not to answer here: no picks and no Send.
      var answerable = d.options.some(function (o) { return !o.href; });
      var sum = el('summary', 'dq-items-sum');
      sum.appendChild(el('span', '', answerable ? 'Decide them one by one' : 'What is in it'));
      sum.appendChild(el('span', 'dq-items-n', String(n)));
      box.appendChild(sum);
      var ul = el('ul', 'dq-item-list');
      d.items.slice(0, state.itemsShown).forEach(function (it) { ul.appendChild(itemRow(it)); });
      box.appendChild(ul);
      if (n > state.itemsShown) {
        var more = button('Show ' + Math.min(ITEMS_SHOWN, n - state.itemsShown) + ' more, of '
          + (n - state.itemsShown) + ' left', 'small dq-items-more', function () {
          state.itemsShown += ITEMS_SHOWN;
          draw();
        });
        box.appendChild(more);
      }
      if (!answerable) { return box; }
      var picked = Object.keys(state.each).length;
      var row = el('div', 'dq-items-send');
      var send = button(picked ? 'Send ' + picked + (picked === 1 ? ' answer' : ' answers') : 'Pick answers above',
        'primary', function () {
          var body = { items: {} };
          for (var k in state.each) { body.items[k] = state.each[k]; }
          act('answer', body);
        });
      send.disabled = !picked || state.busy;
      row.appendChild(send);
      if (picked) {
        row.appendChild(button('Clear', 'ghost', function () { state.each = {}; draw(); }));
        row.appendChild(el('span', 'dq-hint dq-items-hint', picked < n
          ? 'The other ' + (n - picked) + ' stay here, waiting.' : 'All of them, each as you picked.'));
      }
      box.appendChild(row);
      return box;
    }

    function itemRow(it) {
      var li = el('li', 'dq-item' + (state.each[it.id] ? ' dq-item-picked' : ''));
      var main = el('div', 'dq-item-main');
      main.appendChild(el('div', 'dq-item-label', it.label));
      (it.sides || []).forEach(function (side) {
        var p = el('p', 'dq-item-side');
        if (side.href) {
          p.appendChild(goLink(side.label || 'Open', 'dq-item-side-l', side.href, host));
        } else {
          p.appendChild(el('span', 'dq-item-side-l', side.label || ''));
        }
        if (side.text) {
          var t = el('span', 'dq-item-text', side.text);
          t.title = 'Show it all';
          t.addEventListener('click', function () { t.classList.toggle('dq-item-whole'); });
          p.appendChild(t);
        }
        main.appendChild(p);
      });
      if (it.why) { main.appendChild(el('p', 'dq-item-why', it.why)); }
      if (it.detail) { main.appendChild(el('p', 'dq-item-detail', it.detail)); }
      li.appendChild(main);
      var picks = el('div', 'dq-item-picks');
      picks.setAttribute('role', 'group');
      picks.setAttribute('aria-label', 'Your answer for ' + it.label);
      d.options.forEach(function (o) {
        if (o.href || (it.options && it.options.indexOf(o.id) < 0)) { return; }
        var on = state.each[it.id] === o.id;
        var b = button((it.names && it.names[o.id]) || o.each || o.label, 'small dq-ipick dq-ipick-' + o.id, function () {
          if (state.each[it.id] === o.id) { delete state.each[it.id]; } else { state.each[it.id] = o.id; }
          draw();
        });
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.disabled = state.busy;
        picks.appendChild(b);
      });
      li.appendChild(picks);
      return li;
    }

    function other() {
      var box = el('div', 'dq-other');
      if (!state.other) {
        var open = button('Something else…', 'ghost dq-other-open', openOther,
          'Answer in your own words');
        open.disabled = state.busy;
        box.appendChild(open);
        return box;
      }
      var t = el('textarea');
      t.rows = 2;
      t.maxLength = 4000;
      // Written in by Answer with that, from what he said in a chat, for him to read and send.
      if (state.prefill) { t.value = state.prefill; t.rows = 5; state.prefill = ''; }
      t.placeholder = d.options.length ? 'Something else, in your own words' : 'Your answer';
      t.setAttribute('aria-label', 'Your own answer');
      var sendIt = function () {
        var words = t.value.trim();
        if (!words) { t.focus(); return; }
        answer(d.answer_type === 'multi' ? state.picked.slice() : [], words);
      };
      t.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); sendIt(); }
        if (e.key === 'Escape') { e.stopPropagation(); state.other = false; draw(); }
      });
      t.addEventListener('input', function () {
        t.style.height = 'auto';
        t.style.height = Math.min(t.scrollHeight, 240) + 'px';
      });
      box.appendChild(t);
      var row = el('div', 'dq-other-row');
      row.appendChild(el('span', 'dq-hint', 'Ctrl+Enter to send, Esc to close'));
      var s = button('Send', 'primary', sendIt);
      s.disabled = state.busy;
      row.appendChild(s);
      box.appendChild(row);
      return box;
    }

    function confirmBar() {
      var c = el('div', 'dq-confirm');
      c.setAttribute('role', 'alertdialog');
      c.setAttribute('aria-label', 'Confirm: ' + d.risk_words);
      var body = state.confirming.body;
      var which = body.choice && body.choice.length ? body.choice.map(function (id) { return labelOf(d, id); }).join(', ')
        : '“' + (body.text || '').slice(0, 120) + '”';
      c.appendChild(icon('<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4"/><path d="M12 17.5v.01"/>', 'dq-confirm-i'));
      var t = el('div', 'dq-confirm-text');
      t.appendChild(el('strong', '', d.risk_words + '.'));
      t.appendChild(el('span', '', ' ' + (d.risk_note || 'This cannot be taken back once it has gone.')));
      t.appendChild(el('span', 'dq-confirm-which', 'Your answer: ' + which));
      c.appendChild(t);
      var row = el('div', 'dq-confirm-row');
      var yes = button(CONFIRM_WORDS[d.risk] || 'Yes, go ahead', 'danger', confirmIt);
      yes.disabled = state.busy;
      row.appendChild(yes);
      row.appendChild(button('Cancel', '', function () { state.confirming = null; draw(); }));
      c.appendChild(row);
      setTimeout(function () { if (yes.isConnected) { yes.focus(); } }, 0);
      return c;
    }

    function foot() {
      var f = el('footer', 'dq-foot');
      var later = el('div', 'dq-later');
      var lb = button('Later', 'ghost', openLater, 'I will decide later');
      lb.setAttribute('aria-haspopup', 'menu');
      later.appendChild(lb);
      var menu = el('div', 'dq-later-menu');
      menu.setAttribute('role', 'menu');
      menu.hidden = true;
      LATER.forEach(function (pair) {
        var b = button(pair[0], 'dq-later-item', function () {
          menu.hidden = true;
          act('snooze', { until: pair[1]() });
        });
        b.setAttribute('role', 'menuitem');
        menu.appendChild(b);
      });
      menu.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.stopPropagation(); menu.hidden = true; lb.focus(); }
      });
      later.appendChild(menu);
      f.appendChild(later);
      if (d.can_delegate) {
        f.appendChild(button('Rouh, decide this one', 'ghost', delegateIt,
          'Rouh gives its recommended answer for you. Only for what can be changed later.'));
      }
      if (d.can_dismiss) {
        f.appendChild(button('Dismiss', 'ghost', function () { act('dismiss', {}); },
          'Close it without an answer. Nothing it asks about is done.'));
      }
      if (d.link && host.go && opts.place !== 'context' && d.link !== opts.here) {
        f.appendChild(goLink('Show me the context', 'dq-btn ghost dq-go', d.link, host));
      }
      return f;
    }

    function outcome() {
      var o = el('div', 'dq-state dq-state-' + d.status);
      o.setAttribute('role', 'status');
      var said = (d.answer && d.answer.said) || '';
      var who = d.answered_by === 'rouh' ? 'Rouh decided, as you asked'
        : d.by_itself ? 'Closed by itself'
        : d.decided_by ? 'Decided by ' + d.decided_by : 'You answered';
      var where = d.channel === 'offline' ? ' offline' : d.channel && d.channel !== 'screen' ? ' on ' + d.channel : '';
      if (d.status === 'queued') {
        // Answered with no connection: in this device's outbox until there is one.
        o.appendChild(el('span', '', 'You answered offline: '));
        o.appendChild(el('strong', '', said));
        o.appendChild(el('span', 'dq-going', ' It goes when this device is back online.'));
      } else if (d.status === 'answered') {
        var left = Math.max(0, Math.ceil(d.apply_at - Date.now() / 1000));
        o.appendChild(el('span', '', who + where + ': '));
        o.appendChild(el('strong', '', said));
        o.appendChild(el('span', 'dq-going', left > 0 ? ' Goes in ' + left + ' s.' : ' Going now…'));
        if (left > 0) {
          var u = button('Undo', 'small', undoIt);
          u.disabled = state.busy;
          o.appendChild(u);
        }
      } else if (d.status === 'applying') {
        o.appendChild(el('span', '', who + where + ': '));
        o.appendChild(el('strong', '', said));
        o.appendChild(el('span', 'dq-going', ' Carrying it out…'));
      } else if (d.status === 'applied') {
        o.appendChild(el('span', '', (said ? who + where + ': ' : 'Answered' + where + '.')));
        if (said) { o.appendChild(el('strong', '', said)); }
        if (d.decided_words) { o.appendChild(el('span', 'dq-delegate-words', ' \u201c' + d.decided_words + '\u201d')); }
        if (d.result) { o.appendChild(el('span', 'dq-result', ' ' + d.result)); }
        if (d.can_reopen) {
          var back = button('Undo', 'small', function () { act('reopen', {}); },
            'It was not kept: open it again');
          back.disabled = state.busy;
          o.appendChild(back);
        }
      } else if (d.status === 'dismissed') {
        o.appendChild(el('span', '', 'Dismissed. ' + (d.result || 'Nothing was done.')));
      } else if (d.status === 'expired') {
        o.appendChild(el('span', '', 'Ran out of time. ' + (d.result || '')));
      } else if (d.status === 'withdrawn') {
        o.appendChild(el('span', '', 'Not asked any more. ' + (d.result || '')));
      } else if (d.status === 'cleared') {
        // Rouh found it never needed him (`rouh/decision_gate.py`): why, what Rouh went on
        // with, and one press to make it his again.
        o.appendChild(el('span', '', d.result || 'Cleared by Rouh: it did not need you.'));
        if (d.can_reopen) {
          var again = button('Open again', 'small', function () { act('reopen', {}); },
            'Put it back on your list, to answer it yourself');
          again.disabled = state.busy;
          o.appendChild(again);
        }
      }
      return o;
    }

    draw();
    return root;
  }

  /* Rouh's own page: signed in, with the CSRF token on every write. */
  function fetchHost(more) {
    more = more || {};
    function token() {
      var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
      return found ? decodeURIComponent(found[1]) : '';
    }
    function zone() {
      try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
    }
    return {
      act: function (id, what, body) {
        var get = what === 'get';
        var url = '/api/decisions/' + encodeURIComponent(id) + (get ? '' : '/act');
        var payload = {};
        for (var k in (body || {})) { payload[k] = body[k]; }
        payload.act = what;
        // With no connection an answer goes into this device's outbox, and is given
        // through this same path once there is one (app/offline.js, `rouh/offline.py`).
        var outbox = window.RouhOffline;
        if (!get && outbox && !navigator.onLine) { return outbox.answerDecision(id, what, body || {}); }
        return fetch(url, {
          method: get ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Content-Type': 'application/json', 'X-Time-Zone': zone(), 'X-CSRFToken': token() },
          body: get ? undefined : JSON.stringify(payload)
        }).then(function (r) {
          if (r.status === 401) { location.href = '/login'; return { ok: false, status: 401, out: {} }; }
          return r.json().catch(function () { return {}; }).then(function (out) {
            return { ok: r.ok, status: r.status, out: out };
          });
        }, function (err) {
          // The request never reached Rouh: the same outbox as above.
          if (!get && outbox) { return outbox.answerDecision(id, what, body || {}); }
          throw err;
        });
      },
      go: more.go || function (href) { location.href = href; },
      changed: more.changed
    };
  }

  /* A page in a frame, which cannot reach Rouh itself: every press goes up to the page
     around it (`taskDecision` in app/cards.js), which checks it is this page's own
     question before it sends it, and the answer comes back as `rouh-frame-project`. */
  function frameHost() {
    var seq = 0, waitingOn = {};
    window.addEventListener('message', function (e) {
      var m = e.data;
      if (!m || m.type !== 'rouh-frame-project' || !waitingOn[m.id]) { return; }
      var done = waitingOn[m.id];
      delete waitingOn[m.id];
      done({ ok: !!m.ok, status: m.status || (m.ok ? 200 : 400), out: m.out || { error: m.error } });
    });
    function up(said) {
      var p;
      try { p = window.parent; } catch (err) { p = null; }
      if (!p || p === window) { return false; }
      try { p.postMessage(said, '*'); return true; } catch (err) { return false; }
    }
    return {
      act: function (id, what, body) {
        return new Promise(function (resolve) {
          var rid = 'd' + (++seq);
          waitingOn[rid] = resolve;
          if (!up({ type: 'rouh-page-decision', id: rid, decision: id, act: what, body: body || {} })) {
            delete waitingOn[rid];
            resolve({ ok: false, status: 0, out: { error: 'Open this page in Rouh to answer it.' } });
          }
        });
      },
      go: function (href) { up({ type: 'rouh-page-follow', href: href }); }
    };
  }

  /* A decision drawn as a short line, for the history. */
  function line(d, host) {
    var li = el('li', 'dq-line dq-line-' + d.status);
    var src = el('span', 'dq-src');
    src.appendChild(icon(SOURCE_ICON[d.source] || SOURCE_ICON.task));
    li.appendChild(src);
    var tag = numberTag(d, true);
    if (tag) { li.appendChild(tag); }
    var main = el('span', 'dq-line-main');
    main.appendChild(el('span', 'dq-line-q', d.question));
    var said = (d.answer && d.answer.said) || '';
    var words = { applied: said ? (d.decided_by ? 'Decided by ' + d.decided_by + ': '
                  : d.by_itself ? 'Closed by itself: ' : 'Answered: ') + said
                  : 'Answered', dismissed: 'Dismissed',
                  expired: 'Ran out of time', withdrawn: 'Not asked any more',
                  cleared: 'Cleared by Rouh' }[d.status] || d.status;
    var meta = el('span', 'dq-line-meta', words + (d.channel && d.channel !== 'screen' && said ? (d.channel === 'offline' ? ' (offline)' : ' (on ' + d.channel + ')') : '')
      + ' · ' + (d.context || d.source_label) + ' · ' + ago(d.resolved_at || d.updated_at));
    main.appendChild(meta);
    if (d.result && (d.status === 'applied' || d.status === 'cleared')) {
      main.appendChild(el('span', 'dq-line-result', d.status === 'cleared'
        ? d.result.replace(/^Cleared by Rouh:\s*/, '') : d.result));
    }
    li.appendChild(main);
    if (d.link && host && host.go) { li.appendChild(goLink('Open', 'dq-btn ghost small', d.link, host)); }
    if (d.can_reopen && host && host.act) {
      // Closed by itself at its source (a promise a later Slack message showed kept): Undo
      // opens it again, there and here (`decisions.reopen`).
      // Cleared by Rouh, because it never needed him: Open again makes it his once more.
      var undo = el('button', 'dq-btn ghost small', d.cleared ? 'Open again' : 'Undo');
      undo.type = 'button';
      undo.title = d.cleared ? 'Put it back on your list, to answer it yourself'
        : 'It was not kept: open it again';
      undo.addEventListener('click', function () {
        undo.disabled = true;
        host.act(d.id, 'reopen', {}).then(function (r) {
          if (r && r.ok) {
            meta.textContent = ((r.out && r.out.said) || 'Open again.');
            undo.remove();
            if (host.changed) { host.changed(d, 'reopen'); }
          } else {
            undo.disabled = false;
            main.appendChild(el('span', 'dq-line-result', (r && r.out && r.out.error) || 'That did not work.'));
          }
        });
      });
      li.appendChild(undo);
    }
    return li;
  }

  /* The same card again for a page that draws itself over and over (the Heartbeat page
     every fifteen seconds): kept while the decision has not moved, so a confirmation half
     way or words half typed in it are not thrown away by a redraw. */
  function kept(cache, d, host, opts) {
    var key = d.status + ':' + (d.updated_at || 0);
    var had = cache[d.id];
    if (had && had.key === key) { return had.node; }
    var node = card(d, host, opts);
    cache[d.id] = { key: key, node: node };
    return node;
  }

  /* A source's icon, as every place that names a decision's kind draws it. */
  function sourceIcon(source, cls) { return icon(SOURCE_ICON[source] || SOURCE_ICON.task, cls); }

  window.RouhDecision = { card: card, kept: kept, line: line, numberTag: numberTag, sourceIcon: sourceIcon,
                          fetchHost: fetchHost, frameHost: frameHost };

  /* A task's or a step's page that carries its decision (`objectindex._decision_mount`):
     drawn into its mount. At the page's own address there is no Rouh around it to answer
     to, and the card says so when pressed. */
  var mount = document.getElementById('dqMount');
  var carried = null;
  try { carried = mount ? JSON.parse(mount.getAttribute('data-decision') || 'null') : null; }
  catch (err) { carried = null; }
  if (mount && carried) {
    var framed = (window.ROUH_TASK || {}).framed;
    var host = framed ? frameHost() : {
      act: function () {
        return Promise.resolve({ ok: false, status: 0, out: { error: 'Open this page in Rouh to answer it.' } });
      }
    };
    mount.appendChild(card(carried, host, { place: 'context' }));
  }
}());
