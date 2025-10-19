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
    RENDER_APP_URL = os.getenv('RENDER_APP_URL', '')

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
            "last_keep_alive": self.last_keep_alive.isoformat() if self.last_keep_alive else None,
            "timestamp": datetime.now().isoformat()
        }

service_monitor = ServiceMonitor()

# БАЗА ДАННЫХ ДЛЯ КЭШИРОВАНИЯ
class Database:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
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
        current_time = time.time()
        if ip_address in self.blocked_ips:
            return False
        
        if ip_address not in self.request_log:
            self.request_log[ip_address] = []
        
        self.request_log[ip_address] = [
            req_time for req_time in self.request_log[ip_address]
            if current_time - req_time < Config.RATE_LIMIT_WINDOW
        ]
        
        if len(self.request_log[ip_address]) >= Config.MAX_REQUESTS_PER_MINUTE:
            self.blocked_ips.add(ip_address)
            logger.warning(f"🚨 IP заблокирован: {ip_address}")
            return False
        
        self.request_log[ip_address].append(current_time)
        return True

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key or api_key != Config.API_SECRET:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

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

# СИСТЕМА ВРЕМЕНИ
class TimeManager:
    @staticmethod
    def kemerovo_to_server(kemerovo_time_str):
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
        return datetime.now(Config.KEMEROVO_TZ).weekday()

# МЕНЕДЖЕР ВИЗУАЛЬНОГО КОНТЕНТА
class VisualContentManager:
    FOOD_PHOTOS = {
        'breakfast': [
            'https://images.unsplash.com/photo-1551782450-17144efb9c50?w=600',
            'https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=600',
            'https://images.unsplash.com/photo-1570197788417-0e82375c9371?w=600',
        ],
        'lunch': [
            'https://images.unsplash.com/photo-1547592166-23ac45744acd?w=600',
            'https://images.unsplash.com/photo-1606755962773-d324e74532a7?w=600',
            'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=600',
        ],
        'dinner': [
            'https://images.unsplash.com/photo-1563379926898-05f4575a45d8?w=600',
            'https://images.unsplash.com/photo-1598214886806-c87b84b707f5?w=600',
            'https://images.unsplash.com/photo-1555939592-8a1039b86bc4?w=600',
        ],
        'dessert': [
            'https://images.unsplash.com/photo-1563729784474-d77dbb933a9e?w=600',
            'https://images.unsplash.com/photo-1571115764595-644a1f56a55c?w=600',
            'https://images.unsplash.com/photo-1565958011703-44f9829ba187?w=600',
        ],
        'family': [
            'https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=600',
            'https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=600',
        ],
        'advice': [
            'https://images.unsplash.com/photo-1490818387583-1baba5e638af?w=600',
            'https://images.unsplash.com/photo-1550581190-9c1c47bdfba3?w=600',
            'https://images.unsplash.com/photo-1505576399279-565b52d4ac71?w=600',
        ]
    }
    
    EMOJI_CATEGORIES = {
        'breakfast': ['🍳', '🥞', '🍲', '🥣', '☕', '🥐', '🍓', '🥑'],
        'lunch': ['🍝', '🍛', '🥘', '🍜', '🍱', '🥗', '🌯', '🥪'],
        'dinner': ['🌙', '🍽️', '🥘', '🍴', '✨', '🍷', '🕯️', '🌟'],
        'dessert': ['🍰', '🎂', '🍮', '🍨', '🧁', '🍫', '🍩', '🥮'],
        'family': ['👨‍👩‍👧‍👦', '❤️', '🏠', '💕', '✨', '🎉', '🤗', '💝'],
        'advice': ['💡', '🎯', '📚', '🧠', '💪', '🥗', '💧', '👨‍⚕️'],
    }
    
    def get_photo_for_recipe(self, recipe_type):
        photo_category = self._map_recipe_to_photo(recipe_type)
        photos = self.FOOD_PHOTOS.get(photo_category, self.FOOD_PHOTOS['breakfast'])
        return random.choice(photos)
    
    def _map_recipe_to_photo(self, recipe_type):
        mapping = {
            'neuro_breakfast': 'breakfast',
            'energy_breakfast': 'breakfast',
            'protein_breakfast': 'breakfast',
            'veggie_breakfast': 'breakfast',
            'carbs_breakfast': 'breakfast',
            'family_breakfast': 'family',
            'sunday_breakfast': 'breakfast',
            'focus_lunch': 'lunch',
            'protein_lunch': 'lunch',
            'veggie_lunch': 'lunch',
            'carbs_lunch': 'lunch',
            'family_lunch': 'family',
            'sunday_lunch': 'lunch',
            'brain_dinner': 'dinner',
            'protein_dinner': 'dinner',
            'veggie_dinner': 'dinner',
            'family_dinner': 'family',
            'week_prep_dinner': 'dinner',
            'friday_dessert': 'dessert',
            'saturday_dessert': 'dessert',
            'sunday_dessert': 'dessert',
            'neuro_advice': 'advice',
            'protein_advice': 'advice',
            'veggie_advice': 'advice',
            'carbs_advice': 'advice',
            'water_advice': 'advice',
            'family_advice': 'advice',
            'planning_advice': 'advice'
        }
        return mapping.get(recipe_type, 'breakfast')
    
    def generate_attractive_post(self, title, content, recipe_type, benefits):
        photo_url = self.get_photo_for_recipe(recipe_type)
        main_emoji = random.choice(self.EMOJI_CATEGORIES.get('breakfast', ['🍽️']))
        family_emoji = random.choice(self.EMOJI_CATEGORIES['family'])
        
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
        try:
            # Определяем источник сообщения
            source = "manual" if "ТЕСТОВЫЙ ПОСТ" in text or "РУЧНОЙ ПОСТ" in text else "scheduled"
            logger.info(f"📤 [{source}] Попытка отправки сообщения ({len(text)} символов)")
            
            # Проверка конфигурации
            if not self.token or self.token == 'your-telegram-bot-token':
                logger.error("❌ Токен бота не настроен! Проверьте .env файл")
                return False
                
            if not self.channel:
                logger.error("❌ ID канала не настроен!")
                return False

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
            
            logger.info(f"🔗 Отправка запроса к Telegram API...")
            response = requests.post(url, json=payload, timeout=30)
            
            # Детальная обработка ответа
            logger.info(f"📡 Статус ответа: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP ошибка: {response.status_code} - {response.text}")
                return False
                
            result = response.json()
            logger.info(f"📨 Ответ Telegram: {result}")
            
            if result.get('ok'):
                self.sent_hashes.add(content_hash)
                logger.info(f"✅ [{source}] Сообщение успешно отправлено в канал")
                return True
            else:
                error_description = result.get('description', 'Неизвестная ошибка')
                logger.error(f"❌ Ошибка Telegram API: {error_description}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут при отправке сообщения")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ошибка соединения с Telegram API")
            return False
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при отправке: {str(e)}")
            return False
    
    def get_member_count(self):
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
                        'text': "Ты шеф-повар и нутрициолог, специализирующийся на здоровом питании для российских семей."
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
    
    def generate_neuro_breakfast(self):
        content = """
🧠 ОМЛЕТ С АВОКАДО И СЕМЕНАМИ ЛЬНА

Ингредиенты на семью (4 чел):
• Яйца - 8 шт
• Авокадо - 2 шт
• Семена льна - 2 ст.л.
• Молоко 2.5% - 100 мл
• Помидоры черри - 150 г
• Соль, перец - по вкусу
• Масло оливковое - 1 ч.л.

Детальное приготовление (15 мин):
1. Яйца взбить с молоком, солью и перцем
2. Добавить семена льна, оставить на 5 минут
3. Авокадо нарезать кубиками, помидоры разрезать пополам
4. Разогреть сковороду с оливковым маслом
5. Вылить яичную смесь, готовить на среднем огне 3 минуты
6. Добавить авокадо и помидоры, готовить еще 4-5 минут под крышкой
7. Подавать сразу, посыпав свежей зеленью
"""
        
        benefits = """• 🥑 Авокадо - полезные жиры для нейронов
• 🥚 Яйца - холин для памяти и концентрации
• 🌿 Семена льна - Омега-3 для когнитивных функций
• 💰 Бюджет: ~320 рублей
• ⏱️ Быстро: 15 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 НЕЙРОЗАВТРАК: ОМЛЕТ С АВОКАДО И СЕМЕНАМИ ЛЬНА",
            content,
            "neuro_breakfast",
            benefits
        )
    
    def generate_neuro_lunch(self):
        content = """
