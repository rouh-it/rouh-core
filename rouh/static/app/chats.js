/* Rouh's page, the chats: the list in the middle column, the projects, which one you are talking in (section 10c of what was one app.js).
 *
 * Imports app/runs.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { askDelete, CANVAS, canvasChatsFollow, canvasOn, canvasTask, CLOCK, goalsViewing, goNow,
  openTaskThread, openUnder, ownerWords, projectById, projectParts, renderThreads, tasksFrame,
  tasksViewing, taskUrl, taskWords, threadName } from 'app/runs.js';
import { shared } from 'app/shared.js';
import { $, el, linkFresh, linkTo, now } from 'app/helpers.js';
import { tabChatKeep } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { handleMessage, heldMoved, holdMessages, S, send } from 'app/socket.js';
import { stopPlayback } from 'app/playback.js';
import { setState } from 'app/orb.js';
import { drawTranscriptInto, drawWords, editTurn, hideTyping, endTurnOnScreen, pickUpRunningTurn, restoreTranscript, setBusy,
  olderBack, olderFrom, olderLearn, olderMoved, showStop, T, transcriptEl, turnIsRunning, updateJump, wipeTranscript } from 'app/transcript.js';
import { CARDS, cardsAdriftSay, cardWaysSay, frameLoad, projectSaidIt, resetCanvas,
  resetStreamCards, taskSaidIt, WORKSPACE_ROUTE } from 'app/cards.js';
import { detachAsk, FIND, findAsk, findShow } from 'app/search.js';
import { ADDR, addrIsTasksOwn, addrOf, addrTouch, FRESH, freshChatOpened } from 'app/address.js';
import { welcomeShow } from 'app/welcome.js';
import { CANVAS_MIN, CHAT_W, chatIsWanted, chatRoom, panelsForChat, panelsHold, drawTyped, growInput, input, narrow,
  sendTyped, setPane, sidebarDone } from 'app/controls.js';
import { attUploading, drawAttachments } from 'app/attachments.js';

/* ---------------------------------------------------------------- 10c */

/* The chats.
 *
 * What the person says used to be one endless conversation, which is one
 * context window that only ever grew. It is now several: each chat has its
 * own history, its own canvas and its own title, and exactly one of them is
 * active - the voice answers into it, the transcript column shows it, and
 * the canvas shows what was drawn in it.
 *
 * Which chat that is belongs to this tab, and so does the strip of forks
 * around it (fr_349273a9377e, and task 62 step 62-23): the server holds both
 * for each tab, and a chat or a strip opened on the phone moves nothing on
 * the desk. The list of chats is still one, and every tab is told when it
 * changes.
 *
 * They are opened from the sidebar's list of chats, and New chat at the top
 * makes an empty one and puts you in it. The list of every chat and task
 * that hung off the chat's three dots as "All chats and tasks" was taken
 * off on 30 September 2026, at Petar's asking: the sidebar and the task
 * browser already reach every one of them.
 */

var CHATS = { list: [], folders: [], active: null,
              // Which of them is the thread that is always there.
              general: 'conversation',
              // The threads being answered this instant. A turn belongs to
              // the thread it was asked in and goes on there after the
              // person has walked off to another one, so the rail says which
              // ones are still talking.
              answering: [],
              // The conversation the person is in when it is not written
              // down yet: a task opened and not talked about, or New chat
              // with nothing said (`draft` in PROTOCOL.md). It is in none of
              // the lists, because it is not a chat until something is said
              // in it; it is kept here so the head of the conversation can
              // still say whose it is.
              draft: null,
              // The chat this tab is in, as the handshake said it, for its head
              // until the list arrives a moment after (`ready`).
              own: null,
              // The whole list has come, since the page opened.
              listed: false };

/* The forks laid out around the conversation (`rouh/forks.py`, and "forks"
   in PROTOCOL.md). Beside CHATS because a fork is a chat that is in none of
   its lists: its own row is kept here, and `chatById` reads it from here. */
var FORKS = {
  // The chats laid out left to right with the one on screen among them,
  // each with the last few things said in it. Empty with no fork in sight.
  strip: [],
  // Every fork the chat on screen has had, and the message each came off.
  marks: [],
  // Whether the chat on screen may be forked before anything is said in it:
  // a Synapse chat, whose fork keeps the dataset it was made over.
  bare: false,
  // A fork's own row, by id.
  rows: {},
  // Each chat beside the one on screen as the server would read it back on
  // sliding onto it (`chat_peek`), and the ones asked for, by id and count.
  peeks: {},
  peeking: {},
  // The switch on its way in is along the strip: -1 when the chat opening
  // was to the left of the one being left, 1 to its right, 0 when it is a
  // different conversation altogether. The canvas stays for the first two.
  within: 0,
  // What was sent as a fork, drawn in it once it is open.
  typed: null,
  // Each chat of the strip the person has slid away from, kept as it was,
  // with what has arrived for it since (`forkPark`), and what was held for
  // the one that has just been slid back, until it is handed over.
  parked: {},
  resumed: null,
  // The room kept for the slivers, and the conversation's width they were
  // measured against when nobody had dragged its edge (`forkTrack`).
  reserve: 0,
  pinned: 0,
  // The strip as it was last drawn, so a `chats` that changes nothing about
  // it draws nothing (`forksTake`), and one that arrives while a finger is
  // on it waits until the finger is lifted.
  drawn: '',
  later: false,
  // The switch on its way in is to the chat already on the screen, with
  // only its strip changed: nothing of the conversation is drawn again.
  same: false,
  // The number of this page's newest message that moves it to a chat or
  // changes its strip (`MOVES` in app/socket.js). A message about which chat
  // this tab is in and its strip says the number it was worked out after
  // (`asked`); an older one is behind what the page did, and its say on
  // either is not taken (`FORKS.behind`).
  asked: 0
};

/* Whether a message from the server about this tab's chat and its strip was
   worked out before the page's newest move, and so is behind the screen.
   Petar, 23 October 2026: "If I close a fork it disappears, but somehow
   reappears again afterwards for a moment". The page closes a fork, or moves
   along the strip, at once (`stripGo`), and the server's lists of the chats,
   built on a thread, could still arrive afterwards carrying the strip from
   before; until now one did, and laid the fork out again. A message with no
   number (a server from before this) is taken as it always was. */
/** @param {{asked?: number}} m */
function forkBehind(m) {
  return typeof m.asked === 'number' && m.asked < FORKS.asked;
}

/* Where this tab's strip of forks ends: the deepest fork laid out to the
   right, or '' when nothing is laid out beside the chat. The strip is this
   tab's own and nobody else's (`forks.strip`): the address says it
   (`addrNow`), and the page asks for it again whenever it connects (`hello`),
   so a reload, Back and a dropped socket all lay out the same strip. */
function forkTip() {
  var n = FORKS.strip.length;
  return n > 1 ? FORKS.strip[n - 1].id : '';
}

function chatById(id) {
  for (var i = 0; i < CHATS.list.length; i++) {
    if (CHATS.list[i].id === id) return CHATS.list[i];
  }
  if (CHATS.draft && CHATS.draft.id === id) return CHATS.draft;
  // A fork is in no list (`rouh/forks.py`), so its row is where the strip
  // put it.
  if (id && FORKS.rows[id]) return FORKS.rows[id];
  if (id && CHATS.own && CHATS.own.id === id) return CHATS.own;
  return null;
}

/* Whether the thread on screen is a piece of numbered work.
 *
 * One question with one answer, because two things ask it: the chat menu,
 * which offers to make a loose chat a task, and a card, which offers to
 * write itself into the task this one already is. */
function chatIsTask() {
  var chat = CHATS ? chatById(CHATS.active) : null;
  return !!(chat && chat.task);
}

/* The head of the conversation: where you are, in one chip.
 *
 * A folder glyph and the project this chat is in, or the task that owns it,
 * and for a chat that belongs to neither, nothing at all. The chat's own
 * name is **not** up here: it is at the head of the stream, above the first
 * message, and `showStreamTitle` below puts it there. The top of a phone's
 * screen is the scarcest row on the page, and the name of the conversation
 * you are reading is the one thing on it you already know.
 *
 * Pressing the project narrows the sidebar's list to it, which is the same
 * thing pressing it in the sidebar does: the chip is a way back up.
 */
function showCrumb() {
  if (!CHATS) return;
  var chat = chatById(CHATS.active);
  // `threadName` and not `chat.title`, which is the same name the rail puts
  // on the same chat two columns to the left. The thread that is always
  // there is called General because of which thread it is; its own title is
  // whatever the model last wrote from what was said in it, and until 22
  // September 2026 this chip read "New chat" while the rail beside it read
  // "General" and both meant the same conversation.
  var name = chat ? threadName(chat) : '';
  showStreamTitle(name);
  // And on a phone at the top of the screen, in the line with what it
  // belongs to (`crumbLineRest`). Not for the main chat, whose chip is
  // already its name.
  showCrumbTitle(chat && chat.id === CHATS.general && !chat.fork_of
    && !(chat.owned_by && chat.owned_by.type === 'task') && !chat.folder_id ? '' : name);
  // Which chat this is decides whether an empty one says hello: a task's
  // does not (`welcomeWanted`).
  welcomeShow();
  // A fork's glyph says what it is a fork of, and goes back there
  // (`rouh/forks.py`).
  // Closing it is not up here: it is the cross in the fork's own corner
  // (`forkX`), because a cross in the head of the screen did not say which
  // of the chats side by side it would close. Nothing on the dots is for a
  // fork either: it is filed nowhere, pinned nowhere and numbered never, so
  // they go.
  var forkOf = chat && chat.fork_of ? chat.fork_of : '';
  var forkChip = $('crumbFork');
  if (forkChip) {
    forkChip.hidden = !forkOf;
    linkFresh(forkChip);
    if (forkOf) {
      var from = forkName(forkOf);
      $('crumbForkName').textContent = from;
      forkChip.setAttribute('aria-label', 'Forked from ' + from + '. Go back to it');
    }
  }
  var menu = $('chatMenuBtn');
  if (menu) {
    // No conversation, no controls. A page at the front door has nothing to
    // do this to, and dots on their own are a control for nothing. Nor
    // does a draft: there is no chat yet to rename, keep, move or delete,
    // and the first thing said in it is what makes one.
    // Nor the main chat, Rouh, which is the system's own chat and has no
    // options at all for now (Petar, 4 November 2026, fr_ad19bb8be13e:
    // "main rouh has no options it is the main system chat"). A fork has
    // the dots like any other chat, with Unlink on them.
    menu.hidden = !chat || !!chat.draft || (chat.id === CHATS.general && !forkOf);
    menu.title = name ? 'What you can do with “' + name + '”'
      : 'What you can do with this chat';
  }
  // What this chat belongs to, which is a project or a task or nothing.
  // Read off the one link table (`owned_by`) rather than off the folder: a
  // chat attached to a task is that task's, and being a task's is what takes
  // it out of a project.
  var owned = chat ? chat.owned_by : null;
  var ofTask = !!(owned && owned.type === 'task');
  // A subtask's chat is the subtask's own, and says which task it is part
  // of, with the way up to it and Send to the task beside it
  // (`rouh/subtasknotes.py`).
  showParent(ofTask && !forkOf ? owned.parent || null : null, chat);

  // And the empty conversation says whose it is: a task's, opened and not
  // talked about yet, is the task's chat before its first word.
  var empty = $('transcriptEmpty');
  if (empty) {
    empty.textContent = (ofTask && chat.draft
      ? 'The chat about ' + taskWords(owned) + ' starts here. '
        + (owned.parent ? 'Rouh has ' + taskWords(owned.parent)
          + ' as background, and what is said here stays with the subtask. ' : '')
      : '')
      + 'Say something, or type below.';
  }

  /* And what can be done to it, which depends on which of the two it is.
   *
   * A loose chat can be made a task - a new numbered one, which is a
   * different thing from being put under a task that already exists - and it
   * can be kept. A chat a task owns is already numbered and is kept by being
   * owned, so neither item is there: an item that would do nothing is worse
   * than no item. General is loose and is never numbered, and it is kept
   * already, as a matter of record rather than the person's own mark: it
   * stays at the head of the chats whatever its pin says,
   * so Pin and Un-pin on it would both do nothing anybody could see, and
   * neither is offered. */
  var promote = $('promoteChatBtn'), pin = $('pinChatBtn'), unlink = $('unlinkChatBtn');
  // Unlink is a fork's alone: it is the one thing hanging off another chat.
  if (unlink) {
    unlink.hidden = !forkOf;
    unlink.title = 'Detach from the chat it came off, into a task you pick. It becomes a'
      + ' chat of that task, with every message it has.';
  }
  var loose = !!chat && !chat.task;
  if (promote) {
    promote.hidden = !loose || !chat || chat.id === CHATS.general;
    promote.title = 'Give this chat the next task number and a folder in the'
      + ' workspace. Everything said in it is kept, and so is everything it'
      + ' drew.';
  }
  if (pin) {
    // Not on a fork either, which is pinned nowhere until it is unlinked.
    pin.hidden = !loose || !chat || chat.id === CHATS.general || !!forkOf;
    // The same word the three dots on every row of every list use, because
    // it is the same mark on the same chat: "keep" and "pin" for one thing
    // was two words for whoever had to find it twice.
    RouhMenu.label(pin, chat && chat.pinned ? 'Un-pin' : 'Pin');
    RouhMenu.icon(pin, chat && chat.pinned ? 'unpin' : 'pin');
    pin.title = chat && chat.pinned
      ? 'Take the mark off. The chat stays either way: nothing is ever'
        + ' deleted on a clock.'
      : 'Keep this one at the top of the chats. Nothing is deleted'
        + ' automatically either way.';
  }
  // Every chat but General, which is the one that is always there and is
  // never deleted: the server would refuse it, and an item that can only be
  // refused is not an item.
  var del = $('deleteChatBtn'), delRule = $('deleteChatRule');
  if (del) {
    del.hidden = !chat || chat.id === CHATS.general;
    if (delRule) delRule.hidden = del.hidden;
    del.title = 'Delete this chat, with everything it holds. You are asked'
      + ' first, with what else would go.';
  }

  var project = chat && chat.folder_id ? projectById(chat.folder_id) : null;
  var crumb = $('crumbProject');
  if (!crumb) return;
  // The main chat, Rouh, belongs to nothing and is never a fork, and until
  // 30 September 2026 that left the top of it empty, so nothing said which
  // chat you were in. Petar (fr_86b11501514b): "Please make it display
  // '🪸Rouh' on the top in the same style as other floating bubbles/titles
  // so I know I am in that chat." So it has the same chip a task's chat has,
  // with the coral and its name in place of the task's mark.
  var main = !!chat && chat.id === CHATS.general && !forkOf && !ofTask && !project;
  var show = !!(project || ofTask || main);
  crumb.hidden = !show;
  linkFresh(crumb);
  // A task is drawn with a task's mark rather than the folder, which is a
  // project's: "a folder icon, which means this is a chat part of a
  // project" (Petar, 23 September 2026), and this is a task.
  crumb.classList.toggle('is-task', ofTask);
  crumb.classList.toggle('is-main', main);
  if (!show) return;
  if (main) {
    $('crumbProjectEmoji').textContent = '🪸';
    $('crumbProjectName').textContent = name;
    crumb.title = 'This is ' + name + ', the main chat. Press to see the latest chats.';
    crumb.setAttribute('aria-label', name + ', the main chat. Show the latest chats');
    return;
  }
  if (ofTask) {
    $('crumbProjectEmoji').textContent = '';
    var chipName = $('crumbProjectName');
    if (owned.parent && owned.step) {
      // "Subtask 67-03 · Set up …", where a phone keeps "67-03 · Set up …":
      // the arrow in front of it already says it is a level down.
      chipName.textContent = '';
      chipName.appendChild(el('span', 'crumb-sub-word', 'Subtask '));
      chipName.appendChild(document.createTextNode(owned.step + ' · '
        + (owned.label || owned.id)));
    } else {
      chipName.textContent = taskWords(owned, true);
    }
    crumb.title = 'This is the chat about ' + taskWords(owned)
      + '. Press to open the task.';
    crumb.setAttribute('aria-label', 'Open ' + taskWords(owned)
      + ', the task this chat is about');
    return;
  }
  var parts = projectParts(project);
  $('crumbProjectEmoji').textContent = parts.emoji;
  $('crumbProjectName').textContent = parts.name;
  crumb.title = project.folder ? 'Open ' + project.name + ', the project this chat is in'
    : 'This chat is in ' + parts.name + '. Press to see the latest chats.';
  crumb.setAttribute('aria-label', crumb.title);
}

