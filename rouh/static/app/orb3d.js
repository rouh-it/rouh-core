/* Rouh's page, the orb in 3D.
 *
 * The orb is the live picture of every piece of work happening on this
 * machine. Since 11 November 2026 it is drawn in three.js, in the look Petar
 * settled over ten rounds of workspace task 178, step 178-02 ("Orb tree built
 * in Blender by Astra"): see-through glass tubes with a coloured light along
 * their edges, real reflections from a small studio around them, a key and a
 * rim light, a glowing nerve down the middle of each, and a bright white core
 * with a halo of its own and a P hidden inside it.
 *
 * It is not that model's frozen tree. 178-02's own recommendation was to grow
 * the live tree in the browser by the same branching rules, and that is what
 * this does: every job, helper and tool call in the server's work tree
 * (app/orb.js, `applyTree`) becomes a tube grown from its own id, by the rules
 * in rouh/static/orb-branching.json, which the Blender build reads too, so the
 * two cannot drift apart.
 *
 *   the machine   the core: a white sphere with its own halo
 *   a job         a turquoise branch out of the core
 *   a helper      a thinner turquoise branch off its job
 *   a tool call   a coloured twig off the line that made it, longer the
 *                 longer the call ran; its colour is its kind
 *   Rouh's turn   a branch in the core's own pale colour, its calls as twigs
 *   waiting       red and dashed, breathing, with a square at its tip and
 *                 the words NEEDS YOU; it never fades while it waits
 *   finished      fades smoothly with brief flashes, holds, goes to a grey
 *                 trace, and is gone (178-02's lifecycle, its timings)
 *
 * app/orb.js still owns everything around the picture - where the circle
 * sits, the rings, the numbers, the cards and the tips - and the work tree
 * itself. It asks this module to draw (`orb3dFrame`) and what is under a
 * pointer (`orb3dPick`). When WebGL is missing or fails, this says so and
 * app/orb.js draws the old flat orb instead (its `orb2d` path).
 */

var RULES = null;            // rouh/static/orb-branching.json, once read
var T = null;                // three.js, once loaded
var O3 = { on: false, failed: '', frames: 0, renders: 0 };
var KEY_3D = 'rouh.orb3d.v1';

/* ------------------------------------------------------------ settings */

var prefs = null, DEFAULTS = null, LIMITS = null;

function validPrefs(v) {
  var out = {}, k;
  for (k in DEFAULTS) out[k] = DEFAULTS[k];
  if (!v || typeof v !== 'object') return out;
  if (typeof v.nerve === 'boolean') out.nerve = v.nerve;
  for (k in LIMITS) {
    if (typeof v[k] === 'number' && isFinite(v[k])) out[k] = Math.max(LIMITS[k][0], Math.min(LIMITS[k][1], v[k]));
  }
  if (v.blinkDirection === 'down') out.blinkDirection = 'down';
  return out;
}

function loadPrefs() {
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY_3D) || 'null'); } catch (e) { saved = null; }
  prefs = validPrefs(saved);
}

function savePrefs() {
  try { localStorage.setItem(KEY_3D, JSON.stringify(prefs)); } catch (e) {}
}

function blinkConfig() {
  return { end: prefs.endLevel / 100, seconds: prefs.fadeSeconds, rate: prefs.blinkRate,
           length: prefs.blinkLength / 1000, direction: prefs.blinkDirection,
           hold: prefs.holdMinutes * 60, ghost: prefs.ghostSeconds };
}

/* Whether a finished node is still on the orb: through its fade, its hold and
   its grey trace, by the timings it finished under (moved settings apply to
   the next thing to finish). app/orb.js keeps a finished node exactly this
   long, so it can be pointed at until it is gone. */
function orb3dKeeps(n, tnow) {
  if (!prefs) return false;
  var r = REC.get(n.id), c = r && r.blink ? r.blink : blinkConfig();
  return (tnow - n.fade) / 1000 < c.seconds + c.hold + c.ghost + 1;
}

/* 178-02's lifecycle, as its viewer has it (round 10): the whole branch fades
   smoothly from 100% to the end level over the fade time, with a brief flash
   to 100% (or to nothing) a few times a second; then it holds steady, then it
   is a grey trace, then it is gone. Asking for less movement keeps the fade
   and drops the flashes. */
function lifecycle(age, c, still) {
  var level = 1 + (c.end - 1) * Math.min(1, Math.max(0, age) / c.seconds);
  if (age >= c.seconds + c.hold + c.ghost) return { state: 'removed', alpha: 0, level: c.end };
  if (age >= c.seconds + c.hold) return { state: 'ghost', alpha: 0, level: c.end };
  if (age >= c.seconds) return { state: 'holding', alpha: c.end, level: c.end };
  var flashing = !still && age >= 1 / c.rate && (age % (1 / c.rate)) < c.length;
  return { state: 'fading', alpha: flashing ? (c.direction === 'up' ? 1 : 0) : level, level: level };
}

/* -------------------------------------------------------------- seeding */

