from __future__ import annotations

import argparse
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROMAJI_PERSON_NAME_RE = re.compile(r"^[A-Za-z]+(?:[ '-][A-Za-z]+){1,3}$")
ASCII_NAME_RE = re.compile(r"^[A-Za-z0-9 _.'+\-/]+$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)
PROMPT_VERSION = "2026-03-22-v1"
DEFAULT_LOCAL_CONFIG_PATH = Path.home() / ".config" / "cosplay-photo-library-stat" / "llm.env"


class LLMTranslationError(RuntimeError):
    pass


def normalized_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


@dataclass(slots=True)
class LLMClient:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 90

    def chat_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:  # pragma: no cover - network edge case handling
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMTranslationError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:  # pragma: no cover - network edge case handling
            raise LLMTranslationError(f"Request failed: {exc}") from exc

        try:
            payload = json.loads(raw_body)
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMTranslationError(f"Unexpected response payload: {raw_body[:500]}") from exc

        return parse_json_object(content)


class LLMTranslationCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._payload = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}

    def get(self, key: str) -> dict[str, object] | None:
        with self._lock:
            return self._payload.get(key)

    def put(self, key: str, value: dict[str, object]) -> None:
        with self._lock:
            self._payload[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(self._payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def parse_json_object(content: str) -> dict[str, object]:
    text = (content or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = JSON_BLOCK_RE.search(text)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}


def load_local_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key:
                values[key] = value
    return values


def build_client_from_env() -> LLMClient:
    config_file = os.environ.get("COSPLAY_TRANSLATOR_LLM_CONFIG_FILE", "").strip()
    config_path = Path(config_file).expanduser() if config_file else DEFAULT_LOCAL_CONFIG_PATH
    local_config = load_local_env_file(config_path)
    api_key = os.environ.get("COSPLAY_TRANSLATOR_LLM_API_KEY", local_config.get("COSPLAY_TRANSLATOR_LLM_API_KEY", "")).strip()
    base_url = os.environ.get("COSPLAY_TRANSLATOR_LLM_BASE_URL", local_config.get("COSPLAY_TRANSLATOR_LLM_BASE_URL", "")).strip()
    model = os.environ.get("COSPLAY_TRANSLATOR_LLM_MODEL", local_config.get("COSPLAY_TRANSLATOR_LLM_MODEL", "")).strip()
    if not api_key:
        raise LLMTranslationError("Missing COSPLAY_TRANSLATOR_LLM_API_KEY")
    if not base_url:
        raise LLMTranslationError("Missing COSPLAY_TRANSLATOR_LLM_BASE_URL")
    if not model:
        raise LLMTranslationError("Missing COSPLAY_TRANSLATOR_LLM_MODEL")
    return LLMClient(base_url=base_url, api_key=api_key, model=model)


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))


def is_japanese_romaji_person_name(raw_name: str) -> bool:
    raw_name = raw_name.strip()
    if not ROMAJI_PERSON_NAME_RE.fullmatch(raw_name):
        return False
    phrase = normalized_phrase(raw_name)
    tokens = phrase.split()
    if len(tokens) < 2:
        return False
    if any(len(token) <= 1 for token in tokens):
        return False
    if any(token.isdigit() for token in tokens):
        return False
    return True


def _cache_key(task: str, raw_name: str, client: LLMClient) -> str:
    return "||".join((PROMPT_VERSION, task, client.base_url.rstrip("/"), client.model, normalized_phrase(raw_name)))


