#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""UserPromptSubmit hook. Names the skills that cover the request as additional context.
Never blocks the prompt and never decides anything.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "UserPromptSubmit"
LIMIT = 4

# Ordered: a specific trigger before the general one it could also match, so the limit
# cuts off the general skills first.
TRIGGERS = (
    ("refine-issue", r"\b(refine (the )?issue|flesh out (the )?issue|issue verfeinern)\b"),
    ("work-review", r"\b(work[- ]review|review the work)\b"),
    ("work-queue", r"\b(work[- ]?queue|drain the queue|queue abarbeiten)\b"),
    ("security-review", r"\b(security review|vulnerabilit(y|ies)|sicherheit|security check|cve)\b"),
    ("ci-review", r"\b(ci review|review in ci)\b"),
    ("review", r"\b(review|durchsehen|code review)\b"),
    ("commit", r"\b(commit|commits|committen|einchecken|stage and commit)\b"),
    ("pr", r"\b(pull request|\bpr\b|merge request)\b"),
    (
        "github-as-code",
        r"\b(github provider|repository settings|rulesets?|labels as code|org settings|"
        r"Repo-Einstellungen)\b",
    ),
    ("issue", r"\b(issue|ticket|bug report)\b"),
    ("plan", r"\b(plan|planen|implementation plan)\b"),
    ("implement", r"\b(implement|umsetzen|implementieren)\b"),
    ("release", r"\b(cut a release|release machen|tag a release|ver(ö|oe)ffentlichen)\b"),
    ("adr", r"\b(adr|architecture decision)\b"),
    ("concept-doc", r"\b(concept doc|konzept|design doc)\b"),
    ("post-mortem", r"\b(post[- ]?mortem|incident|outage|vorfall|ausfall)\b"),
    ("readme", r"\breadme\b"),
    ("fix-ci", r"\b(ci (is )?(red|failing|broken)|workflow f(ä|ae)hlt|pipeline (red|failing))\b"),
    ("test", r"\b(tests?|unit test|testabdeckung|coverage)\b"),
    ("lint", r"\b(lint|linter|format(ting)?)\b"),
    ("deps", r"\b(renovate|dependency|dependencies|abh(ä|ae)ngigkeiten)\b"),
    ("prune-branches", r"\b(prune branches|stale branches|branches aufr(ä|ae)umen)\b"),
    ("worktree", r"\b(worktree|arbeitsbaum)\b"),
    ("handoff", r"\b(handoff|hand off|(ü|ue)bergeben)\b"),
    ("tldr", r"\b(tl;?dr|tldr|kurzzusammenfassung|short summary)\b"),
    ("propose-rule", r"\b(baseline|propose a rule|regel vorschlagen|guardrail|hook)\b"),
    ("git-conventions", r"\b(branch|rebase|merge strategy|branch anlegen)\b"),
    (
        "repo-conventions",
        r"\b(new repository|agents\.md|repository layout|repo anlegen)\b",
    ),
    ("writing-style", r"\b(rewrite|house style|umschreiben)\b"),
    ("ci-conventions", r"\b(github actions|workflow|pipeline)\b"),
    ("release-conventions", r"\b(versioning|semver|changelog)\b"),
    ("tofu-module", r"\b(tofu module|write a (tofu )?module|module structure|modul schreiben)\b"),
    ("tofu-plan", r"\b(tofu plan|plan reading|blast radius)\b"),
    ("opentofu-conventions", r"\b(tofu|opentofu|terraform)\b"),
    ("helm-chart", r"\b(helm chart|chart template|helm-unittest)\b"),
    ("kubernetes-conventions", r"\b(kubernetes|k8s|kubectl|helm)\b"),
    ("k8s-debug", r"\b(debug (the )?(pod|cluster)|crashloop|kubectl debug)\b"),
    ("talos-ops", r"\b(talos|talosctl)\b"),
    ("ansible-conventions", r"\b(ansible|playbooks?|inventory)\b"),
    ("python-conventions", r"\b(python|pytest|ruff|uv run)\b"),
    ("secrets-handling", r"\b(secret|credential|token|kubeconfig|talosconfig)\b"),
    ("conformance-checks", r"\b(conftest|helm-unittest|conformance)\b"),
    ("skills-config", r"\b(\.agent-skills\.json|skills config)\b"),
    ("agents", r"\b(subagent|spawn an agent|terminate (the )?agent|agent routing)\b"),
)


def main() -> int:
    payload = _common.read_payload()
    prompt = payload.get("prompt") or ""
    if not prompt:
        return _common.emit_empty()

    matched = []
    for skill, pattern in TRIGGERS:
        if len(matched) >= LIMIT:
            break
        if re.search(pattern, prompt, re.IGNORECASE):
            matched.append(skill)

    if not matched:
        return _common.emit_empty()

    names = ", ".join(matched)
    return _common.context(
        EVENT, f"Skills that cover this request: {names}. Load them before acting."
    )


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
