/* Anatomy, Meta, What Rouh keeps and runs, at /anatomy/meta/keeps (`rouh/lean.py`, `rouh/web/lean.py`).

   Petar, 15 November 2026: "I think those options should have the defaults you have assigned. and I
   think those should be available to change through your own instance settings. so we provide default
   behavior. anyone can go in anatomy and change them to something else. days should include a keep
   forever behavior."

   One headline, the preset with its switcher, any removal that waits for a press, then the night jobs
   and the records, one row each: its name, a line on what it is, its choice, roughly the disk or money
   beside each option, and Back to default where the row is the person's own. Lowering a limit removes
   old rows, which cannot be undone, so it is never saved until the person has read what would go and
   pressed to remove it. Drawn into `#keepsBody` from `/api/anatomy/keeps`; Anatomy says when it shows
   and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  /* data: the last answer. ask: a change that waits for its press, {item | preset, mode, days, said, rows}.
     said: what the last change did, by item ('' for the page). error: what went wrong, by item. */
  var S = { open: false, data: null, seq: 0, busy: '', ask: null, said: {}, error: {}, fail: '' };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, label) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    b.disabled = !!S.busy;
    if (label) b.setAttribute('aria-label', label);
    b.addEventListener('click', act);
    return b;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  function call(method, url, body, about) {
    var seq = ++S.seq;
    if (method === 'POST') { S.busy = about || 'page'; S.fail = ''; delete S.error[about || '']; draw(); }
    var fetcher = window.RouhKeepsFetch || fetch;
    return fetcher(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                          body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = '';
          if (method === 'GET' && seq !== S.seq) return j;
          if (j && j.items) S.data = j;
          if (!r.ok) {
            var why = (j && j.error) || 'The server said ' + r.status + '.';
            if (about) S.error[about] = why; else S.fail = why;
          }
          draw();
          return { ok: r.ok, body: j || {} };
        });
      })
      .catch(function () {
        S.busy = '';
        var why = 'Rouh could not be reached. Check the connection and try again.';
        if (about) S.error[about] = why; else S.fail = why;
        draw();
        return { ok: false, body: {} };
      });
  }
  function load() { return call('GET', '/api/anatomy/keeps'); }

  /* ---- changing ---- */

  function choose(item, value) {
    var parts = value.split(':');
    var body = { item: item.id, mode: parts[0], days: parts[1] ? Number(parts[1]) : null };
    S.ask = null;
    send('/api/anatomy/keeps', body, item.id);
  }
  function send(url, body, about) {
    return call('POST', url, body, about).then(function (got) {
      if (!got || !got.ok) return;
      var j = got.body;
      if (j.needs_confirm) {
        if (j.would) {
          S.ask = { preset: j.preset, would: j.would || [] };
          delete S.said.preset;
        } else {
          S.ask = { item: j.item, url: url, body: body, mode: j.mode, days: j.days, said: (j.preview && j.preview.said) || '' };
          delete S.said[j.item];
        }
        draw();
        focusAsk();
        return;
      }
      if (j.saved) {
        S.ask = null;
        S.said[about] = j.held ? 'Saved. ' + j.held : j.swept ? 'Saved. The old rows are being removed now.' : 'Saved.';
        if (S.fromWaiting === about) {
          S.said.waiting = (nameOf(about) + ': ' + (j.swept ? 'saved, and its old rows are being removed now.' : 'saved.'));
          S.fromWaiting = '';
        }
        draw();
        setTimeout(function () { if (S.said[about]) { delete S.said[about]; draw(); } }, 4000);
        setTimeout(function () { if (S.said.waiting) { delete S.said.waiting; draw(); } }, 8000);
      }
    });
  }
  function nameOf(id) {
    var found = S.data && S.data.items.filter(function (it) { return it.id === id; })[0];
    return found ? found.name : '';
  }
  function confirmAsk() {
    var a = S.ask;
    if (!a) return;
    if (a.preset) {
      send('/api/anatomy/keeps/preset', { preset: a.preset, confirm: true }, 'preset');
    } else {
      var body = {}; for (var k in a.body) body[k] = a.body[k];
      body.confirm = true;
      send(a.url, body, a.item);
    }
  }
  function cancelAsk() {
    var a = S.ask;
    S.ask = null;
    draw();
    var back = a && document.querySelector(a.preset ? '#keepsBody .kp-preset-btn[aria-pressed="true"]'
                                                     : '#keepsBody [data-item="' + a.item + '"] select');
    if (back) back.focus();
  }
  function focusAsk() {
    var first = document.querySelector('#keepsBody .kp-ask .ctl.danger');
    if (first) { first.focus({ preventScroll: true }); first.scrollIntoView({ block: 'nearest' }); }
  }

  /* ---- drawing ---- */

  function headline(d) {
    var p = el('p', 'kp-headline');
    if (!d.preset) {
      p.textContent = 'Rouh cannot tell yet which kind of Rouh this is, so everything runs and is kept as before.';
      return p;
    }
    var on = 0, jobs = 0;
    d.items.forEach(function (it) { if (it.kind === 'job') { jobs++; if (runState(it) === 'on') on++; } });
    var bits = ['This Rouh is on the ' + d.preset_said + ' preset', on + ' of ' + jobs + ' jobs ' + (on === 1 ? 'runs' : 'run') + ' here'];
    bits.push(d.changed ? d.changed + (d.changed === 1 ? ' item is' : ' items are') + ' your own' : 'nothing changed by you');
    p.textContent = bits.join(', ') + '.';
    if (d.waiting) {
      var w = el('strong', 'kp-headline-wait', ' ' + d.waiting + (d.waiting === 1 ? ' removal waits' : ' removals wait') + ' for your press.');
      p.appendChild(w);
    }
    return p;
  }

  function presetCard(d) {
    var sec = el('section', 'hb-sec kp-presets');
    sec.setAttribute('aria-labelledby', 'kpPresetH');
    var h = el('h3', 'hb-h', 'Preset');
    h.id = 'kpPresetH';
    h.appendChild(el('span', 'hb-h-sub', 'The defaults every row follows until you change it'));
    sec.appendChild(h);
    var list = el('div', 'kp-preset-list');
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', 'Preset');
    d.presets.forEach(function (p) {
      var on = p.id === d.preset;
      var b = el('button', 'kp-preset-btn' + (on ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.disabled = !!S.busy || !d.preset;
      var name = el('span', 'kp-preset-name', p.name);
      if (on) name.appendChild(el('span', 'kp-tag now', 'now'));
      b.appendChild(name);
      b.appendChild(el('span', 'kp-preset-about', p.about));
      b.addEventListener('click', function () {
        if (on) return;
        S.ask = null;
        send('/api/anatomy/keeps/preset', { preset: p.id }, 'preset');
      });
      list.appendChild(b);
    });
    sec.appendChild(list);
    sec.appendChild(el('p', 'hb-note', 'Your own changes stay yours when the preset changes.'));
    if (S.ask && S.ask.preset) sec.appendChild(presetAsk(d));
    if (S.error.preset) sec.appendChild(el('p', 'kp-error', S.error.preset));
    if (S.said.preset) sec.appendChild(el('p', 'kp-said', S.said.preset));
    return sec;
  }

  function presetAsk(d) {
    var a = S.ask;
    var name = '';
    d.presets.forEach(function (p) { if (p.id === a.preset) name = p.name; });
    var box = el('div', 'kp-ask');
    box.setAttribute('role', 'alert');
    box.appendChild(el('p', 'kp-ask-say', 'Switching to ' + name + ' removes old records. This cannot be undone:'));
    var ul = el('ul', 'kp-ask-list');
    a.would.forEach(function (w) { ul.appendChild(el('li', '', w.name + ': ' + w.said)); });
    box.appendChild(ul);
    var acts = el('div', 'hb-actions');
    acts.appendChild(button('Switch and remove them', 'danger', confirmAsk));
    acts.appendChild(button('Cancel', '', cancelAsk));
    box.appendChild(acts);
    return box;
  }

  function waitingCard(d) {
    var rows = d.preset ? d.items.filter(function (it) { return it.waiting && !(S.ask && S.ask.item === it.id); }) : [];
    if (!rows.length) {
      if (!S.said.waiting) return null;
      var done = el('section', 'hb-sec kp-waiting');
      done.appendChild(el('p', 'kp-said', S.said.waiting));
      return done;
    }
    var sec = el('section', 'hb-sec kp-waiting');
    sec.setAttribute('aria-labelledby', 'kpWaitH');
    var h = el('h3', 'hb-h', 'Waiting for your press');
    h.id = 'kpWaitH';
    sec.appendChild(h);
    sec.appendChild(el('p', 'kp-wait-why', 'These limits are lower than what is kept now. Nothing old is removed until you press.'));
    rows.forEach(function (it) {
      var row = el('div', 'kp-wait-row');
      row.appendChild(el('p', 'kp-wait-name', it.name + ': ' + it.said));
      row.appendChild(el('p', 'kp-wait-what', it.waiting.said + ' This cannot be undone.'));
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Remove them', 'danger', function () {
        S.fromWaiting = it.id;
        send('/api/anatomy/keeps/confirm', { item: it.id }, it.id);
      }, 'Remove the old ' + it.name.toLowerCase()));
      if (it.changed) {
        acts.appendChild(button('Back to default', '', function () { S.fromWaiting = it.id; send('/api/anatomy/keeps/default', { item: it.id }, it.id); }));
      }
      // Copies cannot be kept forever: the alternative is to keep as many as there are (`lean._instead`).
      var instead = it.waiting.instead || { mode: 'forever', days: null, label: 'Keep forever instead' };
      var keep = instead.mode + (instead.days != null ? ':' + instead.days : '');
      acts.appendChild(button(instead.label, '', function () { S.fromWaiting = it.id; choose(it, keep); }));
      row.appendChild(acts);
      if (S.error[it.id]) row.appendChild(el('p', 'kp-error', S.error[it.id]));
      sec.appendChild(row);
    });
    return sec;
  }

  /* One meaning for "runs", shared by the headline and each job's mark: on, list (writes nothing but the
     list of genes), later (left to its own paused row until its test passes) or off. */
  function runState(it) {
    if (it.mode === 'list') return 'list';
    if (it.mode === 'later') return 'later';
    return it.runs ? 'on' : 'off';
  }
  var RUN_SAID = { on: 'Runs here', list: 'List only', later: 'Waits for its test', off: 'Off here' };
  function said(n) {
    return n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? Math.round(n / 1e6) + ' MB' : Math.round(n / 1e3) + ' KB';
  }
  function optionValue(o) { return o.mode + (o.days != null ? ':' + o.days : ''); }

  function rowOf(it, d) {
    var row = el('div', 'kp-row' + (it.changed ? ' changed' : ''));
    row.setAttribute('data-item', it.id);
    var top = el('div', 'kp-row-top');
    var name = el('label', 'kp-name', it.name);
    var id = 'kpSel-' + it.id;
    name.htmlFor = id;
    top.appendChild(name);
    if (it.kind === 'job') {
      var rs = runState(it);
      top.appendChild(el('span', 'kp-run ' + (rs === 'on' ? 'on' : 'off'), RUN_SAID[rs]));
    }
    if (it.waiting && d.preset) top.appendChild(el('span', 'kp-tag wait', 'removal waits, at the top'));
    if (it.changed) top.appendChild(el('span', 'kp-tag', 'changed'));
    row.appendChild(top);
    row.appendChild(el('p', 'kp-what', it.what));

    // While its removal is asked, the choice shows the value asked about, not the one still in force.
    var asked = S.ask && S.ask.item === it.id ? S.ask.mode + (S.ask.days != null ? ':' + S.ask.days : '') : '';
    var line = el('div', 'kp-choose');
    var sel = el('select', 'kp-select');
    sel.id = id;
    sel.disabled = !!S.busy || !d.preset;
    it.options.forEach(function (o) {
      var label = o.label + (o.preset ? ' (default)' : '') + (o.disk ? ', ' + o.disk : '');
      var on = asked ? optionValue(o) === asked : !!o.chosen;
      var opt = new Option(label, optionValue(o), on, on);
      sel.appendChild(opt);
    });
    sel.addEventListener('change', function () { choose(it, sel.value); });
    line.appendChild(sel);
    var facts = el('p', 'kp-facts');
    if (it.kind === 'job') {
      facts.textContent = it.money ? 'Money: ' + it.money : '';
    } else {
      var bits = [];
      if (it.size_said) bits.push('Uses ' + it.size_said + ' now');
      else if (it.shares) bits.push(it.shares);
      var chosen = it.options.filter(function (o) { return asked ? optionValue(o) === asked : o.chosen; })[0];
      if (chosen && chosen.disk && chosen.disk !== 'not measured' && chosen.disk !== 'small') {
        bits.push(chosen.disk.charAt(0) === '+' ? 'grows ' + chosen.disk.slice(1) : 'at this choice ' + chosen.disk);
      }
      facts.textContent = bits.join(', ') || 'Size not measured';
    }
    line.appendChild(facts);
    row.appendChild(line);

    var notes = [];
    if (it.mode === 'off' && it.off_means) notes.push(it.off_means);
    if (it.not_yet) notes.push(it.not_yet);
    if (it.note) notes.push(it.note);
    if (it.changed && it.by) notes.push('Set by ' + it.by + '. Default: ' + it.preset_said + '.');
    else if (it.changed) notes.push('Default: ' + it.preset_said + '.');
    notes.forEach(function (n) { row.appendChild(el('p', 'kp-note', n)); });

    if (S.ask && S.ask.item === it.id) {
      var box = el('div', 'kp-ask');
      box.setAttribute('role', 'alert');
      box.appendChild(el('p', 'kp-ask-say', S.ask.said + ' This cannot be undone.'));
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Remove them', 'danger', confirmAsk));
      acts.appendChild(button('Cancel', '', cancelAsk));
      box.appendChild(acts);
      row.appendChild(box);
    }
    if (it.changed && !(S.ask && S.ask.item === it.id)) {
      var back = el('div', 'hb-actions kp-back');
      var undo = button('Back to default', '', function () {
        S.ask = null;
        send('/api/anatomy/keeps/default', { item: it.id }, it.id);
      }, 'Back to default: ' + it.name);
      if (!d.preset) undo.disabled = true;
      back.appendChild(undo);
      row.appendChild(back);
    }
    if (S.busy === it.id) line.appendChild(el('p', 'kp-said', 'Saving...'));
    if (S.said[it.id]) line.appendChild(el('p', 'kp-said', S.said[it.id]));
    if (S.error[it.id]) row.appendChild(el('p', 'kp-error', S.error[it.id]));
    return row;
  }

  function group(title, sub, rows, d, id) {
    var sec = el('section', 'hb-sec kp-group');
    sec.setAttribute('aria-labelledby', id);
    var h = el('h3', 'hb-h', title);
    h.id = id;
    h.appendChild(el('span', 'hb-h-sub', sub));
    sec.appendChild(h);
    rows.forEach(function (it) { sec.appendChild(rowOf(it, d)); });
    return sec;
  }

  function draw() {
    var host = $('keepsBody');
    if (!host || !S.open) return;
    var keep = document.activeElement && host.contains(document.activeElement) ? document.activeElement.id : '';
    host.textContent = '';
    host.setAttribute('aria-busy', S.data ? 'false' : 'true');
    var page = el('div', 'hb-page kp-page');
    if (!S.data) {
      page.appendChild(el('p', 'hb-empty', S.fail || 'Reading what Rouh keeps and runs...'));
      if (S.fail) page.appendChild(button('Try again', '', load));
      host.appendChild(page);
      return;
    }
    var d = S.data;
    page.appendChild(headline(d));
    var jump = el('nav', 'kp-jump');
    jump.setAttribute('aria-label', 'Parts of this page');
    [['#kpJobsH', 'Night jobs'], ['#kpRecsH', 'Records and disk']].forEach(function (pair) {
      var a = el('a', 'kp-jump-a', pair[1]);
      a.href = pair[0];
      a.addEventListener('click', function (e) {
        e.preventDefault();
        var t = document.querySelector(pair[0]);
        if (t) { t.scrollIntoView({ block: 'start' }); t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); }
      });
      jump.appendChild(a);
    });
    page.appendChild(jump);
    if (S.fail) page.appendChild(el('p', 'kp-error', S.fail));
    var wait = waitingCard(d);
    if (wait) page.appendChild(wait);
    page.appendChild(presetCard(d));
    var jobs = d.items.filter(function (it) { return it.kind === 'job'; });
    var recs = d.items.filter(function (it) { return it.kind === 'record'; });
    page.appendChild(group('Night and background jobs', jobs.length + ' jobs and steps', jobs, d, 'kpJobsH'));
    var total = 0;
    recs.forEach(function (it) { total += it.size_bytes || 0; });
    page.appendChild(group('Records Rouh keeps', (total ? said(total) + ' now, besides the nightly copies. ' : '') + 'Growth as measured on the Creator Rouh.', recs, d, 'kpRecsH'));
    host.appendChild(page);
    if (keep && $(keep)) $(keep).focus({ preventScroll: true });
  }

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.ask = null;
    S.said = {};
    S.error = {};
    draw();
    load();
  }
  function hiddenNow() { S.open = false; S.ask = null; }

  window.RouhKeeps = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
