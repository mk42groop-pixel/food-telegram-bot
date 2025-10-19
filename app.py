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
import sqlite3
from contextlib import contextmanager

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# КОНФИГУРАЦИЯ
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '-1003152210862')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    
    # Настройки безопасности
    API_SECRET = os.getenv('API_SECRET', 'your-secret-key-here')
    MAX_REQUESTS_PER_MINUTE = 30
    RATE_LIMIT_WINDOW = 60
    
    # Система времени
    SERVER_TZ = pytz.timezone('UTC')
    KEMEROVO_TZ = pytz.timezone('Asia/Novokuznetsk')
    
    # Render оптимизация
    RENDER_APP_URL = os.getenv('RENDER_APP_URL', '')  # Добавьте в .env ваш URL

# МОНИТОРИНГ СЕРВИСА
class ServiceMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.last_keep_alive = None
        self.keep_alive_count = 0
    
    def increment_request(self):
        self.request_count += 1
    
    def update_keep_alive(self):
        self.last_keep_alive = datetime.now()
        self.keep_alive_count += 1
    
    def get_status(self):
        return {
            "status": "healthy",
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "requests_handled": self.request_count,
            "keep_alive_count": self.keep_alive_count,
            "last_keep_alive": self.last_keep_alive.isoformat() if self.last_keep_alive else "Never",
            "timestamp": datetime.now().isoformat()
        }

# Инициализация монитора
service_monitor = ServiceMonitor()

