import os
import logging
import requests
import json
import time
import schedule
import hashlib
import re
from datetime import datetime, timedelta
from threading import Thread, Lock
from flask import Flask, request, jsonify, render_template_string
import pytz
import random
from dotenv import load_dotenv
from functools import wraps

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация - БЕЗОПАСНАЯ ВЕРСИЯ
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    
    # Настройки безопасности
    API_SECRET = os.getenv('API_SECRET', 'your-secret-key-here')
    MAX_REQUESTS_PER_MINUTE = 30
    RATE_LIMIT_WINDOW = 60
    
    # Настройки часовых поясов
    SERVER_TIMEZONE = pytz.timezone('UTC')
    KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')
    TIME_DIFFERENCE_HOURS = 7

# Система безопасности
class SecurityManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SecurityManager, cls).__new__(cls)
                cls._instance.request_log = {}
                cls._instance.blocked_ips = set()
            return cls._instance
    
    def check_rate_limit(self, ip_address):
        """Проверка ограничения запросов"""
        current_time = time.time()
        if ip_address in self.blocked_ips:
            return False
        
        if ip_address not in self.request_log:
            self.request_log[ip_address] = []
        
        # Очищаем старые записи
        self.request_log[ip_address] = [
            req_time for req_time in self.request_log[ip_address]
            if current_time - req_time < Config.RATE_LIMIT_WINDOW
        ]
        
        # Проверяем лимит
        if len(self.request_log[ip_address]) >= Config.MAX_REQUESTS_PER_MINUTE:
            self.blocked_ips.add(ip_address)
            logger.warning(f"🚨 IP заблокирован за превышение лимита: {ip_address}")
            return False
        
        self.request_log[ip_address].append(current_time)
        return True

# Декоратор для проверки API ключа
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key or api_key != Config.API_SECRET:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# Декоратор для rate limiting
def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip_address = request.remote_addr
        security_manager = SecurityManager()
        
        if not security_manager.check_rate_limit(ip_address):
            return jsonify({
                "status": "error", 
                "message": "Rate limit exceeded. Try again later."
            }), 429
        
        return f(*args, **kwargs)
    return decorated_function

# Безопасный логгер
class SecureLogger:
    @staticmethod
    def safe_log(message):
        """Безопасное логирование без чувствительных данных"""
        sensitive_patterns = [
            r'bot\d+:[A-Za-z0-9_-]{35}',
            r'api_key_[A-Za-z0-9]{20,}',
            r'token_[A-Za-z0-9]{20,}',
            r'[A-Za-z0-9]{40,}'  # Длинные строки которые могут быть токенами
        ]
        
        safe_message = message
        for pattern in sensitive_patterns:
            safe_message = re.sub(pattern, '[REDACTED]', safe_message)
        
        logger.info(safe_message)

# ДИАГНОСТИКА ТОКЕНОВ - БЕЗОПАСНАЯ ВЕРСИЯ
def safe_debug_tokens():
    """Безопасная диагностика токенов без их показа"""
    print("🔍 БЕЗОПАСНАЯ ДИАГНОСТИКА ТОКЕНОВ:")
    
    tokens_status = {
        'TELEGRAM_BOT_TOKEN': bool(os.getenv('TELEGRAM_BOT_TOKEN')),
        'YANDEX_GPT_API_KEY': bool(os.getenv('YANDEX_GPT_API_KEY')),
        'YANDEX_FOLDER_ID': bool(os.getenv('YANDEX_FOLDER_ID')),
        'DEEPSEEK_API_KEY': bool(os.getenv('DEEPSEEK_API_KEY'))
    }
    
    all_ok = True
    for name, has_value in tokens_status.items():
        if has_value:
            print(f"✅ {name}: Настроен")
        else:
            print(f"❌ {name}: НЕ НАЙДЕН!")
            all_ok = False
    
    # Проверяем файл .env
    if os.path.exists('.env'):
        print("✅ Файл .env найден")
        with open('.env', 'r') as f:
            content = f.read()
            print(f"📄 Содержимое .env: {len(content)} символов")
    else:
        print("❌ Файл .env НЕ найден!")
        all_ok = False
    
    return all_ok

class ContentFormatter:
    """Класс для форматирования контента с новой философией"""
    
    # Эмоциональные триггеры
    EMOTIONAL_TRIGGERS = {
        'achievement': [
            "Станьте версией себя, которой восхищаетесь",
            "Еда - ваш союзник в достижении амбиций", 
            "Инвестируйте в свое долголетие сегодня",
            "Каждая тарелка - шаг к лучшей версии себя"
        ],
        'transformation': [
            "Превратите прием пищи в инструмент роста",
            "Осознанное питание - конкурентное преимущество",
            "Ваше тело заслуживает лучшего топлива", 
            "Долголетие начинается с сегодняшнего ужина"
        ],
        'community': [
            "Присоединяйтесь к клубу тех, кто выбирает осознанность",
            "Вы не одиноки на пути к долголетию",
            "Сообщество единомышленников для вашего роста",
            "Вместе мы создаем культуру умного питания"
        ]
    }
    
    # Системный промпт для GPT - ОБНОВЛЕННЫЙ ФОРМАТ
    SYSTEM_PROMPT = """Ты эксперт по осознанному долголетию и нейропитанию, нутрициолог и Шеф-повар ресторанов Мишлен. Твоя задача - создавать контент, который превращает прием пищи в инструмент для улучшения качества жизни.

ФИЛОСОФИЯ: 
"Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь"

СТРУКТУРА КОНТЕНТА (20/30/40/10):
1. ЭМОЦИОНАЛЬНЫЙ КРЮЧОК (20%) - личная выгода, решение проблемы
2. НАУЧНЫЙ ФАКТ (30%) - доказанные исследования, механизмы действия
3. ПРАКТИЧЕСКИЙ РЕЦЕПТ (40%) - точные количества, пошаговый процесс
4. ПРИЗЫВ К ДЕЙСТВИЮ (10%) - конкретный следующий шаг

ТРЕБОВАНИЯ К ФОРМАТУ:
- Начинай с эмоционального триггера о качестве жизни
- Добавляй научное обоснование пользы ТЕЗИСНО
- Давай практические рецепты с точными количествами
- Объясняй механизм действия на организм ТЕЗИСНО
- Заканчивай призывом к осознанному действию

ОСОБЕННОСТИ РЕЦЕПТОВ:
- Техники шеф-повара Мишлен, адаптированные для дома
- Научно обоснованная польза каждого ингредиента
- Баланс вкуса и функциональности
- Доступные ингредиенты с максимальной пользой

ТОН:
- Дружеский, но экспертный
- Мотивирующий, но без излишнего энтузиазма  
- Научный, но доступный
- Вдохновляющий на изменения
"""
    
    # Реакции для сообщений
    REACTIONS = [
        {"emoji": "😋", "text": "вкусно"},
        {"emoji": "💪", "text": "полезно"},
        {"emoji": "👨‍🍳", "text": "приготовлю"},
        {"emoji": "📝", "text": "запишу себе"},
        {"emoji": "📚", "text": "на рецепты"}
    ]

    @staticmethod
    def get_emotional_trigger():
        """Возвращает случайный эмоциональный триггер"""
        all_triggers = []
        for category in ContentFormatter.EMOTIONAL_TRIGGERS.values():
            all_triggers.extend(category)
        return random.choice(all_triggers)

    @staticmethod
    def format_philosophy_content(title, content, content_type):
        """Форматирует контент с философией осознанного долголетия"""
        trigger = ContentFormatter.get_emotional_trigger()
        
        # Форматируем реакции
        reactions_line = " | ".join([f"{reaction['emoji']} {reaction['text']}" for reaction in ContentFormatter.REACTIONS])
        
        formatted_content = f"""🎪 <b>КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ</b>

{trigger}

{title}

{content}

---
💫 <b>Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию</b>

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

{reactions_line}

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""
        
        return formatted_content

class TimeZoneConverter:
    """Класс для конвертации времени между часовыми поясами"""
    
    @staticmethod
    def kemerovo_to_server_time(kemerovo_time_str):
        """Конвертирует время из Кемерово в серверное время"""
        try:
            today = datetime.now(Config.KEMEROVO_TIMEZONE).date()
            kemerovo_dt = datetime.combine(today, datetime.strptime(kemerovo_time_str, '%H:%M').time())
            kemerovo_dt = Config.KEMEROVO_TIMEZONE.localize(kemerovo_dt)
            server_dt = kemerovo_dt.astimezone(Config.SERVER_TIMEZONE)
            return server_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def server_to_kemerovo_time(server_time_str):
        """Конвертирует время из серверного в Кемерово время"""
        try:
            today = datetime.now(Config.SERVER_TIMEZONE).date()
            server_dt = datetime.combine(today, datetime.strptime(server_time_str, '%H:%M').time())
            server_dt = Config.SERVER_TIMEZONE.localize(server_dt)
            kemerovo_dt = server_dt.astimezone(Config.KEMEROVO_TIMEZONE)
            return kemerovo_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {server_time_str}: {e}")
            return server_time_str
    
    @staticmethod
    def get_current_times():
        """Возвращает текущее время в обоих часовых поясах"""
        server_now = datetime.now(Config.SERVER_TIMEZONE)
        kemerovo_now = datetime.now(Config.KEMEROVO_TIMEZONE)
        
        return {
            'server_time': server_now.strftime('%H:%M:%S'),
            'kemerovo_time': kemerovo_now.strftime('%H:%M:%S'),
            'server_date': server_now.strftime('%Y-%m-%d'),
            'kemerovo_date': kemerovo_now.strftime('%Y-%m-%d'),
            'server_timezone': str(Config.SERVER_TIMEZONE),
            'kemerovo_timezone': str(Config.KEMEROVO_TIMEZONE)
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
                SecureLogger.safe_log(f"✅ Опрос создан: {question}")
                return result['result']
            else:
                logger.error(f"❌ Ошибка создания опроса: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение при создании опроса: {str(e)}")
            return None

# СИСТЕМА АНАЛИТИКИ И МЕТРИК
class ChannelAnalytics:
    """Расширенный класс для сбора и анализа статистики канала"""
    
    def __init__(self, bot_token, channel_id):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.engagement_data = {}
        self.post_metrics = {}
        
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
    
    def track_post_engagement(self, message_id, content_type):
        """Начало отслеживания engagement для поста"""
        self.post_metrics[message_id] = {
            'content_type': content_type,
            'timestamp': datetime.now(),
            'views': 0,
            'reactions': {},
            'comments': 0,
            'shares': 0,
            'chat_clicks': 0,
            'relevance_score': self._calculate_relevance_score(content_type)
        }
    
    def _calculate_relevance_score(self, content_type):
        """Расчет релевантности контента по формуле 20/30/40/10"""
        base_scores = {
            'neuro_breakfast': 85,
            'energy_breakfast': 80,
            'longevity_breakfast': 90,
            'gastronomy_breakfast': 75,
            'science_content': 95,
            'expert_advice': 88
        }
        return base_scores.get(content_type, 75)
    
    def update_engagement(self, message_id, metric_type, value=1):
        """Обновление метрик engagement"""
        if message_id in self.post_metrics:
            if metric_type in self.post_metrics[message_id]:
                self.post_metrics[message_id][metric_type] += value
            else:
                self.post_metrics[message_id][metric_type] = value
    
    def get_engagement_report(self):
        """Генерация отчета по engagement"""
        total_posts = len(self.post_metrics)
        if total_posts == 0:
            return "Нет данных для анализа"
        
        total_engagement = {
            'reactions': 0,
            'comments': 0,
            'shares': 0,
            'chat_clicks': 0,
            'avg_relevance': 0
        }
        
        for metrics in self.post_metrics.values():
            total_engagement['reactions'] += sum(metrics.get('reactions', {}).values())
            total_engagement['comments'] += metrics.get('comments', 0)
            total_engagement['shares'] += metrics.get('shares', 0)
            total_engagement['chat_clicks'] += metrics.get('chat_clicks', 0)
            total_engagement['avg_relevance'] += metrics.get('relevance_score', 0)
        
        total_engagement['avg_relevance'] = total_engagement['avg_relevance'] / total_posts
        
        return {
            'total_posts': total_posts,
            'engagement_metrics': total_engagement,
            'engagement_rate': (total_engagement['reactions'] + total_engagement['comments']) / total_posts,
            'chat_conversion_rate': total_engagement['chat_clicks'] / total_posts if total_posts > 0 else 0
        }
    
    def generate_public_report(self):
        """Генерация публичного отчета для канала"""
        member_count = self.get_member_count()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        engagement_report = self.get_engagement_report()
        
        report = f"""📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЕТ КАНАЛА @ppsupershef</b>

