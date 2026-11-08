/* Today's focus, at the top of the navigation (`rouh/one_thing.py`, the one thing on the
 * morning brief, `briefpage.js`).
 *
 * Petar, 8 November 2026 (fr_7bfe96b7672b): "Once set for the day, I would like a spot that
 * will remind me of this. maybe in the navigation on the very top in some color? you come up
 * with an idea to match the purpose. if it is a task, I should be able to click it."
 *
 * So while a focus is set for today it stands in the brand's place in the sidebar's head, in
 * its own colour, with a target and the word Today: the task or sub task (which it opens),
 * the category, or his own words (which open the brief, where it is changed or cleared).
 * One focus a day, and only today's: the server hands back nothing once the day it was
 * picked for is over (`one_thing.chosen`), and this asks again whenever the page comes back
 * into view and every ten minutes, so a new morning starts with none.
 *
 * The brief tells it at once when the choice changes (`rouh:one-thing`, `oneThingSaid`).
 */
import { goToAddress } from 'app/cards.js';
import { sidebarDone } from 'app/controls.js';
import { $, browserTakes, linkTo } from 'app/helpers.js';

var chip = /** @type {HTMLAnchorElement | null} */ ($('focusChip'));
var nameEl = $('focusName');
var head = chip ? /** @type {HTMLElement | null} */ (chip.parentElement) : null;
var EVERY = 10 * 60 * 1000;

/**
 * @typedef {{ id?: string, name: string, href?: string, path?: string[] }} FocusPart
 * @typedef {{ text?: string, category?: FocusPart, task?: FocusPart | null,
 *             sub?: FocusPart | null }} Focus
 */

/** @param {Focus | null} one */
function show(one) {
  if (!chip || !nameEl || !head) return;
  var part = one && !one.text ? (one.sub || one.task || one.category || null) : null;
  var words = one ? (one.text || (part ? part.name : '')) : '';
  if (!words) {
    chip.hidden = true;
    head.classList.remove('has-focus');
    return;
  }
  var where = part && part.href ? part.href : '/brief';
  var what = one && one.text ? '' : one && one.sub ? 'sub task' : one && one.task ? 'task' : 'category';
  nameEl.textContent = words;
  linkTo(chip, where);
  var say = "Today's focus: " + words + (what ? ' (' + what + ')' : '') +
    (part && part.href ? '. Opens it.' : '. Opens the morning brief, where it is changed.');
  chip.setAttribute('aria-label', say);
  chip.title = say;
  chip.hidden = false;
  head.classList.add('has-focus');
}

function read() {
  if (!chip) return;
  fetch('/api/brief/one-thing?only=chosen', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (j) { if (j && j.ok) show(j.one_thing || null); })
    .catch(function () { /* offline: what it showed stays */ });
}

// A plain press opens it here, in the canvas, as every link of the navigation does; a press
// with Cmd or Ctrl is the browser's, a tab of its own.
if (chip) {
  chip.addEventListener('click', function (e) {
    if (browserTakes(e)) return;
    e.preventDefault();
    var href = chip.getAttribute('href');
    if (!href) return;
    sidebarDone();
    goToAddress(href);
  });
}

window.addEventListener('rouh:one-thing', function (e) {
  show(/** @type {CustomEvent} */ (e).detail || null);
});
document.addEventListener('visibilitychange', function () { if (!document.hidden) read(); });
setInterval(function () { if (!document.hidden) read(); }, EVERY);
read();

export { show as focusShow };
