/* A project's own page at /workspace/_task/<its folder>/.

   The markup is `objectindex.build_task`: the name, what the project is for
   under it, the box that starts a chat, the two pills, and one section per
   kind of thing in the project. This is everything on it that can be pressed.

   What it is for
   --------------

   Petar asked for this on 23 September 2026, with Claude's own project screen
   beside a screenshot of ours: "Notice the instructions and the file uploads
   as functionalities as well as the new chat button float. On desktop, the new
   chat is directly the input box at the very top and once you hit enter it
   opens that chat on a New screen. We should already have a description for
   the projects. There are three dots at the very top, there we have edit and
   we get to the screenshot with changing title and description."

   So, in that order: the box at the top starts a chat in this project and
   takes you to it; the floating button does the same with nothing typed; Add
   files attaches a file to the project; Instructions writes the project's own
   AGENTS.md; and the three dots open Edit, which is the name and the
   description in one panel, saved together.

   How it saves
   ------------

   It cannot save anything itself. The page is sandboxed, with an origin of its
   own and `connect-src 'none'`, so it can no more write than it can read
   (`pages.py`). Every change is handed to the page around it, which is signed
   in and makes the request:

     the name, the description, the instructions, a file taken off
        -> `rouh-page-file`  -> POST /api/workspace/filing (objectindex.change)
     a chat started
        -> `rouh-page-chat`  -> the socket's `new_chat`, with this project's id
     a file attached
        -> `rouh-page-upload`-> POST /api/workspace/file

   Each one names this project by its id and never by a path, and each answer
   carries the project as it really is afterwards, so what is on the screen is
   what is saved rather than what was typed.

   Opened at its own address there is no page around it to hand anything to, so
   the controls are not drawn at all and the page says why. */
