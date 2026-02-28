# Market Research Agent

AI-powered market research agent that autonomously searches the web, synthesizes findings, and generates professional PDF reports. Built with the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).

## What It Does

Give it a topic — it produces an executive-grade research brief:

1. **Research phase** — Performs 6-10 targeted web searches and fetches key pages for data on market size, competitors, analyst views, and trends
2. **Writing phase** — Synthesizes findings into a structured 8-10 page Markdown report
3. **PDF generation** — Converts the report to a professionally styled PDF with tables, headers, and page numbers

Reports follow the structure of Gartner/Forrester/McKinsey briefs: Executive Summary, Market Overview, Competitive Landscape, Technology Analysis, Key Trends, Strategic Considerations, and Market Outlook.

## Quick Start

### Prerequisites

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed
- Anthropic API key
- WeasyPrint system dependencies:
  ```bash
  # macOS
  brew install pango

  # Ubuntu/Debian
  sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0
  ```

### Installation

```bash
git clone https://github.com/manish-code125/prd-agent.git
cd prd-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configuration

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### Usage

#### Web UI (recommended)

```bash
market-research serve
```

Open http://localhost:8000 in your browser. Enter a topic, optionally add instructions, and click "Start Research". Progress streams in real-time via SSE.

#### CLI

```bash
market-research research "cloud computing market 2025"
```

Options:
- `--prompt / -p` — Additional instructions for the agent
- `--output / -o` — Output directory (default: `./output`)
- `--max-turns / -t` — Max agent iterations (default: 50)
- `--verbose / -v` — Show detailed agent reasoning

### macOS Note

If using Homebrew-installed pango with Anaconda Python, you may need:

```bash
DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib" market-research serve
```

## Project Structure

```
prd-agent/
├── pyproject.toml                   # Dependencies and CLI entry point
├── .env.example                     # API key template
├── market_research/
│   ├── cli.py                       # Typer CLI (research + serve commands)
│   ├── agent.py                     # Claude Agent SDK query + report extraction
│   ├── web.py                       # FastAPI server with SSE streaming
│   ├── pdf_renderer.py              # Markdown -> HTML -> PDF (WeasyPrint)
│   ├── prompts/
│   │   ├── system_prompt.txt        # Research methodology + output format
│   │   └── task_template.txt        # Task prompt with {topic} placeholder
│   ├── styles/
│   │   └── report.css               # Professional A4 PDF styling
│   ├── templates/
│   │   └── index.html               # Web UI (dark theme, SSE progress)
│   └── utils/
│       └── config.py                # Environment loading + validation
└── output/                          # Generated PDF reports
```

## How It Works

The agent uses a two-phase pipeline:

**Phase 1: Research** — A Claude agent with `WebSearch` and `WebFetch` tools performs targeted searches across market landscape, competitive intelligence, analyst perspectives, and strategic outlook. The agent follows a structured methodology with a hard limit of 10 tool calls to prevent endless searching.

**Phase 2: Report** — The agent writes a complete Markdown report in a single message, following a prescribed executive brief format. Python code then converts this to a styled PDF using `markdown` + `weasyprint` with custom CSS.

The agent itself never writes files or generates PDFs — it only searches and composes text. PDF rendering happens in deterministic Python code, making the output reliable and customizable.

## Web UI Features

- Real-time progress streaming (searches, fetches, status)
- Session-based cancellation (stop research mid-flight)
- Heartbeat indicators for long-running sessions
- Report history with download links
- Dark theme interface

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent | Claude Agent SDK (`claude-code-sdk`) |
| CLI | Typer + Rich |
| Web server | FastAPI + Uvicorn |
| Real-time updates | Server-Sent Events (SSE) |
| PDF rendering | markdown + WeasyPrint |
| Styling | Custom CSS (A4, page numbers, tables) |

## License

MIT