function hashId(s) {
  var h = 2166136261, i;
  s = String(s);
  for (i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// The same numbers for the same id every time (mulberry32), so a job keeps
// its shape across a reload and a new job never reshuffles the others.
function seeded(id) {
  var a = hashId(id) || 1;
  function next() {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  }
  return { next: next, R: function (lo, hi) { return lo + (hi - lo) * next(); } };
}

/* ------------------------------------------------------------- the scene */

var renderer, scene, camera, group, controls, composer, bloom, baseTarget, finalQuad;
var keyLight, rimLight, coreSphere, coreLetter, coreHalo, coreMask, coreRadius = 0.028;
var edgeUniform = { value: 1 };
var canvas = null, host = null, labels = null;
var REC = new Map();          // one record per node id that has a tube
var growth = 0;               // the growth clock, in seconds, sped up by Growth speed
var size = { w: 0, h: 0, ratio: 0, state: '' };
var dirty = true, lastRender = -1e9, lastMode = '', viewTween = null, slowMo = false;
var userMoved = false;

function colourOf(key) {
  return new T.Color(RULES.palette[key] || RULES.palette.other);
}

/* The glass, as 178-02's viewer makes it (`glass` there): a physical material
   that is mostly see-through in the middle and nearly solid at its edges,
   with a coloured light along the edge, studio reflections and a clear coat;
   every surface is tone-mapped to display brightness on its own before it is
   laid over what is behind it, so a fade dims the whole branch evenly.
   What is added here is the growth: each tube is drawn from its centre line
   in the vertex shader, so the tip can travel along the curve while the grown
   part stays where it is and thickens. */
function glass(colour, kind, u) {
  var G = RULES.glass, P = RULES.path, rim = kind === 'tube' ? G.rim : null;
  var m = new T.MeshPhysicalMaterial();
  m.color.copy(colour);
  m.emissive.copy(colour);
  m.emissiveIntensity = kind === 'nerve' ? G.nerve.emission : kind === 'core' ? prefs.coreGlow : G.emission;
  m.opacity = kind === 'nerve' ? G.nerve.alpha : kind === 'core' ? 1 : G.alpha;
  m.transparent = true;
  m.premultipliedAlpha = true;
  m.depthWrite = kind === 'core';
  m.side = T.FrontSide;
  m.roughness = kind === 'core' ? 0.2 : G.roughness;
  m.metalness = 0;
  m.clearcoat = prefs.reflections === 0 ? 0 : 1;
  m.clearcoatRoughness = G.clearcoatRoughness;
  m.specularIntensity = prefs.reflections;
  m.envMapIntensity = prefs.reflections;
  m.onBeforeCompile = function (shader) {
    shader.uniforms.orbEdge = edgeUniform;
    shader.fragmentShader = 'uniform float orbEdge;\n' + shader.fragmentShader;
    if (u) {
      for (var name in u) shader.uniforms[name] = u[name];
      shader.vertexShader =
        'attribute vec3 orbCenter; attribute float orbArc; attribute float orbR;\n' +
        'uniform float uAge, uGrow, uThicken, uThickness, uLen;\n' +
        'varying float vOrbArc;\n' +
        shader.vertexShader.replace('#include <begin_vertex>',
          '#include <begin_vertex>\n' +
          ' float orbU = clamp(orbArc / max(uLen, 0.0001), 0.0, 1.0);\n' +
          ' float orbTaper = pow(1.0 - orbU, ' + P.taperPower.toFixed(3) + ') * ' + P.taperScale.toFixed(3) +
          ' + ' + P.taperFloor.toFixed(3) + ';\n' +
          ' float orbMature = smoothstep(0.0, uThicken, uAge - orbArc * uGrow);\n' +
          ' float orbRad = orbR * orbTaper * uThickness * (' + RULES.growth.seedRadius.toFixed(3) +
          ' + ' + (1 - RULES.growth.seedRadius).toFixed(3) + ' * orbMature);\n' +
          ' transformed = orbCenter + normal * orbRad;\n' +
          ' vOrbArc = orbArc;');
      shader.fragmentShader =
        'uniform float uReveal, uDash; varying float vOrbArc;\n' +
        shader.fragmentShader.replace('#include <clipping_planes_fragment>',
          '#include <clipping_planes_fragment>\n if (vOrbArc > uReveal) discard;\n' +
          ' if (uDash > 0.0 && mod(vOrbArc * uDash, 2.0) > 1.1) discard;');
    }
    if (rim) {
      shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>',
        '  float edge = pow(1.0 - abs(dot(normalize(normal), normalize(vViewPosition))), ' + rim.power.toFixed(3) + ');\n' +
        '  float band = pow(edge, ' + rim.narrowPower.toFixed(3) + ');\n' +
        '  vec3 tint = diffuseColor.rgb;\n' +
        '  tint = mix(tint, vec3(max(max(tint.r, tint.g), tint.b)), 0.10);\n' +
        '  float alive = min(1.0, max(max(totalEmissiveRadiance.r, totalEmissiveRadiance.g), totalEmissiveRadiance.b));\n' +
        '  outgoingLight += tint * band * ' + rim.highlight.toFixed(3) + ' * orbEdge * alive;\n' +
        '  float profile = mix(' + rim.centerAlpha.toFixed(3) + ', ' + rim.rimAlpha.toFixed(3) + ', edge);\n' +
        '  diffuseColor.a = opacity * profile / ' + G.alpha.toFixed(3) + ';\n' +
        '  #include <opaque_fragment>');
    }
    shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>',
      '  outgoingLight /= 1.0 + max(max(outgoingLight.r, outgoingLight.g), outgoingLight.b);\n' +
      '  outgoingLight = sRGBTransferOETF(vec4(outgoingLight, 1.0)).rgb;\n' +
      '  #include <opaque_fragment>');
  };
  m.customProgramCacheKey = function () { return 'rouh-orb3d-' + kind + (u ? '-grown' : ''); };
  return m;
}

/* A tube's geometry: its centre line, smoothed, at even steps along its
   length, with eight sides round each step and a cap on the tip. The vertex
   shader puts each vertex at its centre plus its direction times the radius,
   so the same geometry is the thin seed, the grown tube, the thicker one a
   slider asks for, and - drawn with another material - the nerve inside. */
var SEGMENTS = 32, SIDES = 8;

function tubeGeometry(path) {
  var curve = new T.CatmullRomCurve3(path.pts, false, 'centripetal');
  var frames = curve.computeFrenetFrames(SEGMENTS, false);
  var n = (SEGMENTS + 1) * SIDES + 1;
  var pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), cen = new Float32Array(n * 3);
  var arc = new Float32Array(n), rad = new Float32Array(n), centres = [], i, j, k = 0;
  var p = new T.Vector3(), dir = new T.Vector3();
  for (i = 0; i <= SEGMENTS; i++) {
    var u = i / SEGMENTS;
    curve.getPointAt(u, p);
    centres.push(p.clone());
    var r = path.radius * path.wob(u);
    for (j = 0; j < SIDES; j++) {
      var a = j / SIDES * Math.PI * 2;
      dir.copy(frames.normals[i]).multiplyScalar(Math.cos(a)).addScaledVector(frames.binormals[i], Math.sin(a)).normalize();
      pos[k * 3] = p.x + dir.x * r; pos[k * 3 + 1] = p.y + dir.y * r; pos[k * 3 + 2] = p.z + dir.z * r;
      nor[k * 3] = dir.x; nor[k * 3 + 1] = dir.y; nor[k * 3 + 2] = dir.z;
      cen[k * 3] = p.x; cen[k * 3 + 1] = p.y; cen[k * 3 + 2] = p.z;
      arc[k] = u; rad[k] = r;
      k++;
    }
  }
  // The tip's cap: one vertex at the very end, with no radius of its own.
  var tip = centres[SEGMENTS], tan = frames.tangents[SEGMENTS];
  pos[k * 3] = tip.x; pos[k * 3 + 1] = tip.y; pos[k * 3 + 2] = tip.z;
  nor[k * 3] = tan.x; nor[k * 3 + 1] = tan.y; nor[k * 3 + 2] = tan.z;
  cen[k * 3] = tip.x; cen[k * 3 + 1] = tip.y; cen[k * 3 + 2] = tip.z;
  arc[k] = 1; rad[k] = 0;
  var index = [];
  for (i = 0; i < SEGMENTS; i++) {
    for (j = 0; j < SIDES; j++) {
      var a0 = i * SIDES + j, a1 = i * SIDES + (j + 1) % SIDES, b0 = a0 + SIDES, b1 = a1 + SIDES;
      index.push(a0, b0, a1, a1, b0, b1);
    }
  }
  var last = SEGMENTS * SIDES;
  for (j = 0; j < SIDES; j++) index.push(last + j, k, last + (j + 1) % SIDES);
  var g = new T.BufferGeometry();
  g.setAttribute('position', new T.BufferAttribute(pos, 3));
  g.setAttribute('normal', new T.BufferAttribute(nor, 3));
  g.setAttribute('orbCenter', new T.BufferAttribute(cen, 3));
  g.setAttribute('orbArc', new T.BufferAttribute(arc, 1));
  g.setAttribute('orbR', new T.BufferAttribute(rad, 1));
  g.setIndex(index);
  g.computeBoundingSphere();
  return { geometry: g, centres: centres, tangents: frames.tangents, length: curve.getLength() };
}

/* One branch's centre line, by build_orb.py's own rule (`path` there): out
   along its direction, bowed gently to one side, wandering a little more the
   further out it gets, and not quite round all the way along. */
