"""
AI Daily Bulletin — Versión 100% GRATUITA
- Publica en Notion inmediatamente después de analizar cada item
- Filtra automáticamente: solo publica relevancia Alta y Media
- Gemini con criterio estricto de curación

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
MAX_PER_FEED       = int(os.environ.get("MAX_PER_FEED", "3"))
GEMINI_MODEL       = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_URL         = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

# Solo publica estos niveles — cambia a ["Alta"] si quieres ser aún más estricto
PUBLISH_RELEVANCIA = {"Alta", "Media"}

# ── Fuentes RSS ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"url": "https://rss.arxiv.org/rss/cs.AI",  "source": "ArXiv", "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.LG",  "source": "ArXiv", "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.CV",  "source": "ArXiv", "category": "Paper"},
    {"url": "https://rss.arxiv.org/rss/cs.CL",  "source": "ArXiv", "category": "Paper"},
    {"url": "https://huggingface.co/blog/feed.xml",        "source": "Hugging Face", "category": "Foundation Model"},
    {"url": "https://simonwillison.net/atom/everything/",   "source": "Blog",         "category": "Tool"},
    {"url": "https://blog.langchain.dev/rss/",              "source": "Blog",         "category": "Workflow"},
    {"url": "https://www.llamaindex.ai/blog/rss.xml",       "source": "Blog",         "category": "Workflow"},
    {"url": "https://openai.com/blog/rss.xml",    "source": "OpenAI",    "category": "Foundation Model"},
    {"url": "https://www.anthropic.com/rss.xml",  "source": "Anthropic", "category": "Foundation Model"},
    {"url": "https://mistral.ai/feed.xml",        "source": "Other",     "category": "Foundation Model"},
    {"url": "https://www.reddit.com/r/LocalLLaMA/.rss?limit=10&sort=hot",      "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/MachineLearning/.rss?limit=10&sort=hot", "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/StableDiffusion/.rss?limit=10&sort=hot", "source": "Reddit", "category": "Image Gen"},
    {"url": "https://www.reddit.com/r/comfyui/.rss?limit=10&sort=hot",         "source": "Reddit", "category": "Image Gen"},
    {"url": "https://www.reddit.com/r/singularity/.rss?limit=10&sort=hot",     "source": "Reddit", "category": "Community"},
    {"url": "https://www.reddit.com/r/aivideo/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Video Gen"},
    {"url": "https://www.reddit.com/r/AIMusic/.rss?limit=5&sort=hot",          "source": "Reddit", "category": "Audio"},
    {"url": "https://www.reddit.com/r/ollama/.rss?limit=5&sort=hot",           "source": "Reddit", "category": "Tool"},
    {"url": "https://www.reddit.com/r/FluxAI/.rss?limit=5&sort=hot",           "source": "Reddit", "category": "Image Gen"},
    {"url": "https://hnrss.org/newest?q=LLM+language+model&points=100",       "source": "Other", "category": "Community"},
    {"url": "https://hnrss.org/newest?q=stable+diffusion+comfyui&points=50",  "source": "Other", "category": "Image Gen"},
    {"url": "https://hnrss.org/newest?q=AI+agent+RAG&points=100",             "source": "Other", "category": "Agent"},
]

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

# ── Gemini — Prompt con criterio estricto de curación ────────────────────────
SYSTEM_PROMPT = """Eres un curador experto en AI/ML con criterio MUY estricto.
Tu trabajo es separar lo verdaderamente importante del ruido diario.
Devuelve ÚNICAMENTE JSON válido, sin texto extra, sin bloques markdown.

Estructura exacta:
{
  "titulo": "string conciso en español (máx 120 chars)",
  "resumen": "2-3 oraciones en español: qué es, por qué importa y qué cambia",
  "categoria": "Foundation Model | Tool | Paper | Community | Image Gen | Video Gen | Audio | RAG | Agent | Update | Other",
  "tipo": "Open Source | Closed | Research | Community | Update",
  "relevancia": "Alta | Media | Baja",
  "tags": ["LLM","Vision","Audio","Video","Image","RAG","Agent","Multimodal","ComfyUI","Diffusion","SOTA"]
}

━━━ CRITERIOS DE RELEVANCIA (sé muy estricto) ━━━

🔴 Alta — Solo estos casos merecen Alta:
  • Lanzamiento de modelo fundacional nuevo (GPT-5, Gemini 3, LLaMA 4, Claude 4, Mistral Large, Flux 2, Wan 3, etc.)
  • Paper que rompe un benchmark SOTA de forma significativa (>5% mejora en métricas clave)
  • Herramienta o tecnología que cambia el paradigma de trabajo (como cuando salió ComfyUI, LangChain, MCP, LoRA, GGUF)
  • Release MAYOR de herramienta clave con features importantes (ComfyUI 2.0, Ollama con multimodal, etc.)
  • Evento de impacto real en el mundo: primera película hecha con IA, robot humanoide operacional, regulación importante de IA
  • Descubrimiento científico asistido por IA (proteínas, medicamentos, física)
  • Hito de capacidad: IA supera a humanos en tarea nueva importante

