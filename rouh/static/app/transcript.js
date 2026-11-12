/* Rouh's page, transcript (section 8 of what was one app.js).
 *
 * Imports app/orb.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { clipWords, num, setState } from 'app/orb.js';
import { shared } from 'app/shared.js';
import { $, browserTakes, el, linkTo, now } from 'app/helpers.js';
import { cfg } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { S, send } from 'app/socket.js';
import { PB, readAloud, stopPlayback } from 'app/playback.js';
import { ANSWER_HELD, answerHeldGo, cardsUnpark, footnotes, goToAddress, renderBlock, resetCanvas, resetStreamCards, svgEl } from 'app/cards.js';
import { copyText, growToLines } from 'app/runs.js';
import { CHATS, forkBtnPaint, forkComeNow, forkKeys, forkMarksDraw, FORKS, isSendKey, sendKeys } from 'app/chats.js';
import { welcomeShow } from 'app/welcome.js';
import { screenHeight } from 'app/controls.js';
import { drawTurnFiles, isDrawn } from 'app/attachments.js';
import { lineFor, onRecall, onRedo, recallDraw, routeDraw, traceDraw, traceMove } from 'app/turnline.js';

/* ------------------------------------------------------------------ 8 */

var T = { assistant: null, partial: null, typed: null, typing: null, dots: null,
          // The exchange the turn now running is writing into, so the answer
          // being written can be told which question it answers the moment
          // it is built rather than only once it is stored. The turn's own
          // number goes with it: a bubble opened for the turn now running
          // must not be stamped with the exchange the last one was writing
          // into, which is how an answer ended up filed under the question
          // above it and a retry then took the wrong one off the screen.
          now: { turn: 0, root: 0 },
          // The turn whose answer was split by a message the person sent
          // while it was being written (`onSteerTaken`): the bubble after it
          // holds only what came after, so the finished answer, which is all
          // of it, must not be poured into that bubble whole (`onDone`).
          split: 0,
          // Whether the server has said what the conversation on screen
          // holds. Until it has, an empty transcript is one not read yet
          // rather than one with nothing in it, and a chat with a hundred
          // messages must not open on the welcome (`welcomeShow`).
          heard: false };

// Where the conversation is being drawn: the one on screen, or for the
// length of `drawTranscriptInto`, a card's copy of a chat beside it.
var HOST = { el: /** @type {HTMLElement|null} */ (null) };
function transcriptEl() { return HOST.el || $('transcript'); }

// Whether to keep following the bottom. It is a remembered decision, not
// something recalculated from the scroll position each time new text lands.
//
// The version this replaces asked "am I at the bottom?" *after* appending the
// new text. By then the new text had already made the box taller, so anything
// longer than the threshold looked like the reader had scrolled away, and
// following stopped in the middle of every reply of any length.
//
// Now only the reader changes it: scrolling up stops the following, and
// returning to the bottom starts it again.
shared.stick = true;

function atBottom(slack) {
  var t = transcriptEl();
  if (!t) return true;
  return t.scrollHeight - t.scrollTop - t.clientHeight <= (slack === undefined ? 4 : slack);
}

// When the conversation last folded away or came back (`sbApply`), and how
// long its column takes to get there: the grid's 260ms, and some to spare.
shared.foldMoved = 0;
var FOLD_SETTLES = 400;

/* Following the end, and what stops it.

   Petar, 8 October 2026 (fr_59873056b853): "after I type a message, the
   first tool use appears and activates the 'latest' button so the auto
   scroll stops working". This handler used to ask only how far the end was
   at each scroll event, and Safari sends scroll events nobody made. Its
   conversation's box gets shorter when the text box grows a line, and the
   event arrives before the ResizeObserver in controls.js has put the end
   back in view; and having been put back, it can be moved up again by the
   same forty pixels a moment later, by Safari itself. Either read as the
   reader scrolling away.

   So a scroll event that finds the end out of view stops the following
   only when it moved up, and only when the move is the reader's: it comes
   straight after their own wheel, finger, key or scrollbar (`readerHand`),
   or nothing in the conversation had just changed size, which is how a
   jump to something found on the page or to a link given the focus looks.
   Anything else is the conversation moving by itself, and while following
   is on the end is put back. */
var lastTop = 0;        // where the conversation was, as last seen or put
var fromEnd = 0;        // how far above its end that was
var unseen = false;     // it has been off the screen since it was last seen
var sizedAt = 0;        // when the box or something in it last changed size
var handAt = 0;         // when the reader last reached for it
var handHeld = false;   // a press on the scrollbar, not yet let go
var touchY = null;      // where a finger on it started
var HAND_MS = 600;
var SIZE_MS = 300;

function onTranscriptScroll() {
  var t = transcriptEl();
  if (!t) return;
  // Back on the screen with the place it had dropped: that is not the
  // reader going up to the top, and it is put back first (`keepEnd`).
  if (unseen) { keepEnd(); return; }
  var up = t.scrollTop < lastTop - 1;
  lastTop = t.scrollTop;
  // Nobody scrolls a conversation that is folded away or still unfolding,
  // so a scroll then is the fold's and not the reader's. The column narrows
  // to nothing and widens again, the words wrap and unwrap, and the box
  // moves by itself: on 23 September 2026 a chat about a task that was
  // folded away jumped from its end to its top the instant it began to open
  // again, which read as the reader scrolling up, and "↓ Latest" was over
  // the empty chat that Start chat on the task's page had just opened.
  var app = t.closest('.app');
  if (app && app.classList.contains('no-chat')) return;
  if (Date.now() - shared.foldMoved < FOLD_SETTLES) return;
  var now = Date.now();
  var byHand = handHeld || now - handAt < HAND_MS || now - sizedAt > SIZE_MS;
  // A little slack, because "all the way down" by hand is rarely exact, and
  // a smooth scroll can stop a pixel short.
  if (atBottom(28)) shared.stick = true;
  else if (up && byHand) shared.stick = false;
  else if (shared.stick) keepEnd();
  if (t.clientHeight) fromEnd = t.scrollHeight - t.scrollTop - t.clientHeight;
  updateJump();
  olderNear();
}

/* What was said before the page the conversation opened on (23 October 2026).

   The handshake and each switch hand the page the last rows of a chat
   (`TRANSCRIPT_PAGE` in rouh/runtime.py) and a mark for where the rows
   before them end (`older`). Until then nothing older than those forty rows
   could be read back at all. Now, as the reader nears the top, the page
   before is asked for and drawn above what is there, and the reader stays on
   exactly the line they were reading: nothing moves under them. The cards
   come back the way they always did, a page at a time, and one that was
   waiting at the top for its message goes under it once the message is
   drawn (`cardsUnpark`). */
var OLDER = { chat: '', before: '', loading: false, gen: 0,
              //: Each chat's mark as this page last had it, for a chat slid back into view
              //: along a strip of forks with its conversation as it was (`forkResume`).
              marks: /** @type {Record<string, string>} */ ({}) };
//: How near the top, in pixels, the reader is when the page before is asked for.
var OLDER_NEAR = 600;
var OLDER_PAGE = 40;
//: How long after a page of them failed to come it is asked for again, if the reader is still near the top.
var OLDER_AGAIN = 2000;

/** @param {string} chat @param {string} [mark] */
function olderFrom(chat, mark) {
  OLDER.gen++;
  OLDER.chat = chat || '';
  OLDER.before = mark || '';
  OLDER.loading = false;
  if (chat) OLDER.marks[chat] = OLDER.before;
}

// A chat back on the screen as it was left: it goes on from where it had got to.
/** @param {string} chat */
function olderBack(chat) { olderFrom(chat, OLDER.marks[chat] || ''); }

/* A chat the page moved to itself, along a strip of forks, before the server
   has said where what came before it begins (`stripGo` in app/chats.js): it
   goes on from the mark this page had, and a chat it has no mark for yet
   learns it from the server's answer (`olderLearn`), not taking "none" from
   the move. */
/** @param {string} chat */
function olderMoved(chat) {
  OLDER.gen++;
  OLDER.chat = chat || '';
  OLDER.before = (chat && OLDER.marks[chat]) || '';
  OLDER.loading = false;
}

/** @param {string} chat @param {string} [mark] */
function olderLearn(chat, mark) {
  if (chat && mark && OLDER.marks[chat] === undefined && OLDER.chat === chat) olderFrom(chat, mark);
}

function olderNear() {
  var t = transcriptEl();
  if (!t || HOST.el || !OLDER.before || OLDER.loading || !t.clientHeight) return;
  if (t.scrollTop < OLDER_NEAR) olderLoad();
}

