# Daily AI News

A first-version AI news site that refreshes daily via GitHub Actions and publishes to GitHub Pages.

What it does
- Pulls a default set of AI-focused RSS/Atom feeds
- Keeps articles from the last 24 hours
- Removes duplicates by title/link
- Generates a static site at `docs/index.html`
- Exports structured data at `docs/news.json`

Default sources
- OpenAI
- Anthropic
- Google DeepMind
- Google AI Blog
- Hugging Face
- Meta AI
- NVIDIA Blog AI
- TechCrunch AI
- The Verge AI
- MIT Technology Review AI

Local usage
1. Install dependencies
   `python3 -m pip install -r requirements.txt`
2. Generate the site
   `python3 generate_news.py`
3. Run tests
   `python3 -m pytest -q`

Repository layout
- `generate_news.py`: entrypoint
- `daily_news/builder.py`: fetch, filter, render logic
- `sources.yaml`: site config and feed list
- `templates/index.html.j2`: HTML template
- `docs/`: generated GitHub Pages output
- `.github/workflows/daily-news.yml`: scheduled workflow

GitHub Pages
- In repo Settings -> Pages, set Source to `GitHub Actions`
- The workflow will regenerate and deploy the site every day

Customize later
- Add or remove feeds in `sources.yaml`
- Change title, description, item limit, and lookback window in `sources.yaml`
- Add AI summaries in a later version with an API key
