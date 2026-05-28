"""
AI Daily Bulletin — Versión 100% GRATUITA
- Rota feeds por día de la semana para no agotar la quota de Gemini
- Solo publica Alta y Media relevancia
- Publica en Notion inmediatamente tras analizar cada item
- sleep=5s entre llamadas → ~12 RPM (bajo el límite de 15 RPM free tier)
"""

import os, sys, json, time, hashlib, logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests

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
MAX_PER_FEED       = int(os.environ.get("MAX_PER_FEED", "3"))
GEMINI_MODEL       = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_URL         = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)
PUBLISH_RELEVANCIA = {"Alta", "Media"}
SLEEP_BETWEEN      = 5  # segundos entre llamadas Gemini → ~12 RPM

# ── Feeds organizados por grupo ───────────────────────────────────────────────
# Se procesan SIEMPRE (pocos items nuevos al día, bajo consumo de quota)
FEEDS_DAILY = [
    {"url": "https://huggingface.co/blog/feed.xml",       "source": "Hugging Face", "category": "Foundation Model"},
    {"url": "https://openai.com/blog/rss.xml",            "source": "OpenAI",       "category": "Foundation Model"},
    {"url": "https://www.anthropic.com/rss.xml",          "source": "Anthropic",    "category": "Foundation Model"},
    {"url": "https://mistral.ai/feed.xml",                "source": "Other",        "category": "Foundation Model"},
    {"url": "https://simonwillison.net/atom/everything/", "source": "Blog",         "category": "Tool"},
    {"url": "https://www.reddit.com/r/LocalLLaMA/.rss?limit=5&sort=hot",  "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/singularity/.rss?limit=5&sort=hot", "source": "Reddit", "category": "Community"},
]

# Se rotan — cada grupo se procesa 2 veces por semana
FEEDS_ROTATION = [
    # Lunes y Jueves — Papers
    [
        {"url": "https://rss.arxiv.org/rss/cs.AI", "source": "ArXiv", "category": "Paper"},
        {"url": "https://rss.arxiv.org/rss/cs.LG", "source": "ArXiv", "category": "Paper"},
        {"url": "https://rss.arxiv.org/rss/cs.CL", "source": "ArXiv", "category": "Paper"},
        {"url": "https://rss.arxiv.org/rss/cs.CV", "source": "ArXiv", "category": "Paper"},
    ],
    # Martes y Viernes — Imagen / Video / Audio
    [
        {"url": "https://www.reddit.com/r/StableDiffusion/.rss?limit=5&sort=hot", "source": "Reddit", "category": "Image Gen"},
        {"url": "https://www.reddit.com/r/comfyui/.rss?limit=5&sort=hot",         "source": "Reddit", "category": "Image Gen"},
        {"url": "https://www.reddit.com/r/FluxAI/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Image Gen"},
        {"url": "https://www.reddit.com/r/aivideo/.rss?limit=5&sort=hot",         "source": "Reddit", "category": "Video Gen"},
        {"url": "https://www.reddit.com/r/AIMusic/.rss?limit=5&sort=hot",         "source": "Reddit", "category": "Audio"},
    ],
    # Miércoles y Sábado — Dev / Tools / Agentes
    [
        {"url": "https://blog.langchain.dev/rss/",                                "source": "Blog",   "category": "Workflow"},
        {"url": "https://www.llamaindex.ai/blog/rss.xml",                         "source": "Blog",   "category": "Workflow"},
        {"url": "https://www.reddit.com/r/MachineLearning/.rss?limit=5&sort=hot", "source": "Reddit", "category": "Community"},
        {"url": "https://www.reddit.com/r/ollama/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Tool"},
        {"url": "https://hnrss.org/newest?q=LLM+AI+agent&points=100",            "source": "Other",  "category": "Agent"},
    ],
    # Domingo — Revisión general
    [
        {"url": "https://hnrss.org/newest?q=stable+diffusion+comfyui&points=50", "source": "Other", "category": "Image Gen"},
        {"url": "https://hnrss.org/newest?q=LLM+language+model&points=100",      "source": "Other", "category": "Community"},
    ],
]

# Mapa día de semana → índice de grupo (0=Lun, 6=Dom)
DAY_TO_GROUP = {0: 0, 1: 1, 2: 2, 3: 0, 4: 1, 5: 2, 6: 3}