👥 Подписчиков: <b>{member_count}</b>
📅 Дата: {current_time}
📍 Время Кемерово: {TimeZoneConverter.get_current_times()['kemerovo_time']}

💫 <b>СТАТИСТИКА ЗА НЕДЕЛЮ:</b>
• 📈 Engagement Rate: {engagement_report['engagement_rate']:.1f}%
• 💬 Активность в чате: {engagement_report['chat_conversion_rate']:.1f}%
• 🎯 Релевантность контента: {engagement_report['engagement_metrics']['avg_relevance']:.0f}%

🎯 <b>ПРИСОЕДИНЯЙТЕСЬ К КЛУБУ ОСОЗНАННОГО ДОЛГОЛЕТИЯ!</b>

#отчет #статистика #клуб"""
        
        return report

# Класс для работы с Telegram каналом
class EliteChannel:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.group = Config.TELEGRAM_GROUP
        self.polls_manager = TelegramPolls(self.token)
        self.formatter = ContentFormatter()
        self.sent_posts = set()  # Защита от дублирования
        SecureLogger.safe_log(f"✅ Инициализирован канал с ID: {self.channel}")
    
    def _get_content_hash(self, content):
        """Генерация хеша контента для проверки дубликатов"""
        return hashlib.md5(content.encode()).hexdigest()
    
    def send_to_telegram(self, message, parse_mode='HTML', content_type='general'):
        """Отправка сообщения в Telegram канал с защитой от дублирования"""
        try:
            if not self.token or not self.channel:
                logger.error("❌ Токен или ID канала не установлены")
                return False
            
            # Проверка на дубликат
            content_hash = self._get_content_hash(message)
            if content_hash in self.sent_posts:
                logger.warning("⚠️ Попытка отправить дубликат контента")
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
                message_id = result['result']['message_id']
                # Начинаем отслеживание engagement
                channel_analytics.track_post_engagement(message_id, content_type)
                self.sent_posts.add(content_hash)
                SecureLogger.safe_log(f"✅ Сообщение отправлено в канал {self.channel}")
                return True
            else:
                error_msg = result.get('description', 'Unknown error')
                logger.error(f"❌ Ошибка отправки: {error_msg}")
                return False
                
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ошибка подключения к Telegram API")
            time.sleep(5)
            return self.send_to_telegram(message, parse_mode, content_type)
        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут подключения к Telegram API")
            return False
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False

    def test_connection(self):
        """Тестирование подключения к канала"""
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
    
    def send_poll(self, poll_type='content_preference'):
        """Отправка опроса в канал"""
        try:
            poll_data = {
                'question': "🎯 Какой аспект осознанного питания вам наиболее интересен?",
                'options': ['🧠 Нейропитание', '💪 Энергия', '🛡️ Долголетие', '🍽️ Гастрономия']
            }
            return self.polls_manager.create_poll(self.channel, poll_data['question'], poll_data['options'])
        except Exception as e:
            logger.error(f"❌ Ошибка отправки опроса: {str(e)}")
            return None

