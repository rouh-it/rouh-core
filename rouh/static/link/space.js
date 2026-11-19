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
  var colours = {};          // actor label -> colour slot
  var seenItems = {};
  var cur = null;            // live cursors (link/cursors.js), started once the person is in the space
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

  // Every list and every long text the space's kind has (a task: steps and notes; a trip: flights,
  // stays, places and notes; research: sources, findings and a summary; ...), each a section of its own,
  // made once and filled again on every change, so a box being typed in keeps its place.
  var listBoxes = {}, textBoxes = {};

  function listBox(name) {
    if (listBoxes[name]) return listBoxes[name];
    var input = el('input', { type: 'text', class: 'grow', maxlength: '300', 'aria-label': 'New item for ' + listWord(name), placeholder: 'Add to ' + listWord(name).toLowerCase() });
    var form = el('form', { class: 'row', style: 'margin-top:10px', onsubmit: function (ev) { ev.preventDefault(); addItem(name, input); } },
      [input, el('button', { type: 'submit', text: 'Add' })]);
    var b = { marks: el('span'), ul: el('ul', { class: 'steps' }), form: form };
    b.section = el('section', { class: 'box part', 'data-part': 'list:' + name }, [
      el('header', {}, [el('h2', { text: listWord(name) }), b.marks]), b.ul, form]);
    $('lists').appendChild(b.section);
    return (listBoxes[name] = b);
  }
  function listWord(name) { return (S.space.names || {})[name] || name; }

  function drawLists() {
    (S.space.lists || []).forEach(drawList);
  }

  function drawList(listName) {
    var b = listBox(listName);
    b.form.hidden = !canEdit();
    var items = (S.doc.lists || {})[listName] || [];
    var focusId = document.activeElement && document.activeElement.getAttribute('data-item');
    clear(b.marks).appendChild(marksFor('list:' + listName).node);
    var ul = clear(b.ul);
    if (!items.length) ul.appendChild(el('li', { class: 'dim small', text: 'Nothing here yet. Add one, or ask your Rouh to.' }));
    items.forEach(function (it) {
      var part = 'item:' + it.id;
      var marks = marksFor(part);
      var claim = claimOf(part) || claimOf('list:' + listName);
      var text = el('textarea', { rows: '1', class: 'text', 'data-item': it.id, 'aria-label': listWord(listName) + ' item',
        disabled: !canEdit(),
        onfocus: function () { myPart = part; nudge(); },
        onkeydown: function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); text.blur(); } },
        oninput: function () { fit(text); },
        onchange: function () { send([op('set', { path: ['lists', listName, it.id, 'text'], v: text.value.replace(/\n/g, ' ').slice(0, 300) })]); } });
      text.value = String(it.fields.text || '');
      var under = el('div', { class: 'under' });
      var li = el('li', { class: 'step part' + (it.fields.done ? ' done' : '') + (marks.colour ? ' marked' : '') + (seenItems[it.id] ? '' : ' new'),
        style: marks.colour ? '--mc:' + marks.colour : (isRouh(it.by) ? '--mc:var(--' + ['accent', 'partner', 'third', 'fourth', 'dim'][slot(labelOf(it.by))] + ')' : ''),
        'data-part': part }, [
        el('input', { type: 'checkbox', checked: !!it.fields.done, 'aria-label': 'Done', disabled: !canEdit(),
          onchange: function (ev) { send([op('set', { path: ['lists', listName, it.id, 'done'], v: ev.target.checked })]); } }),
        text,
        el('span', { class: 'tools' }, [
          claim ? null : el('button', { class: 'quiet', text: 'Claim', title: 'Take this: only you change it until you let it go', disabled: !canEdit(),
            onclick: function () { send([op('claim', { part: part })]); } }),
          claim ? el('button', { class: 'quiet', text: labelOf(claim.by) === S.me.label && !isRouh(claim.by) ? 'Let go' : 'Take back', disabled: !canEdit(),
            onclick: function () { send([op('release', { part: claim.part || part })]); } }) : null,
          el('button', { class: 'quiet', text: 'Comment', onclick: function () { commentForm(part, under); } }),
          el('button', { class: 'quiet subtle', 'aria-label': 'Remove', text: 'Remove', disabled: !canEdit(),
            onclick: function () { send([op('remove', { list: listName, item: it.id })]); } })
        ]),
        under
      ]);
      seenItems[it.id] = true;
      requestAnimationFrame(function () { fit(text); });
      [marks.node.childNodes.length ? marks.node : null,
        claim ? el('span', { class: 'claimed dim' }, ['Claimed by ', tag(claim.by)]) : null,
        isRouh(it.by) && labelOf(it.by) !== S.me.label ? el('span', { class: 'byline', text: 'Added by ' + actorWords(it.by) }) : null,
        commentsFor(part)].forEach(function (n) { if (n) under.appendChild(n); });
      ul.appendChild(li);
    });
    if (focusId) { var again = b.ul.querySelector('[data-item="' + focusId + '"]'); if (again) again.focus(); }
  }

  // An item's text grows to show all of it, where the browser cannot size the box by itself.
  function fit(t) { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }

  function addItem(listName, input) {
    var t = input.value.trim(); if (!t) return;
    var items = (S.doc.lists || {})[listName] || [];
    var pos = items.length ? items[items.length - 1].pos + 1 : 1;
    input.value = '';
    send([op('add', { list: listName, item: uid().slice(0, 12), pos: pos, fields: { text: t.slice(0, 300), done: false } })]);
  }

  function textBox(name) {
    if (textBoxes[name]) return textBoxes[name];
    var b = { busy: false, timer: null, marks: el('span'), by: el('span', { class: 'row' }), comments: el('div'),
      title: el('h2', { text: textTitle(name) }), claim: el('span', { class: 'row' }) };
    b.ta = el('textarea', { rows: '6', 'aria-label': textTitle(name), placeholder: 'Write here; everyone sees it as you type.',
      oninput: function () { b.busy = true; clearTimeout(b.timer); b.timer = setTimeout(function () { sendText(name); }, 260); },
      onfocus: function () { myPart = 'text:' + name; nudge(); tellSelection(b.ta); },
      onkeyup: function () { tellSelection(b.ta); }, onmouseup: function () { tellSelection(b.ta); },
      onselect: function () { tellSelection(b.ta); } });
    b.ta._textName = name;
    var holder = el('div');
    b.section = el('section', { class: 'box part notes', 'data-part': 'text:' + name }, [
      el('header', {}, [b.title, el('span', { class: 'row' }, [b.marks, b.claim])]),
      el('div', { class: 'stack' }, [b.ta, el('div', { class: 'row' }, [el('span', { class: 'byline', text: 'Written by' }), b.by,
        el('span', { class: 'spacer grow' }), el('button', { class: 'quiet', type: 'button', text: 'Comment',
          onclick: function () { commentForm('text:' + name, holder); } })]), b.comments, holder])]);
    $('texts').appendChild(b.section);
    return (textBoxes[name] = b);
  }

  // The texts: the kind's own, then one body for each section of a document or page, in the sections'
  // order, so a team writes one document side by side, each section claimed by whoever writes it.
  function textNames() {
    var names = (S.space.texts || []).slice();
    ((S.doc.lists || {}).sections || []).forEach(function (it) { names.push('sec-' + it.id); });
    return names;
  }
  function textTitle(name) {
    if (name.indexOf('sec-') === 0) {
      var it = findItem(name.slice(4));
      return it ? String(it.fields.text || 'A section') : 'A section';
    }
    return (S.space.names || {})[name] || name;
  }
  function drawTexts() {
    var names = textNames();
    names.forEach(drawText);
    // In order, moving only a box that is out of place (a box being typed in stays put).
    var host = $('texts'), want = names.map(function (n) { return textBox(n).section; });
    want.forEach(function (node, i) { if (host.children[i] !== node && document.activeElement && !node.contains(document.activeElement)) host.insertBefore(node, host.children[i] || null); });
    Object.keys(textBoxes).forEach(function (n) { if (names.indexOf(n) < 0) textBoxes[n].section.hidden = true; else textBoxes[n].section.hidden = false; });
  }

  function drawText(name) {
    var b = textBox(name);
    var t = (S.doc.texts || {})[name] || { text: '', ids: [], by: [], top: 0 };
    var ta = b.ta;
    var part = 'text:' + name;
    b.title.textContent = textTitle(name);
    var claim = claimOf(part);
    ta.disabled = !canEdit() || !!(claim && claim.by !== S.me.person && claim.by !== S.me.rouh && isRouh(claim.by) && false);
    clear(b.claim);
    if (claim) b.claim.appendChild(el('span', { class: 'claimed small' }, ['Claimed by ', tag(claim.by)]));
    if (canEdit()) b.claim.appendChild(claim
      ? el('button', { class: 'quiet', text: claim.by === S.me.person ? 'Let go' : 'Take back', onclick: function () { send([op('release', { part: part })]); } })
      : el('button', { class: 'quiet', text: 'Claim', title: 'Take this part: only you and your Rouh change it until you let it go', onclick: function () { send([op('claim', { part: part })]); } }));
    var marks = marksFor(part);
    clear(b.marks).appendChild(marks.node);
    b.section.classList.toggle('marked', !!marks.colour);
    if (marks.colour) b.section.style.setProperty('--mc', marks.colour);
    var writers = {};
    (t.by || []).forEach(function (r) { writers[r[2]] = (writers[r[2]] || 0) + r[1]; });
    clear(b.by);
    Object.keys(writers).forEach(function (a) { b.by.appendChild(tag(a)); });
    clear(b.comments).appendChild(commentsFor(part));
    if (b.busy) return;
    if (ta.value !== t.text) {
      // The person's own caret and selection stay on the same characters through the others' edits,
      // both ends by the ids of the characters round them, as the others' are drawn (`indexOf`).
      var focused = document.activeElement === ta, oldIds = ta._ids || [];
      var ps = posAt(oldIds, ta.selectionStart), pe = posAt(oldIds, ta.selectionEnd), dir = ta.selectionDirection;
      ta.value = t.text;
      if (focused) ta.setSelectionRange(indexOf(t.ids, t.text.length, ps), indexOf(t.ids, t.text.length, pe), dir);
    }
    ta._ids = t.ids.slice();
    ta._text = t.text;
    ta._top = t.top;
    tellSelection(ta);   // the ids under the caret may be new now; cursors.js sends only a change
  }

  function sendText(name) {
    var b = textBox(name), ta = b.ta;
    var old = ta._text || '', ids = ta._ids || [], now = ta.value;
    var a = 0; while (a < old.length && a < now.length && old[a] === now[a]) a++;
    var e = 0; while (e < old.length - a && e < now.length - a && old[old.length - 1 - e] === now[now.length - 1 - e]) e++;
    var gone = ids.slice(a, old.length - e);
    var added = now.slice(a, now.length - e);
    var after = a > 0 ? ids[a - 1] : '';
    var ops = [];
    if (gone.length) ops.push(op('del', { t: name, ids: gone }));
    if (added) {
      var n = (ta._top || 0) + 1;
      ops.push(op('ins', { t: name, after: after, id0: n + '~' + S.me.person, text: added }));
      ta._top = n + added.length;
    }
    if (!ops.length) { b.busy = false; return; }
    var sent = now;
    send(ops).then(function () {
      return API.get(base + '?since=-1&wait=0&part=' + encodeURIComponent(myPart));
    }).then(function (st) {
      if (!st) { b.busy = false; return; }
      S = st; version = Math.max(version, st.version);
      var t = (st.doc.texts || {})[name] || { text: '', ids: [], top: 0 };
      if (ta.value !== sent) {
        // More was typed while this went: diff the rest against what the room has now.
        ta._text = t.text; ta._ids = t.ids.slice(); ta._top = t.top;
        sendText(name);
        return;
      }
      b.busy = false;
      draw();
    }).catch(function () { b.busy = false; });
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
      // Under a written grant: yes for another person, checked by their Rouh's code against the grant.
      var forOthers = p.state === 'open' ? (S.grants_in || []).filter(function (g) {
        return g.what === 'meetings' && needed.indexOf(g.from) >= 0 && !(p.yes || {})[g.from];
      }) : [];
      box.appendChild(el('div', { class: 'option' + (chosen ? ' chosen' : '') }, [
        el('div', {}, [el('div', { text: o.label }), yeses]),
        p.state === 'open' && needed.indexOf(S.me.label) >= 0 ?
          el('button', { class: mine && mine.option === o.id ? 'quiet' : '', text: mine && mine.option === o.id ? 'Your yes' : 'Yes, this time',
            'aria-pressed': mine && mine.option === o.id ? 'true' : 'false',
            onclick: function () { send([op('yes', { pid: p.id, option: o.id })]); } }) :
          (chosen ? el('span', { class: 'state-mark good' }, [svgCheck(), 'This one']) : el('span'))
      ]));
      forOthers.forEach(function (g) {
        var who = memberName(g.from).split(' ·')[0];
        box.lastChild.appendChild(el('button', { class: 'quiet', text: 'Yes for ' + who + ', under their grant', title: g.words,
          onclick: function () { act('yes_for', { granter: g.from, proposal: p.id, option: o.id })
            .then(function () { toast(who + '’s Rouh checked it against the grant and said yes for them.'); }).catch(fail); } }));
      });
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
    // The stand-in: a member's Rouh that holds the room while this one is off (the owner chooses).
    var sb = clear($('standinBox'));
    var editors = (S.space.members || []).filter(function (m) { return m.state === 'joined' && m.role === 'editor'; });
    if (S.space.mine && S.space.state === 'live' && editors.length) {
      var sel = el('select', { id: 'standinWho', 'aria-label': 'Stand-in while your Rouh is off' });
      sel.appendChild(el('option', { value: '', text: 'No stand-in' }));
      editors.forEach(function (m) { sel.appendChild(el('option', { value: m.label, text: m.name.split(' ·')[0] + '’s Rouh', selected: S.space.standin === m.label })); });
      sel.addEventListener('change', function () { act('standin', { label: sel.value }).then(function () { toast(sel.value ? 'Stand-in named.' : 'No stand-in now.'); }).catch(fail); });
      sb.appendChild(el('label', { for: 'standinWho', text: 'Holds the room while your Rouh is off' }));
      sb.appendChild(sel);
    } else if (S.space.standin) {
      sb.appendChild(el('p', { class: 'small dim', text: (S.space.standin === S.me.label ? 'Your Rouh' : memberName(S.space.standin).split(' ·')[0] + '’s Rouh') + ' holds the room if its owner’s Rouh is off.' }));
    }
    if (S.space.epoch) sb.appendChild(el('p', { class: 'small dim', text: 'Locked for the group: key ' + S.space.epoch + ', new each time someone joins or leaves.' }));
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
    } else if (S.holder_off && S.space.standin_active) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: (S.space.standin_active === S.me.label ? 'Your Rouh' : memberName(S.space.standin_active).split(' ·')[0] + '’s Rouh') + ' holds the room while ' + memberName(S.space.holder).split(' ·')[0] + '’s Rouh is off. Everything goes back to it when it returns.' })]));
    } else if (S.holder_off) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'The Rouh holding this space is off. Your changes show here and wait' + (S.pending ? ' (' + S.pending + ' waiting)' : '') + '; they go when it is back.' })]));
    } else if (S.space.state === 'ended') {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'This space has ended. What is here stays to read.' })]));
    }
    if (following) {
      var p = presenceByActor()[following];
      var pointer = livePointer(following);   // a person's own pointer, when it is live, says more than their presence
      var on = pointer ? pointer.part : (p && p.part);
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'Following ' + actorWords(following) + (on ? ', on ' + partName(on) : '') + '.' }),
        el('button', { text: 'Stop following', onclick: function () { following = ''; nudge(); draw(); } })]));
      if (!pointer && p && p.part) {
        var target = document.querySelector('[data-part="' + p.part + '"]');
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
    drawLists();
    drawTexts();
    drawMeeting();
    drawMyRouh();
    drawMembers();
    if (historyOpen) $('histRange').max = String(S.seq);
    $('work').hidden = !S.space.joined;
    if (!cur && S.space.joined) startCursors();
  }

  function showGone() {
    clear($('main')).appendChild(el('div', { class: 'empty' }, [el('h2', { text: 'This space is not here' }),
      el('p', { text: 'It may have ended, or you were never asked into it.' }), el('a', { href: '/link', text: 'Back to Connections' })]));
  }

  // --- live cursors (step 189-09) -----------------------------------------------------------------
  // Each person's pointer, caret and selection, shared live with the others here, like Figma. The
  // talking is link/cursors.js; this draws. A point is a part of the space and a place inside it, so
  // it lands right on any screen; a caret is the text's character ids, so it follows everyone's edits.
  // Nothing of it is kept anywhere. People's colours only (--person-1..4), never a Rouh's.

  var others = {};           // actor -> what is known and drawn of their cursor
  var rings = [];            // touch taps, each drawn for 2 s
  var looping = false;
  var personColours = null;  // read from the theme, again when it changes
  var mirror = null;         // a hidden copy of a textarea, to measure where a character is
  var lastFollowScroll = 0;
  var FADE_AFTER = 4000, DROP_AFTER = 30000, RING_FOR = 2000;
  var calm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function startCursors() {
    if (!window.RouhCursors) return;
    cur = window.RouhCursors.start({ base: base, key: 'link-cursor-share', onCursors: takeCursors });
    var box = $('cursorShare');
    if (box) {
      box.checked = cur.sharing();
      box.addEventListener('change', function () { cur.share(box.checked); });
    }
  }

  // The innermost shared part under a point, and where in it, as fractions of its box.
  function partAt(target, cx, cy) {
    var node = target && target.closest ? target.closest('[data-part]') : null;
    if (!node || !$('work').contains(node)) return null;
    var r = node.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return { node: node, part: node.getAttribute('data-part'),
      x: Math.max(0, Math.min(1, (cx - r.left) / r.width)), y: Math.max(0, Math.min(1, (cy - r.top) / r.height)) };
  }

  function wireCursors() {
    document.addEventListener('pointermove', function (ev) {
      if (!cur || ev.pointerType === 'touch') return;
      var at = partAt(ev.target, ev.clientX, ev.clientY);
      cur.move(at ? { part: at.part, x: at.x, y: at.y } : { part: '' });
    }, { passive: true });
    // A finger lifting "leaves" too; the tap it made stays shown, so only a real pointer leaving counts.
    document.documentElement.addEventListener('pointerleave', function (ev) { if (cur && ev.pointerType !== 'touch') cur.move({ part: '' }); });
    document.addEventListener('pointerdown', function (ev) {
      if (!cur) return;
      var at = partAt(ev.target, ev.clientX, ev.clientY);
      if (ev.pointerType === 'touch' && at) cur.tap({ part: at.part, x: at.x, y: at.y });
      // Into another shared part that is not a text: the selection there is over. Anywhere else (the
      // ask box, a button outside the work) keeps it, so "this one" still means it.
      if (at && at.part.indexOf('text:') !== 0) cur.select(null);
    }, { passive: true });
    document.addEventListener('selectionchange', function () {
      var a = document.activeElement;
      if (a && a._textName) tellSelection(a);
    });
    var again = function () { personColours = null; };
    $('themeSwitch').addEventListener('click', function () { setTimeout(again, 0); });
    if (window.matchMedia) {
      var mq = matchMedia('(prefers-color-scheme: light)');
      if (mq.addEventListener) mq.addEventListener('change', again);
    }
  }

  // The person's own caret or selection in a live text, by the ids of the characters round it.
  function posAt(ids, i) {
    var p = { i: i };
    if (i > 0 && ids[i - 1]) p.b = ids[i - 1];
    if (ids[i]) p.n = ids[i];
    return p;
  }
  function tellSelection(ta) {
    if (!cur || !ta || document.activeElement !== ta || !ta._textName) return;
    var ids = ta._ids || [];
    var s = ta.selectionStart, e = ta.selectionEnd, back = ta.selectionDirection === 'backward';
    cur.select({ t: 'text:' + ta._textName, a: posAt(ids, back ? e : s), f: posAt(ids, back ? s : e) }, ta.value.slice(s, e));
  }
  // A place sent by someone else, in the text as it is here now: just after the character before it
  // if that is still here, else just before the one after it, else where it was, kept inside the text.
  function indexOf(ids, len, p) {
    if (!p) return 0;
    var k;
    if (p.b && (k = ids.indexOf(p.b)) >= 0) return Math.min(k + 1, len);
    if (p.n && (k = ids.indexOf(p.n)) >= 0) return Math.min(k, len);
    return Math.max(0, Math.min(len, p.i | 0));
  }

  function takeCursors(list) {
    var now = Date.now(), seen = {};
    (list || []).forEach(function (c) {
      if (!c || !c.actor || isRouh(c.actor)) return;
      seen[c.actor] = true;
      var o = others[c.actor];
      if (!o) o = others[c.actor] = { actor: c.actor, n: -1, at: 0, shown: false };
      if (c.gone) { dropCursor(c.actor); return; }
      if (c.n === o.n) return;
      o.n = c.n;
      o.c = c;
      o.at = now - Math.max(0, Number(c.age) || 0) * 1000;
      if (c.tap) {
        o.tapAt = [c.part, c.x, c.y].join('|');
        if (now - o.at < RING_FOR) rings.push({ actor: c.actor, part: c.part, x: c.x, y: c.y, t0: o.at });
      }
    });
    Object.keys(others).forEach(function (a) { if (!seen[a]) dropCursor(a); });
    if (following && others[following]) draw();   // the banner says where they point
    loop();
  }
  function dropCursor(actor) {
    var o = others[actor];
    if (o && o.nodes) Object.keys(o.nodes).forEach(function (k) { var n = o.nodes[k]; if (n.parentNode) n.parentNode.removeChild(n); });
    delete others[actor];
  }
  // A person's pointer on this screen, if it is live: fresh, on a part, and not just a touch tap.
  function livePointer(actor) {
    var o = others[actor];
    if (!o || !o.c || !o.c.part || Date.now() - o.at > FADE_AFTER) return null;
    if (o.tapAt === [o.c.part, o.c.x, o.c.y].join('|')) return null;
    return o.c;
  }

  // Colours: by the person's place in the members, so each person has the same colour on every screen.
  function colourOf(label) {
    if (!personColours) {
      var cs = getComputedStyle(document.documentElement);
      personColours = [1, 2, 3, 4].map(function (k) { return cs.getPropertyValue('--person-' + k).trim() || '#9d8cff'; });
    }
    var ms = (S && S.space.members) || [];
    var i = ms.map(function (m) { return m.label; }).indexOf(label);
    if (i < 0) { i = ms.length + Object.keys(others).indexOf('person:' + label); }
    return personColours[((i % 4) + 4) % 4];
  }
  // Dark words on a light colour, white on a dark one, so a label reads in either theme.
  function ink(hex) {
    var h = String(hex).replace('#', '');
    if (h.length < 6) h = h.split('').map(function (c) { return c + c; }).join('');
    var lin = function (i) { var c = parseInt(h.substr(i, 2), 16) / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    var L = 0.2126 * lin(0) + 0.7152 * lin(2) + 0.0722 * lin(4);
    return L > 0.18 ? '#0b1114' : '#ffffff';
  }
  function firstName(c) {
    var n = (c.name || memberName(labelOf(c.actor)) || '').split(' ·')[0].trim();
    return n.split(/\s+/)[0] || 'Someone';
  }

  function layer() {
    var l = $('cursorLayer');
    if (!l) { l = el('div', { id: 'cursorLayer', class: 'cursor-layer', 'aria-hidden': 'true' }); document.body.appendChild(l); }
    return l;
  }
  function node(o, key, make) {
    o.nodes = o.nodes || {};
    if (!o.nodes[key]) { o.nodes[key] = make(); layer().appendChild(o.nodes[key]); }
    return o.nodes[key];
  }
  function hide(o, key) { if (o.nodes && o.nodes[key]) o.nodes[key].style.display = 'none'; }
  function partNode(part) {
    if (!part) return null;
    var n = document.querySelector('[data-part="' + (window.CSS && CSS.escape ? CSS.escape(part) : part) + '"]');
    if (!n || !$('work').contains(n) || $('work').hidden) return null;
    var r = n.getBoundingClientRect();
    return r.width && r.height ? r : null;
  }

  function arrowNode(colour) {
    var d = el('div', { class: 'cur-arrow' });
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 20 22'); s.setAttribute('width', '20'); s.setAttribute('height', '22');
    var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'M2 1.5 L2 18 L6.4 14 L9.6 20.6 L12.6 19.2 L9.5 12.8 L15.6 12.8 Z');
    p.setAttribute('stroke-linejoin', 'round');
    s.appendChild(p); d.appendChild(s);
    d.appendChild(el('span', { class: 'cur-label' }));
    return d;
  }

  function loop() {
    if (looping) return;
    looping = true;
    requestAnimationFrame(frame);
  }
  function frame() {
    var now = Date.now();
    var vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var sx = window.scrollX, sy = window.scrollY;
    Object.keys(others).forEach(function (a) {
      var o = others[a], c = o.c;
      if (!c) return;
      if (now - o.at > DROP_AFTER) { dropCursor(a); return; }
      var colour = colourOf(labelOf(a));
      // The pointer: eased toward its newest point, in page coordinates so a scroll moves it at once.
      var r = c.part ? partNode(c.part) : null;
      var tapOnly = o.tapAt === [c.part, c.x, c.y].join('|');
      if (r && !tapOnly) {
        var tx = r.left + sx + c.x * r.width, ty = r.top + sy + c.y * r.height;
        if (!o.shown || calm || Math.abs(tx - o.dx) + Math.abs(ty - o.dy) > 900) { o.dx = tx; o.dy = ty; }
        else { o.dx += (tx - o.dx) * 0.35; o.dy += (ty - o.dy) * 0.35; }
        o.shown = true;
        var arrow = node(o, 'arrow', function () { return arrowNode(colour); });
        var vx = o.dx - sx, vy = o.dy - sy;
        arrow.style.display = '';
        arrow.style.transform = 'translate(' + Math.round(vx) + 'px,' + Math.round(vy) + 'px)';
        arrow.style.setProperty('--pc', colour);
        arrow.style.opacity = now - o.at > FADE_AFTER ? '0' : '1';
        var lab = arrow.lastChild;
        var name = firstName(c);
        if (lab.textContent !== name) lab.textContent = name;
        lab.style.color = ink(colour);
        // Near the right edge the label goes to the left of the arrow, so it is never cut off.
        arrow.classList.toggle('flip', vx + 16 + lab.offsetWidth > vw - 8);
        // Following this person: keep their point in the middle band of the screen.
        if (following === a && now - o.at < FADE_AFTER && now - lastFollowScroll > 700 && (vy < vh * 0.2 || vy > vh * 0.8)) {
          lastFollowScroll = now;
          window.scrollTo({ top: Math.max(0, ty - vh / 2), behavior: calm ? 'auto' : 'smooth' });
        }
      } else {
        o.shown = false;
        hide(o, 'arrow');
      }
      drawSelection(o, colour, now);
    });
    rings = rings.filter(function (g) {
      var t = (now - g.t0) / RING_FOR;
      var r = partNode(g.part);
      if (t >= 1 || !r) { if (g.node && g.node.parentNode) g.node.parentNode.removeChild(g.node); return false; }
      if (!g.node) { g.node = el('div', { class: 'cur-ring' }); layer().appendChild(g.node); }
      g.node.style.setProperty('--pc', colourOf(labelOf(g.actor)));
      var scale = calm ? 1 : 0.4 + 1.2 * t;
      g.node.style.transform = 'translate(' + Math.round(r.left + g.x * r.width) + 'px,' + Math.round(r.top + g.y * r.height) + 'px) scale(' + scale.toFixed(3) + ')';
      g.node.style.opacity = String((1 - t) * 0.95);
      return true;
    });
    looping = false;
    if (Object.keys(others).length || rings.length) loop();
  }

  // Someone's caret and selection in a live text: a 2 px bar with their name, and a band over the words.
  function drawSelection(o, colour, now) {
    var sel = o.c.sel;
    var b = sel && sel.t && sel.t.indexOf('text:') === 0 ? textBoxes[sel.t.slice(5)] : null;
    var ta = b && !b.section.hidden && !$('work').hidden ? b.ta : null;
    var box = ta ? ta.getBoundingClientRect() : null;
    if (!box || !box.width) { hide(o, 'caret'); hide(o, 'bands'); return; }
    var ids = ta._ids || [], len = ta.value.length;
    var ia = indexOf(ids, len, sel.a), ifo = indexOf(ids, len, sel.f);
    var s = Math.min(ia, ifo), e = Math.max(ia, ifo);
    var g = measure(ta, s, e, ifo);
    // The textarea's inside, on screen; what is scrolled out of it is not drawn.
    var left = box.left + ta.clientLeft - ta.scrollLeft, top = box.top + ta.clientTop - ta.scrollTop;
    var inTop = box.top + ta.clientTop, inBottom = inTop + ta.clientHeight;
    var inLeft = box.left + ta.clientLeft, inRight = inLeft + ta.clientWidth;
    var bands = node(o, 'bands', function () { return el('div', { class: 'cur-bands' }); });
    bands.style.display = '';
    bands.style.setProperty('--pc', colour);
    var want = g.rects.length;
    while (bands.childNodes.length < want) bands.appendChild(el('div', { class: 'cur-band' }));
    while (bands.childNodes.length > want) bands.removeChild(bands.lastChild);
    g.rects.forEach(function (q, i) {
      var y0 = Math.max(inTop, top + q.top), y1 = Math.min(inBottom, top + q.top + q.height);
      var x0 = Math.max(inLeft, left + q.left), x1 = Math.min(inRight, left + q.left + Math.max(q.width, 4));
      var d = bands.childNodes[i];
      if (y1 <= y0 || x1 <= x0) { d.style.display = 'none'; return; }
      d.style.display = '';
      d.style.transform = 'translate(' + x0 + 'px,' + y0 + 'px)';
      d.style.width = (x1 - x0) + 'px'; d.style.height = (y1 - y0) + 'px';
    });
    var cy = top + g.caret.top, cx = left + g.caret.left;
    if (cy + g.caret.height <= inTop || cy >= inBottom || cx < inLeft - 1 || cx > inRight + 1) { hide(o, 'caret'); return; }
    var caret = node(o, 'caret', function () { return el('div', { class: 'cur-caret' }, [el('span', { class: 'cur-flag' })]); });
    caret.style.display = '';
    caret.style.setProperty('--pc', colour);
    caret.style.transform = 'translate(' + Math.round(cx - 1) + 'px,' + Math.round(cy) + 'px)';
    caret.style.height = g.caret.height + 'px';
    var flag = caret.firstChild, name = firstName(o.c);
    if (flag.textContent !== name) flag.textContent = name;
    flag.style.color = ink(colour);
    // The name shows while they are at it, then only the bar and the band stay.
    caret.classList.toggle('quiet', now - o.at > FADE_AFTER);
  }

  // Where characters s..e and the caret at f sit inside a textarea, measured on a hidden copy with the
  // same font, padding, width and wrapping. Kept until the text, the width or the places change.
  function measure(ta, s, e, f) {
    var key = [ta.value.length, ta.clientWidth, s, e, f].join('|');
    ta._measured = ta._measured || {};
    var m = ta._measured[key];
    if (m && m.text === ta.value) return m;
    if (!mirror) { mirror = el('div', { class: 'cur-mirror', 'aria-hidden': 'true' }); document.body.appendChild(mirror); }
    var cs = getComputedStyle(ta);
    ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing', 'wordSpacing', 'lineHeight', 'textTransform',
      'textIndent', 'tabSize', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].forEach(function (p) { mirror.style[p] = cs[p]; });
    mirror.style.width = Math.max(0, ta.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) + 'px';
    var v = ta.value;
    clear(mirror);
    // A caret is a word joiner: no width, and no new place to break a line.
    var mark = function (t) { return el('span', { text: t }); };
    var caretSpan;
    if (s === e) {
      mirror.appendChild(document.createTextNode(v.slice(0, s)));
      mirror.appendChild(caretSpan = mark('⁠'));
      mirror.appendChild(document.createTextNode(v.slice(s) + '⁠'));
    } else {
      var band = mark(v.slice(s, e));
      mirror.appendChild(document.createTextNode(v.slice(0, s)));
      if (f === s) { mirror.appendChild(caretSpan = mark('⁠')); mirror.appendChild(band); }
      else { mirror.appendChild(band); mirror.appendChild(caretSpan = mark('⁠')); }
      mirror.appendChild(document.createTextNode(v.slice(e) + '⁠'));
    }
    var mr = mirror.getBoundingClientRect();
    var rects = [];
    if (s !== e) {
      Array.prototype.forEach.call(mirror.querySelectorAll('span')[f === s ? 1 : 0].getClientRects(), function (q) {
        rects.push({ left: q.left - mr.left, top: q.top - mr.top, width: q.width, height: q.height });
      });
    }
    var cr = caretSpan.getClientRects()[0] || caretSpan.getBoundingClientRect();
    var lh = parseFloat(cs.lineHeight) || cr.height || 20;
    m = { text: v, rects: rects, caret: { left: cr.left - mr.left, top: cr.top - mr.top + (cr.height - lh) / 2, height: lh } };
    if (Object.keys(ta._measured).length > 8) ta._measured = {};
    ta._measured[key] = m;
    return m;
  }

  // --- the side controls ------------------------------------------------------------------------------

  function wire() {
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
    wireCursors();
    poll();
  });
})();
