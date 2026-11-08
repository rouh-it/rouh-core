"""Pictures Rouh makes: asked for in words, drawn by a provider, kept in the chat.

Petar, 26 September 2026 (fr_77013fa4c9bc): "Great, OpenAI is working. Can
you now create functionality for image generation. If OpenAI allows for area
change only, implement interface and functionality for that. Image generation
can also be done later with Google Gemini, I am saying this for architectural
decisions. But for now OpenAI only. Look at various functionalities image
generation has and implement those too (preview thumbnails if that exists etc)"

So this file is the half of it that does not know which company draws the
picture, and `imaging_openai.py` is the one company there is today. Nothing
the chat, the page, the tools or the stored transcript know about is
OpenAI's: they speak in an `Ask` and get back `Made` pictures, and a second
provider is a second class with the same three methods, registered in
`PROVIDERS`, with nothing on the chat side touched.

What a picture is, once it is made
----------------------------------

A file in the chat's own attachment folder (`rouh/attachments.py`), stored
exactly the way a photo the person dropped in is, with `made` in its record
saying how it came about: the words it was drawn from, the provider and model,
the size and quality, and for an edit the picture it was made from and whether
an area was chosen. So it is served, downloaded, opened full size and handed
to the model by the code that already does all of that for an upload, and it
is still there after a reload because the transcript points at it.

What the chat keeps is one message of Rouh's per set of pictures, carrying the
attachment markers (`draw`, and the turn or the picture controls that write
it down), so the transcript draws the set as a row of thumbnails wherever it
is read back. The model reads each as a line of words - which picture, drawn
from what - and never as the picture (`attachments._made_block`).

What each provider has to say about itself
------------------------------------------

`Provider.models()` lists what it can draw with and what each can do - the
shapes, the qualities, how many at once, whether it edits, whether it can be
told which area to change, whether it can leave the background transparent -
and the page builds the controls from that list rather than from a list of
its own (`options`). A provider that cannot take a mask says so, and the
editor offers only the whole-picture instruction for it.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import logging
import re
import struct
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger("rouh.imaging")

#: The shapes a picture can be asked for in, by name, as the page and the model
#: say them. A provider turns each into a size of its own, and a model that
#: cannot draw one leaves it out of its `shapes`.
SHAPES = {
    "square": "Square",
    "landscape": "Landscape",
    "portrait": "Portrait",
    "wide": "Wide 16:9",
    "tall": "Tall 9:16",
    "auto": "Let it choose",
}

#: How carefully a picture is drawn, lowest first. What each costs and how long
#: it takes is the provider's; `auto` leaves the choice to the model.
QUALITIES = {
    "auto": "Let it choose",
    "low": "Draft",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Very high",
    "max": "Best",
}

#: What happens behind whatever is drawn.
BACKGROUNDS = {
    "auto": "Let it choose",
    "opaque": "Solid",
    "transparent": "Transparent",
}

#: The most pictures one ask makes. Every provider may make fewer: a set of
#: four is a row of thumbnails to pick from, which is the point of asking for
#: more than one, and more than that is a bill for pictures nobody looks at.
MOST = 4

#: The longest description a picture is asked for with. Every model that
#: draws takes far more than this; a person does not write more.
PROMPT_MAX = 8000

#: The biggest picture an edit takes, and the biggest mask. OpenAI's own
#: limits (50 MB and 4 MB); a provider with smaller ones checks its own.
SOURCE_MAX = 50 * 1024 * 1024
MASK_MAX = 4 * 1024 * 1024

#: The formats a picture to be edited may be in. Everything a browser can draw
#: onto a canvas is turned into a PNG by the editor before it is sent, so this
#: is what arrives from a model's tool call, which hands over the stored file.
EDITABLE = ("image/png", "image/jpeg", "image/webp")


class ImageFailed(Exception):
    """A picture could not be made, and `said` is the sentence the person reads.

    Never a stack trace and never the provider's raw JSON: what they asked
    for, what went wrong in words, and whether trying again could help.
    """

    def __init__(self, said: str, *, retry: bool = False) -> None:
        super().__init__(said)
        self.said = said
        self.retry = retry


@dataclass
class Model:
    """One model a provider draws with, and what it can do."""

    id: str
    label: str
    note: str = ""
    shapes: tuple = ("square", "landscape", "portrait", "auto")
    qualities: tuple = ("auto", "low", "medium", "high")
    backgrounds: tuple = ("auto", "opaque", "transparent")
    most: int = MOST
    edits: bool = True
    masks: bool = True

    def said(self) -> dict:
        return {
            "id": self.id, "label": self.label, "note": self.note,
            "shapes": [{"id": s, "label": SHAPES[s]} for s in self.shapes if s in SHAPES],
            "qualities": [{"id": q, "label": QUALITIES[q]} for q in self.qualities
                          if q in QUALITIES],
            "backgrounds": [{"id": b, "label": BACKGROUNDS[b]} for b in self.backgrounds
                            if b in BACKGROUNDS],
            "most": min(self.most, MOST),
            "edits": self.edits,
            "masks": self.masks,
        }


@dataclass
class Source:
    """The picture an edit starts from, as bytes, and what it is."""

    data: bytes
    media_type: str
    name: str = "image.png"
    width: int = 0
    height: int = 0
    #: The attachment it is, when it is one of this chat's: the id the new
    #: picture says it was made from.
    id: str = ""


@dataclass
class Ask:
    """One request for pictures, in words any provider can take."""

    prompt: str
    shape: str = "auto"
    quality: str = "auto"
    count: int = 1
    background: str = "auto"
    #: A model the provider knows, or "" for its own choice.
    model: str = ""
    #: The picture to change, for an edit; nothing for a new one.
    source: Source | None = None
    #: A PNG the size of the source, transparent wherever it may change. With
    #: no mask an edit is an instruction about the whole picture.
    mask: bytes | None = None
    #: Another take on `source`: an edit with no mask, and words asking for one.
    variation: bool = False
    #: Pictures to draw from besides the one being changed, such as a logo to
    #: put on a mug or a face to keep: the person's own, attached to the ask.
    references: list = field(default_factory=list)
    #: The words its file is named after, when they are not the prompt: a
    #: variation is named after the picture it is a variation of.
    title: str = ""
    #: The person's own words, when `prompt` was written from them and the
    #: conversation before them (`with_conversation`); "" when it is their words.
    asked: str = ""

    @property
    def editing(self) -> bool:
        """Whether this is drawn from pictures handed in rather than from words alone."""
        return self.source is not None or bool(self.references)

    @property
    def images(self) -> list:
        """Every picture handed in, the one being changed first."""
        return ([self.source] if self.source is not None else []) + list(self.references)


@dataclass
class Made:
    """One picture a provider drew."""

    data: bytes
    media_type: str
    width: int = 0
    height: int = 0
    model: str = ""
    quality: str = ""
    #: What the provider said it drew, when it rewrote the words it was given.
    revised: str = ""
    usage: dict = field(default_factory=dict)
    cost: float | None = None
    #: Whether a transparent background was asked for and the model drew one
    #: anyway, so Rouh took the background out itself (`ensure_transparent`).
    cleared: bool = False


class Provider:
    """A company that draws pictures. `imaging_openai.OpenAIImages` is one.

    Three things are asked of one: whether it can be used here at all
    (`ready`), what it can draw with (`models`), and to draw (`make`), calling
    `partial(slot, data, media_type)` with each rough version of a picture it
    has before the picture is done, if it has any, so the page has something
    to show while it waits.
    """

    name = ""
    label = ""

    def ready(self, cfg) -> bool:
        raise NotImplementedError

    def why_not(self, cfg) -> str:
        """The sentence the person reads when `ready` is false."""
        return f"{self.label} is not set up on this server."

    def models(self) -> list[Model]:
        raise NotImplementedError

    def default_model(self, editing: bool) -> str:
        return self.models()[0].id

    def model(self, wanted: str, editing: bool) -> Model:
        known = {m.id: m for m in self.models()}
        return known.get(wanted) or known[self.default_model(editing)]

    async def make(self, ask: Ask, cfg, partial=None) -> list[Made]:
        raise NotImplementedError


def _openai() -> Provider:
    from .imaging_openai import OpenAIImages
    return OpenAIImages()


#: Every provider, by name, in the order they are offered. A second one - Google's
#: Gemini, when it comes - is one more entry here and a file of its own.
PROVIDERS = {"openai": _openai}


def providers() -> list[Provider]:
    return [make() for make in PROVIDERS.values()]


def provider_for(cfg, name: str = "") -> Provider:
    """The provider asked for, or the first one that is set up here.

    Raises ImageFailed with what to do when none is.
    """
    every = providers()
    if name:
        for one in every:
            if one.name == name:
                if not one.ready(cfg):
                    raise ImageFailed(one.why_not(cfg))
                return one
        raise ImageFailed(f"There is no picture provider called {name}.")
    for one in every:
        if one.ready(cfg):
            return one
    raise ImageFailed(every[0].why_not(cfg) if every else "No picture provider is set up.")


def options(cfg) -> dict:
    """What the page's picture controls offer, built from what each provider says."""
    out = []
    for one in providers():
        ready = one.ready(cfg)
        out.append({
            "name": one.name,
            "label": one.label,
            "ready": ready,
            "why_not": "" if ready else one.why_not(cfg),
            "models": [m.said() for m in one.models()],
            "default_model": one.default_model(False),
            "default_edit_model": one.default_model(True),
        })
    return {"providers": out, "most": MOST, "prompt_max": PROMPT_MAX}