# Генерация контента
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.formatter = ContentFormatter()
        SecureLogger.safe_log("✅ Инициализирован генератор контента")
    
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
                    'maxTokens': 1500
                },
                'messages': [
                    {
                        'role': 'system',
                        'text': ContentFormatter.SYSTEM_PROMPT
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

    # ПОНЕДЕЛЬНИК: 🧠 НЕЙРОПИТАНИЕ
    def generate_neuro_breakfast(self):
        """Генерация нейрозавтрака для ясности ума"""
        prompt = """Создай рецепт завтрака, который запускает когнитивные функции на полную мощность.

Эмоциональный триггер: "Начни день с ясностью ума, которая превратит задачи в достижения"

Научные компоненты ТЕЗИСНО:
• Омега-3 для нейропластичности
• Антиоксиданты для защиты мозга  
• Холин для памяти и обучения
• L-тирозин для фокуса

Механизм действия ТЕЗИСНО:
• Улучшает нейронные связи
• Защищает от окислительного стресса
• Повышает нейротрансмиттеры
• Ускоряет когнитивные процессы

Включи:
1. Полный список ингредиентов с точными количествами
2. Пошаговый процесс приготовления 
3. Время приготовления (до 15 минут)
4. Советы по усилению эффекта

Используй доступные в России ингредиенты."""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", content, "neuro_breakfast")
        
        fallback = """🥑 Омлет с авокадо и шпинатом

Ингредиенты:
• Яйца - 2 шт
• Авокадо - ½ шт  
• Шпинат - 50 г
• Грецкие орехи - 20 г
• Оливковое масло - 1 ч.л.

Приготовление:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами

💡 Научное обоснование:
• Авокадо - омега-9 для мембран нейронов
• Шпинат - лютеин для когнитивных функций  
• Грецкие орехи - омега-3 для нейропластичности

⚡ Механизм действия:
• Улучшает проводимость нейронов
• Защищает клетки мозга
• Повышает скорость мышления

🎯 Начните день с ясностью ума - приготовьте этот завтрак сегодня!"""
        return self.formatter.format_philosophy_content("🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА", fallback, "neuro_breakfast")

    # ВТОРНИК: 💪 ЭНЕРГИЯ И ТОНУС
    def generate_energy_breakfast(self):
        """Генерация энерго-завтрака для активного дня"""
        prompt = """Создай рецепт завтрака, который заряжает клеточные электростанции - митохондрии.

Эмоциональный триггер: "Проснись с энергией, которой хватит на все твои амбиции"

Научные компоненты ТЕЗИСНО:
• Коэнзим Q10 для производства энергии
• Магний для АТФ синтеза
• Витамины группы B для метаболизма
• Железо для кислородного обмена

Механизм действия ТЕЗИСНО:
• Активирует митохондрии
• Ускоряет производство АТФ
• Улучшает кислородный транспорт
• Оптимизирует метаболизм

Фокус на:
- Быстрое приготовление (до 10 минут)
- Ингредиенты, доступные в обычном магазине
- Советы по поддержанию уровня энергии"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", content, "energy_breakfast")
        
        fallback = """🥣 Энергетическая овсянка с семенами

Ингредиенты:
• Овсяные хлопья - 50 г
• Миндаль - 20 г
• Семена чиа - 1 ст.л.
• Банан - 1 шт
• Корица - ½ ч.л.

Приготовление:
1. Залейте овсянку горячей водой на 5 минут
2. Добавьте нарезанный банан и семена чиа
3. Посыпьте миндалем и корицей

💡 Научное обоснование:
• Овсянка - медленные углеводы для энергии
• Семена чиа - омега-3 для митохондрий
• Корица - регулирует уровень сахара

⚡ Механизм действия:
• Обеспечивает стабильную энергию
• Улучшает клеточное дыхание
• Стабилизирует глюкозу крови

🎯 Зарядитесь энергией на весь день!"""
        return self.formatter.format_philosophy_content("⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ", fallback, "energy_breakfast")

    # СРЕДА: 🛡️ ДОЛГОЛЕТИЕ
    def generate_longevity_breakfast(self):
        """Генерация завтрака долгожителя"""
        prompt = """Создай рецепт завтрака, который активирует гены долголетия и процессы клеточного обновления.

Эмоциональный триггер: "Каждое утро - возможность добавить здоровые годы к своей жизни"

Геропротекторы ТЕЗИСНО:
• Ресвератрол для активации сиртуинов
• Куркумин против воспаления
• Полифенолы для антиоксидантной защиты
• Спермидин для аутофагии

Механизм действия ТЕЗИСНО:
• Активирует гены долголетия
• Снижает клеточное старение
• Ускоряет аутофагию
• Борется с воспалением

Акцент на:
- Продукты, доказано связанные с долголетием
- Простые техники приготовления
- Доступные аналоги дорогих суперфудов"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", content, "longevity_breakfast")
        
        fallback = """🥣 Каша с куркумой и ягодами

Ингредиенты:
• Гречневая крупа - 50 г
• Куркума - 1 ч.л.
• Ягоды (замороженные) - 100 г
• Грецкие орехи - 20 г
• Льняное масло - 1 ч.л.

Приготовление:
1. Сварите гречневую кашу
2. Добавьте куркуму за 2 минуты до готовности
3. Подавайте с ягодами, орехами и льняным маслом

💡 Научное обоснование:
• Куркума - куркумин против воспаления
• Ягоды - антоцианы против стресса
• Льняное масло - омега-3 для мембран

⚡ Механизм действия:
• Снижает воспалительные маркеры
• Защищает от окислительного damage
• Улучшает клеточную коммуникацию

🎯 Инвестируйте в свое долголетие с каждым завтраком!"""
        return self.formatter.format_philosophy_content("🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ", fallback, "longevity_breakfast")

    # ЧЕТВЕРГ: 🍽️ ГАСТРОНОМИЧЕСКОЕ НАСЛАЖДЕНИЕ
    def generate_gastronomy_breakfast(self):
        """Генерация творческого завтрака"""
        prompt = """Создай рецепт завтрака ресторанного уровня, который доказывает: полезное может быть изысканным.

Эмоциональный триггер: "Начни день с гастрономического наслаждения, которое продлевает жизнь"

Научные компоненты ТЕЗИСНО:
• Антиоксиданты для молодости
• Противовоспалительные компоненты
• Пробиотики для микробиома
• Флавоноиды для здоровья сосудов

Механизм действия ТЕЗИСНО:
• Улучшает микробиом кишечника
• Снижает системное воспаление
• Укрепляет сосудистую систему
• Поддерживает гормональный баланс

Фокус на:
- Простые приемы шеф-поваров для дома
- Баланс вкуса и пользы
- Время приготовления до 20 минут
- Ингредиенты, доступные в обычных магазинах"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", content, "gastronomy_breakfast")
        
        fallback = """🍳 Гренки с авокадо и яйцом-пашот

Ингредиенты:
• Хлеб цельнозерновой - 2 ломтика
• Авокадо - 1 шт
• Яйца - 2 шт
• Руккола - 30 г
• Семена кунжута - 1 ч.л.

Приготовление:
1. Подсушите хлеб на сухой сковороде
2. Разомните авокадо с солью
3. Приготовьте яйца-пашот (3 минуты в кипящей воде)
4. Соберите: хлеб + авокадо + руккола + яйцо

💡 Научное обоснование:
• Авокадо - мононенасыщенные жиры
• Яйца - холин для мозга
• Руккола - глюкозинолаты для детокса

⚡ Механизм действия:
• Поддерживает здоровье сердца
• Улучшает липидный профиль
• Стимулирует детокс процессы

🎯 Наслаждайтесь каждым укусом - это инвестиция в ваше здоровье!"""
        return self.formatter.format_philosophy_content("🎨 ТВОРЧЕСКИЙ ЗАВТРАК", fallback, "gastronomy_breakfast")

    # ПЯТНИЦА: 🎯 РЕЗУЛЬТАТЫ И ПЛАНЫ
    def generate_analytical_breakfast(self):
        """Генерация аналитического завтрака"""
        prompt = """Создай рецепт завтрака, который помогает анализировать прошедшую неделю и планировать следующую.

Эмоциональный триггер: "Завтрак, который превращает опыт недели в планы на будущее"

Научные компоненты ТЕЗИСНО:
• Тирозин для ясности мышления
• Омега-3 для когнитивных функций
• Глюкоза для энергии мозга
• Антиоксиданты для снижения стресса

Механизм действия ТЕЗИСНО:
• Улучшает префронтальную кору
• Повышает нейропластичность
• Снижает кортизол
• Оптимизирует нейротрансмиттеры

Особенности:
- Связь питания и продуктивности
- Практические советы по планированию питания
- Подготовка к выходным без срывов"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", content, "analytical_breakfast")
        
        fallback = """🥣 Творожная масса с орехами и медом

Ингредиенты:
• Творог 5% - 150 г
• Грецкие орехи - 30 г
• Мед - 1 ст.л.
• Изюм - 20 г
• Лимонный сок - 1 ч.л.

Приготовление:
1. Смешайте творог с медом и лимонным соком
2. Добавьте измельченные орехи и изюм
3. Подавайте с цельнозерновыми хлебцами

💡 Научное обоснование:
• Творог - тирозин для ясности
• Орехи - омега-3 для когнитивных функций
• Мед - натуральная глюкоза для энергии

⚡ Механизм действия:
• Улучшает исполнительные функции
• Повышает концентрацию внимания
• Снижает умственную усталость

🎯 Планируйте успешную неделю с правильным завтраком!"""
        return self.formatter.format_philosophy_content("📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК", fallback, "analytical_breakfast")

    # СУББОТА: 🛒 УМНЫЕ ПОКУПКИ + РЕЦЕПТЫ
    def generate_smart_shopping_list(self):
        """Генерация умного чек-листа покупок"""
        season = self._get_current_season()
        
        shopping_list = f"""🛒 <b>УМНЫЙ ЧЕК-ЛИСТ НА НЕДЕЛЮ</b>

Основа для осознанного долголетия + сезонные продукты ({season})

🧠 <b>ДЛЯ МОЗГА И НЕРВНОЙ СИСТЕМЫ:</b>
• Грецкие орехи - 200 г
• Авокадо - 3-4 шт
• Жирная рыба (лосось, скумбрия) - 500 г
• Яйца - 10 шт
• Темный шоколад 85% - 100 г

💪 <b>ДЛЯ ЭНЕРГИИ И ТОНУСА:</b>
• Овсяные хлопья - 500 г
• Бананы - 1 кг
• Семена чиа - 100 г
• Куриная грудка - 1 кг
• Гречневая крупа - 500 г

🛡️ <b>ДЛЯ ДОЛГОЛЕТИЯ:</b>
• Куркума - 50 г
• Имбирь - 100 г
• Чеснок - 3 головки
• Ягоды (замороженные) - 500 г
• Зеленые овощи - 1 кг

🍽️ <b>ДЛЯ ГАСТРОНОМИЧЕСКОГО НАСЛАЖДЕНИЯ:</b>
• Специи (корица, кардамон, мускат)
• Натуральный мед - 300 г
• Кокосовое молоко - 400 мл
• Оливковое масло - 500 мл

💡 <b>СОВЕТЫ ОТ ШЕФ-ПОВАРА:</b>
• Покупайте сезонные местные продукты
• Читайте составы - избегайте рафинированного сахара
• Планируйте меню на неделю вперед
• Храните орехи и семена в холодильнике

🎯 <b>ФИЛОСОФИЯ ПОКУПОК:</b>
Каждый продукт в вашей корзине - это инвестиция в ваше долголетие и качество жизни!

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

    # ВОСКРЕСЕНЬЕ: 📊 АНАЛИТИКА + РЕЦЕПТЫ
    def generate_sunday_brunch(self):
        """Генерация воскресного бранча"""
        prompt = """Создай рецепт бранча, который становится ритуалом подготовки к новой неделе.

