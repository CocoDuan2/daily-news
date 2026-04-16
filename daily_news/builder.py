from __future__ import annotations

import json
import os
import re
import ssl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi
import feedparser
from jinja2 import Environment, FileSystemLoader, select_autoescape


OFFICIAL_SOURCES = {
    "OpenAI",
    "Anthropic",
    "Google DeepMind",
    "Google AI Blog",
    "Meta AI",
    "Hugging Face",
    "NVIDIA Blog AI",
}


def load_config(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return _simple_yaml_load(text)


def _simple_yaml_load(text: str) -> dict[str, Any]:
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    root: dict[str, Any] = {}
    current_section: str | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in lines:
        if raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and line.endswith(":"):
            current_section = line[:-1]
            if current_section == "sources":
                root[current_section] = []
            else:
                root[current_section] = {}
            current_item = None
            continue
        if current_section == "sources":
            if line.startswith("- "):
                key, value = line[2:].split(":", 1)
                current_item = {key.strip(): _parse_scalar(value.strip())}
                root[current_section].append(current_item)
            else:
                key, value = line.split(":", 1)
                if current_item is None:
                    raise ValueError("Invalid sources block")
                current_item[key.strip()] = _parse_scalar(value.strip())
        else:
            key, value = line.split(":", 1)
            root[current_section][key.strip()] = _parse_scalar(value.strip())
    return root


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if value.isdigit():
        return int(value)
    return value


def fetch_entries(sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for source in sources:
        source_type = source.get("type", "rss")
        try:
            if source_type == "rss":
                entries.extend(fetch_rss_entries(source))
            elif source_type == "tavily":
                entries.extend(fetch_tavily_entries(source))
        except Exception as exc:
            print(f"[warn] skipping source {source.get('name', 'unknown')}: {exc}")
    return entries


def fetch_rss_entries(source: dict[str, str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    feed = feedparser.parse(source["url"])
    if should_retry_feed_with_download(feed):
        feed = feedparser.parse(download_feed_content(source["url"]))
    for item in getattr(feed, "entries", []):
        published = parse_entry_datetime(item)
        if published is None:
            continue
        entries.append(
            {
                "source": source["name"],
                "title": clean_text(item.get("title", "Untitled")),
                "link": item.get("link", source["url"]),
                "published": published,
                "summary": summarize_entry(item),
            }
        )
    return entries


def should_retry_feed_with_download(feed: Any) -> bool:
    exception = getattr(feed, "bozo_exception", None)
    if exception is None:
        return False
    if isinstance(exception, ssl.SSLCertVerificationError):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in repr(exception)


def download_feed_content(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0; +https://github.com/CocoDuan2/daily-news)",
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=20, context=ssl_context) as response:
        return response.read()


def fetch_tavily_entries(source: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []

    request_body = {
        "query": source.get("query", "AI news"),
        "topic": source.get("topic", "news"),
        "max_results": int(source.get("max_results", 10)),
        "search_depth": source.get("search_depth", "advanced"),
        "include_answer": False,
        "include_raw_content": False,
    }
    request = Request(
        "https://api.tavily.com/search",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    entries: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        published = parse_tavily_datetime(item.get("published_date"))
        if published is None:
            continue
        entries.append(
            {
                "source": source["name"],
                "title": clean_text(item.get("title", "Untitled")),
                "link": item.get("url", ""),
                "published": published,
                "summary": clean_text(item.get("content", "") or item.get("title", "")),
            }
        )
    return entries


def parse_entry_datetime(item: dict[str, Any]) -> datetime | None:
    for key in ("published", "updated", "created"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
    for key in ("published_parsed", "updated_parsed"):
        raw = item.get(key)
        if raw:
            return datetime(*raw[:6], tzinfo=timezone.utc)
    return None


def parse_tavily_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clean_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()
    return collapsed


def summarize_entry(item: dict[str, Any], max_length: int = 220) -> str:
    summary = clean_text(item.get("summary", "") or item.get("description", ""))
    if not summary:
        summary = clean_text(item.get("title", ""))
    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 1].rstrip() + "…"


def dedupe_and_filter_entries(
    entries: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    lookback_hours: int = 24,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    seen_keys: set[str] = set()
    seen_titles: set[str] = set()
    filtered: list[dict[str, Any]] = []

    for entry in sorted(entries, key=lambda item: item["published"], reverse=True):
        if entry["published"] < cutoff:
            continue
        key = canonical_key(entry)
        normalized_title = re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")
        if key in seen_keys or normalized_title in seen_titles:
            continue
        seen_keys.add(key)
        seen_titles.add(normalized_title)
        filtered.append(entry)
        if max_items and len(filtered) >= max_items:
            break
    return filtered


def canonical_key(entry: dict[str, Any]) -> str:
    parsed = urlparse(entry["link"])
    normalized_link = f"{parsed.netloc}{parsed.path}".rstrip("/")
    normalized_title = re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")
    if normalized_link:
        return f"{normalized_title}|{normalized_link}"
    return normalized_title


def group_entries_by_day(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in sorted(entries, key=lambda item: item["published"], reverse=True):
        grouped[entry["published"].strftime("%Y-%m-%d")].append(entry)
    return [
        {"date": day, "entries": day_entries}
        for day, day_entries in sorted(grouped.items(), reverse=True)
    ]


def select_featured_entries(entries: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(
        entries,
        key=lambda item: (
            0 if item["source"] in OFFICIAL_SOURCES else 1,
            -int(item["published"].timestamp()),
        ),
    )
    return ranked[:limit]


def build_news_payload(entries: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
    return {
        "generated_at": generated_at.isoformat(),
        "count": len(entries),
        "items": [
            {
                **entry,
                "published": entry["published"].isoformat(),
            }
            for entry in entries
        ],
    }


def render_site(
    *,
    entries: list[dict[str, Any]],
    generated_at: datetime,
    output_dir: str | Path,
    site_title: str,
    base_url: str = "",
    description: str = "",
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / "archive"
    archive_path.mkdir(parents=True, exist_ok=True)

    template_env = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    index_template = template_env.get_template("index.html.j2")
    archive_template = template_env.get_template("archive.html.j2")
    archive_index_template = template_env.get_template("archive_index.html.j2")

    all_grouped = group_entries_by_day(entries)
    today_key = generated_at.strftime("%Y-%m-%d")
    today_entries = next((group["entries"] for group in all_grouped if group["date"] == today_key), [])
    display_entries = today_entries or (all_grouped[0]["entries"] if all_grouped else [])
    display_day_key = today_key if today_entries else (all_grouped[0]["date"] if all_grouped else today_key)
    featured_entries = select_featured_entries(display_entries)
    remaining_entries = [entry for entry in display_entries if entry not in featured_entries]

    home_html = index_template.render(
        site_title=site_title,
        generated_at=generated_at,
        description=description,
        today_key=display_day_key,
        featured_entries=featured_entries,
        remaining_entries=remaining_entries,
        archive_url=(base_url or "") + "archive/",
        json_url=(base_url or "") + "news.json",
    )
    (output_path / "index.html").write_text(home_html, encoding="utf-8")

    archive_index_html = archive_index_template.render(
        site_title=site_title,
        generated_at=generated_at,
        grouped_entries=all_grouped,
        home_url=base_url or "../",
    )
    (archive_path / "index.html").write_text(archive_index_html, encoding="utf-8")

    for group in all_grouped:
        day_html = archive_template.render(
            site_title=site_title,
            day=group["date"],
            entries=group["entries"],
            home_url=(base_url or "../"),
            archive_index_url=(base_url or "") + "archive/",
        )
        (archive_path / f"{group['date']}.html").write_text(day_html, encoding="utf-8")

    payload = build_news_payload(display_entries, generated_at)
    (output_path / "news.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_site(config_path: str | Path = "sources.yaml") -> list[dict[str, Any]]:
    config = load_config(config_path)
    site_config = config["site"]
    generated_at = datetime.now(timezone.utc)
    entries = fetch_entries(config["sources"])
    final_entries = dedupe_and_filter_entries(
        entries,
        now=generated_at,
        lookback_hours=site_config.get("lookback_hours", 48),
        max_items=site_config.get("max_items", 60),
    )
    render_site(
        entries=final_entries,
        generated_at=generated_at,
        output_dir="docs",
        site_title=site_config.get("title", "每日 AI 资讯"),
        base_url=site_config.get("base_url", ""),
        description=site_config.get("description", ""),
    )
    return final_entries
