// A live shared space (task 189, Rouh Link): a task page two people and their Rouhs work on at
// once. The page only ever asks its own Rouh (/api/link/spaces/<id>...), with a long poll that
// returns the moment anything changes; its own Rouh holds the room or follows it.
//
// What is drawn: who is here (people round, Rouhs square), the live line, each Rouh's marker on
// its part, the steps, the notes (live text), the meeting proposal, the person's own Rouh (ask,
// intent with Stop, its live steps, Skip to the end), the people and Rouhs here (Undo its edits),
// comments in place, history (Bring back this version), invite, and the log.
(function () {
  'use strict';

  var SID = (document.body.getAttribute('data-space') || '').trim();
  var API = window.LINK_API || {
    get: function (path) { return fetch(path, { credentials: 'same-origin' }).then(answer); },
    post: function (path, body) {
      return fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) }).then(answer);
    }
  };
  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok) { var e = new Error(j.error || ('The Rouh answered ' + r.status)); e.status = r.status; throw e; }
      return j;
    });
  }
  var base = '/api/link/spaces/' + encodeURIComponent(SID);

  var S = null;              // the last state from this Rouh
  var version = -1;
  var myPart = '';
  var following = '';
  var historyOpen = false;
  var notesBusy = false;     // the person is typing: incoming notes wait until their change is in
  var notesTimer = null;
  var colours = {};          // actor label -> colour slot
  var seenItems = {};
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k != null) e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k); });
    return e;
  }
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); return node; }
  function uid() { return Math.random().toString(36).slice(2, 12) + Date.now().toString(36).slice(-6); }
  function labelOf(actor) { return String(actor || '').split(':').slice(1).join(':'); }
  function isRouh(actor) { return String(actor || '').indexOf('rouh:') === 0; }
  function slot(label) {
    if (!S) return 4;
    if (label === S.me.label) return 0;
    if (colours[label] == null) {
      var n = Object.keys(colours).length + 1;
      colours[label] = Math.min(n, 4);
    }
    return colours[label];
  }
  function memberName(label) {
    var m = (S.space.members || []).filter(function (x) { return x.label === label; })[0];
    return m && m.name ? m.name : label;
  }
  function actorWords(actor) {
    var label = labelOf(actor);
    if (S && label === S.me.label) return isRouh(actor) ? 'Your Rouh' : 'You';
    var short = memberName(label).split(' ·')[0];
    return isRouh(actor) ? short + "'s Rouh" : short + "'s person";
  }
  function initials(actor) {
    var n = memberName(labelOf(actor)).replace(/·.*/, '').trim().split(/\s+/);
    return ((n[0] || '?')[0] + ((n[1] || '')[0] || '')).toUpperCase();
  }
  function tag(actor) {
    return el('span', { class: 'tag c-' + slot(labelOf(actor)) + (isRouh(actor) ? ' rouh' : '') },
      [el('span', { class: 'glyph', 'aria-hidden': 'true' }), actorWords(actor)]);
  }
  function toast(words, undo) {
    var t = $('toast');
    clear(t).appendChild(el('span', { text: words }));
    if (undo) t.appendChild(el('button', { class: 'quiet', text: 'Undo', onclick: function () { t.hidden = true; undo(); } }));
    t.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { t.hidden = true; }, 6000);
  }
  function fail(e) { toast(e && e.message ? e.message : 'That did not work.'); }

  // --- talking to this Rouh -----------------------------------------------------------------------

  function op(kind, fields) {
    var o = { id: uid(), kind: kind, actor: S.me.person, at: Date.now() / 1000 };
    Object.keys(fields || {}).forEach(function (k) { o[k] = fields[k]; });
    return o;
  }
  function send(ops) {
    return API.post(base + '/ops', { ops: ops }).then(function (got) {
      (got.refused || []).forEach(function (r) { toast(r.why); });
      return got;
    }).catch(fail);
  }
  function act(what, more) {
    var body = { act: what };
    Object.keys(more || {}).forEach(function (k) { body[k] = more[k]; });
    return API.post(base + '/act', body);
  }

  function poll() {
    var q = '?since=' + version + '&wait=20&part=' + encodeURIComponent(myPart) + '&follow=' + encodeURIComponent(following);
    API.get(base + q).then(function (st) {
      S = st; version = st.version; draw();
      setTimeout(poll, 30);
    }).catch(function (e) {
      if (e && e.status === 404) { showGone(); return; }
      $('liveLine').textContent = 'Lost touch with your Rouh; trying again.';
      setTimeout(poll, 3000);
    });
  }
  function nudge() {   // presence moved: tell at once, without waiting for the long poll
    API.get(base + '?since=' + 1e9 + '&wait=0&part=' + encodeURIComponent(myPart) + '&follow=' + encodeURIComponent(following))
      .catch(function () {});
  }

  // --- drawing ------------------------------------------------------------------------------------

  function presenceByActor() {
    var by = {};
    (S.presence || []).forEach(function (p) { by[p.actor] = p; });
    return by;
  }

  // Who is here now: the people and Rouhs with a fresh presence, and this Rouh always (it is here
  // whenever its person is). The avatars and the sentence both count this one list.
  function hereNow() {
    var by = presenceByActor();
    var out = [];
    (S.space.members || []).forEach(function (m) {
      if (m.state && m.state !== 'joined') return;
      ['person:' + m.label, 'rouh:' + m.label].forEach(function (a) {
        if (by[a] || (isRouh(a) && labelOf(a) === S.me.label)) out.push(a);
      });
    });
    return out;
  }

  function drawWho() {
    var box = clear($('who'));
    var by = presenceByActor();
    hereNow().forEach(function (a) {
      var here = by[a];
      var label = labelOf(a);
      var b = el('button', {
        class: 'av c-' + slot(label) + (isRouh(a) ? ' rouh' : '') + (here && here.busy ? ' busy' : ''),
        'aria-label': (following === a ? 'Stop following ' : 'Follow ') + actorWords(a) + (here && here.doing ? ': ' + here.doing : ''),
        title: actorWords(a) + (here && here.doing ? ': ' + here.doing : ''),
        'aria-pressed': following === a ? 'true' : 'false',
        text: initials(a),
        onclick: function () { following = following === a ? '' : a; nudge(); draw(); }
      });
      box.appendChild(b);
    });
  }

  function liveLine() {
    var by = presenceByActor();
    var people = 0, rouhs = 0, working = [];
    hereNow().forEach(function (a) {
      if (isRouh(a)) { rouhs++; if (by[a] && by[a].busy) working.push(a); } else people++;
    });
    if (S.space.state === 'ended') return 'This space has ended. You can still read it.';
    if (!S.space.joined) return memberName(S.space.holder).split(' ·')[0] + ' asks you into this space.';
    var line = 'Live: ' + people + (people === 1 ? ' person' : ' people') + ' and ' + rouhs + (rouhs === 1 ? ' Rouh' : ' Rouhs') + ' here.';
    working.forEach(function (a) {
      var p = by[a];
      line += ' ' + actorWords(a) + ' is ' + (p.doing ? p.doing.charAt(0).toLowerCase() + p.doing.slice(1) : 'working') + (p.part ? ' (' + partName(p.part) + ')' : '') + '.';
    });
    return line;
  }

  function partName(part) {
    var bits = String(part).split(':');
    var names = S.space.names || {};
    if (bits[0] === 'item') {
      var it = findItem(bits[1]);
      return it ? '“' + String(it.fields.text || '').slice(0, 40) + '”' : 'a step';
    }
    return names[bits[1]] || bits[1] || part;
  }
  function findItem(id) {
    var lists = S.doc.lists || {};
    var found = null;
    Object.keys(lists).forEach(function (k) { lists[k].forEach(function (it) { if (it.id === id) found = it; }); });
    return found;
  }

  function marksFor(part, extra) {
    var by = presenceByActor();
    var out = el('span', { class: 'marks' });
    var any = '';
    Object.keys(by).forEach(function (a) {
      var p = by[a];
      if (!p.part) return;
      if (p.part === part || (extra && extra.indexOf(p.part) >= 0)) {
        if (labelOf(a) === S.me.label && !isRouh(a)) return;
        out.appendChild(tag(a));
        any = any || 'var(--' + ['accent', 'partner', 'third', 'fourth', 'dim'][slot(labelOf(a))] + ')';
      }
    });
    return { node: out, colour: any };
  }

  function commentsFor(part) {
    var wrap = el('div', { class: 'stack', style: 'gap:4px' });
    (S.doc.comments || []).filter(function (c) { return c.part === part && !c.resolved; }).forEach(function (c) {
      wrap.appendChild(el('div', { class: 'comment' }, [
        el('span', { class: 'by', text: actorWords(c.by) + ':' }), el('span', { text: c.text }), ' ',
        el('button', { class: 'quiet small', text: 'Resolve', onclick: function () { send([op('resolve', { cid: c.id })]); } })
      ]));
    });
    return wrap;
  }

  function commentForm(part, holder) {
    var ta = el('textarea', { rows: '2', 'aria-label': 'Your comment' });
    var f = el('form', { class: 'say-form', onsubmit: function (ev) {
      ev.preventDefault();
      var t = ta.value.trim(); if (!t) return;
      send([op('comment', { cid: uid(), part: part, text: t })]).then(function () { f.remove(); });
    } }, [ta, el('div', { class: 'row' }, [
      el('button', { class: 'primary', type: 'submit', text: 'Post comment' }),
      el('button', { class: 'quiet', type: 'button', text: 'Cancel', onclick: function () { f.remove(); } })])]);
    holder.appendChild(f);
    ta.focus();
  }

  function claimOf(part) { return (S.doc.claims || {})[part]; }

  function drawSteps() {
    var listName = (S.space.lists || [])[0];
    var box = $('steps');
    $('stepsTitle').textContent = (S.space.names || {})[listName] || 'Steps';
    if (!listName) { $('stepsBox').hidden = true; return; }
    $('stepsBox').hidden = false;
    var items = (S.doc.lists || {})[listName] || [];
    var focusId = document.activeElement && document.activeElement.getAttribute('data-item');
    var listMarks = marksFor('list:' + listName);
    clear($('stepsMarks')).appendChild(listMarks.node);
    var ul = clear(box);
    if (!items.length) ul.appendChild(el('li', { class: 'dim small', text: 'No steps yet. Add one, or ask your Rouh to.' }));
    items.forEach(function (it) {
      var part = 'item:' + it.id;
      var marks = marksFor(part);
      var claim = claimOf(part) || claimOf('list:' + listName);
      var text = el('textarea', { rows: '1', class: 'text', 'data-item': it.id,
        'aria-label': 'Step', disabled: !canEdit() || (claim && isRouh(claim.by) && labelOf(claim.by) !== S.me.label && false),
        onfocus: function () { myPart = part; nudge(); },
        onkeydown: function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); text.blur(); } },
        oninput: function () { fit(text); },
        onchange: function () { send([op('set', { path: ['lists', listName, it.id, 'text'], v: text.value.replace(/\n/g, ' ').slice(0, 300) })]); } });
      text.value = String(it.fields.text || '');
      var li = el('li', { class: 'step part' + (it.fields.done ? ' done' : '') + (marks.colour ? ' marked' : '') + (seenItems[it.id] ? '' : ' new'),
        style: marks.colour ? '--mc:' + marks.colour : (isRouh(it.by) ? '--mc:var(--' + ['accent', 'partner', 'third', 'fourth', 'dim'][slot(labelOf(it.by))] + ')' : ''),
        'data-part': part }, [
        el('input', { type: 'checkbox', checked: !!it.fields.done, 'aria-label': 'Done', disabled: !canEdit(),
          onchange: function (ev) { send([op('set', { path: ['lists', listName, it.id, 'done'], v: ev.target.checked })]); } }),
        text,
        el('span', { class: 'tools' }, [
          claim ? null : el('button', { class: 'quiet', text: 'Claim', title: 'Take this step: only you change it until you let it go', disabled: !canEdit(),
            onclick: function () { send([op('claim', { part: part })]); } }),
          claim ? el('button', { class: 'quiet', text: labelOf(claim.by) === S.me.label && !isRouh(claim.by) ? 'Let go' : 'Take back', disabled: !canEdit(),
            onclick: function () { send([op('release', { part: claim.part || part })]); } }) : null,
          el('button', { class: 'quiet', text: 'Comment', onclick: function () { commentForm(part, under); } }),
          el('button', { class: 'quiet subtle', 'aria-label': 'Remove step', text: 'Remove', disabled: !canEdit(),
            onclick: function () { send([op('remove', { list: listName, item: it.id })]); } })
        ])
      ]);
      seenItems[it.id] = true;
      requestAnimationFrame(function () { fit(text); });
      var under = el('div', { class: 'under' }, [
        marks.node.childNodes.length ? marks.node : null,
        claim ? el('span', { class: 'claimed dim' }, ['Claimed by ', tag(claim.by)]) : null,
        isRouh(it.by) && labelOf(it.by) !== S.me.label ? el('span', { class: 'byline', text: 'Added by ' + actorWords(it.by) }) : null,
        commentsFor(part)
      ]);
      li.appendChild(under);
      ul.appendChild(li);
    });
    if (focusId) { var again = box.querySelector('[data-item="' + focusId + '"]'); if (again) again.focus(); }
  }

  // A step's text grows to show all of it, where the browser cannot size the box by itself.
  function fit(t) { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }

  function addStep(ev) {
    ev.preventDefault();
    var listName = (S.space.lists || [])[0];
    var input = $('newStep');
    var t = input.value.trim(); if (!t) return;
    var items = (S.doc.lists || {})[listName] || [];
    var pos = items.length ? items[items.length - 1].pos + 1 : 1;
    input.value = '';
    send([op('add', { list: listName, item: uid().slice(0, 12), pos: pos, fields: { text: t.slice(0, 300), done: false } })]);
  }

  function drawNotes() {
    var name = (S.space.texts || [])[0];
    if (!name) { $('notesBox').hidden = true; return; }
    $('notesBox').hidden = false;
    $('notesTitle').textContent = (S.space.names || {})[name] || 'Notes';
    var t = (S.doc.texts || {})[name] || { text: '', ids: [], by: [], top: 0 };
    var ta = $('notes');
    ta.disabled = !canEdit();
    var part = 'text:' + name;
    var marks = marksFor(part);
    clear($('notesMarks')).appendChild(marks.node);
    $('notesPart').classList.toggle('marked', !!marks.colour);
    if (marks.colour) $('notesPart').style.setProperty('--mc', marks.colour);
    var writers = {};
    (t.by || []).forEach(function (r) { writers[r[2]] = (writers[r[2]] || 0) + r[1]; });
    var bl = clear($('notesBy'));
    Object.keys(writers).forEach(function (a) { bl.appendChild(tag(a)); });
    clear($('notesComments')).appendChild(commentsFor(part));
    if (notesBusy) return;
    if (ta.value !== t.text) {
      var focused = document.activeElement === ta;
      var at = ta.selectionStart, idAt = focused && at > 0 ? (ta._ids || [])[at - 1] : null;
      ta.value = t.text;
      if (focused) {
        var i = idAt ? t.ids.indexOf(idAt) + 1 : 0;
        if (i < 0) i = Math.min(at, t.text.length);
        ta.setSelectionRange(i, i);
      }
    }
    ta._ids = t.ids.slice();
    ta._text = t.text;
    ta._top = t.top;
  }

  function notesTyped() {
    notesBusy = true;
    clearTimeout(notesTimer);
    notesTimer = setTimeout(sendNotes, 260);
  }
  function sendNotes() {
    var ta = $('notes');
    var name = (S.space.texts || [])[0];
    var old = ta._text || '', ids = ta._ids || [], now = ta.value;
    var a = 0; while (a < old.length && a < now.length && old[a] === now[a]) a++;
    var b = 0; while (b < old.length - a && b < now.length - a && old[old.length - 1 - b] === now[now.length - 1 - b]) b++;
    var gone = ids.slice(a, old.length - b);
    var added = now.slice(a, now.length - b);
    var after = a > 0 ? ids[a - 1] : '';
    var ops = [];
    if (gone.length) ops.push(op('del', { t: name, ids: gone }));
    if (added) {
      var n = (ta._top || 0) + 1;
      ops.push(op('ins', { t: name, after: after, id0: n + '~' + S.me.person, text: added }));
      ta._top = n + added.length;
    }
    if (!ops.length) { notesBusy = false; return; }
    var sent = now;
    send(ops).then(function () {
      return API.get(base + '?since=-1&wait=0&part=' + encodeURIComponent(myPart));
    }).then(function (st) {
      if (!st) { notesBusy = false; return; }
      S = st; version = Math.max(version, st.version);
      var t = (st.doc.texts || {})[name] || { text: '', ids: [], top: 0 };
      if (ta.value !== sent) {
        // More was typed while this went: diff the rest against what the room has now.
        ta._text = t.text; ta._ids = t.ids.slice(); ta._top = t.top;
        sendNotes();
        return;
      }
      notesBusy = false;
      draw();
    }).catch(function () { notesBusy = false; });
  }

  function drawMeeting() {
    var box = clear($('meeting'));
    var props = (S.doc.proposals || []).filter(function (p) { return p.kind === 'meeting'; });
    var open = props.filter(function (p) { return p.state === 'open'; });
    $('findTime').hidden = !!open.length || !S.space.joined || S.space.state !== 'live';
    var lastSeq = props.length ? props[props.length - 1].seq : -1;
    var none = (S.doc.activity || []).filter(function (a) { return /^No time when everyone is free/.test(a.words) && a.seq > lastSeq; }).pop();
    if (none) {
      box.appendChild(el('p', { class: 'state-mark warn' }, [svgClock(), 'No time when you are all free in the next 7 days, in working hours. Try a shorter meeting.']));
      return;
    }
    if (!props.length) {
      box.appendChild(el('p', { class: 'dim small', text: 'Only free and busy times cross between the Rouhs: never what a meeting is, where, or with whom.' }));
      return;
    }
    var p = props[props.length - 1];
    var mine = (p.yes || {})[S.me.label];
    var needed = p.needed || [];
    var said = needed.filter(function (l) { return (p.yes || {})[l]; }).length;
    var head = el('div', { class: 'row' }, [el('h3', { class: 'grow', text: p.title })]);
    if (p.state === 'agreed' || p.state === 'booked') {
      head.appendChild(el('span', { class: 'state-mark good' }, [svgCheck(), 'Agreed']));
    } else {
      head.appendChild(el('span', { class: 'state-mark warn' }, [svgClock(), said + ' of ' + needed.length + ' said yes']));
    }
    box.appendChild(head);
    if (p.state === 'open') box.appendChild(el('p', { class: 'small dim', text: 'Each person says yes on their own screen. When all say yes to the same time, each Rouh puts it in its own person’s calendar.' }));
    (p.options || []).forEach(function (o) {
      var yeses = el('span', { class: 'yeses' });
      needed.forEach(function (l) {
        var y = (p.yes || {})[l];
        if (y && y.option === o.id) yeses.appendChild(tag('person:' + l));
      });
      var chosen = p.chosen === o.id;
      box.appendChild(el('div', { class: 'option' + (chosen ? ' chosen' : '') }, [
        el('div', {}, [el('div', { text: o.label }), yeses]),
        p.state === 'open' && needed.indexOf(S.me.label) >= 0 ?
          el('button', { class: mine && mine.option === o.id ? 'quiet' : '', text: mine && mine.option === o.id ? 'Your yes' : 'Yes, this time',
            'aria-pressed': mine && mine.option === o.id ? 'true' : 'false',
            onclick: function () { send([op('yes', { pid: p.id, option: o.id })]); } }) :
          (chosen ? el('span', { class: 'state-mark good' }, [svgCheck(), 'This one']) : el('span'))
      ]));
    });
    if (p.state === 'agreed') {
      var booked = (S.doc.activity || []).filter(function (a) { return /^(Put it in|Agreed;)/.test(a.words); });
      booked.forEach(function (a) { box.appendChild(el('p', { class: 'small' }, [tag(a.by), ' ', a.words])); });
    }
  }
  function svg(path) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '2.4'); s.setAttribute('stroke-linecap', 'round');
    var p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', path); s.appendChild(p);
    return s;
  }
  function svgCheck() { return svg('M4 12.5l5 5L20 6.5'); }
  function svgClock() { return svg('M12 6v6l4 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z'); }

  function drawIntent() {
    var shown = (S.doc.intents || []).filter(function (i) { return i.state === 'shown'; });
    var box = clear($('intent'));
    box.hidden = !shown.length;
    shown.forEach(function (i) {
      var started = (S.doc.activity || []).some(function (a) { return a.by === i.by && a.seq > i.seq; });
      box.appendChild(el('div', { class: 'banner', role: 'status' }, [
        tag(i.by), el('p', { text: (started ? 'is working on: ' : 'is about to: ') + i.words }),
        el('button', { text: 'Skip to the end', onclick: function () { skipFor(i.by); } }),
        el('button', { class: 'stop', text: 'Stop', onclick: function () {
          send([op('intent.end', { iid: i.id, state: 'stopped' })]);
          if (labelOf(i.by) === S.me.label) act('stop');
        } })
      ]));
    });
  }

  function drawMyRouh() {
    var pace = S.pacing || {};
    $('rouhBusy').hidden = !pace.busy;
    $('rouhAsk').hidden = !!pace.busy || !canEdit();
    if (pace.busy) $('rouhProgress').textContent = 'Working: ' + pace.done + ' of ' + pace.total + ' steps' + (pace.skipping ? ', skipping to the end' : '') + '.';
    var feed = clear($('feed'));
    var acts = (S.doc.activity || []).slice(-12).reverse();
    if (!acts.length) feed.appendChild(el('li', { class: 'dim' }, [el('span', { text: '' }), el('span', { text: 'What the Rouhs do here shows up here, step by step.' })]));
    var shown = {};
    acts.forEach(function (a) {
      var older = shown[a.by];
      shown[a.by] = true;
      feed.appendChild(el('li', { class: older ? 'older' : '' }, [older ? null : tag(a.by), el('span', { text: (a.of ? a.step + ' of ' + a.of + ': ' : '') + a.words })]));
    });
  }

  function canEdit() { return S && S.space.joined && S.space.state === 'live' && ['owner', 'editor'].indexOf(S.me.role) >= 0; }

  function drawMembers() {
    var box = clear($('members'));
    var runs = S.doc.runs || {};
    (S.space.members || []).forEach(function (m) {
      if (m.state && ['joined', 'invited'].indexOf(m.state) < 0) return;
      ['person:', 'rouh:'].forEach(function (k) {
        var a = k + m.label;
        var edits = editsBy(a);
        box.appendChild(el('div', { class: 'member' }, [
          el('span', { class: 'av c-' + slot(m.label) + (k === 'rouh:' ? ' rouh' : ''), 'aria-hidden': 'true', text: initials(a) }),
          el('div', {}, [el('div', { text: actorWords(a) }), el('div', { class: 'role', text: (k === 'rouh:' ? 'Rouh, ' : '') + (m.role || '') + (m.state === 'invited' ? ', asked in' : '') })]),
          k === 'rouh:' && edits ? el('button', { class: 'quiet', text: 'Undo its edits', title: 'Takes out this Rouh’s edits; the people’s stay',
            onclick: function () {
              send([op('undo', { target: a, from: 0 })]).then(function () { toast('Took out ' + actorWords(a) + '’s edits. The people’s stay.'); });
            } }) : el('span')
        ]));
      });
    });
    var inv = $('inviteBox');
    inv.hidden = !S.space.mine || S.space.state !== 'live';
  }
  function editsBy(actor) {
    var n = 0;
    var d = S.doc;
    Object.keys(d.field_by || {}).forEach(function (k) { if (d.field_by[k] === actor) n++; });
    Object.keys(d.lists || {}).forEach(function (k) { d.lists[k].forEach(function (it) { if (it.by === actor) n++; }); });
    Object.keys(d.texts || {}).forEach(function (k) { (d.texts[k].by || []).forEach(function (r) { if (r[2] === actor) n += 1; }); });
    return n;
  }

  function drawBanners() {
    var b = clear($('state'));
    if (!S.space.joined) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: memberName(S.space.holder) + ' asks you into “' + (S.doc.fields.title || 'this space') + '”. Join to see it live and work in it.' }),
        el('button', { class: 'primary', text: 'Join', onclick: function () { act('join').then(function () { toast('Joined.'); }).catch(fail); } })]));
    } else if (S.holder_off) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'The Rouh holding this space is off. Your changes show here and wait' + (S.pending ? ' (' + S.pending + ' waiting)' : '') + '; they go when it is back.' })]));
    } else if (S.space.state === 'ended') {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'This space has ended. What is here stays to read.' })]));
    }
    if (following) {
      var p = presenceByActor()[following];
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'Following ' + actorWords(following) + (p && p.part ? ', on ' + partName(p.part) : '') + '.' }),
        el('button', { text: 'Stop following', onclick: function () { following = ''; nudge(); draw(); } })]));
      if (p && p.part) {
        var target = document.querySelector('[data-part="' + p.part + '"]') || (p.part.indexOf('text:') === 0 ? $('notesPart') : null);
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  }

  // Skip to the end for any Rouh at work: this one's own run directly, another's by asking it
  // in the room (a "pace" change only a person may make; its pacer sends the rest at once).
  function skipFor(actor) {
    if (labelOf(actor) === S.me.label) { act('skip').catch(fail); return; }
    send([op('pace', { target: actor, how: 'skip' })]).then(function () { toast('Asked ' + actorWords(actor) + ' to skip to the end.'); });
  }

  function drawAtWork() {
    var by = presenceByActor();
    var others = hereNow().filter(function (a) { return isRouh(a) && labelOf(a) !== S.me.label && by[a] && by[a].busy; });
    var box = $('atWork');
    box.hidden = !others.length;
    clear(box);
    if (others.length) {
      box.appendChild(el('span', { text: others.map(actorWords).join(', ') + (others.length === 1 ? ' is' : ' are') + ' at work' }));
      box.appendChild(el('button', { class: 'quiet', text: 'Skip to the end', onclick: function () { others.forEach(skipFor); } }));
    }
  }

  function draw() {
    if (!S) return;
    drawAtWork();
    document.title = (S.doc.fields.title || 'Live space') + ' · live';
    $('title').textContent = S.doc.fields.title || 'A live space';
    $('kind').textContent = S.space.kind_word + (S.space.mine ? ', held by your Rouh' : ', held by ' + memberName(S.space.holder) + '’s Rouh');
    $('liveLine').textContent = liveLine();
    drawWho();
    drawBanners();
    drawIntent();
    drawSteps();
    drawNotes();
    drawMeeting();
    drawMyRouh();
    drawMembers();
    if (historyOpen) $('histRange').max = String(S.seq);
    $('work').hidden = !S.space.joined;
  }

  function showGone() {
    clear($('main')).appendChild(el('div', { class: 'empty' }, [el('h2', { text: 'This space is not here' }),
      el('p', { text: 'It may have ended, or you were never asked into it.' }), el('a', { href: '/link', text: 'Back to Connections' })]));
  }

  // --- the side controls ------------------------------------------------------------------------------

  function wire() {
    $('addStep').addEventListener('submit', addStep);
    $('notes').addEventListener('input', notesTyped);
    $('notes').addEventListener('focus', function () { myPart = 'text:' + (S.space.texts || [])[0]; nudge(); });
    $('notesComment').addEventListener('click', function () { commentForm('text:' + (S.space.texts || [])[0], $('notesComments')); });
    $('rouhAsk').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var w = $('rouhWords').value.trim(); if (!w) return;
      $('rouhGo').disabled = true;
      act('rouh', { words: w }).then(function () { $('rouhWords').value = ''; toast('Your Rouh is on it.'); })
        .catch(fail).then(function () { $('rouhGo').disabled = false; });
    });
    $('skip').addEventListener('click', function () { act('skip').catch(fail); });
    $('stopRouh').addEventListener('click', function () { act('stop').catch(fail); });
    $('findTime').addEventListener('click', function () {
      $('findTime').disabled = true;
      act('meeting', { minutes: +$('minutes').value, days: 7 }).then(function (got) {
        if (got && got.waiting && got.waiting.length) toast('Waiting for the other Rouh, which is off; the times come when it is back.');
      }).catch(fail).then(function () { $('findTime').disabled = false; });
    });
    $('histToggle').addEventListener('click', function () {
      historyOpen = !historyOpen;
      $('hist').hidden = !historyOpen;
      $('histToggle').setAttribute('aria-expanded', historyOpen ? 'true' : 'false');
      if (historyOpen) { $('histRange').max = String(S.seq); $('histRange').value = String(S.seq); showAt(S.seq); }
    });
    $('histRange').addEventListener('input', function () { showAt(+$('histRange').value); });
    $('restore').addEventListener('click', function () {
      var to = +$('histRange').value;
      send([op('restore', { to: to })]).then(function () { toast('Brought back the version from change ' + to + '. Comments and decisions stay.'); });
    });
    $('logOpen').addEventListener('click', openLog);
    $('inviteBox').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var label = $('inviteWho').value; if (!label) return;
      act('invite', { label: label, role: $('inviteRole').value }).then(function (got) { toast('Asked ' + got.label + ' in, as ' + got.role + '.'); }).catch(fail);
    });
    $('leave').addEventListener('click', function () {
      act('leave').then(function () { location.href = '/link'; }).catch(fail);
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeLog(); });
    loadPeers();
  }

  function showAt(seq) {
    API.get(base + '/history?seq=' + seq).then(function (h) {
      var d = h.doc;
      var lines = [d.fields.title || ''];
      Object.keys(d.lists || {}).forEach(function (k) { d.lists[k].forEach(function (it) { lines.push((it.fields.done ? '[x] ' : '[ ] ') + (it.fields.text || '')); }); });
      Object.keys(d.texts || {}).forEach(function (k) { if (d.texts[k].text) lines.push('', d.texts[k].text); });
      $('preview').textContent = lines.join('\n');
      $('histSaid').textContent = seq >= S.seq ? 'Now.' : 'As it was after change ' + seq + ' of ' + S.seq + '.';
      $('restore').disabled = seq >= S.seq;
    }).catch(fail);
  }

  function loadPeers() {
    API.get('/api/link').then(function (st) {
      var sel = clear($('inviteWho'));
      var ok = (st.peers || []).filter(function (p) { return p.state === 'connected'; });
      if (!ok.length) sel.appendChild(el('option', { value: '', text: 'No connected Rouh yet' }));
      ok.forEach(function (p) { sel.appendChild(el('option', { value: p.label, text: p.name + ' (' + p.trust_word + ')' })); });
    }).catch(function () {});
  }

  function openLog() {
    API.get(base + '/log').then(function (got) {
      var d = $('logDrawer'); d.hidden = false; $('scrim').hidden = false;
      var ul = clear($('logList'));
      (got.entries || []).slice().reverse().forEach(function (e) {
        var when = new Date(e.at * 1000);
        ul.appendChild(el('li', {}, [el('span', { class: 'when', text: when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' + when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }),
          el('span', { text: e.plain })]));
      });
      if (!(got.entries || []).length) ul.appendChild(el('li', { class: 'dim', text: 'Nothing yet.' }));
      $('logClose').focus();
    }).catch(fail);
  }
  function closeLog() { $('logDrawer').hidden = true; $('scrim').hidden = true; }

  document.addEventListener('DOMContentLoaded', function () {
    $('logClose').addEventListener('click', closeLog);
    $('scrim').addEventListener('click', closeLog);
    $('themeSwitch').addEventListener('click', function () {
      var root = document.documentElement;
      var dark = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
      root.setAttribute('data-theme', dark ? 'light' : 'dark');
      try { localStorage.setItem('link-theme', root.getAttribute('data-theme')); } catch (e) {}
    });
    try { var th = localStorage.getItem('link-theme'); if (th) document.documentElement.setAttribute('data-theme', th); } catch (e) {}
    wire();
    poll();
  });
})();