def ask_from(said: dict, *, provider: Provider, editing: bool) -> Ask:
    """An Ask from what the page or a tool call sent, held to what the model does.

    Anything the chosen model cannot do is quietly put back to its own choice
    rather than refused: a shape it cannot draw becomes `auto`, a quality it
    does not have becomes `auto`. The prompt is the one thing that must be
    there.
    """
    said = said if isinstance(said, dict) else {}
    prompt = str(said.get("prompt") or "").strip()
    if not prompt:
        raise ImageFailed("Say what the picture should show.")
    if len(prompt) > PROMPT_MAX:
        raise ImageFailed(f"That description is {len(prompt):,} characters; "
                          f"the most a picture takes is {PROMPT_MAX:,}.")
    model = provider.model(str(said.get("model") or ""), editing)
    shape = str(said.get("shape") or "auto").lower()
    quality = str(said.get("quality") or "auto").lower()
    background = str(said.get("background") or "auto").lower()
    try:
        count = int(said.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    return Ask(
        prompt=prompt,
        shape=shape if shape in model.shapes else "auto",
        quality=quality if quality in model.qualities else "auto",
        background=background if background in model.backgrounds else "auto",
        count=max(1, min(count, model.most, MOST)),
        model=model.id,
    )


# --------------------------------------------------------------------------
# How big a picture is, read off its own bytes
# --------------------------------------------------------------------------


def dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height of a PNG, JPEG, GIF or WebP, or None.

    Read from the header rather than by decoding the picture, so it needs
    nothing installed and costs nothing on a fifty megabyte photograph.
    """
    if not data or len(data) < 24:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return int(w), int(h)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        return None
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            (length,) = struct.unpack(">H", data[i + 2:i + 4])
            # Every start-of-frame marker but the three that are not one.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            i += 2 + length
        return None
    return None


def media_of(data: bytes) -> str:
    """The media type a picture's own first bytes say it is, or ""."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return ""


EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
              "image/gif": "gif"}