function olderLoad() {
  var chat = OLDER.chat, mark = OLDER.before, gen = OLDER.gen;
  if (!chat || !mark) return;
  OLDER.loading = true;
  fetch('/api/transcript?chat=' + encodeURIComponent(chat) + '&before=' + encodeURIComponent(mark)
        + '&limit=' + OLDER_PAGE, { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) {
      if (!r.ok) throw new Error('the conversation before this answered ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (gen !== OLDER.gen) return;
      if (chat !== CHATS.active) { OLDER.loading = false; return; }
      var t = transcriptEl();
      if (!t || HOST.el) { OLDER.loading = false; return; }
      var first = /** @type {HTMLElement | null} */ (t.querySelector('.turn'));
      var fromTheBottom = t.scrollHeight - t.scrollTop;
      var entries = (data && data.transcript) || [];
      var last = null;
      for (var i = 0; i < entries.length; i++) {
        var drew = drawStored(entries[i], first, last);
        if (drew) last = drew;
      }
      cardsUnpark();
      forkMarksDraw();
      // Exactly where the reader was, measured from the end, which nothing above moves.
      t.scrollTop = t.scrollHeight - fromTheBottom;
      lastTop = t.scrollTop;
      OLDER.before = (data && data.older) || '';
      OLDER.marks[chat] = OLDER.before;
      OLDER.loading = false;
      // A short page that leaves the reader still at the top asks for the one before it.
      olderNear();
    })
    .catch(function (err) {
      console.warn('rouh:', err && err.message);
      if (gen !== OLDER.gen) return;
      OLDER.loading = false;
      // A reader already at the top makes no more scrolling to ask again with.
      setTimeout(function () { if (gen === OLDER.gen) olderNear(); }, OLDER_AGAIN);
    });
}

/* The reader reaching for the conversation. A wheel or a trackpad turned
   up, or a finger drawn down the screen, stops the following at once,
   rather than at the scroll event the move makes, because a reply being
   written puts the end back in view with every word and can win that race
   with a slow hand. A key or a press on the scrollbar marks the scroll it
   makes as the reader's. */
function readerHand(e) {
  var t = transcriptEl();
  if (!t) return;
  var kind = e.type;
  if (kind === 'pointerup' || kind === 'pointercancel') {
    if (handHeld) { handHeld = false; handAt = Date.now(); }
    return;
  }
  handAt = Date.now();
  if (kind === 'pointerdown') {
    // On the scroller itself rather than on anything in it: its scrollbar.
    if (e.target === t) handHeld = true;
    return;
  }
  if (kind === 'keydown') return;
  if (kind === 'touchstart') {
    touchY = e.touches.length === 1 ? e.touches[0].clientY : null;
    return;
  }
  if (kind === 'wheel' ? e.deltaY >= 0 || Math.abs(e.deltaX) > -e.deltaY
    : touchY == null || e.touches.length !== 1 || e.touches[0].clientY - touchY < 6) return;
  if (t.scrollTop <= 0 || !shared.stick) return;
  // A box of its own in the conversation that still has room to go up, a
  // command's output or a long code block, takes the move, and the
  // conversation stays where it is.
  for (var n = e.target; n && n !== t && n.nodeType === 1; n = n.parentNode) {
    if (n.scrollTop > 0 && n.scrollHeight > n.clientHeight) return;
  }
  shared.stick = false;
  updateJump();
}

function scrollDown(force) {
  if (force) shared.stick = true;
  keepEnd();
  updateJump();
}

// The end back in view while following is on, and wherever the
// conversation is now remembered as where it was. Called whenever the box
// or anything in it changes size (controls.js), because a conversation
// that gets shorter moves up by itself, and Safari sends no scroll event
// for that: without it the next event it does send compares against a
// place the conversation has left, and reads as going up.
//
// Off the screen - behind the canvas on a phone, folded away at a desk - the
// box has no layout and no scroll, and the browser drops where it was. So
// nothing is measured then, and when it is back it goes to its end if it was
// following and otherwise to the place the reader left it, measured from the
// end, because whatever arrived meanwhile above or below is not the reader
// moving. Read as a scroll of 0, that place was the very top of the history.
function keepEnd() {
  var t = transcriptEl();
  if (!t) return;
  sizedAt = Date.now();
  if (!t.clientHeight) { unseen = true; return; }
  if (shared.stick) t.scrollTop = t.scrollHeight;
  else if (unseen) t.scrollTop = t.scrollHeight - t.clientHeight - fromEnd;
  unseen = false;
  lastTop = t.scrollTop;
  fromEnd = t.scrollHeight - t.scrollTop - t.clientHeight;
  updateJump();
}

// Something is about to be drawn in the conversation, so it is not empty
// any more, and the welcome goes with the line that said so.
function dropEmpty() {
  // A card beside the conversation being drawn is not the conversation.
  if (HOST.el) return;
  var e = $('transcriptEmpty');
  if (e) e.remove();
  welcomeShow();
}

/* What somebody said, in a bubble.

   A message is a block list with one text block in it, so the words go
   through the same renderer a card's text block goes through. Markdown is
   not a path of its own any more: it is what a text block holds, and it is
   drawn wherever a text block is drawn.

   The words themselves are kept on the node (`__raw`). Read back out of the
   rendered markup they would come back as the text of the markup and not as
   what was written, and a turn is re-rendered more than once - a streamed
   answer settles on its final text, and a sentence said in pieces grows. */
function drawWords(node, text) {
  if (!node) return;
  var words = text == null ? '' : String(text);
  node.__raw = words;
  node.textContent = '';
  var block = null;
  try { block = renderBlock({ block: 'text', text: words }); } catch (err) { block = null; }
  if (block) { node.appendChild(block); node.classList.add('rendered'); }
  else { node.textContent = words; node.classList.remove('rendered'); }
  // Over the whole message and not only this piece of it: an answer written
  // either side of a tool has its numbers above the tool and its list below.
  footnotes((node.closest && node.closest('.turn')) || node);
  // Rouh's answers name tasks by their number; the person's own words are
  // left as they typed them.
  var turn = node.closest && node.closest('.turn');
  if (!turn || !turn.classList.contains('user')) taskRefs(node);
}

// The words a bubble holds, as they were written.
function wordsOf(node) {
  if (!node) return '';
  return node.__raw != null ? node.__raw : (node.textContent || '');
}

/* ---------- a task's number, as its name ----------------------------------

   Petar, 24 October 2026 (fr_493a5928008e), of an answer that said "it's
   reading 98-23 and its deployment step, 98-23-01": "I have no idea what
   98-23 is. I would like all such references to be in their full name and
   also with their icon and a link, so I can click it and see."

   So every task number in an answer - 98-23, 98-23-01, or 140 after the word
   task - is drawn as the number, bold, then the task's icon and name,
   and the whole of it is a link to the task (number first: Petar, the same
   evening, fr_2b1188fc0c55). What each number is
   comes from Rouh (`task_refs`, `searching.refs`), asked once a number for as
   long as the page is open; a number no task is called stays plain text, and
   so does one that is an amount, "10-15 minutes". Spoken, the name is said
   instead (`searching.spoken`).

   A bare number is a task only after the word task. Petar, 28 October 2026
   (fr_2849579ed226): an answer walking him through "Step 1", "step 3" and
   "step 4" of a setup had each of them drawn as tasks 1, 3 and 4 - Lego
   wheels, Ipi group research, a Bricklink store. A step of a task always has
   a dash in its number (98-23), so "step 4" is the fourth step of what is
   being said and never a task. */
var REF_MARK = /(?<![\w.:\/-])(\d{1,3}-\d{2}(?:-\d{2})*)(?![\w-])|\b((?:sub-?task|task|step)\s+)(\d{1,3}-\d{2}(?:-\d{2})*|(?<=(?<![\w-])task\s+)\d{1,3})\b/gi;
var REF_AMOUNT = /^\s*(?:%|percent|min|mins|minutes?|hours?|hrs?|days?|weeks?|months?|years?|seconds?|secs?|people|persons?|euros?|eur|lev|leva|usd|dollars?|pages?|items?|times?|km|kg|m|cm)\b/i;
var REF_SKIP = 'a, code, pre, button, sup.cites, .sources-list, .turn-acts, .card-head, .tool, .task-ref';
//: What Rouh said each number is (`known`), the numbers it said no task is
//: called (`none`), when each still unanswered was asked, and the messages
//: waiting on an answer to be drawn again.
var REFS = { known: {}, none: {}, asked: {}, waiting: [], timer: 0 };
var REF_ASK_AGAIN = 15000;

function refNumbers(text) {
  var out = [], m;
  REF_MARK.lastIndex = 0;
  while ((m = REF_MARK.exec(text))) {
    if (REF_AMOUNT.test(text.slice(m.index + m[0].length))) continue;
    var said = m[1] || m[3];
    out.push({ said: said, start: m[1] ? m.index : m.index + m[2].length, end: m.index + m[0].length });
  }
  return out;
}

/** @param {{title: string, number: string, url: string, icon: string, img: string}} info */
function refLink(info) {
  var a = /** @type {HTMLAnchorElement} */ (el('a', 'task-ref'));
  linkTo(a, info.url);
  a.title = info.title + ' (' + info.number + ')';
  var mark = el('span', 'task-ref-icon');
  mark.setAttribute('aria-hidden', 'true');
  if (info.img) {
    var img = /** @type {HTMLImageElement} */ (el('img'));
    img.src = info.img;
    img.alt = '';
    mark.appendChild(img);
  } else {
    mark.textContent = info.icon || '';
  }
  a.appendChild(el('span', 'task-ref-num', info.number));
  if (mark.firstChild) a.appendChild(mark);
  a.appendChild(el('span', 'task-ref-name', info.title));
  a.addEventListener('click', function (e) {
    if (browserTakes(e)) return;
    e.preventDefault();
    goToAddress(info.url);
  });
  return a;
}

function refText(node, found) {
  var text = node.nodeValue || '', parts = document.createDocumentFragment(), last = 0, any = false;
  for (var i = 0; i < found.length; i++) {
    var info = REFS.known[found[i].said];
    if (!info) continue;
    parts.appendChild(document.createTextNode(text.slice(last, found[i].start)));
    parts.appendChild(refLink(info));
    last = found[i].end;
    any = true;
  }
  if (!any || !node.parentNode) return;
  parts.appendChild(document.createTextNode(text.slice(last)));
  node.parentNode.replaceChild(parts, node);
}

/** @param {Element} root */
function taskRefs(root) {
  if (!root || !root.querySelectorAll) return;
  var walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  var hits = [], want = [], node, at = Date.now();
  while ((node = walk.nextNode())) {
    if (!/\d/.test(node.nodeValue || '')) continue;
    if (node.parentElement && node.parentElement.closest(REF_SKIP)) continue;
    var marks = refNumbers(node.nodeValue || '');
    if (marks.length) hits.push({ node: node, marks: marks });
  }
  for (var i = 0; i < hits.length; i++) {
    var found = hits[i].marks;
    for (var j = 0; j < found.length; j++) {
      var n = found[j].said;
      if (REFS.known[n] || REFS.none[n]) continue;
      if (REFS.asked[n] && at - REFS.asked[n] < REF_ASK_AGAIN) { want.push(''); continue; }
      REFS.asked[n] = at;
      want.push(n);
    }
    refText(hits[i].node, found);
  }
  if (!want.length) return;
  if (REFS.waiting.indexOf(root) < 0) REFS.waiting.push(root);
  var ask = want.filter(Boolean);
  if (ask.length) send({ type: 'task_refs', numbers: ask });
}

/** @param {import('./protocol').FromServer<'task_refs'>} m */
function onTaskRefs(m) {
  var refs = m.refs || {};
  (m.asked || []).forEach(function (n) {
    delete REFS.asked[n];
    if (refs[n] && refs[n].url) REFS.known[n] = refs[n];
    else REFS.none[n] = true;
  });
  var roots = REFS.waiting;
  REFS.waiting = [];
  roots.forEach(function (r) { if (r.isConnected) taskRefs(r); });
}

/* ---------- what a message can do -------------------------------------

   Under every message in the stream, a quiet row of icons: retry, copy and,
   on the person's own messages, edit. It exists because re-asking used to
   mean sending the same words a second time, which left the conversation
   holding the question twice with the old answer in between - which is what
   Petar was looking at on 20 September 2026.

   Retry and edit are one thing with one difference. Both ask the server to
   answer an exchange again (`retry` in PROTOCOL.md); edit sends the new
   wording with it. The answer that comes back takes the old one's place in
   the stream, and the old one is kept: the arrows in this same row step
   between the tries, and the counter says which one is being read.

   An exchange is a question and its answer, and both carry its number in
   `data-root`. That is the whole of what a button needs to know, so the same
   row works under a message drawn live, one read back out of the history,
   and one that arrived from the person's phone.  */

//: Which try of each exchange is live, and how many there are. Keyed by the
//: exchange's number. An exchange asked once is not in here at all.
shared.VERSIONS = {};

//: The retry happening this instant: which exchange, where its answer is to
//: be drawn, and the answer that was taken off the screen to make room. The
//: old one goes back if the new one never arrives, so a retry that is
//: cancelled or that fails leaves the conversation as it found it.
shared.RETRY = null;

function actIcon(kind) {
  var svg = svgEl('svg', {
    viewBox: '0 0 24 24', width: '14', height: '14', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  svg.setAttribute('aria-hidden', 'true');
  if (kind === 'retry') {
    svg.appendChild(svgEl('path', { d: 'M20 12a8 8 0 1 1-2.3-5.6' }));
    svg.appendChild(svgEl('path', { d: 'M20 4v4.5h-4.5' }));
  } else if (kind === 'copy') {
    svg.appendChild(svgEl('rect', { class: 'ico-copy', x: '9', y: '9',
                                    width: '11', height: '11', rx: '2' }));
    svg.appendChild(svgEl('path', { class: 'ico-copy', d: 'M5 15V5a2 2 0 0 1 2-2h10' }));
    svg.appendChild(svgEl('path', { class: 'ico-copied', d: 'M5 13l4.5 4.5L19 7' }));
  } else if (kind === 'edit') {
    svg.appendChild(svgEl('path', { d: 'M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3z' }));
    svg.appendChild(svgEl('path', { d: 'M14.5 7.5l2 2' }));
  } else if (kind === 'prev') {
    svg.appendChild(svgEl('path', { d: 'M14.5 6l-6 6 6 6' }));
  } else if (kind === 'next') {
    svg.appendChild(svgEl('path', { d: 'M9.5 6l6 6-6 6' }));
  } else if (kind === 'info') {
    svg.appendChild(svgEl('circle', { cx: '12', cy: '12', r: '9' }));
    svg.appendChild(svgEl('path', { d: 'M12 11v5.5M12 7.6v.4' }));
  } else if (kind === 'when') {
    svg.appendChild(svgEl('circle', { cx: '12', cy: '12', r: '9' }));
    svg.appendChild(svgEl('path', { d: 'M12 7.5V12l3 2' }));
  } else if (kind === 'say') {
    // A speaker with its sound, and while it reads, a square to stop it.
    svg.appendChild(svgEl('path', { class: 'ico-say', d: 'M4 9.5h3.5L12 5.5v13l-4.5-4H4z' }));
    svg.appendChild(svgEl('path', { class: 'ico-say', d: 'M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11' }));
    svg.appendChild(svgEl('rect', { class: 'ico-stop', x: '7', y: '7', width: '10', height: '10',
                                    rx: '1.5', fill: 'currentColor' }));
  }
  return svg;
}

function actBtn(kind, said) {
  var b = el('button', 'act act-' + kind);
  b.type = 'button';
  b.title = said;
  b.setAttribute('aria-label', said);
  b.appendChild(actIcon(kind));
  return b;
}

// A tick on the icon itself for a moment, then back to the copy icon. The
// button says what happened where the press happened, rather than in a
// notice at the other end of the screen.
function copied(b, said) {
  clearTimeout(b.__copiedFor);
  // What the button says when it is not saying "copied", remembered once. A
  // second press inside the moment would otherwise read the tick's own words
  // back and the button would say "Copied" for ever.
  if (b.__said == null) b.__said = b.getAttribute('aria-label');
  b.classList.add('copied');
  b.title = said || 'Copied';
  b.setAttribute('aria-label', said || 'Copied');
  b.__copiedFor = setTimeout(function () {
    b.classList.remove('copied');
    b.title = b.__said;
    b.setAttribute('aria-label', b.__said);
  }, 1600);
}

function copyFrom(b, text, said) {
  if (!text) return;
  copyText(text).then(function () { copied(b, said); })
    .catch(function (err) { notify(err.message, { tone: 'error' }); });
}

// The words of a message, as they were written rather than as they are drawn.
function turnWords(turn) {
  var parts = [];
  var bodies = turn.querySelectorAll(':scope > .turn-body');
  for (var i = 0; i < bodies.length; i++) {
    if (bodies[i].classList.contains('dots')) continue;
    var said = wordsOf(bodies[i]).trim();
    if (said) parts.push(said);
  }
  return parts.join('\n\n');
}

function exchangeOf(turn) {
  var root = turn && turn.getAttribute('data-root');
  return root ? Number(root) : 0;
}

/* The row itself, built once per message and kept up to date after that.

   Which buttons a message gets is decided by whose message it is: everybody's
   can be retried and copied, and only the person's own can be edited, since
   there is nothing to edit about words Rouh wrote. */
function fitActs(turn) {
  if (!turn || !turn.classList || !turn.classList.contains('turn')) return;
  if (turn.classList.contains('partial') || turn.classList.contains('typing')) return;
  // Not read yet, so there is nothing to ask again, copy or edit until it is.
  if (turn.classList.contains('waiting')) return;
  var mine = turn.classList.contains('user');
  var row = turn.querySelector(':scope > .turn-acts');
  if (!row) {
    row = el('div', 'turn-acts');
    var steps = el('div', 'turn-steps');
    steps.hidden = true;
    row.appendChild(steps);

    var askai = turn.classList.contains('askai');
    // A notice kept in its chat (`noticeMark`) answered nothing, so there is
    // nothing to answer again.
    var notice = turn.classList.contains('notice');
    // A message sent while an answer was being written, and read part way
    // through it: the exchange it is in is the question above's, so asking it
    // again or editing it would be asking that question, not this.
    var steered = turn.classList.contains('steered');
    var retry = actBtn('retry', mine ? 'Ask this again' : 'Answer this again');
    retry.addEventListener('click', function () { askAgain(turn); });
    if (!askai && !notice && !steered) row.appendChild(retry);

    var copy = actBtn('copy', mine ? 'Copy this message' : 'Copy this answer');
    copy.addEventListener('click', function () {
      copyFrom(copy, turnWords(turn), 'Copied the message');
    });
    row.appendChild(copy);

    if (mine && !askai && !steered) {
      var edit = actBtn('edit', 'Edit this message and ask again');
      edit.addEventListener('click', function () { editTurn(turn); });
      row.appendChild(edit);
    }

    var when = actBtn('when', mine ? 'When this was sent' : 'When this was written');
    when.setAttribute('aria-expanded', 'false');
    when.addEventListener('click', function () { toggleWhen(turn, when); });
    row.appendChild(when);

    // After the clock, on what the person receives: the message read aloud in
    // Rouh's own voice (fr_fc456cc390af, app/playback.js `readAloud`).
    if (!mine) {
      var say = actBtn('say', 'Read this aloud');
      say.setAttribute('aria-pressed', 'false');
      say.addEventListener('click', function () { readAloud(say, turnWords(turn)); });
      row.appendChild(say);
    }
    row.__steps = steps;
  }
  // When it was: the stored message's own time, and for one drawn live, the
  // moment it was finished here.
  if (turn.__at == null) {
    var stored = turn.getAttribute('data-at');
    turn.__at = stored ? Number(stored) : Date.now() / 1000;
  }
  // Last in the message, under the words, the cost line and any note, and
  // the clock's line under the row while it is open.
  turn.appendChild(row);
  var told = turn.querySelector(':scope > .turn-when');
  if (told) turn.appendChild(told);
  // A turn that did all its work through tools has no words in it, and a
  // copy button that copies nothing is a button that looks broken.
  var copyBtn = row.querySelector('.act-copy');
  if (copyBtn) copyBtn.disabled = !turnWords(turn);
  var sayBtn = row.querySelector('.act-say');
  if (sayBtn) sayBtn.disabled = !turnWords(turn);
  fitSteps(turn, row);
  return row;
}

/* The back and forward arrows, and "2 of 3" between them.

   They are drawn only where they mean something. Under an answer that is the
   only one there has ever been there is nothing to step to; under a question
   whose wording never changed, a counter would be saying "you asked this
   three times" about words that are identical, so it is the answers that
   carry the counter and the question carries it only once it has really been
   rewritten. */
function fitSteps(turn, row) {
  var steps = row.__steps;
  var root = exchangeOf(turn);
  var info = root ? shared.VERSIONS[root] : null;
  var mine = turn.classList.contains('user');
  var show = !!(info && info.versions > 1 && (!mine || info.edited));
  steps.hidden = !show;
  turn.classList.toggle('has-versions', show);
  if (!show) { steps.textContent = ''; return; }
  steps.textContent = '';
  var back = actBtn('prev', 'The previous version of this');
  back.disabled = info.version <= 1;
  back.addEventListener('click', function () { stepVersion(root, info.version - 1); });
  var count = el('span', 'turn-step-count', info.version + ' of ' + info.versions);
  count.setAttribute('aria-live', 'polite');
  var on = actBtn('next', 'The next version of this');
  on.disabled = info.version >= info.versions;
  on.addEventListener('click', function () { stepVersion(root, info.version + 1); });
  steps.appendChild(back);
  steps.appendChild(count);
  steps.appendChild(on);
}

// Every message of an exchange, brought up to date after its counter changed.
function refreshActs(root) {
  var host = transcriptEl();
  if (!host) return;
  var turns = host.querySelectorAll('.turn[data-root="' + Number(root) + '"]');
  for (var i = 0; i < turns.length; i++) fitActs(turns[i]);
}

/* A line under a message - "you stopped this", "everything above is from
   earlier" - goes under its words and above the row of icons, because the
   row is always the last thing in a message. */
function noteUnder(turn, node) {
  turn.appendChild(node);
  var row = turn.querySelector(':scope > .turn-acts');
  if (row) turn.appendChild(row);
}

/* How the model of an answer was decided (`rouh/modelrouter.py`), drawn in the
   line at the top of its answer (app/turnline.js `routeDraw`). */
function routeMark(turn, route) {
  if (!turn || !route) return;
  routeDraw(turn, route);
  fitActs(turn);
}

/* The exact date and time a message was sent or written, in the person's own
   time zone, said under its row behind the clock icon (fr_bcb7f5453426). One
   is open at a time, and a press anywhere else closes it. */
function whenWords(at) {
  var d = new Date(Number(at) * 1000);
  if (isNaN(d.getTime())) return 'Not known';
  return d.toLocaleString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    timeZoneName: 'short' });
}

function closeWhen(except) {
  var host = transcriptEl();
  if (!host) return;
  var open = host.querySelectorAll('.turn > .turn-when');
  for (var i = 0; i < open.length; i++) {
    if (open[i] === except) continue;
    var b = open[i].parentNode.querySelector(':scope > .turn-acts .act-when');
    if (b) b.setAttribute('aria-expanded', 'false');
    open[i].remove();
  }
}

function toggleWhen(turn, b) {
  var said = turn.querySelector(':scope > .turn-when');
  closeWhen(null);
  if (said) return;
  said = el('p', 'turn-when', whenWords(turn.__at));
  turn.appendChild(said);
  b.setAttribute('aria-expanded', 'true');
}

document.addEventListener('click', function (ev) {
  var t = /** @type {Element|null} */ (ev.target);
  if (t && t.closest && (t.closest('.act-when') || t.closest('.turn-when'))) return;
  closeWhen(null);
});

function tagRoot(turn, root) {
  if (!turn || !root) return;
  turn.setAttribute('data-root', String(root));
  fitActs(turn);
}

// Says whether the asking really went, so the box a message is being
// rewritten in stays open with their words in it when it did not. `tier` is
// Cheaper, Daily or Best pressed beside the "Model decision" line.
function askAgain(turn, text, tier) {
  var root = exchangeOf(turn);
  if (!root) {
    notify('That message cannot be asked again yet - it has not been stored.', { tone: 'warning' });
    return false;
  }
  if (S.busy) {
    notify('Rouh is still answering. Stop it first, then ask again.', { tone: 'warning' });
    return false;
  }
  /* Petar, 4 November 2026: "I later edited the message below, but it submitted
     what I have written before, not what I edited on top." The Cheaper and Smart
     buttons sit on the line just under a message being edited, and a press on one
     asked the exchange again with no words, which is the stored ones. A press
     anywhere that asks this exchange again while its question's box is open asks
     what is typed in the box, and closes it. */
  var editing = null;
  if (text == null) {
    var host = transcriptEl();
    var ask = host ? host.querySelector('.turn.user:not(.steered)[data-root="' + root + '"]') : null;
    if (ask && ask.__editing) {
      editing = ask;
      var typed = ask.__editing.value.trim();
      if (typed && typed !== ask.__editWas) text = typed;
    }
  }
  /** @type {import('./protocol').ToServer<'retry'>} */
  var out = { type: 'retry', root: root };
  if (text != null) out.text = text;
  if (tier) out.tier = tier;
  if (!send(out)) {
    notify('Not connected, so nothing was asked again.', { tone: 'error' });
    return false;
  }
  if (editing && editing.__editClose) editing.__editClose();
  setState('thinking');
  setBusy(true);
  return true;
}

onRedo(function (turn, tier) { return askAgain(turn, null, tier); });

/* Back to the exchange a branch of the conversation was taken at, once the
   conversation has been drawn again from the top (`chat_switched` with
   `redraw`): its question at the top of the screen, as the person left it. */
function branchFocus(root) {
  var host = transcriptEl();
  // Nothing on the screen is from earlier: it is the same conversation, on another branch.
  var notes = host ? host.querySelectorAll('.turn-note.from-earlier') : [];
  for (var i = 0; i < notes.length; i++) notes[i].remove();
  var at = host ? host.querySelector('.turn.user:not(.steered)[data-root="' + Number(root) + '"]')
    || host.querySelector('.turn[data-root="' + Number(root) + '"]') : null;
  if (!at) return;
  // After the page has settled: drawing a chat ends by going to its bottom.
  requestAnimationFrame(function () {
    at.scrollIntoView({ block: 'start' });
    updateJump();
  });
}

function stepVersion(root, version) {
  if (version < 1) return;
  send({ type: 'pick_version', root: root, version: version });
}

/* ---------- editing a message in place --------------------------------

   The bubble becomes the box at the foot of the chat, with the same words
   in it: the text on top, and on the line under it Fork and Send, the
   main box's own two buttons, in the place they have there. Petar, 26 September
   2026 (fr_16b9bf1db8db): "When I edit a message I should have a fork and
   submit buttons the same as in my main input". They are copies of those
   two, lit by the same rule (`forkBtnPaint`), so the two boxes cannot
   drift apart.

   Send asks the new words in place of the old ones (`askAgain`). Fork asks
   them in a fork that comes off just above this message, as the chat stood
   when it was first asked (`rouh/forks.py`), and this message and its
   answer stay as they were. The keys are the main box's too: Enter is a new
   line, Ctrl+Enter sends (`isSendKey`), Ctrl+Shift+Enter forks (Cmd for
   Ctrl on a Mac), and Escape cancels, which is also a button, because this
   is used with a thumb as much as with a keyboard. */
function editTurn(turn, words) {
  if (turn.__editing) { turn.__editing.focus(); return; }
  var body = turn.querySelector(':scope > .turn-body');
  if (!body) return;
  var was = wordsOf(body);
  var box = el('div', 'turn-edit composer-box');
  var area = el('textarea', 'composer-input turn-edit-box');
  area.value = words != null ? words : was;
  area.rows = 1;
  area.setAttribute('enterkeyhint', 'enter');
  area.setAttribute('aria-label', 'Edit this message and ask again');
  var row = el('div', 'turn-edit-acts');
  var cancel = el('button', 'ctl small', 'Cancel');
  cancel.type = 'button';
  cancel.title = 'Keep the message as it was (Esc)';
  var fork = likeComposer('forkBtn', 'Send the edited message as a fork');
  fork.title = 'Fork: ask this in a side chat to the right, from just above this message,'
    + ' and keep this chat as it is (' + forkKeys() + ')';
  var sendIt = likeComposer('sendBtn', 'Send the edited message');
  sendIt.title = 'Send: ask this here, in place of what was asked (' + sendKeys() + ')';
  row.appendChild(cancel);
  row.appendChild(fork);
  row.appendChild(sendIt);
  box.appendChild(area);
  box.appendChild(row);

  function close() {
    turn.__editing = null;
    turn.__editClose = null;
    box.remove();
    body.hidden = false;
    turn.classList.remove('editing');
  }
  function commit() {
    var text = area.value.trim();
    if (!text) { area.focus(); return; }
    if (text === was) { close(); return; }
    if (askAgain(turn, text)) close();
    else area.focus();
  }
  function forkIt() {
    // The keys can be pressed where Fork is not drawn, and a press that
    // does nothing has to say why, as it does in the main box.
    if (fork.hidden) {
      notify('This is the first message in this chat, so there is nothing above it to fork'
        + ' from. Send it to ask it again here.', { tone: 'warning' });
      area.focus();
      return;
    }
    if (forkFromEdit(turn, area.value.trim())) close();
    else area.focus();
  }
  function grow() {
    growToLines(area, Math.round(screenHeight() * 0.45) - row.offsetHeight);
  }
  cancel.addEventListener('click', close);
  fork.addEventListener('click', forkIt);
  sendIt.addEventListener('click', commit);
  area.addEventListener('input', function () { grow(); forkBtnPaint(); });
  area.addEventListener('keydown', function (e) {
    if (e.isComposing) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'Enter' && e.shiftKey && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      forkIt();
    }
    else if (isSendKey(e)) { e.preventDefault(); commit(); }
  });
  // A press on the box around the words, the line under them included, puts
  // the cursor back in them, as it does in the main box.
  box.addEventListener('mousedown', function (e) {
    var t = /** @type {HTMLElement} */ (e.target);
    if (t.closest && t.closest('button, textarea')) return;
    e.preventDefault();
    area.focus();
  });

  body.hidden = true;
  turn.classList.add('editing');
  turn.insertBefore(box, body.nextSibling);
  turn.__editing = area;
  // The words it was opened with, and how it is closed, for a press that asks
  // this exchange again from somewhere else while it is open (`askAgain`).
  turn.__editWas = was.trim();
  turn.__editClose = close;
  turn.__editFork = fork;
  turn.__editSend = sendIt;
  forkBtnPaint();
  grow();
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
}

