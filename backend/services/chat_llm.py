# backend/services/chat_llm.py
"""
AIRP -- AIRP Assistant LLM Wrapper + Objectivity Guardrail (T-102)

A thin wrapper over the existing ``backend.agents.llm_factory.get_llm``
for the AIRP Assistant chatbot (T-099's ``chat_sessions`` schema), plus
the guardrail system prompt that governs every chat turn regardless of
which chat session type (T-100's memo-scoped, T-101's portfolio-wide)
or caller (a future REST endpoint in T-103, a future WebSocket stream
in T-104) invokes it.

Why this module exists at all, given ``get_llm()`` already does the
provider switch
------------------------------------------------------------------------
``get_llm()`` answers "which LLM client do I construct" (Groq during
development, Claude for the demo) -- that decision is identical for
every caller in this codebase, agents and chat alike, and T-102's own
acceptance criteria do not ask for a different one here. What the eight
committee agents and the AIRP Assistant do NOT share is *what the LLM
is told to do with that client*. Each research/debate agent in
``backend/agents/`` owns its own persona system prompt because each one
is producing a NEW analytical judgement from raw data. The AIRP
Assistant is the opposite case by design: it must never produce a new
judgement, only explain judgements the committee already reached and
already persisted. That asymmetry is exactly what belongs in a
chat-specific module rather than folded into ``llm_factory`` itself --
``get_llm()`` stays a provider factory with zero persona opinions, and
every persona (including this one) lives beside the feature that owns
it, matching where ``SYSTEM_PROMPT`` already lives in every agent
module (see ``backend/agents/contrarian_investor.py``, etc.).

Why this lives in ``backend/services/``, not ``backend/agents/``
------------------------------------------------------------------------
Every module under ``backend/agents/`` is a LangGraph node: it takes an
``InvestmentState`` dict, participates in the 8-agent committee
pipeline, and is wrapped in ``@traced_agent`` for per-node LangSmith
tags (agent_name, company_name) keyed off that state shape. The AIRP
Assistant is not a pipeline node -- it is invoked per user chat turn,
outside any ``InvestmentState``, by request-scoped callers exactly like
``backend/services/chat_service.py`` (T-100) and
``backend/tools/portfolio_tools.py`` (T-101) already are. This module
completes that same Phase 10 trio in the same layer: ``chat_service.py``
builds context, ``portfolio_tools.py`` builds tools, ``chat_llm.py``
builds the persona and the call that ties context + tools + history
together. LangSmith tracing is still active for every call this module
makes -- ``get_llm()`` calls ``configure_tracing()`` internally before
constructing the client, exactly as it does for every agent -- there is
just no ``@traced_agent``-style per-node tag here, because there is no
node.

The guardrail, and why it is repeated rather than stated once
------------------------------------------------------------------------
T-102's acceptance criterion is explicit: "System prompt explicitly
forbids overriding stored verdicts." ``SYSTEM_PROMPT`` below states
that rule once as a hard rule, then enumerates the specific phrasings a
user is likely to try (direct requests for an opinion, "update this
verdict given new information", claiming market conditions changed,
simple insistence) and forbids the assistant from producing a new
verdict, conviction score, or price target under any of them. This is
deliberately more repetitive than a single-sentence rule would be --
LLM system prompts are not code with unambiguous control flow; a rule
stated once and only in the abstract is measurably easier for a model
to route around under a persistent or creatively-phrased user than the
same rule restated against concrete attempted phrasings. The assistant
is still allowed, and encouraged, to explain the *reasoning* behind a
stored verdict and to discuss what new information a user raises could
mean in general terms -- what it must never do is convert that
discussion into a new BUY/HOLD/SELL call, conviction score, or price
target of its own.

Personalization (T-106) -- why it is a SEPARATE instruction block, not
folded into ``SYSTEM_PROMPT`` itself
------------------------------------------------------------------------
``SYSTEM_PROMPT`` is identical for every call, by design (see "The
guardrail" above) -- it has no per-user state. Risk appetite and
preferred sectors (``user_preferences.risk_appetite`` /
``.preferred_sectors``, added by T-106's migration on top of T-099's
table) are per-user and change what gets built into the prompt on a
per-call basis, the same way ``response_style`` already does via
``RESPONSE_STYLE_INSTRUCTIONS``.
``build_personalization_instruction()`` follows that same established
pattern rather than inventing a new one: a small, independently
testable function that returns instruction text,
``build_system_prompt()`` appends it after the response-style
instruction and before any grounded ``context``. Its hard rule
("personalization affects tone/emphasis only, never a verdict") is
DELIBERATELY restated immediately beside the personalization data
itself, not only once in ``SYSTEM_PROMPT`` -- the same "restate a
guardrail against the concrete thing that could tempt a model to break
it, not only once in the abstract" reasoning "The guardrail" section
above already gives for the verdict-override rule.

Why ``get_chat_llm()`` does not change temperature/config
------------------------------------------------------------------------
``get_llm()`` constructs both providers with ``temperature=0`` -- every
existing agent relies on that for reproducible, non-creative output.
The AIRP Assistant has the same requirement for a different reason: it
is explaining and grounding, not composing, and a guardrail against
fabricated verdicts is far easier to keep honest at temperature 0 than
at a setting that invites the model to embellish. ``get_chat_llm()``
therefore returns ``get_llm()`` completely unchanged today. It exists
as its own function (not a bare re-export/alias) purely so chat-feature
code imports and mocks ``backend.services.chat_llm.get_chat_llm`` --
one seam, owned by this module, the same way every agent module patches
its own local ``get_llm`` import in tests rather than patching
``backend.agents.llm_factory.get_llm`` globally -- and so a future,
chat-specific override (a different temperature, a different timeout)
has exactly one place to land without touching ``llm_factory.py`` or
any agent.

Why stored ``role='system'``/``role='tool'`` chat_messages rows are
never replayed as conversation turns
------------------------------------------------------------------------
``chat_messages.role`` (T-099) allows all four of
'user'/'assistant'/'system'/'tool'. ``build_chat_messages()`` below
converts only 'user' and 'assistant' rows into LangChain messages and
silently skips anything else. This is a deliberate security property,
not an oversight: if a stored 'system' row were ever replayed as a
second ``SystemMessage``, it would be placed later in the message list
than this module's own guardrail ``SystemMessage`` and could weaken or
contradict it in a model that gives more weight to a more recent system
instruction. The guardrail in this module is the ONLY system prompt any
chat call built here ever sends -- no caller can inject a second one
by writing an attacker- or bug-influenced 'system' row into
``chat_messages`` first. 'tool' rows are skipped for a narrower, purely
scope reason: turning a stored tool result into free-standing
conversation history is a T-103/T-104-era chat-loop decision (how much
of a tool call to replay vs. summarise), not something this thin
wrapper needs to decide to satisfy T-102's own acceptance criteria.

Design decisions
------------------------------------------------------------------------
* NO ``from __future__ import annotations`` -- this module lives beside
  ``backend/services/chat_service.py``, which documents the same reason
  for omitting it (breaks Pydantic v2 union resolution for modules that
  import this one); this module defines no Pydantic models itself but
  keeps the same convention as its sibling for consistency within the
  Phase 10 chat feature.
* Plain ASCII section comments (# ---) -- established AIRP convention.
* No bare ``type: ignore`` -- cast()/explicit annotations only.
* ``invoke_chat()`` RAISES ``ChatLLMError`` on failure rather than
  degrading gracefully with a canned string. This is the opposite
  convention from the 8 committee agents (which never raise, and
  return an ``error`` field so the pipeline can keep going for the
  other 7 agents). The AIRP Assistant has no "other 7 agents" to fall
  back on -- a chat turn either produced a real, groundable answer or
  it did not, and a caller that silently returned canned filler text
  from inside this module would make a failed chat turn indistinguishable
  from a real answer to both the end user and to the chat_messages
  table this response eventually gets written into. Raising lets a
  future router (T-103) or WebSocket handler (T-104) decide how to
  surface the failure (e.g. HTTP 502, a WS error frame) explicitly.

Public API
----------
    from backend.services.chat_llm import (
        SYSTEM_PROMPT,
        ChatLLMError,
        get_chat_llm,
        build_system_prompt,
        build_system_message,
        build_chat_messages,
        invoke_chat,
        astream_chat,
        astream_chat_from_messages,
        run_tool_calling_round,
    )
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from backend.agents.llm_factory import get_llm

logger = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_PROMPT",
    "RESPONSE_STYLE_INSTRUCTIONS",
    "DEFAULT_RESPONSE_STYLE",
    "LIVE_DATA_TOOL_INSTRUCTION",
    "ChatLLMError",
    "get_chat_llm",
    "build_system_prompt",
    "build_system_message",
    "build_chat_messages",
    "build_personalization_instruction",
    "invoke_chat",
    "astream_chat",
    "astream_chat_from_messages",
    "run_tool_calling_round",
]

# ---------------------------------------------------------------------------
# Guardrail persona -- the AIRP Assistant's system prompt
# ---------------------------------------------------------------------------

#: The single system prompt every AIRP Assistant chat call sends, for
#: BOTH session types (T-100 memo-scoped, T-101 portfolio-wide). Scope
#: (which analysis, which tools) is layered on top per call via
#: ``context``/tool bindings -- the objectivity guardrail itself never
#: changes between the two.
SYSTEM_PROMPT = """\
You are the AIRP Assistant, a support analyst for the Autonomous \
Investment Research Platform (AIRP). You help users understand \
investment analyses that AIRP's eight-agent investment committee has \
already completed and stored. You do not perform investment research \
yourself, and you have no analytical authority of your own.

