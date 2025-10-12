import requests
import schedule
import time
import random
from datetime import datetime

class FoodBot:
    def __init__(self):
        self.token = "8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA"
        self.channel = "@ppsupershef"
        
        self.meal_types = ['завтрак', 'обед', 'ужин', 'перекус']
        self.diets = ['классика', 'кето', 'веган', 'безглютен']
        
    def generate_recipe(self, meal_type):
        """Генерирует рецепт с красивым форматированием"""
        
        recipes = {
            'завтрак': [
                {
                    'name': '🥞 Сырники с малиной',
                    'ingredients': ['Творог 5% - 200г', 'Яйцо - 1 шт', 'Малина - 100г', 'Мед - 1 ч.л.'],
                    'steps': ['Смешать творог с яйцом', 'Сформировать сырники', 'Обжарить 5-7 минут'],
                    'calories': '280 ккал',
                    'time': '20 минут'
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
            ]
        }
        
        recipe = random.choice(recipes[meal_type])
        diet = random.choice(self.diets)
        
        message = f"🍳 *{recipe['name']}* ({diet.upper()})\n\n"
        message += "🥗 *Ингредиенты:*\n"
        for ing in recipe['ingredients']:
            message += f"• {ing}\n"
        message += f"\n📊 *КБЖУ:* {recipe['calories']}\n"
        message += f"🔔 *Подписывайтесь на канал!*"
        
        return message
    
    def send_to_telegram(self, message):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.channel,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                print(f"✅ Сообщение отправлено!")
            else:
                print(f"❌ Ошибка: {response.text}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

# Тестовый запуск
bot = FoodBot()
print("🧪 Тестируем отправку...")
test_message = bot.generate_recipe('завтрак')
print(test_message)
print("\n📤 Отправляем в Telegram...")
bot.send_to_telegram(test_message)
print("✅ Готово!")
