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
// under the person's pointer, and in comment mode turns a click into a pick of a spot. Whatever the
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

  function num(v, lo, hi) { v = Number(v); return isFinite(v) ? Math.max(lo, Math.min(hi, v)) : lo; }
  function short(v, n) { return String(v == null ? '' : v).slice(0, n); }

  // --- the viewer's scroll, first ------------------------------------------------------------------
  var want = start ? { x: num(start.x, 0, 1e7), y: num(start.y, 0, 1e7) } : null;
  function restore() { if (want && (want.x || want.y)) W.scrollTo(want.x, want.y); }
  restore();

  // --- the layer the marks are drawn on -----------------------------------------------------------
  var host = null, root = null, hoverBox = null;
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
      'font:700 12px/26px system-ui,-apple-system,sans-serif;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.35);pointer-events:none}';
    root.appendChild(st);
    hoverBox = D.createElement('div');
    hoverBox.className = 'box hover';
    hoverBox.style.display = 'none';
    root.appendChild(hoverBox);
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

  // --- what the screen says ----------------------------------------------------------------------
  W.addEventListener('message', function (ev) {
    if (ev.source !== P) return;
    var m = ev.data;
    if (!m || typeof m !== 'object' || m.rouh !== TAG) return;
    if (m.type === 'marks') { marks = cleanMarks(m.marks); soon(); }
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
  var lastPart = '', lastSent = 0, scrollT = 0;
  W.addEventListener('pointermove', function (ev) {
    var node = owner(ev.target);
    if (mode === 'comment' && hoverBox) {
      if (node) {
        var b = boxOf(node);
        hoverBox.style.cssText = 'left:' + (b.x - 2) + 'px;top:' + (b.y - 2) + 'px;width:' + (b.w + 4) + 'px;height:' + (b.h + 4) + 'px';
      } else hoverBox.style.display = 'none';
    }
    var part = node ? 'el:' + node.getAttribute('data-rouh-id') : '';
    var now = Date.now();
    if (part !== lastPart && now - lastSent > 250) { lastPart = part; lastSent = now; send({ type: 'pointer', part: part }); }
  }, true);
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
    send({ type: 'ready', h: Math.round(D.documentElement.scrollHeight || 0) });
    // Pictures and fonts can grow the page after the first drawing: put the scroll back once more.
    W.addEventListener('load', function () { restore(); soon(); });
    setTimeout(function () { want = null; }, 1500);
  }
  if (D.readyState === 'loading') D.addEventListener('DOMContentLoaded', ready, true); else ready();
})
