"""A contact's face from their iCloud card, kept on this machine and drawn round.

Petar, 27 October 2026, of his own card: "Contact cards show no photo." Rouh read a picture only when a
card carried it whole, as base64 (`meeting_people.icloud_photo`). An iPhone today keeps most pictures
at an address instead - `PHOTO;VALUE=uri:https://...`, on iCloud's own photo server or on a host such
as the one a contacts app synced it from - and those were never fetched, so every such card drew its
initials. His own card is one of them.

So the CardDAV sync (`apple_contacts.ContactDesk._sync`) ends with `keep_faces`: every contact whose
card has a picture Rouh has not kept yet, or a different one from the one it kept, gets it now.

- **Where it comes from.** A picture inside the card is decoded from it. One at an address is fetched:
  on iCloud's own hosts through the same signed-in CardDAV connection the sync uses (`CardDAV.picture`),
  anywhere else through `picture.fetch`, which only ever reaches public addresses.
- **What is kept.** The part the phone shows: Apple keeps it as `X-ABCROP-RECTANGLE` (x, y, width,
  height, from the bottom left), and that part is cut out, made square around its middle without
  stretching it, and made at most `SIDE` pixels across, as a JPEG under the data directory
  (`meeting_people.photo_dir`). The person's meta says where (`icloud_photo`), with the card's own
  digest of it, so an unchanged picture is never fetched twice and a changed one is fetched again.
- **The order a face is drawn in** (`meeting_people.photo_url`, `photo_of`): this one, then the LinkedIn
  photo research kept for them, then their initials. Nothing here is ever written to iCloud.

A picture that cannot be fetched is tried again on a later sync, at most `TRIES` times for the same one.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time

log = logging.getLogger("rouh.contacts.photos")

#: The widest a kept face is, in pixels: twice the largest circle Rouh draws one in.
SIDE = 512
#: How many faces one sync fetches at most, and how many at once.
PER_SYNC = 150
AT_ONCE = 4
#: How many times the same picture is tried before it is left alone until the card changes.
TRIES = 3
#: The largest picture taken in, as it arrives.
MOST_BYTES = 8 * 1024 * 1024


def _square(body: bytes, crop: list | None) -> bytes | None:
    """The picture cut to the part the phone shows, made square without stretching, as a JPEG."""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - Pillow is in the requirements
        return body
    try:
        image = Image.open(io.BytesIO(body))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception:  # noqa: BLE001 - not a picture Pillow can read
        return None
    width, height = image.size
    if crop and len(crop) == 4:
        x, y, w, h = (int(v) for v in crop)
        # Apple measures from the bottom left; Pillow from the top left.
        top = height - (y + h)
        box = (max(0, x), max(0, top), min(width, x + w), min(height, top + h))
        if box[2] - box[0] >= 8 and box[3] - box[1] >= 8:
            image = image.crop(box)
            width, height = image.size
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    if side > SIDE:
        image = image.resize((SIDE, SIDE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def _inline_bytes(meta: dict) -> bytes | None:
    from . import meeting_people

    got = meeting_people.icloud_photo(meta)
    return got[0] if got else None


def wanted(meta: dict) -> dict | None:
    """The card's picture when it is not the one kept yet (and not given up on), else None."""
    photo = ((meta.get("icloud") or {}).get("photo") or {})
    if not photo or not photo.get("digest") and not photo.get("uri"):
        return None
    kept = meta.get("icloud_photo") or {}
    key = photo.get("digest") or photo.get("uri")
    if kept.get("key") == key and (kept.get("file") or int(kept.get("tries") or 0) >= TRIES):
        return None
    return photo


def _path_for(who, pid: str, body: bytes) -> tuple[str, str]:
    from .meeting_people import photo_dir

    rel = f"{who.org_id}/{who.user_id}/{pid}-icloud-{hashlib.sha256(body).hexdigest()[:16]}.jpg"
    return rel, os.path.join(photo_dir(), rel)


def _keep(who, pid: str, photo: dict, body: bytes | None, why: str = "") -> bool:
    """The face written to disk and named on the person, or the try counted when there is none."""
    from .meeting_people import photo_path
    from .synapse import db
    from .synapse import people as synapse_people

    row = db.row("SELECT meta FROM synapse.item WHERE id = %s::uuid AND kind = 'person'", (pid,))
    if row is None:
        return False
    meta = row.get("meta") or {}
    key = photo.get("digest") or photo.get("uri")
    before = photo_path({"photo": meta.get("icloud_photo") or {}})
    square = _square(body, photo.get("crop")) if body else None
    if not square:
        tries = int((meta.get("icloud_photo") or {}).get("tries") or 0) + 1 \
            if (meta.get("icloud_photo") or {}).get("key") == key else 1
        synapse_people.set_meta(pid, {"icloud_photo": {"key": key, "tries": tries, "at": time.time(),
                                                       "why": why[:200]}})
        return False
    rel, path = _path_for(who, pid, square)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "wb") as fh:
        fh.write(square)
    os.replace(path + ".part", path)
    synapse_people.set_meta(pid, {"icloud_photo": {"key": key, "file": rel, "type": "image/jpeg",
                                                   "at": time.time(), "uri": photo.get("uri") or ""}})
    if before and before != os.path.realpath(path):
        try:
            os.remove(before)
        except OSError:
            pass
    return True


