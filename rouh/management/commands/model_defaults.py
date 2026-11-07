"""``python manage.py model_defaults``: read or change the mode, the router's bar, the
tiers, each use's choice, the locks, Auto and Sync.

The same as the Models page in Settings and Rouh's own `model_defaults` tool
(`rouh/modeldefaults.py`): a mode (best, balanced or saver), two tiers (cheaper and
smart), each an ordered list of models across Anthropic, OpenAI, Google and xAI, the
first with a key here being the one asked, every use of a model on one of them or on
models of its own, and the two sharing choices (the anonymous totals, the blind
comparisons).
How deeply a model thinks comes with the model and is not set here.
With no options it says what they are. It is here for a job working on this
machine that Petar has asked to change them: he asked on 27 September 2026 that
such a request change these values, not the code.

    python manage.py model_defaults
    python manage.py model_defaults --mode saver
    python manage.py model_defaults --bar 95        (or --bar service)
    python manage.py model_defaults --tier cheaper=claude-sonnet-5        (to the front)
    python manage.py model_defaults --tier smart=claude-opus-5-5,gemini-4-argon,grok-4.7
    python manage.py model_defaults --main smart=google        (its first Google model to the front)
    python manage.py model_defaults --use chat_title=smart --use heartbeat_check=off
    python manage.py model_defaults --use run_summary=claude-sonnet-5      (Custom)
    python manage.py model_defaults --use run_summary=gemini-3.8-flash,gpt-6-luna
    python manage.py model_defaults --share off --compare on --compare-per-day 2
    python manage.py model_defaults --lock code_runs --unlock smart
    python manage.py model_defaults --auto off        (or on; both boxes)
    python manage.py model_defaults --auto off --box uses
    python manage.py model_defaults --sync --box tiers
    python manage.py model_defaults --undo-sync
    python manage.py model_defaults --reset --box uses
    python manage.py model_defaults --fetch-standard

`--org` is the organisation, and is only needed on an install with more than
one person in it: otherwise it is the organisation Rouh itself would use
(`modeldefaults.org_now`). Everything that asks a model reads them fresh, so
the next turn, run or feedback uses a change made here at once. An open page
only shows it the next time it opens Settings: this is not the server, and has
no way to tell a page anything.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from rouh import modeldefaults, modelstandard
from rouh.config import config


class Command(BaseCommand):
    help = ("Read or change the mode, the router's bar, the two tiers' lists, each use's choice, the "
            "locks, Auto and Sync, and the two sharing choices.")

    def add_arguments(self, parser):
        parser.add_argument("--org", default="", help="the organisation, when there is more than one")
        parser.add_argument("--mode", choices=modeldefaults.MODES,
                            help="the mode: best, balanced (the router decides) or saver")
        parser.add_argument("--bar", metavar="PERCENT",
                            help="the router's bar set by hand, such as 95, or 'service' for the service's")
        parser.add_argument("--tier", action="append", default=[], metavar="TIER=MODEL[,MODEL...]",
                            help="one model moved to the front of a tier, or its whole list in order: "
                                 + ", ".join(modeldefaults.TIERS))
        parser.add_argument("--main", action="append", default=[], metavar="TIER=PROVIDER",
                            help="a provider's first model on a tier moved to its front: "
                                 "anthropic, openai, google or xai")
        parser.add_argument("--share", choices=("on", "off"),
                            help="share the anonymous daily totals with rouh.land")
        parser.add_argument("--compare", choices=("on", "off"),
                            help="blind comparisons (they send a request to a second provider)")
        parser.add_argument("--compare-per-day", type=int, metavar="N",
                            help="at most this many comparisons a person a day")
        parser.add_argument("--use", action="append", default=[], metavar="ID=CHOICE",
                            help="a use on a tier, off, or a model's id (Custom): "
                                 + ", ".join(modeldefaults.BY_ID))
        parser.add_argument("--lock", action="append", default=[], metavar="ITEM",
                            help="a tier or a use to lock")
        parser.add_argument("--unlock", action="append", default=[], metavar="ITEM",
                            help="a tier or a use to unlock")
        parser.add_argument("--box", choices=modeldefaults.BOXES,
                            help="the box --auto, --sync and --reset are for: tiers (Models) or "
                                 "uses (Each use); both when not given")
        parser.add_argument("--auto", choices=("on", "off"),
                            help="Auto on (the Rouh model service; while either box is on, the "
                                 "day's counts and double calls) or off (the manual settings)")
        parser.add_argument("--sync", action="store_true",
                            help="make the box's manual settings the service's, except what is locked")
        parser.add_argument("--undo-sync", action="store_true",
                            help="put back what the last Sync or Reset changed")
        parser.add_argument("--reset", action="store_true",
                            help="the box's manual settings not locked back to the defaults")
        parser.add_argument("--fetch-standard", action="store_true",
                            help="fetch the published standard now, rather than at its daily time")
        parser.add_argument("--by", default="manage.py", help="who is changing them, for Settings")

    def handle(self, *args, **options):
        org = options["org"] or modeldefaults.org_now()
        if options["fetch_standard"]:
            said = modelstandard.fetch(config)
            self.stdout.write(f"Standard: {said.get('revision') or said.get('error')}")
        by = options["by"]
        try:
            box = options["box"]
            if options["mode"]:
                modeldefaults.put(org, "mode", mode=options["mode"], by=by, cfg=config)
                self.stdout.write(f"The mode is {options['mode']}.")
            if options["bar"]:
                bar = None if options["bar"] in ("service", "standard") else options["bar"]
                modeldefaults.put(org, "bar", bar=bar, by=by, cfg=config)
                self.stdout.write("Changed the router's bar.")
            if options["auto"]:
                modeldefaults.put(org, "auto", on=options["auto"] == "on", box=box, by=by, cfg=config)
                self.stdout.write(f"Auto {options['auto']} for {box or 'both boxes'}.")
            if options["sync"]:
                n = modeldefaults.put(org, "sync", box=box, by=by, cfg=config)
                self.stdout.write(f"Synced with the service: {n} changed.")
            if options["undo_sync"]:
                n = modeldefaults.put(org, "undo_sync", by=by, cfg=config)
                self.stdout.write(f"Undid the last Sync: {n} put back.")
            if options["reset"]:
                n = modeldefaults.put(org, "reset", box=box, by=by, cfg=config)
                self.stdout.write(f"Reset to the defaults: {n} changed.")
            if options["share"]:
                modeldefaults.put(org, "share", on=options["share"] == "on", by=by, cfg=config)
                self.stdout.write(f"Sharing the totals: {options['share']}.")
            if options["compare"] or options["compare_per_day"] is not None:
                modeldefaults.put(org, "compare", on=None if not options["compare"] else options["compare"] == "on",
                                  per_day=options["compare_per_day"], by=by, cfg=config)
                self.stdout.write("Changed the blind comparisons.")
            for said in options["tier"]:
                tier, _, model = str(said).partition("=")
                if "," in model:
                    modeldefaults.put(org, tier.strip(), models=model.split(","), by=by, cfg=config)
                else:
                    modeldefaults.put(org, tier.strip(), model=model.strip(), by=by, cfg=config)
                self.stdout.write(f"Changed {tier.strip()}.")
            for said in options["main"]:
                tier, _, main = str(said).partition("=")
                modeldefaults.put(org, tier.strip(), main=main.strip(), by=by, cfg=config)
                self.stdout.write(f"Moved {main.strip()}'s model to the front of {tier.strip()}.")
            for said in options["use"]:
                use, _, tier = str(said).partition("=")
                if use.strip() not in modeldefaults.BY_ID or not tier.strip():
                    raise CommandError(f"--use {said!r}: it is ID=TIER, and the ids are "
                                       + ", ".join(modeldefaults.BY_ID))
                if "," in tier:
                    modeldefaults.put(org, use.strip(), models=tier.split(","), by=by, cfg=config)
                else:
                    modeldefaults.put(org, use.strip(), tier=tier.strip(), by=by, cfg=config)
                self.stdout.write(f"Changed {use.strip()}.")
            for item in options["lock"]:
                modeldefaults.put(org, item, lock=True, by=by, cfg=config)
                self.stdout.write(f"Locked {item}.")
            for item in options["unlock"]:
                modeldefaults.put(org, item, lock=False, by=by, cfg=config)
                self.stdout.write(f"Unlocked {item}.")
        except modeldefaults.Refused as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"{org}: {modeldefaults.said(org, config)}")
