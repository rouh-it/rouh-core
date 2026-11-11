/* Anatomy, Your Rouh, at /anatomy/your-rouh (`rouh/birth.py`, `rouh/web/birth.py`,
   `rouh/landaccount.py`): one page about the Rouh itself. Rouh profile (Meta, Birthday before 4
   November 2026), Your profile's connecting and Connections, Phone until 7 November 2026, when
   task 141, step 141-17 gave each journey one home: "if it is about the Rouh, it is on Your Rouh".

   From the top, the most frequent question first ("is my Rouh connected and fine?"):
   - a headline sentence naming the Rouh and its state, and three tiles, Name, rouh.land and URL,
     each a press away from its card;
   - only when something is wrong, one sentence and the one thing to do (Needs you);
   - the rouh.land card: what connecting gives, sends and keeps private, and the one action that
     fits - Connect to rouh.land, Connect now (back from rouh.land with a code, with a warning when
     the code came from another site), Connect again, or Disconnect… with a sheet that says what it
     keeps and what stops; the Gene Pool in one line, whose controls stay in Evolution;
   - Your Rouh's URL, the template's card that phonepage.js draws, with its (i);
   - Name: the official name (fixed, from rouh.land), what you call it (yours alone) and the owner,
     shown apart and never sent;
   - What others can see: its public card on rouh.land, and what is never public.

   A member who is not an administrator sees every state, with no buttons, and who can change it.
   No key, key id, registry id or recovery words anywhere (Petar, 4 and 7 November 2026).

   Drawn into `#birthBody` (down to the rouh.land card) and `#yrAfter` (Name, What others can see)
   from /api/birth and /api/rouh-land/account. rouh.land sends the person back here with a code
   (`?birth=`, read once and taken off the address; `addressing.ROUH_LAND_RETURN`). Anatomy tells it
   when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var G = { open: false, data: null, land: null, phone: null, busy: false, error: '', checked: false,
            editing: false, incoming: null, back: '', seq: 0, toastTimer: 0 };

  var ICON = {
    warn: '<svg class="yr-ic" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" ' +
          'aria-hidden="true"><path d="M12 3l9.5 17h-19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.3" r=".6" fill="currentColor"/></svg>',
    bad: '<svg class="yr-ic" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" ' +
         'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/></svg>',
    wait: '<svg class="yr-ic" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" ' +
          'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.4 2.1"/></svg>',
    tick: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" ' +
          'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    out: '<svg class="yr-out" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" ' +
         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/>' +
         '<path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    globe: '<svg class="yr-globe" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" ' +
           'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>' +
           '<path d="M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5s1.2-6.2 3.6-8.5z"/></svg>'
  };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, label) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (label) b.setAttribute('aria-label', label);
    b.disabled = G.busy;
    b.addEventListener('click', act);
    return b;
  }
  function help(text) { return el('p', 'settings-help', text); }
  /** An address inside Rouh: a plain press goes there in the page, Cmd-click opens a tab. */
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
  function outLink(text, href, cls) {
    var a = el('a', 'ctl small ' + (cls || 'yr-quiet'), text + ' ');
    a.insertAdjacentHTML('beforeend', ICON.out);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.setAttribute('aria-label', text + ' (opens rouh.land in a new tab)');
    return a;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function zone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function host(url) { return String(url || '').replace(/^https?:\/\//, '').replace(/\/.*$/, ''); }

  /** @param {string} method @param {string} url @param {any} [body] */
  function call(method, url, body) {
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': zone(), 'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return { ok: false, j: {} }; }
        return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j || {} }; });
      })
      .catch(function () { return { ok: false, j: { error: 'Rouh could not be reached. Check the connection and try again.' } }; });
  }

  function load() {
    var seq = ++G.seq;
    return Promise.all([call('GET', '/api/birth'), call('GET', '/api/rouh-land/account')]).then(function (got) {
      if (seq !== G.seq) return;
      if (got[0].ok) G.data = got[0].j; else G.error = got[0].j.error || 'Your Rouh could not be read.';
      if (got[1].ok) G.land = got[1].j;
      draw();
      // The page's own ask of rouh.land, once as it opens; said only when something is wrong.
      if (G.land && G.land.check_due && !G.checked) { G.checked = true; check(false); }
    });
  }

  /** @param {boolean} retry pressed beside a problem, so asked whatever the last ask was */
  function check(retry) {
    if (retry) { G.busy = true; draw(); }
    return call('POST', '/api/rouh-land/account/check', { retry: !!retry }).then(function (got) {
      G.busy = false;
      if (got.ok && got.j && 'connected' in got.j) {
        G.land = got.j;
        if (retry) toast(got.j.problem ? 'Asked rouh.land: still no answer.' : 'Asked rouh.land: it answered.');
        return call('GET', '/api/birth').then(function (b) { if (b.ok) G.data = b.j; draw(); });
      }
      if (retry) G.error = (got.j && got.j.error) || 'rouh.land could not be asked.';
      draw();
    });
  }

  /** A press that changes something: busy while it runs, then read again. */
  function act(url, body, said) {
    G.busy = true; G.error = ''; draw();
    return call('POST', url, body).then(function (got) {
      G.busy = false;
      if (!got.ok) { G.error = got.j.error || 'That did not work. Nothing was changed.'; draw(); return null; }
      if (said) toast(typeof said === 'function' ? said(got.j) : said);
      return load().then(function () { return got.j; });
    });
  }

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

  function toast(text) {
    var t = $('yrToast');
    if (!t) return;
    t.textContent = text;
    t.hidden = false;
    requestAnimationFrame(function () { t.classList.add('on'); });
    clearTimeout(G.toastTimer);
    G.toastTimer = window.setTimeout(function () {
      t.classList.remove('on');
      window.setTimeout(function () { t.hidden = true; }, 220);
    }, 5000);
  }

  /* ---- how this Rouh stands ---- */

  /** One word for the whole state, as the design names them: free, code, connected, unreachable,
      stopped, disconnected. */
  function kind() {
    var d = G.data;
    if (!d) return '';
    if (G.incoming && d.admin) return 'code';
    if (!d.born) return 'free';
    var r = d.rouh || {};
    if ((d.standing || {}).kind === 'stopped') return 'stopped';
    if (!r.connected) return r.disconnected_words ? 'disconnected' : 'free';
    var p = G.land && G.land.problem;
    if (p && p.kind !== 'key') return 'unreachable';
    return 'connected';
  }
  function named() { return !!(G.data && G.data.born && G.data.rouh); }
  function nameNow() {
    var d = G.data;
    if (named()) return d.rouh.name;
    return d.nickname || 'Rouh';
  }
  function owner() { return (G.data && G.data.owner && G.data.owner.name) || 'its owner'; }
  function phoneOn() { return !!(G.phone && G.phone.hostname && G.phone.on); }
  /** In the owner's rouh.land account, not only registered there. */
  function inAccount() { return !!(G.land && G.land.connected); }
  function doorHref() {
    var base = (G.land && G.land.door) || '';
    if (!base) return '';
    var email = (G.land && G.land.sign_in_email) || (G.data && G.data.connect_email) || '';
    return base + (base.indexOf('?') < 0 ? '?' : '&') + 'rouh=' + encodeURIComponent(location.origin) +
      (email ? '&email=' + encodeURIComponent(email) : '');
  }

  /* ---- drawing ---- */

  function draw() {
    var top = $('birthBody'), after = $('yrAfter');
    if (!top || !after || !G.open) return;
    if (G.editing) return;   // what is being typed is not drawn over (Save or Cancel draws again)
    top.textContent = '';
    after.textContent = '';
    var page = el('div', 'hb-page yr-top');
    top.appendChild(page);
    if (G.error) {
      var e = el('p', 'hb-say bad', G.error);
      e.setAttribute('role', 'alert');
      page.appendChild(e);
    }
    var d = G.data;
    if (!d) { if (!G.error) page.appendChild(el('p', 'hb-empty', 'Reading…')); return; }
    var k = kind();
    if (window.RouhPhone && window.RouhPhone.land) window.RouhPhone.land({ kind: k, admin: !!d.admin, owner: owner() });
    page.appendChild(headline(k));
    var needs = needsBox(k);
    if (needs) page.appendChild(needs);
    page.appendChild(tiles(k));
    var jump = el('p', 'yr-jump');
    var seen = el('a', 'bd-inline', 'What others can see about it');
    seen.href = '#yrSeen';
    seen.addEventListener('click', function (ev) { ev.preventDefault(); scrollTo('yrSeen'); });
    jump.appendChild(seen);
    page.appendChild(jump);
    page.appendChild(landCard(k));
    var rest = el('div', 'hb-page');
    after.appendChild(rest);
    rest.appendChild(nameCard(k));
    rest.appendChild(seenCard(k));
  }

  function scrollTo(id) {
    var t = $(id);
    if (!t) return;
    t.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    var h = t.querySelector('h4');
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
  }

  function headline(k) {
    var p = el('p', 'yr-headline');
    var nm = nameNow();
    function b(text) { p.appendChild(el('strong', 'yr-break', text)); }
    function t(text) { p.appendChild(document.createTextNode(text)); }
    var kind = (G.data && G.data.independent) || 'Independent Rouh';
    if (k === 'connected') {
      if (named()) p.appendChild(el('strong', 'yr-break rouh-name', nm)); else b(nm);
      if (!inAccount()) t(' is registered with rouh.land, and not yet in your rouh.land account.');
      else t(' is connected to rouh.land' + (phoneOn() ? ' and you can reach it from your phone.'
        : G.phone && G.phone.relay === false ? '.' : '. Its URL is off.'));
    } else if (k === 'free') {
      // Never "free" as this kind's name: the rouh.land account is free too (task 176).
      if (named()) { p.appendChild(el('strong', 'yr-break rouh-name', nm)); b(': ' + kind + '.'); }
      else b(kind + '.');
      t(' It works fully here without rouh.land. Connect it to get ' + (named() ? 'its own URL.' : 'its official name and its own URL.'));
    } else if (k === 'code') {
      if (foreign()) { b('A site that is not rouh.land sent you back with a code.'); t(' Check it before you connect.'); }
      else { b('rouh.land sent you back.'); t(named() ? ' One press connects ' + nm + ' to your account.'
        : ' One press connects this Rouh and gives it its official name.'); }
    } else if (k === 'unreachable') {
      b('Can’t reach rouh.land right now.'); t(' ' + nm + ' keeps working here as before.');
    } else if (k === 'stopped') {
      b('rouh.land stopped ' + nm + '.'); t(' It keeps working here; its URL and Gene Pool sharing are off.');
    } else if (k === 'disconnected') {
      b(nm + ' is disconnected from rouh.land.'); t(' It keeps its official name and works here as before.');
    }
    return p;
  }

  function foreign() {
    var d = G.data;
    var url = G.incoming && G.incoming.url;
    return !!(url && d && d.defaults && host(url) !== host(d.defaults.url));
  }

  function needsBox(k) {
    var d = G.data;
    var box;
    if (k === 'unreachable') {
      box = el('div', 'yr-needs warn');
      box.setAttribute('role', 'status');
      box.innerHTML = ICON.warn;
      var p = (G.land && G.land.problem) || {};
      var w = el('div', 'yr-needs-words');
      w.appendChild(el('p', 'yr-needs-t', p.kind === 'refused' ? 'rouh.land did not accept the last check.' : 'Can’t reach rouh.land right now.'));
      w.appendChild(el('p', '', p.kind === 'refused' ? p.said : 'It tries again by itself. Nothing here stops working.'));
      box.appendChild(w);
      if (d.admin) {
        var a = el('div', 'yr-needs-acts');
        a.appendChild(button(G.busy ? 'Asking rouh.land…' : 'Try again', 'primary', function () { check(true); }));
        box.appendChild(a);
      }
      return box;
    }
    if (k === 'stopped') {
      box = el('div', 'yr-needs bad');
      box.setAttribute('role', 'alert');
      box.innerHTML = ICON.bad;
      var w2 = el('div', 'yr-needs-words');
      var when = (d.rouh && d.rouh.key_dead_words) || '';
      w2.appendChild(el('p', 'yr-needs-t', 'rouh.land stopped this Rouh' + (when ? ' ' + when : '') + '.'));
      w2.appendChild(el('p', '', 'That is done from your rouh.land account, for example when a machine is lost. ' +
        'Open your Rouhs there to see why and to start it again.'));
      box.appendChild(w2);
      if (d.admin && G.land && G.land.account_url) {
        var a2 = el('div', 'yr-needs-acts');
        a2.appendChild(outLink('Open your Rouhs on rouh.land', G.land.account_url));
        box.appendChild(a2);
      }
      return box;
    }
    if (d.recovering || (d.rouh && d.rouh.pending)) {
      box = el('div', 'yr-needs wait');
      box.setAttribute('role', 'status');
      box.innerHTML = ICON.wait;
      var w3 = el('div', 'yr-needs-words');
      w3.appendChild(el('p', 'yr-needs-t', 'Something waits on rouh.land.'));
      w3.appendChild(el('p', '', (d.recovering && d.recovering.said) || (d.rouh.pending && d.rouh.pending.said) || 'It is asked after by itself.'));
      box.appendChild(w3);
      return box;
    }
    return null;
  }

  function tile(key, value, sub, cls, target) {
    var a = el('a', 'yr-tile ' + cls);
    a.href = '#' + target;
    a.appendChild(el('span', 'yr-tile-k', key));
    var v = el('span', 'yr-tile-v');
    var dot = el('span', 'yr-dot');
    dot.setAttribute('aria-hidden', 'true');
    v.appendChild(dot);
    v.appendChild(document.createTextNode(value));
    a.appendChild(v);
    a.appendChild(el('span', 'yr-tile-s', sub));
    a.addEventListener('click', function (e) { e.preventDefault(); scrollTo(target); });
    var li = el('li');
    li.appendChild(a);
    return li;
  }

  function tiles(k) {
    var d = G.data;
    var r = d.rouh || {};
    var ul = el('ul', 'yr-tiles');
    ul.setAttribute('aria-label', 'How it stands');
    ul.appendChild(named()
      ? tile('Name', r.name, 'Official, never changes', 'st-good rouh-named', 'yrName')
      : tile('Name', 'No official name yet', 'Comes with connecting', 'st-none', 'yrName'));
    var land = {
      connected: inAccount() ? ['Connected', r.checked_words ? 'Checked ' + r.checked_words : 'It checks by itself', 'st-good']
        : ['Registered', 'Not in your account yet', 'st-none'],
      free: [(d.independent_word || 'Independent'), 'Not connected, works fine', 'st-none'],
      code: ['Ready to connect', 'One press left', 'st-none'],
      unreachable: ['Can’t reach', r.checked_words ? 'Last answered ' + r.checked_words : 'It tries again by itself', 'st-warn'],
      stopped: ['Stopped', r.key_dead_words ? 'Since ' + r.key_dead_words : 'By rouh.land', 'st-bad'],
      disconnected: ['Disconnected', r.disconnected_words ? 'Since ' + r.disconnected_words : 'Connect it again any time', 'st-none'],
    }[k] || ['', '', 'st-none'];
    ul.appendChild(tile('rouh.land', land[0], land[1], land[2], 'yrLand'));
    var ph = G.phone;
    var url = k === 'stopped' ? ['Off', 'Off while stopped', 'st-none']
      : k === 'disconnected' ? ['Off', 'Its URL waits for it', 'st-none']
      : k === 'free' || k === 'code' ? ['None', 'Comes with connecting', 'st-none']
      : !ph ? ['…', 'Reading', 'st-none']
      : ph.relay === false ? ['None', 'No relay here', 'st-none']
      : !ph.hostname ? ['None yet', 'On its way from rouh.land', 'st-none']
      : ph.on ? ['On', host(ph.address), ph.state === 'connected' ? 'st-good' : 'st-warn']
      : ['Off', 'Nothing open to the internet', 'st-none'];
    ul.appendChild(tile('URL', url[0], url[1], url[2], 'yrUrl'));
    return ul;
  }

  function card(id, title, where) {
    var s = el('section', 'setting-card hb-card yr-card');
    s.id = id;
    var h = el('h4', 'hb-h', title);
    h.id = id + 'H';
    s.setAttribute('aria-labelledby', h.id);
    if (where) {
      var w = el('span', 'yr-where');
      w.innerHTML = ICON.globe;
      w.appendChild(document.createTextNode(where));
      h.appendChild(w);
    }
    s.appendChild(h);
    return s;
  }

  function three(cols) {
    var box = el('div', 'yr-three');
    cols.forEach(function (c) {
      var col = el('div');
      col.appendChild(el('p', 'yr-three-h', c[0]));
      var ul = el('ul');
      c[1].forEach(function (x) { ul.appendChild(el('li', '', x)); });
      col.appendChild(ul);
      box.appendChild(col);
    });
    return box;
  }

  function memberLine(s) { s.appendChild(el('p', 'yr-member', 'Only ' + owner() + ', who owns this Rouh, can change this.')); }

  function poolLine(s) {
    var pool = G.data.pool || {};
    var p = el('p', 'settings-help');
    p.appendChild(document.createTextNode('Gene Pool: ' + (pool.joined
      ? 'sharing out is ' + pool.outgoing + ', taking in is ' + pool.incoming + '. '
      : 'not joined yet; it joins by itself, exchanging nothing. ')));
    p.appendChild(inapp('Choose what it shares, in Evolution, Gene Pool', pool.route || '/evolution/pool'));
    p.appendChild(document.createTextNode('.'));
    s.appendChild(p);
  }

  function landCard(k) {
    var d = G.data;
    var r = d.rouh || {};
    var s = card('yrLand', 'rouh.land', 'talks to rouh.land');
    var lede = el('p', 'yr-lede');
    function b(text) { lede.appendChild(el('strong', null, text)); }
    function t(text) { lede.appendChild(document.createTextNode(text)); }
    var email = r.account_email || (G.land && G.land.sign_in_email) || '';
    if (k === 'connected' && inAccount()) {
      b('Connected'); t(' to the rouh.land account of ' + (d.owner && d.owner.you ? 'you' + (email ? ' (' + email + ')' : '') : owner()) +
        '.' + (r.checked_words ? ' Last checked ' + r.checked_words + '; it checks by itself.' : ' It checks by itself.'));
    } else if (k === 'connected') {
      b('Registered'); t(' with rouh.land, but not in your rouh.land account yet. Add it, and one email signs you in to both.');
    } else if (k === 'free') {
      b('Not connected.'); t(' ' + (d.independent || 'Independent Rouh') + ': it works fully without rouh.land.');
    } else if (k === 'code') {
      b('Ready to connect.'); t(' You signed up or in on rouh.land, and it sent you back with a code.');
    } else if (k === 'unreachable') {
      b('Connected, but can’t reach rouh.land just now.');
      if (r.checked_words) t(' It last answered ' + r.checked_words + '.');
    } else if (k === 'stopped') {
      b('Stopped by rouh.land'); t((r.key_dead_words ? ' ' + r.key_dead_words : '') + '. It still works here.');
    } else if (k === 'disconnected') {
      b('Disconnected'); t((r.disconnected_words ? ' ' + r.disconnected_words : '') + '. Your rouh.land account is still there.');
    }
    s.appendChild(lede);

    if (k === 'free' || k === 'code' || k === 'disconnected') {
      s.appendChild(three([
        ['Connecting gives it', (k === 'disconnected' ? ['Its URL back']
          : named() ? ['Its own URL, to reach it from your phone']
          : ['Its official name, for good', 'Its own URL, to reach it from your phone'])
          .concat(['Sharing pages and tasks, like Google Drive: by email, read or edit, or by link',
            'The Gene Pool, sharing only what you choose', 'Security fixes and the model price list'])],
        ['It sends rouh.land', ['A new key that proves it is this Rouh', 'Your email, to sign you in']],
        ['It stays private', ['Your files, mail and chats', 'Every call to a model', 'What you call it, and your name']],
      ]));
    }
    if (k === 'connected' || k === 'unreachable') poolLine(s);
    if (!d.admin) { memberLine(s); return s; }

    var acts = el('div', 'hb-actions');
    var href = doorHref();
    if (k === 'free' || k === 'disconnected' || (k === 'connected' && !inAccount())) {
      if (href) {
        var go = el('a', 'ctl small primary', k === 'free' ? 'Connect to rouh.land'
          : k === 'disconnected' ? 'Connect again' : 'Add it to your rouh.land account');
        go.href = href;
        acts.appendChild(go);
        s.appendChild(acts);
        s.appendChild(help(k === 'disconnected' || named()
          ? 'Opens rouh.land here. It brings you back with a code, and ' + nameNow() + ' comes back under the same official name.'
          : 'Opens rouh.land here. New there? It makes your account with the same email. Connecting gives it a public card ' +
            'with its official name and birthday; nothing about you.'));
      }
      if (k === 'connected') {
        var off0 = el('div', 'hb-actions');
        off0.appendChild(button('Disconnect…', 'yr-quiet', openDisconnect));
        s.appendChild(off0);
      }
    } else if (k === 'code') {
      if (foreign()) {
        var warn = el('p', 'yr-warnline', 'This code came from ' + host(G.incoming.url) + ', not rouh.land. ' +
          'Connect only if you set that site up yourself.');
        warn.setAttribute('role', 'alert');
        s.appendChild(warn);
      }
      acts.appendChild(button(G.busy ? 'Connecting…' : 'Connect now', foreign() ? '' : 'primary', function () {
        var inc = G.incoming;
        act(d.born ? '/api/birth/connect' : '/api/birth/born', { code: inc.code, url: inc.url }, function (j) {
          return j.said || 'Connected.';
        }).then(function (j) { if (j && j.ok !== false) { G.incoming = null; draw(); } });
      }));
      acts.appendChild(button('Cancel', 'yr-quiet', function () {
        G.incoming = null; draw(); toast('Not connected. Nothing was sent.');
      }));
      s.appendChild(acts);
      s.appendChild(help('After this, rouh.land shows a public card for it: its official name, its birthday and the genes ' +
        'you choose to share. Nothing about you. Its URL stays off until you turn it on.'));
    } else if (k === 'connected' || k === 'unreachable') {
      acts.appendChild(button('Disconnect…', 'yr-quiet', openDisconnect));
      s.appendChild(acts);
    } else if (k === 'stopped') {
      s.appendChild(help('Nothing to press here: rouh.land decides when it starts again. Use the link above.'));
    }
    return s;
  }

  function nameCard(k) {
    var d = G.data;
    var r = d.rouh || {};
    var s = card('yrName', 'Name');
    var nm = nameNow();
    s.appendChild(el('p', 'bd-name' + (named() ? ' rouh-name' : ' yr-free'), nm));
    if (named()) {
      var sub = 'Born ' + r.born_words;
      if (r.retro && r.life_began_words) sub += ', after running since ' + r.life_began_words;
      s.appendChild(el('p', 'bd-sub', sub + '.'));
      if (r.second_name) {
        var sn = el('p', 'bd-second');
        sn.appendChild(el('span', 'bd-second-name', r.second_name));
        sn.appendChild(document.createTextNode(' · its second name, given by itself ' + r.second_name_words +
          (r.second_name_why ? ': ' + r.second_name_why : '')));
        s.appendChild(sn);
      }
    } else {
      s.appendChild(el('p', 'bd-sub', 'No official name yet. rouh.land gives it one when you connect it; until then it ' +
        'answers to Rouh' + (d.nickname ? ' and ' + d.nickname : '') + '.'));
    }
    var dl = el('dl', 'yr-rows');
    function row(term, value, helpText, extra) {
      var div = el('div');
      div.appendChild(el('dt', null, term));
      var dd = el('dd');
      if (term === 'Official name' && named()) dd.appendChild(el('span', 'rouh-name', value));
      else dd.appendChild(document.createTextNode(value));
      if (extra) dd.appendChild(extra);
      if (helpText) dd.appendChild(el('p', 'settings-help', helpText));
      div.appendChild(dd);
      dl.appendChild(div);
      return dd;
    }
    if (named()) {
      row('Official name', r.name, (r.named_by_land ? 'rouh.land gave it at its birth.' : 'It was given its name at its birth.') +
        ' Nobody chose it, and nobody can change it. Other Rouhs and the Gene Pool know it by this name.',
        el('span', 'yr-lock', 'never changes'));
    } else {
      row('Official name', 'None yet', 'Given by rouh.land when this Rouh connects. You don’t choose it.');
    }
    if (d.owner && d.owner.name) {
      row('Owner', d.owner.name + (d.owner.you ? ' (you)' : ''),
        'Shown only here. Never part of its name, never sent to rouh.land or the Gene Pool.');
    }
    var names = d.human_names || {};
    var called = [names.first, names.last].filter(Boolean).join(' ');
    var said = called || d.nickname ? [called, d.nickname ? '“' + d.nickname + '”' : ''].filter(Boolean).join(', ')
      : 'Rouh (the default)';
    var dd = row('What you call it', said, 'Only you see this. Each person here has their own. It always answers to Rouh too.');
    var ea = el('div', 'hb-actions');
    ea.appendChild(button('Change what you call it', '', function () { editNames(s, dd); }));
    dd.appendChild(ea);
    s.appendChild(dl);
    return s;
  }

  function editNames(s, dd) {
    var d = G.data;
    var names = d.human_names || {};
    G.editing = true;
    var acts = dd.querySelector('.hb-actions');
    if (acts) acts.remove();
    var f = el('form', 'yr-nick');
    f.setAttribute('aria-label', 'What you call your Rouh');
    f.setAttribute('autocomplete', 'off');
    var boxes = [['yrFirst', 'First name', names.first], ['yrLast', 'Last name', names.last], ['yrNickname', 'Nickname', d.nickname]]
      .map(function (x) {
        var fld = el('div', 'field');
        var lab = el('label', null, x[1]);
        lab.htmlFor = x[0];
        var input = el('input');
        input.id = x[0];
        input.type = 'text';
        input.maxLength = 40;
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.value = x[2] || '';
        fld.appendChild(lab);
        fld.appendChild(input);
        f.appendChild(fld);
        return input;
      });
    f.appendChild(help('Leave them empty to call it Rouh. Typing “Rouh” as a nickname is the same as none.'));
    var fa = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save');
    save.type = 'submit';
    fa.appendChild(save);
    var cancel = el('button', 'ctl small yr-quiet', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', function () { G.editing = false; draw(); });
    fa.appendChild(cancel);
    f.appendChild(fa);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      G.editing = false;
      act('/api/birth/nickname', { first: boxes[0].value, last: boxes[1].value, nickname: boxes[2].value },
          'Saved what you call it.');
    });
    s.appendChild(f);
    boxes[0].focus();
  }

  function seenCard(k) {
    var d = G.data;
    var r = d.rouh || {};
    var s = card('yrSeen', 'What others can see');
    var wrap = el('div', 'yr-public');
    var pub = el('div', 'yr-pubcard');
    if (named() && r.connected) {
      pub.appendChild(el('p', 'yr-pub-k', 'Its public card on rouh.land (preview)'));
      pub.appendChild(el('p', 'yr-pub-name rouh-name', r.name));
      var ul = el('ul');
      ul.appendChild(el('li', '', 'Born ' + r.born_words));
      ul.appendChild(el('li', '', 'The genes you choose to share'));
      pub.appendChild(ul);
    } else if (k === 'disconnected') {
      pub.appendChild(el('p', 'yr-pub-k', 'Its public card on rouh.land'));
      pub.appendChild(el('p', '', 'Hidden while disconnected. Genes it shared before stay in the Gene Pool under its official name.'));
    } else {
      pub.appendChild(el('p', 'yr-pub-k', 'Its public card on rouh.land'));
      pub.appendChild(el('p', '', 'None. This ' + (d.independent || 'Independent Rouh') + ' is not on rouh.land at all.'));
    }
    wrap.appendChild(pub);
    var never = el('div');
    never.appendChild(el('p', 'yr-pub-k', 'Never public'));
    var list = el('ul', 'yr-never');
    ['Your name, email or anything about you', 'What you call it', 'Your files, mail, chats and what it does'].forEach(function (x) {
      var li = el('li');
      li.innerHTML = ICON.tick;
      li.appendChild(document.createTextNode(x));
      list.appendChild(li);
    });
    never.appendChild(list);
    wrap.appendChild(never);
    s.appendChild(wrap);
    s.appendChild(help(k === 'free' || k === 'code'
      ? 'Connecting gives it a public card: its official name and birthday. Genes join that card only when you share them, one at a time.'
      : 'Beyond this card, something becomes public only when you share a gene, one at a time, in Evolution, Gene Pool.'));
    return s;
  }

  /* ---- the Disconnect sheet ---- */

  function openDisconnect() {
    var dlg = /** @type {HTMLDialogElement | null} */ ($('yrSheet'));
    if (!dlg) return;
    var nm = nameNow();
    var email = (G.land && G.land.sign_in_email) || 'your email';
    dlg.textContent = '';
    var h = el('h2', 'yr-sheet-h', 'Disconnect ' + nm + ' from rouh.land?');
    h.id = 'yrSheetH';
    dlg.appendChild(h);
    dlg.appendChild(el('p', 'yr-lede', 'It keeps working here. You can connect it again any time.'));
    dlg.appendChild(three([
      ['It keeps', ['Its official name, ' + nm, 'Everything on this machine', 'Your sign-in with ' + email]],
      ['It stops', ['Its URL: phones signed in can’t reach it', 'Gene Pool sharing, and new genes from there',
                    'Security fixes and the model price list from rouh.land']],
      ['On rouh.land', ['Your account stays', 'Its URL is kept for it', 'Genes it shared stay, under its official name']],
    ]));
    var acts = el('div', 'hb-actions');
    var go = el('button', 'ctl small danger', 'Disconnect ' + nm);
    go.type = 'button';
    go.addEventListener('click', function () {
      dlg.close();
      act('/api/birth/disconnect', {}, 'Disconnected from rouh.land.').then(function () {
        if (window.RouhPhone) window.RouhPhone.reload();
      });
    });
    var keep = el('button', 'ctl small yr-quiet', 'Keep connected');
    keep.type = 'button';
    keep.addEventListener('click', function () { dlg.close(); });
    acts.appendChild(go);
    acts.appendChild(keep);
    dlg.appendChild(acts);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    dlg.showModal();
    keep.focus();
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (G.open) { load(); return; }
    G.open = true;
    G.error = '';
    G.editing = false;
    G.checked = false;
    readAddress();
    draw();
    load().then(function () {
      if (G.back) {
        var id = G.back;
        G.back = '';
        act('/api/birth/recover/started', { request: id });
      }
    });
  }

  function hiddenNow() {
    G.open = false;
    G.editing = false;
    var dlg = /** @type {HTMLDialogElement | null} */ ($('yrSheet'));
    if (dlg && dlg.open) dlg.close();
    var top = $('birthBody'), after = $('yrAfter');
    if (top) top.textContent = '';
    if (after) after.textContent = '';
  }

  /** What the URL card read (`phonepage.js`): the headline and the URL tile follow it. */
  function phoneNow(data) {
    var before = JSON.stringify(G.phone && [G.phone.on, G.phone.hostname, G.phone.state, G.phone.relay]);
    G.phone = data;
    if (before !== JSON.stringify(data && [data.on, data.hostname, data.state, data.relay])) draw();
  }

  window.RouhBirth = { shown: shownNow, hidden: hiddenNow, reload: load, phone: phoneNow, toast: toast };
})();
