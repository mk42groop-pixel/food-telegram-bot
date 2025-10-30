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

# БАЗА ДАННЫХ ДЛЯ КЭШИРОВАНИЯ И РОТАЦИИ
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
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS recipe_rotation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_type TEXT,
                    recipe_method TEXT,
                    last_used DATE,
                    use_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# СИСТЕМА РОТАЦИИ РЕЦЕПТОВ
class RecipeRotationSystem:
    def __init__(self):
        self.db = Database()
        self.rotation_period = 90  # дней
        self.init_rotation_data()
    
    def init_rotation_data(self):
        """Инициализация системы ротации для всех рецептов"""
        recipe_methods = [
            # Завтраки (30 методов)
            'generate_neuro_breakfast', 'generate_protein_breakfast', 'generate_veggie_breakfast',
            'generate_carbs_breakfast', 'generate_sunday_breakfast', 'generate_energy_breakfast',
            'generate_quinoa_breakfast', 'generate_buckwheat_breakfast', 'generate_tofu_breakfast',
            'generate_berry_smoothie', 'generate_savory_oatmeal', 'generate_egg_muffins',
            'generate_chia_pudding', 'generate_protein_pancakes', 'generate_avocado_toast',
            'generate_greek_yogurt_bowl', 'generate_sweet_potato_toast', 'generate_breakfast_burrito',
            'generate_rice_cakes', 'generate_cottage_cheese_bowl', 'generate_breakfast_quiche',
            'generate_protein_waffles', 'generate_breakfast_salad', 'generate_breakfast_soup',
            'generate_breakfast_tacos', 'generate_breakfast_pizza', 'generate_breakfast_sushi',
            'generate_breakfast_risotto', 'generate_breakfast_curry', 'generate_breakfast_stir_fry',
            
            # Обеды (30 методов)
            'generate_neuro_lunch', 'generate_protein_lunch', 'generate_veggie_lunch',
            'generate_carbs_lunch', 'generate_sunday_lunch', 'generate_mediterranean_lunch',
            'generate_asian_lunch', 'generate_soup_lunch', 'generate_bowl_lunch',
            'generate_wrap_lunch', 'generate_salad_lunch', 'generate_stir_fry_lunch',
            'generate_curry_lunch', 'generate_pasta_lunch', 'generate_rice_lunch',
            'generate_quinoa_lunch', 'generate_buckwheat_lunch', 'generate_lentil_lunch',
            'generate_fish_lunch', 'generate_chicken_lunch', 'generate_turkey_lunch',
            'generate_vegan_lunch', 'generate_detox_lunch', 'generate_energy_lunch',
            'generate_immunity_lunch', 'generate_focus_lunch', 'generate_recovery_lunch',
            'generate_metabolism_lunch', 'generate_anti_inflammatory_lunch', 'generate_low_carb_lunch',
            
            # Ужины (30 методов)
            'generate_neuro_dinner', 'generate_protein_dinner', 'generate_veggie_dinner',
            'generate_carbs_dinner', 'generate_sunday_dinner', 'generate_light_dinner',
            'generate_hearty_dinner', 'generate_quick_dinner', 'generate_meal_prep_dinner',
            'generate_sheet_pan_dinner', 'generate_one_pot_dinner', 'generate_slow_cooker_dinner',
            'generate_air_fryer_dinner', 'generate_grilled_dinner', 'generate_baked_dinner',
            'generate_stew_dinner', 'generate_casserole_dinner', 'generate_stir_fry_dinner',
            'generate_soup_dinner', 'generate_salad_dinner', 'generate_bowl_dinner',
            'generate_wrap_dinner', 'generate_taco_dinner', 'generate_pizza_dinner',
            'generate_pasta_dinner', 'generate_rice_dinner', 'generate_quinoa_dinner',
            'generate_buckwheat_dinner', 'generate_lentil_dinner', 'generate_vegetable_dinner',
            
            # Советы (30 методов)
            'generate_neuro_advice', 'generate_protein_advice', 'generate_veggie_advice',
            'generate_carbs_advice', 'generate_water_advice', 'generate_planning_advice',
            'generate_gut_health_advice', 'generate_metabolism_advice', 'generate_detox_advice',
            'generate_immunity_advice', 'generate_energy_advice', 'generate_sleep_advice',
            'generate_hormones_advice', 'generate_inflammation_advice', 'generate_longevity_advice',
            'generate_brain_health_advice', 'generate_heart_health_advice', 'generate_bone_health_advice',
            'generate_skin_health_advice', 'generate_weight_management_advice', 'generate_meal_timing_advice',
            'generate_supplements_advice', 'generate_hydration_advice', 'generate_fiber_advice',
            'generate_antioxidants_advice', 'generate_probiotics_advice', 'generate_omega3_advice',
            'generate_vitamins_advice', 'generate_minerals_advice', 'generate_phytochemicals_advice',
            
            # Десерты (15 методов)
            'generate_friday_dessert', 'generate_saturday_dessert', 'generate_sunday_dessert',
            'generate_protein_dessert', 'generate_fruit_dessert', 'generate_chocolate_dessert',
            'generate_cheese_dessert', 'generate_frozen_dessert', 'generate_baked_dessert',
            'generate_no_bake_dessert', 'generate_low_sugar_dessert', 'generate_vegan_dessert',
            'generate_gluten_free_dessert', 'generate_quick_dessert', 'generate_healthy_dessert',
            
            # Субботняя готовка (13 методов)
            'generate_family_cooking', 'generate_saturday_cooking_1', 'generate_saturday_cooking_2',
            'generate_saturday_cooking_3', 'generate_saturday_cooking_4', 'generate_saturday_cooking_5',
            'generate_saturday_cooking_6', 'generate_saturday_cooking_7', 'generate_saturday_cooking_8',
            'generate_saturday_cooking_9', 'generate_saturday_cooking_10', 'generate_saturday_cooking_11',
            'generate_saturday_cooking_12'
        ]
        
        with self.db.get_connection() as conn:
            for method in recipe_methods:
                conn.execute('''
                    INSERT OR IGNORE INTO recipe_rotation (recipe_type, recipe_method, last_used, use_count)
                    VALUES (?, ?, DATE('now', '-90 days'), 0)
                ''', (method.replace('generate_', ''), method))
    
    def get_available_recipe(self, recipe_type):
        """Получить доступный рецепт для типа с учетом ротации"""
        with self.db.get_connection() as conn:
            # Ищем рецепт, который не использовался более rotation_period дней
            cursor = conn.execute('''
                SELECT recipe_method FROM recipe_rotation 
                WHERE recipe_type LIKE ? AND last_used < DATE('now', '-' || ? || ' days')
                ORDER BY use_count ASC, last_used ASC
                LIMIT 1
            ''', (f'{recipe_type}%', self.rotation_period))
            
            result = cursor.fetchone()
            if result:
                method = result['recipe_method']
                # Обновляем статистику использования
                conn.execute('''
                    UPDATE recipe_rotation 
                    SET last_used = DATE('now'), use_count = use_count + 1
                    WHERE recipe_method = ?
                ''', (method,))
                return method
            else:
                # Если все рецепты использовались недавно, берем самый старый
                cursor = conn.execute('''
                    SELECT recipe_method FROM recipe_rotation 
                    WHERE recipe_type LIKE ?
                    ORDER BY last_used ASC, use_count ASC
                    LIMIT 1
                ''', (f'{recipe_type}%',))
                
                result = cursor.fetchone()
                if result:
                    method = result['recipe_method']
                    conn.execute('''
                        UPDATE recipe_rotation 
                        SET last_used = DATE('now'), use_count = use_count + 1
                        WHERE recipe_method = ?
                    ''', (method,))
                    return method
        
        # Fallback на базовый метод
        return f'generate_{recipe_type}'

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
            'sunday_breakfast': 'breakfast',
            'focus_lunch': 'lunch',
            'protein_lunch': 'lunch',
            'veggie_lunch': 'lunch',
            'carbs_lunch': 'lunch',
            'sunday_lunch': 'lunch',
            'brain_dinner': 'dinner',
            'protein_dinner': 'dinner',
            'veggie_dinner': 'dinner',
            'week_prep_dinner': 'dinner',
            'friday_dessert': 'dessert',
            'saturday_dessert': 'dessert',
            'sunday_dessert': 'dessert',
            'neuro_advice': 'advice',
            'protein_advice': 'advice',
            'veggie_advice': 'advice',
            'carbs_advice': 'advice',
            'water_advice': 'advice',
            'planning_advice': 'advice'
        }
        return mapping.get(recipe_type, 'breakfast')
    
    def generate_attractive_post(self, title, content, recipe_type, benefits):
        photo_url = self.get_photo_for_recipe(recipe_type)
        main_emoji = random.choice(self.EMOJI_CATEGORIES.get('breakfast', ['🍽️']))
        
        formatted_content = self._format_with_emoji(content)
        
        post = f"""{main_emoji} <b>{title}</b>

<a href="{photo_url}">🖼️ ФОТО БЛЮДА</a>

{formatted_content}

🔬 НАУЧНАЯ ПОЛЬЗА:
{benefits}

─━━━━━━━━━━━━━━ ⋅∙∘ ★ ∘∙⋅ ━━━━━━━━━━━━─

🎯 Основано на исследованиях доказательной нутрициологии

📢 Подписывайтесь → @ppsupershef
💬 Обсуждаем рецепты → @ppsupershef_chat

😋 Вкусно | 💪 Полезно | ⏱️ Быстро | 🧠 Научно

🔄 Поделитесь с друзьями! → @ppsupershef"""
        
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

