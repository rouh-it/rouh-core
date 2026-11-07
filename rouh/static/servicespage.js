/* Anatomy, Money, Services, at /anatomy/money/services (`rouh/services.py`, `rouh/web/services.py`).

   Petar, 15 October 2026: "Services are things we purchase and we need to track and maybe
   unsubscribe ... the services item should be in payments of anatomy." So this is a list kept
   by hand, beside Payments: each service paid for again and again, what one month, year or week
   of it costs, when it renews next, when a trial ends, what pays for it, the account it is under
   and how to cancel it. Mark cancelled once it has been; nothing here cancels or pays for
   anything. It has nothing to do with the nightly feature run, which keeps its own sign-ups.

   A section of Anatomy's Money, drawn into `#servicesBody` from `/api/settings/services`.
   Anatomy tells it when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  /* form: 'new', a service's id being edited, or ''. draft: what a refused save kept.
     wrong: what the server said is wrong in the form last sent, by its fields. armed: the id
     of a service whose Remove was pressed once. */
  var S = { open: false, data: null, error: '', said: '', seq: 0, busy: false,
            form: '', draft: null, wrong: {}, armed: 0 };

  function host() { return window.RouhHeartbeatHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    b.disabled = S.busy;
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

  function call(method, url, body) {
    var seq = ++S.seq;
    if (method === 'POST') { S.busy = true; S.said = ''; }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = false;
          if (seq !== S.seq && method === 'GET') return j;
          if (j && j.services) S.data = j;
          var errs = !r.ok && j && j.fields && typeof j.fields === 'object' ? j.fields : null;
          S.wrong = errs || {};
          if (r.ok) { S.error = ''; S.said = (j && j.said) || ''; }
          else S.error = errs ? '' : (j && j.error) || 'The server said ' + r.status + '.';
          if (r.ok && method === 'POST') { S.form = ''; S.draft = null; }
          draw();
          if (errs) {
            var first = document.querySelector('#servicesBody [aria-invalid="true"]');
            if (first) { first.focus({ preventScroll: true }); first.scrollIntoView({ block: 'center' }); }
          }
          return j;
        });
      })
      .catch(function () {
        S.busy = false;
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/settings/services'); }

  /* ---- words ---- */

  var SYMBOL = { USD: '$', EUR: '€', GBP: '£' };
  function money(amount, currency) {
    var sym = SYMBOL[currency];
    return sym ? sym + amount : amount + ' ' + currency;
  }
  function cost(v) {
    return v.amount ? money(v.amount, v.currency) + ' ' + v.period_said : 'Cost not written down';
  }
  function day(iso) {
    if (!iso) return '';
    try {
      var p = iso.split('-');
      return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
    } catch (err) { return iso; }
  }
  function within(n) {
    if (n == null) return '';
    if (n === 0) return 'today';
    if (n === 1) return 'tomorrow';
    if (n < 0) return n === -1 ? 'yesterday' : (-n) + ' days ago';
    return 'in ' + n + ' days';
  }
  var PILL = { active: 'yes', trial: 'blocking', cancelled: 'no' };

  /* ---- drawing ---- */

  function draw() {
    var body = $('servicesBody');
    if (!body || !S.open) return;
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.error || S.said);
    say.setAttribute('role', 'status');
    say.hidden = !(S.error || S.said);
    page.appendChild(say);
    var d = S.data;
    if (!d) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the services…'));
      return;
    }
    page.appendChild(listCard(d));
  }

  function listCard(d) {
    var s = el('section', 'setting-card hb-card svc-card');
    var h = el('h4', 'hb-h', 'Services');
    if (d.services.length) h.appendChild(el('span', 'hb-h-sub', String(d.services.length)));
    s.appendChild(h);
    s.appendChild(el('p', 'settings-help', 'What you or Rouh pay for again and again: a subscription, a plan, a trial ' +
      'that turns into one. Each is written down here, to see what it costs, when it renews and how to stop it. ' +
      'Rouh never cancels or pays for one by itself.'));
    if (d.monthly.length) {
      s.appendChild(el('p', 'svc-total', 'The active ones come to about ' +
        d.monthly.map(function (m) { return money(m.amount, m.currency); }).join(' and ') + ' a month.'));
    }
    if (!d.services.length && S.form !== 'new') s.appendChild(el('p', 'hb-empty', 'None yet.'));
    if (d.services.length) {
      var list = el('ul', 'hb-list svc-list');
      d.services.forEach(function (v) {
        list.appendChild(S.form === String(v.id) ? wrapForm(d, v) : row(v));
      });
      s.appendChild(list);
    }
    if (S.form === 'new') s.appendChild(form(d, null));
    else {
      var acts = el('div', 'hb-actions svc-add');
      acts.appendChild(button('Add a service', d.services.length ? '' : 'primary', function () {
        S.form = 'new'; S.draft = null; S.wrong = {}; S.said = ''; S.error = ''; S.armed = 0;
        draw();
        var first = $('svcName');
        if (first) first.focus();
      }));
      s.appendChild(acts);
    }
    return s;
  }

  function wrapForm(d, v) {
    var li = el('li', 'hb-beat svc-item');
    li.appendChild(form(d, v));
    return li;
  }

  function row(v) {
    var li = el('li', 'hb-beat svc-item ' + v.state);
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what', v.name));
    top.appendChild(el('span', 'hb-pill ' + (PILL[v.state] || ''), v.state_said));
    top.appendChild(el('span', 'hb-beat-nums svc-cost', cost(v)));
    li.appendChild(top);
    var dl = el('dl', 'hb-ask-dl svc-dl');
    function line(name, value) {
      if (!value) return;
      dl.appendChild(el('dt', '', name));
      var dd = el('dd');
      if (typeof value === 'string') dd.textContent = value; else dd.appendChild(value);
      dl.appendChild(dd);
    }
    line('For', v.what_for);
    if (v.state !== 'cancelled') {
      if (v.renews_next) line('Renews', day(v.renews_next) + ' (' + within(v.renews_in) + ')');
      if (v.trial_ends) line('Trial ends', day(v.trial_ends) + ' (' + within(v.trial_in) + ')');
    }
    line('Paid with', v.paid_with);
    line('Account', v.account);
    if (v.cancel_how) {
      var how = v.cancel_how;
      if (/^https?:\/\/\S+$/i.test(how)) {
        var a = el('a', '', how);
        a.href = how;
        a.target = '_blank';
        a.rel = 'noopener';
        line('How to cancel', a);
      } else line('How to cancel', how);
    }
    if (dl.childNodes.length) li.appendChild(dl);
    var acts = el('div', 'hb-actions svc-acts');
    acts.appendChild(button('Edit', '', function () {
      S.form = String(v.id); S.draft = null; S.wrong = {}; S.said = ''; S.error = ''; S.armed = 0;
      draw();
      var first = $('svcName');
      if (first) first.focus();
    }));
    if (v.state === 'cancelled') {
      acts.appendChild(button('Active again', '', function () {
        call('POST', '/api/settings/services/state', { id: v.id, state: 'active' });
      }));
    } else {
      acts.appendChild(button('Mark cancelled', '', function () {
        call('POST', '/api/settings/services/state', { id: v.id, state: 'cancelled' });
      }));
    }
    var armed = S.armed === v.id;
    acts.appendChild(button(armed ? 'Remove for good' : 'Remove', armed ? 'danger' : '', function () {
      if (!armed) { S.armed = v.id; draw(); return; }
      S.armed = 0;
      call('POST', '/api/settings/services/delete', { id: v.id });
    }));
    if (armed) acts.appendChild(el('span', 'settings-help', 'Takes it out of the list. Mark cancelled keeps it as a record.'));
    li.appendChild(acts);
    return li;
  }

  /* ---- the form ---- */

  function field(text, type, value, id, opts) {
    opts = opts || {};
    var label = el('label', 'hb-field' + (opts.cls ? ' ' + opts.cls : ''));
    label.appendChild(el('span', '', text));
    var input;
    if (type === 'select') {
      input = el('select');
      opts.options.forEach(function (o) { input.appendChild(new Option(o.name, o.id)); });
    } else {
      input = el('input');
      input.type = type;
      if (opts.max) input.maxLength = opts.max;
      if (opts.place) input.placeholder = opts.place;
      if (opts.mode) input.setAttribute('inputmode', opts.mode);
      if (opts.list) input.setAttribute('list', opts.list);
      input.setAttribute('autocomplete', 'off');
      input.spellcheck = false;
    }
    input.id = id;
    input.value = value == null ? '' : String(value);
    label.appendChild(input);
    var said = S.wrong[opts.name || ''];
    if (said) {
      var box = el('span', 'svc-field-error', said);
      box.id = id + 'Error';
      label.appendChild(box);
      label.classList.add('wrong');
      input.setAttribute('aria-invalid', 'true');
      input.setAttribute('aria-describedby', box.id);
    }
    return { label: label, input: input };
  }

  function form(d, v) {
    var f = el('form', 'hb-form svc-form');
    f.noValidate = true;
    f.setAttribute('aria-label', v ? 'Edit ' + v.name : 'Add a service');
    f.appendChild(el('h5', 'hb-h5', v ? 'Edit ' + v.name : 'New service'));
    var x = S.draft || v || { currency: 'USD', period: 'month', state: 'active' };
    var name = field('Name', 'text', x.name, 'svcName', { name: 'name', max: 120, cls: 'wide', place: 'Figma, Google Workspace, ElevenLabs' });
    var what = field('What it is for (optional)', 'text', x.what_for, 'svcFor', { name: 'what_for', max: 300, cls: 'wide' });
    var r1 = el('div', 'hb-row');
    var amount = field('Cost', 'text', x.amount, 'svcAmount', { name: 'amount', max: 14, mode: 'decimal', place: '12.00' });
    var currency = field('Currency', 'text', x.currency, 'svcCurrency', { name: 'currency', max: 3, place: 'USD' });
    var period = field('Each', 'select', x.period, 'svcPeriod', { name: 'period', options: d.periods });
    [amount, currency, period].forEach(function (one) { r1.appendChild(one.label); });
    var r2 = el('div', 'hb-row');
    var state = field('It is', 'select', x.state, 'svcState', { name: 'state', options: d.states });
    var renews = field('Renews on', 'date', x.renews_on, 'svcRenews', { name: 'renews_on' });
    var trial = field('Trial ends (optional)', 'date', x.trial_ends, 'svcTrial', { name: 'trial_ends' });
    [state, renews, trial].forEach(function (one) { r2.appendChild(one.label); });
    var paid = field('Paid with (optional)', 'text', x.paid_with, 'svcPaid', { name: 'paid_with', max: 120, list: 'svcCards', place: 'Visa ending 4242' });
    var cards = el('datalist');
    cards.id = 'svcCards';
    (d.cards || []).forEach(function (c) { cards.appendChild(new Option(c)); });
    paid.label.appendChild(cards);
    var account = field('Account it is under (optional)', 'text', x.account, 'svcAccount', { name: 'account', max: 200, place: 'you@example.com' });
    var r3 = el('div', 'hb-row');
    r3.appendChild(paid.label); r3.appendChild(account.label);
    var cancel = field('How to cancel (optional)', 'text', x.cancel_how, 'svcCancel', { name: 'cancel_how', max: 600, cls: 'wide', place: 'A link, or Account, Billing, Cancel plan' });
    [name.label, what.label, r1, r2, r3, cancel.label].forEach(function (n) { f.appendChild(n); });
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', v ? 'Save' : 'Add service');
    save.type = 'submit';
    save.disabled = S.busy;
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () {
      S.form = ''; S.draft = null; S.wrong = {};
      draw();
    }));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { name: name.input.value, what_for: what.input.value, amount: amount.input.value,
                   currency: currency.input.value.toUpperCase(), period: period.input.value,
                   state: state.input.value, renews_on: renews.input.value, trial_ends: trial.input.value,
                   paid_with: paid.input.value, account: account.input.value, cancel_how: cancel.input.value };
      if (v) body.id = v.id;
      S.draft = body;
      call('POST', '/api/settings/services', body);
    });
    return f;
  }

  /* ---- shown and left ---- */
  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = '';
    S.form = '';
    S.armed = 0;
    draw();
    load();
  }
  function hiddenNow() { S.open = false; }

  window.RouhServices = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
