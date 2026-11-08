// The lines under a new password, ticked off as the person types it.
//
// On the invitation's form (`join.html`) and the forgotten-password one
// (`reset.html`). The lines are the server's own rules, the validators
// `rouh/password_rules.py` reads out of the settings, and each is judged here
// exactly as Django judges it, so that when every line is green the server
// takes the password: the same length count, the same likeness to the person's
// name and address (difflib's quick_ratio), the same common-password list. The
// server still checks all of it again; this is only so nobody has to guess.
//
// Nothing the person types leaves the page while they type it. The one list
// the page cannot know, Django's twenty thousand common passwords, is fetched
// once; if it will not come, that line is left unticked and the server judges.
//
// It also takes over the form's own "this is missing" for the names on the
// invitation, so the words under an empty box say which box it is.
(function () {
  'use strict';

  var form = document.getElementById('passwordForm');
  var list = document.getElementById('passwordRules');
  var data = document.getElementById('passwordRulesData');
  if (!form || !list || !data) return;
  var DATA = JSON.parse(data.textContent || '{}');
  var RULES = DATA.rules || [];
  var one = form.elements.password1;
  var two = form.elements.password2;
  var names = Array.prototype.filter.call(form.querySelectorAll('input[data-name]'),
                                          function (input) { return input.required; });
  var lines = list.querySelectorAll('li[data-rule]');

  // null while the list is on its way, false if it never came.
  var common = null;

  // Python's str.strip(): its whitespace is not quite JavaScript's.
  var ENDS = /^[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
  function strip(s) { return s.replace(ENDS, ''); }

  // Python counts characters, not UTF-16 halves.
  function chars(s) { return Array.from(s); }

  // difflib.SequenceMatcher(a=a, b=b).quick_ratio(), which is what Django's
  // UserAttributeSimilarityValidator compares with its max_similarity.
  function quickRatio(a, b) {
    var A = chars(a), B = chars(b), full = new Map(), avail = new Map(), matches = 0;
    B.forEach(function (c) { full.set(c, (full.get(c) || 0) + 1); });
    A.forEach(function (c) {
      var n = avail.has(c) ? avail.get(c) : (full.get(c) || 0);
      avail.set(c, n - 1);
      if (n > 0) matches += 1;
    });
    var length = A.length + B.length;
    return length ? 2 * matches / length : 1;
  }

  // Django's exceeds_maximum_length_ratio: a part so much shorter than the
  // password that it cannot be too like it, and is not compared at all.
  function tooShortToMatter(password, most, part) {
    var p = chars(password).length, v = chars(part).length;
    return p >= 10 * v && v < most / 2 * p;
  }

  function person() {
    var who = Object.assign({}, DATA.person || {});
    names.forEach(function (input) { who[input.name] = input.value; });
    return who;
  }

  function tooLike(pw, rule) {
    var password = pw.toLowerCase(), who = person();
    return rule.attributes.some(function (attribute) {
      var value = who[attribute];
      if (!value || typeof value !== 'string') return false;
      var lower = value.toLowerCase();
      // re.split(r"\W+", value) and the whole value too, as Django does.
      return lower.split(/[^\p{L}\p{N}_]+/u).concat([lower]).some(function (part) {
        return !tooShortToMatter(password, rule.max, part) &&
          quickRatio(password, part) >= rule.max;
      });
    });
  }

  // true: met. false: not yet. null: this page cannot tell, the server will.
  function judge(rule) {
    var pw = one.value;
    if (rule.kind === 'same') return pw !== '' && pw === two.value;
    if (!pw) return false;
    if (rule.kind === 'length') return chars(pw).length >= rule.min;
    // Python's str.isalpha(), str.isnumeric() and "not str.isalnum()", one character at a time.
    if (rule.kind === 'letter') return /\p{L}/u.test(pw);
    if (rule.kind === 'number') return /\p{N}/u.test(pw);
    if (rule.kind === 'symbol') return /[^\p{L}\p{N}]/u.test(pw);
    if (rule.kind === 'similar') return !tooLike(pw, rule);
    if (rule.kind === 'common') {
      return common instanceof Set ? !common.has(strip(pw.toLowerCase())) : common === null ? false : null;
    }
    return null;
  }

  function update() {
    var unmet = [];
    RULES.forEach(function (rule, i) {
      var met = judge(rule), line = lines[i];
      if (!line) return;
      line.classList.toggle('met', met === true);
      line.classList.toggle('open', met === false);
      line.querySelector('.sr').textContent = met === true ? ', done' : ', not yet';
      if (met === false) unmet.push(rule);
    });
    if (!unmet.length) form.classList.remove('tried');
    return unmet;
  }

  function missing(input, show) {
    var said = document.getElementById(input.id + 'Missing');
    if (said) said.hidden = !show;
    if (show) {
      input.setAttribute('aria-invalid', 'true');
      if (said) input.setAttribute('aria-describedby', said.id);
    } else {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    }
  }

  // The form's checks are this script's now, so the words under an empty
  // name say which one it is. Without the script the browser's own still run.
  form.noValidate = true;
  form.addEventListener('submit', function (event) {
    var first = null;
    names.forEach(function (input) {
      var empty = !input.value.trim();
      missing(input, empty);
      if (empty && !first) first = input;
    });
    var unmet = update();
    if (unmet.length) {
      form.classList.add('tried');
      var onlySame = unmet.length === 1 && unmet[0].kind === 'same';
      if (!first) first = onlySame && one.value ? two : one;
    }
    if (first) {
      event.preventDefault();
      first.focus();
    }
  });
  names.forEach(function (input) {
    input.addEventListener('input', function () {
      if (input.value.trim()) missing(input, false);
      update();
    });
  });
  one.addEventListener('input', update);
  two.addEventListener('input', update);

  if (RULES.some(function (rule) { return rule.kind === 'common'; })) {
    fetch(DATA.common, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (text) { common = new Set(text.split('\n')); })
      .catch(function () { common = false; })
      .then(update);
  }
  update();
})();
