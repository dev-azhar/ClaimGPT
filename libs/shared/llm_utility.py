# """
# LLM Utility Module

# Provides a unified interface for LLM calls with primary OpenRouter support
# and automatic fallback to Gemini API.
# """

# import logging
# import os
# import httpx
# from typing import Optional

# logger = logging.getLogger(__name__)

# # Default timeouts
# DEFAULT_OPENROUTER_TIMEOUT = 60
# DEFAULT_GEMINI_TIMEOUT = 60

# import time
# import redis

# # REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# # redis_client = redis.from_url(
# #     REDIS_URL,
# #     decode_responses=True,
# # )

# LLM_RATE_LIMIT_KEY = "llm:rpm"
# LLM_MAX_REQUESTS_PER_MINUTE = int(
#     os.getenv("LLM_MAX_REQUESTS_PER_MINUTE", "8")
# )

# # def _wait_for_rate_limit() -> None:
# #     """
# #     Global Redis-backed rate limiter.

# #     Ensures all workers together do not exceed
# #     LLM_MAX_REQUESTS_PER_MINUTE.
# #     """

# #     while True:
# #         current = redis_client.incr(LLM_RATE_LIMIT_KEY)

# #         if current == 1:
# #             redis_client.expire(LLM_RATE_LIMIT_KEY, 60)

# #         if current <= LLM_MAX_REQUESTS_PER_MINUTE:
# #             return

# #         redis_client.decr(LLM_RATE_LIMIT_KEY)

# #         ttl = redis_client.ttl(LLM_RATE_LIMIT_KEY)

# #         sleep_time = min(
# #             max(ttl, 1),
# #             5,
# #         )

# #         logger.warning(
# #             "LLM global rate limit reached. "
# #             f"Sleeping {sleep_time}s"
# #         )

# #         time.sleep(sleep_time)

# class LLMError(Exception):
#     """Base exception for LLM utility errors."""
#     pass


# class OpenRouterError(LLMError):
#     """Error from OpenRouter API."""
#     pass


# class GeminiError(LLMError):
#     """Error from Gemini API."""
#     pass


# def get_openrouter_config() -> dict:
#     """
#     Get OpenRouter configuration from environment variables.
    
#     Returns:
#         dict with keys: url, api_key, model
#     """
#     return {
#         "url": os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"),
#         "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
#         "model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
#     }


# def get_gemini_config() -> dict:
#     """
#     Get Gemini configuration from environment variables.
    
#     Returns:
#         dict with keys: api_key, model
#     """
#     return {
#         "api_key": os.environ.get("GEMINI_API_KEY", ""),
#         "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
#     }


# def _call_openrouter(
#     system_prompt: str,
#     user_message: str,
#     max_tokens: int,
#     temperature: float,
#     timeout: int = DEFAULT_OPENROUTER_TIMEOUT,
# ) -> str:
#     """
#     Call OpenRouter API.
    
#     Args:
#         system_prompt: System prompt for the LLM
#         user_message: User message/query
#         max_tokens: Maximum tokens to generate
#         temperature: Temperature for generation (0.0-1.0)
#         timeout: Request timeout in seconds
        
#     Returns:
#         LLM response text
        
#     Raises:
#         OpenRouterError: If the API call fails
#     """
#     config = get_openrouter_config()
    
#     if not config["api_key"]:
#         raise OpenRouterError("OPENROUTER_API_KEY not configured")
    
#     # Support multiple keys separated by commas or pipes
#     keys = [k.strip() for k in config["api_key"].replace("|", ",").split(",") if k.strip()]
#     if not keys:
#         raise OpenRouterError("No valid OpenRouter API keys found")
    
#     url = config["url"]
#     model = config["model"]
    
#     payload = {
#         "model": model,
#         "messages": [
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_message},
#         ],
#         "max_tokens": max_tokens,
#         "temperature": temperature,
#     }
    
#     last_error = None
    
#     # Try each key sequentially
#     for key_idx, key in enumerate(keys):
#         try:
#             headers = {
#                 "Authorization": f"Bearer {key}",
#                 "Content-Type": "application/json",
                
#             }
            
#             logger.debug(f"Attempting OpenRouter call with key {key_idx + 1}/{len(keys)}")
#             # _wait_for_rate_limit()
#             with httpx.Client() as client:
#                 response = client.post(url, json=payload, headers=headers, timeout=timeout)
            
#             if response.status_code == 429:
#                 retry_after = response.headers.get(
#                     "Retry-After"
#                 )

#                 sleep_time = (
#                     int(retry_after)
#                     if retry_after and retry_after.isdigit()
#                     else 1
#                 )

#                 logger.warning(
#                     f"OpenRouter rate limited (429). "
#                     f"Sleeping {sleep_time}s"
#                 )

