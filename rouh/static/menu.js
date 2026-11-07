/* The menu behind three dots, and there is one kind of it.

   Petar, 24 September 2026, looking at a chat's three dots: "The three-dot
   menu does not have Delete on a chat, and it should have Delete. Also, where
   it says 'Move that chat,' it should say 'Move' ... They should have an icon
   for visual recognition. 'Delete' should be separated by a horizontal line,
   with red letters and a red hover that turns the letters white. And make that
   three-dot pop-up menu universal around. I should see it as a universal
   interface everywhere for chats, for everything."

   So every menu that drops out of something - the three dots on a chat, on a
   row of the sidebar, on a run, on a search result, on a project's page, the
   task browser's menu on a project, and the menu behind the person's own
   name - is this one: the same box, the same rows, a small icon in front of a
   short word, and whatever cannot be undone last, under a rule, in red.
   `menu.css` beside this file is how it looks, and this is what it does.

   It is one file for Rouh's page and for the pages Rouh draws in a frame
   (`objectindex._shell` puts it into those, the way it puts their own script
   in), so an icon is drawn once, here, and a bin is the same bin everywhere.

   What each menu holds and what each item does stays with the menu: a menu
   of the sidebar's rows is moved to whichever row asked for it, the search's
   is driven from the keyboard by numbers, a chat's hangs off the one pair of
   dots it has. What they share is here:

     dress(root)        every `.menu-item[data-icon]` under `root` given its
                        icon and its name, once
     label(item, text)  the words on an item, leaving its icon alone
     icon(item, name)   another icon on an item: a pin, and a pin struck out
     keys(menu, e)      the arrow keys, Home and End, between the items that
                        can be pressed
     first(menu)        the focus on the first of those
     place(menu, anchor, align)
                        against the thing that opened it, fixed to the window,
                        and back onto the screen when there is no room
     bind(button, menu, opts)
                        a menu that belongs to one button: the press opens it
                        and a second press closes it, and so do a press
                        anywhere else, Escape, Tab and choosing an item

   The markup of an item is a button with its words in it and the name of its
   icon on it:

     <button class="menu-item" type="button" role="menuitem"
             data-icon="rename">Rename</button>
     <hr class="menu-rule">
     <button class="menu-item danger" type="button" role="menuitem"
             data-icon="delete">Delete</button>

   and `dress` turns it into the icon and a `.menu-name` holding the words.
   Anything already in the button after the words - a key to press, an arrow
   for a list that opens beside it - is left where it is, at the end. */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  /* The icons, on a 24 pixel grid, drawn in the colour of the item's words.
     Outlines rather than solid shapes, because they sit in front of words and
     a solid shape is louder than the word it is there to help find. */
  var ICONS = {
    // Rename, and Edit, which is the name and more: a pencil.
    rename: '<path d="M4 20l1-4L16 5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/>',
    // Delete: a bin.
    'delete': '<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'
      + '<path d="M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12"/>'
      + '<path d="M10 11v5M14 11v5"/>',
    // Move: a folder with an arrow going into it.
    move: '<path d="M3.5 7.5v10A1.5 1.5 0 0 0 5 19h14a1.5 1.5 0 0 0 1.5-1.5V9A1.5 1.5 0 0 0 19 7.5h-7L10 5H5'
      + 'A1.5 1.5 0 0 0 3.5 6.5z"/><path d="M8.5 13.25h7M13 10.75l2.5 2.5-2.5 2.5"/>',
    // Out of the project it is in: the same folder, emptied.
    unproject: '<path d="M3.5 7.5v10A1.5 1.5 0 0 0 5 19h14a1.5 1.5 0 0 0 1.5-1.5V9A1.5 1.5 0 0 0 19 7.5h-7L10 5H5'
      + 'A1.5 1.5 0 0 0 3.5 6.5z"/><path d="M9 13.25h6"/>',
    pin: '<path d="M9 3.5h6"/><path d="M10 3.5V9l-3 3v1.5h10V12l-3-3V3.5"/><path d="M12 13.5v7"/>',
    unpin: '<path d="M9 3.5h6"/><path d="M10 3.5V9l-3 3v1.5h10V12l-3-3V3.5"/><path d="M12 13.5v7"/>'
      + '<path d="M4 4l16 16"/>',
    // Every chat and task: a list.
    list: '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><circle cx="4.75" cy="6.5" r=".9" fill="currentColor"/>'
      + '<circle cx="4.75" cy="12" r=".9" fill="currentColor"/><circle cx="4.75" cy="17.5" r=".9" fill="currentColor"/>',
    // A chat made a numbered task: a box with a tick in it.
    task: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 12.2l2.4 2.4 4.8-5"/>',
    // A subtask promoted to a task of its own: an arrow up to a line.
    promote: '<path d="M12 20V8"/><path d="M7 13l5-5 5 5"/><path d="M5 4h14"/>',
    // A subtask moved into a new task: a box with a plus in it.
    newtask: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8.5v7M8.5 12h7"/>',
    // Every card a chat drew, side by side.
    cards: '<rect x="3.5" y="5" width="7.5" height="14" rx="1.5"/><rect x="13" y="5" width="7.5" height="14" rx="1.5"/>',
    // What one thing owns: a thing with two things hanging under it.
    under: '<rect x="3.5" y="3" width="6" height="4" rx="1"/><path d="M6.5 7v10.5h5M6.5 11.5h5"/>'
      + '<rect x="11.5" y="9.5" width="8" height="4" rx="1"/><rect x="11.5" y="15.5" width="8" height="4" rx="1"/>',
    // Open: the same return arrow the search's own open button wears.
    open: '<path d="M19 5v6a3 3 0 0 1-3 3H6"/><path d="M9.5 10.5L6 14l3.5 3.5"/>',
    // Somewhere else: out of a box.
    tab: '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5L11 13"/>'
      + '<path d="M17.5 14v4a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 18V8A1.5 1.5 0 0 1 6 6.5h4"/>',
    // From one side to the other.
    swap: '<path d="M4 8h14.5M15 4.5L18.5 8 15 11.5"/><path d="M20 16H5.5M9 12.5L5.5 16 9 19.5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
      + 'a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.9 19a1.7 1.7 0 0 0-1.9.3'
      + 'l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.9'
      + 'a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0'
      + 'v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9'
      + 'a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    memory: '<path d="M6 3.5h9.5L19 7v13.5H6z"/><path d="M9.5 11h6M9.5 14.5h6M9.5 18h3.5"/>',
    signout: '<path d="M15 17l5-5-5-5"/><path d="M20 12H9"/><path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6"/>',
    offline: '<path d="M7 18h10a4 4 0 0 0 .7-7.9A6 6 0 0 0 6.2 9.3 4.4 4.4 0 0 0 7 18z"/><path d="M12 10.5v5M9.8 13.4 12 15.6l2.2-2.2"/>'
  };
  // Reminders (`rouh/reminders.py`): hold one, and let it go on.
  // A page as a printable PDF (`rouh/page_pdf.py`): a sheet, and the PDF kept beside it to save.
  ICONS.pdf = '<path d="M6 3.5h8.5L18.5 7.5v13H6z"/><path d="M14 3.5v4.5h4.5"/><path d="M9 12.5h6M9 16h6"/>';
  // Share (fr_167c36b97e6e): a box with an arrow going up out of it, the
  // share sign every phone uses, and the one on the canvas bar's own button.
  ICONS.share = '<path d="M8.5 9.5H7a2 2 0 0 0-2 2V19a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7.5a2 2 0 0 0-2-2h-1.5"/>'
    + '<path d="M12 14.5V3"/><path d="M8.5 6.5 12 3l3.5 3.5"/>';
  // A Google Doc of this page (`rouh/page_gdoc.py`): a document with its lines and a fold.
  ICONS.gdoc = '<path d="M6 3.5h8.5L18.5 7.5v13H6z"/><path d="M14 3.5v4.5h4.5"/><path d="M9 11.5h6M9 14.5h6M9 17.5h4"/>';
  ICONS.download = '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>';
  ICONS.pause = '<rect x="6.5" y="5" width="3.5" height="14" rx="1"/><rect x="14" y="5" width="3.5" height="14" rx="1"/>';
  ICONS.resume = '<path d="M7.5 5.5v13l11-6.5z"/>';
  // A goal's own chat (`rouh/goals.py`): a speech bubble, the chats' own.
  // Two people: whose task it is (`rouh/task_origin.py`).
  ICONS.people = '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19.5c.6-3.3 2.8-5.2 5.5-5.2s4.9 1.9 5.5 5.2"/>'
    + '<path d="M15.5 5.2a3 3 0 0 1 0 5.6"/><path d="M17.2 14.6c1.8.6 3 2.3 3.3 4.9"/>';
  // Made by Rouh (`rouh/task_origin.py`): a ring with Rouh's spark in it, as the task
  // browser's Made by Rouh button wears.
  ICONS.rouh = '<circle cx="12" cy="12" r="8"/><path d="M12 7.5l1.3 3.2 3.2 1.3-3.2 1.3-1.3 3.2-1.3-3.2-3.2-1.3 3.2-1.3z"/>';
  ICONS.chat = '<path d="M21 12a8 8 0 0 1-8 8H4l2.2-2.6A8 8 0 1 1 21 12z"/>';
  ICONS.edit = ICONS.rename;
  // History: a clock with its hand going back round.
  ICONS.history = '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3.5 4.5V9H8"/><path d="M12 8v4.5l3 2"/>';
  // Demo mode (`rouh/demo.py`): an eye, what the audience sees.
  ICONS.demo = '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>';
  // Send to the task, from a subtask's chat (`rouh/subtasknotes.py`): up and
  // into the tray above.
  // Unlink: a chain link pulled apart, the break marked at either end
  // (Lucide's "unlink", ISC licence), as on a fork's detach until 4 November 2026.
  ICONS.unlink = '<path d="M18.84 12.25l1.72-1.71a5 5 0 0 0-.12-7.07 5 5 0 0 0-6.95 0l-1.72 1.71"/>'
    + '<path d="M5.17 11.75l-1.71 1.71a5 5 0 0 0 .12 7.07 5 5 0 0 0 6.95 0l1.71-1.71"/>'
    + '<path d="M8 2v3M2 8h3M16 19v3M19 16h3"/>';
  ICONS.up = '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>';
  // A task archived (`rouh/archiving.py`): a box with its lid on; brought
  // back, the same box with an arrow coming up out of it.
  ICONS.archive = '<rect x="3.5" y="4.5" width="17" height="4" rx="1"/><path d="M5 8.5v10a1.5 1.5 0 0 0 1.5 1.5h11'
    + 'a1.5 1.5 0 0 0 1.5-1.5v-10"/><path d="M10 12.5h4"/>';
  ICONS.unarchive = '<rect x="3.5" y="4.5" width="17" height="4" rx="1"/><path d="M5 8.5v10a1.5 1.5 0 0 0 1.5 1.5h11'
    + 'a1.5 1.5 0 0 0 1.5-1.5v-10"/><path d="M12 17.5v-5.5M9.5 14.5L12 12l2.5 2.5"/>';

  function svg(name) {
    var s = document.createElementNS(NS, 'svg');
    s.setAttribute('class', 'menu-ic');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('width', '16');
    s.setAttribute('height', '16');
    s.setAttribute('aria-hidden', 'true');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.7');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.innerHTML = ICONS[name] || '';
    return s;
  }

  /* One item, given its icon and its words' own span. The words are whatever
     text sits directly in the button; an element already in it - a key, an
     arrow, a `.menu-name` somebody wrote out by hand - stays, after them. */
  function dressItem(item) {
    if (!item || item.querySelector(':scope > .menu-ic')) return;
    var name = item.querySelector(':scope > .menu-name');
    if (!name) {
      name = document.createElement('span');
      name.className = 'menu-name';
      var words = '';
      for (var n = item.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3) words += n.nodeValue;
      }
      for (var k = item.childNodes.length - 1; k >= 0; k--) {
        if (item.childNodes[k].nodeType === 3) item.removeChild(item.childNodes[k]);
      }
      name.textContent = words.replace(/\s+/g, ' ').trim();
      item.insertBefore(name, item.firstChild);
    }
    item.insertBefore(svg(item.getAttribute('data-icon') || ''), item.firstChild);
  }

  function dress(root) {
    var all = (root || document).querySelectorAll('.menu-item[data-icon]');
    for (var i = 0; i < all.length; i++) dressItem(all[i]);
  }

  // The words on an item, and nothing else on it touched.
  function label(item, text) {
    if (!item) return;
    dressItem(item);
    var name = item.querySelector(':scope > .menu-name');
    if (name) name.textContent = text;
  }

  // Another icon on an item that has one: Pin, and Un-pin struck through.
  function icon(item, name) {
    if (!item || !ICONS[name]) return;
    item.setAttribute('data-icon', name);
    var was = item.querySelector(':scope > .menu-ic');
    if (was) item.replaceChild(svg(name), was);
    else dressItem(item);
  }

  // What can be pressed, in order: not disabled, and neither it nor anything
  // it is inside, short of the menu, hidden.
  function items(menu) {
    var all = menu ? menu.querySelectorAll('.menu-item') : [], out = [];
    for (var i = 0; i < all.length; i++) {
      if (all[i].disabled) continue;
      var n = all[i];
      while (n && n !== menu && !n.hidden) n = n.parentNode;
      if (n === menu) out.push(all[i]);
    }
    return out;
  }

  function first(menu) {
    var all = items(menu);
    if (all.length) all[0].focus({ preventScroll: true });
  }

  /* The arrow keys, between the items that can be pressed, round from the
     last to the first and back; Home and End to either end. True when the
     key was one of these, so the caller can stop there. */
  function keys(menu, e) {
    if (!menu || menu.hidden) return false;
    var k = e.key;
    if (k !== 'ArrowDown' && k !== 'ArrowUp' && k !== 'Home' && k !== 'End') return false;
    var all = items(menu);
    if (!all.length) return false;
    var at = all.indexOf(document.activeElement);
    var to;
    if (k === 'Home') to = 0;
    else if (k === 'End') to = all.length - 1;
    else if (at < 0) to = k === 'ArrowDown' ? 0 : all.length - 1;
    else to = (at + (k === 'ArrowDown' ? 1 : -1) + all.length) % all.length;
    e.preventDefault();
    all[to].focus({ preventScroll: true });
    return true;
  }

  /* Under the thing that opened it, with one edge lined up with it: its left
     edge for `start`, its right edge for `end`. Above it when there is no room
     below, and never off either side: on a window 320 pixels wide a menu half
     off the edge has an item nobody can press. For a menu fixed to the window;
     false when the anchor is not on the screen at all. */
  function place(menu, anchor, align) {
    if (!menu || !anchor) return false;
    var box = anchor.getBoundingClientRect();
    if (!box.width && !box.height) return false;
    var w = menu.offsetWidth, h = menu.offsetHeight;
    var left = align === 'end' ? box.right - w : box.left;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    var top = box.bottom + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, box.top - h - 4);
    menu.style.left = Math.round(left) + 'px';
    menu.style.top = Math.round(top) + 'px';
    return true;
  }

  /* A menu that belongs to one button, and the whole of what that means.

     The press opens it and the same press again closes it. The focus goes to
     its first item as it opens, so the keyboard can walk it at once; a press
     with the mouse does not light that item up, because the browser only
     draws a focus ring where the keyboard put it. Choosing an item closes it,
     unless the item opens something of its own beside it. So does a press
     anywhere else, Tab, and Escape - which also hands the focus back to the
     button, because that is where the person was before they opened it, and
     does nothing else on the page while it is closing a menu.

     `opts.open` is called just before it is shown, to put this instant's
     words on it (Pin or Un-pin, what is hidden). `opts.align` places it
     against the button when the menu is fixed to the window: `start` or
     `end` for `place`, or a function of its own, given the menu and the
     button, for a menu with somewhere it must never be (the one behind the
     person's name keeps off the orb). Without it the stylesheet has already
     put it where it goes.

     Hands back `show(on)`, for the few places that close it from outside. */
  function bind(button, menu, opts) {
    opts = opts || {};
    if (!button || !menu) return function () {};
    dress(menu);

    function show(on) {
      if (!on) {
        if (menu.hidden) return;
        menu.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        if (opts.close) opts.close();
        return;
      }
      if (opts.open && opts.open() === false) return;
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      align();
    }

    function align() {
      if (typeof opts.align === 'function') opts.align(menu, button);
      else if (opts.align) place(menu, button, opts.align);
    }

    button.addEventListener('click', function (e) {
      if (e.stopPropagation) e.stopPropagation();
      var opening = menu.hidden;
      show(opening);
      if (opening && !menu.hidden) first(menu);
    });
    menu.addEventListener('click', function (e) {
      var item = e.target.closest ? e.target.closest('.menu-item') : null;
      if (!item || item.getAttribute('aria-haspopup')) return;
      show(false);
    });
    menu.addEventListener('keydown', function (e) {
      if (keys(menu, e)) return;
      if (e.key === 'Tab') show(false);
    });
    document.addEventListener('click', function (e) {
      if (menu.hidden) return;
      if (menu.contains(e.target) || button.contains(e.target)) return;
      show(false);
    });
    // Escape closes the menu and nothing else: one press, one layer. It is
    // caught on the way down and stopped there, so the same press does not
    // also climb the canvas a level or close the panel under the menu, and a
    // page in a frame does not also hand it up to Rouh (`pages.keys_script`).
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || menu.hidden) return;
      e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      var inside = menu.contains(document.activeElement);
      show(false);
      if (inside) button.focus();
    }, true);
    if (opts.align) {
      window.addEventListener('resize', function () {
        if (!menu.hidden) align();
      });
    }
    return show;
  }

  window.RouhMenu = {
    dress: dress, label: label, icon: icon, items: items, first: first,
    keys: keys, place: place, bind: bind
  };

  // Everything above this script is here already, which on every page that
  // loads it is every menu there is; anything after it is dressed once the
  // page has finished arriving. Dressing an item twice does nothing.
  dress(document);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { dress(document); });
  }
}());
