"""What a turn cost, in tokens and in money.

Nobody could see what a turn cost, so nobody could tell an expensive habit
from a cheap one until the bill arrived. The numbers were there the whole
time: every response carries its own usage, and the loop was already adding
them up to throw them away at the end of the turn.

So this turns them into two things a person can act on. A price per turn, on
the line under the answer. And a running total, on the machine load readout
beside the CPU and the memory, because "how hard is this box working" and
"what is it spending" are the same question asked twice.

The prices
----------

Per million tokens, for the models this actually runs. Input and output are
the list prices. The two cache numbers are the ones that make caching worth
doing and are the reason the cache figure is on the screen at all: a read out
of the cache is a tenth of the price of the same tokens sent again, and
writing one costs a quarter more than sending them once. A turn with a high
cache figure is a cheap turn, and the screen should say so.

A model nobody has priced here is not a reason to show nothing: it is counted
in tokens, its cost is left out, and `priced` says so, which is how a person
can tell "this cost nothing" from "nobody knows what this cost".

Each request of a turn
----------------------

A turn with tools is several requests, one per round of tools, and every one
sends the whole conversation again. What the prompt cache saves only shows
request by request: the first of a turn writes the conversation to the cache,
and each after it should read nearly all of it back (`rouh/promptcache.py`).
So the four numbers of each request are kept beside the turn's totals, in
`calls`, in the order they were made: on the line under the answer, in the
spend table, and in the log.
"""
from __future__ import annotations

#: Dollars per million tokens: (input, output). From Anthropic's list prices.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # OpenAI's list price for GPT-6 Luna (developers.openai.com, 26 September
    # 2026). A cached token is a tenth of an input token and writing one is a
    # quarter more, the same two ratios as Anthropic's, so the two constants
    # below hold for it too. Past 272K tokens of prompt it costs twice as much
    # to send, which no spoken turn reaches: the window is trimmed at 120K
    # (`Config.context_budget_tokens`).
    "gpt-6-luna": (0.10, 0.50),
    # The rest of OpenAI's models on the list (`config.OPENAI_CHOICES`), at
    # their list prices for prompts under 272K tokens (developers.openai.com,
    # 5 October 2026). Each reads its cache at a tenth but GPT-6.1 Sol.
    "gpt-6-astra": (10.00, 50.00),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    # What Synapse's lab asks of OpenAI besides Luna (`rouh/synapse/ai.py`),
    # at OpenAI's list prices: the model whose log probabilities stand in for
    # a decision model while the Decisions API is not open to this key, and
    # the two embedding models, which have no output to pay for.
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-3-small": (0.02, 0.0),
    # Voyage AI's voyage-4, which Synapse's vectors are made with since 3
    # October 2026 (spec D37): $0.06 per million tokens at list price, the
    # first 200 million free, which this does not count.
    "voyage-4": (0.06, 0.0),
    # Google's Gemini models (`config.GOOGLE_CHOICES`), at the Gemini API's paid-tier list
    # prices for prompts up to 200K tokens (ai.google.dev/gemini-api/docs/pricing, last
    # updated 22 October 2026), and xAI's Grok models below 200K tokens (docs.x.ai/docs/models,
    # read 24 October 2026). Each one's cached price is in `CACHE_READS`.
    "gemini-4-argon": (4.00, 20.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "grok-4.7": (2.00, 6.00),
    "grok-4.6": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
}

#: OpenAI's Decisions API (`POST /v1/decisions`, `rouh/llm.py` `decide`), per million
#: tokens: (uncached input, cached input, cache write). Its guide, read on 23 October 2026
#: (developers.openai.com/api/docs/guides/decisions, "Pricing"): "With gpt-6-luna,
#: uncached input costs $0.10 per 1M tokens. Prompt cache hits receive discounted input
#: pricing; cache writes are charged. Cache-read and cache-write rates match the standard
#: gpt-6-luna prompt caching rates. Output tokens are not charged." The pricing page has
#: those at $0.01 a cached token and $0.125 a 30-minute write (the only lifetime the
#: Decisions API takes) for prompts under 272K tokens. So there is no output price here at
#: all: until 23 October 2026 a decision was priced as a Responses call on `PRICES`, and
#: any output tokens it reported were charged at Luna's $0.50. GPT-6 Luna is the only
#: model it takes (`config.DECISIONS_MODELS`).
DECISION_PRICES = {
    "gpt-6-luna": (0.10, 0.01, 0.125),
}

#: What a cache read costs against the input price, and what writing one does.
#: These two are why the cache figure is worth putting on the screen.
CACHE_READ = 0.1
CACHE_WRITE = 1.25