Эмоциональный триггер: "Воскресный бранч - твой стратегический ресурс для успешной недели"

Научные компоненты ТЕЗИСНО:
• Комплексные углеводы для энергии
• Белки для сытости и мышц
• Здоровые жиры для гормонов
• Клетчатка для детокса

Механизм действия ТЕЗИСНО:
• Стабилизирует уровень сахара
• Подготавливает метаболизм
• Восстанавливает ресурсы
• Настраивает циркадные ритмы

Элементы ритуала:
- Блюда, требующие осознанного приготовления
- Ингредиенты для ментальной подготовки
- Техники, развивающие кулинарные навыки"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", content, "sunday_brunch")
        
        fallback = """🥞 Панкейки из цельнозерновой муки с ягодным соусом

Ингредиенты:
• Мука цельнозерновая - 150 г
• Яйца - 2 шт
• Кефир - 200 мл
• Разрыхлитель - 1 ч.л.
• Ягоды (замороженные) - 200 г
• Мед - 2 ст.л.

Приготовление:
1. Смешайте сухие ингредиенты
2. Добавьте яйца и кефир, замесите тесто
3. Жарьте на антипригарной сковороде по 2-3 минуты с каждой стороны
4. Для соуса разогрейте ягоды с медом

💡 Научное обоснование:
• Цельнозерновая мука - клетчатка для микробиома
• Яйца - холин для нейротрансмиттеров
• Ягоды - полифенолы для сосудов

⚡ Механизм действия:
• Подготавливает пищеварительную систему
• Обеспечивает стабильную энергию
• Улучшает когнитивные функции

🎯 Создайте ритуал воскресного бранча для успешной недели!"""
        return self.formatter.format_philosophy_content("🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ", fallback, "sunday_brunch")

    # НАУЧНЫЙ КОНТЕНТ
    def generate_science_content(self):
        """Генерация научного контента"""
        prompt = """Представь научный факт о питании и долголетии, который можно применить сегодня же.

Эмоциональный триггер: "Наука, которая меняет твое отношение к еде прямо сейчас"

Требования:
- Только доказанные исследования
- Практическое применение
- Объяснение механизма действия ТЕЗИСНО
- Опора на авторитетные источники

Структура:
1. Научное открытие/факт
2. Как это работает в организме ТЕЗИСНО
3. Как применить в питании сегодня
4. Ожидаемый эффект
5. Простые шаги для внедрения"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", content, "science_content")
        
        fallback = """🏆 Научный факт: Интервальное голодание активирует аутофагию

Что это такое: Аутофагия - процесс очищения клеток от поврежденных компонентов, открытый японским ученым Ёсинори Осуми (Нобелевская премия 2016).

💡 Механизм действия ТЕЗИСНО:
• Активирует гены очищения
• Удаляет поврежденные белки
• Обновляет клеточные структуры
• Снижает воспаление

Практическое применение: Попробуйте окончить ужин в 20:00 и позавтракать в 12:00 следующего дня.

Ожидаемый эффект: Улучшение когнитивных функций, замедление старения, снижение риска возрастных заболеваний.

🎯 Простые шаги: Начните с 12-часового перерыва, постепенно увеличивая до 16 часов."""
        return self.formatter.format_philosophy_content("🔬 НАУКА ОСОЗНАННОГО ДОЛГОЛЕТИЯ", fallback, "science_content")

    # СОВЕТЫ ЭКСПЕРТОВ
    def generate_expert_advice(self):
        """Генерация советов экспертов"""
        prompt = """Сформулируй принцип осознанного питания, который становится философией на всю жизнь.

Эмоциональный триггер: "Принцип, который превращает еду из привычки в инструмент роста"

Научное обоснование ТЕЗИСНО:
• Основные механизмы действия
• Ключевые преимущества для здоровья
• Влияние на долголетие

Механизм действия ТЕЗИСНО:
• Как влияет на метаболизм
• Воздействие на системы организма
• Эффекты для ментального здоровья

Структура:
1. Формулировка принципа
2. Почему это работает (наука ТЕЗИСНО)
3. Как применять на практике
4. Какие результаты дает
5. Истории успеха или исследования"""
        
        content = self.generate_with_yandex_gpt(prompt)
        if content:
            return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", content, "expert_advice")
        
        fallback = """🎯 Принцип: "Ешьте цвета радуги"

Формулировка: Каждый день включайте в рацион продукты всех цветов радуги - красные, оранжевые, желтые, зеленые, синие, фиолетовые.

💡 Научное обоснование ТЕЗИСНО:
• Красные - ликопин против рака
• Оранжевые - бета-каротин для зрения  
• Зеленые - лютеин для мозга
• Синие - антоцианы для сердца

⚡ Механизм действия ТЕЗИСНО:
• Обеспечивает фитонутриентное разнообразие
• Укрепляет антиоксидантную защита
• Снижает системное воспаление
• Поддерживает микробиом

Практическое применение: Сделайте свой обед разноцветным - салат из помидоров, моркови, перца, огурцов и капусты.

Результаты: Укрепление иммунной системы, снижение воспаления, защита от хронических заболеваний.

