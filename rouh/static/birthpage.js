/* Anatomy, Rouh Land Account, Rouh profile, at /anatomy/rouh-land/rouh-profile (`rouh/birth.py`,
   `rouh/web/birth.py`): Meta, Birthday until 4 November 2026. rouh.land still sends the person
   back to the old address with a code, which the server sends on here (`addressing.ROUH_LAND_RETURN`).

   Petar, 4 November 2026: "free rouh will get birth and official name by connecting to rouh.land.
   before that, only a nickname by the person", and "the keys should be opaque to users". So:

   - A free Rouh (never registered): it answers to Rouh and to the nicknames people give it, and one
     line says it is a free Rouh and that connecting it, on Your profile, gives it its birth and name.
   - Born (registered with rouh.land): its official name, which rouh.land gave it, its birthday, what
     this person calls it, and one plain line about rouh.land (`birth.standing`).

   Nothing else: no key, key id, registry id or recovery words, and no Models or Gene Pool (each
   has its own section). Back from rouh.land with a code (`?birth=`), the one press that connects
   it with that code; with the id of a new key asked for before (`?recovery=`), it is asked after.

   A section of Anatomy, drawn into `#birthBody` from `/api/birth`. Anatomy tells it when it shows
   and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var G = { open: '', data: null, busy: false, error: '', said: '', seq: 0, editing: '',
            incoming: null, back: '' };

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
  function route(id, fallback) {
    return (window.RouhNav && window.RouhNav.route(id)) || fallback;
  }
  /* An address inside Rouh, in a sentence: a plain press goes there in the page, Cmd-click opens a tab. */
  function inapp(text, href) {
    var a = el('a', 'bd-inline', text);
    a.href = href;
    a.setAttribute('data-inapp', '');
    a.addEventListener('click', function (e) {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (window.RouhGenesHost) window.RouhGenesHost.go(href);
      else location.href = href;
    });
    return a;
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
    if (method === 'POST') { G.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') G.busy = false;
          if (seq !== G.seq && method === 'GET') return j;
          if (j && j.name === 'Birthday') G.data = j;
          if (r.ok) {
            G.error = '';
            if (j && j.said) G.said = j.said;
            G.editing = '';
          } else {
            G.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return r.ok ? j : null;
        });
      })
      .catch(function () {
        if (method === 'POST') G.busy = false;
        G.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/birth'); }
  function post(url, body) { G.said = ''; return call('POST', url, body); }

  /* What rouh.land sent the person back with. Read once, then taken off the address, so a reload
     or a copied link does not carry it. */
  function readAddress() {
    var q;
    try { q = new URLSearchParams(location.search); } catch (err) { return; }
    var code = q.get('birth');
    var rec = q.get('recovery') || '';
    if (!code && !rec) return;
    if (code) G.incoming = { code: code.slice(0, 200), url: (q.get('registry') || '').slice(0, 500) };
    if (rec) G.back = rec.slice(0, 60);
    try { history.replaceState(history.state, '', location.pathname); } catch (err) { /* kept */ }
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('birthBody');
    if (!body || !G.open) return;
    if (G.editing && G.data) {
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = G.error || G.said;
        say.className = 'hb-say' + (G.error ? ' bad' : '');
        say.hidden = !(G.error || G.said);
      }
      return;
    }
    var opened = Array.prototype.map.call(body.querySelectorAll('details[open] > summary'),
                                          function (s) { return s.textContent; });
    body.textContent = '';
    var page = el('div', 'hb-page bd-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (G.error ? ' bad' : ''), G.error || G.said);
    say2.setAttribute('role', 'status');
    say2.hidden = !(G.error || G.said);
    page.appendChild(say2);
    if (!G.data) {
      if (!G.error) page.appendChild(el('p', 'hb-empty', 'Reading…'));
      return;
    }
    profileInto(page, G.data);
    body.querySelectorAll('details > summary').forEach(function (s) {
      if (opened.indexOf(s.textContent) >= 0) /** @type {HTMLDetailsElement} */ (s.parentElement).open = true;
    });
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }
  function help(text) { return el('p', 'settings-help', text); }
  function field(text, type, id, opts) {
    opts = opts || {};
    var label = el('label', 'hb-field' + (opts.cls ? ' ' + opts.cls : ''));
    label.appendChild(el('span', '', text));
    var input = el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    else input.rows = opts.rows || 3;
    input.id = id;
    input.setAttribute('autocomplete', opts.auto || 'off');
    if (opts.max) input.maxLength = opts.max;
    if (opts.place) input.placeholder = opts.place;
    if (opts.value) input.value = opts.value;
    input.spellcheck = false;
    label.appendChild(input);
    return { label: label, input: input };
  }
  function editing(f, name) {
    f.addEventListener('input', function () { G.editing = name; });
    f.addEventListener('focusin', function () { G.editing = name; });
  }
  function form(label, name) {
    var f = el('form', 'hb-form');
    f.setAttribute('aria-label', label);
    f.setAttribute('autocomplete', 'off');
    editing(f, name);
    return f;
  }
  function actions(f, label, cls) {
    var acts = el('div', 'hb-actions');
    var go = el('button', 'ctl small ' + (cls || 'primary'), G.busy ? 'Working…' : label);
    go.type = 'submit';
    go.disabled = G.busy;
    acts.appendChild(go);
    f.appendChild(acts);
    return acts;
  }
  /* ---- Rouh profile ---- */

  function profileInto(page, d) {
    if (d.recovering) page.appendChild(waitingCard(d));
    if (!d.born) { free(page, d); return; }
    var r = d.rouh;
    page.appendChild(nameCard(d, r));
    page.appendChild(nicknameCard(d, r));
    page.appendChild(standingCard(d, r));
  }

  /* A machine waiting on rouh.land to say which Rouh it is (a move begun and not come back). */
  function waitingCard(d) {
    var s = card('Waiting on rouh.land', '', 'bd-alert');
    s.appendChild(el('p', 'bd-lead', (d.recovering && d.recovering.said) || 'Waiting on rouh.land.'));
    return s;
  }

  /* A free Rouh: no name, no keys. What people call it, and how it gets its birth and name. */
  function free(page, d) {
    var who = d.nickname || 'Rouh';
    var s = card('', '', 'bd-hero');
    s.querySelector('.hb-h').remove();
    s.appendChild(el('h3', 'bd-name', who));
    s.appendChild(el('p', 'bd-sub', 'A free Rouh'));
    page.appendChild(s);
    page.appendChild(nicknameCard(d, null));
    if (G.incoming && d.admin) { page.appendChild(incomingCard(d)); return; }
    var st = card('rouh.land', '', 'bd-reg');
    var p = el('p', 'settings-help bd-standing');
    p.appendChild(document.createTextNode('A free Rouh. It works fine without rouh.land. Connecting it, on '));
    p.appendChild(inapp('Your profile', route('your-profile', '/anatomy/rouh-land/your-profile')));
    p.appendChild(document.createTextNode(', gives it its birth and its own name.'));
    st.appendChild(p);
    page.appendChild(st);
  }

  function incomingCard(d) {
    var s = card('rouh.land is ready', '', 'bd-incoming');
    s.appendChild(help('You came back from rouh.land. Connecting now is its birth: rouh.land gives it its name. ' +
      'Never your name goes there.'));
    var url = G.incoming.url || d.defaults.url;
    if (url && url !== d.defaults.url) {
      s.appendChild(el('p', 'bd-warn', 'You came back from ' + url + ', not rouh.land itself. Go on only if you set that up yourself.'));
    }
    var acts = el('div', 'hb-actions');
    acts.appendChild(button(G.busy ? 'Working…' : 'Connect it to rouh.land', 'primary', function () {
      post('/api/birth/born', { code: G.incoming.code, url: G.incoming.url }).then(function (j) {
        if (j && j.ok) G.incoming = null;
      });
    }));
    s.appendChild(acts);
    return s;
  }

  function nameCard(d, r) {
    var s = card('', '', 'bd-hero');
    s.querySelector('.hb-h').remove();
    s.appendChild(el('h3', 'bd-name', r.name));
    var sub = 'Born ' + r.born_words;
    if (r.retro && r.life_began_words) sub += ', after running since ' + r.life_began_words;
    s.appendChild(el('p', 'bd-sub', sub));
    if (r.second_name) {
      var sn = el('p', 'bd-second');
      sn.appendChild(el('span', 'bd-second-name', r.second_name));
      sn.appendChild(document.createTextNode(' · its second name, given by itself ' + r.second_name_words +
        (r.second_name_why ? ': ' + r.second_name_why : '')));
      s.appendChild(sn);
    }
    s.appendChild(help((r.named_by_land ? 'rouh.land gave it its name at its birth.' : 'It was given its name at its birth.') +
      ' Nobody chose it, and it never changes.'));
    return s;
  }

  function nicknameCard(d, r) {
    var s = card('What you call it', 'only you see this', 'bd-nick');
    s.appendChild(help(r ? 'Its human names. Everyone else, other Rouhs and the Gene Pool see ' + r.name + '.'
      : 'Its human names. They are yours: everyone else knows it as Rouh.'));
    var f = form('What you call your Rouh', 'nick');
    var names = d.human_names || {};
    var first = field('First name', 'text', 'bdFirst', { value: names.first, max: 40, place: 'none' });
    var last = field('Last name', 'text', 'bdLast', { value: names.last, max: 40, place: 'none' });
    var n = field('Nickname', 'text', 'bdNickname', { value: d.nickname, max: 40, place: 'none', cls: 'wide' });
    f.appendChild(first.label);
    f.appendChild(last.label);
    f.appendChild(n.label);
    // Petar, 4 November 2026: so nobody writes Rouh in the box. The server keeps "Rouh" as no nickname.
    var why = help('Your Rouh answers to “Rouh” by default. If you wish to give it another nickname as well, ' +
      'feel free: it answers to both.');
    why.classList.add('bd-nick-help');
    why.id = 'bdNicknameHelp';
    n.input.setAttribute('aria-describedby', why.id);
    f.appendChild(why);
    actions(f, d.nickname || names.first || names.last ? 'Save' : 'Save the names');
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      G.editing = '';
      post('/api/birth/nickname', { first: first.input.value, last: last.input.value, nickname: n.input.value });
    });
    s.appendChild(f);
    return s;
  }

  /* One plain line about rouh.land (`birth.standing`), and the one thing to do when something is
     wrong. Back from rouh.land with a code, the press that registers it with that code. */
  function standingCard(d, r) {
    var st = d.standing || {};
    var wrong = st.kind === 'stopped';
    var s = card('rouh.land', '', 'bd-reg' + (wrong ? ' bd-alert' : ''));
    var line = el('p', wrong ? 'bd-lead' : 'settings-help bd-standing', st.said || '');
    if (wrong) line.setAttribute('role', 'alert');
    s.appendChild(line);
    if (!d.admin) return s;
    var acts = el('div', 'hb-actions');
    if (G.incoming && !(r.connected && r.account)) {
      s.appendChild(help('You came back from rouh.land: register ' + r.name + ' there now, under the name it has.'));
      acts.appendChild(button(G.busy ? 'Working…' : 'Register ' + r.name, 'primary', function () {
        post('/api/birth/connect', { code: G.incoming.code, url: G.incoming.url }).then(function (j) {
          if (j && j.ok) G.incoming = null;
        });
      }));
      s.appendChild(acts);
    }
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (G.open) return;
    G.open = 'profile';
    G.said = '';
    G.editing = '';
    readAddress();
    draw();
    load().then(function () {
      if (G.back) {
        var id = G.back;
        G.back = '';
        post('/api/birth/recover/started', { request: id });
      }
    });
  }

  function hiddenNow() {
    G.open = '';
    G.editing = '';
    var body = $('birthBody');
    if (body) { body.querySelectorAll('input, textarea').forEach(function (i) { i.value = ''; }); body.textContent = ''; }
  }

  window.RouhBirth = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
