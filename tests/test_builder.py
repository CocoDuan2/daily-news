from datetime import datetime, timedelta, timezone
import json
import ssl
import os

from daily_news.builder import (
    dedupe_and_filter_entries,
    fetch_entries,
    fetch_rss_entries,
    render_site,
)


NOW = datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc)


def make_entry(source: str, title: str, link: str, published: datetime, summary: str) -> dict:
    return {
        "source": source,
        "title": title,
        "link": link,
        "published": published,
        "summary": summary,
    }


def test_dedupe_and_filter_entries_keeps_recent_unique_items_sorted():
    entries = [
        make_entry("OpenAI", "Fresh launch", "https://example.com/fresh", NOW - timedelta(hours=2), "Fresh summary"),
        make_entry("Anthropic", "Duplicate title", "https://example.com/dup", NOW - timedelta(hours=3), "Original"),
        make_entry("Anthropic", "Duplicate title", "https://example.com/dup-2", NOW - timedelta(hours=4), "Should be removed by title"),
        make_entry("Google AI", "Old item", "https://example.com/old", NOW - timedelta(hours=30), "Too old"),
    ]

    result = dedupe_and_filter_entries(entries, now=NOW, lookback_hours=24)

    assert [item["title"] for item in result] == ["Fresh launch", "Duplicate title"]
    assert result[0]["source"] == "OpenAI"


def test_render_site_writes_chinese_homepage_and_archives(tmp_path):
    entries = [
        make_entry("OpenAI", "OpenAI launches GPT update", "https://example.com/openai", NOW, "OpenAI 发布新更新"),
        make_entry("Anthropic", "Claude gets new coding features", "https://example.com/claude", NOW + timedelta(minutes=30), "Claude 编程能力增强"),
        make_entry("Google DeepMind", "Gemini research milestone", "https://example.com/gemini", NOW - timedelta(days=1), "Gemini 研究进展"),
    ]

    render_site(
        entries=entries,
        generated_at=NOW,
        output_dir=tmp_path,
        site_title="每日 AI 资讯",
        base_url="https://cocoduan2.github.io/daily-news/",
        description="每天自动更新的 AI 新闻聚合站。",
    )

    home_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    archive_index = (tmp_path / "archive" / "index.html").read_text(encoding="utf-8")
    archive_day = (tmp_path / "archive" / "2026-04-15.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))

    assert "每日 AI 资讯" in home_html
    assert "今日重点" in home_html
    assert "今日全部" in home_html
    assert "历史归档" in home_html
    assert "https://cocoduan2.github.io/daily-news/archive/" in home_html
    assert "OpenAI launches GPT update" in home_html
    assert "Claude gets new coding features" in home_html
    assert "Gemini research milestone" not in home_html

    assert "历史归档" in archive_index
    assert "2026-04-16" in archive_index
    assert "2026-04-15" in archive_index

    assert "2026-04-15 AI 资讯" in archive_day
    assert "Gemini research milestone" in archive_day

    assert payload["count"] == 2
    assert [item["title"] for item in payload["items"]] == [
        "Claude gets new coding features",
        "OpenAI launches GPT update",
    ]


def test_fetch_entries_skips_tavily_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    result = fetch_entries(
        [
            {
                "name": "Tavily AI News",
                "type": "tavily",
                "query": "AI news",
                "topic": "news",
                "max_results": 5,
            }
        ]
    )

    assert result == []


def test_fetch_entries_uses_tavily_results_when_api_key_present(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["auth"] = request.get_header("Authorization")
        body = json.loads(request.data.decode("utf-8"))
        captured["body"] = body

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": "Major AI release",
                                "url": "https://example.com/ai-release",
                                "content": "A major AI model was released.",
                                "published_date": "2026-04-15T09:30:00Z",
                            }
                        ]
                    }
                ).encode("utf-8")

        return FakeResponse()

    monkeypatch.setattr("daily_news.builder.urlopen", fake_urlopen)

    result = fetch_entries(
        [
            {
                "name": "Tavily AI News",
                "type": "tavily",
                "query": "AI news",
                "topic": "news",
                "max_results": 5,
            }
        ]
    )

    assert len(result) == 1
    assert result[0]["source"] == "Tavily AI News"
    assert result[0]["title"] == "Major AI release"
    assert result[0]["link"] == "https://example.com/ai-release"
    assert result[0]["summary"] == "A major AI model was released."
    assert result[0]["published"] == datetime(2026, 4, 15, 9, 30, tzinfo=timezone.utc)
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["query"] == "AI news"
    assert captured["body"]["topic"] == "news"
    assert captured["body"]["max_results"] == 5


