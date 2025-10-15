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
TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')  # Группа для комментариев
YANDEX_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

class CommentManager:
    def __init__(self, ai_generator):
        self.ai_generator = ai_generator
        self.processed_comments = set()  # Чтобы не отвечать дважды
        self.expert_roles = {
            "nutritionist": "🧬 Нутрициолог с 40-летним стажем",
            "chef": "👨‍🍳 Шеф-повар Мишлен", 
            "trainer": "💪 Фитнес-тренер мирового уровня"
        }
    
    def should_respond(self, comment_text, comment_id):
        """Определяем, нужно ли отвечать на комментарий"""
        if comment_id in self.processed_comments:
            return False
            
        # Не отвечаем на короткие/неинформативные комментарии
        if len(comment_text.strip()) < 10:
            return False
            
        # Ключевые слова, требующие ответа
        trigger_words = [
            'вопрос', 'помогите', 'посоветуй', 'как', 'почему', 
            'что', 'можно ли', 'стоит ли', 'подскажите', 'помоги',
            'рецепт', 'питание', 'диета', 'здоровье', 'похудение',
            'белки', 'жиры', 'углеводы', 'калории', 'метаболизм'
        ]
        
        comment_lower = comment_text.lower()
        return any(word in comment_lower for word in trigger_words)
    
    def generate_ai_response(self, comment_text, username, expert_role="nutritionist"):
        """Генерация ответа через AI"""
        
        prompt = f"""
        Ты {self.expert_roles[expert_role]}. Ответь на комментарий пользователя в кулинарном телеграм-канале.

        КОММЕНТАРИЙ ОТ {username}: "{comment_text}"

        Требования к ответу:
        - Будь экспертом, но дружелюбным
        - Ответь по существу, 2-3 предложения
        - Дай практический совет
        - Используй эмодзи для живости
        - Не повторяй вопрос пользователя
        - Подпишись как эксперт в конце

        Формат ответа:
        [Основной ответ с советом] [Эмодзи]

        💎 [Подпись эксперта]
        """
        
        response = self.ai_generator.generate_content(prompt, "advice")
        if response:
            return response
        
        # Fallback ответ
        return f"Спасибо за вопрос! Рекомендую проконсультироваться с специалистом для персонализированного совета. 💎\n\n{self.expert_roles[expert_role]}"
    
    def determine_expert_role(self, comment_text):
        """Определяем, какой эксперт должен ответить"""
        comment_lower = comment_text.lower()
        
        # Вопросы шеф-повару
        chef_keywords = ['рецепт', 'готовить', 'приготовление', 'ингредиенты', 'блюдо', 'вкус', 'кухня', 'шеф']
        if any(word in comment_lower for word in chef_keywords):
            return "chef"
        
        # Вопросы тренеру
        trainer_keywords = ['тренировка', 'спорт', 'упражнения', 'фитнес', 'мышцы', 'сила', 'выносливость']
        if any(word in comment_lower for word in trainer_keywords):
            return "trainer"
        
        # По умолчанию - нутрициолог
        return "nutritionist"
    
    def process_comment(self, comment_text, comment_id, username, message_id=None):
        """Обработка комментария и генерация ответа"""
        if not self.should_respond(comment_text, comment_id):
            return None
            
        try:
            # Определяем эксперта
            expert_role = self.determine_expert_role(comment_text)
            
            # Генерируем ответ
            response = self.generate_ai_response(comment_text, username, expert_role)
            
            # Помечаем как обработанный
            self.processed_comments.add(comment_id)
            
            print(f"🤖 Сгенерирован ответ на комментарий {comment_id} от {username}")
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

# Инициализация менеджера комментариев (добавить в EliteContentManager)
class EliteContentManager:
    def __init__(self):
        self.token = TELEGRAM_TOKEN
        self.channel = TELEGRAM_CHANNEL
        self.timezone_offset = 7
        self.ai_generator = AIContentGenerator()
        self.comment_manager = CommentManager(self.ai_generator)  # ← ДОБАВИТЬ ЭТУ СТРОЧКУ
        self.webhook_manager = TelegramWebhookManager(self.token, self.comment_manager)
        self.content_strategy = self._initialize_content_strategy()
        self.last_sent_times = {}
    
    # ... остальной код без изменений ...

