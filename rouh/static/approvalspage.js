/* Approvals, at /mail/approvals, under Now: every email and message Rouh
   stopped on for the person's decision, in its group's queue, and the latest
   after them (`rouh/mail_cases.py` `queue`, `rouh/web/trusted.py`).

   A page of its own, drawn by the server, until 15 October 2026, when Petar
   asked for it in the navigation under Now and inside Rouh with the orb, like
   every other page: "It is not a setting page, it is content page"
   (fr_37cea76c6db3). A case, `/mail/case/<key>`, opens in this same layer,
   so going to one and back never leaves Rouh or its orb (fr_7d4948ef128b):
   its one page, drawn by the server (`mail_case.html`, with what they asked
   and the decisions on it at the top, `mailcasepage.js`), in a frame here,
   since Petar asked for the case's two pages to be one, at one address
   (fr_65ed87c8685b).

   The layer, its address and its row in the navigation are app/runs.js's
   (`approvalsOpen`), handed over through `window.RouhApprovalsHost`. */
(function () {
  'use strict';

  var A = { open: false, key: '', data: null, error: '', loading: false, seq: 0 };

  function host() { return window.RouhApprovalsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function cut(text, most) {
    text = String(text || '');
    return text.length > most ? text.slice(0, most - 1) + '…' : text;
  }

  /* ---- reading ---- */

  function load() {
    var seq = ++A.seq;
    A.loading = true;
    A.error = '';
    if (!A.data) { draw(); }
    return fetch('/api/mail/approvals', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent('/mail/approvals'); return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== A.seq) { return; }
          A.loading = false;
          if (!r.ok || !j) {
            A.error = (j && j.error) || 'The approvals could not be read. Try again in a moment.';
          } else {
            A.data = j;
          }
          draw();
        });
      })
      .catch(function () {
        if (seq !== A.seq) { return; }
        A.loading = false;
        A.error = 'The server could not be reached. Try again in a moment.';
        draw();
      });
  }

  /* ---- drawing ---- */

  function row(r, waiting) {
    var a = el('a', 'ap-row');
    a.href = '/mail/case/' + encodeURIComponent(r.key);
    a.addEventListener('click', function (e) {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || !host().go) { return; }
      e.preventDefault();
      host().go(a.getAttribute('href'));
    });
    a.appendChild(el('span', 'ap-who', r.who || r.address || '(somebody)'));
    a.appendChild(el('span', 'ap-pill ap-' + (waiting ? 'warn' : (r.pill || 'busy')),
                     waiting ? 'Decide' : r.stage_words));
    var what = (r.subject || '(no subject)') + (r.when ? ' · ' + r.when : '');
    var more = r.blocker || (!waiting && r.outcome) || '';
    if (more) { what += ' · ' + cut(more, 140); }
    a.appendChild(el('span', 'ap-what', what));
    if (r.address) { a.title = r.address; }
    return a;
  }

  function section(name, rows, waiting) {
    var s = el('section', 'ap-sec' + (waiting ? ' ap-waiting' : ''));
    s.setAttribute('aria-label', name);
    var h = el('h4', 'ap-h', name);
    h.appendChild(el('span', 'ap-n', String(rows.length)));
    s.appendChild(h);
    var list = el('div', 'ap-list');
    rows.forEach(function (r) { list.appendChild(row(r, waiting)); });
    s.appendChild(list);
    return s;
  }

  function draw() {
    var body = $('approvalsBody');
    var meta = $('approvalsMeta');
    if (!body || A.key) { return; }
    body.setAttribute('aria-busy', A.loading ? 'true' : 'false');
    var d = A.data;
    if (meta) {
      meta.textContent = !d || d.off ? '' :
        d.waiting === 1 ? '1 waiting for your decision' :
        d.waiting ? d.waiting + ' waiting for your decision' : 'Nothing waiting';
    }
    var page = el('div', 'ap-page');
    var intro = el('p', 'settings-help ap-intro',
      "Email and messages Rouh stopped on for your decision: your trusted contacts' in each " +
      "contact's queue, and everybody else's after them. A queue only sorts: it never gives " +
      'anybody trust or permission. ');
    if (d && d.contacts) {
      var set = el('a', 'ap-contacts', 'Set up the queues in Trusted contacts');
      set.href = d.contacts;
      set.addEventListener('click', function (e) {
        if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || !host().go) { return; }
        e.preventDefault();
        host().go(d.contacts);
      });
      intro.appendChild(set);
      intro.appendChild(document.createTextNode('.'));
    }
    page.appendChild(intro);
    if (A.error) {
      page.appendChild(el('p', 'ap-error', A.error));
    }
    if (!d) {
      if (!A.error) { page.appendChild(el('p', 'ap-said', 'Reading the approvals…')); }
      body.replaceChildren(page);
      return;
    }
    if (d.off) {
      page.appendChild(el('p', 'ap-empty', 'New mail is not handled on this server, so there is nothing to decide.'));
      body.replaceChildren(page);
      return;
    }
    if (d.queues && d.queues.length) {
      d.queues.forEach(function (q) { page.appendChild(section(q.name, q.rows || [], true)); });
    } else {
      var none = el('p', 'ap-empty', 'Nothing is waiting for your decision.');
      none.id = 'nothingWaiting';
      page.appendChild(none);
    }
    if (d.recent && d.recent.length) {
      page.appendChild(section('Lately', d.recent, false));
    }
    body.replaceChildren(page);
  }

  /* ---- the layer ---- */

  /* One case: its page, in a frame filling the layer's body. The frame asks the case's own
     address for it (`trusted.case`), and the page sends its links back out through the host.
     Until that page has loaded, the frame is out of sight and "Loading..." stands in its place
     (`.ap-loading`): Safari paints a frame white until its page draws, which was a white
     sheet inside Rouh on every case opened (fr_2da2f1984247). */
  var FRAME_WAIT_LONGEST = 10000;
  function framed(body, key, hash) {
    // The step the address points at (#approval-2, a line in Decisions), carried to the page.
    var at = /^#[A-Za-z0-9_-]{1,80}$/.test(hash || '') ? hash : '';
    var src = '/mail/case/' + encodeURIComponent(key) + '?framed=1' + at;
    var f = body.querySelector('iframe.ap-frame');
    if (f && f.getAttribute('data-key') === key) {
      if (at) { try { f.contentWindow.location.hash = at; } catch (e) { /* not loaded yet */ } }
      return;
    }
    f = el('iframe', 'ap-frame');
    f.id = 'caseFrame';
    f.title = 'The case';
    f.setAttribute('data-key', key);
    var frame = f;
    function drawn() {
      frame.removeEventListener('load', loaded);
      if (frame.parentNode === body) { body.classList.remove('ap-loading'); }
    }
    // Safari says a new frame has loaded its first, blank page as soon as it is put in: only
    // the case's own page counts (the frame is the same origin, so its address can be read).
    function loaded() {
      var at = '';
      try { at = frame.contentWindow.location.href; } catch (e) { at = src; }
      if (at && at !== 'about:blank') { drawn(); }
    }
    frame.addEventListener('load', loaded);
    setTimeout(drawn, FRAME_WAIT_LONGEST);
    frame.src = src;
    body.classList.add('ap-loading');
    body.replaceChildren(frame, el('p', 'ap-wait', 'Loading…'));
  }

  /* With a key, one case, in a frame in this layer's body; without, the list. */
  function shown(key, hash) {
    A.open = true;
    A.key = key || '';
    var body = $('approvalsBody');
    var meta = $('approvalsMeta');
    if (!body) { return; }
    body.classList.toggle('ap-framed', !!A.key);
    if (!A.key) { body.classList.remove('ap-loading'); }
    if (A.key) {
      if (meta) { meta.textContent = ''; }
      framed(body, A.key, hash);
      return;
    }
    body.scrollTop = 0;
    draw();
    load();
  }
  function hidden() {
    A.open = false;
    // A case's page asks after itself every few seconds: closed, it goes.
    var body = $('approvalsBody');
    if (body && A.key) { body.classList.remove('ap-framed', 'ap-loading'); body.replaceChildren(); }
    A.key = '';
  }

  window.RouhApprovals = { shown: shown, hidden: hidden, reload: load };

  var x = $('approvalsClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
