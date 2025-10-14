import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL')
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

class VisualContentGenerator:
    def __init__(self):
        self.visual_content = {
            'infographics': [
                {
                    'title': '📊 ПРАВИЛО ТАРЕЛКИ',
                    'content': '• 1/2 тарелки - овощи/фрукты\n• 1/4 тарелки - белки\n• 1/4 тарелки - сложные углеводы\n\n🎯 Идеальный баланс для каждого приема пищи!',
                    'hashtags': '#ПравилоТарелки #БалансПитания #ИдеальнаяПорция'
                },
                {
                    'title': '📈 БАЛАНС БЖУ',
                    'content': '💪 Белки: 25-30%\n🥑 Жиры: 25-30%\n⚡ Углеводы: 40-50%\n\n📊 Оптимальное соотношение для здорового метаболизма!',
                    'hashtags': '#БалансБЖУ #Макросы #ПитаниеНаучно'
                },
                {
                    'title': '⏱️ ТАЙМИНГ ПРИЕМОВ ПИЩИ',
                    'content': '🕗 Завтрак: 7-9 утра\n🕛 Обед: 12-14 дня\n🕠 Ужин: 17-19 вечера\n\n⏰ Регулярность - ключ к стабильному метаболизму!',
                    'hashtags': '#ТаймингПитания #РежимДня #Метаболизм'
                },
                {
                    'title': '💧 ГИДРАТАЦИЯ В ТЕЧЕНИЕ ДНЯ',
                    'content': '☀️ Утро: 2 стакана воды\n🌞 День: 1.5 литра\n🌙 Вечер: 0.5 литра\n\n💦 Вода - основа всех метаболических процессов!',
                    'hashtags': '#Гидратация #ВодныйБаланс #ЗдоровыеПривычки'
                }
            ],
            'checklists': [
                {
                    'title': '✅ ЧЕК-ЛИСТ ПОЛЕЗНЫХ ПРОДУКТОВ',
                    'content': '🥦 Овощи: брокколи, шпинат, морковь\n🍎 Фрукты: яблоки, бананы, ягоды\n💪 Белки: курица, рыба, тофу\n🌾 Углеводы: киноа, гречка, овсянка\n🥑 Жиры: авокадо, орехи, оливковое масло',
                    'hashtags': '#ЧекЛист #ПолезныеПродукты #ЗдороваяКорзина'
                },
                {
                    'title': '🎒 СПИСОК ДЛЯ ЛАНЧБОКСА',
                    'content': '📦 Основа: крупа/салат\n🍗 Белок: курица/яйца/рыба\n🥬 Овощи: свежие/запеченные\n🍶 Заправка: отдельно\n🥤 Напиток: вода/чай\n\n💼 Идеальный обед на работе!',
                    'hashtags': '#Ланчбокс #ОбедНаРаботу #MealPrep'
                },
                {
                    'title': '📅 ПЛАН ПИТАНИЯ НА НЕДЕЛЮ',
                    'content': '🗓️ ПН: Рыбный день\n🗓️ ВТ: Куриный день\n🗓️ СР: Вегетарианский\n🗓️ ЧТ: Бобовый\n🗓️ ПТ: Разнообразный\n🗓️ СБ: Семейный\n🗓️ ВС: Подготовительный',
                    'hashtags': '#ПланПитания #MealPlan #Организация'
                }
            ]
        }
    
    def get_random_infographic(self):
        return random.choice(self.visual_content['infographics'])
    
    def get_random_checklist(self):
        return random.choice(self.visual_content['checklists'])

