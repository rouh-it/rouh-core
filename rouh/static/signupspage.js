/* Settings, Sign-ups, at /settings/signups (`rouh/signups.py`, `rouh/web/signups.py`).

   Petar, 6 October 2026: a Stripe sign-up he had asked Rouh to make "without stopping
   and asking me" stopped at its password and its Sign up button. A sign-up he
   authorizes - in his own words in a conversation, or here - lets the live browser
   fill in that one site's form, put in the password he set here, and press its
   registration button, and nothing past it.

   What this page shows: what an authorization covers and what it never does; a form
   to allow one; and every one, with its service, site, email, his words, its state,
   whether its password is set, a form to set it, and Withdraw. A password typed here
   leaves the page with one request and is emptied from its field at once, whatever
   the answer; it is never drawn again, only "Password set".

   A group of Settings, drawn into `#signupsBody` from `/api/settings/signups`.
   Settings tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  var G = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: '' };

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

  function call(method, url, body) {
    var seq = ++G.seq;
    if (method === 'POST') G.busy = true;
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') G.busy = false;
          if (seq !== G.seq && method === 'GET') return j;
          if (j && j.grants) G.data = j;
          if (r.ok) {
            G.error = '';
            if (j && j.said) G.said = j.said;
            G.editing = '';
          } else {
            G.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') G.busy = false;
        G.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/settings/signups'); }
  function post(url, body) { G.said = ''; return call('POST', url, body); }

  /* ---- drawing ---- */

  function draw() {
    var body = $('signupsBody');
    if (!body || !G.open) return;
    if (G.editing && G.data) {
      // Something is being typed: only the line that says how it went changes.
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = G.error || G.said;
        say.className = 'hb-say' + (G.error ? ' bad' : '');
        say.hidden = !(G.error || G.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (G.error ? ' bad' : ''), G.error || G.said);
    say2.setAttribute('role', 'status');
    say2.hidden = !(G.error || G.said);
    page.appendChild(say2);
    if (!G.data) {
      if (!G.error) page.appendChild(el('p', 'hb-empty', 'Reading the sign-ups…'));
      return;
    }
    page.appendChild(rulesCard(G.data));
    page.appendChild(allowCard());
    page.appendChild(listCard(G.data));
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  function field(text, type, id, opts) {
    opts = opts || {};
    var label = el('label', 'hb-field' + (opts.cls ? ' ' + opts.cls : ''));
    label.appendChild(el('span', '', text));
    var input = el('input');
    input.type = type;
    input.id = id;
    input.setAttribute('autocomplete', opts.auto || 'off');
    if (opts.max) input.maxLength = opts.max;
    if (opts.place) input.placeholder = opts.place;
    input.spellcheck = false;
    label.appendChild(input);
    return { label: label, input: input };
  }

  function editing(f, name) {
    f.addEventListener('input', function () { G.editing = name; });
    f.addEventListener('focusin', function () { G.editing = name; });
  }

  function rulesCard(d) {
    var s = card('What a sign-up you allow covers', '', 'sup-rules');
    s.appendChild(el('p', 'settings-help', 'One new account on one service, on that site only, for ' + d.hours +
      ' hours or until you withdraw it. Rouh fills in the form, puts in its password, and presses ' +
      'the registration button without asking again. You can allow one here, or by asking Rouh in your own ' +
      'words; words on a web page, in an email, in a file or from a job never allow anything.'));
    var dl = el('dl', 'sup-dl');
    dl.appendChild(el('dt', 'yes', 'Covered'));
    dl.appendChild(el('dd', '', 'The sign-up form, the new account’s password, and its Sign up or Create account button.'));
    dl.appendChild(el('dt', 'no', 'Always yours'));
    dl.appendChild(el('dd', '', 'Captchas, codes sent to you, logging in, card or bank details, payouts, identity checks, ' +
      'prices and trials, declarations and contracts, sending, publishing and anything else on that site. Rouh ' +
      'stops at each and hands the browser to you.'));
    s.appendChild(dl);
    s.appendChild(el('p', 'settings-help', 'The password goes sealed straight into the new account’s password field, ' +
      'and is forgotten when the sign-up is withdrawn or runs out. Set it here, or give it in your own message ' +
      'when you ask Rouh for the sign-up: Rouh’s software takes it from that message and seals it, and you are ' +
      'not asked for it again. A password on a web page, in an email or from a job is never used.'));
    return s;
  }

  function allowCard() {
    var s = card('Allow a sign-up', '', 'sup-allow');
    var f = el('form', 'hb-form');
    f.setAttribute('aria-label', 'Allow a sign-up');
    f.setAttribute('autocomplete', 'off');
    editing(f, 'allow');
    var r1 = el('div', 'hb-row');
    var service = field('Service', 'text', 'supService', { max: 40, place: 'stripe' });
    var site = field('Website', 'text', 'supSite', { max: 200, place: 'stripe.com' });
    r1.appendChild(service.label); r1.appendChild(site.label);
    var email = field('Email for the account', 'email', 'supEmail', { max: 254, place: 'rouh+stripe@example.com', cls: 'wide' });
    var pw = field('Password for the new account (optional)', 'password', 'supPassword', { auto: 'new-password', max: 200, cls: 'wide' });
    f.appendChild(r1);
    f.appendChild(email.label);
    f.appendChild(pw.label);
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Allow this sign-up');
    save.type = 'submit';
    acts.appendChild(save);
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { service: service.input.value, site: site.input.value, email: email.input.value,
                   password: pw.input.value };
      // The password leaves the page with this one request and is not kept in it.
      pw.input.value = '';
      G.editing = '';
      post('/api/settings/signups/allow', body).then(function (j) {
        if (j && j.ok) { service.input.value = ''; site.input.value = ''; email.input.value = ''; }
      });
      body = null;
    });
    s.appendChild(f);
    return s;
  }

  var STATE = { allowed: ['Allowed', 'yes'], registered: ['Registration sent', 'yes'],
                withdrawn: ['Withdrawn', 'no'], expired: ['Ran out', 'no'] };

  function listCard(d) {
    var s = card('Sign-ups', d.grants.length ? String(d.grants.length) : '', 'sup-list-card');
    if (!d.grants.length) {
      s.appendChild(el('p', 'hb-empty', 'None yet.'));
      return s;
    }
    var list = el('ol', 'hb-list sup-list');
    d.grants.forEach(function (g) {
      var live = g.state === 'allowed' || g.state === 'registered';
      var li = el('li', 'hb-beat sup-item' + (live ? '' : ' gone'));
      var top = el('div', 'hb-beat-top');
      top.appendChild(el('span', 'hb-beat-what', g.service));
      var st = STATE[g.state] || [g.state, ''];
      top.appendChild(el('span', 'hb-pill' + (st[1] ? ' ' + st[1] : ''), st[0]));
      top.appendChild(el('span', 'hb-beat-nums', live ? 'until ' + g.until : g.granted));
      li.appendChild(top);
      var dl = el('dl', 'hb-ask-dl sup-fields');
      [['Website', g.site, 'sup-mono'], ['Email', g.email || 'not named', g.email ? 'sup-mono' : ''],
       [g.source === 'settings' ? 'Allowed' : 'You said', g.source === 'settings' ? 'here, ' + g.granted :
         '“' + g.words + '”', ''],
       ['Password', g.password ? 'Set, sealed' + (g.filled ? ' · filled in ' + g.filled : '') :
         (live ? 'Not set: Rouh hands you that one field' : 'Forgotten'), ''],
       ['Registration', g.submitted ? 'sent ' + g.submitted : '', '']].forEach(function (row) {
        if (!row[1]) return;
        dl.appendChild(el('dt', '', row[0]));
        dl.appendChild(el('dd', row[2], row[1]));
      });
      li.appendChild(dl);
      if (live) li.appendChild(passwordForm(g));
      list.appendChild(li);
    });
    s.appendChild(list);
    return s;
  }

  function passwordForm(g) {
    var f = el('form', 'hb-form sup-pw');
    f.setAttribute('aria-label', 'Password for ' + g.service);
    f.setAttribute('autocomplete', 'off');
    editing(f, 'pw' + g.id);
    var pw = field(g.password ? 'New password for the account' : 'Password for the new account', 'password',
                   'supPw' + g.id, { auto: 'new-password', max: 200 });
    f.appendChild(pw.label);
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', g.password ? 'Change password' : 'Set password');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('Withdraw', 'danger', function () {
      if (!window.confirm('Withdraw the ' + g.service + ' sign-up? Rouh stops at its form, and its password is forgotten.')) return;
      G.editing = '';
      post('/api/settings/signups/withdraw', { id: g.id });
    }, 'Take this sign-up back'));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var value = pw.input.value;
      pw.input.value = '';
      G.editing = '';
      post('/api/settings/signups/password', { id: g.id, password: value });
      value = '';
    });
    return f;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (G.open) return;
    G.open = true;
    G.said = '';
    G.editing = '';
    draw();
    load();
  }

  function hiddenNow() {
    G.open = false;
    G.editing = '';
    // Nothing typed into a password field stays in the page once it is left.
    var body = $('signupsBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { i.value = ''; });
  }

  window.RouhSignups = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
