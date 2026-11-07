/* A task's icon, and the picker a press on it opens (`rouh/taskicons.py`).

   Petar, 22 October 2026 (fr_0ac90fe38f73): "I should be able to click it and
   change it, just like in notion. it should be possible to put an image
   upload, small icon instead of emoji." Put into the task browser and into a
   task's or a step's own page, ahead of their own scripts, so the icon and
   its picker are one component wherever a task's title is drawn
   (`objectindex.icon_mark` draws the same mark on a task's page).

   The picker is Notion's: a search over every emoji and the words each is
   found by, the emoji in their groups with a bar to go to each, and Upload an image, which makes the picture 128 pixels square here before
   it goes up. What is picked goes up to Rouh as `rouh-page-task`, act `icon`,
   and Rouh writes it (`taskIconAct` in app.js). Every mark of that task on
   the page shows the new icon the moment Rouh says it is kept. */
(function () {
  'use strict';

  var ASK = 'rouh-page-task', BACK = 'rouh-frame-project';
  var SIDE = 128;
  var seq = 0, asked = {};

  /* Every emoji, in Unicode's groups, and the words each is found by: its name,
     CLDR's keywords in English and Bulgarian, and about forty associations
     brainstormed for it (`rouh/static/emoji.json`, made by tools/emoji/build.py).
     Petar, 22 October 2026 (fr_288afd00eb77): "if I type red I don't get the red
     pin. and in osx I do." The page cannot fetch, so Rouh is asked for the list
     once, the first time the picker opens (`emojiList` in cards.js). */
  var EMOJI = null, asking = false;

  /* The mark of each group in the bar along the bottom, which goes to it. */
  var MARKS = {
    'For tasks': '\u{1F4CC}', 'Smileys & Emotion': '\u{1F600}', 'People & Body': '\u{1F44B}',
    'Animals & Nature': '\u{1F43B}', 'Food & Drink': '\u{1F354}', 'Travel & Places': '\u{2708}\uFE0F',
    'Activities': '\u{26BD}', 'Objects': '\u{1F4A1}', 'Symbols': '\u{2764}\uFE0F', 'Flags': '\u{1F3F3}\uFE0F'
  };

  /* The list as Rouh sent it, made ready to search: each emoji with its name
     and its words, lower case, split once rather than at every key. */
  function ready(data) {
    var list = (data && data.emoji) || [], groups = (data && data.groups) || [], flags = {};
    /* A flag found by one of its own words counts half: "red" is in the
       stripes of seventy flags, and is far more often the pin or the heart.
       By its name ("bulgaria") it counts whole. */
    groups.forEach(function (g) {
      if (g[0] === 'Flags') { g[1].forEach(function (at) { flags[at] = true; }); }
    });
    EMOJI = {
      all: list.map(function (x, i) {
        var name = String(x[1] || '').toLowerCase();
        return {
          e: x[0], name: x[1] || '', at: i, n: name, nw: name.split(/[^\p{L}\p{N}'’]+/u).filter(Boolean),
          tw: (String(x[2] || '') + ' ' + String(x[3] || '')).split(' ').filter(Boolean),
          weak: flags[i] ? 0.5 : 1
        };
      }),
      groups: groups
    };
  }

  function loadEmoji() {
    if (EMOJI || asking) { return; }
    asking = true;
    send({ act: 'emoji' }, [], function (m) {
      asking = false;
      if (!m.ok || !m.emoji) { say(m.error || 'The emoji could not be loaded.'); return; }
      ready(m.emoji);
      var q = pop && pop.querySelector('.tip-q');
      if (q) { show(q.value); }
    });
  }

  /* How well one emoji answers what was typed, 0 for not at all. Every word
     typed has to be found: as a word of its name or of its own words, or at
     the start of one ("re" finds red), or for three letters or more anywhere
     in its name ("pin" finds the pushpin). Not inside its own words, where
     "happy" would find every unhappy face. A whole word counts before the start of one, a word of its name
     before its own words, and those in the order they were brainstormed, the
     likeliest first; a short name before a long one. */
  function score(x, q, words) {
    if (x.e === q || x.e.replace(/\uFE0F/g, '') === q.replace(/\uFE0F/g, '')) { return 5000; }
    var s = x.n === q ? 1000 : Math.max(0, 40 - 10 * x.nw.length);
    for (var i = 0; i < words.length; i++) {
      var w = words[i], best = 0, j, t, near;
      for (j = 0; j < x.nw.length; j++) {
        t = x.nw[j];
        if (t === w) { best = Math.max(best, 300); }
        else if (t.indexOf(w) === 0) { best = Math.max(best, 120); }
        else if (w.length > 2 && t.indexOf(w) > 0) { best = Math.max(best, 20); }
      }
      for (j = 0; j < x.tw.length && best < 200; j++) {
        t = x.tw[j];
        near = Math.min(j, 40);
        if (t === w) { best = Math.max(best, (200 - 2 * near) * x.weak); }
        else if (t.indexOf(w) === 0) { best = Math.max(best, (100 - near) * x.weak); }
      }
      if (!best) { return 0; }
      s += best;
    }
    return s;
  }

  function cell(x) {
    return '<button type="button" class="tip-emoji" data-emoji="' + esc(x.e) + '" title="' + esc(x.name) +
      '" aria-label="' + esc(x.name) + '">' + esc(x.e) + '</button>';
  }

  /* Every emoji in its group, or what was typed, best first. */
  function grid(q) {
    if (!EMOJI) { return '<p class="tip-none">Loading the emoji\u2026</p>'; }
    q = String(q || '').trim().toLowerCase();
    if (!q) {
      return EMOJI.groups.map(function (g, i) {
        return '<div class="tip-group" id="tip-g' + i + '">' + esc(g[0]) + '</div><div class="tip-grid">' +
          g[1].map(function (at) { return EMOJI.all[at] ? cell(EMOJI.all[at]) : ''; }).join('') + '</div>';
      }).join('');
    }
    var words = q.split(/\s+/).filter(Boolean), found = [];
    EMOJI.all.forEach(function (x) {
      var s = score(x, q, words);
      if (s) { found.push([s, x]); }
    });
    found.sort(function (a, b) { return b[0] - a[0] || a[1].at - b[1].at; });
    if (!found.length) {
      return '<p class="tip-none">No emoji for that. Type or paste any emoji and press Enter.</p>';
    }
    return '<div class="tip-grid">' + found.slice(0, 400).map(function (f) { return cell(f[1]); }).join('') +
      '</div>';
  }

  /* The bar of groups along the bottom: one press goes to that group. */
  function bar() {
    if (!EMOJI) { return ''; }
    return EMOJI.groups.map(function (g, i) {
      return '<button type="button" class="tip-jump" data-group="' + i + '" title="' + esc(g[0]) +
        '" aria-label="' + esc(g[0]) + '">' + esc(MARKS[g[0]] || g[0].charAt(0)) + '</button>';
    }).join('');
  }

  function show(typed) {
    if (!pop) { return; }
    var list = pop.querySelector('.tip-list'), jumps = pop.querySelector('.tip-bar');
    list.innerHTML = grid(typed);
    list.scrollTop = 0;
    jumps.innerHTML = bar();
    jumps.hidden = !EMOJI || !!String(typed || '').trim();
  }

  var pop = null, openFor = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* The face of a mark: the picture, or the emoji. */
  function face(icon, img) {
    return img ? '<img src="' + esc(img) + '" alt="">' : esc(icon || '');
  }

  /* A task's icon in front of its title. `id` empty is a mark that cannot be
     changed (a folder with no row). */
  function mark(o, cls) {
    var icon = o && o.icon, img = o && o.img, id = o && o.id;
    if (!icon && !img) { return ''; }
    if (!id || !reachable()) {
      return '<span class="ticon ' + (cls || '') + '" aria-hidden="true">' + face(icon, img) + '</span>';
    }
    var title = o.title || o.name || '';
    return '<span class="ticon ' + (cls || '') + '" role="button" tabindex="0" data-task="' + esc(id) +
      '" data-title="' + esc(title) + '" aria-label="' + esc('Change the icon of ' + title) + '">' +
      face(icon, img) + '</span>';
  }

  function reachable() {
    var up;
    try { up = window.parent; } catch (err) { up = null; }
    return !!up && up !== window;
  }

  function send(said, moving, done) {
    var id = 'ti' + (++seq);
    asked[id] = done;
    said.type = ASK;
    said.id = id;
    try { window.parent.postMessage(said, '*', moving || []); }
    catch (err) { delete asked[id]; done({ ok: false, error: 'Rouh could not be reached.' }); }
  }
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== BACK || !asked[m.id]) { return; }
    var done = asked[m.id];
    delete asked[m.id];
    done(m);
  });

  /* Every mark of this task on the page, showing what Rouh kept. */
  var heard = [];
  function kept(task, shown) {
    var marks = document.querySelectorAll('.ticon[data-task]');
    for (var i = 0; i < marks.length; i++) {
      if (marks[i].getAttribute('data-task') === task) { marks[i].innerHTML = face(shown.icon, shown.img); }
    }
    heard.forEach(function (tell) { try { tell(task, shown); } catch (err) { /* the mark is right */ } });
  }

  function say(words) {
    var line = pop && pop.querySelector('.tip-said');
    if (line) { line.textContent = words || ''; line.hidden = !words; }
  }

  function pickEmoji(task, emoji) {
    say('');
    send({ act: 'icon', task: task, icon: emoji }, [], function (m) {
      if (!m.ok || !m.shown) { say(m.error || 'The icon was not changed.'); return; }
      kept(task, m.shown);
      close();
    });
  }

  /* The picture chosen, as a square PNG 128 pixels a side, cut from its middle. */
  function squared(file, done) {
    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onload = function () {
      URL.revokeObjectURL(url);
      var w = img.naturalWidth, h = img.naturalHeight, s = Math.min(w, h);
      if (!s) { done(null); return; }
      var side = Math.min(SIDE, s);
      var c = document.createElement('canvas');
      c.width = side; c.height = side;
      c.getContext('2d').drawImage(img, (w - s) / 2, (h - s) / 2, s, s, 0, 0, side, side);
      c.toBlob(function (blob) {
        if (!blob) { done(null); return; }
        blob.arrayBuffer().then(done, function () { done(null); });
      }, 'image/png');
    };
    img.onerror = function () { URL.revokeObjectURL(url); done(null); };
    img.src = url;
  }

  function upload(task, file) {
    if (!file) { return; }
    say('Uploading\u2026');
    squared(file, function (bytes) {
      if (!bytes) { say('That file is not a picture this browser can read.'); return; }
      send({ act: 'icon', task: task, bytes: bytes, name: 'icon.png', media_type: 'image/png' }, [bytes],
        function (m) {
          if (!m.ok || !m.shown) { say(m.error || 'The picture was not kept.'); return; }
          kept(task, m.shown);
          close();
        });
    });
  }

  function close() {
    if (!pop) { return; }
    pop.remove();
    pop = null;
    var back = openFor;
    openFor = null;
    if (back && back.isConnected) { back.focus({ preventScroll: true }); }
  }

  function place(anchor) {
    var r = anchor.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    if (vw < 560) { pop.classList.add('sheet'); return; }
    pop.style.height = '';
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.max(8, Math.min(r.left, vw - w - 8));
    /* Below the icon, or above it, whichever it fits; where it fits neither,
       on the roomier side, made as short as that side, so its bar of groups
       is never cut off at the frame's foot. */
    var below = vh - r.bottom - 14, above = r.top - 14, top;
    if (h <= below) { top = r.bottom + 6; }
    else if (h <= above) { top = r.top - h - 6; }
    else if (Math.max(below, above) >= 240) {
      h = Math.max(below, above);
      pop.style.height = h + 'px';
      top = below >= above ? r.bottom + 6 : r.top - h - 6;
    } else { top = vh - h - 8; }
    pop.style.left = left + 'px';
    pop.style.top = Math.max(8, top) + 'px';
  }

  function open(anchor) {
    var task = anchor.getAttribute('data-task');
    if (!task) { return; }
    if (openFor === anchor) { close(); return; }
    close();
    openFor = anchor;
    pop = document.createElement('div');
    pop.className = 'ticon-pick';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Icon of ' + (anchor.getAttribute('data-title') || 'this task'));
    pop.innerHTML =
      '<div class="tip-top"><input type="search" class="tip-q" placeholder="Search or paste an emoji" ' +
      'aria-label="Search the emoji" autocomplete="off">' +
      '<button type="button" class="tip-up">Upload an image</button>' +
      '<input type="file" class="tip-file" accept="image/png,image/jpeg,image/gif,image/webp" hidden></div>' +
      '<p class="tip-said" role="status" hidden></p>' +
      '<div class="tip-list"></div><div class="tip-bar" hidden></div>';
    document.body.appendChild(pop);
    show('');
    place(anchor);
    loadEmoji();
    var q = pop.querySelector('.tip-q'), list = pop.querySelector('.tip-list');
    var file = pop.querySelector('.tip-file');
    q.addEventListener('input', function () { show(q.value); });
    pop.querySelector('.tip-bar').addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('.tip-jump');
      var head = b && list.querySelector('#tip-g' + b.getAttribute('data-group'));
      if (head) { list.scrollTop = head.offsetTop; }
    });
    q.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        var first = list.querySelector('.tip-emoji');
        var typed = q.value.trim();
        if (typed && !/^[\p{L}\p{N}\s]+$/u.test(typed)) { pickEmoji(task, typed); }
        else if (first) { pickEmoji(task, first.getAttribute('data-emoji')); }
      }
    });
    pop.querySelector('.tip-up').addEventListener('click', function () { file.click(); });
    file.addEventListener('change', function () { upload(task, file.files && file.files[0]); });
    list.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('.tip-emoji');
      if (b) { pickEmoji(task, b.getAttribute('data-emoji')); }
    });
    if (window.matchMedia('(pointer: fine)').matches) { q.focus({ preventScroll: true }); }
  }

  /* A press on a mark, caught before the link it sits in opens the task. */
  function pressed(e) {
    if (!reachable()) { return; }
    var t = e.target;
    if (pop && t.closest && !t.closest('.ticon-pick') && !t.closest('.ticon[data-task]')) {
      close();
      return;
    }
    var m = t.closest && t.closest('.ticon[data-task]');
    if (!m) { return; }
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'click') { open(m); }
  }
  document.addEventListener('click', pressed, true);
  document.addEventListener('mousedown', function (e) {
    var t = e.target;
    if (t.closest && t.closest('.ticon[data-task]')) { e.stopPropagation(); }
  }, true);
  document.addEventListener('dragstart', function (e) {
    var t = e.target;
    if (t.closest && t.closest('.ticon[data-task]')) { e.preventDefault(); }
  }, true);
  document.addEventListener('keydown', function (e) {
    if (pop && e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    var m = e.target && e.target.closest && e.target.closest('.ticon[data-task]');
    if (m && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      e.stopPropagation();
      open(m);
    }
  }, true);
  window.addEventListener('resize', function () { if (openFor && pop) { place(openFor); } });

  window.RouhTaskIcon = {
    mark: mark,
    /* Told whenever a task's icon is kept: (task id, {icon, img}). */
    onKept: function (tell) { heard.push(tell); }
  };
})();
