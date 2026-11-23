from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

RAW_PATH = DATA_DIR / "raw.jsonl"
PROBLEMS_PATH = DATA_DIR / "problems.jsonl"
CLUSTERS_PATH = DATA_DIR / "clusters.json"
SCORED_PATH = DATA_DIR / "scored.csv"
REPORT_MD_PATH = DATA_DIR / "report.md"
REPORT_CSV_PATH = DATA_DIR / "report.csv"
PIPELINE_REPORT_MD_PATH = DATA_DIR / "pipeline_report.md"
PIPELINE_SCORES_CSV_PATH = DATA_DIR / "pipeline_scores.csv"

CACHE_DIR = DATA_DIR / "cache"
EXTRACT_CACHE_DIR = CACHE_DIR / "extract"
IDEATE_CACHE_DIR = CACHE_DIR / "ideate"
HYPOTHESIS_CACHE_DIR = CACHE_DIR / "hypotheses"
HYPOTHESIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
COMPETITOR_CACHE_DIR = CACHE_DIR / "competitors"
COMPETITOR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CRITIQUE_CACHE_DIR = CACHE_DIR / "critiques"
CRITIQUE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
WEDGE_CACHE_DIR = CACHE_DIR / "wedges"
WEDGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MVP_CACHE_DIR = CACHE_DIR / "mvps"
MVP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
GTM_CACHE_DIR = CACHE_DIR / "gtm"
GTM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DECISION_CACHE_DIR = CACHE_DIR / "decisions"
DECISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
USER_AGENT = os.getenv("USER_AGENT", "microsaas-lab/0.1 (research experiment)")
GROQ_KEY = (os.getenv("GROQ_KEY") or os.getenv("GROQ_API_KEY", "")).strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY", "")).strip()
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "").strip()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").lower()
USE_OLLAMA = os.getenv("USE_OLLAMA", "").lower() in ("true", "1", "yes")

def _check_ollama(url: str) -> bool:
    import socket
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        with socket.create_connection((p.hostname or "localhost", p.port or 11434), timeout=0.4):
            return True
    except Exception:
        return False

ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
ollama_active = (LLM_PROVIDER == "ollama" or USE_OLLAMA or bool(os.getenv("OLLAMA_MODEL"))) and _check_ollama(ollama_url)

# Configure LLM client settings (prioritize Ollama if active, then Groq, then OpenAI)
if ollama_active:
    LLM_BASE_URL = ollama_url
    LLM_API_KEY = "ollama"
    DEFAULT_MODEL = os.getenv("OLLAMA_MODEL") or os.getenv("IDEATE_MODEL") or "gpt-oss:20b"
    EXTRACT_MODEL = os.getenv("EXTRACT_MODEL") or DEFAULT_MODEL
    IDEATE_MODEL = os.getenv("IDEATE_MODEL") or DEFAULT_MODEL
elif GROQ_KEY:
    LLM_BASE_URL = "https://api.groq.com/openai/v1"
    LLM_API_KEY = GROQ_KEY
    DEFAULT_MODEL = "qwen/qwen3.8-27b"
    EXTRACT_MODEL = os.getenv("EXTRACT_MODEL") if (os.getenv("EXTRACT_MODEL") and "gpt-oss:20b" not in os.getenv("EXTRACT_MODEL")) else "qwen/qwen3.8-27b"
    IDEATE_MODEL = os.getenv("IDEATE_MODEL") or DEFAULT_MODEL
else:
    LLM_BASE_URL = None
    LLM_API_KEY = OPENAI_API_KEY
    DEFAULT_MODEL = "gpt-4o-mini"
    EXTRACT_MODEL = os.getenv("EXTRACT_MODEL") or DEFAULT_MODEL
    IDEATE_MODEL = os.getenv("IDEATE_MODEL") or DEFAULT_MODEL

LLM_TIMEOUT = float(
    os.getenv(
        "LLM_TIMEOUT",
        "900.0" if (LLM_PROVIDER == "ollama" or USE_OLLAMA or os.getenv("OLLAMA_MODEL")) else "120.0"
    )
)

# Text hygiene: keeps LLM cost predictable and drops noise.
MAX_TEXT_CHARS = 4000
MIN_TEXT_CHARS = 60

# Pain phrases. Mix of emotional and neutral ("manually", "every week").
# Trim with --max-phrases while testing; order = priority.
PAIN_PHRASES = [
    "wish there was",
    "is there a tool",
    "no tool",
    "looking for a tool",
    "there has to be",
    "manually",
    "workaround",
    "takes hours",
    "tired of",
    "every week",
    "is there a way to",
    "how do you handle",
]

# Niche keyword groups
NICHE_KEYWORDS = {
    "data_file": ["csv", "json", "excel", "parquet", "reconcile", "schema inference", "data validation"],
    "api_openapi": ["openapi", "swagger", "api spec", "breaking change", "mock server", "api docs", "postman"],
    "devops_config": ["yaml", "kubernetes", "terraform", "github actions", "helm", "ci config", "kube config"],
}
