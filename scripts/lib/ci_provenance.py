"""CI provenance predicate — §3.5.1 non-TTY CI authorization.

Exported surface
----------------
* `CiPredicateError`                  — base exception (exit_code=6)
* `NonTtyAuthorizationUnverified`     — step 1/3/4 failure
* `CiBotIdentityOverlapsHumanApprover` — step 2 overlap
* `CiProviderAmbiguous`               — two provider markers set
* `CiOidcUnreachable`                 — OIDC fetch network failure
* `CiOidcClaimMismatch`               — OIDC claim verification failure
* `CiProvenanceResult`                — success dataclass (all 6 audit fields)
* `ci_predicate_satisfied(...)`       — §3.5.1 algorithm

Design
------
Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §3.5.1 + §12.4

Algorithm (must run under state lock, before any mutation):

  1. HARNESS_AUTOMATION ∈ {"phase","chain"} present in env.
     Else → NonTtyAuthorizationUnverified.
  2. HARNESS_BY_TRUST present, non-empty, passes sanitization
     (same _FORBIDDEN_CHARS set as phase_approve), NOT in
     install_record_approvers.  Else → CiBotIdentityOverlapsHumanApprover.
  3. Exactly ONE provider marker from the allowlist is present in env.
     Zero markers → NonTtyAuthorizationUnverified.
     Two+ markers → CiProviderAmbiguous.
  4. All required vars for that provider are present.
     Else → NonTtyAuthorizationUnverified.
  5. Fetch OIDC token via `oidc_fetcher`.  Failure → CiOidcUnreachable.
  6. Verify token + claims via `oidc_verifier`.  Mismatch → CiOidcClaimMismatch.
  7. Return CiProvenanceResult.

Test seams
----------
Two callables are injected so tests never hit the network:

  oidc_fetcher(url: str) -> str
      Default stub reads env var HARNESS_TEST_OIDC_TOKEN_<PROVIDER>
      (e.g. HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS).  If absent,
      raises CiOidcUnreachable.  TEST-ONLY — requires HARNESS_OIDC_TEST_MODE=1
      in environment (see _is_test_mode()).  Production wiring deferred to
      S07-prep step 3.

  oidc_verifier(token: str, expected_claims: dict) -> dict
      Default stub reads env var HARNESS_TEST_OIDC_CLAIMS_<PROVIDER>
      (JSON) and returns parsed dict.  If the env var is absent, raises
      CiOidcClaimMismatch.  TEST-ONLY — requires HARNESS_OIDC_TEST_MODE=1
      in environment.  Production JWT/crypto wiring deferred to S07-prep step 3.

Production-mode safety gate
----------------------------
When ``oidc_fetcher=None`` or ``oidc_verifier=None`` is passed AND
``HARNESS_OIDC_TEST_MODE`` is NOT set to ``"1"``, ``ci_predicate_satisfied``
raises ``CiOidcUnreachable`` immediately — it refuses to fall back to the
test stubs in production environments.

To enable the test stubs in CI/unit tests set:
    HARNESS_OIDC_TEST_MODE=1  (explicit opt-in)

This env var is TEST-ONLY and must never be set in real CI pipelines.

The real HTTP + cryptographic verification path (JWKS fetch, RS256
signature verification, jti replay defense) is deferred to a follow-up
step per §12.4.

Provider allowlist (§3.5.1 table)
----------------------------------
* github_actions — marker GITHUB_ACTIONS=true
    Required: GITHUB_RUN_ID, GITHUB_REPOSITORY, GITHUB_SHA,
              GITHUB_WORKFLOW, GITHUB_RUN_ATTEMPT
    Token URL: ACTIONS_ID_TOKEN_REQUEST_URL (+ ACTIONS_ID_TOKEN_REQUEST_TOKEN)
    Claims: repository, sha, workflow, run_id

* gitlab_ci — marker GITLAB_CI=true
    Required: CI_JOB_ID, CI_PIPELINE_ID, CI_PROJECT_PATH,
              CI_COMMIT_SHA, CI_RUNNER_ID
    Token: CI_JOB_JWT_V2

* buildkite — marker BUILDKITE=true
    Required: BUILDKITE_BUILD_ID, BUILDKITE_JOB_ID,
              BUILDKITE_PIPELINE_SLUG, BUILDKITE_COMMIT,
              BUILDKITE_AGENT_ID
    Token: Buildkite OIDC token

circleci and jenkins are deliberately NOT in the allowlist (§3.5.1);
their markers produce NonTtyAuthorizationUnverified.

Deferred
--------
* Real HTTP OIDC fetch + JWKS crypto verify (S07-prep step 3 / follow-up)
* phase_autopilot wiring (step 3 of the series)
* CLI argparse wiring
* --allow-network source check (separate step)
* jti replay defense (§12.4)
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Callable, Mapping, Optional

# ---------------------------------------------------------------------------
# Sanitization — same charset as phase_approve._FORBIDDEN_CHARS (§12.6)
# ---------------------------------------------------------------------------

# C0 controls (0x00–0x1f) and DEL (0x7f)
_C0_CONTROLS = frozenset(chr(c) for c in range(0x00, 0x20))
# Unicode bidi/isolate formatting controls (Trojan-Source class)
_BIDI_CONTROLS = frozenset([
    "‎", "‏",           # LRM, RLM
    "‪", "‫", "‬", "‭", "‮",  # LRE/RLE/PDF/LRO/RLO
    "⁦", "⁧", "⁨", "⁩",             # LRI/RLI/FSI/PDI
])
# Zero-width joiners, ALM, LS, PS (§3.1.1 / §12.6 Trojan-Source parity)
_EXTRA_INVISIBLES = frozenset([
    "‌",  # ZERO WIDTH NON-JOINER
    "‍",  # ZERO WIDTH JOINER
    "؜",  # ARABIC LETTER MARK
    " ",  # LINE SEPARATOR
    " ",  # PARAGRAPH SEPARATOR
])
_FORBIDDEN_CHARS = _C0_CONTROLS | {"\x7f"} | _BIDI_CONTROLS | _EXTRA_INVISIBLES


def _has_forbidden_chars(s: str) -> bool:
    return any(c in _FORBIDDEN_CHARS for c in s)


# ---------------------------------------------------------------------------
# Provider allowlist (§3.5.1)
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, dict] = {
    "github_actions": {
        "marker_var": "GITHUB_ACTIONS",
        "marker_value": "true",
        "required_vars": [
            "GITHUB_RUN_ID",
            "GITHUB_REPOSITORY",
            "GITHUB_SHA",
            "GITHUB_WORKFLOW",
            "GITHUB_RUN_ATTEMPT",
        ],
        # URL env var for OIDC token request (GitHub-specific)
        "token_url_var": "ACTIONS_ID_TOKEN_REQUEST_URL",
        # Claim keys to pull from the verified OIDC token
        "claim_keys": ["iss", "sub", "repository", "ref", "sha"],
        # Authorization source string for audit
        "authorization_source": "ci_github_actions",
        # TEST env var suffix (HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS)
        "test_env_suffix": "GITHUB_ACTIONS",
    },
    "gitlab_ci": {
        "marker_var": "GITLAB_CI",
        "marker_value": "true",
        "required_vars": [
            "CI_JOB_ID",
            "CI_PIPELINE_ID",
            "CI_PROJECT_PATH",
            "CI_COMMIT_SHA",
            "CI_RUNNER_ID",
        ],
        # GitLab provides a JWT directly in env — no URL needed
        "token_url_var": None,
        "claim_keys": ["iss", "sub", "repository", "ref", "sha"],
        "authorization_source": "ci_gitlab_ci",
        "test_env_suffix": "GITLAB_CI",
    },
    "buildkite": {
        "marker_var": "BUILDKITE",
        "marker_value": "true",
        "required_vars": [
            "BUILDKITE_BUILD_ID",
            "BUILDKITE_JOB_ID",
            "BUILDKITE_PIPELINE_SLUG",
            "BUILDKITE_COMMIT",
            "BUILDKITE_AGENT_ID",
        ],
        "token_url_var": None,
        "claim_keys": ["iss", "sub", "repository", "ref", "sha"],
        "authorization_source": "ci_buildkite",
        "test_env_suffix": "BUILDKITE",
    },
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CiPredicateError(OSError):
    """Base class for all CI predicate failures.

    All subclasses carry ``exit_code=6`` and a ``sub_reason`` string that
    maps to the §3.4 taxonomy bucket.
    """

    exit_code: int = 6

    def __init__(self, message: str, sub_reason: str) -> None:
        super().__init__(message)
        self.sub_reason = sub_reason
        self.message = message

    def __str__(self) -> str:
        return f"{self.sub_reason}: {self.message}"


class NonTtyAuthorizationUnverified(CiPredicateError):
    """Raised when the §3.5.1 predicate cannot be satisfied and no TTY is
    present.  exit_code=6, sub_reason='non_tty_authorization_unverified'."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="non_tty_authorization_unverified")