# Глобальные объекты
elite_channel = EliteContentManager()

# Webhook endpoint для Telegram
@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Endpoint для получения webhook от Telegram"""
    try:
        data = request.get_json()
        
        # Логируем входящие данные для отладки
        print(f"📨 Входящий webhook: {json.dumps(data, ensure_ascii=False)[:500]}...")
        
        # Обрабатываем сообщение
        if 'message' in data:
            message = data['message']
            
            # Проверяем, что это комментарий в группе обсуждений
            chat_id = message.get('chat', {}).get('id')
            message_id = message.get('message_id')
            text = message.get('text', '')
            username = message.get('from', {}).get('username', 'Аноним')
            
            # Игнорируем сообщения от ботов и служебные сообщения
            if (message.get('from', {}).get('is_bot', False) or 
                not text.strip() or
                text.startswith('/')):
                return 'ok'
            
            # Обрабатываем комментарий
            response_text = elite_channel.comment_manager.process_comment(
                text, message_id, username, message_id
            )
            
            # Отправляем ответ если нужно
            if response_text:
                success = elite_channel.webhook_manager.send_reply(
                    chat_id, message_id, response_text
                )
                if success:
                    print(f"✅ Ответ отправлен на комментарий {message_id}")
                else:
                    print(f"❌ Ошибка отправки ответа на комментарий {message_id}")
        
        return 'ok'
        
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return 'error', 500

# Обновляем главную страницу с информацией о комментариях
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
        
        # Проверяем webhook
        webhook_status = "✅ Активен" if elite_channel.webhook_manager.webhook_url else "❌ Не настроен"
        
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
                    .feature {{ background: #d1ecf1; padding: 10px; border-radius: 5px; margin: 5px 0; }}
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
                        <strong>🤖 AI Генерация:</strong> {'✅ Активна' if elite_channel.ai_generator.yandex_gpt.is_active or elite_channel.ai_generator.deepseek_gpt.is_active else '❌ Не настроена'}
                    </div>
                    
                    <div class="status {'success' if elite_channel.webhook_manager.webhook_url else 'warning'}">
                        <strong>🤖 Ответы на комментарии:</strong> {webhook_status}
                    </div>
                    
                    <div class="feature">
                        <strong>🎯 Автоответы на комментарии:</strong>
                        <br>• 🧬 Нутрициолог - научные вопросы
                        <br>• 👨‍🍳 Шеф - рецепты и готовка  
                        <br>• 💪 Тренер - фитнес и активность
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
                        <a href="/setup-webhook" class="btn">🔗 Настроить Webhook</a>
                        <a href="/force/breakfast" class="btn">🚀 Отправить завтрак</a>
                        <a href="/debug" class="btn">🔧 Диагностика</a>
                    </div>
                </div>
            </body>
        </html>
        """
    except Exception as e:
        return f"<h1>❌ Ошибка: {e}</h1>"

# Endpoint для настройки webhook
@app.route('/setup-webhook')
def setup_webhook():
    """Настройка webhook для Telegram"""
    webhook_url = f"https://{request.host}/webhook/telegram"
    success = elite_channel.webhook_manager.setup_webhook(webhook_url)
    
    if success:
        return f"""
        <html>
            <body>
                <h2>✅ Webhook настроен!</h2>
                <p><strong>URL:</strong> {webhook_url}</p>
                <p>Теперь бот будет автоматически отвечать на комментарии в группе обсуждений.</p>
                <a href="/">← Назад</a>
            </body>
        </html>
        """
    else:
        return f"""
        <html>
            <body>
                <h2>❌ Ошибка настройки webhook</h2>
                <p>Проверьте токен бота и доступность URL.</p>
                <a href="/">← Назад</a>
            </body>
        </html>
        """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    # Автоматическая настройка webhook при запуске
    webhook_url = f"https://food-telegram-bot.onrender.com/webhook/telegram"
    elite_channel.webhook_manager.setup_webhook(webhook_url)
    
    print(f"🚀 Запуск системы @ppsupershef на порту {port}")
    print(f"📍 Время Кемерово: {elite_channel.get_kemerovo_time().strftime('%d.%m %H:%M')}")
    print(f"🔗 Webhook: {webhook_url}")
    app.run(host='0.0.0.0', port=port, debug=False)
