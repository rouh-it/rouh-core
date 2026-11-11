"""Every request Rouh makes of a model, and what came of it (`rouh/llmlog.py`).

One row of `llm_requests` for every request that goes out: what was asked,
what came back, the reasoning the model returned, the tokens, the money, how
long it took, and whose it was. A request that failed, was stopped half way or
was tried again has a row of its own, because each one was sent and each one
may have been paid for.

What was asked is kept once however many times it is sent. A turn sends the
whole conversation again with every request, and the same system prompt and
tools with every turn, so a row holds the digests of its pieces
(`system_piece`, `tools_piece`, `message_pieces`) and `llm_pieces` holds each
piece once. `llmlog.request_of` puts a request back together as the JSON that
was sent, every key in the order it went.

Organisation and person are text columns, as everywhere else, and every one of
these rows carries both (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

from django.db import models


class LLMRequest(models.Model):
    """One request made of a model: one HTTP request, retries each their own."""

    id = models.BigAutoField(primary_key=True)
    #: When it was sent and when its answer ended, as epoch seconds like every
    #: other time Rouh keeps. `finished_at` is empty while it is in flight, and
    #: stays empty for a request the process went away in the middle of.
    started_at = models.FloatField()
    finished_at = models.FloatField(null=True, blank=True)

    # --- whose it was, and what it was for --------------------------------
    org_id = models.TextField(blank=True, default="")
    user_id = models.TextField(blank=True, default="")
    #: The chat it was made in, when it was made in one.
    session_id = models.TextField(blank=True, default="")
    #: Every request one spoken or typed turn made, tool rounds included.
    turn_id = models.TextField(blank=True, default="")
    #: What it was for: "turn", "subagent", "chat_title", "filing", "triage",
    #: "askai", "comment_pass". A request nobody said anything about is named
    #: after the code that sent it.
    purpose = models.TextField(blank=True, default="")
    #: What it was about, beyond the chat: a page, a task, a feedback.
    subject = models.TextField(blank=True, default="")
    #: The function in Rouh that sent it, `rouh/brain.py:pump`.
    caller = models.TextField(blank=True, default="")

    # --- what was asked ---------------------------------------------------
    provider = models.TextField(default="anthropic")
    endpoint = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    stream = models.BooleanField(default=False)
    max_tokens = models.IntegerField(null=True, blank=True)
    effort = models.TextField(blank=True, default="")
    #: "adaptive", "adaptive/summarized", "disabled", or "" when not said.
    thinking = models.TextField(blank=True, default="")
    #: Everything else the request said, beside its system prompt, its tools
    #: and its messages: `output_config`, `container`, `tool_choice`, ...;
    #: turn-only reasoning data is removed from the logged copy.
    settings = models.JSONField(default=dict)
    system_piece = models.CharField(max_length=64, blank=True, default="")
    tools_piece = models.CharField(max_length=64, blank=True, default="")
    message_pieces = models.JSONField(default=list)
    #: The digest of the whole request, so two identical sends - a retry - are
    #: one query apart.
    request_hash = models.CharField(max_length=64, blank=True, default="")
    request_bytes = models.IntegerField(default=0)
    #: 1 for a first try. A retry, by Rouh or by Anthropic's SDK, counts up.
    attempt = models.IntegerField(default=1)

    # --- what came back ---------------------------------------------------
    #: "sent" while in flight, then "ok", "error", or "stopped": closed by Rouh
    #: before the model had finished, which is still paid for.
    status = models.TextField(default="sent")
    http_status = models.IntegerField(null=True, blank=True)
    #: Anthropic's own id for the request, which is what their support asks for.
    request_id = models.TextField(blank=True, default="")
    message_id = models.TextField(blank=True, default="")
    #: The model that answered, as the answer names it.
    served_model = models.TextField(blank=True, default="")
    stop_reason = models.TextField(blank=True, default="")
    error_type = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    #: The words of the answer, and the model's reasoning as it returned it.
    #: A thinking block the model sent empty ("omitted") thought, was billed
    #: for it, and returned no words: `reasoning` is then empty and the block
    #: is still in `response`.
    text = models.TextField(blank=True, default="")
    reasoning = models.TextField(blank=True, default="")
    #: The answer as the API sent it, with encrypted reasoning credentials
    #: and thinking signatures removed: content blocks, tools, web results
    #: and usage.
    response = models.JSONField(null=True, blank=True)

    # --- what it took -----------------------------------------------------
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_read_tokens = models.BigIntegerField(default=0)
    cache_write_tokens = models.BigIntegerField(default=0)
    web_searches = models.IntegerField(default=0)
    #: The usage object exactly as the API reported it.
    usage = models.JSONField(default=dict)
    #: In dollars at list price (`rouh/costs.py`). Empty for a model nobody has
    #: priced, which is not the same as free.
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    #: Milliseconds from sending to the first word or thought, and to the end.
    first_token_ms = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "llm_requests"
        indexes = [
            models.Index(fields=["-started_at"], name="llm_requests_recent"),
            models.Index(fields=["user_id", "org_id", "-started_at"], name="llm_requests_mine"),
            models.Index(fields=["session_id", "id"], name="llm_requests_chat"),
            models.Index(fields=["turn_id"], name="llm_requests_turn"),
            models.Index(fields=["purpose", "-started_at"], name="llm_requests_purpose"),
            models.Index(fields=["request_hash"], name="llm_requests_same"),
        ]


class LLMPiece(models.Model):
    """One piece of what was asked, kept once: a system prompt, a set of tools,
    or one message, as the JSON its digest was taken of."""

    hash = models.CharField(max_length=64, primary_key=True)
    #: "system", "tools" or "message".
    kind = models.TextField()
    body = models.TextField()
    size = models.IntegerField(default=0)
    created_at = models.FloatField()

    class Meta:
        db_table = "llm_pieces"