🎯 Простой шаг: Добавьте хотя бы 3 разных цвета в каждый основной прием пищи."""
        return self.formatter.format_philosophy_content("💡 ПРИНЦИПЫ УМНОГО ПИТАНИЯ", fallback, "expert_advice")

# ОПТИМИЗИРОВАННОЕ РАСПИСАНИЕ КОНТЕНТА
class ContentScheduler:
    def __init__(self):
        # ОПТИМИЗИРОВАННОЕ расписание на всю неделю в времени Кемерово (UTC+7)
        self.kemerovo_schedule = {
            'monday': {
                "08:00": {"type": "neuro_breakfast", "name": "🧠 Нейрозавтрак + научный факт", "generator": "generate_neuro_breakfast"},
                "13:00": {"type": "energy_lunch", "name": "💪 Энерго-обед с лайфхаком", "generator": "generate_energy_breakfast"}, 
                "19:00": {"type": "longevity_dinner", "name": "🌙 Ужин для долголетия + инсайт", "generator": "generate_longevity_breakfast"},
                "21:00": {"type": "science_content", "name": "🔬 Научный факт о мозге", "generator": "generate_science_content"}
            },
            'tuesday': {
                "08:00": {"type": "energy_breakfast", "name": "⚡ Энерго-завтрак + исследование", "generator": "generate_energy_breakfast"},
                "13:00": {"type": "focus_lunch", "name": "🎯 Обед для фокуса + биохакинг", "generator": "generate_energy_breakfast"},
                "18:00": {"type": "gastronomy_dinner", "name": "🍽️ Ресторанный ужин дома", "generator": "generate_gastronomy_breakfast"},
                "20:00": {"type": "expert_advice", "name": "💡 Принцип осознанного питания", "generator": "generate_expert_advice"}
            },
            'wednesday': {
                "08:00": {"type": "longevity_breakfast", "name": "🛡️ Завтрак долгожителя + геропротекторы", "generator": "generate_longevity_breakfast"},
                "13:00": {"type": "anti_age_lunch", "name": "🌿 Anti-age обед + научные данные", "generator": "generate_longevity_breakfast"},
                "19:00": {"type": "cellular_dinner", "name": "🌙 Ужин для клеточного обновления", "generator": "generate_longevity_breakfast"},
                "21:00": {"type": "science_content", "name": "🔬 Стратегии долголетия", "generator": "generate_science_content"}
            },
            'thursday': {
                "08:00": {"type": "gastronomy_breakfast", "name": "🎨 Творческий завтрак ресторанного уровня", "generator": "generate_gastronomy_breakfast"},
                "13:00": {"type": "michelin_lunch", "name": "🍽️ Обед по принципам Мишлен", "generator": "generate_gastronomy_breakfast"},
                "18:00": {"type": "gastronomy_dinner", "name": "🌙 Гастрономический ужин + винные пары", "generator": "generate_gastronomy_breakfast"},
                "20:00": {"type": "expert_advice", "name": "💡 Искусство осознанного наслаждения", "generator": "generate_expert_advice"}
            },
            'friday': {
                "08:00": {"type": "analytical_breakfast", "name": "📊 Аналитический завтрак для планирования", "generator": "generate_analytical_breakfast"},
                "13:00": {"type": "results_lunch", "name": "🎯 Обед для подведения итогов недели", "generator": "generate_analytical_breakfast"},
                "19:00": {"type": "planning_dinner", "name": "🌙 Ужин для подготовки к выходным", "generator": "generate_analytical_breakfast"},
                "21:00": {"type": "expert_advice", "name": "💡 Планирование питания на неделю", "generator": "generate_expert_advice"}
            },
            'saturday': {
                "09:00": {"type": "weekend_breakfast", "name": "🥗 Субботний завтрак для семьи", "generator": "generate_energy_breakfast"},
                "11:00": {"type": "shopping_list", "name": "🛒 Умный чек-лист покупок на неделю", "generator": "generate_smart_shopping_list"},
                "13:00": {"type": "family_lunch", "name": "🍲 Семейный обед + вовлечение детей", "generator": "generate_gastronomy_breakfast"},
                "17:00": {"type": "weekend_dessert", "name": "🧁 Субботний десерт + вовлечение", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "weekend_dinner", "name": "🌙 Вечерний анализ покупок", "generator": "generate_gastronomy_breakfast"}
            },
            'sunday': {
                "10:00": {"type": "sunday_brunch", "name": "🍳 Воскресный бранч-ритуал", "generator": "generate_sunday_brunch"},
                "13:00": {"type": "sunday_lunch", "name": "🥘 Воскресный обед для подготовки", "generator": "generate_gastronomy_breakfast"},
                "17:00": {"type": "sunday_dessert", "name": "🍮 Десерт для осмысления недели", "generator": "generate_neuro_dessert"},
                "19:00": {"type": "sunday_dinner", "name": "🌙 Ужин для настройки на неделю", "generator": "generate_analytical_breakfast"},
                "21:00": {"type": "weekly_motivation", "name": "🎯 Мотивация на новую неделю", "generator": "generate_expert_advice"}
            }
        }
        
        # Конвертируем расписание в серверное время
        self.server_schedule = self._convert_schedule_to_server()
        
        self.is_running = False
        SecureLogger.safe_log("✅ Инициализирован планировщик контента с оптимизированным расписанием")

    def _convert_schedule_to_server(self):
        """Конвертирует все расписание в серверное время"""
        server_schedule = {}
        for day, day_schedule in self.kemerovo_schedule.items():
            server_schedule[day] = {}
            for kemerovo_time, event in day_schedule.items():
                server_time = TimeZoneConverter.kemerovo_to_server_time(kemerovo_time)
                server_schedule[day][server_time] = event
                SecureLogger.safe_log(f"🕒 Расписание: {day} - Кемерово {kemerovo_time} -> Сервер {server_time} - {event['name']}")
        return server_schedule

    def get_schedule(self):
        """Возвращает расписание"""
        return {
            'kemerovo_schedule': self.kemerovo_schedule,
            'server_schedule': self.server_schedule
        }
    
    def get_next_event(self):
        """Получает следующее событие с учетом текущего дня недели"""
        try:
            current_times = TimeZoneConverter.get_current_times()
            current_kemerovo_time = current_times['kemerovo_time'][:5]
            
            # Получаем текущий день недели (0-6, где 0-понедельник)
            current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
            days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            current_day = days[current_weekday]
            
            # Получаем расписание на текущий день
            today_schedule = self.kemerovo_schedule.get(current_day, {})
            
            # Ищем следующее событие сегодня
            times_today = [t for t in today_schedule.keys() if t > current_kemerovo_time]
            
            if times_today:
                # Есть посты сегодня
                next_kemerovo_time = min(times_today)
                next_event = today_schedule[next_kemerovo_time]
                next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                return next_server_time, next_kemerovo_time, next_event
            else:
                # Постов сегодня больше нет, берем первый пост завтра
                next_weekday = (current_weekday + 1) % 7
                next_day = days[next_weekday]
                next_day_schedule = self.kemerovo_schedule.get(next_day, {})
                
                if next_day_schedule:
                    next_kemerovo_time = min(next_day_schedule.keys())
                    next_event = next_day_schedule[next_kemerovo_time]
                    next_server_time = TimeZoneConverter.kemerovo_to_server_time(next_kemerovo_time)
                    return next_server_time, next_kemerovo_time, next_event
            
            # Если ничего не найдено, возвращаем заглушку
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "17:00", "17:00", {"name": "Следующий пост", "type": "unknown"}
    
    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
        
        SecureLogger.safe_log("🚀 Запуск планировщика контента с оптимизированным расписанием...")
        
        # Планируем основной контент для каждого дня
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                if 'generator' in event:
                    self._schedule_daily_content(day, server_time, event)
        
        # Планируем ежедневный отчет
        self._schedule_analytics_reports()
        
        self.is_running = True
        self._run_scheduler()

    def _schedule_daily_content(self, day, server_time, event):
        """Планирует контент для конкретного дня"""
        def job():
            current_times = TimeZoneConverter.get_current_times()
            SecureLogger.safe_log(f"🕒 Выполнение: {event['name']}")
            
            if 'generator' in event:
                method_name = event['generator']
                method = getattr(content_gen, method_name)
                content = method()
            else:
                content = None
            
            if content:
                content_with_time = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
                success = elite_channel.send_to_telegram(content_with_time, content_type=event['type'])
                if success:
                    SecureLogger.safe_log(f"✅ Успешная публикация: {event['name']}")
        
        # Валидация дня и времени
        allowed_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        if day not in allowed_days:
            logger.error(f"❌ Попытка запланировать на недопустимый день: {day}")
            return
        
        # Планируем задачу на конкретный день и время
        job_func = getattr(schedule.every(), day)
        job_func.at(server_time).do(job)
        SecureLogger.safe_log(f"✅ Запланировано: {day} {server_time} - {event['name']}")

    def _schedule_analytics_reports(self):
        """Планирование аналитических отчетов"""
        # Публичный отчет в 09:00 по Кемерово каждый день
        public_report_time = TimeZoneConverter.kemerovo_to_server_time("09:00")
        
        def public_analytics_job():
            SecureLogger.safe_log("📊 Генерация публичного отчета")
            report = channel_analytics.generate_public_report()
            elite_channel.send_to_telegram(report, content_type='analytics')
        
        schedule.every().day.at(public_report_time).do(public_analytics_job)
        SecureLogger.safe_log(f"✅ Запланирован публичный отчет на {public_report_time}")

    def _run_scheduler(self):
        """Запускает фоновый поток планировщика"""
        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        SecureLogger.safe_log("✅ Планировщик запущен")

    def _get_day_theme(self, weekday):
        """Возвращает тему дня недели"""
        themes = {
            0: "🧠 Нейропитание - фокус на мозг и когнитивные функции",
            1: "💪 Энергия и тонус - заряд энергии для достижений", 
            2: "🛡️ Долголетие - стратегии здоровой долгой жизни",
            3: "🍽️ Гастрономическое наслаждение - изысканность с пользой",
            4: "🎯 Результаты и планы - аналитика и планирование",
            5: "🛒 Умные покупки + рецепты - подготовка к неделе",
            6: "📊 Аналитика + ритуалы - настрой на новую неделю"
        }
        return themes.get(weekday, "Осознанное питание")

# Инициализация компонентов
elite_channel = EliteChannel()
content_gen = ContentGenerator()
content_scheduler = ContentScheduler()
channel_analytics = ChannelAnalytics(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHANNEL)

# Запускаем планировщик при старте
try:
    content_scheduler.start_scheduler()
    SecureLogger.safe_log("✅ Все компоненты инициализированы")
    
    current_times = TimeZoneConverter.get_current_times()
    SecureLogger.safe_log(f"🌍 Текущее время сервера: {current_times['server_time']}")
    SecureLogger.safe_log(f"🌍 Время Кемерово: {current_times['kemerovo_time']}")
    
    member_count = channel_analytics.get_member_count()
    SecureLogger.safe_log(f"📊 Начальное количество подписчиков: {member_count}")
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")

# МАРШРУТЫ ДЛЯ ДИАГНОСТИКИ
@app.route('/channel-diagnostics')
@rate_limit
def channel_diagnostics():
    """Полная диагностика канала"""
    try:
        diagnostic_results = {
            'status': 'completed',
            'steps': [],
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'bot_status': 'unknown',
            'channel_status': 'unknown',
            'member_count': 0,
            'engagement_metrics': {},
            'errors': [],
            'success': []
        }
        
        # Шаг 1: Проверка токенов
        diagnostic_results['steps'].append("🔐 Проверка токенов...")
        try:
            token_status = safe_debug_tokens()
            diagnostic_results['success'].append("Токены проверены безопасно")
            diagnostic_results['bot_status'] = 'token_ok'
        except Exception as e:
            diagnostic_results['errors'].append(f"Ошибка проверки токенов: {str(e)}")
            diagnostic_results['bot_status'] = 'token_error'
        
        # Шаг 2: Проверка бота
        diagnostic_results['steps'].append("🤖 Проверка подключения бота...")
        try:
            bot_test = elite_channel.test_connection()
            if bot_test.get('status') == 'success':
                diagnostic_results['success'].append(f"Бот активен: {bot_test.get('bot', 'Unknown')}")
                diagnostic_results['bot_status'] = 'active'
            else:
                diagnostic_results['errors'].append(f"Ошибка бота: {bot_test.get('message', 'Unknown error')}")
                diagnostic_results['bot_status'] = 'connection_error'
        except Exception as e:
            diagnostic_results['errors'].append(f"Ошибка проверки бота: {str(e)}")
        
        # Шаг 3: Проверка канала
        diagnostic_results['steps'].append("📊 Проверка доступа к каналу...")
        try:
            member_count = channel_analytics.get_member_count()
            if member_count > 0:
                diagnostic_results['success'].append(f"Подписчиков в канале: {member_count}")
                diagnostic_results['member_count'] = member_count
                diagnostic_results['channel_status'] = 'accessible'
            else:
                diagnostic_results['errors'].append("Не удалось получить статистику канала")
                diagnostic_results['channel_status'] = 'access_error'
        except Exception as e:
            diagnostic_results['errors'].append(f"Ошибка доступа к каналу: {str(e)}")
        
        # Шаг 4: Проверка планировщика
        diagnostic_results['steps'].append("⏰ Проверка планировщика...")
        if content_scheduler.is_running:
            diagnostic_results['success'].append("Планировщик активен")
        else:
            diagnostic_results['errors'].append("Планировщик не запущен")
        
        # Шаг 5: Статистика engagement
        diagnostic_results['steps'].append("📈 Проверка метрик engagement...")
        try:
            engagement_report = channel_analytics.get_engagement_report()
            diagnostic_results['engagement_metrics'] = engagement_report
            diagnostic_results['success'].append("Метрики engagement собраны")
        except Exception as e:
            diagnostic_results['errors'].append(f"Ошибка сбора метрик: {str(e)}")
        
        return jsonify(diagnostic_results)
        
    except Exception as e:
        return jsonify({
            'status': 'error', 
            'message': f'Ошибка диагностики: {str(e)}'
        })

@app.route('/fix-bot-token', methods=['POST'])
@require_api_key
@rate_limit
def fix_bot_token():
    """Ручное обновление токена бота"""
    try:
        data = request.get_json()
        new_token = data.get('token', '').strip()
        
        if not new_token:
            return jsonify({'status': 'error', 'message': 'Пустой токен'})
        
        # Обновляем токен в текущей сессии
        elite_channel.token = new_token
        channel_analytics.bot_token = new_token
        
        # Тестируем новый токен
        test_result = elite_channel.test_connection()
        
        if test_result.get('status') == 'success':
            return jsonify({
                'status': 'success', 
                'message': 'Токен обновлен и проверен!'
            })
        else:
            return jsonify({
                'status': 'error', 
                'message': f'Токен невалиден: {test_result.get("message")}'
            })
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ОСНОВНЫЕ МАРШРУТЫ FLASK
@app.route('/')
@rate_limit
def index():
    """Главная страница с расширенной аналитикой"""
    try:
        next_server_time, next_kemerovo_time, next_event = content_scheduler.get_next_event()
        connection_info = elite_channel.test_connection()
        current_times = TimeZoneConverter.get_current_times()
        member_count = channel_analytics.get_member_count()
        engagement_report = channel_analytics.get_engagement_report()
        
        # Получаем русское название дня недели
        weekday_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
        current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
        current_day_name = weekday_names[current_weekday]
        
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
                    .engagement-card {{ background: #9b59b6; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .time-info {{ background: #27ae60; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .btn {{ display: inline-block; padding: 10px 20px; margin: 5px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
                    .btn-danger {{ background: #e74c3c; }}
                    .btn-success {{ background: #27ae60; }}
                    .btn-warning {{ background: #f39c12; }}
                    .content-section {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                    .quick-actions {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .content-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .form-group {{ margin: 10px 0; }}
                    input, textarea, select {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }}
                    .day-info {{ background: #e67e22; color: white; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }}
                    .metric-card {{ background: white; padding: 15px; border-radius: 5px; border-left: 4px solid #3498db; }}
                    
                    /* Стили для модального окна */
                    .modal {{
                        display: none;
                        position: fixed;
                        z-index: 1000;
                        left: 0;
                        top: 0;
                        width: 100%;
                        height: 100%;
                        background-color: rgba(0,0,0,0.5);
                    }}
                    .modal-content {{
                        background-color: white;
                        margin: 5% auto;
                        padding: 20px;
                        border-radius: 10px;
                        width: 80%;
                        max-width: 800px;
                        max-height: 80vh;
                        overflow-y: auto;
                    }}
                    .close {{
                        color: #aaa;
                        float: right;
                        font-size: 28px;
                        font-weight: bold;
                        cursor: pointer;
                    }}
                    .close:hover {{
                        color: black;
                    }}
                    .diagnostics-loading {{
                        text-align: center;
                        padding: 20px;
                    }}
                    .spinner {{
                        border: 4px solid #f3f3f3;
                        border-top: 4px solid #3498db;
                        border-radius: 50%;
                        width: 40px;
                        height: 40px;
                        animation: spin 2s linear infinite;
                        margin: 20px auto;
                    }}
                    @keyframes spin {{
                        0% {{ transform: rotate(0deg); }}
                        100% {{ transform: rotate(360deg); }}
                    }}
                    .diagnostics-steps ul, 
                    .diagnostics-success ul, 
                    .diagnostics-errors ul {{
                        margin-left: 20px;
                    }}
                    .diagnostics-header {{
                        border-bottom: 2px solid #3498db;
                        padding-bottom: 10px;
                        margin-bottom: 20px;
                    }}
                    .modal-actions {{
                        margin-top: 20px;
                        text-align: right;
                        border-top: 1px solid #ddd;
                        padding-top: 15px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎪 Система управления @ppsupershef</h1>
                        <p>ФИЛОСОФИЯ: Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь</p>
                    </div>
                    
                    <div class="day-info">
                        <h2>📅 Сегодня: {current_day_name}</h2>
                        <p>Тема дня: {content_scheduler._get_day_theme(current_weekday)}</p>
                    </div>
                    
                    <div class="quick-actions">
                        <button class="btn" onclick="testChannel()">📊 Статистика</button>
                        <button class="btn" onclick="testConnection()">Тест канала</button>
                        <button class="btn" onclick="runChannelDiagnostics()">🩺 Диагностика канала</button>
                        <button class="btn" onclick="showDebug()">Отладка</button>
                        <button class="btn" onclick="healthCheck()">Health Check</button>
                        <button class="btn" onclick="showFormatPreview()">Предпросмотр формата</button>
                        <button class="btn" onclick="sendPoll()">Отправить опрос</button>
                        <button class="btn" onclick="sendVisualContent()">Визуальный контент</button>
                        <button class="btn" onclick="sendShoppingList()">Чек-лист покупок</button>
                        <button class="btn btn-success" onclick="sendPublicReport()">📨 Отчет статистики</button>
                    </div>
                    
                    <div class="content-section">
                        <h2>📤 Отправка контента</h2>
                        <div class="content-grid">
                            <button class="btn" onclick="sendContent('breakfast')">🍳 Завтрак</button>
                            <button class="btn" onclick="sendContent('lunch')">🍲 Обед</button>
                            <button class="btn" onclick="sendContent('science')">🔬 Наука</button>
                            <button class="btn" onclick="sendContent('interval')">⏱️ Интервал</button>
                            <button class="btn" onclick="sendContent('dinner')">🍽️ Ужин</button>
                            <button class="btn" onclick="sendContent('advice')">💡 Советы экспертов</button>
                        </div>
                        
                        <div class="form-group">
                            <h3>✍️ Ручной ввод контента</h3>
                            <textarea id="manualContent" rows="6" placeholder="Введите текст сообщения для Telegram..."></textarea>
                            <button class="btn btn-success" onclick="sendManualContent()">📤 Отправить в канал</button>
                        </div>
                    </div>
                    
                    <div class="stats-card">
                        <h2>📊 СТАТИСТИКА КАНАЛА</h2>
                        <p><strong>👥 Подписчиков: {member_count}</strong></p>
                        <p><strong>📈 Контент: 28 постов/неделя</strong></p>
                        <p><strong>🎯 Философия: Осознанное долголетие</strong></p>
                    </div>
                    
                    <div class="engagement-card">
                        <h2>📈 METРИКИ ENGAGEMENT</h2>
                        <div class="metric-grid">
                            <div class="metric-card">
                                <h3>🎯 Engagement Rate</h3>
                                <p><strong>{engagement_report.get('engagement_rate', 0):.1f}%</strong></p>
                            </div>
                            <div class="metric-card">
                                <h3>💬 Конверсия в чат</h3>
                                <p><strong>{engagement_report.get('chat_conversion_rate', 0):.1f}%</strong></p>
                            </div>
                            <div class="metric-card">
                                <h3>⭐ Релевантность</h3>
                                <p><strong>{engagement_report['engagement_metrics'].get('avg_relevance', 0):.0f}/100</strong></p>
                            </div>
                            <div class="metric-card">
                                <h3>📝 Всего постов</h3>
                                <p><strong>{engagement_report.get('total_posts', 0)}</strong></p>
                            </div>
                        </div>
                    </div>
                    
                    <div class="time-info">
                        <h3>🌍 ИНФОРМАЦИЯ О ВРЕМЕНИ</h3>
                        <p>Сервер: <strong>{current_times['server_time']}</strong> • Кемерово: <strong>{current_times['kemerovo_time']}</strong></p>
                        <p>Следующая публикация: <strong>{next_kemerovo_time} - {next_event['name']}</strong></p>
                    </div>
                </div>

                <!-- Модальное окно диагностики -->
                <div id="diagnosticsModal" class="modal">
                    <div class="modal-content">
                        <span class="close" onclick="closeDiagnostics()">&times;</span>
                        <h2>🩺 Диагностика канала</h2>
                        <div id="diagnosticsResults">
                            <div class="diagnostics-loading">
                                <p>Запуск диагностики...</p>
                                <div class="spinner"></div>
                            </div>
                        </div>
                        
                        <div id="tokenFixSection" style="display: none; margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                            <h3>🔧 Исправить токен бота</h3>
                            <p>Токен бота невалиден. Получите новый токен в @BotFather и вставьте его ниже:</p>
                            <input type="text" id="newBotToken" placeholder="Новый токен бота" style="width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px;">
                            <button class="btn btn-success" onclick="updateBotToken()">Обновить токен</button>
                        </div>
                        
                        <div class="modal-actions">
                            <button class="btn" onclick="closeDiagnostics()">Закрыть</button>
                            <button class="btn btn-warning" onclick="runChannelDiagnostics()">🔄 Перезапустить диагностику</button>
                        </div>
                    </div>
                </div>

                <script>
                    function testConnection() {{
                        fetch('/test-channel')
                            .then(response => response.json())
                            .then(data => alert('Результат теста: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
                    }}

                    function healthCheck() {{
                        fetch('/health')
                            .then(response => response.json())
                            .then(data => alert('Статус системы: ' + (data.status === 'healthy' ? '✅ Здорова' : '❌ Проблемы')));
                    }}

                    function showDebug() {{
                        fetch('/debug')
                            .then(response => response.json())
                            .then(data => alert('Отладка: ' + JSON.stringify(data, null, 2)));
                    }}

                    function testChannel() {{
                        fetch('/test-channel')
                            .then(response => response.json())
                            .then(data => alert('Тест канала: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
                    }}

                    function sendPublicReport() {{
                        fetch('/send-public-report')
                            .then(response => response.json())
                            .then(data => alert('Отчет: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function sendPoll() {{
                        fetch('/send-poll')
                            .then(response => response.json())
                            .then(data => alert('Опрос: ' + (data.status === 'success' ? '✅ Создан' : '❌ Ошибка')));
                    }}

                    function sendVisualContent() {{
                        fetch('/send-visual-content')
                            .then(response => response.json())
                            .then(data => alert('Визуальный контент: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function sendShoppingList() {{
                        fetch('/send-shopping-list')
                            .then(response => response.json())
                            .then(data => alert('Чек-лист: ' + (data.status === 'success' ? '✅ Отправлен' : '❌ Ошибка')));
                    }}

                    function showFormatPreview() {{
                        fetch('/format-preview')
                            .then(response => response.json())
                            .then(data => {{
                                if (data.status === 'success') {{
                                    alert('Предпросмотр формата отправлен в канал');
                                }} else {{
                                    alert('Ошибка: ' + data.message);
                                }}
                            }});
                    }}

                    function sendContent(type) {{
                        const endpoints = {{
                            'breakfast': '/send-breakfast',
                            'lunch': '/send-lunch', 
                            'science': '/send-science',
                            'interval': '/send-interval',
                            'dinner': '/send-dinner',
                            'advice': '/send-advice'
                        }};

                        if (endpoints[type]) {{
                            fetch(endpoints[type])
                                .then(response => response.json())
                                .then(data => alert('Контент отправлен: ' + (data.status === 'success' ? '✅ Успешно' : '❌ Ошибка')));
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
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{ content: content }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Сообщение отправлено в канал');
                                document.getElementById('manualContent').value = '';
                            }} else {{
                                alert('❌ Ошибка: ' + data.message);
                            }}
                        }});
                    }}

                    function runChannelDiagnostics() {{
                        document.getElementById('diagnosticsModal').style.display = 'block';
                        document.getElementById('diagnosticsResults').innerHTML = `
                            <div class="diagnostics-loading">
                                <p>Запуск диагностики...</p>
                                <div class="spinner"></div>
                            </div>
                        `;
                        
                        fetch('/channel-diagnostics')
                            .then(response => response.json())
                            .then(data => {{
                                let resultsHtml = '';
                                
                                if (data.status === 'completed') {{
                                    resultsHtml = `
                                        <div class="diagnostics-header">
                                            <h3>📊 Результаты диагностики</h3>
                                            <p><small>Время проверки: ${data.timestamp}</small></p>
                                        </div>
                                        
                                        <div class="diagnostics-steps">
                                            <h4>📋 Выполненные проверки:</h4>
                                            <ul>
                                                ${data.steps.map(step => `<li>${step}</li>`).join('')}
                                            </ul>
                                        </div>
                                        
                                        <div class="diagnostics-success" style="color: #27ae60; margin: 15px 0;">
                                            <h4>✅ Успешные проверки:</h4>
                                            <ul>
                                                ${data.success.map(item => `<li>${item}</li>`).join('')}
                                            </ul>
                                        </div>
                                    `;
                                    
                                    if (data.errors && data.errors.length > 0) {{
                                        resultsHtml += `
                                            <div class="diagnostics-errors" style="color: #e74c3c; margin: 15px 0;">
                                                <h4>❌ Обнаруженные ошибки:</h4>
                                                <ul>
                                                    ${data.errors.map(error => `<li>${error}</li>`).join('')}
                                                </ul>
                                            </div>
                                        `;
                                        
                                        // Показываем секцию исправления токена если есть ошибка бота
                                        if (data.bot_status === 'token_error' || data.bot_status === 'connection_error') {{
                                            document.getElementById('tokenFixSection').style.display = 'block';
                                        }}
                                    }}
                                    
                                    // Статус канала и метрики
                                    resultsHtml += `
                                        <div class="channel-status" style="margin-top: 20px; padding: 15px; background: #ecf0f1; border-radius: 5px;">
                                            <h4>📈 Статус канала:</h4>
                                            <p><strong>Подписчиков:</strong> ${data.member_count}</p>
                                            <p><strong>Статус бота:</strong> ${getStatusText(data.bot_status)}</p>
                                            <p><strong>Доступ к каналу:</strong> ${getStatusText(data.channel_status)}</p>
                                        </div>
                                        
                                        <div class="engagement-metrics" style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                                            <h4>📊 Метрики Engagement:</h4>
                                            <p><strong>Engagement Rate:</strong> ${data.engagement_metrics.engagement_rate ? data.engagement_metrics.engagement_rate.toFixed(1) + '%' : 'Нет данных'}</p>
                                            <p><strong>Конверсия в чат:</strong> ${data.engagement_metrics.chat_conversion_rate ? data.engagement_metrics.chat_conversion_rate.toFixed(1) + '%' : 'Нет данных'}</p>
                                            <p><strong>Релевантность контента:</strong> ${data.engagement_metrics.engagement_metrics ? data.engagement_metrics.engagement_metrics.avg_relevance.toFixed(0) + '/100' : 'Нет данных'}</p>
                                        </div>
                                    `;
                                    
                                }} else {{
                                    resultsHtml = `<div class="diagnostics-error">❌ Ошибка диагностики: ${data.message}</div>`;
                                }}
                                
                                document.getElementById('diagnosticsResults').innerHTML = resultsHtml;
                            }})
                            .catch(error => {{
                                document.getElementById('diagnosticsResults').innerHTML = `
                                    <div class="diagnostics-error">❌ Ошибка загрузки диагностики: ${error}</div>
                                `;
                            }});
                    }}

                    function getStatusText(status) {{
                        const statusMap = {{
                            'active': '✅ Активен',
                            'token_ok': '✅ Токен валиден',
                            'accessible': '✅ Доступен',
                            'token_error': '❌ Ошибка токена',
                            'connection_error': '❌ Ошибка подключения',
                            'access_error': '❌ Ошибка доступа',
                            'unknown': '⚪ Неизвестно'
                        }};
                        return statusMap[status] || status;
                    }}

                    function updateBotToken() {{
                        const newToken = document.getElementById('newBotToken').value.trim();
                        
                        if (!newToken) {{
                            alert('Введите новый токен бота');
                            return;
                        }}
                        
                        fetch('/fix-bot-token', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{ token: newToken }})
                        }})
                        .then(response => response.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Токен успешно обновлен!');
                                document.getElementById('tokenFixSection').style.display = 'none';
                                runChannelDiagnostics(); // Перезапускаем диагностику
                            }} else {{
                                alert('❌ Ошибка: ' + data.message);
                            }}
                        }})
                        .catch(error => {{
                            alert('❌ Ошибка обновления токена: ' + error);
                        }});
                    }}

                    function closeDiagnostics() {{
                        document.getElementById('diagnosticsModal').style.display = 'none';
                    }}

                    // Закрытие модального окна при клике вне его
                    window.onclick = function(event) {{
                        const modal = document.getElementById('diagnosticsModal');
                        if (event.target === modal) {{
                            closeDiagnostics();
                        }}
                    }}
                </script>
            </body>
        </html>
        """
        return html
        
    except Exception as e:
        logger.error(f"❌ Ошибка в главной странице: {e}")
        return f"Ошибка: {str(e)}"

