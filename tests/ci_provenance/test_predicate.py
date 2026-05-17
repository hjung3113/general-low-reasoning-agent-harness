"""S07-prep step 2 — §3.5.1 CI authorization predicate tests.

Design refs:
  - §3.5.1  Non-TTY CI authorization predicate algorithm + provider allowlist
  - §12.4   OIDC claim pinning (shapes verified here at stub level)
  - §3.4    Exit codes: all failures exit 6

Fault classes asserted:
  - non_tty_authorization_unverified          exit 6  (steps 1, 3, 4)
  - ci_bot_identity_overlaps_human_approver   exit 6  (step 2)
  - ci_provider_ambiguous                     exit 6  (step 3 dual-marker)
  - ci_oidc_unreachable                       exit 6  (step 5)
  - ci_oidc_claim_mismatch                    exit 6  (step 6)

Test seams:
  - oidc_fetcher / oidc_verifier injected callables (no real network)
  - TEST-ONLY env vars HARNESS_TEST_OIDC_TOKEN_<PROVIDER> and
    HARNESS_TEST_OIDC_CLAIMS_<PROVIDER> (JSON) exercised via monkeypatch
"""

from __future__ import annotations

import json

import pytest

from lib.ci_provenance import (
    CiBotIdentityOverlapsHumanApprover,
    CiOidcClaimMismatch,
    CiOidcUnreachable,
    CiPredicateError,
    CiProviderAmbiguous,
    CiProvenanceResult,
    NonTtyAuthorizationUnverified,
    ci_predicate_satisfied,
)


# ---------------------------------------------------------------------------
# Shared helpers / minimal env builders
# ---------------------------------------------------------------------------

_GITHUB_REQUIRED = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "12345",
    "GITHUB_REPOSITORY": "acme/repo",
    "GITHUB_SHA": "abc123def456",
    "GITHUB_WORKFLOW": "ci.yml",
    "GITHUB_RUN_ATTEMPT": "1",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.githubusercontent.com/token",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "gha_bearer_token",
}

_GITLAB_REQUIRED = {
    "GITLAB_CI": "true",
    "CI_JOB_ID": "99",
    "CI_PIPELINE_ID": "1000",
    "CI_PROJECT_PATH": "acme/repo",
    "CI_COMMIT_SHA": "deadbeef",
    "CI_RUNNER_ID": "runner-42",
    "CI_JOB_JWT_V2": "v2.jwt.token",
}

_BUILDKITE_REQUIRED = {
    "BUILDKITE": "true",
    "BUILDKITE_BUILD_ID": "build-uuid",
    "BUILDKITE_JOB_ID": "job-uuid",
    "BUILDKITE_PIPELINE_SLUG": "my-pipeline",
    "BUILDKITE_COMMIT": "cafebabe",
    "BUILDKITE_AGENT_ID": "agent-1",
}

_BASE_ENV = {
    "HARNESS_AUTOMATION": "phase",
    "HARNESS_BY_TRUST": "ci-bot@example.com",
}

_APPROVERS: set[str] = {"alice@example.com", "bob@example.com"}

_FAKE_CLAIMS = {
    "iss": "https://token.actions.githubusercontent.com",
    "sub": "repo:acme/repo:ref:refs/heads/main",
    "repository": "acme/repo",
    "ref": "refs/heads/main",
    "sha": "abc123def456",
}


def _injected_fetcher(token: str = "fake.jwt.token"):
    """Return a simple fetcher that always succeeds."""
    def _f(url: str) -> str:  # noqa: ARG001
        return token
    return _f


def _injected_verifier(claims: dict | None = None):
    """Return a verifier that always returns the given claims."""
    if claims is None:
        claims = _FAKE_CLAIMS.copy()

    def _v(token: str, expected: dict) -> dict:  # noqa: ARG001
        return claims
    return _v


def _raising_fetcher(exc: Exception):
    def _f(url: str) -> str:  # noqa: ARG001
        raise exc
    return _f


def _raising_verifier(exc: Exception):
    def _v(token: str, expected: dict) -> dict:  # noqa: ARG001
        raise exc
    return _v


def _github_env(**overrides) -> dict:
    return {**_BASE_ENV, **_GITHUB_REQUIRED, **overrides}


def _gitlab_env(**overrides) -> dict:
    return {**_BASE_ENV, **_GITLAB_REQUIRED, **overrides}


def _buildkite_env(**overrides) -> dict:
    return {**_BASE_ENV, **_BUILDKITE_REQUIRED, **overrides}


# ===========================================================================
# Happy-path tests
# ===========================================================================


