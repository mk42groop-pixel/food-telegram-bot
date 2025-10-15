import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime
from threading import Thread
from flask import Flask, request, jsonify

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8459555322:AAHeddx-gWdcYXYkQHzyb9w7he9AHmZLhmA')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY', 'AQVN3PPgJleV36f1uQeT6F_Ph5oI5xTyFPNf18h-')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-8af2b1f4bce441f8a802c2653516237a')

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        logger.info(f"✅ Инициализирован канал с ID: {self.channel}")
    
    def send_to_telegram(self, message, parse_mode='HTML'):
        """Отправка сообщения в Telegram канал"""
        try:
            if not self.token or not self.channel:
                logger.error("❌ Токен или ID канала не установлены")
                return False
            
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.channel,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Сообщение отправлено в канал {self.channel}")
                return True
            else:
                error_msg = result.get('description', 'Unknown error')
                logger.error(f"❌ Ошибка отправки: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False

    def test_connection(self):
        """Тестирование подключения к каналу"""
        try:
            if not self.token:
                return {"status": "error", "message": "Токен бота не установлен"}
            
            url = f"https://api.telegram.org/bot{self.token}/getMe"
            response = requests.get(url, timeout=10)
            bot_info = response.json()
            
            if not bot_info.get('ok'):
                return {"status": "error", "message": "Неверный токен бота"}
            
            return {
                "status": "success", 
                "bot": bot_info['result']['username'],
                "channel_id": self.channel
            }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        logger.info("✅ Инициализирован генератор контента")
    
    def generate_with_yandex_gpt(self, prompt):
        """Генерация контента через Yandex GPT"""
        try:
            if not self.yandex_key:
                logger.error("❌ Yandex GPT API ключ не установлен")
                return None
            
            url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
            headers = {
                'Authorization': f'Api-Key {self.yandex_key}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'modelUri': f'gpt://{self.yandex_folder}/yandexgpt-lite',
                'completionOptions': {
                    'stream': False,
                    'temperature': 0.7,
                    'maxTokens': 800
                },
                'messages': [
                    {
                        'role': 'system',
                        'text': 'Ты эксперт по кулинарии и здоровому питанию. Создавай качественный контент.'
                    },
                    {
                        'role': 'user',
                        'text': prompt
                    }
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            result = response.json()
            
            if 'result' in result:
                return result['result']['alternatives'][0]['message']['text']
            else:
                logger.error(f"Ошибка Yandex GPT: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Исключение в Yandex GPT: {str(e)}")
            return None
    
    def generate_breakfast(self):
        """Генерация контента для завтрака"""
        prompt = "Создай рецепт полезного завтрака с описанием и пользой для здоровья"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"🍳 ЗАВТРАК\n\n{content}\n\n#завтрак #рецепт #здоровоепитание"
        return "🍳 ЗАВТРАК\n\nНачните день с полезного завтрака! Овсянка с ягодами и орехами - отличный выбор.\n\n#завтрак #здоровоепитание"
    
    def generate_lunch(self):
        """Генерация контента для обеда"""
        prompt = "Придумай рецепт питательного обеда для активного дня"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"🍲 ОБЕД\n\n{content}\n\n#обед #рецепт #питание"
        return "🍲 ОБЕД\n\nСбалансированный обед - залог продуктивного дня. Не пропускайте основной прием пищи!\n\n#обед #питание"
    
    def generate_science(self):
        """Генерация научного контента"""
        prompt = "Напиши короткий научный факт о питании или кулинарии"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"🔬 НАУКА\n\n{content}\n\n#наука #факты #питание"
        return "🔬 НАУКА\n\nИсследования показывают: регулярное питание улучшает метаболизм и поддерживает здоровый вес.\n\n#наука #питание"
    
    def generate_interval(self):
        """Генерация контента про интервалы"""
        prompt = "Напиши короткую мысль о перерывах в питании или интервальном голодании"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"⏱️ ИНТЕРВАЛ\n\n{content}\n\n#интервал #перерыв #питание"
        return "⏱️ ИНТЕРВАЛ\n\nПерерывы между приемами пищи важны для пищеварения. Оптимальный интервал - 3-4 часа.\n\n#интервал #питание"
    
    def generate_dinner(self):
        """Генерация контента для ужина"""
        prompt = "Предложи рецепт легкого ужина для хорошего сна"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"🍽️ УЖИН\n\n{content}\n\n#ужин #рецепт #здоровье"
        return "🍽️ УЖИН\n\nЛегкий ужин за 3 часа до сна способствует качественному отдыху и восстановлению.\n\n#ужин #здоровье"
    
    def generate_expert_advice(self):
        """Генерация совета эксперта"""
        prompt = "Дай практический совет по улучшению пищевых привычек"
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return f"💡 СОВЕТ ЭКСПЕРТА\n\n{content}\n\n#совет #эксперт #кулинария"
        return "💡 СОВЕТ ЭКСПЕРТА\n\nПейте воду за 30 минут до еды - это улучшает пищеварение и помогает контролировать аппетит.\n\n#совет #эксперт"

# Расписание публикаций
class ContentScheduler:
    def __init__(self):
        self.schedule = {
            "07:00": {"type": "breakfast", "name": "🍳 Завтрак", "generator": "generate_breakfast"},
            "12:00": {"type": "lunch", "name": "🍲 Обед", "generator": "generate_lunch"},
            "16:00": {"type": "science", "name": "🔬 Наука", "generator": "generate_science"},
            "18:00": {"type": "interval", "name": "⏱️ Интервал", "generator": "generate_interval"},
            "19:00": {"type": "dinner", "name": "🍽️ Ужин", "generator": "generate_dinner"},
            "21:00": {"type": "expert_advice", "name": "💡 Советы экспертов", "generator": "generate_expert_advice"}
        }
        self.is_running = False
        logger.info("✅ Инициализирован планировщик контента")
    
    def get_schedule(self):
        return self.schedule
    
    def get_next_event(self):
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        times_today = [t for t in self.schedule.keys() if t > current_time]
        if times_today:
            next_time = min(times_today)
            return next_time, self.schedule[next_time]
        
        first_time_tomorrow = min(self.schedule.keys())
        return first_time_tomorrow, self.schedule[first_time_tomorrow]
    
    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        logger.info("🚀 Запуск планировщика публикаций...")
        
        def schedule_job(time_str, content_type):
            method_name = self.schedule[time_str]['generator']
            method = getattr(content_gen, method_name)
            
            def job():
                logger.info(f"🕒 Выполнение: {content_type}")
                content = method()
                if content:
                    success = elite_channel.send_to_telegram(content)
                    if success:
                        logger.info(f"✅ Успешная публикация: {content_type}")
            
            schedule.every().day.at(time_str).do(job)
            logger.info(f"✅ Запланировано: {time_str} - {content_type}")
        
        for time_str, event in self.schedule.items():
            schedule_job(time_str, event['type'])
        
        self.is_running = True
        
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        logger.info("✅ Планировщик запущен")

# Инициализация компонентов
elite_channel = EliteChannel()
content_gen = ContentGenerator()
content_scheduler = ContentScheduler()

# Запускаем планировщик при старте
try:
    content_scheduler.start_scheduler()
    logger.info("✅ Все компоненты инициализированы")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    try:
        next_time, next_event = content_scheduler.get_next_event()
        connection_info = elite_channel.test_connection()
        
        html = f"""
        <html>
            <head>
                <title>Система управления @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                    .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                    .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }}
                    .schedule {{ background: #ecf0f1; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                    .event {{ padding: 10px; margin: 5px 0; background: white; border-left: 4px solid #3498db; }}
                    .status-success {{ color: #27ae60; }}
                    .status-error {{ color: #e74c3c; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🍳 Система управления @ppsupershef</h1>
                        <p>ID канала: {Config.TELEGRAM_CHANNEL}</p>
                        <p class="status-{'success' if connection_info.get('status') == 'success' else 'error'}">
                            Статус: {connection_info.get('status', 'unknown')}
                        </p>
                    </div>
                    
                    <div class="schedule">
                        <h2>📅 Расписание публикаций</h2>
        """
        
        for time_str, event in content_scheduler.schedule.items():
            is_next = " (Следующая)" if time_str == next_time else ""
            html += f'<div class="event">{time_str} - {event["name"]}{is_next}</div>'
        
        html += f"""
                    </div>
                    
                    <div>
                        <h3>⚡ Быстрые действия</h3>
                        <a class="btn" href="/test-channel">Тест канала</a>
                        <a class="btn" href="/debug">Отладка</a>
                        <a class="btn" href="/health">Health Check</a>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <h3>📤 Отправка контента</h3>
        """
        
        for event in content_scheduler.schedule.values():
            html += f'<a class="btn" href="/send-now/{event["type"]}" style="background: #9b59b6;">{event["name"]}</a>'
        
        html += f"""
                    </div>
                    
                    <div style="margin-top: 20px; color: #7f8c8d;">
                        <p>Следующая публикация: <strong>{next_time} - {next_event['name']}</strong></p>
                        <p>Время сервера: {datetime.now().strftime('%H:%M:%S')}</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"""
        <html>
            <body>
                <h1>Система управления @ppsupershef</h1>
                <p>Ошибка: {str(e)}</p>
                <p><a href="/debug">Перейти к отладке</a></p>
            </body>
        </html>
        """

@app.route('/debug')
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    
    return jsonify({
        "status": "active",
        "telegram_channel_id": Config.TELEGRAM_CHANNEL,
        "channel_username": "@ppsupershef",
        "bot_token_exists": bool(Config.TELEGRAM_BOT_TOKEN),
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "connection_test": connection_test,
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "environment": "production" if os.getenv('PRODUCTION') else "development"
    })

@app.route('/send-now/<content_type>')
def send_now(content_type):
    """Немедленная отправка контента"""
    try:
        content = None
        
        if content_type == 'breakfast':
            content = content_gen.generate_breakfast()
        elif content_type == 'lunch':
            content = content_gen.generate_lunch()
        elif content_type == 'science':
            content = content_gen.generate_science()
        elif content_type == 'dinner':
            content = content_gen.generate_dinner()
        elif content_type == 'interval':
            content = content_gen.generate_interval()
        elif content_type == 'expert_advice':
            content = content_gen.generate_expert_advice()
        else:
            return jsonify({
                "status": "error", 
                "message": f"Неизвестный тип контента: {content_type}"
            })
        
        if not content:
            return jsonify({
                "status": "error",
                "message": "Не удалось сгенерировать контент"
            })
        
        success = elite_channel.send_to_telegram(content)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Контент '{content_type}' отправлен в канал",
                "channel_id": Config.TELEGRAM_CHANNEL
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Не удалось отправить '{content_type}'"
            })
            
    except Exception as e:
        logger.error(f"❌ Ошибка в send-now: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Исключение: {str(e)}"
        })

@app.route('/test-channel')
def test_channel():
    """Тестирование подключения к каналу"""
    test_message = f"✅ ТЕСТ: Канал @ppsupershef работает! Время: {datetime.now().strftime('%H:%M:%S')}"
    
    success = elite_channel.send_to_telegram(test_message)
    
    return jsonify({
        "status": "success" if success else "error",
        "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки",
        "channel_id": Config.TELEGRAM_CHANNEL,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    connection = elite_channel.test_connection()
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "telegram_connection": connection,
        "scheduler_running": content_scheduler.is_running,
        "channel": "@ppsupershef"
    })

if __name__ == '__main__':
    logger.info(f"🚀 Запуск приложения для канала: @ppsupershef")
    logger.info(f"📋 ID канала: {Config.TELEGRAM_CHANNEL}")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
