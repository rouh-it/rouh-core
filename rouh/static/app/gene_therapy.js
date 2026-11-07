/* Rouh's page, Gene therapy: the drawer on the right, and the board it opens (section 12 of what was one app.js).
 *
 * Imports app/attachments.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { ATT_BLOCKED, ATT_MAX, ATT_SHOWABLE, attExt, attRetryButton, attSize, attTookIn, dragHasFiles, droppedFiles,
  dropTypes, openImage, takeInFile } from 'app/attachments.js';
import { $, el, now, safeParse } from 'app/helpers.js';
import { cfg, load } from 'app/settings.js';
import { S } from 'app/socket.js';
import { A, debug, MIC, openThreshold } from 'app/voice.js';
import { PB, pbLevel, SPK } from 'app/playback.js';
import { applyTree, haveTree, KEY_ORB, memColour, orb, ORB_BASE, ORB_CFG, ORB_HIT, ORB_ROWS,
  ORB_SOUND, orbFrameNo, orbMoved, orbPanelOpen, orbPointAt, orbRaf, orbStats, orbUnsent, orbW,
  ORDER, SCENE, SELF, setState } from 'app/orb.js';
import { stillSpeaking, turnIsRunning } from 'app/transcript.js';
import { CARDS, layerOpen, loadOlderCards, renderCard, showLayer, streamEl, WORKSPACE_ROUTE } from 'app/cards.js';
import { applyTaskList, since, taskRecs, upsertTask } from 'app/tasks.js';
import { oneOpen, POLICY_MEANS, projectsClose, tasksFrame, whenWords } from 'app/runs.js';
import { CHATS } from 'app/chats.js';
import { bootWaiting } from 'app/address.js';
import { accountMenu, cols, SB, sidebarDone } from 'app/controls.js';

/* ------------------------------------------------------------------ 12 */
/* Gene therapy: the drawer on the right, and the board it opens.
 *
 * It was Feedback until 12 October 2026, when Petar renamed it: "Can we also
 * change the name of the feedback function to be called gene therapy with a
 * gene emoji and rename all the code files ... Also make it playful, how would
 * you like to mutate me?" What it keeps did not change name: a feedback and a
 * feature request, in the same tables, at `/api/gene-therapy` (and still at
 * `/api/feedback`). The frame messages a workspace page sends a report with
 * keep theirs too, `rouh-page-feedback` and `rouh-frame-feedback`, because
 * pages already written send them.
 *
 * Two screens and two things behind them, and the whole design is in that:
 *
 *   a feedback       what somebody said, never rewritten into anything else
 *   a feature request what is going to be done about it, with its own type,
 *                    its own status, and a run that can be started for it
 *
 * The drawer is the fourth column of the app's grid, so opening it pushes
 * the conversation and the canvas in rather than lying over them: whatever
 * the person is writing about is still on the screen beside what they are
 * writing. All of that is in app.css - this only sets `data-gt` on the app
 * element and the stylesheet does the rest.
 *
 * Files are uploaded the moment they are attached, into a folder of their
 * own, through the same `/attachments/{session}` route the composer uses
 * (rouh/attachments.py). Sending is what binds those ids to the row, so a
 * screenshot that is still going up never delays the sentence it came with:
 * Send waits for it instead.
 */

var GT = {
  //: The drawer.
  open: false,
  //: The board, over the conversation and the canvas.
  board: false,
  //: Which one is being read in full: {kind: 'feedback'|'request', id: '...'}.
  view: null,
  //: The last thing the board was told, so a redraw needs no request.
  data: null,
  //: Which status each column is filtered to. Empty is all of them. Kept
  //: only while the board is open: a filter is a way of looking, not a
  //: setting to remember.
  filter: { feedback: '', requests: '' },
  //: What is typed in the search box, narrowing both columns at once.
  find: '',
  //: The timer that retracts the drawer two seconds after Thank you.
  thanks: 0,
  //: Told the feedback once a report handed over by Rouh's own page is sent (`gtHandOver`).
  onSent: null,
  loading: false
};

//: How long Thank you stays before the drawer goes back off to the right,
//: with or without the line under it saying what is happening to what they
//: just wrote. It was three seconds, and five with that line, until Petar
//: asked for two on 4 October 2026 (fr_fc7eb1ce2033); Submit another one is
//: on the same screen for whoever wants to stay.
var GT_THANKS_MS = 2000;

//: What each status is called on the screen. The words the database keeps
//: are short and lower case; these are what a person reads.
var GT_STATUS_WORDS = {
  new: 'New', triaged: 'Triaged', planned: 'Planned', done: 'Done',
  declined: 'Declined', proposed: 'Proposed', building: 'Building',
  shipped: 'Shipped', failed: 'Failed'
};
var GT_KIND_WORDS = {
  feature: 'Feature', bug: 'Bug', improvement: 'Improvement', question: 'Question'
};

function gtWords(map, key) {
  return map[key] || (String(key || '').charAt(0).toUpperCase() + String(key || '').slice(1));
}

function gtFetch(url, opts) {
  opts = opts || {};
  opts.credentials = 'same-origin';
  if (opts.body && typeof opts.body !== 'string') {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(opts.body);
  }
  return fetch(url, opts).then(function (r) {
    if (r.status === 401) { location.href = '/login'; throw new Error('Sign in again.'); }
    return r.text().then(function (text) {
      var body = safeParse(text) || {};
      if (!r.ok) throw new Error(body.error || ('That came back ' + r.status + '.'));
      return body;
    });
  });
}

/* ---------- files, wherever they are attached ----------

   The drawer has a set of these, and so does the form that turns a feedback
   into a feature request, so it is a small thing made twice rather than one
   thing with two owners. Each set uploads into a folder of its own, which is
   minted here and not by the server: the folder is half of a file's address,
   so a set that has not uploaded anything costs nothing and two sets can
   never collide. */

function gtNewSession() {
  return 'fb-' + Date.now().toString(36) + '-' +
         Math.random().toString(36).slice(2, 10);
}

