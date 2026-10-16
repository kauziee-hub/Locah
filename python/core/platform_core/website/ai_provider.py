"""AI model provider abstraction (Doc 12 §12.2).

`get_ai_provider()` returns DeepSeek by default (`AI_PROVIDER=deepseek`), Gemini
when `AI_PROVIDER=gemini`, or, for local acceptance runs, the recorded replay
provider; `UnavailableAIProvider` when no key is configured. Callers describe a
*purpose*; each provider maps the purpose to its own model, so no vendor model
name leaks into business logic. Callers always keep the deterministic fallback
path (Doc 12 §12.1) regardless. Voice is separate: `VOICE_PROVIDER` stays Gemini.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from platform_core.ai_guard import guard_external_ai
from platform_core.logging import get_logger

_log = get_logger("website.ai_provider")

# Content generation only — never platform mechanics (Doc 12 §12.6).


@runtime_checkable
class AIModelProvider(Protocol):
    provider_name: str

    @property
    def model_name(self) -> str: ...

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class AIProviderPermanentError(RuntimeError):
    """The provider refused in a way that retrying cannot fix.

    A rejected key, a revoked key or an unknown model fails identically on every
    attempt, so retrying only delays the deterministic fallback — and the owner
    is sitting in onboarding watching it. Retry the transient cases only.
    """


class AIProviderBillingError(AIProviderPermanentError):
    """Google refused on billing (HTTP 402 — prepaid credit depleted, billing off).

    Every fallback model bills to the same Google project and refuses the same
    way, so this is one call, never one per model. Its own type so the job's
    `fallback_reason` and the logs say billing, not a generic failure.
    """


class UnavailableAIProvider:
    """Default provider when no API key is configured — always fails fast."""

    provider_name = "unavailable"

    @property
    def model_name(self) -> str:
        return "unavailable"

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "AI provider not configured (no key for AI_PROVIDER); use deterministic fallback"
        )

    async def generate_structured_from_file(
        self, prompt: str, data: bytes, mime_type: str, schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        raise RuntimeError("AI provider not configured (no key for AI_PROVIDER)")

    async def generate_structured_with_images(
        self, prompt: str, images: list[Any], schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        raise RuntimeError("AI provider not configured (no key for AI_PROVIDER)")


# ---------------------------------------------------------------- Gemini

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"

# One fast model everywhere by default; the purposes differ in how much the
# model is allowed to think. Routine extraction is quotation and must answer
# while the owner is waiting, so it thinks least. Website strategy and copy are
# the one place where a little more deliberation visibly changes the result.
_GEMINI_THINKING = {
    "business.interview": "low",
    # Reading a menu or catalogue is transcription with judgement about what is
    # a heading and what is an item; a little thinking, not much.
    "document.extract": "low",
    "website.design_strategy": "medium",
    "website.personalization": "medium",
    "website.generate": "medium",
}

# Keywords JSON Schema allows but Gemini's structured-output subset rejects or
# ignores. Pydantic emits them; they carry no constraint the platform relies
# on, because every response is re-validated by the same Pydantic model.
_UNSUPPORTED_SCHEMA_KEYS = {"title", "default", "$schema", "examples", "discriminator"}


# Gemini's structured output accepts a narrower JSON Schema than Pydantic
# writes, and the subset differs by model. Live, with the interview schema:
# `maxLength: 4000` failed on gemini-3.8-flash ("400 invalid argument", or a 503
# "high demand" from the grammar build), and on gemini-3.5-flash the remaining
# constraint keywords failed too — while the same schema with only type,
# properties, items, enum, required and description was accepted by both.
# So only that core is sent. Every limit still reaches the model as guidance
# in the description, and `_fit` enforces all of them on the answer before
# the caller's own Pydantic validation runs.
_GEMINI_KEEP = {"type", "properties", "items", "enum", "required", "description", "anyOf", "nullable"}


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema as Gemini will accept it: references inlined, constraints as guidance."""

    def relax(node: Any) -> Any:
        if isinstance(node, list):
            return [relax(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: relax(sub) for name, sub in value.items()}
            elif key in _GEMINI_KEEP:
                out[key] = relax(value)
        if "const" in node and "enum" not in out:
            # A single allowed value is still a constraint worth decoding.
            out["enum"] = [node["const"]]
        hints = []
        if isinstance(node.get("minimum"), (int, float)) or isinstance(node.get("maximum"), (int, float)):
            hints.append(f"Between {node.get('minimum', '-inf')} and {node.get('maximum', 'inf')}.")
        if isinstance(node.get("maxLength"), int):
            hints.append(f"At most {node['maxLength']} characters.")
        if isinstance(node.get("maxItems"), int):
            hints.append(f"At most {node['maxItems']} items.")
        if hints:
            out["description"] = " ".join([str(out.get("description", ""))] + hints).strip()
        return out

    relaxed = relax(_inline_schema(schema))
    return relaxed if isinstance(relaxed, dict) else {}


def _fit(value: Any, schema: Any) -> Any:
    """Hold an answer to the limits Gemini was only told about.

    Strings are trimmed to maxLength, lists capped at maxItems, list items that
    break minLength or miss a required field are dropped, and keys a closed
    object does not declare are removed — the smallest repair that lets one
    over-eager field survive instead of failing the whole answer.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, str):
        limit = schema.get("maxLength")
        return value[:limit] if isinstance(limit, int) else value
    if isinstance(value, list):
        item_schema = schema.get("items")
        kept = [_fit(item, item_schema) for item in value]
        kept = [item for item in kept if _acceptable(item, item_schema)]
        limit = schema.get("maxItems")
        return kept[:limit] if isinstance(limit, int) else kept
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        closed = schema.get("additionalProperties") is False
        return {k: _fit(v, props.get(k)) for k, v in value.items() if not closed or k in props}
    return value


def _acceptable(item: Any, schema: Any) -> bool:
    if not isinstance(schema, dict):
        return True
    if isinstance(item, str):
        return len(item) >= int(schema.get("minLength") or 0)
    if isinstance(item, dict):
        props = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in item:
                return False
            sub = props.get(name)
            if isinstance(item[name], str) and isinstance(sub, dict):
                if len(item[name]) < int(sub.get("minLength") or 0):
                    return False
    return True


def _inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline `$defs` references and drop keywords Gemini does not accept."""
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 24:
            return {}
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                target = defs.get(ref.rsplit("/", 1)[-1], {})
                merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged, depth + 1)
            out: dict[str, Any] = {}
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    # Property *names* are data, not keywords: a field called
                    # "title" was being stripped as if it were the keyword, and
                    # Gemini rightly refused a schema requiring a missing field.
                    out[key] = {name: resolve(sub, depth + 1) for name, sub in value.items()}
                elif key not in _UNSUPPORTED_SCHEMA_KEYS and key not in {"$defs", "definitions"}:
                    out[key] = resolve(value, depth + 1)
            return out
        if isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        return node

    resolved = resolve(schema)
    return resolved if isinstance(resolved, dict) else {}


