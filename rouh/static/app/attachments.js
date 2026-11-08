/* Rouh's page, files attached to a message: the paperclip, the drop zone, paste (section 11c of what was one app.js).
 *
 * Imports app/controls.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { growInput, input, micSays, narrow, sendTyped, setMic } from 'app/controls.js';
import { shared } from 'app/shared.js';
import { $, el, now, safeParse } from 'app/helpers.js';
import { cfg } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { connect, S, send } from 'app/socket.js';
import { A } from 'app/voice.js';
import { holdAudioSession, makeSpeaker, pbFlush, silentTick, speakerReady, SPK } from 'app/playback.js';
import { addPart, drawWords, ensureAssistant, fitActs, newTurn, scrollDown } from 'app/transcript.js';
import { forkBtnPaint, sendKeys, withSendKeys } from 'app/chats.js';
import { freshChatFirst } from 'app/address.js';

/* ----------------------------------------------------------------- 11c */
/* Files attached to a message.
 *
 * Three ways in, one path afterwards: the paperclip opens a picker, files
 * dragged anywhere over the conversation are dropped on it, and a screenshot
 * in the clipboard is pasted. All three end in addFiles(), which puts a chip
 * above the composer for each one and starts its upload straight away.
 *
 * Uploading happens when the file is attached, not when the message is sent,
 * so the wait for a twenty megabyte PDF happens while the person is still
 * typing. What travels on the socket with the message is a list of ids.
 */

//: Kept the same as BLOCKED in attachments.py, which is what actually refuses
//: a file. Checking here as well is only so a file that cannot possibly work
//: is refused before megabytes of it are sent.
//:
//: A list of what is refused, not a list of what is allowed: everything else
//: goes up. These are the formats an operating system runs when you open
//: them. A shell script is not one of them - it is text, and what is stored
//: is stored without the bit that would let it run.
var ATT_BLOCKED = {
  exe: 1, com: 1, scr: 1, pif: 1, msi: 1, msp: 1, cpl: 1, msc: 1, sys: 1,
  drv: 1, dll: 1, ocx: 1, bat: 1, cmd: 1, vbs: 1, vbe: 1, jse: 1, wsf: 1,
  wsh: 1, hta: 1, lnk: 1,
  so: 1, dylib: 1, app: 1, appimage: 1, deb: 1, rpm: 1, dmg: 1, pkg: 1,
  jar: 1, apk: 1, ipa: 1
};
//: The most one file may be: attachments.MAX_BYTES, which the server writes
//: on the file picker, so a file too big is refused here, in words, before a
//: byte of it goes up. The number after it is only for a page with no picker.
var ATT_MAX = Number(document.getElementById('fileInput')?.dataset.max) || 512 * 1024 * 1024;

//: A file bigger than this goes up as it is rather than being read into
//: memory first (`takeInFile`). The read is for a screenshot a phone may take
//: back; a video of hundreds of megabytes is a saved file, and reading it whole
//: would take longer than the read is given and could run a phone out of memory.
var ATT_READ_FIRST = 32 * 1024 * 1024;

//: The picture formats a browser will actually draw. A .heic from a phone and
//: a .svg are both image/something and neither may be put in an <img> here:
//: the .heic draws nothing, and the .svg is a document full of script that
//: the server hands over as a download rather than as a page.
var ATT_SHOWABLE = { 'image/png': 1, 'image/jpeg': 1, 'image/gif': 1, 'image/webp': 1 };

//: Every file attached to the message not yet sent, in the order they were
//: attached. Each is {key, name, size, status, pct, id, thumb, error}, and
//: `retry` while it has failed in a way that trying again could mend.
shared.attached = [];
var attSeq = 0;
//: Set when send was pressed while something was still going up. The message
//: goes by itself the moment the last upload settles, because "press it again
//: in a second" is a thing software should do for you.
shared.sendWhenUploaded = false;

function attSize(n) {
  if (!(n > 0)) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' kB';
  var mb = n / (1024 * 1024);
  return (mb === Math.round(mb) ? mb : mb.toFixed(1)) + ' MB';
}

function attExt(name) {
  var m = /\.([A-Za-z0-9]+)$/.exec(String(name || ''));
  return m ? m[1].toLowerCase() : '';
}

// What the server kept is not always what was sent: an iPhone photo goes up
// as a .heic, which no browser but Safari draws, and is kept as a .jpg
// (`attachments.Attachments.save`). So the chip takes the name the server
// kept, draws the picture from the server's copy when it had none of its
// own, and says so in words when the picture could not be opened.
function attTookIn(a, body, session) {
  if (body.name) a.name = body.name;
  a.note = body.unseen || '';
  if (!a.thumb && ATT_SHOWABLE[a.media_type] && a.kind === 'image' && session) {
    a.thumb = '/attachments/' + encodeURIComponent(session) + '/' + encodeURIComponent(a.id);
  }
}

function attUploading() {
  return shared.attached.some(function (a) { return a.status === 'uploading'; });
}

function attReady() {
  return shared.attached.filter(function (a) { return a.status === 'ready' && a.id; });
}

/* --- the chips above the composer --- */

function drawAttachments() {
  var row = $('attachRow');
  forkBtnPaint();
  if (!row) return;
  row.innerHTML = '';
  row.hidden = shared.attached.length === 0;
  shared.attached.forEach(function (a) {
    var chip = el('div', 'att' + (a.status === 'uploading' ? ' is-uploading' :
                                  a.status === 'failed' ? ' is-failed' : ''));
    chip.appendChild(attThumb(a));

    var text = el('div', 'att-text');
    var name = el('div', 'att-name', a.name);
    name.title = a.name;
    text.appendChild(name);
    if (a.status === 'failed') text.appendChild(el('div', 'att-err', a.error));
    else if (a.note) text.appendChild(el('div', 'att-err', a.note));
    else if (a.reading) text.appendChild(el('div', 'att-size', 'Reading it…'));
    else if (a.status === 'uploading') {
      text.appendChild(el('div', 'att-size', Math.round(a.pct * 100) + '% of ' + attSize(a.size)));
    } else text.appendChild(el('div', 'att-size', attSize(a.size)));
    chip.appendChild(text);

    if (a.status === 'failed' && a.retry) chip.appendChild(attRetryButton(a, attRetry));

    var x = el('button', 'att-x', '×');
    x.type = 'button';
    x.title = 'Remove ' + a.name;
    x.setAttribute('aria-label', 'Remove ' + a.name);
    x.addEventListener('click', function () { removeAttachment(a.key); });
    chip.appendChild(x);

    if (a.status === 'uploading') {
      var bar = el('div', 'att-bar');
      bar.style.width = Math.round(a.pct * 100) + '%';
      chip.appendChild(bar);
      a.bar = bar;
    }
    a.chip = chip;
    row.appendChild(chip);
  });
  growInput();
}

// A picture shows itself. Anything else shows its extension - ZIP, DOCX, MP3 -
// in the same square, because that is the one word that says what the file is
// at a glance, and because the alternative people reach for is an <img> that
// cannot draw a .zip and leaves a broken picture in the conversation.
function attThumb(a) {
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
    box.title = a.media_type ? a.name + ' - ' + a.media_type : a.name || '';
    return box;
  }
  box.innerHTML = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" ' +
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>' +
    '<path d="M14 3v5h5"/></svg>';
  return box;
}

// Retry, on a chip whose upload failed: the same file again, without the
// picker. Only a failure that trying again could mend has one; a program, or
// a file over the limit, would only fail the same way twice.
function attRetryButton(a, again) {
  var b = el('button', 'att-retry', 'Retry');
  b.type = 'button';
  b.title = 'Upload ' + a.name + ' again';
  b.setAttribute('aria-label', 'Retry uploading ' + a.name);
  b.addEventListener('click', function () { again(a); });
  return b;
}

function attRetry(a) {
  var go = a.retry;
  if (!go || shared.attached.indexOf(a) < 0) return;
  a.retry = null;
  a.status = 'uploading';
  a.error = '';
  a.pct = 0;
  go();
  drawAttachments();
}

function removeAttachment(key) {
  for (var i = 0; i < shared.attached.length; i++) {
    if (shared.attached[i].key !== key) continue;
    var a = shared.attached[i];
    if (a.xhr && a.status === 'uploading') { try { a.xhr.abort(); } catch (e) {} }
    if (a.thumb) { try { URL.revokeObjectURL(a.thumb); } catch (e) {} }
    shared.attached.splice(i, 1);
    break;
  }
  drawAttachments();
}

function clearAttachments() {
  shared.attached.forEach(function (a) {
    if (a.xhr && a.status === 'uploading') { try { a.xhr.abort(); } catch (e) {} }
    if (a.thumb) { try { URL.revokeObjectURL(a.thumb); } catch (e) {} }
  });
  shared.attached = [];
  drawAttachments();
}

/* --- taking files in --- */

function addFiles(list) {
  if (!list || !list.length) return;
  for (var i = 0; i < list.length; i++) queueFile(list[i]);
  drawAttachments();
  if (input) input.focus();
}

