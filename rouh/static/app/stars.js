/* Rouh's page, a falling star across the navigation now and then.
 *
 * Petar, 9 October 2026 (fr_dc043452954a): "I would like to have my
 * navigation falling stars from time to time for luck". So now and then a
 * small star streaks across the sidebar with a tail behind it and is gone.
 *
 * And the same day, once he had seen the first ones: "make the shooting star
 * go in various directions and various positioning ... I would like it to be
 * unpredictable ... don't repeat at a set interval, rather have randomized
 * time ... stars should be with various speed. like in real life." So no two
 * are alike. Each crosses some point anywhere in the column, in any
 * direction, for its own distance, at its own speed, from a quick faint
 * streak half a second long to a slow bright one that takes nearly three.
 * A fast star has a longer tail.
 *
 * Petar, 9 October 2026, once they had been falling for a while: "the
 * falling star happens way too often. should be a random time between 1 and
 * 24h". So a star is a rare thing now: one, and then the next one any time
 * from an hour to a day later, never two close together. When it is due is
 * kept in the browser (`rouh.nextStarAt` in localStorage), so reloading the
 * page or opening another tab does not start the wait again, and every tab
 * waits for the same moment. The first tab that shows it picks the next one,
 * so the others do not show it too. A star that came due while no tab was
 * open, or while the page was hidden or the sidebar folded, is shown the next
 * time the sidebar is in sight, and the wait for the one after starts then.
 *
 * It is a picture and nothing else. The sky it crosses is a layer of its own
 * over the column (`.sb-sky` in app.css): hidden from a screen reader, never
 * focusable, out of the layout, and every press goes straight through it to
 * the link under it. A person whose system asks for less motion never sees
 * one, and neither does a folded sidebar or a tab nobody is looking at.
 *
 * `?stars=often` in the address waits a couple of seconds on average instead,
 * the way the wait between meteors in a real sky goes (any length, and now
 * and then a second one moments after the first), so the stars can be
 * watched while they are being worked on. It keeps its own time in the page
 * and never reads or writes the stored one.
 *
 * It imports nothing and nothing imports it but app.js: it only needs the
 * page to be there, which it is by the time a module runs.
 */

/* ------------------------------------------------------------- stars */

var STARS_OFTEN = /(?:^|[?&])stars=often(?:&|$)/.test(location.search);
// With ?stars=often, the wait between two stars, in seconds: its average,
// the shortest and the longest it may be; and how often the next one comes
// almost at once, and how soon that is.
var STARS_WAIT = { mean: 2.5, least: 0.4, most: 8, soon: [0.3, 1.5] };
var STARS_SOON = 0.12;
// Otherwise, where the moment the next star is due is kept, shared by every
// tab, and the shortest and longest wait for it, in milliseconds.
var STARS_KEY = 'rouh.nextStarAt';
var STARS_HOUR = 60 * 60 * 1000;
var STARS_LEAST = STARS_HOUR, STARS_MOST = 24 * STARS_HOUR;
var starsCalm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

function starsRand(lo, hi) { return lo + Math.random() * (hi - lo); }

// With ?stars=often, how long until the next star, in milliseconds. Meteors
// arrive the way anything independent and rare does: the time to the next
// one is drawn from an exponential, so how long it has been says nothing
// about how long it will be. Sometimes one follows another within a few
// seconds, as they do in a shower.
function starsWait() {
  var w = STARS_WAIT;
  if (Math.random() < STARS_SOON) return starsRand(w.soon[0], w.soon[1]) * 1000;
  // The shortest wait plus the exponential, rather than the exponential held
  // up to the shortest, which would pile every short wait on one number.
  var t = w.least - Math.log(1 - Math.random()) * (w.mean - w.least);
  return Math.min(w.most, t) * 1000;
}

function starsSky() {
  var nav = document.getElementById('tasksPanel');
  if (!nav) return null;
  var sky = nav.querySelector(':scope > .sb-sky');
  if (sky) return sky;
  sky = document.createElement('div');
  sky.className = 'sb-sky';
  sky.setAttribute('aria-hidden', 'true');
  // First in the column, so the panels the column opens over itself (the
  // version details) are drawn over a star rather than under one.
  nav.insertBefore(sky, nav.firstChild);
  return sky;
}

// Whether a star now would be seen, and wanted.
function starsWanted(sky) {
  if (starsCalm && starsCalm.matches) return false;
  if (document.hidden) return false;
  var app = document.getElementById('app');
  if (app && app.getAttribute('data-sb') === 'shut') return false;
  return sky.clientWidth > 80 && sky.clientHeight > 120;
}

