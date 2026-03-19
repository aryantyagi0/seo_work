### **File-by-File Explanation**


**app.py (The Director)**

* Role: The main interface. It calls create\_workflow() and runs the graph for every URL in your Excel file. It handles the "Phase 1" pre-crawling manually before starting the graph.


**workflow.py \& nodes.py (The Assembly Line)**

* workflow.py: Defines the path: Ingestion → Orchestrator → Worker → State → Synthesis.
* ingestion\_node: Prepares the data. It checks if the Knowledge Base has the HTML; if not, it fetches it live.
* orchestrator\_node: The "Manager". It looks at your Excel columns and asks the Planner Agent "How do I solve this column?". It creates a JSON plan of primitives.
* worker\_node: The "Doer". It takes the JSON plan and runs the actual Python tools (tools/). Crucially, it checks fallback\_checks.py for reliable deterministic logic.
* synthesis\_node: The "Writer". It takes the raw numbers from the Worker and asks the Writer Agent to write a human-readable summary.


**agents/ (The Brains)**

* planner\_agent.py: Uses gpt-4o-mini map a human request (e.g., "Check canonical") into a sequence of tools (e.g., SELECT -> EXTRACT -> COMPARE).
* writer\_agent.py: Uses gpt-4o-mini to turn raw data (JSON) into a professional SEO audit summary.


**tools/ (The Hands)**

* fetch.py: Handles network requests. Knows when to use simple aiohttp vs complex Crawl4AI (for JS rendering).
* validate.py: Contains the heavy logic for specific SEO checks (SSL expiration, GA4 patterns, Broken Link checking).
* measure.py: Math stuff (Word counts, keyword density TF-IDF).
* select.py / extract.py: HTML parsing helpers (finding tags, getting attributes).
* etc...


**settings.py (The Rules)**

* Sets API keys, timeouts, and crucial flags like FALLBACK\_ENABLED (which tells the system to prefer your hard-coded Python checks over LLM guesses when possible).