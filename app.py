import os
import requests
import schedule
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

# Ключи из вашего проекта
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '@ppsupershef')
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

class AIContentGenerator:
    def __init__(self):
        self.yandex_gpt = YandexGPT()
        self.deepseek_gpt = DeepSeekGPT()
        print(f"🤖 AI Генератор: YandexGPT - {'✅' if self.yandex_gpt.is_active else '❌'}, DeepSeek - {'✅' if self.deepseek_gpt.is_active else '❌'}")
        
    def generate_content(self, prompt, content_type="recipe"):
        """Умная генерация контента с использованием доступных AI"""
        # Пробуем DeepSeek
        if self.deepseek_gpt.is_active:
            content = self.deepseek_gpt.generate_content(prompt, content_type)
            if content:
                return content
        
        # Пробуем Yandex GPT
        if self.yandex_gpt.is_active:
            content = self.yandex_gpt.generate_text(prompt)
            if content:
                return content
        
        return None

class YandexGPT:
    def __init__(self):
        self.api_key = YANDEX_API_KEY
        self.folder_id = YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        # Упрощенная проверка
        self.is_active = bool(self.api_key and self.folder_id)
        print(f"🤖 Yandex GPT: {'✅ Активен' if self.is_active else '❌ Не настроен'}")
        
    def generate_text(self, prompt, temperature=0.7):
        """Генерация текста через Yandex GPT"""
        if not self.is_active:
            return None
            
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
            print(f"🔄 Запрос к Yandex GPT...")
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                text = result['result']['alternatives'][0]['message']['text']
                print(f"✅ Yandex GPT ответ получен ({len(text)} символов)")
                return text
            else:
                print(f"❌ Ошибка Yandex GPT API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с Yandex GPT: {e}")
            return None

class DeepSeekGPT:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        # Упрощенная проверка
        self.is_active = bool(self.api_key)
        print(f"🤖 DeepSeek GPT: {'✅ Активен' if self.is_active else '❌ Не настроен'}")
        
    def generate_content(self, prompt, content_type="recipe"):
        """Генерация контента через DeepSeek"""
        if not self.is_active:
            return None
            
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        system_prompts = {
            "recipe": """Ты шеф-повар ресторанов Мишлен и нутрициолог с 40-летним стажем. Создавай полезные и вкусные рецепты.""",
            "science": """Ты нутрициолог с 40-летним стажем. Объясняй научные концепции простым языком.""",
            "advice": """Ты команда экспертов: нутрициолог, шеф-повар Мишлен и фитнес-тренер."""
        }
        
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': system_prompts.get(content_type, system_prompts["recipe"])
                },
                {
                    'role': 'user', 
                    'content': prompt
                }
            ],
            'temperature': 0.7,
            'max_tokens': 2000
        }
        
        try:
            print(f"🔄 Запрос к DeepSeek...")
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                text = result['choices'][0]['message']['content']
                print(f"✅ DeepSeek ответ получен ({len(text)} символов)")
                return text
            else:
                print(f"❌ Ошибка DeepSeek API: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с DeepSeek: {e}")
            return None