class TestHappyPathGitHubActions:
    """§3.5.1 step 7 — full success for GitHub Actions provider."""

    def test_returns_ci_provenance_result(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert isinstance(result, CiProvenanceResult)

    def test_authorization_source(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert result.authorization_source == "ci_github_actions"

    def test_ci_oidc_verified_true(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert result.ci_oidc_verified is True

    def test_ci_signature_snapshot(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        # Must contain exactly the required vars
        assert result.ci_signature == {
            "GITHUB_RUN_ID": "12345",
            "GITHUB_REPOSITORY": "acme/repo",
            "GITHUB_SHA": "abc123def456",
            "GITHUB_WORKFLOW": "ci.yml",
            "GITHUB_RUN_ATTEMPT": "1",
        }

    def test_bot_identity_populated(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert result.bot_identity == "ci-bot@example.com"

    def test_bot_identity_distinct_from_approvers(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert result.bot_identity_distinct_from_approvers is True

    def test_ci_oidc_claims_shape(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(_FAKE_CLAIMS),
        )
        # Must carry the §3.5.1 / §12.4 claim subset
        for key in ("iss", "sub", "repository", "ref", "sha"):
            assert key in result.ci_oidc_claims

    def test_all_six_audit_fields_present(self):
        """§3.5.1 audit fields — CiProvenanceResult must have all six fields."""
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        # Verify all dataclass fields are set (not None for required ones)
        assert result.authorization_source is not None
        assert isinstance(result.ci_signature, dict)
        assert isinstance(result.ci_oidc_verified, bool)
        assert isinstance(result.ci_oidc_claims, dict)
        assert result.bot_identity is not None
        assert isinstance(result.bot_identity_distinct_from_approvers, bool)


class TestHappyPathGitLabCI:
    """Happy path for GitLab CI provider."""

    def test_returns_result(self):
        claims = {
            "iss": "https://gitlab.com",
            "sub": "project_path:acme/repo:ref_type:branch:ref:main",
            "repository": "acme/repo",
            "ref": "main",
            "sha": "deadbeef",
        }
        result = ci_predicate_satisfied(
            env=_gitlab_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(claims),
        )
        assert result.authorization_source == "ci_gitlab_ci"
        assert result.ci_oidc_verified is True
        assert result.ci_signature["CI_JOB_ID"] == "99"
        assert result.bot_identity == "ci-bot@example.com"

    def test_ci_signature_contains_required_vars(self):
        result = ci_predicate_satisfied(
            env=_gitlab_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        expected_keys = {
            "CI_JOB_ID", "CI_PIPELINE_ID", "CI_PROJECT_PATH",
            "CI_COMMIT_SHA", "CI_RUNNER_ID",
        }
        assert set(result.ci_signature.keys()) == expected_keys


class TestHappyPathBuildkite:
    """Happy path for Buildkite provider."""

    def test_returns_result(self):
        claims = {
            "iss": "https://agent.buildkite.com",
            "sub": "organization_slug:acme:pipeline_slug:my-pipeline",
            "repository": "acme/repo",
            "ref": "main",
            "sha": "cafebabe",
        }
        result = ci_predicate_satisfied(
            env=_buildkite_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(claims),
        )
        assert result.authorization_source == "ci_buildkite"
        assert result.ci_oidc_verified is True

    def test_ci_signature_contains_required_vars(self):
        result = ci_predicate_satisfied(
            env=_buildkite_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        expected_keys = {
            "BUILDKITE_BUILD_ID", "BUILDKITE_JOB_ID", "BUILDKITE_PIPELINE_SLUG",
            "BUILDKITE_COMMIT", "BUILDKITE_AGENT_ID",
        }
        assert set(result.ci_signature.keys()) == expected_keys


# ===========================================================================
# Step 1 — HARNESS_AUTOMATION failures
# ===========================================================================


class TestStep1AutomationMissing:
    """NonTtyAuthorizationUnverified on missing/bad HARNESS_AUTOMATION."""

    def test_missing_automation_raises(self):
        env = {**_github_env()}
        del env["HARNESS_AUTOMATION"]
        with pytest.raises(NonTtyAuthorizationUnverified) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert exc_info.value.exit_code == 6
        assert exc_info.value.sub_reason == "non_tty_authorization_unverified"

    def test_wrong_automation_value_raises(self):
        env = _github_env(HARNESS_AUTOMATION="manual")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_automation_chain_accepted(self):
        """HARNESS_AUTOMATION=chain must also work (not just 'phase')."""
        env = _github_env(HARNESS_AUTOMATION="chain")
        result = ci_predicate_satisfied(
            env=env,
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(),
        )
        assert result.authorization_source == "ci_github_actions"


# ===========================================================================
# Step 2 — HARNESS_BY_TRUST failures
# ===========================================================================


class TestStep2BotIdentity:
    """NonTtyAuthorizationUnverified + CiBotIdentityOverlapsHumanApprover."""

    def test_missing_by_trust_raises(self):
        env = {**_github_env()}
        del env["HARNESS_BY_TRUST"]
        with pytest.raises(NonTtyAuthorizationUnverified) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert exc_info.value.exit_code == 6

    def test_empty_by_trust_raises(self):
        env = _github_env(HARNESS_BY_TRUST="")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_whitespace_only_by_trust_raises(self):
        env = _github_env(HARNESS_BY_TRUST="   ")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_by_trust_with_nul_raises(self):
        """NUL char is in _C0_CONTROLS — must be rejected."""
        env = _github_env(HARNESS_BY_TRUST="ci-bot\x00@example.com")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_by_trust_with_crlf_raises(self):
        """CR (0x0d) is a C0 control — must be rejected."""
        env = _github_env(HARNESS_BY_TRUST="ci-bot\r\n@example.com")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_by_trust_with_bidi_control_raises(self):
        """Unicode bidi control (RLM U+200F) — must be rejected."""
        env = _github_env(HARNESS_BY_TRUST="ci-bot‏@example.com")
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_by_trust_matches_human_approver_raises(self):
        """Bot identity in install_record_approvers → CiBotIdentityOverlapsHumanApprover."""
        env = _github_env(HARNESS_BY_TRUST="alice@example.com")
        with pytest.raises(CiBotIdentityOverlapsHumanApprover) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert exc_info.value.exit_code == 6
        assert exc_info.value.sub_reason == "ci_bot_identity_overlaps_human_approver"

    def test_by_trust_case_insensitive_overlap_raises(self):
        """Overlap check is case-insensitive (matches phase_approve pattern)."""
        env = _github_env(HARNESS_BY_TRUST="ALICE@EXAMPLE.COM")
        with pytest.raises(CiBotIdentityOverlapsHumanApprover):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )


# ===========================================================================
# Step 3 — provider marker failures
# ===========================================================================


class TestStep3ProviderMarkers:
    """Zero / two+ markers."""

    def test_no_provider_marker_raises(self):
        """No CI provider marker → NonTtyAuthorizationUnverified."""
        env = {**_BASE_ENV}  # no provider vars
        with pytest.raises(NonTtyAuthorizationUnverified) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert "No recognized CI provider" in str(exc_info.value)

    def test_two_provider_markers_raises(self):
        """GITHUB_ACTIONS + GITLAB_CI both set → CiProviderAmbiguous."""
        env = {
            **_BASE_ENV,
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "12345",
            "GITHUB_REPOSITORY": "acme/repo",
            "GITHUB_SHA": "abc123",
            "GITHUB_WORKFLOW": "ci.yml",
            "GITHUB_RUN_ATTEMPT": "1",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/token",
            "GITLAB_CI": "true",
            "CI_JOB_ID": "99",
            "CI_PIPELINE_ID": "1000",
            "CI_PROJECT_PATH": "acme/repo",
            "CI_COMMIT_SHA": "deadbeef",
            "CI_RUNNER_ID": "runner-42",
        }
        with pytest.raises(CiProviderAmbiguous) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert exc_info.value.exit_code == 6
        assert exc_info.value.sub_reason == "ci_provider_ambiguous"

    def test_circleci_marker_only_raises(self):
        """circleci is NOT in the v0.7 allowlist → NonTtyAuthorizationUnverified."""
        env = {
            **_BASE_ENV,
            "CIRCLECI": "true",
            "CIRCLE_BUILD_NUM": "123",
        }
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_jenkins_marker_only_raises(self):
        """jenkins is NOT in the v0.7 allowlist → NonTtyAuthorizationUnverified."""
        env = {
            **_BASE_ENV,
            "JENKINS_URL": "https://ci.example.com",
            "BUILD_NUMBER": "42",
        }
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )


# ===========================================================================
# Step 4 — required variable missing
# ===========================================================================


class TestStep4RequiredVarsMissing:
    """Provider marker present but a required var is absent."""

    def test_github_missing_run_id_raises(self):
        env = _github_env()
        del env["GITHUB_RUN_ID"]
        with pytest.raises(NonTtyAuthorizationUnverified) as exc_info:
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )
        assert "GITHUB_RUN_ID" in str(exc_info.value)

    def test_github_missing_repository_raises(self):
        env = _github_env()
        del env["GITHUB_REPOSITORY"]
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_gitlab_missing_job_id_raises(self):
        env = _gitlab_env()
        del env["CI_JOB_ID"]
        with pytest.raises(NonTtyAuthorizationUnverified):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )


# ===========================================================================
# Step 5 — OIDC fetch failures
# ===========================================================================


class TestStep5OidcFetch:
    """CiOidcUnreachable propagation."""

    def test_fetcher_raises_ci_oidc_unreachable_propagated(self):
        with pytest.raises(CiOidcUnreachable) as exc_info:
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_raising_fetcher(
                    CiOidcUnreachable("network timeout")
                ),
                oidc_verifier=_injected_verifier(),
            )
        assert exc_info.value.exit_code == 6
        assert exc_info.value.sub_reason == "ci_oidc_unreachable"

    def test_fetcher_raises_generic_exception_wrapped_as_unreachable(self):
        """Non-CiPredicateError exceptions from the fetcher become CiOidcUnreachable."""
        with pytest.raises(CiOidcUnreachable):
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_raising_fetcher(ConnectionError("refused")),
                oidc_verifier=_injected_verifier(),
            )

    def test_missing_token_url_raises_unreachable(self):
        """GitHub provider: missing ACTIONS_ID_TOKEN_REQUEST_URL → CiOidcUnreachable."""
        env = _github_env()
        del env["ACTIONS_ID_TOKEN_REQUEST_URL"]
        with pytest.raises(CiOidcUnreachable):
            ci_predicate_satisfied(
                env=env,
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_injected_verifier(),
            )

    def test_default_fetcher_stub_no_env_var_raises_unreachable(self, monkeypatch):
        """Default TEST-ONLY stub raises CiOidcUnreachable when env var absent."""
        # Remove the test env var so default stub raises
        monkeypatch.delenv("HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS", raising=False)
        with pytest.raises(CiOidcUnreachable):
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                # No fetcher — uses default stub
            )


# ===========================================================================
# Step 6 — OIDC claim verification failures
# ===========================================================================


class TestStep6OidcClaimVerification:
    """CiOidcClaimMismatch propagation."""

    def test_verifier_raises_claim_mismatch_propagated(self):
        with pytest.raises(CiOidcClaimMismatch) as exc_info:
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_raising_verifier(
                    CiOidcClaimMismatch("repository mismatch")
                ),
            )
        assert exc_info.value.exit_code == 6
        assert exc_info.value.sub_reason == "ci_oidc_claim_mismatch"

    def test_verifier_raises_generic_exception_wrapped_as_claim_mismatch(self):
        """Non-CiPredicateError exceptions from the verifier become CiOidcClaimMismatch."""
        with pytest.raises(CiOidcClaimMismatch):
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                oidc_verifier=_raising_verifier(ValueError("bad JWT")),
            )

    def test_default_verifier_stub_no_env_var_raises_mismatch(self, monkeypatch):
        """Default TEST-ONLY stub raises CiOidcClaimMismatch when env var absent."""
        monkeypatch.delenv("HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS", raising=False)
        # Provide a custom fetcher so we get past step 5
        with pytest.raises(CiOidcClaimMismatch):
            ci_predicate_satisfied(
                env=_github_env(),
                install_record_approvers=_APPROVERS,
                oidc_fetcher=_injected_fetcher(),
                # No verifier — uses default stub
            )

    def test_default_verifier_stub_with_env_var_succeeds(self, monkeypatch):
        """Default TEST-ONLY stub parses HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS."""
        monkeypatch.setenv(
            "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS",
            json.dumps(_FAKE_CLAIMS),
        )
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            # No verifier — uses default stub that reads env var
        )
        assert result.ci_oidc_verified is True
        assert result.ci_oidc_claims["iss"] == _FAKE_CLAIMS["iss"]

    def test_default_fetcher_and_verifier_both_env_vars(self, monkeypatch):
        """Both TEST-ONLY env vars set → full success without any injected callables."""
        monkeypatch.setenv(
            "HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS",
            "eyJhbGciOiJSUzI1NiJ9.stub",
        )
        monkeypatch.setenv(
            "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS",
            json.dumps(_FAKE_CLAIMS),
        )
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
        )
        assert result.authorization_source == "ci_github_actions"
        assert result.ci_oidc_verified is True


