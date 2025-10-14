import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
import json

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL')
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

class YandexGPT:
    def __init__(self):
        self.api_key = YANDEX_API_KEY
        self.folder_id = YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        
    def generate_text(self, prompt, temperature=0.7):
        """Генерация текста через Yandex GPT"""
        if not self.api_key or not self.folder_id:
            return "❌ Не настроены ключи Yandex GPT"
            
        headers = {
            'Authorization': f'Api-Key {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'modelUri': f'gpt://{self.folder_id}/yandexgpt-lite',
            'completionOptions': {
                'stream': False,
                'temperature': temperature,
                'maxTokens': 2000
            },
            'messages': [
                {
                    'role': 'user',
                    'text': prompt
                }
            ]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result['result']['alternatives'][0]['message']['text']
            else:
                return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка соединения: {str(e)}"

class SmartFoodChannel:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.content_themes = self.get_weekly_themes()
        self.gpt = YandexGPT()
        
    def get_kemerovo_time(self):
        """Получаем текущее время в Кемерово (UTC+7)"""
        utc_time = datetime.now(timezone.utc)
        kemerovo_time = utc_time + timedelta(hours=self.timezone_offset)
        return kemerovo_time
    
    def get_weekly_themes(self):
        return {
            0: "🚀 Быстрые завтраки",
            1: "💼 Обеды для работы", 
            2: "⚡ Ужины за 20 минут",
            3: "🔍 Разбор мифов о питании",
            4: "💰 Бюджетные рецепты",
            5: "🎯 Спецпроекты",
            6: "❓ Ответы на вопросы"
        }
    
    def get_daily_content(self, meal_type):
        """Генерирует контент по дням недели и типу приема пищи"""
        kemerovo_time = self.get_kemerovo_time()
        weekday = kemerovo_time.weekday()
        theme = self.content_themes[weekday]
        
        content_generators = {
            'завтрак': self.generate_breakfast_content,
            'обед': self.generate_lunch_content,
            'ужин': self.generate_dinner_content,
            'перекус': self.generate_snack_content,
            'нутрициолог': self.generate_nutritionist_advice
        }
        
        content = content_generators[meal_type](weekday)
        
        # Добавляем дополнительный развлекательный контент для ужина
        if meal_type == 'ужин':
            entertainment = self.get_daily_entertainment(weekday)
            content += f"\n\n🎭 ВЕЧЕРНИЙ БЛОК\n{entertainment}"
            
        return content
    
    def generate_breakfast_content(self, weekday):
        """Генерация завтрака через Yandex GPT"""
        themes = {
            0: "быстрый и энергичный завтрак для начала недели",
            1: "питательный завтрак для продуктивного дня", 
            2: "легкий и полезный завтрак",
            3: "необычный завтрак с интересными сочетаниями",
            4: "бюджетный, но сытный завтрак",
            5: "особенный завтрак для выходного дня",
            6: "расслабленный семейный завтрак"
        }
        
        prompt = f"""
        Создай рецепт завтрака для {themes[weekday]}. 
        
        Требования к формату:
        🍳 НАЗВАНИЕ БЛЮДА (с эмодзи)
        
        🥗 ИНГРЕДИЕНТЫ:
        • Список ингредиентов с количествами
        
        👨‍🍳 ПРИГОТОВЛЕНИЕ (укажи время):
        1. Шаг 1
        2. Шаг 2
        3. Шаг 3
        
        📊 КБЖУ: приблизительная калорийность и польза
        
        Рецепт должен быть простым, полезным и доступным для приготовления дома.
        Используй вкусные описания и практичные советы.
        """
        
        gpt_response = self.gpt.generate_text(prompt)
        return f"🌅 ЗАВТРАК ДНЯ\n\n{gpt_response}"
    
    def generate_lunch_content(self, weekday):
        """Генерация обеда через Yandex GPT"""
        themes = {
            0: "быстрый обед для рабочего дня",
            1: "сбалансированный обед для офиса", 
            2: "легкий, но сытный обед",
            3: "обед с необычными ингредиентами",
            4: "экономный, но питательный обед",
            5: "особенный обед для выходных",
            6: "семейный воскресный обед"
        }
        
        prompt = f"""
        Создай рецепт обеда для {themes[weekday]}. 
        
        Требования к формату:
        🍲 НАЗВАНИЕ БЛЮДА (с эмодзи)
        
        🥗 ИНГРЕДИЕНТЫ:
        • Список ингредиентов с количествами
        
        👨‍🍳 ПРИГОТОВЛЕНИЕ (укажи время):
        1. Шаг 1
        2. Шаг 2
        3. Шаг 3
        
        📊 КБЖУ: приблизительная калорийность и питательная ценность
        
        Блюдо должно быть сбалансированным, сытным и подходить для дневного приема пищи.
        Добавь совет по сервировке или вариантам замены ингредиентов.
        """
        
        gpt_response = self.gpt.generate_text(prompt)
        return f"🍽️ ОБЕД ДНЯ\n\n{gpt_response}"
    
    def generate_dinner_content(self, weekday):
        """Генерация ужина через Yandex GPT"""
        themes = {
            0: "легкий ужин после рабочего дня",
            1: "быстрый ужин для вечера после работы", 
            2: "полезный ужин за 20 минут",
            3: "ужин, развенчивающий мифы о питании",
            4: "бюджетный, но вкусный ужин",
            5: "особенный ужин для выходных",
            6: "расслабленный семейный ужин"
        }
        
        prompt = f"""
        Создай рецепт ужина для {themes[weekday]}. 
        
        Требования к формату:
        🍽️ НАЗВАНИЕ БЛЮДА (с эмодзи)
        
        🥗 ИНГРЕДИЕНТЫ:
        • Список ингредиентов с количествами
        
        👨‍🍳 ПРИГОТОВЛЕНИЕ (укажи время, желательно до 30 минут):
        1. Шаг 1
        2. Шаг 2
        3. Шаг 3
        
        📊 КБЖУ: приблизительная калорийность
        
        Ужин должен быть легким, но сытным, способствовать хорошему сну.
        Добавь совет по сочетанию с напитками или вечерними ритуалами.
        """
        
        gpt_response = self.gpt.generate_text(prompt)
        return f"🌙 УЖИН ДНЯ\n\n{gpt_response}"
    
    def generate_snack_content(self, weekday):
        """Генерация перекуса через Yandex GPT"""
        prompt = f"""
        Создай рецепт полезного перекуса на {['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье'][weekday]}. 
        
        Требования к формату:
        🥜 НАЗВАНИЕ ПЕРЕКУСА (с эмодзи)
        
        🥗 ИНГРЕДИЕНТЫ:
        • Список ингредиентов с количествами
        
        👨‍🍳 ПРИГОТОВЛЕНИЕ (укажи время, должно быть быстрым):
        1. Шаг 1
        2. Шаг 2
        3. Шаг 3
        
        📊 КБЖУ: приблизительная калорийность
        
        Перекус должен быть полезным, быстрым в приготовлении (до 10 минут) 
        и давать энергию без чувства тяжести.
        Предложи варианты для сладкого и соленого перекуса.
        """
        
        gpt_response = self.gpt.generate_text(prompt)
        return f"☕ ПЕРЕКУС ДНЯ\n\n{gpt_response}"
    
    def generate_nutritionist_advice(self, weekday):
        """Советы нутрициолога через Yandex GPT"""
        topics = {
            0: "быстрых завтраков и утреннего метаболизма",
            1: "сбалансированных обедов и продуктивности", 
            2: "легких ужинов и вечернего пищеварения",
            3: "разрушения мифов о здоровом питании",
            4: "экономного и здорового питания",
            5: "особенностей питания в выходные дни",
            6: "семейного питания и пищевых привычек"
        }
        
        prompt = f"""
        Напиши совет от нутрициолога с 40-летним стажем на тему {topics[weekday]}.
        
        Формат строго следующий:
        💎 СОВЕТ НУТРИЦИОЛОГА
        
        👨‍⚕️ [Основной совет в кавычках, как цитата эксперта]
        
        📚 НАУЧНОЕ ОБОСНОВАНИЕ: [Объяснение с научной точки зрения, почему это работает]
        
        💡 ПРАКТИЧЕСКИЙ СОВЕТ: [Конкретное действие, которое можно применить сегодня]
        
        Тон должен быть авторитетным, дружелюбным и мотивирующим.
        Используй конкретные цифры и факты, где это уместно.
        Совет должен быть практичным и легко применимым в повседневной жизни.
        """
        
        gpt_response = self.gpt.generate_text(prompt, temperature=0.8)
        return f"{gpt_response}\n\n🌟 Нутрициолог с 40-летним стажем"
    
    def get_daily_entertainment(self, weekday):
        """Развлекательный контент через Yandex GPT"""
        day_names = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье']
        themes = {
            0: "идеи для быстрых ужинов после работы и лайфхаки для кухни",
            1: "кулинарные челленджи и эксперименты с новыми блюдами", 
            2: "советы по релаксации после ужина и созданию уютной атмосферы",
            3: "разбор популярных мифов о вечернем питании",
            4: "идеи для пятничного вечера и релакса после недели",
            5: "активности для выходных и семейные традиции",
            6: "подготовка к новой неделе и планирование питания"
        }
        
        prompt = f"""
        Создай развлекательный контент для {day_names[weekday]} на тему: {themes[weekday]}.
        
        Формат должен включать:
        - Интересный факт или статистику о питании
        - Практический лайфхак для кухни или питания
        - Вопрос для взаимодействия с аудиторией
        - Мотивирующую фразу
        
        Стиль: легкий, дружелюбный, вовлекающий. Используй эмодзи для визуального оформления.
        Длина: примерно 150-200 слов.
        """
        
        gpt_response = self.gpt.generate_text(prompt, temperature=0.9)
        return gpt_response
    
    def send_to_telegram(self, message):
        if not self.token or not self.channel:
            print("❌ Ошибка: Не установлен токен или канал!")
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.channel,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                kemerovo_time = self.get_kemerovo_time()
                print(f"✅ Сообщение отправлено: {kemerovo_time.strftime('%H:%M')} (Кемерово)")
                return True
            else:
                print(f"❌ Ошибка Telegram: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False
    
    def run_scheduler(self):
        """Запускает 5 публикаций в день по кемеровскому времени"""
        # РАСПИСАНИЕ ДЛЯ КЕМЕРОВО (UTC+7)
        schedule.every().day.at("09:00").do(lambda: self.publish_meal('завтрак'))
        schedule.every().day.at("13:00").do(lambda: self.publish_meal('обед'))
        schedule.every().day.at("16:00").do(lambda: self.publish_meal('перекус'))
        schedule.every().day.at("19:00").do(lambda: self.publish_meal('ужин'))
        schedule.every().day.at("21:30").do(lambda: self.publish_meal('нутрициолог'))
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"📅 РАСПИСАНИЕ АКТИВИРОВАНО! Текущее время в Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print("🥞 Завтрак: 09:00")
        print("🍲 Обед: 13:00") 
        print("🥜 Перекус: 16:00")
        print("🍽️ Ужин: 19:00 (с развлекательным контентом)")
        print("💎 Советы нутрициолога: 21:30")
        print("🤖 Генерация: Yandex GPT")
        print("=" * 50)
        
        # Тестовая отправка при запуске
        print("🧪 Тестовая отправка...")
        self.publish_meal('завтрак')
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_meal(self, meal_type):
        """Публикация контента для конкретного приема пищи"""
        kemerovo_time = self.get_kemerovo_time()
        print(f"📤 Генерация {meal_type} через Yandex GPT... ({kemerovo_time.strftime('%H:%M')} Кемерово)")
        message = self.get_daily_content(meal_type)
        success = self.send_to_telegram(message)
        
        if success:
            print(f"✅ {meal_type.capitalize()} успешно отправлен!")
        else:
            print(f"❌ Ошибка отправки {meal_type}")

# Запуск системы
channel = SmartFoodChannel()

# Запуск в отдельном потоке
def start_scheduler():
    channel.run_scheduler()

scheduler_thread = Thread(target=start_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

@app.route('/')
def home():
    kemerovo_time = channel.get_kemerovo_time()
    weekday = kemerovo_time.weekday()
    theme = channel.content_themes[weekday]
    return f"""
    <html>
        <body>
            <h1>🍳 Умная Кухня 4.0 с Yandex GPT</h1>
            <p><strong>Кемерово:</strong> {kemerovo_time.strftime('%H:%M')}</p>
            <p><strong>Сегодня:</strong> {theme}</p>
            <p><strong>Генерация:</strong> Yandex GPT</p>
            <p><strong>Расписание:</strong></p>
            <ul>
                <li>🥞 Завтрак: 09:00</li>
                <li>🍲 Обед: 13:00</li>
                <li>🥜 Перекус: 16:00</li>
                <li>🍽️ Ужин: 19:00 (с развлекательным контентом)</li>
                <li>💎 Нутрициолог: 21:30</li>
            </ul>
        </body>
    </html>
    """

@app.route('/test')
def test():
    """Простой тест отправки"""
    test_message = "🧪 ТЕСТОВОЕ СООБЩЕНИЕ\n\nЕсли вы это видите, бот работает! ✅"
    success = channel.send_to_telegram(test_message)
    return f"Тест отправлен: {'✅' if success else '❌'}"

@app.route('/force/<meal_type>')
def force_publish(meal_type):
    """Принудительная отправка"""
    valid_meals = ['завтрак', 'обед', 'ужин', 'перекус', 'нутрициолог']
    if meal_type not in valid_meals:
        return f"❌ Неверный тип. Используйте: {', '.join(valid_meals)}"
    
    channel.publish_meal(meal_type)
    return f"✅ Принудительно отправлен {meal_type}"

@app.route('/debug')
def debug():
    """Страница диагностики"""
    kemerovo_time = channel.get_kemerovo_time()
    return {
        "telegram_token_set": bool(TELEGRAM_TOKEN),
        "telegram_channel_set": bool(TELEGRAM_CHANNEL),
        "yandex_gpt_set": bool(YANDEX_API_KEY and YANDEX_FOLDER_ID),
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "status": "active"
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port)
