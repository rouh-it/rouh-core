/* Rouh's page, an empty conversation says hello, and says where to start (section welcome of what was one app.js).
 *
 * Imports app/address.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { ADDR, FRESH } from 'app/address.js';
import { $, el } from 'app/helpers.js';
import { S } from 'app/socket.js';
import { ORBX } from 'app/orb.js';
import { T } from 'app/transcript.js';
import { chatById, CHATS } from 'app/chats.js';
import { FIND, FIND_KEYS, findAct, findAsk, findMenuShow, findMove, findPaint, findShow } from 'app/search.js';
import { chatIsWanted, growInput, narrow, queueFold, setPane } from 'app/controls.js';
import { settingsOpen } from 'app/runs.js';

/* ------------------------------------------------------------- welcome */

/* An empty conversation says hello, and says where to start.
 *
 * Petar, 24 September 2026, passing on what somebody signing in for the
 * first time said: "It is empty. No hello, no 'start here'." And how it is
 * to be put right: "In the chat panel move the input box to the middle and
 * put a text above it: Hello, <Person's Name> / Ask me what I can do ...
 * And on the right, on the canvas, have 3,4 nice cards with examples of
 * prompts for research, create a page for something, etc".
 *
 * So while the conversation has nothing in it, the column is laid out
 * around the box rather than above it: the greeting, and the box under it
 * in the middle of the column. The things to try are on the canvas beside
 * it, and on a phone, where the canvas is behind the conversation rather
 * than beside it, under the box. The first thing drawn in the conversation
 * - the person's own words, an answer, a card - puts everything back where
 * a conversation has it (`dropEmpty`).
 *
 * Every empty conversation, and not only the very first one: the front
 * door is empty every time it is opened, and so is every New chat, and
 * each is somewhere a person is starting from. Not a task's, though. A
 * task's chat that nobody has talked in yet is about that task and says so
 * (`showCrumb`), and a hello with things to try that have nothing to do
 * with the task would be the wrong answer to "where do I start".
 */

//: The things to try: one of each kind of thing Rouh does that needs
//: nothing connected first, each in words that work exactly as they are.
var TRY = [
  { kind: 'research', head: 'Research a topic',
    say: 'Research how small companies make a four-day week work: what went'
      + ' well, what did not, and where you found it.' },
  { kind: 'page', head: 'Make a page',
    say: 'Make a page with a three-day plan for Lisbon: where to stay, what'
      + ' to see each day, and where to eat.' },
  { kind: 'task', head: 'Plan a piece of work',
    say: 'Make a task for organising a team offsite in March, and break it'
      + ' into steps.' },
  { kind: 'video', head: 'Sum up a video',
    say: 'Find a well-watched YouTube talk on giving good feedback and sum up'
      + ' its main points.' }
];

//: The rest of setting up, for a few days after the first run:
//: each one a guided step the chat takes the person through, in front of
//: two of the things to try (`firstrun.guiding`, the built-in rule new-rouh).
var SETUP = [
  { kind: 'mail', head: 'Connect my Gmail and calendar',
    say: 'Help me connect my Gmail and calendar, one step at a time.' },
  { kind: 'chat', head: 'Talk to me on Telegram',
    say: 'Help me connect Telegram, so I can talk to you from my phone.' },
  { kind: 'phone', head: 'Reach me from my phone',
    say: 'How can I reach you from the browser on my phone?' },
  { kind: 'you', head: 'Get to know me',
    say: 'Get to know me: ask me a few short questions about my work and what I want help with.' }
];

//: Each kind's glyph, drawn the way every other glyph on the page is. The
//: task's is the clipboard the head of a task's chat wears.
var TRY_GLYPH = {
  research: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  page: '<path d="M6 3h8l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>'
    + '<path d="M14 3v5h5M8.5 13h7M8.5 17h5"/>',
  task: '<path d="M9 4.5H7.5a2 2 0 0 0-2 2V19a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V6.5'
    + 'a2 2 0 0 0-2-2H15"/><rect x="9" y="3" width="6" height="3.2" rx="1"/>'
    + '<path d="M9 11h6M9 15h4"/>',
  video: '<rect x="3" y="5" width="18" height="14" rx="3"/>'
    + '<path d="M10.2 9.3v5.4l4.6-2.7z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>',
  chat: '<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
  you: '<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5c1.2-3.8 4-5.6 7.5-5.6s6.3 1.8 7.5 5.6"/>'
};

