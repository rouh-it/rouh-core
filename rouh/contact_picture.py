"""A picture dropped into a chat, put on a contact as their picture in iCloud.

Petar, 17 November 2026: he dropped a photo of Maria's dog Clara into the chat and asked for it to go on
Clara's contact. Rouh could see the picture, but no tool of its could take it, so it told him to add it
from his phone himself. "Fix the fact that you can't access the image. You should."

So `save_contact` takes `photo`: a file dropped into a conversation, named the way `one_say` names its
attachments (its name, its id or the path Rouh was told; `runfiles.one`). This is what it becomes:

- **Square, round the face.** The model the Models page has for Contact pictures (`contact_picture`) is
  shown the picture and says where the face is, a person's or an animal's, as a box; the square is made
  round that box with room for the head, and kept inside the picture. When there is no face to find, or
  the model cannot be asked, the square is the middle of the picture across and a little above the
  middle down, which is where a portrait's face is.
- **Small enough to carry.** At most `SIDE` pixels across, as a JPEG, carried inside the card
  (`vcard.set_photo`), which is how a phone writes a picture into a vCard 3.0 and what iCloud keeps.
- **Shown before it is saved.** The card on the screen draws the new picture, and the look and the save
  make the same square (`_made`, by the picture's own bytes), so what is saved is what was shown.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger("rouh.contacts.picture")

#: The widest the picture kept on a card is, in pixels: what a phone keeps for a contact.
SIDE = 512
#: The widest the picture shown to the model is: plenty to find a face in.
ASKED_SIDE = 768
#: How much bigger than the face the square is, so the head and a little round it are in it.
ROOM = 1.8
#: The longest the model is waited for before the plain square is used.
ASK_SECONDS = 40
#: The side of the copy drawn on the card on the screen.
SHOWN_SIDE = 160

SYSTEM = (
    "You find the face in a photo that is about to be a contact's picture. The face may be a person's or "
    "an animal's. Answer with JSON alone: {\"face\": [left, top, right, bottom]}, each a fraction of the "
    "picture's width or height from 0 to 1, round the whole head (ears and hair included), or "
    "{\"face\": null} when there is no face. When there are several, the biggest.")


class Refused(ValueError):
    """Why the picture cannot go on the card, in a sentence the person can be told."""


@dataclass
class Made:
    """The square for the card, and how it was found."""

    jpeg: bytes
    #: "face" when it is round the face the model found, "middle" otherwise.
    how: str

    def shown(self) -> str:
        """A small copy as a data address, for the card on the screen."""
        return data_url(self.jpeg, SHOWN_SIDE)


#: The squares made lately, by the picture's own bytes: the look and the save make one square.
_made: dict[str, Made] = {}
_MOST_KEPT = 16


async def made_from(body: bytes, *, who=None) -> Made:
    """The square for a contact's card out of a picture's bytes."""
    key = hashlib.sha256(body).hexdigest()
    if key in _made:
        return _made[key]
    image = await asyncio.to_thread(_opened, body)
    box = await _face(image, who)
    jpeg = await asyncio.to_thread(_square, image, box)
    made = Made(jpeg=jpeg, how="face" if box else "middle")
    while len(_made) >= _MOST_KEPT:
        _made.pop(next(iter(_made)))
    _made[key] = made
    return made


def _opened(body: bytes):
    try:
        from PIL import Image, ImageOps

        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:  # noqa: BLE001 - a .heic has its copy already (`runfiles.picture`)
            pass
        image = Image.open(io.BytesIO(body))
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - a file that is not a picture Pillow opens
        raise Refused("That file could not be opened as a picture.") from exc


async def _face(image, who) -> tuple[int, int, int, int] | None:
    """The face's box in the picture's own pixels, or None when there is none or nobody could say."""
    from . import llm

    width, height = image.size
    asked = await asyncio.to_thread(_jpeg, image, ASKED_SIDE, 85)
    messages = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(asked).decode("ascii")}},
        {"type": "text", "text": "Where is the face in this picture?"}]}]
    try:
        got = await llm.ask("contact_picture", system=SYSTEM, messages=messages, max_tokens=200,
                            who=who, read_only=True, timeout=ASK_SECONDS)
    except Exception as exc:  # noqa: BLE001 - the plain square is a picture all the same
        log.info("contact picture: no face asked for (%s)", exc)
        return None
    return box_from(got.text, width, height)


def box_from(text: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    """The model's answer as a box in pixels, or None for no face or an answer that is not one."""
    found = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        face = json.loads(found.group(0)).get("face") if found else None
        left, top, right, bottom = (float(v) for v in face)
    except Exception:  # noqa: BLE001 - null, or not four numbers
        return None
    if max(left, top, right, bottom) > 1.5:          # pixels of the copy it was shown, not fractions
        scale = max(width, height) / ASKED_SIDE if max(width, height) > ASKED_SIDE else 1
        left, right = left * scale / width, right * scale / width
        top, bottom = top * scale / height, bottom * scale / height
    left, right = sorted((min(max(left, 0.0), 1.0), min(max(right, 0.0), 1.0)))
    top, bottom = sorted((min(max(top, 0.0), 1.0), min(max(bottom, 0.0), 1.0)))
    box = (int(left * width), int(top * height), int(right * width), int(bottom * height))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return box


def square_box(width: int, height: int, face) -> tuple[int, int, int, int]:
    """The square to cut: round the face with room for the head, else a portrait's middle."""
    most = min(width, height)
    if face:
        fl, ft, fr, fb = face
        big = max(fr - fl, fb - ft)
        side = int(min(most, max(big, big * ROOM)))
        cx, cy = (fl + fr) / 2, (ft + fb) / 2
        left = int(min(max(cx - side / 2, 0), width - side))
        top = int(min(max(cy - side / 2, 0), height - side))
    else:
        side = most
        left = (width - side) // 2
        top = int((height - side) * 0.3)
    return left, top, left + side, top + side


def _square(image, face) -> bytes:
    cut = image.crop(square_box(*image.size, face))
    return _jpeg(cut, SIDE, 88)


def _jpeg(image, side: int, quality: int) -> bytes:
    from PIL import Image

    if max(image.size) > side:
        image = image.copy()
        image.thumbnail((side, side), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def data_url(jpeg: bytes, side: int = SHOWN_SIDE) -> str:
    """A JPEG as a data address, made at most `side` across, for drawing on a card."""
    image = _opened(jpeg)
    return "data:image/jpeg;base64," + base64.b64encode(_jpeg(image, side, 85)).decode("ascii")


async def resolve(args: dict, chat: str, store, *, who=None) -> tuple[dict, Made | None]:
    """`save_contact`'s arguments with `photo` named by its whole path, so a press on the card's Save
    button, which comes outside the turn, finds the same file; and the square made from it, or None
    when no picture was given. Raises `Refused`."""
    from . import runfiles

    named = args.get("photo")
    if named is None or (isinstance(named, str) and not named.strip()):
        return {k: v for k, v in args.items() if k != "photo"}, None
    try:
        record = await asyncio.to_thread(runfiles.one, named, chat, store, kind="picture")
        body = await asyncio.to_thread(runfiles.picture, record, store)
    except runfiles.Refused as exc:
        raise Refused(str(exc)) from None
    made = await made_from(body, who=who)
    return dict(args, photo=str(record.get("path") or named)), made


__all__ = ["Made", "Refused", "box_from", "data_url", "made_from", "resolve", "square_box"]