// One star, its own in every way: where it crosses the column, which way it
// goes, how far, how fast, and how bright.
function starFall(sky) {
  var w = sky.clientWidth, h = sky.clientHeight;
  var star = document.createElement('span');
  star.className = 'sb-star';
  // Any direction at all, in degrees from pointing right, screen y down.
  var way = Math.random() * 360;
  var rad = way * Math.PI / 180;
  var dx = Math.cos(rad), dy = Math.sin(rad);
  // A point anywhere in the column that it passes through around the middle
  // of its way, while it is at its brightest: so it may come in from out of
  // sight, or go out of sight, or come and go inside the column, and is seen
  // whichever it does.
  var px = w * starsRand(0.08, 0.92), py = h * starsRand(0.04, 0.96);
  var far = 120 + Math.pow(Math.random(), 1.4) * (Math.min(Math.hypot(w, h), 560) - 120);
  var before = far * starsRand(0.25, 0.75);
  var x0 = px - dx * before, y0 = py - dy * before;
  var x1 = x0 + dx * far, y1 = y0 + dy * far;
  // Speed, spread evenly over its logarithm, as meteors' are: most are quick,
  // a few crawl. The faster it is, the longer the tail it pulls.
  var speed = Math.exp(starsRand(Math.log(140), Math.log(900)));
  var ms = Math.min(2800, Math.max(500, far / speed * 1000));
  var bright = Math.random() < 0.15, faint = !bright && Math.random() < 0.3;
  var tail = Math.round((30 + speed * 0.12) * (bright ? 1.3 : faint ? 0.7 : 1));
  var peak = bright ? 1 : faint ? 0.5 : starsRand(0.75, 0.95);
  if (bright) star.classList.add('sb-star-bright');
  // The tail is drawn pointing right from the head, so it is turned to point
  // back the way the star came.
  var turn = ' rotate(' + (way - 180) + 'deg)';
  sky.appendChild(star);
  var gone = function () { star.remove(); };
  if (!star.animate) { setTimeout(gone, ms); return; }
  var lit = starsRand(0.12, 0.4);
  var run = star.animate([
    { transform: 'translate(' + x0 + 'px,' + y0 + 'px)' + turn, width: '2px', opacity: 0 },
    { opacity: peak, width: tail * 0.6 + 'px', offset: lit },
    { opacity: peak * starsRand(0.7, 1), offset: starsRand(Math.max(lit + 0.1, 0.55), 0.85) },
    { transform: 'translate(' + x1 + 'px,' + y1 + 'px)' + turn, width: tail + 'px', opacity: 0 },
  ], { duration: ms, easing: 'cubic-bezier(0.3, 0.05, 0.6, 1)', fill: 'forwards' });
  run.onfinish = gone;
  run.oncancel = gone;
}

function starsNext() {
  setTimeout(function () {
    var sky = starsSky();
    if (sky && starsWanted(sky)) starFall(sky);
    starsNext();
  }, starsWait());
}

// The moment the next star is due, as the browser keeps it. Where storage is
// refused (a private window, site data blocked) it is kept in the page
// instead, which is the best that can be done there.
var starsHeld = 0;

function starsDueRead() {
  var v = starsHeld;
  try { v = Number(localStorage.getItem(STARS_KEY)); } catch (e) { /* kept in the page */ }
  // Nothing, nonsense, or further off than the longest wait (a clock that was
  // set back, a hand-edited value): as good as nothing.
  if (!isFinite(v) || v <= 0 || v > Date.now() + STARS_MOST + 60000) return 0;
  return v;
}

// Picks the next star's moment, an hour to a day from now, and keeps it.
function starsDueNew() {
  var due = Math.round(Date.now() + starsRand(STARS_LEAST, STARS_MOST));
  starsHeld = due;
  try { localStorage.setItem(STARS_KEY, String(due)); } catch (e) { /* kept in the page */ }
  return due;
}

// Takes the star that is due, for this tab alone: true if this tab is to show
// it, having already picked the next one, and false if another tab got there
// first. Behind a lock where the browser has one, so two tabs in sight at the
// same moment cannot both take it.
function starsTake(then) {
  var take = function () {
    var due = starsDueRead();
    if (due && due > Date.now()) return false;
    starsDueNew();
    return true;
  };
  if (navigator.locks && navigator.locks.request) {
    navigator.locks.request(STARS_KEY, take).then(then, function () { then(take()); });
  } else {
    then(take());
  }
}

var starsTimer = 0;

// Looks at when the next star is due and waits for it. Run when the page
// starts, when its timer goes off, and whenever the page comes back into
// sight.
function starsCheck() {
  clearTimeout(starsTimer);
  var due = starsDueRead() || starsDueNew();
  var left = due - Date.now();
  if (left > 0) {
    // At most a day, well inside what a timer can hold, and read again when
    // it goes off, since another tab may have moved it on meanwhile.
    starsTimer = setTimeout(starsCheck, Math.min(left, STARS_MOST) + starsRand(0, 2000));
    return;
  }
  var sky = starsSky();
  if (!sky || !starsWanted(sky)) {
    // Due, and nobody to see it: a hidden page is woken by visibilitychange,
    // and a folded or squeezed sidebar is looked at again now and then.
    if (!document.hidden) starsTimer = setTimeout(starsCheck, 20000);
    return;
  }
  starsTake(function (mine) {
    if (mine && starsWanted(sky)) starFall(sky);
    starsCheck();
  });
}

if (STARS_OFTEN) {
  starsNext();
} else {
  // A moment after the page is up or back in sight, rather than in the same
  // instant, so a star that has been waiting is seen to fall.
  var starsSoon = function () {
    clearTimeout(starsTimer);
    if (!document.hidden) starsTimer = setTimeout(starsCheck, starsRand(2000, 5000));
  };
  document.addEventListener('visibilitychange', starsSoon);
  starsSoon();
}

export {};
