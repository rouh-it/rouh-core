/* Receipts, at /receipts: every receipt and invoice in the person's mail, one
   month at a time, with what each says was paid, its files, and one download
   of the month for the accountant (`rouh/receipts.py`, `rouh/web/receipts.py`).

   Built by the nightly feature run, night 4, 7 October 2026 (task 94, idea
   I-006): a company's receipts arrive by mail, about sixty a month, and
   gathering them for the books was a search, a download per email and a list
   typed by hand. Behind the switch `receipts`.

   The layer, its address and its row in the sidebar are app/runs.js's
   (`receiptsOpen`), handed over through `window.RouhReceiptsHost`. */
(function () {
  'use strict';

  var R = { open: false, month: '', data: null, error: '', seq: 0, loading: false, zipping: false,
            zipSaid: '' };

  function host() { return window.RouhReceiptsHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function zone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; }
  }
  function headers() { var z = zone(); return z ? { 'X-Time-Zone': z } : {}; }

  /* ---- words ---- */

  function monthSaid(name) {
    var got = /^(\d{4})-(\d{2})$/.exec(name || '');
    if (!got) { return name || ''; }
    return new Date(Number(got[1]), Number(got[2]) - 1, 1)
      .toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  }
  function money(currency, value) {
    var n = Number(value);
    try {
      return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency }).format(n);
    } catch (e) {
      return currency + ' ' + n.toFixed(2);
    }
  }
  function day(at) {
    if (!at) { return ''; }
    return new Date(at * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }
  function kind(file) {
    var t = String(file.type || '').toLowerCase();
    var ext = /\.([a-z0-9]{2,4})$/i.exec(file.name || '');
    if (t === 'application/pdf') { return 'PDF'; }
    if (t.indexOf('image/') === 0) { return 'Picture'; }
    return ext ? ext[1].toUpperCase() : 'File';
  }
  function fileHref(row, file) {
    return '/api/receipts/file?inbox=' + encodeURIComponent(row.inbox) + '&id=' +
      encodeURIComponent(row.id) + '&part=' + encodeURIComponent(file.part);
  }

  /* ---- reading ---- */

  function load(again) {
    var seq = ++R.seq;
    R.loading = true;
    R.error = '';
    draw();
    var q = '/api/receipts?month=' + encodeURIComponent(R.month) + (again ? '&again=1' : '');
    return fetch(q, { credentials: 'same-origin', cache: 'no-store', headers: headers() })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== R.seq) { return; }
          R.loading = false;
          if (!r.ok || !j) {
            R.error = (j && j.error) || 'Your receipts could not be read. Try again in a moment.';
          } else {
            R.data = j;
            if (!R.month && j.month) { R.month = j.month; }
          }
          if (R.open) { draw(); }
        });
      })
      .catch(function () {
        if (seq !== R.seq) { return; }
        R.loading = false;
        R.error = 'Rouh could not be reached. Try again in a moment.';
        if (R.open) { draw(); }
      });
  }

  function pick(month) {
    if (!month || month === R.month) { return; }
    R.month = month;
    R.data = null;
    R.zipSaid = '';
    load(false);
  }

  /* The month as a zip: fetched here rather than followed as a link, so the
     button can say it is being made, which takes a while for sixty files. */
  function download() {
    if (R.zipping) { return; }
    R.zipping = true;
    R.zipSaid = '';
    draw();
    var month = R.month;
    fetch('/api/receipts/zip?month=' + encodeURIComponent(month),
          { credentials: 'same-origin', cache: 'no-store', headers: headers() })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return null; }).then(function (j) {
            throw new Error((j && j.error) || 'The zip could not be made. Try again in a moment.');
          });
        }
        return r.blob().then(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'receipts-' + month + '.zip';
          document.body.appendChild(a);
          a.click();
          setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 60000);
          R.zipSaid = 'Downloaded receipts-' + month + '.zip.';
        });
      })
      .catch(function (err) { R.zipSaid = String((err && err.message) || err); })
      .then(function () { R.zipping = false; if (R.open) { draw(); } });
  }

  /* ---- drawing ---- */

  function bar(d) {
    var b = el('div', 'rc-bar');
    var months = (d && d.months) || [];
    var at = months.indexOf(R.month);
    var older = el('button', 'ctl small rc-step', '‹');
    older.type = 'button';
    older.title = 'The month before';
    older.setAttribute('aria-label', 'The month before');
    older.disabled = at < 0 || at >= months.length - 1;
    older.addEventListener('click', function () { pick(months[at + 1]); });
    var choose = el('select', 'rc-month');
    choose.setAttribute('aria-label', 'Month');
    months.forEach(function (m) {
      var o = el('option', '', monthSaid(m));
      o.value = m;
      if (m === R.month) { o.selected = true; }
      choose.appendChild(o);
    });
    if (!months.length) {
      var only = el('option', '', monthSaid(R.month) || 'This month');
      choose.appendChild(only);
      choose.disabled = true;
    }
    choose.addEventListener('change', function () { pick(choose.value); });
    var newer = el('button', 'ctl small rc-step', '›');
    newer.type = 'button';
    newer.title = 'The month after';
    newer.setAttribute('aria-label', 'The month after');
    newer.disabled = at <= 0;
    newer.addEventListener('click', function () { pick(months[at - 1]); });
    var again = el('button', 'ctl small rc-again', 'Read again');
    again.type = 'button';
    again.title = 'Read the mail again for this month';
    again.disabled = R.loading;
    again.addEventListener('click', function () { load(true); });
    var zip = el('button', 'ctl rc-zip', R.zipping ? 'Making the zip…' : 'Download for the accountant');
    zip.type = 'button';
    zip.title = 'Every file of the month, named by date and sender, with a list as receipts.csv';
    zip.disabled = R.zipping || R.loading || !(d && d.rows && d.rows.length);
    zip.addEventListener('click', download);
    var pickRow = el('div', 'rc-pick');
    pickRow.appendChild(older);
    pickRow.appendChild(choose);
    pickRow.appendChild(newer);
    b.appendChild(pickRow);
    b.appendChild(again);
    b.appendChild(zip);
    return b;
  }

  function summary(d) {
    var s = el('div', 'rc-sum');
    var rows = d.rows || [];
    s.appendChild(el('span', 'rc-count', rows.length === 1 ? '1 receipt' : rows.length + ' receipts'));
    (d.totals || []).forEach(function (t) {
      var chip = el('span', 'rc-total', money(t.currency, t.value));
      chip.title = t.count + (t.count === 1 ? ' receipt' : ' receipts') + ' in ' + t.currency;
      s.appendChild(chip);
    });
    var unread = rows.filter(function (r) { return !r.amount; }).length;
    if (unread) {
      s.appendChild(el('span', 'rc-unsaid', unread === 1 ? '1 says no amount in its words'
                                                         : unread + ' say no amount in their words'));
    }
    return s;
  }

  function line(row) {
    var li = el('li', 'rc-row');
    li.appendChild(el('span', 'rc-day', day(row.at)));
    var what = el('div', 'rc-what');
    what.appendChild(el('span', 'rc-who', row.merchant));
    var subject = el('span', 'rc-subject', row.subject);
    subject.title = row.subject;
    what.appendChild(subject);
    var files = el('div', 'rc-files');
    (row.files || []).forEach(function (f) {
      var a = el('a', 'rc-file');
      a.appendChild(el('span', 'rc-kind', kind(f)));
      a.appendChild(document.createTextNode(f.name));
      a.href = fileHref(row, f);
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = 'Open ' + f.name;
      files.appendChild(a);
    });
    if (row.link) {
      var g = el('a', 'rc-gmail', 'Gmail');
      g.href = row.link;
      g.target = '_blank';
      g.rel = 'noopener';
      g.title = 'Open the email in Gmail';
      files.appendChild(g);
    }
    what.appendChild(files);
    li.appendChild(what);
    var paid = el('span', 'rc-amount' + (row.amount ? '' : ' rc-none'),
                  row.amount ? money(row.amount.currency, row.amount.value) : '–');
    if (!row.amount) {
      paid.title = 'The email does not say an amount in its words' +
        ((row.files || []).length ? ': see its file' : '');
    }
    li.appendChild(paid);
    return li;
  }

  function draw() {
    var body = $('receiptsBody');
    var meta = $('receiptsMeta');
    if (!body) { return; }
    body.setAttribute('aria-busy', R.loading ? 'true' : 'false');
    body.textContent = '';
    var d = R.data;
    var page = el('div', 'rc-page');
    body.appendChild(page);
    if (d && d.off) {
      if (meta) { meta.textContent = ''; }
      var off = el('div', 'rc-empty');
      off.appendChild(el('p', 'rc-empty-h', 'Receipts is switched off.'));
      off.appendChild(el('p', 'rc-empty-p', 'Turn it on in Evolution, Mutations.'));
      page.appendChild(off);
      return;
    }
    page.appendChild(bar(d));
    if (meta) {
      var from = d && d.inboxes ? d.inboxes.map(function (i) { return i.address; }) : [];
      meta.textContent = from.length ? 'From ' + from.join(' and ') : '';
    }
    if (R.zipSaid) { page.appendChild(el('p', 'rc-said', R.zipSaid)); }
    if (R.error) { page.appendChild(el('p', 'rc-error', R.error)); }
    if (R.loading && !(d && d.month === R.month)) {
      page.appendChild(el('p', 'rc-loading', 'Reading your mail for ' +
        (R.month ? monthSaid(R.month) : 'this month') + '…'));
      return;
    }
    if (!d) { return; }
    (d.trouble || []).forEach(function (t) { page.appendChild(el('p', 'rc-error', t)); });
    var rows = d.rows || [];
    // Nothing found because nothing could be read says only that.
    if (!rows.length && (d.trouble || []).length) { return; }
    if (!rows.length) {
      var none = el('div', 'rc-empty');
      none.appendChild(el('p', 'rc-empty-h', 'No receipts or invoices for ' + monthSaid(d.month) + '.'));
      none.appendChild(el('p', 'rc-empty-p', 'Rouh looks for what Gmail files under Purchases and ' +
        'for receipt, invoice, billing, фактура or ' +
        'разписка in the subject.'));
      page.appendChild(none);
      return;
    }
    page.appendChild(summary(d));
    var inboxes = d.inboxes || [];
    var groups = inboxes.length > 1 ? inboxes : [{ address: '', whose: '' }];
    groups.forEach(function (box) {
      var mine = rows.filter(function (r) { return !box.address || r.inbox === box.address; });
      if (!mine.length) { return; }
      var sec = el('section', 'rc-sec');
      if (box.address) {
        var h = el('h4', 'rc-h');
        h.appendChild(el('span', '', box.address));
        h.appendChild(el('span', 'rc-whose', box.whose === 'rouh' ? 'Rouh’s inbox' : 'your inbox'));
        h.appendChild(el('span', 'rc-n', String(mine.length)));
        sec.appendChild(h);
      }
      var list = el('ul', 'rc-list');
      mine.forEach(function (r) { list.appendChild(line(r)); });
      sec.appendChild(list);
      page.appendChild(sec);
    });
  }

  /* ---- the layer ---- */

  function shown() {
    R.open = true;
    if (!R.data && !R.loading) { load(false); } else { draw(); }
  }
  function hidden() { R.open = false; }

  window.RouhReceipts = { shown: shown, hidden: hidden, reload: function () { return load(true); } };

  var x = $('receiptsClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
