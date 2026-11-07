"""Trials' tables (`rouh/trials/`): a made-up person tries a change the way a real one would, and
every moment they trip on is kept on one list of problems.

Petar, 4 November 2026: "Rouh is bad at human usability." Every row carries `org_id` and `user_id`,
and every query names both.
"""
from django.db import models


class Trial(models.Model):
    """One try: one persona, one goal, one fresh tester, from the first screen to the ending."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its number in this person's list of trials, shown as "Trial <number>".
    number = models.IntegerField()
    #: The persona's file name in `rouh/trials/personas/`, such as "vesela".
    persona = models.TextField()
    #: What the persona is trying to do, in one sentence in their own words.
    goal = models.TextField()
    #: What was tried, in a few plain words, such as "the Trials page".
    subject = models.TextField(blank=True, default="")
    #: The gene the change belongs to, when it is one gene's, and the address it began at.
    gene = models.TextField(blank=True, default="")
    page = models.TextField(blank=True, default="")
    #: 1 for the first try, 2 and 3 for the tries after a round of fixes.
    round = models.IntegerField(default=1)
    #: The first try of the same goal, when this one is a try after fixes.
    first_id = models.BigIntegerField(null=True, blank=True)
    #: queued (a run is on its way to it), running, passed, failed or broken (it could not finish).
    state = models.TextField(default="queued")
    #: yes, partly or no, at the end.
    managed = models.TextField(blank=True, default="")
    #: In the persona's own words: where they nearly gave up, and how it went.
    nearly_gave_up = models.TextField(blank=True, default="")
    ending = models.TextField(blank=True, default="")
    steps = models.IntegerField(default=0)
    seconds = models.FloatField(default=0)
    #: How many problems it found, and the reason it is broken when it is.
    problems = models.IntegerField(default=0)
    why = models.TextField(blank=True, default="")
    #: Who started it (a run, a job, the person) and the run doing it.
    by = models.TextField(blank=True, default="")
    run_id = models.TextField(blank=True, default="")
    #: The model that was the tester, as it answered.
    model = models.TextField(blank=True, default="")
    #: The screens it visited, by their address with numbers taken out (`trials.screen_key`).
    screens = models.JSONField(default=list, blank=True)
    #: The job it is a try of (`TrialJob.id`): what was being tested, which every try of it shares.
    job_id = models.BigIntegerField(null=True, blank=True)
    #: auto: a test while a feature is built, fixed by its builder and tried again, at most two rounds, then
    #: shipped, with nobody asked. review: one the owner asked for in their own words ("Have Vesela test
    #: this"): a report to read and discuss, and nothing is fixed until the owner chooses what.
    mode = models.TextField(default="auto")
    created_at = models.FloatField()
    started_at = models.FloatField(null=True, blank=True)
    ended_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "trials"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"], name="trial_number_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "created_at"], name="trial_whose_when")]


class TrialStep(models.Model):
    """One step of one trial: what the persona saw, thought and did, with the screen as it was."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    trial_id = models.BigIntegerField()
    n = models.IntegerField()
    at = models.FloatField()
    #: The address it was on, the screen's key, and its title as the browser showed it.
    url = models.TextField(blank=True, default="")
    screen = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    #: The screenshot's file name in the trial's folder, "" when none was kept.
    shot = models.TextField(blank=True, default="")
    see = models.TextField(blank=True, default="")
    think = models.TextField(blank=True, default="")
    #: What they did, in their words ("I press Run trial"), and as the browser did it.
    does = models.TextField(blank=True, default="")
    action = models.JSONField(default=dict, blank=True)
    #: On a screen new to them, the three answers: {"what", "how", "then", "clear": [bool, bool, bool]}.
    answers = models.JSONField(default=dict, blank=True)
    #: The problems they named at this step: [{"what", "said", "how_bad"}], put on the list at the end.
    found = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "trial_steps"
        constraints = [models.UniqueConstraint(fields=["trial_id", "n"], name="trial_step_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "trial_id"], name="trial_step_whose")]


class TrialProblem(models.Model):
    """One confusing or bad moment, seen once or many times, open until a trial gets past it."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its number in this person's list, shown as "Problem <number>".
    number = models.IntegerField()
    #: The screen's key (`trials.screen_key`) and its name as a person would say it.
    screen = models.TextField(blank=True, default="")
    screen_name = models.TextField(blank=True, default="")
    #: What goes wrong, in one plain line.
    what = models.TextField()
    #: blocked, confused, annoyed or minor: the worst any sighting of it was.
    how_bad = models.TextField(default="minor")
    #: "persona" when a trial found it, "owner" when the owner said it.
    source = models.TextField(default="persona")
    #: The personas who tripped on it (["vesela"]), and the gene it came from first.
    personas = models.JSONField(default=list, blank=True)
    gene = models.TextField(blank=True, default="")
    #: How many times it was seen.
    count = models.IntegerField(default=1)
    #: What the tester expected to happen, what happened instead, and a suggested fix, in plain words.
    expected = models.TextField(blank=True, default="")
    actual = models.TextField(blank=True, default="")
    fix = models.TextField(blank=True, default="")
    #: open or closed (fixed: a passing trial got past it).
    status = models.TextField(default="open")
    #: What the owner made of it, from its discussion: "" (not looked at), not_a_problem, wont_fix,
    #: decided (with `decision`, "fix it like this", which the builder of the next round reads), or sent
    #: (to Gene therapy as feedback, `feedback_id`). Kept apart from `status`, which only a trial changes.
    verdict = models.TextField(blank=True, default="")
    decision = models.TextField(blank=True, default="")
    verdict_at = models.FloatField(null=True, blank=True)
    feedback_id = models.TextField(blank=True, default="")
    closed_at = models.FloatField(null=True, blank=True)
    #: The trial that got past it, or "" when it was closed by hand, with the words why.
    closed_by = models.BigIntegerField(null=True, blank=True)
    closed_note = models.TextField(blank=True, default="")
    first_at = models.FloatField()
    last_at = models.FloatField()

    class Meta:
        db_table = "trial_problems"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"], name="trial_problem_number_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="trial_problem_whose_status")]


class TrialSighting(models.Model):
    """One time one problem was seen: the words said then, and the screenshot, in the trial it was in."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    problem_id = models.BigIntegerField()
    #: The trial and its step, or null for the owner's own words in a chat.
    trial_id = models.BigIntegerField(null=True, blank=True)
    step = models.IntegerField(null=True, blank=True)
    #: The words, exactly as said, and how bad this one was.
    quote = models.TextField()
    how_bad = models.TextField(default="minor")
    source = models.TextField(default="persona")
    persona = models.TextField(blank=True, default="")
    #: The chat the owner said it in, when they did.
    chat = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "trial_sightings"
        indexes = [models.Index(fields=["org_id", "user_id", "problem_id"], name="trial_sighting_problem")]


class TrialTester(models.Model):
    """One made-up person who tries things: their whole profile, as they are told it before every try.

    Petar, 4 November 2026: "I need to be able to see and manage the people testing the software."
    Archived, never deleted, so an old try still says who did it."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Short and lower case, such as "vesela": how a tool, `rouh-trial --persona` and a try name them.
    key = models.TextField()
    name = models.TextField()
    age = models.IntegerField(null=True, blank=True)
    job = models.TextField(blank=True, default="")
    city = models.TextField(blank=True, default="")
    #: One line on who they are.
    short = models.TextField(blank=True, default="")
    #: phone or desk: what they mostly use.
    device = models.TextField(default="phone")
    #: her, him or them.
    them = models.TextField(default="them")
    #: Everything written about them, in Markdown, in the second person ("You are ..."), with a heading a
    #: section: exactly what the tester is told.
    profile = models.TextField(blank=True, default="")
    #: seed (one of the two every Rouh starts with), owner, or rouh (written by Rouh from a sentence).
    made_by = models.TextField(blank=True, default="owner")
    #: When the owner paused them, or null: a paused tester starts no new try of any kind, and stays on the
    #: list and as the one who tries every change (Petar, 5 November 2026).
    paused_at = models.FloatField(null=True, blank=True)
    #: How many tries were skipped because they (or everyone) were paused, and the last time one was.
    skipped = models.IntegerField(default=0)
    skipped_at = models.FloatField(null=True, blank=True)
    archived_at = models.FloatField(null=True, blank=True)
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "trial_testers"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "key"], name="trial_tester_key_once")]


class TrialJob(models.Model):
    """What is being tested: a goal on a screen or feature, tried again and again, often for one gene."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its number in this person's list, shown as "Job <number>".
    number = models.IntegerField()
    #: What it is called, such as "Sign up and sign in for the first time".
    name = models.TextField()
    #: What the tester is asked to do, in one sentence as they would put it.
    goal = models.TextField(blank=True, default="")
    #: What it covers, in a line or two.
    covers = models.TextField(blank=True, default="")
    #: The address it begins at, and the gene it belongs to when it is one gene's.
    page = models.TextField(blank=True, default="")
    gene = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "trial_jobs"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"], name="trial_job_number_once")]


class TrialNote(models.Model):
    """One message in a problem's discussion: the owner's words, or Rouh's answer, or a decision made."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    problem_id = models.BigIntegerField()
    #: owner or rouh.
    who = models.TextField()
    #: said (words in the thread) or verdict (a decision, said in a line).
    kind = models.TextField(default="said")
    text = models.TextField()
    model = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "trial_notes"
        indexes = [models.Index(fields=["org_id", "user_id", "problem_id"], name="trial_note_problem")]