/* The way up from a subtask's chat, and the way to send something up.

   Petar, 29 September 2026 (fr_3113364c29fa), asking for his own
   recommendation to be built: "make the new chat belong to the subtask,
   but give it the parent task's relevant context as background. Keep the
   conversation local by default, and provide a clear link or action to
   bring important decisions back to the parent." So a subtask's chat names
   the subtask on its chip, and in front of it the task it is part of,
   which opens that task's page; and Send to the task, beside New chat and
   in the dots, sends a decision up to it (`note_to_parent`), where it is
   listed on the task's page under From its subtasks. */
var PARENT = { up: null, chat: '' };

function showParent(up, chat) {
  PARENT.up = up;
  PARENT.chat = up && chat ? chat.id : '';
  var chip = $('crumbParent'), send = $('crumbToParent'), item = $('toParentBtn');
  if ($('crumbParentSep')) $('crumbParentSep').hidden = !up;
  if (chip) {
    chip.hidden = !up;
    linkFresh(chip);
    if (up) {
      // The number and the name apart, so a phone can keep the number
      // alone: "↑ 67" in front of the subtask's own chip.
      var named = $('crumbParentName');
      named.textContent = '';
      var num = up.number != null ? String(up.number) : (up.step || '');
      if (num) named.appendChild(el('span', 'crumb-parent-num', num));
      named.appendChild(el('span', 'crumb-parent-words',
        (num ? ' · ' : '') + (up.label || up.id)));
      chip.title = 'This subtask is part of ' + taskWords(up) + '. Press to open it.';
      chip.setAttribute('aria-label', 'Up to ' + taskWords(up)
        + ', the task this subtask is part of');
    }
  }
  // Nothing to send up from a chat nobody has said anything in yet.
  var can = !!up && !!chat && !chat.draft;
  var words = up ? 'Send to ' + taskWords(up) : 'Send to the task';
  if (send) {
    send.hidden = !can;
    send.title = words + ': a decision or a note from this chat, listed on the'
      + ' task’s page and known to Rouh in its chats';
    send.setAttribute('aria-label', words);
  }
  if (item) {
    item.hidden = !can;
    RouhMenu.label(item, up && up.number != null ? 'Send to task ' + up.number
      : 'Send to the task');
  }
}

function parentOpen() {
  var up = PARENT.up;
  if (!up) return;
  var rel = up.folder || '';
  if (!rel) { openUnder('task', up.id, ownerWords(up)); return; }
  var there = tasksViewing() && !CANVAS.step
    && String(CANVAS.at || '').split('?')[0] === taskUrl(rel);
  if (!there) canvasTask(rel);
  chatIsWanted();
  if (narrow()) setPane('canvas');
  sidebarDone();
}

// What the last answer in this chat said, as plain words: what the box
// starts with, because what is worth sending up is most often what Rouh
// has just said was decided. The person changes it before it goes.
function lastAnswerWords() {
  var all = transcriptEl().querySelectorAll('.turn.assistant');
  var last = all.length ? all[all.length - 1] : null;
  if (!last) return '';
  var body = last.querySelector('.turn-body') || last;
  return String(body.innerText || body.textContent || '').trim().slice(0, 4000);
}

function parentNoteOpen() {
  var up = PARENT.up, dlg = $('parentNoteDialog');
  if (!up || !dlg || !PARENT.chat) return;
  $('parentNoteHead').textContent = 'Send to ' + taskWords(up);
  $('parentNoteError').hidden = true;
  var box = $('parentNoteText');
  box.value = lastAnswerWords();
  $('parentNoteGo').disabled = false;
  dlg.showModal();
  box.focus();
  box.select();
}

function parentNoteSend() {
  var text = $('parentNoteText').value.trim();
  var err = $('parentNoteError');
  if (!text) {
    err.textContent = 'Write the decision or note to send first.';
    err.hidden = false;
    return;
  }
  if (!send({ type: 'note_to_parent', chat: PARENT.chat, text: text })) {
    err.textContent = 'Rouh is not connected, so it was not sent.';
    err.hidden = false;
    return;
  }
  $('parentNoteGo').disabled = true;
}

// The answer to `note_to_parent`.
/** @param {import('./protocol').FromServer<'note_sent'>} m */
function onNoteSent(m) {
  var dlg = $('parentNoteDialog');
  if (!m.ok) {
    if (dlg && dlg.open) {
      $('parentNoteError').textContent = m.why || 'That could not be sent.';
      $('parentNoteError').hidden = false;
      $('parentNoteGo').disabled = false;
    } else {
      notify(m.why || 'That could not be sent.', { tone: 'error' });
    }
    return;
  }
  if (dlg && dlg.open) dlg.close();
  var up = m.parent || PARENT.up;
  notify('Sent to ' + (up ? taskWords(up) : 'the task')
    + '. It is on the task’s page, under From its subtasks.', { tone: 'success', action: up && up.folder ? {
      label: 'Open the task',
      run: function () { PARENT.up = up; parentOpen(); }
    } : null });
  // The task's page, if it is the one on the canvas, lists it now.
  if (up && up.folder && tasksViewing()
      && String(CANVAS.at || '').split('?')[0] === taskUrl(up.folder)) {
    var frame = tasksFrame();
    if (frame) frameLoad(frame, CANVAS.at);
  }
}

/* The chat's name, at the head of its own stream.
 *
 * Above the first message and inside the scroller, so it is there when the
 * reader is at the beginning of the conversation and gone the moment they
 * are anywhere else. That is the whole of what it is for: the top of the
 * screen no longer says which chat this is, and a name that scrolls with
 * the words costs no row of a phone to say it.
 *
 * It is written on every `showCrumb`, which is every time the chats change,
 * so a chat the model has just named stops being "New chat" here at the
 * same moment it stops being one in the rail.
 */
function showStreamTitle(name) {
  var box = $('streamTitle');
  if (!box) return;
  box.textContent = name || '';
  box.hidden = !name;
}

/* The chat's title at the top of a phone's screen, and the line it is in.

   The line is what the chat belongs to - the chat it was forked from, the
   task it is part of, its project - as bubbles, and the chat's own title
   after them. Petar, 5 October 2026 (fr_511d4b99d903): "Very chat should
   display its title on top, and its parent should be to the left and if it
   is too long to fit it is draggable. But the beginning of the title is the
   beginning of the chat. Parent title bubble just shows on the left side
   that exists to hint you that it exists and if you want to see it, you can
   drag that line to the right."

   So it rests with the title a little in from the left edge and the end of
   the bubble before it showing in that little, and a finger drags the line
   either way. A line short enough to fit is given room after the title so
   it can rest the same way: the title is always where the eye starts. It
   rests again only when what is in it changes or it changes size, never
   under a finger that has just moved it because a list came in. */
var LINE = { key: '', frame: 0 };
var LINE_SLIVER = 6;

function showCrumbTitle(name) {
  var title = $('crumbTitle');
  if (!title) return;
  title.textContent = name || '';
  title.hidden = !name;
  // After the rest of the head is written, whose chips are in the line too.
  if (!LINE.frame) LINE.frame = requestAnimationFrame(function () {
    LINE.frame = 0;
    crumbLineRest(false);
  });
}

function crumbLineRest(again) {
  var line = $('crumbLine'), title = $('crumbTitle'), end = $('crumbEnd');
  // A desk's line is nothing of its own and has no width to scroll.
  if (!line || !title || !end || !line.clientWidth) return;
  var chips = line.querySelectorAll('.crumb-project:not([hidden])');
  var key = CHATS.active + '\n' + title.textContent + '\n' + line.clientWidth;
  for (var i = 0; i < chips.length; i++) key += '\n' + chips[i].textContent;
  if (!again && key === LINE.key) return;
  LINE.key = key;
  end.style.width = '0px';
  if (title.hidden) { line.scrollLeft = 0; return; }
  var pad = parseFloat(getComputedStyle(line).paddingLeft) || 0;
  // A fork's title begins with the fork glyph in front of it.
  var fork = $('crumbFork');
  var head = fork && !fork.hidden ? fork : title;
  var at = head.getBoundingClientRect().left - line.getBoundingClientRect().left + line.scrollLeft;
  var want = Math.round(at - pad - (chips.length ? LINE_SLIVER : 0));
  if (want <= 0) { line.scrollLeft = 0; return; }
  var short = want + line.clientWidth - line.scrollWidth;
  if (short > 0) end.style.width = (end.offsetWidth + short) + 'px';
  line.scrollLeft = want;
}

// The line coming onto the screen - back from the canvas, a window turned
// on its side - or its title finishing in its real font is a line of a new
// size, and rests again.
if ($('crumbLine') && window.ResizeObserver) {
  new ResizeObserver(function () { crumbLineRest(false); }).observe($('crumbLine'));
  if ($('crumbTitle')) new ResizeObserver(function () { crumbLineRest(true); }).observe($('crumbTitle'));
}

/* A draft that has just become a chat, because something was said in it.
 *
 * The task's own page on the canvas was drawn while there was nothing in the
 * task, and says so - "Nothing in it yet" - beside the conversation that is
 * now in it. So it is drawn again, in the frame it is in, and counts the
 * chat. In place and nothing more: which columns are showing is not this
 * page's business, and a conversation that folded itself away the moment
 * its first answer arrived would be the worse surprise. */
function draftMade(was) {
  if (!was || !was.task || CHATS.draft || !chatById(was.id) || !tasksViewing()) return;
  if ((CANVAS.at || '').indexOf(WORKSPACE_ROUTE + '_task/' + was.task + '/') !== 0) return;
  var frame = tasksFrame();
  if (frame) frameLoad(frame, CANVAS.at);
}

// Everything the server said about the chats, from `ready` or from `chats`.
/** @param {Partial<import('./protocol').ServerMessages['chats']>} m a chats, a ready, or the active chat and forks a switch brings */
function applyChats(m) {
  if (!m) return;
  var was = CHATS.draft;
  if (Array.isArray(m.chats)) { CHATS.list = m.chats; CHATS.listed = true; }
  if ('draft' in m) CHATS.draft = m.draft || null;
  draftMade(was);
  if (Array.isArray(m.folders)) CHATS.folders = m.folders;
  if (Array.isArray(m.answering)) CHATS.answering = m.answering;
  // Which chat the person is in - unless this page is at the front door,
  // which is in none. The list is still drawn from this message; which of
  // its rows is open is the one thing not taken from it (see 10g).
  if (m.active_chat && !ADDR.front) CHATS.active = m.active_chat;
  if (m.general) {
    CHATS.general = m.general;
    // Rouh's row in the sidebar is a link to it (`linkTo`), from now on.
    if ($('generalRow')) linkFresh($('generalRow'));
  }
  // The forks laid out around the chat that is active, and the ones marked
  // in it. Before the head is drawn, which names a fork's parent from them.
  if (m.forks) forksTake(m.forks);
  showCrumb();
  ownerFollow();
  // The projects on the runs page and General's dot are drawn from these same
  // chats, so they are drawn from the same message.
  renderThreads();
  // And the latest chats in Search, when it is open with nothing typed.
  if (FIND && FIND.open && !FIND.q) findAsk(true);
  // And the task's page on the canvas, when it lists one of them.
  canvasChatsFollow();
  // Which chat is the active one arrives here as well as in `chat_switched`
  // - it is part of `ready`, which is how a page that has just opened learns
  // what it is showing - and the address falls back to that chat whenever
  // the canvas is showing nothing of its own (see 10f). So this is where a
  // page that opened at the front door settles on an address.
  addrTouch();
}

/* The canvas follows the chat on screen into the task it has just become.

   A chat that becomes a task without being switched to - asked for in it,
   or in a fork that is then cut from its parent (`forks.cut`) - stayed
   beside whatever page was on the canvas: task 88's chat, made from a fork
   of task 87's, beside task 87's page. Petar, 4 October 2026
   (fr_3702d01d197d): a task's chat is never beside another task's
   content. So when the chat on screen is the same chat and its task is not
   the one it had, the canvas goes to that task's page, behind the
   conversation rather than in front of it. A switch to another chat is
   `onChatSwitched`'s to place, and is only remembered here. */
var OWNED = { chat: '', task: '' };
function ownerFollow() {
  var chat = CHATS.active ? chatById(CHATS.active) : null;
  var task = chat && !chat.draft ? (chat.task || '') : '';
  var was = OWNED;
  OWNED = { chat: CHATS.active || '', task: task };
  if (!task || !was.chat || was.chat !== OWNED.chat || was.task === task) return;
  if (ADDR.front || canvasOn(task)) return;
  shared.THREAD_ASKED = task;
  CANVAS.redraw = true;
  try { canvasTask(task); } finally { CANVAS.redraw = false; }
  // Loading a page folds the conversation away, and this one was being
  // talked in a moment ago.
  chatIsWanted();
}

// Opening a chat. It is asked of the server and nothing
// is changed here: the server decides which chat is active and tells every
// tab, this one included, so there is one answer rather than a guess here
// and a correction a moment later.
/** @param {string} id @param {string} [strip] the end of the strip to lay out with it, when an address names one */
function openChat(id, strip) {
  if (!id) return;
  // With no connection there is no server to ask: a chat this device keeps opens from its copy,
  // forks and all, on the Offline page (app/offlineview.js).
  var off = window.RouhOffline;
  if (off && !off.online() && off.hasChat(id)) { off.open('chats', id); return; }
  chatIsWanted();
  /** @type {import('./protocol').ToServer<'open_chat'>} */
  var ask = { type: 'open_chat', id: id };
  if (typeof strip === 'string') ask.strip = strip;
  send(ask);
}

/* A chat opened by its own address - a chat's row pressed on a task's or a
   project's page, a search result, a pasted link - is a chat the person
   wants to look at. At a desk it is the column beside the canvas, and
   `chatIsWanted` unfolds it; on a phone it is the other pane, so the pane
   goes to it, and `onChatSwitched` keeps it there rather than sliding the
   phone back to the task's page, which it otherwise does for a task's own
   chat so that a task opened shows its page. Petar, 4 October 2026 (fr_c497aa8de75f): "On
   the task I click the chat. It seems the chat loads but the screen
   doesn't change to the chat." */