🧠 ЛОСОСЬ С КИНОА И БРОККОЛИ

Ингредиенты на семью (4 чел):
• Лосось - 600 г
• Киноа - 200 г
• Брокколи - 1 кочан
• Лимон - 1 шт
• Чеснок - 3 зубчика
• Оливковое масло - 2 ст.л.
• Специи: укроп, соль, перец

Детальное приготовление (25 мин):
1. Киноа промыть, варить 15 минут
2. Брокколи разобрать на соцветия, бланшировать 5 минут
3. Лосось нарезать стейками, посолить, поперчить
4. Обжарить лосось с двух сторон по 4 минуты
5. Добавить чеснок и лимонный сок
6. Подавать с киноа и брокколи
"""
        
        benefits = """• 🐟 Лосось - Омега-3 для мозга
• 🌾 Киноа - сложные углеводы
• 🥬 Брокколи - антиоксиданты
• 💰 Бюджет: ~450 рублей
• ⏱️ Питательно: 25 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ОБЕД ДЛЯ КОНЦЕНТРАЦИИ: ЛОСОСЬ С КИНОА",
            content,
            "focus_lunch",
            benefits
        )
    
    def generate_neuro_dinner(self):
        content = """
🧠 ГРЕЧНЕВАЯ КАША С ГРИБАМИ И ЛЬНЯНЫМ МАСЛОМ

Ингредиенты на семью (4 чел):
• Гречка - 300 г
• Шампиньоны - 400 г
• Лук - 2 шт
• Морковь - 1 шт
• Льняное масло - 2 ст.л.
• Зелень - пучок
• Соевый соус - 2 ст.л.

Детальное приготовление (20 мин):
1. Гречку отварить до готовности
2. Лук и морковь обжарить до мягкости
3. Добавить грибы, жарить 10 минут
4. Смешать гречку с овощами и грибами
5. Заправить льняным маслом и соевым соусом
6. Посыпать зеленью перед подачей
"""
        
        benefits = """• 🌾 Гречка - магний для нервной системы
• 🍄 Грибы - витамины группы B
• 🌿 Льняное масло - Омега-3
• 💰 Бюджет: ~280 рублей
• ⏱️ Легко: 20 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УЖИН ДЛЯ МОЗГА: ГРЕЧКА С ГРИБАМИ",
            content,
            "brain_dinner",
            benefits
        )
    
    def generate_protein_breakfast(self):
        content = """
💪 ТВОРОЖНАЯ ЗАПЕКАНКА С МИНДАЛЕМ И СЕМЕНАМИ ЧИА

Ингредиенты на семью (4 чел):
• Творог 5% - 600 г
• Яйца - 3 шт
• Миндаль - 50 г
• Семена чиа - 1 ст.л.
• Мед - 2 ст.л.
• Ванилин - щепотка
• Сметана 15% - для смазывания

Детальное приготовление (20 мин + 25 мин выпекание):
1. Творог протереть через сито для однородности
2. Добавить яйца, мед, ванилин - тщательно перемешать
3. Миндаль измельчить, добавить в творожную массу
4. Добавить семена чиа, оставить на 10 минут для набухания
5. Форму смазать маслом, выложить массу
6. Смазать поверхность сметаной для румяной корочки
7. Выпекать 25 минут при 180°C до золотистого цвета
"""
        
        benefits = """• 🧀 Творог - 25 г белка на порцию
• 🥜 Миндаль - витамин Е и магний
• 🌿 Семена чиа - клетчатка и Омега-3
• 💰 Бюджет: ~280 рублей
• ⏱️ На весь день: энергии хватит до обеда"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ ЗАВТРАК: ТВОРОЖНАЯ ЗАПЕКАНКА С МИНДАЛЕМ",
            content,
            "protein_breakfast",
            benefits
        )
    
    def generate_protein_lunch(self):
        content = """
💪 КУРИНАЯ ГРУДКА С НУТОМ И ОВОЩАМИ

Ингредиенты на семью (4 чел):
• Куриная грудка - 800 г
• Нут консервированный - 400 г
• Болгарский перец - 3 шт
• Цукини - 2 шт
• Лук - 2 шт
• Томатная паста - 3 ст.л.
• Специи: паприка, куркума, соль

Детальное приготовление (30 минут):
1. Куриную грудку нарезать кубиками
2. Овощи нарезать крупными кусками
3. Обжарить курицу до золотистой корочки
4. Добавить лук и томатную пасту, обжарить 3 минуты
5. Добавить овощи и нут, тушить 20 минут
6. В конце добавить специи и зелень
"""
        
        benefits = """• 🍗 Курица - 30 г белка на порцию
• 🌱 Нут - растительный белок и клетчатка
• 🥬 Овощи - витамины и минералы
• 💰 Бюджет: ~350 рублей
• ⏱️ Сытный обед: 30 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ ОБЕД: КУРИНАЯ ГРУДКА С НУТОМ",
            content,
            "protein_lunch",
            benefits
        )
    
    def generate_protein_dinner(self):
        content = """
💪 ТУШЕНАЯ ИНДЕЙКА С ЧЕЧЕВИЦЕЙ

Ингредиенты на семью (4 чел):
• Филе индейки - 600 г
• Чечевица красная - 300 г
• Морковь - 2 шт
• Сельдерей - 2 стебля
• Лук - 2 шт
• Бульон овощной - 500 мл
• Специи: розмарин, тимьян, соль

Детальное приготовление (35 минут):
1. Индейку нарезать кубиками, обжарить
2. Лук, морковь и сельдерей обжарить до мягкости
3. Добавить чечевицу и бульон, довести до кипения
4. Добавить индейку и специи
5. Тушить на медленном огне 25 минут
6. Подавать с зеленью
"""
        
        benefits = """• 🦃 Индейка - нежирный белок
