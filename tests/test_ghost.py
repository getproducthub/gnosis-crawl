"""Unit tests for app.agent.ghost — Ghost Protocol block detection and logic."""

import pytest

from app.agent.ghost import (
    BlockDetection,
    BlockSignal,
    GhostCapture,
    GhostExtraction,
    GhostResult,
    GHOST_EXTRACTION_PROMPT,
    detect_block,
    should_trigger_ghost,
)


class TestBlockSignal:
    def test_all_signals(self):
        assert BlockSignal.CLOUDFLARE == "cloudflare_challenge"
        assert BlockSignal.CAPTCHA == "captcha"
        assert BlockSignal.SESSION_VERIFY == "session_verification"
        assert BlockSignal.ACCESS_DENIED == "access_denied"
        assert BlockSignal.BOT_CHALLENGE == "bot_challenge"
        assert BlockSignal.EMPTY_SHELL == "empty_spa_shell"
        assert BlockSignal.HTTP_403 == "http_403"
        assert BlockSignal.HTTP_429 == "http_429"
        assert BlockSignal.HTTP_503 == "http_503"


class TestDetectBlock:
    def test_cloudflare_detected(self):
        d = detect_block(html="<div>Checking your browser... Cloudflare</div>")
        assert d.blocked is True
        assert d.signal == BlockSignal.CLOUDFLARE
        assert d.confidence >= 0.9

    def test_captcha_detected(self):
        d = detect_block(html="<div>Please solve the CAPTCHA below</div>")
        assert d.blocked is True
        assert d.signal == BlockSignal.CAPTCHA
        assert d.captcha_detected is True

    def test_recaptcha_detected(self):
        d = detect_block(html='<div class="g-recaptcha" data-sitekey="abc"></div>')
        assert d.blocked is True
        assert d.signal == BlockSignal.CAPTCHA

    def test_hcaptcha_detected(self):
        d = detect_block(html='<iframe src="https://hcaptcha.com/challenge"></iframe>')
        assert d.blocked is True
        assert d.signal == BlockSignal.CAPTCHA

    def test_bot_challenge_just_a_moment(self):
        d = detect_block(html="<title>Just a moment...</title>")
        assert d.blocked is True
        assert d.signal == BlockSignal.BOT_CHALLENGE

    def test_bot_challenge_are_you_human(self):
        d = detect_block(html="<h1>Are you human?</h1>")
        assert d.blocked is True
        assert d.signal == BlockSignal.BOT_CHALLENGE

    def test_checking_your_browser(self):
        d = detect_block(html="<p>Checking your browser before accessing</p>")
        assert d.blocked is True
        assert d.signal == BlockSignal.BOT_CHALLENGE

    def test_access_denied(self):
        d = detect_block(html="<h1>Access Denied</h1>")
        assert d.blocked is True
        assert d.signal == BlockSignal.ACCESS_DENIED

    def test_http_403(self):
        d = detect_block(html="", status_code=403)
        assert d.blocked is True
        assert d.signal == BlockSignal.HTTP_403

    def test_http_429(self):
        d = detect_block(html="", status_code=429)
        assert d.blocked is True
        assert d.signal == BlockSignal.HTTP_429

    def test_http_503(self):
        d = detect_block(html="", status_code=503)
        assert d.blocked is True
        assert d.signal == BlockSignal.HTTP_503

    def test_empty_spa_shell(self):
        # Big HTML but almost no text content
        html = '<html><head><script src="app.js"></script></head><body><div id="root"></div></body></html>' * 10
        d = detect_block(
            html=html,
            body_char_count=50,
            body_word_count=5,
        )
        assert d.blocked is True
        assert d.signal == BlockSignal.EMPTY_SHELL

    def test_content_quality_blocked(self):
        d = detect_block(html="<html></html>", content_quality="blocked")
        assert d.blocked is True

    def test_normal_page_not_blocked(self):
        d = detect_block(
            html="<html><body><h1>Hello World</h1><p>This is content.</p></body></html>",
            body_char_count=500,
            body_word_count=80,
        )
        assert d.blocked is False

    def test_http_200_not_blocked(self):
        d = detect_block(html="<html><body>OK</body></html>", status_code=200)
        assert d.blocked is False

    def test_markdown_also_checked(self):
        d = detect_block(html="", markdown="# Cloudflare challenge page")
        assert d.blocked is True
        assert d.signal == BlockSignal.CLOUDFLARE

    def test_case_insensitive(self):
        d = detect_block(html="<div>CLOUDFLARE RAY ID</div>")
        assert d.blocked is True


class TestShouldTriggerGhost:
    def test_trigger_on_cloudflare(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.CLOUDFLARE, confidence=0.95)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=True) is True

    def test_no_trigger_when_disabled(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.CLOUDFLARE, confidence=0.95)
        assert should_trigger_ghost(d, ghost_enabled=False, auto_trigger=True) is False

    def test_no_trigger_when_auto_off(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.CLOUDFLARE, confidence=0.95)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=False) is False

    def test_no_trigger_when_not_blocked(self):
        d = BlockDetection(blocked=False)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=True) is False

    def test_no_trigger_on_low_confidence_access_denied(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.ACCESS_DENIED, confidence=0.7)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=True) is False

    def test_trigger_on_captcha(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.CAPTCHA, confidence=0.95)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=True) is True

    def test_trigger_on_empty_shell(self):
        d = BlockDetection(blocked=True, signal=BlockSignal.EMPTY_SHELL, confidence=0.6)
        assert should_trigger_ghost(d, ghost_enabled=True, auto_trigger=True) is True


class TestGhostDataclasses:
    def test_ghost_capture_defaults(self):
        c = GhostCapture()
        assert c.success is False
        assert c.image_bytes == b""
        assert c.content_type == "image/png"

    def test_ghost_extraction_defaults(self):
        e = GhostExtraction()
        assert e.success is False
        assert e.render_mode == "ghost"
        assert e.blocked_content is False

    def test_ghost_result_defaults(self):
        r = GhostResult()
        assert r.success is False
        assert r.render_mode == "ghost"

    def test_extraction_prompt_exists(self):
        assert len(GHOST_EXTRACTION_PROMPT) > 100
        assert "screenshot" in GHOST_EXTRACTION_PROMPT.lower()
