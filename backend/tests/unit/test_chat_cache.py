# backend/tests/unit/test_chat_cache.py
"""
Unit tests for backend/services/chat_cache.py (B9).

Test strategy
-------------
1. normalize_question -- trims, lower-cases, collapses internal
   whitespace; two differently-formatted-but-equivalent questions
   normalise to the same string.
2. build_cache_key -- deterministic (same inputs -> same key), different
   user_id/session_scope/question each produce a different key, the
   question text itself never appears verbatim in the key (it is
   hashed), and normalisation is applied before hashing (so two
   differently-formatted questions collide on the same key).
3. get_cached_reply / set_cached_reply -- round-trips through
   backend.tools.cache's real (test-env no-op, or fake-client-injected)
   cache_get_json/cache_set_json; a miss returns None; a cached value
   with no usable "reply" string is treated as a miss rather than
   raising; set_cached_reply forwards CHAT_REPLY_CACHE_TTL_SECONDS.

Matches test_cache.py's own "inject a fake client via
backend.tools.cache.get_client" pattern for the round-trip tests, since
backend.tools.cache's own low-level helpers already handle the
ENVIRONMENT=test no-op case.

ENVIRONMENT must be set to 'test' before any backend import.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch
import uuid

os.environ.setdefault("ENVIRONMENT", "test")

from backend.services.chat_cache import (  # noqa: E402
    CHAT_REPLY_CACHE_TTL_SECONDS,
    PORTFOLIO_SCOPE,
    build_cache_key,
    get_cached_reply,
    normalize_question,
    set_cached_reply,
)

# ---------------------------------------------------------------------------
# 1. normalize_question
# ---------------------------------------------------------------------------


class TestNormalizeQuestion:
    def test_trims_leading_and_trailing_whitespace(self) -> None:
        assert normalize_question("  hello  ") == "hello"

    def test_lower_cases(self) -> None:
        assert normalize_question("What Is My PE Ratio?") == "what is my pe ratio?"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_question("what   is  my\tPE ratio") == "what is my pe ratio"

    def test_equivalent_differently_formatted_questions_normalise_identically(
        self,
    ) -> None:
        a = normalize_question("What's my PE ratio?")
        b = normalize_question("  what's my pe ratio?  ")
        assert a == b

    def test_genuinely_different_questions_normalise_differently(self) -> None:
        assert normalize_question("What is my PE ratio?") != normalize_question(
            "What is my PB ratio?"
        )


# ---------------------------------------------------------------------------
# 2. build_cache_key
# ---------------------------------------------------------------------------


class TestBuildCacheKey:
    def test_deterministic_for_the_same_inputs(self) -> None:
        user_id = uuid.uuid4()
        key_a = build_cache_key(user_id, "portfolio", "What is my PE ratio?")
        key_b = build_cache_key(user_id, "portfolio", "What is my PE ratio?")
        assert key_a == key_b

    def test_normalisation_applied_before_hashing(self) -> None:
        user_id = uuid.uuid4()
        key_a = build_cache_key(user_id, "portfolio", "What is my PE ratio?")
        key_b = build_cache_key(user_id, "portfolio", "  what is my pe ratio?  ")
        assert key_a == key_b

    def test_different_users_get_different_keys(self) -> None:
        key_a = build_cache_key(uuid.uuid4(), "portfolio", "hello")
        key_b = build_cache_key(uuid.uuid4(), "portfolio", "hello")
        assert key_a != key_b

    def test_different_session_scopes_get_different_keys(self) -> None:
        user_id = uuid.uuid4()
        key_a = build_cache_key(user_id, "portfolio", "hello")
        key_b = build_cache_key(user_id, str(uuid.uuid4()), "hello")
        assert key_a != key_b

    def test_different_questions_get_different_keys(self) -> None:
        user_id = uuid.uuid4()
        key_a = build_cache_key(user_id, "portfolio", "What is my PE ratio?")
        key_b = build_cache_key(user_id, "portfolio", "What is my PB ratio?")
        assert key_a != key_b

    def test_question_text_is_not_embedded_verbatim_in_the_key(self) -> None:
        key = build_cache_key(
            uuid.uuid4(), "portfolio", "a very specific secret question"
        )
        assert "secret" not in key

    def test_key_includes_the_user_id_and_scope_for_readability_debugging(self) -> None:
        user_id = uuid.uuid4()
        key = build_cache_key(user_id, "portfolio", "hello")
        assert str(user_id) in key
        assert "portfolio" in key

    def test_memo_scoped_uses_analysis_id_as_scope(self) -> None:
        analysis_id = str(uuid.uuid4())
        key = build_cache_key(uuid.uuid4(), analysis_id, "hello")
        assert analysis_id in key

    def test_portfolio_scope_constant_is_a_stable_non_uuid_placeholder(self) -> None:
        # A UUID-shaped scope would never collide with PORTFOLIO_SCOPE by
        # accident -- confirms the placeholder is deliberately distinct.
        assert PORTFOLIO_SCOPE == "portfolio"


# ---------------------------------------------------------------------------
# 3. get_cached_reply / set_cached_reply
# ---------------------------------------------------------------------------


class TestGetSetCachedReply:
    def test_miss_under_test_env_returns_none(self) -> None:
        assert get_cached_reply("any:key") is None

    def test_set_is_a_no_op_under_test_env_and_never_raises(self) -> None:
        set_cached_reply("any:key", "some reply")  # must not raise

    def test_get_round_trips_through_a_fake_client(self) -> None:
        fake = MagicMock()
        store: dict[str, str] = {}

        def _get(key: str) -> Any:
            return store.get(key)

        def _set(key: str, value: str, ex: int) -> bool:
            store[key] = value
            return True

        fake.get.side_effect = _get
        fake.set.side_effect = _set

        with patch("backend.tools.cache.get_client", return_value=fake):
            set_cached_reply("k1", "the cached reply text")
            result = get_cached_reply("k1")

        assert result == "the cached reply text"

    def test_set_forwards_the_documented_ttl(self) -> None:
        fake = MagicMock()
        with patch("backend.tools.cache.get_client", return_value=fake):
            set_cached_reply("k1", "reply")

        kwargs = fake.set.call_args.kwargs
        assert kwargs.get("ex") == CHAT_REPLY_CACHE_TTL_SECONDS

    def test_cached_value_with_no_reply_key_is_treated_as_a_miss(self) -> None:
        fake = MagicMock()
        fake.get.return_value = '{"not_reply": "oops"}'

        with patch("backend.tools.cache.get_client", return_value=fake):
            result = get_cached_reply("k1")

        assert result is None

    def test_cached_value_with_non_string_reply_is_treated_as_a_miss(self) -> None:
        fake = MagicMock()
        fake.get.return_value = '{"reply": 12345}'

        with patch("backend.tools.cache.get_client", return_value=fake):
            result = get_cached_reply("k1")

        assert result is None

    def test_corrupt_cached_json_is_treated_as_a_miss_not_a_crash(self) -> None:
        fake = MagicMock()
        fake.get.return_value = "{not valid json"

        with patch("backend.tools.cache.get_client", return_value=fake):
            result = get_cached_reply("k1")

        assert result is None
