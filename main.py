import os
import re
import time
import json
import urllib.parse
import urllib.request
import feedparser
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from google import genai

# 1. Налаштування Gemini API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_KEY:
    print("Помилка: GEMINI_API_KEY не знайдено в Secrets.")
    exit(1)

client = genai.Client(api_key=GEMINI_KEY)

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
]

INCIDENTS_FILE = "incidents.json"
KYIV_TZ = timezone(timedelta(hours=2))
RECENT_WINDOW_HOURS = 48  # Сьогодні та вчора (останні 48 годин)

# 2. Пошукові запити для Google News RSS (тільки новинні сайти через Google News)
SEARCH_QUERIES = [
    'стадіон OR спорткомплекс OR басейн пошкоджено OR зруйновано OR обстріл',
    'спортзал OR "палац спорту" OR спортшкола пошкоджено OR зруйновано OR обстріл',
    'ДЮСШ OR арена OR "спортивний майданчик" пошкоджено OR зруйновано OR обстріл',
    'стадіон OR спорткомплекс OR басейн "внаслідок атаки" OR "ракетного обстрілу"',
    'спортшкола OR ДЮСШ OR арена "внаслідок атаки" OR "ракетного обстрілу"',
    '"палац спорту" OR "локомотив" Харків пошкоджено OR зруйновано OR атака',
]

# Ключові слова для попередньої перевірки спортивної інфраструктури
SPORT_KEYWORDS = [
    "стадіон",
    "спорткомплекс",
    "спортивний комплекс",
    "палац спорту",
    "спортшкола",
    "дюсьш",
    "сдюшор",
    "спортзал",
    "басейн",
    "арена",
    "спортивний майданчик",
    "локомотив",
]


def load_incidents(filepath: str = INCIDENTS_FILE) -> list:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Помилка читання {filepath}: {e}")
        return []


def save_incidents(filepath: str, incidents: list) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(incidents, f, ensure_ascii=False, indent=2)


def parse_pub_datetime_utc(published_str: str):
    if not published_str or published_str == "Дата не вказана":
        return None
    try:
        dt = parsedate_to_datetime(published_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def format_pub_date_kyiv(published_str: str) -> str:
    dt_utc = parse_pub_datetime_utc(published_str)
    if dt_utc is None:
        return published_str or "Дата не вказана"
    dt_kyiv = dt_utc.astimezone(KYIV_TZ)
    return dt_kyiv.strftime("%d.%m.%Y о %H:%M")


def is_today_or_yesterday(published_str: str, hours: int = RECENT_WINDOW_HOURS) -> bool:
    dt_utc = parse_pub_datetime_utc(published_str)
    if dt_utc is None:
        return False
    now_utc = datetime.now(timezone.utc)
    return (now_utc - dt_utc) <= timedelta(hours=hours)


def matches_sport_keywords(text: str) -> bool:
    low = (text or "").lower()
    return any(kw in low for kw in SPORT_KEYWORDS)


def get_google_news() -> list:
    articles = []
    seen_links = set()

    for query in SEARCH_QUERIES:
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=uk&gl=UA&ceid=UA:uk"
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:12]:
            link = getattr(entry, "link", "")
            title = getattr(entry, "title", "Без заголовка")
            published_raw = getattr(entry, "published", "Дата не вказана")

            if not link or link in seen_links:
                continue
            if not matches_sport_keywords(title):
                continue

            seen_links.add(link)
            source_title = ""
            if hasattr(entry, "source") and getattr(entry, "source"):
                source_title = getattr(entry.source, "title", "") or ""

            articles.append({
                "title": title,
                "link": link,
                "published_kyiv": format_pub_date_kyiv(published_raw),
                "is_recent": is_today_or_yesterday(published_raw),
                "source": source_title or "Новинне джерело",
            })
    return articles


