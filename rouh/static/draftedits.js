/* Anatomy, Behaviour, Draft edits, at /anatomy/behaviour/draft-edits (`rouh/draft_edits.py`,
   `rouh/web/draftedits.py`).

   Petar, 16 October 2026 (mutation request 2): "We keep only the recording part of this
   feature. Don't modify responses. For now we will log changes ... this gene should be
   accessible somewhere and I should be able to click somewhere and see the logs".

   Every email Rouh drafted on a card that he changed before pressing Send, newest first: its
   subject, who it went to and when, then each place he changed it, what Rouh wrote over what
   he sent. The whole draft and the whole email are behind a section closed at the start, and
   the chat the card was in is a link. Older ones come a page at a time with Show older. Read
   only: nothing here changes anything.

   A section of Anatomy, drawn into `#draftEditsBody` from `/api/settings/draft-edits`. Anatomy
   tells it when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var D = { open: false, data: null, busy: false, error: '', seq: 0 };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function host() { return window.RouhHeartbeatHost || {}; }

  function get(before) {
    var seq = ++D.seq;
    D.busy = true;
    var url = '/api/settings/draft-edits' + (before ? '?before=' + encodeURIComponent(before) : '');
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== D.seq) return;
          D.busy = false;
          if (!r.ok) { D.error = (j && j.error) || 'The server said ' + r.status + '.'; draw(); return; }
          D.error = '';
          if (before && D.data) {
            D.data.edits = D.data.edits.concat(j.edits || []);
            D.data.more = !!j.more;
            D.data.total = j.total;
            D.data.on = j.on;
          } else D.data = j;
          draw();
        });
      })
      .catch(function () {
        if (seq !== D.seq) return;
        D.busy = false;
        D.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function when(at) {
    var d = new Date((at || 0) * 1000);
    try {
      return d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric',
                                           hour: '2-digit', minute: '2-digit' });
    } catch (err) { return d.toISOString(); }
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('draftEditsBody');
    if (!body || !D.open) return;
    body.setAttribute('aria-busy', D.busy ? 'true' : 'false');
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    if (D.error) {
      var say = el('p', 'hb-say bad', D.error);
      say.setAttribute('role', 'status');
      page.appendChild(say);
    }
    if (!D.data) {
      if (!D.error) page.appendChild(el('p', 'hb-empty', 'Reading your edits…'));
      return;
    }
    var d = D.data;
    var s = el('section', 'setting-card hb-card de-card');
    var h = el('h4', 'hb-h', 'Emails you changed before Send');
    if (d.total) h.appendChild(el('span', 'hb-h-sub', String(d.total)));
    s.appendChild(h);
    if (!d.on) s.appendChild(el('p', 'settings-help', 'Recording is off: nothing new is kept.'));
    if (!d.edits.length) {
      s.appendChild(el('p', 'hb-empty', 'None yet. An email Rouh drafts that you change before Send is kept here.'));
    } else {
      var list = el('ol', 'hb-list de-list');
      d.edits.forEach(function (e) { list.appendChild(row(e)); });
      s.appendChild(list);
    }
    if (d.more) {
      var more = el('button', 'ctl small de-more', D.busy ? 'Reading…' : 'Show older');
      more.type = 'button';
      more.disabled = D.busy;
      more.addEventListener('click', function () {
        var last = d.edits[d.edits.length - 1];
        if (last) { get(last.id); draw(); }
      });
      s.appendChild(more);
    }
    page.appendChild(s);
  }

  function row(e) {
    var li = el('li', 'hb-beat de-edit');
    li.id = 'de-' + e.id;
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what de-subject', e.subject || '(no subject)'));
    top.appendChild(el('span', 'hb-beat-nums', when(e.at)));
    li.appendChild(top);
    if (e.to) li.appendChild(el('div', 'de-to', 'To ' + e.to));
    var changes = el('ol', 'de-changes');
    (e.changes || []).forEach(function (c) { changes.appendChild(change(c)); });
    li.appendChild(changes);
    var foot = el('div', 'de-foot');
    if (e.drafted && e.sent && (e.drafted.body || e.sent.body)) foot.appendChild(whole(e));
    if (e.chat) {
      var href = '/chat/' + encodeURIComponent(e.chat);
      var a = el('a', 'hb-link de-chat', 'Open the chat');
      a.href = href;
      a.addEventListener('click', function (ev) {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
        ev.preventDefault();
        if (host().go) host().go(href); else location.href = href;
      });
      foot.appendChild(a);
    }
    if (foot.childNodes.length) li.appendChild(foot);
    return li;
  }

  function change(c) {
    var li = el('li', 'de-change');
    if (c.part === 'subject') li.appendChild(el('div', 'de-part', 'Subject'));
    var was = el('div', 'de-side de-was');
    was.appendChild(el('span', 'de-who', 'Rouh wrote'));
    was.appendChild(c.was ? el('del', 'de-text', c.was) : el('span', 'de-text de-none', 'nothing'));
    li.appendChild(was);
    var now = el('div', 'de-side de-now');
    now.appendChild(el('span', 'de-who', 'You sent'));
    now.appendChild(c.now ? el('ins', 'de-text', c.now) : el('span', 'de-text de-none', 'nothing, it was cut'));
    li.appendChild(now);
    return li;
  }

  function whole(e) {
    var box = el('details', 'de-whole');
    box.appendChild(el('summary', '', 'The whole email'));
    var two = el('div', 'de-two');
    [['Rouh’s draft', e.drafted], ['What was sent', e.sent]].forEach(function (pair) {
      var col = el('div', 'de-col');
      col.appendChild(el('div', 'de-who', pair[0]));
      var subject = pair[1].fields && pair[1].fields.subject;
      if (subject) col.appendChild(el('div', 'de-col-subject', subject));
      col.appendChild(el('div', 'de-body', pair[1].body || ''));
      two.appendChild(col);
    });
    box.appendChild(two);
    return box;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (D.open) return;
    D.open = true;
    D.error = '';
    draw();
    get(0);
  }

  function hiddenNow() { D.open = false; }

  window.RouhDraftEdits = { shown: shownNow, hidden: hiddenNow, reload: function () { return get(0); } };
})();
