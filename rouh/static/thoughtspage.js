/* Thoughts, at /thoughts: the person's own thoughts, kept in their words
   (`rouh/thoughts.py`, `rouh/web/thoughts.py`).

   Petar, 12 October 2026: a thought he wanted kept was a note in Synapse,
   found only by search, with no list of them anywhere - "But that is exactly
   what I was interested in getting solved". So here they are, newest first
   and grouped by month, each one whole with when and how it came, with a
   search over their words, a filter by topic, and on each one Edit, Archive
   and Follow up: a later thought on the same line of thinking, linked to it,
   so a line of thinking can grow over time.

   Each new thought is taken further by itself (`rouh/thought_enrich.py`;
   Petar, 14 October 2026, fr_f2b63641423a): Rouh makes it a task of its own
   and a run researches it and writes its enriched version, a page with a
   visual explainer. Every thought says where that stands - Enriching, then
   View enriched version with Research again beside it (a fresh run in the
   same task, Petar, 15 October 2026), or why it failed with Try again; a
   thought kept before any of this has Research it - on the list and
   on its own page at `/thoughts/<its number>`, which shows that one thought
   whole. The enriched page opens on the canvas, in its task; the thought's
   own words stay here, unchanged.

   The layer, its address and its row in the sidebar are app/runs.js's
   (`thoughtsOpen`), handed over through `window.RouhThoughtsHost`. */