class CiBotIdentityOverlapsHumanApprover(CiPredicateError):
    """HARNESS_BY_TRUST matches an install-record human approver.
    exit_code=6, sub_reason='ci_bot_identity_overlaps_human_approver'."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="ci_bot_identity_overlaps_human_approver")


class CiProviderAmbiguous(CiPredicateError):
    """Two or more provider markers set simultaneously.
    exit_code=6, sub_reason='ci_provider_ambiguous'."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="ci_provider_ambiguous")


class CiOidcUnreachable(CiPredicateError):
    """OIDC token fetch failed (network error, missing URL env var, etc.).
    exit_code=6, sub_reason='ci_oidc_unreachable'."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="ci_oidc_unreachable")


class CiOidcClaimMismatch(CiPredicateError):
    """OIDC token claims failed verification.
    exit_code=6, sub_reason='ci_oidc_claim_mismatch'."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="ci_oidc_claim_mismatch")


class CiOidcJtiReplayed(CiPredicateError):
    """OIDC token jti claim was already consumed (replay detected).
    exit_code=6, sub_reason='ci_oidc_jti_replay' (§12.4 jti replay defense)."""

    exit_code = 6

    def __init__(self, message: str) -> None:
        super().__init__(message, sub_reason="ci_oidc_jti_replay")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CiProvenanceResult:
    """Audit payload returned on success.

    All six fields MUST be present; callers write them verbatim into
    ``verb=phase.autopilot.start`` audit entries (§3.5.1 audit fields).
    """

    authorization_source: str   # "ci_github_actions" / "ci_gitlab_ci" / "ci_buildkite"
    ci_signature: dict           # snapshot of provider's required env vars
    ci_oidc_verified: bool       # True after (stub) verification
    ci_oidc_claims: dict         # {iss, sub, repository, ref, sha} subset
    bot_identity: str            # HARNESS_BY_TRUST value
    bot_identity_distinct_from_approvers: bool  # MUST be True


