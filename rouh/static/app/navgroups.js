/* Rouh's page, the navigation's rail of five group boxes and the links beside it.
 *
 * Outside the chain, like app/offlineview.js. app/runs.js and app/address.js
 * import it too, so it may run before the modules above them in the chain:
 * its top level touches nothing but the page's own markup and app/helpers.js,
 * and what it calls in the others it calls only when something is pressed.
 *
 * Petar, 12 October 2026: the orb, the close button, the dedicated area for
 * Rouh, Gene therapy, the profile row, the notifications and Search stay exactly
 * as they are; "What should change is only the organization of the links
 * above that with those group tabs", and the groups are a rail of stacked
 * boxes, each the group's glyph over its name, with the picked group's links
 * in a column beside it, from the sketch on card 1462 ("I like the sketch you
 * had with the vertically stacked boxes", the same day). The links and the
 * boxes are drawn by the server from
 * the gene registry (`rouh/genes`, one manifest per gene,
 * GENES.md), never written into the page, and the same registry comes as
 * JSON (`#rouhGenes`) for what is done here:
 *
 * - a box picks its group, and is remembered on this device (`rouh.navGroup`);
 *   which one shows on load is picked before the page is painted, by the
 *   little script beside the rail in index.html: the group of the page the
 *   address opens, else the one remembered, else Now;
 * - a link whose page has no code of its own for it (`data-opens`) goes to its
 *   route, as any link inside Rouh does, or presses the control it names, and
 *   is lit while its place is open (`navMark`);
 * - Now's count is how many decisions wait (`navNowCount`, from `decisionsRows`), there
 *   and nowhere else: never a number on the orb's circle (Petar, 4 November 2026);
 * - Search opens a gene it found (`geneGo`) and draws its glyph
 *   (`geneIcon`).
 */
import { $, linkTo } from 'app/helpers.js';
import { goToAddress } from 'app/cards.js';
import { sidebarDone } from 'app/controls.js';

var NAV_KEPT = 'rouh.navGroup';

/** @type {{groups: {id: string, name: string}[], anatomy: any[], moved: string[], genes: any[]}} */
var REG = { groups: [], anatomy: [], moved: [], genes: [] };
try {
  var raw = $('rouhGenes');
  if (raw) REG = JSON.parse(raw.textContent || '{}') || REG;
} catch (err) {}

/** @param {string} id */
function geneById(id) {
  for (var i = 0; i < REG.genes.length; i++) if (REG.genes[i].id === id) return REG.genes[i];
  return null;
}

function navTabs() {
  return /** @type {HTMLElement[]} */ (Array.prototype.slice.call(document.querySelectorAll('#sbTabs .sb-tab')));
}

/** Shows one group's links. Kept on this device when it was the person's own press.
    @param {string} group @param {boolean} [keep] */
function navGroupShow(group, keep) {
  if (!$('navTab-' + group)) return;
  navTabs().forEach(function (tab) {
    var g = tab.getAttribute('data-group') || '', on = g === group;
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    tab.tabIndex = on ? 0 : -1;
    var panel = $('navGroup-' + g);
    if (!panel) return;
    panel.toggleAttribute('data-off', !on);
    panel.toggleAttribute('inert', !on);
  });
  if (keep) {
    try { localStorage.setItem(NAV_KEPT, group); } catch (err) {}
  }
}

/* The count on Now: what waits on the person's answer, red while one is urgent.
   @param {number} count @param {boolean} urgent */
function navNowCount(count, urgent) {
  var badge = $('navNowCount');
  if (!badge) return;
  badge.hidden = !count;
  badge.textContent = count ? String(count) : '';
  badge.classList.toggle('urgent', !!urgent);
  var tab = $('navTab-now');
  if (tab) tab.setAttribute('aria-label', count ? 'Now, ' + count + ' waiting on you' : 'Now');
}

/* A link is lit while its place is open: the one whose route is the longest
   that the address starts with, so /settings/payments lights Payments and not
   Settings as well. Every link with a route, whether the page has code of its
   own for it or not: until 22 October 2026 only the ones without were, so the
   Task browser was never lit, opened from its own row or from its address
   (fr_35eeac6a7875). A link paired with a button beside it is lit as the
   pair, which is where the stylesheet looks.
   @param {string} path */
function navMark(path) {
  path = String(path || '').split('?')[0].split('#')[0].replace(/\/+$/, '');
  var rows = document.querySelectorAll('#sbGo [data-nav][href]'), best = null, len = 0, i;
  for (i = 0; i < rows.length; i++) {
    var r = rows[i].getAttribute('href') || '';
    if (r && (path === r || path.indexOf(r + '/') === 0) && r.length > len) { best = rows[i]; len = r.length; }
  }
  for (i = 0; i < rows.length; i++) (rows[i].closest('.sb-pair') || rows[i]).classList.toggle('on', rows[i] === best);
}

/* Opening a gene the way its manifest says, from a press on its link or
   from Search. @param {any} f the gene, as `#rouhGenes` has it */
