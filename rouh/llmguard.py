"""`python -m rouh.llmguard`: nothing asks a model past the LLM service, or names one.

Petar, 3 October 2026: "Please make sure no LLM code runs outside of our service
that tracks usage and pricing." And the evening of 18 October 2026: "Every call
that we make now has to route through our new model selection. Whatever we select
here should be the one called. No exceptions." Asked "so this cannot come back",
this reads Rouh's own source and fails on any of three things:

1. **A model client made anywhere but `rouh/llmlog.py`**, the clients that write
   every request down, or a provider's address written into the code.
2. **A model asked anywhere but the LLM service** (`SERVICE`): `rouh/llm.py`, which
   asks one question of the model a use is set to, and the few loops that are more
   than one question and take their model from the Models page the same way.
3. **A model named in code** outside the files whose job is to list models and
   their facts (`NAMES_KEPT`): the list to choose from, prices, context sizes,
   image models. A model named anywhere else is a model nobody picked.

Run by `land.sh` before every push that touches Rouh's Python (`llm_guard`), and by
the deploy (`deploy/rouh.sh`, through `python -m rouh.llmlog`). Standard library only,
so it runs without Rouh's packages. Claude Code and Codex are programs of their own,
started for a run, and are not this.
"""
from __future__ import annotations

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

#: Where a model is asked: the LLM service. Each takes its model from the Models page
#: (`modeldefaults.use_pair`) at the moment of asking, and nothing else may ask one.
SERVICE = {
    "rouh/llm.py",              # one question, either company: every use that asks one
    "rouh/llmlog.py",           # the recording clients themselves
    "rouh/brain.py",            # a chat's turn on Anthropic's side
    "rouh/luna.py",             # a chat's turn on OpenAI's side
    "rouh/compat.py",           # a chat's turn on Google's or xAI's side (Chat Completions)
    "rouh/askai.py",            # Ask AI's loop of tools and page edits
    "rouh/commentpass.py",      # Ask AI's pass over a page's comments
    "rouh/subagent.py",         # look_into's loop, with Anthropic's web tools
    "rouh/synapse/ai.py",       # Synapse's engine: embeddings and structured answers
    "rouh/imaging.py",          # pictures, whose model is picked in the picture editor
    "rouh/imaging_openai.py",
}

#: Where a model may be named: the lists of models and of their facts.
NAMES_KEPT = {
    "rouh/config.py",           # the models there are to choose from (MODEL_CHOICES)
    "rouh/costs.py",            # what each costs
    "rouh/context_editing.py",  # how much each can read
    "rouh/imaging_openai.py",   # the picture models
    "rouh/llmguard.py",
}

#: What asks a model, as a call: `client.messages.create(...)` and the rest.
_ASKS = re.compile(r"^(?:messages\.(?:create|stream|count_tokens)|responses\.(?:create|stream|parse)"
                   r"|chat\.completions\.(?:create|parse)|completions\.create|embeddings\.create)$")

#: A model's id, whole: claude-opus-5-5, gpt-6-luna, gpt-4.1-mini, o3-mini. A family
#: written to test a name by (`startswith("gpt-5")`) is not a model and is not this; an
#: id on the list with no name after its number (gpt-5.5) is caught by `_listed`.
_MODEL = re.compile(r"^(?:claude-(?:opus|sonnet|haiku|fable)-\d[\w.-]*"
                    r"|gpt-\d[\d.]*-[a-z][\w.-]*|o[134]-[a-z]+"
                    r"|gemini-\d[\d.]*-[a-z][\w.-]*|grok-\d[\d.]*(?:-[\w.-]+)?)$")


def _listed(root: str) -> set[str]:
    """Every model id on the list to choose from (`config.MODEL_CHOICES`), read from
    config.py's source, so this needs nothing imported."""
    with open(os.path.join(root, "config.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("ANTHROPIC_CHOICES",
                                                                        "OPENAI_CHOICES",
                                                                        "GOOGLE_CHOICES",
                                                                        "XAI_CHOICES")
                                                for t in node.targets):
            for pair in getattr(node.value, "elts", []):
                first = pair.elts[0] if isinstance(pair, ast.Tuple) and pair.elts else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.add(first.value)
    return out


#: A client of a model provider's SDK, by the name of its class.
_SDK_CLIENT = re.compile(r"^(?:Async)?(?:Azure)?(?:Anthropic|OpenAI)(?:Bedrock|Vertex|Foundry)?$")

#: A provider's own address, which only a request past the SDK would need.
_PROVIDER_HOST = re.compile(r"api\.(?:anthropic|openai|voyageai)\.com|ai\.mongodb\.com|api\.x\.ai"
                            r"|generativelanguage\.googleapis")

#: Folders that are never Rouh asking: the stand-ins are the far end of a request.
_SKIP = {"testing", "__pycache__", "static", "templates", "migrations", "tests"}


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join(reversed(parts))


def strays(root: str = HERE) -> list[str]:
    """Every place in Rouh's source that breaks one of the three rules."""
    found = []
    top = os.path.dirname(root)
    listed = _listed(root)
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP)
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            where = os.path.relpath(path, top).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                            ast.ClassDef))
                          and n.body and isinstance(n.body[0], ast.Expr)
                          and isinstance(n.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called = getattr(func, "attr", None) or getattr(func, "id", None) or ""
                    if _SDK_CLIENT.match(called) and where != "rouh/llmlog.py":
                        found.append(f"{where}:{node.lineno} makes {called} directly: make it "
                                     "with rouh.llmlog.client or rouh.llmlog.openai_client")
                    tail = ".".join(_dotted(func).split(".")[-2:])
                    tail3 = ".".join(_dotted(func).split(".")[-3:])
                    if (_ASKS.match(tail) or _ASKS.match(tail3)) and where not in SERVICE:
                        found.append(f"{where}:{node.lineno} asks a model past the LLM service "
                                     f"({tail}): ask through rouh.llm.ask with the use's name")
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if _PROVIDER_HOST.search(node.value) and where != "rouh/llmlog.py":
                        found.append(f"{where}:{node.lineno} names "
                                     f"{_PROVIDER_HOST.search(node.value).group(0)}")
                    if ((_MODEL.match(node.value.strip()) or node.value.strip() in listed)
                            and where not in NAMES_KEPT
                            and id(node) not in docstrings):
                        found.append(f"{where}:{node.lineno} names the model {node.value!r}: a "
                                     "model comes from the Models page (modeldefaults.use_pair)")
    return found


def main() -> int:
    found = strays()
    for one in found:
        print("FAIL " + one, file=sys.stderr)
    if found:
        print(f"{len(found)} place(s) ask a model past the LLM service or name one in code",
              file=sys.stderr)
        return 1
    print("every model is asked through the LLM service, with the model the Models page gives it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
