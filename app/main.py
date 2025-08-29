import os, hashlib, time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import requests, feedparser
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="AI Curator")

DIGEST_WINDOW_HOURS = int(os.getenv("DIGEST_WINDOW_HOURS", "24"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "25"))

NYT_API_KEY = os.getenv("NYT_API_KEY", "")
NYT_QUERY = os.getenv("NYT_QUERY", '( "artificial intelligence" OR AI )')
NYT_PAGE_LIMIT = int(os.getenv("NYT_PAGE_LIMIT", "2"))

DEFAULT_ECON_FEEDS = [
    "https://www.economist.com/science-and-technology/rss.xml",
    "https://www.economist.com/business/rss.xml",
]
ECON_FEEDS = [u.strip() for u in os.getenv("ECON_FEEDS", "").split(",") if u.strip()] or DEFAULT_ECON_FEEDS

AI_KEYWORDS = [k.lower() for k in os.getenv("AI_KEYWORDS", "AI,artificial intelligence,machine learning,LLM,OpenAI,Anthropic,GPT,deep learning").split(",")]

INSTAPAPER_USER = os.getenv("INSTAPAPER_SIMPLE_USER", "")
INSTAPAPER_PASS = os.getenv("INSTAPAPER_SIMPLE_PASS", "")

app.state.digest: List[Dict[str, Any]] = []

def _mk_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]

def _contains_ai(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in AI_KEYWORDS)

def _canon(url: str) -> str:
    return url.split("?")[0].rstrip("/")

def fetch_nyt_ai(since: datetime) -> List[Dict[str, Any]]:
    if not NYT_API_KEY: return []
    base = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
    begin_date = since.strftime("%Y%m%d")
    params = {"q": NYT_QUERY, "begin_date": begin_date, "sort": "newest", "api-key": NYT_API_KEY}
    out: List[Dict[str, Any]] = []
    for page in range(NYT_PAGE_LIMIT):
        params["page"] = page
        r = requests.get(base, params=params, timeout=20)
        if r.status_code != 200: break
        docs = r.json().get("response", {}).get("docs", [])
        for d in docs:
            url, title = d.get("web_url"), (d.get("headline") or {}).get("main")
            if url and title and _contains_ai(title):
                out.append({"id": _mk_id(url), "source": "NYT", "title": title.strip(), "url": url, "published_at": d.get("pub_date")})
        time.sleep(0.2)
    return out

def fetch_econ_ai(since: datetime) -> List[Dict[str, Any]]:
    out = []
    for feed in ECON_FEEDS:
        try: f = feedparser.parse(feed)
        except Exception: continue
        for e in f.entries:
            url, title = getattr(e, "link", None), getattr(e, "title", None)
            summary = getattr(e, "summary", "")
            if url and title and _contains_ai(title + " " + summary):
                out.append({"id": _mk_id(url), "source": "Economist", "title": title.strip(), "url": url, "published_at": getattr(e, "published", None)})
    return out

def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, unique = set(), []
    for it in items:
        cu = _canon(it["url"])
        if cu not in seen:
            seen.add(cu)
            unique.append(it)
    return unique[:MAX_ITEMS]

def instapaper_add(url: str, title: str | None = None) -> Dict[str, Any]:
    if not (INSTAPAPER_USER and INSTAPAPER_PASS):
        return {"ok": False, "error": "Instapaper creds missing"}
    data = {"url": url}
    if title: data["title"] = title
    resp = requests.post("https://www.instapaper.com/api/add", data=data, auth=(INSTAPAPER_USER, INSTAPAPER_PASS), timeout=20)
    return {"ok": resp.status_code in (201, 202), "status": resp.status_code}

@app.get("/run-digest")
def run_digest():
    since = datetime.now(timezone.utc) - timedelta(hours=DIGEST_WINDOW_HOURS)
    digest = dedupe(fetch_nyt_ai(since) + fetch_econ_ai(since))
    app.state.digest = digest
    return {"count": len(digest)}

@app.get("/digest/today")
def digest_today():
    return app.state.digest

class ApproveBody(BaseModel):
    ids: List[str]

@app.post("/approve")
def approve(body: ApproveBody):
    by_id = {it["id"]: it for it in app.state.digest}
    results = []
    for _id in body.ids:
        if it := by_id.get(_id):
            r = instapaper_add(it["url"], it["title"])
            results.append({"id": _id, "ok": r.get("ok")})
    return {"saved": sum(1 for r in results if r["ok"]), "results": results}