# ---------------------------------------------------------------------------
# Test-mode gate
# ---------------------------------------------------------------------------


def _is_test_mode() -> bool:
    """Return True ONLY if HARNESS_OIDC_TEST_MODE=1 is set in os.environ.

    TEST-ONLY explicit opt-in.  Must NOT be set in real CI pipelines.
    Gating on this env var prevents the test stubs (which accept any
    attacker-controlled env var as a valid OIDC token) from running in
    production.
    """
    return os.environ.get("HARNESS_OIDC_TEST_MODE", "") == "1"


# ---------------------------------------------------------------------------
# Default test-seam implementations (TEST-ONLY — requires HARNESS_OIDC_TEST_MODE=1)
# ---------------------------------------------------------------------------

def _test_oidc_fetcher_factory(provider_key: str) -> Callable[[str], str]:
    """Return a fetcher that reads HARNESS_TEST_OIDC_TOKEN_<SUFFIX>.

    TEST-ONLY — requires HARNESS_OIDC_TEST_MODE=1.  Production HTTP wiring
    is deferred to S07-prep step 3.
    """
    suffix = _PROVIDERS[provider_key]["test_env_suffix"]
    env_var = f"HARNESS_TEST_OIDC_TOKEN_{suffix}"

    def _fetcher(url: str) -> str:  # noqa: ARG001 — url intentionally unused in stub
        token = os.environ.get(env_var, "")
        if not token:
            raise CiOidcUnreachable(
                f"OIDC token not available: {env_var} not set "
                f"(TEST-ONLY stub; production HTTP wiring deferred)"
            )
        return token

    return _fetcher