function gtFiles(node) {
  var list = [], seq = 0, session = gtNewSession(), onSettled = null;

  function draw() {
    if (!node) return;
    node.textContent = '';
    node.hidden = list.length === 0;
    list.forEach(function (a) {
      var chip = el('div', 'att' + (a.status === 'uploading' ? ' is-uploading' :
                                    a.status === 'failed' ? ' is-failed' : ''));
      chip.appendChild(gtThumb(a));
      var text = el('div', 'att-text');
      var name = el('div', 'att-name', a.name);
      name.title = a.name;
      text.appendChild(name);
      if (a.status === 'failed') text.appendChild(el('div', 'att-err', a.error));
      else if (a.note) text.appendChild(el('div', 'att-err', a.note));
      else if (a.reading) text.appendChild(el('div', 'att-size', 'Reading it…'));
      else if (a.status === 'uploading') {
        text.appendChild(el('div', 'att-size',
          Math.round(a.pct * 100) + '% of ' + attSize(a.size)));
      } else text.appendChild(el('div', 'att-size', attSize(a.size)));
      chip.appendChild(text);
      if (a.status === 'failed' && a.retry) chip.appendChild(attRetryButton(a, retry));
      var x = el('button', 'att-x', '×');
      x.type = 'button';
      x.title = 'Remove ' + a.name;
      x.setAttribute('aria-label', 'Remove ' + a.name);
      x.addEventListener('click', function () { remove(a.key); });
      chip.appendChild(x);
      if (a.status === 'uploading') {
        var bar = el('div', 'att-bar');
        bar.style.width = Math.round(a.pct * 100) + '%';
        chip.appendChild(bar);
        a.bar = bar;
      }
      node.appendChild(chip);
    });
  }

  // Retry: the same file again, from where it failed (`attRetry` says why).
  function retry(a) {
    var go = a.retry;
    if (!go || list.indexOf(a) < 0) return;
    a.retry = null;
    a.status = 'uploading';
    a.error = '';
    a.pct = 0;
    go();
    draw();
  }

  function remove(key) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].key !== key) continue;
      if (list[i].xhr) { try { list[i].xhr.abort(); } catch (e) {} }
      if (list[i].thumb) { try { URL.revokeObjectURL(list[i].thumb); } catch (e) {} }
      list.splice(i, 1);
      break;
    }
    draw();
  }

  function add(files) {
    if (!files || !files.length) return;
    for (var i = 0; i < files.length; i++) queue(files[i]);
    draw();
  }

  function queue(file) {
    var a = {
      key: 'f' + (++seq), name: file.name || 'file', size: file.size || 0,
      status: 'uploading', pct: 0, id: null, media_type: '', kind: '',
      thumb: null, error: '', xhr: null
    };
    list.push(a);
    var ext = attExt(a.name);
    if (ATT_BLOCKED[ext]) {
      a.status = 'failed';
      a.error = ext + ' files cannot be attached, because that is a program ' +
        'rather than a document.';
      return;
    }
    if (a.size > ATT_MAX) {
      a.status = 'failed';
      a.error = a.name + ' is ' + attSize(a.size) + ', and the limit is ' +
        attSize(ATT_MAX) + ' per file.';
      return;
    }
    readThenSend(a, file);
  }

  function readThenSend(a, file) {
    // Read now, the way the conversation's own files are (`takeInFile`).
    a.reading = true;
    takeInFile(file).then(function (got) {
      a.reading = false;
      if (list.indexOf(a) < 0) return;
      if (got.error) {
        a.status = 'failed';
        a.error = got.error;
        a.retry = function () { readThenSend(a, file); };
        settled(a);
        return;
      }
      a.name = got.file.name;
      a.size = got.file.size;
      if (!a.thumb && ATT_SHOWABLE[got.file.type] && window.URL && URL.createObjectURL) {
        try { a.thumb = URL.createObjectURL(got.file); } catch (e) {}
      }
      send(a, got.file);
      draw();
    });
  }

  function send(a, file) {
    var form = new FormData();
    form.append('file', file, a.name);
    var xhr = new XMLHttpRequest();
    a.xhr = xhr;
    xhr.open('POST', '/attachments/' + encodeURIComponent(session));
    xhr.upload.onprogress = function (e) {
      if (!e.lengthComputable) return;
      a.pct = e.total ? e.loaded / e.total : 0;
      if (a.bar) a.bar.style.width = Math.round(a.pct * 100) + '%';
    };
    xhr.onload = function () {
      var body = safeParse(xhr.responseText) || {};
      if (xhr.status >= 200 && xhr.status < 300 && body.id) {
        a.status = 'ready';
        a.id = body.id;
        a.size = body.size || a.size;
        a.media_type = body.media_type || '';
        a.kind = body.kind || 'file';
        attTookIn(a, body, session);
      } else {
        a.status = 'failed';
        a.error = body.error || ('That upload came back ' + xhr.status + '.');
        a.retry = function () { send(a, file); };
      }
      settled(a);
    };
    xhr.onerror = function () {
      a.status = 'failed';
      a.error = 'The upload did not reach the server.';
      a.retry = function () { send(a, file); };
      settled(a);
    };
    xhr.onabort = function () { settled(a); };
    xhr.send(form);
  }

  function settled(a) {
    a.xhr = null;
    draw();
    if (onSettled && !uploading()) { var f = onSettled; onSettled = null; f(); }
  }

  function uploading() {
    return list.some(function (a) { return a.status === 'uploading'; });
  }

  // What goes with the submission: the session and the id, because a file's
  // address is both of them and the server will not look an id up without
  // the folder it went into.
  function sent() {
    return list.filter(function (a) { return a.status === 'ready' && a.id; })
      .map(function (a) { return { session: session, id: a.id }; });
  }

  function clear() {
    list.forEach(function (a) {
      if (a.xhr) { try { a.xhr.abort(); } catch (e) {} }
      if (a.thumb) { try { URL.revokeObjectURL(a.thumb); } catch (e) {} }
    });
    list = [];
    session = gtNewSession();
    draw();
  }

  return {
    add: add, draw: draw, clear: clear, sent: sent, uploading: uploading,
    count: function () { return list.length; },
    // Press Send while something is still going up and the message goes by
    // itself the moment the last upload settles, which is what the composer
    // does and for the same reason.
    whenSettled: function (fn) { onSettled = fn; }
  };
}

function gtThumb(a) {
  if (a.thumb) {
    var img = document.createElement('img');
    img.className = 'att-thumb';
    img.src = a.thumb;
    img.alt = a.name;
    img.addEventListener('click', function () { openImage(a.thumb, a.name); });
    return img;
  }
  var ext = attExt(a.name);
  var box = el('div', 'att-thumb');
  if (ext) {
    box.className = 'att-thumb att-ext' + (ext.length > 3 ? ' is-long' : '');
    box.textContent = ext.slice(0, 4).toUpperCase();
    box.title = a.name || '';
  }
  return box;
}

//: The drawer's own set of files.
var gtDrawerFiles = gtFiles($('gtFiles'));

/* ---------- the drawer ---------- */

function gtOver() { return GT.open; }