var CHAT_SHOW = '';
/** @param {string} id @param {string} [strip] */
function chatShow(id, strip) {
  if (!id) return;
  if (narrow()) { CHAT_SHOW = id; setPane('chat'); }
  openChat(id, strip);
}

// This tab's chat changed. What was on the screen belonged to the
// chat it was in a moment ago, so the transcript is emptied and this
// one's is drawn, and the canvas reads this one's cards back from the start.
/** @param {import('./protocol').FromServer<'chat_switched'>} m */
function onChatSwitched(m) {
  var chat = m.chat || {};
  // Whether this is the chat the front door asked for, read before anything
  // below moves the page off it (see 10g).
  var fresh = FRESH.asked;
  // The second half of opening a task's page, when the bar already said the
  // first half: this writes over that entry rather than adding one (`ADDR`).
  if (ADDR.thread && chat.task === ADDR.thread && ADDR.half && ADDR.half === ADDR.at) {
    ADDR.replace = true;
  }
  ADDR.thread = '';
  ADDR.half = '';
  // The panels this chat was left with, or starts with - unless this is a
  // move along a strip of forks, where the canvas is the strip's.
  if (chat.id && !FORKS.within && !FORKS.same) panelsForChat(chat);
  panelsHold(true);
  if (chat.id) {
    CHATS.active = chat.id;
    tabChatKeep(chat.id);
    // Which task's thread is open now, however it was opened - here, on the
    // phone, or out loud - so the canvas never asks for one that is already
    // open and never fails to ask for one that is not (`pickThread`).
    shared.THREAD_ASKED = chat.task || '';
    // A chat made a moment ago is not in the list yet: the list follows in
    // its own message. Putting it in here is what stops the name beside
    // "Transcript" going blank for the instant in between.
    //
    // Unless it is a draft: a task opened, or New chat pressed, with nothing
    // said yet. That is not a chat and goes in no list; it is kept beside
    // them until the first thing said in it makes it one, under this same
    // id, and the list that arrives then has it in.
    //
    // Nor is a fork: it is in no list at all, and its row is kept beside
    // them for the same reason a draft's is (`FORKS.rows`).
    var known = chatById(chat.id);
    if (chat.draft) CHATS.draft = chat;
    else if (chat.fork_of) FORKS.rows[chat.id] = chat;
    else if (known) { known.title = chat.title || known.title; known.folder_id = chat.folder_id || null; }
    else CHATS.list.unshift(chat);
    // Attachments are uploaded to /attachments/{chat} before the message
    // carrying them is sent, so this has to follow the chat and not the tab.
    S.sessionId = chat.id;
    var idBox = $('sessId');
    if (idBox) { idBox.textContent = chat.id; idBox.title = chat.id; }
  }
  // The sound of the thread being left goes with it. It is that thread's
  // answer being spoken, the person has just opened another one, and a voice
  // that carried on would be talking over what they moved to look at. It
  // also settles the screen: an `audio_end` for a thread this page is no
  // longer showing is one it will never draw, and the Stop control waits on
  // that message (`stillSpeaking`).
  stopPlayback();
  // A chat of the strip that was kept as it was is back on the screen
  // already, cards and all (`forkResume`): nothing is read again. Nor is the
  // chat already on the screen, sent again with only its strip changed
  // (Back onto a strip, Rouh in the navigation): wiping it and drawing it
  // again is what threw the reader back to its end.
  var same = FORKS.same;
  FORKS.same = false;
  var resumed = !!FORKS.resumed || same;
  if (!resumed) {
    wipeTranscript();
    restoreTranscript(m.transcript);
    // And where what came before it begins, for reading it back as the reader scrolls up.
    if (m.local) olderMoved(chat.id || '');
    else olderFrom(chat.id || '', m.older || '');
  } else if (!same) olderBack(chat.id || '');
  // The server's answer to a move the page made itself says it for a chat
  // the page had no mark for.
  else olderLearn(chat.id || '', m.older || '');
  showCrumb();
  // Along a strip of forks the canvas is the strip's, not the chat's: what
  // was on it stays, and only this chat's own cards are read back into its
  // conversation. "It opens up and slides to show itself, and the canvas
  // does not move" (`rouh/forks.py`).
  var within = FORKS.within;
  FORKS.within = 0;
  if (resumed) { cardWaysSay(); cardsAdriftSay(); }
  else if (within) { resetStreamCards(); cardsAdriftSay(); }
  else resetCanvas();
  // Whatever was being written belonged to the thread that was on screen a
  // moment ago and is still being written there; this thread has a turn of
  // its own or it has none. Coming back to one that is still being answered
  // shows it being answered, from the words it has so far.
  //
  // Unless this is the fresh chat the front door asked for: it is empty, and
  // there was nothing on the screen to stand down. Settling anyway is what
  // would take the orb off listening in the middle of the first sentence
  // said at the front door (see 10g).
  if (fresh) S.turn = 0; else if (!resumed) pickUpRunningTurn(m.running);
  // The server's answer to a move this page made itself (`stripGo`) is the
  // first word on a turn running in that chat that the page had not heard.
  else if (same && m.running && !turnIsRunning()) pickUpRunningTurn(m.running);
  /* The canvas follows the conversation.
   *
   * A chat a numbered task owns **is** that task, so being in it means
   * having its page on the canvas; a loose chat has no page of its own, so
   * whatever is loaded there belongs to something else and goes. The rail
   * has always done this when a thread is picked in it (`openThread`), and
   * doing it here instead of there is what makes it true however the chat
   * was opened: from the list, from a link, from Back, from the phone, or
   * out loud. It is also what lets one address say both which conversation
   * you are in and what is beside it - `/task/<folder>` would otherwise
   * sometimes mean the task's page and sometimes a bare canvas.
   *
   * Nothing is reloaded when the canvas is already on it: `pickThread` is
   * answered by the `THREAD_ASKED` set above, so this cannot ask the server
   * for the thread it has only just been told about.
   */
  var addressed = !!(ADDR.forChat && ADDR.forChat === chat.id);
  ADDR.forChat = '';
  var shown = !!(CHAT_SHOW && CHAT_SHOW === chat.id);
  CHAT_SHOW = '';
  if (within || same) {
    // Moving along the strip of forks, or the chat on screen with its strip
    // changed. Whatever the canvas holds - a card, a task's page, a run - is
    // what the person is asking about, and it stays put.
  } else if (addressed || ADDR.wanted) {
    // An address named this conversation, and named what is beside it too.
    // The canvas is that address's to set, not this switch's.
  } else if (CLOCK.keepFor && CLOCK.keepFor === chat.id && goalsViewing()) {
    // A goal's chat, opened from the Goals page, beside it (`clockToChat`).
    CLOCK.keepFor = '';
    chatIsWanted();
  } else if (chat.task) {
    // A subtask's chat is beside the subtask's page, which is the canvas
    // already when that is where it was started.
    if (!tasksViewing() || !canvasOn(chat.task)) {
      // Put on the canvas behind the conversation, not in front of it, when
      // the conversation is what was pressed (`chatShow`).
      CANVAS.redraw = shown;
      try { canvasTask(chat.task); } finally { CANVAS.redraw = false; }
      // And the conversation with it, in that order: loading a page folds
      // this column away by itself, and somebody whose conversation has
      // just changed is somebody who wants to see it.
      chatIsWanted();
    }
  } else if (shared.LEFT_UP && Date.now() - shared.LEFT_UP < 10000) {
    // Moved here because the chat that was open went with what was just
    // deleted; the canvas is on the level above it (`canvasLeftBehind`).
  } else if (tasksViewing()) {
    goNow();
  }
  shared.LEFT_UP = 0;
  panelsHold(false);
  // The conversation is the thing the address falls back to when the canvas
  // is showing nothing of its own, so a chat opened here - or on the phone,
  // or out loud - is a chat the bar has to say (see 10f).
  addrTouch();
  // And whatever was said at the front door while there was nothing to say
  // it in: this is the conversation it asked for (see 10g).
  if (fresh) freshChatOpened();
  // And whatever was typed into a project's own box, which asked for this
  // conversation the same way and for the same reason (`projectChat`).
  projectSaidIt();
  // And what a task's page asked to have said in it (`taskChat`).
  taskSaidIt();
  // And the question this tab has just sent as a fork, which opened this
  // chat to be asked in (`sendTyped`).
  forkTypedArrived(chat);
  // On a phone the panes are one at a time, and a chat opened from the list
  // is read in the conversation. Going there is what the click was for, and
  // the list has done its job, so it closes behind them: "All chats and
  // tasks", on the chevron beside the chat's name, is what opens it again.
  // On a wide screen every column is already on the page and the list
  // stays.
  //
  // Unless the conversation only moved because a task was loaded in the
  // canvas. Picking a task is picking its thread, so the thread follows -
  // but the person asked for the task, and being thrown onto an empty
  // conversation and made to press the corner glyph to see what they
  // pressed for is not what they asked for. They stay on what they loaded.
  //
  // Start chat on the task's own page is the exception: the person asked
  // for the conversation, not for the page they were already on. So is the
  // chat itself pressed, on that page's Chats list or anywhere else that
  // opens it by its own address (`chatShow`).
  var asked = shown || (!!chat.task && chat.task === shared.TASK_CHAT_ASKED);
  shared.TASK_CHAT_ASKED = '';
  if (!narrow()) return;
  setPane(!asked && tasksViewing() && canvasOn(chat.task) ? 'canvas' : 'chat');
}

/* ---------- forks ----------

   Petar, 24 September 2026 (fr_6fd33e631405): "anytime I'm in a
   conversation and don't understand something, I would like to ask for
   clarification. That might trigger an entirely new conversation, but at
   the same time, I don't want to lose where we are in the main thread."

   `rouh/forks.py` is what a fork is. This is the page's half:

   - **Fork, beside Send**, or Ctrl+Shift+Enter (Cmd on a Mac), sends what
     is typed into a new fork of this chat instead of into it. The fork
     opens to the right, and this chat stays on the left.
   - **The strip.** The chats a fork hangs between are a row in the
     conversation's column, left to right: where it all started, each fork
     of the one before, and the canvas after all of them, where it always
     was. The chat being talked in is the column, and the chats either side
     of it are themselves, cut off by its edges; the row slides sideways
     (the row, below). The canvas does not move.
   - **The marks.** Every fork is marked in the conversation it came off,
     where it came off, with the whole of what was asked in it, and the mark
     opens it again: after it is closed, or when another fork of the same
     chat has taken its place on the strip.
   - **Closing** a fork, from the cross in its own corner, takes it and
     every fork below it off the strip, and puts the person back in the chat
     it came off when they were in it. Nothing is deleted.
   - **Every chat of the strip stays as it is** while another is on screen,
     a turn still running in it included, and nothing is read back when it
     is slid into view again (`forkPark`). */

function forkIcon(size) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.innerHTML = '<path d="M6 20V4"/><path d="M6 15c0-4.5 3.5-7 12-7"/><path d="M15 5l3 3-3 3"/>';
  return svg;
}

/* What a chat on the strip is called: the name it goes by everywhere else
   on the page (`threadName`), from whichever row there is.

   Not the strip's `title` on its own, which is the chat's stored title.
   General's is whatever the model last wrote from what was said in it, so
   until 26 September 2026 (fr_8f780f8b2c92) a fork of General opened about
   a contact's login said at the top of the screen that it was a "Fork of
   🚀 Deploy service restart issue", a chat nowhere on the list, while the
   list and General's own head both said General. */
function forkName(id) {
  var chat = chatById(id);
  for (var i = 0; !chat && i < FORKS.strip.length; i++) {
    if (FORKS.strip[i].id === id) chat = FORKS.strip[i];
  }
  return chat ? threadName(chat) : 'the chat it came from';
}

function forkIds() {
  var out = [];
  for (var i = 0; i < FORKS.strip.length; i++) out.push(FORKS.strip[i].id);
  return out;
}

/* Whether a `chat_switched` is a move along the strip on screen, and from
   which side. Read off the strip the message carries and the one the page
   had, so opening a fork (the new strip has both), going back along one
   (both strips have both) and closing one (only the old strip had the fork)
   are all moves along it, and opening any other chat is not. */
/** @param {import('./protocol').FromServer<'chat_switched'>} m */
function forkWithin(m) {
  var to = m.chat && m.chat.id, from = CHATS.active;
  if (!to || !from || to === from || ADDR.front) return 0;
  var next = [];
  var laid = (m.forks && m.forks.strip) || [];
  for (var i = 0; i < laid.length; i++) next.push(laid[i].id);
  var a = next.indexOf(from), b = next.indexOf(to);
  if (a >= 0 && b >= 0) return b < a ? -1 : 1;
  var prev = forkIds();
  a = prev.indexOf(from); b = prev.indexOf(to);
  if (a >= 0 && b >= 0) return b < a ? -1 : 1;
  return 0;
}

function forksTake(f) {
  FORKS.strip = Array.isArray(f.strip) ? f.strip : [];
  FORKS.marks = Array.isArray(f.marks) ? f.marks : [];
  FORKS.bare = !!f.bare;
  // A fork that is in the lists now was detached (Unlink, `detachAsk`), here or
  // in another tab: the row the strip kept for it is the list's from here
  // on, which does not call it a fork. Where it went is said by the bar the
  // move puts up in the tab that detached it (`detachAnswered`).
  for (var id in FORKS.rows) {
    for (var n = 0; n < CHATS.list.length; n++) {
      if (CHATS.list[n].id === id) { delete FORKS.rows[id]; break; }
    }
  }
  forkKeptFollow();
  forkPeeksFollow();
  for (var i = 0; i < FORKS.strip.length; i++) {
    var c = FORKS.strip[i];
    if (!c.fork_of) continue;
    // The strip's row is fresher about the title and the count; the row the
    // switch carried knows everything else a chat row says.
    var row = FORKS.rows[c.id] || { id: c.id, task: '', folder_id: null, loose: true };
    row.title = c.title; row.titled = c.titled; row.messages = c.messages;
    row.fork_of = c.fork_of;
    FORKS.rows[c.id] = row;
  }
  // Drawn again only when what it draws has changed. A `chats` arrives
  // whenever anything about any chat does - a turn starting or ending
  // anywhere, a title written - and drawing the strip from it each time took
  // the chats beside this one off and put them back, and put the row back in
  // the middle under a finger that was moving it. A strip that is
  // the same is left exactly as it is.
  var drawn = forkDrawnAs();
  if (drawn !== FORKS.drawn) {
    if (STRIP.touching || STRIP.moving) FORKS.later = true;
    else { FORKS.drawn = drawn; forksPaint(); }
  }
  var marked = JSON.stringify(FORKS.marks) + ' ' + forkIds().join(' ');
  if (marked !== MARKS_DRAWN) forkMarksDraw();
  forkBtnPaint();
}

// What the strip as drawn depends on: which chats, which of them is in the
// middle, and what each beside it says of itself.
function forkDrawnAs() {
  var parts = [CHATS.active || '', ADDR.front ? 'front' : '', narrow() ? 'phone' : 'desk'];
  for (var i = 0; i < FORKS.strip.length; i++) {
    var c = FORKS.strip[i];
    parts.push(c.id + ':' + c.messages + ':' + c.title + ':' + (c.fork_of || ''));
  }
  return parts.join('|');
}