function branchPath(rng, origin, d, length, radius) {
  var P = RULES.path, R = rng.R;
  var Z = new T.Vector3(0, 0, 1), Y = new T.Vector3(0, 1, 0);
  var side = d.clone().cross(Math.abs(d.z) < 0.9 ? Z : Y).normalize();
  var up = d.clone().cross(side).normalize();
  var phase = R(0, Math.PI * 2), phase2 = R(0, Math.PI * 2);
  var bend = side.clone().multiplyScalar(R(-P.bendSide, P.bendSide)).addScaledVector(up, R(-P.bendUp, P.bendUp));
  var pts = [origin.clone()];
  for (var i = 1; i <= P.samples; i++) {
    var t = i / P.samples;
    var wander = side.clone().multiplyScalar(Math.sin(t * P.wanderFreqSide + phase) - Math.sin(phase))
      .addScaledVector(up, Math.sin(t * P.wanderFreqUp + phase2) - Math.sin(phase2))
      .multiplyScalar(length * P.wander * t);
    pts.push(origin.clone().addScaledVector(d, length * t).addScaledVector(bend, length * t * t).add(wander));
  }
  return {
    pts: pts, radius: Math.max(radius, P.minRadius),
    wob: function (t) { return 1 + P.wobble * Math.sin(t * P.wobbleFreq + phase); }
  };
}

/* ------------------------------------------------------------- records */

// What the tree's node is, to the shape: a job's or a helper's branch, a twig,
// or Rouh's own line.
function roleOf(n) {
  if (n.kind === 'tool') return 'twig';
  if (n.kind === 'self') return 'self';
  return 'branch';
}

// How long a call ran, from 0 to 1: a quick read is a stub, thirty seconds
// or more is the whole length (the flat orb's own measure).
function costOf(n, tnow) {
  var raw = n.raw || {};
  var secs = raw.ms != null && n.closed ? raw.ms / 1000 : Math.max(0, ((n.closed || tnow) - n.opened) / 1000);
  return Math.max(0, Math.min(1, Math.log(1 + secs) / Math.log(1 + RULES.process.fullAfterSeconds)));
}

// A direction out of the core for a job: from the job's own id, the one of a
// handful of its own candidates furthest from the jobs already there. Nothing
// already drawn ever moves for it.
function jobDirection(rng) {
  var A = RULES.agent, best = null, bestScore = -1;
  var taken = [];
  REC.forEach(function (r) { if (r.depth === 1 && !r.removed) taken.push(r.dir); });
  for (var c = 0; c < 8; c++) {
    var z = rng.R(-1, 1), a = rng.R(0, Math.PI * 2), s = Math.sqrt(1 - z * z);
    var d = new T.Vector3(Math.cos(a) * s, Math.sin(a) * s, z * A.zSquash).normalize();
    var score = 4;
    for (var i = 0; i < taken.length; i++) score = Math.min(score, d.distanceTo(taken[i]));
    if (score > bestScore) { bestScore = score; best = d; }
    if (!taken.length) break;
  }
  return best;
}

function makeRecord(n, parent, tnow) {
  var A = RULES.agent, Pr = RULES.process, rng = seeded(n.id), role = roleOf(n);
  var depth = parent ? parent.depth + 1 : 1;
  var origin, dir, length, radius, fork = 0;
  if (!parent) {
    origin = new T.Vector3();
    if (role === 'twig') {
      // One of Rouh's own calls with no line of its own to hang off.
      dir = jobDirection(rng);
      length = rng.R(A.length[0], A.length[1]) * rng.R(Pr.length[0], Pr.length[1]) * Pr.longest;
      radius = Pr.radius;
    } else {
      dir = jobDirection(rng);
      length = rng.R(A.length[0], A.length[1]);
      radius = A.radius;
    }
  } else {
    var lo = role === 'twig' ? Pr.fork[0] : A.childFork[0], hi = role === 'twig' ? Pr.fork[1] : A.childFork[1];
    fork = rng.R(lo, hi);
    var at = Math.round(fork * SEGMENTS);
    origin = parent.centres[at].clone();
    var tan = parent.tangents[at].clone().normalize();
    var side = new T.Vector3(-tan.y, tan.x, rng.R(-0.4, 0.4)).normalize();
    if (role === 'twig') {
      var sign = rng.next() < 0.5 ? -1 : 1;
      var angle = sign * (Pr.minAngle + rng.R(0, Pr.spread)) + rng.R(-Pr.spreadJitter, Pr.spreadJitter);
      dir = tan.clone().multiplyScalar(Math.cos(angle)).addScaledVector(side, Math.sin(angle)).normalize();
      length = parent.length * rng.R(Pr.length[0], Pr.length[1]) * Math.pow(Pr.lengthFalloff, depth - 2) * Pr.longest;
      radius = Math.max(Pr.minRadius, Pr.radius * Math.pow(Pr.radiusFalloff, depth - 2));
    } else {
      dir = tan.clone().multiplyScalar(A.childLean)
        .addScaledVector(side, (rng.next() < 0.5 ? 1 : -1) * rng.R(A.childSpread[0], A.childSpread[1])).normalize();
      length = parent.length * rng.R(A.childLength[0], A.childLength[1]);
      radius = Math.min(A.radius * Math.pow(A.radiusFalloff, depth - 1), parent.radius * A.childRadiusOfParent);
    }
  }
  var path = branchPath(rng, origin, dir, length, radius);
  var tube = tubeGeometry(path);
  var colour = colourOf(role === 'self' ? 'self' : role === 'twig' ? 'other' : 'agent');
  var u = {
    uAge: { value: 0 }, uGrow: { value: RULES.growth.tipSeconds }, uThicken: { value: RULES.growth.thickenSeconds },
    uThickness: { value: 1 }, uLen: { value: 1 }, uReveal: { value: -1 }, uDash: { value: 0 }
  };
  var un = {
    uAge: u.uAge, uGrow: u.uGrow, uThicken: u.uThicken, uThickness: { value: RULES.glass.nerve.radius },
    uLen: u.uLen, uReveal: u.uReveal, uDash: { value: 0 }
  };
  var mat = glass(colour, 'tube', u), nmat = glass(colour, 'nerve', un);
  var mesh = new T.Mesh(tube.geometry, mat), nerve = new T.Mesh(tube.geometry, nmat);
  mesh.frustumCulled = false; nerve.frustumCulled = false;
  mesh.renderOrder = depth; nerve.renderOrder = depth;
  group.add(mesh); group.add(nerve);
  // Something already well under way when it was first seen - a reload, a
  // tree that arrived late - is drawn grown, not grown again.
  var seenLate = n.opened && tnow - n.opened > 2500;
  var born = seenLate ? growth - 60 : growth;
  if (parent && !seenLate) born = Math.max(born, parent.born + RULES.growth.tipSeconds * fork);
  var r = {
    id: n.id, node: n, role: role, depth: depth, parent: parent ? parent.id : null, dir: dir.clone(),
    centres: tube.centres, tangents: tube.tangents, length: length, worldLength: tube.length, radius: radius,
    fork: fork, mesh: mesh, nerve: nerve, mat: mat, nmat: nmat, u: u, un: un, colour: colour,
    born: born, finished: 0, blink: null, life: null, seen: 0, removed: false, reveal: -1, key: ''
  };
  REC.set(n.id, r);
  dirty = true;
  return r;
}

function dropRecord(r) {
  group.remove(r.mesh); group.remove(r.nerve);
  r.mesh.geometry.dispose(); r.mat.dispose(); r.nmat.dispose();
  r.removed = true;
  REC.delete(r.id);
  dirty = true;
}