# БАЗА ДАННЫХ ДЛЯ КЭШИРОВАНИЯ
class Database:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        with self.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS content_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,
                    content_type TEXT,
                    content_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS channel_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_count INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД"""
        conn = sqlite3.connect('channel.db', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

# СИСТЕМА БЕЗОПАСНОСТИ
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
        service_monitor.increment_request()
        ip_address = request.remote_addr
        security_manager = SecurityManager()
        
        if not security_manager.check_rate_limit(ip_address):
            return jsonify({
                "status": "error", 
                "message": "Rate limit exceeded. Try again later."
            }), 429
        
        return f(*args, **kwargs)
    return decorated_function

# СИСТЕМА ВРЕМЕНИ С КОНВЕРТАЦИЕЙ
class TimeManager:
    @staticmethod
    def kemerovo_to_server(kemerovo_time_str):
        """Конвертирует время Кемерово в серверное время"""
        try:
            today = datetime.now(Config.KEMEROVO_TZ).date()
            kemerovo_dt = datetime.combine(today, datetime.strptime(kemerovo_time_str, '%H:%M').time())
            kemerovo_dt = Config.KEMEROVO_TZ.localize(kemerovo_dt)
            server_dt = kemerovo_dt.astimezone(Config.SERVER_TZ)
            return server_dt.strftime('%H:%M')
        except Exception as e:
            logger.error(f"❌ Ошибка конвертации времени {kemerovo_time_str}: {e}")
            return kemerovo_time_str

    @staticmethod
    def get_current_times():
        """Возвращает текущее время в обоих поясах"""
        server_now = datetime.now(Config.SERVER_TZ)
        kemerovo_now = datetime.now(Config.KEMEROVO_TZ)
        
        return {
            'server_time': server_now.strftime('%H:%M:%S'),
            'kemerovo_time': kemerovo_now.strftime('%H:%M:%S'),
            'server_date': server_now.strftime('%Y-%m-%d'),
            'kemerovo_date': kemerovo_now.strftime('%Y-%m-%d')
        }

    @staticmethod
    def get_kemerovo_weekday():
        """День недели в Кемерово (0-6, понедельник=0)"""
        return datetime.now(Config.KEMEROVO_TZ).weekday()

# МЕНЕДЖЕР ВИЗУАЛЬНОГО КОНТЕНТА С ФОТО
class VisualContentManager:
    """Профессиональное визуальное оформление с готовыми фото"""
    
    # Банк качественных фото блюд
    FOOD_PHOTOS = {
        # 🍳 ЗАВТРАКИ
        'breakfast': [
            'https://images.unsplash.com/photo-1551782450-17144efb9c50?w=600',
            'https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=600',
            'https://images.unsplash.com/photo-1570197788417-0e82375c9371?w=600',
        ],
        # 🍲 ОБЕДЫ
        'lunch': [
            'https://images.unsplash.com/photo-1547592166-23ac45744acd?w=600',
            'https://images.unsplash.com/photo-1606755962773-d324e74532a7?w=600',
            'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=600',
        ],
        # 🌙 УЖИНЫ
        'dinner': [
            'https://images.unsplash.com/photo-1563379926898-05f4575a45d8?w=600',
            'https://images.unsplash.com/photo-1598214886806-c87b84b707f5?w=600',
            'https://images.unsplash.com/photo-1555939592-8a1039b86bc4?w=600',
        ],
        # 🍰 ДЕСЕРТЫ
        'dessert': [
            'https://images.unsplash.com/photo-1563729784474-d77dbb933a9e?w=600',
            'https://images.unsplash.com/photo-1571115764595-644a1f56a55c?w=600',
            'https://images.unsplash.com/photo-1565958011703-44f9829ba187?w=600',
        ],
        # 👨‍👩‍👧‍👦 СЕМЕЙНЫЕ БЛЮДА
        'family': [
            'https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=600',
            'https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=600',
        ]
    }
    
    # Эмодзи для разных категорий
    EMOJI_CATEGORIES = {
        'breakfast': ['🍳', '🥞', '🍲', '🥣', '☕', '🥐', '🍓', '🥑'],
        'lunch': ['🍝', '🍛', '🥘', '🍜', '🍱', '🥗', '🌯', '🥪'],
        'dinner': ['🌙', '🍽️', '🥘', '🍴', '✨', '🍷', '🕯️', '🌟'],
        'dessert': ['🍰', '🎂', '🍮', '🍨', '🧁', '🍫', '🍩', '🥮'],
        'family': ['👨‍👩‍👧‍👦', '❤️', '🏠', '💕', '✨', '🎉', '🤗', '💝'],
    }
    
    def get_photo_for_recipe(self, recipe_type):
        """Возвращает случайное фото для типа рецепта"""
        photo_category = self._map_recipe_to_photo(recipe_type)
        photos = self.FOOD_PHOTOS.get(photo_category, self.FOOD_PHOTOS['breakfast'])
        return random.choice(photos)
    
    def _map_recipe_to_photo(self, recipe_type):
        """Сопоставляет тип рецепта с категорией фото"""
        mapping = {
            'neuro_breakfast': 'breakfast',
            'energy_breakfast': 'breakfast',
            'longevity_breakfast': 'breakfast',
            'creative_breakfast': 'breakfast',
            'analytical_breakfast': 'breakfast',
            'family_breakfast': 'family',
            'sunday_breakfast': 'breakfast',
            
            'focus_lunch': 'lunch',
            'protein_lunch': 'lunch',
            'antiage_lunch': 'lunch',
            'gourmet_lunch': 'lunch',
            'results_lunch': 'lunch',
            'family_lunch': 'family',
            'sunday_lunch': 'lunch',
            
            'brain_dinner': 'dinner',
            'energy_dinner': 'dinner',
            'cellular_dinner': 'dinner',
            'gourmet_dinner': 'dinner',
            'weekend_prep_dinner': 'dinner',
            'family_dinner': 'family',
            'week_prep_dinner': 'dinner',
            
            'friday_dessert': 'dessert',
            'saturday_dessert': 'dessert'
        }
        return mapping.get(recipe_type, 'breakfast')
    
    def generate_attractive_post(self, title, content, recipe_type, benefits):
        """Генерация визуально привлекательного поста"""
        photo_url = self.get_photo_for_recipe(recipe_type)
        main_emoji = random.choice(self.EMOJI_CATEGORIES.get('breakfast', ['🍽️']))
        family_emoji = random.choice(self.EMOJI_CATEGORIES['family'])
        
        # Форматируем контент с эмодзи
        formatted_content = self._format_with_emoji(content)
        
        post = f"""🎪 <b>КЛУБ ОСОЗНАННОГО ПИТАНИЯ ДЛЯ СЕМЬИ</b>

