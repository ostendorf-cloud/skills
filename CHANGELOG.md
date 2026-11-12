# Changelog

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