def area_model(provider: Provider, ask: Ask) -> None:
    """An area to change goes to a model that can be told one.

    One that cannot is refused in words rather than sent the area: the page
    only offers it when nothing is painted, and a model handed a mask it does
    not take can give back something worse than no change at all (Sunburst's
    black, `imaging_openai`).
    """
    model = provider.model(ask.model, True)
    if ask.mask and not model.masks:
        able = [m.label for m in provider.models() if m.masks]
        raise ImageFailed(f"{model.label} cannot change just one area of a picture"
                          + (f"; pick {' or '.join(able)} for that." if able else "."))


def check_mask(mask: bytes, source: Source) -> None:
    """Refuse a mask a provider would refuse, with a sentence saying why."""
    if media_of(mask) != "image/png":
        raise ImageFailed("The area to change did not arrive as a picture.")
    if len(mask) > MASK_MAX:
        raise ImageFailed("The area to change is too big to send; paint it again "
                          "on a smaller picture.")
    size = dimensions(mask)
    if source.width and size != (source.width, source.height):
        raise ImageFailed(
            f"The area to change is {size[0]}x{size[1]} and the picture is "
            f"{source.width}x{source.height}; open the editor again." if size else
            "The area to change could not be read.")


def source_from(data: bytes, *, name: str = "image.png", id: str = "") -> Source:
    """A Source from a picture's bytes, checked the way a provider would."""
    media = media_of(data)
    if media not in EDITABLE:
        raise ImageFailed("Only a PNG, JPEG or WebP picture can be changed.")
    if len(data) > SOURCE_MAX:
        raise ImageFailed("That picture is too big to change; the most is 50 MB.")
    size = dimensions(data) or (0, 0)
    return Source(data=data, media_type=media, name=name, width=size[0], height=size[1],
                  id=id)


