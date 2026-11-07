/* Rouh's page, notifications (`rouh/notices.py`).
 *
 * Petar, 10 October 2026 (fr_8f09d161935f): "The navigation should pop up from
 * the top, like iOS. If I have more than one, they stack on top of each other.
 * If I click the stack, they expand into a single row and a single column, and
 * I can scroll through them. If I tap one of them, I see it fully expanded in
 * the same column of items." And: "if I swipe them left, I dismiss them, and if
 * I swipe right, I go to the task, the chat, or whatever that notification
 * links to, if there's anything. If there's nothing, then nothing happens when
 * I swipe right." And: "I can push up to get away from it, meaning I'm going to
 * look at it in a little bit or later."
 *
 * So there are three ways it is on the screen:
 *
 *   off    nothing new: only the bell in the sidebar, with how many are still
 *          to read.
 *   stack  something new: the newest notice drops in at the top, the others
 *          as layers under it. Left, it is dismissed and the next one is on
 *          top; right, it goes where it leads, and is dismissed; up, the whole
 *          stack is put away under the bell; a tap opens the column.
 *   list   the column, from a tap on the stack or a press on the bell: every
 *          notice of the last week, newest first, scrolling: New over the
 *          last day's, Earlier over the rest (`listed`). A press on its
 *          icon opens one in place, all of it, with the decision it asks drawn
 *          inside it and a button for where it leads. The same swipes work on
 *          every row.
 *
 * A notice that is new and left alone goes to the phone after `grace` seconds
 * (the server decides that, not this page): the thin line along the foot of
 * the top card is that time running out, and once it has gone the card says
 * so. Anything done with it - dismissed, opened, put away - means it was seen,
 * and the phone stays quiet.
 *
 * With a mouse the same drags work, and every one of them is a button too:
 * the cross on a card, the grip under the stack, and the buttons inside an
 * opened notice. A drag that starts on a notice's words in the column is the
 * mouse choosing them, not a swipe.
 *
 * A notice that has been followed has done its job. Petar, 11 October 2026
 * (fr_a7c05457e6a3): "When I tap on the button to visit something for link
 * from the notification it has to be dismissed. I should not come back to
 * notifications and find it again there". So going where one leads - its
 * button, a swipe right, or a link inside the decision it asks - dismisses it
 * in the same press, everywhere it is shown. Answering a decision, Later and
 * opening one in place do not: they are not going anywhere.
 *
 * Opened, a notice says all of it. Petar, 10 October 2026 (fr_70b1c378cc0e):
 * "when I tap a notification, it shows in full. But in full with ellipsis.
 * Which makes no sense because that is not in full. Either give me 'see more'
 * link or something." So the server keeps every word (a finished job's whole
 * closing message, not the phone's line or two), and an opened one draws it
 * whole as the markdown it is.
 *
 * Only the strip down its left, where its icon is, opens and closes it, and a
 * chevron under the icon says which way it will go. Petar, 15 October 2026
 * (fr_8341875cfa83): "Sometimes I need to copy paste text from those
 * notifications. However I can't do that, because when I tap on them, they
 * expand contract ... I like the sidebar where the icon is. Can we make this
 * tappable and have a little icon to tell you that. Also remove the see more
 * link. It is annoying because it is close to the other buttons below." So in
 * the column a notice's words are only words, to be chosen and copied, and
 * there is no See more under them. The top card of the stack still opens the
 * column wherever it is pressed: nothing is opened in place there.
 *
 * A tab left behind by a deploy says nothing of its own about it: the finished
 * run that put the new build live carries the Reload on its notice (`ranHere`):
 * "These are two notifications for the same thing ... if the run was a feature
 * that need restart, just add the button reload to it" (Petar, 11 October 2026,
 * fr_c09961ff435d). The page's own "Rouh has been updated" is gone since 13
 * October 2026, at his asking (`noteBuild`).
 */
import { $, el, linkTo } from 'app/helpers.js';
import { send } from 'app/socket.js';
import { goToAddress, renderMarkdown } from 'app/cards.js';
import { sidebarDone } from 'app/controls.js';

/** A notice as this page holds it: the server's, which may carry a Reload (`ranHere`), or the
 *  page's own (a negative id), which may carry something to do (`run`, labelled `link_label`)
 *  and a severity (`tone`, from `notify`).
 *  @typedef {import('./protocol').Notice & { reload?: boolean, tone?: Tone, run?: () => void }} Notice */

/** @typedef {'error' | 'warning' | 'success' | 'info'} Tone */

var NT = {
  /** The server's and the page's own together, newest first. @type {Notice[]} */
  items: [],
  /** @type {Notice[]} */
  server: [],
  /** The page's own, this tab's alone (`notify`). @type {Notice[]} */
  local: [],
  unread: 0,
  serverUnread: 0,
  grace: 45,
  /** @type {'off' | 'stack' | 'list'} */
  mode: 'off',
  /** The one opened in the column, by id, or 0. */
  open: 0,
  /** Acted on here and not yet confirmed by the server, so a listing already on its way
   *  cannot bring it back for a moment. @type {Record<number, string>} */
  acted: {},
  /** Told the server it was drawn while the page was in front of the person. */
  /** @type {Record<number, boolean>} */
  seen: {},
  /** Drawn on this page already, so only a new one drops in. */
  /** @type {Record<number, boolean>} */
  shown: {},
  /** Where New ends and Earlier begins in the column, in seconds, fixed when it opens so a
   *  notice does not move from one to the other under the finger. 0 while it is closed. */
  cut: 0,
  /** Decisions drawn inside opened notices (`decision.js`), and the host they answer through. */
  /** @type {Record<string, any>} */
  cards: {},
  host: null
};

/* How far a card has to travel, or how fast, before letting go of it counts. */
var SWIPE_PX = 96;
var SWIPE_SPEED = 0.55;   // px per ms
var UP_PX = 36;
var MOVE_PX = 8;