# ОСТАЛЬНЫЕ МАРШРУТЫ (с защитой)
@app.route('/send-public-report')
@rate_limit
def send_public_report():
    """Отправка публичного отчета"""
    try:
        report = channel_analytics.generate_public_report()
        success = elite_channel.send_to_telegram(report, content_type='analytics')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/test-channel')
@rate_limit
def test_channel():
    """Тестирование канала"""
    current_times = TimeZoneConverter.get_current_times()
    test_message = f"""🎪 <b>ТЕСТ: Клуб Осознанного Долголетия @ppsupershef работает!</b>

Новая философия контента активирована:

🧠 <b>Нейропитание</b> - пища для ясности ума
💪 <b>Энергия</b> - топливо для достижений  
🛡️ <b>Долголетие</b> - стратегии здоровой жизни
🍽️ <b>Гастрономия</b> - наслаждение с пользой

🤖 <b>Автопостинг:</b> ✅ Активен
🎯 <b>Контент-план:</b> 28 постов/неделя
💫 <b>Философия:</b> Осознанное питание как инвестиция в качество жизни

Присоединяйтесь к клубу тех, кто выбирает осознанность!

🕐 Опубликовано: {current_times['kemerovo_time']}"""
    
    success = elite_channel.send_to_telegram(test_message, content_type='test')
    return jsonify({"status": "success" if success else "error"})

