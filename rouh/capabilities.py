"""What Rouh can do for somebody other than the owner, as the code that does it declares it, and
whether a contact may have it done: capabilities, their contracts, and grants judged as data.

Petar, 21 October 2026, approving the design after the audit of run 2be7789c (card 1796): a grant
made from a case was free text a model wrote, given with one press, and matched to later asks
only by a model reading that text again. "Every gene/tool declares stable capability/action IDs,
resource types, supported constraint schema and actual effects ... Plain prose is explanation
only, never enforcement." So (CAPABILITIES.md):

- **A capability is declared by its gene** (`rouh/genes/manifests/<gene>.json`, `capabilities`):
  an id, a version, what it does in a verb phrase (`said`), the kind of thing it acts on
  (`RESOURCES`), where its authority comes from (`AUTHORITIES`), its effects (`EFFECTS`, a closed
  list in code), the limits it can enforce (`CONSTRAINTS`), and every tool that carries it out with
  how that tool's arguments name the resource and the limited values (`Binding`). The catalogue is
  whatever the deployed manifests declare (`catalogue`): a gene deployed tomorrow brings its own,
  and nothing here lists them. A model never makes one.
- **A contract is what a capability does**, without its words (`contract`), and every version's
  contract is locked in `capabilities.lock.json` (`lock_problems`, `python -m rouh.capabilities
  check`). A grant is made for a version; a later version is used for it only when it is proved
  compatible (`compatible`): no new effect, no new tool, the same resource and authority, the same
  limits no wider. Otherwise the grant is suspended, with the reason, and an unknown version fails
  closed (`version_state`).
- **A grant is data** (`propose`, `validate`, `wording`, `digest`): a contact, a capability, an
  exact scope, typed limits and a lifetime, worded by this code from exactly those fields, and
  approved by the digest of what the owner was shown.
- **Authorisation is code** (`authorize`, `check_call`): the subject, the capability and its
  version, every resource inside the scope, every value inside the limits, the lifetime and the
  uses; and again on the actual arguments of every tool call of a case's turn, immediately before
  it runs.

Standard library only, so `rouh/mail_replay.py` runs the very same code.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFESTS = HERE / "genes" / "manifests"
LOCK = HERE / "capabilities.lock.json"

# --- the closed vocabularies: what code knows how to say and to check -----------------------

#: Every effect a capability may declare: what it is in words, to the owner, about the contact
#: ("them"), and the hard limit it is (`grants.HARD_LIMITS`), or "". A capability with a hard-limit
#: effect is never grantable to a contact, unless a grant may lift that limit (`LIFTABLE`).
EFFECTS: dict[str, tuple[str, str]] = {
    "reply": ("answer them on their own email, Telegram or Slack", ""),
    "read_tasks": ("read the task, its notes, pages and steps", ""),
    "change_task": ("add to or change the task, and use Ask AI on its pages", ""),
    "decide": ("decide for you on the task, never on money, deleting, publishing, sending or "
               "anybody's grants", ""),
    "share_page": ("share pages of tasks they may read with them", ""),
    "make_task": ("make a new task in your Personal column that you and they both add to", ""),
    "keep_note": ("add notes they give to your memory, marked as theirs", ""),
    "schedule": ("put items on Clockwork that are theirs, doing at a time what they may already "
                 "have done", ""),
    "start_job": ("start work for them in your workspace, filed as a Guest task, with the result "
                  "sent to them", ""),
    "read_inbox": ("read your own inbox for them, as far as their page allows", ""),
    "change_inbox": ("label, archive and draft in your own inbox for them", ""),
    "calendar": ("add events to your calendar and move events made for them", "time"),
    "money": ("pay, buy or book with your money", "money"),
    "accounts": ("reach your accounts or passwords", "accounts"),
    "as_owner": ("send as you, in your name", "as_owner"),
    "delete_mail": ("delete your mail", "delete_mail"),
    "forward_outside": ("forward your mail outside", "forward_outside"),
    "third_party": ("send or share with somebody other than them", "third_party"),
    "publish": ("publish or make public", "publish"),
    "irreversible": ("do what cannot be undone", "irreversible"),
}

#: The hard limits a grant may lift for a contact: committing the owner's time, by Your calendar
#: (`grants.LIFTS`, Petar, 15 October 2026). Every other hard limit stays the owner's, ask by ask.
LIFTABLE = frozenset({"time"})

#: The kinds of thing a capability acts on, and how a scope of them is checked.
#: none: nothing; self: what belongs to the contact themselves; task: the owner's tasks by number,
#: each with its steps; calendar: the owner's calendars by id.
RESOURCES = {"none": "nothing", "self": "what is theirs", "task": "tasks", "calendar": "calendars"}
SCOPED = frozenset({"task", "calendar"})

#: Where a capability's authority comes from: "grant", a grant the contact holds (on their page,
#: or a structured grant); "task_level", their level on the task it names (`rouh/task_access.py`).
AUTHORITIES = {"grant", "task_level"}
LEVELS = ("view", "edit", "decide")

#: The limits a capability can declare, by type: "count", a whole number between `min` and `max`
#: (how many a day); "choice", some of `values` (who an item goes to).
CONSTRAINTS = {"count", "choice"}

#: How long a grant lasts.
ONCE, UNTIL, STANDING = "once", "until", "standing"
LIFETIMES = (ONCE, UNTIL, STANDING)
#: The furthest a grant "until a date" may run.
MOST_DAYS = 366

#: A grant's states. Only an active one allows anything.
PROPOSED, ACTIVE, REJECTED, REVOKED, SPENT, SUSPENDED, REPLACED = (
    "proposed", "active", "rejected", "revoked", "spent", "suspended", "replaced")

ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
WORD_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
TASK_RE = re.compile(r"^\d{1,6}$")
TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
#: What is never an id in a scope: a wildcard, a pattern, or nothing.
WILD = re.compile(r"[*?%]|^all$|^any$|^every", re.I)

# --- a capability, as declared -------------------------------------------------------------


@dataclass(frozen=True)
class Binding:
    """How one tool carries out a capability: the arguments that make a call this capability
    (`when`, with `defaults` for an argument not given), the argument that names the resource and
    its default, the arguments that carry the limited values, and whether a call counts as a use
    (a read does not). `guard` "tool" is a call whose resource the tool's own code checks."""

    tool: str
    when: tuple = ()          # ((arg, (value, ...)), ...)
    defaults: tuple = ()      # ((arg, value), ...)
    resource: str = ""
    resource_default: str = ""
    values: tuple = ()        # ((constraint, arg), ...)
    value_defaults: tuple = ()
    value_map: tuple = ()     # ((constraint, ((said, value), ...)), ...)
    counts: bool = True
    guard: str = ""

    def as_dict(self) -> dict:
        out: dict = {"tool": self.tool}
        if self.when:
            out["when"] = {k: list(v) for k, v in self.when}
        if self.defaults:
            out["defaults"] = dict(self.defaults)
        if self.resource:
            out["resource"] = self.resource
        if self.resource_default:
            out["resource_default"] = self.resource_default
        if self.values:
            out["values"] = dict(self.values)
        if self.value_defaults:
            out["value_defaults"] = dict(self.value_defaults)
        if self.value_map:
            out["value_map"] = {k: dict(v) for k, v in self.value_map}
        if not self.counts:
            out["counts"] = False
        if self.guard:
            out["guard"] = self.guard
        return out

    def matches(self, args: dict) -> bool:
        given = {**dict(self.defaults), **{k: v for k, v in (args or {}).items()
                                            if v not in (None, "")}}
        return all(str(given.get(arg, "")) in values for arg, values in self.when)

    def resource_of(self, args: dict) -> str:
        if not self.resource:
            return ""
        said = str((args or {}).get(self.resource) or "").strip().lstrip("#")
        return said or self.resource_default

    def values_of(self, args: dict) -> dict:
        out = {}
        maps = {k: dict(v) for k, v in self.value_map}
        for name, arg in self.values:
            raw = (args or {}).get(arg)
            if raw in (None, ""):
                raw = dict(self.value_defaults).get(name)
            if raw in (None, ""):
                continue
            said = str(raw).strip().lower()
            out[name] = maps.get(name, {}).get(said, said)
        return out


