"""OpenAI drawing Rouh's pictures, through its Images API.

The one provider `rouh/imaging.py` has today. What OpenAI offers for pictures,
as its SDK and its guide said it on 26 September 2026, and what is used:

- **Two endpoints**, `images.generate` for a new picture and `images.edit`
  for one made from another. Both are what the GPT Image models answer on;
  the Responses API's own `image_generation` tool is not offered by the two
  newest of them, and one picture from one prompt is what the Images API is
  for.
- **Models.** `gpt-image-2.5-flare`, the small fast one, draws and changes
  pictures unless another is picked, and `gpt-image-2.5-sunburst`, the larger
  one, is offered beside it for the finest detail. `ROUH_IMAGE_MODEL` and
  `ROUH_IMAGE_EDIT_MODEL` move either default.
- **Changing only an area** is `images.edit` with a `mask`: a PNG the size of
  the picture, transparent wherever it may change, made the way OpenAI's guide
  makes one (white and opaque where it stays). OpenAI says of it: "Masking
  with GPT Image is entirely prompt-based. The model uses the mask as
  guidance, but may not follow its exact shape with complete precision." So
  the area is guidance for the model, not a stencil, and the editor says so.
  Flare does it well. Sunburst does not: asked on the real API on
  26 September 2026, with the guide's own mask and with three other shapes of
  one, it gave back the painted area black every time and repainted the rest,
  so it is marked as a model that takes no mask (`masks=False`) and is
  offered for new pictures, whole-picture changes and More like this.
- **Several at once.** `n` goes up to ten; the controls offer up to four,
  which is a row of thumbnails to pick from. Each is asked for as a request
  of its own, at the same time, rather than as one request with `n`, so that
  each can stream its own rough previews into its own thumbnail, arrive the
  moment it is done, and fail on its own without taking the others with it.
  The price is the same: OpenAI charges by the picture.
- **Rough previews while it draws.** `stream` with `partial_images`: up to
  three rougher versions of the picture arrive before it is finished, and the
  page shows each in the picture's place.
- **Shape.** The three sizes every GPT Image model draws (1024x1024,
  1536x1024, 1024x1536), 16:9 and 9:16 at 1536x864 and 864x1536, which the
  2.x models draw as they draw any size in steps of 16, and `auto`.
- **Quality** low to high, and on the two 2.5 models `xhigh` and `max` too.
- **Background**: opaque, transparent, or the model's choice. Every picture
  comes back as a PNG, so a transparent one stays transparent.
- **Variations.** OpenAI's variations endpoint takes only `dall-e-2`. A
  "More like this" is therefore an edit with no mask: the picture handed in as
  the thing to draw from, and words asking for another take on it.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os

from . import costs, llmlog
from .imaging import Ask, ImageFailed, Made, Model, Provider, dimensions

log = logging.getLogger("rouh.imaging.openai")

FLARE = "gpt-image-2.5-flare"
SUNBURST = "gpt-image-2.5-sunburst"

_EVERY = ("square", "landscape", "portrait", "wide", "tall", "auto")
_QUALITIES = ("auto", "low", "medium", "high", "xhigh", "max")

MODELS = [
    Model(FLARE, "Flare", "Fast, for everyday pictures and changing an area",
          shapes=_EVERY, qualities=_QUALITIES),
    Model(SUNBURST, "Sunburst", "Slower, for the finest detail; changes whole pictures only",
          shapes=_EVERY, qualities=_QUALITIES, masks=False),
]

#: Each shape as the size OpenAI is asked for.
SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
    "wide": "1536x864",
    "tall": "864x1536",
    "auto": "auto",
}

#: How many rough versions of a picture are asked for before the finished one.
#: Two: the first arrives while the composition is still settling, the second
#: when it has, and a third arrives so close to the finished picture that it
#: is mostly bytes on the socket.
PARTIALS = 2

#: How long one picture may take. Sunburst at its best quality spends minutes
#: on one; a request that has said nothing for this long is not coming back.
TIMEOUT = 360.0

#: The largest picture handed to an edit at its own size. Anything bigger is
#: drawn at the model's own choice of size: past 2560x1440 OpenAI calls a size
#: experimental.
EDIT_PIXELS = 2560 * 1440

_client = None
_client_key = ""


def _client_for(cfg):
    """OpenAI's client for pictures, one per key, and written down like Luna's.

    Two retries of its own, unlike Luna's none: nothing has been said to the
    person yet that a retry could say twice, and a picture that failed on a
    dropped connection is a picture worth asking for again.
    """
    global _client, _client_key
    key = getattr(cfg, "openai_api_key", "")
    if _client is None or key != _client_key:
        _client = llmlog.openai_client(key, max_retries=2, timeout=TIMEOUT)
        _client_key = key
    return _client


def size_for(ask: Ask) -> str:
    """The size to ask for: the shape asked for, or for an edit the picture's own.

    An edit keeps the size of what it changes when that is a size the model
    draws - both sides in steps of 16, no longer than three times as long as
    it is wide, and no bigger than OpenAI's own non-experimental limit - so
    the picture before and the picture after can be laid one over the other.
    """
    if ask.editing and ask.shape == "auto" and ask.source is not None:
        w, h = ask.source.width, ask.source.height
        if (w and h and w % 16 == 0 and h % 16 == 0 and w * h <= EDIT_PIXELS
                and max(w, h) <= 3 * min(w, h) and min(w, h) >= 256):
            return f"{w}x{h}"
        return "auto"
    return SIZES.get(ask.shape, "auto")


def _said_of(exc) -> str:
    """What OpenAI said went wrong, in its own words where it gave any."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        if inner.get("message"):
            return str(inner["message"])
    return str(getattr(exc, "message", "") or exc)