function gtSetOpen(open) {
  GT.open = !!open;
  $('app').setAttribute('data-gt', open ? 'open' : 'shut');
  $('geneTherapyBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
}

function gtOpen() {
  if (GT.thanks) { clearTimeout(GT.thanks); GT.thanks = 0; }
  gtShowForm();
  gtSetOpen(true);
  // The sidebar is lying over the page on a narrow screen, and the button
  // that opened this is in it. Nothing is readable with both up.
  sidebarDone();
  setTimeout(function () { try { $('gtText').focus(); } catch (e) {} }, 160);
}

function gtClose() {
  if (GT.thanks) { clearTimeout(GT.thanks); GT.thanks = 0; }
  gtSetOpen(false);
  gtSay('');
}

function gtShowForm() {
  $('gtForm').hidden = false;
  $('gtThanks').hidden = true;
  $('gtSend').disabled = false;
  $('gtSend').textContent = 'Mutate';
}

function gtSay(text, kind) {
  var box = $('gtSay');
  box.className = 'gt-say' + (kind ? ' ' + kind : '');
  box.textContent = text || '';
  box.hidden = !text;
}

function gtSubmit() {
  var text = $('gtText').value.trim();
  if (!text) { gtSay('Write what to change first.'); $('gtText').focus(); return; }
  var send = $('gtSend');
  if (gtDrawerFiles.uploading()) {
    // Not an error and not a refusal: it goes by itself the moment the last
    // file lands.
    gtSay('Waiting for the files to finish going up…');
    send.disabled = true;
    send.textContent = 'Waiting…';
    gtDrawerFiles.whenSettled(gtSubmit);
    return;
  }
  gtSay('');
  send.disabled = true;
  send.textContent = 'Mutating…';
  // With no connection it goes into this device's outbox, with when it was written, and is on
  // the board once the device is back online (`offline._gene_therapy`). A file cannot be put up
  // with no connection, so one still attached is said rather than lost quietly.
  var off = window.RouhOffline;
  if (off && !off.online()) {
    var files = gtDrawerFiles.sent().length;
    off.queue('feedback', { body: text, page: location.pathname + (location.search || '') }, {}).then(function () {
      $('gtText').value = '';
      gtSay('');
      $('gtThanksMore').textContent = 'You are offline, so it is kept on this device and goes to the board, '
        + 'dated now, when you are back online.' + (files ? ' The files did not go with it: add them then.' : '');
      $('gtThanksMore').hidden = false;
      $('gtForm').hidden = true;
      $('gtThanks').hidden = false;
      GT.thanks = setTimeout(function () {
        GT.thanks = 0;
        gtSetOpen(false);
        gtShowForm();
      }, GT_THANKS_MS * 2);
    });
    return;
  }
  gtFetch('/api/gene-therapy', {
    method: 'POST',
    body: {
      body: text,
      files: gtDrawerFiles.sent(),
      // Where they were when they said it. A person writing "this is wrong"
      // means the screen in front of them.
      page: location.pathname + (location.search || '')
    }
  }).then(function (got) {
    if (GT.onSent) {
      var told = GT.onSent;
      GT.onSent = null;
      try { told(got && got.feedback); } catch (e) {}
    }
    $('gtText').value = '';
    gtDrawerFiles.clear();
    gtSay('');
    // The form goes, Thank you takes its place, and two seconds later the
    // drawer slides back off to the right by itself. When the server is
    // taking it up by itself, Thank you says so: what happens to a feedback
    // is the thing people most want to know, and by the time this is read
    // it has usually already happened.
    var byItself = !!(got && got.automatic);
    $('gtThanksMore').textContent = got && got.autobuild === false
      ? 'It is being read now and written up as a feature request. Automatic '
        + 'build is off, so it waits on the board until somebody starts it.'
      : 'It is being read now, written up as a feature request, and given a '
        + 'run to splice it in.';
    $('gtThanksMore').hidden = !byItself;
    $('gtForm').hidden = true;
    $('gtThanks').hidden = false;
    GT.thanks = setTimeout(function () {
      GT.thanks = 0;
      gtSetOpen(false);
      gtShowForm();
    }, GT_THANKS_MS);
    if (GT.board) gtLoad();
  }).catch(function (err) {
    gtSay(err.message || 'The mutation did not take. Try again.');
    send.disabled = false;
    send.textContent = 'Mutate';
  });
}

/* ---------- a report handed over by a page in the workspace ----------

   A page in the workspace may hold reports written for this drawer, such as
   the bug reports a job writes after using Rouh as a customer would, each
   with its screenshot. The page cannot send one itself: it is a sandboxed
   frame with no sign-in. So it hands the words and the addresses of its own
   screenshots up here (`rouh-page-feedback`, `pages.FEEDBACK_MESSAGE`), and
   they are put in this drawer, the screenshots attached, where the person
   reads them before anything goes.

   The drawer is filled and never sent from here. A page a job built runs
   its own scripts and never speaks for the person (`ownPage`), and a
   feedback is read and built by itself the moment it lands, so the press
   that sends it is the person's own Mutate. `edit` says which the
   page offered: the words with the cursor in them, or Send ready to press.

   Only the canvas's own frame, only a page of the workspace, and only
   screenshots beside that page, fetched from here with the sign-in. What
   the person had already typed in the drawer is never written over. */

//: The most screenshots one report may bring with it.
var GT_PAGE_SHOTS = 4;
var GT_PAGE_SHOT = /^[A-Za-z0-9_][A-Za-z0-9_.\-\/]*\.(png|jpe?g|webp|gif)$/i;

function gtPageSay(frame, id, said) {
  said.type = 'rouh-frame-feedback';
  said.id = id;
  try { frame.contentWindow.postMessage(said, '*'); } catch (err) {}
}

function gtPageShots(at, shots) {
  var base = new URL(at, location.href), out = [];
  (Array.isArray(shots) ? shots : []).slice(0, GT_PAGE_SHOTS).forEach(function (s) {
    if (typeof s !== 'string' || !GT_PAGE_SHOT.test(s) || s.indexOf('..') >= 0) return;
    var u = new URL(s, base);
    if (u.origin === location.origin && u.pathname.indexOf(WORKSPACE_ROUTE) === 0) out.push(u);
  });
  return out;
}

function gtFromPage(frame, m) {
  var at = String(frame && frame.rouhAt || '');
  if (frame !== tasksFrame() || at.indexOf(WORKSPACE_ROUTE) !== 0) {
    gtPageSay(frame, m.id, { ok: false,
      error: 'Rouh takes a report for Gene therapy only from a page of your workspace.' });
    return;
  }
  var body = typeof m.body === 'string' ? m.body.trim().slice(0, 20000) : '';
  if (!body) {
    gtPageSay(frame, m.id, { ok: false, error: 'There is nothing in that report to put in Gene therapy.' });
    return;
  }
  var box = $('gtText'), had = box.value.trim();
  gtOpen();
  if (had && had !== body) {
    gtSay('This box already has words of yours in it. Send them or clear them, then press the '
          + 'button on the page again.');
    gtPageSay(frame, m.id, { ok: false,
      error: 'Rouh\'s Gene therapy box already has something in it. Send or clear that first.' });
    return;
  }
  var shots = had ? [] : gtPageShots(at, m.shots);
  box.value = body;
  Promise.all(shots.map(function (u) {
    return fetch(u.href, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) return null;
      return r.blob().then(function (b) {
        return new File([b], decodeURIComponent(u.pathname.split('/').pop()),
                        { type: b.type || 'image/jpeg' });
      });
    }).catch(function () { return null; });
  })).then(function (files) {
    files = files.filter(Boolean);
    if (files.length) gtDrawerFiles.add(files);
    var missing = shots.length - files.length;
    gtSay(missing ? missing + ' of its screenshots could not be read, so they are not attached.' : '');
    setTimeout(function () {
      try { (m.edit ? box : $('gtSend')).focus(); } catch (e) {}
      if (m.edit) { box.setSelectionRange(0, 0); box.scrollTop = 0; }
    }, 200);
    gtPageSay(frame, m.id, { ok: true, files: files.length });
  });
}

/* ---------- a report handed over by Rouh's own pages ----------

   Trials (`trialspage.js`) hands one problem over as a report, with its
   screenshot, the way Teodora's bug hunt did (30-44): "Send as feedback"
   fills this drawer and sends it, because it is Rouh's own page and the
   person pressed it; "Edit before sending" fills it and puts the cursor in
   the words, and it goes when they press Mutate. Either way `onSent` is told
   the feedback once it is on the board, so the problem can say it was sent.
   What the person had already typed here is never written over. */

function gtHandOver(body, shotUrls, opts) {
  opts = opts || {};
  body = String(body || '').trim().slice(0, 20000);
  var box = $('gtText'), had = box.value.trim();
  gtOpen();
  if (had && had !== body) {
    gtSay('This box already has words of yours in it. Send them or clear them, then press the button again.');
    return Promise.resolve({ ok: false, error: 'The Gene therapy box already has words in it.' });
  }
  box.value = body;
  GT.onSent = typeof opts.onSent === 'function' ? opts.onSent : null;
  var urls = had ? [] : (Array.isArray(shotUrls) ? shotUrls : []).slice(0, GT_PAGE_SHOTS).filter(function (u) {
    return typeof u === 'string' && u.indexOf('/api/trials/') === 0;
  });
  return Promise.all(urls.map(function (u) {
    return fetch(u, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) return null;
      return r.blob().then(function (b) {
        return new File([b], 'trial-' + u.split('/').slice(-3).join('-').replace(/[^\w-]/g, '') + '.jpg',
                        { type: b.type || 'image/jpeg' });
      });
    }).catch(function () { return null; });
  })).then(function (files) {
    files = files.filter(Boolean);
    if (files.length) gtDrawerFiles.add(files);
    if (opts.edit) {
      setTimeout(function () { try { box.focus(); box.setSelectionRange(0, 0); box.scrollTop = 0; } catch (e) {} }, 200);
    } else {
      gtSubmit();
    }
    return { ok: true, files: files.length };
  });
}

window.RouhGeneTherapy = { fill: gtHandOver };

/* ---------- the board ---------- */

function gtBoardOpen() {
  // The same two columns the projects and every canvas layer use. One
  // place at a time, and this is the one being opened.
  showLayer(null);
  projectsClose();
  GT.board = true;
  GT.view = null;
  $('gtBoard').hidden = false;
  $('app').setAttribute('data-board', 'gene-therapy');
  // On a narrow screen the sidebar is lying over the page, and the board is
  // under it. Nothing is readable with both up.
  sidebarDone();
  gtShowColumns();
  gtLoad();
}

function gtBoardClose() {
  GT.board = false;
  GT.view = null;
  $('gtBoard').hidden = true;
  $('app').removeAttribute('data-board');
}

function gtShowColumns() {
  GT.view = null;
  $('gtBoardBody').hidden = false;
  $('gtDetail').hidden = true;
  $('gtDetail').textContent = '';
  $('gtBack').hidden = true;
  $('gtNewRequest').hidden = false;
  $('gtSearch').hidden = false;
  $('gtBoardTitle').textContent = 'All mutations';
  gtBoardSub();
}

function gtBoardSub() {
  var d = GT.data;
  if (!d) { $('gtBoardSub').textContent = ''; return; }
  var said = (d.feedback || []).length, asked = (d.requests || []).length;
  $('gtBoardSub').textContent =
    said + (said === 1 ? ' mutation asked for' : ' mutations asked for') +
    ', ' + asked + (asked === 1 ? ' feature request' : ' feature requests') +
    // "Nothing has happened to mine yet" and "nobody is ever going to look
    // at mine" are two very different things to be reading. Nor is "it is
    // being built" the same as "it is waiting for somebody to build it".
    (!d.automatic ? ''
      : gtBuilds() ? '. Everything left here is read, written up and given a '
                     + 'run by itself.'
      : '. Everything left here is read and written up by itself, and waits '
        + 'for somebody to start its run.');
}