def _test_oidc_verifier_factory(provider_key: str) -> Callable[[str, dict], dict]:
    """Return a verifier that reads HARNESS_TEST_OIDC_CLAIMS_<SUFFIX> (JSON).

    TEST-ONLY — requires HARNESS_OIDC_TEST_MODE=1.  Production JWT/crypto
    wiring is deferred to S07-prep step 3.
    """
    suffix = _PROVIDERS[provider_key]["test_env_suffix"]
    env_var = f"HARNESS_TEST_OIDC_CLAIMS_{suffix}"

    def _verifier(token: str, expected_claims: dict) -> dict:  # noqa: ARG001
        raw = os.environ.get(env_var, "")
        if not raw:
            raise CiOidcClaimMismatch(
                f"OIDC claims not available: {env_var} not set "
                f"(TEST-ONLY stub; production JWT verify deferred)"
            )
        try:
            claims = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CiOidcClaimMismatch(
                f"OIDC claims JSON invalid in {env_var}: {exc}"
            ) from exc
        if not isinstance(claims, dict):
            raise CiOidcClaimMismatch(
                f"OIDC claims in {env_var} must be a JSON object"
            )
        return claims

    return _verifier


# ---------------------------------------------------------------------------
# Public predicate
# ---------------------------------------------------------------------------


