"""Rouh Link: Rouhs working together, live, like people in Figma (task 189).

Each person keeps their own Rouh. Rouhs that know each other connect, and then work together in
**live shared spaces**: a task page, a document, a trip, a list, any piece of work, with several
Rouhs and their people in it at once, every change reaching everyone in under a second. People
still decide anything that binds them. LINK.md at the top of the repository has the whole of it;
in short:

- `me`: this Rouh's identity for the link (its name, relay label, address, daily key, link key).
- `seal`: every message between two Rouhs is locked to the other's link key (X25519) and signed
  with the sender's daily key (Ed25519, the key its name was born from or its signed successor).
  The relay and the mailbox only ever carry locked bytes.
- `card`: the Rouh card, an A2A agent card, signed, at ``/.well-known/agent-card.json``.
- `forms`: the keyless reader. Whatever another Rouh sends is turned into a fixed form by code,
  or refused. Nothing another Rouh wrote ever reaches a model that holds a tool or a key.
- `trust`, `limits`: who may do what, checked in code outside the AI, every time.
- `log`: the signed log of every message and change, readable in plain words by both people.
- `wire`: sending and receiving, the outbox, and the mailbox beside the relay for a Rouh that is
  off (`mailbox`).
- `peers`: connecting by a link, a QR code or a contact; trust levels; cutting a connection.
- `doc`, `room`, `spaces`: the live room per shared space, held by its owner's Rouh: the order of
  changes, last-writer-wins fields, a text CRDT for long text, claims, intents, comments,
  proposals, history and undo per Rouh; and each member's own copy.
- `pacing`, `worker`: a Rouh's own edits shown at a person's speed, and its work in a space done
  by a reader with no tools.
- `meeting`: the first job gene, "Book a meeting" (`rouh/genes/manifests/book-a-meeting.json`).

Rouh Link is part of Rouh's core, not a gene: every kind of job is a gene on top of it.
"""
