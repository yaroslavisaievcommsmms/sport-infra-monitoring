import os
import time
import json
import asyncio
import urllib.parse
import urllib.request
import feedparser
from datetime import datetime, timedelta, timezone
from google import genai
from telethon import TelegramClient

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

# 2. Пошукові запити для Google News RSS
SEARCH_QUERIES = [
    'стадіон OR спорткомплекс OR басейн пошкоджено OR зруйновано OR обстріл',
    'спортзал OR "палац спорту" OR спортшкола пошкоджено OR зруйновано OR обстріл',
    'ДЮСШ OR арена OR "спортивний майданчик" пошкоджено OR зруйновано OR обстріл',
    'стадіон OR спорткомплекс OR басейн "внаслідок атаки" OR "ракетного обстрілу"',
    'спортшкола OR ДЮСШ OR арена "внаслідок атаки" OR "ракетного обстрілу"'
]

# 3. Список Telegram-каналів для моніторингу (Оновлений список із 145 каналів)
TG_CHANNELS = [
    'DonetskaODA', 'ODA_RV', 'Sumy_news_ODA', 'UA_National_Police', 'cherkaskaODA', 
    'cherkassy_live', 'cherkasy_golovne', 'chernigiv_truexa', 'chernigivskaODA', 
    'chernihiv_golovne_ua', 'chernihiv_live', 'chernivcitruexa', 'chernivetskaODA', 
    'chernivtsi_golovne_ua', 'chernivtsi_live', 'dancor_sumy', 'dnipro_main', 
    'dnipro_now', 'dnipro_operativ', 'dnipropetrovskaODA', 'donetchanyn', 'dsns_telegram', 
    'frankivsk_golovne', 'frankivsk_live', 'galka_if_ua', 'h_kharkov', 'ha_golovne', 
    'hueviyherson', 'hyevuy_dnepr', 'its_zp', 'kharkiv_1654', 'kharkivlife', 
    'kherson_live', 'kherson_non_fake', 'kherson_now', 'khersonskaODA', 'khmel_golovne', 
    'khmel_typ', 'khmelnytskaODA', 'khmelnytsky_live', 'kiev_operativniy', 'kievinfo_kyiv', 
    'kievreal1', 'kirovogradskaODA', 'kozytskyy_maksym_official', 'kramatorsk_tg', 
    'krop_golovne', 'krop_live', 'kropyvnytskyi_news', 'kropyvnytskyi_typ', 'kurs_odessa', 
    'kyiv_golovne', 'kyivoda', 'lisichansk_live', 'luhansk_operative', 'luhanskaVTSA', 
    'lutsk_live', 'lutsk_tipical', 'lviv_golovne', 'lviv_typical', 'lvivych_news', 
    'molbuk', 'mykolaiv_now', 'mykolaiv_typical', 'mykolaivskaODA', 'nikolaev_live', 
    'novosti_n', 'odesa_golovne', 'odesatruexa', 'odeskaODA', 'odessa_infonews', 
    'odessa_typical', 'onyshchuksvitlana', 'pokrovsk_news', 'poltava_golovne', 
    'poltava_live', 'poltavshchyna', 'poltavskaOVA', 'provce_ck', 'pzhytomyr', 
    'rivne_1', 'rivne_golovne', 'rivne_live', 'rivnetruexa', 'severodonetsk_news', 
    'slavyansk_tut', 'starobilsk_life', 'sumy_golovne_ua', 'sumy_live', 'sumytoday', 
    'suspilne_chernihiv', 'synegubov', 'te_20_hvylyn', 'ternopil1', 'ternopil_golovne', 
    'ternopil_live', 'ternopilskaODA', 'ternopiltruexa', 'tipove_rivne', 'transcarpathia', 
    'truexacherkasy', 'truexadnepr', 'truexadonbass', 'truexafrankivsk', 'truexakharkiv', 
    'truexakhersonua', 'truexakropivnicky', 'truexakyiv', 'truexaluck', 'truexalviv', 
    'truexanikolaev', 'truexapoltava', 'truexasumy', 'truexaxmelnitskyy', 'truexazaporozie', 
    'truexazhitomir', 'typical_cherkasy', 'typical_chernihiv', 'typical_chernivtsi', 
    'typical_frankivsk', 'typical_poltava', 'uzgorodtruexa', 'varta1', 'vinnicatruexa', 
    'vinnitsa_blacklist', 'vinnytsia_golovne', 'vinnytsia_live', 'vinnytsia_novyny', 
    'vinnytskaODA', 'vitalii_glagola', 'volyn_golovne_ua', 'volynblog', 'volynskaODA', 
    'vsim_ua', 'zakarpatskaODA', 'zakarpattia_golovne', 'zakarpattya24', 'zap_golovne', 
    'zaporizhzhia_now', 'zhitomir_news', 'zhytomyr_glvn', 'zhytomyr_info', 
    'zhytomyrskaODA', 'zoda_gov_ua', 'zp_operativ'
]