function queueFile(file) {
  var a = {
    key: 'att' + (++attSeq),
    name: file.name || 'file',
    size: file.size || 0,
    status: 'uploading',
    pct: 0,
    id: null,
    media_type: '',
    kind: '',
    thumb: null,
    error: '',
    xhr: null
  };
  shared.attached.push(a);

  var ext = attExt(a.name);
  if (ATT_BLOCKED[ext]) {
    a.status = 'failed';
    a.error = ext + ' files cannot be attached, because that is a ' +
      'program rather than a document. Everything else can: pictures, text, ' +
      'code, archives, sound, video. Put it in a .zip if the program itself ' +
      'is what you need me to have.';
    return;
  }
  if (a.size > ATT_MAX) {
    a.status = 'failed';
    a.error = a.name + ' is ' + attSize(a.size) + ', and the limit is ' +
      attSize(ATT_MAX) + ' per file. Attach a smaller one, or ask me to open ' +
      'it from a path on this machine.';
    return;
  }
  readThenUpload(a, file);
}

function readThenUpload(a, file) {
  a.reading = true;
  takeInFile(file).then(function (got) {
    a.reading = false;
    if (shared.attached.indexOf(a) < 0) return;   // taken off again meanwhile
    if (got.error) {
      a.status = 'failed';
      a.error = got.error;
      // A phone that handed over nothing the first time often has it now.
      a.retry = function () { readThenUpload(a, file); };
      attSettled();
      return;
    }
    var f = got.file;
    a.name = f.name;
    a.size = f.size;
    // The picture the person is about to send, from the file itself rather
    // than from the server: it is there the instant they drop it, and it is
    // the one way to tell four screenshots apart while they are still going up.
    if (!a.thumb && ATT_SHOWABLE[f.type] && window.URL && URL.createObjectURL) {
      try { a.thumb = URL.createObjectURL(f); } catch (e) {}
    }
    uploadFile(a, f);
    drawAttachments();
  });
}

// One file finished, one way or the other. The message waiting on it goes
// by itself once nothing is still going up.
function attSettled() {
  drawAttachments();
  if (shared.sendWhenUploaded && !attUploading()) {
    var fork = shared.sendWhenUploaded === 'fork';
    shared.sendWhenUploaded = false;
    sendTyped(fork);
  }
}

function uploadFile(a, file) {
  // Attaching a file is saying something, and at the front door there is no
  // conversation to put it in. One is opened first and the file goes up into
  // that; the chip sits at nought for the moment in between (see 10g).
  if (freshChatFirst(function () { uploadFile(a, file); })) return;
  // What Retry does once this has failed: the bytes already read, sent again.
  var again = function () { uploadFile(a, file); };
  if (!S.sessionId) {
    a.status = 'failed';
    a.error = 'Not connected yet, so there is nowhere to put it.';
    a.retry = again;
    return;
  }
  var form = new FormData();
  form.append('file', file, a.name);
  var xhr = new XMLHttpRequest();
  a.xhr = xhr;
  xhr.open('POST', '/attachments/' + encodeURIComponent(S.sessionId));
  xhr.upload.onprogress = function (e) {
    if (!e.lengthComputable) return;
    a.pct = e.total ? e.loaded / e.total : 0;
    // Only the bar moves, so a file going up does not redraw the whole row
    // several times a second under the person's cursor.
    if (a.bar) a.bar.style.width = Math.round(a.pct * 100) + '%';
  };
  xhr.onload = function () {
    var body = safeParse(xhr.responseText) || {};
    if (xhr.status >= 200 && xhr.status < 300 && body.id) {
      a.status = 'ready';
      a.id = body.id;
      a.size = body.size || a.size;
      // What the file turned out to be is the server's answer, not the
      // browser's guess, and it is what the chip in the sent message is drawn
      // from. Without it a .heic would be asked to draw as a picture.
      a.media_type = body.media_type || '';
      a.kind = body.kind || 'file';
      attTookIn(a, body, S.sessionId);
    } else {
      a.status = 'failed';
      a.error = body.error || ('That upload came back ' + xhr.status + '.');
      a.retry = again;
    }
    settled();
  };
  xhr.onerror = function () {
    a.status = 'failed';
    a.error = 'The upload did not reach the server.';
    a.retry = again;
    settled();
  };
  xhr.onabort = function () { settled(); };
  xhr.send(form);

  function settled() {
    a.xhr = null;
    attSettled();
  }
}

/* --- the paperclip --- */

if ($('attachBtn') && $('fileInput')) {
  $('attachBtn').addEventListener('click', function () { $('fileInput').click(); });
  $('fileInput').addEventListener('change', /** @this {HTMLInputElement} */ function () {
    addFiles(this.files);
    // Cleared so choosing the same file twice in a row is still a change.
    this.value = '';
  });
}

/* --- dropping files on the conversation --- */

// Whether this drag is carrying files. A drag of selected text reports
// text/plain and must not put a "drop files" sheet over the conversation.
// A picture handed over by a phone can say only what it is, image/png
// rather than Files, and is a file all the same; the drawer asks this too.
function dragHasFiles(e) {
  var dt = e.dataTransfer;
  if (!dt) return false;
  var types = dt.types || [], i;
  for (i = 0; i < types.length; i++) {
    if (types[i] === 'Files' || /^image\//i.test(types[i])) return true;
  }
  var items = dt.items || [];
  for (i = 0; i < items.length; i++) if (items[i].kind === 'file') return true;
  return false;
}

// The overlay is driven by "when did a dragover last arrive", not by counting
// dragenter against dragleave. Counting is what makes these overlays flicker
// as the pointer crosses a child element, and what leaves them stuck on
// screen for ever when a drag ends outside the window and the last dragleave
// never comes. dragover repeats several times a second for as long as a drag
// is over the column, so its absence is the reliable signal.
var dragAt = 0;
var dragTimer = null;

function showDrop(on) {
  var zone = $('dropZone');
  if (!zone || zone.hidden === !on) return;
  zone.hidden = !on;
}

function dragAlive() {
  dragAt = now();
  showDrop(true);
  if (dragTimer) return;
  dragTimer = setInterval(function () {
    if (now() - dragAt < 350) return;
    clearInterval(dragTimer);
    dragTimer = null;
    showDrop(false);
  }, 150);
}

function dragDone() {
  dragAt = 0;
  if (dragTimer) { clearInterval(dragTimer); dragTimer = null; }
  showDrop(false);
}

var chatCol = $('chatCol');
if (chatCol) {
  ['dragenter', 'dragover'].forEach(function (kind) {
    chatCol.addEventListener(kind, function (e) {
      if (!dragHasFiles(e)) return;
      // Without this the browser takes the drop itself and navigates away
      // from the conversation to show the file.
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      dragAlive();
    });
  });
  chatCol.addEventListener('drop', function (e) {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragDone();
    addFiles(droppedFiles(e.dataTransfer));
  });
}

// Everywhere else on the page a dropped file must simply do nothing. The
// default is to leave the page and open the file, which loses the
// conversation, the microphone and anything typed and not sent.
window.addEventListener('dragover', function (e) {
  if (dragHasFiles(e)) e.preventDefault();
});
window.addEventListener('drop', function (e) {
  if (!dragHasFiles(e)) return;
  e.preventDefault();
  dragDone();
});
window.addEventListener('dragend', dragDone);

/* --- pasting a screenshot --- */

document.addEventListener('paste', function (e) {
  var t = /** @type {HTMLElement} */ (e.target);
  // The run's terminal and its message box handle their own paste, and the
  // start dialog is a form. Taking the event from them would be wrong.
  if (t && t.closest && t.closest('#oneTerm, #oneSay, #oneStartDialog')) return;
  var dt = e.clipboardData;
  if (!dt) return;
  var out = [];
  var items = dt.items || [];
  for (var i = 0; i < items.length; i++) {
    if (items[i].kind !== 'file') continue;
    var f = items[i].getAsFile();
    if (f) out.push(pastedName(f));
  }
  if (!out.length) return;
  // Only when there really was a file: a normal paste of text must still
  // reach the box the cursor is in.
  e.preventDefault();
  addFiles(out);
});

// A screenshot on the clipboard arrives with no name of its own, or with the
// same one every time. Four files all called image.png are impossible to tell
// apart in a chip, in the transcript or on disk, so the clock names them.
// screenshot-2026-09-27-062523.png: the name a picture gets when it came
// without one of its own.
function screenshotName(ext) {
  if (ext === 'jpeg') ext = 'jpg';
  var d = new Date();
  function two(n) { return (n < 10 ? '0' : '') + n; }
  return 'screenshot-' + d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' +
    two(d.getDate()) + '-' + two(d.getHours()) + two(d.getMinutes()) +
    two(d.getSeconds()) + '.' + ext;
}

function pastedName(file) {
  var name = file.name || '';
  if (name && !/^(image|blob|unknown)(\.[a-z0-9]+)?$/i.test(name)) return file;
  var ext = (/^image\/(png|jpeg|gif|webp)$/.exec(file.type || '') || [])[1] || 'png';
  try {
    return new File([file], screenshotName(ext), { type: file.type });
  } catch (err) {
    return file;   // older browsers: keep the file, keep the name it came with
  }
}

/* --- a dropped file, taken in the moment it lands --- */

// The files a drop carries. `files` is where a browser puts them, but a
// phone can hand a picture over only as an item of kind "file", with
// `files` left empty, and then the drop would be seen and nothing attached.
// And a screenshot dragged off an iPhone's thumbnail can list a file with
// nothing in it beside an item that has the picture, so the one with bytes
// in it is taken. Read here, inside the drop, because a browser lets go of
// both the moment the drop event is over.
function droppedFiles(dt) {
  if (!dt) return [];
  var listed = [], held = [], i, f;
  var files = dt.files || [];
  for (i = 0; i < files.length; i++) if (files[i]) listed.push(files[i]);
  var items = dt.items || [];
  for (i = 0; i < items.length; i++) {
    if (!items[i] || items[i].kind !== 'file') continue;
    try { f = items[i].getAsFile && items[i].getAsFile(); } catch (e) { f = null; }
    if (f) held.push(f);
  }
  function full(list) { return list.some(function (x) { return x.size > 0; }); }
  if (listed.length && (full(listed) || !full(held))) return listed;
  return held.length ? held : listed;
}

// What a drop said it carried, for the sentence that says nothing came of
// it: the one thing the person can read back to whoever fixes it.
function dropTypes(dt) {
  var types = (dt && dt.types) || [], out = [];
  for (var i = 0; i < types.length; i++) out.push(String(types[i]));
  return out.join(', ') || 'nothing';
}

//: What the first bytes say a picture is. The server asks the same question
//: (`attachments.SNIFF`); asking it here too is what lets the chip draw the
//: picture and name it truly before it has gone anywhere.
var ATT_SNIFF = [
  { at: 0, bytes: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], type: 'image/png', ext: 'png' },
  { at: 0, bytes: [0xff, 0xd8, 0xff], type: 'image/jpeg', ext: 'jpg' },
  { at: 0, bytes: [0x47, 0x49, 0x46, 0x38], type: 'image/gif', ext: 'gif' },
  { at: 8, bytes: [0x57, 0x45, 0x42, 0x50], type: 'image/webp', ext: 'webp' },
  { at: 4, bytes: [0x66, 0x74, 0x79, 0x70, 0x68, 0x65, 0x69], type: 'image/heic', ext: 'heic' }
];
var ATT_PICTURE_EXT = { png: 1, jpg: 1, jpeg: 1, gif: 1, webp: 1, heic: 1, heif: 1 };

