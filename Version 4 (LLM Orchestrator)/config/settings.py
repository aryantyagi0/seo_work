"""
Configuration settings for V4 LLM Orchestrator
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Check Python version requirement
if sys.version_info < (3, 12):
    raise RuntimeError("This application requires Python 3.12 or higher")

# Set base directory paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "outputs"
VECTOR_DB_DIR = DATA_DIR / "vector_db"
PROMPTS_DIR = BASE_DIR / "prompts"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please check your .env file.")

PLANNER_MODEL = "gpt-4o-mini"
WRITER_MODEL = "gpt-4o-mini"
LLM_TIMEOUT = 45 
LLM_TEMPERATURE = 0  

# Fallback: if primitive chain fails/returns bad data, use deterministic checks
FALLBACK_ENABLED = True

# FAISS Configuration
FAISS_INDEX_PATH = VECTOR_DB_DIR / "central_truth.faiss"
FAISS_METADATA_PATH = VECTOR_DB_DIR / "metadata.json"
EMBEDDING_MODEL = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.50

# Crawler Configuration
CRAWL_TIMEOUT = 30
MAX_RETRIES = 2
USER_AGENT = "Mozilla/5.0 (compatible; SEOAuditor/4.0)"

# Crawl4AI Configuration (Python 3.12 compatible)
CRAWL4AI_ENABLED = True
CRAWL4AI_BROWSER = "chromium"  # chromium, firefox, webkit
CRAWL4AI_HEADLESS = True
CRAWL4AI_WAIT_FOR = "networkidle"  # networkidle, domcontentloaded, load

# Columns requiring JavaScript rendering (Crawl4AI)
CRAWL4AI_REQUIRED_COLUMNS = [
    "Avoid crawl traps",
    "Avoid redirect chains/loops",
    "Broken Links",
    "GEO Friendly",
    "Google Analytics/GA4 setup",
    "Google Search Console setup",
    "Image Alt Text & Tag",
    "Internal linking optimization",
    "No mixed content warnings"
]

# Column Bypass Keywords
LIGHTHOUSE_COLUMNS = ["LCP", "FID", "INP", "CLS", "Mobile page speed"]
SERVER_LOG_COLUMNS = ["Analyze server logs"]

# Maximum tokens of raw data to send to writer (prevents context overflow)
WRITER_MAX_RAW_CHARS = 4000

# Parallelism tuning
URL_BATCH_SIZE = 3        # Process URLs in parallel batches of 3
WRITER_BATCH_SIZE = 10    # Writer summaries in parallel batches of 10
PLANNER_BATCH_SIZE = 15   # Planner columns in parallel batches of 15
WORKER_BATCH_SIZE = 15    # Worker columns in parallel batches of 15
BROKEN_LINK_LIMIT = 25    # Max links to HEAD-check (was 50)
LINK_CHECK_TIMEOUT = 4    # Seconds per HEAD/GET link check (was 8)

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"