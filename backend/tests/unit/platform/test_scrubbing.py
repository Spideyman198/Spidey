"""Redaction contract: recall over precision — secrets never survive."""

from __future__ import annotations

from spidey.platform.security.scrubbing import REDACTED, scrub_event_dict, scrub_text


class TestScrubText:
    def test_provider_keys(self) -> None:
        assert REDACTED in scrub_text("key=sk-ant-abc123def456ghi789")
        assert REDACTED in scrub_text("openai sk-abcdefghijklmnopqrstuvwxyz123456")

    def test_github_tokens(self) -> None:
        assert REDACTED in scrub_text("ghp_abcdefghijklmnopqrst123456")
        assert REDACTED in scrub_text("github_pat_abcdefghijklmnopqrstuv")

    def test_bearer_header(self) -> None:
        assert (
            scrub_text("Authorization: Bearer eyJhbGciOi.payload.sig")
            == f"Authorization: {REDACTED}"
        )

    def test_aws_access_key(self) -> None:
        assert REDACTED in scrub_text("AKIAIOSFODNN7EXAMPLE")

    def test_private_key_block(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        assert scrub_text(pem) == REDACTED

    def test_url_credentials_masked(self) -> None:
        scrubbed = scrub_text("postgresql://spidey:hunter2@db:5432/app")
        assert "hunter2" not in scrubbed
        assert "spidey" in scrubbed  # username is kept for debuggability

    def test_email_local_part_masked(self) -> None:
        scrubbed = scrub_text("contact alice.smith@example.com please")
        assert "alice.smith" not in scrubbed
        assert "a***@example.com" in scrubbed

    def test_benign_text_untouched(self) -> None:
        text = "indexing finished for workspace 42 in 3.2s"
        assert scrub_text(text) == text


class TestScrubEventDict:
    def test_sensitive_keys_redacted_regardless_of_value(self) -> None:
        event = scrub_event_dict(None, "info", {"password": "x", "api_key": "y", "event": "login"})
        assert event == {"password": REDACTED, "api_key": REDACTED, "event": "login"}

    def test_nested_structures(self) -> None:
        event = scrub_event_dict(
            None,
            "info",
            {
                "payload": {
                    "headers": {"Authorization": "Bearer abc12345"},
                    "items": ["ghp_abcdefghijklmnopqrst123456"],
                }
            },
        )
        payload = event["payload"]
        assert payload["headers"]["Authorization"] == REDACTED  # sensitive key
        assert payload["items"][0] == REDACTED  # sensitive value shape

    def test_depth_bomb_is_cut_off(self) -> None:
        nested: dict[str, object] = {"v": "leaf"}
        for _ in range(20):
            nested = {"n": nested}
        event = scrub_event_dict(None, "info", {"deep": nested})
        assert REDACTED in str(event)

    def test_non_string_values_pass_through(self) -> None:
        event = scrub_event_dict(None, "info", {"count": 3, "ratio": 0.5, "ok": True, "none": None})
        assert event == {"count": 3, "ratio": 0.5, "ok": True, "none": None}
