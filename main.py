import os
import re
import time
import json
import urllib.parse
import urllib.request
import feedparser
from datetime import datetime
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

# 2. Пошукові запити для Google News RSS
SEARCH_QUERIES = [
    'стадіон OR спорткомплекс OR басейн пошкоджено OR зруйновано OR обстріл',
    'спортзал OR "палац спорту" OR спортшкола пошкоджено OR зруйновано OR обстріл',
    'ДЮСШ OR арена OR "спортивний майданчик" пошкоджено OR зруйновано OR обстріл',
    'стадіон OR спорткомплекс OR басейн "внаслідок атаки" OR "ракетного обстрілу"',
    'спортшкола OR ДЮСШ OR арена "внаслідок атаки" OR "ракетного обстрілу"',
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


def get_google_news() -> list:
    articles = []
    seen_links = set()

    for query in SEARCH_QUERIES:
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=uk&gl=UA&ceid=UA:uk"
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:10]:
            link = getattr(entry, "link", "")
            if link and link not in seen_links:
                seen_links.add(link)
                source_title = ""
                if hasattr(entry, "source") and getattr(entry, "source"):
                    source_title = getattr(entry.source, "title", "") or ""
                articles.append({
                    "title": getattr(entry, "title", "Без заголовка"),
                    "link": link,
                    "published": getattr(entry, "published", "Дата не вказана"),
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


def analyze_new_incidents(articles: list, existing_incidents: list) -> list:
    if not articles:
        return []

    compact_existing = [
        {
            "date": item.get("date", ""),
            "region_city": item.get("region_city", ""),
            "facility": item.get("facility", ""),
            "description": item.get("description", ""),
        }
        for item in existing_incidents[-150:]
    ]

    prompt = f"""
Ти аналітик, який моніторить руйнування та пошкодження спортивної інфраструктури в Україні внаслідок війни.
Твоє завдання:
1. Проаналізувати список новин з Google News.
2. Залишити ТІЛЬКИ підтверджені випадки руйнування або пошкодження спортивних об'єктів (стадіони, спорткомплекси, басейни, ДЮСШ, спортзали, палаци спорту, спортивні арени, майданчики тощо).
3. Звірити кожну подію зі списком УЖЕ ЗАФІКСОВАНИХ ПОДІЙ нижче. Якщо це той самий об'єкт і та сама або вже відома подія (навіть якщо новина свіжіша або з іншого медіа) — НЕ включай її у результат! Повертай лише НОВІ події, яких ще немає у базі.
4. Для кожної НОВОЇ події сформуй поля:
   - "date": дата та час публікації новини (візьми з поля "Дата публікації" або з тексту новини; якщо часу немає — вкажи дату; якщо взагалі немає — "Дата не вказана")
   - "region_city": область та населений пункт (наприклад: Харківська область, м. Харків)
   - "facility": назва або тип спортивного об'єкта (без зірочок **)
   - "description": короткий опис пошкоджень (1-2 речення, без зірочок **)
   - "source_name": коротка назва медіа/джерела (наприклад: Суспільне, РБК-Україна, ДСНС)
   - "link": точне посилання зі списку новин

Поверни відповідь ВИКЛЮЧНО у форматі валідного JSON-масиву (без зайвого тексту до або після JSON). Якщо нових подій немає — поверни порожній масив: []

ВЖЕ ЗАФІКСОВАНІ ПОДІЇ:
{json.dumps(compact_existing, ensure_ascii=False)}

НОВИНИ ДЛЯ АНАЛІЗУ:
"""

    for idx, item in enumerate(articles, 1):
        prompt += (
            f"\n{idx}. Заголовок: {item['title']}\n"
            f"   Дата публікації: {item['published']}\n"
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
                if isinstance(parsed, list):
                    valid_new = []
                    for entry in parsed:
                        if isinstance(entry, dict) and entry.get("facility") and entry.get("link"):
                            valid_new.append({
                                "date": str(entry.get("date", "Дата не вказана")).replace("*", "").strip(),
                                "region_city": str(entry.get("region_city", "Не вказано")).replace("*", "").strip(),
                                "facility": str(entry.get("facility", "Спортивний об'єкт")).replace("*", "").strip(),
                                "description": str(entry.get("description", "")).replace("*", "").strip(),
                                "source_name": str(entry.get("source_name", "Джерело")).replace("*", "").strip(),
                                "link": str(entry.get("link", "")).strip(),
                            })
                    return valid_new
                return []
            except Exception as e:
                print(f"Помилка {model_name} (спроба {attempt + 1}/2): {e}")
                if attempt == 0:
                    time.sleep(60)
        print(f"Модель {model_name} не відповідає, переходимо до наступної.\n")

    print("Помилка: жодна модель не змогла повернути коректний список нових подій.")
    return []


def format_telegram_message(new_incidents: list) -> str:
    if not new_incidents:
        return "Нових руйнувань не зафіксовано"

    lines = ["Знайдено інформацію про руйнування", ""]
    for idx, inc in enumerate(new_incidents, 1):
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


def format_site_report(new_incidents: list, updated_at: str) -> str:
    if not new_incidents:
        return f"Станом на {updated_at}: Нових руйнувань не зафіксовано."

    blocks = [f"Станом на {updated_at}: Знайдено інформацію про руйнування\n"]
    for idx, inc in enumerate(new_incidents, 1):
        blocks.append(
            f"{idx}. {inc['region_city']}\n"
            f"   Об'єкт: {inc['facility']}\n"
            f"   Дата та час публікації: {inc['date']}\n"
            f"   Опис: {inc['description']}\n"
            f"   Джерело: [{inc['source_name']}]({inc['link']})\n"
        )
    return "\n".join(blocks).strip()


def send_telegram_notification(message_html: str) -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Пропуск відправки: Секрети TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID відсутні.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print("Успішно відправлено сповіщення у Telegram!")
            else:
                print(f"Не вдалося надіслати в Telegram (Код: {response.status})")
    except Exception as e:
        print(f"Помилка відправки в Telegram: {e}")


if __name__ == "__main__":
    print("Завантаження бази зафіксованих подій...")
    existing_incidents = load_incidents(INCIDENTS_FILE)
    print(f"У базі вже зафіксовано подій: {len(existing_incidents)}")

    print("\nЗбір новин з Google News...")
    google_news = get_google_news()
    print(f"Знайдено новин у Google: {len(google_news)}")

    print("\nАналіз та перевірка на дублікати через Gemini AI...")
    new_incidents = analyze_new_incidents(google_news, existing_incidents)
    print(f"Виявлено нових подій: {len(new_incidents)}")

    if new_incidents:
        updated_incidents = existing_incidents + new_incidents
        save_incidents(INCIDENTS_FILE, updated_incidents)
        print(f"Оновлено {INCIDENTS_FILE}. Всього подій у базі: {len(updated_incidents)}")

    current_time = datetime.now().strftime("%d.%m.%Y о %H:%M")
    site_report_text = format_site_report(new_incidents, current_time)

    html_content = f"""<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Моніторинг руйнувань спортивної інфраструктури України</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
    </style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col">
    <header class="bg-slate-800 border-b border-slate-700 py-6 px-6 sm:px-12 shadow-md">
        <div class="max-w-5xl mx-auto flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
                <span class="bg-red-500/10 text-red-400 text-xs font-semibold px-3 py-1 rounded-full border border-red-500/20">
                    Дані відкритого моніторингу (Новинні сайти)
                </span>
                <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-white mt-2">
                    Sport Infra Monitor Ukraine
                </h1>
            </div>
            <div class="text-sm text-slate-400 bg-slate-900/50 px-4 py-2 rounded-xl border border-slate-700/50">
                Оновлено: <span class="text-white font-medium">{current_time}</span>
            </div>
        </div>
    </header>

    <main class="flex-1 max-w-5xl w-full mx-auto px-6 py-10">
        <div class="bg-slate-800/60 border border-slate-700 rounded-2xl p-6 sm:p-8 shadow-xl backdrop-blur-md">
            <h2 class="text-xl font-bold text-white mb-6 flex items-center gap-2">
                Оперативний звіт подій
            </h2>
            
            <div class="prose prose-invert max-w-none text-slate-300 leading-relaxed whitespace-pre-wrap">
{_escape_html(site_report_text)}
            </div>
        </div>
    </main>

    <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        Система автоматичного моніторингу наслідків війни для спортивної галузі України.
    </footer>
</body>
</html>
"""

    with open("index.html", "w", encoding="utf-8") as file:
        file.write(html_content)

    print("\nHTML-лендинг згенеровано у файл index.html!")

    tg_message = format_telegram_message(new_incidents)
    print("\nВідправка сповіщення у Telegram-канал...")
    send_telegram_notification(tg_message)
