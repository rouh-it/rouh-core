"""Every table Rouh keeps, as Django models, in PostgreSQL.

Until 23 September 2026 these were SQLite tables each store made for itself
with `CREATE TABLE IF NOT EXISTS` and grew with `ALTER TABLE` when it found a
column missing. They are one schema now, made and changed by Django's
migrations (`rouh/migrations/`), and every table keeps the name it had, so the
history each store tells about its own tables still reads true.

The stores themselves - `memory.py`, `objects.py`, `crew.py` and the rest -
still own what their rows mean. These files only say what the rows are.
"""
from .agents import (AgentInstruction, AgentInstructionChange, AgentInstructionGroup,
                     AgentInstructionIssue)
from .accounts import (DEFAULT_ORG_ID, DEFAULT_ORG_NAME, Handover, Organisation,
                       SignInFailure, User)
from .evolution import EvolutionSetting, GeneMutation, GeneQuestion, MutationsGene, MutationsGeneEvent
from .incubator import IncubatorEvent, IncubatorIdea
from .trials import Trial, TrialJob, TrialNote, TrialProblem, TrialSighting, TrialStep, TrialTester
from .genelog import (GeneEval, GeneLogCommit, GeneLogEvent, GeneLogGene, GeneMark, GeneUseDaily,
                      PoolMembership)
from .birth import RouhBirth, RouhNickname
from .files import File, FileOwner, FileVersion
from .signin import Passkey, SignInEmail, SignInLink
from .prompt_parts import PromptPart
from .llmlog import LLMPiece, LLMRequest
from .memory import (AppState, ChatFolder, Event, Fact, LegacySession, OpenTurn,
                     RecallTimeline, RouteTimeline, ScreenCard, Spend, ToolLine, TranscriptMessage, TurnRecord)
from .objects import (Artifact, ArtifactVersion, Chat, ChatFork, ChatMessage, ContentFile,
                      Link, ObjectRow, Project, Run, SubtaskNote, Task, TaskAnswer, TaskChange,
                      TaskToken, TelegramFork,
                      TelegramReply, UploadedFile)
from .rest import (AppleConnection, AskEdit, AskMessage, AskThread,
                   BirthdayLink, BrowserLogins, CloudflareZone, CrewEvent, Crewmate, CrewTreeEvent,
                   FeatureRequest, Feedback, FeedbackBoard, FeedbackFile, GmailPush, JobRequest, RunWords,
                   CardCharge, Decision, DecisionEvent, DecisionGate, DraftEdit, HeartbeatApproval, HeartbeatBeat, HeartbeatState, LongWork,
                   LongWorkLedger, BillingEntity, PaidService, PaymentCard, PaymentSettings, SignupGrant, StripeLink,
                   ShippingOption, ShippingSituation,
                   FeatureSwitch, GeneLabEvent, GeneRegistry, NightlyFeatureNight, NightlyFeatureService,
                   NightlyRefactorNight,
                   SharedGene,
                   GoogleClient, GoogleConnection, GoogleOAuthState, MailAlert,
                   MailAlertSeen, ModelDefaults, ModelDouble, ModelOutcome, ModelProviderKey, ModelVote, MorningBrief, NavTap, Notice, OfflineAction, PageComment, PageCommentMessage,
                   PageDefinition, PageGuest, PageHighlight, PageRead, PageSourceCheck, PageState,
                   PageOption, PagePlace, PublicPage, ShareEnd, ReadMailbox, GhostMark, Reminder,
                   RequesterShare, TelegramAccount, Thought, Box, BoxHandover,
                   UserSetting, WorkerNote)
from .silos import Silo, SiloRule
from .demo import DemoApproval, DemoEvent, DemoState
from .dreame import DreameConnection
from .hue import HueApp, HueConnection
from .youtube import YouTubeTranscript
from .slack import (SlackConnection, SlackConversation, SlackMessage, SlackPerson, SlackPromise,
                    SlackTaskDecision, SlackTaskLink)
from .trust import (CapabilityGrant, CapabilityGrantEvent, CapabilityUse, ContactGrant, ContactGroup, DelegateAct, Grant, GrantVersion,
                    InboxRead, MailApproval, MailAsk, MailCase, MailCaseAttempt, MailCaseDryRun,
                    MailCaseEvent, MailCaseFix, MailCaseNote,
                    MailCaseTrace, MailOutbox, TelegramLink, TrustedAddress,
                    TrustedContact)