# Tried in order after the purpose's own model. In the live run each one was
# busy at some moment (3.5-flash: a 503 after 31 s) and another answered.
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash,gemini-3.1-flash-lite"


class _GeminiRejected(Exception):
    """A non-2xx answer: the status, and the error callers should finally see."""

    def __init__(self, status: int, error: Exception) -> None:
        super().__init__(str(error))
        self.status = status
        self.error = error


class GeminiProvider:
    """Google Gemini `generateContent` with native JSON-schema structured output.

    Schema compliance is a convenience, not a guarantee the platform trusts:
    every caller re-validates with its own Pydantic model and deterministic
    rules. A quota or credential failure is
    permanent for the request — retrying a 429 on a free tier only spends the
    remaining allowance faster.
    """

    provider_name = "gemini"

    def __init__(self, api_key: str, model: str = GEMINI_DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model
        self._model_used: str | None = None
        self.last_usage: dict[str, Any] | None = None

    @property
    def model_name(self) -> str:
        """The model that actually answered last — the fallback, when it did."""
        return self._model_used or self._model

    def model_for(self, purpose: str | None) -> str:
        key = str(purpose or "")
        if key == "business.interview":
            return os.getenv("GEMINI_INTERVIEW_MODEL", "").strip() or self._model
        if key.startswith("website."):
            return os.getenv("GEMINI_WEBSITE_MODEL", "").strip() or self._model
        if key.startswith("document."):
            return os.getenv("GEMINI_DOCUMENT_MODEL", "").strip() or self._model
        return self._model

    def build_body(
        self, prompt: str, schema: dict[str, Any], model_config: dict[str, Any],
        file: tuple[bytes, str] | None = None, more_files: list[tuple[bytes, str]] | None = None,
    ) -> dict[str, Any]:
        purpose = model_config.get("purpose")
        generation: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": _gemini_schema(schema),
            "maxOutputTokens": int(model_config.get("max_output_tokens", 8192)),
        }
        if "temperature" in model_config:
            generation["temperature"] = float(model_config["temperature"])
        thinking = model_config.get("thinking_level") or _GEMINI_THINKING.get(str(purpose or ""))
        if thinking:
            generation["thinkingConfig"] = {"thinkingLevel": thinking}
        parts: list[dict[str, Any]] = []
        import base64

        # The owner's own document, inline: a menu photo or a catalogue PDF —
        # or the candidate pictures a judge is asked to compare.
        for attached in ([file] if file is not None else []) + list(more_files or []):
            parts.append({"inlineData": {"mimeType": attached[1], "data": base64.b64encode(attached[0]).decode()}})
        parts.append({"text": prompt})
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation,
        }
        system_prompt = model_config.get("system_prompt")
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": str(system_prompt)}]}
        return body

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        model_config: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """One structured answer, from the purpose's model or — once — the fallback.

        A busy Gemini model answers 503, and on the free tier its overloaded
        replicas also answer `400 invalid argument` for a request that another
        replica accepts unchanged. Quotas are per model, so the fallback model
        (GEMINI_FALLBACK_MODEL, a comma-separated list) are real further chances
        at no second provider.
        Only a credential or billing failure skips it: another model cannot fix
        a bad key, and it bills to the same depleted account.
        """
        return await self._structured(prompt, schema, model_config, timeout_seconds)

    async def generate_structured_from_file(
        self, prompt: str, data: bytes, mime_type: str, schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        """One structured answer about one file the owner gave (a menu, a catalogue)."""
        return await self._structured(prompt, schema, model_config, timeout_seconds, file=(data, mime_type))

    async def generate_structured_with_images(
        self, prompt: str, images: list[Any], schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        """One structured answer about several pictures. Gemini is sent the bytes,
        not a link, so a URL-only picture is refused and the caller supplies bytes."""
        if any(getattr(image, "data", None) is None for image in images):
            raise AIProviderPermanentError("gemini needs the picture bytes, not a link")
        return await self._structured(
            prompt, schema, model_config, timeout_seconds,
            more_files=[(image.data, image.mime_type) for image in images],
        )

    async def _structured(
        self, prompt: str, schema: dict[str, Any], model_config: dict[str, Any], timeout_seconds: int,
        file: tuple[bytes, str] | None = None, more_files: list[tuple[bytes, str]] | None = None,
    ) -> dict[str, Any]:
        purpose = model_config.get("purpose")
        guard_external_ai("text", self.provider_name, str(purpose or ""))
        primary = str(model_config.get("model") or self.model_for(purpose))
        fallbacks = (os.getenv("GEMINI_FALLBACK_MODEL") or GEMINI_FALLBACK_MODEL).split(",")
        models = [primary] + [m.strip() for m in fallbacks if m.strip() and m.strip() != primary]
        body = self.build_body(prompt, schema, model_config, file, more_files)
        started = time.monotonic()
        failure: Exception | None = None
        for attempt, model in enumerate(models):
            remaining = timeout_seconds - (time.monotonic() - started)
            if attempt and remaining < 3:
                break
            try:
                data = await self._post(model, body, purpose, max(remaining, 1.0))
            except _GeminiRejected as exc:
                failure = exc.error
                if exc.status in (401, 402, 403):
                    break
                continue
            parsed = self._parse(data, model, purpose, started)
            clipped = _fit(parsed, _inline_schema(schema))
            return clipped if isinstance(clipped, dict) else parsed
        assert failure is not None
        raise failure

    async def _post(
        self, model: str, body: dict[str, Any], purpose: Any, timeout: float
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{_GEMINI_BASE}/models/{model}:generateContent",
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                    json=body,
                )
        except Exception as exc:  # noqa: BLE001
            _log.warning("ai.gemini.call_failed", model=model, purpose=purpose, error=type(exc).__name__)
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            # Google's own message ("high demand", "quota exceeded") carries no
            # key and no owner text, and without it a 400 is undiagnosable.
            try:
                reason = str((response.json().get("error") or {}).get("message", ""))[:200]
            except ValueError:
                reason = response.text[:200]
            if response.status_code == 402:
                # Not a code or model problem: the Google project is out of credit.
                _log.error(
                    "ai.gemini.billing_refused", model=model, purpose=purpose,
                    status_code=402, latency_ms=latency_ms, reason=reason,
                )
                raise _GeminiRejected(
                    402, AIProviderBillingError(f"gemini billing refused the request (402): {reason}")
                )
            _log.warning(
                "ai.gemini.call_failed", model=model, purpose=purpose,
                status_code=response.status_code, latency_ms=latency_ms, reason=reason,
            )
            error: Exception = (
                AIProviderPermanentError(f"gemini rejected the request ({response.status_code}): {reason}")
                if response.status_code in (400, 401, 403, 404, 429)
                else RuntimeError(f"gemini unavailable ({response.status_code}): {reason}")
            )
            raise _GeminiRejected(response.status_code, error)
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _parse(
        self, data: dict[str, Any], model: str, purpose: Any, started: float
    ) -> dict[str, Any]:
        latency_ms = int((time.monotonic() - started) * 1000)
        self._model_used = model
        raw_usage = data.get("usageMetadata")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        self.last_usage = {
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
            "thinking_tokens": usage.get("thoughtsTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
            "latency_ms": latency_ms,
            "model": model,
        }
        # Keys avoid the word "token": the log redactor masks anything named
        # like a credential, and usage is the one thing these lines are for.
        _log.info(
            "ai.gemini.completed", model=model, purpose=purpose, latency_ms=latency_ms,
            prompt_units=usage.get("promptTokenCount"),
            output_units=usage.get("candidatesTokenCount"),
            thinking_units=usage.get("thoughtsTokenCount"),
        )
        text = self.extract_text(data)
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.index("{"):] if "{" in text else text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini returned non-JSON output") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Gemini returned a non-object JSON value")
        return parsed

    @staticmethod
    def extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = data.get("promptFeedback") or {}
            raise RuntimeError(f"Gemini returned no candidates ({feedback.get('blockReason', 'unknown')})")
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        parts = ((first.get("content") or {}).get("parts")) or []
        # Thought summaries are not the answer and must never be parsed as one.
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and not part.get("thought")
        ).strip()
        if not text:
            raise RuntimeError(f"Gemini returned empty content ({first.get('finishReason', 'unknown')})")
        return text


