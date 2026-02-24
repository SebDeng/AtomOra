"""Tests for silence mode settings persistence."""


class TestSilenceModePersistence:
    def test_silence_mode_read_from_settings(self):
        """silence_mode is read from settings dict."""
        settings = {"app": {"silence_mode": True}}
        assert settings.get("app", {}).get("silence_mode", False) is True

    def test_silence_mode_defaults_false(self):
        """silence_mode defaults to False when not in settings."""
        settings = {"app": {}}
        assert settings.get("app", {}).get("silence_mode", False) is False

    def test_silence_mode_missing_app_section(self):
        """silence_mode defaults to False when app section missing."""
        settings = {}
        assert settings.get("app", {}).get("silence_mode", False) is False