def _normalize_translation(value: object) -> str:
    text = str(value or "").strip()
    text = text.strip("`\"' ")
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _cached_or_infer(
    *,
    task: str,
    raw_name: str,
    client: LLMClient,
    cache: LLMTranslationCache | None,
    system_prompt: str,
    user_prompt: str,
    min_confidence: float,
    require_cjk: bool,
) -> str:
    cache_key = _cache_key(task, raw_name, client)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            translation = _normalize_translation(cached.get("translation"))
            confidence = _normalize_confidence(cached.get("confidence"))
            if translation and confidence >= min_confidence and (not require_cjk or has_cjk(translation)):
                return translation
            return ""

    payload = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
    translation = _normalize_translation(payload.get("translation"))
    confidence = _normalize_confidence(payload.get("confidence"))
    if cache is not None:
        cache.put(
            cache_key,
            {
                "raw_name": raw_name,
                "translation": translation,
                "confidence": confidence,
                "reason": _normalize_translation(payload.get("reason")),
            },
        )
    if not translation or confidence < min_confidence:
        return ""
    if require_cjk and not has_cjk(translation):
        return ""
    return translation


def infer_coser_name_with_llm(
    raw_name: str,
    *,
    client: LLMClient,
    cache: LLMTranslationCache | None = None,
    min_confidence: float = 0.78,
) -> str:
    raw_name = raw_name.strip()
    if not raw_name or has_cjk(raw_name):
        return ""
    if not is_japanese_romaji_person_name(raw_name):
        return ""
    system_prompt = (
        "You help maintain zh-CN translations for a cosplay photo library. "
        "The input is a coser name written in romaji. "
        "If it is likely a Japanese personal name, infer the single most likely kanji form and convert it to "
        "Simplified Chinese characters. If the name looks like a handle, a non-Japanese name, or is too ambiguous, "
        "return an empty translation. Respond with JSON only: "
        '{"translation":"","confidence":0.0,"reason":""}.'
    )
    user_prompt = (
        "Task: convert Japanese romaji personal names to their most likely simplified-Chinese kanji form.\n"
        "Rules:\n"
        "- Only answer with one likely person name.\n"
        "- Prefer empty translation over guessing.\n"
        "- Do not include explanations outside JSON.\n"
        f"Input: {raw_name}"
    )
    return _cached_or_infer(
        task="coser_name",
        raw_name=raw_name,
        client=client,
        cache=cache,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        min_confidence=min_confidence,
        require_cjk=True,
    )


def infer_character_name_with_llm(
    raw_name: str,
    *,
    client: LLMClient,
    cache: LLMTranslationCache | None = None,
    min_confidence: float = 0.72,
) -> str:
    raw_name = raw_name.strip()
    if not raw_name or has_cjk(raw_name):
        return ""
    if not ASCII_NAME_RE.fullmatch(raw_name):
        return ""
    system_prompt = (
        "You help maintain zh-CN translations for a cosplay photo library. "
        "Infer which cosplay character an English or romanized tag most likely refers to. "
        "Return exactly one Chinese character name or the most common Chinese translation used in Chinese fandom. "
        "If uncertain, return an empty translation. Respond with JSON only: "
        '{"translation":"","confidence":0.0,"reason":""}.'
    )
    user_prompt = (
        "Question: In cosplay context, the tag below most likely refers to which character?\n"
        "Requirements:\n"
        "- Answer with one character name in Chinese only.\n"
        "- Use the common Chinese translation used by fans when possible.\n"
        "- If the tag is too ambiguous, return an empty translation.\n"
        f"Tag: {raw_name}"
    )
    return _cached_or_infer(
        task="character_name",
        raw_name=raw_name,
        client=client,
        cache=cache,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        min_confidence=min_confidence,
        require_cjk=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the configured OpenAI-compatible model for difficult cosplay translation cases.")
    parser.add_argument("mode", choices=("coser-name", "character"))
    parser.add_argument("text", help="Raw name or tag to translate.")
    parser.add_argument(
        "--cache",
        default="data/i18n/llm_cache/manual_lookup.json",
        help="Local cache path for model responses.",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON object instead of only the translation text.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = build_client_from_env()
    cache = LLMTranslationCache(Path(args.cache))
    if args.mode == "coser-name":
        translation = infer_coser_name_with_llm(args.text, client=client, cache=cache)
    else:
        translation = infer_character_name_with_llm(args.text, client=client, cache=cache)
    if args.json:
        print(json.dumps({"translation": translation}, ensure_ascii=False))
        return
    print(translation)


if __name__ == "__main__":
    main()