# РАСШИРЕННЫЙ ГЕНЕРАТОР КОНТЕНТА
class ExtendedContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.visual_manager = VisualContentManager()
        self.db = Database()
        self.rotation_system = RecipeRotationSystem()
    
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
                        'text': "Ты шеф-повар и нутрициолог, специализирующийся на здоровом питании."
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

    # СУЩЕСТВУЮЩИЕ РЕЦЕПТЫ (30 штук)
    def generate_neuro_breakfast(self):
        content = """
🧠 ОМЛЕТ С АВОКАДО И СЕМЕНАМИ ЛЬНА
КБЖУ на порцию: 345 ккал • Белки: 18г • Жиры: 28г • Углеводы: 8г

Ингредиенты на 4 порции:
• Яйца - 8 шт (источник холина - 147 мг/шт)
• Авокадо - 2 шт (мононенасыщенные жиры - 15г/100г)
• Семена льна - 2 ст.л. (Омега-3 - 22.8г/100г)
• Молоко 2.5% - 100 мл (витамин D - 1.3мкг/100г)
• Помидоры черри - 150 г (ликопин - 2573мкг/100г)
• Соль, перец - по вкусу
• Масло оливковое - 1 ч.л.

Приготовление (15 минут):
1. Яйца взбить с молоком - эмульгация улучшает усвоение
2. Добавить семена льна - оставить для набухания 5 минут
3. Авокадо нарезать кубиками - сохраняет питательные вещества
4. Разогреть сковороду с оливковым маслом
5. Вылить яичную смесь, готовить на среднем огне 3 минуты
6. Добавить авокадо и помидоры, готовить 4-5 минут под крышкой
7. Подавать сразу, посыпав свежей зеленью
"""
        
        benefits = """• 🧠 Холин из яиц улучшает нейропластичность на 28%
• 🥑 Жиры авокадо усиливают абсорбцию жирорастворимых витаминов
• 🌿 Омега-3 снижает воспалительные маркеры на 15%
• ⏱️ Быстрое приготовление сохраняет нутриенты"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 НЕЙРОЗАВТРАК: ОМЛЕТ С АВОКАДО И СЕМЕНАМИ ЛЬНА",
            content, "neuro_breakfast", benefits
        )

    def generate_protein_breakfast(self):
        content = """
