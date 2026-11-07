/* Trials, in Evolution, at `/evolution/trials` (`rouh/web/trials.py`, `rouh/trials/`).

   Petar, 4 November 2026, on the first version: "Terrible first version of trials." What he asked for:
   "1. I need to be able to see and manage the people testing the software. I want to be able to add more
   people and remove them. I want to see their full profile and everything written on them. 2. I want a
   list of jobs. Each job will have multiple tries and has to say who did it, but only when I click on the
   job. Then I see the trials for that job specifically, and for each try, I want to see the different
   problems and discuss them." With the best of the two earlier tests he liked, Mira's ten use cases
   (30-43) and Teodora's bug hunt (30-44): a tester who reads like a real person, each try told step by
   step with its screenshot and the tester's own words, problems worst first with what should have
   happened, what did and how to fix it, a severity filter, screenshots that open full size, ticking and
   copying, Send as feedback and Edit before sending, and a page on how it works with its words explained.

   The look since 7 November 2026 is the "Page atlas", the design that scored best in design test 3
   (task 169, step 169-09, run v2-full, direction B), installed on Petar's word: "Take the best one from
   the v2 full and install it." Everything hangs off the pages of Rouh being tested: the Atlas draws one
   phone per page with one mark per open problem, shaped by how bad it is; the Fix list puts the worst
   first beside a page-by-severity grid; a try is a storyboard of phone frames; a problem has its story on
   the left, the talk with Rouh on the right and the decisions in a bar that stays at the bottom; the
   testers (the Cast) are in the header on every page, each with a pause button. Only real data: what the
   design drew from numbers Rouh does not record (cost, trait dials, a stop button for a run) is not here.

   The pages, each its own address under /evolution/trials:
     ''                 the Atlas: a verdict, the tiles, the latest tries, the pages of Rouh, what needs
                        you, and the jobs (what is being tested; who tried each is inside a job)
     job/<n>            one job: its goal and what it covers, its tries as a ladder and a list
     <n>                one try: its storyboard, step by step, how it ended, and its problems, worst first
     problems           the Fix list: every problem across the jobs, open first, worst first
     problem/<n>        one problem: its story, every sighting, its talk with Rouh, and what to do with it
     testers            the Cast; testers/new adds one; tester/<key> one whole; tester/<key>/edit changes one
     how                how trials work, and the words they use
   `window.RouhTrials` is what `evolutionpage.js` mounts. Plain words only: Vesela tries this page too. */
