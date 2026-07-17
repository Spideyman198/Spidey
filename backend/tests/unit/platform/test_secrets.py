"""Secret detection on write paths: hits are reported (never echoed), clean text passes."""

from __future__ import annotations

import pytest

from spidey.platform.security import describe_findings, scan_for_secrets


class TestScanForSecrets:
    @pytest.mark.parametrize(
        ("kind", "sample"),
        [
            ("anthropic api key", "key = 'sk-ant-abc123DEF456ghi789'"),
            ("openai-style api key", "OPENAI_KEY=sk-abcdefghij0123456789ABCD"),
            ("github token", "url = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
            ("aws access key id", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"),
            ("slack token", "hook: xoxb-123456789-abcdefghijk"),
            ("private key block", "-----BEGIN RSA PRIVATE KEY-----"),
            ("bearer credential", "Authorization: Bearer abcdef0123456789xyz"),
            ("url-embedded credential", "db = postgres://admin:hunter2secret@db:5432/x"),
            ("hardcoded password assignment", 'PASSWORD = "correct-horse-battery"'),
        ],
    )
    def test_detects_credential_shapes(self, kind: str, sample: str) -> None:
        findings = scan_for_secrets(f"+ {sample}")
        assert [f.kind for f in findings] == [kind]
        assert findings[0].line == 1

    def test_clean_code_has_no_findings(self) -> None:
        clean = (
            "def add(a: int, b: int) -> int:\n"
            "    # the password parameter name alone is fine\n"
            "    return a + b\n"
        )
        assert scan_for_secrets(clean) == []

    def test_reports_line_numbers_across_a_diff(self) -> None:
        diff = "+context line\n+token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n+more\n"
        findings = scan_for_secrets(diff)
        assert len(findings) == 1
        assert findings[0].line == 2

    def test_finding_never_carries_the_secret_value(self) -> None:
        secret = "sk-ant-SUPERSECRETVALUE123"
        findings = scan_for_secrets(f"x = '{secret}'")
        rendered = describe_findings(findings)
        assert findings
        assert secret not in rendered
        assert "line 1" in rendered

    def test_one_finding_per_kind_and_line(self) -> None:
        # Two Anthropic-shaped keys on one line collapse to one finding.
        line = "a = 'sk-ant-aaaaaaaaaa'; b = 'sk-ant-bbbbbbbbbb'"
        findings = scan_for_secrets(line)
        assert len([f for f in findings if f.kind == "anthropic api key"]) == 1
