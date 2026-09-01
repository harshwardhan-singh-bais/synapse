"""
Independent verification before a stage is accepted.

The architect and tester roles are NEVER the same session that wrote the code —
they receive a fresh session each verification pass.
"""

from __future__ import annotations

import re
from typing import Callable

from .types import Effort, TeamConfig, VerificationResult

# Matches a genuine "ALL CHECKS PASS" signal.
# We strip code fences, inline code, and quoted strings first so agents
# cannot game the signal by echoing it inside those contexts.
_PASS_SIGNAL = re.compile(
    r'(?<!["\'])\bALL CHECKS PASS\b(?!["\'])',
    re.IGNORECASE,
)
_REJECT_SIGNAL = re.compile(r'\bNOT ALL CHECKS PASS\b', re.IGNORECASE)
_CODE_FENCE = re.compile(r'```.*?```', re.DOTALL)
_INLINE_CODE = re.compile(r'`[^`]+`')
_QUOTED = re.compile(r'"[^"]*ALL CHECKS PASS[^"]*"', re.IGNORECASE)


def _check_passed(report: str) -> bool:
    """Return True if the verification report contains a genuine ALL CHECKS PASS signal.

    Strips code fences, inline code, and quoted strings before checking so the
    signal cannot be gamed by agents that echo it in those contexts.
    """
    if _REJECT_SIGNAL.search(report):
        return False
    clean = _CODE_FENCE.sub("", report)
    clean = _INLINE_CODE.sub("", clean)
    clean = _QUOTED.sub("", clean)
    return bool(_PASS_SIGNAL.search(clean))


class Verifier:
    """Runs tester and architect verification against the current worktree.

    Neither role is allowed to write code — they only report.  The caller
    supplies a *session_runner* callable so the verifier stays decoupled from
    the agent-invocation mechanism.
    """

    def __init__(self, team: TeamConfig, effort: Effort = Effort.standard) -> None:
        self.team = team
        self.effort = effort

    # ──────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _build_verification_prompt(self, goal: str, context: str = "") -> str:
        supplement = ""
        if self.effort in (Effort.high, Effort.max):
            from .prompts import VERIFICATION_EFFORT_SUPPLEMENTS
            supplement = "\n\n" + VERIFICATION_EFFORT_SUPPLEMENTS.get(self.effort.value, "")

        context_block = f"Context:\n{context}\n\n" if context else ""
        return (
            f"# Verification Task\n\n"
            f"Goal that was supposed to be accomplished:\n{goal}\n\n"
            f"{context_block}"
            f"Your job: verify independently that the goal has been fully and correctly accomplished.\n"
            f"Run tests, review the code, exercise the features.{supplement}\n\n"
            f"Remember: output ALL CHECKS PASS (on its own line) only if you are genuinely satisfied.\n"
        )

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def verify(
        self,
        goal: str,
        cwd: str,
        session_runner: Callable[[str, str, str], str],
        context: str = "",
    ) -> VerificationResult:
        """Run tester and architect verification.

        *session_runner* is called as ``session_runner(role_name, prompt, cwd)``
        and must return the agent's text output.  The verifier roles are taken
        from ``team.verifiers``.
        """
        prompt = self._build_verification_prompt(goal, context)

        tester_report = ""
        architect_report = ""
        rejection_reasons: list[str] = []

        # Run testers
        for role_name in self.team.verifiers.get("testers", []):
            if role_name in self.team.agents:
                report = session_runner(role_name, prompt, cwd)
                tester_report += report + "\n"
                if not _check_passed(report):
                    rejection_reasons.append(f"Tester ({role_name}): {report[:500]}")

        # Run reviewers
        for role_name in self.team.verifiers.get("reviewers", []):
            if role_name in self.team.agents:
                report = session_runner(role_name, prompt, cwd)
                architect_report += report + "\n"
                if not _check_passed(report):
                    rejection_reasons.append(f"Reviewer ({role_name}): {report[:500]}")

        passed = len(rejection_reasons) == 0
        return VerificationResult(
            passed=passed,
            tester_report=tester_report,
            architect_report=architect_report,
            rejection_reason="\n\n".join(rejection_reasons),
        )
