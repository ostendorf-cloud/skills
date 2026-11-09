# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for secret_guard.py."""

import os
import shutil
import subprocess
import tempfile
import unittest

from helper import bash_payload, decision, reason, run_hook

GITLEAKS_REAL_BINARY = shutil.which("gitleaks")
NO_GITLEAKS_PATH = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def git_repo() -> str:
    """A temporary repository on branch main with one commit."""
    path = tempfile.mkdtemp(prefix="secret-guard-")
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "dev@example.com"],
        ["config", "user.name", "dev"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "chore: init"], cwd=path, check=True, capture_output=True
    )
    return path


def stage(repo: str, name: str, content: str) -> None:
    with open(os.path.join(repo, name), "w", encoding="utf-8") as handle:
        handle.write(content)
    subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)


def no_gitleaks_env() -> dict:
    """An environment whose PATH cannot resolve gitleaks."""
    env = dict(os.environ)
    env["PATH"] = NO_GITLEAKS_PATH
    return env


def gitleaks_env() -> dict:
    """An environment whose PATH resolves gitleaks to the real installed binary,
    bypassing the mise shim so the test does not depend on a pinned version in cwd."""
    shim_dir = tempfile.mkdtemp(prefix="gitleaks-shim-")
    os.symlink(GITLEAKS_REAL_BINARY, os.path.join(shim_dir, "gitleaks"))
    env = dict(os.environ)
    env["PATH"] = shim_dir + ":" + env.get("PATH", "")
    return env


