/* The Shipping page, at /settings/shipping (`rouh/shipping.py`, `rouh/web/shipping.py`).

   Petar, 14 October 2026: "I want to be able to define shipping options and
   addresses with priority depending on what the vendor allows ... sometimes it
   is a box, sometimes a speedy office, sometimes I have to provide address. I
   have preferences for each situation ... I need to be able to line up options
   in favorite order." And: "I need to be able to define logistics company, type
   of place, and specific address."

   So the page is three cards:

   - Shipping options, the main order: each option is a row with a handle to
     drag it by (or the arrow keys on the handle), its place in the list, its
     name, its three parts (the courier, the kind of place, the place itself),
     Move up and Move down, an on/off switch, Edit and Delete. The list ends
     with "Then: ask me", which is what Rouh does when nothing fits. Add option
     opens a form in three parts kept apart: 1 the logistics company, typed or
     picked from the suggestions; 2 the type of place, a locker or box, an
     office, or a door address; 3 the specific place, which asks for a code and
     a name for a locker or an office, and a street, entrance, floor, apartment
     and door code for a door. Then the recipient, empty for your own, and
     notes for the courier.
   - Situations: Default, which is the main order, and any named ones ("Big or
     heavy", "Abroad"), each its own list of the saved options, ordered the
     same two ways, with options added to it and taken out of it.
   - The recipient: whose name and phone a parcel carries unless an option
     says otherwise, starting as the profile's name and the contact card's
     phone.

   What is wrong with a form sent is said under each field it is wrong in, as
   on the Payments page. A group of Settings, drawn into `#shippingBody` from
   `/api/shipping`; Settings tells it when it shows and when it is left
   (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  /* form: the option being edited, by id, 'new' for one being added, or ''.
     draft: what was typed into that form, kept across a refusal.
     sit: the situation being renamed, by id, or ''. wrong: what the server said
     is wrong in the form last sent, { form, errs }. focus: what to focus once
     the page is drawn again, by its data-keep. */
  var S = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: '', form: '',
            draft: null, formError: '', sit: '', wrong: { form: '', errs: {} }, focus: '', drag: null };

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
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }

  function call(method, url, body, form) {
    var seq = ++S.seq;
    if (method === 'POST') S.busy = true;
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = false;
          if (seq !== S.seq && method === 'GET') return j;
          if (j && j.options) S.data = j;
          var errs = !r.ok && j && j.fields && typeof j.fields === 'object' ? j.fields : null;
          if (method === 'POST') S.wrong = { form: errs ? form || '' : '', errs: errs || {} };
          if (r.ok) {
            S.error = '';
            if (j && j.said) S.said = j.said;
            S.editing = '';
          } else if (errs && form) {
            S.error = '';
          } else {
            S.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          if (errs && form) focusWrong(form);
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') { S.busy = false; S.wrong = { form: '', errs: {} }; }
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/shipping'); }
  function post(url, body, form) { S.said = ''; return call('POST', url, body, form); }

  /* ---- drawing ---- */

  function draw() {
    var body = $('shippingBody');
    if (!body || !S.open || S.drag) return;
    var d = S.data;
    if (S.editing && d) {
      // Something is being typed: only the line that says how it went changes.
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = S.error || S.said;
        say.className = 'hb-say' + (S.error ? ' bad' : '');
        say.hidden = !(S.error || S.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.error || S.said);
    say2.setAttribute('role', 'status');
    say2.hidden = !(S.error || S.said);
    page.appendChild(say2);
    if (!d) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading your shipping options…'));
      return;
    }
    page.appendChild(optionsCard(d));
    page.appendChild(situationsCard(d));
    page.appendChild(recipientCard(d));
    if (S.focus) {
      var again = /** @type {HTMLButtonElement|null} */ (body.querySelector('[data-keep="' + S.focus + '"]'));
      S.focus = '';
      // Moved to the top or the bottom, its own button is off: the row's handle has the focus.
      if (again && again.disabled) {
        var row = again.closest('.ship-item');
        again = row ? /** @type {HTMLButtonElement|null} */ (row.querySelector('.ship-grip')) : null;
      }
      if (again) again.focus();
    }
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  function field(text, type, value, id, opts) {
    opts = opts || {};
    var label = el('label', 'hb-field' + (opts.cls ? ' ' + opts.cls : ''));
    var words = el('span', '', text);
    label.appendChild(words);
    var input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') /** @type {HTMLInputElement} */ (input).type = type;
    else /** @type {HTMLTextAreaElement} */ (input).rows = 2;
    input.id = id;
    input.value = value == null ? '' : String(value);
    input.setAttribute('autocomplete', opts.auto || 'off');
    if (opts.mode) input.setAttribute('inputmode', opts.mode);
    if (opts.max) input.maxLength = opts.max;
    if (opts.place) input.placeholder = opts.place;
    if (opts.list) input.setAttribute('list', opts.list);
    input.spellcheck = false;
    label.appendChild(input);
    if (opts.help) {
      var help = el('span', 'settings-help hb-field-help', opts.help);
      help.id = id + 'Help';
      input.setAttribute('aria-describedby', help.id);
      label.appendChild(help);
    }
    return { label: label, input: input, words: words };
  }

  /* Under each field of `form` the server said is wrong, what is wrong with it; changing
     the field takes it away. */
  function markWrong(form, map) {
    var errs = S.wrong.form === form ? S.wrong.errs : {};
    Object.keys(map).forEach(function (name) {
      var f = map[name];
      var said = errs[name];
      if (!said || !f) return;
      var box = el('span', 'ship-field-error', said);
      box.id = f.input.id + 'Error';
      f.label.insertBefore(box, f.input.nextSibling);
      f.label.classList.add('wrong');
      f.input.setAttribute('aria-invalid', 'true');
      var described = f.input.getAttribute('aria-describedby');
      f.input.setAttribute('aria-describedby', box.id + (described ? ' ' + described : ''));
      function right() {
        if (!box.parentNode) return;
        box.remove();
        f.label.classList.remove('wrong');
        f.input.removeAttribute('aria-invalid');
        if (described) f.input.setAttribute('aria-describedby', described);
        else f.input.removeAttribute('aria-describedby');
        delete errs[name];
      }
      f.input.addEventListener('input', right);
      f.input.addEventListener('change', right);
    });
  }

  function focusWrong(form) {
    var first = document.querySelector('#shippingBody [data-form="' + form + '"] [aria-invalid="true"]');
    if (!first) return false;
    /** @type {HTMLElement} */ (first).focus({ preventScroll: true });
    first.scrollIntoView({ block: 'center' });
    return true;
  }

  function editing(f, name) {
    f.addEventListener('input', function () { S.editing = name; });
    f.addEventListener('focusin', function () { S.editing = name; });
  }

  function optionById(d, id) {
    for (var i = 0; i < d.options.length; i++) if (d.options[i].id === id) return d.options[i];
    return null;
  }

  /* The place itself, in a few words: "BG-1234 “Example Mall”" or "10 Example Street, Lisbon". */
  function placeWords(o) {
    var a = o.address || {};
    if (o.kind === 'locker' || o.kind === 'office') {
      var named = [o.place_code, o.place_name ? '“' + o.place_name + '”' : ''].filter(Boolean).join(' ');
      return [named, a.city].filter(Boolean).join(', ');
    }
    var more = [a.entrance ? 'entr. ' + a.entrance : '', a.floor ? 'fl. ' + a.floor : '',
                a.apartment ? 'apt ' + a.apartment : ''].filter(Boolean).join(' ');
    return [a.line1, more, a.city].filter(Boolean).join(', ');
  }

  var KIND_ICONS = {
    locker: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M4 9.5h16M4 15h16M12 3.5v17"/>',
    office: '<path d="M3.5 10.5 12 4l8.5 6.5"/><path d="M5.5 9v11h13V9"/><path d="M10 20v-5.5h4V20"/>',
    address: '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>'
  };
  function kindIcon(kind) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'ship-kind-icon');
    svg.innerHTML = KIND_ICONS[kind] || '';
    return svg;
  }

  function arrow(up) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + (up ? 'M12 19V5M6 11l6-6 6 6' : 'M12 5v14M6 13l6 6 6-6') + '"/></svg>';
  }

  /* A list in its order, the main one or a situation's: each option with a handle, its
     place, its words and what can be done to it there, and "Then: ask me" at the end. */
  function orderList(d, sit, ids) {
    var ol = el('ol', 'ship-list');
    ol.setAttribute('data-situation', String(sit.id));
    ol.setAttribute('aria-label', sit.default ? 'Your shipping options, in order' : sit.name + ', in order');
    ids.forEach(function (id, i) {
      var o = optionById(d, id);
      if (!o) return;
      if (sit.default && S.form === o.id) {
        var edit = el('li', 'ship-item ship-editing');
        edit.appendChild(optionForm(d, o));
        ol.appendChild(edit);
        return;
      }
      ol.appendChild(item(d, sit, o, i, ids.length));
    });
    var ask = el('li', 'ship-ask');
    ask.appendChild(el('span', 'ship-rank', String(ids.length + 1)));
    var words = el('span', 'ship-ask-words', 'Then: ask me');
    ask.appendChild(words);
    ask.appendChild(el('span', 'ship-ask-help', ids.length ? 'when nothing above is offered' : 'always, until something is in this list'));
    ol.appendChild(ask);
    return ol;
  }

  function item(d, sit, o, i, n) {
    var li = el('li', 'ship-item' + (o.active ? '' : ' off'));
    li.setAttribute('data-id', String(o.id));
    var key = sit.id + '-' + o.id;
    var grip = el('button', 'ship-grip');
    grip.type = 'button';
    grip.setAttribute('data-keep', 'grip-' + key);
    grip.setAttribute('aria-label', 'Reorder ' + o.label + ', number ' + (i + 1) + ' of ' + n +
                      '. Drag it, or press the up and down arrow keys');
    grip.title = 'Drag to reorder, or use the arrow keys';
    grip.innerHTML = '<svg viewBox="0 0 12 16" aria-hidden="true"><circle cx="3" cy="3" r="1.3"/>' +
      '<circle cx="9" cy="3" r="1.3"/><circle cx="3" cy="8" r="1.3"/><circle cx="9" cy="8" r="1.3"/>' +
      '<circle cx="3" cy="13" r="1.3"/><circle cx="9" cy="13" r="1.3"/></svg>';
    grip.addEventListener('pointerdown', function (e) { dragStart(e, sit, o, li); });
    grip.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      moveBy(sit, o, e.key === 'ArrowUp' ? -1 : 1, 'grip-' + key);
    });
    li.appendChild(grip);
    li.appendChild(el('span', 'ship-rank', String(i + 1)));
    var main = el('div', 'ship-main');
    var top = el('div', 'ship-top');
    top.appendChild(el('span', 'ship-name', o.label));
    if (!o.active) top.appendChild(el('span', 'ship-off', 'Off'));
    main.appendChild(top);
    var parts = el('div', 'ship-parts');
    var co = el('span', 'ship-part ship-co' + (o.any ? ' any' : ''), o.company);
    parts.appendChild(co);
    var kind = el('span', 'ship-part ship-kind');
    kind.appendChild(kindIcon(o.kind));
    kind.appendChild(document.createTextNode(o.kind_name));
    parts.appendChild(kind);
    var place = placeWords(o);
    if (place) parts.appendChild(el('span', 'ship-part ship-place', place));
    main.appendChild(parts);
    if (sit.default && (o.recipient_name || o.recipient_phone || o.notes)) {
      main.appendChild(el('div', 'ship-extra', [o.recipient_name || o.recipient_phone ?
        'For ' + [o.recipient_name, o.recipient_phone].filter(Boolean).join(', ') : '',
        o.notes ? 'Notes: ' + o.notes : ''].filter(Boolean).join(' · ')));
    }
    li.appendChild(main);
    var acts = el('div', 'ship-acts');
    var up = button('', 'ship-move', function () { moveBy(sit, o, -1, 'up-' + key); });
    up.innerHTML = arrow(true);
    up.setAttribute('aria-label', 'Move ' + o.label + ' up');
    up.setAttribute('data-keep', 'up-' + key);
    up.title = 'Move up';
    up.disabled = i === 0;
    var down = button('', 'ship-move', function () { moveBy(sit, o, 1, 'down-' + key); });
    down.innerHTML = arrow(false);
    down.setAttribute('aria-label', 'Move ' + o.label + ' down');
    down.setAttribute('data-keep', 'down-' + key);
    down.title = 'Move down';
    down.disabled = i === n - 1;
    acts.appendChild(up);
    acts.appendChild(down);
    if (sit.default) {
      var sw = el('button', 'ship-toggle');
      sw.type = 'button';
      sw.setAttribute('role', 'switch');
      sw.setAttribute('aria-checked', o.active ? 'true' : 'false');
      sw.setAttribute('aria-label', o.label + ' is ' + (o.active ? 'on' : 'off'));
      sw.title = o.active ? 'On: Rouh may pick it. Press to switch it off' : 'Off: Rouh skips it. Press to switch it on';
      sw.setAttribute('data-keep', 'sw-' + o.id);
      sw.appendChild(el('span', 'ship-knob'));
      sw.appendChild(el('span', 'ship-toggle-word', o.active ? 'On' : 'Off'));
      sw.addEventListener('click', function () {
        sw.disabled = true;
        S.focus = 'sw-' + o.id;
        post('/api/shipping/option/active', { id: o.id, active: !o.active });
      });
      acts.appendChild(sw);
      var ed = button('Edit', '', function () {
        S.form = o.id;
        S.draft = null;
        S.formError = '';
        S.wrong = { form: '', errs: {} };
        draw();
        var first = $('shipLabel');
        if (first) first.focus();
      });
      ed.setAttribute('aria-label', 'Edit ' + o.label);
      acts.appendChild(ed);
      var del = button('Delete', 'danger', function () {
        if (!window.confirm('Delete ' + o.label + '? It goes from every situation too.')) return;
        post('/api/shipping/option/delete', { id: o.id });
      });
      del.setAttribute('aria-label', 'Delete ' + o.label);
      acts.appendChild(del);
    } else {
      var out = button('Remove', '', function () {
        post('/api/shipping/order', { situation: sit.id, order: sit.options.filter(function (x) { return x !== o.id; }) });
      }, 'Take it out of ' + sit.name + '; it stays in your options');
      out.setAttribute('aria-label', 'Remove ' + o.label + ' from ' + sit.name);
      acts.appendChild(out);
    }
    li.appendChild(acts);
    return li;
  }

  /* One step up or down, drawn at once and then saved; the server's answer is drawn after. */
  function moveBy(sit, o, by, keep) {
    if (S.busy) return;
    var ids = sit.options.slice();
    var at = ids.indexOf(o.id), to = at + by;
    if (at < 0 || to < 0 || to >= ids.length) return;
    ids.splice(at, 1);
    ids.splice(to, 0, o.id);
    S.focus = keep;
    setOrder(sit, ids);
  }

  function setOrder(sit, ids) {
    sit.options = ids;
    if (sit.default) {
      var by = {};
      S.data.options.forEach(function (x) { by[x.id] = x; });
      S.data.options = ids.map(function (id) { return by[id]; }).filter(Boolean);
    }
    var keep = S.focus;
    draw();
    S.focus = keep;
    post('/api/shipping/order', { situation: sit.id, order: ids });
  }

  /* Dragging by the handle, with the pointer - a mouse, a pen or a finger - rather than the
     browser's own drag and drop, which a finger cannot do. A line shows where it will go;
     letting go there moves it, and letting go anywhere else, or Escape, puts it back. */
  function dragStart(e, sit, o, li) {
    if (S.busy || S.form || (e.button != null && e.button !== 0)) return;
    e.preventDefault();
    var grip = /** @type {HTMLElement} */ (e.currentTarget);
    try { grip.setPointerCapture(e.pointerId); } catch (err) { /* a pointer that is gone */ }
    var list = /** @type {HTMLElement} */ (li.parentNode);
    var box = li.getBoundingClientRect();
    var ghost = el('div', 'ship-ghost', o.label);
    ghost.style.width = Math.min(box.width, 320) + 'px';
    document.body.appendChild(ghost);
    var line = el('li', 'ship-drop');
    line.setAttribute('aria-hidden', 'true');
    S.drag = { sit: sit, id: o.id, li: li, list: list, ghost: ghost, line: line, dy: e.clientY - box.top,
               x0: e.clientX, y0: e.clientY, moved: false, to: -1 };
    li.classList.add('dragging');
    place(e);

    function moveTo(ev) { place(ev); }
    function end(ev) {
      grip.removeEventListener('pointermove', moveTo);
      grip.removeEventListener('pointerup', end);
      grip.removeEventListener('pointercancel', cancel);
      document.removeEventListener('keydown', esc, true);
      var d = S.drag;
      S.drag = null;
      finish(d, !!ev && ev.type === 'pointerup');
    }
    function cancel() { end(null); }
    function esc(ev) {
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); end(null); }
    }
    grip.addEventListener('pointermove', moveTo);
    grip.addEventListener('pointerup', end);
    grip.addEventListener('pointercancel', cancel);
    document.addEventListener('keydown', esc, true);
  }

  function place(e) {
    var d = S.drag;
    if (!d) return;
    d.ghost.style.left = Math.max(8, Math.min(e.clientX - 24, window.innerWidth - 120)) + 'px';
    d.ghost.style.top = (e.clientY - 14) + 'px';
    if (Math.abs(e.clientX - d.x0) + Math.abs(e.clientY - d.y0) > 4) d.moved = true;
    var rows = Array.prototype.slice.call(d.list.querySelectorAll(':scope > .ship-item[data-id]'));
    var index = rows.length;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { index = i; break; }
    }
    var first = rows[0] && rows[0].getBoundingClientRect();
    var last = rows.length && rows[rows.length - 1].getBoundingClientRect();
    // Too far from the list puts it back where it was.
    var off = !first || e.clientY < first.top - 60 || e.clientY > last.bottom + 60;
    if (d.line.parentNode) d.line.parentNode.removeChild(d.line);
    d.to = off ? -1 : index;
    if (!off) d.list.insertBefore(d.line, rows[index] || d.list.querySelector(':scope > .ship-ask'));
    var edge = 48;
    if (e.clientY > window.innerHeight - edge) window.scrollBy(0, 12);
    else if (e.clientY < edge) window.scrollBy(0, -12);
  }

  function finish(d, dropped) {
    if (!d) return;
    if (d.ghost.parentNode) d.ghost.parentNode.removeChild(d.ghost);
    if (d.line.parentNode) d.line.parentNode.removeChild(d.line);
    d.li.classList.remove('dragging');
    if (!dropped || !d.moved || d.to < 0) return;
    var ids = d.sit.options.slice();
    var at = ids.indexOf(d.id);
    if (at < 0 || d.to === at || d.to === at + 1) return;
    ids.splice(at, 1);
    ids.splice(d.to > at ? d.to - 1 : d.to, 0, d.id);
    S.focus = 'grip-' + d.sit.id + '-' + d.id;
    setOrder(d.sit, ids);
  }

  /* ---- the options ---- */

  function optionsCard(d) {
    var main = d.situations[0];
    var s = card('Shipping options', d.options.length ? String(d.options.length) : '', 'ship-options');
    var help = el('p', 'settings-help', 'At a checkout Rouh goes down this list, takes the first option the seller ' +
      'offers, fills it in and tells you which and why. It presses the button that orders only for an order you asked for, and only when the address on the page is one of these. ');
    if (d.silo) {
      help.appendChild(document.createTextNode('Kept in your '));
      help.appendChild(siloChip(d.silo));
      help.appendChild(document.createTextNode(' silo, as private contact detail.'));
    }
    s.appendChild(help);
    if (!d.options.length && S.form !== 'new') {
      s.appendChild(el('p', 'hb-empty', 'Nothing saved yet, so Rouh asks you every time. Add the way you like ' +
        'parcels best first: a locker, an office or your door.'));
    }
    if (d.options.length) s.appendChild(orderList(d, main, main.options));
    if (S.form === 'new') {
      s.appendChild(optionForm(d, null));
    } else {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Add option', d.options.length ? '' : 'primary', function () {
        S.form = 'new';
        S.draft = null;
        S.formError = '';
        S.wrong = { form: '', errs: {} };
        draw();
        var first = $('shipLabel');
        if (first) first.focus();
      }));
      s.appendChild(acts);
    }
    return s;
  }

  function siloChip(c) {
    var chip = el('span', 'silo-chip ship-silo');
    if (/^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
    chip.appendChild(el('span', 'silo-dot'));
    chip.appendChild(el('span', 'silo-name', c.name || ''));
    return chip;
  }

  var PLACE_WORDS = {
    locker: { code: 'Locker code', name: 'Locker name', street: 'Street (optional)',
              help: 'As the courier lists it, such as its number on the courier’s map.' },
    office: { code: 'Office code', name: 'Office name', street: 'Street (optional)',
              help: 'As the courier lists it, such as the office’s number or its name on the courier’s site.' },
    address: { street: 'Street and number' }
  };

  /* An option typed in, new or changed, in its three parts. Nothing in it is secret, so a
     refused save keeps all of it. */
  function optionForm(d, o) {
    var f = el('form', 'hb-form ship-form');
    f.setAttribute('data-form', 'option');
    f.noValidate = true;
    f.setAttribute('aria-label', o ? 'Edit ' + o.label : 'Add a shipping option');
    f.setAttribute('autocomplete', 'off');
    editing(f, 'option');
    f.appendChild(el('h5', 'hb-h5', o ? 'Edit ' + o.label : 'New shipping option'));
    var v = S.draft || (o ? { label: o.label, company: o.company, kind: o.kind, place_code: o.place_code,
                              place_name: o.place_name, address: o.address || {}, recipient_name: o.recipient_name,
                              recipient_phone: o.recipient_phone, notes: o.notes }
                            : { kind: '', address: { country: 'BG' } });
    var a = v.address || {};
    var label = field('Name', 'text', v.label, 'shipLabel', {
      max: 80, cls: 'wide', place: 'Speedy locker near home', help: 'What you and Rouh call it.' });
    f.appendChild(label.label);

    // 1. The logistics company.
    var p1 = part('1', 'Logistics company');
    var list = el('datalist');
    list.id = 'shipCompanies';
    d.companies.forEach(function (c) { list.appendChild(new Option(c, c)); });
    p1.appendChild(list);
    var company = field('Company', 'text', v.company, 'shipCompany', {
      max: 60, cls: 'wide', list: 'shipCompanies', place: 'Speedy, Econt, BOX NOW…',
      help: 'Any courier fits whichever the seller offers.' });
    p1.appendChild(company.label);
    var picks = el('div', 'ship-picks');
    picks.setAttribute('aria-label', 'Suggestions');
    d.companies.forEach(function (c) {
      var b = button(c, 'ship-pick', function () {
        company.input.value = c;
        company.input.dispatchEvent(new Event('input', { bubbles: true }));
        mark();
      });
      picks.appendChild(b);
    });
    function mark() {
      Array.prototype.forEach.call(picks.children, function (b) {
        b.setAttribute('aria-pressed', b.textContent.toLowerCase() === company.input.value.trim().toLowerCase() ? 'true' : 'false');
      });
    }
    company.input.addEventListener('input', mark);
    mark();
    p1.appendChild(picks);
    f.appendChild(p1);

    // 2. The type of place.
    var p2 = part('2', 'Type of place');
    var kinds = el('div', 'ship-kinds');
    kinds.setAttribute('role', 'radiogroup');
    kinds.setAttribute('aria-label', 'Type of place');
    kinds.id = 'shipKind';
    var radios = {};
    d.kinds.forEach(function (k) {
      var lab = el('label', 'ship-kind-pick');
      var r = /** @type {HTMLInputElement} */ (el('input'));
      r.type = 'radio';
      r.name = 'shipKind';
      r.value = k.key;
      r.checked = v.kind === k.key;
      r.addEventListener('change', shape);
      radios[k.key] = r;
      lab.appendChild(r);
      lab.appendChild(kindIcon(k.key));
      lab.appendChild(el('span', '', k.name));
      kinds.appendChild(lab);
    });
    p2.appendChild(kinds);
    // A refusal for the kind is said under the group, as for a field.
    var kindField = { label: p2, input: kinds };
    f.appendChild(p2);

    // 3. The specific place.
    var p3 = part('3', 'Specific place');
    var pick = el('p', 'settings-help ship-pick-first', 'Pick the type of place first.');
    p3.appendChild(pick);
    var rPlace = el('div', 'hb-row');
    var code = field('Code', 'text', v.place_code, 'shipCode', { max: 40 });
    var pname = field('Name', 'text', v.place_name, 'shipPlaceName', { max: 120, cls: 'wide' });
    rPlace.appendChild(code.label); rPlace.appendChild(pname.label);
    var placeHelp = el('p', 'settings-help ship-place-help', '');
    var street = field('Street', 'text', a.line1, 'shipStreet', { max: 160, cls: 'wide', place: '10 Example Street' });
    var rDoor = el('div', 'hb-row');
    var entrance = field('Entrance', 'text', a.entrance, 'shipEntrance', { max: 10 });
    var floor = field('Floor', 'text', a.floor, 'shipFloor', { max: 10, mode: 'numeric' });
    var apt = field('Apartment', 'text', a.apartment, 'shipApartment', { max: 10 });
    var door = field('Door code', 'text', a.door_code, 'shipDoorCode', { max: 20 });
    [entrance, floor, apt, door].forEach(function (x) { rDoor.appendChild(x.label); });
    var rCity = el('div', 'hb-row');
    var city = field('City', 'text', a.city, 'shipCity', { max: 80 });
    var zip = field('Postcode', 'text', a.postal_code, 'shipZip', { max: 20 });
    var country = field('Country', 'text', a.country, 'shipCountry', { max: 2, place: 'BG',
                                                                         help: 'Two letters.' });
    [city, zip, country].forEach(function (x) { rCity.appendChild(x.label); });
    [rPlace, placeHelp, street.label, rDoor, rCity].forEach(function (x) { p3.appendChild(x); });
    f.appendChild(p3);

    function shape() {
      var k = Object.keys(radios).filter(function (x) { return radios[x].checked; })[0] || '';
      var w = PLACE_WORDS[k] || {};
      pick.hidden = !!k;
      rPlace.hidden = placeHelp.hidden = !(k === 'locker' || k === 'office');
      street.label.hidden = rCity.hidden = !k;
      rDoor.hidden = k !== 'address';
      code.words.textContent = w.code || 'Code';
      pname.words.textContent = w.name || 'Name';
      street.words.textContent = w.street || 'Street';
      placeHelp.textContent = w.help || '';
      p3.classList.toggle('empty', !k);
    }
    shape();

    // The recipient and notes for the courier.
    var p4 = part('', 'Recipient and notes');
    var own = d.recipient || {};
    var rWho = el('div', 'hb-row');
    var rname = field('Recipient', 'text', v.recipient_name, 'shipRecipient', { max: 120, auto: 'off',
      place: own.name || 'Your name' });
    var rphone = field('Phone', 'tel', v.recipient_phone, 'shipPhone', { max: 40, auto: 'off', mode: 'tel',
      place: own.phone || 'Your phone' });
    rWho.appendChild(rname.label); rWho.appendChild(rphone.label);
    p4.appendChild(rWho);
    p4.appendChild(el('p', 'settings-help', 'Leave them empty for the recipient below' +
      (own.name ? ' (' + [own.name, own.phone].filter(Boolean).join(', ') + ')' : '') + '.'));
    var notes = field('Notes for the courier', 'textarea', v.notes, 'shipNotes', { max: 400, cls: 'wide',
      place: 'Call when outside; the bell does not work.' });
    p4.appendChild(notes.label);
    f.appendChild(p4);

    markWrong('option', { label: label, company: company, kind: kindField, place_code: code, place_name: pname,
                          line1: street, city: city, postal_code: zip, country: country, floor: floor,
                          apartment: apt, entrance: entrance, door_code: door, recipient_name: rname,
                          recipient_phone: rphone, notes: notes });
    if (S.formError) {
      var why = el('p', 'hb-say bad', S.formError);
      why.setAttribute('role', 'alert');
      f.appendChild(why);
    }
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', o ? 'Save' : 'Add option');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () {
      S.form = '';
      S.editing = '';
      S.draft = null;
      S.formError = '';
      S.wrong = { form: '', errs: {} };
      draw();
    }));
    f.appendChild(acts);
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var kind = Object.keys(radios).filter(function (x) { return radios[x].checked; })[0] || '';
      var body = { label: label.input.value, company: company.input.value, kind: kind,
                   place_code: kind === 'address' ? '' : code.input.value,
                   place_name: kind === 'address' ? '' : pname.input.value,
                   address: { line1: street.input.value, city: city.input.value, postal_code: zip.input.value,
                              country: country.input.value.trim().toUpperCase(),
                              entrance: kind === 'address' ? entrance.input.value : '',
                              floor: kind === 'address' ? floor.input.value : '',
                              apartment: kind === 'address' ? apt.input.value : '',
                              door_code: kind === 'address' ? door.input.value : '' },
                   recipient_name: rname.input.value, recipient_phone: rphone.input.value,
                   notes: notes.input.value };
      if (o) body.id = o.id;
      S.editing = '';
      S.draft = body;
      S.formError = '';
      post('/api/shipping/option', body, 'option').then(function (j) {
        if (j && j.ok) {
          S.form = '';
          S.draft = null;
          draw();
        } else if (S.form !== '' && S.error) {
          S.formError = S.error;
          S.error = '';
          draw();
        }
      });
    });
    return f;
  }

  function part(n, title) {
    var fs = el('fieldset', 'ship-part-set');
    var lg = el('legend', 'ship-legend');
    if (n) lg.appendChild(el('span', 'ship-step', n));
    lg.appendChild(document.createTextNode(title));
    fs.appendChild(lg);
    return fs;
  }

  /* ---- situations ---- */

  function situationsCard(d) {
    var named = d.situations.filter(function (x) { return !x.default; });
    var s = card('Situations', named.length ? String(named.length + 1) : '', 'ship-sits');
    s.appendChild(el('p', 'settings-help', 'A situation lines the same options up its own way, such as Big or ' +
      'heavy, or Abroad. Tell Rouh the situation at a checkout; otherwise it uses Default.'));
    var def = el('div', 'ship-sit ship-sit-default');
    var head = el('div', 'ship-sit-head');
    head.appendChild(el('h5', 'ship-sit-name', 'Default'));
    head.appendChild(el('span', 'ship-sit-count', 'the main order above, then ask me'));
    def.appendChild(head);
    s.appendChild(def);
    named.forEach(function (x) { s.appendChild(situationBlock(d, x)); });
    s.appendChild(situationAdd(d));
    return s;
  }

  function situationBlock(d, x) {
    var b = el('div', 'ship-sit');
    b.setAttribute('data-situation', String(x.id));
    var head = el('div', 'ship-sit-head');
    if (S.sit === x.id) {
      head.appendChild(nameForm(d, x));
    } else {
      head.appendChild(el('h5', 'ship-sit-name', x.name));
      head.appendChild(el('span', 'ship-sit-count', x.options.length === 1 ? '1 option' : x.options.length + ' options'));
      var acts = el('div', 'ship-sit-acts');
      var rn = button('Rename', '', function () {
        S.sit = x.id;
        S.wrong = { form: '', errs: {} };
        draw();
        var i = $('shipSitName');
        if (i) i.focus();
      });
      rn.setAttribute('aria-label', 'Rename ' + x.name);
      acts.appendChild(rn);
      var del = button('Delete', 'danger', function () {
        if (!window.confirm('Delete the situation ' + x.name + '? The options in it stay.')) return;
        post('/api/shipping/situation/delete', { id: x.id });
      });
      del.setAttribute('aria-label', 'Delete the situation ' + x.name);
      acts.appendChild(del);
      head.appendChild(acts);
    }
    b.appendChild(head);
    b.appendChild(orderList(d, x, x.options));
    var rest = d.options.filter(function (o) { return x.options.indexOf(o.id) < 0; });
    if (rest.length) {
      var add = el('div', 'ship-sit-add');
      var sel = /** @type {HTMLSelectElement} */ (el('select'));
      sel.id = 'shipSitAdd' + x.id;
      sel.setAttribute('aria-label', 'Option to add to ' + x.name);
      sel.appendChild(new Option('Add an option to this list…', ''));
      rest.forEach(function (o) { sel.appendChild(new Option(o.label, String(o.id))); });
      sel.addEventListener('change', function () {
        if (!sel.value) return;
        post('/api/shipping/order', { situation: x.id, order: x.options.concat([Number(sel.value)]) });
      });
      add.appendChild(sel);
      b.appendChild(add);
    } else if (!d.options.length) {
      b.appendChild(el('p', 'hb-empty', 'Add shipping options above first.'));
    }
    return b;
  }

  function nameForm(d, x) {
    var f = el('form', 'ship-name-form');
    f.setAttribute('data-form', 'situation');
    f.noValidate = true;
    editing(f, 'situation');
    var name = field(x ? 'Name' : 'New situation', 'text', x ? x.name : '', x ? 'shipSitName' : 'shipSitNew',
                     { max: 60, cls: 'wide', place: 'Big or heavy' });
    f.appendChild(name.label);
    markWrong('situation', { name: name });
    var save = el('button', 'ctl small' + (x ? ' primary' : ''), x ? 'Save' : 'Add situation');
    save.type = 'submit';
    f.appendChild(save);
    if (x) {
      f.appendChild(button('Cancel', '', function () {
        S.sit = '';
        S.editing = '';
        S.wrong = { form: '', errs: {} };
        draw();
      }));
    }
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      S.editing = '';
      var body = { name: name.input.value };
      // A new one starts as the main order's options that are on, to be trimmed and reordered.
      if (x) body.id = x.id;
      else body.options = d.options.filter(function (o) { return o.active; }).map(function (o) { return o.id; });
      post('/api/shipping/situation', body, 'situation').then(function (j) {
        if (j && j.ok) { S.sit = ''; draw(); }
      });
    });
    return f;
  }

  function situationAdd(d) {
    var wrap = el('div', 'ship-sit ship-sit-new');
    wrap.appendChild(nameForm(d, null));
    return wrap;
  }

  /* ---- the recipient ---- */

  function recipientCard(d) {
    var r = d.recipient || { set: {}, own: {} };
    var s = card('Recipient', '', 'ship-recipient');
    s.appendChild(el('p', 'settings-help', 'The name and phone a parcel carries unless an option says otherwise. ' +
      'Empty, they are your profile’s name and your contact card’s phone.'));
    var f = el('form', 'hb-form');
    f.setAttribute('data-form', 'recipient');
    f.noValidate = true;
    editing(f, 'recipient');
    var row = el('div', 'hb-row');
    var name = field('Name', 'text', r.set.name, 'shipRecName', { max: 120, place: r.own.name || 'Your name' });
    var phone = field('Phone', 'tel', r.set.phone, 'shipRecPhone', { max: 40, mode: 'tel',
                                                                     place: r.own.phone || '+359 …' });
    row.appendChild(name.label); row.appendChild(phone.label);
    f.appendChild(row);
    markWrong('recipient', { name: name, phone: phone });
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small', 'Save recipient');
    save.type = 'submit';
    acts.appendChild(save);
    f.appendChild(acts);
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      S.editing = '';
      post('/api/shipping/recipient', { name: name.input.value, phone: phone.input.value }, 'recipient');
    });
    s.appendChild(f);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = '';
    S.editing = '';
    draw();
    load();
  }

  function hiddenNow() {
    S.open = false;
    S.editing = '';
    S.form = '';
    S.draft = null;
    S.formError = '';
    S.sit = '';
    S.wrong = { form: '', errs: {} };
  }

  window.RouhShipping = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