@dataclass(frozen=True)
class Constraint:
    name: str
    type: str
    said: str
    min: int = 0
    max: int = 0
    default: object = None
    values: tuple = ()        # ((value, words), ...) for a choice

    def as_dict(self) -> dict:
        out = {"type": self.type, "said": self.said, "default": self.default}
        if self.type == "count":
            out.update(min=self.min, max=self.max)
        else:
            out["values"] = dict(self.values)
        return out

    def contract(self) -> dict:
        """What the limit is, without its words."""
        if self.type == "count":
            return {"type": "count", "min": self.min, "max": self.max}
        return {"type": "choice", "values": sorted(v for v, _ in self.values)}


@dataclass(frozen=True)
class Capability:
    id: str
    version: int
    gene: str
    name: str
    said: str
    action: str
    resource: str
    authority: str
    effects: tuple
    bindings: tuple = ()
    constraints: tuple = ()   # (Constraint, ...)
    aliases: tuple = ()
    level: str = ""
    legacy_grant: str = ""
    rows: bool = False
    about: str = ""

    @property
    def reserved(self) -> list[str]:
        """The hard limits its effects are."""
        return [EFFECTS[e][1] for e in self.effects if EFFECTS.get(e, ("", ""))[1]]

    @property
    def grantable(self) -> bool:
        """Whether a contact can be given it as a grant of its own: declared so, its authority a
        grant, and no hard limit in its effects that no grant may lift."""
        return (self.rows and self.authority == "grant"
                and all(limit in LIFTABLE for limit in self.reserved))

    def constraint(self, name: str) -> Constraint | None:
        return next((c for c in self.constraints if c.name == name), None)

    def tools(self) -> list[str]:
        return list(dict.fromkeys(b.tool for b in self.bindings))

    def as_dict(self) -> dict:
        return {"id": self.id, "version": self.version, "gene": self.gene, "name": self.name,
                "said": self.said, "action": self.action, "aliases": list(self.aliases),
                "resource": self.resource, "authority": self.authority, "level": self.level,
                "legacy_grant": self.legacy_grant, "rows": self.rows,
                "effects": list(self.effects),
                "effects_said": [EFFECTS[e][0] for e in self.effects if e in EFFECTS],
                "tools": [b.as_dict() for b in self.bindings],
                "constraints": {c.name: c.as_dict() for c in self.constraints},
                "grantable": self.grantable, "about": self.about}


# --- reading declarations --------------------------------------------------------------------