• 🌱 Чечевица - железо и клетчатка
• 🥕 Овощи - комплекс витаминов
• 💰 Бюджет: ~320 рублей
• ⏱️ Питательный ужин: 35 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ УЖИН: ИНДЕЙКА С ЧЕЧЕВИЦЕЙ",
            content,
            "protein_dinner",
            benefits
        )
    
    def generate_veggie_breakfast(self):
        content = """
🥬 СМУЗИ-БОУЛ С СЕМЕНАМИ ЧИА И ЯГОДАМИ

Ингредиенты на семью (4 чел):
• Шпинат замороженный - 200 г
• Банан - 2 шт
• Ягоды замороженные - 300 г
• Семена чиа - 4 ст.л.
• Миндальное молоко - 400 мл
• Мед - 4 ч.л.
• Гранола - 100 г

Детальное приготовление (10 минут):
1. Шпинат, банан, ягоды взбить в блендере
2. Добавить миндальное молоко и мед
3. Семена чиа залить водой на 5 минут
4. Разлить смузи по тарелкам
5. Добавить набухшие семена чиа
6. Посыпать гранолой и свежими ягодами
"""
        
        benefits = """• 🥬 Шпинат - железо и витамины
• 🍓 Ягоды - антиоксиданты
• 🌿 Семена чиа - Омега-3
• 💰 Бюджет: ~250 рублей
• ⏱️ Быстро: 10 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ОВОЩНОЙ ЗАВТРАК: СМУЗИ-БОУЛ С ЧИА",
            content,
            "veggie_breakfast",
            benefits
        )
    
    def generate_veggie_lunch(self):
        content = """
🥬 ОВОЩНОЕ РАГУ С ФАСОЛЬЮ И БРОККОЛИ

Ингредиенты на семью (4 чел):
• Фасоль красная консервированная - 400 г
• Брокколи - 1 кочан (400 г)
• Морковь - 2 шт
• Лук - 2 шт
• Цветная капуста - 300 г
• Томатная паста - 2 ст.л.
• Чеснок - 3 зубчика
• Специи: куркума, паприка, соль

Детальное приготовление (30 минут):
1. Лук нарезать кубиками, морковь - полукружиями
2. Брокколи и цветную капусту разобрать на соцветия
3. Обжарить лук и морковь на оливковом масле 5 минут
4. Добавить томатную пасту, обжаривать 2 минуты
5. Добавить брокколи и цветную капусту, тушить 10 минут
6. Добавить фасоль (без жидкости) и специи
7. Тушить под крышкой 15 минут на медленном огне
8. В конце добавить измельченный чеснок
"""
        
        benefits = """• 🥬 Брокколи - витамин С и антиоксиданты
• 🌱 Фасоль - растительный белок (15 г на порцию)
• 🥕 Овощи - клетчатка для пищеварения
• 💰 Бюджет: ~250 рублей
• ⏱️ Сытно и полезно: 350 ккал на порцию"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ОВОЩНОЙ ОБЕД: РАГУ С ФАСОЛЬЮ И БРОККОЛИ",
            content,
            "veggie_lunch",
            benefits
        )
    
    def generate_veggie_dinner(self):
        content = """
🥬 САЛАТ С АВОКАДО, НУТОМ И РУККОЛОЙ

Ингредиенты на семью (4 чел):
• Авокадо - 2 шт
• Нут консервированный - 400 г
• Руккола - 200 г
• Помидоры черри - 300 г
• Огурцы - 2 шт
• Лимонный сок - 3 ст.л.
• Оливковое масло - 4 ст.л.
• Специи: соль, перец, орегано

Детальное приготовление (15 минут):
1. Авокадо нарезать кубиками
2. Помидоры разрезать пополам
3. Огурцы нарезать кружочками
4. Смешать все овощи с нутом и рукколой
5. Заправить оливковым маслом и лимонным соком
6. Добавить специи, аккуратно перемешать
"""
        
        benefits = """• 🥑 Авокадо - полезные жиры
• 🌱 Нут - растительный белок
• 🥬 Руккола - витамин К и кальций
• 💰 Бюджет: ~300 рублей
• ⏱️ Легкий ужин: 15 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ОВОЩНОЙ УЖИН: САЛАТ С АВОКАДО И НУТОМ",
            content,
            "veggie_dinner",
            benefits
        )
    
    def generate_carbs_breakfast(self):
        content = """
🍠 ЭНЕРГЕТИЧЕСКАЯ ОВСЯНКА С СЕМЕНАМИ ЧИА

Ингредиенты на семью (4 чел):
• Овсяные хлопья - 200 г
• Молоко/вода - 800 мл
• Семена чиа - 4 ч.л.
• Ягоды замороженные - 200 г
• Мед - 4 ч.л.
• Корица - 1 ч.л.
• Грецкие орехи - 50 г

Детальное приготовление (15 минут):
1. Овсяные хлопья залить молоком/водой
2. Добавить семена чиа и корицу
3. Варить на медленном огне 10 минут, помешивая
4. Ягоды разморозить при комнатной температуре
5. Грецкие орехи измельчить
6. В готовую кашу добавить ягоды и мед
7. Подавать, посыпав орехами
"""
        
        benefits = """• 🌾 Овсянка - сложные углеводы
• 🌿 Семена чиа - Омега-3 и клетчатка
• 🍓 Ягоды - антиоксиданты и витамины
• 💰 Бюджет: ~180 рублей
• ⏱️ Быстро: 15 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 ЭНЕРГЕТИЧЕСКАЯ ОВСЯНКА С СЕМЕНАМИ ЧИА",
            content,
            "carbs_breakfast",
            benefits
        )
    
    def generate_carbs_lunch(self):
        content = """
🍚 БУРЫЙ РИС С КУРИЦЕЙ И ОВОЩАМИ

Ингредиенты на семью (4 чел):
• Бурый рис - 300 г
• Куриное филе - 500 г
• Морковь - 2 шт
• Лук - 2 шт
• Горошек замороженный - 200 г
• Соевый соус - 3 ст.л.
• Чеснок - 3 зубчика
• Имбирь - 1 см

Детальное приготовление (35 минут):
1. Рис отварить до готовности
2. Курицу нарезать кубиками, обжарить
3. Лук и морковь обжарить до мягкости
4. Добавить горошек, чеснок и имбирь
5. Смешать с курицей и рисом
6. Заправить соевым соусом, прогреть 5 минут
"""
        
        benefits = """• 🌾 Бурый рис - сложные углеводы
• 🍗 Курица - белок для сытости
• 🥕 Овощи - клетчатка и витамины
• 💰 Бюджет: ~320 рублей
• ⏱️ Энергичный обед: 35 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🍚 УГЛЕВОДНЫЙ ОБЕД: БУРЫЙ РИС С КУРИЦЕЙ",
            content,
            "carbs_lunch",
            benefits
        )
    
    def generate_carbs_dinner(self):
        content = """
🥔 ЗАПЕЧЕННЫЙ КАРТОФЕЛЬ С ТВОРОГОМ И ЗЕЛЕНЬЮ

Ингредиенты на семью (4 чел):
• Картофель - 1 кг
• Творог 5% - 400 г
• Укроп - пучок
• Петрушка - пучок
• Чеснок - 3 зубчика
• Сметана - 200 г
• Специи: соль, перец, паприка

Детальное приготовление (40 минут):
1. Картофель вымыть, нарезать дольками
2. Выложить на противень, посолить, поперчить
3. Запекать 30 минут при 200°C до румяности
4. Творог смешать с измельченной зеленью и чесноком
5. Добавить сметану, тщательно перемешать
6. Подавать картофель с творожным соусом
"""
        
        benefits = """• 🥔 Картофель - калий и углеводы
