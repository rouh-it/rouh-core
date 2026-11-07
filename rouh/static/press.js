/* A button tapped while a field is typed in is pressed on that one tap.

   Rouh's own page loads this, and Rouh puts it into every page it frames on
   the canvas (`pages.frame_script`): a task's or a step's page, the task
   browser, a project's page and every page a job built, with its Ask AI
   drawer and its comments. Each has text boxes with a button beside them.

   Petar, 4 October 2026, on an iPad with the floating keyboard, on the
   Synapse chat (fr_43689e0df2c9): "while my keyboard of the iPad is
   floating, I type and then I try to press buttons to submit stuff and I
   can not for some reason. I have to tap out of the input so keyboard
   disappears and then I can press on buttons". And again on 12 October 2026,
   in the Gene therapy drawer (fr_f180995a3a50), whose Mutate button was the
   one on the screen this did not reach: it sat at the foot of a sheet that
   did not shrink with the keyboard (app.css, under "Gene therapy").

   A tap reaches a button as touchstart and touchend, and then Safari decides
   whether to make a click of it - after a pause, after a hover it may count
   as the whole of the tap, and with a keyboard over part of the window it
   may not make one at all. Whatever it decided, the person's finger went
   down and came up on the button, which is all a press is. So while one of
   this page's own fields has the focus, and so may have a keyboard, a tap
   that starts and ends on the same button without moving is that button
   pressed, there and then, and the click Safari would have made of it is
   cancelled so nothing is pressed twice. The field keeps the focus, so the
   keyboard stays for the next thing typed, the way it does when Send is
   tapped with the keyboard docked.

   Two more ways the tap was lost, each answered here:

   - The page moved under the finger. A keyboard settling, or the screen
     being measured again, can slide the button between the finger going
     down and coming up. The button is the one the finger went down on, and
     where it was then counts as much as where it is now.
   - Something nobody can see was over it: a sheet fading out, still taking
     touches at no opacity. A finger that lands on something invisible goes
     to the button underneath it.

   Only a finger, only while a field is being typed in, and only buttons and
   the things that act like them, which includes a link Rouh opens in place:
   a scroll, a drag, a long press, any other link and everything at any other
   time are the browser's as they always were. */