# ===========================================================================
# Exception hierarchy
# ===========================================================================


class TestExceptionHierarchy:
    """All fault classes are CiPredicateError subclasses with exit_code=6."""

    @pytest.mark.parametrize("exc_class", [
        NonTtyAuthorizationUnverified,
        CiBotIdentityOverlapsHumanApprover,
        CiProviderAmbiguous,
        CiOidcUnreachable,
        CiOidcClaimMismatch,
    ])
    def test_is_subclass_of_ci_predicate_error(self, exc_class):
        assert issubclass(exc_class, CiPredicateError)

    @pytest.mark.parametrize("exc_class,msg,expected_sub_reason", [
        (NonTtyAuthorizationUnverified, "test", "non_tty_authorization_unverified"),
        (CiBotIdentityOverlapsHumanApprover, "test", "ci_bot_identity_overlaps_human_approver"),
        (CiProviderAmbiguous, "test", "ci_provider_ambiguous"),
        (CiOidcUnreachable, "test", "ci_oidc_unreachable"),
        (CiOidcClaimMismatch, "test", "ci_oidc_claim_mismatch"),
    ])
    def test_exit_code_is_6(self, exc_class, msg, expected_sub_reason):
        exc = exc_class(msg)
        assert exc.exit_code == 6
        assert exc.sub_reason == expected_sub_reason

    @pytest.mark.parametrize("exc_class", [
        NonTtyAuthorizationUnverified,
        CiBotIdentityOverlapsHumanApprover,
        CiProviderAmbiguous,
        CiOidcUnreachable,
        CiOidcClaimMismatch,
    ])
    def test_is_oserror_subclass(self, exc_class):
        """CiPredicateError inherits from OSError per spec."""
        assert issubclass(exc_class, OSError)


