/* A person's email addresses, as one list (rouh/person_addresses.py).

   Petar, 27 October 2026: the contact card listed the iCloud card's addresses at the top and the ones
   Rouh knew further down, and his profile listed them under "Connected" and then again under "Your email
   addresses, for mail". One list now, drawn by this one component on the contact card (app/cards.js,
   contactBlock) and on the profile (app/runs.js, meDraw), at every width. Each row is:

   - the address, and its label exactly as the iCloud card has it (home, work, other, iCloud, or one of
     the person's own);
   - where it comes from: the iCloud card, the Rouh account, or known only to Rouh;
   - for the person's own addresses, whether it is a mailbox connected to Rouh: Connected only when it
     really is, Not connected otherwise, with Connect where Rouh can connect it;
   - its silo, a chip pressed to change it in place: the silos open under the row, one press puts the
     address in one, and mail from or to it is labelled so;
   - Unlink, for an address that is only Rouh's guess on somebody else's card.

   It talks to /api/people/<person>/addresses. What it was drawn with may be older than what is kept
   (a card drawn yesterday), so it reads the list once and draws again only if it differs. Every word in
   it may be somebody's own, so all of it goes in as text. */
(function () {
  'use strict';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }

  function button(cls, text, label) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (label) b.setAttribute('aria-label', label);
    return b;
  }

  function chip(c, cls) {
    var span = el('span', 'silo-chip' + (cls ? ' ' + cls : ''));
    if (c && /^#[0-9a-f]{6}$/i.test(c.colour || '')) span.style.setProperty('--silo', c.colour);
    span.appendChild(el('span', 'silo-dot'));
    span.appendChild(el('span', 'silo-name', (c && c.name) || 'No silo'));
    return span;
  }

  function call(url, body) {
    var init = { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (body) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('Sign in again.'); }
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
        if (!r.ok || !j || j.ok === false) {
          throw new Error((j && (j.why || j.error)) || 'That could not be done (the server said ' + r.status + ').');
        }
        return j;
      });
    }, function () { throw new Error('Rouh could not be reached. Try again.'); });
  }

  var MAILBOX = { connected: 'is-good', reconnect: 'is-bad', not_connected: 'is-quiet', rouh: 'is-quiet' };

  /**
   * @param {{data: any, editable?: boolean, ds?: string, title?: string,
   *          extra?: function(any, HTMLElement): void, changed?: function(any): void}} opts
   */
  function list(opts) {
    var data = opts.data || null;
    var box = el('section', 'pa');
    var head = el('div', 'pa-head');
    var title = el('h5', 'pa-title', opts.title || 'Email addresses');
    title.id = 'paT' + Math.random().toString(36).slice(2, 9);
    box.setAttribute('aria-labelledby', title.id);
    head.appendChild(title);
    box.appendChild(head);
    var ul = el('ul', 'pa-rows');
    box.appendChild(ul);
    var said = el('p', 'pa-said');
    said.hidden = true;
    said.setAttribute('role', 'alert');
    box.appendChild(said);
    var open = '';   // the address whose silos are open under it
    var busy = false;
    var base = function () {
      return '/api/people/' + encodeURIComponent((data && data.person) || '') + '/addresses';
    };

    function fail(e) {
      busy = false;
      box.classList.remove('is-busy');
      said.textContent = (e && e.message) || 'That could not be done.';
      said.hidden = false;
      draw();
    }

    function took(j) {
      busy = false;
      box.classList.remove('is-busy');
      data = j;
      open = '';
      draw();
      if (opts.changed) opts.changed(j);
    }

    function setSilo(row, key) {
      if (busy) return;
      busy = true;
      box.classList.add('is-busy');
      said.hidden = true;
      Array.prototype.forEach.call(box.querySelectorAll('button'), function (x) { x.disabled = true; });
      call(base() + '/silo', { address: row.address, silo: key }).then(took).catch(fail);
    }

    function unlink(row) {
      if (busy || !opts.ds) return;
      busy = true;
      box.classList.add('is-busy');
      said.hidden = true;
      Array.prototype.forEach.call(box.querySelectorAll('button'), function (x) { x.disabled = true; });
      var aka = '/api/synapse/ds/' + encodeURIComponent(opts.ds) + '/item/' + encodeURIComponent(data.person) + '/aka';
      call(aka + '/unlink', { type: 'email', value: row.address.toLowerCase(), by: 'contact card' })
        .then(function () { return call(base(), null); }).then(took).catch(fail);
    }

    function siloControl(row) {
      var wrap = el('span', 'pa-silo');
      var c = row.silo;
      var editable = opts.editable !== false && data && data.person && (data.silos || []).length;
      var shown = chip(c, (c ? '' : 'is-none') + (row.silo_by === 'domain' ? ' is-derived' : ''));
      if (!editable) {
        wrap.appendChild(shown);
      } else {
        var press = button('pa-silo-btn', null, (c ? 'Silo of ' + row.address + ': ' + c.name : row.address + ' is in no silo') + '. Change it');
        press.setAttribute('aria-expanded', open === row.address ? 'true' : 'false');
        press.appendChild(shown);
        press.addEventListener('click', function () {
          open = open === row.address ? '' : row.address;
          draw();
        });
        wrap.appendChild(press);
      }
      if (row.silo_why) wrap.appendChild(el('span', 'pa-why', row.silo_why));
      return wrap;
    }

    function choices(row) {
      var group = el('div', 'pa-choices');
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', 'Silo for ' + row.address);
      var mine = row.silo_by === 'address' && row.silo ? row.silo.key : '';
      (data.silos || []).forEach(function (c) {
        var b = button('silo-toggle', null, c.name);
        b.setAttribute('aria-pressed', mine === c.key ? 'true' : 'false');
        b.appendChild(chip(c));
        b.addEventListener('click', function () { setSilo(row, mine === c.key ? '' : c.key); });
        group.appendChild(b);
      });
      if (mine) {
        var none = button('pa-btn', 'No silo', 'Take ' + row.address + ' out of its silo');
        none.addEventListener('click', function () { setSilo(row, ''); });
        group.appendChild(none);
      }
      group.appendChild(el('p', 'pa-hint', 'Mail from or to this address goes in the silo picked here.'));
      return group;
    }

    function rowNode(row) {
      var li = el('li', 'pa-row');
      li.setAttribute('data-address', row.address);
      var main = el('div', 'pa-main');
      var top = el('div', 'pa-top');
      top.appendChild(el('span', 'pa-addr', row.address));
      if (row.label) top.appendChild(el('span', 'pa-label', row.label));
      main.appendChild(top);
      var meta = el('div', 'pa-meta');
      if (row.source_said) meta.appendChild(el('span', 'pa-from', row.source_said));
      if (row.mailbox) {
        var state = el('span', 'pa-box ' + (MAILBOX[row.mailbox] || ''), row.mailbox_said || '');
        meta.appendChild(state);
      }
      if (row.connect) {
        var go = el('a', 'pa-btn is-main', row.mailbox === 'reconnect' ? 'Connect again' : 'Connect');
        go.href = row.connect;
        go.setAttribute('aria-label', 'Connect the mailbox ' + row.address + ' to Rouh');
        meta.appendChild(go);
      }
      main.appendChild(meta);
      li.appendChild(main);
      var side = el('div', 'pa-side');
      side.appendChild(siloControl(row));
      if (row.unlink && opts.ds && opts.editable !== false) {
        var u = button('pa-btn', 'Unlink', 'Unlink ' + row.address + ' from this person');
        u.addEventListener('click', function () { unlink(row); });
        side.appendChild(u);
      }
      li.appendChild(side);
      if (opts.extra) opts.extra(row, li);
      if (open === row.address) li.appendChild(choices(row));
      return li;
    }

    function draw() {
      ul.textContent = '';
      var rows = (data && data.rows) || [];
      if (!rows.length) { ul.appendChild(el('li', 'pa-empty', 'No email address yet.')); return; }
      rows.forEach(function (row) { ul.appendChild(rowNode(row)); });
    }

    draw();
    if (data && data.person && opts.fresh !== false) {
      call(base(), null).then(function (v) {
        if (busy) return;
        var was = JSON.stringify({ rows: data.rows, silos: data.silos });
        if (JSON.stringify({ rows: v.rows, silos: v.silos }) !== was) { data = v; draw(); }
      }).catch(function () { /* drawn with what it was given */ });
    }
    box.__redraw = function (d) { if (d) data = d; draw(); };
    return box;
  }

  window.RouhAddresses = { list: list };
})();
