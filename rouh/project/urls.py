"""Every address Rouh answers, and the view that answers it.

The same addresses the FastAPI app answered until 23 September 2026, plus
those that came with Django: `/admin/` (Django's own admin, for whoever manages
accounts), and the two a Django app always has, a 404 and a 500 that give
nothing of the machine away. Since 24 September 2026 the two a forgotten
password needs, `/login/forgot` and the link it emails,
`/login/reset/<uid>/<token>` (`rouh/web/reset.py`); since 4 November 2026 the
ways in after the email box (`rouh/web/auth.py`), and no Google sign-in.

**Order matters in three places.** `/api/gene-therapy/requests...` and
`/api/gene-therapy/settings` come before `/api/gene-therapy/<id>`, or the word
"requests" or "settings" would be read as a feedback's id (and the same under
`/api/feedback`, Gene therapy's name until 12 October 2026).
The page's own
addresses - `/`, `/one/`, `/tasks` and one per kind of object - are last,
because they are the widest.

The websocket is not here: it is `/ws`, routed by Channels in
`rouh/project/asgi.py`.
"""
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path, re_path

from rouh import addressing, askai, filelinks, genes, onebridge, pages, picturelinks, sharing
from rouh.web import agent_instructions as agent_instructions_web
from rouh.web import anatomy as anatomy_web
from rouh.web import silos as silos_web
from rouh.web import demo as demo_web
from rouh.web import dreame as dreame_web
from rouh.web import claude_signin as claude_signin_web
from rouh.web import codex_signin as codex_signin_web
from rouh.web import subscriptions as subscriptions_web
from rouh.web import setup_api
from rouh.web import firstrun as firstrun_web
from rouh.web import phoneapi
from rouh.web import filesapi
from rouh.web import home as home_web
from rouh.web import hue as hue_web
from rouh.web import birth as birth_web
from rouh.web import landaccount as landaccount_web
from rouh.web import signin as signin_web
from rouh.web import relay as relay_web
from rouh.web import slack as slack_web
from rouh.web import synapse as synapse_web
from rouh.web import actions as actions_web
from rouh.web import (apple, assets, auth, boxes, brief, changes as changes_web, clock, cloudflare, comments, control,
                      decisions, defaults,
                      definitions,
                      draftedits,
                      evolution as evolution_web, incubator as incubator_web, nightly_run as nightly_run_web, trials as trials_web, gene_therapy, genelog as genelog_web, genepool as genepool_web, genes as genes_web,
                      heartbeat, payments, quests, receipts, services, shipping, signups, stats, thoughts,
                      google,
                      guests, highlights, location, mail_alerts, mailboxes, mycard, offline, people, profile, reset,
                      rules,
                      signatures, sources, vocabulary,
                      
                      page_gdoc as page_gdoc_web, page_listen as page_listen_web, page_pdf as page_pdf_web,
                      pagestate as pagestate_web,
                      since_read as since_read_web,
                      doc_on_page as doc_on_page_web, meeting_attach as meeting_attach_web, task_docs as task_docs_web, to_send as to_send_web, open_items as open_items_web, task_time as task_time_web, not_arrived as not_arrived_web, away_after as away_after_web, new_number as new_number_web, renewal as renewal_web, objecttreeapi, taskapi, telegram_account, trusted, views)


def _admin_sign_in(request, extra_context=None):
    """The admin's own sign-in page is Rouh's: there is one way in, and it is
    the one with the throttling on it (`rouh/web/auth.py`)."""
    return HttpResponseRedirect("/login?next=" + (request.GET.get("next") or "/admin/"))


def _section(name: str) -> str:
    """A section of Anatomy's address, without its first slash: `anatomy/<its group>/<name>`."""
    return f"{addressing.ANATOMY.lstrip('/')}/{genes.SECTIONS[name]}/{name}"


def gene_therapy_old_address(request):
    """/feedback, Gene therapy's name until 12 October 2026: the page with the drawer
    open, at its new address, with anything after the `?` kept."""
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(addressing.GENE_THERAPY + ("?" + query if query else ""))


def evolution_library_old_address(request, rest=""):
    """/evolution/library, Mutations' address while it was the Gene library, and the Gene Pool's
    while it was one of its views, until 14 October 2026 (fr_a982710d30c7): an old link or bookmark
    lands on the same view at its new address, with anything after the `?` kept."""
    query = request.META.get("QUERY_STRING", "")
    rest = rest.strip("/")
    if rest == "pool" or rest.startswith("pool/"):
        to = addressing.EVOLUTION + "/" + rest
    else:
        to = addressing.EVOLUTION + "/mutations" + ("/" + rest if rest else "")
    return HttpResponseRedirect(to + ("?" + query if query else ""))


def sources_without_a_task(request):
    """/sources with no task after it, which was every checked page until 13 October 2026, when
    Petar took it out of the navigation (fr_fce8f51c00d6): sources belong to a task and are
    reached from it. An old link or bookmark lands in the task browser, with `?chat=` kept."""
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(addressing.BROWSER + ("?" + query if query else ""))


def browser_with_a_slash(request):
    """/tasks/, the task browser's address with a slash after it, which a person types or a
    bookmark keeps: the browser, with anything after the `?` kept, rather than Not found."""
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(addressing.BROWSER + ("?" + query if query else ""))


def clockwork_old_address(request):
    """/reminders, Clockwork's address until 8 October 2026: the same page at its new
    address, with the conversation beside it (`?chat=`) kept."""
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(addressing.CLOCKWORK + ("?" + query if query else ""))


def metabolism_old_address(request, tab=""):
    """/runs, Metabolism's address until 14 October 2026: the same page at its new
    address, on the same tab, with the conversation beside it (`?chat=`) kept."""
    query = request.META.get("QUERY_STRING", "")
    to = addressing.METABOLISM + ("/" + tab if tab in addressing.METABOLISM_TABS else "")
    return HttpResponseRedirect(to + ("?" + query if query else ""))


admin.site.login = _admin_sign_in
admin.site.site_header = "Rouh"
admin.site.site_title = "Rouh"
admin.site.index_title = "Accounts and organisations"

handler404 = "rouh.web.views.not_found"
handler500 = "rouh.web.views.server_error"