//: Whether this board gives what it writes up a run by itself: the switch
//: at its top. On until the server says otherwise, which is what every
//: board did before there was a switch.
function gtBuilds() {
  var s = (GT.data || {}).settings;
  return !s || s.autobuild !== false;
}

//: A request the machine would have started a run for by now, held back
//: only because the switch is off. The server says which requests the sweep
//: would start (`queued`, rouh/triage.py); this adds the switch.
function gtWaiting(row) {
  return !!(row && row.queued && !row.run_id && (GT.data || {}).automatic && !gtBuilds());
}

function gtSwitchDraw() {
  var d = GT.data, sw = $('gtAutobuild');
  // Nothing is taken up by itself on this machine at all, so there is
  // nothing for the switch to hold back.
  sw.hidden = !(d && d.automatic);
  if (sw.hidden) return;
  var on = gtBuilds(), s = d.settings || {};
  sw.setAttribute('aria-checked', on ? 'true' : 'false');
  $('gtAutobuildState').textContent = on ? 'On' : 'Off';
  sw.title = (on
    ? 'On: every feature request written out of a mutation asked for is given a run to '
      + 'build it, by itself. Turn it off to keep writing them up without building them.'
    : 'Off: mutations asked for are still read and written up as feature requests, and they '
      + 'wait here until somebody starts a run. Turned back on, what is waiting '
      + 'is built by itself, a few at a time.')
    + (s.changed_by ? ' Turned ' + (on ? 'on' : 'off') + ' by ' + s.changed_by
       + (s.changed_at ? ', ' + since(s.changed_at * 1000) : '') + '.' : '');
}

//: Everything on the screen that says whether a run follows, drawn again
//: after the switch has moved.
function gtSwitchRedraw() {
  gtSwitchDraw();
  if (!GT.board) return;
  if (!GT.view && $('gtDetail').hidden) { gtRender(); gtBoardSub(); return; }
  if (GT.view && GT.view.kind === 'request') gtOpenRequest(GT.view.id);
}

function gtLoad() {
  if (GT.loading) return Promise.resolve();
  GT.loading = true;
  return gtFetch('/api/gene-therapy').then(function (data) {
    GT.data = data;
    gtSwitchDraw();
    if (GT.board && !GT.view) gtRender();
    if (GT.board) gtBoardSub();
  }).catch(function (err) {
    if (GT.board && !GT.view) {
      $('gtListSaid').textContent = '';
      $('gtListSaid').appendChild(el('p', 'empty', err.message || 'It could not be read.'));
    }
  }).then(function () { GT.loading = false; });
}

function gtRender() {
  var d = GT.data;
  if (!d) return;
  gtFilters($('gtFilterSaid'), d.statuses.feedback, 'feedback');
  gtFilters($('gtFilterAsked'), d.statuses.requests, 'requests');

  var said = (d.feedback || []).filter(function (f) {
    return (!GT.filter.feedback || f.status === GT.filter.feedback) && gtMatches(f);
  });
  var asked = (d.requests || []).filter(function (r) {
    return (!GT.filter.requests || r.status === GT.filter.requests) && gtMatches(r);
  });
  $('gtCountSaid').textContent = said.length;
  $('gtCountAsked').textContent = asked.length;

  gtFill($('gtListSaid'), said, gtSaidCard,
         GT.find ? 'Nothing here says that.'
                 : GT.filter.feedback
                   ? 'Nothing is ' + gtWords(GT_STATUS_WORDS, GT.filter.feedback).toLowerCase() + '.'
                   : 'Nobody has asked for a mutation yet.');
  gtFill($('gtListAsked'), asked, gtAskedCard,
         GT.find ? 'Nothing here says that.'
                 : GT.filter.requests
                   ? 'Nothing is ' + gtWords(GT_STATUS_WORDS, GT.filter.requests).toLowerCase() + '.'
                   : 'Nothing has been turned into a feature request yet.');
}

//: Whether one card has the words being searched for in it. Everything a
//: person would have read on the card: what was written, its title, and who
//: wrote it.
function gtMatches(row) {
  if (!GT.find) return true;
  var hay = ((row.title || '') + ' ' + (row.body || '') + ' ' +
             (row.author || '')).toLowerCase();
  return hay.indexOf(GT.find) !== -1;
}

function gtFill(node, rows, draw, empty) {
  node.textContent = '';
  if (!rows.length) { node.appendChild(el('p', 'empty', empty)); return; }
  rows.forEach(function (row) { node.appendChild(draw(row)); });
}

function gtFilters(node, statuses, which) {
  node.textContent = '';
  var counts = ((GT.data || {}).counts || {})[which] || {};
  function chip(value, words, n) {
    var b = el('button', 'gt-chip' + (GT.filter[which] === value ? ' on' : ''),
               words + (n ? ' ' + n : ''));
    b.type = 'button';
    b.setAttribute('aria-pressed', GT.filter[which] === value ? 'true' : 'false');
    b.addEventListener('click', function () {
      GT.filter[which] = GT.filter[which] === value ? '' : value;
      gtRender();
    });
    node.appendChild(b);
  }
  var all = 0;
  (statuses || []).forEach(function (s) { all += counts[s] || 0; });
  chip('', 'All', all);
  (statuses || []).forEach(function (s) {
    chip(s, gtWords(GT_STATUS_WORDS, s), counts[s] || 0);
  });
}

function gtPill(kind, value, words) {
  return el('span', 'gt-pill ' + kind + '-' + value, words);
}

function gtCardMeta(row) {
  var meta = el('div', 'gt-card-meta');
  meta.appendChild(el('span', null, row.author || 'Someone'));
  meta.appendChild(el('span', null, since((row.created_at || 0) * 1000)));
  // A request nobody typed. It is on the card because a reading of what
  // somebody said is not the same thing as what they said, and reading a
  // title without knowing which of the two it is would be the wrong way
  // round (rouh/triage.py).
  if (row.automatic) meta.appendChild(el('span', 'gt-auto', 'written by Rouh'));
  if ((row.files || []).length) {
    meta.appendChild(el('span', null, row.files.length +
      (row.files.length === 1 ? ' file' : ' files')));
  }
  return meta;
}

function gtSaidCard(row) {
  var card = el('button', 'gt-card');
  card.type = 'button';
  var top = el('div', 'gt-card-top');
  top.appendChild(gtPill('s', row.status, gtWords(GT_STATUS_WORDS, row.status)));
  card.appendChild(top);
  card.appendChild(el('p', 'gt-card-body', row.body));
  card.appendChild(gtCardMeta(row));
  card.addEventListener('click', function () { gtOpenFeedback(row.id); });
  return card;
}

function gtAskedCard(row) {
  var card = el('button', 'gt-card');
  card.type = 'button';
  var top = el('div', 'gt-card-top');
  top.appendChild(gtPill('k', row.kind, gtWords(GT_KIND_WORDS, row.kind)));
  top.appendChild(gtPill('s', row.status, gtWords(GT_STATUS_WORDS, row.status)));
  card.appendChild(top);
  card.appendChild(el('h4', 'gt-card-title', row.title));
  if (row.body) card.appendChild(el('p', 'gt-card-body', row.body));
  card.appendChild(gtCardMeta(row));
  var run = gtRunWords(row);
  if (run) card.appendChild(el('div', 'gt-card-run' + (gtWaiting(row) ? ' is-waiting' : ''), run));
  card.addEventListener('click', function () { gtOpenRequest(row.id); });
  return card;
}