class SmartFoodChannel:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.content_themes = self.get_weekly_themes()
        self.visual_gen = VisualContentGenerator()
        
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
            'нутрициолог': self.generate_nutritionist_advice,
            'визуал': self.generate_visual_content
        }
        
        content = content_generators[meal_type](weekday)
        
        # Добавляем дополнительный развлекательный контент для ужина
        if meal_type == 'ужин':
            entertainment = self.get_daily_entertainment(weekday)
            content += f"\n\n🎭 ВЕЧЕРНИЙ БЛОК\n{entertainment}"
        
        # Добавляем призыв к действию и ссылки (кроме визуального контента)
        if meal_type != 'визуал':
            content += self.get_call_to_action()
            
        return content
    
    def generate_breakfast_content(self, weekday):
        """Генерация завтрака"""
        return self.format_recipe({
            'name': '🥣 Полезный завтрак',
            'ingredients': ['Овсяные хлопья - 50г', 'Молоко - 200мл', 'Фрукты - 100г', 'Мед - 1 ч.л.'],
            'steps': ['Залить овсянку молоком', 'Довести до кипения', 'Добавить фрукты и мед'],
            'time': '10 минут',
            'calories': '250 ккал'
        }, "🌅 ЗАВТРАК ДНЯ")
    
    def generate_lunch_content(self, weekday):
        """Генерация обеда"""
        return self.format_recipe({
            'name': '🍲 Сытный обед',
            'ingredients': ['Куриная грудка - 150г', 'Рис - 100г', 'Овощи - 200г', 'Специи'],
            'steps': ['Приготовить курицу', 'Отварить рис', 'Потушить овощи', 'Подать вместе'],
            'time': '25 минут', 
            'calories': '400 ккал'
        }, "🍽️ ОБЕД ДНЯ")
    
    def generate_dinner_content(self, weekday):
        """Генерация ужина"""
        return self.format_recipe({
            'name': '🍽️ Легкий ужин',
            'ingredients': ['Рыба - 200г', 'Овощи - 300г', 'Лимон - 0.5 шт', 'Зелень'],
            'steps': ['Запечь рыбу 15 мин', 'Приготовить овощи на пару', 'Подать с лимоном'],
            'time': '20 минут',
            'calories': '300 ккал'
        }, "🌙 УЖИН ДНЯ")
    
    def generate_snack_content(self, weekday):
        """Генерация перекуса"""
        return self.format_recipe({
            'name': '🥜 Полезный перекус',
            'ingredients': ['Йогурт - 150г', 'Фрукты - 100г', 'Орехи - 30г', 'Мед - 1 ч.л.'],
            'steps': ['Нарезать фрукты', 'Смешать с йогуртом', 'Посыпать орехами', 'Добавить мед'],
            'time': '5 минут',
            'calories': '180 ккал'
        }, "☕ ПЕРЕКУС ДНЯ")
    
    def generate_nutritionist_advice(self, weekday):
        """Советы нутрициолога"""
        advice_list = [
            {
                'title': '💎 СОВЕТ НУТРИЦИОЛОГА',
                'advice': '«После 40 лет метаболизм замедляется на 5% каждое десятилетие. Сократите порции на 10%, но увеличьте частоту приемов пищи до 4-5 раз в день.»',
                'explanation': '📚 Научное обоснование: Частое питание небольшими порциями поддерживает стабильный уровень сахара в крови и предотвращает переедание.',
                'tip': '💡 Практический совет: Используйте тарелки меньшего размера - это психологически помогает контролировать порции.'
            },
            {
                'title': '💎 СОВЕТ НУТРИЦИОЛОГА', 
                'advice': '«Вода - лучший детокс. За 40 лет практики я убедился: 2 литра чистой воды в день решают 80% проблем с пищеварением.»',
                'explanation': '📚 Научное обоснование: Вода участвует во всех метаболических процессах и помогает выводить токсины.',
                'tip': '💡 Практический совет: Пейте по стакану воды за 30 минут до еды - это улучшит пищеварение и снизит аппетит.'
            }
        ]
        advice = random.choice(advice_list)
        message = f"{advice['title']}\n\n"
        message += f"👨‍⚕️ {advice['advice']}\n\n"
        message += f"{advice['explanation']}\n\n"
        message += f"{advice['tip']}\n\n"
        message += "🌟 Нутрициолог с 40-летним стажем"
        
        return message
    
    def generate_visual_content(self, weekday):
        """Генерация визуального контента"""
        # Чередуем инфографику и чек-листы
        if weekday % 2 == 0:
            visual = self.visual_gen.get_random_infographic()
        else:
            visual = self.visual_gen.get_random_checklist()
        
        message = f"🎨 {visual['title']}\n\n"
        message += f"{visual['content']}\n\n"
        message += f"{visual['hashtags']}\n\n"
        message += "👇 Сохраните себе в закладки!"
        
        return message
    
    def get_daily_entertainment(self, weekday):
        """Развлекательный контент для ужина"""
        entertainment = [
            "💡 Совет вечера: Наслаждайтесь ужином без гаджетов - это улучшает пищеварение! 📵",
            "🌟 Факт: 20-минутная прогулка после ужина ускоряет метаболизм на 30%! 🚶‍♂️",
            "📚 Идея: Создайте вечерний ритуал - чай с травами и хорошая книга! 📖",
            "🏃‍♂️ Напоминание: Легкий ужин = качественный сон! 😴",
            "🥗 Рекомендация: Попробуйте новый овощ на ужин - расширяйте вкусовые горизонты! 🌈",
            "🎯 Челлендж: Готовьте ужин вместе с семьей - это сближает! 👨‍👩‍👧‍👦",
            "📝 Планирование: Составьте меню на следующую неделю сегодня вечером! 📅"
        ]
        return entertainment[weekday]
    
    def get_call_to_action(self):
        """Призыв к действию и ссылки"""
        cta = "\n\n" + "═" * 40 + "\n\n"
        cta += "📱 **ПОНРАВИЛОСЬ? ПОДПИСЫВАЙТЕСЬ!**\n\n"
        cta += "👉 @FoodExpertChannel - ежедневные рецепты и советы\n\n"
        cta += "❤️ Поделитесь с друзьями | 💬 Комментируйте | 📤 Сохраняйте\n\n"
        cta += "👇 **Ваша реакция на пост:**\n"
        cta += "👍 - Вкусно!    🥰 - Обязательно приготовлю!    🔥 - Полезно!"
        
        return cta
    
    def format_recipe(self, recipe, theme):
        message = f"{theme}\n\n"
        message += f"🍳 *{recipe['name']}*\n\n"
        
        message += "🥗 *Ингредиенты:*\n"
        for ing in recipe['ingredients']:
            message += f"• {ing}\n"
            
        message += f"\n👨‍🍳 *Приготовление ({recipe['time']}):*\n"
        for i, step in enumerate(recipe['steps'], 1):
            message += f"{i}. {step}\n"
            
        message += f"\n📊 *КБЖУ:* {recipe['calories']}\n"
        message += "\n🔔 Приятного аппетита! 🍴"
        
        return message
    
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
        """Запускает 6 публикаций в день по кемеровскому времени"""
        # РАСПИСАНИЕ ДЛЯ КЕМЕРОВО (UTC+7)
        schedule.every().day.at("09:00").do(lambda: self.publish_meal('завтрак'))
        schedule.every().day.at("13:00").do(lambda: self.publish_meal('обед'))
        schedule.every().day.at("16:00").do(lambda: self.publish_meal('перекус'))
        schedule.every().day.at("19:00").do(lambda: self.publish_meal('ужин'))
        schedule.every().day.at("21:30").do(lambda: self.publish_meal('нутрициолог'))
        schedule.every().day.at("15:00").do(lambda: self.publish_meal('визуал'))  # Новая публикация
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"📅 РАСПИСАНИЕ АКТИВИРОВАНО! Текущее время в Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print("🥞 Завтрак: 09:00")
        print("🍲 Обед: 13:00") 
        print("🥜 Перекус: 16:00")
        print("🍽️ Ужин: 19:00")
        print("💎 Советы нутрициолога: 21:30")
        print("🎨 Визуальный контент: 15:00")
        print("=" * 50)
        
        # Тестовая отправка при запуске
        print("🧪 Тестовая отправка...")
        self.publish_meal('визуал')
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def publish_meal(self, meal_type):
        """Публикация контента"""
        kemerovo_time = self.get_kemerovo_time()
        print(f"📤 Публикация {meal_type}... ({kemerovo_time.strftime('%H:%M')} Кемерово)")
        message = self.get_daily_content(meal_type)
        success = self.send_to_telegram(message)
        
        if success:
            print(f"✅ {meal_type.capitalize()} успешно отправлен!")
        else:
            print(f"❌ Ошибка отправки {meal_type}")

