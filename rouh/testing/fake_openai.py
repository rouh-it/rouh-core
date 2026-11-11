"""A stand-in for OpenAI's Responses API, so a Luna turn can be driven for real.

The same idea as `fake_model.py`, for the other company: Rouh talks to Luna
through OpenAI's own SDK (`rouh/luna.py`), and a test that patched the client
would prove that Rouh meant to send something, not that it was sent. So this is
a real HTTP server that speaks enough of `POST /v1/responses`, streamed, to be
the far end of that SDK. Point `OPENAI_BASE_URL` at it, give Rouh any
`OPENAI_API_KEY`, and every request body lands in the record directory as a
file named `luna-...json` that can be opened.

It answers the way the stand-in in front of Anthropic does, so the same words
drive both, and it holds Rouh to what the real API would refuse:

- Every reply starts with one of the turn marks when the instructions ask for
  them, and `NOTFINISHED`, `STILLTHINKING` and `THATSALL` in what the person
  said pick which (`rouh/turnmarks.py`).
- `TOOL name {json}` in the person's words comes back as a real function call,
  one a round, the way `fake_model.py` does it.
- `LUNASEARCH some words` runs OpenAI's own web search: a `web_search_call`
  that says what it searched only when it is done, and an answer whose words
  carry `url_citation` annotations to two pages. `LUNAOPEN https://...` opens
  one page instead, which Rouh draws as web_fetch.
- `SLOWLY` writes the answer a word at a time, for the Stop button.
- Synapse's explanations (a JSON shape named `synapse_explanation`) say which
  label and place they were asked about, and a rewrite says how many came
  before it, so each press of 🤷‍♂️ is seen to bring a new one; one asked
  with a question repeats the question, so it is seen to be built around it.
- A function declared with `defer_loading` is only called once it is loaded:
  with OpenAI's own `tool_search` declared, the same response first searches
  for it and loads it, as OpenAI's hosted search does; with the search run
  by the caller (`execution: "client"`), the response is only the search, and
  the call comes once the next request hands back its `tool_search_output`.
  Functions may sit in namespaces, and a call says which it was in.
- A namespace under a name OpenAI keeps for its own tools (`RESERVED`) is
  refused with the real API's words, which is what every Luna turn met on
  26 September 2026 when Rouh's web tools were in a namespace called `web`.
- `DESCRIPTIONLIMIT` refuses any function description over 1,024 characters,
  with the words OpenAI's older APIs used, which is how Rouh's fallback for
  that (`luna.shortened`) is seen working.
- `OVERLOAD n` answers 503 to the next n requests with those words, and
  `DROP n` opens the stream and then fails inside it, the way a response that
  breaks after its headers does.
- Every response carries a reasoning item with encrypted content, and a
  request that hands back one of this server's function calls without the
  reasoning that came with it is refused with the real API's complaint, as is
  a tool output with no call in front of it, a function whose schema is not an
  object, and any field of Anthropic's own (`input_schema`, `cache_control`,
  `system`, `messages`, `max_tokens`) that has strayed into the request.
- The usage says what a real cache would: the part of this request that is the
  same as the one before it was read from the cache, and the rest written.

And enough of the Images API, `POST /v1/images/generations` and
`POST /v1/images/edits`, to be the far end of `rouh/imaging_openai.py`:

- A picture is a mosaic of coloured squares whose colours come from the words
  it was asked for, so two prompts give two pictures, at exactly the size
  asked for. Streamed, each rough preview is the same mosaic in bigger
  squares, so the page is seen sharpening.
- An edit with a mask repaints only where the mask is transparent, in a colour
  of the prompt's own, and leaves every other pixel of the picture it was
  handed as it was: a screenshot shows whether the area painted in the editor
  is the area that arrived. With no mask the whole picture is tinted. Sunburst
  with a mask gives the area back black and tints the rest, which is what the
  real `gpt-image-2.5-sunburst` did every time it was asked on 26 September
  2026 (`rouh/imaging_openai.py`).
- It refuses what the real API refuses: an unknown model, a size the model
  cannot draw, a quality it does not have, a transparent JPEG, `n` out of
  range, and a mask that is not a PNG the size of the picture.
- `background: transparent` is drawn as a round cut-out on nothing, and
  `OPAQUEPICTURE` in the prompt draws it on a flat dark backdrop instead, as a
  model that ignores the setting does.
- `REFUSEPICTURE` in the prompt is refused as the safety system refuses one,
  `SLOWPICTURE` takes a second and a half between previews, so the picture
  can be watched arriving, and `BROKENPICTURE` breaks the stream before the
  finished picture.
- Every request is written to the record directory as `image-...json`: the
  JSON body, or an edit's form fields with each file's size and dimensions.

And enough of the Decisions API, `POST /v1/decisions`, to be the far end of
`llm.decide_model` (the router's choice of tier, Synapse's hosted decisions):

- It takes what OpenAI's reference takes and nothing else: `model` (only
  gpt-6-luna), `input`, and 1 to 400 `questions`, each a predicate, a choice
  of 2 to 255 different values or a score of 2 to 10 levels, with names that
  are each their own. Any other field is refused with the real API's words for
  an unknown parameter, which is what the spec's `purpose` and `state` met.
- `DECIDE <value>` in the input picks that choice or level at 0.8 (or at the probability
  after it, `DECIDE easy 0.95`), `ROUTE CHEAPER` the router's easy at 0.95 and `ROUTE
  SMART` its hard, and a
  predicate at 0.9 for `DECIDE YES`; otherwise the first choice, the lowest
  level and 0.5.
- `DECISIONSDOWN` answers 500 and `DECISIONSREFUSED` 403 with the words this
  key met on 3 October 2026, `DECISIONSSLOW` takes five seconds, so the
  router's fallback to Smart can be seen.
- The usage is input alone, and `output_tokens` 0, as the real API sends it.
- Every request is written to the record directory as `decision-...json`.

    python -m rouh.testing.fake_openai --port 8098 --record /tmp/requests
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import itertools
import json
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import fake_model
from ..turnmarks import ANSWER_NOW, CUT_OFF_MID_THOUGHT, FINISHED, STILL_THINKING

MODEL = "gpt-6-luna"
#: The small models Synapse asks for a structured answer, as its decision model (`numbers.decision_model`):
#: automatic recall's reading of each message (`autorecall.ask`). They take no reasoning effort.
SMALL_MODELS = ("gpt-4.1-mini", "gpt-4.1-nano")
# The first line of the rule "turn-marks", which a turn of words from the microphone is told, as a new Rouh starts
# with it (`rouh/rule_defaults_fallback.json`).
MARK_INSTRUCTION = next(r["text"] for r in __import__("rouh.ruledefaults", fromlist=["fallback"]).fallback()["rules"]
                        if r["key"] == "turn-marks").strip().splitlines()[0]
MARKS_BY_WORD = {"NOTFINISHED": CUT_OFF_MID_THOUGHT, "STILLTHINKING": STILL_THINKING,
                 "THATSALL": FINISHED}
MARK_WORDS = re.compile(r"\b(%s)\b" % "|".join(MARKS_BY_WORD))
TOOL_LINE = re.compile(r"TOOL\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\{)")
SEARCH_LINE = re.compile(r"LUNASEARCH\s+([^\n]+)")
OPEN_LINE = re.compile(r"LUNAOPEN\s+(https?://\S+)")
OVERLOAD_LINE = re.compile(r"OVERLOAD\s+(\d+)")
DROP_LINE = re.compile(r"DROP\s+(\d+)")
SLOW_MARK = "SLOWLY"
SLOW_WORD_SECONDS = 0.15
SLOW_ANSWER = ("This answer is being written slowly on purpose, a word at a time, so "
               "that there is time to press Stop while it is still arriving and "
               "still being spoken, and see what is kept.")
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
DESCRIPTION_MAX = 1024
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: The namespace names the real API refuses, asked of it one by one on
#: 26 September 2026: "Function 'web.look_into' is not allowed in reserved
#: namespace 'web'." `functions`, `container`, `mcp`, `tools`, `openai` and
#: every name Rouh uses now were accepted.
RESERVED = ("web", "browser", "python", "file_search", "computer", "image_gen",
            "multi_tool_use")
ANTHROPIC_FIELDS = ("system", "messages", "max_tokens", "input_schema", "cache_control",
                    "output_config", "thinking", "allowed_callers")

_ids = itertools.count(1)
_countdown: dict[str, int] = {}
_last_prefix = {"text": ""}

#: The two pages a LUNASEARCH finds, and so cites.
PAGES = [("https://example.com/luna/prices", "Example prices page"),
         ("https://example.org/luna/review", "An example review")]


def _sse(payload: dict) -> bytes:
    return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n".encode()


def _error(status: int, message: str, *, kind: str = "invalid_request_error",
           code: str | None = None, param: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"message": message, "type": kind, "param": param, "code": code}})


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [str(p.get("text") or "") for p in (content or [])
            if isinstance(p, dict) and p.get("type") in ("input_text", "output_text")]


def _last_user(items: list) -> tuple[int, dict | None]:
    """The person's own last message: not Rouh's note asking for an answer."""
    for i in range(len(items) - 1, -1, -1):
        item = items[i]
        if item.get("role") == "user":
            words = " ".join(_texts(item.get("content")))
            if words.strip() == ANSWER_NOW.strip():
                continue
            return i, item
    return -1, None


def refuses(body: dict) -> tuple[int, str, str | None] | None:
    """What the real API would refuse in this request, or None."""
    stray = [k for k in ANTHROPIC_FIELDS if k in body]
    if stray:
        return 400, f"Unknown parameter: '{stray[0]}'.", "unknown_parameter"
    from ..config import OPENAI_CHOICES

    # Any of OpenAI's models on Rouh's list answers, as the real API does for a key that has them:
    # a blind comparison or a double call asks Smart's OpenAI model too (`rouh/modelvotes.py`).
    if body.get("model") != MODEL and body.get("model") not in SMALL_MODELS \
            and body.get("model") not in {m for m, _ in OPENAI_CHOICES}:
        return 404, f"The model `{body.get('model')}` does not exist or you do not have access to it.", "model_not_found"
    effort = (body.get("reasoning") or {}).get("effort", "medium")
    if effort not in EFFORTS:
        return 400, f"Invalid value: '{effort}'. Supported values are: {', '.join(EFFORTS)}.", "invalid_value"
    if effort != "none" and any(k in body for k in ("temperature", "top_p")):
        return 400, "Unsupported parameter: 'temperature' is not supported with this model.", "unsupported_parameter"
    deferred = False
    searching = False
    for n, tool in enumerate(body.get("tools") or []):
        if any(k in tool for k in ANTHROPIC_FIELDS):
            return 400, f"Unknown parameter: 'tools[{n}].{[k for k in ANTHROPIC_FIELDS if k in tool][0]}'.", "unknown_parameter"
        kind = tool.get("type")
        if kind == "web_search":
            continue
        if kind == "tool_search":
            searching = True
            continue
        inner = [tool]
        if kind == "namespace":
            if not _NAME.match(str(tool.get("name") or "")) or not tool.get("tools"):
                return 400, f"Invalid 'tools[{n}]': a namespace needs a name and tools.", "invalid_value"
            inner = tool["tools"]
            if tool["name"] in RESERVED:
                first = next((fn.get("name") for fn in inner if isinstance(fn, dict)), "")
                return 400, (f"Invalid Value: 'tools'. Function '{tool['name']}.{first}' is not "
                             f"allowed in reserved namespace '{tool['name']}'."), None
        elif kind != "function":
            return 400, f"Invalid value: '{kind}'. Supported values are: 'function', 'namespace', 'tool_search', 'web_search', ...", "invalid_value"
        for fn in inner:
            if fn.get("type") != "function":
                return 400, f"Invalid 'tools[{n}]': a namespace holds functions.", "invalid_value"
            if not _NAME.match(str(fn.get("name") or "")):
                return 400, f"Invalid 'tools[{n}].name': string does not match pattern.", "invalid_value"
            params = fn.get("parameters") or {}
            if params.get("type") != "object":
                return 400, f"Invalid schema for function '{fn.get('name')}': schema must be a JSON Schema of 'type: \"object\"'.", "invalid_function_parameters"
            deferred = deferred or bool(fn.get("defer_loading"))
    if deferred and not searching:
        return 400, "Deferred tools need a tool_search tool to load them.", "invalid_value"
    items = body.get("input") or []
    if isinstance(items, str):
        return None
    called: set[str] = set()
    searched: set[str] = set()
    reasoned = False
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            return 400, f"Invalid 'input[{n}]'.", "invalid_type"
        if any(k in item for k in ("cache_control",)):
            return 400, f"Unknown parameter: 'input[{n}].cache_control'.", "unknown_parameter"
        kind = item.get("type") or ("message" if "role" in item else "")
        if kind == "reasoning":
            if not item.get("encrypted_content"):
                return 404, (f"Item with id '{item.get('id')}' not found. Items are not persisted "
                             "when `store` is set to false."), None
            reasoned = True
        elif kind == "function_call":
            if str(item.get("id") or "").startswith("fc_luna") and not reasoned:
                return 400, (f"Item '{item.get('id')}' of type 'function_call' was provided "
                             "without its required 'reasoning' item."), None
            called.add(str(item.get("call_id")))
        elif kind == "tool_search_call":
            if item.get("call_id"):
                searched.add(str(item["call_id"]))
        elif kind == "tool_search_output":
            if item.get("execution") == "client" and str(item.get("call_id")) not in searched:
                return 400, (f"No tool search call found for tool search output with call_id "
                             f"{item.get('call_id')}."), None
        elif kind == "function_call_output":
            if str(item.get("call_id")) not in called:
                return 400, (f"No tool call found for function call output with call_id "
                             f"{item.get('call_id')}."), None
        elif kind == "message":
            if item.get("role") == "user":
                reasoned = False
                for part in item.get("content") if isinstance(item.get("content"), list) else []:
                    if part.get("type") not in ("input_text", "input_image", "input_file"):
                        return 400, f"Invalid content type '{part.get('type')}' in a user message.", "invalid_value"
    return None


def declared(body: dict) -> dict:
    """Every function the request declares: name -> (namespace, definition)."""
    out = {}
    for tool in body.get("tools") or []:
        if tool.get("type") == "function":
            out[tool["name"]] = ("", tool)
        elif tool.get("type") == "namespace":
            for fn in tool.get("tools") or []:
                out[fn["name"]] = (tool["name"], dict(fn, _space=tool))
    return out


def loaded(items: list) -> set:
    """Every function a tool search earlier in the input loaded."""
    out = set()
    for item in items:
        if item.get("type") != "tool_search_output":
            continue
        for tool in item.get("tools") or []:
            for fn in (tool.get("tools") or [] if tool.get("type") == "namespace" else [tool]):
                if fn.get("name"):
                    out.add(fn["name"])
    return out


def search_mode(body: dict) -> str:
    for tool in body.get("tools") or []:
        if tool.get("type") == "tool_search":
            return tool.get("execution") or "server"
    return ""


def wanted_tool(items: list) -> tuple[str, dict] | None:
    """The next `TOOL` line of the person's last words not yet answered."""
    at, user = _last_user(items)
    if user is None:
        return None
    answered = sum(1 for item in items[at + 1:] if item.get("type") == "function_call_output")
    calls = []
    text = " ".join(_texts(user.get("content")))
    for found in TOOL_LINE.finditer(text):
        try:
            args, _ = json.JSONDecoder().raw_decode(text, found.start(2))
        except ValueError:
            continue
        if isinstance(args, dict):
            calls.append((found.group(1), args))
    return calls[answered] if answered < len(calls) else None


