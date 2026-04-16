# 每日 AI 资讯

一个每天自动刷新并发布到 GitHub Pages 的 AI 新闻聚合站。

功能
- 抓取默认 AI RSS/Atom 新闻源
- 保留最近 48 小时的新闻，便于首页展示当天并兼顾归档
- 按标题和链接去重
- 首页展示“今日重点 + 今日全部 + 历史归档”
- 生成首页 `docs/index.html`
- 生成今日数据 `docs/news.json`
- 生成历史归档 `docs/archive/`

默认源
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

本地使用
1. 安装依赖
   `python3 -m pip install -r requirements.txt`
2. 生成站点
   `python3 generate_news.py`
3. 运行测试
   `python3 -m pytest -q`

仓库结构
- `generate_news.py`: 生成入口
- `daily_news/builder.py`: 抓取、过滤、分组、渲染逻辑
- `sources.yaml`: 站点配置和新闻源
- `templates/index.html.j2`: 中文首页模板
- `templates/archive_index.html.j2`: 历史归档索引
- `templates/archive.html.j2`: 单日归档页
- `docs/`: GitHub Pages 生成输出
- `.github/workflows/daily-news.yml`: 定时工作流

GitHub Pages
- 在仓库 Settings -> Pages 中把 Source 设为 `GitHub Actions`
- 工作流每天会重新生成并部署站点

后续可继续增强
- 为每条新闻生成中文标题
- 为每条新闻生成中文摘要
- 增加按来源筛选
- 增加周报/月报页面