function welcomeWanted() {
  // Asked from the transcript's own code, which can run before this
  // section has: until the address is read there is nothing to decide.
  if (!ADDR || !$('transcriptEmpty')) return false;
  if (ADDR.front) return true;
  if (!T.heard || !CHATS) return false;
  // Decided from the chat's own row the handshake carries (`CHATS.own`) as
  // much as from the list that follows it, so the hello is there with the
  // conversation, or not at all, rather than turning up a second later when
  // the list does.
  var chat = chatById(CHATS.active);
  if (!chat) return false;
  // A fork is never empty for long: it opens with the question it was made
  // to ask, and the canvas beside it is the strip's, not a place for things
  // to try (`rouh/forks.py`).
  if (chat.fork_of) return false;
  // A Synapse dataset's own chat is about that dataset, which is on the
  // canvas beside it: things to try elsewhere would be the wrong welcome.
  if (String(chat.title || '').indexOf('Synapse \u00b7 ') >= 0) return false;
  return !chat.task && !(chat.owned_by && chat.owned_by.type === 'task');
}

/* Whether the page is on its way to a conversation: opened at an address it
   has not gone to yet, or with another chat asked of the server and not yet
   switched to. Meanwhile the screen holds whatever was open before, and an
   empty one there says nothing about the chat on its way. Deciding by it
   put the welcome up for an instant over a chat with history in it, opened
   by its own address while the chat open everywhere else was a new one. */
function welcomeHeld() {
  return !!(ADDR && ADDR.wanted) || S.switching;
}

// Called wherever the conversation is emptied, is first drawn in, or turns
// out to be another chat. Doing nothing when nothing changed is what makes
// that cheap enough to call from all of them.
function welcomeShow() {
  var col = $('chatCol'), canvas = $('canvasPanel');
  if (!col) return;
  var wanted = welcomeWanted();
  // Stepped into on a phone (`welcomeEnter`, below) lasts as long as the
  // conversation it was stepped into is empty, and not a moment past it.
  if (!wanted) ENTER.on = false;
  var on = wanted && !(ENTER.on && narrow());
  if (col.classList.contains('welcome') === on) return;
  // Held only from going up. Anything drawn in the conversation takes it
  // down whatever is on its way, so an answer that never comes cannot leave
  // it standing over words.
  if (on && welcomeHeld()) return;
  col.classList.toggle('welcome', on);
  if (canvas) canvas.classList.toggle('welcome', on);
  ['welcomeHello', 'welcomeUnder', 'welcomeTry'].forEach(function (id) {
    var node = $(id);
    if (node) node.hidden = !on;
  });
  // The box has moved, and how tall it may grow is a share of the room it
  // is in. On a phone the orb rides above it, so it follows.
  growInput();
  ORBX.dirty = true;
}

/* Into the conversation from the hello.

   Petar, 5 October 2026, on his phone at `/` (fr_e5f62aeb5ed2): "When I tap
   in the input, it should basically slide down and enter Rouh standard chat.
   Maybe the right way is to be entering Rouh standard chat but masking it to
   look like this screen".

   It already is the standard chat: the hello is this same column and this
   same box, laid out around the box while the conversation is empty. So the
   tap takes the mask off. On a phone, putting the cursor in the box steps
   into the conversation: the hello and the things to try slide down out of
   the way with the box, the box lands at the foot where a conversation has
   it, and the keyboard comes up under it with nothing in the way. Whatever is
   typed or said goes where it always went, because nothing but the layout
   has changed.

   Leaving the box with nothing in it, and nothing begun - no word, no file,
   no microphone, no conversation being opened - is stepping back out, and
   the hello slides back up. A press on the box's own controls is not leaving
   it: the microphone, the model and the paper clip are all part of starting.

   At a desk the box in the middle is where a person types, the keyboard
   covers nothing, and the things to try are on the canvas beside it, so the
   hello stays until the first thing is said, as it always has. */

