/* Anatomy, You, Your account (Account until 7 November 2026, 141-17): a headline sentence, the
   email that signs you in and your passkeys (`rouh/web/signin.py`, `rouh/signin.py`); the password
   card under it is the page's own (About You's until then), and the rouh.land account card is
   landaccountpage.js's. And, on a guest's contact card, the owner's
   two ways to get that guest back in (window.RouhGuestSignIn).

   Petar, 4 November 2026: "passkey/face/touch should be extra, not default", and "if you are
   connected, one email runs both". So:

   - one email, labelled "Signs you in to this Rouh and rouh.land" when connected, or "Signs you in
     to this Rouh"; changing it while connected opens rouh.land, which this Rouh follows;
   - Add a passkey, and each passkey with Remove. A passkey added here is remembered in this browser
     (`rouh-passkeys`, the addresses only), so the sign-in page offers it first on this device and
     never has to ask the server whether an address has one;

   The Sign out form under it is the page's own, a form so it works with no script at all. */
(function () {
  'use strict';

  var S = { open: false, data: null, said: '', error: '', busy: false, editing: false };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function zone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function call(url, body) {
    var init = { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Time-Zone': zone() } };
    if (body !== undefined) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.headers['X-CSRFToken'] = csrfToken();
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || 'The server said ' + r.status + '.');
        return j;
      });
    });
  }
  function b64u(buf) {
    var s = '', b = new Uint8Array(buf);
    for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function unb64u(t) {
    t = t.replace(/-/g, '+').replace(/_/g, '/');
    while (t.length % 4) t += '=';
    var s = atob(t), out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out.buffer;
  }
  function held() {
    try { return JSON.parse(localStorage.getItem('rouh-passkeys') || '[]') || []; } catch (e) { return []; }
  }
  function remember(email) {
    if (!email) return;
    var list = held();
    if (list.indexOf(email) < 0) list.push(email);
    try { localStorage.setItem('rouh-passkeys', JSON.stringify(list)); } catch (e) { /* private window */ }
  }
  function forget(email) {
    try { localStorage.setItem('rouh-passkeys', JSON.stringify(held().filter(function (x) { return x !== email; }))); }
    catch (e) { /* private window */ }
  }
  function button(text, cls, act) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    b.addEventListener('click', act);
    return b;
  }

  function load() {
    return call('/api/sign-in/me').then(function (j) { S.data = j; draw(); })
      .catch(function (e) { S.error = e.message; draw(); });
  }
  function done(p) {
    S.busy = true; S.said = ''; S.error = ''; draw();
    return p.then(function (j) {
      S.busy = false;
      if (j.go) { window.open(j.go, '_blank', 'noopener'); }
      S.said = j.said || '';
      if (j.email !== undefined) S.data = j;
      draw();
      return j;
    }).catch(function (e) { S.busy = false; S.error = e.message; draw(); });
  }

  function addPasskey() {
    if (!window.PublicKeyCredential) { S.error = 'This browser cannot make passkeys.'; draw(); return; }
    S.busy = true; S.said = ''; S.error = ''; draw();
    var email = '';
    call('/api/sign-in/passkey/options', {}).then(function (o) {
      email = o.email || '';
      return navigator.credentials.create({ publicKey: {
        challenge: unb64u(o.challenge), rp: o.rp,
        user: { id: unb64u(o.user.id), name: o.user.name, displayName: o.user.displayName },
        pubKeyCredParams: o.pubKeyCredParams, timeout: o.timeout, attestation: o.attestation,
        authenticatorSelection: o.authenticatorSelection,
        excludeCredentials: o.excludeCredentials.map(function (c) { return { type: c.type, id: unb64u(c.id) }; }) } });
    }).then(function (c) {
      var name = /iPhone|iPad/.test(navigator.userAgent) ? 'iPhone or iPad' : /Mac/.test(navigator.userAgent) ? 'Mac'
        : /Android/.test(navigator.userAgent) ? 'Android' : /Windows/.test(navigator.userAgent) ? 'Windows' : 'This device';
      return call('/api/sign-in/passkey/add', { clientDataJSON: b64u(c.response.clientDataJSON),
        attestationObject: b64u(c.response.attestationObject), name: name });
    }).then(function (j) {
      remember(email);
      S.busy = false; S.said = j.said || ''; S.data = j; draw();
    }).catch(function (e) {
      S.busy = false;
      S.error = e && e.name === 'NotAllowedError' ? 'No passkey was made.'
        : e && e.name === 'SecurityError' ? 'Passkeys need this Rouh opened at its name, not at a number address.'
        : (e && e.message) || 'No passkey was made.';
      draw();
    });
  }

  function draw() {
    var body = $('signInBody');
    if (!body || !S.open) return;
    body.textContent = '';
    if (S.error) body.appendChild(el('p', 'settings-help bad', S.error));
    else if (S.said) body.appendChild(el('p', 'settings-help good', S.said));
    var d = S.data;
    if (!d) { body.appendChild(el('p', 'settings-help', 'Reading…')); return; }

    // The headline: the one email, and where it signs you in (141-17).
    var head = el('p', 'yr-headline');
    head.appendChild(document.createTextNode('You sign in with '));
    head.appendChild(el('strong', 'yr-break', d.email || 'no email yet'));
    head.appendChild(document.createTextNode(d.connected ? ', here and on rouh.land.'
      : d.can_send ? '. A sign-in link comes to it.' : ' and your password. This Rouh can\u2019t send email yet.'));
    body.insertBefore(head, body.firstChild);
    // The password card under this one is the page's own: what it is for depends on the mail.
    var why = $('pwWhy');
    if (why) why.textContent = d.can_send ? 'Kept as a backup, for when this Rouh can\u2019t send you email.'
      : 'This Rouh can\u2019t send email yet, so this is how you sign in.';

    var mail = el('section', 'setting-card');
    mail.id = 'signInEmailCard';
    mail.appendChild(el('h4', null, 'How you sign in'));
    var dl = el('dl', 'readout');
    var row = el('div');
    row.appendChild(el('dt', null, 'Email'));
    row.appendChild(el('dd', 'mono', d.email || 'none yet'));
    dl.appendChild(row);
    mail.appendChild(dl);
    mail.appendChild(el('p', 'settings-help', d.label + '.' + (d.former.length
      ? ' ' + d.former.join(', ') + ' still works too, until you first sign in with ' + d.email + '.' : '')));
    if (d.connected) {
      var a = el('a', 'ctl small', 'Change email on rouh.land');
      a.href = d.account_url; a.target = '_blank'; a.rel = 'noopener';
      a.setAttribute('aria-label', 'Change email on rouh.land (opens in a new tab)');
      var acts = el('div', 'setting-actions'); acts.appendChild(a); mail.appendChild(acts);
    } else if (!d.guest) {
      if (!S.editing) {
        var acts2 = el('div', 'setting-actions');
        acts2.appendChild(button('Change email', '', function () { S.editing = true; S.said = ''; S.error = ''; draw(); }));
        mail.appendChild(acts2);
      } else {
        var f = el('form', 'setting-form');
        var field = el('div', 'field');
        var lab = el('label', null, 'New email'); lab.htmlFor = 'signInNewEmail';
        var box = el('input'); box.id = 'signInNewEmail'; box.type = 'email'; box.required = true;
        box.autocomplete = 'email';
        field.appendChild(lab); field.appendChild(box); f.appendChild(field);
        var pw = null;
        if (!d.can_send) {
          var f2 = el('div', 'field');
          var l2 = el('label', null, 'Your password'); l2.htmlFor = 'signInEmailPw';
          pw = el('input'); pw.id = 'signInEmailPw'; pw.type = 'password'; pw.autocomplete = 'current-password';
          f2.appendChild(l2); f2.appendChild(pw); f.appendChild(f2);
        }
        f.appendChild(el('p', 'settings-help', d.can_send
          ? 'A link goes to the new email. Nothing changes until it is opened.'
          : 'This Rouh cannot send email yet, so your password stands in for the link.'));
        var fa = el('div', 'setting-actions');
        var go = el('button', 'ctl small primary', S.busy ? 'Working…' : 'Change'); go.type = 'submit'; go.disabled = S.busy;
        fa.appendChild(go);
        fa.appendChild(button('Cancel', '', function () { S.editing = false; draw(); }));
        f.appendChild(fa);
        f.addEventListener('submit', function (e) {
          e.preventDefault();
          done(call('/api/sign-in/email', { email: box.value, password: pw ? pw.value : '' }))
            .then(function (j) { if (j && j.ok) S.editing = false; draw(); });
        });
        mail.appendChild(f);
        setTimeout(function () { box.focus(); }, 0);
      }
    }
    body.appendChild(mail);

    var keys = el('section', 'setting-card');
    keys.id = 'signInPasskeys';
    keys.appendChild(el('h4', null, 'Passkeys for this Rouh'));
    keys.appendChild(el('p', 'settings-help', 'An extra way in, with your face, fingerprint or device code. Your email ' +
      'always works too. On a device with a passkey, the sign-in page offers it first. Passkeys for rouh.land are ' +
      'separate, kept on rouh.land.'));
    var list = el('ul', 'signin-keys');
    d.passkeys.forEach(function (p) {
      var li = el('li');
      li.appendChild(el('span', null, p.name + ', added ' + p.added + (p.used ? ', last used ' + p.used : '')));
      li.appendChild(button('Remove', 'danger', function () {
        if (!window.confirm('Remove this passkey? You still sign in with your email.')) return;
        done(call('/api/sign-in/passkey/remove', { id: p.id })).then(function (j) {
          if (j && j.passkeys && !j.passkeys.length) forget(d.email);
        });
      }));
      list.appendChild(li);
    });
    if (d.passkeys.length) keys.appendChild(list);
    var ka = el('div', 'setting-actions');
    var add = button(S.busy ? 'Working…' : 'Add a passkey', '', addPasskey);
    add.disabled = S.busy;
    ka.appendChild(add);
    keys.appendChild(ka);
    body.appendChild(keys);

  }

  window.RouhSignIn = {
    shown: function () { S.open = true; S.said = ''; S.error = ''; draw(); load(); },
    hidden: function () { S.open = false; S.editing = false; },
  };

  /* ---- On a guest's contact card, for the owner ---- */

  /** @param {string[]} emails the card's addresses */
  function guestSection(emails) {
    var box = el('div', 'ct-own signin-guest');
    box.hidden = true;
    if (!emails || !emails.length) return box;
    call('/api/sign-in/guest?email=' + encodeURIComponent(emails.join(','))).then(function (j) {
      if (!j.guests || !j.guests.length) return;
      box.hidden = false;
      box.appendChild(el('h5', 'ct-own-title', 'Signs in to this Rouh'));
      j.guests.forEach(function (g) {
        var p = el('p', 'ct-own-empty', g.email + ' signs in as a guest. Locked out? Send them a new way in.');
        box.appendChild(p);
        var acts = el('div', 'hb-actions');
        var said = el('p', 'ct-own-empty');
        if (j.can_send) {
          acts.appendChild(button('Send a sign-in email', '', function () {
            call('/api/sign-in/guest/send', { email: g.email }).then(function (r) { said.textContent = r.said; })
              .catch(function (e) { said.textContent = e.message; });
          }));
        }
        acts.appendChild(button('Make a one-time link', '', function () {
          call('/api/sign-in/guest/link', { email: g.email }).then(function (r) {
            said.textContent = r.said + ' ' + r.link + '  (or the code ' + r.code + ')';
          }).catch(function (e) { said.textContent = e.message; });
        }));
        box.appendChild(acts);
        box.appendChild(said);
      });
    }).catch(function () { /* not the owner, or nothing to say */ });
    return box;
  }

  window.RouhGuestSignIn = { section: guestSection };
})();
