"""
Unified AI Client
-----------------
Single abstraction for all AI calls in the system (extraction + categorization),
with automatic fallback between a local llama_cpp model and the OpenAI API.

Design goals
------------
* "Use the AI model if you have to" - callers don't care which backend serves a
  request, they just want a result. This client decides.
* Local-first privacy: when a local model is installed, statement content never
  leaves the machine. OpenAI is only contacted when the local model is missing,
  errors, or is explicitly preferred.
* One place to fix/extend AI behavior (prompts, retries, cost tracking) instead
  of the two ad-hoc call sites that existed before (ai_detector.py + analyzer.py).

Backends
--------
* Local : llama_cpp loading a GGUF model. Multimodal (vision) support is opt-in
          via config ``local_supports_vision`` because it requires a vision GGUF
          + mmproj. Thread-safe via a lock (llama_cpp is not re-entrant).
* OpenAI: text + vision via gpt-4o-mini (configurable). Reads the API key from
          ``config/openai.txt`` (where it actually lives - the old analyzer code
          looked for ``openai.txt`` in the repo root and never found it).

Fallback order (preferred_backend="auto")
    text   -> local -> openai
    vision -> openai (unless local_supports_vision, then local -> openai)
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

# --- Optional backend imports (guarded so the module loads without them) ----
try:
    from llama_cpp import Llama

    LLAMA_CPP_AVAILABLE = True
except Exception:  # ImportError or llama_cpp init quirks
    LLAMA_CPP_AVAILABLE = False
    Llama = None  # type: ignore[assignment]

try:
    import openai

    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False
    openai = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config", "ai_settings.json")

# Google's Gemma 4 E2B is a real, current (April 2026) multimodal model family
# that natively supports text + images. The E2B-it Q8_0 GGUF is the natural
# default - it's the exact model the original project targeted. Users can point
# STATEMENT_ORGANIZER_AI_MODEL_PATH at any GGUF they prefer.
_DEFAULT_LOCAL_MODEL = os.getenv(
    "STATEMENT_ORGANIZER_AI_MODEL_PATH",
    os.path.join(_BASE_DIR, "models", "gemma-4-e2b-it-Q8_0.gguf"),
)
_DEFAULT_LOCAL_MODEL_URL = os.getenv(
    "STATEMENT_ORGANIZER_AI_MODEL_URL",
    "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/"
    "gemma-4-E2B-it-Q8_0.gguf",
)
# Gemma 4 (like most multimodal GGUFs) needs a separate "mmproj" projector file
# to process images. Without it the model is text-only. The F32 projector gives
# the best vision quality per the Gemma 4 llama.cpp guidance.
_DEFAULT_LOCAL_MMPROJ = os.getenv(
    "STATEMENT_ORGANIZER_AI_MMPROJ_PATH",
    os.path.join(_BASE_DIR, "models", "mmproj-F32.gguf"),
)
_DEFAULT_LOCAL_MMPROJ_URL = os.getenv(
    "STATEMENT_ORGANIZER_AI_MMPROJ_URL",
    "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/mmproj-F32.gguf",
)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "initial_setup_complete": True,
    "preferred_backend": "auto",  # "local" | "openai" | "auto"
    "local_model_path": _DEFAULT_LOCAL_MODEL,
    "local_model_url": _DEFAULT_LOCAL_MODEL_URL,
    "local_mmproj_path": _DEFAULT_LOCAL_MMPROJ,
    "local_mmproj_url": _DEFAULT_LOCAL_MMPROJ_URL,
    "local_supports_vision": False,  # set True once a vision GGUF + mmproj are installed
    "local_n_ctx": 4096,
    "openai_model": "gpt-4o-mini",
    "openai_key_file": os.path.join("config", "openai.txt"),
    "openai_key_env": "OPENAI_API_KEY",
    # Extraction: escalate deterministic->AI when doc confidence is below this (0-100)
    "extraction_confidence_threshold": 50,
    "max_tokens_extraction": 2000,
    "max_tokens_categorization": 400,
    "categorization_batch_size": 20,
}


def load_ai_settings() -> Dict[str, Any]:
    """Load AI settings merged with defaults. Never raises - returns defaults on error."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
                user = json.load(fh)
            if isinstance(user, dict):
                settings.update(user)
    except Exception as exc:  # corrupted JSON etc.
        print(f"⚠️ Could not read {_CONFIG_PATH}, using defaults: {exc}")
    return settings