/* -------------------------------------------------------------- a frame */

var MAX_TWIGS = 24;
var frameNo = 0;
var GHOST = null, WAIT = null;

// Each record's look this frame, from its node: colour, how much of it has
// grown, how it is fading. Says whether anything on it is moving, which is
// what decides whether the small circle needs drawing again.
function updateRecord(r, n, tnow, t, mode) {
  var G = RULES.glass, moving = false;
  r.node = n;
  r.seen = frameNo;
  var role = r.role;
  var waiting = !n.fade && n.state === 'waiting';
  var kind = role === 'self' ? 'self' : role === 'branch' ? 'agent' : (O3.kindOf(n.label, n.raw && n.raw.what) || 'other');
  // The finished work's own clock: from when it was seen to finish. Settings
  // moved later apply to the next thing to finish, as in 178-02.
  if (n.fade && r.finished !== n.fade) { r.finished = n.fade; r.blink = blinkConfig(); }
  if (!n.fade) { r.finished = 0; r.blink = null; }
  var life = r.finished ? lifecycle((tnow - r.finished) / 1000, r.blink, slowMo) : null;
  r.life = life;
  if (life && life.state === 'removed') return 'removed';

  // Length: a job's whole branch; a call's twig is as long as the call ran.
  var len = role === 'twig' ? (RULES.process.shortest + (RULES.process.longest - RULES.process.shortest) * costOf(n, tnow)) / RULES.process.longest : 1;
  if (role === 'twig' && !n.closed) moving = true;
  r.u.uLen.value = len;
  var age = growth - r.born;
  r.u.uAge.value = age;
  var reveal = age < 0 ? -1 : Math.min(len, age / RULES.growth.tipSeconds);
  r.u.uReveal.value = reveal;
  r.reveal = reveal;
  if (age < RULES.growth.tipSeconds + RULES.growth.thickenSeconds + 0.1) moving = true;
  // The small circle is 66 px across: there the tubes are drawn thicker and
  // more solid, or a branch would be a pixel of see-through glass.
  var small = mode !== 'open';
  var thick = prefs.thickness * (mode === 'corner' ? 4 : mode === 'menu' ? 2 : 1);
  r.u.uThickness.value = thick;
  r.un.uThickness.value = thick * G.nerve.radius;
  r.u.uDash.value = waiting ? r.worldLength * (mode === 'open' ? 160 : 45) : 0;

  var key = life && life.state === 'ghost' ? 'ghost' : waiting ? 'wait' : kind;
  var col = key === 'ghost' ? GHOST : key === 'wait' ? WAIT : colourOf(kind);
  if (r.key !== key) {
    r.key = key;
    r.mat.color.copy(col); r.mat.emissive.copy(col);
    r.nmat.color.copy(col); r.nmat.emissive.copy(col);
    dirty = true;
  }
  var alpha = 1, emission = G.emission, nerveEmission = G.nerve.emission;
  if (life) {
    moving = true;
    if (life.state === 'ghost') {
      alpha = G.ghostAlpha; emission = G.ghostEmission; nerveEmission = 0.08;
    } else alpha = life.alpha;
  }
  if (waiting) {
    // Breathing: the one cue here that moves on its own. Held steady for a
    // machine that asks for less movement; the red, the dashes, the square
    // and the words say it without it.
    emission = G.emission * (slowMo ? 1.6 : 1.3 + 0.7 * Math.sin(t * 2.3));
    if (!slowMo) moving = true;
  }
  r.mat.opacity = Math.min(1, G.alpha * alpha * (small ? 2.6 : 1));
  r.mat.emissiveIntensity = emission;
  r.nmat.opacity = G.nerve.alpha * (life && life.state === 'ghost' ? G.ghostAlpha : alpha);
  r.nmat.emissiveIntensity = nerveEmission;
  r.mesh.renderOrder = life && life.state === 'ghost' ? -1 : r.depth;
  r.mesh.visible = reveal > 0;
  r.nerve.visible = reveal > 0 && prefs.nerve;
  r.waiting = waiting;
  return moving ? 'moving' : 'still';
}

// Walk the tree app/orb.js worked out this frame: jobs off the core, helpers
// and calls off them. Records are made the first time something is seen.
function sync(v) {
  var tnow = v.tnow, moving = false, waiting = 0, live = 0;
  frameNo++;
  function visit(n, parent) {
    var r = REC.get(n.id);
    if (!r) r = makeRecord(n, parent, tnow);
    var said = updateRecord(r, n, tnow, v.t, v.mode);
    if (said === 'removed') { dropRecord(r); return; }
    if (said === 'moving') moving = true;
    if (r.waiting) waiting++;
    else if (!n.fade && r.role !== 'twig') live++;
    var calls = n.calls || [];
    if (calls.length > MAX_TWIGS) calls = calls.slice().sort(function (a, b) { return a.opened - b.opened; }).slice(-MAX_TWIGS);
    for (var i = 0; i < calls.length; i++) {
      // A call of a branch that is finished is finished too.
      visit(calls[i], r);
    }
    var subs = n.subs || [];
    for (var j = 0; j < subs.length; j++) visit(subs[j], r);
  }
  for (var i = 0; i < v.jobs.length; i++) visit(v.jobs[i], null);
  // Rouh's own calls hang off its line while that is drawn; off the core
  // itself when one outlives the line.
  var selfRec = v.self && v.self.alpha > 0.005 ? REC.get(v.self.id) : null;
  if (!selfRec) {
    for (var k = 0; k < v.own.length; k++) visit(v.own[k], null);
  }
  REC.forEach(function (r) { if (r.seen !== frameNo) dropRecord(r); });
  O3.waiting = waiting;
  O3.live = live;
  return moving;
}

/* ------------------------------------------------------------- drawing */

function near() {
  var d = camera.position.distanceTo(controls && controls.enabled ? controls.target : new T.Vector3());
  return T.MathUtils.smoothstep(d / coreRadius, 1.1, 3);
}

// How far the drawn work reaches from the core, for framing it.
function reach() {
  var far = 0.45;
  REC.forEach(function (r) {
    if (r.reveal <= 0) return;
    var at = r.centres[Math.min(SEGMENTS, Math.round(r.reveal * SEGMENTS))];
    far = Math.max(far, at.length() + 0.04);
  });
  return far;
}

var PITCH = 0.28;

// The camera for the small circle and the row: fixed, a little above, framed
// on whatever is drawn, which the circle cuts round.
function frameStill(mode, w, h) {
  var far = reach(), half = T.MathUtils.degToRad(camera.fov / 2);
  var dist = far / Math.sin(half) * 0.98;
  if (mode === 'menu') {
    // The row is a slit onto the middle of the orb: its height shows a little
    // over half of it, so the branches pass through it rather than fill it.
    dist = far / Math.sin(half) * 0.62;
  }
  camera.position.set(0, Math.sin(PITCH) * dist, Math.cos(PITCH) * dist);
  camera.lookAt(0, 0, 0);
}

// The open orb's distance: the whole of what is drawn in view, with room
// round it, and never further than 178-02's own 3.1.
function defaultDistance() {
  var half = T.MathUtils.degToRad(camera.fov / 2) * Math.min(1, camera.aspect >= 1 ? 1 : camera.aspect);
  return Math.min(3.1, Math.max(0.9, reach() / Math.tan(half) * 1.12));
}