function sniffPicture(head) {
  for (var i = 0; i < ATT_SNIFF.length; i++) {
    var s = ATT_SNIFF[i], ok = head.length >= s.at + s.bytes.length;
    for (var j = 0; ok && j < s.bytes.length; j++) ok = head[s.at + j] === s.bytes[j];
    if (ok) return s;
  }
  return null;
}

function readBytes(file) {
  if (file.arrayBuffer) return file.arrayBuffer();
  return new Promise(function (resolve, reject) {
    var r = new FileReader();
    r.onload = function () { resolve(r.result); };
    r.onerror = function () { reject(r.error); };
    r.readAsArrayBuffer(file);
  });
}

// Petar, 27 September 2026: "If I make a screenshot and the little temporary
// thumbnail is dragged onto the attach area it understands I am trying to
// attach something but it gives me error. If I choose from library that,
// works." A screenshot dragged off an iPhone's thumbnail before it is saved
// is a file the phone may take back, or may not have finished, once the
// drop is over, and an upload that reads it later sends nothing. So its
// bytes are read here, at once and into memory, and it is those that go up.
// It is also named from those bytes: a name that says .png over a JPEG, or
// no name at all, is the phone's guess and not the file.
//
// Answers {file} to upload, or {error} in words the person can act on.
function takeInFile(file) {
  if (file.size > ATT_READ_FIRST) return Promise.resolve({ file: file });
  var tries = 0;
  function attempt() {
    // A file the phone has taken back can leave the read answering never,
    // and the chip would say Reading it for good; five seconds is an answer.
    var late = new Promise(function (_, reject) {
      setTimeout(function () { reject(new Error('timeout')); }, 5000);
    });
    return Promise.race([readBytes(file), late]).then(function (buf) {
      if (buf && buf.byteLength) return buf;
      throw new Error('empty');
    }).catch(function (err) {
      // Still being written when it was dropped: give it a moment or two.
      if (++tries < 4) {
        return new Promise(function (r) { setTimeout(r, 400 * tries); }).then(attempt);
      }
      throw err;
    });
  }
  return attempt().then(function (buf) {
    var pic = sniffPicture(new Uint8Array(buf, 0, Math.min(16, buf.byteLength)));
    var name = file.name || '';
    var type = file.type || '';
    if (pic) {
      type = pic.type;
      var ext = attExt(name);
      if (!name || /^(image|blob|unknown)(\.[a-z0-9]+)?$/i.test(name)) {
        name = screenshotName(pic.ext);
      } else if (!ext) {
        name = name + '.' + pic.ext;
      } else if (ATT_PICTURE_EXT[ext] && ext !== pic.ext &&
                 !(ext === 'jpeg' && pic.ext === 'jpg') &&
                 !(ext === 'heif' && pic.ext === 'heic')) {
        name = name.slice(0, name.length - ext.length) + pic.ext;
      }
    }
    if (!name) name = 'file';
    try {
      return { file: new File([buf], name, { type: type }) };
    } catch (e) {
      return { file: file };   // no File constructor: the original, as it came
    }
  }, function () {
    return { error: (file.name || 'That file') + ' arrived with nothing in it, so ' +
      'there was nothing to attach. A screenshot dragged from its thumbnail ' +
      'straight after it is taken sometimes comes over empty: drop it again ' +
      'once the thumbnail has gone, or pick it from Photos with the paperclip.' };
  });
}

/* --- attached files inside a message on screen --- */

//: Same shape whether the message has just been sent or has been read back
//: from the server after a reload: name, size, and the picture itself when
//: there is one.
function drawTurnFiles(turn, list) {
  if (!turn || !list || !list.length) return;
  // Kept on the message, for a fork taken from it while it is edited
  // (`forkFromEdit`), which draws the same files in the fork.
  turn.turn.__files = list;
  // Pictures Rouh drew are a set of their own, as they were while they
  // were drawn (`drawPictureRow`); everything else is a chip.
  var drawn = list.filter(isDrawn);
  if (drawn.length) drawPictureRow(turn, drawn);
  list = list.filter(function (f) { return !isDrawn(f); });
  if (!list.length) return;
  var box = el('div', 'turn-files');
  list.forEach(function (f) {
    var url = f.url || ('/attachments/' + encodeURIComponent(f.session_id || S.sessionId || '') +
      '/' + encodeURIComponent(f.id || ''));
    var shown = !!(f.made && (f.made.kind === 'area' || f.made.kind === 'ref'));
    var chip = el('div', shown ? 'att is-shown' : 'att');
    // Only the four formats a browser draws. A .heic and a .svg are both
    // image/something, and putting either in an <img> here leaves a broken
    // picture: the first draws nothing, and the second is handed over as a
    // download rather than as a page, on purpose.
    if (ATT_SHOWABLE[f.media_type] && f.kind === 'image') {
      var img = document.createElement('img');
      img.className = 'att-thumb';
      img.src = url;
      img.alt = f.name || 'attached image';
      img.title = 'Open ' + (f.name || 'this picture') + ' full size';
      // A picture that can be changed opens with what can be done with it
      // under it: change an area, more like it, download.
      img.addEventListener('click', function () {
        if (PIC_EDITABLE[f.media_type]) openPicture([picItem(f)], 0);
        else openImage(url, f.name);
      });
      chip.appendChild(img);
      // The area painted, or the picture asked about: the picture says it.
      if (shown) { box.appendChild(chip); return; }
    } else {
      chip.appendChild(attThumb({ name: f.name, media_type: f.media_type }));
    }
    var text = el('div', 'att-text');
    var a = el('a', 'att-name', f.name || 'file');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.title = f.name || '';
    text.appendChild(a);
    text.appendChild(el('div', 'att-size', attSize(f.size)));
    chip.appendChild(text);
    box.appendChild(chip);
  });
  // Above the words, in the same order they were sent in.
  turn.turn.insertBefore(box, turn.body);
}

/* --- a picture, full size --- */

function openImage(url, name) {
  var box = $('lightbox');
  if (!box) { window.open(url, '_blank', 'noopener'); return; }
  // Just the picture: none of what a picture Rouh can change has under it.
  LB.items = null;
  $('lightboxBar').hidden = true;
  $('lightboxSaid').hidden = true;
  $('lightboxPrev').hidden = true;
  $('lightboxNext').hidden = true;
  $('lightboxImg').src = url;
  $('lightboxImg').alt = name || '';
  $('lightboxName').textContent = name || '';
  box.hidden = false;
}

