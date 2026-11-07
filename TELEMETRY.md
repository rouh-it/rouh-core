# The work tree, and the thing that draws it

Two halves of one feature, built against this contract so they can be built at
the same time.

- **The tree** is what is happening right now, as data. Server side.
- **The orb** is that same tree, drawn as a rotating three-dimensional
  structure. Browser side.

Nobody reads the orb literally. It is meant to be understood the way you
understand a room is busy without counting the people in it.

---

## Where the data comes from, measured

Claude Code fires hooks. Run against the real server on 8 September 2026, one
session that spawned one sub-agent that ran one shell command:

```
event          tool    agent_type  agent_id      tool_use_id  effort  ms
PreToolUse     Agent   -           -             5WGtt6pZXE   high
SubagentStart  -       general-pu  aa73a53b0f2a  -            -
PreToolUse     Bash    general-pu  aa73a53b0f2a  uvs9NBFYcB   high
PostToolUse    Bash    general-pu  aa73a53b0f2a  uvs9NBFYcB   high    205
SubagentStop   -       general-pu  aa73a53b0f2a  -            high
PostToolUse    Agent   -           -             5WGtt6pZXE   high    4605
SessionEnd     -       -           -             -            -
```

Four facts make the tree exact rather than guessed:

1. **`agent_id`** identifies a sub-agent. Every event inside one carries it; the
   parent's own events do not. So each event attributes to one node with no
   inference.
2. **`tool_use_id`** pairs `PreToolUse` with `PostToolUse`. A tool call is one
   node that opens and closes, not two events to match up.
3. **`duration_ms`** arrives on close.
4. **`effort`** is on every event, so "at what level" is per node and live.

The events are strictly nested, so a push/pop stack builds the tree correctly
even before any of the ids are used.

`session_id` is the same for a parent and its sub-agents - a sub-agent runs
inside the parent's session. Depth comes from `agent_id`, never from
`session_id`.

---

## The shape

One JSON tree. Every node has the same fields; only `kind` differs.

