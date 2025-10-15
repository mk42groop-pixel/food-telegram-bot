import os
import requests
import time
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import json
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

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
TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

class YandexGPT:
    def __init__(self):
        self.api_key = YANDEX_API_KEY
        self.folder_id = YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
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
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result['result']['alternatives'][0]['message']['text']
            else:
                print(f"❌ Ошибка Yandex GPT API: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с Yandex GPT: {e}")
            return None

class DeepSeekGPT:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
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
            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"❌ Ошибка DeepSeek API: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"❌ Ошибка соединения с DeepSeek: {e}")
            return None

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

class CommentManager:
    def __init__(self, ai_generator):
        self.ai_generator = ai_generator
        self.processed_comments = set()
        self.expert_roles = {
            "nutritionist": "🧬 Нутрициолог с 40-летним стажем",
            "chef": "👨‍🍳 Шеф-повар Мишлен", 
            "trainer": "💪 Фитнес-тренер мирового уровня"
        }
    
    def should_respond(self, comment_text, comment_id):
        """Определяем, нужно ли отвечать на комментарий"""
        if comment_id in self.processed_comments:
            return False
            
        if len(comment_text.strip()) < 10:
            return False
            
        trigger_words = [
            'вопрос', 'помогите', 'посоветуй', 'как', 'почему', 
            'что', 'можно ли', 'стоит ли', 'подскажите', 'помоги',
            'рецепт', 'питание', 'диета', 'здоровье', 'похудение'
        ]
        
        comment_lower = comment_text.lower()
        return any(word in comment_lower for word in trigger_words)
    
    def generate_ai_response(self, comment_text, username, expert_role="nutritionist"):
        """Генерация ответа через AI"""
        
        prompt = f"""
        Ты {self.expert_roles[expert_role]}. Ответь на комментарий пользователя.

        КОММЕНТАРИЙ ОТ {username}: "{comment_text}"

        Требования:
        - Будь экспертом, но дружелюбным
        - Ответь по существу, 2-3 предложения
        - Дай практический совет
        - Используй эмодзи
        - Подпишись как эксперт

        Формат:
        [Ответ с советом] [Эмодзи]

        💎 [Подпись эксперта]
        """
        
        response = self.ai_generator.generate_content(prompt, "advice")
        if response:
            return response
        
        return f"Спасибо за вопрос! Рекомендую проконсультироваться с специалистом. 💎\n\n{self.expert_roles[expert_role]}"
    
    def determine_expert_role(self, comment_text):
        """Определяем, какой эксперт должен ответить"""
        comment_lower = comment_text.lower()
        
        chef_keywords = ['рецепт', 'готовить', 'приготовление', 'ингредиенты', 'блюдо', 'вкус']
        if any(word in comment_lower for word in chef_keywords):
            return "chef"
        
        trainer_keywords = ['тренировка', 'спорт', 'упражнения', 'фитнес', 'мышцы']
        if any(word in comment_lower for word in trainer_keywords):
            return "trainer"
        
        return "nutritionist"
    
    def process_comment(self, comment_text, comment_id, username, message_id=None):
        """Обработка комментария и генерация ответа"""
        if not self.should_respond(comment_text, comment_id):
            return None
            
        try:
            expert_role = self.determine_expert_role(comment_text)
            response = self.generate_ai_response(comment_text, username, expert_role)
            self.processed_comments.add(comment_id)
            
            print(f"🤖 Сгенерирован ответ на комментарий {comment_id}")
            return response
            
        except Exception as e:
            print(f"❌ Ошибка обработки комментария: {e}")
            return None

