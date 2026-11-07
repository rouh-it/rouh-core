/* The daily doodle, the last section of the morning brief (fr_ddbb892590f8).

   Petar, 30 September 2026: "Add also at the end of morning brief. Daily
   doodle drawn from your schedule".

   So it is a small sketch of today, drawn from what the brief already holds
   and nothing else: today's calendar events, each a little hand-drawn picture
   standing on a wandering path from morning to evening at roughly its time
   (a coffee cup for a coffee, two speech bubbles for a meeting, a plane for a
   flight, a star for anything it cannot place), with its name scribbled
   underneath; the day's all-day events as bunting across the top; and the
   day's weather in the corner. A day with nothing on it gets a hammock
   between two trees, because a free day is not an error.

   Today's reminders are on the path too, each a little bell at its time
   with its words under it, and today's birthdays fly in the bunting, as
   Petar asked on 3 October 2026 (fr_3c7faab7e0ce): "include reminders as a
   section in the morning routine and in the doodle? ... Doodle only today
   obviously". Yesterday's and tomorrow's are in the brief's sections only.

   Every wobble comes from a generator seeded with the day and its events, so
   opening the same brief again, or the page redrawing it each minute, gives
   the same doodle, and the next day's brief gets a new one. Nothing is asked
   of the server and nothing is kept: it is drawn here, from the kept brief.
   It is visual only; the phone's lines and anything spoken leave it out.

   `RouhDoodle.draw(brief)` hands back the drawing, or null when there is
   nothing to draw it from (the calendar could not be read and there are no
   reminders or birthdays today), and the brief leaves the section out rather
   than guess. */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var W = 520, H = 196;
  var PATH_Y = 128, ICON_Y = 94;
  var MOST = 5;

  // A small seeded generator (mulberry32), so a day's doodle is always the same.
  function seeded(words) {
    var h = 1779033703 ^ words.length;
    for (var i = 0; i < words.length; i++) {
      h = Math.imul(h ^ words.charCodeAt(i), 3432918353);
      h = (h << 13) | (h >>> 19);
    }
    var a = h >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function node(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }
  function f(n) { return Math.round(n * 10) / 10; }

  /* ------------------------------------------------ the hand-drawn pen */

  function Pen(rand) {
    this.rand = rand;
  }
  Pen.prototype.j = function (amount) { return (this.rand() - 0.5) * 2 * amount; };

  // A line drawn twice, each time a little off, the way a pen goes over it.
  Pen.prototype.line = function (g, x1, y1, x2, y2, cls) {
    var d = '';
    for (var pass = 0; pass < 2; pass++) {
      var len = Math.hypot(x2 - x1, y2 - y1), wob = Math.min(1.6, 0.4 + len / 60);
      var mx = (x1 + x2) / 2 + this.j(wob), my = (y1 + y2) / 2 + this.j(wob);
      d += 'M' + f(x1 + this.j(wob)) + ' ' + f(y1 + this.j(wob)) + ' Q' + f(mx) + ' ' + f(my) +
           ' ' + f(x2 + this.j(wob)) + ' ' + f(y2 + this.j(wob)) + ' ';
    }
    return node('path', { d: d, 'class': cls || 'dd-ink' }, g);
  };

  Pen.prototype.lines = function (g, pts, closed, cls) {
    for (var i = 0; i + 1 < pts.length; i++) {
      this.line(g, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], cls);
    }
    if (closed) {
      var a = pts[pts.length - 1], b = pts[0];
      this.line(g, a[0], a[1], b[0], b[1], cls);
    }
  };

  // A smooth wobbly curve through points: midpoints joined by quadratics.
  function smooth(pts, closed) {
    var p = closed ? pts.concat([pts[0], pts[1]]) : pts;
    var mid = function (a, b) { return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };
    var start = closed ? mid(p[0], p[1]) : p[0];
    var d = 'M' + f(start[0]) + ' ' + f(start[1]);
    for (var i = 1; i < p.length - 1; i++) {
      var m = mid(p[i], p[i + 1]);
      d += ' Q' + f(p[i][0]) + ' ' + f(p[i][1]) + ' ' + f(m[0]) + ' ' + f(m[1]);
    }
    if (!closed) d += ' L' + f(p[p.length - 1][0]) + ' ' + f(p[p.length - 1][1]);
    return d;
  }

  // An ellipse that does not quite close, with a wash of colour just off it.
  Pen.prototype.ellipse = function (g, cx, cy, rx, ry, wash) {
    if (wash) {
      node('ellipse', { cx: f(cx + 2.5), cy: f(cy + 2.5), rx: f(rx), ry: f(ry),
                        'class': 'dd-wash ' + wash }, g);
    }
    var pts = [], n = 10, turn = this.rand() * Math.PI * 2;
    for (var i = 0; i <= n + 1; i++) {
      var a = turn + (i / n) * Math.PI * 2 * 1.04, k = 1 + this.j(0.07);
      pts.push([cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k]);
    }
    return node('path', { d: smooth(pts, false), 'class': 'dd-ink' }, g);
  };

  Pen.prototype.shape = function (g, pts, wash) {
    if (wash) {
      node('path', { d: smooth(pts.map(function (p) { return [p[0] + 2.5, p[1] + 2.5]; }), true),
                     'class': 'dd-wash ' + wash }, g);
    }
    var self = this;
    var drawn = pts.map(function (p) { return [p[0] + self.j(0.8), p[1] + self.j(0.8)]; });
    return node('path', { d: smooth(drawn, true), 'class': 'dd-ink' }, g);
  };

  Pen.prototype.wave = function (g, x, y, len, up, cls) {
    var pts = [];
    for (var i = 0; i <= 6; i++) pts.push([x + (i % 2 ? 3 : -3) + this.j(0.8), y - (up * i) / 6]);
    return node('path', { d: smooth(pts, false), 'class': cls || 'dd-ink' }, g);
  };

  /* ------------------------------------------------ what each thing is */

  // Whole words only, in any alphabet (JavaScript's \b knows only Latin).
  function word(alts) { return new RegExp('(?<![\\p{L}\\d])(' + alts + ')(?![\\p{L}\\d])', 'iu'); }

  var KINDS = [
    ['plane', word('flight|fly|flying|airport|plane|boarding|departure|полет|летище')],
    ['travel', word('train|drive|driving|trip|travel|commute|taxi|pick ?up|drop ?off|пътуване')],
    ['coffee', word('coffee|tea|cafe|café|espresso|кафе')],
    ['meal', word('lunch|dinner|breakfast|brunch|meal|restaurant|обяд|вечеря|закуска')],
    ['sport', word('gym|run|running|yoga|workout|training|swim|swimming|tennis|football|padel|pilates|hike|фитнес|тренировка')],
    ['health', word('doctor|dentist|hospital|clinic|therapy|physio|checkup|check-up|лекар|зъболекар')],
    ['party', word('birthday|party|celebration|drinks|wedding|рожден|парти')],
    ['book', word('read|reading|study|class|course|lecture|school|learn|webinar')],
    ['talk', word('call|meet|meeting|sync|standup|stand-up|1:1|1-1|one on one|interview|review|chat|demo|catch ?up|intro|среща|разговор')],
  ];

  function kindOf(one) {
    var words = (one.title || '') + ' ' + (one.where || '');
    for (var i = 0; i < KINDS.length; i++) if (KINDS[i][1].test(words)) return KINDS[i][0];
    if (one.video) return 'talk';
    return 'star';
  }

  // Each picture is drawn around (0, 0), about 44 across, standing on y = 22.
  var DRAW = {
    talk: function (p, g) {
      p.ellipse(g, -7, -8, 15, 10, 'a');
      p.lines(g, [[-14, 0], [-17, 8], [-7, 1]]);
      p.ellipse(g, 9, 6, 13, 9, 'b');
      p.lines(g, [[15, 13], [18, 20], [9, 14]]);
    },
    coffee: function (p, g) {
      p.shape(g, [[-13, -4], [13, -4], [10, 18], [-10, 18]], 'a');
      p.ellipse(g, 17, 5, 5, 6);
      p.line(g, -18, 21, 18, 21);
      p.wave(g, -5, -8, 0, 14, 'dd-soft');
      p.wave(g, 4, -9, 0, 12, 'dd-soft');
    },
    meal: function (p, g) {
      p.ellipse(g, 0, 8, 17, 9, 'a');
      p.ellipse(g, 0, 8, 9, 4.5);
      p.line(g, -23, -6, -23, 18);
      p.lines(g, [[-26, -12], [-26, -4], [-20, -4], [-20, -12]]);
      p.line(g, 23, -12, 23, 18);
      p.shape(g, [[23, -12], [27, -6], [27, 3], [23, 3]]);
    },
    sport: function (p, g) {
      p.line(g, -12, 4, 12, 4);
      p.shape(g, [[-20, -8], [-12, -8], [-12, 16], [-20, 16]], 'a');
      p.shape(g, [[12, -8], [20, -8], [20, 16], [12, 16]], 'a');
      p.line(g, -24, 0, -24, 8);
      p.line(g, 24, 0, 24, 8);
    },
    plane: function (p, g) {
      p.shape(g, [[-22, 2], [16, -2], [22, 1], [16, 5], [-20, 6]], 'b');
      p.lines(g, [[-2, 2], [8, -14], [12, -14], [6, 2]]);
      p.lines(g, [[-2, 5], [6, 18], [10, 18], [6, 5]]);
      p.lines(g, [[-18, 2], [-22, -8], [-18, -8], [-12, 2]]);
      p.line(g, -30, 14, -40, 16, 'dd-soft');
      p.line(g, -28, 20, -36, 22, 'dd-soft');
    },
    travel: function (p, g) {
      p.shape(g, [[-22, 4], [-14, -8], [12, -8], [22, 4], [22, 14], [-22, 14]], 'b');
      p.ellipse(g, -11, 16, 5, 5);
      p.ellipse(g, 11, 16, 5, 5);
      p.line(g, -12, -6, -12, 4);
      p.line(g, 0, -8, 0, 4);
    },
    health: function (p, g) {
      p.shape(g, [[0, 18], [-18, 0], [-18, -10], [-10, -16], [0, -8], [10, -16], [18, -10],
                  [18, 0]], 'r');
      p.line(g, 0, -6, 0, 8);
      p.line(g, -7, 1, 7, 1);
    },
    party: function (p, g) {
      p.ellipse(g, -6, -8, 10, 13, 'r');
      p.ellipse(g, 10, -4, 9, 11, 'a');
      p.wave(g, -6, 22, 0, 17);
      p.wave(g, 10, 22, 0, 15);
    },
    book: function (p, g) {
      p.shape(g, [[0, -6], [-20, -12], [-20, 14], [0, 20]], 'a');
      p.shape(g, [[0, -6], [20, -12], [20, 14], [0, 20]], 'b');
      p.line(g, -15, -3, -5, 0, 'dd-soft');
      p.line(g, -15, 4, -5, 7, 'dd-soft');
      p.line(g, 5, 0, 15, -3, 'dd-soft');
    },
    bell: function (p, g) {
      p.shape(g, [[-17, 14], [-12, 8], [-11, -4], [-6, -13], [6, -13], [11, -4], [12, 8],
                  [17, 14]], 'y');
      p.ellipse(g, 0, -16, 3, 3);
      p.ellipse(g, 0, 18, 3.5, 3.5, 'a');
      p.line(g, -20, -8, -25, -12, 'dd-soft');
      p.line(g, 20, -8, 25, -12, 'dd-soft');
    },
    star: function (p, g) {
      var pts = [];
      for (var i = 0; i < 10; i++) {
        var a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 8 : 19;
        pts.push([Math.cos(a) * r, 2 + Math.sin(a) * r]);
      }
      p.shape(g, pts, 'y');
    },
  };

  /* ------------------------------------------------ the scene */

  function weatherKind(w) {
    var words = ((w && w.ok && w.words) || '').toLowerCase();
    if (!words) return '';
    if (/thunder/.test(words)) return 'storm';
    if (/snow/.test(words)) return 'snow';
    if (/rain|drizzle|shower/.test(words)) return 'rain';
    if (/fog/.test(words)) return 'fog';
    if (/overcast|cloud/.test(words) && !/partly|mostly clear/.test(words)) return 'cloud';
    if (/partly/.test(words)) return 'partly';
    return 'sun';
  }

  function sun(p, g, x, y, r) {
    p.ellipse(g, x, y, r, r, 'y');
    for (var i = 0; i < 8; i++) {
      var a = (i * Math.PI) / 4 + p.j(0.12);
      p.line(g, x + Math.cos(a) * (r + 4), y + Math.sin(a) * (r + 4),
             x + Math.cos(a) * (r + 10), y + Math.sin(a) * (r + 10), 'dd-soft');
    }
  }

  function cloud(p, g, x, y) {
    p.shape(g, [[x - 22, y + 8], [x - 24, y - 2], [x - 12, y - 8], [x - 4, y - 16], [x + 10, y - 14],
                [x + 16, y - 6], [x + 25, y - 2], [x + 22, y + 8]], 'c');
  }

  function weather(p, g, w) {
    var kind = weatherKind(w), x = W - 44, y = 34;
    if (!kind) return;
    if (kind === 'sun') { sun(p, g, x, y, 12); return; }
    if (kind === 'partly') { sun(p, g, x + 10, y - 6, 10); cloud(p, g, x - 4, y + 6); return; }
    cloud(p, g, x, y);
    if (kind === 'rain') {
      [-12, -2, 8, 18].forEach(function (dx) { p.line(g, x + dx, y + 14, x + dx - 3, y + 22, 'dd-rain'); });
    } else if (kind === 'snow') {
      [-10, 2, 14].forEach(function (dx) { p.ellipse(g, x + dx, y + 18, 1.6, 1.6); });
    } else if (kind === 'storm') {
      p.lines(g, [[x + 2, y + 10], [x - 4, y + 20], [x + 3, y + 19], [x - 2, y + 30]], false, 'dd-bolt');
    } else if (kind === 'fog') {
      p.line(g, x - 26, y + 16, x + 20, y + 16, 'dd-soft');
      p.line(g, x - 18, y + 22, x + 26, y + 22, 'dd-soft');
    }
  }

  function scribble(g, x, y, words, cls, tilt) {
    var t = node('text', { x: f(x), y: f(y), 'class': cls, 'text-anchor': 'middle',
                           transform: 'rotate(' + f(tilt) + ' ' + f(x) + ' ' + f(y) + ')' }, g);
    t.textContent = words;
    return t;
  }

  // At most `most` letters, cut at a word where there is one.
  function short(words, most) {
    words = String(words || '').trim();
    if (words.length <= most) return words;
    var cut = words.slice(0, most + 1), space = cut.lastIndexOf(' ');
    return (space > most / 2 ? cut.slice(0, space) : cut.slice(0, most - 1)).trim() + '…';
  }

  function hourOf(one) {
    var m = /^(\d\d):(\d\d)$/.exec(one.start || '');
    return m ? +m[1] + +m[2] / 60 : null;
  }

  // Where each of the day's timed things stands on the path: at its hour,
  // pushed apart so no two pictures touch, and spread evenly if they would
  // run off the end.
  function places(hours, right) {
    var left = 58, gap = (right - left) / Math.max(1, MOST - 1);
    var first = Math.min(8, Math.floor(hours[0])), last = Math.max(20, Math.ceil(hours[hours.length - 1]));
    var xs = hours.map(function (h) { return left + ((h - first) / (last - first)) * (right - left); });
    for (var i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + gap);
    if (xs.length && xs[xs.length - 1] > right) {
      var step = xs.length > 1 ? (right - left) / (xs.length - 1) : 0;
      xs = xs.map(function (_, k) { return xs.length > 1 ? left + k * step : W / 2; });
    }
    return xs;
  }

  function trail(p, g, x1, x2) {
    var pts = [];
    for (var x = x1; x <= x2 + 1; x += 26) pts.push([x, PATH_Y + Math.sin(x / 47) * 5 + p.j(1.5)]);
    node('path', { d: smooth(pts, false), 'class': 'dd-trail' }, g);
  }

  function bunting(p, g, titles) {
    var x1 = 22, x2 = W - 104, y = 14;
    node('path', { d: 'M' + x1 + ' ' + y + ' Q' + f((x1 + x2) / 2) + ' ' + (y + 16) + ' ' + x2 + ' ' + y,
                   'class': 'dd-ink' }, g);
    for (var x = x1 + 14, i = 0; x < x2 - 10; x += 26, i++) {
      var sag = y + 16 * (1 - Math.pow((2 * (x - x1)) / (x2 - x1) - 1, 2)) / 2;
      p.shape(g, [[x - 7, sag], [x + 7, sag], [x, sag + 13]], i % 2 ? 'a' : 'y');
    }
    scribble(g, (x1 + x2) / 2, y + 36, short(titles.join(' · '), 44), 'dd-label', p.j(1.5));
  }

  function hammock(p, g) {
    // Two trees, a sagging hammock between them, and a little "zzz".
    var l = W / 2 - 110, r = W / 2 + 110, ground = PATH_Y + 14;
    [l, r].forEach(function (x, i) {
      p.line(g, x, ground, x + p.j(2), ground - 76);
      var lean = i ? 6 : -6;
      p.ellipse(g, x + lean - 12, ground - 80, 17, 13, 'g');
      p.ellipse(g, x + lean + 12, ground - 82, 16, 13, 'g');
      p.ellipse(g, x + lean, ground - 96, 19, 15, 'g');
    });
    var sagY = ground - 26;
    node('path', { d: 'M' + (l + 2) + ' ' + (ground - 56) + ' Q' + W / 2 + ' ' + f(sagY + 22) + ' ' +
                      (r - 2) + ' ' + (ground - 56), 'class': 'dd-ink' }, g);
    node('path', { d: 'M' + (l + 20) + ' ' + (ground - 46) + ' Q' + W / 2 + ' ' + f(sagY + 12) + ' ' +
                      (r - 20) + ' ' + (ground - 46), 'class': 'dd-soft' }, g);
    scribble(g, W / 2 + 34, ground - 70, 'z z z', 'dd-note', -8);
    trail(p, g, 24, W - 24);
  }

  // Today's part of a three-day section (Reminders, Birthdays), or none.
  function todayOf(part, field) {
    var day = part && part.ok && (part.days || []).filter(function (d) { return d.key === 'today'; })[0];
    return (day && day[field]) || [];
  }

  function draw(brief) {
    var cal = brief && brief.calendar, calOk = !!(cal && cal.ok);
    var reminders = todayOf(brief && brief.reminders, 'items').map(function (one) {
      return { title: one.what, start: one.time, reminder: true, kind: one.kind };
    });
    // A birthday on a calendar is already in its all-day events; one only on
    // a contact is not.
    var born = todayOf(brief && brief.birthdays, 'people').filter(function (one) {
      return !calOk || !one.event_key;
    }).map(function (one) { return (one.name || one.guess || one.title) + '’s birthday'; });
    if (!calOk && !reminders.length && !born.length) return null;
    var events = calOk ? cal.today || [] : [];
    var today = events.concat(reminders);
    var allDay = events.filter(function (one) { return one.all_day; })
      .map(function (one) { return one.title; }).concat(born);
    var timed = today.filter(function (one) { return !one.all_day && hourOf(one) != null; });
    timed.sort(function (a, b) { return hourOf(a) - hourOf(b); });
    var more = 0;
    if (timed.length > MOST) { more = timed.length - (MOST - 1); timed = timed.slice(0, MOST - 1); }

    var rand = seeded(brief.day + '|' + today.map(function (one) {
      return (one.start || '') + one.title;
    }).concat(born).join('|'));
    var p = new Pen(rand);
    var svg = node('svg', { viewBox: '0 0 ' + W + ' ' + H, 'class': 'dd-svg', role: 'img' });
    var g = node('g', {}, svg);
    weather(p, g, brief.weather);

    var said;
    if (!today.length && !allDay.length) {
      hammock(p, g);
      scribble(g, W / 2, H - 20, 'Nothing booked. The day is yours.', 'dd-label', p.j(1.5));
      said = 'A doodle of a free day: a hammock between two trees.';
    } else {
      if (allDay.length) bunting(p, g, allDay);
      var xs = places(timed.map(hourOf), W - (more ? 100 : 58));
      var ends = xs.length ? [Math.min(40, xs[0] - 30), W - 24] : [24, W - 24];
      trail(p, g, ends[0], ends[1]);
      timed.forEach(function (one, i) {
        var x = xs[i], y = ICON_Y + p.j(3);
        var pic = node('g', { transform: 'translate(' + f(x) + ' ' + f(y) + ') rotate(' +
                                         f(p.j(6)) + ')' }, g);
        DRAW[one.reminder ? 'bell' : kindOf(one)](p, pic);
        p.ellipse(g, x, PATH_Y + Math.sin(x / 47) * 5, 2.2, 2.2, 'a');
        scribble(g, x, PATH_Y + 26, short(one.title, 12), 'dd-label', p.j(3));
        scribble(g, x, PATH_Y + 43, one.start, 'dd-note', p.j(2));
      });
      if (more) {
        var mx = W - 42;
        scribble(g, mx, ICON_Y + 6, '+' + more, 'dd-more', p.j(6));
        scribble(g, mx, ICON_Y + 24, 'more', 'dd-note', p.j(4));
      }
      if (!timed.length && !more) {
        scribble(g, W / 2, PATH_Y - 10, 'No meetings. Room to wander.', 'dd-label', p.j(1.5));
      }
      said = 'A doodle of your day: ' + today.filter(function (one) { return !one.all_day; })
        .map(function (one) {
          return !one.reminder ? one.title
            : (one.kind === 'remind' ? 'a reminder, ' : 'scheduled, ') + one.title;
        })
        .concat(allDay).join(', ') + '.';
    }
    svg.setAttribute('aria-label', said);
    return svg;
  }

  window.RouhDoodle = {
    // The drawing, or null when there is nothing to draw it from. A doodle
    // that fails is left out; it never takes the brief down with it.
    draw: function (brief) {
      try { return draw(brief); } catch (e) { return null; }
    },
    kindOf: kindOf,
  };
})();
