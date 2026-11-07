"""Where the nightly Rouh feature run picks its ideas: the Incubator, and nowhere else.

Petar, 4 November 2026: "now can you modify the nightly build to use the incubator to pick ideas,
rather than its own list it used to use?" Since 3 November the night's brief had only told the run to
read the Incubator with `rouh-incubator`; when that could not reach Rouh (night 33, a Rouh serving an
older commit), the night went back to the task's `ideas.md` and wrote its new ideas into `ledger.md`
as I-180 to I-183. So the choosing is Rouh's now, not a sentence in a brief:

- **Which ideas a night may pick** (`pickable`, `why_not`): an idea of the Incubator that is New or
  Triaged, not tagged technical, never handed to Gene therapy (no feedback or feature request) and
  not already something built (`built_as`), and the first of any ideas that carry the same title.
  Go is not pickable: Go hands an idea to Gene therapy, which builds it, and a night building it
  too would build it twice. In build, Built, Parked, Rejected and Merged are not either. Nothing
  here changes a status to make an idea pickable; only what a night picks, adds or drops moves.
- **What the night is told** (`brief_block`): that rule, and the pickable ideas as Rouh read them
  when the night started, with their INC numbers, highest score first (`rouh/incubator_score.py`).
  An idea a night proposes again is not added twice: the one there is gains a proposed_again in its
  history, which is demand, and is scored again.
- **What the night does with them** (`act`, the tool `nightly_idea`, through the same
  `/internal/nightly` the night's other tools use, so it works whenever they do): list, read, pick
  (In build, refused for an idea the rule leaves out), add (source nightly, refused when the
  Incubator already has that title), and drop (Parked or Rejected, with why). An idea a night
  built is linked to its gene in Mutations and set Built by `nightly_gene` with `ideas`
  (`built`).
- **The old list is kept** (`adopt_legacy`, at every night's start): every `### I-nnn` entry of
  the task's `ideas.md` not yet in the Incubator, and every idea a night wrote only into
  `ledger.md` (`**Idea added** - I-nnn, ...`), is added once, with source nightly, its words as
  they were written and its I- number as its name in its source. `ideas.md` and `ledger.md` are
  read and never written.

Every row is the night's person's: every call names their `org_id` and `user_id` (`incubator`).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from . import incubator

log = logging.getLogger("rouh.nightly_ideas")

#: The statuses a night may pick from. Go is Gene therapy's, so it is not one of them.
PICKABLE = ("new", "triaged")
#: An idea tagged so is not a night's: technical work is the refactoring run's.
NOT_A_NIGHTS = ("technical",)
#: How many pickable ideas the brief lists; the rest are a `nightly_idea list` away.
IN_BRIEF = 80

RULE = ("A night picks only an idea of the Incubator that is New or Triaged, not tagged technical, "
        "never handed to Gene therapy and not already built, and only the first of ideas with the same "
        "title. Go, In build, Built, Parked, Rejected and Merged are never picked.")


def _norm(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).split())


def why_not(row) -> str:
    """Why the night may not pick this idea, or "" when it may."""
    name = incubator.code(row.number)
    if row.status == "go":
        return f"{name} is Go: it was handed to Gene therapy, which builds it, so a night does not build it too."
    if row.status not in PICKABLE:
        return f"{name} is {incubator.STATUS_NAMES.get(row.status, row.status)}; a night picks only New or Triaged ideas."
    if any(t in NOT_A_NIGHTS for t in (row.tags or [])):
        return f"{name} is tagged technical, which is the refactoring run's work, not a night's."
    if row.feedback_id or row.request_id:
        return f"{name} was handed to Gene therapy already, which builds it."
    if row.built_as:
        return f"{name} is already built, as {row.built_as}."
    return ""


def pickable(who, *, most: int = 0) -> list:
    """The ideas a night may pick, highest score first, with ideas that repeat a title left out."""
    rows = (incubator._rows(who).filter(status__in=PICKABLE, feedback_id="", request_id="", built_as="")
            .order_by("number"))
    titles = {}
    for r in incubator._rows(who).exclude(status="merged").order_by("number").values_list("number", "title"):
        titles.setdefault(_norm(r[1]), r[0])
    out = []
    for row in rows:
        if why_not(row) or titles.get(_norm(row.title), row.number) != row.number:
            continue
        out.append(row)
    # Highest score first (`rouh/incubator_score.py`), so the person's stars reach the night; an idea
    # not scored yet after every scored one, oldest first.
    from . import incubator_score

    def rank(r):
        s = incubator_score.compute(r.score_parts or {}, r.stars_suggested, r.stars_mine)
        return (s is None, -(s or 0), r.number)

    out.sort(key=rank)
    return out[:most] if most else out


def _line(row) -> str:
    from . import incubator_score

    score = incubator_score.compute(row.score_parts or {}, row.stars_suggested, row.stars_mine)
    return (f"- {incubator.code(row.number)} (score {round(score) if score is not None else 'not yet'}, "
            f"{incubator.STATUS_NAMES.get(row.status, row.status)}, "
            f"{incubator.KIND_NAMES.get(row.kind, row.kind)}, "
            f"{incubator.CATEGORY_NAMES.get(row.category, row.category or 'no category')}, "
            f"{incubator.SOURCE_NAMES.get(row.source, row.source)}"
            + (f", {row.ref}" if row.ref else "") + f"): {row.title}")


def brief_block(who) -> str:
    """The brief's "Where the ideas are": the rule, the tool, and tonight's pickable ideas."""
    rows = pickable(who)
    lines = [
        "## Where the ideas are",
        "",
        "The ideas are the Incubator's (Evolution), the one list of ideas for new genes and mutations. "
        "Pick only from it: never from the task's ideas.md or ledger.md, which stay as they were for their "
        "history and are not written to. Where run.md says ideas.md, it means the Incubator. "
        "Rouh has already put every idea of ideas.md, and every idea a night wrote only into ledger.md, "
        "into the Incubator, with its I- number as its name there.",
        "",
        RULE,
        "",
        "Use `nightly_idea`, which Rouh answers for this night: `list` (the pickable ideas, or `q` to "
        "search every idea), `read` one whole, `pick` it (it goes In build; Rouh refuses one the rule "
        "leaves out), `add` what your research finds (source nightly; Rouh refuses a title the Incubator "
        "already has, and names it), and `drop` one you will not build (`parked` or `rejected`, with why). "
        "Give `nightly_gene` the INC numbers it was built from as `ideas`, and Rouh links each to its gene "
        "in Mutations and sets it Built. `rouh-incubator` reaches the same list, if you need more of it.",
        "",
    ]
    if not rows:
        lines.append("No idea is pickable tonight: research, `add` what you find, then pick it.")
    else:
        lines.append(f"The {len(rows)} pickable ideas as tonight started"
                     + (f", the first {IN_BRIEF} listed (`nightly_idea list` has the rest)" if len(rows) > IN_BRIEF else "")
                     + ", highest score first (the Incubator's score: impact, confidence, frequency, pain, the "
                     "person's stars, clarity and risk). Prefer the highest you can build well tonight:")
        lines.append("")
        lines += [_line(r) for r in rows[:IN_BRIEF]]
    return "\n".join(lines)


# --- the night's tool -------------------------------------------------------------------------------


def _night_link(night) -> dict:
    return {"kind": "link", "label": f"Nightly run, night {night.number}" + (f" (run {night.run_id})" if night.run_id else ""),
            "href": "/evolution/nightly"}


def act(who, night, args: dict) -> str:
    """`nightly_idea`: list, read, pick, add or drop, for the night's own run."""
    args = args if isinstance(args, dict) else {}
    do = str(args.get("do") or "list").strip().lower()
    by = f"Night {night.number}" + (f", run {night.run_id}" if night.run_id else "")
    try:
        if do == "list":
            q = str(args.get("q") or "").strip()
            if q:
                found = incubator.listing(who, q=q, limit=60)
                if not found:
                    return f"No idea in the Incubator has the words {q!r}."
                return "\n".join(incubator.line_for_model(v) for v in found)
            rows = pickable(who)
            if not rows:
                return "No idea is pickable now: research, add what you find, then pick it."
            return f"{len(rows)} pickable ideas. {RULE}\n" + "\n".join(_line(r) for r in rows)
        if do == "read":
            return incubator.detail_for_model(incubator.one(who, args.get("id")))
        if do == "pick":
            row = incubator.find(who, args.get("id"))
            why = why_not(row)
            if why:
                raise incubator.Refused(why)
            first = next((r for r in pickable(who) if r.id == row.id), None)
            if first is None:
                raise incubator.Refused(f"{incubator.code(row.number)} repeats the title of an earlier idea; "
                                        "pick that one, or drop this one as the same.")
            note = f"Picked by night {night.number}." + (f" {args['note']}" if args.get("note") else "")
            incubator.link(who, row.number, by=by, **_night_link(night))
            v = incubator.set_status(who, row.number, "in_build", by=by, note=note)
            return f"{v['code']} is In build, picked by night {night.number}: {v['title']}"
        if do == "add":
            title = " ".join(str(args.get("title") or "").split())
            same = next((r for r in incubator._rows(who).exclude(status="merged")
                         if _norm(r.title) == _norm(title)), None) if title else None
            if same is not None:
                # Proposed again: that is demand, which raises its frequency when it is scored again.
                incubator._event(who, same.id, "proposed_again", by=by, note=f"Night {night.number} proposed it again.")
                from . import incubator_score

                incubator_score.queue(who, same.id)
                raise incubator.Refused(f"The Incubator has that idea already: {incubator.code(same.number)}, "
                                        f"{incubator.STATUS_NAMES.get(same.status, same.status)}, {same.title}.")
            v = incubator.add(who, title=title, text=str(args.get("text") or ""), kind=str(args.get("kind") or ""),
                              gene=str(args.get("gene") or ""), category=str(args.get("category") or ""),
                              source="nightly", ref=str(args.get("ref") or ""), links=[_night_link(night)],
                              by=by, what="added")
            return f"Added {v['code']}, New, from the nightly run: {v['title']}"
        if do == "drop":
            status = str(args.get("status") or "parked").strip().lower()
            if status not in ("parked", "rejected"):
                raise incubator.Refused("A dropped idea is parked or rejected.")
            why = " ".join(str(args.get("why") or "").split())
            if len(why) < 10:
                raise incubator.Refused("why is the reason, in a sentence, so the idea is not proposed again for it.")
            v = incubator.set_status(who, args.get("id"), status, by=by, note=f"Night {night.number}: {why}")
            return f"{v['code']} is {v['status_name']}: {why}"
    except (incubator.NotFound, LookupError):
        raise incubator.Refused(f"There is no idea {args.get('id')!r} in the Incubator.")
    raise incubator.Refused("do is list, read, pick, add or drop.")