def declaration_problems(raw, gene: str = "") -> list[str]:
    """Everything wrong with a manifest's `capabilities`, as sentences (`rouh/genes`)."""
    where = f"{gene or 'a manifest'}: capabilities"
    if not isinstance(raw, list):
        return [f"{where} is not a list"]
    out: list[str] = []
    for n, one in enumerate(raw, start=1):
        at = f"{where}[{n}]"
        if not isinstance(one, dict):
            out.append(f"{at} is not an object")
            continue
        known = {"id", "version", "name", "said", "action", "aliases", "resource", "authority",
                 "level", "legacy_grant", "rows", "effects", "tools", "constraints", "about"}
        for key in sorted(set(one) - known):
            out.append(f"{at} has a key the contract does not know: {key!r}")
        cid = one.get("id")
        if not (isinstance(cid, str) and ID_RE.match(cid)):
            out.append(f"{at}: id {cid!r} is not area.action in lower case")
            continue
        at = f"{where} {cid}"
        if not (isinstance(one.get("version"), int) and not isinstance(one.get("version"), bool)
                and one["version"] >= 1):
            out.append(f"{at}: version is not a whole number from 1")
        for key in ("name", "said"):
            if not (isinstance(one.get(key), str) and one[key].strip()):
                out.append(f"{at}: {key} is empty")
        if not (isinstance(one.get("action"), str) and WORD_RE.match(one["action"])):
            out.append(f"{at}: action is not one lower-case word")
        if not (isinstance(one.get("aliases", []), list)
                and all(isinstance(a, str) and WORD_RE.match(a) for a in one.get("aliases", []))):
            out.append(f"{at}: aliases is not a list of lower-case words")
        if one.get("resource") not in RESOURCES:
            out.append(f"{at}: resource is not one of {', '.join(RESOURCES)}")
        if one.get("authority") not in AUTHORITIES:
            out.append(f"{at}: authority is not one of {', '.join(sorted(AUTHORITIES))}")
        if one.get("authority") == "task_level":
            if one.get("level") not in LEVELS:
                out.append(f"{at}: a task_level capability needs level, one of {', '.join(LEVELS)}")
            if one.get("resource") != "task":
                out.append(f"{at}: a task_level capability acts on tasks")
            if one.get("rows"):
                out.append(f"{at}: a task_level capability is the task's permission, never a "
                           "grant of its own (rows)")
        effects = one.get("effects")
        if not (isinstance(effects, list) and effects
                and all(isinstance(e, str) and e in EFFECTS for e in effects)
                and len(set(effects)) == len(effects)):
            out.append(f"{at}: effects must be a non-empty list of {', '.join(EFFECTS)}")
        if "rows" in one and not isinstance(one["rows"], bool):
            out.append(f"{at}: rows is not true or false")
        if "legacy_grant" in one and not (isinstance(one["legacy_grant"], str)
                                          and re.match(r"^[a-z][a-z0-9_:-]{0,60}$",
                                                       one["legacy_grant"])):
            out.append(f"{at}: legacy_grant is not a grant key")
        names: set[str] = set()
        cons = one.get("constraints", {})
        if not isinstance(cons, dict):
            out.append(f"{at}: constraints is not an object")
            cons = {}
        for cname, c in cons.items():
            cat = f"{at} constraint {cname}"
            names.add(cname)
            if not WORD_RE.match(str(cname)):
                out.append(f"{cat}: its name is not one lower-case word")
            if not isinstance(c, dict) or c.get("type") not in CONSTRAINTS:
                out.append(f"{cat}: type is not one of {', '.join(sorted(CONSTRAINTS))}")
                continue
            if not (isinstance(c.get("said"), str) and c["said"].strip()):
                out.append(f"{cat}: said is empty")
            if c["type"] == "count":
                lo, hi, d = c.get("min"), c.get("max"), c.get("default")
                if not all(isinstance(x, int) and not isinstance(x, bool) for x in (lo, hi, d)) \
                        or not (1 <= lo <= d <= hi):
                    out.append(f"{cat}: a count needs whole numbers 1 <= min <= default <= max")
                elif "{n}" not in c.get("said", ""):
                    out.append(f"{cat}: a count's said needs {{n}}")
            else:
                vals = c.get("values")
                d = c.get("default")
                if not (isinstance(vals, dict) and vals and all(
                        WORD_RE.match(str(k)) and isinstance(v, str) and v.strip()
                        for k, v in vals.items())):
                    out.append(f"{cat}: a choice needs values, each a word with its words")
                elif not (isinstance(d, list) and d and all(x in vals for x in d)):
                    out.append(f"{cat}: a choice's default must be some of its values")
                elif "{values}" not in c.get("said", ""):
                    out.append(f"{cat}: a choice's said needs {{values}}")
        tools = one.get("tools", [])
        if not isinstance(tools, list):
            out.append(f"{at}: tools is not a list")
            tools = []
        for b in tools:
            if not isinstance(b, dict) or not TOOL_RE.match(str(b.get("tool") or "")):
                out.append(f"{at}: a tool binding needs a tool's name")
                continue
            bat = f"{at} tool {b['tool']}"
            for key in sorted(set(b) - {"tool", "when", "defaults", "resource",
                                        "resource_default", "values", "value_defaults",
                                        "value_map", "counts", "guard"}):
                out.append(f"{bat}: has a key the contract does not know: {key!r}")
            when = b.get("when", {})
            if not (isinstance(when, dict) and all(isinstance(v, list) and v and all(
                    isinstance(x, str) for x in v) for v in when.values())):
                out.append(f"{bat}: when is not {{argument: [values]}}")
            if b.get("resource") and one.get("resource") not in SCOPED:
                out.append(f"{bat}: names a resource argument for a capability that acts on "
                           f"{one.get('resource')}")
            if one.get("resource") in SCOPED and b.get("counts", True) and not b.get("resource") \
                    and b.get("guard") != "tool":
                out.append(f"{bat}: acts on {one.get('resource')} and names no resource argument "
                           "(or guard tool, when the tool checks it itself)")
            vals = b.get("values", {})
            if not isinstance(vals, dict) or any(k not in names for k in vals):
                out.append(f"{bat}: values names a limit the capability does not declare")
            if b.get("guard") not in (None, "", "tool"):
                out.append(f"{bat}: guard is only tool")
            if "counts" in b and not isinstance(b["counts"], bool):
                out.append(f"{bat}: counts is not true or false")
    return out


def _binding(raw: dict) -> Binding:
    return Binding(
        tool=raw["tool"],
        when=tuple(sorted((k, tuple(str(x) for x in v)) for k, v in (raw.get("when") or {}).items())),
        defaults=tuple(sorted((k, str(v)) for k, v in (raw.get("defaults") or {}).items())),
        resource=str(raw.get("resource") or ""),
        resource_default=str(raw.get("resource_default") or ""),
        values=tuple(sorted((k, str(v)) for k, v in (raw.get("values") or {}).items())),
        value_defaults=tuple(sorted((k, str(v)) for k, v in
                                    (raw.get("value_defaults") or {}).items())),
        value_map=tuple(sorted((k, tuple(sorted((str(a), str(b)) for a, b in v.items())))
                               for k, v in (raw.get("value_map") or {}).items())),
        counts=bool(raw.get("counts", True)), guard=str(raw.get("guard") or ""))


def _capability(raw: dict, gene: str) -> Capability:
    cons = []
    for name, c in (raw.get("constraints") or {}).items():
        if c["type"] == "count":
            cons.append(Constraint(name=name, type="count", said=c["said"], min=c["min"],
                                   max=c["max"], default=c["default"]))
        else:
            cons.append(Constraint(name=name, type="choice", said=c["said"],
                                   default=tuple(c["default"]),
                                   values=tuple((str(k), str(v)) for k, v in c["values"].items())))
    return Capability(
        id=raw["id"], version=int(raw["version"]), gene=gene, name=raw["name"].strip(),
        said=" ".join(raw["said"].split()), action=raw["action"],
        resource=raw["resource"], authority=raw["authority"], effects=tuple(raw["effects"]),
        bindings=tuple(_binding(b) for b in raw.get("tools") or []),
        constraints=tuple(sorted(cons, key=lambda c: c.name)),
        aliases=tuple(raw.get("aliases") or ()), level=str(raw.get("level") or ""),
        legacy_grant=str(raw.get("legacy_grant") or ""), rows=bool(raw.get("rows")),
        about=" ".join(str(raw.get("about") or "").split()))


