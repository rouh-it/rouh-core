"""The emoji the icon picker offers, and the words each is found by (`rouh/static/emoji.json`).

Petar, 22 October 2026 (fr_288afd00eb77): the picker "doesn't have all the emojis, and it should",
and its search "almost always doesn't find anything ... if I type red I don't get the red pin.
and in osx I do ... each emoji you can brainstorm on various tags that are relevant. like 40
associations ... and those would be our database for search."

So every emoji is here, and each is found by three sets of words, worked out once and kept:

- Unicode's own list (`emoji-test.txt`): every fully qualified emoji, in Unicode's order and
  groups, with its name. Skin tones are left out, as the macOS picker shows them only on a long
  press: each person is offered once, in the yellow the picker shows first. The other genders
  and hair colours are emoji of their own and are kept. An emoji newer than `NEWEST` is left
  out, because Apple and Google do not draw it yet and it would be an empty box.
- CLDR's keywords for it, in English and in Bulgarian (`cldr-annotations-*`), which are the
  words Apple's and Google's pickers search.
- Associations brainstormed by a model, about forty for each emoji, kept in `associations.json`
  beside this file: what it looks like (its colours and shape), what it is used for, where it is,
  how it feels. That is what finds the round pushpin by "red".

    python3 tools/emoji/build.py brainstorm   # asks for the associations of every emoji that has none
    python3 tools/emoji/build.py brainstorm --thin 25   # and again for any with fewer than 25
    python3 tools/emoji/build.py build        # writes rouh/static/emoji.json

Run `brainstorm` and then `build` when Unicode adds emoji and `NEWEST` is moved: only the new
ones are asked about. The brainstorm asks the `claude` command line, which is signed in on the
server; it is a tool for whoever updates this list, and Rouh never asks it anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "rouh", "static", "emoji.json")
ASSOCIATIONS = os.path.join(HERE, "associations.json")
CACHE = os.path.join(HERE, ".cache")

#: The newest Emoji version offered: 17.0 (September 2025) is drawn by iOS and macOS 26.4 and
#: by Android 16 QPR. Emoji 18.0 is not drawn anywhere yet.
NEWEST = 17.0

SOURCES = {
    "emoji-test.txt": "https://unicode.org/Public/17.0.0/emoji/emoji-test.txt",
    "en.json": "https://cdn.jsdelivr.net/npm/cldr-annotations-full@48/annotations/en/annotations.json",
    "en-derived.json": "https://cdn.jsdelivr.net/npm/cldr-annotations-derived-full@48/annotationsDerived/en/annotations.json",
    "bg.json": "https://cdn.jsdelivr.net/npm/cldr-annotations-full@48/annotations/bg/annotations.json",
    "bg-derived.json": "https://cdn.jsdelivr.net/npm/cldr-annotations-derived-full@48/annotationsDerived/bg/annotations.json",
}

SKIN = re.compile("[\U0001F3FB-\U0001F3FF]")
VS16 = "️"

#: The emoji a task's icon is most often, offered first, before Unicode's own groups.
FOR_TASKS = (
    "💻 🖥️ 🤖 🧪 🐞 🔧 ⚙️ 🛠️ 🧩 📦 🚀 📈 📊 💼 🤝 📝 📄 📚 📁 📋 📌 📍 📅 ⏰ 🔍 💡 🎯 🏁 ✅ ⚠️ 🔒 🔑 "
    "🌐 🔗 ✉️ 💬 📞 📱 📣 ⚖️ 📜 🏛️ 💶 💰 💳 🧾 🏦 🛒 🏠 🏢 🛋️ 🧹 🚗 ✈️ 🧳 🏨 🗺️ 🏖️ 🩺 💊 🦷 🏃 "
    "👶 👪 🎓 🎁 🎂 🎉 ❤️ 🍽️ ☕ 🐶 🐱 🌱 🎨 📷 🎬 🎧 🎵 🎤 🎮 🔬 🧭 🔋 🛡️ 🏆 💎 🔥 ⚡ ⭐ 🧠 👥 🧰 ⌛"
).split()


def fetch(name: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        with urllib.request.urlopen(SOURCES[name], timeout=60) as r, open(path, "wb") as fh:
            fh.write(r.read())
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def unicode_list() -> list[tuple[str, str, str]]:
    """Every emoji offered, in Unicode's order: (group, emoji, name)."""
    out, group = [], ""
    for line in fetch("emoji-test.txt").splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
            continue
        if not line or line.startswith("#") or "; fully-qualified" not in line:
            continue
        m = re.match(r".*?# (\S+) E(\d+\.\d+) (.+)$", line)
        if not m or group == "Component":
            continue
        emoji, version, name = m.group(1), float(m.group(2)), m.group(3).strip()
        if version > NEWEST or SKIN.search(emoji):
            continue
        out.append((group, emoji, name))
    return out


def cldr(lang: str) -> dict[str, list[str]]:
    """CLDR's keywords for every emoji in one language, by the emoji without its VS16."""
    words: dict[str, list[str]] = {}
    for name, key in ((f"{lang}.json", "annotations"), (f"{lang}-derived.json", "annotationsDerived")):
        for emoji, said in json.loads(fetch(name))[key]["annotations"].items():
            words.setdefault(emoji.replace(VS16, ""), []).extend(said.get("tts", []) + said.get("default", []))
    return words


#: Words that find nothing by themselves, left out of an emoji's words (its name keeps them).
STOP = set("a an the of and or to with for in on at by is it as from its be"
           " и на с в за от по със до е".split())


