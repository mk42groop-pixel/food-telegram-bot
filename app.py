import os
import requests
import schedule
import time
import random
from datetime import datetime
from threading import Thread
from flask import Flask
from dotenv import load_dotenv

# Загружаем настройки из .env файла
load_dotenv()

app = Flask(__name__)

# Загрузка переменных окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL')

class FoodBot:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        
        self.meal_types = ['завтрак', 'обед', 'ужин', 'перекус']
        self.diets = ['классика', 'кето', 'веган', 'безглютен']
        
    def generate_recipe(self, meal_type):
        recipes = {
            'завтрак': [
                {
                    'name': '🥞 Сырники с малиной',
                    'ingredients': ['Творог 5% - 200г', 'Яйцо - 1 шт', 'Малина - 100г', 'Мед - 1 ч.л.'],
                    'steps': ['Смешать творог с яйцом', 'Сформировать сырники', 'Обжарить 5-7 минут'],
                    'calories': '280 ккал',
                    'time': '20 минут'
                },
                {
                    'name': '🍳 Омлет с овощами',
                    'ingredients': ['Яйца - 2 шт', 'Помидор - 1 шт', 'Перец - 1 шт', 'Зелень'],
                    'steps': ['Взбить яйца', 'Нарезать овощи', 'Обжарить 7-10 минут'],
                    'calories': '250 ккал',
                    'time': '15 минут'
                }
            ],
            'обед': [
                {
                    'name': '🍲 Куриный суп с овощами',
                    'ingredients': ['Куриная грудка - 200г', 'Морковь - 1 шт', 'Картофель - 2 шт', 'Лук - 1 шт'],
                    'steps': ['Сварить бульон', 'Добавить овощи', 'Варить 25 минут'],
                    'calories': '180 ккал',
                    'time': '30 минут'
                }
            ],
            'ужин': [
                {
                    'name': '🍽️ Рыба на пару с брокколи',
                    'ingredients': ['Филе рыбы - 200г', 'Брокколи - 150г', 'Лимон - 0.5 шт', 'Специи'],
                    'steps': ['Приготовить на пару', 'Добавить лимон', 'Подавать с брокколи'],
                    'calories': '200 ккал',
                    'time': '20 минут'
                }
            ],
            'перекус': [
                {
                    'name': '🥜 Фруктовый салат с йогуртом',
                    'ingredients': ['Яблоко - 1 шт', 'Банан - 1 шт', 'Йогурт - 100г', 'Мед - 1 ч.л.'],
                    'steps': ['Нарезать фрукты', 'Заправить йогуртом', 'Добавить мед'],
                    'calories': '150 ккал',
                    'time': '5 минут'
                }
            ]
        }
        
        recipe = random.choice(recipes[meal_type])
        diet = random.choice(self.diets)
        
        message = f"🍳 *{recipe['name']}* ({diet.upper()})\n\n"
        message += "🥗 *Ингредиенты:*\n"
        for ing in recipe['ingredients']:
            message += f"• {ing}\n"
            
        message += f"\n👨‍🍳 *Приготовление ({recipe['time']}):*\n"
        for i, step in enumerate(recipe['steps'], 1):
            message += f"{i}. {step}\n"
            
        message += f"\n📊 *КБЖУ:* {recipe['calories']}\n"
        message += f"⏰ *Время:* {recipe['time']}\n"
        message += f"🍽️ *Тип:* {meal_type.capitalize()}\n"
        
        message += f"\n📈 *Статистика поста:*\n"
        message += f"• Эмодзи: {message.count('🥗') + message.count('👨') + message.count('📊') + message.count('⏰') + message.count('🍽️') + message.count('📈')}\n"
        message += f"• Строки: {message.count(chr(10)) + 1}\n"
        
        message += f"\n🔔 *Подписывайтесь на [Умную Кухню](https://t.me/smart_food_kitchen) - каждый день новые рецепты!*"
        
        return message
    
    def send_to_telegram(self, message):
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
                print(f"✅ Успешно отправлен {datetime.now().strftime('%H:%M')}")
                return True
            else:
                print(f"❌ Ошибка: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False
    
    def run_scheduler(self):
        """Запускает планировщик в отдельном потоке"""
        schedule.every().day.at("08:00").do(lambda: self.publish_recipe('завтрак'))
        schedule.every().day.at("13:00").do(lambda: self.publish_recipe('обед'))
        schedule.every().day.at("19:00").do(lambda: self.publish_recipe('ужин'))
        schedule.every().day.at("11:00").do(lambda: self.publish_recipe('перекус'))
        
        print("📅 Расписание настроено на Back4app!")
        print("🥞 Завтрак: 08:00")
        print("🍲 Обед: 13:00") 
        print("🍽️ Ужин: 19:00")
        print("🥜 Перекус: 11:00")
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_recipe(self, meal_type):
        print(f"📤 Генерация {meal_type}...")
        message = self.generate_recipe(meal_type)
        self.send_to_telegram(message)

# Создаем и запускаем бота
bot = FoodBot()

# Запускаем планировщик в отдельном потоке
def start_scheduler():
    bot.run_scheduler()

scheduler_thread = Thread(target=start_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

@app.route('/')
def home():
    return "🍳 Умная Кухня работает на Back4app! Бот активен."

@app.route('/test')
def test():
    bot.send_to_telegram("🧪 Тестовое сообщение от Back4app")
    return "Тестовое сообщение отправлено"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
