### **Workflow Diagram Explanation**

The diagram above shows the complete V4 architecture with:

**Layers:**

1. **APP LAYER** **- app.py orchestrates phases \& U**I
2. **PHASE 1** **-** **Knowledge Base pre-crawls all URLs**
3. **PHASE 2 - LangGraph Workflow processes each URL:**
   	Ingestion → Sets up HTML context
   	Orchestrator → Plans execution (uses planner\_agent)
   	Worker → Executes primitives with fallback logic
   	State Updater → Collects metrics
   	Synthesis → Generates summaries (uses writer\_agent)
   	Export → Prepares output
   
4. **TOOLS LAYER - primitive operations:**
   	fetch.py - HTTP requests + JS rendering
   	select.py - CSS/XPath/Regex selectors
   	extract.py - Attribute \& content extraction
   	transform.py - Data normalization \& parsing
   	validate.py - Schema, SSL, GA4, broken links, interstitials, robots.txt
   	measure.py - Word count, keyword density, URL depth
   	compare.py - Comparisons with type conversion
   	reason.py - LLM analysis
   
5. **AGENTS - LLM Brains:**
   	planner\_agent.py - Decomposes columns to primitive chains
   	writer\_agent.py - Converts metrics to professional summaries
   
6. **CONFIG - settings.py centralizes all parameters**
7. **UTILS - logging \& crawler helpers**
8. **GRAPH - LangGraph orchestration**

The system processes URLs in parallel batches with fallback to deterministic checks when LLM primitives fail!