(function () {
  'use strict';
  if (window.__rouhPress) return;
  window.__rouhPress = true;

  // A link Rouh opens in place (`linkTo`) is pressed like the button it was.
  var PRESSABLE = 'button, [role="button"], a[data-inapp], summary, input[type="button"],' +
    ' input[type="submit"], input[type="reset"], input[type="checkbox"], input[type="radio"]';
  // A finger on glass wanders: 16 pixels is still a tap, and so is a press
  // held for a second and a half, which is how a tap is made when the last
  // one did nothing.
  var MOVE = 16, LONG = 1500;
  var down = null, handled = null;

  // Whether a field of this page's own has the focus, which is the only time
  // an on-screen keyboard can be standing in for part of the window.
  // Into a shadow root as well: a page's comments draw in one, and from out
  // here the focus is on its host and a tap lands on the host.
  function typingHere() {
    var el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
    if (!el || el === document.body) return false;
    var tag = el.tagName;
    if (tag === 'INPUT') return !/^(button|checkbox|color|file|hidden|image|radio|range|reset|submit)$/i.test(el.type);
    return tag === 'TEXTAREA' || tag === 'SELECT' || !!el.isContentEditable;
  }

  function targetOf(e) {
    var path = e.composedPath ? e.composedPath() : null;
    var t = path && path.length ? path[0] : e.target;
    return t && t.nodeType === 3 ? t.parentElement : t;
  }

  function pressable(t) {
    var b = t && t.closest ? t.closest(PRESSABLE) : null;
    if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true') return null;
    if (b.closest('fieldset[disabled]')) return null;
    return b;
  }

  // Drawn at no opacity, by itself or by anything it sits in.
  function unseen(el) {
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (parseFloat(getComputedStyle(n).opacity) < 0.02) return true;
    }
    return false;
  }

  // The button under the finger: the one it landed on, or one under
  // something invisible it landed on. Never one under anything that can be
  // seen, which is the thing the person meant to tap.
  function under(e, p) {
    var b = pressable(targetOf(e));
    if (b || !document.elementsFromPoint) return b;
    var stack = document.elementsFromPoint(p.clientX, p.clientY);
    for (var i = 0; i < stack.length; i++) {
      var el = stack[i];
      if (el === document.documentElement || el === document.body) return null;
      b = pressable(el);
      if (b) return unseen(b) ? null : b;
      if (!unseen(el)) return null;
    }
    return null;
  }

  /* Each finger on its own. A tablet is held, and a thumb resting on the
     glass while the other hand types on a floating keyboard is a second touch
     the whole time: counting every touch on the screen, as this did until 13
     October 2026, let every tap go back to Safari, which makes no click of a
     tap with another finger down either. Only the finger that went down on
     the button is followed, by its own identifier, and any other is left
     alone. */
  function find(list, id) {
    for (var i = 0; list && i < list.length; i++) if (list[i].identifier === id) return list[i];
    return null;
  }

  document.addEventListener('touchstart', function (e) {
    // Another finger coming down while one is on a button changes nothing.
    if (down && find(e.touches, down.id)) return;
    down = null;
    var p = e.changedTouches[0];
    if (!p || !typingHere()) return;
    var b = under(e, p);
    if (!b) {
      landed(targetOf(e), p, e.touches.length);
      return;
    }
    down = { b: b, id: p.identifier, x: p.clientX, y: p.clientY, at: Date.now(), n: e.touches.length };
  }, { capture: true, passive: true });

  document.addEventListener('touchmove', function (e) {
    if (!down) return;
    var p = find(e.changedTouches, down.id);
    if (p && (Math.abs(p.clientX - down.x) > MOVE || Math.abs(p.clientY - down.y) > MOVE)) {
      missed(down, 'moved', p);
      down = null;
    }
  }, { capture: true, passive: true });

  document.addEventListener('touchcancel', function (e) {
    if (down && find(e.changedTouches, down.id)) { missed(down, 'cancelled', null); down = null; }
  }, { capture: true, passive: true });

  document.addEventListener('touchend', function (e) {
    var d = down;
    if (!d) return;
    var p = find(e.changedTouches, d.id);
    if (!p) return;
    down = null;
    if (!typingHere()) return missed(d, 'not typing', p);
    if (Date.now() - d.at > LONG) return missed(d, 'long', p);
    if (Math.abs(p.clientX - d.x) > MOVE || Math.abs(p.clientY - d.y) > MOVE) return missed(d, 'moved', p);
    // Still a button that can be pressed: the page may have changed under it
    // while it was held. Where it is now is not asked: the finger went down on
    // it and came up where it went down, and a button the page slid away in
    // between is still the one that was tapped.
    if (!d.b.isConnected || pressable(d.b) !== d.b) return missed(d, 'gone', p);
    // No click from the browser, which would go to whatever is on top, and no
    // mousedown taking the focus away.
    if (e.cancelable) e.preventDefault();
    handled = { b: d.b, at: Date.now() };
    note(d.b, 'pressed', p, d);
    d.b.click();
  }, { capture: true, passive: false });

  /* ---------- what happened to a tap made while typing, in the event log

     So that a tap that is still lost says where it went rather than leaving
     only a person saying it did nothing (`ui.tap` in rouh/events.py). Numbers
     and the names of controls only, the way every other event is: never what
     is in a field. Rouh's own page only, which is where the log is kept.

     - A tap on a button while typing that was not turned into a press, and
       why: it moved, it was held, the field had gone, the button had gone.
     - A tap while typing that landed on no button at all, when there was one
       within a finger's width of it: the clue to a page drawn in one place
       and touched in another.
     - A button pressed by the browser within a few seconds of the keyboard
       going away, with the taps made while typing just before it. That is
       the person's way round a tap that did nothing, and those taps - or
       their absence, which means Safari kept them - are what it was. */
  var RECENT = [], blurAt = 0, NEAR = 48;

  function keyOf(el) {
    if (!el || el.nodeType !== 1) return '';
    var cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/)[0] : '';
    return String(el.id || el.tagName.toLowerCase() + (cls ? '.' + cls : '')).slice(0, 80);
  }

  function screen() {
    var vv = window.visualViewport, r = document.body ? document.body.getBoundingClientRect() : null;
    return {
      vvh: vv ? Math.round(vv.height) : null, vvtop: vv ? Math.round(vv.offsetTop) : null,
      scale: vv ? Math.round(vv.scale * 100) / 100 : null,
      ih: window.innerHeight, ch: document.documentElement.clientHeight,
      top: r ? Math.round(r.top) : null
    };
  }

  function emit(el, props) {
    var log = window.RouhTrack;
    if (!log || window.parent !== window) return;
    var s = screen();
    for (var k in s) props[k] = s[k];
    log.event('ui.tap', { object_type: 'control', object_id: keyOf(el), props: props });
  }

  function remember(what) {
    what.at = Date.now();
    RECENT.push(what);
    if (RECENT.length > 6) RECENT.shift();
  }

  function note(b, why, p, d) {
    remember({ t: keyOf(b), why: why, x: Math.round(p.clientX), y: Math.round(p.clientY),
               ms: Date.now() - d.at, n: d.n });
  }

  function missed(d, why, p) {
    var at = p || { clientX: d.x, clientY: d.y };
    note(d.b, why, at, d);
    emit(d.b, { why: why, x: Math.round(at.clientX), y: Math.round(at.clientY), ms: Date.now() - d.at,
                moved: Math.round(Math.max(Math.abs(at.clientX - d.x), Math.abs(at.clientY - d.y))),
                fingers: d.n });
  }

  // Landed on no button. Said only when one was close, and never for a tap
  // into a text box, which is how a caret is moved.
  function landed(t, p, n) {
    if (!t || !t.closest || t.closest('textarea, input, select, [contenteditable]')) return;
    var best = null, dist = NEAR + 1;
    var all = document.querySelectorAll(PRESSABLE);
    for (var i = 0; i < all.length; i++) {
      var r = all[i].getBoundingClientRect();
      if (!r.width || !r.height) continue;
      var dx = Math.max(r.left - p.clientX, 0, p.clientX - r.right);
      var dy = Math.max(r.top - p.clientY, 0, p.clientY - r.bottom);
      var gap = Math.max(dx, dy);
      if (gap < dist) { dist = gap; best = all[i]; }
    }
    remember({ t: keyOf(t), why: 'no button', near: best ? keyOf(best) : '', x: Math.round(p.clientX),
               y: Math.round(p.clientY), n: n });
    if (best) emit(best, { why: 'no button', landed: keyOf(t), gap: Math.round(dist),
                           x: Math.round(p.clientX), y: Math.round(p.clientY), fingers: n });
  }

  document.addEventListener('focusout', function (e) {
    var t = e.target;
    if (t && /^(TEXTAREA|INPUT)$/.test(t.tagName || '')) blurAt = Date.now();
  }, true);

  // Pressed by the browser soon after the keyboard went. Bubbling, so a click
  // this page swallowed is not counted.
  document.addEventListener('click', function (e) {
    if (!e.isTrusted || !blurAt || Date.now() - blurAt > 3000 || typingHere()) return;
    var b = pressable(targetOf(e));
    if (!b) return;
    var since = Date.now() - blurAt;
    blurAt = 0;
    var now = Date.now();
    // One line each, as the log keeps a list of plain values: what was touched,
    // what became of it, where, for how long, with how many fingers, how long ago.
    var before = RECENT.filter(function (r) { return now - r.at < 20000; }).map(function (r) {
      return r.t + ' ' + r.why + (r.near ? ' near ' + r.near : '') + ' at ' + r.x + ',' + r.y +
        (r.ms != null ? ' ' + r.ms + 'ms' : '') + ' fingers ' + r.n + ' ' + (now - r.at) + 'ms ago';
    });
    emit(b, { why: 'after keyboard', since_blur: since, taps_while_typing: before });
  }, false);

  // A browser that makes its click anyway gets it swallowed, once.
  document.addEventListener('click', function (e) {
    var h = handled;
    if (!h || !e.isTrusted) return;
    handled = null;
    // On the button, or on the invisible thing that was over it.
    if (Date.now() - h.at > 800 || !(h.b.contains(targetOf(e)) || unseen(targetOf(e)))) return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);
}());