// A strip that changed while a finger was on it, drawn once it is lifted.
function forkDrawLater() {
  if (!FORKS.later || STRIP.touching || STRIP.moving) return;
  FORKS.later = false;
  FORKS.drawn = forkDrawnAs();
  forksPaint();
}

// A length off the stylesheet: how much of a chat beside this one shows,
// and the gap between two, which are not the same at a desk and on a phone.
//
// Read once for each width the page is laid out at, never in the middle of a
// move: reading a style straight after the conversation has been moved makes
// the browser work the whole page's styles out there and then, which was
// three quarters of the moment a move along the strip held the page still.
var PX = { at: '', got: /** @type {Record<string, number>} */ ({}) };
function forkPx(name) {
  var at = window.innerWidth + 'x' + window.innerHeight;
  if (PX.at !== at) { PX.at = at; PX.got = {}; }
  if (!(name in PX.got)) {
    var v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
    PX.got[name] = isFinite(v) ? v : 0;
  }
  return PX.got[name];
}

/* The room the strip keeps beside the chat being talked in: one chat's
   edge when there are two on it, one either side when there are more. It is
   kept for the strip and not for where on it the person is, so moving along
   it never moves the canvas; at either end of a longer strip the one chat
   beside it shows twice as much. */
/* A length the strip is laid out by, set only when it changes. Both are
   inherited by everything under the element they are set on - the whole
   page for `--fork-w`, the conversation's column for `--strip-room` - so the
   browser works every style under it out again whenever one is set, even to
   the value it already had. The strip set both on every move and on every
   frame of every slide, which was most of a move's pause (23 October 2026). */
/** @param {HTMLElement} at @param {string} name @param {string} value */
function stripVar(at, name, value) {
  if (at.style.getPropertyValue(name) === value) return;
  at.style.setProperty(name, value);
}

function forkRoomFor(n) {
  if (n < 2) return 0;
  return (n > 2 ? 2 : 1) * (forkPx('--strip-peek') + forkPx('--strip-gap'));
}

function forksPaint() {
  var left = $('forkLeft'), right = $('forkRight'), col = $('chatCol'), row = $('forkRow');
  if (!left || !right || !col || !row) return;
  FORKS.drawn = forkDrawnAs();
  stripSettle();
  left.innerHTML = '';
  right.innerHTML = '';
  var strip = FORKS.strip, at = -1, i;
  for (i = 0; i < strip.length; i++) if (strip[i].id === CHATS.active) at = i;
  var on = strip.length > 1 && at >= 0 && !ADDR.front;
  left.hidden = !on || at === 0;
  right.hidden = !on || at === strip.length - 1;
  col.classList.toggle('stripped', on);
  forkNavPaint(on ? at : -1);
  // The cross in the corner of the chat being talked in, when it is a fork.
  // Unlink is on its three dots since 4 November 2026, not a circle here.
  var self = $('chatSelf'), had = self ? self.querySelectorAll(':scope > .fork-x') : [];
  for (i = 0; i < had.length; i++) had[i].remove();
  if (!on) { forkRoom(0); STRIP.ids = ''; STRIP.active = ''; STRIP.placed = false; return; }
  if (self && strip[at].fork_of) {
    self.appendChild(forkX(strip[at]));
  }
  if (!narrow()) {
    // At a desk the chat it came off and the fork from it are strips either
    // side of it, and the rest of the path is behind the count (`forkStrip`).
    if (at > 0) left.appendChild(forkStrip(strip[at - 1], at - 1, 'left'));
    if (at < strip.length - 1) right.appendChild(forkStrip(strip[at + 1], at + 1, 'right'));
  } else {
    for (i = 0; i < at; i++) left.appendChild(forkPane(strip[i], i));
    for (i = at + 1; i < strip.length; i++) right.appendChild(forkPane(strip[i], i));
  }
  forkRoom(forkRoomFor(strip.length));
  stripPlace();
  for (i = 0; i < strip.length; i++) if (i !== at) forkPeekAsk(strip[i]);
}

/* ---------- each chat beside this one, whole ----------

   Petar, 15 October 2026 (fr_60918f90d0bb): "There is a snap and after the
   snap some refresh happens. Can we not have it?" A chat beside this one
   that had not been on screen since the page loaded was drawn on its card
   from the last few things said in it, in words only, and slid onto it was
   read back from the server in its place: tool lines, the lines under each
   message and its own forks' marks arrived after the snap, all at once. So
   each one is asked for whole the moment it is beside this one
   (`peek_chat`), and its card is drawn from that by the same hand that
   draws it when it is slid onto (`drawTranscriptInto`). */

// Whether what was had of this chat is the chat as the strip has it now.
function forkPeekFresh(chat) {
  var peek = FORKS.peeks[chat.id];
  return !!peek && peek.messages === Number(chat.messages);
}

/** @param {any} chat a chat of the strip */
function forkPeekAsk(chat) {
  if (!chat || !chat.id || forkPeekFresh(chat)) return;
  var kept = FORKS.parked[chat.id];
  if (kept && !kept.stale && !kept.held.length) return;
  var want = chat.id + ' ' + Number(chat.messages);
  if (FORKS.peeking[chat.id] === want) return;
  FORKS.peeking[chat.id] = want;
  send({ type: 'peek_chat', id: chat.id });
}

// What was had of chats no longer on the strip goes.
function forkPeeksFollow() {
  var on = {}, id;
  for (var i = 0; i < FORKS.strip.length; i++) on[FORKS.strip[i].id] = true;
  for (id in FORKS.peeks) if (!on[id]) delete FORKS.peeks[id];
  for (id in FORKS.peeking) if (!on[id]) delete FORKS.peeking[id];
}

/** @param {import('./protocol').FromServer<'chat_peek'>} m */
function forkPeeked(m) {
  if (!m || !m.id) return;
  var chat = null;
  for (var i = 0; i < FORKS.strip.length; i++) if (FORKS.strip[i].id === m.id) chat = FORKS.strip[i];
  if (!chat) return;
  FORKS.peeks[m.id] = { messages: Number(m.messages), transcript: m.transcript || [], marks: m.marks || [] };
  // Its card, drawn again from it where it stands, at the end of its
  // conversation, the way the chat is read when it is slid onto.
  var pane = document.querySelector('.fork-pane[data-chat="' + m.id + '"]');
  var old = pane && pane.querySelector(':scope > .fork-look');
  if (!pane || !old || !forkPeekFresh(chat)) return;
  var look = forkLook(chat);
  look.setAttribute('inert', '');
  look.setAttribute('aria-hidden', 'true');
  pane.replaceChild(look, old);
  var t = look.querySelector('[data-was="transcript"]');
  if (t) t.scrollTop = t.scrollHeight;
}

function forkRoom(room) {
  var col = $('chatCol');
  if (col) stripVar(col, '--strip-room', room + 'px');
  // At a desk the conversation's track is widened by it; a phone has one
  // pane and no track to widen.
  var reserve = narrow() ? 0 : room;
  if (reserve === FORKS.reserve) return;
  var shrinks = reserve < FORKS.reserve;
  FORKS.reserve = reserve;
  if (!shrinks) { forkTrack(); return; }
  /* Narrower at once, not eased (`transition: grid-template-columns` in
     app.css). A chat going off the strip is one closed, and the chat slid
     back to stands where it was slid to only in a row as narrow as it ends
     up: in a wider one there is too little to scroll, and it stood 128
     pixels to the side and eased back (fr_74e2f2bd025d). The strip going
     altogether was never eased either. */
  var app = $('app');
  if (app) app.classList.add('strip-shrinks');
  forkTrack();
  if (!app) return;
  void app.offsetWidth;
  app.classList.remove('strip-shrinks');
}

/* The conversation's track, widened by the strip.

   A dragged edge is a width in pixels and `chatWidth` already adds the
   strip's room to it (`--fork-w`). An edge nobody has dragged is a share of
   the window, and a share cannot have pixels added to it, so the width it
   has at the moment the strip opens is written down as pixels for as long
   as there is a strip, and the share is put back when there is not. */
var forkTrackTries = 0;
function forkTrack() {
  var root = document.documentElement.style;
  stripVar(document.documentElement, '--fork-w', FORKS.reserve + 'px');
  if (CHAT_W) { FORKS.pinned = 0; return; }
  if (FORKS.reserve && !FORKS.pinned && !narrow()) {
    var box = chatRoom();
    if (!box) {
      // A page opened straight into a fork gets here before it has been
      // laid out, when neither column has a width to measure yet.
      if (forkTrackTries++ < 60) window.requestAnimationFrame(forkTrack);
      return;
    }
    forkTrackTries = 0;
    FORKS.pinned = Math.round(box.width);
    root.setProperty('--chat-track', 'minmax(0px, calc(' + FORKS.pinned
      + 'px + var(--fork-w) + var(--gutter)))');
    root.setProperty('--canvas-track',
      'minmax(calc(' + CANVAS_MIN + 'px + 2 * var(--gutter)), 2fr)');
  } else if (!FORKS.reserve && FORKS.pinned) {
    FORKS.pinned = 0;
    root.removeProperty('--chat-track');
    root.removeProperty('--canvas-track');
  }
}

/* ---------- moving along the strip is this page's own act ----------

   Petar, 23 October 2026: "clicking left and right somehow falls into a no
   mans land, where I can shuffle between left and right and can never reach
   the middle chat ... changing url doesn't have to mean refresh and loading
   information ... it should definitely NOT affect anything on screen that
   controls my interaction". Every chat of the strip is on this page already:
   the one being talked in, and each beside it, kept as it was left
   (`forkPark`) or drawn from what the server sent for its card
   (`chat_peek`). So moving to one is done here, at once, by the same hand a
   switch from the server is drawn with, and the server is told after. Until
   then the server's answer was waited for, with the middle of the strip an
   inert copy that took no typing, and a second press while it was on its way
   undid the first. Now the answer, when it comes, finds the chat already
   there and draws nothing (`FORKS.asked`, `forkBehind`). */
/** @param {string} id @param {any[]} [strip] the strip as it will be, when a close is shortening it */
function stripGo(id, strip) {
  if (!id || id === CHATS.active || ADDR.front || !CHATS.active) return false;
  var laid = strip || FORKS.strip, at = -1;
  for (var i = 0; i < laid.length; i++) if (laid[i].id === id) at = i;
  if (at < 0) return false;
  var row = laid[at], kept = FORKS.parked[id];
  var whole = !!kept && !(kept.stale && Number(row.messages) !== kept.messages);
  var peek = forkPeekFresh(row) ? FORKS.peeks[id] : null;
  if (!whole && !peek) return false;
  var chat = Object.assign({}, chatById(id) || { task: '', folder_id: null, loose: true },
                           { id: id, title: row.title, messages: row.messages, fork_of: row.fork_of || '' });
  handleMessage({ type: 'chat_switched', chat: chat, local: true, running: null,
                  transcript: whole ? [] : peek.transcript,
                  forks: { strip: laid.length > 1 ? laid : [], marks: whole ? kept.marks : peek.marks,
                           bare: whole ? kept.bare : false } });
  return true;
}

// The chat the strip has come to rest on, opened: here, or by the server
// when this page has nothing of it yet.
/** @param {string} id */
function stripHere(id) {
  if (!id || id === CHATS.active) return;
  if (stripGo(id)) send({ type: 'open_chat', id: id, strip: forkTip() });
  else openChat(id);
}

/* A chat of the strip pressed - its card, the name of the chat a fork came
   off, a mark of a fork already on the strip: it slides into the middle,
   and is the chat being talked in when it gets there. A press while the
   strip is still moving is where it goes next. */
/** @param {string} id */
function stripTo(id) {
  if (!id) return;
  if (STRIP.moving) { STRIP.next = id; return; }
  if (id === CHATS.active) return;
  var to = forkAt(id), cards = stripCards();
  var after = function () {
    stripHere(id);
    var next = STRIP.next;
    STRIP.next = '';
    if (next && next !== CHATS.active) stripTo(next);
  };
  if (to < 0 || !cards) { after(); return; }
  stripMove({ dest: cards[to], going: [], coming: null, count: cards.length, index: to, go: id, after: after });
}

/* ---------- every chat of the strip, kept as it is ----------

   Petar, 26 September 2026 (fr_a3aadda7007c): "As I scroll left and right
   between the chats they reload ... No such loading should be happening.
   Parent chats and children for that matter should stay as they are ... as
   I was waiting for a response on a child chat, I saw tool calls and I went
   to reread parent and when I came back the list of tool calls was missing
   - which is a sign of loaded chat anew."

   Sliding to another chat of the strip used to empty the conversation and
   read the next one back from the server, and a turn still running in the
   one left was then only the words it had written so far. Now the chat
   slid away from is kept: the conversation itself, not a copy - its
   bubbles, the tool lines and the half-written answer of a turn still
   running, its cards, how far it was scrolled - and the turn's own state,
   and what was typed or attached in its box (`forkPark`). The server goes
   on sending whatever a turn writes in any chat of the strip (`Turn.tabs`
   in rouh/runtime.py), and what arrives for a kept chat is held in the
   order it came (`forkHold`). Slid back, the chat is put back exactly as it
   was (`forkResume`) and what was held is handed over as though it were
   arriving that moment (`forkReplay`), so an answer that finished off
   screen is there, whole, with every tool it ran.

   A chat of the strip not shown on this page since it was loaded has
   nothing kept, and is read back from the server the first time. So is a
   kept one that stopped hearing about itself - the socket went away, or it
   was closed off the strip - when something happened in it meanwhile. */

// The page's own record of the turn on screen, which goes with the chat.
var PARK_S = ['busy', 'state', 'stopped', 'textDone', 'tools', 'turn', 'turnSign', 'turnAsked'];
//: A chat kept for longer than this many messages is read back instead: an
//: answer streamed for an hour off screen is not worth holding word by word.
var HOLD_MOST = 20000;
//: What is never held. The sound of a turn is this tab's and went with the
//: move (`stopPlayback`); an answer to a press is for the chat pressed in.
var HOLD_NOT = { audio_start: 1, audio_end: 1, answer_chat: 1 };

