"""``python manage.py rule_defaults``: the defaults every Rouh starts with (`rouh/ruledefaults.py`).

    python manage.py rule_defaults                      # what is in use, and what the last fetch said
    python manage.py rule_defaults fetch                # fetch them from rouh.land now
    python manage.py rule_defaults take --user 1        # take what is in use into that person's Master now
    python manage.py rule_defaults export --user 1 > defaults.json
        # the document of that person's rules tagged "defaults", for rouh.land to publish

    python manage.py rule_defaults prepare --doc defaults.json --published live.json --out ready.json \
        --fallback rouh/rule_defaults_fallback.json [--words private-words.txt]
        # the export made ready to publish: nothing private in it, versions carried on from what rouh.land
        # serves now, and the fallback brought into step with it (no database is read)
    python manage.py rule_defaults read --url https://rouh.land/rules/defaults.json
        # the live document read as every Rouh reads it, said in a line (no database is read)

To publish, run `tools/rule_defaults/publish.sh` (README, "What a conversation is told"): it exports, prepares,
copies the document to rouh.land's site as rouhit/rules/defaults.json, deploys the site and reads it back.
On the server, run it with Rouh's environment, as Rouh's other commands are run (README).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Say, fetch, take in or export the defaults every Rouh starts with."

    def add_arguments(self, parser):
        parser.add_argument("action", nargs="?", default="status", choices=["status", "fetch", "take", "export", "prepare", "read"])
        parser.add_argument("--user", default="1")
        parser.add_argument("--org", default="")
        parser.add_argument("--revision", default="")
        parser.add_argument("--doc", default="", help="prepare: the exported document")
        parser.add_argument("--published", default="", help="prepare: what rouh.land serves now, if anything")
        parser.add_argument("--words", default="", help="prepare: a file of words no published rule may hold")
        parser.add_argument("--out", default="", help="prepare: where the document to publish is written")
        parser.add_argument("--fallback", default="", help="prepare: the fallback file to bring into step")
        parser.add_argument("--url", default="", help="read: the address to read")

    def handle(self, *args, **o):
        from rouh import ruledefaults, rules
        from rouh.config import config
        from rouh.models.accounts import User

        if o["action"] == "status":
            doc = ruledefaults.current()
            self.stdout.write(json.dumps({"in_use": doc["revision"], "from": doc["source"], "rules": len(doc["rules"]),
                                          "last_fetch": ruledefaults.fetched_said()}, indent=1))
            return
        if o["action"] == "prepare":
            self._prepare(o)
            return
        if o["action"] == "read":
            self._read(o["url"] or config.rule_defaults_url)
            return
        if o["action"] == "fetch":
            self.stdout.write(json.dumps(ruledefaults.fetch(config), indent=1))
            return
        user = User.objects.filter(id=o["user"]).first()
        if user is None:
            raise CommandError(f"There is no account {o['user']}.")
        ds = rules.master(str(user.id), o["org"] or str(user.org_id or "org-default"))
        if o["action"] == "take":
            self.stdout.write(json.dumps(ruledefaults.take(ds, ruledefaults.current())))
            return
        self.stdout.write(json.dumps(ruledefaults.export(ds, revision=o["revision"]), indent=1, ensure_ascii=False))

    def _prepare(self, o):
        from rouh import ruledefaults

        if not o["doc"] or not o["out"]:
            raise CommandError("prepare needs --doc and --out.")
        with open(o["doc"], encoding="utf-8") as f:
            doc = json.load(f)
        if o["revision"]:
            doc["revision"] = o["revision"]
        elif str(doc.get("revision") or "").startswith("fallback-"):
            # The fallback published as it is (`publish.sh --from-fallback`): a revision of the published kind.
            import time

            doc["revision"] = time.strftime("%Y-%m-%d") + "." + ruledefaults.digest(
                json.dumps(doc.get("rules"), sort_keys=True))[:8]
        published = None
        if o["published"]:
            with open(o["published"], encoding="utf-8") as f:
                raw = f.read().strip()
            published = json.loads(raw) if raw else None
        words: list[str] = []
        if o["words"]:
            with open(o["words"], encoding="utf-8") as f:
                words = [w.strip() for w in f if w.strip() and not w.lstrip().startswith("#")]
        try:
            ready = ruledefaults.publishable(doc, published, words=words)
        except ruledefaults.Bad as exc:
            raise CommandError(f"Not published: {exc}") from None
        with open(o["out"], "w", encoding="utf-8") as f:
            f.write(ruledefaults.dumps(ready))
        if o["fallback"]:
            with open(o["fallback"], "w", encoding="utf-8") as f:
                f.write(ruledefaults.dumps(ruledefaults.as_fallback(ready)))
        before = {r["key"]: r["version"] for r in (ruledefaults.check(published)["rules"] if published else [])}
        changed = [r["key"] for r in ready["rules"] if before.get(r["key"]) != r["version"]]
        self.stdout.write(json.dumps({"revision": ready["revision"], "rules": len(ready["rules"]),
                                      "new_or_changed": changed,
                                      "gone": sorted(set(before) - {r["key"] for r in ready["rules"]})}, indent=1))

    def _read(self, url):
        import httpx

        from rouh import ruledefaults

        r = httpx.get(httpx.URL(url).copy_merge_params({"schema": ruledefaults.SCHEMA}), timeout=15.0,
                      follow_redirects=True, headers={"Accept": "application/json"})
        if r.status_code != 200:
            raise CommandError(f"{url} answered HTTP {r.status_code}")
        kind = r.headers.get("content-type", "")
        if not kind.startswith("application/json"):
            raise CommandError(f"{url} answered {kind!r}, not JSON")
        try:
            doc = ruledefaults.check(r.json())
        except (ValueError, ruledefaults.Bad) as exc:
            raise CommandError(f"{url} answered a document no Rouh takes: {exc}") from None
        self.stdout.write(json.dumps({"url": url, "status": r.status_code, "content_type": kind,
                                      "revision": doc["revision"], "rules": len(doc["rules"]),
                                      "keys": [x["key"] for x in doc["rules"]]}))
