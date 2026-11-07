"""Gmail, Drive, Docs and Calendar, for one person at a time.

`GoogleClients.for_user(who)` is the whole entry point: hand it an `Identity`
and it resolves **that person's organisation's** OAuth client and **that
person's** tokens, refreshes if the access token is about to expire, and hands
back four small clients that already know who they are acting as. Nothing
below this line ever sees a client secret and nothing takes a token as an
argument, so there is no way to call Gmail as somebody else by passing the
wrong string.

These are written against Google's REST endpoints with `httpx`, which Rouh
already depends on, rather than against `google-api-python-client`. Three
reasons, in order: the timeout, the retry and the redaction are then ours and
behave the same as the rest of this process; the request bodies are plain and a
test can stand in for Google with twenty lines; and it is one fewer large
dependency on a server that has to keep starting.

Reading and writing, both. Everything that writes - sending a message,
labelling one, editing a document, saving a file - is recorded in the audit
trail as it happens (`google_audit.py`), because a send cannot be taken back
and "what did it actually do" has to be answerable without taking anybody's
word for it. There is deliberately no confirmation prompt anywhere in here:
Rouh asks the person out loud, in the conversation, before it calls any of
this. `GOOGLE.md` is the whole picture.

It is a package of one module per service, and this file is only the door:
every name the rest of Rouh imports from `rouh.google_api` is re-exported here,
so `from .google_api import Gmail` keeps working wherever it is written.

- `common.py`: where each API lives, timeouts, retries and ceilings, the
  errors every client raises, and how Google's refusals are read
- `clients.py`: `GoogleClients` and `Services`, and the one place a request
  is made (`GoogleClients.call`)
- `gmail.py`, `drive.py`, `docs.py`, `calendar.py`, `slides.py`, `sheets.py`: one client per service,
  with the helpers and constants only that service uses
- `signature.py`: the signature put under what is written, for `gmail.py`
- `desk.py`: `GoogleDesk`, what the assistant's own tools reach for
"""
from __future__ import annotations

from .common import (API_NAMES, API_SWITCHED_OFF, ATTEMPTS, BACKOFF_CEILING_SECONDS,
                     BACKOFF_SECONDS, CONNECT_SECONDS, CannotDoThat, GoogleSaidNo,
                     LEFT_OUT_OF_A_THREAD, MAIL_LIMIT, MAX_FILES, MAX_MESSAGES, READ_SECONDS,
                     REAL_BASES, SCOPE_TOO_NARROW, SeveralOfThose, UPLOAD_SECONDS, _pause, _reason,
                     _said, _text_of_html)
from .clients import GoogleClients, Services
from .gmail import Gmail, HistoryGone, SYSTEM_LABELS, _attachments, _message_bodies
from .signature import signature_text, with_signature
from .drive import (CANNOT_MAKE_A_SHARED_DRIVE, DOC_TYPE, DRIVE_MEMBER_ROLES, DRIVE_ROLE_WORDS,
                    Drive, EXPORT_AS, FILE_FIELDS, FOLDER_LISTED, FOLDER_TYPE, KINDS,
                    LISTING_FIELDS, MAX_FILE_CHARS, MAX_FOLDER_LISTED, MAX_SHARED_DRIVES,
                    MAX_TREE_BYTES, MAX_TREE_FILES, MAX_UPLOAD_BYTES, MULTIPART_LIMIT,
                    MY_DRIVE_ROOT, MemberRefused, OUR_TYPES, OUTSIDE_NOT_ALLOWED,
                    PERMISSION_FIELDS, PERMISSION_FIELDS_ONE, ROLES, ROLE_WORDS, can, drive_role,
                    member_refusal, size_said, type_of)
from .slides import PRESENTATION_TYPE, Slides, deck_of, slide_link
from .sheets import SPREADSHEET_TYPE, Sheets, sheet_link
from .docs import (DocTab, Docs, LINKED_KINDS, MAX_LINKED_LISTED, SHORTEST_PART, linked_file,
                   pick_tab, reading_of, tabs_of)
from .calendar import (ACCESS_ORDER, ACCESS_WORDS, Calendar, DEFAULT_MINUTES, EVENTS_LISTED,
                       LOOK_AHEAD_DAYS, MAKING_CALENDARS_NEEDS, MAX_CALENDARS, MAX_EVENTS_LISTED,
                       NEW_CALENDAR_ZONE, NotOnThisAccount, RESPONSES, SEARCH_REACH_DAYS,
                       SECONDARY_CALENDAR, SHARE_ROLES, WRITABLE, event_span, listing_window,
                       must_be_one_address, restore_changed, said_day, said_span, when_given,
                       zone_of_person)
from .desk import GoogleDesk