⚡ Media — Útil pero no urgente:
  • Actualización menor de herramienta conocida con mejoras reales
  • Paper interesante con idea nueva aunque no sea SOTA
  • Tutorial o recurso excepcionalmente útil y práctico
  • Nuevo modelo open source que compite bien con los cerrados
  • Nodo o extensión relevante para ComfyUI/workflows

⬇️ Baja — La MAYORÍA del contenido cae aquí:
  • Opiniones, debates filosóficos, predicciones
  • Papers muy técnicos y específicos sin impacto práctico inmediato
  • Releases de versiones patch (v1.2.3 → v1.2.4) sin features nuevas
  • Posts de Reddit que son preguntas, memes o discusiones generales
  • Noticias repetidas que ya cubrieron otras fuentes
  • Contenido de marketing o promocional"""


def analyze_with_gemini(title: str, content: str, url: str, suggested_cat: str) -> Optional[dict]:
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Analiza este contenido:\n"
        f"Título: {title}\n"
        f"URL: {url}\n"
        f"Categoría sugerida: {suggested_cat}\n"
        f"Contenido: {content[:2500]}"
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
        log.warning(f"Notion {r.status_code}: {r.text[:300]}")
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


# ── Procesar y publicar en tiempo real ───────────────────────────────────────
def process_and_publish(title: str, content: str, url: str,
                        source: str, category: str,
                        stats: dict) -> None:
    """Analiza con Gemini → filtra por relevancia → publica en Notion al instante."""
    if already_seen(url):
        return

    if page_exists_in_notion(url):
        log.info(f"  ⏭  Ya existe en Notion: {title[:55]}")
        stats["skipped"] += 1
        return

    analysis = analyze_with_gemini(title, content, url, category)
    if not analysis:
        stats["errors"] += 1
        return

    relevancia = analysis.get("relevancia", "Baja")

    # ── FILTRO PRINCIPAL: descartar Baja relevancia ──
    if relevancia not in PUBLISH_RELEVANCIA:
        log.info(f"  🔕 [{relevancia}] Descartado: {title[:60]}")
        stats["filtered"] += 1
        return

    analysis["url"]             = url
    analysis["fuente_original"] = source

    ok = create_notion_page(analysis)
    if ok:
        log.info(f"  ✅ [{relevancia}] {analysis.get('titulo','')[:70]}")
        stats["published"] += 1
    else:
        log.warning(f"  ❌ Error Notion para: {title[:55]}")
        stats["errors"] += 1


# ── RSS Processing ────────────────────────────────────────────────────────────
def process_rss_feeds(stats: dict) -> None:
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
            if not entry_url:
                continue

            content = entry.get("summary", "") or entry.get("description", "") or ""
            title   = entry.get("title", "Sin título")

            process_and_publish(title, content, entry_url,
                                fc["source"], fc["category"], stats)
            count += 1
            time.sleep(4)  # ~15 RPM — respeta free tier Gemini


# ── GitHub Processing ─────────────────────────────────────────────────────────
def process_github_releases(stats: dict) -> None:
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
            if not rel_url:
                continue

            tag   = release.get("tag_name", "")
            name  = release.get("name", "") or tag
            body  = release.get("body", "")[:2000]
            title = f"{repo.split('/')[1]} {tag} — {name}"

            process_and_publish(title, body, rel_url,
                                "GitHub", rc["category"], stats)
            time.sleep(4)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("🚀 AI Daily Bulletin — Free Edition (Gemini)")
    log.info(f"   Modelo      : {GEMINI_MODEL}")
    log.info(f"   Ventana     : últimas {HOURS_LOOKBACK}h | Max/feed: {MAX_PER_FEED}")
    log.info(f"   Notion DB   : {NOTION_DATABASE_ID}")
    log.info(f"   Filtro      : Solo publica relevancia {PUBLISH_RELEVANCIA}")
    log.info(f"   Publicación : Inmediata (item por item)\n")

    stats = {"published": 0, "filtered": 0, "skipped": 0, "errors": 0}

    log.info("📡 Procesando RSS feeds...")
    process_rss_feeds(stats)

    log.info("\n🐙 Procesando GitHub releases...")
    process_github_releases(stats)

    log.info(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Publicados en Notion : {stats['published']}
🔕 Filtrados (Baja)     : {stats['filtered']}
⏭  Ya existían          : {stats['skipped']}
❌ Errores              : {stats['errors']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━""")


if __name__ == "__main__":
    main()
