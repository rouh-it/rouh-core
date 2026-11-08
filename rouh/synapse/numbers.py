"""Every number Synapse works by, each a value and never a constant (D5).

The spec's section 16 lists every starting number with the measurement that
moves it; each is here with its decision, so the debugger can show it, change
it per dataset and put it back. `starting` is true for the spec's own starting
values; the few that are this lab's own choices (which OpenAI model, for
instance) say so in their note.

A dataset keeps only what differs from here (`dataset.tuning`), and a query can
be run with more changes on top without keeping them (Tune's side-by-side).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Number:
    key: str
    group: str
    label: str
    value: object
    ref: str
    kind: str = "float"            # float | int | bool | choice | text
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    moves: str = ""                # what measurement would move it (section 16)
    note: str = ""
    choices: tuple = field(default_factory=tuple)
    starting: bool = True          # a spec starting value, not this lab's choice


DECISION_BACKENDS = ("openai_decisions", "generative", "off")
DECISION_PURPOSES = ("tier", "sensitivity", "link_screen", "short_links",
                     "contradiction_screen", "seed_rerank", "frontier", "checkpoint_shadow")

N = Number
NUMBERS: tuple[Number, ...] = (
    # --- X-rays (section 3) ---------------------------------------------------------
    N("xray_min_words", "X-rays", "No X-ray under this many words", 0, "D8", "int", 0, 2000, 10,
      "Short raw items crowding packs; X-ray cost per useful claim",
      "0 since the decision of 3 October 2026 (D8 revised): every item but a person or a topic gets an "
      "X-ray, and with it the model's title, tier, sensitivity and area in the one call (D82). Above 0, an "
      "item under it gets no X-ray: code makes its gist from the first sentence and keeps its title."),
    N("claims_per_words", "X-rays", "One claim per this many words", 100, "D8", "int", 20, 1000, 10,
      "Facts of long items missed"),
    N("claims_min", "X-rays", "Claims per item, at least", 2, "D8", "int", 1, 12, 1, "Facts of long items missed"),
    N("claims_max", "X-rays", "Claims per item, at most", 12, "D8", "int", 2, 40, 1, "Facts of long items missed"),
    N("long_doc_words", "X-rays", "A long document, X-rayed per section, from", 4000, "D8", "int", 500, 50000, 500,
      "Facts of long items missed"),
    N("doc_claims_max", "X-rays", "Document-level claims of a long document", 7, "D8", "int", 2, 20, 1,
      "Facts of long items missed"),
    N("claim_words", "X-rays", "Gist and claim length, words", 30, "D7", "int", 10, 80, 1,
      "Citation failures from long claims"),
    N("quote_reject_share", "X-rays", "Reject the X-ray when this share of quotes fail", 0.5, "D10", "float", 0.1, 1.0, 0.05,
      "Rate of good claims dropped", "Over this share failing, the item falls back to raw."),

    # --- the map (section 4) ------------------------------------------------------------
    N("map_on", "Map", "Load the map into every question", True, "D85", "bool",
      moves="Evaluation with the map on and off: recall, citation, answer, searches skipped and time",
      note="Off, a question is asked with no map: the model writes the search query and answers without the "
           "areas, the active work and ‹owner›'s words, and never skips a search for it. For measuring "
           "whether the map earns its place (D85, 5 October 2026); the map is still built either way.",
      starting=False),
    N("map_skip_search", "Map", "Skip the search when the map alone answers", False, "D85", "bool",
      moves="Evaluation with it on and off: searches skipped, and whether the skipped questions were answered right",
      note="On, the model that writes the search query may say the map alone answers the question, and then "
           "nothing is searched (the answer step can still search). Off since 5 October 2026: on Northwind it "
           "skipped 3 searches in 24 questions and all 3 answers were wrong. Needs the map on.", starting=False),
    N("map_words", "Map", "Map size, words (target)", 600, "D15", "int", 100, 3000, 50,
      "Failures from missing lines against unused lines"),
    N("map_token_cap", "Map", "Map hard cap, tokens", 1200, "D15", "int", 200, 5000, 50, "Same"),
    N("map_areas", "Map", "Area lines, at most", 25, "D15", "int", 1, 100, 1, "Same"),
    N("map_active", "Map", "Active-now lines, at most", 10, "D15", "int", 1, 50, 1, "Same"),
    N("map_terms", "Map", "‹owner›'s-words lines, at most", 40, "D15", "int", 0, 200, 1, "Same"),
    N("map_line_words", "Map", "Words per map line, at most", 15, "D15", "int", 5, 60, 1, "Same"),
    N("map_rebuild_minutes", "Map", "Rebuild the map at most every, minutes", 10, "D17", "int", 0, 1440, 1,
      "Prompt cache hit rate"),
    N("active_days", "Map", "Active window, days", 7, "D16", "int", 1, 90, 1,
      "Questions about last week's work missing"),
    N("term_min_items", "Map", "A word joins the map after this many items", 3, "D16", "int", 1, 20, 1,
      "Terms ‹owner› uses that search misses"),
    N("area_min_items", "Map", "An area the model proposes becomes real after this many items", 3, "D16", "int",
      1, 20, 1, "Items left under General that belong together, against areas of one or two items each",
      "Until then the proposal waits on each item and the item stays under General. This lab's own "
      "choice, after term_min_items.", starting=False),
    N("area_not_media", "Map", "Never an area: words that name how an item came or what kind it is",
      "email, emails, e-mail, mail, mails, gmail, inbox, inboxes, outbox, message, messages, messaging, sms, "
      "chat, chats, conversation, conversations, thread, threads, telegram, whatsapp, slack, letter, letters, "
      "correspondence, communication, communications, notification, notifications, task, tasks, project, projects, "
      "file, files, document, documents, doc, docs, attachment, attachments, pdf, pdfs, spreadsheet, spreadsheets, "
      "upload, uploads, calendar, calendars, event, events, note, notes, page, pages, card, cards, contact, "
      "contacts, item, items, record, records, misc, miscellaneous, general, other, various, stuff, incoming, "
      "outgoing, inbound, outbound, sent, received, and, my, the, of", "D83", "text",
      moves="An area the model proposed that still names a medium or a kind, or a real area this list wrongly "
            "refused",
      note="Starting value, 5 October 2026. Checked by code on every area the model names: a name made only of "
           "these words (Email, Mail, Projects, Inbox messages) is refused and the item stays under General; these "
           "words at either end are taken off (Work email is Work, Acme emails is Acme). An area the "
           "owner sets is never checked. Comma separated, case does not matter.", starting=False),

    # --- records (section 5) -------------------------------------------------------------
    N("passage_tokens", "Records", "Passage size, tokens", 400, "D24", "int", 100, 2000, 50,
      "Recall on mid-document answers"),
    N("passage_overlap", "Records", "Passage overlap, tokens", 50, "D24", "int", 0, 400, 10,
      "Recall on mid-document answers"),
    N("version_days", "Records", "Old X-rays kept, days", 90, "D27", "int", 1, 3650, 1, "Whether anybody looks"),

    # --- links (section 6) --------------------------------------------------------------
    N("link_candidates", "Links", "Candidates shown to the helper model", 20, "D31", "int", 5, 60, 1,
      "Missed links that were in the top 40"),
    N("link_structure_max", "Links", "Candidates from structure (thread, files, people), at most", 10, "D31",
      "int", 0, 40, 1, "Missed links that were in the top 40",
      "Taken first, before any search, each by an index lookup. This lab's own choice.", starting=False),
    N("link_rare_terms", "Links", "Candidates by words: the item's rarest words searched", 8, "D31", "int",
      1, 30, 1, "Missed links that were in the top 40",
      "Never the item's whole text: only its rarest words, by how many passages hold each.", starting=False),
    N("link_words_cap", "Links", "Candidates by words: passages ranked, at most", 500, "D31", "int", 50, 20000, 50,
      "Missed links that were in the top 40, against link candidate time at 100,000 items",
      "The words list for link candidates ranks at most this many passages holding the rarest words; "
      "a question's search has its own (Search > words_cap).", starting=False),
    N("judgement_links_max", "Links", "Judgement links per item, at most", 8, "D31", "int", 1, 30, 1,
      "Wrong links per 10"),
    N("strength_weak", "Links", "Strength: weak", 0.3, "D32", "float", 0.0, 1.0, 0.05, "Where learning moves links"),
    N("strength_medium", "Links", "Strength: medium", 0.6, "D32", "float", 0.0, 1.0, 0.05, "Where learning moves links"),
    N("strength_strong", "Links", "Strength: strong", 0.9, "D32", "float", 0.0, 1.0, 0.05, "Where learning moves links"),
    N("s_from", "Links", "Code link strength: from", 0.6, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_to", "Links", "Code link strength: to", 0.5, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_cc", "Links", "Code link strength: cc", 0.3, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_in_thread", "Links", "Code link strength: in_thread", 0.9, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_reply_to", "Links", "Code link strength: reply_to", 0.9, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_in", "Links", "Code link strength: in (task or project)", 0.8, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_same_as", "Links", "Code link strength: same_as", 1.0, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_attached", "Links", "Code link strength: attached", 0.8, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_rule_for", "Links", "Code link strength: rule_for", 1.0, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_built_from", "Links", "Code link strength: built_from", 0.7, "D29", "float", 0, 1, 0.05, "Learning"),
    N("s_recorded", "Links", "Code link strength: recorded (a meeting to its calendar event)", 0.9, "D29", "float", 0, 1,
      0.05, "Learning"),
    N("s_attended", "Links", "Code link strength: attended (a meeting to who took part)", 0.6, "D29", "float", 0, 1, 0.05,
      "Learning"),
    N("s_invited", "Links", "Code link strength: invited (a meeting to who was invited and did not come)", 0.3, "D29",
      "float", 0, 1, 0.05, "Learning"),
    N("s_spoke", "Links", "Code link strength: spoke (a meeting to a confirmed speaker)", 0.7, "D29", "float", 0, 1, 0.05,
      "Learning"),
    N("topic_bar_items", "Links", "A new topic needs this many items proposing it", 2, "D34", "int", 1, 10, 1,
      "One-item topics over 30%"),
    N("topic_bar_days", "Links", "... within this many days", 30, "D34", "int", 1, 365, 1, "One-item topics over 30%"),
    N("topic_merge_cosine", "Links", "Merge topics above this cosine", 0.92, "D34", "float", 0.5, 1.0, 0.01,
      "Duplicate topics found by ‹owner›"),
    N("topic_match_cosine", "Links", "A proposed topic name counts as an existing topic or proposal above this cosine",
      0.85, "D34", "float", 0.5, 1.0, 0.01, "Duplicate topics found by ‹owner›",
      note="Revised D34, 4 October 2026: names that mean the same are matched, not only names spelt the same. "
           "On voyage-4, synonyms (Hiring, Recruiting) measured 0.88 to 0.94 and distinct subjects up to 0.83 "
           "(Marketing, Sales), so 0.85 sits between them."),

    # --- search (section 7) ----------------------------------------------------------------
    # --- every message in Rouh's chats (D84, 5 October 2026) --------------------------------
    N("message_seeds", "Every message", "Look up seeds on every message in Rouh's chats", True, "D84", "bool",
      moves="How often a strong seed comes in, and whether it bore on the message",
      note="On Synapse Master only: every message the person sends in a chat that is not Synapse's own is looked "
           "up by words and meaning, fused by rank, with no walk and no model call, beside the turn. Only seeds "
           "over the cosine below come into the turn's context; synapse_query stays for the full walk.",
      starting=False),
    N("message_seed_tasks", "Every message", "A task the message names by number comes in at once", True, "D84",
      "bool", moves="Whether a message that names a task by number has the task in its turn's first request",
      note="On, a message that names a task or a step by its number, in digits or in words (\"what's up with 58\", "
           "\"where are we with seventy\", \"twenty nine dash three\"), has that task's own line in the turn, "
           "found by its number in code with no vector and so ready before the turn's first request even when "
           "the rest of the lookup is not, whatever its cosine. Dates, amounts, times and counts are never read "
           "as task numbers (the same reading as Search's task_numbers). Attempt 22, 7 October 2026.",
      starting=False),
    N("message_seed_cosine", "Every message", "A seed comes in at this cosine or more", 0.6, "D84", "float",
      0.0, 1.0, 0.01, "Seeds a judge called useful against seeds it called noise, on real past messages",
      "The cosine between the message's vector (voyage-4) and the item's best passage. Measured 5 October 2026 "
      "on 200 real messages against a copy of Master, Claude Opus 5 judging each seed: at 0.60, 79 "
      "messages of 200 let something in, 184 seeds, 66% useful, 10% noise, and 66 messages got a useful one; "
      "at 0.50, 143 messages and 14% noise; at 0.65, 48 messages and 5% noise.", starting=False),
    N("message_seeds_max", "Every message", "Seeds brought in on one message, at most", 3, "D84", "int", 1, 10, 1,
      "Tokens per turn against seeds the answer used", starting=False),
    N("message_seed_tokens", "Every message", "Their lines, tokens at most", 600, "D84", "int", 100, 4000, 50,
      "Tokens per turn", starting=False),
    N("message_seed_depth", "Every message", "Each list's top, fused, for a message", 20, "D84", "int", 5, 100, 5,
      "Time of the lookup against strong seeds missed", starting=False),
    N("message_seed_wait_ms", "Every message", "The turn waits for the lookup at most, ms", 100, "D84", "int",
      0, 2000, 10, "Added time to a turn, median and 95th percentile",
      "The lookup starts when the message comes and runs beside the turn's own work; when that work is done "
      "the turn waits at most this long more and goes on without the seeds if they are not back, and they come "
      "in with the turn's next request instead, after its tools, if it makes one. 100 ms is the search's 95th "
      "percentile at 1,000,000 items (card 1125), ‹owner›'s bar. Measured 5 October 2026: the whole lookup is 232 "
      "ms median and 329 ms at the 95th percentile, 202 and 280 of it Voyage's vector, so at 100 ms the seeds "
      "almost never reach the first request; at 250 ms 78% would, at 350 ms 97%.", starting=False),
    N("recall_wait_ms", "Every message", "Automatic recall: the first reply waits for it at most, ms", 10000,
      "D84", "int", 0, 30000, 250, "Look-ups back in time against the wait before the first word",
      "Automatic recall (`autorecall.py`) looks up what ‹owner›'s message names the moment it comes; the turn's "
      "first request waits at most this long from then. Look-ups still running carry on, up to 30 seconds, and "
      "what they find goes into the turn's next request or the next message in the chat, never dropped. 2,500 "
      "until 10 October 2026, when the owner said: \"I definitely don't want answers to be limited to 2.5 seconds\"; "
      "6,000 until 14 October 2026, when he said: \"raise the 6s total of the operation to 10 seconds\". "
      "Each message's timeline in the chat draws this wait and the old 2.5 s beside its look-ups.",
      starting=False),
    N("rrf_k", "Search", "Fusion constant k", 60, "D36", "int", 1, 500, 1, "Recall"),
    N("list_depth", "Search", "Each list's top, fused", 60, "D36", "int", 5, 500, 5, "Recall"),
    N("seeds", "Search", "Seeds for the walk", 20, "D36", "int", 1, 100, 1, "Recall against latency"),
    N("context_first", "Search", "Start from the item a question is asked about", True, "D36", "bool",
      moves="The benchmark's questions asked about an item, with it on and off: recall",
      note="On, a live question asked about an item (the mail being handled, the item open in the Synapse chat) "
           "has that item as the walk's first seed and its title added to its search query, when the asker may "
           "read it. Off, a live recall only boosts items of the same task or sender, as until 29 October 2026 "
           "(attempt 44); a background recall has its own fixed order for it either way (D56).", starting=False),
    N("task_numbers", "Search", "Search for a task the question names by number", True, "D36", "bool",
      moves="The benchmark's Task status questions, with it on and off: recall and answer correctness",
      note="On, a question that names a task or a step by its number, in digits or in words (\"what's going on "
           "with 58\", \"where are we with seventy\", \"twenty nine dash three\") has that task's number and "
           "title, found by code, added to its search query, so the task's files, steps, cards and chats are "
           "found. A date, an amount, a time or a count is never read as a task number. Attempt 21, 6 October 2026.",
      starting=False),
    N("plain_when_named", "Search", "Synapse's own answer searches the question as asked when it names someone",
      True, "D50", "bool",
      moves="The benchmark's judged pass, with it on and off: recall and answer correctness",
      note="When Synapse answers itself (the Synapse chat, the lab, the judged benchmark), a model first rewrites "
           "the question into a search query. On, a question that names a task by number or a person by a "
           "capitalised name the dataset knows (never the owner or the assistant itself) is searched as asked, "
           "and only the others are searched by the rewrite: on 31 October 2026 the rewrite found 1.0 instead of "
           "0 for 'which of my calendars has Rouh been given' and lost half of 'Who is Sam?' and 'what's going "
           "on with 58'. A model calling synapse_query from a chat writes its own query and is not touched. "
           "Attempt 46.",
      starting=False),
    N("person_mails", "Search", "Mails of a person the question names, as seeds", 3, "D36", "int", 0, 50, 1,
      "The benchmark's People and Across mails questions, with it at 0 and on: recall and answer correctness",
      "When a person the search found is named in the question (\"Who is Sam?\", \"What has Rouh emailed "
      "Jordan about?\"), this many of the mails they sent, were sent or were copied on, closest to the question "
      "first, are seeds of the walk besides the search's own; 0 turns it off. Only the persons matching the most "
      "of the question's words count, never the owner and never a mailbox Master reads. Measured on 15 October "
      "2026 (attempt 30): 3 found the same gold mails as 5 and lost nothing, while 5 and 8 pushed task files out "
      "of 'is Sam around next week to send Jordan the DPA?', and so did fusing them into the search's own list, "
      "where they took seed places from it.",
      starting=False),
    N("person_named_mails", "Search", "Mails that name a person the question names, as seeds", 3, "D36", "int", 0,
      50, 1, "The benchmark's People and Across mails questions, with it at 0 and on: recall and answer correctness",
      "When a person the search found is named in the question, this many of the mails whose own text or subject "
      "names them (every word of the name the question used, as whole words), closest to the question first, are "
      "seeds of the walk too, besides their own mails above; 0 turns it off. An introduction or a hand-over about "
      "somebody is written by others, to others, so no link ties it to them: 'Who is Ivan Varbanov?' missed "
      "both 'Re: Intro' mails about him, though only three mails in the dataset held his surname. Attempt 37, "
      "22 October 2026.",
      starting=False),
    N("task_items", "Search", "Items of a task the question names, as seeds", 3, "D36", "int", 0, 50, 1,
      "The benchmark's Task status questions, with it at 0 and on: recall and answer correctness",
      "When a question names a task by its number (\"what's going on with 58\"), this many of the items about "
      "it or attached to it (its chats, cards and files) that the search did not already make seeds, closest to "
      "the question first, are seeds of the walk too; 0 turns it off. The search finds the task, but its own chat and answer card are "
      "a link further, and the walk ran out of room with them still queued: 'what's going on with 58' lost the "
      "chat of the decision and the card that answered it. Attempt 51, 8 November 2026.",
      starting=False),
    N("words_cap", "Search", "Words list: candidate passages, at most", 2000, "D36", "int", 100, 50000, 100,
      "Recall against time to pack, at 10,000 and 100,000 items",
      "The question's rarest words draw the candidates from the index, as many words as fit this many "
      "passages between them; only those are ranked. When even the rarest word is in more passages than "
      "this, its most recent ones are taken. This lab's own choice, 4 October 2026.", starting=False),
    N("words_backend", "Search", "Words list: how passages are found and ranked", "pg_search", "D36", "choice",
      choices=("capped", "bm25", "pg_search"), moves="Ranking cases and time, synapse_bench (card 1125 change 1)",
      note="pg_search since 4 October 2026, once Rouh's PostgreSQL loaded it: ParadeDB's BM25 index ranked 97.8% "
           "of synapse_bench's cases right at 100,000 items against 93.3% for bm25, and faster; where pg_search "
           "is not loaded it ranks with bm25 and says so. bm25: BM25 in PostgreSQL, with passages holding most of "
           "the question's commoner words together found before the most recent ones; at 1,000,000 fictional "
           "items it ranked 77.8% of synapse_bench's cases right against 51.1% for capped, for 19 ms more at "
           "the 95th percentile. capped: the rarest words' passages, scored by rarity and ts_rank, as before.",
      starting=False),
    N("hnsw_ef_search", "Search", "Meaning list: neighbours the vector index keeps while it searches", 100, "D36",
      "int", 10, 1000, 10, "Meaning-only cases found, against time, synapse_bench at 1,000,000",
      "pgvector's ef_search, 40 by default. At 1,000,000 fictional items, meaning-only questions found their item "
      "40% of the time at 40, 65% at 100 for about 4 ms more at the 95th percentile, and no more at 200 for 14 ms "
      "more (4 October 2026); the rest needs a better-connected graph.", starting=False),
    N("bm25_k1", "Search", "BM25: how fast repeating a word stops counting (k1)", 1.2, "D36", "float", 0.1, 3.0, 0.1,
      "Ranking cases", "Used by the bm25 words list.", starting=False),
    N("bm25_b", "Search", "BM25: how much a long passage is discounted (b)", 0.75, "D36", "float", 0.0, 1.0, 0.05,
      "Ranking cases", "Used by the bm25 words list.", starting=False),
    N("words_terms", "Search", "Words list: question words that draw candidates, at most", 16, "D36", "int",
      1, 64, 1, "Recall against time to pack", "Every question word still counts in the ranking.", starting=False),
    N("recent_first", "Search", "Search recent items first", False, "D36", "bool",
      moves="Recall on the evaluation questions, with and without",
      note="Both lists over the last days first, and older items only when that finds too little, merged by "
           "score. Off because contradictions and old decisions are often old: on only if the evaluation "
           "says recall holds.", starting=False),
    N("recent_days", "Search", "Recent first: days counted as recent", 90, "D36", "int", 1, 3650, 1,
      "Recall with recent first on", starting=False),
    N("recent_enough", "Search", "Recent first: older items too when it finds fewer than", 20, "D36", "int",
      1, 500, 1, "Recall with recent first on", starting=False),
    N("recent_cosine", "Search", "Recent first: older items too when its best cosine is under", 0.5, "D36",
      "float", -1.0, 1.0, 0.01, "Recall with recent first on", starting=False),
    N("diversity", "Search", "Seed diversity: weight on relevance", 1.0, "D47", "float", 0.0, 1.0, 0.05,
      "Ambiguous questions answered narrowly",
      "Maximal marginal relevance; 1.0 means no diversity: the seeds are the search's best, in its order, and "
      "no vectors are read for them. 0.7 until 20 October 2026 (attempt 35): on Master every item is fairly like "
      "every other (median likeness between candidates 0.45), so the step mostly pushed out the items on the "
      "question's own subject, at search ranks 9 to 17, for unrelated ones further down. Free passes on the "
      "frozen copy found 85.0% of the gold at 0.7, 87.3% at 0.9 and 88.5% at 0.95 and 1.0.", starting=False),
    N("embed_model", "Search", "Embedding model", "voyage-4", "D37", "choice",
      choices=("voyage-4", "text-embedding-3-large", "text-embedding-3-small"), moves="Memory pressure; Q4",
      note="Voyage's voyage-4 as the spec says, at 1,024 dimensions, stored as half precision. "
           "A dataset's vectors are all one model's, and search uses that model: changing this only "
           "says where Vectors > Move goes, which re-embeds every passage beside the old vectors, "
           "checks them, and only then switches search over."),

    # --- reranking (D39, D70) ----------------------------------------------------------------
    N("seed_rerank", "Reranking", "Rerank the seed candidates with a decision model", False, "D70", "bool",
      moves="Recall at budget, with and without", note="Off until it passes D79's gate."),
    N("rerank_candidates", "Reranking", "Candidates scored for the rerank", 100, "D70", "int", 10, 300, 10,
      "Recall against time to pack"),
    N("rerank_per_call", "Reranking", "Candidates per decision call", 30, "D70", "int", 5, 60, 1,
      "Recall against time to pack"),
    N("rerank_shape", "Reranking", "Rerank question shape", "noul", "D70", "choice", choices=("noul", "choice"),
      moves="D79 compares the two"),

    # --- traversal (section 8) ----------------------------------------------------------------
    N("hop_decay", "Traversal", "Hop decay d", 0.5, "D41", "float", 0.05, 1.0, 0.05, "Recall at budget, latency"),
    N("hub_constant", "Traversal", "Hub constant (links before the mark-down)", 50, "D41", "int", 1, 5000, 1,
      "Hubs crowding or vanishing", "H = sqrt(constant / links) when an item has more links than this."),
    N("half_life_days", "Traversal", "Recency half-life, days", 180, "D41", "int", 1, 3650, 1,
      "Old answers missed or stale ones preferred", "Mail and chat turns only."),
    N("recency_floor", "Traversal", "Recency floor", 0.3, "D41", "float", 0.0, 1.0, 0.05,
      "Old answers missed or stale ones preferred"),
    N("prior_junk", "Traversal", "Prior: tier 0, junk", 0.2, "D41", "float", 0.0, 1.0, 0.05, "Junk in packs, important missed"),
    N("prior_normal", "Traversal", "Prior: tier 1, normal", 0.6, "D41", "float", 0.0, 1.0, 0.05, "Junk in packs, important missed"),
    N("prior_important", "Traversal", "Prior: tier 2, important", 1.0, "D41", "float", 0.0, 1.0, 0.05,
      "Junk in packs, important missed"),
    N("superseded", "Traversal", "Superseded item (another updates it)", 0.5, "D41", "float", 0.0, 1.0, 0.05,
      "Outdated facts in answers"),
    N("person_value_base", "Traversal", "Person value: base", 0.3, "D41", "float", 0.0, 1.0, 0.05,
      "Important people missed, or minor ones crowding packs",
      "A person's prior in the walk is their value (3 October 2026): this, plus the parts below.", starting=False),
    N("person_value_activity", "Traversal", "Person value: weight of their items", 0.45, "D41", "float", 0.0, 1.0, 0.05,
      "Important people missed, or minor ones crowding packs",
      "Times 1 - e^(-(items + 2 x items the owner wrote to them or answered) / scale), times the recency of the "
      "latest, by the half-life above.", starting=False),
    N("person_value_items", "Traversal", "Person value: scale, in items", 4, "D41", "float", 0.5, 100, 0.5,
      "Important people missed, or minor ones crowding packs", "How many items make a person count fully.",
      starting=False),
    N("person_value_relationship", "Traversal", "Person value: a relationship set", 0.25, "D41", "float", 0.0, 1.0,
      0.05, "Important people missed", "Added when the owner said who they are, or marked them known.",
      starting=False),
    N("r_low", "Traversal", "Relevance: cosine that scores 0", 0.2, "D41", "float", -1.0, 1.0, 0.01,
      "Recall at budget", "R for items reached by links maps cosine linearly from this to the next."),
    N("r_high", "Traversal", "Relevance: cosine that scores 1", 0.8, "D41", "float", -1.0, 1.0, 0.01,
      "Recall at budget"),
    N("width_ratio", "Traversal", "Width: keep children within this of the best", 0.6, "D43", "float", 0.0, 1.0, 0.05,
      "Recall, items expanded"),
    N("width_cap", "Traversal", "Width: at most this many children", 6, "D43", "int", 1, 50, 1, "Recall, items expanded"),
    N("mail_thread", "Traversal", "Mail to mail along its thread: link factor", 2.5, "D41", "float", 0.0, 5.0, 0.1,
      "Recall of replies", "An in_thread, reply_to, continues or follows_up link between two mails is multiplied "
      "by this on top of T(type), so a found mail's replies are reached before the cards, chats and layers it is "
      "only about. 2.5 since attempt 34: on the frozen benchmark 1 found 77.9% of the inbox set's gold, 2 80.6%, "
      "2.5 and 3 83.3%, 4 and 5 82.3%, the rest of Master the same at every value; raising every thread link "
      "whatever its ends lost Master items."),
    N("walk_words", "Traversal", "Relevance by the question's rare words: at most", 0.4, "D41", "float", 0.0, 1.0, 0.05,
      "Recall at budget", "An item reached by a link is relevant by meaning (the cosine above) or by the "
      "question's rare words its passages hold, whichever is higher: this times their weights added up, at most 1, "
      "where a word only one passage holds weighs 1 and commoner words less (BM25's idf); and one that holds any "
      "of them is queued however far below the best neighbour it scores (the width rule), within the width cap. "
      "0 turns both off. Meaning alone ranked a found task's file that named the very person asked about below "
      "its other files, and the width rule dropped it. On the frozen benchmark: 91.5% of the gold off, 92.9% at "
      "0.2, 93.4% at 0.3, 94.0% at 0.4 and 0.5; the weight alone, without the width rule, gave at most 92.8% and "
      "lost gold above 0.6. Attempt 38, 23 October 2026.", starting=False),
    N("walk_words_df", "Traversal", "Rare words: held by at most this many passages", 200, "D41", "int", 1, 100000, 10,
      "Recall at budget", "Only the question's words this rare count for the walk (above); commoner ones are "
      "left to meaning. 100 and 200 found the same, 400 lost gold. Attempt 38.", starting=False),
    N("floor", "Traversal", "Floor: never queue under", 0.02, "D44", "float", 0.0, 1.0, 0.005, "Recall, latency"),
    N("weak_frontier", "Traversal", "Stop when the best left is under", 0.05, "D44", "float", 0.0, 1.0, 0.005, "Recall, latency"),
    N("nothing_new", "Traversal", "A branch stops after this many empty expansions", 3, "D44", "int", 1, 50, 1,
      "Recall, latency"),
    N("max_expansions", "Traversal", "Walk cap: expansions", 300, "D44", "int", 1, 5000, 10, "Latency"),
    N("max_db_seconds", "Traversal", "Walk cap: database seconds", 1.5, "D44", "float", 0.1, 60, 0.1, "Latency"),
    N("budget_live", "Traversal", "Live budget, tokens", 5500, "D45", "int", 200, 50000, 100, "Where recall flattens",
      "4,000 until 18 October 2026 (attempt 33), when 30 of the benchmark's 34 questions that missed gold stopped "
      "on it with a gold item the search had found still in the queue. Free passes on the frozen copy found 77.2% "
      "of the gold at 4,000, 80.7% at 5,000, 82.2% at 5,500 and no more at 6,000, where the walk runs out of good "
      "items before the room; the own words gave 1,000 of their tokens to it, so the pack grew by about 2%.",
      starting=False),
    N("raw_open_max", "Traversal", "Raw items the checkpoint may open", 3, "D45", "int", 0, 10, 1, "Where recall flattens"),
    N("raw_open_tokens", "Traversal", "Tokens per raw item opened", 2000, "D45", "int", 100, 20000, 100,
      "Where recall flattens"),
    N("pack_words_tokens", "Traversal", "Items' own words in the pack, tokens", 5000, "D46", "int", 0, 50000, 500,
      "Answer correctness against cost", starting=False,
      note="X-ray lines keep no exact links, IDs, numbers or clauses, so the pack also carries the words: a short "
           "item whole, a long one's passages that best match the question, best-scored items first (4 October 2026). "
           "6,000 until 18 October 2026, when 1,000 of them went to the live walk's budget (attempt 33)."),
    N("pack_words_short_chars", "Traversal", "An item this short goes in whole, characters", 1500, "D46", "int", 0,
      20000, 100, "Answer correctness against cost", starting=False),
    N("pack_passages_per_item", "Traversal", "Passages from a long item", 2, "D46", "int", 0, 10, 1,
      "Answer correctness against cost", starting=False),
    N("handed_tokens", "Traversal", "What a model calling synapse_query is handed, at most, tokens", 8000, "D46",
      "int", 0, 50000, 500, "Recall of the gold in what is handed against its tokens", starting=False,
      note="The whole text a model reading the result is handed, counted as that model counts it (about 2.5 "
           "characters a token, `text.handed`): the pack's lines, their own words and the rules for what it "
           "found. The best-scored items first; an item that does not fit with its own words comes without "
           "them, and one that does not fit at all is left out, never cut in the middle. 0 hands it all. Until "
           "24 October 2026 the walk's 5,500 counted only the summaries, so the pack ran to 17,500 tokens on "
           "average and was cut at 12,000 characters wherever that fell, which handed over 37.9% of the "
           "benchmark's gold. Fitted, the gold handed over was 52% at 3,000, 67% at 4,500, 78% at 6,000, 86% "
           "at 8,000, 93% at 10,000 and 94% with no limit (17,500 tokens)."),
    N("handed_first_claims", "Traversal", "Claims an item first comes with in a handed pack", 3, "D46", "int", 0, 30,
      1, "Recall of the gold in what is handed against its tokens", starting=False,
      note="When the pack is fitted to handed_tokens, every item first goes in with its heading, its gist and only "
           "this many of its X-ray claims (those sharing most words with the question), best-scored item first; "
           "then, best first, whole, with all its claims and its own words (which keep the exact numbers, dates "
           "and names the X-ray lines leave out); then the rest with all their claims, while room is left. 0 "
           "gives every item all its claims from the start, as until 25 October 2026 (attempt 40), when about "
           "23 of the walk's 28 items fitted and 19 gold items of the benchmark were among those left out."),
    N("understand_for_models", "Traversal", "Rewrite the question for a model calling synapse_query", False,
      "D50", "bool", starting=False, moves="Recall of the gold with and without it",
      note="The understand step (D50, step 1) writes the search query with the answer model. It runs with "
           "Synapse's own answer, in the Synapse chat and the lab; for a model that reads the pack itself it is "
           "off unless this is on, since that model can search again itself."),
    N("budget_background", "Traversal", "Background budget, tokens", 20000, "D45", "int", 1000, 200000, 500,
      "Same, for mail"),
    N("background_seconds", "Traversal", "Background budget, seconds", 30, "D45", "int", 1, 600, 1, "Same, for mail"),
    N("context_boost", "Traversal", "Context boost (items in the context's task or from its sender)", 1.5, "D48",
      "float", 1.0, 5.0, 0.1, "Questions in a task answered from elsewhere"),
    N("extra_recalls", "Traversal", "Extra recalls the checkpoint may ask for", 2, "D50", "int", 0, 5, 1,
      "Cost against answer quality"),
    N("pack_days", "Traversal", "A background pack is kept, days", 7, "D56", "int", 1, 60, 1,
      "Packs reused against packs stale"),

    # --- decision models (D64 to D79) -------------------------------------------------------
    N("decision_models", "Decision models", "Decision models on (every point below)", False, "D64", "bool",
      starting=False, moves="D79's with-and-without comparison",
      note="Off since the decision of 4 October 2026: no decision call is made, and whatever needs deciding "
           "is decided by the helper model, mostly in the X-ray call (D82). Every point below takes its "
           "fallback, which is the spec without decision models. On brings them back, to compare (Q22); "
           "Evaluate's With decision models run turns them on for that run only."),
    N("dm_tier", "Decision models", "Tier call, when the helper model cannot answer (D80)", "openai_decisions", "D80",
      "choice", choices=DECISION_BACKENDS, moves="How often the helper model fails",
      note="The tier call is the helper model's, because it writes a reason. Only when that call fails is a "
           "decision model asked instead; its reason is what it picked and how sure it was. If neither "
           "answers, the item is tier 1, with why. D73's triage is withdrawn.", starting=False),
    N("xray_split_tier", "Decision models", "A separate tier call before the X-ray, for items that get one (D80)",
      False, "D82", "bool", moves="The benchmark of 4 October 2026: agreement, time and cost against the one call",
      note="Off: the X-ray call decides the tier, with its reason, from code's signals and the whole item, in the "
           "same answer (D82). On: the tier call runs first, as it did before 4 October 2026, and the X-ray only "
           "moves an item between tiers 1 and 2. Items with no X-ray always get the tier call.", starting=False),
    N("xray_split_sensitivity", "Decision models", "Sensitivity suggestions (D75) for items that get an X-ray too",
      False, "D82", "bool", moves="The benchmark of 4 October 2026: special items caught against the one call",
      note="Off: the X-ray call's sensitivity is the model's reading, raised by a level given with the item or "
           "an area of health, money, legal or finance (D82). On: the suggestions below also run before the "
           "X-ray, and can only raise. Items with no X-ray always get them.", starting=False),
    N("dm_sensitivity", "Decision models", "Sensitivity suggestions (D75)", "generative", "D75", "choice",
      choices=DECISION_BACKENDS, moves="Special items caught, 98 in 100",
      note="The spec says local only, never hosted; there is no local model on this machine yet, "
           "so the lab uses the generative backend, which D67 allows.", starting=False),
    N("dm_link_screen", "Decision models", "Link screening (D74)", "openai_decisions", "D74", "choice",
      choices=DECISION_BACKENDS, moves="Wrong and missed links per 10", starting=False),
    N("dm_short_links", "Decision models", "Short-item about links (D74)", "openai_decisions", "D74", "choice",
      choices=DECISION_BACKENDS, moves="Wrong links per 10", starting=False),
    N("dm_contradiction_screen", "Decision models", "Contradiction screen (D74)", "openai_decisions", "D74",
      "choice", choices=DECISION_BACKENDS, moves="Real contradictions reaching the helper call", starting=False),
    N("dm_seed_rerank", "Decision models", "Seed rerank backend (D70)", "openai_decisions", "D70", "choice",
      choices=DECISION_BACKENDS, moves="Recall at budget, with and without", starting=False,
      note="Used only when Rerank the seed candidates is on."),
    N("dm_frontier", "Decision models", "Frontier scoring in background walks (D71)", "openai_decisions", "D71",
      "choice", choices=DECISION_BACKENDS, moves="Recall of background packs", starting=False),
    N("dm_checkpoint_shadow", "Decision models", "Checkpoint shadow (D72)", "openai_decisions", "D72", "choice",
      choices=DECISION_BACKENDS, moves="How often a third call happens and is predicted", starting=False),
    N("hosted_allowed", "Decision models", "Hosted decision calls allowed for normal items (Q17)", True, "D67",
      "bool", starting=False,
      note="On in the lab because its data is fictional. Q17 is still open for real mail. Items "
           "above normal never go hosted, whatever this says."),
    N("tier_fallback_confidence", "Decision models", "Tier call fallback: a decision model's tier counts from",
      0.80, "D80", "float", 0, 1, 0.01, "Items the fallback put in the wrong tier",
      "Only when the helper model failed. Below this the item is tier 1, with why.", starting=False),
    N("sensitivity_noul", "Decision models", "Sensitivity suggests special at any Noul from", 0.30, "D78", "float",
      0, 1, 0.01, "Special items caught, 98 in 100"),
    N("short_link_noul", "Decision models", "Short-item link at Noul from", 0.85, "D78", "float", 0, 1, 0.01,
      "Wrong links per 10"),
    N("short_links_max", "Decision models", "Short-item links, at most", 3, "D74", "int", 0, 10, 1, "Wrong links per 10"),
    N("short_link_pool", "Decision models", "Short-item link candidates", 30, "D74", "int", 5, 100, 1, "Wrong links per 10"),
    N("screen_from", "Decision models", "Link screening: candidates screened", 100, "D74", "int", 20, 300, 10,
      "Wrong and missed links per 10"),
    N("contradiction_noul", "Decision models", "Contradiction screen at Noul from", 0.40, "D78", "float", 0, 1, 0.01,
      "Share of real contradictions reaching the helper call"),
    N("contradiction_max", "Decision models", "Contradiction candidates, at most", 5, "D74", "int", 0, 20, 1,
      "Share of real contradictions reaching the helper call"),
    N("contradiction_pool", "Decision models", "Older claims screened for contradictions", 50, "D74", "int", 0, 300, 5,
      "Share of real contradictions reaching the helper call"),
    N("frontier_wave", "Decision models", "Frontier wave: opens", 6, "D71", "int", 1, 30, 1,
      "Recall of background packs against wall time"),
    N("frontier_max", "Decision models", "Frontier wave: neighbours scored, at most", 60, "D71", "int", 1, 300, 1,
      "Recall of background packs against wall time"),
    N("frontier_weight", "Decision models", "Frontier relevance: weight on the decision model", 0.5, "D71", "float",
      0, 1, 0.05, "Recall at 0.25, 0.5, 0.75"),
    N("checkpoint_act", "Decision models", "Checkpoint shadow would act at", 0.90, "D72", "float", 0, 1, 0.01,
      "How often a third call happens and is predicted", "Logged only; nothing acts on it."),
    N("live_timeout_ms", "Decision models", "Live decision call time limit, ms", 300, "D69", "int", 50, 20000, 50,
      "Share of live calls past it",
      "The generative backend usually takes about a second, so at 300 ms a live seed rerank falls "
      "back; raise it to try the rerank with that backend."),
    N("background_timeout_s", "Decision models", "Background decision call time limit, s", 10, "D69", "int", 1, 120, 1,
      "Share of background calls past it"),
    N("daily_cap_usd", "Decision models", "Hosted decision spend cap per day, $", 1.0, "D69", "float", 0, 100, 0.5,
      "The bill; caps reached"),

    # --- importing many items at once ----------------------------------------------------------
    N("import_concurrency", "Import", "Items stored at once by an import", 16, "D52", "int", 1, 64, 1,
      "Hours per 10,000 items against rate limits",
      "An import stores this many items at once and runs their model part on the queue's backfill lane, "
      "which never takes a slot live items need. This lab's own choice.", starting=False),
    N("import_retries", "Import", "Tries for an item that fails during an import", 3, "D52", "int", 1, 10, 1,
      "Items left failed", starting=False),
    N("import_cap_usd", "Import", "Backfill spend cap per day, $", 100.0, "D52", "float", 0, 1000, 5,
      "The bill",
      "Backfill work stops for the day when this dataset's organisation has spent this much on Synapse "
      "today, and goes on the next day. At $0.0006 an item, 100,000 emails cost about $60.", starting=False),

    # --- layers (section 10) -------------------------------------------------------------------
    N("layer_thread", "Layers", "Thread layer from this many items", 4, "D53", "int", 2, 100, 1, "Packs flooded by one person"),
    N("layer_topic", "Layers", "Topic layer from this many items of a person and topic", 10, "D53", "int", 2, 500, 1,
      "Packs flooded by one person"),
    N("layer_profile", "Layers", "Profile from this many items", 30, "D53", "int", 2, 5000, 1, "Packs flooded by one person"),
    N("layer_profile_claims", "Layers", "Profile claims", 15, "D53", "int", 3, 60, 1, "Layer facts missed"),
    N("layer_topic_claims", "Layers", "Topic layer claims", 10, "D53", "int", 3, 60, 1, "Layer facts missed"),
    N("layer_thread_claims", "Layers", "Thread layer claims", 8, "D53", "int", 3, 60, 1, "Layer facts missed"),
    N("layer_removal_cap", "Layers", "One pass may retire at most this share", 0.25, "D54", "float", 0, 1, 0.05,
      "Never; it is a safety rule"),
    N("topic_layer_minutes", "Layers", "Topic layer updates at most every, minutes", 60, "D54", "int", 0, 1440, 5,
      "Cost; stale layers"),
    N("profile_layer_minutes", "Layers", "Profile updates at most every, minutes", 1440, "D54", "int", 0, 10080, 10,
      "Cost; stale layers"),

    # --- learning, tiers, rules ------------------------------------------------------------------
    N("learn_step", "Learning", "Learning step", 0.05, "D57", "float", 0, 0.5, 0.01, "Recall with and without"),
    N("learn_max", "Learning", "Most a link moves from where it was made", 0.3, "D57", "float", 0, 1, 0.05,
      "Recall with and without"),
    N("learn_min_shows", "Learning", "Down only after this many showings never cited", 10, "D57", "int", 1, 100, 1,
      "Recall with and without"),
    N("learn_code_floor", "Learning", "Code links never below", 0.2, "D57", "float", 0, 1, 0.05, "Recall with and without"),
    N("junk_sender_count", "Tiers", "Signal: a sender is often unanswered from this many items with no reply", 20,
      "D80", "int", 1, 500, 1, "Junk misfiled",
      "A signal the tier call reads, never a rule: code decides no tier."),
    N("tier_text_tokens", "Tiers", "Tier call: tokens of the item's text it reads", 1000, "D80", "int", 100, 8000, 50,
      "Tier calls that would change with more text; cost per 1,000 items"),
    N("tier_reason_words", "Tiers", "Tier call: its reason, words at most", 20, "D80", "int", 5, 60, 1,
      "Reasons ‹owner› accepts"),
    N("rules_account_tokens", "Rules", "Account-wide rules budget, tokens", 1000, "D59", "int", 100, 10000, 100,
      "Rules near the budget"),
    N("rules_item_tokens", "Rules", "Rules for one task or person, tokens", 1500, "D59", "int", 100, 10000, 100,
      "Rules near the budget"),

    # --- dreaming (D86 to D92, 5 October 2026) ------------------------------------------------------
    N("dream_cap_usd", "Dreaming", "A night's spend cap, $", 2.0, "D90", "float", 0, 50, 0.25,
      "What a night finds against what it costs",
      "A night stops cleanly when its model calls reach this, applies what it had judged, and says so. "
      "‹owner›'s starting value.", starting=False),
    N("dream_guard_share", "Dreaming", "A night changes at most this share of an area's claims or of its scope",
      0.25, "D89", "float", 0.01, 1, 0.01, "Never; it is a safety rule",
      "Over it, the night applies none of what it found and keeps every change waiting for ‹owner›, and says so "
      "on its page (OpenClaw's own rule).", starting=False),
    N("dream_guard_min_claims", "Dreaming", "The share is checked for an area from this many claims", 20, "D89",
      "int", 1, 10000, 1, "Nights stopped by one change in a tiny area",
      "An area with fewer claims is held by the night's scope alone, so one change in a three-claim area "
      "does not stop a night.", starting=False),
    N("dream_backfill_items", "Dreaming", "Items never read by a night, taken oldest first, per night", 300, "D87",
      "int", 0, 20000, 50, "Nights to cover the whole memory against their time and cost",
      "Besides what changed since the last night: the oldest items no night has read yet, so the whole "
      "memory is compared over the first nights, within the spend cap.", starting=False),
    N("dream_neighbours", "Dreaming", "Neighbours of an item compared with it, at most", 9, "D87", "int", 2, 30, 1,
      "Changes found per call against tokens per call",
      "Same thread, same person, same task, same topic, links one hop out, then the closest by words and "
      "meaning.", starting=False),
    N("dream_matches", "Dreaming", "Of them, closest by words and meaning, at most", 4, "D87", "int", 0, 20, 1,
      "Changes found by search alone", starting=False),
    N("dream_concurrency", "Dreaming", "Judge calls at once", 4, "D88", "int", 1, 16, 1,
      "A night's time against rate limits", starting=False),
    N("dream_auto_replaced", "Dreaming", "Apply by itself: a claim replaced by a newer one", True, "D91", "bool",
      starting=False, note="An annotation beside the claim, never an edit; Undo puts it back."),
    N("dream_auto_closed", "Dreaming", "Apply by itself: an ask answered, a promise kept", True, "D91", "bool",
      starting=False, note="An annotation beside the claim, never an edit; Undo puts it back."),
    N("dream_auto_links", "Dreaming", "Apply by itself: the usage feedback on link strengths", True, "D91", "bool",
      starting=False, note="The same moves as synapse_learn (D57), each with Undo."),
    N("dream_auto_duplicates", "Dreaming", "Apply by itself: a duplicate kept as an alias", False, "D91", "bool",
      starting=False, note="Off: a merge waits for ‹owner›'s Approve or Reject."),
    N("dream_auto_kinds", "Dreaming", "Apply by itself: a rule that is a fact or a contract term", False, "D91",
      "bool", starting=False, note="Off: a change of kind waits for ‹owner›'s Approve or Reject."),
    N("dream_auto_sensitivity", "Dreaming", "Apply by itself: a thread raised to its highest sensitivity", False,
      "D91", "bool", starting=False, note="Off: it waits for ‹owner›. Never lowered, whatever this says."),

    # --- evaluation gates (section 15) --------------------------------------------------------
    N("gate_recall", "Evaluation", "Gate: recall at budget", 0.85, "15", "float", 0, 1, 0.01, "‹owner›"),
    N("gate_citation", "Evaluation", "Gate: citation correctness", 0.95, "15", "float", 0, 1, 0.01, "‹owner›"),
    N("gate_median_s", "Evaluation", "Gate: time to pack, median, seconds", 2.0, "15", "float", 0.1, 60, 0.1, "‹owner›"),
    N("gate_p95_s", "Evaluation", "Gate: time to pack, 95th percentile, seconds", 5.0, "15", "float", 0.1, 120, 0.1, "‹owner›"),
    N("gate_cost", "Evaluation", "Gate: cost per question, $", 0.02, "15", "float", 0, 1, 0.005, "‹owner›"),
    N("gate_decision_points", "Evaluation", "Decision-model gate: recall up by, points", 3, "D79", "float", 0, 50, 1,
      "How large the gains turn out to be"),
    N("key_facts", "Evaluation", "Key facts the answers are scored against", "current", "D77", "choice",
      choices=("current", "v1"), starting=False,
      note="current is each question's facts as they are now; v1 is the facts kept from before the rewrite of "
           "4 October 2026 (one claim to a line, dates on their own lines). A question with no v1 uses its current "
           "facts. For runs that measure one change at a time."),
    N("judge_version", "Evaluation", "The judge's rules", "v2", "D77", "choice", choices=("v2", "v1"),
      starting=False,
      note="v2 (since 4 October 2026): never of the family that ranked or answered; a fact is present when its "
           "substance is stated, and a missing date fails only a fact that is a date. v1: never of the family that "
           "ranked only, and 'Be strict'. Kept so a run can measure a change against the judge as it was."),
    N("judge_evidence_chars", "Evaluation", "The judge reads of each cited item, characters", 6000, "D77", "int", 500,
      50000, 500, "Citation correctness against judge cost", starting=False,
      note="A longer item is quoted in the passages that best match what the answer says with it, not its "
           "first part (4 October 2026)."),
)

BY_KEY = {n.key: n for n in NUMBERS}

#: Which model each of Synapse's model jobs asks is not a number of this lab's any more: Petar, the
#: evening of 18 October 2026, "Every call that we make now has to route through our new model
#: selection. Whatever we select here should be the one called. No exceptions." Each is a use on the
#: Models page (`rouh/modeldefaults.py`, group Synapse), read at the moment of asking through these
#: names on a dataset's settings (`Settings.__getattr__`), so `s.answer_model` is whatever Answers is
#: set to there now. Until then each was a number here, per dataset (helper_model, answer_model,
#: decision_model, recall_second_model, judge_model, dream_model), and a value a dataset kept for one
#: is ignored. The embedding model (`embed_model`) stays a number of the dataset's: a dataset's vectors
#: are all one embedding model's, and a question has to be embedded with that same model.
MODEL_USES = {"helper_model": "synapse_helper", "answer_model": "synapse_answer",
              "decision_model": "synapse_decision", "decisions_api_model": "synapse_decisions_api",
              "recall_first_model": "synapse_recall_first", "recall_second_model": "synapse_recall_second",
              "judge_model": "synapse_judge", "dream_model": "synapse_dream"}

#: The link types (D29), who writes each and its starting strength key.
LINK_TYPES = {
    "from": ("code", "s_from"), "to": ("code", "s_to"), "cc": ("code", "s_cc"),
    "in_thread": ("code", "s_in_thread"), "reply_to": ("code", "s_reply_to"),
    "in": ("code", "s_in"), "same_as": ("code", "s_same_as"), "attached": ("code", "s_attached"),
    "about": ("model", ""), "follows_up": ("model", ""), "continues": ("model", ""), "contradicts": ("model", ""),
    "updates": ("model", ""), "rule_for": ("code", "s_rule_for"), "built_from": ("code", "s_built_from"),
    # A meeting from the meeting library (`meetings.py`).
    "recorded": ("code", "s_recorded"), "attended": ("code", "s_attended"), "invited": ("code", "s_invited"),
    "spoke": ("code", "s_spoke"),
}
JUDGEMENT_TYPES = ("about", "follows_up", "continues", "contradicts", "updates")

#: The kinds of item (D21), a closed list.
KINDS = ("mail", "event", "doc", "person", "place", "topic", "task", "project", "file", "chat_turn",
         "note", "rule", "layer", "rouh_said", "card", "meeting")


class Settings(dict):
    """The numbers one dataset (and perhaps one query) works by."""

    def __getattr__(self, key):
        if key in MODEL_USES:
            return self.pair(key).model
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def pair(self, key: str):
        """The model and the level the Models page has for one of Synapse's model jobs, now
        (`MODEL_USES`), for the organisation whose dataset this is."""
        from .. import modeldefaults

        return modeldefaults.use_pair(MODEL_USES.get(key, key), dict.get(self, "_org") or None)

    def strength(self, bucket: str) -> float:
        return float(self.get("strength_" + bucket, 0.6))

    def code_strength(self, link_type: str) -> float:
        key = LINK_TYPES.get(link_type, ("", ""))[1]
        return float(self.get(key, 0.6)) if key else 0.6

    def type_factor(self, link_type: str) -> float:
        """T(type) in D41: 1 for every type to start with."""
        return float((self.get("type_factors") or {}).get(link_type, 1.0))


def clean(key: str, value):
    """A value for one number, held to its kind and its range, or a ValueError."""
    n = BY_KEY.get(key)
    if key == "type_factors":
        if not isinstance(value, dict):
            raise ValueError("type factors are a table of link type to a number")
        return {k: max(0.0, min(5.0, float(v))) for k, v in value.items() if k in LINK_TYPES}
    if n is None:
        raise ValueError(f"there is no number called {key}")
    if n.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)
    if n.kind == "choice":
        if value not in n.choices:
            raise ValueError(f"{n.label} is one of {', '.join(map(str, n.choices))}")
        return value
    if n.kind == "text":
        return str(value)
    number = float(value)
    if n.lo is not None and number < n.lo:
        raise ValueError(f"{n.label} is at least {n.lo}")
    if n.hi is not None and number > n.hi:
        raise ValueError(f"{n.label} is at most {n.hi}")
    return int(round(number)) if n.kind == "int" else number


def defaults() -> dict:
    out = {n.key: n.value for n in NUMBERS}
    out["type_factors"] = {t: 1.0 for t in LINK_TYPES}
    return out


def settings_for(tuning: dict | None, override: dict | None = None, org_id: str = "") -> Settings:
    """The numbers in force: the starting values, the dataset's, then the query's. `org_id` is
    whose Models page Synapse's models are read from (`MODEL_USES`)."""
    out = defaults()
    for source in (tuning or {}, override or {}):
        for key, value in source.items():
            try:
                out[key] = clean(key, value)
            except (ValueError, TypeError):
                continue
    if org_id:
        out["_org"] = str(org_id)
    return Settings(out)


def catalogue(tuning: dict | None = None) -> list[dict]:
    """Every number, with its starting value and what the dataset has it at."""
    now = settings_for(tuning)
    return [{"key": n.key, "group": n.group, "label": n.label, "start": n.value,
             "value": now[n.key], "ref": n.ref, "kind": n.kind, "lo": n.lo, "hi": n.hi,
             "step": n.step, "moves": n.moves, "note": n.note, "choices": list(n.choices),
             "starting": n.starting, "changed": now[n.key] != n.value}
            for n in NUMBERS] + [{
                "key": "type_factors", "group": "Traversal", "label": "T(type): per link type factor",
                "start": {t: 1.0 for t in LINK_TYPES}, "value": now["type_factors"], "ref": "D41",
                "kind": "table", "moves": "Learning (D57) showing a type matters more or less",
                "note": "1 for every type at the start, so only strength counts.", "starting": True,
                "changed": any(v != 1.0 for v in now["type_factors"].values()), "choices": []}]
