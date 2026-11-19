// A Live page space (task 189, Rouh Link): one fully custom HTML page that several Rouhs and their
// people work on live, like Figma. The screen only ever asks its own Rouh (/api/link/spaces/<id>...),
// with the same long poll as a live space (`link/space.js`, whose patterns this keeps); the poll
// carries `hv=`, so a page that did not change is not sent again.
//
// The page is drawn in a sealed frame: `<iframe sandbox="allow-scripts">` from srcdoc, never with
// the same origin, with a policy that allows no network, and with `link/frame-bridge.js` in it before
// the page's own source. What the frame says comes back only by postMessage, is taken only from the
// frame this screen made, only in its exact shapes, and is a hint for this screen's own drawing:
// where the person's pointer is (their presence), where they scrolled, and in comment mode a spot
// picked for a comment, which opens a box the person still has to type into and press Pin. Nothing
// the page sends changes the space or asks a Rouh. Each redraw loads a new frame hidden, which puts
// the viewer's scroll back first, then takes the old one's place.
//
// What is drawn besides: who is here (people round, Rouhs square, the partner's Rouh amber; press one
// to follow it), the live line, each member's marker on the element it is on, claims and numbered
// comment pins in the page, the source (tinted by who wrote it) with Edit source, the person's own
// Rouh (ask, intent with Stop, live steps, Skip to the end), comments with Resolve, the people and
// Rouhs here (Undo its edits), claimed parts, invite, the version in the task (Bring this version
// into the task, Put back what was there, the asks to keep it), history (the page as it was, Bring
// back this version), the log and Leave.
//
// Live cursors (step 189-09, `link/cursors.js`): the person's pointer, taps and selection go to their
// own Rouh, which shares them live with the others unless "Show my cursor to others" is off; the
// others' are drawn in the frame (an arrow with a name, a tap ring, a tinted band over selected words)
// and over the source. Each person gets one of the people's colours, never a Rouh's amber or turquoise.
(function () {
  'use strict';

  var SID = (document.body.getAttribute('data-space') || '').trim();
  var API = window.LINK_API || {
    get: function (path) { return fetch(path, { credentials: 'same-origin' }).then(answer); },
    post: function (path, body) {
      return fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) }).then(answer);
    }
  };
  function answer(r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok) { var e = new Error(j.error || ('The Rouh answered ' + r.status)); e.status = r.status; throw e; }
      return j;
    });
  }
  var base = '/api/link/spaces/' + encodeURIComponent(SID);

  var TAG = 'live-page-1';
  var MOST = 2000000;
  var POLICY = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; " +
    "media-src data: blob:; connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; " +
    "form-action 'none'; base-uri 'none'; object-src 'none'; manifest-src 'none'";
  var ID = /^[A-Za-z0-9_-]{1,40}$/;
  var SLOTS = ['accent', 'partner', 'third', 'fourth', 'dim'];

  var S = null;              // the last state from this Rouh
  var version = -1;
  var myPart = '';
  var following = '';
  var revealed = '';
  var historyOpen = false;
  var colours = {};          // actor label -> colour slot
  var page = { text: '', v: -1, by: [], size: 0 };   // the page as it stands, kept between polls (hv=)
  var past = null;           // {seq, text, by} while the history slider shows an earlier version
  var view = '';             // page | both | source
  var commenting = false;
  var editing = null;        // {base, start} while the person edits the source
  var picked = '';           // the spot a comment is being written for
  var bridge = null;         // the bridge's text, once
  var frame = null, pending = null, drawnKey = '', drawAgain = false, serial = 0;
  var scroll = { x: 0, y: 0 };
  var sentMarks = '';
  var cur = null;            // the live cursors (link/cursors.js)
  var others = [], othersAt = 0;   // the others' cursors as they last came, and when
  var personColours = {};    // person label -> 1..4, the --person-N colour
  // Where this screen itself last saw the pointer, outside the frame. The frame is sealed in a process
  // of its own, so this screen hears nothing while the pointer is over it: a point from the frame is
  // believed only while this screen hears nothing (`inFrame`), and only if the pointer was last seen
  // here at the frame's edge, so the page's own script cannot move the person's arrow while they
  // point somewhere else on Rouh's screen.
  var lastOut = null;        // {x, y, t} of the last pointer move this screen saw, outside the frame
  var touchedAt = 0;         // the last tap the frame said
  var mySel = '';            // where the person's own selection last was: 'el', 'src' or ''
  var sentCursors = '';
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
  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); return node; }
  function uid() { return Math.random().toString(36).slice(2, 12) + Date.now().toString(36).slice(-6); }
  function labelOf(actor) { return String(actor || '').split(':').slice(1).join(':'); }
  function isRouh(actor) { return String(actor || '').indexOf('rouh:') === 0; }
  function slot(label) {
    if (!S) return 4;
    if (label === S.me.label) return 0;
    if (colours[label] == null) {
      var n = Object.keys(colours).length + 1;
      colours[label] = Math.min(n, 4);
    }
    return colours[label];
  }
  function memberName(label) {
    var m = (S.space.members || []).filter(function (x) { return x.label === label; })[0];
    return m && m.name ? m.name : label;
  }
  function shortName(label) { return memberName(label).split(' ·')[0]; }
  function actorWords(actor) {
    var label = labelOf(actor);
    if (S && label === S.me.label) return isRouh(actor) ? 'Your Rouh' : 'You';
    return isRouh(actor) ? shortName(label) + "'s Rouh" : shortName(label) + "'s person";
  }
  function initials(actor) {
    var n = memberName(labelOf(actor)).replace(/·.*/, '').trim().split(/\s+/);
    return ((n[0] || '?')[0] + ((n[1] || '')[0] || '')).toUpperCase();
  }
  function tag(actor) {
    return el('span', { class: 'tag c-' + slot(labelOf(actor)) + (isRouh(actor) ? ' rouh' : '') },
      [el('span', { class: 'glyph', 'aria-hidden': 'true' }), actorWords(actor)]);
  }
  // A member's colour as the frame takes it: a plain hex value read from this theme's tokens.
  function hexOf(label) {
    var v = getComputedStyle(document.documentElement).getPropertyValue('--' + SLOTS[slot(label)]).trim();
    return /^#[0-9a-fA-F]{3,8}$/.test(v) ? v : '#a3b1b6';
  }
  function toast(words, undo) {
    var t = $('toast');
    clear(t).appendChild(el('span', { text: words }));
    if (undo) t.appendChild(el('button', { class: 'quiet', text: 'Undo', onclick: function () { t.hidden = true; undo(); } }));
    t.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { t.hidden = true; }, 6000);
  }
  function fail(e) { toast(e && e.message ? e.message : 'That did not work.'); }
  function svg(paths) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.6'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
    paths.forEach(function (d) { var p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', d); s.appendChild(p); });
    return s;
  }

  // --- who may do what ----------------------------------------------------------------------------

  function live() { return S && S.space.joined && S.space.state === 'live'; }
  function canEdit() { return live() && ['owner', 'editor'].indexOf(S.me.role) >= 0; }
  function canComment() { return live() && ['owner', 'editor', 'commenter'].indexOf(S.me.role) >= 0; }

  // --- talking to this Rouh -----------------------------------------------------------------------

  function op(kind, fields) {
    var o = { id: uid(), kind: kind, actor: S.me.person, at: Date.now() / 1000 };
    Object.keys(fields || {}).forEach(function (k) { o[k] = fields[k]; });
    return o;
  }
  function send(ops) {
    return API.post(base + '/ops', { ops: ops }).then(function (got) {
      (got.refused || []).forEach(function (r) { toast(r.why); });
      return got;
    }).catch(fail);
  }
  function act(what, more) {
    var body = { act: what };
    Object.keys(more || {}).forEach(function (k) { body[k] = more[k]; });
    return API.post(base + '/act', body);
  }
  function query(wait, since) {
    return '?since=' + since + '&wait=' + wait + '&part=' + encodeURIComponent(myPart) + '&follow=' + encodeURIComponent(following) +
      (page.v >= 0 ? '&hv=' + page.v : '');
  }

  // The page's source is left out of a poll when it has not changed since `hv`: keep the copy here.
  function take(st) {
    var h = st.doc && st.doc.html;
    if (h) {
      if (h.same) { h.text = page.text; if (!h.by) h.by = page.by; }
      else page = { text: String(h.text || ''), v: h.v, by: h.by || [], size: h.size || String(h.text || '').length };
      page.size = h.size != null ? h.size : page.text.length;
    }
    S = st; version = Math.max(version, st.version);
  }

  function poll() {
    API.get(base + query(20, version)).then(function (st) {
      take(st); draw();
      setTimeout(poll, 30);
    }).catch(function (e) {
      if (e && e.status === 404) { showGone(); return; }
      $('liveLine').textContent = 'Lost touch with your Rouh; trying again.';
      setTimeout(poll, 3000);
    });
  }
  function nudge() {   // presence moved: tell at once, without waiting for the long poll
    API.get(base + query(0, 1e9)).catch(function () {});
  }
  var nudgeT = null, nudgeAt = 0;
  function nudgeSoon() {   // the pointer moves often: at most once a second
    clearTimeout(nudgeT);
    var wait = Math.max(0, 1000 - (Date.now() - nudgeAt));
    nudgeT = setTimeout(function () { nudgeAt = Date.now(); nudge(); }, wait);
  }

  // --- the parts of the page, in words ------------------------------------------------------------

  var names = { v: -2, of: {} };
  var TAGWORD = { h1: 'heading', h2: 'heading', h3: 'heading', h4: 'heading', h5: 'heading', h6: 'heading', p: 'paragraph',
    img: 'picture', picture: 'picture', svg: 'drawing', a: 'link', button: 'button', table: 'table', tr: 'table row', td: 'table cell',
    th: 'table heading', ul: 'list', ol: 'list', li: 'list item', nav: 'menu', header: 'header', footer: 'footer', form: 'form',
    input: 'field', textarea: 'field', select: 'field', section: 'section', article: 'article', aside: 'side panel', main: 'main part',
    figure: 'figure', blockquote: 'quote', span: 'text', strong: 'text', em: 'text', label: 'label', video: 'video' };
  // The page as it stands names a part; an earlier version shown in history, only one gone since.
  function elName(id) {
    var key = page.v + (past ? '|p' + past.seq : '');
    if (names.v !== key) names = { v: key, of: {} };
    if (names.of[id] != null) return names.of[id];
    var text = page.text;
    var at = text.indexOf('data-rouh-id="' + id + '"');
    if (at < 0 && past) { text = past.text; at = text.indexOf('data-rouh-id="' + id + '"'); }
    var word = 'a part of the page';
    if (at >= 0) {
      var open = text.lastIndexOf('<', at);
      var t = /^<([a-zA-Z][a-zA-Z0-9-]*)/.exec(text.slice(open, open + 40));
      var tg = t ? t[1].toLowerCase() : '';
      var close = text.indexOf('>', at);
      var after = close >= 0 ? text.slice(close + 1, close + 400) : '';
      // Its first words: the first stretch of text in it, not everything inside it run together.
      var words = after.replace(/<[^>]*>?/g, '\u0000').split('\u0000').map(function (w) { return w.replace(/\s+/g, ' ').trim(); })
        .filter(Boolean)[0] || '';
      word = 'the ' + (TAGWORD[tg] || 'part');
      if (words) word += ' “' + (words.length > 36 ? words.slice(0, 35) + '…' : words) + '”';
    }
    return (names.of[id] = word);
  }
  function partName(part) {
    var bits = String(part).split(':');
    if (bits[0] === 'el' && ID.test(bits[1] || '')) return elName(bits[1]);
    if (part === 'text:html') return 'the source';
    return 'the page';
  }

  // --- who is here ---------------------------------------------------------------------------------

  function presenceByActor() {
    var by = {};
    (S.presence || []).forEach(function (p) { by[p.actor] = p; });
    return by;
  }
  function hereNow() {
    var by = presenceByActor();
    var out = [];
    (S.space.members || []).forEach(function (m) {
      if (m.state && m.state !== 'joined') return;
      ['person:' + m.label, 'rouh:' + m.label].forEach(function (a) {
        if (by[a] || labelOf(a) === S.me.label) out.push(a);   // this person, looking, and their Rouh are here
      });
    });
    return out;
  }

  function drawWho() {
    var box = clear($('who'));
    var by = presenceByActor();
    hereNow().forEach(function (a) {
      if (a === S.me.person) return;   // nobody follows themselves
      var here = by[a];
      box.appendChild(el('button', {
        class: 'av c-' + slot(labelOf(a)) + (isRouh(a) ? ' rouh' : '') + (here && here.busy ? ' busy' : ''),
        'aria-label': (following === a ? 'Stop following ' : 'Follow ') + actorWords(a) + (here && here.doing ? ': ' + here.doing : ''),
        title: actorWords(a) + (here && here.doing ? ': ' + here.doing : ''),
        'aria-pressed': following === a ? 'true' : 'false',
        text: initials(a),
        onclick: function () { following = following === a ? '' : a; revealed = ''; nudge(); draw(); }
      }));
    });
  }

  function liveLine() {
    var by = presenceByActor();
    var people = 0, rouhs = 0, working = [];
    hereNow().forEach(function (a) {
      if (isRouh(a)) { rouhs++; if (by[a] && by[a].busy) working.push(a); } else people++;
    });
    if (S.space.state === 'ended') return 'This space has ended. You can still read the page.';
    if (!S.space.joined) return shortName(S.space.holder) + ' asks you into this page.';
    var line = 'Live: ' + people + (people === 1 ? ' person' : ' people') + ' and ' + rouhs + (rouhs === 1 ? ' Rouh' : ' Rouhs') + ' here.';
    working.forEach(function (a) {
      var p = by[a];
      line += ' ' + actorWords(a) + ' is ' + (p.doing ? p.doing.charAt(0).toLowerCase() + p.doing.slice(1) : 'working') + (p.part ? ' (' + partName(p.part) + ')' : '') + '.';
    });
    return line;
  }

  function drawAtWork() {
    var by = presenceByActor();
    var others = S.space.state === 'ended' ? [] : hereNow().filter(function (a) { return isRouh(a) && labelOf(a) !== S.me.label && by[a] && by[a].busy; });
    var box = $('atWork');
    box.hidden = !others.length;
    clear(box);
    if (others.length) {
      box.appendChild(el('span', { text: others.map(actorWords).join(', ') + (others.length === 1 ? ' is' : ' are') + ' at work' }));
      if (canEdit()) box.appendChild(el('button', { class: 'quiet', text: 'Skip to the end', onclick: function () { others.forEach(skipFor); } }));
    }
  }

  function skipFor(actor) {
    if (labelOf(actor) === S.me.label) { act('skip').catch(fail); return; }
    send([op('pace', { target: actor, how: 'skip' })]).then(function () { toast('Asked ' + actorWords(actor) + ' to skip to the end.'); });
  }

  // --- the frame -----------------------------------------------------------------------------------

  function loadBridge() {
    if (bridge != null) return Promise.resolve(bridge);
    if (typeof window.LIVE_PAGE_BRIDGE === 'string') return Promise.resolve(bridge = window.LIVE_PAGE_BRIDGE);
    var at = document.body.getAttribute('data-bridge') || '/static/link/frame-bridge.js';
    return fetch(at, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error('bridge ' + r.status);
      return r.text();
    }).then(function (t) { return (bridge = t); });
  }

  // The whole document the frame gets: the policy first, then the bridge, called with where the viewer
  // was, then the page's own source with its doctype taken off.
  function srcdoc(html, start) {
    var call = String(bridge).replace(/[\s;]+$/, '') + '(' + JSON.stringify(start).replace(/</g, '\\u003c') + ');';
    call = call.replace(/<\/(script)/gi, '<\\/$1').replace(/<!--/g, '<\\!--');
    var body = String(html).replace(/^\s*(<!--[\s\S]*?-->\s*)*<!doctype[^>]*>/i, '');
    return '<!doctype html><meta http-equiv="Content-Security-Policy" content="' + POLICY + '"><script>' + call + '</scr' + 'ipt>' + body;
  }

  function newFrame(doc) {
    serial += 1;
    var f = document.createElement('iframe');
    f.setAttribute('sandbox', 'allow-scripts');
    f.setAttribute('csp', POLICY);
    f.setAttribute('referrerpolicy', 'no-referrer');
    // No `allow` attribute: a frame of another origin (this one's is opaque) gets no camera, microphone,
    // place, payment, USB or clipboard unless they are handed to it, and naming them only makes the
    // browser warn about each.
    f.setAttribute('title', 'The live page');
    f.name = 'rouh-live-' + serial;
    f.className = 'waiting';
    f.setAttribute('tabindex', '-1');
    f._loads = 0;
    f._ready = false;
    f.addEventListener('load', function () {
      f._loads += 1;
      // A second load is the page sending its own frame somewhere else: draw it again from the source.
      if (f._loads > 1 && f === frame && !f._moved) { f._moved = true; toast('The page tried to open another address. It is drawn again here, from its source.'); drawnKey = ''; drawFrame(true); }
    });
    f.srcdoc = doc;
    return f;
  }

  function wanted() {
    if (past) return { key: 'p' + past.seq, text: past.text };
    return { key: 'v' + page.v, text: page.text };
  }

  function drawFrame(force) {
    if (!S) return;
    var w = wanted();
    if (!force && w.key === drawnKey) return;
    if (pending) { drawAgain = true; return; }
    if (!String(w.text).trim()) { drawnKey = w.key; dropFrames(); showBlank(); return; }
    loadBridge().then(function () {
      drawnKey = w.key;
      var f = newFrame(srcdoc(w.text, { x: scroll.x, y: scroll.y, mode: commenting ? 'comment' : 'view', marks: marks(), cursors: frameCursors() }));
      pending = f;
      $('frames').appendChild(f);
      f._timer = setTimeout(function () { if (pending === f) notDrawn(f); }, 6000);
    }).catch(function () {
      say('This screen could not load what it needs to draw the page. Reload to try again.', 'bad');
    });
  }

  function swapIn(f) {
    clearTimeout(f._timer);
    f._ready = true;
    var old = frame;
    frame = f; pending = null;
    f.classList.remove('waiting');
    f.removeAttribute('tabindex');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    sentMarks = ''; sentCursors = '';
    say('');
    sendMarks();
    sendCursors(true);
    if (drawAgain) { drawAgain = false; drawFrame(); }
  }

  function notDrawn(f) {
    pending = null;
    if (f.parentNode) f.parentNode.removeChild(f);
    if (frame) say('The newest version did not finish drawing in 6 seconds, so the one before stays. Its source is in Source.', 'thin');
    else say('The page did not finish drawing. It may have a script that never ends, or broken markup. Its source is in Source.', 'bad');
    if (drawAgain) { drawAgain = false; drawFrame(); }
  }

  function dropFrames() {
    [frame, pending].forEach(function (f) { if (f) { clearTimeout(f._timer); if (f.parentNode) f.parentNode.removeChild(f); } });
    frame = null; pending = null; drawAgain = false;
  }

  // Words over the stage: '' takes them away.
  function say(words, how) {
    var box = $('frameSaid');
    clear(box);
    box.className = 'lp-over' + (how === 'thin' ? ' thin' : '');
    box.hidden = !words;
    if (!words) return;
    var kids = [el('p', { text: words })];
    if (how === 'thin') kids.push(el('button', { type: 'button', text: 'Dismiss', onclick: function () { say(''); } }));
    else kids.unshift(svg(['M12 8v5', 'M12 16.5v.5', 'M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z']));
    if (how !== 'thin' && view !== 'both') kids.push(el('button', { type: 'button', text: 'Show the source', onclick: function () { setView('source'); } }));
    box.appendChild(el('div', {}, kids));
  }

  function showBlank() {
    var box = $('frameSaid');
    clear(box);
    box.className = 'lp-over';
    box.hidden = false;
    var kids = [svg(['M6 3h8l4 4v14H6z', 'M14 3v4h4']), el('h2', { text: past ? 'The page was blank then' : 'This page is blank' })];
    if (past) kids.push(el('p', { class: 'dim', text: 'Nothing was on it after change ' + past.seq + '.' }));
    else if (canEdit()) {
      kids.push(el('p', { class: 'dim', text: 'Ask your Rouh what to put on it, or write its source yourself. Everyone here sees it the moment it changes.' }));
      kids.push(el('button', { type: 'button', text: 'Edit source', onclick: startEdit }));
    } else kids.push(el('p', { class: 'dim', text: 'Nobody has started it yet. It appears here the moment someone does.' }));
    box.appendChild(el('div', {}, kids));
  }

  // Only the frame this screen made speaks, only in the fixed shapes, every value checked.
  var SHAPES = { ready: ['h'], scroll: ['x', 'y'], pointer: ['part', 'x', 'y'], pick: ['part'], select: ['part', 'a', 'f', 'q'], tap: ['part', 'x', 'y'] };
  var EL = /^el:[A-Za-z0-9_-]{1,40}$/;
  function isFrac(v) { return typeof v === 'number' && isFinite(v) && v >= 0 && v <= 1; }
  function fr3(v) { return Math.round(v * 1000) / 1000; }
  function inFrame() {
    var box = $('frames') ? $('frames').getBoundingClientRect() : null;
    if (!box || !box.width) return false;
    if (!lastOut) return true;                       // not seen on this screen yet: came in from outside the window
    if (Date.now() - lastOut.t < 120) return false;  // still moving on Rouh's own screen
    var m = 48;
    return lastOut.x >= box.left - m && lastOut.x <= box.right + m && lastOut.y >= box.top - m && lastOut.y <= box.bottom + m;
  }
  window.addEventListener('message', function (ev) {
    var f = frame && ev.source === frame.contentWindow ? frame : (pending && ev.source === pending.contentWindow ? pending : null);
    if (!f || ev.origin !== 'null') return;
    var m = ev.data;
    if (!m || typeof m !== 'object' || Array.isArray(m) || m.rouh !== TAG || !SHAPES.hasOwnProperty(m.type)) return;
    var keys = Object.keys(m);
    var allowed = ['rouh', 'type'].concat(SHAPES[m.type]);
    if (keys.length > allowed.length || keys.some(function (k) { return allowed.indexOf(k) < 0; })) return;
    if (m.type === 'ready') {
      if (f === pending && typeof m.h === 'number') swapIn(f);
      return;
    }
    if (f !== frame) return;
    if (m.type === 'scroll') {
      if (typeof m.x === 'number' && typeof m.y === 'number' && isFinite(m.x) && isFinite(m.y))
        scroll = { x: Math.max(0, Math.min(1e7, Math.round(m.x))), y: Math.max(0, Math.min(1e7, Math.round(m.y))) };
    } else if (m.type === 'pointer') {
      if (typeof m.part !== 'string' || m.part.length > 44) return;
      if (m.part && !EL.test(m.part)) return;
      if (m.part && (!isFrac(m.x) || !isFrac(m.y))) return;
      // The page's own script runs in the same frame and could post these too. So a point is taken
      // only while this screen itself saw the pointer go over the frame: a page cannot move the
      // person's arrow on the others' screens while the person is somewhere else.
      if (!inFrame()) return;
      if (cur && !past) cur.move(m.part ? { part: m.part, x: fr3(m.x), y: fr3(m.y) } : { part: '' });
      if (m.part && m.part !== myPart && !editing) { myPart = m.part; nudgeSoon(); }
    } else if (m.type === 'tap') {
      if (typeof m.part !== 'string' || !EL.test(m.part) || !isFrac(m.x) || !isFrac(m.y)) return;
      var now = Date.now();
      if (now - touchedAt < 300) return;   // a page's script cannot fill the others' screens with rings
      touchedAt = now;
      if (cur && !past) cur.tap({ part: m.part, x: fr3(m.x), y: fr3(m.y) });
      if (m.part !== myPart && !editing) { myPart = m.part; nudgeSoon(); }
    } else if (m.type === 'select') {
      if (typeof m.part !== 'string' || (m.part && !EL.test(m.part))) return;
      if (!m.part) {
        // Nothing selected in the page any more: only a selection that was in the page goes.
        if (mySel === 'el' && cur) { mySel = ''; cur.select(null); }
        return;
      }
      var whole = function (v) { return typeof v === 'number' && isFinite(v) && v >= 0 && v <= MOST && Math.floor(v) === v; };
      if (!whole(m.a) || !whole(m.f) || typeof m.q !== 'string' || m.q.length > 300) return;
      // As with the pointer: only while the person is in the frame (pointer over it, the frame
      // focused, or a tap in it just now), so a page cannot put words in the person's selection.
      if (!inFrame() && document.activeElement !== frame && Date.now() - touchedAt > 10000) return;
      if (cur && !past) { mySel = 'el'; cur.select({ t: m.part, a: { i: m.a }, f: { i: m.f } }, m.q); }
    } else if (m.type === 'pick') {
      if (!commenting || !canComment() || past || typeof m.part !== 'string' || m.part.length > 56) return;
      var g = /^el:([A-Za-z0-9_-]{1,40}):(\d{1,4}):(\d{1,4})$/.exec(m.part);
      if (!g || +g[2] > 1000 || +g[3] > 1000) return;
      openPick(m.part);
    }
  });

  function post(msg) {
    if (!frame || !frame.contentWindow) return;
    msg.rouh = TAG;
    frame.contentWindow.postMessage(msg, '*');
  }

  // Every mark on the page: each member where it is, the intents shown, the claims, the comment pins.
  function marks() {
    if (!S) return [];
    var out = [], on = {};
    var by = S.space.state === 'ended' ? {} : presenceByActor();
    Object.keys(by).forEach(function (a) {
      var p = by[a];
      if (!p.part || !/^el:[A-Za-z0-9_-]{1,40}$/.test(p.part)) return;
      if (labelOf(a) === S.me.label && !isRouh(a)) return;
      on[a + p.part] = true;
      out.push({ part: p.part, who: isRouh(a) ? actorWords(a) + (p.busy && p.doing ? ': ' + p.doing : '') : shortName(labelOf(a)) + ' is looking here', colour: hexOf(labelOf(a)), kind: isRouh(a) ? 'rouh' : 'person' });
    });
    (S.doc.intents || []).forEach(function (i) {
      if (i.state !== 'shown' || S.space.state === 'ended' || !/^el:[A-Za-z0-9_-]{1,40}$/.test(i.part || '') || on[i.by + i.part]) return;
      out.push({ part: i.part, who: actorWords(i.by) + ' is about to change this', colour: hexOf(labelOf(i.by)), kind: 'intent' });
    });
    var claims = S.doc.claims || {};
    Object.keys(claims).forEach(function (part) {
      if (!/^el:[A-Za-z0-9_-]{1,40}$/.test(part)) return;
      out.push({ part: part, who: 'Claimed by ' + actorWords(claims[part].by), colour: hexOf(labelOf(claims[part].by)), kind: 'claim' });
    });
    numbered().forEach(function (c) {
      if (c.resolved || !/^el:[A-Za-z0-9_-]{1,40}:\d{1,4}:\d{1,4}$/.test(c.part)) return;
      out.push({ part: c.part, who: '', colour: hexOf(labelOf(c.by)), kind: 'comment', n: c.n });
    });
    return out;
  }
  function sendMarks(force) {
    if (!frame) return;
    var m = past ? [] : marks();
    var key = JSON.stringify(m);
    if (!force && key === sentMarks) return;
    sentMarks = key;
    post({ type: 'marks', marks: m });
  }

  function follow() {
    if (!following || past) return;
    if (following.indexOf('person:') === 0) {
      // A person with a live pointer: their pointer's element, each time it changes, not every frame.
      var c = others.filter(function (o) { return o.actor === following && !o.gone && o.part && EL.test(o.part) && (o.age || 0) < 4; })[0];
      if (c) {
        if (c.part !== revealed && frame) { revealed = c.part; post({ type: 'reveal', part: c.part }); }
        return;
      }
    }
    var p = presenceByActor()[following];
    if (p && p.part && /^el:/.test(p.part) && p.part !== revealed && frame) {
      revealed = p.part;
      post({ type: 'reveal', part: p.part });
    }
  }

  // --- live cursors ----------------------------------------------------------------------------------

  // A person's own colour: one of the four people's colours, each label its own, in the order seen.
  // Never --partner (amber) or --accent (turquoise): those are the Rouhs'.
  function personHex(label) {
    if (personColours[label] == null) personColours[label] = (Object.keys(personColours).length % 4) + 1;
    var v = getComputedStyle(document.documentElement).getPropertyValue('--person-' + personColours[label]).trim();
    return /^#[0-9a-fA-F]{3,8}$/.test(v) ? v : '#a3b1b6';
  }
  function personName(c) {
    var n = String(c.name || '') || (S ? shortName(labelOf(c.actor)) : '') || 'Someone';
    return n.split(' ·')[0].slice(0, 40);
  }
  function takeCursors(list) {
    others = (Array.isArray(list) ? list : []).filter(function (c) {
      return c && typeof c === 'object' && /^person:[A-Za-z0-9_.:-]{1,80}$/.test(String(c.actor));
    });
    othersAt = Date.now();
    sendCursors();
    drawSourceSel();
    follow();
  }
  // What the frame gets: only parts of the drawn page, every value plain and in range.
  function frameCursors() {
    if (past) return [];
    var lag = (Date.now() - othersAt) / 1000;
    return others.slice(0, 40).map(function (c) {
      var part = typeof c.part === 'string' && EL.test(c.part) ? c.part : '';
      var one = { id: String(c.actor), name: personName(c), part: part, x: isFrac(c.x) ? c.x : 0, y: isFrac(c.y) ? c.y : 0,
        colour: personHex(labelOf(c.actor)), tap: c.tap === true, gone: c.gone === true,
        age: Math.max(0, Math.min(3600, (typeof c.age === 'number' && isFinite(c.age) ? c.age : 0) + lag)) };
      var s = c.sel;
      if (s && typeof s === 'object' && typeof s.t === 'string' && EL.test(s.t) && s.a && s.f && typeof s.a.i === 'number' && typeof s.f.i === 'number')
        one.sel = { part: s.t, a: Math.max(0, Math.min(MOST, Math.round(s.a.i))), f: Math.max(0, Math.min(MOST, Math.round(s.f.i))) };
      return one;
    });
  }
  function sendCursors(force) {
    if (!frame) return;
    var list = frameCursors();
    var key = JSON.stringify(list.map(function (c) { var o = {}; Object.keys(c).forEach(function (k) { if (k !== 'age') o[k] = c[k]; }); return o; }));
    if (!force && key === sentCursors) return;
    sentCursors = key;
    post({ type: 'cursors', cursors: list });
  }

  // The person's own selection in the source: the source view (offsets in its text, which is the
  // page's text) or the box they edit in.
  function textAt(within, node, off) {
    try { var r = document.createRange(); r.setStart(within, 0); r.setEnd(node, off); return r.toString().length; } catch (e) { return -1; }
  }
  function sourceSelected() {
    if (!cur || past) return;
    if (editing) {
      var t = $('sourceText');
      if (document.activeElement !== t) return;   // keep the last one while the person is elsewhere
      var a = t.selectionDirection === 'backward' ? t.selectionEnd : t.selectionStart;
      var f = t.selectionDirection === 'backward' ? t.selectionStart : t.selectionEnd;
      mySel = 'src';
      cur.select({ t: 'src', a: { i: a }, f: { i: f } }, t.value.slice(Math.min(a, f), Math.max(a, f)).slice(0, 300));
      return;
    }
    var sel = window.getSelection ? window.getSelection() : null;
    var pre = $('sourceView');
    if (!sel || !sel.rangeCount || !pre.contains(sel.anchorNode) || !pre.contains(sel.focusNode)) return;   // elsewhere: kept
    var a2 = textAt(pre, sel.anchorNode, sel.anchorOffset), f2 = textAt(pre, sel.focusNode, sel.focusOffset);
    if (a2 < 0 || f2 < 0) return;
    mySel = 'src';
    cur.select({ t: 'src', a: { i: a2 }, f: { i: f2 } }, String(sel).slice(0, 300));
  }

  // The others' selections in the source: tinted bands over the source view, from their offsets in
  // the page's text, and in words while the person is editing (the box they type in is their own).
  function lineOf(text, i) { var n = 1, at = -1; while ((at = text.indexOf('\n', at + 1)) >= 0 && at < i) n++; return n; }
  function drawSourceSel() {
    var layer = $('srcMarks'), said = $('srcSel');
    if (!layer || !said) return;
    clear(layer); clear(said);
    var text = page.text;
    var sels = past ? [] : others.filter(function (c) {
      var s = c.sel;
      return !c.gone && s && s.t === 'src' && s.a && s.f && typeof s.a.i === 'number' && typeof s.f.i === 'number';
    });
    said.hidden = true;
    if (!sels.length) return;
    var pre = $('sourceView');
    var showing = !editing && !pre.hidden && pre.offsetParent !== null && pre.textContent.length === text.length;
    if (showing) {   // the layer sits exactly over the source view, so a band scrolled out of it is cut off
      layer.style.left = pre.offsetLeft + 'px'; layer.style.top = pre.offsetTop + 'px';
      layer.style.width = pre.offsetWidth + 'px'; layer.style.height = pre.offsetHeight + 'px';
    }
    var lines = [];
    sels.slice(0, 8).forEach(function (c) {
      var lo = Math.max(0, Math.min(text.length, Math.min(c.sel.a.i, c.sel.f.i))), hi = Math.max(0, Math.min(text.length, Math.max(c.sel.a.i, c.sel.f.i)));
      var l1 = lineOf(text, lo), l2 = lineOf(text, hi);
      lines.push({ who: personName(c), colour: personHex(labelOf(c.actor)), words: l1 === l2 ? 'line ' + l1 : 'lines ' + l1 + ' to ' + l2, caret: lo === hi });
      if (showing) bandsIn(pre, layer, lo, hi, personHex(labelOf(c.actor)), personName(c));
    });
    if (!showing) {
      said.hidden = false;
      lines.forEach(function (l) {
        said.appendChild(el('p', { class: 'small lp-src-sel' }, [el('span', { class: 'lp-dot', style: '--c:' + l.colour, 'aria-hidden': 'true' }),
          l.who + (l.caret ? ' is in the source: ' : ' is selecting in the source: ') + l.words]));
      });
    }
  }
  function bandsIn(pre, layer, lo, hi, colour, who) {
    var w = document.createTreeWalker(pre, 4, null), t, at = 0, start = null, end = null, last = null;
    while ((t = w.nextNode())) {
      var len = t.data.length;
      if (!start && lo <= at + len) start = [t, lo - at];
      if (!end && hi <= at + len) { end = [t, hi - at]; break; }
      at += len; last = t;
    }
    if (!start || !end) return;
    var r = document.createRange();
    try { r.setStart(start[0], start[1]); r.setEnd(end[0], end[1]); } catch (e) { return; }
    var box = layer.getBoundingClientRect();
    var pr = pre.getBoundingClientRect();
    var inside = function (q) { return q.bottom > pr.top && q.top < pr.bottom; };
    if (lo !== hi) Array.prototype.slice.call(r.getClientRects(), 0, 300).forEach(function (q) {
      if (q.width < 1 || !inside(q)) return;
      layer.appendChild(el('span', { class: 'lp-band', style: '--c:' + colour + ';left:' + (q.left - box.left) + 'px;top:' + (q.top - box.top) + 'px;width:' + q.width + 'px;height:' + q.height + 'px' }));
    });
    var c = r.cloneRange(); c.collapse(false);
    var q = c.getClientRects()[0] || c.getBoundingClientRect();
    if (q && inside(q)) layer.appendChild(el('span', { class: 'lp-caret', style: '--c:' + colour + ';left:' + (q.left - box.left) + 'px;top:' + (q.top - box.top) + 'px;height:' + Math.max(14, q.height) + 'px' },
      [el('span', { class: 'lp-caret-name', style: 'color:' + inkOn(colour), text: who.split(/\s+/)[0] })]));
  }
  function inkOn(hex) {
    var h = hex.replace('#', '');
    if (h.length < 6) h = h.split('').map(function (c) { return c + c; }).join('');
    var lin = function (i) { var c = parseInt(h.substr(i, 2), 16) / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    return 0.2126 * lin(0) + 0.7152 * lin(2) + 0.0722 * lin(4) > 0.18 ? '#0b1114' : '#ffffff';
  }

  function startCursors() {
    if (!window.RouhCursors || cur) return;
    cur = window.RouhCursors.start({ base: base, key: 'link-cursor-share', onCursors: takeCursors });
    var box = $('cursorShare');
    if (box) {
      box.checked = cur.sharing();
      box.addEventListener('change', function () { cur.share(box.checked); toast(box.checked ? 'The others see your cursor again.' : 'Your cursor is hidden from the others. Your own Rouh still sees where you point.'); });
    }
    // Over Rouh's own screen, outside the page: remembered (see `inFrame`), and the arrow goes from
    // the others' screens.
    var offAt = 0;
    document.addEventListener('pointermove', function (ev) {
      if (ev.pointerType === 'touch') return;
      var now = Date.now();
      lastOut = { x: ev.clientX, y: ev.clientY, t: now };
      if (now - offAt < 250) return;
      offAt = now;
      cur.move({ part: '' });
    }, { passive: true });
    document.documentElement.addEventListener('pointerleave', function (ev) {
      if (ev.pointerType === 'touch') return;
      lastOut = null;   // out of the window: it may come back in anywhere, the frame included
      cur.move({ part: '' });
    });
    document.addEventListener('selectionchange', function () { clearTimeout(startCursors.t); startCursors.t = setTimeout(sourceSelected, 80); });
    var t = $('sourceText');
    ['select', 'keyup', 'mouseup', 'focus'].forEach(function (k) { t.addEventListener(k, function () { clearTimeout(startCursors.t); startCursors.t = setTimeout(sourceSelected, 80); }); });
    $('sourceView').addEventListener('scroll', function () { requestAnimationFrame(drawSourceSel); }, { passive: true });
    window.addEventListener('resize', function () { requestAnimationFrame(drawSourceSel); });
  }

  // --- the views: page, side by side, source --------------------------------------------------------

  var wide = window.matchMedia('(min-width: 1241px)');
  function setView(v) {
    if (v === 'both' && !wide.matches) v = 'page';
    view = v;
    $('stage').setAttribute('data-view', v);
    $('viewPage').setAttribute('aria-pressed', v === 'page' ? 'true' : 'false');
    $('viewBoth').setAttribute('aria-pressed', v === 'both' ? 'true' : 'false');
    $('viewSource').setAttribute('aria-pressed', v === 'source' ? 'true' : 'false');
    if (v !== 'page' && v !== 'both' && commenting) setCommenting(false);
    requestAnimationFrame(drawSourceSel);
  }

  function setCommenting(on) {
    commenting = !!on && canComment();
    $('commentMode').setAttribute('aria-pressed', commenting ? 'true' : 'false');
    $('stage').classList.toggle('commenting', commenting);
    $('modeSaid').hidden = !commenting;
    if (commenting && view === 'source') setView(wide.matches ? 'both' : 'page');
    post({ type: 'mode', mode: commenting ? 'comment' : 'view' });
    if (!commenting) closePick();
  }

  // --- a comment on a spot, and a claim on its part -----------------------------------------------

  function openPick(part) {
    picked = part;
    var id = part.split(':')[1];
    $('pickTitle').textContent = 'On ' + elName(id);
    $('pickWords').value = '';
    var box = $('pickBox');
    box.style.top = '12px'; box.style.right = '12px'; box.style.left = 'auto';
    box.hidden = false;
    drawPickClaim();
    primaries();
    $('pickWords').focus();
  }
  function drawPickClaim() {
    if (!picked) return;
    var whole = 'el:' + picked.split(':')[1];
    var claim = (S.doc.claims || {})[whole];
    var b = $('pickClaim'), said = $('pickClaimed');
    b.hidden = !canEdit();
    said.hidden = !claim;
    if (claim) said.textContent = 'Claimed by ' + actorWords(claim.by) + ': no other Rouh changes it.';
    b.textContent = claim ? (claim.by === S.me.person ? 'Let go' : 'Take back') : 'Claim this part';
    b.setAttribute('title', claim ? 'Let anyone change this part again' : 'Take this part: no other Rouh changes it until you let it go');
  }
  function closePick() {
    picked = '';
    $('pickBox').hidden = true;
    primaries();
  }

  // One primary button per view: while the source is edited or a comment written, that is the one.
  function primaries() {
    $('rouhGo').classList.toggle('primary', !editing && !picked);
  }

  // --- the source ----------------------------------------------------------------------------------

  var sourceKey = '';
  function drawSource() {
    var text = past ? past.text : page.text;
    var by = past ? past.by : page.by;
    var key = (past ? 'p' + past.seq : 'v' + page.v) + '|' + Object.keys(colours).length;
    var size = past ? text.length : page.size;
    var sz = $('size');
    sz.textContent = kb(size) + ' of 2 MB' + (size > MOST * 0.9 ? ', nearly full' : '');
    sz.classList.toggle('near', size > MOST * 0.9);
    $('editSource').hidden = !canEdit() || !!past || !!editing;
    $('sourceBox').classList.toggle('editing', !!editing);
    $('sourceView').hidden = !!editing;
    $('sourceEdit').hidden = !editing;
    if (editing) {
      var note = $('sourceSaid');
      if (page.v !== editing.base && note.className.indexOf('bad') < 0) {
        note.hidden = false; note.className = 'small lp-said info';
        note.textContent = 'The page changed while you edit. Saving keeps their change and yours.';
      }
    }
    var writers = {};
    (by || []).forEach(function (r) { writers[r[2]] = (writers[r[2]] || 0) + r[1]; });
    var w = clear($('writers'));
    Object.keys(writers).sort(function (a, b) { return writers[b] - writers[a]; }).slice(0, 5).forEach(function (a) { w.appendChild(tag(a)); });
    if (key === sourceKey) return;
    sourceKey = key;
    var pre = $('sourceView');
    var top = pre.scrollTop;
    clear(pre);
    if (!text) { pre.appendChild(el('span', { class: 'dim', text: 'Nothing here yet.' })); return; }
    if (text.length > 300000 || !by || !by.length || by.length > 4000) { pre.textContent = text; pre.scrollTop = top; drawSourceSel(); return; }
    var frag = document.createDocumentFragment();
    var at = 0;
    by.forEach(function (r) {
      var start = r[0], len = r[1];
      if (start > at) frag.appendChild(document.createTextNode(text.slice(at, start)));
      var piece = text.slice(start, start + len);
      var n = slot(labelOf(r[2]));
      if (n === 0 && !isRouh(r[2])) frag.appendChild(document.createTextNode(piece));
      else frag.appendChild(el('span', { class: 'w-' + Math.max(1, n), title: 'Written by ' + actorWords(r[2]), text: piece }));
      at = start + len;
    });
    if (at < text.length) frag.appendChild(document.createTextNode(text.slice(at)));
    pre.appendChild(frag);
    pre.scrollTop = top;
    drawSourceSel();
  }
  function kb(n) { return n >= 1000000 ? (n / 1000000).toFixed(2).replace(/\.?0+$/, '') + ' MB' : Math.max(n ? 1 : 0, Math.round(n / 1000)) + ' KB'; }

  function startEdit() {
    if (!canEdit()) return;
    if (past) { leavePast(); }
    editing = { base: page.v, start: page.text };
    $('sourceText').value = page.text;
    $('sourceSaid').hidden = true; $('sourceSaid').className = 'small lp-said';
    if (view === 'page') setView(wide.matches ? 'both' : 'source');
    myPart = 'text:html'; nudge();
    draw();
    drawSourceSel();
    $('sourceText').focus();
  }
  function stopEdit() {
    editing = null;
    myPart = '';
    if (mySel === 'src' && cur) { mySel = ''; cur.select(null); }
    nudge();
    draw();
    drawSourceSel();
  }
  function saveSource(ev) {
    ev.preventDefault();
    if (!editing) return;
    var html = $('sourceText').value;
    var said = $('sourceSaid');
    if (html.length > MOST) {
      said.hidden = false; said.className = 'small lp-said';
      said.textContent = 'A live page holds at most 2 MB; this change would make it bigger. It is ' + kb(html.length) + '.';
      return;
    }
    if (html === editing.start && page.v === editing.base) { stopEdit(); return; }
    $('sourceSave').disabled = true;
    act('source', { html: html, base: editing.base }).then(function (got) {
      var refused = (got && got.refused) || [];
      if (refused.length) {
        said.hidden = false; said.className = 'small lp-said';
        said.textContent = refused[0].why || 'Your Rouh did not take that change.';
        return;
      }
      stopEdit();
      toast('Saved. Everyone here sees it now.');
    }).catch(function (e) {
      said.hidden = false; said.className = 'small lp-said';
      said.textContent = e && e.message ? e.message : 'That did not save.';
    }).then(function () { $('sourceSave').disabled = false; });
  }
  function cancelEdit() {
    if (!editing) return;
    var kept = $('sourceText').value, was = editing;
    var changed = kept !== was.start;
    stopEdit();
    if (changed) toast('Your edit was not saved.', function () {
      editing = was; $('sourceText').value = kept; myPart = 'text:html'; nudge(); draw(); $('sourceText').focus();
    });
  }

  // --- the side -------------------------------------------------------------------------------------

  function drawIntent() {
    // An ended space has nobody at work in it, whatever an intent was left saying.
    var shown = S.space.state === 'ended' ? [] : (S.doc.intents || []).filter(function (i) { return i.state === 'shown'; });
    var box = clear($('intent'));
    box.hidden = !shown.length;
    shown.forEach(function (i) {
      var started = (S.doc.activity || []).some(function (a) { return a.by === i.by && a.seq > i.seq; });
      box.appendChild(el('div', { class: 'banner', role: 'status' }, [
        tag(i.by), el('p', { text: (started ? 'is working on: ' : 'is about to: ') + i.words + (i.part && i.part !== 'text:html' ? ' (' + partName(i.part) + ')' : '') }),
        canEdit() ? el('button', { type: 'button', text: 'Skip to the end', onclick: function () { skipFor(i.by); } }) : null,
        canEdit() ? el('button', { type: 'button', class: 'stop', text: 'Stop', onclick: function () {
          send([op('intent.end', { iid: i.id, state: 'stopped' })]);
          if (labelOf(i.by) === S.me.label) act('stop').catch(function () {});
        } }) : null
      ]));
    });
  }

  function drawMyRouh() {
    var pace = S.pacing || {};
    $('rouhBusy').hidden = !pace.busy;
    $('rouhAsk').hidden = !!pace.busy || !canEdit();
    var cannot = $('rouhCannot');
    cannot.hidden = canEdit() || !!pace.busy;
    if (!canEdit()) cannot.textContent = !live() ? 'Nothing can change here now.'
      : S.me.role === 'commenter' ? 'You can comment on the page. Only the owner and editors ask their Rouh to change it.'
      : 'You are watching. Only the owner and editors ask their Rouh to change this page.';
    if (pace.busy) $('rouhProgress').textContent = 'Working: ' + pace.done + ' of ' + pace.total + ' steps' + (pace.skipping ? ', skipping to the end' : '') + '.';
    var feed = clear($('feed'));
    var acts = (S.doc.activity || []).slice(-12).reverse();
    if (!acts.length) feed.appendChild(el('li', { class: 'dim' }, [el('span', { text: 'What the Rouhs do here shows up here, step by step.' })]));
    var shown = {};
    acts.forEach(function (a) {
      var older = shown[a.by];
      shown[a.by] = true;
      feed.appendChild(el('li', { class: older ? 'older' : '' }, [older ? null : tag(a.by), el('span', { text: (a.of ? a.step + ' of ' + a.of + ': ' : '') + a.words })]));
    });
  }

  // Comments in the order they were made, numbered once, so a pin and its line agree.
  function numbered() {
    return (S.doc.comments || []).map(function (c, i) { return { id: c.id, part: c.part, by: c.by, text: c.text, resolved: c.resolved, at: c.at, n: i + 1 }; });
  }
  var showResolved = false;
  function drawComments() {
    var all = numbered();
    var open = all.filter(function (c) { return !c.resolved; });
    var done = all.filter(function (c) { return c.resolved; });
    $('commentCount').textContent = open.length ? open.length + ' open' : '';
    var ol = clear($('comments'));
    if (!all.length) {
      ol.appendChild(el('li', { class: 'dim small lp-none' }, [el('span', { text: canComment() ? 'No comments yet. Press Comment, then click a spot on the page.' : 'No comments yet.' })]));
      return;
    }
    open.concat(showResolved ? done : []).forEach(function (c) {
      var whole = String(c.part).split(':').slice(0, 2).join(':');
      ol.appendChild(el('li', { class: c.resolved ? 'resolved' : '' }, [
        el('span', { class: 'num c-' + slot(labelOf(c.by)), 'aria-label': 'Comment ' + c.n, text: String(c.n) }),
        el('div', { class: 'body' }, [
          el('div', { class: 'row', style: 'gap:6px' }, [tag(c.by), el('span', { class: 'small dim', text: 'on ' + partName(c.part) })]),
          el('p', { text: c.text }),
          el('div', { class: 'acts' }, [
            /^el:/.test(whole) ? el('button', { type: 'button', class: 'quiet', text: 'Show on the page', onclick: function () {
              if (view === 'source') setView('page');
              if (past) leavePast();
              post({ type: 'reveal', part: whole });
            } }) : null,
            !c.resolved && canComment() ? el('button', { type: 'button', class: 'quiet', text: 'Resolve', onclick: function () {
              send([op('resolve', { cid: c.id })]).then(function () { toast('Resolved comment ' + c.n + '.'); });
            } }) : null,
            c.resolved ? el('span', { class: 'small dim', text: 'Resolved' }) : null
          ])
        ])
      ]));
    });
    if (done.length) ol.appendChild(el('li', {}, [el('span'), el('button', { type: 'button', class: 'quiet small', 'aria-expanded': showResolved ? 'true' : 'false',
      text: showResolved ? 'Hide the resolved ones' : 'Show ' + done.length + ' resolved', onclick: function () { showResolved = !showResolved; drawComments(); } })]));
  }

  function editsBy(actor) {
    var n = 0, d = S.doc;
    Object.keys(d.field_by || {}).forEach(function (k) { if (d.field_by[k] === actor) n++; });
    Object.keys(d.lists || {}).forEach(function (k) { d.lists[k].forEach(function (it) { if (it.by === actor) n++; }); });
    Object.keys(d.texts || {}).forEach(function (k) { (d.texts[k].by || []).forEach(function (r) { if (r[2] === actor) n += 1; }); });
    (page.by || []).forEach(function (r) { if (r[2] === actor) n += 1; });
    return n;
  }

  // Every member, each said to be here now or away; the count agrees with the live line's.
  function drawMembers() {
    var box = clear($('members'));
    var now = hereNow();
    $('hereCount').textContent = now.length + ' here now';
    (S.space.members || []).forEach(function (m) {
      if (m.state && ['joined', 'invited'].indexOf(m.state) < 0) return;
      ['person:', 'rouh:'].forEach(function (k) {
        var a = k + m.label;
        var edits = editsBy(a);
        box.appendChild(el('div', { class: 'member' }, [
          el('span', { class: 'av c-' + slot(m.label) + (k === 'rouh:' ? ' rouh' : ''), 'aria-hidden': 'true', text: initials(a) }),
          el('div', {}, [el('div', { text: actorWords(a) }), el('div', { class: 'role', text: (k === 'rouh:' ? 'Rouh, ' : '') + (m.role || '') + (m.state === 'invited' ? ', asked in' : now.indexOf(a) >= 0 ? ', here now' : ', away') })]),
          k === 'rouh:' && edits && canEdit() ? el('button', { type: 'button', class: 'quiet', text: 'Undo its edits', title: 'Takes out this Rouh’s edits; the people’s stay',
            onclick: function () {
              send([op('undo', { target: a, from: 0 })]).then(function () { toast('Took out ' + actorWords(a) + '’s edits. The people’s stay.'); });
            } }) : el('span')
        ]));
      });
    });
    var claims = S.doc.claims || {};
    var parts = Object.keys(claims);
    $('claimsBox').hidden = !parts.length;
    var ul = clear($('claims'));
    parts.forEach(function (part) {
      var c = claims[part];
      var mine = c.by === S.me.person;
      ul.appendChild(el('li', {}, [
        el('span', { class: 'what', text: partName(part) }), tag(c.by),
        canEdit() ? el('button', { type: 'button', class: 'quiet', text: mine ? 'Let go' : 'Take back',
          onclick: function () { send([op('release', { part: part })]).then(function () { toast(mine ? 'Let go of ' + partName(part) + '.' : 'Took back ' + partName(part) + '.'); }); } }) : null
      ]));
    });
    $('inviteBox').hidden = !S.space.mine || S.space.state !== 'live';
  }

  // The version in the task: the owner brings it in, or puts back what was there; a member asks.
  function drawKeep() {
    var box = clear($('keep'));
    var src = String(S.space.source || '');
    var inTask = src && src.indexOf('card:') !== 0;
    if (S.space.mine) {
      $('keepBox').hidden = !inTask && !(S.space.keep_asks || []).length;
      $('keepTitle').textContent = 'This page in the task';
      if (inTask) {
        box.appendChild(el('p', { class: 'small dim', text: 'It came from this page in your workspace:' }));
        box.appendChild(el('p', { class: 'lp-path', text: src }));
        var b = S.space.brought;
        if (b) {
          var when = new Date((b.at || 0) * 1000);
          box.appendChild(el('p', { class: 'small', text: 'You brought the version of change ' + b.seq + ' into it at ' + when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) + '. What was there is kept.' }));
        }
        if (S.space.state === 'live' || b) {
          var row = el('div', { class: 'row' });
          if (S.space.state === 'live') row.appendChild(el('button', { type: 'button', id: 'bringBack', text: 'Bring this version into the task', onclick: function (ev) {
            var btn = ev.currentTarget; btn.disabled = true;
            act('bring_back').then(function (got) { toast(got.said || 'Brought this version into the task.'); }).catch(fail).then(function () { btn.disabled = false; });
          } }));
          if (b) row.appendChild(el('button', { type: 'button', class: 'quiet', text: 'Put back what was there', onclick: function (ev) {
            var btn = ev.currentTarget; btn.disabled = true;
            act('put_back').then(function (got) { toast(got.said || 'Put back what was there.'); }).catch(fail).then(function () { btn.disabled = false; });
          } }));
          box.appendChild(row);
        }
      }
      var asks = S.space.keep_asks || [];
      if (asks.length) {
        box.appendChild(el('h3', { class: 'lp-sub', text: asks.length === 1 ? 'One ask to keep a version' : asks.length + ' asks to keep a version' }));
        asks.slice(-8).reverse().forEach(function (k) {
          box.appendChild(el('div', { class: 'lp-ask' }, [
            el('p', { class: 'small', text: String(k.name || k.from).split(' ·')[0] + ' asks you to keep the version of change ' + k.seq + '.' }),
            k.words ? el('p', { class: 'small dim', text: '“' + k.words + '”' }) : null
          ]));
        });
      }
      return;
    }
    var may = live() && ['editor', 'commenter'].indexOf(S.me.role) >= 0;
    $('keepBox').hidden = !may;
    $('keepTitle').textContent = 'Keep this version';
    if (!may) return;
    var words = el('textarea', { id: 'keepWords', rows: '2', maxlength: '300', placeholder: 'This one reads best' });
    box.appendChild(el('p', { class: 'small dim', text: shortName(S.space.holder) + ' decides what goes back into their task.' }));
    box.appendChild(el('div', {}, [el('label', { for: 'keepWords', text: 'A word for them (optional)' }), words]));
    box.appendChild(el('button', { type: 'button', text: 'Ask the owner to keep this version', onclick: function (ev) {
      var btn = ev.currentTarget; btn.disabled = true;
      act('ask_keep', { words: words.value.trim().slice(0, 300) }).then(function () {
        words.value = ''; toast('Asked ' + shortName(S.space.holder) + ' to keep this version.');
      }).catch(fail).then(function () { btn.disabled = false; });
    } }));
  }

  function drawBanners() {
    var b = clear($('state'));
    if (!S.space.joined) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: memberName(S.space.holder) + ' asks you into “' + (S.doc.fields.title || 'this page') + '”. Join to see it live and work on it.' }),
        el('button', { type: 'button', class: 'primary', text: 'Join', onclick: function () { act('join').then(function () { toast('Joined.'); }).catch(fail); } })]));
    } else if (S.holder_off && S.space.standin_active) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: (S.space.standin_active === S.me.label ? 'Your Rouh' : shortName(S.space.standin_active) + '’s Rouh') + ' holds the page while ' + shortName(S.space.holder) + '’s Rouh is off. Everything goes back to it when it returns.' })]));
    } else if (S.holder_off) {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'The Rouh holding this page is off. Your changes show here and wait' + (S.pending ? ' (' + S.pending + ' waiting)' : '') + '; they go when it is back.' })]));
    } else if (S.space.state === 'ended') {
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'This space has ended. The page and its history stay to read.' })]));
    }
    if (past) {
      b.appendChild(el('div', { class: 'banner info lp-past' }, [el('p', { text: 'You are looking at the page as it was after change ' + past.seq + ' of ' + S.seq + '. The page as it stands is unchanged until you bring this version back.' }),
        canEdit() ? el('button', { type: 'button', text: 'Bring back this version', onclick: restore }) : null,
        el('button', { type: 'button', class: 'quiet', text: 'Back to now', onclick: leavePast })]));
    }
    if (following) {
      var p = presenceByActor()[following];
      b.appendChild(el('div', { class: 'banner info' }, [el('p', { text: 'Following ' + actorWords(following) + (p && p.part ? ', on ' + partName(p.part) : '') + '.' }),
        el('button', { type: 'button', text: 'Stop following', onclick: function () { following = ''; nudge(); draw(); } })]));
    }
  }

  function drawToolbar() {
    var c = $('commentMode');
    c.hidden = !canComment();
    if (!canComment() && commenting) setCommenting(false);
    c.disabled = !!past;
  }

  function draw() {
    if (!S) return;
    drawAtWork();
    var title = S.doc.fields.title || 'A live page';
    document.title = title + ' · live';
    $('title').textContent = title;
    $('kind').textContent = 'Live page' + (S.space.mine ? ', held by your Rouh' : ', held by ' + shortName(S.space.holder) + '’s Rouh') +
      (S.me.role && S.me.role !== 'owner' ? '. You are ' + (S.me.role === 'editor' ? 'an editor' : 'a ' + S.me.role) + ' here.' : '');
    $('liveLine').textContent = liveLine();
    drawWho();
    drawBanners();
    drawIntent();
    drawToolbar();
    drawFrame();
    sendMarks();
    sendCursors();
    follow();
    drawSource();
    drawMyRouh();
    drawComments();
    drawMembers();
    drawKeep();
    drawPickClaim();
    primaries();
    if (historyOpen && !past) { $('histRange').max = String(S.seq); $('histRange').value = String(S.seq); }
    else if (historyOpen) $('histRange').max = String(S.seq);
    $('work').hidden = !S.space.joined;
    if (!cur && live()) startCursors();   // only once in: before that, this Rouh has no cursors for it
  }

  function showGone() {
    dropFrames();
    clear($('main')).appendChild(el('div', { class: 'empty' }, [el('h2', { text: 'This page is not here' }),
      el('p', { text: 'Its space may have ended, or you were never asked into it.' }), el('a', { href: '/link', text: 'Back to Connections' })]));
  }

  // --- history ----------------------------------------------------------------------------------------

  var histT = null, histAsk = 0;
  function showAt(seq) {
    if (!S) return;
    if (seq >= S.seq) { leavePast(); return; }
    var mine = ++histAsk;
    API.get(base + '/history?seq=' + seq).then(function (h) {
      if (mine !== histAsk) return;
      var d = (h.doc && h.doc.html) || {};
      if (editing) stopEdit();
      closePick();
      past = { seq: seq, text: String(d.text || ''), by: d.by || [] };
      $('histSaid').textContent = 'As it was after change ' + seq + ' of ' + S.seq + '. The page shows it.';
      $('restore').disabled = !canEdit();
      $('stage').classList.add('past');
      draw();
      if (cur) { cur.move({ part: '' }); if (mySel) { mySel = ''; cur.select(null); } }
    }).catch(fail);
  }
  function leavePast() {
    if (!past) { $('histSaid').textContent = 'Now.'; $('restore').disabled = true; return; }
    past = null;
    $('stage').classList.remove('past');
    $('histSaid').textContent = 'Now.';
    $('restore').disabled = true;
    if (historyOpen && S) $('histRange').value = String(S.seq);
    draw();
  }
  function restore() {
    if (!past || !canEdit()) return;
    var to = past.seq;
    send([op('restore', { to: to })]).then(function (got) {
      if (got && !(got.refused || []).length) toast('Brought back the version from change ' + to + '. Comments and claims stay.');
      leavePast();
    });
  }

  // --- wiring -----------------------------------------------------------------------------------------

  function loadPeers() {
    API.get('/api/link').then(function (st) {
      var sel = clear($('inviteWho'));
      var ok = (st.peers || []).filter(function (p) { return p.state === 'connected'; });
      if (!ok.length) sel.appendChild(el('option', { value: '', text: 'No connected Rouh yet' }));
      ok.forEach(function (p) { sel.appendChild(el('option', { value: p.label, text: p.name + ' (' + p.trust_word + ')' })); });
    }).catch(function () {});
  }

  function openLog() {
    API.get(base + '/log').then(function (got) {
      var d = $('logDrawer'); d.hidden = false; $('scrim').hidden = false;
      var ul = clear($('logList'));
      (got.entries || []).slice().reverse().forEach(function (e) {
        var when = new Date(e.at * 1000);
        ul.appendChild(el('li', {}, [el('span', { class: 'when', text: when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' + when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }),
          el('span', { text: e.plain })]));
      });
      if (!(got.entries || []).length) ul.appendChild(el('li', { class: 'dim', text: 'Nothing yet.' }));
      $('logClose').focus();
    }).catch(fail);
  }
  function closeLog() { $('logDrawer').hidden = true; $('scrim').hidden = true; }

  function wire() {
    $('rouhAsk').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var w = $('rouhWords').value.trim(); if (!w) return;
      $('rouhGo').disabled = true;
      act('rouh', { words: w }).then(function () { $('rouhWords').value = ''; toast('Your Rouh is on it.'); })
        .catch(fail).then(function () { $('rouhGo').disabled = false; });
    });
    $('skip').addEventListener('click', function () { act('skip').catch(fail); });
    $('stopRouh').addEventListener('click', function () { act('stop').catch(fail); });
    $('viewPage').addEventListener('click', function () { setView('page'); });
    $('viewBoth').addEventListener('click', function () { setView('both'); });
    $('viewSource').addEventListener('click', function () { setView('source'); });
    wide.addEventListener('change', function () { setView(view); });
    $('commentMode').addEventListener('click', function () { setCommenting(!commenting); });
    $('editSource').addEventListener('click', startEdit);
    $('sourceEdit').addEventListener('submit', saveSource);
    $('sourceCancel').addEventListener('click', cancelEdit);
    $('pickBox').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var t = $('pickWords').value.trim();
      if (!t || !picked) { $('pickWords').focus(); return; }
      var part = picked;
      $('pickPin').disabled = true;
      send([op('comment', { cid: uid(), part: part, text: t.slice(0, 2000) })]).then(function (got) {
        if (got && !(got.refused || []).length) { closePick(); toast('Pinned your comment.'); }
      }).then(function () { $('pickPin').disabled = false; });
    });
    $('pickClose').addEventListener('click', closePick);
    $('pickClaim').addEventListener('click', function () {
      if (!picked || !canEdit()) return;
      var whole = 'el:' + picked.split(':')[1];
      var claim = (S.doc.claims || {})[whole];
      send([op(claim ? 'release' : 'claim', { part: whole })]).then(function (got) {
        if (got && !(got.refused || []).length) toast(claim ? 'Let go of ' + partName(whole) + '.' : 'Claimed ' + partName(whole) + '. No other Rouh changes it until you let go.');
      });
    });
    $('histToggle').addEventListener('click', function () {
      historyOpen = !historyOpen;
      $('hist').hidden = !historyOpen;
      $('histToggle').setAttribute('aria-expanded', historyOpen ? 'true' : 'false');
      $('histToggle').textContent = historyOpen ? 'Hide' : 'Show';
      if (historyOpen) { $('histRange').max = String(S.seq); $('histRange').value = String(S.seq); $('histSaid').textContent = 'Now.'; }
      else leavePast();
    });
    $('histRange').addEventListener('input', function () {
      clearTimeout(histT);
      var v = +$('histRange').value;
      histT = setTimeout(function () { showAt(v); }, 150);
    });
    $('restore').addEventListener('click', restore);
    $('logOpen').addEventListener('click', openLog);
    $('inviteBox').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var label = $('inviteWho').value; if (!label) return;
      act('invite', { label: label, role: $('inviteRole').value }).then(function (got) { toast('Asked ' + got.label + ' in, as ' + got.role + '.'); }).catch(fail);
    });
    $('leave').addEventListener('click', function () {
      act('leave').then(function () { location.href = '/link'; }).catch(fail);
    });
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      if (!$('logDrawer').hidden) closeLog();
      else if (picked) closePick();
      else if (commenting) setCommenting(false);
    });
    loadPeers();
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('logClose').addEventListener('click', closeLog);
    $('scrim').addEventListener('click', closeLog);
    $('themeSwitch').addEventListener('click', function () {
      var root = document.documentElement;
      var dark = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
      root.setAttribute('data-theme', dark ? 'light' : 'dark');
      try { localStorage.setItem('link-theme', root.getAttribute('data-theme')); } catch (e) {}
      sendMarks(true);
      sendCursors(true);
      drawSourceSel();
    });
    try { var th = localStorage.getItem('link-theme'); if (th) document.documentElement.setAttribute('data-theme', th); } catch (e) {}
    setView(wide.matches ? 'both' : 'page');
    wire();
    loadBridge().catch(function () {});
    poll();
  });
})();