function closeImage() {
  var box = $('lightbox');
  if (!box || box.hidden) return;
  box.hidden = true;
  $('lightboxImg').src = '';
}

if ($('lightbox')) {
  $('lightbox').addEventListener('click', closeImage);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeImage();
  });
}

/* --------------------------------------------- pictures Rouh draws */

/*
 * Petar, 26 September 2026 (fr_77013fa4c9bc): pictures, drawn by OpenAI for
 * now and by another company later, with a way to change only one area of
 * one, and whatever else the provider offers.
 *
 * A picture is drawn on the server (`rouh/imaging.py`), kept in the chat's
 * own files, and written into the conversation as a message of Rouh's that
 * carries its markers, so the same row of thumbnails comes back after a
 * reload. There are three ways in, and one way out:
 *
 * - the composer switched to a picture (`pictureMode`), which asks the
 *   server directly with the settings in the bar above the text;
 * - asking in words, typed or said, which the model answers with its own
 *   `make_picture` and `change_picture`;
 * - under a picture opened full size, Change an area (`openEditor`) and
 *   More like this.
 *
 * Whichever it was, the set arrives the same way: `pictures` with its
 * frames while it is drawn, `picture_partial` with each rough preview, and
 * `pictures` again when it is done or has failed, with the sentence saying
 * why. What the controls may offer is the server's to say, per provider and
 * per model (`imaging.options`), and arrives with `ready`.
 */

var PICS = {
  options: null,     // what the controls may offer (`imaging.options`)
  on: false,         // the composer is asking for a picture, not a reply
  sets: {},          // set id -> a set of pictures on the screen
  waiting: {},       // the page's own id for an ask -> its set, until named
  seq: 0,
  choice: null       // what was picked in the bar, kept in this browser
};
var PIC_KEY = 'rouh.pictures';
//: What a provider can change. A GIF is shown and saved and not changed.
var PIC_EDITABLE = { 'image/png': 1, 'image/jpeg': 1, 'image/webp': 1 };
//: A frame's shape while its picture is still being drawn.
var PIC_RATIO = { square: '1 / 1', landscape: '3 / 2', portrait: '2 / 3',
                  wide: '16 / 9', tall: '9 / 16', auto: '1 / 1' };
//: The words for each, when the server's list is not to hand: the same as
//: `imaging.SHAPES` and `imaging.QUALITIES`.
var PIC_SHAPES = { square: 'Square', landscape: 'Landscape', portrait: 'Portrait',
                   wide: 'Wide 16:9', tall: 'Tall 9:16' };
var PIC_QUALITIES = { low: 'Draft', medium: 'Medium', high: 'High', xhigh: 'Very high',
                      max: 'Best' };
var INPUT_SAID = input.placeholder;
var ICON_BRUSH = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20c2.5 0 4-1.2 4-3.3 0-1.2-.9-2.1-2.1-2.1C4.5 14.6 4 15.8 4 17z"/><path d="M8.7 15.2L19.5 4.5a1.8 1.8 0 0 1 2.5 2.5L11.3 17.8"/></svg>';
var ICON_SAVE = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>';

/* --- what can be drawn with, here --- */

function picProvider() {
  var o = PICS.options;
  if (!o || !o.providers) return null;
  for (var i = 0; i < o.providers.length; i++) if (o.providers[i].ready) return o.providers[i];
  return null;
}

function picModel(id, editing) {
  var p = picProvider();
  if (!p || !p.models || !p.models.length) return null;
  var want = id || (editing ? p.default_edit_model : p.default_model);
  for (var i = 0; i < p.models.length; i++) if (p.models[i].id === want) return p.models[i];
  return p.models[0];
}

function picturesReady(o) {
  PICS.options = o || null;
  var btn = $('pictureBtn');
  if (!btn) return;
  var p = picProvider();
  var first = o && o.providers && o.providers[0];
  btn.disabled = !p;
  btn.title = p ? 'Make a picture: describe it, then send' :
    ((first && first.why_not) || 'Pictures are not set up on this server.');
  if (!p && PICS.on) pictureMode(false);
  if (p && PICS.on) picFill();
}

function picChoice() {
  if (PICS.choice) return PICS.choice;
  var kept = null;
  try { kept = safeParse(localStorage.getItem(PIC_KEY) || ''); } catch (e) { kept = null; }
  PICS.choice = { model: '', shape: 'auto', quality: 'auto', count: 1, background: 'auto' };
  if (kept && typeof kept === 'object') {
    ['model', 'shape', 'quality', 'count', 'background'].forEach(function (k) {
      if (kept[k] != null) PICS.choice[k] = kept[k];
    });
  }
  return PICS.choice;
}

function picKeep() {
  try { localStorage.setItem(PIC_KEY, JSON.stringify(PICS.choice)); } catch (e) { /* kept for this page only */ }
}

function fillPick(sel, items, value) {
  if (!sel) return;
  sel.innerHTML = '';
  items.forEach(function (it) {
    var o = document.createElement('option');
    o.value = String(it.id);
    o.textContent = it.label;
    if (it.title) o.title = it.title;
    sel.appendChild(o);
  });
  sel.value = String(value);
  if (sel.value !== String(value) && items.length) sel.value = String(items[0].id);
}

// The bar's choices, from what the model picked in it can draw.
function picFill() {
  var p = picProvider();
  if (!p) return;
  var c = picChoice();
  fillPick($('picModel'), p.models.map(function (m) {
    return { id: m.id, label: m.label, title: m.note };
  }), c.model || p.default_model);
  var m = picModel($('picModel').value, false);
  fillPick($('picShape'), m.shapes.map(function (s) {
    return { id: s.id, label: s.id === 'auto' ? 'Any shape' : s.label };
  }), c.shape);
  fillPick($('picQuality'), m.qualities.map(function (q) {
    return { id: q.id, label: q.id === 'auto' ? 'Any quality' : q.label + ' quality' };
  }), c.quality);
  var counts = [];
  for (var n = 1; n <= (m.most || 1); n++) counts.push({ id: n, label: n === 1 ? '1 picture' : n + ' pictures' });
  fillPick($('picCount'), counts, c.count);
  fillPick($('picBackground'), m.backgrounds.map(function (b) {
    return { id: b.id, label: b.id === 'auto' ? 'Any background' :
             b.id === 'transparent' ? 'Transparent' : b.label + ' background' };
  }), c.background);
}

['picModel', 'picShape', 'picQuality', 'picCount', 'picBackground'].forEach(function (id) {
  var sel = $(id);
  if (!sel) return;
  sel.addEventListener('change', function () {
    var c = picChoice();
    c.model = $('picModel').value;
    c.shape = $('picShape').value;
    c.quality = $('picQuality').value;
    c.count = Number($('picCount').value) || 1;
    c.background = $('picBackground').value;
    picKeep();
    // Another model may draw other shapes and qualities.
    if (id === 'picModel') picFill();
  });
});

/* --- the composer, asking for a picture --- */

function pictureMode(on) {
  on = !!on && !!picProvider();
  PICS.on = on;
  var bar = $('pictureBar'), btn = $('pictureBtn');
  if (bar) bar.hidden = !on;
  if (btn) {
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.classList.toggle('on', on);
  }
  $('composer').classList.toggle('picture-mode', on);
  input.placeholder = on ? withSendKeys('Describe the picture') : INPUT_SAID;
  $('sendBtn').title = (on ? 'Make the picture' : 'Send') + ' (' + sendKeys() + ')';
  $('sendBtn').setAttribute('aria-label', on ? 'Make the picture' : 'Send message');
  if (on) picFill();
  growInput();
  input.focus();
}

if ($('pictureBtn')) {
  $('pictureBtn').addEventListener('click', function () { pictureMode(!PICS.on); });
  $('pictureOff').addEventListener('click', function () { pictureMode(false); });
}

// Send, while the box is asking for a picture. Not a turn: nothing waits on
// it, and the person can go on talking while it is drawn.
function sendPicture() {
  var text = input.value.trim();
  if (!text) {
    notify('Describe the picture first.', { tone: 'warning' });
    input.focus();
    return;
  }
  if (freshChatFirst(sendPicture)) return;
  if (attUploading()) {
    notify('Wait for the upload to finish, then send.', { tone: 'warning' });
    return;
  }
  var c = picChoice();
  var files = attReady();
  var ids = files.filter(function (a) { return PIC_EDITABLE[a.media_type]; })
    .map(function (a) { return a.id; });
  var rid = 'pic' + (++PICS.seq) + '-' + Date.now();
  var ok = send({
    type: 'picture_make', rid: rid, prompt: text,
    model: $('picModel').value || c.model, shape: $('picShape').value || c.shape,
    quality: $('picQuality').value || c.quality,
    count: Number($('picCount').value) || c.count || 1,
    background: $('picBackground').value || c.background, references: ids
  });
  if (!ok) {
    notify('Not connected, so that picture was not asked for.', { tone: 'error' });
    return;
  }
  input.value = '';
  growInput();
  var drawn = files.map(function (a) {
    return { id: a.id, name: a.name, size: a.size, media_type: a.media_type || '',
             kind: a.kind || 'file' };
  });
  clearAttachments();
  var mine = newTurn('You', 'user');
  drawTurnFiles(mine, drawn);
  drawWords(mine.body, text);
  fitActs(mine.turn);
  picWaiting(rid, Number($('picCount').value) || 1, $('picShape').value || 'auto');
  scrollDown(true);
}

