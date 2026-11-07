/* Settings, Connections, Dreame, at /anatomy/connections/dreame (`rouh/dreame.py`, `rouh/web/dreame.py`).

   Petar, 17 October 2026: "I have robot for cleaning, can we connect that too?", his Dreame robot
   vacuum through the Dreamehome cloud.

   One card: not connected, connected to which robot on which account and when it was last
   reached, or lapsed and saying why. Until it is connected, or once it has lapsed, the sign-in
   under it: the app the robot is paired in (Dreamehome or Mi Home), the account's email and
   password, typed here by the person, and its region, Automatic to start with, with an (i)
   saying what the sign-in takes. The password leaves the page in the one request that signs in
   and is never kept in it. A Mi Home sign-in that Xiaomi stops shows, in place of the form, the
   field for the code Xiaomi sent or the picture whose letters it wants, which the person types
   (`waiting`, from the server, so a reload shows it again). Once connected: Check now and
   Disconnect.

   The same components as the Philips Hue card (`huepage.js`): the Heartbeat page's cards and the
   Slack page's (i), facts and form. A section of Anatomy, drawn into `#dreameBody` from
   `/api/settings/dreame`; Anatomy tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  var S = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: false, typed: null, focus: '' };

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
    if (method === 'POST') { S.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = false;
          if (seq !== S.seq && method === 'GET') return j;
          // Read again and nothing changed: the page is left exactly as it is.
          var same = method === 'GET' && r.ok && S.data && !S.error && JSON.stringify(S.data) === JSON.stringify(j);
          if (j && 'connected' in j) S.data = j;
          if (same) return j;
          if (r.ok) {
            S.error = '';
            if (j && j.said) S.said = j.said;
            if (method === 'POST') {
              S.editing = false;
              // What was being typed is kept until the robot is connected (Start again fills it back in).
              if (j && j.connected) S.typed = null;
            }
          } else {
            S.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') S.busy = false;
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/settings/dreame'); }
  function post(url, body) { S.said = ''; S.error = ''; return call('POST', url, body); }

  /* ---- the (i): what the sign-in takes, opened in place ---- */

  var INFO_SVG = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.4" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="6.2" r="1.15" fill="currentColor"/>' +
    '<path d="M10 9v5.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var infoSeq = 0;
  function info(label, lines) {
    var id = 'dreameInfo' + (++infoSeq);
    var b = el('button', 'sk-i');
    b.type = 'button';
    b.innerHTML = INFO_SVG;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', id);
    var note = el('div', 'sk-guide');
    note.id = id;
    note.hidden = true;
    lines.forEach(function (t) { note.appendChild(el('p', '', t)); });
    b.addEventListener('click', function () {
      note.hidden = !note.hidden;
      b.setAttribute('aria-expanded', note.hidden ? 'false' : 'true');
    });
    return { button: b, note: note };
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('dreameBody');
    if (!body || !S.open) return;
    body.setAttribute('aria-busy', S.busy ? 'true' : 'false');
    if (S.editing && S.data && !S.busy) {
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
    var say2 = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.busy ? 'Asking ' + (cloudNow() === 'mi' ? 'Xiaomi' : 'Dreamehome') + '…' : (S.error || S.said));
    say2.setAttribute('role', 'status');
    say2.hidden = !(S.busy || S.error || S.said);
    page.appendChild(say2);
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the connection…'));
      return;
    }
    page.appendChild(card(S.data));
    if (S.focus) {
      var f = $(S.focus);
      S.focus = '';
      if (f) f.focus();
    }
  }

  /* The app the request on its way is for: the one being signed in to, or the one connected. */
  function cloudNow() {
    if (S.typed && S.typed.account) return S.typed.account;
    if (S.data && S.data.waiting) return 'mi';
    return (S.data && S.data.account) || 'dreamehome';
  }

  function stateOf(d) {
    if (d.lapsed) return ['Sign in again', 'failed'];
    if (d.connected) return ['Connected', 'yes'];
    return ['Not connected', ''];
  }

  function card(d) {
    var s = el('section', 'setting-card hb-card dreame-card');
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what', d.robot || 'Dreame'));
    var st = stateOf(d);
    top.appendChild(el('span', 'hb-pill' + (st[1] ? ' ' + st[1] : ''), st[0]));
    s.appendChild(top);
    var rows = [];
    if (d.lapsed) rows.push(['Why', d.lapsed_said || 'The app no longer accepts Rouh’s sign-in.']);
    if (d.connected || d.lapsed) {
      if (d.account_name) rows.push(['App', d.account_name]);
      if (d.email) rows.push(['Account', d.email]);
      if (d.region_name) rows.push(['Region', d.region_name]);
      if (d.connected && !d.has_robot) rows.push(['Robot', 'None on this account']);
      if (d.since) rows.push(['Connected', d.since]);
      if (d.reached) rows.push(['Last reached', d.reached]);
    }
    if (rows.length) {
      var dl = el('dl', 'hb-ask-dl sk-fields');
      rows.forEach(function (r) {
        dl.appendChild(el('dt', '', r[0]));
        dl.appendChild(el('dd', '', r[1]));
      });
      s.appendChild(dl);
    }
    if (d.connected) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Check now', '', function () { post('/api/settings/dreame/check', {}); },
        'Reach the robot through the Dreamehome cloud now'));
      acts.appendChild(button('Disconnect', 'danger', function () {
        if (!window.confirm('Disconnect the Dreame robot? Rouh forgets your Dreamehome email, password and sign-in.')) return;
        post('/api/settings/dreame/disconnect', {});
      }, 'Forget your Dreamehome account'));
      s.appendChild(acts);
      return s;
    }
    s.appendChild(d.waiting ? waiting(d.waiting) : signIn(d));
    if (d.lapsed) {
      var acts2 = el('div', 'hb-actions');
      acts2.appendChild(button('Disconnect', 'danger', function () {
        if (!window.confirm('Disconnect the Dreame robot? Rouh forgets your Dreamehome email, password and sign-in.')) return;
        post('/api/settings/dreame/disconnect', {});
      }, 'Forget your Dreamehome account'));
      s.appendChild(acts2);
    }
    return s;
  }

  /* What the (i) says for each app. */
  var TIPS = {
    dreamehome: ['The email and password you sign in to the Dreamehome app with. An account made with Apple or Google sign-in has no password, so it cannot be used here.',
                 'Rouh keeps the password sealed, so it can sign in again by itself, and never shows it.'],
    mi: ['The Xiaomi account you sign in to the Mi Home app with: its email, phone number or Xiaomi ID, and its password.',
         'Xiaomi may send you a code, or show a picture with letters. You type them here yourself.',
         'Rouh keeps only Xiaomi’s sign-in, sealed, not the password.']
  };

  function signIn(d) {
    var typed = S.typed || {};
    var kind = typed.account || (d.lapsed && d.account) || 'dreamehome';
    var f = el('form', 'hb-form sk-form dreame-form');
    f.setAttribute('aria-label', 'The robot’s account');
    var head = el('h4', 'hb-h sk-label', 'The robot’s account');
    var tip = info('What the sign-in takes', TIPS[kind] || TIPS.dreamehome);
    head.appendChild(tip.button);
    f.appendChild(head);
    f.appendChild(tip.note);
    f.addEventListener('input', function () { S.editing = true; });
    var app = select(f, 'App the robot is in', 'dreameAccount', d.accounts || [{ id: 'dreamehome', name: 'Dreamehome' }]);
    app.value = kind;
    var email = field(f, kind === 'mi' ? 'Email, phone or Xiaomi ID' : 'Email', 'dreameEmail',
                      kind === 'mi' ? 'text' : 'email', 'username');
    email.value = typed.email != null ? typed.email : (d.lapsed && d.account === kind ? d.email || '' : '');
    email.setAttribute('inputmode', kind === 'mi' ? 'text' : 'email');
    var password = field(f, 'Password', 'dreamePassword', 'password', 'current-password');
    var regions = (d.regions && d.regions[kind]) || [{ id: 'auto', name: 'Automatic' }];
    var region = select(f, 'Region', 'dreameRegion', regions);
    var keep = typed.region || (d.lapsed && d.account === kind && d.region) || 'auto';
    region.value = regions.some(function (r) { return r.id === keep; }) ? keep : 'auto';
    // Another app redraws the form for it: its own (i), its own name for the account, its regions.
    // What was typed into the account's field stays; the password is never carried over.
    app.addEventListener('change', function () {
      S.typed = { account: app.value, email: email.value };
      S.editing = false;
      S.focus = 'dreameAccount';
      draw();
    });
    var acts = el('div', 'hb-actions');
    var go = el('button', 'ctl small primary', d.lapsed ? 'Connect again' : 'Connect');
    go.type = 'submit';
    go.disabled = S.busy;
    acts.appendChild(go);
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (S.busy) return;
      var body = { account: app.value, email: email.value, password: password.value, region: region.value };
      // The password leaves the page with this one request and is not kept in it.
      password.value = '';
      S.editing = false;
      S.typed = { account: body.account, email: body.email, region: body.region };
      post('/api/settings/dreame/connect', body);
      body = {};
    });
    return f;
  }

  /* A Mi Home sign-in Xiaomi stopped: the code it sent, or the letters in its picture, typed here. */
  function waiting(w) {
    var f = el('form', 'hb-form sk-form dreame-form');
    f.setAttribute('aria-label', w.step === 'code' ? 'Code from Xiaomi' : 'Letters in the picture');
    f.addEventListener('input', function () { S.editing = true; });
    var input;
    if (w.step === 'code') {
      f.appendChild(el('p', 'dreame-ask', w.sent_to ? 'Xiaomi sent a code to ' + w.sent_to + '.' : 'Xiaomi sent you a code.'));
      input = field(f, 'Code', 'dreameCode', 'text', 'one-time-code');
      input.setAttribute('inputmode', 'numeric');
      input.maxLength = 12;
    } else {
      f.appendChild(el('p', 'dreame-ask', 'Xiaomi wants the letters in this picture.'));
      if (w.image) {
        var img = el('img', 'dreame-captcha');
        img.src = w.image;
        img.alt = 'The picture from Xiaomi';
        f.appendChild(img);
      }
      input = field(f, 'Letters', 'dreameCaptcha', 'text', 'off');
      input.setAttribute('autocapitalize', 'characters');
      input.maxLength = 12;
    }
    var acts = el('div', 'hb-actions');
    var go = el('button', 'ctl small primary', w.step === 'code' ? 'Verify' : 'Continue');
    go.type = 'submit';
    go.disabled = S.busy;
    acts.appendChild(go);
    if (w.step === 'code') {
      acts.appendChild(button('Send a new code', '', function () {
        post('/api/settings/dreame/answer', { again: true });
      }, 'Ask Xiaomi to send the code again'));
    }
    acts.appendChild(button('Start again', '', function () {
      S.typed = { account: 'mi', email: w.user || '', region: w.region || 'auto' };
      post('/api/settings/dreame/cancel', {});
    }, 'Forget this sign-in and type the password again'));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (S.busy) return;
      var body = w.step === 'code' ? { code: input.value } : { captcha: input.value };
      input.value = '';
      S.editing = false;
      post('/api/settings/dreame/answer', body);
    });
    S.focus = S.focus || (w.step === 'code' ? 'dreameCode' : 'dreameCaptcha');
    return f;
  }

  function select(form, text, id, options) {
    var label = el('label', 'hb-field wide');
    label.appendChild(el('span', '', text));
    var sel = el('select');
    sel.id = id;
    options.forEach(function (r) {
      var o = el('option', '', r.name);
      o.value = r.id;
      sel.appendChild(o);
    });
    label.appendChild(sel);
    form.appendChild(label);
    return sel;
  }

  function field(form, text, id, type, auto) {
    var label = el('label', 'hb-field wide');
    label.appendChild(el('span', '', text));
    var input = el('input');
    input.type = type;
    input.id = id;
    input.name = id;
    input.setAttribute('autocomplete', auto);
    input.spellcheck = false;
    input.maxLength = 200;
    label.appendChild(input);
    form.appendChild(label);
    return input;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = ''; S.error = ''; S.editing = false;
    draw();
    load();
  }

  function hiddenNow() {
    S.open = false;
    S.editing = false;
    // Nothing typed into the password's field stays in the page once it is left.
    var body = $('dreameBody');
    if (body) body.querySelectorAll('input[type="password"]').forEach(function (i) { i.value = ''; });
  }

  window.RouhDreame = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