__all__ = [
    "IncubatorEvent", "IncubatorIdea",
    "Trial", "TrialJob", "TrialNote", "TrialProblem", "TrialSighting", "TrialStep", "TrialTester",
    "DemoApproval", "DemoEvent", "DemoState",
    "CapabilityGrant", "CapabilityGrantEvent", "CapabilityUse",
    "AgentInstruction", "AgentInstructionChange", "AgentInstructionGroup", "AgentInstructionIssue",
    "DEFAULT_ORG_ID", "DEFAULT_ORG_NAME", "Handover", "Organisation", "SignInFailure", "User",
    "EvolutionSetting", "GeneMutation", "GeneQuestion", "MutationsGene", "MutationsGeneEvent",
    "GeneEval", "GeneLogCommit", "GeneLogEvent", "GeneLogGene", "GeneMark", "GeneUseDaily",
    "PoolMembership",
    "RouhBirth", "RouhNickname",
    "Passkey", "SignInEmail", "SignInLink",
    "PromptPart",
    "LLMPiece", "LLMRequest",
    "AppState", "ChatFolder", "Event", "Fact", "LegacySession", "OpenTurn", "RecallTimeline", "RouteTimeline", "ScreenCard",
    "Spend", "ToolLine", "TranscriptMessage", "TurnRecord",
    "Artifact", "ArtifactVersion", "Chat", "ChatFork", "ChatMessage", "ContentFile", "Link",
    "ObjectRow", "Project", "Run", "SubtaskNote", "Task", "TaskAnswer", "TaskChange", "TaskToken",
    "TelegramFork", "TelegramReply",
    "UploadedFile",
    "AppleConnection", "AskEdit", "AskMessage", "AskThread", "BirthdayLink",
    "BrowserLogins", "CloudflareZone",
    "CrewEvent", "Crewmate", "CrewTreeEvent", "FeatureRequest", "Feedback",
    "FeedbackBoard", "FeedbackFile", "GmailPush", "GoogleClient",
    "CardCharge", "DraftEdit", "FeatureSwitch", "GeneLabEvent", "GeneRegistry", "SharedGene", "NightlyFeatureNight", "NightlyFeatureService", "NightlyRefactorNight", "Decision", "DecisionEvent", "DecisionGate", "Notice", "HeartbeatApproval", "JobRequest", "RunWords", "HeartbeatBeat", "HeartbeatState", "LongWork",
    "LongWorkLedger", "BillingEntity", "PaidService", "PaymentCard", "PaymentSettings", "SignupGrant", "StripeLink",
    "ShippingOption", "ShippingSituation",
    "GoogleConnection", "GoogleOAuthState",
    "MailAlert", "MailAlertSeen", "ModelDefaults", "ModelDouble", "ModelOutcome", "ModelProviderKey", "ModelVote", "MorningBrief", "NavTap", "OfflineAction", "PageComment",
    "PageCommentMessage", "PageDefinition", "PageGuest", "PageHighlight", "PageRead", "PageSourceCheck", "PageState",
    "PageOption", "PagePlace", "PublicPage", "ShareEnd", "ReadMailbox", "GhostMark", "Reminder",
    "RequesterShare", "TelegramAccount", "Thought", "Box", "BoxHandover",
    "UserSetting", "WorkerNote",
    "Silo", "SiloRule",
    "DreameConnection",
    "HueApp", "HueConnection",
    "YouTubeTranscript",
    "SlackConnection", "SlackConversation", "SlackMessage", "SlackPerson", "SlackPromise",
    "SlackTaskDecision", "SlackTaskLink",
    "ContactGrant", "ContactGroup", "DelegateAct", "Grant", "GrantVersion",
    "InboxRead", "MailApproval", "MailAsk", "MailCase", "MailCaseAttempt", "MailCaseDryRun", "MailCaseEvent", "MailCaseFix", "MailCaseNote", "MailCaseTrace", "MailOutbox", "TelegramLink", "TrustedAddress",
    "TrustedContact",
]
