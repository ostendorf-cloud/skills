# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for usage_statusline.py."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from helper import HOOKS_DIR

sys.path.insert(0, HOOKS_DIR)
import usage_statusline  # noqa: E402

SCRIPT = os.path.join(HOOKS_DIR, "usage_statusline.py")

FULL = {
    "session_id": "abc123",
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "workspace": {"current_dir": "/nonexistent/repo", "project_dir": "/nonexistent/repo"},
    "context_window": {"used_percentage": 8.4},
    "rate_limits": {
        "five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
        "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600},
    },
}


class Collector(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        Collector.received.append((self.path, dict(self.headers), body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def run(data, env_extra=None, raw=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, SCRIPT],
        input=raw if raw is not None else json.dumps(data),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def points(body):
    result = {}
    for metric in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]:
        for point in metric["gauge"]["dataPoints"]:
            attrs = {a["key"]: a["value"]["stringValue"] for a in point["attributes"]}
            result[(metric["name"], attrs.get("window", ""))] = (point["asDouble"], attrs)
    return result


class StatusLineTest(unittest.TestCase):
    def test_prints_model_context_and_both_limits(self):
        result = run(FULL)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "Opus | ctx 8% | 5h 24% | 7d 41%")

    def test_prints_without_rate_limits(self):
        data = {"model": {"display_name": "Opus"}, "context_window": {"used_percentage": None}}
        self.assertEqual(run(data).stdout.strip(), "Opus")

    def test_prints_a_line_for_garbage_input(self):
        result = run(None, raw="not json {{{")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "claude")

    def test_prints_a_line_for_wrong_types(self):
        data = {"model": 3, "context_window": "x", "rate_limits": {"five_hour": []}}
        result = run(data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "claude")

    def test_ignores_boolean_percentages(self):
        data = {"rate_limits": {"five_hour": {"used_percentage": True}}}
        self.assertEqual(run(data).stdout.strip(), "claude")


class PayloadTest(unittest.TestCase):
    def test_builds_three_gauges_with_session_model_and_repository(self):
        body = usage_statusline.build_payload(FULL, {}, "skills", 5)
        found = points(body)
        self.assertEqual(found[("claude_code.context.used_percentage", "")][0], 8.4)
        five = found[("claude_code.plan_limit.used_percentage", "five_hour")]
        seven = found[("claude_code.plan_limit.used_percentage", "seven_day")]
        self.assertEqual((five[0], seven[0]), (23.5, 41.2))
        for _, attrs in (five, seven):
            self.assertEqual(attrs["session.id"], "abc123")
            self.assertEqual(attrs["model"], "claude-opus-5-5")
            self.assertEqual(attrs["vcs.repository.name"], "skills")

    def test_returns_none_without_any_percentage(self):
        self.assertIsNone(usage_statusline.build_payload({"session_id": "x"}, {}, "", 5))

    def test_resource_attributes_come_from_the_environment(self):
        env = {"OTEL_RESOURCE_ATTRIBUTES": "host.role=laptop, team=platform"}
        body = usage_statusline.build_payload(FULL, env, "", 5)
        resource = {
            a["key"]: a["value"]["stringValue"]
            for a in body["resourceMetrics"][0]["resource"]["attributes"]
        }
        self.assertEqual(resource["host.role"], "laptop")
        self.assertEqual(resource["team"], "platform")

    def test_payload_carries_no_prompt_or_path_fields(self):
        text = json.dumps(usage_statusline.build_payload(FULL, {}, "skills", 5))
        self.assertNotIn("/nonexistent", text)

    def test_endpoint_prefers_the_metrics_override(self):
        env = {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example:4318/",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://other.example/v1/metrics",
        }
        self.assertEqual(usage_statusline.metrics_endpoint(env), "http://other.example/v1/metrics")
        del env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
        self.assertEqual(
            usage_statusline.metrics_endpoint(env), "http://collector.example:4318/v1/metrics"
        )
        self.assertEqual(usage_statusline.metrics_endpoint({}), "")

    def test_repository_name_from_a_temporary_clone_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(
                ["git", "-C", tmp, "remote", "add", "origin", "git@example.test:org/skills.git"],
                check=True,
            )
            self.assertEqual(usage_statusline.repository_name(tmp), "skills")
        self.assertEqual(usage_statusline.repository_name(""), "")


class SendTest(unittest.TestCase):
    def setUp(self):
        Collector.received = []
        self.server = HTTPServer(("127.0.0.1", 0), Collector)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.env = {
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{self.server.server_port}",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic fake-test-value",
            "USAGE_STATUSLINE_FOREGROUND": "1",
            "USAGE_STATUSLINE_STATE_DIR": self.state.name,
        }

    def test_posts_the_gauges_with_the_configured_headers(self):
        result = run(FULL, self.env)
        self.assertEqual(result.stdout.strip(), "Opus | ctx 8% | 5h 24% | 7d 41%")
        self.assertEqual(len(Collector.received), 1)
        path, headers, body = Collector.received[0]
        self.assertEqual(path, "/v1/metrics")
        self.assertEqual(headers["Authorization"], "Basic fake-test-value")
        self.assertEqual(len(points(body)), 3)

    def test_sends_once_per_interval_for_a_session(self):
        run(FULL, self.env)
        run(FULL, self.env)
        self.assertEqual(len(Collector.received), 1)

    def test_sends_again_for_another_session(self):
        run(FULL, self.env)
        run(dict(FULL, session_id="other"), self.env)
        self.assertEqual(len(Collector.received), 2)

    def test_sends_nothing_without_an_endpoint(self):
        env = {k: v for k, v in self.env.items() if k != "OTEL_EXPORTER_OTLP_ENDPOINT"}
        result = run(FULL, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Collector.received, [])

    def test_prints_the_line_when_the_endpoint_is_down(self):
        self.server.shutdown()
        result = run(FULL, self.env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("5h 24%", result.stdout)


if __name__ == "__main__":
    unittest.main()