function recenter() {
  if (!controls) return;
  var damp = controls.enableDamping;
  controls.enableDamping = false; controls.update(); controls.enableDamping = damp;
  viewTween = { start: performance.now(), from: camera.position.clone(), target: controls.target.clone(),
                to: new T.Vector3(0, 0, defaultDistance()) };
  userMoved = false;
  dirty = true;
}

function resize(w, h, mode) {
  var ratio = mode === 'open' ? Math.min(window.devicePixelRatio || 1, 1.5) : Math.min(window.devicePixelRatio || 1, 2);
  if (w === size.w && h === size.h && ratio === size.ratio) return;
  size.w = w; size.h = h; size.ratio = ratio;
  renderer.setPixelRatio(ratio);
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(1, h);
  camera.fov = mode === 'open' && camera.aspect < 1 ? 38 / Math.max(camera.aspect, 0.55) : 38;
  camera.updateProjectionMatrix();
  if (mode === 'open' && composer) {
    composer.setSize(w, h);
    baseTarget.setSize(Math.round(w * ratio), Math.round(h * ratio));
  }
  dirty = true;
}

function paintCore(mode, waiting) {
  var strength = prefs.coreGlow * (mode === 'open' ? near() : 1);
  coreSphere.material.emissiveIntensity = strength;
  coreSphere.material.opacity = strength === 0 ? 0.22 : T.MathUtils.lerp(0.22, 1, Math.min(1, strength / 4));
  coreSphere.material.depthWrite = coreSphere.material.opacity >= 1;
  coreLetter.material.emissiveIntensity = strength;
  coreLetter.material.color.setScalar(strength === 0 ? 0.12 : 1);
  coreHalo.material.opacity = Math.min(1, prefs.coreGlow / 80) * (mode === 'open' ? near() : 0.9);
  coreHalo.scale.setScalar(coreRadius * (5 + 5 * Math.sqrt(prefs.coreGlow / 80)) * (mode === 'open' ? 1 : 0.8));
  // The circle's colour at a glance: the halo goes red while anything waits
  // for the person, and turquoise-white while work runs.
  var tint = waiting ? WAIT : O3.live ? colourOf('agent') : null;
  // Over the whole screen the core stays white with only a hint of it; the
  // branch itself, red and dashed with NEEDS YOU, says the rest there.
  var open = mode === 'open';
  if (tint) coreHalo.material.color.copy(tint).lerp(new T.Color(1, 1, 1), open ? (waiting ? 0.7 : 0.85) : (waiting ? 0.15 : 0.45));
  else coreHalo.material.color.setRGB(1, 1, 1);
}

function render(mode) {
  if (mode !== 'open' || !composer || !(prefs.glow > 0)) {
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
    O3.renders++;
    return;
  }
  // 178-02's order: the scene, then bloom from the branches only (the core
  // and its halo masked out, so Glow is the branches' and Core glow the
  // core's), then the two added together.
  renderer.setRenderTarget(baseTarget);
  renderer.render(scene, camera);
  var saved = [[coreSphere, coreSphere.material], [coreLetter, coreLetter.material]];
  coreSphere.material = coreMask; coreLetter.material = coreMask;
  coreHalo.visible = false;
  var bg = scene.background;
  scene.background = new T.Color(0);
  composer.render();
  scene.background = bg;
  for (var i = 0; i < saved.length; i++) saved[i][0].material = saved[i][1];
  coreHalo.visible = true;
  finalQuad.material.uniforms.soft.value = bloom.renderTargetsHorizontal[0].texture;
  renderer.setRenderTarget(null);
  finalQuad.render(renderer);
  O3.renders++;
}

var DPOS = null;

// The words NEEDS YOU and the square at the tip of each thing waiting for
// the person, laid over the picture: crisp at any size, and the square is
// there in the small circle too. Only the open orb has room for the words.
function paintLabels(mode) {
  if (!labels) return;
  var n = 0, rect = { w: size.w, h: size.h };
  REC.forEach(function (r) {
    if (!r.waiting || r.reveal <= 0) return;
    var el = labels.children[n] || labels.appendChild(document.createElement('div'));
    el.className = 'orb3d-wait' + (mode === 'open' ? '' : ' small');
    if (!el.firstChild) el.innerHTML = '<i></i><b>NEEDS YOU</b>';
    var tip = r.centres[Math.min(SEGMENTS, Math.round(r.reveal * SEGMENTS))];
    DPOS.copy(tip).applyMatrix4(group.matrixWorld).project(camera);
    el.style.transform = 'translate(' + ((DPOS.x + 1) / 2 * rect.w).toFixed(1) + 'px,' + ((1 - DPOS.y) / 2 * rect.h).toFixed(1) + 'px)';
    el.hidden = DPOS.z > 1;
    n++;
  });
  while (labels.children.length > n) labels.removeChild(labels.lastChild);
}

/* The one call app/orb.js makes each frame it draws. `v` is what it worked
   out this frame: the time, the jobs, Rouh's own calls and line, where the
   orb is (corner, open or the row on a phone) and the box's size. Drawing
   happens only when it is worth it: the open orb every frame, the small
   circle when something changed, and at a quarter of the page's rate while
   anything on it moves. */
function orb3dFrame(v) {
  if (!O3.on) return;
  O3.frames++;
  var mode = v.mode, dt = v.dt || 0;
  growth += dt * prefs.speed;
  if (mode !== lastMode) {
    dirty = true;
    if (controls) controls.enabled = mode === 'open';
    if (mode === 'open') {
      userMoved = false;
      controls.target.set(0, 0, 0);
      camera.position.set(0, 0, defaultDistance());
      controls.update();
    }
    lastMode = mode;
  }
  resize(v.w, v.h, mode);
  var moving = sync(v);
  if (!slowMo && REC.size) { group.rotation.y += dt * 0.07; moving = true; }
  if (mode === 'open') {
    if (viewTween) {
      var k = slowMo ? 1 : Math.min(1, (performance.now() - viewTween.start) / 650), e = k * k * (3 - 2 * k);
      camera.position.copy(viewTween.from).lerp(viewTween.to, e);
      controls.target.copy(viewTween.target).multiplyScalar(1 - e);
      camera.lookAt(controls.target);
      if (k >= 1) { viewTween = null; controls.update(); }
    } else if (!userMoved) {
      // Until the person turns or zooms it themselves, the open orb keeps
      // the whole tree in view as it grows and as finished work goes.
      var want = defaultDistance(), d = camera.position.length();
      if (Math.abs(want - d) > 0.01) {
        camera.position.multiplyScalar((d + (want - d) * Math.min(1, dt * 2)) / d);
        dirty = true;
      }
    }
    controls.update();
  } else {
    frameStill(mode, v.w, v.h);
  }
  paintCore(mode, O3.waiting);
  var due = mode === 'open' || dirty || (moving && v.t - lastRender >= 1 / 15);
  if (!due) return;
  group.updateMatrixWorld();
  render(mode);
  paintLabels(mode);
  lastRender = v.t;
  dirty = false;
}

/* ------------------------------------------------------------- pointing */

var LIMB_RADIUS = 14, TIP_RADIUS = 16, WAIT_RADIUS = 22, TWIG_RADIUS = 9, TWIG_TIP_RADIUS = 12, TWIG_BIAS = 3;
var CORE_HOLD = 16, CORE_RADIUS = 34;
var PV = null;

