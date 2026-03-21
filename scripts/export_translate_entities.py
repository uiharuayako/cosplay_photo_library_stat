from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ddgs import DDGS

from app.dashboard import build_dashboard_payload
from app.db import SessionLocal
from app.i18n import load_entity_translations, save_entity_translations


VALID_ENTITIES = ("cosers", "characters")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36"
HTTP_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.2
TAG_PATTERN = re.compile(r"<.*?>", re.S)
CJK_NAME_PATTERN = re.compile(r"[\u3400-\u9fff][\u3400-\u9fff·・]{1,15}")
CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u9fff]")
KANA_PATTERN = re.compile(r"[\u3040-\u30ff]")
HANGUL_PATTERN = re.compile(r"[\uac00-\ud7af]")
ASCII_WORD_PATTERN = re.compile(r"^[A-Za-z0-9 _.'+\-/]+$")
GENERIC_CJK_STOPWORDS = {
    "写真",
    "合集",
    "图包",
    "套图",
    "微博",
    "更新",
    "下载",
    "完整版",
    "全套",
    "目录",
    "在线",
    "官方",
    "频道",
    "作品",
    "角色",
    "系列",
    "原神",
    "明日方舟",
    "碧蓝航线",
    "舰队收藏",
    "舰队Collection",
    "最终幻想",
    "中文",
    "简体",
    "繁体",
    "百科",
    "维基",
}
COSER_CJK_STOPWORDS = GENERIC_CJK_STOPWORDS | {
    "小姐姐",
    "福利视频",
    "演员",
    "高清",
    "频道",
    "更新中",
    "作品集",
    "合集下载",
}
COSER_CONTEXT_KEYWORDS = (
    "coser",
    "cosplay",
    "写真",
    "图包",
    "套图",
    "album",
    "gallery",
    "instagram",
    "微博",
    "patreon",
    "fansly",
    "onlyfans",
)
CHARACTER_GLOSSARY = {
    "2b": "2B",
    "a2": "A2",
    "ahri": "阿狸",
    "atago": "爱宕",
    "bb": "BB",
    "bikini": "比基尼",
    "bunny": "兔女郎",
    "casual": "私服",
    "christmas": "圣诞",
    "chinese dress": "旗袍",
    "d.va": "D.Va",
    "dancer": "舞娘",
    "dress": "礼服",
    "dva": "D.Va",
    "elf": "精灵",
    "gothloli": "哥特萝莉",
    "jk": "JK",
    "kimono": "和服",
    "kunoichi": "女忍者",
    "latex": "乳胶",
    "lingerie": "内衣",
    "maid": "女仆",
    "marie rose": "玛丽·萝丝",
    "miko": "巫女",
    "neko": "猫娘",
    "nun": "修女",
    "nurse": "护士",
    "ol": "OL",
    "qipao": "旗袍",
    "rem": "雷姆",
    "shimakaze": "岛风",
    "succubus": "魅魔",
    "swimsuit": "泳装",
    "takao": "高雄",
    "vampire": "吸血鬼",
    "zero two": "02",
}
COMPOSITE_CHARACTER_PARTS = dict(sorted(CHARACTER_GLOSSARY.items(), key=lambda item: len(item[0]), reverse=True))
REQUEST_CACHE_LOCK = Lock()
RESEARCH_CACHE_LOCK = Lock()
DDGS_CACHE_LOCK = Lock()
DDGS_CACHE: dict[str, list[dict[str, str]]] = {}
CACHE_VERSION = "2026-03-22-ddgs-v4"


@dataclass(slots=True)
class ResearchResult:
    translation: str
    status: str
    confidence: float
    source: str
    evidence: str


class RequestCache:
    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        with REQUEST_CACHE_LOCK:
            return self.payloads.get(key)

    def put(self, key: str, value: str) -> None:
        with REQUEST_CACHE_LOCK:
            self.payloads[key] = value


