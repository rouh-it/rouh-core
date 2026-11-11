/* Rouh's page, the cog wheel of the open orb, and the panel behind it
 * (out of app/orb.js).
 *
 * Nothing here runs when the module is loaded: app/orb.js calls wireOrbPanel()
 * at the place in it where this code used to be, so everything happens in
 * the order it always did.
 */
import { shared } from 'app/shared.js';
import { $, el } from 'app/helpers.js';
import { ORB_BASE, ORB_CFG, ORB_GROUPS, ORB_ROWS, orbMoved, orbSane, orbSaveNow, orbSaveSoon,
  orbTipHide, ORBX, slowMo } from 'app/orb.js';
import { orbSoundPreview } from 'app/orb_sound.js';
import { orbUsageShow } from 'app/orb_costs.js';
import { O3, orb3dDump, orb3dPanelPaint, orb3dPutBackAll } from 'app/orb3d.js';

/* ---------- the cog wheel, and the panel behind it ----------------------
 *
 * The cog is in the corner of the orb opened over the whole screen, beside
 * the button that puts it back, and nowhere else: the only other place the
 * orb is ever in is the 96 px circle in the corner, which is one button with
 * no room for a second.
 *
 * The panel is a column down the right of the open orb. Every slider writes
 * the live settings object the drawing loop reads, so the shape changes
 * under the thumb; nothing is saved until the dragging stops, and nothing is
 * rebuilt at all. A setting that has been moved off the approved design
 * grows a control that puts it back, and so does its group.
 */

function orbPanelOpen() {
  var p = $('orbPanel');
  return !!p && !p.hidden;
}

// The value as the panel writes it: whole numbers plain, everything else to
// two places with a trailing zero dropped, then the design's unit.
function orbValWords(v, unit) {
  var s = v === Math.round(v) ? String(v) : v.toFixed(2).replace(/0$/, '');
  return unit ? s + ' ' + unit : s;
}

// One setting moved. The live object first, so the picture is already
// different by the time anything else happens.
function orbSetting(key, v) {
  v = orbSane(key, v);
  if (v === null || ORB_CFG[key] === v) return;
  ORB_CFG[key] = v;
  orbSaveSoon();
  orbPanelMark(key);
  // The picture changes under the slider; the sound has to be heard.
  if (key === 'noteVol') orbSoundPreview();
}

// Put a setting, a whole group, or everything, back to the approved design.
function orbPutBack(keys) {
  var i, moved = false;
  for (i = 0; i < keys.length; i++) {
    if (ORB_CFG[keys[i]] === ORB_BASE[keys[i]]) continue;
    ORB_CFG[keys[i]] = ORB_BASE[keys[i]];
    moved = true;
  }
  if (!moved) return;
  orbSaveNow();
  orbPanelPaint();
}

/* One row's own numbers, without repainting the panel. Dragging a slider
   must not rebuild the column under the pointer: the browser would lose the
   element the drag belongs to and the thumb would stop following the mouse
   halfway along. So a drag writes only the value it changed and the two
   controls whose presence depends on it. */
function orbPanelMark(key) {
  var row = document.querySelector('#orbPanel [data-orb-row="' + key + '"]');
  if (!row) return;
  var spec = ORB_ROWS[key];
  var out = row.querySelector('.v'), back = /** @type {HTMLElement} */ (row.querySelector('.orb-back'));
  var input = row.querySelector('input');
  if (out) out.textContent = orbValWords(ORB_CFG[key], spec[5]);
  if (input && parseFloat(input.value) !== ORB_CFG[key]) input.value = ORB_CFG[key];
  if (back) back.hidden = !orbMoved(key);
  row.classList.toggle('moved', orbMoved(key));
  var group = row.closest('[data-orb-group]');
  if (group) {
    var any = !!group.querySelector('.row.moved');
    var gback = /** @type {HTMLElement} */ (group.querySelector('.orb-back-group'));
    if (gback) gback.hidden = !any;
  }
  orbPanelFoot();
}

// What the foot says: whether anything at all is off the design.
function orbPanelFoot() {
  var all = $('orbResetAll'), k, n = 0;
  if (!all || O3.on) return;
  for (k in ORB_BASE) if (orbMoved(k)) n++;
  all.hidden = !n;
  all.lastChild.textContent = n === 1 ? '1 changed' : n + ' changed';
}

