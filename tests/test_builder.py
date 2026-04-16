from datetime import datetime, timedelta, timezone
import json

from daily_news.builder import dedupe_and_filter_entries, render_site


NOW = datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc)


def test_dedupe_and_filter_entries_keeps_recent_unique_items_sorted():
    entries = [
        {
            "source": "OpenAI",
            "title": "Fresh launch",
            "link": "https://example.com/fresh",
            "published": NOW - timedelta(hours=2),
            "summary": "Fresh summary",
        },
        {
            "source": "Anthropic",
            "title": "Duplicate title",
            "link": "https://example.com/dup",
            "published": NOW - timedelta(hours=3),
            "summary": "Original",
        },
        {
            "source": "Anthropic",
            "title": "Duplicate title",
            "link": "https://example.com/dup-2",
            "published": NOW - timedelta(hours=4),
            "summary": "Should be removed by title",
        },
        {
            "source": "Google AI",
            "title": "Old item",
            "link": "https://example.com/old",
            "published": NOW - timedelta(hours=30),
            "summary": "Too old",
        },
    ]

    result = dedupe_and_filter_entries(entries, now=NOW, lookback_hours=24)

    assert [item["title"] for item in result] == ["Fresh launch", "Duplicate title"]
    assert result[0]["source"] == "OpenAI"


def test_render_site_writes_html_and_json(tmp_path):
    entries = [
        {
            "source": "OpenAI",
            "title": "Fresh launch",
            "link": "https://example.com/fresh",
            "published": NOW,
            "summary": "A short summary",
        }
    ]

    render_site(
        entries=entries,
        generated_at=NOW,
        output_dir=tmp_path,
        site_title="Daily AI News",
        base_url="https://cocoduan2.github.io/daily-news/",
    )

    html = (tmp_path / "index.html").read_text()
    payload = json.loads((tmp_path / "news.json").read_text())

    assert "Fresh launch" in html
    assert "Daily AI News" in html
    assert "https://cocoduan2.github.io/daily-news/news.json" in html
    assert payload["count"] == 1
    assert payload["items"][0]["source"] == "OpenAI"
    assert payload["items"][0]["published"] == "2026-04-16T00:00:00+00:00"
