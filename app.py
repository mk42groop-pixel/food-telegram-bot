import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request, jsonify, render_template_string
import pytz
import random

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Безопасная загрузка конфигурации
class Config:
    def __init__(self):
        self.TELEGRAM_BOT_TOKEN = self._get_env_safe('TELEGRAM_BOT_TOKEN')
        self.TELEGRAM_CHANNEL = self._get_env_safe('TELEGRAM_CHANNEL', '-1003152210862')
        self.TELEGRAM_GROUP = self._get_env_safe('TELEGRAM_GROUP', '@ppsupershef_chat')
        self.YANDEX_GPT_API_KEY = self._get_env_safe('YANDEX_GPT_API_KEY')
        self.YANDEX_FOLDER_ID = self._get_env_safe('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
        self.DEEPSEEK_API_KEY = self._get_env_safe('DEEPSEEK_API_KEY')
        
        # Настройки часовых поясов
        self.SERVER_TIMEZONE = pytz.timezone('UTC')
        self.KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')
        
        self._validate_config()

    def _get_env_safe(self, key, default=None):
        """Безопасное получение переменных окружения"""
        value = os.getenv(key, default)
        if value is None:
            logger.warning(f"⚠️ Переменная окружения {key} не установлена")
        return value

    def _validate_config(self):
        """Проверка обязательных конфигураций"""
        required = ['TELEGRAM_BOT_TOKEN', 'YANDEX_GPT_API_KEY']
        missing = [key for key in required if not getattr(self, key)]
        
        if missing:
            error_msg = f"❌ Отсутствуют обязательные переменные: {', '.join(missing)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info("✅ Конфигурация загружена безопасно")

# Инициализация конфигурации
try:
    config = Config()
except ValueError as e:
    logger.error(f"Критическая ошибка конфигурации: {e}")
    exit(1)

class ContentFormatter:
    """Класс для форматирования контента"""
    
    EMOTIONAL_TRIGGERS = {
        'achievement': [
            "💫 Станьте версией себя, которой восхищаетесь",
            "🚀 Еда - ваш союзник в достижении амбиций", 
        ],
        'transformation': [
            "🌟 Превратите прием пищи в инструмент роста",
            "🎯 Осознанное питание - конкурентное преимущество",
        ]
    }
    
    REACTIONS = [
        {"emoji": "😋", "text": "вкусно"},
        {"emoji": "💪", "text": "полезно"},
        {"emoji": "👨‍🍳", "text": "приготовлю"},
    ]

    @staticmethod
    def get_emotional_trigger():
        """Возвращает случайный эмоциональный триггер"""
        all_triggers = []
        for category in ContentFormatter.EMOTIONAL_TRIGGERS.values():
            all_triggers.extend(category)
        return random.choice(all_triggers) if all_triggers else "🎯 Начните свой путь к осознанному питанию"

    @staticmethod
    def format_philosophy_content(title, content, content_type):
        """Форматирует контент с философией осознанного долголетия"""
        trigger = ContentFormatter.get_emotional_trigger()
        
        reactions_line = " | ".join([f"{reaction['emoji']} {reaction['text']}" for reaction in ContentFormatter.REACTIONS])
        
        formatted_content = f"""🎪 КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ

{trigger}

{title}

{content}

---
💫 Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию

📢 Подписывайтесь на канал! → @ppsupershef
💬 Обсуждаем в комментариях! → @ppsupershef_chat

{reactions_line}

🔄 Поделитесь с друзьями! → @ppsupershef"""
        
        return formatted_content

class TimeZoneConverter:
    """Класс для конвертации времени между часовыми поясами"""
    
    @staticmethod
    def kemerovo_to_server_time(kemerovo_time_str):
        """Конвертирует время из Кемерово в серверное время"""
        try:
            today = datetime.now(config.KEMEROVO_TIMEZONE).date()
            kemerovo_dt = datetime.combine(today, datetime.strptime(kemerovo_time_str, '%H:%M').time())
            kemerovo_dt = config.KEMEROVO_TIMEZONE.localize(kemerovo_dt)
            server_dt = kemerovo_dt.astimezone(config.SERVER_TIMEZONE)
            return server_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def get_current_times():
        """Возвращает текущее время в обоих часовых поясах"""
        try:
            server_now = datetime.now(config.SERVER_TIMEZONE)
            kemerovo_now = datetime.now(config.KEMEROVO_TIMEZONE)
            
            return {
                'server_time': server_now.strftime('%H:%M:%S'),
                'kemerovo_time': kemerovo_now.strftime('%H:%M:%S'),
                'server_timezone': str(config.SERVER_TIMEZONE),
                'kemerovo_timezone': str(config.KEMEROVO_TIMEZONE)
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения времени: {e}")
            return {
                'server_time': '00:00:00',
                'kemerovo_time': '00:00:00',
                'server_timezone': 'UTC',
                'kemerovo_timezone': 'Asia/Novokuznetsk'
            }

class TelegramPolls:
    """Класс для работы с опросами в Telegram"""
    
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def create_poll(self, chat_id, question, options, is_anonymous=True, allows_multiple_answers=False):
        """Создание опроса в Telegram"""
        try:
            url = f"{self.base_url}/sendPoll"
            payload = {
                'chat_id': chat_id,
                'question': question,
                'options': options,
                'is_anonymous': is_anonymous,
                'allows_multiple_answers': allows_multiple_answers,
                'type': 'regular'
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Опрос создан: {question}")
                return result['result']
            else:
                logger.error(f"❌ Ошибка создания опроса: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение при создании опроса: {str(e)}")
            return None

class ChannelAnalytics:
    """Класс для сбора и анализа статистики канала"""
    
    def __init__(self, bot_token, channel_id):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
    def get_member_count(self):
        """Получение количества подписчиков"""
        try:
            url = f"{self.base_url}/getChatMembersCount"
            payload = {
                'chat_id': self.channel_id
            }
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            if result.get('ok'):
                return result['result']
            return 0
        except Exception as e:
            logger.error(f"❌ Ошибка получения количества подписчиков: {e}")
            return 0
    
    def generate_public_report(self):
        """Генерация публичного отчета для канала"""
        try:
            member_count = self.get_member_count()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            report = f"""📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ КАНАЛА @ppsupershef

👥 Подписчиков: {member_count}
📅 Дата: {current_time}
📍 Время Кемерово: {TimeZoneConverter.get_current_times()['kemerovo_time']}

💫 СЕГОДНЯ В КАНАЛЕ:
• 🧠 Нейропитание для ясности ума
• 💪 Энергия для достижений
• 🛡️ Стратегии долголетия

🎯 ПРИСОЕДИНЯЙТЕСЬ К КЛУБУ ОСОЗНАННОГО ДОЛГОЛЕТИЯ!

#отчет #статистика #клуб"""
            
            return report
        except Exception as e:
            logger.error(f"❌ Ошибка генерации отчета: {e}")
            return "📊 Отчет временно недоступен"

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.channel = config.TELEGRAM_CHANNEL
        self.group = config.TELEGRAM_GROUP
        self.polls_manager = TelegramPolls(self.token)
        self.formatter = ContentFormatter()
        
        if not self.token:
            logger.error("❌ Токен бота не установлен")
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен")
            
        logger.info("✅ Инициализирован менеджер Telegram канала")
    
    def send_to_telegram(self, message, parse_mode='HTML'):
        """Безопасная отправка сообщения в Telegram канал"""
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
                logger.info("✅ Сообщение отправлено в канал")
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
    
    def diagnose_channel(self):
        """Полная диагностика канала"""
        try:
            diagnosis = {
                "status": "running",
                "checks": [],
                "summary": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Проверка токена
            if not self.token:
                diagnosis["checks"].append({"check": "Токен бота", "status": "❌ Ошибка", "details": "Токен не установлен"})
                diagnosis["status"] = "error"
            else:
                diagnosis["checks"].append({"check": "Токен бота", "status": "✅ Успех", "details": "Токен установлен"})
            
            # Проверка бота
            bot_info = self.test_connection()
            if bot_info["status"] == "success":
                diagnosis["checks"].append({"check": "Доступность бота", "status": "✅ Успех", "details": f"Бот: @{bot_info['bot']}"})
            else:
                diagnosis["checks"].append({"check": "Доступность бота", "status": "❌ Ошибка", "details": bot_info["message"]})
                diagnosis["status"] = "error"
            
            # Проверка канала
            if not self.channel:
                diagnosis["checks"].append({"check": "ID канала", "status": "❌ Ошибка", "details": "ID канала не установлен"})
                diagnosis["status"] = "error"
            else:
                diagnosis["checks"].append({"check": "ID канала", "status": "✅ Успех", "details": f"Канал: {self.channel}"})
            
            # Проверка отправки сообщения
            if diagnosis["status"] != "error":
                test_message = "🔧 Тестовое сообщение диагностики"
                success = self.send_to_telegram(test_message)
                if success:
                    diagnosis["checks"].append({"check": "Отправка сообщений", "status": "✅ Успех", "details": "Тестовое сообщение отправлено"})
                else:
                    diagnosis["checks"].append({"check": "Отправка сообщений", "status": "❌ Ошибка", "details": "Не удалось отправить сообщение"})
                    diagnosis["status"] = "error"
            
            # Сводка
            if diagnosis["status"] == "error":
                diagnosis["summary"] = "❌ Требуется внимание: обнаружены критические ошибки"
            else:
                diagnosis["summary"] = "✅ Все системы работают нормально"
            
            return diagnosis
            
        except Exception as e:
            return {
                "status": "error",
                "checks": [{"check": "Общая диагностика", "status": "❌ Ошибка", "details": f"Исключение: {str(e)}"}],
                "summary": "❌ Ошибка диагностики",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = config.YANDEX_GPT_API_KEY
        self.yandex_folder = config.YANDEX_FOLDER_ID
        self.formatter = ContentFormatter()
        
        if not self.yandex_key:
            logger.warning("⚠️ Yandex GPT API ключ не установлен")
            
        logger.info("✅ Инициализирован генератор контента")

    def generate_energy_breakfast(self):
        """Генерация энерго-завтрака"""
        fallback = """🥣 Энергетическая овсянка с семенами

🎯 ИНГРЕДИЕНТЫ:
• 🌾 Овсяные хлопья - 50 г
• 🌰 Миндаль - 20 г
• 💎 Семена чиа - 1 ст.л.
• 🍌 Банан - 1 шт
• 🟤 Корица - ½ ч.л.

🎯 ПРИГОТОВЛЕНИЕ:
1. Залейте овсянку горячей водой на 5 минут
2. Добавьте нарезанный банан и семена чиа
3. Посыпьте миндалем и корицей

💡 НАУЧНОЕ ОБОСНОВАНИЕ:
🌾 Овсянка дает медленные углеводы для стабильной энергии
💎 Семена чиа - омега-3 для митохондрий"""
        
        return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", fallback, "breakfast")

    def generate_smart_shopping_list(self):
        """Генерация умного чек-листа покупок"""
        season = self._get_current_season()
        
        shopping_list = f"""🛒 УМНЫЙ ЧЕК-ЛИСТ НА НЕДЕЛЮ

🎯 Основа для осознанного долголетия ({season})

🧠 ДЛЯ МОЗГА И НЕРВНОЙ СИСТЕМЫ:
• 🌰 Грецкие орехи - 200 г
• 🥑 Авокадо - 3-4 шт
• 🐟 Жирная рыба - 500 г
• 🥚 Яйца - 10 шт

💪 ДЛЯ ЭНЕРГИИ И ТОНУСА:
• 🌾 Овсяные хлопья - 500 г
• 🍌 Бананы - 1 кг
• 💎 Семена чиа - 100 г

🎯 ФИЛОСОФИЯ ПОКУПОК:
Каждый продукт - инвестиция в ваше долголетие!

#чеклист #умныепокупки #{season}"""
        
        return shopping_list

    def _get_current_season(self):
        """Определяет текущий сезон"""
        month = datetime.now().month
        if month in [12, 1, 2]:
            return "зима"
        elif month in [3, 4, 5]:
            return "весна"
        elif month in [6, 7, 8]:
            return "лето"
        else:
            return "осень"

    def generate_expert_advice(self):
        """Генерация советов экспертов"""
        fallback = """🎯 Принцип: "Ешьте цвета радуги"

🎯 ФОРМУЛИРОВКА: Каждый день включайте в рацион продукты всех цветов радуги.

🔬 НАУЧНОЕ ОБОСНОВАНИЕ:
• 🔴 Красные - ликопин (против рака)
• 🟠 Оранжевые - бета-каротин (зрение)
• 🟢 Зеленые - лютеин (мозг)

💡 ПРОСТОЙ ШАГ: Добавьте 3 разных цвета в каждый прием пищи."""
        
        return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", fallback, "advice")

# Безопасная инициализация компонентов
def initialize_components():
    """Безопасная инициализация всех компонентов"""
    components = {}
    
    try:
        components['channel'] = EliteChannel()
        components['content_gen'] = ContentGenerator()
        components['analytics'] = ChannelAnalytics(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHANNEL)
        
        logger.info("✅ Все компоненты инициализированы")
        return components
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации компонентов: {e}")
        # Создаем заглушки для критически важных компонентов
        components['content_gen'] = ContentGenerator()
        components['analytics'] = ChannelAnalytics('dummy_token', 'dummy_channel')
        return components

# Инициализация
components = initialize_components()
elite_channel = components.get('channel')
content_gen = components['content_gen']
channel_analytics = components['analytics']

# Маршруты Flask
@app.route('/')
def index():
    """Главная страница"""
    try:
        current_times = TimeZoneConverter.get_current_times()
        member_count = channel_analytics.get_member_count()
        
        # Получаем русское название дня недели
        weekday_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        current_weekday = datetime.now(config.KEMEROVO_TIMEZONE).weekday()
        current_day_name = weekday_names[current_weekday]
        
        # Безопасные данные для интерфейса
        next_event_info = {
            'time': '07:00',
            'name': '🍳 Утренний завтрак'
        }
        
        html = f"""
        <html>
            <head>
                <title>Система управления @ppsupershef</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
                    .stats-card {{ background: #3498db; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .time-info {{ background: #27ae60; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
                    .btn-success {{ background: #27ae60; }}
                    .btn-warning {{ background: #f39c12; }}
                    .btn-info {{ background: #17a2b8; }}
                    .content-section {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                    .quick-actions {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .form-group {{ margin: 10px 0; }}
                    input, textarea {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }}
                    .day-info {{ background: #9b59b6; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .diagnosis-result {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 15px; margin: 10px 0; display: none; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎪 Система управления @ppsupershef</h1>
                        <p>🎯 ФИЛОСОФИЯ: Осознанное питание как инвестиция в энергичную жизнь</p>
                    </div>
                    
                    <div class="day-info">
                        <h2>📅 Сегодня: {current_day_name}</h2>
                    </div>
                    
                    <div class="quick-actions">
                        <button class="btn" onclick="testConnection()">Тест подключения</button>
                        <button class="btn btn-info" onclick="diagnoseChannel()">🔧 Диагностика</button>
                        <button class="btn" onclick="healthCheck()">Health Check</button>
                        <button class="btn btn-success" onclick="sendPublicReport()">📨 Отчет</button>
                    </div>
                    
                    <div class="content-section">
                        <h2>📤 Отправка контента</h2>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0;">
                            <button class="btn" onclick="sendContent('breakfast')">🍳 Завтрак</button>
                            <button class="btn" onclick="sendContent('shopping')">🛒 Чек-лист</button>
                            <button class="btn" onclick="sendContent('advice')">💡 Советы</button>
                        </div>
                        
                        <div class="form-group">
                            <h3>✍️ Ручной ввод</h3>
                            <textarea id="manualContent" rows="4" placeholder="Введите сообщение для Telegram..."></textarea>
                            <button class="btn btn-success" onclick="sendManualContent()">📤 Отправить</button>
                        </div>
                    </div>
                    
                    <div id="diagnosisResult" class="diagnosis-result">
                        <h3>🔧 Результаты диагностики</h3>
                        <div id="diagnosisContent"></div>
                    </div>
                    
                    <div class="stats-card">
                        <h2>📊 СТАТИСТИКА КАНАЛА</h2>
                        <p><strong>👥 Подписчиков: {member_count}</strong></p>
                        <p><strong>🎯 Философия: Осознанное долголетие</strong></p>
                    </div>
                    
                    <div class="time-info">
                        <h3>🌍 ИНФОРМАЦИЯ О ВРЕМЕНИ</h3>
                        <p>Сервер: <strong>{current_times['server_time']}</strong></p>
                        <p>Кемерово: <strong>{current_times['kemerovo_time']}</strong></p>
                    </div>
                </div>

                <script>
                    function testConnection() {{
                        fetch('/test-channel')
                            .then(response => response.json())
                            .then(data => alert('Результат: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')))
                            .catch(() => alert('❌ Ошибка сети'));
                    }}

                    function healthCheck() {{
                        fetch('/health')
                            .then(response => response.json())
                            .then(data => alert('Статус: ' + data.status))
                            .catch(() => alert('❌ Ошибка сети'));
                    }}

                    function diagnoseChannel() {{
                        fetch('/diagnose-channel')
                            .then(response => response.json())
                            .then(data => {{
                                const resultDiv = document.getElementById('diagnosisResult');
                                const contentDiv = document.getElementById('diagnosisContent');
                                
                                let html = `<h4>${{data.summary}}</h4>`;
                                html += `<p><strong>Время:</strong> ${{data.timestamp}}</p>`;
                                html += `<h5>Проверки:</h5>`;
                                
                                data.checks.forEach(check => {{
                                    html += `<div style="margin: 5px 0; padding: 5px; border-radius: 3px; background: #f8f9fa;">
                                        <strong>${{check.check}}</strong>: ${{check.status}} - ${{check.details}}
                                    </div>`;
                                }});
                                
                                contentDiv.innerHTML = html;
                                resultDiv.style.display = 'block';
                                resultDiv.scrollIntoView({{ behavior: 'smooth' }});
                            }})
                            .catch(() => alert('❌ Ошибка диагностики'));
                    }}

                    function sendPublicReport() {{
                        fetch('/send-public-report')
                            .then(response => response.json())
                            .then(data => alert('Отчет: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')))
                            .catch(() => alert('❌ Ошибка отправки'));
                    }}

                    function sendContent(type) {{
                        const endpoints = {{
                            'breakfast': '/send-breakfast',
                            'shopping': '/send-shopping-list',
                            'advice': '/send-advice'
                        }};

                        if (endpoints[type]) {{
                            fetch(endpoints[type])
                                .then(response => response.json())
                                .then(data => alert('Результат: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')))
                                .catch(() => alert('❌ Ошибка сети'));
                        }}
                    }}

                    function sendManualContent() {{
                        const content = document.getElementById('manualContent').value;
                        if (!content) {{
                            alert('Введите текст сообщения');
                            return;
                        }}

                        fetch('/send-manual-content', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ content: content }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Сообщение отправлено');
                                document.getElementById('manualContent').value = '';
                            }} else {{
                                alert('❌ Ошибка: ' + data.message);
                            }}
                        }})
                        .catch(() => alert('❌ Ошибка сети'));
                    }}
                </script>
            </body>
        </html>
        """
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"""
        <html>
            <head><title>Ошибка</title></head>
            <body>
                <h1>⚠️ Временные неполадки</h1>
                <p>Система временно недоступна. Попробуйте обновить страницу.</p>
                <p><small>Ошибка: {str(e)}</small></p>
            </body>
        </html>
        """

@app.route('/health')
def health_check():
    """Проверка здоровья системы"""
    try:
        current_times = TimeZoneConverter.get_current_times()
        member_count = channel_analytics.get_member_count()
        
        return jsonify({
            "status": "healthy",
            "components": {
                "telegram": elite_channel is not None,
                "content_generator": content_gen is not None,
                "analytics": channel_analytics is not None
            },
            "member_count": member_count,
            "timestamp": current_times['server_time']
        })
    except Exception as e:
        return jsonify({
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })

@app.route('/test-channel')
def test_channel():
    """Тестирование канала"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        current_times = TimeZoneConverter.get_current_times()
        test_message = f"""🎪 ТЕСТ СИСТЕМЫ

✅ Система управления каналом работает
🕐 Время: {current_times['kemerovo_time']}

#тест #диагностика"""
        
        success = elite_channel.send_to_telegram(test_message)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/diagnose-channel')
def diagnose_channel():
    """Диагностика канала"""
    try:
        if not elite_channel:
            return jsonify({
                "status": "error",
                "checks": [{"check": "Инициализация", "status": "❌ Ошибка", "details": "Канал не инициализирован"}],
                "summary": "❌ Критическая ошибка инициализации",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
        return jsonify(elite_channel.diagnose_channel())
    except Exception as e:
        return jsonify({
            "status": "error",
            "checks": [{"check": "Диагностика", "status": "❌ Ошибка", "details": str(e)}],
            "summary": "❌ Ошибка диагностики",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

@app.route('/send-public-report')
def send_public_report():
    """Отправка публичного отчета"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        report = channel_analytics.generate_public_report()
        success = elite_channel.send_to_telegram(report)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-breakfast')
def send_breakfast():
    """Отправка завтрака"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        content = content_gen.generate_energy_breakfast()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-shopping-list')
def send_shopping_list():
    """Отправка чек-листа покупок"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        content = content_gen.generate_smart_shopping_list()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-advice')
def send_advice():
    """Отправка советов экспертов"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        content = content_gen.generate_expert_advice()
        success = elite_channel.send_to_telegram(content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-manual-content', methods=['POST'])
def send_manual_content():
    """Отправка ручного контента"""
    try:
        if not elite_channel:
            return jsonify({"status": "error", "message": "Канал не инициализирован"})
            
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({"status": "error", "message": "Отсутствует содержимое"})
            
        content = data['content']
        if not content.strip():
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        current_times = TimeZoneConverter.get_current_times()
        content_with_footer = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
        
        success = elite_channel.send_to_telegram(content_with_footer)
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {str(error)}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    logger.info("🚀 Запуск безопасной системы управления Telegram каналом")
    logger.info("🔐 Все токены защищены")
    
    # Простая проверка конфигурации
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN не установлен, некоторые функции будут недоступны")
    if not config.YANDEX_GPT_API_KEY:
        logger.warning("⚠️ YANDEX_GPT_API_KEY не установлен, генерация контента будет ограничена")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