def describe(items: list) -> str:
    """What the last user message and any tool output after it carried."""
    at, user = _last_user(items)
    said = []
    for part in (user or {}).get("content") if isinstance((user or {}).get("content"), list) else []:
        kind = part.get("type")
        if kind == "input_text":
            said.append("text " + " ".join(str(part.get("text") or "").split())[:400])
        elif kind == "input_image":
            url = str(part.get("image_url") or "")
            head, _, data = url.partition(";base64,")
            raw = base64.b64decode(data or "")
            said.append(f"image {head.removeprefix('data:')} {len(raw)} bytes "
                        f"sha256:{hashlib.sha256(raw).hexdigest()[:16]}")
        elif kind == "input_file":
            data = str(part.get("file_data") or "").partition(";base64,")[2]
            raw = base64.b64decode(data or "")
            words = b" ".join(re.findall(rb"\(([ -~]{3,})\)", raw)[:8]).decode("ascii", "replace")
            said.append(f"file {part.get('filename')} {len(raw)} bytes reading {words}")
    if user is not None and isinstance(user.get("content"), str):
        said.append("text " + " ".join(user["content"].split())[:400])
    for item in items[at + 1:]:
        if item.get("type") == "function_call_output":
            said.append("tool result " + " ".join(str(item.get("output") or "").split())[:1200])
    return "Luna received: " + ("; ".join(said) if said else "nothing")