def file_name(prompt: str, index: int, media_type: str, *, edited: bool = False,
              variation: bool = False) -> str:
    """A name a person would recognise their picture by in a Downloads folder."""
    words = re.findall(r"[A-Za-z0-9]+", prompt.lower())[:6]
    stem = "-".join(words) or "picture"
    if variation:
        stem = "more-like-" + stem
    elif edited:
        stem = "edited-" + stem
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stem[:60]}-{stamp}-{index + 1}.{EXTENSIONS.get(media_type, 'png')}"


async def make(provider: Provider, ask: Ask, cfg, partial=None) -> list[Made]:
    """Ask a provider for pictures, with every failure turned into words."""
    try:
        made = await provider.make(ask, cfg, partial)
    except ImageFailed:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as exc:                       # noqa: BLE001 - said, not raised
        log.exception("making a picture with %s failed", provider.name)
        raise ImageFailed(f"{provider.label} could not make the picture: {exc}") from exc
    if not made:
        raise ImageFailed(f"{provider.label} answered with no picture. Try again.",
                          retry=True)
    for one in made:
        if not (one.width and one.height):
            with contextlib.suppress(Exception):
                one.width, one.height = dimensions(one.data) or (0, 0)
    if ask.background == "transparent":
        for one in made:
            await asyncio.to_thread(ensure_transparent, one)
    return made


# --------------------------------------------------------------------------
# In the chat: drawn, shown while drawing, kept, and written down
# --------------------------------------------------------------------------

#: The pictures the turn running in this context has shown, which the turn
#: writes into its chat as one message of Rouh's when it ends (`runtime.Turn`).
#: Not written by the tool that drew them: a row put between a tool call and
#: its result breaks the conversation for every turn after it
#: (`memory.repair_history`), and the turn is the one thing that knows when
#: the last of its rows is down.
SHOWN: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "rouh_pictures_shown", default=None)


def shown(markers: list[dict]) -> bool:
    """Hand the turn in this context pictures to write down. False with none."""
    kept = SHOWN.get()
    if kept is None:
        return False
    kept.extend(markers)
    return True


def new_set() -> str:
    """The id of one set of pictures, the page's handle on it while it is drawn."""
    return uuid.uuid4().hex[:12]


def caption(provider: Provider, ask: Ask) -> str:
    """The line under a set of pictures: which model, what shape, how careful."""
    model = provider.model(ask.model, ask.editing)
    parts = [model.label]
    if ask.source is not None:
        parts.append("area changed" if ask.mask else
                     "variation" if ask.variation else "whole picture changed")
    elif ask.references:
        parts.append("from your picture" if len(ask.references) == 1 else
                     f"from {len(ask.references)} of your pictures")
    if ask.asked:
        parts.append("with the conversation")
    if ask.shape != "auto" and ask.source is None:
        parts.append(SHAPES.get(ask.shape, ask.shape))
    if ask.quality != "auto":
        parts.append(QUALITIES.get(ask.quality, ask.quality))
    if ask.background == "transparent":
        parts.append("transparent")
    return " · ".join(parts)


