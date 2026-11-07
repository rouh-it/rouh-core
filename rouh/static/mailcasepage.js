/* What they asked, and Petar's decision on each, at the top of a mail case's
   page (`mail_case.html`, `/mail/case/<key>`), which Rouh shows in a frame
   inside the Approvals layer, with the orb beside it (`approvalspage.js`).

   Petar, 15 October 2026 (fr_7d4948ef128b): "There are x things that are
   required/requested and I need to clearly see for each: what it is, what is
   the status and my controls for one time approval or creating a grant or
   giving a grant to a person. Those x things should be grouped and at the end
   of the group test button and redo. Anything that is a user-guide
   explanation should be in (i) icon."

   So these are the case's asks (`mail_ledger`), in two groups: what the
   sender asked, and what the work found it needs, each group ending with Test
   (each ask as a run would take it now, nothing done) and Redo (his run of it).

   The same evening (fr_bfda0e144e7c): the old page's decisions kept, "What
   they asked" and "Your decision" one thing. So an ask that waits on him sits
   in its decision, the old page's box, with the other asks that need the same
   grant (`trusted._case_box`): a grant card - its name, whether it is new,
   made under another or an existing one expanded, where it sits, what it lets
   Rouh do, who holds it, what it covers and its prompt, each named for what
   it is - with step 1, setting it up; then step 2, what the contact gets. How
   it works is behind the (i). An ask's why is under its own Details.

   Then (fr_1dd66d24e1f6) "notice the ai slop": an ask is named in a few words
   and quoted in the sender's own words, and the long sentence the work wrote
   is said once, under Details. The two boxes are Grant and Contact, each with
   its number in the top left corner, filled green when it is done, never
   covered by a tick; no To do, Final or Can change. Contact's four choices are
   each explained behind an (i), the chosen one stays pressed, and a press is
   saved at once, with Saving…, then a tick or what went wrong, in its box.

   This was a page of its own inside Rouh for that evening, beside the old
   page; then (fr_65ed87c8685b) "The new approvals page should be merged into
   the old one, and there should be 1 url". Who sent it, the message, what
   went back, every step, the logs and fixes are the old page's own, drawn by
   the server around this.

   Read from GET /api/mail/case/<key>, pressed with POST to the same address
   (`trusted.case_api`), and drawn again when the case's stamp moves
   (`/mail/case/<key>/state`). A link goes through Rouh around the frame
   (`window.caseHost`, from the page), so it never leaves the app. */
