# Handoff: Rouh Link phase 1 screens

Built straight into Rouh's code: `rouh/templates/rouh/link_space.html`, `link_connections.html`, `link_join.html`, `rouh/static/link/{link.css,space.js,connections.js}`; the prototypes in `.design/a-live/` and `.design/a-connections/` are those same files inlined with a fixed state.

## Journeys and targets
1 Who is here: 0 clicks, top bar avatars, the amber "is at work" mark and the live sentence (one list counts both). 2 Ask my Rouh: 1 field, 1 click (top of the side column; first on a phone). 3 Meeting: Find a meeting time, then Yes, this time. 4 Undo its edits: 1 click; History: Show, slide, Bring back. 5 Comment: 2 clicks. 6 Connect: Make a connect link (link and QR) or Bring a link, 2 actions. 7 Lower or cut: 1 select or 1 press. 8 The log: 1 click.

## Navigation
Connections at `/link` (gene `rouh-link`, Work group link); a space at `/link/space/<id>`; a task's three dots: Work on it live with another Rouh; a contact card: Their Rouh.

## States
Invited (Join banner, work hidden), the room off (banner with the waiting count), ended, no time free, agreed, not born, no connection yet, a request waiting.

## Data the backend supplies
`GET /api/link/spaces/<id>?since&wait&part&follow`: space, me, doc (fields, texts with character ids and writers, lists, claims, comments, intents, proposals, activity, runs, seq), presence, pacing, pending, holder_off. `GET /api/link`: me, settings (with held, held_why), peers, invites, spaces, levels.

## Tokens (both themes)
Dark: ground #0f1417, panel #161d21, raised #1d262b, line #2a363c, ink #e8eef0, dim #a3b1b6, accent #36dce5 (Rouh's), partner #ffb547, third #b9a7ff, fourth #ff8fb0, good #7fe0a0, bad #ff6b81. Light: ground #f5f7f7, panel #fff, raised #eef2f3, line #d5dde0, ink #12191c, dim #4c5a60, accent #0b7f86, partner #a35a00, third #5b45c4, fourth #b0285a, good #1c7a43, bad #b3243b. People round, Rouhs rounded squares. System fonts.

## Dropped, and open
Open: a marker on the very step a Rouh is adding (today the list's); five members in the bar (phase 2); a thread of many comments folded.
