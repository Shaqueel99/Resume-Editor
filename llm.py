"""
llm.py — single LiteLLM wrapper used by every other module.

All LLM calls in this project go through ask_json() or ask_text().
No other module imports litellm directly.

Supported MODEL prefixes (set in .env or Streamlit secrets):
  openai/...    — cloud; requires OPENAI_API_KEY
  anthropic/... — cloud; requires ANTHROPIC_API_KEY
  gemini/...    — cloud; requires GEMINI_API_KEY
  ollama/...    — local; requires `ollama serve` and the model to be pulled;
                  no API key; reads OLLAMA_API_BASE (default localhost:11434)
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from litellm import completion
import litellm

load_dotenv()

_MODEL = os.getenv("MODEL", "openai/gpt-4o-mini")

# Phrases that indicate the LLM violated the anti-rewrite rule.
_REWRITE_MARKERS = ("here is a rewritten", "improved version:")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_ollama(model: str) -> bool:
    return model.startswith("ollama/")


def _call_kwargs(model: str, messages: list, temperature: float, max_tokens: int) -> dict:
    """Build keyword arguments for a litellm completion() call."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if _is_ollama(model):
        # Ollama does not support response_format on all models; omit it.
        # Omit max_tokens so Ollama uses its full context window (equiv. to -2).
        # Cloud routes need an explicit limit both for cost control and because
        # OpenAI/Anthropic reject non-positive max_tokens values.
        kwargs["api_base"] = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    else:
        # openai/* and anthropic/* both honour JSON mode.
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["max_tokens"] = max_tokens
    return kwargs


