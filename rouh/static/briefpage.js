/* The morning brief, at /brief (`rouh/morning_brief.py`).

   It opens with The one thing (fr_8435b9dc8732): the single task that makes
   today a win if nothing else happens, which Petar picks himself, a category,
   then a task in it, then a sub task if he wants one (`rouh/one_thing.py`).
   Rouh's own projects, tasks and steps are offered at each level, and he may
   type his own instead at any of them. It is today's only.

   The heading is today's date, short ("Tuesday, 29 Sept"), with only "made
   at 8:53" under it, then the greeting, and then the page, in the order Petar
   set on 29 and 30 September 2026 (fr_c01a16e51a05, fr_a2b5a77d76b3, then
   fr_1da7cddc045b): the weather first, at the very top; then the one thing;
   then the calendar for today and tomorrow and no further, read again from
   Google every time the page opens, today on a card of its own, each day
   saying so when it is empty, each event's start on his own clock and on the
   second one he picked, every event opening whole when pressed, with its
   description, who is invited and his answer to give; then his mail, one section for
   each mailbox he gave Rouh, its own Google connection and each one
   connected read-only, headed by its address (fr_dfce915c2c6d), with two
   tabs: Incoming, the unread mail in its Primary tab from the last day, and
   Ghosts, Waiting on others (task 71, fr_1007ecea9327), the emails he sent
   from it that asked for something and nobody answered, any of them opened
   and read whole in place by pressing anywhere on it; then Needs you in
   Slack, only when something there waits on him; then World News, the
   three most significant world stories; then AI, straight after it, as Petar
   asked on 1 October 2026 (fr_7f28a9cd0cc1): what his own AI channels on
   YouTube said, condensed into a few items that each name the channel and
   link to the video; then Reminders (fr_3c7faab7e0ce), yesterday's,
   today's and tomorrow's, today the biggest, as Birthdays are; then
   Today in history (fr_05fbc0c5754b): a few events of
   this date in past years, only for the topics he picks with the gear on
   its heading (fr_a1b47c17f8cf), the most significant first; then
   Birthdays (fr_d3ea4a374d50), yesterday's, today's and tomorrow's, today
   the biggest, each unlinked one with Link contact beside it. Each
   section names its source. A section whose source could not
   be reached says so in a line rather than being left to look empty. It
   closes with the daily doodle (fr_ddbb892590f8), a small sketch of today
   drawn from its calendar (`briefdoodle.js`), left out when there is none to
   draw, and after it a dad joke (fr_6fb4aad2f62c), one of r/dadjokes' most
   voted, word for word, left out when there is none.

   The server makes the brief every morning at the person's time and keeps
   it; this file only draws it, and asks for it to be brought up to date with
   Update. Opening it never makes it (fr_5fb00def9d2d, 8 October 2026: "when
   the morning brief is generated, let's save it in the database. And just
   show that"; fr_e7c51081dc50, 9 October 2026: "anytime I visit that page I
   see the last generated routine"): before today's is made it shows the
   newest one there is, saying whose day it is and when it was made, and with
   none at all it says so. Update reads every part again and the server does a
   model's work again only for what is new, then the page says which sections
   changed, or that nothing had, and marks each changed section Updated.
   What to raise at each meeting is made with the brief and kept on the
   meeting, so a meeting opens with it at once and the same every time.

   Every brief is kept, one a day, and the link at the bottom, All past
   briefs, lists them newest first at `/brief/past`; each opens at
   `/brief/<day>` exactly as it was made, with nothing in it read again. The layer,
   its address and its row in the sidebar are app.js's (`briefOpen`), handed
   over through `window.RouhBriefHost`, like the Control Room's. */
