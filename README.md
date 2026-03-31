# 🤖 SEO Ecosystem: Multi-Agent Audit & Rank Tracking Suite


## 📖 Overview
This repository contains three independent SEO systems:
- Version 3.1: interactive, URL-first auditing with a chatbot, deterministic parameter tools, LangGraph orchestration, KB caching, and Excel/PDF outputs with recommendations.
- Version 4: LLM Orchestrator architecture with a 5-phase pipeline, primitive tool chains, a pre-crawled Knowledge Base, and Excel reporting.
- Keyword Rank Tracker: local SEO rank tracking (Map Pack + Organic) via a Streamlit UI with a FastAPI backend, using Playwright or SerpApi and storing history in SQLite.

These systems are not upgrades of each other. They have different workflows, data models, inputs, and design goals.


# 🛠️ Project Setup Guide
Python 3.12 preferred (Version 4 enforces 3.12+; Version 3.1 is compatible).

1. Install Python Dependencies
```bash
pip install -r "requirements.txt"
```

2. Install Playwright
```bash
playwright install
```

3. Set Up Crawl4AI
```bash
crawl4ai-setup  #Setup Crawl4AI Browser
crawl4ai-doctor #verify if its working
```

4. Lighthouse Setup (Node.js Dependency)

- Initialize Node Project
```bash
npm init -y
```

- Install Lighthouse
```bash
npm install lighthouse --save-dev
```

5. Environment Configuration

Create a `.env` file in the project root and configure the following:

```env
# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here
```

Make sure your `.env` file is added to `.gitignore`.


## ▶️ Deployment & Usage
- **Unified Streamlit (recommended)**
Run to access both Version 3.1 and Version 4 from a single UI entry point:
```bash
streamlit run "unified_app2.py"
```

---

## 📌 What Happens After Launch
The main Streamlit hub opens with three options and launches each version in its own tab:
1. V1: Agentic Assistant (Version 3.1)
2. V2: LLM Orchestrator (Version 4)
3. V3: Rank Tracker (Keyword Rank)

Keep the hub tab open because it manages the background processes for all versions.

---

**V1: Agentic Assistant (Version 3.1)**
1. Enter the `Website URL`.
2. `Audit all discovered URLs` is checked by default (runs for all discovered URLs). Untick it to set a `Max URLs` limit.
3. Click `Run Audit`. The chatbot is the main focus and becomes available only after the first audit completes.

---

**V2: LLM Orchestrator (Version 4)**
1. Upload an Excel file with URLs.
2. Use the slider to set how many URLs to audit.
3. Click `Start Audit` and download the generated report.

---

**V3: Rank Tracker (Keyword Rank)**
1. Select `City`, add `Area` (optional), set `Brand` and `Domain`, and choose the search method (`playwright` or `serpapi`). If using `serpapi`, enter the API key.
2. Enter the `Keyword` and click `Check Rankings`.
3. Optionally enable `Show Ranking History` to view charts and a daily rank table.