def friendly(exc) -> ImageFailed:
    """A failure from OpenAI as a sentence the person can act on."""
    import openai

    said = _said_of(exc).strip()
    status = getattr(exc, "status_code", None)
    low = said.lower()
    if isinstance(exc, openai.APITimeoutError):
        return ImageFailed("OpenAI took too long to draw it. Try again, or ask for a "
                           "lower quality.", retry=True)
    if isinstance(exc, openai.APIConnectionError):
        return ImageFailed("OpenAI could not be reached. Try again in a moment.", retry=True)
    if status == 401:
        return ImageFailed("OpenAI refused the API key this server has.")
    if status == 403 and "verif" in low:
        return ImageFailed("OpenAI will only draw with this model for a verified "
                           f"organisation: {said}")
    if status == 429 and ("quota" in low or "billing" in low or "credit" in low):
        return ImageFailed("The OpenAI account is out of credit, so nothing was drawn.")
    if status == 429:
        return ImageFailed("OpenAI is being asked for too many pictures at once. Try "
                           "again in a minute.", retry=True)
    if status == 400 and ("safety" in low or "moderation" in low or "content_policy" in low
                          or "rejected" in low):
        return ImageFailed(f"OpenAI would not draw that: {said}")
    if status and status >= 500:
        return ImageFailed(f"OpenAI had a problem drawing it ({status}). Try again.",
                           retry=True)
    return ImageFailed(f"OpenAI could not draw it: {said}" if said else
                       "OpenAI could not draw it.")