class EliteContentManager:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.ai_generator = AIContentGenerator()
        self.content_strategy = self._initialize_content_strategy()
        self.last_sent_times = {}
        
    def get_kemerovo_time(self):
        """Получаем текущее время в Кемерово (UTC+7)"""
        utc_time = datetime.now(timezone.utc)
        kemerovo_time = utc_time + timedelta(hours=self.timezone_offset)
        return kemerovo_time
    
    def _initialize_content_strategy(self):
        """Элитная стратегия контента"""
        return {
            "weekly_themes": {
                0: "🧬 НАУЧНЫЙ ПОНЕДЕЛЬНИК: Биохимия питания",
                1: "👨‍🍳 TECH CHECK: Техники шефа", 
                2: "💬 СРЕДА ОТВЕТОВ: Команда экспертов",
                3: "🍽️ РЕЦЕПТ НЕДЕЛИ: Шедевр от Мишлен",
                4: "📊 ТРЕНДОВАЯ ПЯТНИЦА: Анализ тенденций",
                5: "⚡ БЫСТРО & ЗДОРОВО: Простые решения",
                6: "🎯 ВОСКРЕСНЫЙ ДАЙДЖЕСТ: Итоги и мотивация"
            }
        }
    
    def generate_elite_content(self, content_type, weekday=None):
        """Генерация элитного контента"""
        if weekday is None:
            weekday = self.get_kemerovo_time().weekday()
            
        theme = self.content_strategy["weekly_themes"][weekday]
        
        # Пробуем AI генерацию
        ai_content = self._try_ai_generation(content_type, weekday, theme)
        if ai_content:
            return ai_content
        
        # Fallback на статический контент
        return self._get_static_content(content_type, weekday, theme)
    
    def _try_ai_generation(self, content_type, weekday, theme):
        """Попытка генерации контента через AI"""
        prompts = {
            'breakfast': f"Создай рецепт полезного завтрака на тему: {theme}. Включи ингредиенты, шаги приготовления и nutritional info.",
            'lunch': f"Создай рецепт обеда для продуктивности на тему: {theme}. С фокусом на баланс БЖУ.",
            'dinner': f"Создай рецепт легкого ужина для восстановления на тему: {theme}.",
            'science': f"Объясни научную концепцию питания простым языком на тему: {theme}.",
            'expert_advice': f"Дай совет от команды экспертов (нутрициолог, шеф, тренер) на тему: {theme}.",
            'visual': f"Создай описание инфографики на тему: {theme}.",
            'interactive': f"Создай интерактивный опрос или челлендж на тему: {theme}."
        }
        
        prompt = prompts.get(content_type)
        if not prompt:
            return None
            
        content = self.ai_generator.generate_content(prompt, content_type)
        if content:
            emoji = self._get_content_emoji(content_type)
            return f"{emoji} {content_type.upper()} ПРЕМИУМ\n\n{theme}\n\n{content}"
        
        return None
    
    def _get_content_emoji(self, content_type):
        """Возвращает эмодзи для типа контента"""
        emojis = {
            'breakfast': '🌅',
            'lunch': '🍽️', 
            'dinner': '🌙',
            'science': '🧬',
            'visual': '🎨',
            'interactive': '💬',
            'expert_advice': '🌟'
        }
        return emojis.get(content_type, '📝')
    
    def _get_static_content(self, content_type, weekday, theme):
        """Статический контент как fallback"""
        static_content = {
            'breakfast': [
                "🌅 ЭЛИТНЫЙ ЗАВТРАК: Овсянка с суперфудами\n\n🥗 Ингредиенты:\n• Овсяные хлопья - 50г\n• Молоко миндальное - 200мл\n• Семена чиа - 1 ст.л.\n• Ягоды годжи - 1 ст.л.\n• Мед - 1 ч.л.\n\n👨‍🍳 Приготовление:\n1. Варить овсянку 5 минут\n2. Добавить суперфуды\n3. Подавать теплым\n\n📊 КБЖУ: 280 ккал",
                "🌅 ЭЛИТНЫЙ ЗАВТРАК: Авокадо-тост с яйцом-пашот\n\n🥗 Ингредиенты:\n• Хлеб цельнозерновой - 2 ломтика\n• Авокадо - ½ шт\n• Яйца - 2 шт\n• Семена кунжута\n\n👨‍🍳 Приготовление:\n1. Поджарить хлеб\n2. Размять авокадо\n3. Приготовить яйца-пашот\n4. Собрать тосты\n\n📊 КБЖУ: 320 ккал"
            ],
            'lunch': [
                "🍽️ ОБЕД ДЛЯ ПРОДУКТИВНОСТИ: Киноа с овощами\n\n🥗 Ингредиенты:\n• Киноа - 100г\n• Овощи гриль - 200г\n• Нут - 100г\n• Лимонный сок\n\n👨‍🍳 Приготовление:\n1. Отварить киноа\n2. Обжарить овощи\n3. Смешать с нутом\n4. Заправить соком\n\n📊 КБЖУ: 350 ккал",
                "🍽️ ОБЕД ДЛЯ ПРОДУКТИВНОСТИ: Салат с лососем\n\n🥗 Ингредиенты:\n• Лосось - 150г\n• Руккола - 100г\n• Авокадо - ½ шт\n• Орехи грецкие - 30г\n\n👨‍🍳 Приготовление:\n1. Запечь лосось\n2. Смешать зелень\n3. Добавить авокадо\n4. Посыпать орехами\n\n📊 КБЖУ: 380 ккал"
            ],
            'dinner': [
                "🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: Рыба на пару\n\n🥗 Ингредиенты:\n• Морской окунь - 200г\n• Брокколи - 150г\n• Морковь - 1 шт\n• Имбирь\n\n👨‍🍳 Приготовление:\n1. Приготовить на пару 15 мин\n2. Подать с овощами\n3. Сбрызнуть соевым соусом\n\n📊 КБЖУ: 250 ккал",
                "🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: Тушеные овощи с тофу\n\n🥗 Ингредиенты:\n• Тофу - 150г\n• Цукини - 1 шт\n• Грибы - 100г\n• Кокосовое молоко\n\n👨‍🍳 Приготовление:\n1. Обжарить тофу\n2. Добавить овощи\n3. Тушить 20 минут\n\n📊 КБЖУ: 280 ккал"
            ],
            'science': [
                "🧬 НАУКА ПИТАНИЯ: Циркадные ритмы\n\n📚 Факт: Прием пищи в правильное время ускоряет метаболизм на 10-15%\n\n💡 Практика: Завтракайте в течение часа после пробуждения\n\n🎯 Эксперт: Соблюдайте 12-часовое окно для приема пищи",
                "🧬 НАУКА ПИТАНИЯ: Микробиом\n\n📚 Факт: Кишечные бактерии влияют на иммунитет и настроение\n\n💡 Практика: Ешьте ферментированные продукты\n\n🎯 Эксперт: Разнообразьте рацион клетчаткой"
            ],
            'visual': [
                "🎨 ИНФОГРАФИКА: Правило тарелки\n\n📊 Идеальная пропорция:\n• ½ Тарелки - Овощи\n• ¼ Тарелки - Белки\n• ¼ Тарелки - Углеводы\n\n💡 Добавьте полезные жиры\n\n🏷️ #ПравилоТарелки #Баланс",
                "🎨 ИНФОГРАФИКА: Время приемов пищи\n\n⏰ Оптимальный график:\n• 🕗 7-9: Завтрак\n• 🕛 12-14: Обед\n• 🕐 16-17: Перекус\n• 🕢 18-20: Ужин\n\n🏷️ #Тайминг #Метаболизм"
            ],
            'interactive': [
                "💬 ОПРОС: Ваш подход к питанию?\n\n• 🕒 Строгий график\n• 🍽️ Интуитивное питание\n• 📊 Подсчет калорий\n• 🌱 Растительное питание\n\n💭 Напишите в комментариях!",
                "🎯 ЧЕЛЛЕНДЖ НЕДЕЛИ\n\nПриготовьте полезный ужин и:\n1. 📸 Сфотографируйте\n2. 💬 Опишите рецепт\n3. 🏷️ Отметьте @ppsupershef\n\n🏆 Лучшие рецепты - в сторис!"
            ],
            'expert_advice': [
                "🌟 СОВЕТ ЭКСПЕРТОВ\n\n🧬 Нутрициолог: 'Пейте воду за 30 минут до еды'\n👨‍🍳 Шеф: 'Используйте свежие травы вместо соли'\n💪 Тренер: 'Сочетайте кардио и силовые тренировки'",
                "🌟 СОВЕТ ЭКСПЕРТОВ\n\n🧬 Нутрициолог: 'Слушайте сигналы голода'\n👨‍🍳 Шеф: 'Экспериментируйте со специями'\n💪 Тренер: 'Восстановление так же важно как тренировки'"
            ]
        }
        
        content_list = static_content.get(content_type, ["📝 Контент в разработке"])
        content = content_list[weekday % len(content_list)]
        emoji = self._get_content_emoji(content_type)
        
        return f"{emoji} {content_type.upper()}\n\n{theme}\n\n{content}"
    
    def _get_elite_call_to_action(self):
        """Призыв к действию"""
        return """

═══════════════════════════════

💎 **ПОДПИСЫВАЙТЕСЬ!** 👉 @ppsupershef

💬 **КОММЕНТИРУЙТЕ!** Эксперты отвечают на вопросы

👇 **РЕАКЦИИ:**
❤️ - Нравится | 🔥 - Приготовлю | 📚 - Полезно

📤 **ПОДЕЛИТЕСЬ** с друзьями!

🏷️ #ppsupershef #ЗдоровоеПитание #Рецепты
"""

    def run_elite_scheduler(self):
        """Запуск расписания публикаций"""
        # Очищаем существующие задания
        schedule.clear()
        
        # Основные публикации (время Кемерово UTC+7)
        schedule.every().day.at("07:00").do(lambda: self.publish_content('breakfast'))
        schedule.every().day.at("12:00").do(lambda: self.publish_content('lunch')) 
        schedule.every().day.at("15:00").do(lambda: self.publish_content('science'))
        schedule.every().day.at("18:00").do(lambda: self.publish_content('interactive'))
        schedule.every().day.at("19:00").do(lambda: self.publish_content('dinner'))
        schedule.every().day.at("21:00").do(lambda: self.publish_content('expert_advice'))
        
        # Визуальный контент через день
        if self.get_kemerovo_time().day % 2 == 0:
            schedule.every().day.at("16:00").do(lambda: self.publish_content('visual'))
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"🎯 РАСПИСАНИЕ АКТИВИРОВАНО!")
        print(f"📍 Кемерово: {kemerovo_time.strftime('%H:%M')}")
        print(f"📱 Канал: @ppsupershef")
        print("📊 Расписание:")
        print("🥞 07:00 - Завтрак")
        print("🍽️ 12:00 - Обед") 
        print("🧬 15:00 - Наука")
        print("🎨 16:00 - Визуал (через день)")
        print("💬 18:00 - Интерактив")
        print("🍽️ 19:00 - Ужин")
        print("🌟 21:00 - Советы экспертов")
        print("=" * 50)
        
        # Немедленный тест
        print("🧪 Тест системы...")
        self.publish_content('breakfast')
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)
            except Exception as e:
                print(f"❌ Ошибка в планировщике: {e}")
                time.sleep(60)
    
    def publish_content(self, content_type):
        """Публикация контента"""
        try:
            kemerovo_time = self.get_kemerovo_time()
            
            # Проверяем чтобы не отправлять слишком часто
            last_sent = self.last_sent_times.get(content_type)
            if last_sent and (kemerovo_time - last_sent).total_seconds() < 300:  # 5 минут
                print(f"⏰ Пропускаем {content_type} - отправлялся недавно")
                return
                
            print(f"📤 Публикация {content_type}... ({kemerovo_time.strftime('%H:%M')})")
            
            message = self.generate_elite_content(content_type)
            message += self._get_elite_call_to_action()
            
            success = self.send_to_telegram(message)
            
            if success:
                print(f"✅ {content_type.upper()} отправлен в @ppsupershef!")
                self.last_sent_times[content_type] = kemerovo_time
            else:
                print(f"❌ Ошибка отправки {content_type}")
                
        except Exception as e:
            print(f"❌ Критическая ошибка в publish_content: {e}")
    
    def send_to_telegram(self, message):
        """Отправка сообщения в Telegram"""
        if not self.token:
            print("❌ Ошибка: Не установлен токен бота!")
            return False
            
        if not self.channel:
            print("❌ Ошибка: Не установлен канал!")
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.channel,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"✅ Сообщение отправлено в @ppsupershef")
                return True
            else:
                print(f"❌ Ошибка Telegram API: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения с Telegram: {e}")
            return False