def _clean_json_text(raw_text: str) -> str:
    cleaned = (raw_text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def analyze_articles(articles: list, existing_incidents: list) -> dict:
    if not articles:
        return {"new_incidents": [], "extra_sources": []}

    compact_existing = []
    for item in existing_incidents[-200:]:
        compact_existing.append({
            "date": item.get("date", ""),
            "region_city": item.get("region_city", ""),
            "facility": item.get("facility", ""),
            "description": item.get("description", ""),
            "sources": item.get("sources", [item.get("link", "")] if item.get("link") else []),
        })

    prompt = f"""
Ти аналітик, який моніторить виключно руйнування та пошкодження СПОРТИВНОЇ ІНФРАСТРУКТУРИ в Україні внаслідок війни.
Твоє завдання:
1. Проаналізувати список новин і залишити ТІЛЬКИ підтверджені випадки руйнування або пошкодження спортивних об'єктів (стадіони, спорткомплекси, басейни, ДЮСШ, СДЮШОР, спортшколи, спортзали, палаци спорту, спортивні арени, майданчики). Музеї, університети, житлові будинки без підтвердженого пошкодження саме спортивного об'єкта — ІГНОРУЙ.
2. Звір кожну спортивну подію зі списком УЖЕ ЗАФІКСОВАНИХ ПОДІЙ нижче:
   - Якщо такий об'єкт і подія ВЖЕ є в базі (наприклад, Палац спорту «Локомотив» у Харкові вже є у списку), НЕ додавай її до "new_incidents". Якщо посилання немає у "sources" цієї події — додай його в "extra_sources".
   - Якщо подія НОВА і ще не зафіксована у базі — додай її до "new_incidents".

Поверни відповідь ВИКЛЮЧНО у форматі валідного JSON-об'єкта без зайвого тексту до або після JSON:
{{
  "new_incidents": [
    {{
      "date": "дата та час публікації новини",
      "region_city": "область та населений пункт",
      "facility": "назва або тип спортивного об'єкта (без зірочок **)",
      "description": "короткий опис пошкоджень (1-2 речення, без зірочок **)",
      "source_name": "коротка назва медіа/джерела",
      "link": "точне посилання зі списку новин",
      "is_recent": true
    }}
  ],
  "extra_sources": [
    {{
      "match_facility": "назва спортивного об'єкта з бази, до якого належить новина",
      "match_city": "місто/область з бази",
      "source_name": "коротка назва нового медіа/джерела",
      "link": "точне нове посилання"
    }}
  ]
}}

ВЖЕ ЗАФІКСОВАНІ ПОДІЇ:
{json.dumps(compact_existing, ensure_ascii=False)}

НОВИНИ ДЛЯ АНАЛІЗУ:
"""

    for idx, item in enumerate(articles, 1):
        prompt += (
            f"\n{idx}. Заголовок: {item['title']}\n"
            f"   Дата публікації: {item['published_kyiv']}\n"
            f"   Свіжа новина (сьогодні/вчора): {'true' if item['is_recent'] else 'false'}\n"
            f"   Джерело: {item['source']}\n"
            f"   Посилання: {item['link']}\n"
        )

    for model_name in MODELS:
        print(f"Пробуємо модель: {model_name}...")
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw = _clean_json_text(response.text)
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    valid_new = []
                    for entry in parsed.get("new_incidents", []):
                        if isinstance(entry, dict) and entry.get("facility") and entry.get("link"):
                            raw_recent = entry.get("is_recent", False)
                            is_rec = raw_recent is True or str(raw_recent).lower() == "true"
                            link_val = str(entry.get("link", "")).strip()
                            src_name = str(entry.get("source_name", "Джерело")).replace("*", "").strip()
                            valid_new.append({
                                "date": str(entry.get("date", "Дата не вказана")).replace("*", "").strip(),
                                "region_city": str(entry.get("region_city", "Не вказано")).replace("*", "").strip(),
                                "facility": str(entry.get("facility", "Спортивний об'єкт")).replace("*", "").strip(),
                                "description": str(entry.get("description", "")).replace("*", "").strip(),
                                "source_name": src_name,
                                "link": link_val,
                                "sources": [{"source_name": src_name, "link": link_val}] if link_val else [],
                                "is_recent": is_rec,
                            })

                    valid_extra = []
                    for ex in parsed.get("extra_sources", []):
                        if isinstance(ex, dict) and ex.get("link"):
                            valid_extra.append({
                                "match_facility": str(ex.get("match_facility", "")).replace("*", "").strip(),
                                "match_city": str(ex.get("match_city", "")).replace("*", "").strip(),
                                "source_name": str(ex.get("source_name", "Джерело")).replace("*", "").strip(),
                                "link": str(ex.get("link", "")).strip(),
                            })

                    return {"new_incidents": valid_new, "extra_sources": valid_extra}
                return {"new_incidents": [], "extra_sources": []}
            except Exception as e:
                print(f"Помилка {model_name} (спроба {attempt + 1}/2): {e}")
                if attempt == 0:
                    time.sleep(60)
        print(f"Модель {model_name} не відповідає, переходимо до наступної.\n")

    print("Помилка: жодна модель не змогла повернути коректний результат.")
    return {"new_incidents": [], "extra_sources": []}


def merge_extra_sources_into_db(existing_incidents: list, extra_sources: list) -> int:
    added_count = 0
    for ex in extra_sources:
        target_facility = ex.get("match_facility", "").lower()
        target_city = ex.get("match_city", "").lower()
        new_link = ex.get("link", "").strip()
        new_src_name = ex.get("source_name", "Джерело").strip()
        if not new_link:
            continue

        for inc in existing_incidents:
            inc_fac = str(inc.get("facility", "")).lower()
            inc_city = str(inc.get("region_city", "")).lower()
            fac_match = target_facility and (target_facility in inc_fac or inc_fac in target_facility)
            city_match = not target_city or (target_city in inc_city or inc_city in target_city)

            if fac_match and city_match:
                sources_list = inc.get("sources")
                if not isinstance(sources_list, list):
                    sources_list = []
                    if inc.get("link"):
                        sources_list.append({
                            "source_name": inc.get("source_name", "Джерело"),
                            "link": inc.get("link"),
                        })
                existing_links = {s.get("link") for s in sources_list if isinstance(s, dict)}
                if new_link not in existing_links:
                    sources_list.append({"source_name": new_src_name, "link": new_link})
                    inc["sources"] = sources_list
                    added_count += 1
                break
    return added_count


def format_telegram_message(recent_incidents: list) -> str:
    if not recent_incidents:
        return "Нових пошкоджень не зафіксовано"

    lines = ["Знайдено інформацію про руйнування", ""]
    for idx, inc in enumerate(recent_incidents, 1):
        date_str = _escape_html(inc.get("date", "Дата не вказана"))
        place_str = _escape_html(inc.get("region_city", "Не вказано"))
        facility_str = _escape_html(inc.get("facility", "Спортивний об'єкт"))
        desc_str = _escape_html(inc.get("description", ""))
        source_name = _escape_html(inc.get("source_name", "Джерело"))
        link = _escape_html(inc.get("link", ""))

        lines.append(f"{idx}. {place_str}")
        lines.append(f"Об'єкт: {facility_str}")
        lines.append(f"Дата та час публікації: {date_str}")
        if desc_str:
            lines.append(f"Опис: {desc_str}")
        if link:
            lines.append(f'Джерело: <a href="{link}">{source_name}</a>')
        lines.append("")

    msg = "\n".join(lines).strip()
    if len(msg) > 3950:
        msg = msg[:3920] + "\n\n..."
    return msg


def send_telegram_notification(message_html: str) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Пропуск відправки: Секрети TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID відсутні.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(payload_dict: dict) -> tuple[bool, str]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload_dict).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as response:
                body = response.read().decode("utf-8", errors="ignore")
                return True, f"HTTP {response.status}: {body}"
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            return False, f"HTTP {e.code}: {err_body}"
        except Exception as e:
            return False, str(e)

    ok, info = _post({
        "chat_id": chat_id,
        "text": message_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })

    if ok:
        print(f"Успішно відправлено сповіщення у Telegram! ({info})")
        return

    print(f"Помилка HTML-відправки в Telegram: {info}")
    plain_fallback = re.sub(r"<[^>]+>", "", message_html)
    ok_plain, info_plain = _post({
        "chat_id": chat_id,
        "text": plain_fallback,
        "disable_web_page_preview": True,
    })
    if ok_plain:
        print(f"Відправлено запасним текстовим форматом у Telegram! ({info_plain})")
    else:
        print(f"Помилка і запасного формату в Telegram: {info_plain}")