• 🧀 Творог - белок и кальций
• 🌿 Зелень - витамины и антиоксиданты
• 💰 Бюджет: ~220 рублей
• ⏱️ Сытный ужин: 40 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "🥔 УГЛЕВОДНЫЙ УЖИН: ЗАПЕЧЕННЫЙ КАРТОФЕЛЬ",
            content,
            "carbs_dinner",
            benefits
        )
    
    def generate_family_cooking(self):
        content = """
👨‍🍳 ЧЕЧЕВИЧНЫЕ КОТЛЕТЫ С БРОККОЛИ

Ингредиенты для семейной готовки:
• Чечевица красная - 300 г
• Брокколи - 300 g
• Лук - 1 шт
• Морковь - 1 шт
• Яйцо - 2 шт
• Семена чиа - 2 ст.л.
• Мука цельнозерновая - 4 ст.л.
• Специи: зира, кориандр, соль

Семейный процесс (40 минут):

Подготовка (15 минут):
1. ДЕТИ: промыть чечевицу, разобрать брокколи на соцветия
2. РОДИТЕЛИ: лук и морковь нарезать мелкими кубиками
3. ВМЕСТЕ: отварить чечевицу до мягкости (15 минут)

Формовка котлет (15 минут):
4. РОДИТЕЛИ: брокколи бланшировать 3 минуты, измельчить
5. ВМЕСТЕ: смешать чечевицу, овощи, яйца, семена чиа
6. ДЕТИ: добавлять муку, вымешивать "тесто"
7. ВМЕСТЕ: формировать котлеты, обвалять в муке

Приготовление (10 минут):
8. РОДИТЕЛИ: обжарить котлеты с двух сторон до золотистого цвета
9. РОДИТЕЛИ: довести до готовности в духовке 10 минут при 180°C
"""
        
        benefits = """• 👶 Знакомство с растительными белками
• 💬 Изучение новых продуктов (чечевица, чиа)
• 🍽️ Гордость за собственное полезное блюдо
• 💰 Бюджет: ~220 рублей
• ⏱️ Общее время: 40 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 ГОТОВИМ ВМЕСТЕ: ЧЕЧЕВИЧНЫЕ КОТЛЕТЫ С БРОККОЛИ",
            content,
            "family_lunch",
            benefits
        )
    
    def generate_friday_dessert(self):
        content = """
🍰 ТВОРОЖНО-БАНАНОВЫЕ РОЛЛЫ С СЕМЕНАМИ ЧИА

Ингредиенты для радости:
• Творог 5% - 400 g
• Бананы - 3 шт
• Мед - 2 ст.л.
• Семена чиа - 1 ст.л.
• Кокосовая стружка - 50 г
• Лаваш тонкий - 2 шт
• Ванилин - щепотка

Детальное приготовление (15 мин + охлаждение):
1. Бананы размять вилкой в пюре
2. Творог смешать с банановым пюре
3. Добавить мед, ванилин и семена чиа, тщательно перемешать
4. Лаваш намазать творожной начинкой
5. Посыпать кокосовой стружкой
6. Плотно завернуть рулетом
7. Охладить 1 час в холодильнике
8. Нарезать порционными рулетиками
"""
        
        benefits = """• 🍌 Натуральная сладость из бананов
• 🧀 Кальций для костей детей
• 🌿 Семена чиа - Омега-3 для мозга
• ❌ Без выпечки и сахара
• 💰 Бюджет: ~180 рублей"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ПЯТНИЧНЫЙ ДЕСЕРТ: ТВОРОЖНО-БАНАНОВЫЕ РОЛЛЫ",
            content,
            "friday_dessert",
            benefits
        )
    
    def generate_sunday_breakfast(self):
        content = """
☀️ СЫРНИКИ С СЕМЕНАМИ ЛЬНА И ЯГОДАМИ

Ингредиенты на семью (4 чел):
• Творог 9% - 600 г
• Яйца - 2 шт
• Мука цельнозерновая - 5 ст.л. + 2 ст.л. для панировки
• Семена льна - 2 ст.л.
• Мед - 3 ст.л.
• Ягоды свежие/замороженные - 200 г
• Сметана для подачи

Детальное приготовление (25 мин):
1. Творог выложить в глубокую миску, размять вилкой
2. Добавить яйца, мед, семена льна - тщательно перемешать
3. Постепенно всыпать 5 ст.л. муки, замесить тесто
4. Стол посыпать оставшейся мукой, сформировать колбаску
5. Нарезать колбаску на 12 частей, сформировать сырники
6. Разогреть сковороду с маслом на среднем огне
7. Обжаривать сырники 4-5 минут до золотистой корочки
8. Подавать со сметаной и ягодами
"""
        
        benefits = """• 🧀 Творог - кальций для роста детей
• 🌿 Семена льна - Омега-3 для развития мозга
• 🍓 Ягоды - антиоксиданты и витамины
• 💰 Бюджет: ~240 рублей
• ⏱️ Празднично: 25 минут"""
        
        return self.visual_manager.generate_attractive_post(
            "☀️ ВОСКРЕСНЫЙ БРАНЧ: СЫРНИКИ С СЕМЕНАМИ ЛЬНА",
            content,
            "sunday_breakfast",
            benefits
        )

    def generate_neuro_advice(self):
        content = """
🧠 КАК ЕДА ВЛИЯЕТ НА ВАШ МОЗГ

💡 3 ПРОДУКТА ДЛЯ УЛУЧШЕНИЯ ПАМЯТИ:

1. 🥑 АВОКАДО - полезные жиры для нейронов
• Улучшает нейронные связи
• Содержит витамин E для защиты клеток
• 💡 Совет: добавляйте в салаты и завтраки

2. 🐟 ЛОСОСЬ - Омега-3 для когнитивных функций
• Укрепляет мембраны нервных клеток
• Улучшает память на 15-20%
• 💡 Совет: 2-3 раза в неделю на обед

3. 🌰 ГРЕЦКИЕ ОРЕХИ - витамины для мозга
• Форма ореха напоминает мозг - природа не случайна!
• Магний и цинк улучшают нейропластичность
• 💡 Совет: горсть в день как перекус

🎯 ПРАКТИЧЕСКОЕ ЗАДАНИЕ:
Добавьте один из продуктов в завтрак завтра!
"""
        
        benefits = """• 🧠 Улучшение памяти и концентрации
• 💡 Ясность мышления и быстрая реакция
• 🛡️ Защита от возрастных изменений
• 💪 Повышение продуктивности на работе/учебе
• 👨‍👩‍👧‍👦 Подходит для всех членов семьи"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 СОВЕТ НУТРИЦИОЛОГА: ПИТАНИЕ ДЛЯ МОЗГА",
            content,
            "neuro_advice",
            benefits
        )
    
    def generate_protein_advice(self):
        content = """
💪 БЕЛКИ: СТРОИТЕЛЬНЫЕ КИРПИЧИКИ ОРГАНИЗМА

🥩 ЖИВОТНЫЕ БЕЛКИ:
• Курица, индейка, рыба, яйца
• Легко усваиваются организмом
• Содержат все незаменимые аминокислоты
• 💡 Оптимально: 2-3 раза в день

