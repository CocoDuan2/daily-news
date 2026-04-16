from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
from jinja2 import Environment, FileSystemLoader, select_autoescape


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
        feed = feedparser.parse(source["url"])
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

    template_env = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = template_env.get_template("index.html.j2")

    html = template.render(
        site_title=site_title,
        generated_at=generated_at,
        entries=entries,
        base_url=base_url,
        description=description,
    )
    (output_path / "index.html").write_text(html, encoding="utf-8")

    payload = {
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
        lookback_hours=site_config.get("lookback_hours", 24),
        max_items=site_config.get("max_items", 30),
    )
    render_site(
        entries=final_entries,
        generated_at=generated_at,
        output_dir="docs",
        site_title=site_config.get("title", "Daily AI News"),
        base_url=site_config.get("base_url", ""),
        description=site_config.get("description", ""),
    )
    return final_entries
