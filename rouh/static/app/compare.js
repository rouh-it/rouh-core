/* A blind comparison under an answer (`rouh/modelvotes.py`, `model_compare` on the socket).

   Petar, 24 October 2026: with the opt-in on, now and then a second provider's model answers
   the same request after the answer was shown, and a small comparison appears beside it,
   easy to ignore: two answers, A and B, the models' names hidden and the sides shuffled, and
   five choices, A, B, Tie, Neither and Skip. A press is the vote and the card goes; ignoring
   it is Skip, with no reminder and no notice. Nothing of it is kept on the page: a reload
   leaves the answer as it was, and the comparison unanswered, which is Skip. */
import { $, el } from 'app/helpers.js';

var CHOICES = [['a', 'A is better'], ['b', 'B is better'], ['tie', 'Tie'], ['neither', 'Neither'],
               ['skip', 'Skip']];

/** Where a comparison goes: under the last part of the answer it compares, or at the end. */
function placeFor(root) {
  var host = $('transcript');
  if (!host) return null;
  var parts = root ? host.querySelectorAll('.turn.assistant[data-root="' + root + '"]') : [];
  return { host: host, after: parts.length ? parts[parts.length - 1] : null };
}

function vote(card, token, said) {
  card.classList.add('done');
  Array.prototype.forEach.call(card.querySelectorAll('button'), function (b) { b.disabled = true; });
  fetch('/api/models/vote', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: token, vote: said }),
  }).catch(function () {}).then(function () { card.remove(); });
}

/** Draw a comparison the server sent. @param {any} m */
export function compareShow(m) {
  if (!m || !m.token || !m.a || !m.b) return;
  var where = placeFor(m.root);
  if (!where || where.host.querySelector('.compare-card[data-token="' + m.token + '"]')) return;
  var card = el('section', 'compare-card');
  card.setAttribute('data-token', m.token);
  card.setAttribute('aria-label', 'Which answer is better?');
  var head = el('details', 'compare-box');
  var summary = el('summary', null, 'Which answer is better?');
  head.appendChild(summary);
  var sides = el('div', 'compare-sides');
  [['A', m.a], ['B', m.b]].forEach(function (side) {
    var col = el('div', 'compare-side');
    col.appendChild(el('h5', null, side[0]));
    col.appendChild(el('div', 'compare-text', side[1]));
    sides.appendChild(col);
  });
  head.appendChild(sides);
  card.appendChild(head);
  var acts = el('div', 'compare-acts');
  acts.setAttribute('role', 'group');
  acts.setAttribute('aria-label', 'Your vote');
  CHOICES.forEach(function (c) {
    var b = /** @type {HTMLButtonElement} */ (el('button', 'ctl small compare-vote', c[1]));
    b.type = 'button';
    b.setAttribute('data-vote', c[0]);
    b.addEventListener('click', function () { vote(card, m.token, c[0]); });
    acts.appendChild(b);
  });
  card.appendChild(acts);
  if (where.after && where.after.parentNode) where.after.parentNode.insertBefore(card, where.after.nextSibling);
  else where.host.appendChild(card);
}