def save_ai_settings(settings: Dict[str, Any]) -> None:
    """Persist AI settings to config/ai_settings.json."""
    try:
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except Exception as exc:
        print(f"⚠️ Could not write {_CONFIG_PATH}: {exc}")


def _read_openai_key(settings: Dict[str, Any]) -> Optional[str]:
    """Resolve the OpenAI API key from env or the configured key file."""
    key = os.getenv(settings.get("openai_key_env", "OPENAI_API_KEY"))
    if key:
        return key.strip()
    # Resolve relative to project base, then try absolute as-is.
    candidates = [
        os.path.join(_BASE_DIR, settings.get("openai_key_file", "config/openai.txt")),
        settings.get("openai_key_file", ""),
        os.path.join(_BASE_DIR, "openai.txt"),  # legacy location
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    val = fh.read().strip()
                    if val:
                        return val
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Response type
# ---------------------------------------------------------------------------
@dataclass
class AIResponse:
    """Normalized result of a single AI call."""

    text: str
    backend: str  # "local" | "openai" | ""
    success: bool
    error: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()


def _empty(backend: str, error: str = "") -> AIResponse:
    return AIResponse(text="", backend=backend, success=False, error=error)


# ---------------------------------------------------------------------------
# JSON helpers (shared by extraction + categorization)
# ---------------------------------------------------------------------------
def extract_json(text: str) -> Optional[Union[Dict[str, Any], List[Any]]]:
    """Extract a JSON object or array from model output. Returns None on failure."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # Try direct parse first (model obeyed instructions).
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Then try to locate the outermost object/array.
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def extract_json_list(text: str) -> List[Any]:
    """Convenience: return a JSON array from text, or [] if none found."""
    parsed = extract_json(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Single object -> wrap.
        return [parsed]
    return []


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Convenience: return a JSON object from text, or None."""
    parsed = extract_json(text)
    if isinstance(parsed, dict):
        return parsed
    return None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class _LocalBackend:
    """llama_cpp GGUF backend. Thread-safe (llama_cpp is not re-entrant)."""

    backend_name = "local"

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.model_path = settings.get("local_model_path", _DEFAULT_LOCAL_MODEL)
        self.mmproj_path = settings.get("local_mmproj_path", _DEFAULT_LOCAL_MMPROJ)
        self.n_ctx = int(settings.get("local_n_ctx", 4096))
        # Vision is supported when the user says so AND a mmproj file is present.
        self.supports_vision = bool(settings.get("local_supports_vision", False)) and bool(
            self.mmproj_path and os.path.exists(self.mmproj_path)
        )
        self._client: Any = None
        self._chat_handler: Any = None
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None

    def _ensure_loaded(self) -> bool:
        """Lazily load the model on first use.

        For multimodal (vision) models like Gemma 4, llama-cpp-python needs a
        separate mmproj projector file wired in via a chat handler; the bare
        Llama() is text-only.
        """
        if self._client is not None:
            return True
        if self._load_error is not None:
            return False
        if not LLAMA_CPP_AVAILABLE:
            self._load_error = "llama_cpp not installed"
            return False
        if not os.path.exists(self.model_path):
            self._load_error = f"model not found: {self.model_path}"
            return False
        try:
            n_gpu_layers = self._detect_gpu_layers()
            self._client = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=max(1, (os.cpu_count() or 2) - 1),
                n_gpu_layers=n_gpu_layers,
                verbose=False,
            )
            # Attach the multimodal projector if present so vision calls work.
            # Gemma 4 has a dedicated handler (Gemma4ChatHandler) in
            # llama-cpp-python >= 0.3.29; fall back to MTMDChatHandler (the
            # generic multimodal handler) on slightly older versions.
            if self.mmproj_path and os.path.exists(self.mmproj_path):
                try:
                    from llama_cpp.llama_chat_format import Gemma4ChatHandler

                    self._chat_handler = Gemma4ChatHandler(
                        clip_model_path=self.mmproj_path, verbose=False
                    )
                    self._client.chat_handler = self._chat_handler
                    print(
                        f"✅ Local AI model loaded with vision: "
                        f"{os.path.basename(self.model_path)} + {os.path.basename(self.mmproj_path)}"
                    )
                except ImportError:
                    try:
                        from llama_cpp.llama_chat_format import MTMDChatHandler

                        self._chat_handler = MTMDChatHandler(
                            clip_model_path=self.mmproj_path, verbose=False
                        )
                        self._client.chat_handler = self._chat_handler
                        print(
                            f"✅ Local AI model loaded with vision (MTMD): "
                            f"{os.path.basename(self.model_path)} + {os.path.basename(self.mmproj_path)}"
                        )
                    except Exception as exc:
                        # Model loaded fine for text; just no vision.
                        self.supports_vision = False
                        print(
                            f"✅ Local AI model loaded (text-only; vision disabled: {exc})"
                        )
                except Exception as exc:
                    # Model loaded fine for text; just no vision.
                    self.supports_vision = False
                    print(
                        f"✅ Local AI model loaded (text-only; vision disabled: {exc})"
                    )
            else:
                self.supports_vision = False
                print(f"✅ Local AI model loaded (text-only): {os.path.basename(self.model_path)}")
            return True
        except Exception as exc:
            self._load_error = str(exc)
            print(f"⚠️ Could not load local AI model: {exc}")
            return False

    @staticmethod
    def _detect_gpu_layers() -> int:
        """Auto-detect GPU acceleration (Metal on Apple Silicon). -1 = all layers."""
        try:
            import platform

            if platform.system() == "Darwin" and platform.machine() == "arm64":
                return -1  # Metal: offload everything
        except Exception:
            pass
        return 0

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    def chat_text(
        self, prompt: str, max_tokens: int = 500, temperature: float = 0.0
    ) -> AIResponse:
        if not self._ensure_loaded():
            return _empty("local", self._load_error or "unavailable")
        try:
            with self._lock:
                resp = self._client.create_chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            text = resp["choices"][0]["message"]["content"]
            return AIResponse(text=text or "", backend="local", success=True)
        except Exception as exc:
            return _empty("local", str(exc))

    def chat_vision(
        self,
        image_b64: str,
        prompt: str,
        mime: str = "image/png",
        max_tokens: int = 1000,
        temperature: float = 0.0,
    ) -> AIResponse:
        if not self.supports_vision:
            return _empty("local", "local model not vision-capable")
        if not self._ensure_loaded():
            return _empty("local", self._load_error or "unavailable")
        try:
            data_url = f"data:{mime};base64,{image_b64}"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ]
            with self._lock:
                resp = self._client.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            text = resp["choices"][0]["message"]["content"]
            return AIResponse(text=text or "", backend="local", success=True)
        except Exception as exc:
            return _empty("local", str(exc))


