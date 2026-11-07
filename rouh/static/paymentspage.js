/* The Payments page, at /settings/payments (`rouh/payments.py`, `rouh/web/payments.py`).

   Petar, 5 October 2026: "Payments: general, part of the arsenal, in Settings
   at its own address. Rouh's card vault and Stripe key, for any work to use."

   The card vault: the billing entities, each with the cards under it (14
   October 2026, fr_7c47d56e9a95: "we also need company details for the
   invoices- company, vat, and if anything else is filled. We actually need to
   have multiple entities saved. I have two business entities and one personal
   set of cards"). An entity is drawn as its name and how many cards it has,
   then what its invoices carry, only what is filled in, with Edit and Remove;
   then its cards, each drawn only as its brand, its number masked to the last
   four, the name on it and its expiry, with a button to remove it and pickers
   for its silo and its entity; then Add card, which opens a form he types a
   new card into himself, under that entity (14 October 2026, fr_392511bf4c9c:
   "please make the cc digits not display, only the last 4 of the card ... can
   you make multiple cards adding?"). The billing address is the entity's,
   typed once in its own form, not the card's.

   The card form goes to the server once and is sealed there, beside the
   cards already saved. Its number, expiry and code are emptied the moment it
   is sent, whatever the answer, so the digits never sit in the page, and the
   security code is never drawn again anywhere. When it is refused, the rest
   of what was typed (the name, the silo, the entity) is kept and the reason
   is said in the form itself, by the Save card button, so only the card's
   own details have to be typed again. Each card can be for one of the
   account's silos (14 October 2026, fr_3c19cfb75db1: "add also silo to the
   card. different purposes different cards... work for work"): its silo is
   drawn as a chip beside it and picked under it, and a purchase in that silo
   fills it. The spending caps are each card's own (14 October 2026,
   fr_c29d7ddcee31: "Each card needs to have a limit", then "I have a spending
   cap but it needs to be per card"): the most a purchase, a day and a month,
   each optional, drawn under the card with what is spent against the day's and
   the month's so far, or plainly that it has none, and Change caps opening a
   small form in the card itself; a new card's start at the vault's old pair,
   100 dollars a purchase and a day. Then the Stripe restricted key (shown masked,
   with the exact permissions to make it with beside it) and its webhook, and
   what was bought with the card, and billed to whom, and what came in through
   Stripe.

   What is wrong with a form sent is said under each field it is wrong in, the
   field outlined in red, every one at once, and each goes the moment that field
   is changed (13 October 2026, fr_0bcd34587d67: "Errors should be field
   specific"). The server names the fields (`Refused.fields`); a refusal that
   belongs to no one field, or no answer at all, is still said for the whole.
   The browser's own checks are off on these forms (noValidate), so its bubble
   never says a different thing in a different place.

   A group of Settings, drawn into `#paymentsBody` from `/api/payments`.
   Settings tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  /* adding: the id of the entity a card is being typed in under, or ''.
     entity: the id of the entity being edited, 'new' for one being added, or ''.
     capsFor: the id of the card whose caps are being set, or ''; capsDraft what a
     refused save of them kept.
     wrong: what the server said is wrong in the form last sent, by its fields:
     { form: 'entity', 'card', 'caps' or 'stripe', errs: { field: what is wrong } }. */
  var P = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: '', adding: '',
            draft: null, cardError: '', entity: '', entityDraft: null, entityError: '',
            wrong: { form: '', errs: {} }, capsDraft: null, capsFor: '' };

  function host() { return window.RouhHeartbeatHost || {}; }
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
  /* Django's CSRF token, on every write this page makes. csrf.js puts it on all of
     them as well; this page holds a form that matters too much to rest on that alone. */
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }

  function call(method, url, body, form) {
    var seq = ++P.seq;
    if (method === 'POST') P.busy = true;
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') P.busy = false;
          if (seq !== P.seq && method === 'GET') return j;
          if (j && j.cards) P.data = j;
          var errs = !r.ok && j && j.fields && typeof j.fields === 'object' ? j.fields : null;
          if (method === 'POST') P.wrong = { form: errs ? form || '' : '', errs: errs || {} };
          if (r.ok) {
            P.error = '';
            if (j && j.said) P.said = j.said;
            P.editing = '';
          } else if (errs && form) {
            // Said under each field it is wrong in, not over the whole page.
            P.error = '';
          } else {
            P.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          if (errs && form) focusWrong(form);
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') { P.busy = false; P.wrong = { form: '', errs: {} }; }
        P.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function load() { return call('GET', '/api/payments'); }
  /* form: which form's fields a refusal may name ('entity', 'card', 'caps', 'stripe'). */
  function post(url, body, form) { P.said = ''; return call('POST', url, body, form); }

  /* ---- drawing ---- */

  function draw() {
    var body = $('paymentsBody');
    if (!body || !P.open) return;
    var d = P.data;
    if (P.editing && d) {
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = P.error || P.said;
        say.className = 'hb-say' + (P.error ? ' bad' : '');
        say.hidden = !(P.error || P.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (P.error ? ' bad' : ''), P.error || P.said);
    say2.setAttribute('role', 'status');
    say2.hidden = !(P.error || P.said);
    page.appendChild(say2);
    if (!d) {
      if (!P.error) page.appendChild(el('p', 'hb-empty', 'Reading payments…'));
      return;
    }
    page.appendChild(cardCard(d));
    page.appendChild(stripeCard(d));
    page.appendChild(chargesCard(d));
    page.appendChild(moneyInCard(d));
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
    label.appendChild(el('span', '', text));
    var input = el('input');
    input.type = type;
    input.id = id;
    input.value = value == null ? '' : String(value);
    if (opts.auto) input.setAttribute('autocomplete', opts.auto);
    if (opts.mode) input.setAttribute('inputmode', opts.mode);
    if (opts.max) input.maxLength = opts.max;
    if (opts.place) input.placeholder = opts.place;
    input.spellcheck = false;
    label.appendChild(input);
    if (opts.help) {
      var help = el('span', 'settings-help hb-field-help', opts.help);
      help.id = id + 'Help';
      input.setAttribute('aria-describedby', help.id);
      label.appendChild(help);
    }
    return { label: label, input: input };
  }

  /* Under each field of `form` the server said is wrong, what is wrong with it, and the
     field marked; changing the field takes both away. `map` is { name: field() or
     { label, input } }, by the names the server uses. */
  function markWrong(form, map) {
    var errs = P.wrong.form === form ? P.wrong.errs : {};
    Object.keys(map).forEach(function (name) {
      var f = map[name];
      var said = errs[name];
      if (!said) return;
      var box = el('span', 'pay-field-error', said);
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

  /* The first field of `form` marked wrong, focused and brought into view. */
  function focusWrong(form) {
    var first = document.querySelector('#paymentsBody form[data-form="' + form + '"] [aria-invalid="true"]');
    if (!first) return false;
    first.focus({ preventScroll: true });
    first.scrollIntoView({ block: 'center' });
    return true;
  }

  function editing(f, name) {
    f.addEventListener('input', function () { P.editing = name; });
    f.addEventListener('focusin', function () { P.editing = name; });
  }

  /* A silo as app.css's small chip: its colour as a dot and its name (rouh/silos.py). */
  function siloChip(c) {
    var chip = el('span', 'silo-chip pay-silo');
    if (/^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
    chip.setAttribute('data-silo', c.key);
    chip.appendChild(el('span', 'silo-dot'));
    chip.appendChild(el('span', 'silo-name', c.name || ''));
    return chip;
  }

  /* The account's silos as a list to pick one from, or none. */
  function siloSelect(d, value, id, label) {
    var sel = el('select');
    if (id) sel.id = id;
    if (label) sel.setAttribute('aria-label', label);
    sel.appendChild(new Option('No silo', ''));
    (d.silos || []).forEach(function (one) { sel.appendChild(new Option(one.name, one.key)); });
    sel.value = value || '';
    return sel;
  }

  /* A saved card's number as it may be shown: its last four, the rest dots. */
  function masked(last4) { return '\u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 ' + last4; }

  function cardCard(d) {
    var ents = d.entities || [];
    var s = card('Card vault', d.cards.length ? String(d.cards.length) : '', 'pay-card');
    s.appendChild(el('p', 'settings-help', 'Rouh fills a card only into a checkout page open in the live browser, for the plan ' +
      'of a quest or an order you asked for, or into the nightly feature run’s own checkout, up to $100 a night, within the ' +
      'caps of the card it fills, and tells you each time. It never sees the number, the expiry or the ' +
      'code. When you ask it in your own words to order something, it ticks the shop’s required terms and presses the ' +
      'order button itself, once the total on the page is within the card’s caps and close to what it expected, and ' +
      'the delivery address is one of your shipping options. It never types a one-time code or a password to sign in, ' +
      'and 3-D Secure is yours. The one password it fills in is a new account’s, for a sign-up you allowed in Settings, ' +
      'Sign-ups.'));
    s.appendChild(el('p', 'settings-help', 'Each card is kept under the billing entity it pays for. When it is filled in, ' +
      'the checkout gets that entity’s address and whichever of its legal name, VAT number, registration number ' +
      'and invoice email are filled in here, so the invoice is made out to it; a personal entity with none of them ' +
      'leaves them out. The security code is sealed with the card, because a checkout asks for it and nobody is there ' +
      'to type it, and it is never shown again.'));
    if (d.cards.length) {
      s.appendChild(el('p', 'settings-help', 'Each card can be for one silo. A purchase in that silo, for a quest or in a ' +
        'chat of a task or project in it, fills that card; any other fills the ' +
        (d.cards.length > 1 ? 'card marked Default' : 'default') + ', the card for no silo saved last. ' +
        'Name a card by its last four to use it instead.'));
    }
    if (!ents.length && P.entity !== 'new') {
      s.appendChild(el('p', 'hb-empty', 'No billing entity yet. Add one first: the name, company details and address ' +
        'a card’s purchases are billed to, such as a company of yours or Personal.'));
    }
    ents.forEach(function (e) {
      var mine = d.cards.filter(function (c) { return c.entity === e.id; });
      s.appendChild(entityBlock(d, e, mine));
    });
    var loose = d.cards.filter(function (c) { return c.entity == null; });
    if (loose.length) {
      var lost = el('section', 'pay-entity pay-entity-loose');
      lost.setAttribute('aria-label', 'Cards under no billing entity');
      var head = el('div', 'pay-entity-head');
      head.appendChild(el('h5', 'pay-entity-name', 'Under no entity'));
      head.appendChild(el('span', 'pay-entity-count', count(loose.length)));
      lost.appendChild(head);
      lost.appendChild(el('p', 'settings-help', 'Pick the billing entity each of these is for' +
        (ents.length ? '.' : ', once you have added one.')));
      lost.appendChild(cardList(d, loose));
      s.appendChild(lost);
    }
    if (P.entity === 'new') {
      s.appendChild(entityForm(d, null));
    } else {
      var open = el('div', 'hb-actions');
      var addE = button('Add billing entity', ents.length ? '' : 'primary', function () {
        P.entity = 'new';
        P.entityDraft = null;
        P.entityError = '';
        P.wrong = { form: '', errs: {} };
        draw();
        var first = $('payEntLabel');
        if (first) first.focus();
      }, 'A company of yours, or yourself: who a card’s purchases are billed to');
      addE.id = 'payAddEntity';
      open.appendChild(addE);
      s.appendChild(open);
    }
    return s;
  }

  function count(n) { return n + (n === 1 ? ' card' : ' cards'); }

  /* One billing entity: its name and how many cards, what its invoices carry (only
     what is filled in), its cards, and Add card for one more under it. */
  function entityBlock(d, e, mine) {
    var b = el('section', 'pay-entity');
    b.setAttribute('aria-label', e.label + ', ' + count(mine.length));
    b.setAttribute('data-entity', String(e.id));
    if (P.entity === e.id) {
      b.appendChild(entityForm(d, e));
      if (mine.length) b.appendChild(cardList(d, mine));
      return b;
    }
    var head = el('div', 'pay-entity-head');
    var name = el('h5', 'pay-entity-name', e.label);
    head.appendChild(name);
    head.appendChild(el('span', 'pay-entity-count', count(mine.length)));
    var acts = el('div', 'pay-entity-acts');
    var edit = button('Edit', '', function () {
      P.entity = e.id;
      P.entityDraft = null;
      P.entityError = '';
      P.wrong = { form: '', errs: {} };
      draw();
      var first = $('payEntLabel');
      if (first) first.focus();
    }, 'Change what ' + e.label + '’s invoices carry');
    edit.setAttribute('aria-label', 'Edit ' + e.label);
    acts.appendChild(edit);
    var gone = button('Remove', 'danger', function () {
      if (!window.confirm('Remove the billing entity ' + e.label + '?')) return;
      post('/api/payments/entity/delete', { id: e.id });
    }, mine.length ? 'Move or remove its cards first' : 'Take ' + e.label + ' out');
    gone.setAttribute('aria-label', 'Remove ' + e.label);
    acts.appendChild(gone);
    head.appendChild(acts);
    b.appendChild(head);
    var facts = el('dl', 'pay-entity-facts');
    [['company', 'Legal name'], ['vat', 'VAT number'], ['reg_number', 'Registration no.'], ['email', 'Invoice email']]
      .forEach(function (f) {
        if (!e[f[0]]) return;
        facts.appendChild(el('dt', '', f[1]));
        facts.appendChild(el('dd', '', e[f[0]]));
      });
    var a = e.address || {};
    var town = [a.postal_code, a.city].filter(Boolean).join(' ');
    facts.appendChild(el('dt', '', 'Address'));
    facts.appendChild(el('dd', '', [a.line1, a.line2, town, a.state, a.country].filter(Boolean).join(', ')));
    b.appendChild(facts);
    if (mine.length) b.appendChild(cardList(d, mine));
    else b.appendChild(el('p', 'hb-empty', 'No card under it yet.'));
    if (P.adding === e.id) {
      b.appendChild(cardForm(d, e.id));
    } else {
      var more = el('div', 'hb-actions');
      var add = button('Add card', mine.length ? '' : 'primary', function () {
        P.adding = e.id;
        P.draft = null;
        P.cardError = '';
        P.wrong = { form: '', errs: {} };
        draw();
        var first = $('payNumber');
        if (first) first.focus();
      }, 'Type in a new card billed to ' + e.label);
      add.setAttribute('aria-label', 'Add a card to ' + e.label);
      more.appendChild(add);
      b.appendChild(more);
    }
    return b;
  }

  /* An entity's cards, each its brand, masked number, silo, name, expiry, and the
     pickers for its silo and its entity. */
  function cardList(d, cards) {
    var ents = d.entities || [];
    var list = el('ul', 'pay-cards');
    list.setAttribute('aria-label', 'Saved cards');
    cards.forEach(function (c) {
      var li = el('li', 'pay-saved pay-saved-card');
      var top = el('div', 'pay-card-top');
      top.appendChild(el('span', 'pay-brand', c.brand));
      top.appendChild(el('span', 'pay-last4', masked(c.last4)));
      if (c.silo) top.appendChild(siloChip(c.silo));
      if (c.default && d.cards.length > 1) {
        var dflt = el('span', 'pay-in-use', 'Default');
        dflt.title = 'Filled for a purchase in no silo, or in a silo with no card of its own';
        top.appendChild(dflt);
      }
      li.appendChild(top);
      var bits = [];
      if (c.name) bits.push(c.name);
      if (c.expiry) bits.push('expires ' + c.expiry);
      if (c.saved) bits.push('saved ' + c.saved);
      if (bits.length) li.appendChild(el('span', 'pay-when', bits.join(' · ')));
      li.appendChild(P.capsFor === c.id ? capsForm(c) : capsLine(c));
      var picks = el('div', 'pay-picks');
      var pick = el('label', 'pay-silo-pick');
      pick.appendChild(el('span', '', 'Silo'));
      var sel = siloSelect(d, c.silo ? c.silo.key : '', '', 'Silo of the ' + c.brand + ' ending ' + c.last4);
      sel.addEventListener('change', function () {
        post('/api/payments/card/silo', { id: c.id, silo: sel.value });
      });
      pick.appendChild(sel);
      picks.appendChild(pick);
      if (ents.length > 1 || (c.entity == null && ents.length)) {
        var move = el('label', 'pay-silo-pick');
        move.appendChild(el('span', '', 'Billed to'));
        var to = entitySelect(d, c.entity, '', 'Billing entity of the ' + c.brand + ' ending ' + c.last4);
        to.addEventListener('change', function () {
          if (to.value) post('/api/payments/card/entity', { id: c.id, entity: Number(to.value) });
        });
        move.appendChild(to);
        picks.appendChild(move);
      }
      li.appendChild(picks);
      var gone = button('Remove', 'danger', function () {
        if (!window.confirm('Remove the ' + c.brand + ' ending ' + c.last4 + ' from the vault?')) return;
        post('/api/payments/card/delete', { id: c.id });
      }, 'Take the ' + c.brand + ' ending ' + c.last4 + ' out of the vault');
      gone.setAttribute('aria-label', 'Remove the ' + c.brand + ' ending ' + c.last4);
      li.appendChild(gone);
      list.appendChild(li);
    });
    return list;
  }

  function cardNamed(c) { return 'the ' + c.brand + ' ending ' + c.last4; }

  /* A card's three caps as fields side by side, from `v` ({ per_purchase, per_day,
     per_month }, each a number of dollars or empty for none); `id` starts each field's id. */
  function capsFields(v, id) {
    var row = el('div', 'hb-row pay-caps-row');
    var out = { row: row };
    [['per_purchase', 'A purchase ($)', 'Purchase'], ['per_day', 'A day ($)', 'Day'],
     ['per_month', 'A month ($)', 'Month']].forEach(function (c) {
      var f = field(c[1], 'number', v[c[0]], id + c[2], { mode: 'decimal', place: 'No cap' });
      f.input.min = '0'; f.input.step = '0.01';
      row.appendChild(f.label);
      out[c[0]] = f;
    });
    return out;
  }

  /* A card's caps as they are drawn under it: each one set, the day's and the month's
     with what is spent against them so far, or plainly that it has none; and the button
     to change them. */
  function capsLine(c) {
    var k = c.caps || {};
    var parts = [];
    if (k.per_purchase != null) parts.push(['$' + k.per_purchase + ' a purchase', '']);
    if (k.per_day != null) parts.push(['$' + k.per_day + ' a day', '$' + k.spent_day + ' spent today']);
    if (k.per_month != null) parts.push(['$' + k.per_month + ' a month', '$' + k.spent_month + ' spent this month']);
    var line = el('div', 'pay-caps-line' + (parts.length ? '' : ' none'));
    var text = el('span', 'pay-caps-said');
    if (parts.length) {
      text.appendChild(el('span', 'pay-caps-name', 'At most '));
      parts.forEach(function (p, n) {
        if (n) text.appendChild(el('span', 'pay-caps-name', ' · '));
        text.appendChild(el('strong', 'pay-caps-amount', p[0]));
        if (p[1]) text.appendChild(el('span', 'pay-caps-spent', ' (' + p[1] + ')'));
      });
    } else {
      text.textContent = 'No caps set: nothing limits what it is charged';
    }
    line.appendChild(text);
    var change = button(parts.length ? 'Change caps' : 'Set caps', '', function () {
      P.capsFor = c.id;
      P.capsDraft = null;
      P.wrong = { form: '', errs: {} };
      draw();
      var first = $('payCapsPurchase');
      if (first) first.focus();
    }, 'The most ' + cardNamed(c) + ' may be charged in one purchase, a day and a month');
    change.setAttribute('aria-label', 'Change the caps of ' + cardNamed(c));
    line.appendChild(change);
    return line;
  }

  /* A card's caps typed in, in the card itself; an empty field is no cap of that kind. A
     refused save keeps what was typed. */
  function capsForm(c) {
    var f = el('form', 'hb-form pay-caps-form');
    f.setAttribute('data-form', 'caps');
    f.noValidate = true;
    f.setAttribute('aria-label', 'Caps of ' + cardNamed(c));
    f.setAttribute('autocomplete', 'off');
    editing(f, 'caps');
    var v = P.wrong.form === 'caps' && P.capsDraft ? P.capsDraft : (c.caps || {});
    f.appendChild(el('h5', 'hb-h5', 'The most it may be charged'));
    var caps = capsFields(v, 'payCaps');
    f.appendChild(caps.row);
    markWrong('caps', { per_purchase: caps.per_purchase, per_day: caps.per_day, per_month: caps.per_month });
    f.appendChild(el('p', 'settings-help', 'A purchase that would cross one of them is refused before the card is filled, ' +
      'and no other card is used instead. A month is the calendar month. Leave a field empty for no cap of that kind.'));
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save caps');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () {
      P.capsFor = '';
      P.editing = '';
      P.capsDraft = null;
      P.wrong = { form: '', errs: {} };
      draw();
    }));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      P.editing = '';
      P.capsDraft = { per_purchase: caps.per_purchase.input.value, per_day: caps.per_day.input.value,
                      per_month: caps.per_month.input.value };
      var body = { id: c.id, per_purchase: P.capsDraft.per_purchase, per_day: P.capsDraft.per_day,
                   per_month: P.capsDraft.per_month };
      post('/api/payments/card/caps', body, 'caps').then(function (j) {
        if (j && j.ok) {
          P.capsFor = '';
          P.capsDraft = null;
          draw();
        }
      });
    });
    return f;
  }

  /* The account's billing entities as a list to pick one from. */
  function entitySelect(d, value, id, label) {
    var sel = el('select');
    if (id) sel.id = id;
    if (label) sel.setAttribute('aria-label', label);
    if (value == null) sel.appendChild(new Option('Pick one', ''));
    (d.entities || []).forEach(function (e) { sel.appendChild(new Option(e.label, String(e.id))); });
    sel.value = value == null ? '' : String(value);
    return sel;
  }

  /* A billing entity typed in, new or changed. Nothing in it is secret, so a refused
     save keeps all of it and says why by Save. */
  function entityForm(d, e) {
    var f = el('form', 'hb-form pay-entity-form');
    f.setAttribute('data-form', 'entity');
    f.noValidate = true;
    f.setAttribute('aria-label', e ? 'Edit ' + e.label : 'Add a billing entity');
    f.setAttribute('autocomplete', 'off');
    editing(f, 'entity');
    f.appendChild(el('h5', 'hb-h5', e ? 'Edit ' + e.label : 'New billing entity'));
    var v = P.entityDraft || (e ? { label: e.label, company: e.company, vat: e.vat, reg_number: e.reg_number,
                                     email: e.email, address: e.address || {} } : { address: {} });
    /* The two names Petar could not tell apart (fr_da02f21285d7): `label` is only ever
       Rouh's own name for the entity, and `company` is what payments.py fills into a
       checkout and an invoice carries. */
    var label = field('Trading name, used in Rouh', 'text', v.label, 'payEntLabel', {
      auto: 'off', max: 80, cls: 'wide', place: 'Northwind, or Personal',
      help: 'The everyday name you pick this entity by in Rouh. It is never put on an invoice.' });
    f.appendChild(label.label);
    f.appendChild(el('p', 'settings-help', 'For the invoice, each only if it is filled in:'));
    var company = field('Legal name, as registered (optional)', 'text', v.company, 'payEntCompany', {
      auto: 'off', max: 200, cls: 'wide', place: 'Northwind Ltd',
      help: 'What invoices and official documents carry, so type it exactly as on the company’s registration. ' +
            'Leave it empty for a personal entity.' });
    var r1 = el('div', 'hb-row');
    var vat = field('VAT number', 'text', v.vat, 'payEntVat', { auto: 'off', max: 40, place: 'BG123456789' });
    var reg = field('Registration number', 'text', v.reg_number, 'payEntReg', { auto: 'off', max: 40, place: 'Company or EIK number' });
    r1.appendChild(vat.label); r1.appendChild(reg.label);
    var email = field('Email for invoices', 'email', v.email, 'payEntEmail', { auto: 'off', max: 200, cls: 'wide' });
    f.appendChild(company.label);
    f.appendChild(r1);
    f.appendChild(email.label);
    f.appendChild(el('h5', 'hb-h5', 'Billing address'));
    var a = v.address || {};
    var l1 = field('Street', 'text', a.line1, 'payLine1', { auto: 'off', max: 120, cls: 'wide' });
    var l2 = field('Second line', 'text', a.line2, 'payLine2', { auto: 'off', max: 120, cls: 'wide' });
    var r2 = el('div', 'hb-row');
    var city = field('City', 'text', a.city, 'payCity', { auto: 'off', max: 120 });
    var zip = field('Postcode', 'text', a.postal_code, 'payZip', { auto: 'off', max: 20 });
    r2.appendChild(city.label); r2.appendChild(zip.label);
    var r3 = el('div', 'hb-row');
    var region = field('Region', 'text', a.state, 'payRegion', { auto: 'off', max: 120 });
    var country = field('Country (two letters)', 'text', a.country, 'payCountry', { auto: 'off', max: 2, place: 'BG' });
    r3.appendChild(region.label); r3.appendChild(country.label);
    [l1.label, l2.label, r2, r3].forEach(function (n) { f.appendChild(n); });
    markWrong('entity', { label: label, company: company, vat: vat, reg_number: reg, email: email, line1: l1,
                          line2: l2, city: city, postal_code: zip, state: region, country: country });
    if (P.entityError) {
      var why = el('p', 'hb-say bad pay-card-error', P.entityError);
      why.setAttribute('role', 'alert');
      f.appendChild(why);
    }
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', e ? 'Save' : 'Add entity');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () {
      P.entity = '';
      P.editing = '';
      P.entityDraft = null;
      P.entityError = '';
      P.wrong = { form: '', errs: {} };
      draw();
    }));
    f.appendChild(acts);
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var body = { label: label.input.value, company: company.input.value, vat: vat.input.value,
                   reg_number: reg.input.value, email: email.input.value,
                   address: { line1: l1.input.value, line2: l2.input.value, city: city.input.value,
                              postal_code: zip.input.value, state: region.input.value,
                              country: country.input.value.toUpperCase() } };
      if (e) body.id = e.id;
      P.editing = '';
      P.entityDraft = body;
      P.entityError = '';
      post('/api/payments/entity', body, 'entity').then(function (j) {
        if (j && j.ok) {
          P.entity = '';
          P.entityDraft = null;
          draw();
        } else if (P.entity !== '' && P.error) {
          // A refusal that is no one field's: said by Save, where the eye is.
          P.entityError = P.error;
          P.error = '';
          draw();
          var again = $('payEntLabel');
          if (again) again.focus();
          var said = document.querySelector('#paymentsBody .pay-entity-form .hb-actions');
          if (said) said.scrollIntoView({ block: 'nearest' });
        }
      });
    });
    return f;
  }

  /* The expiry as MM/YY, with the slash put in by the page: the number keypad a phone
     shows for it has none. `k` is how many digits are before the caret, and `typed` says
     the change was an insertion, which may put a 0 before a month that can only be one
     digit (4, or 1 then 3, or 1 then a slash) and may take 12/2028 as 12/28. Answers the
     field's text and where the caret goes in it. */
  function expiryText(raw, k, typed) {
    var d = raw.replace(/\D/g, '');
    if (typed) {
      if (/^\s*[1-9]\s*\//.test(raw) || /^[2-9]/.test(d) || /^1[3-9]/.test(d)) {
        d = '0' + d;
        if (k > 0) k++;
      }
      if (d.length === 6 && d.slice(2, 4) === '20') {
        d = d.slice(0, 2) + d.slice(4);
        k = Math.max(Math.min(k, 2), k - 2);
      }
    }
    d = d.slice(0, 4);
    k = Math.min(k, d.length);
    return { text: d.length >= 2 ? d.slice(0, 2) + '/' + d.slice(2) : d, at: k >= 2 ? k + 1 : k };
  }

  /* Digits only into the expiry, the slash coming by itself after the month, and never
     in the way: a delete that took only the slash takes the digit beside it instead, so
     each press of backspace removes one digit. */
  function expiryTyping(input) {
    var was = input.value;
    input.addEventListener('input', function (ev) {
      var raw = input.value;
      var at = input.selectionStart == null ? raw.length : input.selectionStart;
      var kind = /** @type {InputEvent} */ (ev).inputType || '';
      var k = raw.slice(0, at).replace(/\D/g, '').length;
      var before = was.replace(/\D/g, '');
      var now = raw.replace(/\D/g, '');
      var typed = !/^delete/.test(kind);
      if (!typed && now === before) {
        if (/Backward/.test(kind) && k > 0) { raw = now.slice(0, k - 1) + now.slice(k); k--; }
        else if (/Forward/.test(kind)) raw = now.slice(0, k) + now.slice(k + 1);
      }
      if (typed && before.length >= 4 && now.replace(/^(\d\d)20(\d\d)$/, '$1$2').length > 4) {
        // Already MM/YY: a fifth digit is not taken, wherever the caret was.
        var back = Math.max(0, at - (input.value.length - was.length));
        input.value = was;
        input.setSelectionRange(back, back);
        return;
      }
      var f = expiryText(raw, k, typed);
      input.value = f.text;
      if (document.activeElement === input) input.setSelectionRange(f.at, f.at);
      was = f.text;
    });
  }

  /* A new card, typed in under the entity whose Add card was pressed. */
  function cardForm(d, entityId) {
    var f = el('form', 'hb-form pay-card-form');
    f.setAttribute('data-form', 'card');
    f.noValidate = true;
    f.setAttribute('aria-label', 'Add a card');
    f.setAttribute('autocomplete', 'off');
    editing(f, 'card');
    f.appendChild(el('h5', 'hb-h5', 'New card'));
    // What a refused save kept: never the number, the expiry or the code.
    var kept = P.draft || {};
    var num = field('Card number', 'text', '', 'payNumber', { auto: 'off', mode: 'numeric', max: 23,
                                                               place: '1234 5678 9012 3456', cls: 'wide' });
    // Grouped in fours as it is typed, so it can be checked against the card.
    num.input.addEventListener('input', function () {
      var i = num.input;
      if (i.selectionStart !== i.value.length) return;
      i.value = i.value.replace(/\D/g, '').slice(0, 19).replace(/(\d{4})(?=\d)/g, '$1 ');
    });
    var r1 = el('div', 'hb-row');
    var exp = field('Expiry', 'text', '', 'payExpiry', { auto: 'off', mode: 'numeric', max: 7, place: 'MM/YY' });
    expiryTyping(exp.input);
    var cvc = field('Security code', 'password', '', 'payCvc', { auto: 'off', mode: 'numeric', max: 4, place: '123' });
    r1.appendChild(exp.label); r1.appendChild(cvc.label);
    var name = field('Name on the card', 'text', kept.name, 'payName', { auto: 'off', max: 120, cls: 'wide' });
    var r2 = el('div', 'hb-row');
    var siloField = el('label', 'hb-field');
    siloField.appendChild(el('span', '', 'Silo'));
    var silo = siloSelect(d, kept.silo, 'paySilo');
    siloField.appendChild(silo);
    var entField = el('label', 'hb-field');
    entField.appendChild(el('span', '', 'Billed to'));
    var ent = entitySelect(d, kept.entity != null ? kept.entity : entityId, 'payEntity');
    entField.appendChild(ent);
    r2.appendChild(entField); r2.appendChild(siloField);
    // A new card's caps start at the vault's old pair, so no card is added unbounded by mistake.
    var caps = capsFields(kept.caps || d.new_caps || {}, 'payCard');
    f.appendChild(num.label);
    f.appendChild(r1);
    f.appendChild(name.label);
    f.appendChild(r2);
    f.appendChild(el('h5', 'hb-h5', 'The most it may be charged'));
    f.appendChild(caps.row);
    f.appendChild(el('p', 'settings-help', 'Leave one empty for no cap of that kind. A month is the calendar month.'));
    markWrong('card', { number: num, expiry: exp, cvc: cvc, name: name, entity: { label: entField, input: ent },
                        silo: { label: siloField, input: silo }, per_purchase: caps.per_purchase,
                        per_day: caps.per_day, per_month: caps.per_month });
    if (P.cardError) {
      var why = el('p', 'hb-say bad pay-card-error', P.cardError);
      why.setAttribute('role', 'alert');
      f.appendChild(why);
    }
    var acts2 = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save card');
    save.type = 'submit';
    acts2.appendChild(save);
    var all = [num, exp, cvc, name, caps.per_purchase, caps.per_day, caps.per_month];
    acts2.appendChild(button('Cancel', '', function () {
      all.forEach(function (x) { x.input.value = ''; });
      P.adding = '';
      P.editing = '';
      P.draft = null;
      P.cardError = '';
      P.wrong = { form: '', errs: {} };
      draw();
    }));
    f.appendChild(acts2);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { number: num.input.value, expiry: exp.input.value, cvc: cvc.input.value,
                   name: name.input.value, silo: silo.value, entity: ent.value ? Number(ent.value) : null,
                   per_purchase: caps.per_purchase.input.value, per_day: caps.per_day.input.value,
                   per_month: caps.per_month.input.value };
      // The number, the expiry and the code leave the page with this one request
      // and are not kept in it: emptied now, whatever the server answers.
      num.input.value = ''; exp.input.value = ''; cvc.input.value = '';
      P.editing = '';
      P.draft = { name: body.name, silo: body.silo, entity: body.entity,
                  caps: { per_purchase: body.per_purchase, per_day: body.per_day, per_month: body.per_month } };
      P.cardError = '';
      // Kept apart: `body` is dropped as soon as it is sent, before the answer comes.
      var under = body.entity;
      post('/api/payments/card', body, 'card').then(function (j) {
        if (j && j.ok) {
          all.forEach(function (x) { x.input.value = ''; });
          silo.value = '';
          P.adding = '';
          P.draft = null;
          draw();
          // The form is gone: bring the entity the new card is under back into view.
          var back = document.querySelector('#paymentsBody .pay-entity[data-entity="' + under + '"]');
          if (back) back.scrollIntoView({ block: 'nearest' });
        } else if (P.adding !== '' && P.error) {
          // A refusal that is no one field's: said by the button, where the eye is,
          // rather than above the vault.
          P.cardError = P.error;
          P.error = '';
          draw();
          var again = $('payNumber');
          if (again) again.focus();
          var said = document.querySelector('#paymentsBody .pay-card-form .hb-actions');
          if (said) said.scrollIntoView({ block: 'nearest' });
        }
      });
      body = null;
    });
    return f;
  }

  function stripeCard(d) {
    var s = card('Stripe', d.stripe ? ({ live: 'live', test: 'test mode' }[d.stripe.mode] || '') : '', 'pay-stripe');
    s.appendChild(el('p', 'settings-help', 'A restricted key lets Rouh make products, prices and payment links for a ' +
      'quest, and read what was paid. Refunds go to the Heartbeat’s approval queue, and payouts and account changes stay yours.'));
    var split = el('div', 'pay-split');
    var left = el('div', 'pay-key');
    if (d.stripe) {
      var shown = el('div', 'pay-saved');
      shown.appendChild(el('span', 'pay-brand', 'Key'));
      shown.appendChild(el('code', 'pay-hint', d.stripe.hint));
      if (d.stripe.saved) shown.appendChild(el('span', 'pay-when', 'saved ' + d.stripe.saved));
      left.appendChild(shown);
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Delete key', 'danger', function () {
        if (!window.confirm('Delete the Stripe key? Its webhook is forgotten with it.')) return;
        post('/api/payments/stripe/delete', {});
      }));
      left.appendChild(acts);
      left.appendChild(el('h5', 'hb-h5', 'Webhook'));
      if (d.webhook) {
        var row = el('div', 'copy-row');
        row.appendChild(el('code', '', d.webhook.url));
        left.appendChild(row);
        left.appendChild(el('p', 'settings-help', 'Stripe sends every payment here; each is checked against its signing ' +
          'secret, recorded as money in against the work it came from, and you are told on Telegram.'));
      } else {
        left.appendChild(el('p', 'settings-help', 'Not made yet. Rouh makes its own endpoint at the address it is served on, ' +
          'and keeps the signing secret sealed.'));
      }
      var hookActs = el('div', 'hb-actions');
      var make = button(d.webhook ? 'Make it again' : 'Make the webhook', d.webhook ? '' : 'primary', function () {
        post('/api/payments/webhook', {});
      });
      make.id = 'payWebhook';
      hookActs.appendChild(make);
      left.appendChild(hookActs);
    } else {
      var f = el('form', 'hb-form');
      f.setAttribute('data-form', 'stripe');
      f.noValidate = true;
      f.setAttribute('aria-label', 'Stripe key');
      f.setAttribute('autocomplete', 'off');
      editing(f, 'stripe');
      var key = field('Restricted key', 'password', '', 'payStripeKey', { auto: 'off', max: 300,
                                                                       place: 'rk_live_… or rk_test_…', cls: 'wide' });
      markWrong('stripe', { key: key });
      f.appendChild(key.label);
      var acts2 = el('div', 'hb-actions');
      var save = el('button', 'ctl small primary', 'Save key');
      save.type = 'submit';
      acts2.appendChild(save);
      f.appendChild(acts2);
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var value = key.input.value;
        key.input.value = '';
        P.editing = '';
        post('/api/payments/stripe', { key: value }, 'stripe');
      });
      left.appendChild(f);
    }
    split.appendChild(left);
    var perms = el('div', 'pay-perms');
    perms.appendChild(el('h5', 'hb-h5', 'Make the key with'));
    [['Write', d.permissions.write], ['Read', d.permissions.read], ['None', d.permissions.none]].forEach(function (p) {
      var block = el('div', 'pay-perm ' + p[0].toLowerCase());
      block.appendChild(el('span', 'pay-perm-name', p[0]));
      block.appendChild(el('span', 'pay-perm-what', p[1].join(', ')));
      perms.appendChild(block);
    });
    perms.appendChild(el('p', 'settings-help', 'In Stripe: Developers, API keys, Create restricted key.'));
    split.appendChild(perms);
    s.appendChild(split);
    return s;
  }

  function chargesCard(d) {
    var s = card('Bought with the card', d.charges.length ? String(d.charges.length) : '', 'pay-charges');
    if (!d.charges.length) {
      s.appendChild(el('p', 'hb-empty', 'Nothing yet.'));
      return s;
    }
    var list = el('ol', 'hb-list');
    d.charges.forEach(function (c) {
      var li = el('li', 'hb-beat pay-charge ' + c.state);
      var top = el('div', 'hb-beat-top');
      top.appendChild(el('span', 'hb-when', c.when));
      top.appendChild(el('span', 'hb-beat-what', c.merchant));
      // A press is not a payment: paid only once the page confirmed it (rouh/purchases.py).
      top.appendChild(el('span', 'hb-beat-nums', (c.state === 'void' ? 'never went through · ' :
        c.state === 'unpaid' ? 'unpaid order · ' :
        c.state === 'submitted' ? 'ordered, awaiting payment · ' :
        c.state === 'confirming' ? 'pressed, awaiting confirmation · ' :
        c.state === 'bank' ? 'waiting for your bank\u2019s approval · ' :
        c.state === 'failed' ? 'payment failed · ' :
        c.state === 'unconfirmed' ? 'not confirmed · ' :
        c.state === 'paid' ? 'paid · ' : '') +
        c.amount + ' ' + c.currency));
      li.appendChild(top);
      var why = el('p', 'hb-beat-reason', (c.placed && c.bought ? c.bought : c.reason) + ' · ' + c.card +
        (c.billed_to && !c.billing_address ? ' · billed to ' + c.billed_to : ''));
      li.appendChild(why);
      // Where it was billed and where it went, each on its own line, so the two can be
      // checked apart (fr_cd4ba48083df).
      if (c.billing_address) {
        li.appendChild(el('p', 'hb-beat-for', 'Billed to ' +
          (c.billed_to ? c.billed_to + ', ' : '') + c.billing_address));
      }
      if (c.delivered_to) li.appendChild(el('p', 'hb-beat-for', 'Delivered to ' + c.delivered_to));
      if (c.placed || c.submitted || c.pressed) {
        // Ordered by Rouh itself, on Petar's own words (rouh/purchases.py).
        li.appendChild(el('p', 'hb-beat-for', 'Ordered by Rouh' +
          (c.words ? ' on your words: \u201c' + c.words + '\u201d' : '')));
      }
      if (c.state === 'unpaid') {
        // Submitted at a shop that takes the card afterwards, and never paid.
        li.appendChild(el('p', 'hb-beat-for', 'The shop has this order and is waiting for the money. Pay it from your account there, or ask them to cancel it.'));
      }
      if (c.state === 'bank') {
        li.appendChild(el('p', 'hb-beat-for', 'Nothing is paid until you approve it with your bank' +
          (c.outcome ? ': the page said \u201c' + c.outcome.replace(/[.\s]+$/, '') + '\u201d' : '') + '.'));
      } else if (c.state === 'failed' && c.outcome) {
        li.appendChild(el('p', 'hb-beat-for', 'The page said \u201c' + c.outcome + '\u201d'));
      } else if (c.state === 'unconfirmed') {
        li.appendChild(el('p', 'hb-beat-for', 'Rouh pressed Pay, but ' +
          (c.outcome || 'nothing') + ' before the page said whether it went through. Check the shop or your bank.'));
      }
      if (c.task && !c.work) li.appendChild(el('p', 'hb-beat-for', 'For task ' + c.task));
      if (c.work) {
        var p = el('p', 'hb-beat-for', 'For ');
        var a = el('a', 'hb-raised work', c.work);
        a.href = c.work_href;
        a.addEventListener('click', function (e) { e.preventDefault(); if (host().go) host().go(c.work_href); });
        p.appendChild(a);
        li.appendChild(p);
      }
      var waiting = c.state === 'confirming' || c.state === 'bank' || c.state === 'unconfirmed';
      if (c.state === 'filled' || c.state === 'submitted' || waiting) {
        var acts = el('div', 'hb-ask-do');
        if (waiting) {
          acts.appendChild(button('It was paid', '', function () {
            post('/api/payments/charge/paid', { id: c.id });
          }, 'The shop or your bank shows it went through'));
        }
        acts.appendChild(button('It never went through', '', function () {
          post('/api/payments/charge/void', { id: c.id });
        }, 'Take it off the caps and out of its work’s ledger'));
        li.appendChild(acts);
      }
      list.appendChild(li);
    });
    s.appendChild(list);
    return s;
  }

  function moneyInCard(d) {
    var s = card('Came in through Stripe', d.money_in.length ? String(d.money_in.length) : '', 'pay-in');
    if (!d.money_in.length) {
      s.appendChild(el('p', 'hb-empty', 'Nothing yet.'));
      return s;
    }
    var table = el('table', 'hb-table');
    var tbody = el('tbody');
    d.money_in.forEach(function (e) {
      var tr = el('tr', 'in');
      tr.appendChild(el('td', 'hb-when', e.when));
      tr.appendChild(el('td', '', e.what + (e.work ? ' · ' + e.work : '')));
      tr.appendChild(el('td', 'hb-amt', '+' + e.amount + ' ' + e.currency));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    s.appendChild(table);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (P.open) return;
    P.open = true;
    P.said = '';
    P.editing = '';
    draw();
    load();
  }

  function hiddenNow() {
    P.open = false;
    P.editing = '';
    P.adding = '';
    P.draft = null;
    P.cardError = '';
    P.entity = '';
    P.entityDraft = null;
    P.entityError = '';
    P.capsFor = '';
    P.capsDraft = null;
    P.wrong = { form: '', errs: {} };
    // Nothing typed into the card form stays in the page once it is left.
    var body = $('paymentsBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { i.value = ''; });
  }

  window.RouhPayments = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