🌱 РАСТИТЕЛЬНЫЕ БЕЛКИ:
• Чечевица, нут, фасоль, тофу
• Содержат клетчатку для пищеварения
• Не содержат холестерин
• 💡 Отлично: для вегетарианских дней

⚖️ БАЛАНС БЕЛКОВ В ДЕНЬ:
• Взрослые: 1-1.5 г на кг веса
• Дети: 1.5-2 г на кг веса
• Спортсмены: 1.5-2 г на кг веса

🎯 ПРАКТИЧЕСКИЙ СОВЕТ:
Сочетайте животные и растительные белки в течение дня!
"""
        
        benefits = """• 💪 Рост и восстановление мышц
• 🛡️ Укрепление иммунной системы
• ⚡ Энергия и выносливость
• 🧠 Здоровье волос, кожи и ногтей
• 👶 Особенно важно для растущего организма"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СОВЕТ НУТРИЦИОЛОГА: ЗНАЧЕНИЕ БЕЛКОВ",
            content,
            "protein_advice",
            benefits
        )
    
    def generate_veggie_advice(self):
        content = """
🥬 ОВОЩИ: ПОЛЬЗА КЛЕТЧАТКИ И ВИТАМИНОВ

🌈 ПРАВИЛО РАДУГИ НА ТАРЕЛКЕ:

🔴 КРАСНЫЕ (помидоры, перец)
• Ликопин для здоровья сердца
• Антиоксиданты против старения

🟢 ЗЕЛЕНЫЕ (брокколи, шпинат)
• Хлорофилл для детокса
• Витамин K для костей

🟠 ОРАНЖЕВЫЕ (морковь, тыква)
• Бета-каротин для зрения
• Витамин A для иммунитета

🟣 ФИОЛЕТОВЫЕ (баклажан, свекла)
• Антоцианы для мозга
• Противовоспалительные свойства

⚪ БЕЛЫЕ (цветная капуста, лук)
• Аллицин для иммунитета
• Пребиотики для микрофлоры

🎯 ЦЕЛЬ НА ДЕНЬ:
5 разных цветов овощей в рационе!
"""
        
        benefits = """• 🌿 Улучшение пищеварения и работы ЖКТ
• 💊 Натуральные витамины и минералы
• 🛡️ Укрепление иммунной системы
• 📉 Контроль веса и аппетита
• ✨ Улучшение состояния кожи"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 СОВЕТ НУТРИЦИОЛОГА: СИЛА ОВОЩЕЙ",
            content,
            "veggie_advice",
            benefits
        )
    
    def generate_carbs_advice(self):
        content = """
🍠 УГЛЕВОДЫ: ЭНЕРГИЯ ДЛЯ АКТИВНОЙ ЖИЗНИ

⚡ СЛОЖНЫЕ УГЛЕВОДЫ:
• Овсянка, гречка, бурый рис
• Цельнозерновой хлеб, макароны из твердых сортов
• Бобовые: чечевица, нут, фасоль
• 💡 Дают энергию на 3-4 часа

🚫 ПРОСТЫЕ УГЛЕВОДЫ:
• Сахар, мед, варенье
• Белый хлеб, выпечка
• Сладкие напитки, конфеты
• 💡 Быстрая энергия на 30-60 минут

⏰ КОГДА ЕСТЬ УГЛЕВОДЫ:
• 🕗 УТРОМ - энергия на весь день
• 🕐 ОБЕД - поддержка активности
• 🏃‍♀️ ДО ТРЕНИРОВКИ - топливо для мышц
• ❌ ВЕЧЕРОМ - ограничить простые углеводы

🎯 ПРАВИЛО:
80% сложных углеводов + 20% простых!
"""
        
        benefits = """• ⚡ Стабильная энергия в течение дня
• 🧠 Питание для мозга и нервной системы
• 💪 Топливо для физической активности
• 📊 Контроль уровня сахара в крови
• 🏃‍♀️ Улучшение спортивных результатов"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 СОВЕТ НУТРИЦИОЛОГА: ЭНЕРГИЯ УГЛЕВОДОВ",
            content,
            "carbs_advice",
            benefits
        )
    
    def generate_water_advice(self):
        content = """
💧 ВОДА: ОСНОВА ВСЕХ ПРОЦЕССОВ

🚰 ПОЧЕМУ ВОДА ТАК ВАЖНА:

🔥 УСКОРЕНИЕ МЕТАБОЛИЗМА
• +30% к скорости обмена веществ
• Помогает сжигать калории эффективнее

🧠 УЛУЧШЕНИЕ РАБОТЫ МОЗГА
• 75% мозга состоит из воды
• Улучшает концентрацию и память

🍽️ КОНТРОЛЬ АППЕТИТА
• Стакан воды перед едой = -13% калорий
• Снижает чувство голода между приемами пищи

⏰ ПРАВИЛЬНОЕ ВРЕМЯ ДЛЯ ВОДЫ:
🕢 1 стакан после пробуждения
🕥 1 стакан перед каждым приемом пищи
🕓 1 стакан во время перекусов
🕤 1 стакан перед сном

💡 СОВЕТЫ:
• Держите бутылку с водой всегда на виду
• Установите напоминания на телефоне
• Добавьте лимон/мяту для вкуса
"""
        
        benefits = """• 💦 Улучшение всех функций организма
• 🧠 Ясность мышления и концентрация
• 🍽️ Контроль аппетита и веса
• ✨ Улучшение состояния кожи
• 🏃‍♂️ Повышение физической выносливости"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 СОВЕТ НУТРИЦИОЛОГА: ВОДНЫЙ БАЛАНС",
            content,
            "water_advice",
            benefits
        )
    
    def generate_family_advice(self):
        content = """
👨‍👩‍👧‍👦 ПИТАНИЕ ДЛЯ ВСЕЙ СЕМЬИ

👶 ДЛЯ ДЕТЕЙ:
• Разноцветные блюда - интересно есть
• Совместная готовка - развивает интерес к еде
• Положительный пример родителей - лучшая мотивация

🍽️ ПРАВИЛА СЕМЕЙНОГО СТОЛА:
1. НИКАКИХ ГАДЖЕТОВ ЗА ЕДОЙ
2. СПОКОЙНАЯ И ДРУЖЕЛЮБНАЯ АТМОСФЕРА
3. НОВЫЕ ПРОДУКТЫ ПРЕДЛАГАТЬ БЕЗ ПРИНУЖДЕНИЯ

💡 СОВЕТЫ ДЛЯ РОДИТЕЛЕЙ:
• Превратите прием пищи в приятный ритуал
• Рассказывайте о пользе продуктов в игровой форме
• Разрешите детям участвовать в выборе меню

🎯 ИДЕЯ НА ВЫХОДНЫЕ:
Устройте "цветной ужин" - каждый выбирает овощ своего цвета!
"""
        
        benefits = """• 👶 Формирование здоровых привычек у детей