function gtRunWords(row) {
  if (!row.run_id) {
    // Held back on purpose, and said so: a Proposed card with nothing under
    // it reads as stuck, and this one is exactly where somebody put it.
    if (gtWaiting(row)) return 'waiting to be built - automatic build is off';
    // Nothing would take it, and this is the sentence why: a machine with no
    // worker and no one program on it cannot start anything. It is tried
    // again on the sweep, so this says that too.
    if (row.run_note) return 'no run yet: ' + row.run_note;
    // And the one the sweep is about to start: what was waiting when the
    // switch went back on, a few at a time.
    return row.queued && (GT.data || {}).automatic ? 'queued to be built by itself' : '';
  }
  var run = row.run;
  if (!run) return 'run ' + row.run_id.slice(0, 8) + ' - not on this machine';
  if (run.gone) return 'run ' + row.run_id.slice(0, 8) + ' - forgotten';
  return 'run ' + run.status + (run.detail ? ' - ' + run.detail : '');
}

/* ---------- one of them, in full ---------- */

function gtDetailUp(title) {
  GT.view = null;
  $('gtBoardBody').hidden = true;
  $('gtDetail').hidden = false;
  $('gtDetail').textContent = '';
  $('gtBack').hidden = false;
  $('gtNewRequest').hidden = true;
  $('gtSearch').hidden = true;
  $('gtBoardTitle').textContent = title;
  $('gtBoardSub').textContent = '';
  return $('gtDetail');
}

function gtBack() {
  gtShowColumns();
  gtRender();
}

function gtMetaLine(row) {
  var meta = el('div', 'gt-detail-meta');
  meta.appendChild(el('span', null, row.author || 'Someone'));
  meta.appendChild(el('span', null, whenWords(row.created_at)));
  if (row.page) meta.appendChild(el('span', null, 'from ' + row.page));
  return meta;
}

function gtFileList(files) {
  var box = el('div', 'gt-files');
  (files || []).forEach(function (f) {
    if (ATT_SHOWABLE[f.media_type]) {
      var img = document.createElement('img');
      img.className = 'gt-shot';
      img.src = f.url;
      img.alt = f.name;
      img.title = f.name;
      img.addEventListener('click', function () { openImage(f.url, f.name); });
      box.appendChild(img);
      return;
    }
    var chip = el('div', 'att');
    chip.appendChild(gtThumb({ name: f.name }));
    var text = el('div', 'att-text');
    var link = document.createElement('a');
    link.className = 'att-name';
    link.href = f.url + '?download=1';
    link.textContent = f.name;
    link.title = f.name;
    text.appendChild(link);
    text.appendChild(el('div', 'att-size', attSize(f.size)));
    chip.appendChild(text);
    box.appendChild(chip);
  });
  return box;
}

function gtStatusRow(label, value, options, onPick) {
  var row = el('div', 'gt-row');
  var id = 'fbpick' + Math.random().toString(36).slice(2, 8);
  var lab = el('label', null, label);
  lab.htmlFor = id;
  row.appendChild(lab);
  var pick = document.createElement('select');
  pick.id = id;
  options.forEach(function (o) {
    var opt = el('option', null, gtWords(GT_STATUS_WORDS, o));
    opt.value = o;
    pick.appendChild(opt);
  });
  pick.value = value;
  pick.addEventListener('change', function () { onPick(pick.value); });
  row.appendChild(pick);
  return row;
}

function gtOpenFeedback(id) {
  var box = gtDetailUp('Mutation asked for');
  box.appendChild(el('p', 'empty', 'Reading it…'));
  gtFetch('/api/gene-therapy/' + encodeURIComponent(id)).then(function (got) {
    GT.view = { kind: 'feedback', id: id };
    var row = got.feedback;
    box.textContent = '';
    box.appendChild(el('h3', null, 'What was said'));
    box.appendChild(gtMetaLine(row));
    box.appendChild(el('p', 'gt-said', row.body));
    if ((row.files || []).length) box.appendChild(gtFileList(row.files));

    var state = el('div', 'gt-section');
    state.appendChild(el('h4', null, 'Status'));
    state.appendChild(gtStatusRow('This mutation is',
      row.status, (GT.data || {}).statuses.feedback, function (value) {
        gtFetch('/api/gene-therapy/' + encodeURIComponent(id),
                { method: 'POST', body: { status: value } })
          .then(function () { return gtLoad(); })
          .then(function () { gtOpenFeedback(id); });
      }));
    box.appendChild(state);

    // What has already come out of it, so nobody writes the same feature
    // request twice.
    if ((got.requests || []).length) {
      var made = el('div', 'gt-section');
      made.appendChild(el('h4', null, 'Turned into'));
      got.requests.forEach(function (r) { made.appendChild(gtAskedCard(r)); });
      box.appendChild(made);
    }

    box.appendChild(gtPromoteForm(row));

    var drop = el('button', 'ctl small', 'Delete this mutation');
    drop.type = 'button';
    drop.addEventListener('click', function () {
      if (!window.confirm('Delete this mutation? Its files stay on disk.')) return;
      gtFetch('/api/gene-therapy/' + encodeURIComponent(id), { method: 'DELETE' })
        .then(function () { return gtLoad(); })
        .then(gtBack);
    });
    box.appendChild(drop);
  }).catch(function (err) {
    box.textContent = '';
    box.appendChild(el('p', 'empty', err.message || 'It could not be read.'));
  });
}

//: Turning what somebody said into what is going to be done about it. The
//: feedback itself is never edited: this writes a second thing that
//: remembers it.
function gtPromoteForm(row) {
  var form = el('form', 'gt-section');
  form.appendChild(el('h4', null, 'Turn this into a feature request'));

  var kindRow = el('div', 'gt-row');
  var kindPick = document.createElement('select');
  ((GT.data || {}).kinds || ['feature']).forEach(function (k) {
    var o = el('option', null, gtWords(GT_KIND_WORDS, k));
    o.value = k;
    kindPick.appendChild(o);
  });
  kindRow.appendChild(el('label', null, 'It is a'));
  kindRow.appendChild(kindPick);
  var title = document.createElement('input');
  title.type = 'text';
  title.placeholder = 'Title';
  title.value = (row.body || '').split('\n')[0].slice(0, 120);
  title.className = 'gt-grow';
  kindRow.appendChild(title);
  form.appendChild(kindRow);

  var how = document.createElement('textarea');
  how.placeholder = 'How the solution should work. This is what the run is briefed with, so it is the one worth writing properly.';
  form.appendChild(how);

  var files = el('div', 'gt-atts');
  files.hidden = true;
  form.appendChild(files);
  var picker = document.createElement('input');
  picker.type = 'file';
  picker.multiple = true;
  picker.className = 'sr-only';
  form.appendChild(picker);
  var set = gtFiles(files);
  picker.addEventListener('change', function () {
    set.add(this.files);
    this.value = '';
  });

  var say = el('p', 'gt-say');
  say.hidden = true;
  form.appendChild(say);

  var actions = el('div', 'gt-row');
  var attach = el('button', 'ctl small', 'Attach guidance files');
  attach.type = 'button';
  attach.addEventListener('click', function () { picker.click(); });
  actions.appendChild(attach);
  var go = el('button', 'ctl small primary', 'Make a feature request');
  go.type = 'submit';
  actions.appendChild(go);
  form.appendChild(actions);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!title.value.trim()) {
      say.textContent = 'Give it a title.';
      say.hidden = false;
      title.focus();
      return;
    }
    say.hidden = true;
    go.disabled = true;
    go.textContent = 'Making it…';
    gtFetch('/api/gene-therapy/' + encodeURIComponent(row.id) + '/promote', {
      method: 'POST',
      body: { title: title.value, kind: kindPick.value, body: how.value,
              files: set.sent() }
    }).then(function (got) {
      return gtLoad().then(function () { gtOpenRequest(got.request.id); });
    }).catch(function (err) {
      say.textContent = err.message || 'It could not be made.';
      say.hidden = false;
      go.disabled = false;
      go.textContent = 'Make a feature request';
    });
  });
  return form;
}