def built(who, night, ideas, gene_key: str) -> str:
    """After `nightly_gene` registered `gene_key`: each idea it was built from linked to it and Built.
    The words for the run, saying what moved and what could not."""
    from .models import MutationsGene

    if not ideas:
        return ""
    if isinstance(ideas, str):
        ideas = [i for i in re.split(r"[,\s]+", ideas) if i]
    gene = (MutationsGene.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id), key=str(gene_key or ""))
            .order_by("-id").first()) if gene_key else None
    by = f"Night {night.number}" if night is not None else "the nightly run"
    done, failed = [], []
    for ident in list(ideas)[:10]:
        try:
            row = incubator.find(who, ident)
            if row.status in ("merged", "rejected"):
                failed.append(f"{incubator.code(row.number)} is {incubator.STATUS_NAMES[row.status]}")
                continue
            if gene is not None:
                incubator.link(who, row.number, kind="gene", label=f"Gene {gene.key}: {gene.name}",
                               href=f"/evolution/mutations/gene/{gene.id}", by=by)
            if night is not None:
                incubator.link(who, row.number, by=by, **_night_link(night))
            incubator.set_status(who, row.number, "built", by=by, note=f"Built by {by} as the gene {gene_key}.")
            done.append(incubator.code(row.number))
        except (incubator.NotFound, incubator.Refused) as exc:
            failed.append(f"{ident}: {exc}")
    said = (f"In the Incubator, {', '.join(done)} {'is' if len(done) == 1 else 'are'} Built, linked to {gene_key}." if done else "")
    if failed:
        said += (" " if said else "") + "Not moved: " + "; ".join(failed) + "."
    return said