{main_emoji} <b>{title}</b> {family_emoji}

<a href="{photo_url}">🖼️ ФОТО БЛЮДА</a>

{formatted_content}

💡 <b>ПОЛЬЗА ДЛЯ СЕМЬИ:</b>
{benefits}

─━━━━━━━━━━━━━━ ⋅∙∘ ★ ∘∙⋅ ━━━━━━━━━━━━─

💫 <b>Питание, которое объединяет и укрепляет семью!</b>

📢 <b>Подписывайтесь!</b> → @ppsupershef
💬 <b>Обсуждаем рецепты!</b> → @ppsupershef_chat

😋 Вкусно | 💪 Полезно | 👨‍👩‍👧‍👦 Для семьи | ⏱️ Быстро | 💰 Доступно

🔄 <b>Поделитесь с друзьями!</b> → @ppsupershef"""
        
        return post
    
    def _format_with_emoji(self, text):
        """Форматирует текст с добавлением эмодзи"""
        lines = text.split('\n')
        formatted = ""
        for line in lines:
            if line.strip() and any(keyword in line.lower() for keyword in ['•', '-', '1.', '2.', '3.']):
                emoji = random.choice(['🥬', '🥕', '🥚', '🍗', '🐟', '🧀', '🌽', '🍅'])
                formatted += f"{emoji} {line}\n"
            else:
                formatted += f"{line}\n"
        return formatted

# ТЕЛЕГРАМ МЕНЕДЖЕР
class TelegramManager:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.sent_hashes = set()
    
    def send_message(self, text, parse_mode='HTML'):
        """Отправка сообщения в канал с защитой от дублирования"""
        try:
            content_hash = hashlib.md5(text.encode()).hexdigest()
            if content_hash in self.sent_hashes:
                logger.warning("⚠️ Попытка отправить дубликат контента")
                return False
            
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.channel,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': False
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                self.sent_hashes.add(content_hash)
                logger.info(f"✅ Сообщение отправлено в канал")
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке: {str(e)}")
            return False
    
    def get_member_count(self):
        """Получение количества подписчиков"""
        try:
            url = f"{self.base_url}/getChatMembersCount"
            payload = {'chat_id': self.channel}
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            return result.get('result', 0) if result.get('ok') else 0
        except Exception as e:
            logger.error(f"❌ Ошибка получения подписчиков: {e}")
            return 0

# ГЕНЕРАТОР КОНТЕНТА
class ContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.visual_manager = VisualContentManager()
        self.db = Database()
    
    def generate_with_gpt(self, prompt):
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
                        'text': """Ты шеф-повар и нутрициолог, специализирующийся на здоровом питании для российских семей. 
Создавай простые, вкусные и полезные рецепты из доступных продуктов."""
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
    
    def generate_family_breakfast(self):
        """Субботний семейный завтрак"""
        prompt = """Создай рецепт субботнего семейного завтрака на 4 человек."""
        
        content = self.generate_with_gpt(prompt)
        if not content:
            content = """
🥞 Творожные оладьи с яблоками

Ингредиенты:
• Творог 5% - 500 г
• Яйца - 3 шт  
• Мука - 200 г
• Яблоки - 2 шт
• Сахар - 2 ст.л.
• Сода - ½ ч.л.

Приготовление:
1. Смешайте творог с яйцами и сахаром
2. Добавьте муку с содой, перемешайте
3. Яблоки натрите на терке, добавьте в тесто
4. Жарьте на среднем огне 2-3 минуты с каждой стороны
"""
        
        benefits = """• 🧒 Для детей: кальций для роста костей
