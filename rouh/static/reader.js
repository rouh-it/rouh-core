// One shared page, read by somebody who is not its owner (`rouh/web/guests.py`).
//
// The page is in a sandboxed frame with the Ask AI drawer in it, exactly as
// the owner's canvas frames it, and for the same reason it cannot call out:
// an origin of its own and `connect-src 'none'` (`rouh/pages.py`). So this
// page, which is Rouh's own, fetches the page's markup and puts it in the
// frame, and carries what the drawer asks for to the routes under this one
// token - the same arrangement `askRelay` in app.js is for the owner.
//
// What it carries is a short list and nothing else: the drawer's own few
// addresses, mapped onto this page's own routes. Which page it is about is
// never the frame's to say: the routes find it from the token in their own
// address.
(function () {
  'use strict';

  var BASE = JSON.parse(document.getElementById('readerBase').textContent || '""');
  // Where the page is inside a task shared to change, which every route of
  // it is asked with (`_for_guest` in guests.py); empty for one shared page.
  var atBox = document.getElementById('readerAt');
  var AT = atBox ? String(JSON.parse(atBox.textContent || '""') || '') : '';
  function addressed(to, ask) {
    var all = (ask || []).slice();
    if (AT) all.unshift('at=' + encodeURIComponent(AT));
    return BASE + to + (all.length ? '?' + all.join('&') : '');
  }
  var frame = document.getElementById('reader');
  var said = document.getElementById('readerSaid');
  var loads = 0;
  var sayTimer = null;
  // A comment thread to open, from the link in a letter that tagged this
  // person (`rouh/comments.py`). Only the first load asks for it: the page
  // sent again after a change keeps what the reader has open themselves.
  var comment = (function () {
    var found = /[?&]comment=(\d{1,12})(?:&|$)/.exec(location.search || '');
    return found ? Number(found[1]) : 0;
  })();

  function say(words) {
    if (!said) return;
    said.textContent = words || '';
    said.hidden = !words;
    clearTimeout(sayTimer);
    if (words) sayTimer = setTimeout(function () { said.hidden = true; }, 6000);
  }

  // A plain page in the frame, for when the shared one could not be read.
  function frameSays(words) {
    var esc = String(words).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    return '<!doctype html><meta charset="utf-8"><body style="margin:0;padding:24px;' +
      'color:#8d9aac;background:#0a0c10;font:15px/1.5 -apple-system,sans-serif">' + esc;
  }

  // Markup into the frame without a step in the tab's history, which is what
  // setting `srcdoc` on a frame that holds a page already can be in Safari:
  // Back after the page was sent again for a change would land on the old
  // one, which Safari draws empty and white. Out of the page and back in, the frame is a new browsing
  // context, and a context's first page replaces the blank it started with.
  // A name it has never had means a step the page inside did leave behind
  // names a frame that is gone (`frameWrite` in app.js, fr_08e89370f7c7).
  var written = 0;
  function write(html) {
    var parent = frame.parentNode, next = frame.nextSibling;
    written += 1;
    frame.name = 'rouh-reader-' + written;
    if (parent) parent.removeChild(frame);
    frame.srcdoc = html;
    if (parent) parent.insertBefore(frame, next);
  }

  // The page, into the frame. `thread` and `y` put the reader back where they
  // were when it is loaded again after a change: the topic open in the
  // drawer, and the page scrolled to where they were reading.
  function load(thread, y) {
    var mine = ++loads;
    var ask = [];
    if (thread > 0) ask.push('thread=' + encodeURIComponent(thread));
    if (y > 0) ask.push('y=' + Math.round(y));
    if (comment > 0) { ask.push('comment=' + comment); comment = 0; }
    fetch(addressed('page', ask), { credentials: 'same-origin' })
      .then(function (r) {
        return r.text().then(function (text) { return { ok: r.ok, status: r.status, text: text }; });
      })
      .catch(function () { return { ok: false, status: 0, text: '' }; })
      .then(function (got) {
        if (mine !== loads) return;
        if (got.ok) { write(got.text); return; }
        write(frameSays(got.status === 404
          ? 'This page is not shared here any more.'
          : 'The page could not be read' + (got.status ? ': the server said ' + got.status + '.' : '.')));
      });
  }

  // The drawer's own addresses, and where each one is answered for this page.
  var THREAD = /^\/api\/threads\/(\d+)$/;
  function route(path) {
    if (path === '/api/ask') return 'ask';
    if (path === '/api/threads') return 'threads';
    if (path === '/api/undo') return 'undo';
    // Text typed straight into the page (`askai.type_text`).
    if (path === '/api/type') return 'type';
    // Comments pinned to the page (`rouh/web/comments.py`), for a person the
    // page was shared with; a link has no such route and is answered 404.
    if (path === '/api/comments') return 'comments';
    // The highlights on it, everybody's (`rouh/web/highlights.py`).
    if (path === '/api/highlights') return 'highlights';
    // The passages explained in place on it (`rouh/web/definitions.py`).
    if (path === '/api/definitions') return 'definitions';
    // One of the page's options made the default, or no longer offered
    // (`rouh/pagehistory.py`). Its history is the owner's, so there is no
    // route here for that.
    if (path === '/api/option') return 'option';
    var one = THREAD.exec(path);
    return one ? 'threads/' + one[1] : '';
  }

  function tell(id, part) {
    part.type = 'rouh-page-answer';
    part.id = id;
    try { frame.contentWindow.postMessage(part, '*'); } catch (err) {}
  }

  // A refusal, in the drawer's own event shape, so it is a sentence in the
  // conversation rather than a status the drawer would call "not reachable".
  function trouble(id, words) {
    tell(id, { part: 'open', status: 200 });
    tell(id, { part: 'chunk',
               text: 'data: ' + JSON.stringify({ type: 'error', message: words }) + '\n\n' +
                     'data: ' + JSON.stringify({ type: 'done' }) + '\n\n' });
    tell(id, { part: 'end' });
  }

  function relay(m) {
    var path = String(m.path || '');
    var to = route(path);
    var asking = path === '/api/ask';
    if (!to) {
      tell(m.id, { part: 'open', status: 404 });
      tell(m.id, { part: 'end' });
      return;
    }
    var init = { credentials: 'same-origin', method: m.method === 'POST' ? 'POST' : 'GET' };
    if (init.method === 'POST') {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = typeof m.body === 'string' ? m.body : '{}';
    }
    fetch(addressed(to), init).then(function (r) {
      if (asking && !r.ok) {
        trouble(m.id, r.status === 401 || r.status === 403
          ? 'Your sign-in has run out. Reload the page and ask again.'
          : (r.status === 404 ? 'This page is not shared here any more.'
                              : 'That could not be answered: the server said ' + r.status + '.'));
        return;
      }
      tell(m.id, { part: 'open', status: r.status });
      if (!r.body) {
        return r.text().then(function (t) {
          tell(m.id, { part: 'chunk', text: t });
          tell(m.id, { part: 'end' });
        });
      }
      var reader = r.body.getReader(), dec = new TextDecoder();
      return (function pump() {
        return reader.read().then(function (got) {
          if (got.done) { tell(m.id, { part: 'end' }); return; }
          tell(m.id, { part: 'chunk', text: dec.decode(got.value, { stream: true }) });
          return pump();
        });
      })();
    }).catch(function () {
      if (asking) trouble(m.id, 'Rouh could not be reached. Check the connection and ask again.');
      else { tell(m.id, { part: 'open', status: 502 }); tell(m.id, { part: 'end' }); }
    });
  }

  window.addEventListener('message', function (e) {
    if (!frame || e.source !== frame.contentWindow) return;
    var m = e.data;
    if (!m || typeof m.type !== 'string') return;
    if (m.type === 'rouh-page-ask') { relay(m); return; }
    // The drawer changed the page, or put it back: the page is loaded again,
    // with the reader's topic still open and the page where they were.
    if (m.type === 'rouh-askai' && m.what === 'reload') {
      load(Number(m.thread) || 0, Number(m.y) || 0);
      return;
    }
    // A link inside the page to another page of the workspace. Only this one
    // page is shared, so there is nowhere for it to go, and that is said.
    // A link to another site opens in a tab of its own, which the sandboxed
    // page cannot do itself (`pages.follow_script`).
    if (m.type === 'rouh-page-follow' && m.out) {
      var went;
      try { went = new URL(String(m.href)); } catch (err) { return; }
      if (/^https?:$/.test(went.protocol) && went.origin !== location.origin) {
        window.open(went.href, '_blank', 'noopener,noreferrer');
      }
      return;
    }
    if (m.type === 'rouh-page-follow') {
      say('Only this page is shared, so that link does not open here.');
    }
  }, false);

  // C is "comment", as it is in Figma, pressed anywhere on this page: a key
  // pressed out here never reaches the page in the frame, so it is handed
  // down to it (`keys_script` in pages.py presses it there), and the frame
  // takes the keyboard with it. Shift+C shows or hides the comments. E is
  // Edit, pointing at the part of the page to change (`askai.js`), for a
  // reader who may change it; for anybody else the page ignores it. H is the
  // highlighter (`highlights.js`).
  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!/^[cCeEhH]$/.test(e.key)) return;
    var a = document.activeElement;
    if (a && (a === frame || a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))) return;
    if (!frame || !frame.contentWindow) return;
    e.preventDefault();
    try {
      frame.contentWindow.postMessage({ type: 'rouh-frame-key', key: e.key, shift: !!e.shiftKey }, '*');
    } catch (err) {}
    try { frame.focus(); } catch (err) {}
  }, false);

  load(0, 0);
})();
