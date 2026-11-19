// The bridge inside a Live page's frame (Rouh Link, task 189; LIVE-PAGE in LINK.md).
//
// `link/livepage.js` puts this text, as it is, into the sealed frame's srcdoc before the page's own
// source, and calls it with where the viewer was: `(this)({x, y, mode, marks})`. So it runs before
// any of the page's own script. The frame is `sandbox="allow-scripts"` with no same origin and a
// policy that allows no network at all; this is the only thing in it that talks to the person's
// screen, and it does so only by postMessage, in the fixed shapes of `{rouh: "live-page-1", ...}`.
//
// What it does: puts the viewer's scroll back, draws each member's marker, claim and comment pin
// over the element it is on (a layer of its own, in a closed shadow root), says which element is
// under the person's pointer and where in it, what words they selected and where they tapped, draws
// the other people's live cursors (an arrow with a name, a tap ring, a selection band), and in
// comment mode turns a click into a pick of a spot. Whatever the
// page says or does, it can send the screen nothing but these hints, and the screen treats them as
// hints for its own drawing only: nothing a page sends changes the space or asks a Rouh.
//
// This file has no trailing semicolon on purpose: livepage.js appends the call.
(function (start) {
  'use strict';
  var TAG = 'live-page-1';
  var W = window, D = document, P = W.parent;
  var send = function (m) { m.rouh = TAG; try { P.postMessage(m, '*'); } catch (e) {} };

  // Nothing in here may open a way out: no peer connections (the one road a policy cannot close).
  ['RTCPeerConnection', 'webkitRTCPeerConnection', 'mozRTCPeerConnection', 'RTCDataChannel',
    'RTCSessionDescription', 'RTCIceCandidate', 'RTCRtpSender', 'RTCRtpReceiver'].forEach(function (k) {
    try { Object.defineProperty(W, k, { value: undefined, writable: false, configurable: false }); } catch (e) {}
  });
  try { if (W.navigator && W.navigator.mediaDevices) Object.defineProperty(W.navigator, 'mediaDevices', { value: undefined }); } catch (e) {}

  var ID = /^[A-Za-z0-9_-]{1,40}$/;
  var COLOUR = /^#[0-9a-fA-F]{3,8}$/;
  var KINDS = { rouh: 1, person: 1, claim: 1, comment: 1, intent: 1 };
  var mode = start && start.mode === 'comment' ? 'comment' : 'view';
  var marks = [];
  var cursors = {};          // id -> {c: the last sample, at: when it came, x, y: where it is drawn now, node: its div}

  function num(v, lo, hi) { v = Number(v); return isFinite(v) ? Math.max(lo, Math.min(hi, v)) : lo; }
  function short(v, n) { return String(v == null ? '' : v).slice(0, n); }

  // --- the viewer's scroll, first ------------------------------------------------------------------
  var want = start ? { x: num(start.x, 0, 1e7), y: num(start.y, 0, 1e7) } : null;
  function restore() { if (want && (want.x || want.y)) W.scrollTo(want.x, want.y); }
  restore();

  // --- the layer the marks are drawn on -----------------------------------------------------------
  var host = null, root = null, hoverBox = null, curLayer = null;
  function layer() {
    if (host && host.isConnected) return root;
    host = D.createElement('rouh-live-marks');
    host.setAttribute('aria-hidden', 'true');
    host.style.cssText = 'all:initial;position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;display:block';
    root = host.attachShadow ? host.attachShadow({ mode: 'closed' }) : host;
    var st = D.createElement('style');
    st.textContent = '.box{position:absolute;box-sizing:border-box;border:2px solid var(--c);border-radius:4px;pointer-events:none}' +
      '.box.claim{border-style:dashed}.box.hover{border:2px dashed #36dce5;background:rgba(54,220,229,.08)}' +
      '.lab{position:absolute;left:-2px;bottom:100%;margin-bottom:2px;font:600 12px/18px system-ui,-apple-system,"Segoe UI",sans-serif;' +
      'padding:0 7px;border-radius:5px;background:var(--c);color:#0b1114;white-space:nowrap;max-width:280px;overflow:hidden;text-overflow:ellipsis}' +
      '.lab.below{bottom:auto;top:100%;margin:2px 0 0}.box.person .lab{border-radius:9px}' +
      '.pin{position:absolute;width:26px;height:26px;margin:-26px 0 0 -2px;border-radius:13px 13px 13px 2px;background:var(--c);color:#0b1114;' +
      'font:700 12px/26px system-ui,-apple-system,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.35);pointer-events:none}' +
      '.cur{position:absolute;left:0;top:0;pointer-events:none;transition:opacity .4s;will-change:transform}.cur.idle{opacity:0}' +
      '.cur svg{position:absolute;left:-2px;top:-2px;width:20px;height:22px;overflow:visible;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}' +
      '.cur .name{position:absolute;left:14px;top:18px;font:600 12px/20px system-ui,-apple-system,"Segoe UI",sans-serif;padding:0 8px;' +
      'border-radius:10px;background:var(--c);white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis;box-shadow:0 1px 3px rgba(0,0,0,.3)}' +
      '.ring{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;border:3px solid var(--c);border-radius:50%;box-sizing:border-box;' +
      'pointer-events:none;animation:rouh-ring 2s ease-out forwards}' +
      '@keyframes rouh-ring{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}' +
      '.band{position:absolute;pointer-events:none;background:var(--c);opacity:.25;border-radius:2px}' +
      '.caret{position:absolute;width:2px;margin-left:-1px;background:var(--c);pointer-events:none}' +
      '.caret .name{position:absolute;left:-1px;bottom:100%;font:600 11px/16px system-ui,-apple-system,sans-serif;padding:0 6px;' +
      'border-radius:4px 4px 4px 0;background:var(--c);white-space:nowrap;max-width:160px;overflow:hidden;text-overflow:ellipsis}' +
      '@media (prefers-reduced-motion:reduce){.cur{transition:none}.ring{animation:rouh-ring-still 2s linear forwards}' +
      '@keyframes rouh-ring-still{from{opacity:1}to{opacity:0}}}';
    root.appendChild(st);
    hoverBox = D.createElement('div');
    hoverBox.className = 'box hover';
    hoverBox.style.display = 'none';
    root.appendChild(hoverBox);
    curLayer = D.createElement('div');
    root.appendChild(curLayer);
    (D.body || D.documentElement).appendChild(host);
    return root;
  }

  function find(id) { return ID.test(id) ? D.querySelector('[data-rouh-id="' + id + '"]') : null; }
  function boxOf(node) {
    var r = node.getBoundingClientRect();
    return { x: r.left + W.scrollX, y: r.top + W.scrollY, w: r.width, h: r.height };
  }

  // Dark words on a light colour, white on a dark one, so a label reads in either theme.
  function ink(hex) {
    var h = hex.replace('#', '');
    if (h.length < 6) h = h.split('').map(function (c) { return c + c; }).join('');
    var lin = function (i) { var c = parseInt(h.substr(i, 2), 16) / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    var L = 0.2126 * lin(0) + 0.7152 * lin(2) + 0.0722 * lin(4);
    return L > 0.18 ? '#0b1114' : '#ffffff';
  }

  var drawn = [];
  function draw() {
    var R = layer();
    drawn.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    drawn = [];
    marks.forEach(function (m) {
      var bits = m.part.split(':');
      var node = find(bits[1]);
      if (!node) return;
      var b = boxOf(node);
      if (m.kind === 'comment' && bits.length === 4) {
        var pin = D.createElement('div');
        pin.className = 'pin';
        pin.style.setProperty('--c', m.colour);
        pin.style.left = (b.x + b.w * num(bits[2], 0, 1000) / 1000) + 'px';
        pin.style.top = (b.y + b.h * num(bits[3], 0, 1000) / 1000) + 'px';
        pin.textContent = String(m.n || '');
        pin.style.color = ink(m.colour);
        R.appendChild(pin); drawn.push(pin);
        return;
      }
      var box = D.createElement('div');
      box.className = 'box ' + m.kind;
      box.style.setProperty('--c', m.colour);
      box.style.left = (b.x - 3) + 'px'; box.style.top = (b.y - 3) + 'px';
      box.style.width = (b.w + 6) + 'px'; box.style.height = (b.h + 6) + 'px';
      if (m.who) {
        var lab = D.createElement('div');
        lab.className = 'lab' + (b.y < 24 ? ' below' : '');
        lab.textContent = m.who;
        lab.style.color = ink(m.colour);
        box.appendChild(lab);
      }
      R.appendChild(box); drawn.push(box);
    });
  }
  var queued = false;
  function soon() { if (queued) return; queued = true; requestAnimationFrame(function () { queued = false; draw(); }); }

  function setMode(m) {
    mode = m === 'comment' ? 'comment' : 'view';
    var st = D.getElementById('rouh-live-mode');
    if (mode === 'comment') {
      if (!st) { st = D.createElement('style'); st.id = 'rouh-live-mode'; st.textContent = '*{cursor:crosshair!important}'; (D.head || D.documentElement).appendChild(st); }
    } else {
      if (st) st.remove();
      if (hoverBox) hoverBox.style.display = 'none';
    }
  }

  function cleanMarks(list) {
    if (!Array.isArray(list)) return [];
    var out = [];
    list.slice(0, 300).forEach(function (m) {
      if (!m || typeof m !== 'object') return;
      var part = short(m.part, 120);
      var bits = part.split(':');
      if (bits[0] !== 'el' || !ID.test(bits[1] || '') || (bits.length !== 2 && bits.length !== 4)) return;
      var colour = COLOUR.test(String(m.colour)) ? String(m.colour) : '#a3b1b6';
      out.push({ part: part, who: short(m.who, 80), colour: colour, kind: KINDS[m.kind] ? m.kind : 'person', n: num(m.n, 0, 9999) });
    });
    return out;
  }

  // --- the other people's live cursors ------------------------------------------------------------
  // Each is a person's pointer on an element, as fractions of its box, and maybe their selection in
  // it. Drawn eased toward each new point every frame, so 15 samples a second look smooth; faded after
  // 4 seconds without a new one; gone on `gone`, after 30 seconds, or while its element is not here.
  var SID = /^[A-Za-z0-9_:.-]{1,80}$/;
  function elPart(v) { var p = short(v, 44); return /^el:[A-Za-z0-9_-]{1,40}$/.test(p) ? p : ''; }
  function cleanCursors(list) {
    if (!Array.isArray(list)) return [];
    var out = [];
    list.slice(0, 40).forEach(function (c) {
      if (!c || typeof c !== 'object' || !SID.test(String(c.id))) return;
      var one = { id: String(c.id), name: short(c.name, 40), part: elPart(c.part), x: num(c.x, 0, 1), y: num(c.y, 0, 1),
        colour: COLOUR.test(String(c.colour)) ? String(c.colour) : '#a3b1b6', tap: c.tap === true, gone: c.gone === true,
        age: num(c.age, 0, 3600), sel: null };
      var s = c.sel;
      if (s && typeof s === 'object' && elPart(s.part)) one.sel = { part: elPart(s.part), a: Math.round(num(s.a, 0, 2e6)), f: Math.round(num(s.f, 0, 2e6)) };
      out.push(one);
    });
    return out;
  }
  function takeCursors(list) {
    var now = Date.now(), seen = {};
    list.forEach(function (c) {
      seen[c.id] = true;
      var had = cursors[c.id];
      if (c.gone) { if (had) dropCursor(c.id); return; }
      var at = now - c.age * 1000;
      var fresh = !had || had.c.part !== c.part || had.c.x !== c.x || had.c.y !== c.y || had.c.tap !== c.tap;
      if (had) { had.c = c; had.at = at; } else cursors[c.id] = { c: c, at: at, x: null, y: null, node: null };
      if (c.tap && fresh && now - at < 2500) ring(c);
    });
    Object.keys(cursors).forEach(function (id) { if (!seen[id]) dropCursor(id); });
    tick();
  }
  function dropCursor(id) {
    var k = cursors[id];
    if (k && k.node && k.node.parentNode) k.node.parentNode.removeChild(k.node);
    if (k && k.marks) k.marks.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    delete cursors[id];
  }
  function arrow(colour) {
    var NS = 'http://www.w3.org/2000/svg';
    var s = D.createElementNS(NS, 'svg');
    s.setAttribute('viewBox', '0 0 20 22');
    var p = D.createElementNS(NS, 'path');
    p.setAttribute('d', 'M2 2 L2 18 L6.5 14 L9.5 20.5 L12.5 19.2 L9.6 12.8 L15.5 12.6 Z');
    p.setAttribute('fill', colour); p.setAttribute('stroke', '#ffffff'); p.setAttribute('stroke-width', '1.6'); p.setAttribute('stroke-linejoin', 'round');
    s.appendChild(p);
    return s;
  }
  function firstName(n) { return String(n || '').split(' \u00b7')[0].trim().split(/\s+/)[0] || 'Someone'; }
  function cursorNode(k) {
    if (k.node && k.node.isConnected && k.node._colour === k.c.colour && k.node._name === k.c.name) return k.node;
    if (k.node && k.node.parentNode) k.node.parentNode.removeChild(k.node);
    var d = D.createElement('div');
    d.className = 'cur';
    d.style.setProperty('--c', k.c.colour);
    d.appendChild(arrow(k.c.colour));
    var lab = D.createElement('div');
    lab.className = 'name';
    lab.textContent = firstName(k.c.name);
    lab.style.color = ink(k.c.colour);
    d.appendChild(lab);
    d._colour = k.c.colour; d._name = k.c.name;
    layer(); curLayer.appendChild(d);
    return (k.node = d);
  }
  function ring(c) {
    var node = find(c.part.split(':')[1] || '');
    if (!node) return;
    var b = boxOf(node);
    layer();
    var r = D.createElement('div');
    r.className = 'ring';
    r.style.setProperty('--c', c.colour);
    r.style.left = (b.x + b.w * c.x) + 'px'; r.style.top = (b.y + b.h * c.y) + 'px';
    curLayer.appendChild(r);
    setTimeout(function () { if (r.parentNode) r.parentNode.removeChild(r); }, 2100);
  }
  // Where the text offsets of an element are, as a Range over its text nodes.
  function rangeIn(node, a, f) {
    var w = D.createTreeWalker(node, 4, null), t, at = 0, lo = Math.min(a, f), hi = Math.max(a, f), r = D.createRange();
    var start = null, end = null, last = null;
    while ((t = w.nextNode())) {
      var len = t.data.length;
      if (!start && lo <= at + len) start = [t, lo - at];
      if (!end && hi <= at + len) { end = [t, hi - at]; break; }
      at += len; last = t;
    }
    if (!start) { if (!last) return null; start = [last, last.data.length]; }
    if (!end) end = last ? [last, last.data.length] : start;
    try { r.setStart(start[0], start[1]); r.setEnd(end[0], end[1]); } catch (e) { return null; }
    return r;
  }
  function drawSel(k) {
    (k.marks || []).forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    k.marks = [];
    var s = k.c.sel;
    if (!s) return;
    var node = find(s.part.split(':')[1] || '');
    if (!node) return;
    var r = rangeIn(node, s.a, s.f);
    if (!r) return;
    var sx = W.scrollX, sy = W.scrollY;
    if (s.a !== s.f) Array.prototype.slice.call(r.getClientRects(), 0, 200).forEach(function (q) {
      if (q.width < 1 || q.height < 1) return;
      var b = D.createElement('div');
      b.className = 'band';
      b.style.setProperty('--c', k.c.colour);
      b.style.cssText += ';left:' + (q.left + sx) + 'px;top:' + (q.top + sy) + 'px;width:' + q.width + 'px;height:' + q.height + 'px';
      curLayer.appendChild(b); k.marks.push(b);
    });
    // The caret, at the focus end, with the name on it.
    var c = r.cloneRange();
    c.collapse(s.f <= s.a);
    var cr = c.getClientRects()[0] || c.getBoundingClientRect();
    if (!cr || (!cr.height && !cr.left && !cr.top)) { var nb = node.getBoundingClientRect(); cr = { left: nb.left, top: nb.top, height: Math.min(nb.height, 20) || 18 }; }
    var bar = D.createElement('div');
    bar.className = 'caret';
    bar.style.setProperty('--c', k.c.colour);
    bar.style.cssText += ';left:' + (cr.left + sx) + 'px;top:' + (cr.top + sy) + 'px;height:' + Math.max(14, cr.height) + 'px';
    var lab = D.createElement('div');
    lab.className = 'name';
    lab.textContent = firstName(k.c.name);
    lab.style.color = ink(k.c.colour);
    bar.appendChild(lab);
    curLayer.appendChild(bar); k.marks.push(bar);
  }
  var ticking = false, selAt = 0;
  function tick() { if (ticking) return; ticking = true; requestAnimationFrame(step); }
  function step() {
    ticking = false;
    var now = Date.now(), any = false, redoSel = now - selAt > 150;
    if (redoSel) selAt = now;
    Object.keys(cursors).forEach(function (id) {
      var k = cursors[id];
      if (now - k.at > 30000) { dropCursor(id); return; }
      any = true;
      if (redoSel) drawSel(k);
      var node = k.c.part ? find(k.c.part.split(':')[1]) : null;
      if (!node || k.c.tap) { if (k.node) k.node.style.display = 'none'; k.x = null; return; }
      var b = boxOf(node);
      var tx = b.x + b.w * k.c.x, ty = b.y + b.h * k.c.y;
      // Eased: a third of the way each frame; a jump when first seen, after hiding, or from far away.
      if (k.x == null || Math.abs(tx - k.x) + Math.abs(ty - k.y) > 1200) { k.x = tx; k.y = ty; }
      else { k.x += (tx - k.x) * 0.35; k.y += (ty - k.y) * 0.35; if (Math.abs(tx - k.x) < 0.3) k.x = tx; if (Math.abs(ty - k.y) < 0.3) k.y = ty; }
      var d = cursorNode(k);
      d.style.display = '';
      d.style.transform = 'translate(' + k.x.toFixed(1) + 'px,' + k.y.toFixed(1) + 'px)';
      d.classList.toggle('idle', now - k.at > 4000);
    });
    if (any) tick();
  }

  // --- what the screen says ----------------------------------------------------------------------
  W.addEventListener('message', function (ev) {
    if (ev.source !== P) return;
    var m = ev.data;
    if (!m || typeof m !== 'object' || m.rouh !== TAG) return;
    if (m.type === 'marks') { marks = cleanMarks(m.marks); soon(); }
    else if (m.type === 'cursors') takeCursors(cleanCursors(m.cursors));
    else if (m.type === 'mode') setMode(m.mode);
    else if (m.type === 'scroll') W.scrollTo(num(m.x, 0, 1e7), num(m.y, 0, 1e7));
    else if (m.type === 'reveal') {
      var node = find(String(m.part || '').split(':')[1] || '');
      if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, true);

  // --- what this side tells the screen ---------------------------------------------------------------
  function owner(t) {
    while (t && t.nodeType === 1) {
      var id = t.getAttribute('data-rouh-id');
      if (id && ID.test(id)) return t;
      t = t.parentElement;
    }
    return null;
  }
  // Where the pointer is: the element's id and the place in its box, as fractions, so it lands on the
  // same spot on any screen. At most 15 a second, the last one always going.
  var scrollT = 0, ptrT = 0, ptrAt = 0, ptrNext = null, ptrLast = '';
  function frac(v) { return Math.round(num(v, 0, 1) * 1000) / 1000; }
  function pointAt(ev) {
    var node = owner(ev.target);
    if (!node) return { part: '' };
    var r = node.getBoundingClientRect();
    return { part: 'el:' + node.getAttribute('data-rouh-id'), x: frac((ev.clientX - r.left) / (r.width || 1)), y: frac((ev.clientY - r.top) / (r.height || 1)) };
  }
  function sayPointer(p) {
    ptrNext = p;
    var wait = Math.max(0, 1000 / 15 - (Date.now() - ptrAt));
    if (ptrT) return;
    ptrT = setTimeout(function () {
      ptrT = 0;
      var q = ptrNext; ptrNext = null;
      if (!q) return;
      var k = q.part + ':' + q.x + ':' + q.y;
      if (k === ptrLast) return;
      ptrLast = k; ptrAt = Date.now();
      var msg = { type: 'pointer', part: q.part };
      if (q.part) { msg.x = q.x; msg.y = q.y; }
      send(msg);
    }, wait);
  }
  W.addEventListener('pointermove', function (ev) {
    var node = owner(ev.target);
    if (mode === 'comment' && hoverBox) {
      if (node) {
        var b = boxOf(node);
        hoverBox.style.cssText = 'left:' + (b.x - 2) + 'px;top:' + (b.y - 2) + 'px;width:' + (b.w + 4) + 'px;height:' + (b.h + 4) + 'px';
      } else hoverBox.style.display = 'none';
    }
    if (ev.pointerType === 'touch') return;   // a finger has no hover: it taps (below)
    sayPointer(pointAt(ev));
  }, true);
  // The pointer left the page: its arrow goes from everyone's screen.
  D.addEventListener('mouseleave', function () { sayPointer({ part: '' }); }, true);
  W.addEventListener('pointerout', function (ev) { if (!ev.relatedTarget && ev.pointerType !== 'touch') sayPointer({ part: '' }); }, true);
  W.addEventListener('blur', function () { sayPointer({ part: '' }); });
  W.addEventListener('pointerdown', function (ev) {
    if (ev.pointerType !== 'touch' || mode === 'comment') return;
    var p = pointAt(ev);
    if (p.part) send({ type: 'tap', part: p.part, x: p.x, y: p.y });
  }, true);

  // What the person selected: inside one element, as offsets in that element's text.
  function textOffset(within, node, off) {
    try {
      var r = D.createRange();
      r.setStart(within, 0);
      r.setEnd(node, off);
      return r.toString().length;
    } catch (e) { return -1; }
  }
  var selT = 0, selLast = JSON.stringify({ type: 'select', part: '' });   // a new frame has nothing selected: say nothing
  D.addEventListener('selectionchange', function () {
    clearTimeout(selT);
    selT = setTimeout(function () {
      var s = W.getSelection ? W.getSelection() : null;
      var msg = { type: 'select', part: '' };
      if (s && s.rangeCount && s.anchorNode && s.focusNode) {
        var common = s.getRangeAt(0).commonAncestorContainer;
        var node = owner(common.nodeType === 1 ? common : common.parentElement);
        if (node) {
          var a = textOffset(node, s.anchorNode, s.anchorOffset), f = textOffset(node, s.focusNode, s.focusOffset);
          if (a >= 0 && f >= 0) msg = { type: 'select', part: 'el:' + node.getAttribute('data-rouh-id'), a: a, f: f, q: String(s).slice(0, 300) };
        }
      }
      var k = JSON.stringify(msg);
      if (k === selLast) return;
      selLast = k;
      send(msg);
    }, 80);
  });

  W.addEventListener('scroll', function () {
    clearTimeout(scrollT);
    scrollT = setTimeout(function () { send({ type: 'scroll', x: Math.round(W.scrollX), y: Math.round(W.scrollY) }); }, 120);
  }, true);
  function pick(ev) {
    if (mode !== 'comment') return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    if (ev.type !== 'click') return;
    var node = owner(ev.target);
    if (!node) return;
    var r = node.getBoundingClientRect();
    var x = Math.round(num((ev.clientX - r.left) / (r.width || 1), 0, 1) * 1000);
    var y = Math.round(num((ev.clientY - r.top) / (r.height || 1), 0, 1) * 1000);
    send({ type: 'pick', part: 'el:' + node.getAttribute('data-rouh-id') + ':' + x + ':' + y });
  }
  ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'submit', 'auxclick', 'dblclick'].forEach(function (k) {
    W.addEventListener(k, pick, true);
  });
  W.addEventListener('resize', soon);
  if (W.ResizeObserver) { try { new W.ResizeObserver(soon).observe(D.documentElement); } catch (e) {} }
  setInterval(soon, 1000);

  function ready() {
    restore();
    marks = cleanMarks(start && start.marks);
    setMode(mode);
    draw();
    takeCursors(cleanCursors(start && start.cursors));
    send({ type: 'ready', h: Math.round(D.documentElement.scrollHeight || 0) });
    // Pictures and fonts can grow the page after the first drawing: put the scroll back once more.
    W.addEventListener('load', function () { restore(); soon(); });
    setTimeout(function () { want = null; }, 1500);
  }
  if (D.readyState === 'loading') D.addEventListener('DOMContentLoaded', ready, true); else ready();
})