class _OpenAIBackend:
    """OpenAI API backend (text + vision). gpt-4o-mini by default."""

    backend_name = "openai"

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.model = settings.get("openai_model", "gpt-4o-mini")
        self._client: Any = None
        self._load_error: Optional[str] = None

    def _ensure_loaded(self) -> bool:
        if self._client is not None:
            return True
        if self._load_error is not None:
            return False
        if not OPENAI_AVAILABLE:
            self._load_error = "openai package not installed"
            return False
        key = _read_openai_key(self.settings)
        if not key:
            self._load_error = "no OpenAI API key found"
            return False
        try:
            self._client = openai.OpenAI(api_key=key)
            return True
        except Exception as exc:
            self._load_error = str(exc)
            return False

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    def chat_text(
        self, prompt: str, max_tokens: int = 500, temperature: float = 0.0
    ) -> AIResponse:
        if not self._ensure_loaded():
            return _empty("openai", self._load_error or "unavailable")
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data-extraction assistant. "
                        "Return only valid JSON, no commentary.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.choices[0].message.content or ""
            return AIResponse(text=text, backend="openai", success=True)
        except Exception as exc:
            return _empty("openai", str(exc))

    def chat_vision(
        self,
        image_b64: str,
        prompt: str,
        mime: str = "image/png",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> AIResponse:
        if not self._ensure_loaded():
            return _empty("openai", self._load_error or "unavailable")
        try:
            data_url = f"data:{mime};base64,{image_b64}"
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data-extraction assistant. "
                        "Return only valid JSON, no commentary.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.choices[0].message.content or ""
            return AIResponse(text=text, backend="openai", success=True)
        except Exception as exc:
            return _empty("openai", str(exc))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class AIClient:
    """Unified AI client with automatic local->OpenAI fallback.

    Callers use :meth:`chat_text` / :meth:`chat_vision` and inspect the returned
    :class:`AIResponse.backend` to know which backend actually answered (useful
    for surfacing privacy/cost in the GUI).
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.settings = settings or load_ai_settings()
        self.preferred = str(self.settings.get("preferred_backend", "auto")).lower()
        self._local = _LocalBackend(self.settings)
        self._openai = _OpenAIBackend(self.settings)

    # -- introspection ------------------------------------------------------
    @property
    def available(self) -> bool:
        """True if at least one backend can serve requests."""
        return self._local.available or self._openai.available

    @property
    def active_backend(self) -> str:
        """Which backend a fresh request would try first."""
        if self.preferred == "local":
            return "local" if self._local.available else "openai"
        if self.preferred == "openai":
            return "openai" if self._openai.available else "local"
        # auto: local first, then openai
        return "local" if self._local.available else "openai"

    def describe(self) -> str:
        """Human-readable status line for GUI/logs."""
        parts = []
        if self._local.available:
            v = "vision" if self._local.supports_vision else "text-only"
            parts.append(f"local ({v})")
        if self._openai.available:
            parts.append(f"openai ({self._openai.model})")
        if not parts:
            return "no AI backend available"
        return f"{self.preferred}: " + ", ".join(parts)

    # -- text ---------------------------------------------------------------
    def chat_text(
        self, prompt: str, max_tokens: int = 500, temperature: float = 0.0
    ) -> AIResponse:
        """Send a text prompt; try the preferred backend, then the other."""
        order = self._text_order()
        last = _empty("", "no backend attempted")
        for backend in order:
            resp = backend.chat_text(prompt, max_tokens=max_tokens, temperature=temperature)
            if resp.success and not resp.is_empty:
                return resp
            last = resp
        return last or _empty("", "all backends failed")

    def chat_text_json(
        self, prompt: str, max_tokens: int = 500, temperature: float = 0.0
    ) -> Optional[Union[Dict[str, Any], List[Any]]]:
        """Text call that parses JSON from the response. None on failure."""
        resp = self.chat_text(prompt, max_tokens=max_tokens, temperature=temperature)
        if not resp.success:
            return None
        return extract_json(resp.text)

    # -- vision -------------------------------------------------------------
    def chat_vision(
        self,
        image_b64: str,
        prompt: str,
        mime: str = "image/png",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> AIResponse:
        """Send an image + prompt. Local is only used if it supports vision."""
        order = self._vision_order()
        last = _empty("", "no backend attempted")
        for backend in order:
            resp = backend.chat_vision(
                image_b64, prompt, mime=mime, max_tokens=max_tokens, temperature=temperature
            )
            if resp.success and not resp.is_empty:
                return resp
            last = resp
        return last or _empty("", "all backends failed")

    def chat_vision_json(
        self,
        image_b64: str,
        prompt: str,
        mime: str = "image/png",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> Optional[Union[Dict[str, Any], List[Any]]]:
        """Vision call that parses JSON. None on failure."""
        resp = self.chat_vision(
            image_b64, prompt, mime=mime, max_tokens=max_tokens, temperature=temperature
        )
        if not resp.success:
            return None
        return extract_json(resp.text)

    # -- ordering -----------------------------------------------------------
    def _text_order(self) -> List[Union[_LocalBackend, _OpenAIBackend]]:
        if self.preferred == "openai":
            return self._ordered(self._openai, self._local)
        # local or auto: local first
        return self._ordered(self._local, self._openai)

    def _vision_order(self) -> List[Union[_LocalBackend, _OpenAIBackend]]:
        # A text-only local model cannot do vision - skip it entirely.
        local_usable = self._local.supports_vision
        if self.preferred == "local" and local_usable:
            return self._ordered(self._local, self._openai)
        if self.preferred == "openai" or not local_usable:
            return self._ordered(self._openai, self._local if local_usable else None)
        # auto with no local vision -> openai first (local unusable)
        return self._ordered(self._openai, self._local if local_usable else None)

    @staticmethod
    def _ordered(first, second) -> List[Any]:
        out = []
        if first is not None:
            out.append(first)
        if second is not None:
            out.append(second)
        return out


# ---------------------------------------------------------------------------
# Module-level singleton (models are heavy; share one instance)
# ---------------------------------------------------------------------------
_client: Optional[AIClient] = None
_client_lock = threading.Lock()


def get_ai_client() -> AIClient:
    """Get or create the shared AIClient instance (thread-safe)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = AIClient()
    return _client


def reset_ai_client() -> None:
    """Drop the cached client (used after config changes)."""
    global _client
    with _client_lock:
        _client = None