def test_fetch_rss_entries_retries_with_explicit_download_when_feedparser_ssl_fails(monkeypatch):
    captured = {}
    rss_xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <rss version='2.0'>
      <channel>
        <title>Example Feed</title>
        <item>
          <title>SSL-safe AI update</title>
          <link>https://example.com/ssl-safe</link>
          <pubDate>Wed, 15 Apr 2026 12:00:00 GMT</pubDate>
          <description>Downloaded with explicit CA bundle.</description>
        </item>
      </channel>
    </rss>
    """

    class FakeFailingFeed:
        entries = []
        bozo = 1
        bozo_exception = ssl.SSLCertVerificationError("certificate verify failed")

    def fake_feedparser_parse(payload):
        captured.setdefault("parse_calls", []).append(payload)
        if isinstance(payload, str):
            return FakeFailingFeed()
        return type("ParsedFeed", (), {
            "entries": [
                {
                    "title": "SSL-safe AI update",
                    "link": "https://example.com/ssl-safe",
                    "published": "Wed, 15 Apr 2026 12:00:00 GMT",
                    "summary": "Downloaded with explicit CA bundle.",
                }
            ],
            "bozo": 0,
        })()

    def fake_download(url):
        captured["download_url"] = url
        return rss_xml

    monkeypatch.setattr("daily_news.builder.feedparser.parse", fake_feedparser_parse)
    monkeypatch.setattr("daily_news.builder.download_feed_content", fake_download)

    result = fetch_rss_entries({"name": "Example RSS", "url": "https://example.com/feed.xml"})

    assert len(result) == 1
    assert result[0]["source"] == "Example RSS"
    assert result[0]["title"] == "SSL-safe AI update"
    assert captured["parse_calls"][0] == "https://example.com/feed.xml"
    assert captured["parse_calls"][1] == rss_xml
    assert captured["download_url"] == "https://example.com/feed.xml"


def test_fetch_entries_skips_sources_that_raise_errors(monkeypatch):
    def fake_fetch_rss_entries(source):
        if source["name"] == "Broken Feed":
            raise RuntimeError("boom")
        return [
            {
                "source": source["name"],
                "title": "Working item",
                "link": "https://example.com/item",
                "published": datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
                "summary": "ok",
            }
        ]

    monkeypatch.setattr("daily_news.builder.fetch_rss_entries", fake_fetch_rss_entries)

    result = fetch_entries(
        [
            {"name": "Broken Feed", "url": "https://example.com/broken.xml"},
            {"name": "Healthy Feed", "url": "https://example.com/healthy.xml"},
        ]
    )

    assert len(result) == 1
    assert result[0]["source"] == "Healthy Feed"


def test_render_site_uses_latest_available_day_when_generated_day_has_no_entries(tmp_path):
    generated_at = datetime(2026, 4, 16, 3, 0, tzinfo=timezone.utc)
    entries = [
        make_entry("TechCrunch AI", "Late-night AI funding round", "https://example.com/funding", datetime(2026, 4, 15, 23, 30, tzinfo=timezone.utc), "Funding update"),
        make_entry("OpenAI", "Agents SDK update", "https://example.com/agents", datetime(2026, 4, 15, 20, 0, tzinfo=timezone.utc), "SDK update"),
    ]

    render_site(
        entries=entries,
        generated_at=generated_at,
        output_dir=tmp_path,
        site_title="每日 AI 资讯",
        base_url="https://cocoduan2.github.io/daily-news/",
        description="每天自动更新的 AI 新闻聚合站。",
    )

    home_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))

    assert "Late-night AI funding round" in home_html
    assert "Agents SDK update" in home_html
    assert payload["count"] == 2
    assert [item["title"] for item in payload["items"]] == [
        "Late-night AI funding round",
        "Agents SDK update",
    ]