// One of the main box's buttons, for the box a message is edited in: the
// same element, icon, word and look, with nothing of the original's that
// belongs to it alone - its id, and Send being the main form's submit.
function likeComposer(id, label) {
  var b = $(id).cloneNode(true);
  b.removeAttribute('id');
  b.type = 'button';
  b.hidden = false;
  b.disabled = false;
  b.setAttribute('aria-label', label);
  return b;
}

/* Fork, on the box a message is edited in: the new words asked in a fork
   of this chat that comes off just above the message (`fork_and_ask` in
   rouh/runtime.py, which also carries the files it was asked with). Says
   whether it went, so the box stays open with the words in it when it did
   not. The fork opens to the right and draws what was asked, as a fork
   from the main box does (`forkTypedArrived`). */
function forkFromEdit(turn, text) {
  var root = exchangeOf(turn);
  if (!text) return false;
  if (!root) {
    notify('That message cannot be forked from yet - it has not been stored.', { tone: 'warning' });
    return false;
  }
  if (S.busy) {
    notify('Rouh is still answering. Stop it first, then fork.', { tone: 'warning' });
    return false;
  }
  if (!send({ type: 'fork', from: CHATS.active, text: text, root: root })) {
    notify('Not connected, so nothing was forked.', { tone: 'error' });
    return false;
  }
  // Drawn in the fork once it is open, with the files the message was
  // asked with, which are kept under this chat and go with the new words.
  var here = CHATS.active;
  var files = (turn.__files || []).map(function (f) {
    return Object.assign({}, f, { session_id: f.session_id || here });
  });
  FORKS.typed = { from: here, text: text, files: files };
  setBusy(true);
  forkComeNow({ text: text });
  return true;
}

/* ---------- an exchange being answered again --------------------------- */

// The server has started answering this exchange again. The old answer comes
// off the screen and is kept to one side, and the new one is drawn where it
// was rather than at the bottom of the conversation.
/** @param {Partial<import('./protocol').FromServer<'retry'>>} m a retry, or the one a running turn is part way through */
function onRetryStart(m) {
  var host = transcriptEl();
  var root = Number(m.root);
  if (!host || !root) return;
  finishRetry();
  var ask = host.querySelector('.turn.user[data-root="' + root + '"]');
  if (ask && typeof m.text === 'string' && m.text) {
    var body = ask.querySelector(':scope > .turn-body');
    if (body) drawWords(body, m.text);
  }
  var old = [].slice.call(host.querySelectorAll('.turn.assistant[data-root="' + root + '"]'));
  /* And everything said after this exchange: the new answer begins a branch of
     the conversation, and what followed the old one stays with it (Petar, 4
     November 2026: "it kept the message below instead of forking the
     conversation from that point on"). It comes back if this try is stopped
     before its question is written, and otherwise the server draws the branch
     once the turn is over (`chat_switched` with `redraw`). The messages still
     waiting to be read stay: they are what is being said now. */
  var later = [].slice.call(host.querySelectorAll('.turn[data-root]:not(.waiting)'))
    .filter(function (t) { return Number(t.getAttribute('data-root')) > root; });
  var laterAt = later.map(function (t) {
    var next = t.nextSibling;
    while (next && later.indexOf(/** @type {any} */ (next)) !== -1) next = next.nextSibling;
    return next;
  });
  var anchor = old.length ? old[old.length - 1].nextSibling
    : (ask ? ask.nextSibling : null);
  for (var i = 0; i < old.length; i++) old[i].remove();
  for (var j = 0; j < later.length; j++) later[j].remove();
  while (anchor && anchor.parentNode !== host) anchor = anchor.nextSibling;
  shared.RETRY = { root: root, turnId: m.turn_id, anchor: anchor, removed: old, drew: false,
                   later: later, laterAt: laterAt };
  T.now = { turn: m.turn_id || 0, root: root };
  closeAssistant();
  setState('thinking');
  setBusy(true);
  scrollDown();
}

// The retry is over, one way or the other. An answer that never arrived
// leaves the old one exactly where it was: a retry that was stopped, or that
// failed, must not take an answer away as its parting act.
function finishRetry() {
  var was = shared.RETRY;
  shared.RETRY = null;
  if (!was || was.drew) return;
  var host = transcriptEl();
  if (!host) return;
  var at = was.anchor && was.anchor.parentNode === host ? was.anchor : null;
  for (var i = 0; i < was.removed.length; i++) host.insertBefore(was.removed[i], at);
  // What followed it, back where it was.
  var later = was.later || [];
  for (var j = 0; j < later.length; j++) {
    var next = was.laterAt[j];
    host.insertBefore(later[j], next && next.parentNode === host ? next : null);
  }
}

