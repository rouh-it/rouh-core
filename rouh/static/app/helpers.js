/* Rouh's page, small helpers (section 1 of what was one app.js).
 *
 * The first module: nothing runs before it. app.js says how the modules are
 * put in order.
 */
/* ------------------------------------------------------------------ 1 */

// An element by its id. `any`, because each caller knows which kind of element
// that id is and uses it as one - an input's value, a canvas's context - and
// a cast at every one of a few thousand calls would say nothing the id does not.
/** @type {(id: string) => any} */
var $ = function (id) { return document.getElementById(id); };

/**
 * @template {string} K
 * @param {K} tag
 * @param {string | null} [cls]
 * @param {unknown} [text]
 * @returns {K extends keyof HTMLElementTagNameMap ? HTMLElementTagNameMap[K] : HTMLElement}
 */
function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = String(text);
  return /** @type {any} */ (n);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

/* A silo as a small chip: its colour as a dot and its name (rouh/silos.py). `c`
   is {key, name, colour}, the colour as #rrggbb; a page that lists a thing's
   label draws one per silo, in the account's order. */
/**
 * @param {{key?: string, name?: string, colour?: string}} c
 * @returns {HTMLSpanElement}
 */
function siloChip(c) {
  var chip = el('span', 'silo-chip');
  if (c && /^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
  if (c && c.key) chip.setAttribute('data-silo', c.key);
  chip.appendChild(el('span', 'silo-dot'));
  chip.appendChild(el('span', 'silo-name', (c && c.name) || ''));
  return chip;
}

/* A thing's label as chips in a row, or nothing when it is in no silo. */
/**
 * @param {Array<{key?: string, name?: string, colour?: string}>} list
 * @param {string} [cls]
 * @returns {HTMLSpanElement | null}
 */
function siloChips(list, cls) {
  if (!list || !list.length) return null;
  var row = el('span', 'silo-chips' + (cls ? ' ' + cls : ''));
  row.setAttribute('aria-label', 'Silos: ' + list.map(function (c) { return c.name; }).join(', '));
  list.forEach(function (c) { row.appendChild(siloChip(c)); });
  return row;
}

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

function now() { return Date.now(); }

function safeParse(s) { try { return JSON.parse(s); } catch (e) { return null; } }

function hexToRgb(h) {
  h = String(h).trim();
  var m = /^#?([0-9a-f]{6})$/i.exec(h);
  if (m) {
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  var m2 = /rgba?\(([^)]+)\)/i.exec(h);
  if (m2) {
    var p = m2[1].split(',').map(function (x) { return parseInt(x, 10) || 0; });
    return [p[0] || 0, p[1] || 0, p[2] || 0];
  }
  return [94, 194, 255];
}

/* A link in Rouh is a link (fr_dd6276f8a9d6).

   Petar, 5 October 2026: "The links are still not clickable with Command so
   they open in a new tab, or by right-clicking and opening in a new tab.
   Maybe that's because they're not links". They were not: the sidebar's
   Task browser, Runs, Reminders and the rest were buttons, and a button has
   no address for a browser to open anywhere else. The fix of 2 October
   (a6300990) was for links inside a framed page, and never reached these.

   So whatever takes the person somewhere is an `<a href>` at the address of
   where it goes, made one here, and this is the whole of how it behaves:

   - a plain press stays in this tab and does exactly what the control
     always did - the address is not loaded, the page's own handler opens
     the place the way it always has;
   - Cmd, Ctrl or Shift held, or the middle button, is the browser's: the
     press never reaches this page's handlers, so the tab the person is in
     does not move, and the browser opens the address in a new tab or
     window the way it opens any link;
   - right-click has Open link in new tab, Copy link address and the rest,
     because it is a link.

   Alt is not in the list: on a link it downloads the page, which is never
   what anybody pressing a row meant. A link whose address depends on what
   is on the screen - the conversation beside a place, Rouh's own chat once
   its id is known - is handed a function, and its address is read again
   whenever a pointer comes over it, it is focused or it is pressed, so the
   one in the status bar, the menu and the new tab is always the current
   one.

   One control can go somewhere at one time and do something at another:
   the chip at the top of a conversation opens the task or the project the
   chat is in, and on Rouh's own chat it opens Search. With no address it
   is a button for as long as it has none - its role, a place in the Tab
   order, and Enter and Space pressing it - so it is never a link to
   nowhere. */
var LINK_HREF = new WeakMap();

/**
 * @template {HTMLElement} T
 * @param {T} a an `<a>`
 * @param {string | (() => string)} href where it goes, or how to work it out
 * @returns {T}
 */
function linkTo(a, href) {
  a.setAttribute('data-inapp', '');
  if (typeof href === 'function') {
    LINK_HREF.set(a, href);
    linkFresh(a);
  } else {
    LINK_HREF.delete(a);
    linkSet(a, href);
  }
  return a;
}

/** @param {Element} a */
function linkFresh(a) {
  var f = LINK_HREF.get(a);
  if (!f) return;
  var h = '';
  try { h = f() || ''; } catch (err) {}
  linkSet(a, h);
}

/** @param {Element} a @param {string} h */
function linkSet(a, h) {
  if (h) {
    if (a.getAttribute('href') !== h) a.setAttribute('href', h);
    if (a.getAttribute('role') === 'button') {
      a.removeAttribute('role');
      a.removeAttribute('tabindex');
    }
    return;
  }
  a.removeAttribute('href');
  if (!a.hasAttribute('role')) {
    a.setAttribute('role', 'button');
    a.setAttribute('tabindex', '0');
  }
}

/** @param {MouseEvent} e */
function browserTakes(e) {
  return !!(e.button || e.metaKey || e.ctrlKey || e.shiftKey);
}

/** @param {Event} e @returns {Element | null} */
function inAppLink(e) {
  var t = /** @type {Element} */ (e.target);
  return t && t.closest ? t.closest('a[data-inapp]') : null;
}

// On the window and in capture, so it is first: nothing of this page's own
// sees a press the browser is to have. That holds for every link on the
// page, not only the ones made here: the quests, the heartbeat, the beats
// and payments draw their own `<a href>`s and took every press on them,
// Cmd's too, and a link pressed with Cmd is the browser's whoever drew it.
// A plain press is the page's only on the links made by `linkTo`; any other
// link goes on doing what its own handler, or the browser, does with it.
window.addEventListener('click', function (e) {
  var t = /** @type {Element} */ (e.target);
  var a = t && t.closest ? t.closest('a[href]') : null;
  if (!a) return;
  var href = a.getAttribute('href') || '';
  if (!href || href.charAt(0) === '#' || /^javascript:/i.test(href)) return;
  // A button on a card that is a link (a run's archive, its dots) is that
  // button's press, held keys and all, and never the link's: Chrome follows
  // the link around a button pressed with Shift unless it is told not to.
  var inner = t.closest('button, input, select, textarea, label');
  if (inner && a.contains(inner)) { e.preventDefault(); return; }
  if (browserTakes(e)) { e.stopImmediatePropagation(); return; }
  if (a.hasAttribute('data-inapp')) e.preventDefault();
}, true);
// A link with no address for now is a button, and a button is pressed from
// the keyboard as well (`linkSet`). Last, on the way back up, so a control
// that already answers its own keys (a run's card) is not pressed twice.
window.addEventListener('keydown', function (e) {
  if ((e.key !== 'Enter' && e.key !== ' ') || e.defaultPrevented) return;
  var t = /** @type {Element} */ (e.target);
  if (!t || !t.matches || !t.matches('a[data-inapp][role="button"]')) return;
  e.preventDefault();
  /** @type {HTMLElement} */ (t).click();
});
['pointerover', 'focusin', 'pointerdown', 'contextmenu'].forEach(function (type) {
  window.addEventListener(type, function (e) {
    var a = inAppLink(e);
    if (a) linkFresh(a);
  }, true);
});

/* Whether the navigation is a drawer laid over the page rather than a column
   beside it, and so the orb's circle is the menu button (`sbSize` in
   app/controls.js, `orbMenuButton` in app/orb.js, and the drawer layout at
   the foot of app.css). It is, at every width, since 12 October 2026.

   It was a phone's alone, then a tablet's too and any window under 1100
   pixels (Petar, 10 October 2026: "Can you just extend whatever we did for
   mobile to be valid for tablet too?"), and a desk kept the docked column
   with the orb in the top left corner. Petar, 12 October 2026
   (fr_9133d49e9c12): "menu on the desktop should be the same as mobile. Orb
   is down and is used as open menu button. navigation slides the same way,
   same organization of content." So a desk is a drawer too, and the one
   question every caller asks always has the one answer. */
function drawerLayout() {
  return true;
}

export { $, browserTakes, clamp, drawerLayout, el, esc, hexToRgb, inAppLink, linkFresh, linkTo, now, safeParse, siloChip, siloChips };