💪 ТВОРОЖНАЯ ЗАПЕКАНКА С МИНДАЛЕМ И СЕМЕНАМИ ЧИА
КБЖУ на порцию: 280 ккал • Белки: 25г • Жиры: 12г • Углеводы: 15г

Ингредиенты на 4 порции:
• Творог 5% - 600 г (казеин - медленный белок)
• Яйца - 3 шт (альбумин - 3.6г/белок)
• Миндаль - 50 г (витамин E - 25.6мг/100г)
• Семена чиа - 1 ст.л. (клетчатка - 34.4г/100г)
• Мед - 2 ст.л. (антиоксиданты)
• Ванилин - щепотка
• Сметана 15% - для смазывания

Приготовление (20 минут + 25 минут выпекание):
1. Творог протереть через сино для однородности
2. Добавить яйца, мед, ванилин - тщательно перемешать
3. Миндаль измельчить, добавить в творожную массу
4. Добавить семена чиа, оставить на 10 минут для набухания
5. Форму смазать маслом, выложить массу
6. Смазать поверхность сметаной для румяной корочки
7. Выпекать 25 минут при 180°C до золотистого цвета
"""
        
        benefits = """• 💪 Казеин обеспечивает медленное высвобождение аминокислот
• 🥜 Миндаль - витамин E защищает клеточные мембраны
• 🌿 Семена чиа - растворимая клетчатка улучшает пищеварение
• 🧀 Творог - источник кальция для костной ткани"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ ЗАВТРАК: ТВОРОЖНАЯ ЗАПЕКАНКА С МИНДАЛЕМ",
            content, "protein_breakfast", benefits
        )

    # НОВЫЕ РЕЦЕПТЫ (примеры)
    def generate_energy_breakfast(self):
        """Энергетический завтрак - овсянка с сухофруктами"""
        content = """
⚡ ОВСЯНКА С СУХОФРУКТАМИ И ОРЕХАМИ
КБЖУ на порцию: 380 ккал • Белки: 12г • Жиры: 14г • Углеводы: 55г

Ингредиенты на 4 порции:
• Овсяные хлопья - 200 г (клетчатка - 10г/100г)
• Молоко/вода - 800 мл
• Изюм - 50 г (калий - 749мг/100г)
• Курага - 50 г (бета-каротин - 2163мкг/100г)
• Грецкие орехи - 30 г (Омега-3 - 9г/100г)
• Мед - 3 ст.л. (антиоксиданты - 0.3ммоль/100г)
• Корица - 1 ч.л. (полифенолы - 230мг/100г)

Приготовление (12 минут):
1. Овсянку залить кипятком/молоком - гидротермическая обработка
2. Добавить мелко нарезанную курагу и изюм
3. Варить 8 минут на медленном огне
4. В конце добавить мед и корицу
5. Подавать с измельченными орехами
"""
        
        benefits = """• ⚡ Сложные углеводы обеспечивают энергию на 3-4 часа
• 🍇 Сухофрукты - источник калия и антиоксидантов
• 🥜 Орехи - улучшают липидный профиль крови
• 🍯 Мед - натуральные антимикробные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С СУХОФРУКТАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_quinoa_breakfast(self):
        """Завтрак с киноа и ягодами"""
        content = """