/* A retry that was replaced or interrupted wrote nothing down at all: the
   question of a cancelled turn never reaches the conversation, so the try
   the person was replacing is still the live one. What the model had written
   before it was cut off goes, and the answer taken off the screen to make
   room for it comes back - otherwise the screen holds an answer the server
   has no record of, under a question whose real answer is the one that was
   just hidden. */
function undoRetry(turnId) {
  if (!shared.RETRY) return;
  if (turnId && shared.RETRY.turnId && Number(turnId) !== Number(shared.RETRY.turnId)) return;
  var host = transcriptEl();
  if (host && shared.RETRY.drew && shared.RETRY.turnId) {
    var drawn = host.querySelectorAll('.turn.assistant[data-turn="' + shared.RETRY.turnId + '"]');
    for (var i = 0; i < drawn.length; i++) drawn[i].remove();
    if (T.assistant && !T.assistant.turn.parentNode) closeAssistant();
    shared.RETRY.drew = false;
  }
  finishRetry();
}

// Which exchange this turn is writing into, and how many tries it has behind
// it now. The first one arrives as soon as the question is stored, which is
// the first moment there is anything for a button to name.
/** @param {import('./protocol').FromServer<'exchange'>} m */
function onExchange(m) {
  var host = transcriptEl();
  var root = Number(m.root);
  if (!host || !root) return;
  if (m.versions > 1) {
    shared.VERSIONS[root] = { version: Number(m.version) || 1,
                       versions: Number(m.versions) || 1, edited: !!m.edited };
  } else {
    delete shared.VERSIONS[root];
  }
  T.now = { turn: m.turn_id || 0, root: root };
  // An exchange begun by a note of Rouh's own - a finished job, a run's
  // question - has no question of the person's anywhere on the screen, and
  // a message of theirs still waiting for its own answer is not it.
  if (!m.note && !host.querySelector('.turn.user:not(.steered)[data-root="' + root + '"]')) {
    // The question of the turn now running: the newest of the person's
    // messages that does not belong to an exchange yet.
    var asks = host.querySelectorAll('.turn.user:not([data-root]):not(.waiting):not(.steered)');
    for (var i = asks.length - 1; i >= 0; i--) {
      if (asks[i].classList.contains('partial')) continue;
      tagRoot(asks[i], root);
      break;
    }
  }
  // And the answer, by the number of the turn writing it, which is the one
  // thing that cannot be mistaken for the turn before it.
  var answers = m.turn_id
    ? host.querySelectorAll('.turn.assistant[data-turn="' + m.turn_id + '"]') : [];
  for (var k = 0; k < answers.length; k++) {
    if (m.route) routeDraw(answers[k], m.route);
    tagRoot(answers[k], root);
  }
  if (T.assistant) {
    var its = T.assistant.turn.getAttribute('data-turn');
    if (!its || !m.turn_id || Number(its) === Number(m.turn_id)) {
      if (m.route) routeDraw(T.assistant.turn, m.route);
      tagRoot(T.assistant.turn, root);
    }
  }
  // The line goes with the question (`routeDraw`), whether or not the answer
  // has begun; an answer drawn before this said which exchange it was (a reply
  // that came quickly) is how an exchange with no question on the screen gets it.
  var question = m.route && !m.note
    ? host.querySelector('.turn.user:not(.steered)[data-root="' + root + '"]') : null;
  if (question) routeMark(question, m.route);
  else if (m.route) {
    var drawn = host.querySelectorAll('.turn.assistant[data-root="' + root + '"]');
    for (var d = 0; d < drawn.length; d++) routeMark(drawn[d], m.route);
  }
  refreshActs(root);
}

// The person stepped to another try. The exchange is drawn again from what
// the server sent, in the place it already had in the stream.
/** @param {import('./protocol').FromServer<'version_picked'>} m */
function onVersionPicked(m) {
  var host = transcriptEl();
  var root = Number(m.root);
  if (!host || !root) return;
  if (m.versions > 1) {
    shared.VERSIONS[root] = { version: Number(m.version) || 1,
                       versions: Number(m.versions) || 1, edited: !!m.edited };
  } else {
    delete shared.VERSIONS[root];
  }
  var mine = [].slice.call(host.querySelectorAll('.turn[data-root="' + root + '"]'));
  var anchor = mine.length ? mine[mine.length - 1].nextSibling : null;
  while (anchor && mine.indexOf(anchor) !== -1) anchor = anchor.nextSibling;
  // A card sits inside the answer that drew it. It is not that answer's to
  // take with it: it goes back in its place once the try is drawn, or where
  // the answer was when its place is not in this one.
  var kept = [];
  for (var i = 0; i < mine.length; i++) {
    var inside = mine[i].querySelectorAll('.card-slot');
    for (var j = 0; j < inside.length; j++) {
      if (anchor) host.insertBefore(inside[j], anchor);
      else host.appendChild(inside[j]);
      kept.push(inside[j]);
    }
    mine[i].remove();
  }
  var rows = Array.isArray(m.messages) ? m.messages : [];
  var last = null;
  for (var k = 0; k < rows.length; k++) {
    var drew = drawStored(rows[k], anchor, last);
    if (drew) last = drew;
  }
  for (var n = 0; n < kept.length; n++) {
    var place = kept[n].__place;
    if (place && place.call) cardInAnswer(kept[n], place.call, null, place.at);
  }
  refreshActs(root);
  scrollDown();
}

/* `before` is where the turn goes when it is not simply the next thing said:
   history being drawn again in the place it already had, and the answer to
   an exchange being answered again, which belongs where the old answer was
   and not at the bottom of the conversation. */
function newTurn(who, cls, before) {
  dropEmpty();
  var turn = el('div', 'turn ' + cls);
  turn.appendChild(el('div', 'turn-who', who));
  var body = el('div', 'turn-body');
  turn.appendChild(body);
  var t = transcriptEl();
  if (before && before.parentNode === t) { t.insertBefore(turn, before); return { turn: turn, body: body }; }
  // Above the messages still waiting to be read, which stay the last thing
  // in the conversation until the model reads them (`drawWaiting`).
  var waiting = t ? firstWaiting(t) : null;
  // Above the three dots, never below them. The dots mean "a reply is being
  // written", so anything that arrives while they are showing was said
  // BEFORE that reply - and appending it underneath put the person's own
  // words below the answer that was still being written for them.
  if (T.typing && T.typing.parentNode === t) t.insertBefore(turn, T.typing);
  else if (waiting) t.insertBefore(turn, waiting);
  else t.appendChild(turn);
  // A chat with something in it is one that can be forked.
  forkBtnPaint();
  return { turn: turn, body: body };
}

/* One row of stored conversation, drawn where it belongs.

   Used by both halves of the same job: the whole transcript read back on a
   handshake, and one exchange drawn again when the person steps to another
   try of it.  */
function drawStored(e, before, last) {
  var parts = e && Array.isArray(e.parts) && e.parts.length ? e.parts : null;
  if (!e || (!e.text && !parts && !(e.attachments && e.attachments.length))) return null;
  // A turn the person stopped. It is stored as one of their messages,
  // because that is what the model reads, but it was never something they
  // said: on screen it is the line under the answer that stops there.
  if (e.stopped) {
    if (last) noteUnder(last.turn, el('div', 'turn-note stopped', STOP_SAID));
    return null;
  }
  var mine = e.role === 'user';
  // The next round of an answer the one before it began: live they were one
  // answer under one name, words and the lines of its calls in the order
  // they came, and read back they still are (fr_3f1814427840).
  if (!mine && !e.askai && sameAnswer(last, e, before)) {
    drawParts(last, e);
    return last;
  }
  var turn = newTurn(mine ? 'You' : 'Rouh', mine ? 'user' : 'assistant', before);
  if (e.askai) askaiMark(turn, e.askai, mine);
  if (e.notice && !mine) noticeMark(turn);
  if (e.steered && mine) turn.turn.classList.add('steered');
  // Which row of the conversation this is, and when it was. A card says
  // which message it came after, and this is what it is matched against
  // when the stream is put back together (`placeByAnchor`).
  if (e.id != null) turn.turn.setAttribute('data-msg', String(e.id));
  if (e.ts != null) turn.turn.setAttribute('data-at', String(e.ts));
  // And which exchange it is part of, which is what retry, edit and the
  // arrows all name.
  if (e.root != null) {
    turn.turn.setAttribute('data-root', String(e.root));
    if (e.versions > 1) {
      shared.VERSIONS[Number(e.root)] = { version: Number(e.version) || 1,
                                   versions: Number(e.versions),
                                   edited: !!e.edited };
    }
  }
  drawTurnFiles(turn, e.attachments);
  if (parts && !mine) {
    turn.body.remove();
    drawParts(turn, e);
  } else if (!mine && !e.text && (e.attachments || []).some(isDrawn)) {
    // Only pictures, as the picture controls write them: the set is the
    // answer, as it was while it was drawn (`picPlace`), with no empty words
    // under it.
    turn.body.remove();
  } else {
    drawWords(turn.body, e.text);
    turn.body.__row = e.id;
  }
  // What Master's look-ups did for it, kept for the line in its answer.
  if (mine && e.recall) recallDraw(turn.turn, e.recall, false);
  // And how the answer was made, in one line at the top of its first part
  // (app/turnline.js): every step of it (`rouh/turntrace.py`), else what was kept.
  if (!mine && e.route && e.route.trace && e.root != null) {
    var host = transcriptEl();
    var first = host && host.querySelector('.turn.assistant[data-root="' + Number(e.root) + '"]');
    if (first === turn.turn || (first && !first.querySelector(':scope > .tline'))) {
      traceDraw(first, e.route.trace, false);
    }
  }
  if (!mine && e.route) routeDraw(turn.turn, e.route);
  if (!mine) lineFor(turn.turn);
  fitActs(turn.turn);
  return turn;
}

/* What Master's look-ups are doing for one of the person's messages, drawn in
   the line of its answer (`rouh/recalling.py`, app/turnline.js). */
/** @param {import('./protocol').FromServer<'recall'>} m */
function onRecallMessage(m) {
  onRecall(transcriptEl(), m);
}

// Whether a stored row of Rouh's is more of the answer drawn just before it:
// the same exchange, and nothing - no card, no note - in between.
function sameAnswer(last, e, before) {
  if (!last || !last.turn || e.root == null) return false;
  var t = last.turn;
  if (!t.classList.contains('assistant') || t.classList.contains('askai')
      || t.classList.contains('notice')) return false;
  if (t.getAttribute('data-root') !== String(e.root)) return false;
  var host = transcriptEl();
  if (!host || t.parentNode !== host) return false;
  var next = t.nextElementSibling;
  return before ? next === before : !next;
}

/* One stored answer's words and tool lines, in the bubble it belongs to.
   Words are a `.turn-body` each and lines a `.tools` row each, which is the
   shape a live answer has (`onDelta`, `toolsRow`), so it looks the same and
   copies the same. Placed above the row of buttons, which stays last. */
function drawParts(turn, e) {
  var t = turn.turn;
  var acts = t.querySelector(':scope > .turn-acts');
  var parts = Array.isArray(e.parts) && e.parts.length ? e.parts
    : (e.text ? [{ text: e.text }] : []);
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i], node;
    if (Array.isArray(p.tools)) {
      // Lines with no words between them are one row, across rounds too,
      // as they were live: the row the next tool joins (`toolsRow`).
      var prev = acts ? acts.previousElementSibling : t.lastElementChild;
      var joins = prev && prev.classList.contains('tools');
      node = joins ? prev : el('div', 'tools');
      // Each line says which row it is from, as each piece of words does: a
      // card drawn by one round of the answer goes after that round's lines
      // and before the next one's (`cardInAnswer`).
      for (var k = 0; k < p.tools.length; k++) {
        var chip = storedTool(p.tools[k]);
        chip.__row = e.id;
        node.appendChild(chip);
      }
      if (joins) continue;
    } else if (p.text) {
      node = el('div', 'turn-body');
      node.__row = e.id;
      t.insertBefore(node, acts);
      drawWords(node, p.text);
      continue;
    } else {
      continue;
    }
    t.insertBefore(node, acts);
  }
  // Every row it holds, so a card drawn after any of them is placed under it.
  if (e.id != null) {
    var had = t.getAttribute('data-msgs');
    t.setAttribute('data-msgs', (had ? had + ' ' : '') + String(e.id));
  }
  if (acts) fitActs(t);
}

function restoreTranscript(entries) {
  // The server has sent the conversation so far. Without this a reload showed
  // an empty column and looked like everything had been forgotten, which is
  // a poor answer to "what were we just saying". Says whether it drew
  // anything, because what was drawn is what the cards are placed among.
  //
  // Nothing in it is an answer too: the conversation is empty, not unread.
  T.heard = true;
  if (!Array.isArray(entries) || !entries.length) return false;
  var t = transcriptEl();
  if (!t || t.querySelector('.turn')) return false;   // live turns already drawn
  dropEmpty();
  var last = null;
  for (var i = 0; i < entries.length; i++) {
    var drew = drawStored(entries[i], null, last);
    if (drew) last = drew;
  }
  // Not while the person has said nothing here yet: under Rouh's own first words alone,
  // written into General as the first run ends (`firstrun.GREETING`), nothing came earlier
  // than they did. Those words are an answer of Rouh's since 9 November 2026, so the model
  // reads them, and no longer a notice; what is asked is whether anybody talked.
  var talked = entries.some(function (e) { return e && !e.notice && e.role === 'user'; });
  if (last && talked) {
    noteUnder(last.turn, el('div', 'turn-note from-earlier', 'Everything above is from earlier.'));
  }
  // And where each fork of it came off, among the messages it came off.
  forkMarksDraw();
  scrollDown(true);
  return !!last;
}

/* A chat beside this one on its strip of forks, drawn into `host` - the
   conversation of its card (`forkLook`) - by the very hand that draws it
   when it is slid onto (`restoreTranscript`), from the very transcript
   (`chat_peek`), with its own forks' marks. So the card and the chat are the
   same thing, and the slide onto it ends on what was already showing.
   Petar, 15 October 2026 (fr_60918f90d0bb): "There is a snap and after the
   snap some refresh happens. Can we not have it?"

   Nothing of the conversation on screen is touched: the record of its turn,
   its versions and its marks are put back as they were, whatever happens. */