(function () {
  'use strict';

  var B = { open: false, data: null, busy: false, error: '', seq: 0, tick: 0, stale: false,
            // The server's today on this device's clock, and when the brief is
            // made by itself ({on, time}), as the last read of today's said.
            today: '', schedule: null,
            // Whether what is on its way is Update, rather than a read of what is kept.
            making: false,
            // Which brief is up: '' today's, 'past' the list of every one
            // kept, or a day (YYYY-MM-DD), that day's as it was kept.
            view: '',
            // The list of every brief kept, while `view` is 'past'.
            past: { busy: false, list: null, error: '', today: '' },
            // The calendar, read again from Google every time the brief is
            // opened (`calendarLoad`): whether it is being read, and what
            // came back this time, which wins over the kept brief's.
            cal: { busy: false, part: null, note: '', seq: 0 },
            // The one thing's picker, while it is open: which level it is at,
            // what is picked so far, and what Rouh offered.
            pick: null,
            // Today in history's topics, while the gear has them open in its box.
            topics: null,
            // The Slack line just dismissed, for its Undo: {part, one, at, text}, or a failure.
            slackSaid: null,
            // Owed to you (`rouh/owed_to_you.py`): which follow-ups are open, what is drafted or
            // typed in them, what each line was about once read, and the line said after Send or
            // It came, with its Undo.
            owed: { open: {}, text: {}, drafting: {}, about: {}, said: null },
            noNotes: { said: null },
            // Changed by others (`rouh/others_changed.py`): the line said after Seen, with Undo.
            othersChanged: { said: null },
            // Shared with you (`rouh/shared_with_you.py`): the line said after Add or Got it,
            // with Undo, and which task each line has picked.
            shared: { said: null, pick: {}, busy: '' },
            // Not opened yet (`rouh/not_opened.py`): the line said after Let it be, with Undo.
            notOpened: { said: null },
            // New comments on your documents (`rouh/new_comments.py`): the line said after Let it
            // be, with Undo.
            newComments: { said: null },
            // The deck for your talk (`rouh/talk_deck.py`): the line said after Let it be, with
            // Undo.
            talkDeck: { said: null },
            // Made, not handed over (`rouh/not_handed.py`): the line said after Handed over, with
            // Undo.
            notHanded: { said: null },
            // Dates your tasks wait on (`rouh/task_dates.py`): the line said after Done, with Undo.
            taskDates: { said: null },
            // Your word, by mail (`rouh/my_word.py`): the line said after Done, with Undo.
            myWord: { said: null },
            // Who lets the note-taker in (`rouh/host_admits.py`): the line said after No notes needed.
            hostAdmits: { said: null },
            // Flights left open (`rouh/flight_open.py`): the line said after Not needed, or a fault.
            flightOpen: { said: null },
            // Invitations not in your calendar (`rouh/invite_missing.py`): the line said after Not needed.
            inviteMissing: { said: null },
            // Meetings with nowhere to meet (`rouh/no_place.py`): the line said after Not needed.
            noPlace: { said: null },
            // Guests who have not said yes (`rouh/not_said_yes.py`): the line said after Not needed.
            notSaidYes: { said: null },
            // Invitations you have not answered (`rouh/not_answered.py`): the line said after an answer
            // or Not now, and which line is being answered.
            notAnswered: { said: null, busy: '' },
            // Gone quiet (`rouh/gone_quiet.py`): the line said after Not now, with Undo.
            goneQuiet: { said: null },
            // Agreed, not booked (`rouh/next_meeting.py`): the line said after Book it or Not
            // needed, with Undo for Not needed, and which line is being booked.
            nextMeeting: { said: null, busy: '' },
            // Waiting on others (task 71, `rouh/ghosts.py`): read on its own,
            // after the brief, from every mailbox the person gave Rouh.
            ghosts: { busy: false, data: null, error: '', seq: 0, open: {}, text: {},
                      shown: {}, said: {},
                      // Which tab each mailbox is on: Incoming, or Ghosts.
                      tab: {},
                      // The email open to be read, and the line to go back to.
                      reading: null, backTo: '' } };

  function host() { return window.RouhBriefHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  // A silo as the small chip app.css draws (`.silo-chip`, rouh/silos.py).
  function siloChip(c) {
    var chip = el('span', 'silo-chip bf-silo');
    if (/^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
    chip.appendChild(el('span', 'silo-dot'));
    chip.appendChild(el('span', 'silo-name', c.name || ''));
    return chip;
  }
  // A control that takes the person somewhere in Rouh: a link to that
  // address, so Cmd-click and Open link in new tab open it in a tab of its
  // own. A plain press is left to its own handler by the page around this
  // (`data-inapp`, app/helpers.js).
  function goLink(a, href) {
    a.href = href;
    a.setAttribute('data-inapp', '');
    return a;
  }
  function out(href, cls, text, title) {
    var a = el('a', cls, text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    if (title) a.title = title;
    return a;
  }
  // Open in Gmail. Petar, 30 September 2026 (fr_3f75a6f114eb): on a phone
  // it is the Gmail app, at the email, in the account that holds it, named by
  // something that is the account's own and never by a number, because he
  // has several accounts signed in; on a computer it is Gmail on the web, in
  // that account (`authuser`, `ghosts.link_to`), in a tab of its own.
  //
  // The phone's link is Google's own (`ghosts.app_link`): a gmail.app.goo.gl
  // address with the email's Message-ID and the account's Google id in it,
  // as the Gmail app makes it itself. The app claims that address on an
  // iPhone and on Android; a browser is sent on to Gmail on the web. The
  // googlegmail:///cv= links tried before were refused by the app, every
  // form of them ("Unable to understand the link"), and a timer that sent
  // Rouh's own page to the web took it away from him (b02b134). An email
  // with no Message-ID on file yet, from a look made before there was one,
  // keeps the web link until the mailbox is looked at again. Followed in a
  // new tab from his iPhone, Google's link opened the browser and not the app
  // (fr_3f75a6f114eb, 30 September 2026), so it is not yet known what does.
  //
  // `/brief?gmailtest=1` (kept for the tab; `=0` puts it away) lists, under
  // each email, ways of asking the Gmail app for the conversation itself, each
  // saying what it tries, for Petar to tap on his own phone. Every search form
  // (rfc822msgid, in Google's link or the app's scheme) was refused on his
  // iPhone, and he wants the conversation, not a search.
  var GMAIL_TEST = (function () {
    var said = /[?&]gmailtest=([01])\b/.exec(location.search);
    try {
      if (said) sessionStorage.setItem('rouh.gmailtest', said[1]);
      return sessionStorage.getItem('rouh.gmailtest') === '1';
    } catch (err) { return !!said && said[1] === '1'; }
  })();
  function phone() {
    var ua = navigator.userAgent || '';
    return /Android|iPhone|iPad|iPod/.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }
  function gmailTries(one, m) {
    // Gmail's own address of one conversation, as the Gmail app makes it
    // (`https://mail.google.com/mail/u/<account>/#all/%23thread-f:<n>|msg-f:<n>`,
    // the ids in decimal), in the account named by its address.
    var dec = function (hex) {
      return /^[0-9a-f]{1,16}$/i.test(hex || '') && window.BigInt ? BigInt('0x' + hex).toString() : '';
    };
    var tf = dec(one.thread_id), mf = dec(one.message_id);
    var who = encodeURIComponent(m.email);
    var og = m.account ? '&ogid=' + encodeURIComponent(m.account) : '';
    var google = function (inner) {
      return 'https://gmail.app.goo.gl/?link=' + encodeURIComponent(inner) + og + '&apn=com.google.android.gm';
    };
    var scheme = function (inner) { return 'googlegmail://' + inner.replace(/^https:\/\//, ''); };
    var byF = tf ? 'https://mail.google.com/mail/u/' + who + '/#all/%23thread-f:' + tf +
      (mf ? '%7Cmsg-f:' + mf : '') : '';
    var byHex = 'https://mail.google.com/mail/u/' + who + '/#all/' + encodeURIComponent(one.thread_id);
    var byF0 = tf ? 'https://mail.google.com/mail/u/0/#all/%23thread-f:' + tf +
      (mf ? '%7Cmsg-f:' + mf : '') : '';
    var out = [];
    if (byF) out.push(['Google\u2019s app link to the conversation (thread-f id)', google(byF), true]);
    out.push(['Google\u2019s app link to the conversation (its short id)', google(byHex), true]);
    if (byF0) out.push(['Google\u2019s app link, account by Google id only', google(byF0), true]);
    if (byF) out.push(['the app\u2019s scheme to the conversation (thread-f id)', scheme(byF), true]);
    out.push(['the app\u2019s scheme to the conversation (its short id)', scheme(byHex), true]);
    if (byF) out.push(['the plain Gmail address of the conversation', byF, false]);
    out.push(['the Gmail app alone', 'googlegmail://', true]);
    return out;
  }
  function gmailOut(one, m) {
    var a = out(one.link, 'bf-btn', 'Open in Gmail', 'Open the conversation in Gmail as ' + m.email);
    if (phone() && one.app_link) {
      a.href = one.app_link;
      a.title = 'Open the email in the Gmail app, as ' + m.email;
    }
    if (!GMAIL_TEST || !one.app_link) return a;
    var both = document.createDocumentFragment();
    both.appendChild(a);
    var tries = el('ol', 'bf-gmail-try');
    gmailTries(one, m).forEach(function (t) {
      var li = el('li');
      var b = el('a', null, t[0]);
      b.href = t[1];
      if (!t[2]) { b.target = '_blank'; b.rel = 'noopener noreferrer'; }
      li.appendChild(b);
      li.appendChild(el('code', null, t[1]));
      tries.appendChild(li);
    });
    both.appendChild(tries);
    return both;
  }
  function clock(t) {
    var d = new Date(t * 1000);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  // A moment on another clock: "14:00", and the day when it is not the same
  // day there ("10:00 Thu").
  function clockIn(t, zone) {
    try {
      return new Date(t * 1000).toLocaleTimeString('en-GB', {
        timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    } catch (err) { return ''; }
  }
  // The day a moment falls on there, when it is not the day it is here.
  function otherDay(t, zone) {
    try {
      var at = new Date(t * 1000);
      var day = at.toLocaleDateString('en-GB', { timeZone: zone, weekday: 'short' });
      var here = at.toLocaleDateString('en-GB', {
        timeZone: (B.data && B.data.zone) || undefined, weekday: 'short' });
      return day !== here ? day : '';
    } catch (err) { return ''; }
  }
  function city(zone) { return String(zone || '').split('/').pop().replace(/_/g, ' '); }
  // Today's date the way Petar wrote it: "Tuesday, 29 Sept".
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'June', 'July', 'Aug', 'Sept', 'Oct',
                'Nov', 'Dec'];
  var WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  function shortDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    if (!m) return '';
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return WEEKDAYS[d.getUTCDay()] + ', ' + d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()];
  }
  // A day's date alone: "19 Oct".
  function dayDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? +m[3] + ' ' + MONTHS[+m[2] - 1] : '';
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  // Middle dots between the parts of a line that are there.
  function dotted(parent, parts) {
    parts.filter(Boolean).forEach(function (part, i) {
      if (i) parent.appendChild(el('span', 'bf-dot', '·'));
      parent.appendChild(typeof part === 'string' ? el('span', null, part) : part);
    });
    return parent;
  }

  // Words with the addresses in them made into links that open elsewhere.
  var ADDRESS = /\bhttps?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]]/g;
  function linked(parent, text) {
    var at = 0;
    String(text || '').replace(ADDRESS, function (url, i) {
      if (i > at) parent.appendChild(document.createTextNode(text.slice(at, i)));
      parent.appendChild(out(url, 'bf-inlink', url));
      at = i + url.length;
      return url;
    });
    if (at < text.length) parent.appendChild(document.createTextNode(text.slice(at)));
    return parent;
  }
  // No run of empty lines longer than one, and none at either end.
  function tidyWords(text) {
    return String(text || '').replace(/\r\n?/g, '\n').replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n').trim();
  }

  /* ------------------------------------------------------------ reading */

  function ask(method, url) {
    var seq = ++B.seq;
    B.busy = true;
    B.making = method === 'POST';
    B.error = '';
    draw();
    fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                 headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone() },
                 body: method === 'POST' ? '{}' : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== B.seq) return;
          B.busy = false;
          if (r.ok && j && j.today) B.today = j.today;
          if (r.ok && j && j.schedule) B.schedule = j.schedule;
          if (r.ok && j && j.brief) {
            B.data = j.brief;
            // Read again since this brief was kept, so it is the one to show.
            if (B.cal.part && !B.view && !older()) B.data.calendar = B.cal.part;
          }
          // Today's, and there has never been one: said so (`drawNone`).
          else if (r.ok && j && j.ok && !B.view) B.data = null;
          else B.error = (j && j.error) || (B.view ? 'That brief could not be read'
            : B.making ? 'The brief could not be made' : 'The brief could not be read') +
            ' (the server said ' + r.status + ').';
          draw();
        });
      })
      .catch(function () {
        if (seq !== B.seq) return;
        B.busy = false;
        B.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  /* The brief is read on this device's clock, the one its calendar shows. */
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }

  function load() { ask('GET', '/api/brief'); ghostsLoad(false); }

  // Whether what is up is a brief as it was kept on another day, or the list
  // of them, rather than today's: nothing in it is read again or changed.
  function keptOnly() { return !!B.view; }

  // Whether today's brief is up but is not made yet, so the newest one there
  // is is shown in its place, exactly as it was kept: its calendar is not read
  // again, because its Today is its own day's.
  function older() { return !B.view && !!B.data && !!B.today && B.data.day !== B.today; }

  // A link to another of the briefs: '' today's, 'past' the list, or a day.
  function briefLink(view, cls, text) {
    var a = goLink(el('a', cls, text), '/brief' + (view ? '/' + view : ''));
    a.addEventListener('click', function (e) {
      e.preventDefault();
      if (host().show) host().show(view);
    });
    return a;
  }

  /* Every brief kept, newest first (`GET /api/brief/past`). */
  function pastLoad() {
    var seq = ++B.seq;
    B.past.busy = true;
    B.past.error = '';
    draw();
    fetch('/api/brief/past', { credentials: 'same-origin', cache: 'no-store',
                               headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== B.seq) return;
          B.past.busy = false;
          if (r.ok && j && j.briefs) { B.past.list = j.briefs; B.past.today = j.today || ''; }
          else B.past.error = (j && j.error) || 'The past briefs could not be read (the server said ' +
            r.status + ').';
          draw();
        });
      })
      .catch(function () {
        if (seq !== B.seq) return;
        B.past.busy = false;
        B.past.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function drawPast(body) {
    // Its name is the layer's heading, and "newest first" is under it (`meta`).
    var sec = el('section', 'bf-sec bf-kept');
    sec.setAttribute('aria-label', 'Past briefs');
    var list = B.past.list;
    if (B.past.error) sec.appendChild(el('p', 'bf-say bad', B.past.error));
    else if (!list) sec.appendChild(el('p', 'bf-note', 'Reading the briefs kept…'));
    else if (!list.length) sec.appendChild(el('p', 'bf-empty', 'No brief has been kept yet.'));
    else {
      var ul = el('ul', 'bf-kept-list');
      list.forEach(function (one) {
        var li = el('li');
        var a = briefLink(one.today ? '' : one.day, 'bf-kept-row', null);
        a.appendChild(el('span', 'bf-kept-day', one.words));
        if (one.today) a.appendChild(el('span', 'bf-kept-today', 'Today'));
        a.appendChild(el('span', 'bf-kept-made', 'made at ' + clock(one.made_at)));
        li.appendChild(a);
        ul.appendChild(li);
      });
      sec.appendChild(ul);
    }
    body.appendChild(sec);
    var f = el('footer', 'bf-foot');
    f.appendChild(briefLink('', 'bf-settings', 'Today’s brief'));
    body.appendChild(f);
  }

  /* The calendar read again from Google, every time the brief is opened
     (fr_854ef3f9eb57: "every time I open this page, the calendar refreshes"),
     with a small spinner in the calendar's top right corner while it is. Only
     the calendar's own section is drawn again when it comes, so nothing being
     typed or read anywhere else on the page moves. */
  function calendarLoad() {
    var seq = ++B.cal.seq;
    B.cal.busy = true;
    B.cal.part = null;
    B.cal.note = '';
    calendarRedraw();
    var done = function (part, note) {
      if (seq !== B.cal.seq || keptOnly()) return;
      B.cal.busy = false;
      if (older()) { calendarRedraw(); return; }
      if (part && part.ok) {
        B.cal.part = part;
        if (B.data) B.data.calendar = part;
      } else if (B.data && B.data.calendar && B.data.calendar.ok) {
        // What was kept stays, with a word that it is not the latest.
        B.cal.note = 'Not read again just now: ' + (note || 'Google could not be reached.');
      } else if (part && B.data) B.data.calendar = part;
      calendarRedraw();
    };
    fetch('/api/brief/calendar', { credentials: 'same-origin', cache: 'no-store',
                                   headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          done(j && j.calendar, (j && j.calendar && j.calendar.note) || (j && j.error));
        });
      })
      .catch(function () { done(null, 'Rouh could not be reached.'); });
  }

  // The calendar's section alone, drawn again where it is.
  function calendarRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-calendar');
    if (!old || !B.data) return;
    var holder = document.createDocumentFragment();
    drawCalendar(holder, B.data.calendar, Date.now() / 1000);
    old.replaceWith(holder);
  }
  // Update: every part read again, and only what is new worked out again.
  function remake() {
    if (B.busy || keptOnly()) return;
    ask('POST', '/api/brief/make');
    ghostsLoad(true);
  }

  /* ------------------------------------------------------------ drawing */

  // Each section's icon before its name, so it is known at a glance (Petar, 19 October 2026,
  // fr_6d5b2ccbf194: "slack icon for visual recognition of this category, calendar for the
  // calendar category, email icon for the emails, etc for every section"). Outlines on a
  // 24 pixel grid in the colour of the words, drawn as menu.js draws its own.
  var SECTION_ICONS = {
    weather: '<circle cx="8.5" cy="8.5" r="3"/><path d="M8.5 2.5v1.2M3.7 4.3l.9.9M2.5 9h1.2M13.3 4.3l-.9.9"/>'
      + '<path d="M9 20h9a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.4 1.4A2.8 2.8 0 0 0 9 20z"/>',
    one: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>'
      + '<path d="M8 14h2M14 14h2M8 17h2"/>',
    mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3.5 7l8.5 6.5L20.5 7"/>',
    // Slack's own mark, its four bars turning round the middle.
    slack: '<rect x="9" y="2.5" width="3" height="9.5" rx="1.5"/><rect x="12" y="9" width="9.5" height="3" rx="1.5"/>'
      + '<rect x="12" y="12" width="3" height="9.5" rx="1.5"/><rect x="2.5" y="12" width="9.5" height="3" rx="1.5"/>',
    // Owed to you: a tray with something coming into it.
    owed: '<path d="M3.5 13.5h4l1.5 3h6l1.5-3h4"/><path d="M3.5 13.5l2.5-7.5h12l2.5 7.5v5a1.5 1.5 0 0 1-1.5 1.5h-14a1.5 1.5 0 0 1-1.5-1.5z"/>'
      + '<path d="M12 3.5v7M9.5 8l2.5 2.5L14.5 8"/>',
    // Meetings with no notes: a notepad with a line struck through it.
    no_notes: '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/>'
      + '<path d="M4 20L20 4"/>',
    // Changed by others: a page with a pencil over its corner.
    others_changed: '<path d="M6 3.5h8l4 4v6"/><path d="M6 3.5a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h5"/>'
      + '<path d="M8.5 9.5h6M8.5 13h4"/><path d="M14 20.5l.6-2.6 5.2-5.2a1.4 1.4 0 0 1 2 2l-5.2 5.2z"/>',
    // Shared with you: a page with an arrow coming in to it.
    shared_with_you: '<path d="M8 3.5h6l4 4v12a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-3"/><path d="M14 3.5v4h4"/>'
      + '<path d="M2.5 12.5h8M8 9.5l3 3-3 3"/>',
    // Not opened yet: an eye with a line through it.
    not_opened: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/>'
      + '<circle cx="12" cy="12" r="2.5"/><path d="M4 20L20 4"/>',
    // New comments on your documents: a speech bubble on a page.
    new_comments: '<path d="M6 3.5h8l4 4v4"/><path d="M6 3.5a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h4"/>'
      + '<path d="M13 13.5h8v5.5h-4.5l-2.5 2v-2h-1z"/>',
    // The deck for your talk: a screen on its stand.
    talk_deck: '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M12 16v4M8 20.5h8M7 9h6M7 12h9"/>',
    not_handed: '<path d="M4 12h11M11 8l4 4-4 4"/><path d="M15 5h3a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-3"/>',
    // Dates your tasks wait on: a calendar page with a clock's hand.
    task_dates: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 9.5h16M8.5 3v4M15.5 3v4"/>'
      + '<path d="M12 12v3.2l2.2 1.4"/>',
    // Your word, by mail: an envelope with a tick for a promise kept.
    my_word: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 8l9 6 9-6"/><path d="M15 3.5l2 2 3.5-3.5"/>',
    host_admits: '<rect x="3" y="6" width="12" height="12" rx="2"/><path d="M15 10l5-3v10l-5-3"/><path d="M7 12h4"/>',
    flight_open: '<path d="M2.5 19h19"/><path d="M3.5 13.5l3 1.2 4-1.6-5.2-5.4 2-.8 7.6 4.2 4.4-1.8c1.1-.4 2.2.3 2 1.2-.1.6-.6 1-1.2 1.3L6.9 17.1 3.5 13.5z"/>',
    // Invitations not in your calendar: an envelope with a calendar's two rings.
    invite_missing: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M3 9l9 6 9-6"/><path d="M8 4v4M16 4v4"/>',
    // Meetings with nowhere to meet: a map pin with a question in it.
    no_place: '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><path d="M10.2 8.6a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.4"/><path d="M12 13.9v.1"/>',
    // Invitations you have not answered: an envelope with a question mark beside it.
    not_answered: '<rect x="2.5" y="6" width="13" height="11" rx="2"/><path d="M2.5 8l6.5 4.5L15.5 8"/>'
      + '<path d="M18 7.4a2.2 2.2 0 1 1 3.2 2c-.6.3-.9.7-.9 1.3v.4"/><path d="M20.3 14v.1"/>',
    // Gone quiet: two people, the second faded.
    gone_quiet: '<circle cx="8" cy="8" r="3.2"/><path d="M2.5 19c.5-3.3 2.8-5.5 5.5-5.5s5 2.2 5.5 5.5"/>'
      + '<circle cx="17" cy="9" r="2.6" stroke-dasharray="2 2"/><path d="M15.5 14.2c2.6.2 4.6 2.2 5 4.8" stroke-dasharray="2 2"/>',
    // Guests who have not said yes: a person with a question mark beside them.
    not_said_yes: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-6 6.5-6s5.9 2.4 6.5 6"/>'
      + '<path d="M16.6 6.4a2.2 2.2 0 1 1 3.2 2c-.6.3-.9.7-.9 1.3v.4"/><path d="M18.9 13v.1"/>',
    // Agreed, not booked: a calendar page with a plus where the day should be.
    next_meeting: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 9.5h16M8.5 3v4M15.5 3v4"/>'
      + '<path d="M12 12.5v5M9.5 15h5"/>',
    world: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>'
      + '<path d="M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5s1.1-6.1 3.4-8.5z"/>',
    ai: '<path d="M10 3.5l1.7 4.8 4.8 1.7-4.8 1.7L10 16.5l-1.7-4.8L3.5 10l4.8-1.7z"/>'
      + '<path d="M17.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    reminders: '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 2.5"/><path d="M4.5 5.5l2.5-2M19.5 5.5l-2.5-2"/>',
    report: '<path d="M4 20.5h16"/><rect x="5.5" y="12" width="3" height="6" rx=".5"/>'
      + '<rect x="10.5" y="7" width="3" height="11" rx=".5"/><rect x="15.5" y="9.5" width="3" height="8.5" rx=".5"/>',
    // Today in history: an hourglass.
    history: '<path d="M6.5 3.5h11M6.5 20.5h11"/><path d="M7.5 3.5c0 4.5 4.5 5.5 4.5 8.5s-4.5 4-4.5 8.5"/>'
      + '<path d="M16.5 3.5c0 4.5-4.5 5.5-4.5 8.5s4.5 4 4.5 8.5"/>',
    doodle: '<path d="M4 20l1-4L16 5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/>',
    birthdays: '<path d="M4.5 20.5h15v-7a1.5 1.5 0 0 0-1.5-1.5H6a1.5 1.5 0 0 0-1.5 1.5z"/>'
      + '<path d="M4.5 16c1.3 1 2.5 1 3.8 0s2.5-1 3.7 0 2.5 1 3.8 0 2.4-1 3.7 0"/>'
      + '<path d="M12 12V8.5"/><path d="M12 3.5c1 1.2 1.2 2.3 0 3.5-1.2-1.2-1-2.3 0-3.5z"/>',
    // The dad joke: a face, grinning.
    joke: '<circle cx="12" cy="12" r="8.5"/><path d="M8 14c1 1.8 2.4 2.7 4 2.7s3-.9 4-2.7z"/>'
      + '<path d="M8.5 9.5h.01M15.5 9.5h.01"/>'
  };
  function headIcon(key) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('class', 'bf-h-ic');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('width', '16');
    s.setAttribute('height', '16');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.7');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.innerHTML = SECTION_ICONS[key] || '';
    return s;
  }

  // `bare` leaves out the source in the top right corner, for a section that
  // has something else there.
  function section(key, title, part, sub, bare) {
    var sec = el('section', 'bf-sec bf-' + key);
    sec.setAttribute('aria-label', title);
    var h = el('h4', 'bf-h');
    if (SECTION_ICONS[key]) h.appendChild(headIcon(key));
    h.appendChild(el('span', 'bf-h-name', title));
    if (sub) h.appendChild(el('span', 'bf-h-sub', sub));
    if (updated(key)) h.appendChild(el('span', 'bf-h-new', 'Updated'));
    if (part && part.source && !bare) h.appendChild(el('span', 'bf-src', part.source));
    sec.appendChild(h);
    if (part && !part.ok) sec.appendChild(el('p', 'bf-note', part.note || 'Not available.'));
    return sec;
  }

  // The second time zone picked in Settings, when it is not the clock the
  // brief is already on.
  function secondZone() {
    var d = B.data;
    if (!d || !d.second_zone || d.second_zone === d.zone) return '';
    return d.second_zone;
  }

  // An event's time on the second clock: "Lisbon 14:00-15:00".
  function altSpan(one) {
    var zone = secondZone();
    if (!zone || one.all_day || !one.starts_at) return null;
    var day = otherDay(one.starts_at, zone);
    var words = city(zone) + ' ' + clockIn(one.starts_at, zone) +
      (one.ends_at ? '–' + clockIn(one.ends_at, zone) : '') + (day ? ' ' + day : '');
    var span = el('span', 'bf-alt', words);
    span.title = 'On ' + zone.replace(/_/g, ' ') + ' time';
    return span;
  }

  var RESPONSE_WORDS = { accepted: 'Going', declined: 'Not going', tentative: 'Maybe',
                         needsAction: 'Not answered yet' };

  /* ---- the two days, side by side (fr_c997039d8d22) */

  // Today and tomorrow as two columns on one grid of hours, the way Google
  // Calendar's two-day view on his phone draws them: an event's height is
  // how long it is, ones that overlap share their hour side by side, and a
  // line marks now (fr_c997039d8d22: "Instead of list view, can you give me
  // 2 day view"). All-day events sit in a row above the hours.

  var GRID_HOUR = 48;   // pixels an hour is tall
  var GRID_FIRST = 8, GRID_LAST = 20;   // the hours always shown, widened to fit

  // The grid is drawn by the clock on the wall, never by seconds counted from
  // midnight: on the day the clocks go back a day is 25 hours long, so 9:00
  // is ten hours after midnight, and counting them drew now and every event
  // after the change an hour late (fr_6bb943668ce5). Each moment is read on
  // the zone's own clock, with the offset of that moment, wherever it is.
  var WALLS = {};
  function wallFormat(zone) {
    var key = zone || '';
    if (!WALLS[key]) {
      WALLS[key] = new Intl.DateTimeFormat('en-GB', { timeZone: zone || undefined, hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
        second: '2-digit' });
    }
    return WALLS[key];
  }

  // A moment, in seconds, as the clock there reads it, counted as if it were UTC.
  function wallOf(t, zone) {
    var parts = {};
    wallFormat(zone).formatToParts(new Date(t * 1000))
      .forEach(function (p) { parts[p.type] = +p.value; });
    return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour % 24, parts.minute,
                    parts.second) / 1000;
  }

  // A YYYY-MM-DD as seconds, as if it were midnight UTC, or null.
  function isoDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) / 1000 : null;
  }

  // Where a moment sits on a day's grid: the hour the clock there shows,
  // counted from that day's midnight, so the next day's 01:00 is 25.
  function hourOn(t, iso, zone) {
    try { return (wallOf(t, zone) - isoDay(iso)) / 3600; }
    catch (err) { return (t - isoDay(iso)) / 3600; }
  }

  // The moment the clock there shows an hour of a day, in seconds.
  function momentAt(iso, hour, zone) {
    var want = isoDay(iso) + hour * 3600;
    try {
      var t = want - (wallOf(want, zone) - want);
      return want - (wallOf(t, zone) - t);
    } catch (err) { return want; }
  }

  // Where a timed event sits on its day, in hours from midnight, cut to the day.
  function hoursOf(one, iso, zone) {
    var from = hourOn(one.starts_at, iso, zone);
    var to = one.ends_at ? hourOn(one.ends_at, iso, zone) : from + 0.5;
    from = Math.max(0, from);
    to = Math.min(24, Math.max(to, from + 0.25));
    return { from: from, to: to };
  }

  // Where each event goes across its column, the way Google lays them out:
  // ones that start within NEAR hours of each other share the width side by
  // side, and one that starts later during a longer one is drawn over it, a
  // little in from its left edge, so the long one stays readable beside it.
  var NEAR = 0.75, INDENT = 12;   // hours, pixels

  function lanes(placed) {
    placed.sort(function (x, y) { return x.from - y.from || y.to - x.to; });
    var groups = [];
    placed.forEach(function (p) {
      var running = placed.filter(function (q) { return q.group && q.to > p.from; });
      var over = running.filter(function (q) { return p.from - q.from >= NEAR; });
      var parent = over.reduce(function (best, q) {
        return !best || q.depth > best.depth || (q.depth === best.depth && q.from > best.from) ? q : best;
      }, null);
      p.depth = parent ? parent.depth + 1 : 0;
      p.parent = parent;
      var group = groups.find(function (g) {
        return g.parent === parent && g.members.some(function (q) {
          return q.to > p.from && p.from - q.from < NEAR;
        });
      });
      if (!group) {
        group = parent ? { parent: parent, l: parent.l + parent.w * parent.i / parent.group.members.length,
                           w: parent.w / parent.group.members.length, off: parent.off + INDENT, members: [] }
                       : { parent: null, l: 0, w: 1, off: 0, members: [] };
        groups.push(group);
      }
      p.group = group;
      p.i = group.members.length;
      p.l = group.l; p.w = group.w; p.off = group.off;
      group.members.push(p);
    });
    return placed;
  }

  // An event's left edge and width on its column, as CSS.
  function across(p) {
    var n = p.group.members.length;
    var span = '(' + (p.w * 100) + '% - ' + p.off + 'px)';
    return { left: 'calc(' + (p.l * 100) + '% + ' + p.off + 'px + ' + span + ' * ' + (p.i / n) + ' + 1px)',
             width: 'calc(' + span + ' / ' + n + ' - 3px)' };
  }

  // One event on the grid, or in the all-day row: a press opens it whole.
  function block(one, now, cls) {
    var b = el('button', cls);
    b.type = 'button';
    b.dataset.ev = evKey(one);
    b.setAttribute('aria-haspopup', 'dialog');
    if (one.ends_at && one.ends_at <= now) b.classList.add('past');
    else if (one.starts_at && one.starts_at <= now) b.classList.add('now');
    if (one.response === 'needsAction') b.classList.add('ask');
    if (one.response === 'tentative') b.classList.add('maybe');
    b.appendChild(el('span', 'bf-gb-title', one.title));
    var said = [one.all_day ? 'All day' : one.start + (one.end ? '–' + one.end : '')];
    if (one.response && one.response !== 'accepted' && RESPONSE_WORDS[one.response]) {
      said.push(RESPONSE_WORDS[one.response]);
    }
    if (!one.all_day) b.appendChild(el('span', 'bf-gb-time', said.join(' · ')));
    if (one.where && !one.all_day) b.appendChild(el('span', 'bf-gb-where', one.where));
    b.title = [one.title, said.join(' · '), one.where].filter(Boolean).join('\n');
    b.addEventListener('click', function () { eventOpen(one, b); });
    return b;
  }

  function calendarGrid(sec, days, now) {
    var zone = B.data.zone, second = secondZone();
    days.forEach(function (d) {
      d.known = isoDay(d.iso) != null;
      d.timed = d.events.filter(function (one) { return !one.all_day && one.starts_at && d.known; });
      d.allday = d.events.filter(function (one) { return one.all_day || !d.known; });
    });
    // The hours shown: eight to eight, and wider for an event outside them.
    var first = GRID_FIRST, last = GRID_LAST;
    days.forEach(function (d) {
      d.timed.forEach(function (one) {
        var h = hoursOf(one, d.iso, zone);
        first = Math.min(first, Math.floor(h.from));
        last = Math.max(last, Math.ceil(h.to));
      });
    });
    var grid = el('div', 'bf-grid');
    grid.style.setProperty('--bf-hour', GRID_HOUR + 'px');
    grid.style.setProperty('--bf-hours', String(last - first));
    if (second) grid.classList.add('two-clocks');

    // The days' names, today's in the accent, as Google marks it.
    var head = el('div', 'bf-grid-row bf-grid-head');
    head.appendChild(el('span', 'bf-grid-gutter'));
    days.forEach(function (d) {
      var name = el('div', 'bf-grid-day bf-grid-day-' + d.key);
      name.appendChild(el('span', 'bf-grid-dayword', d.words));
      if (d.date) name.appendChild(el('span', 'bf-grid-date', d.date));
      head.appendChild(name);
    });
    grid.appendChild(head);

    // All day, above the hours, only when either day has one.
    if (days.some(function (d) { return d.allday.length; })) {
      var row = el('div', 'bf-grid-row bf-grid-allday');
      row.appendChild(el('span', 'bf-grid-gutter', 'All day'));
      days.forEach(function (d) {
        var cell = el('div', 'bf-grid-cell');
        d.allday.forEach(function (one) { cell.appendChild(block(one, now, 'bf-gb bf-gb-allday')); });
        row.appendChild(cell);
      });
      grid.appendChild(row);
    }

    var body = el('div', 'bf-grid-row bf-grid-body');
    var gutter = el('div', 'bf-grid-gutter bf-grid-hours');
    for (var h = first; h < last; h++) {
      var label = el('span', 'bf-grid-hour');
      label.style.top = ((h - first) * GRID_HOUR) + 'px';
      if (h > first) {
        label.appendChild(el('span', 'bf-grid-here', String(h).padStart(2, '0') + ':00'));
        if (second && days[0].known) {
          label.appendChild(el('span', 'bf-second', clockIn(momentAt(days[0].iso, h, zone), second)));
        }
      }
      gutter.appendChild(label);
    }
    if (second) gutter.title = 'Under each hour, the same hour in ' + city(second);
    body.appendChild(gutter);
    days.forEach(function (d) {
      var col = el('div', 'bf-grid-col bf-grid-col-' + d.key);
      col.setAttribute('role', 'group');
      col.setAttribute('aria-label', d.words);
      var placed = lanes(d.timed.map(function (one) {
        var at = hoursOf(one, d.iso, zone);
        return { one: one, from: at.from, to: at.to };
      }));
      placed.forEach(function (p) {
        var b = block(p.one, now, 'bf-gb');
        b.style.top = ((p.from - first) * GRID_HOUR) + 'px';
        b.style.height = Math.max(18, (p.to - p.from) * GRID_HOUR - 2) + 'px';
        var at = across(p);
        b.style.left = at.left;
        b.style.width = at.width;
        b.style.zIndex = String(1 + p.depth);
        if (p.depth) b.classList.add('over');
        if ((p.to - p.from) * GRID_HOUR < 34) b.classList.add('short');
        col.appendChild(b);
      });
      if (!d.events.length) col.appendChild(el('p', 'bf-grid-free', d.empty));
      // Now, as a line across today with a dot at its start.
      if (d.key === 'today' && d.own && d.known) {
        var at = hourOn(now, d.iso, zone);
        if (at >= first && at <= last) {
          var line = el('span', 'bf-grid-now');
          line.style.top = ((at - first) * GRID_HOUR) + 'px';
          line.setAttribute('aria-hidden', 'true');
          col.appendChild(line);
        }
      }
      body.appendChild(col);
    });
    grid.appendChild(body);
    sec.appendChild(grid);
  }

  // Text being selected with the mouse is not a press on the row it is in.
  function selecting() {
    var sel = window.getSelection && window.getSelection();
    return !!(sel && !sel.isCollapsed && String(sel).trim());
  }

  /* ---- one event, open (fr_1da7cddc045b) */

  // Pressed anywhere on its row, an event opens whole in a dialog over the
  // brief: when, where, the call, its description, who is invited and what
  // each said, and, when it is an invitation to this calendar, Going, Maybe
  // and Not going, which are sent to Google as the answer, the organiser
  // told, as pressing them in Google Calendar does. It opens at once with
  // what the brief kept and is read again from Google underneath, so the
  // answers are the ones there are now. Escape, Close or a press outside it
  // puts it away, and the keyboard goes back to the event it came from.

  var EV = { one: null, data: null, error: '', busy: '', said: null, seq: 0, back: null,
             prep: null, raise: null, fix: null };

  function evKey(one) { return one.calendar_id + ':' + one.id; }

  function eventOpen(one, from) {
    EV.one = one;
    EV.data = one;
    EV.error = '';
    EV.busy = '';
    EV.said = null;
    EV.back = from || null;
    EV.prep = null;
    EV.fixed = false;
    // What to raise, as it was made with the brief and kept on the meeting
    // (fr_5fb00def9d2d): drawn at once, the same every time, never asked for.
    EV.raise = one.raise || null;
    // A correction being written or made is this meeting's, and is still there
    // when the meeting is opened again; another meeting starts without one.
    if (EV.fix && EV.fix.key !== evKey(one)) EV.fix = null;
    var dlg = evDialog();
    evDraw();
    if (!dlg.open) dlg.showModal();
    var close = dlg.querySelector('.bf-dlg-x');
    if (close) close.focus({ preventScroll: true });
    if (!one.id || !one.calendar_id) return;
    var seq = ++EV.seq;
    // What to raise is asked for when there is none to draw, on a brief of
    // another day too: the server leaves off one that read nothing, because
    // mail with them may have come since (fr_a69ec60fb722, `redo_raise`).
    if (!one.raise) raiseLoad(one, seq);
    // Otherwise a brief of another day is shown as it was kept, and nothing is read again.
    if (keptOnly()) return;
    prepLoad(one, seq);
    fetch('/api/brief/event?calendar=' + encodeURIComponent(one.calendar_id) + '&event=' +
          encodeURIComponent(one.id), { credentials: 'same-origin', cache: 'no-store',
                                        headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== EV.seq || EV.one !== one) return;
          if (r.ok && j && j.event) { EV.data = j.event; evKeep(one, j.event); }
          else EV.error = (j && j.error) || 'It could not be read again from Google just now; ' +
            'this is what the brief had.';
          evDraw();
        });
      })
      .catch(function () {
        if (seq !== EV.seq || EV.one !== one) return;
        EV.error = 'Rouh could not be reached; this is what the brief had.';
        evDraw();
      });
  }

  // Before you meet (`rouh/meeting_prep.py`): for a meeting with people from
  // outside, who each of them is, from the contacts, and the last emails with
  // each, from every inbox Rouh can read. Asked for beside the event itself,
  // and drawn under its own heading once it comes; an event with nobody from
  // outside, or the feature switched off, draws nothing at all.
  function prepLoad(one, seq) {
    EV.prep = { busy: true };
    fetch('/api/brief/event/prep?calendar=' + encodeURIComponent(one.calendar_id) + '&event=' +
          encodeURIComponent(one.id), { credentials: 'same-origin', cache: 'no-store',
                                        headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== EV.seq || EV.one !== one) return;
          EV.prep = (r.ok && j && j.ok) ? j : { error: (j && j.error) ||
            'The note could not be made just now (the server said ' + r.status + ').' };
          evDraw();
        });
      })
      .catch(function () {
        if (seq !== EV.seq || EV.one !== one) return;
        EV.prep = { error: 'Rouh could not be reached for the note.' };
        evDraw();
      });
  }

  function prepWhen(at) {
    if (!at) return '';
    return new Date(at * 1000).toLocaleDateString('en-GB', {
      timeZone: (B.data && B.data.zone) || undefined, day: 'numeric', month: 'short',
      year: new Date(at * 1000).getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
  }

  function prepDraw(box) {
    var p = EV.prep;
    if (!p || p.off) return;
    if (p.busy) {
      var wait = el('div', 'bf-prep');
      wait.appendChild(el('h5', 'bf-h5', 'Before you meet'));
      wait.appendChild(el('p', 'bf-note', 'Looking up who is coming and the last emails with them…'));
      box.appendChild(wait);
      return;
    }
    if (p.error) {
      var bad = el('div', 'bf-prep');
      bad.appendChild(el('h5', 'bf-h5', 'Before you meet'));
      bad.appendChild(el('p', 'bf-note bad', p.error));
      box.appendChild(bad);
      return;
    }
    var people = p.people || [];
    if (!people.length) return;
    var sec = el('section', 'bf-prep');
    sec.setAttribute('aria-label', 'Before you meet');
    var h = el('h5', 'bf-h5 bf-inbox-part', 'Before you meet');
    h.appendChild(el('span', 'bf-inbox-count', plural(people.length, 'person', 'people') +
      ' from outside'));
    sec.appendChild(h);
    var list = el('ul', 'bf-prep-people');
    people.forEach(function (one) {
      var li = el('li', 'bf-prep-person');
      var top = el('div', 'bf-prep-who');
      top.appendChild(el('span', 'bf-prep-name', one.name || one.email));
      if (one.organisation) top.appendChild(el('span', 'bf-prep-org', one.organisation));
      li.appendChild(top);
      var sub = el('div', 'bf-prep-sub');
      sub.appendChild(el('span', 'bf-guest-mail', one.email));
      if (!one.known) sub.appendChild(el('span', 'bf-prep-tag', 'Not in your contacts'));
      li.appendChild(sub);
      if (one.relationship) {
        var rel = el('p', 'bf-prep-line');
        rel.appendChild(el('span', 'bf-dlg-label', 'You: '));
        rel.appendChild(document.createTextNode(one.relationship));
        li.appendChild(rel);
      }
      if (one.research) li.appendChild(el('p', 'bf-prep-line bf-prep-research', one.research));
      var mails = one.mails || [];
      if (mails.length) {
        var ml = el('ul', 'bf-prep-mails');
        ml.setAttribute('aria-label', 'Last emails with ' + (one.name || one.email));
        mails.forEach(function (m) {
          var mi = el('li', 'bf-prep-mail');
          var line = el('div', 'bf-prep-mail-top');
          line.appendChild(el('span', 'bf-prep-when', prepWhen(m.at)));
          var subj = m.link ? out(m.link, 'bf-prep-subj', m.subject, 'Open in Gmail')
                            : el('span', 'bf-prep-subj', m.subject);
          line.appendChild(subj);
          mi.appendChild(line);
          var who = 'From ' + m.from + (m.inbox && (p.inboxes || []).length > 1
            ? ' · in ' + m.inbox : '');
          mi.appendChild(el('div', 'bf-prep-from', who));
          if (m.snippet) mi.appendChild(el('div', 'bf-prep-snip', m.snippet));
          ml.appendChild(mi);
        });
        li.appendChild(ml);
      } else {
        li.appendChild(el('p', 'bf-note', 'No email with them in ' +
          ((p.inboxes || []).length ? (p.inboxes || []).join(' or ') : 'any inbox Rouh can read') + '.'));
      }
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (p.note) sec.appendChild(el('p', 'bf-note', p.note));
    box.appendChild(sec);
  }

  // What to raise (`rouh/meeting_brief.py`): for a meeting with people from
  // outside whom he has written to, the model's reading of the mail with them -
  // where things stand, what is open, what they last asked, what to raise and
  // what to be careful of - and the emails it read, each a link into Gmail. It
  // is made with the brief and kept on each meeting, so this is asked only for
  // a meeting the brief has none for (one added since, one the model could
  // not be asked about then, or one that read nothing yet), and the server
  // keeps what it makes on today's brief. An event with nobody from outside, a seminar, or the feature
  // switched off draws nothing at all.
  function raiseLoad(one, seq) {
    EV.raise = { busy: true };
    fetch('/api/brief/event/raise?calendar=' + encodeURIComponent(one.calendar_id) + '&event=' +
          encodeURIComponent(one.id), { credentials: 'same-origin', cache: 'no-store',
                                        headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== EV.seq || EV.one !== one) return;
          EV.raise = (r.ok && j && j.ok) ? j : { people: [1], error: (j && j.error) ||
            'What to raise could not be worked out just now (the server said ' + r.status + ').' };
          // Kept by the server as it is on the brief's own copy, so it opens at once next time.
          if (r.ok && j && j.ok && !j.off && !j.again) one.raise = j;
          evDraw();
        });
      })
      .catch(function () {
        if (seq !== EV.seq || EV.one !== one) return;
        EV.raise = { people: [1], error: 'Rouh could not be reached for What to raise.' };
        evDraw();
      });
  }

  // Correcting it (fr_792353f69079, 9 October 2026: "makes some factual
  // mistakes and I need a way to correct it. So maybe a button edit would give
  // me an input where I can type what is different"). Edit opens a box right
  // under the heading for what is wrong, in his own words; Make it again sends
  // it, and the reading made again with it (`meeting_brief.correct`) replaces
  // this one in place and on the brief's copy, with the box put away. While it
  // is made the old one stays, dimmed, and if it cannot be made it stays as it
  // was, with what he typed still in the box and why under it.
  function fixOpen() {
    EV.fix = { key: evKey(EV.one), text: (EV.fix && EV.fix.text) || '', busy: false, error: '',
               focus: true };
    evDraw();
  }

  function fixSend() {
    var fix = EV.fix, one = EV.one;
    if (!fix || fix.busy || !one) return;
    if (!fix.text.trim()) {
      fix.error = 'Say what is wrong in it first.';
      fix.focus = true;
      evDraw();
      return;
    }
    fix.busy = true;
    fix.error = '';
    evDraw();
    function failed(words) {
      fix.busy = false;
      fix.error = words;
      if (EV.fix === fix && EV.one === one) { fix.focus = true; evDraw(); }
    }
    fetch('/api/brief/event/raise/correct', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone() },
      body: JSON.stringify({ calendar: one.calendar_id, event: one.id, correction: fix.text })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!(r.ok && j && j.ok && j.brief)) {
          failed((j && j.error) || 'It could not be made again just now (the server said ' +
                 r.status + '). Your correction is still here; try again.');
          return;
        }
        // The brief's own copy, so the corrected one is what opens next time.
        one.raise = j;
        if (EV.fix === fix) EV.fix = null;
        if (EV.one !== one) return;
        EV.raise = j;
        EV.fixed = true;
        evDraw();
      });
    }).catch(function () {
      failed('Rouh could not be reached, so it was not made again. Your correction is still ' +
             'here; try again.');
    });
  }

  function fixDraw(sec) {
    var fix = EV.fix;
    var form = el('form', 'bf-raise-fix');
    form.setAttribute('aria-label', 'Correct What to raise');
    var id = 'bfRaiseFix';
    var label = el('label', 'bf-nudge-label', 'What is wrong in it? Say it in your own words, ' +
                   'such as a date, a name or something it claims.');
    label.htmlFor = id;
    var text = el('textarea', 'bf-nudge-text');
    text.id = id;
    text.rows = 3;
    text.maxLength = 2000;
    text.value = fix.text;
    text.readOnly = fix.busy;
    text.addEventListener('input', function () { fix.text = text.value; });
    text.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); fixSend(); }
    });
    form.appendChild(label);
    form.appendChild(text);
    var row = el('div', 'bf-pick-row');
    var go = el('button', 'bf-btn primary', fix.busy ? 'Making it again…' : 'Make it again');
    go.type = 'submit';
    go.disabled = fix.busy;
    row.appendChild(go);
    var cancel = el('button', 'bf-btn', 'Cancel');
    cancel.type = 'button';
    cancel.disabled = fix.busy;
    cancel.addEventListener('click', function () {
      EV.fix = null;
      evDraw();
      var edit = document.querySelector('#bfEventDialog .bf-raise-edit');
      if (edit) edit.focus({ preventScroll: true });
    });
    row.appendChild(cancel);
    if (fix.busy) {
      var busy = el('span', 'bf-raise-busy');
      busy.setAttribute('role', 'status');
      busy.appendChild(el('span', 'bf-spin'));
      busy.appendChild(document.createTextNode('Reading the mail again with your correction…'));
      row.appendChild(busy);
    }
    form.appendChild(row);
    if (fix.error) {
      var bad = el('p', 'bf-note bad', fix.error);
      bad.setAttribute('role', 'alert');
      form.appendChild(bad);
    }
    form.addEventListener('submit', function (e) { e.preventDefault(); fixSend(); });
    sec.appendChild(form);
    if (fix.focus) {
      fix.focus = false;
      setTimeout(function () {
        if (!document.contains(text)) return;
        text.focus({ preventScroll: true });
        text.setSelectionRange(text.value.length, text.value.length);
        text.scrollIntoView({ block: 'nearest' });
      }, 0);
    }
  }

  function raiseDraw(box) {
    var r = EV.raise;
    if (!r || r.off) return;
    var sec = el('section', 'bf-raise');
    sec.setAttribute('aria-label', 'What to raise');
    var top = el('div', 'bf-raise-top');
    var h = el('h5', 'bf-h5 bf-inbox-part', 'What to raise');
    top.appendChild(h);
    sec.appendChild(top);
    if (r.busy) {
      sec.appendChild(el('p', 'bf-note', 'Reading the mail with the people from outside…'));
      box.appendChild(sec);
      return;
    }
    if (!(r.people || []).length) return;
    if (r.error) {
      sec.appendChild(el('p', 'bf-note bad', r.error));
      box.appendChild(sec);
      return;
    }
    var b = r.brief;
    // What it read: the emails, since night 7 (`raise_memory`) the earlier meetings, and since
    // 22 October 2026 the Slack messages about the meeting (`meeting_slack.for_reading`).
    var read = [];
    if ((r.sources || []).length) read.push(plural(r.sources.length, 'email'));
    if ((r.meetings || []).length) read.push(plural(r.meetings.length, 'earlier meeting'));
    if ((r.slack_read || []).length) read.push(plural(r.slack_read.length, 'Slack message'));
    // Since night 31 (`rouh/raise_attached.py`), the documents attached to the invitation.
    var attachedRead = (r.attached_read || []).filter(function (a) { return !a.unread; });
    if (attachedRead.length) read.push(plural(attachedRead.length, 'attached document'));
    if (read.length) {
      var said = read.length > 1 ? read.slice(0, -1).join(', ') + ' and ' + read[read.length - 1] : read[0];
      h.appendChild(el('span', 'bf-inbox-count', 'from ' + said));
    }
    if (!b) {
      sec.appendChild(el('p', 'bf-note', r.note || 'Nothing to say yet.'));
      box.appendChild(sec);
      return;
    }
    // Only today's brief is corrected: one of another day is shown as it was kept.
    var fixing = EV.fix && EV.one && EV.fix.key === evKey(EV.one);
    if (EV.one && EV.one.id && EV.one.calendar_id && !keptOnly() && !fixing) {
      var edit = el('button', 'bf-btn bf-raise-edit', 'Edit');
      edit.type = 'button';
      edit.title = 'Say what is wrong in it, and it is made again';
      edit.setAttribute('aria-label', 'Edit What to raise: say what is wrong in it');
      edit.addEventListener('click', fixOpen);
      top.appendChild(edit);
    }
    if (fixing) {
      fixDraw(sec);
      if (EV.fix.busy) sec.classList.add('busy');
    } else if (EV.fixed) {
      var done = el('p', 'bf-note bf-raise-fixed', 'Made again with your correction.');
      done.setAttribute('role', 'status');
      sec.appendChild(done);
    }
    if (b.nothing && !b.standing && !(b.raise || []).length) {
      sec.appendChild(el('p', 'bf-raise-standing', b.nothing));
    }
    if (b.standing) sec.appendChild(el('p', 'bf-raise-standing', b.standing));
    if ((b.raise || []).length) {
      sec.appendChild(el('p', 'bf-raise-label', 'Raise'));
      var rl = el('ol', 'bf-raise-points');
      rl.setAttribute('aria-label', 'Raise');
      b.raise.forEach(function (one) {
        var li = el('li', 'bf-raise-point');
        li.appendChild(el('span', 'bf-raise-what', one.point));
        if (one.why) li.appendChild(el('span', 'bf-raise-why', one.why));
        rl.appendChild(li);
      });
      sec.appendChild(rl);
    }
    if ((b.open || []).length) {
      sec.appendChild(el('p', 'bf-raise-label', 'Open'));
      var ol = el('ul', 'bf-raise-open');
      ol.setAttribute('aria-label', 'Open');
      b.open.forEach(function (one) {
        var li = el('li', '', one.what);
        var who = [one.owed_by ? 'owed by ' + one.owed_by : '', one.since ? 'since ' + one.since : '']
          .filter(Boolean).join(', ');
        if (who) li.appendChild(el('span', 'bf-raise-owed', ' · ' + who));
        ol.appendChild(li);
      });
      sec.appendChild(ol);
    }
    if (b.they_asked) {
      var asked = el('p', 'bf-raise-line');
      asked.appendChild(el('span', 'bf-dlg-label', 'They last asked: '));
      asked.appendChild(document.createTextNode(b.they_asked));
      sec.appendChild(asked);
    }
    if (b.careful) {
      var care = el('p', 'bf-raise-line bf-raise-careful');
      care.appendChild(el('span', 'bf-dlg-label', 'Careful: '));
      care.appendChild(document.createTextNode(b.careful));
      sec.appendChild(care);
    }
    if ((r.sources || []).length) {
      var more = el('details', 'bf-raise-read');
      more.appendChild(el('summary', '', 'The emails it read'));
      var ml = el('ul', 'bf-raise-mails');
      r.sources.forEach(function (m) {
        var li = el('li', 'bf-raise-mail');
        li.appendChild(el('span', 'bf-prep-when', prepWhen(m.at)));
        li.appendChild(m.link ? out(m.link, 'bf-prep-subj', m.subject, 'Open in Gmail')
                              : el('span', 'bf-prep-subj', m.subject));
        li.appendChild(el('span', 'bf-raise-from', m.from));
        ml.appendChild(li);
      });
      more.appendChild(ml);
      sec.appendChild(more);
    }
    if ((r.meetings || []).length) {
      var met = el('details', 'bf-raise-read');
      met.appendChild(el('summary', '', 'The meetings it read'));
      var mtl = el('ul', 'bf-raise-mails');
      r.meetings.forEach(function (m) {
        var li = el('li', 'bf-raise-mail');
        li.appendChild(el('span', 'bf-prep-when', prepWhen(m.at)));
        li.appendChild(m.link ? out(m.link, 'bf-prep-subj', m.title, 'Open in the meeting library')
                              : el('span', 'bf-prep-subj', m.title));
        mtl.appendChild(li);
      });
      met.appendChild(mtl);
      sec.appendChild(met);
    }
    if ((r.slack_read || []).length) {
      var sl = el('details', 'bf-raise-read');
      sl.appendChild(el('summary', '', 'The Slack messages it read'));
      var sll = el('ul', 'bf-raise-mails');
      r.slack_read.forEach(function (m) {
        var li = el('li', 'bf-raise-mail bf-raise-slackread');
        li.appendChild(el('span', 'bf-prep-when', prepWhen(m.at)));
        li.appendChild(m.link ? out(m.link, 'bf-prep-subj', m.text, 'Open the message in Slack')
                              : el('span', 'bf-prep-subj', m.text));
        li.appendChild(el('span', 'bf-raise-from', [m.from, m.where].filter(Boolean).join(', ')));
        sll.appendChild(li);
      });
      sl.appendChild(sll);
      sec.appendChild(sl);
    }
    if ((r.attached_read || []).length) {
      // What to raise reads what is attached (night 31, `rouh/raise_attached.py`): the documents
      // attached to the meeting's invitation it read, each a link; one it could not open says so.
      var at = el('details', 'bf-raise-read bf-raise-attached');
      at.appendChild(el('summary', '', 'The documents attached to the invitation it read'));
      var atl = el('ul', 'bf-raise-mails');
      r.attached_read.forEach(function (a) {
        var li = el('li', 'bf-raise-mail bf-raise-attachedrow');
        var link = a.link ? out(a.link, 'bf-prep-subj', a.title, 'Open the document') : el('span', 'bf-prep-subj', a.title);
        if (a.link) {
          link.addEventListener('click', function () { raiseAttachedUsed('doc', a.title); });
        }
        li.appendChild(link);
        if (a.unread) li.appendChild(el('span', 'bf-raise-from', 'not read: ' + a.unread));
        atl.appendChild(li);
      });
      at.appendChild(atl);
      at.addEventListener('toggle', function () {
        if (at.open) raiseAttachedUsed('opened', (EV.one && EV.one.title) || '');
      });
      sec.appendChild(at);
    }
    if ((r.remembered || []).length) {
      var told = el('details', 'bf-raise-read');
      told.appendChild(el('summary', '', 'What you told it before'));
      var tl = el('ul', 'bf-raise-mails');
      r.remembered.forEach(function (f) {
        var li = el('li', 'bf-raise-mail bf-raise-told');
        li.appendChild(el('span', 'bf-prep-when', prepWhen(f.at)));
        li.appendChild(el('span', 'bf-prep-subj', f.text));
        tl.appendChild(li);
      });
      told.appendChild(tl);
      sec.appendChild(told);
    }
    box.appendChild(sec);
  }

  // Last said in Slack (`rouh/meeting_slack.py`): for each guest who is in his
  // Slack workspace, colleagues too, two or three lines of where he and they
  // left things there, each a link to the message it rests on. It comes with
  // What to raise, kept on the meeting the same way, and is drawn only when
  // there is something.
  function slackDraw(box) {
    var r = EV.raise;
    if (!r || r.off || r.busy || !(r.slack || []).length) return;
    var sec = el('section', 'bf-raise bf-slack');
    sec.setAttribute('aria-label', 'Last said in Slack');
    sec.appendChild(el('h5', 'bf-h5 bf-inbox-part', 'Last said in Slack'));
    r.slack.forEach(function (one) {
      sec.appendChild(el('p', 'bf-raise-label', one.name));
      var ul = el('ul', 'bf-slack-lines');
      ul.setAttribute('aria-label', 'With ' + one.name);
      (one.lines || []).forEach(function (line) {
        var li = el('li', 'bf-slack-line');
        li.appendChild(el('span', 'bf-slack-said', line.text));
        var when = [prepWhen(line.at), line.where].filter(Boolean).join(' · ');
        li.appendChild(out(line.link, 'bf-slack-link', when || 'Open in Slack', 'Open the message in Slack'));
        ul.appendChild(li);
      });
      sec.appendChild(ul);
    });
    box.appendChild(sec);
  }

  // An event asked for in the address (`/brief#event=<calendar>:<event>`), as
  // the message an hour before a meeting links to it (`meeting_prep.event_link`).
  // Read once, as the page starts, and opened as soon as the brief can.
  var WANT_EVENT = (function () {
    var found = /[#&]event=([^&]+)/.exec(location.hash || '');
    if (!found) return '';
    try { return decodeURIComponent(found[1]); } catch (err) { return ''; }
  }());

  function openWanted() {
    if (!WANT_EVENT || !B.open) return;
    var cut = WANT_EVENT.lastIndexOf(':');
    if (cut <= 0) { WANT_EVENT = ''; return; }
    var calendar = WANT_EVENT.slice(0, cut), id = WANT_EVENT.slice(cut + 1);
    WANT_EVENT = '';
    try { history.replaceState(history.state, '', location.pathname + location.search); } catch (err) {}
    var cal = (B.data && B.data.calendar) || {};
    var held = [].concat(cal.today || [], cal.tomorrow || []).filter(function (one) {
      return one.calendar_id === calendar && one.id === id;
    })[0];
    eventOpen(held || { calendar_id: calendar, id: id, title: 'The meeting', guests: [] });
  }

  // What Google said now, kept on the brief's own copy, so its row says it too.
  function evKeep(one, got) {
    ['response', 'guests', 'description', 'where', 'video', 'title'].forEach(function (k) {
      if (got[k] !== undefined) one[k] = got[k];
    });
  }

  function evClose() {
    var dlg = $('bfEventDialog');
    EV.one = null;
    EV.seq++;
    if (dlg && dlg.open) dlg.close();
  }

  function evDialog() {
    var dlg = $('bfEventDialog');
    if (dlg) return dlg;
    dlg = el('dialog', 'bf-dlg');
    dlg.id = 'bfEventDialog';
    dlg.setAttribute('aria-labelledby', 'bfEventTitle');
    // A press on the backdrop, outside the box, puts it away.
    dlg.addEventListener('click', function (e) {
      if (e.target !== dlg) return;
      var r = dlg.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
        evClose();
      }
    });
    dlg.addEventListener('close', function () {
      EV.one = null;
      if (EV.back && document.contains(EV.back)) EV.back.focus({ preventScroll: true });
      else {
        var key = EV.backKey && document.querySelector('.brief-view [data-ev="' + EV.backKey + '"]');
        if (key) key.focus({ preventScroll: true });
      }
    });
    ($('briefView') || document.body).appendChild(dlg);
    return dlg;
  }

  function evWhen(ev) {
    if (ev.all_day) return (ev.day_words || '') + ', all day';
    var day = ev.starts_at ? new Date(ev.starts_at * 1000).toLocaleDateString('en-GB', {
      timeZone: (B.data && B.data.zone) || undefined, weekday: 'long', day: 'numeric',
      month: 'long' }) : ev.day_words;
    return day + ', ' + ev.start + (ev.end ? '–' + ev.end : '');
  }

  var GUEST_MARKS = { accepted: '✓', declined: '✕', tentative: '?', needsAction: '·' };

  function evDraw() {
    var dlg = $('bfEventDialog');
    var ev = EV.data;
    if (!dlg || !ev) return;
    EV.backKey = EV.one ? evKey(EV.one) : '';
    // It is drawn again whenever something under it comes in, which must not
    // move the dialog back to its top or take the caret out of a correction
    // being typed.
    var scrolled = dlg.scrollTop;
    var typing = document.activeElement && document.activeElement.id === 'bfRaiseFix'
      ? document.activeElement : null;
    var caret = typing ? [typing.selectionStart, typing.selectionEnd] : null;
    dlg.textContent = '';
    var box = el('div', 'bf-dlg-box');
    var head = el('div', 'bf-dlg-head');
    var h = el('h3', 'bf-dlg-title', ev.title);
    h.id = 'bfEventTitle';
    head.appendChild(h);
    var x = el('button', 'layer-x bf-dlg-x', '×');
    x.type = 'button';
    x.title = 'Close (Esc)';
    x.setAttribute('aria-label', 'Close the event');
    x.addEventListener('click', evClose);
    head.appendChild(x);
    box.appendChild(head);

    var dl = el('dl', 'bf-read-heads bf-dlg-facts');
    function fact(name, value) {
      if (!value) return;
      dl.appendChild(el('dt', null, name));
      var dd = el('dd');
      if (typeof value === 'string') dd.textContent = value; else dd.appendChild(value);
      dl.appendChild(dd);
    }
    fact('When', evWhen(ev) + (B.data && B.data.zone && secondZone()
      ? ' (' + city(B.data.zone) + ')' : ''));
    var alt = altSpan(ev);
    if (alt) fact(city(secondZone()), alt.textContent.replace(city(secondZone()) + ' ', ''));
    if (ev.repeats) fact('Repeats', 'Yes, this is one of a series');
    fact('Where', ev.where);
    if (ev.video) fact('Call', out(ev.video, 'bf-join', ev.video.replace(/^https?:\/\//, '')));
    fact('Calendar', ev.calendar);
    if (ev.organiser && !ev.mine) {
      fact('Organiser', ev.organiser_name ? ev.organiser_name + ' <' + ev.organiser + '>'
                                          : ev.organiser);
    }
    box.appendChild(dl);

    if (EV.error) box.appendChild(el('p', 'bf-note bad', EV.error));

    // His answer, when this calendar is one of those invited.
    var me = (ev.guests || []).filter(function (g) { return g.me; })[0];
    if (me && !ev.mine && !keptOnly()) {
      var ans = el('div', 'bf-dlg-answer');
      ans.setAttribute('role', 'group');
      ans.setAttribute('aria-label', 'Your answer');
      var now = el('p', 'bf-dlg-now');
      now.appendChild(el('span', 'bf-dlg-label', 'Your answer'));
      now.appendChild(el('span', 'bf-dlg-state ' + (ev.response || 'needsAction'),
                         RESPONSE_WORDS[ev.response] || RESPONSE_WORDS.needsAction));
      ans.appendChild(now);
      var row = el('div', 'bf-pick-row');
      [['accepted', 'Going'], ['tentative', 'Maybe'], ['declined', 'Not going']].forEach(function (a) {
        var b = el('button', 'bf-btn' + (ev.response === a[0] ? ' primary' : ''),
                   EV.busy === a[0] ? 'Sending…' : a[1]);
        b.type = 'button';
        b.setAttribute('aria-pressed', ev.response === a[0] ? 'true' : 'false');
        b.disabled = !!EV.busy || !ev.id;
        b.addEventListener('click', function () { evAnswer(a[0]); });
        row.appendChild(b);
      });
      ans.appendChild(row);
      if (EV.said) {
        var said = el('p', 'bf-note' + (EV.said.bad ? ' bad' : ''), EV.said.text);
        said.setAttribute('role', 'status');
        ans.appendChild(said);
      }
      box.appendChild(ans);
    }

    raiseDraw(box);
    slackDraw(box);
    prepDraw(box);

    // Always under its own heading here, so an event Google holds no words
    // for says so, rather than looking as if the brief lost them (fr_f4ea233f9c06).
    box.appendChild(el('h5', 'bf-h5', 'Description'));
    if (ev.description) {
      box.appendChild(linked(el('div', 'bf-dlg-desc'), tidyWords(ev.description)));
    } else {
      box.appendChild(el('p', 'bf-note', 'None. Nothing is written in this event in Google Calendar.'));
    }

    var guests = ev.guests || [];
    if (guests.length) {
      var counts = {};
      guests.forEach(function (g) { counts[g.response] = (counts[g.response] || 0) + 1; });
      var hg = el('h5', 'bf-h5 bf-inbox-part', 'Invited');
      hg.appendChild(el('span', 'bf-inbox-count', [
        counts.accepted ? counts.accepted + ' going' : '',
        counts.tentative ? counts.tentative + ' maybe' : '',
        counts.declined ? counts.declined + ' not going' : '',
        counts.needsAction ? counts.needsAction + ' not answered' : ''
      ].filter(Boolean).join(', ')));
      box.appendChild(hg);
      var list = el('ul', 'bf-guests');
      guests.forEach(function (g) {
        var li = el('li', 'bf-guest ' + g.response);
        var mark = el('span', 'bf-guest-mark', GUEST_MARKS[g.response] || '·');
        mark.setAttribute('aria-hidden', 'true');
        li.appendChild(mark);
        var who = el('span', 'bf-guest-who');
        who.appendChild(el('span', 'bf-guest-name', (g.name || g.email) + (g.me ? ' (you)' : '')));
        if (g.name && g.email) who.appendChild(el('span', 'bf-guest-mail', g.email));
        li.appendChild(who);
        li.appendChild(el('span', 'bf-guest-said', (g.organiser ? 'Organiser · ' : '') +
          (RESPONSE_WORDS[g.response] || RESPONSE_WORDS.needsAction) +
          (g.optional ? ' · optional' : '')));
        list.appendChild(li);
      });
      box.appendChild(list);
      if (ev.more_guests) box.appendChild(el('p', 'bf-note', 'And ' + ev.more_guests + ' more.'));
    }

    var acts = el('div', 'bf-pick-row bf-dlg-acts');
    if (ev.link) acts.appendChild(out(ev.link, 'bf-btn', 'Open in Google Calendar'));
    var close = el('button', 'bf-btn', 'Close');
    close.type = 'button';
    close.addEventListener('click', evClose);
    acts.appendChild(close);
    box.appendChild(acts);
    dlg.appendChild(box);
    dlg.scrollTop = scrolled;
    var again = typing && $('bfRaiseFix');
    if (again && !EV.fix.busy) {
      again.focus({ preventScroll: true });
      again.setSelectionRange(caret[0], caret[1]);
    }
  }

  function evAnswer(response) {
    var one = EV.one, ev = EV.data;
    if (!one || EV.busy) return;
    EV.busy = response;
    EV.said = null;
    evDraw();
    fetch('/api/brief/event/answer', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone() },
      body: JSON.stringify({ calendar: ev.calendar_id, event: ev.id, response: response })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (EV.one !== one) return;
        EV.busy = '';
        if (r.ok && j && j.event) {
          EV.data = j.event;
          evKeep(one, j.event);
          EV.said = { text: 'Sent: ' + (RESPONSE_WORDS[j.event.response] || response).toLowerCase() +
            '. ' + (j.event.organiser_name || j.event.organiser || 'The organiser') +
            ' has been told.' };
        } else {
          EV.said = { bad: true, text: 'Not sent: ' + ((j && j.error) ||
            'the server said ' + r.status + '.') };
        }
        evDraw();
        draw();
      });
    }).catch(function () {
      if (EV.one !== one) return;
      EV.busy = '';
      EV.said = { bad: true, text: 'Not sent: Rouh could not be reached. Try again.' };
      evDraw();
    });
  }

  // No source in its top right corner (fr_854ef3f9eb57: "Remove Google
  // Calendar from top right corner"): the spinner is there instead, while it
  // is being read again (`calendarLoad`). The days are only "Today" and
  // "Tomorrow", whatever words a brief kept before that said.
  function drawCalendar(body, cal, now) {
    var zone = secondZone();
    var sec = section('calendar', 'Calendar', cal, zone && B.data.zone
      ? city(B.data.zone) + ' time, and ' + city(zone) : '', true);
    if (B.cal.busy) {
      var spin = el('span', 'bf-spin');
      spin.setAttribute('role', 'status');
      spin.setAttribute('aria-label', 'Reading your calendar again');
      spin.title = 'Reading your calendar again';
      sec.querySelector('.bf-h').appendChild(spin);
    }
    sec.setAttribute('aria-busy', B.cal.busy ? 'true' : 'false');
    body.appendChild(sec);
    if (!cal.ok) return;
    // A brief of another day says its own days by name, not Today and Tomorrow.
    var own = !keptOnly() && !older();
    var day = B.data.day, after = nextDay(B.data.day);
    var days = [
      { key: 'today', iso: day, events: cal.today || [], own: own,
        words: own ? 'Today' : shortDate(day).split(',')[0], date: dayDate(day),
        empty: own ? 'Nothing today.' : 'Nothing that day.' },
      { key: 'tomorrow', iso: after, events: cal.tomorrow || [], own: own,
        words: own ? 'Tomorrow' : shortDate(after).split(',')[0], date: dayDate(after),
        empty: own ? 'Nothing tomorrow.' : 'Nothing that day.' }];
    calendarGrid(sec, days, now);
    (cal.trouble || []).forEach(function (t) { sec.appendChild(el('p', 'bf-note', t)); });
    if (B.cal.note) sec.appendChild(el('p', 'bf-note', B.cal.note));
  }

  function drawWeather(body, w) {
    var sec = section('weather', 'Weather', w, w.ok ? w.place : '');
    body.appendChild(sec);
    if (!w.ok) return;
    var row = el('div', 'bf-wx');
    row.appendChild(el('span', 'bf-wx-pic', w.picture));
    var main = el('div', 'bf-wx-main');
    var big = el('p', 'bf-wx-big');
    big.appendChild(el('span', 'bf-hi', w.high + '°'));
    big.appendChild(el('span', 'bf-lo', ' / ' + w.low + '°'));
    main.appendChild(big);
    var rain = w.rain_from ? 'Rain likely from ' + w.rain_from
      : (w.rain != null ? 'Rain ' + w.rain + '%' : '');
    main.appendChild(dotted(el('p', 'bf-wx-words'), [w.words, rain]));
    row.appendChild(main);
    sec.appendChild(row);
    sec.appendChild(dotted(el('p', 'bf-wx-more'), [
      w.now != null ? 'Now ' + w.now + '°' + (w.feels != null && w.feels !== w.now
        ? ', feels like ' + w.feels + '°' : '') : '',
      w.wind != null ? 'Wind ' + w.wind + ' km/h' : '',
      w.sunrise ? 'Sunrise ' + w.sunrise : '', w.sunset ? 'Sunset ' + w.sunset : '']));
  }

  function drawWorld(body, n) {
    var sec = section('world', 'World News', n);
    body.appendChild(sec);
    if (!n.ok) return;
    var list = el('ol', 'bf-stories');
    n.stories.forEach(function (one) {
      var li = el('li', 'bf-story');
      li.appendChild(out(one.link, 'bf-top', one.title));
      if (one.summary) li.appendChild(el('p', 'bf-sum', one.summary));
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  // Needs you in Slack (16 October 2026, `rouh/slack_brief.py`): what waits on him there, one
  // line a conversation or thread, who, where and how long, and what they ask, opening the
  // message in Slack. Nothing waiting is no section at all.
  function waited(at, now) {
    var mins = Math.max(1, Math.round((now - at) / 60));
    if (mins < 60) return mins + ' min';
    if (mins < 24 * 60) return Math.round(mins / 60) + ' h';
    return plural(Math.round(mins / 1440), 'day');
  }

  // An x on each line puts it away (Petar, 19 October 2026, fr_6d5b2ccbf194: "give me an x on
  // each item, because I want to discard what is past and not needed anymore"). It goes at once,
  // the list closes up, and a line under the heading says so with Undo. The server keeps it out
  // of every brief after, until somebody writes in that place again (`slack_brief.dismiss`).
  function drawSlack(body, s, now) {
    var items = (s.ok && s.items) || [];
    var said = B.slackSaid && B.slackSaid.part === s ? B.slackSaid : null;
    if (!items.length && !said) return;
    var sec = section('slack', 'Needs you in Slack', s);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { slackUndo(s, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-slack-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.who));
      head.appendChild(el('span', 'bf-slack-where', one.where));
      var days = el('span', 'bf-ghost-days', waited(one.at, now));
      days.title = 'Waiting since ' + whenWords(one.at);
      head.appendChild(days);
      if (!keptOnly() && one.key) {
        var x = el('button', 'bf-slack-x');
        x.type = 'button';
        x.title = 'Dismiss';
        x.setAttribute('aria-label', 'Dismiss ' + one.who + ', ' + one.where);
        x.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" ' +
          'stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';
        x.addEventListener('click', function () { slackDismiss(s, one); });
        head.appendChild(x);
      }
      li.appendChild(head);
      var what = one.what || 'Open the message';
      li.appendChild(one.link ? out(one.link, 'bf-ghost-subject', what, 'Open in Slack')
        : el('p', 'bf-ghost-subject', what));
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  // The Slack section alone, drawn again where it is, so nothing else on the page moves.
  function slackRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-slack');
    if (!old || !B.data || !B.data.slack) return;
    var holder = document.createDocumentFragment();
    drawSlack(holder, B.data.slack, Date.now() / 1000);
    old.replaceWith(holder);
  }

  function slackSend(one, undo) {
    return fetch('/api/brief/slack/dismiss', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: one.key, at: one.last_at || one.at, undo: !!undo })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return false; }
      return r.ok;
    }).catch(function () { return false; });
  }

  function slackDismiss(s, one) {
    var at = s.items.indexOf(one);
    if (at < 0) return;
    s.items.splice(at, 1);
    var said = { part: s, one: one, at: at, text: 'Dismissed ' + one.who + ', ' + one.where + '.' };
    B.slackSaid = said;
    slackRedraw();
    slackSend(one, false).then(function (ok) {
      if (ok || B.slackSaid !== said) return;
      // Not kept: the line comes back where it was, and the line says so.
      if (s.items.indexOf(one) < 0) s.items.splice(Math.min(at, s.items.length), 0, one);
      B.slackSaid = { part: s, bad: true, text: 'That could not be dismissed. Try again.' };
      slackRedraw();
    });
  }

  function slackUndo(s, said) {
    if (s.items.indexOf(said.one) < 0) s.items.splice(Math.min(said.at, s.items.length), 0, said.one);
    B.slackSaid = null;
    slackRedraw();
    slackSend(said.one, true).then(function (ok) {
      if (ok) return;
      var i = s.items.indexOf(said.one);
      if (i >= 0) s.items.splice(i, 1);
      B.slackSaid = { part: s, bad: true, text: 'It could not be brought back. Try again.' };
      slackRedraw();
    });
  }

  // Owed to you (21 October 2026, `rouh/owed_to_you.py`): what somebody said in a meeting they
  // would do by a date that has passed, one line each, the latest first. What was this about,
  // closed and read only when opened, and a follow-up drafted only when asked for (version 2,
  // 27 October 2026), to send from Rouh's inbox; It came, which puts the line away with Undo, and
  // Dismiss, which puts it away the same way for a line to ignore, saying nothing came
  // (fr_c80e0bd69613). Nothing owed is no section.
  function drawOwed(body, o) {
    var items = (o.ok && o.items) || [];
    var said = B.owed.said;
    if (!items.length && !said) return;
    var sec = section('owed', 'Owed to you', o);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { owedUndo(o, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-owed-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.who));
      head.appendChild(el('span', 'bf-ghost-days', one.late === 1 ? '1 day late' : one.late + ' days late'));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-ghost-subject', one.what));
      var from = el('p', 'bf-note bf-owed-from', 'Due ' + dueWords(one.due) + ', said in ');
      from.appendChild(one.page ? out(one.page, 'bf-link', one.meeting, 'The meeting\'s notes')
                                : el('span', null, one.meeting));
      if (one.met_at) from.appendChild(document.createTextNode(', ' + dayWords(one.met_at)));
      if (one.chased) from.appendChild(document.createTextNode('. Followed up ' + whenWords(one.chased)));
      li.appendChild(from);
      owedAbout(li, one);
      var acts = el('div', 'bf-ghost-acts');
      var open = !!B.owed.open[one.key];
      var chase = el('button', 'bf-btn', open ? 'Hide the follow-up'
                                              : (one.chased ? 'Follow up again' : 'Draft a follow-up'));
      chase.type = 'button';
      chase.setAttribute('aria-expanded', open ? 'true' : 'false');
      chase.addEventListener('click', function () {
        B.owed.open[one.key] = !open;
        if (!open && B.owed.text[one.key] == null) owedDraft(one);
        owedRedraw();
      });
      acts.appendChild(chase);
      var came = el('button', 'bf-btn', 'It came');
      came.type = 'button';
      came.addEventListener('click', function () { owedPut(o, one, 'came', 'Marked as come: '); });
      acts.appendChild(came);
      var dismiss = el('button', 'bf-btn', 'Dismiss');
      dismiss.type = 'button';
      dismiss.addEventListener('click', function () { owedPut(o, one, 'dismiss', 'Dismissed: '); });
      acts.appendChild(dismiss);
      li.appendChild(acts);
      if (open) owedBox(li, o, one);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function dueWords(iso) {
    var d = new Date(iso + 'T12:00:00');
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  // What was this about: closed at first, read from his Master the first time it is opened, and
  // kept open and read through every redraw of the section.
  function owedAbout(li, one) {
    var held = B.owed.about[one.key] || (B.owed.about[one.key] = { open: false, data: null, bad: '' });
    var box = el('details', 'bf-raise-read bf-owed-about');
    box.open = held.open;
    box.appendChild(el('summary', '', 'What was this about'));
    var inside = el('div', 'bf-owed-about-body');
    box.appendChild(inside);
    function fill() {
      inside.textContent = '';
      if (held.bad) { inside.appendChild(el('p', 'bf-note bad', held.bad)); return; }
      if (!held.data) { inside.appendChild(el('p', 'bf-note', 'Reading the meeting…')); return; }
      owedAboutDraw(inside, held.data);
    }
    fill();
    // Drawn open again, the details says toggle once by itself: that is not his press.
    var drawnOpen = held.open;
    box.addEventListener('toggle', function () {
      if (drawnOpen) { drawnOpen = false; return; }
      held.open = box.open;
      if (!box.open || held.data || held.busy) return;
      held.busy = true;
      held.bad = '';
      fill();
      owedPost({ key: one.key, act: 'context' }).then(function (j) {
        held.busy = false;
        if (!j) return;
        if (j.error) held.bad = 'It could not be read: ' + j.error;
        else held.data = j;
        owedRedraw();
      });
    });
    li.appendChild(box);
  }

  function owedAboutDraw(inside, c) {
    function line(label, text) {
      var p = el('p', 'bf-raise-line');
      p.appendChild(el('span', 'bf-dlg-label', label));
      p.appendChild(document.createTextNode(text));
      inside.appendChild(p);
    }
    function named(p) { return p.name + (p.outside ? ' (outside)' : ''); }
    var there = (c.people || []).filter(function (p) { return p.took_part; });
    var away = (c.people || []).filter(function (p) { return !p.took_part; });
    if (there.length) line('Who was there: ', there.map(named).join(', '));
    if (away.length) line('Invited, not there: ', away.map(named).join(', '));
    if ((c.to || []).length) line('Promised to: ', c.to.join(', '));
    if (c.summary) line('What the meeting was about: ', c.summary);
    if ((c.said || []).length) {
      inside.appendChild(el('p', 'bf-raise-line bf-dlg-label', 'What was said:'));
      var list = el('ul', 'bf-raise-mails');
      c.said.forEach(function (t) {
        var li = el('li', 'bf-raise-mail bf-owed-turn');
        li.appendChild(el('span', 'bf-prep-when', t.at));
        li.appendChild(el('span', 'bf-prep-subj', t.said));
        li.appendChild(el('span', 'bf-raise-from', t.who));
        list.appendChild(li);
      });
      inside.appendChild(list);
    }
  }

  // Draft a follow-up: written by Rouh only when pressed, then his to change before Send.
  function owedDraft(one) {
    B.owed.drafting[one.key] = true;
    owedPost({ key: one.key, act: 'draft' }).then(function (j) {
      delete B.owed.drafting[one.key];
      if (!j) return;
      if (j.error) B.owed.open[one.key] = false;
      else if (B.owed.text[one.key] == null) B.owed.text[one.key] = j.text;
      B.owed.said = j.error ? { bad: true, text: 'The follow-up could not be drafted: ' + j.error } : B.owed.said;
      owedRedraw();
    });
  }

  function owedBox(li, o, one) {
    var box = el('div', 'bf-nudge');
    if (B.owed.drafting[one.key] || B.owed.text[one.key] == null) {
      box.appendChild(el('p', 'bf-note', 'Drafting the follow-up…'));
      li.appendChild(box);
      return;
    }
    var id = 'bfOwed' + one.key;
    var label = el('label', 'bf-nudge-label', 'A follow-up to send to ' + one.email);
    label.htmlFor = id;
    var text = el('textarea', 'bf-nudge-text');
    text.id = id;
    text.rows = 7;
    text.value = B.owed.text[one.key];
    // The whole letter in sight, growing as it is written, never cut.
    function fit() { text.style.height = 'auto'; text.style.height = text.scrollHeight + 2 + 'px'; }
    text.addEventListener('input', function () { B.owed.text[one.key] = text.value; fit(); });
    requestAnimationFrame(fit);
    box.appendChild(label);
    box.appendChild(text);
    var row = el('div', 'bf-pick-row');
    var send = el('button', 'bf-btn primary', 'Send');
    send.type = 'button';
    var said = el('span', 'bf-note bf-nudge-said');
    said.setAttribute('role', 'status');
    send.addEventListener('click', function () { owedSend(o, one, text, send, said); });
    row.appendChild(send);
    row.appendChild(said);
    box.appendChild(row);
    box.appendChild(el('p', 'bf-note', 'Send emails it from Rouh\'s own inbox, as a new email to ' +
      one.email + '.'));
    li.appendChild(box);
  }

  function owedRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-owed');
    if (!B.data || !B.data.owed) return;
    var holder = document.createDocumentFragment();
    drawOwed(holder, B.data.owed);
    if (old) old.replaceWith(holder);
  }

  function owedPost(body) {
    return fetch('/api/brief/owed', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function owedSend(o, one, text, button, said) {
    if (!text.value.trim()) {
      said.classList.add('bad');
      said.textContent = 'There is nothing in the follow-up to send.';
      return;
    }
    button.disabled = true;
    text.readOnly = true;
    button.textContent = 'Sending…';
    said.classList.remove('bad');
    said.textContent = '';
    owedPost({ key: one.key, act: 'send', text: text.value }).then(function (j) {
      if (!j) return;
      if (j.error) {
        button.disabled = false;
        text.readOnly = false;
        button.textContent = 'Send';
        said.classList.add('bad');
        said.textContent = 'Not sent: ' + j.error;
        return;
      }
      one.chased = j.at;
      B.owed.open[one.key] = false;
      delete B.owed.text[one.key];
      B.owed.said = { text: 'Sent the follow-up to ' + j.to + '.' };
      owedRedraw();
    });
  }

  // It came or Dismiss: the line goes at once, with Undo, and comes back if it could not be kept.
  function owedPut(o, one, act, words) {
    var at = o.items.indexOf(one);
    if (at < 0) return;
    o.items.splice(at, 1);
    var said = { one: one, at: at, text: words + one.what + '.' };
    B.owed.said = said;
    owedRedraw();
    owedPost({ key: one.key, act: act }).then(function (j) {
      if (!j || !j.error || B.owed.said !== said) return;
      if (o.items.indexOf(one) < 0) o.items.splice(Math.min(at, o.items.length), 0, one);
      B.owed.said = { bad: true, text: 'That could not be kept. Try again.' };
      owedRedraw();
    });
  }

  function owedUndo(o, said) {
    if (o.items.indexOf(said.one) < 0) o.items.splice(Math.min(said.at, o.items.length), 0, said.one);
    B.owed.said = null;
    owedRedraw();
    owedPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = o.items.indexOf(said.one);
      if (i >= 0) o.items.splice(i, 1);
      B.owed.said = { bad: true, text: 'It could not be brought back. Try again.' };
      owedRedraw();
    });
  }

  // Meetings with no notes (22 October 2026, `rouh/notes_missing.py`): his meetings with people
  // from outside, on a video call, that the meeting library sent no notes for, the latest first,
  // with when it last sent any. Not recorded puts one away, with Undo. None missing is no section.
  function drawNoNotes(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.noNotes.said;
    if (!items.length && !said) return;
    var sec = section('no_notes', 'Meetings with no notes', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { noNotesUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var many = items.length === 1 ? 'One meeting' : items.length + ' meetings';
    var lead = el('p', 'bf-note bf-nonotes-lead', many + ' with people from outside had no notes from ' +
      'the meeting library. The last notes it sent were for ');
    lead.appendChild(el('b', null, n.last.title));
    lead.appendChild(document.createTextNode(', ' + dayWords(n.last.at) + '.'));
    sec.appendChild(lead);
    if (n.library) {
      var row = el('div', 'bf-ghost-acts bf-nonotes-acts');
      var lib = out(n.library, 'bf-btn', 'Open the meeting library');
      lib.addEventListener('click', function () { noNotesPost({ act: 'library' }); });
      row.appendChild(lib);
      sec.appendChild(row);
    }
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-nonotes-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The event in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      head.appendChild(el('span', 'bf-ghost-days', whenWords(one.start)));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-note', 'With ' + one.outside.join(', ')));
      var acts = el('div', 'bf-ghost-acts');
      var none = el('button', 'bf-btn', 'Not recorded');
      none.type = 'button';
      none.title = 'It was not meant to be recorded: put it away';
      none.addEventListener('click', function () { noNotesPut(n, one); });
      acts.appendChild(none);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function noNotesRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-no_notes');
    if (!B.data || !B.data.no_notes) return;
    var holder = document.createDocumentFragment();
    drawNoNotes(holder, B.data.no_notes);
    if (old) old.replaceWith(holder);
  }

  function noNotesPost(body) {
    return fetch('/api/brief/no_notes', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function noNotesPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Put away as not recorded: ' + one.title + '.' };
    B.noNotes.said = said;
    noNotesRedraw();
    noNotesPost({ key: one.key, act: 'not_recorded' }).then(function (j) {
      if (!j || !j.error || B.noNotes.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.noNotes.said = { bad: true, text: 'That could not be kept. Try again.' };
      noNotesRedraw();
    });
  }

  function noNotesUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.noNotes.said = null;
    noNotesRedraw();
    noNotesPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.noNotes.said = { bad: true, text: 'It could not be brought back. Try again.' };
      noNotesRedraw();
    });
  }

  // Changed by others (24 October 2026, `rouh/others_changed.py`): his pages somebody else changed
  // since he last opened them, newest first: who, how many changes, when, and what the newest
  // changes did. Open the page opens it; Seen puts it away until it changes again, with Undo.
  function drawOthersChanged(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.othersChanged.said;
    if (!items.length && !said) return;
    var sec = section('others_changed', 'Changed by others', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { othersUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-others-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.title));
      head.appendChild(el('span', 'bf-ghost-days', whenWords(one.last)));
      li.appendChild(head);
      var many = one.changes === 1 ? 'one change' : one.changes + ' changes';
      li.appendChild(el('p', 'bf-note', one.people.join(', ') + ', ' + many +
        (one.opened ? ' since you opened it ' + whenWords(one.opened).toLowerCase()
                    : ', and you have not opened it since')));
      if (one.summaries.length) {
        var what = el('ul', 'bf-others-what');
        one.summaries.forEach(function (words) { what.appendChild(el('li', null, words)); });
        if (one.more) what.appendChild(el('li', 'bf-others-more', 'and ' + one.more + ' more'));
        li.appendChild(what);
      }
      var acts = el('div', 'bf-ghost-acts');
      var open = goLink(el('a', 'bf-btn', 'Open the page'), one.link);
      open.addEventListener('click', function () {
        othersPost({ key: one.key, act: 'open', newest: one.newest });
        if (host().go) host().go(one.link);
        else location.href = one.link;
      });
      acts.appendChild(open);
      var seen = el('button', 'bf-btn', 'Seen');
      seen.type = 'button';
      seen.title = 'Put it away until somebody changes it again';
      seen.addEventListener('click', function () { othersPut(n, one); });
      acts.appendChild(seen);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function othersRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-others_changed');
    if (!B.data || !B.data.others_changed) return;
    var holder = document.createDocumentFragment();
    drawOthersChanged(holder, B.data.others_changed);
    if (old) old.replaceWith(holder);
  }

  function othersPost(body) {
    return fetch('/api/brief/others_changed', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function othersPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Put away: ' + one.title + '.' };
    B.othersChanged.said = said;
    othersRedraw();
    othersPost({ key: one.key, act: 'seen', newest: one.newest }).then(function (j) {
      if (!j || !j.error || B.othersChanged.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.othersChanged.said = { bad: true, text: 'That could not be kept. Try again.' };
      othersRedraw();
    });
  }

  function othersUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.othersChanged.said = null;
    othersRedraw();
    othersPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.othersChanged.said = { bad: true, text: 'It could not be brought back. Try again.' };
      othersRedraw();
    });
  }

  // Shared with you (26 October 2026, `rouh/shared_with_you.py`): a Google document somebody
  // shared with him in his own inboxes that no task links yet, who shared it and when, whether
  // Rouh can open it, and the task whose notes name that person. Add to task keeps its link in
  // the task's notes, with Undo; Open opens it; Got it puts it away.
  function drawShared(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.shared.said;
    if (!items.length && !said) return;
    var sec = section('shared_with_you', 'Shared with you', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { sharedUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-shared-line');
      var head = el('p', 'bf-ghost-head');
      var name = el('a', 'bf-ghost-who bf-shared-title', one.title);
      name.href = one.url;
      name.target = '_blank';
      name.rel = 'noopener';
      name.addEventListener('click', function () { sharedPost({ key: one.key, act: 'open' }); });
      head.appendChild(name);
      head.appendChild(el('span', 'bf-usual-when', one.kind));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-usual-said', one.who + ' shared it with you on ' + one.day + '.'));
      if (one.rouh_can_open === false) {
        li.appendChild(el('p', 'bf-note', 'Rouh’s own Google account cannot open it, so a job or a chat cannot read it until it is shared with Rouh too.'));
      }
      var acts = el('div', 'bf-ghost-acts');
      var tasks = one.tasks || [];
      if (tasks.length) {
        var pick = B.shared.pick[one.key] || tasks[0].rel;
        var picked = tasks.filter(function (t) { return t.rel === pick; })[0] || tasks[0];
        // One task: its name is on the button. Several: picked in the list, and Add beside it.
        var add = el('button', 'bf-btn', tasks.length > 1 ? 'Add'
          : 'Add to task ' + picked.number + ' · ' + picked.title);
        add.type = 'button';
        add.disabled = B.shared.busy === one.key;
        add.addEventListener('click', function () { sharedAdd(n, one, picked); });
        if (tasks.length > 1) {
          var choose = el('select', 'bf-shared-pick');
          choose.setAttribute('aria-label', 'The task to add it to');
          tasks.forEach(function (t) {
            var o = el('option', '', 'Task ' + t.number + ' · ' + t.title);
            o.value = t.rel;
            if (t.rel === picked.rel) o.selected = true;
            choose.appendChild(o);
          });
          choose.addEventListener('change', function () {
            B.shared.pick[one.key] = choose.value;
            sharedRedraw();
          });
          acts.appendChild(choose);
        }
        acts.appendChild(add);
      } else {
        li.appendChild(el('p', 'bf-note', 'No task of yours names ' + one.who + ' yet.'));
      }
      var seen = el('button', 'bf-btn', 'Got it');
      seen.type = 'button';
      seen.title = 'Put it away';
      seen.addEventListener('click', function () { sharedPut(n, one); });
      acts.appendChild(seen);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function sharedRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-shared_with_you');
    if (!B.data || !B.data.shared_with_you) return;
    var holder = document.createDocumentFragment();
    drawShared(holder, B.data.shared_with_you);
    if (old) old.replaceWith(holder);
  }

  function sharedPost(body) {
    return fetch('/api/brief/shared_with_you', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function sharedAdd(n, one, task) {
    B.shared.busy = one.key;
    sharedRedraw();
    sharedPost({ key: one.key, act: 'add', task: task.rel }).then(function (j) {
      B.shared.busy = '';
      if (j && j.error) {
        B.shared.said = { bad: true, text: 'It could not be added: ' + j.error };
        sharedRedraw();
        return;
      }
      var at = n.items.indexOf(one);
      if (at >= 0) n.items.splice(at, 1);
      B.shared.said = { one: one, at: Math.max(at, 0),
                        text: 'Added ' + one.title + ' to task ' + task.number + ' · ' + task.title + '.' };
      sharedRedraw();
    });
  }

  function sharedPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Put away: ' + one.title + '.' };
    B.shared.said = said;
    sharedRedraw();
    sharedPost({ key: one.key, act: 'seen' }).then(function (j) {
      if (!j || !j.error || B.shared.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.shared.said = { bad: true, text: 'That could not be kept. Try again.' };
      sharedRedraw();
    });
  }

  function sharedUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.shared.said = null;
    sharedRedraw();
    sharedPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.shared.said = { bad: true, text: 'It could not be brought back. Try again.' };
      sharedRedraw();
    });
  }

  // Not opened yet (28 October 2026, `rouh/not_opened.py`): a page or a task he shared with
  // somebody by hand, two to fourteen days ago, that they have not opened since. Write to them
  // opens Gmail's own new message to them, in his mailbox, with their link in it; Let it be puts
  // it away, with Undo. A line goes by itself once they open it.
  function drawNotOpened(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.notOpened.said;
    if (!items.length && !said) return;
    var sec = section('not_opened', 'Not opened yet', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { notOpenedUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-notopened-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.title));
      head.appendChild(el('span', 'bf-ghost-days', one.days === 1 ? '1 day' : one.days + ' days'));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-note', 'Shared with ' + one.email + ' on ' + one.day +
        (one.level === 'edit' ? ', to edit.' : ', to read.')));
      var acts = el('div', 'bf-ghost-acts');
      var write = out(one.write, 'bf-btn', 'Write to them', 'A new email to ' + one.email + ' in Gmail, with their link');
      write.addEventListener('click', function () { notOpenedPost({ key: one.key, act: 'write' }); });
      acts.appendChild(write);
      var open = goLink(el('a', 'bf-btn', 'Open the ' + one.kind), one.link);
      open.addEventListener('click', function () {
        notOpenedPost({ key: one.key, act: 'opened' });
        if (host().go) host().go(one.link);
        else location.href = one.link;
      });
      acts.appendChild(open);
      var seen = el('button', 'bf-btn', 'Let it be');
      seen.type = 'button';
      seen.title = 'Put it away';
      seen.addEventListener('click', function () { notOpenedPut(n, one); });
      acts.appendChild(seen);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function notOpenedRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-not_opened');
    if (!B.data || !B.data.not_opened) return;
    var holder = document.createDocumentFragment();
    drawNotOpened(holder, B.data.not_opened);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function notOpenedPost(body) {
    return fetch('/api/brief/not_opened', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function notOpenedPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Let be: ' + one.title + '.' };
    B.notOpened.said = said;
    notOpenedRedraw();
    notOpenedPost({ key: one.key, act: 'seen' }).then(function (j) {
      if (!j || !j.error || B.notOpened.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.notOpened.said = { bad: true, text: 'That could not be kept. Try again.' };
      notOpenedRedraw();
    });
  }

  function notOpenedUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.notOpened.said = null;
    notOpenedRedraw();
    notOpenedPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.notOpened.said = { bad: true, text: 'It could not be brought back. Try again.' };
      notOpenedRedraw();
    });
  }

  // New comments on your documents (29 October 2026, `rouh/new_comments.py`): a comment left in
  // the last days on a Google document one of his tasks links to, by somebody else, with no
  // answer from him or Rouh yet. Open the comment opens it in its document; Open the task the
  // task's page; Let it be puts it away, with Undo. A line goes by itself once it is answered.
  function drawNewComments(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.newComments.said;
    if (!items.length && !said) return;
    var sec = section('new_comments', 'New comments on your documents', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { newCommentsUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-newcomment-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.who + ' on ' + one.doc));
      head.appendChild(el('span', 'bf-ghost-days', one.day));
      li.appendChild(head);
      if (one.on) li.appendChild(el('p', 'bf-note bf-newcomment-on', '\u201c' + one.on + '\u201d'));
      li.appendChild(el('p', 'bf-newcomment-words', one.words));
      if (one.task) {
        li.appendChild(el('p', 'bf-note', one.kind + ' linked in task ' + one.task.number + ', ' +
          one.task.title + (one.answers ? '. Answered by somebody else, not by you.' : '.')));
      }
      var acts = el('div', 'bf-ghost-acts');
      var open = out(one.link, 'bf-btn', 'Open the comment', 'The comment in its document, in Google');
      open.addEventListener('click', function () { newCommentsPost({ key: one.key, act: 'opened' }); });
      acts.appendChild(open);
      if (one.task) {
        var task = goLink(el('a', 'bf-btn', 'Open the task'), one.task.link);
        task.addEventListener('click', function (e) {
          e.preventDefault();
          newCommentsPost({ key: one.key, act: 'task' });
          if (host().go) host().go(one.task.link);
          else location.href = one.task.link;
        });
        acts.appendChild(task);
      }
      var seen = el('button', 'bf-btn', 'Let it be');
      seen.type = 'button';
      seen.title = 'Put it away';
      seen.addEventListener('click', function () { newCommentsPut(n, one); });
      acts.appendChild(seen);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function newCommentsRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-new_comments');
    if (!B.data || !B.data.new_comments) return;
    var holder = document.createDocumentFragment();
    drawNewComments(holder, B.data.new_comments);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function newCommentsPost(body) {
    return fetch('/api/brief/new_comments', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function newCommentsPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Let be: ' + one.who + ' on ' + one.doc + '.' };
    B.newComments.said = said;
    newCommentsRedraw();
    newCommentsPost({ key: one.key, act: 'seen' }).then(function (j) {
      if (!j || !j.error || B.newComments.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.newComments.said = { bad: true, text: 'That could not be kept. Try again.' };
      newCommentsRedraw();
    });
  }

  function newCommentsUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.newComments.said = null;
    newCommentsRedraw();
    newCommentsPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.newComments.said = { bad: true, text: 'It could not be brought back. Try again.' };
      newCommentsRedraw();
    });
  }

  // The deck for your talk (30 October 2026, `rouh/talk_deck.py`): a Google Slides deck named
  // with today's or tomorrow's date, when something in it is still open: slides with no speaker
  // notes, comments nobody of his answered, a change somebody else made. Open the deck, the first
  // slide with no notes or a comment; Let it be puts that version away, with Undo.
  function drawTalkDeck(body, n) {
    var decks = (n.ok && n.decks) || [];
    var said = B.talkDeck.said;
    if (!decks.length && !said) return;
    var sec = section('talk_deck', 'The deck for your talk', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { talkDeckUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!decks.length) return;
    var list = el('ol', 'bf-ghost-list');
    decks.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-talkdeck');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.name));
      head.appendChild(el('span', 'bf-ghost-days', 'Talk ' + one.when + ' \u00b7 ' + one.slides + ' slides'));
      li.appendChild(head);
      if (one.no_notes && one.no_notes.length) {
        var notes = el('p', 'bf-talkdeck-notes', one.no_notes.length === 1
          ? 'Slide ' + one.no_notes_said + ' has no speaker notes. '
          : one.no_notes.length + ' slides have no speaker notes: ' + one.no_notes_said + '. ');
        var first = out(one.first_no_notes, 'bf-link', 'Open slide ' + one.no_notes[0],
          'The deck in Google Slides, on the first slide with no notes');
        first.addEventListener('click', function () { talkDeckPost({ key: one.key, act: 'slide' }); });
        notes.appendChild(first);
        li.appendChild(notes);
      }
      if (one.comments && one.comments.length) {
        li.appendChild(el('p', 'bf-note', one.open === 1 ? '1 comment not answered yet:'
          : one.open + ' comments not answered yet' + (one.open > one.comments.length ? ', the first ' + one.comments.length : '') + ':'));
        var cl = el('ul', 'bf-talkdeck-cmts');
        one.comments.forEach(function (c) {
          var ci = el('li', 'bf-talkdeck-cmt');
          ci.appendChild(el('p', 'bf-talkdeck-who', c.who + (c.slide ? ' on slide ' + c.slide : '') + ', ' + c.day));
          if (c.on) ci.appendChild(el('p', 'bf-note bf-newcomment-on', '\u201c' + c.on + '\u201d'));
          ci.appendChild(el('p', 'bf-newcomment-words', c.words));
          var open = out(c.link, 'bf-link', 'Open the comment', 'The comment in the deck, in Google Slides');
          open.addEventListener('click', function () { talkDeckPost({ key: one.key, act: 'comment' }); });
          ci.appendChild(open);
          cl.appendChild(ci);
        });
        li.appendChild(cl);
      }
      if (one.changed) li.appendChild(el('p', 'bf-note', one.changed));
      var acts = el('div', 'bf-ghost-acts');
      var deck = out(one.link, 'bf-btn', 'Open the deck', 'The deck in Google Slides');
      deck.addEventListener('click', function () { talkDeckPost({ key: one.key, act: 'opened' }); });
      acts.appendChild(deck);
      var seen = el('button', 'bf-btn', 'Let it be');
      seen.type = 'button';
      seen.title = 'Put it away until the deck changes again';
      seen.addEventListener('click', function () { talkDeckPut(n, one); });
      acts.appendChild(seen);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function talkDeckRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-talk_deck');
    if (!B.data || !B.data.talk_deck) return;
    var holder = document.createDocumentFragment();
    drawTalkDeck(holder, B.data.talk_deck);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function talkDeckPost(body) {
    return fetch('/api/brief/talk_deck', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function talkDeckPut(n, one) {
    var at = n.decks.indexOf(one);
    if (at < 0) return;
    n.decks.splice(at, 1);
    var said = { one: one, at: at, text: 'Let be: ' + one.name + ', until it changes again.' };
    B.talkDeck.said = said;
    talkDeckRedraw();
    talkDeckPost({ key: one.key, act: 'seen' }).then(function (j) {
      if (!j || !j.error || B.talkDeck.said !== said) return;
      if (n.decks.indexOf(one) < 0) n.decks.splice(Math.min(at, n.decks.length), 0, one);
      B.talkDeck.said = { bad: true, text: 'That could not be kept. Try again.' };
      talkDeckRedraw();
    });
  }

  function talkDeckUndo(n, said) {
    if (n.decks.indexOf(said.one) < 0) n.decks.splice(Math.min(said.at, n.decks.length), 0, said.one);
    B.talkDeck.said = null;
    talkDeckRedraw();
    talkDeckPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.decks.indexOf(said.one);
      if (i >= 0) n.decks.splice(i, 1);
      B.talkDeck.said = { bad: true, text: 'It could not be brought back. Try again.' };
      talkDeckRedraw();
    });
  }

  // Made, not handed over (31 October 2026, `rouh/not_handed.py`): work a task's notes say is to be
  // handed to somebody by name, never shared with them. Open the task opens it, where Share is;
  // Handed over puts it away, with Undo. None is no section.
  function drawNotHanded(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.notHanded.said;
    if (!items.length && !said) return;
    var sec = section('not_handed', 'Made, not handed over', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { notHandedUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-nothanded');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', 'For ' + one.person));
      head.appendChild(el('span', 'bf-ghost-days', 'since ' + one.since + ' \u00b7 '
        + (one.days === 1 ? '1 day' : one.days + ' days')));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-nothanded-task', 'Task ' + one.number + ' \u00b7 ' + one.title));
      li.appendChild(el('p', 'bf-newcomment-words', one.words));
      li.appendChild(el('p', 'bf-note', 'Not shared with ' + one.person + ' yet.'));
      var acts = el('div', 'bf-ghost-acts');
      var task = goLink(el('a', 'bf-btn', 'Open the task'), one.link);
      task.title = 'The task, where Share is';
      task.addEventListener('click', function (e) {
        e.preventDefault();
        notHandedPost({ key: one.key, act: 'task' });
        if (host().go) host().go(one.link);
        else location.href = one.link;
      });
      acts.appendChild(task);
      var handed = el('button', 'bf-btn', 'Handed over');
      handed.type = 'button';
      handed.title = 'It went another way, by email or in a meeting: put it away';
      handed.addEventListener('click', function () { notHandedPut(n, one); });
      acts.appendChild(handed);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) {
      sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
    }
  }

  function notHandedRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-not_handed');
    if (!B.data || !B.data.not_handed) return;
    var holder = document.createDocumentFragment();
    drawNotHanded(holder, B.data.not_handed);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function notHandedPost(body) {
    return fetch('/api/brief/not_handed', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function notHandedPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Handed over: task ' + one.number + ', for ' + one.person + '.' };
    B.notHanded.said = said;
    notHandedRedraw();
    notHandedPost({ key: one.key, act: 'handed' }).then(function (j) {
      if (!j || !j.error || B.notHanded.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.notHanded.said = { bad: true, text: 'That could not be kept. Try again.' };
      notHandedRedraw();
    });
  }

  function notHandedUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.notHanded.said = null;
    notHandedRedraw();
    notHandedPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.notHanded.said = { bad: true, text: 'It could not be brought back. Try again.' };
      notHandedRedraw();
    });
  }

  // Dates your tasks wait on (1 November 2026, `rouh/task_dates.py`): a date an open task's notes
  // say something is due by, passed (first) or in the coming week. What it says opens the line as the
  // notes have it; Open the task opens it; Done puts it away, with Undo. None is no section.
  function drawTaskDates(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.taskDates.said;
    if (!items.length && !said) return;
    var sec = section('task_dates', 'Dates your tasks wait on', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { taskDatesUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-taskdate' + (one.days < 0 ? ' is-passed' : ''));
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.on));
      head.appendChild(el('span', 'bf-ghost-days', one.when));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-nothanded-task', 'Task ' + one.number + ' \u00b7 ' + one.title));
      li.appendChild(el('p', 'bf-newcomment-words', '\u201c' + one.words + '\u201d'));
      li.appendChild(el('p', 'bf-note', one.days < 0
        ? 'Passed, and the task still says it waits on it.'
        : 'Coming up, and the task is still open.'));
      var about = el('details', 'bf-raise-read bf-taskdate-about');
      about.appendChild(el('summary', '', 'What it says'));
      about.appendChild(el('p', 'bf-taskdate-line', one.line));
      if (one.written) about.appendChild(el('p', 'bf-note', 'In the notes since ' + one.written + '.'));
      about.addEventListener('toggle', function () {
        if (about.open && !about.__told) { about.__told = true; taskDatesPost({ key: one.key, act: 'context' }); }
      });
      li.appendChild(about);
      var acts = el('div', 'bf-ghost-acts');
      var task = goLink(el('a', 'bf-btn', 'Open the task'), one.link);
      task.addEventListener('click', function (e) {
        e.preventDefault();
        taskDatesPost({ key: one.key, act: 'task' });
        if (host().go) host().go(one.link);
        else location.href = one.link;
      });
      acts.appendChild(task);
      var done = el('button', 'bf-btn', 'Done');
      done.type = 'button';
      done.title = 'It was met, or nothing waits on it any more: put it away';
      done.addEventListener('click', function () { taskDatesPut(n, one); });
      acts.appendChild(done);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) {
      sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
    }
  }

  function taskDatesRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-task_dates');
    if (!B.data || !B.data.task_dates) return;
    var holder = document.createDocumentFragment();
    drawTaskDates(holder, B.data.task_dates);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function taskDatesPost(body) {
    return fetch('/api/brief/task_dates', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function taskDatesPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Done: task ' + one.number + ', ' + one.on + '.' };
    B.taskDates.said = said;
    taskDatesRedraw();
    taskDatesPost({ key: one.key, act: 'done' }).then(function (j) {
      if (!j || !j.error || B.taskDates.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.taskDates.said = { bad: true, text: 'That could not be kept. Try again.' };
      taskDatesRedraw();
    });
  }

  function taskDatesUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.taskDates.said = null;
    taskDatesRedraw();
    taskDatesPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.taskDates.said = { bad: true, text: 'It could not be brought back. Try again.' };
      taskDatesRedraw();
    });
  }

  // Your word, by mail (night 36, 7 November 2026, `rouh/my_word.py`): what he promised somebody
  // by email by a day that is today, tomorrow or passed, and he has not written to them since. What
  // you wrote opens the sentence in its email; Open the email opens the conversation in Gmail, to send
  // it from there; Done puts it away, with Undo. None is no section.
  function drawMyWord(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.myWord.said;
    if (!items.length && !said) return;
    var sec = section('my_word', 'Your word, by mail', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { myWordUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-myword' + (one.days < 0 ? ' is-passed' : ''));
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', 'To ' + one.to + (one.others ? ' and ' + one.others + (one.others === 1 ? ' other' : ' others') : '')));
      head.appendChild(el('span', 'bf-ghost-days', 'Due ' + one.when));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-newcomment-words', '\u201c' + one.sentence + '\u201d'));
      li.appendChild(el('p', 'bf-note', one.days < 0
        ? 'You said ' + one.said_when + ', and you have not written to them since.'
        : 'You said ' + one.said_when + '.'));
      var about = el('details', 'bf-raise-read bf-myword-about');
      about.appendChild(el('summary', '', 'What you wrote'));
      about.appendChild(el('p', 'bf-taskdate-line', 'Subject: ' + one.subject));
      about.appendChild(el('p', 'bf-note', 'Sent ' + one.sent + ' to ' + one.to + (one.email && one.email !== one.to ? ' <' + one.email + '>' : '')
        + ', from ' + one.mailbox + (one.read_only ? ' (read-only)' : '') + '.'));
      about.addEventListener('toggle', function () {
        if (about.open && !about.__told) { about.__told = true; myWordPost({ key: one.key, act: 'context' }); }
      });
      li.appendChild(about);
      var acts = el('div', 'bf-ghost-acts');
      var open = out(one.link, 'bf-btn', 'Open the email', 'The conversation in Gmail, to send what you promised from there');
      open.addEventListener('click', function () { myWordPost({ key: one.key, act: 'open' }); });
      acts.appendChild(open);
      var done = el('button', 'bf-btn', 'Mark as done');
      done.type = 'button';
      done.title = 'You kept it, or it is not needed any more: take it off this list (you can undo it)';
      done.addEventListener('click', function () { myWordPut(n, one); });
      acts.appendChild(done);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) {
      sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
    }
  }

  function myWordRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-my_word');
    if (!B.data || !B.data.my_word) return;
    var holder = document.createDocumentFragment();
    drawMyWord(holder, B.data.my_word);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function myWordPost(body) {
    return fetch('/api/brief/my_word', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function myWordPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Marked as done and taken off the list: your promise to ' + one.to + '. Nobody was told.' };
    B.myWord.said = said;
    myWordRedraw();
    myWordPost({ key: one.key, act: 'done' }).then(function (j) {
      if (!j || !j.error || B.myWord.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.myWord.said = { bad: true, text: 'That could not be kept. Try again.' };
      myWordRedraw();
    });
  }

  function myWordUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.myWord.said = null;
    myWordRedraw();
    myWordPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.myWord.said = { bad: true, text: 'It could not be brought back. Try again.' };
      myWordRedraw();
    });
  }

  // Who lets the note-taker in (2 November 2026, `rouh/host_admits.py`): today's and tomorrow's calls
  // somebody outside his company hosts, where only the host or a co-host can let the meeting
  // library's note-taker in. Ask the host opens a note to them in his own Gmail and marks the line
  // asked; No notes needed puts it away, with Undo; Who is in it opens the guests. None is no section.
  function drawHostAdmits(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.hostAdmits.said;
    if (!items.length && !said) return;
    var sec = section('host_admits', 'Who lets the note-taker in', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { hostAdmitsUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    sec.appendChild(el('p', 'bf-note bf-hostadmits-lead', (items.length === 1 ? 'One call' : items.length + ' calls') +
      ' coming up ' + (items.length === 1 ? 'is' : 'are') + ' hosted by somebody outside your company. ' +
      'The note-taker waits in the lobby, and only the host or a co-host can let it in.'));
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-hostadmits-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The event in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ' ' + one.time));
      li.appendChild(head);
      var who = el('p', 'bf-note', 'Hosted by ');
      who.appendChild(el('b', null, one.host));
      if (one.host_email && one.host_email !== one.host) who.appendChild(document.createTextNode(' (' + one.host_email + ')'));
      who.appendChild(document.createTextNode(' on ' + one.platform + ': only they or a co-host can let the note-taker in.'));
      li.appendChild(who);
      if (one.asked) li.appendChild(el('p', 'bf-note bf-hostadmits-asked', 'You opened a note to them on ' + dayWords(one.asked) + '.'));
      if (one.guests && one.guests.length) {
        var about = el('details', 'bf-raise-read bf-hostadmits-guests');
        about.appendChild(el('summary', '', 'Who is in it'));
        about.appendChild(el('p', 'bf-note', one.guests.join(', ')));
        about.addEventListener('toggle', function () {
          if (about.open && !about.__told) { about.__told = true; hostAdmitsPost({ key: one.key, act: 'guests' }); }
        });
        li.appendChild(about);
      }
      var acts = el('div', 'bf-ghost-acts');
      var first = String(one.host || '').split(/[\s@]/)[0] || 'the host';
      var ask = out(one.compose, 'bf-btn', 'Ask ' + first + ' to let it in', 'A note to ' + first + ' in your own Gmail, for you to send');
      ask.addEventListener('click', function () {
        one.asked = Date.now() / 1000;
        hostAdmitsPost({ key: one.key, act: 'asked' });
        setTimeout(hostAdmitsRedraw, 0);
      });
      acts.appendChild(ask);
      var none = el('button', 'bf-btn', 'No notes needed');
      none.type = 'button';
      none.title = 'This call is not to be recorded: put it away';
      none.addEventListener('click', function () { hostAdmitsPut(n, one); });
      acts.appendChild(none);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) {
      sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
    }
  }

  function hostAdmitsRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-host_admits');
    if (!B.data || !B.data.host_admits) return;
    var holder = document.createDocumentFragment();
    drawHostAdmits(holder, B.data.host_admits);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  // Flights left open (night 32, `rouh/flight_open.py`): a flight in the next two weeks, on a
  // calendar of its own, during which his main calendar - the one people booking him see - says
  // free. Block it as out of office puts Google's own out-of-office there; Not needed puts the
  // line away, with Undo. None is no section.
  function drawFlightOpen(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.flightOpen.said;
    if (!items.length && !said) return;
    var sec = section('flight_open', 'Flights left open', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { flightOpenUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var open = items.filter(function (one) { return !one.blocked; }).length;
    if (open) {
      sec.appendChild(el('p', 'bf-note bf-flight-lead', (open === 1 ? 'One flight is' : open + ' flights are') +
        ' on another calendar, and your main calendar - the one people see when they book you - shows you free then.'));
    }
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-flight-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The flight in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ', ' + one.time));
      li.appendChild(head);
      if (one.calendar) li.appendChild(el('p', 'bf-note', 'On ' + one.calendar + '.'));
      if (one.clashes && one.clashes.length) {
        var c = el('p', 'bf-note bf-flight-clash', 'Already in that time on your main calendar: ');
        one.clashes.forEach(function (m, i) {
          if (i) c.appendChild(document.createTextNode('; '));
          c.appendChild(m.link ? out(m.link, 'bf-link', m.title, 'The meeting in Google Calendar') : el('b', null, m.title));
          c.appendChild(document.createTextNode(' at ' + m.time));
        });
        c.appendChild(document.createTextNode('. A block does not decline these.'));
        li.appendChild(c);
      }
      var acts = el('div', 'bf-ghost-acts');
      if (one.blocked) {
        var done = el('p', 'bf-note bf-flight-done', 'Blocked as out of office on your main calendar. ');
        if (one.blocked_link) done.appendChild(out(one.blocked_link, 'bf-link', 'Open it', 'The block in Google Calendar'));
        li.appendChild(done);
      } else {
        var block = el('button', 'bf-btn', one.busy ? 'Blocking...' : 'Block it as out of office');
        block.type = 'button';
        block.disabled = !!one.busy;
        block.title = 'Google declines new invitations for that time, with a short note';
        block.addEventListener('click', function () { flightOpenBlock(n, one); });
        acts.appendChild(block);
        var none = el('button', 'bf-btn', 'Not needed');
        none.type = 'button';
        none.title = 'Leave the main calendar as it is: put this line away';
        none.addEventListener('click', function () { flightOpenPut(n, one); });
        acts.appendChild(none);
        li.appendChild(acts);
      }
      if (one.fault) li.appendChild(el('p', 'bf-note bad', one.fault));
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
  }

  function flightOpenRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-flight_open');
    if (!B.data || !B.data.flight_open) return;
    var holder = document.createDocumentFragment();
    drawFlightOpen(holder, B.data.flight_open);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function flightOpenPost(body) {
    return fetch('/api/brief/flight_open', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function flightOpenBlock(n, one) {
    one.busy = true;
    one.fault = '';
    flightOpenRedraw();
    flightOpenPost({ key: one.key, act: 'block', calendar_id: one.calendar_id, event_id: one.event_id }).then(function (j) {
      one.busy = false;
      if (!j || j.error) {
        one.fault = 'It was not blocked: ' + ((j && j.error) || 'try again.');
      } else {
        one.blocked = Date.now() / 1000;
        one.blocked_link = j.link || '';
      }
      flightOpenRedraw();
    });
  }

  function flightOpenPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not needed: ' + one.title + '.' };
    B.flightOpen.said = said;
    flightOpenRedraw();
    flightOpenPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.flightOpen.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.flightOpen.said = { bad: true, text: 'That could not be kept. Try again.' };
      flightOpenRedraw();
    });
  }

  function flightOpenUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.flightOpen.said = null;
    flightOpenRedraw();
    flightOpenPost({ key: said.one.key, act: 'undo' });
  }

  // Invitations not in your calendar (night 33, `rouh/invite_missing.py`): an invitation in his own
  // mail whose meeting is on none of his calendars, because Google adds one by itself only from a
  // sender it knows. Put it in my calendar adds it as the same meeting; Not needed puts the line
  // away, with Undo. None is no section.
  function drawInviteMissing(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.inviteMissing.said;
    if (!items.length && !said) return;
    var sec = section('invite_missing', 'Invitations not in your calendar', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { inviteMissingUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var open = items.filter(function (one) { return !one.added; }).length;
    if (open) {
      sec.appendChild(el('p', 'bf-note bf-invite-lead', (open === 1 ? 'One invitation in your mail is' : open + ' invitations in your mail are') +
        ' on none of your calendars, so the time looks free and no reminder will come.'));
    }
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-invite-line');
      var head = el('p', 'bf-ghost-head');
      var mail = one.message && one.inbox
        ? 'https://mail.google.com/mail/u/' + encodeURIComponent(one.inbox) + '/#all/' + encodeURIComponent(one.message) : '';
      head.appendChild(mail ? out(mail, 'bf-ghost-who bf-link', one.title, 'The invitation in Gmail')
                            : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ', ' + one.time));
      li.appendChild(head);
      var from = (one.changed ? 'A changed invitation from ' : 'From ') + (one.who || 'somebody') +
        (one.email && one.email !== one.who ? ' (' + one.email + ')' : '') + ', to ' + one.inbox + '.';
      li.appendChild(el('p', 'bf-note', from));
      var bits = [];
      if (one.theirs) bits.push('They wrote ' + one.theirs + '; the time above is yours.');
      if (one.where && one.where !== one.call) bits.push('Where: ' + one.where + '.');
      if (bits.length) li.appendChild(el('p', 'bf-note', bits.join(' ')));
      if (one.call) {
        var call = el('p', 'bf-note');
        call.appendChild(out(one.call, 'bf-link', one.call_on ? 'Join on ' + one.call_on : 'Join the call', 'Opens the call'));
        li.appendChild(call);
      }
      if (one.added) {
        var done = el('p', 'bf-note bf-invite-done', 'On your calendar now. ');
        if (one.added_link) done.appendChild(out(one.added_link, 'bf-link', 'Open it', 'The meeting in Google Calendar'));
        li.appendChild(done);
      } else {
        var acts = el('div', 'bf-ghost-acts');
        var add = el('button', 'bf-btn', one.busy ? 'Putting it in...' : 'Put it in my calendar');
        add.type = 'button';
        add.disabled = !!one.busy;
        add.title = 'Adds it to your main calendar as the same meeting, so a later change from them finds it. Nobody is emailed.';
        add.addEventListener('click', function () { inviteMissingAdd(n, one); });
        acts.appendChild(add);
        var none = el('button', 'bf-btn', 'Not needed');
        none.type = 'button';
        none.title = 'Leave it out of the calendar: put this line away';
        none.addEventListener('click', function () { inviteMissingPut(n, one); });
        acts.appendChild(none);
        li.appendChild(acts);
      }
      if (one.fault) li.appendChild(el('p', 'bf-note bad', one.fault));
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
  }

  function inviteMissingRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-invite_missing');
    if (!B.data || !B.data.invite_missing) return;
    var holder = document.createDocumentFragment();
    drawInviteMissing(holder, B.data.invite_missing);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function inviteMissingPost(body) {
    return fetch('/api/brief/invite_missing', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function inviteMissingAdd(n, one) {
    one.busy = true;
    one.fault = '';
    inviteMissingRedraw();
    inviteMissingPost({ key: one.key, act: 'add' }).then(function (j) {
      one.busy = false;
      if (!j || j.error) {
        one.fault = 'It was not put in: ' + ((j && j.error) || 'try again.');
      } else {
        one.added = Date.now() / 1000;
        one.added_link = j.link || '';
      }
      inviteMissingRedraw();
    });
  }

  function inviteMissingPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not needed: ' + one.title + '.' };
    B.inviteMissing.said = said;
    inviteMissingRedraw();
    inviteMissingPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.inviteMissing.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.inviteMissing.said = { bad: true, text: 'That could not be kept. Try again.' };
      inviteMissingRedraw();
    });
  }

  function inviteMissingUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.inviteMissing.said = null;
    inviteMissingRedraw();
    inviteMissingPost({ key: said.one.key, act: 'undo' });
  }

  // Meetings with nowhere to meet (night 33, second run, `rouh/no_place.py`): a meeting of his in
  // the next days with guests and no place, no call and no call link. Add a Meet link has Google
  // give it one, the way Add Google Meet does, and the guests are told; Not needed puts the line
  // away, with Undo. None is no section.
  function drawNoPlace(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.noPlace.said;
    if (!items.length && !said) return;
    var sec = section('no_place', 'Meetings with nowhere to meet', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { noPlaceUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var open = items.filter(function (one) { return !one.added; }).length;
    if (open) {
      sec.appendChild(el('p', 'bf-note bf-noplace-lead', (open === 1 ? 'One of your meetings has' : open + ' of your meetings have') +
        ' guests but no place and no call link, so they will not know where to go.'));
    }
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-noplace-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The meeting in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ', ' + one.time));
      li.appendChild(head);
      if (one.who) li.appendChild(el('p', 'bf-note', 'With ' + one.who + '.'));
      if (one.added) {
        var done = el('p', 'bf-note bf-noplace-done', 'You added a Meet link; Google sent the guests the updated invitation. ');
        if (one.video) done.appendChild(out(one.video, 'bf-link', 'Join on Google Meet', 'Opens the call'));
        li.appendChild(done);
      } else {
        var acts = el('div', 'bf-ghost-acts');
        var add = el('button', 'bf-btn', one.busy ? 'Adding...' : 'Add a Meet link');
        add.type = 'button';
        add.disabled = !!one.busy;
        add.title = 'Google adds a Meet link to the meeting and tells the guests';
        add.addEventListener('click', function () { noPlaceAdd(n, one); });
        acts.appendChild(add);
        var none = el('button', 'bf-btn', 'Not needed');
        none.type = 'button';
        none.title = 'Everybody knows where it is: put this line away';
        none.addEventListener('click', function () { noPlacePut(n, one); });
        acts.appendChild(none);
        li.appendChild(acts);
      }
      if (one.fault) li.appendChild(el('p', 'bf-note bad', one.fault));
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
  }

  function noPlaceRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-no_place');
    if (!B.data || !B.data.no_place) return;
    var holder = document.createDocumentFragment();
    drawNoPlace(holder, B.data.no_place);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) body.appendChild(holder);
  }

  function noPlacePost(body) {
    return fetch('/api/brief/no_place', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function noPlaceAdd(n, one) {
    one.busy = true;
    one.fault = '';
    noPlaceRedraw();
    noPlacePost({ key: one.key, act: 'add', calendar_id: one.calendar_id, event_id: one.event_id }).then(function (j) {
      one.busy = false;
      if (!j || j.error) {
        one.fault = 'No link was added: ' + ((j && j.error) || 'try again.');
      } else {
        one.added = Date.now() / 1000;
        one.video = j.video || '';
      }
      noPlaceRedraw();
    });
  }

  function noPlacePut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not needed: ' + one.title + '.' };
    B.noPlace.said = said;
    noPlaceRedraw();
    noPlacePost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.noPlace.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.noPlace.said = { bad: true, text: 'That could not be kept. Try again.' };
      noPlaceRedraw();
    });
  }

  function noPlaceUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.noPlace.said = null;
    noPlaceRedraw();
    noPlacePost({ key: said.one.key, act: 'undo' });
  }

  // Invitations you have not answered (night 36, `rouh/not_answered.py`): a meeting somebody else
  // invited him to, today or tomorrow, that he never answered. Yes, Maybe and No answer it in his
  // calendar, and Google tells the organiser; Not now puts the line away, with Undo.
  function drawNotAnswered(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.notAnswered.said;
    if (!items.length && !said) return;
    var sec = section('not_answered', 'Invitations you have not answered', n);
    body.appendChild(sec);
    if (items.length) {
      sec.appendChild(el('p', 'bf-note', items.length === 1
        ? 'Somebody invited you to this and does not know yet whether you are coming.'
        : 'Somebody invited you to each of these and does not know yet whether you are coming.'));
    }
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { notAnsweredUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-nan-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The meeting in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ', ' + one.time));
      li.appendChild(head);
      var words = [];
      words.push((one.organiser || 'Somebody') + ' invited you.');
      if (one.others) {
        words.push(one.others_yes === one.others
          ? (one.others === 1 ? 'The other guest has said yes.' : 'All ' + one.others + ' other guests have said yes.')
          : one.others_yes + ' of the ' + one.others + ' other guest' + (one.others === 1 ? '' : 's') + ' said yes.');
      }
      if (one.in_minutes >= 0 && one.in_minutes < 120) words.push('It starts in ' + (one.in_minutes < 60
        ? one.in_minutes + ' minutes.' : 'about an hour.'));
      li.appendChild(el('p', 'bf-note', words.join(' ')));
      var acts = el('div', 'bf-ghost-acts');
      var busy = B.notAnswered.busy === one.key;
      [['accepted', 'Yes'], ['tentative', 'Maybe'], ['declined', 'No']].forEach(function (pair) {
        var b = el('button', 'bf-btn', pair[1]);
        b.type = 'button';
        b.disabled = !!B.notAnswered.busy;
        b.title = 'Answer ' + pair[1] + ' in your calendar; Google tells ' + (one.organiser || 'the organiser');
        b.addEventListener('click', function () { notAnsweredAnswer(n, one, pair[0], pair[1]); });
        acts.appendChild(b);
      });
      var later = el('button', 'bf-btn', 'Not now');
      later.type = 'button';
      later.disabled = !!B.notAnswered.busy;
      later.title = 'Put this line away without answering';
      later.addEventListener('click', function () { notAnsweredPut(n, one); });
      acts.appendChild(later);
      if (busy) acts.appendChild(el('span', 'bf-note', 'Answering...'));
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
  }

  function notAnsweredRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-not_answered');
    if (!B.data || !B.data.not_answered) return;
    var holder = document.createDocumentFragment();
    drawNotAnswered(holder, B.data.not_answered);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) {
      var cal = body.querySelector('.bf-sec.bf-calendar');
      if (cal) cal.before(holder); else body.appendChild(holder);
    }
  }

  function notAnsweredPost(body) {
    return fetch('/api/brief/not_answered', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function notAnsweredAnswer(n, one, answer, word) {
    if (B.notAnswered.busy) return;
    B.notAnswered.busy = one.key;
    notAnsweredRedraw();
    notAnsweredPost({ key: one.key, act: answer, event_id: one.event_id, calendar_id: one.calendar_id }).then(function (j) {
      B.notAnswered.busy = '';
      if (!j) return;
      if (j.error) {
        B.notAnswered.said = { bad: true, text: 'Not answered: ' + j.error };
      } else {
        var at = n.items.indexOf(one);
        if (at >= 0) n.items.splice(at, 1);
        if (n.count) n.count -= 1;
        B.notAnswered.said = { text: 'Answered ' + word + ' to ' + one.title + '. Google told '
          + (j.organiser || one.organiser || 'the organiser') + '.' };
      }
      notAnsweredRedraw();
    });
  }

  function notAnsweredPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not now: ' + one.title + ', not answered.' };
    B.notAnswered.said = said;
    notAnsweredRedraw();
    notAnsweredPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.notAnswered.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.notAnswered.said = { bad: true, text: 'That could not be kept. Try again.' };
      notAnsweredRedraw();
    });
  }

  function notAnsweredUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.notAnswered.said = null;
    notAnsweredRedraw();
    notAnsweredPost({ key: said.one.key, act: 'undo' });
  }

  // Gone quiet (night 36, `rouh/gone_quiet.py`): a company he met regularly that has stopped meeting
  // him, with nothing booked. When you met, closed at first, lists the meetings; Write to them opens
  // his own Gmail to the people he last met there; Not now puts the line away, with Undo.
  function drawGoneQuiet(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.goneQuiet.said;
    if (!items.length && !said) return;
    var sec = section('gone_quiet', 'Gone quiet', n);
    body.appendChild(sec);
    if (items.length) {
      sec.appendChild(el('p', 'bf-note', items.length === 1
        ? 'You used to meet them regularly. It has been more than twice as long as usual, and nothing is booked.'
        : 'You used to meet each of these regularly. It has been more than twice as long as usual, and nothing is booked.'));
    }
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { goneQuietUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-quiet-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.company));
      head.appendChild(el('span', 'bf-ghost-days', one.silent + ' days'));
      li.appendChild(head);
      li.appendChild(el('p', 'bf-note', one.said));
      if ((one.meetings || []).length) {
        var met = el('details', 'bf-raise-read');
        met.appendChild(el('summary', '', 'When you met'));
        var ml = el('ul', 'bf-raise-mails');
        one.meetings.forEach(function (m) {
          var row = el('li', 'bf-raise-mail');
          row.appendChild(el('span', 'bf-prep-when', m.when));
          row.appendChild(el('span', 'bf-prep-subj', m.title + ((m.people || []).length ? ', with ' + m.people.join(', ') : '')));
          ml.appendChild(row);
        });
        met.appendChild(ml);
        li.appendChild(met);
      }
      var acts = el('div', 'bf-ghost-acts');
      if (one.write && (one.people || []).length) {
        var w = out(one.write, 'bf-btn', 'Write to them', 'A new email to ' + one.people.join(', ') + ' in your own Gmail');
        w.addEventListener('click', function () { goneQuietPost({ key: one.key, act: 'wrote' }); });
        acts.appendChild(w);
      }
      var later = el('button', 'bf-btn', 'Not now');
      later.type = 'button';
      later.title = 'Put this line away until you meet them again';
      later.addEventListener('click', function () { goneQuietPut(n, one); });
      acts.appendChild(later);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
  }

  function goneQuietRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-gone_quiet');
    if (!B.data || !B.data.gone_quiet) return;
    var holder = document.createDocumentFragment();
    drawGoneQuiet(holder, B.data.gone_quiet);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) {
      var cal = body.querySelector('.bf-sec.bf-calendar');
      if (cal) cal.after(holder); else body.appendChild(holder);
    }
  }

  function goneQuietPost(body) {
    return fetch('/api/brief/gone_quiet', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function goneQuietPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not now: ' + one.company + ' is put away until you meet them again.' };
    B.goneQuiet.said = said;
    goneQuietRedraw();
    goneQuietPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.goneQuiet.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.goneQuiet.said = { bad: true, text: 'That could not be kept. Try again.' };
      goneQuietRedraw();
    });
  }

  function goneQuietUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.goneQuiet.said = null;
    goneQuietRedraw();
    goneQuietPost({ key: said.one.key, act: 'undo' });
  }

  // Guests who have not said yes (night 34, `rouh/not_said_yes.py`): a meeting of his today or
  // tomorrow that nobody invited has accepted, or somebody declined. Write to them in Gmail opens
  // his own Gmail with a note to exactly those guests; Not needed puts the line away, with Undo.
  function drawNotSaidYes(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.notSaidYes.said;
    if (!items.length && !said) return;
    var sec = section('not_said_yes', 'Guests who have not said yes', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { notSaidYesUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    sec.appendChild(el('p', 'bf-note bf-noplace-lead', (items.length === 1 ? 'One of your meetings' : items.length + ' of your meetings') +
      ' today or tomorrow ' + (items.length === 1 ? 'has' : 'have') + ' guests who have not said yes. You can write to them from here.'));
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-nsy-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(one.link ? out(one.link, 'bf-ghost-who bf-link', one.title, 'The meeting in Google Calendar')
                                : el('span', 'bf-ghost-who', one.title));
      var day = String(one.day || '');
      head.appendChild(el('span', 'bf-ghost-days', day.charAt(0).toUpperCase() + day.slice(1) + ', ' + one.time));
      li.appendChild(head);
      var words = [];
      if (one.nobody) {
        words.push(one.asked === 1 ? 'Your guest has not accepted yet, so it may not happen.'
                                   : 'None of the ' + one.asked + ' guests has accepted yet, so it may not happen.');
      }
      if (one.declined) words.push(one.declined + ' declined.');
      if (one.waiting) words.push(one.waiting + (one.waiting_n === 1 ? ' has not answered.' : ' have not answered.'));
      li.appendChild(el('p', 'bf-note', words.join(' ')));
      var acts = el('div', 'bf-ghost-acts');
      if (one.write) {
        var write = out(one.write, 'bf-btn', one.write_to === 'declined' ? 'Ask for another time' : 'Write to them in Gmail',
                        one.write_to === 'declined' ? 'Opens a note in your own Gmail asking ' + one.declined + ' for another time, for you to send or not'
                                                    : 'Opens a note in your own Gmail to ' + one.waiting + ', for you to send or not');
        write.addEventListener('click', function () {
          one.wrote = true;
          notSaidYesPost({ key: one.key, act: 'wrote' });
          setTimeout(notSaidYesRedraw, 0);
        });
        acts.appendChild(write);
      }
      var none = el('button', 'bf-btn', 'Not needed');
      none.type = 'button';
      none.title = 'You know they are coming: put this line away';
      none.addEventListener('click', function () { notSaidYesPut(n, one); });
      acts.appendChild(none);
      li.appendChild(acts);
      if (one.wrote) {
        var to = one.write_to === 'declined' ? one.declined : one.waiting;
        var said = el('p', 'bf-note bf-noplace-done', 'Gmail opened in a new tab with a note to ' + to +
          ', written for you. Read it and press Send there; Rouh sends nothing.');
        said.setAttribute('role', 'status');
        li.appendChild(said);
      }
      list.appendChild(li);
    });
    sec.appendChild(list);
    if (n.count > items.length) sec.appendChild(el('p', 'bf-note', 'And ' + (n.count - items.length) + ' more.'));
    if (n.fine) {
      sec.appendChild(el('p', 'bf-note', (n.fine === 1 ? 'Your other meeting with guests today and tomorrow has'
                                                       : 'Your other ' + n.fine + ' meetings with guests today and tomorrow have') +
        ' a yes from the people invited.'));
    }
  }

  function notSaidYesRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-not_said_yes');
    if (!B.data || !B.data.not_said_yes) return;
    var holder = document.createDocumentFragment();
    drawNotSaidYes(holder, B.data.not_said_yes);
    if (old) old.replaceWith(holder);
    else if (body && holder.firstChild) {
      var cal = body.querySelector('.bf-sec.bf-calendar');
      if (cal) cal.before(holder); else body.appendChild(holder);
    }
  }

  function notSaidYesPost(body) {
    return fetch('/api/brief/not_said_yes', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function notSaidYesPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'Not needed: ' + one.title + '.' };
    B.notSaidYes.said = said;
    notSaidYesRedraw();
    notSaidYesPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.notSaidYes.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.notSaidYes.said = { bad: true, text: 'That could not be kept. Try again.' };
      notSaidYesRedraw();
    });
  }

  function notSaidYesUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.notSaidYes.said = null;
    notSaidYesRedraw();
    notSaidYesPost({ key: said.one.key, act: 'undo' });
  }

  // What to raise reads what is attached (night 31, `rouh/raise_attached.py`): his opening the
  // list of the attached documents it read, or one of them, is the gene's use.
  function raiseAttachedUsed(act, what) {
    fetch('/api/brief/raise_attached', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ act: act, what: String(what || '').slice(0, 120) })
    }).catch(function () { /* the use is not counted; nothing else changes */ });
  }

  function hostAdmitsPost(body) {
    return fetch('/api/brief/host_admits', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function hostAdmitsPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    if (n.count) n.count -= 1;
    var said = { one: one, at: at, text: 'No notes needed: ' + one.title + '.' };
    B.hostAdmits.said = said;
    hostAdmitsRedraw();
    hostAdmitsPost({ key: one.key, act: 'put' }).then(function (j) {
      if (!j || !j.error || B.hostAdmits.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.hostAdmits.said = { bad: true, text: 'That could not be kept. Try again.' };
      hostAdmitsRedraw();
    });
  }

  function hostAdmitsUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) {
      n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
      n.count = (n.count || 0) + 1;
    }
    B.hostAdmits.said = null;
    hostAdmitsRedraw();
    hostAdmitsPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.hostAdmits.said = { bad: true, text: 'It could not be brought back. Try again.' };
      hostAdmitsRedraw();
    });
  }

  // Agreed, not booked (23 October 2026, `rouh/next_meeting.py`): a next meeting agreed in one of
  // his meetings, with nothing in his calendar near that day. Book it puts it there with the same
  // guests, length and title; Not needed puts it away, with Undo. None is no section.
  function drawNextMeeting(body, n) {
    var items = (n.ok && n.items) || [];
    var said = B.nextMeeting.said;
    if (!items.length && !said) return;
    var sec = section('next_meeting', 'Agreed, not booked', n);
    body.appendChild(sec);
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.link) line.appendChild(out(said.link, 'bf-link', 'Open the event', 'The event in Google Calendar'));
      if (said.one && !said.link) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { nextMeetingUndo(n, said); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (!items.length) return;
    var list = el('ol', 'bf-ghost-list');
    items.forEach(function (one) {
      var li = el('li', 'bf-ghost bf-next-line');
      var head = el('p', 'bf-ghost-head');
      head.appendChild(el('span', 'bf-ghost-who', one.title));
      head.appendChild(el('span', 'bf-ghost-days', one.timed ? whenWords(one.at) : dayWords(one.at)));
      li.appendChild(head);
      var why = el('p', 'bf-note', 'Agreed in ');
      why.appendChild(one.page ? out(one.page, 'bf-link', 'the meeting', 'Its notes in the meeting library')
                               : document.createTextNode('the meeting'));
      why.appendChild(document.createTextNode(' of ' + dayWords(one.met_at) + ', and not in your calendar. With ' +
        one['with'].join(', ') + '.'));
      li.appendChild(why);
      var acts = el('div', 'bf-ghost-acts');
      var busy = B.nextMeeting.busy === one.key;
      var book = el('button', 'bf-btn', busy ? 'Booking…' : 'Book it');
      book.type = 'button';
      book.disabled = busy;
      book.title = 'Put it in your calendar for ' + (one.timed ? fullWhen(one.at) : dayWords(one.at) + ' at ' + clock(one.at)) +
        ', ' + one.minutes + ' minutes, and invite ' + one['with'].join(', ');
      book.addEventListener('click', function () { nextMeetingBook(n, one); });
      acts.appendChild(book);
      var none = el('button', 'bf-btn', 'Not needed');
      none.type = 'button';
      none.title = 'It will not happen, or is booked some other way: put it away';
      none.addEventListener('click', function () { nextMeetingPut(n, one); });
      acts.appendChild(none);
      li.appendChild(acts);
      list.appendChild(li);
    });
    sec.appendChild(list);
  }

  function nextMeetingRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-sec.bf-next_meeting');
    if (!B.data || !B.data.next_meeting) return;
    var holder = document.createDocumentFragment();
    drawNextMeeting(holder, B.data.next_meeting);
    if (old) old.replaceWith(holder);
    else if (body) {
      var after = body.querySelector('.bf-sec.bf-no_notes') || body.querySelector('.bf-sec.bf-owed');
      if (after) after.after(holder);
    }
  }

  function nextMeetingPost(body) {
    return fetch('/api/brief/next_meeting', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        return r.ok ? (j || {}) : { error: (j && j.error) || 'the server said ' + r.status + '.' };
      });
    }).catch(function () { return { error: 'Rouh could not be reached. Try again.' }; });
  }

  function nextMeetingBook(n, one) {
    if (B.nextMeeting.busy) return;
    B.nextMeeting.busy = one.key;
    nextMeetingRedraw();
    nextMeetingPost({ key: one.key, act: 'book' }).then(function (j) {
      B.nextMeeting.busy = '';
      if (!j) return;
      if (j.error) {
        B.nextMeeting.said = { bad: true, text: j.error };
      } else {
        var at = n.items.indexOf(one);
        if (at >= 0) n.items.splice(at, 1);
        B.nextMeeting.said = { text: 'Booked: ' + one.title + ', ' + dayWords(one.at) + ' at ' + clock(one.at) +
          (j.guests && j.guests.length ? ', and Google invited ' + j.guests.join(', ') + '.' : '.'),
          link: j.link || '' };
      }
      nextMeetingRedraw();
    });
  }

  function nextMeetingPut(n, one) {
    var at = n.items.indexOf(one);
    if (at < 0) return;
    n.items.splice(at, 1);
    var said = { one: one, at: at, text: 'Put away as not needed: ' + one.title + '.' };
    B.nextMeeting.said = said;
    nextMeetingRedraw();
    nextMeetingPost({ key: one.key, act: 'not_needed' }).then(function (j) {
      if (!j || !j.error || B.nextMeeting.said !== said) return;
      if (n.items.indexOf(one) < 0) n.items.splice(Math.min(at, n.items.length), 0, one);
      B.nextMeeting.said = { bad: true, text: 'That could not be kept. Try again.' };
      nextMeetingRedraw();
    });
  }

  function nextMeetingUndo(n, said) {
    if (n.items.indexOf(said.one) < 0) n.items.splice(Math.min(said.at, n.items.length), 0, said.one);
    B.nextMeeting.said = null;
    nextMeetingRedraw();
    nextMeetingPost({ key: said.one.key, act: 'undo' }).then(function (j) {
      if (!j || !j.error) return;
      var i = n.items.indexOf(said.one);
      if (i >= 0) n.items.splice(i, 1);
      B.nextMeeting.said = { bad: true, text: 'It could not be brought back. Try again.' };
      nextMeetingRedraw();
    });
  }

  // A video to watch: its title, linked, and its channel.
  function videoLine(one) {
    var li = el('li');
    li.appendChild(out(one.link, 'bf-link', one.title, 'Watch on YouTube'));
    li.appendChild(el('p', 'bf-link-sub', one.channel));
    return li;
  }

  function drawAi(body, a) {
    var chans = a.channels || [];
    var sec = section('ai', 'AI', a, chans.length ? 'From ' + chans.join(', ') : '');
    body.appendChild(sec);
    if (a.items && a.items.length) {
      var list = el('ol', 'bf-stories');
      a.items.forEach(function (one) {
        var li = el('li', 'bf-story');
        li.appendChild(el('p', 'bf-item', one.headline));
        if (one.summary) li.appendChild(el('p', 'bf-sum', one.summary));
        var from = el('p', 'bf-from-video');
        from.appendChild(el('span', 'bf-chan', one.channel));
        from.appendChild(el('span', 'bf-dot', '·'));
        from.appendChild(out(one.link, 'bf-watch', '▶ ' + one.title, 'Watch on YouTube'));
        li.appendChild(from);
        list.appendChild(li);
      });
      sec.appendChild(list);
    }
    // Videos with nothing condensed out of them are still there to watch.
    var used = {};
    (a.items || []).forEach(function (one) { used[one.link] = true; });
    var rest = (a.videos || []).filter(function (one) {
      return !used[one.link] && (!a.ok || !one.transcript);
    });
    if (rest.length) {
      if (a.ok) sec.appendChild(el('h5', 'bf-h5', 'Also new'));
      var vids = el('ul', 'bf-links bf-vids');
      rest.forEach(function (one) { vids.appendChild(videoLine(one)); });
      sec.appendChild(vids);
    }
    (a.notes || []).forEach(function (t) { sec.appendChild(el('p', 'bf-note', t)); });
  }

  // Clockwork (fr_3c7faab7e0ce; Reminders until 8 October 2026), drawn the way Birthdays are: yesterday,
  // today and tomorrow, each a group of its own, today the one made most of
  // ("Like birthdays- yesterday, today highlighted, and tomorrow"). Each is
  // its time and words, what kind it is and how it repeats; today's that are
  // already past are quieter, as past events are.
  var RM_EMPTY = { yesterday: 'Nothing in Clockwork yesterday.', today: 'Nothing in Clockwork today.',
                   tomorrow: 'Nothing in Clockwork tomorrow.' };

  function drawReminders(body, r, now) {
    var sec = section('reminders', 'Clockwork', r);
    body.appendChild(sec);
    if (!r.ok) return;
    var days = r.days || [];
    if (!days.some(function (day) { return day.items.length; })) {
      sec.appendChild(el('p', 'bf-empty', 'Nothing in Clockwork yesterday, today or tomorrow. ' +
        'Ask Rouh to remind you of something, or to do a piece of work at a time, and it is here on its day.'));
      return;
    }
    days.forEach(function (day) {
      var group = dayGroup(sec, day);
      if (!day.items.length) { group.appendChild(el('p', 'bf-three-none', RM_EMPTY[day.key] || '')); return; }
      var list = el('ol', 'bf-rm-list');
      day.items.forEach(function (one) {
        var li = el('li', 'bf-rm-row' + (day.key === 'today' && one.at <= now ? ' past' : ''));
        li.appendChild(el('span', 'bf-rm-time', one.time));
        var main = el('div', 'bf-rm-main');
        main.appendChild(el('span', 'bf-rm-what', one.what));
        main.appendChild(dotted(el('span', 'bf-rm-sub'), [
          one.kind === 'do' ? 'Scheduled work' : one.kind === 'server' ? 'Rouh\'s own job' : 'A reminder', one.repeats,
          one.owner ? 'For ' + one.owner : '']));
        li.appendChild(main);
        list.appendChild(li);
      });
      group.appendChild(list);
    });
  }

  // The Report (Petar, 5 October 2026): what ran while you slept. First one
  // plain paragraph about last night's Synapse attempt, with its decision and
  // options when there is one, and the way to it in the Synapse lab; then
  // everything else scheduled that ran since the last brief, each with what
  // it found or did, which is left out when nothing else ran.
  var RP_OUTCOME = { kept: 'good', kept_experience: 'good', discarded: 'quiet', failed: 'bad', none: 'bad', needs_decision: 'warn',
                     baseline: 'info', running: 'info' };

  var reportCards = {}, reportDecisions = null;
  function reportHost() {
    if (!reportDecisions) {
      reportDecisions = window.RouhDecision.fetchHost({ go: function (href) { if (host().go) host().go(href); } });
    }
    return reportDecisions;
  }

  // What is about Rouh and repeats, the nightly runs, is not in it (Petar, 18 October 2026:
  // "I can see those in notifications"), so a morning with nothing else has no Report at all.
  function drawReport(body, r) {
    var sec = section('report', 'Report', r);
    if (!r.ok) { body.appendChild(sec); return; }
    var s = r.synapse, ran = r.ran || [];
    if (s) {
      var card = el('div', 'bf-rp-night');
      var head = el('p', 'bf-rp-head');
      head.appendChild(el('span', 'bf-rp-name', 'Synapse, last night'));
      head.appendChild(el('span', 'bf-rp-outcome ' + (RP_OUTCOME[s.outcome] || 'info'),
        s.outcome_words + (s.number ? ' · attempt ' + s.number : '')));
      card.appendChild(head);
      card.appendChild(el('p', 'bf-rp-text', s.paragraph));
      var d = s.decision;
      // The paragraph says the decision and its options itself, in its own words; one that does not gets them here.
      if (d && d.question && !/decision/i.test(s.paragraph || '')) {
        var ask = el('div', 'bf-rp-decide');
        ask.appendChild(el('p', 'bf-rp-q', 'Your decision: ' + d.question));
        var opts = el('ul', 'bf-rp-opts');
        (d.options || []).forEach(function (o) {
          var li = el('li');
          li.appendChild(el('strong', null, o.label));
          if (o.detail) li.appendChild(document.createTextNode(': ' + o.detail));
          opts.appendChild(li);
        });
        ask.appendChild(opts);
        card.appendChild(ask);
      }
      if (s.address && host().go) {
        var see = goLink(el('a', 'bf-settings bf-rp-see', s.number ? 'Open attempt ' + s.number + ' in the Synapse lab'
                                                                   : 'Open the Synapse lab\'s Improvements'), s.address);
        see.addEventListener('click', function () { host().go(s.address); });
        card.appendChild(see);
      }
      sec.appendChild(card);
    }
    if (ran.length) {
      sec.appendChild(el('p', 'bf-rp-sub', (s ? 'Everything else' : 'Everything') + ' scheduled that ran since the last brief'));
      var list = el('ol', 'bf-rm-list bf-rp-ran');
      ran.forEach(function (one) {
        var li = el('li', 'bf-rm-row');
        li.appendChild(el('span', 'bf-rm-time', one.time));
        var main = el('div', 'bf-rm-main');
        main.appendChild(el('span', 'bf-rm-what', one.what));
        main.appendChild(el('span', 'bf-rm-sub', (one.day === 'Yesterday' ? 'Yesterday: ' : '') +
          (one.said ? one.said.charAt(0).toUpperCase() + one.said.slice(1) : 'Done')));
        // The night's feature, while its question waits: the one decision card, with its
        // number and Accept or Reject and undo (`decision.js`).
        if (one.decision && window.RouhDecision) {
          var dq = el('div', 'bf-rp-dq');
          dq.appendChild(window.RouhDecision.kept(reportCards, one.decision, reportHost(), { place: 'context' }));
          main.appendChild(dq);
        }
        if (one.refactor) main.appendChild(refactorPart(one.refactor));
        li.appendChild(main);
        list.appendChild(li);
      });
      sec.appendChild(list);
    }
    // What somebody he gave authority decided for him, with their own words, and what was
    // held for him (`rouh/delegation.py`). Undo is on their page under Trusted contacts.
    var given = r.delegated || [];
    if (given.length) {
      sec.appendChild(el('p', 'bf-rp-sub', 'Decided for you by the people you gave authority'));
      var dl = el('ol', 'bf-rm-list bf-rp-delegated');
      var OUT = { done: '', for_owner: 'Held for you: ', for_petar: 'Held for you: ', refused: 'Not done: ', undone: 'Undone: ', answered: 'You answered: ' };
      given.forEach(function (one) {
        var li = el('li', 'bf-rm-row');
        li.appendChild(el('span', 'bf-rm-time', one.time));
        var main = el('div', 'bf-rm-main');
        main.appendChild(el('span', 'bf-rm-what', (one.day === 'Yesterday' ? 'Yesterday, ' : '') + one.name));
        main.appendChild(el('span', 'bf-rm-sub', (OUT[one.outcome] || '') + one.said +
          (one.words ? ' \u201c' + one.words + '\u201d' : '')));
        li.appendChild(main);
        dl.appendChild(li);
      });
      sec.appendChild(dl);
    }
    if (s || ran.length || given.length) body.appendChild(sec);
  }

  // Last night's refactoring (`rouh/nightly_refactor.py`): each thing it refactored, and Undo,
  // which asks once and then starts a run that reverts exactly that night's commits.
  function refactorPart(r) {
    var box = el('div', 'bf-rf');
    if ((r.items || []).length) {
      var items = el('ul', 'bf-rf-items');
      r.items.forEach(function (i) {
        var li = el('li', null, i.title);
        if (i.result) li.appendChild(el('span', 'bf-rf-result', ' \u00b7 ' + i.result));
        items.appendChild(li);
      });
      box.appendChild(items);
    }
    var said = el('p', 'bf-gene-said');
    said.setAttribute('aria-live', 'polite');
    if (r.undo_run) said.textContent = 'Being undone by run ' + r.undo_run + '.';
    if (r.can_undo) {
      var n = (r.commits || []).length;
      var row = el('div', 'bf-gene-picks');
      var undo = el('button', 'bf-gene-pick', 'Undo night ' + r.number + '\u2019s refactors');
      undo.type = 'button';
      undo.addEventListener('click', function () {
        row.textContent = '';
        said.textContent = 'Revert its ' + n + (n === 1 ? ' commit' : ' commits') + ' and deploy?';
        var yes = el('button', 'bf-gene-pick', 'Yes, undo them');
        var no = el('button', 'bf-gene-pick', 'Keep them');
        yes.type = no.type = 'button';
        no.addEventListener('click', function () { row.textContent = ''; row.appendChild(undo); said.textContent = ''; });
        yes.addEventListener('click', function () {
          yes.disabled = no.disabled = true;
          fetch('/api/brief/refactoring/' + r.number + '/undo', {
            method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}'
          }).then(function (x) { return x.json(); }).then(function (j) {
            if (j && j.ok) { row.textContent = ''; said.textContent = j.said; return; }
            said.textContent = (j && j.error) || 'The undo could not be started. Try again.';
            yes.disabled = no.disabled = false;
          }).catch(function () {
            said.textContent = 'Rouh could not be reached. Try again.';
            yes.disabled = no.disabled = false;
          });
        });
        row.appendChild(yes);
        row.appendChild(no);
      });
      row.appendChild(undo);
      box.appendChild(said);
      box.appendChild(row);
    } else box.appendChild(said);
    return box;
  }

  // One of the three days Birthdays and Reminders each have, under its name
  // and date: today on a card of its own with the accent edge, yesterday and
  // tomorrow indented and quieter either side of it.
  function dayGroup(sec, day) {
    var group = el('div', 'bf-three-day bf-three-' + day.key);
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', day.words);
    var when = el('p', 'bf-three-when');
    when.appendChild(el('span', 'bf-three-word', day.words));
    when.appendChild(el('span', 'bf-three-date', day.date_words));
    group.appendChild(when);
    sec.appendChild(group);
    return group;
  }

  // Today in history, for the topics picked with the gear at the right of its
  // heading (fr_a1b47c17f8cf): each thing its year, Wikipedia's words linked
  // to its article and the topic it belongs to, most significant first. With
  // no topic picked there are no events, only a line asking for them. The
  // gear opens the topics in the same box; Save keeps them and has the
  // section picked again for them, here and in every brief after.
  function drawHistory(body, h) {
    var T = B.topics;
    var editing = !!(T && T.open);
    var sec = section('history', 'Today in history', editing ? null : h,
                      h.words || '', editing);
    var head = sec.querySelector('.bf-h');
    if (editing && h.source) head.appendChild(el('span', 'bf-src', h.source));
    if (!keptOnly()) head.appendChild(topicsGear(editing));
    body.appendChild(sec);
    if (editing) { topicsDraw(sec); return; }
    if (!h.ok) return;
    if (h.choose) {
      sec.appendChild(el('p', 'bf-empty', 'Pick the topics you care about, and this shows ' +
        'what happened on this day in them.'));
      if (!keptOnly()) {
        var go = el('button', 'bf-btn primary bf-topics-go', 'Choose topics');
        go.type = 'button';
        go.addEventListener('click', topicsOpen);
        var row = el('div', 'bf-pick-row');
        row.appendChild(go);
        sec.appendChild(row);
      }
      return;
    }
    if (!(h.events || []).length) {
      sec.appendChild(el('p', 'bf-empty', 'Nothing that happened on this date belongs to your topics.'));
    } else {
      var list = el('ol', 'bf-past');
      h.events.forEach(function (one) {
        var li = el('li', 'bf-past-row');
        li.appendChild(el('span', 'bf-year', one.year == null ? 'Today'
          : one.year < 0 ? -one.year + ' BC' : one.year));
        var what = el('span', 'bf-past-what');
        what.appendChild(one.link ? out(one.link, 'bf-past-text', one.text, 'Read on Wikipedia')
                                  : el('span', 'bf-past-text', one.text));
        if (one.topic) what.appendChild(el('span', 'bf-past-topic', one.topic));
        li.appendChild(what);
        list.appendChild(li);
      });
      sec.appendChild(list);
    }
    if (h.picked_by) sec.appendChild(el('p', 'bf-link-sub bf-past-by', h.picked_by + '.'));
  }

  // The gear at the right of Today in history's heading, menu.js's own icon.
  function topicsGear(on) {
    var b = el('button', 'bf-gear');
    b.type = 'button';
    b.title = on ? 'Close the topics' : 'Choose the topics';
    b.setAttribute('aria-label', b.title);
    b.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (window.RouhMenu) window.RouhMenu.icon(b, 'settings');
    else b.textContent = 'Topics';
    b.addEventListener('click', function () { if (on) topicsClose(); else topicsOpen(); });
    return b;
  }

  function historyRedraw() {
    var body = $('briefBody');
    var old = body && body.querySelector('.bf-history');
    if (!old || !B.data || !B.data.history) return;
    var holder = document.createDocumentFragment();
    drawHistory(holder, B.data.history);
    old.replaceWith(holder);
  }

  function topicsOpen() {
    B.topics = { open: true, busy: true, saving: false, error: '', choices: [], examples: [],
                 most: 6, picked: [], custom: [], typed: '' };
    historyRedraw();
    var T = B.topics;
    fetch('/api/brief/history/topics', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (B.topics !== T) return;
          T.busy = false;
          if (r.ok && j && j.ok) {
            T.choices = j.choices || [];
            T.examples = j.examples || [];
            T.most = j.most_custom || T.most;
            T.picked = (j.topics || []).slice();
            T.custom = (j.custom || []).slice();
          } else T.error = (j && j.error) || 'The topics could not be read (the server said ' + r.status + ').';
          historyRedraw();
          var first = $('briefBody') && $('briefBody').querySelector('.bf-topic');
          if (first) first.focus({ preventScroll: true });
        });
      })
      .catch(function () {
        if (B.topics !== T) return;
        T.busy = false;
        T.error = 'Rouh could not be reached. Check the connection and try again.';
        historyRedraw();
      });
  }

  function topicsClose() {
    B.topics = null;
    historyRedraw();
    var gear = $('briefBody') && $('briefBody').querySelector('.bf-history .bf-gear');
    if (gear) gear.focus({ preventScroll: true });
  }

  // A topic of one's own, as typed, kept once whatever its capitals.
  function topicsAdd(words) {
    var T = B.topics;
    words = String(words || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    if (!T || !words) return false;
    var have = T.custom.some(function (one) { return one.toLowerCase() === words.toLowerCase(); });
    if (!have && T.custom.length >= T.most) {
      T.error = 'You can keep ' + T.most + ' topics of your own at most.';
      return false;
    }
    if (!have) T.custom.push(words);
    T.error = '';
    return true;
  }

  function topicsSave() {
    var T = B.topics;
    if (!T || T.busy || T.saving) return;
    // What is typed and not added yet is meant too.
    if (T.typed.trim() && !topicsAdd(T.typed)) { historyRedraw(); return; }
    T.typed = '';
    T.saving = true;
    T.error = '';
    historyRedraw();
    fetch('/api/brief/history/topics', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone() },
      body: JSON.stringify({ topics: T.picked, custom: T.custom, day: (B.data && B.data.day) || '' })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (B.topics !== T) return;
        T.saving = false;
        if (r.ok && j && j.ok) {
          if (j.history && B.data) B.data.history = j.history;
          topicsClose();
          return;
        }
        T.error = (j && j.error) || 'The topics could not be kept (the server said ' + r.status + ').';
        historyRedraw();
      });
    }).catch(function () {
      if (B.topics !== T) return;
      T.saving = false;
      T.error = 'Rouh could not be reached. Check the connection and try again.';
      historyRedraw();
    });
  }

  // The topics, in Today in history's own box: one toggle a topic, the
  // person's own below them with a box to add one and examples of what one
  // can be, then Save and Cancel.
  function topicsDraw(sec) {
    var T = B.topics;
    if (T.busy) { sec.appendChild(el('p', 'bf-empty', 'Reading your topics…')); return; }
    var wait = T.saving;
    var grid = el('div', 'bf-topics');
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', 'Topics');
    T.choices.forEach(function (c) {
      var on = T.picked.indexOf(c.id) >= 0;
      var b = el('button', 'bf-topic', c.name);
      b.type = 'button';
      b.disabled = wait;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.addEventListener('click', function () {
        var at = T.picked.indexOf(c.id);
        if (at >= 0) T.picked.splice(at, 1); else T.picked.push(c.id);
        b.setAttribute('aria-pressed', at < 0 ? 'true' : 'false');
      });
      grid.appendChild(b);
    });
    sec.appendChild(grid);

    sec.appendChild(el('h5', 'bf-h5', 'Your own topics'));
    if (T.custom.length) {
      var mine = el('div', 'bf-topics bf-topics-mine');
      T.custom.forEach(function (words, i) {
        var chip = el('span', 'bf-topic bf-topic-mine');
        chip.setAttribute('aria-pressed', 'true');
        chip.appendChild(el('span', 'bf-topic-words', words));
        var x = el('button', 'bf-topic-x', '×');
        x.type = 'button';
        x.disabled = wait;
        x.title = 'Remove ' + words;
        x.setAttribute('aria-label', x.title);
        x.addEventListener('click', function () {
          T.custom.splice(i, 1);
          T.error = '';
          historyRedraw();
          var box = $('bfTopicNew');
          if (box) box.focus({ preventScroll: true });
        });
        chip.appendChild(x);
        mine.appendChild(chip);
      });
      sec.appendChild(mine);
    }
    var form = el('form', 'bf-topic-add');
    var box = el('input', 'bf-pick-input');
    box.id = 'bfTopicNew';
    box.type = 'text';
    box.maxLength = 60;
    box.placeholder = 'A person, company or place';
    box.setAttribute('aria-label', 'A topic of your own');
    box.autocomplete = 'off';
    box.value = T.typed;
    box.disabled = wait;
    box.addEventListener('input', function () { T.typed = box.value; });
    var add = el('button', 'bf-btn', 'Add');
    add.type = 'submit';
    add.disabled = wait;
    form.appendChild(box);
    form.appendChild(add);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (topicsAdd(T.typed)) T.typed = '';
      historyRedraw();
      var again = $('bfTopicNew');
      if (again) again.focus({ preventScroll: true });
    });
    sec.appendChild(form);
    var eg = el('p', 'bf-topic-eg');
    eg.appendChild(el('span', 'bf-topic-eg-word', 'For example'));
    T.examples.forEach(function (words) {
      var b = el('button', 'bf-topic-eg-one', words);
      b.type = 'button';
      b.disabled = wait;
      b.title = 'Add ' + words;
      b.addEventListener('click', function () {
        topicsAdd(words);
        historyRedraw();
      });
      eg.appendChild(b);
    });
    sec.appendChild(eg);

    if (T.error) sec.appendChild(el('p', 'bf-say bad bf-topic-said', T.error));
    var row = el('div', 'bf-pick-row');
    var save = el('button', 'bf-btn primary', wait ? 'Picking events for your topics…' : 'Save');
    save.type = 'button';
    save.disabled = wait;
    save.addEventListener('click', topicsSave);
    var cancel = el('button', 'bf-btn', 'Cancel');
    cancel.type = 'button';
    cancel.disabled = wait;
    cancel.addEventListener('click', topicsClose);
    row.appendChild(save);
    row.appendChild(cancel);
    sec.appendChild(row);
  }

  // The daily doodle: the last section but the dad joke, a sketch of today drawn from
  // its calendar, today's reminders and today's birthdays. With none of them
  // to draw from, or a drawing that fails, there is no section at all.
  function drawDoodle(body, d) {
    var art = window.RouhDoodle && window.RouhDoodle.draw(d);
    if (!art) return;
    var today = d.calendar.ok ? (d.calendar.today || []).length : 0;
    var due = ((d.reminders && d.reminders.ok && d.reminders.days) || []).some(function (day) {
      return day.key === 'today' && day.items.length;
    });
    var sec = section('doodle', 'Daily doodle', null,
      today && due ? 'your day, from your calendar and Clockwork' :
      due ? 'your day, from Clockwork' :
      today ? 'your day, from your calendar' : 'a free day');
    var frame = el('div', 'bf-doodle-art');
    frame.appendChild(art);
    sec.appendChild(frame);
    body.appendChild(sec);
  }

  // The dad joke (fr_6fb4aad2f62c, 20 October 2026: "do not invent jokes, get
  // them from somewhere. preferably rated high"), right after the doodle: the
  // post's title and its own words under it, exactly as on r/dadjokes, and the
  // source in the corner opening the post. With none there is no section.
  function rankWords(j) {
    var n = j.rank || 1;
    var th = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
    return (n === 1 ? 'the most voted ' : 'the ' + n + th + ' most voted ') + (j.span || '');
  }

  function drawJoke(body, j) {
    if (!j || !j.ok || !j.setup) return;
    var sec = section('joke', 'Dad joke', j, rankWords(j), true);
    if (j.link) sec.firstChild.appendChild(out(j.link, 'bf-src bf-joke-src', j.source,
      'Open the post on Reddit'));
    sec.appendChild(el('p', 'bf-joke-setup', j.setup));
    if (j.punchline) sec.appendChild(el('p', 'bf-joke-punch', j.punchline));
    body.appendChild(sec);
  }

  /* ------------------------------------------------------------ birthdays */

  // Birthdays (fr_d3ea4a374d50), right before the doodle: yesterday, today
  // and tomorrow, each a group of its own under its own name, and each saying
  // so when nobody has one. Today is the one made most of, bigger and on a
  // card of its own; yesterday and tomorrow sit indented and quieter either
  // side of it, as Petar asked ("today needs to be highlighted not tomorrow").
  // A person he has as a contact is their full name and company. A birthday
  // on his calendar with no contact behind it is the event as it says itself,
  // with Link contact beside it, which opens a picker of his contacts
  // (`linkOpen`); once linked it is the contact, in this brief and every one
  // after (`rouh/birthdays.py`).

  var BD_EMPTY = { yesterday: 'Nobody had a birthday yesterday.',
                   today: 'Nobody has a birthday today.',
                   tomorrow: 'Nobody has a birthday tomorrow.' };

  function ageWords(key, age) {
    if (!age) return '';
    return (key === 'yesterday' ? 'turned ' : key === 'today' ? 'turns ' : 'will be ') + age;
  }

  function birthdayRow(day, one) {
    var li = el('li', 'bf-bd-row' + (one.contact_uid ? '' : ' unlinked'));
    var main = el('div', 'bf-bd-main');
    if (one.contact_uid) {
      main.appendChild(el('span', 'bf-bd-name', one.name));
      var sub = dotted(el('span', 'bf-bd-sub'), [
        one.company ? el('span', 'bf-bd-company', one.company) : null,
        ageWords(day.key, one.age)]);
      if (sub.childNodes.length) main.appendChild(sub);
    } else {
      main.appendChild(el('span', 'bf-bd-event', one.title));
      if (one.calendar) main.appendChild(el('span', 'bf-bd-sub', 'On ' + one.calendar +
        ', not linked to a contact'));
    }
    li.appendChild(main);
    if (one.event_key && (!one.contact_uid || one.linked === 'you') && !keptOnly()) {
      var b = el('button', one.contact_uid ? 'bf-bd-change' : 'bf-btn bf-bd-link',
                 one.contact_uid ? 'Change' : 'Link contact');
      b.type = 'button';
      b.setAttribute('aria-haspopup', 'dialog');
      b.dataset.bd = bdKey(one);
      b.title = one.contact_uid ? 'Linked from “' + one.title + '” on your calendar. ' +
        'Link it to someone else, or unlink it' : 'Pick which of your contacts this is';
      b.addEventListener('click', function () { linkOpen(day, one, b); });
      li.appendChild(b);
    }
    return li;
  }

  function drawBirthdays(body, part) {
    var sec = section('birthdays', 'Birthdays', part);
    body.appendChild(sec);
    if (!part.ok) return;
    (part.days || []).forEach(function (day) {
      var group = dayGroup(sec, day);
      if (!day.people.length) group.appendChild(el('p', 'bf-three-none', BD_EMPTY[day.key] || ''));
      else {
        var list = el('ul', 'bf-bd-list');
        day.people.forEach(function (one) { list.appendChild(birthdayRow(day, one)); });
        group.appendChild(list);
      }
    });
    (part.notes || []).forEach(function (t) { sec.appendChild(el('p', 'bf-note', t)); });
  }

  /* ---- Link contact: pick which contact a calendar birthday is */

  var LK = { day: null, one: null, q: '', found: null, connected: true, chosen: null,
             busy: false, error: '', seq: 0, timer: 0, back: null, backKey: '' };

  function bdKey(one) { return one.calendar_id + ':' + one.event_key; }

  function linkOpen(day, one, from) {
    LK.day = day;
    LK.one = one;
    LK.q = one.contact_uid ? one.name : (one.guess || one.title || '');
    // What the box starts with: when not one contact matches it, everyone is
    // listed instead, so there is always somebody to pick from.
    LK.prefill = LK.q;
    LK.widened = false;
    LK.found = null;
    LK.chosen = null;
    LK.busy = false;
    LK.error = '';
    LK.back = from || null;
    LK.backKey = bdKey(one);
    var dlg = linkDialog();
    linkDraw();
    if (!dlg.open) dlg.showModal();
    var input = $('bfLinkQ');
    if (input) { input.focus(); input.select(); }
    linkSearch();
  }

  function linkClose() {
    var dlg = $('bfLinkDialog');
    LK.one = null;
    LK.seq++;
    clearTimeout(LK.timer);
    if (dlg && dlg.open) dlg.close();
  }

  function linkDialog() {
    var dlg = $('bfLinkDialog');
    if (dlg) return dlg;
    dlg = el('dialog', 'bf-dlg bf-link-dlg');
    dlg.id = 'bfLinkDialog';
    dlg.setAttribute('aria-labelledby', 'bfLinkTitle');
    dlg.addEventListener('click', function (e) {
      if (e.target !== dlg) return;
      var r = dlg.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
        linkClose();
      }
    });
    dlg.addEventListener('close', function () {
      LK.one = null;
      var back = LK.back && document.contains(LK.back) ? LK.back
        : document.querySelector('.brief-view [data-bd="' + LK.backKey + '"]');
      if (back) back.focus({ preventScroll: true });
    });
    ($('briefView') || document.body).appendChild(dlg);
    return dlg;
  }

  function linkSearch(everyone) {
    clearTimeout(LK.timer);
    var seq = ++LK.seq, one = LK.one;
    if (!everyone) LK.widened = false;
    LK.timer = setTimeout(function () {
      fetch('/api/brief/contacts?q=' + encodeURIComponent(everyone ? '' : LK.q.trim()),
            { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) {
          if (r.status === 401) { location.href = '/login'; return null; }
          return r.json().catch(function () { return {}; }).then(function (j) {
            if (seq !== LK.seq || LK.one !== one) return;
            if (r.ok && j && !everyone && !(j.contacts || []).length && LK.q.trim() &&
                LK.q === LK.prefill && j.connected !== false) {
              LK.widened = true;
              linkSearch(true);
              return;
            }
            if (r.ok && j) { LK.found = j.contacts || []; LK.connected = j.connected !== false; }
            else LK.error = (j && j.error) || 'Your contacts could not be read (the server said ' +
              r.status + ').';
            linkList();
          });
        })
        .catch(function () {
          if (seq !== LK.seq || LK.one !== one) return;
          LK.error = 'Rouh could not be reached. Try again.';
          linkList();
        });
    }, LK.found ? 180 : 0);
  }

  function linkDraw() {
    var dlg = $('bfLinkDialog'), one = LK.one;
    if (!dlg || !one) return;
    dlg.textContent = '';
    var box = el('div', 'bf-dlg-box');
    var head = el('div', 'bf-dlg-head');
    var h = el('h3', 'bf-dlg-title', 'Whose birthday is it?');
    h.id = 'bfLinkTitle';
    head.appendChild(h);
    var x = el('button', 'layer-x bf-dlg-x', '×');
    x.type = 'button';
    x.title = 'Close (Esc)';
    x.setAttribute('aria-label', 'Close without linking');
    x.addEventListener('click', linkClose);
    head.appendChild(x);
    box.appendChild(head);

    var what = el('p', 'bf-link-what');
    what.appendChild(el('span', 'bf-bd-event', one.title));
    what.appendChild(el('span', 'bf-bd-sub', [one.calendar ? 'on ' + one.calendar : '',
      LK.day ? LK.day.words.toLowerCase() + ', ' + LK.day.date_words : ''].filter(Boolean)
      .join(', ')));
    box.appendChild(what);
    box.appendChild(el('p', 'bf-note bf-link-how', 'Pick the contact it is. From then on it ' +
      'shows as their full name and company, this year and every year after.'));

    var label = el('label', 'bf-pick-label', 'Find a contact');
    var input = el('input', 'bf-pick-input');
    input.type = 'search';
    input.id = 'bfLinkQ';
    input.maxLength = 200;
    input.autocomplete = 'off';
    input.placeholder = 'A name, a company or an email';
    input.value = LK.q;
    label.htmlFor = input.id;
    input.addEventListener('input', function () {
      LK.q = input.value;
      LK.chosen = null;
      LK.error = '';
      linkSearch();
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        var first = document.querySelector('#bfLinkList .bf-pick-item');
        if (first) { e.preventDefault(); first.focus(); }
      }
      if (e.key === 'Enter') { e.preventDefault(); if (LK.chosen) linkSave(); }
    });
    box.appendChild(label);
    box.appendChild(input);

    var list = el('ul', 'bf-pick-list bf-link-list');
    list.id = 'bfLinkList';
    list.setAttribute('aria-label', 'Your contacts');
    box.appendChild(list);
    var said = el('p', 'bf-note bf-link-said');
    said.id = 'bfLinkSaid';
    said.setAttribute('role', 'status');
    box.appendChild(said);

    var acts = el('div', 'bf-pick-row bf-dlg-acts');
    if (one.linked === 'you') {
      var un = el('button', 'bf-btn bf-link-un', 'Unlink');
      un.type = 'button';
      un.id = 'bfLinkUn';
      un.addEventListener('click', function () { linkSave(true); });
      acts.appendChild(un);
    }
    var cancel = el('button', 'bf-btn', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', linkClose);
    acts.appendChild(cancel);
    var ok = el('button', 'bf-btn primary', 'Link');
    ok.type = 'button';
    ok.id = 'bfLinkOk';
    ok.addEventListener('click', function () { linkSave(false); });
    acts.appendChild(ok);
    box.appendChild(acts);
    dlg.appendChild(box);
    linkList();
  }

  // The list and what is said under it, drawn again without the box to type
  // in, so typing is never interrupted.
  function linkList() {
    var list = $('bfLinkList');
    if (!list) return;
    list.textContent = '';
    if (!LK.connected) {
      list.appendChild(el('li', 'bf-note', 'Apple Contacts is not connected, so there is ' +
        'nobody to pick yet. Connect it in Settings, under Apple Contacts.'));
    } else if (LK.found === null) {
      list.appendChild(el('li', 'bf-note', 'Reading your contacts…'));
    } else if (LK.widened && LK.found.length) {
      list.appendChild(el('li', 'bf-note bf-link-wide', 'None of your contacts match “' +
        LK.q.trim() + '”, so here is everyone. Type to narrow it down.'));
    } else if (!LK.found.length) {
      list.appendChild(el('li', 'bf-note', LK.q.trim()
        ? 'None of your contacts match “' + LK.q.trim() + '”. Try part of the name.'
        : 'You have no contacts yet.'));
    }
    (LK.found || []).forEach(function (c) {
      var li = el('li');
      var b = el('button', 'bf-pick-item bf-link-item');
      b.type = 'button';
      var who = el('span', 'bf-pick-name');
      who.appendChild(el('span', 'bf-link-name', c.name));
      if (c.company) who.appendChild(el('span', 'bf-link-co', c.company));
      b.appendChild(who);
      if (c.birthday) b.appendChild(el('span', 'bf-pick-hint', 'born ' + c.birthday));
      b.chosen = c;
      b.addEventListener('click', function () { LK.chosen = c; LK.error = ''; linkState(); });
      b.addEventListener('keydown', function (e) {
        var items = Array.prototype.slice.call(list.querySelectorAll('.bf-pick-item'));
        var at = items.indexOf(b);
        // Enter on the one already picked links it, as Link does.
        if (e.key === 'Enter' && LK.chosen === c) { e.preventDefault(); linkSave(false); return; }
        if (e.key === 'ArrowDown' && items[at + 1]) { e.preventDefault(); items[at + 1].focus(); }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (items[at - 1]) items[at - 1].focus(); else { var q = $('bfLinkQ'); if (q) q.focus(); }
        }
      });
      li.appendChild(b);
      list.appendChild(li);
    });
    linkState();
  }

  // Which contact is picked, and what is said about it, without drawing the
  // list again, so the keyboard stays where it is.
  function linkState() {
    var list = $('bfLinkList'), said = $('bfLinkSaid'), ok = $('bfLinkOk'), un = $('bfLinkUn');
    if (!list) return;
    Array.prototype.forEach.call(list.querySelectorAll('.bf-pick-item'), function (b) {
      var on = b.chosen === LK.chosen;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.disabled = LK.busy;
    });
    if (said) {
      said.className = 'bf-note bf-link-said' + (LK.error ? ' bad' : '');
      said.textContent = LK.error || (LK.busy ? 'Linking…' : LK.chosen
        ? 'Link it to ' + LK.chosen.name + (LK.chosen.company ? ', ' + LK.chosen.company : '') + '.'
        : '');
    }
    if (ok) ok.disabled = LK.busy || !LK.chosen;
    if (un) un.disabled = LK.busy;
  }

  function linkSave(unlink) {
    var one = LK.one;
    if (!one || LK.busy || (!unlink && !LK.chosen)) return;
    LK.busy = true;
    LK.error = '';
    linkState();
    var sent = { calendar: one.calendar_id, event: one.event_key, title: one.title };
    if (unlink) sent.unlink = true; else sent.contact = LK.chosen.id;
    fetch('/api/brief/birthday/link', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone() },
      body: JSON.stringify(sent)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (LK.one !== one) return;
        LK.busy = false;
        if (r.ok && j && j.birthdays) {
          if (B.data) B.data.birthdays = j.birthdays;
          LK.back = null;
          linkClose();
          draw();
          return;
        }
        LK.error = (unlink ? 'Not unlinked: ' : 'Not linked: ') +
          ((j && j.error) || 'the server said ' + r.status + '.');
        linkState();
      });
    }).catch(function () {
      if (LK.one !== one) return;
      LK.busy = false;
      LK.error = (unlink ? 'Not unlinked' : 'Not linked') + ': Rouh could not be reached. Try again.';
      linkState();
    });
  }

  /* ---------------------------------------------------- mail, per inbox */

  // One section for each mailbox the person gave Rouh (`rouh/ghosts.py`),
  // headed by its address, so it is plain at a glance which inbox every email
  // is in (fr_dfce915c2c6d, 30 September 2026: "I don't know which mail inbox
  // that is and now we have multiple"). Rouh's own Google connection first,
  // then each read-only mailbox, marked Read-only. Under each: the unread mail
  // in its inbox since yesterday, then Waiting on others, the emails sent from
  // it that asked for something and were never answered.
  //
  // Any email opens in place, whole - who sent it, to whom, when, and all of
  // its body - with what can be done about it under it. It expands under its
  // own line and every other email stays where it was; pressing its subject
  // again, Close or Escape folds it back (fr_411f07408618: "emails I should
  // be able to click them and they expand in full").
  // Defer (three days or a week), Dismiss and Handled are kept in Rouh, per
  // mailbox and per email, so they hold across reloads and devices, and none
  // of it writes to any mailbox: nothing is sent, drafted or marked read, so
  // a read-only mailbox has every one of them. The nudge is words to copy.

  var G = B.ghosts;

  function ghostsLoad(fresh) {
    var seq = ++G.seq;
    G.busy = true;
    G.error = '';
    if (B.open) draw();
    fetch('/api/brief/ghosts' + (fresh ? '?fresh=1' : ''),
          { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (seq !== G.seq) return;
          G.busy = false;
          if (r.ok && j && j.mailboxes) {
            G.data = j;
            // An email being read that is no longer on the list is put away.
            if (G.reading && !listed(G.reading.mailbox, G.reading.message_id)) G.reading = null;
          } else G.error = (j && j.error) || 'Your mailboxes could not be read (the server said ' +
            r.status + ').';
          draw();
        });
      })
      .catch(function () {
        if (seq !== G.seq) return;
        G.busy = false;
        G.error = 'Rouh could not be reached to read your mailboxes. Check the connection.';
        draw();
      });
  }

  function ghostKey(m, one) { return m.id + ':' + one.thread_id; }

  function mailboxOf(id) {
    return ((G.data && G.data.mailboxes) || []).filter(function (m) { return m.id === id; })[0];
  }
  // The email on a mailbox's list, shown or hidden, with this message id.
  function listed(id, messageId) {
    var m = mailboxOf(id);
    if (!m) return null;
    return (m.unread || []).concat(m.items || [], m.hidden || []).filter(function (one) {
      return one.message_id === messageId;
    })[0] || null;
  }

  function dayWords(t) {
    var d = new Date(t * 1000);
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  }
  // When an email came: the time today, the day this week, the date before.
  function whenWords(t) {
    var d = new Date(t * 1000), now = new Date();
    if (d.toDateString() === now.toDateString()) return clock(t);
    var yesterday = new Date(now.getTime() - 86400000);
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday ' + clock(t);
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) +
      ' ' + clock(t);
  }
  function fullWhen(t) {
    return new Date(t * 1000).toLocaleString('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit' });
  }

  // What each action is called on a button, and what it is said to have done.
  var DEFERS = [['Defer 3 days', 'days'], ['Defer a week', 'week']];
  function markWords(one) {
    if (one.mark === 'dismissed') return 'Dismissed';
    if (one.mark === 'handled') return 'Handled';
    if (one.mark === 'nudged') return 'Nudge sent';
    return 'Deferred until ' + dayWords(one.until);
  }

  function ghostMark(m, one, action, until) {
    var key = ghostKey(m, one);
    G.said[m.id] = '';
    fetch('/api/brief/ghosts/mark', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mailbox: m.id, thread: one.thread_id, message: one.message_id,
                             action: action, until: until || '' })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) {
          G.said[m.id] = { bad: true, text: (j && j.error) || 'That could not be saved.' };
          draw();
          return;
        }
        var shownList = one.kind === 'unread' ? m.unread : m.items;
        var from = action === 'restore' ? m.hidden : shownList;
        var to = action === 'restore' ? shownList : m.hidden;
        var at = from.indexOf(one);
        if (at >= 0) from.splice(at, 1);
        if (action === 'restore') {
          delete one.mark;
          to.push(one);
          if (one.kind === 'unread') to.sort(function (a, b) { return b.at - a.at; });
          else to.sort(function (a, b) { return a.sent_at - b.sent_at; });
          G.said[m.id] = null;
        } else {
          one.mark = j.state;
          one.until = j.until;
          to.push(one);
          G.open[key] = false;
          // Done with it: back to the list, where it has gone.
          if (G.reading && G.reading.mailbox === m.id &&
              G.reading.message_id === one.message_id) G.reading = null;
          G.said[m.id] = { one: one, text: (j.state === 'dismissed'
            ? 'Dismissed “' + one.subject + '”. It comes back only if you ask again in it.'
            : j.state === 'handled'
              ? 'Marked “' + one.subject + '” handled.'
              : 'Deferred “' + one.subject + '” until ' + dayWords(j.until) + '.') };
        }
        draw();
      });
    }).catch(function () {
      G.said[m.id] = { bad: true, text: 'Rouh could not be reached. Try again.' };
      draw();
    });
  }

  function ghostNudge(li, m, one) {
    var key = ghostKey(m, one);
    var box = el('div', 'bf-nudge');
    var id = 'bfNudge' + m.id + '_' + one.thread_id.replace(/[^\w-]/g, '');
    // From the account Rouh controls it is sent from here; from a read-only
    // one it can only be copied into a reply (fr_e052e3e4d875).
    var sends = !!m.can_send;
    var label = el('label', 'bf-nudge-label', sends ? 'A nudge to send as a reply'
                                                   : 'A nudge to copy into a reply');
    label.htmlFor = id;
    var text = el('textarea', 'bf-nudge-text');
    text.id = id;
    text.rows = 6;
    text.value = G.text[key] != null ? G.text[key] : one.nudge;
    text.addEventListener('input', function () { G.text[key] = text.value; });
    box.appendChild(label);
    box.appendChild(text);
    var row = el('div', 'bf-pick-row');
    var said = el('span', 'bf-note bf-nudge-said');
    said.setAttribute('role', 'status');
    if (sends) {
      var send = el('button', 'bf-btn primary', 'Send');
      send.type = 'button';
      send.addEventListener('click', function () { nudgeSend(m, one, text, send, said); });
      row.appendChild(send);
    } else {
      var copy = el('button', 'bf-btn primary', 'Copy');
      copy.type = 'button';
      copy.addEventListener('click', function () {
        function done() { said.textContent = 'Copied. Paste it into a reply in Gmail.'; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text.value).then(done, function () {
            text.select();
            said.textContent = 'Selected: press Ctrl+C or ⌘C to copy it.';
          });
        } else { text.select(); said.textContent = 'Selected: press Ctrl+C or ⌘C to copy it.'; }
      });
      row.appendChild(copy);
    }
    row.appendChild(said);
    box.appendChild(row);
    box.appendChild(el('p', 'bf-note', sends
      ? 'Send replies in the same conversation, from ' + m.email + ', to ' +
        one.to.map(function (p) { return p.name || p.email; }).join(', ') +
        (one.cc ? ', with ' + plural(one.cc, 'other') + ' on Cc' : '') + '.'
      : 'Rouh cannot send from ' + m.email + ', which is connected read-only: ' +
        'this is here to copy.'));
    li.appendChild(box);
  }

  // The nudge, sent from the connection as a reply; the email is then put
  // away as nudged, and the mailbox's line says who it went to.
  function nudgeSend(m, one, text, button, said) {
    var key = ghostKey(m, one);
    if (!text.value.trim()) {
      said.classList.add('bad');
      said.textContent = 'There is nothing in the nudge to send.';
      return;
    }
    button.disabled = true;
    text.readOnly = true;
    button.textContent = 'Sending…';
    said.classList.remove('bad');
    said.textContent = '';
    function failed(words) {
      button.disabled = false;
      text.readOnly = false;
      button.textContent = 'Send';
      said.classList.add('bad');
      said.textContent = 'Not sent: ' + words;
    }
    fetch('/api/brief/ghosts/send', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mailbox: m.id, thread: one.thread_id, message: one.message_id,
                             text: text.value })
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) {
          failed((j && j.error) || 'the server said ' + r.status + '.');
          return;
        }
        var at = m.items.indexOf(one);
        if (at >= 0) m.items.splice(at, 1);
        one.mark = j.state;
        one.until = j.until;
        m.hidden.push(one);
        G.open[key] = false;
        delete G.text[key];
        if (G.reading && G.reading.mailbox === m.id &&
            G.reading.message_id === one.message_id) G.reading = null;
        G.said[m.id] = { text: 'Sent the nudge on “' + one.subject + '” to ' +
          j.to + (j.cc ? ', copying ' + j.cc : '') + '.' };
        draw();
      });
    }).catch(function () { failed('Rouh could not be reached. Try again.'); });
  }

  // What can be done about one email, the same on its line and when it is open.
  function mailActs(m, one) {
    var key = ghostKey(m, one);
    var acts = el('div', 'bf-ghost-acts');
    if (one.mark) {
      // Already put away: say so, and offer it back.
      acts.appendChild(el('span', 'bf-read-mark', markWords(one)));
      var back = el('button', 'bf-btn', 'Bring back');
      back.type = 'button';
      back.addEventListener('click', function () { ghostMark(m, one, 'restore'); });
      acts.appendChild(back);
      acts.appendChild(gmailOut(one, m));
      return acts;
    }
    if (one.kind === 'ask') {
      var nudge = el('button', 'bf-btn', G.open[key] ? 'Hide the nudge' : 'Draft a nudge');
      nudge.type = 'button';
      nudge.setAttribute('aria-expanded', G.open[key] ? 'true' : 'false');
      nudge.addEventListener('click', function () { G.open[key] = !G.open[key]; draw(); });
      acts.appendChild(nudge);
    }
    DEFERS.forEach(function (a) {
      var b = el('button', 'bf-btn', a[0]);
      b.type = 'button';
      b.addEventListener('click', function () { ghostMark(m, one, 'defer', a[1]); });
      acts.appendChild(b);
    });
    var last = one.kind === 'ask' ? ['Dismiss', 'dismiss'] : ['Handled', 'handled'];
    var b = el('button', 'bf-btn', last[0]);
    b.type = 'button';
    b.addEventListener('click', function () { ghostMark(m, one, last[1]); });
    acts.appendChild(b);
    acts.appendChild(gmailOut(one, m));
    return acts;
  }

  function reading(m, one) {
    return !!G.reading && G.reading.mailbox === m.id && G.reading.message_id === one.message_id;
  }

  // The subject, as the button that opens the email here, and folds it again.
  function opener(m, one, cls) {
    var open = reading(m, one);
    var b = el('button', 'bf-open ' + cls, one.subject);
    b.type = 'button';
    b.dataset.mail = m.id + ':' + one.message_id;
    b.title = open ? 'Fold it away' : 'Read it here';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    b.addEventListener('click', function () {
      if (reading(m, one)) readClose(); else readOpen(m, one);
    });
    return b;
  }

  // A press anywhere on an email's line opens it, or folds it when it is
  // open, not only on its subject (fr_1da7cddc045b: "tap anywhere to expand
  // it"). Its buttons and links, the open email itself and text being
  // selected are left to themselves.
  function wholeRow(li, m, one) {
    li.classList.add('bf-row-opens');
    li.addEventListener('click', function (e) {
      if (e.target.closest('a, button, textarea, input, select, label, .bf-read, .bf-nudge') ||
          selecting()) return;
      if (reading(m, one)) readClose(); else readOpen(m, one);
    });
  }

  function unreadRow(m, one) {
    var li = el('li', 'bf-unread');
    wholeRow(li, m, one);
    var head = el('p', 'bf-ghost-head');
    head.appendChild(el('span', 'bf-ghost-who', one.from.name || one.from.email));
    if (one.returned) head.appendChild(el('span', 'bf-ghost-ro', 'Back from deferral'));
    head.appendChild(el('span', 'bf-unread-when', whenWords(one.at)));
    li.appendChild(head);
    li.appendChild(opener(m, one, 'bf-ghost-subject'));
    if (reading(m, one)) drawReading(li, m, one);
    else if (one.snippet) li.appendChild(el('p', 'bf-unread-snip', one.snippet));
    return li;
  }

  function ghostRow(m, one) {
    var key = ghostKey(m, one);
    var li = el('li', 'bf-ghost');
    wholeRow(li, m, one);
    var head = el('p', 'bf-ghost-head');
    var to = one.to[0] || { name: '', email: '' };
    head.appendChild(el('span', 'bf-ghost-who', to.name || to.email));
    if (one.to.length > 1) head.appendChild(el('span', 'bf-ghost-more', ' and ' +
      plural(one.to.length - 1, 'other')));
    head.appendChild(el('span', 'bf-ghost-days', plural(one.days, 'day')));
    li.appendChild(head);
    li.appendChild(opener(m, one, 'bf-ghost-subject'));
    li.appendChild(el('p', 'bf-ghost-ask', '“' + one.ask + '”'));
    li.appendChild(dotted(el('p', 'bf-ev-sub'), [
      'Sent ' + dayWords(one.sent_at) + ' to ' + one.to.map(function (p) {
        return p.name ? p.name + ' <' + p.email + '>' : p.email; }).join(', '),
      one.cc ? plural(one.cc, 'other') + ' on Cc' : '',
      one.auto_reply ? el('span', 'bf-ask', 'Only an automatic reply came back') : null]));
    // Open, its actions and its nudge are under the whole email instead.
    if (reading(m, one)) { drawReading(li, m, one); return li; }
    li.appendChild(mailActs(m, one));
    if (G.open[key]) ghostNudge(li, m, one);
    return li;
  }

  /* ---- one email, open */

  function readOpen(m, one) {
    var r = { mailbox: m.id, message_id: one.message_id, data: null, error: '', seq: 0 };
    G.reading = r;
    G.backTo = m.id + ':' + one.message_id;
    G.said[m.id] = null;
    draw();
    // The keyboard stays on the subject that was pressed, which folds it again.
    readFocus(G.backTo);
    readFetch(r);
  }

  function readFetch(r) {
    var seq = ++r.seq;
    r.error = '';
    fetch('/api/brief/mail/message?mailbox=' + encodeURIComponent(r.mailbox) + '&message=' +
          encodeURIComponent(r.message_id), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (res) {
        if (res.status === 401) { location.href = '/login'; return null; }
        return res.json().catch(function () { return {}; }).then(function (j) {
          if (G.reading !== r || seq !== r.seq) return;
          if (res.ok && j && j.message) r.data = j.message;
          else r.error = (j && j.error) || 'That email could not be read (the server said ' +
            res.status + ').';
          var had = document.activeElement && document.activeElement.dataset &&
            document.activeElement.dataset.mail;
          draw();
          if (had) readFocus(had);
        });
      })
      .catch(function () {
        if (G.reading !== r || seq !== r.seq) return;
        r.error = 'Rouh could not be reached to read that email. Try again.';
        draw();
      });
  }

  function readFocus(key) {
    var at = key && document.querySelector('.brief-view [data-mail="' + key + '"]');
    if (at) at.focus({ preventScroll: true });
  }

  function readClose() {
    if (!G.reading) return;
    G.reading = null;
    draw();
    var back = G.backTo && document.querySelector('.brief-view [data-mail="' + G.backTo + '"]');
    if (back) {
      back.scrollIntoView({ block: 'nearest' });
      back.focus({ preventScroll: true });
    }
  }

  // The body as it came: its text, or, when it has only HTML, that HTML in a
  // frame that runs nothing and can reach nothing on this page.
  function readBody(msg) {
    if (msg.html) {
      var frame = document.createElement('iframe');
      frame.className = 'bf-read-frame';
      frame.setAttribute('sandbox', '');
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.title = 'The email, as it was sent';
      frame.srcdoc = '<!doctype html><html><head><meta charset="utf-8">'
        + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        + 'img-src https: data:; style-src \'unsafe-inline\'; font-src data: https:">'
        + '<base target="_blank"><style>body{margin:12px;font:14px/1.5 system-ui,sans-serif;'
        + 'color:#222;background:#fff;overflow-wrap:anywhere}img{max-width:100%;height:auto}'
        + '</style></head><body>' + msg.html + '</body></html>';
      return frame;
    }
    return el('div', 'bf-read-text', msg.body || '(This email has no text.)');
  }

  function drawReading(li, m, one) {
    var r = G.reading;
    li.classList.add('open');
    var box = el('div', 'bf-read');
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', 'The email, open');
    var msg = r.data;
    if (r.error) {
      box.appendChild(el('p', 'bf-note bad', r.error));
      var again = el('button', 'bf-btn', 'Try again');
      again.type = 'button';
      again.addEventListener('click', function () { readFetch(r); draw(); });
      var row = el('div', 'bf-pick-row');
      row.appendChild(again);
      box.appendChild(row);
    } else if (!msg) {
      box.appendChild(el('p', 'bf-empty', 'Opening the email…'));
    } else {
      var dl = el('dl', 'bf-read-heads');
      [['From', msg.from], ['To', msg.to], ['Cc', msg.cc],
       ['Date', msg.at ? fullWhen(msg.at) : msg.date]].forEach(function (h) {
        if (!h[1]) return;
        dl.appendChild(el('dt', null, h[0]));
        dl.appendChild(el('dd', null, h[1]));
      });
      if (msg.files && msg.files.length) {
        dl.appendChild(el('dt', null, msg.files.length === 1 ? 'File' : 'Files'));
        dl.appendChild(el('dd', null, msg.files.map(function (f) { return f.name; }).join(', ')));
      }
      box.appendChild(dl);
      box.appendChild(readBody(msg));
    }
    var acts = mailActs(m, one);
    acts.classList.add('bf-read-acts');
    var close = el('button', 'bf-btn bf-read-close', 'Close');
    close.type = 'button';
    close.title = 'Fold the email away (Escape)';
    close.addEventListener('click', readClose);
    acts.appendChild(close);
    box.appendChild(acts);
    if (one.kind === 'ask' && G.open[ghostKey(m, one)]) ghostNudge(box, m, one);
    li.appendChild(box);
  }

  /* ---- one mailbox */

  // The emails put away from one tab (`kind` "unread" or "ask"), or from
  // both when the mailbox could not be read and there are no tabs.
  function hiddenList(sec, m, kind) {
    var put = (m.hidden || []).filter(function (one) { return !kind || one.kind === kind; });
    if (!put.length) return;
    var kinds = put.some(function (one) { return one.mark === 'nudged'; })
      ? 'deferred, dismissed, handled or nudged' : 'deferred, dismissed or handled';
    var toggle = el('button', 'bf-settings bf-ghost-toggle', (G.shown[m.id] ? 'Hide ' : 'Show ') +
      plural(put.length, kinds + ' email', kinds + ' emails'));
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', G.shown[m.id] ? 'true' : 'false');
    toggle.addEventListener('click', function () { G.shown[m.id] = !G.shown[m.id]; draw(); });
    sec.appendChild(toggle);
    if (!G.shown[m.id]) return;
    var hid = el('ul', 'bf-links bf-ghost-hidden');
    m.hidden.filter(function (one) { return !kind || one.kind === kind; }).forEach(function (one) {
      var li = el('li', 'bf-ghost-hid');
      wholeRow(li, m, one);
      var main = el('div', 'bf-ev-main');
      main.appendChild(opener(m, one, 'bf-link'));
      var who = one.kind === 'unread' ? (one.from.name || one.from.email)
        : (one.to[0] ? 'To ' + (one.to[0].name || one.to[0].email) : '');
      main.appendChild(el('p', 'bf-link-sub', (who ? who + ' · ' : '') + markWords(one)));
      li.appendChild(main);
      var back = el('button', 'bf-btn', 'Bring back');
      back.type = 'button';
      back.addEventListener('click', function () { ghostMark(m, one, 'restore'); });
      // Open, Bring back is under the whole email with the rest.
      if (reading(m, one)) drawReading(li, m, one); else li.appendChild(back);
      hid.appendChild(li);
    });
    sec.appendChild(hid);
  }

  function drawMailbox(body, m) {
    var sec = el('section', 'bf-sec bf-inbox');
    sec.setAttribute('aria-label', 'Mail in ' + m.email);
    var h = el('h4', 'bf-h bf-inbox-head');
    h.appendChild(headIcon('mail'));
    h.appendChild(el('span', 'bf-h-name bf-inbox-addr', m.email));
    if (m.read_only) {
      var ro = el('span', 'bf-ghost-ro', 'Read-only');
      ro.title = 'Rouh can read this mailbox: it cannot draft or change anything in it, ' +
        'and sends nothing from it but a forward you ask for, if you allowed forwarding ' +
        'from it in Settings.';
      h.appendChild(ro);
    }
    h.appendChild(el('span', 'bf-src', 'Gmail'));
    sec.appendChild(h);
    body.appendChild(sec);

    var said = G.said[m.id];
    if (said) {
      var line = el('p', 'bf-note bf-ghost-said' + (said.bad ? ' bad' : ''), said.text + ' ');
      line.setAttribute('role', 'status');
      if (said.one) {
        var undo = el('button', 'bf-settings', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () { ghostMark(m, said.one, 'restore'); });
        line.appendChild(undo);
      }
      sec.appendChild(line);
    }
    if (m.note) {
      sec.appendChild(el('p', 'bf-note' + (m.ok && !m.stale ? '' : ' bad'), m.note +
        (m.stale && m.at ? ' Below is what was found at ' + clock(m.at) + '.' : '')));
    }
    if (!m.ok) { hiddenList(sec, m); return; }

    // Two tabs (fr_1da7cddc045b): Incoming, what came into Primary in the
    // last day and is still unread, and Ghosts, Waiting on others. Incoming
    // is the one open to begin with. Both are drawn, the other one hidden,
    // so a printed brief has both.
    var unread = m.unread || [];
    var tab = G.tab[m.id] || 'incoming';
    var tabs = el('div', 'bf-tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Mail in ' + m.email);
    sec.appendChild(tabs);
    var panels = {};
    [['incoming', 'Incoming', unread.length], ['ghosts', 'Ghosts', m.items.length]]
      .forEach(function (t) {
        var id = 'bfTab' + m.id + t[0];
        var b = el('button', 'bf-tab', t[1]);
        b.type = 'button';
        b.id = id;
        b.setAttribute('role', 'tab');
        b.setAttribute('aria-selected', tab === t[0] ? 'true' : 'false');
        b.setAttribute('aria-controls', id + 'Panel');
        b.tabIndex = tab === t[0] ? 0 : -1;
        if (t[2]) b.appendChild(el('span', 'bf-tab-n', String(t[2])));
        b.addEventListener('click', function () { tabTo(m, t[0]); });
        b.addEventListener('keydown', function (e) {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home' &&
              e.key !== 'End') return;
          e.preventDefault();
          tabTo(m, tab === 'incoming' ? 'ghosts' : 'incoming');
        });
        tabs.appendChild(b);
        var panel = el('div', 'bf-tabpanel');
        panel.id = id + 'Panel';
        panel.setAttribute('role', 'tabpanel');
        panel.setAttribute('aria-labelledby', id);
        panel.hidden = tab !== t[0];
        // Printed, where there are no tabs, each says what it is.
        panel.appendChild(el('h5', 'bf-h5 bf-print-only', t[1]));
        panels[t[0]] = panel;
        sec.appendChild(panel);
      });

    // What came in. The tab says what it is, so there is no line saying it
    // again over the list, nor over Ghosts' (fr_aa4d72962ef5); only how much
    // is unread altogether, when there is any.
    var inc = panels.incoming;
    if (m.unread_total) inc.appendChild(el('p', 'bf-tab-about bf-inbox-count',
      (m.unread_more ? m.unread_total + ' or more' : m.unread_total) +
      ' unread in Primary altogether'));
    if (m.unread_note) inc.appendChild(el('p', 'bf-note bad', m.unread_note));
    if (unread.length) {
      var ul = el('ol', 'bf-ghost-list');
      unread.forEach(function (one) { ul.appendChild(unreadRow(m, one)); });
      inc.appendChild(ul);
    } else if (!m.unread_note) {
      inc.appendChild(el('p', 'bf-empty', 'Nothing new and unread in Primary in the last 24 hours.'));
    }
    hiddenList(inc, m, 'unread');

    // What is waiting on others.
    var gh = panels.ghosts;
    if (m.items.length) {
      var list = el('ol', 'bf-ghost-list');
      m.items.forEach(function (one) { list.appendChild(ghostRow(m, one)); });
      gh.appendChild(list);
    } else {
      gh.appendChild(el('p', 'bf-empty', 'Nobody owes you an answer: everything you asked ' +
        'from here in the last ' + m.look_back_days + ' days was answered, or was sent less ' +
        'than ' + m.wait_days + ' days ago.'));
    }
    if (m.more) gh.appendChild(el('p', 'bf-note', 'And ' + m.more + ' more, older.'));
    hiddenList(gh, m, 'ask');
  }

  function tabTo(m, which) {
    G.tab[m.id] = which;
    draw();
    var b = $('bfTab' + m.id + which);
    if (b) b.focus({ preventScroll: true });
  }

  function drawMailboxes(body) {
    var d = G.data;
    if (d && d.mailboxes.length && !G.error) {
      if (G.busy) body.appendChild(el('p', 'bf-note bf-inbox-busy',
        'Looking through your mailboxes again…'));
      d.mailboxes.forEach(function (m) { drawMailbox(body, m); });
      return;
    }
    var sec = el('section', 'bf-sec bf-inbox');
    sec.setAttribute('aria-label', 'Mail');
    var h = el('h4', 'bf-h');
    h.appendChild(headIcon('mail'));
    h.appendChild(el('span', 'bf-h-name', 'Mail'));
    h.appendChild(el('span', 'bf-src', 'Your mailboxes'));
    sec.appendChild(h);
    body.appendChild(sec);
    if (G.error) {
      sec.appendChild(el('p', 'bf-note bad', G.error));
      var again = el('button', 'bf-btn', 'Try again');
      again.type = 'button';
      again.addEventListener('click', function () { ghostsLoad(false); });
      var r = el('div', 'bf-pick-row');
      r.appendChild(again);
      sec.appendChild(r);
      return;
    }
    if (!d) {
      sec.appendChild(el('p', 'bf-empty', 'Reading your mailboxes…'));
      return;
    }
    sec.appendChild(el('p', 'bf-empty', d.can_connect
      ? 'Connect one of your mailboxes to see here what came in, and the emails you sent that ' +
        'asked for something and were never answered. Rouh only reads it: nothing is ever ' +
        'sent, drafted, archived or marked in it.'
      : 'Nothing to read yet: Google is not set up for your organisation, so no mailbox ' +
        'can be connected. An administrator enters its Google app in Settings.'));
    var row = el('div', 'bf-pick-row');
    var go = goLink(el('a', 'bf-btn primary', d.can_connect ? 'Connect a mailbox' : 'Open Settings'),
                    '/settings/email');
    go.addEventListener('click', function () {
      if (host().mailboxes) host().mailboxes(); else if (host().settings) host().settings();
    });
    row.appendChild(go);
    sec.appendChild(row);
  }

  // Escape puts an open email away, and nothing else: caught before the
  // layer's own Escape, which would close the brief.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !B.open) return;
    if (LK.one) {
      // The contact picker over the brief: that goes, and the brief stays.
      e.preventDefault();
      e.stopPropagation();
      linkClose();
      return;
    }
    if (EV.one) {
      // An event open over the brief: that goes, and the brief stays.
      e.preventDefault();
      e.stopPropagation();
      evClose();
      return;
    }
    if (!G.reading) return;
    e.preventDefault();
    e.stopPropagation();
    readClose();
  }, true);

  /* ------------------------------------------------------- the one thing */

  function oneThingAsk(method, body, done) {
    fetch('/api/brief/one-thing', {
      method: method, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (r.ok) done(j, '');
          else done(null, (j && j.error) || 'That could not be saved (the server said ' +
            r.status + ').');
        });
      })
      .catch(function () { done(null, 'Rouh could not be reached. Check the connection.'); });
  }

  function pickStart() {
    B.pick = { level: 'category', category: null, task: null, offered: null, query: '',
               error: '', saving: false };
    draw();
    oneThingAsk('GET', null, function (j, err) {
      if (!B.pick) return;
      B.pick.offered = j || { categories: [], tasks: [], note: '' };
      if (err) B.pick.error = 'Your projects could not be read just now, so type your own.';
      draw();
    });
  }

  function pickSave(sub) {
    var p = B.pick;
    p.saving = true;
    p.error = '';
    draw();
    oneThingAsk('POST', { category: p.category, task: p.task, sub: sub || null },
      function (j, err) {
        if (!B.pick) return;
        if (err) { p.saving = false; p.error = err; draw(); return; }
        B.pick = null;
        if (B.data) B.data.one_thing = j.one_thing;
        draw();
      });
  }

  function oneThingClear() {
    oneThingAsk('POST', { clear: true }, function (j, err) {
      if (err) { B.error = err; draw(); return; }
      if (B.data) B.data.one_thing = null;
      draw();
    });
  }

  // Picked at one level: on to the next, or saved at the last.
  function pickChose(level, item) {
    var p = B.pick;
    p.query = '';
    p.error = '';
    if (level === 'category') { p.category = item; p.level = 'task'; }
    else if (level === 'task') { p.task = item; p.level = 'sub'; }
    else { pickSave(item); return; }
    draw();
  }

  // Picked from a search outside the category: its category and task are
  // filled in, and a sub task picked that way is saved straight away.
  function pickWent(go) {
    var p = B.pick;
    p.query = '';
    p.error = '';
    p.category = go.category;
    p.task = go.task;
    p.level = 'sub';
    if (go.sub) { pickSave(go.sub); return; }
    draw();
  }

  function pickBack() {
    var p = B.pick;
    p.query = '';
    p.error = '';
    if (p.level === 'sub') { p.task = null; p.level = 'task'; }
    else if (p.level === 'task') { p.category = null; p.level = 'category'; }
    else B.pick = null;
    draw();
  }

  // What Rouh has at the level the picker is at.
  function pickItems(p) {
    var o = p.offered || { categories: [], tasks: [] };
    if (p.level === 'category') {
      return o.categories.map(function (c) { return { id: c.id, name: c.name, hint: c.side }; });
    }
    if (p.level === 'task') {
      return (p.category.id ? o.tasks.filter(function (t) { return t.category === p.category.id; })
                            : []).map(function (t) {
        var hint = [t.n != null ? '#' + t.n : '', t.done ? 'Done' : ''].filter(Boolean).join(' · ');
        // Its number is found as well as its name: "74" finds task 74.
        return { id: t.id, name: t.name, hint: hint, also: t.n != null ? String(t.n) : '' };
      });
    }
    var task = p.task.id ? o.tasks.filter(function (t) { return t.id === p.task.id; })[0] : null;
    return task ? task.subs.map(function (s) {
      return { id: s.id, name: s.name, hint: s.n || '', also: s.n || '' };
    }) : [];
  }

  // What was typed, as it is matched: "#74", "74: x" and "108-4" read as
  // "74", "74 x" and "108-04", the way tasks and steps are numbered.
  function pickQuery(typed) {
    return typed.trim().toLowerCase().replace(/^#/, '')
      .replace(/^(\d+)\s*[-.:·]\s*(\d+)(?!\d)/, function (_, a, b) {
        return a + '-' + (b.length < 2 ? '0' + b : b);
      })
      .replace(/^(\d+)\s*[-.:·]\s*(?=\D)/, '$1 ');
  }

  // A row is found by its name, or by its number with or without its name.
  function pickMatches(it, q) {
    if (!q) return true;
    if (it.name.toLowerCase().indexOf(q) >= 0) return true;
    return !!it.also && (it.also + ' ' + it.name.toLowerCase()).indexOf(q) === 0;
  }

  // Tasks and sub tasks outside the category the picker is in, for a search
  // that finds nothing there: Petar typed "108-04" under Various on 20 October
  // 2026 and was told none of his matched, because task 108 is in another
  // category (fr_319eeb5fa992). Picking one fills in its category and task.
  function pickElsewhere(p, q) {
    var o = p.offered || { categories: [], tasks: [] };
    if (!q || p.level === 'sub') return [];
    var cats = {};
    o.categories.forEach(function (c) { cats[c.id] = c; });
    var here = p.level === 'task' && p.category.id ? p.category.id : null;
    var tasks = [], steps = [];
    o.tasks.forEach(function (t) {
      var cat = cats[t.category];
      if (!cat) return;
      var task = { id: t.id, name: t.name };
      var also = t.n != null ? String(t.n) : '';
      if (t.category !== here && pickMatches({ name: t.name, also: also }, q)) {
        tasks.push({ name: t.name, also: also,
          hint: [also ? '#' + also : '', cat.name, t.done ? 'Done' : ''].filter(Boolean).join(' · '),
          go: { category: { id: cat.id, name: cat.name }, task: task } });
      }
      // A sub task by its name only once three letters are typed, and only
      // at the start of a word, or "ups" would offer every step with "groups".
      (t.subs || []).forEach(function (s) {
        var named = s.name.toLowerCase();
        var byNumber = !!s.n && (s.n + ' ' + named).indexOf(q) === 0;
        var at = named.indexOf(q);
        while (at > 0 && /[a-z0-9]/.test(named.charAt(at - 1))) at = named.indexOf(q, at + 1);
        if (!byNumber && (q.length < 3 || at < 0)) return;
        steps.push({ name: s.name, also: s.n || '',
          hint: [s.n, t.name].filter(Boolean).join(' · '),
          go: { category: { id: cat.id, name: cat.name }, task: task,
                sub: { id: s.id, name: s.name } } });
      });
    });
    return tasks.concat(steps).slice(0, 20);
  }

  var LEVEL_WORDS = { category: 'category', task: 'task', sub: 'sub task' };

  function drawPicker(sec) {
    var p = B.pick;
    var box = el('div', 'bf-pick');
    var steps = el('ol', 'bf-pick-steps');
    steps.setAttribute('aria-label', 'Steps');
    [['category', '1. Category'], ['task', '2. Task'], ['sub', '3. Sub task (optional)']]
      .forEach(function (s) {
        var li = el('li', s[0] === p.level ? 'on' : '', s[1]);
        if (s[0] === p.level) li.setAttribute('aria-current', 'step');
        steps.appendChild(li);
      });
    box.appendChild(steps);
    var so = [p.category && p.category.name, p.task && p.task.name].filter(Boolean);
    if (so.length) box.appendChild(el('p', 'bf-pick-so', so.join(' › ')));

    var word = LEVEL_WORDS[p.level];
    var label = el('label', 'bf-pick-label', p.level === 'sub'
      ? 'Pick a sub task, type one, or keep just the task'
      : 'Pick a ' + word + ' or type a new one');
    var input = el('input', 'bf-pick-input');
    input.type = 'text';
    input.maxLength = 200;
    input.value = p.query;
    input.placeholder = 'Find or type a ' + word;
    input.id = 'bfPickInput';
    label.htmlFor = input.id;
    box.appendChild(label);
    box.appendChild(input);

    var list = el('ul', 'bf-pick-list');
    list.setAttribute('aria-label', 'Your ' + word + (p.level === 'category' ? ' list' : 's'));
    box.appendChild(list);
    var add = el('button', 'bf-pick-add');
    add.type = 'button';
    box.appendChild(add);

    function refill() {
      var q = pickQuery(p.query);
      var all = pickItems(p);
      var shown = all.filter(function (it) { return pickMatches(it, q); });
      var far = shown.length ? [] : pickElsewhere(p, q);
      list.textContent = '';
      if (!p.offered) list.appendChild(el('li', 'bf-note', 'Reading your projects…'));
      else if (!all.length && !far.length) {
        list.appendChild(el('li', 'bf-note', p.offered.note && p.level === 'category'
          ? p.offered.note
          : 'Nothing here yet: type a ' + word + ' of your own.'));
      } else if (!shown.length && !far.length) {
        list.appendChild(el('li', 'bf-note', 'None of yours match.'));
      }
      shown.concat(far).forEach(function (it) {
        var li = el('li');
        var b = el('button', 'bf-pick-item');
        b.type = 'button';
        b.appendChild(el('span', 'bf-pick-name', it.name));
        if (it.hint) b.appendChild(el('span', 'bf-pick-hint', it.hint));
        b.disabled = p.saving;
        b.addEventListener('click', function () {
          if (it.go) pickWent(it.go);
          else pickChose(p.level, { id: it.id, name: it.name });
        });
        li.appendChild(b);
        list.appendChild(li);
      });
      var typed = p.query.trim();
      var same = all.some(function (it) {
        return it.name.toLowerCase() === typed.toLowerCase() || (!!it.also && it.also === q);
      });
      add.hidden = !typed || same;
      add.textContent = 'Use “' + typed + '” as a new ' + word;
      add.disabled = p.saving;
    }
    input.addEventListener('input', function () { p.query = input.value; refill(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !add.hidden) { e.preventDefault(); add.click(); }
      if (e.key === 'Escape') { e.preventDefault(); B.pick = null; draw(); }
    });
    add.addEventListener('click', function () {
      var typed = p.query.trim();
      if (typed) pickChose(p.level, { name: typed });
    });
    refill();

    var row = el('div', 'bf-pick-row');
    var back = el('button', 'bf-btn', p.level === 'category' ? 'Cancel' : 'Back');
    back.type = 'button';
    back.addEventListener('click', pickBack);
    row.appendChild(back);
    if (p.level === 'sub') {
      var none = el('button', 'bf-btn primary', 'No sub task, just the task');
      none.type = 'button';
      none.disabled = p.saving;
      none.addEventListener('click', function () { pickSave(null); });
      row.appendChild(none);
    }
    if (p.saving) row.appendChild(el('span', 'bf-note', 'Saving…'));
    box.appendChild(row);
    if (p.error) box.appendChild(el('p', 'bf-say bad', p.error));
    sec.appendChild(box);
    return input;
  }

  function drawOneThing(body, chosen) {
    var sec = el('section', 'bf-sec bf-one');
    sec.setAttribute('aria-label', 'The one thing');
    var h = el('h4', 'bf-h');
    h.appendChild(headIcon('one'));
    h.appendChild(el('span', 'bf-h-name', 'The one thing'));
    h.appendChild(el('span', 'bf-h-sub', 'what makes today a win if nothing else happens'));
    sec.appendChild(h);
    body.appendChild(sec);
    if (B.pick) return drawPicker(sec);
    var row = el('div', 'bf-pick-row');
    if (!chosen) {
      sec.appendChild(el('p', 'bf-empty', 'Nothing chosen for today yet.'));
      var pick = el('button', 'bf-btn primary', 'Pick the one thing');
      pick.type = 'button';
      pick.addEventListener('click', pickStart);
      row.appendChild(pick);
      sec.appendChild(row);
      return null;
    }
    var main = chosen.sub || chosen.task;
    sec.appendChild(el('p', 'bf-one-name', main.name));
    sec.appendChild(dotted(el('p', 'bf-one-ctx'), [
      chosen.category.name, chosen.sub ? chosen.task.name : '']));
    var change = el('button', 'bf-btn', 'Change');
    change.type = 'button';
    change.addEventListener('click', pickStart);
    var clear = el('button', 'bf-btn', 'Clear');
    clear.type = 'button';
    clear.addEventListener('click', oneThingClear);
    row.appendChild(change);
    row.appendChild(clear);
    sec.appendChild(row);
    return null;
  }

  function greeting(name) {
    var h = new Date().getHours();
    var word = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    return word + (name ? ', ' + name : '');
  }

  function foot(body, d) {
    var f = el('footer', 'bf-foot');
    var s = d.settings || {};
    var said = s.on
      ? 'Made by itself every morning at ' + s.time + (d.sent_at ? ', and this one at ' +
        clock(d.sent_at) : '') + '. '
      : 'Not made by itself: press Update to make it. ';
    f.appendChild(el('span', null, said + (s.place
      ? 'The weather is for ' + s.place + ', your location. '
      : 'No location is set, so there is no weather. ')));
    if (keptOnly()) {
      f.textContent = '';
      f.appendChild(el('span', null, 'This is the brief of ' + longDay(d.day) + ', as it was made' +
        (d.made_at ? ' at ' + clock(d.made_at) : '') + '. Nothing in it has been read again. '));
    } else {
      var change = goLink(el('a', 'bf-settings', 'Change these in Settings'), '/settings/brief');
      change.addEventListener('click', function () { if (host().settings) host().settings(); });
      f.appendChild(change);
    }
    // Every brief kept, newest first (fr_5fb00def9d2d: "There should be a link
    // at the bottom that takes me to all previously generated briefs").
    var links = el('p', 'bf-foot-links');
    links.appendChild(briefLink('past', 'bf-settings bf-kept-link', 'All past briefs'));
    if (keptOnly()) {
      links.appendChild(document.createTextNode(' · '));
      links.appendChild(briefLink('', 'bf-settings', 'Today’s brief'));
    }
    f.appendChild(links);
    body.appendChild(f);
  }

  // The day after a YYYY-MM-DD.
  function nextDay(iso) {
    var at = new Date(String(iso || '') + 'T12:00:00Z');
    if (isNaN(at.getTime())) return '';
    at.setUTCDate(at.getUTCDate() + 1);
    return at.toISOString().slice(0, 10);
  }

  // How a kept brief's day is said beside today: "yesterday", or "Wednesday 7 October".
  function dayFrom(iso) {
    return B.today && nextDay(iso) === B.today ? 'yesterday' : longDay(iso);
  }

  // Whether the last Update found this section changed, on today's brief.
  function updated(key) {
    var u = B.data && !keptOnly() && !older() && B.data.update;
    return !!(u && (u.changed || []).indexOf(key) >= 0);
  }

  // The parts an Update names, in the order the page draws them.
  var CHANGES = { weather: 'Weather', calendar: 'Calendar', slack: 'Slack', world: 'World News',
                  ai: 'AI', history: 'Today in history', birthdays: 'Birthdays' };

  // What the last Update found, in a line at the top of today's brief.
  function drawUpdate(body, d) {
    var u = d.update;
    if (!u || keptOnly() || older()) return;
    var names = (u.changed || []).map(function (k) { return CHANGES[k]; }).filter(Boolean);
    var since = u.since ? ' since ' + clock(u.since) : '';
    var said = 'Updated at ' + clock(u.at) + '. ' + (names.length
      ? 'New' + since + ': ' + names.join(', ') + '. The rest was the same, and is as it was.'
      : 'Nothing had changed' + since + ', so the brief is as it was.');
    var p = el('p', 'bf-updated', said);
    p.setAttribute('role', 'status');
    body.appendChild(p);
  }

  // When today's is made by itself, in words, or that it is not.
  function scheduleWords() {
    var s = B.schedule || (B.data && B.data.settings) || {};
    return s.on && s.time ? 'It is made by itself every morning at ' + s.time +
      '; press Update to make today’s now.'
      : 'It is not made by itself (that is off in Settings): press Update to make today’s.';
  }

  // Today's is not made yet, and an earlier one is up in its place.
  function drawOlder(body, d) {
    var p = el('p', 'bf-older');
    p.appendChild(el('strong', null, 'This is ' + (dayFrom(d.day) === 'yesterday' ? 'yesterday’s brief'
      : 'the brief of ' + longDay(d.day)) + ', the newest there is. '));
    p.appendChild(document.createTextNode(scheduleWords()));
    body.appendChild(p);
  }

  // There has never been a brief: said plainly, and nothing is made by opening the page.
  function drawNone(body) {
    var sec = el('section', 'bf-sec bf-none');
    sec.setAttribute('aria-label', 'No brief yet');
    sec.appendChild(el('p', 'bf-empty', 'No morning brief has been made yet.'));
    sec.appendChild(el('p', 'bf-note', scheduleWords()));
    var change = goLink(el('a', 'bf-settings', 'Change when it is made in Settings'), '/settings/brief');
    change.addEventListener('click', function () { if (host().settings) host().settings(); });
    var p = el('p', 'bf-note');
    p.appendChild(change);
    sec.appendChild(p);
    body.appendChild(sec);
  }

  // "Wednesday 7 October", from a day's YYYY-MM-DD.
  function longDay(iso) {
    var at = new Date(String(iso || '') + 'T12:00:00Z');
    if (isNaN(at.getTime())) return iso || '';
    return at.toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'long', day: 'numeric',
                                            month: 'long' });
  }

  // The heading is today's date, short, and under it only when it was made.
  function meta() {
    var m = $('briefMeta'), t = $('briefTitle');
    if (t && B.view === 'past') {
      t.textContent = 'Past briefs';
      t.removeAttribute('title');
    } else if (t) {
      var day = B.data && shortDate(B.data.day);
      t.textContent = '';
      t.removeAttribute('title');
      if (!day) t.textContent = 'Morning brief';
      else {
        // The weekday short on a narrow phone, where the whole of "Wednesday,"
        // does not fit beside Print, Update and the X (briefpage.css).
        var comma = day.indexOf(',');
        t.title = day;
        t.appendChild(el('span', 'bf-day-long', day.slice(0, comma)));
        t.appendChild(el('span', 'bf-day-short', day.slice(0, 3)));
        t.appendChild(document.createTextNode(day.slice(comma)));
      }
    }
    if (!m) return;
    m.textContent = '';
    if (B.view === 'past') { m.textContent = 'newest first, each as it was made'; return; }
    if (B.busy && keptOnly()) return;
    if (B.busy) {
      m.textContent = B.data && !older() ? 'Updating…' : 'Making today’s brief…';
      return;
    }
    if (!B.data) return;
    if (older()) {
      m.textContent = 'made ' + dayFrom(B.data.day) + ' at ' + clock(B.data.made_at);
      return;
    }
    m.textContent = 'made at ' + clock(B.data.made_at) + (keptOnly() ? ', a past brief'
      : B.data.updated_at ? ', updated at ' + clock(B.data.updated_at) : '');
  }

  function draw() {
    var body = $('briefBody'), button = $('briefRefresh');
    if (!body) return;
    // Update is today's only: a past brief stays as it was made.
    if (button) { button.disabled = B.busy; button.hidden = keptOnly(); }
    body.setAttribute('aria-busy', (B.view === 'past' ? B.past.busy : B.busy) ? 'true' : 'false');
    meta();
    body.textContent = '';
    if (B.view === 'past') {
      var list = el('div', 'bf-page');
      drawPast(list);
      body.appendChild(list);
      return;
    }
    if (B.error) body.appendChild(el('p', 'bf-say bad', B.error));
    var d = B.data;
    if (!d) {
      if (B.busy && keptOnly()) body.appendChild(el('p', 'bf-empty', 'Reading the brief kept for ' +
        longDay(B.view) + '…'));
      else if (B.busy && B.making) body.appendChild(el('p', 'bf-empty', 'Reading the weather, your calendar ' +
        'and the news, the new videos from your AI channels, and what happened on this ' +
        'day in history. This can take a minute.'));
      else if (B.busy) body.appendChild(el('p', 'bf-empty', 'Reading the brief…'));
      else if (!B.error && !keptOnly() && B.today) {
        var none = el('div', 'bf-page');
        drawNone(none);
        body.appendChild(none);
      }
      return;
    }
    var now = Date.now() / 1000;
    var page = el('div', 'bf-page');
    var hello = el('div', 'bf-hello');
    hello.appendChild(el('h2', 'bf-greet', greeting(d.name)));
    page.appendChild(hello);
    if (older()) drawOlder(page, d);
    drawUpdate(page, d);
    drawWeather(page, d.weather);
    // The one thing and the mail are today's, and read as the page opens,
    // so a past brief has neither.
    var typing = keptOnly() ? null : drawOneThing(page, d.one_thing);
    // Your word, by mail is something to do today, so it comes before the day's meetings (a tester
    // nearly gave up looking for it lower down, trial 10).
    if (d.my_word && !keptOnly()) drawMyWord(page, d.my_word);
    // Guests who have not said yes goes before the calendar it is about: who has not answered is
    // not in the calendar's own boxes, and a tester reading them never got past them (trial 42).
    if (d.not_said_yes && !keptOnly()) drawNotSaidYes(page, d.not_said_yes);
    // Invitations you have not answered is about meetings in the calendar too, and waits on him.
    if (d.not_answered && !keptOnly()) drawNotAnswered(page, d.not_answered);
    drawCalendar(page, d.calendar, now);
    // Gone quiet is about who is missing from the calendar above it.
    if (d.gone_quiet && !keptOnly()) drawGoneQuiet(page, d.gone_quiet);
    // Meetings with nowhere to meet is about the meetings just above it, so it is drawn under them.
    if (d.no_place && !keptOnly()) drawNoPlace(page, d.no_place);
    if (!keptOnly()) drawMailboxes(page);
    if (d.slack) drawSlack(page, d.slack, now);
    if (d.owed && !keptOnly()) drawOwed(page, d.owed);
    if (d.no_notes && !keptOnly()) drawNoNotes(page, d.no_notes);
    if (d.next_meeting && !keptOnly()) drawNextMeeting(page, d.next_meeting);
    if (d.others_changed && !keptOnly()) drawOthersChanged(page, d.others_changed);
    if (d.shared_with_you && !keptOnly()) drawShared(page, d.shared_with_you);
    if (d.not_opened && !keptOnly()) drawNotOpened(page, d.not_opened);
    if (d.new_comments && !keptOnly()) drawNewComments(page, d.new_comments);
    if (d.talk_deck && !keptOnly()) drawTalkDeck(page, d.talk_deck);
    if (d.not_handed && !keptOnly()) drawNotHanded(page, d.not_handed);
    if (d.task_dates && !keptOnly()) drawTaskDates(page, d.task_dates);
    if (d.host_admits && !keptOnly()) drawHostAdmits(page, d.host_admits);
    if (d.flight_open && !keptOnly()) drawFlightOpen(page, d.flight_open);
    if (d.invite_missing && !keptOnly()) drawInviteMissing(page, d.invite_missing);
    drawWorld(page, d.world);
    drawAi(page, d.ai);
    if (d.reminders) drawReminders(page, d.reminders, now);
    if (d.report) drawReport(page, d.report);
    if (d.history) drawHistory(page, d.history);
    if (d.birthdays) drawBirthdays(page, d.birthdays);
    drawDoodle(page, d);
    drawJoke(page, d.joke);
    foot(page, d);
    body.appendChild(page);
    if (WANT_EVENT && !B.busy && !keptOnly()) openWanted();
    // The picker is drawn afresh at each level; the box to type in is where
    // the keyboard goes, so the next level can be typed straight away.
    if (typing) typing.focus({ preventScroll: true });
  }

  /* ------------------------------------------------------------ the layer */

  function shownNow(view) {
    var was = B.view;
    B.open = true;
    B.view = view || '';
    if (was !== B.view) {
      // Another brief, or the list: nothing of the one that was up is drawn
      // under it, and nothing still on its way for it is drawn when it comes.
      evClose();
      linkClose();
      B.pick = null;
      B.topics = null;
      B.data = null;
      B.error = '';
      B.busy = false;
      B.cal.seq++;
      B.cal.busy = false;
      B.cal.part = null;
      B.seq++;
      var scroller = $('briefView');
      if (scroller) scroller.scrollTop = 0;
    }
    if (B.view === 'past') {
      B.past.list = null;
      pastLoad();
    } else if (B.view) {
      // One day's brief, exactly as it was kept.
      ask('GET', '/api/brief/day/' + encodeURIComponent(B.view));
    } else {
      // Today's: drawn at once when it is up already, and read again underneath.
      draw();
      if (B.stale) { B.stale = false; remake(); } else load();
      calendarLoad();
    }
    clearInterval(B.tick);
    // What is past and what is on now moves with the clock.
    B.tick = setInterval(function () {
      // Not while a nudge is open, or an email: it is being read, edited or copied.
      var nudging = Object.keys(G.open).some(function (k) { return G.open[k]; });
      if (B.open && !B.busy && !B.pick && !B.topics && !nudging && !G.reading && !LK.one &&
          B.view !== 'past') draw();
    }, 60000);
  }

  function hiddenNow() {
    B.open = false;
    evClose();
    linkClose();
    G.reading = null;
    B.pick = null;
    B.topics = null;
    clearInterval(B.tick);
  }

  (function wire() {
    var close = $('briefClose'), refresh = $('briefRefresh'), print = $('briefPrint');
    if (close) close.addEventListener('click', function () { if (host().close) host().close(); });
    if (refresh) refresh.addEventListener('click', remake);
    // The whole brief, on as many pages as it takes (briefpage.css, @media print).
    if (print) print.addEventListener('click', function () { window.print(); });
  })();

  window.RouhBrief = {
    shown: shownNow,
    hidden: hiddenNow,
    reload: function () { if (!B.view) load(); },
    // The second time zone changed in Settings: read the brief again, which
    // is quick, since it is kept, and says the new zone.
    zonesChanged: function () {
      if (!B.open || B.view === 'past') return;
      ask('GET', B.view ? '/api/brief/day/' + encodeURIComponent(B.view) : '/api/brief');
    },
    // A new time or channels: the brief is made again the next time it is
    // opened, so the weather and the footer say the new ones.
    settingsChanged: function () { if (B.open && !B.view) remake(); else B.stale = true; },
    // A mailbox connected or disconnected in Settings: the mail is read
    // again, straight away if the brief is open.
    mailboxesChanged: function () {
      G.data = null;
      G.reading = null;
      if (B.open) ghostsLoad(false);
    }
  };
})();
