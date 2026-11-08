/* The three dots of a working folder inside a task, and of every line of its listing.

   Petar, 8 November 2026 (fr_b89a4b1770d4), on the `scans` folder of a task: "The folder of a
   task is missing the context menu with three dots that has the standard meaningful options like
   rename, delete, make new folder, upload etc". So beside the folder's name there are three dots
   with New folder, Upload files, Rename and Delete (`objectindex_panels.folder_dots`), and every
   folder and file listed in it has its own, with Rename and Delete (`_folder_item`).

   The page cannot change anything itself: each press is handed up to Rouh, which names the task
   it framed from its own canvas, never from this page (`taskFolderAct` in cards.js), and the
   server does it (`rouh/folder_acts.py`). What changed is then drawn by loading this page again,
   or, when this folder itself was renamed or deleted, by Rouh opening where it is now: the new
   name, or the folder above it. Delete asks first, in a dialog of its own.

   Nothing is drawn at the page's own address, away from Rouh, where nothing could be done. */
(function () {
  'use strict';
  var DATA = window.ROUH_FOLDER || {};
  var BACK = 'rouh-frame-project';
  var FOLDER = 'rouh-page-folder';
  if (!DATA.framed || !DATA.doc) { return; }

  var toastEl = null, toastTimer = null;
  function toast(words, good) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.className = good ? 'toast' : 'toast bad';
    toastEl.textContent = words;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, 9000);
  }

  var seq = 0, asked = {};
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== BACK || !asked[m.id]) { return; }
    var said = asked[m.id];
    delete asked[m.id];
    if (!m.ok) {
      toast(m.error || 'Rouh could not do that.');
      if (said.refused) { said.refused(m); }
    } else if (said.done) {
      said.done(m);
    }
  });

  /* One press handed up to Rouh. `refused` when it says no or cannot be reached; `done` when
     it is done. `moving` is what is transferred rather than copied: a file's bytes. */
  function tell(said, refused, done, moving) {
    var up;
    try { up = window.parent; } catch (err) { up = null; }
    if (!up || up === window) {
      toast('Rouh could not be reached.');
      if (refused) { refused(); }
      return;
    }
    var id = 'f' + (++seq);
    asked[id] = { refused: refused, done: done };
    said.type = FOLDER;
    said.id = id;
    try { up.postMessage(said, '*', moving || []); }
    catch (err) {
      delete asked[id];
      toast('Rouh could not be reached.');
      if (refused) { refused(); }
    }
  }

  /* The page is drawn by Rouh into a sandboxed frame, so it cannot load itself again: Rouh is
     asked to draw it again, with what is in the folder now. */
  function again() { tell({ act: 'again', doc: DATA.doc }); }

  /* Delete asks first: what goes, in words, and Delete in red or Keep it. Escape and a press
     outside keep it. */
  function confirmDelete(what, isFolder, go) {
    var box = document.createElement('dialog');
    box.className = 'fdconfirm';
    box.setAttribute('aria-labelledby', 'fdConfirmHead');
    var head = document.createElement('h2');
    head.id = 'fdConfirmHead';
    head.textContent = 'Delete ' + what + '?';
    var line = document.createElement('p');
    line.textContent = isFolder
      ? 'The folder and everything in it are taken out of this task.'
      : 'The file is taken out of this task.';
    var acts = document.createElement('div');
    acts.className = 'fdconfirm-acts';
    var keep = document.createElement('button');
    keep.type = 'button';
    keep.className = 'fdbtn fdbtn-2';
    keep.textContent = 'Keep it';
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'fdbtn fdbtn-danger';
    del.textContent = 'Delete';
    acts.appendChild(keep);
    acts.appendChild(del);
    box.appendChild(head);
    box.appendChild(line);
    box.appendChild(acts);
    document.body.appendChild(box);
    function close() {
      if (box.open) { box.close(); }
      if (box.parentNode) { box.parentNode.removeChild(box); }
    }
    keep.addEventListener('click', close);
    box.addEventListener('cancel', function () { setTimeout(close, 0); });
    box.addEventListener('click', function (e) { if (e.target === box) { close(); } });
    del.addEventListener('click', function () {
      del.disabled = keep.disabled = true;
      del.textContent = 'Deleting…';
      go(close);
    });
    box.showModal();
    keep.focus();
  }

  /* A name made a field in place, holding the same words, selected: Enter keeps it, and so does
     pressing away; Escape puts the old one back. `send(words, undo)` hands it up. */
  function editInPlace(name, label, send) {
    if (!name || name.hidden) { return; }
    var link = name.closest('a[href]');
    var was = name.textContent || '';
    var field = document.createElement('input');
    field.type = 'text';
    field.className = 'oname-edit';
    field.value = was;
    field.maxLength = 120;
    field.setAttribute('aria-label', label);
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('spellcheck', 'false');
    function hold(e) { e.preventDefault(); }
    if (link) { link.addEventListener('click', hold); }
    name.hidden = true;
    name.parentNode.insertBefore(field, name.nextSibling);
    var done = false;
    function stop(keep) {
      if (done) { return; }
      done = true;
      var said = field.value.replace(/\s+/g, ' ').trim();
      if (field.parentNode) { field.parentNode.removeChild(field); }
      name.hidden = false;
      setTimeout(function () { if (link) { link.removeEventListener('click', hold); } }, 0);
      if (!keep || !said || said === was) { return; }
      name.textContent = said;
      send(said, function () { name.textContent = was; });
    }
    field.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); });
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        stop(true);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        stop(false);
      }
    });
    field.addEventListener('blur', function () { stop(true); });
    field.focus();
    field.select();
  }

  /* New folder: a line at the top of the listing with a field for its name. */
  var making = null;
  function newFolder() {
    if (making) { making.querySelector('input').focus(); return; }
    // Not a form: the frame is sandboxed, and a form's submit is refused there.
    var form = document.createElement('div');
    form.className = 'fdnew';
    form.setAttribute('role', 'group');
    form.setAttribute('aria-label', 'New folder');
    var label = document.createElement('label');
    label.className = 'vh';
    label.setAttribute('for', 'fdNewName');
    label.textContent = 'Name of the new folder';
    var field = document.createElement('input');
    field.type = 'text';
    field.id = 'fdNewName';
    field.className = 'fdnew-name';
    field.placeholder = 'Name of the new folder';
    field.maxLength = 120;
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('spellcheck', 'false');
    var make = document.createElement('button');
    make.type = 'button';
    make.className = 'fdbtn';
    make.textContent = 'Make folder';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'fdbtn fdbtn-2';
    cancel.textContent = 'Cancel';
    form.appendChild(label);
    form.appendChild(field);
    form.appendChild(make);
    form.appendChild(cancel);
    function close() {
      if (form.parentNode) { form.parentNode.removeChild(form); }
      making = null;
    }
    cancel.addEventListener('click', close);
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); makeIt(); }
    });
    make.addEventListener('click', makeIt);
    function makeIt() {
      if (make.disabled) { return; }
      var name = field.value.replace(/\s+/g, ' ').trim();
      if (!name) { field.focus(); return; }
      make.disabled = cancel.disabled = field.disabled = true;
      make.textContent = 'Making…';
      tell({ act: 'new_folder', doc: DATA.doc, name: name }, function () {
        make.disabled = cancel.disabled = field.disabled = false;
        make.textContent = 'Make folder';
        field.focus();
      }, again);
    }
    var list = document.querySelector('section.olist');
    if (list) { list.insertBefore(form, list.firstChild); }
    else { document.body.appendChild(form); }
    making = form;
    field.focus();
  }

  /* Upload files: the browser's own picker, several at once, one after another, and a line
     saying how far it is; the folder is drawn again once they are all in. */
  var picker = document.createElement('input');
  picker.type = 'file';
  picker.multiple = true;
  picker.className = 'vh';
  picker.tabIndex = -1;
  picker.setAttribute('aria-hidden', 'true');
  document.body.appendChild(picker);
  var status = null;
  function say(words) {
    if (!status) {
      status = document.createElement('p');
      status.className = 'fdstatus';
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      var head = document.querySelector('header.ohead');
      if (head) { head.appendChild(status); } else { document.body.insertBefore(status, document.body.firstChild); }
    }
    status.textContent = words;
  }
  function bytesOf(one) {
    return new Promise(function (ok, no) {
      var reader = new FileReader();
      reader.onload = function () { ok(reader.result); };
      reader.onerror = function () { no(new Error(one.name + ' could not be read from your device.')); };
      reader.readAsArrayBuffer(one);
    });
  }
  function uploadAll(chosen) {
    if (!chosen.length) { return; }
    var put = 0, failed = [];
    var queue = Promise.resolve();
    chosen.forEach(function (one, i) {
      queue = queue.then(function () {
        say('Uploading ' + (chosen.length > 1 ? (i + 1) + ' of ' + chosen.length + ': ' : '') + one.name + '…');
        return bytesOf(one).then(function (buffer) {
          return new Promise(function (ok) {
            tell({ act: 'upload', doc: DATA.doc, name: one.name, media_type: one.type || '', bytes: buffer },
              function (m) { failed.push(one.name + ': ' + ((m && m.error) || 'not uploaded')); ok(); },
              function () { put += 1; ok(); }, [buffer]);
          });
        }, function (err) { failed.push(err.message); });
      });
    });
    queue.then(function () {
      if (failed.length) {
        say((put ? put + ' uploaded. ' : '') + 'Not uploaded: ' + failed.join('; '));
        if (put) { setTimeout(again, 2500); }
        return;
      }
      say(put === 1 ? 'Uploaded.' : put + ' files uploaded.');
      again();
    });
  }
  picker.addEventListener('change', function () {
    var chosen = Array.prototype.slice.call(picker.files || []);
    picker.value = '';
    uploadAll(chosen);
  });

  /* The folder's own three dots, beside its name. */
  var bar = document.getElementById('fdBar');
  var more = document.getElementById('fdMore');
  var menu = document.getElementById('fdMenu');
  if (bar && more && menu && window.RouhMenu) {
    bar.hidden = false;
    window.RouhMenu.bind(more, menu);
    document.getElementById('fdNew').addEventListener('click', newFolder);
    document.getElementById('fdUpload').addEventListener('click', function () { picker.click(); });
    document.getElementById('fdRename').addEventListener('click', function () {
      editInPlace(document.getElementById('fdName'), 'The folder\'s new name', function (words, undo) {
        // Rouh opens the folder where its new name is.
        tell({ act: 'rename', doc: DATA.doc, name: words, here: true }, undo);
      });
    });
    document.getElementById('fdDelete').addEventListener('click', function () {
      var name = (document.getElementById('fdName') || {}).textContent || 'this folder';
      confirmDelete(name, true, function (close) {
        // Rouh opens the folder above it, or the task.
        tell({ act: 'delete', doc: DATA.doc, here: true }, close, close);
      });
    });
  }

  /* An empty folder's two buttons: the same two ways in as its dots. */
  var empty = document.getElementById('fdEmptyActs');
  if (empty) {
    empty.hidden = false;
    Array.prototype.forEach.call(empty.querySelectorAll('[data-fd]'), function (b) {
      b.addEventListener('click', function () {
        if (b.getAttribute('data-fd') === 'upload') { picker.click(); } else { newFolder(); }
      });
    });
  }

  /* Every line's own three dots: Rename and Delete of that folder or file. */
  if (window.RouhMenu) {
    var lineMenus = [];
    Array.prototype.forEach.call(document.querySelectorAll('.fditem'), function (line) {
      var dots = line.querySelector('.odots');
      var its = line.querySelector('.imenu');
      if (!dots || !its) { return; }
      dots.hidden = false;
      lineMenus.push(window.RouhMenu.bind(dots, its, { align: 'end' }));
      var doc = line.getAttribute('data-doc') || '';
      var called = line.getAttribute('data-name') || '';
      var isFolder = line.getAttribute('data-kind') === 'folder';
      Array.prototype.forEach.call(its.querySelectorAll('[data-act]'), function (b) {
        b.addEventListener('click', function () {
          if (b.getAttribute('data-act') === 'rename') {
            var name = line.querySelector('.oname');
            // A page's or a note's line says its title; the field holds the name it is filed under.
            if (name) { name.textContent = called; }
            editInPlace(name, 'The new name of ' + called, function (words, undo) {
              tell({ act: 'rename', doc: doc, name: words }, undo, again);
            });
            return;
          }
          confirmDelete(called, isFolder, function (close) {
            tell({ act: 'delete', doc: doc }, close, again);
          });
        });
      });
    });
    window.addEventListener('scroll', function () {
      lineMenus.forEach(function (show) { show(false); });
    }, { passive: true });
  }
})();
