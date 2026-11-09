"""The owner's worker subscriptions, in Anatomy Connections.

Uses the setup protocol and its owner gate. Only safe identity and usage metadata
cross the worker boundary; authentication always completes in the vendors' flow.
"""
import asyncio
import json

from django.http import Http404, JsonResponse

from rouh.one_client import OneRefused, OneUnavailable
from . import claude_signin, codex_signin


async def card(provider: str) -> dict:
    ask = codex_signin._ask if provider == "codex" else claude_signin._ask
    status = await ask("status", timeout=40)
    plan = status.get("plan") if provider == "codex" else status.get("subscriptionType")
    method = status.get("method", "")
    on_plan = bool(status.get("signed_in") and method in ("chatgpt", "claude.ai", "oauth")
                   and not status.get("api_key_through_proxy"))
    out = {**status, "on_plan": on_plan, "reached": True}
    if provider == "claude":
        from one.subscriptions import workspace
        out.update(plan=plan or "", workspace=workspace(str(plan or "")),
                   workspace_name=status.get("orgName") or "")
    if on_plan and not status.get("waiting") and not status.get("waiting_for_code"):
        out["limits"] = await ask("limits", timeout=25)
    return out


async def endpoint(request, provider):
    if not claude_signin.enabled() or not claude_signin._may(request.user) or provider not in ("claude", "codex"):
        raise Http404
    if request.method not in ("GET", "POST"):
        return JsonResponse({"problem": "Use GET or POST."}, status=405)
    ask = codex_signin._ask if provider == "codex" else claude_signin._ask
    try:
        if request.method == "POST":
            try:
                body = json.loads(request.body)
            except (ValueError, UnicodeDecodeError):
                return JsonResponse({"problem": "The request could not be read."}, status=400)
            if not isinstance(body, dict):
                return JsonResponse({"problem": "The request could not be read."}, status=400)
            do = body.get("do")
            allowed = ("start", "cancel", "logout", "code") if provider == "claude" else ("start", "cancel", "logout")
            if do not in allowed:
                return JsonResponse({"problem": "Choose a sign-in action."}, status=400)
            if do == "logout" and body.get("confirmed") is not True:
                return JsonResponse({"problem": "Confirm Sign out first."}, status=400)
            fields = {k: body[k] for k in ("workspace", "account_id", "code") if k in body}
            await ask(do, timeout=100 if do == "code" else 60, **fields)
            if provider == "codex" and do == "start":
                # Signing in with a plan is an explicit choice of subscription billing.
                await ask("api_key", on=False)
        result = await card(provider)
        from rouh import clock
        from .common import who
        me = await asyncio.to_thread(who, request)
        result["zone"] = str(clock.zone_of(me))
        return JsonResponse(result, headers={"Cache-Control": "no-store"})
    except OneRefused as exc:
        return JsonResponse({"problem": str(exc)}, status=400, headers={"Cache-Control": "no-store"})
    except (OneUnavailable, asyncio.TimeoutError):
        return JsonResponse({"reached": False, "problem": "The worker is not answering. Press Refresh to try again."},
                            status=503, headers={"Cache-Control": "no-store"})
