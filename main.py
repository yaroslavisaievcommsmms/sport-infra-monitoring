import os
import time
import urllib.parse
import feedparser
from datetime import datetime
from google import genai

# 1. Налаштування Gemini API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_KEY:
    print("Помилка: GEMINI_API_KEY не знайдено в Secrets.")
    exit(1)

client = genai.Client(api_key=GEMINI_KEY)

# Список моделей для перебору (від пріоритетних до запасних)
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

    # Перебір моделей та спроб
    for model_name in MODELS:
        print(f"Пробуємо модель: {model_name}...")
        for attempt in range(2):  # 2 спроби на кожну модель
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                print(f"Помилка {model_name} (спроба {attempt + 1}/2): {e}")
                if attempt == 0:
                    print("Чекаємо 60 секунд перед повторною спробою...")
                    time.sleep(60)
        print(f"Модель {model_name} не відповідає, переходимо до наступної.\n")

    return "Помилка: Жодна з моделей не змогла згенерувати звіт через перевантаження серверів."

if __name__ == "__main__":
    print("Збір новин з Google News...")
    news = get_news()
    print(f"Знайдено новин для аналізу: {len(news)}")
    
    print("\nАналіз за допомогою Gemini AI...")
    report = analyze_with_gemini(news)
    
    # Формуємо вміст для майбутнього сайту
    site_content = f"""# Моніторинг руйнувань спортивної інфраструктури
*Останнє оновлення: {datetime.now().strftime('%d.%m.%Y %H:%M')}*

{report}
"""
    
    # Зберігаємо у файл index.md
    with open("index.md", "w", encoding="utf-8") as file:
        file.write(site_content)
        
    print("\nЗвіт успішно збережено у файл index.md!")
    
    print("\n" + "="*40)
    print("ОТРИМАНИЙ ЗВІТ:")
    print("="*40)
    print(report)