REQUEST_CACHE = RequestCache()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export entity CSV files and fill translations with search/knowledge-base lookups without touching scan cache schema.",
    )
    parser.add_argument("--locale", default="zh-CN", help="Target locale, for example zh-CN or ja.")
    parser.add_argument(
        "--entity",
        choices=("cosers", "characters", "both"),
        default="both",
        help="Which entity type to process.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/i18n/exports",
        help="Directory for exported and translated CSV files.",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/i18n/research_cache",
        help="Directory for cached lookup results.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Parallel lookup workers.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of ranked rows to process for each entity.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Optional starting offset within the ranked list.",
    )
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help="Keep non-empty existing translations instead of recomputing them.",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Only write CSV files and do not update the JSON translation store.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.82,
        help="Minimum confidence for importing non-empty translations into the JSON store.",
    )
    return parser.parse_args()


def _strip_html(value: str) -> str:
    return html.unescape(TAG_PATTERN.sub("", value or "")).strip()


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def http_get(url: str, params: dict[str, object] | None = None) -> str:
    query = f"{url}?{urlencode(params, doseq=True)}" if params else url
    cached = REQUEST_CACHE.get(query)
    if cached is not None:
        return cached

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            request = Request(query, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
            REQUEST_CACHE.put(query, body)
            return body
        except (HTTPError, URLError, TimeoutError) as exc:  # pragma: no cover - network edge case handling
            last_error = exc
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
    raise RuntimeError(f"request failed for {query}: {last_error}")


def is_cjk(value: str) -> bool:
    return bool(CJK_CHAR_PATTERN.search(value or ""))


def contains_kana_or_hangul(value: str) -> bool:
    return bool(KANA_PATTERN.search(value or "") or HANGUL_PATTERN.search(value or ""))


def normalize_key(value: str) -> str:
    lowered = (value or "").casefold()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def normalized_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def text_variants(value: str) -> list[str]:
    variants = [value.strip()]
    variants.append(re.sub(r"[_-]+", " ", value).strip())
    variants.append(re.sub(r"\s+", " ", value).strip())
    unique: list[str] = []
    seen: set[str] = set()
    for item in variants:
        if not item:
            continue
        marker = normalized_phrase(item)
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def normalize_zh_label(value: str) -> str:
    cleaned = re.sub(r"\s*[（(].*?[）)]\s*$", "", (value or "")).strip()
    if "/" in cleaned or "／" in cleaned:
        parts = [part.strip() for part in re.split(r"[／/]", cleaned) if part.strip()]
        if parts and all(is_cjk(part) for part in parts):
            cleaned = parts[-1]
    return cleaned


def export_rows(entity: str, locale: str, offset: int, limit: int | None) -> list[dict]:
    with SessionLocal() as session:
        payload = build_dashboard_payload(locale, "images", session)
    translations = load_entity_translations(entity, locale)
    rows = [
        {
            "key": row["key"],
            "raw_name": row["raw_name"],
            "translation": translations.get(row["key"], ""),
            "set_count": row["set_count"],
            "image_count": row["image_count"],
            "total_size": row["total_size"],
        }
        for row in payload[entity]
    ]
    sliced = rows[offset:]
    if limit is not None:
        sliced = sliced[:limit]
    return sliced


def search_wikidata(raw_name: str) -> list[dict]:
    results: list[dict] = []
    for variant in text_variants(raw_name):
        try:
            payload = json.loads(
                http_get(
                    "https://www.wikidata.org/w/api.php",
                    {
                        "action": "wbsearchentities",
                        "search": variant,
                        "language": "en",
                        "uselang": "zh-cn",
                        "format": "json",
                        "limit": 5,
                    },
                )
            )
        except Exception:
            continue
        results.extend(payload.get("search", []))
    deduped: list[dict] = []
    seen_ids: set[str] = set()
    for item in results:
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            deduped.append(item)
    return deduped


def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    cache_key = f"{query}::{max_results}"
    with DDGS_CACHE_LOCK:
        cached = DDGS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            rows.append(
                {
                    "title": (item.get("title") or "").strip(),
                    "snippet": (item.get("body") or "").strip(),
                    "href": (item.get("href") or "").strip(),
                }
            )
    with DDGS_CACHE_LOCK:
        DDGS_CACHE[cache_key] = rows
    return rows


def dedupe_preserve_order(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        marker = value.strip()
        if marker and marker not in seen:
            seen.add(marker)
            unique.append(marker)
    return unique


def row_mentions_raw_name(raw_name: str, row: dict[str, str]) -> bool:
    normalized = normalize_key(raw_name)
    if not normalized:
        return False
    joined = " ".join(part for part in (row.get("title", ""), row.get("snippet", ""), row.get("href", "")) if part)
    return normalized in normalize_key(joined)


def row_has_coser_context(row: dict[str, str]) -> bool:
    joined = " ".join(part for part in (row.get("title", ""), row.get("snippet", ""), row.get("href", "")) if part).casefold()
    return any(keyword in joined for keyword in COSER_CONTEXT_KEYWORDS)


def extract_cjk_candidates(text: str, stopwords: set[str]) -> list[str]:
    candidates: list[str] = []
    for match in CJK_NAME_PATTERN.findall(text or ""):
        candidate = normalize_zh_label(match.strip(" ·・"))
        if len(candidate) < 2:
            continue
        if candidate in stopwords:
            continue
        if any(stopword in candidate for stopword in stopwords if len(stopword) >= 2):
            continue
        candidates.append(candidate)
    return dedupe_preserve_order(candidates)


def clean_coser_alias(candidate: str) -> str:
    cleaned = re.sub(r"^(?:coser|cosplayer)\s*[@:：-]?\s*", "", (candidate or "").strip(), flags=re.I)
    cleaned = cleaned.strip(" -|:：,.;/[]{}")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


def extract_coser_alias_candidates(raw_name: str, text: str) -> list[str]:
    raw_boundary = rf"(?<![A-Za-z0-9]){re.escape(raw_name)}(?![A-Za-z0-9])"
    patterns = [
        rf"(?:coser@|@)?(?P<alias>[^|()\n]{{1,40}}[\u3400-\u9fff][^|()\n]{{0,40}})\s*[\(（]\s*{raw_boundary}\s*[\)）]",
        rf"{raw_boundary}\s*[\(（]\s*(?P<alias>[^|()\n]{{1,40}}[\u3400-\u9fff][^|()\n]{{0,40}})\s*[\)）]",
        rf"(?P<alias>[^|@\n]{{1,40}}[\u3400-\u9fff][^|@\n]{{0,20}})\s*@\s*{raw_boundary}",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", flags=re.I):
            candidate = clean_coser_alias(match.group("alias"))
            if not candidate or not is_cjk(candidate):
                continue
            if contains_kana_or_hangul(candidate):
                continue
            if candidate in COSER_CJK_STOPWORDS:
                continue
            candidates.append(candidate)
    return dedupe_preserve_order(candidates)


def pick_best_coser_candidate(raw_name: str, search_results: list[tuple[str, list[dict[str, str]]]]) -> ResearchResult | None:
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    support_rows: dict[str, set[str]] = {}
    support_queries: dict[str, set[str]] = {}
    for query, rows in search_results:
        for index, row in enumerate(rows):
            if not row_mentions_raw_name(raw_name, row):
                continue
            if not row_has_coser_context(row):
                continue
            joined_text = " | ".join(part for part in (row["title"], row["snippet"]) if part)
            if contains_kana_or_hangul(joined_text):
                continue
            title_candidates = extract_coser_alias_candidates(raw_name, row["title"])
            snippet_candidates = extract_coser_alias_candidates(raw_name, row["snippet"])
            row_key = f"{query}::{index}"
            for candidate in title_candidates:
                scores[candidate] = scores.get(candidate, 0.0) + 3.0 - (index * 0.15)
                evidence.setdefault(candidate, []).append(f"{query} | title | {row['title']}")
                support_rows.setdefault(candidate, set()).add(row_key)
                support_queries.setdefault(candidate, set()).add(query)
            for candidate in snippet_candidates:
                scores[candidate] = scores.get(candidate, 0.0) + 1.5 - (index * 0.1)
                evidence.setdefault(candidate, []).append(f"{query} | snippet | {row['snippet']}")
                support_rows.setdefault(candidate, set()).add(row_key)
                support_queries.setdefault(candidate, set()).add(query)
    if not scores:
        return None
    ranking = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_candidate, best_score = ranking[0]
    second_score = ranking[1][1] if len(ranking) > 1 else 0.0
    best_row_support = len(support_rows.get(best_candidate, set()))
    best_query_support = len(support_queries.get(best_candidate, set()))
    if best_score < 4.8:
        return None
    if best_row_support < 2 and best_score < 6.0:
        return None
    if best_query_support < 2 and best_score < 6.4:
        return None
    if second_score and (best_score - second_score) < 1.8:
        return None
    confidence = min(0.98, 0.64 + (best_score / 12.0) + (best_query_support * 0.03))
    return ResearchResult(
        translation=best_candidate,
        status="translated",
        confidence=confidence,
        source="ddgs_search",
        evidence=" || ".join(evidence.get(best_candidate, [])[:3]),
    )


def translate_coser(raw_name: str) -> ResearchResult:
    raw_name = raw_name.strip()
    if not raw_name:
        return ResearchResult("", "unresolved", 0.0, "none", "empty raw name")
    if is_cjk(raw_name) or contains_kana_or_hangul(raw_name):
        return ResearchResult(raw_name, "keep_original", 1.0, "original_script", "already non-latin")
    if not ASCII_WORD_PATTERN.fullmatch(raw_name):
        return ResearchResult(raw_name, "keep_original", 0.98, "original_script", "non-standard script or punctuation")

    queries = [
        f'"{raw_name}" coser',
        f'"{raw_name}" 写真',
        f'"{raw_name}" 微博',
    ]
    search_results: list[tuple[str, list[dict[str, str]]]] = []
    for query in queries:
        try:
            search_results.append((query, search_web(query)))
        except Exception as exc:  # pragma: no cover - network edge case handling
            search_results.append((query, [{"title": "", "snippet": f"lookup failed: {exc}", "href": ""}]))
    picked = pick_best_coser_candidate(raw_name, search_results)
    if picked is not None:
        return picked
    return ResearchResult(raw_name, "keep_original", 0.9, "policy", "no strong Chinese alias found; kept original")


def glossary_lookup(raw_name: str) -> ResearchResult | None:
    key = normalized_phrase(raw_name)
    translation = CHARACTER_GLOSSARY.get(key)
    if not translation:
        return None
    return ResearchResult(translation, "translated", 0.99, "glossary", f"matched glossary term {key}")


def score_wikidata_item(raw_name: str, item: dict) -> tuple[float, str] | None:
    translation = normalize_zh_label(item.get("label") or item.get("display", {}).get("label", {}).get("value") or "")
    description = (item.get("description") or item.get("display", {}).get("description", {}).get("value") or "").strip()
    if not translation or not is_cjk(translation):
        return None
    if any(blocked in translation for blocked in ("列表", "作品", "系列")):
        return None
    match = item.get("match", {})
    score = 0.0
    explanation: list[str] = []
    is_character = any(term in description.casefold() for term in ("fictional character", "character", "登场人物", "角色"))
    if not is_character:
        return None
    if normalize_key(match.get("text", "")) == normalize_key(raw_name):
        score += 4.5
        explanation.append("exact alias/label match")
    aliases = item.get("aliases", []) or []
    if any(normalize_key(alias) == normalize_key(raw_name) for alias in aliases):
        score += 2.0
        explanation.append("alias match")
    score += 3.2
    explanation.append("character description")
    if item.get("display", {}).get("label", {}).get("language") == "zh-cn":
        score += 1.0
        explanation.append("zh-cn label")
    if len(translation) <= 12:
        score += 0.3
    if score < 5.0:
        return None
    return score, ", ".join(explanation)


def pick_wikidata_character(raw_name: str) -> ResearchResult | None:
    ranked: list[tuple[float, str, dict]] = []
    for item in search_wikidata(raw_name):
        scored = score_wikidata_item(raw_name, item)
        if scored is not None:
            ranked.append((scored[0], scored[1], item))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[2].get("label", "")))
    best_score, explanation, best_item = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if second_score and (best_score - second_score) < 0.8:
        return None
    translation = normalize_zh_label(best_item.get("label") or best_item.get("display", {}).get("label", {}).get("value") or "")
    confidence = min(0.98, 0.62 + (best_score / 12.0))
    evidence = f"{best_item.get('id', '')} | {best_item.get('description', '')} | {explanation}".strip(" |")
    return ResearchResult(translation, "translated", confidence, "wikidata", evidence)


def pick_search_character(raw_name: str) -> ResearchResult | None:
    queries = [
        f'"{raw_name}" 中文 角色',
        f'"{raw_name}" 中文',
        f'"{raw_name}" cosplay 中文',
    ]
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    support_rows: dict[str, set[str]] = {}
    support_queries: dict[str, set[str]] = {}
    for query in queries:
        rows = search_web(query)
        for index, row in enumerate(rows):
            if not row_mentions_raw_name(raw_name, row):
                continue
            title_candidates = extract_cjk_candidates(row["title"], GENERIC_CJK_STOPWORDS)
            snippet_candidates = extract_cjk_candidates(row["snippet"], GENERIC_CJK_STOPWORDS)
            row_key = f"{query}::{index}"
            for candidate in title_candidates:
                scores[candidate] = scores.get(candidate, 0.0) + 2.4 - (index * 0.15)
                evidence.setdefault(candidate, []).append(f"{query} | title | {row['title']}")
                support_rows.setdefault(candidate, set()).add(row_key)
                support_queries.setdefault(candidate, set()).add(query)
            for candidate in snippet_candidates:
                scores[candidate] = scores.get(candidate, 0.0) + 1.1 - (index * 0.1)
                evidence.setdefault(candidate, []).append(f"{query} | snippet | {row['snippet']}")
                support_rows.setdefault(candidate, set()).add(row_key)
                support_queries.setdefault(candidate, set()).add(query)
    if not scores:
        return None
    ranking = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_candidate, best_score = ranking[0]
    second_score = ranking[1][1] if len(ranking) > 1 else 0.0
    best_row_support = len(support_rows.get(best_candidate, set()))
    best_query_support = len(support_queries.get(best_candidate, set()))
    if best_score < 3.8:
        return None
    if best_row_support < 2 and best_score < 5.3:
        return None
    if best_query_support < 2 and best_score < 5.7:
        return None
    if second_score and (best_score - second_score) < 1.2:
        return None
    confidence = min(0.92, 0.55 + (best_score / 10.0) + (best_query_support * 0.02))
    return ResearchResult(
        translation=normalize_zh_label(best_candidate),
        status="translated",
        confidence=confidence,
        source="ddgs_search",
        evidence=" || ".join(evidence.get(best_candidate, [])[:3]),
    )


def try_character_composite(raw_name: str) -> ResearchResult | None:
    phrase = normalized_phrase(raw_name)
    for part, translated_part in COMPOSITE_CHARACTER_PARTS.items():
        if not phrase.endswith(part):
            continue
        base_raw = raw_name[: len(raw_name) - len(part)].strip(" _-/")
        if not base_raw:
            continue
        base_result = translate_character(base_raw, allow_composite=False)
        if not base_result.translation or base_result.status == "unresolved":
            continue
        translation = f"{base_result.translation} {translated_part}".strip()
        confidence = min(0.93, base_result.confidence - 0.03)
        return ResearchResult(
            translation,
            "translated",
            confidence,
            "composite",
            f"base={base_raw} -> {base_result.translation}; suffix={part} -> {translated_part}",
        )
    return None


def translate_character(raw_name: str, allow_composite: bool = True) -> ResearchResult:
    raw_name = raw_name.strip()
    if not raw_name:
        return ResearchResult("", "unresolved", 0.0, "none", "empty raw name")
    if is_cjk(raw_name):
        return ResearchResult(raw_name, "keep_original", 1.0, "original_script", "already Chinese")
    direct_glossary = glossary_lookup(raw_name)
    if direct_glossary is not None:
        return direct_glossary
    wikidata_result = pick_wikidata_character(raw_name)
    if wikidata_result is not None:
        return wikidata_result
    if allow_composite:
        composite_result = try_character_composite(raw_name)
        if composite_result is not None:
            return composite_result
    try:
        bing_result = pick_search_character(raw_name)
    except Exception as exc:  # pragma: no cover - network edge case handling
        bing_result = ResearchResult("", "unresolved", 0.0, "ddgs_search", f"lookup failed: {exc}")
    if bing_result is not None and bing_result.translation:
        return bing_result
    return ResearchResult("", "unresolved", 0.0, "none", "no confident Chinese common name found")


def load_research_cache(path: Path) -> dict[str, dict]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return {}
    return payload


def research_row(entity: str, row: dict, preserve_existing: bool, cache_payload: dict[str, dict]) -> dict:
    output = dict(row)
    existing_translation = (row.get("translation") or "").strip()
    if preserve_existing and existing_translation:
        output.update(
            {
                "translation": existing_translation,
                "status": "existing",
                "confidence": 1.0,
                "source": "existing_json",
                "evidence": "preserved existing translation",
            }
        )
        return output

    cached = cache_payload.get(row["key"])
    if cached and cached.get("raw_name") == row["raw_name"] and cached.get("cache_version") == CACHE_VERSION:
        result = ResearchResult(
            translation=cached.get("translation", ""),
            status=cached.get("status", "unresolved"),
            confidence=float(cached.get("confidence", 0.0)),
            source=cached.get("source", "cache"),
            evidence=cached.get("evidence", "cached result"),
        )
    else:
        result = translate_coser(row["raw_name"]) if entity == "cosers" else translate_character(row["raw_name"])
        with RESEARCH_CACHE_LOCK:
            cache_payload[row["key"]] = {
                "cache_version": CACHE_VERSION,
                "raw_name": row["raw_name"],
                **asdict(result),
            }

    output.update(
        {
            "translation": result.translation,
            "status": result.status,
            "confidence": f"{result.confidence:.2f}",
            "source": result.source,
            "evidence": result.evidence,
        }
    )
    return output


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def should_import(row: dict, min_confidence: float) -> bool:
    translation = (row.get("translation") or "").strip()
    if not translation:
        return False
    confidence = float(row.get("confidence") or 0.0)
    if confidence < min_confidence:
        return False
    return translation != (row.get("raw_name") or "").strip()


def build_merged_translation_map(entity: str, locale: str, translated_rows: list[dict], min_confidence: float) -> dict[str, str]:
    merged = load_entity_translations(entity, locale).copy()
    for row in translated_rows:
        key = row["key"]
        raw_name = (row.get("raw_name") or "").strip()
        existing = (merged.get(key) or "").strip()
        if should_import(row, min_confidence):
            merged[key] = (row.get("translation") or "").strip()
            continue
        if existing and existing == raw_name:
            merged.pop(key, None)
    return merged


def process_entity(args: argparse.Namespace, entity: str) -> None:
    rows = export_rows(entity, args.locale, args.offset, args.limit)
    output_dir = Path(args.output_dir)
    cache_path = Path(args.cache_dir) / f"{entity}.{args.locale}.json"
    cache_payload = load_research_cache(cache_path)

    exported_path = output_dir / f"{entity}.{args.locale}.export.csv"
    translated_path = output_dir / f"{entity}.{args.locale}.translated.csv"
    write_csv(exported_path, rows, ["key", "raw_name", "translation", "set_count", "image_count", "total_size"])

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        translated_rows = list(
            executor.map(
                lambda row: research_row(entity, row, args.preserve_existing, cache_payload),
                rows,
            )
        )

    translated_rows.sort(key=lambda row: (-int(row["image_count"]), row["raw_name"].casefold()))
    write_csv(
        translated_path,
        translated_rows,
        [
            "key",
            "raw_name",
            "translation",
            "status",
            "confidence",
            "source",
            "evidence",
            "set_count",
            "image_count",
            "total_size",
        ],
    )
    _write_json(cache_path, cache_payload)

    translated_map = build_merged_translation_map(entity, args.locale, translated_rows, args.min_confidence)
    imported_keys = {
        row["key"]
        for row in translated_rows
        if should_import(row, args.min_confidence)
    }
    if not args.skip_import:
        save_entity_translations(entity, args.locale, translated_map)

    translated_count = sum(1 for row in translated_rows if (row.get("translation") or "").strip())
    imported_count = len(imported_keys)
    unresolved_count = sum(1 for row in translated_rows if row.get("status") == "unresolved")
    kept_count = sum(1 for row in translated_rows if row.get("status") == "keep_original")

    print(f"[{entity}] exported -> {exported_path}")
    print(f"[{entity}] translated -> {translated_path}")
    print(f"[{entity}] cache -> {cache_path}")
    print(
        f"[{entity}] rows={len(translated_rows)} translated_non_empty={translated_count} kept_original={kept_count} unresolved={unresolved_count}"
    )
    if args.skip_import:
        print(f"[{entity}] import skipped")
    else:
        print(f"[{entity}] imported {imported_count} translations into JSON store")


def main() -> None:
    args = parse_args()
    entities = VALID_ENTITIES if args.entity == "both" else (args.entity,)
    for entity in entities:
        process_entity(args, entity)


if __name__ == "__main__":
    main()
