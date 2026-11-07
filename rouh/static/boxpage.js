/* The box, at /box: somewhere to put words Rouh's model never sees
   (`rouh/boxes.py`, `rouh/web/boxes.py`).

   Petar, 13 October 2026: "When I am doing stuff I want to be able to say
   give me a box and save something there so LLM doesn't see it." So at the
   top is an empty box, a secret or an idea, to type or paste into; Save sends
   it over HTTP straight to the database, sealed, and never into the
   conversation. Under it every box he keeps, by its number, none of them
   opened ("they should have identification, maybe numbers so that I can tell
   the LLM which box to open when needed"): Show opens
   one on this page, Copy puts it on the clipboard (a secret with a name like
   STRIPE_SECRET_KEY also as the line for an env file), and Give to Rouh puts
   an idea into the message box, to send when he chooses. Saying "open box 3"
   to Rouh gives it that box, and the box says when it was given.

   What is in a box lives in this page's memory only while it is being typed
   or shown, and is never kept by the browser.

   The layer, its address and its row are app/runs.js's (`boxOpen`), handed
   over through `window.RouhBoxHost`. */
(function () {
  'use strict';

  var B = { open: false, data: null, error: '', said: '', loading: false, seq: 0,
            // The box being filled: its kind, its name and what is in it.
            kind: 'secret', label: '', draft: '', saving: false, peek: false,
            // Boxes opened on this page, by id, and the one just saved or asked to delete.
            shownIds: {}, flash: '', deleting: '', focus: '' };

  function host() { return window.RouhBoxHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text, run, title) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) { b.title = title; }
    b.addEventListener('click', run);
    return b;
  }
  function say(text, tone) {
    if (host().say) { host().say(text, tone || 'success'); }
  }

  /* ---- words ---- */

  function when(at) {
    var d = new Date(at * 1000);
    var same = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: same ? undefined : 'numeric',
                                         hour: '2-digit', minute: '2-digit' });
  }
  function counted(n, one, many) { return n === 1 ? '1 ' + one : n.toLocaleString() + ' ' + many; }
  function nameOf(b) { return b.label ? 'Box ' + b.number + ', “' + b.label + '”' : 'Box ' + b.number; }
  // A name that can stand on the left of an env file's line.
  function envName(b) { return /^[A-Za-z_][A-Za-z0-9_]*$/.test(b.label || '') ? b.label : ''; }
  function envLine(name, value) {
    if (/^[A-Za-z0-9_\-.,:/@+=]*$/.test(value)) { return name + '=' + value; }
    return name + '="' + value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
  }

  /* ---- reading and writing ---- */

  function ask(url, body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    if (body) {
      init.method = 'POST';
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('Sign in first.'); }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that. Try again in a moment.'); }
        return j;
      });
    }, function () { throw new Error('Rouh could not be reached. Try again in a moment.'); });
  }

  function load() {
    var seq = ++B.seq;
    B.loading = true;
    B.error = '';
    if (B.open) { draw(); }
    return ask('/api/box').then(function (j) {
      if (seq !== B.seq) { return; }
      B.loading = false;
      B.data = j;
      if (B.open) { draw(); findFocus(); }
    }, function (err) {
      if (seq !== B.seq) { return; }
      B.loading = false;
      B.error = err.message;
      if (B.open) { draw(); }
    });
  }

  // What is in one box, read only when he asks for it.
  function contentOf(id) {
    if (B.shownIds[id] != null) { return Promise.resolve(B.shownIds[id]); }
    return ask('/api/box/' + encodeURIComponent(id)).then(function (j) { return j.box.content; });
  }

  function save(form, saveBtn) {
    if (B.saving || !B.draft.trim()) { return; }
    B.saving = true;
    B.said = '';
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    ask('/api/box/new', { content: B.draft, label: B.label, kind: B.kind }).then(function (j) {
      B.saving = false;
      B.draft = '';
      B.label = '';
      B.peek = false;
      B.flash = String(j.box.id);
      say('Saved in the box. Rouh’s model cannot see what is in it.');
      return load();
    }, function (err) {
      B.saving = false;
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save in the box';
      var said = form.querySelector('.bx-error');
      if (!said) {
        said = el('p', 'bx-error');
        form.appendChild(said);
      }
      said.textContent = err.message;
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) { return navigator.clipboard.writeText(text); }
    return new Promise(function (ok, no) {
      var t = el('textarea', 'bx-offscreen');
      t.value = text;
      document.body.appendChild(t);
      t.select();
      var done = false;
      try { done = document.execCommand('copy'); } catch (e) { done = false; }
      t.remove();
      if (done) { ok(); } else { no(new Error('The browser would not copy it. Show it and copy it by hand.')); }
    });
  }

  /* ---- the box being filled ---- */

  function filler() {
    var form = el('form', 'bx-new');
    form.setAttribute('aria-label', 'A new box');
    var next = B.data ? (B.data.boxes || []).reduce(function (m, b) { return Math.max(m, b.number); }, 0) + 1 : 0;
    var h = el('h4', 'bx-new-h', 'New box');
    if (next) { h.appendChild(el('span', 'bx-next', 'it will be box ' + next)); }
    form.appendChild(h);
    form.appendChild(el('p', 'bx-lede', 'What you put here goes straight into Rouh’s database, sealed. ' +
      'Rouh’s model never sees it or its name, and nothing of it goes into the conversation.'));

    var kinds = el('div', 'bx-kinds');
    kinds.setAttribute('role', 'radiogroup');
    kinds.setAttribute('aria-label', 'What kind of box');
    [['secret', 'Secret', 'A password or a key, say for an env file'],
     ['idea', 'Idea', 'Held back until you give it to Rouh, so it cannot sway an answer']].forEach(function (k) {
      var b = button('bx-kind' + (B.kind === k[0] ? ' on' : ''), k[1], function () {
        if (B.kind === k[0]) { return; }
        B.kind = k[0];
        draw();
        var c = document.querySelector('#boxBody .bx-content');
        if (c) { c.focus(); }
      }, k[2]);
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', B.kind === k[0] ? 'true' : 'false');
      kinds.appendChild(b);
    });
    form.appendChild(kinds);

    var secret = B.kind === 'secret';
    var name = el('input', 'bx-in bx-name');
    name.type = 'text';
    name.maxLength = 120;
    name.value = B.label;
    name.autocomplete = 'off';
    name.spellcheck = false;
    name.placeholder = secret ? 'Name, like STRIPE_SECRET_KEY' : 'Name, if you like';
    name.setAttribute('aria-label', 'Its name');
    name.addEventListener('input', function () { B.label = name.value; });
    form.appendChild(name);

    var content = el('textarea', 'bx-in bx-content' + (secret && !B.peek ? ' is-masked' : ''));
    content.rows = secret ? 2 : 5;
    content.value = B.draft;
    content.placeholder = secret ? 'Paste the password or key' : 'Your idea, in your words';
    content.setAttribute('aria-label', 'What goes in the box');
    // Nothing of it to a spelling service, a password manager or the keyboard's suggestions.
    content.spellcheck = false;
    content.autocomplete = 'off';
    content.setAttribute('autocapitalize', 'off');
    content.setAttribute('autocorrect', 'off');
    content.setAttribute('data-lpignore', 'true');
    content.setAttribute('data-1p-ignore', '');
    content.addEventListener('input', function () {
      B.draft = content.value;
      saveBtn.disabled = !content.value.trim() || B.saving;
    });
    content.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(form, saveBtn); }
    });
    form.appendChild(content);

    var acts = el('div', 'bx-acts');
    var saveBtn = el('button', 'ctl bx-primary', B.saving ? 'Saving…' : 'Save in the box');
    saveBtn.type = 'submit';
    saveBtn.disabled = !B.draft.trim() || B.saving;
    saveBtn.title = 'Save it (Ctrl+Enter)';
    acts.appendChild(saveBtn);
    if (secret) {
      acts.appendChild(button('ctl small bx-peek', B.peek ? 'Hide what I typed' : 'Show what I typed', function () {
        B.peek = !B.peek;
        content.classList.toggle('is-masked', !B.peek);
        this.textContent = B.peek ? 'Hide what I typed' : 'Show what I typed';
      }));
    }
    form.appendChild(acts);
    form.addEventListener('submit', function (e) { e.preventDefault(); save(form, saveBtn); });
    return form;
  }

  /* ---- one kept box ---- */

  function row(b) {
    var id = String(b.id);
    var shown = B.shownIds[id] != null;
    var lit = B.flash === id || (B.focus && B.focus === String(b.number));
    var li = el('li', 'bx-card bx-' + b.kind + (lit ? ' bx-flash' : ''));
    li.id = 'box-' + b.number;
    var head = el('div', 'bx-head');
    var num = el('a', 'bx-num', String(b.number));
    num.href = '/box/' + b.number;
    num.title = 'Box ' + b.number + ': say “open box ' + b.number + '” to give it to Rouh';
    num.setAttribute('aria-label', 'Box ' + b.number);
    num.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey) { return; }
      e.preventDefault();
      if (host().focus) { host().focus(String(b.number)); }
    });
    head.appendChild(num);
    head.appendChild(el('h5', 'bx-title', b.label || 'Box ' + b.number));
    head.appendChild(el('span', 'bx-pill bx-pill-' + b.kind, b.kind_said));
    head.appendChild(el('span', 'bx-when', when(b.made_at)));
    li.appendChild(head);

    if (shown) {
      li.appendChild(el('pre', 'bx-open', B.shownIds[id]));
    } else {
      var masked = el('p', 'bx-masked');
      masked.appendChild(el('span', 'bx-dots', '••••••••••'));
      masked.appendChild(el('span', 'bx-size', counted(b.size, 'character', 'characters') + ', hidden'));
      li.appendChild(masked);
    }

    if (b.given_at) {
      var given = el('p', 'bx-given');
      given.appendChild(el('span', '', 'Given to Rouh ' + when(b.given_at)));
      if (b.given_chat) {
        given.appendChild(button('bx-link', 'In the chat', function () {
          if (host().go) { host().go('/chat/' + encodeURIComponent(b.given_chat)); }
        }, 'Open the conversation it was given in'));
      }
      li.appendChild(given);
    }

    // Its last hand-over to a job, as a file it never read aloud (rouh/boxes.py, for_job).
    if (b.used_at) {
      var used = el('p', 'bx-given bx-used');
      used.appendChild(el('span', '', 'Last used by a job ' + when(b.used_at) +
        (b.used_ended === 'shredded' ? ', and shredded when it ended' :
          b.used_ended === 'expired' ? ', never collected' : '')));
      if (b.used_run) {
        used.appendChild(button('bx-link', 'Open the job', function () {
          if (host().go) { host().go('/run/' + encodeURIComponent(b.used_run)); }
        }, 'Open the job it was handed to'));
      }
      li.appendChild(used);
    }

    var acts = el('div', 'bx-acts');
    acts.appendChild(button('ctl small', shown ? 'Hide' : 'Show', function (e) {
      var btn = e.currentTarget;
      if (shown) {
        delete B.shownIds[id];
        draw();
        return;
      }
      btn.disabled = true;
      contentOf(id).then(function (text) {
        B.shownIds[id] = text;
        draw();
      }, function (err) {
        btn.disabled = false;
        say(err.message, 'error');
      });
    }, shown ? 'Hide it again' : 'Show what is in it, here on your screen only'));
    acts.appendChild(button('ctl small', 'Copy', function () {
      contentOf(id).then(copyText).then(function () {
        say('Copied what is in ' + nameOf(b) + '.');
      }, function (err) { say(err.message, 'error'); });
    }, 'Copy what is in it'));
    var env = envName(b);
    if (b.kind === 'secret' && env) {
      acts.appendChild(button('ctl small', 'Copy as ' + env + '=…', function () {
        contentOf(id).then(function (text) { return copyText(envLine(env, text)); }).then(function () {
          say('Copied the line for an env file: ' + env + '=…');
        }, function (err) { say(err.message, 'error'); });
      }, 'Copy it as a line for an env file'));
    }
    if (b.kind === 'idea') {
      acts.appendChild(button('ctl small bx-give', 'Give to Rouh', function () {
        contentOf(id).then(function (text) {
          if (host().give) { host().give('From my ' + nameOf(b).replace(/^Box/, 'box') + ':\n\n' + text); }
        }, function (err) { say(err.message, 'error'); });
      }, 'Put it in the message box, to send to Rouh when you choose'));
    }
    if (B.deleting === id) {
      acts.appendChild(button('ctl small bx-delete is-sure', 'Delete for good', function (e) {
        var btn = e.currentTarget;
        btn.disabled = true;
        ask('/api/box/' + encodeURIComponent(id) + '/delete', {}).then(function () {
          B.deleting = '';
          delete B.shownIds[id];
          say(nameOf(b) + ' is deleted.');
          return load();
        }, function (err) {
          btn.disabled = false;
          say(err.message, 'error');
        });
      }, 'It cannot be brought back'));
      acts.appendChild(button('ctl small', 'Keep it', function () { B.deleting = ''; draw(); }));
    } else {
      acts.appendChild(button('ctl small bx-delete', 'Delete', function () { B.deleting = id; draw(); },
                              'Delete this box'));
    }
    li.appendChild(acts);
    return li;
  }

  /* ---- the page ---- */

  function draw() {
    var body = $('boxBody');
    var meta = $('boxMeta');
    if (!body) { return; }
    // What has focus in the box being filled keeps it while the page is drawn again.
    var active = document.activeElement;
    var refocus = active && body.contains(active) && active.classList.contains('bx-in')
      ? (active.classList.contains('bx-name') ? '.bx-name' : '.bx-content') : '';
    var caret = refocus ? [active.selectionStart, active.selectionEnd] : null;
    var scroll = body.scrollTop;
    body.setAttribute('aria-busy', B.loading ? 'true' : 'false');
    body.textContent = '';
    var page = el('div', 'bx-page');
    body.appendChild(page);
    var d = B.data;
    if (meta) { meta.textContent = d ? counted(d.count, 'box', 'boxes') + ' kept' : ''; }
    page.appendChild(filler());
    if (B.error) { page.appendChild(el('p', 'bx-error', B.error)); }
    if (d) {
      var list = d.boxes || [];
      var sec = el('section', 'bx-kept');
      sec.setAttribute('aria-label', 'Your boxes');
      sec.appendChild(el('h4', 'bx-h', 'Your boxes'));
      if (!list.length) {
        sec.appendChild(el('p', 'bx-empty', 'Nothing kept in a box yet. Say “give me a box” to Rouh ' +
          'whenever you want one, or fill the one above.'));
      } else {
        sec.appendChild(el('p', 'bx-hint', 'Rouh never sees what is in a box, or its name. To give it ' +
          'one, say its number: “open box ' + list[0].number + '”. To let a job use one without Rouh ' +
          'reading it, name the box, by number or name, when you ask for the job: it gets the box as a ' +
          'file, shredded when the job ends.'));
        var ul = el('ul', 'bx-list');
        list.forEach(function (b) { ul.appendChild(row(b)); });
        sec.appendChild(ul);
      }
      page.appendChild(sec);
    } else if (B.loading) {
      page.appendChild(el('p', 'bx-loading', 'Reading your boxes…'));
    }
    body.scrollTop = scroll;
    if (refocus) {
      var again = body.querySelector(refocus);
      if (again) {
        again.focus();
        try { again.setSelectionRange(caret[0], caret[1]); } catch (e) { /* not a text field */ }
      }
    }
  }

  // The box in focus, by its number, scrolled to and lit.
  function findFocus() {
    if (!B.focus) { return; }
    var node = document.getElementById('box-' + B.focus);
    if (node) { node.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  }

  // Opened, or asked for again: `fresh` is "give me a box", so the box to
  // fill is focused and in view; `focus` is one box's number, from /box/<n>.
  function shown(fresh, focus) {
    B.open = true;
    B.focus = fresh ? '' : String(focus || '');
    if (!B.data || !B.loading) { load(); }
    draw();
    if (fresh) {
      var body = $('boxBody');
      if (body) { body.scrollTop = 0; }
      setTimeout(function () {
        var c = document.querySelector('#boxBody .bx-content');
        if (c) { c.focus({ preventScroll: true }); }
      }, 0);
    } else if (B.focus) {
      findFocus();
    }
  }
  // Closed: nothing opened stays in the page's memory, and no delete is left half asked.
  function hidden() {
    B.open = false;
    B.shownIds = {};
    B.deleting = '';
    B.flash = '';
    B.focus = '';
    B.peek = false;
  }
  // A box saved, changed, deleted or given elsewhere: read again, keeping what is half written.
  function moved() {
    if (B.open && !B.saving) { load(); }
  }

  window.RouhBox = { shown: shown, hidden: hidden, moved: moved, reload: function () { return load(); } };

  var x = $('boxClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