@app.route('/health')
@rate_limit
def health_check():
    """Проверка здоровья"""
    connection = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    member_count = channel_analytics.get_member_count()
    engagement_report = channel_analytics.get_engagement_report()
    
    return jsonify({
        "status": "healthy",
        "philosophy": "🎪 Клуб Осознанного Долголетия",
        "member_count": member_count,
        "scheduler_running": content_scheduler.is_running,
        "engagement_rate": f"{engagement_report.get('engagement_rate', 0):.1f}%",
        "time_info": current_times
    })

@app.route('/debug')
@rate_limit
def debug():
    """Страница отладки"""
    connection_test = elite_channel.test_connection()
    current_times = TimeZoneConverter.get_current_times()
    member_count = channel_analytics.get_member_count()
    engagement_report = channel_analytics.get_engagement_report()
    
    return jsonify({
        "status": "active",
        "philosophy": "Осознанное долголетие",
        "content_plan": "28 постов/неделя",
        "member_count": member_count,
        "engagement_rate": f"{engagement_report.get('engagement_rate', 0):.1f}%",
        "scheduler_status": "running" if content_scheduler.is_running else "stopped",
        "time_info": current_times
    })

@app.route('/send-poll')
@rate_limit
def send_poll():
    """Отправка опроса"""
    try:
        success = elite_channel.send_poll()
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-visual-content')
@rate_limit
def send_visual_content():
    """Отправка визуального контента"""
    try:
        # Простой визуальный контент
        visual_content = """🎨 <b>ИНФОГРАФИКА: Правило тарелки для долголетия</b>

🍽️ <b>Идеальное распределение продуктов:</b>

½ ТАРЕЛКИ - ОВОЩИ И ЗЕЛЕНЬ
• Брокколи, шпинат, цветная капуста
• Морковь, перец, огурцы
• Салатные листья, зелень

¼ ТАРЕЛКИ - БЕЛКИ  
• Куриная грудка, рыба, яйца
• Тофу, бобовые, орехи
• Творог, греческий йогурт

¼ ТАРЕЛКИ - СЛОЖНЫЕ УГЛЕВОДЫ
• Гречка, киноа, бурый рис
• Батат, цельнозерновой хлеб
• Овсяные хлопья

💫 <b>Плюс полезные жиры:</b>
• Оливковое масло, авокадо
• Орехи, семена

🎯 <b>Сохраните эту карточку для планирования питания!</b>

#инфографика #осознанноепитание #долголетие"""
        
        success = elite_channel.send_to_telegram(visual_content, content_type='visual')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-shopping-list')