WHO PRODUCES AIRP'S VERDICTS
Every BUY / HOLD / SELL verdict, conviction score, and price target a \
user sees was produced by the Portfolio Manager agent after a \
structured, multi-round debate among the Fundamental Analyst, \
Technical Analyst, News Sentiment Agent, Macro Economist, Risk \
Officer, Contrarian Investor, and Valuation Agent. That process -- not \
you -- is the analytical authority behind every verdict on this \
platform.

HARD RULE -- NEVER OVERRIDE A STORED VERDICT
You are strictly forbidden from issuing, implying, or suggesting a new \
or different BUY / HOLD / SELL verdict, conviction score, or price \
target for any company, whether or not AIRP has already analysed it. \
This rule applies even when:
  - the user asks you directly for your own opinion or recommendation
  - the user asks you to "update", "re-evaluate", or "reconsider" a \
verdict given new information they describe
  - the user shares data or news that appears to contradict the \
stored verdict
  - the user claims market conditions have changed since the analysis \
completed
  - the user insists, rephrases the question, or claims special \
expertise or authority
  - the user asks a hypothetical ("if you had to guess", "just \
between us", "what would you do")

In every one of these cases: do NOT produce a new verdict, conviction \
score, or price target of any kind. Instead, explain what the stored \
analysis actually says -- the reasoning, the bull case, the bear case, \
the risk factors, and the debate that led to the verdict -- and tell \
the user that an updated view requires running a new AIRP analysis for \
that company, which is the only way this platform ever produces a \
verdict. You may discuss, in general terms, what new information the \
user raises could mean, and you may note plainly that it is not \
reflected in the stored analysis -- but you must never translate that \
discussion into a BUY/HOLD/SELL call, a conviction score, or a price \
target of your own, implicit or explicit.