class TelegramWebhookManager:
    def __init__(self, token, comment_manager):
        self.token = token
        self.comment_manager = comment_manager
        self.webhook_url = None
    
    def setup_webhook(self, webhook_url):
        """Настройка webhook для Telegram"""
        self.webhook_url = webhook_url
        url = f"https://api.telegram.org/bot{self.token}/setWebhook"
        payload = {
            'url': webhook_url,
            'drop_pending_updates': True
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                print(f"✅ Webhook установлен: {webhook_url}")
                return True
            else:
                print(f"❌ Ошибка установки webhook: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения: {e}")
            return False
    
    def send_reply(self, chat_id, message_id, text):
        """Отправка ответа на комментарий"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown',
            'reply_to_message_id': message_id
        }
        
        try:
            response = requests.post(url, json=payload)
            return response.status_code == 200
        except Exception as e:
            print(f"❌ Ошибка отправки ответа: {e}")
            return False

class EliteContentManager:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.ai_generator = AIContentGenerator()
        self.comment_manager = CommentManager(self.ai_generator)
        self.webhook_manager = TelegramWebhookManager(self.token, self.comment_manager)
        self.content_strategy = self._initialize_content_strategy()
        self.last_sent_times = {}
        self.scheduler = None
        
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
            'breakfast': f"Создай рецепт полезного завтрака на тему: {theme}. Включи ингредиенты, приготовление и КБЖУ.",
            'lunch': f"Создай рецепт обеда для продуктивности на тему: {theme}. Включи ингредиенты, приготовление и КБЖУ.",
            'dinner': f"Создай рецепт легкого ужина для восстановления на тему: {theme}. Включи ингредиенты, приготовление и КБЖУ.",
            'science': f"Объясни научную концепцию питания на тему: {theme}. Сделай это простым и понятным языком.",
            'expert_advice': f"Дай практический совет от команды экспертов на тему: {theme}. Включи мнение нутрициолога, шефа и тренера.",
            'interactive': f"Создай интерактивный пост для обсуждения на тему: {theme}. Задай вопрос аудитории."
        }
        
        prompt = prompts.get(content_type)
        if not prompt:
            return None
            
        content = self.ai_generator.generate_content(prompt, content_type)
        if content:
            emoji = self._get_content_emoji(content_type)
            return f"{emoji} {content_type.upper()}\n\n{theme}\n\n{content}"
        
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
                "🌅 ЗАВТРАК: Овсянка с суперфудами\n\n🥗 Ингредиенты:\n• Овсяные хлопья - 50г\n• Молоко миндальное - 200мл\n• Семена чиа - 1 ст.л.\n• Ягоды годжи - 1 ст.л.\n\n👨‍🍳 Приготовление:\n1. Варить овсянку 5 минут\n2. Добавить суперфуды\n\n📊 КБЖУ: 280 ккал",
                "🌅 ЗАВТРАК: Авокадо-тост с яйцом-пашот\n\n🥗 Ингредиенты:\n• Хлеб цельнозерновой - 2 ломтика\n• Авокадо - ½ шт\n• Яйца - 2 шт\n\n👨‍🍳 Приготовление:\n1. Поджарить хлеб\n2. Размять авокадо\n3. Приготовить яйца-пашот\n\n📊 КБЖУ: 320 ккал"
            ],
            'lunch': [
                "🍽️ ОБЕД: Киноа с овощами\n\n🥗 Ингредиенты:\n• Киноа - 100г\n• Овощи гриль - 200г\n• Нут - 100г\n\n👨‍🍳 Приготовление:\n1. Отварить киноа\n2. Обжарить овощи\n3. Смешать с нутом\n\n📊 КБЖУ: 350 ккал"
            ],
            'dinner': [
                "🌙 УЖИН: Рыба на пару\n\n🥗 Ингредиенты:\n• Морской окунь - 200г\n• Брокколи - 150г\n• Морковь - 1 шт\n\n👨‍🍳 Приготовление:\n1. Приготовить на пару 15 мин\n2. Подать с овощами\n\n📊 КБЖУ: 250 ккал"
            ],
            'science': [
                "🧬 НАУКА: Циркадные ритмы\n\n📚 Факт: Прием пищи в правильное время ускоряет метаболизм\n\n💡 Практика: Завтракайте в течение часа после пробуждения"
            ],
            'interactive': [
                "💬 ИНТЕРАКТИВ: Ваш опыт\n\n❓ Как вы планируете свое питание на неделю?\n\n👇 Поделитесь в комментариях!\n\n❤️ - Планирую заранее\n🔥 - Импровизирую\n📚 - Слежу за КБЖУ"
            ],
            'expert_advice': [
                "🌟 СОВЕТ ЭКСПЕРТОВ\n\n🧬 Нутрициолог: 'Пейте воду за 30 минут до еды'\n👨‍🍳 Шеф: 'Используйте свежие травы'\n💪 Тренер: 'Сочетайте кардио и силовые'"
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

💬 **ОБСУЖДАЕМ В КОММЕНТАРИЯХ!**

👇 **РЕАКЦИИ:**
❤️ - Вкусно | 🔥 - Приготовлю | 📚 - Полезно

📤 **ПОДЕЛИТЕСЬ** с друзьями!

🏷️ #ppsupershef #ЗдоровоеПитание
"""

    def run_elite_scheduler(self):
        """Запуск расписания публикаций с учетом часового пояса"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            
        self.scheduler = BackgroundScheduler()
        # Часовой пояс Кемерово (Asia/Novokuznetsk или Asia/Krasnoyarsk)
        self.scheduler.configure(timezone='Asia/Novokuznetsk')
        
        # Добавляем задания с учетом часового пояса
        self.scheduler.add_job(
            lambda: self.publish_content('breakfast'),
            trigger=CronTrigger(hour=7, minute=0),
            id='breakfast',
            replace_existing=True
        )
        self.scheduler.add_job(
            lambda: self.publish_content('lunch'),
            trigger=CronTrigger(hour=12, minute=0),
            id='lunch',
            replace_existing=True
        )
        self.scheduler.add_job(
            lambda: self.publish_content('science'),
            trigger=CronTrigger(hour=15, minute=0),
            id='science',
            replace_existing=True
        )
        self.scheduler.add_job(
            lambda: self.publish_content('interactive'),
            trigger=CronTrigger(hour=18, minute=0),
            id='interactive',
            replace_existing=True
        )
        self.scheduler.add_job(
            lambda: self.publish_content('dinner'),
            trigger=CronTrigger(hour=19, minute=0),
            id='dinner',
            replace_existing=True
        )
        self.scheduler.add_job(
            lambda: self.publish_content('expert_advice'),
            trigger=CronTrigger(hour=21, minute=0),
            id='expert_advice',
            replace_existing=True
        )
        
        self.scheduler.start()
        
        kemerovo_time = self.get_kemerovo_time()
        print(f"🎯 РАСПИСАНИЕ АКТИВИРОВАНО!")
        print(f"📍 Кемерово: {kemerovo_time.strftime('%d.%m.%Y %H:%M')}")
        print("📊 Расписание:")
        print("🥞 07:00 - Завтрак")
        print("🍽️ 12:00 - Обед") 
        print("🧬 15:00 - Наука")
        print("💬 18:00 - Интерактив")
        print("🍽️ 19:00 - Ужин")
        print("🌟 21:00 - Советы экспертов")
        print("=" * 50)
        
        # Тестовый запуск
        print("🧪 Тест системы...")
        self.publish_content('breakfast')
        
        return self.scheduler
    
    def publish_content(self, content_type):
        """Публикация контента"""
        try:
            kemerovo_time = self.get_kemerovo_time()
            
            last_sent = self.last_sent_times.get(content_type)
            if last_sent and (kemerovo_time - last_sent).total_seconds() < 300:
                print(f"⏰ Пропускаем {content_type} - уже отправляли недавно")
                return
                
            print(f"📤 Публикация {content_type}... ({kemerovo_time.strftime('%H:%M')})")
            
            message = self.generate_elite_content(content_type)
            if not message:
                print(f"❌ Не удалось сгенерировать контент для {content_type}")
                return
                
            message += self._get_elite_call_to_action()
            
            success = self.send_to_telegram(message)
            
            if success:
                print(f"✅ {content_type.upper()} отправлен!")
                self.last_sent_times[content_type] = kemerovo_time
            else:
                print(f"❌ Ошибка отправки {content_type}")
                
        except Exception as e:
            print(f"❌ Ошибка в publish_content: {e}")
    
    def send_to_telegram(self, message):
        """Отправка сообщения в Telegram"""
        if not self.token or not self.channel:
            print("❌ Не настроен токен или канал")
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.channel,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                return True
            else:
                print(f"❌ Ошибка Telegram API: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Ошибка соединения с Telegram: {e}")
            return False

# Инициализация системы
elite_channel = EliteContentManager()

# Запускаем планировщик при старте приложения
scheduler = elite_channel.run_elite_scheduler()

@app.route('/')
def home():
    try:
        kemerovo_time = elite_channel.get_kemerovo_time()
        weekday = kemerovo_time.weekday()
        theme = elite_channel.content_strategy["weekly_themes"][weekday]
        
        now = kemerovo_time
        schedule_status = {
            'breakfast': "✅" if now.hour >= 7 else "⏰",
            'lunch': "✅" if now.hour >= 12 else "⏰", 
            'science': "✅" if now.hour >= 15 else "⏰",
            'interactive': "✅" if now.hour >= 18 else "⏰",
            'dinner': "✅" if now.hour >= 19 else "⏰",
            'expert_advice': "✅" if now.hour >= 21 else "⏰"
        }
        
        webhook_status = "✅ Активен" if elite_channel.webhook_manager.webhook_url else "❌ Не настроен"
        
        # Получаем статус заданий планировщика
        scheduler_jobs = []
        if elite_channel.scheduler:
            for job in elite_channel.scheduler.get_jobs():
                next_run = job.next_run_time.astimezone(pytz.timezone('Asia/Novokuznetsk')) if job.next_run_time else "Не запланировано"
                scheduler_jobs.append(f"{job.id}: {next_run}")
        
        return f"""
        <html>
            <head>
                <title>@ppsupershef - Система управления</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f0f2f5; }}
                    .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }}
                    .status {{ padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid; }}
                    .success {{ background: #e8f5e8; border-color: #4CAF50; }}
                    .warning {{ background: #fff3cd; border-color: #ffc107; }}
                    .schedule {{ background: #e9ecef; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                    .schedule-item {{ display: flex; align-items: center; margin: 8px 0; }}
                    .time {{ font-weight: bold; width: 80px; }}
                    .emoji {{ font-size: 20px; margin-right: 10px; }}
                    .btn {{ display: inline-block; padding: 10px 15px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }}
                    .jobs {{ background: #f8f9fa; padding: 10px; border-radius: 5px; margin: 10px 0; font-family: monospace; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🍳 @ppsupershef - Система управления</h1>
                    
                    <div class="status success">
                        <strong>📍 Кемерово:</strong> {kemerovo_time.strftime('%d.%m.%Y %H:%M')} | 
                        <strong>🎯 Тема:</strong> {theme} |
                        <strong>📱 Канал:</strong> @ppsupershef
                    </div>
                    
                    <div class="status {'success' if elite_channel.ai_generator.yandex_gpt.is_active or elite_channel.ai_generator.deepseek_gpt.is_active else 'warning'}">
                        <strong>🤖 AI Генерация:</strong> {'✅ Активна' if elite_channel.ai_generator.yandex_gpt.is_active or elite_channel.ai_generator.deepseek_gpt.is_active else '❌ Не настроена'}
                    </div>
                    
                    <div class="status {'success' if elite_channel.webhook_manager.webhook_url else 'warning'}">
                        <strong>🤖 Ответы на комментарии:</strong> {webhook_status}
                    </div>
                    
                    <div class="schedule">
                        <h3>📅 Расписание публикаций:</h3>
                        <div class="schedule-item"><span class="emoji">🥞</span><span class="time">07:00</span> Завтрак {schedule_status['breakfast']}</div>
                        <div class="schedule-item"><span class="emoji">🍽️</span><span class="time">12:00</span> Обед {schedule_status['lunch']}</div>
                        <div class="schedule-item"><span class="emoji">🧬</span><span class="time">15:00</span> Наука {schedule_status['science']}</div>
                        <div class="schedule-item"><span class="emoji">💬</span><span class="time">18:00</span> Интерактив {schedule_status['interactive']}</div>
                        <div class="schedule-item"><span class="emoji">🍽️</span><span class="time">19:00</span> Ужин {schedule_status['dinner']}</div>
                        <div class="schedule-item"><span class="emoji">🌟</span><span class="time">21:00</span> Советы экспертов {schedule_status['expert_advice']}</div>
                    </div>
                    
                    <div class="jobs">
                        <strong>📋 Задания планировщика:</strong><br>
                        {('<br>'.join(scheduler_jobs)) if scheduler_jobs else 'Планировщик не активен'}
                    </div>
                    
                    <div>
                        <a href="/test" class="btn">🧪 Тест системы</a>
                        <a href="/setup-webhook" class="btn">🔗 Настроить Webhook</a>
                        <a href="/restart-scheduler" class="btn">🔄 Перезапуск расписания</a>
                        <a href="/debug" class="btn">🔧 Диагностика</a>
                    </div>
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return f"<h1>❌ Ошибка: {e}</h1>"

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        
        if 'message' in data:
            message = data['message']
            chat_id = message.get('chat', {}).get('id')
            message_id = message.get('message_id')
            text = message.get('text', '')
            username = message.get('from', {}).get('username', 'Аноним')
            
            if (message.get('from', {}).get('is_bot', False) or 
                not text.strip() or
                text.startswith('/')):
                return 'ok'
            
            response_text = elite_channel.comment_manager.process_comment(
                text, message_id, username, message_id
            )
            
            if response_text:
                success = elite_channel.webhook_manager.send_reply(
                    chat_id, message_id, response_text
                )
                if success:
                    print(f"✅ Ответ отправлен на комментарий {message_id}")
        
        return 'ok'
        
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return 'error', 500

@app.route('/setup-webhook')
def setup_webhook():
    webhook_url = f"https://{request.host}/webhook/telegram"
    success = elite_channel.webhook_manager.setup_webhook(webhook_url)
    
    if success:
        return f"<h2>✅ Webhook настроен!</h2><p>URL: {webhook_url}</p><a href='/'>← Назад</a>"
    else:
        return f"<h2>❌ Ошибка настройки webhook</h2><a href='/'>← Назад</a>"

@app.route('/restart-scheduler')
def restart_scheduler():
    try:
        global scheduler
        if elite_channel.scheduler:
            elite_channel.scheduler.shutdown()
        
        scheduler = elite_channel.run_elite_scheduler()
        return "<h2>✅ Планировщик перезапущен!</h2><a href='/'>← Назад</a>"
    except Exception as e:
        return f"<h2>❌ Ошибка перезапуска: {e}</h2><a href='/'>← Назад</a>"

@app.route('/test')
def test():
    test_message = "🧪 ТЕСТ СИСТЕМЫ\n\nСистема @ppsupershef работает корректно! ✅\nВремя Кемерово: " + elite_channel.get_kemerovo_time().strftime('%d.%m.%Y %H:%M') + "\n\n🤖 AI системы активны и готовы к работе!"
    success = elite_channel.send_to_telegram(test_message)
    return f"Тест отправлен: {'✅ Успешно' if success else '❌ Ошибка'}<br><a href='/'>← Назад</a>"

@app.route('/debug')
def debug():
    kemerovo_time = elite_channel.get_kemerovo_time()
    
    # Проверяем доступность Telegram API
    telegram_status = "✅ Доступен"
    try:
        response = requests.get(f"https://api.telegram.org/bot{elite_channel.token}/getMe", timeout=10)
        if response.status_code != 200:
            telegram_status = f"❌ Ошибка: {response.status_code}"
    except Exception as e:
        telegram_status = f"❌ Ошибка: {e}"
    
    return jsonify({
        "system": "@ppsupershef",
        "status": "active",
        "kemerovo_time": kemerovo_time.strftime('%Y-%m-%d %H:%M:%S'),
        "telegram_api": telegram_status,
        "ai_services": {
            "yandex_gpt": elite_channel.ai_generator.yandex_gpt.is_active,
            "deepseek": elite_channel.ai_generator.deepseek_gpt.is_active
        },
        "scheduler": {
            "running": elite_channel.scheduler.running if elite_channel.scheduler else False,
            "jobs": len(elite_channel.scheduler.get_jobs()) if elite_channel.scheduler else 0
        },
        "last_sent": {k: v.strftime('%H:%M') for k, v in elite_channel.last_sent_times.items()}
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    # Автоматическая настройка webhook
    webhook_url = f"https://food-telegram-bot.onrender.com/webhook/telegram"
    elite_channel.webhook_manager.setup_webhook(webhook_url)
    
    print(f"🚀 Запуск системы @ppsupershef на порту {port}")
    print(f"📍 Время Кемерово: {elite_channel.get_kemerovo_time().strftime('%d.%m.%Y %H:%M')}")
    print(f"🤖 AI сервисы: YandexGPT - {'✅' if elite_channel.ai_generator.yandex_gpt.is_active else '❌'}, DeepSeek - {'✅' if elite_channel.ai_generator.deepseek_gpt.is_active else '❌'}")
    print(f"📅 Планировщик: {'✅ Активен' if scheduler.running else '❌ Не активен'}")
    
    app.run(host='0.0.0.0', port=port, debug=False)