#                 time.sleep(sleep_time)

#                 last_error = OpenRouterError(
#                     "Rate limited (429)"
#                 )

#                 continue
                        
#             if response.status_code == 401:
#                 # Unauthorized - try next key
#                 logger.warning(f"OpenRouter unauthorized (401) with key {key_idx + 1}/{len(keys)}")
#                 last_error = OpenRouterError(f"Unauthorized (401)")
#                 continue
            
#             if response.status_code != 200:
#                 try:
#                     error_json = response.json()
#                 except Exception:
#                     error_json = None

#                 logger.error(
#                     "OpenRouter Failed | status=%s model=%s "
#                     "response=%s",
#                     response.status_code,
#                     model,
#                     error_json if error_json else response.text,
#                 )

#                 if error_json:
#                     error_obj = error_json.get("error", {})
#                     message = str(error_obj.get("message", "")).lower()

#                     if any(
#                         x in message
#                         for x in [
#                             "context_length_exceeded",
#                             "token_limit_exceeded",
#                             "max_tokens_exceeded",
#                             "context window",
#                             "too many tokens",
#                         ]
#                     ):
#                         logger.error(
#                             "TOKEN LIMIT ERROR | "
#                             "model=%s max_tokens=%s "
#                             "system_chars=%s user_chars=%s",
#                             model,
#                             max_tokens,
#                             len(system_prompt),
#                             len(user_message),
#                         )

#                     logger.error(
#                         "OpenRouter Error Details | "
#                         "code=%s message=%s metadata=%s",
#                         error_obj.get("code"),
#                         error_obj.get("message"),
#                         error_obj.get("metadata"),
#                     )

#                     last_error = OpenRouterError(
#                         f"{error_obj.get('code')} - "
#                         f"{error_obj.get('message')}"
#                     )
#                 else:
#                     last_error = OpenRouterError(
#                         f"HTTP {response.status_code}: {response.text}"
#                     )

#                 continue
            
#             # Success!
#             data = response.json()
#             usage = data.get("usage", {})

#             logger.info(
#                 "OpenRouter Usage | "
#                 "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
#                 usage.get("prompt_tokens"),
#                 usage.get("completion_tokens"),
#                 usage.get("total_tokens"),
#             )
                        
#             # Extract response content from standard OpenAI format
#             if isinstance(data, dict):
#                 if "choices" in data and data["choices"]:
#                     choice = data["choices"][0]
#                     message = choice.get("message")
#                     if isinstance(message, dict):
#                         content = message.get("content")
#                     else:
#                         content = message
                    
#                     if content:
#                         logger.debug("OpenRouter call successful")
#                         return str(content)
            
#             # No content in response
#             logger.warning(f"OpenRouter returned no content: {data}")
#             last_error = OpenRouterError("No content in response")
#             continue
            
#         except httpx.TimeoutException as e:
#             logger.warning(f"OpenRouter timeout with key {key_idx + 1}/{len(keys)}: {e}")
#             last_error = OpenRouterError(f"Timeout: {e}")
#             continue
#         except Exception as e:
#             logger.exception(
#                 "OpenRouter Exception | "
#                 "key=%s/%s model=%s",
#                 key_idx + 1,
#                 len(keys),
#                 model,
#             )
#             last_error = OpenRouterError(f"Error: {e}")
#             continue
    
#     # All keys failed
#     error_msg = str(last_error) if last_error else "All OpenRouter API keys failed"
#     logger.error(f"OpenRouter call failed: {error_msg}")
#     raise OpenRouterError(error_msg)


# def _call_gemini(
#     system_prompt: str,
#     user_message: str,
#     max_tokens: int,
#     temperature: float,
#     timeout: int = DEFAULT_GEMINI_TIMEOUT,
# ) -> str:
#     """
#     Call Gemini API (via REST endpoint).
    
#     Args:
#         system_prompt: System prompt for the LLM
#         user_message: User message/query
#         max_tokens: Maximum tokens to generate
#         temperature: Temperature for generation (0.0-1.0)
#         timeout: Request timeout in seconds
        
#     Returns:
#         LLM response text
        
#     Raises:
#         GeminiError: If the API call fails
#     """
#     config = get_gemini_config()
    
#     if not config["api_key"]:
#         raise GeminiError("GEMINI_API_KEY not configured")
    
#     model = config["model"]
#     url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
#     payload = {
#         "contents": [
#             {
#                 "role": "user",
#                 "parts": [
#                     {"text": f"System: {system_prompt}\n\nUser: {user_message}"}
#                 ]
#             }
#         ],
#         "generationConfig": {
#             "maxOutputTokens": max_tokens,
#             "temperature": temperature,
#         }
#     }
    