// The chat on screen, taken off it and kept whole.
function forkPark(id) {
  var t = transcriptEl();
  if (!id || !t || ADDR.front) return;
  var chat = chatById(id);
  var box = document.createElement('div');
  box.className = 'fork-parked';
  var kept = {
    box: box,
    T: {}, S: {}, retry: shared.RETRY, versions: shared.VERSIONS, stick: shared.stick,
    scroll: t.scrollTop,
    // A page of its older cards on its way now is dropped, and asked for
    // again when it is back.
    cards: { oldest: CARDS.oldest, more: CARDS.loading ? true : CARDS.more },
    typed: input ? input.value : '', files: shared.attached, sendWhenUploaded: shared.sendWhenUploaded,
    messages: chat ? Number(chat.messages) : -1,
    // Its forks' marks and whether it may be forked empty, for when it is
    // slid back to before the server has said (`stripGo`).
    marks: FORKS.marks, bare: FORKS.bare,
    held: [], stale: false
  };
  var k;
  for (k in T) if (Object.prototype.hasOwnProperty.call(T, k)) kept.T[k] = T[k];
  for (k = 0; k < PARK_S.length; k++) kept.S[PARK_S[k]] = S[PARK_S[k]];
  // A fork just sent from this chat: the answer the page is waiting on is
  // the fork's. Fork cannot be pressed while this chat is answering, so this
  // one is not, and back on it Stop showed until it was read again.
  if (FORKS.typed && FORKS.typed.from === id) kept.S.busy = false;
  while (t.firstChild) box.appendChild(t.firstChild);
  // Kept as it is, and shown as it is beside the chat being talked in
  // (`forkLook`), so nothing in it may answer to the page's own names: a
  // kept "Loading what came before" would be found before the real one.
  var named = box.querySelectorAll('[id]');
  for (k = 0; k < named.length; k++) {
    named[k].setAttribute('data-parked-id', named[k].id);
    named[k].removeAttribute('id');
  }
  // Nothing the page does next may reach into what was kept: settling the
  // screen for the chat arriving takes down the sign and the empty bubble of
  // whatever turn the record points at, and that is the kept one's. So the
  // record starts again as wiping the conversation leaves it.
  for (k in T) if (Object.prototype.hasOwnProperty.call(T, k)) T[k] = null;
  T.now = { turn: 0, root: 0 };
  T.heard = false;
  shared.RETRY = null;
  shared.VERSIONS = {};
  CARDS.gen++;
  CARDS.loading = false;
  // Its box goes with it: what is typed in one chat of the strip is that
  // chat's, and is not sent in the next.
  var hadFiles = shared.attached.length > 0;
  shared.attached = [];
  shared.sendWhenUploaded = false;
  // Each drawn again only when it held something: an empty box and an empty
  // row of files are already as they will be, and drawing either measures
  // the box, which makes the browser lay the whole page out there and then.
  if (input && input.value) { input.value = ''; growInput(); }
  if (hadFiles) drawAttachments(); else forkBtnPaint();
  FORKS.parked[id] = kept;
}

// The chat a `chat_switched` opens, put back as it was kept, when it was.
// Answers what was held for it, or null when it is to be read back instead.
/** @param {import('./protocol').FromServer<'chat_switched'>} m */
function forkResume(m) {
  var id = m.chat && m.chat.id;
  var kept = id ? FORKS.parked[id] : null;
  if (!kept) return null;
  delete FORKS.parked[id];
  // It stopped hearing about itself while it was kept (`forkKeptFollow`).
  // Only a chat nothing happened in since - no turn running in it, and as
  // many messages as it had - is still what the server holds.
  if (kept.stale && (m.running || Number(m.chat.messages) !== kept.messages)) return null;
  var t = transcriptEl();
  if (!t) return null;
  t.innerHTML = '';
  var named = kept.box.querySelectorAll('[data-parked-id]');
  for (var n = 0; n < named.length; n++) {
    named[n].id = named[n].getAttribute('data-parked-id') || '';
    named[n].removeAttribute('data-parked-id');
  }
  // The very nodes, moved back: nothing is drawn again.
  while (kept.box.firstChild) t.appendChild(kept.box.firstChild);
  var k;
  for (k in T) if (Object.prototype.hasOwnProperty.call(T, k)) delete T[k];
  for (k in kept.T) if (Object.prototype.hasOwnProperty.call(kept.T, k)) T[k] = kept.T[k];
  for (k = 0; k < PARK_S.length; k++) S[PARK_S[k]] = kept.S[PARK_S[k]];
  // A kept turn has been quiet on this screen for as long as it was off it,
  // which is not the quiet the watchdog is for.
  S.turnSign = now();
  shared.RETRY = kept.retry;
  shared.VERSIONS = kept.versions;
  shared.stick = kept.stick;
  CARDS.gen++;
  CARDS.oldest = kept.cards.oldest;
  CARDS.more = kept.cards.more;
  CARDS.loading = false;
  CARDS.keepCanvas = false;
  if (input && (input.value || kept.typed)) { input.value = kept.typed; growInput(); }
  var hadFiles = shared.attached.length > 0;
  shared.attached = kept.files || [];
  if (hadFiles || shared.attached.length) drawAttachments(); else forkBtnPaint();
  shared.sendWhenUploaded = kept.sendWhenUploaded || false;
  var b = $('sendBtn');
  if (b) b.disabled = false;
  forkBtnPaint();
  showStop();
  updateJump();
  t.scrollTop = kept.scroll;
  return kept.held;
}

// Something for a chat of the strip that is not the one on screen.
function forkHold(m) {
  var kept = FORKS && FORKS.parked[m.chat];
  if (!kept || kept.stale || HOLD_NOT[m.type]) return;
  if (kept.held.length >= HOLD_MOST) { kept.stale = true; kept.held = []; return; }
  kept.held.push(m);
}

function forkKeptStale() {
  if (!FORKS) return;
  for (var id in FORKS.parked) FORKS.parked[id].stale = true;
}

//: How many chats are kept at most, on the strip or off it.
var KEPT_MOST = 8;

/* The kept chats, after the strip has been told again. One still on it
   takes the count of messages the strip gives it, which is how many its
   conversation and what is held for it hold between them. One that has
   come off it - closed, with the forks under it - is kept too, but nothing
   arrives for it any more, so it is stale: opened again from its mark with
   nothing having happened in it, it comes back as it was, tool lines and
   all, which reading it back would not draw. The oldest to come off go
   first when more are kept than `KEPT_MOST`. */
function forkKeptFollow() {
  var rows = {}, off = [], id;
  for (var i = 0; i < FORKS.strip.length; i++) rows[FORKS.strip[i].id] = FORKS.strip[i];
  for (id in FORKS.parked) {
    var kept = FORKS.parked[id];
    if (rows[id]) {
      if (!kept.stale) kept.messages = Number(rows[id].messages);
      kept.off = 0;
    } else {
      kept.stale = true;
      if (!kept.off) kept.off = now();
      off.push(id);
    }
  }
  off.sort(function (a, b) { return FORKS.parked[a].off - FORKS.parked[b].off; });
  var many = Object.keys(FORKS.parked).length;
  for (var k = 0; k < off.length && many > KEPT_MOST; k++, many--) delete FORKS.parked[off[k]];
}

// What was held for the chat just slid back, handed over in order. Then the
// turn on screen is what the server says it is at the switch: a turn the
// chat was left in the middle of, and whose end was never held because it
// happened here - the chat a fork was sent from, waiting on nothing - ends.
/** @param {import('./protocol').FromServer<'chat_switched'>} m */
function forkReplay(m) {
  var held = FORKS.resumed;
  FORKS.resumed = null;
  if (!held) return;
  for (var i = 0; i < held.length; i++) {
    try {
      handleMessage(held[i]);
    } catch (err) {
      console.error('rouh: a held "' + held[i].type + '" could not be handled:', err);
    }
  }
  // Not after a move of this page's own, which knows nothing of the turn yet:
  // the server's answer to it says, and a turn left running here is still
  // running (`stripGo`).
  if (!m.local && !m.running && turnIsRunning()) endTurnOnScreen();
  // An upload that finished while the chat was kept, with Send pressed
  // before it did, goes now.
  if (shared.sendWhenUploaded && !attUploading()) {
    var fork = shared.sendWhenUploaded === 'fork';
    shared.sendWhenUploaded = false;
    sendTyped(fork);
  }
}

/* ---------- the row: the chats themselves, side by side ----------

   Petar, 24 September 2026, on the first version, which drew each chat
   beside this one as a narrow card with its name, a few lines and "Back":
   "the vertical bar should be the actual chat, not a button ... I don't want
   it to snap and immediately see something else. I want to be able to slide
   like a side scroll", and then, of the desk, a screenshot of the right-hand
   edge of a real conversation - bubbles cut off by the edge, a card's line,
   the fork's own line, the box with Send - captioned "this is what I want".

   So the conversation's column holds a row that scrolls sideways
   (`#forkRow`, `.stripped` in app.css). Every chat on the strip is a card in
   it, in order, the width of the conversation. The one being talked in is
   the real one, `#chatSelf`; each other one is that chat as it looks, cut
   off by the edge of the column (`forkLook`). A finger, a trackpad, a wheel
   over the edge or a press on it moves the row, and nothing snaps it: it
   stays where it is let go, and only when another chat is the one most in
   view where it comes to rest does it carry on to that one, which is then
   the chat being talked in (`stripSettled`). */
var STRIP = { ids: '', active: '', mine: false, going: '', moving: false, placed: false, touching: false, next: '' };

// Where the row goes after the strip has been drawn again: nowhere when
// nothing moved, nowhere when the person scrolled it there themselves, and
// otherwise to the chat being talked in, sliding from the one they were in
// when that is still on the row.
function stripPlace() {
  var row = $('forkRow');
  panesToTheirPlace();
  var ids = forkIds().join(' ');
  var same = ids === STRIP.ids;
  var was = STRIP.active;
  var moved = was !== CHATS.active;
  // Nothing moved: the row stays exactly where it is, and a slide the person
  // made that the server has still to answer is still theirs. Clearing it
  // here, on a draw in between, is what threw the row back to the chat they
  // had slid away from when the answer came.
  if (!moved && same) return;
  var mine = STRIP.mine;
  STRIP.ids = ids;
  STRIP.active = CHATS.active;
  STRIP.mine = false;
  if (moved) STRIP.going = '';
  // Hidden behind the canvas there is nothing to measure; the pane coming
  // back is a resize, and that puts the chat being talked in in the middle.
  if (!row || !row.clientWidth) return;
  // The row moved there already, the moment it was pressed (`stripMove`).
  var placed = STRIP.placed;
  STRIP.placed = false;
  if (moved && placed) { row.scrollLeft = stripCentre($('chatSelf')); return; }
  if (moved && mine) return;
  var target = stripCentre($('chatSelf'));
  var from = was ? row.querySelector('.fork-pane[data-chat="' + was + '"]') : null;
  if (moved && from) {
    row.scrollLeft = stripCentre(from);
    stripSlide(row, target);
    return;
  }
  row.scrollLeft = target;
}

// Where the row has to be scrolled to for this card to stand in the middle,
// or as near the middle as the ends of the row let it.
function stripCentre(card) {
  var row = $('forkRow');
  if (!card || !row) return 0;
  var most = Math.max(0, row.scrollWidth - row.clientWidth);
  return Math.min(most, Math.max(0, card.offsetLeft - (row.clientWidth - card.offsetWidth) / 2));
}

function stripSlide(row, left) {
  if (row.scrollTo) {
    try { row.scrollTo({ left: left, behavior: 'smooth' }); return; } catch (err) { /* old engines */ }
  }
  row.scrollLeft = left;
}

/* The frame a chat beside this one is drawn in: the chat on screen's head
   and box, and its conversation's scroller with nothing in it. Every id is
   renamed, so nothing the page looks up by id finds the copy instead of the
   real thing (a few looks keyed by id are given again by `data-was` in
   app.css), and no frame or player is carried along.

   Never the conversation itself. Until 23 October 2026 every move along the
   strip copied the whole of the chat on screen, every message and card of
   it, once for its card and again for each card drawn from that copy, and
   the page stood still while it did (Petar: "something takes a long time to
   load and refresh, and blocks my mouse for input and typing"). A chat
   beside this one is shown with its own conversation, the very nodes, moved
   (`forkLook`). */
/** @returns {any} */
function forkCopy() {
  var self = $('chatSelf');
  if (!self) return el('div');
  var copy = /** @type {HTMLElement} */ (cloneBut(self, $('transcript')));
  copy.removeAttribute('id');
  // And nothing of a movement it was taken in the middle of (`stripMove`).
  copy.removeAttribute('style');
  copy.className = 'fork-look';
  var named = copy.querySelectorAll('[id]');
  for (var i = 0; i < named.length; i++) {
    named[i].setAttribute('data-was', named[i].id);
    named[i].removeAttribute('id');
  }
  var gone = copy.querySelectorAll('iframe, video, audio, .fork-x, .panel-hide, .fork-nav, .fork-path');
  for (i = 0; i < gone.length; i++) gone[i].remove();
  var typed = copy.querySelectorAll('textarea');
  for (i = 0; i < typed.length; i++) /** @type {HTMLTextAreaElement} */ (typed[i]).value = '';
  var off = copy.querySelectorAll('[data-was="jumpLatest"], [data-was="stopBtn"], [data-was="attachRow"]');
  for (i = 0; i < off.length; i++) /** @type {HTMLElement} */ (off[i]).hidden = true;
  // Send as it stands in a chat with nobody waiting on an answer.
  var sendIt = /** @type {HTMLButtonElement|null} */ (copy.querySelector('[data-was="sendBtn"]'));
  if (sendIt) sendIt.disabled = false;
  return copy;
}

// A node and everything in it but what is inside `skip`, which is copied empty.
/** @param {Node} node @param {Node|null} skip @returns {Node} */
function cloneBut(node, skip) {
  var copy = node.cloneNode(false);
  if (node === skip) return copy;
  for (var kid = node.firstChild; kid; kid = kid.nextSibling) copy.appendChild(cloneBut(kid, skip));
  return copy;
}

/* One chat beside the one being talked in, as it looks. The copy kept when
   the person left it, while nothing has been said in it since; otherwise
   the conversation's own frame with this chat's last things said drawn in
   it, which is what a chat never opened on this page looks like. */
function forkLook(chat) {
  var kept = FORKS.parked[chat.id];
  var look = forkCopy();
  var t = look.querySelector('[data-was="transcript"]');
  var peek = forkPeekFresh(chat) ? FORKS.peeks[chat.id] : null;
  // The chat as it was left, itself, when nothing has happened in it since
  // or there is nothing fresher to draw it from.
  if (t && kept && (!kept.stale && !kept.held.length || !peek)) {
    t.innerHTML = '';
    t.appendChild(kept.box);
    look.__scroll = kept.scroll;
    // Its fork lines as the strip stands now.
    var marks = kept.box.querySelectorAll('.fork-mark');
    for (var k = 0; k < marks.length; k++) {
      var open = forkIds().indexOf(marks[k].getAttribute('data-fork')) >= 0;
      marks[k].classList.toggle('is-open', open);
      var state = marks[k].querySelector('.fork-mark-state');
      if (state) state.textContent = open ? 'On the right' : 'Open it';
    }
    var box = /** @type {HTMLTextAreaElement|null} */ (look.querySelector('textarea[data-was="input"]'));
    if (box) box.value = kept.typed || '';
  } else if (t && peek) {
    t.innerHTML = '';
    t.appendChild(el('p', 'stream-title', forkName(chat.id)));
    drawTranscriptInto(t, peek.transcript, peek.marks);
  } else if (t) {
    t.innerHTML = '';
    t.appendChild(el('p', 'stream-title', forkName(chat.id)));
    var lines = chat.said || [];
    for (var i = 0; i < lines.length; i++) {
      var mine = lines[i].role === 'user';
      var turn = el('div', 'turn ' + (mine ? 'user' : 'assistant'));
      turn.appendChild(el('div', 'turn-who', mine ? 'You' : 'Rouh'));
      var body = el('div', 'turn-body');
      turn.appendChild(body);
      drawWords(body, lines[i].text);
      t.appendChild(turn);
    }
  }
  // Its own head: the fork it is, or nothing but the two acts.
  forkHeadInto(look, chat.fork_of ? forkName(chat.id) : '', chat.fork_of || '');
  var dots = look.querySelector('[data-was="chatMenuBtn"]');
  if (dots) dots.hidden = chat.id === CHATS.general && !chat.fork_of;
  var project = look.querySelector('[data-was="crumbProject"]');
  if (project) project.hidden = true;
  return look;
}

