"""
AI Daily Bulletin — Versión 100% GRATUITA
Usa Gemini 2.5 Flash-Lite (Google AI Studio free tier: 1,000 req/día gratis)

Variables de entorno requeridas (GitHub Secrets):
  GEMINI_API_KEY      — API key de Google AI Studio (gratis en aistudio.google.com)
  NOTION_TOKEN        — Integration token de Notion
  NOTION_DATABASE_ID  — ID de tu base de datos AI News Feed
  GITHUB_TOKEN        — (opcional) sube el rate limit de GitHub de 60 a 5,000 req/hora
"""

import os, sys, json, time, hashlib, logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
NOTION_TOKEN       = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "0916313650de4b1e945857fe95734269")
HOURS_LOOKBACK     = int(os.environ.get("HOURS_LOOKBACK", "26"))
MAX_PER_FEED       = int(os.environ.get("MAX_PER_FEED", "2"))

# Flash-Lite = 1,000 req/día gratis (más que suficiente)
# Cambia a "gemini-2.5-flash" si quieres más calidad (250 req/día)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

# ── Fuentes RSS ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # Papers
    {"url": "https://rss.arxiv.org/rss/cs.AI",  "source": "ArXiv",        "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.LG",  "source": "ArXiv",        "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.CV",  "source": "ArXiv",        "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.CL",  "source": "ArXiv",        "category": "Paper"},

    # Modelos y herramientas
    {"url": "https://huggingface.co/blog/feed.xml",       "source": "Hugging Face", "category": "Foundation Model"},
    {"url": "https://simonwillison.net/atom/everything/",  "source": "Blog",         "category": "Tool"},
    {"url": "https://blog.langchain.dev/rss/",             "source": "Blog",         "category": "Workflow"},
    {"url": "https://www.llamaindex.ai/blog/rss.xml",      "source": "Blog",         "category": "Workflow"},

    # Labs oficiales
    {"url": "https://openai.com/blog/rss.xml",   "source": "OpenAI",    "category": "Foundation Model"},
    {"url": "https://www.anthropic.com/rss.xml", "source": "Anthropic", "category": "Foundation Model"},
    {"url": "https://mistral.ai/feed.xml",       "source": "Other",     "category": "Foundation Model"},

    # Reddit — posts más votados del día
    {"url": "https://www.reddit.com/r/LocalLLaMA/.rss?limit=10&sort=hot",      "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/MachineLearning/.rss?limit=10&sort=hot", "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/StableDiffusion/.rss?limit=10&sort=hot", "source": "Reddit", "category": "Image Gen"},
    {"url": "https://www.reddit.com/r/comfyui/.rss?limit=10&sort=hot",         "source": "Reddit", "category": "Image Gen"},
    {"url": "https://www.reddit.com/r/singularity/.rss?limit=10&sort=hot",     "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/aivideo/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Video Gen"},
    {"url": "https://www.reddit.com/r/AIMusic/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Audio"},
    {"url": "https://www.reddit.com/r/ollama/.rss?limit=5&sort=hot",           "source": "Reddit", "category": "Tool"},
    {"url": "https://www.reddit.com/r/FluxAI/.rss?limit=5&sort=hot",           "source": "Reddit", "category": "Image Gen"},

    # Hacker News filtrado por puntos
    {"url": "https://hnrss.org/newest?q=LLM+language+model&points=50",       "source": "Other", "category": "Community"},
    {"url": "https://hnrss.org/newest?q=stable+diffusion+comfyui&points=30", "source": "Other", "category": "Image Gen"},
    {"url": "https://hnrss.org/newest?q=AI+agent+RAG&points=50",             "source": "Other", "category": "Agent"},
]

# ── GitHub Releases ───────────────────────────────────────────────────────────
GITHUB_REPOS = [
    {"repo": "comfyanonymous/ComfyUI",               "category": "Image Gen",        "source": "GitHub"},
    {"repo": "ollama/ollama",                         "category": "Tool",             "source": "GitHub"},
    {"repo": "ggml-org/llama.cpp",                    "category": "Foundation Model", "source": "GitHub"},
    {"repo": "huggingface/transformers",              "category": "Foundation Model", "source": "GitHub"},
    {"repo": "LangChain-ai/langchain",                "category": "Workflow",         "source": "GitHub"},
    {"repo": "black-forest-labs/flux",                "category": "Image Gen",        "source": "GitHub"},
    {"repo": "unslothai/unsloth",                     "category": "Update",           "source": "GitHub"},
    {"repo": "microsoft/autogen",                     "category": "Agent",            "source": "GitHub"},
    {"repo": "BerriAI/litellm",                       "category": "Tool",             "source": "GitHub"},
    {"repo": "run-llama/llama_index",                 "category": "Workflow",         "source": "GitHub"},
    {"repo": "Wan-Video/Wan2.1",                      "category": "Video Gen",        "source": "GitHub"},
    {"repo": "AUTOMATIC1111/stable-diffusion-webui",  "category": "Image Gen",        "source": "GitHub"},
]