#: In words asked for as a JSON shape (`text.format` json_schema), the answer
#: to give, word for word: "REMINDER {\"title\": \"Tea\", ...}". The stand-in
#: reads no language, so a test says what the model would have answered.
SHAPED_LINE = re.compile(r"\b(?:REMINDER|SHAPED)\s+(\{.*\})", re.S)


def shaped_answer(body: dict, words: str) -> str | None:
    """The JSON text for a request that asked for a JSON shape, or None.

    With a SHAPED_LINE in the words, that JSON; otherwise the shape with its
    strings empty, its enums at their first value and its lists empty, which
    is a model that found nothing in the words.
    """
    fmt = ((body.get("text") or {}).get("format") or {})
    if fmt.get("type") != "json_schema":
        return None
    found = SHAPED_LINE.search(words or "")
    if found:
        return found.group(1)
    if fmt.get("name") == "synapse_explanation":
        # Synapse's (i) (`rouh/synapse/explain.py`): an explanation that says
        # which label it was for, where, and how many came before it, so a
        # rewrite is seen to be a new one.
        label = re.search(r"^Label: (.*)$", words or "", re.M)
        place = re.search(r"^Where it is: (.*)$", words or "", re.M)
        before = len(re.findall(r"^Explanation \d+: ", words or "", re.M))
        said = ("Stand-in explanation of " + (label.group(1) if label else "nothing") + ", " +
                (place.group(1) if place else "nowhere") + ".")
        now = re.search(r"^What he says now: (.*)$", words or "", re.M)
        if now:
            said = f"Rewrite {before} of it, around what he asked: {now.group(1)}. " + said
        elif before:
            said = f"Rewrite {before} of it, said another way. " + said
        return json.dumps({"text": said})
    if fmt.get("name") == "recall_pick":
        return json.dumps(recall_pick(str(body.get("instructions") or ""), words))
    empty = {}
    for key, spec in ((fmt.get("schema") or {}).get("properties") or {}).items():
        empty[key] = ((spec.get("enum") or [""])[0] if spec.get("type") == "string"
                      else [] if spec.get("type") == "array" else None)
    return json.dumps(empty)