function screenOf(p, rect) {
  PV.copy(p).applyMatrix4(group.matrixWorld).project(camera);
  return { x: rect.left + (PV.x + 1) / 2 * rect.width, y: rect.top + (1 - PV.y) / 2 * rect.height, z: PV.z };
}

function segDist(px, py, a, b) {
  var dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
  var t = l2 > 0 ? ((px - a.x) * dx + (py - a.y) * dy) / l2 : 0;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  var ex = a.x + t * dx - px, ey = a.y + t * dy - py;
  return Math.sqrt(ex * ex + ey * ey);
}

// A branch's drawn line on the screen, up to its tip as far as it has grown.
function screenLine(r, rect) {
  var last = Math.max(1, Math.min(SEGMENTS, Math.round(r.reveal * SEGMENTS))), out = [];
  for (var i = 0; i <= last; i += 2) out.push(screenOf(r.centres[i], rect));
  if (last % 2) out.push(screenOf(r.centres[last], rect));
  return out;
}

/* What is under a point on the screen, the same way the flat orb answers it:
   every line drawn is a line on the screen with a reach round it - a job's
   or a helper's 14 px, a twig's 9, more at a tip and round a question - and
   the nearest wins, so a twig 1 px wide can still be pointed at. The core
   wins right on top of itself, and is the answer when nothing else is near. */
function orb3dPick(clientX, clientY) {
  if (!O3.on || !canvas) return null;
  var rect = canvas.getBoundingClientRect();
  if (!rect.width) return null;
  group.updateMatrixWorld();
  var core = screenOf(new T.Vector3(), rect);
  var toCore = Math.hypot(core.x - clientX, core.y - clientY);
  var coreAt = Math.max(8, Math.min(CORE_HOLD, coreScreenRadius(rect) * 2.5));
  if (toCore <= coreAt) return 'core';
  /** @type {any} */
  var best = null, bestScore = Infinity;
  REC.forEach(function (r) {
    if (r.reveal <= 0 || !r.mesh.visible) return;
    var line = screenLine(r, rect), twig = r.role === 'twig';
    var reach = twig ? TWIG_RADIUS : LIMB_RADIUS, tipReach = r.waiting ? WAIT_RADIUS : twig ? TWIG_TIP_RADIUS : TIP_RADIUS;
    for (var i = 1; i < line.length; i++) {
      var d = segDist(clientX, clientY, line[i - 1], line[i]);
      var limit = i === line.length - 1 ? Math.max(reach, Math.hypot(line[i].x - clientX, line[i].y - clientY) < tipReach ? tipReach : reach) : reach;
      if (d >= limit) continue;
      var score = twig ? d - TWIG_BIAS : d;
      if (score < bestScore) { bestScore = score; best = r; }
    }
  });
  if (best) return best.node;
  return toCore < CORE_RADIUS ? 'core' : null;
}

