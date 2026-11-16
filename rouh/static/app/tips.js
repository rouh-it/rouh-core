/* The composer's tooltips: what each button does and its key, after a short wait.
 *
 * Petar, 16 November 2026: the line of keys under the box took room at the bottom, so "put the
 * keyboard shortcuts on a delayed tooltip along with the explanation of what each button does". A
 * button on the composer's line says what it does in `data-tip` (and its key, when it has one, in
 * `data-key`); one that sets its `title` as it changes (the microphone, Send, the model) has it moved
 * into `data-tip` as it is set, so the browser's own tooltip, which comes late and never on a focus
 * from the keyboard, is never drawn over this one. Shown 600 ms after the pointer rests on a button or
 * the keyboard brings the focus to it, gone the moment either leaves, a button is pressed or Escape
 * is pressed. Outside the chain, like app/reading.js, and imported by app.js after it.
 */
import { $ } from 'app/helpers.js';

var WAIT = 600;
var line = $('composerControls');
var tip = document.createElement('div');
tip.className = 'composer-tip';
tip.id = 'composerTip';
tip.setAttribute('role', 'tooltip');
tip.hidden = true;
document.body.appendChild(tip);
var TIP = { timer: 0, on: /** @type {HTMLElement | null} */ (null) };

/** The button's title, moved to `data-tip`. @param {Element} b */
function adopt(b) {
  var t = b.getAttribute('title');
  if (t == null) return;
  if (t) /** @type {HTMLElement} */ (b).dataset.tip = t;
  b.removeAttribute('title');
}

function hide() {
  clearTimeout(TIP.timer);
  tip.hidden = true;
  if (TIP.on) TIP.on.removeAttribute('aria-describedby');
  TIP.on = null;
}

/** @param {HTMLElement} b */
function show(b) {
  var words = b.dataset.tip || '';
  if (!words || !document.contains(b) || b.offsetParent === null) return;
  tip.textContent = words;
  if (b.dataset.key && words.indexOf(b.dataset.key) < 0) {
    var k = document.createElement('kbd');
    k.textContent = b.dataset.key;
    tip.appendChild(document.createTextNode(' '));
    tip.appendChild(k);
  }
  tip.hidden = false;
  var r = b.getBoundingClientRect();
  var w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.round(Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2))) + 'px';
  var above = r.top - h - 8;
  tip.style.top = Math.round(above >= 8 ? above : r.bottom + 8) + 'px';
  TIP.on = b;
  b.setAttribute('aria-describedby', 'composerTip');
}

/** @param {HTMLElement | null} b */
function soon(b) {
  hide();
  if (!b) return;
  TIP.timer = window.setTimeout(function () { show(b); }, WAIT);
}

if (line) {
  line.querySelectorAll('[title]').forEach(adopt);
  new MutationObserver(function (changes) {
    changes.forEach(function (c) {
      if (c.type === 'attributes') adopt(/** @type {Element} */ (c.target));
      else c.addedNodes.forEach(function (n) {
        if (n.nodeType !== 1) return;
        var e = /** @type {Element} */ (n);
        if (e.hasAttribute('title')) adopt(e);
        e.querySelectorAll('[title]').forEach(adopt);
      });
    });
  }).observe(line, { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] });

  /** @param {Event} e */
  function target(e) {
    var t = /** @type {Element | null} */ (e.target instanceof Element ? e.target : null);
    var b = t ? /** @type {HTMLElement | null} */ (t.closest('[data-tip]')) : null;
    return b && line && line.contains(b) ? b : null;
  }
  line.addEventListener('pointerover', function (e) {
    if (/** @type {PointerEvent} */ (e).pointerType === 'touch') return;
    var b = target(e);
    if (b !== TIP.on) soon(b);
  });
  line.addEventListener('pointerleave', hide);
  line.addEventListener('pointerdown', hide);
  line.addEventListener('focusin', function (e) {
    var b = target(e);
    if (b && b.matches(':focus-visible')) soon(b); else hide();
  });
  line.addEventListener('focusout', hide);
  window.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); }, true);
  window.addEventListener('scroll', hide, true);
}
