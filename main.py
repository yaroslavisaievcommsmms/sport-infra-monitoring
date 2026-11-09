import os
import urllib.parse
import feedparser
from datetime import datetime
import google.generativeai as genai

# 1. Налаштування Gemini API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_KEY:
    print("Помилка: GEMINI_API_KEY не знайдено в Secrets.")
    exit(1)

genai.configure(api_key=GEMINI_KEY)

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

    model = genai.GenerativeModel("gemini-1.5-flash")
    
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

    response = model.generate_content(prompt)
    return response.text

if __name__ == "__main__":
    print("Збір новин з Google News...")
    news = get_news()
    print(f"Знайдено новин для аналізу: {len(news)}")
    
    print("\nАналіз за допомогою Gemini AI...")
    report = analyze_with_gemini(news)
    
    print("\n" + "="*40)
    print("ОТРИМАНИЙ ЗВІТ:")
    print("="*40)
    print(report)