# Инициализация системы
elite_channel = EliteContentManager()

def start_elite_scheduler():
    """Запуск планировщика в отдельном потоке"""
    try:
        elite_channel.run_elite_scheduler()
    except Exception as e:
        print(f"❌ Критическая ошибка планировщика: {e}")

# Запускаем планировщик
scheduler_thread = Thread(target=start_elite_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

@app.route('/')
def home():
    """Главная страница"""
    try:
        kemerovo_time = elite_channel.get_kemerovo_time()
        weekday = kemerovo_time.weekday()
        theme = elite_channel.content_strategy["weekly_themes"][weekday]
        
        # Проверяем статус отправки
        now = kemerovo_time
        schedule_status = {
            'breakfast': "✅" if now.hour >= 7 else "⏰",
            'lunch': "✅" if now.hour >= 12 else "⏰", 
            'science': "✅" if now.hour >= 15 else "⏰",
            'visual': "✅" if now.hour >= 16 and now.day % 2 == 0 else "⏰",
            'interactive': "✅" if now.hour >= 18 else "⏰",
            'dinner': "✅" if now.hour >= 19 else "⏰",
            'expert_advice': "✅" if now.hour >= 21 else "⏰"
        }
        
        return f"""
        <html>
            <head>
                <title>@ppsupershef - Система управления</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f0f2f5; }}
                    .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                    .status {{ padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid; }}
                    .success {{ background: #e8f5e8; border-color: #4CAF50; }}
                    .warning {{ background: #fff3cd; border-color: #ffc107; }}
                    .error {{ background: #f8d7da; border-color: #dc3545; }}
                    .schedule {{ background: #e9ecef; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                    .schedule-item {{ display: flex; align-items: center; margin: 8px 0; }}
                    .time {{ font-weight: bold; width: 80px; }}
                    .emoji {{ font-size: 20px; margin-right: 10px; }}
                    .buttons {{ margin-top: 20px; }}
                    .btn {{ display: inline-block; padding: 10px 15px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }}
                    .btn:hover {{ background: #0056b3; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🍳 @ppsupershef - Система управления</h1>
                    
                    <div class="status success">
                        <strong>📍 Кемерово:</strong> {kemerovo_time.strftime('%d.%m %H:%M')} | 
                        <strong>🎯 Тема:</strong> {theme} |
                        <strong>📱 Канал:</strong> @ppsupershef
                    </div>
                    
                    <div class="status {'success' if elite_channel.ai_generator.yandex_gpt.is_active else 'warning'}">
                        <strong>🤖 Yandex GPT:</strong> {'✅ Активен' if elite_channel.ai_generator.yandex_gpt.is_active else '❌ Не настроен'}
                    </div>
                    
                    <div class="status {'success' if elite_channel.ai_generator.deepseek_gpt.is_active else 'warning'}">
                        <strong>🤖 DeepSeek:</strong> {'✅ Активен' if elite_channel.ai_generator.deepseek_gpt.is_active else '❌ Не настроен'}
                    </div>
                    
                    <div class="schedule">
                        <h3>📅 Расписание на сегодня:</h3>
                        <div class="schedule-item"><span class="emoji">🥞</span><span class="time">07:00</span> Завтрак {schedule_status['breakfast']}</div>
                        <div class="schedule-item"><span class="emoji">🍽️</span><span class="time">12:00</span> Обед {schedule_status['lunch']}</div>
                        <div class="schedule-item"><span class="emoji">🧬</span><span class="time">15:00</span> Наука {schedule_status['science']}</div>
                        <div class="schedule-item"><span class="emoji">🎨</span><span class="time">16:00</span> Визуал {schedule_status['visual']}</div>
                        <div class="schedule-item"><span class="emoji">💬</span><span class="time">18:00</span> Интерактив {schedule_status['interactive']}</div>
                        <div class="schedule-item"><span class="emoji">🍽️</span><span class="time">19:00</span> Ужин {schedule_status['dinner']}</div>
                        <div class="schedule-item"><span class="emoji">🌟</span><span class="time">21:00</span> Советы экспертов {schedule_status['expert_advice']}</div>
                    </div>
                    
                    <div class="buttons">
                        <a href="/test" class="btn">🧪 Тест системы</a>
                        <a href="/force/breakfast" class="btn">🚀 Отправить завтрак</a>
                        <a href="/force/science" class="btn">🔬 Отправить науку</a>
                        <a href="/debug" class="btn">🔧 Диагностика</a>
                    </div>
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return f"<h1>❌ Ошибка: {e}</h1>"

@app.route('/test')
def test():
    """Тестовая отправка"""
    test_message = "🧪 ТЕСТ СИСТЕМЫ\n\nСистема @ppsupershef работает корректно! ✅\n\nВремя Кемерово: " + elite_channel.get_kemerovo_time().strftime('%H:%M')
    success = elite_channel.send_to_telegram(test_message)
    return f"Тест отправлен: {'✅ Успешно' if success else '❌ Ошибка'}"

@app.route('/force/<content_type>')
def force_publish(content_type):
    """Принудительная отправка"""
    valid_types = ['breakfast', 'lunch', 'dinner', 'science', 'visual', 'interactive', 'expert_advice']
    if content_type not in valid_types:
        return f"❌ Неверный тип. Используйте: {', '.join(valid_types)}"
    
    elite_channel.publish_content(content_type)
    return f"✅ Принудительно отправлен {content_type}"

@app.route('/debug')
def debug():
    """Диагностика"""
    kemerovo_time = elite_channel.get_kemerovo_time()
    return jsonify({
        "system": "@ppsupershef",
        "status": "active",
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "ai_services": {
            "yandex_gpt": elite_channel.ai_generator.yandex_gpt.is_active,
            "deepseek": elite_channel.ai_generator.deepseek_gpt.is_active
        },
        "telegram": {
            "token_set": bool(TELEGRAM_TOKEN),
            "channel_set": bool(TELEGRAM_CHANNEL)
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"🚀 Запуск системы @ppsupershef на порту {port}")
    print(f"📍 Время Кемерово: {elite_channel.get_kemerovo_time().strftime('%d.%m %H:%M')}")
    app.run(host='0.0.0.0', port=port, debug=False)