def claude_errand(body: dict, words: str) -> str:
    """The answer the stand-in for Claude gives one of Rouh's side errands, or "": the same words
    whichever company the Models page puts the errand on. A page told as a narration
    (`rouh/page_listen.py`), a waiting decision read for an answer already given in a chat
    (`rouh/answered_in_chat.py`), and a picture's description written from its chat
    (`imaging.with_conversation`)."""
    asked = {"system": str(body.get("instructions") or ""), "messages": [{"role": "user", "content": words}]}
    for is_it, answer in ((fake_model.is_page_listen, fake_model.a_narration),
                          (fake_model.is_answered, fake_model.an_answered),
                          (fake_model.is_picture_prompt, fake_model.a_picture_prompt)):
        if is_it(asked):
            return answer(asked)
    return ""


def recall_pick(instructions: str, words: str) -> dict:
    """Automatic recall's reading of a message (`rouh/synapse/autorecall.py`), as a model that reads only
    what is written: each person on its list whose name or word for them the message holds, each task whose
    code it holds, each project whose name it holds, and each phrase it puts in double quotes as a topic.
    `PICKFAIL` in the message is a model that refuses, for the path where nothing is looked up, and
    `PICKSLOW` one that takes three seconds (`responses`). The stand-in for Claude answers the same way
    (`fake_model.a_recall_pick`), so both companies' readers read alike, and `HAIKUSLOW` makes it take four."""
    message = words.split("THE MESSAGE:\n", 1)[-1]
    if "PICKFAIL" in message:
        raise ValueError("PICKFAIL")
    low = message.lower()

    def says(name: str) -> bool:
        return bool(name) and re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", low) is not None

    got = {"people": [], "other_people": [], "tasks": [], "projects": [], "topics": [], "related": False}
    section = ""
    for line in instructions.splitlines():
        # A heading: in capitals, or the owner's own words for people, under their name
        # ("ALEX'S OWN WORDS FOR PEOPLE:", or "Alex'S ..." as `rouh/owner.py` fills it in).
        if line.isupper() or line.startswith(("PEOPLE", "PROJECTS", "TASKS")) \
                or re.match(r"^.+'S OWN WORDS FOR PEOPLE:", line):
            section = line.split(" ", 1)[0]
            continue
        person = re.match(r"^(P\d+) ([^(]+?)(?: \(.*?\))?(?: - .+? calls them (.*))?$", line)
        if section == "PEOPLE" and person:
            calls = re.findall(r'"([^"]+)"', person.group(3) or "")
            if says(person.group(2)) or any(says(c) for c in calls):
                got["people"].append(f"{person.group(1)} {person.group(2)}")
        task = re.match(r"^(\d+(?:-\d+)*) ", line)
        if section == "TASKS" and task and re.search(rf"(?<![\w-]){task.group(1)}(?!\w|-\d)", low):
            got["tasks"].append(task.group(1))
        project = re.match(r"^([\w/.-]+): (.+)$", line)
        if section == "PROJECTS" and project and says(project.group(2)):
            got["projects"].append(project.group(1))
    got["topics"] = re.findall(r'"([^"]{3,60})"', message)[:3]
    got["related"] = sum(len(v) for v in got.values() if isinstance(v, list)) >= 2
    return got


def turn_mark(body: dict, items: list) -> str:
    if MARK_INSTRUCTION not in str(body.get("instructions") or ""):
        return ""
    last = items[-1] if items else {}
    if last.get("role") == "user" and " ".join(_texts(last.get("content"))).strip() == ANSWER_NOW.strip():
        return FINISHED
    _at, user = _last_user(items)
    found = MARK_WORDS.findall(" ".join(_texts((user or {}).get("content"))))
    return MARKS_BY_WORD[found[-1]] if found else FINISHED


def countdown(line: re.Pattern, text: str) -> bool:
    """Whether this request is one of the next n that `OVERLOAD n` / `DROP n` asked for."""
    found = line.search(text)
    if not found:
        return False
    key = found.group(0) + "|" + text
    left = _countdown.setdefault(key, int(found.group(1)))
    if left <= 0:
        return False
    _countdown[key] = left - 1
    return True