def build_light_dashboard_html(incidents: list, recent_count: int, updated_at: str) -> str:
    safe_incidents = []
    for idx, item in enumerate(reversed(incidents), 1):
        sources_raw = item.get("sources")
        normalized_sources = []
        if isinstance(sources_raw, list):
            for s in sources_raw:
                if isinstance(s, dict) and s.get("link"):
                    normalized_sources.append({
                        "source_name": str(s.get("source_name", "Джерело")).replace("*", "").strip(),
                        "link": str(s.get("link", "")).strip(),
                    })
        if not normalized_sources and item.get("link"):
            normalized_sources.append({
                "source_name": str(item.get("source_name", "Джерело")).replace("*", "").strip(),
                "link": str(item.get("link", "")).strip(),
            })

        safe_incidents.append({
            "id": idx,
            "date": str(item.get("date", "Дата не вказана")).replace("*", "").strip(),
            "region_city": str(item.get("region_city", "Не вказано")).replace("*", "").strip(),
            "facility": str(item.get("facility", "Спортивний об'єкт")).replace("*", "").strip(),
            "description": str(item.get("description", "")).replace("*", "").strip(),
            "is_recent": bool(item.get("is_recent", False)),
            "sources": normalized_sources,
        })

    embedded_json = json.dumps(safe_incidents, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sport Infra Monitor Ukraine — Моніторинг спортивної інфраструктури</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
    </style>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen flex flex-col">
    <!-- Світла шапка -->
    <header class="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div class="max-w-6xl mx-auto px-4 sm:px-8 py-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
                <div class="inline-flex items-center gap-2 bg-sky-50 text-sky-700 text-xs font-semibold px-3 py-1 rounded-full border border-sky-200">
                    <span class="w-2 h-2 rounded-full bg-sky-600"></span>
                    Моніторинг новинних сайтів
                </div>
                <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 mt-2">
                    Sport Infra Monitor Ukraine
                </h1>
                <p class="text-sm text-slate-500 mt-0.5">
                    Відкритий реєстр зафіксованих пошкоджень і руйнувань спортивної інфраструктури
                </p>
            </div>
            <div class="text-xs sm:text-sm text-slate-600 bg-slate-100 px-4 py-2.5 rounded-xl border border-slate-200">
                Оновлено: <span class="font-semibold text-slate-900">{_escape_html(updated_at)}</span>
            </div>
        </div>
    </header>

    <!-- Основний контент -->
    <main class="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-8 py-8 space-y-6">
        <!-- Показники -->
        <section class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs">
                <div class="text-xs font-medium uppercase tracking-wider text-slate-500">Усього в базі</div>
                <div class="text-3xl font-bold text-slate-900 mt-1.5">{len(safe_incidents)}</div>
                <div class="text-xs text-slate-500 mt-1">Зафіксованих записів без дублів</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs">
                <div class="text-xs font-medium uppercase tracking-wider text-slate-500">Нові (сьогодні / вчора)</div>
                <div class="text-3xl font-bold text-sky-700 mt-1.5">{recent_count}</div>
                <div class="text-xs text-slate-500 mt-1">Останні 48 годин</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs">
                <div class="text-xs font-medium uppercase tracking-wider text-slate-500">Статус останньої перевірки</div>
                <div class="text-base font-semibold text-emerald-700 mt-2">
                    {"Знайдено інформацію про руйнування" if recent_count > 0 else "Нових пошкоджень не зафіксовано"}
                </div>
                <div class="text-xs text-slate-500 mt-1">Автооновлення за розкладом</div>
            </div>
        </section>

        <!-- Пошук та фільтри -->
        <section class="bg-white border border-slate-200 rounded-2xl p-4 sm:p-5 shadow-xs flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <div class="relative flex-1">
                <input
                    id="searchInput"
                    type="text"
                    placeholder="Пошук за містом, областю, об'єктом або описом..."
                    class="w-full bg-slate-50 border border-slate-300 text-slate-900 placeholder-slate-400 text-sm rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                />
            </div>
            <div class="flex items-center gap-2">
                <button
                    id="filterAllBtn"
                    type="button"
                    class="px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-900 text-white cursor-pointer"
                >
                    Усі події
                </button>
                <button
                    id="filterRecentBtn"
                    type="button"
                    class="px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200 cursor-pointer"
                >
                    Свіжі (48 год)
                </button>
            </div>
        </section>

        <!-- Список карток -->
        <section id="cardsContainer" class="grid grid-cols-1 md:grid-cols-2 gap-5"></section>
        <div id="emptyState" class="hidden bg-white border border-slate-200 rounded-2xl p-10 text-center text-slate-500">
            За заданим запитом подій не знайдено.
        </div>
    </main>

    <!-- Футер -->
    <footer class="bg-white border-t border-slate-200 py-5 text-center text-xs text-slate-500">
        Sport Infra Monitor Ukraine · Світлий дашборд відкритого моніторингу
    </footer>

    <script>
        const INCIDENTS_DATA = {embedded_json};
        let onlyRecent = false;

        const searchInput = document.getElementById("searchInput");
        const filterAllBtn = document.getElementById("filterAllBtn");
        const filterRecentBtn = document.getElementById("filterRecentBtn");
        const cardsContainer = document.getElementById("cardsContainer");
        const emptyState = document.getElementById("emptyState");

        function escapeText(str) {{
            return String(str || "")
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;");
        }}

        function setFilterMode(recentMode) {{
            onlyRecent = recentMode;
            if (recentMode) {{
                filterRecentBtn.className = "px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-900 text-white cursor-pointer";
                filterAllBtn.className = "px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200 cursor-pointer";
            }} else {{
                filterAllBtn.className = "px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-900 text-white cursor-pointer";
                filterRecentBtn.className = "px-4 py-2.5 text-sm font-medium rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200 cursor-pointer";
            }}
            renderCards();
        }}

        function renderCards() {{
            const q = (searchInput.value || "").trim().toLowerCase();
            const filtered = INCIDENTS_DATA.filter((item) => {{
                if (onlyRecent && !item.is_recent) return false;
                if (!q) return true;
                const haystack = [
                    item.region_city,
                    item.facility,
                    item.description,
                    item.date,
                ].join(" ").toLowerCase();
                return haystack.includes(q);
            }});

            if (filtered.length === 0) {{
                cardsContainer.innerHTML = "";
                emptyState.classList.remove("hidden");
                return;
            }}

            emptyState.classList.add("hidden");
            cardsContainer.innerHTML = filtered.map((item) => {{
                const sourcesHtml = (item.sources || [])
                    .map((s) => `<a href="${{escapeText(s.link)}}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center text-xs font-medium text-sky-700 bg-sky-50 hover:bg-sky-100 border border-sky-200 px-3 py-1.5 rounded-lg transition-colors">${{escapeText(s.source_name || "Джерело")}}</a>`)
                    .join(" ");

                const badgeHtml = item.is_recent
                    ? `<span class="text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200 px-2.5 py-0.5 rounded-full">Свіже</span>`
                    : `<span class="text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200 px-2.5 py-0.5 rounded-full">У базі</span>`;

                return `
                    <article class="bg-white border border-slate-200 rounded-2xl p-6 shadow-xs flex flex-col justify-between gap-4">
                        <div class="space-y-2.5">
                            <div class="flex items-start justify-between gap-3">
                                <span class="text-xs font-semibold text-slate-600 bg-slate-100 px-3 py-1 rounded-full">
                                    ${{escapeText(item.region_city)}}
                                </span>
                                ${{badgeHtml}}
                            </div>
                            <h2 class="text-lg font-bold text-slate-900 leading-snug">
                                ${{escapeText(item.facility)}}
                            </h2>
                            <p class="text-xs text-slate-500">
                                Публікація: <span class="font-medium text-slate-700">${{escapeText(item.date)}}</span>
                            </p>
                            <p class="text-sm text-slate-700 leading-relaxed">
                                ${{escapeText(item.description)}}
                            </p>
                        </div>
                        <div class="pt-3 border-t border-slate-100 flex flex-wrap items-center gap-2">
                            <span class="text-xs text-slate-500 mr-1">Джерела:</span>
                            ${{sourcesHtml || '<span class="text-xs text-slate-400">Не вказано</span>'}}
                        </div>
                    </article>
                `;
            }}).join("");
        }}

        searchInput.addEventListener("input", renderCards);
        filterAllBtn.addEventListener("click", () => setFilterMode(false));
        filterRecentBtn.addEventListener("click", () => setFilterMode(true));

        renderCards();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    print("Завантаження бази зафіксованих подій...")
    existing_incidents = load_incidents(INCIDENTS_FILE)
    print(f"У базі вже зафіксовано подій: {len(existing_incidents)}")

    print("\nЗбір новин з Google News за ключовими словами...")
    google_news = get_google_news()
    print(f"Відібрано новин за ключовими словами: {len(google_news)}")

    print("\nАналіз через Gemini AI та звірка з базою...")
    analysis = analyze_articles(google_news, existing_incidents)
    all_new_incidents = analysis.get("new_incidents", [])
    extra_sources = analysis.get("extra_sources", [])

    added_links_count = merge_extra_sources_into_db(existing_incidents, extra_sources)
    db_changed = False

    if all_new_incidents:
        existing_incidents.extend(all_new_incidents)
        db_changed = True

    if added_links_count > 0:
        db_changed = True

    if db_changed:
        save_incidents(INCIDENTS_FILE, existing_incidents)
        print(
            f"Оновлено {INCIDENTS_FILE}: нових подій +{len(all_new_incidents)}, "
            f"нових посилань до існуючих подій +{added_links_count}. Всього подій: {len(existing_incidents)}"
        )
    else:
        print("Змін для запису в базу немає.")

    recent_new_incidents = [item for item in all_new_incidents if item.get("is_recent")]
    print(f"Нових подій (сьогодні/вчора) для сповіщення: {len(recent_new_incidents)}")

    kyiv_now = datetime.now(KYIV_TZ)
    current_time = kyiv_now.strftime("%d.%m.%Y о %H:%M")

    html_content = build_light_dashboard_html(
        incidents=existing_incidents,
        recent_count=len(recent_new_incidents),
        updated_at=current_time,
    )

    with open("index.html", "w", encoding="utf-8") as file:
        file.write(html_content)

    print("\nСвітлий дашборд згенеровано у файл index.html!")

    tg_message = format_telegram_message(recent_new_incidents)
    print(f"\nТекст для відправки у Telegram:\n{tg_message}\n")
    send_telegram_notification(tg_message)