/* A copy's head as a fork's own is (`showCrumb`): the fork glyph naming the
   chat it came off, and its name after it. Nothing of either for a chat
   that is not a fork. */
function forkHeadInto(look, name, of) {
  var chip = look.querySelector('[data-was="crumbFork"]');
  if (chip) chip.hidden = !of;
  var from = look.querySelector('[data-was="crumbForkName"]');
  if (from && of) from.textContent = forkName(of);
  var title = look.querySelector('[data-was="crumbTitle"]');
  if (title && of) { title.textContent = name; title.hidden = !name; }
}

function forkPane(chat, index) {
  var pane = el('div', 'fork-pane');
  pane.setAttribute('data-chat', chat.id);
  pane.setAttribute('role', 'group');
  var name = forkName(chat.id);
  pane.setAttribute('aria-label', (index === 0 ? 'Main chat: ' : 'Fork: ') + name);
  pane.title = name;
  var look = forkLook(chat);
  // Looked at, not used: nothing in it takes a press or a focus, and a press
  // anywhere on it lands on the card, which slides it in.
  look.setAttribute('inert', '');
  // And read out as the card's own label, not as a second set of every
  // control on the page.
  look.setAttribute('aria-hidden', 'true');
  pane.appendChild(look);
  // Its own cross, which is a real one: the copy under it is only looked at.
  if (chat.fork_of) pane.appendChild(forkX(chat));
  pane.addEventListener('click', function () { stripTo(chat.id); });
  return pane;
}

/* ---------- at a desk: strips either side, and the count in the head ----------

   Petar, 26 October 2026 (fr_341089f4b07a): "please implement this setup for
   chats and canvas. title bar alignments, forks in sidebars", with a mockup
   of a fork between the chat it came off and the fork from it, each of those
   a dimmed strip with its number and its name read sideways, and in the
   fork's head a back arrow, the count ("2 / 3", which opens the whole path),
   and an on arrow, before its name. A press on a strip, an arrow, a row of
   the path or a sideways stroke of a trackpad opens that chat at once
   (`stripGo`). The rest of the strip is not drawn at a desk: the count says
   it is there and the path lists it. A phone keeps its row of whole chats a
   finger drags. */
/** @param {any} chat @param {number} index @param {string} side */
function forkStrip(chat, index, side) {
  var name = forkName(chat.id);
  var b = el('button', 'fork-pane fork-strip is-' + side);
  b.type = 'button';
  b.setAttribute('data-chat', chat.id);
  b.setAttribute('aria-label', (index === 0 ? 'Main chat' : 'Fork ' + (index + 1)) + ': ' + name);
  b.title = name;
  b.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none"'
    + ' stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    + (side === 'left' ? '<path d="m14.5 6-6 6 6 6"/>' : '<path d="m9.5 6 6 6-6 6"/>') + '</svg>';
  b.appendChild(el('span', 'fork-strip-no', String(index + 1)));
  b.appendChild(el('span', 'fork-strip-name', name));
  b.addEventListener('click', function () { stripTo(chat.id); });
  return b;
}

/* A fork being opened at a desk: its strip on the right at once, saying
   what was asked, until the server's answer lays the strip out with it. */
function forkStripComing(how) {
  var col = $('chatCol'), right = $('forkRight');
  if (!col || !right) return false;
  if (how.text) hideTyping();
  var at = col.classList.contains('stripped') ? forkAt(CHATS.active) : 0;
  if (at < 0) return false;
  var mk = how.mark;
  var name = (mk && (mk.title || String(mk.asked || '').trim())) || how.text || '💬 New chat';
  var b = forkStrip({ id: mk ? mk.id : '' }, at + 1, 'right');
  b.classList.add('is-coming');
  b.setAttribute('aria-hidden', 'true');
  b.tabIndex = -1;
  var label = b.querySelector('.fork-strip-name');
  if (label) label.textContent = name;
  b.title = name;
  right.innerHTML = '';
  right.appendChild(b);
  right.hidden = false;
  col.classList.add('stripped');
  // The room it takes is the room the strip the answer brings will keep.
  var count = Math.max(at + 2, FORKS.strip.length);
  forkRoom(forkRoomFor(count));
  return true;
}

// The head's count and its two arrows. `at` is this chat's place on the
// strip, or -1 when there is no strip.
/** @param {number} at */
function forkNavPaint(at) {
  var nav = $('forkNav'), prev = $('forkPrev'), next = $('forkNext');
  if (!nav || !prev || !next) return;
  var strip = FORKS.strip, on = at >= 0 && strip.length > 1;
  nav.hidden = !on;
  if (!on) { if ($('forkPath')) forkPathShow(false); return; }
  $('forkNavAt').textContent = String(at + 1);
  $('forkNavOf').textContent = String(strip.length);
  var count = $('forkCount');
  if (count) {
    var said = 'Chat ' + (at + 1) + ' of ' + strip.length + ' on this path of forks';
    count.setAttribute('aria-label', said + '. Show the whole path');
    count.title = said;
  }
  var before = at > 0 ? strip[at - 1] : null, after = at < strip.length - 1 ? strip[at + 1] : null;
  prev.disabled = !before;
  next.disabled = !after;
  var back = before ? 'Back to ' + forkName(before.id) : 'This is the main chat';
  var on2 = after ? 'On to the fork ' + forkName(after.id) : 'No fork from this chat';
  prev.setAttribute('aria-label', back); prev.title = back;
  next.setAttribute('aria-label', on2); next.title = on2;
}

// The whole path, behind the count: every chat on the strip in its order,
// each one in a step from the one it came off, this one marked.
function forkPathFill() {
  var menu = $('forkPath');
  if (!menu) return false;
  menu.innerHTML = '';
  var strip = FORKS.strip;
  if (strip.length < 2) return false;
  for (var i = 0; i < strip.length; i++) {
    var c = strip[i];
    var item = el('button', 'menu-item fork-path-item');
    item.type = 'button';
    item.setAttribute('role', 'menuitem');
    item.style.setProperty('--depth', String(i));
    if (c.id === CHATS.active) {
      item.classList.add('is-here');
      item.setAttribute('aria-current', 'true');
    }
    item.appendChild(el('span', 'fork-strip-no', String(i + 1)));
    item.appendChild(el('span', 'menu-name', forkName(c.id)));
    (function (id) {
      item.addEventListener('click', function () { if (id !== CHATS.active) stripTo(id); });
    }(c.id));
    menu.appendChild(item);
  }
  return true;
}
var forkPathShow = RouhMenu.bind($('forkCount'), $('forkPath'), { open: forkPathFill, align: 'start' });
if ($('forkPrev')) $('forkPrev').addEventListener('click', function () { forkStep(-1); });
if ($('forkNext')) $('forkNext').addEventListener('click', function () { forkStep(1); });

/** @param {number} by */
function forkStep(by) {
  var at = forkAt(CHATS.active), to = at >= 0 ? FORKS.strip[at + by] : null;
  if (to) stripTo(to.id);
}

// Each card beside the one being talked in, scrolled where it was left, or
// at its end - the way a conversation is read - when it was never on screen.
function panesToTheirPlace() {
  var looks = document.querySelectorAll('.fork-pane .fork-look');
  for (var i = 0; i < looks.length; i++) {
    var t = looks[i].querySelector('[data-was="transcript"]');
    if (!t) continue;
    t.scrollTop = looks[i].__scroll != null ? looks[i].__scroll : t.scrollHeight;
  }
}