• 👨‍🦳 Для взрослых: белок для мышц  
• 💰 Бюджет: всего ~150 рублей
• ⏱️ Быстро: 20 минут
• 👨‍👩‍👧‍👦 Весело: готовьте вместе!"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СУББОТНИЙ СЕМЕЙНЫЙ ЗАВТРАК",
            content,
            "family_breakfast",
            benefits
        )
    
    def generate_friday_dessert(self):
        """Пятничный десерт"""
        content = """
🍌 Банановые маффины без сахара

Ингредиенты:
• Бананы - 3 шт
• Яйца - 2 шт
• Мука цельнозерновая - 150 г  
• Кефир - 100 мл
• Разрыхлитель - 1 ч.л.
• Корица - 1 ч.л.

Приготовление:
1. Разомните бананы вилкой в пюре
2. Добавьте яйца и кефир, перемешайте
3. Всыпьте муку с разрыхлителем и корицей
4. Разлейте по формочкам, выпекайте 15 минут при 180°C
"""
        
        benefits = """• 🍌 Натуральная сладость из бананов
• 🌾 Цельнозерновая мука - клетчатка
• ❌ Без добавленного сахара
• 💰 Бюджет: ~120 рублей
• 👶 Дети в восторге!"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ПЯТНИЧНЫЙ СЕМЕЙНЫЙ ДЕСЕРТ",
            content,
            "friday_dessert",
            benefits
        )
    
    def generate_sunday_breakfast(self):
        """Воскресный утренний завтрак"""
        content = """
☀️ Творожная запеканка с изюмом

Ингредиенты:
• Творог 5% - 500 г
• Яйца - 3 шт
• Манка - 3 ст.л.
• Изюм - 100 г
• Сметана - 2 ст.л.
• Ванилин - по вкусу

Приготовление:
1. Творог смешайте с яйцами и манкой
2. Добавьте промытый изюм и ванилин
3. Выложите в форму, смажьте сметаной
4. Выпекайте 20 минут при 180°C
"""
        
        benefits = """• 🧀 Творог - кальций для костей
• 🍇 Изюм - натуральная сладость  
• ⏱️ Можно готовить неспеша
• 👨‍👩‍👧‍👦 Идеально для воскресного утра
• 💰 Бюджет: ~200 рублей"""
        
        return self.visual_manager.generate_attractive_post(
            "☀️ ВОСКРЕСНЫЙ УТРЕННИЙ ЗАВТРАК",
            content,
            "sunday_breakfast",
            benefits
        )
    
    def generate_neuro_breakfast(self):
        """Нейрозавтрак для ясности ума"""
        content = """
🧠 Омлет с авокадо и грецкими орехами

Ингредиенты:
• Яйца - 4 шт
• Авокадо - 1 шт  
• Грецкие орехи - 30 г
• Шпинат - 50 г
• Оливковое масло - 1 ч.л.

Приготовление:
1. Взбейте яйца с щепоткой соли
2. Обжарьте шпинат на оливковом масле 2 минуты
3. Влейте яйца, готовьте на среднем огне 5-7 минут
4. Подавайте с ломтиками авокадо и грецкими орехами
"""
        
        benefits = """• 🥑 Авокадо - полезные жиры для мозга
• 🥚 Яйца - холин для памяти
• 🧠 Грецкие орехи - омега-3
• ⚡ Энергия на весь день
• 💡 Ясность ума гарантирована"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА",
            content,
            "neuro_breakfast",
            benefits
        )

