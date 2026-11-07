/* Rouh's page: the state more than one module writes.
 *
 * A module may read another's variables through its exports, which stay live,
 * but may not assign to them: an imported binding is read-only. These are the
 * variables that more than one module assigns, so they are fields of one
 * object here instead, written as `shared.<name>`. Each module that declared one
 * still sets it to its starting value at the moment it always did, where the
 * variable used to be declared; the values below are the same ones.
 */
export const shared = {
  askedTreeAt: 0, // orb.js
  orbSizedAt: -1e9, // orb.js: when the orb's canvas was last measured
  stick: true, // transcript.js
  foldMoved: 0, // transcript.js
  VERSIONS: {}, // transcript.js
  RETRY: null, // transcript.js
  TYPED_ANSWER: null, // cards.js
  THREAD_ASKED: '', // runs.js
  TASK_CHAT_ASKED: '', // runs.js
  LEFT_UP: 0, // runs.js
  attached: [], // attachments.js
  /** @type {boolean | 'fork'} Send pressed while an upload was going: true, or 'fork' for Fork. */
  sendWhenUploaded: false, // attachments.js
};