//: Whether the person has stepped into the empty conversation, and when they
//: last pressed somewhere on the box.
var ENTER = { on: false, pressed: 0 };

// Glide time, close to the way a phone's own sheets move.
var ENTER_MS = 340;
var ENTER_EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';

function motionOk() {
  return !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

/* A still picture of a part of the hello, laid exactly over it, so it can be
   seen to go while the real one is already hidden. Nothing on it can be
   pressed, read out or found by its id. */
function ghostOf(id) {
  var node = $(id);
  if (!node || node.hidden) return null;
  var r = node.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  var ghost = /** @type {HTMLElement} */ (node.cloneNode(true));
  ghost.removeAttribute('id');
  ghost.querySelectorAll('[id]').forEach(function (n) { n.removeAttribute('id'); });
  ghost.setAttribute('aria-hidden', 'true');
  ghost.setAttribute('inert', '');
  ghost.classList.add('welcome-ghost');
  ghost.style.left = r.left + 'px';
  ghost.style.top = r.top + 'px';
  ghost.style.width = r.width + 'px';
  ghost.style.height = r.height + 'px';
  ghost.scrollTop = node.scrollTop;
  document.body.appendChild(ghost);
  return ghost;
}

/* The layout changes at once, and is then seen to move from where it was to
   where it is: the box from the middle to the foot and back, the hello and the
   things to try going down with it or coming up with it. */
function welcomeGlide() {
  var col = $('chatCol'), box = $('composer');
  if (!col || !box) { welcomeShow(); return; }
  var was = col.classList.contains('welcome');
  var moving = motionOk();
  var from = box.getBoundingClientRect().top;
  var ghosts = moving && was ? [ghostOf('welcomeHello'), ghostOf('welcomeUnder')] : [];
  welcomeShow();
  var now = col.classList.contains('welcome');
  var dy = from - box.getBoundingClientRect().top;
  if (now === was || !moving || !box.animate || Math.abs(dy) < 2) {
    ghosts.forEach(function (g) { if (g) g.remove(); });
    return;
  }
  var timing = { duration: ENTER_MS, easing: ENTER_EASE };
  // The navigation button stands just above a box at the foot, and was
  // measured against this one on its way there: it is measured again where
  // the box has landed.
  box.animate([{ transform: 'translateY(' + dy + 'px)' }, { transform: 'none' }], timing)
    .finished.then(queueFold, queueFold);
  if (!now) {
    // Out: everything that was round the box goes down with it and fades,
    // and the conversation's own empty line comes up in its place.
    ghosts.forEach(function (g) {
      if (!g) return;
      g.animate([{ transform: 'none', opacity: 1 },
                 { transform: 'translateY(' + (-dy) + 'px)', opacity: 0 }], timing)
        .finished.then(function () { g.remove(); }, function () { g.remove(); });
    });
    var line = $('transcriptEmpty');
    if (line) line.animate([{ opacity: 0 }, { opacity: 1 }],
                           { duration: ENTER_MS, easing: 'ease-out', delay: ENTER_MS / 3, fill: 'backwards' });
    return;
  }
  // Back in: the things to try come up from the foot with the box. The
  // greeting comes in the way it always does (`welcome-in`).
  var under = $('welcomeUnder');
  if (under && !under.hidden) {
    under.animate([{ transform: 'translateY(' + dy + 'px)', opacity: 0 },
                   { transform: 'none', opacity: 1 }], timing);
  }
}

function welcomeEnter() {
  var col = $('chatCol');
  if (ENTER.on || !narrow() || !col || !col.classList.contains('welcome')) return;
  ENTER.on = true;
  welcomeGlide();
}

// Whether something has been begun in the box, so leaving it is not leaving.
function welcomeBegun() {
  var input = /** @type {HTMLTextAreaElement | null} */ ($('input'));
  if (input && input.value.trim()) return true;
  var files = $('attachRow');
  if (files && !files.hidden) return true;
  var mic = $('micBtn');
  if (mic && !mic.classList.contains('off')) return true;
  return !!(FRESH && FRESH.asked);
}

function welcomeLeave() {
  if (!ENTER.on) return;
  var form = $('composer');
  if (form && form.contains(document.activeElement)) return;
  // A press on the box a moment ago is still being answered: look again
  // once it has been.
  var since = Date.now() - ENTER.pressed;
  if (since < 600) { setTimeout(welcomeLeave, 600 - since); return; }
  if (welcomeBegun()) return;
  ENTER.on = false;
  welcomeGlide();
}

(function () {
  var input = $('input'), form = $('composer');
  if (!input || !form) return;
  input.addEventListener('focus', welcomeEnter);
  form.addEventListener('pointerdown', function () { ENTER.pressed = Date.now(); }, true);
  // Decided a moment after the focus goes, once whatever the press was for
  // - a button on the box, the microphone opening - has happened.
  form.addEventListener('focusout', function () { setTimeout(welcomeLeave, 250); });
  // A phone turned on its side to a desk's width has no stepping in.
  if (window.matchMedia) {
    var wide = window.matchMedia('(max-width: 899px)');
    if (wide.addEventListener) wide.addEventListener('change', function () { welcomeShow(); });
  }
}());

// An example is somewhere to start from, not what the person meant to say,
// so it goes in the box to be changed and sent rather than being sent.
function tryThis(say) {
  var box = $('input');
  if (!box) return;
  // The box has to be on the screen to be written in. A conversation folded
  // away at a desk comes back, and a phone looking at the canvas goes back
  // to the conversation.
  var app = $('app');
  if (app && app.classList.contains('no-chat')) chatIsWanted();
  if (narrow()) setPane('chat');
  box.value = say;
  growInput();
  box.focus();
  try { box.setSelectionRange(say.length, say.length); } catch (err) {}
}

/* With a URL from the relay (`rouh/relay.py`), the phone's step is its own page: the URL, the
   switch that opens it and the QR code, on Your Rouh (its URL card). The step keeps its words,
   "Reach me from my phone", since they name the goal (141-17, Correction 1). */
function phoneStep(item) {
  var host = ($('welcomeTry') || { dataset: {} }).dataset.phone;
  if (item.kind !== 'phone' || !host) return item;
  return { kind: 'phone', head: item.head, say: host + ': open it, then scan the code with your phone',
           settings: 'this-rouh' };
}

function tryCard(item) {
  var card = el('button', 'try-card try-' + item.kind);
  card.type = 'button';
  card.title = 'Put this in the box';
  var mark = el('span', 'try-mark');
  mark.setAttribute('aria-hidden', 'true');
  mark.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
    + ' stroke="currentColor" stroke-width="1.7" stroke-linecap="round"'
    + ' stroke-linejoin="round">' + TRY_GLYPH[item.kind] + '</svg>';
  card.appendChild(mark);
  var words = el('span', 'try-words');
  words.appendChild(el('span', 'try-head', item.head));
  words.appendChild(el('span', 'try-say', item.say));
  card.appendChild(words);
  card.addEventListener('click', function () {
    if (item.settings) settingsOpen(item.settings);
    else tryThis(item.say);
  });
  var row = el('div', 'try-item');
  row.setAttribute('role', 'listitem');
  row.appendChild(card);
  return row;
}

(function () {
  var section = $('welcomeTry');
  var items = section && section.dataset.settingUp ? SETUP.map(phoneStep).concat(TRY.slice(0, 2)) : TRY;
  ['tryCanvas', 'tryUnder'].forEach(function (id) {
    var list = $(id);
    if (!list) return;
    items.forEach(function (item) { list.appendChild(tryCard(item)); });
  });
}());
welcomeShow();

/* ---------- wiring ---------- */

(function () {
  var dlg = $('searchDialog'), box = $('findInput');
  if (!dlg || !box) return;

  if ($('searchBtn')) {
    $('searchBtn').addEventListener('click', function () { findShow(!FIND.open); });
  }
  if ($('findClose')) {
    $('findClose').addEventListener('click', function () { findShow(false); });
  }
  // `close` is the one place FIND.open is put back, because a dialog can be
  // closed by the browser as well as by this file.
  dlg.addEventListener('close', function () {
    FIND.open = false;
    findMenuShow(false);
    if ($('searchBtn')) $('searchBtn').setAttribute('aria-expanded', 'false');
  });
  // Escape closes a row's menu first, and the box only when there is no menu.
  dlg.addEventListener('cancel', function (e) {
    if (FIND.menu >= 0) { e.preventDefault(); findMenuShow(false); }
  });
  // A press on the backdrop, which is the dialog element itself: anywhere
  // that is not the panel closes it, the way every modal does.
  dlg.addEventListener('click', function (e) {
    if (e.target === dlg) { findShow(false); return; }
    if (FIND.menu >= 0 && e.target.closest && !e.target.closest('.find-menu')
        && !e.target.closest('.find-dots')) {
      findMenuShow(false);
    }
  });

  box.addEventListener('input', function () {
    FIND.q = box.value;
    findAsk(false);
  });

  $('findPills').addEventListener('click', function (e) {
    var pill = e.target && e.target.closest ? e.target.closest('.find-pill') : null;
    if (!pill) return;
    FIND.kind = pill.getAttribute('data-kind') || 'all';
    box.focus();
    // The pills narrow the same question, so this is asked again with the
    // same words rather than being filtered here: the answer is capped at a
    // screenful, and a pill filtering that screenful would hide rows the
    // count beside it says are there.
    findAsk(true);
  });

  var list = $('findList');
  list.addEventListener('click', function (e) {
    var node = e.target && e.target.closest ? e.target.closest('.find-row') : null;
    if (!node) return;
    var i = Number(node.getAttribute('data-i'));
    var act = e.target.closest('[data-act]');
    var was = FIND.at;
    FIND.at = i;
    findPaint(was);
    if (act && act.getAttribute('data-act') === 'menu') {
      e.stopPropagation();
      findMenuShow(FIND.menu !== i, i);
      return;
    }
    findAct('open', i);
  });
  // Hovering a row moves the highlight with it, so the keys and the pointer
  // never disagree about which row the next press belongs to.
  list.addEventListener('mousemove', function (e) {
    if (FIND.menu >= 0) return;
    var node = e.target && e.target.closest ? e.target.closest('.find-row') : null;
    if (!node) return;
    var i = Number(node.getAttribute('data-i'));
    if (i === FIND.at) return;
    var was = FIND.at;
    FIND.at = i;
    findPaint(was);
  });

  $('findMenu').addEventListener('click', function (e) {
    var item = e.target && e.target.closest ? e.target.closest('[data-do]') : null;
    if (!item) return;
    findAct(item.getAttribute('data-do'), FIND.menu);
  });

  dlg.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); findMenuShow(false); findMove(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); findMenuShow(false); findMove(-1); return; }
    if (e.key === 'ArrowRight' && FIND.at >= 0 && FIND.menu < 0
        && box.selectionStart === box.value.length) {
      e.preventDefault(); findMenuShow(true, FIND.at); return;
    }
    if (e.key === 'ArrowLeft' && FIND.menu >= 0) {
      e.preventDefault(); findMenuShow(false); return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (FIND.at >= 0) findAct('open', FIND.at);
      return;
    }
    // The five numbers, live while a menu is open and only then: the squares
    // beside the menu's items are the promise, and a digit with no menu on
    // the screen belongs to the field it was typed into.
    if (FIND.menu >= 0 && FIND_KEYS[e.key] && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      findAct(FIND_KEYS[e.key], FIND.menu);
    }
  });

  /* The key. Cmd+K on a Mac, Ctrl+K everywhere else, which is what every
     program with a search box has settled on. Taken even while the text box
     has the cursor: the person pressing it meant search. */
  var mac = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '');
  var caps = document.querySelectorAll('.find-key');
  for (var i = 0; i < caps.length; i++) caps[i].textContent = mac ? '⌘K' : 'Ctrl+K';
  if ($('searchBtn')) {
    $('searchBtn').title = 'Search everything  ' + (mac ? '⌘K' : 'Ctrl+K');
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'k' && e.key !== 'K') return;
    if (e.altKey || e.shiftKey) return;
    if (mac ? !e.metaKey : !(e.ctrlKey && !e.metaKey)) return;
    e.preventDefault();
    findShow(!FIND.open);
  });
}());

export { tryThis, welcomeShow };