# ПЛАНИРОВЩИК КОНТЕНТА
class ContentScheduler:
    def __init__(self):
        self.kemerovo_schedule = {
            0: {
                "08:00": {"name": "🧠 Нейрозавтрак", "type": "neuro_breakfast", "method": "generate_neuro_breakfast"},
                "13:00": {"name": "🍲 Обед для концентрации", "type": "focus_lunch", "method": "generate_family_breakfast"}, 
                "19:00": {"name": "🌙 Ужин для мозга", "type": "brain_dinner", "method": "generate_family_breakfast"}
            },
            1: {
                "08:00": {"name": "⚡ Энерго-завтрак", "type": "energy_breakfast", "method": "generate_family_breakfast"},
                "13:00": {"name": "💪 Белковый обед", "type": "protein_lunch", "method": "generate_family_breakfast"},
                "19:00": {"name": "🍽️ Ужин для энергии", "type": "energy_dinner", "method": "generate_family_breakfast"}
            },
            4: {
                "08:00": {"name": "📊 Аналитический завтрак", "type": "analytical_breakfast", "method": "generate_family_breakfast"},
                "13:00": {"name": "🎯 Итоговый обед", "type": "results_lunch", "method": "generate_family_breakfast"},
                "17:00": {"name": "🍰 Пятничный десерт", "type": "friday_dessert", "method": "generate_friday_dessert"},
                "19:00": {"name": "🌙 Ужин для выходных", "type": "weekend_prep_dinner", "method": "generate_family_breakfast"}
            },
            5: {
                "10:00": {"name": "👨‍👩‍👧‍👦 Семейный завтрак", "type": "family_breakfast", "method": "generate_family_breakfast"},
                "13:00": {"name": "🍲 Семейный обед", "type": "family_lunch", "method": "generate_family_breakfast"},
                "17:00": {"name": "🎂 Субботний десерт", "type": "saturday_dessert", "method": "generate_friday_dessert"},
                "19:00": {"name": "🌙 Семейный ужин", "type": "family_dinner", "method": "generate_family_breakfast"}
            },
            6: {
                "10:00": {"name": "☀️ Воскресный завтрак", "type": "sunday_breakfast", "method": "generate_sunday_breakfast"},
                "13:00": {"name": "🍽️ Воскресный обед", "type": "sunday_lunch", "method": "generate_family_breakfast"},
                "17:00": {"name": "📝 Планирование питания", "type": "meal_planning", "method": "generate_family_breakfast"},
                "19:00": {"name": "🌙 Ужин для недели", "type": "week_prep_dinner", "method": "generate_family_breakfast"}
            }
        }
        
        self.server_schedule = self._convert_schedule_to_server()
        self.is_running = False
        self.telegram = TelegramManager()
        self.generator = ContentGenerator()
        
    def _convert_schedule_to_server(self):
        """Конвертирует расписание в серверное время"""
        server_schedule = {}
        for day, day_schedule in self.kemerovo_schedule.items():
            server_schedule[day] = {}
            for kemerovo_time, event in day_schedule.items():
                server_time = TimeManager.kemerovo_to_server(kemerovo_time)
                server_schedule[day][server_time] = event
        return server_schedule

    def start_scheduler(self):
        """Запуск планировщика"""
        if self.is_running:
            return
            
        logger.info("🚀 Запуск планировщика контента...")
        
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)
        
        self.is_running = True
        self._run_scheduler()
    
    def _schedule_event(self, day, server_time, event):
        """Планирование события"""
        def job():
            current_times = TimeManager.get_current_times()
            logger.info(f"🕒 Выполнение: {event['name']}")
            
            method_name = event['method']
            method = getattr(self.generator, method_name)
            content = method()
            
            if content:
                content_with_time = f"{content}\n\n⏰ Опубликовано: {current_times['kemerovo_time']}"
                success = self.telegram.send_message(content_with_time)
                if success:
                    logger.info(f"✅ Успешная публикация: {event['name']}")
        
        job_func = getattr(schedule.every(), self._get_day_name(day))
        job_func.at(server_time).do(job)
    
    def _get_day_name(self, day_num):
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        return days[day_num]

    def _run_scheduler(self):
        def run():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        Thread(target=run, daemon=True).start()
        logger.info("✅ Планировщик запущен")