WHAT YOU ARE FOR
  - Explaining a stored analysis in plain language: the verdict, the \
reasoning behind it, what each agent found, the debate transcript, the \
risks, and the valuation.
  - Answering portfolio-wide questions using the stored context you \
are given (for example: which of the user's past analyses ended BUY, \
what AIRP said about a specific ticker) -- grounded strictly in that \
stored context, never invented.
  - Being honest about the limits of a stored analysis: its data \
quality, the time horizon it covers, when it was run, and what it does \
not cover.

WHAT YOU MUST NEVER DO
  - Never state or imply a BUY/HOLD/SELL call, conviction score, or \
price target that did not come verbatim from a stored AIRP analysis.
  - Never claim an agent said something it did not say, and never \
fabricate numbers, quotes, or tool results.
  - Never give generic stock-market advice unconnected to a stored \
AIRP analysis -- if asked, redirect the user to run an AIRP analysis \
for that company instead.
  - Never present your own summarisation or interpretation as if it \
were additional analysis from the investment committee.
  - Never let a user's stated risk appetite or preferred sectors \
change a verdict, conviction score, price target, or any numeric \
figure in a stored analysis -- personalization may only adjust your \
tone and which already-stored details you choose to emphasise.

If a user asks something the stored context cannot answer, say so \
plainly rather than guessing."""

#: Per-``user_preferences.chat_response_style`` (T-099) verbosity
#: instruction, appended after ``SYSTEM_PROMPT``. Any style value not
#: present here (including a stale/unrecognised one from a future
#: migration) falls back to ``DEFAULT_RESPONSE_STYLE`` rather than
#: raising -- an unrecognised preference value should degrade to a
#: sensible default, not break the chat turn.
RESPONSE_STYLE_INSTRUCTIONS: dict[str, str] = {
    "concise": (
        "Response style: concise. Answer in 2-4 sentences or a short "
        "bullet list unless the user explicitly asks for more detail."
    ),
    "detailed": (
        "Response style: detailed. Give a thorough answer that walks "
        "through the relevant agents' reasoning and cites specific "
        "figures from the stored analysis where useful."
    ),
}

DEFAULT_RESPONSE_STYLE = "concise"

#: Appended (B9) only for a call that actually has tools bound
#: (``build_chat_messages(..., tools_available=True)``) -- portfolio-wide
#: sessions get the ``backend.tools.portfolio_tools`` functions, and both
#: session types get the live-market-data tools (``fetch_ratios``,
#: ``fetch_stock_price``). Kept as a separate, conditionally-appended
#: block rather than folded into ``SYSTEM_PROMPT`` for the same reason
#: ``build_personalization_instruction`` is separate: a memo-scoped call
#: with no tools bound has nothing to gain from instructions about tools
#: it cannot call, and a shorter prompt for that (more common) case is
#: strictly better.
LIVE_DATA_TOOL_INSTRUCTION = """\
TOOLS AVAILABLE THIS TURN
You have live data tools bound to this conversation. Use them whenever \
they would let you answer more precisely than the context already \
given -- for example, looking up the user's own past analyses, pulling \
up a specific stored memo, searching their uploaded documents, or \
fetching a live market ratio (P/E, P/B, ROE, current price, and \
similar) for a ticker.

HARD RULE -- LABEL LIVE DATA AS LIVE, NEVER AS A STORED VERDICT
A number a tool fetches live (e.g. today's P/E ratio, today's price) is \
NOT a stored AIRP analysis and is NEVER a verdict, conviction score, or \
price target. When you use a live-fetched figure, say plainly that it \
is a live/current figure (e.g. "as of right now, TCS trades at a P/E of \
X") and keep it visibly separate from anything that came from a stored \
AIRP analysis (e.g. "your stored analysis rated TCS a BUY at conviction \
8/10"). Never blend the two into a single unlabelled number, and never \
let a live figure imply a new BUY/HOLD/SELL call -- that restriction \
from the rules above still applies with no exception for tool-fetched \
data.

If a tool call fails or returns no data, say so plainly rather than \
guessing or inventing a figure."""

#: Maps a stored ``chat_messages.role`` value to the LangChain message
#: class it becomes. Deliberately excludes 'system' and 'tool' -- see
#: this module's docstring for why those two are never replayed as
#: conversation turns.
_HISTORY_ROLE_TO_MESSAGE: dict[str, Any] = {
    "user": HumanMessage,
    "assistant": AIMessage,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


#: A transient Groq/Anthropic hiccup (a rate-limit blip, a momentary
#: network error, an overloaded-model 5xx) must not fail an entire chat
#: turn on the very first bad response when a single retry -- especially
#: one with a shorter, simplified prompt -- has a real chance of
#: succeeding. Kept at exactly one retry (not a full exponential-backoff
#: loop like backend/tools/*.py's external-data fetchers use): a chat
#: turn is a live, latency-sensitive user-facing wait, not a background
#: batch job, so bounding the extra latency a failure can add is more
#: important here than maximising eventual success odds.
_MAX_LLM_RETRIES = 1

#: Fixed delay before the one retry -- long enough to ride out a brief
#: rate-limit window, short enough that a user watching a chat reply
#: does not perceive the retry as a second hang on top of the first.
_RETRY_BACKOFF_SECONDS = 1.0


def _simplify_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Build a shorter, simpler message list for a post-failure retry.

    Keeps only the guardrail ``SystemMessage`` (always first, see
    ``build_chat_messages``) and the FINAL message (the user's actual
    question, or -- after a tool-calling round -- the model's own
    tool-call turn plus its tool results, which is deliberately dropped
    here in favour of the plain question instead: a retry after a
    failed decision/streaming call should ask a strictly simpler
    question, not repeat a tool-calling round). Dropping conversation
    history is the "simplified prompt" this module's callers retry
    with -- a shorter prompt is both cheaper (helps against a
    token-budget-flavoured rate limit) and structurally simpler (fewer
    turns for the model to get confused by) than the original, at the
    cost of losing multi-turn context for just this one retry attempt.

    Args:
        messages: The original message list that failed.

    Returns:
        A new list: [system_message, last_human_message] when at least
        one ``HumanMessage`` exists in ``messages``; otherwise the
        original list unchanged (nothing sensible to simplify).
    """
    if not messages:
        return messages

    system = messages[0]
    last_human: Optional[HumanMessage] = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_human = msg
            break

    if last_human is None:
        return messages

    return [system, last_human]


class ChatLLMError(Exception):
    """
    Raised when an AIRP Assistant chat turn cannot produce a response.

    Wraps the original exception (if any) in ``cause`` so a caller
    (a future REST endpoint in T-103, a future WebSocket handler in
    T-104) can log or inspect the underlying failure while presenting
    a clean, user-facing error of its own choosing.
    """

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause


# ---------------------------------------------------------------------------
# LLM wrapper
# ---------------------------------------------------------------------------


def get_chat_llm() -> Any:
    """
    Return the configured LLM for the AIRP Assistant.

    Thin wrapper over ``backend.agents.llm_factory.get_llm`` -- see
    this module's docstring for why the wrapper exists as its own
    function rather than a bare re-export, and why it does not change
    provider, temperature, or timeout from ``get_llm()``'s own
    defaults today.

    Returns:
        The same LLM client every agent uses: ``ChatGroq`` when
        ``LLM_PROVIDER=groq`` (default), ``ChatAnthropic`` when
        ``LLM_PROVIDER=anthropic``.
    """
    return get_llm()


# ---------------------------------------------------------------------------
# Personalization (T-106)
# ---------------------------------------------------------------------------


def build_personalization_instruction(
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
) -> str:
    """
    Build the personalization instruction block appended to the system
    prompt (T-106).

    Two mutually exclusive shapes, matching this task's "ask and
    remember... once" acceptance criterion:

      * Nothing known yet (``risk_appetite`` is None and
        ``preferred_sectors`` is empty/None): instructs the assistant
        to ask, at most ONCE per conversation, in a brief and natural
        way -- never as an interrogation, and never blocking the
        actual answer to whatever the user just asked.
      * Something is known: states it plainly, with an adjacent HARD
        RULE that it may only steer tone/emphasis/which already-stored
        details to highlight -- never a verdict, conviction score,
        price target, or any numeric figure in the stored analysis.
        See this module's docstring for why the hard rule is repeated
        here rather than left to only ``SYSTEM_PROMPT``.

    Args:
        risk_appetite: 'conservative' | 'moderate' | 'aggressive', or
            None if not yet known
            (``user_preferences.risk_appetite`` is NULL).
        preferred_sectors: Sector names the user favours, or an
            empty/None list if not yet known
            (``user_preferences.preferred_sectors`` is ``[]``).

    Returns:
        Instruction text to append to the system prompt.
    """
    sectors = preferred_sectors or []

    if risk_appetite is None and not sectors:
        return (
            "PERSONALIZATION: You do not yet know this user's risk "
            "appetite or preferred sectors. If a natural moment arises "
            "in this reply, ask ONE brief question about their risk "
            "appetite (conservative, moderate, or aggressive) and/or "
            "which sectors they are most interested in -- do not force "
            "it, and never let it delay or replace answering what they "
            "actually asked. Ask this at most once per conversation: if "
            "you already asked earlier in this session, do not ask "
            "again even if they have not answered yet."
        )

    known_bits = []
    if risk_appetite is not None:
        known_bits.append(f"risk appetite: {risk_appetite}")
    if sectors:
        known_bits.append(f"preferred sectors: {', '.join(sectors)}")
    known_summary = "; ".join(known_bits)

    return (
        f"PERSONALIZATION: This user has told you -- {known_summary}. "
        "Use this only to adjust your tone and which already-stored "
        "details you choose to emphasise -- for example, lead with "
        "downside risk and capital-preservation factors for a "
        "conservative investor, lead with growth catalysts for an "
        "aggressive one, or note a stored analysis's relevance to a "
        "sector they favour. HARD RULE: this NEVER changes a verdict, "
        "conviction score, price target, or any numeric figure in the "
        "stored analysis -- those come only from the investment "
        "committee's own completed analysis, exactly as required above."
    )


# ---------------------------------------------------------------------------
# Prompt / message builders
# ---------------------------------------------------------------------------


def build_system_prompt(
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
    tools_available: bool = False,
) -> str:
    """
    Build the full system prompt text for one AIRP Assistant call.

    Always starts with the objectivity guardrail (``SYSTEM_PROMPT``),
    then the response-style instruction, then the personalization
    instruction (T-106, see ``build_personalization_instruction``),
    then -- only when ``tools_available`` -- the live-data-tool
    instruction (B9, see ``LIVE_DATA_TOOL_INSTRUCTION``), then -- only
    when provided -- the grounded context block (e.g. a memo-scoped
    session's ``MemoChatContext.full_context`` from T-100). ``context``
    is never validated or summarised here; this function only assembles
    text the caller already trusts.

    Args:
        response_style: One of the keys in
            ``RESPONSE_STYLE_INSTRUCTIONS`` (typically a
            ``UserPreferences.chat_response_style`` value). Any other
            value falls back to ``DEFAULT_RESPONSE_STYLE``.
        context: Optional grounded context to append, e.g. a
            memo-scoped session's rendered analysis.
        risk_appetite: Forwarded to
            ``build_personalization_instruction`` -- typically a
            ``UserPreferences.risk_appetite`` value (T-106).
        preferred_sectors: Forwarded to
            ``build_personalization_instruction`` -- typically a
            ``UserPreferences.preferred_sectors`` value (T-106).
        tools_available: (B9) True when this call has one or more
            LangChain tools bound (portfolio-wide session tools and/or
            the live-market-data tools) -- appends
            ``LIVE_DATA_TOOL_INSTRUCTION`` when true. False for a call
            with no tools bound, keeping that (more common) prompt
            shorter.

    Returns:
        The full system prompt text, ready to wrap in a
        ``SystemMessage``.
    """
    style_instruction = RESPONSE_STYLE_INSTRUCTIONS.get(
        response_style, RESPONSE_STYLE_INSTRUCTIONS[DEFAULT_RESPONSE_STYLE]
    )
    parts = [
        SYSTEM_PROMPT,
        style_instruction,
        build_personalization_instruction(risk_appetite, preferred_sectors),
    ]
    if tools_available:
        parts.append(LIVE_DATA_TOOL_INSTRUCTION)
    if context:
        parts.append(f"Grounded context for this conversation:\n{context}")
    return "\n\n".join(parts)


def build_system_message(
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
    tools_available: bool = False,
) -> SystemMessage:
    """Wrap ``build_system_prompt()``'s output in a ``SystemMessage``."""
    return SystemMessage(
        content=build_system_prompt(
            response_style, context, risk_appetite, preferred_sectors, tools_available
        )
    )


def build_chat_messages(
    history: list[dict[str, str]],
    user_message: str,
    *,
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
    tools_available: bool = False,
) -> list[BaseMessage]:
    """
    Assemble the full message list for one AIRP Assistant LLM call.

    Order: one guardrail ``SystemMessage`` (always first and always
    exactly one -- see this module's docstring for why stored
    'system'/'tool' rows are never replayed here), then ``history`` in
    order as alternating Human/AI messages, then ``user_message`` as
    the final ``HumanMessage``.

    Args:
        history: Prior turns in this session, each a dict with at
            least ``role`` ('user'/'assistant'/'system'/'tool', the
            same values ``chat_messages.role`` stores) and ``content``.
            Rows with any role other than 'user'/'assistant' are
            skipped. Malformed entries (missing keys) are skipped
            rather than raising -- one bad row must not break an
            otherwise-valid chat turn.
        user_message: The new message the user just sent.
        response_style: Forwarded to ``build_system_prompt``.
        context: Forwarded to ``build_system_prompt``.
        risk_appetite: Forwarded to ``build_system_prompt`` (T-106).
        preferred_sectors: Forwarded to ``build_system_prompt`` (T-106).
        tools_available: Forwarded to ``build_system_prompt`` (B9).

    Returns:
        A list of LangChain ``BaseMessage`` objects ready to pass to
        ``llm.invoke(...)``.
    """
    messages: list[BaseMessage] = [
        build_system_message(
            response_style, context, risk_appetite, preferred_sectors, tools_available
        )
    ]

    for turn in history:
        role = turn.get("role")
        message_cls = _HISTORY_ROLE_TO_MESSAGE.get(role) if role else None
        if message_cls is None:
            continue
        content = turn.get("content")
        if not isinstance(content, str):
            continue
        messages.append(message_cls(content=content))

    messages.append(HumanMessage(content=user_message))
    return messages


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def invoke_chat(
    history: list[dict[str, str]],
    user_message: str,
    *,
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
    llm: Optional[Any] = None,
) -> str:
    """
    Run one AIRP Assistant chat turn and return the assistant's reply.

    A synchronous, single-call convenience wrapper: build the message
    list (guardrail system prompt + history + new user message), call
    the LLM once, and return its text. T-103's REST endpoints and
    T-104's WebSocket streaming are expected to call
    ``build_chat_messages`` directly instead when they need to stream
    tokens or interleave tool calls -- this function is for the common
    case (and for this task's own manual QA transcript) of "one
    question in, one grounded answer out".

    Args:
        history: Prior turns in this session -- see
            ``build_chat_messages`` for the expected shape.
        user_message: The new message the user just sent.
        response_style: Forwarded to ``build_chat_messages``.
        context: Forwarded to ``build_chat_messages`` -- typically a
            memo-scoped session's ``MemoChatContext.full_context``
            (T-100) or a short description of which portfolio-wide
            tools (T-101) are bound for this call.
        risk_appetite: Forwarded to ``build_chat_messages`` (T-106).
        preferred_sectors: Forwarded to ``build_chat_messages`` (T-106).
        llm: Optional pre-built LLM client (e.g. one already bound to
            portfolio tools via ``.bind_tools(...)``). Defaults to
            ``get_chat_llm()`` when not provided.

    Returns:
        The assistant's reply text.

    Raises:
        ChatLLMError: the LLM call itself failed, or returned a
            response with no usable text content. See this module's
            docstring for why this function raises rather than
            degrading gracefully.
    """
    messages = build_chat_messages(
        history,
        user_message,
        response_style=response_style,
        context=context,
        risk_appetite=risk_appetite,
        preferred_sectors=preferred_sectors,
    )
    active_llm = llm if llm is not None else get_chat_llm()

    attempt_messages = messages
    last_exc: Optional[Exception] = None
    response: Any = None
    for attempt in range(_MAX_LLM_RETRIES + 1):
        try:
            response = active_llm.invoke(attempt_messages)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_LLM_RETRIES:
                logger.warning(
                    "chat_llm: LLM invocation failed (attempt %d/%d), "
                    "retrying with a simplified prompt: %s",
                    attempt + 1,
                    _MAX_LLM_RETRIES + 1,
                    exc,
                )
                attempt_messages = _simplify_messages(messages)
                time.sleep(_RETRY_BACKOFF_SECONDS)
            else:
                logger.exception("chat_llm: LLM invocation failed on final attempt")

    if last_exc is not None:
        raise ChatLLMError(
            "AIRP Assistant failed to generate a response.", cause=last_exc
        ) from last_exc

    raw_content: Any = response.content if hasattr(response, "content") else response
    text = raw_content if isinstance(raw_content, str) else str(raw_content)

    if not text.strip():
        logger.warning("chat_llm: LLM returned an empty response")
        raise ChatLLMError("AIRP Assistant returned an empty response.")

    return text


# ---------------------------------------------------------------------------
# Tool-calling round (B9)
# ---------------------------------------------------------------------------
#
# Root cause this section fixes: a portfolio-wide chat session's guardrail
# persona and streaming mechanics were fully wired (T-104), but
# backend.tools.portfolio_tools.build_portfolio_tools's three tools were
# never bound to the streaming call at all -- chat_stream.py's own module
# docstring documented this as a deliberately deferred "known scope
# boundary". The practical symptom: the assistant had no way to look up
# the user's own analyses, so any portfolio-wide question about a
# specific past analysis produced "I don't have that" / "analysis has
# not been done" even when the user had one -- a false negative, not a
# genuinely missing analysis.
#
# astream_chat's own async generator can stream TEXT token by token, but
# has no mechanism to execute a tool call mid-stream and feed the result
# back for a second pass -- most providers emit tool-call deltas with
# empty text content, so simply handing a .bind_tools()-bound LLM to
# astream_chat's existing loop would either silently yield nothing (the
# empty-response ChatLLMError below) or stream a reply the model produced
# without ever actually calling the tool it needed. _run_tool_calling_round
# below is the fix: ONE non-streamed decision call (tools bound) up front
# to let the model decide whether it needs a tool, then either the
# streaming call proceeds normally (no tool needed) or a follow-up
# streaming call runs on the updated message history (tool results
# appended as ToolMessages, tools NOT re-bound) so the model must produce
# a final answer from what it already has rather than requesting further
# tool calls -- deliberately one round, not a full agentic loop, to keep
# a single chat turn's latency and cost bounded.


async def run_tool_calling_round(
    llm: Any,
    tools: list[BaseTool],
    messages: list[BaseMessage],
) -> tuple[list[BaseMessage], Optional[str]]:
    """
    Run one non-streamed tool-calling decision round.

    Exposed as a public, standalone function (not folded into
    ``astream_chat``'s own body) specifically so a caller whose tools
    need a resource with a narrower lifetime than the token stream --
    ``backend.tools.portfolio_tools``'s tools need an open
    ``AsyncSession``, and ``backend/routers/chat_stream.py`` deliberately
    closes its DB session before streaming begins (see that router's own
    module docstring) -- can run this decision-and-execution round WHILE
    that session is still open, then close it, then stream the final
    answer (via ``astream_chat_from_messages``, which touches no DB at
    all) afterwards. ``astream_chat`` itself still calls this internally
    for callers with no such constraint (see its own docstring).

    Args:
        llm:      The base (not yet tool-bound) LLM client.
        tools:    Tools to bind for this decision call (portfolio-wide
                  session tools and/or the live-market-data tools).
        messages: The full message list built by ``build_chat_messages``
                  (already includes the guardrail system prompt, history,
                  and the new user message).

    Returns:
        ``(messages, text)`` where exactly one of the two return
        elements carries the useful result:

        * The model needed no tool: ``text`` is its own reply (already
          complete, non-streamed) and ``messages`` is the SAME list
          passed in, unchanged -- the caller should yield ``text``
          directly rather than making a second LLM call.
        * The model called one or more tools: ``text`` is ``None`` and
          ``messages`` is the ORIGINAL list plus the model's own
          tool-calling ``AIMessage`` and one ``ToolMessage`` per call
          (each tool executed via its own ``.ainvoke()``, exceptions
          caught and turned into an error-shaped ``ToolMessage`` rather
          than propagating -- matching the "tools never crash the
          caller" convention every tool in this codebase already
          follows) -- the caller should make a second, final streaming
          call on this updated list, WITHOUT re-binding tools.

    Never raises for a tool-execution failure (see above). The decision
    call itself (``llm.bind_tools(...).ainvoke``) gets one bounded retry
    with a simplified (history-dropped) prompt on failure -- a
    malformed/garbled tool-call response or a transient provider error
    on this one call used to fail the entire turn immediately; now only
    a repeated failure does. A failure of BOTH attempts still propagates
    exactly like a normal ``invoke_chat``/``astream_chat`` LLM failure --
    the caller's existing ``except Exception`` handling around this call
    already turns that into a ``ChatLLMError``.
    """
    attempt_messages = messages
    response: Any = None
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_LLM_RETRIES + 1):
        try:
            tool_bound_llm = llm.bind_tools(tools)
            response = await tool_bound_llm.ainvoke(attempt_messages)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_LLM_RETRIES:
                logger.warning(
                    "chat_llm: tool-calling decision call failed "
                    "(attempt %d/%d), retrying with a simplified prompt: %s",
                    attempt + 1,
                    _MAX_LLM_RETRIES + 1,
                    exc,
                )
                attempt_messages = _simplify_messages(messages)
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            else:
                logger.exception(
                    "chat_llm: tool-calling decision call failed on final attempt"
                )

    if last_exc is not None:
        raise last_exc

    tool_calls: list[dict[str, Any]] = list(getattr(response, "tool_calls", None) or [])
    if not tool_calls:
        raw_content: Any = (
            response.content if hasattr(response, "content") else response
        )
        text = raw_content if isinstance(raw_content, str) else str(raw_content)
        return messages, text

    tools_by_name = {t.name: t for t in tools}
    updated: list[BaseMessage] = [*messages, response]

    for call in tool_calls:
        tool_name = call.get("name")
        tool_obj = tools_by_name.get(tool_name) if tool_name else None
        call_id = str(call.get("id") or "")
        call_args = call.get("args")

        if tool_obj is None:
            logger.warning(
                "chat_llm: tool_call id=%s model requested unknown tool %r "
                "(args=%r) -- returning an error result instead of "
                "executing anything",
                call_id,
                tool_name,
                call_args,
            )
            updated.append(
                ToolMessage(
                    content=json.dumps({"error": "unknown_tool", "tool": tool_name}),
                    tool_call_id=call_id,
                )
            )
            continue

        logger.info(
            "chat_llm: tool_call id=%s invoking tool=%s args=%r",
            call_id,
            tool_name,
            call_args,
        )
        started_at = time.monotonic()
        try:
            tool_result = await tool_obj.ainvoke(call)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.warning(
                "chat_llm: tool_call id=%s tool=%s failed after %.0fms: %s "
                "-- returning an error result instead of failing the whole turn",
                call_id,
                tool_name,
                elapsed_ms,
                exc,
            )
            updated.append(
                ToolMessage(
                    content=json.dumps({"error": "tool_failed", "message": str(exc)}),
                    tool_call_id=call_id,
                )
            )
            continue

        elapsed_ms = (time.monotonic() - started_at) * 1000
        logger.info(
            "chat_llm: tool_call id=%s tool=%s completed in %.0fms",
            call_id,
            tool_name,
            elapsed_ms,
        )

        # BaseTool.ainvoke(call) on a ToolCall-shaped dict (name/args/id/
        # type, exactly what response.tool_calls items already are)
        # returns a fully-formed ToolMessage directly -- nothing further
        # to wrap.
        updated.append(tool_result)

    return updated, None