/** @param {HTMLElement} host @param {any[]} entries @param {any[]} marks */
function drawTranscriptInto(host, entries, marks) {
  var keptT = {}, k;
  for (k in T) if (Object.prototype.hasOwnProperty.call(T, k)) keptT[k] = T[k];
  var versions = shared.VERSIONS, ownMarks = FORKS.marks;
  var last = null;
  HOST.el = host;
  shared.VERSIONS = {};
  FORKS.marks = Array.isArray(marks) ? marks : [];
  try {
    for (var i = 0; i < (entries || []).length; i++) {
      var drew = drawStored(entries[i], null, last);
      if (drew) last = drew;
    }
    if (last) noteUnder(last.turn, el('div', 'turn-note', 'Everything above is from earlier.'));
    forkMarksDraw();
  } finally {
    HOST.el = null;
    shared.VERSIONS = versions;
    FORKS.marks = ownMarks;
    for (k in keptT) if (Object.prototype.hasOwnProperty.call(keptT, k)) T[k] = keptT[k];
    forkBtnPaint();
  }
  return !!last;
}

/* One chat, on the screen: what was said and what was drawn, in the order it
   happened.

   The two halves arrive separately - the words come down the socket with
   `ready`, the cards are fetched from /api/canvas/cards - and the cards are
   placed among the words, so the words have to be drawn first. That is the
   whole reason this exists rather than the two being started side by side.

   A reconnect draws nothing: this conversation is already on the screen, and
   reading the cards back over it would undo anything the person has taken
   off it.

   Except when the socket went in the middle of a turn (`cut`). Then the
   screen holds that turn as it was when the socket went - a tool still
   "running", an answer half written - and the record may hold more: the
   finished answer, or the sentence written when a restart cut it short
   (`Memory.mark_interrupted`). So the words are drawn again from the record,
   as a reload would draw them, and this chat's cards are read back among
   them while the canvas stays as it is. Petar, 19 October 2026
   (fr_433563836c27): a restart in the middle of a turn left it on screen as
   it was until the page was reloaded. */
/** @param {any[]} entries @param {boolean} [cut] */
function openTheStream(entries, cut) {
  var on = transcriptEl();
  if (cut && on && on.querySelector('.turn')) {
    // A reader who had scrolled up is put back where they were, measured
    // from the end, rather than thrown to it: a socket that came back is not
    // the reader moving.
    var fromEnd = shared.stick || !on.clientHeight ? -1 : on.scrollHeight - on.scrollTop;
    wipeTranscript();
    restoreTranscript(entries);
    resetStreamCards();
    if (fromEnd >= 0 && on.scrollHeight > fromEnd) {
      shared.stick = false;
      on.scrollTop = on.scrollHeight - fromEnd;
      lastTop = on.scrollTop;
      updateJump();
    }
    return;
  }
  var drawn = restoreTranscript(entries);
  welcomeShow();
  var t = transcriptEl();
  if (!drawn && t && t.querySelector('.turn')) return;
  resetCanvas();
}

// Take everything off the transcript and leave it as it was when the page
// opened. Two things ask for this: the Clear button, and switching to
// another chat, which is the same act - what is on the screen is one chat's
// conversation, and the next one's is about to be drawn in its place.
function wipeTranscript() {
  hideTyping();
  transcriptEl().innerHTML = '';
  // The chat's name goes back above everything, including the note below:
  // it is the head of the conversation, and a page of older messages read
  // back is placed under that note and so stays under this too.
  var title = el('p', 'stream-title', '');
  title.id = 'streamTitle';
  title.hidden = true;
  transcriptEl().appendChild(title);
  // The note that says there is more history above goes back first, because
  // everything read back is placed under it.
  var older = el('p', 'stream-older', 'Loading what came before…');
  older.id = 'streamOlder';
  older.hidden = true;
  transcriptEl().appendChild(older);
  var p = el('p', 'empty', 'Say something, or type below.');
  p.id = 'transcriptEmpty';
  transcriptEl().appendChild(p);
  T.assistant = null;
  T.dots = null;
  T.partial = null;
  T.typed = null;
  T.lastUser = null;
  T.lastUserTurn = null;
  // Another conversation's exchanges are not this one's.
  T.now = { turn: 0, root: 0 };
  shared.RETRY = null;
  shared.VERSIONS = {};
  welcomeShow();
  forkBtnPaint();
}

/* A question asked in Ask AI and its answer, in this conversation.

   Petar, 27 September 2026 (fr_dd4ac24658fa): "ask ai doesn't get included
   in the orb and it should". So every exchange on the This page side is
   written into the conversation on the Rouh side as well, which is the one
   the orb and the voice carry on (`Memory.add_askai`). It is drawn as what
   it was: the person's question, with the page it was about and the passage
   they selected over it, and the answer Ask AI gave, both labelled. Neither
   offers to be asked again or edited here, because that would ask Rouh a
   question that was Ask AI's, without the page in front of it. */
function askaiMark(turn, about, mine) {
  turn.turn.classList.add('askai');
  var who = turn.turn.querySelector(':scope > .turn-who');
  if (who) who.textContent = mine ? 'You, in Ask AI' : 'Rouh, in Ask AI';
  if (!mine) return;
  var head = el('div', 'askai-about');
  head.appendChild(el('span', 'askai-page', 'On ' + (about.title || about.doc || 'the page')));
  if (about.passage) head.appendChild(el('span', 'askai-passage', clipWords(about.passage, 160)));
  turn.body.parentNode.insertBefore(head, turn.body);
}

/* A notice's words, kept in the chat it leads to (`Memory.add_notice`).

   Petar, 12 October 2026 (fr_c8fb46a5a132): "That same content in the
   notification needs to be posted in the chat for permanence. Otherwise
   notifications disappear and I can never reread then". So a finished run's
   notice is one of Rouh's messages in its chat too, every word of it, drawn
   the moment it is said and read back with the chat. It answered nothing, so
   it is not offered to be answered again (`fitActs`). */
function noticeMark(turn) {
  turn.turn.classList.add('notice');
}

function askaiSaid(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  for (var i = 0; i < rows.length; i++) drawStored(rows[i], null, null);
  scrollDown();
}

/** @param {import('./protocol').FromServer<'transcript_add'>} m */
function addTurnFromElsewhere(m) {
  // Said or typed on the phone while this desktop was open, or the other way
  // round. It is drawn exactly as a restored turn is, with the same labels:
  // it is the same person and the same conversation, so nothing marks it out
  // as having come from somewhere else.
  var text = m.text || '';
  var files = m.attachments;
  if (!text && !(files && files.length)) return;
  var mine = m.role === 'user';
  // Sent on another device while the answer here is being written, and not
  // read yet: drawn waiting, as it is there.
  if (mine && m.steer) { drawWaiting(text, files, m.steer); return; }
  var turn = newTurn(mine ? 'You' : 'Rouh', mine ? 'user' : 'assistant');
  if (m.ts != null) turn.turn.__at = Number(m.ts);
  if (m.notice && !mine) {
    noticeMark(turn);
    // Its row, so a card drawn after it is put after it (`placeByAnchor`).
    if (m.id != null) turn.turn.setAttribute('data-msg', String(m.id));
    if (m.id != null) turn.turn.setAttribute('data-root', String(m.id));
  }
  drawTurnFiles(turn, files);
  drawWords(turn.body, text);
  // Which exchange it is arrives a moment later, with `exchange`, and the row
  // under it grows its arrows then. See onExchange.
  fitActs(turn.turn);
  scrollDown();
}

function onStt(text, final, turnId) {
  // A typed message is already on screen. If the server echoes it back as a
  // transcript, correct that turn rather than printing the sentence twice.
  if (T.typed) {
    if (!final) return;
    drawWords(T.typed.body, text);
    T.typed = null;
    closeAssistant();
    scrollDown(true);
    return;
  }
  // Words that carry on the question already on screen - said before Rouh
  // had finished answering it - join that message rather than starting one.
  var joins = !!(turnId && T.lastUser && T.lastUserTurn === turnId && T.lastUser.turn.parentNode);
  if (!final) {
    // The transcriber keeps sending "still being said" updates after it has
    // already settled on a sentence, repeating words it has just finalised.
    // Drawing those made a second, dashed copy of a message that was already
    // on screen.
    if (settled(text)) return;
    if (joins) { showTail(text); scrollDown(); return; }
    if (!T.partial) {
      var p = newTurn('You', 'user partial');
      T.partial = p;
    }
    T.partial.body.textContent = text;
    scrollDown();
    return;
  }
  hideTail();
  if (joins) {
    dropPartial();
    if (text) {
      drawWords(T.lastUser.body, wordsOf(T.lastUser.body) + ' ' + text);
      remember(text);
    }
  } else if (T.partial) {
    T.partial.turn.classList.remove('partial');
    drawWords(T.partial.body, text);
    T.lastUser = T.partial;
    T.lastUserTurn = turnId || null;
    T.partial = null;
    remember(text);
  } else if (text) {
    // One thought said with pauses arrives as several transcripts, and they
    // all go to the model as one question. Printing each as its own message
    // made six bubbles for one sentence and, worse, made the screen disagree
    // with what the model was actually sent - so an answer that was correct
    // for its input looked stupid against what was on screen.
    //
    // Pieces of the same turn are therefore joined into one message.
    if (turnId && T.lastUser && T.lastUserTurn === turnId) {
      drawWords(T.lastUser.body, wordsOf(T.lastUser.body) + ' ' + text);
    } else {
      T.lastUser = newTurn('You', 'user');
      drawWords(T.lastUser.body, text);
      T.lastUserTurn = turnId || null;
    }
    remember(text);
  }
  if (T.lastUser) fitActs(T.lastUser.turn);
  closeAssistant();
  scrollDown(true);
}

/* One sign that Rouh is working, and only one: three dots while it thinks
   or waits on a tool, a blinking cursor while its words arrive. It sits after
   the last thing already on screen, never above it.

   Seen live on a phone: a Rouh bubble with nothing in it but a blinking
   cursor, then a finished tool, a running job, and under them a second Rouh
   bubble with three dots. The model's first run had gone straight to its
   tools, so a bubble was opened for words that never came, and the next run
   drew its own dots below: two signs at once, the cursor above everything
   that had happened since.

   So a Rouh turn is built from its parts as they arrive - words, a row of
   tools, more words - and a bubble for words is drawn only once there are
   words to put in it. */
function ensureAssistant(turnId) {
  if (T.assistant) {
    if (turnId && !T.assistant.turn.getAttribute('data-turn')) {
      T.assistant.turn.setAttribute('data-turn', String(turnId));
    }
    return T.assistant;
  }
  // Anything still marked as being said was never finished. It cannot be
  // part of the question now being answered, so it does not stay on screen.
  dropPartial();
  hideTail();
  // An exchange being answered again has a place in the stream already, and
  // the new answer belongs in it rather than at the bottom.
  var where = shared.RETRY && !shared.RETRY.drew ? shared.RETRY.anchor : null;
  var a = newTurn('Rouh', 'assistant', where);
  if (shared.RETRY && !shared.RETRY.drew) shared.RETRY.drew = true;
  if (T.now.root && T.now.turn === turnId) {
    a.turn.setAttribute('data-root', String(T.now.root));
  }
  a.body.remove();
  a.body = null;
  a.text = '';        // every word of the answer, in the order written
  a.seg = null;       // the words being written now
  a.segText = '';
  a.tools = null;     // the row the next tool joins, while nothing is written after it
  a.caret = el('span', 'caret');
  // Which question it answers, so an answer the person talked over can be
  // found and taken away again. See onRetract.
  if (turnId) a.turn.setAttribute('data-turn', String(turnId));
  T.assistant = a;
  // The turn takes over from the dots that stood in for it, and the timeline moves with it.
  traceMove(T.typing, a.turn);
  hideTyping();
  return a;
}

// A part of the answer goes after everything already in the turn.
function addPart(a, node) {
  a.turn.insertBefore(node, T.dots && T.dots.parentNode === a.turn ? T.dots : null);
}

// Put up the one sign - 'thinking', 'writing' or nothing - and take down
// whatever showed before.
function placeSign(kind) {
  var a = T.assistant;
  if (a && a.caret.parentNode) a.caret.remove();
  if (T.dots && T.dots.parentNode) T.dots.remove();
  T.dots = null;
  if (kind === 'writing' && a && a.seg) {
    hideTyping();
    a.seg.appendChild(a.caret);
  } else if (kind === 'thinking' && a) {
    hideTyping();
    T.dots = dotsBody();
    a.turn.appendChild(T.dots);
  } else if (kind === 'thinking') {
    showTyping();
  } else {
    hideTyping();
  }
  scrollDown();
}

/* The sign while Rouh works: what it is doing now, in a few words (`trace.now`),
   beside one pulsing dot. Petar, 23 October 2026: "The bouncing dots replaced by a
   label for what is actually going on." Until the server's first word on it, the
   message is on its way. */
function dotsBody() {
  var body = el('div', 'turn-body dots');
  body.setAttribute('role', 'status');
  body.appendChild(el('span', 'dot'));
  body.appendChild(el('span', 'dots-said', TRACE.now || 'Sending'));
  return body;
}

/** The label in every sign on the page, as the live timeline says it. */
function dotsSay(words) {
  TRACE.now = words || '';
  var host = transcriptEl();
  if (!host || !words) return;
  Array.prototype.forEach.call(host.querySelectorAll('.dots .dots-said'), function (n) {
    if (n.textContent !== words) n.textContent = words;
  });
}

/** The live timeline of the turn running in this chat (`trace`). */
var TRACE = { now: '', turn: '' };

/* The timeline of the turn now running (`trace`, `rouh/turntrace.py`): the label
   in place of the dots, the "Model decision" line the moment the router decides,
   and the lanes at the top of the reply, or of the placeholder standing for it. */
/** @param {import('./protocol').FromServer<'trace'>} m */
function onTrace(m) {
  var host = transcriptEl();
  var tl = m.trace;
  if (!host || !tl) return;
  if (TRACE.turn !== m.turn_id) { TRACE.turn = m.turn_id; TRACE.now = ''; }
  if (tl.state === 'running') dotsSay(tl.now);
  // The person's message it answers, whose memory and model decision go in the same line.
  var question = null;
  if (!tl.note) {
    question = host.querySelector('.turn.user[data-trace="' + m.turn_id + '"]');
    if (!question && tl.root) question = host.querySelector('.turn.user:not(.steered)[data-root="' + tl.root + '"]');
    if (!question) {
      var asks = host.querySelectorAll('.turn.user:not([data-root]):not(.waiting):not(.steered):not(.partial)');
      question = asks.length ? asks[asks.length - 1] : null;
    }
    if (question) question.setAttribute('data-trace', String(m.turn_id));
  }
  var reply = host.querySelector('.turn.assistant[data-turn="' + m.turn_id + '"]');
  if (!reply && T.assistant) {
    var its = T.assistant.turn.getAttribute('data-turn');
    if (!its || its === String(m.turn_id)) reply = T.assistant.turn;
  }
  if (!reply && tl.state === 'running' && S.busy) {
    showTyping();
    reply = T.typing;
  }
  if (reply) traceDraw(reply, Object.assign({ turn_id: m.turn_id }, tl), true, question);
  // How the model was decided, as soon as it was.
  if (tl.route && question) routeDraw(question, tl.route);
}

