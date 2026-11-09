import os
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

# Список моделей для перебору
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
]

# 2. Пошукові запити для Google News RSS
SEARCH_QUERIES = [
    'стадіон OR спорткомплекс OR басейн пошкоджено OR зруйновано OR обстріл',
    'спортзал OR "палац спорту" OR спортшкола пошкоджено OR зруйновано OR обстріл',
    'ДЮСШ OR арена OR "спортивний майданчик" пошкоджено OR зруйновано OR обстріл',
    'стадіон OR спорткомплекс OR басейн "внаслідок атаки" OR "ракетного обстрілу"',
    'спортшкола OR ДЮСШ OR арена "внаслідок атаки" OR "ракетного обстрілу"'
]

def get_news():
    articles = []
    seen_links = set()
    
    for query in SEARCH_QUERIES:
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=uk&gl=UA&ceid=UA:uk"
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:10]:
            if entry.link not in seen_links:
                seen_links.add(entry.link)
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'published': getattr(entry, 'published', 'Дата невідома')
                })
    return articles

def analyze_with_gemini(articles):
    if not articles:
        return "За останню добу новин за пошуковими запитами не знайдено."

    prompt = f"""
    Ти аналітик, який збирає інформацію про пошкодження спортивної інфраструктури в Україні внаслідок війни.
    Нижче наведено список новин. Твоє завдання:
    1. Відбракувати новини, які НЕ стосуються руйнувань або пошкоджень спортивних об'єктів (стадіони, спорткомплекси, басейни, ДЮСШ, спортзали, палаци спорту тощо).
    2. Для кожної підтвердженої події виділи:
       - Дата/час (якщо є)
       - Область та населений пункт
       - Назва або тип спортивного об'єкта
       - Короткий опис пошкоджень
       - Посилання на джерело

    Якщо серед новин немає жодного підтвердженого випадку руйнування спортоб'єкта, напиши чітко: "За добу підтверджених новин про руйнування спортивної інфраструктури не знайдено."

    Ось список новин:
    """
    
    for idx, item in enumerate(articles, 1):
        prompt += f"\n{idx}. Заголовок: {item['title']}\n   Посилання: {item['link']}\n"

    for model_name in MODELS:
        print(f"Пробуємо модель: {model_name}...")
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                print(f"Помилка {model_name} (спроба {attempt + 1}/2): {e}")
                if attempt == 0:
                    time.sleep(60)
        print(f"Модель {model_name} не відповідає, переходимо до наступної.\n")

    return "Помилка: Жодна з моделей не змогла згенерувати звіт через перевантаження серверів."

def send_telegram_notification(report_text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Пропуск Telegram: Секрети TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID відсутні.")
        return

    site_url = "https://yaroslavisaievcommsms.github.io/sport-infra-monitoring/"
    
    # Обрізаємо повідомлення до ліміту Telegram, якщо звіт занадто довгий
    safe_text = report_text[:3800] + "\n\n..." if len(report_text) > 3800 else report_text

    message = f"🚨 **Оперативний звіт моніторингу спортивної інфраструктури**\n\n{safe_text}\n\n🌐 **Повний звіт на сайті:** {site_url}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": False
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print("Успішно відправлено звіт у Telegram!")
            else:
                print(f"Не вдалося надіслати в Telegram (Код: {response.status})")
    except Exception as e:
        print(f"Помилка відправки в Telegram: {e}")

if __name__ == "__main__":
    print("Збір новин з Google News...")
    news = get_news()
    print(f"Знайдено новин для аналізу: {len(news)}")
    
    print("\nАналіз за допомогою Gemini AI...")
    report = analyze_with_gemini(news)
    
    current_time = datetime.now().strftime('%d.%m.%Y о %H:%M')

    # Шаблон сучасного HTML-лендингу з Tailwind CSS
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
    <!-- Шапка -->
    <header class="bg-slate-800 border-b border-slate-700 py-6 px-6 sm:px-12 shadow-md">
        <div class="max-w-5xl mx-auto flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
                <span class="bg-red-500/10 text-red-400 text-xs font-semibold px-3 py-1 rounded-full border border-red-500/20">
                    Автентифіковані дані відкритого моніторингу
                </span>
                <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-white mt-2">
                    ⚽ Sport Infra Monitor Ukraine
                </h1>
            </div>
            <div class="text-sm text-slate-400 bg-slate-900/50 px-4 py-2 rounded-xl border border-slate-700/50">
                🕒 Оновлено: <span class="text-white font-medium">{current_time}</span>
            </div>
        </div>
    </header>

    <!-- Основний контент -->
    <main class="flex-1 max-w-5xl w-full mx-auto px-6 py-10">
        <div class="bg-slate-800/60 border border-slate-700 rounded-2xl p-6 sm:p-8 shadow-xl backdrop-blur-md">
            <h2 class="text-xl font-bold text-white mb-6 flex items-center gap-2">
                📊 Оперативний звіт подій
            </h2>
            
            <div class="prose prose-invert max-w-none text-slate-300 leading-relaxed whitespace-pre-wrap">
{report}
            </div>
        </div>
    </main>

    <!-- Футер -->
    <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        Система автоматичного щоденного моніторингу наслідків війни для спортивної галузі України.
    </footer>
</body>
</html>
"""
    
    # Зберігаємо у файл index.html
    with open("index.html", "w", encoding="utf-8") as file:
        file.write(html_content)
        
    print("\nГарний HTML-лендинг успішно збережено у файл index.html!")

    # Відправляємо звіт у Telegram-канал
    print("\nВідправка сповіщення у Telegram...")
    send_telegram_notification(report)