def _strip_fences(text: str) -> str:
    """Remove leading ```json / ``` and trailing ``` markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line (e.g. ```json\n...)
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text


def _parse_json(text: str) -> dict:
    """
    Parse the first JSON object in *text*, tolerating preamble and trailing
    content (e.g. "Here is the JSON:\n{...}\nHope that helps!").

    Strategy:
      1. Find the first '{' and use JSONDecoder.raw_decode() to parse exactly
         one object starting there, stopping at the matching '}' and ignoring
         anything after it.
      2. Fall back to plain json.loads() on the full text so the error message
         is useful if no '{' is found at all.

    Raises json.JSONDecodeError if parsing fails.
    """
    start = text.find("{")
    if start != -1:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return obj  # type: ignore[return-value]
    # No '{' found — attempt full parse so the JSONDecodeError is informative.
    return json.loads(text)  # type: ignore[return-value]


def _check_no_rewrite(data: object, path: str = "") -> None:
    """Raise RuntimeError if any string field contains a rewrite marker."""
    if isinstance(data, dict):
        for key, value in data.items():
            _check_no_rewrite(value, f"{path}.{key}" if path else key)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            _check_no_rewrite(item, f"{path}[{i}]")
    elif isinstance(data, str):
        lower = data.lower()
        for marker in _REWRITE_MARKERS:
            if marker in lower:
                raise RuntimeError(
                    f"Anti-rewrite rule violation in field '{path}': "
                    f"the LLM generated résumé content ('{marker}'). "
                    "This is not allowed — check the prompt."
                )


def _raise_auth_error(model: str, exc: Exception) -> None:
    """Raise a RuntimeError naming the missing env var for the chosen route."""
    if model.startswith("anthropic/"):
        var = "ANTHROPIC_API_KEY"
    elif model.startswith("gemini/"):
        var = "GEMINI_API_KEY"
    else:
        var = "OPENAI_API_KEY"
    raise RuntimeError(
        f"{var} is invalid or missing for route '{model}'. "
        "Check your Streamlit secrets or .env file."
    ) from exc

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ask_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1500,
) -> dict:
    """
    Send (system, user) to the configured LLM, expect JSON, return as dict.

    Retries up to 3 times: on RateLimitError (exponential back-off 1s, 2s)
    and on JSONDecodeError (sends a correction message asking for valid JSON).
    Raises RuntimeError on authentication failure, connection failure, or
    if JSON cannot be parsed after the retry.
    """
    model = _MODEL
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for attempt in range(3):
        try:
            response = completion(**_call_kwargs(model, messages, temperature, max_tokens))

        except (litellm.RateLimitError, litellm.ServiceUnavailableError) as exc:
            # Rate limit or service-overloaded (503) — back off and retry.
            if attempt < 2:
                sleep_secs = 2 ** attempt   # 1s, then 2s
                print(f"{type(exc).__name__}; retrying in {sleep_secs}s…", file=sys.stderr)
                time.sleep(sleep_secs)
                continue
            raise RuntimeError(f"{type(exc).__name__} after 3 attempts. Try again later.")

        except litellm.AuthenticationError as exc:
            # Auth failure — name the missing env var so the student can fix it.
            _raise_auth_error(model, exc)

        except litellm.APIConnectionError as exc:
            # Connection failure — Ollama not running, or network error.
            if _is_ollama(model):
                api_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
                raise RuntimeError(
                    f"Cannot reach Ollama at {api_base}. Is `ollama serve` running?"
                ) from exc
            raise RuntimeError(f"API connection error: {exc}") from exc

        except Exception as exc:
            # Catch Ollama "model not found" (surfaces as a non-litellm error).
            msg = str(exc).lower()
            if _is_ollama(model) and ("not found" in msg or "unknown model" in msg):
                model_name = model.removeprefix("ollama/")
                raise RuntimeError(
                    f"Ollama model '{model_name}' not found. "
                    f"Run: ollama pull {model_name}"
                ) from exc
            raise

        # ---- response received ----

        choice = response.choices[0]

        if choice.finish_reason == "length":
            # Output was cut off mid-token — warn but try to parse anyway.
            print(
                "WARNING: finish_reason='length'; response was truncated. "
                "JSON may be incomplete.",
                file=sys.stderr,
            )

        raw = choice.message.content or ""
        raw = _strip_fences(raw)

        try:
            parsed = _parse_json(raw)
        except json.JSONDecodeError as exc:
            if attempt < 2:
                print(
                    f"JSON parse error on attempt {attempt + 1}; retrying.",
                    file=sys.stderr,
                )
                snippet = raw[max(0, exc.pos - 20): exc.pos + 80]
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous output could not be parsed as JSON.\n"
                        f"Error: {exc.msg} (at position {exc.pos})\n"
                        f"Near: ...{snippet!r}...\n\n"
                        "Please return ONLY the corrected JSON object — "
                        "no prose, no markdown fences."
                    ),
                })
                continue
            snippet = raw[max(0, exc.pos - 60): exc.pos + 120]
            raise RuntimeError(
                f"LLM returned non-JSON after {attempt + 1} attempts.\n"
                f"Parse error: {exc.msg} (line {exc.lineno}, col {exc.colno}, "
                f"char {exc.pos} of {len(raw)}).\n"
                f"finish_reason: {choice.finish_reason!r} "
                f"(if 'length', the response was cut off by max_tokens).\n"
                f"Near error position: ...{snippet!r}...\n"
                f"Raw (first 500 chars):\n{raw[:500]}"
            )

        # Post-hoc anti-rewrite check on every returned JSON object.
        _check_no_rewrite(parsed)
        return parsed

    raise RuntimeError("ask_json: all retry attempts exhausted")


def ask_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 600,
) -> str:
    """
    Send (system, user) to the LLM, return plain text.

    Same retry behaviour as ask_json for RateLimitError and
    AuthenticationError. Does not request JSON mode.
    """
    model = _MODEL
    # For ask_text, never pass response_format — we want plain text.
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if _is_ollama(model):
        kwargs["api_base"] = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    else:
        kwargs["max_tokens"] = max_tokens

    for attempt in range(3):
        try:
            response = completion(**kwargs)
        except (litellm.RateLimitError, litellm.ServiceUnavailableError) as exc:
            # Back off and retry on rate limit or service-overloaded (503).
            if attempt < 2:
                sleep_secs = 2 ** attempt
                print(f"{type(exc).__name__}; retrying in {sleep_secs}s…", file=sys.stderr)
                time.sleep(sleep_secs)
                continue
            raise RuntimeError(f"{type(exc).__name__} after 3 attempts.")
        except litellm.AuthenticationError as exc:
            _raise_auth_error(model, exc)
        except litellm.APIConnectionError as exc:
            if _is_ollama(model):
                api_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
                raise RuntimeError(
                    f"Cannot reach Ollama at {api_base}. Is `ollama serve` running?"
                ) from exc
            raise RuntimeError(f"API connection error: {exc}") from exc
        except Exception as exc:
            msg = str(exc).lower()
            if _is_ollama(model) and ("not found" in msg or "unknown model" in msg):
                model_name = model.removeprefix("ollama/")
                raise RuntimeError(
                    f"Ollama model '{model_name}' not found. "
                    f"Run: ollama pull {model_name}"
                ) from exc
            raise

        return response.choices[0].message.content or ""

    raise RuntimeError("ask_text: all retry attempts exhausted")