function onDelta(text, turnId) {
  var fresh = !T.assistant || !T.assistant.seg;
  // Words after a tool start on a line of their own, below it.
  if (fresh) text = String(text || '').replace(/^\s+/, '');
  if (!text) return;
  var a = ensureAssistant(turnId);
  if (!a.seg) {
    a.seg = el('div', 'turn-body');
    a.segText = '';
    addPart(a, a.seg);
    a.tools = null;
  }
  a.segText += text;
  a.text += text;
  // Plain while it is still arriving: the caret lives in this node and it is
  // rewritten on every delta. `settleWords` draws the finished answer as the
  // text block it is.
  a.seg.__raw = a.segText;
  a.seg.textContent = a.segText;
  placeSign('writing');
}

// A reply that was opened and never written. The turn is over, so a sign
// under "Rouh" is a lie: it says something is coming and nothing is. It
// happens when a turn does all its work through tools and has nothing left
// to say. A turn with a tool keeps the tool; one with nothing at all goes.
function closeEmptyAssistant() {
  if (!T.assistant) return;
  if ((T.assistant.text || '').trim()) return;
  placeSign(null);
  if (T.assistant.turn && !T.assistant.turn.querySelector('.tool')) {
    if (T.assistant.turn.parentNode) T.assistant.turn.remove();
    T.assistant = null;
    return;
  }
  closeAssistant();
}

function closeAssistant() {
  var a = T.assistant;
  if (a && a.caret && a.caret.parentNode) a.caret.remove();
  if (T.dots && T.dots.parentNode) T.dots.remove();
  T.dots = null;
  T.assistant = null;
}

function onDone(text, usage, turnId, spent) {
  var words = typeof text === 'string' ? text : '';
  var written = T.assistant ? (T.assistant.text || '') : '';
  // An answer the person's message was read in the middle of is two bubbles,
  // and this one is only what came after it.
  if (T.split && (!turnId || T.split === turnId)) words = written;
  T.split = 0;
  if (!words.trim() && !written.trim()) {
    // Nothing was said. A "Rouh" heading over an empty box reads as a reply
    // that failed to arrive - live, one request drawn as five questions left
    // three of them - so none is drawn, and one a tool opened keeps only the
    // tool. See closeEmptyAssistant.
    hideTyping();
    closeEmptyAssistant();
    T.typed = null;
    scrollDown();
    return;
  }
  var a = ensureAssistant(turnId);
  placeSign(null);
  settleWords(a, words);
  // "I stopped hearing it" turned out to be this button, switched off and
  // forgotten. Silence with no explanation is indistinguishable from a fault,
  // so the first silent reply says which it is.
  if (!cfg.voiceReply && !S.toldAboutVoice) {
    S.toldAboutVoice = true;
    var note = el('div', 'turn-note');
    note.textContent = 'Spoken replies are off. Turn them on with the Voice replies button.';
    a.turn.appendChild(note);
  }
  // What the turn cost, under the answer. The server works the money out
  // from the API's own numbers (`rouh/costs.py`); the cache figure is
  // here because a turn with a high one is a cheap turn, and that is the
  // only reason a person would want to see it.
  if (spent && spent.sent !== undefined) {
    var u = el('div', 'turn-usage');
    var calls = spent.calls || [];
    var bits = [num(spent.sent) + ' in / ' + num(spent.output) + ' out'];
    // How many requests the turn took: one per round of tools, and each
    // sends the whole conversation again, so fewer is cheaper and quicker.
    if (calls.length > 1) bits.push(calls.length + ' requests');
    if (spent.sent) bits.push(Math.round((spent.cached || 0) * 100) + '% cached');
    if (spent.priced) bits.push(spent.money || '');
    if (spent.trimmed) {
      bits.push(spent.trimmed + ' old result' + (spent.trimmed === 1 ? '' : 's') + ' trimmed');
    }
    u.textContent = bits.filter(Boolean).join(' \u00b7 ');
    // Request by request is where the cache shows: the first of a turn
    // writes the conversation to it, and every one after should read nearly
    // all of it back (`rouh/promptcache.py`).
    u.title = 'Tokens sent and written, how much of what was sent came out of the '
      + 'cache, and what it cost' + calls.map(function (c, i) {
        var sent = (c.input || 0) + (c.cache_read || 0) + (c.cache_write || 0);
        return '\nRequest ' + (i + 1) + ': ' + num(sent) + ' in, ' + num(c.cache_read || 0)
          + ' read from the cache, ' + num(c.cache_write || 0) + ' written to it, '
          + num(c.input || 0) + ' uncached; ' + num(c.output || 0) + ' out';
      }).join('');
    a.turn.appendChild(u);
  } else if (usage && (usage.input_tokens || usage.output_tokens)) {
    var was = el('div', 'turn-usage');
    was.textContent = (usage.input_tokens || 0) + ' in / ' + (usage.output_tokens || 0) + ' out tokens';
    a.turn.appendChild(was);
  }
  fitActs(a.turn);
  closeAssistant();
  T.typed = null;
  scrollDown();
}

// The finished answer is the one to keep. One piece of writing takes the
// final text whole, as it always did, since it has any word the stream
// missed. Pieces written either side of tools keep their places.
function settleWords(a, final) {
  var segs = [], i;
  for (i = 0; i < a.turn.children.length; i++) {
    var c = a.turn.children[i];
    if (c.classList.contains('turn-body') && !c.classList.contains('dots')) segs.push(c);
  }
  if (!segs.length) {
    if (!final.trim()) return;
    var seg = el('div', 'turn-body');
    drawWords(seg, final.trim());
    addPart(a, seg);
    a.text = final;
    return;
  }
  if (segs.length === 1) {
    if (final.length >= a.text.length) a.text = final;
    drawWords(segs[0], a.text.trim());
    return;
  }
  // The words arrive plain while they are being written, because a caret has
  // to sit in them and they are replaced on every delta. The finished answer
  // is drawn the way every other text block is drawn.
  for (i = 0; i < segs.length; i++) drawWords(segs[i], wordsOf(segs[i]).trim());
}

// The person carried on before the answer was finished, so the answer to
// what they had said so far goes: from the screen, as it goes from what the
// model is sent. A tool it had already run stays in view, because it ran.
function onRetract(turnId) {
  placeSign(null);
  var t = transcriptEl();
  var bubbles = t ? [].slice.call(t.querySelectorAll('.turn.assistant[data-turn="' + turnId + '"]')) : [];
  if (T.assistant && !T.assistant.turn.getAttribute('data-turn')) bubbles.push(T.assistant.turn);
  for (var i = 0; i < bubbles.length; i++) {
    var bubble = bubbles[i];
    if (bubble.querySelector('.tool')) {
      var said = [].slice.call(bubble.querySelectorAll('.turn-body'));
      for (var k = 0; k < said.length; k++) said[k].remove();
    } else if (bubble.parentNode) {
      bubble.remove();
    }
  }
  if (T.assistant && bubbles.indexOf(T.assistant.turn) !== -1) T.assistant = null;
  // The same is true of an answer taken back: it was never the conversation,
  // so an exchange being answered again goes back to the try it had.
  undoRetry(turnId);
  setBusy(false);
}

/* While a reply is being written: the send button is off, one sign says
   Rouh is at work, and the jump-to-latest pill is allowed to show. Every
   way a turn can end has to switch this back off, including the ways that
   are failures - a send button stuck off for ever would make a bad minute
   look like a broken product. */
function setBusy(on) {
  // Busy again means a new turn, and a new turn is never the stopped one.
  if (on) {
    S.stopped = false;
    // A new turn starts with none of the last one's: no words yet, none of
    // its tools open, and the clock the watchdog reads starting now.
    S.textDone = false;
    S.tools = 0;
    noteTurnSign();
  }
  // Every way a turn can end comes through here, which is where a retry
  // that produced nothing puts the answer it took down back on the screen.
  if (!on) finishRetry();
  S.busy = !!on;
  // Send stays usable while an answer is being written: what is sent then
  // waits, and the model reads it at its next step (`sendTyped`).
  var b = $('sendBtn');
  if (b) b.disabled = false;
  forkBtnPaint();
  placeSign(on ? 'thinking' : null);
  updateJump();
  showStop();
  // An answer from a task's page that came into this chat while Rouh was
  // answering something else in it goes now, once this ending has settled
  // (`answerHeldGo`).
  if (!on && ANSWER_HELD) setTimeout(answerHeldGo, 0);
}

/* ---------- stopping a turn ------------------------------------------

   Rouh is an agentic loop, not one call: by the time the person has had
   enough, the turn may be three model calls and half a dozen tool calls in,
   with a sentence already playing out of the speaker. So Stop does three
   things at once and does not wait for any of them to agree with each other:

   1. the audio already queued in this browser is killed here, in this
      function, before anything is sent. Waiting for the server to answer
      means a second and a half of Rouh still talking after the press,
      which is the whole thing the person pressed the button about;
   2. POST /api/stop sets the flag the loop reads, so nothing more is
      thought, called or said (rouh/stopping.py);
   3. the screen settles at once: the sign goes, the answer is closed off
      with a line saying it was stopped, and the orb's own line ends.

   What it never does is reach past Rouh. A background job, a delegated
   task and a run of the one program all carry on, and the note says so.  */

//: The line drawn under an answer the person stopped. The second sentence is
//: the important one: "stop" on its own reads as "stop everything", and what
//: was handed to a worker is the person's work and is still running.
var STOP_SAID = 'You stopped this. Background jobs, tasks and runs already started carry on.';

// Whether there is a turn to stop: something is being written, thought about
// or said out loud. The speaking state matters as much as the other two,
// because the answer is finished long before the last sentence of it is out
// of the speaker, and that is exactly when Stop is pressed.
function turnIsRunning() {
  return !!(S.busy || S.state === 'thinking' || S.state === 'speaking' || stillSpeaking());
}

// Sound of the answer still to come out of this browser: the server is in
// the middle of sending a turn's audio, or there are buffers scheduled on
// the speaker that have not played yet. The server calls a turn over as soon
// as it has sent the last of the bytes, and the last second of it is still
// in here, so without this Stop vanished while Rouh was audibly talking.
//
// Bytes waiting for a speaker that has never been allowed to start are
// deliberately not counted. Those can sit there for a minute (`pbHoldCap`),
// and they have their own notice on screen.
function stillSpeaking() {
  if (S.stopped) return false;
  return PB.turn !== null || PB.sources.length > 0;
}

function showStop() {
  var b = $('stopBtn');
  if (b) b.hidden = !turnIsRunning();
}

/* ---------- a turn cannot be left running on screen for ever ----------

   Everything above is driven by messages, and a message that never arrives
   leaves the screen wrong with nothing to put it right. That is the bug
   this section exists for: the Stop control stayed on screen, red and
   pressable, and Rouh's own line stayed lit on the orb, both of them long
   after the answer had been given.

   There are two ends to it. The server now says a turn is over however it
   ended, including the turns that were cancelled or replaced
   (`Session.turn_is_over`). This is the other end, which does not trust
   that: if a turn has been on screen with nothing arriving for it, the page
   asks the server what is really running, and if not even that gets an
   answer it settles the screen itself. The worst a lost message can now
   cost is TURN_GONE_MS of a Stop control that does nothing.  */

//: Nothing has arrived for this long, so ask whether the turn is real.
var TURN_QUIET_MS = 4000;
//: Asked, and not even that was answered. The socket is not delivering, so
//: there is nothing more coming for this turn whatever the server thinks.
var TURN_GONE_MS = 10000;
//: The answer is written and no sound has started. Speech follows the last
//: word by a moment, never by this long, so past it there is none coming.
var SPEECH_GRACE_MS = 2500;

// Something of this turn arrived. Called for anything that belongs to one:
// its words, its tools, its states, the sound of it.
function noteTurnSign(turnId) {
  S.turnSign = now();
  if (turnId && turnId > S.turn) S.turn = turnId;
}

/* A turn that was already running in the thread this page has just arrived
   in: a reload in the middle of an answer, or opening a thread that is still
   being answered after walking away from it.

   The server holds the turn, not the page (`Turn` in rouh/server.py), so
   what it has written so far comes with the thread. It is drawn as the live
   answer and everything after it arrives the ordinary way, which is what
   makes coming back show one answer being written rather than half of one,
   frozen, with a Stop control that does nothing.

   Called with nothing when the thread is quiet, and then it is the other
   half of the same job: the screen settles, because what was on it belonged
   to the thread that has just been left. */
// Whether the question of a turn still running is drawn already: by this
// page, which typed it, or as the last thing said on a screen a reconnect
// did not draw again (`openTheStream`).
function askedOnScreen(text) {
  if (T.typed && T.typed.turn && T.typed.turn.parentNode) return true;
  var t = transcriptEl();
  var users = t ? t.querySelectorAll('.turn.user .turn-body') : [];
  var last = users.length ? /** @type {any} */ (users[users.length - 1]) : null;
  return !!last && String(last.__raw != null ? last.__raw : last.textContent).trim() === String(text).trim();
}

function pickUpRunningTurn(running) {
  // The high-water mark is per thread and this page has just changed
  // threads: a turn number from the thread it left says nothing about this
  // one, and left in place it would swallow this turn's own ending.
  S.turn = running && running.turn_id ? running.turn_id : 0;
  if (!running) { endTurnOnScreen(); return; }
  S.stopped = false;
  // A turn answering an exchange again was part way through when this page
  // arrived, and the history it has just drawn still holds the answer being
  // replaced. It comes off now, exactly as it would have if the page had
  // been here when the retry started.
  if (running.root) {
    onRetryStart({ root: running.root, turn_id: running.turn_id,
                   // The question as it is being asked this time, which the
                   // conversation does not hold yet: a retry writes nothing
                   // down until the model has answered.
                   text: running.asked || '' });
  } else if (running.asked && !askedOnScreen(running.asked)) {
    // A question the conversation does not hold yet (`Turn.picture`), so
    // the history just drawn has no bubble for it. Asked a moment ago -
    // here, by a page that had not yet heard which chat it was in when the
    // question was sent and has read that chat back since, or on another
    // device - it is drawn as it was asked, above the answer to it. Before 21
    // October 2026 it was left out, and only a reload showed it.
    T.typed = newTurn('You', 'user');
    drawWords(T.typed.body, running.asked);
    fitActs(T.typed.turn);
  }
  setBusy(true);
  setState(running.state === 'speaking' ? 'speaking' : 'thinking');
  if (running.said) onDelta(running.said, running.turn_id);
  // And its timeline so far, with the label in place of the dots (`trace`).
  if (running.trace) onTrace(/** @type {any} */ ({ type: 'trace', turn_id: running.turn_id, trace: running.trace }));
  // And what the person sent since, which the model has not read yet.
  var waiting = Array.isArray(running.waiting) ? running.waiting : [];
  for (var i = 0; i < waiting.length; i++) {
    drawWaiting(waiting[i].text || '', waiting[i].attachments, waiting[i].id);
  }
  noteTurnSign(running.turn_id);
  showStop();
}

