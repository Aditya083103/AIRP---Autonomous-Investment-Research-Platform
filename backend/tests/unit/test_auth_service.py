# backend/tests/unit/test_auth_service.py
"""
Unit tests for T-046: backend/services/auth.py

Tests password hashing (bcrypt via passlib) and JWT issuance/
verification in complete isolation -- no FastAPI app, no database.
This is the layer the auth router and get_current_user dependency both
build on, so its correctness here is what the higher-level tests in
test_auth_router.py and test_dependencies_auth.py can safely assume.

Acceptance criteria verified (from task spec, at this layer):
  * password hashed with bcrypt
  * JWT tokens issued and verifiable
  * an invalid/expired/tampered token is rejected (raises, not silently
    accepted) -- the router/dependency layer turns this into the actual
    401 response
"""

from __future__ import annotations

import uuid

from freezegun import freeze_time
from jose import jwt as raw_jwt
import pytest

from backend.config import Settings
from backend.services.auth import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestHashPassword:
    def test_returns_a_string(self) -> None:
        result = hash_password("correct-horse-battery-staple")
        assert isinstance(result, str)

    def test_hash_is_not_the_plaintext(self) -> None:
        plain = "correct-horse-battery-staple"
        assert hash_password(plain) != plain

    def test_hash_has_bcrypt_prefix(self) -> None:
        # passlib's bcrypt scheme produces hashes starting with $2b$
        # (or, for older inputs, $2a$/$2y$) -- $2b$ is what passlib
        # writes for new hashes with the "bcrypt" scheme as configured.
        result = hash_password("correct-horse-battery-staple")
        assert result.startswith("$2b$")

    def test_two_hashes_of_the_same_password_differ(self) -> None:
        # bcrypt salts each hash independently -- two hashes of the
        # identical password must never be byte-for-byte equal.
        plain = "correct-horse-battery-staple"
        assert hash_password(plain) != hash_password(plain)


class TestVerifyPassword:
    def test_correct_password_verifies(self) -> None:
        plain = "correct-horse-battery-staple"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_incorrect_password_does_not_verify(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_empty_password_does_not_verify_against_real_hash(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("", hashed) is False

    def test_malformed_hash_returns_false_not_raise(self) -> None:
        # A corrupted/non-bcrypt password_hash value (e.g. a DB row
        # written before this scheme existed) must degrade to "does
        # not match" rather than raising -- a 401, not a 500.
        assert verify_password("anything", "not-a-real-bcrypt-hash") is False

    def test_case_sensitive(self) -> None:
        hashed = hash_password("CorrectHorseBatteryStaple")
        assert verify_password("correcthorsebatterystaple", hashed) is False


# ---------------------------------------------------------------------------
# JWT issuance
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    def test_returns_a_string_token_and_int_expiry(
        self, test_settings: Settings
    ) -> None:
        token, expires_in = create_access_token(uuid.uuid4(), settings=test_settings)
        assert isinstance(token, str)
        assert isinstance(expires_in, int)

    def test_expires_in_matches_settings(self, test_settings: Settings) -> None:
        _, expires_in = create_access_token(uuid.uuid4(), settings=test_settings)
        assert expires_in == test_settings.access_token_expire_minutes

    def test_token_has_three_jwt_segments(self, test_settings: Settings) -> None:
        token, _ = create_access_token(uuid.uuid4(), settings=test_settings)
        assert len(token.split(".")) == 3

    def test_sub_claim_is_the_user_id_as_string(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, settings=test_settings)
        raw_claims = raw_jwt.decode(
            token, test_settings.secret_key, algorithms=["HS256"]
        )
        assert raw_claims["sub"] == str(user_id)

    def test_exp_claim_is_a_unix_timestamp_int(self, test_settings: Settings) -> None:
        token, _ = create_access_token(uuid.uuid4(), settings=test_settings)
        raw_claims = raw_jwt.decode(
            token, test_settings.secret_key, algorithms=["HS256"]
        )
        assert isinstance(raw_claims["exp"], int)

    def test_uses_get_settings_singleton_when_none_passed(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        """When settings=None (the default), create_access_token must
        resolve via get_settings() rather than failing or using some
        other source -- patch the exact import target auth.py uses."""
        monkeypatch.setattr("backend.services.auth.get_settings", lambda: test_settings)
        token, expires_in = create_access_token(uuid.uuid4())
        assert isinstance(token, str)
        assert expires_in == test_settings.access_token_expire_minutes


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


class TestDecodeAccessToken:
    def test_valid_token_decodes_to_matching_sub(self, test_settings: Settings) -> None:
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, settings=test_settings)
        payload = decode_access_token(token, settings=test_settings)
        assert payload.sub == str(user_id)

    def test_garbage_string_raises_invalid_token_error(
        self, test_settings: Settings
    ) -> None:
        with pytest.raises(InvalidTokenError):
            decode_access_token("not-a-jwt-at-all", settings=test_settings)

    def test_token_signed_with_wrong_secret_raises(
        self, test_settings: Settings
    ) -> None:
        wrong_secret_token = raw_jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": 9999999999},
            "a-completely-different-secret-key-value",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(wrong_secret_token, settings=test_settings)

    def test_expired_token_raises_invalid_token_error(
        self, test_settings: Settings
    ) -> None:
        with freeze_time("2026-01-01 00:00:00"):
            token, _ = create_access_token(uuid.uuid4(), settings=test_settings)
        # access_token_expire_minutes is 60 in test_settings -- jump
        # well past that so the token is unambiguously expired.
        with freeze_time("2026-01-01 02:00:00"):
            with pytest.raises(InvalidTokenError):
                decode_access_token(token, settings=test_settings)

    def test_token_missing_sub_claim_raises(self, test_settings: Settings) -> None:
        token_without_sub = raw_jwt.encode(
            {"exp": 9999999999},
            test_settings.secret_key,
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(token_without_sub, settings=test_settings)

    def test_uses_get_settings_singleton_when_none_passed(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        monkeypatch.setattr("backend.services.auth.get_settings", lambda: test_settings)
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id, settings=test_settings)
        payload = decode_access_token(token)
        assert payload.sub == str(user_id)