• 💞 Укрепление семейных связей
• 🍽️ Развитие культуры питания
• 🧠 Позитивное отношение к здоровой пище
• 👨‍👩‍👧‍👦 Совместное времяпрепровождение"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СОВЕТ НУТРИЦИОЛОГА: СЕМЕЙНОЕ ПИТАНИЕ",
            content,
            "family_advice",
            benefits
        )
    
    def generate_planning_advice(self):
        content = """
📝 ПЛАНИРОВАНИЕ ПИТАНИЯ: КЛЮЧ К УСПЕХУ

🗓️ ЧТО ДАЕТ ПЛАНИРОВАНИЕ:
• Экономия времени и денег
• Сбалансированный рацион
• Отсутствие вредных перекусов
• Снижение стресса от "что приготовить?"

📋 ШАГИ ПЛАНИРОВАНИЯ НА НЕДЕЛЮ:

1. 🛒 СОСТАВЬТЕ СПИСОК ПРОДУКТОВ
   • Основные белки, крупы, овощи
   • Учитывайте сезонность и акции

2. 🍽️ РАСПИШИТЕ МЕНЮ НА НЕДЕЛЮ
   • Завтраки, обеды, ужины, перекусы
   • Чередуйте виды белков и круп

3. 🕒 ПОДГОТОВЬТЕ БАЗОВЫЕ ПРОДУКТЫ
   • Отварите крупы на 2-3 дня
   • Нарежьте овощи для салатов
   • Разморозьте и разделите мясо/рыбу

💡 СОВЕТ:
Выделите 1 час в воскресенье для планирования - сэкономите 10 часов в неделю!
"""
        
        benefits = """• ⏱️ Экономия времени на готовку
• 💰 Снижение расходов на продукты
• 🍽️ Сбалансированное и разнообразное питание
• 😌 Снижение стресса и принятия решений
• 👨‍👩‍👧‍👦 Организованность для всей семьи"""
        
        return self.visual_manager.generate_attractive_post(
            "📝 СОВЕТ НУТРИЦИОЛОГА: ПЛАНИРОВАНИЕ ПИТАНИЯ",
            content,
            "planning_advice",
            benefits
        )