def _waiting(user_id: str, org_id: str) -> list[tuple[str, dict, dict]]:
    """(person id, the card's picture, meta) for every contact whose picture is not kept yet."""
    from . import vcard
    from .synapse import contacts, db

    ds = contacts.master_of(user_id, org_id, make=False)
    if ds is None:
        return []
    # A card kept before its picture was read (27 October 2026) has the vCard and no `photo` yet: read it
    # from the vCard once, here, rather than waiting for the card to change in iCloud.
    for r in db.rows("SELECT id, meta->'icloud'->>'vcard' AS vcard FROM synapse.item WHERE dataset_id = %s "
                     "AND kind = 'person' AND deleted_at IS NULL AND meta ? 'icloud' AND NOT meta->'icloud' ? 'photo'",
                     (ds["id"],)):
        try:
            photo = vcard.photo_of(vcard.Card.parse(r["vcard"] or "")) if r["vcard"] else {}
        except vcard.BadField:
            photo = {}
        db.run("UPDATE synapse.item SET meta = jsonb_set(meta, '{icloud,photo}', %s::jsonb) WHERE id = %s",
               (db.Json(photo), r["id"]))
    rows = db.rows("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                   "AND meta->'icloud' ? 'photo' AND meta->'icloud'->'photo' <> '{}'::jsonb", (ds["id"],))
    out = []
    for r in rows:
        meta = r.get("meta") or {}
        photo = wanted(meta)
        if photo is not None:
            out.append((str(r["id"]), photo, meta))
    return out


def gone_from_cards(user_id: str, org_id: str) -> int:
    """A face kept for a card that no longer carries a picture, taken off: the card is what decides."""
    from .meeting_people import photo_path
    from .synapse import contacts, db
    from .synapse import people as synapse_people

    ds = contacts.master_of(user_id, org_id, make=False)
    if ds is None:
        return 0
    rows = db.rows("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                   "AND meta ? 'icloud_photo' AND NOT (meta->'icloud' ? 'photo' AND meta->'icloud'->'photo' <> "
                   "'{}'::jsonb)", (ds["id"],))
    for r in rows:
        path = photo_path({"photo": (r.get("meta") or {}).get("icloud_photo") or {}})
        synapse_people.set_meta(str(r["id"]), {}, drop=("icloud_photo",))
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    return len(rows)


async def keep_faces(dav, who, *, most: int = PER_SYNC) -> int:
    """Every contact's picture not kept yet, fetched and kept: how many were. Never raises."""
    from . import picture

    try:
        waiting = await asyncio.to_thread(_waiting, who.user_id, who.org_id)
        await asyncio.to_thread(gone_from_cards, who.user_id, who.org_id)
    except Exception:  # noqa: BLE001 - the contacts synced; their faces wait for the next sync
        log.exception("contact photos: the waiting faces could not be read")
        return 0
    gate = asyncio.Semaphore(AT_ONCE)
    kept = 0

    async def one(pid: str, photo: dict, meta: dict) -> None:
        nonlocal kept
        body, why = None, ""
        async with gate:
            try:
                if photo.get("kind") == "inline":
                    body = _inline_bytes(meta)
                elif dav is not None and dav.trusts(photo.get("uri") or ""):
                    body = await dav.picture(photo["uri"], most=MOST_BYTES)
                else:
                    body, _media = await picture.fetch(photo.get("uri") or "")
            except Exception as exc:  # noqa: BLE001 - tried again on a later sync
                why = str(exc) or type(exc).__name__
                log.info("contact photos: a picture for %s could not be fetched: %s", pid, why)
        try:
            if await asyncio.to_thread(_keep, who, pid, photo, body, why):
                kept += 1
        except Exception:  # noqa: BLE001
            log.exception("contact photos: the picture for %s could not be kept", pid)

    await asyncio.gather(*(one(*w) for w in waiting[:most]))
    if waiting:
        log.info("contact photos for user %s: %d of %d waiting kept", who.user_id, kept, len(waiting))
    return kept


__all__ = ["keep_faces", "gone_from_cards", "wanted"]