(function () {
  'use strict';
  var DATA = window.ROUH_PROJECT || {};
  var ASK = 'rouh-page-file', CHAT = 'rouh-page-chat', UP = 'rouh-page-upload',
    TOLD = 'rouh-frame-filed', BACK = 'rouh-frame-project';
  var NAME_MAX = 60, DESCRIPTION_MAX = 1000, INSTRUCTIONS_MAX = 20000;
  var readonly = !DATA.framed;

  function $(s, r) { return (r || document).querySelector(s); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  // As the server says it (`attachments.human_size`), so a line drawn here
  // reads the same as one the page was served with.
  function human(n) {
    n = Number(n) || 0;
    if (n < 1024) { return n + ' bytes'; }
    if (n < 1048576) { return (n / 1024).toFixed(0) + ' kB'; }
    return (n / 1048576).toFixed(1) + ' MB';
  }

  /* ---------- talking to Rouh ---------- */

  var waiting = {}, seq = 0;
  /* One at a time and in order, so an answer that arrives late can never draw
     an older project over a newer one. */
  var queue = Promise.resolve();

  function post(kind, message, moving) {
    var sent = queue.then(function () {
      return new Promise(function (ok, no) {
        if (readonly) {
          no(new Error('This page is open at its own address, away from Rouh, so nothing on it can be changed.'));
          return;
        }
        var id = 'p' + (++seq), up;
        try { up = window.parent; } catch (e) { up = null; }
        if (!up || up === window) { no(new Error('Rouh could not be reached.')); return; }
        var slot = { ok: ok, no: no };
        slot.timer = setTimeout(function () {
          if (waiting[id]) { delete waiting[id]; no(new Error('Rouh did not answer.')); }
        }, 180000);
        waiting[id] = slot;
        message.type = kind;
        message.id = id;
        try { up.postMessage(message, '*', moving || []); }
        catch (e) {
          delete waiting[id];
          clearTimeout(slot.timer);
          no(new Error('Rouh could not be reached.'));
        }
      });
    });
    queue = sent.catch(function () { /* the caller reports it */ });
    return sent;
  }

  /* A filing action: the name, the description, the instructions, a file taken
     off. `rel` goes with every one of them, which is what makes the answer
     carry this project back rather than only the task browser's index. */
  function file(body) {
    body.rel = DATA.folder || '';
    return post(ASK, { body: body });
  }

  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || (m.type !== TOLD && m.type !== BACK)) { return; }
    var slot = waiting[m.id];
    if (!slot) { return; }
    delete waiting[m.id];
    clearTimeout(slot.timer);
    if (m.project) { adopt(m.project); }
    if (m.ok) { slot.ok(m); } else { slot.no(new Error(m.error || 'That was not saved.')); }
  });

  /* The project as the server says it is. Everything drawn from it is drawn
     again, so a rename, a description, a file or instructions written in one
     panel show up everywhere on the page at once. */
  function adopt(said) {
    if (!said || typeof said !== 'object') { return; }
    DATA.name = said.name || DATA.name;
    DATA.description = said.description || '';
    DATA.instructions = said.instructions || '';
    if (said.files) { DATA.files = said.files; }
    if (said.files_at) { DATA.files_at = said.files_at; }
    drawName();
    drawDescription();
    drawFiles();
    drawInstructionsMark();
  }

  /* ---------- what is drawn ---------- */

  var nameEl = $('#pjName'), descEl = $('#pjDesc'),
    filesSet = $('#pjFilesSet'), fileRows = $('#pjFileRows'),
    fileCount = $('#pjFileCount'), instrDot = $('#pjInstrDot'),
    sayForm = $('#pjSay'), sayBox = $('#pjWhat');

  function drawName() {
    if (nameEl) { nameEl.textContent = DATA.name || ''; }
    if (sayBox) {
      sayBox.placeholder = withSendKeys('Start a new chat in ' + (DATA.name || 'this project'));
    }
    if (document.title && DATA.name) { document.title = DATA.name; }
  }

  function drawDescription() {
    if (!descEl) { return; }
    descEl.textContent = DATA.description || '';
    descEl.hidden = !DATA.description;
  }

  function drawInstructionsMark() {
    if (instrDot) { instrDot.hidden = !(DATA.instructions || '').trim(); }
  }

  function drawFiles() {
    if (!fileRows || !filesSet) { return; }
    var held = DATA.files || [];
    fileRows.textContent = '';
    held.forEach(function (one) {
      var row = el('div', 'orow frow');
      row.setAttribute('data-file', one.id);
      row.appendChild(el('span', 'omark', '📎'));
      var open = el('a', 'oname', one.name);
      open.href = one.at || ((DATA.files_at || '') + one.id);
      open.target = '_blank';
      open.rel = 'noopener';
      row.appendChild(open);
      row.appendChild(el('span', 'ometa-cell', human(one.size)));
      if (!readonly) {
        var drop = el('button', 'fdrop', '×');
        drop.type = 'button';
        drop.setAttribute('aria-label', 'Take ' + one.name + ' off this project');
        drop.addEventListener('click', function () { dropFile(one); });
        row.appendChild(drop);
      }
      fileRows.appendChild(row);
    });
    if (fileCount) { fileCount.textContent = String(held.length); }
    filesSet.hidden = !held.length;
  }

  /* ---------- saying something went wrong ----------

     Only what went wrong: a change that worked shows as the change, on the
     page, and says nothing more (Petar, 22 October 2026, fr_1b64390a0545). */

  var toastEl = null, toastTimer = null;
  function toast(words, bad) {
    if (!toastEl) {
      toastEl = el('div', 'toast');
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = words;
    toastEl.classList.toggle('bad', !!bad);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, bad ? 9000 : 4000);
  }

  /* ---------- the box at the top, and the floating button ---------- */

  /* Enter is a new line and Ctrl+Enter, or Cmd+Enter on a Mac, sends: the
     rule every message box in Rouh keeps, so the one on this page does not
     need learning separately (`isSendKey` in app.js, and why). The empty box
     says so where there is a keyboard to press it on. */
  function isSendKey(e) {
    return e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey
      && !e.isComposing;
  }

  function withSendKeys(words) {
    if (!(window.matchMedia && window.matchMedia('(pointer: fine)').matches)) { return words; }
    var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
    return words + ' (' + (mac ? '\u2318\u21a9' : 'Ctrl+Enter') + ' to send)';
  }

  /* And it grows the way every one does: a line at a time, with no
     scrollbar, up to fifteen lines, and only then a scrollbar, in the box's
     own colours (`workspace/.claude/skills/bb-chat-interface`). It stopped at
     220 pixels with the browser's grey bar until 24 September 2026
     (fr_224c13b2160c). Fewer than fifteen where half the frame will not hold
     them. The same as `fitLines` in taskpage.js, and `growToLines` in
     Rouh's own app.js. */
  function fitLines(box) {
    var cs = getComputedStyle(box);
    var line = parseFloat(cs.lineHeight) || 22;
    var pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    var room = Math.floor((window.innerHeight / 2 - pad) / line);
    var most = Math.max(1, Math.min(15, room)) * line + pad;
    box.style.height = 'auto';
    var want = box.scrollHeight;
    box.style.height = Math.min(want, most) + 'px';
    box.classList.toggle('scrolls', want > most + 1);
  }

  function grow() {
    if (sayBox && sayBox.offsetParent !== null) { fitLines(sayBox); }
  }

  function startChat(said) {
    post(CHAT, { project: DATA.id, said: said || '' })
      .then(function () {
        if (sayBox) { sayBox.value = ''; grow(); }
      })
      .catch(function (err) { toast(err.message, true); });
  }

  if (sayForm && sayBox) {
    if (readonly) {
      sayForm.hidden = true;
    } else {
      sayForm.addEventListener('submit', function (e) {
        e.preventDefault();
        startChat(sayBox.value);
      });
      /* The arrow is pressed as a click and answered as one. A page in a
         sandbox without `allow-forms` never gets its `submit` event: the
         browser refuses the submission before it is fired ("Blocked form
         submission ... the 'allow-forms' permission is not set"), so until 23
         September 2026 the arrow did nothing and only Enter started a chat. */
      var go = sayForm.querySelector('.pjgo');
      if (go) {
        go.addEventListener('click', function (e) {
          e.preventDefault();
          startChat(sayBox.value);
        });
      }
      sayBox.addEventListener('input', grow);
      window.addEventListener('resize', grow);
      sayBox.addEventListener('keydown', function (e) {
        if (isSendKey(e)) {
          e.preventDefault();
          startChat(sayBox.value);
        }
      });
      grow();
    }
  }

  if (!readonly) {
    var float = el('button', 'pjnew');
    float.type = 'button';
    float.innerHTML = '<span aria-hidden="true">+</span>';
    float.appendChild(document.createTextNode('New'));
    float.setAttribute('aria-label', 'Start a new chat in this project');
    float.addEventListener('click', function () { startChat(''); });
    document.body.appendChild(float);
  }

  /* ---------- the panels ---------- */

  /* One shell for both, because they are the same shape: a cross that throws
     the change away, a name, and a tick that saves it. Claude's own screen is
     laid out this way and the person's screenshot is of that screen. */
  function sheet(title, build, save) {
    var back = el('div', 'pjsheet');
    var box = el('div', 'pjbox');
    var top = el('div', 'pjtop');
    var shut = el('button', 'pjx', '×');
    shut.type = 'button';
    shut.setAttribute('aria-label', 'Close without saving');
    var ok = el('button', 'pjok');
    ok.type = 'button';
    ok.setAttribute('aria-label', 'Save');
    ok.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" '
      + 'stroke="currentColor" stroke-width="2"><path d="M3.5 8.5l3 3 6-7"/></svg>';
    top.appendChild(shut);
    top.appendChild(el('h2', null, title));
    top.appendChild(ok);
    box.appendChild(top);
    var first = build(box);
    back.appendChild(box);
    document.body.appendChild(back);

    function close() {
      back.remove();
      document.removeEventListener('keydown', onKey, true);
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    }
    document.addEventListener('keydown', onKey, true);
    shut.addEventListener('click', close);
    back.addEventListener('mousedown', function (e) { if (e.target === back) { close(); } });
    ok.addEventListener('click', function () {
      ok.disabled = true;
      var done = save();
      if (!done || !done.then) { close(); return; }
      done.then(function () { close(); })
        .catch(function (err) { ok.disabled = false; toast(err.message, true); });
    });
    if (first) { try { first.focus(); } catch (e) { /* nothing to focus */ } }
    return close;
  }

  function field(box, words, tag, value, hint, max) {
    box.appendChild(el('label', 'pjlabel', words));
    var node = el(tag, 'pjfield');
    node.value = value || '';
    if (hint) { node.placeholder = hint; }
    if (max) { node.maxLength = max; }
    if (tag === 'textarea') { node.rows = 5; }
    box.appendChild(node);
    return node;
  }

  function editSheet() {
    var name, said;
    sheet('Edit details', function (box) {
      name = field(box, 'What are you working on?', 'input', DATA.name,
                   'Name this project', NAME_MAX);
      said = field(box, 'What are you trying to achieve?', 'textarea',
                   DATA.description, 'Describe your project, goals, subject, etc…',
                   DESCRIPTION_MAX);
      return name;
    }, function () {
      var wanted = name.value.trim(), told = said.value;
      if (!wanted) { return Promise.reject(new Error('A project needs a name.')); }
      // The description always, the name only when it really changed: a
      // rename writes the folder's own `.object.json` as well as the row, and
      // there is no reason to do that for a name nobody touched.
      var first = wanted === (DATA.name || '')
        ? Promise.resolve()
        : file({ action: 'rename', id: DATA.id, name: wanted });
      return first
        .then(function () { return file({ action: 'describe', id: DATA.id, description: told }); });
    });
  }

  function instructionsSheet() {
    var said;
    sheet('Instructions', function (box) {
      box.appendChild(el('p', 'pjsaid',
        'What anything working in this project should know: how you want it '
        + 'done, what to leave alone, where things go. It is kept in the '
        + 'project’s own AGENTS.md, which is what the workspace already reads.'));
      said = field(box, 'Instructions for this project', 'textarea',
                   DATA.instructions, 'Write what belongs here…', INSTRUCTIONS_MAX);
      said.rows = 12;
      return said;
    }, function () {
      return file({ action: 'instructions', id: DATA.id, instructions: said.value });
    });
  }

  /* ---------- the three dots ---------- */

  /* The same menu as every three dots in Rouh (`menu.js`, put into this page
     ahead of this script): an icon and a word on each item, and it closes on
     choosing one, on a press anywhere else and on Escape. */
  var more = $('#pjMore'), menu = $('#pjMenu'), edit = $('#pjEdit');

  if (more && menu) {
    if (readonly) {
      more.hidden = true;
    } else {
      window.RouhMenu.bind(more, menu);
      if (edit) { edit.addEventListener('click', editSheet); }
    }
  }

  /* ---------- the two pills ---------- */

  var addBtn = $('#pjAdd'), instrBtn = $('#pjInstr');

  if (instrBtn) {
    if (readonly) { instrBtn.hidden = true; }
    else { instrBtn.addEventListener('click', instructionsSheet); }
  }

  /* Add files. The picker is in this page, because a file picker only opens on
     a press the person really made and a press relayed to the page around this
     one is not one.

     The bytes do not stay here. They go up as an ArrayBuffer, **transferred**
     rather than copied, and Rouh makes them a file again in its own origin and
     uploads it signed in. Handing the `File` itself up is the obvious thing
     and it does not work: this page is sandboxed with an origin of its own, so
     the file the browser gave it belongs to that origin, and the request the
     page around it then makes is refused before it leaves the browser -
     `net::ERR_ALPN_NEGOTIATION_FAILED`, with nothing in the server log at all.
     An ArrayBuffer has no origin, so it crosses; and being transferred rather
     than cloned means a big file is moved, not copied. */
  var picker = null;
  if (addBtn) {
    if (readonly) {
      addBtn.hidden = true;
    } else {
      picker = el('input');
      picker.type = 'file';
      picker.multiple = true;
      picker.className = 'vh';
      // Out of the way of the keyboard and of a screen reader alike: the
      // button above is the control, and this is only how the browser is
      // asked for a file.
      picker.tabIndex = -1;
      picker.setAttribute('aria-hidden', 'true');
      document.body.appendChild(picker);
      addBtn.addEventListener('click', function () { picker.click(); });
      picker.addEventListener('change', function () {
        var chosen = Array.prototype.slice.call(picker.files || []);
        picker.value = '';
        if (!chosen.length) { return; }
        addBtn.disabled = true;
        chosen.reduce(function (before, one) {
          return before.then(function () {
            return sendFile(one)
              .catch(function (err) { toast(err.message, true); });
          });
        }, Promise.resolve()).then(function () {
          addBtn.disabled = false;
        });
      });
    }
  }

  /* One file's bytes, and what the browser said it was. Read here rather than
     by Rouh, which cannot reach into this page's origin to read it. */
  function bytesOf(one) {
    return new Promise(function (ok, no) {
      var reader = new FileReader();
      reader.onload = function () { ok(reader.result); };
      reader.onerror = function () {
        no(new Error(one.name + ' could not be read from your device.'));
      };
      reader.readAsArrayBuffer(one);
    });
  }

  function sendFile(one) {
    return bytesOf(one).then(function (buffer) {
      return post(UP, {
        project: DATA.id, name: one.name,
        media_type: one.type || '', bytes: buffer
      }, [buffer]);
    });
  }

  function dropFile(one) {
    file({ action: 'drop_file', id: DATA.id, file: one.id })
      .catch(function (err) { toast(err.message, true); });
  }

  /* ---------- and the page as it stands now ---------- */

  if (readonly) {
    document.body.classList.add('readonly');
    var note = el('p', 'pjread',
      'This page is open at its own address, away from Rouh, so it is read '
      + 'only: no chat can be started, nothing attached and nothing changed '
      + 'from here. Open the project in Rouh to use it.');
    var head = $('.ohead');
    if (head) { head.appendChild(note); } else { document.body.insertBefore(note, document.body.firstChild); }
  }
  drawName();
  drawDescription();
  drawFiles();
  drawInstructionsMark();
}());