// The row has come to rest. With the chat being talked in still the one
// most in view, it stays exactly where it was let go: a little way across
// is a little way across, and nothing springs back. With another one most
// in view, the row carries on until that one is in the middle, and it is
// the one being talked in.
(function () {
  var col = $('chatCol'), row = $('forkRow');
  if (!col || !row) return;
  var timer = 0, touching = false;
  // Only while the row is on the screen. Hidden behind the canvas it
  // measures nothing, every card stands at nought, and the first of them
  // would be taken for the one most in view.
  function stripShown() {
    return col.classList.contains('stripped') && row.clientWidth > 0;
  }
  function stripSettled() {
    window.clearTimeout(timer);
    if (touching || STRIP.moving || !stripShown()) return;
    var cards = row.querySelectorAll('.fork-pane, #chatSelf');
    var from = row.scrollLeft, to = from + row.clientWidth, best = null, most = -1;
    for (var i = 0; i < cards.length; i++) {
      var a = cards[i].offsetLeft, b = a + cards[i].offsetWidth;
      var seen = Math.min(b, to) - Math.max(a, from);
      if (seen > most) { most = seen; best = cards[i]; }
    }
    var id = best && best.getAttribute('data-chat');
    if (!id || id === CHATS.active || id === STRIP.going) return;
    STRIP.going = id;
    STRIP.mine = true;
    stripSlide(row, stripCentre(best));
    stripHere(id);
  }
  function later() {
    window.clearTimeout(timer);
    timer = window.setTimeout(stripSettled, 180);
  }
  row.addEventListener('scroll', function () {
    if (stripShown()) later();
  }, { passive: true });
  function lifted() {
    touching = false;
    STRIP.touching = false;
    forkDrawLater();
    later();
  }
  row.addEventListener('touchstart', function () { touching = true; STRIP.touching = true; }, { passive: true });
  row.addEventListener('touchend', lifted, { passive: true });
  row.addEventListener('touchcancel', lifted, { passive: true });
  // A wheel turned over a chat at the edge moves the row, the way a
  // trackpad's sideways stroke does anywhere on it: the chat at the edge
  // has nothing of its own to scroll.
  row.addEventListener('wheel', function (e) {
    if (!stripShown() || Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
    if (!e.target || !e.target.closest || !e.target.closest('.fork-pane')) return;
    row.scrollLeft += e.deltaY;
    e.preventDefault();
  }, { passive: false });
  // At a desk a trackpad's sideways stroke over the conversation goes to the
  // chat beside it, once a stroke, unless what it is over scrolls sideways
  // itself (a wide table, a block of code).
  var stroke = 0, strokeAt = 0, quietUntil = 0;
  function scrollsSideways(node) {
    for (var n = node; n && n !== row; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1) {
        var x = getComputedStyle(n).overflowX;
        if (x === 'auto' || x === 'scroll') return true;
      }
    }
    return false;
  }
  row.addEventListener('wheel', function (e) {
    if (!stripShown() || narrow() || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    if (scrollsSideways(e.target)) return;
    e.preventDefault();
    var t = now();
    // The rest of a stroke that has already moved, still coasting.
    if (t < quietUntil) { quietUntil = t + 250; return; }
    if (t - strokeAt > 300) stroke = 0;
    strokeAt = t;
    stroke += e.deltaX;
    if (Math.abs(stroke) < 90) return;
    var by = stroke > 0 ? 1 : -1;
    stroke = 0;
    quietUntil = t + 250;
    forkStep(by);
  }, { passive: false });
  // A card is a share of the column, so a column that changes size - a
  // window turned on its side, a keyboard coming up, the pane coming back
  // from the canvas, the sidebar folding - puts the chat being talked in
  // back in the middle.
  function again() {
    // Not while the strip is moving, nor once it has moved somewhere the
    // server has still to say it is (`stripMove`): this is the column
    // changing size under it, and it is in the middle already.
    if (STRIP.moving || STRIP.placed || !stripShown()) return;
    row.scrollLeft = stripCentre($('chatSelf'));
    panesToTheirPlace();
  }
  if (window.ResizeObserver) new ResizeObserver(again).observe(row);
  else window.addEventListener('resize', again);
}());

/* Closing a fork is this tab's own act, and nothing can refuse it: the
   server only works out the same strip from the same two ends
   (`close_fork` in rouh/runtime.py). So it is done here, the moment the
   strip has narrowed: the strip is shortened, and when the person was in the
   fork they are in the chat it came off, which is on this page already
   (`stripGo`). The server is told after, and its answer draws nothing.
   Until 23 October 2026 the page waited for that answer, and a list of the
   chats sent before it - with the fork still on the strip - laid it out
   again for a moment (Petar: "If I close a fork it disappears, but somehow
   reappears again afterwards for a moment"). A strip the server worked out
   before the close is passed over (`forkBehind`), and if the socket goes
   first the page asks for the strip it closed to when it is back, which is
   the strip on its screen (`hello`). */
function forkClose(id) {
  if (!id) return;
  var shut = forkAt(id), at = forkAt(CHATS.active);
  if (shut < 1 || at < 0) { send({ type: 'close_fork', id: id }); return; }
  var back = FORKS.strip[shut - 1].id, inside = at >= shut;
  var left = FORKS.strip.slice(0, shut);
  var done = function () {
    // In the fork, and the chat it came off not on this page to move to:
    // the server's answer brings it.
    if (inside && !stripGo(back, left)) { send({ type: 'close_fork', id: id }); return; }
    if (!inside) {
      FORKS.strip = left.length > 1 ? left : [];
      forksPaint();
      forkMarksDraw();
      forkBtnPaint();
      addrTouch();
    }
    send({ type: 'close_fork', id: id });
  };
  var cards = STRIP.moving ? null : stripCards();
  if (!cards) { done(); return; }
  stripMove({ dest: cards[inside ? shut - 1 : at], going: cards.slice(shut), coming: null,
              count: shut, index: inside ? shut - 1 : at, go: inside ? back : '', after: done });
}

/* ---------- the strip moves the moment it is pressed ----------

   Petar, 21 October 2026 (fr_74e2f2bd025d), of closing a fork: "it should
   immediately close and slide over to the previous (parent) chat. And it
   should slide over, not jump", and then, of the slide that did that: "it
   feels like it stays open and then it disappears and things change. can we
   make it instead reduce width to 0 without crunching the contents ... also
   can you make the opposite true? when I click a fork it should immediately
   expand to the right by expanding width of the side chat ... a loading
   circle inside can appear, but the visuals and mechanics should be
   immediate and intuitive."

   So every press that changes the strip moves it at once, in one movement,
   from where it is to where the server's answer will put it
   (`stripMove`): a fork closed narrows to nothing where it stands, with
   everything after it, while the chat it came off slides into its place; a
   fork opened widens from nothing beside the chat it comes off, while that
   chat slides aside; a chat of the strip pressed slides into the middle.
   What is in a card keeps its width as the card narrows or widens, and the
   card cuts it off (`.strip-sized` in app.css). The server's answer is held
   until the movement is over (`holdMessages`), and then puts the real chat
   exactly where its card has got to (`STRIP.placed`), so nothing moves
   again. A fork being opened is its question and a sign that the answer is
   on its way, or a ring while the chat is read, until it arrives
   (`forkComing`). With no answer the strip is put back as it was. */

//: How long the strip takes to get there, the way a sheet moves on iOS.
var MOVE_MS = 320;

function forkAt(id) {
  for (var i = 0; i < FORKS.strip.length; i++) if (FORKS.strip[i].id === id) return i;
  return -1;
}

// The cards of the strip on screen, in its order, or null when it is not
// on screen as the page has it.
function stripCards() {
  var col = $('chatCol'), row = $('forkRow');
  if (!col || !row || !col.classList.contains('stripped') || !row.clientWidth || ADDR.front) return null;
  // A desk's strips are not cards a chat slides along: a press there opens
  // the chat at once (`forkStrip`).
  if (!narrow()) return null;
  var cards = Array.prototype.slice.call(
    row.querySelectorAll('#forkLeft > .fork-pane, #chatSelf, #forkRight > .fork-pane'));
  return cards.length === FORKS.strip.length ? cards : null;
}

/* Opening: a fork just sent (`text`), or one marked in this chat (`mark`),
   widens in on the right of the chat it comes off, and whatever was on the
   right of that chat narrows away. Says whether the strip is moving. */
function forkComeNow(how) {
  var row = $('forkRow'), col = $('chatCol'), self = $('chatSelf'), right = $('forkRight');
  if (!row || !col || !self || !right || ADDR.front || !CHATS.active) return false;
  if (!narrow()) return forkStripComing(how);
  var was = col.classList.contains('stripped');
  var at = was ? forkAt(CHATS.active) : 0;
  if (at < 0) return false;
  if (!was) {
    // One chat alone is not a row of cards yet: it is made one, as wide as
    // the column, for the new card to come in beside.
    stripVar(col, '--strip-room', '0px');
    col.classList.add('stripped');
  }
  var cards = was ? stripCards() : (row.clientWidth ? [self] : null);
  if (!cards) {
    if (!was) col.classList.remove('stripped');
    return false;
  }
  // The chat a fork is sent from is not answering it: the dots `sendTyped`
  // put up here belong to the fork, and are drawn in its card.
  if (how.text) hideTyping();
  var pane = forkComing(how);
  right.hidden = false;
  right.insertBefore(pane, right.firstChild);
  return stripMove({
    dest: pane, going: cards.slice(at + 1), coming: pane,
    count: at + 2, index: at + 1, go: how.mark ? how.mark.id : '',
    until: ['chat_switched'], stop: ['fork_refused'], most: 6000
  });
}

/* A fork being opened, until it is there: the conversation's own frame,
   with its head saying it is a fork of this chat, and in it what was asked
   and the answer's dots, or a ring while it is read back. One that was on
   this page before and has not changed since is the copy kept of it. */
function forkComing(how) {
  var mk = how.mark;
  var pane = el('div', 'fork-pane is-coming');
  if (mk) pane.setAttribute('data-chat', mk.id);
  pane.setAttribute('aria-hidden', 'true');
  var row = mk ? Object.assign({}, FORKS.rows[mk.id] || {}, { id: mk.id, fork_of: CHATS.active,
                                 messages: mk.messages, title: mk.title }) : null;
  var kept = mk && FORKS.parked[mk.id];
  var look;
  if (row && kept && !kept.stale) {
    look = forkLook(row);
  } else {
    look = forkCopy();
    var t = look.querySelector('[data-was="transcript"]');
    if (t) {
      t.innerHTML = '';
      // Its name as its mark has it, which is not on the strip to be looked
      // up (`forkName`). A fork just made has none yet, and is called what
      // the server calls a chat with none (`conversations.UNTITLED`).
      t.appendChild(el('p', 'stream-title', mk ? mk.title || '\uD83D\uDCAC New chat' : '\uD83D\uDCAC New chat'));
      var asked = how.text || (mk && String(mk.asked || '').trim()) || '';
      if (asked) {
        var turn = el('div', 'turn user');
        turn.appendChild(el('div', 'turn-who', 'You'));
        var body = el('div', 'turn-body');
        turn.appendChild(body);
        drawWords(body, asked);
        t.appendChild(turn);
      }
      if (how.text) {
        // The answer to it, on its way, as it is drawn in the fork.
        var typing = el('div', 'turn assistant typing');
        typing.appendChild(el('div', 'turn-who', 'Rouh'));
        var dots = el('div', 'turn-body');
        for (var i = 0; i < 3; i++) dots.appendChild(el('span', 'dot'));
        typing.appendChild(dots);
        t.appendChild(typing);
      } else {
        t.appendChild(el('div', 'fork-loading'));
      }
    }
    forkHeadInto(look, mk ? mk.title || '\uD83D\uDCAC New chat' : '\uD83D\uDCAC New chat', CHATS.active);
    var menu = look.querySelector('[data-was="chatMenuBtn"]');
    if (menu) menu.hidden = true;
    var project = look.querySelector('[data-was="crumbProject"]');
    if (project) project.hidden = true;
  }
  look.setAttribute('inert', '');
  look.setAttribute('aria-hidden', 'true');
  pane.appendChild(look);
  return pane;
}

/* The movement itself. `dest` is the card of the chat that is to be the
   one talked in, which ends up where the strip the answer brings puts it:
   `count` cards, it the `index`th. Everything is worked out from that
   strip: how much of a chat beside it shows (`forkRoomFor`), how much wider
   the conversation's track is at a desk (`forkRoom`), and so where that
   card stands. Each frame moves all of them the same share of the way. */
function stripMove(p) {
  var row = $('forkRow'), col = $('chatCol'), app = $('app');
  if (!row || !col) return false;
  var desk = !narrow();
  var gap = forkPx('--strip-gap');
  var room0 = parseFloat(col.style.getPropertyValue('--strip-room')) || 0;
  var room1 = forkRoomFor(p.count);
  var reserve0 = desk ? FORKS.reserve || 0 : 0, reserve1 = desk ? room1 : 0;
  var rowW1 = row.clientWidth + reserve1 - reserve0, card1 = rowW1 - room1;
  var off1 = p.index * (card1 + gap);
  var most1 = Math.max(0, p.count * card1 + (p.count - 1) * gap - rowW1);
  var x1 = p.count > 1 ? off1 - Math.min(most1, Math.max(0, off1 - (rowW1 - card1) / 2)) : 0;
  var x0 = p.dest.offsetLeft - row.scrollLeft;
  // A track getting wider is set as it will be, so that it is held at a
  // width in pixels, which the frames below then widen it to; one getting
  // narrower is narrowed by them and set by the answer.
  if (reserve1 > reserve0) forkRoom(room1);
  if (app) app.classList.add('strip-moving');
  var going = p.going.map(function (c) {
    var w = c.offsetWidth;
    c.classList.add('strip-sized');
    c.style.setProperty('--sized-w', w + 'px');
    return w;
  });
  if (p.coming) {
    p.coming.classList.add('strip-sized');
    p.coming.style.setProperty('--sized-w', card1 + 'px');
  }
  STRIP.moving = true;
  STRIP.placed = true;
  // The row coming to rest on that chat is not the person asking to open
  // it (`stripSettled`): the press is what opens it.
  STRIP.going = p.go || '';
  // Opening a fork waits for the server, which makes it; nothing else does.
  if (p.until) holdMessages({ most: p.most, until: p.until, stop: p.stop, undo: stripUndo });
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var t0 = now(), took = reduce ? 0 : MOVE_MS;
  function at(a, b, e) { return a + (b - a) * e; }
  function frame() {
    var t = took ? Math.min(1, (now() - t0) / took) : 1;
    var e = 1 - Math.pow(1 - t, 3);
    if (room1 !== room0) stripVar(col, '--strip-room', at(room0, room1, e) + 'px');
    if (desk && reserve1 !== reserve0) stripVar(document.documentElement, '--fork-w', at(reserve0, reserve1, e) + 'px');
    for (var i = 0; i < p.going.length; i++) p.going[i].style.flex = '0 0 ' + going[i] * (1 - e) + 'px';
    if (p.coming) p.coming.style.flex = '0 0 ' + card1 * e + 'px';
    row.scrollLeft = p.dest.offsetLeft - at(x0, x1, e);
    if (t < 1) { window.requestAnimationFrame(frame); return; }
    if (app) app.classList.remove('strip-moving');
    if (p.coming) {
      p.coming.classList.remove('strip-sized');
      p.coming.style.flex = '';
    }
    STRIP.moving = false;
    if (p.until) heldMoved();
    forkDrawLater();
    if (p.after) p.after();
  }
  frame();
  return true;
}

// What a movement did to the strip, undone, before it is laid out again.
function stripSettle() {
  var row = $('forkRow');
  if (!row) return;
  var sized = row.querySelectorAll('.strip-sized');
  for (var i = 0; i < sized.length; i++) {
    sized[i].classList.remove('strip-sized');
    /** @type {HTMLElement} */ (sized[i]).style.flex = '';
    /** @type {HTMLElement} */ (sized[i]).style.removeProperty('--sized-w');
  }
  stripVar(document.documentElement, '--fork-w', (FORKS.reserve || 0) + 'px');
}

// No answer came: the strip as the page last heard it.
function stripUndo() {
  STRIP.placed = false;
  STRIP.going = '';
  forksPaint();
}

/* The cross in the top right corner of every fork on the strip, the one
   being talked in and each one beside it. Petar, 26 September 2026
   (fr_a3aadda7007c): "the close button for that specific fork should be a
   floating x circle in the top right corner on the fork itself. Currently
   there seems to be X in the title bar, but it is not clear which of the
   chats it will close. So I expect, each of the nested chats has its own
   close button that closes this chat and all its children". It rides on its
   chat as the row slides, so it is never in doubt whose it is. Closing puts
   the person in the chat it came off when they were in it or below it
   (`close_fork` in rouh/runtime.py); the chat where it all started has no
   cross, because it is not a fork. */
function forkX(chat) {
  var name = forkName(chat.id);
  var x = el('button', 'fork-x');
  x.type = 'button';
  x.setAttribute('data-fork', chat.id);
  x.setAttribute('aria-label', 'Close the fork ' + name + ', and every fork from it');
  x.title = 'Close this fork and every fork from it. Each stays marked in the chat it came'
    + ' off, and opens again from there.';
  x.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none"'
    + ' stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  x.addEventListener('click', function (e) {
    // Not a press on the chat under it, which would slide that chat in.
    e.stopPropagation();
    forkClose(chat.id);
  });
  return x;
}

/* Unlink, on a fork's three dots: detach from parent chat.
   Petar, 5 October 2026: a fork that has grown into work of its own should
   be able to stop hanging off the chat it came off and become a chat like
   any other - in the lists, found by search as itself, laid out alone.
   Nothing is copied or deleted (`forks.detach`): the chat keeps every
   message and its own forks, the model still reads what it carried, and
   the chat it came off keeps a mark that opens it. Nobody is moved: the
   person stays where they are and the strip is laid out again without it.

   And never into nowhere. Petar, 6 October 2026 (fr_efa418fa7e82): "when I
   detach a chat I have to pick which task I move it to, or else I am not
   detaching. this is done to prevent loose chats". So the press opens the
   box that picks the task (`detachAsk`), and the fork is detached and filed
   under that task in one step only once one is picked.

   It was a chain-link circle beside each fork's cross until 4 November
   2026, when Petar asked for it on the three dots (fr_ad19bb8be13e). */
$('unlinkChatBtn').addEventListener('click', function () {
  chatMenuShow(false);
  var chat = chatById(CHATS.active);
  if (!chat || !chat.fork_of) return;
  detachAsk(chat);
});

/* The marks: one line in this conversation for each fork it has had, after
   the answer it came off. A mark whose place is further back than what is
   drawn waits there, unseen, like the messages around it. */
var MARKS_DRAWN = '';
function forkMarksDraw() {
  var t = transcriptEl();
  if (!t || !ADDR) return;
  if (t === $('transcript')) MARKS_DRAWN = JSON.stringify(FORKS.marks) + ' ' + forkIds().join(' ');
  var old = t.querySelectorAll('.fork-mark');
  for (var i = 0; i < old.length; i++) old[i].remove();
  if (ADDR.front || !FORKS.marks.length) return;
  // Placed by exchange, which is the order the conversation is drawn in,
  // and not by message number: a question edited after later ones were
  // asked writes its new try with the newest numbers in the chat, in its
  // old place. A message carries the number of the exchange it is part of,
  // which is the number of its question, or, read back from before there
  // were exchanges, its own number, which was its exchange's. A message
  // said on this page has only the first: a chat kept as it was along a
  // strip is never read back (`forkPark`), and a fork is only made from a
  // chat with no answer being written, so an exchange begun at or before
  // the point a fork came off was over before it.
  var turns = t.querySelectorAll('.turn[data-msg], .turn[data-root]');
  for (var k = 0; k < FORKS.marks.length; k++) {
    var mk = FORKS.marks[k], ex = Number(mk.ex || mk.at);
    // A fork of a Synapse chat made before anything was said in it came off
    // nothing (`bare`), and its mark is above the first exchange, once
    // that is drawn.
    if (!ex) {
      var older = $('streamOlder');
      if (older && !older.hidden) continue;
      var first = t.querySelector('.turn');
      if (first) t.insertBefore(forkMark(mk), first);
      else t.appendChild(forkMark(mk));
      continue;
    }
    // The message it came off: the last one drawn in its exchange or
    // before it. None means it came off further back than what is drawn.
    var prev = null;
    for (var j = 0; j < turns.length; j++) {
      var n = Number(turns[j].getAttribute('data-root') || turns[j].getAttribute('data-msg'));
      if (n && n <= ex) prev = turns[j];
    }
    if (!prev) continue;
    // Under it and under whatever belongs to it - its cards, the marks
    // before this one - and above whatever was said next, read back or
    // said just now, which has no number on the page yet.
    var next = prev.nextElementSibling;
    while (next && !next.classList.contains('turn') && next !== T.typing) {
      next = next.nextElementSibling;
    }
    var line = forkMark(mk);
    if (next) t.insertBefore(line, next);
    else t.appendChild(line);
  }
}

/* One mark: a short line saying it is a fork, and under it the whole of
   what was asked in it. Petar, 26 September 2026 (fr_a3aadda7007c): "I
   would like to see the full original message, not just the first few
   words of a summary" - the fork's title, which is the model's summary of
   it. The message it came off is the one just above; the mark is what
   split from it, and the whole mark is the press that opens the fork.

   A fork that became a task is cut from this chat (`forks.cut`,
   fr_3702d01d197d): it is that task's own chat now, so its mark names the
   task and opens it, with its page, rather than laying the chat out beside
   this one. */
function forkMark(mk) {
  if (mk.task) return taskMark(mk);
  if (mk.detached) return detachedMark(mk);
  // On the right is this tab's strip, which is the only strip there is.
  var open = forkIds().indexOf(mk.id) >= 0;
  var line = el('div', 'fork-mark' + (open ? ' is-open' : ''));
  line.setAttribute('data-fork', mk.id);
  // A link to the fork's own address, so it opens in a tab of its own too.
  var go = linkTo(el('a', 'fork-mark-go'), addrOf('chat', mk.id));
  var head = el('span', 'fork-mark-head');
  head.appendChild(forkIcon(14));
  // The branch and the fork's own title, whole. Petar, 29 October 2026
  // (fr_b4f079029d4a): "keep the sign of fork but then have the title of the
  // chat instead of the word FORK". A fork whose title is not written yet
  // says Fork until it is, and a renamed one its new name: the marks come
  // again with every change to a chat, and are drawn again when they differ.
  var titled = !!mk.titled && !!String(mk.title || '').trim();
  var title = titled ? String(mk.title).trim() : 'New chat';
  head.appendChild(el('span', 'fork-mark-word' + (titled ? ' is-named' : ''), titled ? title : 'Fork'));
  var n = Number(mk.messages) || 0;
  head.appendChild(el('span', 'fork-mark-count', n + (n === 1 ? ' message' : ' messages')));
  head.appendChild(el('span', 'fork-mark-state', open ? 'On the right' : 'Open it'));
  go.appendChild(head);
  // A fork opened with a file and no words has only its title to say, which
  // the head says already once there is one.
  var asked = String(mk.asked || '').trim();
  if (asked || !titled) {
    go.appendChild(el('span', 'fork-mark-asked' + (asked ? '' : ' is-title'), asked || title));
  }
  go.title = (open ? 'Go to this fork, open on the right' : 'Open this fork again, on the right of this chat')
    + ': ' + title;
  go.addEventListener('click', function () {
    if (forkAt(mk.id) >= 0) { stripTo(mk.id); return; }
    forkComeNow({ mark: mk });
    openChat(mk.id);
  });
  line.appendChild(go);
  return line;
}

