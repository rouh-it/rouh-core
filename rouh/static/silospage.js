/* Settings, Silos, at /settings/silos (`rouh/silos.py`, `rouh/web/silos.py`).

   Petar, 12 October 2026: "Make a silo setting in settings. This will control
   how many silos you have and what they are called. Maybe a person has more
   than two. And then everything will get labeled - data, emails, calendars
   etc".

   The first card is the silos themselves: each with its colour and its name,
   what it holds, who sees it until you say otherwise, and the words that put
   a contact in it; renamed in place, recoloured with one press, moved up and
   down, and deleted. Deleting one that still holds anything asks which silo
   it all moves to, and nothing is ever left in a silo that is not there.

   The cards under it are the source rules, which do the labelling so nobody
   has to: each project and column, every calendar, the inboxes, email
   domains and senders, shared drives, and the meetings with no calendar
   event, each with the silo it puts things in. A change is kept at once.

   A group of Settings, drawn into `#silosBody` from `/api/settings/silos`.
   Settings tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  var S = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: '', removing: '' };

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
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

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
          if (j && j.silos) S.data = j;
          if (j && j.error) { S.error = j.error; S.said = ''; }
          else if (j && j.said) { S.said = j.said; S.error = ''; }
          draw();
          return j;
        });
      })
      .catch(function () {
        S.busy = false;
        S.error = 'Rouh could not be reached. Try again.';
        draw();
        return null;
      });
  }
  function load() { return call('GET', '/api/settings/silos'); }
  function post(url, body) { S.said = ''; S.error = ''; S.editing = ''; return call('POST', url, body); }

  /* ---- the pieces ---- */

  function silosOf(d) { return d.silos || []; }
  function nameOf(d, key) {
    if (key === d.every) return 'Every silo';
    var s = silosOf(d).filter(function (x) { return x.key === key; })[0];
    return s ? s.name : '';
  }

  /* A choice of silo for one source: none (or what it follows), each silo, or every silo. */
  function siloSelect(d, value, none, label, onPick) {
    var sel = el('select', 'sl-pick');
    sel.setAttribute('aria-label', label);
    sel.appendChild(new Option(none, ''));
    silosOf(d).forEach(function (s) { sel.appendChild(new Option(s.name, s.key)); });
    sel.appendChild(new Option('Every silo', d.every));
    sel.value = value || '';
    sel.disabled = S.busy;
    sel.addEventListener('change', function () { onPick(sel.value); });
    return sel;
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('silosBody');
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
    var focus = document.activeElement && body.contains(document.activeElement) ? document.activeElement.id : '';
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.busy && !S.said ? 'Saving…' : (S.error || S.said));
    say2.setAttribute('role', 'status');
    say2.hidden = !((S.busy && !S.said) || S.error || S.said);
    page.appendChild(say2);
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading your silos…'));
      return;
    }
    page.appendChild(silosCard(S.data));
    page.appendChild(projectsCard(S.data));
    page.appendChild(calendarsCard(S.data));
    page.appendChild(mailCard(S.data));
    page.appendChild(drivesCard(S.data));
    page.appendChild(slackCard(S.data));
    if (focus && $(focus)) $(focus).focus();
  }

  function silosCard(d) {
    var s = card('Silos', plural(silosOf(d).length, 'silo'), 'sl-silos');
    s.appendChild(el('p', 'settings-help', 'The parts of your life Rouh keeps apart. Everything Rouh keeps is ' +
      'labelled with them: your memory, email, calendars, contacts, tasks and Clockwork. A thing can be in one ' +
      'silo, several or none. The rules below do the labelling, so you never have to; anything they do not ' +
      'reach is read by Rouh as it learns it, and you can change any label where you see it.'));
    s.appendChild(el('p', 'settings-help', 'Others are people you have not set: anybody who writes to Rouh, and a ' +
      'trusted contact or delegate until you tick what they see on their page in Trusted contacts. Unattended ' +
      'runs are the nightly runs that work on Rouh itself, with nobody watching. Anybody who does not see every ' +
      'silo never sees what is in none.'));
    var list = el('ol', 'hb-list sl-list');
    silosOf(d).forEach(function (one, i) { list.appendChild(siloRow(d, one, i)); });
    s.appendChild(list);
    s.appendChild(addForm());
    return s;
  }

  function held(h) {
    if (!h || !h.total) return 'Nothing in it yet';
    var parts = [];
    if (h.items) parts.push(plural(h.items, 'thing') + ' in your memory');
    if (h.clockwork) parts.push(plural(h.clockwork, 'Clockwork item'));
    if (h.rules) parts.push(plural(h.rules, 'rule'));
    if (h.people) parts.push(plural(h.people, 'person', 'people') + ' see it');
    if (h.cards) parts.push(plural(h.cards, 'payment card'));
    if (h.shipping) parts.push(plural(h.shipping, 'shipping option'));
    return parts.join(' · ');
  }

  function siloRow(d, one, i) {
    var li = el('li', 'hb-beat sl-silo');
    li.setAttribute('aria-label', one.name);
    li.style.setProperty('--silo', one.hex);

    var top = el('div', 'sl-top');
    top.appendChild(el('span', 'sl-dot'));
    var name = el('input', 'sl-name');
    name.type = 'text';
    name.id = 'slName-' + one.key;
    name.value = one.name;
    name.maxLength = 40;
    name.setAttribute('aria-label', 'Name of ' + one.name);
    name.spellcheck = false;
    name.addEventListener('input', function () { S.editing = one.key; });
    function rename() {
      S.editing = '';
      var v = name.value.trim();
      if (!v || v === one.name) { name.value = one.name; return; }
      post('/api/settings/silos/change', { key: one.key, name: v });
    }
    name.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); rename(); }
      if (e.key === 'Escape') { name.value = one.name; S.editing = ''; name.blur(); }
    });
    name.addEventListener('blur', rename);
    top.appendChild(name);
    top.appendChild(el('span', 'sl-held', held(one.held)));
    li.appendChild(top);

    // Its colour: the page's seven, and any other.
    var colours = el('div', 'sl-colours');
    colours.setAttribute('role', 'group');
    colours.setAttribute('aria-label', 'Colour of ' + one.name);
    (d.colours || []).forEach(function (c) {
      var on = one.colour === c.name;
      var sw = el('button', 'sl-sw');
      sw.type = 'button';
      sw.style.setProperty('--cc', c.hex);
      sw.setAttribute('aria-pressed', on ? 'true' : 'false');
      sw.setAttribute('aria-label', c.name.charAt(0).toUpperCase() + c.name.slice(1));
      sw.title = sw.getAttribute('aria-label');
      sw.disabled = S.busy;
      sw.addEventListener('click', function () {
        if (!on) post('/api/settings/silos/change', { key: one.key, colour: c.name });
      });
      colours.appendChild(sw);
    });
    var any = el('label', 'sl-any');
    any.title = 'Any colour';
    var custom = /^#/.test(one.colour);
    var wheel = el('input', 'sl-wheel');
    wheel.type = 'color';
    wheel.value = one.hex;
    wheel.setAttribute('aria-label', 'Any colour for ' + one.name);
    wheel.addEventListener('change', function () { post('/api/settings/silos/change', { key: one.key, colour: wheel.value }); });
    var swAny = el('span', 'sl-sw sl-sw-any' + (custom ? ' on' : ''));
    if (custom) swAny.style.setProperty('--cc', one.hex);
    swAny.appendChild(wheel);
    any.appendChild(swAny);
    colours.appendChild(any);
    li.appendChild(colours);

    // Who sees it until you say otherwise.
    var who = el('div', 'sl-who');
    [['others', 'Others see it'], ['runs', 'Unattended runs see it']].forEach(function (f) {
      var lab = el('label', 'sl-tick');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = !!one[f[0]];
      box.disabled = S.busy;
      box.addEventListener('change', function () {
        var change = { key: one.key };
        change[f[0]] = box.checked;
        post('/api/settings/silos/change', change);
      });
      lab.appendChild(box);
      lab.appendChild(el('span', '', f[1]));
      who.appendChild(lab);
    });
    li.appendChild(who);

    // The words that put a contact in it, and tell Rouh what it covers.
    var more = el('details', 'sl-words');
    if (S.editing === 'words-' + one.key) more.open = true;
    more.appendChild(el('summary', '', 'Words for it' + (one.words ? ': ' + one.words.split(',').slice(0, 4).join(',') + (one.words.split(',').length > 4 ? '…' : '') : '')));
    more.appendChild(el('p', 'settings-help', 'What it covers, as words, with commas between. A contact whose ' +
      'relationship to you says one of them is in it, and Rouh reads them to know what belongs here.'));
    var area = el('textarea', 'sl-words-in');
    area.id = 'slWords-' + one.key;
    area.rows = 3;
    area.value = one.words || '';
    area.setAttribute('aria-label', 'Words for ' + one.name);
    area.addEventListener('input', function () { S.editing = 'words-' + one.key; });
    more.appendChild(area);
    var acts0 = el('div', 'hb-actions');
    acts0.appendChild(button('Save words', '', function () {
      post('/api/settings/silos/change', { key: one.key, words: area.value });
    }));
    more.appendChild(acts0);
    li.appendChild(more);

    var acts = el('div', 'hb-actions sl-acts');
    var up = button('Move up', '', function () { post('/api/settings/silos/move', { key: one.key, by: -1 }); },
      'Put ' + one.name + ' one place higher');
    up.disabled = S.busy || i === 0;
    acts.appendChild(up);
    var down = button('Move down', '', function () { post('/api/settings/silos/move', { key: one.key, by: 1 }); },
      'Put ' + one.name + ' one place lower');
    down.disabled = S.busy || i === silosOf(d).length - 1;
    acts.appendChild(down);
    var del = button('Delete', 'danger sl-del', function () {
      if (one.held && one.held.total) { S.removing = one.key; S.said = ''; S.error = ''; draw(); return; }
      if (!window.confirm('Delete ' + one.name + '? Nothing is in it.')) return;
      post('/api/settings/silos/remove', { key: one.key });
    }, 'Delete ' + one.name);
    del.disabled = S.busy || silosOf(d).length < 2;
    acts.appendChild(del);
    li.appendChild(acts);
    if (S.removing === one.key) li.appendChild(removeForm(d, one));
    return li;
  }

  /* Deleting a silo that holds things: which silo they all move to, asked
     before anything is deleted. */
  function removeForm(d, one) {
    var f = el('form', 'hb-form sl-remove');
    f.setAttribute('aria-label', 'Delete ' + one.name);
    f.appendChild(el('p', 'sl-remove-said', one.name + ' holds ' + held(one.held).toLowerCase() +
      '. Nothing is deleted with it: everything in it moves to the silo you pick.'));
    var lab = el('label', 'hb-field wide');
    lab.appendChild(el('span', '', 'Move what is in ' + one.name + ' to'));
    var sel = el('select');
    sel.id = 'slMoveTo-' + one.key;
    silosOf(d).forEach(function (s) { if (s.key !== one.key) sel.appendChild(new Option(s.name, s.key)); });
    lab.appendChild(sel);
    f.appendChild(lab);
    var acts = el('div', 'hb-actions');
    var go = el('button', 'ctl small danger', 'Move it and delete ' + one.name);
    go.type = 'submit';
    go.disabled = S.busy;
    acts.appendChild(go);
    acts.appendChild(button('Cancel', '', function () { S.removing = ''; draw(); }));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      S.removing = '';
      post('/api/settings/silos/remove', { key: one.key, to: sel.value });
    });
    return f;
  }

  function addForm() {
    var f = el('form', 'hb-form sl-add');
    f.setAttribute('aria-label', 'Add a silo');
    f.setAttribute('autocomplete', 'off');
    var row = el('div', 'hb-row');
    var lab = el('label', 'hb-field wide');
    lab.appendChild(el('span', '', 'A new silo'));
    var input = el('input');
    input.type = 'text';
    input.id = 'slAddName';
    input.maxLength = 40;
    input.placeholder = 'Family, a company, a project of your own';
    input.addEventListener('input', function () { S.editing = 'add'; });
    lab.appendChild(input);
    row.appendChild(lab);
    var add = el('button', 'ctl small', 'Add silo');
    add.type = 'submit';
    row.appendChild(add);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var name = input.value.trim();
      if (!name) { S.error = 'Give the new silo a name.'; S.editing = ''; draw(); return; }
      post('/api/settings/silos/add', { name: name });
    });
    return f;
  }

  function rule(d, kind, match, label) {
    var got = (d.rules || []).filter(function (r) { return r.kind === kind && r.match === match; })[0];
    return got ? got.silo : '';
  }
  function setRule(kind, match, silo, label) {
    post('/api/settings/silos/rule', { kind: kind, match: match, silo: silo, label: label || '' });
  }

  function sourceRow(name, sub, select) {
    var li = el('li', 'sl-src');
    var words = el('span', 'sl-src-name');
    words.appendChild(el('span', '', name));
    if (sub) words.appendChild(el('span', 'sl-src-sub', sub));
    li.appendChild(words);
    li.appendChild(select);
    return li;
  }

  function projectsCard(d) {
    var s = card('Projects and columns', '', 'sl-projects');
    s.appendChild(el('p', 'settings-help', 'A task takes its project’s silo, or its column’s, and everything ' +
      'inside it follows: its files, chats and cards. A chat in General is in no silo.'));
    var list = el('ul', 'sl-srcs');
    (d.projects || []).forEach(function (p) {
      var from = p.follows_from || 'its column';
      var none = p.follows ? 'Same as ' + from + (from === nameOf(d, p.follows) ? '' : ' (' + nameOf(d, p.follows) + ')')
        : 'In no silo';
      var row = sourceRow(p.title, p.depth ? p.folder : 'column', siloSelect(d, p.silo, none, 'Silo of ' + p.title,
        function (v) { setRule('project', p.folder, v, p.title); }));
      if (p.depth) row.classList.add('sl-inner');
      list.appendChild(row);
    });
    if (!(d.projects || []).length) list.appendChild(el('li', 'hb-empty', 'No projects yet.'));
    s.appendChild(list);
    return s;
  }

  function calendarsCard(d) {
    var s = card('Calendars', '', 'sl-calendars');
    s.appendChild(el('p', 'settings-help', 'Every calendar Rouh can see, and the silo its events are in. A ' +
      'meeting from your meeting library is in its calendar event’s silo.'));
    var list = el('ul', 'sl-srcs');
    (d.calendars || []).forEach(function (c) {
      list.appendChild(sourceRow(c.name, c.name !== c.id ? c.id : '', siloSelect(d, rule(d, 'calendar', c.id), 'In no silo',
        'Silo of the calendar ' + c.name, function (v) { setRule('calendar', c.id, v, c.name); })));
    });
    if (!(d.calendars || []).length) list.appendChild(el('li', 'hb-empty', 'No calendars yet: connect Google in Email and calendar.'));
    s.appendChild(list);
    if (d.google_calendars_said && (d.calendars || []).length) s.appendChild(el('p', 'hb-note', 'Google’s own list could not be read: ' + d.google_calendars_said));
    var meet = el('div', 'sl-src sl-meet');
    meet.appendChild(el('span', 'sl-src-name', 'Meetings with no calendar event'));
    meet.appendChild(siloSelect(d, rule(d, 'meetings', ''), 'In no silo', 'Silo of meetings with no calendar event',
      function (v) { setRule('meetings', '', v); }));
    s.appendChild(meet);
    return s;
  }

  function mailCard(d) {
    var s = card('Email', '', 'sl-mail');
    s.appendChild(el('p', 'settings-help', 'An email is in its sender’s silo, else their domain’s, else their ' +
      'contact’s when that contact is in one silo, else its inbox’s. Mail that already came in is labelled ' +
      'again whenever a rule changes; anything no rule reaches is read by Rouh.'));
    var list = el('ul', 'sl-srcs');
    (d.inboxes || []).forEach(function (a) {
      list.appendChild(sourceRow(a, 'inbox', siloSelect(d, rule(d, 'inbox', a), 'In no silo', 'Silo of the inbox ' + a,
        function (v) { setRule('inbox', a, v); })));
    });
    (d.rules || []).filter(function (r) { return r.kind === 'domain' || r.kind === 'sender'; }).forEach(function (r) {
      var row = sourceRow(r.match, r.kind === 'domain' ? 'everyone at this domain' : 'this sender',
        siloSelect(d, r.silo, 'Take the rule away', (r.kind === 'domain' ? 'Silo of the domain ' : 'Silo of the sender ') + r.match,
          function (v) { setRule(r.kind, r.match, v); }));
      list.appendChild(row);
    });
    s.appendChild(list);
    // A new rule: a domain or a sender, and its silo.
    var f = el('form', 'hb-form sl-rule-add');
    f.setAttribute('aria-label', 'Add an email rule');
    var row = el('div', 'hb-row');
    var lab = el('label', 'hb-field wide');
    lab.appendChild(el('span', '', 'A domain or an address'));
    var input = el('input');
    input.type = 'text';
    input.id = 'slRuleMatch';
    input.placeholder = 'example.com, or someone@example.com';
    input.spellcheck = false;
    input.setAttribute('autocomplete', 'off');
    input.addEventListener('input', function () { S.editing = 'rule'; });
    lab.appendChild(input);
    row.appendChild(lab);
    var lab2 = el('label', 'hb-field');
    lab2.appendChild(el('span', '', 'Is in'));
    var sel = el('select');
    sel.id = 'slRuleSilo';
    silosOf(d).forEach(function (one) { sel.appendChild(new Option(one.name, one.key)); });
    lab2.appendChild(sel);
    row.appendChild(lab2);
    var add = el('button', 'ctl small', 'Add rule');
    add.type = 'submit';
    row.appendChild(add);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var m = input.value.trim();
      if (!m) { S.error = 'Type a domain or an address first.'; S.editing = ''; draw(); return; }
      setRule(m.indexOf('@') > 0 ? 'sender' : 'domain', m, sel.value);
    });
    s.appendChild(f);
    return s;
  }

  function drivesCard(d) {
    var s = card('Shared drives', '', 'sl-drives');
    s.appendChild(el('p', 'settings-help', 'A file in a shared drive is in that drive’s silo. Drive files are ' +
      'not in Rouh’s memory yet; when they are, they take these.'));
    var list = el('ul', 'sl-srcs');
    (d.drives || []).forEach(function (one) {
      list.appendChild(sourceRow(one.name, '', siloSelect(d, rule(d, 'drive', one.id), 'In no silo',
        'Silo of the shared drive ' + one.name, function (v) { setRule('drive', one.id, v, one.name); })));
    });
    if (!(d.drives || []).length) {
      list.appendChild(el('li', 'hb-empty', d.drives_said ? 'Google’s shared drives could not be read: ' + d.drives_said
        : 'No shared drives.'));
    }
    s.appendChild(list);
    return s;
  }

  function slackCard(d) {
    var s = card('Slack', '', 'sl-slack');
    var row = el('div', 'sl-src sl-meet');
    row.appendChild(el('span', 'sl-src-name', 'Everything Rouh keeps from Slack'));
    row.appendChild(siloSelect(d, rule(d, 'slack', ''), 'Work (the default)', 'Silo of what Rouh keeps from Slack',
      function (v) { setRule('slack', '', v); }));
    s.appendChild(row);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = ''; S.error = ''; S.removing = '';
    draw();
    load();
  }
  function hiddenNow() { S.open = false; }

  window.RouhSilos = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
