/*
 * Rouh browser client.
 *
 * One WebSocket carries everything. Text frames are JSON, binary frames are audio:
 * 16000 Hz PCM16 going up, 24000 Hz PCM16 coming down.
 *
 * This file was the whole of it, one function of 36,000 lines, until
 * 5 October 2026. It is native ES modules now, one per section it had, in
 * rouh/static/app/, loaded with no build step: the browser fetches each module
 * itself, at the address the import map in index.html gives it, which carries
 * a hash of that module's own content (rouh/web/assets.py). A deploy that
 * changes one module downloads that one module again and nothing else.
 *
 * The modules, in the order they run:
 *
 *   app/helpers.js      1   small helpers
 *   app/settings.js     2   settings
 *   app/socket.js       4   the socket, with reconnection
 *   app/voice.js        5   the voice detector, and the one place the microphone
 *                           is opened
 *   app/playback.js     6   playback scheduler
 *   app/orb.js          7   the orb
 *   app/transcript.js   8   transcript
 *   app/cards.js        9   cards
 *   app/tasks.js       10   tasks, and one of Rouh's own jobs on the canvas (10a)
 *   app/runs.js        10b  the one program's runs, opened on the canvas; the
 *                           Start box; your workspace's tasks
 *   app/chats.js       10c  the chats: the list in the middle column, the
 *                           projects, which one you are talking in
 *   app/search.js      10d  search, over all five: the box over everything, the
 *                           pills, the rows and what each row's menu does
 *   app/address.js     10f  the address of what is on the screen, and the front
 *                      10g  door
 *   app/welcome.js          an empty conversation says hello
 *   app/controls.js    11   controls, composer, the speakers
 *   app/attachments.js 11c  files attached to a message: the paperclip, the drop
 *                           zone, paste
 *   app/gene_therapy.js 12  Gene therapy: the drawer on the right, and the board it
 *                           opens; and window.__rouh, what the tests reach
 *   app/shared.js           the variables more than one module assigns
 *   app/stars.js            a falling star across the navigation now and
 *                           then; it needs nothing from the others, so it
 *                           stands outside the chain and is imported here
 *   app/notices.js          notifications: dropped in at the top, stacked,
 *                           swiped, and under the bell. app/socket.js hands
 *                           it the server's list, so it runs just before the
 *                           socket; its top level only wires its own buttons,
 *                           so it needs nothing of the others when it runs
 *   app/offline.js          Rouh offline: this device's copy, the outbox, the
 *                           pill that says which. Imported by app/socket.js
 *                           first, so it runs just after the settings
 *   app/offlineview.js      the Offline page, at /offline; outside the chain
 *                           and imported here, so everything it calls
 *                           has run
 *   app/demo.js             demo mode: the switch beside the house, the grey bars, the
 *                           purple dots (`rouh/demo.py`); imports nothing, and
 *                           app/socket.js hands it the server's `demo` message
 *   app/focus.js            today's focus at the top of the navigation, from
 *                           the morning brief's one thing; outside the chain,
 *                           and needs only app/helpers.js
 *   app/composer_extras.js  the voice button and Cheap, Smart or Auto on the
 *                           composer's line; outside the chain, and needs
 *                           app/chats.js, app/helpers.js, app/notices.js and
 *                           app/socket.js
 *   app/navgroups.js        the navigation's five group tabs and the links
 *                           drawn from the gene registry (GENES.md);
 *                           outside the chain, and its top level touches
 *                           nothing but the page's own markup
 *
 * Why they run in this order, and how.
 *
 * In the one file, every function could call every other and the code at the
 * top level ran from the first line to the last. Split, the functions are the
 * same - a module's function declarations exist before any module runs, so a
 * call from one module into a later one works exactly as it did - but the top
 * level of each module runs once, when the browser evaluates it, and the
 * browser evaluates a module after the modules it imports. Most of these
 * modules import from later ones as well as earlier ones, so left to itself
 * the browser would run, say, the cards before the socket that the cards'
 * top level expects to exist.
 *
 * So each module's first import is the module before it in the list above,
 * and this file imports only the last. Evaluation goes down that chain to
 * app/helpers.js before anything runs; every import of a later module on the
 * way is an import of a module already being evaluated, which the browser
 * skips; and then the modules run on the way back up, 1, 2, 3 ... 12 - the
 * order the one file ran in. Adding a module means putting it in that chain:
 * import the module before it first, and have the module after it import it.
 *
 * Every specifier is `app/<name>.js`, a bare name the import map in
 * index.html points at the module's hashed address, and tsconfig.json points
 * at the file, so the type checker reads the same graph the browser does
 * (tools/typecheck says how to run it).
 */
import 'app/gene_therapy.js';
import 'app/stars.js';
import 'app/notices.js';
import 'app/offlineview.js';
import 'app/navgroups.js';
import 'app/demo.js';
import 'app/focus.js';
import 'app/composer_extras.js';
import { addrEarly } from 'app/address.js';

// A page opened at the task browser opens it now, once every module above
// has run and before the socket has said anything (`addrEarly`).
addrEarly();