# ---------------------------------------------------------------------------
# Streaming entry point (T-104)
# ---------------------------------------------------------------------------


async def astream_chat(
    history: list[dict[str, str]],
    user_message: str,
    *,
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
    llm: Optional[Any] = None,
    tools: Optional[list[BaseTool]] = None,
) -> AsyncIterator[str]:
    """
    Run one AIRP Assistant chat turn and yield the reply token by token.

    The streaming counterpart to ``invoke_chat`` -- same message
    construction (``build_chat_messages``, so the guardrail system
    prompt, personalization instruction (T-106), and history-role
    handling are identical), but calls the underlying LangChain
    client's ``.astream(...)`` instead of ``.invoke(...)`` and yields
    each chunk's text as it arrives, for a caller (WS /api/v1/chat/
    {session_id}/stream, T-104) that forwards each token to a
    connected client as it is produced rather than waiting for the
    complete response.

    Every empty chunk is skipped (some providers emit an empty leading
    or trailing chunk as part of normal streaming, and forwarding a
    zero-length token event over the wire would be pure overhead), but
    an ENTIRELY empty response (zero non-empty chunks total) is treated
    as a failure -- see the ``ChatLLMError`` raised below -- for the
    same reason ``invoke_chat`` treats an empty non-streamed response
    as a failure: a silently blank AIRP Assistant reply is worse for
    the caller to receive than a clear error it can act on.

    Args:
        history:        Prior turns in this session -- see
                         ``build_chat_messages`` for the expected
                         shape.
        user_message:    The new message the user just sent.
        response_style: Forwarded to ``build_chat_messages``.
        context:        Forwarded to ``build_chat_messages``.
        risk_appetite:  Forwarded to ``build_chat_messages`` (T-106).
        preferred_sectors: Forwarded to ``build_chat_messages`` (T-106).
        llm:            Optional pre-built LLM client. Defaults to
                         ``get_chat_llm()`` when not provided.
        tools:          (B9) Tools to make available for this turn --
                         typically ``backend.tools.portfolio_tools.
                         build_portfolio_tools(...)`` for a
                         portfolio-wide session, plus the live-market-
                         data tools, for either session type. When
                         non-empty, one non-streamed decision call runs
                         first (see ``_run_tool_calling_round``) to let
                         the model decide whether it needs a tool before
                         the actual token stream begins -- this adds one
                         extra LLM round-trip of latency before the
                         first token for a tool-eligible turn, in
                         exchange for the model being able to ground its
                         answer in real data instead of guessing or
                         falsely claiming "no analysis". ``None`` or an
                         empty list (the default) preserves the exact
                         pre-B9 behaviour: one streaming call, no tools.

    Yields:
        Each non-empty text chunk of the assistant's reply, in the
        order the provider streamed them. When the tool-calling round
        determined no tool was needed, its own already-complete reply
        is yielded as a single chunk rather than re-querying the model
        a second time purely to re-derive the same text token by token.

    Raises:
        ChatLLMError: the streaming call itself failed (raised from
            inside the ``async for`` loop, so any tokens already
            yielded before the failure remain valid and already
            delivered to the caller), or the stream produced zero
            non-empty chunks. A failure during the tool-calling decision
            call itself is wrapped the same way.
    """
    messages = build_chat_messages(
        history,
        user_message,
        response_style=response_style,
        context=context,
        risk_appetite=risk_appetite,
        preferred_sectors=preferred_sectors,
        tools_available=bool(tools),
    )
    active_llm = llm if llm is not None else get_chat_llm()

    if tools:
        try:
            messages, immediate_text = await run_tool_calling_round(
                active_llm, tools, messages
            )
        except Exception as exc:
            logger.exception("chat_llm: tool-calling decision round failed")
            raise ChatLLMError(
                "AIRP Assistant failed to generate a response.", cause=exc
            ) from exc

        if immediate_text is not None:
            if not immediate_text.strip():
                logger.warning(
                    "chat_llm: tool-calling round produced an empty response "
                    "with no tool calls"
                )
                raise ChatLLMError("AIRP Assistant returned an empty response.")
            yield immediate_text
            return

    async for token in astream_chat_from_messages(messages, llm=active_llm):
        yield token