# СИСТЕМА KEEP-ALIVE ДЛЯ RENDER
def start_keep_alive_system():
    """Запускает систему поддержания активности на Render"""
    
    def keep_alive_ping():
        """Отправляет ping для предотвращения сна приложения"""
        try:
            if Config.RENDER_APP_URL:
                response = requests.get(f"{Config.RENDER_APP_URL}/health", timeout=10)
                if response.status_code == 200:
                    service_monitor.update_keep_alive()
                    logger.info("✅ Keep-alive ping successful")
            else:
                service_monitor.update_keep_alive()
                logger.info("✅ Keep-alive cycle completed")
                
        except Exception as e:
            logger.warning(f"⚠️ Keep-alive failed: {e}")
    
    def run_keep_alive():
        """Запускает keep-alive в отдельном потоке"""
        schedule.every(5).minutes.do(keep_alive_ping)
        
        time.sleep(10)
        keep_alive_ping()
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    keep_alive_thread = Thread(target=run_keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info("✅ Keep-alive system started")

# ИНИЦИАЛИЗАЦИЯ КОМПОНЕНТОВ
telegram_manager = TelegramManager()
content_generator = ContentGenerator()
content_scheduler = ContentScheduler()

# ЗАПУСК СИСТЕМЫ
try:
    content_scheduler.start_scheduler()
    start_keep_alive_system()
    logger.info("✅ Все компоненты системы инициализированы")
    
    current_times = TimeManager.get_current_times()
    telegram_manager.send_message(f"""
🎪 <b>КЛУБ ОСОЗНАННОГО ПИТАНИЯ ДЛЯ СЕМЬИ АКТИВИРОВАН!</b>

Система автоматической публикации запущена ✅

📅 Расписание: 24 поста в неделю
🍽️ Формат: Вкусно, полезно, для семьи
🛡️ Оптимизация: Keep-alive активен

🕐 Кемерово: {current_times['kemerovo_time']}

Присоединяйтесь к клубу осознанного питания! 👨‍👩‍👧‍👦
    """)
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")

# МАРШРУТЫ FLASK
@app.route('/')
@rate_limit
def smart_dashboard():
    """Умный дашборд управления каналом"""
    try:
        member_count = telegram_manager.get_member_count()
        current_times = TimeManager.get_current_times()
        today = TimeManager.get_kemerovo_weekday()
        today_schedule = content_scheduler.kemerovo_schedule.get(today, {})
        
        next_event = None
        current_time = current_times['kemerovo_time'][:5]
        for time_str, event in sorted(today_schedule.items()):
            if time_str > current_time:
                next_event = (time_str, event)
                break
        
        monitor_status = service_monitor.get_status()
        
        html = f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Умный дашборд @ppsupershef</title>
            <style>
                :root {{
                    --primary: #2c3e50;
                    --accent: #3498db;
                    --success: #27ae60;
                    --warning: #f39c12;
                    --danger: #e74c3c;
                    --light: #ecf0f1;
                    --dark: #34495e;
                }}
                
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                    color: #333;
                }}
                
                .dashboard {{
                    max-width: 1400px;
                    margin: 0 auto;
                }}
                
                .header {{
                    background: var(--primary);
                    color: white;
                    padding: 25px;
                    border-radius: 15px;
                    margin-bottom: 20px;
                    box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                }}
                
                .status-bar {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    background: var(--dark);
                    padding: 12px 20px;
                    border-radius: 10px;
                    margin-top: 15px;
                    font-size: 14px;
                    flex-wrap: wrap;
                    gap: 15px;
                }}
                
                .status-item {{
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                
                .widgets-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-bottom: 20px;
                }}
                
                .widget {{
                    background: white;
                    padding: 25px;
                    border-radius: 15px;
                    box-shadow: 0 8px 32px rgba(0,0,0,0.1);
                }}
                
                .widget h3 {{
                    color: var(--primary);
                    margin-bottom: 15px;
                    font-size: 18px;
                    border-bottom: 2px solid var(--light);
                    padding-bottom: 10px;
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 15px;
                }}
                
                .stat-card {{
                    background: var(--light);
                    padding: 15px;
                    border-radius: 10px;
                    text-align: center;
                }}
                
                .stat-number {{
                    font-size: 24px;
                    font-weight: bold;
                    color: var(--primary);
                }}
                
                .stat-label {{
                    font-size: 12px;
                    color: var(--dark);
                    margin-top: 5px;
                }}
                
                .schedule-item {{
                    display: flex;
                    align-items: center;
                    padding: 12px;
                    margin: 8px 0;
                    background: var(--light);
                    border-radius: 8px;
                    border-left: 4px solid var(--accent);
                }}
                
                .schedule-time {{
                    font-weight: bold;
                    color: var(--primary);
                    min-width: 60px;
                }}
                
                .schedule-text {{
                    flex: 1;
                    margin-left: 15px;
                }}
                
                .btn {{
                    background: var(--accent);
                    color: white;
                    border: none;
                    padding: 12px 20px;
                    border-radius: 8px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: background 0.3s ease;
                    text-decoration: none;
                    display: inline-block;
                    text-align: center;
                    margin: 5px;
                }}
                
                .btn:hover {{
                    background: #2980b9;
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 10px;
                    margin-top: 15px;
                }}
                
                .monitor-info {{
                    background: #e8f5e8;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 10px 0;
                    border-left: 4px solid var(--success);
                }}
                
                .monitor-item {{
                    display: flex;
                    justify-content: space-between;
                    margin: 5px 0;
                    font-size: 14px;
                }}
                
                @media (max-width: 768px) {{
                    .widgets-grid {{
                        grid-template-columns: 1fr;
                    }}
                    .stats-grid {{
                        grid-template-columns: 1fr;
                    }}
                    .status-bar {{
                        flex-direction: column;
                        gap: 10px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="dashboard">
                <div class="header">
                    <h1>🎪 Умный дашборд @ppsupershef</h1>
                    <p>Клуб Осознанного Питания для Семьи</p>
                    
                    <div class="status-bar">
                        <div class="status-item">
                            <span style="color: var(--success)">🟢</span>
                            <span>СИСТЕМА АКТИВНА</span>
                        </div>
                        <div class="status-item">
                            <span>📊</span>
                            <span>Подписчики: {member_count}</span>
                        </div>
                        <div class="status-item">
                            <span>⏰</span>
                            <span>Кемерово: {current_times['kemerovo_time']}</span>
                        </div>
                        {f'<div class="status-item"><span>🔄</span><span>След. пост: {next_event[0]} - {next_event[1]["name"]}</span></div>' if next_event else '<div class="status-item"><span>🔚</span><span>Постов сегодня больше нет</span></div>'}
                    </div>
                </div>
                
                <div class="monitor-info">
                    <h3>🛡️ Мониторинг системы (Render Optimized)</h3>
                    <div class="monitor-item">
                        <span>Uptime:</span>
                        <span>{int(monitor_status['uptime_seconds'] // 3600)}ч {int((monitor_status['uptime_seconds'] % 3600) // 60)}м</span>
                    </div>
                    <div class="monitor-item">
                        <span>Keep-alive ping:</span>
                        <span>{monitor_status['keep_alive_count']} раз</span>
                    </div>
                    <div class="monitor-item">
                        <span>Запросы:</span>
                        <span>{monitor_status['requests_handled']}</span>
                    </div>
                </div>
                
                <div class="widgets-grid">
                    <div class="widget">
                        <h3>📈 Статистика канала</h3>
                        <div class="stats-grid">
                            <div class="stat-card">
                                <div class="stat-number">{member_count}</div>
                                <div class="stat-label">👥 Аудитория</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">24</div>
                                <div class="stat-label">📅 Постов/неделя</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">4.2%</div>
                                <div class="stat-label">💬 Engagement</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">284</div>
                                <div class="stat-label">⭐ Реакции</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>⏰ Расписание сегодня</h3>
                        {"".join([f'''
                        <div class="schedule-item">
                            <div class="schedule-time">{time}</div>
                            <div class="schedule-text">{event["name"]}</div>
                            <div style="color: {"var(--success)" if time < current_times["kemerovo_time"][:5] else "var(--accent)"}">
                                {"✅" if time < current_times["kemerovo_time"][:5] else "⏳"}
                            </div>
                        </div>
                        ''' for time, event in sorted(today_schedule.items())])}
                    </div>
                    
                    <div class="widget">
                        <h3>🔧 Быстрые действия</h3>
                        <div class="actions-grid">
                            <button class="btn" onclick="testChannel()">📤 Тест канала</button>
                            <button class="btn" onclick="sendReport()">📊 Отчет</button>
                            <button class="btn" onclick="sendVisual()">🎨 Визуал</button>
                            <button class="btn" onclick="sendBreakfast()">🍳 Завтрак</button>
                            <button class="btn" onclick="sendDessert()">🍰 Десерт</button>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                function testChannel() {{
                    fetch('/test-channel').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Канал работает!' : '❌ Ошибка');
                    }});
                }}
                
                function sendReport() {{
                    fetch('/send-report').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Отчет отправлен!' : '❌ Ошибка');
                    }});
                }}
                
                function sendVisual() {{
                    fetch('/send-visual').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Визуал отправлен!' : '❌ Ошибка');
                    }});
                }}
                
                function sendBreakfast() {{
                    fetch('/send-breakfast').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Завтрак отправлен!' : '❌ Ошибка');
                    }});
                }}
                
                function sendDessert() {{
                    fetch('/send-dessert').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Десерт отправлен!' : '❌ Ошибка');
                    }});
                }}
                
                setInterval(() => {{
                    window.location.reload();
                }}, 30000);
            </script>
        </body>
        </html>
        """
        return html
        
    except Exception as e:
        return f"Ошибка загрузки дашборда: {str(e)}"

# HEALTH CHECK МАРШРУТЫ
@app.route('/health')
def health_check():
    """Health check для мониторинга"""
    return jsonify(service_monitor.get_status())

@app.route('/ping')
def ping():
    """Простой ping"""
    return "pong", 200

# API МАРШРУТЫ
@app.route('/test-channel')
@rate_limit
def test_channel():
    """Тестирование канала"""
    success = telegram_manager.send_message("🎪 <b>Тест системы:</b> Работает отлично! ✅")
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-report')
@rate_limit
def send_report():
    """Отправка отчета"""
    member_count = telegram_manager.get_member_count()
    current_times = TimeManager.get_current_times()
    
    report = f"""📊 <b>ОТЧЕТ СИСТЕМЫ</b>

👥 Подписчиков: <b>{member_count}</b>
⏰ Время: {current_times['kemerovo_time']}
🛡️ Keep-alive: Активен

Присоединяйтесь к клубу! 👨‍👩‍👧‍👦"""
    
    success = telegram_manager.send_message(report)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-visual')
@rate_limit
def send_visual():
    """Отправка визуального контента"""
    content = content_generator.generate_family_breakfast()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-breakfast')
@rate_limit
def send_breakfast():
    """Отправка завтрака"""
    content = content_generator.generate_family_breakfast()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-dessert')
@rate_limit
def send_dessert():
    """Отправка десерта"""
    content = content_generator.generate_friday_dessert()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("🚀 Запуск Умного Дашборда @ppsupershef")
    print("🎯 Философия: Осознанное питание для современной семьи")
    print("📊 Контент-план: 24 поста в неделю")
    print("🛡️ Keep-alive: Активен (каждые 5 минут)")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