def usage_of(raw: bytes, body: dict) -> dict:
    """What a real cache would report: the prefix shared with the last request read."""
    text = json.dumps([body.get("instructions"), body.get("tools"), body.get("input")])
    before = _last_prefix["text"]
    common = 0
    for a, b in zip(before, text):
        if a != b:
            break
        common += 1
    _last_prefix["text"] = text
    sent = max(1, len(text) // 4)
    read = min(sent, common // 4)
    wrote = max(0, sent - read) if sent >= 1024 else 0
    return {"input_tokens": sent,
            "input_tokens_details": {"cached_tokens": read, "cache_write_tokens": wrote},
            "output_tokens": 40, "output_tokens_details": {"reasoning_tokens": 12},
            "total_tokens": sent + 40}


#: The GPT Image models, and the two that also draw `xhigh` and `max` and any
#: size in steps of 16.
IMAGE_MODELS = ("gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5", "gpt-image-2",
                "gpt-image-2-2026-04-21", "gpt-image-2.5-sunburst",
                "gpt-image-2.5-sunburst-2026-09-08", "gpt-image-2.5-flare",
                "gpt-image-2.5-flare-2026-09-08", "chatgpt-image-latest")
ANY_SIZE = tuple(m for m in IMAGE_MODELS if m.startswith("gpt-image-2"))
FINEST = tuple(m for m in IMAGE_MODELS if m.startswith("gpt-image-2.5"))
STANDARD_SIZES = ("1024x1024", "1536x1024", "1024x1536")


def _picture_refuses(fields: dict) -> str | None:
    """What the real Images API would say to this, or None."""
    model = str(fields.get("model") or "")
    if model not in IMAGE_MODELS:
        return (f"Invalid value: '{model}'. Supported values are: "
                + ", ".join(f"'{m}'" for m in IMAGE_MODELS) + ".")
    if not str(fields.get("prompt") or "").strip():
        return "Missing required parameter: 'prompt'."
    size = str(fields.get("size") or "auto")
    if size != "auto" and size not in STANDARD_SIZES:
        found = re.fullmatch(r"(\d+)x(\d+)", size)
        if model not in ANY_SIZE or not found:
            return f"Invalid value: '{size}'. Supported values are: 'auto', " + ", ".join(
                f"'{s}'" for s in STANDARD_SIZES) + "."
        w, h = int(found.group(1)), int(found.group(2))
        if w % 16 or h % 16 or max(w, h) > 3840 or max(w, h) > 3 * min(w, h):
            return (f"Invalid size '{size}'. Width and height must both be divisible by 16, "
                    "at most 3840, and the aspect ratio between 1:3 and 3:1.")
    quality = str(fields.get("quality") or "auto")
    allowed = ("auto", "low", "medium", "high") + (("xhigh", "max") if model in FINEST else ())
    if quality not in allowed:
        return f"Invalid value: '{quality}'. Supported values are: " + ", ".join(
            f"'{q}'" for q in allowed) + "."
    if fields.get("background") == "transparent" and fields.get("output_format") == "jpeg":
        return "Transparent background is not supported for the jpeg output format."
    try:
        n = int(fields.get("n") or 1)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= 10:
        return "Invalid 'n': must be between 1 and 10."
    return None


def _size_of(fields: dict, handed=None) -> tuple[int, int]:
    size = str(fields.get("size") or "auto")
    found = re.fullmatch(r"(\d+)x(\d+)", size)
    if found:
        return int(found.group(1)), int(found.group(2))
    if handed is not None:
        return handed.size
    return 1024, 1024


def _hue_of(words: str) -> float:
    return int(hashlib.sha256(words.encode()).hexdigest()[:6], 16) / 0xFFFFFF


#: Each request draws its own picture from the same words, as the real model
#: does, so a set of four is four pictures to pick from.
_drawings = itertools.count()


def _mosaic(size: tuple[int, int], words: str, square: int):
    """The stand-in's picture: squares of colour out of the words, `square`
    pixels across, so a rough preview is the same picture in bigger squares."""
    import colorsys

    from PIL import Image

    w, h = size
    cols, rows = max(1, -(-w // square)), max(1, -(-h // square))
    small = Image.new("RGB", (cols, rows))
    hue = _hue_of(words)
    pixels = []
    for y in range(rows):
        for x in range(cols):
            t = (x / max(1, cols - 1) + y / max(1, rows - 1)) / 2
            r, g, b = colorsys.hsv_to_rgb((hue + 0.35 * t) % 1.0, 0.55 + 0.35 * t, 0.95 - 0.4 * t)
            pixels.append((int(r * 255), int(g * 255), int(b * 255)))
    small.putdata(pixels)
    return small.resize((cols * square, rows * square), Image.NEAREST).crop((0, 0, w, h))


def _png(picture) -> bytes:
    import io

    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def _drawn(fields: dict, square: int, handed=None, mask=None):
    """One picture, finished or rough: new, tinted all over, or repainted where
    the mask lets it be."""
    from PIL import Image

    words = str(fields.get("prompt") or "")
    size = _size_of(fields, handed)
    fresh = _mosaic(size, words, square)
    if handed is None:
        return fresh
    base = handed.convert("RGBA").resize(size)
    fresh = fresh.convert("RGBA")
    if mask is not None:
        # Transparent in the mask is where the picture may change.
        alpha = mask.convert("RGBA").resize(size).getchannel("A")
        where = alpha.point(lambda a: 255 if a == 0 else 0)
        if str(fields.get("model") or "").startswith("gpt-image-2.5-sunburst"):
            base = Image.blend(base, fresh, 0.45)
            base.paste((0, 0, 0, 255), (0, 0) + size, where)
            return base
        base.paste(fresh, (0, 0), where)
        return base
    return Image.blend(base, fresh, 0.45)


def _clear(fields: dict, picture):
    """The picture on the background asked for.

    `background: transparent` gives the mosaic in a round shape with nothing
    around it, fully transparent, the way a model that heeds it draws a cut-out
    subject. `OPAQUEPICTURE` in the prompt is a model that does not heed it: the
    same round mosaic on a flat dark backdrop painted into every pixel, which is
    what the real Sunburst gave back on 8 November 2026 (`imaging.ensure_transparent`).
    """
    from PIL import Image, ImageDraw

    if fields.get("background") != "transparent":
        return picture
    w, h = picture.size
    shape = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape).ellipse((w * 0.2, h * 0.2, w * 0.8, h * 0.8), fill=255)
    if "OPAQUEPICTURE" in str(fields.get("prompt") or ""):
        out = Image.new("RGB", (w, h), (18, 30, 52))
        out.paste(picture.convert("RGB"), (0, 0), shape)
        return out
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(picture.convert("RGBA"), (0, 0), shape)
    return out


def _image_of(data: bytes):
    import io

    from PIL import Image

    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
        return picture
    except Exception:                                   # noqa: BLE001 - not a picture
        return None


def _add_pictures(app: FastAPI, record_dir: str) -> None:
    """`/v1/images/generations` and `/v1/images/edits` (see the top of the file)."""

    def record(kept: dict) -> None:
        name = f"image-{time.time():.6f}-{len(os.listdir(record_dir)):03d}.json"
        with open(os.path.join(record_dir, name), "w") as fh:
            json.dump(kept, fh, indent=1)

    def answer(fields: dict, kind: str, handed=None, mask=None):
        words = str(fields.get("prompt") or "")
        fields = dict(fields, prompt=f"{words} #{next(_drawings)}")
        if "REFUSEPICTURE" in words:
            return _error(400, "Your request was rejected as a result of our safety system. "
                               "Your request may contain content that is not allowed by our "
                               "safety system.", code="moderation_blocked")
        n = int(fields.get("n") or 1)
        size = "x".join(map(str, _size_of(fields, handed)))
        quality = str(fields.get("quality") or "auto")
        quality = "medium" if quality == "auto" else quality
        background = str(fields.get("background") or "auto")
        background = "opaque" if background == "auto" else background
        common = {"background": background, "output_format": str(fields.get("output_format")
                                                                  or "png"),
                  "quality": quality, "size": size}
        usage = {"input_tokens": 20 + len(words.split()) + (1500 if handed is not None else 0),
                 "input_tokens_details": {"text_tokens": 20 + len(words.split()),
                                          "image_tokens": 1500 if handed is not None else 0},
                 "output_tokens": 4160, "total_tokens": 0}
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        stream = str(fields.get("stream")).lower() == "true"
        if not stream:
            data = [{"b64_json": base64.b64encode(_png(_clear(fields, _drawn(fields, 16, handed, mask))))
                     .decode()} for _ in range(n)]
            return JSONResponse({"created": int(time.time()), "data": data, "usage": usage,
                                 **common})
        partials = max(0, min(3, int(fields.get("partial_images") or 0)))
        slow = 1.5 if "SLOWPICTURE" in words else 0.2
        broken = "BROKENPICTURE" in words

        def events():
            for index in range(partials):
                time.sleep(slow)
                rough = _png(_clear(fields, _drawn(fields, (128, 48, 24)[index], handed, mask)))
                yield _sse({"type": f"{kind}.partial_image", "partial_image_index": index,
                            "b64_json": base64.b64encode(rough).decode(),
                            "created_at": int(time.time()), **common})
            time.sleep(slow)
            if broken:
                yield _sse({"type": "error", "error": {
                    "type": "server_error", "code": "server_error",
                    "message": "The server had an error while processing your request."}})
                return
            done = _png(_clear(fields, _drawn(fields, 16, handed, mask)))
            yield _sse({"type": f"{kind}.completed", "b64_json": base64.b64encode(done).decode(),
                        "created_at": int(time.time()), "usage": usage, **common})

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1/images/generations")
    async def generations(request: Request):
        raw = await request.body()
        try:
            fields = json.loads(raw)
        except ValueError:
            fields = {}
        record({"endpoint": "generations", **fields})
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "You didn't provide an API key.", code="invalid_api_key")
        why = _picture_refuses(fields)
        if why:
            return _error(400, why)
        return answer(fields, "image_generation")

    @app.post("/v1/images/edits")
    async def edits(request: Request):
        form = await request.form()
        fields: dict = {}
        files: dict = {}
        for key, value in form.multi_items():
            if hasattr(value, "read"):
                data = await value.read()
                picture = _image_of(data)
                files.setdefault(key.removesuffix("[]"), []).append((data, picture))
            else:
                fields[key] = value
        kept = dict(fields)
        for key, got in files.items():
            kept[key] = [{"bytes": len(d), "size": list(p.size) if p else None,
                          "format": p.format if p else None} for d, p in got]
        record({"endpoint": "edits", **kept})
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "You didn't provide an API key.", code="invalid_api_key")
        why = _picture_refuses(fields)
        handed = [p for _d, p in files.get("image", [])]
        if why is None and not handed:
            why = "Missing required parameter: 'image'."
        if why is None and any(p is None for p in handed):
            why = "Invalid image file or mode for image 1, please check your image file."
        if why is None and len(handed) > 16:
            why = "Too many images: at most 16 may be given."
        mask = None
        if why is None and files.get("mask"):
            mask = files["mask"][0][1]
            if mask is None or mask.format != "PNG":
                why = "Invalid mask image format - mask image must be a PNG."
            elif mask.size != handed[0].size:
                why = (f"Invalid mask image size - the mask ({mask.size[0]}x{mask.size[1]}) "
                       f"must be the same size as the image ({handed[0].size[0]}x"
                       f"{handed[0].size[1]}).")
        if why:
            return _error(400, why)
        return answer(fields, "image_edit", handed[0], mask)


DECISION_FIELDS = ("model", "input", "questions", "prompt_cache_key", "prompt_cache_options",
                   "safety_identifier")


def _decision_refuses(body: dict) -> str | None:
    """What the real Decisions API would refuse about a request, in its words, or None."""
    for key in body:
        if key not in DECISION_FIELDS:
            return f"Unknown parameter: '{key}'."
    if body.get("model") != MODEL:
        return f"The model '{body.get('model')}' is not supported by the Decisions API."
    questions = body.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 400:
        return "'questions' must have between 1 and 400 items."
    names = [q.get("name") for q in questions if isinstance(q, dict) and q.get("name") is not None]
    if len(set(names)) != len(names):
        return "Question names must be unique."
    for q in questions:
        kind = q.get("type") if isinstance(q, dict) else None
        if kind == "choice":
            values = [c.get("value") for c in q.get("choices") or [] if isinstance(c, dict)]
            if not 2 <= len(values) <= 255 or len(set(map(repr, values))) != len(values):
                return "Provide between 2 and 255 choices. Each choice must be unique."
        elif kind == "score":
            if not 2 <= len(q.get("levels") or []) <= 10:
                return "'levels' must have between 2 and 10 items."
        elif kind != "predicate":
            return f"Invalid value for 'questions[].type': {kind!r}."
        if "instructions" not in q:
            return "Missing required parameter: 'questions[].instructions'."
    return None


def _decision_answer(q: dict, said: str) -> dict:
    asked = re.search(r"DECIDE\s+([A-Za-z][A-Za-z0-9_.-]*)(?:\s+(0?\.\d+|1\.0+|1))?",
                      said.split("The new message:")[-1])
    # The router's easy-or-hard question (`modelrouter.QUESTION`): `ROUTE CHEAPER` is easy at
    # 0.95, over the bar of 0.9; `ROUTE SMART` (or the old DAILY and BEST) is hard.
    routed = re.search(r"ROUTE\s+(CHEAPER|SMART|DAILY|BEST)", said.split("The new message:")[-1])
    want = (asked.group(1) if asked else
            ("easy" if routed.group(1) == "CHEAPER" else "hard") if routed else "").strip()
    sure = float(asked.group(2)) if asked and asked.group(2) else (0.95 if routed else 0.8)
    name = q.get("name")
    if q["type"] == "predicate":
        return {"type": "predicate", "name": name, "probability": 0.9 if want.upper() == "YES" else 0.5}
    if q["type"] == "choice":
        values = [c["value"] for c in q["choices"]]
        pick = next((v for v in values if str(v).lower() == want.lower()), values[0])
        rest = (1 - sure) / (len(values) - 1)
        return {"type": "choice", "name": name, "choice": pick, "confidence": 0.6,
                "probabilities": [{"value": v, "probability": sure if v == pick else rest} for v in values]}
    labels = [lv.get("label") for lv in q["levels"]]
    at = next((i for i, lv in enumerate(labels) if str(lv).lower() == want.lower()), 0)
    rest = (1 - 0.8) / (len(labels) - 1)
    probs = [0.8 if i == at else rest for i in range(len(labels))]
    return {"type": "score", "name": name, "confidence": 0.6, "score": sum(i * p for i, p in enumerate(probs)),
            "probabilities": [{"value": i, "label": lv, "probability": probs[i]} for i, lv in enumerate(labels)]}


def build_app(record_dir: str) -> FastAPI:
    app = FastAPI()
    os.makedirs(record_dir, exist_ok=True)
    _add_pictures(app, record_dir)

    @app.post("/v1/decisions")
    async def decisions(request: Request):
        raw = await request.body()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        name = f"decision-{time.time():.6f}-{len(os.listdir(record_dir)):03d}.json"
        with open(os.path.join(record_dir, name), "wb") as fh:
            fh.write(raw)
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "You didn't provide an API key.", code="invalid_api_key")
        said = json.dumps(body.get("input") or "")
        said = said.split("The new message:")[-1]
        if "DECISIONSREFUSED" in said:
            return _error(403, "Decision API is not enabled for this user.", kind="permission_error")
        if "DECISIONSDOWN" in said:
            return _error(500, "The server had an error while processing your request.", kind="server_error")
        if "DECISIONSSLOW" in said:
            await asyncio.sleep(5)
        why = _decision_refuses(body if isinstance(body, dict) else {})
        if why:
            return _error(400, why)
        tokens = max(1, len(raw) // 4)
        return JSONResponse({"model": MODEL, "answers": [_decision_answer(q, said) for q in body["questions"]],
                             "usage": {"input_tokens": tokens,
                                       "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                                       "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0},
                                       "total_tokens": tokens}})

    # A key is judged by its own words, the way the first run's brain screen meets real ones
    # (`rouh/web/firstrun.py`): WRONG in it is a key OpenAI does not know, NOCREDIT a right key
    # on an account with no credit.
    def _refused_key(request: Request, asking: bool):
        key = request.headers.get("authorization", "")
        if "WRONG" in key:
            return _error(401, "Incorrect API key provided. You can find your API key at "
                               "https://platform.openai.com/account/api-keys.", code="invalid_api_key")
        if asking and "NOCREDIT" in key:
            return _error(429, "You exceeded your current quota, please check your plan and billing details.",
                          kind="insufficient_quota", code="insufficient_quota")
        return None

    @app.get("/v1/models")
    async def models_list(request: Request):
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "You didn't provide an API key.", code="invalid_api_key")
        refused = _refused_key(request, asking=False)
        if refused is not None:
            return refused
        return JSONResponse({"object": "list", "data": [{"id": "gpt-4.1-mini", "object": "model", "created": 0,
                                                         "owned_by": "openai"}]})

    @app.post("/v1/responses")
    async def responses(request: Request):
        raw = await request.body()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        name = f"luna-{time.time():.6f}-{len(os.listdir(record_dir)):03d}.json"
        with open(os.path.join(record_dir, name), "wb") as fh:
            fh.write(raw)
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "You didn't provide an API key.", code="invalid_api_key")
        refused = _refused_key(request, asking=True)
        if refused is not None:
            return refused
        why = refuses(body)
        if why is None and "DESCRIPTIONLIMIT" in json.dumps(body.get("input") or ""):
            for n, tool in enumerate(body.get("tools") or []):
                said = str(tool.get("description") or "")
                if len(said) > DESCRIPTION_MAX:
                    why = (400, f"Invalid 'tools[{n}].description': string too long. Expected a "
                                f"string with maximum length {DESCRIPTION_MAX}, but got a string "
                                f"with length {len(said)} instead.", "string_above_max_length")
                    break
        if why:
            status, message, code = why
            return _error(status, message, code=code)
        items = body.get("input") or []
        if isinstance(items, str):
            items = [{"role": "user", "content": items}]
        _at, user = _last_user(items)
        words = " ".join(_texts((user or {}).get("content")))
        if countdown(OVERLOAD_LINE, words):
            return JSONResponse(status_code=503, headers={"retry-after": "0"}, content={
                "error": {"message": "The server is overloaded.", "type": "server_error",
                          "param": None, "code": "server_is_overloaded"}})
        drop = countdown(DROP_LINE, words)
        mark = turn_mark(body, items)
        unfinished = mark in (CUT_OFF_MID_THOUGHT, STILL_THINKING)
        # A request that offers no tools can be answered by none, whatever
        # its words say: a word review quotes an email's TOOL lines as data.
        call = None if unfinished or not body.get("tools") else wanted_tool(items)
        answered_web = any(item.get("type") == "web_search_call" for item in items[_at + 1:])
        search = None if (unfinished or call) else SEARCH_LINE.search(words)
        opened = None if (unfinished or call or search) else OPEN_LINE.search(words)
        slow = not unfinished and call is None and SLOW_MARK in words
        shaped = claude_errand(body, words) or shaped_answer(body, words)
        if (((body.get("text") or {}).get("format") or {}).get("name") == "recall_pick"
                and "PICKSLOW" in words.split("THE MESSAGE:")[-1]):
            # A reading that is late, so the other company's answers first (`autorecall.ask`).
            await asyncio.sleep(3)
        usage = usage_of(raw, body)
        rid = f"resp_luna{next(_ids):04d}"
        n = next(_ids)
        summary = ([{"type": "summary_text", "text": "Fake readable reasoning summary."}]
                   if (body.get("reasoning") or {}).get("summary") == "auto" else [])

        def response(status: str, output: list) -> dict:
            return {"id": rid, "object": "response", "created_at": int(time.time()),
                    "status": status, "model": MODEL, "output": output,
                    "parallel_tool_calls": True, "tool_choice": "auto",
                    "tools": body.get("tools") or [], "usage": usage if status != "in_progress" else None,
                    "incomplete_details": None, "error": None, "store": False,
                    "reasoning": body.get("reasoning")}

        if not body.get("stream") and shaped is not None:
            # Asked for a JSON shape without a stream, the way Synapse asks
            # (`rouh/synapse/ai.py`): the whole response at once.
            part = {"type": "output_text", "text": shaped, "annotations": [], "logprobs": []}
            whole = response("completed", [
                {"type": "reasoning", "id": f"rs_luna{n:04d}", "summary": summary,
                 "encrypted_content": f"enc-{n:04d}"},
                {"type": "message", "id": f"msg_luna{next(_ids):04d}", "role": "assistant",
                 "status": "completed", "content": [part]}])
            whole["output_text"] = shaped
            return JSONResponse(whole)

        def stream():
            seq = itertools.count()

            def ev(kind: str, **fields) -> bytes:
                return _sse({"type": kind, "sequence_number": next(seq), **fields})

            output: list[dict] = []
            yield ev("response.created", response=response("in_progress", []))
            if drop:
                failed = response("failed", [])
                failed["error"] = {"code": "server_error",
                                   "message": "The model broke off part way through."}
                yield ev("response.failed", response=failed)
                return
            reasoning = {"type": "reasoning", "id": f"rs_luna{n:04d}", "summary": summary,
                         "encrypted_content": f"enc-{n:04d}"}
            yield ev("response.output_item.added", output_index=0, item=dict(reasoning))
            yield ev("response.output_item.done", output_index=0, item=reasoning)
            output.append(reasoning)

            def message(text: str, annotations: list, index: int, pause: float = 0.0):
                mid = f"msg_luna{next(_ids):04d}"
                started = {"type": "message", "id": mid, "role": "assistant",
                           "status": "in_progress", "content": []}
                yield ev("response.output_item.added", output_index=index, item=started)
                yield ev("response.content_part.added", output_index=index, item_id=mid,
                         content_index=0, part={"type": "output_text", "text": "", "annotations": []})
                pieces = text.split(" ") if pause else [text]
                written = ""
                # Each annotation is announced once, as soon as the words it
                # covers have all been written, the way the real stream does.
                announced: set[int] = set()
                for i, piece in enumerate(pieces):
                    delta = piece + (" " if pause and i < len(pieces) - 1 else "")
                    written += delta
                    yield ev("response.output_text.delta", output_index=index, item_id=mid,
                             content_index=0, delta=delta, logprobs=[])
                    for k, note in enumerate(annotations):
                        if note["end_index"] <= len(written) and k not in announced:
                            announced.add(k)
                            yield ev("response.output_text.annotation.added", output_index=index,
                                     item_id=mid, content_index=0, annotation_index=k,
                                     annotation=note)
                    if pause:
                        time.sleep(pause)
                part = {"type": "output_text", "text": text, "annotations": annotations}
                yield ev("response.output_text.done", output_index=index, item_id=mid,
                         content_index=0, text=text, logprobs=[])
                yield ev("response.content_part.done", output_index=index, item_id=mid,
                         content_index=0, part=part)
                done = {"type": "message", "id": mid, "role": "assistant",
                        "status": "completed", "content": [part]}
                yield ev("response.output_item.done", output_index=index, item=done)
                output.append(done)

            known = declared(body)
            space, definition = known.get(call[0], ("", {})) if call is not None else ("", {})
            needs_search = (call is not None and definition.get("defer_loading")
                            and call[0] not in loaded(items))
            mode = search_mode(body)
            if needs_search:
                # Deferred and not loaded: it has to be searched for first.
                ts = {"type": "tool_search_call", "id": f"ts_luna{n:04d}",
                      "execution": mode, "status": "completed",
                      "call_id": f"tsc_luna{n:04d}" if mode == "client" else None,
                      "arguments": {"query": call[0]}}
                yield ev("response.output_item.added", output_index=1,
                         item=dict(ts, status="in_progress"))
                yield ev("response.output_item.done", output_index=1, item=ts)
                output.append(ts)
                if mode == "client":
                    # The caller runs it, and calls back with what it loaded.
                    yield ev("response.completed", response=response("completed", output))
                    return
                spaced = definition.get("_space") or {}
                fn = {k: v for k, v in definition.items() if k != "_space"}
                found = ({"type": "namespace", "name": spaced.get("name"),
                          "description": spaced.get("description", ""), "tools": [fn]}
                         if spaced else fn)
                tso = {"type": "tool_search_output", "id": f"tso_luna{n:04d}",
                       "execution": "server", "call_id": None, "status": "completed",
                       "tools": [found]}
                yield ev("response.output_item.added", output_index=2, item=dict(tso))
                yield ev("response.output_item.done", output_index=2, item=tso)
                output.append(tso)
            if call is not None:
                tool, args = call
                fc = {"type": "function_call", "id": f"fc_luna{n:04d}",
                      "call_id": f"call_luna{n:04d}", "name": tool, "arguments": "",
                      "status": "in_progress"}
                if space:
                    fc["namespace"] = space
                yield ev("response.output_item.added", output_index=1, item=dict(fc))
                arguments = json.dumps(args)
                yield ev("response.function_call_arguments.delta", output_index=1,
                         item_id=fc["id"], delta=arguments)
                yield ev("response.function_call_arguments.done", output_index=1,
                         item_id=fc["id"], arguments=arguments, name=tool)
                fc.update(arguments=arguments, status="completed")
                yield ev("response.output_item.done", output_index=1, item=fc)
                output.append(fc)
            elif (search or opened) and not answered_web:
                ws_id = f"ws_luna{n:04d}"
                yield ev("response.output_item.added", output_index=1,
                         item={"type": "web_search_call", "id": ws_id, "status": "in_progress"})
                yield ev("response.web_search_call.in_progress", output_index=1, item_id=ws_id)
                yield ev("response.web_search_call.searching", output_index=1, item_id=ws_id)
                time.sleep(0.5)
                yield ev("response.web_search_call.completed", output_index=1, item_id=ws_id)
                if search:
                    query = search.group(1).strip()
                    action = {"type": "search", "query": query,
                              "sources": [{"type": "url", "url": u} for u, _t in PAGES]}
                else:
                    action = {"type": "open_page", "url": opened.group(1)}
                ws = {"type": "web_search_call", "id": ws_id, "status": "completed",
                      "action": action}
                yield ev("response.output_item.done", output_index=1, item=ws)
                output.append(ws)
                if search:
                    first = f"{mark} The first page says the price is nineteen euros."
                    second = " The second page agrees with it."
                    text = first + second
                    annotations = [
                        {"type": "url_citation", "start_index": 2, "end_index": len(first),
                         "url": PAGES[0][0], "title": PAGES[0][1]},
                        {"type": "url_citation", "start_index": len(first) + 1,
                         "end_index": len(text), "url": PAGES[1][0], "title": PAGES[1][1]},
                    ]
                else:
                    text = f"{mark} That page says what Luna read on it."
                    annotations = [{"type": "url_citation", "start_index": 2,
                                    "end_index": len(text), "url": opened.group(1),
                                    "title": "The page Luna opened"}]
                yield from message(text, annotations, 2, pause=0.02)
            else:
                if unfinished:
                    text = mark
                elif slow:
                    text = f"{mark} {SLOW_ANSWER}" if mark else SLOW_ANSWER
                elif shaped is not None:
                    text = shaped
                else:
                    said = describe(items)
                    text = f"{mark} {said}" if mark else said
                yield from message(text, [], 1, pause=SLOW_WORD_SECONDS if slow else 0.0)
            yield ev("response.completed", response=response("completed", output))

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", required=True)
    args = ap.parse_args()
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
