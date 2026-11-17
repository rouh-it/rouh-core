// Connections (task 189, Rouh Link): the other Rouhs this one is connected to, how far each is
// trusted, connect links and QR codes, requests, a contact's Rouh, the live spaces, and what is off.
// Every press is one call to this Rouh (/api/link...), and the page is drawn again from its answer.
(function () {
  'use strict';

  var API = window.LINK_API || {
    get: function (path) { return fetch(path, { credentials: 'same-origin' }).then(answer); },
    post: function (path, body) {
      return fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) }).then(answer);
    }
  };
  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok) { var e = new Error(j.error || ('Rouh answered ' + r.status)); e.status = r.status; throw e; }
      return j;
    });
  }
  var S = null;
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    });
    (kids || []).forEach(function (k) { if (k != null) e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k); });
    return e;
  }
  function clear(n) { while (n && n.firstChild) n.removeChild(n.firstChild); return n; }
  function toast(words) {
    var t = $('toast'); t.textContent = words; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.hidden = true; }, 6000);
  }
  function fail(e) { toast(e && e.message ? e.message : 'That did not work.'); }
  function initials(name) {
    var n = String(name || '?').replace(/·.*/, '').trim().split(/\s+/);
    return ((n[0] || '?')[0] + ((n[1] || '')[0] || '')).toUpperCase();
  }
  function when(at) {
    if (!at) return '';
    var d = new Date(at * 1000);
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'long' });
  }

  function load() {
    return API.get('/api/link').then(function (st) { S = st; draw(); }).catch(fail);
  }

  function draw() {
    if (!S.born) {
      $('lead').textContent = 'Your Rouh is not born yet, so it has no name to work with other Rouhs.';
      $('leadMore').textContent = 'Its birth gives it a name and a key: Anatomy, Your Rouh, Connect to rouh.land.';
      $('content').hidden = true;
      return;
    }
    $('content').hidden = false;
    var connected = S.peers.filter(function (p) { return p.state === 'connected'; });
    var asks = S.peers.filter(function (p) { return p.state === 'asked'; });
    var invited = S.spaces.filter(function (s) { return s.state === 'invited'; });
    var lead = 'Your Rouh, ' + S.me.name + ', is connected to ' + connected.length + (connected.length === 1 ? ' Rouh' : ' Rouhs');
    if (asks.length || invited.length) lead += '; ' + (asks.length + invited.length) + ' need' + (asks.length + invited.length === 1 ? 's' : '') + ' you';
    $('lead').textContent = lead + '.';
    $('leadMore').textContent = S.me.address ? 'Other Rouhs reach it at ' + S.me.address.replace(/^https?:\/\//, '') + '.' : 'It has no address other Rouhs can reach yet.';
    drawNeeds(asks, invited);
    // One primary press a view: the request waiting, else making a link.
    $('makeLink').className = asks.length || invited.length || !S.peers.length ? '' : 'primary';
    drawPeers();
    drawSpaces();
    drawInvites();
    drawOff();
    drawHandoffs();
    if (window.LINK_ACCEPT && !draw.accepted) { draw.accepted = true; $('bringLink').value = window.LINK_ACCEPT; $('bringLink').focus(); }
  }

  function levelSelect(p, onchange) {
    var sel = el('select', { 'aria-label': 'Trust level for ' + p.name });
    S.levels.forEach(function (l) { sel.appendChild(el('option', { value: l.id, text: l.word, selected: l.id === p.trust })); });
    sel.addEventListener('change', function () { onchange(sel.value); });
    return sel;
  }

  function peerAct(label, body, said) {
    return API.post('/api/link/peer/' + encodeURIComponent(label), body).then(function () { if (said) toast(said); return load(); }).catch(fail);
  }

  function drawNeeds(asks, invited) {
    var box = clear($('needs'));
    $('needsBox').hidden = !(asks.length || invited.length);
    asks.forEach(function (p) {
      var level = 'known';
      box.appendChild(el('div', { class: 'peer' }, [
        el('span', { class: 'av rouh c-1', 'aria-hidden': 'true', text: initials(p.name) }),
        el('div', {}, [el('div', { text: p.name + (p.via === 'stranger' ? ', a Rouh you do not know,' : '') + ' asks to connect.' }),
          el('div', { class: 'small dim', text: p.address || 'reached by the mailbox' }),
          p.note ? el('div', { class: 'small', text: p.note }) : null]),
        el('div', { class: 'acts' }, [
          levelSelect(p, function (v) { level = v; }),
          el('button', { class: 'primary', text: 'Connect', onclick: function () { peerAct(p.label, { act: 'yes', level: level }, 'Connected to ' + p.name + '.'); } }),
          el('button', { class: 'quiet', text: 'No', onclick: function () { peerAct(p.label, { act: 'cut' }, 'Said no.'); } })
        ])
      ]));
    });
    invited.forEach(function (s) {
      box.appendChild(el('div', { class: 'peer' }, [
        el('span', { class: 'av rouh c-1', 'aria-hidden': 'true', text: initials(s.holder) }),
        el('div', {}, [el('div', { text: 'You are asked into a live ' + s.kind_word.toLowerCase() + ': “' + s.title + '”.' })]),
        el('div', { class: 'acts' }, [el('a', { href: '/link/space/' + s.space_id }, [el('button', { class: 'primary', text: 'Open' })])])
      ]));
    });
  }

  function drawPeers() {
    var box = clear($('peers'));
    var shown = S.peers.filter(function (p) { return p.state !== 'asked'; });
    if (!shown.length) {
      box.appendChild(el('div', { class: 'empty' }, [el('h3', { text: 'No Rouh connected yet' }),
        el('p', { class: 'dim', text: 'Make a connect link and send it to someone with a Rouh, or bring a link they sent you.' }),
        el('div', {}, [el('button', { class: 'primary', text: 'Make a connect link', onclick: makeLink })])]));
      return;
    }
    shown.forEach(function (p) {
      var stateWords = { connected: 'Connected', waiting: 'Waiting for its person', cut: 'Cut', blocked: 'Blocked', refused: 'Said no', noted: 'A contact’s Rouh, not connected yet' }[p.state] || p.state;
      var acts = el('div', { class: 'acts' });
      if (p.state === 'connected') {
        acts.appendChild(levelSelect(p, function (v) { peerAct(p.label, { act: 'trust', level: v }, p.name + ' is ' + v + ' now.'); }));
        var side = el('select', { 'aria-label': 'Side for ' + p.name });
        [['', 'Either side'], ['work', 'Work'], ['personal', 'Personal']].forEach(function (o) { side.appendChild(el('option', { value: o[0], text: o[1], selected: o[0] === (p.silo || '') })); });
        side.addEventListener('change', function () { peerAct(p.label, { act: 'silo', silo: side.value }, 'Side changed.'); });
        acts.appendChild(side);
        acts.appendChild(el('button', { class: 'danger', text: 'Cut', onclick: function () { peerAct(p.label, { act: 'cut' }, 'Cut. It can no longer reach your Rouh.'); } }));
      }
      if (p.state === 'noted') acts.appendChild(el('button', { text: 'Connect', onclick: function () { connectAddress(p.address); } }));
      if (p.state === 'blocked') acts.appendChild(el('button', { text: 'Unblock', onclick: function () { peerAct(p.label, { act: 'unblock' }, 'Unblocked.'); } }));
      else acts.appendChild(el('button', { class: 'quiet danger', text: 'Block', onclick: function () { peerAct(p.label, { act: 'block' }, 'Blocked.'); } }));
      acts.appendChild(el('button', { class: 'quiet', text: 'The log', onclick: function () { openLog(p); } }));
      if (p.state === 'connected' && p.trust === 'delegate') acts.appendChild(el('button', { class: 'quiet', text: 'Write a grant', onclick: function () { grantForm(p, box); } }));
      var theirs = (S.grants || []).filter(function (g) { return g.peer === p.label && g.active; });
      var grantsBox = el('div', { class: 'acts stack', style: 'gap:6px' });
      theirs.forEach(function (g) {
        grantsBox.appendChild(el('div', { class: 'grant' }, [
          el('p', { class: 'small' }, [el('strong', { text: g.direction === 'out' ? 'Your grant: ' : 'Their grant to your Rouh: ' }), g.words]),
          g.direction === 'out' ? el('button', { class: 'danger', text: 'Withdraw', onclick: function () {
            API.post('/api/link/grant', { act: 'withdraw', grant_id: g.grant_id }).then(function () { toast('Withdrawn. Nothing more is decided under it.'); load(); }).catch(fail); } }) : null]));
      });
      box.appendChild(el('div', { class: 'peer' }, [
        el('span', { class: 'av rouh c-' + (p.state === 'connected' ? '1' : '4'), 'aria-hidden': 'true', text: initials(p.name) }),
        el('div', {}, [el('div', { text: p.name }), el('div', { class: 'small dim', text: stateWords + (p.state === 'connected' ? ', ' + p.trust_word + (p.silo ? ', ' + p.silo : '') : '') + (p.since ? ', since ' + when(p.since) : '') })]),
        acts, theirs.length ? grantsBox : null
      ]));
    });
  }

  function holderName(label) {
    var p = (S.peers || []).filter(function (x) { return x.label === label; })[0];
    return p ? p.name.split(' ·')[0] : label;
  }

  function drawSpaces() {
    var box = clear($('spaces'));
    var live = S.spaces.filter(function (s) { return s.state !== 'invited'; });
    if (!live.length) box.appendChild(el('p', { class: 'dim small', text: 'No live space yet. Start one, then ask a connected Rouh in.' }));
    live.forEach(function (s) {
      box.appendChild(el('div', { class: 'peer' }, [
        el('span', { class: 'av c-0', 'aria-hidden': 'true', text: s.kind_word[0] }),
        el('div', {}, [el('a', { href: '/link/space/' + s.space_id, text: s.title || 'Untitled' }),
          el('div', { class: 'small dim', text: s.kind_word + ', ' + (s.mine ? 'held by your Rouh' : 'held by ' + holderName(s.holder) + '’s Rouh') + ', ' + s.members.length + (s.members.length === 1 ? ' Rouh' : ' Rouhs') + ' in it' + (s.state === 'ended' ? ', ended' : '') })])
      ]));
    });
  }

  function drawInvites() {
    var box = clear($('invites'));
    var open = (S.invites || []).filter(function (i) { return i.open; });
    if (!open.length) return;
    box.appendChild(el('h3', { text: 'Links not used yet' }));
    open.forEach(function (i) {
      box.appendChild(el('div', { class: 'row small' }, [el('span', { class: 'grow', text: i.trust + (i.for_label ? ', for ' + i.for_label + ' only' : '') + ', good until ' + when(i.expires_at) }),
        el('button', { class: 'quiet', text: 'Withdraw', onclick: function () { API.post('/api/link/invite/withdraw', { id: i.id }).then(load).catch(fail); } })]));
    });
  }

  function drawOff() {
    var st = S.settings || {};
    $('strangers').checked = !!st.strangers;
    $('openNet').checked = !!st.open_network;
    $('findable').checked = !!st.findable_by_email;
    ['strangers', 'openNet', 'findable'].forEach(function (id) { $(id).disabled = !!st.held; });
    $('heldWhy').textContent = st.held ? st.held_why : 'You choose. Each stays off until you turn it on.';
  }

  // A written grant to a delegate: what it may decide for you, with its limits, shown to both people.
  function grantForm(p, box) {
    var mins = el('select', { 'aria-label': 'Longest meeting' });
    [30, 60, 90, 120].forEach(function (m) { mins.appendChild(el('option', { value: m, text: 'Up to ' + m + ' minutes', selected: m === 60 })); });
    var week = el('select', { 'aria-label': 'Most a week' });
    [1, 3, 5, 10].forEach(function (m) { week.appendChild(el('option', { value: m, text: 'At most ' + m + ' a week', selected: m === 5 })); });
    var f = el('form', { class: 'stack grant-form', onsubmit: function (ev) {
      ev.preventDefault();
      API.post('/api/link/grant', { label: p.label, what: 'meetings', limits: { most_minutes: +mins.value, most_a_week: +week.value,
        days: [0, 1, 2, 3, 4], from_hour: 9, to_hour: 18 } }).then(function (g) { toast('Written and shown to ' + p.name + ': ' + g.words); f.remove(); load(); }).catch(fail);
    } }, [el('p', { class: 'small', text: p.name.split(' ·')[0] + '’s Rouh may agree meetings for you, weekdays 9:00 to 18:00:' }),
      el('div', { class: 'row' }, [mins, week]), el('p', { class: 'small dim', text: 'Never money. Withdraw it here at any time.' }),
      el('div', { class: 'row' }, [el('button', { class: 'primary', type: 'submit', text: 'Write the grant' }),
        el('button', { class: 'quiet', type: 'button', text: 'Cancel', onclick: function () { f.remove(); } })])]);
    box.appendChild(f);
  }

  function peerName(label) {
    var p = (S.peers || []).filter(function (x) { return x.label === label; })[0];
    return p ? p.name : label;
  }

  function drawHandoffs() {
    var box = clear($('handoffs'));
    var list = S.handoffs || [];
    if (!list.length) box.appendChild(el('p', { class: 'dim small', text: 'Nothing handed over yet.' }));
    list.forEach(function (h) {
      var f = h.form || {}, row = el('div', { class: 'grant' });
      if (h.kind === 'handoff.brief') {
        row.appendChild(el('p', { class: 'small' }, [el('strong', { text: 'A brief from ' + peerName(h.peer) + ': ' }), String(f.need || ''),
          ' (budget: ' + (f.budget_band || 'ask') + (f.by_when ? ', by ' + f.by_when : '') + ')']));
        if (h.state === 'new') {
          var amount = el('input', { type: 'text', inputmode: 'decimal', 'aria-label': 'Amount', placeholder: 'Amount', style: 'width:110px' });
          var cur = el('select', { 'aria-label': 'Currency', style: 'width:auto' });
          ['EUR', 'BGN', 'USD', 'GBP'].forEach(function (c) { cur.appendChild(el('option', { value: c, text: c })); });
          row.appendChild(el('form', { class: 'row', onsubmit: function (ev) { ev.preventDefault();
            API.post('/api/link/handoff', { act: 'quote', brief_id: h.id.split(':')[1], amount: parseFloat(amount.value) || 0, currency: cur.value })
              .then(function () { toast('Quote sent. A person decides on it there.'); load(); }).catch(fail); } },
            [amount, cur, el('button', { type: 'submit', text: 'Send a quote' })]));
        } else row.appendChild(el('span', { class: 'small dim', text: h.said || h.state }));
      } else if (h.kind === 'handoff.quote') {
        row.appendChild(el('p', { class: 'small' }, [el('strong', { text: 'A quote from ' + peerName(h.peer) + ': ' }), f.amount + ' ' + f.currency + (f.words ? ', ' + f.words : '')]));
      } else if (h.kind === 'money.proposal') {
        row.appendChild(el('p', { class: 'small' }, [el('strong', { text: peerName(h.peer) + ' proposes ' + f.amount + ' ' + f.currency + ': ' }), String(f.for || '')]));
        row.appendChild(el('a', { href: '/link/money/' + encodeURIComponent(h.id), text: h.state === 'agreed' ? 'You agreed' : 'Read it' }));
      }
      box.appendChild(row);
    });
    var sel = clear($('briefTo'));
    (S.peers || []).filter(function (p) { return p.state === 'connected'; }).forEach(function (p) { sel.appendChild(el('option', { value: p.label, text: p.name })); });
    $('briefForm').hidden = !sel.options.length;
  }

  function makeLink() {
    var body = { trust: $('newTrust').value, for_label: $('newFor').value.trim(), silo: $('newSide').value };
    API.post('/api/link/invite', body).then(function (got) {
      $('linkOut').hidden = false;
      $('linkText').textContent = got.link;
      var qr = clear($('linkQr'));
      if (got.qr) { qr.innerHTML = got.qr; qr.hidden = false; } else qr.hidden = true;
      $('copyLink').onclick = function () {
        (navigator.clipboard ? navigator.clipboard.writeText(got.link) : Promise.reject()).then(function () { toast('Copied.'); }, function () { toast('Select the link and copy it.'); });
      };
      load();
    }).catch(fail);
  }

  function connectAddress(address) {
    API.post('/api/link/connect', { address: address, trust: 'known' }).then(function (p) {
      toast(p.state === 'connected' ? 'Connected to ' + p.name + '.' : 'Asked ' + p.name + '; waiting for its person.'); load();
    }).catch(fail);
  }

  function openLog(p) {
    $('logTitle').textContent = 'The log with ' + p.name;
    $('logDrawer').hidden = false; $('scrim').hidden = false;
    clear($('logMine')).appendChild(el('li', { class: 'dim', text: 'Reading…' }));
    clear($('logTheirs'));
    API.get('/api/link/peer/' + encodeURIComponent(p.label) + '/log').then(function (got) {
      fill($('logMine'), got.mine, false);
      fill($('logTheirs'), got.theirs, true);
      if (got.theirs_said) $('logTheirs').appendChild(el('li', { class: 'dim', text: got.theirs_said }));
    }).catch(fail);
    $('logClose').focus();
  }
  function fill(ul, entries, theirs) {
    clear(ul);
    (entries || []).slice().reverse().forEach(function (e) {
      var d = new Date(e.at * 1000);
      ul.appendChild(el('li', {}, [el('span', { class: 'when', text: d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }),
        el('span', { class: theirs && e.holds === false ? 'broken' : '', text: e.plain + (theirs && e.holds === false ? ' (its signature does not hold)' : '') })]));
    });
    if (!(entries || []).length) ul.appendChild(el('li', { class: 'dim', text: 'Nothing yet.' }));
  }
  function closeLog() { $('logDrawer').hidden = true; $('scrim').hidden = true; }

  document.addEventListener('DOMContentLoaded', function () {
    $('makeLink').addEventListener('click', makeLink);
    $('bring').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var link = $('bringLink').value.trim(); if (!link) return;
      $('bringGo').disabled = true;
      API.post('/api/link/accept', { link: link, trust: $('bringTrust').value }).then(function (p) {
        $('bringLink').value = ''; toast('Connected to ' + p.name + '.'); load();
      }).catch(fail).then(function () { $('bringGo').disabled = false; });
    });
    $('briefForm').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var need = $('briefNeed').value.trim(); if (!need) return;
      API.post('/api/link/handoff', { act: 'brief', label: $('briefTo').value, need: need, budget_band: $('briefBudget').value })
        .then(function () { $('briefNeed').value = ''; toast('Brief handed over, in its fixed form.'); load(); }).catch(fail);
    });
    $('fromContact').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var a = $('contactAddress').value.trim(); if (a) connectAddress(a);
    });
    $('newSpace').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var t = $('spaceTitle').value.trim(); if (!t) return;
      API.post('/api/link/spaces', { title: t, kind: $('spaceKind').value, silo: $('spaceSide').value }).then(function (got) { location.href = got.url; }).catch(fail);
    });
    ['strangers', 'openNet', 'findable'].forEach(function (id) {
      $(id).addEventListener('change', function () {
        var body = {}; body[{ strangers: 'strangers', openNet: 'open_network', findable: 'findable_by_email' }[id]] = $(id).checked;
        API.post('/api/link/settings', body).then(function () { load(); }).catch(function (e) { fail(e); load(); });
      });
    });
    $('logClose').addEventListener('click', closeLog);
    $('scrim').addEventListener('click', closeLog);
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeLog(); });
    $('themeSwitch').addEventListener('click', function () {
      var root = document.documentElement;
      var dark = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
      root.setAttribute('data-theme', dark ? 'light' : 'dark');
      try { localStorage.setItem('link-theme', root.getAttribute('data-theme')); } catch (e) {}
    });
    try { var th = localStorage.getItem('link-theme'); if (th) document.documentElement.setAttribute('data-theme', th); } catch (e) {}
    load();
    setInterval(load, 20000);
  });
})();