async def astream_chat_from_messages(
    messages: list[BaseMessage],
    *,
    llm: Optional[Any] = None,
) -> AsyncIterator[str]:
    """
    Stream one LLM reply token by token from an ALREADY-BUILT message list.

    The low-level primitive ``astream_chat`` itself delegates to once it
    has finished building messages (and running the tool-calling round,
    if any) -- extracted as its own function for the same reason
    ``run_tool_calling_round`` is public: a caller whose message-building
    step needs a resource with a narrower lifetime than the token stream
    (``backend/routers/chat_stream.py``'s per-turn DB session) can build
    ``messages`` and run any tool round while that resource is still
    open, then call THIS function -- which touches no DB, no tools,
    nothing but the LLM client -- after closing it.

    Touches no history, no context, no tools -- ``messages`` is used
    exactly as given. Every empty chunk is skipped (some providers emit
    an empty leading/trailing chunk as part of normal streaming); an
    ENTIRELY empty response (zero non-empty chunks) is treated as a
    failure, the same reasoning ``invoke_chat``/``astream_chat`` already
    document for their own empty-response cases.

    Args:
        messages: Full message list ready for ``llm.astream(...)`` --
            typically ``build_chat_messages(...)``'s output, optionally
            already passed through ``run_tool_calling_round``.
        llm: Optional pre-built LLM client. Defaults to
            ``get_chat_llm()`` when not provided.

    Yields:
        Each non-empty text chunk of the reply, in the order the
        provider streamed them.

    Raises:
        ChatLLMError: the streaming call itself failed, or the stream
            produced zero non-empty chunks -- after one bounded retry
            with a simplified (history-dropped) prompt, but ONLY when
            the failure/empty result happened before any token was
            actually delivered to the caller. A failure that occurs
            AFTER some tokens were already yielded is never retried --
            the caller has already received and (for
            backend/routers/chat_stream.py) forwarded real partial
            content, so retrying would mean silently prepending a
            second, differently-worded attempt onto what the user is
            already reading.
    """
    active_llm = llm if llm is not None else get_chat_llm()

    attempt_messages = messages
    for attempt in range(_MAX_LLM_RETRIES + 1):
        is_last_attempt = attempt == _MAX_LLM_RETRIES
        yielded_any = False
        try:
            async for chunk in active_llm.astream(attempt_messages):
                raw_content: Any = chunk.content if hasattr(chunk, "content") else chunk
                token = (
                    raw_content if isinstance(raw_content, str) else str(raw_content)
                )
                if token:
                    yielded_any = True
                    yield token
        except Exception as exc:
            if yielded_any or is_last_attempt:
                logger.exception(
                    "chat_llm: streaming LLM invocation failed "
                    "(yielded_any=%s, attempt=%d/%d)",
                    yielded_any,
                    attempt + 1,
                    _MAX_LLM_RETRIES + 1,
                )
                raise ChatLLMError(
                    "AIRP Assistant failed to generate a response.", cause=exc
                ) from exc
            logger.warning(
                "chat_llm: streaming LLM invocation failed before any token "
                "was produced (attempt %d/%d), retrying with a simplified "
                "prompt: %s",
                attempt + 1,
                _MAX_LLM_RETRIES + 1,
                exc,
            )
            attempt_messages = _simplify_messages(messages)
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            continue

        if yielded_any:
            return

        if is_last_attempt:
            logger.warning("chat_llm: streaming LLM produced no tokens")
            raise ChatLLMError("AIRP Assistant returned an empty response.")

        logger.warning(
            "chat_llm: streaming LLM produced no tokens (attempt %d/%d), "
            "retrying with a simplified prompt",
            attempt + 1,
            _MAX_LLM_RETRIES + 1,
        )
        attempt_messages = _simplify_messages(messages)
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