class OpenAIImages(Provider):
    name = "openai"
    label = "OpenAI"

    def ready(self, cfg) -> bool:
        return bool(getattr(cfg, "openai_api_key", ""))

    def why_not(self, cfg) -> str:
        return ("Pictures are drawn by OpenAI, and this server has no OpenAI API key. "
                "Add OPENAI_API_KEY to its environment.")

    def models(self) -> list[Model]:
        return list(MODELS)

    def default_model(self, editing: bool) -> str:
        known = {m.id for m in MODELS}
        said = os.environ.get("ROUH_IMAGE_EDIT_MODEL" if editing else "ROUH_IMAGE_MODEL", "")
        if said.strip() in known:
            return said.strip()
        return FLARE

    async def make(self, ask: Ask, cfg, partial=None) -> list[Made]:
        client = _client_for(cfg)
        slots = [self._one(client, ask, slot, partial) for slot in range(ask.count)]
        results = await asyncio.gather(*slots, return_exceptions=True)
        made = [r for r in results if isinstance(r, Made)]
        failed = [r for r in results if isinstance(r, BaseException)]
        for exc in failed:
            if isinstance(exc, asyncio.CancelledError):
                raise exc
        if not made and failed:
            first = failed[0]
            raise first if isinstance(first, ImageFailed) else friendly(first)
        if failed:
            log.warning("%d of %d pictures failed: %s", len(failed), ask.count, failed[0])
        return made

    def _options(self, ask: Ask) -> dict:
        options = {
            "model": ask.model or self.default_model(ask.editing),
            "prompt": ask.prompt,
            "size": size_for(ask),
            "quality": ask.quality or "auto",
            "background": ask.background or "auto",
            "output_format": "png",
            "n": 1,
        }
        return options

    async def _one(self, client, ask: Ask, slot: int, partial) -> Made:
        import openai

        options = self._options(ask)
        stream = partial is not None
        if stream:
            options.update(stream=True, partial_images=PARTIALS)
        try:
            if ask.editing:
                handed = [(one.name, one.data, one.media_type) for one in ask.images]
                files = {"image": handed[0] if len(handed) == 1 else handed}
                if ask.mask and ask.source is not None:
                    files["mask"] = ("mask.png", ask.mask, "image/png")
                answer = await client.images.edit(**files, **options)
            else:
                answer = await client.images.generate(**options)
            if stream:
                return await self._read_stream(answer, ask, slot, partial, options)
            return self._read_whole(answer, options)
        except ImageFailed:
            raise
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise friendly(exc) from exc

    async def _read_stream(self, stream, ask: Ask, slot: int, partial, options) -> Made:
        done = None
        async for event in stream:
            kind = str(getattr(event, "type", "") or "")
            data = getattr(event, "b64_json", None)
            if kind.endswith("partial_image") and data:
                try:
                    await partial(slot, base64.b64decode(data), "image/png")
                except Exception:                  # noqa: BLE001 - a preview is not the picture
                    log.debug("a rough preview could not be shown", exc_info=True)
            elif kind.endswith("completed") and data:
                done = event
            elif kind == "error" or kind.endswith(".failed"):
                error = getattr(event, "error", None)
                if isinstance(error, dict):
                    error = type("Said", (), error)
                said = getattr(error, "message", None) or str(error or "it failed")
                code = str(getattr(error, "code", "") or getattr(error, "type", "") or "")
                raise ImageFailed(f"OpenAI could not draw it: {said}",
                                  retry=code in ("server_error", "rate_limit_exceeded"))
        if done is None:
            raise ImageFailed("OpenAI stopped before the picture was finished. Try again.",
                              retry=True)
        return self._made(base64.b64decode(done.b64_json), done, options)

    def _read_whole(self, answer, options) -> Made:
        pictures = [p for p in (getattr(answer, "data", None) or []) if getattr(p, "b64_json", None)]
        if not pictures:
            raise ImageFailed("OpenAI answered with no picture. Try again.", retry=True)
        made = self._made(base64.b64decode(pictures[0].b64_json), answer, options)
        made.revised = str(getattr(pictures[0], "revised_prompt", "") or "")
        return made

    def _made(self, data: bytes, said, options) -> Made:
        usage = getattr(said, "usage", None)
        usage = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
        size = dimensions(data) or (0, 0)
        model = options["model"]
        return Made(data=data, media_type="image/png", width=size[0], height=size[1],
                    model=model, quality=str(getattr(said, "quality", "") or options["quality"]),
                    usage=usage, cost=costs.image_cost(usage, model))