// A set drawn the moment it is asked for, before the server has named it.
function picWaiting(rid, count, shape, ratio) {
  var rec = picSet({ count: count, shape: shape, ratio: ratio });
  picPlace(rec, {});
  PICS.waiting[rid] = rec;
  return rec;
}

/* --- a set of pictures in the conversation --- */

function picSet(opts) {
  var box = el('div', 'pics');
  var grid = el('div', 'pics-grid');
  var meta = el('div', 'pics-meta');
  box.appendChild(grid);
  box.appendChild(meta);
  var rec = { box: box, grid: grid, meta: meta, tiles: [], items: [],
              shape: opts.shape || 'auto', ratio: opts.ratio || '', caption: opts.caption || '' };
  picFrames(rec, opts.count || 1);
  picLine(rec, 'working');
  return rec;
}

function picFrames(rec, n) {
  rec.grid.innerHTML = '';
  rec.tiles = [];
  rec.grid.className = 'pics-grid n' + Math.min(n, 4);
  for (var i = 0; i < n; i++) {
    var tile = el('figure', 'pic is-working');
    tile.style.aspectRatio = rec.ratio || PIC_RATIO[rec.shape] || '1 / 1';
    var wait = el('div', 'pic-wait');
    wait.appendChild(el('span', 'pic-spin'));
    wait.appendChild(el('span', 'pic-wait-word', n > 1 ? 'Drawing ' + (i + 1) + ' of ' + n : 'Drawing'));
    tile.appendChild(wait);
    rec.grid.appendChild(tile);
    rec.tiles.push(tile);
  }
}

// Where a live set goes: inside the answer whose tool drew it, or as an
// answer of its own when the picture controls asked.
function picPlace(rec, m) {
  if (m.turn_id) {
    var a = ensureAssistant(m.turn_id);
    addPart(a, rec.box);
    // What the turn says or does next goes under the pictures.
    a.tools = null;
    a.seg = null;
    rec.turn = a.turn;
  } else {
    var t = newTurn('Rouh', 'assistant');
    t.body.remove();
    t.turn.appendChild(rec.box);
    rec.turn = t.turn;
  }
}

function picLine(rec, state, cost, missing) {
  var line = rec.caption || '';
  if (state === 'done' && cost != null && cost > 0) line += (line ? ' · ' : '') + picMoney(cost);
  if (missing) line += (line ? ' · ' : '') + missing + ' could not be drawn';
  rec.meta.textContent = line;
  rec.meta.hidden = !line;
}

// The same rule for money as the line under an answer (`costs.money`).
function picMoney(cost) {
  if (cost < 0.01) return (cost * 100).toFixed(2) + 'c';
  if (cost < 1) return '$' + cost.toFixed(3);
  return '$' + cost.toFixed(2);
}

function picItem(f) {
  var sid = f.session_id || S.sessionId || '';
  return {
    id: f.id, name: f.name, size: f.size, media_type: f.media_type || '',
    kind: f.kind || 'image', session_id: sid, made: f.made || null,
    url: f.url || ('/attachments/' + encodeURIComponent(sid) + '/' + encodeURIComponent(f.id || ''))
  };
}

function picDone(rec, pictures, cost, missing) {
  var items = pictures.map(picItem);
  rec.items = items;
  rec.grid.innerHTML = '';
  rec.tiles = [];
  rec.grid.className = 'pics-grid n' + Math.min(items.length, 4);
  items.forEach(function (it, i) {
    var tile = picTile(rec, it, i);
    rec.grid.appendChild(tile);
    rec.tiles.push(tile);
  });
  if (cost === undefined) {
    var sum = 0, priced = items.length > 0;
    items.forEach(function (it) {
      if (it.made && it.made.cost != null) sum += Number(it.made.cost) || 0;
      else priced = false;
    });
    cost = priced ? sum : null;
  }
  picLine(rec, 'done', cost, missing);
}

function picTile(rec, it, i) {
  var tile = el('figure', 'pic is-done');
  var made = it.made || {};
  if (made.width && made.height) tile.style.aspectRatio = made.width + ' / ' + made.height;
  var open = el('button', 'pic-open');
  open.type = 'button';
  open.title = 'Open it full size';
  var img = el('img', 'pic-img');
  img.src = it.url;
  img.alt = made.prompt || it.name || 'A picture';
  img.decoding = 'async';
  open.appendChild(img);
  open.addEventListener('click', function () { openPicture(rec.items, i); });
  tile.appendChild(open);
  var acts = el('div', 'pic-acts');
  if (picProvider() && PIC_EDITABLE[it.media_type]) {
    var edit = el('button', 'pic-act');
    edit.type = 'button';
    edit.title = 'Change an area of it';
    edit.setAttribute('aria-label', 'Change an area of it');
    edit.innerHTML = ICON_BRUSH;
    edit.addEventListener('click', function () { openEditor(it); });
    acts.appendChild(edit);
  }
  var save = el('a', 'pic-act');
  save.href = it.url + '?download=1';
  save.setAttribute('download', it.name || '');
  save.title = 'Download ' + (it.name || 'it');
  save.setAttribute('aria-label', 'Download it');
  save.innerHTML = ICON_SAVE;
  acts.appendChild(save);
  tile.appendChild(acts);
  return tile;
}

function picFailed(rec, said) {
  rec.grid.innerHTML = '';
  rec.tiles = [];
  rec.grid.className = 'pics-grid is-failed';
  var box = el('div', 'pics-failed');
  box.setAttribute('role', 'alert');
  box.appendChild(el('span', 'pics-failed-mark', '!'));
  box.appendChild(el('span', 'pics-failed-said', said || 'The picture could not be made.'));
  rec.grid.appendChild(box);
  picLine(rec, 'failed');
}

// The line under a set read back from the history: what the server wrote
// under it while it was drawn (`imaging.caption`).
function picCaptionOf(made) {
  made = made || {};
  /** @type {any} */
  var model = null;
  var p = picProvider();
  if (p) p.models.forEach(function (m) { if (m.id === made.model) model = m; });
  var parts = [model ? model.label : (made.model || '')];
  if (made.from) parts.push(made.area ? 'area changed' : made.variation ? 'variation' : 'whole picture changed');
  else if (made.references && made.references.length) {
    parts.push(made.references.length === 1 ? 'from your picture' : 'from ' + made.references.length + ' of your pictures');
  }
  if (made.asked) parts.push('with the conversation');
  if (made.shape && made.shape !== 'auto' && !made.from) parts.push(PIC_SHAPES[made.shape] || made.shape);
  if (made.quality && made.quality !== 'auto') parts.push(PIC_QUALITIES[made.quality] || made.quality);
  if (made.background === 'transparent') parts.push('transparent');
  return parts.filter(Boolean).join(' · ');
}

function isDrawn(f) { return !!(f && f.made && f.made.kind === 'drawn'); }

// Every set in one stored message of Rouh's: a turn that drew twice has two.
function drawPictureRow(turn, list) {
  var sets = {}, order = [];
  list.forEach(function (f) {
    var key = (f.made && f.made.set) || f.id;
    if (!sets[key]) { sets[key] = []; order.push(key); }
    sets[key].push(f);
  });
  order.forEach(function (key) {
    var files = sets[key];
    var first = files[0].made || {};
    var rec = picSet({ count: files.length, shape: first.shape, caption: picCaptionOf(first) });
    turn.turn.insertBefore(rec.box, turn.body);
    rec.turn = turn.turn;
    picDone(rec, files);
  });
}

/** @param {import('./protocol').FromServer<'pictures'>} m */
function onPictures(m) {
  var rec = PICS.sets[m.set];
  if (!rec && m.rid && PICS.waiting[m.rid]) {
    rec = PICS.waiting[m.rid];
    delete PICS.waiting[m.rid];
  }
  if (!rec) {
    // Another screen's ask, or this one reloaded in the middle of it.
    var n = m.count || (m.pictures || []).length || 1;
    rec = picSet({ count: n, shape: m.shape, caption: m.caption });
    picPlace(rec, m);
  }
  PICS.sets[m.set] = rec;
  if (m.caption) rec.caption = m.caption;
  if (m.state === 'working') {
    if (rec.tiles.length !== (m.count || 1) || (m.shape && m.shape !== rec.shape && !rec.ratio)) {
      rec.shape = m.shape || rec.shape;
      picFrames(rec, m.count || 1);
    }
    picLine(rec, 'working');
  } else if (m.state === 'done') {
    picDone(rec, m.pictures || [], m.cost, m.missing);
  } else if (m.state === 'failed') {
    picFailed(rec, m.said);
  }
  scrollDown();
}