#: What writing one costs when it is to be kept an hour rather than five
#: minutes: twice the input price. The system prompt is written that way
#: (`promptcache.LONG`), so a turn that writes it is dearer than the constant
#: above would say, and one that reads it an hour later far cheaper.
CACHE_WRITE_HOUR = 2.0

#: The models that read out of the cache for less than the tenth above. Opus
#: 5.5 charges $0.20 against an input price of $4.00, which is half what every
#: model before it charged, so a cached turn on it is cheaper than the
#: constant would say. Keyed like `PRICES` and matched the same way.
CACHE_READS = {
    "claude-opus-5-5": 0.05,
    # $0.25 against $10.00: a quarter of what the tenth above would charge.
    "claude-fable-5-1": 0.025,
    # $0.10 against $2.00.
    "gpt-6.1-sol": 0.05,
    # OpenAI's GPT-4.1 family reads cached input at a quarter of the price.
    "gpt-4.1-mini": 0.25,
    "gpt-4.1-nano": 0.25,
    # $0.20 against $4.00, and a tenth for the two Flash models (the same pages as above).
    "gemini-4-argon": 0.05,
    # Grok: $0.50 against $2.00, and $0.20 against $1.25.
    "grok-4.7": 0.25,
    "grok-4.6": 0.25,
    "grok-4.3": 0.16,
}

#: One web search, in dollars: $10 a thousand, on top of the tokens its
#: results add. A web fetch costs only the tokens of what it read.
WEB_SEARCH = 0.01

#: Per million tokens, so every figure below is in dollars.
PER = 1_000_000

#: The models that draw pictures (`rouh/imaging_openai.py`), per million
#: tokens: (text in, picture in, picture out). OpenAI's list prices for the two
#: GPT Image 2.5 models (developers.openai.com, 26 September 2026). A picture
#: handed in to be changed is counted as picture tokens in; what is drawn is
#: picture tokens out, and it is nearly the whole of the bill.
IMAGE_PRICES = {
    "gpt-image-2.5-flare": (5.00, 8.00, 30.00),
    "gpt-image-2.5-sunburst": (5.00, 8.00, 30.00),
}


def priced_as(model: str) -> str | None:
    """Which name in `PRICES` a model id is priced as, or nothing.

    Matched on the longest prefix, because a dated model id is the same model
    at the same price: `claude-opus-5-20260401` is `claude-opus-5`. Longest
    and not first, because `claude-opus-5-5` starts with `claude-opus-5` and
    is a different model at a different price.
    """
    name = str(model or "").strip()
    if not name:
        return None
    if name in PRICES:
        return name
    best = ""
    for known in PRICES:
        if name.startswith(known) and len(known) > len(best):
            best = known
    return best or None


def price_of(model: str) -> tuple[float, float] | None:
    """The two prices for a model, or nothing if it is not priced here."""
    name = priced_as(model)
    return PRICES[name] if name else None


def cache_read_of(model: str) -> float:
    """What a cached input token costs this model, against its input price."""
    return CACHE_READS.get(priced_as(model) or "", CACHE_READ)


def tokens_of(usage) -> dict:
    """The four numbers off a usage, whatever shape it arrived in, and how
    many of the cache writes were to be kept an hour (`cache_write_1h`, part
    of `cache_write` and not beside it)."""
    def number(*names, of=None) -> int:
        of = usage if of is None else of
        for name in names:
            value = getattr(of, name, None)
            if value is None and isinstance(of, dict):
                value = of.get(name)
            if value is not None:
                return int(value or 0)
        return 0

    # The API says how the writes split between the two lifetimes in a
    # `cache_creation` of its own; a total from here says it as a number.
    split = getattr(usage, "cache_creation", None)
    if split is None and isinstance(usage, dict):
        split = usage.get("cache_creation")
    hour = (number("ephemeral_1h_input_tokens", of=split) if split is not None
            else number("cache_write_1h"))
    return {
        "input": number("input_tokens", "input"),
        "output": number("output_tokens", "output"),
        "cache_read": number("cache_read_input_tokens", "cache_read"),
        "cache_write": number("cache_creation_input_tokens", "cache_write"),
        "cache_write_1h": hour,
    }


def cost_of(usage, model: str) -> float | None:
    """What those tokens cost, in dollars, or nothing for an unpriced model."""
    price = price_of(model)
    if price is None:
        return None
    took = tokens_of(usage)
    per_in, per_out = price
    hour = min(took["cache_write_1h"], took["cache_write"])
    return (
        took["input"] * per_in
        + took["output"] * per_out
        + took["cache_read"] * per_in * cache_read_of(model)
        + (took["cache_write"] - hour) * per_in * CACHE_WRITE
        + hour * per_in * CACHE_WRITE_HOUR
    ) / PER