def _made(provider: Provider, ask: Ask, one: Made, *, set_id: str, index: int,
          count: int, extra: dict | None) -> dict:
    made = {
        "kind": "drawn", "by": provider.name, "model": one.model or ask.model,
        "prompt": ask.prompt, "shape": ask.shape, "quality": ask.quality,
        "background": ask.background, "width": one.width, "height": one.height,
        "set": set_id, "index": index, "of": count,
    }
    if ask.source is not None and ask.source.id:
        made["from"] = ask.source.id
    if ask.references:
        made["references"] = [r.id for r in ask.references if r.id]
    if ask.mask:
        made["area"] = True
    if ask.variation:
        made["variation"] = True
    if one.quality and one.quality != ask.quality:
        # What the model settled on when it was left to choose.
        made["quality_drawn"] = one.quality
    if one.revised:
        made["revised"] = one.revised
    if ask.asked:
        made["asked"] = ask.asked
    if one.cleared:
        made["background_cleared"] = True
    if one.cost is not None:
        made["cost"] = round(one.cost, 5)
    made.update(extra or {})
    return made


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64," + base64.b64encode(data).decode("ascii")


def on_screen(marker: dict) -> dict:
    """A marker as the page is sent it: everything but its type."""
    return {k: v for k, v in marker.items() if k != "type"}


async def draw(provider: Provider, ask: Ask, cfg, *, store, chat: str, send,
               set_id: str = "", extra: dict | None = None) -> list[dict]:
    """Draw a set of pictures, show them on the way, keep them, and return
    their markers.

    `send` puts one message on the screens of the chat: the set appearing as
    as many empty frames as pictures asked for, each rough preview in its
    frame as it arrives, and then the finished pictures, or the sentence
    saying why there are none. Each picture is kept in the chat's own files
    before the page is told it is finished, so a finished picture on the
    screen is one that is there after a reload.

    Raises ImageFailed, having said so on the screen.
    """
    set_id = set_id or new_set()
    line = caption(provider, ask)
    await send({"type": "pictures", "set": set_id, "state": "working",
                "count": ask.count, "shape": ask.shape, "caption": line,
                "prompt": ask.prompt, "editing": ask.editing, "area": bool(ask.mask),
                "from": ask.source.id if ask.source is not None else ""})

    async def partial(slot: int, data: bytes, media_type: str) -> None:
        await send({"type": "picture_partial", "set": set_id, "slot": slot,
                    "src": _data_url(data, media_type)})

    try:
        made = await make(provider, ask, cfg, partial)
        markers = []
        for index, one in enumerate(made):
            info = _made(provider, ask, one, set_id=set_id, index=index, count=len(made),
                         extra=extra)
            name = file_name(ask.title or ask.prompt, index, one.media_type,
                             edited=ask.editing, variation=ask.variation)
            record = await asyncio.to_thread(store.save, chat, name, one.data, one.media_type,
                                             made=info)
            markers.append(_marker(record))
    except ImageFailed as exc:
        await send({"type": "pictures", "set": set_id, "state": "failed", "said": exc.said,
                    "retry": exc.retry, "caption": line})
        raise
    except Exception as exc:                       # noqa: BLE001 - said, not raised
        log.exception("keeping a picture failed")
        failed = ImageFailed(f"The picture was drawn and could not be kept: {exc}")
        await send({"type": "pictures", "set": set_id, "state": "failed", "said": failed.said,
                    "caption": line})
        raise failed from exc
    cost = sum(float(m["made"].get("cost") or 0) for m in markers)
    priced = all(m["made"].get("cost") is not None for m in markers)
    await send({"type": "pictures", "set": set_id, "state": "done", "caption": line,
                "pictures": [on_screen(m) for m in markers],
                "missing": max(0, ask.count - len(markers)),
                "cost": round(cost, 5) if priced else None})
    return markers