function coreScreenRadius(rect) {
  var a = screenOf(new T.Vector3(), rect), b = screenOf(new T.Vector3(coreRadius, 0, 0).applyMatrix4(new T.Matrix4().copy(group.matrixWorld).invert()), rect);
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/* For the checks, which point with a real mouse the way a person does: each
   piece drawn, with a point on it where a pointer gets that piece and no
   other, and where it starts and ends. */
function orb3dPoints() {
  var out = { nodes: [], core: null };
  if (!O3.on || !canvas) return out;
  var rect = canvas.getBoundingClientRect();
  group.updateMatrixWorld();
  var core = screenOf(new T.Vector3(), rect);
  out.core = { x: core.x, y: core.y };
  REC.forEach(function (r) {
    if (r.reveal <= 0) return;
    var line = screenLine(r, rect), at = null;
    var tries = [0.55, 0.45, 0.65, 0.35, 0.75, 0.25, 0.85, 0.92];
    for (var i = 0; i < tries.length && !at; i++) {
      var p = line[Math.min(line.length - 1, Math.round(tries[i] * (line.length - 1)))];
      var seen = p.x > rect.left + 24 && p.x < rect.right - 24 && p.y > rect.top + 24 && p.y < rect.bottom - 24;
      if (seen && orb3dPick(p.x, p.y) === r.node) at = p;
    }
    var n = r.node, b = line[0], tip = line[line.length - 1];
    out.nodes.push({ id: n.id, kind: n.kind, label: n.label, parent: n.parent, state: n.state,
                     colour: r.key, life: r.life ? r.life.state : (r.waiting ? 'waiting' : 'running'),
                     x: at ? at.x : tip.x, y: at ? at.y : tip.y, reachable: !!at,
                     bx: b.x, by: b.y, tx: tip.x, ty: tip.y,
                     alpha: Math.round(r.mat.opacity / RULES.glass.alpha * 100) / 100, ghost: !!n.fade });
  });
  return out;
}

/* ------------------------------------------------------------- starting */

// Whether this browser can draw in WebGL at all, without keeping a context.
function webglThere() {
  try {
    var q = new URLSearchParams(location.search).get('orb');
    if (q === '2d') return false;
    var c = document.createElement('canvas');
    var gl = c.getContext('webgl2') || c.getContext('webgl');
    if (!gl) return false;
    var lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
    return true;
  } catch (e) {
    return false;
  }
}

function makeCore() {
  var G = RULES.glass, C = RULES.core;
  coreRadius = C.radius;
  var white = new T.Color(1, 1, 1);
  coreSphere = new T.Mesh(new T.SphereGeometry(C.radius, 32, 16), glass(white, 'core', null));
  coreSphere.name = 'core_sphere';
  coreSphere.renderOrder = 5;
  // The P, small and wholly inside the sphere: seen only with Core glow at
  // nothing, or from very close.
  var h = C.letterHeight, s = new T.Shape(), hole = new T.Path();
  s.moveTo(-0.35, -0.5); s.lineTo(-0.12, -0.5); s.lineTo(-0.12, -0.04); s.lineTo(0.06, -0.04);
  s.absarc(0.06, 0.23, 0.27, -Math.PI / 2, Math.PI / 2, false); s.lineTo(-0.35, 0.5); s.lineTo(-0.35, -0.5);
  hole.moveTo(-0.12, 0.13); hole.lineTo(0.06, 0.13); hole.absarc(0.06, 0.23, 0.1, -Math.PI / 2, Math.PI / 2, false);
  hole.lineTo(-0.12, 0.33); hole.lineTo(-0.12, 0.13);
  s.holes.push(hole);
  var lg = new T.ExtrudeGeometry(s, { depth: 0.2, bevelEnabled: false, curveSegments: 10 });
  lg.center();
  lg.scale(h, h, h);
  coreLetter = new T.Mesh(lg, glass(white, 'core', null));
  coreLetter.name = 'core_easter_egg_P';
  coreLetter.material.depthWrite = true;
  coreLetter.renderOrder = 4;
  group.add(coreSphere); group.add(coreLetter);
  // The core's own halo, separate from the branches' bloom and tied only to
  // Core glow, so the core stays bright with Glow at nothing (round 10).
  var c = document.createElement('canvas');
  c.width = c.height = 128;
  var g = c.getContext('2d'), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  [[0, 1], [0.12, 0.95], [0.25, 0.55], [0.45, 0.16], [0.7, 0.025], [1, 0]].forEach(function (s2) {
    grad.addColorStop(s2[0], 'rgba(255,255,255,' + s2[1] + ')');
  });
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  coreHalo = new T.Sprite(new T.SpriteMaterial({ map: new T.CanvasTexture(c), transparent: true, depthWrite: false,
                                                  depthTest: false, toneMapped: false }));
  coreHalo.name = 'core_independent_halo';
  coreHalo.renderOrder = 10;
  scene.add(coreHalo);
  coreMask = new T.MeshBasicMaterial({ color: 0, depthWrite: true });
}

function voidColour() {
  var v = getComputedStyle(document.documentElement).getPropertyValue('--void').trim() || '#000000';
  var c = new T.Color();
  try { c.setStyle(v, T.LinearSRGBColorSpace); } catch (e) { c.setRGB(0, 0, 0); }
  return c;
}

/* Start the 3D orb on `cv`, a canvas of its own in the orb's box. Resolves
   true once it is drawing; false, with the reason in O3.failed, when this
   browser cannot, and then nothing of it is left running. */
async function orb3dStart(cv, hooks) {
  if (O3.on) return true;
  if (!webglThere()) { O3.failed = 'This browser has no WebGL.'; return false; }
  try {
    var got = await Promise.all([
      import('three'),
      import('three/addons/controls/OrbitControls.js'),
      import('three/addons/postprocessing/EffectComposer.js'),
      import('three/addons/postprocessing/RenderPass.js'),
      import('three/addons/postprocessing/UnrealBloomPass.js'),
      import('three/addons/postprocessing/Pass.js'),
      fetch('orb-branching.json').then(function (r) {
        if (!r.ok) throw new Error('the orb\'s branching rules answered ' + r.status);
        return r.json();
      })
    ]);
    T = got[0];
    RULES = got[6];
    DEFAULTS = RULES.defaults; LIMITS = RULES.limits;
    loadPrefs();
    O3.kindOf = hooks.kindOf;
    slowMo = !!hooks.slowMo;
    canvas = cv; host = hooks.host;
    renderer = new T.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: 'low-power' });
    // Lighting stays physical; every surface maps itself to display
    // brightness in its own shader, so nothing is tone-mapped twice.
    renderer.toneMapping = T.NoToneMapping;
    renderer.outputColorSpace = T.LinearSRGBColorSpace;
    scene = new T.Scene();
    scene.background = voidColour();
    // A small studio of light cards captured into a filtered cube map: the
    // reflections the glass shows (178-02, round 9).
    var studio = new T.Scene();
    studio.background = new T.Color(0.035, 0.035, 0.035);
    [[[2, 3, 4], [2.2, 4], 8], [[-3, 1, -2], [1.2, 3], 5], [[0, 4, 0], [3, 1], 2]].forEach(function (c) {
      var card = new T.Mesh(new T.PlaneGeometry(c[1][0], c[1][1]),
        new T.MeshBasicMaterial({ color: new T.Color(c[2], c[2], c[2]), side: T.DoubleSide }));
      card.position.fromArray(c[0]); card.lookAt(0, 0, 0); studio.add(card);
    });
    var pmrem = new T.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(studio, 0.04).texture;
    studio.traverse(function (o) { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    pmrem.dispose();
    keyLight = new T.DirectionalLight(0xffffff, prefs.light); keyLight.position.set(2, 3, 4); scene.add(keyLight);
    rimLight = new T.DirectionalLight(0xffffff, 1.5); rimLight.position.set(-3, 1, -2); scene.add(rimLight);
    scene.add(new T.AmbientLight(0xffffff, 0.2));
    camera = new T.PerspectiveCamera(38, 1, 0.001, 50);
    camera.position.set(0, 0, 3.1);
    group = new T.Group();
    scene.add(group);
    GHOST = colourOf('ghost'); WAIT = colourOf('wait');
    DPOS = new T.Vector3(); PV = new T.Vector3();
    makeCore();
    controls = new got[1].OrbitControls(camera, cv);
    controls.enableDamping = true;
    controls.enabled = false;
    controls.minDistance = 0.04;
    controls.maxDistance = 8;
    controls.addEventListener('change', function () { dirty = true; });
    controls.addEventListener('start', function () { viewTween = null; userMoved = true; });
    composer = new got[2].EffectComposer(renderer);
    composer.renderTarget1.samples = 0; composer.renderTarget2.samples = 0;
    composer.addPass(new got[3].RenderPass(scene, camera));
    bloom = new got[4].UnrealBloomPass(new T.Vector2(1, 1), prefs.glow, 0.35, 0.12);
    // Bloom without a brightness cutoff, from the branches' faded display
    // values, so a fade dims their glow too (round 10).
    bloom.threshold = 0;
    bloom.highPassUniforms.smoothWidth.value = 0.00001;
    composer.addPass(bloom);
    composer.renderToScreen = false;
    baseTarget = new T.WebGLRenderTarget(1, 1, { type: T.HalfFloatType, samples: 4 });
    finalQuad = new got[5].FullScreenQuad(new T.ShaderMaterial({
      uniforms: { base: { value: baseTarget.texture }, soft: { value: null } },
      vertexShader: 'varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}',
      fragmentShader: 'uniform sampler2D base;uniform sampler2D soft;varying vec2 vUv;' +
        'void main(){gl_FragColor=vec4(texture2D(base,vUv).rgb+texture2D(soft,vUv).rgb,1.);}',
      depthTest: false, depthWrite: false, toneMapped: false
    }));
    labels = document.createElement('div');
    labels.className = 'orb3d-labels';
    labels.setAttribute('aria-hidden', 'true');
    cv.insertAdjacentElement('afterend', labels);
    cv.addEventListener('webglcontextlost', function (e) {
      e.preventDefault();
      O3.on = false;
      O3.failed = 'The graphics context was lost.';
      if (hooks.onLost) hooks.onLost();
    });
    applyPrefs();
    O3.on = true;
    dirty = true;
    return true;
  } catch (err) {
    O3.failed = (err && err.message) || String(err);
    try { if (renderer) renderer.dispose(); } catch (e) {}
    O3.on = false;
    return false;
  }
}

function applyPrefs() {
  if (!scene) return;
  edgeUniform.value = prefs.edge;
  if (keyLight) keyLight.intensity = prefs.light;
  if (bloom) bloom.strength = prefs.glow;
  scene.traverse(function (o) {
    if (!o.isMesh || !o.material || !o.material.isMeshPhysicalMaterial) return;
    var m = o.material;
    m.envMapIntensity = prefs.reflections;
    m.specularIntensity = prefs.reflections;
    m.clearcoat = prefs.reflections === 0 ? 0 : 1;
  });
  dirty = true;
}

/* ------------------------------------------------------- the tuning panel

   178-02's controls, behind the cog of the open orb: closed until pressed,
   each with its own way back to the default, remembered in this browser.
   Built into the panel app/orb_panel.js opens, in its rows and its words. */

/** @type {Array<[string, Array<string[]>]>} */
var PANEL = [
  ['Look', [
    ['glow', 'Glow', 'Soft light around branches. The core has its own glow.', ''],
    ['coreGlow', 'Core glow', 'The white centre light and its halo, even with Glow at zero.', ''],
    ['edge', 'Edge glow', 'Strength of the coloured light along tube edges.', '×'],
    ['reflections', 'Reflections', 'Strength of the studio reflections and glossy highlights.', '×'],
    ['light', 'Light', 'Strength of the key light facing the tubes.', '×'],
    ['thickness', 'Thickness', 'Widen or narrow the tubes without moving their path.', '×'],
    ['nerve', 'Inside nerve', 'The glowing line down the middle of each tube.', 'toggle']
  ]],
  ['Growth', [
    ['speed', 'Growth speed', 'How quickly new branches grow along their curves.', '×']
  ]],
  ['Finished work', [
    ['endLevel', 'Fade to', 'Brightness of the whole branch at the end of the fade.', '%'],
    ['fadeSeconds', 'Fade time', 'Seconds to fade smoothly from 100% to that level.', 's'],
    ['blinkRate', 'Blinks per second', 'Brief flashes each second while it fades.', '/s'],
    ['blinkLength', 'Blink length', 'How long each flash lasts.', 'ms'],
    ['blinkDirection', 'Blink', 'Flash up to full, or down to nothing.', 'choice'],
    ['holdMinutes', 'Stay before going grey', 'Minutes held steady at that level, without blinking.', 'min'],
    ['ghostSeconds', 'Grey trace time', 'Seconds the grey trace stays before it goes.', 's']
  ]]
];

function moved(key) { return prefs[key] !== DEFAULTS[key]; }

function valueWords(key, unit) {
  var v = prefs[key];
  if (unit === 'choice') return v === 'down' ? 'down' : 'up';
  if (unit === 'toggle') return v ? 'on' : 'off';
  var s = v === Math.round(v) ? String(v) : v.toFixed(2).replace(/0$/, '');
  return unit ? s + (unit === '%' || unit === '×' || unit === '/s' ? '' : ' ') + unit : s;
}

function setPref(key, value, panelHost) {
  prefs[key] = value;
  prefs = validPrefs(prefs);
  applyPrefs();
  savePrefs();
  markRow(key, panelHost);
}

function markRow(key, panelHost) {
  var row = panelHost && panelHost.querySelector('[data-orb-row="' + key + '"]');
  if (!row) return;
  /** @type {any} */
  var spec = null;
  PANEL.forEach(function (g) { g[1].forEach(function (r) { if (r[0] === key) spec = r; }); });
  var v = row.querySelector('.v'), back = row.querySelector('.orb-back'), input = row.querySelector('input, select');
  if (v) v.textContent = valueWords(key, spec[3]);
  if (back) back.hidden = !moved(key);
  row.classList.toggle('moved', moved(key));
  if (input) {
    if (input.type === 'checkbox') input.checked = !!prefs[key];
    else if (String(input.value) !== String(prefs[key])) input.value = prefs[key];
  }
  var group2 = row.closest('[data-orb-group]');
  if (group2) {
    var gb = group2.querySelector('.orb-back-group');
    if (gb) gb.hidden = !group2.querySelector('.row.moved');
  }
  var all = document.getElementById('orbResetAll');
  if (all) {
    var count = 0;
    for (var k in DEFAULTS) if (moved(k)) count++;
    all.hidden = !count;
    all.lastChild.textContent = count === 1 ? '1 changed' : count + ' changed';
  }
}

function el(tag, cls, text) {
  var e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function orb3dPanelPaint(panelHost) {
  panelHost.innerHTML = '';
  PANEL.forEach(function (grp) {
    var box = el('div', 'orb-grp');
    box.setAttribute('data-orb-group', grp[0]);
    var head = el('div', 'orb-grp-head');
    head.appendChild(el('span', null, grp[0].toUpperCase()));
    var gb = el('button', 'orb-back-group', 'put back');
    gb.type = 'button';
    gb.title = 'Put every setting in this group back to its default';
    gb.hidden = !grp[1].some(function (r) { return moved(r[0]); });
    gb.addEventListener('click', function () { orb3dPutBack(grp[1].map(function (r) { return r[0]; }), panelHost); });
    head.appendChild(gb);
    box.appendChild(head);
    grp[1].forEach(function (spec) { box.appendChild(panelRow(spec, panelHost)); });
    panelHost.appendChild(box);
  });
  var view = el('div', 'orb-grp');
  view.setAttribute('data-orb-group', 'View');
  var vh = el('div', 'orb-grp-head');
  vh.appendChild(el('span', null, 'VIEW'));
  view.appendChild(vh);
  var rc = el('button', 'orb3d-recenter', 'Recenter');
  rc.type = 'button';
  rc.id = 'orb3dRecenter';
  rc.title = 'Turn and zoom back to the whole orb (R, or a double click on empty space)';
  rc.addEventListener('click', recenter);
  view.appendChild(rc);
  panelHost.appendChild(view);
  var all = document.getElementById('orbResetAll');
  if (all) {
    var count = 0;
    for (var k in DEFAULTS) if (moved(k)) count++;
    all.hidden = !count;
    all.lastChild.textContent = count === 1 ? '1 changed' : count + ' changed';
  }
}

function panelRow(spec, panelHost) {
  var key = spec[0], unit = spec[3];
  var row = el('div', 'row');
  row.setAttribute('data-orb-row', key);
  row.classList.toggle('moved', moved(key));
  var head = el('div', 'rowHead');
  var name = el('label', null, spec[1]);
  name.setAttribute('for', 'orb3dS-' + key);
  head.appendChild(name);
  var back = el('button', 'orb-back', '↺');
  back.type = 'button';
  back.hidden = !moved(key);
  back.title = 'Put "' + spec[1] + '" back to ' + valueWords(key, unit).replace(String(prefs[key]), String(DEFAULTS[key]));
  back.setAttribute('aria-label', 'Reset ' + spec[1].toLowerCase());
  back.addEventListener('click', function () { setPref(key, DEFAULTS[key], panelHost); });
  head.appendChild(back);
  head.appendChild(el('span', 'v', valueWords(key, unit)));
  row.appendChild(head);
  var input;
  if (unit === 'toggle') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!prefs[key];
    input.addEventListener('change', function () { setPref(key, input.checked, panelHost); });
  } else if (unit === 'choice') {
    input = document.createElement('select');
    input.innerHTML = '<option value="up">Flash up to 100%</option><option value="down">Flash down to 0%</option>';
    input.value = prefs[key];
    input.addEventListener('change', function () { setPref(key, input.value, panelHost); });
  } else {
    var lim = LIMITS[key];
    input = document.createElement('input');
    input.type = 'range';
    input.min = lim[0]; input.max = lim[1]; input.step = lim[2];
    input.value = prefs[key];
    input.addEventListener('input', function () { setPref(key, parseFloat(input.value), panelHost); });
  }
  input.id = 'orb3dS-' + key;
  input.setAttribute('aria-describedby', 'orb3dH-' + key);
  row.appendChild(input);
  var help = el('p', 'orb3d-help', spec[2]);
  help.id = 'orb3dH-' + key;
  row.appendChild(help);
  return row;
}

function orb3dPutBack(keys, panelHost) {
  for (var i = 0; i < keys.length; i++) prefs[keys[i]] = DEFAULTS[keys[i]];
  applyPrefs();
  savePrefs();
  if (panelHost) orb3dPanelPaint(panelHost);
}

function orb3dPutBackAll(panelHost) { orb3dPutBack(Object.keys(DEFAULTS), panelHost); }

function orb3dDump() {
  return JSON.stringify(prefs, null, 1);
}

export { O3, orb3dDump, orb3dFrame, orb3dKeeps, orb3dPanelPaint, orb3dPick, orb3dPoints, orb3dPutBackAll,
  orb3dStart, recenter as orb3dRecenter };