def decision_cost(usage, model: str) -> float | None:
    """What one call of OpenAI's Decisions API cost: its input, read from the cache or
    written to it or neither, and never its output, which is not charged. `usage` is in
    the names `tokens_of` reads, with `input` the uncached tokens alone (`llm.decision_usage`
    makes it from what the API sends). Nothing for a model the Decisions API is not priced
    for here."""
    name = str(model or "").strip()
    price = DECISION_PRICES.get(name) or next(
        (p for known, p in DECISION_PRICES.items() if name.startswith(known + "-")), None)
    if price is None:
        return None
    took = tokens_of(usage)
    per_in, per_read, per_write = price
    return (took["input"] * per_in + took["cache_read"] * per_read
            + took["cache_write"] * per_write) / PER


def request_cost(usage, model: str) -> float | None:
    """What one request cost, from its usage exactly as the API reported it.

    The tokens as `cost_of` prices them, and every web search the request
    made on top, which a turn's four added-up numbers leave out. Nothing for a
    model nobody has priced here.
    """
    cost = cost_of(usage, model)
    if cost is None:
        return None
    tools = getattr(usage, "server_tool_use", None)
    if tools is None and isinstance(usage, dict):
        tools = usage.get("server_tool_use")
    searches = getattr(tools, "web_search_requests", None)
    if searches is None and isinstance(tools, dict):
        searches = tools.get("web_search_requests")
    return cost + int(searches or 0) * WEB_SEARCH


def image_cost(usage, model: str) -> float | None:
    """What drawing one picture cost, from the usage OpenAI sent with it.

    Nothing for a model not priced here, or a usage that says nothing, which is
    "nobody knows" rather than "free".
    """
    name = str(model or "")
    price = IMAGE_PRICES.get(name) or next(
        (p for known, p in IMAGE_PRICES.items() if name.startswith(known)), None)
    if price is None or not isinstance(usage, dict) or not usage:
        return None

    def number(of, key) -> int:
        try:
            return int((of or {}).get(key) or 0)
        except (TypeError, ValueError, AttributeError):
            return 0

    details = usage.get("input_tokens_details") if isinstance(
        usage.get("input_tokens_details"), dict) else {}
    text_in = number(details, "text_tokens")
    image_in = number(details, "image_tokens")
    if not details:
        text_in = number(usage, "input_tokens")
    per_text, per_image, per_out = price
    return (text_in * per_text + image_in * per_image
            + number(usage, "output_tokens") * per_out) / PER


def summarise(usage, model: str) -> dict:
    """The whole of what a turn is worth saying about itself."""
    took = tokens_of(usage)
    read = took["cache_read"]
    sent = took["input"] + read + took["cache_write"]
    out = dict(took)
    out["model"] = model
    out["sent"] = sent
    # Each request of the turn, the four numbers each, in order.
    calls = usage.get("calls") if isinstance(usage, dict) else None
    out["calls"] = [tokens_of(one) for one in calls or []]
    # How much of what went in came out of the cache. A high number is a cheap
    # turn, which is the only reason this is worth a person's attention.
    out["cached"] = round(read / sent, 3) if sent else 0.0
    cost = cost_of(usage, model)
    out["cost"] = cost
    out["priced"] = cost is not None
    # The money as a person reads it, worked out here rather than in the page:
    # the rule about cents is a rule about money and belongs with the prices.
    out["money"] = money(cost)
    return out


def money(cost) -> str:
    """A cost as a person would read it.

    Under a cent it is said in cents, because "$0.004" reads as nothing and a
    turn that costs four tenths of a cent is the normal case.
    """
    if cost is None:
        return "not priced"
    if cost <= 0:
        return "$0.00"
    if cost < 0.01:
        return f"{cost * 100:.2f}c"
    if cost < 1:
        return f"${cost:.3f}"
    return f"${cost:,.2f}"


def said(summary: dict) -> str:
    """One line, for the log and for anything that has to say it out loud."""
    calls = len(summary.get("calls") or [])
    over = f" over {calls} requests" if calls > 1 else ""
    return (f"{summary['sent']:,} in / {summary['output']:,} out{over}, "
            f"{int(summary['cached'] * 100)}% cached, {money(summary['cost'])}")


def call_said(took: dict) -> str:
    """One request of a turn, in a line: what it sent, and how much of that was
    read out of the cache, how much written to it and how much sent at the full
    price."""
    sent = took["input"] + took["cache_read"] + took["cache_write"]
    return (f"{sent:,} in ({took['cache_read']:,} read from the cache, "
            f"{took['cache_write']:,} written to it, {took['input']:,} uncached) / "
            f"{took['output']:,} out")