(function () {
  'use strict';

  var C = { key: '', data: null, error: '', busy: '', said: '', bad: false, where: '', tests: {},
            seq: 0, timer: 0, body: null, cals: null, calsAsked: false, calPick: {}, pick: {},
            prop: {}, why: {} };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function api() { return '/api/mail/case/' + encodeURIComponent(C.key); }

  /* ---- reading, and drawing again when the case moves ---- */

  function load() {
    var seq = ++C.seq;
    return fetch(api(), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { window.top.location.href = '/login?next=' + encodeURIComponent('/mail/case/' + C.key); return; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== C.seq) { return; }
          if (!r.ok || !j || !j.case) {
            C.error = (j && j.error) || 'The case could not be read. Try again in a moment.';
          } else {
            C.error = '';
            took(j.case);
          }
          draw();
        });
      })
      .catch(function () {
        if (seq !== C.seq) { return; }
        C.error = 'The server could not be reached. Try again in a moment.';
        draw();
      });
  }

  function took(data) {
    C.data = data;
  }

  function watch() {
    stop();
    C.timer = window.setInterval(function () {
      if (!C.data || C.busy || document.hidden || typing()) { return; }
      fetch(C.data.path + '/state', { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (j && C.data && j.stamp && j.stamp !== C.data.stamp && !C.busy) {
            // What a press said is about the case as it was; it has moved since.
            C.said = '';
            C.bad = false;
            C.where = '';
            load();
          }
        })
        .catch(function () {});
    }, 5000);
  }
  function stop() {
    if (C.timer) { window.clearInterval(C.timer); C.timer = 0; }
  }
  /* A grant's words being edited: the page is not drawn again under the person typing. */
  function typing() {
    var a = document.activeElement;
    return !!(a && C.body && C.body.contains(a) && /^(INPUT|TEXTAREA)$/.test(a.tagName));
  }

  /* ---- pressing ---- */

  /* A press, saved at once. `box` is the box it was pressed in, {where, said}: what it is doing
     and what came of it are said there, in the page's own words, rather than at the top. */
  function press(what, payload, box) {
    if (C.busy || !C.data) { return Promise.resolve(false); }
    C.busy = what;
    C.said = '';
    C.bad = false;
    C.where = box ? box.where : '';
    draw();
    return post(api(), payload)
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (j) {
          C.busy = '';
          if (j && j.case) { took(j.case); }
          var ok = !!(r.ok && j && j.ok);
          if (!ok) {
            C.bad = true;
            C.said = (j && j.error) || 'It could not be done. Try again in a moment.';
          } else {
            // A test's result is said once, at the end of its group, never here as well.
            C.said = j.test ? '' : box ? box.said : j.said || 'Done.';
            if (j.test && payload.group) {
              var rows = {};
              j.test.forEach(function (t) { rows[t.id] = t; });
              C.tests[payload.group] = rows;
            }
          }
          draw();
          return ok;
        });
      })
      .catch(function () {
        C.busy = '';
        C.bad = true;
        C.said = 'The server could not be reached, so nothing was done. Try again in a moment.';
        draw();
        return false;
      });
  }

  function post(url, payload) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  }

  /* ---- the (i): how the page works, opened in place, never on its own ---- */

  var INFO_SVG = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.4" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="6.2" r="1.15" fill="currentColor"/>' +
    '<path d="M10 9v5.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

  var infoSeq = 0;
  /* An (i) button, and the note it opens, which the caller puts where it reads best. */
  function info(label, lines, key) {
    var id = key ? 'note-' + key : 'mcInfo' + (++infoSeq);
    var b = el('button', 'mc-i');
    b.type = 'button';
    b.innerHTML = INFO_SVG;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', id);
    var note = el('div', 'mc-guide');
    note.id = id;
    note.hidden = true;
    lines.filter(Boolean).forEach(function (t) {
      if (typeof t === 'string') { note.appendChild(el('p', '', t)); return; }
      var p = el('p', '');
      p.appendChild(el('b', '', t[0]));
      p.appendChild(document.createTextNode(' ' + t[1]));
      note.appendChild(p);
    });
    if (key) { b.id = 'about-' + key; }
    b.addEventListener('click', function () {
      note.hidden = !note.hidden;
      b.setAttribute('aria-expanded', note.hidden ? 'false' : 'true');
    });
    return { button: b, note: note };
  }

  /* ---- drawing ---- */

  /* A link to somewhere else in Rouh, which goes there around the frame. */
  function inApp(a, href) {
    a.href = href;
    a.addEventListener('click', function (e) {
      var host = window.caseHost;
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || !host || !host.go) { return; }
      e.preventDefault();
      host.go(href);
    });
    return a;
  }

  function guideFor(d, g) {
    var first = d.first || 'them';
    return [
      g.key === 'needed'
        ? 'What the work Rouh started found it needs, and could not get with the grants there are.'
        : 'What ' + first + ' asked for, as Rouh read the ' + d.noun + '.',
      'Each choice is saved the moment you press it, and the one you chose stays pressed. Press another ' +
        'to change it, at any time.',
      ['Grant', 'is what it needs: a grant Rouh’s code proposes, in one sentence made from exactly what it ' +
        'would give. Narrow it, and the sentence is made again; Give gives exactly what the sentence says.'],
      ['Contact', 'is what ' + first + ' gets. The (i) beside each choice says what it does. Give permanently ' +
        'takes effect at once; the other three wait for Redo.'],
      ['Test', 'shows at once what a run would do now. Nothing is sent, written or done.'],
      ['Redo', 'runs the whole ' + d.noun + ' with your choices.']
    ];
  }

  /* The long explanation, why it stands where it does, what shows it done: said once, folded,
     closed until pressed. The sender's own words are above it, never here as well. */
  function details(it) {
    var whys = [it.about, it.why,
                it.possible ? 'A run does it now: ' + it.possible + '.' : ''].concat(it.evidence || []).filter(Boolean);
    if (!whys.length) { return null; }
    var why = el('details', 'mc-why');
    why.id = 'details-' + it.id;
    why.appendChild(el('summary', '', 'Details'));
    whys.forEach(function (t) { why.appendChild(el('p', '', t)); });
    return why;
  }

  /* An ask: what it is in a few words, the sender's own words asking it, its status, what it
     was started as, and its test. */
  function askRow(it, test, cls) {
    var row = el('div', cls || 'mc-ask');
    row.id = 'ask-' + it.id;
    row.setAttribute('data-status', it.status);
    var top = el('div', 'mc-row');
    top.appendChild(el('span', 'mc-what', it.what));
    top.appendChild(el('span', 'mc-pill mc-' + (it.tone || 'busy'), it.words));
    row.appendChild(top);
    if (it.quote) {
      var q = el('blockquote', 'mc-quote', '“' + it.quote.replace(/^[“"]+|[”"]+$/g, '') + '”');
      q.id = 'quote-' + it.id;
      row.appendChild(q);
    }
    var line = el('div', 'mc-line');
    if (!it.box && it.needs && it.status !== 'done' && it.status !== 'started') {
      line.appendChild(el('span', 'mc-need', it.needs));
    }
    (it.work || []).forEach(function (w) {
      var span = el('span', 'mc-work');
      span.appendChild(document.createTextNode(it.status === 'done' ? 'Done as ' : 'Started as '));
      if (w.href) { span.appendChild(inApp(el('a', '', w.title), w.href)); }
      else { span.appendChild(el('span', '', w.title)); }
      if (w.now) { span.appendChild(el('span', 'mc-pill mc-' + (w.tone || 'busy'), w.now)); }
      line.appendChild(span);
    });
    if (test) {
      line.appendChild(el('span', 'mc-test ' + (test.goes ? 'mc-goes' : 'mc-held'),
        test.goes ? '✓ Test: it goes' : '✕ Test: ' + test.words.toLowerCase()));
    }
    if (line.childNodes.length) { row.appendChild(line); }
    var why = details(it);
    if (why) { row.appendChild(why); }
    return row;
  }

  function item(it, test) {
    var li = el('li', 'mc-item');
    li.setAttribute('data-status', it.status);
    li.appendChild(askRow(it, test, 'mc-ask mc-ask-solo'));
    return li;
  }

  function btn(text, cls, on, title) {
    var b = el('button', 'mc-btn' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) { b.title = title; }
    if (on) { b.addEventListener('click', on); }
    return b;
  }

  /* A choice pressed in a box: saved at once, and said in that box - saving, saved or why not. */
  function choose(where, said, asks, act, target, more) {
    var payload = { do: 'choose', asks: asks, act: act, target: target || '' };
    Object.keys(more || {}).forEach(function (k) { payload[k] = more[k]; });
    return press(act + ':' + asks[0], payload, { where: where, said: said });
  }

  /* What the last press in this box is doing, or did: a spinner while it saves, then a tick
     or what went wrong. Nothing when the last press was elsewhere. */
  function pressLine(where) {
    var line = el('p', 'mc-saved');
    line.id = 'saved-' + where;
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    if (C.where !== where || !(C.busy || C.said)) { line.hidden = true; return line; }
    if (C.busy) {
      line.classList.add('mc-saving');
      line.appendChild(el('span', 'mc-spin'));
      line.appendChild(document.createTextNode('Saving…'));
    } else {
      line.classList.add(C.bad ? 'mc-bad' : 'mc-ok');
      line.appendChild(el('span', 'mc-mark', C.bad ? '✕' : '✓'));
      line.appendChild(document.createTextNode(C.said));
    }
    return line;
  }

  /* What happens to the grant, in two or three words, and in a line when the words add to it. */
  function kindOf(d, gr) {
    var parent = gr.path && gr.path.length ? gr.path[gr.path.length - 1] : '';
    switch (gr.kind) {
      case 'new': return ['New grant', '', 'new'];
      case 'sub': return ['New sub grant', 'Rouh would create it under ' + parent + '.', 'new'];
      case 'expand': return ['Expands a grant', 'Rouh would widen ' + gr.canonical + ', which exists, to cover this.', 'new'];
      case 'exists': return ['Existing grant', 'It is there already: nothing to create.', 'ok'];
      // Not where it was made from: the pill says it is done, and Sits says where it is
      // (Petar, 16 October 2026, fr_c622df46477c).
      case 'made': return [gr.made === 'merge_into' ? 'Expanded' : 'Created', '', 'ok'];
      // Letting them edit one task: a permission of the task, never a grant (MAIL.md D28).
      case 'task': return ['Task permission', '', gr.level === 'edit' ? 'ok' : 'new'];
      default: return ['Hard limit', 'No grant can lift it: only you decide it, ask by ask.', 'limit'];
    }
  }

  var TOOL_WORDS = { assistant_job: 'Work for them in your workspace', check_tasks: 'Check tasks',
                     look_at_task: 'Look at a task' };
  function toolSaid(t) {
    if (TOOL_WORDS[t]) { return TOOL_WORDS[t]; }
    var s = String(t).replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function fact(dl, term, value) {
    var row = el('div', 'mc-fact');
    row.appendChild(el('dt', '', term));
    var dd = el('dd', '');
    if (typeof value === 'string') { dd.textContent = value; } else { dd.appendChild(value); }
    row.appendChild(dd);
    dl.appendChild(row);
  }

  /* The head of Grant and of Contact, the same in both: the step's number in the top left
     corner, filled green once it is done and never covered by a tick, the box's name, and a
     pill that says what it is about. */
  function boxHead(n, title, done, pill, pillCls, doneWords) {
    var h = el('div', 'mc-box-head' + (done ? ' mc-st-done' : ''));
    if (n) {
      var dot = el('span', 'mc-dot', String(n));
      dot.setAttribute('aria-hidden', 'true');
      h.appendChild(dot);
    }
    h.appendChild(el('span', 'mc-box-title', title));
    if (pill) { h.appendChild(el('span', 'mc-kind ' + (pillCls || ''), pill)); }
    if (n) {
      // Read out, as the colour cannot be: "Step 1, done" or "Step 1".
      h.appendChild(el('span', 'mc-sr', 'Step ' + n + (done ? ', ' + (doneWords || 'done') : '')));
    }
    return h;
  }

  /* A proposal made from what the work needed has the work's sentence for its name and its
     words: that sentence is the ask's, under Details above, and never said here again. */
  function fromTheAsk(gr) {
    var name = String(gr.canonical || '').replace(/…$/, '');
    return !!gr.description && !!name && gr.description.indexOf(name) === 0;
  }

  /* Grant, step 1: the grant the box decides on - what it is, where it sits, what it lets Rouh
     do, who holds it, its prompt - and setting it up. */
  function grantCard(d, b) {
    var gr = b.grant;
    if (gr.kind === 'once') { return onceCard(d, b); }
    if (gr.kind === 'proposal' || gr.kind === 'unsupported') { return proposalCard(d, b); }
    var where = 'grant-' + b.n;
    var card = el('section', 'mc-box mc-gcard mc-k-' + gr.kind);
    card.id = where;
    card.setAttribute('aria-label', 'Grant');
    var k = kindOf(d, gr);

    if (gr.kind === 'task') {
      var first = d.first || 'They';
      card.setAttribute('aria-label', 'Permission');
      card.appendChild(boxHead(0, 'Permission: Task ' + gr.task, gr.level === 'edit', k[0], 'mc-kind-' + k[2]));
      if (gr.title) { card.appendChild(el('p', 'mc-gc-title', gr.title)); }
      card.appendChild(el('p', 'mc-gc-kind', gr.level === 'edit' ? first + ' may edit it.' :
        gr.level === 'view' ? first + ' may only read it now.' : first + ' may not open it now.'));
      return card;
    }
    if (gr.kind === 'limit') {
      card.appendChild(boxHead(0, 'Grant', false, k[0], 'mc-kind-' + k[2]));
      card.appendChild(el('p', 'mc-gc-title', gr.limit ? gr.limit.charAt(0).toUpperCase() + gr.limit.slice(1) + '.' : ''));
      card.appendChild(el('p', 'mc-gc-kind', k[1] + ' Allow it once, or not.'));
      return card;
    }
    var done = gr.kind === 'exists' || gr.kind === 'made';
    // Its head is the grant by its canonical name, "Grant: Your calendar", even when Rouh
    // proposed it from the work's own sentence (Petar, 16 October 2026, fr_c622df46477c).
    var head = boxHead(1, 'Grant: ' + gr.canonical, done, k[0], 'mc-kind-' + k[2], k[0].toLowerCase());
    var named = head.querySelector('.mc-box-title');
    named.classList.add('mc-gc-name');
    named.id = 'grantName-' + b.n;
    card.appendChild(head);
    var own = fromTheAsk(gr);
    // What the asks' Details say already is never said again here (Petar, 18 October 2026,
    // fr_aa3ca23c06f7: "It is either a prompt or a detail, not displayed billion times").
    var said = {};
    (d.groups || []).forEach(function (g) {
      g.items.forEach(function (it) {
        if (it.box === b.key) { [it.about, it.why].forEach(function (t) { if (t) { said[plain(t)] = true; } }); }
      });
    });
    function saidAlready(t) { return !!said[plain(t)]; }
    if (k[1]) { card.appendChild(el('p', 'mc-gc-kind', k[1])); }
    var title = own ? '' : gr.title || '';
    var same = !!title && !!gr.description && gr.description.indexOf(title.replace(/…$/, '')) === 0;
    if (same) { title = gr.description; }
    if (saidAlready(title)) { title = ''; }
    if (title) {
      var line = el('p', 'mc-gc-title', title);
      card.appendChild(line);
    }

    var dl = el('dl', 'mc-facts');
    if (gr.kind === 'expand' && gr.proposed && gr.proposed !== gr.canonical) {
      fact(dl, 'This part', gr.proposed);
    }
    if (gr.path && gr.path.length) {
      var at = el('span', 'mc-path');
      gr.path.forEach(function (p) {
        at.appendChild(el('span', 'mc-chip', p));
        at.appendChild(el('span', 'mc-sep', '›'));
      });
      at.appendChild(el('span', 'mc-chip mc-chip-me', gr.canonical));
      fact(dl, 'Sits under', at);
    } else {
      fact(dl, 'Sits', 'At the top level, under no other grant');
    }
    var can = el('span', 'mc-tools');
    if (gr.inbox) {
      can.appendChild(el('span', 'mc-dim', 'Your inbox, as far as their page allows.'));
    } else if (gr.tools && gr.tools.length) {
      gr.tools.forEach(function (t) {
        var c = el('span', 'mc-chip', toolSaid(t));
        c.title = t;
        can.appendChild(c);
      });
      if (gr.tools_from) { can.appendChild(el('span', 'mc-dim', 'from ' + gr.tools_from)); }
    } else {
      can.appendChild(el('span', 'mc-dim', 'Go ahead with asks like this one without asking you. It adds ' +
        'nothing Rouh can do: only what it can already do for ' + (d.first || 'them') + '.'));
    }
    fact(dl, 'Lets Rouh', can);
    if (gr.lifts) { fact(dl, 'Lifts', 'The hard limit on ' + gr.lifts + ', for whoever holds it'); }
    var people = (gr.affects || []).join(', ');
    if (gr.kind === 'expand') { fact(dl, 'Widens it for', people || 'nobody yet: nobody holds it'); }
    else if (gr.kind === 'sub') { fact(dl, 'Also goes to', people ? people + ', who hold ' + gr.path[gr.path.length - 1] : 'nobody yet'); }
    else if (gr.kind !== 'new') { fact(dl, 'Held by', people || 'nobody yet'); }
    if (gr.nearest) { fact(dl, 'Closest grant', gr.nearest); }
    card.appendChild(dl);

    if (gr.description && !same && !own && !saidAlready(gr.description)) {
      var full = el('details', 'mc-fold');
      full.id = 'grantAbout-' + b.n;
      full.appendChild(el('summary', '', 'What it covers'));
      full.appendChild(el('p', 'mc-fold-text', gr.description));
      card.appendChild(full);
    }
    if (gr.addition && gr.kind === 'expand') {
      var add = el('div', 'mc-add');
      add.appendChild(el('span', 'mc-add-head', 'Expanding adds to its prompt'));
      add.appendChild(el('p', 'mc-fold-text', gr.addition));
      card.appendChild(add);
    }
    // A grant's prompt is told to nothing since grants are data (CAPABILITIES.md): not shown.
    card.appendChild(pressLine(where));
    return card;
  }

  function plain(t) { return String(t || '').replace(/\s+/g, ' ').trim(); }

  /* A one-off: what one case needed, which no grant covers and which is no grant of its own
     (Petar, 18 October 2026, fr_aa3ca23c06f7: "either we create grant and assign to <the contact> or
     we just fix this manually once"). Two routes in one box - allow it this once, which leaves
     nothing in Grants, or give them a grant: one there is, or a new category named here - and
     Decline or I'll see to it. What was chosen stays pressed and is said in the box. */
  function onceCard(d, b) {
    var first = d.first || 'them';
    var where = 'grant-' + b.n;
    var card = el('section', 'mc-box mc-gcard mc-k-once');
    card.id = where;
    card.setAttribute('aria-label', 'Your approval');
    var chosen = b.options.find(function (o) { return o.chosen; });
    var head = boxHead(0, 'Your approval', !!chosen, 'No grant covers it', 'mc-kind-new');
    head.querySelector('.mc-box-title').classList.add('mc-gc-name');
    card.appendChild(head);
    var opt = {};
    b.options.forEach(function (o) { opt[o.key] = o; });
    var pending = C.busy && C.where === where ? C.busy : '';
    function choice(key, label, cls, more, said) {
      var o = opt[key] || {};
      var on = pending ? pending === 'contact:' + key + ':' + b.asks[0] : !!o.chosen;
      var x = btn(label, (on ? 'mc-on' : cls || '') + (on && pending ? ' mc-pending' : ''), function () {
        if (o.chosen && !more) { return; }
        choose(where, said, b.asks, 'contact:' + key, '', more);
      });
      x.id = 'choice-' + key + '-' + b.n;
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (C.busy) { x.disabled = true; }
      return x;
    }

    // This once.
    var once = el('div', 'mc-step mc-route');
    once.id = 'routeOnce-' + b.n;
    once.appendChild(el('span', 'mc-choice-head', 'Just this once'));
    var row = el('div', 'mc-acts');
    row.appendChild(choice('once', 'Allow once', 'mc-strong', null,
                           'Saved: allowed once. Nothing was added to your grants.'));
    var i1 = info('What Allow once does', ['Rouh does it this once, when you press Redo. Nothing is ' +
      'added to your grants or to ' + first + '’s page.'], 'once-' + b.n);
    row.appendChild(i1.button);
    once.appendChild(row);
    once.appendChild(i1.note);
    card.appendChild(once);

    // Or a grant, for this and later asks like it.
    var give = el('div', 'mc-step mc-route');
    give.id = 'routeGrant-' + b.n;
    give.appendChild(el('span', 'mc-choice-head', 'Or give ' + first + ' a grant, for this and later asks like it'));
    if (!b.listed) {
      give.appendChild(el('p', 'mc-alt-said', 'Only somebody on your Trusted contacts can be given a grant.'));
    } else {
      var pickRow = el('div', 'mc-alt-row');
      var sel = el('select', 'mc-select');
      sel.id = 'grantPick-' + b.n;
      sel.setAttribute('aria-label', 'The grant to give ' + first);
      var none = el('option', '', 'Pick a grant');
      none.value = '';
      sel.appendChild(none);
      (d.parents || []).forEach(function (g) {
        var o = el('option', '', g.label);
        o.value = g.key;
        if (C.pick['grant-' + b.n] === g.key) { o.selected = true; }
        sel.appendChild(o);
      });
      var giveBtn = btn('Give it', '', function () {
        var g = (d.parents || []).find(function (x) { return x.key === sel.value; });
        if (!g) { return; }
        choose(where, 'Saved: ' + first + ' was given ' + g.label + '.', b.asks, 'contact:grant', '',
               { grant: g.key });
      });
      giveBtn.id = 'giveGrant-' + b.n;
      giveBtn.disabled = !!C.busy || !sel.value;
      sel.addEventListener('change', function () {
        C.pick['grant-' + b.n] = sel.value;
        giveBtn.disabled = !!C.busy || !sel.value;
        said();
      });
      if (C.busy) { sel.disabled = true; }
      pickRow.appendChild(sel);
      pickRow.appendChild(giveBtn);
      give.appendChild(pickRow);
      var who = el('p', 'mc-alt-said');
      function said() {
        var g = (d.parents || []).find(function (x) { return x.key === sel.value; });
        who.hidden = !g;
        if (g) { who.textContent = 'Held now by ' + ((g.holders || []).join(', ') || 'nobody') + '.'; }
      }
      said();
      give.appendChild(who);
    }
    card.appendChild(give);

    // Or not at all.
    var no = el('div', 'mc-step mc-route');
    no.id = 'routeNo-' + b.n;
    var nrow = el('div', 'mc-opts');
    var notes = el('div', 'mc-opt-notes');
    [['decline', 'Decline', 'mc-danger'], ['mine', 'I\'ll see to it', '']].forEach(function (k) {
      var o = opt[k[0]];
      if (!o) { return; }
      var one = el('span', 'mc-opt');
      one.appendChild(choice(k[0], o.label, k[2], null, 'Saved: ' + o.label + '.'));
      var i = info('What ' + o.label + ' does', [o.said], k[0] + '-' + b.n);
      one.appendChild(i.button);
      nrow.appendChild(one);
      notes.appendChild(i.note);
    });
    no.appendChild(nrow);
    no.appendChild(notes);
    card.appendChild(no);

    // Which route was taken, said in the box for as long as it stands.
    if (chosen && !pending && !(C.where === where && C.said)) {
      card.appendChild(el('p', 'mc-saved mc-ok', chosen.key === 'once'
        ? '✓ You allowed it once. Nothing was added to your grants.'
        : '✓ You chose ' + chosen.label + '.'));
    }
    card.appendChild(pressLine(where));
    return card;
  }

  /* Contact, step 2: what the contact gets. Four choices, each explained behind its own (i);
     the one chosen stays pressed, any other can be pressed instead at any time, and each press
     is saved at once, said in the box. */
  function contract(d, b) {
    var first = d.first || 'them';
    var where = 'contact-' + b.n;
    var s = el('section', 'mc-box mc-contract');
    s.id = 'step2-' + b.n;
    s.setAttribute('aria-label', 'Contact');
    var chosen = b.options.find(function (o) { return o.chosen; });
    var n = b.grant.kind === 'limit' || b.grant.kind === 'task' ? 1 : 2;
    var head = boxHead(n, 'Contact', !!chosen, d.name || first, 'mc-kind-who',
                       chosen ? 'chosen: ' + chosen.label : '');
    // Their name opens their page in Trusted contacts, to change what they are trusted for
    // (Petar, 16 October 2026, fr_c622df46477c).
    var who = head.querySelector('.mc-kind-who');
    if (d.contact_href && who) {
      var link = inApp(el('a', 'mc-kind mc-kind-who mc-who-link', who.textContent), d.contact_href);
      link.id = 'contactLink-' + b.n;
      link.title = (d.name || first) + ' in Trusted contacts';
      who.replaceWith(link);
    }
    s.appendChild(head);
    // A calendar grant is given one calendar at a time (Petar, 16 October 2026): the ones
    // ticked here go with Give permanently, never every calendar at once. A grant Rouh's code
    // proposes names its calendars in its own box, above.
    var prop = b.grant.kind === 'proposal' ? propOf(b) : null;
    var grantOpt = b.options.find(function (o) { return o.key === 'grant' && !o.off; });
    var cal = b.grant.by_calendar && grantOpt && !prop ? calendarPick(d, b, where, !!grantOpt.chosen) : null;
    if (cal) { s.appendChild(cal.part); }
    s.appendChild(el('span', 'mc-choice-head', 'Your choice'));
    var row = el('div', 'mc-opts');
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', 'What ' + first + ' gets');
    var notes = el('div', 'mc-opt-notes');
    var pending = C.busy && C.where === where ? C.busy : '';
    b.options.forEach(function (o) {
      var one = el('span', 'mc-opt' + (o.off ? ' mc-off' : ''));
      var on = pending ? pending === 'contact:' + o.key + ':' + b.asks[0] : o.chosen;
      var x = btn(o.label, (on ? 'mc-on' : o.key === 'decline' ? 'mc-danger' : '') + (on && pending ? ' mc-pending' : ''), function () {
        if (o.chosen) { return; }
        // The reason as it stands at the press, kept with the declined proposal.
        if (prop && o.key === 'decline') { more = { reason: C.why[where] || '' }; }
        choose(where, 'Saved: ' + o.label + '.', b.asks, 'contact:' + o.key, '', more);
      });
      var more = o.key === 'grant' && cal ? { calendars: cal.ticked() } : undefined;
      if (prop && o.key === 'grant') {
        // Exactly the grant shown above, and the digest of what was shown (CAPABILITIES.md).
        more = { proposal: prop.fields, digest: prop.shown.digest };
        if (prop.busy || (prop.shown.problems || []).length || !prop.shown.digest) {
          x.disabled = true;
          x.title = (prop.shown.problems || [])[0] || 'Wait for the sentence above to be made again.';
        }
      }
      x.id = 'choice-' + o.key + '-' + b.n;
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (o.off || C.busy) { x.disabled = true; }
      if (o.key === 'grant' && cal && !o.chosen && !cal.ticked().length) {
        x.disabled = true;
        x.title = 'Tick at least one calendar above first.';
      }
      one.appendChild(x);
      var i = info('What ' + o.label + ' does', [o.off ? o.why_off : o.said], o.key + '-' + b.n);
      one.appendChild(i.button);
      row.appendChild(one);
      notes.appendChild(i.note);
    });
    s.appendChild(row);
    if (prop && b.options.some(function (o) { return o.key === 'decline'; })) {
      // Why not, kept with the proposal and shown the next time the same is proposed.
      var why = el('input', 'mc-input mc-why-not');
      why.type = 'text';
      why.id = 'declineWhy-' + b.n;
      why.maxLength = 500;
      why.placeholder = 'Why not, if you decline (optional)';
      why.setAttribute('aria-label', 'Why not, if you decline');
      why.value = C.why[where] || '';
      why.addEventListener('input', function () { C.why[where] = why.value; });
      if (C.busy) { why.disabled = true; }
      s.appendChild(why);
    }
    s.appendChild(notes);
    s.appendChild(pressLine(where));
    return s;
  }

  /* ---- a grant Rouh's code proposes (CAPABILITIES.md) ---- */

  /* What this box's grant is now: its fields as the owner narrowed them, and the sentence, digest
     and problems the server made of exactly those fields. Kept while the page is drawn again. */
  function propOf(b) {
    var gr = b.grant;
    var st = C.prop[b.key];
    if (!st || st.digest0 !== gr.digest || st.wording0 !== gr.wording) {
      st = C.prop[b.key] = {
        fields: JSON.parse(JSON.stringify(gr.fields || {})), busy: false, seq: 0,
        digest0: gr.digest, wording0: gr.wording,
        shown: { wording: gr.wording, digest: gr.digest, problems: gr.problems || [] }
      };
    }
    return st;
  }

  /* The fields changed: the server makes the sentence again from them, with its digest, and
     only that digest can be given. */
  var previewTimer = 0;
  function reshow(b) {
    var st = propOf(b);
    st.busy = true;
    var seq = ++st.seq;
    draw();
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(function () {
      post(api(), { do: 'preview', asks: b.asks, proposal: st.fields })
        .then(function (r) { return r.json().catch(function () { return null; }); })
        .then(function (j) {
          if (seq !== st.seq) { return; }
          st.busy = false;
          if (j && j.ok && j.preview) {
            var p = j.preview.proposal || {};
            st.shown = { wording: p.wording || '', digest: p.digest || '', problems: j.preview.problems || [] };
          } else {
            st.shown = { wording: st.shown.wording, digest: '', problems: [(j && j.error) || 'It could not be worded. Try again.'] };
          }
          draw();
        })
        .catch(function () {
          if (seq !== st.seq) { return; }
          st.busy = false;
          st.shown = { wording: st.shown.wording, digest: '', problems: ['The server could not be reached.'] };
          draw();
        });
    }, 250);
  }

  function dayOf(at) {
    var t = new Date(at * 1000);
    return t.getDate() + ' ' + t.toLocaleString('en-GB', { month: 'long' }) + ' ' + t.getFullYear();
  }

  /* Grant, step 1, for a grant Rouh's code proposes: the one sentence that gives it, what it
     lets Rouh do behind the (i), and Narrow it - its tasks or calendars, each limit, and how long
     it lasts - which makes the sentence again. Or, when nothing Rouh has does it, that. */
  function proposalCard(d, b) {
    var gr = b.grant;
    var first = d.first || 'them';
    var where = 'grant-' + b.n;
    var card = el('section', 'mc-box mc-gcard mc-k-' + gr.kind);
    card.id = where;
    card.setAttribute('aria-label', 'Grant');
    if (gr.kind === 'unsupported') {
      var h0 = boxHead(0, gr.canonical ? 'Grant: ' + gr.canonical : 'Grant', false, 'Nothing does it', 'mc-kind-limit');
      card.appendChild(h0);
      card.appendChild(el('p', 'mc-gc-kind', 'Rouh has no way to do this, so nothing can be given for it. See to it ' +
        'yourself, or decline it.'));
      return card;
    }
    var st = propOf(b);
    var head = boxHead(1, 'Grant: ' + gr.canonical, false, gr.lifts ? 'Lifts a hard limit' : 'Proposed', 'mc-kind-new');
    var named = head.querySelector('.mc-box-title');
    named.classList.add('mc-gc-name');
    named.id = 'grantName-' + b.n;
    card.appendChild(head);
    var said = el('p', 'mc-gc-title mc-wording' + (st.busy ? ' mc-dim' : ''), st.shown.wording);
    said.id = 'grantWording-' + b.n;
    var i = info('What this grant lets Rouh do', [].concat(
      (gr.effects || []).map(function (e) { return 'It lets Rouh ' + e + '.'; }),
      [gr.about, gr.lifts ? 'It lifts the hard limit on ' + gr.lifts + ', and only that.' : '',
       'Its contract is ' + gr.capability + ', version ' + gr.version + ': if what it does ever grows, ' +
       'this grant is suspended rather than grown with it.']), 'what-' + b.n);
    var line = el('div', 'mc-row');
    line.appendChild(said);
    line.appendChild(i.button);
    card.appendChild(line);
    card.appendChild(i.note);
    (st.shown.problems || []).forEach(function (t) {
      var pr = el('p', 'mc-gc-kind mc-problem', t);
      pr.id = 'grantProblem-' + b.n;
      card.appendChild(pr);
    });
    if (gr.declined) {
      card.appendChild(el('p', 'mc-alt-said', 'You declined ' + (gr.declined.wording === st.shown.wording ? 'this' : 'one like it') +
        ' on ' + dayOf(gr.declined.at) + (gr.declined.reason ? ': “' + gr.declined.reason + '”' : '') + '.'));
    }
    card.appendChild(narrow(d, b, st, (st.shown.problems || []).length > 0));
    card.appendChild(pressLine(where));
    return card;
  }

  /* Narrow it: what the grant reaches, each limit, and how long it lasts. Closed until pressed,
     open when the grant cannot be given without the owner's own pick. */
  function narrow(d, b, st, open) {
    var gr = b.grant;
    var f = st.fields;
    var fold = el('details', 'mc-fold mc-narrow');
    fold.id = 'narrow-' + b.n;
    if (open) { fold.open = true; }
    fold.appendChild(el('summary', '', 'Narrow it'));
    var body = el('div', 'mc-edit-body');
    var off = !!C.busy;
    if (gr.resource === 'task') {
      body.appendChild(el('span', 'mc-edit-k', 'Tasks'));
      var chips = el('div', 'mc-path');
      (f.scope || []).forEach(function (n) {
        var chip = el('span', 'mc-chip', 'Task ' + n);
        if ((f.scope || []).length > 1) {
          var x = btn('×', 'mc-chip-x', function () {
            f.scope = f.scope.filter(function (m) { return m !== n; });
            reshow(b);
          }, 'Leave task ' + n + ' out');
          x.id = 'scopeOut-' + b.n + '-' + n;
          x.setAttribute('aria-label', 'Leave task ' + n + ' out');
          if (off) { x.disabled = true; }
          chip.appendChild(x);
        }
        chips.appendChild(chip);
      });
      body.appendChild(chips);
    }
    if (gr.resource === 'calendar') {
      body.appendChild(el('span', 'mc-edit-k', 'Calendars'));
      if (!C.cals) {
        loadCalendars();
        body.appendChild(el('p', 'mc-dim', 'Asking Google which calendars Rouh can change…'));
      } else {
        var cals = (C.cals.calendars || []).filter(function (c) { return c.access === 'owner' || c.access === 'writer'; });
        if (!cals.length) { body.appendChild(el('p', 'mc-dim', C.cals.say || 'Rouh cannot change any calendar yet.')); }
        cals.forEach(function (c) {
          var lab = el('label', 'mc-cal');
          var box = el('input');
          box.type = 'checkbox';
          box.id = 'scopeCal-' + b.n + '-' + c.id.replace(/[^\w-]/g, '_');
          box.checked = (f.scope || []).indexOf(c.id) >= 0;
          box.disabled = off;
          box.addEventListener('change', function () {
            var now = (f.scope || []).filter(function (m) { return m !== c.id; });
            if (box.checked) { now.push(c.id); }
            f.scope = now;
            reshow(b);
          });
          lab.appendChild(box);
          var words = el('span', 'mc-cal-words');
          words.appendChild(el('span', '', c.name || c.id));
          if (c.name && c.name !== c.id) { words.appendChild(el('span', 'mc-cal-id', c.id)); }
          lab.appendChild(words);
          body.appendChild(lab);
        });
      }
    }
    (gr.constraints || []).forEach(function (c) {
      var id = 'limit-' + b.n + '-' + c.name;
      if (c.type === 'count') {
        var asked = c.said.replace('{n}', 'how many');
        var lab = el('label', 'mc-edit-k', asked.charAt(0).toUpperCase() + asked.slice(1));
        lab.setAttribute('for', id);
        var n = el('input', 'mc-input mc-num');
        n.type = 'number';
        n.id = id;
        n.min = c.min;
        n.max = c.max;
        n.step = 1;
        n.inputMode = 'numeric';
        n.value = (f.limits || {})[c.name];
        n.disabled = off;
        n.addEventListener('change', function () {
          var v = parseInt(n.value, 10);
          if (isNaN(v)) { return; }
          f.limits[c.name] = v;
          reshow(b);
        });
        body.appendChild(lab);
        body.appendChild(n);
      } else {
        var who = c.said.replace(' {values}', '').replace('{values}', '');
        body.appendChild(el('span', 'mc-edit-k', who.charAt(0).toUpperCase() + who.slice(1)));
        var row = el('div', 'mc-acts');
        (c.values || []).forEach(function (v) {
          var lab2 = el('label', 'mc-cal');
          var box = el('input');
          box.type = 'checkbox';
          box.id = id + '-' + v.key;
          box.checked = ((f.limits || {})[c.name] || []).indexOf(v.key) >= 0;
          box.disabled = off;
          box.addEventListener('change', function () {
            var now = ((f.limits || {})[c.name] || []).filter(function (m) { return m !== v.key; });
            if (box.checked) { now.push(v.key); }
            f.limits[c.name] = now;
            reshow(b);
          });
          lab2.appendChild(box);
          lab2.appendChild(el('span', '', v.said));
          row.appendChild(lab2);
        });
        body.appendChild(row);
      }
    });
    var lid = 'life-' + b.n;
    var llab = el('label', 'mc-edit-k', 'How long');
    llab.setAttribute('for', lid);
    var life = el('select', 'mc-select');
    life.id = lid;
    [['standing', 'Until you take it back'], ['until', 'Until a date'], ['once', 'This once']].forEach(function (o) {
      var opt = el('option', '', o[1]);
      opt.value = o[0];
      if (f.lifetime === o[0]) { opt.selected = true; }
      life.appendChild(opt);
    });
    life.disabled = off;
    life.addEventListener('change', function () {
      f.lifetime = life.value;
      if (f.lifetime === 'until' && !f.until) {
        var t = new Date(Date.now() + 30 * 86400000);
        f.until = t.toISOString().slice(0, 10);
      }
      if (f.lifetime !== 'until') { f.until = ''; }
      reshow(b);
    });
    body.appendChild(llab);
    body.appendChild(life);
    if (f.lifetime === 'until') {
      var day = el('input', 'mc-input mc-day');
      day.type = 'date';
      day.id = 'until-' + b.n;
      day.value = f.until || '';
      day.setAttribute('aria-label', 'The last day it lasts');
      day.disabled = off;
      day.addEventListener('change', function () { f.until = day.value; reshow(b); });
      body.appendChild(day);
    }
    fold.appendChild(body);
    return fold;
  }

  /* The calendars Rouh can change, asked of Google once for the page
     (GET /api/settings/google/calendars), the same list as on a contact's page in Trusted
     contacts. Read-only ones are not offered: the grant is for changing a calendar. */
  function loadCalendars() {
    if (C.calsAsked) { return; }
    C.calsAsked = true;
    fetch('/api/settings/google/calendars', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          C.cals = r.ok ? j : { say: (j && j.error) || 'Google did not list the calendars.' };
        });
      })
      .catch(function () { C.cals = { say: 'The calendars could not be read. Try again in a moment.' }; })
      .then(function () { if (!typing()) { draw(); } });
  }

  /* Which calendars the contact gets with Give permanently, one box each: what they hold
     now when the grant is theirs already, else none. Once given, a tick changes it at once;
     the last one cannot be unticked here, as Give permanently is not taken back here. */
  function calendarPick(d, b, where, given) {
    var first = d.first || 'them';
    var part = el('div', 'mc-cals');
    part.id = 'calendars-' + b.n;
    part.setAttribute('role', 'group');
    part.setAttribute('aria-label', 'Which calendars ' + first + ' gets');
    part.appendChild(el('span', 'mc-choice-head', 'Which calendars ' + first + ' gets'));
    var key = where;
    if (!C.cals) {
      loadCalendars();
      part.appendChild(el('p', 'mc-dim', 'Asking Google which calendars Rouh can change…'));
      return { part: part, ticked: function () { return C.calPick[key] || []; } };
    }
    var cals = (C.cals.calendars || []).filter(function (c) { return c.access === 'owner' || c.access === 'writer'; });
    if (!(key in C.calPick)) {
      var now = b.grant.calendars_held ? b.grant.calendars_now : [];
      C.calPick[key] = now === null ? cals.map(function (c) { return c.id; }) : (now || []).slice();
    }
    var pick = C.calPick[key];
    if (!cals.length) {
      part.appendChild(el('p', 'mc-dim', C.cals.say || (C.cals.connected === false
        ? 'Google is not connected, so there are no calendars to pick yet.'
        : 'Rouh cannot change any calendar through ' + (C.cals.account || 'its Google account') + ' yet.')));
    }
    cals.forEach(function (c) {
      var label = el('label', 'mc-cal');
      var box = el('input');
      box.type = 'checkbox';
      box.value = c.id;
      box.checked = pick.indexOf(c.id) >= 0;
      box.disabled = !!C.busy || (given && box.checked && pick.length === 1);
      box.addEventListener('change', function () {
        var at = pick.indexOf(c.id);
        if (box.checked && at < 0) { pick.push(c.id); }
        if (!box.checked && at >= 0) { pick.splice(at, 1); }
        if (given) {
          var n = pick.length;
          choose(where, 'Saved: ' + first + ' gets ' + n + ' calendar' + (n === 1 ? '' : 's') + '.',
                 b.asks, 'contact:grant', '', { calendars: pick.slice() });
          return;
        }
        draw();
      });
      label.appendChild(box);
      var words = el('span', 'mc-cal-words');
      var name = el('span', '', c.name || c.id);
      if (c.theirs) { name.appendChild(el('span', 'mc-cal-whose', 'Yours')); }
      else if (c.primary) { name.appendChild(el('span', 'mc-cal-whose', 'This account\'s own')); }
      words.appendChild(name);
      if (c.name && c.name !== c.id) { words.appendChild(el('span', 'mc-cal-id', c.id)); }
      label.appendChild(words);
      part.appendChild(label);
    });
    return { part: part, ticked: function () { return pick.slice(); } };
  }

  /* One decision: the asks that need the same grant, then Grant and Contact. */
  function decision(d, b, its, tests) {
    var li = el('li', 'mc-item mc-dec');
    li.id = 'box-' + b.n;
    li.setAttribute('data-status', 'waiting_for_owner');
    var asks = el('div', 'mc-dec-asks');
    its.forEach(function (it) { asks.appendChild(askRow(it, tests && tests[it.id])); });
    li.appendChild(asks);
    li.appendChild(grantCard(d, b));
    if (b.grant.kind !== 'once') { li.appendChild(contract(d, b)); }
    return li;
  }

  function group(d, g, drawn) {
    var s = el('section', 'mc-group');
    s.id = 'group-' + g.key;
    s.setAttribute('aria-labelledby', 'groupHead-' + g.key);
    var h = el('h5', 'mc-gh');
    h.id = 'groupHead-' + g.key;
    h.appendChild(el('span', '', g.name));
    h.appendChild(el('span', 'mc-n', String(g.items.length)));
    var i = info('How ' + g.name.charAt(0).toLowerCase() + g.name.slice(1) + ' works', guideFor(d, g));
    h.appendChild(i.button);
    s.appendChild(h);
    s.appendChild(i.note);
    var tests = C.tests[g.key];
    var list = el('ol', 'mc-items');
    var all = [];
    (d.groups || []).forEach(function (x) { all = all.concat(x.items); });
    g.items.forEach(function (it) {
      var b = it.box && d.boxes && d.boxes[it.box];
      // A permission they hold already is never asked for: no box and no buttons for it
      // (Petar, 16 October 2026, MAIL.md D29). The server sends none; this keeps it so.
      if (b && b.grant.kind === 'task' && b.grant.level === 'edit') { b = null; }
      if (!b) { list.appendChild(item(it, tests && tests[it.id])); return; }
      if (drawn[b.key]) { return; }
      drawn[b.key] = true;
      list.appendChild(decision(d, b, all.filter(function (x) { return x.box === b.key; }), tests));
    });
    s.appendChild(list);

    var foot = el('div', 'mc-foot');
    var t = btn(C.busy === 'test:' + g.key ? 'Testing…' : 'Test', '', function () {
      press('test:' + g.key, { do: 'test', group: g.key });
    });
    t.id = 'test-' + g.key;
    var r = btn(C.busy === 'redo' ? 'Starting…' : 'Redo', 'mc-primary', function () {
      press('redo', { do: 'redo', attempt: d.redo.attempt });
    });
    r.id = 'redo-' + g.key;
    if (!d.redo.open) {
      r.disabled = true;
      r.title = d.redo.why_not || '';
    }
    if (C.busy) { t.disabled = true; r.disabled = true; }
    foot.appendChild(t);
    foot.appendChild(r);
    if (tests) {
      var ids = g.items.map(function (x) { return x.id; }).filter(function (x) { return tests[x]; });
      var goes = ids.filter(function (x) { return tests[x].goes; }).length;
      foot.appendChild(el('span', 'mc-foot-said', goes + ' of ' + ids.length + ' would go. Nothing was sent or done.'));
    } else if (!d.redo.open && d.redo.why_not) {
      foot.appendChild(el('span', 'mc-foot-said', d.redo.why_not));
    }
    s.appendChild(foot);
    return s;
  }

  function draw() {
    var body = C.body;
    if (!body) { return; }
    var page = el('div', 'mc-page');
    if (!C.data) {
      page.appendChild(el('p', C.error ? 'mc-error' : 'mc-said', C.error || 'Reading what they asked…'));
      body.replaceChildren(page);
      return;
    }
    var d = C.data;
    if (d.answered_elsewhere) {
      page.appendChild(el('p', 'mc-note', 'You answered this on the Decisions page; it goes in a few seconds, and this shows it then.'));
    }
    var top = C.where ? '' : C.said;
    var said = el('p', 'mc-status' + (C.bad ? ' mc-bad' : ''), top || C.error);
    said.id = 'mcSaid';
    said.setAttribute('role', 'status');
    said.setAttribute('aria-live', 'polite');
    said.hidden = !(top || C.error);
    page.appendChild(said);
    var drawn = {};
    d.groups.forEach(function (g) { page.appendChild(group(d, g, drawn)); });
    // With no asks there is nothing here to say: the line under the page's heading says why.
    body.hidden = !d.groups.length && !d.answered_elsewhere && !(top || C.error);
    // Drawn again in place: what was unfolded stays unfolded, an (i) opened stays open, and
    // the press keeps its focus.
    body.querySelectorAll('details[open][id]').forEach(function (was) {
      var now = page.querySelector('#' + CSS.escape(was.id));
      if (now) { now.open = true; }
    });
    body.querySelectorAll('.mc-i[id][aria-expanded="true"]').forEach(function (was) {
      var now = page.querySelector('#' + CSS.escape(was.id));
      var note = now && page.querySelector('#' + CSS.escape(now.getAttribute('aria-controls')));
      if (note) { note.hidden = false; now.setAttribute('aria-expanded', 'true'); }
    });
    var focus = document.activeElement && document.activeElement.id;
    body.replaceChildren(page);
    if (focus && $(focus) && body.contains($(focus))) { $(focus).focus({ preventScroll: true }); }
  }

  /* ---- starting, on the case's page ---- */

  var box = $('caseAsks');
  if (box && box.getAttribute('data-key')) {
    C.body = box;
    C.key = box.getAttribute('data-key');
    draw();
    load();
    watch();
  }
}());