var ICONS = {
  job: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  reminder: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M5 3.5L2.8 5.7M19 3.5l2.2 2.2"/>',
  decision: '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/><path d="M9 12l2 2 4-4"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.8 6.6l8.2 6.2 8.2-6.2"/>',
  brief: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
  meeting: '<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.4"/><path d="M15.5 14.2A5 5 0 0 1 21 19"/>',
  conflict: '<path d="M6 3v12"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  browser: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 9h18"/>',
  payment: '<rect x="2.5" y="5.5" width="19" height="13" rx="2"/><path d="M2.5 10h19M6 15h4"/>',
  heartbeat: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
  gene: '<path d="M7 3c0 6 10 6 10 12s-10 3-10 6"/><path d="M17 3c0 6-10 6-10 12s10 3 10 6"/><path d="M8.5 7h7M8.5 17h7"/>',
  error: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.1"/>',
  warning: '<path d="M10.3 4.2L2.8 17.5A2 2 0 0 0 4.5 20.5h15a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 16.9v.1"/>',
  success: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.2 9.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/>',
  rouh: '<circle cx="12" cy="12" r="3.8"/><path d="M16.8 14.8C17.4 17.4 21 14.9 21.4 17.4M12 17.6C10 19.4 14 21.2 12 22.8M7.2 14.8C4.6 14 5 18.4 2.6 17.4M7.2 9.2C6.6 6.6 3 9.1 2.6 6.6M12 6.4C14 4.6 10 2.8 12 1.2M16.8 9.2C19.4 10 19 5.6 21.4 6.6"/>'
};

/** @param {string} kind */
function icon(kind) {
  var span = el('span', 'nt-ico nt-k-' + (ICONS[kind] ? kind : 'rouh'));
  span.setAttribute('aria-hidden', 'true');
  span.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"' +
    ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[kind] || ICONS.rouh) + '</svg>';
  return span;
}

/** How long ago, the way a phone says it: now, 4m, 2h, Mon. @param {number} at */
function ago(at) {
  var s = Math.max(0, Date.now() / 1000 - at);
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h';
  return new Date(at * 1000).toLocaleDateString([], { weekday: 'short' });
}

/* ---------- what is new, and what is on the screen ---------- */

/** The notices still to drop in at the top, newest first. */
function fresh() {
  return NT.items.filter(function (n) { return n.state === 'new' && !NT.acted[n.id]; });
}

/** @param {Notice} n */
function isRead(n) { return n.state === 'read' || NT.acted[n.id] === 'read'; }

/** How long a notice is listed under New: a day. */
var NEW_FOR = 24 * 3600;

/** Every notice the column lists, not dismissed here, newest first, in two sections by when it
 *  came: New, the last day's, and Earlier, the rest of the week's. Read or not is the dot on
 *  each, never which section it is in. They were once split that way, unread over read, and a
 *  notice opened a minute after it came sank under ones from the night before: "In reality the
 *  food was the new thing, the ones on top in section new are the older ones. Can you double
 *  check that there ordering is correct by recency- most recent on top" (Petar, 15 October
 *  2026, fr_c57b6f2118f1). */
function listed() {
  var keep = NT.items.filter(function (n) { return NT.acted[n.id] !== 'dismiss'; });
  var cut = (NT.mode === 'list' && NT.cut) || Date.now() / 1000 - NEW_FOR;
  return {
    recent: keep.filter(function (n) { return n.at >= cut; }),
    earlier: keep.filter(function (n) { return n.at < cut; })
  };
}

/** @param {number[]} ids @param {'seen' | 'later' | 'read' | 'dismiss'} what */
function act(ids, what) {
  // The page's own are this page's to change, and the server has never heard of them.
  var mine = ids.filter(function (id) { return id < 0; });
  ids = ids.filter(function (id) { return id >= 0; });
  if (mine.length && what !== 'seen') {
    NT.local = NT.local.filter(function (n) { return !(what === 'dismiss' && mine.indexOf(n.id) >= 0); });
    NT.local.forEach(function (n) { if (mine.indexOf(n.id) >= 0) n.state = what === 'read' || n.state === 'read' ? 'read' : 'later'; });
    merge();
  }
  if (ids.length) {
    if (what !== 'seen') ids.forEach(function (id) { NT.acted[id] = what; });
    send({ type: 'notice', act: what, ids: ids });
  }
  // The bell is right at once rather than when the server answers.
  if (what !== 'seen') count();
}

/** Whether the server's list has come once already: what is in the first one is not new. */
var heardOnce = false;

/** The server's list, on connect and whenever one is said or acted on anywhere.
 * @param {import('./protocol').FromServer<'notices'>} m */
function noticesHeard(m) {
  // A gene the registry blocklisted, or one with an update waiting (`rouh/genelab.py`):
  // the shared links in the navigation, and Meta, Gene registry, are drawn again now, so a
  // gene switched off by the blocklist is gone from every open tab at once.
  var known = {};
  NT.server.forEach(function (n) { known[n.id] = true; });
  if (heardOnce && (m.items || []).some(function (n) { return n.kind === 'gene' && !known[n.id]; })) {
    if (window.RouhNav) window.RouhNav.refresh();
    if (window.RouhGenes) window.RouhGenes.reload();
  }
  heardOnce = true;
  NT.server = (m.items || []).slice();
  NT.serverUnread = m.unread || 0;
  NT.grace = m.grace || 45;
  merge();
  // What the server has caught up with no longer needs holding here.
  var by = {};
  NT.items.forEach(function (n) { by[n.id] = n; });
  Object.keys(NT.acted).forEach(function (k) {
    var n = by[+k], did = NT.acted[+k];
    if (!n || (did === 'later' && n.state === 'later') || (did === 'read' && n.state === 'read')) {
      delete NT.acted[+k];
    }
  });
  if (NT.open && !by[NT.open]) NT.open = 0;
  if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
  draw();
}

/** The server's and the page's own as one list, newest first, and the count still to read.
 *  A run's notice that put live what this page is behind on carries the Reload (`ranHere`). */
function merge() {
  var server = NT.server.map(function (n) {
    return ranHere(n) ? Object.assign({}, n, { reload: true }) : n;
  });
  NT.items = NT.local.concat(server).sort(function (a, b) { return b.at - a.at; });
  count();
}

/** How many are still to read: the server's count, which is the whole week's and not only the
 *  listed ones (`listing`), less those read or dismissed here that it has not heard of yet, and
 *  the page's own. Until 4 November 2026 a press counted the listed ones again instead, so one
 *  swipe put a bell of 80 down to the unread among the 60 listed. */