function orbPanelPaint() {
  var host = $('orbPanelGroups');
  if (!host) return;
  // The 3D orb has 178-02's own controls, which it builds itself.
  if (O3.on) {
    orb3dPanelPaint(host);
    var note3 = $('orbPanelNote');
    if (note3) {
      note3.textContent = 'This machine asks for less movement, so finished work fades steadily ' +
        'without flashing, waiting work does not breathe, and the orb does not turn by itself.';
      note3.hidden = !slowMo;
    }
    return;
  }
  host.innerHTML = '';
  for (var g = 0; g < ORB_GROUPS.length; g++) {
    var title = /** @type {string} */ (ORB_GROUPS[g][0]);
    var rows = /** @type {Array<Array<string | number>>} */ (ORB_GROUPS[g][1]);
    var keys = rows.map(function (r) { return r[0]; });
    var box = el('div', 'orb-grp');
    box.setAttribute('data-orb-group', title);
    var head = el('div', 'orb-grp-head');
    head.appendChild(el('span', null, title.toUpperCase()));
    var gback = el('button', 'orb-back-group', 'put back');
    gback.type = 'button';
    gback.hidden = !rows.some(function (r) { return orbMoved(r[0]); });
    gback.title = 'Put every setting in this group back to the approved design';
    gback.addEventListener('click', (function (ks) {
      return function () { orbPutBack(ks); };
    })(keys));
    head.appendChild(gback);
    box.appendChild(head);
    for (var i = 0; i < rows.length; i++) box.appendChild(orbPanelRow(rows[i]));
    host.appendChild(box);
  }
  // The two sliders a machine asking for less movement does nothing with.
  var note = $('orbPanelNote');
  if (note) note.hidden = !slowMo;
  orbPanelFoot();
}

function orbPanelRow(spec) {
  var key = spec[0];
  var row = el('div', 'row');
  row.setAttribute('data-orb-row', key);
  row.classList.toggle('moved', orbMoved(key));
  var head = el('div', 'rowHead');
  var name = el('label', null, spec[1]);
  name.setAttribute('for', 'orbS-' + key);
  head.appendChild(name);
  var back = el('button', 'orb-back', '↺');
  back.type = 'button';
  back.hidden = !orbMoved(key);
  back.title = 'Put "' + spec[1] + '" back to ' + orbValWords(ORB_BASE[key], spec[5]);
  back.setAttribute('aria-label', back.title);
  head.appendChild(back);
  back.addEventListener('click', function () { orbPutBack([key]); });
  head.appendChild(el('span', 'v', orbValWords(ORB_CFG[key], spec[5])));
  row.appendChild(head);
  var input = document.createElement('input');
  input.type = 'range';
  input.id = 'orbS-' + key;
  input.min = spec[2];
  input.max = spec[3];
  input.step = spec[4];
  input.value = ORB_CFG[key];
  input.addEventListener('input', function () { orbSetting(key, parseFloat(input.value)); });
  // A slider left with the keyboard or the mouse has stopped moving.
  input.addEventListener('change', orbSaveNow);
  row.appendChild(input);
  return row;
}

function orbPanelShow(on) {
  var panel = $('orbPanel'), cog = $('orbCog');
  if (!panel || !cog) return;
  on = !!on && ORBX.state === 'open';
  if (on === !panel.hidden) return;
  if (on) orbUsageShow(false);
  if (on) orbPanelPaint();
  panel.hidden = !on;
  cog.setAttribute('aria-expanded', on ? 'true' : 'false');
  cog.classList.toggle('on', on);
  // The cog and the button that puts the orb back stand clear of the column
  // rather than on top of it, and the canvas gives up its width, so the
  // picture is re-measured on the next frame rather than up to a quarter of
  // a second later.
  $('orbBox').classList.toggle('with-panel', on);
  shared.orbSizedAt = -1e9;
  // Leaving it, the last thing written goes to the store at once rather than
  // waiting on a timer nobody is watching any more.
  if (!on) orbSaveNow();
  orbTipHide();
  if (on) {
    var first = panel.querySelector('input');
    if (first) first.focus();
  } else if (panel.contains(document.activeElement)) {
    cog.focus();
  }
}

// Wired from app/orb.js, at the place in it where this code always ran.
function wireOrbPanel() {
  var cog = $('orbCog'), panel = $('orbPanel');
  if (!cog || !panel) return;
  cog.addEventListener('click', function () { orbPanelShow(panel.hidden); });
  var close = $('orbPanelClose');
  if (close) close.addEventListener('click', function () { orbPanelShow(false); });
  var all = $('orbResetAll');
  if (all) {
    all.addEventListener('click', function () {
      if (O3.on) { orb3dPutBackAll($('orbPanelGroups')); return; }
      orbPutBack(Object.keys(ORB_BASE));
    });
  }
  // What the settings are now, as the text that would be pasted into the
  // code to make them the design: the way a look tuned here becomes the look
  // everybody gets.
  var dump = $('orbDump');
  if (dump) {
    dump.addEventListener('click', function () {
      var box = $('orbDumpBox'), out = {}, k;
      for (k in ORB_BASE) out[k] = ORB_CFG[k];
      box.textContent = O3.on ? orb3dDump() : JSON.stringify(out, null, 1);
      box.hidden = !box.hidden;
      dump.classList.toggle('on', !box.hidden);
      // Opened from the foot of a column that is taller than the screen, the
      // text appeared below the fold and looked like nothing had happened.
      if (!box.hidden && box.scrollIntoView) box.scrollIntoView({ block: 'end' });
    });
  }
}

export { orbPanelOpen, orbPanelPaint, orbPanelShow, wireOrbPanel };
