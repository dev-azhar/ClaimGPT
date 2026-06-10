import logging
import os
import time
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Default timeouts
DEFAULT_OPENROUTER_TIMEOUT = 60
DEFAULT_GEMINI_TIMEOUT = 60

# Global call timeout (seconds) — raises LLMTimeoutError if exceeded
GLOBAL_CALL_TIMEOUT = 3

LLM_RATE_LIMIT_KEY = "llm:rpm"
LLM_MAX_REQUESTS_PER_MINUTE = int(os.getenv("LLM_MAX_REQUESTS_PER_MINUTE", "8"))


class LLMError(Exception):
    """Base exception for LLM utility errors."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when the overall LLM call exceeds GLOBAL_CALL_TIMEOUT seconds."""
    pass


class OpenRouterError(LLMError):
    """Error from OpenRouter API."""
    pass


class GeminiError(LLMError):
    """Error from Gemini API."""
    pass


def get_openrouter_config() -> dict:
    return {
        "url": os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    }


def get_gemini_config() -> dict:
    return {
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
    }


def _call_openrouter(
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    timeout: int = DEFAULT_OPENROUTER_TIMEOUT,
    deadline: Optional[float] = None,
) -> str:
    """
    Call OpenRouter API, trying each configured API key sequentially.

    Retry behaviour:
      - 401 Unauthorized  → skip to next key (no retry on same key)
      - 429 Rate Limited  → sleep Retry-After (or 1s), then skip to next key
      - Any other error   → skip to next key
    Total attempts = number of keys provided; no per-key retry loop.

    Args:
        deadline: absolute time.monotonic() value; raises LLMTimeoutError if exceeded.
    """
    config = get_openrouter_config()

    if not config["api_key"]:
        raise OpenRouterError("OPENROUTER_API_KEY not configured")

    keys = [k.strip() for k in config["api_key"].replace("|", ",").split(",") if k.strip()]
    if not keys:
        raise OpenRouterError("No valid OpenRouter API keys found")

    url = config["url"]
    model = config["model"]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    last_error = None

    for key_idx, key in enumerate(keys):
        # Check global deadline before each attempt
        if deadline is not None and time.monotonic() >= deadline:
            raise LLMTimeoutError(
                f"LLM call exceeded {GLOBAL_CALL_TIMEOUT}s global timeout "
                f"(before key {key_idx + 1}/{len(keys)})"
            )

        try:
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }

            with httpx.Client() as client:
                response = client.post(url, json=payload, headers=headers, timeout=timeout)

            if response.status_code == 429:
                # retry_after = response.headers.get("Retry-After")
                # sleep_time = int(retry_after) if retry_after and retry_after.isdigit() else 1
                logger.warning("OpenRouter rate limited (429).")
                # time.sleep(sleep_time)
                last_error = OpenRouterError("Rate limited (429)")
                continue

            if response.status_code == 401:
                logger.warning("OpenRouter unauthorized (401) with key %s/%s.", key_idx + 1, len(keys))
                last_error = OpenRouterError("Unauthorized (401)")
                continue

            if response.status_code != 200:
                try:
                    error_json = response.json()
                except Exception:
                    error_json = None

                if error_json:
                    error_obj = error_json.get("error", {})
                    message = str(error_obj.get("message", "")).lower()

                    if any(x in message for x in [
                        "context_length_exceeded", "token_limit_exceeded",
                        "max_tokens_exceeded", "context window", "too many tokens",
                    ]):
                        logger.error(
                            "Token limit exceeded | model=%s max_tokens=%s "
                            "system_chars=%s user_chars=%s",
                            model, max_tokens, len(system_prompt), len(user_message),
                        )

                    logger.error(
                        "OpenRouter error | status=%s code=%s message=%s metadata=%s",
                        response.status_code,
                        error_obj.get("code"),
                        error_obj.get("message"),
                        error_obj.get("metadata"),
                    )
                    last_error = OpenRouterError(f"{error_obj.get('code')} - {error_obj.get('message')}")
                else:
                    logger.error("OpenRouter error | status=%s body=%s", response.status_code, response.text)
                    last_error = OpenRouterError(f"HTTP {response.status_code}: {response.text}")

                continue

            data = response.json()
            usage = data.get("usage", {})
            logger.info(
                "OpenRouter usage | prompt=%s completion=%s total=%s",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )

            if isinstance(data, dict) and data.get("choices"):
                choice = data["choices"][0]
                message_obj = choice.get("message")
                content = message_obj.get("content") if isinstance(message_obj, dict) else message_obj
                if content:
                    return str(content)

            logger.warning("OpenRouter returned no content: %s", data)
            last_error = OpenRouterError("No content in response")
            continue

        except LLMTimeoutError:
            raise  # propagate global timeout immediately

        except httpx.TimeoutException as e:
            logger.warning("OpenRouter HTTP timeout (key %s/%s): %s", key_idx + 1, len(keys), e)
            last_error = OpenRouterError(f"Timeout: {e}")
            continue

        except Exception as e:
            logger.exception("OpenRouter unexpected error (key %s/%s)", key_idx + 1, len(keys))
            last_error = OpenRouterError(f"Error: {e}")
            continue

    error_msg = str(last_error) if last_error else "All OpenRouter API keys failed"
    logger.error("OpenRouter call failed after all keys: %s", error_msg)
    raise OpenRouterError(error_msg)