# ===========================================================================
# Audit field shape — §3.5.1 + §12.4 (claim pinning)
# ===========================================================================


class TestAuditFieldShape:
    """CiProvenanceResult carries all 6 audit fields with correct types/values."""

    def test_all_fields_present_and_typed(self):
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(_FAKE_CLAIMS),
        )
        # authorization_source
        assert isinstance(result.authorization_source, str)
        assert result.authorization_source.startswith("ci_")
        # ci_signature — dict with string keys/values
        assert isinstance(result.ci_signature, dict)
        assert all(isinstance(k, str) and isinstance(v, str)
                   for k, v in result.ci_signature.items())
        # ci_oidc_verified
        assert result.ci_oidc_verified is True
        # ci_oidc_claims — dict with §3.5.1 claim subset
        assert isinstance(result.ci_oidc_claims, dict)
        # bot_identity — non-empty string
        assert isinstance(result.bot_identity, str)
        assert len(result.bot_identity) > 0
        # bot_identity_distinct_from_approvers — bool, must be True
        assert result.bot_identity_distinct_from_approvers is True

    def test_claim_subset_keys(self):
        """§12.4 — ci_oidc_claims must carry iss/sub/repository/ref/sha."""
        result = ci_predicate_satisfied(
            env=_github_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(_FAKE_CLAIMS),
        )
        for key in ("iss", "sub", "repository", "ref", "sha"):
            assert key in result.ci_oidc_claims, f"Missing claim key: {key!r}"

    def test_gitlab_audit_fields(self):
        gitlab_claims = {
            "iss": "https://gitlab.com",
            "sub": "project_path:acme/repo:ref_type:branch:ref:main",
            "repository": "acme/repo",
            "ref": "main",
            "sha": "deadbeef",
        }
        result = ci_predicate_satisfied(
            env=_gitlab_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(gitlab_claims),
        )
        assert result.authorization_source == "ci_gitlab_ci"
        assert result.ci_signature["CI_PROJECT_PATH"] == "acme/repo"
        assert result.ci_oidc_claims["iss"] == "https://gitlab.com"

    def test_buildkite_audit_fields(self):
        bk_claims = {
            "iss": "https://agent.buildkite.com",
            "sub": "organization_slug:acme:pipeline_slug:my-pipeline",
            "repository": "acme/repo",
            "ref": "main",
            "sha": "cafebabe",
        }
        result = ci_predicate_satisfied(
            env=_buildkite_env(),
            install_record_approvers=_APPROVERS,
            oidc_fetcher=_injected_fetcher(),
            oidc_verifier=_injected_verifier(bk_claims),
        )
        assert result.authorization_source == "ci_buildkite"
        assert result.ci_signature["BUILDKITE_PIPELINE_SLUG"] == "my-pipeline"
        assert result.ci_oidc_claims["iss"] == "https://agent.buildkite.com"