GITHUB_HEADERS = {"Accept": "application/vnd.github+json"}
if os.environ.get("GITHUB_TOKEN"):
    GITHUB_HEADERS["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

# ── Gemini ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un experto en AI/ML. Analizas noticias y papers de IA.
Devuelve ÚNICAMENTE JSON válido, sin texto extra, sin bloques de código markdown.

Estructura exacta:
{
  "titulo": "string conciso en español (máx 120 chars)",
  "resumen": "2-3 oraciones en español: qué es y por qué importa",
  "categoria": "Foundation Model | Tool | Paper | Community | Image Gen | Video Gen | Audio | RAG | Agent | Update | Other",
  "tipo": "Open Source | Closed | Research | Community | Update",
  "relevancia": "Alta | Media | Baja",
  "tags": ["LLM","Vision","Audio","Video","Image","RAG","Agent","Multimodal","ComfyUI","Diffusion","SOTA"]
}

Relevancia → Alta: modelo SOTA nuevo, paper breakthrough, release mayor importante
             Media: actualización, tutorial útil, discusión relevante
             Baja: opinión, contenido sin novedad técnica"""


def analyze_with_gemini(title: str, content: str, url: str, suggested_cat: str) -> Optional[dict]:
    prompt = (
        f"{SYSTEM_PROMPT}\n\nAnaliza:\nTítulo: {title}\nURL: {url}\n"
        f"Categoría sugerida: {suggested_cat}\nContenido: {content[:2500]}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
    }

    for attempt in range(3):
        try:
            r = requests.post(GEMINI_URL, json=payload, timeout=30)

            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                log.warning(f"Rate limit Gemini — esperando {wait}s...")
                time.sleep(wait)
                continue

            if r.status_code != 200:
                log.warning(f"Gemini HTTP {r.status_code}: {r.text[:150]}")
                return None

            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Limpiar bloques ```json ... ``` si Gemini los incluye
            if "```" in raw:
                for chunk in raw.split("```"):
                    chunk = chunk.strip().lstrip("json").strip()
                    if chunk.startswith("{"):
                        raw = chunk
                        break

            return json.loads(raw)

        except json.JSONDecodeError as e:
            log.warning(f"JSON inválido para '{title[:50]}': {e}")
            return None
        except requests.RequestException as e:
            log.warning(f"Red error Gemini (intento {attempt+1}): {e}")
            time.sleep(5)

    return None


# ── Deduplicación ─────────────────────────────────────────────────────────────
_seen: set = set()

def already_seen(url: str) -> bool:
    h = hashlib.md5(url.encode()).hexdigest()
    if h in _seen:
        return True
    _seen.add(h)
    return False

def is_recent(entry) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc) >= cutoff
            except Exception:
                pass
    return True


# ── RSS Processing ────────────────────────────────────────────────────────────
def process_rss_feeds() -> list[dict]:
    results = []
    for fc in RSS_FEEDS:
        log.info(f"📡 {fc['url'][:70]}")
        try:
            feed = feedparser.parse(fc["url"])
        except Exception as e:
            log.warning(f"Error feed: {e}")
            continue

        count = 0
        for entry in feed.entries:
            if count >= MAX_PER_FEED:
                break
            if not is_recent(entry):
                continue
            entry_url = entry.get("link", "")
            if not entry_url or already_seen(entry_url):
                continue

            content = entry.get("summary", "") or entry.get("description", "") or ""
            title   = entry.get("title", "Sin título")

            analysis = analyze_with_gemini(title, content, entry_url, fc["category"])
            if not analysis:
                continue

            analysis["url"]             = entry_url
            analysis["fuente_original"] = fc["source"]
            results.append(analysis)
            log.info(f"  ✅ [{analysis.get('relevancia','?')}] {analysis.get('titulo','')[:75]}")
            count += 1
            time.sleep(1.5)  # ~10 RPM respetando free tier

    return results


# ── GitHub Processing ─────────────────────────────────────────────────────────
def process_github_releases() -> list[dict]:
    results = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)

    for rc in GITHUB_REPOS:
        repo = rc["repo"]
        log.info(f"🐙 {repo}")
        try:
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=3",
                headers=GITHUB_HEADERS, timeout=10,
            )
            if r.status_code != 200:
                continue
        except Exception as e:
            log.warning(f"Error GitHub {repo}: {e}")
            continue

        for release in r.json():
            pub = release.get("published_at", "")
            if pub:
                try:
                    if datetime.fromisoformat(pub.replace("Z", "+00:00")) < cutoff:
                        continue
                except Exception:
                    pass

            rel_url = release.get("html_url", "")
            if not rel_url or already_seen(rel_url):
                continue

            tag   = release.get("tag_name", "")
            name  = release.get("name", "") or tag
            body  = release.get("body", "")[:2000]
            title = f"{repo.split('/')[1]} {tag} — {name}"

            analysis = analyze_with_gemini(title, body, rel_url, rc["category"])
            if not analysis:
                analysis = {
                    "titulo":    title[:120],
                    "resumen":   f"Nueva versión {tag} de {repo.split('/')[1]}. {body[:200]}",
                    "categoria": rc["category"],
                    "tipo":      "Open Source",
                    "relevancia":"Media",
                    "tags":      [],
                }

            analysis["url"]             = rel_url
            analysis["fuente_original"] = "GitHub"
            results.append(analysis)
            log.info(f"  ✅ [{analysis.get('relevancia','?')}] {analysis.get('titulo','')[:75]}")
            time.sleep(1.5)

    return results


# ── Notion ────────────────────────────────────────────────────────────────────
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": "2022-06-28",
}
VALID_TAGS = {"LLM","Vision","Audio","Video","Image","RAG","Agent","Multimodal","ComfyUI","Diffusion","SOTA"}
CAT_MAP = {
    "Foundation Model":"Foundation Model", "Tool":"Tool", "Paper":"Paper",
    "Community":"Community", "Image Gen":"Image Gen", "Video Gen":"Video Gen",
    "Audio":"Audio", "RAG":"RAG", "Agent":"Agent", "Update":"Update",
    "Workflow":"Tool", "Other":"Update", "Fine-tuning":"Update", "Benchmark":"Update",
}
SRC_MAP = {
    "ArXiv":"ArXiv", "Hugging Face":"Hugging Face", "GitHub":"GitHub",
    "Reddit":"Reddit", "OpenAI":"OpenAI", "Anthropic":"Anthropic",
    "DeepMind":"DeepMind", "Meta AI":"Meta AI", "ComfyUI":"ComfyUI",
    "Newsletter":"Newsletter", "Blog":"Other", "Other":"Other",
}

def page_exists_in_notion(url: str) -> bool:
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query",
            headers=NOTION_HEADERS,
            json={"filter": {"property": "URL", "url": {"equals": url}}},
            timeout=10,
        )
        return r.status_code == 200 and len(r.json().get("results", [])) > 0
    except Exception:
        return False

def create_notion_page(item: dict) -> bool:
    tags  = [t for t in item.get("tags", []) if t in VALID_TAGS]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    props = {
        "Título":    {"title": [{"text": {"content": item.get("titulo","Sin título")[:200]}}]},
        "Categoría": {"select": {"name": CAT_MAP.get(item.get("categoria","Other"),"Update")}},
        "Tipo":      {"select": {"name": item.get("tipo","Community")}},
        "Relevancia":{"select": {"name": item.get("relevancia","Baja")}},
        "Fuente":    {"select": {"name": SRC_MAP.get(item.get("fuente_original","Other"),"Other")}},
        "Resumen":   {"rich_text": [{"text": {"content": item.get("resumen","")[:2000]}}]},
        "date:Fecha:start":       today,
        "date:Fecha:is_datetime": 0,
        "Leido":    {"checkbox": False},
        "Guardado": {"checkbox": False},
    }
    if item.get("url"):
        props["URL"] = {"url": item["url"]}
    if tags:
        props["Tags"] = {"multi_select": [{"name": t} for t in tags]}

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": NOTION_DATABASE_ID}, "properties": props},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        log.warning(f"Notion {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"Error Notion: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("🚀 AI Daily Bulletin — Free Edition (Gemini)")
    log.info(f"   Modelo   : {GEMINI_MODEL}")
    log.info(f"   Ventana  : últimas {HOURS_LOOKBACK}h | Max/feed: {MAX_PER_FEED}")
    log.info(f"   Notion DB: {NOTION_DATABASE_ID}")

    all_items: list[dict] = []

    log.info("\n📡 Procesando RSS feeds...")
    rss = process_rss_feeds()
    all_items.extend(rss)
    log.info(f"   → {len(rss)} items")

    log.info("\n🐙 Procesando GitHub releases...")
    gh = process_github_releases()
    all_items.extend(gh)
    log.info(f"   → {len(gh)} releases")

    # Ordenar Alta → Media → Baja
    order = {"Alta": 0, "Media": 1, "Baja": 2}
    all_items.sort(key=lambda x: order.get(x.get("relevancia", "Baja"), 2))

    log.info(f"\n📤 Publicando {len(all_items)} items en Notion...")
    published = skipped = 0

    for item in all_items:
        url = item.get("url", "")
        if url and page_exists_in_notion(url):
            skipped += 1
            continue
        published += 1 if create_notion_page(item) else 0
        time.sleep(0.4)

    log.info(f"\n✅ Listo — Publicados: {published} | Omitidos/duplicados: {skipped}")


if __name__ == "__main__":
    main()