def _call_gemini(
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    timeout: int = DEFAULT_GEMINI_TIMEOUT,
    deadline: Optional[float] = None,
) -> str:
    """
    Call Gemini API (via REST endpoint). No retries — raises on first failure.

    Args:
        deadline: absolute time.monotonic() value; raises LLMTimeoutError if exceeded.
    """
    # Check deadline before making the call
    if deadline is not None and time.monotonic() >= deadline:
        raise LLMTimeoutError(f"LLM call exceeded {GLOBAL_CALL_TIMEOUT}s global timeout (before Gemini call)")

    config = get_gemini_config()

    if not config["api_key"]:
        raise GeminiError("GEMINI_API_KEY not configured")

    model = config["model"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"System: {system_prompt}\n\nUser: {user_message}"}],
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }

    try:
        with httpx.Client() as client:
            response = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                params={"key": config["api_key"]},
                timeout=timeout,
            )

        if response.status_code == 429:
            raise GeminiError("Rate limited (429)")

        if response.status_code in (401, 403):
            raise GeminiError(f"Authentication error ({response.status_code})")

        if response.status_code != 200:
            raise GeminiError(f"HTTP {response.status_code}: {response.text}")

        data = response.json()

        if isinstance(data, dict) and data.get("candidates"):
            candidate = data["candidates"][0]
            content = candidate.get("content")
            if isinstance(content, dict) and content.get("parts"):
                text = content["parts"][0].get("text")
                if text:
                    return str(text)

        logger.warning("Gemini returned no content: %s", data)
        raise GeminiError("No content in response")

    except LLMTimeoutError:
        raise  # propagate global timeout immediately

    except httpx.TimeoutException as e:
        raise GeminiError(f"Timeout: {e}") from e

    except httpx.HTTPError as e:
        raise GeminiError(f"HTTP error: {e}") from e

    except GeminiError:
        raise

    except Exception as e:
        raise GeminiError(f"Error: {e}") from e


def call_llm(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    fallback_to_gemini: bool = True,
    openrouter_timeout: int = DEFAULT_OPENROUTER_TIMEOUT,
    gemini_timeout: int = DEFAULT_GEMINI_TIMEOUT,
) -> str:
    """
    Call an LLM with primary OpenRouter support and optional Gemini fallback.

    Raises LLMTimeoutError if the total elapsed time exceeds GLOBAL_CALL_TIMEOUT (3s).

    Retry summary:
      - OpenRouter: one attempt per API key (no per-key retry); 429 sleeps then moves to next key.
      - Gemini: no retries — raises immediately on any failure.

    Args:
        system_prompt: System prompt/instructions for the LLM
        user_message: User message/query
        max_tokens: Maximum tokens to generate (default: 1024)
        temperature: Temperature for generation, 0.0-1.0 (default: 0.7)
        fallback_to_gemini: If True, fall back to Gemini on OpenRouter failure (default: True)
        openrouter_timeout: Per-request HTTP timeout for OpenRouter in seconds (default: 60)
        gemini_timeout: Per-request HTTP timeout for Gemini in seconds (default: 60)

    Returns:
        str: The LLM response text

    Raises:
        LLMTimeoutError: If the overall call exceeds GLOBAL_CALL_TIMEOUT seconds
        LLMError: If all available LLM providers fail
    """
    deadline = time.monotonic() + GLOBAL_CALL_TIMEOUT
    logger.info("Starting LLM call | provider=openrouter fallback=%s", fallback_to_gemini)

    try:
        response = _call_openrouter(
            system_prompt, user_message, max_tokens, temperature, openrouter_timeout, deadline
        )
        logger.info("LLM call succeeded | provider=openrouter")
        return response

    except LLMTimeoutError:
        raise

    except OpenRouterError as e:
        logger.warning("OpenRouter failed: %s", e)

        if not fallback_to_gemini:
            raise LLMError(f"OpenRouter failed: {e}") from e

        logger.info("Falling back to Gemini")

    try:
        response = _call_gemini(
            system_prompt, user_message, max_tokens, temperature, gemini_timeout, deadline
        )
        logger.info("LLM call succeeded | provider=gemini (fallback)")
        return response

    except LLMTimeoutError:
        raise

    except GeminiError as e:
        logger.error("Gemini fallback failed: %s", e)
        raise LLMError(f"All LLM providers failed. Last error: {e}") from e