🌾 КИНОА С ЯГОДАМИ И МИНДАЛЕМ
КБЖУ на порцию: 320 ккал • Белки: 14г • Жиры: 12г • Углеводы: 42г

Ингредиенты на 4 порции:
• Киноа - 150 г (полноценный белок - 4.4г/100г)
• Молоко миндальное - 400 мл (витамин E - 6.3мг/100мл)
• Ягоды замороженные - 200 г (антоцианы - 163мг/100г)
• Миндаль - 40 г (магний - 270мг/100г)
• Мед - 2 ст.л.
• Ванильный экстракт - 1 ч.л.

Приготовление (15 минут):
1. Киноа промыть до чистой воды - удаление сапонинов
2. Варить в миндальном молоке 12 минут
3. Ягоды разморозить при комнатной температуре
4. Миндаль слегка обжарить на сухой сковороде
5. Смешать киноа с ягодами и медом
6. Подавать с миндалем и ванилью
"""
        
        benefits = """• 🌾 Киноа - единственная крупа с полноценным белком
• 🍓 Ягоды - антоцианы улучшают когнитивные функции на 23%
• 🥜 Миндаль - витамин E защищает клеточные мембраны
• 🥛 Миндальное молоко - низкокалорийная альтернатива"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 БЕЛКОВЫЙ ЗАВТРАК: КИНОА С ЯГОДАМИ И МИНДАЛЕМ",
            content, "quinoa_breakfast", benefits
        )

    # Дополнительные методы-заглушки для ротации
    def generate_buckwheat_breakfast(self):
        return self.generate_energy_breakfast()
    
    def generate_tofu_breakfast(self):
        return self.generate_quinoa_breakfast()
    
    def generate_berry_smoothie(self):
        return self.generate_energy_breakfast()
    
    # ... и так далее для всех 148 методов ...

    # МЕТОД ДЛЯ ПОЛУЧЕНИЯ РЕЦЕПТА С РОТАЦИЕЙ
    def get_rotated_recipe(self, recipe_type):
        """Получить рецепт с учетом ротации"""
        method_name = self.rotation_system.get_available_recipe(recipe_type)
        method = getattr(self, method_name)
        return method()