urlpatterns = [
    # --- signing in -----------------------------------------------------------
    path("login", auth.login),
    path("login/link/<str:token>", auth.link),
    path("login/help", auth.help_page),
    path("login/passkey/options", auth.passkey_options),
    path("login/passkey/verify", auth.passkey_verify),
    path("login/forgot", reset.forgot),
    path("login/reset/<str:uid>/<str:token>", reset.follow),
    path("login/common-passwords", reset.common_passwords),
    path("logout", auth.logout),
    # A fresh installation's first run (`rouh/web/firstrun.py`): the code, then one screen at a
    # time, each at its own address; the first is open until there is an owner, the rest are the
    # owner's until the first run is over.
    path("setup", firstrun_web.setup),
    path("setup/you", firstrun_web.you),
    path("setup/connect", firstrun_web.connect),
    path("setup/email", firstrun_web.email),
    path("setup/born", firstrun_web.born),
    path("setup/brain", firstrun_web.brain),
    path("setup/brain/<str:company>", firstrun_web.company_key),
    path("setup/brain/<str:company>/how", firstrun_web.company_how),
    # The same first run for Rouh for Mac's native screens, as JSON, with the setup code as a bearer
    # token (`rouh/web/setup_api.py`, task 140, step 140-13).
    path("setup/api/state", setup_api.get_state),
    path("setup/api/you", setup_api.you),
    path("setup/api/kind", setup_api.kind),
    path("setup/api/email", setup_api.email),
    path("setup/api/born", setup_api.born),
    path("setup/api/key", setup_api.key),
    path("setup/api/plan", setup_api.plan),
    path("setup/api/done", setup_api.done),
    path("setup/api/name", setup_api.name),
    path("setup/api/address/email", setup_api.address_email),
    path("setup/api/open", setup_api.open_rouh),
    # Then Claude Code's sign-in, in the containers only (`rouh/web/claude_signin.py`).
    # The phone address: its HTTP-01 check and the QR code's sign-in (`rouh/web/relay.py`).
    path(".well-known/acme-challenge/<str:token>", relay_web.challenge),
    path("phone/in", relay_web.phone_in),
    path("setup/claude", claude_signin_web.page),
    path("setup/claude/state", claude_signin_web.state),
    # And Codex's, with a ChatGPT plan (`rouh/web/codex_signin.py`).
    path("api/subscriptions/<str:provider>", subscriptions_web.endpoint),
    path("setup/codex", codex_signin_web.page),
    path("setup/codex/state", codex_signin_web.state),
    path("healthz", views.healthz),

    # --- the page's own files ----------------------------------------------------
    path("a/<str:stamp>/<path:filename>", assets.asset),
    # The service worker, at the top so it looks after every address (`rouh/web/offline.py`).
    path("sw.js", offline.service_worker),
    path("static/<path:path>", assets.static_file),

    # --- demo mode: one switch that blurs the person's content everywhere (`rouh/web/demo.py`) ---
    path("api/demo", demo_web.state),
    path("api/demo/dots", demo_web.dots),
    path("api/demo/preview", demo_web.preview),
    path("api/demo/approvals", demo_web.approvals),
    path("api/demo/approve", demo_web.approve),
    path("api/demo/copy", demo_web.copy),
    path("api/demo/history", demo_web.history),

    # --- the machine, the spend, the stop --------------------------------------
    path("api/machine/load", views.machine_load_now),
    path("api/spend", views.spend_record),
    path("api/usage/daily", views.usage_by_day),
    path("api/turns/export", views.turns_export),
    path("api/stop", views.stop_the_turn),
    path("gaps", views.gaps_page),
    path("api/gaps", views.gaps_record),

    # --- the canvas and the workspace --------------------------------------------
    path("api/canvas/cards", views.canvas_cards),
    path("api/transcript", views.transcript_page),
    path("api/canvas/card", views.canvas_card),
    path("api/canvas/drawn", views.canvas_drawn),
    path("api/canvas/image", views.canvas_image),
    # One of Rouh's own jobs on the canvas, and starting one that died again.
    path("api/job/<str:job_id>", views.job_page),
    path("api/job/<str:job_id>/restart", views.job_restart),
    path("api/workspace/index", views.workspace_index),
    # The Control Room: the work in flight, read only (`rouh/controlroom.py`).
    path("api/control", control.control_room),
    path("api/control/others", control.control_others),
    # Synapse's lab: the new memory, its datasets and its debugger (`rouh/synapse/`).
    re_path(r"^api/synapse/?(?P<rest>.*)$", synapse_web.api),
    # The meeting library says a meeting changed: signed, and open to it alone (`rouh/synapse/meetings.py`).
    path("api/hooks/meeting-library", synapse_web.meeting_library_hook),
    path("api/workspace/task", views.workspace_task),
    path("api/workspace/filing", views.workspace_filing),
    # Where a task's Move may put it (`rouh/moving.py`).
    path("api/workspace/destinations", views.workspace_destinations),
    path("api/workspace/file", views.workspace_file),
    path("api/workspace/folder", views.workspace_folder),
    path("api/workspace/step", views.workspace_step),
    path("api/one/deploy", views.deploy_the_one_program),

    # A task's working file, downloaded by the signed link beside it (`rouh/filelinks.py`).
    path(filelinks.ROUTE.lstrip("/") + "<str:token>/<str:name>", views.file_link),
    # A picture of a page on the canvas, by the signed address it was given (`rouh/picturelinks.py`).
    path(picturelinks.ROUTE.lstrip("/") + "<str:token>/<path:rel>", views.picture_link),

    # --- files attached in the chat -------------------------------------------------
    path("attachments/<str:session_id>", views.attach),
    path("attachments/<str:session_id>/<str:att_id>", views.attached),

    # --- the workspace's pages, Ask AI on them, and making one public ------------------
    re_path(r"^" + pages.ROUTE.lstrip("/") + r"(?P<path>.*)$", views.workspace_page),
    path(askai.ROUTE.lstrip("/") + "threads", views.askai_threads),
    path(askai.ROUTE.lstrip("/") + "threads/<int:thread_id>", views.askai_thread),
    path(askai.ROUTE.lstrip("/") + "ask", views.askai_ask),
    path(askai.ROUTE.lstrip("/") + "undo", views.askai_undo),
    path(askai.ROUTE.lstrip("/") + "type", views.askai_type),
    # Comments pinned to one of the person's own pages (`rouh/web/comments.py`).
    path("api/comments", comments.for_owner),
    # Passages the person highlighted on one of their own pages (`rouh/web/highlights.py`).
    path("api/highlights", highlights.for_owner),
    # Passages explained in place on one of the person's own pages (`rouh/web/definitions.py`).
    path("api/definitions", definitions.for_owner),
    # A page's own settings, the person's choices on it (`rouh/web/pagestate.py`).
    path("api/page-state", pagestate_web.for_owner),
    # Every page's checked sources, and his word that one holds (`rouh/web/sources.py`).
    path("api/sources", sources.for_owner),
    # A page as a printable PDF from its own PDF button, and the notice when it is ready
    # (`rouh/web/page_pdf.py`, `rouh/page_pdf.py`).
    path("api/page-pdf", page_pdf_web.for_owner),
    # Listen to this page, the speaker in a page's floating control (`rouh/web/page_listen.py`,
    # `rouh/page_listen.py`), carried by the canvas's relay.
    path("api/page-listen", page_listen_web.for_owner),
    # What changed on a page since its owner last saw it, the canvas bar's What changed
    # (`rouh/web/since_read.py`, `rouh/since_read.py`).
    path("api/since-read", since_read_web.for_owner),
    # A Google Doc of this page, the share icon's menu (`rouh/web/page_gdoc.py`, `rouh/page_gdoc.py`).
    path("api/page-gdoc", page_gdoc_web.for_owner),
    # What changed in a Google document a task's notes link to (`rouh/web/task_docs.py`).
    path("api/task-docs/changes", task_docs_web.changes),
    path("api/task-docs/names", task_docs_web.names),
    path("api/task-docs/add", task_docs_web.add),
    # Comments on the task's documents (`rouh/task_comments.py`, night 26).
    path("api/task-docs/comments", task_docs_web.comments),
    path("api/task-docs/apply-comments", task_docs_web.apply_comments),
    path("api/task-docs/rehearse", task_docs_web.rehearse_deck),
    path("api/task-docs/slide-picture", task_docs_web.slide_picture),
    path("api/task-docs/rehearsed", task_docs_web.rehearsed),
    path("api/to-send", to_send_web.press),
    path("api/open-items", open_items_web.press),
    path("api/task-time", task_time_web.press),
    # On the page?, beside What changed (`rouh/web/doc_on_page.py`, `rouh/doc_on_page.py`).
    path("api/task-docs/on-page", doc_on_page_web.on_page),
    # Attach to a meeting, on a document's line (`rouh/web/meeting_attach.py`, `rouh/meeting_attach.py`).
    path("api/task-docs/attach", meeting_attach_web.attach),
    # Evolution: Parameters and Mutations (`rouh/web/evolution.py`, `rouh/evolution.py`).
    path("api/evolution/parameters", evolution_web.parameters),
    path("api/evolution/mutations", evolution_web.mutations),
    path("api/evolution/month", evolution_web.month),
    path("api/evolution/genes/<int:gene_id>", evolution_web.gene),
    path("api/evolution/genes/<int:gene_id>/answer", evolution_web.gene_answer),
    path("api/evolution/genes/<int:gene_id>/trial", evolution_web.gene_trial),
    path("api/evolution/genes/<int:gene_id>/mutate", evolution_web.gene_mutate),
    path("api/evolution/genes/<int:gene_id>/ask", evolution_web.gene_ask),
    path("api/evolution/mutations/<int:mutation_id>", evolution_web.mutation),
    path("api/evolution/switches", evolution_web.switch),
    # The Incubator: one list of ideas for new genes and mutations (`rouh/web/incubator.py`).
    path("api/incubator", incubator_web.listing),
    path("api/incubator/new", incubator_web.new),
    path("api/incubator/bulk", incubator_web.bulk),
    path("api/incubator/prefs", incubator_web.prefs),
    path("api/incubator/chat", incubator_web.chat),
    path("api/incubator/scoring", incubator_web.scoring),
    path("api/incubator/gists", incubator_web.gists),
    path("api/incubator/<int:number>", incubator_web.idea),
    path("api/incubator/<int:number>/status", incubator_web.status),
    path("api/incubator/<int:number>/merge", incubator_web.merge),
    path("api/incubator/<int:number>/link", incubator_web.link),
    path("api/incubator/<int:number>/score", incubator_web.score),
    path("api/incubator/<int:number>/chat", incubator_web.idea_chat),
    path("api/incubator/<int:number>/feedback", incubator_web.feedback),
    # Trials: a made-up person tries a change, and the list of problems they trip on (`rouh/web/trials.py`).
    path("api/trials", trials_web.listing),
    path("api/trials/new", trials_web.new),
    path("api/trials/problems", trials_web.problems),
    path("api/trials/problems/<int:number>", trials_web.one_problem),
    path("api/trials/problems/<int:number>/say", trials_web.problem_say),
    path("api/trials/problems/<int:number>/verdict", trials_web.problem_verdict),
    path("api/trials/problems/<int:number>/report", trials_web.problem_report),
    path("api/trials/jobs/<int:number>", trials_web.one_job),
    path("api/trials/jobs/<int:number>/run", trials_web.run_job),
    path("api/trials/testers", trials_web.testers),
    path("api/trials/testers/new", trials_web.new_tester),
    path("api/trials/testers/draft", trials_web.draft_tester),
    path("api/trials/testers/<str:key>", trials_web.one_tester),
    path("api/trials/testers/<str:key>/remove", trials_web.remove_tester),
    path("api/trials/testers/<str:key>/default", trials_web.default_tester),
    path("api/trials/testers/<str:key>/pause", trials_web.pause_tester),
    path("api/trials/pause", trials_web.pause_all),
    path("api/trials/<int:number>", trials_web.trial),
    path("api/trials/<int:number>/again", trials_web.again),
    path("api/trials/<int:number>/fix", trials_web.fix),
    path("api/trials/<int:number>/shot/<int:step>", trials_web.shot),
    # The nightly feature run as a feature of its own (`rouh/web/nightly_run.py`).
    path("api/evolution/nightly", nightly_run_web.page),
    # The gene log: every gene in this Rouh, its family, use, mark and evaluation (`rouh/web/genelog.py`).
    path("api/genes/log", genelog_web.listing),
    path("api/genes/log/read", genelog_web.read),
    path("api/genes/log/<int:gene_id>", genelog_web.gene),
    path("api/genes/log/<int:gene_id>/mark", genelog_web.mark),
    path("api/genes/log/<int:gene_id>/evaluate", genelog_web.evaluate),
    path("api/genes/log/<int:gene_id>/turn", genelog_web.turn),
    path("api/genes/log/<int:gene_id>/remove", genelog_web.remove),
    path("api/genes/log/<int:gene_id>/draft", genelog_web.draft),
    path("api/genes/drafts/propose", genelog_web.propose),
    # A Rouh's birth: its own name, its keys, rouh.land (`rouh/web/birth.py`, task 141).
    path("api/rouh-land/account", landaccount_web.page),
    path("api/rouh-land/account/check", landaccount_web.check),
    path("api/rouh-land/account/confirm", landaccount_web.confirm),
    # Signing in, from the signed-in side (`rouh/web/signin.py`): Anatomy, You, Account, and a guest's card.
    path("api/sign-in/me", signin_web.me_state),
    path("api/sign-in/email", signin_web.change_email),
    path("api/sign-in/passkey/options", signin_web.passkey_options),
    path("api/sign-in/passkey/add", signin_web.passkey_add),
    path("api/sign-in/passkey/remove", signin_web.passkey_remove),
    path("api/sign-in/guest", signin_web.guest_state),
    path("api/sign-in/guest/send", signin_web.guest_send),
    path("api/sign-in/guest/link", signin_web.guest_link),
    path("api/birth", birth_web.page),
    path("api/birth/born", birth_web.born),
    path("api/birth/nickname", birth_web.nickname),
    path("api/birth/connect", birth_web.connect),
    path("api/birth/check", birth_web.check),
    path("api/birth/rotate", birth_web.rotate),
    path("api/birth/recover", birth_web.recover),
    path("api/birth/recover/started", birth_web.recover_started),
    path("api/birth/end", birth_web.end),
    path("api/birth/disconnect", birth_web.disconnect),
    # The Gene Pool, and choosing a gene for it (`rouh/web/genepool.py`).
    path("api/genes/log/<int:gene_id>/share", genepool_web.share),
    path("api/genes/log/<int:gene_id>/allow", genepool_web.allow),
    path("api/genes/pool", genepool_web.page),
    path("api/genes/pool/refresh", genepool_web.refresh),
    path("api/genes/pool/match", genepool_web.match),
    path("api/genes/pool/install", genepool_web.install),
    path("api/genes/pool/thanks", genepool_web.thanks),
    path("api/genes/pool/update", genepool_web.update),
    path("api/genes/pool/mode", genepool_web.mode),
    path("api/genes/pool/incoming", genepool_web.incoming),
    path("api/genes/pool/out", genepool_web.out),
    path("api/genes/pool/out/<int:gene_id>", genepool_web.out),
    path("api/genes/pool/out/<int:gene_id>/approve", genepool_web.approve),
    path("api/genes/pool/out/<int:gene_id>/decline", genepool_web.decline),
    path("api/genes/pool/out/<int:gene_id>/edit", genepool_web.edit),
    path(askai.ROUTE.lstrip("/") + "history", views.askai_history),
    path(askai.ROUTE.lstrip("/") + "keep", views.askai_keep),
    path(askai.ROUTE.lstrip("/") + "where", views.askai_where),
    path(askai.ROUTE.lstrip("/") + "option", views.askai_option),
    path("api/share", views.share),
    path("api/share/all", views.share_all),
    path("api/share/stop", views.share_stop),
    path("api/share/invite", guests.invite),
    path("api/share/remind", guests.remind),
    path("api/share/ends", guests.ends),
    path("api/share/meetings", guests.meetings),
    path("api/share/uninvite", guests.uninvite),
    path(sharing.ROUTE.lstrip("/") + "<str:token>", views.public_page),

    # --- a page read by somebody who is not its owner (`rouh/web/guests.py`) ----------
    # A visitor to a public link that may be changed, and a person the page
    # was shared with by email: the same page and the same five routes under
    # each one's own token. `/join/` is the invitation, open to everybody like
    # `/p/`, because it is for somebody with no account yet.
    path(sharing.ROUTE.lstrip("/") + "<str:token>/page", guests.LINK["page"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/ask", guests.LINK["ask"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/threads", guests.LINK["threads"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/threads/<int:thread_id>",
         guests.LINK["thread"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/undo", guests.LINK["undo"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/type", guests.LINK["type"]),
    path(sharing.ROUTE.lstrip("/") + "<str:token>/option", guests.LINK["option"]),
    path("join/<str:token>", guests.join),
    path("shared", guests.shared_list),
    path("shared/<str:token>", guests.SHARED["view"]),
    path("shared/<str:token>/page", guests.SHARED["page"]),
    path("shared/<str:token>/ask", guests.SHARED["ask"]),
    path("shared/<str:token>/threads", guests.SHARED["threads"]),
    path("shared/<str:token>/threads/<int:thread_id>", guests.SHARED["thread"]),
    path("shared/<str:token>/undo", guests.SHARED["undo"]),
    path("shared/<str:token>/type", guests.SHARED["type"]),
    # Comments on a page shared with a person. Not under `/p/`: a visitor to a
    # link is nobody, with no name to put on a comment (`rouh/comments.py`).
    path("shared/<str:token>/comments", comments.for_shared),
    # Everybody's highlights on it, for the same people as its comments.
    path("shared/<str:token>/highlights", highlights.for_shared),
    # And the passages explained on it, for the same people again.
    path("shared/<str:token>/definitions", definitions.for_shared),
    path("shared/<str:token>/option", guests.SHARED["option"]),

    # --- Gene therapy: feedback and feature requests (requests, settings first: see the
    # docstring). Under `api/feedback` as well, its name until 12 October 2026, so a page
    # loaded before the rename still sends and reads.
    *[route for base in ("api/gene-therapy", "api/feedback") for route in (
        path(base, gene_therapy.board),
        path(base + "/settings", gene_therapy.settings),
        path(base + "/requests", gene_therapy.new_request),
        path(base + "/requests/<str:request_id>", gene_therapy.one_request),
        path(base + "/requests/<str:request_id>/run", gene_therapy.run_for_request),
        path(base + "/<str:feedback_id>", gene_therapy.one_feedback),
        path(base + "/<str:feedback_id>/promote", gene_therapy.promote),
    )],

    # --- Google: the organisation's client, and each person's connection ----------------
    path("api/settings/location", location.settings_location),
    path("api/settings/location/forget", location.forget),
    path("api/settings/location/place", location.typed_place),
    path("api/settings/location/second", location.second_zone),
    path("api/settings/models", defaults.settings_models),
    path("api/settings/models/share", defaults.settings_models_share),
    path("api/settings/models/sent", defaults.settings_models_sent),
    path("api/settings/models/keys", defaults.settings_models_keys),
    path("api/models/vote", defaults.models_vote),
    path("api/settings/signatures", signatures.settings_signatures),
    path("api/settings/google", google.settings_google),
    path("api/settings/google/client", google.save_client),
    path("api/settings/google/client/remove", google.remove_client),
    path("api/settings/google/calendars", google.calendars),
    path("api/settings/google/calendars/add", google.add_calendar),
    path("api/settings/google/calendars/remove", google.remove_calendar),
    path("auth/google/start", google.start),
    path("auth/google/callback", google.callback),
    path("auth/google/disconnect", google.disconnect),
    path("api/settings/mailboxes", mailboxes.settings_mailboxes),
    path("api/settings/mailboxes/disconnect", mailboxes.disconnect),
    path("auth/mailbox/start", mailboxes.start),
    path("api/brief/ghosts", mailboxes.brief_ghosts),
    path("api/brief/ghosts/mark", mailboxes.brief_ghosts_mark),
    path("api/brief/ghosts/send", mailboxes.brief_ghosts_send),
    path("api/brief/mail/message", mailboxes.brief_mail_message),

    # --- Apple Contacts: each person's own iCloud address book ---------------------------
    path("api/settings/apple", apple.settings_apple),
    path("api/settings/apple/sync", apple.sync_now),
    path("api/settings/apple/disconnect", apple.disconnect),
    path("api/people/<str:person_id>/photo", people.photo),
    path("api/people/<str:person_id>/addresses", people.addresses),
    path("api/people/<str:person_id>/addresses/silo", people.address_silo),
    path("api/settings/profile", profile.settings_profile),
    path("api/settings/profile/password", profile.password),
    path("api/settings/my-card", mycard.settings_my_card),
    path("api/settings/my-card/search", mycard.search),
    path("api/settings/my-card/emails", mycard.emails),
    path("api/settings/telegram-account", telegram_account.settings_telegram_account),
    path("api/settings/telegram-account/code", telegram_account.code),
    path("api/settings/telegram-account/password", telegram_account.password),
    path("api/settings/telegram-account/disconnect", telegram_account.disconnect),

    # --- new mail, handed to Rouh the moment it arrives ------------------------------------
    path("api/settings/mail-alerts", mail_alerts.settings_alerts),
    path("api/settings/mail-alerts/on", mail_alerts.turn_on),
    path("api/settings/mail-alerts/off", mail_alerts.turn_off),
    path("api/settings/mail-alerts/topic", mail_alerts.topic),
    path("settings/mail-alerts/log", mail_alerts.decision_log),
    # Google's Pub/Sub posting a note that an inbox changed. No sign-in: the
    # token is the credential (`gate.py`, `rouh/mail_alerts.py`).
    path("hooks/gmail/<str:token>", mail_alerts.gmail_push),
    # Stripe's events, checked against the signing secret kept for the address.
    path("hooks/stripe/<str:token>", payments.stripe_event),
    # Trusted contacts, and each trusted contact's email as a case Petar
    # decides on (`rouh/web/trusted.py`, `rouh/mail_cases.py`).
    path("api/settings/trusted", trusted.trusted_contacts),
    path("api/settings/trusted/find", trusted.find),
    path("api/settings/grants", trusted.grants_panel),
    path("api/mail/approvals", trusted.approvals),
    path("api/mail/case/<str:key>", trusted.case_api),
    path("mail/not-arrived/<str:key>", not_arrived_web.open_it),
    path("mail/away-after/<str:key>", away_after_web.open_it),
    path("mail/new-number/<str:key>", new_number_web.add_it),
    path("mail/renewal/<str:key>", renewal_web.open_it),
    path("mail/case/<str:key>", trusted.case),
    path("mail/case/<str:key>/trace", trusted.case_trace),
    path("mail/case/<str:key>/request/<int:request_id>", trusted.case_request),
    path("mail/case/<str:key>/ask", trusted.case_ask),
    path("mail/case/<str:key>/file/<str:file_id>", trusted.case_file),
    path("mail/case/<str:key>/file/<str:file_id>/page/<int:page>", trusted.case_file),
    path("mail/case/<str:key>/attachment/<str:part>", trusted.case_attachment),
    path("mail/case/<str:key>/fixes", trusted.case_fixes),
    path("mail/case/<str:key>/state", trusted.case_state),
    path("mail/case/<str:key>/fix/<int:fix_id>/<str:act>", trusted.case_fix),

    # --- every rule Rouh follows: the Rules page (`rouh/web/rules.py`) ------------------
    path("api/rules", rules.page),
    path("api/rules/add", rules.add),
    path("api/rules/edit", rules.edit),
    path("api/rules/delete", rules.delete),
    path("api/rules/enable", rules.enable),
    path("api/rules/switch", rules.switch),
    path("api/rules/group", rules.group),
    path("api/rules/restore", rules.restore),
    path("api/rules/history", rules.history),
    path("api/rules/apply", rules.apply),
    path("api/rules/useful", rules.useful),
    path("api/rules/standard", rules.standard),
    path("api/rules/targets", rules.targets),
    path("api/rules/told", rules.told),
    # --- the person's Vocabulary in Synapse Master: its page (`rouh/web/vocabulary.py`) -------
    path("api/vocabulary", vocabulary.page),
    path("api/vocabulary/add", vocabulary.add),
    path("api/vocabulary/edit", vocabulary.edit),
    path("api/vocabulary/delete", vocabulary.delete),
    # What every agent Rouh starts is told first: the Agent instructions page
    # (`rouh/web/agent_instructions.py`).
    path("api/agent-instructions", agent_instructions_web.page),
    path("api/agent-instructions/add", agent_instructions_web.add),
    path("api/agent-instructions/preview", agent_instructions_web.preview),
    path("api/agent-instructions/issued", agent_instructions_web.issued),
    # Reminders and goals (`rouh/web/clock.py`).
    path("api/reminders", clock.reminders_list),
    path("api/reminders/save", clock.reminders_save),
    path("api/reminders/act", clock.reminders_act),
    path("api/reminders/read", clock.reminders_read),
    path("api/goals", clock.goals_list),
    path("api/goals/save", clock.goals_save),
    path("api/goals/step", clock.goals_step),
    path("api/goals/revise", clock.goals_revise),
    # The heartbeat (`rouh/web/heartbeat.py`).
    path("api/job-requests", views.job_requests),
    path("api/heartbeat", heartbeat.page),
    path("api/heartbeat/act", heartbeat.act),
    path("api/heartbeat/answer", heartbeat.answer_one),
    path("api/heartbeat/approvals", heartbeat.approvals),
    path("api/heartbeat/work", heartbeat.work),
    path("api/heartbeat/beats", heartbeat.beats),
    path("api/heartbeat/beats/<int:ident>", heartbeat.one_beat),
    # Decisions: everything waiting on the person, from every source (`rouh/web/decisions.py`).
    path("api/decisions", decisions.listing),
    path("api/decisions/<int:ident>", decisions.one),
    # By its number, the only name a decision has (`rouh/decision_numbers.py`).
    re_path(r"^api/decisions/at/(?P<ref>\d+)$", decisions.at),
    path("api/decisions/<int:ident>/act", decisions.act),
    re_path(r"^api/decisions/of/(?P<source>[a-z]+)/(?P<source_id>.+)$", decisions.of_source),
    # Your part: the hands-on things only the person can do (`rouh/web/actions.py`).
    path("api/actions", actions_web.listing),
    re_path(r"^api/actions/at/(?P<ref>\d+)$", actions_web.at),
    path("api/actions/<int:ident>/act", actions_web.act),
    # The quests the heartbeat carries (`rouh/web/quests.py`).
    path("api/quests", quests.listing),
    path("api/quests/<int:number>", quests.page),
    path("api/quests/<int:number>/act", quests.act),
    path("api/quests/<int:number>/ledger", quests.ledger),
    # Receipts: every receipt and invoice in the mail, by month (`rouh/web/receipts.py`).
    path("api/receipts", receipts.listing),
    path("api/receipts/zip", receipts.bundle),
    path("api/receipts/file", receipts.one_file),
    # Thoughts: the person's own thoughts, in their words (`rouh/web/thoughts.py`).
    path("api/thoughts", thoughts.listing),
    path("api/thoughts/new", thoughts.add),
    path("api/thoughts/<int:ident>", thoughts.one),
    path("api/thoughts/<int:ident>/archive", thoughts.archive),
    path("api/thoughts/<int:ident>/link", thoughts.link),
    path("api/thoughts/<int:ident>/enrich", thoughts.enrich),
    # The box: what the person keeps from the model, sealed (`rouh/web/boxes.py`).
    path("api/box", boxes.listing),
    path("api/box/new", boxes.add),
    path("api/box/<int:ident>", boxes.one),
    path("api/box/<int:ident>/delete", boxes.delete),
    # Payments: the card vault and Stripe (`rouh/web/payments.py`).
    path("api/settings/services", services.page),
    path("api/settings/services/state", services.state),
    path("api/settings/services/delete", services.delete),
    # Anatomy's status board: what needs attention in each of its groups (`rouh/web/anatomy.py`).
    path("api/anatomy", anatomy_web.board),
    path("api/settings/stats", stats.page),
    path("api/settings/stats/events", stats.event_log),
    path("api/nav/tap", stats.tap),
    path("api/events", stats.take),
    path("api/payments", payments.page),
    path("api/payments/card", payments.card),
    path("api/payments/card/delete", payments.card_delete),
    path("api/payments/card/silo", payments.card_silo),
    path("api/payments/card/caps", payments.card_caps),
    path("api/payments/card/entity", payments.card_entity),
    path("api/payments/entity", payments.entity),
    path("api/payments/entity/delete", payments.entity_delete),
    path("api/payments/charge/void", payments.charge_void),
    path("api/payments/charge/paid", payments.charge_paid),
    path("api/payments/stripe", payments.stripe_key),
    path("api/payments/stripe/delete", payments.stripe_delete),
    path("api/payments/webhook", payments.webhook),
    # Shipping options in the person's favourite order (`rouh/web/shipping.py`).
    path("api/shipping", shipping.page),
    path("api/shipping/option", shipping.option),
    path("api/shipping/option/delete", shipping.option_delete),
    path("api/shipping/option/active", shipping.option_active),
    path("api/shipping/order", shipping.order),
    path("api/shipping/move", shipping.move),
    path("api/shipping/situation", shipping.situation),
    path("api/shipping/situation/delete", shipping.situation_delete),
    path("api/shipping/recipient", shipping.recipient),
    # Sign-ups the person authorized the live browser to make (`rouh/web/signups.py`).
    path("api/settings/signups", signups.page),
    path("api/settings/signups/allow", signups.allow),
    path("api/settings/signups/password", signups.password),
    path("api/settings/signups/withdraw", signups.withdraw),
    # The emails the person changed before Send, recorded (`rouh/web/draftedits.py`).
    path("api/settings/draft-edits", draftedits.page),
    # Cloudflare's API tokens, one a zone, typed in and sealed (`rouh/web/cloudflare.py`).
    # Meta, Changes: this Rouh's code, its undo points and its protected core (`rouh/web/changes.py`).
    path("api/settings/changes", changes_web.page),
    path("api/settings/changes/undo", changes_web.undo),
    # Connections, Phone: the address on the relay, on or off, and the phone's sign-in (`rouh/web/relay.py`).
    path("api/settings/phone", relay_web.page),
    path("api/settings/phone/on", relay_web.turn_on),
    path("api/settings/phone/off", relay_web.turn_off),
    path("api/settings/phone/claim", relay_web.claim),
    path("api/settings/phone/signin", relay_web.signin),
    path("api/settings/cloudflare", cloudflare.page),
    path("api/settings/cloudflare/token", cloudflare.token),
    path("api/settings/cloudflare/check", cloudflare.check),
    path("api/settings/cloudflare/remove", cloudflare.remove),
    path("api/settings/cloudflare/zone", cloudflare.zone),
    path("api/settings/cloudflare/zone/forget", cloudflare.zone_forget),
    # Rouh's own Slack app: its three tokens, typed in and sealed (`rouh/web/slack.py`).
    path("api/settings/slack", slack_web.page),
    path("api/settings/slack/tokens", slack_web.tokens),
    path("api/settings/slack/check", slack_web.check),
    path("api/settings/slack/remove", slack_web.remove),
    # Philips Hue through its cloud: the organisation's Hue app, and each person's sign-in to
    # their own Hue account and its bridge (`rouh/web/hue.py`).
    path("api/settings/hue", hue_web.page),
    path("api/settings/hue/app", hue_web.save_app),
    path("api/settings/hue/app/remove", hue_web.remove_app),
    path("api/settings/hue/check", hue_web.check),
    path("api/settings/hue/link", hue_web.link),
    path("api/settings/hue/disconnect", hue_web.disconnect),
    path("auth/hue/start", hue_web.start),
    path("auth/hue/callback", hue_web.callback),
    # A Dreame robot vacuum through the Dreamehome cloud: each person's own Dreamehome account, and
    # the robot for the Home page (`rouh/web/dreame.py`).
    path("api/settings/dreame", dreame_web.page),
    path("api/settings/dreame/connect", dreame_web.connect),
    path("api/settings/dreame/check", dreame_web.check),
    path("api/settings/dreame/answer", dreame_web.answer_check),
    path("api/settings/dreame/cancel", dreame_web.cancel),
    path("api/settings/dreame/disconnect", dreame_web.disconnect),
    path("api/home/vacuum", dreame_web.vacuum),
    # The Home page's lights: the whole home, and one press (`rouh/web/home.py`).
    path("api/home/lights", home_web.lights),
    # The account's silos and the source rules that label things with them (`rouh/web/silos.py`).
    path("api/settings/silos", silos_web.page),
    path("api/settings/silos/add", silos_web.add),
    path("api/settings/silos/change", silos_web.change),
    path("api/settings/silos/move", silos_web.move),
    path("api/settings/silos/remove", silos_web.remove),
    path("api/settings/silos/rule", silos_web.rule),
    # Shared genes from a registry, and the lab they arrive in (`rouh/web/genes.py`).
    path("api/settings/genes", genes_web.page),
    path("api/settings/genes/registry", genes_web.registry),
    path("api/settings/genes/registry/forget", genes_web.registry_forget),
    path("api/settings/genes/check", genes_web.check),
    path("api/settings/genes/install", genes_web.install),
    path("api/settings/genes/switch", genes_web.switch),
    path("api/settings/genes/update", genes_web.update),
    path("api/settings/genes/remove", genes_web.remove),
    path("api/settings/genes/lab", genes_web.lab),
    path("api/settings/genes/file", genes_web.file),
    path("api/settings/genes/nav", genes_web.nav),
    # The morning brief (`rouh/web/brief.py`).
    path("api/brief", brief.brief_today),
    path("api/brief/make", brief.brief_make),
    path("api/brief/one-thing", brief.brief_one_thing),
    path("api/brief/refactoring/<int:number>/undo", brief.brief_refactor_undo),
    path("api/brief/event", brief.brief_event),
    path("api/brief/contacts", brief.brief_contacts),
    path("api/brief/birthday/link", brief.brief_birthday_link),
    path("api/brief/event/answer", brief.brief_event_answer),
    path("api/brief/event/prep", brief.brief_event_prep),
    path("api/brief/event/raise", brief.brief_event_raise),
    path("api/brief/event/raise/correct", brief.brief_event_raise_correct),
    path("api/brief/calendar", brief.brief_calendar),
    path("api/brief/past", brief.brief_past),
    path("api/brief/history/topics", brief.brief_history_topics),
    path("api/brief/slack/dismiss", brief.brief_slack_dismiss),
    path("api/brief/owed", brief.brief_owed),
    path("api/brief/no_notes", brief.brief_no_notes),
    path("api/brief/others_changed", brief.brief_others_changed),
    path("api/brief/shared_with_you", brief.brief_shared_with_you),
    path("api/brief/not_opened", brief.brief_not_opened),
    path("api/brief/new_comments", brief.brief_new_comments),
    path("api/brief/talk_deck", brief.brief_talk_deck),
    path("api/brief/not_handed", brief.brief_not_handed),
    path("api/brief/task_dates", brief.brief_task_dates),
    path("api/brief/my_word", brief.brief_my_word),
    path("api/brief/answer_waiting", brief.brief_answer_waiting),
    path("api/brief/flight_open", brief.brief_flight_open),
    path("api/brief/invite_missing", brief.brief_invite_missing),
    path("api/brief/no_place", brief.brief_no_place),
    path("api/brief/not_said_yes", brief.brief_not_said_yes),
    path("api/brief/not_answered", brief.brief_not_answered),
    path("api/brief/gone_quiet", brief.brief_gone_quiet),
    path("api/brief/raise_attached", brief.brief_raise_attached),
    path("api/brief/next_meeting", brief.brief_next_meeting),
    path("api/brief/day/<str:day>", brief.brief_day),
    path("api/settings/brief", brief.settings_brief),
    # Rouh offline: this device's copy, a part at a time, and the one outbox (`rouh/web/offline.py`).
    path("api/offline/pack/<str:part>", offline.pack),
    path("api/offline/outbox", offline.outbox),
    # A task's status and summary from outside Rouh, with a key (`rouh/web/taskapi.py`).
    path("api/task", taskapi.api_task),

    # --- this machine's own callers --------------------------------------------------
    path("internal/crew-event", views.crew_event),
    path("internal/outbox", views.outbox_note),
    path("internal/nightly", views.nightly_tool),
    path("internal/casefix", views.case_fix_tool),
    path("internal/refactoring", views.refactor_tool),
    path("internal/jobtools", views.job_tools_tool),
    path("internal/task", taskapi.internal_task),
    # The list of files, for a job, a run or a terminal (`rouh/web/filesapi.py`, `bin/rouh-files`).
    path("internal/files", filesapi.internal_files),
    path("internal/incubator", incubator_web.internal),
    path("internal/trials", trials_web.internal),
    path("internal/objecttree", objecttreeapi.internal_objecttree),
    path("internal/agent-instructions", agent_instructions_web.internal),
    path("internal/boxes/collect", boxes.collect),
    path("internal/boxes/shredded", boxes.shredded),
    path("internal/wipe-test-jobs", views.wipe_test_jobs),
    path("internal/phone", phoneapi.internal_phone),

    # --- managing accounts ----------------------------------------------------------------
    path("admin/", admin.site.urls),

    # --- the one page, at every address it is drawn at --------------------------------
    path("", views.index),
    path("one/", views.index),
    # The one program's own pages, through Rouh, where no nginx sends them to it (the containers,
    # `rouh/onebridge.py`); 404 where it is not set up, which nginx never lets reach here anyway.
    re_path(r"^one/(?P<rest>.+)$", onebridge.http),
    path(addressing.BROWSER.lstrip("/"), views.index),
    path(addressing.BROWSER.lstrip("/") + "/", browser_with_a_slash),
    path(addressing.WEB.lstrip("/"), views.index),
    path(addressing.CLOCKWORK.lstrip("/"), views.index),
    # Clockwork's address until 8 October 2026, which links on phones and in chats still name.
    path(addressing.REMINDERS_OLD.lstrip("/"), clockwork_old_address),
    path(addressing.GOALS.lstrip("/"), views.index),
    # Gene therapy: the page with its drawer open, and its address while it was Feedback.
    path(addressing.GENE_THERAPY.lstrip("/"), views.index),
    path(addressing.GENE_THERAPY_OLD.lstrip("/"), gene_therapy_old_address),
    path(addressing.CONTROL.lstrip("/"), views.index),
    path(addressing.SYNAPSE.lstrip("/"), views.index),
    re_path(r"^" + addressing.SYNAPSE.lstrip("/") + r"/[0-9a-f-]{36}$", views.index),
    # The attempts to make Synapse better, and one of them (`rouh/synapse/improvements.py`).
    re_path(r"^" + addressing.SYNAPSE.lstrip("/") + r"/improvements(/\d+)?$", views.index),
    # The person's Vocabulary (`rouh/vocabulary.py`, `rouh/web/vocabulary.py`).
    re_path(r"^" + addressing.SYNAPSE.lstrip("/") + r"/vocabulary$", views.index),
    # A dataset's Dreams page, one night on it, and what waits (`rouh/synapse/dreaming.py`).
    re_path(r"^" + addressing.SYNAPSE.lstrip("/") + r"/[0-9a-f-]{36}/dreams(?:/(?:\d+|waiting))?$", views.index),
    # Metabolism, every run, on its everyday work or its mutations, and its address
    # while it was Runs.
    path(addressing.METABOLISM.lstrip("/"), views.index),
    re_path(r"^" + addressing.METABOLISM.lstrip("/") + r"/(?:everyday|mutations)$", views.index),
    path(addressing.RUNS_OLD.lstrip("/"), metabolism_old_address),
    re_path(r"^" + addressing.RUNS_OLD.lstrip("/") + r"/(?P<tab>everyday|mutations)$",
            metabolism_old_address),
    path(addressing.BRIEF.lstrip("/"), views.index),
    # Every brief kept, and one of them by its day (`rouh/web/brief.py`).
    re_path(r"^" + addressing.BRIEF.lstrip("/") + r"/(?:past|\d{4}-\d{2}-\d{2})$", views.index),
    path(addressing.HEARTBEAT.lstrip("/"), anatomy_web.old_address),
    path(addressing.QUESTS.lstrip("/"), views.index),
    path(addressing.DECISIONS.lstrip("/"), views.index),
    # One in focus, by its number (`rouh/decision_numbers.py`).
    re_path(r"^" + addressing.DECISIONS.lstrip("/") + r"/\d+$", views.index),
    # Your part, and one action by its number (`rouh/actions.py`).
    path(addressing.ACTIONS.lstrip("/"), views.index),
    re_path(r"^" + addressing.ACTIONS.lstrip("/") + r"/\d+$", views.index),
    re_path(r"^" + addressing.QUESTS.lstrip("/") + r"/\d+$", views.index),
    path(addressing.RECEIPTS.lstrip("/"), views.index),
    path(addressing.HOME.lstrip("/"), views.index),
    path(addressing.AGENT_INSTRUCTIONS.lstrip("/"), views.index),
    # The Rules page, and one of its groups or its What Rouh was told (`addressing.RULES`).
    path(addressing.RULES.lstrip("/"), views.index),
    re_path(r"^" + addressing.RULES.lstrip("/") + r"/[a-z]{2,20}$", views.index),
    path(addressing.MAIL_APPROVALS.lstrip("/"), views.index),
    # A task's or a step's sources, by its folder; with none, the task browser.
    path(addressing.SOURCES.lstrip("/"), sources_without_a_task),
    re_path(r"^" + addressing.SOURCES.lstrip("/") + r"/(?P<rest>.+)$", views.index),
    # Evolution's three pages: Parameters; Mutations, its views and one gene (with the old views'
    # and the morning deck's addresses, which the page sends on); and the Gene Pool and one family
    # of it. And Mutations' address while it was the
    # Gene library, with the Pool one of its views, sent on to where each is now.
    path(addressing.EVOLUTION.lstrip("/"), views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/") + r"/(?:parameters|mutations|pool|incubator|nightly|trials|trials/problems)$", views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/") + r"/trials/(?:\d{1,6}|job/\d{1,6}|problem/\d{1,6}|testers|testers/new"
            r"|tester/[a-z0-9]{1,40}(?:/edit)?|how)$", views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/") + r"/incubator/(?:INC-)?\d{1,6}$", views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/")
            + r"/mutations/(?:new|trial|passed|failed|unused|month|out|review|rouh|off|rejected|week|deck|log|log/\d+"
            + r"|gene/\d+(?:/(?:essence|trial|versions|history|card|mutations|decisions|questions|learning))?)$",
            views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/") + r"/pool/(?:[0-9a-f]{1,16}|yours|yours/\d+|outgoing|outgoing/\d+|incoming)$", views.index),
    re_path(r"^" + addressing.EVOLUTION.lstrip("/") + r"/library(?P<rest>/.*)?$",
            evolution_library_old_address),
    path(addressing.THOUGHTS.lstrip("/"), views.index),
    path(addressing.BOX.lstrip("/"), views.index),
    # One box in focus, by its number.
    re_path(r"^" + addressing.BOX.lstrip("/") + r"/\d+$", views.index),
    # One thought in focus, by its number.
    re_path(r"^" + addressing.THOUGHTS.lstrip("/") + r"/\d+$", views.index),
    path(addressing.OFFLINE.lstrip("/"), views.index),
    # A quest's page by its record, as long-running work was addressed for its first day.
    path(addressing.WORK.lstrip("/") + "/<int:ident>", quests.old_address),
    # Anatomy (`rouh/web/anatomy.py`): its status board, each of its groups' pages, and a
    # section of one, the page scrolled to it, all from the gene manifests (`genes.anatomy`).
    # A section moved to another group has no old address (`genes.MOVED`), with one exception:
    # rouh.land's own return address, which rouh.land's site has written into it
    # (`addressing.ROUH_LAND_RETURN`), answered only when rouh.land sends a code back on it.
    path(addressing.ROUH_LAND_RETURN.lstrip("/"), anatomy_web.rouh_land_return),
    path(addressing.ANATOMY.lstrip("/"), views.index),
    re_path(r"^" + addressing.ANATOMY.lstrip("/") + r"/(?:" + "|".join(genes.ANATOMY_IDS) + r")$", views.index),
    *[path(_section(name), views.index) for name in genes.SECTIONS],
    # Services was Meta's for a day, until 15 October 2026, when Petar put it in Money beside
    # Payments: a link from that day lands where it is now.
    path(addressing.ANATOMY.lstrip("/") + "/meta/services", anatomy_web.old_address, {"rest": "services"}),
    # One trusted contact, opened from the list in its section, or the grants they can be given.
    re_path(r"^" + _section("trusted-contacts") + r"/(?:\d+|grants)$", views.index),
    # The beats filtered to one piece of work, or to the heartbeat's own.
    re_path(r"^" + _section("beats") + r"/(?:\d+|heartbeat)$", views.index),
    # The heartbeat's settings, a view of its own beside Today and the beats (`heartbeatpage.js`).
    path(_section("heartbeat") + "/settings", views.index),
    # Stats' Event log tab (`statspage.js`).
    path(_section("stats") + "/events", views.index),
    # One shared gene's page, by its registry id, <publisher>/<name> (`genespage.js`).
    re_path(r"^" + _section("gene-pool") + r"/[a-z0-9][a-z0-9_-]{0,62}/[a-z][a-z0-9-]{1,62}$", views.index),
    # Settings' addresses until 14 October 2026, and the heartbeat's own for a day before that,
    # each sent on to the section it named (`anatomy.old_address`).
    path(addressing.SETTINGS.lstrip("/"), anatomy_web.old_address),
    re_path(r"^" + addressing.SETTINGS.lstrip("/") + r"/(?P<rest>.+)$", anatomy_web.old_address),
    *[re_path(r"^" + kind + r"/(?P<rest>.*)$", views.index) for kind in addressing.KINDS],
]