function gtOpenRequest(id) {
  var box = gtDetailUp('Feature request');
  box.appendChild(el('p', 'empty', 'Reading it…'));
  gtFetch('/api/gene-therapy/requests/' + encodeURIComponent(id)).then(function (got) {
    GT.view = { kind: 'request', id: id };
    var row = got.request;
    box.textContent = '';

    var top = el('div', 'gt-card-top');
    top.appendChild(gtPill('k', row.kind, gtWords(GT_KIND_WORDS, row.kind)));
    top.appendChild(gtPill('s', row.status, gtWords(GT_STATUS_WORDS, row.status)));
    box.appendChild(top);
    box.appendChild(el('h3', null, row.title));
    box.appendChild(gtMetaLine(row));
    if (row.automatic) {
      // Who started the run is not said here, because nothing records it:
      // with Automatic build off, a run under a card Rouh wrote is started
      // by somebody pressing Start, and this line used to credit Rouh with
      // it. The run section below says what the run is doing.
      box.appendChild(el('p', 'gt-auto-line',
        'Rouh wrote this by reading the mutation it came from. What the person '
        + 'actually said is at the bottom of this page, and it is what the run '
        + 'builds to.'));
    }
    box.appendChild(el('p', 'gt-said', row.body || 'Nothing was written about how it should work.'));
    if ((row.files || []).length) box.appendChild(gtFileList(row.files));

    var state = el('div', 'gt-section');
    state.appendChild(el('h4', null, 'Status'));
    state.appendChild(gtStatusRow('This request is',
      row.status, (GT.data || {}).statuses.requests, function (value) {
        gtFetch('/api/gene-therapy/requests/' + encodeURIComponent(id),
                { method: 'POST', body: { status: value } })
          .then(function () { return gtLoad(); })
          .then(function () { gtOpenRequest(id); });
      }));
    box.appendChild(state);

    box.appendChild(gtRunSection(row));

    if (got.source) {
      var came = el('div', 'gt-section');
      came.appendChild(el('h4', null, 'The mutation this came from'));
      came.appendChild(gtSaidCard(got.source));
      box.appendChild(came);
    }

    var drop = el('button', 'ctl small', 'Delete this feature request');
    drop.type = 'button';
    drop.addEventListener('click', function () {
      if (!window.confirm('Delete this feature request? A run started for it keeps going.')) return;
      gtFetch('/api/gene-therapy/requests/' + encodeURIComponent(id), { method: 'DELETE' })
        .then(function () { return gtLoad(); })
        .then(gtBack);
    });
    box.appendChild(drop);
  }).catch(function (err) {
    box.textContent = '';
    box.appendChild(el('p', 'empty', err.message || 'It could not be read.'));
  });
}

//: Starting a run to build it. The same `starting.start` every other way of
//: starting work goes through, so this is a run of exactly the same kind as
//: one started from the sidebar: told apart by its workspace and its policy
//: and by nothing else.
function gtRunSection(row) {
  var box = el('div', 'gt-section');
  box.appendChild(el('h4', null, 'The run'));

  if (gtWaiting(row)) {
    box.appendChild(el('p', 'gt-card-run is-waiting',
      'Waiting to be built. Automatic build is off, so nothing starts this by '
      + 'itself: start a run for it here, or turn Automatic build back on at the '
      + 'top of the board.'));
  } else if (!row.run_id && !row.run_note && row.queued && (GT.data || {}).automatic) {
    box.appendChild(el('p', 'gt-card-run',
      'Queued to be built by itself. Rouh starts what is queued every few minutes, '
      + 'a few at a time.'));
  }
  if (!row.run_id && row.run_note) {
    // It was tried and nothing took it. Said here rather than left to be
    // guessed at from a status that still reads "proposed", and tried again
    // on the next sweep without anybody doing anything.
    box.appendChild(el('p', 'gt-card-run',
      'No run yet: ' + row.run_note +
      (row.run_tries ? ' Tried ' + row.run_tries +
        (row.run_tries === 1 ? ' time' : ' times') + '.' : '')));
  }
  if (row.run_id) {
    var words = gtRunWords(row);
    box.appendChild(el('p', 'gt-card-run', words));
    if (row.run && !row.run.gone && row.run.mode === 'one') {
      var open = el('button', 'ctl small', 'Open the run');
      open.type = 'button';
      open.addEventListener('click', function () {
        gtBoardClose();
        oneOpen(row.run.id);
      });
      box.appendChild(open);
    }
  }

  var options = (GT.data || {}).run_options || { workspaces: [], policies: [] };
  var row1 = el('div', 'gt-row');
  var wsPick = document.createElement('select');
  wsPick.id = 'fbws' + row.id;
  (options.workspaces || []).forEach(function (w) {
    var o = el('option', null, w.label || w.name);
    o.value = w.name;
    wsPick.appendChild(o);
  });
  // Feedback about Rouh is nearly always work in Rouh's own code, so that is
  // what is selected when this machine has it. Both keys are tried: the
  // workspace was called `jarvis` until the package was renamed on 22
  // September 2026, and a machine still answering to the old name must not
  // silently start runs in the person's workspace instead.
  ['rouh', 'jarvis'].some(function (name) {
    if (!wsPick.querySelector('option[value="' + name + '"]')) return false;
    wsPick.value = name;
    return true;
  });
  var wsLabel = el('label', null, 'In');
  wsLabel.htmlFor = wsPick.id;
  row1.appendChild(wsLabel);
  row1.appendChild(wsPick);

  var polPick = document.createElement('select');
  polPick.id = 'fbpol' + row.id;
  (options.policies || []).forEach(function (p) {
    var o = el('option', null, p + (POLICY_MEANS[p] ? ' - ' + POLICY_MEANS[p] : ''));
    o.value = p;
    polPick.appendChild(o);
  });
  // The program's own rules when this machine has a one program, and an
  // unattended worker here when it has not. The server answers that, not
  // this browser: whether the page has paired with the program is a
  // different question, and using it here offered a worker on a machine that
  // has none.
  polPick.value = options.one_program ? 'one' : 'yolo';
  var polLabel = el('label', null, 'under');
  polLabel.htmlFor = polPick.id;
  row1.appendChild(polLabel);
  row1.appendChild(polPick);
  box.appendChild(row1);

  var say = el('p', 'gt-say');
  say.hidden = true;
  box.appendChild(say);

  var go = el('button', 'ctl small primary',
              row.run_id ? 'Start another run' : 'Start a run for this');
  go.type = 'button';
  go.addEventListener('click', function () {
    say.hidden = true;
    go.disabled = true;
    go.textContent = 'Starting…';
    gtFetch('/api/gene-therapy/requests/' + encodeURIComponent(row.id) + '/run', {
      method: 'POST',
      body: { workspace: wsPick.value, policy: polPick.value }
    }).then(function () {
      return gtLoad().then(function () { gtOpenRequest(row.id); });
    }).catch(function (err) {
      say.textContent = err.message || 'It could not be started.';
      say.hidden = false;
      go.disabled = false;
      go.textContent = row.run_id ? 'Start another run' : 'Start a run for this';
    });
  });
  box.appendChild(go);
  return box;
}

//: A feature request nobody complained about first. That is allowed, and it
//: is the other half of what the board is for.
function gtNewRequestForm() {
  var box = gtDetailUp('New feature request');
  box.textContent = '';
  var form = el('form', 'gt-section');
  form.appendChild(el('h4', null, 'What should be built'));

  var kindRow = el('div', 'gt-row');
  var kindPick = document.createElement('select');
  ((GT.data || {}).kinds || ['feature']).forEach(function (k) {
    var o = el('option', null, gtWords(GT_KIND_WORDS, k));
    o.value = k;
    kindPick.appendChild(o);
  });
  kindRow.appendChild(el('label', null, 'It is a'));
  kindRow.appendChild(kindPick);
  var title = document.createElement('input');
  title.type = 'text';
  title.placeholder = 'Title';
  title.className = 'gt-grow';
  kindRow.appendChild(title);
  form.appendChild(kindRow);

  var how = document.createElement('textarea');
  how.placeholder = 'How the solution should work.';
  form.appendChild(how);

  var files = el('div', 'gt-atts');
  files.hidden = true;
  form.appendChild(files);
  var picker = document.createElement('input');
  picker.type = 'file';
  picker.multiple = true;
  picker.className = 'sr-only';
  form.appendChild(picker);
  var set = gtFiles(files);
  picker.addEventListener('change', function () { set.add(this.files); this.value = ''; });

  var say = el('p', 'gt-say');
  say.hidden = true;
  form.appendChild(say);

  var actions = el('div', 'gt-row');
  var attach = el('button', 'ctl small', 'Attach guidance files');
  attach.type = 'button';
  attach.addEventListener('click', function () { picker.click(); });
  actions.appendChild(attach);
  var go = el('button', 'ctl small primary', 'Make it');
  go.type = 'submit';
  actions.appendChild(go);
  form.appendChild(actions);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!title.value.trim()) {
      say.textContent = 'Give it a title.';
      say.hidden = false;
      title.focus();
      return;
    }
    go.disabled = true;
    go.textContent = 'Making it…';
    gtFetch('/api/gene-therapy/requests', {
      method: 'POST',
      body: { title: title.value, kind: kindPick.value, body: how.value,
              files: set.sent() }
    }).then(function (got) {
      return gtLoad().then(function () { gtOpenRequest(got.request.id); });
    }).catch(function (err) {
      say.textContent = err.message || 'It could not be made.';
      say.hidden = false;
      go.disabled = false;
      go.textContent = 'Make it';
    });
  });
  box.appendChild(form);
  title.focus();
}

