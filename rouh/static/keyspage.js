/* Settings, Keys, at /anatomy/connections/keys (`rouh/service_keys.py`, `rouh/web/service_keys.py`).

   Petar, 12 November 2026: "this should be done for all such integrations and connections. we
   should be able to save it in there. in the settings. just like the cloudflare setup, you paste
   the code there, not in the chat and not in the file on the computer directly".

   Built the way Cloudflare's page is (`cloudflarepage.js`): one card a service, with what Rouh
   does with it, where its key is made, and each of its values: a secret drawn only as set, its
   last four and when, a plain value (a chat id, an address) as itself. A value leaves the page in
   one request and every secret field is emptied at once, whatever the answer. The server checks
   the values with the service before keeping any; a refusal says why under the card. A secret
   left empty keeps the one already kept, so a voice can be changed without the key again.

   A group of Settings, drawn into `#keysBody` from `/api/settings/keys`. Settings tells it when it
   shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var K = { open: false, data: null, busy: '', error: {}, said: '', seq: 0, editing: '', changing: {}, typed: {}, refocus: '' };

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

  function call(method, url, body, service) {
    var seq = ++K.seq;
    if (method === 'POST') { K.busy = service || 'x'; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') K.busy = '';
          if (seq !== K.seq && method === 'GET') return j;
          if (j && j.services) K.data = j;
          if (service) delete K.error[service];
          if (r.ok) {
            if (j && j.said) K.said = j.said;
            if (service && url.indexOf('/save') > 0) { K.changing[service] = false; delete K.typed[service]; }
            K.editing = '';
          } else if (service) {
            K.error[service] = (j && j.error) || 'The server said ' + r.status + '.';
            K.refocus = service;
          } else {
            K.said = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          if (K.refocus) {
            var again = document.querySelector('#keys-' + K.refocus + ' input[type=password], #keys-' + K.refocus + ' input');
            if (again) again.focus();
            K.refocus = '';
          }
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') K.busy = '';
        if (service) K.error[service] = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/settings/keys'); }
  function post(url, body, service) { K.said = ''; return call('POST', url, body, service); }

  /* A service's one state, the same word in its index button and on its card. */
  function stateOf(sv) {
    if (!sv.set) return { word: 'Not set', cls: '' };
    if (sv.check && sv.check.ok === false) return { word: 'Set · check failed', cls: 'failed' };
    if (!sv.check && !sv.page) return { word: 'Set · not checked', cls: 'unchecked' };
    return { word: 'Set', cls: 'yes' };
  }

  /* Open a service's form (or its card, when it is set) and put the cursor in it. */
  function openService(sv) {
    if (!sv.set && !sv.page) K.changing[sv.id] = true;
    K.editing = '';
    draw();
    var target = $('keys-' + sv.id);
    if (!target) return;
    target.scrollIntoView({ block: 'start', behavior: 'smooth' });
    var first = target.querySelector('input, a, button.primary, button');
    if (first) first.focus({ preventScroll: true });
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('keysBody');
    if (!body || !K.open) return;
    body.setAttribute('aria-busy', K.busy ? 'true' : 'false');
    if (K.editing && K.data && !K.busy) return;   // something is being typed: leave it be
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say = el('p', 'hb-say', K.said);
    say.setAttribute('role', 'status');
    say.hidden = !K.said;
    page.appendChild(say);
    if (!K.data) {
      page.appendChild(el('p', 'hb-empty', 'Reading the keys…'));
      return;
    }
    page.appendChild(aboutCard(K.data));
    K.data.services.forEach(function (sv) { page.appendChild(serviceCard(K.data, sv)); });
  }

  function card(title, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    s.appendChild(el('h4', 'hb-h', title));
    return s;
  }

  function aboutCard(d) {
    var s = card('Your services', 'keys-about');
    var set = d.services.filter(function (sv) { return sv.set; }).length;
    var failed = d.services.filter(function (sv) { return stateOf(sv).cls === 'failed'; }).length;
    s.appendChild(el('p', 'keys-lead', set + ' of ' + d.services.length + ' services are set' +
                     (failed ? ', ' + failed + ' failing its check.' : '.')));
    s.appendChild(el('p', 'settings-help', 'Paste a key here, never in a chat or a file: Rouh checks it with the ' +
      'service, keeps it sealed, shows only its last four, and uses it at once.'));
    if (!d.admin) s.appendChild(el('p', 'settings-help', 'Only an administrator of this Rouh changes its keys.'));
    // Most come here for one service Rouh named: each is one press away, with its state.
    var idx = el('ul', 'keys-index');
    idx.setAttribute('aria-label', 'Services');
    d.services.forEach(function (sv) {
      var st = stateOf(sv);
      var li = el('li');
      var b = el('button', 'keys-jump' + (st.cls ? ' ' + st.cls : ''));
      b.type = 'button';
      b.appendChild(el('span', 'keys-dot'));
      b.appendChild(el('span', '', sv.name));
      if (st.cls === 'failed') b.appendChild(el('span', 'keys-jump-word', 'failed'));
      if (st.cls === 'unchecked') b.appendChild(el('span', 'keys-jump-word dim', 'not checked'));
      b.setAttribute('aria-label', sv.name + ', ' + st.word.toLowerCase());
      b.addEventListener('click', function () { openService(sv); });
      li.appendChild(b);
      idx.appendChild(li);
    });
    s.appendChild(idx);
    var models = el('p', 'settings-help keys-models');
    models.appendChild(document.createTextNode('A model key (Anthropic, OpenAI, Google, xAI) goes in '));
    var a = el('a', '', 'Behaviour, Models');
    a.href = '/anatomy/behaviour/models';
    models.appendChild(a);
    models.appendChild(document.createTextNode(', the same way.'));
    s.appendChild(models);
    return s;
  }

  function serviceCard(d, sv) {
    var s = card(sv.name, 'keys-service');
    s.id = 'keys-' + sv.id;
    var head = s.querySelector('.hb-h');
    var st = stateOf(sv);
    head.appendChild(el('span', 'hb-pill keys-pill' + (st.cls ? ' ' + st.cls : ''), st.word));
    s.appendChild(el('p', 'settings-help', sv.what));

    var dl = el('dl', 'hb-ask-dl keys-fields');
    sv.fields.forEach(function (f) {
      var shown = !f.set ? 'not set'
        : f.source === 'settings_file' ? (f.secret ? 'set, in the settings file' : f.value + ' (in the settings file)')
        : (f.secret ? 'set, ending …' + f.last4 : f.value) + (f.saved ? ', saved ' + f.saved : '');
      dl.appendChild(el('dt', '', f.label));
      dl.appendChild(el('dd', f.secret && f.set ? 'keys-mono' : 'keys-plain', shown));
    });
    // An open form shows the fields itself: the list is left out rather than shown twice.
    if (!K.changing[sv.id] && sv.fields.some(function (f) { return f.set; })) s.appendChild(dl);
    if (sv.check && sv.check.said) {
      var line = el('p', 'keys-check ' + (sv.check.ok === false ? 'bad' : 'good'));
      line.appendChild(el('span', 'keys-mark'));
      line.appendChild(el('span', '', (sv.check.ok === false ? 'Failed, checked ' : 'Passed, checked ') +
                                      sv.check.at + ': ' + sv.check.said));
      s.appendChild(line);
    }
    var err = K.error[sv.id];
    if (err) {
      var bad = el('p', 'keys-check bad keys-error');
      bad.appendChild(el('span', 'keys-mark'));
      bad.appendChild(el('span', '', err));
      bad.setAttribute('role', 'alert');
      s.appendChild(bad);
    }
    if (sv.page) {
      var go = el('p', 'settings-help');
      var a = el('a', '', 'Set it on its own page, with its steps');
      a.href = sv.page;
      go.appendChild(a);
      s.appendChild(go);
      return s;
    }
    if (!d.admin) return s;
    if (K.changing[sv.id]) {
      s.appendChild(form(sv));
    } else if (!sv.set) {
      var open = el('div', 'hb-actions');
      open.appendChild(button('Set up', '', function () { openService(sv); }, 'Paste ' + sv.name + "'s key"));
      s.appendChild(open);
    } else {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Change', '', function () {
        K.changing[sv.id] = true; delete K.error[sv.id]; K.said = ''; draw();
        var first = $('keys-' + sv.id + '-0');
        if (first) first.focus();
      }, 'Change ' + sv.name));
      acts.appendChild(button('Check again', sv.check && sv.check.ok === false ? 'primary' : '', function () {
        post('/api/settings/keys/check', { service: sv.id }, sv.id);
      }, 'Ask the service again whether these still work'));
      if (sv.from_page) {
        acts.appendChild(button('Remove', '', function () {
          if (!window.confirm('Remove ' + sv.name + '? Rouh forgets what was kept here, and uses the ' +
                              'settings file\'s, if it has one.')) return;
          post('/api/settings/keys/remove', { service: sv.id }, sv.id);
        }, 'Forget what was kept here'));
      }
      s.appendChild(acts);
    }
    return s;
  }

  function form(sv) {
    var f = el('form', 'hb-form keys-form');
    f.setAttribute('aria-label', sv.name);
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { K.editing = sv.id; });
    if (sv.steps && sv.steps.length) {
      var ol = el('ol', 'settings-steps');
      sv.steps.forEach(function (t) { ol.appendChild(el('li', '', t)); });
      f.appendChild(ol);
    }
    var inputs = [];
    sv.fields.forEach(function (fd, i) {
      var label = el('label', 'hb-field wide');
      var words = fd.label + (fd.required ? '' : ', if you have it');
      if (fd.secret && fd.set) words += ' (empty keeps the one ' + (fd.source === 'settings_file' ? 'in the settings file'
                                                                    : 'ending …' + fd.last4) + ')';
      label.appendChild(el('span', '', words));
      var input = el('input', fd.secret ? 'keys-mono' : '');
      input.id = 'keys-' + sv.id + '-' + i;
      input.type = fd.secret ? 'password' : 'text';
      input.setAttribute('autocomplete', fd.secret ? 'new-password' : 'off');
      input.setAttribute('autocapitalize', 'off');
      input.spellcheck = false;
      input.maxLength = 2000;
      input.placeholder = fd.placeholder || '';
      // What was typed into a field that is no secret survives a refusal; a secret never stays.
      var kept = (K.typed[sv.id] || {})[fd.name];
      if (!fd.secret && kept != null) input.value = kept;
      else if (!fd.secret && fd.value && fd.source === 'page') input.value = fd.value;
      input.setAttribute('data-name', fd.name);
      label.appendChild(input);
      f.appendChild(label);
      inputs.push(input);
    });
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', K.busy === sv.id ? 'Checking…' : 'Save');
    save.type = 'submit';
    save.disabled = !!K.busy;
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () {
      inputs.forEach(function (i) { i.value = ''; });
      K.changing[sv.id] = false; K.editing = ''; delete K.error[sv.id]; delete K.typed[sv.id];
      draw();
    }));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (K.busy) return;
      var values = {};
      var plain = K.typed[sv.id] = {};
      inputs.forEach(function (i) {
        values[i.getAttribute('data-name')] = i.value;
        if (i.type !== 'password') plain[i.getAttribute('data-name')] = i.value;
        // A secret leaves the page with this one request and is not kept in it.
        if (i.type === 'password') i.value = '';
      });
      K.editing = '';
      post('/api/settings/keys/save', { service: sv.id, values: values }, sv.id);
      values = null;
    });
    return f;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (K.open) return;
    K.open = true;
    K.said = '';
    K.error = {};
    K.editing = '';
    K.changing = {};
    draw();
    load();
  }

  function hiddenNow() {
    K.open = false;
    K.editing = '';
    // Nothing typed into a key's field stays in the page once it is left.
    var body = $('keysBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { i.value = ''; });
  }

  window.RouhKeys = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