/** @param {import('./protocol').FromServer<'picture_partial'>} m */
function onPicturePartial(m) {
  var rec = PICS.sets[m.set];
  var tile = rec && rec.tiles[m.slot];
  if (!tile || !tile.classList.contains('is-working') || !m.src) return;
  var img = tile.querySelector('img.pic-rough');
  if (!img) {
    img = el('img', 'pic-rough');
    img.alt = 'A rough preview of the picture being drawn';
    tile.insertBefore(img, tile.firstChild);
    tile.classList.add('has-rough');
  }
  img.src = m.src;
}

/* --- a picture, full size, and what can be done with it --- */

var LB = { items: null, at: 0 };

function openPicture(items, at) {
  var box = $('lightbox');
  if (!box || !items || !items.length) return;
  LB.items = items;
  LB.at = Math.max(0, Math.min(items.length - 1, at || 0));
  showPicture();
  box.hidden = false;
}

function showPicture() {
  var it = LB.items[LB.at];
  var made = it.made || {};
  $('lightboxImg').src = it.url;
  $('lightboxImg').alt = made.prompt || it.name || '';
  var many = LB.items.length > 1;
  $('lightboxName').textContent = (it.name || '') + (many ? '  ·  ' + (LB.at + 1) + ' of ' + LB.items.length : '');
  var said = made.kind === 'drawn' ? (made.variation ? 'More like the picture it came from' : made.prompt || '') : '';
  $('lightboxSaid').textContent = said;
  $('lightboxSaid').hidden = !said;
  var editable = !!picProvider() && !!PIC_EDITABLE[it.media_type] && made.kind !== 'area';
  $('lightboxBar').hidden = false;
  $('lightboxEdit').hidden = !editable;
  $('lightboxMore').hidden = !editable;
  $('lightboxSave').href = it.url + '?download=1';
  $('lightboxSave').setAttribute('download', it.name || '');
  $('lightboxPrev').hidden = !many;
  $('lightboxNext').hidden = !many;
}

function stepPicture(by) {
  if (!LB.items || LB.items.length < 2) return;
  LB.at = (LB.at + by + LB.items.length) % LB.items.length;
  showPicture();
}

// Asked for with no words: another take on the picture, two to pick from.
function moreLikeThis(it) {
  if (!picProvider()) return;
  if (freshChatFirst(function () { moreLikeThis(it); })) return;
  var rid = 'pic' + (++PICS.seq) + '-' + Date.now();
  var made = it.made || {};
  if (!send({ type: 'picture_edit', rid: rid, variation: true, source: it.id,
              source_chat: it.session_id, count: 2 })) {
    notify('Not connected, so nothing was asked for.', { tone: 'error' });
    return;
  }
  closeImage();
  var mine = newTurn('You', 'user');
  drawTurnFiles(mine, [{ id: it.id, name: it.name, size: it.size, media_type: it.media_type,
                         kind: 'image', session_id: it.session_id, made: { kind: 'ref' } }]);
  drawWords(mine.body, 'More like this');
  fitActs(mine.turn);
  picWaiting(rid, 2, 'auto', made.width && made.height ? made.width + ' / ' + made.height : '');
  scrollDown(true);
}

(function () {
  function keep(id, go) {
    var b = $(id);
    if (!b) return;
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      if (go) { e.preventDefault(); go(); }
    });
  }
  keep('lightboxPrev', function () { stepPicture(-1); });
  keep('lightboxNext', function () { stepPicture(1); });
  keep('lightboxEdit', function () { if (LB.items) openEditor(LB.items[LB.at]); });
  keep('lightboxMore', function () { if (LB.items) moreLikeThis(LB.items[LB.at]); });
  // Download is a link, and the browser follows it; it only must not close
  // the picture on the way.
  keep('lightboxSave', null);
  document.addEventListener('keydown', function (e) {
    var box = $('lightbox');
    if (!box || box.hidden || !LB.items || LB.items.length < 2) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); stepPicture(-1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); stepPicture(1); }
  });
})();

/* --- changing an area --- */

/*
 * The picture with a canvas laid over it at the size it is sent at, and a
 * brush, a box and an eraser to paint the area to change. What is sent is a
 * mask the size of that picture, transparent where it was painted, which is
 * what OpenAI's edit takes; with nothing painted it is an instruction about
 * the whole picture. A picture bigger than PE_MAX on its long side, or one
 * that is not a PNG, is sent as a PNG copy drawn here at that size, so the
 * mask and the picture are always the same size and a phone photo the right
 * way up (the browser draws it by its EXIF, which the provider may not).
 *
 * Every stroke is kept as what was done rather than as pixels, so Undo
 * takes back one stroke by drawing the rest again.
 */

var PE_MAX = 2048;
//: The paint: pink hatched with white, which reads as marked over any
//: picture, where one flat colour turns brown over green and vanishes over
//: its own colour. Only its shape is sent; the colour never leaves the page.
var PE_PAINT = (function () {
  var t = document.createElement('canvas');
  t.width = t.height = 14;
  var x = t.getContext('2d');
  x.fillStyle = '#ff2f86';
  x.fillRect(0, 0, 14, 14);
  x.strokeStyle = 'rgba(255, 255, 255, 0.85)';
  x.lineWidth = 3;
  x.beginPath();
  x.moveTo(-2, 16); x.lineTo(16, -2);
  x.moveTo(-9, 9); x.lineTo(9, -9);
  x.moveTo(5, 23); x.lineTo(23, 5);
  x.stroke();
  return x.createPattern(t, 'repeat') || '#ff2f86';
})();
var PE = { item: null, w: 0, h: 0, work: false, ops: [], op: null, tool: 'brush', busy: false };

function editorOpen() {
  var box = $('picEditor');
  return !!(box && !box.hidden);
}

function openEditor(it) {
  if (!it || !picProvider()) return;
  closeImage();
  PE.item = it;
  PE.ops = [];
  PE.op = null;
  PE.busy = false;
  PE.w = PE.h = 0;
  $('picEditor').hidden = false;
  $('pePrompt').value = '';
  $('peGo').disabled = false;
  peFill();
  peTool('brush');
  var img = $('peImg');
  img.onload = peMeasure;
  img.src = it.url;
  if (img.complete && img.naturalWidth) peMeasure();
  peHint();
  // A keyboard at a desk goes straight to the words; a phone's would cover
  // half the picture before anything was painted.
  if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) $('pePrompt').focus();
}

function closeEditor() {
  var box = $('picEditor');
  if (!box || box.hidden) return;
  box.hidden = true;
  $('peImg').removeAttribute('src');
  $('peRing').hidden = true;
  PE.item = null;
  PE.op = null;
}

function peFill() {
  var p = picProvider();
  if (!p) return;
  var models = p.models.filter(function (m) { return m.edits; });
  fillPick($('peModel'), models.map(function (m) {
    return { id: m.id, label: m.label, title: m.note };
  }), p.default_edit_model);
  var m = picModel($('peModel').value, true);
  fillPick($('peQuality'), m.qualities.map(function (q) {
    return { id: q.id, label: q.id === 'auto' ? 'Any quality' : q.label + ' quality' };
  }), picChoice().quality || 'auto');
}

function peMeasure() {
  var img = $('peImg');
  var W = img.naturalWidth, H = img.naturalHeight;
  if (!W || !H || !PE.item) return;
  var s = Math.min(1, PE_MAX / Math.max(W, H));
  PE.work = s < 1 || PE.item.media_type !== 'image/png';
  PE.w = Math.max(1, Math.round(W * s));
  PE.h = Math.max(1, Math.round(H * s));
  // A copy is drawn in steps of 16 on both sides, a stretch of under one
  // per cent, because that is a size the provider can be asked to keep:
  // the picture that comes back is the size of the one that went.
  if (PE.work) {
    PE.w = Math.max(16, Math.round(PE.w / 16) * 16);
    PE.h = Math.max(16, Math.round(PE.h / 16) * 16);
  }
  var c = $('pePaint');
  c.width = PE.w;
  c.height = PE.h;
  peFit();
  peRedraw();
}

// The picture as large as the stage lets it be, at its own proportions.
function peFit() {
  if (!PE.w) return;
  var r = $('peStage').getBoundingClientRect();
  var k = Math.min(Math.max(40, r.width - 24) / PE.w, Math.max(40, r.height - 24) / PE.h);
  var f = $('peFrame');
  f.style.width = Math.floor(PE.w * k) + 'px';
  f.style.height = Math.floor(PE.h * k) + 'px';
}

window.addEventListener('resize', function () { if (editorOpen()) peFit(); });

