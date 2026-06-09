"""Tests for the Ollama classifier wrapper.

We don't hit real Ollama in tests — the connection-error path is exercised
via monkeypatched urlopen, and JSON parsing is tested directly on synthetic
model outputs."""
import json
import urllib.error
from pathlib import Path

import pytest

from cleanup_agent import classifier
from cleanup_agent.classifier import OllamaUnreachable, _extract_json, classify


# --- _extract_json: model outputs in the wild are messy ---

def test_extract_pure_json():
    out = '{"destination": "/a/b", "confidence": "high"}'
    assert _extract_json(out) == {"destination": "/a/b", "confidence": "high"}


def test_extract_json_in_markdown_fence():
    out = '```json\n{"destination": "/a/b", "confidence": "low"}\n```'
    parsed = _extract_json(out)
    assert parsed["destination"] == "/a/b"


def test_extract_json_with_surrounding_prose():
    out = (
        "Sure! Here's my suggestion:\n"
        '{"destination": "/Users/foo/Desktop/work", "confidence": "medium"}\n'
        "Hope that helps."
    )
    parsed = _extract_json(out)
    assert parsed["destination"] == "/Users/foo/Desktop/work"
    assert parsed["confidence"] == "medium"


def test_extract_returns_none_on_unparseable():
    assert _extract_json("no json here") is None


# --- classify: end-to-end with monkeypatched urlopen ---

def _fake_urlopen(payload):
    """Build a context-manager that returns an object whose .read() yields
    the JSON-encoded `payload`. Mirrors what urllib.request.urlopen does."""
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(payload).encode("utf-8")
    def _fn(req, timeout=30):
        return _Resp()
    return _fn


def test_classify_returns_path_and_confidence(monkeypatch):
    dest = Path("/Users/foo/Desktop/work")
    monkeypatch.setattr(
        classifier.urllib.request, "urlopen",
        _fake_urlopen({
            "response": json.dumps({
                "destination": str(dest),
                "confidence": "high",
            })
        }),
    )

    suggested, confidence = classify("report.pdf", [dest])
    assert suggested == dest
    assert confidence == "high"


def test_classify_rejects_hallucinated_destination(monkeypatch):
    """If the model picks a path that wasn't in our allow-list, we treat
    the suggestion as invalid and return (None, 'low')."""
    real = Path("/Users/foo/Desktop/work")
    monkeypatch.setattr(
        classifier.urllib.request, "urlopen",
        _fake_urlopen({
            "response": json.dumps({
                "destination": "/some/path/that/was/not/in/the/list",
                "confidence": "high",
            })
        }),
    )

    suggested, confidence = classify("report.pdf", [real])
    assert suggested is None
    assert confidence == "low"


def test_classify_handles_bad_confidence_value(monkeypatch):
    dest = Path("/Users/foo/Desktop/work")
    monkeypatch.setattr(
        classifier.urllib.request, "urlopen",
        _fake_urlopen({
            "response": json.dumps({
                "destination": str(dest),
                "confidence": "very-high-actually",
            })
        }),
    )

    suggested, confidence = classify("report.pdf", [dest])
    assert suggested == dest
    assert confidence == "low"  # fell back


def test_classify_returns_low_when_no_destinations():
    suggested, confidence = classify("report.pdf", [])
    assert suggested is None
    assert confidence == "low"


# --- resolve_model: auto-pick whatever's installed ---

def test_resolve_model_exact_match(monkeypatch):
    monkeypatch.setattr(
        classifier, "list_installed_models",
        lambda: ["llama3:latest", "codellama:7b"],
    )
    assert classifier.resolve_model("llama3:latest") == "llama3:latest"


def test_resolve_model_finds_same_base_name(monkeypatch):
    """User passes 'llama3', Ollama has 'llama3:latest' — return that."""
    monkeypatch.setattr(
        classifier, "list_installed_models",
        lambda: ["llama3:latest"],
    )
    assert classifier.resolve_model("llama3") == "llama3:latest"


def test_resolve_model_falls_back_to_prefix(monkeypatch):
    """The real-world case: user has 'llama3.2:latest' pulled but the
    script defaults to 'llama3'. Prefix match finds the closest variant
    so the user doesn't have to pass --model every run."""
    monkeypatch.setattr(
        classifier, "list_installed_models",
        lambda: ["llama3.2:latest", "codellama:7b"],
    )
    assert classifier.resolve_model("llama3") == "llama3.2:latest"


def test_resolve_model_no_match_returns_input_unchanged(monkeypatch):
    """If nothing remotely matches, return what the user asked for and
    let the next API call surface a clear error."""
    monkeypatch.setattr(
        classifier, "list_installed_models",
        lambda: ["codellama:7b"],
    )
    assert classifier.resolve_model("llama3") == "llama3"


def test_resolve_model_empty_list_returns_input(monkeypatch):
    monkeypatch.setattr(
        classifier, "list_installed_models",
        lambda: [],
    )
    assert classifier.resolve_model("llama3") == "llama3"


def test_classify_raises_when_ollama_is_down(monkeypatch):
    def _refuse(req, timeout=30):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(classifier.urllib.request, "urlopen", _refuse)

    with pytest.raises(OllamaUnreachable) as excinfo:
        classify("report.pdf", [Path("/Users/foo/Desktop/work")])
    assert "ollama serve" in str(excinfo.value).lower()
