"""The small program every Codex hook runs: post the hook to the program, print its answer.

Claude Code posts a hook straight to an address (``"type": "http"``). Codex
0.154.0 has no such hook: its own words when it is given one are ``unknown
variant `http`, expected one of `command`, `mcp_tool`, `prompt`, `agent``.
So each of a Codex run's hooks is a command hook running this, which reads the
hook's JSON on its input, posts it to the same address Claude Code's hooks post
to, and prints the program's answer for Codex to read. The shapes on both sides
are the same, so the program decides a Codex call with the code that decides a
Claude one.

**A call this cannot get an answer for is refused, never allowed.** If the
program is not answering, or the answer is not JSON, a hook that decides
something says deny and gives the reason; every other hook says nothing, which
Codex reads as "carry on". A Claude Code run has a second line behind the
hooks - the deny rules in its own settings, which Claude Code enforces with no
hook involved - and Codex has nothing of the kind, so the hook failing open
would leave a Codex run with no rules at all.

The run's key is read from the environment, not taken as an argument: an
argument is on the process list for every account on this machine to read.

Only the standard library, and nothing newer than Python 3.9: it runs under
whichever python3 the run's own machine has.

**A PreToolUse call the program allows is answered with nothing at all.**
Codex honours only ``deny`` there: an ``allow`` (or ``ask``) is reported as
"Hook failed: PreToolUse hook returned unsupported permissionDecision:allow"
on the run's screen, and the call then runs anyway, so every allowed call
looked like a broken hook. Seen with codex-cli 0.163.0 on 20 October 2026.
The program's answer is shared with Claude Code, which does want the allow, so
it is this poster, Codex's alone, that drops it: an allow becomes no output,
a deny goes through untouched, and an ``ask``, which the program never sends,
is refused rather than passed on to fail open.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

#: The hooks whose answer decides whether a call runs. Anything else is told
#: about a call, and cannot stop it.
DECIDING = {"pre_tool_use": "PreToolUse", "permission_request": "PermissionRequest"}


def refusal(kind, why):
    """The answer that stops the call, in the shape that hook reads."""
    if kind == "permission_request":
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                       "decision": {"behavior": "deny", "message": why}}}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": why}}


def for_codex(kind, text):
    """What Codex is given for the program's answer ``text`` to a ``kind`` hook."""
    if kind != "pre_tool_use":
        return text or "{}"
    answer = json.loads(text or "{}")
    said = (answer.get("hookSpecificOutput") or {}) if isinstance(answer, dict) else {}
    decision = said.get("permissionDecision") if isinstance(said, dict) else None
    if decision == "deny":
        return text
    if decision == "ask":
        return json.dumps(refusal(kind, (
            "The one program would have asked the person about this call, and a Codex "
            "run cannot be asked, so it was not allowed.")))
    return ""


def main(argv):
    if len(argv) < 4:
        sys.stderr.write("usage: codexhook.py <hook-url> <run> <kind> [timeout]\n")
        return 2
    url, run, kind = argv[1], argv[2], argv[3]
    timeout = float(argv[4]) if len(argv) > 4 else 60.0
    payload = sys.stdin.read()
    key = os.environ.get("ONE_HOOK_KEY", "")
    where = url + "?" + urllib.parse.urlencode({"run": run, "kind": kind, "key": key})
    try:
        request = urllib.request.Request(
            where, data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            text = answer.read().decode("utf-8", "replace").strip()
        json.loads(text or "{}")          # an answer that is not JSON is no answer
    except Exception as exc:              # noqa: BLE001 - every failure is the same failure
        if kind in DECIDING:
            sys.stdout.write(json.dumps(refusal(kind, (
                "The one program could not be asked about this call "
                "(%s), so it was not allowed. Carry on without it, or stop and say what you "
                "needed." % type(exc).__name__))))
            return 0
        sys.stdout.write("{}")
        return 0
    sys.stdout.write(for_codex(kind, text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