/* ---------- the controls ---------- */

$('geneTherapyBtn').addEventListener('click', function () {
  accountMenu(false);
  if (GT.open) gtClose(); else gtOpen();
});
$('gtClose').addEventListener('click', gtClose);
$('gtAll').addEventListener('click', function () {
  gtClose();
  if (GT.board) { gtShowColumns(); gtRender(); return; }
  gtBoardOpen();
});
$('gtForm').addEventListener('submit', function (e) {
  e.preventDefault();
  gtSubmit();
});
// Another one, straight away: the drawer stays, the timer that would take
// it away is stopped, and the form comes back empty.
$('gtAnother').addEventListener('click', gtOpen);
$('gtAttach').addEventListener('click', function () { $('gtFileInput').click(); });
$('gtFileInput').addEventListener('change', /** @this {HTMLInputElement} */ function () {
  gtDrawerFiles.add(this.files);
  this.value = '';
});
// A screenshot in the clipboard, pasted straight into the box, which is how
// most of these will arrive.
$('gtText').addEventListener('paste', function (e) {
  var items = (e.clipboardData && e.clipboardData.files) || null;
  if (!items || !items.length) return;
  e.preventDefault();
  gtDrawerFiles.add(items);
});
$('gtBack').addEventListener('click', gtBack);
$('gtBoardClose').addEventListener('click', gtBoardClose);
// Moved the moment it is pressed and put back if the server says no: a
// switch that waits a round trip before it moves reads as one that did not
// hear. The server tells every other open board itself.
$('gtAutobuild').addEventListener('click', function () {
  var sw = this;
  if (sw.getAttribute('aria-busy') === 'true') return;
  var want = !gtBuilds();
  sw.setAttribute('aria-busy', 'true');
  sw.setAttribute('aria-checked', want ? 'true' : 'false');
  $('gtAutobuildState').textContent = want ? 'On' : 'Off';
  gtFetch('/api/gene-therapy/settings', { method: 'POST', body: { autobuild: want } })
    .then(function (got) {
      if (GT.data) GT.data.settings = got.settings;
      gtSwitchRedraw();
    }).catch(function (err) {
      gtSwitchDraw();
      $('gtBoardSub').textContent = err.message || 'Automatic build could not be changed.';
    }).then(function () { sw.removeAttribute('aria-busy'); });
});
$('gtNewRequest').addEventListener('click', gtNewRequestForm);
$('gtSearch').addEventListener('input', function () {
  GT.find = this.value.trim().toLowerCase();
  gtRender();
});

// Files dragged anywhere over the drawer. The sheet goes by "when did a
// dragover last arrive", the way the conversation's does, rather than by
// counting dragenter against dragleave: a phone does not pair those up, and
// the count left the sheet blue over a drop that had already happened.
// On a phone the drawer is the whole screen, so a drop anywhere while it is
// open is a drop on it (fr_adebbb3c2691: Petar dragged a screenshot's
// thumbnail over it, the screen went blue, and nothing was attached).
(function () {
  var panel = $('gtPanel'), zone = $('gtDrop'), at = 0, timer = null;
  function phoneSheet() {
    return GT.open && window.matchMedia && window.matchMedia('(max-width: 899px)').matches;
  }
  function alive() {
    at = now();
    zone.hidden = false;
    if (timer) return;
    timer = setInterval(function () {
      if (now() - at < 350) return;
      done();
    }, 150);
  }
  function done() {
    at = 0;
    if (timer) { clearInterval(timer); timer = null; }
    zone.hidden = true;
  }
  function over(e) {
    if (!dragHasFiles(e)) return;
    if (!panel.contains(e.target) && !phoneSheet()) return;
    // Ahead of the conversation's own sheet, which would take the drop.
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    alive();
  }
  function drop(e) {
    if (!dragHasFiles(e)) return;
    if (!panel.contains(e.target) && !phoneSheet()) return;
    e.preventDefault();
    e.stopPropagation();
    done();
    var files = droppedFiles(e.dataTransfer);
    if (!files.length) {
      gtSay('That drop brought no file with it, so nothing was attached. Press ' +
        'Attach to pick it instead. (It said it carried: ' + dropTypes(e.dataTransfer) + '.)');
      return;
    }
    gtSay('');
    gtDrawerFiles.add(files);
  }
  // On the window and before anything else, so neither the conversation's
  // drop sheet nor the page's "a stray drop does nothing" can be first.
  window.addEventListener('dragenter', over, true);
  window.addEventListener('dragover', over, true);
  window.addEventListener('drop', drop, true);
  window.addEventListener('dragend', done);
})();

// Escape closes the drawer first and then the board: one press, one thing.
// Registered after the layer handler above, and it only acts on what that
// one leaves alone, so nothing closes twice.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || e.defaultPrevented) return;
  if (GT.open) { e.preventDefault(); gtClose(); return; }
  if (GT.board) { e.preventDefault(); gtBoardClose(); }
});

// A run started from a feature request is an ordinary run, so it arrives on
// the same feed as every other one. Redrawing the board off that feed is
// what puts "run running" and then "run finished" on the card with nothing
// polling and no second socket message.
function gtBoardRefresh(runId) {
  if (!GT.board) return;
  // A run nothing on this board was started for is somebody else's work.
  // Without this the board asked the server again on every tool call of
  // every run on the machine.
  if (runId && !gtOurRun(runId)) return;
  var was = gtRunSign(GT.view);
  gtLoad().then(function () {
    if (!GT.view || GT.view.kind !== 'request') return;
    // Only when this request's own run has actually moved. Redrawing the
    // detail on every run anywhere would clear the workspace and policy the
    // person was in the middle of choosing on it.
    if (gtRunSign(GT.view) !== was) gtOpenRequest(GT.view.id);
  });
}

//: Whether that run is one this board is waiting on.
function gtOurRun(runId) {
  var rows = (GT.data || {}).requests || [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].run_id === runId) return true;
  }
  return false;
}

//: What this board knows about the run behind the request being read, as one
//: string to compare against itself a moment later.
function gtRunSign(view) {
  if (!view || view.kind !== 'request' || !GT.data) return '';
  var rows = GT.data.requests || [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i].id !== view.id) continue;
    var run = rows[i].run;
    return rows[i].run_id + '|' + rows[i].status + '|' +
           (run ? run.status + '|' + run.detail : 'none') +
           (gtWaiting(rows[i]) ? '|waiting' : '');
  }
  return '';
}

/* ------------------------------------------------------- test surface */