# ── GitHub Releases ───────────────────────────────────────────────────────────
GITHUB_REPOS = [
    {"repo": "comfyanonymous/ComfyUI",              "category": "Image Gen",        "source": "GitHub"},
    {"repo": "ollama/ollama",                        "category": "Tool",             "source": "GitHub"},
    {"repo": "ggml-org/llama.cpp",                   "category": "Foundation Model", "source": "GitHub"},
    {"repo": "huggingface/transformers",             "category": "Foundation Model", "source": "GitHub"},
    {"repo": "LangChain-ai/langchain",               "category": "Workflow",         "source": "GitHub"},
    {"repo": "black-forest-labs/flux",               "category": "Image Gen",        "source": "GitHub"},
    {"repo": "unslothai/unsloth",                    "category": "Update",           "source": "GitHub"},
    {"repo": "microsoft/autogen",                    "category": "Agent",            "source": "GitHub"},
    {"repo": "BerriAI/litellm",                      "category": "Tool",             "source": "GitHub"},
    {"repo": "run-llama/llama_index",                "category": "Workflow",         "source": "GitHub"},
    {"repo": "Wan-Video/Wan2.1",                     "category": "Video Gen",        "source": "GitHub"},
    {"repo": "AUTOMATIC1111/stable-diffusion-webui", "category": "Image Gen",        "source": "GitHub"},
]