```json
{
  "id": "root",
  "kind": "root",
  "state": "running",
  "children": [
    {
      "id": "fe968984",
      "kind": "worker",
      "label": "Show running version number",
      "owner": "self",
      "state": "running",
      "effort": "high",
      "mode": "self",
      "opened_at": 1788900000.0,
      "doing": "Its helper is working on \"Run echo command\"",
      "recent": [
        {"what": "Echo test string", "state": "done", "ms": 205, "tool": "Bash", "helper": "Run echo command"}
      ],
      "children": [
        {
          "id": "aa73a53b0f2a",
          "kind": "subagent",
          "label": "general-purpose",
          "what": "Run echo command",
          "detail": "Run exactly this shell command with the Bash tool: echo from-the-subagent",
          "state": "running",
          "effort": "high",
          "opened_at": 1788900004.0,
          "doing": "Thinking about its next step",
          "recent": [{"what": "Echo test string", "state": "done", "ms": 205, "tool": "Bash"}],
          "children": [
            {
              "id": "uvs9NBFYcB",
              "kind": "tool",
              "label": "Bash",
              "what": "Echo test string",
              "detail": "$ echo from-the-subagent",
              "state": "done",
              "opened_at": 1788900004.2,
              "closed_at": 1788900004.4,
              "ms": 205,
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

**`kind`**: `root` | `worker` | `subagent` | `tool`
**`state`**: `running` | `done` | `failed` | `waiting` | `lost`

**The words** (added 13 September 2026), all built on the server by `rouh/worklabel.py`, with keys, passwords, tokens and variable values hidden and every line capped:
`what` is what a step did or a helper was asked to do, in one line of at most 90 characters, and `detail` the longer version, at most 220 (the command, the full path, what a page was read for).
`owner` says who runs a worker: `assistant` (the person's assistant), `self` (Rouh on its own code) or `server`.
`step` is a worker's workspace task and step, such as `30-02`, from the last step folder under `tasks/` it wrote in, else read or searched, or only the task, `30`, when no step folder was named.
`doing` is what a worker or helper is doing now, and `recent` its last six steps, newest first, each with its tool's name in `tool`, kept after the steps themselves have left the tree.
`label` stays the raw name: the tool, the helper's type, the job's title.

`waiting` means a human is being asked something. It is the one state that
should be impossible to miss anywhere it appears.

Two things reach the tree without a worker behind them, and both are `waiting`
for the same reason: only a person can move them.
A tool call that has to be asked about stops on its own node
(`rouh/permissions.py`), and a job whose work will not go onto main becomes a
`worker` node of its own (`rouh/conflicts.py`).
That second one carries two more fields: `conflict`, the id of the record
holding both sides, and `detail`, the question in one plain-English line.
It has no `owner`, because it is not running: it has finished and is waiting for
one decision.
The node is built from a JSON file on disk rather than from an event, so a
question asked before the last restart is still being asked after it.

### Four mutations, one per event

| Event | What it does to the tree |
|---|---|
| worker spawned (Rouh's own `delegate_task`) | add a `worker` under `root` |
| `SubagentStart` | add a `subagent` under the worker, id `agent_id` |
| `PreToolUse` | add a `tool` under the current node, id `tool_use_id` |
| `PostToolUse` | close that `tool`, set `ms` and `state` |
| `SubagentStop` | close that `subagent` |
| `SessionEnd`, or the crew sweep | close the `worker` |

"The current node" is the sub-agent named by `agent_id`, or the worker itself
when there is no `agent_id`.

### Two things that are not events

**Thinking is a gap.** Between one tool closing and the next opening the agent is
reasoning and nothing fires. The tree must not pretend otherwise: a node with no
open child and a recent close is *thinking*, derived from the clock, and that is
worth drawing because it is most of where the time goes.

**A close can go missing.** A killed worker never sends `SubagentStop`, which
would leave a node open for ever. So the tree is **derived state, rebuilt from
the stored events**, never the only copy. Keep the raw events; a missed close is
then a bug to fix rather than a corrupted structure. The crew's existing
reconciliation sweep closes orphans the same way it already marks a worker
`lost`.

**A close can come with nothing open.**
Once Claude Code's prompt suggestions are on, as they are for this machine's account since 24 September 2026, every turn ends with `Stop` and then, a moment later, a `SubagentStop` with no `SubagentStart` before it.
It is the hidden fork that works out the grey next prompt Claude Code offers, and it carries an empty `agent_type` and the suggestion as `last_assistant_message`.
It closes nothing: the tree drops a stop for something it never saw start, and the run register writes a sub-agent's end only onto a sub-agent it already has (`runs.sub_done`).
Until that day the register made a run out of it, and the runs list showed a job named by a bare id whose page said "That job is not on record here." (fr_1d8c9f71239b).

---

## On the wire

| `type` | Meaning |
|---|---|
| `tree` | the whole tree, sent on `ready`, on request, and when it changes |
| `tree_delta` | one mutation, for when sending the whole thing is wasteful |

`{"type": "get_tree"}` asks for it.

Send the whole tree until it is measurably too big. A tree with ten workers and
their tool calls is a few kilobytes; a delta protocol that is wrong in one place
leaves a structure on screen that nothing will ever correct.

---

## How it is drawn

A **structure**, not a chart: no legend and no numbers, and the only words on
it are NEEDS YOU beside anything waiting for a person. It lives on a layer of
its own over the whole screen: a small circle at the bottom-left of the screen,
on a full canvas and an empty one alike, and the whole screen when it is opened
from there.

The look is the design "Fourth", made and tuned in Claude Design and approved
on 14 September 2026. The handoff is kept in the workspace, in task 30's step
`30-04.orb-designs/source-code/design_handoff_orb/`.

### The mapping

| In the tree | On screen |
|---|---|
| root | the core: three thin crossing rings, with a ring round them breathing slowly |
| worker | a thick blue-turquoise line out of the core, tapering to 15% of its width at the tip |
| subagent | a thinner, paler line off its worker, 55% of the way out, fanning forward |
| tool call | a short twig along the line that made it, leaning out from it |
| Rouh's own turn (not in the tree; the page knows it) | a line in the core's colour out of the core, from the moment Rouh starts on an answer until it has said the last of it and none of its own calls is open; its own calls are twigs along it |
| how long a call ran | how long its twig is: a stub for a quick read, the whole length at thirty seconds or more |
| how long a worker has run | its line reaches half its length at once and the rest over ten seconds |
| running | a ring breathing at the tip of the line |
| `waiting` | the line turns red and dashed, with a filled square at its tip, a square breathing round it, a ring turning against the rotation and the words NEEDS YOU |
| finished | faint and grey for ten seconds, then gone |
| a call that returned nothing | a short bar across the end of its twig |

### Colour and mark are what kind of call

A twig says its kind twice, by its colour and by the mark at its tip, so the
kind survives greyscale, colour blindness and the 96-pixel circle.

| Call | Colour | Mark at the tip |
|---|---|---|
| web search | amber `#e8b456` | a chevron |
| reading a web page | orange `#e07b2a` | a small open square |
| running code | green `#57c98a` | a triangle, filled while it runs |
| shell command | violet `#7a6bd0` | two short bars |
| reading a file, and anything else | grey `#6e7793` | a dot |
| editing a file | magenta `#ff3ec8` | a cross |
| waiting for a person | red `#ff2b4a` | a filled square |