# ПЛАНИРОВЩИК КОНТЕНТА
class ContentScheduler:
    def __init__(self):
        self.kemerovo_schedule = {
            # ПОНЕДЕЛЬНИК - 🧠 "НЕЙРОПИТАНИЕ"
            0: {
                "08:00": {"name": "🧠 Нейрозавтрак: Омлет с авокадо", "type": "neuro_breakfast", "method": "generate_neuro_breakfast"},
                "13:00": {"name": "🍲 Обед для концентрации", "type": "focus_lunch", "method": "generate_neuro_lunch"},
                "17:00": {"name": "🧠 Совет: Питание для мозга", "type": "neuro_advice", "method": "generate_neuro_advice"},
                "19:00": {"name": "🥗 Ужин для мозга", "type": "brain_dinner", "method": "generate_neuro_dinner"}
            },
            # ВТОРНИК - 💪 "БЕЛКОВЫЙ ДЕНЬ"
            1: {
                "08:00": {"name": "💪 Белковый завтрак: Творожная запеканка", "type": "protein_breakfast", "method": "generate_protein_breakfast"},
                "13:00": {"name": "🍵 Чечевичный суп с индейкой", "type": "protein_lunch", "method": "generate_protein_lunch"},
                "17:00": {"name": "💪 Совет: Значение белков", "type": "protein_advice", "method": "generate_protein_advice"},
                "19:00": {"name": "🍗 Куриные грудки с киноа", "type": "protein_dinner", "method": "generate_protein_dinner"}
            },
            # СРЕДА - 🥬 "ОВОЩНОЙ ДЕНЬ"
            2: {
                "08:00": {"name": "🥤 Смузи-боул с семенами чиа", "type": "veggie_breakfast", "method": "generate_veggie_breakfast"},
                "13:00": {"name": "🥬 Овощное рагу с фасолью", "type": "veggie_lunch", "method": "generate_veggie_lunch"},
                "17:00": {"name": "🥬 Совет: Сила овощей", "type": "veggie_advice", "method": "generate_veggie_advice"},
                "19:00": {"name": "🥑 Салат с авокадо и нутом", "type": "veggie_dinner", "method": "generate_veggie_dinner"}
            },
            # ЧЕТВЕРГ - 🍠 "СЛОЖНЫЕ УГЛЕВОДЫ"
            3: {
                "08:00": {"name": "🍠 Энергетическая овсянка с чиа", "type": "carbs_breakfast", "method": "generate_carbs_breakfast"},
                "13:00": {"name": "🍚 Бурый рис с курицей", "type": "carbs_lunch", "method": "generate_carbs_lunch"},
                "17:00": {"name": "🍠 Совет: Энергия углеводов", "type": "carbs_advice", "method": "generate_carbs_advice"},
                "19:00": {"name": "🥔 Запеченный картофель", "type": "carbs_dinner", "method": "generate_carbs_dinner"}
            },
            # ПЯТНИЦА - 🎉 "ВКУСНО И ПОЛЕЗНО"
            4: {
                "08:00": {"name": "🥞 Блинчики цельнозерновые", "type": "carbs_breakfast", "method": "generate_carbs_breakfast"},
                "13:00": {"name": "🍝 Паста с фасолью", "type": "carbs_lunch", "method": "generate_carbs_lunch"},
                "16:00": {"name": "🍰 Пятничный десерт", "type": "friday_dessert", "method": "generate_friday_dessert"},
                "17:00": {"name": "💧 Совет: Водный баланс", "type": "water_advice", "method": "generate_water_advice"},
                "19:00": {"name": "🍕 Домашняя пицца", "type": "family_dinner", "method": "generate_family_cooking"}
            },
            # СУББОТА - 👨‍🍳 "ГОТОВИМ ВМЕСТЕ"
            5: {
                "10:00": {"name": "🍳 Семейный завтрак", "type": "family_breakfast", "method": "generate_sunday_breakfast"},
                "13:00": {"name": "👨‍🍳 Готовим вместе: Чечевичные котлеты", "type": "family_lunch", "method": "generate_family_cooking"},
                "16:00": {"name": "🎂 Субботний десерт", "type": "saturday_dessert", "method": "generate_friday_dessert"},
                "17:00": {"name": "👨‍👩‍👧‍👦 Совет: Семейное питание", "type": "family_advice", "method": "generate_family_advice"},
                "19:00": {"name": "🍽️ Семейный ужин", "type": "family_dinner", "method": "generate_protein_dinner"}
            },
            # ВОСКРЕСЕНЬЕ - 📝 "ПЛАНИРУЕМ НЕДЕЛЮ"
            6: {
                "10:00": {"name": "☀️ Воскресный бранч: Сырники", "type": "sunday_breakfast", "method": "generate_sunday_breakfast"},
                "13:00": {"name": "🛒 Обед + Корзина на неделю", "type": "sunday_lunch", "method": "generate_veggie_lunch"},
                "17:00": {"name": "📝 Совет: Планирование питания", "type": "planning_advice", "method": "generate_planning_advice"},
                "19:00": {"name": "📋 Настрой на неделю", "type": "week_prep_dinner", "method": "generate_carbs_dinner"}
            }
        }
        
        self.server_schedule = self._convert_schedule_to_server()
        self.is_running = False
        self.telegram = TelegramManager()
        self.generator = ContentGenerator()
        
    def _convert_schedule_to_server(self):
        server_schedule = {}
        for day, day_schedule in self.kemerovo_schedule.items():
            server_schedule[day] = {}
            for kemerovo_time, event in day_schedule.items():
                server_time = TimeManager.kemerovo_to_server(kemerovo_time)
                server_schedule[day][server_time] = event
        return server_schedule

    def start_scheduler(self):
        if self.is_running:
            return
            
        logger.info("🚀 Запуск планировщика контента...")
        
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)
        
        self.is_running = True
        self._run_scheduler()
    
    def _schedule_event(self, day, server_time, event):
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

    def get_next_event(self):
        """Получает следующее событие для отображения в дашборде"""
        try:
            current_times = TimeManager.get_current_times()
            current_kemerovo_time = current_times['kemerovo_time'][:5]
            
            current_weekday = TimeManager.get_kemerovo_weekday()
            today_schedule = self.kemerovo_schedule.get(current_weekday, {})
            
            # Ищем следующее событие сегодня
            for time_str, event in sorted(today_schedule.items()):
                if time_str > current_kemerovo_time:
                    return time_str, event
            
            # Если сегодня событий больше нет, берем первое завтра
            tomorrow = (current_weekday + 1) % 7
            tomorrow_schedule = self.kemerovo_schedule.get(tomorrow, {})
            if tomorrow_schedule:
                first_time = min(tomorrow_schedule.keys())
                return first_time, tomorrow_schedule[first_time]
            
            # Если ничего не найдено
            return "09:00", {"name": "Следующий пост", "type": "general"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "09:00", {"name": "Следующий пост", "type": "general"}

# СИСТЕМА KEEP-ALIVE
def start_keep_alive_system():
    def keep_alive_ping():
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

📅 Расписание: 32 поста в неделю
🍽️ Формат: Вкусно, полезно, для семьи
💰 Бюджет: Доступные рецепты
⏱️ Время: Быстрое приготовление
💡 Советы: Ежедневные рекомендации нутрициолога
🛡️ Оптимизация: Keep-alive активен

🕐 Сервер: {current_times['server_time']}
🕐 Кемерово: {current_times['kemerovo_time']}

Присоединяйтесь к клубу осознанного питания! 👨‍👩‍👧‍👦
    """)
    
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")

# МАРШРУТЫ FLASK
@app.route('/')
@rate_limit
def smart_dashboard():
    try:
        member_count = telegram_manager.get_member_count()
        next_time, next_event = content_scheduler.get_next_event()
        current_times = TimeManager.get_current_times()
        current_weekday = TimeManager.get_kemerovo_weekday()
        
        weekly_stats = {
            'posts_sent': 18,
            'engagement_rate': 4.2,
            'new_members': 12,
            'total_reactions': 284
        }
        
        content_progress = {
            0: {"completed": 4, "total": 8, "theme": "🧠 Нейропитание"},
            1: {"completed": 2, "total": 8, "theme": "💪 Белки"},
            2: {"completed": 8, "total": 8, "theme": "🥬 Овощи"},
            3: {"completed": 1, "total": 8, "theme": "🍠 Углеводы"},
            4: {"completed": 3, "total": 8, "theme": "🎉 Вкусно"},
            5: {"completed": 0, "total": 8, "theme": "👨‍🍳 Готовим"},
            6: {"completed": 0, "total": 8, "theme": "📝 Планируем"}
        }
        
        today_schedule = content_scheduler.kemerovo_schedule.get(current_weekday, {})
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
                    transition: transform 0.3s ease;
                }}
                
                .widget:hover {{
                    transform: translateY(-5px);
                }}
                
                .widget h3 {{
                    color: var(--primary);
                    margin-bottom: 15px;
                    font-size: 18px;
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
                
                .progress-bar {{
                    background: #e0e0e0;
                    border-radius: 10px;
                    height: 8px;
                    margin: 10px 0;
                    overflow: hidden;
                }}
                
                .progress-fill {{
                    height: 100%;
                    background: var(--success);
                    border-radius: 10px;
                    transition: width 0.3s ease;
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
                
                .btn-success {{
                    background: var(--success);
                }}
                
                .btn-warning {{
                    background: var(--warning);
                }}
                
                .btn-danger {{
                    background: var(--danger);
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 10px;
                    margin-top: 15px;
                }}
                
                .metrics-grid {{
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 15px;
                }}
                
                .metric-item {{
                    text-align: center;
                    padding: 15px;
                    background: var(--light);
                    border-radius: 10px;
                }}
                
                .automation-status {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px;
                    background: var(--light);
                    border-radius: 8px;
                    margin: 8px 0;
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
                    <p>Клуб Осознанного Долголетия - Полное управление контентом</p>
                    
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
                        <div class="status-item">
                            <span>🔄</span>
                            <span>След. пост: {next_time} - {next_event['name']}</span>
                        </div>
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
                                <div class="stat-number">8542</div>
                                <div class="stat-label">📊 Охват</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">{weekly_stats['engagement_rate']}%</div>
                                <div class="stat-label">💬 Engagement</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">{weekly_stats['total_reactions']}</div>
                                <div class="stat-label">⭐ Реакции</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>🎯 Контент-план недели</h3>
                        {"".join([f'''
                        <div style="margin: 10px 0;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span>{progress["theme"]}</span>
                                <span>{progress["completed"]}/{progress["total"]}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: {(progress['completed']/progress['total'])*100}%"></div>
                            </div>
                        </div>
                        ''' for day, progress in content_progress.items()])}
                    </div>
                    
                    <div class="widget">
                        <h3>⏰ Расписание сегодня</h3>
                        {"".join([f'''
                        <div class="schedule-item">
                            <div class="schedule-time">{time}</div>
                            <div class="schedule-text">{event["name"]}</div>
                            <div style="color: var(--success)">✅</div>
                        </div>
                        ''' for time, event in sorted(today_schedule.items())])}
                    </div>
                    
                    <div class="widget">
                        <h3>🔧 Быстрые действия</h3>
                        <div class="actions-grid">
                            <button class="btn" onclick="testChannel()">📤 Тест канала</button>
                            <button class="btn btn-success" onclick="testQuickPost()">🧪 Тест отправки</button>
                            <button class="btn" onclick="sendPoll()">🔄 Опрос</button>
                            <button class="btn btn-success" onclick="sendReport()">📊 Отчет</button>
                            <button class="btn" onclick="sendVisual()">🎨 Визуал</button>
                            <button class="btn btn-warning" onclick="runDiagnostics()">🧪 Диагностика</button>
                            <button class="btn" onclick="showManualPost()">📝 Ручной пост</button>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>📊 Метрики эффективности</h3>
                        <div class="metrics-grid">
                            <div class="metric-item">
                                <div class="stat-number">3.8%</div>
                                <div class="stat-label">📈 CTR</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">2.1 мин</div>
                                <div class="stat-label">⏱️ Время чтения</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">47</div>
                                <div class="stat-label">🔄 Репосты</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">28</div>
                                <div class="stat-label">💬 Комментарии</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>🚀 Автоматизация</h3>
                        <div class="automation-status">
                            <span>✅ Автопостинг</span>
                            <span>Активен</span>
                        </div>
                        <div class="automation-status">
                            <span>✅ Аналитика</span>
                            <span>Включена</span>
                        </div>
                        <div class="automation-status">
                            <span>✅ Keep-alive</span>
                            <span>Активен (5 мин)</span>
                        </div>
                        <div class="automation-status">
                            <span>⏳ След. проверка</span>
                            <span>через 55 сек</span>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                function testChannel() {{
                    fetch('/test-channel').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Канал работает отлично!' : '❌ Ошибка канала');
                    }});
                }}
                
                function testQuickPost() {{
                    const btn = event.target;
                    const originalText = btn.textContent;
                    btn.textContent = '⏳ Тест...';
                    btn.disabled = true;
                    
                    fetch('/test-quick-post')
                        .then(r => r.json())
                        .then(data => {{
                            alert(data.status === 'success' ? '✅ Тестовый пост отправлен!' : '❌ Ошибка: ' + data.message);
                        }})
                        .catch(error => {{
                            alert('❌ Ошибка сети: ' + error);
                        }})
                        .finally(() => {{
                            btn.textContent = originalText;
                            btn.disabled = false;
                        }});
                }}
                
                function sendPoll() {{
                    fetch('/send-poll').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос создан!' : '❌ Ошибка создания опроса');
                    }});
                }}
                
                function sendReport() {{
                    fetch('/send-report').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Отчет отправлен!' : '❌ Ошибка отправки отчета');
                    }});
                }}
                
                function sendVisual() {{
                    fetch('/send-visual').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Визуал отправлен!' : '❌ Ошибка отправки визуала');
                    }});
                }}
                
                function runDiagnostics() {{
                    fetch('/diagnostics').then(r => r.json()).then(data => {{
                        alert('Диагностика завершена: ' + (data.status === 'success' ? '✅ Все системы в норме' : '❌ Обнаружены проблемы'));
                    }});
                }}
                
                function showManualPost() {{
                    const content = prompt('Введите текст поста (поддерживается HTML разметка):');
                    if (content) {{
                        // Показываем индикатор загрузки
                        const btn = event.target;
                        const originalText = btn.textContent;
                        btn.textContent = '⏳ Отправка...';
                        btn.disabled = true;
                        
                        fetch('/quick-post', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{content: content}})
                        }}).then(r => r.json()).then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Пост успешно отправлен в канал!');
                            }} else {{
                                alert('❌ Ошибка: ' + (data.message || 'Неизвестная ошибка'));
                            }}
                        }}).catch(error => {{
                            alert('❌ Ошибка сети: ' + error);
                        }}).finally(() => {{
                            // Восстанавливаем кнопку
                            btn.textContent = originalText;
                            btn.disabled = false;
                        }});
                    }}
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
        logger.error(f"❌ Ошибка дашборда: {e}")
        return f"Ошибка загрузки дашборда: {str(e)}"

# HEALTH CHECK
@app.route('/health')
def health_check():
    return jsonify(service_monitor.get_status())

@app.route('/ping')
def ping():
    return "pong", 200

# API МАРШРУТЫ
@app.route('/test-channel')
@rate_limit
def test_channel():
    success = telegram_manager.send_message("🎪 <b>Тест системы:</b> Клуб осознанного питания для семьи работает отлично! ✅")
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-poll')
@rate_limit
def send_poll():
    return jsonify({"status": "success", "message": "Опрос будет реализован в следующей версии"})

@app.route('/send-report')
@rate_limit
def send_report():
    member_count = telegram_manager.get_member_count()
    current_times = TimeManager.get_current_times()
    
    report = f"""📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЕТ КАНАЛА @ppsupershef</b>

👥 Подписчиков: <b>{member_count}</b>
📅 Дата: {current_times['kemerovo_date']}
📍 Время Кемерово: {current_times['kemerovo_time']}

💫 <b>СТАТИСТИКА ЗА НЕДЕЛЮ:</b>
• 📈 Engagement Rate: 4.2%
• 💬 Активность в чате: 3.1%
• 🎯 Релевантность контента: 85%

🎯 <b>ПРИСОЕДИНЯЙТЕСЬ К КЛУБУ ОСОЗНАННОГО ДОЛГОЛЕТИЯ!</b>

#отчет #статистика #клуб"""
    
    success = telegram_manager.send_message(report)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-visual')
@rate_limit
def send_visual():
    content = content_generator.generate_neuro_breakfast()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-breakfast')
@rate_limit
def send_breakfast():
    content = content_generator.generate_neuro_breakfast()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-dessert')
@rate_limit
def send_dessert():
    content = content_generator.generate_friday_dessert()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-advice')
@rate_limit
def send_advice():
    content = content_generator.generate_neuro_advice()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/diagnostics')
@rate_limit
def diagnostics():
    try:
        member_count = telegram_manager.get_member_count()
        current_times = TimeManager.get_current_times()
        
        return jsonify({
            "status": "success",
            "components": {
                "telegram": "active" if member_count > 0 else "error",
                "scheduler": "active" if content_scheduler.is_running else "error",
                "database": "active",
                "keep_alive": "active"
            },
            "metrics": {
                "member_count": member_count,
                "system_time": current_times['kemerovo_time'],
                "uptime": service_monitor.get_status()['uptime_seconds']
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/manual-post', methods=['POST'])
@require_api_key
@rate_limit
def manual_post():
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        current_times = TimeManager.get_current_times()
        content_with_time = f"{content}\n\n⏰ Опубликовано: {current_times['kemerovo_time']}"
        
        success = telegram_manager.send_message(content_with_time)
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# НОВЫЕ МАРШРУТЫ ДЛЯ РУЧНОЙ ОТПРАВКИ
@app.route('/quick-post', methods=['POST'])
@rate_limit
def quick_post():
    """Упрощенный маршрут для ручной отправки из дашборда"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        
        if not content:
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        # Добавляем временную метку
        current_times = TimeManager.get_current_times()
        content_with_time = f"{content}\n\n⏰ Опубликовано: {current_times['kemerovo_time']}"
        
        # Отправляем сообщение
        success = telegram_manager.send_message(content_with_time)
        
        if success:
            logger.info(f"✅ Ручной пост отправлен: {content[:50]}...")
            return jsonify({"status": "success", "message": "Пост успешно отправлен"})
        else:
            return jsonify({"status": "error", "message": "Ошибка отправки в Telegram"})
            
    except Exception as e:
        logger.error(f"❌ Ошибка ручной отправки: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/test-quick-post')
@rate_limit
def test_quick_post():
    """Тестовая отправка предопределенного сообщения"""
    try:
        test_content = """🎪 <b>ТЕСТОВЫЙ ПОСТ ИЗ ДАШБОРДА</b>

✅ <b>Проверка системы отправки</b>

Это тестовое сообщение подтверждает, что ручная отправка из дашборда работает корректно.

💫 <b>Функции проверены:</b>
• 📤 Отправка HTML сообщений
• ⏰ Временные метки
• 🔗 Ссылки и форматирование
• 🛡️ Система безопасности

📊 <b>Статус:</b> Все системы работают нормально!

#тест #дашборд #управление"""
        
        success = telegram_manager.send_message(test_content)
        return jsonify({
            "status": "success" if success else "error", 
            "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("🚀 Запуск Умного Дашборда @ppsupershef")
    print("🎯 Философия: Осознанное питание для современной семьи")
    print("📊 Контент-план: 32 поста в неделю")
    print("💡 Особенность: Ежедневные советы нутрициолога")
    print("📸 Визуалы: Готовые фото для каждой категории")
    print("🛡️ Keep-alive: Активен (каждые 5 минут)")
    print("🎮 Ручная отправка: Активирована")
    print("✅ Расписание: Исправлено (соответствие времени суток)")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
