# 🤖 AI Daily Bulletin — Free Edition

Boletín diario de AI/ML/GenAI completamente **gratuito**.  
Usa **Gemini Flash-Lite** (Google AI Studio) en lugar de Claude API.

## 💰 Costo: $0

| Servicio | Límite gratis | Uso del boletín |
|---|---|---|
| **Gemini 2.5 Flash-Lite** | 1,000 req/día | ~80-120 req/día ✅ |
| **Gemini 2.5 Flash** | 250 req/día | ~80-120 req/día ✅ |
| **GitHub Actions** | 2,000 min/mes | ~5-10 min/día ✅ |
| **Notion API** | Ilimitado | ✅ |

> ⚠️ Nota: En el free tier de Google AI Studio, tus prompts pueden usarse
> para mejorar los modelos de Google. Si eso te preocupa, usa el tier de pago
> (~$0.10/día con Flash-Lite) o Claude API (~$0.18/día con Haiku).

## 🚀 Setup en 4 pasos

### 1. Obtén tu Gemini API Key (gratis, sin tarjeta)

1. Ve a **https://aistudio.google.com**
2. Inicia sesión con tu cuenta de Google
3. Haz clic en **"Get API Key"** → **"Create API key"**
4. Copia la key (empieza con `AIza...`)

### 2. Obtén tu Notion Integration Token

1. Ve a **https://www.notion.so/my-integrations**
2. **New Integration** → nombre: "AI Bulletin" → Submit
3. Copia el **"Internal Integration Token"** (`secret_...`)
4. Abre tu base de datos `AI News Feed` en Notion
5. Clic en **···** (arriba derecha) → **Connections** → conecta "AI Bulletin"

### 3. Crea el repositorio en GitHub

1. Crea un repo nuevo en GitHub (puede ser privado)
2. Sube los 4 archivos respetando esta estructura:
```
tu-repo/
├── ai_daily_bulletin.py
├── requirements.txt
└── .github/
    └── workflows/
        └── daily_bulletin.yml
```

### 4. Agrega los Secrets

Ve a tu repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|---|---|
| `GEMINI_API_KEY` | `AIza...` (de Google AI Studio) |
| `NOTION_TOKEN` | `secret_...` (de Notion) |
| `NOTION_DATABASE_ID` | `0916313650de4b1e945857fe95734269` |

> `GITHUB_TOKEN` se agrega automáticamente por GitHub Actions — no necesitas crear uno.

### Primera ejecución

1. **Actions** → `🤖 AI Daily Bulletin (Free)` → **Run workflow**
2. En "Horas hacia atrás" pon `168` (7 días) para la primera corrida
3. Revisa los logs — deberías ver items publicándose en tiempo real
4. Abre tu Notion y verifica que aparecen las entradas

Desde ese momento **corre solo cada día a las 8 AM hora CDMX** ☕

---

## ⚙️ Personalización

### Cambiar el horario
En `.github/workflows/daily_bulletin.yml`:
```yaml
# 8 AM CDMX todos los días (actual)
- cron: "0 14 * * *"

# Solo lunes a viernes
- cron: "0 14 * * 1-5"

# Dos veces al día (8 AM y 2 PM CDMX)
- cron: "0 14,20 * * *"
```

### Elegir modelo Gemini
Al ejecutar manualmente puedes elegir entre:
- `gemini-2.5-flash-lite-preview-06-17` — **1,000 req/día gratis** ← default
- `gemini-2.5-flash` — **250 req/día gratis**, mejor calidad de resúmenes

### Agregar feeds RSS
En `ai_daily_bulletin.py`, añade a `RSS_FEEDS`:
```python
{"url": "https://tu-feed.com/rss", "source": "Nombre", "category": "Tool"},
```

### Agregar repos de GitHub
En `GITHUB_REPOS`:
```python
{"repo": "owner/repo", "category": "Tool", "source": "GitHub"},
```

---

## 🔧 Solución de problemas

**Error 429 de Gemini (rate limit):**
- El script ya maneja esto automáticamente con reintentos
- Si pasa mucho, reduce `MAX_PER_FEED` a 3

**No aparece nada en Notion:**
- Verifica que la integración esté conectada a la DB (paso 2.5)
- Confirma el `NOTION_DATABASE_ID` correcto
- Revisa los logs de GitHub Actions

**El modelo Gemini no existe:**
- Los nombres de modelos de Google cambian frecuentemente
- Ve a https://aistudio.google.com y busca el nombre actual del modelo Flash-Lite
- Actualiza `GEMINI_MODEL` en el workflow o en el script

---

## 📁 Archivos

```
ai-daily-bulletin/
├── ai_daily_bulletin.py          ← Script principal (Gemini + Notion)
├── requirements.txt               ← Solo 2 dependencias: feedparser + requests
├── README.md                      ← Este archivo
└── .github/
    └── workflows/
        └── daily_bulletin.yml     ← GitHub Actions: cron diario
```