class SecretGuardTest(unittest.TestCase):
    def test_allows_ordinary_commands(self):
        repo = git_repo()
        for command in [
            "git status",
            "echo hello",
            "kubectl get secrets",
            "kubectl get pods -o yaml",
        ]:
            self.assertIsNone(
                decision(run_hook("secret_guard.py", bash_payload(command, repo))), command
            )

    def test_denies_commands_that_print_secrets(self):
        for command in [
            "bao kv get secret/prod/app",
            "vault read secret/data/app",
            "bws secret get my-secret",
            "bw get item my-item",
            "gh auth token",
            "tofu output database_password",
            "tofu state show module.app.resource",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_commands_that_print_secrets_with_flag_before_subcommand(self):
        for command in [
            "tofu -chdir=infra/prod output database_password",
            "tofu -chdir=infra/prod state show module.app.resource",
            "tofu -chdir=infra/prod state pull",
            "bws -o env secret get my-secret",
            "bws secret -o env get my-secret",
            "bws --profile prod secret list",
            "bw --raw get password my-item",
            "bw --session $BW_SESSION get item my-item",
            "gh auth --hostname github.com token",
            "gh auth --hostname=github.com token",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_safe_commands_with_flag_before_subcommand(self):
        for command in [
            "tofu -chdir=infra/prod plan",
            "tofu -chdir=infra/prod state list",
            "bws -o table project list",
            "bw --raw list items",
            "gh auth --hostname github.com status",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_denies_kubectl_get_secret_with_structured_output(self):
        for command in [
            "kubectl get secret db-credentials -o yaml",
            "kubectl get secrets -o json",
            "kubectl get secret db-credentials -o jsonpath={.data.password}",
            "kubectl get secret db-credentials --output=yaml",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_gh_auth_token_with_flag_before_the_noun(self):
        for command in [
            "gh --hostname example.com auth token",
            "gh --hostname=example.com auth token",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_auth_status_with_flag_before_the_noun(self):
        command = "gh --hostname example.com auth status"
        self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))))

    def test_denies_kubectl_get_secret_with_global_flag_before_the_verb(self):
        for command in [
            "kubectl -n default get secret db-credentials -o yaml",
            "kubectl --namespace=default get secret db-credentials -o yaml",
            "kubectl --namespace kube-system get secrets -o json",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_kubectl_reads_with_global_flag_before_the_verb(self):
        for command in [
            "kubectl -n default get secret db-credentials",
            "kubectl -n default get secrets",
            "kubectl --namespace=default get pods -o yaml",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_denies_kubectl_get_secret_in_the_resource_slash_name_form(self):
        for command in [
            "kubectl get secret/db-credentials -o yaml",
            "kubectl get secrets/db-credentials -o json",
            "kubectl get secret.v1.core/db-credentials -o yaml",
            "kubectl get secrets.v1. -o yaml",
            "kubectl -n default get secret/db-credentials -o yaml",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_kubectl_get_secret_listed_among_other_resource_types(self):
        for command in [
            "kubectl get secret,configmap -o yaml",
            "kubectl get configmap,secret -o json",
            "kubectl get configmap,secret.v1.core/db-credentials -o yaml",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_kubectl_get_secret_with_a_flag_between_the_verb_and_the_resource(self):
        for command in [
            "kubectl get -o yaml secret db-credentials",
            "kubectl get -o yaml secret/db-credentials",
            "kubectl get --output=json secrets",
            "kubectl get -n default -o yaml secret db-credentials",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_kubectl_get_for_a_resource_that_is_not_a_secret(self):
        for command in [
            "kubectl get configmap -o yaml",
            "kubectl get configmap/app-config -o yaml",
            "kubectl get configmap,pod -o json",
            "kubectl get secretproviderclass -o yaml",
            "kubectl get -o yaml configmap app-config",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_denies_kubectl_get_secret_with_a_templated_output_format(self):
        for command in [
            "kubectl get secret db-credentials -o go-template={{.data}}",
            "kubectl get secret db-credentials -o go-template-file=/tmp/secret.tpl",
            "kubectl get secret db-credentials -o template={{.data}}",
            "kubectl get secret db-credentials -o templatefile=/tmp/secret.tpl",
            "kubectl get secret db-credentials -o custom-columns=DATA:.data",
            "kubectl get secret db-credentials --output=custom-columns-file=/tmp/cols.txt",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_kubectl_get_secret_in_the_kyaml_output_format(self):
        for command in [
            "kubectl get secret db-credentials -o kyaml",
            "kubectl get secrets --output=kyaml",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_kubectl_get_secret_with_a_quoted_output_format(self):
        for command in [
            "kubectl get secret db-credentials -o 'yaml'",
            "kubectl get secret db-credentials -o 'kyaml'",
            'kubectl get secret db-credentials -o "go-template={{.data}}"',
            "kubectl get secret db-credentials --output='json'",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_a_quoted_output_format_that_prints_no_data_map(self):
        for command in [
            "kubectl get secret db-credentials -o 'name'",
            "kubectl get secret db-credentials -o 'wide'",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_allows_kubectl_get_secret_without_a_structured_output(self):
        command = "kubectl get secret db-credentials"
        self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))))

    def test_denies_gh_auth_token_called_by_absolute_path(self):
        for command in [
            "gh auth token",
            "/opt/homebrew/bin/gh auth token",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_kubectl_secret_read_called_by_absolute_path(self):
        for command in [
            "kubectl get secret db-credentials -o yaml",
            "/opt/homebrew/bin/kubectl get secret db-credentials -o yaml",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_secret_manager_read_called_by_absolute_path(self):
        for command in [
            "bws secret get my-secret",
            "/opt/homebrew/bin/bws secret get my-secret",
            "bw get password my-item",
            "/opt/homebrew/bin/bw get password my-item",
            "tofu output database_password",
            "/opt/homebrew/bin/tofu output database_password",
            "bao kv get secret/prod/app",
            "/opt/homebrew/bin/bao kv get secret/prod/app",
            "vault read secret/data/app",
            "/usr/local/bin/vault read secret/data/app",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_a_safe_secret_manager_command_called_by_absolute_path(self):
        for command in [
            "/opt/homebrew/bin/bws project list",
            "/opt/homebrew/bin/bw list items",
            "/opt/homebrew/bin/tofu plan",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_denies_a_secret_file_read_called_by_absolute_path(self):
        for command in [
            "cat .env",
            "/bin/cat .env",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_policed_part_whose_quoting_does_not_parse(self):
        for command in [
            'gh repo edit owner/repo --description "unclosed',
            'cat "secrets.yaml',
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_reading_a_secret_file(self):
        for command in [
            "cat .env",
            "head kubeconfig",
            "tail -f talosconfig",
            "less id_rsa",
            "grep -r password .env.production",
            "cat secrets.tfvars",
            "cat environments/prod/secrets.auto.tfvars",
            "head secrets.tfvars.json",
            "cat secrets.auto.tfvars.json",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_reading_a_configuration_tfvars_file(self):
        for command in [
            "cat nodes.tfvars",
            "head environments/prod/dns.auto.tfvars",
            "grep count terraform.tfvars",
            "cat mysecrets.tfvars",
        ]:
            self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload(command))), command)

    def test_denies_echoing_a_credential_variable(self):
        for command in [
            "echo $GH_TOKEN",
            'echo "$VAULT_TOKEN"',
            "printf '%s' ${AWS_SECRET_ACCESS_KEY}",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_grepping_the_environment_for_credentials(self):
        for command in [
            "env | grep TOKEN",
            "printenv | grep -i secret",
            "env | grep GH_TOKEN",
        ]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_denies_printenv_of_a_credential_variable(self):
        for command in ["printenv GH_TOKEN", "printenv AWS_SECRET_ACCESS_KEY"]:
            self.assertEqual(
                decision(run_hook("secret_guard.py", bash_payload(command))), "deny", command
            )

    def test_allows_printenv_of_an_ordinary_variable(self):
        self.assertIsNone(decision(run_hook("secret_guard.py", bash_payload("printenv PATH"))))

    def test_denies_staging_a_forbidden_file(self):
        repo = git_repo()
        stage(repo, ".env", "API_KEY=value\n")
        self.assertEqual(
            decision(
                run_hook(
                    "secret_guard.py",
                    bash_payload("git commit -m 'chore: add config'", repo),
                    env=no_gitleaks_env(),
                )
            ),
            "deny",
        )

    def test_denies_staging_a_secrets_yml_file(self):
        repo = git_repo()
        stage(repo, "secrets.yml", "password: hunter2\n")
        self.assertEqual(
            decision(
                run_hook(
                    "secret_guard.py",
                    bash_payload("git commit -m 'chore: add config'", repo),
                    env=no_gitleaks_env(),
                )
            ),
            "deny",
        )

    def test_denies_staging_a_forbidden_file_through_dash_c_path(self):
        repo = git_repo()
        stage(repo, ".env", "API_KEY=value\n")
        other = tempfile.mkdtemp(prefix="secret-guard-other-")
        self.assertEqual(
            decision(
                run_hook(
                    "secret_guard.py",
                    bash_payload(f"git -C {repo} commit -m 'chore: add config'", other),
                    env=no_gitleaks_env(),
                )
            ),
            "deny",
        )

    def test_allows_an_ordinary_commit(self):
        repo = git_repo()
        stage(repo, "notes.md", "nothing secret here\n")
        self.assertIsNone(
            decision(
                run_hook(
                    "secret_guard.py",
                    bash_payload("git commit -m 'docs: add notes'", repo),
                    env=no_gitleaks_env(),
                )
            )
        )

    def test_falls_back_to_regex_scan_without_gitleaks(self):
        repo = git_repo()
        stage(repo, "config.yaml", "token: ghp_" + "a" * 36 + "\n")
        output = run_hook(
            "secret_guard.py",
            bash_payload("git commit -m 'feat: add config'", repo),
            env=no_gitleaks_env(),
        )
        self.assertEqual(decision(output), "deny")
        self.assertIn("config.yaml", reason(output))
        self.assertNotIn("ghp_", reason(output))

    @unittest.skipUnless(GITLEAKS_REAL_BINARY, "gitleaks is not installed on this machine")
    def test_denies_a_staged_token_found_by_gitleaks(self):
        repo = git_repo()
        # A filename outside the secret file patterns, so the gitleaks content scan is
        # what catches this, not the filename check that runs before it.
        # The header is assembled at run time so this source file itself never carries a
        # key shaped line that a scanner of the repository would report.
        header = "-----BEGIN " + "RSA PRIVATE KEY-----"
        footer = "-----END " + "RSA PRIVATE KEY-----"
        stage(
            repo,
            "deploy-notes.md",
            f"{header}\n"
            "MIIBogIBAAJBAKj34GkxFhD91assxmE1QHDAuyBbS4U8/03/vapEO9OCjF2gnXVE\n"
            "DdpnTGhNJ9KqaIaZImLjfDuxCz8xx1rhTQ0CAwEAAQ==\n"
            f"{footer}\n",
        )
        output = run_hook(
            "secret_guard.py",
            bash_payload("git commit -m 'chore: add key'", repo),
            env=gitleaks_env(),
        )
        self.assertEqual(decision(output), "deny")
        self.assertIn("deploy-notes.md", reason(output))
        self.assertNotIn(header, reason(output))


if __name__ == "__main__":
    unittest.main()
