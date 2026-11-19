/* Your Rouh, the card "Your Rouh's URL" (`rouh/relay.py`, `rouh/web/relay.py`): Connections, Phone
   until 7 November 2026, when step 141-17 moved it to Your Rouh and Petar's Correction 1 renamed the
   phone address its URL, with an (i) beside the title that says what kind of URL it is.

   The one place a Rouh's URL is: the address the relay gave it at birth, Turn on URL (where the
   chat's setup step "Reach me from my phone" sends the owner), the real state of the line to the
   relay (Connected, Reconnecting, Connecting, Off), this month's traffic beside the fair limit when
   the relay says it, the QR code that signs the owner in on the phone once, and Turn off.

   Change (19 November 2026, Petar: "there should be a "Change/update" link next to my current
   link"): a link beside the address opens an editor in place, the name before the relay's domain
   checked as it is typed (its shape here, whether it is free by rouh.land), Save and Cancel. Saved,
   the card follows the move step by step (rouh.land, the relay's route, the certificate, the check
   from outside) and says when it is done, or that the old address was put back
   (`relay.change_name`).

   Drawn into `#phoneBody` from `/api/settings/phone`, read again every few seconds while it shows
   and the URL is on; Your Rouh (`birthpage.js`) tells it how the Rouh stands with rouh.land
   (`land`), and it tells Your Rouh's headline and tiles what it found. Anatomy tells it when it
   shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var P = { open: false, data: null, busy: false, error: '', link: null, timer: 0, seq: 0, seen: '', info: false,
            land: /** @type {{kind: string, admin: boolean, owner: string} | null} */ (null),
            /* Change: the editor, while it is open. */
            edit: /** @type {{value: string, verdict: string, why: string, seq: number, timer: number} | null} */ (null) };
  var EVERY = 3000;

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
    b.disabled = P.busy;
    b.addEventListener('click', act);
    return b;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function gb(bytes) {
    var n = bytes / 1e9;
    return (n >= 10 ? Math.round(n) : Math.round(n * 10) / 10) + ' GB';
  }
  function day(at) {
    try {
      return new Date(at * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
    } catch (err) { return ''; }
  }
  function clock(at) {
    try {
      return new Date(at * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch (err) { return ''; }
  }

  /** @param {string} method @param {string} url @param {Object} [sent] */
  function call(method, url, sent) {
    var seq = ++P.seq;
    if (method === 'POST') { P.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(sent || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') P.busy = false;
          if (seq !== P.seq && method === 'GET') return j;
          var error = r.ok ? '' : ((j && j.error) || 'The server said ' + r.status + '.');
          // A look that found nothing new leaves the page as it is (B1).
          var seen = JSON.stringify([j, error]);
          if (method === 'GET' && seen === P.seen) return j;
          P.seen = seen;
          if (j && j.link) P.link = j;
          else if (j && 'state' in j) P.data = j;
          // A sign-in code for an address the card no longer shows is put away.
          if (P.link && P.data && P.data.preferred && P.link.address !== P.data.preferred) P.link = null;
          P.error = error;
          // The editor is never drawn over while the person types in it.
          if (method === 'GET' && P.edit) return j;
          draw();
          return j;
        });
      })
      .catch(function () {
        P.busy = false;
        P.error = 'Rouh could not be reached.';
        draw();
        return null;
      });
  }

  function load() { return call('GET', '/api/settings/phone'); }

  var WORDS = {
    connected: ['Connected', 'yes'],
    reconnecting: ['Reconnecting', 'wait'],
    connecting: ['Connecting', 'wait'],
    off: ['Off', 'no']
  };

  function stateLine(d) {
    var w = WORDS[d.state] || WORDS.off;
    var line = el('p', 'hb-state ph-state ' + d.state);
    line.appendChild(el('span', 'hb-pulse'));
    line.appendChild(el('b', '', w[0]));
    if (d.said) line.appendChild(el('span', 'ph-said', d.said));
    return line;
  }

  /* What Your Rouh says of its connection (`birthpage.js`), which changes what this card offers:
     a free or disconnected Rouh has no URL, a stopped one has it off, a member presses nothing. */
  function land() { return P.land || { kind: '', admin: true, owner: '' }; }
  function say(text, undo) { if (window.RouhBirth && window.RouhBirth.toast) window.RouhBirth.toast(text, undo); }
  function help(text) { return el('p', 'settings-help', text); }

  function draw() {
    var body = $('phoneBody');
    if (!body || !P.open) return;
    var d = P.data;
    var L = land();
    var page = el('div', 'hb-page yr-url');
    if (P.error) page.appendChild(el('p', 'hb-say bad', P.error));
    if (!d) {
      if (!P.error) page.appendChild(el('p', 'hb-empty', 'Reading…'));
      body.replaceChildren(page);
      tell();
      return;
    }
    var admin = d.admin && L.admin !== false;
    if (!d.relay) {
      page.appendChild(el('p', 'hb-empty', 'This installation has no relay, so it has no URL.'));
    } else if (L.kind === 'free' || L.kind === 'code' || L.kind === 'disconnected' || d.connected_choice === false && !d.hostname) {
      var none = el('div', 'yr-empty');
      none.appendChild(el('p', '', L.kind === 'disconnected'
        ? 'No URL while disconnected. It waits for this Rouh, and comes back when it connects again.'
        : 'No URL yet. It comes with connecting to rouh.land, above.'));
      none.appendChild(help(L.kind === 'disconnected' ? 'Nothing is open to the internet while it is disconnected.'
        : 'This ' + (d.independent || 'Independent Rouh') + ' opens nothing to the internet.'));
      page.appendChild(none);
    } else if (!d.hostname) {
      page.appendChild(el('p', 'hb-empty', d.pending || 'Its URL has not come from ' + d.service + ' yet.'));
      if (d.claim_error) page.appendChild(el('p', 'hb-say bad', d.claim_error));
      if (admin) {
        var again = el('div', 'hb-actions');
        again.appendChild(button(d.connected_choice ? 'Ask for it again' : 'Get its URL',
          d.connected_choice ? '' : 'primary', function () { call('POST', '/api/settings/phone/claim'); }));
        page.appendChild(again);
        page.appendChild(help('Nothing is open to the internet until you then turn it on.'));
      }
    } else {
      var shown = d.preferred || d.address;
      var mv = d.rename && d.rename.state === 'working';
      if (P.edit && (!admin || !d.on || mv)) P.edit = null;
      if (P.edit) {
        page.appendChild(editor(d));
      } else {
        var addr = el('p', 'ph-address');
        var a = el('a', '', shown.replace(/^https:\/\//, ''));
        a.href = shown;
        a.target = '_blank';
        a.rel = 'noopener';
        addr.appendChild(a);
        if (admin && d.on && !mv && L.kind !== 'stopped') {
          var ch = el('button', 'ph-change', 'Change');
          ch.type = 'button';
          ch.id = 'phChange';
          ch.setAttribute('aria-label', 'Change your Rouh’s URL');
          ch.disabled = P.busy;
          ch.addEventListener('click', openEditor);
          addr.appendChild(ch);
        }
        page.appendChild(addr);
        page.appendChild(sharedLine(d));
      }
      if (d.rename && !(P.edit && d.rename.state !== 'working')) page.appendChild(moving(d));
      if (L.kind === 'stopped') {
        var off = el('p', 'hb-state ph-state off');
        off.appendChild(el('span', 'hb-pulse'));
        off.appendChild(el('b', '', 'Off'));
        off.appendChild(el('span', 'ph-said', 'while rouh.land has stopped this Rouh.'));
        page.appendChild(off);
        body.replaceChildren(page);
        tell();
        return;
      }
      page.appendChild(stateLine(d));
      if (d.on && d.checked && !d.checked.ok && d.checked.error) {
        page.appendChild(el('p', 'hb-say bad', 'Checked from outside at ' + clock(d.checked.at) + ': ' + d.checked.error + '.'));
      }
      if (d.on && d.limit_bytes && d.usage) {
        var used = el('div', 'ph-usage');
        used.appendChild(el('span', '', 'This month ' + gb(d.usage.bytes) + ' of ' + gb(d.limit_bytes)
          + (d.usage.slowed ? ', slowed until the month ends' : '')));
        var bar = el('span', 'ph-bar');
        var fill = el('span', 'ph-fill' + (d.usage.slowed ? ' slowed' : ''));
        fill.style.width = Math.min(100, Math.round(100 * d.usage.bytes / d.limit_bytes)) + '%';
        bar.appendChild(fill);
        used.appendChild(bar);
        page.appendChild(used);
      }
      if (!admin) {
        page.appendChild(el('p', 'yr-member', 'Only ' + (L.owner || 'its owner') + ', who owns this Rouh, can change this.'));
      } else {
        var acts = el('div', 'hb-actions');
        if (!d.on) {
          acts.appendChild(button('Turn on URL', 'primary', function () {
            P.link = null;
            call('POST', '/api/settings/phone/on').then(function (j) {
              if (j && !j.error) say('URL on.');
              tick();
            });
          }));
        } else {
          if (d.state === 'connected' && !P.edit) {
            acts.appendChild(button(P.link ? 'New sign-in code' : 'Show sign-in code', 'primary', function () {
              call('POST', '/api/settings/phone/signin');
            }));
          }
          acts.appendChild(button('Turn off', 'yr-quiet', function () {
            P.link = null;
            call('POST', '/api/settings/phone/off').then(function (j) {
              if (j && !j.error) say('URL off. Phones signed in stop reaching it.');
            });
          }));
        }
        if (!P.edit) page.appendChild(acts);
        if (!d.on) page.appendChild(help('Turning it on lets your phone open this Rouh from anywhere. Only people who sign in can use it. Nothing is open to the internet until then.'));
      }
      if (d.on && P.link && d.state === 'connected') page.appendChild(qrCard(P.link));
      if (d.certificate && d.certificate.until) {
        var info = el('details', 'info ph-info');
        info.open = P.info;
        info.addEventListener('toggle', function () { P.info = info.open; });
        info.appendChild(el('summary', '', 'Locked end to end'));
        info.appendChild(el('p', 'hb-note', 'Locked with its own certificate, good until ' + day(d.certificate.until)
          + '. rouh.land’s relay passes it on by its name and never sees what is in it.'
          + (d.on && d.checked && d.checked.ok ? ' Checked from outside at ' + clock(d.checked.at) + '.' : '')));
        page.appendChild(info);
      } else if (d.on && d.certificate && d.certificate.error) {
        page.appendChild(el('p', 'hb-say bad', 'No certificate yet: ' + d.certificate.error));
      }
    }
    body.replaceChildren(page);
    tell();
  }

  /* Under the address and in Change (Petar, 19 November 2026): a chosen name is the way in, and
     every link this Rouh shares is on the born name, which never changes (`relay.share_address`). */
  /** @param {any} d */
  function sharedLine(d) {
    var born = String(d.share || d.address || '').replace(/^https:\/\//, '');
    var p = el('p', 'settings-help ph-shared');
    p.id = 'phShared';
    p.appendChild(document.createTextNode('The name you choose is how you reach your Rouh. Links you share always use '));
    p.appendChild(el('b', '', born));
    p.appendChild(document.createTextNode(', which never changes, so renaming never breaks a shared link.'));
    return p;
  }

  /** "today at 14:05", "tomorrow at 09:30", on this browser's clock. @param {number} at */
  function when(at) {
    var t = new Date(at * 1000), now = new Date();
    var morrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    var dayWord = t.toDateString() === now.toDateString() ? 'today'
      : t.toDateString() === morrow.toDateString() ? 'tomorrow'
      : t.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
    return dayWord + ' at ' + clock(at);
  }

  /** How many changes are left today, or when the next is allowed. @param {any} d */
  function changesLine(d) {
    var c = d.changes || { left: 1, limit: 2, next_at: 0 };
    var p = el('p', 'ph-limit' + (c.left ? '' : ' none'));
    p.id = 'phLimit';
    p.textContent = c.left
      ? 'You can change your address ' + c.limit + ' times in any 24 hours. '
        + (c.left === c.limit ? 'Both are left.' : c.left === 1 ? 'One is left.' : c.left + ' are left.')
      : 'You have changed your address ' + c.limit + ' times in the last 24 hours. You can change it again ' + when(c.next_at) + '.';
    return p;
  }
  function noneLeft() { var c = P.data && P.data.changes; return !!(c && c.left === 0); }

  /* --- Change --------------------------------------------------------------------------------- */

  /** The part before the relay's domain, as rouh.land reads what was typed. @param {string} v */
  function plain(v) {
    v = String(v || '').trim().toLowerCase();
    var dom = '.' + ((P.data && P.data.domain) || 'rouh.page');
    if (v.slice(-dom.length) === dom) v = v.slice(0, -dom.length);
    return v.replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '');
  }
  function label(host) { return String(host || '').split('.')[0]; }
  /** What is wrong with a name's shape, or ''. rouh.land holds names to 3 to 30 characters. */
  function shape(n) {
    if (!n) return '';
    if (n.length < 3 || n.length > 30) return 'Use 3 to 30 letters, digits or dashes.';
    if (/^-|-$/.test(n) || n.indexOf('--') >= 0) return 'A name cannot start or end with a dash, or have two dashes together.';
    if (!/[a-z]/.test(n)) return 'A name needs at least one letter.';
    return '';
  }

  function openEditor() {
    var d = P.data;
    if (!d) return;
    P.edit = { value: label(d.current || d.hostname), verdict: 'same', why: 'That is your address now.', seq: 0, timer: 0 };
    draw();
    var input = /** @type {HTMLInputElement | null} */ ($('phNewName'));
    if (input) { input.focus(); input.select(); }
  }
  function closeEditor() {
    if (!P.edit) return;
    clearTimeout(P.edit.timer);
    P.edit = null;
    draw();
    var ch = $('phChange');
    if (ch) ch.focus();
  }

  /** Looks the name up: its shape here, at once; whether it is free by rouh.land, after a pause. */
  function judge() {
    var E = P.edit, d = P.data;
    if (!E || !d) return;
    clearTimeout(E.timer);
    var n = plain(E.value);
    var seq = ++E.seq;
    if (!n) { E.verdict = 'empty'; E.why = 'Type the name you want before .' + d.domain + '.'; return verdict(); }
    if (n === label(d.current || d.hostname)) { E.verdict = 'same'; E.why = 'That is your address now.'; return verdict(); }
    var bad = shape(n);
    if (bad) { E.verdict = 'bad'; E.why = bad; return verdict(); }
    if (n === label(d.hostname)) {
      E.verdict = 'ok'; E.why = 'The address it was born with. Save to go back to it.';
      return verdict();
    }
    E.verdict = 'checking'; E.why = 'Checking ' + n + '.' + d.domain + '…';
    verdict();
    E.timer = setTimeout(function () {
      fetch('/api/settings/phone/name?name=' + encodeURIComponent(n), { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return [r.ok, j]; }); })
        .then(function (got) {
          if (!P.edit || seq !== P.edit.seq) return;
          var j = got[1] || {};
          if (!got[0]) { P.edit.verdict = 'error'; P.edit.why = 'Could not check it: ' + (j.error || 'rouh.land did not answer') ; }
          else if (j.available) { P.edit.verdict = 'ok'; P.edit.why = (j.name || n) + '.' + d.domain + ' is available.'; }
          else { P.edit.verdict = 'bad'; P.edit.why = j.why || 'That name is not available.'; }
          verdict();
        })
        .catch(function () {
          if (!P.edit || seq !== P.edit.seq) return;
          P.edit.verdict = 'error'; P.edit.why = 'Could not check it: Rouh could not be reached.';
          verdict();
        });
    }, 350);
  }

  var MARKS = {
    ok: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3L13 4.5"/></svg>',
    bad: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    wait: '<span class="ph-spin" aria-hidden="true"></span>',
    dot: '<span class="ph-hollow" aria-hidden="true"></span>'
  };

  /** The line under the field, and Save on or off, changed in place so typing is never interrupted. */
  function verdict() {
    var E = P.edit, line = $('phVerdict'), save = /** @type {HTMLButtonElement | null} */ ($('phSave'));
    if (!E || !line) return;
    var v = E.verdict;
    line.className = 'ph-verdict ' + (v === 'ok' ? 'ok' : v === 'bad' || v === 'error' ? 'bad' : 'wait');
    line.innerHTML = v === 'ok' ? MARKS.ok : v === 'bad' || v === 'error' ? MARKS.bad : v === 'checking' ? MARKS.wait : '';
    line.appendChild(el('span', '', E.why));
    if (save) save.disabled = P.busy || v !== 'ok' || noneLeft();
  }

  /** @param {any} d */
  function editor(d) {
    var E = /** @type {{value: string, verdict: string, why: string, seq: number, timer: number}} */ (P.edit);
    var f = el('form', 'ph-edit');
    f.setAttribute('novalidate', '');
    f.appendChild(el('label', 'ph-edit-l', 'New address')).setAttribute('for', 'phNewName');
    var field = el('div', 'ph-field');
    var input = /** @type {HTMLInputElement} */ (el('input'));
    input.id = 'phNewName';
    input.type = 'text';
    input.value = E.value;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('autocapitalize', 'none');
    input.setAttribute('maxlength', '40');
    input.setAttribute('aria-describedby', 'phVerdict phOld');
    input.addEventListener('input', function () {
      var at = input.selectionStart, before = input.value;
      var low = before.toLowerCase().replace(/[\s_]/g, '-');
      if (low !== before) { input.value = low; try { input.setSelectionRange(at, at); } catch (err) { /* */ } }
      E.value = input.value;
      judge();
    });
    field.appendChild(input);
    field.appendChild(el('span', 'ph-suffix', '.' + d.domain));
    f.appendChild(field);
    var line = el('p', 'ph-verdict wait');
    line.id = 'phVerdict';
    line.setAttribute('aria-live', 'polite');
    f.appendChild(line);
    var cur = d.current || d.hostname;
    var old = el('p', 'ph-old');
    old.id = 'phOld';
    if (d.chosen && cur === d.chosen) {
      old.appendChild(el('b', '', cur));
      old.appendChild(document.createTextNode(' stops working when you save. Phones and bookmarks that use it will need the new address. '
        + 'It is kept for you for ' + ((d.changes && d.changes.held_days) || 15) + ' days before anyone else can take it. '
        + d.hostname + ', the address it was born with, keeps working.'));
    } else {
      old.appendChild(el('b', '', cur));
      old.appendChild(document.createTextNode(' is the address it was born with and keeps working, so phones signed in on it go on working. '
        + 'Your Rouh opens on the new one from then on.'));
    }
    f.appendChild(old);
    f.appendChild(sharedLine(d));
    f.appendChild(changesLine(d));
    var acts = el('div', 'hb-actions');
    var save = /** @type {HTMLButtonElement} */ (el('button', 'ctl small primary', 'Save'));
    save.type = 'submit';
    save.id = 'phSave';
    acts.appendChild(save);
    acts.appendChild(button('Cancel', 'yr-quiet', closeEditor));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!P.edit || P.edit.verdict !== 'ok' || P.busy) return;
      var n = plain(P.edit.value);
      clearTimeout(P.edit.timer);
      P.edit = null;
      call('POST', '/api/settings/phone/name', { name: n }).then(function (j) {
        if (j && j.error) {
          // Refused before anything moved: the editor comes back with the reason.
          P.edit = { value: n, verdict: 'bad', why: j.error, seq: 0, timer: 0 };
          P.error = '';
          draw();
          verdict();
          var again = /** @type {HTMLInputElement | null} */ ($('phNewName'));
          if (again) again.focus();
        }
      });
    });
    f.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeEditor(); }
    });
    setTimeout(verdict, 0);
    return f;
  }

  /** The move on its way, or how it ended: under the address. @param {any} d */
  function moving(d) {
    var R = d.rename;
    var box = el('div', 'ph-move ' + R.state);
    box.setAttribute('role', 'status');
    if (R.state === 'working') {
      var head = el('p', 'ph-move-h');
      head.appendChild(document.createTextNode('Moving to '));
      head.appendChild(el('b', '', R.to));
      box.appendChild(head);
      var list = el('ol', 'ph-steps');
      R.steps.forEach(function (/** @type {{words: string, state: string}} */ s) {
        var li = el('li', 'ph-step ' + s.state);
        var mark = el('span', 'ph-mark');
        mark.innerHTML = s.state === 'done' ? MARKS.ok : s.state === 'failed' ? MARKS.bad : s.state === 'working' ? MARKS.wait : MARKS.dot;
        li.appendChild(mark);
        li.appendChild(el('span', '', s.words));
        li.appendChild(el('span', 'ph-sr', s.state === 'done' ? ', done' : s.state === 'working' ? ', on its way' : ', waiting'));
        list.appendChild(li);
      });
      box.appendChild(list);
      box.appendChild(el('p', 'hb-note', 'Usually under a minute. If it is not working by ' + clock(R.until) + ', '
        + (R.back_to || d.hostname) + ' is put back by itself, so you always have an address that works.'));
      if (R.detail) {
        var more = el('details', 'info ph-info');
        more.appendChild(el('summary', '', 'Show details'));
        more.appendChild(el('p', 'hb-note', R.detail));
        box.appendChild(more);
      }
      return box;
    }
    var said = el('p', 'hb-say' + (R.state === 'done' ? ' ph-done' : ' bad'));
    said.appendChild(el('span', 'ph-mark', '')).innerHTML = R.state === 'done' ? MARKS.ok : MARKS.bad;
    said.appendChild(el('span', '', R.said));
    box.appendChild(said);
    if (R.state === 'done' && R.from && (d.addresses || []).indexOf(R.from) < 0) {
      box.appendChild(el('p', 'hb-note', R.from + ' no longer works. Phones and bookmarks that used it need the new address: '
        + 'Show sign-in code signs a phone in on it.'));
    }
    var acts = el('div', 'hb-actions');
    acts.appendChild(button('OK', 'yr-quiet', function () { call('POST', '/api/settings/phone/name', { do: 'seen' }); }));
    box.appendChild(acts);
    return box;
  }

  /* Your Rouh's headline and URL tile follow this card. */
  function tell() { if (window.RouhBirth && window.RouhBirth.phone) window.RouhBirth.phone(P.data); }

  /* The (i) beside "Your Rouh's URL" (Correction 1 of 141-17): a small popover that says what kind
     of URL this is and what the relay is. It closes on Escape (focus back on the (i)), a click or
     tap outside it, or the (i) again. */
  (function info() {
    var ib = $('yrUrlInfoBtn'), pop = $('yrUrlInfo');
    if (!ib || !pop) return;
    function setOpen(o) {
      pop.hidden = !o;
      ib.setAttribute('aria-expanded', o ? 'true' : 'false');
      // Opened low on a phone's screen, it is brought up whole rather than left under the fold.
      if (o && pop.scrollIntoView) pop.scrollIntoView({ block: 'nearest' });
    }
    ib.addEventListener('click', function (e) { e.stopPropagation(); setOpen(pop.hidden); });
    document.addEventListener('click', function (e) {
      var t = /** @type {Node} */ (e.target);
      if (!pop.hidden && !pop.contains(t) && !ib.contains(t)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !pop.hidden) { e.stopPropagation(); setOpen(false); ib.focus(); }
    }, true);
  }());

  function qrCard(link) {
    var box = el('div', 'ph-qr');
    var pic = el('div', 'ph-qr-pic');
    pic.setAttribute('role', 'img');
    pic.setAttribute('aria-label', 'QR code that signs you in on your phone');
    pic.innerHTML = link.qr;
    box.appendChild(pic);
    var words = el('div', 'ph-qr-words');
    words.appendChild(el('p', '', 'Scan it with your phone\'s camera. It signs you in once, for ten minutes, until '
      + clock(link.until) + '.'));
    words.appendChild(el('p', 'hb-note', 'Then use Share, Add to Home Screen, to keep it like an app.'));
    box.appendChild(words);
    return box;
  }

  function tick() {
    clearTimeout(P.timer);
    if (!P.open) return;
    P.timer = setTimeout(function () {
      if (!P.open) return;
      var on = P.data && P.data.on;
      (on ? load() : Promise.resolve()).then(tick);
    }, EVERY);
  }

  function shownNow() {
    if (P.open) return;
    P.open = true;
    P.error = '';
    P.seen = '';
    draw();
    load().then(tick);
  }

  function hiddenNow() {
    P.open = false;
    P.link = null;
    clearTimeout(P.timer);
    var pop = $('yrUrlInfo'), ib = $('yrUrlInfoBtn');
    if (pop) pop.hidden = true;
    if (ib) ib.setAttribute('aria-expanded', 'false');
  }

  /** Your Rouh's connection, as birthpage.js reads it. @param {{kind: string, admin: boolean, owner: string}} L */
  function landNow(L) {
    var before = JSON.stringify(P.land);
    P.land = L;
    if (before !== JSON.stringify(L)) draw();
  }

  window.RouhPhone = { shown: shownNow, hidden: hiddenNow, reload: load, land: landNow };
}());