function peTool(tool) {
  PE.tool = tool;
  var tools = document.querySelectorAll('#picEditor .pe-tool[data-tool]');
  for (var i = 0; i < tools.length; i++) {
    var on = tools[i].getAttribute('data-tool') === tool;
    tools[i].setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  $('pePaint').classList.toggle('is-box', tool === 'box');
}

function pePoint(e) {
  var r = $('pePaint').getBoundingClientRect();
  return [(e.clientX - r.left) * (PE.w / (r.width || 1)),
          (e.clientY - r.top) * (PE.h / (r.height || 1))];
}

// The brush's size is said in pixels on the screen and painted in pixels of
// the picture, so a stroke is as wide as the ring that showed where it went.
function peRadius() {
  var r = $('pePaint').getBoundingClientRect();
  return (Number($('peSize').value) / 2) * (PE.w / (r.width || PE.w));
}

function peRedraw() {
  var c = $('pePaint');
  var x = c.getContext('2d');
  x.clearRect(0, 0, c.width, c.height);
  PE.ops.forEach(function (op) { peDraw(x, op); });
}

function peDraw(x, op) {
  x.save();
  x.globalCompositeOperation = op.t === 'erase' ? 'destination-out' : 'source-over';
  x.fillStyle = PE_PAINT;
  x.strokeStyle = PE_PAINT;
  if (op.t === 'box') {
    x.fillRect(Math.min(op.a[0], op.b[0]), Math.min(op.a[1], op.b[1]),
               Math.abs(op.b[0] - op.a[0]), Math.abs(op.b[1] - op.a[1]));
  } else if (op.pts.length === 1) {
    x.beginPath();
    x.arc(op.pts[0][0], op.pts[0][1], op.r, 0, Math.PI * 2);
    x.fill();
  } else {
    x.lineCap = 'round';
    x.lineJoin = 'round';
    x.lineWidth = op.r * 2;
    x.beginPath();
    x.moveTo(op.pts[0][0], op.pts[0][1]);
    for (var i = 1; i < op.pts.length; i++) x.lineTo(op.pts[i][0], op.pts[i][1]);
    x.stroke();
  }
  x.restore();
}

// Whether anything is painted once the eraser has had its say, read off the
// paint itself at a size small enough to read at once.
function pePainted() {
  if (!PE.ops.length || !PE.w) return false;
  var t = document.createElement('canvas');
  t.width = 256;
  t.height = Math.max(1, Math.round(256 * PE.h / PE.w));
  var x = t.getContext('2d');
  x.drawImage($('pePaint'), 0, 0, t.width, t.height);
  var d = x.getImageData(0, 0, t.width, t.height).data;
  for (var i = 3; i < d.length; i += 4) if (d[i] > 0) return true;
  return false;
}

function peHint() {
  var p = picProvider();
  var painted = PE.ops.some(function (op) { return op.t !== 'erase'; });
  // With an area painted, only a model that can be told an area may be
  // picked; the others are there, greyed, saying why.
  var sel = $('peModel');
  if (p && sel) {
    for (var i = 0; i < sel.options.length; i++) {
      var o = sel.options[i], mm = picModel(o.value, true);
      o.disabled = painted && !!mm && !mm.masks;
      o.textContent = mm ? mm.label + (o.disabled ? ' (whole picture only)' : '') : o.textContent;
    }
    if (sel.selectedOptions[0] && sel.selectedOptions[0].disabled) {
      var able = p.models.filter(function (x) { return x.edits && x.masks; })[0];
      if (able) sel.value = able.id;
    }
  }
  var m = picModel(sel ? sel.value : '', true);
  var who = (p && p.label) || 'The provider';
  var said;
  if (m && !m.masks) said = m.label + ' changes the whole picture, as the words say. To change only one area, paint it and ' +
    'pick a model that can.';
  else if (painted) said = 'Only the painted area should change. ' + who +
    ' treats it as a guide rather than a stencil, so its edges may move a little.';
  else said = 'Paint over what should change. Paint nothing to change the whole picture.';
  $('peHint').textContent = said;
  if (!PE.busy) $('peGo').textContent = painted ? 'Change the area' : 'Change the picture';
}

function peRing(e) {
  var ring = $('peRing');
  if (PE.tool === 'box' || e.pointerType === 'touch') { ring.hidden = true; return; }
  var f = $('peFrame').getBoundingClientRect();
  var size = Number($('peSize').value);
  ring.hidden = false;
  ring.style.width = ring.style.height = size + 'px';
  ring.style.left = (e.clientX - f.left - size / 2) + 'px';
  ring.style.top = (e.clientY - f.top - size / 2) + 'px';
  ring.classList.toggle('is-erase', PE.tool === 'erase');
}

(function () {
  var paint = $('pePaint');
  if (!paint) return;
  paint.addEventListener('pointerdown', function (e) {
    if (PE.busy || !PE.w || (e.pointerType === 'mouse' && e.button !== 0)) return;
    e.preventDefault();
    try { paint.setPointerCapture(e.pointerId); } catch (err) { /* painted all the same */ }
    var p = pePoint(e);
    PE.op = PE.tool === 'box' ? { t: 'box', a: p, b: p } : { t: PE.tool, r: peRadius(), pts: [p] };
    PE.ops.push(PE.op);
    peRedraw();
  });
  paint.addEventListener('pointermove', function (e) {
    peRing(e);
    if (!PE.op) return;
    var p = pePoint(e);
    if (PE.op.t === 'box') PE.op.b = p;
    else PE.op.pts.push(p);
    peRedraw();
  });
  function done(e) {
    if (!PE.op) return;
    PE.op = null;
    try { paint.releasePointerCapture(e.pointerId); } catch (err) { /* already let go */ }
    peHint();
  }
  paint.addEventListener('pointerup', done);
  paint.addEventListener('pointercancel', done);
  paint.addEventListener('pointerleave', function () { $('peRing').hidden = true; });

  var tools = document.querySelectorAll('#picEditor .pe-tool[data-tool]');
  for (var i = 0; i < tools.length; i++) {
    tools[i].addEventListener('click', function () { peTool(this.getAttribute('data-tool')); });
  }
  $('peUndo').addEventListener('click', function () { PE.ops.pop(); peRedraw(); peHint(); });
  $('peClear').addEventListener('click', function () { PE.ops = []; peRedraw(); peHint(); });
  $('peClose').addEventListener('click', closeEditor);
  $('peModel').addEventListener('change', function () { peHint(); });
  $('peForm').addEventListener('submit', function (e) { e.preventDefault(); peGo(); });

  // Its own keys, while it is open: Escape closes it, and B, R and E pick
  // the tools and Ctrl+Z takes a stroke back unless the words are being
  // typed, where those keys are letters.
  document.addEventListener('keydown', function (e) {
    if (!editorOpen()) return;
    var typing = document.activeElement === $('pePrompt');
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeEditor(); return; }
    if (typing || e.altKey) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault();
      PE.ops.pop();
      peRedraw();
      peHint();
      return;
    }
    if (e.ctrlKey || e.metaKey) return;
    var tool = { b: 'brush', r: 'box', e: 'erase' }[String(e.key).toLowerCase()];
    if (tool) { e.preventDefault(); peTool(tool); }
  }, true);
})();

function peBlob(canvas, type, quality) {
  return new Promise(function (ok, no) {
    canvas.toBlob(function (b) { if (b) ok(b); else no(new Error('the picture could not be made into a file')); },
                  type, quality);
  });
}

// One file into this chat's attachments, as the paperclip sends them.
function peUpload(blob, name) {
  var form = new FormData();
  form.append('file', blob, name);
  return fetch('/attachments/' + encodeURIComponent(S.sessionId), { method: 'POST', body: form })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok || !body.id) throw new Error(body.error || ('the upload came back ' + r.status));
        return body;
      });
    });
}

