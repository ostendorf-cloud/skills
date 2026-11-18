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
LIMIT = 2

# Task phrases, not single nouns: a bare noun such as "issue" or "branch" appears in almost
# every prompt about the repository. Ordered: a specific trigger before the general one it
# could also match, so the limit cuts off the general skills first.
TRIGGERS = (
    (
        "refine-issue",
        r"\b(refine (the |this )?issue|flesh out (the )?issue|groom the backlog|"
        r"(issue|ticket) (verfeinern|sch(ä|ae)rfen))\b",
    ),
    (
        "work-review",
        r"\b(work[- ]review|review the work|review issue #?\d+|issue #?\d+ review|"
        r"check the pr for issue|(pr|pull request) gegenpr(ü|ue)fen)\b",
    ),
    (
        "work-queue",
        r"\b(work[- ]?queue|drain the queue|queue abarbeiten|work the issues|"
        r"run the work loop|warteschlange abarbeiten|issues automatisch bearbeiten)\b",
    ),
    (
        "security-review",
        r"\b(security review|security check|sicherheitscheck|sicherheitspr(ü|ue)fung|"
        r"check (this |the )?\w* ?for vulnerabilit(y|ies)|cve-\d{4}-\d+)\b",
    ),
    (
        "ci-review",
        r"\b(ci review|review in ci|(pull request|pr) aus der ci|automatisierte review|"
        r"infrastruktur pull request|plan kommentar)\b",
    ),
    ("post-mortem", r"\b(post[- ]?mortem|incident report|vorfallbericht)\b"),
    (
        "review",
        r"\b(code review|review this|request changes|"
        r"review (the|my|that) (pr|pull request|diff|branch|changes?|code)|"
        r"(pr|pull request|diff|code) (reviewen|pr(ü|ue)fen|durchsehen))\b",
    ),
    (
        "commit",
        r"\b(commit (this|these|that|it|the|my|all|changes?|and push)|git commit|committen|"
        r"split (these |the )?commits|commits aufteilen|"
        r"commit message|stage and commit|(ä|ae)nderungen einchecken)\b",
    ),
    (
        "pr",
        r"\b((open|create|raise|make|draft|update|mark) (an? |the )?(draft )?"
        r"(pull request|pr|merge request)|"
        r"(pull request|pr|merge request) "
        r"(aufmachen|erstellen|(ö|oe)ffnen|anlegen|aktualisieren))\b",
    ),
    (
        "github-as-code",
        r"\b(github provider|repository settings|rulesets?|labels as code|org settings|"
        r"github[- ]app|app permissions|Repo-Einstellungen)\b",
    ),
    (
        "issue",
        r"\b((create|open|file|write|raise|update|edit) (an? |the )?(new )?"
        r"(issue|ticket|bug report)|"
        r"(issue|ticket) (erstellen|anlegen|aufmachen|schreiben|(ö|oe)ffnen|aktualisieren)|"
        r"file a bug)\b",
    ),
    (
        "plan",
        r"\b((write|make|draft|create) (a |the )?(short )?(implementation )?plan|"
        r"plan (this|the) (issue|work|task|change)|plan schreiben|vorgehen planen)\b",
    ),
    (
        "implement",
        r"\b(implement (issue|this issue|the issue|#?\d+|(the|this|a) (feature|change|fix))|"
        r"work (on )?(this|the) issue|work on issue|pick up (the |an? )?issue|"
        r"address (the )?review feedback|"
        r"(issue|ticket) (umsetzen|abarbeiten|implementieren))\b",
    ),
    (
        "release",
        r"\b(cut a release|release machen|tag a release|ship a release|"
        r"(release|version) freigeben|release (ver(ö|oe)ffentlichen|schneiden))\b",
    ),
    (
        "adr",
        r"\b(write (an? )?adr|adr (schreiben|anlegen)|architecture decision record|"
        r"architekturentscheidung)\b",
    ),
    (
        "concept-doc",
        r"\b(concept doc|(write|draft) (a )?design doc|konzept (schreiben|erstellen)|"
        r"feature-konzept)\b",
    ),
    (
        "readme",
        r"\b((write|update|review|rewrite|refresh|fix) (the |a |our )?readme|"
        r"readme (schreiben|aktualisieren|(ü|ue)berarbeiten))\b",
    ),
    (
        "fix-ci",
        r"\b(ci (is )?(red|failing|broken)|workflow f(ä|ae)hlt|pipeline (red|failing)|"
        r"fix (the )?ci|ci reparieren|workflow debuggen|debug (the )?(ci|workflow))\b",
    ),
    ("go-tests", r"\b(go test|go-tests|table[- ]?driven|testing in go)\b"),
    ("go-lint", r"\b(golangci-lint|gofumpt|go linten)\b"),
    (
        "go-conventions",
        r"\b(golang|go code|go package|go module|go schreiben|go-konventionen)\b",
    ),
    (
        "testing-conventions",
        r"\b(testkonventionen|testing conventions)\b",
    ),
    (
        "test",
        r"\b(run (the |all )?tests|add (missing )?tests|write (a |some )?tests?|"
        r"tests? (ausf(ü|ue)hren|erg(ä|ae)nzen|schreiben)|testabdeckung|test coverage)\b",
    ),
    (
        "lint",
        r"\b(run (the )?(linters?|lint)|lint (the|this|my) \w+|code linten|"
        r"linter laufen|format (the|this) code|code formatieren)\b",
    ),
    (
        "deps",
        r"\b(renovate|(update|bump) (the )?dependenc(y|ies)|triage dependency|dependency[- ]prs|"
        r"(abh(ä|ae)ngigkeiten|dependencies) (updaten|aktualisieren))\b",
    ),
    (
        "prune-branches",
        r"\b(prune branches|stale branches|clean up (merged )?branches|"
        r"delete (the )?merged branches|branches (aufr(ä|ae)umen|l(ö|oe)schen)|"
        r"alte branches)\b",
    ),
    (
        "worktree",
        r"\b((create|add|remove|set up|use) (a |the )?(new )?worktree|"
        r"worktree (anlegen|erstellen|entfernen|starten))\b",
    ),
    (
        "handoff",
        r"\b(handoff|hand (this )?off|(ü|ue)bergabe schreiben|zwischenstand sichern)\b",
    ),
    (
        "tldr",
        r"\b(tl;?dr|tldr|kurzzusammenfassung|short summary|summarize this|"
        r"pr description|kurz zusammenfassen|status geben)\b",
    ),
    (
        "user-story",
        r"\b(user story|turn this into a story|check this story)\b",
    ),
    (
        "propose-rule",
        r"\b(propose a rule|rule change|regel vorschlagen|baseline anpassen|"
        r"this should be a rule)\b",
    ),
    (
        "git-conventions",
        r"\b(rebase (onto|on|this|the|my)|(create|cut|make|start) (a |the )?(new )?branch|"
        r"branch (anlegen|erstellen|name)|merge strategy|force[- ]push)\b",
    ),
    (
        "repo-conventions",
        r"\b(new repository|agents\.md|repository layout|repo(sitory)? anlegen|"
        r"where does this script go|tool-version pinnen)\b",
    ),
    (
        "writing-style",
        r"\b(rewrite (this|that|the)|house style|hausstil|umschreiben)\b",
    ),
    (
        "ci-conventions",
        r"\b(github actions|(write|add|name|create|review) (a |the )?(new )?(workflow|pipeline)|"
        r"workflow (schreiben|anlegen|benennen)|agent laeuft in ci|unbeaufsichtigt|"
        r"tofu pipeline|module planen)\b",
    ),
    (
        "release-conventions",
        r"\b(versioning|versionierung|semver|semantic versioning|release-konventionen)\b",
    ),
    (
        "container-images",
        r"\b(dockerfile (schreiben|writing)|(write|change|update) (a |the )?dockerfile|"
        r"multi-arch|basisimage|base image|manifest list|linux/arm64|containerimage|"
        r"architekturen bauen)\b",
    ),
    (
        "tofu-module",
        r"\b(tofu module|write a (tofu )?module|module structure|modul schreiben|new module|"
        r"extract a module|module (readme|inputs|outputs)|neues modul|"
        r"modul (extrahieren|variablen))\b",
    ),
    (
        "tofu-plan",
        r"\b(tofu plan|tofu apply|plan reading|blast radius|review a plan|"
        r"drift pr(ü|ue)fen|tofu anwenden|plan erstellen)\b",
    ),
    (
        "opentofu-conventions",
        r"\b(tofu|opentofu|terraform|variables\.tf|provider block|state backend|"
        r"variablen datei|statedatei)\b",
    ),
    (
        "helm-chart",
        r"\b(helm chart|chart template|helm-unittest|write a chart|helm template|helm lint|"
        r"values\.yaml|chart (werte|version))\b",
    ),
    (
        "kubernetes-conventions",
        r"\b(kubernetes|k8s|kubectl|helm|helm_release|install a chart|crds?|network policy|"
        r"pod security|ingress|gateway api|httproute|namespace anlegen|secret einbinden)\b",
    ),
    (
        "k8s-debug",
        r"\b(debug (the )?(pod|cluster)|crash[- ]?loop(ing)?|kubectl debug|pending pod|"
        r"helm release failed|service unreachable|pod startet nicht|fehler im cluster)\b",
    ),
    (
        "talos-ops",
        r"\b(talos|talosctl|machine config|etcd quorum|apply-config|node neu starten)\b",
    ),
    (
        "ansible-conventions",
        r"\b(ansible|playbooks?|dynamic inventory|inventar generieren|check mode|"
        r"pre-flight guard)\b",
    ),
    (
        "python-conventions",
        r"\b(python (script|code|hook|project|package|schreiben)|write python|"
        r"python-konventionen|pytest|ruff|uv run)\b",
    ),
    (
        "secrets-handling",
        r"\b(kubeconfig|talosconfig|rotate (the |a )?(secret|token|credential)s?|"
        r"(store|handle|leak|commit) (a |the )?(secret|token|credential)s?|"
        r"(secret|token)s? rotieren|leaked (key|secret|token)|geleakt\w* (token|secret|key)|"
        r"zugangsdaten)\b",
    ),
    (
        "conformance-checks",
        r"\b(conftest|helm-unittest|conformance|konvention pr(ü|ue)fen|policy schreiben)\b",
    ),
    (
        "skills-config",
        r"\b(agent-skills\.json|skills config|konfiguration pr(ü|ue)fen|repo-konfiguration)\b",
    ),
    (
        "website-conventions",
        r"\b((new|build|create|review|check) (a |the )?(new )?(website|landing ?page)|"
        r"(write|create|add|review|check) (an? |the )?(imprint|privacy (page|policy|statement)|"
        r"terms page)|(impressum|datenschutz\w*|agb)\b.{0,30}\b(schreiben|erstellen|pr(ü|ue)fen)|"
        r"webseite (bauen|erstellen|pr(ü|ue)fen))\b",
    ),
    (
        "agents",
        r"\b(subagent\w*|spawn (an? )?agents?|terminate (the )?agents?|agent routing|"
        r"run this in parallel|clean up the agents|agenten aufr(ä|ae)umen)\b",
    ),
)


def matches(prompt: str) -> list:
    """Every skill whose trigger matches prompt, in trigger order, without the limit."""
    return [skill for skill, pattern in TRIGGERS if re.search(pattern, prompt, re.IGNORECASE)]


def main() -> int:
    payload = _common.read_payload()
    prompt = payload.get("prompt") or ""
    if not prompt:
        return _common.emit_empty()

    matched = matches(prompt)[:LIMIT]
    if not matched:
        return _common.emit_empty()

    names = ", ".join(matched)
    return _common.context(
        EVENT, f"Skills that may apply: {names}. Load one only when the task needs it."
    )


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