def ci_predicate_satisfied(
    *,
    env: Mapping[str, str],
    install_record_approvers: set[str],
    oidc_fetcher: Optional[Callable[[str], str]] = None,
    oidc_verifier: Optional[Callable[[str, dict], dict]] = None,
) -> CiProvenanceResult:
    """Evaluate the §3.5.1 CI authorization predicate.

    Parameters
    ----------
    env:
        Environment mapping (typically ``os.environ``).  Tests inject a
        plain ``dict`` to avoid touching the real process environment.
    install_record_approvers:
        Lower-cased approver emails from ``install-record.json``.  Used
        to enforce step 2 (bot identity must NOT overlap human approvers).
    oidc_fetcher:
        Callable ``(url: str) -> token_str``.  If ``None``, the
        TEST-ONLY default stub is used (reads
        ``HARNESS_TEST_OIDC_TOKEN_<PROVIDER>``).
    oidc_verifier:
        Callable ``(token: str, expected_claims: dict) -> verified_claims``.
        If ``None``, the TEST-ONLY default stub is used (reads
        ``HARNESS_TEST_OIDC_CLAIMS_<PROVIDER>`` JSON).

    Returns
    -------
    CiProvenanceResult
        On success.  All six audit fields populated.

    Raises
    ------
    NonTtyAuthorizationUnverified
        Steps 1, 3, or 4 fail.
    CiBotIdentityOverlapsHumanApprover
        Step 2 overlap detected.
    CiProviderAmbiguous
        Two or more provider markers present.
    CiOidcUnreachable
        Step 5: OIDC fetch raised.
    CiOidcClaimMismatch
        Step 6: claim verification failed.
    """

    # ------------------------------------------------------------------
    # Step 1 — HARNESS_AUTOMATION ∈ {"phase", "chain"}
    # ------------------------------------------------------------------
    automation = env.get("HARNESS_AUTOMATION", "")
    if automation not in ("phase", "chain"):
        raise NonTtyAuthorizationUnverified(
            f"HARNESS_AUTOMATION not in {{\"phase\",\"chain\"}} "
            f"(got {automation!r}); CI predicate cannot be satisfied"
        )

    # ------------------------------------------------------------------
    # Step 2 — HARNESS_BY_TRUST validation
    # ------------------------------------------------------------------
    bot_identity_raw = env.get("HARNESS_BY_TRUST", "")
    if not bot_identity_raw:
        raise NonTtyAuthorizationUnverified(
            "HARNESS_BY_TRUST is absent or empty; CI predicate cannot be satisfied"
        )
    if _has_forbidden_chars(bot_identity_raw):
        raise NonTtyAuthorizationUnverified(
            "HARNESS_BY_TRUST contains forbidden chars "
            "(NUL / control chars / bidi controls / zero-width chars); "
            "CI predicate cannot be satisfied"
        )
    bot_identity = bot_identity_raw.strip()
    if not bot_identity:
        raise NonTtyAuthorizationUnverified(
            "HARNESS_BY_TRUST is whitespace-only; CI predicate cannot be satisfied"
        )

    # Normalise to lower-case for membership check (match phase_approve pattern)
    if bot_identity.lower() in install_record_approvers:
        raise CiBotIdentityOverlapsHumanApprover(
            f"HARNESS_BY_TRUST {bot_identity!r} matches a human approver; "
            "bot identity must be distinct from all install-record approvers"
        )

    # ------------------------------------------------------------------
    # Step 3 — detect provider markers
    # ------------------------------------------------------------------
    matched_providers: list[str] = []
    for provider_key, spec in _PROVIDERS.items():
        if env.get(spec["marker_var"], "").lower() == spec["marker_value"]:
            matched_providers.append(provider_key)

    if len(matched_providers) == 0:
        raise NonTtyAuthorizationUnverified(
            "No recognized CI provider marker found in environment; "
            "CI predicate cannot be satisfied.  "
            "(circleci and jenkins are not in the v0.7 allowlist)"
        )
    if len(matched_providers) > 1:
        names = ", ".join(matched_providers)
        raise CiProviderAmbiguous(
            f"Multiple CI provider markers set simultaneously: {names}; "
            "exactly one is required"
        )

    provider_key = matched_providers[0]
    spec = _PROVIDERS[provider_key]

    # ------------------------------------------------------------------
    # Step 4 — all required vars present
    # ------------------------------------------------------------------
    missing = [v for v in spec["required_vars"] if not env.get(v, "")]
    if missing:
        raise NonTtyAuthorizationUnverified(
            f"Provider {provider_key!r}: required env vars missing: "
            f"{', '.join(missing)}"
        )

    # Snapshot ci_signature (required vars only, verbatim)
    ci_signature = {v: env.get(v, "") for v in spec["required_vars"]}

    # ------------------------------------------------------------------
    # Step 5 — fetch OIDC token
    # ------------------------------------------------------------------
    if oidc_fetcher is None:
        if not _is_test_mode():
            raise CiOidcUnreachable(
                "production OIDC fetcher not configured; refusing to authorize via "
                "CI predicate. Set HARNESS_OIDC_TEST_MODE=1 ONLY in test environments "
                "to enable the TEST-ONLY env-var stub."
            )
        oidc_fetcher = _test_oidc_fetcher_factory(provider_key)

    # Determine token URL (GitHub uses a URL env var; others have token directly)
    token_url_var = spec.get("token_url_var")
    if token_url_var:
        token_url = env.get(token_url_var, "")
        if not token_url:
            raise CiOidcUnreachable(
                f"Provider {provider_key!r}: {token_url_var} not set; "
                "cannot fetch OIDC token"
            )
    else:
        token_url = f"oidc://{provider_key}"  # synthetic URL for non-URL providers

    # Fetch — propagate CiOidcUnreachable from fetcher
    try:
        token = oidc_fetcher(token_url)
    except CiOidcUnreachable:
        raise
    except Exception as exc:
        raise CiOidcUnreachable(
            f"Provider {provider_key!r}: OIDC fetch raised unexpected error: {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # Step 6 — verify token claims
    # ------------------------------------------------------------------
    if oidc_verifier is None:
        if not _is_test_mode():
            raise CiOidcUnreachable(
                "production OIDC verifier not configured; refusing to authorize via "
                "CI predicate. Set HARNESS_OIDC_TEST_MODE=1 ONLY in test environments "
                "to enable the TEST-ONLY env-var stub."
            )
        oidc_verifier = _test_oidc_verifier_factory(provider_key)

    expected_claims: dict = {}  # stub — real expected claims built from env snapshot

    try:
        verified_claims = oidc_verifier(token, expected_claims)
    except CiOidcClaimMismatch:
        raise
    except Exception as exc:
        raise CiOidcClaimMismatch(
            f"Provider {provider_key!r}: OIDC verifier raised unexpected error: {exc}"
        ) from exc

    # Extract the §3.5.1 / §12.4 audit claim subset.
    # jti is always extracted if present (§12.4 replay defense key).
    claim_keys = spec["claim_keys"]
    ci_oidc_claims = {k: verified_claims.get(k) for k in claim_keys}
    if "jti" in verified_claims:
        ci_oidc_claims["jti"] = verified_claims["jti"]

    # ------------------------------------------------------------------
    # Step 7 — return result
    # ------------------------------------------------------------------
    return CiProvenanceResult(
        authorization_source=spec["authorization_source"],
        ci_signature=ci_signature,
        ci_oidc_verified=True,
        ci_oidc_claims=ci_oidc_claims,
        bot_identity=bot_identity,
        bot_identity_distinct_from_approvers=True,
    )


__all__ = [
    "CiPredicateError",
    "NonTtyAuthorizationUnverified",
    "CiBotIdentityOverlapsHumanApprover",
    "CiProviderAmbiguous",
    "CiOidcUnreachable",
    "CiOidcClaimMismatch",
    "CiOidcJtiReplayed",
    "CiProvenanceResult",
    "ci_predicate_satisfied",
]