function peGo() {
  if (PE.busy || !PE.item || !PE.w) return;
  var words = $('pePrompt').value.trim();
  if (!words) {
    $('peHint').textContent = 'Say what should be there instead, then press it again.';
    $('pePrompt').focus();
    return;
  }
  if (!S.sessionId) {
    $('peHint').textContent = 'Open a chat first, so the picture has somewhere to go.';
    return;
  }
  var it = PE.item;
  var painted = pePainted();
  var img = $('peImg');
  PE.busy = true;
  $('peGo').disabled = true;
  $('peGo').textContent = 'Sending';
  var stem = String(it.name || 'picture').replace(/\.[A-Za-z0-9]+$/, '');
  var jobs = [];
  // The area, the way OpenAI's guide makes one: white and opaque where the
  // picture stays, and see-through wherever it was painted.
  if (painted) {
    var mask = document.createElement('canvas');
    mask.width = PE.w;
    mask.height = PE.h;
    var mx = mask.getContext('2d');
    mx.fillStyle = '#fff';
    mx.fillRect(0, 0, PE.w, PE.h);
    mx.globalCompositeOperation = 'destination-out';
    mx.drawImage($('pePaint'), 0, 0);
    jobs.push(peBlob(mask, 'image/png').then(function (b) { return peUpload(b, 'mask-' + stem + '.png'); }));
  } else jobs.push(Promise.resolve(null));
  // The picture at the size the mask was painted at, when it is not the file.
  if (PE.work) {
    var work = document.createElement('canvas');
    work.width = PE.w;
    work.height = PE.h;
    work.getContext('2d').drawImage(img, 0, 0, PE.w, PE.h);
    jobs.push(peBlob(work, 'image/png').then(function (b) { return peUpload(b, 'work-' + stem + '.png'); }));
  } else jobs.push(Promise.resolve(null));
  // A small copy with the painted area on it, which stands in the question.
  var pw = Math.min(480, PE.w), ph = Math.max(1, Math.round(pw * PE.h / PE.w));
  var look = document.createElement('canvas');
  look.width = pw;
  look.height = ph;
  var lx = look.getContext('2d');
  lx.drawImage(img, 0, 0, pw, ph);
  if (painted) {
    lx.globalAlpha = 0.55;
    lx.drawImage($('pePaint'), 0, 0, pw, ph);
  }
  jobs.push(peBlob(look, 'image/jpeg', 0.86).then(function (b) { return peUpload(b, 'area-' + stem + '.jpg'); }));
  var ratio = PE.w + ' / ' + PE.h;
  Promise.all(jobs).then(function (got) {
    var rid = 'pic' + (++PICS.seq) + '-' + Date.now();
    /** @type {import('./protocol').ToServer<'picture_edit'>} */
    var msg = { type: 'picture_edit', rid: rid, prompt: words, source: it.id,
                source_chat: it.session_id, model: $('peModel').value,
                quality: $('peQuality').value, count: 1 };
    if (got[0]) msg.mask = got[0].id;
    if (got[1]) msg.image = got[1].id;
    if (got[2]) msg.preview = got[2].id;
    if (!send(msg)) throw new Error('not connected');
    closeEditor();
    var shown = got[2] ? { id: got[2].id, name: got[2].name, size: got[2].size,
                           media_type: got[2].media_type, kind: 'image', session_id: S.sessionId,
                           made: { kind: 'area' } }
      : { id: it.id, name: it.name, size: it.size, media_type: it.media_type, kind: 'image',
          session_id: it.session_id, made: { kind: 'ref' } };
    var mine = newTurn('You', 'user');
    drawTurnFiles(mine, [shown]);
    drawWords(mine.body, words);
    fitActs(mine.turn);
    picWaiting(rid, 1, 'auto', ratio);
    scrollDown(true);
  }).catch(function (err) {
    PE.busy = false;
    $('peGo').disabled = false;
    peHint();
    $('peHint').textContent = 'That did not go: ' + (err && err.message ? err.message : err) + '. Try again.';
  });
}

/* --------------------------------------- the speakers, and only those */

/*
 * The page loads straight into the three columns, signed in and live on the
 * socket. There is no splash screen and nothing to tap through: everything
 * except the voice works from the first frame.
 *
 * A browser will not start a speaker outside a real press either, but that
 * press is not a press on anything in particular and it is emphatically not
 * a microphone: an AudioContext is an output, so making one opens no device,
 * asks for no permission and lights no indicator on the phone. The section
 * above the playback scheduler does all of that on demand, and `unlockAudio`
 * below takes any press at all as the one it was waiting for.
 *
 * The microphone is a different thing entirely and has its own section. It
 * is opened when somebody presses the microphone button or starts
 * dictating, and at no other moment. The orb has nothing to do with any of
 * it: the orb is the picture of what the machine is doing, in both its
 * places, and is never a control for the microphone.
 */

function micUnavailable(why) {
  // Nothing left to press, so the speaker's "press me" comes off first: a
  // disabled button that is still pulsing is asking for something it cannot
  // be given.
  $('micBtn').classList.remove('needs-press');
  $('micBtn').disabled = true;
  $('micBtn').setAttribute('aria-pressed', 'false');
  $('micBtn').title = why;
  $('micLabel').textContent = 'No microphone';
  $('meterVal').textContent = 'off';
}

(function () {
  if (!window.AudioContext && !window.webkitAudioContext) {
    micUnavailable('No microphone: this browser has no Web Audio support');
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    micUnavailable('No microphone: this browser has no microphone access');
    return;
  }
  micSays();
}());

/* --------------------------------------------- leaving the microphone open

   A microphone nobody is using is the thing its own section exists to
   prevent, so every way of walking away from the page closes it. Leaving the
   page, and the page put into the back-forward cache, are handled where
   `releaseMic` is defined. This is the other one: walking away without
   leaving.

   A tab put in the background with the microphone on keeps the dot lit on a
   phone for as long as it is there, which is exactly the complaint, so after
   a minute out of sight the microphone is closed. Coming back shows the
   button off, which is true. */

var HIDDEN_GRACE_MS = 60000;
var hiddenTimer = 0;

document.addEventListener('visibilitychange', function () {
  if (!document.hidden) {
    if (hiddenTimer) { clearTimeout(hiddenTimer); hiddenTimer = 0; }
    return;
  }
  if (hiddenTimer || !S.micReady) return;
  hiddenTimer = setTimeout(function () {
    hiddenTimer = 0;
    if (document.hidden && S.micReady) setMic(true);
  }, HIDDEN_GRACE_MS);
});

// Live from the first frame: the socket opens itself, and on a screen with
// room for all three columns the text box is where the person is going to
// start. Not on a phone: there the text box is one pane of three, and
// putting the caret in it on load is the page deciding for them.
connect();
if (!narrow()) $('input').focus();

window.addEventListener('beforeunload', function () {
  S.wantOpen = false;
  if (S.ws) try { S.ws.close(); } catch (e) {}
});

/* Every press anywhere on the page is the permission a browser is waiting
   for, and this is what spends it.

   It used to begin `if (!A.ctx ...) return`, which meant a press could only
   ever *resume* a speaker that already existed. Nothing here ever made one.
   The only thing that made one was `speakerArmed`, when a reply was already
   arriving - and a reply arrives on a websocket, which is not a press. On
   every browser that insists a speaker be started from inside a real press,
   which is every browser on an iPhone, that is the one moment a press was
   guaranteed not to be in hand. So the page collected a dozen taps, threw
   all of them away, and then asked for one more.

   It makes the speaker now, inside the press, which is where WebKit wants it
   made. Three things, in the order iOS wants them: the session that the mute
   switch does not silence, the context itself, and a silent sample through
   it so the engine has seen the page use its speaker while a press was in
   hand. None of it opens a microphone, asks a permission or lights an
   indicator - an AudioContext is an output.

   It never complains if it fails. A reply arriving is what complains. */
function unlockAudio() {
  if (!cfg.voiceReply) return;    // no speaker is wanted, so none is built
  holdAudioSession();
  if (!makeSpeaker()) return;
  SPK.unlocked = true;
  silentTick();
  speakerNudge();
}

/* Getting a speaker going again, without building one.

   Coming back to the tab is not a press, so this is only ever worth
   anything where the browser has changed its mind by itself - a tab
   restored, an interruption ended.

   `interrupted` is the state that used to be missed. An AudioContext on iOS
   is not only running or suspended: it goes to `interrupted` when another
   app takes the audio session - a call, Siri, another tab - and when a Home
   Screen web app is put away and brought back, which is most of what one
   does all day. Testing for `suspended` exactly meant an interrupted speaker
   ignored every press for the rest of the visit, with the reply held and the
   notice up and nothing able to take either of them down. Anything that is
   not running is asked to start. */
function speakerNudge() {
  if (!A.ctx || A.ctx.state === 'running') return;
  var done = function () {
    if (A.ctx && A.ctx.state === 'running') { speakerReady(); pbFlush(false); }
  };
  try {
    var asked = A.ctx.resume();
    if (asked && asked.then) asked.then(done, function () {});
  } catch (e) {}
}

function speakerBackFromAway() {
  if (document.hidden) return;
  // The element stops when iOS takes the session away, and a paused keeper
  // is no keeper at all.
  if (SPK.session && SPK.session.paused) {
    var p = SPK.session.play();
    if (p && p.catch) p.catch(function () {});
  }
  speakerNudge();
}

document.addEventListener('visibilitychange', speakerBackFromAway);
// A Home Screen web app coming back off the back-forward cache fires this
// and not always the one above.
window.addEventListener('pageshow', speakerBackFromAway);

// `click` as well as the three that precede it: a keyboard's Enter on a
// focused button, and every assistive technology, arrive as a click and
// nothing else. Capturing, so a handler that stops propagation cannot spend
// the press without the speaker seeing it.
['pointerdown', 'touchend', 'keydown', 'click'].forEach(function (kind) {
  document.addEventListener(kind, unlockAudio, true);
});

export { ATT_BLOCKED, ATT_MAX, ATT_SHOWABLE, attExt, attReady, attRetryButton, attSize, attTookIn,
  attUploading,
  clearAttachments, dragHasFiles, drawAttachments, drawTurnFiles, droppedFiles, dropTypes,
  editorOpen, isDrawn, onPicturePartial, onPictures, openImage, PICS, picturesReady, sendPicture,
  speakerNudge, takeInFile, unlockAudio };