// The turn on this screen is over, whatever the server did or did not say.
// Used by the watchdog below and by a socket that has gone away. What is
// already scheduled on the speaker is left to play out and takes the word in
// the title bar with it when it drains (`src.onended`); nothing more of the
// turn is expected to arrive, which is what clearing PB.turn says.
function endTurnOnScreen() {
  PB.turn = null;
  T.split = 0;
  setBusy(false);
  closeEmptyAssistant();
  if (!PB.sources.length) setState('idle');
  showStop();
}

// A turn the server has declared over. It arrives for the turns that did not
// end tidily - cancelled, replaced by the next question, or ended by a
// socket going away - which are exactly the ones that used to end in
// silence. Carries the number of the turn it is about, because by the time
// it arrives a newer turn may have started, and that one is not over.
function onTurnEnd(turnId) {
  noteTurnSign();
  // A turn that ended behind a newer one says nothing about the newer one,
  // which is still running and still stoppable.
  if (turnId && S.turn && turnId < S.turn) return;
  // This message is only ever sent for a turn that did not end the way a
  // turn is meant to, which for a retry means nothing of it was stored.
  undoRetry(turnId);
  endTurnOnScreen();
}

function watchTheTurn() {
  // The sound draining is the one thing that changes what Stop should be
  // doing without any message arriving, so it is re-read here every beat.
  showStop();
  if (!turnIsRunning() || S.stopped) return;
  if (PB.sources.length) { noteTurnSign(); return; }   // it is talking
  if (!S.turnSign) S.turnSign = now();
  var quiet = now() - S.turnSign;
  // The answer is written, nothing of Rouh's own is running, and no sound
  // has started. Then the turn is over and the speech is not coming.
  if (S.textDone && !S.tools && quiet >= SPEECH_GRACE_MS) { endTurnOnScreen(); return; }
  if (quiet < TURN_QUIET_MS) return;
  // Ask. The server is the only thing that knows whether the model is still
  // going, and its answer is a state message, which counts as a sign of life
  // and puts this clock back - so a genuinely long turn is never cut short
  // while the socket is working.
  if (now() - S.turnAsked >= TURN_QUIET_MS && send({ type: 'get_state' })) {
    S.turnAsked = now();
    return;
  }
  // Not even the asking got through, for long enough that nothing is coming
  // down this socket. Whatever the server is doing, this page is not being
  // told about it, so the turn on screen is finished here.
  if (quiet >= TURN_GONE_MS) endTurnOnScreen();
}

// The person pressed Stop or Escape. Both controls check for themselves that
// there is something to stop; this checks again, because a line saying "you
// stopped this" under an answer that finished an hour ago would be a lie.
// setBusy and setState both put the button away, so it is not done again here.
function stopTheTurn() {
  if (!turnIsRunning()) return;
  S.stopped = true;
  stopPlayback();
  markStopped();
  setBusy(false);
  setState('idle');
  fetch('/api/stop', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    // The conversation on this tab's screen, which is this tab's own:
    // another tab may be talking in another one.
    body: JSON.stringify({ chat: CHATS.active || '' }),
    credentials: 'same-origin'
  }).catch(function () {
    // The flag never landed, so the turn is still going on the server. Say
    // so rather than leave a screen that claims it stopped.
    notify('The stop did not reach the server. Say something to take over the turn.', { tone: 'error' });
  });
}

// The line under the answer, drawn once however many ways the stop arrives.
// A turn that was nothing but tools keeps its tools and gets the line under
// them; a turn that had not drawn anything yet gets a line of its own, so a
// press is never silent.
function markStopped() {
  placeSign(null);
  var host = T.assistant ? T.assistant.turn : null;
  if (!host) {
    var t = transcriptEl();
    var turns = t ? t.querySelectorAll('.turn.assistant') : null;
    host = turns && turns.length ? turns[turns.length - 1] : null;
  }
  if (!host) {
    var turn = newTurn('Rouh', 'assistant');
    turn.body.remove();
    host = turn.turn;
  }
  if (!host.querySelector('.turn-note.stopped')) {
    host.appendChild(el('div', 'turn-note stopped', STOP_SAID));
  }
  closeAssistant();
  scrollDown();
}

// The last few things the transcriber settled on, so a repeat of one of them
// is recognised as a repeat rather than drawn again.
var SETTLED = [];

function remember(text) {
  var key = norm(text);
  if (!key) return;
  SETTLED.push(key);
  if (SETTLED.length > 6) SETTLED.shift();
}

function settled(text) {
  var key = norm(text);
  if (!key) return false;
  for (var i = 0; i < SETTLED.length; i++) {
    if (SETTLED[i] === key || SETTLED[i].indexOf(key) === 0) return true;
  }
  return false;
}

function norm(text) {
  return String(text || '').toLowerCase().replace(/[^a-z0-9\u0400-\u04ff]+/g, ' ').trim();
}

function dropPartial() {
  if (T.partial) {
    if (T.partial.turn.parentNode) T.partial.turn.remove();
    T.partial = null;
  }
}

// The words still being said, shown at the end of the message they will join.
function showTail(text) {
  var body = T.lastUser.body;
  if (!T.tail || T.tail.parentNode !== body) {
    hideTail();
    T.tail = el('span', 'tail');
    body.appendChild(T.tail);
  }
  T.tail.textContent = ' ' + text;
}

function hideTail() {
  if (T.tail && T.tail.parentNode) T.tail.remove();
  T.tail = null;
}

function showTyping() {
  if (T.typing || !transcriptEl()) return;
  dropEmpty();
  var turn = el('div', 'turn assistant typing');
  turn.appendChild(el('div', 'turn-who', 'Rouh'));
  turn.appendChild(dotsBody());
  var t = transcriptEl();
  var waiting = firstWaiting(t);
  if (waiting) t.insertBefore(turn, waiting);
  else t.appendChild(turn);
  T.typing = turn;
  scrollDown();
}

/* ---------- a message sent while the answer is being written ----------

   Petar, 17 October 2026 (fr_9fdbf628eb75): "Can you make it so that I can
   add messages during a response and it can be taken into consideration,
   instead of waiting till the last tool call". So Send works while Rouh is
   answering. What is sent then does not stop the answer: it is drawn at the
   bottom, marked as not read yet, and the model reads it at its next step -
   when the tool it is running comes back, before it decides what to do next
   (`Brain._take_steer` in rouh/brain.py). Then the mark comes off and the
   message moves to where it was read, with the answer so far above it and
   what Rouh writes after reading it below, which is the order the model
   saw. If the answer ends first, it is the next question. */

//: The mark under a message sent while the answer was being written.
var WAITING_SAID = 'Rouh reads this after the step it is on';

function firstWaiting(host) {
  return host ? host.querySelector(':scope > .turn.user.waiting') : null;
}

// Drawn the moment it is sent, last in the conversation, under the answer
// still being written.
function drawWaiting(text, files, id) {
  var t = transcriptEl();
  if (!t || !id) return;
  if (t.querySelector('.turn[data-steer="' + id + '"]')) return;
  dropEmpty();
  var w = { turn: el('div', 'turn user waiting'), body: el('div', 'turn-body') };
  w.turn.appendChild(el('div', 'turn-who', 'You'));
  w.turn.appendChild(w.body);
  w.turn.setAttribute('data-steer', id);
  t.appendChild(w.turn);
  drawTurnFiles(w, files);
  drawWords(w.body, text);
  w.turn.appendChild(el('div', 'turn-note waiting-note', WAITING_SAID));
  forkBtnPaint();
  scrollDown(true);
}

/* The model has read them. Mid-answer, the answer so far is closed where it
   stands and what Rouh writes next goes into a bubble of its own under
   them; when the answer had ended first (`question`), the first of them is
   simply the next question, and is tagged with its exchange when that
   arrives (`onExchange`). */
/** @param {import('./protocol').FromServer<'steer_taken'>} m */
function onSteerTaken(m) {
  var host = transcriptEl();
  var taken = Array.isArray(m.taken) ? m.taken : [];
  if (!host || !taken.length) return;
  if (!m.question && T.assistant) {
    var was = T.assistant.turn;
    closeAssistant();
    fitActs(was);
    T.split = m.turn_id || 0;
  }
  hideTyping();
  for (var i = 0; i < taken.length; i++) {
    var one = taken[i];
    var b = host.querySelector('.turn[data-steer="' + one.id + '"]');
    // A tab that never drew it waiting drew it as an ordinary message, or
    // will read it back with the conversation.
    if (!b) continue;
    b.classList.remove('waiting');
    var mark = b.querySelector(':scope > .waiting-note');
    if (mark) mark.remove();
    if (!m.question) {
      b.classList.add('steered');
      if (m.root) b.setAttribute('data-root', String(m.root));
      if (one.message_id != null) b.setAttribute('data-msg', String(one.message_id));
    }
    var still = firstWaiting(host);
    if (still && still !== b) host.insertBefore(b, still);
    else if (!still) host.appendChild(b);
    fitActs(b);
  }
  if (S.busy) placeSign('thinking');
  scrollDown();
}

function hideTyping() {
  if (T.typing) {
    if (T.typing.parentNode) T.typing.remove();
    T.typing = null;
  }
}

// The pill appears whenever the reader has scrolled up, not only while a
// reply is arriving. Scrolling back to the bottom puts it away.
//
// It used to require a reply to be in flight, which meant scrolling up to
// read something older left no way back except scrolling all the way down by
// hand - exactly the situation it exists for.
//
// And it answers to where the conversation is, not only to whether it is
// meant to be following: following with the end out of view is a
// conversation that was left behind, and it is put back there. Petar,
// 17 October 2026 (fr_5fcd2acebed7): "it puts me on the very top. Then I
// don't have a latest button and I have to scroll all the way down."
function updateJump() {
  var j = $('jumpLatest');
  if (!j) return;
  var t = $('transcript');
  if (shared.stick && t && t.clientHeight && !atBottomOf(t, 28)) {
    t.scrollTop = t.scrollHeight;
    lastTop = t.scrollTop;
    fromEnd = t.scrollHeight - t.scrollTop - t.clientHeight;
  }
  j.hidden = shared.stick;
}

function atBottomOf(t, slack) {
  return t.scrollHeight - t.scrollTop - t.clientHeight <= slack;
}

var toolEls = {};

function toolsRow(turnId) {
  var a = ensureAssistant(turnId);
  if (!a.tools) {
    a.tools = el('div', 'tools');
    addPart(a, a.tools);
    // Words written after this go below it, not into the words above.
    a.seg = null;
  }
  return a.tools;
}

/* The two of Anthropic's own tools whose line opens onto what was asked and
   what came back, rather than onto the input as text. They run inside the
   model's turn: what they were sent arrives after the call has started, as
   `tool_update`, and what they found arrives with `tool_end`. Until
   24 September 2026 neither was drawn, so a search opened onto two quote
   marks: its input, which was still empty when the line was made. */
var WEB_TOOLS = {
  web_search: { key: 'query', asked: 'Searched for', running: 'Still searching…',
                none: 'The search came back with no results.' },
  web_fetch: { key: 'url', asked: 'Asked for', running: 'Still reading the page…',
               none: 'Nothing came back from the page.' },
  // The same address again, when web_fetch could not get the page: opened
  // in a headless browser by Rouh itself (rouh/fetchfallback.py). Its line
  // is under the failed fetch's, with the page it read or both reasons.
  browser_fetch: { key: 'url', asked: 'Opened', running: 'Opening the page in a browser…',
                   none: 'The browser read nothing from the page.',
                   read: 'web_fetch could not get this page, so it was opened in a browser instead.' },
  // A link to Rouh itself, read inside Rouh as the person and never through
  // the web (rouh/rouhlinks.py): asked for by the model, or put in place of a
  // web_fetch of one (rouh/fetchfallback.py).
  read_rouh_link: { key: 'url', asked: 'Address', running: 'Reading it inside Rouh…',
                    none: 'Read inside Rouh, as you, and never through the web.',
                    read: 'Read inside Rouh, as you, and never through the web.' },
  // Rouh loading a tool before it uses one (rouh/toolsearch.py): every tool
  // is declared and none is loaded until a search asks for it by name. The
  // line says what was loaded; the pattern it asked with is inside.
  tool_search_tool_regex: { key: 'pattern', asked: 'Looked for', running: 'Loading…',
                            none: 'No tool matched.', loads: true },
  tool_search_tool_bm25: { key: 'query', asked: 'Looked for', running: 'Loading…',
                           none: 'No tool matched.', loads: true },
  find_tools: { key: 'query', asked: 'Looked for', running: 'Loading…',
                none: 'No tool matched.', loads: true },
  // OpenAI's own search, on a turn Luna answers (`rouh/luna.py`).
  tool_search: { key: 'query', asked: 'Looked for', running: 'Loading…',
                 none: 'No tool matched.', loads: true }
};

/* Rouh's own tools that run a command, and the argument the command is in
   (`worklabel.COMMANDS` on the server). Their line opens onto the command
   and, under it, what it printed, each as the text it is and each in a
   space of its own about five lines tall that scrolls by itself. Asked for
   on 26 September 2026: "I already know that this is a command, so I don't
   need to see the curly braces the json the 'command:'". Until then it
   opened onto the input as JSON, one line wide, and what came back was
   nowhere but the first 160 characters on the line itself. */
var COMMAND_TOOLS = { run_command: 'command' };

// What a call was sent. Rouh sends it as JSON text cut at 400 characters
// (brain.py `_shallow`), so it is read back into an object where it still
// parses and kept as the text it is where the cut left it unfinished. It
// used to go through JSON.stringify as it came, which drew the text of the
// text: every quote escaped, all of it on one line. Nothing at all is null.
function toolInput(input) {
  if (input == null || input === '') return null;
  if (typeof input !== 'string') return input;
  try { return JSON.parse(input); } catch (e) { return input; }
}

// What a web tool was asked for: the query, or the address.
function toolAsked(rec) {
  var web = WEB_TOOLS[rec.name], input = toolInput(rec.input);
  return web && input && typeof input === 'object' ? String(input[web.key] || '') : '';
}