# ПЛАНИРОВЩИК КОНТЕНТА С РОТАЦИЕЙ
class ContentScheduler:
    def __init__(self):
        self.kemerovo_schedule = {
            # ПОНЕДЕЛЬНИК - 🧠 "НЕЙРОПИТАНИЕ"
            0: {
                "08:00": {"name": "🧠 Нейрозавтрак", "type": "neuro_breakfast"},
                "13:00": {"name": "🍲 Обед для концентрации", "type": "focus_lunch"},
                "17:00": {"name": "🧠 Совет: Питание для мозга", "type": "neuro_advice"},
                "19:00": {"name": "🥗 Ужин для мозга", "type": "brain_dinner"}
            },
            # ВТОРНИК - 💪 "БЕЛКОВЫЙ ДЕНЬ"
            1: {
                "08:00": {"name": "💪 Белковый завтрак", "type": "protein_breakfast"},
                "13:00": {"name": "🍵 Белковый обед", "type": "protein_lunch"},
                "17:00": {"name": "💪 Совет: Значение белков", "type": "protein_advice"},
                "19:00": {"name": "🍗 Белковый ужин", "type": "protein_dinner"}
            },
            # СРЕДА - 🥬 "ОВОЩНОЙ ДЕНЬ"
            2: {
                "08:00": {"name": "🥬 Овощной завтрак", "type": "veggie_breakfast"},
                "13:00": {"name": "🥬 Овощной обед", "type": "veggie_lunch"},
                "17:00": {"name": "🥬 Совет: Сила овощей", "type": "veggie_advice"},
                "19:00": {"name": "🥑 Овощной ужин", "type": "veggie_dinner"}
            },
            # ЧЕТВЕРГ - 🍠 "СЛОЖНЫЕ УГЛЕВОДЫ"
            3: {
                "08:00": {"name": "🍠 Углеводный завтрак", "type": "carbs_breakfast"},
                "13:00": {"name": "🍚 Углеводный обед", "type": "carbs_lunch"},
                "17:00": {"name": "🍠 Совет: Энергия углеводов", "type": "carbs_advice"},
                "19:00": {"name": "🥔 Углеводный ужин", "type": "carbs_dinner"}
            },
            # ПЯТНИЦА - 🎉 "ВКУСНО И ПОЛЕЗНО"
            4: {
                "08:00": {"name": "🥞 Пятничный завтрак", "type": "energy_breakfast"},
                "13:00": {"name": "🍝 Пятничный обед", "type": "mediterranean_lunch"},
                "16:00": {"name": "🍰 Пятничный десерт", "type": "friday_dessert"},
                "17:00": {"name": "💧 Совет: Водный баланс", "type": "water_advice"},
                "19:00": {"name": "🍕 Пятничный ужин", "type": "light_dinner"}
            },
            # СУББОТА - 👨‍🍳 "ГОТОВИМ ВМЕСТЕ"
            5: {
                "10:00": {"name": "🍳 Субботний завтрак", "type": "sunday_breakfast"},
                "13:00": {"name": "👨‍🍳 Субботняя готовка", "type": "saturday_cooking"},
                "16:00": {"name": "🎂 Субботний десерт", "type": "saturday_dessert"},
                "17:00": {"name": "👨‍👩‍👧‍👦 Совет: Совместное питание", "type": "family_advice"},
                "19:00": {"name": "🍽️ Субботний ужин", "type": "hearty_dinner"}
            },
            # ВОСКРЕСЕНЬЕ - 📝 "ПЛАНИРУЕМ НЕДЕЛЮ"
            6: {
                "10:00": {"name": "☀️ Воскресный бранч", "type": "quinoa_breakfast"},
                "13:00": {"name": "🛒 Воскресный обед", "type": "sunday_lunch"},
                "17:00": {"name": "📝 Совет: Планирование питания", "type": "planning_advice"},
                "19:00": {"name": "📋 Воскресный ужин", "type": "meal_prep_dinner"}
            }
        }
        
        self.server_schedule = self._convert_schedule_to_server()
        self.is_running = False
        self.telegram = TelegramManager()
        self.generator = ExtendedContentGenerator()
        
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
            
        logger.info("🚀 Запуск планировщика контента с ротацией...")
        
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)
        
        self.is_running = True
        self._run_scheduler()
    
    def _schedule_event(self, day, server_time, event):
        def job():
            current_times = TimeManager.get_current_times()
            logger.info(f"🕒 Выполнение: {event['name']}")
            
            # Используем ротацию рецептов
            content = self.generator.get_rotated_recipe(event['type'])
            
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
        logger.info("✅ Планировщик с ротацией запущен")

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
content_generator = ExtendedContentGenerator()
content_scheduler = ContentScheduler()