#     headers = {
#         "Content-Type": "application/json",
#     }
    
#     try:
#         logger.debug("Attempting Gemini call")
#         # _wait_for_rate_limit()
#         with httpx.Client() as client:
#             response = client.post(
#                 url,
#                 json=payload,
#                 headers=headers,
#                 params={"key": config["api_key"]},
#                 timeout=timeout
#             )
        
#         if response.status_code == 429:
#             raise GeminiError("Rate limited (429)")
        
#         if response.status_code == 401 or response.status_code == 403:
#             raise GeminiError(f"Authentication error ({response.status_code})")
        
#         if response.status_code != 200:
#             raise GeminiError(f"HTTP {response.status_code}: {response.text}")
        
#         data = response.json()
        
#         # Extract response content from Gemini API format
#         if isinstance(data, dict):
#             if "candidates" in data and data["candidates"]:
#                 candidate = data["candidates"][0]
#                 content = candidate.get("content")
#                 if isinstance(content, dict) and "parts" in content:
#                     parts = content["parts"]
#                     if parts and isinstance(parts[0], dict):
#                         text = parts[0].get("text")
#                         if text:
#                             logger.debug("Gemini call successful")
#                             return str(text)
        
#         # No content in response
#         logger.warning(f"Gemini returned no content: {data}")
#         raise GeminiError("No content in response")
        
#     except httpx.TimeoutException as e:
#         logger.warning(f"Gemini timeout: {e}")
#         raise GeminiError(f"Timeout: {e}")
#     except httpx.HTTPError as e:
#         logger.warning(f"Gemini HTTP error: {e}")
#         raise GeminiError(f"HTTP error: {e}")
#     except Exception as e:
#         logger.warning(f"Gemini error: {e}")
#         raise GeminiError(f"Error: {e}")


# def call_llm(
#     system_prompt: str,
#     user_message: str,
#     max_tokens: int = 1024,
#     temperature: float = 0.7,
#     fallback_to_gemini: bool = True,
#     openrouter_timeout: int = DEFAULT_OPENROUTER_TIMEOUT,
#     gemini_timeout: int = DEFAULT_GEMINI_TIMEOUT,
# ) -> str:
#     """
#     Call an LLM with primary OpenRouter support and optional Gemini fallback.
    
#     This function attempts to call OpenRouter first. If that fails (due to rate
#     limiting, authentication issues, or other errors), it automatically falls
#     back to Gemini API if fallback_to_gemini is True.
    
#     Args:
#         system_prompt: System prompt/instructions for the LLM
#         user_message: User message/query
#         max_tokens: Maximum tokens to generate (default: 1024)
#         temperature: Temperature for generation, 0.0-1.0 (default: 0.7)
#         fallback_to_gemini: If True, fall back to Gemini on OpenRouter failure (default: True)
#         openrouter_timeout: Timeout for OpenRouter API call in seconds (default: 60)
#         gemini_timeout: Timeout for Gemini API call in seconds (default: 60)
        
#     Returns:
#         str: The LLM response text
        
#     Raises:
#         LLMError: If all available LLM providers fail
        
#     Example:
#         >>> response = call_llm(
#         ...     system_prompt="You are a medical coding expert.",
#         ...     user_message="Extract diagnosis codes from: ICD-10 code for diabetes",
#         ...     max_tokens=256,
#         ...     temperature=0.1,
#         ...     openrouter_timeout=90
#         ... )
#         >>> print(response)
#     """
#     logger.info("Starting LLM call with OpenRouter as primary provider")
    
#     # Try OpenRouter first
#     try:
#         response = _call_openrouter(system_prompt, user_message, max_tokens, temperature, openrouter_timeout)
#         logger.info("Successfully used OpenRouter provider")
#         return response
#     except OpenRouterError as e:
#         logger.warning(f"OpenRouter call failed: {e}")
        
#         if not fallback_to_gemini:
#             logger.error("OpenRouter failed and fallback disabled")
#             raise LLMError(f"OpenRouter failed: {e}") from e
        
#         logger.info("Falling back to Gemini API")
    
#     # Try Gemini as fallback
#     try:
#         response = _call_gemini(system_prompt, user_message, max_tokens, temperature, gemini_timeout)
#         logger.info("Successfully used Gemini provider (fallback)")
#         return response
#     except GeminiError as e:
#         logger.error(f"Gemini fallback also failed: {e}")
#         raise LLMError(f"All LLM providers failed. OpenRouter: {e}, Gemini: {e}") from e

"""
LLM Utility Module

Provides a unified interface for LLM calls with primary OpenRouter support
and automatic fallback to Gemini API.
"""

import logging
import os
import time
import httpx
from typing import Optional

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