@dataclass
class Catalogue:
    """Every capability the deployed manifests declare."""

    caps: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def get(self, key: str) -> Capability | None:
        """A capability by its id, its action word or an alias, or None."""
        key = str(key or "").strip().lower().replace(" ", "_").replace("-", "_")
        if key in self.caps:
            return self.caps[key]
        return next((c for c in self.caps.values() if key == c.action or key in c.aliases), None)

    def by_legacy(self, grant_key: str) -> list[Capability]:
        """The capabilities a grant on the contact page gives, by its key."""
        return [c for c in self.caps.values() if c.legacy_grant and c.legacy_grant == grant_key]

    def bindings_for(self, tool: str) -> list[tuple[Capability, Binding]]:
        return [(c, b) for c in self.caps.values() for b in c.bindings if b.tool == tool]

    def tools(self) -> set[str]:
        return {b.tool for c in self.caps.values() for b in c.bindings}

    def actions(self) -> list[Capability]:
        return sorted(self.caps.values(), key=lambda c: (c.gene, c.id))

    def brief(self) -> list[str]:
        """The catalogue as the reading is told it: one line per capability."""
        out = []
        for c in self.actions():
            res = {"none": "", "self": " (on what is theirs)", "task": " (on tasks: name each "
                   "task's number in resource)", "calendar": " (on calendars)"}[c.resource]
            limits = "; limits: " + ", ".join(
                f"{x.name} ({'a number' if x.type == 'count' else ' or '.join(v for v, _ in x.values)})"
                for x in c.constraints) if c.constraints else ""
            how = (f"needs {c.level} on the task" if c.authority == "task_level" else
                   "needs a grant")
            out.append(f"   - {c.id} (action {c.action}): {c.name}: {c.said}{res}. {how.capitalize()}"
                       f"{limits}.")
        return out


_CACHE: dict = {}


def catalogue(folder: Path | None = None) -> Catalogue:
    """The catalogue the manifests in `folder` declare, read again when any of them changed."""
    folder = Path(folder or MANIFESTS)
    files = sorted(folder.glob("*.json"))
    stamp = tuple((p.name, p.stat().st_mtime_ns) for p in files)
    hit = _CACHE.get(str(folder))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    found = Catalogue()
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            found.problems.append(f"{path.name}: is not JSON ({err})")
            continue
        if not isinstance(raw, dict) or "capabilities" not in raw:
            continue
        said = declaration_problems(raw["capabilities"], path.stem)
        if said:
            # A gene whose declarations are wrong brings none of them: fail closed.
            found.problems.extend(said)
            continue
        for one in raw["capabilities"]:
            if one["id"] in found.caps:
                found.problems.append(f"{path.stem}: capability {one['id']} is declared by "
                                      f"{found.caps[one['id']].gene} already")
                continue
            found.caps[one["id"]] = _capability(one, path.stem)
    words: dict[str, str] = {}
    for c in found.caps.values():
        for w in (c.action, *c.aliases):
            if w in words and words[w] != c.id:
                found.problems.append(f"{c.gene}: action {w} of {c.id} is {words[w]}'s already")
            words[w] = c.id
    _CACHE[str(folder)] = (stamp, found)
    return found


# --- contracts and versions ----------------------------------------------------------------


def contract(cap: Capability) -> dict:
    """What a capability does, without its words: what a grant made for it is bound to."""
    return {"resource": cap.resource, "authority": cap.authority, "level": cap.level,
            "rows": cap.rows, "effects": sorted(cap.effects),
            "tools": sorted((b.as_dict() for b in cap.bindings),
                            key=lambda d: json.dumps(d, sort_keys=True)),
            "constraints": {c.name: c.contract() for c in cap.constraints}}


