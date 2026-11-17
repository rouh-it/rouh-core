/* A contact's relationships with other contacts and with the person (rouh/relationships.py).

   The person, 17 November 2026 (INC-553): "relationships types between contacts. pet of, wife of, ex bf,
   brother, friends, coworkers, tennis buddies, strangers, unknown ... a bunch of popular ones and then
   custom ones possible too." Drawn on the contact card (app/cards.js, contactBlock), the person's own
   card included. Each row is the link as this contact's side reads it, "Wife of: Sara", with Change and
   Remove; Add relationship opens a form in place: who (a contact, or You), what this contact is to them
   (the common types, the person's own, or a new one typed in), and what they are to this contact, filled
   in from the type and changeable. A link shows on both cards, so the other card reads it from its side.

   It talks to /api/people/<person>/relationships. What it was drawn with may be older than what is kept
   (a card drawn before a change on the other card, or in chat), so it reads the list once and draws again
   if it differs. Every word in it may be somebody's own, so all of it goes in as text. */
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

  function call(url, body) {
    var init = { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (body) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(function (r) {
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

  var NEW = '\u0000new';
  var uid = 0;

  /**
   * @param {{data: any, name?: string, editable?: boolean}} opts
   */
  function list(opts) {
    var data = opts.data || { rows: [], types: [] };
    var me = data.person === 'me';
    var mine = me ? 'You' : (opts.name || 'This contact');
    var box = el('section', 'pr');
    var head = el('div', 'pr-head');
    var title = el('h5', 'pr-title', 'Relationships');
    title.id = 'prT' + (++uid);
    box.setAttribute('aria-labelledby', title.id);
    head.appendChild(title);
    var editable = opts.editable !== false && !!data.person;
    var addBtn = null;
    if (editable) {
      addBtn = button('pr-btn pr-add', 'Add relationship');
      addBtn.addEventListener('click', function () { openForm(null); });
      head.appendChild(addBtn);
    }
    box.appendChild(head);
    var ul = el('ul', 'pr-rows');
    box.appendChild(ul);
    var formSlot = el('div', 'pr-form-slot');
    box.appendChild(formSlot);
    var said = el('p', 'pr-said');
    said.hidden = true;
    said.setAttribute('role', 'status');
    box.appendChild(said);
    var busy = false;
    var editing = null;      // the row id whose form is open, 0 for a new one, null for none

    function base() {
      return '/api/people/' + encodeURIComponent(data.person || '') + '/relationships';
    }

    function setBusy(on) {
      busy = on;
      box.classList.toggle('is-busy', on);
      Array.prototype.forEach.call(box.querySelectorAll('button, input, select'), function (x) { x.disabled = on; });
    }

    function tell(text, isBad, undo) {
      said.textContent = '';
      said.classList.toggle('is-bad', !!isBad);
      said.appendChild(el('span', null, text));
      if (undo) {
        var u = button('pr-link', 'Undo');
        u.addEventListener('click', undo);
        said.appendChild(u);
      }
      said.hidden = !text;
    }

    function took(j, message, undo) {
      setBusy(false);
      data = j;
      editing = null;
      formSlot.textContent = '';
      draw();
      tell(message || '', false, undo);
      if (addBtn) addBtn.hidden = false;
    }

    function fail(e) {
      setBusy(false);
      tell((e && e.message) || 'That could not be done.', true);
    }

    function send(body, message, undo) {
      if (busy) return;
      setBusy(true);
      tell('');
      return call(base(), body).then(function (j) { took(j, message, undo); }).catch(fail);
    }

    function draw() {
      ul.textContent = '';
      var rows = data.rows || [];
      ul.hidden = !rows.length;
      box.classList.toggle('is-empty', !rows.length);
      var empty = box.querySelector('.pr-empty');
      if (!rows.length && editing === null) {
        if (!empty) {
          empty = el('p', 'pr-empty', me ? 'Nobody is linked to you yet.' : 'Not linked to anybody yet.');
          box.insertBefore(empty, ul);
        }
      } else if (empty) {
        empty.remove();
      }
      rows.forEach(function (r) {
        var li = el('li', 'pr-row');
        var main = el('div', 'pr-main');
        var line = el('p', 'pr-line');
        line.appendChild(el('span', 'pr-type', r.is + ':'));
        line.appendChild(el('span', 'pr-who' + (r.other && r.other.me ? ' is-me' : ''), r.other ? r.other.name : ''));
        main.appendChild(line);
        var other = r.other && r.other.me ? 'your' : ((r.other && r.other.name) || 'their') + '’s';
        if (r.other_is && r.other_is.toLowerCase() !== String(r.is).toLowerCase()) {
          main.appendChild(el('p', 'pr-meta', 'On ' + other + ' card: ' + r.other_is));
        } else if (r.other && r.other.organisation) {
          main.appendChild(el('p', 'pr-meta', r.other.organisation));
        }
        li.appendChild(main);
        if (editable) {
          var acts = el('div', 'pr-acts');
          var ch = button('pr-btn', 'Change', 'Change ' + r.is + ' ' + (r.other ? r.other.name : ''));
          ch.addEventListener('click', function () { openForm(r); });
          var rm = button('pr-btn is-quiet', 'Remove', 'Remove ' + r.is + ' ' + (r.other ? r.other.name : ''));
          rm.addEventListener('click', function () {
            var back = { action: 'add', other: r.other.id, type: r.is, other_type: r.other_is };
            send({ action: 'remove', id: r.id }, 'Removed ' + r.is + ': ' + r.other.name + ' from both cards.',
              function () { send(back, 'Put back.'); });
          });
          acts.appendChild(ch);
          acts.appendChild(rm);
          li.appendChild(acts);
        }
        ul.appendChild(li);
      });
    }

    /* The form, for a new link (row null) or for the words of one there is. */
    function openForm(row) {
      if (busy) return;
      editing = row ? row.id : 0;
      tell('');
      if (addBtn) addBtn.hidden = true;
      draw();
      formSlot.textContent = '';
      var form = el('form', 'pr-form');
      form.noValidate = true;
      form.setAttribute('aria-label', row ? 'Change the relationship' : 'Add a relationship');
      var n = ++uid;
      var picked = row ? { id: row.other.id, name: row.other.name, me: row.other.me } : null;

      // Who: a contact found by name, or You.
      var whoField = el('div', 'pr-field');
      var whoLabel = el('label', 'pr-label', 'Who');
      whoLabel.htmlFor = 'prQ' + n;
      whoField.appendChild(whoLabel);
      var chosen = el('div', 'pr-chosen');
      var search = el('input', 'pr-input');
      search.id = 'prQ' + n;
      search.type = 'search';
      search.autocomplete = 'off';
      search.placeholder = 'A name or company';
      var found = el('ul', 'pr-found');
      found.id = 'prF' + n;
      found.setAttribute('aria-label', 'Contacts to link to');
      whoField.appendChild(chosen);
      whoField.appendChild(search);
      whoField.appendChild(found);
      form.appendChild(whoField);

      // What this contact is to them.
      var typeField = el('div', 'pr-field');
      var typeLabel = el('label', 'pr-label');
      typeLabel.htmlFor = 'prS' + n;
      typeField.appendChild(typeLabel);
      var select = el('select', 'pr-input pr-select');
      select.id = 'prS' + n;
      var own = (data.types || []).filter(function (t) { return t.own; });
      var common = (data.types || []).filter(function (t) { return !t.own; });
      var inverses = {};
      function group(label, items) {
        if (!items.length) return;
        var g = el('optgroup');
        g.label = label;
        items.forEach(function (t) {
          var o = el('option', null, t.label);
          o.value = t.label;
          inverses[t.label.toLowerCase()] = t.inverse || t.label;
          g.appendChild(o);
        });
        select.appendChild(g);
      }
      var first = el('option', null, 'Pick a type');
      first.value = '';
      select.appendChild(first);
      group('Your own types', own);
      group('Common types', common);
      var typeNew = el('option', null, 'A new type…');
      typeNew.value = NEW;
      select.appendChild(typeNew);
      typeField.appendChild(select);
      var custom = el('input', 'pr-input');
      custom.id = 'prC' + n;
      custom.type = 'text';
      custom.maxLength = 60;
      custom.placeholder = 'Such as Tennis buddy of';
      custom.setAttribute('aria-label', 'The new type');
      custom.hidden = true;
      typeField.appendChild(custom);
      form.appendChild(typeField);

      // What they are to this contact.
      var invField = el('div', 'pr-field');
      var invLabel = el('label', 'pr-label');
      invLabel.htmlFor = 'prI' + n;
      invField.appendChild(invLabel);
      var inverse = el('input', 'pr-input');
      inverse.id = 'prI' + n;
      inverse.type = 'text';
      inverse.maxLength = 60;
      invField.appendChild(inverse);
      var invHint = el('p', 'pr-hint', 'Filled in from the type. Change it when their side reads differently.');
      invField.appendChild(invHint);
      form.appendChild(invField);
      var invTouched = false;
      inverse.addEventListener('input', function () { invTouched = true; });

      var actions = el('div', 'pr-edit-row');
      var save = el('button', 'pr-save', row ? 'Save' : 'Add');
      save.type = 'submit';
      var cancel = button('pr-cancel', 'Cancel');
      actions.appendChild(save);
      actions.appendChild(cancel);
      form.appendChild(actions);
      var formSaid = el('p', 'pr-said is-bad');
      formSaid.hidden = true;
      formSaid.setAttribute('role', 'alert');
      form.appendChild(formSaid);

      function typeNow() {
        return select.value === NEW ? custom.value.trim() : select.value;
      }
      function names() {
        var other = picked ? (picked.me ? 'you' : picked.name) : 'them';
        typeLabel.textContent = me ? 'You are' : mine + ' is';
        var to = me ? 'you' : mine;
        invLabel.textContent = picked ? (picked.me ? 'You are' : picked.name + ' is') + ' to ' + to
          : 'They are to ' + to;
        custom.setAttribute('aria-label', (me ? 'What you are to ' : 'What ' + mine + ' is to ') + other + ', in your words');
      }
      function fillInverse() {
        if (invTouched) return;
        var t = typeNow();
        inverse.value = t ? (inverses[t.toLowerCase()] || t) : '';
      }
      function showPicked() {
        chosen.textContent = '';
        if (!picked) {
          chosen.hidden = true;
          search.hidden = false;
          found.hidden = false;
          return;
        }
        chosen.hidden = false;
        search.hidden = true;
        found.hidden = true;
        chosen.appendChild(el('span', 'pr-chosen-name', picked.me ? 'You' : picked.name));
        if (!row) {
          var again = button('pr-link', 'Pick somebody else');
          again.addEventListener('click', function () {
            picked = null;
            showPicked();
            names();
            search.focus();
          });
          chosen.appendChild(again);
        }
      }
      function choose(p) {
        picked = p;
        showPicked();
        names();
        select.focus();
      }
      function option(p, sub) {
        var li = el('li');
        var b = button('pr-pick');
        b.appendChild(el('span', 'pr-pick-name', p.me ? 'You' : p.name));
        if (sub) b.appendChild(el('span', 'pr-pick-sub', sub));
        b.addEventListener('click', function () { choose(p); });
        li.appendChild(b);
        return li;
      }
      var asked = 0;
      function lookUp() {
        var q = search.value.trim();
        var mark = ++asked;
        found.textContent = '';
        if (!me) found.appendChild(option({ id: 'me', name: 'You', me: true }, 'Yourself'));
        if (!q) return;
        call(base() + '/find?q=' + encodeURIComponent(q), null).then(function (j) {
          if (mark !== asked) return;
          var people = j.people || [];
          people.forEach(function (p) { found.appendChild(option(p, p.organisation || '')); });
          if (!people.length) found.appendChild(el('li', 'pr-none', 'No contact matches “' + q + '”.'));
        }).catch(function (e) {
          if (mark === asked) found.appendChild(el('li', 'pr-none', (e && e.message) || 'Contacts could not be read.'));
        });
      }
      var timer = 0;
      search.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(lookUp, 180);
      });
      select.addEventListener('change', function () {
        custom.hidden = select.value !== NEW;
        if (!custom.hidden) custom.focus();
        fillInverse();
      });
      custom.addEventListener('input', fillInverse);

      if (row) {
        var known = Array.prototype.some.call(select.options, function (o) { return o.value === row.is; });
        if (known) {
          select.value = row.is;
        } else {
          select.value = NEW;
          custom.hidden = false;
          custom.value = row.is;
        }
        inverse.value = row.other_is || row.is;
        invTouched = (inverses[String(row.is).toLowerCase()] || row.is) !== inverse.value;
      }
      names();
      showPicked();
      lookUp();

      cancel.addEventListener('click', function () {
        editing = null;
        formSlot.textContent = '';
        if (addBtn) { addBtn.hidden = false; addBtn.focus(); }
        draw();
      });
      form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var t = typeNow();
        formSaid.hidden = true;
        if (!picked) { formSaid.textContent = 'Pick who it is with.'; formSaid.hidden = false; search.focus(); return; }
        if (!t) { formSaid.textContent = 'Pick a type, or type your own.'; formSaid.hidden = false; select.focus(); return; }
        var whom = picked.me ? 'you' : picked.name;
        if (row) {
          send({ action: 'change', id: row.id, type: t, other_type: inverse.value.trim() },
            'Changed: ' + t + ': ' + whom + '.');
        } else {
          send({ action: 'add', other: picked.id, type: t, other_type: inverse.value.trim() },
            'Added ' + t + ': ' + whom + '. It shows on ' + (picked.me ? 'your' : whom + '’s') + ' card too.');
        }
      });
      formSlot.appendChild(form);
      if (row) select.focus(); else search.focus();
    }

    draw();
    // What it was drawn with may be older than what is kept: read it once, and draw again if it differs.
    if (data.person) {
      call(base(), null).then(function (j) {
        if (busy || editing !== null) return;
        if (JSON.stringify(j.rows) !== JSON.stringify(data.rows) || JSON.stringify(j.types) !== JSON.stringify(data.types)) {
          data = j;
          draw();
        }
      }).catch(function () { /* the card keeps what it was drawn with */ });
    }
    return box;
  }

  window.RouhRelations = { list: list };
})();