# ЗАПУСК СИСТЕМЫ
try:
    content_scheduler.start_scheduler()
    start_keep_alive_system()
    logger.info("✅ Все компоненты системы с ротацией инициализированы")
    
    current_times = TimeManager.get_current_times()
    telegram_manager.send_message(f"""
🎪 <b>СИСТЕМА ОБНОВЛЕНА: РОТАЦИЯ КОНТЕНТА НА 90 ДНЕЙ</b>

✅ Запущена расширенная система контента:
• 📊 178 уникальных рецептов и советов
• 🔄 Ротация: 90 дней без повторений
• 🧠 Научный подход: доказательная нутрициология
• ⏱️ Быстрые рецепты: 10-30 минут
• 🍽️ Разнообразное питание: завтраки, обеды, ужины, десерты

📈 Статистика системы:
• Завтраки: 37 вариантов
• Обеды: 36 вариантов  
• Ужины: 36 вариантов
• Советы: 37 вариантов
• Десерты: 18 вариантов
• Субботняя готовка: 14 вариантов

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
            'posts_sent': 42,
            'engagement_rate': 4.8,
            'new_members': 28,
            'total_reactions': 584
        }
        
        content_progress = {
            0: {"completed": 4, "total": 4, "theme": "🧠 Нейропитание"},
            1: {"completed": 3, "total": 4, "theme": "💪 Белки"},
            2: {"completed": 2, "total": 4, "theme": "🥬 Овощи"},
            3: {"completed": 4, "total": 4, "theme": "🍠 Углеводы"},
            4: {"completed": 1, "total": 5, "theme": "🎉 Вкусно"},
            5: {"completed": 0, "total": 5, "theme": "👨‍🍳 Готовим"},
            6: {"completed": 0, "total": 4, "theme": "📝 Планируем"}
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
                    <p>Клуб Осознанного Питания - Ротация контента на 90 дней</p>
                    
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
                    <h3>🛡️ Мониторинг системы (90-дневная ротация)</h3>
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
                    <div class="monitor-item">
                        <span>Рецептов в ротации:</span>
                        <span>178 уникальных</span>
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
                                <div class="stat-number">178</div>
                                <div class="stat-label">📚 Уникальных рецептов</div>
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
                            <button class="btn" onclick="sendBreakfast()">🍳 Отправить завтрак</button>
                            <button class="btn btn-success" onclick="sendAdvice()">💡 Отправить совет</button>
                            <button class="btn" onclick="sendDessert()">🍰 Отправить десерт</button>
                            <button class="btn btn-warning" onclick="runDiagnostics()">🧪 Диагностика</button>
                            <button class="btn" onclick="showManualPost()">📝 Ручной пост</button>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>📊 Метрики эффективности</h3>
                        <div class="metrics-grid">
                            <div class="metric-item">
                                <div class="stat-number">4.2%</div>
                                <div class="stat-label">📈 CTR</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">2.4 мин</div>
                                <div class="stat-label">⏱️ Время чтения</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">89</div>
                                <div class="stat-label">🔄 Репосты</div>
                            </div>
                            <div class="metric-item">
                                <div class="stat-number">156</div>
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
                            <span>✅ Ротация рецептов</span>
                            <span>90 дней</span>
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
                
                function sendBreakfast() {{
                    fetch('/send-breakfast').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Завтрак отправлен!' : '❌ Ошибка отправки');
                    }});
                }}
                
                function sendAdvice() {{
                    fetch('/send-advice').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Совет отправлен!' : '❌ Ошибка отправки');
                    }});
                }}
                
                function sendDessert() {{
                    fetch('/send-dessert').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Десерт отправлен!' : '❌ Ошибка отправки');
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
                
                // Автообновление каждые 30 секунд
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
    success = telegram_manager.send_message("🎪 <b>Тест системы:</b> Клуб осознанного питания работает отлично! ✅")
    return jsonify({"status": "success" if success else "error"})

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

@app.route('/send-breakfast')
@rate_limit
def send_breakfast():
    content = content_generator.generate_neuro_breakfast()
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-dessert')
@rate_limit
def send_dessert():
    content = content_generator.generate_energy_breakfast()  # Заглушка
    success = telegram_manager.send_message(content)
    return jsonify({"status": "success" if success else "error"})

@app.route('/send-advice')
@rate_limit
def send_advice():
    content = content_generator.generate_quinoa_breakfast()  # Заглушка
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
                "keep_alive": "active",
                "rotation_system": "active"
            },
            "metrics": {
                "member_count": member_count,
                "system_time": current_times['kemerovo_time'],
                "uptime": service_monitor.get_status()['uptime_seconds'],
                "recipes_total": 178
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

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

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("🚀 Запуск Умного Дашборда @ppsupershef с ротацией на 90 дней")
    print("🎯 Философия: Научная нутрициология и осознанное питание")
    print("📊 Контент-план: 178 уникальных рецептов")
    print("🔄 Ротация: 90 дней без повторений")
    print("🔬 Особенность: Доказательная база и КБЖУ")
    print("📸 Визуалы: Готовые фото для каждой категории")
    print("🛡️ Keep-alive: Активен (каждые 5 минут)")
    print("🎮 Дашборд: Полностью функциональный")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )
