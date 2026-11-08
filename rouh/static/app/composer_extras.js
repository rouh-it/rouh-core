/* The voice button and the model, on the composer's line (Petar, 8 November 2026).
 *
 * "I am doing heavy and difficult work and I don't want cheap model to answer me. so I want
 * to redesign this experience. 1. the 3 icons for the voice should be under one icon with a
 * speaking person to save space. then remove the + sign from there. also add a new control -
 * model Cheap, Smart, Auto. and I wonder if that should be saved in the settings of the chat.
 * so I have freedom to do whatever I want. and whatever is on rouh, will be the default for
 * any new chat, unless changed later."
 *
 * The voice: the microphone, voice replies and dictation are the very buttons they were, wired
 * where they always were (app/controls.js), moved into a panel the speaking person opens. This
 * only opens and closes the panel and copies their state onto the button, so the line still says
 * whether the microphone is live, dictation is on or the speaker is waiting for a press.
 *
 * The model: Cheap, Smart or Auto for the chat on screen, read from the server and kept there
 * (the socket's `chat_model`, `chatkinds.choice_of`), never in this browser, so a reload, a restart and
 * another device all see the same. A chat nobody set follows the Models page.
 *
 * Both panels close on Escape (before Escape stops a turn), on a press anywhere else, and on
 * their button again. Outside the chain, like app/focus.js: imported by app.js once the chain
 * has run.
 */
import { CHATS } from 'app/chats.js';
import { $, el } from 'app/helpers.js';
import { notify } from 'app/notices.js';
import { send } from 'app/socket.js';

/** @typedef {{ id: string, name: string, hint: string, model: string, model_name: string }} ModelOption */
/** @typedef {{ chat: string, choice: string, own: boolean, default: string, chooses: boolean,
 *              mode: string, options: ModelOption[] }} ModelChoice */

var NAMES = /** @type {Record<string, string>} */ ({ cheap: 'Cheap', smart: 'Smart', auto: 'Auto' });
var MODES = /** @type {Record<string, string>} */ ({ best: 'Best', balanced: 'Balanced', saver: 'Saver' });

var voiceBtn = /** @type {HTMLButtonElement | null} */ ($('voiceMenuBtn'));
var voicePop = $('voicePop');
var modelBtn = /** @type {HTMLButtonElement | null} */ ($('modelBtn'));
var modelPop = $('modelPop');
var modelWord = $('modelWord');
var modelOpts = $('modelOpts');
var modelFoot = $('modelFoot');

/* --------------------------------------------------------------- the panels */

/** @param {HTMLButtonElement | null} btn @param {HTMLElement | null} pop @param {boolean} on */
function showPop(btn, pop, on) {
  if (!btn || !pop) return;
  pop.hidden = !on;
  btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (on) keepInside(pop);
}

/** A panel opens from its button's left edge and is moved back in if it would leave the window:
    the button sits anywhere on the line, from the left of a desk's wide box to the middle of a
    phone's. @param {HTMLElement} pop */
function keepInside(pop) {
  pop.style.left = '';
  var r = pop.getBoundingClientRect();
  var room = document.documentElement.clientWidth - 8;
  var shift = r.right > room ? room - r.right : 0;
  if (r.left + shift < 8) shift = 8 - r.left;
  if (shift) pop.style.left = shift + 'px';
}

function closeAll() {
  showPop(voiceBtn, voicePop, false);
  showPop(modelBtn, modelPop, false);
}

function anyOpen() {
  return !!((voicePop && !voicePop.hidden) || (modelPop && !modelPop.hidden));
}

if (voiceBtn && voicePop) {
  voiceBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    var on = voicePop.hidden;
    closeAll();
    showPop(voiceBtn, voicePop, on);
    if (on) {
      var first = /** @type {HTMLElement | null} */ (voicePop.querySelector('button:not(:disabled)'));
      if (first && e.detail === 0) first.focus();
    }
  });
}
if (modelBtn && modelPop) {
  modelBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    var on = modelPop.hidden;
    closeAll();
    showPop(modelBtn, modelPop, on);
    if (on) {
      var picked = /** @type {HTMLElement | null} */ (modelPop.querySelector('[aria-checked="true"]'));
      if (picked && e.detail === 0) picked.focus();
    }
  });
}

// A press anywhere outside an open panel and its button closes it. A press inside it does not:
// the voice controls stay on screen with their new state, and the model panel closes itself
// once a choice is made.
document.addEventListener('pointerdown', function (e) {
  if (!anyOpen()) return;
  var t = /** @type {Node} */ (e.target);
  var wraps = [$('voiceWrap'), $('modelWrap')];
  for (var i = 0; i < wraps.length; i++) if (wraps[i] && wraps[i].contains(t)) return;
  closeAll();
}, true);

// Escape closes the panel first, and only the press after it stops a turn (app/cards.js).
window.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || !anyOpen()) return;
  var back = modelPop && !modelPop.hidden ? modelBtn : voiceBtn;
  e.preventDefault();
  e.stopPropagation();
  closeAll();
  if (back && document.activeElement && (voicePop && voicePop.contains(document.activeElement)
      || modelPop && modelPop.contains(document.activeElement))) back.focus();
}, true);

/* ------------------------------------------------- the voice button's state */

function voiceSays() {
  if (!voiceBtn) return;
  var mic = $('micBtn'), reply = $('voiceBtn'), dict = $('dictateBtn');
  var live = !!mic && !mic.disabled && !mic.classList.contains('off');
  var press = !!mic && mic.classList.contains('needs-press');
  var dictating = !!dict && dict.getAttribute('aria-pressed') === 'true';
  var repliesOff = !!reply && reply.getAttribute('aria-pressed') === 'false';
  voiceBtn.classList.toggle('mic-live', live);
  voiceBtn.classList.toggle('needs-press', press);
  voiceBtn.classList.toggle('dictating', dictating);
  voiceBtn.classList.toggle('replies-off', repliesOff);
  var words = 'Voice: ' + (press ? 'press to turn the voice on' : live ? 'microphone on' : 'microphone off')
    + ', voice replies ' + (repliesOff ? 'off' : 'on') + (dictating ? ', dictating' : '');
  voiceBtn.title = words;
  voiceBtn.setAttribute('aria-label', words);
}

if (voiceBtn) {
  var watch = new MutationObserver(voiceSays);
  ['micBtn', 'voiceBtn', 'dictateBtn'].forEach(function (id) {
    var b = $(id);
    if (b) watch.observe(b, { attributes: true, attributeFilter: ['class', 'aria-pressed', 'disabled'] });
  });
  voiceSays();
}

/* ------------------------------------------------------------- the model */

var MODEL = { chat: '', data: /** @type {ModelChoice | null} */ (null),
              before: /** @type {ModelChoice | null} */ (null) };

function currentChat() {
  return String((CHATS && CHATS.active) || '');
}

/** What Auto answers with: the two models it picks between. @param {ModelChoice} d */
function autoWords(d) {
  var by = /** @type {Record<string, string>} */ ({});
  d.options.forEach(function (o) { by[o.id] = o.model_name; });
  return by.cheap && by.smart ? by.cheap + ' or ' + by.smart : '';
}

/** @param {ModelChoice | null} d */
function draw(d) {
  if (!modelBtn || !modelWord || !modelOpts || !modelFoot) return;
  if (!d) {
    modelWord.textContent = 'Model';
    modelBtn.classList.add('follows');
    return;
  }
  var name = NAMES[d.choice] || 'Custom';
  modelWord.textContent = name;
  modelBtn.classList.toggle('follows', !d.own);
  modelBtn.disabled = !d.chooses;
  var says = d.chooses
    ? 'Model for this chat: ' + name + (d.own ? '' : ', the default from the Models page')
    : 'This chat answers on what it is for, set on the Models page';
  modelBtn.title = says;
  modelBtn.setAttribute('aria-label', says);
  modelOpts.textContent = '';
  d.options.forEach(function (o) {
    var b = el('button', 'model-opt');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', o.id === d.choice ? 'true' : 'false');
    b.dataset.choice = o.id;
    b.tabIndex = o.id === d.choice ? 0 : -1;
    b.appendChild(el('span', 'model-opt-mark'));
    var top = el('span', 'model-opt-name', o.name);
    var which = o.id === 'auto' ? autoWords(d) : o.model_name;
    if (which) top.appendChild(el('span', 'model-opt-model', which));
    b.appendChild(top);
    b.appendChild(el('span', 'model-opt-hint', o.hint));
    b.addEventListener('click', function () { pick(o.id); });
    modelOpts.appendChild(b);
  });
  modelFoot.textContent = '';
  var dflt = NAMES[d.default] || 'its own model';
  if (d.own) {
    modelFoot.appendChild(el('span', '', 'New chats start on ' + dflt + ', from the Models page (' + (MODES[d.mode] || d.mode) + ').'));
    var reset = el('button', 'model-reset', 'Follow the Models page');
    reset.type = 'button';
    reset.addEventListener('click', function () { pick(''); });
    modelFoot.appendChild(reset);
  } else {
    modelFoot.appendChild(el('span', '', 'This chat follows the Models page (' + (MODES[d.mode] || d.mode) + ' is ' + dflt + '). Picking one keeps it for this chat only.'));
  }
}

// Arrow keys move between the three, as a group of radio buttons does.
if (modelOpts) {
  modelOpts.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    var all = Array.prototype.slice.call(modelOpts.querySelectorAll('.model-opt'));
    var at = all.indexOf(document.activeElement);
    if (at < 0) return;
    e.preventDefault();
    var next = all[(at + (e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
    next.focus();
  });
}

/** Ask the server what this chat is on. Over the socket, like the choice itself: a tab's messages
    are handled in order, so a choice made and a message sent straight after it are kept in that
    order. False while the socket is down; the next look asks again. @param {string} chat */
function load(chat) {
  if (!modelBtn) return;
  if (!chat) { MODEL.chat = ''; MODEL.data = null; draw(null); return; }
  if (send({ type: 'chat_model', chat: chat })) MODEL.chat = chat;
}

/** @param {string} choice "" to follow the Models page again */
function pick(choice) {
  var chat = MODEL.chat || currentChat();
  if (!chat) return;
  showPop(modelBtn, modelPop, false);
  if (modelBtn) modelBtn.focus();
  if (!send({ type: 'chat_model', chat: chat, choice: choice })) {
    notify('The model for this chat could not be set: Rouh is not connected. Try again in a moment.', { tone: 'error' });
    return;
  }
  // Shown at once; the server's answer follows, and puts it back with the reason if it was not kept.
  var before = MODEL.data;
  MODEL.before = before;
  if (before) {
    var shown = /** @type {ModelChoice} */ (Object.assign({}, before, { choice: choice || before.default, own: !!choice }));
    MODEL.data = shown;
    draw(shown);
  }
}

/** What the server says a chat is on: an answer to this tab, or a choice made on another of the
    person's tabs. `detail` null is the Models page changing: ask again. @param {Event} e */
function heard(e) {
  var d = /** @type {CustomEvent} */ (e).detail;
  if (!d) { MODEL.chat = ''; return; }
  if (d.error) {
    if (d.chat === MODEL.chat && MODEL.before) { MODEL.data = MODEL.before; draw(MODEL.before); }
    notify(d.error, { tone: 'error' });
  }
  MODEL.before = null;
  if (d.chat !== currentChat() || !d.options) return;
  MODEL.data = d;
  draw(d);
}

// The chat on screen changes in many places (a click in the list, a fork, the address, a new
// chat): its id is looked at a few times a second, which is a comparison and nothing more, and
// the server is asked only when it changed, after the socket came back, and when the page
// comes back into view. A choice made on another device arrives by itself (`chat_model`).
if (modelBtn) {
  draw(null);
  window.addEventListener('rouh:chat-model', heard);
  setInterval(function () {
    var chat = currentChat();
    if (chat !== MODEL.chat) load(chat);
  }, 400);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) MODEL.chat = ''; });
}

export { closeAll as composerPopsClose };
