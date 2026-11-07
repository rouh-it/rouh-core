/* Labels: the one drawing of a filter label with its eye and its count, for the task browser
   (`taskbrowser.js`) and the Incubator (`incubatorpage.js`), styled once in `labels.css`.
   Petar, 3 November 2026: "make the filters and labels the same as in the task browser ... an eye
   icon, click it, and hide the stuff that may not be needed ... The numbers should be in the label".

   A label is `<span class="lab rl-lab" data-lab="KEY">`, with an eye `<button class="eye rl-eye"
   data-eye="KEY">` in front when it can be hidden, then the page's own button, which must carry the
   class `rl-chip` and a `<span class="c">` for its count, then anything the page puts at its end. What
   pressing the eye or the button does is the page's: each list knows what its labels mean. `paint`
   says on a label whether its eye is crossed. */
(function () {
  'use strict';

  var EYE_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 ' +
    '21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/><path class="slash" d="M4 20L20 4"/></svg>';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  /* One label as markup: `button` is the page's own button, already drawn; `o.eye` puts the eye in
     front, `o.style` goes on the label (its `--cc`), and `o.tail` after the button. */
  function html(key, button, o) {
    o = o || {};
    return '<span class="lab rl-lab" data-lab="' + esc(key) + '"' + (o.style ? ' style="' + esc(o.style) + '"' : '') + '>' +
      (o.eye ? '<button type="button" class="eye rl-eye" data-eye="' + esc(key) + '" aria-pressed="false">' +
        EYE_SVG + '</button>' : '') + button + (o.tail || '') + '</span>';
  }

  /* Its eye crossed or not. `o.off`: hidden; `o.name`: what the label is called; `o.what`: what it
     hides, "the tasks of" by default; `o.bright`: not dimmed although hidden, as while it is the
     filter pressed, which shows what it carries whatever its eye says. */
  function paint(lab, o) {
    var eye = lab.querySelector('.rl-eye');
    if (!eye) { return; }
    var what = o.what || 'the tasks of';
    eye.setAttribute('aria-pressed', String(!!o.off));
    eye.title = o.off ? 'Hidden: press to show ' + what + ' ' + o.name + ' again' : 'Press to hide ' + what + ' ' + o.name;
    eye.setAttribute('aria-label', (o.off ? 'Show ' : 'Hide ') + o.name);
    lab.classList.toggle('hid', !!o.off && !o.bright);
  }

  window.RouhLabels = { EYE_SVG: EYE_SVG, html: html, paint: paint };
}());