/* A fork that was detached (Unlink, `detachAsk`): it is a chat of its own now, and
   its mark says so and opens it as one, on its own. */
function detachedMark(mk) {
  var line = el('div', 'fork-mark is-detached');
  line.setAttribute('data-fork', mk.id);
  var go = linkTo(el('a', 'fork-mark-go'), addrOf('chat', mk.id));
  var head = el('span', 'fork-mark-head');
  head.appendChild(forkIcon(14));
  head.appendChild(el('span', 'fork-mark-word', 'Detached'));
  var n = Number(mk.messages) || 0;
  head.appendChild(el('span', 'fork-mark-count', n + (n === 1 ? ' message' : ' messages')));
  head.appendChild(el('span', 'fork-mark-state', 'Open the chat'));
  go.appendChild(head);
  var asked = String(mk.asked || '').trim();
  var title = mk.title || 'New chat';
  go.appendChild(el('span', 'fork-mark-asked' + (asked ? '' : ' is-title'), asked || title));
  go.title = 'Forked from here and detached: a chat of its own now. Press to open it: ' + title;
  go.addEventListener('click', function () { openChat(mk.id); });
  line.appendChild(go);
  return line;
}

function taskMark(mk) {
  var task = mk.task;
  var line = el('div', 'fork-mark is-task');
  line.setAttribute('data-fork', mk.id);
  var go = linkTo(el('a', 'fork-mark-go'), task.folder ? addrOf('task', task.folder) : '');
  // The rail in the colour of the task's project: a name of the palette or a hex.
  var cc = String(task.color || '');
  if (cc) go.style.setProperty('--cc', /^#[0-9a-f]{6}$/i.test(cc) ? cc : 'var(--cat-' + cc + ')');
  var head = el('span', 'fork-mark-head');
  // The task's own icon, an emoji or a small picture (`rouh/taskicons.py`).
  if (task.img || task.icon) {
    var mark = el('span', 'fork-mark-icon');
    mark.setAttribute('aria-hidden', 'true');
    if (task.img) {
      var img = /** @type {HTMLImageElement} */ (el('img'));
      img.src = task.img;
      img.alt = '';
      mark.appendChild(img);
    } else {
      mark.textContent = task.icon;
    }
    head.appendChild(mark);
  }
  if (task.number != null) head.appendChild(el('span', 'fork-mark-num', String(task.number)));
  var named = task.name || (task.number != null ? 'Task ' + task.number : 'Task');
  head.appendChild(el('span', 'fork-mark-word', named));
  head.appendChild(el('span', 'fork-mark-state', 'Open the task'));
  go.appendChild(head);
  var asked = String(mk.asked || '').trim();
  go.appendChild(el('span', 'fork-mark-asked' + (asked ? '' : ' is-title'),
    asked || task.name || mk.title || 'New chat'));
  go.title = 'Started ' + taskWords({ number: task.number, label: named })
    + ' from here. Press to open it.';
  go.addEventListener('click', function () { openTaskThread(task); });
  line.appendChild(go);
  return line;
}

/* Fork, beside Send. Drawn in a chat that has something in it to fork, or
   in a Synapse chat with nothing said in it yet, whose fork still carries
   the dataset it is made over (`bare`, fr_c933c22b9bef), and pressable once something is typed or attached - the same things Send
   needs - and not while an answer is being written, when Send is not
   either. */
function forkBtnPaint() {
  var b = $('forkBtn');
  // Asked from the transcript's own drawing, which can run before the
  // sections that hold the chats and the address have.
  if (!b || !CHATS || !ADDR) return;
  var chat = chatById(CHATS.active);
  var t = transcriptEl();
  var can = !ADDR.front && !!chat && !chat.draft
    && (FORKS.bare || !!(t && t.querySelector('.turn')));
  b.hidden = !can;
  var typed = !!(input && input.value.trim()) || (shared.attached && shared.attached.length > 0);
  b.disabled = !typed || !!S.busy;
  // The same two buttons on every message being edited, by the same rule:
  // Fork where there is something above the message to fork from, and
  // pressable once there are words in the box; neither while an answer is
  // being written, when the main box's Send is not either.
  var open = t ? t.querySelectorAll('.turn.editing') : [];
  for (var i = 0; i < open.length; i++) {
    var turn = open[i];
    if (!turn.__editFork) continue;
    var above = turn.previousElementSibling;
    while (above && !above.classList.contains('turn')) above = above.previousElementSibling;
    turn.__editFork.hidden = !can || (!above && !FORKS.bare);
    turn.__editFork.disabled = !turn.__editing.value.trim() || !!S.busy;
    turn.__editSend.disabled = !!S.busy;
  }
}

function onMac() {
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
}

// What Ctrl+Shift+Enter is called on this keyboard, for Fork's tooltip on
// the main box and on a message being edited.
function forkKeys() {
  return onMac() ? '⌘⇧↩' : 'Ctrl+Shift+Enter';
}

/* Enter is a new line in every box a message is written in, and Ctrl+Enter,
   or Cmd+Enter on a Mac, sends it. Petar, 26 September 2026
   (fr_06ec274f0b97): "Can you make the keyboard button make a new line
   instead of submitting the chat message?" Until then Enter sent and only
   Shift+Enter made a new line, so a message of more than one line had to be
   written with a finger on Shift. A phone's return key is a new line as
   well, and its arrow sends. A composition in progress (an IME choosing a
   character) owns the key and keeps it. */
function isSendKey(e) {
  return e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey
    && !e.isComposing;
}

// What that is called on this keyboard, for Send's tooltip.
function sendKeys() {
  return onMac() ? '⌘↩' : 'Ctrl+Enter';
}

// An empty box says how to send what is written in it, where there is a
// keyboard to send it from. On a phone the arrow beside the box is the only
// way, and the words stay as they are. `shorter` is what to say instead of
// `words` when the keys would take them past one line.
function withSendKeys(words, shorter) {
  return window.matchMedia && window.matchMedia('(pointer: fine)').matches
    ? (shorter || words) + ' (' + sendKeys() + ' to send)' : words;
}

(function () {
  var b = $('forkBtn');
  if (!b) return;
  b.title = 'Fork: ask this in a side chat to the right, and keep this chat where it is ('
    + forkKeys() + ')';
  b.addEventListener('click', function () { sendTyped(true); });
}());

// The fork this tab asked for is open: what was typed is drawn in it, the
// same way a message typed into any chat is drawn by the tab that typed it.
function forkTypedArrived(chat) {
  var typed = FORKS.typed;
  if (!typed || !chat || chat.fork_of !== typed.from) return;
  FORKS.typed = null;
  drawTyped(typed.text, typed.files);
}

// Crossing 900 pixels changes how the strip is drawn - a desk's strips
// either side, or a phone's row of whole chats - so it is laid out again.
(function () {
  if (!window.matchMedia) return;
  var mq = window.matchMedia('(max-width: 899px)');
  var again = function () { forksPaint(); };
  if (mq.addEventListener) mq.addEventListener('change', again);
  else if (mq.addListener) mq.addListener(again);
}());

/* The three chips at the head of a conversation go somewhere, so each is a
   link to where it goes (`linkTo`): the chat a fork came off, the task a
   subtask is part of, and the task or the project the chat is in. A press
   opens that beside this conversation, so the address names this one beside
   it, the way the bar does once it is open (`addrNow`); a task's own chat
   is that task's address already. On Rouh's own chat the project chip opens
   Search, which is somewhere to look rather than somewhere to go, and it is
   a button there. */
function crumbBeside(path) {
  return CHATS.active ? path + '?chat=' + encodeURIComponent(CHATS.active) : path;
}

if ($('crumbFork')) {
  linkTo($('crumbFork'), function () {
    var chat = chatById(CHATS.active);
    return chat && chat.fork_of ? addrOf('chat', chat.fork_of) : '';
  });
}
linkTo($('crumbParent'), function () {
  var up = PARENT.up;
  return up && up.folder ? crumbBeside(addrOf('task', up.folder)) : '';
});
linkTo($('crumbProject'), function () {
  var chat = chatById(CHATS.active);
  if (!chat) return '';
  if (chat.owned_by && chat.owned_by.type === 'task') {
    if (!chat.task) return '';
    return addrIsTasksOwn(chat) ? addrOf('task', chat.task) : crumbBeside(addrOf('task', chat.task));
  }
  var project = chat.folder_id ? projectById(chat.folder_id) : null;
  return project && project.folder ? crumbBeside(addrOf('project', project.folder)) : '';
});

if ($('crumbFork')) {
  // The strip slides back on the press, the way pressing the chat beside
  // does (`stripTo`), rather than standing still until the server has
  // answered and then jumping. Petar, 21 October 2026 (fr_2c7e491ab5a6):
  // "on click it should basically slide to the parent but without the
  // delay we have now".
  $('crumbFork').addEventListener('click', function () {
    var chat = chatById(CHATS.active);
    if (!chat || !chat.fork_of) return;
    stripTo(chat.fork_of);
  });
}

/** @param {import('./protocol').FromServer<'fork_refused'>} m */
function forkRefused(m) {
  FORKS.typed = null;
  setBusy(false);
  setState('listening');
  // Fork on a message being edited: the words go back into that box.
  var t = transcriptEl();
  var edited = m.root && t ? t.querySelector('.turn.user[data-root="' + Number(m.root) + '"]') : null;
  if (edited) {
    editTurn(edited, m.text || '');
  } else if (input && !input.value.trim() && m.text) {
    input.value = m.text;
    growInput();
  }
  forkBtnPaint();
  // A desk's strip put up for it on the press (`forkStripComing`) goes.
  if (document.querySelector('.fork-strip.is-coming')) forksPaint();
  notify(m.why || 'That could not be forked.', { tone: 'error' });
}

/* The chevron on the chat's name, and what is behind it.
 *
 * What used to be along the head of this column - the way to every chat, and
 * renaming this one - is here, because a thing you do to what you are
 * looking at belongs on what you are looking at. Starting a new chat is not
 * one of them: that is navigation, and it is at the top of the sidebar with
 * the rest of it.
 */
//
// It is the one menu every three dots on this page open (`menu.js`): it
// closes on the next press anywhere else, on Escape and on choosing an
// item, which is what every menu does and what a person expects without
// being told, and the arrow keys walk it.
var chatMenuShow = RouhMenu.bind($('chatMenuBtn'), $('chatMenu'));

$('crumbProject').addEventListener('click', function () {
  var chat = chatById(CHATS.active);
  // A chat that belongs to a task opens that task's own page, beside the
  // chat: the way back from the conversation to what it is about, which is
  // the other half of the chat button on that page. It opened a dialog
  // listing what was under the task until 23 September 2026, which was not
  // the task and had no way on to it.
  if (chat && chat.owned_by && chat.owned_by.type === 'task') {
    taskFromChat(chat);
    return;
  }
  // A project of the workspace has a page, which is everything in it. The
  // chip showed the chats list, opened at the project, until 30 September
  // 2026, when that list went; the latest chats are in Search now.
  var project = chat && chat.folder_id ? projectById(chat.folder_id) : null;
  if (project && project.folder) { canvasTask(project.folder); return; }
  findShow(true);
});

$('crumbParent').addEventListener('click', parentOpen);
$('crumbToParent').addEventListener('click', parentNoteOpen);
$('toParentBtn').addEventListener('click', function () {
  chatMenuShow(false);
  parentNoteOpen();
});
$('parentNoteCancel').addEventListener('click', function () {
  $('parentNoteDialog').close();
});
$('parentNoteForm').addEventListener('submit', function (e) {
  e.preventDefault();
  parentNoteSend();
});
// Ctrl or Cmd with Enter sends, as a box that takes several lines does.
$('parentNoteText').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    parentNoteSend();
  }
});

// The task's page, from its chat. Already on the canvas at a desk, there is
// nothing to load and nothing is reloaded: the page stays where it was
// scrolled to. A phone shows one pane at a time, so there it is the pane.
function taskFromChat(chat) {
  var rel = chat.task || '';
  if (!rel) {
    openUnder('task', chat.owned_by.id, ownerWords(chat.owned_by));
    return;
  }
  var there = tasksViewing() && !CANVAS.step
    && String(CANVAS.at || '').split('?')[0] === taskUrl(rel);
  if (!there) canvasTask(rel);
  // Opening a page folds the conversation away when the tasks have the
  // window; this was pressed from inside the conversation, which stays.
  chatIsWanted();
  if (narrow()) setPane('canvas');
  sidebarDone();
}

$('renameChatBtn').addEventListener('click', function () {
  chatMenuShow(false);
  var chat = chatById(CHATS.active);
  if (!chat) return;
  var said = window.prompt('What should this chat be called?', chat.title);
  if (said == null) return;
  send({ type: 'rename_chat', id: chat.id, title: said });
});

/* "This one is work."
 *
 * The chat takes the next task number, keeps every message - it is the same
 * conversation, nothing is copied - and a folder for it is written into the
 * workspace from the row. It is asked for here, about the chat the person is
 * in, because that is the moment they know: they have been talking about
 * something and it turns out to be a piece of work. */
$('promoteChatBtn').addEventListener('click', function () {
  chatMenuShow(false);
  var chat = chatById(CHATS.active);
  if (!chat || chat.task) return;
  send({ type: 'promote_thread', id: chat.id });
});

$('pinChatBtn').addEventListener('click', function () {
  chatMenuShow(false);
  var chat = chatById(CHATS.active);
  if (!chat) return;
  send({ type: 'pin_thread', id: chat.id, on: !chat.pinned });
});

/* Delete, from inside the chat. Petar, 24 September 2026: "The three-dot
   menu does not have Delete on a chat, and it should have Delete."

   The one delete dialog, as from the chat's row in the sidebar: it names
   the chat, the server counts what else goes with it, and nothing is
   deleted until its button is pressed (`askDelete`). Deleting the chat you
   are in leaves you in General, on every tab and at General's own address,
   because the server moves every tab whose chat has gone there
   (`delete_object` in runtime.py), rather than on a page for a chat that is
   not there any more. */
$('deleteChatBtn').addEventListener('click', function () {
  chatMenuShow(false);
  var chat = chatById(CHATS.active);
  if (!chat || chat.id === CHATS.general) return;
  askDelete('chat', chat.id, threadName(chat));
});

export { applyChats, chatById, chatIsTask, chatMenuShow, CHATS, chatShow, forkBehind, forkBtnPaint, forkTip,
  forkComeNow, forkHold, forkKeptStale, forkPeeked, forkKeys, forkMarksDraw, forkPark, forkRefused, forkReplay,
  forkResume, FORKS, forkWithin, isSendKey, onChatSwitched, onNoteSent, openChat, sendKeys,
  showCrumb, withSendKeys };
