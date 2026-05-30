import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- Configuration ---
ANYTHINGLLM_URL = "http://127.0.0.1:3001/api/v1/document/upload"
ANYTHINGLLM_KEY = os.getenv("ANYTHINGLLM_KEY", "YOUR_API_KEY")
WORKSPACE_SLUG = "devbrain"
BASE_PATH = os.path.expanduser("~/Documents/DeVault")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "gemma4:e4b"

# Lock to serialize Ollama calls (it can only handle one at a time efficiently)
ollama_lock = threading.Lock()

SOURCES = {
    "tech": {"url": "https://news.ycombinator.com", "type": "hn"},
    "conflicts": {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "type": "rss"},
    "geopolitics": {"url": "https://www.aljazeera.com/xml/rss/all.xml", "type": "rss"},
    "worldnews": {"url": "https://www.reddit.com/r/worldnews/.rss", "type": "rss"},
    "rumors": {"url": "https://www.reddit.com/r/conspiracy/.rss", "type": "rss"},
    "intel": {"url": "https://www.reddit.com/r/OSINT/.rss", "type": "rss"}
}

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})

def get_safe_filename(title):
    return "".join(c for c in title if c.isalnum() or c in " -_").strip()

def get_vault_path(category, subfolder="Headlines"):
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(BASE_PATH, subfolder, category, date_str)
    os.makedirs(path, exist_ok=True)
    return path

def extract_article_text(h):
    try:
        r = session.get(h['url'], timeout=5)
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup(["script", "style"]): s.extract()
        text = soup.get_text()
        lines = (l.strip() for l in text.splitlines())
        text = "\n".join(c for l in lines for c in l.split("  ") if c.strip())
        return {"title": h['title'], "content": text[:300]}
    except:
        return {"title": h['title'], "content": ""}

def get_previous_summary(category):
    try:
        path = os.path.join(BASE_PATH, "Summaries", category)
        if not os.path.exists(path): return None
        dates = sorted(os.listdir(path))
        if not dates: return None
        files = sorted(os.listdir(os.path.join(path, dates[-1])))
        if not files: return None
        with open(os.path.join(path, dates[-1], files[-1]), "r") as f:
            return f.read()[-400:]
    except: return None

def push_to_anythingllm(filepath):
    try:
        base_url = ANYTHINGLLM_URL.replace("/document/upload", "")
        with open(filepath, "rb") as f:
            r = session.post(ANYTHINGLLM_URL, headers={"Authorization": f"Bearer {ANYTHINGLLM_KEY}"}, files={"file": f})
        if r.status_code != 200: return
        data = r.json()
        if not data.get("documents"): return
        session.post(f"{base_url}/workspace/{WORKSPACE_SLUG}/update-embeddings",
                     headers={"Authorization": f"Bearer {ANYTHINGLLM_KEY}"},
                     json={"adds": [data["documents"][0]["location"]]})
    except: pass

def process_category(category):
    info = SOURCES[category]
    headlines = []
    t0 = time.time()
    try:
        # --- PHASE 1: SCRAPE (parallel across categories) ---
        r = session.get(info["url"], timeout=10)
        if info["type"] == "hn":
            soup = BeautifulSoup(r.text, "html.parser")
            for story in soup.select(".titleline > a")[:10]:
                headlines.append({"title": story.text, "url": story.get("href"), "scraped_at": datetime.now().isoformat()})
        else:
            soup = BeautifulSoup(r.text, "xml")
            for item in (soup.find_all("item") or soup.find_all("entry"))[:10]:
                title = item.title.text if item.title else "No Title"
                link_tag = item.find("link")
                url = (link_tag.get("href") or link_tag.text) if link_tag else ""
                headlines.append({"title": title, "url": url, "scraped_at": datetime.now().isoformat()})

        # Save headlines to Obsidian immediately
        path = get_vault_path(category)
        date = datetime.now().strftime("%Y-%m-%d")
        for h in headlines:
            fp = os.path.join(path, f"{date}-{get_safe_filename(h['title'])[:50]}.md")
            if not os.path.exists(fp):
                with open(fp, "w") as f:
                    f.write(f"---\ntitle: \"{h['title'].replace('\"', '\\\"')}\"\nurl: \"{h['url']}\"\ncategory: {category}\n---\n# {h['title']}\n")
        
        scrape_time = round(time.time() - t0, 1)
        print(f"  [{category}] Scraped {len(headlines)} in {scrape_time}s")

        if not headlines: return

        # --- PHASE 2: EXTRACT CONTEXT (parallel within category) ---
        deep_context = ""
        with ThreadPoolExecutor(max_workers=2) as ex:
            for res in ex.map(extract_article_text, headlines[:2]):
                if res['content']:
                    deep_context += f"\n--- {res['title']} ---\n{res['content']}\n"

        # --- PHASE 3: AI ANALYSIS (serialized via lock to prevent Ollama overload) ---
        prev = get_previous_summary(category)
        trend = f"\nPREV INTEL:\n{prev}" if prev else ""
        prompt = f"Analyze {category} intel for political actors, conspiracies, convergence, forecasts, solutions:\n{deep_context}\n{trend}\nHeadlines:\n" + "\n".join([h['title'] for h in headlines])

        with ollama_lock:
            print(f"  [{category}] AI queued -> running...")
            ai_start = time.time()
            resp = session.post(OLLAMA_URL, json={"model": MODEL, "prompt": prompt, "stream": False, "options": {"num_predict": 512}}, timeout=300)
            summary = resp.json().get("response", "No summary.")
            print(f"  [{category}] AI done in {round(time.time() - ai_start, 1)}s")

        # --- PHASE 4: PUBLISH ---
        path = get_vault_path(category, "Summaries")
        filepath = os.path.join(path, f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-{category}-intel.md")
        with open(filepath, "w") as f:
            f.write(f"---\ncategory: {category}\ntype: intelligence-report\ndate: {datetime.now().strftime('%Y-%m-%d')}\n---\n# {category.capitalize()} Report\n{summary}")
        push_to_anythingllm(filepath)
        print(f"  ✓ {category} total: {round(time.time() - t0, 1)}s")

    except Exception as e:
        print(f"  ✗ {category}: {e}")

if __name__ == "__main__":
    start_time = time.time()
    print(f"\n--- Hub 3.1 Started {datetime.now().strftime('%H:%M:%S')} ---")
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as executor:
        executor.map(process_category, SOURCES.keys())
    print(f"--- Complete in {round(time.time() - start_time, 1)}s ---")