function geneOpen(f) {
  if (!f) return;
  if (f.opens === 'press') {
    var target = $(f.press);
    if (target) /** @type {HTMLElement} */ (target).click();
    return;
  }
  if (f.opens === 'page') { location.assign(f.route); return; }
  if (f.route) {
    sidebarDone();
    goToAddress(f.route);
  }
}

/* Search's answer, pressed: the group it is in is picked, so the person sees
   where it lives, and then it opens as a press on its link would.
   @param {string} id */
function geneGo(id) {
  var f = geneById(id);
  if (!f) return;
  var row = f.row ? $(f.row) : null;
  if (row) {
    navGroupShow(f.group, true);
    /** @type {HTMLElement} */ (row).click();
    return;
  }
  geneOpen(f);
}

/* A gene's own glyph, for its row in Search.
   @param {string} id @returns {SVGSVGElement | null} */
function geneIcon(id) {
  var f = geneById(id);
  if (!f || !f.icon) return null;
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  var attrs = { viewBox: '0 0 24 24', width: '16', height: '16', fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' };
  Object.keys(attrs).forEach(function (k) { svg.setAttribute(k, attrs[k]); });
  // The registry's own drawing, from the server's gene manifests (`rouh/genes`
  // checks that it is nothing but lines and shapes).
  svg.innerHTML = f.icon;
  return svg;
}

(function () {
  var bar = $('sbTabs');
  if (!bar) return;
  bar.addEventListener('click', function (e) {
    var tab = e.target && /** @type {Element} */ (e.target).closest ? /** @type {Element} */ (e.target).closest('.sb-tab') : null;
    if (!tab) return;
    navGroupShow(tab.getAttribute('data-group') || '', true);
  });
  // The arrows move along the boxes, up and down the rail as a list of tabs
  // does everywhere (left and right too), and the group follows the focus.
  bar.addEventListener('keydown', function (e) {
    var tabs = navTabs(), at = tabs.indexOf(/** @type {HTMLElement} */ (document.activeElement)), to = -1;
    if (at < 0) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') to = (at + 1) % tabs.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') to = (at - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = tabs.length - 1;
    if (to < 0) return;
    e.preventDefault();
    tabs[to].focus();
    navGroupShow(tabs[to].getAttribute('data-group') || '', true);
  });

  navWire(document.querySelectorAll('#sbGo [data-opens]'));
  navMark(location.pathname);
})();

/* The links with no code of their own, by what their manifest says. A link
   stays a link (`linkTo`), so Cmd-click still opens it in a tab of its own.
   A link a gene's link is drawn as (Anatomy as its groups) is no gene of
   its own and goes to the address it was drawn with.
   @param {NodeListOf<Element> | Element[]} rows */
function navWire(rows) {
  for (var i = 0; i < rows.length; i++) {
    (function (row) {
      var f = geneById(row.getAttribute('data-nav') || '');
      if (!f && row.classList.contains('sb-as-link')) f = { route: row.getAttribute('href') || '', opens: 'address' };
      if (!f) return;
      if (row.tagName === 'A' && f.route) linkTo(/** @type {HTMLAnchorElement} */ (row), f.route);
      row.addEventListener('click', function () { geneOpen(f); });
    })(rows[i]);
  }
}

/* The shared genes' links drawn again from the server, after one of them was
   switched on or off in Rouh Land Account, Gene Pool (`genespage.js`, `rouh/genelab.py`).
   They stand last in their groups, so only they are taken out and put back;
   Rouh's own links, and what is bound to them, are left as they are. */
function navRefresh() {
  return fetch('/api/settings/genes/nav', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (got) {
      if (!got || !got.groups || !got.genes) return;
      REG.genes = got.genes.genes || REG.genes;
      var old = document.querySelectorAll('#sbGo [data-nav^="shared-"]');
      for (var i = 0; i < old.length; i++) old[i].remove();
      Object.keys(got.groups).forEach(function (g) {
        var panel = $('navGroup-' + g);
        if (!panel || !got.groups[g]) return;
        panel.insertAdjacentHTML('beforeend', got.groups[g]);
      });
      navWire(document.querySelectorAll('#sbGo [data-nav^="shared-"]'));
      navMark(location.pathname);
    })
    .catch(function () {});
}
/* A gene's own address, from its manifest, for the scripts outside the page's modules that link
   to one (`synapse.js` to Models), so a section that moves is linked where it is. */
function geneRoute(/** @type {string} */ id) {
  var f = geneById(id);
  return f && f.route ? String(f.route) : '';
}
window.RouhNav = { refresh: navRefresh, route: geneRoute };

/* Anatomy's groups, each with its sections in the order its page stacks them, from the
   gene manifests (`genes.anatomy`): {id, name, route, sections: [{id, name, gene, route}]}. */
function anatomyGroups() {
  return /** @type {{id: string, name: string, route: string, sections: {id: string, name: string, gene: string, route: string}[]}[]} */ (
    REG.anatomy || []);
}

/* The old names of the sections moved on 4 November 2026 (`genes.MOVED`), whose old addresses
   are sent on nowhere. */
function anatomyMoved() {
  return /** @type {string[]} */ (REG.moved || []);
}

export { anatomyGroups, anatomyMoved, geneGo, geneIcon, navMark, navNowCount };