# ---------------------------------------------------------------- DeepSeek

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
# The model LOCAH was asked to use. Pin another with DEEPSEEK_MODEL; the id is
# sent exactly as configured and never silently swapped for a different model.
DEEPSEEK_DEFAULT_MODEL = "DeepSeek-V4.1-Flash"

# Routine extraction and picture judging answer while someone waits, so they skip
# the reasoning pass (DeepSeek's `thinking` switch). Website strategy and copy
# keep the model's default deliberation, as Gemini's "medium" level did.
_DEEPSEEK_NO_THINKING = frozenset({
    "business.interview", "document.extract", "image.query", "image.judge",
})

_IMAGE_MIME_PREFIX = "image/"


@dataclass(frozen=True)
class ImageInput:
    """One picture handed to a vision-capable model: a public https URL, or the
    bytes themselves (sent inline as a data URL, held in memory only)."""

    url: str | None = None
    data: bytes | None = None
    mime_type: str = "image/jpeg"

    def as_url(self) -> str:
        if self.url:
            return self.url
        import base64

        return f"data:{self.mime_type};base64,{base64.b64encode(self.data or b'').decode()}"


class DeepSeekProvider:
    """DeepSeek `/chat/completions` (OpenAI-compatible) with JSON-object output.

    DeepSeek has no server-side schema enforcement: the schema travels in the
    system message and the answer is held to it afterwards by `_fit`, exactly as
    Gemini's is, and every caller still re-validates with its own Pydantic model.
    Pictures go in as `image_url` content parts. A rejected key, an unknown model
    or an over-quota account is permanent for the request; only 5xx and timeouts
    are worth another attempt, and the caller owns that policy.
    """

    provider_name = "deepseek"

    def __init__(self, api_key: str, model: str = DEEPSEEK_DEFAULT_MODEL,
                 base_url: str = DEEPSEEK_DEFAULT_BASE_URL) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self.last_usage: dict[str, Any] | None = None

    @property
    def model_name(self) -> str:
        return self._model

    def model_for(self, purpose: str | None) -> str:
        key = str(purpose or "")
        if key == "business.interview":
            return os.getenv("DEEPSEEK_INTERVIEW_MODEL", "").strip() or self._model
        if key.startswith("website."):
            return os.getenv("DEEPSEEK_WEBSITE_MODEL", "").strip() or self._model
        if key.startswith("document."):
            return os.getenv("DEEPSEEK_DOCUMENT_MODEL", "").strip() or self._model
        if key.startswith("image."):
            return os.getenv("DEEPSEEK_VISION_MODEL", "").strip() or self._model
        return self._model

    def build_body(
        self, prompt: str, schema: dict[str, Any], model_config: dict[str, Any],
        images: list[ImageInput] | None = None,
    ) -> dict[str, Any]:
        purpose = str(model_config.get("purpose") or "")
        schema_text = json.dumps(_inline_schema(schema), separators=(",", ":"), ensure_ascii=False)
        system = str(model_config.get("system_prompt") or "").strip()
        instruction = (
            "Reply with exactly one JSON object and nothing else. It must conform to this JSON Schema "
            "(descriptions state each field's limits):\n" + schema_text
        )
        content: Any = prompt
        if images:
            content = [{"type": "image_url", "image_url": {"url": image.as_url()}} for image in images]
            content.append({"type": "text", "text": prompt})
        body: dict[str, Any] = {
            "model": str(model_config.get("model") or self.model_for(purpose)),
            "messages": [
                {"role": "system", "content": (system + "\n\n" if system else "") + instruction},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": int(model_config.get("max_output_tokens", 8192)),
            "stream": False,
        }
        if "temperature" in model_config:
            body["temperature"] = float(model_config["temperature"])
        if purpose in _DEEPSEEK_NO_THINKING:
            body["thinking"] = {"type": "disabled"}
        return body

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any], model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        return await self._structured(prompt, schema, model_config, timeout_seconds)

    async def generate_structured_from_file(
        self, prompt: str, data: bytes, mime_type: str, schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        """One structured answer about one picture the owner gave (a menu photo).

        DeepSeek reads pictures, not PDFs: a PDF is refused clearly so the caller
        takes its existing path for an unreadable document.
        """
        if not str(mime_type).lower().startswith(_IMAGE_MIME_PREFIX):
            raise AIProviderPermanentError(
                f"deepseek reads pictures, not {mime_type or 'this file type'}; send a photo of the page"
            )
        return await self._structured(
            prompt, schema, model_config, timeout_seconds,
            images=[ImageInput(data=data, mime_type=str(mime_type).lower())],
        )

    async def generate_structured_with_images(
        self, prompt: str, images: list[ImageInput], schema: dict[str, Any],
        model_config: dict[str, Any], timeout_seconds: int,
    ) -> dict[str, Any]:
        """One structured answer about several pictures at once (the picture judge)."""
        return await self._structured(prompt, schema, model_config, timeout_seconds, images=images)

    async def _structured(
        self, prompt: str, schema: dict[str, Any], model_config: dict[str, Any], timeout_seconds: int,
        images: list[ImageInput] | None = None,
    ) -> dict[str, Any]:
        purpose = model_config.get("purpose")
        guard_external_ai("text", self.provider_name, str(purpose or ""))
        body = self.build_body(prompt, schema, model_config, images)
        started = time.monotonic()
        data = await self._post(body, purpose, float(timeout_seconds))
        parsed = self._parse(data, str(body["model"]), purpose, started)
        clipped = _fit(parsed, _inline_schema(schema))
        return clipped if isinstance(clipped, dict) else parsed

    async def _post(self, body: dict[str, Any], purpose: Any, timeout: float) -> dict[str, Any]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except Exception as exc:  # noqa: BLE001
            _log.warning("ai.deepseek.call_failed", model=body.get("model"), purpose=purpose,
                         error=type(exc).__name__)
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            try:
                reason = str((response.json().get("error") or {}).get("message", ""))[:200]
            except ValueError:
                reason = response.text[:200]
            _log.warning("ai.deepseek.call_failed", model=body.get("model"), purpose=purpose,
                         status_code=response.status_code, latency_ms=latency_ms, reason=reason)
            if response.status_code == 402:
                # Insufficient balance: every retry and every model fails the same way.
                raise AIProviderBillingError(f"deepseek billing refused the request (402): {reason}")
            if response.status_code in (400, 401, 403, 404, 422, 429):
                raise AIProviderPermanentError(
                    f"deepseek rejected the request ({response.status_code}): {reason}")
            raise RuntimeError(f"deepseek unavailable ({response.status_code}): {reason}")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _parse(self, data: dict[str, Any], model: str, purpose: Any, started: float) -> dict[str, Any]:
        latency_ms = int((time.monotonic() - started) * 1000)
        raw_usage = data.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        details = usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        self.last_usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "thinking_tokens": reasoning,
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": latency_ms,
            "model": model,
        }
        _log.info("ai.deepseek.completed", model=model, purpose=purpose, latency_ms=latency_ms,
                  prompt_units=usage.get("prompt_tokens"), output_units=usage.get("completion_tokens"),
                  thinking_units=reasoning)
        text = self.extract_text(data)
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.index("{"):] if "{" in text else text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DeepSeek returned non-JSON output") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("DeepSeek returned a non-object JSON value")
        return parsed

    @staticmethod
    def extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("DeepSeek returned no choices")
        first = choices[0]
        raw_message = first.get("message")
        message: dict[str, Any] = raw_message if isinstance(raw_message, dict) else {}
        # `reasoning_content` is the model's working, never the answer.
        text = str(message.get("content") or "").strip()
        if not text:
            raise RuntimeError(f"DeepSeek returned empty content ({first.get('finish_reason', 'unknown')})")
        return text