function count() {
  var gone = NT.server.filter(function (n) {
    var did = NT.acted[n.id];
    return n.state !== 'read' && (did === 'dismiss' || did === 'read');
  }).length;
  NT.unread = Math.max(0, NT.serverUnread - gone) +
    NT.local.filter(function (n) { return n.state !== 'read'; }).length;
}

/** Whether a notice leads anywhere: a link, a Reload, or the page's own thing to do.
 *  @param {Notice} n */
function leads(n) { return !!(n.link || n.reload || n.run || places(n).length); }

/** Every place a notice leads when it leads to more than one, each a button of its own:
 *  a finished run's Run, Chat, Task and Page, those it has, in that order
 *  (`run_report.destinations`). Petar, 13 October 2026 (fr_677001efaa72): "it should give me
 *  all the buttons ... That way, I can immediately press what I want". [] for a notice that
 *  leads to one place, which keeps its one link. @param {Notice} n */
function places(n) {
  return (n.links || []).filter(function (p) { return !!(p && p.href && p.label); });
}

/** One of those places, gone to in the one press. @param {Notice} n
 *  @param {import('./protocol').NoticeLink} p @param {string} cls */
function placeButton(n, p, cls) {
  var a = goLink(n, p.href, cls);
  a.textContent = p.label;
  a.setAttribute('data-to', p.to || '');
  if (p.title) a.title = p.title;
  return a;
}

/** Somewhere a notice leads, as a link at its address, looking as the button it was. They
 *  were buttons, with no address for a browser to open anywhere else: "the buttons are links
 *  that are not working for wheel click or right click open in new tab" (Petar, 17 October
 *  2026, fr_7407619a2fbc). So a plain press goes there in this tab and dismisses the notice,
 *  as it always did (`follow`), and everything else a link does is the browser's (`linkTo`):
 *  the middle button, Cmd or Ctrl, Open link in new tab, Copy link address, the address in
 *  the status bar. A new tab leaves the notice where it is, so another of its places can be
 *  opened beside it. @param {Notice} n @param {string} href @param {string} cls */
function goLink(n, href, cls) {
  var a = linkTo(el('a', cls), href);
  if (href.indexOf('/files/') === 0) {
    a.setAttribute('download', decodeURIComponent(href.split('/').pop() || ''));
  } else if (href.charAt(0) !== '/' || href.charAt(1) === '/') {
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
  }
  a.addEventListener('click', function (e) { e.stopPropagation(); follow(n, href); });
  return a;
}

/** What a swipe right, or its button, says it will do: where it leads, or else a Reload.
 *  @param {Notice} n */
function goWord(n) {
  return n.run || n.link ? (n.link_label || 'Open it') : n.reload ? 'Reload' : 'Nothing to open';
}

/** A Reload button, the card's or an opened notice's. A run's notice it is on has been
 *  read by then, so the page that comes back does not drop it in again; the moment's wait is
 *  for that to reach the server before this page goes. @param {Notice} n */
function reloadButton(n) {
  var again = el('button', 'nt-btn nt-btn-go nt-reload', 'Reload');
  again.type = 'button';
  again.title = 'Load the page again, as the build Rouh is serving now';
  again.addEventListener('click', function (e) {
    e.stopPropagation();
    act([n.id], 'read');
    setTimeout(function () { location.reload(); }, 150);
  });
  return again;
}

/** The words a notice says, as one paragraph's plain text: the card that shows only its first
 *  lines is no place for markdown's stars and backticks. @param {string} text */