def _marker(record: dict) -> dict:
    from .attachments import marker
    return marker(record)


def said_for_tool(markers: list[dict], ask: Ask) -> str:
    """What the model is told when a tool of its own drew pictures."""
    ids = ", ".join(f"{m['name']} (id {m['id']})" for m in markers)
    many = len(markers)
    missing = ask.count - many
    fewer = (f" {missing} of the {ask.count} asked for could not be drawn." if missing > 0
             else "")
    what = "picture is" if many == 1 else f"{many} pictures are"
    return (f"The {what} on the person's screen now, in the chat: {ids}.{fewer} "
            "Say in a few words that it is there; do not describe it unless asked, "
            "because they can see it. Under each picture they can open it full size, "
            "download it, paint an area to change, or ask for more like it; "
            "change_picture changes one when they ask you to in words.")


def variation_title(record: dict) -> str:
    """What a variation's file is named after: the words or the name of the picture."""
    made = record.get("made") if isinstance(record.get("made"), dict) else {}
    return str(made.get("prompt") or re.sub(r"\.[A-Za-z0-9]+$", "", str(record.get("name") or "")))


def variation_prompt(first: str = "") -> str:
    """The words a variation is asked for with: another take on the picture."""
    return ("Draw a new variation of this picture: the same subject, style and colours, "
            "a different take on it."
            + (f" It was first drawn from these words: {first}" if first else ""))


#: What the editor sends up beside the change it asks for, none of which is a
#: picture anybody drew or handed over: the area painted (`mask`), the copy of
#: the picture it painted on when the picture itself would not do (`work`), and
#: the small picture of the area that stands in the question (`area`). Marked
#: in their records so nothing takes one for a picture in the chat.
HELPERS = ("mask", "work", "area")


def is_picture(record: dict) -> bool:
    """A picture in a chat that can be changed: drawn, or handed over."""
    made = record.get("made") if isinstance(record.get("made"), dict) else {}
    return (record.get("kind") == "image" and record.get("media_type") in EDITABLE
            and made.get("kind") not in HELPERS)


def said_failed(exc: ImageFailed) -> str:
    """Rouh's message in the chat when the picture controls asked and none came."""
    return f"I could not make that picture. {exc.said}"


# --------------------------------------------------------------------------
# A transparent background, asked for and really there
# --------------------------------------------------------------------------
#
# Petar, 8 November 2026 (fr_76401247a621): "the transparent background
# definitely doesn't work." Asked with a picture of his own and words about a
# glowing creature, Sunburst gave back four pictures on a painted night sky:
# `background: transparent` reached OpenAI every time, and a GPT Image model
# reads it as a wish the words can outvote. OpenAI's guide says to ask for the
# transparent background in the words too, so every provider is handed
# `prompt_for(ask)`, and whatever comes back is checked for real transparency.

#: What is said after the person's words when the background is to be clear.
TRANSPARENT_WORDS = (
    "Transparent background: draw only the subject itself, cut out cleanly, with "
    "nothing behind it - no scenery, sky, backdrop, floor, frame, vignette, "
    "colour fill, shadow on the ground or checkerboard pattern. Every pixel "
    "around the subject is fully transparent.")


def prompt_for(ask: Ask) -> str:
    """The words a provider is handed: the prompt, and for a clear background
    the sentence that asks for one, which the model heeds where it does not
    always heed the setting alone."""
    if ask.background == "transparent" and TRANSPARENT_WORDS not in ask.prompt:
        return f"{ask.prompt}\n\n{TRANSPARENT_WORDS}"
    return ask.prompt


#: How much of a picture must be see-through for its background to count as
#: transparent: a picture with a clear background has far more than this.
CLEAR_SHARE = 0.02