# Запуск системы
channel = SmartFoodChannel()

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
            <h1>🍳 Умная Кухня 5.0</h1>
            <p><strong>Кемерово:</strong> {kemerovo_time.strftime('%H:%M')}</p>
            <p><strong>Сегодня:</strong> {theme}</p>
            <p><strong>Новые функции:</strong></p>
            <ul>
                <li>🎨 Визуальный контент (инфографика)</li>
                <li>📱 Призывы к действию</li>
                <li>❤️ Интерактивные реакции</li>
                <li>👉 Ссылка на канал</li>
            </ul>
            <p><strong>Расписание:</strong></p>
            <ul>
                <li>🥞 Завтрак: 09:00</li>
                <li>🍲 Обед: 13:00</li>
                <li>🎨 Визуал: 15:00</li>
                <li>🥜 Перекус: 16:00</li>
                <li>🍽️ Ужин: 19:00</li>
                <li>💎 Нутрициолог: 21:30</li>
            </ul>
        </body>
    </html>
    """

@app.route('/test')
def test():
    test_message = "🧪 ТЕСТОВОЕ СООБЩЕНИЕ\n\nБот работает! ✅"
    success = channel.send_to_telegram(test_message)
    return f"Тест отправлен: {'✅' if success else '❌'}"

@app.route('/force/<meal_type>')
def force_publish(meal_type):
    valid_meals = ['завтрак', 'обед', 'ужин', 'перекус', 'нутрициолог', 'визуал']
    if meal_type not in valid_meals:
        return f"❌ Неверный тип. Используйте: {', '.join(valid_meals)}"
    
    channel.publish_meal(meal_type)
    return f"✅ Принудительно отправлен {meal_type}"

@app.route('/debug')
def debug():
    kemerovo_time = channel.get_kemerovo_time()
    return {
        "telegram_token_set": bool(TELEGRAM_TOKEN),
        "telegram_channel_set": bool(TELEGRAM_CHANNEL),
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "status": "active",
        "version": "5.0 - с визуальным контентом"
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port)
