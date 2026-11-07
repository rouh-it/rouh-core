"""``python manage.py offsite_backup``: the weekly encrypted copy off the machine (`rouh/offsite.py`).

    python manage.py offsite_backup status            the nightly copies and the off-site one, in words
    python manage.py offsite_backup run               send one now (the core does it every week by itself)
    python manage.py offsite_backup list              what is in the bucket, under this Rouh's prefix
    python manage.py offsite_backup fetch --to FILE   the newest, downloaded still encrypted, its SHA-256 checked
    python manage.py offsite_backup check [--identity KEYFILE]
                                                      the newest, downloaded, opened and read back

`check` opens the copy with the private key in KEYFILE (as age-keygen writes it) or with
ROUH_OFFSITE_PASSPHRASE, and reads the bundle in it back: what it says it is, and its database,
byte for byte. A copy made for a public key cannot be opened on the machine that made it, which is
the point: check it where the private key is kept.

In a stack: docker compose exec core python manage.py offsite_backup status
"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
import threading

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "The weekly encrypted copy of this Rouh off its machine."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("status", "run", "list", "fetch", "check"))
        parser.add_argument("--to", default="", help="fetch: the file to download into, a new one")
        parser.add_argument("--key", default="", help="fetch, check: one copy by its name in the bucket")
        parser.add_argument("--identity", default="", help="check: an age key file holding the private key")

    def handle(self, *args, **opts):
        from rouh import offsite

        action = opts["action"]
        if action == "status":
            self.stdout.write(offsite.nightly()["human"] + "\n" + offsite.describe()["human"] + "\n")
            return
        try:
            offsite.settings()
        except offsite.NotSetUp as e:
            # Not set up is a plain answer, not a failure: nothing is sent, and nothing is wrong.
            self.stdout.write(f"Nothing done: {e}.\n")
            return
        try:
            if action == "run":
                got = offsite.run()
                self.stdout.write(f"Sent {got['key']}, {got['bytes'] / 1e6:.1f} MB, encrypted, made from {got['dump']}; "
                                  f"{len(got['deleted_old'])} older one(s) deleted.\n")
            elif action == "list":
                s = offsite.settings()
                for o in offsite.objects(offsite.client(s), s):
                    self.stdout.write(f"{o['Key']}  {o['Size'] / 1e6:.1f} MB  {o['LastModified']:%Y-%m-%d %H:%M}\n")
            elif action == "fetch":
                if not opts["to"]:
                    raise CommandError("fetch needs --to FILE")
                got = offsite.fetch(opts["to"], opts["key"])
                self.stdout.write(f"Downloaded {got['key']} into {got['to']}, {got['bytes'] / 1e6:.1f} MB, "
                                  "still encrypted; its SHA-256 is the one it was sent with.\n")
            else:
                self.stdout.write(self._check(offsite, opts) + "\n")
        except (RuntimeError, OSError) as e:
            raise CommandError(str(e)) from e

    def _check(self, offsite, opts) -> str:
        from rouh import agefile, bundle

        ids = []
        if opts["identity"]:
            with open(opts["identity"], encoding="utf-8") as fh:
                ids = agefile.identities_in(fh.read())
        phrase = os.environ.get("ROUH_OFFSITE_PASSPHRASE", "")
        if not ids and not phrase:
            raise CommandError("check needs the private key (--identity KEYFILE) or ROUH_OFFSITE_PASSPHRASE to open the copy")
        with tempfile.TemporaryDirectory(dir=offsite.work_dir() if os.path.isdir(offsite.work_dir()) else None) as tmp:
            sealed = os.path.join(tmp, "copy.age")
            got = offsite.fetch(sealed, opts["key"])
            # Opened into a pipe and read as it opens: the bundle is never written down here.
            r, w = os.pipe()
            failed: list[BaseException] = []

            def open_it() -> None:
                try:
                    with open(sealed, "rb") as src, os.fdopen(w, "wb") as out:
                        agefile.decrypt(src, out, identities=ids, passphrase="" if ids else phrase)
                except BaseException as e:  # noqa: BLE001 - said below
                    failed.append(e)

            opener = threading.Thread(target=open_it, daemon=True)
            opener.start()
            about, digest, names = {}, None, 0
            with os.fdopen(r, "rb") as plain, tarfile.open(fileobj=plain, mode="r|") as t:
                for m in t:
                    names += 1
                    if m.name == bundle.ABOUT:
                        about = json.loads(t.extractfile(m).read())
                    elif m.name == bundle.DUMP:
                        h, f = hashlib.sha256(), t.extractfile(m)
                        for block in iter(lambda: f.read(1 << 20), b""):
                            h.update(block)
                        digest = h.hexdigest()
            opener.join()
        if failed:
            raise CommandError(f"the copy could not be opened: {failed[0]}")
        if about.get("format") != bundle.FORMAT:
            raise CommandError("the copy opened, and holds no bundle of a Rouh")
        if digest != (about.get("database") or {}).get("sha256"):
            raise CommandError("the copy opened, and its database is not the one it describes")
        return (f"{got['key']} opens, and holds {bundle.describe(about)}; its database is whole "
                f"({names} entries in all). It restores with linux_stack.py import.")