function plain(text) {
  return String(text || '')
    .replace(/```[a-z]*\n?/gi, '')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^(\s*)[-*+]\s+/gm, '$1• ')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)\s]+\)/g, '$1')
    // A table's row of dashes says nothing, and its pipes are the cells' words with a dot between.
    .replace(/^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/gm, '')
    .replace(/^[ \t]*\|(.*)\|[ \t]*$/gm, function (_, cells) {
      return cells.split('|').map(function (c) { return c.trim(); }).filter(Boolean).join(' · ');
    })
    // A paragraph's blank line would be one of the three lines, with only the "…" on it.
    .replace(/\n\s*\n+/g, '\n')
    .trim();
}

/* ---------- drawing ---------- */

function draw() {
  var root = $('notices');
  if (!root) return;
  var list = $('ntList');
  bell();
  if (NT.mode === 'stack' && !fresh().length) NT.mode = 'off';
  root.setAttribute('data-mode', NT.mode);
  root.hidden = NT.mode === 'off';
  // A notice's strip that has the keyboard keeps it when the list is drawn again, as it is
  // whenever the server answers.
  var had = document.activeElement && document.activeElement.closest('#ntList .nt-side');
  var hadId = had ? (had.closest('.nt-card') || had).getAttribute('data-id') : '';
  $('ntScrim').hidden = NT.mode !== 'list';
  $('ntHead').hidden = NT.mode !== 'list';
  $('ntGrip').hidden = NT.mode !== 'stack';
  list.textContent = '';
  if (NT.mode === 'off') return;
  if (NT.mode === 'stack') drawStack(list);
  else drawList(list);
  var back = hadId ? /** @type {HTMLElement | null} */ (list.querySelector('.nt-card[data-id="' + hadId + '"] .nt-side')) : null;
  if (back) back.focus({ preventScroll: true });
  tellSeen();
}

/** @param {HTMLElement} list */
function drawStack(list) {
  var all = fresh();
  var top = all[0];
  var card = cardFor(top, 'stack');
  list.appendChild(card);
  // The others, as edges under the top card, two at most, the way a phone stacks them.
  var layers = Math.min(all.length - 1, 2);
  for (var i = 1; i <= layers; i++) {
    var layer = el('div', 'nt-layer nt-layer-' + i);
    layer.setAttribute('aria-hidden', 'true');
    list.appendChild(layer);
  }
  $('ntGrip').setAttribute('aria-label', all.length > 1
    ? 'Put these ' + all.length + ' away for later' : 'Put this away for later');
  var more = $('ntMore');
  more.hidden = all.length < 2;
  more.textContent = all.length > 1 ? 'See all' : '';
}

/** @param {HTMLElement} list */
function drawList(list) {
  $('ntMore').hidden = true;
  tally();
  var got = listed();
  if (!got.recent.length && !got.earlier.length) {
    list.appendChild(el('p', 'nt-empty', 'No notifications.'));
    return;
  }
  if (got.recent.length) {
    list.appendChild(el('h3', 'nt-sec', 'New'));
    got.recent.forEach(function (n) { list.appendChild(cardFor(n, 'list')); });
  }
  if (got.earlier.length) {
    list.appendChild(el('h3', 'nt-sec', 'Earlier'));
    got.earlier.forEach(function (n) { list.appendChild(cardFor(n, 'list')); });
  }
}

/* The line under the column's name: how many are still to read, the number on the bell, and
   when the week holds more of those than the column lists (the newest 60, `LISTED` in
   rouh/notices.py), that the rest are older and not drawn, so the two numbers agree. */
function tally() {
  var line = $('ntTally');
  if (!line) return;
  var n = NT.unread;
  var kept = NT.items.filter(function (x) { return NT.acted[x.id] !== 'dismiss'; });
  var drawn = kept.filter(function (x) { return !isRead(x); }).length;
  var words = n ? n + ' to read' : 'All read';
  if (n > drawn) words += ' \u00b7 newest ' + kept.length + ' shown';
  line.textContent = words;
}

/** One notice. @param {Notice} n @param {'stack' | 'list'} where */
function cardFor(n, where) {
  var opened = where === 'list' && NT.open === n.id;
  var card = el('div', 'nt-card' + (opened ? ' open' : '') + (isRead(n) ? '' : ' unread'));
  card.setAttribute('data-id', String(n.id));
  card.setAttribute('role', 'article');
  card.setAttribute('aria-label', n.title);
  if (n.tone) card.setAttribute('data-tone', n.tone);
  if (!NT.shown[n.id]) {
    NT.shown[n.id] = true;
    if (where === 'stack') card.classList.add('arrive');
  }
  // What is behind the card while it is dragged: Dismiss on the right of it as it goes left,
  // where it leads on the left of it as it goes right.
  var leftUnder = el('div', 'nt-under nt-under-go' + (leads(n) ? '' : ' none'), goWord(n));
  var rightUnder = el('div', 'nt-under nt-under-x', 'Dismiss');
  leftUnder.setAttribute('aria-hidden', 'true');
  rightUnder.setAttribute('aria-hidden', 'true');
  card.appendChild(leftUnder);
  card.appendChild(rightUnder);

  var face = el('div', 'nt-face');
  face.appendChild(side(n, where, opened));
  var main = el('div', 'nt-main');
  var top = el('div', 'nt-top');
  top.appendChild(el('span', 'nt-title', n.title));
  var when = el('time', 'nt-when', ago(n.at));
  when.setAttribute('datetime', new Date(n.at * 1000).toISOString());
  when.title = new Date(n.at * 1000).toLocaleString();
  top.appendChild(when);
  main.appendChild(top);
  // Opened, a decision says its question itself, in its own card; anything else says every
  // word of it, drawn as the markdown it is.
  if (n.body && opened && !n.decision) {
    var whole = el('div', 'nt-body nt-md');
    whole.innerHTML = renderMarkdown(n.body);
    main.appendChild(whole);
  } else if (n.body && !opened) {
    main.appendChild(el('p', 'nt-body', plain(n.body)));
  }
  var meta = el('div', 'nt-meta');
  if (n.reload && !opened) {
    // The one thing to do about it, right on the card, opened or not.
    meta.appendChild(reloadButton(n));
  }
  if (n.run && !opened) {
    // The page's own notice offers its one thing to do on the card, as a Reload is.
    var doIt = el('button', 'nt-btn nt-btn-go nt-reload', goWord(n));
    doIt.type = 'button';
    doIt.addEventListener('click', function (e) { e.stopPropagation(); follow(n); });
    meta.appendChild(doIt);
  }
  var many = places(n);
  if (many.length && !opened) {
    // Every place it leads, side by side, so the one wanted is a press away, folded or not.
    var row = el('div', 'nt-places');
    many.forEach(function (p) { row.appendChild(placeButton(n, p, 'nt-place')); });
    meta.appendChild(row);
  } else if (n.link && !opened) {
    // Where it leads, gone to in the one press, folded or not. It was only a label once, so a
    // press on it was a press on the card and unfolded it instead: "If I press open the chat,
    // it doesn't open the chat it unfolds the full notification" (Petar, 12 October 2026,
    // fr_60dc3a8423c6). Unfolding is the rest of the card's.
    var go = goLink(n, n.link, 'nt-go');
    go.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"' +
      ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg>';
    go.appendChild(document.createTextNode(goWord(n)));
    meta.appendChild(go);
  }
  if (n.phone === 'sent') meta.appendChild(el('span', 'nt-phone', 'Sent to your phone'));
  else if (n.phone === 'due' && n.state === 'new') {
    meta.appendChild(el('span', 'nt-phone due', 'Goes to your phone if left'));
  }
  if (meta.childNodes.length) main.appendChild(meta);
  if (opened) main.appendChild(opening(n));
  face.appendChild(main);
  card.appendChild(face);

  var x = el('button', 'nt-x');
  x.type = 'button';
  x.setAttribute('aria-label', 'Dismiss ' + n.title);
  x.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"' +
    ' stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  x.addEventListener('click', function (e) {
    e.stopPropagation();
    fling(card, -1, function () { dismiss(n); });
  });
  card.appendChild(x);

  if (where === 'stack' && n.phone === 'due') {
    // The time left before the phone is told, running out along the foot of the card.
    var left = NT.grace - (Date.now() / 1000 - n.at);
    if (left > 0) {
      var fuse = el('div', 'nt-fuse');
      fuse.setAttribute('aria-hidden', 'true');
      fuse.style.transform = 'scaleX(' + Math.min(1, left / NT.grace) + ')';
      card.appendChild(fuse);
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          fuse.style.transition = 'transform ' + left + 's linear';
          fuse.style.transform = 'scaleX(0)';
        });
      });
    }
  }

  swipeable(card, n, where);
  return card;
}

/** The strip down a notice's left, its icon and a double chevron under it: the one place
 *  a press opens or closes it. In the stack it opens the column with this one open. The
 *  chevron is doubled because it opens and closes, which a single one elsewhere does not
 *  say: "In notifications there should be two chevrons when we talk about expanding and
 *  contracting, not just one" (Petar, 15 October 2026, fr_cdbfa478483f).
 *  @param {Notice} n @param {'stack' | 'list'} where @param {boolean} opened */
function side(n, where, opened) {
  var b = el('button', 'nt-side');
  b.type = 'button';
  b.setAttribute('aria-expanded', String(opened));
  b.setAttribute('aria-label', (opened ? 'Show less of ' : 'Show all of ') + n.title);
  b.title = opened ? 'Show less' : 'Show all of it';
  b.appendChild(icon(n.kind || n.tone || ''));
  var chev = el('span', 'nt-chev');
  chev.setAttribute('aria-hidden', 'true');
  chev.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"' +
    ' stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 6.5l5 5 5-5M7 12.5l5 5 5-5"/></svg>';
  b.appendChild(chev);
  b.addEventListener('click', function (e) {
    e.stopPropagation();
    if (where === 'stack') openList(n.id);
    else tap(n, where);
  });
  b.addEventListener('keydown', function (e) {
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); dismiss(n); }
  });
  return b;
}

/** What an opened notice says under its words: the decision it asks, and its buttons.
 * @param {Notice} n */
function opening(n) {
  var box = el('div', 'nt-open');
  if (n.decision) {
    // The decision's own card has its answers, Later, Dismiss and the way to its context:
    // a second row of buttons beside them would be two of everything.
    box.appendChild(decisionIn(n.decision));
    // A link in it goes somewhere, which is the notice used (`used`). Caught on the way down,
    // before the link's own press takes the column away.
    box.addEventListener('click', function (e) {
      if (e.target instanceof Element && e.target.closest('a[href]')) used(n);
    }, true);
    box.addEventListener('click', function (e) { e.stopPropagation(); });
    box.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
    return box;
  }
  var row = el('div', 'nt-do');
  if (n.reload) row.appendChild(reloadButton(n));
  var many = places(n);
  if (many.length) {
    // Every place it leads, each as quiet as the next: none of them is the one it is for.
    many.forEach(function (p) { row.appendChild(placeButton(n, p, 'nt-btn')); });
  } else if (n.link || n.run) {
    // Beside a Reload, where it leads is the quieter of the two. The page's own thing to do
    // goes nowhere, so it stays a button.
    var goCls = 'nt-btn' + (n.reload ? '' : ' nt-btn-go');
    var go;
    if (n.link) {
      go = goLink(n, n.link, goCls);
      go.textContent = goWord(n);
    } else {
      go = el('button', goCls, goWord(n));
      go.type = 'button';
      go.addEventListener('click', function (e) { e.stopPropagation(); follow(n); });
    }
    row.appendChild(go);
  }
  // Apart from a row of places, at its far end, so it is not read as one more of them.
  var x = el('button', 'nt-btn' + (many.length ? ' nt-btn-end' : ''), 'Dismiss');
  x.type = 'button';
  x.addEventListener('click', function (e) { e.stopPropagation(); dismiss(n); });
  row.appendChild(x);
  box.appendChild(row);
  // A press inside it is its own and never closes it.
  box.addEventListener('click', function (e) { e.stopPropagation(); });
  box.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
  return box;
}

/** The decision a notice asks, drawn the one way decisions are drawn (`decision.js`).
 * @param {number} id */
function decisionIn(id) {
  var mount = el('div', 'nt-decision');
  var had = NT.cards['d' + id];
  if (had && had.node) { mount.appendChild(had.node); return mount; }
  mount.appendChild(el('p', 'nt-wait', 'Loading the question…'));
  fetch('/api/decisions/' + id, { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (j) {
      mount.textContent = '';
      if (!j || !j.decision || !window.RouhDecision) {
        mount.appendChild(el('p', 'nt-wait', 'That question is not there any more.'));
        return;
      }
      if (!NT.host) {
        NT.host = window.RouhDecision.fetchHost({
          go: function (href) { closeList(); goToAddress(href); }
        });
      }
      var node = window.RouhDecision.card(j.decision, NT.host, { place: 'context' });
      NT.cards['d' + id] = { node: node };
      mount.appendChild(node);
    })
    .catch(function () {
      mount.textContent = '';
      mount.appendChild(el('p', 'nt-wait', 'The question could not be loaded.'));
    });
  return mount;
}

/* ---------- what a person does with one ---------- */

/** The strip's press, or in the stack a press anywhere on the card.
 *  @param {Notice} n @param {'stack' | 'list'} where */
function tap(n, where) {
  if (where === 'stack') {
    // One alone opens in the column, all of it; a stack opens into the column.
    openList(fresh().length === 1 ? n.id : 0);
    return;
  }
  NT.open = NT.open === n.id ? 0 : n.id;
  if (NT.open && n.state !== 'read') act([n.id], 'read');
  draw();
  var again = document.querySelector('#ntList .nt-card[data-id="' + n.id + '"]');
  if (again && again.scrollIntoView) again.scrollIntoView({ block: 'nearest' });
}

/** @param {Notice} n */
function dismiss(n) {
  act([n.id], 'dismiss');
  if (NT.open === n.id) NT.open = 0;
  if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
  draw();
}

/** Gone to where it leads, so it is done with: dismissed, here and on every other screen of
 *  the person's. Drawn again a moment later rather than now, because the link that was pressed
 *  has to still be on the page for the browser to follow it. @param {Notice} n */
function used(n) {
  act([n.id], 'dismiss');
  if (NT.open === n.id) NT.open = 0;
  setTimeout(function () {
    if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
    draw();
  }, 0);
}

/** Where it leads, if it leads anywhere, and it is dismissed on the way (`used`). False when
 *  it leads nowhere. `href` is one of its places (`places`), pressed; without it, its link.
 *  @param {Notice} n @param {string} [href] */
function follow(n, href) {
  var link = href || n.link;
  if (n.reload && !link) { location.reload(); return true; }
  if (!link && !n.run) return false;
  act([n.id], 'dismiss');
  NT.mode = 'off';
  NT.open = 0;
  NT.cut = 0;
  // Whatever else was new was in sight while this was chosen.
  act(fresh().map(function (f) { return f.id; }), 'later');
  draw();
  if (n.run && !href) { n.run(); return true; }
  if (link.indexOf('/files/') === 0) {
    // A file of a task's by the signed link Rouh drew for it (`rouh/filelinks.py`), such as a
    // page made into a PDF (`rouh/page_pdf.py`): saved, never opened as a place in Rouh.
    var save = document.createElement('a');
    save.href = link;
    save.setAttribute('download', decodeURIComponent(link.split('/').pop() || ''));
    document.body.appendChild(save);
    save.click();
    save.remove();
    return true;
  }
  if (/^\/mail\/renewal\//.test(link)) {
    // A renewal's Open the email (`/mail/renewal/<key>`, rouh/renewal_notice.py) says it was used
    // and sends on to the email in Gmail: in a tab of its own, as every link out of Rouh opens.
    window.open(link, '_blank', 'noopener');
    return true;
  }
  if (link.charAt(0) === '/' && link.charAt(1) !== '/') {
    // The pages the server draws by itself (a case's trace, its files) are followed as plain
    // links, as `decision.js` does: Rouh's page has no place of its own for them. A case itself,
    // `/mail/case/<key>`, is Rouh's own since 15 October 2026. And a page behind a deploy goes
    // there as a whole new load, which is its Reload on the way.
    // So is a bounce's Open (`/mail/not-arrived/<key>`, rouh/not_arrived.py), which says it was
    // used and sends the page on to the chat the email went from.
    if (/^\/mail\/(case\/[^/?#]+\/.|not-arrived\/)/.test(link) || n.reload) location.assign(link);
    else {
      // On a phone the bell is inside the navigation's drawer, which goes with the press like
      // after any other link followed from it, or it stays over the place just opened.
      sidebarDone();
      goToAddress(link);
    }
  } else {
    window.open(link, '_blank', 'noopener,noreferrer');
  }
  return true;
}

/** Push the stack away: every new one waits under the bell. */
function putAway() {
  act(fresh().map(function (n) { return n.id; }), 'later');
  NT.mode = 'off';
  draw();
}

/** @param {number} openId */
function openList(openId) {
  NT.mode = 'list';
  NT.open = openId || 0;
  NT.cut = Date.now() / 1000 - NEW_FOR;
  if (NT.open) {
    var n = NT.items.find(function (i) { return i.id === NT.open; });
    if (n && n.state !== 'read') act([n.id], 'read');
  }
  draw();
  var root = $('notices');
  root.classList.remove('listing');
  void root.offsetWidth;
  root.classList.add('listing');
  var first = /** @type {HTMLElement | null} */ (document.querySelector('#ntList .nt-side'));
  var bellBtn = $('noticeBell');
  if (bellBtn) bellBtn.setAttribute('aria-expanded', 'true');
  if (first) first.focus({ preventScroll: true });
}

/** Close the column. What was new in it was in sight, so it is put away rather than
 *  dropped in again. */
function closeList() {
  if (NT.mode !== 'list') return;
  act(fresh().map(function (n) { return n.id; }), 'later');
  NT.mode = 'off';
  NT.open = 0;
  NT.cut = 0;
  var bellBtn = $('noticeBell');
  if (bellBtn) bellBtn.setAttribute('aria-expanded', 'false');
  draw();
}

/** Tell the server which new ones a page in front of the person has drawn. */
function tellSeen() {
  if (document.visibilityState !== 'visible' || NT.mode === 'off') return;
  var ids = [];
  var got = listed();
  var drawn = NT.mode === 'stack' ? fresh().slice(0, 1) : got.recent.concat(got.earlier);
  drawn = drawn.filter(function (n) { return !isRead(n); });
  drawn.forEach(function (n) {
    if (!NT.seen[n.id] && n.state === 'new') { NT.seen[n.id] = true; ids.push(n.id); }
  });
  if (ids.length) act(ids, 'seen');
}

/* ---------- swiping ---------- */

/** Send a card off the screen one way, then do what that way means.
 * @param {HTMLElement} card @param {number} dir -1 left, 1 right, 0 up @param {() => void} then */
function fling(card, dir, then) {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) { then(); return; }
  card.classList.add('flung');
  card.style.transform = dir ? 'translateX(' + (dir * 120) + '%)' : 'translateY(-140%)';
  card.style.opacity = '0';
  setTimeout(then, 170);
}

/** @param {HTMLElement} card @param {Notice} n @param {'stack' | 'list'} where */
function swipeable(card, n, where) {
  var face = /** @type {HTMLElement} */ (card.querySelector('.nt-face'));
  /** @type {{x: number, y: number, t: number, id: number, axis: string, dx: number, dy: number} | null} */
  var drag = null;
  card.addEventListener('pointerdown', function (e) {
    if (e.button || (e.target instanceof Element && e.target.closest('button, a, .nt-open'))) return;
    // In the column a mouse dragged across the words is choosing them to copy.
    if (where === 'list' && e.pointerType === 'mouse' && e.target instanceof Element &&
        e.target.closest('.nt-title, .nt-body')) return;
    drag = { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId, axis: '', dx: 0, dy: 0 };
  });
  card.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.axis) {
      if (Math.abs(dx) < MOVE_PX && Math.abs(dy) < MOVE_PX) return;
      if (Math.abs(dx) > Math.abs(dy)) drag.axis = 'x';
      else if (where === 'stack' && dy < 0) drag.axis = 'y';
      else { drag = null; return; }      // a scroll of the column, the browser's
      try { card.setPointerCapture(e.pointerId); } catch (err) {}
      card.classList.add('dragging');
    }
    drag.dx = dx; drag.dy = dy;
    if (drag.axis === 'x') {
      // Right with nowhere to go gives a little and no more.
      var shown = dx > 0 && !leads(n) ? dx * 0.25 : dx;
      face.style.transform = 'translateX(' + shown + 'px)';
      card.setAttribute('data-pull', dx < 0 ? 'left' : 'right');
      card.classList.toggle('past', Math.abs(dx) >= SWIPE_PX && (dx < 0 || leads(n)));
    } else {
      $('notices').style.setProperty('--nt-lift', Math.min(0, dy) + 'px');
    }
    e.preventDefault();
  });
  function end(/** @type {PointerEvent} */ e, cancelled) {
    if (!drag || e.pointerId !== drag.id) return;
    var d = drag;
    drag = null;
    card.classList.remove('dragging', 'past');
    card.removeAttribute('data-pull');
    var speed = (d.axis === 'x' ? Math.abs(d.dx) : -d.dy) / Math.max(1, performance.now() - d.t);
    if (!d.axis) {
      // Only the top card of the stack opens from a press anywhere on it; in the column the
      // words are left to be chosen and copied, and the strip opens it (`side`).
      if (!cancelled && where === 'stack') tap(n, where);
      return;
    }
    if (d.axis === 'y') {
      $('notices').style.removeProperty('--nt-lift');
      if (!cancelled && (-d.dy >= UP_PX || speed >= SWIPE_SPEED)) {
        fling(/** @type {HTMLElement} */ ($('ntPanel')), 0, function () {
          $('ntPanel').removeAttribute('style');
          putAway();
        });
      }
      return;
    }
    var far = Math.abs(d.dx) >= SWIPE_PX || (speed >= SWIPE_SPEED && Math.abs(d.dx) > 30);
    if (!cancelled && far && d.dx < 0) {
      fling(card, -1, function () { dismiss(n); });
      return;
    }
    if (!cancelled && far && d.dx > 0 && leads(n)) {
      fling(card, 1, function () { follow(n); });
      return;
    }
    face.style.transform = '';
  }
  card.addEventListener('pointerup', function (e) { end(e, false); });
  card.addEventListener('pointercancel', function (e) { end(e, true); });
  // A drag is the card's, not the browser's: no text is picked up and carried off.
  card.addEventListener('dragstart', function (e) { e.preventDefault(); });
}

/* ---------- the bell ---------- */

function bell() {
  var b = $('noticeBell'), count = $('noticeCount');
  if (!b || !count) return;
  var n = NT.unread;
  count.hidden = !n;
  count.textContent = n > 99 ? '99+' : String(n);
  var words = n ? n + ' notification' + (n === 1 ? '' : 's') + ' to read' : 'Notifications';
  b.title = words;
  b.setAttribute('aria-label', words);
  b.classList.toggle('has', !!n);
  // With the sidebar folded away its button carries the dot, and on a phone, where the
  // orb's circle is the menu button, the circle does.
  var fold = $('sidebarToggle');
  if (fold) fold.classList.toggle('nt-dot', !!n);
  orbDot(!!n);
}

/* The dot beside the orb's circle on a phone. The circle's own box clips to a circle and
   the orb's rings are drawn over it, so the dot is a badge of its own, fixed to the window
   just off the circle's upper right, and it follows the circle wherever the orb puts it
   (`orbSet` in app/orb.js rewrites the box's style as it moves). Only on the circle:
   grown into the navigation's row, or opened over the screen, it says nothing. */
/** @type {HTMLElement | null} */
var ORB_DOT = null;

/** @param {boolean} on */
function orbDot(on) {
  var box = $('orbBox');
  if (!ORB_DOT) {
    ORB_DOT = el('span', 'nt-orb-dot');
    ORB_DOT.setAttribute('aria-hidden', 'true');
    ORB_DOT.hidden = true;
    document.body.appendChild(ORB_DOT);
    if (box && window.MutationObserver) {
      new MutationObserver(orbDotPlace).observe(box, { attributes: true, attributeFilter: ['style', 'class'] });
    }
    window.addEventListener('resize', orbDotPlace);
  }
  ORB_DOT.setAttribute('data-on', on ? '1' : '');
  orbDotPlace();
}

function orbDotPlace() {
  var dot = ORB_DOT, box = $('orbBox'), circle = $('orbOpen');
  if (!dot) return;
  var r = box ? box.getBoundingClientRect() : null;
  // The circle, and not the row it grows into: 66 across since 10 October 2026, when it
  // outgrew the 64 this used to allow, and the dot stopped showing at all.
  var shown = !!(dot.getAttribute('data-on') && r && r.width && r.width <= 80 &&
    circle && !circle.hidden && !box.classList.contains('moving') &&
    window.matchMedia('(max-width: 640px)').matches);
  dot.hidden = !shown;
  if (!shown) return;
  dot.style.left = Math.round(r.right - 10) + 'px';
  dot.style.top = Math.round(r.top - 1) + 'px';
}

/* ---------- what the page itself has to say ----------
 *
 * Everything the page tells the person by itself - a press that could not be
 * done, a message that was not sent, a move that landed, a reminder Rouh put
 * on Clockwork - is a notice here, the same card as the server's, of this
 * tab's alone and never sent anywhere. Until 11 October 2026 each was a bar of
 * its own at the top right (`banner`, in app/banners.js), which on a phone sat
 * across the top of the chat. Petar, on that bar (fr_f212c0ce02f6): "Anything
 * that uses that old system should be converted to our new notification system
 * and this old mechanic should be deleted."
 *
 * `tone` is how much it matters and picks its mark. One with something to do
 * about it (`action`, `{ label, run }`) offers it on the card, and swiped right
 * does it; it stays new until it is done, dismissed or put away, as does an
 * error that is not over (`lasting`). Anything else has been said once it has
 * been in sight for `for` milliseconds (nine seconds unless it says), and then
 * leaves the stack, read, for the column under the bell - but not while the
 * pointer or the keyboard is on it.
 */

/** The page's own notices are numbered down from here. */
var SAID = { next: -1, keep: 30 };

/**
 * @param {string} words
 * @param {{ tone?: Tone, kind?: string, body?: string, lasting?: boolean, for?: number,
 *           action?: { label: string, run: () => void } | null }} [how]
 * @returns {{ id: number, remove: () => void }}
 */
function notify(words, how) {
  how = how || {};
  var tone = how.tone || 'info';
  var title = String(words || '').trim() || (tone === 'error' ? 'Something failed.' : '');
  var body = how.body || '';
  // A notice is a title over its words, so more than a sentence is the first one over the
  // rest, rather than every word of it in bold.
  var cut = body ? null : /^(.{12,}?[.!?])\s+(\S[\s\S]*)$/.exec(title);
  if (cut && title.length > 64) { title = cut[1]; body = cut[2]; }
  // The same thing said again is the one notice, brought back to the top.
  NT.local = NT.local.filter(function (o) {
    return !(o.title === title && o.body === body && o.tone === tone && o.state !== 'read');
  });
  /** @type {Notice} */
  var n = {
    id: SAID.next--, kind: how.kind || tone, title: title, body: body, link: '',
    link_label: how.action ? how.action.label : '', decision: null, state: 'new', phone: '',
    at: Date.now() / 1000, phoned_at: null, tone: tone
  };
  if (how.action) n.run = how.action.run;
  NT.local.unshift(n);
  // Only this tab's last few are kept: the oldest that have been read go first.
  var extra = NT.local.length - SAID.keep;
  for (var i = NT.local.length - 1; i >= 0 && extra > 0; i--) {
    if (NT.local[i].state === 'read') { NT.local.splice(i, 1); extra--; }
  }
  merge();
  if (NT.mode !== 'list') NT.mode = 'stack';
  draw();
  if (!how.lasting && (!how.action || how.for)) said(n, how.for || 9000);
  return { id: n.id, remove: function () { unsay(n.id); } };
}

/** Once it has been in sight long enough, it leaves the stack for the column, read.
 *  @param {Notice} n @param {number} ms */
function said(n, ms) {
  window.setTimeout(function () {
    if (NT.local.indexOf(n) < 0 || n.state === 'read') return;
    var card = document.querySelector('#ntList .nt-card[data-id="' + n.id + '"]');
    if (card && (card.matches(':hover') || card.contains(document.activeElement))) {
      said(n, 3000);
      return;
    }
    n.state = 'read';
    merge();
    if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
    draw();
  }, ms);
}

/** Take one of the page's own away, wherever it is. @param {number} id */
function unsay(id) {
  var had = NT.local.length;
  NT.local = NT.local.filter(function (o) { return o.id !== id; });
  if (NT.local.length === had) return;
  if (NT.open === id) NT.open = 0;
  merge();
  if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
  draw();
}

/* ---------- the build this page is made of ----------
 *
 * Every file the page is made of was served from /a/<hash>/, the hash being
 * that file's own content's, and the browser is told to keep it for a year:
 * nothing ever changes under that address, so a tab that is open when Rouh
 * restarts keeps working and no deploy can swap half a page out from under
 * somebody using it. The other half of that bargain is that a tab left open
 * across a deploy is still the old page afterwards.
 *
 * Until 13 October 2026 such a tab said so itself, in a notice of its own
 * ("Rouh has been updated", blue, with both commits and a Reload). Petar asked
 * that day for it to go, twice: "please stop sending the [blue] one ... Instead
 * we have the green checkmark that already has a restart button"
 * (fr_c3a5ce7d17b8), and when holding it back for two minutes still let it
 * through on a deploy no run had reported yet, "You keep displaying that
 * notification, which I requested to be gone. Can we disable/delete it?"
 * (fr_ee6b8d91a861). So the page says nothing of its own about a deploy. It
 * only notes that it is behind, so that the finished run that put the new build
 * live carries the Reload on its own notice (`ranHere`), and never reloads
 * itself: that takes the screen away from whoever is using it.
 */

// The build this page was served as, off the <meta name="rouh-build"> the
// server writes into it. Empty when there is no server in front of it - the
// folder opened straight from disk - and then there is nothing to compare.
function pageBuild() {
  var meta = document.querySelector('meta[name="rouh-build"]');
  return meta ? (meta.getAttribute('content') || '') : '';
}

// The commit this page was stamped with when it was served: {{REVISION}} in
// index.html, which is the same string the Settings panel shows. A page that
// has none says nothing rather than a word that is not a commit, so only
// seven characters of hexadecimal get past this.
function pageCommit() {
  var said = $('verRev') ? ($('verRev').textContent || '').trim() : '';
  return /^[0-9a-f]{7}$/.test(said) ? said : '';
}

/* When this page was loaded, and whether it is behind the build Rouh is serving (`behind`):
   a run whose notice was said after the one and while the other is true put live what this
   page is missing (`ranHere`). */
var BUILD = { mine: pageBuild(), commit: '', behind: false, at: Date.now() / 1000 };

/** Whether a notice is a run's that deployed what this page is behind on: said after the
 *  page was loaded, of a commit that is not the page's own. A few seconds' slack, for a
 *  server clock a little behind this one. @param {Notice} n */
function ranHere(n) {
  return !!(BUILD.behind && n.deployed && n.deployed !== BUILD.commit && n.at >= BUILD.at - 5);
}

/** The handshake's build, against this page's. Once a tab is behind it stays behind until
 *  it is reloaded, however many times it reconnects. @param {string} theirs */
function noteBuild(theirs) {
  if (BUILD.behind || !theirs || !BUILD.mine || theirs === BUILD.mine) return;
  BUILD.behind = true;
  BUILD.commit = pageCommit();
  // A run's notice already in the list may be the one that left this page behind.
  merge();
  if (NT.mode !== 'list') NT.mode = fresh().length ? 'stack' : 'off';
  draw();
}

(function wire() {
  var b = $('noticeBell');
  if (b) {
    b.addEventListener('click', function () {
      if (NT.mode === 'list') closeList();
      else openList(0);
    });
  }
  var grip = $('ntGrip');
  if (grip) grip.addEventListener('click', putAway);
  var scrim = $('ntScrim');
  if (scrim) scrim.addEventListener('click', closeList);
  var done = $('ntDone');
  if (done) done.addEventListener('click', closeList);
  var clear = $('ntClear');
  if (clear) {
    clear.addEventListener('click', function () {
      var got = listed();
      act(got.recent.concat(got.earlier).map(function (n) { return n.id; }), 'dismiss');
      closeList();
    });
  }
  var more = $('ntMore');
  if (more) more.addEventListener('click', function () { openList(0); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && NT.mode === 'list') { e.preventDefault(); closeList(); }
  });
  document.addEventListener('visibilitychange', tellSeen);
  // The times on the cards ("4m") move on by themselves.
  setInterval(function () {
    var times = document.querySelectorAll('#ntList .nt-when');
    for (var i = 0; i < times.length; i++) {
      var t = /** @type {HTMLElement} */ (times[i]);
      var at = Date.parse(t.getAttribute('datetime') || '') / 1000;
      if (at) t.textContent = ago(at);
    }
  }, 30000);
})();

export { notify, noteBuild, noticesHeard };