def words_of(*phrases: list[str] | str) -> list[str]:
    """Every word of the phrases, lower case, each once, in the order first met."""
    seen, out = set(STOP), []
    for group in phrases:
        for phrase in ([group] if isinstance(group, str) else group):
            if re.match(r"(not|no|non|never|less|without) ", phrase.lower()):
                continue  # "not happy" is no word for a frown to be found by "happy"
            for w in re.findall(r"[\w'’&+-]+", phrase.lower()):
                w = w.strip("-'’")
                if w and w not in seen:
                    seen.add(w)
                    out.append(w)
    return out


def load_associations() -> dict[str, list[str]]:
    try:
        with open(ASSOCIATIONS, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


SYSTEM = """You write search keywords for an emoji picker, the way the macOS emoji picker finds an emoji by any word a person might think of.

For each emoji you are given (the emoji and its Unicode name), write about 40 lower case English associations: single words or very short phrases. Cover, as far as they apply:
- what it is and its synonyms (pushpin: pin, thumbtack, tack)
- what it looks like: its colours as drawn on Apple and Google (red, yellow, blue...), its shape and texture (round, pointy, sharp, shiny)
- what it is used for and what people mean when they send it (location, here, marker, remember, important)
- where it belongs and what goes with it (map, office, board, travel, place)
- the feelings, events, seasons, jobs and topics it calls up
- common misspellings or plural forms only when they really help

Never repeat a word from its Unicode name. No explanations.

Answer with one JSON object only, no code fence: each key is the emoji exactly as given, each value a list of strings."""


def ask(batch: list[tuple[str, str]], model: str) -> dict[str, list[str]]:
    said = "\n".join(f"{e}\t{n}" for e, n in batch)
    env = dict(os.environ, CLAUDE_CODE_DISABLE_CLAUDE_MDS="1")
    for _ in range(3):
        run = subprocess.run(
            ["claude", "-p", "--model", model, "--system-prompt", SYSTEM, "--tools", "",
             "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands", said],
            capture_output=True, text=True, env=env, timeout=900)
        text = run.stdout.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            got = json.loads(text[text.index("{"):text.rindex("}") + 1])
        except ValueError:
            print("an answer that was not JSON, asking again", file=sys.stderr)
            continue
        return {e: [str(w).strip().lower() for w in got[e] if str(w).strip()]
                for e, _ in batch if isinstance(got.get(e), list)}
    return {}


def brainstorm(model: str, size: int, workers: int, thin: int) -> None:
    kept = load_associations()
    wanted = [(e, n) for _, e, n in unicode_list() if len(kept.get(e, [])) < thin]
    batches = [wanted[i:i + size] for i in range(0, len(wanted), size)]
    print(f"{len(wanted)} emoji to brainstorm, in {len(batches)} questions", file=sys.stderr)
    with ThreadPoolExecutor(workers) as pool:
        for got in pool.map(lambda b: ask(b, model), batches):
            for e, said in got.items():
                kept[e] = list(dict.fromkeys(kept.get(e, []) + said))
            with open(ASSOCIATIONS, "w", encoding="utf-8") as fh:
                json.dump(dict(sorted(kept.items())), fh, ensure_ascii=False, indent=0)
            print(f"{len(kept)} kept", file=sys.stderr)
    missing = [e for e, _ in wanted if len(kept.get(e, [])) < thin]
    if missing:
        print(f"still none for {len(missing)}: {' '.join(missing)}; run brainstorm again", file=sys.stderr)


def build() -> None:
    en, bg, more = cldr("en"), cldr("bg"), load_associations()
    groups: list[list] = [["For tasks", FOR_TASKS]]
    everything: list[list] = []
    seen = set()
    for group, emoji, name in unicode_list():
        if group != (groups[-1][0] if len(groups) > 1 else None):
            groups.append([group, []])
        bare = emoji.replace(VS16, "")
        name_words = set(words_of(name))
        tags = [w for w in words_of(en.get(bare, []), more.get(emoji, [])) if w not in name_words]
        local = words_of(bg.get(bare, []))
        everything.append([emoji, name, " ".join(tags), " ".join(local)])
        groups[-1][1].append(len(everything) - 1)
        seen.add(emoji)
    unknown = [e for e in FOR_TASKS if e not in seen]
    if unknown:
        sys.exit(f"For tasks names emoji Unicode has not: {' '.join(unknown)}")
    lacking = sum(1 for _, e, _ in unicode_list() if e not in more)
    data = {
        "about": "Every emoji the icon picker offers and the words each is found by: "
                 "[emoji, name, English words, Bulgarian words]. Made by tools/emoji/build.py.",
        "emoji": everything,
        "groups": [[g, [i if isinstance(i, int) else everything.index(next(x for x in everything if x[0] == i))
                        for i in items]] for g, items in groups],
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(f"{len(everything)} emoji written to {os.path.relpath(OUT, REPO)}, "
          f"{os.path.getsize(OUT) // 1024} kB; {lacking} with no associations", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="do", required=True)
    b = sub.add_parser("brainstorm", help="ask for the associations of every emoji that has none")
    b.add_argument("--model", default="claude-sonnet-5")
    b.add_argument("--size", type=int, default=60, help="emoji in one question")
    b.add_argument("--workers", type=int, default=6)
    b.add_argument("--thin", type=int, default=1,
                   help="ask again for every emoji with fewer associations than this, adding to them")
    sub.add_parser("build", help="write rouh/static/emoji.json")
    a = p.parse_args()
    if a.do == "brainstorm":
        brainstorm(a.model, a.size, a.workers, a.thin)
    else:
        build()


if __name__ == "__main__":
    main()
