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
    )
"""

import logging
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from backend.agents.llm_factory import get_llm

logger = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_PROMPT",
    "RESPONSE_STYLE_INSTRUCTIONS",
    "DEFAULT_RESPONSE_STYLE",
    "ChatLLMError",
    "get_chat_llm",
    "build_system_prompt",
    "build_system_message",
    "build_chat_messages",
    "build_personalization_instruction",
    "invoke_chat",
    "astream_chat",
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
) -> str:
    """
    Build the full system prompt text for one AIRP Assistant call.

    Always starts with the objectivity guardrail (``SYSTEM_PROMPT``),
    then the response-style instruction, then the personalization
    instruction (T-106, see ``build_personalization_instruction``),
    then -- only when provided -- the grounded context block (e.g. a
    memo-scoped session's ``MemoChatContext.full_context`` from T-100).
    ``context`` is never validated or summarised here; this function
    only assembles text the caller already trusts.

    Args:
        response_style: One of the keys in
            ``RESPONSE_STYLE_INSTRUCTIONS`` (typically a
            ``UserPreferences.chat_response_style`` value). Any other
            value falls back to ``DEFAULT_RESPONSE_STYLE``.
        context: Optional grounded context to append, e.g. a
            memo-scoped session's rendered analysis, or a short note
            describing which portfolio-wide tools are available.
        risk_appetite: Forwarded to
            ``build_personalization_instruction`` -- typically a
            ``UserPreferences.risk_appetite`` value (T-106).
        preferred_sectors: Forwarded to
            ``build_personalization_instruction`` -- typically a
            ``UserPreferences.preferred_sectors`` value (T-106).

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
    if context:
        parts.append(f"Grounded context for this conversation:\n{context}")
    return "\n\n".join(parts)


def build_system_message(
    response_style: str = DEFAULT_RESPONSE_STYLE,
    context: Optional[str] = None,
    risk_appetite: Optional[str] = None,
    preferred_sectors: Optional[list[str]] = None,
) -> SystemMessage:
    """Wrap ``build_system_prompt()``'s output in a ``SystemMessage``."""
    return SystemMessage(
        content=build_system_prompt(
            response_style, context, risk_appetite, preferred_sectors
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

    Returns:
        A list of LangChain ``BaseMessage`` objects ready to pass to
        ``llm.invoke(...)``.
    """
    messages: list[BaseMessage] = [
        build_system_message(response_style, context, risk_appetite, preferred_sectors)
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

    try:
        response = active_llm.invoke(messages)
    except Exception as exc:
        logger.exception("chat_llm: LLM invocation failed")
        raise ChatLLMError(
            "AIRP Assistant failed to generate a response.", cause=exc
        ) from exc

    raw_content: Any = response.content if hasattr(response, "content") else response
    text = raw_content if isinstance(raw_content, str) else str(raw_content)

    if not text.strip():
        logger.warning("chat_llm: LLM returned an empty response")
        raise ChatLLMError("AIRP Assistant returned an empty response.")

    return text


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

    Yields:
        Each non-empty text chunk of the assistant's reply, in the
        order the provider streamed them.

    Raises:
        ChatLLMError: the streaming call itself failed (raised from
            inside the ``async for`` loop, so any tokens already
            yielded before the failure remain valid and already
            delivered to the caller), or the stream produced zero
            non-empty chunks.
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

    yielded_any = False
    try:
        async for chunk in active_llm.astream(messages):
            raw_content: Any = chunk.content if hasattr(chunk, "content") else chunk
            token = raw_content if isinstance(raw_content, str) else str(raw_content)
            if token:
                yielded_any = True
                yield token
    except Exception as exc:
        logger.exception("chat_llm: streaming LLM invocation failed")
        raise ChatLLMError(
            "AIRP Assistant failed to generate a response.", cause=exc
        ) from exc

    if not yielded_any:
        logger.warning("chat_llm: streaming LLM produced no tokens")
        raise ChatLLMError("AIRP Assistant returned an empty response.")
