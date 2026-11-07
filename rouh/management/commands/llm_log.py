"""``python manage.py llm_log``: the log of every request made of a model.

A reader and nothing else (`rouh/llmlog.py` writes the log). With no
arguments, the newest requests, one line each: when, what for, which model,
how it ended, the tokens, the cost and how long it took. With a request's
number, that one whole: whose it was, what was asked, the reasoning the model
returned, the answer, its tool calls and what it cost.

    python manage.py llm_log                      the last 20
    python manage.py llm_log --chat chat-1a2b     one chat's, oldest first
    python manage.py llm_log --turn turn-3c4d     one turn's
    python manage.py llm_log --days 7 --totals    what a week cost, by purpose and model
    python manage.py llm_log 812                  one request, whole
    python manage.py llm_log 812 --request        and exactly what was sent, as JSON
"""
from __future__ import annotations

import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum

from rouh import costs, llmlog
from rouh.models import LLMRequest


def _when(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"


def _money(cost) -> str:
    return costs.money(None if cost is None else float(cost))


class Command(BaseCommand):
    help = "Read the log of requests made of a model: the newest, one chat's, or one whole."

    def add_arguments(self, parser):
        parser.add_argument("id", nargs="?", type=int, help="one request, whole")
        parser.add_argument("--request", action="store_true",
                            help="with an id: print exactly what was sent, as JSON")
        parser.add_argument("--chat", default="", help="only this chat's requests")
        parser.add_argument("--turn", default="", help="only this turn's requests")
        parser.add_argument("--purpose", default="", help="only requests made for this")
        parser.add_argument("--user", default="", help="only this account's requests")
        parser.add_argument("--days", type=float, default=0, help="only the last N days")
        parser.add_argument("-n", "--limit", type=int, default=20, help="how many lines")
        parser.add_argument("--totals", action="store_true",
                            help="add them up by purpose and model instead")

    def handle(self, *args, **options):
        if options["id"]:
            return self._one(options["id"], options["request"])
        rows = LLMRequest.objects.all()
        if options["chat"]:
            rows = rows.filter(session_id=options["chat"])
        if options["turn"]:
            rows = rows.filter(turn_id=options["turn"])
        if options["purpose"]:
            rows = rows.filter(purpose=options["purpose"])
        if options["user"]:
            rows = rows.filter(user_id=options["user"])
        if options["days"]:
            rows = rows.filter(started_at__gte=datetime.now().timestamp()
                               - options["days"] * 86400)
        if options["totals"]:
            return self._totals(rows)
        # A chat or a turn reads in the order it happened; the log as a whole
        # reads newest first.
        oldest_first = bool(options["chat"] or options["turn"])
        picked = list(rows.order_by("-id")[:max(options["limit"], 1)])
        if oldest_first:
            picked.reverse()
        for r in picked:
            took = f"{r.duration_ms / 1000:.1f}s" if r.duration_ms is not None else "..."
            tries = f" try {r.attempt}" if r.attempt > 1 else ""
            sent = r.input_tokens + r.cache_read_tokens + r.cache_write_tokens
            self.stdout.write(
                f"{r.id:>6}  {_when(r.started_at)}  {r.purpose or '?':<12} {r.model:<26} "
                f"{r.status:<7}{tries}  {sent:>8,} in {r.output_tokens:>7,} out  "
                f"{_money(r.cost_usd):>9}  {took:>6}"
                f"{'  ' + r.session_id if r.session_id else ''}")

    def _totals(self, rows):
        grouped = (rows.values("purpose", "model")
                   .annotate(n=Count("id"), cost=Sum("cost_usd"), inp=Sum("input_tokens"),
                             out=Sum("output_tokens"), read=Sum("cache_read_tokens"),
                             wrote=Sum("cache_write_tokens"))
                   .order_by("-cost"))
        whole = 0.0
        for g in grouped:
            cost = float(g["cost"] or 0)
            whole += cost
            self.stdout.write(
                f"{g['purpose'] or '?':<14} {g['model']:<26} {g['n']:>6} "
                f"{'request ' if g['n'] == 1 else 'requests'}  "
                f"{(g['inp'] or 0) + (g['read'] or 0) + (g['wrote'] or 0):>12,} in "
                f"{g['out'] or 0:>10,} out  {costs.money(cost):>10}")
        self.stdout.write(f"{'all of it':<41} {rows.count():>6} requests  "
                          f"{'':>28}{costs.money(whole):>10}")

    def _one(self, number: int, raw: bool):
        row = LLMRequest.objects.filter(pk=number).first()
        if row is None:
            raise CommandError(f"There is no request {number} in the log.")
        if raw:
            self.stdout.write(json.dumps(llmlog.request_of(row), indent=2, ensure_ascii=False))
            return
        line = self.stdout.write
        line(f"Request {row.id}, sent {_when(row.started_at)}, {row.status}"
             + (f" (HTTP {row.http_status})" if row.http_status else ""))
        line(f"  for       {row.purpose or '?'}"
             + (f", about {row.subject}" if row.subject else ""))
        line(f"  whose     user {row.user_id or '-'} in {row.org_id or '-'}"
             + (f", chat {row.session_id}" if row.session_id else "")
             + (f", {row.turn_id}" if row.turn_id else ""))
        line(f"  sent by   {row.caller or '-'}, try {row.attempt}")
        line(f"  model     {row.model}" + (f", answered by {row.served_model}"
                                           if row.served_model and row.served_model != row.model
                                           else "")
             + (f", effort {row.effort}" if row.effort else "")
             + (f", thinking {row.thinking}" if row.thinking else "")
             + (f", at most {row.max_tokens:,} tokens" if row.max_tokens else ""))
        line(f"  asked     {len(row.message_pieces or [])} messages, "
             f"{row.request_bytes:,} bytes")
        line(f"  tokens    {row.input_tokens:,} in, {row.cache_read_tokens:,} from the cache, "
             f"{row.cache_write_tokens:,} into it, {row.output_tokens:,} out"
             + (f", {row.web_searches} web searches" if row.web_searches else ""))
        line(f"  cost      {_money(row.cost_usd)}")
        took = "-" if row.duration_ms is None else row.duration_ms
        first = "-" if row.first_token_ms is None else row.first_token_ms
        line(f"  took      {took} ms, first word or thought at {first} ms")
        if row.stop_reason:
            line(f"  stopped   {row.stop_reason}")
        if row.error:
            line(f"  error     {row.error_type + ': ' if row.error_type else ''}{row.error}")
        blocks = (row.response or {}).get("content") or []
        thought = [b for b in blocks if b.get("type") == "thinking"]
        if row.reasoning:
            line("\nReasoning\n" + row.reasoning)
        elif thought:
            line("\nReasoning\n(the model thought and returned no words for it)")
        if row.text:
            line("\nAnswer\n" + row.text)
        for block in blocks:
            if block.get("type") in ("tool_use", "server_tool_use"):
                line(f"\nTool call: {block.get('name')} "
                     + json.dumps(block.get("input"), ensure_ascii=False)[:2000])
