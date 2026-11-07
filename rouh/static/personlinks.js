/* Also known as: which Slack member, address and name is which person (rouh/synapse/aka.py).

   Petar, 22 October 2026: "give me interface to do that. I am guessing I should be doing this from
   contacts card of the person?!" One section, drawn the same on the contact card (app/cards.js,
   contactBlock) and on the person's card in Synapse (synapse.js, personCard), at every width:

   - every identifier the person holds beyond their iCloud card, each with Unlink;
   - one search box that finds Slack members, other people and addresses, and links the one picked in;
   - the people flagged as likely the same, each as its whole record side by side with this one (every
     address and number with its label, organisation, who they are, note, research, face, silos, where
     they are known from, when last seen: Petar, 27 October 2026, a name alone is too little to decide
     on), with Same person, Not the same person, and Edit them, for one that is somebody else entirely;
   - the last change with Undo, and every earlier one behind a closed toggle, each with its own Undo.

   It talks to /api/synapse/ds/<dataset>/item/<person>/aka, and after a change hands the answer to
   the page that drew it (`changed`), which draws the person again; with none, it draws itself again.
   Every word in it may be somebody's own (a Slack name, an address), so all of it goes in as text. */
(function () {
  'use strict';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  function button(cls, text, label) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (label) b.setAttribute('aria-label', label);
    return b;
  }

  function when(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var now = new Date();
    var time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) return 'today ' + time;
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ' ' + time;
  }

  var BY = { 'contact card': 'on the contact card', 'Synapse': 'in Synapse', 'Rouh': 'told Rouh' };

  function call(base, path, body) {
    var init = { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (body) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(base + path, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('Sign in again.'); }
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
        if (!r.ok || !j || j.ok === false) {
          throw new Error((j && (j.why || j.error)) || 'That could not be done (the server said ' + r.status + ').');
        }
        return j;
      });
    }, function () { throw new Error('Rouh could not be reached. Try again.'); });
  }

  /**
   * @param {{ds: string, person: string, data?: any, by: string, hideCard?: boolean,
   *          changed?: function(any): void, open?: function(string, string): Node,
   *          className?: string, titleTag?: string}} opts
   */
  function section(opts) {
    var base = '/api/synapse/ds/' + encodeURIComponent(opts.ds) + '/item/' + encodeURIComponent(opts.person) + '/aka';
    var box = el('section', 'pl' + (opts.className ? ' ' + opts.className : ''));
    var head = el('div', 'pl-head');
    var title = el(opts.titleTag || 'h5', 'pl-title', 'Also known as');
    title.id = 'plT' + Math.random().toString(36).slice(2, 9);
    box.setAttribute('aria-labelledby', title.id);
    head.appendChild(title);
    box.appendChild(head);
    var body = el('div', 'pl-body');
    box.appendChild(body);
    var said = el('p', 'pl-said');
    said.hidden = true;
    said.setAttribute('role', 'alert');
    var data = opts.data || null;
    var busy = false;

    function fail(e) {
      busy = false;
      box.classList.remove('is-busy');
      Array.prototype.forEach.call(box.querySelectorAll('button, input'), function (x) { x.disabled = false; });
      said.textContent = (e && e.message) || 'That could not be done.';
      said.hidden = false;
    }
    // A section whose card is drawn again by the page says why when that fails (app/cards.js).
    box.__said = function (why) { fail(new Error(why || 'That was not kept.')); };

    function act(path, sent) {
      if (busy) return;
      busy = true;
      box.classList.add('is-busy');
      said.hidden = true;
      Array.prototype.forEach.call(box.querySelectorAll('button, input'), function (x) { x.disabled = true; });
      sent.by = opts.by;
      call(base, path, sent).then(function (j) {
        if (opts.changed) { opts.changed(j); return; }
        return call(base, '', null).then(function (v) { busy = false; box.classList.remove('is-busy'); data = v; draw(); });
      }).catch(fail);
    }

    function idRow(x) {
      var li = el('li', 'pl-id is-' + x.type);
      li.appendChild(el('span', 'pl-kind', x.label || x.type));
      var what = el('span', 'pl-what');
      var val;
      if (x.href) {
        val = el('a', 'pl-val', x.shown);
        val.href = x.href;
        val.target = '_blank';
        val.rel = 'noopener';
      } else {
        val = el('span', 'pl-val', x.shown);
      }
      what.appendChild(val);
      var more = [x.detail, x.from].filter(Boolean).join(' · ');
      if (more) what.appendChild(el('span', 'pl-from', more));
      li.appendChild(what);
      if (x.unlink) {
        var b = button('pl-btn', 'Unlink', 'Unlink ' + x.shown);
        b.addEventListener('click', function () { act('/unlink', { type: x.type, value: x.value }); });
        li.appendChild(b);
      }
      return li;
    }

    function finder() {
      var wrap = el('div', 'pl-find');
      var input = el('input', 'pl-in');
      input.type = 'search';
      input.autocomplete = 'off';
      input.spellcheck = false;
      input.placeholder = 'Link a Slack member or a person';
      input.setAttribute('aria-label', 'Link to ' + ((data && data.person && data.person.name) || 'this person'));
      input.setAttribute('role', 'combobox');
      input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false');
      var list = el('ul', 'pl-found');
      list.id = 'plF' + Math.random().toString(36).slice(2, 9);
      list.setAttribute('role', 'listbox');
      list.setAttribute('aria-label', 'Found');
      list.hidden = true;
      input.setAttribute('aria-controls', list.id);
      var none = el('p', 'pl-none');
      none.hidden = true;
      var found = [], active = -1, seq = 0, timer = 0;

      function mark() {
        Array.prototype.forEach.call(list.children, function (li, i) {
          li.setAttribute('aria-selected', i === active ? 'true' : 'false');
          if (i === active) input.setAttribute('aria-activedescendant', li.id);
        });
        if (active < 0) input.removeAttribute('aria-activedescendant');
      }
      function show() {
        list.textContent = '';
        found.forEach(function (f, i) {
          var li = el('li', 'pl-opt is-' + f.kind);
          li.id = list.id + '-' + i;
          li.setAttribute('role', 'option');
          li.appendChild(el('span', 'pl-kind', { slack: 'Slack', person: 'Person', email: 'Email', name: 'Name' }[f.kind] || f.kind));
          var w = el('span', 'pl-what');
          w.appendChild(el('span', 'pl-val', f.name));
          if (f.detail) w.appendChild(el('span', 'pl-from', f.detail));
          li.appendChild(w);
          // mousedown, so the box keeps its focus until the pick is made.
          li.addEventListener('mousedown', function (e) { e.preventDefault(); });
          li.addEventListener('click', function () { pick(f); });
          list.appendChild(li);
        });
        list.hidden = !found.length;
        input.setAttribute('aria-expanded', found.length ? 'true' : 'false');
        none.hidden = !!found.length || !input.value.trim();
        none.textContent = 'Nobody found for “' + input.value.trim() + '”.';
        mark();
      }
      function search() {
        clearTimeout(timer);
        var q = input.value.trim(), mine = ++seq;
        if (!q) { found = []; active = -1; show(); return; }
        timer = setTimeout(function () {
          call(base, '/find?q=' + encodeURIComponent(q), null).then(function (j) {
            if (mine !== seq) return;
            found = j.found || [];
            active = found.length ? 0 : -1;
            show();
          }).catch(function (e) { if (mine === seq) fail(e); });
        }, 160);
      }
      function pick(f) {
        var sent = f.kind === 'person' ? { kind: 'person', id: f.id } : { kind: f.kind, value: f.value };
        act('/link', { pick: sent });
      }
      input.addEventListener('input', search);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown' && found.length) { e.preventDefault(); active = (active + 1) % found.length; mark(); }
        else if (e.key === 'ArrowUp' && found.length) { e.preventDefault(); active = (active - 1 + found.length) % found.length; mark(); }
        else if (e.key === 'Enter' && active >= 0 && found[active]) { e.preventDefault(); pick(found[active]); }
        else if (e.key === 'Escape') {
          // Escape empties the box and nothing else: not a turn, not a panel.
          e.preventDefault(); e.stopPropagation();
          input.value = ''; found = []; active = -1; show();
        }
      });
      wrap.appendChild(input);
      wrap.appendChild(list);
      wrap.appendChild(none);
      return wrap;
    }

    function face(r) {
      var f = el('span', 'pl-face');
      f.setAttribute('aria-hidden', 'true');
      var words = String(r.name || '').trim().split(/\s+/).filter(Boolean);
      var initials = ((words[0] || '?')[0] + (words.length > 1 ? words[words.length - 1][0] : '')).toUpperCase();
      if (r.photo) {
        var img = document.createElement('img');
        img.alt = '';
        img.src = r.photo;
        img.addEventListener('error', function () { img.remove(); f.textContent = initials; });
        f.appendChild(img);
      } else {
        f.textContent = initials;
      }
      return f;
    }

    // One field of a record, as the comparison draws it: nothing known is said, never left blank.
    function cell(r, key) {
      var td = el('td', 'pl-cell');
      function line(text, small) {
        var p = el('span', 'pl-line', text);
        if (small) p.appendChild(el('span', 'pl-from', ' ' + small));
        td.appendChild(p);
      }
      if (!r) return td;
      if (key === 'emails' || key === 'phones') {
        (r[key] || []).forEach(function (x) { line(x.value, [x.label, x.from].filter(Boolean).join(' · ')); });
      } else if (key === 'silos') {
        (r.silos || []).forEach(function (c) {
          var chip = el('span', 'silo-chip');
          if (/^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
          chip.appendChild(el('span', 'silo-dot'));
          chip.appendChild(el('span', 'silo-name', c.name));
          td.appendChild(chip);
        });
      } else if (key === 'known_from') {
        if ((r.known_from || []).length) line(r.known_from.join(', '), r.items ? '(' + r.items + ' item' + (r.items === 1 ? '' : 's') + ')' : '');
      } else if (key === 'last_seen') {
        if (r.last_seen) line(when(r.last_seen));
      } else if (key === 'research') {
        var text = String(r.research || '');
        if (text.length > 220) {
          var d = el('details', 'pl-more');
          d.appendChild(el('summary', null, text.slice(0, 200).replace(/\s+\S*$/, '') + '…'));
          d.appendChild(el('div', 'pl-whole', text));
          td.appendChild(d);
        } else if (text) {
          td.appendChild(el('div', 'pl-whole', text));
        }
      } else if (key === 'slack') {
        (r.slack || []).forEach(function (x) { line(x); });
      } else if (r[key]) {
        td.appendChild(el('div', 'pl-whole', r[key]));
      }
      if (!td.childNodes.length) td.appendChild(el('span', 'pl-none-said', 'none'));
      return td;
    }

    var FIELDS = [['emails', 'Email'], ['phones', 'Phone'], ['organisation', 'Organisation'],
      ['relationship', 'Who they are'], ['note', 'Note'], ['research', 'Research'], ['silos', 'Silos'],
      ['slack', 'Slack'], ['known_from', 'Known from'], ['last_seen', 'Last seen']];

    function compare(mine, theirs) {
      var wrap = el('div', 'pl-compare-wrap');
      var table = el('table', 'pl-compare');
      var head = el('tr');
      head.appendChild(el('th', 'pl-k', ''));
      [[mine, 'This contact'], [theirs, 'Maybe the same']].forEach(function (pair) {
        var th = el('th', 'pl-who');
        th.setAttribute('scope', 'col');
        var r = pair[0] || {};
        th.appendChild(face(r));
        var w = el('span', 'pl-who-words');
        w.appendChild(el('span', 'pl-who-name', r.name || '(no name)'));
        w.appendChild(el('span', 'pl-from', pair[1]));
        th.appendChild(w);
        head.appendChild(th);
      });
      var thead = el('thead');
      thead.appendChild(head);
      table.appendChild(thead);
      var body = el('tbody');
      FIELDS.forEach(function (f) {
        if (!(mine && hasField(mine, f[0])) && !hasField(theirs, f[0])) return;
        var tr = el('tr');
        var th = el('th', 'pl-k', f[1]);
        th.setAttribute('scope', 'row');
        tr.appendChild(th);
        tr.appendChild(cell(mine, f[0]));
        tr.appendChild(cell(theirs, f[0]));
        body.appendChild(tr);
      });
      table.appendChild(body);
      wrap.appendChild(table);
      return wrap;
    }

    function hasField(r, key) {
      if (!r) return false;
      var v = r[key];
      return Array.isArray(v) ? v.length > 0 : !!v;
    }

    // The candidate's own fields, corrected in place: sometimes it is somebody else entirely.
    function editor(x, r, done) {
      var form = el('form', 'pl-edit');
      form.setAttribute('autocomplete', 'off');
      var inputs = {};
      [['name', 'Name', r.name], ['organisation', 'Organisation', r.organisation],
       ['relationship', 'Who they are to you', r.relationship], ['note', 'Note', r.note],
       ['email', 'Add an email', ''], ['phone', 'Add a phone', '']].forEach(function (f) {
        var lab = el('label', 'pl-field');
        lab.appendChild(el('span', 'pl-field-name', f[1]));
        var input = el(f[0] === 'note' || f[0] === 'relationship' ? 'textarea' : 'input', 'pl-in');
        if (input.tagName === 'INPUT') input.type = f[0] === 'email' ? 'email' : 'text';
        else input.rows = 2;
        input.value = f[2] || '';
        input.spellcheck = false;
        inputs[f[0]] = input;
        lab.appendChild(input);
        form.appendChild(lab);
      });
      var row = el('div', 'pl-picks');
      var save = el('button', 'pl-btn is-main', 'Save');
      save.type = 'submit';
      var cancel = button('pl-btn', 'Cancel');
      row.appendChild(save);
      row.appendChild(cancel);
      form.appendChild(row);
      cancel.addEventListener('click', function () { done(false); });
      form.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
      });
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (busy) return;
        var name = inputs.name.value.trim();
        if (!name) { inputs.name.focus(); return; }
        var sent = { name: name, organisation: inputs.organisation.value.trim(),
                     relationship: inputs.relationship.value.trim(), note: inputs.note.value.trim() };
        if (inputs.email.value.trim()) sent.emails = [inputs.email.value.trim()];
        if (inputs.phone.value.trim()) sent.phones = [inputs.phone.value.trim()];
        busy = true;
        box.classList.add('is-busy');
        said.hidden = true;
        Array.prototype.forEach.call(form.querySelectorAll('button, input, textarea'), function (b) { b.disabled = true; });
        var edit = '/api/synapse/ds/' + encodeURIComponent(opts.ds) + '/item/' + encodeURIComponent(x.id) + '/edit';
        call(edit, '', sent).then(function () {
          return call(base, '', null);
        }).then(function (v) {
          busy = false;
          box.classList.remove('is-busy');
          data = v;
          editing = '';
          draw();
        }).catch(fail);
      });
      setTimeout(function () { inputs.name.focus(); }, 0);
      return form;
    }

    var editing = '';

    function sameRow(x) {
      var li = el('li', 'pl-maybe');
      var r = x.record || { name: x.name, emails: [], phones: [] };
      var top = el('div', 'pl-maybe-head');
      var w = el('span', 'pl-what');
      var name = opts.open ? opts.open(x.id, x.name) : el('span', 'pl-val', x.name);
      if (name.classList) name.classList.add('pl-val');
      w.appendChild(name);
      if (x.why) w.appendChild(el('span', 'pl-from', 'Flagged: ' + x.why));
      top.appendChild(w);
      li.appendChild(top);
      if (editing === x.id) {
        li.appendChild(editor(x, r, function () { editing = ''; draw(); }));
        return li;
      }
      li.appendChild(compare(data.this, r));
      var picks = el('div', 'pl-picks');
      var yes = button('pl-btn is-main', 'Same person', x.name + ' is the same person');
      yes.addEventListener('click', function () { act('/link', { pick: { kind: 'person', id: x.id } }); });
      var no = button('pl-btn', 'Not the same person', x.name + ' is not the same person');
      no.addEventListener('click', function () { act('/apart', { other: x.id }); });
      var edit = button('pl-btn', 'Edit them', 'Edit ' + x.name);
      edit.addEventListener('click', function () { editing = x.id; draw(); });
      picks.appendChild(yes);
      picks.appendChild(no);
      picks.appendChild(edit);
      li.appendChild(picks);
      return li;
    }

    function changeRow(c) {
      var li = el('li', 'pl-change' + (c.undone ? ' is-undone' : ''));
      var w = el('span', 'pl-what');
      w.appendChild(el('span', 'pl-val', c.what));
      w.appendChild(el('span', 'pl-from', [BY[c.by] || c.by, when(c.at),
        c.undone ? 'undone' + (BY[c.undone_by] ? ' ' + BY[c.undone_by] : '') : ''].filter(Boolean).join(' · ')));
      li.appendChild(w);
      if (c.can_undo) {
        var b = button('pl-btn', 'Undo', 'Undo: ' + c.what);
        b.addEventListener('click', function () { act('/undo', { change: c.id }); });
        li.appendChild(b);
      }
      return li;
    }

    function draw() {
      body.textContent = '';
      if (!data) { body.appendChild(el('p', 'pl-empty', 'Reading…')); return; }
      var ids = (data.ids || []).filter(function (x) {
        if (x.type === 'name' && !x.unlink) return false;  // their own name, at the top of the card
        // Addresses are one list of their own on the contact card, with Unlink (personaddresses.js).
        if (opts.hideEmails && x.type === 'email') return false;
        return !(opts.hideCard && x.from === 'on their iCloud card');
      });
      if (ids.length) {
        var ul = el('ul', 'pl-ids');
        ids.forEach(function (x) { ul.appendChild(idRow(x)); });
        body.appendChild(ul);
      }
      body.appendChild(finder());
      var same = data.likely_same || [];
      if (same.length) {
        var sh = el('div', 'pl-sub');
        sh.appendChild(el('h6', 'pl-subtitle', 'Likely the same person'));
        var su = el('ul', 'pl-ids');
        same.forEach(function (x) { su.appendChild(sameRow(x)); });
        sh.appendChild(su);
        body.appendChild(sh);
      }
      var hist = data.history || [];
      if (hist.length) {
        var last = el('ul', 'pl-ids pl-last');
        last.setAttribute('aria-label', 'Last change');
        last.appendChild(changeRow(hist[0]));
        body.appendChild(last);
        if (hist.length > 1) {
          var more = el('details', 'pl-hist');
          more.appendChild(el('summary', null, 'Earlier changes (' + (hist.length - 1) + ')'));
          var hu = el('ul', 'pl-ids');
          hist.slice(1).forEach(function (c) { hu.appendChild(changeRow(c)); });
          more.appendChild(hu);
          body.appendChild(more);
        }
      }
      body.appendChild(said);
    }

    draw();
    // What the card was drawn with may be older than what is kept now: read it, and draw it again only
    // if it differs, so nothing moves under the person's hand for no reason.
    call(base, '', null).then(function (v) {
      if (busy) return;
      if (JSON.stringify(v) !== JSON.stringify(data)) { data = v; draw(); }
    }).catch(function (e) { if (!data) fail(e); });
    return box;
  }

  window.RouhPersonLinks = { section: section };
})();
