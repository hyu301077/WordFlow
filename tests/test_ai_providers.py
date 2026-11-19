import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from wordflow.ai import (
    AIError,
    PROVIDERS,
    active_provider,
    client_from_settings,
    configured_client,
    material_client_from_settings,
    provider_connection,
    save_provider_connection,
)
from wordflow.settings import Settings
from wordflow.store import Store
from wordflow.ui.assistant import AssistantPage


@pytest.fixture
def settings(tmp_path):
    store = Store(tmp_path / "app.db")
    try:
        yield Settings(store)
    finally:
        store.close()


def test_presets_and_existing_custom_configuration(settings):
    assert active_provider(settings) == "deepseek"
    settings.set("ai_base_url", "http://localhost:11434/v1")
    settings.set("ai_model", "old-model")
    settings.set("ai_api_key", "custom-secret")
    assert active_provider(settings) == "custom"
    for provider in ("deepseek", "openai", "qwen"):
        preset = PROVIDERS[provider]
        assert provider_connection(settings, provider).api_key == ""
        save_provider_connection(settings, provider, "", "", "key-" + provider)
        client = configured_client(settings)
        assert (client.base_url, client.model, client.api_key) == (preset.base_url, preset.model, "key-" + provider)
    assert provider_connection(settings, "custom").api_key == "custom-secret"
    assert provider_connection(settings, "custom").model == "old-model"
    assert provider_connection(settings, "deepseek").api_key == "key-deepseek"


def test_automatic_permission_is_separate_and_bound_to_destination(settings):
    save_provider_connection(settings, "custom", "https://old.example/v1", "m", "old-key")
    settings.set("ai_enabled", 1)
    settings.set("ai_consent", 1)
    assert client_from_settings(settings).model == "m"
    assert material_client_from_settings(settings) is None
    settings.set("ai_material_consent", 1)
    assert material_client_from_settings(settings).api_key == "old-key"
    changed = save_provider_connection(settings, "custom", "https://other.example/v1", "m", "old-key")
    assert changed.api_key == ""
    assert material_client_from_settings(settings) is None
    settings.set("ai_material_consent", 1)
    save_provider_connection(settings, "deepseek", "", "", "ds-secret")
    assert material_client_from_settings(settings) is None
    settings.set("ai_material_consent", 1)
    assert material_client_from_settings(settings).api_key == "ds-secret"
    settings.set("ai_enabled", 0)
    assert material_client_from_settings(settings) is None


def test_ui_switch_and_permission_free_connection_check(settings):
    app = QApplication.instance() or QApplication([])
    page = AssistantPage(SimpleNamespace(settings=settings, store=settings.store), None)
    page.on_show()
    assert page.provider.currentData() == "deepseek"
    assert page.base_url.isReadOnly()
    page.api_key.setText("ds-test-secret")
    page._save_connection()
    assert not settings.flag("ai_enabled")
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"OK"}}]}'
        page._run("ping")
        assert page.worker.wait(2000)
        app.processEvents()
        request = urlopen.call_args.args[0]
        assert request.full_url == "https://api.deepseek.com/chat/completions"
        assert request.get_header("Authorization") == "Bearer ds-test-secret"
        payload = json.loads(request.data)
        assert payload["model"] == "deepseek-flash"
        assert payload["messages"][-1]["content"] == "只回复 OK。"
        assert "已连接" in page.output.toPlainText()
    page.provider.setCurrentIndex(page.provider.findData("custom"))
    assert not page.base_url.isReadOnly()
    assert not page.api_key.text()
    page.provider.setCurrentIndex(page.provider.findData("deepseek"))
    assert page.api_key.text() == "ds-test-secret"
    assert material_client_from_settings(settings) is None
    page.close()


def test_failed_request_redacts_key_before_truncating(settings):
    save_provider_connection(settings, "deepseek", "", "", "token-end-12345")
    client = configured_client(settings)
    assert client.api_key not in repr(client)
    error = urllib.error.HTTPError(
        client.base_url, 401, "unauthorized", {}, io.BytesIO(("x" * 496 + client.api_key).encode())
    )
    with patch("urllib.request.urlopen", side_effect=error), pytest.raises(AIError) as failure:
        client.complete("test", "OK")
    assert "401" in str(failure.value)
    assert "tok" not in str(failure.value)


def test_revoking_automatic_permission_stops_the_next_batch(settings):
    save_provider_connection(settings, "deepseek", "", "", "test-key")
    for flag in ("ai_enabled", "ai_consent", "ai_material_consent"):
        settings.set(flag, 1)
    client = material_client_from_settings(settings)
    Settings(settings.store).set("ai_material_consent", 0)
    with patch("urllib.request.urlopen") as send, pytest.raises(AIError, match="设置已更改"):
        client.complete("translate", "Next sentence.")
    send.assert_not_called()