def contract_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def read_lock(path: Path | None = None) -> dict:
    """{capability: {version (as text): {"hash", "contract"}}}; {} when there is none."""
    try:
        raw = json.loads(Path(path or LOCK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw.get("capabilities", {}) if isinstance(raw, dict) else {}


def lock_problems(found: Catalogue, lock: dict) -> list[str]:
    """Where the manifests and the lock disagree: a contract changed without a new version, a
    version locked differently, or one not locked at all."""
    out = list(found.problems)
    for c in found.caps.values():
        mine = contract(c)
        kept = (lock.get(c.id) or {}).get(str(c.version))
        if kept is None:
            out.append(f"{c.id} version {c.version} is not locked: run python -m "
                       "rouh.capabilities lock")
        elif kept.get("hash") != contract_hash(mine) or kept.get("contract") != mine:
            out.append(f"{c.id} changed what it does at version {c.version}: "
                       + "; ".join(differences(kept.get("contract") or {}, mine) or ["its contract"])
                       + ". A new version is needed (raise version, then lock).")
        newer = [int(v) for v in (lock.get(c.id) or {}) if str(v).isdigit() and int(v) > c.version]
        if newer:
            out.append(f"{c.id} is declared at version {c.version}, and version {max(newer)} is "
                       "locked: a version never goes back.")
    return out


def lock_with(found: Catalogue, lock: dict) -> tuple[dict, list[str]]:
    """The lock with every declared version that is not in it yet, or what refuses it: a version
    already locked with another contract is never written over."""
    out = {k: dict(v) for k, v in lock.items()}
    said = []
    for c in found.caps.values():
        mine = contract(c)
        kept = (out.get(c.id) or {}).get(str(c.version))
        if kept is not None:
            if kept.get("contract") != mine:
                said.append(f"{c.id} version {c.version} is locked with another contract: raise "
                            "its version.")
            continue
        out.setdefault(c.id, {})[str(c.version)] = {"hash": contract_hash(mine), "contract": mine}
        said.append(f"locked {c.id} version {c.version}")
    return out, said


def differences(old: dict, new: dict) -> list[str]:
    """What changed between two contracts, in words, the widening first."""
    out = []
    gained = sorted(set(new.get("effects") or []) - set(old.get("effects") or []))
    for e in gained:
        out.append(f"it gained the effect: {EFFECTS.get(e, (e,))[0]}")
    for e in sorted(set(old.get("effects") or []) - set(new.get("effects") or [])):
        out.append(f"it no longer has the effect: {EFFECTS.get(e, (e,))[0]}")
    if old.get("resource") != new.get("resource"):
        out.append(f"it acts on {RESOURCES.get(new.get('resource'), new.get('resource'))} instead "
                   f"of {RESOURCES.get(old.get('resource'), old.get('resource'))}")
    if old.get("authority") != new.get("authority") or old.get("level") != new.get("level"):
        out.append("where its permission comes from changed")
    old_tools = {json.dumps(t, sort_keys=True) for t in old.get("tools") or []}
    new_tools = {json.dumps(t, sort_keys=True) for t in new.get("tools") or []}
    for t in sorted(new_tools - old_tools):
        out.append(f"a tool acts for it now that did not: {json.loads(t).get('tool')}")
    for t in sorted(old_tools - new_tools):
        out.append(f"a tool no longer acts for it as it did: {json.loads(t).get('tool')}")
    oc, nc = old.get("constraints") or {}, new.get("constraints") or {}
    for name in sorted(set(oc) | set(nc)):
        if oc.get(name) != nc.get(name):
            out.append(f"its limit {name} changed")
    if old.get("rows") != new.get("rows"):
        out.append("whether it can be given on its own changed")
    return out


def compatible(old: dict, new: dict) -> tuple[bool, str]:
    """Whether a grant made for contract `old` may be used under `new`: the same resource and
    authority, no new effect, no tool that was not there, the same limits no wider. A narrower
    new contract is compatible; anything that could do more is not."""
    if not old or not new:
        return False, "its contract is not known"
    if old.get("resource") != new.get("resource"):
        return False, differences(old, new)[0]
    if old.get("authority") != new.get("authority") or old.get("level") != new.get("level"):
        return False, "where its permission comes from changed"
    gained = set(new.get("effects") or []) - set(old.get("effects") or [])
    if gained:
        return False, f"it gained the effect: {EFFECTS.get(sorted(gained)[0], ('',))[0]}"
    old_tools = {json.dumps(t, sort_keys=True) for t in old.get("tools") or []}
    added = [json.loads(t) for t in {json.dumps(t, sort_keys=True) for t in new.get("tools") or []}
             - old_tools]
    if added:
        return False, f"a tool acts for it now that did not: {added[0].get('tool')}"
    oc, nc = old.get("constraints") or {}, new.get("constraints") or {}
    if set(oc) != set(nc):
        return False, "its limits changed"
    for name, o in oc.items():
        n = nc[name]
        if o.get("type") != n.get("type"):
            return False, f"its limit {name} changed"
        if o["type"] == "count" and (n["max"] > o["max"] or n["min"] < o["min"]):
            return False, f"its limit {name} is wider"
        if o["type"] == "choice" and not set(n["values"]) <= set(o["values"]):
            return False, f"its limit {name} takes more"
    return True, ""


def version_state(cap: Capability | None, version: int, lock: dict) -> tuple[str, str]:
    """Whether a grant made for `version` of `cap` holds now: ("ok", ""), ("compatible", ""),
    ("suspended", why) or ("unknown", why). Unknown fails closed."""
    if cap is None:
        return "unknown", "what it was for is not a capability Rouh has now"
    try:
        version = int(version)
    except (TypeError, ValueError):
        return "unknown", "it names no version"
    if version == cap.version:
        return "ok", ""
    if version > cap.version:
        return "unknown", (f"it was made for version {version} of {cap.name}, newer than this "
                           f"Rouh's {cap.version}")
    kept = lock.get(cap.id) or {}
    old, now = kept.get(str(version)), kept.get(str(cap.version))
    if old is None or now is None:
        return "unknown", f"version {version} of {cap.name} is not one Rouh knows"
    # Every step between must be compatible, so nothing grew and narrowed back unseen.
    steps = sorted(int(v) for v in kept if str(v).isdigit() and version <= int(v) <= cap.version)
    for a, b in zip(steps, steps[1:]):
        ok, why = compatible(kept[str(a)]["contract"], kept[str(b)]["contract"])
        if not ok:
            return "suspended", f"{cap.name} changed in version {b}: {why}"
    return "compatible", ""


# --- proposals and grants as data -----------------------------------------------------------


def _day(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def ends_at(until: str) -> float:
    """The moment a grant "until" a day ends: the end of that day, UTC."""
    day = _day(until)
    if day is None:
        return 0.0
    return _dt.datetime(day.year, day.month, day.day, 23, 59, 59,
                        tzinfo=_dt.timezone.utc).timestamp()


def canonical(p: dict) -> dict:
    """The fields of a proposal that a digest and a grant are made of, in one order."""
    return {"contact": int(p.get("contact") or 0), "capability": str(p.get("capability") or ""),
            "version": int(p.get("version") or 0),
            "scope": sorted(str(x) for x in p.get("scope") or []),
            "limits": {k: (sorted(v) if isinstance(v, list) else v)
                       for k, v in sorted((p.get("limits") or {}).items())},
            "lifetime": str(p.get("lifetime") or ""), "until": str(p.get("until") or "")}


def digest(p: dict) -> str:
    """What the owner approves: a hash of exactly the fields shown, so a proposal changed after he
    saw it is never the one given."""
    return hashlib.sha256(json.dumps(canonical(p), sort_keys=True).encode()).hexdigest()[:24]


def propose(cap: Capability, contact_id: int, scope=(), values: dict | None = None,
            *, lifetime: str = STANDING) -> dict:
    """The narrowest grant that covers an ask: exactly the resources it names, every limit the
    capability declares at its default (or tighter, when the ask's own value is narrower), and
    `lifetime`. Built by code from the ask, never by a model."""
    values = values or {}
    limits: dict = {}
    for c in cap.constraints:
        if c.type == "count":
            limits[c.name] = int(c.default)
        else:
            asked = values.get(c.name)
            asked = [asked] if isinstance(asked, str) else list(asked or [])
            ok = [v for v in asked if v in dict(c.values)]
            limits[c.name] = sorted(ok or list(c.default))
    p = {"contact": int(contact_id or 0), "capability": cap.id, "version": cap.version,
         "scope": sorted(dict.fromkeys(str(x).strip().lstrip("#") for x in scope or () if
                                       str(x).strip())) if cap.resource in SCOPED else [],
         "limits": limits, "lifetime": lifetime, "until": ""}
    return canonical(p)


def validate(p: dict, cap: Capability | None, *, today: _dt.date | None = None) -> list[str]:
    """Why this proposal cannot be a grant, as sentences; none when it can. Checks it is a
    capability that can be given, at the version there is, with an exact scope of the right kind
    (never a wildcard, never empty where it acts on things), every limit it declares and only
    those, each inside its bounds, and a lifetime that ends where it says."""
    out: list[str] = []
    if cap is None:
        return ["It is not a capability Rouh has."]
    if not cap.grantable:
        why = ("only the owner ever decides it" if cap.reserved and not all(
            r in LIFTABLE for r in cap.reserved) else
               "it is the task's own permission, set on their page" if cap.authority ==
               "task_level" else "it is given on their page, not as a grant of its own")
        out.append(f"{cap.name} cannot be given as a grant: {why}.")
    p = canonical(p)
    if p["capability"] != cap.id:
        out.append("It names another capability.")
    if p["version"] != cap.version:
        out.append(f"It was made for version {p['version']} of {cap.name}; this Rouh has "
                   f"{cap.version}.")
    if p["contact"] <= 0:
        out.append("It names nobody it is for.")
    scope = p["scope"]
    if cap.resource in SCOPED:
        if not scope:
            out.append(f"Say which {RESOURCES[cap.resource]} it reaches: never all of them.")
        if len(scope) > 20:
            out.append("It names more than 20 at once.")
        for one in scope:
            if WILD.search(one) or not one.strip():
                out.append(f"\"{one}\" is not one {RESOURCES[cap.resource][:-1]}: name each.")
            elif cap.resource == "task" and not TASK_RE.match(one):
                out.append(f"\"{one}\" is not a task's number.")
            elif len(one) > 300:
                out.append("An id is too long.")
    elif scope:
        out.append(f"{cap.name} acts on {RESOURCES[cap.resource]}: it takes no list.")
    limits = p["limits"]
    for name in sorted(set(limits) - {c.name for c in cap.constraints}):
        out.append(f"{cap.name} has no limit called {name}.")
    for c in cap.constraints:
        if c.name not in limits:
            out.append(f"It leaves out the limit {c.name}.")
            continue
        v = limits[c.name]
        if c.type == "count":
            if not isinstance(v, int) or isinstance(v, bool) or not c.min <= v <= c.max:
                out.append(f"{c.name} must be a whole number from {c.min} to {c.max}.")
        else:
            if not isinstance(v, list) or not v or any(x not in dict(c.values) for x in v):
                out.append(f"{c.name} must be some of: {', '.join(x for x, _ in c.values)}.")
    life = p["lifetime"]
    if life not in LIFETIMES:
        out.append("It lasts once, until a date, or from now on.")
    if life == UNTIL:
        day = _day(p["until"])
        today = today or _dt.datetime.now(_dt.timezone.utc).date()
        if day is None:
            out.append("Give the day it ends.")
        elif day < today:
            out.append("The day it ends has passed.")
        elif (day - today).days > MOST_DAYS:
            out.append(f"It may run at most {MOST_DAYS} days; make it standing instead.")
    elif p["until"]:
        out.append("Only a grant until a date has a day it ends.")
    return out


def narrower_or_same(new: dict, old: dict, cap: Capability) -> bool:
    """Whether `new` gives no more than `old`: the same capability, a scope inside it, every
    count no higher, every choice inside it, and a lifetime no longer."""
    a, b = canonical(new), canonical(old)
    if a["capability"] != b["capability"] or a["contact"] != b["contact"]:
        return False
    if cap.resource in SCOPED and not set(a["scope"]) <= set(b["scope"]):
        return False
    for c in cap.constraints:
        x, y = a["limits"].get(c.name), b["limits"].get(c.name)
        if c.type == "count" and (not isinstance(x, int) or not isinstance(y, int) or x > y):
            return False
        if c.type == "choice" and not set(x or []) <= set(y or []):
            return False
    rank = {ONCE: 0, UNTIL: 1, STANDING: 2}
    if rank.get(a["lifetime"], 3) > rank.get(b["lifetime"], 3):
        return False
    if a["lifetime"] == UNTIL and b["lifetime"] == UNTIL and a["until"] > b["until"]:
        return False
    return True


def _and(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _or(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " or " + parts[-1]


def day_said(until: str) -> str:
    day = _day(until)
    return f"{day.day} {day.strftime('%B %Y')}" if day else until


def scope_said(cap: Capability, scope, labels: dict | None = None) -> str:
    labels = labels or {}
    scope = [str(s) for s in scope or []]
    if cap.resource == "task" and scope:
        return ("on task " if len(scope) == 1 else "on tasks ") + _and(scope)
    if cap.resource == "calendar" and scope:
        names = [labels.get(s) or s for s in scope]
        return ("in the calendar " if len(names) == 1 else "in the calendars ") + _and(names)
    return ""


def limits_said(cap: Capability, limits: dict) -> list[str]:
    out = []
    for c in cap.constraints:
        if c.name not in (limits or {}):
            continue
        v = limits[c.name]
        if c.type == "count":
            out.append(c.said.replace("{n}", str(v)))
        else:
            words = dict(c.values)
            out.append(c.said.replace("{values}", _or([words.get(x, x) for x in v or []])))
    return out


def lifetime_said(lifetime: str, until: str = "") -> str:
    return {ONCE: "this once", UNTIL: f"until {day_said(until)}",
            STANDING: "from now on, until you take it back"}.get(lifetime, lifetime)


def wording(p: dict, cap: Capability, first: str, *, labels: dict | None = None) -> str:
    """The one sentence the owner accepts, made from exactly the grant's fields: who, what, on
    what, within what, for how long. "Let Sam keep notes they give in your memory, marked as
    theirs, up to 3 a day, from now on, until you take it back." """
    p = canonical(p)
    parts = [scope_said(cap, p["scope"], labels), *limits_said(cap, p["limits"]),
             lifetime_said(p["lifetime"], p["until"])]
    return f"Let {first or 'them'} {cap.said}" + "".join(", " + x for x in parts if x) + "."


def effects_said(cap: Capability) -> list[str]:
    return [EFFECTS[e][0] for e in cap.effects if e in EFFECTS]


# --- authorisation: code, from what is held ---------------------------------------------------


@dataclass
class Verdict:
    """Whether a contact may have a capability done on these resources with these values, and
    by what: `via` "level" (their task level), "held" (a grant on their page), "row" (a grant of
    its own, `grant_id`), "once" (the owner allowed this ask once), or "" when not; `ref` names the
    authority for the record of uses; `reason` is in words, and `problem` a short code when not."""

    ok: bool
    via: str = ""
    ref: str = ""
    grant_id: int = 0
    reason: str = ""
    problem: str = ""
    limits: dict = field(default_factory=dict)
    scope: list = field(default_factory=list)
    once: bool = False
    version: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "via": self.via, "ref": self.ref, "grant_id": self.grant_id,
                "reason": self.reason, "problem": self.problem, "limits": dict(self.limits),
                "scope": list(self.scope), "once": self.once, "version": self.version}


def _first(name: str) -> str:
    return (str(name or "").split() or ["they"])[0]


def row_problem(row: dict, cap: Capability, lock: dict, *, scope=(), values: dict | None = None,
                now: float | None = None, case_key: str = "", ask: str = "",
                used_today: int | None = None) -> str:
    """Why one grant row does not cover this, or "": its state, its version, its lifetime and uses,
    its scope and its limits, in that order."""
    now = time.time() if now is None else now
    state = str(row.get("state") or "")
    if state != ACTIVE:
        return {REVOKED: "it was taken back", SPENT: "it was used already",
                SUSPENDED: "it is suspended" + (f": {row.get('suspended_reason')}"
                                                 if row.get("suspended_reason") else ""),
                REJECTED: "it was declined", PROPOSED: "it is not given yet",
                REPLACED: "it was replaced"}.get(state, f"it is {state or 'not given'}")
    vs, why = version_state(cap, row.get("version"), lock)
    if vs in ("suspended", "unknown"):
        return why
    if row.get("expires_at") and float(row["expires_at"]) < now:
        return f"it ended on {day_said(row.get('until') or '')}"
    if row.get("lifetime") == ONCE:
        # Bound to the message and the ask it was allowed for: a judgement that names neither
        # is never covered by it.
        if row.get("case_key") and row["case_key"] != case_key:
            return "it was allowed once, for another message"
        if row.get("ask_ident") and row["ask_ident"] != ask:
            return "it was allowed once, for another ask"
        if int(row.get("used") or 0) >= int(row.get("max_uses") or 1) and not (
                ask and row.get("ask_ident") == ask):
            return "it was used already"
    have = [str(s) for s in row.get("scope") or []]
    if cap.resource in SCOPED:
        if not have:
            return "it names no " + RESOURCES[cap.resource]
        missing = [s for s in scope or [] if str(s) not in have]
        if missing:
            return f"it reaches {scope_said(cap, have)[3:]}, not {_and(missing)}"
    limits = row.get("limits") or {}
    for c in cap.constraints:
        v = (values or {}).get(c.name)
        lim = limits.get(c.name)
        if lim is None:
            # A limit the grant does not have is never an unlimited one.
            return f"it says nothing of {c.name}"
        if c.type == "count":
            if used_today is not None and used_today >= int(lim):
                return f"it allows {lim} a day, and {used_today} were used today"
        elif v not in (None, "") and str(v) not in [str(x) for x in lim]:
            words = dict(c.values)
            return f"it allows {_or([words.get(x, x) for x in lim])}, not {words.get(str(v), v)}"
    return ""


def authorize(cap: Capability | None, contact, *, scope=(), values: dict | None = None,
              held: set | None = None, rows: list | None = None, tasks: dict | None = None,
              lock: dict | None = None, now: float | None = None, case_key: str = "",
              ask: str = "", used_today: dict | None = None) -> Verdict:
    """Whether `contact` may have `cap` done on `scope` with `values`, decided by code.

    `held` is the grant keys the contact page gives them (`grants.Tree.held`), `rows` their grants
    as data (`capability_grants.rows_of`), `tasks` their level on each task by number
    (`task_access.for_judge`), `lock` the locked contracts. A scope the ask leaves empty, for a
    capability that acts on things, is allowed by a grant that names its things: which of them a
    call reaches is checked on the call (`check_call`)."""
    lock = lock if lock is not None else {}
    name = getattr(contact, "name", "") or "They"
    first = _first(name)
    if cap is None:
        return Verdict(False, reason="Rouh has no capability that does this.",
                       problem="unknown")
    if contact is None:
        return Verdict(False, reason="Nobody is behind it any more.", problem="subject")
    if not getattr(contact, "implicit", False) and not getattr(contact, "trusted", True):
        return Verdict(False, reason=f"{name} is switched off on your Trusted contacts.",
                       problem="subject")
    scope = [str(s).strip().lstrip("#") for s in scope or [] if str(s).strip()]
    if cap.authority == "task_level":
        if not scope:
            return Verdict(False, reason=f"It names no task of yours for {cap.name}.",
                           problem="scope")
        rank = {"": 0, "view": 1, "edit": 2, "decide": 3}
        for n in scope:
            one = (tasks or {}).get(n)
            if one is None:
                return Verdict(False, reason=f"Task {n} is not one {first} may open.",
                               problem="scope")
            if rank.get(one.get("level") or "", 0) < rank[cap.level]:
                return Verdict(False, reason=(f"{first} may only "
                                              f"{'read' if one.get('level') == 'view' else 'open'}"
                                              f" task {n}, and {cap.name} needs {cap.level}."),
                               problem="level")
        return Verdict(True, via="level", ref="level:" + ",".join(scope), scope=scope,
                       reason=f"{first}'s own level on task {_and(scope)} covers it.")
    # A grant: the contact page's first, exactly as it was, then grants of its own.
    if cap.legacy_grant and cap.legacy_grant in (held or set()):
        return Verdict(True, via="held", ref=f"held:{cap.legacy_grant}",
                       reason=f"{first} holds it on their page.")
    why: list[str] = []
    for row in rows or []:
        if str(row.get("capability")) != cap.id:
            continue
        if row.get("contact") not in (None, "", 0) and str(row.get("contact")) != str(
                getattr(contact, "id", "")):
            # Somebody else's grant is never this person's, whatever the name or the words.
            why.append(f"grant {row.get('id')}: it is another person's")
            continue
        said = row_problem(row, cap, lock, scope=scope, values=values, now=now,
                           case_key=case_key, ask=ask,
                           used_today=(used_today or {}).get(int(row.get("id") or 0)))
        if said:
            why.append(f"grant {row.get('id')}: {said}")
            continue
        return Verdict(True, via="once" if row.get("lifetime") == ONCE else "row",
                       ref=f"row:{row.get('id')}", grant_id=int(row.get("id") or 0),
                       limits=dict(row.get("limits") or {}),
                       scope=[str(s) for s in row.get("scope") or []],
                       once=row.get("lifetime") == ONCE, version=int(row.get("version") or 0),
                       reason=(f"Grant {row.get('id')}: "
                               + (row.get("wording") or f"{first} holds {cap.name}")))
    return Verdict(False, reason=(f"{first} holds no grant for {cap.name}"
                                  + (" that covers it (" + "; ".join(why) + ")" if why else "")
                                  + "."), problem="not_held")


# --- the actual call, checked again ---------------------------------------------------------


@dataclass
class CallCheck:
    """A tool call of a case's turn, checked against what the turn may do: allowed or not, which
    capability it is, the resource and values its arguments name, the authority that covers it,
    and whether it counts as a use."""

    ok: bool
    reason: str = ""
    capability: str = ""
    resource: str = ""
    values: dict = field(default_factory=dict)
    auth: dict = field(default_factory=dict)
    counts: bool = False
    guard: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "capability": self.capability,
                "resource": self.resource, "values": dict(self.values),
                "auth": {k: v for k, v in self.auth.items() if k != "wording"},
                "counts": self.counts, "guard": self.guard}


def check_call(found: Catalogue, tool: str, args: dict, authorized: list[dict], *,
               reads: set | frozenset = frozenset(), limit_of_tool: str = "",
               limits: set | frozenset = frozenset()) -> CallCheck:
    """Whether a case's turn may make this call, from its arguments and the authorisations the
    turn was given (`MailTurn.authorized`), each {"capability", "scope" (None: any of its kind the
    tool's own reach allows), "limits", "values", "ref", "grant_id", "once", "ask"}.

    A tool in `reads` (the reading tools a case may always use) goes. A tool the catalogue does not
    bind goes only when the owner allowed its hard limit for an ask of this turn (`limits`); every
    other undeclared tool is refused: what nobody declared does not run. A bound call must be
    covered by an authorisation of its capability whose scope holds the resource its arguments
    name and whose limits hold its values."""
    args = args or {}
    if tool in reads:
        return CallCheck(True, reason="reading only")
    bound = [(c, b) for c, b in found.bindings_for(tool) if b.matches(args)]
    if not bound:
        if limit_of_tool and limit_of_tool in limits:
            return CallCheck(True, reason="you allowed its hard limit for this ask",
                             auth={"ref": f"limit:{limit_of_tool}"})
        if found.bindings_for(tool):
            return CallCheck(False, reason=(f"{tool} with these arguments is not something any "
                                            "capability does."))
        return CallCheck(False, reason=(f"{tool} is not declared by any capability, so it does "
                                        "not run for somebody else."))
    tried: list[str] = []
    for cap, b in bound:
        resource = b.resource_of(args)
        values = b.values_of(args)
        if not b.counts:
            # A read of what the capability reaches: allowed when the turn may do the capability
            # at all, with nothing counted.
            if any(a.get("capability") == cap.id for a in authorized):
                return CallCheck(True, reason="reading what it reaches", capability=cap.id,
                                 counts=False)
            tried.append(f"{cap.name} is not allowed in this turn")
            continue
        for a in authorized:
            if a.get("capability") != cap.id:
                continue
            scope = a.get("scope")
            if cap.resource in SCOPED and b.guard != "tool":
                if not resource:
                    tried.append(f"{tool} names no {RESOURCES[cap.resource][:-1]}")
                    continue
                if scope is not None and resource not in [str(s) for s in scope]:
                    tried.append(f"{resource} is outside what was allowed "
                                 f"({_and([str(s) for s in scope]) or 'nothing'})")
                    continue
            bad = ""
            for c in cap.constraints:
                v = values.get(c.name)
                if c.type != "choice" or v in (None, ""):
                    continue
                allowed = (a.get("limits") or {}).get(c.name)
                asked = (a.get("values") or {}).get(c.name)
                if allowed is not None and v not in [str(x) for x in allowed]:
                    bad = f"{c.name} {v} is outside the grant ({_or([str(x) for x in allowed])})"
                elif asked not in (None, "", []) and v not in (
                        [str(x) for x in asked] if isinstance(asked, list) else [str(asked)]):
                    bad = f"{c.name} {v} is not what was asked ({asked})"
                if bad:
                    break
            if bad:
                tried.append(bad)
                continue
            return CallCheck(True, reason=a.get("reason") or "allowed", capability=cap.id,
                             resource=resource, values=values, auth=dict(a), counts=True,
                             guard=b.guard)
        if not any(a.get("capability") == cap.id for a in authorized):
            tried.append(f"{cap.name} is not allowed in this turn")
    return CallCheck(False, reason="; ".join(dict.fromkeys(tried)) or "not allowed",
                     capability=bound[0][0].id)


def call_key(case_key: str, tool: str, args: dict) -> str:
    """The same call of the same case is the same use: a retry finds it done."""
    text = json.dumps({"case": case_key, "tool": tool, "args": args or {}}, sort_keys=True,
                      default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


# --- the command: check and lock ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    found = catalogue()
    lock = read_lock()
    if argv[:1] == ["lock"]:
        if found.problems:
            print("\n".join(found.problems))
            return 1
        new, said = lock_with(found, lock)
        refused = [s for s in said if not s.startswith("locked")]
        if refused:
            print("\n".join(refused))
            return 1
        LOCK.write_text(json.dumps({"about": "Every version of every capability's contract "
                                             "(rouh/capabilities.py, CAPABILITIES.md). Written by "
                                             "python -m rouh.capabilities lock; never edited by "
                                             "hand.", "capabilities": new},
                                   indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("\n".join(said) or "Nothing new to lock.")
        return 0
    if argv[:1] in (["check"], []):
        out = lock_problems(found, lock)
        if "--tools" in argv:
            out += tool_problems(found)
        for line in out:
            print(line)
        if out:
            return 1
        print(f"The capability contracts hold: {len(found.caps)} capabilities, each locked.")
        return 0
    print("python -m rouh.capabilities [check [--tools] | lock]")
    return 2


def tool_problems(found: Catalogue) -> list[str]:
    """Every declared tool against the tool registry that runs: there, every bound argument in
    its input schema, and its hard-limit effect among the capability's effects. Needs Rouh."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
    import django

    django.setup()
    from . import mail_turn
    from .runtime import tools as registry

    schemas = {t["name"]: (t.get("input_schema") or {}).get("properties") or {}
               for t in registry._defs if t.get("name")}
    out = []
    for cap in found.caps.values():
        for b in cap.bindings:
            if b.tool not in schemas:
                # Declared only where what it needs is set up (a job runner, Google): nothing
                # here to check it against, and nothing here that could call it.
                print(f"note: {cap.id}: tool {b.tool} is not offered on this machine")
                continue
            props = schemas[b.tool]
            for arg in [*(a for a, _ in b.when), *([b.resource] if b.resource else []),
                        *(a for _, a in b.values)]:
                if arg not in props:
                    out.append(f"{cap.id}: tool {b.tool} takes no argument {arg}")
            limit = mail_turn.EFFECTS.get(b.tool)
            if limit and limit not in cap.reserved:
                out.append(f"{cap.id}: tool {b.tool} has the hard-limit effect {limit}, which "
                           "the capability does not declare")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
