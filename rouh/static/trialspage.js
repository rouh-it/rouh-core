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

   The pages, each its own address under /evolution/trials:
     ''                 the jobs: what is being tested (never who: that is inside a job)
     job/<n>            one job: its goal and what it covers, and its tries, newest first, each with who did it
     <n>                one try: step by step, how it ended, and its problems, worst first
     problems           every problem across the jobs, open first
     problem/<n>        one problem: every sighting, its discussion with Rouh, and what to do with it
     testers            the testers; testers/new adds one; tester/<key> one whole; tester/<key>/edit changes one
     how                how trials work, and the words they use
   `window.RouhTrials` is what `evolutionpage.js` mounts. Plain words only: Vesela tries this page too. */
(function () {
  'use strict';

  var API = '/api/trials';
  var S = { root: null, sub: '', host: null, data: {}, error: '', said: '', busy: '', seq: 0, poll: 0,
            jobsFilter: { persona: '', result: '' }, probFilter: { status: 'open', who: '', job: '' },
            tryBad: '', ticked: {}, confirm: '', editJob: false, deciding: false, draft: null, form: null, carry: '',
            sayDraft: null };

  var RESULT = {
    passed: ['Passed', 'green'], failed: ['Did not pass', 'rose'], running: ['Trying now', 'amber'],
    queued: ['Waiting to start', 'slate'], broken: ['Could not finish', 'slate']
  };
  var MANAGED = { yes: 'Yes', partly: 'Partly', no: 'No' };
  // Said of the tester, by name of what they are: "Confused them" left Vesela asking who "them" is (trial 21).
  var BAD = { blocked: 'Stopped the tester', confused: 'Confused the tester', annoyed: 'Annoyed the tester', minor: 'Small' };
  var BAD_ORDER = ['blocked', 'confused', 'annoyed', 'minor'];
  var BAD_TONE = { blocked: 'rose', confused: 'amber', annoyed: 'violet', minor: 'slate' };
  var STAND = {
    open: ['Not fixed yet', 'amber'], decided: ['Decided how to fix it', 'blue'], fixed: ['Fixed', 'green'],
    set_aside: ['Set aside', 'slate']
  };
  var VERDICT_LINE = { not_a_problem: 'Not a problem', wont_fix: 'Won’t fix', decided: 'Decided how to fix it',
                       sent: 'Sent as feedback' };

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
    var a = el('a', cls || 'evo-link', text);
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
  function date(t) { return t ? new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : ''; }
  function minutes(s) {
    var m = Math.round((s || 0) / 60);
    return m < 1 ? 'under a minute' : m === 1 ? '1 minute' : m + ' minutes';
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function chip(text, tone) { return el('span', 'inc-chip tr-chip inc-tone-' + tone, text); }
  function result(state) { var r = RESULT[state] || ['Not tried yet', 'slate']; return chip(r[0], r[1]); }
  function badChip(b) { return chip(BAD[b] || b, BAD_TONE[b] || 'slate'); }
  function standChip(p) {
    if (p.awaiting_choice) { return chip('Waiting for your choice', 'amber'); }
    if (p.standing === 'set_aside') { return chip(VERDICT_LINE[p.verdict] || 'Set aside', 'slate'); }
    if (p.standing === 'decided' && p.verdict === 'sent') { return chip('Sent as feedback', 'blue'); }
    var s = STAND[p.standing] || STAND.open;
    return chip(s[0], s[1]);
  }
  function upper(text) { text = String(text || ''); return text.charAt(0).toUpperCase() + text.slice(1); }
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
    if (title) { s.appendChild(el('h4', 'evo-part-h tr-sec-h', title)); }
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

  /* A face for a tester: their initials on a colour that is always theirs. */
  function face(t, size) {
    var name = (t && (t.name || t.persona_name || t.first)) || '?';
    var key = (t && (t.key || t.id || t.persona)) || name;
    var h = 7;
    for (var i = 0; i < key.length; i++) { h = (h * 31 + key.charCodeAt(i) * 97) % 9973; }
    h = (h * 137) % 360;
    var parts = String(name).trim().split(/\s+/);
    var f = el('span', 'tr-face' + (size ? ' tr-face-' + size : ''),
      (parts[0] || '?').charAt(0).toUpperCase() + (parts.length > 1 ? parts[parts.length - 1].charAt(0).toUpperCase() : ''));
    f.style.setProperty('--hue', String(h));
    f.setAttribute('aria-hidden', 'true');
    return f;
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
    b.addEventListener('click', function () { bigPicture(src, alt, b); });
    return b;
  }
  function bigPicture(src, alt, back) {
    var box = el('div', 'tr-big');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', alt);
    var close = button('ctl tr-big-close', 'Close');
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

  function load() {
    var seq = ++S.seq, w = where(), want;
    S.error = '';
    function keep(name) { return function (j) { if (seq === S.seq) { S.data[name] = j; } }; }
    if (w.page === 'jobs') {
      var q = [];
      if (S.jobsFilter.persona) { q.push('persona=' + encodeURIComponent(S.jobsFilter.persona)); }
      if (S.jobsFilter.result) { q.push('result=' + encodeURIComponent(S.jobsFilter.result)); }
      want = call(q.length ? '?' + q.join('&') : '').then(keep('jobs'));
    } else if (w.page === 'job') { want = call('/jobs/' + w.n).then(keep('job')); }
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
    return want.then(function () { if (seq === S.seq) { draw(); } }, function (e) {
      if (seq !== S.seq) { return; }
      S.error = String((e && e.message) || e);
      draw();
    });
  }
  function loadProblems(seq) {
    var f = S.probFilter, q = [];
    q.push('status=' + (f.status || 'all'));
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
    var w = where();
    tabs(root, w.page);
    if (S.error) {
      var err = el('div', 'tr-err');
      err.appendChild(el('p', 'evo-error', S.error));
      var again = button('ctl tr-small', 'Open this page again');
      again.addEventListener('click', function () { S.error = ''; draw(); load(); });
      err.appendChild(again);
      root.appendChild(err);
    }
    if (S.said) { root.appendChild(el('p', 'evo-said', S.said)); }
    ({ jobs: drawJobs, job: drawJob, 'try': drawTry, problems: drawProblems, problem: drawProblem,
       testers: drawTesters, tester: drawTester, form: drawForm, how: drawHow })[w.page](root, w);
    // At the end of a long page, the way back to every list, so nobody has to press Back three times (trial 17).
    if (w.page === 'job' || w.page === 'try' || w.page === 'problem' || w.page === 'tester') {
      var foot = el('nav', 'tr-foot');
      foot.setAttribute('aria-label', 'Back to a list');
      foot.appendChild(el('span', 'tr-dim', 'Back to:'));
      [['All jobs', HOME], ['All problems', HOME + '/problems'], ['All testers', HOME + '/testers'],
       ['Add a tester', HOME + '/testers/new']].forEach(function (x) {
        foot.appendChild(link(x[0], x[1], 'evo-link'));
      });
      root.appendChild(foot);
    }
    if (keep) { var again = document.getElementById(keep); if (again) { again.focus(); } }
  }

  function tabs(root, page) {
    var on = page === 'job' || page === 'try' || page === 'jobs' ? 'jobs'
      : page === 'problem' || page === 'problems' ? 'problems'
      : page === 'tester' || page === 'testers' || page === 'form' ? 'testers' : 'how';
    var bar = el('nav', 'evo-views tr-tabs');
    bar.setAttribute('aria-label', 'Trials');
    [['jobs', 'Jobs', HOME], ['problems', 'Problems', HOME + '/problems'], ['testers', 'Testers', HOME + '/testers'],
     ['how', 'How it works', HOME + '/how']].forEach(function (v) {
      var a = link(v[1], v[2], 'evo-vtab' + (on === v[0] ? ' on' : ''));
      if (on === v[0]) { a.setAttribute('aria-current', 'page'); }
      bar.appendChild(a);
    });
    root.appendChild(bar);
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

  /* ---- the jobs ---- */

  function drawJobs(root) {
    var d = S.data.jobs;
    moved('');
    root.appendChild(el('p', 'tr-lede', 'A job is one thing a made-up tester tries on a phone, such as signing in for ' +
      'the first time. Open a job to see each try, who did it, and the problems they ran into.'));
    if (!d) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the jobs…')); } return; }
    var people = [['', 'Anyone']].concat((d.testers || []).map(function (t) { return [t.key, t.first]; }));
    if (d.jobs.length || S.jobsFilter.persona || S.jobsFilter.result) {
      var bar = el('div', 'tr-filters');
      bar.appendChild(choose('Tried by', S.jobsFilter.persona, people, function (v) { S.jobsFilter.persona = v; load(); }));
      bar.appendChild(choose('Latest try', S.jobsFilter.result, [['', 'Any result'], ['passed', 'Passed'],
        ['failed', 'Did not pass'], ['running', 'Trying now'], ['broken', 'Could not finish']],
        function (v) { S.jobsFilter.result = v; load(); }));
      root.appendChild(bar);
    }
    if (!d.jobs.length) {
      root.appendChild(el('p', 'tr-empty', S.jobsFilter.persona || S.jobsFilter.result ? 'No job matches that.'
        : 'Nothing has been tried yet. When Rouh changes something you will see, a tester tries it first, and the job shows up here.'));
      return;
    }
    var ul = el('ul', 'tr-list');
    d.jobs.forEach(function (j) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/job/' + j.number, 'tr-row');
      var top = el('span', 'tr-row-top');
      top.appendChild(el('span', 'tr-row-what', j.name));
      top.appendChild(result(j.latest && j.latest.state));
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
    root.appendChild(ul);
  }

  /* ---- one job ---- */

  function drawJob(root, w) {
    root.appendChild(link('← All jobs', HOME, 'evo-link tr-back'));
    var d = S.data.job;
    if (!d || String(d.job.number) !== w.n) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the job…')); } return; }
    var j = d.job;
    moved(j.name);
    var head = section('tr-head');
    head.appendChild(el('h3', 'tr-h', j.name));
    var line = el('div', 'tr-head-line');
    line.appendChild(result(j.latest && j.latest.state));
    line.appendChild(el('span', 'tr-dim', 'Job ' + j.number + ' · ' + plural(j.tries_count, 'try', 'tries') +
      (j.open ? ' · ' + plural(j.open, 'problem') + ' not fixed' : '')));
    head.appendChild(line);
    if (S.editJob) {
      head.appendChild(jobForm(j));
    } else {
      head.appendChild(said('What the tester is asked to do', j.goal ? '“' + j.goal + '”' : 'Not written yet.'));
      if (j.covers) { head.appendChild(said('What it covers', j.covers)); }
      var edit = button('ctl tr-small', j.covers ? 'Change the name or the description' : 'Describe what this job tests');
      edit.addEventListener('click', function () { S.editJob = true; draw(); });
      head.appendChild(edit);
    }
    root.appendChild(head);

    var tries = section('', 'Tries, newest first');
    if (!j.tries.length) { tries.appendChild(el('p', 'tr-empty', 'Nobody has tried it yet.')); }
    var ul = el('ul', 'tr-list');
    j.tries.forEach(function (t) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/' + t.number, 'tr-row tr-try');
      var top = el('span', 'tr-row-top');
      var who = el('span', 'tr-who-line');
      who.appendChild(face({ key: t.persona, name: t.persona_name }));
      var wn = el('span', 'tr-who-name');
      wn.appendChild(el('strong', '', t.persona_name));
      wn.appendChild(el('span', 'tr-dim', tryName(t.round, t.mode)));
      who.appendChild(wn);
      top.appendChild(who);
      top.appendChild(t.mode === 'review' && (t.state === 'passed' || t.state === 'failed') ? reviewChip(t) : result(t.state));
      a.appendChild(top);
      var meta = el('span', 'tr-row-meta');
      meta.appendChild(modeChip(t.mode));
      meta.appendChild(el('span', '', day(t.created_at)));
      if (t.state !== 'queued') { meta.appendChild(el('span', '', plural(t.steps, 'step') + ' · ' + minutes(t.seconds))); }
      if (t.managed) { meta.appendChild(el('span', '', tryLine(t))); }
      meta.appendChild(el('span', t.open ? 'tr-has' : '', !t.problems ? 'No problems'
        : plural(t.problems, 'problem') + (t.open === t.problems ? ', not fixed yet' : t.open ? ', ' + t.open + ' not fixed yet' : ', all fixed or set aside')));
      a.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    tries.appendChild(ul);
    root.appendChild(tries);
    root.appendChild(runAgain(d.personas || [], d['default'], function (persona) {
      return call('/jobs/' + j.number + '/run', { persona: persona });
    }, 'Ask for a review', 'A tester who has seen nothing before tries this job from the start, and you get the whole ' +
      'walk-through and what they found. It takes a few minutes. Nothing is fixed from it until you choose what.'));
    var probs = section('', 'Its problems');
    probs.appendChild(link(j.found ? 'See the ' + plural(j.found, 'problem') + ' this job found' : 'No problems found yet',
      HOME + '/problems', 'evo-link'));
    probs.lastChild.addEventListener('click', function () { S.probFilter = { status: 'all', who: '', job: String(j.number) }; }, true);
    root.appendChild(probs);
  }

  function jobForm(j) {
    var f = el('form', 'tr-form');
    var name = field(f, 'Name', 'input', j.name, 'tr-job-name');
    var goal = field(f, 'What the tester is asked to do, as they would say it', 'textarea', j.goal, 'tr-job-goal');
    var covers = field(f, 'What this job tests, in a line or two', 'textarea', j.covers, 'tr-job-covers');
    var row = el('div', 'tr-actions');
    var save = button('ctl tr-go', 'Save');
    save.type = 'submit';
    var cancel = button('ctl', 'Cancel');
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
      var o = el('option', '', p.first + ' tries it');
      o.value = p.id;
      if (p.id === def) { o.selected = true; }
      pick.appendChild(o);
    });
    row.appendChild(pl);
    var run = button('ctl tr-go', label);
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

  /* ---- one try ---- */

  function drawTry(root, w) {
    var d = S.data['try'];
    if (!d || String(d.trial.number) !== w.n) {
      root.appendChild(link('← All jobs', HOME, 'evo-link tr-back'));
      if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the try…')); }
      return;
    }
    var t = d.trial, name = t.persona_name;
    root.appendChild(t.job ? link('← ' + t.job_name, HOME + '/job/' + t.job, 'evo-link tr-back')
      : link('← All jobs', HOME, 'evo-link tr-back'));
    moved((t.job_name || upper(t.subject)) + ', try ' + t.number);
    var head = section('tr-head');
    head.appendChild(el('h3', 'tr-h', t.job_name || upper(t.subject) || 'A page of Rouh'));
    var who = el('div', 'tr-who-line tr-who-big');
    who.appendChild(face({ key: t.persona, name: name }, 'm'));
    var wn = el('div', 'tr-who-name');
    var nm = el('div');
    nm.appendChild(link(name, HOME + '/tester/' + t.persona, 'evo-link tr-strong'));
    nm.appendChild(document.createTextNode(', a made-up tester, tried it'));
    wn.appendChild(nm);
    wn.appendChild(el('div', 'tr-dim', tryName(t.round, t.mode) + ' · ' + day(t.created_at) + ' · Try ' + t.number));
    who.appendChild(wn);
    head.appendChild(who);
    var line = el('div', 'tr-head-line');
    // A review is a report, not a test to pass: no red "Did not pass" on it (trial 23).
    line.appendChild(t.mode === 'review' && (t.state === 'passed' || t.state === 'failed') ? reviewChip(t) : result(t.state));
    var why = t.mode === 'review' ? '' : verdictWhy(t);
    if (why) { line.appendChild(el('span', 'tr-why', why)); }
    head.appendChild(line);
    head.appendChild(said('What ' + name + ' wanted to do', '“' + t.goal + '”'));
    var facts = el('dl', 'tr-facts');
    [['Managed it?', MANAGED[t.managed] || '–'], ['Steps', String(t.steps)], ['Time it took', minutes(t.seconds)],
     ['Problems found', t.problems ? t.problems + (t.open ? ' (' + t.open + ' not fixed)' : ' (none open)') : 'None']]
      .forEach(function (f) { facts.appendChild(el('dt', '', f[0])); facts.appendChild(el('dd', '', f[1])); });
    if (t.state !== 'queued' && t.state !== 'running') { head.appendChild(facts); }
    if (t.state === 'queued' || t.state === 'running') {
      // A try going on is read again every few seconds, so its steps appear as they happen.
      clearTimeout(S.poll);
      S.poll = setTimeout(function () { if (S.root && S.root.isConnected && S.sub === String(t.number)) { load(); } }, 5000);
      head.appendChild(el('p', 'tr-dim', t.state === 'queued' ? 'This try is about to start. It takes a few minutes.'
        : name + ' is trying it now. Each step appears here as it happens.'));
    }
    if (t.state === 'broken') { head.appendChild(el('p', 'evo-error', 'This try could not finish: ' + (t.why || 'something went wrong.'))); }
    else if (t.why) { head.appendChild(el('p', 'tr-dim', t.why)); }
    head.appendChild(modeBox(t));
    var jump = el('nav', 'tr-jump');
    jump.setAttribute('aria-label', 'On this page');
    [['Step by step', 'tr-steps-sec'], ['How it ended', 'tr-end-sec'], ['Problems (' + (t.found || []).length + ')', 'tr-probs-sec']]
      .forEach(function (j) {
        var b = button('tr-jump-b', j[0]);
        b.addEventListener('click', function () { var to = document.getElementById(j[1]); if (to) { to.scrollIntoView({ block: 'start' }); } });
        jump.appendChild(b);
      });
    head.appendChild(jump);
    root.appendChild(head);

    var walk = t.walk || [];
    var foundAt = {};
    (t.found || []).forEach(function (f) { (foundAt[f.step] = foundAt[f.step] || []).push(f); });
    var story = section('tr-story', 'Step by step', 'tr-steps-sec');
    if (!walk.length) { story.appendChild(el('p', 'tr-dim', 'No steps yet.')); }
    var ol = el('ol', 'tr-steps');
    walk.forEach(function (s) {
      var li = el('li', 'tr-step');
      li.id = 'step-' + s.n;
      var pic = el('div', 'tr-shot');
      if (s.shot) { pic.appendChild(shot(API + '/' + t.number + '/shot/' + s.n, 'What ' + name + ' saw at step ' + s.n)); }
      li.appendChild(pic);
      var words = el('div', 'tr-words');
      words.appendChild(el('div', 'tr-step-n', 'Step ' + s.n + (s.title ? ' · ' + s.title : '')));
      if (s.see) { words.appendChild(said(name + ' saw', s.see)); }
      if (s.think) { words.appendChild(said(name + ' said', '“' + s.think + '”', 'tr-think')); }
      if (s.does) { words.appendChild(said(name + ' did', s.does)); }
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
        words.appendChild(three);
      }
      (foundAt[s.n] || []).forEach(function (f) {
        var p = el('p', 'tr-found');
        p.appendChild(badChip(f.how_bad));
        p.appendChild(el('span', 'tr-found-what', f.what));
        p.appendChild(link('Problem ' + f.number + (f.notes ? ' · ' + plural(f.notes, 'message') : ''), HOME + '/problem/' + f.number));
        words.appendChild(p);
      });
      li.appendChild(words);
      ol.appendChild(li);
    });
    story.appendChild(ol);
    root.appendChild(story);

    var end = section('tr-end', 'How it ended', 'tr-end-sec');
    if (t.managed || t.ending) {
      end.appendChild(said('Did ' + name + ' manage it?', MANAGED[t.managed] || '–'));
      if (t.ending) { end.appendChild(said('In ' + name + '’s words', '“' + t.ending + '”', 'tr-think')); }
      if (t.nearly_gave_up) { end.appendChild(said('Where ' + name + ' nearly gave up', t.nearly_gave_up)); }
      if ((t.closed || []).length) {
        end.appendChild(said('Fixed, because ' + name + ' got past them this time',
          t.closed.map(function (c) { return 'Problem ' + c.number + ': ' + c.what; }).join('; ')));
      }
    } else { end.appendChild(el('p', 'tr-dim', 'It has not ended yet.')); }
    root.appendChild(end);

    root.appendChild(tryProblems(t));
    root.appendChild(runAgain(d.personas || [], t.persona, function (persona) {
      return call('/' + t.number + '/again', { persona: persona });
    }, 'Ask for a review', 'A tester who has seen nothing before tries the same job from the start, and you get a report ' +
      'like this one. It takes a few minutes. Nothing is fixed from it until you choose what.'));
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
    var go2 = button('ctl tr-small tr-go tr-right', picked === 1 ? 'Fix the one I chose' : picked ? 'Fix the ' + picked + ' I chose' : 'Fix the ones I chose');
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
    var by = {};
    found.forEach(function (f) { by[f.how_bad] = (by[f.how_bad] || 0) + 1; });
    var bar = el('div', 'tr-sev');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Show by how bad');
    [['', 'All ' + found.length]].concat(BAD_ORDER.filter(function (b) { return by[b]; }).map(function (b) {
      return [b, BAD[b] + ' ' + by[b]];
    })).forEach(function (o) {
      var b = button('tr-sev-b' + (S.tryBad === o[0] ? ' on' : ''), o[1]);
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
    var cb = button('ctl tr-small', n ? 'Copy the ' + plural(n, 'ticked problem') : 'Tick Copy on problems to copy them as text');
    cb.disabled = !n;
    cb.addEventListener('click', function () {
      var text = found.filter(function (f) { return S.ticked[f.number]; }).map(reportText).join('\n\n---\n\n');
      copyText(text).then(function () { S.said = 'Copied ' + plural(n, 'problem') + '.'; draw(); });
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
    var li = el('li', 'tr-item tr-card' + (f.standing === 'fixed' || f.standing === 'set_aside' ? ' tr-closed' : ''));
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
    chips.appendChild(badChip(f.how_bad));
    chips.appendChild(standChip(f));
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
      var st = button('ctl tr-small', 'See step ' + f.step);
      st.addEventListener('click', function () { var to = document.getElementById('step-' + f.step); if (to) { to.scrollIntoView({ block: 'start' }); } });
      acts.appendChild(st);
    }
    acts.appendChild(link(f.notes ? 'Discuss (' + plural(f.notes, 'message') + ')' : 'Discuss it with Rouh', HOME + '/problem/' + f.number, 'ctl tr-small tr-go'));
    li.appendChild(acts);
    // In a review the owner chooses on each problem, right here, as on Mira's ten suggestions; deciding how
    // happens in the card too, and Rouh's suggestion can be taken as it is (Vesela, trial 25).
    if (o.review && f.standing !== 'fixed') {
      var pick = el('div', 'tr-actions tr-pick');
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
        var use = button('ctl tr-small tr-go', 'Use this fix');
        use.title = 'Fix it the way suggested above: ' + f.fix;
        use.disabled = !!S.busy;
        use.addEventListener('click', function () { choose2('decided', f.fix); });
        pick.appendChild(use);
      }
      var own = button('ctl tr-small', f.verdict === 'decided' ? 'Change how' : 'Say how to fix it');
      own.disabled = !!S.busy;
      own.addEventListener('click', function () { S.cardDeciding = f.number; draw(); });
      pick.appendChild(own);
      [['not_a_problem', 'Not a problem'], ['wont_fix', 'Won’t fix']].forEach(function (v) {
        if (f.verdict === v[0]) { return; }
        var b = button('ctl tr-small', v[1]);
        b.disabled = !!S.busy;
        b.addEventListener('click', function () { choose2(v[0]); });
        pick.appendChild(b);
      });
      li.appendChild(pick);
      if (S.cardDeciding === f.number) {
        var form = el('form', 'tr-form');
        var how = field(form, 'How should it be fixed?', 'textarea', f.decision || f.fix || '', 'tr-how-' + f.number);
        var row = el('div', 'tr-actions');
        var save = button('ctl tr-small tr-go', 'Save how');
        save.type = 'submit';
        var cancel = button('ctl tr-small', 'Cancel');
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

  /* ---- the problems, every job ---- */

  function drawProblems(root) {
    var d = S.data.problems;
    moved('');
    root.appendChild(el('p', 'tr-lede', 'Every problem a tester ran into, in every job, and the ones you noticed yourself. ' +
      'Open one to talk it over with Rouh and decide what to do with it.'));
    if (d && d.counts && !d.counts.open && !d.counts.closed && !(d.counts.by && (d.counts.by.set_aside || d.counts.by.decided))) {
      root.appendChild(el('p', 'tr-empty', d.counts.trials ? 'No problems found yet: every try so far went without one.'
        : 'Nothing has been tried yet, so no problems have been found.'));
      return;
    }
    var f = S.probFilter;
    var bar = el('div', 'tr-filters');
    function set(k) { return function (v) { S.probFilter[k] = v; var seq = ++S.seq; loadProblems(seq).then(draw, fail); }; }
    bar.appendChild(choose('Show', f.status, [['open', 'Not fixed yet'], ['awaiting', 'Waiting for your choice'],
      ['decided', 'Decided how to fix'], ['fixed', 'Fixed'], ['set_aside', 'Set aside'], ['all', 'All problems']], set('status')));
    var people = [['', 'Everyone']];
    ((d && d.testers) || []).forEach(function (p) { people.push([p.key, p.first + (p.archived ? ' (removed)' : '')]); });
    people.push(['owner', 'You']);
    bar.appendChild(choose('Found by', f.who, people, set('who')));
    var jobs = [['', 'Every job']];
    ((d && d.jobs) || []).forEach(function (j) { jobs.push([String(j.number), j.name]); });
    bar.appendChild(choose('Job', f.job, jobs, set('job')));
    root.appendChild(bar);
    if (!d) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the problems…')); } return; }
    if (!d.problems.length) {
      root.appendChild(el('p', 'tr-empty', f.status === 'open' ? 'Nothing is waiting to be fixed.' : 'No problems here.'));
      return;
    }
    root.appendChild(el('p', 'tr-tally', plural(d.problems.length, 'problem') + ', the worst first.'));
    var ul = el('ul', 'tr-list');
    d.problems.forEach(function (p) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/problem/' + p.number, 'tr-row' + (p.standing === 'fixed' || p.standing === 'set_aside' ? ' tr-closed' : ''));
      var top = el('span', 'tr-row-top');
      top.appendChild(el('span', 'tr-row-what', p.what));
      a.appendChild(top);
      var chips = el('span', 'tr-chips');
      chips.appendChild(badChip(p.how_bad));
      chips.appendChild(standChip(p));
      if (p.source === 'owner') { chips.appendChild(chip('Found by you', 'teal')); }
      a.appendChild(chips);
      var meta = el('span', 'tr-row-meta');
      meta.appendChild(el('span', '', p.screen_name || 'Somewhere in Rouh'));
      meta.appendChild(el('span', '', p.count === 1 ? 'Seen once' : 'Seen ' + p.count + ' times'));
      if (p.source !== 'owner') { meta.appendChild(el('span', '', 'Found by ' + names(p.personas, d.testers))); }
      if ((p.jobs || []).length) { meta.appendChild(el('span', '', p.jobs.map(function (j) { return j.name; }).join(', '))); }
      if (p.notes) { meta.appendChild(el('span', '', plural(p.notes, 'message'))); }
      a.appendChild(meta);
      li.appendChild(a);
      ul.appendChild(li);
    });
    root.appendChild(ul);
  }

  function names(keys, testers) {
    return (keys || []).map(function (k) {
      var t = (testers || []).filter(function (x) { return x.key === k; })[0];
      return t ? t.first : upper(k);
    }).join(' and ') || 'a tester';
  }

  /* ---- one problem, and its discussion ---- */

  function drawProblem(root, w) {
    root.appendChild(link('← All problems', HOME + '/problems', 'evo-link tr-back'));
    var d = S.data.problem;
    if (!d || String(d.problem.number) !== w.n) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the problem…')); } return; }
    var p = d.problem;
    moved(p.what);
    var head = section('tr-head');
    head.appendChild(el('div', 'tr-dim', 'Number ' + p.number + ' on the list of every problem' + (p.screen_name ? ' · on ' + p.screen_name : '')));
    head.appendChild(el('h3', 'tr-h', p.what));
    var chips = el('div', 'tr-chips');
    chips.appendChild(badChip(p.how_bad));
    chips.appendChild(standChip(p));
    chips.appendChild(chip(p.count === 1 ? 'Seen once' : 'Seen ' + p.count + ' times', 'slate'));
    if (p.source === 'owner') { chips.appendChild(chip('Found by you', 'teal')); }
    head.appendChild(chips);
    if (p.status === 'closed') {
      head.appendChild(el('p', 'tr-good', 'Fixed on ' + date(p.closed_at) + (p.closed_by ? ': try ' + p.closed_by +
        ' went past this screen without tripping on it.' : '.')));
    }
    var first = (p.sightings || []).filter(function (s) { return s.trial && s.shot; }).slice(-1)[0];
    var body = el('div', 'tr-card-body tr-prob-main');
    if (first) { body.appendChild(shot(API + '/' + first.trial + '/shot/' + first.step, 'The screen when ' + first.persona_name + ' ran into it', 'tr-card-shot')); }
    var words = el('div', 'tr-card-words');
    if (p.expected) { words.appendChild(said('What should have happened', p.expected)); }
    if (p.actual) { words.appendChild(said('What happened', p.actual)); }
    if (p.decision) { words.appendChild(said('You decided: fix it like this', p.decision, 'tr-decided')); }
    if (p.fix) { words.appendChild(said(p.decision ? 'Rouh’s first suggestion' : 'How to fix it', p.fix)); }
    if (!p.expected && !p.actual && !p.fix && !p.decision) {
      words.appendChild(el('p', 'tr-dim', 'This problem was found before testers said what they expected, so only their words are kept.'));
    }
    body.appendChild(words);
    head.appendChild(body);
    // Straight to the box: under the fold, Vesela could not see where to write to Rouh (trial 21).
    var toTalk = button('ctl tr-small tr-go', 'Write to Rouh about it');
    toTalk.addEventListener('click', function () {
      var box = document.getElementById('tr-say-' + p.number);
      if (box) { box.scrollIntoView({ block: 'center' }); box.focus(); }
    });
    head.appendChild(toTalk);
    root.appendChild(head);

    root.appendChild(thread(p));
    root.appendChild(decide(p));

    var seen = section('', 'Every time it was seen');
    var ul = el('ul', 'tr-list');
    (p.sightings || []).forEach(function (s) {
      var li = el('li', 'tr-item tr-sight');
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
    root.appendChild(seen);
  }

  /* What to do with it: set aside, decide how it is fixed, or send it as feedback (Teodora's two buttons). */
  function decide(p) {
    var box = section('tr-decide', 'What should happen with it?');
    if (p.verdict) {
      var now = el('p', 'tr-verdict');
      now.appendChild(el('strong', '', VERDICT_LINE[p.verdict] || p.verdict_name));
      now.appendChild(document.createTextNode(p.verdict_at ? ', ' + day(p.verdict_at) + '.' : '.'));
      box.appendChild(now);
    }
    if (S.deciding) {
      var f = el('form', 'tr-form');
      var how = field(f, 'Fix it like this', 'textarea', p.decision || p.fix || '', 'tr-decision');
      f.appendChild(el('p', 'tr-dim', p.awaiting_choice || isReview(p) ? 'It is fixed your way when you press Fix the ones I chose on the review’s page.'
        : 'The next round of fixes reads this and does it your way.'));
      var row = el('div', 'tr-actions');
      var save = button('ctl tr-go', 'Save the decision');
      save.type = 'submit';
      var cancel = button('ctl', 'Cancel');
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
    // Each choice with one line on what it does: in a row, five buttons sounded the same to Vesela (trial 21).
    var list = el('ul', 'tr-choices');
    function act(text, cls, fn, what) {
      var li = el('li', 'tr-choice');
      var b = button('ctl tr-small' + (cls ? ' ' + cls : ''), text);
      b.disabled = !!S.busy;
      b.addEventListener('click', fn);
      li.appendChild(b);
      li.appendChild(el('span', 'tr-choice-what', what));
      list.appendChild(li);
    }
    act('Fix it like this…', 'tr-go', function () { S.deciding = true; draw(); },
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
    box.appendChild(list);
    box.appendChild(el('p', 'tr-dim', 'After Not a problem or Won’t fix, a tester who runs into it again no longer counts against the change.'));
    return box;
  }

  function isReview(p) { return (p.sightings || []).some(function (x) { return x.mode === 'review'; }); }

  function verdict(p, v, decision) {
    S.busy = 'verdict';
    call('/problems/' + p.number + '/verdict', { verdict: v, decision: decision || '' }).then(function (got) {
      S.busy = ''; S.deciding = false;
      S.data.problem.problem = got.problem;
      S.said = v === '' ? 'Taken back: it is open again.' : 'Saved: ' + (VERDICT_LINE[v] || v) + '.' +
        (v === 'decided' && isReview(got.problem) ? ' It is fixed when you press Fix the ones I chose on the review’s page.' : '');
      draw();
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
          S.said = 'Sent as feedback.';
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
    var box = section('tr-thread', 'Talk it over with Rouh');
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
    if (!(p.thread || []).length) {
      box.appendChild(el('p', 'tr-dim', 'Ask Rouh what it thinks is going on, or say how you see it. Rouh answers here, ' +
        'with the problem, its picture and the whole try in front of it.'));
    }
    box.appendChild(list);
    if (p.unanswered) { box.appendChild(el('p', 'evo-error', p.unanswered)); }
    var f = el('form', 'tr-form tr-say');
    var area = el('textarea', 'tr-input tr-area');
    area.id = 'tr-say-' + p.number;
    area.rows = 3;
    area.placeholder = 'Write to Rouh about this problem';
    area.setAttribute('aria-label', 'Write to Rouh about this problem');
    if (S.sayDraft && S.sayDraft.n === p.number) { area.value = S.sayDraft.text; }
    // It grows as she types, so the whole message can be read before it is sent (trial 22).
    function grow() { area.style.height = 'auto'; area.style.height = Math.min(area.scrollHeight + 2, 320) + 'px'; }
    area.addEventListener('input', function () { S.sayDraft = { n: p.number, text: area.value }; grow(); });
    setTimeout(grow, 0);
    f.appendChild(area);
    var row = el('div', 'tr-actions tr-end-row');
    var send = button('ctl tr-go', S.busy === 'say' ? 'Rouh is answering…' : 'Send to Rouh');
    send.type = 'submit';
    send.disabled = !!S.busy;
    row.appendChild(send);
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!area.value.trim()) { area.focus(); return; }
      S.busy = 'say'; draw();
      call('/problems/' + p.number + '/say', { text: area.value }).then(function (got) {
        S.busy = ''; S.sayDraft = null;
        S.data.problem.problem = got.problem;
        draw();
      }, fail);
    });
    box.appendChild(f);
    return box;
  }

  /* ---- pausing (Petar, 5 November 2026: "a pause button I can toggle on/off") ---- */

  /* Pause or resume one tester (key), or everyone (no key). The page changes at once, before Rouh answers,
     and goes back, with the reason, if Rouh could not do it. Nothing asks first. */
  function setPause(key, on, first) {
    var lists = [S.data.testers && S.data.testers.testers, S.data.tester && [S.data.tester.tester]];
    function apply(v) {
      if (!key) {
        if (S.data.testers) { S.data.testers.paused_all = v; }
        if (S.data.tester) { S.data.tester.tester.paused_all = v; }
        return;
      }
      lists.forEach(function (l) { (l || []).forEach(function (t) { if (t.key === key) { t.paused = v; } }); });
    }
    apply(on);
    S.error = '';
    // The box at the top already says it for everyone, so it is not said twice (trial 38).
    S.said = !key ? ''
      : (on ? first + ' is paused. ' + first + ' starts no new try until you resume.'
        : allPaused() ? first + ' is resumed, but all testing is still paused, so ' + first + ' waits for that too.'
          : first + ' is testing again.');
    draw();
    call(key ? '/testers/' + key + '/pause' : '/pause', { on: on }).then(function () {}, function (e) {
      apply(!on);
      S.said = '';
      fail(e);
    });
  }

  function allPaused() {
    return !!((S.data.testers && S.data.testers.paused_all) || (S.data.tester && S.data.tester.tester.paused_all));
  }

  function pauseButton(key, paused, first, cls) {
    var b = button('ctl tr-pause-b' + (paused ? ' is-paused' : '') + (cls ? ' ' + cls : ''),
                   paused ? 'Resume' : 'Pause');
    b.setAttribute('aria-pressed', paused ? 'true' : 'false');
    b.setAttribute('aria-label', (paused ? 'Resume ' : 'Pause ') + (first || 'all testing'));
    b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); setPause(key, !paused, first); });
    return b;
  }

  /* The switch for everyone, at the top of the testers list. */
  function pauseAllBox(on, live) {
    live = live || [];
    var held = live.filter(function (t) { return t.paused; });
    var every = live.length > 0 && held.length === live.length;
    var box = el('div', 'tr-pause-all' + (on || every ? ' is-paused' : ''));
    var words = el('div', 'tr-pause-words');
    var names = held.map(function (t) { return t.first; }).join(' and ');
    words.appendChild(el('span', 'tr-pause-title', on ? 'All testing is paused'
      : every ? (live.length === 1 ? names + ' is paused' : 'Every tester is paused')
      : held.length ? 'Testing is on for ' + (live.length - held.length) + ' of ' + live.length + ' testers' : 'Testing is on'));
    words.appendChild(el('span', 'tr-dim', on
      ? 'No tester starts a new try, by itself or when you ask. A try already going may finish. Rouh still builds ' +
        'and ships changes, nightly runs included, just without a tester trying them. Resume any time.'
      : every ? names + (held.length === 1 ? ' is' : ' are') + ' paused on ' + (held.length === 1 ? 'their row' : 'their rows') +
        ', so no try starts. Press Resume on a row to turn that tester back on.'
      : held.length ? names + (held.length === 1 ? ' is' : ' are') + ' paused. Press Resume on a row to turn that tester back on, ' +
        'or pause all ' + live.length + ' here.'
      : 'Testers try changes as usual. Pause one tester on their row, or all ' + live.length + ' here. You can resume any time.'));
    box.appendChild(words);
    // With every tester already paused on their own, a second Pause here only made people doubt (trial 37).
    if (every && !on) { return box; }
    var b = pauseButton('', on, '', 'tr-pause-big');
    b.textContent = on ? 'Resume all testing' : 'Pause all testing';
    b.setAttribute('aria-label', on ? 'Resume all testing' : 'Pause all testing');
    box.appendChild(b);
    return box;
  }

  function pausedChip(t, all) {
    if (t.paused) { return chip('Paused', 'amber'); }
    if (all) { return chip('Paused', 'amber'); }
    return null;
  }

  /* ---- the testers ---- */

  function drawTesters(root) {
    var d = S.data.testers;
    moved('');
    root.appendChild(el('p', 'tr-lede', 'The made-up people who try Rouh’s changes on their phones. Each has a whole ' +
      'life written down, and that is what they are told before every try.'));
    if (d) { root.appendChild(pauseAllBox(!!d.paused_all, d.testers.filter(function (t) { return !t.archived; }))); }
    var add = link('Add a tester', HOME + '/testers/new', 'ctl tr-go tr-add');
    root.appendChild(add);
    if (!d) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the testers…')); } return; }
    var live = d.testers.filter(function (t) { return !t.archived; });
    var gone = d.testers.filter(function (t) { return t.archived; });
    var ul = el('ul', 'tr-list tr-people');
    live.forEach(function (t) { ul.appendChild(personCard(t, !!d.paused_all)); });
    root.appendChild(ul);
    if (!live.length) { root.appendChild(el('p', 'tr-empty', 'There are no testers. Add one, and they try every change.')); }
    if (gone.length) {
      var det = el('details', 'brown-toggle');
      det.appendChild(el('summary', '', 'Removed testers (' + gone.length + ')'));
      var b = el('div', 'brown-toggle-body');
      b.appendChild(el('p', 'tr-dim', 'They no longer try anything. Their old tries still say who did them.'));
      var ul2 = el('ul', 'tr-list tr-people');
      gone.forEach(function (t) { ul2.appendChild(personCard(t)); });
      b.appendChild(ul2);
      det.appendChild(b);
      root.appendChild(det);
    }
  }

  function personCard(t, all) {
    var li = el('li', 'tr-item' + (t.archived ? '' : ' tr-person-item') + ((t.paused || all) && !t.archived ? ' is-paused' : ''));
    var a = link('', HOME + '/tester/' + t.key, 'tr-row tr-person');
    a.appendChild(face(t, 'l'));
    var words = el('span', 'tr-person-words');
    var top = el('span', 'tr-row-top');
    top.appendChild(el('span', 'tr-row-what', t.name + (t.age ? ', ' + t.age : '')));
    var chips = el('span', 'tr-chips');
    if (t['default']) { chips.appendChild(chip('Tries every change', 'green')); }
    var pc = t.archived ? null : pausedChip(t, all);
    if (pc) { chips.appendChild(pc); }
    top.appendChild(chips);
    words.appendChild(top);
    var jc = [t.job, t.city].filter(Boolean).join(' · ');
    if (jc) { words.appendChild(el('span', 'tr-row-goal', jc)); }
    if (t.short) { words.appendChild(el('span', 'tr-person-short', t.short)); }
    words.appendChild(el('span', 'tr-row-meta', plural(t.tries, 'try', 'tries') + ' · ' + plural(t.problems, 'problem') + ' found' +
      (t.running ? ' · ' + (t.running === 1 ? 'a try is going now' : t.running + ' tries going now') : '')));
    a.appendChild(words);
    li.appendChild(a);
    if (!t.archived) {
      var bar = el('div', 'tr-person-bar');
      bar.appendChild(el('span', 'tr-dim', all ? t.first + ' is paused with everyone. Resume all testing at the top.'
        : t.paused ? t.first + ' is paused' : t.first + ' is testing'));
      // While all testing is paused, a row's own button only made people unsure (trial 38): the one at the top lets them go.
      if (!all) { bar.appendChild(pauseButton(t.key, !!t.paused, t.first)); }
      li.appendChild(bar);
    }
    return li;
  }

  function drawTester(root, w) {
    root.appendChild(link('← All testers', HOME + '/testers', 'evo-link tr-back'));
    var d = S.data.tester;
    if (!d || d.tester.key !== w.key) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening the tester…')); } return; }
    var t = d.tester, first = t.first;
    moved(t.name);
    var head = section('tr-head tr-person-head');
    head.appendChild(face(t, 'xl'));
    var hw = el('div', 'tr-person-words');
    hw.appendChild(el('h3', 'tr-h', t.name + (t.age ? ', ' + t.age : '')));
    var jc = [t.job, t.city].filter(Boolean).join(' · ');
    if (jc) { hw.appendChild(el('p', 'tr-goal', jc)); }
    if (t.short) { hw.appendChild(el('p', 'tr-dim', t.short)); }
    var chips = el('div', 'tr-chips');
    if (t['default']) { chips.appendChild(chip('Tries every change', 'green')); }
    if (t.archived) { chips.appendChild(chip('Removed', 'slate')); }
    var pc = t.archived ? null : pausedChip(t, t.paused_all);
    if (pc) { chips.appendChild(pc); }
    chips.appendChild(chip(t.device === 'desk' ? 'Mostly on a computer' : 'Mostly on a phone', 'slate'));
    chips.appendChild(chip(plural(t.tries_count, 'try', 'tries') + ' · ' + plural(t.problems, 'problem') + ' found', 'slate'));
    hw.appendChild(chips);
    head.appendChild(hw);
    root.appendChild(head);
    if (!t.archived) {
      var pbox = el('div', 'tr-pause-all tr-pause-one' + (t.paused || t.paused_all ? ' is-paused' : ''));
      var pw = el('div', 'tr-pause-words');
      pw.appendChild(el('span', 'tr-pause-title', t.paused ? first + ' is paused' : t.paused_all
        ? first + ' is paused with everyone' : first + ' is testing'));
      pw.appendChild(el('span', 'tr-dim', t.paused || t.paused_all
        ? first + ' starts no new try, by itself or when you ask.' + (t['default'] ? ' Changes are still built and ' +
          'shipped, without a tester trying them, and ' + first + ' tries every change again once resumed.' : '') + (t.paused && t.paused_all ? ' Resuming ' + first +
          ' alone is not enough while all testing is paused.' : !t.paused && t.paused_all
          ? ' Resume all testing on the testers list to let ' + first + ' go again.' : '')
        : (t['default'] ? first + ' tries every change Rouh makes that you will see.' : first + ' tries only when you ask for ' +
          first + ' by name.')));
      pw.appendChild(el('span', 'tr-dim', t.running
        ? (t.running === 1 ? 'A try by ' + first + ' is going now' : t.running + ' tries by ' + first + ' are going now') +
          (t.paused || t.paused_all ? '; it may finish.' : '.')
        : 'No try by ' + first + ' is going now.'));
      if (t.skipped) {
        pw.appendChild(el('span', 'tr-dim', plural(t.skipped, 'try', 'tries') + ' skipped while paused' +
          (t.skipped_at ? ', the last on ' + day(t.skipped_at) : '') + '.'));
      }
      pbox.appendChild(pw);
      pbox.appendChild(pauseButton(t.key, !!t.paused, first, 'tr-pause-big'));
      root.appendChild(pbox);
      var acts = el('div', 'tr-actions');
      acts.appendChild(link('Change ' + first + '’s profile', HOME + '/tester/' + t.key + '/edit', 'ctl tr-small'));
      if (!t['default']) {
        var def = button('ctl tr-small', 'Make ' + first + ' try every change');
        def.addEventListener('click', function () {
          call('/testers/' + t.key + '/default', {}).then(function () { S.said = first + ' now tries every change.'; load(); }, fail);
        });
        acts.appendChild(def);
        var rm = button('ctl tr-small tr-danger', 'Remove ' + first);
        rm.addEventListener('click', function () { S.confirm = t.key; draw(); });
        acts.appendChild(rm);
      }
      root.appendChild(acts);
      if (S.confirm === t.key) {
        var c = el('div', 'tr-confirm');
        c.setAttribute('role', 'alertdialog');
        c.setAttribute('aria-label', 'Remove ' + first + '?');
        c.appendChild(el('p', '', 'Remove ' + first + '? ' + first + ' will not try anything again. The ' +
          plural(t.tries_count, 'try', 'tries') + ' ' + first + ' already did stay, and still say who did them.'));
        var row = el('div', 'tr-actions');
        var yes = button('ctl tr-small tr-danger', 'Yes, remove ' + first);
        yes.addEventListener('click', function () {
          call('/testers/' + t.key + '/remove', {}).then(function () {
            S.confirm = ''; S.carry = first + ' is removed.'; go(HOME + '/testers');
          }, fail);
        });
        var no = button('ctl tr-small', 'Keep ' + first);
        no.addEventListener('click', function () { S.confirm = ''; draw(); });
        row.appendChild(yes);
        row.appendChild(no);
        c.appendChild(row);
        root.appendChild(c);
        setTimeout(function () { no.focus(); }, 0);
      }
    }
    if (t.made_by === 'rouh') { root.appendChild(el('p', 'tr-dim', 'Rouh wrote this profile from a sentence, and you kept it.')); }

    var prof = section('tr-profile', 'Everything written about ' + first);
    prof.appendChild(el('p', 'tr-dim', 'This is exactly what ' + first + ' is told before every try, written to ' +
      ({ her: 'her', him: 'him' }[t.them] || 'them') + '.'));
    var jumpTo = el('details', 'tr-toc-box');
    jumpTo.appendChild(el('summary', 'tr-toc-sum', 'Jump to a part of ' + first + '’s life'));
    var toc = el('nav', 'tr-toc');
    toc.setAttribute('aria-label', 'Parts of ' + first + '’s profile');
    jumpTo.appendChild(toc);
    (t.sections || []).forEach(function (s, i) {
      var b = button('tr-jump-b', s.title);
      b.addEventListener('click', function () { var to = document.getElementById('tr-part-' + i); if (to) { to.scrollIntoView({ block: 'start' }); } });
      toc.appendChild(b);
    });
    prof.appendChild(jumpTo);
    (t.sections || []).forEach(function (s, i) {
      var part = el('div', 'tr-part');
      part.id = 'tr-part-' + i;
      part.appendChild(el('h5', 'tr-part-h', s.title));
      part.appendChild(prose(s.text));
      prof.appendChild(part);
    });
    root.appendChild(prof);

    var hist = section('', first + '’s tries');
    if (!t.tries.length) { hist.appendChild(el('p', 'tr-dim', first + ' has not tried anything yet.')); }
    var ul = el('ul', 'tr-list');
    t.tries.forEach(function (x) {
      var li = el('li', 'tr-item');
      var a = link('', HOME + '/' + x.number, 'tr-row');
      var top = el('span', 'tr-row-top');
      top.appendChild(el('span', 'tr-row-what', x.job_name || upper(x.subject) || 'A page of Rouh'));
      top.appendChild(result(x.state));
      a.appendChild(top);
      a.appendChild(el('span', 'tr-row-meta', day(x.created_at) + ' · ' + tryName(x.round, x.mode) + ' · ' +
        (x.problems ? plural(x.problems, 'problem') : 'No problems')));
      li.appendChild(a);
      ul.appendChild(li);
    });
    hist.appendChild(ul);
    root.appendChild(hist);
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
    root.appendChild(link(editing ? '← Back to the tester' : '← All testers', editing ? HOME + '/tester/' + w.key : HOME + '/testers', 'evo-link tr-back'));
    var F = S.form;
    if (!F || (editing && F.key !== w.key)) { if (!S.error) { root.appendChild(el('p', 'evo-loading', 'Opening…')); } return; }
    moved(editing ? F.name : 'New tester');
    root.appendChild(el('h3', 'tr-h', editing ? 'Change ' + (F.name.split(' ')[0] || 'the tester') + '’s profile' : 'Add a tester'));
    if (!editing) {
      var quick = section('tr-quick', 'Describe them in a sentence, and Rouh writes the rest');
      var q = el('textarea', 'tr-input tr-area');
      q.id = 'tr-sentence';
      q.rows = 2;
      q.value = F.sentence;
      q.placeholder = 'For example: a retired teacher in Varna, 67, who is wary of apps and reads everything twice.';
      q.setAttribute('aria-label', 'Describe the new tester in a sentence');
      q.addEventListener('input', function () { F.sentence = q.value; });
      quick.appendChild(q);
      var wr = button('ctl tr-go', S.busy === 'draft' ? 'Rouh is writing… about a minute' : 'Let Rouh write the whole profile');
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
      if (S.draftError) { quick.appendChild(el('p', 'evo-error', S.draftError)); }
      quick.appendChild(el('p', 'tr-dim', 'Rouh only fills in the boxes below. Nothing is kept until you press Save at the bottom. ' +
        'Or fill in everything yourself.'));
      root.appendChild(quick);
    }
    var f = el('form', 'tr-form');
    function bind(label, key, kind, extra) {
      var input = field(f, label, kind || 'input', F[key], 'tr-f-' + key);
      if (extra) { extra(input); }
      input.addEventListener('input', function () { F[key] = input.value; });
      return input;
    }
    var two = el('div', 'tr-two');
    f.appendChild(two);
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
    var prof = bind('Everything about them, written to them (“You are…”), a heading for each part', 'profile', 'textarea',
      function (i) { i.rows = 18; i.classList.add('tr-profile-area'); });
    void prof;
    var row = el('div', 'tr-actions');
    var save = button('ctl tr-go', editing ? 'Save the changes' : 'Save the new tester');
    save.type = 'submit';
    save.disabled = !!S.busy;
    row.appendChild(save);
    row.appendChild(link('Cancel', editing ? HOME + '/tester/' + w.key : HOME + '/testers', 'ctl'));
    f.appendChild(row);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      S.busy = 'save'; S.error = '';
      var body = { name: F.name, age: F.age, job: F.job, city: F.city, short: F.short, them: F.them, device: F.device,
                   profile: F.profile, written_by_rouh: F.written };
      call(editing ? '/testers/' + w.key : '/testers/new', body).then(function (j) {
        S.busy = ''; S.form = null;
        S.carry = editing ? 'Saved.' : j.tester.first + ' is added.';
        go(HOME + '/tester/' + j.tester.key);
      }, fail);
    });
    root.appendChild(f);
  }

  /* ---- how it works, and its words ---- */

  function drawHow(root) {
    moved('');
    var s1 = section('', 'How a trial works');
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
    root.appendChild(s1);
    var sm = section('', 'Two kinds of try');
    sm.appendChild(said('Automatic test while building', 'every change you will see is tried by a tester before it ships. ' +
      'The builder fixes what tripped them, within what you already approved, and it is tried again: at most two rounds of ' +
      'fixes, then it ships. Nobody asks you anything.'));
    sm.appendChild(said('Review you asked for', 'when you ask for someone to test something, for example “Have Vesela test ' +
      'this”. You get the whole walk-through, what they found and what Rouh suggests. Nothing is fixed until you go through ' +
      'the problems and choose what is done and how; Fix the ones I chose then starts one run that does only those.'));
    root.appendChild(sm);
    var s2 = section('', 'How bad a problem is');
    [['blocked', 'they could not go on.'], ['confused', 'they did not understand something they needed.'],
     ['annoyed', 'they understood, but it bothered them.'], ['minor', 'a small thing that bothered nobody much.']].forEach(function (x) {
      var p = el('p', 'tr-said');
      p.appendChild(badChip(x[0]));
      p.appendChild(document.createTextNode(': ' + x[1]));
      s2.appendChild(p);
    });
    root.appendChild(s2);
    var s3 = section('', 'What you can do with a problem');
    [['Talk it over', 'write to Rouh on the problem’s page. Rouh answers there, with the problem, its picture and the whole try in front of it.'],
     ['Fix it like this', 'say how it should be fixed. The next round of fixes reads it and does it your way.'],
     ['Send as feedback', 'it goes, with its picture, to Rouh’s list of changes to make to itself. Edit before sending lets you change the words first.'],
     ['Not a problem, Won’t fix', 'set it aside. A tester who runs into it again no longer fails the try.'],
     ['Fixed', 'only a later try that passes the same screen without tripping on it marks a problem fixed. Nobody marks it by hand.']]
      .forEach(function (x) { s3.appendChild(said(x[0], x[1])); });
    root.appendChild(s3);
    var s4 = section('', 'Where the ideas came from');
    s4.appendChild(el('p', 'tr-dim', 'Two earlier tests you liked: Mira Koleva’s ten use cases as a new customer, each told ' +
      'screen by screen in her own words, and Teodora Angelova’s bug hunt, each bug worst first with its picture, what should ' +
      'have happened, what did, and how to fix it.'));
    root.appendChild(s4);
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
      }
      S.root = el('div', 'tr');
      wrap.appendChild(S.root);
      draw();
      load();
    }
  };
}());