Rouh is dark, and those are its colours. A finished call loses its colour
towards grey, so only live work is bright.

### Movement

Turns slowly about one axis, at 0.07 radians a second. Every line also wanders
a little on its own, and lines off the same parent push each other apart, so
they spread out evenly and move aside over a second or two when a new one
arrives.

Every part can be asked what it is, the core included. Hovering shows three lines and nothing else - whose job it is, what it is doing now, and how long it has been going; a click opens a card with its details - for a job, its title, status, how long it has run and its most recent tool calls; for the core, how many jobs and tool calls are open, or that nothing is.

Where it sits decides what answers the mouse.
The orb is a layer of its own, fixed to the screen above every panel, and it has two places and only two.
It is a small circle at the bottom-left of the screen, over the task list when that is open and over the canvas when it is not, whether or not there is anything on the canvas; everything underneath takes every click, and the last task or card can always be scrolled out from under the circle.
It is never drawn inside the canvas.
A full page on the canvas has to be usable, and a shape underneath it that also answers the mouse leaves nobody able to tell which of the two a click will reach; an empty canvas is the canvas's own to say it is empty.
From the corner its colour still says that work is running, or that something is waiting for a person.
On a phone the circle sits in the corner of whichever pane is showing, just above the text box, and scrolls with it.
Clicking the circle, or asking Rouh to show the orb, opens it over the whole screen, where every part answers the mouse again.
Escape, its close button or asking Rouh puts it back, and so does a new card arriving, since the person just asked for it.

Finished work turns faint and grey within a second and a half, so a stopped
job reads as stopped at once. The ghost stays ten seconds, and can
still be pointed at, then leaves over 1.8 seconds.
A change reaches the page within about a tenth of a second - a job starting or
stopping, a tool call beginning or ending - because the server sends the tree
when something in it changes rather than on a timer.

### The cog wheel

Opened over the whole screen, the orb has a cog in its corner beside the button
that puts it back.
It opens a column down the right with every number the orb is drawn with on it, in three groups: geometry, motion and lifecycle.
The design is "Orb Editor", made in Claude Design and asked for on 16 September 2026.

Each slider writes the one settings object the drawing loop already reads on
every frame, so the shape changes under the thumb.
Nothing is rebuilt: the shape is rebuilt thirty times a second whatever happens, which is why a live editor costs nothing here.
While the column is open the canvas gives up its width, so the orb is drawn beside the controls rather than half underneath them.

What is saved, in `localStorage` under `rouh.orb.v1`, is only the settings that differ from the approved design.
So a later change to a number nobody moved still reaches them, and somebody who puts everything back leaves nothing behind.
A saved value is taken only if it is a number inside the slider it came from,
so a file from an older build cannot put the orb somewhere the panel has no way
to bring it back from.
Writing is held for 300 milliseconds after the last movement, and flushed when the page goes away; another tab moving a slider moves this one too.

Every setting that has been moved off the design says so and offers to put it
back, and so does its group; the foot of the column says how many are off it in
all and offers to put all of them back.
`show config` prints the settings as they stand, which is how a look tuned here becomes the look everybody gets: it is pasted into `ORB_CFG` in `app.js`.

The cog is only on the orb opened over the whole screen.
In its other place the orb is a 96-pixel circle that is one button, with nowhere for a cog to be.
Anything that moves the orb out of that place - a card arriving, the voice, the
close button - takes the column with it.
Escape closes the column first and leaves the orb open; the next press puts the orb back.