window.__rouh = {
  state: function () { return S.state; },
  // Whether the loading screen is up, and what it is waiting for.
  boot: function () {
    return { up: document.documentElement.classList.contains('booting'),
             waiting: bootWaiting() };
  },
  // The memory rings' colour scale, so a check can ask it for a percentage
  // and get back exactly what would be stroked on the ring at it, without
  // waiting three seconds for a poll to land to find out.
  loadColour: memColour,
  orbPoints: function () {
    var out = { segs: orbStats.segs, tips: orbStats.marks, nodes: [], core: null,
                card: $('nodeCard') ? !$('nodeCard').hidden : false };
    var r = orb.getBoundingClientRect();
    if (!orbW || !r.width || !r.height) return out;
    var k = r.width / orbW, c = ORB_HIT.core;
    out.core = { x: r.left + c.x * k, y: r.top + c.y * k };
    var pieces = ORDER.map(function (id) { return SCENE[id]; }).concat([SELF]);
    for (var i = 0; i < pieces.length; i++) {
      var n = pieces[i];
      if (!n || !n.parent || n.alpha <= 0.02 || n.drawn !== orbFrameNo || !(n.pn > 1)) continue;
      // x, y: a point on the drawn line where a real pointer gets this piece,
      // so a check points at it the way a person does; bx, by: where the
      // line starts; tx, ty: its tip.
      var at = orbPointAt(n, r, k), b0 = n.sp[0], b1 = n.sp[n.pn - 1];
      // `state` is here so a check can see the one state that matters:
      // waiting, which is a piece of work stopped until a person does
      // something, drawn red and dashed with NEEDS YOU beside it.
      out.nodes.push({ id: n.id, kind: n.kind, label: n.label, parent: n.parent,
                       state: n.state,
                       x: at ? at.x : r.left + b1.x * k, y: at ? at.y : r.top + b1.y * k,
                       reachable: !!at,
                       bx: r.left + b0.x * k, by: r.top + b0.y * k,
                       tx: r.left + b1.x * k, ty: r.top + b1.y * k,
                       alpha: Math.round(n.alpha * 100) / 100, ghost: !!n.fade });
    }
    return out;
  },
  cfg: cfg,
  debug: debug,
  vad: function () { return { floor: A.floor, level: A.level, open: openThreshold(), utterance: A.utterance }; },
  // What this page is holding of the microphone. `stream` is the one that
  // matters: false means there is no MediaStream here at all, which is the
  // only state in which an operating system puts its indicator out.
  mic: function () {
    var tracks = [];
    if (A.stream) {
      try {
        tracks = A.stream.getTracks().map(function (t) { return t.readyState; });
      } catch (e) { tracks = []; }
    }
    return {
      ready: S.micReady,
      muted: S.muted,
      opening: !!MIC.opening,
      stream: !!A.stream,
      track: !!A.track,
      tracks: tracks,
      ctx: A.ctx ? A.ctx.state : 'none'
    };
  },
  audio: function () {
    return {
      chunks: debug.audioChunks,
      dropped: debug.audioDropped,
      blocked: debug.audioBlocked,
      latchReleased: debug.dropLatchReleased,
      buffers: debug.audioBuffers,
      seconds: debug.audioSeconds,
      live: PB.sources.length,
      rate: PB.rate,
      next: PB.next,
      ctx: A.ctx ? A.ctx.state : 'none',
      ctxTime: A.ctx ? A.ctx.currentTime : 0,
      woken: A.woken,
      // Speech that arrived while the browser would not let the speaker
      // start. Held, not thrown away: it plays on the first press.
      queued: PB.pendingBytes,
      // Sound coming out of the speaker this instant, rather than sound that
      // was scheduled and may be going nowhere.
      level: pbLevel(),
      dropTail: PB.dropTailUntil > 0,
      needsPress: !!($('micBtn') && $('micBtn').classList.contains('needs-press')),
      // A press has been taken as permission and the speaker was built
      // inside it, which is what every browser on an iPhone requires.
      unlocked: !!SPK.unlocked,
      // The silent element holding an audio session open, which is what
      // keeps the Ring/Silent switch on an iPhone from silencing the voice.
      // 'none' anywhere that does not need one.
      session: SPK.session ? (SPK.session.paused ? 'paused' : 'playing') : 'none'
    };
  },
  ws: function () { return S.ws ? S.ws.readyState : -1; },
  connText: function () { return $('conn').getAttribute('aria-label'); },
  cards: function () { return document.querySelectorAll('#transcript .card-slot').length; },
  // The stream: every card in the conversation in the order it is read, what
  // of the history the page holds, whether there is more of it to read,
  // which card is out on the canvas, and which layer - a run, a task - is
  // open over it.
  canvas: function () {
    var host = streamEl(), numbers = [];
    var on = host ? host.querySelectorAll('.card-slot[data-card]') : [];
    for (var i = 0; i < on.length; i++) numbers.push(Number(on[i].getAttribute('data-card')));
    var out = $('cards');
    var away = out ? out.querySelector('.card[data-card]') : null;
    return { cards: numbers, oldest: CARDS.oldest, more: CARDS.more,
             loading: CARDS.loading, layer: layerOpen(),
             onCanvas: away ? Number(away.getAttribute('data-card')) : null };
  },
  // What is in the conversation, top to bottom: a message or a card, and its
  // number where it has one. This is the one stream, so this is the order.
  stream: function () {
    var host = streamEl(), out = [];
    // A card drawn in an answer is inside it, after the message it is in.
    var on = host ? host.querySelectorAll(':scope > .turn, :scope > .card-slot, ' +
                                          ':scope > .turn .card-slot') : [];
    for (var i = 0; i < on.length; i++) {
      var node = on[i];
      if (node.classList.contains('turn') && !node.classList.contains('typing')) {
        out.push({ kind: 'message', id: Number(node.getAttribute('data-msg')) || null,
                   who: node.classList.contains('user') ? 'You' : 'Rouh' });
      } else if (node.classList.contains('card-slot')) {
        out.push({ kind: 'card', id: Number(node.getAttribute('data-card')) || null,
                   away: node.classList.contains('is-away'),
                   folded: node.classList.contains('is-folded') });
      }
    }
    return out;
  },
  olderCards: function () { return loadOlderCards(); },
  // The chats as this page has them: which one is active and what they are
  // called.
  chats: function () {
    return { active: CHATS.active,
             titles: CHATS.list.map(function (c) { return c.title; }),
             folders: CHATS.folders.map(function (f) { return f.name; }) };
  },
  tasks: function () {
    var ids = [], k;
    for (k in taskRecs) ids.push(k);
    return {
      known: ids.length,
      cards: document.querySelectorAll('#tasksList .task').length,
      ids: ids
    };
  },
  busy: function () { return { busy: S.busy, sendDisabled: !!$('sendBtn').disabled }; },
  // Everything that decides whether there is a turn to stop, in one place:
  // what the person can see (the button), and what it is drawn from.
  turn: function () {
    var b = $('stopBtn');
    return {
      stop: !!(b && !b.hidden),
      running: turnIsRunning(),
      busy: S.busy,
      state: S.state,
      speaking: stillSpeaking(),
      stopped: S.stopped,
      textDone: S.textDone,
      tools: S.tools,
      number: S.turn,
      quiet: S.turnSign ? now() - S.turnSign : 0
    };
  },
  columns: function () { return { tasks: SB.open, chat: cols.chat }; },
  orb: function () {
    return {
      mode: '2d',
      running: orbRaf !== 0,
      frames: orbStats.frames,
      segs: orbStats.segs,
      marks: orbStats.marks,
      nodes: orbStats.nodes,
      ms: Math.round(orbStats.ms * 100) / 100,
      back: orb.width,
      haveTree: haveTree
    };
  },
  // What the cog wheel is showing and what it has changed, for the checks
  // that drive the panel with a real mouse.
  orbSettings: function () {
    var cfgNow = {}, moved = [], k;
    for (k in ORB_BASE) {
      cfgNow[k] = ORB_CFG[k];
      if (orbMoved(k)) moved.push(k);
    }
    return {
      open: orbPanelOpen(),
      cog: !$('orbCog').hidden,
      rows: Object.keys(ORB_ROWS).length,
      cfg: cfgNow,
      base: ORB_BASE,
      moved: moved,
      saved: load(KEY_ORB),
      // Whether anything written here is still waiting on a socket to go up.
      unsent: !!orbUnsent
    };
  },
  // What the open orb's sound is doing: whether it is on and sounding, the
  // context it plays through, and the notes it has played, newest last.
  orbSound: function () {
    return {
      on: ORB_SOUND.on,
      live: ORB_SOUND.live,
      ctx: A.ctx ? A.ctx.state : 'none',
      time: A.ctx ? A.ctx.currentTime : 0,
      chords: ORB_SOUND.pad.length,
      queued: ORB_SOUND.queue.length,
      played: ORB_SOUND.played.slice()
    };
  },
  fakeTree: applyTree,
  fakeTasks: applyTaskList,
  fakeTask: upsertTask,
  fakeState: setState,
  fakeCard: renderCard
};

export { gtBoardClose, gtBoardRefresh, gtFromPage, gtOver };