@rate_limit
def send_shopping_list():
    """Отправка чек-листа покупок"""
    try:
        content = content_gen.generate_smart_shopping_list()
        success = elite_channel.send_to_telegram(content, content_type='shopping')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/format-preview')
@rate_limit
def format_preview():
    """Предпросмотр формата контента"""
    try:
        preview_content = """🎪 <b>КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ</b>

Станьте версией себя, которой восхищаетесь

🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА

🥑 Омлет с авокадо и шпинатом

Ингредиенты:
• Яйца - 2 шт
• Авокадо - ½ шт  
• Шпинат - 50 г
• Грецкие орехи - 20 г
• Оливковое масло - 1 ч.л.

Приготовление:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами

💡 Научное обоснование:
• Авокадо - омега-9 для мембран нейронов
• Шпинат - лютеин для когнитивных функций  
• Грецкие орехи - омега-3 для нейропластичности

⚡ Механизм действия:
• Улучшает проводимость нейронов
• Защищает клетки мозга
• Повышает скорость мышления

---
💫 <b>Вы не просто читаете рецепт - вы инвестируете в свое долголетие и энергию</b>

📢 <b>Подписывайтесь на канал!</b> → @ppsupershef
💬 <b>Обсуждаем в комментариях!</b> → @ppsupershef_chat

😋 вкусно | 💪 полезно | 👨‍🍳 приготовлю | 📝 запишу себе | 📚 на рецепты

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""
        
        success = elite_channel.send_to_telegram(preview_content, content_type='preview')
        return jsonify({"status": "success" if success else "error", "message": "Формат отправлен для предпросмотра"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# Маршруты для отправки контента
@app.route('/send-breakfast')
@rate_limit
def send_breakfast():
    """Отправка завтрака"""
    try:
        # Определяем текущий день недели для выбора правильного типа завтрака
        current_weekday = datetime.now(Config.KEMEROVO_TIMEZONE).weekday()
        breakfast_types = [
            "generate_neuro_breakfast", "generate_energy_breakfast", 
            "generate_longevity_breakfast", "generate_gastronomy_breakfast",
            "generate_analytical_breakfast", "generate_energy_breakfast",
            "generate_sunday_brunch"
        ]
        method_name = breakfast_types[current_weekday]
        method = getattr(content_gen, method_name)
        content = method()
        success = elite_channel.send_to_telegram(content, content_type=breakfast_types[current_weekday].replace('generate_', ''))
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-lunch')
@rate_limit
def send_lunch():
    """Отправка обеда"""
    try:
        content = content_gen.generate_energy_breakfast()
        success = elite_channel.send_to_telegram(content, content_type='lunch')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-science')
@rate_limit
def send_science():
    """Отправка научного контента"""
    try:
        content = content_gen.generate_science_content()
        success = elite_channel.send_to_telegram(content, content_type='science')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-interval')
@rate_limit
def send_interval():
    """Отправка контента про интервальное питание"""
    try:
        content = content_gen.generate_expert_advice()
        success = elite_channel.send_to_telegram(content, content_type='advice')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-dinner')
@rate_limit
def send_dinner():
    """Отправка ужина"""
    try:
        content = content_gen.generate_longevity_breakfast()
        success = elite_channel.send_to_telegram(content, content_type='dinner')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-advice')
@rate_limit
def send_advice():
    """Отправка советов экспертов"""
    try:
        content = content_gen.generate_expert_advice()
        success = elite_channel.send_to_telegram(content, content_type='advice')
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-manual-content', methods=['POST'])
@require_api_key
@rate_limit
def send_manual_content():
    """Отправка ручного контента"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        current_times = TimeZoneConverter.get_current_times()
        content_with_footer = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
        
        success = elite_channel.send_to_telegram(content_with_footer, content_type='manual')
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/webhook/telegram', methods=['POST'])
@rate_limit
def telegram_webhook():
    """Обработчик вебхука от Telegram"""
    try:
        data = request.get_json()
        SecureLogger.safe_log(f"📨 Получен вебхук от Telegram: {data}")
        
        # Обработка engagement метрик
        if 'message' in data and 'reply_to_message' in data['message']:
            # Это комментарий к посту
            message_id = data['message']['reply_to_message']['message_id']
            channel_analytics.update_engagement(message_id, 'comments')
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"status": "error"})

# Обработчик ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(429)
def rate_limit_exceeded(error):
    return jsonify({
        "status": "error", 
        "message": "Rate limit exceeded. Try again later."
    }), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {str(error)}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500

if __name__ == '__main__':
    # Запускаем безопасную диагностику токенов при старте
    print("🔍 Запуск БЕЗОПАСНОЙ диагностики токенов...")
    safe_debug_tokens()
    
    SecureLogger.safe_log(f"🚀 Запуск Клуба Осознанного Долголетия: @ppsupershef")
    SecureLogger.safe_log(f"🎯 Философия: Осознанное питание как инвестиция в качество жизни")
    SecureLogger.safe_log(f"📊 Контент-план: 28 постов в неделю (оптимизировано)")
    SecureLogger.safe_log(f"🛡️ Безопасность: Rate limiting и защита токенов активированы")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
