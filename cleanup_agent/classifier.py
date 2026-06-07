"""Ollama wrapper: ask llama3 to pick a destination for a filename, return
(suggested_path, confidence). Confidence is the model's self-report — not
calibrated — but it's enough to flag iffy suggestions in the UI.

We validate the model's answer against the list of allowed destinations
and fall back to (None, 'low') if it hallucinates a path that wasn't in
the list."""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

# 127.0.0.1 instead of localhost: Ollama binds to IPv4 only, and Python's
# urllib doesn't always fall back from IPv6 cleanly on macOS.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "llama3"
VALID_CONFIDENCES = ("low", "medium", "high")


class OllamaUnreachable(RuntimeError):
    """Raised when Ollama isn't running / can't be reached at the URL."""


def classify(filename, destinations, model=DEFAULT_MODEL, timeout=30):
    """Ask Ollama to pick a destination for `filename` from `destinations`.

    Returns (suggested: Path | None, confidence: str). On parse failure or
    a hallucinated destination not in the list, returns (None, 'low') so
    the caller can fall back to manual edit mode without crashing."""
    if not destinations:
        return None, "low"

    prompt = _build_prompt(filename, destinations)
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Ollama is reachable but rejected the request — usually model not
        # found or a bad payload. Surface the body so the user sees why.
        body = e.read().decode("utf-8", errors="replace")[:400]
        raise OllamaUnreachable(
            f"Ollama returned HTTP {e.code}: {body}\n"
            f"  endpoint: {OLLAMA_URL}\n"
            f"  model:    {model}"
        ) from e
    except urllib.error.URLError as e:
        # Network-level failure. Distinguish "not running" from other causes
        # so the message isn't misleading when Ollama actually is up.
        reason = getattr(e, "reason", e)
        raise OllamaUnreachable(
            f"Couldn't reach Ollama: {reason}\n"
            f"  endpoint: {OLLAMA_URL}\n"
            f"  If Ollama isn't running, start it with `ollama serve`."
        ) from e

    raw = payload.get("response", "")
    parsed = _extract_json(raw)
    if not parsed:
        return None, "low"

    dest = parsed.get("destination")
    confidence = str(parsed.get("confidence", "low")).lower()
    if confidence not in VALID_CONFIDENCES:
        confidence = "low"

    allowed = {str(d) for d in destinations}
    if dest in allowed:
        return Path(dest), confidence
    return None, "low"


def _build_prompt(filename, destinations):
    dest_list = "\n".join(f"  {d}" for d in destinations)
    return (
        "You are a file organization assistant. Pick the single best "
        "directory to move a file into, chosen from the list provided.\n\n"
        f"Filename: {filename}\n\n"
        f"Existing directories:\n{dest_list}\n\n"
        "Respond with ONLY a JSON object in this exact format:\n"
        '{"destination": "<one full path from the list above>", '
        '"confidence": "low" | "medium" | "high"}'
    )


def _extract_json(text):
    """Pull a JSON object out of model output, even if wrapped in markdown
    fences or surrounded by prose. Returns the parsed dict or None."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Greedy match — capture the largest {...} block.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