def get_google_news():
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

async def get_telegram_posts_async():
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        print("Пропуск Telegram-моніторингу: TELEGRAM_API_ID або TELEGRAM_API_HASH відсутні.")
        return []

    posts = []
    client = TelegramClient('anon_session', int(api_id), api_hash)
    
    try:
        await client.start()
        print("Телеграм-клієнт успішно підключено!")
        
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        for channel in TG_CHANNELS:
            try:
                print(f"Зчитування каналу @{channel}...")
                async for message in client.iter_messages(channel, limit=15):
                    if message.date and message.date > yesterday and message.text:
                        # Проста фільтрація за ключовими словами для прискорення
                        text_lower = message.text.lower()
                        keywords = ['стадіон', 'спорт', 'дюсш', 'басейн', 'арена', 'комплекс', 'майданчик']
                        if any(kw in text_lower for kw in keywords):
                            posts.append({
                                'title': f"Telegram [@{channel}]: {message.text[:120]}...",
                                'link': f"https://t.me/{channel}/{message.id}",
                                'published': message.date.strftime('%d.%m.%Y %H:%M')
                            })
            except Exception as ch_err:
                print(f"Помилка зчитування каналу @{channel}: {ch_err}")
                
        await client.disconnect()
    except Exception as e:
        print(f"Помилка підключення Telethon: {e}")

    return posts

def analyze_with_gemini(articles):
    if not articles:
        return "За останню добу новин за пошуковими запитами не знайдено."

    prompt = f"""
    Ти аналітик, який збирає інформацію про пошкодження спортивної інфраструктури в Україні внаслідок війни.
    Нижче наведено список новин з Google News та Telegram-каналів. Твоє завдання:
    1. Відбракувати новини/пости, які НЕ стосуються руйнувань або пошкоджень спортивних об'єктів (стадіони, спорткомплекси, басейни, ДЮСШ, спортзали, палаци спорту тощо).
    2. Для кожної підтвердженої події виділи:
       - Дата/час (якщо є)
       - Область та населений пункт
       - Назва або тип спортивного об'єкта
       - Короткий опис пошкоджень
       - Посилання на джерело

    Якщо серед новин немає жодного підтвердженого випадку руйнування спортоб'єкта, напиши чітко: "За добу підтверджених новин про руйнування спортивної інфраструктури не знайдено."

    Ось масив даних:
    """
    
    for idx, item in enumerate(articles, 1):
        prompt += f"\n{idx}. Джерело/Заголовок: {item['title']}\n   Посилання: {item['link']}\n"

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
        print("Пропуск відправки: Секрети TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID відсутні.")
        return

    site_url = "https://yaroslavisaievcommsms.github.io/sport-infra-monitoring/"
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
    google_news = get_google_news()
    print(f"Знайдено новин у Google: {len(google_news)}")
    
    print("\nЗбір дописів з Telegram-каналів...")
    tg_posts = asyncio.run(get_telegram_posts_async())
    print(f"Знайдено відповідних постів у Telegram: {len(tg_posts)}")

    all_sources = google_news + tg_posts
    print(f"\nУсього матеріалів для аналізу: {len(all_sources)}")
    
    print("\nАналіз за допомогою Gemini AI...")
    report = analyze_with_gemini(all_sources)
    
    current_time = datetime.now().strftime('%d.%m.%Y о %H:%M')

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
                    Автентифіковані дані відкритого моніторингу (Web + Telegram)
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
    
    with open("index.html", "w", encoding="utf-8") as file:
        file.write(html_content)
        
    print("\nHTML-лендинг згенеровано у файл index.html!")

    print("\nВідправка сповіщення у Telegram-канал...")
    send_telegram_notification(report)