def clear_share(data: bytes) -> float:
    """The share of a picture's pixels that are fully or mostly see-through."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        if "A" not in im.getbands() and not (im.mode == "P" and "transparency" in im.info):
            return 0.0
        alpha = im.convert("RGBA").getchannel("A")
    hist = alpha.histogram()
    return sum(hist[:128]) / max(1, alpha.width * alpha.height)


def clear_background(data: bytes) -> bytes | None:
    """The picture as a PNG with its background taken out, or None when it has
    no background that can be told from what is in front of it.

    The background is what touches the edges and is near the edges' own
    colour: the colour of the border is measured, every pixel near it that can
    be reached from an edge without crossing the subject becomes see-through,
    and the pixels at the margin fade with how far they are from it, so a glow
    or a soft edge stays soft. A border with no one colour to it (a photograph,
    a busy scene) is left alone rather than cut up.
    """
    import io

    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

    with Image.open(io.BytesIO(data)) as opened:
        im = opened.convert("RGBA")
    w, h = im.size
    if w < 8 or h < 8:
        return None
    rgb = im.convert("RGB")
    edge = max(2, min(w, h) // 64)
    strips = [rgb.crop((0, 0, w, edge)), rgb.crop((0, h - edge, w, h)),
              rgb.crop((0, 0, edge, h)), rgb.crop((w - edge, 0, w, h))]
    border = Image.new("RGB", (sum(s.width * s.height for s in strips), 1))
    border.putdata([p for s in strips for p in s.getdata()])
    stat = ImageStat.Stat(border)
    spread = max(stat.stddev)
    if spread > 40:
        return None
    ref = tuple(int(round(v)) for v in stat.median)
    tol = max(20.0, min(80.0, 2.5 * spread + 16))
    # How far each pixel is from the border's colour, in its worst channel.
    diff = ImageChops.difference(rgb, Image.new("RGB", (w, h), ref))
    r, g, b = diff.split()
    far = ImageChops.lighter(ImageChops.lighter(r, g), b)
    # The background is found on a small copy, where filling is quick, and the
    # answer is laid back over the whole picture.
    scale = min(1.0, 384 / max(w, h))
    sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
    near = far.resize((sw, sh), Image.BILINEAR).point(lambda v: 255 if v <= tol else 0)
    padded = Image.new("L", (sw + 2, sh + 2), 255)
    padded.paste(near, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    reached = padded.crop((1, 1, sw + 1, sh + 1)).point(lambda v: 255 if v == 128 else 0)
    if sum(reached.histogram()[255:]) < 0.05 * sw * sh:
        return None                                 # hardly any background to take out
    reached = reached.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1))
    # Inside the background, opaque only as far as a pixel is from its colour.
    fade = far.point(lambda v: min(255, int(v * 255 / tol)))
    keep = ImageChops.lighter(fade, ImageChops.invert(reached))
    alpha = ImageChops.multiply(im.getchannel("A"), keep)
    im.putalpha(alpha)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


def ensure_transparent(one: Made) -> None:
    """A picture asked for on a clear background, made to have one.

    One the model drew transparent is left as it is. One it drew on a
    background anyway has that background taken out here (`clear_background`)
    and says so in its record; one whose background cannot be told from its
    subject is kept as drawn, which the log says.
    """
    try:
        if clear_share(one.data) >= CLEAR_SHARE:
            return
        cleared = clear_background(one.data)
    except Exception:                               # noqa: BLE001 - the picture is still a picture
        log.warning("could not check a picture for transparency", exc_info=True)
        return
    if cleared is None:
        log.info("a transparent picture came back with a background that could not be "
                 "taken out")
        return
    one.data, one.media_type, one.cleared = cleared, "image/png", True


# --------------------------------------------------------------------------
# A picture asked for in the middle of a conversation
# --------------------------------------------------------------------------
#
# Petar, 8 November 2026 (fr_76401247a621): "image generation only generates
# at the current prompt, it doesn't take the full conversation as input." The
# picture controls handed the provider the words typed into the box and
# nothing else, so "now make it blue" drew something blue. A model that draws
# reads only its prompt, so the prompt is written from the conversation:
# the chat's last messages as words, every picture in them as the words it was
# drawn from (never the picture itself), and the person's request, by the use
# Picture descriptions on the Models page (`picture_prompt`). Earlier pictures
# are not handed in as pictures: changing one is the editor's and
# change_picture's, and a set drawn with a picture of its own goes on taking it.

#: How many of a chat's last messages are read, and how much of them.
CONTEXT_MESSAGES = 24
CONTEXT_CHARS = 12000
_MESSAGE_CHARS = 2500

PROMPT_SYSTEM = (
    "You write the description a picture is drawn from. The model that draws it "
    "sees only your description, never the conversation, so write one whole "
    "description that stands on its own.\n"
    "Use the conversation for whatever the request leans on: the subject, its "
    "details, the style, the colours, the setting and the framing that were "
    "settled earlier, and when the request changes the latest picture (\"now make "
    "it blue\", \"same but at night\", \"another one\"), that picture's own "
    "description with the change made. Keep every detail the request gives; where "
    "the request and the conversation disagree, the request wins. Leave out "
    "whatever in the conversation is not about this picture. If the request "
    "already stands on its own and the conversation adds nothing to it, give it "
    "back as it is.\n"
    "Write only the description: no preamble, no quotes, no notes, at most 250 "
    "words, in English unless words that must appear in the picture are in "
    "another language, spelled exactly as they are to appear.")


def _said_in(content, role: str) -> str:
    """One stored message as the words the prompt writer reads."""
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or "").strip())
        elif kind == "attachment":
            made = block.get("made") if isinstance(block.get("made"), dict) else {}
            if made.get("kind") == "drawn":
                parts.append(f"[A picture Rouh drew, from the description: "
                             f"{made.get('prompt') or ''}]")
            elif made.get("kind") in HELPERS:
                continue
            elif str(block.get("media_type") or "").startswith("image/"):
                parts.append(f"[A picture the person attached: {block.get('name') or ''}]")
            else:
                parts.append(f"[A file: {block.get('name') or ''}]")
    return "\n".join(p for p in parts if p)


def conversation_text(messages: list[dict]) -> str:
    """A chat's last messages as lines of words, newest kept when it is long.

    Tool calls and their results are left out: what came of them is in the
    words around them, and a picture drawn by a tool is in the turn's own
    message of pictures.
    """
    lines = []
    for msg in messages[-CONTEXT_MESSAGES:]:
        role = msg.get("role")
        said = _said_in(msg.get("content"), role)
        if not said or role not in ("user", "assistant"):
            continue
        if len(said) > _MESSAGE_CHARS:
            said = said[:_MESSAGE_CHARS] + " ..."
        lines.append(("Person: " if role == "user" else "Rouh: ") + said)
    kept, used = [], 0
    for line in reversed(lines):
        if used + len(line) > CONTEXT_CHARS:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(reversed(kept))


async def with_conversation(ask: Ask, messages: list[dict], *, who=None,
                            session_id: str = "") -> Ask:
    """The ask, its prompt written from the conversation before it.

    Nothing is asked when the chat has nothing said in it yet. When the model
    cannot be asked, or answers with nothing, the person's words are drawn as
    they are, which is what was drawn before, and the log says why.
    """
    said = conversation_text(messages)
    if not said:
        return ask
    from . import llm

    question = (f"The conversation so far:\n{said}\n\n"
                f"The person now asks for a picture with these words:\n{ask.prompt}\n\n"
                "Write the description of that picture.")
    try:
        got = await llm.ask("picture_prompt", system=PROMPT_SYSTEM,
                            messages=[{"role": "user", "content": question}],
                            max_tokens=1200, who=who, session_id=session_id,
                            read_only=True, timeout=45)
    except Exception as exc:                        # noqa: BLE001 - the words alone still draw
        log.warning("the picture's description could not be written from the "
                    "conversation: %s", exc)
        return ask
    written = (got.text or "").strip().strip('"').strip()
    if not written or written == ask.prompt:
        return ask
    ask.asked = ask.prompt
    ask.prompt = written[:PROMPT_MAX]
    return ask
