"""Provider fault tests use a fake transport; they never consume a model key."""

import io
import json
from urllib.error import HTTPError

import pytest

from server.ai import AISettings, ModelCompletion, OpenAICompatibleProvider, ProviderError, model_trace_fields


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def settings():
    return AISettings("private-test-key", "https://api.deepseek.com", "deepseek-flash")


def test_one_retry_on_transient_http_failure(monkeypatch):
    calls = []

    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise HTTPError("https://api.deepseek.com/chat/completions", 429, "throttled", None, None)
        payload = {"choices": [{"message": {"content": '{"status":"ok"}'}}]}
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("server.ai.urlopen", fake_urlopen)
    monkeypatch.setattr("server.ai.time.sleep", lambda _seconds: None)
    result = OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert result == '{"status":"ok"}'
    assert len(calls) == 2


def test_authentication_failure_does_not_retry_or_trace_key(monkeypatch):
    calls = []

    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        raise HTTPError("https://api.deepseek.com/chat/completions", 401, "unauthorized", None, None)

    monkeypatch.setattr("server.ai.urlopen", fake_urlopen)
    with pytest.raises(ProviderError) as error:
        OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert error.value.code == "http_401"
    assert "private-test-key" not in str(error.value)
    assert len(calls) == 1


def test_empty_json_content_retries_once_with_deepseek_thinking_disabled(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        content = "" if len(requests) == 1 else '{"status":"ok"}'
        return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"))

    monkeypatch.setattr("server.ai.urlopen", fake_urlopen)
    monkeypatch.setattr("server.ai.time.sleep", lambda _seconds: None)
    result = OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert result == '{"status":"ok"}'
    assert len(requests) == 2
    assert all(request["thinking"] == {"type": "disabled"} for request in requests)


def test_provider_exposes_only_bounded_usage_metadata(monkeypatch):
    def fake_urlopen(_request, timeout):
        payload = {
            "model": "deepseek-flash-actual",
            "choices": [{"message": {"content": '{"status":"ok"}', "reasoning_content": "must not persist"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17, "private": "drop-me"},
            "raw_private_field": "drop-me",
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("server.ai.urlopen", fake_urlopen)
    result = OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert isinstance(result, ModelCompletion)
    trace = model_trace_fields(result, configured_model="configured", elapsed_ms=9)
    assert trace == {
        "model": "deepseek-flash-actual",
        "elapsed_ms": 9,
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }
    assert "reasoning" not in json.dumps(trace)
    assert "private" not in json.dumps(trace)


def test_plain_string_provider_result_remains_backward_compatible():
    assert model_trace_fields("{}", configured_model="test-model", elapsed_ms=4) == {
        "model": "test-model",
        "elapsed_ms": 4,
    }


@pytest.mark.parametrize("body,code", [
    (b"not-json", "invalid_response"),
    (b'{"choices": []}', "invalid_response"),
    (b'{"choices":[{"message":{"content":[{"text":123}]}}]}', "empty_content"),
])
def test_malformed_provider_payload_is_bounded_and_safe(monkeypatch, body, code):
    calls = []
    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        return FakeResponse(body)
    monkeypatch.setattr("server.ai.urlopen", fake_urlopen)
    monkeypatch.setattr("server.ai.time.sleep", lambda _: None)
    with pytest.raises(ProviderError) as error:
        OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert error.value.code == code
    assert len(calls) <= 2


def test_timeout_stops_after_one_retry(monkeypatch):
    calls = []
    def timeout(_request, timeout):
        calls.append(timeout)
        raise TimeoutError("private details")
    monkeypatch.setattr("server.ai.urlopen", timeout)
    monkeypatch.setattr("server.ai.time.sleep", lambda _: None)
    with pytest.raises(ProviderError, match="network_error"):
        OpenAICompatibleProvider().complete(system_prompt="JSON", user_prompt="test", settings=settings())
    assert len(calls) == 2