GITHUB_HEADERS = {"Accept": "application/vnd.github+json"}
if os.environ.get("GITHUB_TOKEN"):
    GITHUB_HEADERS["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

# ── Gemini ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un curador experto en AI/ML con criterio MUY estricto.
Devuelve ÚNICAMENTE JSON válido, sin texto extra, sin bloques markdown.

{
  "titulo": "string conciso en español (máx 120 chars)",
  "resumen": "2-3 oraciones en español: qué es, por qué importa y qué cambia",
  "categoria": "Foundation Model | Tool | Paper | Community | Image Gen | Video Gen | Audio | RAG | Agent | Update | Other",
  "tipo": "Open Source | Closed | Research | Community | Update",
  "relevancia": "Alta | Media | Baja",
  "tags": ["LLM","Vision","Audio","Video","Image","RAG","Agent","Multimodal","ComfyUI","Diffusion","SOTA"]
}

CRITERIOS ESTRICTOS:

🔴 Alta — SOLO estos casos:
  • Lanzamiento de modelo fundacional (GPT-5, Gemini 3, LLaMA 4, Claude 4, Flux 2, Wan 3...)
  • Paper que rompe benchmark SOTA de forma significativa
  • Herramienta que cambia el paradigma (como ComfyUI, LangChain, MCP, LoRA cuando salieron)
  • Release MAYOR con features nuevas importantes
  • Evento de impacto real: primera película con IA, robot operacional, regulación, descubrimiento científico con IA

⚡ Media — Útil pero no urgente:
  • Actualización menor con mejoras reales
  • Paper con idea nueva aunque no sea SOTA
  • Modelo open source que compite bien con los cerrados
  • Nodo/extensión relevante para ComfyUI o workflows

⬇️ Baja — La MAYORÍA cae aquí (sé estricto):
  • Opiniones, debates, predicciones, memes
  • Patches menores (v1.2.3 → v1.2.4) sin features
  • Posts de Reddit con preguntas o discusiones generales
  • Noticias repetidas
  • Contenido de marketing"""


def analyze_with_gemini(title: str, content: str, url: str, suggested_cat: str) -> Optional[dict]:
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Título: {title}\nURL: {url}\n"
        f"Categoría sugerida: {suggested_cat}\n"
        f"Contenido: {content[:2000]}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400},
    }
    for attempt in range(3):
        try:
            r = requests.post(GEMINI_URL, json=payload, timeout=30)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                log.warning(f"Rate limit — esperando {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                log.warning(f"Gemini {r.status_code}: {r.text[:100]}")
                return None
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if "```" in raw:
                for chunk in raw.split("```"):
                    chunk = chunk.strip().lstrip("json").strip()
                    if chunk.startswith("{"):
                        raw = chunk
                        break
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
        except requests.RequestException as e:
            log.warning(f"Red error (intento {attempt+1}): {e}")
            time.sleep(5)
    return None


# ── Notion ────────────────────────────────────────────────────────────────────
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Content-Type":   "application/json",
    "Notion-Version": "2022-06-28",
}
VALID_TAGS = {"LLM","Vision","Audio","Video","Image","RAG","Agent","Multimodal","ComfyUI","Diffusion","SOTA"}
CAT_MAP = {
    "Foundation Model":"Foundation Model","Tool":"Tool","Paper":"Paper",
    "Community":"Community","Image Gen":"Image Gen","Video Gen":"Video Gen",
    "Audio":"Audio","RAG":"RAG","Agent":"Agent","Update":"Update",
    "Workflow":"Tool","Other":"Update","Fine-tuning":"Update","Benchmark":"Update",
}
SRC_MAP = {
    "ArXiv":"ArXiv","Hugging Face":"Hugging Face","GitHub":"GitHub",
    "Reddit":"Reddit","OpenAI":"OpenAI","Anthropic":"Anthropic",
    "DeepMind":"DeepMind","Meta AI":"Meta AI","ComfyUI":"ComfyUI",
    "Newsletter":"Newsletter","Blog":"Other","Other":"Other",
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
        "Fecha":     {"date": {"start": today}},
        "Leido":     {"checkbox": False},
        "Guardado":  {"checkbox": False},
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


# ── Core: analizar → filtrar → publicar ──────────────────────────────────────
def process_and_publish(title: str, content: str, url: str,
                        source: str, category: str, stats: dict) -> None:
    if already_seen(url):
        return
    if page_exists_in_notion(url):
        log.info(f"  ⏭  Ya existe: {title[:55]}")
        stats["skipped"] += 1
        return

    analysis = analyze_with_gemini(title, content, url, category)
    if not analysis:
        stats["errors"] += 1
        return

    relevancia = analysis.get("relevancia", "Baja")

    if relevancia not in PUBLISH_RELEVANCIA:
        log.info(f"  🔕 [{relevancia}] {title[:60]}")
        stats["filtered"] += 1
        return

    analysis["url"]             = url
    analysis["fuente_original"] = source

    ok = create_notion_page(analysis)
    if ok:
        log.info(f"  ✅ [{relevancia}] {analysis.get('titulo','')[:70]}")
        stats["published"] += 1
    else:
        stats["errors"] += 1


# ── RSS ───────────────────────────────────────────────────────────────────────
def process_feeds(feeds: list, stats: dict) -> None:
    for fc in feeds:
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
            if not entry_url:
                continue
            content = entry.get("summary", "") or entry.get("description", "") or ""
            title   = entry.get("title", "Sin título")
            process_and_publish(title, content, entry_url, fc["source"], fc["category"], stats)
            count += 1
            time.sleep(SLEEP_BETWEEN)


# ── GitHub ────────────────────────────────────────────────────────────────────
def process_github_releases(stats: dict) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    for rc in GITHUB_REPOS:
        repo = rc["repo"]
        log.info(f"🐙 {repo}")
        try:
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=2",
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
            if not rel_url:
                continue
            tag   = release.get("tag_name", "")
            name  = release.get("name", "") or tag
            body  = release.get("body", "")[:1500]
            title = f"{repo.split('/')[1]} {tag} — {name}"
            process_and_publish(title, body, rel_url, "GitHub", rc["category"], stats)
            time.sleep(SLEEP_BETWEEN)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today     = datetime.now(timezone.utc)
    weekday   = today.weekday()  # 0=Lun, 6=Dom
    day_names = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    group_idx = DAY_TO_GROUP[weekday]
    rotation_feeds = FEEDS_ROTATION[group_idx]

    total_feeds = len(FEEDS_DAILY) + len(rotation_feeds)
    total_items_max = total_feeds * MAX_PER_FEED

    log.info("🚀 AI Daily Bulletin — Free Edition (Gemini)")
    log.info(f"   Modelo      : {GEMINI_MODEL}")
    log.info(f"   Ventana     : últimas {HOURS_LOOKBACK}h | Max/feed: {MAX_PER_FEED}")
    log.info(f"   Día         : {day_names[weekday]} → Grupo de rotación #{group_idx}")
    log.info(f"   Feeds hoy   : {len(FEEDS_DAILY)} fijos + {len(rotation_feeds)} rotación = {total_feeds} total")
    log.info(f"   Items máx   : ~{total_items_max} → aprox. {total_items_max * SLEEP_BETWEEN // 60} min de ejecución")
    log.info(f"   Filtro      : Solo publica {PUBLISH_RELEVANCIA}\n")

    stats = {"published": 0, "filtered": 0, "skipped": 0, "errors": 0}

    log.info("📌 Feeds fijos (diarios)...")
    process_feeds(FEEDS_DAILY, stats)

    log.info(f"\n🔄 Feeds de rotación ({day_names[weekday]})...")
    process_feeds(rotation_feeds, stats)

    log.info("\n🐙 GitHub releases...")
    process_github_releases(stats)

    log.info(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Publicados en Notion : {stats['published']}
🔕 Filtrados (Baja)     : {stats['filtered']}
⏭  Ya existían          : {stats['skipped']}
❌ Errores              : {stats['errors']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")


if __name__ == "__main__":
    main()