# --- the old list, kept -----------------------------------------------------------------------------

_LEDGER_ADDED = re.compile(r"^- \*\*Idea added\*\* - (I-\d{3,4}), (.+)$", re.M)
_LEDGER_PICKED = re.compile(r"^- \*\*Picked\*\* - (I-\d{3,4}) as \*\*(.+?)\*\*", re.M)
_LEDGER_NIGHT = re.compile(r"^## (\d{4}-\d{2}-\d{2}) · run (\S+)", re.M)


def ledger_ideas(text: str) -> list[dict]:
    """Every idea a night wrote into ledger.md with an I- number: its line as written, the night's
    heading it is under, and the gene name it was picked as, if it was."""
    heads = [(m.start(), m.group(0)) for m in _LEDGER_NIGHT.finditer(text)]
    picked = {m.group(1): m.group(2) for m in _LEDGER_PICKED.finditer(text)}
    out, seen = [], set()
    for m in _LEDGER_ADDED.finditer(text):
        ref = m.group(1)
        if ref in seen:
            continue
        seen.add(ref)
        head = next((h for at, h in reversed(heads) if at < m.start()), "")
        out.append({"ref": ref, "line": m.group(0), "said": m.group(2).rstrip(), "night": head.lstrip("# ").strip(),
                    "picked_as": picked.get(ref, ""), "at": text.count("\n", 0, m.start()) + 1})
    return out