The fifteen numbers in its first three groups are the fifteen the drawing code already read from one
object; the fourth group, sound, has the two levels of the sound below, kept and synced the same way.
The rest of what the orb is drawn with - the palette, the tool-call marks, the depth falloff, the core, the growth and fade times, the pointing distances, roughly a hundred and forty numbers in all - is still written into the drawing code, and could be lifted onto the same panel the same way.
Four of the design's own ranges ended exactly where the user's setting sits, so those sliders could not be pushed past the value they open on; zoom and twig length are widened here.
Ghost hold is not: the ghost has to be gone within 13.5 seconds, and with 1.5 seconds to fade in and 1.8 to fade out, ten is all that is left.

### Sound

Asked for on 24 September 2026 (fr_f3ced3c15b3e): opened over the whole screen, the orb plays a short note for every new thing that appears on it, one sound for the light blue things and another for the purple ones, and very quiet music under them.
Nowhere else: in the corner it is silent.

| What appears | Colour | Sound |
|---|---|---|
| a job, a helper, Rouh's own line | blue-turquoise, pale blue, the core's pale ink | a soft piano note; a job adds the octave below |
| a tool call, of any kind | violet for a shell command, magenta for an edit, and the rest of the twig colours | a violin plucked, pizzicato: shorter, lower and quieter |
| underneath, all the time it is open | - | bowed strings holding four slow chords (D, B minor, G, A), eleven seconds each |

Everything is in D major.
The notes are its five-note scale (D, E, F sharp, A, B), and the four chords are built from those same five notes, except the G at the bottom of the G chord, two octaves under the notes, where an F sharp over it is its major seventh; so no note ever lands against the music.
Each of the two voices walks that scale a step or two from its last note, so a run of arrivals is a phrase rather than a scatter.
Arrivals wait for the next quarter of a second, one to a slot, so a burst of tool calls is a quick run of notes in time; past six waiting, the oldest tool calls are let go (never a line before a tool call), and anything that has waited a second and a half is too late to be news.
Each note is placed left or right where the thing that made it appeared on the screen.

What was already on the screen when the orb opened makes no sound, and neither does the whole tree the server sends again after the socket comes back: only work that arrives while the orb is open.
Something first seen already finished and faint is not an arrival either.

Closing the orb, or the page going out of sight, fades all of it out in about half a second and stops it; in the corner nothing is sounding at all.
While Rouh speaks, the music drops by about ten decibels and the notes by five, and the music comes back over a second or two once he has finished.

It is all made in the browser with Web Audio: oscillators for the piano's six partials, a filtered sawtooth for the pluck, a softened sawtooth for the strings, and a reverb whose impulse is noise shaped to die away over three seconds.
There is no audio file, nothing is fetched and there is no licence to hold.
A recorded piece would sound richer; if that is ever wanted, it needs a real recording with a licence to use it, and none has been chosen.

Measured from what the page actually sent to the speaker, at the default levels: the music at about -33 to -36 dBFS, each note peaking at -17 to -24 dBFS, nothing above -6 dBFS even with both sliders at 100 %.

The sound plays through the page's one AudioContext, the one the voice uses (`makeSpeaker`), so the press that lets the voice out lets this out too; the press that opens the orb is one, and an orb opened by the voice starts at the next press anywhere.
Until the browser allows sound, arrivals are let go rather than saved up to burst out at once.

The button with a speaker in it, beside the cog, turns the sound off and on for this browser (`rouh.orb.sound.v1` in local storage), because a phone in a meeting is not the desk.
The cog's panel has the two levels, notes and music, in per cent of the loudest each is built to be; they are the person's own settings like every other number on it, and moving the notes slider plays a note at the new level.

### Rules

- **Three dimensions, drawn by hand.** No 3D library and no graphics-card
  code: points in 3D, turned, projected and drawn far to near on one 2D
  canvas, with far work fainter and thinner. A three.js version with a bloom
  pass was replaced on 14 September 2026 because it was far too bright.
- **No glow, no blur, nothing added together.** Every line is a flat, matte
  stroke with a darker underside, so where two lines cross the nearer one keeps
  a thin gap. That is what keeps the orb calm beside text being read.
- Idle is a quiet core, breathing, and nothing else.
  A line always means real work.
  The seven short stubs it used to draw at idle looked exactly like work and were read as work, on a page with no jobs running.
- Cost is capped. It runs behind a conversation that must stay responsive, so it
  draws at a sensible frame rate and stops entirely when the tab is hidden.