(function () {
  'use strict';

  var API = '/api/trials';
  var S = { root: null, top: null, main: null, sub: '', host: null, data: {}, error: '', said: '', busy: '', seq: 0,
            poll: 0, shell: null, open: null, jobsFilter: { persona: '', result: '' },
            probFilter: { status: 'open', who: '', job: '' }, probView: { screen: null, bad: '', group: false, all: false },
            tryBad: '', ticked: {}, confirm: '', editJob: false, deciding: false, draft: null, form: null, carry: '',
            sayDraft: null, step: {}, toast: null };

  var RESULT = {
    passed: ['Passed', 'green'], failed: ['Did not pass', 'rose'], running: ['Trying now', 'amber'],
    queued: ['Waiting to start', 'slate'], broken: ['Could not finish', 'slate']
  };
  var MANAGED = { yes: 'Yes', partly: 'Partly', no: 'No' };
  // Said of the tester, by name of what they are: "Confused them" left Vesela asking who "them" is (trial 21).
  var BAD = { blocked: 'Stopped the tester', confused: 'Confused the tester', annoyed: 'Annoyed the tester', minor: 'Small' };
  var BAD_SHORT = { blocked: 'Stopped', confused: 'Confused', annoyed: 'Annoyed', minor: 'Small' };
  var BAD_ORDER = ['blocked', 'confused', 'annoyed', 'minor'];
  var BAD_TONE = { blocked: 'rose', confused: 'amber', annoyed: 'violet', minor: 'slate' };
  var STAND = {
    open: ['Not fixed yet', 'amber'], decided: ['Decided how to fix it', 'blue'], fixed: ['Fixed', 'green'],
    set_aside: ['Set aside', 'slate']
  };
  var VERDICT_LINE = { not_a_problem: 'Not a problem', wont_fix: 'Won’t fix', decided: 'Decided how to fix it',
                       sent: 'Sent as feedback' };
  var RULE = 'Fixed only when a later try passes the same screen without tripping on it. Sent is never shown as fixed.';

  /* ---- small things ---- */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text) {
    var b = el('button', cls, text);
    b.type = 'button';
    return b;
  }
  function go(href) { if (S.host && S.host.go) { S.host.go(href); } else { location.href = href; } }
  function link(text, href, cls) {
    var a = el('a', cls || 'tr-a', text);
    a.href = href;
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
      e.preventDefault();
      go(href);
    });
    return a;
  }
  var HOME = '/evolution/trials';
  function call(path, body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    // A read that never answers is said, never left as "Opening…" for ever (Vesela, trial 20). Rouh's
    // answer in a discussion and its draft of a tester take longer, and wait longer.
    var ctl = window.AbortController ? new AbortController() : null;
    var slow = /\/say$|\/draft$|\/run$|\/again$/.test(path);
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, slow ? 240000 : 45000) : 0;
    if (ctl) { init.signal = ctl.signal; }
    if (body !== undefined) {
      init.method = 'POST';
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    return fetch(API + path, init).then(function (r) {
      clearTimeout(timer);
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that just now. Try again in a moment.'); }
        return j;
      });
    }, function (e) {
      clearTimeout(timer);
      throw new Error(e && e.name === 'AbortError' ? 'This page did not open in time. Nothing was lost.'
        : 'Rouh could not be reached just now. Nothing was lost.');
    });
  }
  function day(t) {
    return t ? new Date(t * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
  }
  function dayShort(t) { return t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : ''; }
  function date(t) { return t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function minutes(s) {
    var m = Math.round((s || 0) / 60);
    return m < 1 ? 'under a minute' : m === 1 ? '1 minute' : m + ' minutes';
  }
  function minShort(s) { var m = Math.round((s || 0) / 60); return m < 1 ? '<1 min' : m + ' min'; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function chip(text, tone) { return el('span', 'tr-chip tr-tone-' + tone, text); }
  function result(state, t) {
    if (t && stuck(t)) { return chip('Stuck since ' + dayShort(t.started_at || t.created_at), 'rose'); }
    var r = RESULT[state] || ['Not tried yet', 'slate']; return chip(r[0], r[1]);
  }
  /* How many different problems a try found: the same unit as "not fixed". */
  function foundN(t) { return t.found_n != null ? t.found_n : (t.problems || 0); }
  function upper(text) { text = String(text || ''); return text.charAt(0).toUpperCase() + text.slice(1); }
  function first(name) { return String(name || '').split(/\s+/)[0]; }
  /* Which try it is. A review has no rounds: nothing is fixed between its tries until the owner chooses. */
  function tryName(n, mode) {
    if (mode === 'review') { return 'Review you asked for'; }
    return n >= 3 ? 'Third and last try' : n === 2 ? 'Second try, after fixes' : 'First try';
  }
  /* The two modes, said plainly (Petar, 4 November 2026). */
  function modeChip(mode) {
    return mode === 'review' ? chip('Review you asked for', 'blue') : chip('Automatic test while building', 'slate');
  }
  function said(label, text, cls) {
    var p = el('p', 'tr-said' + (cls ? ' ' + cls : ''));
    p.appendChild(el('span', 'tr-label', label));
    p.appendChild(el('span', '', text));
    return p;
  }
  function section(cls, title, id) {
    var s = el('section', 'tr-sec' + (cls ? ' ' + cls : ''));
    if (id) { s.id = id; }
    if (title) { s.appendChild(el('h2', 'tr-h2', title)); }
    return s;
  }
  function fail(e) { S.busy = ''; S.error = String((e && e.message) || e); draw(); }
  /* Says where inside Evolution the page is, once for each place: telling it again redraws the whole layer. */
  function moved(title) {
    var said = S.sub + '\n' + (title || '');
    if (S.movedSaid === said || !S.host || !S.host.moved) { return; }
    S.movedSaid = said;
    S.host.moved('trials', S.sub, title || '');
  }

  /* ---- the drawn marks: icons, and a shape for each kind of problem, so colour is never the only sign ---- */

  var ICON = {
    pause: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/><rect x="9.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/></svg>',
    play: '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>',
    phone: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="4" y="1.5" width="10" height="15" rx="2.5"/><path d="M7.5 4h3"/><path d="M9 8v5M6.5 10.5h5"/></svg>',
    up: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M7 12V2M2.5 6.5 7 2l4.5 4.5"/></svg>',
    down: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M7 2v10M2.5 7.5 7 12l4.5-4.5"/></svg>',
    flat: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M2 7h10M8 3l4 4-4 4"/></svg>',
    one: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="7" cy="7" r="3"/></svg>',
    check: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M2.5 7.5 5.5 10.5 11.5 3.5"/></svg>',
    wait: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M3.5 1.5h7M3.5 12.5h7M4.5 1.5c0 3 5 3.5 5 5.5s-5 2.5-5 5.5M9.5 1.5c0 3-5 3.5-5 5.5s5 2.5 5 5.5"/></svg>',
    ask: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="7" cy="7" r="5.5"/><path d="M5.3 5.4a1.8 1.8 0 1 1 2.4 1.7c-.5.2-.7.6-.7 1.1M7 10.2v.1"/></svg>',
    x: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg>',
    clock: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="9" cy="9" r="7"/><path d="M9 5v4.5l3 2"/></svg>',
    review: '<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4.5 12.5V8a4.5 4.5 0 0 1 9 0v4.5l1.5 1.5H3z"/><path d="M7.5 16h3"/></svg>',
    tap: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 7V2.5a1 1 0 0 1 2 0V7l3.5.8c.6.2 1 .8.9 1.4l-.6 3.3H5.5L3 9.5a1 1 0 0 1 1.4-1.4z"/></svg>',
    plus: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 3v10M3 8h10"/></svg>'
  };
  var SHAPE = {
    blocked: '<path d="M3.6 .6h4.8l3 3v4.8l-3 3H3.6l-3-3V3.6z" fill="var(--s-blocked)"/>',
    annoyed: '<path d="M6 .6 11.5 11H.5z" fill="var(--s-annoyed)"/>',
    confused: '<path d="M6 .4 11.6 6 6 11.6 .4 6z" fill="var(--s-confused)"/>',
    minor: '<circle cx="6" cy="6" r="4" fill="none" stroke="var(--s-minor)" stroke-width="2.4"/>'
  };
  /* Only the fixed strings above ever go through innerHTML: nothing a person or a tester wrote. */
  function icon(name) { var s = el('span', 'tr-ic'); s.innerHTML = ICON[name] || ''; s.setAttribute('aria-hidden', 'true'); return s; }
  function shape(bad, size) {
    var s = el('span', 'tr-shape');
    s.innerHTML = '<svg width="' + (size || 12) + '" height="' + (size || 12) + '" viewBox="0 0 12 12" aria-hidden="true">' +
      (SHAPE[bad] || SHAPE.minor) + '</svg>';
    return s;
  }
  function sev(bad, long) {
    var s = el('span', 'tr-sev');
    s.appendChild(shape(bad, 13));
    s.appendChild(el('span', '', long ? (BAD[bad] || bad) : (BAD_SHORT[bad] || bad)));
    return s;
  }
  function withIcon(node, name, text) { node.appendChild(icon(name)); if (text != null) { node.appendChild(el('span', '', text)); } return node; }
  function badChip(b) { return chip(BAD[b] || b, BAD_TONE[b] || 'slate'); }
  /* Sent or decided, and then hit again by a later try: the fix did not hold. Read from its sightings. */
  function seenAgain(p) {
    if (p.standing !== 'decided' || !p.verdict_at) { return null; }
    var later = (p.sightings || []).filter(function (x) { return x.at > p.verdict_at; });
    return later.length ? later[0] : null;
  }
  /* Where a problem stands, in one line with its sign. */
  function standBadge(p) {
    var s = el('span', 'tr-state');
    if (p.awaiting_choice) { return withIcon(s, 'ask', 'Waiting for your choice'); }
    if (p.standing === 'fixed') { s.classList.add('is-fixed'); return withIcon(s, 'check', p.closed_by ? 'Fixed: try ' + p.closed_by + ' got past it' : 'Fixed'); }
    if (p.standing === 'set_aside') { return withIcon(s, 'x', 'Set aside: ' + (VERDICT_LINE[p.verdict] || 'set aside')); }
    var again = seenAgain(p);
    if (again) { s.classList.add('is-again'); return withIcon(s, 'up', (p.verdict === 'sent' ? 'Sent' : 'Decided') + ', but seen again' + (again.trial ? ' in try ' + again.trial : '')); }
    if (p.standing === 'decided' && p.verdict === 'sent') { return withIcon(s, 'wait', 'Sent as feedback, waiting for a re-test'); }
    if (p.standing === 'decided') { return withIcon(s, 'wait', 'Decided how to fix it, waiting for a re-test'); }
    return withIcon(s, 'ask', 'Needs your decision');
  }
  /* The proof chain: a problem is fixed only when a later try gets past it, never when a fix is sent. */
  function chain(p) {
    var c = el('div', 'tr-chain');
    c.setAttribute('aria-label', 'How far it is from fixed');
    function n(cls, ic, text) { var x = el('span', 'tr-chain-n' + (cls ? ' ' + cls : '')); if (ic) { x.appendChild(icon(ic)); } x.appendChild(el('span', '', text)); c.appendChild(x); }
    function ln() { var l = el('span', 'tr-chain-ln'); l.setAttribute('aria-hidden', 'true'); c.appendChild(l); }
    if (p.standing === 'fixed') {
      n('done', 'check', p.verdict ? (VERDICT_LINE[p.verdict] || 'Decided') : 'Found'); ln();
      n('ok', 'check', p.closed_by ? 'Try ' + p.closed_by + ' got past it' : 'A later try got past it'); ln(); n('ok', 'check', 'Fixed');
    } else if (p.standing === 'set_aside') {
      n('done', 'x', VERDICT_LINE[p.verdict] || 'Set aside'); ln(); n('', '', 'No longer counted');
    } else if (seenAgain(p)) {
      var ag = seenAgain(p);
      n('done', 'check', (p.verdict === 'sent' ? 'Sent ' : 'Decided ') + dayShort(p.verdict_at)); ln();
      n('bad', 'up', ag.trial ? 'Try ' + ag.trial + ' hit it again' : 'Seen again ' + dayShort(ag.at)); ln(); n('bad', '', 'Not fixed');
    } else if (p.standing === 'decided') {
      n('done', 'check', (p.verdict === 'sent' ? 'Sent ' : 'Decided ') + dayShort(p.verdict_at)); ln(); n('', 'wait', 'Re-test pending'); ln(); n('', '', 'Fixed');
    } else {
      n('', '', 'Not decided'); ln(); n('', '', 'Re-test'); ln(); n('', '', 'Fixed');
    }
    return c;
  }

  /* A face for a tester: their initials on a colour that is always theirs, with a dot while paused. */
  function hueOf(t) {
    var key = (t && (t.key || t.id || t.persona)) || (t && t.name) || '?';
    var h = 7;
    for (var i = 0; i < key.length; i++) { h = (h * 31 + key.charCodeAt(i) * 97) % 9973; }
    return (h * 137) % 360;
  }
  function initials(t) {
    var name = (t && (t.name || t.persona_name || t.first)) || '?';
    var parts = String(name).trim().split(/\s+/);
    return (parts[0] || '?').charAt(0).toUpperCase() + (parts.length > 1 ? parts[parts.length - 1].charAt(0).toUpperCase() : '');
  }
  function face(t, size, paused) {
    var f = el('span', 'tr-face' + (size ? ' tr-face-' + size : ''), initials(t));
    f.style.setProperty('--hue', String(hueOf(t)));
    f.setAttribute('aria-hidden', 'true');
    if (paused != null) {
      var d = el('span', 'tr-face-dot' + (paused ? ' is-paused' : ''));
      if (paused) { d.innerHTML = '<svg width="7" height="7" viewBox="0 0 8 8"><rect x="1" y="1" width="2" height="6" fill="#fff"/><rect x="5" y="1" width="2" height="6" fill="#fff"/></svg>'; }
      f.appendChild(d);
    }
    return f;
  }
  function testerOf(key) {
    var all = (S.shell && S.shell.testers) || [];
    for (var i = 0; i < all.length; i++) { if (all[i].key === key) { return all[i]; } }
    return null;
  }
  function crumbs(items) {
    var nav = el('nav', 'tr-crumbs');
    nav.setAttribute('aria-label', 'Where you are');
    items.forEach(function (it, i) {
      if (i === items.length - 1) { var c = el('span', '', it[0]); c.setAttribute('aria-current', 'page'); nav.appendChild(c); return; }
      nav.appendChild(link(it[0], it[1]));
      var sep = el('span', 'tr-crumb-sep', '›');
      sep.setAttribute('aria-hidden', 'true');
      nav.appendChild(sep);
    });
    return nav;
  }

  /* A screenshot that opens full size over the page, and closes with Escape, a press anywhere, or Close. */
  function shot(src, alt, cls) {
    var b = button('tr-shot-btn' + (cls ? ' ' + cls : ''), null);
    b.setAttribute('aria-label', 'Open this picture full size: ' + alt);
    var img = el('img');
    img.src = src;
    img.alt = alt;
    img.loading = 'lazy';
    b.appendChild(img);
    b.addEventListener('click', function (e) { e.stopPropagation(); bigPicture(src, alt, b); });
    return b;
  }
  function bigPicture(src, alt, back) {
    var box = el('div', 'tr-big');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', alt);
    var close = button('tr-btn tr-big-close', 'Close');
    var img = el('img');
    img.src = src;
    img.alt = alt;
    box.appendChild(close);
    box.appendChild(img);
    box.appendChild(el('p', 'tr-big-cap', alt));
    function shut() {
      document.removeEventListener('keydown', key, true);
      box.remove();
      if (back && back.focus) { back.focus(); }
    }
    function key(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); shut(); } }
    box.addEventListener('click', shut);
    document.addEventListener('keydown', key, true);
    document.body.appendChild(box);
    close.focus();
  }

  /* A profile's Markdown, drawn as plain paragraphs and lists, with **bold** kept. Never as HTML. */
  function prose(text) {
    var out = el('div', 'tr-prose');
    var list = null;
    String(text || '').split('\n').forEach(function (line) {
      var t = line.trim();
      if (!t) { list = null; return; }
      var item = /^[-*]\s+(.*)$/.exec(t);
      var host;
      if (item) {
        if (!list) { list = el('ul'); out.appendChild(list); }
        host = el('li');
        list.appendChild(host);
        t = item[1];
      } else {
        list = null;
        host = el('p');
        out.appendChild(host);
      }
      t.split(/(\*\*[^*]+\*\*)/).forEach(function (bit) {
        if (/^\*\*[^*]+\*\*$/.test(bit)) { host.appendChild(el('strong', '', bit.slice(2, -2))); }
        else if (bit) { host.appendChild(document.createTextNode(bit)); }
      });
    });
    return out;
  }

  /* A short message at the bottom, with Undo when what was done can be taken back. */
  function toast(text, undo) {
    clearTimeout(S.toastTimer);
    S.toast = { text: text, undo: undo || null };
    drawToast();
    S.toastTimer = setTimeout(function () { S.toast = null; drawToast(); }, undo ? 8000 : 4000);
  }
  function drawToast() {
    if (!S.root) { return; }
    var old = S.root.querySelector('.tr-toast');
    if (old) { old.remove(); }
    if (!S.toast) { return; }
    var t = el('div', 'tr-toast');
    t.setAttribute('role', 'status');
    t.appendChild(el('span', '', S.toast.text));
    if (S.toast.undo) {
      var u = button('tr-toast-b', 'Undo');
      var fn = S.toast.undo;
      u.addEventListener('click', function () { S.toast = null; drawToast(); fn(); });
      t.appendChild(u);
    }
    S.root.appendChild(t);
  }

  /* ---- where we are, and reading it ---- */

  function where() {
    var s = S.sub, m;
    if (!s) { return { page: 'jobs' }; }
    if (/^\d+$/.test(s)) { return { page: 'try', n: s }; }
    if ((m = /^job\/(\d+)$/.exec(s))) { return { page: 'job', n: m[1] }; }
    if ((m = /^problem\/(\d+)$/.exec(s))) { return { page: 'problem', n: m[1] }; }
    if (s === 'problems') { return { page: 'problems' }; }
    if (s === 'testers') { return { page: 'testers' }; }
    if (s === 'testers/new') { return { page: 'form' }; }
    if ((m = /^tester\/([a-z0-9]+)\/edit$/.exec(s))) { return { page: 'form', key: m[1] }; }
    if ((m = /^tester\/([a-z0-9]+)$/.exec(s))) { return { page: 'tester', key: m[1] }; }
    if (s === 'how') { return { page: 'how' }; }
    return { page: 'jobs' };
  }

  /* What the header and the Atlas stand on: every job, the newest tries, the counts and the testers. */
  function loadShell() {
    return call('').then(function (j) { S.shell = j; if (!where().page.match(/^jobs$/)) { drawTop(); } return j; });
  }

  function load() {
    var seq = ++S.seq, w = where(), want;
    S.error = '';
    function keep(name) { return function (j) { if (seq === S.seq) { S.data[name] = j; } }; }
    if (w.page === 'jobs') {
      var q = [];
      if (S.jobsFilter.persona) { q.push('persona=' + encodeURIComponent(S.jobsFilter.persona)); }
      if (S.jobsFilter.result) { q.push('result=' + encodeURIComponent(S.jobsFilter.result)); }
      want = Promise.all([
        loadShell(),
        q.length ? call('?' + q.join('&')) : Promise.resolve(null),
        call('/problems?status=open'),
        loadAll()
      ]).then(function (got) {
        if (seq !== S.seq) { return; }
        S.data.jobs = got[1] || got[0];
        S.open = got[2];
      });
    } else {
      var shellFirst = S.shell ? null : loadShell().catch(function () {});
      if (w.page === 'problems' || w.page === 'testers') { shellFirst = Promise.all([shellFirst, loadAll()]); }
      if (w.page === 'job') { want = call('/jobs/' + w.n).then(keep('job')); }
      else if (w.page === 'try') { want = call('/' + w.n).then(keep('try')); }
      else if (w.page === 'problems') { want = loadProblems(seq); }
      else if (w.page === 'problem') { want = call('/problems/' + w.n).then(keep('problem')); }
      else if (w.page === 'testers') { want = call('/testers?archived=1').then(keep('testers')); }
      else if (w.page === 'tester') { want = call('/testers/' + w.key).then(keep('tester')); }
      else if (w.page === 'form') {
        want = w.key ? call('/testers/' + w.key).then(function (j) {
          if (seq === S.seq) { S.data.tester = j; if (!S.form || S.form.key !== w.key) { S.form = formFrom(j.tester); } }
        }) : (S.form && !S.form.key ? Promise.resolve() : call('/testers').then(function (j) {
          if (seq === S.seq) { S.form = blankForm(j.sections || []); }
        }));
      } else { want = Promise.resolve(); }
      if (shellFirst) { want = Promise.all([want, shellFirst]); }
    }
    return want.then(function () { if (seq === S.seq) { draw(); } }, function (e) {
      if (seq !== S.seq) { return; }
      S.error = String((e && e.message) || e);
      draw();
    });
  }
  /* Every problem, for counts that must agree: seen again apart from waiting, and who found what. */
  function loadAll() {
    return call('/problems?status=all').then(function (j) { S.all = j.problems || []; }, function () { S.all = null; });
  }
  function againN() { return (S.all || []).filter(seenAgain).length; }
  /* Who found what, adding up to the total: a problem several testers hit is said once, and the owner's own too. */
  function foundLine(testers) {
    var all = S.all;
    if (!all || !all.length) { return ''; }
    var names = {};
    (testers || []).forEach(function (t) { names[t.key] = t.first; });
    var per = {}, both = 0, mine = 0;
    all.forEach(function (p) {
      if (p.source === 'owner') { mine += 1; return; }
      var ks = p.personas || [];
      if (ks.length > 1) { both += 1; }
      ks.forEach(function (k) { per[k] = (per[k] || 0) + 1; });
    });
    var parts = Object.keys(per).map(function (k) { return (names[k] || upper(k)) + ' found ' + per[k]; });
    var extra = [];
    if (both) { extra.push(both + ' found by more than one tester'); }
    if (mine) { extra.push(mine + ' by you'); }
    return parts.join(', ') + (extra.length ? '; ' + extra.join(' and ') : '') + ', ' + all.length + ' in all.';
  }
  function loadProblems(seq) {
    var f = S.probFilter, q = [];
    q.push('status=' + (f.status === 'again' ? 'decided' : f.status || 'all'));
    if (f.who === 'owner') { q.push('source=owner'); } else if (f.who) { q.push('persona=' + encodeURIComponent(f.who)); }
    if (f.job) { q.push('job=' + encodeURIComponent(f.job)); }
    return call('/problems?' + q.join('&')).then(function (j) { if (seq === S.seq) { S.data.problems = j; } });
  }

  /* ---- drawing ---- */

  function draw() {
    var root = S.root;
    if (!root || !root.isConnected) { return; }
    var keep = document.activeElement && root.contains(document.activeElement) && document.activeElement.id;
    root.textContent = '';
    S.top = el('header', 'tr-top');
    S.main = el('div', 'tr-main');
    root.appendChild(S.top);
    root.appendChild(S.main);
    var w = where();
    drawTop();
    var main = S.main;
    if (S.error) {
      var err = el('div', 'tr-err');
      err.appendChild(el('p', 'tr-err-words', S.error));
      var again = button('tr-btn', 'Open this page again');
      again.addEventListener('click', function () { S.error = ''; draw(); load(); });
      err.appendChild(again);
      main.appendChild(err);
    }
    if (S.said) { main.appendChild(el('p', 'tr-saidnow', S.said)); }
    ({ jobs: drawJobs, job: drawJob, 'try': drawTry, problems: drawProblems, problem: drawProblem,
       testers: drawTesters, tester: drawTester, form: drawForm, how: drawHow })[w.page](main, w);
    // At the end of a long page, the way back to every list, so nobody has to press Back three times (trial 17).
    if (w.page === 'job' || w.page === 'try' || w.page === 'problem' || w.page === 'tester') {
      var foot = el('nav', 'tr-foot');
      foot.setAttribute('aria-label', 'Back to a list');
      foot.appendChild(el('span', 'tr-dim', 'Back to:'));
      [['The Atlas', HOME], ['The Fix list', HOME + '/problems'], ['The testers', HOME + '/testers'],
       ['Add a tester', HOME + '/testers/new']].forEach(function (x) {
        foot.appendChild(link(x[0], x[1]));
      });
      main.appendChild(foot);
    }
    drawToast();
    if (keep) { var back = document.getElementById(keep); if (back) { back.focus(); } }
  }

  /* The header on every page: the four places, the testers with their pause buttons, and Run a trial. */
  function drawTop() {
    var top = S.top;
    if (!top) { return; }
    top.textContent = '';
    var page = where().page;
    var on = page === 'job' || page === 'try' || page === 'jobs' ? 'jobs'
      : page === 'problem' || page === 'problems' ? 'problems'
      : page === 'tester' || page === 'testers' || page === 'form' ? 'testers' : 'how';
    var sh = S.shell;
    var nav = el('nav', 'tr-nav');
    nav.setAttribute('aria-label', 'Trials');
    [['jobs', 'Atlas', '', HOME], ['problems', 'Fix list', '', HOME + '/problems'], ['testers', 'Cast', 'Testers', HOME + '/testers'],
     ['how', 'How it works', '', HOME + '/how']].forEach(function (v) {
      var a = link('', v[3], 'tr-nav-a' + (v[2] ? ' is-two' : ''));
      var top1 = el('span', 'tr-nav-w', v[1]);
      if (v[0] === 'problems' && sh && sh.counts && sh.counts.by) {
        var c = el('span', 'tr-nav-count', String(sh.counts.by.open));
        c.title = sh.counts.by.open + ' need your decision';
        top1.appendChild(c);
      }
      a.appendChild(top1);
      if (v[2]) { a.appendChild(el('span', 'tr-nav-sub', v[2])); }
      if (on === v[0]) { a.setAttribute('aria-current', 'page'); }
      nav.appendChild(a);
    });
    top.appendChild(nav);
    var cast = el('div', 'tr-cast');
    cast.setAttribute('role', 'group');
    cast.setAttribute('aria-label', 'The testers');
    cast.appendChild(el('span', 'tr-cast-lbl', 'Cast'));
    var live = sh ? (sh.testers || []).filter(function (t) { return !t.archived; }) : [];
    live.forEach(function (t) {
      var held = !!t.paused || !!(sh && sh.paused_all);
      var m = el('span', 'tr-member');
      var a = link('', HOME + '/tester/' + t.key, 'tr-member-a');
      a.appendChild(face(t, '', held));
      a.setAttribute('aria-label', t.name + ', ' + (held ? 'paused' : 'testing'));
      a.title = t.name + (held ? ', paused' : ', testing');
      m.appendChild(a);
      if (!(sh && sh.paused_all)) {
        var b = button('tr-member-b', null);
        b.appendChild(icon(t.paused ? 'play' : 'pause'));
        b.setAttribute('aria-label', (t.paused ? 'Resume ' : 'Pause ') + t.first);
        b.title = (t.paused ? 'Resume ' : 'Pause ') + t.first;
        b.addEventListener('click', function () { setPause(t.key, !t.paused, t.first); });
        m.appendChild(b);
      }
      cast.appendChild(m);
    });
    if (sh && live.length) { cast.appendChild(pauseAllButton(live, !!sh.paused_all, 'tr-btn')); }
    top.appendChild(cast);
    var run = button('tr-btn tr-outline tr-run', null);
    withIcon(run, 'phone', 'Run a trial');
    run.addEventListener('click', function () { openStart(); });
    top.appendChild(run);
  }

  /* One button for everyone: the switch that pauses every tester, or, when each is paused on their own,
     resuming each of them. With every tester paused on their own, a second Pause only made people doubt (trial 37). */
  function pauseAllButton(live, switchOn, cls) {
    var every = live.length > 0 && live.every(function (t) { return t.paused; });
    var b = button(cls || 'tr-btn', null);
    if (switchOn) {
      withIcon(b, 'play', 'Resume all');
      b.addEventListener('click', function () { setPause('', false, ''); });
    } else if (every) {
      withIcon(b, 'play', 'Resume all');
      b.addEventListener('click', function () { live.forEach(function (t) { setPause(t.key, false, t.first, true); }); toast('Every tester is testing again.'); });
    } else {
      withIcon(b, 'pause', 'Pause all');
      b.addEventListener('click', function () { setPause('', true, ''); });
    }
    b.setAttribute('aria-label', switchOn || every ? 'Resume all testing' : 'Pause all testing');
    return b;
  }

  function choose(label, value, options, onChange) {
    var wrap = el('label', 'tr-choose');
    wrap.appendChild(el('span', 'tr-label', label));
    var s = el('select', 'tr-select');
    // Named by its label alone: wrapped in it, a screen reader also read every option into the name.
    s.setAttribute('aria-label', label);
    options.forEach(function (o) {
      var opt = el('option', '', o[1]);
      opt.value = o[0];
      if (value === o[0]) { opt.selected = true; }
      s.appendChild(opt);
    });
    s.addEventListener('change', function () { onChange(s.value); });
    wrap.appendChild(s);
    return wrap;
  }

  /* ---- the Atlas ---- */

  function finished(t) { return t.state === 'passed' || t.state === 'failed'; }
  /* A try still going an hour after it began is stuck: a try takes minutes. Rouh has no way to stop one yet. */
  function stuck(t) { return (t.state === 'running' || t.state === 'queued') && (t.started_at || t.created_at) < Date.now() / 1000 - 3600; }
  function stuckOf(key) { return ((S.shell && S.shell.trials) || []).filter(function (t) { return stuck(t) && (!key || t.persona === key); }); }

  /* The verdict at the top, in a sentence: did the newest try of each job pass, who is paused, what is going. */
  function verdictLine(sh) {
    var jobs = (sh.jobs || []).filter(function (j) { return j.latest; });
    if (!jobs.length) { return 'Nothing has been tried yet. When Rouh changes something you will see, a tester tries it first.'; }
    var by = {};
    jobs.forEach(function (j) { by[j.latest.state] = (by[j.latest.state] || 0) + 1; });
    var parts = [];
    if ((by.passed || 0) === jobs.length) { parts.push('Yes. The newest try of every job passed.'); }
    else {
      var bits = [];
      if (by.failed) { bits.push((by.failed === jobs.length ? 'The newest try of all ' + jobs.length + ' jobs' : 'The newest try of ' + by.failed + ' of ' + jobs.length + ' jobs') + ' did not pass'); }
      if (by.broken) { bits.push((bits.length ? '' : 'The newest try of ') + plural(by.broken, 'job') + (bits.length ? ' could not finish' : ' could not finish')); }
      var going = jobs.filter(function (j) { return j.latest.state === 'running' || j.latest.state === 'queued'; });
      var jammed = going.filter(function (j) { return stuck(trialOf(sh, j.latest.number) || {}); });
      if (going.length > jammed.length) { bits.push(plural(going.length - jammed.length, 'job') + ' ' + (going.length - jammed.length === 1 ? 'is' : 'are') + ' being tried now'); }
      if (jammed.length) {
        var since = trialOf(sh, jammed[0].latest.number);
        bits.push(plural(jammed.length, 'try', 'tries') + ' ' + (jammed.length === 1 ? 'has' : 'have') + ' been stuck since ' + dayShort(since.started_at || since.created_at));
      }
      if (by.passed) { bits.push(by.passed + ' passed'); }
      parts.push('Not yet. ' + upper(bits.join(', ')) + '.');
    }
    var live = (sh.testers || []).filter(function (t) { return !t.archived; });
    var held = live.filter(function (t) { return t.paused; });
    if (sh.paused_all) { parts.push('All testing is paused.'); }
    else if (held.length && held.length === live.length) { parts.push(live.length === 2 ? 'Both testers are paused.' : 'Every tester is paused.'); }
    else if (held.length) { parts.push(held.map(function (t) { return t.first; }).join(' and ') + (held.length === 1 ? ' is paused.' : ' are paused.')); }
    return parts.join(' ');
  }

  function trialOf(sh, n) { return ((sh && sh.trials) || []).filter(function (t) { return t.number === n; })[0] || null; }

  /* Better or worse: each job's newest finished try against its own try before, never two jobs mixed. */
  function trends(sh) {
    var per = {};
    (sh.trials || []).slice().sort(function (a, b) { return a.created_at - b.created_at; }).forEach(function (t) {
      if (t.job && finished(t)) { (per[t.job] = per[t.job] || []).push(t); }
    });
    var out = [];
    (sh.jobs || []).forEach(function (j) {
      var l = per[j.number] || [];
      if (l.length < 2) { out.push({ job: j, dir: 'one', last: l.length ? foundN(l[l.length - 1]) : null }); return; }
      var a = foundN(l[l.length - 2]), b = foundN(l[l.length - 1]);
      out.push({ job: j, dir: b > a ? 'worse' : b < a ? 'better' : 'same', prev: a, last: b,
                 prevTry: l[l.length - 2].number, lastTry: l[l.length - 1].number });
    });
    return out;
  }

  function stat(title, href) {
    var s = href ? link('', href, 'tr-stat') : el('div', 'tr-stat');
    s.appendChild(el('div', 'tr-stat-what', title));
    return s;
  }

  function drawJobs(root) {
    var sh = S.shell, d = S.data.jobs;
    moved('');
    if (!sh || !d) { if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the Atlas…')); } return; }
    root.appendChild(el('h1', 'tr-headline', verdictLine(sh)));
    var open = (S.open && S.open.problems) || [];
    var by = (sh.counts && sh.counts.by) || {};

    var tiles = el('div', 'tr-grid4');
    // Problems, by how bad, the same set the pages below are drawn from.
    var t1 = stat('Problems', HOME + '/problems');
    t1.appendChild(el('div', 'tr-big-n', by.open + ' to decide'));
    var sevN = {};
    open.forEach(function (p) { sevN[p.how_bad] = (sevN[p.how_bad] || 0) + 1; });
    if (open.length) {
      var bar = el('div', 'tr-sevbar');
      bar.setAttribute('aria-hidden', 'true');
      BAD_ORDER.forEach(function (b) { if (sevN[b]) { var i = el('i'); i.style.flex = String(sevN[b]); i.style.background = 'var(--s-' + b + ')'; bar.appendChild(i); } });
      t1.appendChild(bar);
    }
    var leg = el('div', 'tr-legend');
    BAD_ORDER.forEach(function (b) { if (sevN[b]) { var x = el('span'); x.appendChild(shape(b)); x.appendChild(el('span', '', sevN[b] + ' ' + BAD_SHORT[b].toLowerCase())); leg.appendChild(x); } });
    t1.appendChild(leg);
    var rest = el('div', 'tr-legend');
    var ag = againN();
    if (by.decided - ag > 0) { rest.appendChild(withIcon(el('span'), 'wait', (by.decided - ag) + ' decided, waiting for a re-test')); }
    if (ag) { rest.appendChild(withIcon(el('span', 'is-again'), 'up', ag + ' sent, but seen again')); }
    if (by.set_aside) { rest.appendChild(withIcon(el('span'), 'x', by.set_aside + ' set aside')); }
    if (by.fixed) { rest.appendChild(withIcon(el('span', 'is-fixed'), 'check', by.fixed + ' fixed')); }
    t1.appendChild(rest);
    tiles.appendChild(t1);

    var tr = trends(sh);
    var cmp = tr.filter(function (x) { return x.dir !== 'one'; });
    var worse = cmp.filter(function (x) { return x.dir === 'worse'; }).length;
    var better = cmp.filter(function (x) { return x.dir === 'better'; }).length;
    var t2 = stat('Better or worse');
    if (!cmp.length) {
      t2.appendChild(el('div', 'tr-big-n', 'No trend yet'));
      t2.appendChild(el('p', 'tr-cap', 'No job has two finished tries among the newest ones yet.'));
    } else {
      t2.appendChild(el('div', 'tr-big-n', worse >= better ? worse + ' worse' : better + ' better'));
      var big = cmp.slice().sort(function (a, b) { return Math.abs(b.last - b.prev) - Math.abs(a.last - a.prev); })[0];
      t2.appendChild(el('p', 'tr-cap', 'Of ' + plural(cmp.length, 'job') + ' with two finished tries, each against its own try before: ' +
        better + ' better, ' + (cmp.length - better - worse) + ' the same, ' + worse + ' worse.' +
        (big && big.last !== big.prev ? ' Biggest change: ' + big.job.name + ', ' + big.prev + ' → ' + big.last + ' problems.' : '')));
      var arrows = el('div', 'tr-arrows');
      tr.forEach(function (x) {
        var a = icon(x.dir === 'worse' ? 'up' : x.dir === 'better' ? 'down' : x.dir === 'same' ? 'flat' : 'one');
        a.title = x.job.name + ': ' + (x.dir === 'one' ? 'one finished try so far' : x.prev + ' → ' + x.last + ' problems');
        a.removeAttribute('aria-hidden');
        a.setAttribute('role', 'img');
        a.setAttribute('aria-label', a.title);
        arrows.appendChild(a);
      });
      t2.appendChild(arrows);
    }
    tiles.appendChild(t2);

    // Tested lately: the tries of the last seven days, a bar for each day.
    var week = Date.now() / 1000 - 7 * 86400;
    var recent = (sh.trials || []).filter(function (t) { return t.created_at >= week; });
    var t3 = stat('Tested lately');
    t3.appendChild(el('div', 'tr-big-n', plural(recent.length, 'try', 'tries')));
    var who = {};
    recent.forEach(function (t) { who[t.persona_name] = (who[t.persona_name] || 0) + 1; });
    var whoLine = Object.keys(who).map(function (k) { return k + ' ' + who[k]; }).join(', ');
    t3.appendChild(el('p', 'tr-cap', recent.length ? 'In the last 7 days, by ' + whoLine + '.' : 'None in the last 7 days.'));
    if (recent.length) {
      var bars = el('div', 'tr-bars');
      bars.setAttribute('aria-hidden', 'true');
      var most = 1, days = [];
      for (var k = 6; k >= 0; k--) {
        var d0 = new Date(); d0.setHours(0, 0, 0, 0); d0.setDate(d0.getDate() - k);
        var from = d0.getTime() / 1000, n = recent.filter(function (t) { return t.created_at >= from && t.created_at < from + 86400; }).length;
        days.push([d0.getDate(), n]);
        most = Math.max(most, n);
      }
      days.forEach(function (x) { var s = el('span'); var b = el('b'); b.style.height = Math.round(x[1] / most * 100) + '%'; s.appendChild(b); s.appendChild(el('span', '', String(x[0]))); bars.appendChild(s); });
      t3.appendChild(bars);
      t3.appendChild(el('p', 'tr-cap', 'Tries each day, by date'));
    }
    tiles.appendChild(t3);

    var live = (sh.testers || []).filter(function (t) { return !t.archived; });
    var heldN = sh.paused_all ? live.length : live.filter(function (t) { return t.paused; }).length;
    var t4 = stat('Testers', HOME + '/testers');
    t4.appendChild(el('div', 'tr-big-n', (live.length - heldN) + ' of ' + live.length + ' testing'));
    t4.appendChild(el('p', 'tr-cap', sh.paused_all ? 'All testing is paused. No tester starts a new try until you resume.'
      : heldN ? live.filter(function (t) { return t.paused; }).map(function (t) { return t.first; }).join(' and ') + (heldN === 1 ? ' is' : ' are') + ' paused.'
      : 'Every tester tries changes as usual.'));
    var faces = el('div', 'tr-faces');
    live.forEach(function (t) { faces.appendChild(face(t, 'xs', !!t.paused || !!sh.paused_all)); });
    t4.appendChild(faces);
    tiles.appendChild(t4);
    root.appendChild(tiles);

    // The newest tries, in a row.
    var tries = (sh.trials || []).slice(0, 5);
    if (tries.length) {
      var lt = el('section', 'tr-latest');
      lt.appendChild(el('h2', 'tr-h3', 'Latest tries'));
      var ol = el('ol');
      tries.forEach(function (t) {
        var li = el('li');
        var a = link('', HOME + '/' + t.number);
        a.appendChild(face(testerOf(t.persona) || { key: t.persona, name: t.persona_name }));
        var m = el('span', 'tr-lr-m');
        var tt = el('span', 'tr-lr-t');
        tt.appendChild(el('b', '', 'Try ' + t.number));
        tt.appendChild(document.createTextNode(' · ' + (t.job_name || upper(t.subject) || 'A page of Rouh')));
        m.appendChild(tt);
        m.appendChild(el('span', 'tr-lr-s', t.persona_name + ', ' + day(t.created_at)));
        m.appendChild(el('span', 'tr-lr-r' + (t.state === 'running' || t.state === 'queued' ? ' is-live' : ''),
          stuck(t) ? 'Stuck since ' + dayShort(t.started_at || t.created_at) : t.state === 'running' ? 'Trying now' : t.state === 'queued' ? 'Waiting to start' : t.state === 'broken' ? 'Could not finish: no report'
            : foundN(t) ? plural(foundN(t), 'problem') : t.state === 'passed' ? 'Passed, no problems' : 'No problems'));
        a.appendChild(m);
        li.appendChild(a);
        ol.appendChild(li);
      });
      lt.appendChild(ol);
      root.appendChild(lt);
    }

    var lay = el('div', 'tr-atlas');
    var left = el('section', 'tr-pages');
    var lh = el('div', 'tr-sec-head');
    lh.appendChild(el('h2', 'tr-h2', 'The pages of Rouh'));
    var key = el('div', 'tr-legend');
    BAD_ORDER.forEach(function (b) { var x = el('span'); x.appendChild(shape(b)); x.appendChild(el('span', '', BAD_SHORT[b])); key.appendChild(x); });
    key.appendChild(el('span', '', 'one mark for each problem to decide'));
    lh.appendChild(key);
    left.appendChild(lh);
    left.appendChild(pagePhones(open, sh));
    lay.appendChild(left);
    lay.appendChild(needsYou(open, sh));
    root.appendChild(lay);

    drawJobList(root, d);
  }

  /* One drawn phone for each page of Rouh with a problem to decide, one mark per problem, worst first. */
  function pagePhones(open, sh) {
    var groups = {}, order = [];
    open.forEach(function (p) {
      var k = p.screen || '';
      if (!groups[k]) { groups[k] = { key: k, name: p.screen_name || 'Somewhere in Rouh', list: [] }; order.push(k); }
      groups[k].list.push(p);
    });
    var wrap = el('div', 'tr-tiles');
    if (!order.length) {
      wrap.appendChild(el('p', 'tr-empty', (sh.counts && sh.counts.trials) ? 'No page has a problem waiting for your decision.'
        : 'Nothing has been tried yet, so no page has a problem.'));
      return wrap;
    }
    var jobsByPage = {};
    (sh.jobs || []).forEach(function (j) { if (j.page) { (jobsByPage[j.page] = jobsByPage[j.page] || []).push(j); } });
    var tr = {};
    trends(sh).forEach(function (x) { tr[x.job.number] = x; });
    order.sort(function (a, b) { return groups[b].list.length - groups[a].list.length; });
    order.forEach(function (k) {
      var g = groups[k];
      var tile = link('', HOME + '/problems', 'tr-tile');
      tile.addEventListener('click', function () { S.probFilter = { status: 'open', who: '', job: '' }; S.probView = { screen: k, bad: '', group: false, all: false }; }, true);
      tile.setAttribute('aria-label', g.name + ': ' + plural(g.list.length, 'problem') + ' to decide. Open them in the Fix list.');
      var ph = el('div', 'tr-phone');
      ph.appendChild(el('div', 'tr-pname', g.name));
      var stopped = g.list.filter(function (p) { return p.how_bad === 'blocked'; }).length;
      ph.appendChild(el('div', 'tr-pnum', g.list.length + ' to decide' + (stopped ? ', ' + stopped + ' stopped the tester' : '')));
      var dots = el('div', 'tr-dots');
      g.list.slice().sort(function (a, b) { return BAD_ORDER.indexOf(a.how_bad) - BAD_ORDER.indexOf(b.how_bad); })
        .forEach(function (p) { dots.appendChild(shape(p.how_bad)); });
      ph.appendChild(dots);
      var js = jobsByPage[k] || [];
      if (js.length) {
        var foot = el('div', 'tr-pfoot');
        js.slice(0, 2).forEach(function (j) {
          var x = tr[j.number];
          var line = el('span', 'tr-trend');
          line.appendChild(icon(!x || x.dir === 'one' ? 'one' : x.dir === 'worse' ? 'up' : x.dir === 'better' ? 'down' : 'flat'));
          line.appendChild(el('span', '', (js.length > 1 ? first(j.name) + ': ' : '') + (!x || x.dir === 'one' ? 'one finished try, no trend yet'
            : (x.dir === 'same' ? 'Same' : upper(x.dir)) + ': ' + x.prev + ' → ' + x.last)));
          foot.appendChild(line);
        });
        ph.appendChild(foot);
      }
      tile.appendChild(ph);
      var lastJob = js.slice().sort(function (a, b) { return (b.last_at || 0) - (a.last_at || 0); })[0];
      if (lastJob && lastJob.last_at) { tile.appendChild(el('div', 'tr-under', 'Last tried ' + day(lastJob.last_at))); }
      wrap.appendChild(tile);
    });
    return wrap;
  }

  /* What needs the person: tries going now or stuck, reviews waiting on a choice, pauses, the worst problems. */
  function needsYou(open, sh) {
    var box = el('section', 'tr-needs');
    box.appendChild(el('h2', 'tr-h2', 'Needs you'));
    var ul = el('ul');
    function need(ic, title, sub, href, cls) {
      var li = el('li');
      var a = href ? link('', href, 'tr-need' + (cls ? ' ' + cls : '')) : el('div', 'tr-need' + (cls ? ' ' + cls : ''));
      if (typeof ic === 'string') { a.appendChild(icon(ic)); } else { a.appendChild(ic); }
      var w = el('div', 'tr-need-w');
      w.appendChild(el('div', 'tr-need-t', title));
      if (sub) { w.appendChild(typeof sub === 'string' ? el('div', 'tr-need-s', sub) : sub); }
      a.appendChild(w);
      li.appendChild(a);
      ul.appendChild(li);
      return w;
    }
    var hour = Date.now() / 1000 - 3600;
    (sh.trials || []).filter(function (t) { return t.state === 'running' || t.state === 'queued'; }).forEach(function (t) {
      var long = (t.started_at || t.created_at) < hour;
      need('clock', long ? 'Try ' + t.number + ' stuck since ' + day(t.started_at || t.created_at) : 'Try ' + t.number + ' is going now',
        t.persona_name + ' on ' + (t.job_name || upper(t.subject) || 'a page of Rouh') + (long ? '. A try takes minutes; this one never ended. Open it to see how far it got.'
          : '. Open it to watch its steps arrive.'), HOME + '/' + t.number, long ? 'is-stuck' : '');
    });
    var waiting = open.filter(function (p) { return p.awaiting_choice; });
    if (waiting.length) {
      var w = need('review', plural(waiting.length, 'problem') + ' from a review ' + (waiting.length === 1 ? 'waits' : 'wait') + ' for your choice',
        'Nothing is fixed from a review until you choose.', HOME + '/problems', 'is-notif');
      void w;
      ul.lastChild.firstChild.addEventListener('click', function () { S.probFilter = { status: 'awaiting', who: '', job: '' }; S.probView = { screen: null, bad: '', group: false, all: false }; }, true);
    }
    (sh.jobs || []).filter(function (j) { return j.latest && j.latest.state === 'broken'; }).forEach(function (j) {
      need('x', 'Try ' + j.latest.number + ' could not finish', j.name + ': the tester gave back no report, which is not the same as no problems.', HOME + '/' + j.latest.number);
    });
    var live = (sh.testers || []).filter(function (t) { return !t.archived; });
    var held = live.filter(function (t) { return t.paused; });
    if (sh.paused_all || held.length) {
      var sub = el('div', 'tr-need-s');
      sub.appendChild(el('div', '', 'No new tries start while ' + (sh.paused_all || held.length === live.length ? (live.length === 2 ? 'they are' : 'everyone is') : (held.length === 1 ? held[0].first + ' is' : 'they are')) + ' paused.'));
      var actions = el('div', 'tr-flex');
      if (sh.paused_all || held.length === live.length) { actions.appendChild(pauseAllButton(live, !!sh.paused_all, 'tr-btn tr-btn-s')); }
      else {
        held.forEach(function (t) {
          var b = button('tr-btn tr-btn-s', null);
          withIcon(b, 'play', 'Resume ' + t.first);
          b.addEventListener('click', function () { setPause(t.key, false, t.first); });
          actions.appendChild(b);
        });
      }
      sub.appendChild(actions);
      need('pause', sh.paused_all ? 'All testing is paused' : held.length === live.length ? (live.length === 2 ? 'Both testers are paused' : 'Every tester is paused')
        : held.map(function (t) { return t.first; }).join(' and ') + (held.length === 1 ? ' is paused' : ' are paused'), sub, '');
    }
    open.filter(function (p) { return !p.awaiting_choice; }).slice(0, 3).forEach(function (p) {
      var s = el('div', 'tr-need-s');
      s.appendChild(el('span', '', BAD_SHORT[p.how_bad] + ', seen ' + (p.count === 1 ? 'once' : p.count + ' times') + (p.screen_name ? ' on ' + p.screen_name : '')));
      need(shape(p.how_bad, 14), p.what, s, HOME + '/problem/' + p.number);
    });
    box.appendChild(ul);
    var more = open.length - Math.min(3, open.filter(function (p) { return !p.awaiting_choice; }).length) - waiting.length;
    if (more > 0) { box.appendChild(link(plural(more, 'more needs', 'more need') + ' a decision in the Fix list', HOME + '/problems', 'tr-a tr-more-a')); }
    if (!ul.childNodes.length) { box.appendChild(el('p', 'tr-empty', 'Nothing needs you right now.')); }
    return box;
  }

  /* The jobs: what is being tested, never who (that is inside a job). */
  function drawJobList(root, d) {
    var sec = section('tr-jobs', 'Jobs');
    sec.appendChild(el('p', 'tr-lede', 'A job is one thing a made-up tester tries on a phone, such as signing in for ' +
      'the first time. Open a job to see each try, who did it, and the problems they ran into.'));
    var people = [['', 'Anyone']].concat(((S.shell && S.shell.testers) || []).map(function (t) { return [t.key, t.first]; }));
    if (d.jobs.length || S.jobsFilter.persona || S.jobsFilter.result) {
      var bar = el('div', 'tr-filters');
      bar.appendChild(choose('Tried by', S.jobsFilter.persona, people, function (v) { S.jobsFilter.persona = v; load(); }));
      bar.appendChild(choose('Latest try', S.jobsFilter.result, [['', 'Any result'], ['passed', 'Passed'],
        ['failed', 'Did not pass'], ['running', 'Trying now or stuck'], ['broken', 'Could not finish']],
        function (v) { S.jobsFilter.result = v; load(); }));
      sec.appendChild(bar);
    }
    if (!d.jobs.length) {
      sec.appendChild(el('p', 'tr-empty', S.jobsFilter.persona || S.jobsFilter.result ? 'No job matches that.'
        : 'Nothing has been tried yet. When Rouh changes something you will see, a tester tries it first, and the job shows up here.'));
      root.appendChild(sec);
      return;
    }
    var ul = el('ul', 'tr-list');
    d.jobs.forEach(function (j) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/job/' + j.number, 'tr-row');
      var top = el('span', 'tr-row-top');
      top.appendChild(el('span', 'tr-row-what', j.name));
      top.appendChild(result(j.latest && j.latest.state, j.latest && trialOf(S.shell, j.latest.number)));
      a.appendChild(top);
      if (j.covers || j.goal) { a.appendChild(el('span', 'tr-row-goal', j.covers || '“' + j.goal + '”')); }
      var meta = el('span', 'tr-row-meta');
      meta.appendChild(el('span', '', plural(j.tries_count, 'try', 'tries')));
      meta.appendChild(el('span', j.open ? 'tr-has' : '', j.open ? plural(j.open, 'problem') + ' not fixed'
        : j.found ? 'No problems left open' : 'No problems found'));
      if (j.last_at) { meta.appendChild(el('span', '', 'Last tried ' + day(j.last_at))); }
      a.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    root.appendChild(sec);
  }

  /* ---- one job ---- */

  function drawJob(root, w) {
    var d = S.data.job;
    if (!d || String(d.job.number) !== w.n) {
      root.appendChild(crumbs([['Atlas', HOME], ['Job ' + w.n]]));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the job…')); }
      return;
    }
    var j = d.job;
    moved(j.name);
    root.appendChild(crumbs([['Atlas', HOME], [j.name]]));
    var hub = el('div', 'tr-hub');
    var ph = el('section', 'tr-phone tr-hub-phone');
    ph.appendChild(el('h1', 'tr-h1', j.name));
    var line = el('div', 'tr-head-line');
    line.appendChild(result(j.latest && j.latest.state, j.latest && (trialOf(S.shell, j.latest.number) || j.tries[0])));
    line.appendChild(el('span', 'tr-dim', 'Job ' + j.number + ' · ' + plural(j.tries_count, 'try', 'tries') +
      (j.open ? ' · ' + plural(j.open, 'problem') + ' not fixed' : '')));
    ph.appendChild(line);
    if (S.editJob) {
      ph.appendChild(jobForm(j));
    } else {
      var g = el('div', 'tr-goal');
      g.appendChild(el('b', '', 'What the tester is asked to do'));
      g.appendChild(el('span', '', j.goal ? '“' + j.goal + '”' : 'Not written yet.'));
      ph.appendChild(g);
      if (j.covers) { var c = el('div', 'tr-goal'); c.appendChild(el('b', '', 'What it covers')); c.appendChild(el('span', '', j.covers)); ph.appendChild(c); }
      var edit = button('tr-btn tr-btn-s', j.covers ? 'Change the name or the description' : 'Describe what this job tests');
      edit.addEventListener('click', function () { S.editJob = true; draw(); });
      ph.appendChild(edit);
    }
    hub.appendChild(ph);

    // The ladder: each try a column, its height the number of problems it found.
    var lad = el('section', 'tr-ladder-sec');
    lad.appendChild(el('h2', 'tr-h3', 'Each try, oldest to newest'));
    lad.appendChild(el('p', 'tr-cap', 'The height is how many problems the try found. A dashed one gave no report, is stuck, or is still going.'));
    var wrapL = el('div', 'tr-ladder-wrap');
    var cols = el('div', 'tr-lcols');
    var most = Math.max.apply(null, [1].concat(j.tries.map(function (t) { return foundN(t); })));
    j.tries.slice().reverse().forEach(function (t) {
      var col = link('', HOME + '/' + t.number, 'tr-lcol');
      col.setAttribute('aria-label', 'Try ' + t.number + ' by ' + t.persona_name + ': ' + (stuck(t) ? 'stuck since ' + dayShort(t.started_at || t.created_at)
        : (RESULT[t.state] || ['?'])[0]) + ', ' + plural(foundN(t), 'problem'));
      var n = t.state === 'broken' ? 'no report' : stuck(t) ? 'stuck' : t.state === 'running' || t.state === 'queued' ? 'going' : String(foundN(t));
      col.appendChild(el('span', 'tr-lcol-n' + (/\D/.test(n) ? ' is-word' : ''), n));
      var bar = el('span', 'tr-lcol-bar is-' + (stuck(t) ? 'stuck' : t.state));
      if (t.state !== 'broken' && t.state !== 'running' && t.state !== 'queued') { bar.style.height = Math.max(3, Math.round(foundN(t) / most * 110)) + 'px'; }
      col.appendChild(bar);
      col.appendChild(face(testerOf(t.persona) || { key: t.persona, name: t.persona_name }, 'xs'));
      col.appendChild(el('span', 'tr-lcol-lab', 'Try ' + t.number));
      cols.appendChild(col);
    });
    if (!j.tries.length) { lad.appendChild(el('p', 'tr-empty', 'Nobody has tried it yet.')); }
    else { wrapL.appendChild(cols); lad.appendChild(wrapL); }
    hub.appendChild(lad);
    root.appendChild(hub);

    var tries = section('', 'Tries, newest first');
    var ul = el('ul', 'tr-list');
    j.tries.forEach(function (t) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/' + t.number, 'tr-row tr-try');
      var top = el('span', 'tr-row-top');
      var who = el('span', 'tr-who-line');
      who.appendChild(face(testerOf(t.persona) || { key: t.persona, name: t.persona_name }));
      var wn = el('span', 'tr-who-name');
      wn.appendChild(el('strong', '', t.persona_name));
      wn.appendChild(el('span', 'tr-dim', tryName(t.round, t.mode)));
      who.appendChild(wn);
      top.appendChild(who);
      top.appendChild(t.mode === 'review' && (t.state === 'passed' || t.state === 'failed') ? reviewChip(t) : result(t.state, t));
      a.appendChild(top);
      var meta = el('span', 'tr-row-meta');
      meta.appendChild(modeChip(t.mode));
      meta.appendChild(el('span', '', 'Try ' + t.number + ' · ' + day(t.created_at)));
      if (t.state !== 'queued') { meta.appendChild(el('span', '', plural(t.steps, 'step') + ' · ' + minutes(t.seconds))); }
      if (t.managed) { meta.appendChild(el('span', '', tryLine(t))); }
      var fn = foundN(t);
      meta.appendChild(el('span', t.open ? 'tr-has' : '', !fn ? 'No problems'
        : plural(fn, 'problem') + (t.open === fn ? ', not fixed yet' : t.open ? ', ' + t.open + ' not fixed yet' : ', all fixed or set aside')));
      a.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    tries.appendChild(ul);
    if (j.tries.length) { root.appendChild(tries); }
    root.appendChild(runAgain(d.personas || [], d['default'], function (persona) {
      return call('/jobs/' + j.number + '/run', { persona: persona });
    }, 'Ask for a review', 'A tester who has seen nothing before tries this job from the start, and you get the whole ' +
      'walk-through and what they found. It takes a few minutes. Nothing is fixed from it until you choose what.'));
    var probs = section('', 'Its problems');
    probs.appendChild(link(j.found ? 'See the ' + plural(j.found, 'problem') + ' this job found, in the Fix list' : 'No problems found yet',
      HOME + '/problems', 'tr-a'));
    probs.lastChild.addEventListener('click', function () { S.probFilter = { status: 'all', who: '', job: String(j.number) }; S.probView = { screen: null, bad: '', group: false, all: false }; }, true);
    root.appendChild(probs);
  }

  function jobForm(j) {
    var f = el('form', 'tr-form');
    var name = field(f, 'Name', 'input', j.name, 'tr-job-name');
    var goal = field(f, 'What the tester is asked to do, as they would say it', 'textarea', j.goal, 'tr-job-goal');
    var covers = field(f, 'What this job tests, in a line or two', 'textarea', j.covers, 'tr-job-covers');
    var row = el('div', 'tr-actions');
    var save = button('tr-btn tr-primary', 'Save');
    save.type = 'submit';
    var cancel = button('tr-btn', 'Cancel');
    cancel.addEventListener('click', function () { S.editJob = false; draw(); });
    row.appendChild(save);
    row.appendChild(cancel);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      save.disabled = true;
      call('/jobs/' + j.number, { name: name.value, goal: goal.value, covers: covers.value }).then(function (got) {
        S.editJob = false;
        S.data.job = { job: got.job, personas: S.data.job.personas, 'default': S.data.job['default'] };
        S.said = 'Saved.';
        draw();
      }, fail);
    });
    return f;
  }

  function field(form, label, kind, value, id) {
    var wrap = el('label', 'tr-field');
    wrap.appendChild(el('span', 'tr-label', label));
    var input = el(kind, 'tr-input' + (kind === 'textarea' ? ' tr-area' : ''));
    if (id) { input.id = id; }
    input.value = value == null ? '' : String(value);
    wrap.appendChild(input);
    form.appendChild(wrap);
    return input;
  }

  function runAgain(personas, def, start, label, words) {
    var box = section('tr-again', label);
    box.appendChild(el('p', 'tr-dim', words));
    var row = el('div', 'tr-again-row');
    // A word above the picker: "Vesela tries it" alone did not say a tester is being chosen (trial 22).
    var pl = el('label', 'tr-choose');
    pl.appendChild(el('span', 'tr-label', 'Who tries it'));
    var pick = el('select', 'tr-select');
    pick.setAttribute('aria-label', 'Who tries it');
    pl.appendChild(pick);
    personas.forEach(function (p) {
      var o = el('option', '', p.first + ' tries it' + (p.paused ? ' (paused)' : ''));
      o.value = p.id;
      if (p.id === def) { o.selected = true; }
      pick.appendChild(o);
    });
    row.appendChild(pl);
    var run = button('tr-btn tr-primary', label);
    run.disabled = !!S.busy;
    run.addEventListener('click', function () {
      S.busy = 'run'; S.said = ''; draw();
      start(pick.value).then(function (j) {
        S.busy = '';
        S.carry = j.said || 'Starting.';
        go(HOME + '/' + j.trial.number);
      }, fail);
    });
    row.appendChild(run);
    box.appendChild(row);
    return box;
  }

  /* Run a trial, from the header: pick a job and a tester, and the try opens and fills in as it goes. */
  function openStart() {
    var sh = S.shell;
    var dlg = el('dialog', 'tr-dlg');
    dlg.setAttribute('aria-labelledby', 'tr-dlg-h');
    var f = el('form', 'tr-dlg-in');
    f.method = 'dialog';
    var head = el('div', 'tr-dlg-head');
    var h = el('h2', 'tr-h2', 'Run a trial');
    h.id = 'tr-dlg-h';
    head.appendChild(h);
    var x = button('tr-icon-btn', null);
    x.appendChild(icon('x'));
    x.setAttribute('aria-label', 'Close');
    head.appendChild(x);
    f.appendChild(head);
    f.appendChild(el('p', 'tr-dim', 'A tester who has seen nothing before tries the job from the start, and you watch the steps ' +
      'arrive. It is a review you asked for: nothing is fixed from it until you choose what.'));
    var jobs = (sh && sh.jobs) || [];
    var testers = ((sh && sh.testers) || []).filter(function (t) { return !t.archived; });
    var pickJob = el('fieldset', 'tr-pick');
    pickJob.appendChild(el('legend', 'tr-label', 'Which job'));
    jobs.forEach(function (j, i) {
      var l = el('label');
      var r = el('input');
      r.type = 'radio'; r.name = 'job'; r.value = String(j.number);
      if (i === 0) { r.checked = true; }
      l.appendChild(r);
      l.appendChild(el('b', '', j.name));
      var lt = j.latest && trialOf(sh, j.latest.number);
      l.appendChild(el('span', 'tr-dim', !j.latest ? 'Not tried yet' : lt && stuck(lt) ? 'Stuck since ' + dayShort(lt.started_at || lt.created_at)
        : (RESULT[j.latest.state] || ['?'])[0] + ' last time'));
      pickJob.appendChild(l);
    });
    if (!jobs.length) { pickJob.appendChild(el('p', 'tr-empty', 'There is no job yet. A job is made the first time a change is tried.')); }
    f.appendChild(pickJob);
    var pickT = el('fieldset', 'tr-pick');
    pickT.appendChild(el('legend', 'tr-label', 'Who tries it'));
    var def = sh && sh['default'];
    var firstFree = null, anyone = null;
    // A paused tester can be picked too: Start then resumes them first, so the button is never dead.
    testers.forEach(function (t) {
      var held = !!t.paused || !!(sh && sh.paused_all);
      var l = el('label', 'tr-pick-t');
      var r = el('input');
      r.type = 'radio'; r.name = 'tester'; r.value = t.key;
      if (!anyone || t.key === def) { anyone = r; }
      if (!held && (t.key === def || !firstFree)) { firstFree = r; }
      l.appendChild(r);
      l.appendChild(face(t, '', held));
      var w = el('span');
      w.appendChild(el('b', '', t.first));
      w.appendChild(el('span', 'tr-dim', held ? ' paused' : ''));
      l.appendChild(w);
      pickT.appendChild(l);
    });
    (firstFree || anyone || {}).checked = true;
    f.appendChild(pickT);
    var err = el('p', 'tr-err-words');
    f.appendChild(err);
    var foot = el('div', 'tr-dlg-foot');
    var cancel = button('tr-btn', 'Cancel');
    var startB = button('tr-btn tr-primary', null);
    withIcon(startB, 'phone', 'Start the trial');
    startB.type = 'submit';
    startB.disabled = !testers.length || !jobs.length;
    function who() {
      var k = (f.querySelector('input[name=tester]:checked') || {}).value;
      return testers.filter(function (t) { return t.key === k; })[0] || null;
    }
    // Says what Start will do: resume the one picked, or all testing, when they are paused.
    function label() {
      var t = who();
      startB.textContent = '';
      withIcon(startB, 'phone', sh && sh.paused_all ? 'Resume all testing and start' : t && t.paused ? 'Resume ' + t.first + ' and start' : 'Start the trial');
    }
    pickT.addEventListener('change', label);
    label();
    foot.appendChild(cancel);
    foot.appendChild(startB);
    f.appendChild(foot);
    dlg.appendChild(f);
    function shut() {
      document.removeEventListener('keydown', esc, true);
      if (dlg.open) { dlg.close(); }
      dlg.remove();
    }
    // Escape closes it here, and never also closes the layer underneath.
    function esc(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); shut(); } }
    x.addEventListener('click', shut);
    cancel.addEventListener('click', shut);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) { shut(); } });
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var jn = (f.querySelector('input[name=job]:checked') || {}).value;
      var tk = (f.querySelector('input[name=tester]:checked') || {}).value;
      if (!jn || !tk) { return; }
      startB.disabled = true;
      err.textContent = '';
      var t = who();
      var resume = sh && sh.paused_all ? call('/pause', { on: false }) : t && t.paused ? call('/testers/' + t.key + '/pause', { on: false }) : Promise.resolve();
      resume.then(function () {
        if (sh && sh.paused_all) { sh.paused_all = false; } else if (t) { t.paused = false; }
        drawTop();
        return call('/jobs/' + jn + '/run', { persona: tk });
      }).then(function (j) {
        shut();
        S.carry = j.said || 'Starting.';
        S.shell = null;
        go(HOME + '/' + j.trial.number);
      }, function (e2) { startB.disabled = false; err.textContent = String((e2 && e2.message) || e2); });
    });
    document.addEventListener('keydown', esc, true);
    (S.root || document.body).appendChild(dlg);
    dlg.showModal();
    var firstInput = f.querySelector('input:checked');
    if (firstInput) { firstInput.focus(); }
  }

  /* ---- one try ---- */

  function drawTry(root, w) {
    var d = S.data['try'];
    if (!d || String(d.trial.number) !== w.n) {
      root.appendChild(crumbs([['Atlas', HOME], ['Try ' + w.n]]));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the try…')); }
      return;
    }
    var t = d.trial, name = t.persona_name;
    moved((t.job_name || upper(t.subject)) + ', try ' + t.number);
    root.appendChild(crumbs(t.job ? [['Atlas', HOME], [t.job_name, HOME + '/job/' + t.job], ['Try ' + t.number]]
      : [['Atlas', HOME], ['Try ' + t.number]]));
    var head = el('section', 'tr-runhead');
    var h = el('h1', 'tr-h1', 'Try ' + t.number + ': ' + name + ' on ' + (t.job_name || upper(t.subject) || 'a page of Rouh'));
    h.appendChild(el('small', '', tryName(t.round, t.mode) + ' · ' + day(t.created_at)));
    head.appendChild(h);
    var who = el('div', 'tr-who');
    var tt = testerOf(t.persona);
    who.appendChild(face(tt || { key: t.persona, name: name }, 'm', tt ? !!tt.paused : null));
    var nm = el('div');
    nm.appendChild(link(name, HOME + '/tester/' + t.persona, 'tr-a tr-strong'));
    nm.appendChild(document.createTextNode(', a made-up tester' + (tt && tt.age ? ', ' + tt.age : '') + (tt && tt.city ? ', ' + tt.city : '')));
    who.appendChild(nm);
    head.appendChild(who);
    head.appendChild(el('p', 'tr-goalq', '“' + t.goal + '”'));
    if (t.state !== 'queued' && t.state !== 'running') {
      var facts = el('div', 'tr-facts');
      [[String(t.steps), plural(t.steps, 'step').replace(/^\d+ /, '')], [String(foundN(t)), 'problems found' + (t.open ? ', ' + t.open + ' not fixed' : '')],
       [minShort(t.seconds), 'time it took'], [MANAGED[t.managed] || '–', 'managed it?']].forEach(function (x) {
        var f = el('div', 'tr-fact');
        f.appendChild(el('b', '', x[0]));
        f.appendChild(el('span', '', x[1]));
        facts.appendChild(f);
      });
      var res = el('div', 'tr-fact');
      res.appendChild(el('b', '', t.mode === 'review' && (t.state === 'passed' || t.state === 'failed')
        ? ({ yes: 'They managed it', partly: 'Partly managed', no: 'Did not manage' }[t.managed] || 'Done') : (RESULT[t.state] || ['–'])[0]));
      res.appendChild(el('span', '', t.mode === 'review' ? 'a review' : 'the result'));
      facts.appendChild(res);
      head.appendChild(facts);
    }
    var why = t.mode === 'review' ? '' : verdictWhy(t);
    if (why) { head.appendChild(el('p', 'tr-why', why)); }
    if (t.state === 'queued' || t.state === 'running') {
      // A try going on is read again every few seconds, so its steps appear as they happen.
      clearTimeout(S.poll);
      S.poll = setTimeout(function () { if (S.root && S.root.isConnected && S.sub === String(t.number)) { load(); } }, 5000);
      var live = el('div', 'tr-banner');
      live.appendChild(el('span', 'tr-live-dot'));
      if (stuck(t)) { live.classList.add('is-stuck'); }
      live.appendChild(el('p', '', stuck(t) ? 'Stuck since ' + day(t.started_at || t.created_at) + '. A try takes a few minutes, and this one ' +
          'never ended, so it is probably stuck. Its steps so far are below.'
        : t.state === 'queued' ? 'This try is about to start. It takes a few minutes.'
        : name + ' is trying it now. Each step appears here as it happens.'));
      head.appendChild(live);
    }
    if (t.state === 'broken') {
      var nr = el('div', 'tr-banner is-stuck');
      nr.appendChild(el('p', '', 'This try could not finish, so there is no report: ' + (t.why || 'something went wrong.') + ' That is not the same as no problems.'));
      head.appendChild(nr);
    } else if (t.why) { head.appendChild(el('p', 'tr-dim', t.why)); }
    root.appendChild(head);

    var walk = t.walk || [];
    var foundAt = {};
    (t.found || []).forEach(function (f) { (foundAt[f.step] = foundAt[f.step] || []).push(f); });
    var stuckAt = 0;
    walk.forEach(function (s) { if ((foundAt[s.n] || []).some(function (f) { return f.how_bad === 'blocked'; })) { stuckAt = s.n; } });
    var sel = S.step[t.number] || stuckAt || (walk.length ? walk[walk.length - 1].n : 0);
    var story = section('tr-replay', 'Step by step', 'tr-steps-sec');
    if (!walk.length) { story.appendChild(el('p', 'tr-dim', 'No steps yet.')); }
    else {
      // The strip: one bar per step, its height the problems hit there; where they got stuck is outlined.
      var most = Math.max.apply(null, [1].concat(walk.map(function (s) { return (foundAt[s.n] || []).length; })));
      var strip = el('div', 'tr-strip');
      strip.setAttribute('role', 'group');
      strip.setAttribute('aria-label', 'Steps');
      walk.forEach(function (s) {
        var n = (foundAt[s.n] || []).length;
        var b = button('tr-strip-b' + (n ? ' has' : '') + (s.n === stuckAt ? ' is-stuck' : ''), null);
        b.setAttribute('aria-pressed', s.n === sel ? 'true' : 'false');
        b.setAttribute('aria-label', 'Step ' + s.n + ': ' + plural(n, 'problem') + (s.n === stuckAt ? ', stuck here' : ''));
        var marks = el('span', 'tr-marks');
        (foundAt[s.n] || []).slice(0, 4).forEach(function (f) { marks.appendChild(shape(f.how_bad, 9)); });
        b.appendChild(marks);
        var bar = el('span', 'tr-strip-bar');
        bar.style.height = (n ? Math.round(4 + n / most * 18) : 2) + 'px';
        b.appendChild(bar);
        b.appendChild(el('span', '', String(s.n)));
        b.addEventListener('click', function () { pickStep(t, s.n); });
        strip.appendChild(b);
      });
      story.appendChild(strip);
      var key = el('div', 'tr-strip-key');
      if (stuckAt) { var k1 = el('span', 'tr-stuckword'); k1.appendChild(shape('blocked', 10)); k1.appendChild(el('span', '', 'outlined: where ' + name + ' was stopped')); key.appendChild(k1); }
      key.appendChild(el('span', '', 'bar height: problems at that step'));
      story.appendChild(key);
      // The storyboard: a phone frame per step, what they saw, what they did, and what they thought.
      var board = el('ol', 'tr-board');
      board.setAttribute('aria-label', 'Every step');
      walk.forEach(function (s) {
        var li = el('li', 'tr-frame' + (s.n === stuckAt ? ' is-stuck' : '') + (s.n === sel ? ' is-on' : ''));
        li.id = 'step-' + s.n;
        var ph = el('div', 'tr-phone');
        var pick = button('tr-frame-pick', null);
        pick.setAttribute('aria-pressed', s.n === sel ? 'true' : 'false');
        var sn = el('span', 'tr-frame-sn');
        sn.appendChild(el('span', '', 'Step ' + s.n));
        if (s.n === stuckAt) { var sw = el('span', 'tr-stuckword'); sw.appendChild(shape('blocked', 9)); sw.appendChild(el('span', '', 'Stuck here')); sn.appendChild(sw); }
        pick.appendChild(sn);
        pick.appendChild(el('span', 'tr-frame-t', s.title || ('Step ' + s.n)));
        pick.setAttribute('aria-label', 'Show step ' + s.n + (s.title ? ', ' + s.title : '') + ' below the strip');
        pick.addEventListener('click', function () { pickStep(t, s.n); });
        ph.appendChild(pick);
        if (s.shot) { ph.appendChild(shot(API + '/' + t.number + '/shot/' + s.n, 'What ' + name + ' saw at step ' + s.n, 'tr-frame-shot')); }
        var f = foundAt[s.n] || [];
        var marks = el('div', 'tr-marks');
        f.forEach(function (x) { marks.appendChild(shape(x.how_bad, 10)); });
        marks.appendChild(el('span', '', f.length ? plural(f.length, 'problem') : 'No problem'));
        ph.appendChild(marks);
        li.appendChild(ph);
        if (s.does) { var did = el('div', 'tr-did'); did.appendChild(icon('tap')); did.appendChild(el('span', '', s.does)); li.appendChild(did); }
        if (s.think) { li.appendChild(el('div', 'tr-bubble', s.think)); }
        board.appendChild(li);
      });
      story.appendChild(board);
      story.appendChild(stepDetail(t, walk, foundAt, sel, stuckAt));
    }
    root.appendChild(story);

    var end = section('tr-end', 'How it ended', 'tr-end-sec');
    if (t.managed || t.ending) {
      if (t.ending) { end.appendChild(el('p', 'tr-last', '“' + t.ending + '”')); }
      end.appendChild(said('Did ' + name + ' manage it?', MANAGED[t.managed] || '–'));
      if (t.nearly_gave_up) { end.appendChild(said('Where ' + name + ' nearly gave up', t.nearly_gave_up)); }
      if ((t.closed || []).length) {
        end.appendChild(said('Fixed, because ' + name + ' got past them this time',
          t.closed.map(function (c) { return 'Problem ' + c.number + ': ' + c.what; }).join('; ')));
      }
    } else { end.appendChild(el('p', 'tr-dim', 'It has not ended yet.')); }
    root.appendChild(end);

    // What kind of try it was, and for a review the button that starts the fixes, just above the problems
    // it is about: above the steps it pushed the step strip off a phone's first screen.
    var kind = el('section', 'tr-sec');
    kind.appendChild(modeBox(t));
    root.appendChild(kind);
    root.appendChild(tryProblems(t));
    root.appendChild(runAgain(d.personas || [], t.persona, function (persona) {
      return call('/' + t.number + '/again', { persona: persona });
    }, 'Ask for a review', 'A tester who has seen nothing before tries the same job from the start, and you get a report ' +
      'like this one. It takes a few minutes. Nothing is fixed from it until you choose what.'));
  }

  function pickStep(t, n) {
    S.step[t.number] = n;
    draw();
    var to = document.getElementById('tr-stepd');
    if (to) { to.scrollIntoView({ block: 'nearest' }); }
  }

  /* One step whole: what they saw, said and did, the three questions, and the problems hit there. */
  function stepDetail(t, walk, foundAt, n, stuckAt) {
    var s = walk.filter(function (x) { return x.n === n; })[0] || walk[walk.length - 1];
    var name = t.persona_name;
    var box = el('div', 'tr-panel tr-stepd');
    box.id = 'tr-stepd';
    box.setAttribute('aria-live', 'polite');
    var left = el('div');
    left.appendChild(el('h3', 'tr-h3', 'Step ' + s.n + ' of ' + walk.length + (s.n === stuckAt ? ': stuck here' : '') + (s.title ? ' · ' + s.title : '')));
    var kv = el('dl', 'tr-kv');
    [['Saw', s.see], ['Said', s.think ? '“' + s.think + '”' : ''], ['Did', s.does]].forEach(function (x) {
      if (!x[1]) { return; }
      kv.appendChild(el('dt', '', x[0]));
      kv.appendChild(el('dd', x[0] === 'Said' ? 'tr-think' : '', x[1]));
    });
    left.appendChild(kv);
    if (s.answers && (s.answers.what || s.answers.how || s.answers.then)) {
      var three = el('dl', 'tr-three');
      [['What is this?', s.answers.what], ['What do I do here?', s.answers.how], ['What happens when I do it?', s.answers.then]]
        .forEach(function (q, i) {
          var clear = !s.answers.clear || s.answers.clear[i] !== false;
          var dt = el('dt', '', q[0]);
          if (!clear) { dt.appendChild(chip('Not clear to ' + name, 'amber')); }
          three.appendChild(dt);
          three.appendChild(el('dd', '', q[1] || '–'));
        });
      left.appendChild(three);
    }
    box.appendChild(left);
    var right = el('div');
    var f = foundAt[s.n] || [];
    right.appendChild(el('h3', 'tr-h3', f.length ? plural(f.length, 'problem') + ' hit here' : 'No problem hit here'));
    var ul = el('ul', 'tr-mini');
    f.forEach(function (x) {
      var li = el('li');
      var a = link('', HOME + '/problem/' + x.number);
      a.appendChild(shape(x.how_bad, 12));
      var w = el('span');
      w.appendChild(el('span', '', x.what));
      w.appendChild(el('span', 'tr-dim', ' · ' + BAD[x.how_bad] + ' · Problem ' + x.number + (x.notes ? ' · ' + plural(x.notes, 'message') : '')));
      a.appendChild(w);
      li.appendChild(a);
      ul.appendChild(li);
    });
    right.appendChild(ul);
    if (s.shot) { right.appendChild(shot(API + '/' + t.number + '/shot/' + s.n, 'What ' + name + ' saw at step ' + s.n, 'tr-stepd-shot')); }
    box.appendChild(right);
    return box;
  }

  function reviewChip(t) {
    return chip({ yes: 'They managed it', partly: 'They partly managed it', no: 'They did not manage it' }[t.managed] || 'Done', 'blue');
  }

  /* What this try's mode means, and for a review what is waiting on the owner and the one button that starts the fixes. */
  function modeBox(t) {
    var box = el('div', 'tr-mode tr-mode-' + (t.mode === 'review' ? 'review' : 'auto'));
    var top = el('div', 'tr-head-line');
    top.appendChild(modeChip(t.mode));
    box.appendChild(top);
    if (t.mode !== 'review') {
      box.appendChild(el('p', 'tr-dim', 'Run by itself while a feature was built. The builder fixes what tripped the tester, ' +
        'within what you already approved, and it is tried again, at most two rounds of fixes. Then it ships. Nobody is asked.'));
      return box;
    }
    var found = t.found || [];
    var seen = {}, all = [];
    found.forEach(function (f) { if (!seen[f.number]) { seen[f.number] = 1; all.push(f); } });
    var waiting = all.filter(function (f) { return f.awaiting_choice; }).length;
    var picked = all.filter(function (f) { return f.verdict === 'decided' && f.standing !== 'fixed'; }).length;
    box.appendChild(el('p', 'tr-mode-words', 'You asked for this review. Nothing is fixed from it until you choose. Go through each ' +
      'problem below: Use this fix, Say how to fix it, Not a problem or Won’t fix. Then press Fix the ones I chose, here or ' +
      'under the problems, and Rouh fixes only those, your way, in one go.'));
    box.appendChild(el('p', 'tr-dim', all.length ? plural(all.length, 'problem') + ' found · ' + (waiting ? waiting + ' waiting for your choice' :
      'all chosen') + ' · ' + plural(picked, 'chosen to fix', 'chosen to fix') : 'No problems found.'));
    if (all.length) { box.appendChild(fixButton(t, picked)); }
    return box;
  }

  function reviewCounts(t) {
    var seen = {}, picked = 0, waiting = 0;
    (t.found || []).forEach(function (f) {
      if (seen[f.number]) { return; }
      seen[f.number] = 1;
      if (f.awaiting_choice) { waiting += 1; }
      if (f.verdict === 'decided' && f.standing !== 'fixed') { picked += 1; }
    });
    return { picked: picked, waiting: waiting };
  }

  function fixButton(t, picked) {
    var go2 = button('tr-btn tr-primary', picked === 1 ? 'Fix the one I chose' : picked ? 'Fix the ' + picked + ' I chose' : 'Fix the ones I chose');
    go2.disabled = !picked || !!S.busy;
    if (!picked) { go2.title = 'Choose Use this fix or Say how to fix it on a problem first'; }
    go2.addEventListener('click', function () {
      S.busy = 'fix'; draw();
      call('/' + t.number + '/fix', {}).then(function (j) { S.busy = ''; S.said = j.said; load(); }, fail);
    });
    return go2;
  }

  /* Whether they managed it, said so it never reads against Passed or Did not pass (trials 17 and 21). */
  function tryLine(t) {
    if (t.state === 'failed' && t.managed === 'yes') { return 'Managed it, but problems got in the way'; }
    return { yes: 'Managed it', partly: 'Partly managed it', no: 'Did not manage it' }[t.managed] || '';
  }

  /* Why a try passed or not, in a line: "Managed it" and "Did not pass" side by side read as a contradiction
     to Vesela (trial 17) when nothing said that a problem that stopped or confused her fails it. */
  function verdictWhy(t) {
    var bad = (t.found || []).filter(function (f) {
      return (f.how_bad === 'blocked' || f.how_bad === 'confused') && f.standing !== 'set_aside';
    }).length;
    var who = t.persona_name;
    if (t.state === 'passed') { return who + ' managed it, and nothing stopped or confused them.'; }
    if (t.state !== 'failed') { return ''; }
    if (t.managed === 'yes' && bad) { return who + ' managed it, but ' + plural(bad, 'problem') + ' stopped or confused them, so it did not pass.'; }
    if (t.managed === 'partly') { return who + ' only partly managed it.'; }
    if (t.managed === 'no') { return who + ' did not manage it.'; }
    return t.why || '';
  }

  /* The try's problems, worst first: Teodora's cards, each with its picture, what should have happened,
     what did, how to fix it, and Send as feedback; a filter by how bad, and ticking and copying. */
  function tryProblems(t) {
    var box = section('tr-probs', 'Problems, worst first', 'tr-probs-sec');
    var found = t.found || [];
    if (!found.length) { box.appendChild(el('p', 'tr-dim', t.state === 'passed' || t.managed ? 'No problems.' : 'None yet.')); return box; }
    var by = {}, distinct = {};
    found.forEach(function (f) { by[f.how_bad] = (by[f.how_bad] || 0) + 1; distinct[f.number] = 1; });
    var nd = Object.keys(distinct).length;
    // One card for each time a problem was met, so a problem met at two steps has two cards: said, so the counts agree.
    if (nd < found.length) { box.appendChild(el('p', 'tr-dim', plural(nd, 'problem') + ', met ' + found.length + ' times in this try: a card for each time.')); }
    var bar = el('div', 'tr-tabs');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Show by how bad');
    [['', 'All', found.length]].concat(BAD_ORDER.filter(function (b) { return by[b]; }).map(function (b) {
      return [b, BAD[b], by[b]];
    })).forEach(function (o) {
      var b = button('tr-tab', null);
      if (o[0]) { b.appendChild(shape(o[0], 11)); }
      b.appendChild(el('span', '', o[1]));
      b.appendChild(el('b', '', String(o[2])));
      b.setAttribute('aria-pressed', S.tryBad === o[0] ? 'true' : 'false');
      b.addEventListener('click', function () { S.tryBad = o[0]; draw(); });
      bar.appendChild(b);
    });
    box.appendChild(bar);
    var list = el('ul', 'tr-list');
    found.filter(function (f) { return !S.tryBad || f.how_bad === S.tryBad; }).forEach(function (f) {
      list.appendChild(problemCard(f, { shot: f.step ? API + '/' + t.number + '/shot/' + f.step : '', name: t.persona_name,
                                        stepOf: t, tick: true, review: t.mode === 'review' }));
    });
    box.appendChild(list);
    // The button that starts the fixes, also where the choosing ends: at the top only, Vesela scrolled up and
    // down and never found it (trial 26).
    if (t.mode === 'review') {
      var c = reviewCounts(t);
      var end = el('div', 'tr-mode tr-mode-review');
      end.appendChild(el('p', 'tr-mode-words', c.picked ? plural(c.picked, 'problem') + ' chosen to fix' +
        (c.waiting ? ', ' + c.waiting + ' still waiting for your choice.' : '.') : 'Choose on each problem above, then press this.'));
      end.appendChild(fixButton(t, c.picked));
      box.appendChild(end);
    }
    var n = Object.keys(S.ticked).filter(function (k) { return S.ticked[k]; }).length;
    var copy = el('div', 'tr-copy');
    var cb = button('tr-btn tr-btn-s', n ? 'Copy the ' + plural(n, 'ticked problem') : 'Tick Copy on problems to copy them as text');
    cb.disabled = !n;
    cb.addEventListener('click', function () {
      var text = found.filter(function (f) { return S.ticked[f.number]; }).map(reportText).join('\n\n---\n\n');
      copyText(text).then(function () { toast('Copied ' + plural(n, 'problem') + '.'); });
    });
    copy.appendChild(cb);
    box.appendChild(copy);
    return box;
  }

  function reportText(p) {
    var lines = ['Problem ' + p.number + ': ' + p.what, 'How bad: ' + (BAD[p.how_bad] || p.how_bad) +
      (p.screen_name ? ' · Where: ' + p.screen_name : '')];
    if (p.quote) { lines.push('In their words: “' + p.quote + '”'); }
    if (p.expected) { lines.push('What should have happened: ' + p.expected); }
    if (p.actual) { lines.push('What happened: ' + p.actual); }
    if (p.decision) { lines.push('Fix it like this: ' + p.decision); } else if (p.fix) { lines.push('How to fix it: ' + p.fix); }
    lines.push('Page: ' + location.origin + HOME + '/problem/' + p.number);
    return lines.join('\n');
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () { return copyOld(text); });
    }
    return Promise.resolve(copyOld(text));
  }
  function copyOld(text) {
    var a = el('textarea');
    a.value = text;
    a.style.position = 'fixed';
    a.style.opacity = '0';
    document.body.appendChild(a);
    a.select();
    try { document.execCommand('copy'); } catch (e) { /* nothing more to try */ }
    a.remove();
  }

  function problemCard(f, o) {
    var li = el('li', 'tr-card' + (f.standing === 'fixed' || f.standing === 'set_aside' ? ' tr-closed' : ''));
    li.id = 'problem-' + f.number;
    var top = el('div', 'tr-card-top');
    if (o.tick) {
      var tick = el('input', 'tr-tick');
      tick.type = 'checkbox';
      tick.id = 'tick-' + f.number;
      tick.checked = !!S.ticked[f.number];
      tick.addEventListener('change', function () { S.ticked[f.number] = tick.checked; draw(); });
      // A box with words beside it: a bare one said nothing of what ticking it does (Vesela, trial 17).
      var tl = el('label', 'tr-tick-l');
      tl.appendChild(tick);
      tl.appendChild(el('span', '', 'Copy'));
      tl.title = 'Tick problems, then press Copy at the bottom of the list to copy them';
      top.appendChild(tl);
    }
    var title = el('div', 'tr-card-title');
    title.appendChild(link(f.what, HOME + '/problem/' + f.number, 'tr-card-what'));
    var chips = el('div', 'tr-chips');
    chips.appendChild(sev(f.how_bad, true));
    chips.appendChild(standBadge(f));
    title.appendChild(chips);
    top.appendChild(title);
    li.appendChild(top);
    var body = el('div', 'tr-card-body');
    if (o.shot) { body.appendChild(shot(o.shot, 'The screen when ' + o.name + ' ran into problem ' + f.number, 'tr-card-shot')); }
    var words = el('div', 'tr-card-words');
    if (f.quote) { words.appendChild(said(o.name + ' said', '“' + f.quote + '”', 'tr-think')); }
    if (f.expected) { words.appendChild(said('What should have happened', f.expected)); }
    if (f.actual) { words.appendChild(said('What happened', f.actual)); }
    if (f.decision) { words.appendChild(said('You decided: fix it like this', f.decision, 'tr-decided')); }
    else if (f.fix) { words.appendChild(said('How to fix it', f.fix)); }
    body.appendChild(words);
    li.appendChild(body);
    var acts = el('div', 'tr-actions');
    if (o.stepOf && f.step) {
      var st = button('tr-btn tr-btn-s', 'See step ' + f.step);
      st.addEventListener('click', function () { pickStep(o.stepOf, f.step); });
      acts.appendChild(st);
    }
    acts.appendChild(link(f.notes ? 'Discuss (' + plural(f.notes, 'message') + ')' : 'Discuss it with Rouh', HOME + '/problem/' + f.number, 'tr-btn tr-btn-s tr-outline'));
    li.appendChild(acts);
    // In a review the owner chooses on each problem, right here, as on Mira's ten suggestions; deciding how
    // happens in the card too, and Rouh's suggestion can be taken as it is (Vesela, trial 25).
    if (o.review && f.standing !== 'fixed') {
      var pick = el('div', 'tr-actions tr-pick-row');
      pick.appendChild(el('span', 'tr-label', f.verdict ? 'You chose: ' + (VERDICT_LINE[f.verdict] || f.verdict) : 'Your choice'));
      function choose2(v, decision) {
        S.busy = 'verdict';
        call('/problems/' + f.number + '/verdict', { verdict: v, decision: decision || '' }).then(function () {
          S.busy = ''; S.cardDeciding = 0;
          S.said = 'Saved for problem “' + f.what + '”: ' + (VERDICT_LINE[v] || v) + '.' +
            (v === 'decided' ? ' It is fixed when you press Fix the ones I chose, under the problems.' : '');
          load();
        }, fail);
      }
      if (f.fix && f.verdict !== 'decided') {
        var use = button('tr-btn tr-btn-s tr-primary', 'Use this fix');
        use.title = 'Fix it the way suggested above: ' + f.fix;
        use.disabled = !!S.busy;
        use.addEventListener('click', function () { choose2('decided', f.fix); });
        pick.appendChild(use);
      }
      var own = button('tr-btn tr-btn-s', f.verdict === 'decided' ? 'Change how' : 'Say how to fix it');
      own.disabled = !!S.busy;
      own.addEventListener('click', function () { S.cardDeciding = f.number; draw(); });
      pick.appendChild(own);
      [['not_a_problem', 'Not a problem'], ['wont_fix', 'Won’t fix']].forEach(function (v) {
        if (f.verdict === v[0]) { return; }
        var b = button('tr-btn tr-btn-s', v[1]);
        b.disabled = !!S.busy;
        b.addEventListener('click', function () { choose2(v[0]); });
        pick.appendChild(b);
      });
      li.appendChild(pick);
      if (S.cardDeciding === f.number) {
        var form = el('form', 'tr-form');
        var how = field(form, 'How should it be fixed?', 'textarea', f.decision || f.fix || '', 'tr-how-' + f.number);
        var row = el('div', 'tr-actions');
        var save = button('tr-btn tr-btn-s tr-primary', 'Save how');
        save.type = 'submit';
        var cancel = button('tr-btn tr-btn-s', 'Cancel');
        cancel.addEventListener('click', function () { S.cardDeciding = 0; draw(); });
        row.appendChild(save);
        row.appendChild(cancel);
        form.appendChild(row);
        form.addEventListener('submit', function (e) { e.preventDefault(); if (how.value.trim()) { choose2('decided', how.value); } });
        li.appendChild(form);
        setTimeout(function () { how.focus(); }, 0);
      }
      li.appendChild(el('p', 'tr-dim', 'Use this fix: fix it as suggested above. Say how to fix it: write your own way. Not a problem: ' +
        'it is fine as it is. Won’t fix: it is real, but not worth changing. Nothing is fixed until you press Fix the ones I chose, under the problems.'));
    }
    return li;
  }

  /* ---- the Fix list: the problems, every job ---- */

  var STATUS_TABS = [['open', 'Needs your decision', 'open'], ['awaiting', 'Waiting for your choice', ''],
                     ['decided', 'Decided, waiting for a re-test', 'decided'], ['again', 'Seen again', ''], ['fixed', 'Fixed', 'fixed'],
                     ['set_aside', 'Set aside', 'set_aside'], ['all', 'All', '*']];

  function drawProblems(root) {
    var d = S.data.problems;
    moved('');
    if (d && d.counts && !d.counts.open && !d.counts.closed && !(d.counts.by && (d.counts.by.set_aside || d.counts.by.decided))) {
      root.appendChild(el('h1', 'tr-headline', 'Nothing to fix.'));
      root.appendChild(el('p', 'tr-empty', d.counts.trials ? 'No problems found yet: every try so far went without one.'
        : 'Nothing has been tried yet, so no problems have been found.'));
      return;
    }
    var f = S.probFilter, v = S.probView;
    if (!d) {
      root.appendChild(el('h1', 'tr-headline', 'The Fix list'));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the problems…')); }
      return;
    }
    if (f.status === 'again') { d = Object.assign({}, d, { problems: d.problems.filter(seenAgain) }); }
    else if (f.status === 'decided') { d = Object.assign({}, d, { problems: d.problems.filter(function (p) { return !seenAgain(p); }) }); }
    var list = d.problems.filter(function (p) {
      return (v.screen == null || (p.screen || '') === v.screen) && (!v.bad || p.how_bad === v.bad);
    });
    var by = (d.counts && d.counts.by) || {};
    var worst = d.problems[0];
    var tab = STATUS_TABS.filter(function (x) { return x[0] === f.status; })[0] || STATUS_TABS[0];
    root.appendChild(el('h1', 'tr-headline tr-hl-fix', !d.problems.length ? (f.status === 'open' ? 'Nothing is waiting for your decision.' : 'No problems here.')
      : f.status === 'open' ? plural(d.problems.length, 'problem needs', 'problems need') + ' your decision. The worst is “' + worst.what + '”, seen ' +
        (worst.count === 1 ? 'once' : worst.count + ' times') + (worst.screen_name ? ' on ' + worst.screen_name : '') + '.'
      : plural(d.problems.length, 'problem') + ': ' + tab[1].toLowerCase() + '.'));
    var who = foundLine(d.testers);
    root.appendChild(el('p', 'tr-lede', 'Worst first means how bad it was first (stopped, then confused, then annoyed, then small), ' +
      'then how often it was seen.' + (who ? ' ' + who : '')));

    var grid = el('div', 'tr-fixgrid');
    // Where they are: each page against how bad, a count in each cell, and pressing one shows only those.
    var mx = el('section', 'tr-mxsec');
    mx.appendChild(el('h2', 'tr-h2', 'Where they are'));
    var pages = {}, porder = [];
    d.problems.forEach(function (p) {
      var k = p.screen || '';
      if (!pages[k]) { pages[k] = { name: p.screen_name || 'Somewhere in Rouh', n: {}, all: 0 }; porder.push(k); }
      pages[k].n[p.how_bad] = (pages[k].n[p.how_bad] || 0) + 1;
      pages[k].all += 1;
    });
    porder.sort(function (a, b) { return pages[b].all - pages[a].all; });
    var m = el('div', 'tr-matrix');
    m.setAttribute('role', 'table');
    m.setAttribute('aria-label', 'Problems by page and how bad');
    var hrow = el('div', 'tr-mx-row tr-mx-h');
    hrow.setAttribute('role', 'row');
    hrow.appendChild(el('span', '', 'Page'));
    BAD_ORDER.forEach(function (b) { var c = el('span'); c.appendChild(shape(b, 10)); c.appendChild(el('span', '', BAD_SHORT[b])); hrow.appendChild(c); });
    hrow.appendChild(el('span', '', 'All'));
    m.appendChild(hrow);
    var most = 1;
    porder.forEach(function (k) { BAD_ORDER.forEach(function (b) { most = Math.max(most, pages[k].n[b] || 0); }); });
    porder.forEach(function (k) {
      var r = el('div', 'tr-mx-row');
      r.setAttribute('role', 'row');
      var pg = button('tr-mx-pg', pages[k].name);
      pg.setAttribute('aria-pressed', v.screen === k && !v.bad ? 'true' : 'false');
      pg.addEventListener('click', function () { setView(v.screen === k && !v.bad ? null : k, ''); });
      r.appendChild(pg);
      BAD_ORDER.forEach(function (b) {
        var n = pages[k].n[b] || 0;
        if (!n) { r.appendChild(el('span', 'tr-mx-zero', '0')); return; }
        var c = button('tr-mx-cell', null);
        var sq = el('span', 'tr-mx-sq');
        var s = Math.round(6 + n / most * 12);
        sq.style.width = s + 'px'; sq.style.height = s + 'px'; sq.style.background = 'var(--s-' + b + ')';
        c.appendChild(sq);
        c.appendChild(el('span', '', String(n)));
        c.setAttribute('aria-label', pages[k].name + ', ' + BAD_SHORT[b].toLowerCase() + ': ' + n + '. Show only these.');
        c.setAttribute('aria-pressed', v.screen === k && v.bad === b ? 'true' : 'false');
        c.addEventListener('click', function () { setView(v.screen === k && v.bad === b ? null : k, v.screen === k && v.bad === b ? '' : b); });
        r.appendChild(c);
      });
      r.appendChild(el('b', 'tr-mx-all', String(pages[k].all)));
      m.appendChild(r);
    });
    if (porder.length) { mx.appendChild(m); } else { mx.appendChild(el('p', 'tr-dim', 'No problems in this view.')); }
    grid.appendChild(mx);

    var right = el('section', 'tr-worst');
    var rh = el('div', 'tr-sec-head');
    rh.appendChild(el('h2', 'tr-h2', 'Worst first'));
    var grp = button('tr-btn tr-btn-s', v.group ? 'One list' : 'Group by page');
    grp.setAttribute('aria-pressed', v.group ? 'true' : 'false');
    grp.addEventListener('click', function () { S.probView.group = !S.probView.group; draw(); });
    rh.appendChild(grp);
    right.appendChild(rh);
    var tabs = el('div', 'tr-tabs');
    tabs.setAttribute('role', 'group');
    tabs.setAttribute('aria-label', 'Where they stand');
    STATUS_TABS.forEach(function (x) {
      var b = button('tr-tab', null);
      b.appendChild(el('span', '', x[1]));
      var n = x[2] === '*' ? (by.open || 0) + (by.decided || 0) + (by.fixed || 0) + (by.set_aside || 0)
        : x[0] === 'decided' && S.all ? (by.decided || 0) - againN() : x[0] === 'again' && S.all ? againN() : x[2] ? by[x[2]] : null;
      if (n != null) { b.appendChild(el('b', '', String(n))); }
      b.setAttribute('aria-pressed', f.status === x[0] ? 'true' : 'false');
      b.addEventListener('click', function () { S.probFilter.status = x[0]; S.probView = { screen: null, bad: '', group: v.group, all: false }; reloadProblems(); });
      tabs.appendChild(b);
    });
    right.appendChild(tabs);
    right.appendChild(el('p', 'tr-rule', RULE));
    var bar = el('div', 'tr-filters');
    var people = [['', 'Everyone']];
    (d.testers || []).forEach(function (p) { people.push([p.key, p.first + (p.archived ? ' (removed)' : '')]); });
    people.push(['owner', 'You']);
    bar.appendChild(choose('Found by', f.who, people, function (x) { S.probFilter.who = x; reloadProblems(); }));
    var jobs = [['', 'Every job']];
    (d.jobs || []).forEach(function (j) { jobs.push([String(j.number), j.name]); });
    bar.appendChild(choose('Job', f.job, jobs, function (x) { S.probFilter.job = x; reloadProblems(); }));
    right.appendChild(bar);
    if (v.screen != null || v.bad) {
      var on = el('div', 'tr-showing');
      on.appendChild(el('span', '', 'Showing only: ' + [v.screen != null ? (pages[v.screen] ? pages[v.screen].name : 'that page') : '', v.bad ? BAD_SHORT[v.bad].toLowerCase() : '']
        .filter(Boolean).join(', ') + ' (' + list.length + ')'));
      var clr = button('tr-btn tr-btn-s', 'Show every page');
      clr.addEventListener('click', function () { setView(null, ''); });
      on.appendChild(clr);
      right.appendChild(on);
    }
    if (!list.length) {
      right.appendChild(el('p', 'tr-empty', f.status === 'open' ? 'Nothing is waiting to be fixed.' : 'No problems here.'));
    } else if (v.group) {
      var groups = {}, gorder = [];
      list.forEach(function (p) { var k = p.screen_name || 'Somewhere in Rouh'; if (!groups[k]) { groups[k] = []; gorder.push(k); } groups[k].push(p); });
      gorder.forEach(function (k) {
        right.appendChild(el('h3', 'tr-h3 tr-group-h', k + ' (' + groups[k].length + ')'));
        right.appendChild(problemRows(groups[k], d, false));
      });
    } else {
      right.appendChild(problemRows(list, d, true));
    }
    grid.appendChild(right);
    root.appendChild(grid);
  }

  function setView(screen, bad) { S.probView.screen = screen; S.probView.bad = bad; S.probView.all = false; draw(); }
  function reloadProblems() { var seq = ++S.seq; draw(); Promise.all([loadProblems(seq), loadAll()]).then(function () { if (seq === S.seq) { draw(); } }, fail); }

  function problemRows(list, d, cut) {
    var show = cut && !S.probView.all ? list.slice(0, 40) : list;
    var ul = el('ul', 'tr-plist');
    show.forEach(function (p) {
      var li = el('li', 'tr-prow' + (p.standing === 'fixed' || p.standing === 'set_aside' ? ' tr-closed' : ''));
      li.appendChild(sev(p.how_bad));
      var mid = el('div', 'tr-prow-mid');
      mid.appendChild(link(p.what, HOME + '/problem/' + p.number, 'tr-prow-title'));
      var meta = el('div', 'tr-prow-meta');
      meta.appendChild(el('span', '', p.screen_name || 'Somewhere in Rouh'));
      meta.appendChild(el('span', '', p.count === 1 ? 'Seen once' : 'Seen ' + p.count + ' times'));
      if (p.source === 'owner') { meta.appendChild(el('span', '', 'Found by you')); }
      else {
        var w = el('span', 'tr-prow-who');
        (p.personas || []).forEach(function (k) {
          var t = (d.testers || []).filter(function (x) { return x.key === k; })[0];
          w.appendChild(face(t || { key: k, name: upper(k) }, 'xs'));
        });
        w.appendChild(el('span', '', names(p.personas, d.testers)));
        meta.appendChild(w);
      }
      if ((p.jobs || []).length) { meta.appendChild(el('span', '', p.jobs.map(function (j) { return j.name; }).join(', '))); }
      if (p.notes) { meta.appendChild(el('span', '', plural(p.notes, 'message'))); }
      mid.appendChild(meta);
      li.appendChild(mid);
      li.appendChild(standBadge(p));
      if (p.standing === 'open') {
        var act = el('div', 'tr-prow-act');
        var fb = button('tr-btn tr-btn-s', 'Send as feedback');
        fb.disabled = !!S.busy;
        fb.addEventListener('click', function () { toFeedback(p, false); });
        act.appendChild(fb);
        li.appendChild(act);
      }
      ul.appendChild(li);
    });
    if (show.length < list.length) {
      var more = el('li', 'tr-more');
      more.appendChild(el('span', '', 'and ' + (list.length - show.length) + ' more'));
      var b = button('tr-btn tr-btn-s', 'Show all ' + list.length);
      b.addEventListener('click', function () { S.probView.all = true; draw(); });
      more.appendChild(b);
      ul.appendChild(more);
    }
    return ul;
  }

  function names(keys, testers) {
    return (keys || []).map(function (k) {
      var t = (testers || []).filter(function (x) { return x.key === k; })[0];
      return t ? t.first : upper(k);
    }).join(' and ') || 'a tester';
  }

  /* ---- one problem, and its discussion ---- */

  function drawProblem(root, w) {
    var d = S.data.problem;
    if (!d || String(d.problem.number) !== w.n) {
      root.appendChild(crumbs([['Fix list', HOME + '/problems'], ['Problem ' + w.n]]));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the problem…')); }
      return;
    }
    var p = d.problem;
    moved(p.what);
    root.appendChild(crumbs([['Fix list', HOME + '/problems'], [(p.screen_name || 'Somewhere in Rouh') + ': problem ' + p.number]]));
    root.appendChild(el('h1', 'tr-h1 tr-ph', p.what));
    var meta = el('div', 'tr-pmeta');
    meta.appendChild(sev(p.how_bad, true));
    meta.appendChild(el('span', '', (p.count === 1 ? 'Seen once' : 'Seen ' + p.count + ' times') +
      (p.source === 'owner' ? ', found by you' : (p.personas || []).length ? ' by ' + names(p.personas, (S.shell && S.shell.testers) || []) : '')));
    meta.appendChild(standBadge(p));
    meta.appendChild(el('span', 'tr-dim', 'Problem ' + p.number));
    root.appendChild(meta);
    // On a phone the decisions sit here, under the title: a bar at the bottom would cover Rouh's own menu button.
    root.appendChild(decide(p, 'inline'));
    if (p.status === 'closed') {
      root.appendChild(el('p', 'tr-good', 'Fixed on ' + date(p.closed_at) + (p.closed_by ? ': try ' + p.closed_by +
        ' went past this screen without tripping on it.' : '.')));
    }

    var focus = el('div', 'tr-focus');
    var story = el('div', 'tr-story');
    var sights = p.sightings || [];
    var latest = sights[0];
    if (latest && latest.quote) {
      story.appendChild(el('p', 'tr-quote', latest.quote));
      var by = el('p', 'tr-dim');
      by.appendChild(document.createTextNode((latest.source === 'owner' ? 'You' : latest.persona_name) + ', ' + day(latest.at)));
      if (latest.trial) { by.appendChild(document.createTextNode(' · ')); by.appendChild(link('try ' + latest.trial + ', step ' + latest.step, HOME + '/' + latest.trial)); }
      story.appendChild(by);
    }
    var withShot = sights.filter(function (s) { return s.trial && s.shot; })[0];
    if (withShot) {
      var whereB = el('section', 'tr-panel tr-where');
      var wh = el('div', 'tr-sec-head');
      wh.appendChild(el('h2', 'tr-h3', 'Where it happened: try ' + withShot.trial + ', step ' + withShot.step));
      var open = link('Open the try', HOME + '/' + withShot.trial, 'tr-a');
      open.addEventListener('click', function () { S.step[withShot.trial] = withShot.step; }, true);
      wh.appendChild(open);
      whereB.appendChild(wh);
      if (withShot.job_name) { whereB.appendChild(el('p', 'tr-dim', withShot.job_name + ' · ' + withShot.persona_name)); }
      whereB.appendChild(shot(API + '/' + withShot.trial + '/shot/' + withShot.step, 'The screen when ' + withShot.persona_name + ' ran into it', 'tr-where-shot'));
      story.appendChild(whereB);
    }
    var eh = el('div', 'tr-eh');
    if (p.expected) { var a1 = el('div'); a1.appendChild(el('h3', 'tr-h3', 'What should have happened')); a1.appendChild(el('p', '', p.expected)); eh.appendChild(a1); }
    if (p.actual) { var a2 = el('div'); a2.appendChild(el('h3', 'tr-h3', 'What happened')); a2.appendChild(el('p', '', p.actual)); eh.appendChild(a2); }
    if (eh.childNodes.length) { story.appendChild(eh); }
    if (p.decision || p.fix) {
      var fx = el('section', 'tr-panel');
      if (p.decision) { fx.appendChild(el('h2', 'tr-h3', 'You decided: fix it like this')); fx.appendChild(el('p', 'tr-decided', p.decision)); }
      if (p.fix) { fx.appendChild(el('h2', 'tr-h3', p.decision ? 'Rouh’s first suggestion' : 'Suggested fix')); fx.appendChild(el('p', '', p.fix)); }
      story.appendChild(fx);
    }
    if (!p.expected && !p.actual && !p.fix && !p.decision) {
      story.appendChild(el('p', 'tr-dim', 'This problem was found before testers said what they expected, so only their words are kept.'));
    }
    var pc = el('section', 'tr-panel');
    pc.appendChild(el('h2', 'tr-h3', 'How far it is from fixed'));
    pc.appendChild(chain(p));
    pc.appendChild(el('p', 'tr-rule', RULE));
    story.appendChild(pc);
    // Each choice with one line on what it does: in a row, five buttons sounded the same to Vesela (trial 21).
    var what = section('', 'What each choice does');
    var dl = el('dl', 'tr-choices');
    [['Fix it like this…', 'You say how it should be fixed. The next round of fixes does it your way.'],
     ['Send as feedback', 'Sends it now, with its picture, to Rouh’s list of changes to make to itself.'],
     ['Edit before sending', 'The same, but you can change the words first, then send.'],
     ['Not a problem', 'The tester was wrong: it is fine as it is.'],
     ['Won’t fix', 'It is real, but not worth changing.'],
     ['Take it back', 'Undo your choice: it is open again. Every choice also has Undo on the message that appears.']]
      .forEach(function (x) { dl.appendChild(el('dt', '', x[0])); dl.appendChild(el('dd', '', x[1])); });
    what.appendChild(dl);
    what.appendChild(el('p', 'tr-dim', 'After Not a problem or Won’t fix, a tester who runs into it again no longer counts against the change.'));
    story.appendChild(what);

    var seen = section('', 'Every time it was seen');
    var ul = el('ul', 'tr-sights');
    sights.forEach(function (s) {
      var li = el('li', 'tr-sight');
      if (s.shot && s.trial) { li.appendChild(shot(API + '/' + s.trial + '/shot/' + s.step, 'The screen at that moment', 'tr-thumb')); }
      var ww = el('div', 'tr-sight-words');
      ww.appendChild(el('p', 'tr-think', '“' + s.quote + '”'));
      var from = el('p', 'tr-dim');
      from.appendChild(document.createTextNode((s.source === 'owner' ? 'You said this' : s.persona_name) + ', ' + day(s.at)));
      if (s.trial) {
        from.appendChild(document.createTextNode(' · '));
        from.appendChild(link((s.job_name ? s.job_name + ', ' : '') + 'try ' + s.trial + ', step ' + s.step, HOME + '/' + s.trial));
      }
      ww.appendChild(from);
      li.appendChild(ww);
      ul.appendChild(li);
    });
    seen.appendChild(ul);
    story.appendChild(seen);
    focus.appendChild(story);
    focus.appendChild(thread(p));
    root.appendChild(focus);
    root.appendChild(decide(p, 'bar'));
  }

  /* What to do with it, in a bar that stays at the bottom: decide how it is fixed, send it as feedback,
     or set it aside (Teodora's two buttons and the owner's three). Every choice can be undone. */
  function decide(p, kind) {
    var box = el('section', 'tr-decbar is-' + kind);
    box.setAttribute('aria-label', 'What should happen with it?');
    if (S.deciding) {
      var f = el('form', 'tr-form tr-decform');
      var how = field(f, 'Fix it like this', 'textarea', p.decision || p.fix || '', 'tr-decision-' + kind);
      how.rows = 3;
      f.appendChild(el('p', 'tr-dim', p.awaiting_choice || isReview(p) ? 'It is fixed your way when you press Fix the ones I chose on the review’s page.'
        : 'The next round of fixes reads this and does it your way.'));
      var row = el('div', 'tr-actions');
      var save = button('tr-btn tr-primary', 'Save the decision');
      save.type = 'submit';
      var cancel = button('tr-btn', 'Cancel');
      cancel.addEventListener('click', function () { S.deciding = false; draw(); });
      row.appendChild(save);
      row.appendChild(cancel);
      f.appendChild(row);
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        verdict(p, 'decided', how.value);
      });
      box.appendChild(f);
      return box;
    }
    var wrap = el('div', 'tr-decbar-in');
    wrap.appendChild(el('span', 'tr-decbar-q', 'What should happen with it?'));
    function act(text, cls, fn, what) {
      var b = button('tr-btn' + (cls ? ' ' + cls : ''), text);
      b.disabled = !!S.busy;
      b.title = what;
      b.addEventListener('click', fn);
      wrap.appendChild(b);
    }
    act('Fix it like this…', 'tr-primary', function () { S.deciding = true; draw(); },
      'You say how it should be fixed. The next round of fixes does it your way.');
    act('Send as feedback', '', function () { toFeedback(p, false); },
      'Sends it now, with its picture, to Rouh’s list of changes to make to itself.');
    act('Edit before sending', '', function () { toFeedback(p, true); },
      'The same, but you can change the words first, then send.');
    if (p.verdict !== 'not_a_problem') {
      act('Not a problem', '', function () { verdict(p, 'not_a_problem'); }, 'The tester was wrong: it is fine as it is.');
    }
    if (p.verdict !== 'wont_fix') {
      act('Won’t fix', '', function () { verdict(p, 'wont_fix'); }, 'It is real, but not worth changing.');
    }
    if (p.verdict) { act('Take it back', '', function () { verdict(p, ''); }, 'Undo your choice: it is open again.'); }
    box.appendChild(wrap);
    // Each choice in a line: in a row, five buttons sounded the same to Vesela (trial 21).
    var now = el('p', 'tr-decbar-now');
    if (p.verdict) {
      now.appendChild(el('strong', '', 'You chose: ' + (VERDICT_LINE[p.verdict] || p.verdict_name)));
      now.appendChild(document.createTextNode((p.verdict_at ? ', ' + day(p.verdict_at) : '') + '. Every choice can be taken back.'));
    } else {
      now.appendChild(document.createTextNode('Every choice can be undone. What each one does is under the problem.'));
    }
    box.appendChild(now);
    return box;
  }

  function isReview(p) { return (p.sightings || []).some(function (x) { return x.mode === 'review'; }); }

  function verdict(p, v, decision, quiet) {
    var before = { verdict: p.verdict || '', decision: p.decision || '' };
    S.busy = 'verdict';
    call('/problems/' + p.number + '/verdict', { verdict: v, decision: decision || '' }).then(function (got) {
      S.busy = ''; S.deciding = false;
      if (S.data.problem && S.data.problem.problem.number === p.number) { S.data.problem.problem = got.problem; }
      S.said = '';
      if (S.shell) { loadShell().catch(function () {}); }
      draw();
      if (quiet) { toast('Put back as it was.'); return; }
      var msg = v === '' ? 'Taken back: it is open again.' : 'Saved: ' + (VERDICT_LINE[v] || v) + '.' +
        (v === 'decided' && isReview(got.problem) ? ' It is fixed when you press Fix the ones I chose on the review’s page.' : '');
      toast(msg, before.verdict === 'sent' ? null : function () { verdict(got.problem, before.verdict, before.decision, true); });
    }, fail);
  }

  function toFeedback(p, edit) {
    var gt = window.RouhGeneTherapy;
    if (!gt) { S.error = 'Feedback cannot be sent from this page.'; draw(); return; }
    S.busy = 'feedback'; draw();
    call('/problems/' + p.number + '/report').then(function (r) {
      return gt.fill(r.body, r.shots || [], { edit: edit, onSent: function (fb) {
        call('/problems/' + p.number + '/verdict', { verdict: 'sent', feedback: (fb && fb.id) || '' }).then(function (got) {
          if (S.data.problem && S.data.problem.problem.number === p.number) { S.data.problem.problem = got.problem; }
          if (where().page === 'problems') { reloadProblems(); }
          if (S.shell) { loadShell().catch(function () {}); }
          S.said = '';
          toast('Sent as feedback: “' + p.what + '”.');
          draw();
        }, fail);
      } });
    }).then(function (got) {
      S.busy = '';
      S.said = got && got.ok === false ? got.error : edit ? 'It is in the box on the right. Change the words, then press Mutate to send it.' : 'Sending it…';
      draw();
    }, fail);
  }

  function thread(p) {
    var box = el('section', 'tr-panel tr-talk');
    box.appendChild(el('h2', 'tr-h2', 'Talk it over with Rouh'));
    var list = el('ol', 'tr-msgs');
    (p.thread || []).forEach(function (n) {
      var li = el('li', 'tr-msg tr-msg-' + (n.kind === 'verdict' ? 'verdict' : n.who));
      if (n.kind === 'verdict') {
        li.appendChild(el('span', '', n.text + ' · ' + day(n.at)));
      } else {
        li.appendChild(el('div', 'tr-msg-who', (n.who === 'owner' ? 'You' : 'Rouh') + ' · ' + day(n.at)));
        li.appendChild(prose(n.text));
      }
      list.appendChild(li);
    });
    function send(text) {
      S.busy = 'say'; S.sayDraft = { n: p.number, text: text }; draw();
      call('/problems/' + p.number + '/say', { text: text }).then(function (got) {
        S.busy = ''; S.sayDraft = null;
        S.data.problem.problem = got.problem;
        draw();
      }, fail);
    }
    if (!(p.thread || []).length) {
      box.appendChild(el('p', 'tr-dim', 'Rouh answers here, with the problem, its picture and the whole try in front of it. Start with a question:'));
      var qs = el('div', 'tr-suggest');
      [p.how_bad === 'blocked' ? 'Why did this stop the tester?' : 'Why did this happen?', 'How would you fix it?', 'Is it worth fixing now?']
        .forEach(function (q) {
          var b = button('tr-btn tr-btn-s', q);
          b.disabled = !!S.busy;
          b.addEventListener('click', function () { send(q); });
          qs.appendChild(b);
        });
      box.appendChild(qs);
    }
    box.appendChild(list);
    if (S.busy === 'say') { box.appendChild(el('p', 'tr-thinking', 'Rouh is answering…')); }
    if (p.unanswered) { box.appendChild(el('p', 'tr-err-words', p.unanswered)); }
    var f = el('form', 'tr-form tr-say');
    var lab = el('label', 'tr-label', 'Your message');
    lab.htmlFor = 'tr-say-' + p.number;
    f.appendChild(lab);
    var area = el('textarea', 'tr-input tr-area');
    area.id = 'tr-say-' + p.number;
    area.rows = 3;
    area.placeholder = 'Ask about this problem, or say how you see it';
    if (S.sayDraft && S.sayDraft.n === p.number) { area.value = S.sayDraft.text; }
    // It grows as she types, so the whole message can be read before it is sent (trial 22).
    function grow() { area.style.height = 'auto'; area.style.height = Math.min(area.scrollHeight + 2, 320) + 'px'; }
    area.addEventListener('input', function () { S.sayDraft = { n: p.number, text: area.value }; grow(); });
    setTimeout(grow, 0);
    f.appendChild(area);
    var row = el('div', 'tr-actions tr-end-row');
    var sendB = button('tr-btn tr-outline', S.busy === 'say' ? 'Rouh is answering…' : 'Send to Rouh');
    sendB.type = 'submit';
    sendB.disabled = !!S.busy;
    row.appendChild(sendB);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!area.value.trim()) { area.focus(); return; }
      send(area.value);
    });
    box.appendChild(f);
    return box;
  }

  /* ---- pausing (Petar, 5 November 2026: "a pause button I can toggle on/off") ---- */

  /* Pause or resume one tester (key), or everyone (no key). The page changes at once, before Rouh answers,
     and goes back, with the reason, if Rouh could not do it. Nothing asks first. */
  function setPause(key, on, firstName, quiet) {
    function apply(v) {
      if (!key) {
        if (S.data.testers) { S.data.testers.paused_all = v; }
        if (S.data.tester) { S.data.tester.tester.paused_all = v; }
        if (S.shell) { S.shell.paused_all = v; }
        return;
      }
      [S.data.testers && S.data.testers.testers, S.data.tester && [S.data.tester.tester], S.shell && S.shell.testers,
       S.shell && S.shell.personas].forEach(function (l) {
        (l || []).forEach(function (t) { if ((t.key || t.id) === key) { t.paused = v; } });
      });
    }
    apply(on);
    S.error = '';
    S.said = '';
    if (!quiet) {
      toast(!key ? (on ? 'All testing is paused. No tester starts a new try until you resume.' : 'All testing is on again.')
        : on ? firstName + ' is paused. ' + firstName + ' starts no new try until you resume.'
          : allPaused() ? firstName + ' is resumed, but all testing is still paused, so ' + firstName + ' waits for that too.'
            : firstName + ' is testing again.');
    }
    draw();
    call(key ? '/testers/' + key + '/pause' : '/pause', { on: on }).then(function () {}, function (e) {
      apply(!on);
      fail(e);
    });
  }

  function allPaused() {
    return !!((S.data.testers && S.data.testers.paused_all) || (S.data.tester && S.data.tester.tester.paused_all) ||
              (S.shell && S.shell.paused_all));
  }

  function pauseButton(key, paused, firstName, cls) {
    var b = button('tr-btn tr-pause-b' + (paused ? ' is-paused' : '') + (cls ? ' ' + cls : ''), null);
    withIcon(b, paused ? 'play' : 'pause', (paused ? 'Resume ' : 'Pause ') + (firstName || 'all testing'));
    b.setAttribute('aria-pressed', paused ? 'true' : 'false');
    b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); setPause(key, !paused, firstName); });
    return b;
  }

  /* What pausing means, at the top of the testers. */
  function pauseWords(on, live) {
    var held = live.filter(function (t) { return t.paused; });
    var every = live.length > 0 && held.length === live.length;
    var names = held.map(function (t) { return t.first; }).join(' and ');
    return on
      ? 'No tester starts a new try, by itself or when you ask. A try already going may finish. Rouh still builds ' +
        'and ships changes, nightly runs included, just without a tester trying them. Resume any time.'
      : every ? names + (held.length === 1 ? ' is' : ' are') + ' paused, so no try starts. Resume one on their card, or all of them here.'
      : held.length ? names + (held.length === 1 ? ' is' : ' are') + ' paused. Resume on their card, or pause all ' + live.length + ' here.'
      : 'Testers try changes as usual. Pause one on their card, or all ' + live.length + ' here. You can resume any time.';
  }

  /* ---- the testers: the Cast ---- */

  function drawTesters(root) {
    var d = S.data.testers;
    moved('');
    if (!d) {
      root.appendChild(el('h1', 'tr-headline', 'The testers'));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the testers…')); }
      return;
    }
    var live = d.testers.filter(function (t) { return !t.archived; });
    var gone = d.testers.filter(function (t) { return t.archived; });
    var held = live.filter(function (t) { return t.paused; });
    root.appendChild(el('div', 'tr-eyebrow', 'Cast'));
    var head = d.paused_all ? 'All testing is paused.' : held.length && held.length === live.length ? (live.length === 2 ? 'Both testers are paused.' : 'Every tester is paused.')
      : held.length ? held.map(function (t) { return t.first; }).join(' and ') + (held.length === 1 ? ' is paused.' : ' are paused.')
      : live.length ? (live.length === 1 ? 'One tester, testing.' : 'All ' + live.length + ' testers are testing.') : 'There are no testers.';
    var finds = foundLine(d.testers);
    root.appendChild(el('h1', 'tr-headline', head + (finds ? ' ' + finds : '')));
    root.appendChild(el('p', 'tr-lede', 'The made-up people who try Rouh’s changes on their phones. Each has a whole ' +
      'life written down, and that is what they are told before every try.'));
    var row = el('div', 'tr-flex tr-cast-acts');
    if (live.length) { row.appendChild(pauseAllButton(live, !!d.paused_all, 'tr-btn')); }
    var add = link('', HOME + '/testers/new', 'tr-btn tr-primary');
    withIcon(add, 'plus', 'Add a tester');
    row.appendChild(add);
    root.appendChild(row);
    if (live.length) { root.appendChild(el('p', 'tr-dim tr-pause-words', pauseWords(!!d.paused_all, live))); }
    var ul = el('ul', 'tr-cards');
    live.forEach(function (t) { ul.appendChild(personCard(t, !!d.paused_all)); });
    root.appendChild(ul);
    if (!live.length) { root.appendChild(el('p', 'tr-empty', 'There are no testers. Add one, and they try every change.')); }
    if (gone.length) {
      var det = el('details', 'brown-toggle');
      det.appendChild(el('summary', '', 'Removed testers (' + gone.length + ')'));
      var b = el('div', 'brown-toggle-body');
      b.appendChild(el('p', 'tr-dim', 'They no longer try anything. Their old tries still say who did them.'));
      var ul2 = el('ul', 'tr-cards');
      gone.forEach(function (t) { ul2.appendChild(personCard(t)); });
      b.appendChild(ul2);
      det.appendChild(b);
      root.appendChild(det);
    }
  }

  function personCard(t, all) {
    var held = (!!t.paused || !!all) && !t.archived;
    var li = el('li', 'tr-pcard' + (held ? ' is-paused' : ''));
    var por = el('div', 'tr-portrait');
    var f = face(t, 'portrait');
    por.appendChild(f);
    var words = el('div', 'tr-person-words');
    var h = el('h2', 'tr-h2');
    h.appendChild(link(t.name, HOME + '/tester/' + t.key, 'tr-pcard-name'));
    words.appendChild(h);
    var jc = [t.age, t.job, t.city].filter(Boolean).join(', ');
    if (jc) { words.appendChild(el('div', 'tr-pcard-job', jc)); }
    if (t.short) { words.appendChild(el('div', 'tr-dim', t.short)); }
    por.appendChild(words);
    li.appendChild(por);
    var chips = el('div', 'tr-chips');
    if (t['default']) { chips.appendChild(chip('Tries every change', 'green')); }
    if (held) { chips.appendChild(chip('Paused', 'amber')); }
    if (chips.childNodes.length) { li.appendChild(chips); }
    var st = el('div', 'tr-pstat');
    var jam = t.archived ? 0 : stuckOf(t.key).length;
    [[t.tries, t.tries === 1 ? 'try' : 'tries'], [t.problems, t.problems === 1 ? 'problem found' : 'problems found'],
     jam ? [jam, 'stuck'] : [t.running || 0, 'going now']]
      .forEach(function (x) { var dv = el('div'); dv.appendChild(el('b', '', String(x[0] || 0))); dv.appendChild(el('span', '', x[1])); st.appendChild(dv); });
    li.appendChild(st);
    if (!t.archived) {
      var status = el('div', 'tr-status-line');
      status.appendChild(withIcon(el('span', 'tr-status'), held ? 'pause' : 'play',
        all ? t.first + ' is paused with everyone' : t.paused ? t.first + ' is paused' + (t.paused_at ? ' since ' + day(t.paused_at) : '') : t.first + ' is testing'));
      status.appendChild(el('span', 'tr-dim', t['default'] ? 'Tries every change' : 'Tries only when asked for by name'));
      li.appendChild(status);
      var acts = el('div', 'tr-actions');
      // While all testing is paused, a card's own button only made people unsure (trial 38): the one at the top lets them go.
      if (!all) { acts.appendChild(pauseButton(t.key, !!t.paused, t.first)); }
      acts.appendChild(link('Open ' + t.first, HOME + '/tester/' + t.key, 'tr-btn tr-quiet'));
      li.appendChild(acts);
    }
    return li;
  }

  function drawTester(root, w) {
    var d = S.data.tester;
    if (!d || d.tester.key !== w.key) {
      root.appendChild(crumbs([['Cast', HOME + '/testers'], ['Tester']]));
      if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening the tester…')); }
      return;
    }
    var t = d.tester, firstName = t.first;
    moved(t.name);
    root.appendChild(crumbs([['Cast', HOME + '/testers'], [t.name]]));
    var topG = el('div', 'tr-tester-top');
    var leftC = el('div', 'tr-tester-main');
    var por = el('div', 'tr-portrait');
    por.appendChild(face(t, 'portrait'));
    var hw = el('div', 'tr-person-words');
    hw.appendChild(el('h1', 'tr-h1', t.name + (t.age ? ', ' + t.age : '')));
    var jc = [t.job, t.city].filter(Boolean).join(' · ');
    if (jc) { hw.appendChild(el('p', 'tr-pcard-job', jc)); }
    if (t.short) { hw.appendChild(el('p', 'tr-dim', t.short)); }
    var chips = el('div', 'tr-chips');
    if (t['default']) { chips.appendChild(chip('Tries every change', 'green')); }
    if (t.archived) { chips.appendChild(chip('Removed', 'slate')); }
    if (!t.archived && (t.paused || t.paused_all)) { chips.appendChild(chip('Paused', 'amber')); }
    chips.appendChild(chip(t.device === 'desk' ? 'Mostly on a computer' : 'Mostly on a phone', 'slate'));
    chips.appendChild(chip(plural(t.tries_count, 'try', 'tries') + ' · ' + plural(t.problems, 'problem') + ' found', 'slate'));
    hw.appendChild(chips);
    por.appendChild(hw);
    leftC.appendChild(por);
    if (!t.archived) {
      var pbox = el('div', 'tr-pausebox' + (t.paused || t.paused_all ? ' is-paused' : ''));
      var pw = el('div', 'tr-pause-text');
      pw.appendChild(el('b', '', t.paused ? firstName + ' is paused' : t.paused_all
        ? firstName + ' is paused with everyone' : firstName + ' is testing'));
      pw.appendChild(el('span', 'tr-dim', t.paused || t.paused_all
        ? firstName + ' starts no new try, by itself or when you ask.' + (t['default'] ? ' Changes are still built and ' +
          'shipped, without a tester trying them, and ' + firstName + ' tries every change again once resumed.' : '') + (t.paused && t.paused_all ? ' Resuming ' + firstName +
          ' alone is not enough while all testing is paused.' : !t.paused && t.paused_all
          ? ' Resume all testing on the testers page to let ' + firstName + ' go again.' : '')
        : (t['default'] ? firstName + ' tries every change Rouh makes that you will see.' : firstName + ' tries only when you ask for ' +
          firstName + ' by name.')));
      var jam = stuckOf(t.key);
      pw.appendChild(el('span', 'tr-dim', jam.length ? (jam.length === 1 ? 'Try ' + jam[0].number + ' by ' + firstName + ' has been stuck since ' +
          day(jam[0].started_at || jam[0].created_at) + ': a try takes minutes.' : jam.length + ' tries by ' + firstName + ' are stuck.')
        : t.running
        ? (t.running === 1 ? 'A try by ' + firstName + ' is going now' : t.running + ' tries by ' + firstName + ' are going now') +
          (t.paused || t.paused_all ? '; it may finish.' : '.')
        : 'No try by ' + firstName + ' is going now.'));
      if (t.skipped) {
        pw.appendChild(el('span', 'tr-dim', plural(t.skipped, 'try', 'tries') + ' skipped while paused' +
          (t.skipped_at ? ', the last on ' + day(t.skipped_at) : '') + '.'));
      }
      pbox.appendChild(pw);
      pbox.appendChild(pauseButton(t.key, !!t.paused, firstName));
      leftC.appendChild(pbox);
      var acts = el('div', 'tr-actions');
      acts.appendChild(link('Change ' + firstName + '’s profile', HOME + '/tester/' + t.key + '/edit', 'tr-btn tr-btn-s'));
      if (!t['default']) {
        var def = button('tr-btn tr-btn-s', 'Make ' + firstName + ' try every change');
        def.addEventListener('click', function () {
          call('/testers/' + t.key + '/default', {}).then(function () { S.said = firstName + ' now tries every change.'; S.shell = null; load(); }, fail);
        });
        acts.appendChild(def);
        var rm = button('tr-btn tr-btn-s tr-danger', 'Remove ' + firstName);
        rm.addEventListener('click', function () { S.confirm = t.key; draw(); });
        acts.appendChild(rm);
      }
      leftC.appendChild(acts);
      if (S.confirm === t.key) {
        var c = el('div', 'tr-confirm');
        c.setAttribute('role', 'alertdialog');
        c.setAttribute('aria-label', 'Remove ' + firstName + '?');
        c.appendChild(el('p', '', 'Remove ' + firstName + '? ' + firstName + ' will not try anything again. The ' +
          plural(t.tries_count, 'try', 'tries') + ' ' + firstName + ' already did stay, and still say who did them.'));
        var row = el('div', 'tr-actions');
        var yes = button('tr-btn tr-btn-s tr-danger', 'Yes, remove ' + firstName);
        yes.addEventListener('click', function () {
          call('/testers/' + t.key + '/remove', {}).then(function () {
            S.confirm = ''; S.carry = firstName + ' is removed.'; S.shell = null; go(HOME + '/testers');
          }, fail);
        });
        var no = button('tr-btn tr-btn-s', 'Keep ' + firstName);
        no.addEventListener('click', function () { S.confirm = ''; draw(); });
        row.appendChild(yes);
        row.appendChild(no);
        c.appendChild(row);
        leftC.appendChild(c);
        setTimeout(function () { no.focus(); }, 0);
      }
    }
    if (t.made_by === 'rouh') { leftC.appendChild(el('p', 'tr-dim', 'Rouh wrote this profile from a sentence, and you kept it.')); }

    // Everything written about them, a folded chapter for each part: it is what they are told, read rarely.
    var prof = section('tr-profile', 'Everything written about ' + firstName);
    prof.appendChild(el('p', 'tr-dim', 'This is exactly what ' + firstName + ' is told before every try, written to ' +
      ({ her: 'her', him: 'him' }[t.them] || 'them') + '. Open a part to read it.'));
    var openAll = button('tr-btn tr-btn-s', 'Open every part');
    prof.appendChild(openAll);
    var parts = [];
    (t.sections || []).forEach(function (s, i) {
      var part = el('details', 'tr-ch');
      part.id = 'tr-part-' + i;
      if (i === 0) { part.open = true; }
      part.appendChild(el('summary', '', s.title));
      part.appendChild(prose(s.text));
      prof.appendChild(part);
      parts.push(part);
    });
    openAll.addEventListener('click', function () {
      var shut = parts.every(function (x) { return x.open; });
      parts.forEach(function (x) { x.open = !shut; });
      openAll.textContent = shut ? 'Open every part' : 'Close every part';
    });
    leftC.appendChild(prof);
    topG.appendChild(leftC);

    var hist = el('section', 'tr-panel tr-hist-sec');
    hist.appendChild(el('h2', 'tr-h2', firstName + '’s tries'));
    if (!t.tries.length) { hist.appendChild(el('p', 'tr-dim', firstName + ' has not tried anything yet.')); }
    var ul = el('ul', 'tr-hist');
    t.tries.forEach(function (x) {
      var li = el('li');
      var a = link('', HOME + '/' + x.number);
      a.appendChild(el('span', 'tr-dim', 'Try ' + x.number));
      var mid = el('span', 'tr-hist-mid');
      mid.appendChild(el('span', 'tr-strong', x.job_name || upper(x.subject) || 'A page of Rouh'));
      mid.appendChild(el('span', 'tr-dim', day(x.created_at) + ' · ' + tryName(x.round, x.mode) + ' · ' +
        (foundN(x) ? plural(foundN(x), 'problem') : 'No problems')));
      a.appendChild(mid);
      a.appendChild(result(x.state));
      li.appendChild(a);
      ul.appendChild(li);
    });
    hist.appendChild(ul);
    topG.appendChild(hist);
    root.appendChild(topG);
  }

  /* ---- adding or changing a tester ---- */

  function blankForm(sections) {
    return { key: '', name: '', age: '', job: '', city: '', short: '', them: 'her', device: 'phone', sentence: '',
             profile: '# You are ...\n\nYou are ... You are ... years old, and you live in ...\n\n' +
               sections.map(function (s) { return '## ' + s + '\n\n'; }).join(''), written: false };
  }
  function formFrom(t) {
    return { key: t.key, name: t.name, age: t.age || '', job: t.job, city: t.city, short: t.short, them: t.them,
             device: t.device, profile: t.profile, sentence: '', written: false };
  }

  function drawForm(root, w) {
    var editing = !!w.key;
    var F = S.form;
    root.appendChild(crumbs(editing ? [['Cast', HOME + '/testers'], [(F && F.name) || 'The tester', HOME + '/tester/' + w.key], ['Change']]
      : [['Cast', HOME + '/testers'], ['Add a tester']]));
    if (!F || (editing && F.key !== w.key)) { if (!S.error) { root.appendChild(el('p', 'tr-loading', 'Opening…')); } return; }
    moved(editing ? F.name : 'New tester');
    root.appendChild(el('h1', 'tr-headline', editing ? 'Change ' + (F.name.split(' ')[0] || 'the tester') + '’s profile' : 'Add a tester'));
    if (!editing) {
      var quick = section('tr-panel tr-quick', 'Describe them in a sentence, and Rouh writes the rest');
      var q = el('textarea', 'tr-input tr-area');
      q.id = 'tr-sentence';
      q.rows = 2;
      q.value = F.sentence;
      q.placeholder = 'For example: a retired teacher in Varna, 67, who is wary of apps and reads everything twice.';
      q.setAttribute('aria-label', 'Describe the new tester in a sentence');
      q.addEventListener('input', function () { F.sentence = q.value; });
      quick.appendChild(q);
      var wr = button('tr-btn tr-primary', S.busy === 'draft' ? 'Rouh is writing… about a minute' : 'Let Rouh write the whole profile');
      wr.disabled = !!S.busy;
      wr.addEventListener('click', function () {
        if (!F.sentence.trim()) { q.focus(); return; }
        S.busy = 'draft'; S.error = ''; S.draftError = ''; draw();
        call('/testers/draft', { sentence: F.sentence }).then(function (j) {
          S.busy = '';
          var g = j.draft || {};
          ['name', 'age', 'job', 'city', 'short', 'them', 'device', 'profile'].forEach(function (k) {
            if (g[k] != null && g[k] !== '') { F[k] = g[k]; }
          });
          F.written = true;
          S.said = 'Rouh wrote the profile below. Read it and change anything, then press Save.';
          draw();
        }, function (e) {
          // Said beside the button that was pressed, not at the top of the page out of sight.
          S.busy = '';
          S.draftError = String((e && e.message) || e);
          draw();
        });
      });
      quick.appendChild(wr);
      if (S.draftError) { quick.appendChild(el('p', 'tr-err-words', S.draftError)); }
      quick.appendChild(el('p', 'tr-dim', 'Rouh only fills in the boxes below. Nothing is kept until you press Save at the bottom. ' +
        'Or fill in everything yourself.'));
      root.appendChild(quick);
    }
    var f = el('form', 'tr-form tr-panel');
    function bind(label, key, kind, extra) {
      var input = field(f, label, kind || 'input', F[key], 'tr-f-' + key);
      if (extra) { extra(input); }
      input.addEventListener('input', function () { F[key] = input.value; });
      return input;
    }
    bind('Name', 'name');
    bind('Age', 'age', 'input', function (i) { i.inputMode = 'numeric'; });
    bind('Job', 'job');
    bind('City', 'city');
    bind('One line about them', 'short');
    var pick = el('div', 'tr-two');
    pick.appendChild(choose('Call them', F.them, [['her', 'she / her'], ['him', 'he / him'], ['them', 'they / them']],
      function (v) { F.them = v; }));
    pick.appendChild(choose('Mostly uses', F.device, [['phone', 'A phone'], ['desk', 'A computer']],
      function (v) { F.device = v; }));
    f.appendChild(pick);
    bind('Everything about them, written to them (“You are…”), a heading for each part', 'profile', 'textarea',
      function (i) { i.rows = 18; i.classList.add('tr-profile-area'); });
    var row = el('div', 'tr-actions');
    var save = button('tr-btn tr-primary', editing ? 'Save the changes' : 'Save the new tester');
    save.type = 'submit';
    save.disabled = !!S.busy;
    row.appendChild(save);
    row.appendChild(link('Cancel', editing ? HOME + '/tester/' + w.key : HOME + '/testers', 'tr-btn'));
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      S.busy = 'save'; S.error = '';
      var body = { name: F.name, age: F.age, job: F.job, city: F.city, short: F.short, them: F.them, device: F.device,
                   profile: F.profile, written_by_rouh: F.written };
      call(editing ? '/testers/' + w.key : '/testers/new', body).then(function (j) {
        S.busy = ''; S.form = null; S.shell = null;
        S.carry = editing ? 'Saved.' : j.tester.first + ' is added.';
        go(HOME + '/tester/' + j.tester.key);
      }, fail);
    });
    root.appendChild(f);
  }

  /* ---- how it works, and its words ---- */

  function drawHow(root) {
    moved('');
    root.appendChild(el('h1', 'tr-headline', 'How trials work'));
    var grid = el('div', 'tr-how');
    var s1 = section('tr-panel', 'The words');
    [['A tester', 'a made-up person with a whole life written down, such as Vesela, 41, head of HR in Plovdiv. ' +
       'A model plays them. They know only what is on the screen, never how Rouh is built.'],
     ['A job', 'one thing a tester tries, such as signing in for the first time. Every try of the same thing is kept in the same job.'],
     ['A try', 'one tester going at a job from the first screen, on a phone, saying out loud what they see, think and do, ' +
       'with a picture of the screen at every step.'],
     ['The three questions', 'on every new screen the tester answers: What is this? What do I do here? What happens when I do it? ' +
       'One they cannot answer is a problem.'],
     ['Passed', 'the tester managed it, and nothing stopped or confused them.'],
     ['Rounds', 'when a change does not pass, Rouh fixes what tripped the tester and a new tester tries again: the first try, ' +
       'the second try after fixes, and the third and last. After that the change goes out anyway, its problems stay open, and you are told.']]
      .forEach(function (x) { s1.appendChild(said(x[0], x[1])); });
    grid.appendChild(s1);
    var sm = section('tr-panel', 'Two kinds of try');
    sm.appendChild(said('Automatic test while building', 'every change you will see is tried by a tester before it ships. ' +
      'The builder fixes what tripped them, within what you already approved, and it is tried again: at most two rounds of ' +
      'fixes, then it ships. Nobody asks you anything.'));
    sm.appendChild(said('Review you asked for', 'when you ask for someone to test something, for example “Have Vesela test ' +
      'this”, or press Run a trial. You get the whole walk-through, what they found and what Rouh suggests. Nothing is fixed until you go through ' +
      'the problems and choose what is done and how; Fix the ones I chose then starts one run that does only those.'));
    grid.appendChild(sm);
    var s2 = section('tr-panel', 'How bad a problem is');
    [['blocked', 'they could not go on.'], ['confused', 'they did not understand something they needed.'],
     ['annoyed', 'they understood, but it bothered them.'], ['minor', 'a small thing that bothered nobody much.']].forEach(function (x) {
      var p = el('p', 'tr-said tr-sev-line');
      p.appendChild(sev(x[0], true));
      p.appendChild(document.createTextNode(': ' + x[1]));
      s2.appendChild(p);
    });
    s2.appendChild(el('p', 'tr-dim', 'Each kind has its own shape as well as its colour: an octagon, a diamond, a triangle and a ring.'));
    grid.appendChild(s2);
    var s3 = section('tr-panel', 'What you can do with a problem');
    [['Talk it over', 'write to Rouh on the problem’s page. Rouh answers there, with the problem, its picture and the whole try in front of it.'],
     ['Fix it like this', 'say how it should be fixed. The next round of fixes reads it and does it your way.'],
     ['Send as feedback', 'it goes, with its picture, to Rouh’s list of changes to make to itself. Edit before sending lets you change the words first.'],
     ['Not a problem, Won’t fix', 'set it aside. A tester who runs into it again no longer fails the try.'],
     ['Undo', 'every choice can be taken back: press Undo on the message that appears, or Take it back later.'],
     ['Fixed', 'only a later try that passes the same screen without tripping on it marks a problem fixed. Nobody marks it by hand.']]
      .forEach(function (x) { s3.appendChild(said(x[0], x[1])); });
    grid.appendChild(s3);
    var s4 = section('tr-panel', 'Where the ideas came from');
    s4.appendChild(el('p', 'tr-dim', 'Two earlier tests you liked: Mira Koleva’s ten use cases as a new customer, each told ' +
      'screen by screen in her own words, and Teodora Angelova’s bug hunt, each bug worst first with its picture, what should ' +
      'have happened, what did, and how to fix it. The look is the Page atlas, the design that scored best in design test 3.'));
    grid.appendChild(s4);
    root.appendChild(grid);
  }

  window.RouhTrials = {
    mount: function (wrap, sub, host) {
      var was = S.sub;
      S.host = host || null;
      S.sub = String(sub || '');
      if (was !== S.sub) {
        S.said = S.carry || ''; S.carry = ''; S.error = ''; S.confirm = ''; S.draftError = ''; S.editJob = false; S.tryBad = '';
        if (!/^problem\//.test(S.sub)) { S.deciding = false; }
        if (!/^(testers\/new|tester\/[a-z0-9]+\/edit)$/.test(S.sub)) { S.form = null; }
        if (S.sub === 'testers/new' && S.form && S.form.key) { S.form = null; }
        if (S.sub !== 'problems') { S.probView.all = false; }
      }
      S.root = el('div', 'tr');
      wrap.appendChild(S.root);
      draw();
      load();
    }
  };
}());