def configured_provider_name() -> str:
    """Which provider is configured, without revealing anything about its key."""
    return os.getenv("AI_PROVIDER", "deepseek").strip().lower() or "deepseek"


def get_ai_provider() -> AIModelProvider:
    """The one configured provider, or none at all.

    DeepSeek is the default; `AI_PROVIDER=gemini` selects Gemini. There is no
    silent second vendor: a failed request is never retried on another provider
    (Gemini falls back only to other Gemini models, GEMINI_FALLBACK_MODEL). When
    no key is configured, callers get `UnavailableAIProvider` and take their
    existing deterministic path.
    """
    choice = configured_provider_name()
    if choice == "replay":
        # Recorded answers for tests and local acceptance runs only.
        replay_file = os.getenv("LOCAH_AI_REPLAY_FILE", "").strip()
        if replay_file and os.path.exists(replay_file):
            from platform_core.website.replay_provider import ReplayProvider

            replay: AIModelProvider = ReplayProvider(replay_file)
            return replay
        return UnavailableAIProvider()
    if choice == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if api_key:
            model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_DEFAULT_MODEL).strip() or DEEPSEEK_DEFAULT_MODEL
            base_url = os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE_URL).strip() or DEEPSEEK_DEFAULT_BASE_URL
            return DeepSeekProvider(api_key, model, base_url)
        return UnavailableAIProvider()
    if choice == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
            return GeminiProvider(api_key, model)
        return UnavailableAIProvider()
    # Any other value (e.g. a leftover AI_PROVIDER=xai) means no model at all —
    # never a silent second vendor.
    _log.warning("website.ai_provider.unsupported", provider=choice)
    return UnavailableAIProvider()