def _title_of(said: str) -> str:
    """The idea's words without the estimate and the labels after them: "an invitation ..., 0.5, `acts`"."""
    t = re.split(r",\s*\d+(?:\.\d+)?\s*,", said, maxsplit=1)[0].strip().rstrip(".")
    return (t[:1].upper() + t[1:]) if t else said


def adopt_legacy(who, root: str, folder: str, *, by: str = "the nightly run, from its old list") -> dict:
    """Put the nightly run's old ideas into the Incubator once: ideas.md's entries, then ledger.md's
    ideas that never reached ideas.md. Never writes either file, never adds one twice. The counts."""
    from . import incubator_import as imp

    base = Path(root or "")
    task = base / folder if folder else None
    report = {"ideas": 0, "ledger": 0, "already": 0}
    if task is None or not task.is_dir():
        return report
    have = set(incubator._rows(who).exclude(source_key="").values_list("source_key", flat=True))
    refs = set(incubator._rows(who).filter(source="nightly").exclude(ref="").values_list("ref", flat=True))
    # Merged ideas keep their own source keys, so an idea merged into another is never added again.
    in_list = set()
    ideas = task / "ideas.md"
    if ideas.is_file():
        items = imp._list_items(ideas, base, "nightly", "I", imp.NIGHTLY_STATUS, {}, {"nightly": {}})
        for item in items:
            in_list.add(item["ref"])
            if item["source_key"] in have or item["ref"] in refs:
                report["already"] += 1
                continue
            imp.put_in(who, item, by=by)
            have.add(item["source_key"])
            report["ideas"] += 1
    ledger = task / "ledger.md"
    if ledger.is_file():
        from . import pages

        rel = imp._rel(base, ledger)
        for e in ledger_ideas(imp._read(ledger)):
            key = f"nightly:{e['ref']}"
            if e["ref"] in in_list or key in have or e["ref"] in refs:
                report["already"] += 1
                continue
            status, gene, tags = "new", None, ["from the ledger"]
            if e["picked_as"]:
                from .models import MutationsGene

                gene = (MutationsGene.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id),
                                                     name__iexact=e["picked_as"]).order_by("-id").first())
                status = "built" if gene is not None else "in_build"
                if gene is None:
                    tags.append("status to check")
            text = f"{e['line']}\n\n(ledger.md, {e['night']}, line {e['at']}" + (
                f"; picked there as {e['picked_as']})" if e["picked_as"] else ")")
            links = [{"kind": "file", "label": f"ledger.md, {e['ref']} (line {e['at']})",
                      "href": pages.url_for(rel), "path": rel}]
            v = incubator.add(who, title=_title_of(e["said"]), text=text, source="nightly", ref=e["ref"],
                              source_key=key, status=status, links=links, tags=tags,
                              source_status=("picked" if e["picked_as"] else "added") + " (ledger.md)",
                              by=by, what="imported")
            if gene is not None:
                incubator.link(who, v["number"], kind="gene", label=f"Gene {gene.key}: {gene.name}",
                               href=f"/evolution/mutations/gene/{gene.id}", by=by)
            have.add(key)
            report["ledger"] += 1
    return report


__all__ = ["PICKABLE", "RULE", "act", "adopt_legacy", "brief_block", "built", "ledger_ideas", "pickable", "why_not"]