function toolLine(rec) {
  var web = WEB_TOOLS[rec.name];
  if (web && web.loads) return rec.done ? (rec.summary || 'done') : 'loading';
  var asked = toolAsked(rec);
  var said = rec.name === 'web_search' && asked ? '“' + asked + '”' : asked;
  if (!rec.done) return said || 'running';
  var summary = rec.summary || (rec.ok ? 'done' : 'failed');
  return said ? said + ' · ' + summary : summary;
}

function drawTool(rec) {
  var line = toolLine(rec);
  rec.sum.textContent = line;
  rec.sum.title = line;
  var box = rec.body;
  box.textContent = '';
  var command = toolCommand(rec);
  if (command != null) { drawCommand(box, rec, command); return; }
  var web = WEB_TOOLS[rec.name];
  if (!web) {
    var input = toolInput(rec.input);
    box.appendChild(input == null ? el('p', 'tool-quiet', 'It was given nothing.')
      : el('pre', null, typeof input === 'string' ? input : JSON.stringify(input, null, 2)));
    return;
  }
  var asked = toolAsked(rec);
  if (asked) {
    var head = el('div', 'tool-asked');
    head.appendChild(el('span', 'tool-k', web.asked));
    head.appendChild(el('span', 'tool-q', asked));
    box.appendChild(head);
  }
  if (!rec.done) {
    box.appendChild(el('p', 'tool-quiet', web.running));
  } else if (!rec.ok) {
    var why = rec.summary || 'failed';
    box.appendChild(el('p', 'tool-quiet bad', why.charAt(0).toUpperCase() + why.slice(1) + '.'));
  } else if (!rec.results.length) {
    box.appendChild(el('p', 'tool-quiet', web.none));
  } else {
    if (web.read) box.appendChild(el('p', 'tool-quiet', web.read));
    // A search found a list; a fetch read one page, which is not numbered.
    var list = rec.results.length > 1 ? el('ol', 'tool-results') : el('ul', 'tool-results only');
    rec.results.forEach(function (r) { list.appendChild(toolResult(r)); });
    box.appendChild(list);
  }
}

// The command a call ran, or null for a call that runs none. A command
// whose input did not arrive as the object it is is drawn the way any other
// input is, as the text that came.
function toolCommand(rec) {
  var key = COMMAND_TOOLS[rec.name], input = key ? toolInput(rec.input) : null;
  return input && typeof input === 'object' ? String(input[key] || '') : null;
}

// A command opened: the command, and under it what it printed. Neither is
// labelled. The line above them already names the tool, and the command is
// the one written brighter.
function drawCommand(box, rec, command) {
  var io = el('div', 'tool-io');
  io.appendChild(command ? el('pre', 'tool-cmd', command)
    : el('p', 'tool-cmd tool-quiet', 'It was given no command.'));
  var out = rec.output == null ? '' : String(rec.output);
  if (!rec.done) {
    io.appendChild(el('p', 'tool-out tool-quiet', 'Still running…'));
  } else if (out) {
    io.appendChild(el('pre', 'tool-out' + (rec.ok ? '' : ' bad'), out));
  } else if (!rec.ok) {
    var why = rec.summary || 'failed';
    io.appendChild(el('p', 'tool-out tool-quiet bad', why.charAt(0).toUpperCase() + why.slice(1) + '.'));
  } else {
    io.appendChild(el('p', 'tool-out tool-quiet', 'It printed nothing.'));
  }
  box.appendChild(io);
}

// One page a search found, or the page a fetch read: its title, and its
// address as a link that opens it. Only a web address is ever made a link.
function toolResult(r) {
  var li = el('li');
  var url = String(r.url || '');
  var link = /^https?:\/\//i.test(url);
  /** @type {any} */
  var a = el(link ? 'a' : 'span', 'tool-result');
  if (link) {
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
  }
  a.appendChild(el('span', 'tool-rt', r.title || url || 'Untitled'));
  if (url) a.appendChild(el('span', 'tool-ru', url));
  li.appendChild(a);
  if (r.age) li.appendChild(el('span', 'tool-age', r.age));
  return li;
}

/* A card in the answer that drew it.

   Petar, 5 October 2026 (fr_6b1852e8f32e): "when I chat, I first get a card
   then the explanation streams but it streams above the card", and "when I
   refresh the chat, somehow the card goes above the text answer". The card
   was put after the whole of Rouh's bubble, and the words written after it
   went on growing inside that bubble, above it; read back, it was placed by
   the message it came after, which the words could be either side of. His
   rule since: everything in the order it came, and the same after a reload.

   So a card drawn while an answer is being written is a part of that answer,
   like a row of tool lines: under the line of the call that drew it, with
   whatever is written or called after it below it. Read back it is put in
   the same place by the same means: `call` is the call it sits under, and
   `row` the stored message it came after, for a card with no call to go by.
   Says whether it found a place in an answer; when it did not, the card goes
   where it always went, between messages. */
function cardInAnswer(slot, call, row, at) {
  var host = transcriptEl();
  if (!host) return false;
  var after = null, turn = null;
  if (call) {
    var chips = host.querySelectorAll('.turn.assistant .tool[data-call="' + CSS.escape(String(call)) + '"]');
    after = chips.length ? chips[chips.length - 1] : null;
  }
  if (!after && row != null) {
    turn = host.querySelector('.turn.assistant[data-msg="' + Number(row) + '"], ' +
                              '.turn.assistant[data-msgs~="' + Number(row) + '"]');
    // The last thing that row drew: its words or a line of its calls.
    var kids = turn ? turn.children : [];
    for (var i = 0; i < kids.length; i++) {
      var kid = kids[i];
      if (kid.classList.contains('tools')) {
        for (var k = 0; k < kid.children.length; k++) {
          var r = kid.children[k].__row;
          if (r != null && Number(r) <= Number(row)) after = kid.children[k];
        }
      } else if (kid.__row != null && Number(kid.__row) <= Number(row)) {
        after = kid;
      }
    }
  }
  if (!after) return false;
  slot.__place = { call: call || null, row: row, at: at };
  slot.__at = at;
  if (after.classList.contains('tool')) {
    // Lines started after the card are below it, in a row of their own.
    var line = after.parentNode;
    if (after.nextSibling) {
      var rest = el('div', 'tools');
      while (after.nextSibling) rest.appendChild(after.nextSibling);
      line.parentNode.insertBefore(rest, line.nextSibling);
    }
    after = line;
  }
  // After any card already under the same place that was put there first.
  var at_ = after.nextSibling;
  while (at_ && at_.nodeType === 1 && at_.classList.contains('card-slot') &&
         !(at != null && at_.__at != null && Number(at_.__at) > Number(at))) {
    at_ = at_.nextSibling;
  }
  after.parentNode.insertBefore(slot, at_);
  return true;
}

/* The same, for a card arriving now, while the answer it belongs to is
   being written: at the end of it, under the call that drew it, and the
   next words and the next lines start again below it. */
function cardInLiveAnswer(slot, call) {
  var a = T.assistant, host = transcriptEl();
  if (!a || !host || a.turn.parentNode !== host) return false;
  var at = Date.now() / 1000;
  if (!(call && a.turn.querySelector('.tool[data-call="' + CSS.escape(String(call)) + '"]') &&
        cardInAnswer(slot, call, null, at))) {
    slot.__place = { call: null, row: null, at: at };
    slot.__at = at;
    addPart(a, slot);
  }
  a.seg = null;
  a.tools = null;
  return true;
}

/** @param {import('./protocol').FromServer<'tool_start'>} m */
function onToolStart(m) {
  var row = toolsRow(m.turn_id);
  var rec = toolChip(m);
  row.appendChild(rec.chip);
  toolEls[m.id || m.name] = rec;
  // One more of Rouh's own calls open. A turn with one of these running
  // can go a long time with nothing else arriving, and it is still running.
  S.tools++;
  // Rouh is still at work while the tool runs: the sign goes after it.
  placeSign(S.busy ? 'thinking' : null);
}

/* A line read back out of the chat's history, drawn as it was left live
   (`memory.Memory.note_tool`): what `tool_start` made it, what
   `tool_update` gave it and what `tool_end` said. One whose call never
   ended - the turn was stopped, or the server went away under it - is not
   drawn running, because nothing is: it says it did not finish. */
function storedTool(line) {
  var rec = toolChip(line);
  var ended = !!line.done;
  rec.chip.classList.remove('running');
  rec.chip.classList.add(ended && line.ok !== false ? 'ok' : 'bad');
  rec.done = true;
  rec.ok = ended && line.ok !== false;
  rec.summary = ended ? (line.summary || '') : 'did not finish';
  rec.results = Array.isArray(line.results) ? line.results : [];
  rec.output = line.output == null ? null : String(line.output);
  drawTool(rec);
  return rec.chip;
}

// One line of a call: the chip and what it opens onto, not yet anywhere.
function toolChip(m) {
  var chip = el('div', 'tool running' + (COMMAND_TOOLS[m.name] ? ' command' : ''));
  // Which call it is, which is what a card the call drew is placed under.
  if (m.id || m.name) chip.setAttribute('data-call', String(m.id || m.name));
  var lineBtn = el('button', 'tool-btn');
  lineBtn.type = 'button';
  lineBtn.setAttribute('aria-expanded', 'false');
  var mark = el('span', 'tool-mark');
  var name = el('span', 'tool-name', m.name || 'tool');
  var sum = el('span', 'tool-sum');
  lineBtn.appendChild(mark);
  lineBtn.appendChild(name);
  lineBtn.appendChild(sum);
  chip.appendChild(lineBtn);

  var body = el('div', 'tool-body');
  body.hidden = true;
  chip.appendChild(body);

  lineBtn.addEventListener('click', function () {
    body.hidden = !body.hidden;
    chip.classList.toggle('open', !body.hidden);
    lineBtn.setAttribute('aria-expanded', body.hidden ? 'false' : 'true');
    scrollDown();
  });

  var rec = { chip: chip, sum: sum, body: body, name: m.name || '', input: m.input,
              nameEl: name, done: false, ok: true, summary: '', results: [], output: null };
  drawTool(rec);
  return rec;
}

/* ---------- a tool that has to be asked about ----------

   A named tool stops before it runs and the person is asked (permissions.py
   on the server). It arrives as one message with the question and its two
   answers on it, and it is drawn under the turn it belongs to, where the
   tool chips are, because that is where the person is already looking.

   On the orb the same call goes red and dashed and says NEEDS YOU, which is
   the one thing on the orb that must never be left alone. Two pictures of
   one piece of work, not two pieces of work. */

var asks = {};

/** @param {import('./protocol').FromServer<'permission_ask'>} m */
function onPermissionAsk(m) {
  var row = toolsRow(m.turn_id);
  var box = el('div', 'ask');
  box.setAttribute('data-ask', m.id || '');
  box.appendChild(el('div', 'ask-q', m.question || 'May I do that?'));
  if (m.detail) box.appendChild(el('div', 'ask-detail', m.detail));

  var buttons = el('div', 'ask-buttons');
  var yes = el('button', 'ask-yes', 'Allow');
  var no = el('button', 'ask-no', 'Not now');
  yes.type = no.type = 'button';
  function answer(allow) {
    // Both buttons off at once: a second press while the first is in flight
    // is a second answer to a question that has already been answered.
    yes.disabled = no.disabled = true;
    send({ type: 'permission_answer', id: m.id, allow: allow });
  }
  yes.addEventListener('click', function () { answer(true); });
  no.addEventListener('click', function () { answer(false); });
  buttons.appendChild(yes);
  buttons.appendChild(no);
  box.appendChild(buttons);

  row.appendChild(box);
  asks[m.id] = { box: box, yes: yes, no: no };
  scrollDown();
}

/** @param {Partial<import('./protocol').FromServer<'permission_done'>> & {gone?: boolean}} m a permission_done, or a permission_gone said as one */
function onPermissionDone(m) {
  var rec = asks[m.id];
  if (!rec) return;
  delete asks[m.id];
  rec.yes.disabled = rec.no.disabled = true;
  var allowed = m.answer === 'allow';
  rec.box.classList.add(allowed ? 'ask-allowed' : 'ask-refused');
  var said = allowed ? 'Allowed.'
    : m.timed_out ? 'Nobody answered, so it was not done.'
      : m.gone ? 'Already answered.' : 'Not done.';
  var note = el('div', 'ask-said', said);
  rec.box.replaceChild(note, rec.box.lastChild);
  scrollDown();
}

// One of Anthropic's own calls has been sent its whole input.
/** @param {import('./protocol').FromServer<'tool_update'>} m */
function onToolUpdate(m) {
  var rec = toolEls[m.id || m.name];
  if (!rec || m.input == null) return;
  rec.input = m.input;
  // A web call of Luna's is only known to have read a page rather than
  // searched once it is done, and its line takes the name it turned out to
  // have (PROTOCOL.md, tool_update). Claude's calls never change theirs.
  if (m.name && m.name !== rec.name) {
    rec.name = m.name;
    if (rec.nameEl) rec.nameEl.textContent = m.name;
  }
  drawTool(rec);
}

/** @param {import('./protocol').FromServer<'tool_end'>} m */
function onToolEnd(m) {
  if (S.tools > 0) S.tools--;
  var rec = toolEls[m.id || m.name];
  if (!rec) return;
  rec.chip.classList.remove('running');
  rec.chip.classList.add(m.ok === false ? 'bad' : 'ok');
  rec.done = true;
  rec.ok = m.ok !== false;
  rec.summary = m.summary || '';
  rec.results = Array.isArray(m.results) ? m.results : [];
  rec.output = m.output == null ? null : String(m.output);
  drawTool(rec);
  scrollDown();
}

export { actBtn, branchFocus, onTaskRefs, hideTyping, drawTranscriptInto, addPart, addTurnFromElsewhere, onRecallMessage, askaiSaid, atBottom, cardInAnswer,
  cardInLiveAnswer, closeAssistant,
  closeEmptyAssistant, copyFrom, drawWords, dropEmpty, editTurn, endTurnOnScreen,
  drawWaiting, ensureAssistant, fitActs, markStopped, newTurn, noteTurnSign, onDelta, onDone, onExchange,
  onSteerTaken, onTrace,
  onPermissionAsk, onPermissionDone, onRetract, onRetryStart, onStt, onToolEnd, onToolStart,
  onToolUpdate, onTranscriptScroll, onTurnEnd, onVersionPicked, openTheStream,
  keepEnd, olderBack, olderFrom, olderLearn, olderMoved, pickUpRunningTurn, readerHand, restoreTranscript, scrollDown, setBusy, showStop,
  stillSpeaking, stopTheTurn, T, transcriptEl, turnIsRunning, updateJump, watchTheTurn, wipeTranscript };