(function () {
  'use strict';

  var T = { open: false, focus: '', data: null, error: '', seq: 0, loading: false,
            // The thought on its own page (`focus`), read by itself.
            one: null, oneError: '', oneSeq: 0, poll: 0,
            q: '', tag: '', archived: false,
            // The thought being edited or followed up, and what is half written in it.
            editing: '', following: '', flash: '', busy: '', said: '',
            draft: '', searchTimer: 0 };

  function host() { return window.RouhThoughtsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text, run, title) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) { b.title = title; }
    b.addEventListener('click', run);
    return b;
  }

  /* ---- words ---- */

  function monthOf(at) {
    var d = new Date(at * 1000);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }
  function monthSaid(at) {
    return new Date(at * 1000).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }
  function when(at) {
    var d = new Date(at * 1000);
    var same = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short',
                                         year: same ? undefined : 'numeric',
                                         hour: '2-digit', minute: '2-digit' });
  }
  function counted(n, one, many) { return n === 1 ? '1 ' + one : n + ' ' + many; }

  /* ---- reading and writing ---- */

  function load() {
    var seq = ++T.seq;
    T.loading = true;
    T.error = '';
    if (T.open) { draw(); }
    var q = '/api/thoughts?q=' + encodeURIComponent(T.q) + '&tag=' + encodeURIComponent(T.tag) +
      (T.archived ? '&archived=1' : '');
    return fetch(q, { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== T.seq) { return; }
          T.loading = false;
          if (!r.ok || !j) {
            T.error = (j && j.error) || 'Your thoughts could not be read. Try again in a moment.';
          } else {
            T.data = j;
            if (host().counted && j.counts) { host().counted(j.counts.kept || 0); }
          }
          if (T.open) { draw(); }
          keepPolling();
        });
      })
      .catch(function () {
        if (seq !== T.seq) { return; }
        T.loading = false;
        T.error = 'Rouh could not be reached. Try again in a moment.';
        if (T.open) { draw(); }
      });
  }

  // The thought on its own page, read by itself, so one that is archived or
  // hidden by a search on the list is there all the same.
  function loadOne() {
    var want = T.focus;
    if (!want) { return Promise.resolve(); }
    var seq = ++T.oneSeq;
    return fetch('/api/thoughts/' + encodeURIComponent(want), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== T.oneSeq || T.focus !== want) { return; }
          if (!r.ok || !j || !j.thought) {
            T.one = null;
            T.oneError = (j && j.error) || 'This thought could not be read. Try again in a moment.';
          } else {
            T.one = j.thought;
            T.oneError = '';
          }
          if (T.open) { draw(); }
          keepPolling();
        });
      })
      .catch(function () {
        if (seq !== T.oneSeq) { return; }
        T.oneError = 'Rouh could not be reached. Try again in a moment.';
        if (T.open) { draw(); }
      });
  }

  function reread() {
    var all = [load()];
    if (T.focus) { all.push(loadOne()); }
    return Promise.all(all);
  }

  // While a thought on the screen is being enriched, it is read again now and
  // then: its run's end is told over the socket, and this is for the one
  // whose run ended without telling (`thought_enrich.settle`).
  function enriching(t) {
    var e = t && t.enriched;
    return !!(e && (e.state === 'starting' || e.state === 'running'));
  }
  function keepPolling() {
    clearTimeout(T.poll);
    var shown = T.focus ? [T.one] : ((T.data && T.data.thoughts) || []);
    if (!T.open || !shown.some(enriching)) { return; }
    T.poll = setTimeout(function () {
      if (T.open && !T.busy && !T.editing && !T.following) { reread(); } else { keepPolling(); }
    }, 60000);
  }

  // A write. The page is not drawn again until it is answered, so a form
  // being saved keeps what was typed in it, and keeps it if the save fails;
  // `button` says it is working meanwhile.
  function post(url, body, busy, done, button, working) {
    T.busy = busy;
    T.said = '';
    var was = button ? button.textContent : '';
    if (button) {
      button.disabled = true;
      if (working) { button.textContent = working; }
    }
    return fetch(url, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (j) {
          if (!r.ok || !j || !j.ok) {
            throw new Error((j && j.error) || 'That could not be saved. Try again in a moment.');
          }
          return j.thought;
        });
      })
      .then(function (t) {
        T.busy = '';
        if (done) { done(t); }
        return reread();
      })
      .catch(function (err) {
        T.busy = '';
        var why = String((err && err.message) || err);
        if (!button || !button.isConnected) {
          T.said = why;
          draw();
          return;
        }
        // Said beside the button, so whatever was typed stays as it was.
        button.disabled = false;
        button.textContent = was;
        var row = button.parentNode;
        var said = row.nextElementSibling;
        if (!said || !said.classList.contains('th-error')) {
          said = el('p', 'th-error');
          row.parentNode.insertBefore(said, row.nextSibling);
        }
        said.textContent = why;
      });
  }

  function keepNew(button) {
    var words = T.draft.trim();
    if (!words || T.busy) { return; }
    post('/api/thoughts/new', { words: words }, 'new', function (t) {
      T.draft = '';
      T.flash = String(t.id);
    }, button, 'Keeping…');
  }

  /* ---- its parts ---- */

  function chips(tags, cls) {
    var row = el('div', cls || 'th-tags');
    (tags || []).forEach(function (tag) {
      var b = button('th-tag' + (T.tag && T.tag.toLowerCase() === tag.toLowerCase() ? ' on' : ''), tag,
                     function () { pickTag(tag); }, 'Only the thoughts about ' + tag);
      row.appendChild(b);
    });
    return row;
  }

  function linkTo(id, title) {
    return button('th-link', title ? '“' + title + '”' : 'Thought ' + id,
                  function () { focusOn(String(id)); }, 'Go to thought ' + id);
  }

  function editForm(t) {
    var form = el('form', 'th-form');
    form.setAttribute('aria-label', 'Edit this thought');
    var title = el('input', 'th-in');
    title.type = 'text';
    title.value = t.title;
    title.maxLength = 120;
    title.setAttribute('aria-label', 'Title');
    var words = el('textarea', 'th-in th-words-in');
    words.value = t.words;
    words.rows = Math.min(14, Math.max(4, Math.ceil(t.words.length / 70) + 1));
    words.setAttribute('aria-label', 'Your words');
    var tags = el('input', 'th-in');
    tags.type = 'text';
    tags.value = (t.tags || []).join(', ');
    tags.placeholder = 'Topics, separated by commas';
    tags.setAttribute('aria-label', 'Topics');
    var l1 = el('label', 'th-field');
    l1.appendChild(el('span', 'th-lab', 'Title'));
    l1.appendChild(title);
    var l2 = el('label', 'th-field');
    l2.appendChild(el('span', 'th-lab', 'Your words'));
    l2.appendChild(words);
    var l3 = el('label', 'th-field');
    l3.appendChild(el('span', 'th-lab', 'Topics'));
    l3.appendChild(tags);
    form.appendChild(l1);
    form.appendChild(l2);
    form.appendChild(l3);
    var acts = el('div', 'th-acts');
    var save = el('button', 'ctl th-primary', 'Save');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('ctl', 'Cancel', function () { T.editing = ''; draw(); }));
    form.appendChild(acts);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      post('/api/thoughts/' + t.id, { title: title.value, words: words.value,
                                      tags: tags.value.split(',') }, 'edit', function () {
        T.editing = '';
        T.flash = String(t.id);
      }, save, 'Saving…');
    });
    form.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); T.editing = ''; draw(); }
    });
    setTimeout(function () { words.focus(); }, 0);
    return form;
  }

  function followForm(t) {
    var form = el('form', 'th-form th-follow-form');
    form.setAttribute('aria-label', 'Follow up this thought');
    var words = el('textarea', 'th-in th-words-in');
    words.rows = 3;
    words.placeholder = 'Where this thought has gone since, in your words';
    words.setAttribute('aria-label', 'Your follow-up');
    form.appendChild(words);
    var acts = el('div', 'th-acts');
    var save = el('button', 'ctl th-primary', 'Keep the follow-up');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('ctl', 'Cancel', function () { T.following = ''; draw(); }));
    form.appendChild(acts);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!words.value.trim()) { words.focus(); return; }
      post('/api/thoughts/new', { words: words.value, follows: t.id }, 'follow', function (made) {
        T.following = '';
        T.flash = String(made.id);
      }, save, 'Keeping…');
    });
    form.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); T.following = ''; draw(); }
    });
    setTimeout(function () { words.focus(); }, 0);
    return form;
  }

  /* ---- its enriched version ---- */

  function goTo(href) { if (host().go) { host().go(href); } }

  function taskLink(task) {
    if (!task || !task.folder) {
      return el('span', '', task && task.number != null ? 'task ' + task.number : 'a task of its own');
    }
    return button('th-link', 'task ' + task.number, function () { goTo('/task/' + task.folder); },
                  'Open task ' + task.number + ', “' + task.title + '”');
  }

  // Research it again, in its own task: a fresh run that writes a new
  // enriched version, the earlier one kept until it is made. Also the first
  // time, for a thought kept before thoughts were researched.
  function researchButton(t, label) {
    var e = t.enriched;
    var task = e && e.task && e.task.number != null ? e.task : null;
    return button('ctl small th-research', label, function (ev) {
      post('/api/thoughts/' + t.id + '/enrich', {}, 'enrich', null, ev.currentTarget, 'Starting…');
    }, label === 'Research it'
      ? 'Research this thought and make an enriched version of it, with a visual explainer'
      : 'Research it again from scratch' + (task ? ', in task ' + task.number : '') +
        '; the version it has now stays until the new one is ready');
  }

  function earlierButton(e) {
    return button('th-link th-enr-earlier', 'View the earlier version', function () { goTo(e.address); },
                  'The enriched version made before this one');
  }

  // Where the thought's enriched version stands: being made, ready to open,
  // or failed with why and a way to try again. On its own page (`big`) it is
  // a panel of its own; on the list, one line.
  function enrichedPart(t, big) {
    var e = t.enriched;
    if (!e) { return null; }
    var box = el(big ? 'section' : 'div', 'th-enr th-enr-' + e.state + (big ? ' th-enr-big' : ''));
    if (big) {
      box.setAttribute('aria-label', 'Enriched version');
      box.appendChild(el('h6', 'th-enr-h', 'Enriched version'));
    }
    var row = el('div', 'th-enr-row');
    box.appendChild(row);
    var task = e.task && e.task.number != null ? e.task : null;
    var note = el('span', 'th-enr-note');
    var acts = null;
    if (e.state === 'starting' || e.state === 'running') {
      var pill = el('span', 'th-enr-pill');
      pill.setAttribute('role', 'status');
      pill.appendChild(el('span', 'th-enr-dot'));
      pill.appendChild(document.createTextNode(e.address ? 'Researching again…' : 'Enriching…'));
      row.appendChild(pill);
      note.appendChild(document.createTextNode(e.state === 'starting' && !task
        ? 'Rouh is about to research it' : 'Rouh is researching it'));
      if (task) {
        note.appendChild(document.createTextNode(' in '));
        note.appendChild(taskLink(task));
      }
      if (big) {
        note.appendChild(document.createTextNode(e.address
          ? ', and is writing a new version. The one it has now stays until the new one is ready.'
          : ', and is writing an expanded version with a visual explainer. It opens from here when it is ready.'));
      }
      if (e.address) {
        row.appendChild(note);
        note = null;
        row.appendChild(earlierButton(e));
      }
    } else if (e.state === 'done') {
      row.appendChild(button('ctl small th-enr-open', 'View enriched version', function () { goTo(e.address); },
                             'The research, the expanded write-up and its visual explainer'));
      if (big) {
        note.appendChild(document.createTextNode('Researched and expanded, with a visual explainer' +
          (e.done_at ? ', ' + when(e.done_at) : '') + (task ? ', in ' : '.')));
      } else if (task) {
        note.appendChild(document.createTextNode('In '));
      }
      if (task) {
        note.appendChild(taskLink(task));
        if (big) { note.appendChild(document.createTextNode('.')); }
      }
      row.appendChild(note);
      note = null;
      if (big) {
        acts = el('div', 'th-acts');
        acts.appendChild(researchButton(t, 'Research again'));
      } else {
        row.appendChild(researchButton(t, 'Research again'));
      }
    } else if (e.state === 'failed') {
      row.appendChild(el('span', 'th-enr-pill th-enr-bad', e.address ? 'Researching again failed' : 'Enrichment failed'));
      note.appendChild(document.createTextNode(e.why || 'It did not finish.'));
      row.appendChild(note);
      note = null;
      acts = el('div', 'th-acts');
      acts.appendChild(researchButton(t, 'Try again'));
      if (e.address) { acts.appendChild(earlierButton(e)); }
    }
    if (note && note.childNodes.length) { row.appendChild(note); }
    if (acts) { box.appendChild(acts); }
    return box;
  }

  /* ---- one thought ---- */

  function card(t, big) {
    var id = String(t.id);
    var li = el('li', 'th-card' + (t.status === 'developed' ? ' is-developed' : '') +
                       (t.status === 'archived' ? ' is-archived' : '') +
                       (big ? ' th-card-big' : '') + (!big && T.flash === id ? ' th-flash' : ''));
    li.id = 'thought-' + id;
    li.setAttribute('data-thought', id);
    var head = el('div', 'th-head');
    var h = el('h5', 'th-title');
    if (big) {
      h.textContent = t.title;
    } else {
      // The title opens the thought on its own page, as its number does.
      var open = el('a', 'th-title-a', t.title);
      open.href = '/thoughts/' + id;
      open.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
        e.preventDefault();
        focusOn(id);
      });
      h.appendChild(open);
    }
    head.appendChild(h);
    var num = el('a', 'th-num', '#' + id);
    num.href = '/thoughts/' + id;
    num.title = 'This thought’s own page';
    num.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
      e.preventDefault();
      focusOn(id);
    });
    head.appendChild(num);
    li.appendChild(head);

    var meta = el('div', 'th-meta');
    meta.appendChild(el('span', 'th-src th-src-' + t.source, t.source_said));
    meta.appendChild(el('span', 'th-when', when(t.said_at)));
    if (t.chat) {
      var chat = button('th-link th-chat', 'In the chat', function () {
        if (host().go) { host().go('/chat/' + encodeURIComponent(t.chat)); }
      }, 'Open the conversation it was said in');
      meta.appendChild(chat);
    }
    if (t.status !== 'open') {
      meta.appendChild(el('span', 'th-status th-status-' + t.status,
                          t.status === 'developed' ? 'Developed' : 'Archived'));
    }
    li.appendChild(meta);

    if (t.follows) {
      var up = el('div', 'th-line');
      up.appendChild(el('span', 'th-line-lab', 'Follows'));
      up.appendChild(linkTo(t.follows.id, t.follows.title));
      li.appendChild(up);
    }

    if (T.editing === id) {
      li.appendChild(editForm(t));
    } else {
      li.appendChild(el('p', 'th-words', t.words));
      if ((t.tags || []).length) { li.appendChild(chips(t.tags)); }
      var enr = enrichedPart(t, big);
      if (enr) { li.appendChild(enr); }
    }

    if ((t.followed_by || []).length) {
      var down = el('div', 'th-line');
      down.appendChild(el('span', 'th-line-lab', 'Followed up'));
      t.followed_by.forEach(function (f) { down.appendChild(linkTo(f.id, f.title)); });
      li.appendChild(down);
    }

    if (T.editing !== id) {
      var acts = el('div', 'th-acts');
      if (t.status !== 'archived') {
        acts.appendChild(button('ctl small', 'Follow up', function () {
          T.following = T.following === id ? '' : id;
          T.editing = '';
          draw();
        }, 'Add a later thought to this line of thinking'));
      }
      if (!t.enriched && t.status !== 'archived') { acts.appendChild(researchButton(t, 'Research it')); }
      acts.appendChild(button('ctl small', 'Edit', function () {
        T.editing = id;
        T.following = '';
        draw();
      }, 'Change its title, words or topics'));
      if (t.status === 'open') {
        acts.appendChild(button('ctl small', 'Mark developed', function (e) {
          post('/api/thoughts/' + id, { status: 'developed' }, 'status', null, e.currentTarget);
        }, 'You have taken this thought further'));
      } else if (t.status === 'developed') {
        acts.appendChild(button('ctl small', 'Mark open', function (e) {
          post('/api/thoughts/' + id, { status: 'open' }, 'status', null, e.currentTarget);
        }, 'Still being thought about'));
      }
      acts.appendChild(button('ctl small th-archive', t.status === 'archived' ? 'Bring back' : 'Archive',
        function (e) {
          post('/api/thoughts/' + id + '/archive', { back: t.status === 'archived' }, 'archive', null,
               e.currentTarget);
        }, t.status === 'archived' ? 'Put it back with your kept thoughts' : 'Put it away; it stays findable under Archived'));
      li.appendChild(acts);
    }
    if (T.following === id) { li.appendChild(followForm(t)); }
    return li;
  }

  /* ---- the page ---- */

  function composer() {
    var form = el('form', 'th-new');
    form.setAttribute('aria-label', 'A new thought');
    var box = el('textarea', 'th-in th-new-in');
    box.rows = 2;
    box.placeholder = 'A thought, in your words';
    box.setAttribute('aria-label', 'A new thought');
    box.value = T.draft;
    box.addEventListener('input', function () { T.draft = box.value; keep.disabled = !box.value.trim(); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); keepNew(keep); }
    });
    form.appendChild(box);
    var keep = el('button', 'ctl th-primary', 'Keep it');
    keep.type = 'submit';
    keep.disabled = !T.draft.trim();
    keep.title = 'Keep it (Ctrl+Enter)';
    form.appendChild(keep);
    form.addEventListener('submit', function (e) { e.preventDefault(); keepNew(keep); });
    return form;
  }

  function finder(d) {
    var bar = el('div', 'th-bar');
    var search = el('input', 'th-in th-search');
    search.type = 'search';
    search.placeholder = 'Search your thoughts';
    search.setAttribute('aria-label', 'Search your thoughts');
    search.value = T.q;
    search.addEventListener('input', function () {
      T.q = search.value;
      clearTimeout(T.searchTimer);
      T.searchTimer = setTimeout(function () { load().then(function () { refocus(); }); }, 250);
    });
    bar.appendChild(search);
    var which = el('div', 'th-which');
    which.setAttribute('role', 'group');
    which.setAttribute('aria-label', 'Which thoughts');
    var c = (d && d.counts) || { kept: 0, archived: 0 };
    [[false, 'Kept', c.kept], [true, 'Archived', c.archived]].forEach(function (w) {
      var b = button('th-pick' + (T.archived === w[0] ? ' on' : ''), w[1] + (w[2] ? ' ' + w[2] : ''),
                     function () {
                       if (T.archived === w[0]) { return; }
                       T.archived = w[0];
                       T.data = null;
                       load();
                     });
      b.setAttribute('aria-pressed', T.archived === w[0] ? 'true' : 'false');
      which.appendChild(b);
    });
    bar.appendChild(which);
    return bar;
  }

  function topics(d) {
    var tags = (d && d.tags) || [];
    if (!tags.length) { return null; }
    var row = el('div', 'th-topics');
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', 'Topics');
    var all = button('th-tag' + (T.tag ? '' : ' on'), 'All topics', function () { pickTag(''); });
    row.appendChild(all);
    tags.forEach(function (t) {
      var b = button('th-tag' + (T.tag.toLowerCase() === t.tag.toLowerCase() ? ' on' : ''), t.tag,
                     function () { pickTag(t.tag); }, counted(t.count, 'thought', 'thoughts'));
      b.appendChild(el('span', 'th-tag-n', String(t.count)));
      row.appendChild(b);
    });
    return row;
  }

  // The search box keeps its place and its caret while the page is drawn again under it.
  function refocus() {
    var s = document.querySelector('#thoughtsBody .th-search');
    if (s && document.activeElement !== s && T.refocus) {
      s.focus();
      s.setSelectionRange(s.value.length, s.value.length);
    }
    T.refocus = false;
  }

  function draw() {
    var body = $('thoughtsBody');
    var meta = $('thoughtsMeta');
    if (!body) { return; }
    var active = document.activeElement;
    T.refocus = !!(active && active.classList && active.classList.contains('th-search') && body.contains(active));
    var scroll = body.scrollTop;
    body.setAttribute('aria-busy', T.loading ? 'true' : 'false');
    body.textContent = '';
    var d = T.data;
    var page = el('div', 'th-page');
    body.appendChild(page);
    if (meta) {
      var c = d && d.counts;
      meta.textContent = c ? counted(c.kept, 'thought', 'thoughts') + ' kept' +
        (c.developed ? ', ' + c.developed + ' developed' : '') : '';
    }
    if (T.focus) {
      drawOne(page);
      body.scrollTop = scroll;
      return;
    }
    if (!T.archived) { page.appendChild(composer()); }
    page.appendChild(finder(d));
    var tops = topics(d);
    if (tops) { page.appendChild(tops); }
    if (T.said) { page.appendChild(el('p', 'th-error', T.said)); }
    if (T.error) { page.appendChild(el('p', 'th-error', T.error)); }
    if (!d) {
      if (T.loading) { page.appendChild(el('p', 'th-loading', 'Reading your thoughts…')); }
      body.scrollTop = scroll;
      refocus();
      return;
    }
    var list = d.thoughts || [];
    if (!list.length) {
      var none = el('div', 'th-empty');
      if (T.q || T.tag) {
        none.appendChild(el('p', 'th-empty-h', 'No thought matches' +
          (T.q ? ' “' + T.q + '”' : '') + (T.tag ? ' in ' + T.tag : '') + '.'));
        none.appendChild(button('ctl small', 'Show them all', function () {
          T.q = '';
          T.tag = '';
          load();
        }));
      } else if (T.archived) {
        none.appendChild(el('p', 'th-empty-h', 'Nothing archived.'));
      } else {
        none.appendChild(el('p', 'th-empty-h', 'No thoughts kept yet.'));
        none.appendChild(el('p', 'th-empty-p', 'Say “remember this thought” to Rouh, start a message ' +
          'with “thought:” here or on Telegram, or write one above. Each is kept in your words, ' +
          'with when and how it came.'));
      }
      page.appendChild(none);
      body.scrollTop = scroll;
      refocus();
      return;
    }
    var month = '';
    var ul = null;
    list.forEach(function (t) {
      var m = monthOf(t.said_at);
      if (m !== month) {
        month = m;
        var sec = el('section', 'th-month');
        var n = list.filter(function (x) { return monthOf(x.said_at) === m; }).length;
        var h = el('h4', 'th-h');
        h.appendChild(el('span', '', monthSaid(t.said_at)));
        h.appendChild(el('span', 'th-n', String(n)));
        sec.appendChild(h);
        ul = el('ul', 'th-list');
        sec.appendChild(ul);
        page.appendChild(sec);
      }
      ul.appendChild(card(t));
    });
    body.scrollTop = scroll;
    refocus();
  }

  // One thought on its own page: the whole of it, its enriched version as a
  // panel of its own, and the way back to the rest.
  function drawOne(page) {
    var bar = el('div', 'th-one-bar');
    bar.appendChild(button('ctl small th-back', '‹ All thoughts', function () { focusOn(''); },
                           'Back to every thought'));
    page.appendChild(bar);
    if (T.said) { page.appendChild(el('p', 'th-error', T.said)); }
    var t = T.one;
    if (!t || String(t.id) !== T.focus) {
      page.appendChild(el('p', T.oneError ? 'th-error' : 'th-loading', T.oneError || 'Reading the thought…'));
      return;
    }
    if (T.oneError) { page.appendChild(el('p', 'th-error', T.oneError)); }
    var ul = el('ul', 'th-list th-one');
    ul.appendChild(card(t, true));
    page.appendChild(ul);
  }

  /* ---- focus ---- */

  function pickTag(tag) {
    T.tag = tag && T.tag.toLowerCase() === tag.toLowerCase() ? '' : (tag || '');
    load();
  }

  function focusOn(id) {
    if (host().focus) { host().focus(id); } else { shown(id); }
  }

  function shown(id) {
    var was = T.open;
    var want = id ? String(id) : '';
    var moved = want !== T.focus;
    T.open = true;
    T.focus = want;
    if (moved) {
      T.editing = '';
      T.following = '';
      T.said = '';
    }
    if (T.focus) {
      T.flash = '';
      if (moved || !T.one) {
        T.one = null;
        T.oneError = '';
      }
      draw();
      loadOne();
      if (!T.data && !T.loading) { load(); }
      return;
    }
    if (!T.data && !T.loading) { load(); return; }
    draw();
    if (!was) { load(); }
  }
  function hidden() {
    T.open = false;
    T.editing = '';
    T.following = '';
    clearTimeout(T.poll);
  }
  // A thought kept or changed elsewhere: read again, keeping what is half written.
  function moved() {
    if (T.open && !T.busy && !T.editing && !T.following) { reread(); }
  }
  // One just kept in the conversation, while the page is up: drawn lit at the top.
  function flash(id) {
    T.flash = id ? String(id) : '';
    if (T.open) { load(); }
  }
  // Rouh asked to show the thoughts found by these words, or this topic.
  function find(q, tag) {
    T.q = q || '';
    T.tag = tag || '';
    T.archived = false;
    load();
  }

  window.RouhThoughts = { shown: shown, hidden: hidden, moved: moved, flash: flash, find: find,
                          reload: function () { return load(); } };

  var x = $('thoughtsClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
