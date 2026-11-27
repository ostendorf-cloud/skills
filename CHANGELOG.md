# Changelog

## [v0.5.0](https://github.com/ostendorf-cloud/skills/compare/v0.4.0...v0.5.0) (2026-11-27)

### Features

- **rules:** require an open item inventory and ledger pruning ([#309](https://github.com/ostendorf-cloud/skills/pull/309))
- **settings:** record token use and plan limit per session ([#305](https://github.com/ostendorf-cloud/skills/pull/305))
- **mods:** rotate the orchestrator context through a mod ([#304](https://github.com/ostendorf-cloud/skills/pull/304))
- **hooks:** block a bold owner step without a question call ([#298](https://github.com/ostendorf-cloud/skills/pull/298))
- **skills:** add a grill-me skill that closes open assumptions ([#284](https://github.com/ostendorf-cloud/skills/pull/284))
- **agents:** add a researcher agent that stores sources and results ([#283](https://github.com/ostendorf-cloud/skills/pull/283))
- **hooks:** inject the workstream ledger at session start ([#273](https://github.com/ostendorf-cloud/skills/pull/273))
- **skills:** add agents-md skill and nested AGENTS.md scan ([#270](https://github.com/ostendorf-cloud/skills/pull/270))
- **rules:** never make clear the only way on ([#272](https://github.com/ostendorf-cloud/skills/pull/272))
- **work:** allow ai ready when the request names the work ([#271](https://github.com/ostendorf-cloud/skills/pull/271))

### Bug Fixes

- **commit:** sign off commits where a DCO check applies ([#315](https://github.com/ostendorf-cloud/skills/pull/315))
- **hooks:** allow a worktree branch push through git -C ([#302](https://github.com/ostendorf-cloud/skills/pull/302))
- **skills:** close the baseline gaps found in the rollout ([#306](https://github.com/ostendorf-cloud/skills/pull/306))
- **hooks:** name the github module in the IaC refusal ([#303](https://github.com/ostendorf-cloud/skills/pull/303))
- **hooks:** read each commit segment's own heredoc ([#294](https://github.com/ostendorf-cloud/skills/pull/294))
- **hooks:** judge only the git commit segment of a commit command ([#287](https://github.com/ostendorf-cloud/skills/pull/287))
- **settings:** allow reads of installed skills and agents ([#278](https://github.com/ostendorf-cloud/skills/pull/278))
- **settings:** allow reading the installer state file ([#269](https://github.com/ostendorf-cloud/skills/pull/269))

## [v0.4.0](https://github.com/ostendorf-cloud/skills/compare/v0.3.0...v0.4.0) (2026-11-24)

### Features

- **settings:** run go get outside the sandbox and move the pnpm store ([#249](https://github.com/ostendorf-cloud/skills/pull/249))
- **hooks:** deny finding write-ups in public repositories ([#246](https://github.com/ostendorf-cloud/skills/pull/246))
- **hooks:** refuse a scratchpad path with a dash before the session id ([#234](https://github.com/ostendorf-cloud/skills/pull/234))
- **skills:** add the website conventions skill ([#231](https://github.com/ostendorf-cloud/skills/pull/231))
- **work-review:** name a sanctioned way to wait for a pending check ([#228](https://github.com/ostendorf-cloud/skills/pull/228))

### Bug Fixes

- **hooks:** guard commit identity under the global config switch ([#229](https://github.com/ostendorf-cloud/skills/pull/229))
- **work-review:** align the probe guardrail with the baseline ([#226](https://github.com/ostendorf-cloud/skills/pull/226))
- **hooks:** let the last branch switch decide in git-guard ([#223](https://github.com/ostendorf-cloud/skills/pull/223))
- **hooks:** harden the git guard ([#217](https://github.com/ostendorf-cloud/skills/pull/217))
- **hooks:** deny git fetch, pull and push outside a standalone call ([#211](https://github.com/ostendorf-cloud/skills/pull/211))

## [v0.3.0](https://github.com/ostendorf-cloud/skills/compare/v0.2.0...v0.3.0) (2026-11-15)

### Features

- **skills:** validate the Renovate configuration locally ([#199](https://github.com/ostendorf-cloud/skills/pull/199))
- **skills:** add agent guidance rules from five issues ([#198](https://github.com/ostendorf-cloud/skills/pull/198))
- **skills:** let the supervising session make trivial changes itself ([#196](https://github.com/ostendorf-cloud/skills/pull/196))
- **settings:** default to opusplan, medium effort and sonnet subagents ([#190](https://github.com/ostendorf-cloud/skills/pull/190))
- **skills:** name the sandbox traps and cap what a report returns ([#185](https://github.com/ostendorf-cloud/skills/pull/185))
- **skills:** a verification claim names the commit behind it ([#152](https://github.com/ostendorf-cloud/skills/pull/152))
- **skills:** let a reviewer probe what it cannot read ([#151](https://github.com/ostendorf-cloud/skills/pull/151))
- **skills:** a refusal test names what refused ([#150](https://github.com/ostendorf-cloud/skills/pull/150))
- **skills:** require every image to build for amd64 and arm64 ([#154](https://github.com/ostendorf-cloud/skills/pull/154))
- **hooks:** warn when the installed skills lag their checkout ([#140](https://github.com/ostendorf-cloud/skills/pull/140))
- **skills:** three verification rules, each paid for by a real failure ([#144](https://github.com/ostendorf-cloud/skills/pull/144))
- **ci:** wire renovate into CI ([#138](https://github.com/ostendorf-cloud/skills/pull/138))
- **skills:** require both Ingress and Gateway API in a chart ([#132](https://github.com/ostendorf-cloud/skills/pull/132))
- **baseline:** status table, decisions via tool only, terser prose ([#124](https://github.com/ostendorf-cloud/skills/pull/124))
- **secrets-handling:** add the env-vars-only _FILE twin rule ([#123](https://github.com/ostendorf-cloud/skills/pull/123))
- **baseline:** no public write-up for an unfixed vulnerability ([#119](https://github.com/ostendorf-cloud/skills/pull/119))

### Bug Fixes

- **tests:** run git in tests without the global git config ([#205](https://github.com/ostendorf-cloud/skills/pull/205))
- **skills:** create worktrees with --no-track and clear a half one ([#204](https://github.com/ostendorf-cloud/skills/pull/204))
- **hooks:** credential deny, review calls and scratch scope ([#203](https://github.com/ostendorf-cloud/skills/pull/203))
- **settings:** open the sandbox for pnpm, known_hosts and chromium ([#201](https://github.com/ostendorf-cloud/skills/pull/201))
- **skills:** install the shared reference file and check references ([#200](https://github.com/ostendorf-cloud/skills/pull/200))
- **hooks:** name skills only for clear task phrases ([#191](https://github.com/ostendorf-cloud/skills/pull/191))
- **install:** make an installation self contained ([#158](https://github.com/ostendorf-cloud/skills/pull/158))
- **install:** recognise another worktree of the same repository ([#153](https://github.com/ostendorf-cloud/skills/pull/153))
- **skills:** assert a selector override replaces the default map ([#157](https://github.com/ostendorf-cloud/skills/pull/157))
- **hooks:** allow the first push to a missing default branch ([#139](https://github.com/ostendorf-cloud/skills/pull/139))
- **settings:** narrow the permission deny and let the hook carry the net ([#148](https://github.com/ostendorf-cloud/skills/pull/148))
- **settings:** narrow the sandbox env deny instead of widening an allow ([#147](https://github.com/ostendorf-cloud/skills/pull/147))
- **settings:** enumerate the env template depths under the code root ([#146](https://github.com/ostendorf-cloud/skills/pull/146))
- **settings:** let a session work with committed env templates ([#142](https://github.com/ostendorf-cloud/skills/pull/142))
- **settings:** let the sandbox delete a checked out .env.example ([#131](https://github.com/ostendorf-cloud/skills/pull/131))
- **settings:** let the sandbox read .env.example in a repository ([#130](https://github.com/ostendorf-cloud/skills/pull/130))
- **renovate:** pinDigests is a config key, not a preset ([#122](https://github.com/ostendorf-cloud/skills/pull/122))

## [v0.2.0](https://github.com/ostendorf-cloud/skills/compare/v0.1.0...v0.2.0) (2026-11-12)

### Features

- add community health files and license, codeql enforcement ([#108](https://github.com/ostendorf-cloud/skills/pull/108))
- **install:** support more than one installation target ([#106](https://github.com/ostendorf-cloud/skills/pull/106))
- **rules:** confirm no live agent holds a worktree before reuse ([#101](https://github.com/ostendorf-cloud/skills/pull/101))
- **plan:** optional multi-perspective critique for large plans ([#81](https://github.com/ostendorf-cloud/skills/pull/81))

### Bug Fixes

- **release:** drop the labels override, use release-me's defaults ([#110](https://github.com/ostendorf-cloud/skills/pull/110))
- **worktree:** move the worktree convention to .claude/worktrees/ ([#104](https://github.com/ostendorf-cloud/skills/pull/104))
- **hooks:** see past a wrapper prefix in the secret guard, tracker body, label move and iac first hooks ([#99](https://github.com/ostendorf-cloud/skills/pull/99))
- **hooks:** walk wrapper flags the way getopt does ([#98](https://github.com/ostendorf-cloud/skills/pull/98))
- **hooks:** resolve the git basename in strip_global_git_options ([#95](https://github.com/ostendorf-cloud/skills/pull/95))
- **hooks:** resolve quoted names, sudo and flagged wrappers ([#97](https://github.com/ostendorf-cloud/skills/pull/97))
- **hooks:** resolve the git basename in git_guard and commit_message ([#91](https://github.com/ostendorf-cloud/skills/pull/91))
- **hooks:** resolve the command basename and widen the kubectl secret output deny ([#90](https://github.com/ostendorf-cloud/skills/pull/90))
- **hooks:** find the subcommand behind the flags in front of it ([#88](https://github.com/ostendorf-cloud/skills/pull/88))
- **settings:** narrow gh label deny to keep list readable ([#85](https://github.com/ostendorf-cloud/skills/pull/85))
- **settings:** stop denying committed .env template files ([#86](https://github.com/ostendorf-cloud/skills/pull/86))

## v0.2.0 (2026-11-12)

### Features

- **install:** support more than one installation target ([#106](https://github.com/ostendorf-cloud/skills/pull/106))
- **rules:** confirm no live agent holds a worktree before reuse ([#101](https://github.com/ostendorf-cloud/skills/pull/101))
- **plan:** optional multi-perspective critique for large plans ([#81](https://github.com/ostendorf-cloud/skills/pull/81))

### Bug Fixes

- **worktree:** move the worktree convention to .claude/worktrees/ ([#104](https://github.com/ostendorf-cloud/skills/pull/104))
- **hooks:** see past a wrapper prefix in the secret guard, tracker body, label move and iac first hooks ([#99](https://github.com/ostendorf-cloud/skills/pull/99))
- **hooks:** walk wrapper flags the way getopt does ([#98](https://github.com/ostendorf-cloud/skills/pull/98))
- **hooks:** resolve the git basename in strip_global_git_options ([#95](https://github.com/ostendorf-cloud/skills/pull/95))
- **hooks:** resolve quoted names, sudo and flagged wrappers ([#97](https://github.com/ostendorf-cloud/skills/pull/97))
- **hooks:** resolve the git basename in git_guard and commit_message ([#91](https://github.com/ostendorf-cloud/skills/pull/91))
- **hooks:** resolve the command basename and widen the kubectl secret output deny ([#90](https://github.com/ostendorf-cloud/skills/pull/90))
- **hooks:** find the subcommand behind the flags in front of it ([#88](https://github.com/ostendorf-cloud/skills/pull/88))
- **settings:** narrow gh label deny to keep list readable ([#85](https://github.com/ostendorf-cloud/skills/pull/85))
- **settings:** stop denying committed .env template files ([#86](https://github.com/ostendorf-cloud/skills/pull/86))

## v0.1.0 (2026-10-27)

### Features

- **release:** switch from release-please to release-me, make it the default ([#75](https://github.com/ostendorf-cloud/skills/pull/75))
- **settings:** allow read-only gh release commands without a prompt ([#72](https://github.com/ostendorf-cloud/skills/pull/72))
- **work:** user-story skill with role, wish, reason and given-when-then criteria ([#58](https://github.com/ostendorf-cloud/skills/pull/58))
- **quality:** testing-conventions skill, a bug fix starts with the test that reproduces it ([#59](https://github.com/ostendorf-cloud/skills/pull/59))
- **hooks:** deny inline interpreter one liners that write a file ([#53](https://github.com/ostendorf-cloud/skills/pull/53))
- **hooks:** deny attribution lines in commits, pull request bodies and comments ([#45](https://github.com/ostendorf-cloud/skills/pull/45))
- **work:** exactly one ai state label after every move ([#46](https://github.com/ostendorf-cloud/skills/pull/46))
- **skills:** one github app per purpose ([#34](https://github.com/ostendorf-cloud/skills/pull/34))
- **skills:** add go skills ([#16](https://github.com/ostendorf-cloud/skills/pull/16))
- **skills:** add post-mortem ([#15](https://github.com/ostendorf-cloud/skills/pull/15))
- **rules:** a worktree lives as long as its pull request ([#31](https://github.com/ostendorf-cloud/skills/pull/31))
- **skills:** pr records a stacked pull request on its issue ([#28](https://github.com/ostendorf-cloud/skills/pull/28))
- **skills:** opentofu state, secrets, adoption and file order ([#20](https://github.com/ostendorf-cloud/skills/pull/20))
- **skills:** talos-ops through opentofu ([#14](https://github.com/ostendorf-cloud/skills/pull/14))
- **skills:** add ansible-conventions ([#13](https://github.com/ostendorf-cloud/skills/pull/13))
- **skills:** merge commits by default, review fixes into the commit they correct ([#30](https://github.com/ostendorf-cloud/skills/pull/30))
- **skills:** review verdict as comment, formal review as upgrade ([#27](https://github.com/ostendorf-cloud/skills/pull/27))
- **skills:** opentofu plan and apply in ci ([#25](https://github.com/ostendorf-cloud/skills/pull/25))
- verify defaults to task check ([#26](https://github.com/ostendorf-cloud/skills/pull/26))
- **skills:** decision records on demand, deviations in AGENTS.md ([#24](https://github.com/ostendorf-cloud/skills/pull/24))
- **skills:** workflows by purpose, one job per check, yaml extension ([#18](https://github.com/ostendorf-cloud/skills/pull/18))
- **skills:** add github-as-code ([#19](https://github.com/ostendorf-cloud/skills/pull/19))
- **rules:** generic conventions, one check per job, Taskfile, yaml extension ([#11](https://github.com/ostendorf-cloud/skills/pull/11))
- **hooks:** add guard and context hooks with tests
- **scripts:** add installer and validator with tests
- **rules:** announce expected duration before longer tasks
- **skills:** add meta skills
- **skills:** add quality, docs, release, ci and python skills
- **skills:** add work loop skills
- **skills:** add repository skills
- **skills:** add convention skills
- **rules:** check agents that miss their expected report time
- **skills:** add opentofu and kubernetes skills
- **skills:** add security-review
- add skills.sh groupings and config schema
- **hooks:** add hook manifest
- **settings:** add laptop and ci profiles
- **rules:** add baseline rules

### Bug Fixes

- **rules:** name what the session does itself and what a subagent does ([#73](https://github.com/ostendorf-cloud/skills/pull/73))
- **skills:** close the review loop with inline findings and a terminal label ([#71](https://github.com/ostendorf-cloud/skills/pull/71))
- **hooks:** deny every spelling of an in place sed or perl edit ([#62](https://github.com/ostendorf-cloud/skills/pull/62))
- **hooks:** shell hygiene sees through wrapper prefixes ([#60](https://github.com/ostendorf-cloud/skills/pull/60))
- **hooks:** allow attribution patterns quoted in code ([#54](https://github.com/ostendorf-cloud/skills/pull/54))
- **settings:** drop the Write deny rules, Edit covers every file tool ([#42](https://github.com/ostendorf-cloud/skills/pull/42))
- **settings:** tfvars files are configuration, only secrets.tfvars stays denied ([#39](https://github.com/ostendorf-cloud/skills/pull/39))
- **settings:** git network commands run outside the sandbox ([#38](https://github.com/ostendorf-cloud/skills/pull/38))
- **ci:** skip tofu fmt tests without tofu, one job per check ([#12](https://github.com/ostendorf-cloud/skills/pull/12))
- **scripts:** doctor, uninstall and status agree with install, legacy links reclaimed
- **hooks:** close push, redirect, commit message and gh api gaps from review
- **skills:** review runs without questions, release-conventions gets when to use
- **settings:** close gh alias, extension and secret file gaps, protect the installed baseline
