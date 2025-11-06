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

# Настройка логирования с улучшенным отслеживанием дублирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
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
        self.duplicate_rejections = 0
    
    def increment_request(self):
        self.request_count += 1
    
    def increment_duplicate_rejection(self):
        self.duplicate_rejections += 1
    
    def update_keep_alive(self):
        self.last_keep_alive = datetime.now()
        self.keep_alive_count += 1
    
    def get_status(self):
        return {
            "status": "healthy",
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "requests_handled": self.request_count,
            "duplicate_rejections": self.duplicate_rejections,
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
            # Таблица для кэширования контента
            conn.execute('''
                CREATE TABLE IF NOT EXISTS content_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,
                    content_type TEXT,
                    content_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для статистики канала
            conn.execute('''
                CREATE TABLE IF NOT EXISTS channel_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_count INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для ротации рецептов
            conn.execute('''
                CREATE TABLE IF NOT EXISTS recipe_rotation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_type TEXT,
                    recipe_method TEXT,
                    content_category TEXT,
                    last_used DATE,
                    use_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для защиты от дублирования
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,
                    message_text TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    recipe_type TEXT
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

    @staticmethod
    def get_kemerovo_hour():
        return datetime.now(Config.KEMEROVO_TZ).hour

# СИСТЕМА РОТАЦИИ РЕЦЕПТОВ С ИСПРАВЛЕННОЙ ЛОГИКОЙ
class AdvancedRotationSystem:
    def __init__(self):
        self.db = Database()
        self.rotation_period = 90
        self.priority_map = self._create_priority_map()
        self.category_map = self._create_category_map()
        self.init_rotation_data()
        self.fix_rotation_dates()  # 🔧 ИСПРАВЛЕНИЕ: сбрасываем даты
    
    def _create_priority_map(self):
        return {
            # ПОНЕДЕЛЬНИК - 🧠 НЕЙРОПИТАНИЕ
            0: {
                'neuro_science': ['generate_monday_science'],
                'neuro_breakfast': ['generate_brain_boost_breakfast', 'generate_focus_oatmeal', 'generate_memory_smoothie'],
                'neuro_lunch': ['generate_brain_salmon_bowl', 'generate_cognitive_chicken', 'generate_neuro_salad'],
                'neuro_dinner': ['generate_memory_fish', 'generate_brain_omelette', 'generate_neuro_stew'],
                'neuro_advice': ['generate_brain_nutrition_advice', 'generate_focus_foods_advice', 'generate_memory_boost_advice']
            },
            
            # ВТОРНИК - 💪 БЕЛКОВЫЙ ДЕНЬ
            1: {
                'protein_science': ['generate_tuesday_science'],
                'protein_breakfast': ['generate_muscle_breakfast', 'generate_energy_protein_shake', 'generate_satiety_omelette'],
                'protein_lunch': ['generate_amino_acids_bowl', 'generate_anabolic_lunch', 'generate_repair_salad'],
                'protein_dinner': ['generate_night_protein', 'generate_recovery_dinner', 'generate_lean_protein_meal'],
                'protein_advice': ['generate_protein_science_advice', 'generate_muscle_health_advice', 'generate_amino_guide_advice']
            },
            
            # СРЕДА - 🥬 ОВОЩНОЙ ДЕНЬ
            2: {
                'veggie_science': ['generate_wednesday_science'],
                'veggie_breakfast': ['generate_green_smoothie_bowl', 'generate_vegetable_omelette', 'generate_detox_breakfast'],
                'veggie_lunch': ['generate_rainbow_salad', 'generate_veggie_stew', 'generate_cleansing_soup'],
                'veggie_dinner': ['generate_roasted_vegetables', 'generate_plant_based_dinner', 'generate_fiber_rich_meal'],
                'veggie_advice': ['generate_fiber_benefits_advice', 'generate_antioxidant_guide_advice', 'generate_detox_science_advice']
            },
            
            # ЧЕТВЕРГ - 🍠 УГЛЕВОДНЫЙ ДЕНЬ
            3: {
                'carbs_science': ['generate_thursday_science'],
                'carbs_breakfast': ['generate_energy_porridge', 'generate_complex_carbs_toast', 'generate_sustained_energy_meal'],
                'carbs_lunch': ['generate_glycogen_replenishment', 'generate_energy_bowl', 'generate_carbs_balance_meal'],
                'carbs_dinner': ['generate_slow_carbs_dinner', 'generate_energy_reserve_meal', 'generate_evening_carbs'],
                'carbs_advice': ['generate_carbs_science_advice', 'generate_energy_management_advice', 'generate_glycemic_control_advice']
            },
            
            # ПЯТНИЦА - 🎉 БАЛАНС И УДОВОЛЬСТВИЕ
            4: {
                'balance_science': ['generate_friday_science'],
                'energy_breakfast': ['generate_fun_breakfast', 'generate_balanced_meal', 'generate_weekend_mood_meal'],
                'mediterranean_lunch': ['generate_mediterranean_feast', 'generate_social_lunch', 'generate_celebration_meal'],
                'friday_dessert': ['generate_healthy_indulgence', 'generate_guilt_free_treat', 'generate_weekend_dessert'],
                'water_advice': ['generate_hydration_science', 'generate_electrolyte_balance', 'generate_detox_hydration'],
                'light_dinner': ['generate_social_dinner', 'generate_evening_balance', 'generate_weekend_starter']
            },
            
            # СУББОТА - 👨‍🍳 СЕМЕЙНАЯ ГОТОВКА
            5: {
                'family_science': ['generate_saturday_science'],
                'saturday_breakfast': ['generate_family_brunch', 'generate_weekend_pancakes', 'generate_shared_breakfast'],
                'saturday_cooking': ['generate_cooking_workshop', 'generate_kids_friendly', 'generate_team_cooking'],
                'saturday_dessert': ['generate_family_dessert', 'generate_weekend_treat', 'generate_shared_sweets'],
                'family_dinner': ['generate_family_lasagna', 'generate_saturday_pizza', 'generate_shared_platter'],
                'family_advice': ['generate_family_nutrition_advice', 'generate_cooking_together_advice', 'generate_weekend_planning_advice']
            },
            
            # ВОСКРЕСЕНЬЕ - 📝 ПЛАНИРОВАНИЕ
            6: {
                'planning_science': ['generate_sunday_science'],
                'sunday_breakfast': ['generate_brunch_feast', 'generate_lazy_breakfast', 'generate_meal_prep_breakfast'],
                'sunday_lunch': ['generate_weekly_prep_lunch', 'generate_batch_cooking_lunch', 'generate_efficient_lunch'],
                'sunday_dessert': ['generate_weekly_treat', 'generate_prep_friendly_dessert', 'generate_healthy_indulgence'],
                'meal_prep_dinner': ['generate_weekly_prep_chicken', 'generate_batch_cooking', 'generate_container_meal'],
                'planning_advice': ['generate_meal_prep_guide_advice', 'generate_weekly_planning_advice', 'generate_efficient_cooking_advice']
            }
        }
    
    def _create_category_map(self):
        """Карта категорий контента для СТРОГОЙ ВАЛИДАЦИИ"""
        return {
            # Научные сообщения
            'neuro_science': 'science', 'protein_science': 'science', 'veggie_science': 'science',
            'carbs_science': 'science', 'balance_science': 'science', 'family_science': 'science',
            'planning_science': 'science',
            
            # Завтраки
            'neuro_breakfast': 'breakfast', 'protein_breakfast': 'breakfast', 'veggie_breakfast': 'breakfast',
            'carbs_breakfast': 'breakfast', 'energy_breakfast': 'breakfast', 'saturday_breakfast': 'breakfast',
            'sunday_breakfast': 'breakfast',
            
            # Обеды
            'neuro_lunch': 'lunch', 'protein_lunch': 'lunch', 'veggie_lunch': 'lunch', 'carbs_lunch': 'lunch',
            'mediterranean_lunch': 'lunch', 'sunday_lunch': 'lunch',
            
            # Ужины
            'neuro_dinner': 'dinner', 'protein_dinner': 'dinner', 'veggie_dinner': 'dinner', 'carbs_dinner': 'dinner',
            'light_dinner': 'dinner', 'family_dinner': 'dinner', 'meal_prep_dinner': 'dinner',
            
            # Десерты
            'friday_dessert': 'dessert', 'saturday_dessert': 'dessert', 'sunday_dessert': 'dessert',
            
            # Советы
            'neuro_advice': 'advice', 'protein_advice': 'advice', 'veggie_advice': 'advice', 'carbs_advice': 'advice',
            'water_advice': 'advice', 'family_advice': 'advice', 'planning_advice': 'advice',
            
            # Готовка
            'saturday_cooking': 'cooking'
        }
    
    def init_rotation_data(self):
        """Инициализация системы ротации для всех рецептов С КАТЕГОРИЯМИ"""
        recipe_methods = [
            # Научные сообщения (7 методов)
            ('generate_monday_science', 'neuro_science', 'science'),
            ('generate_tuesday_science', 'protein_science', 'science'),
            ('generate_wednesday_science', 'veggie_science', 'science'),
            ('generate_thursday_science', 'carbs_science', 'science'),
            ('generate_friday_science', 'balance_science', 'science'),
            ('generate_saturday_science', 'family_science', 'science'),
            ('generate_sunday_science', 'planning_science', 'science'),
            
            # Завтраки (49 методов)
            ('generate_brain_boost_breakfast', 'neuro_breakfast', 'breakfast'),
            ('generate_focus_oatmeal', 'neuro_breakfast', 'breakfast'),
            ('generate_memory_smoothie', 'neuro_breakfast', 'breakfast'),
            ('generate_neuro_omelette', 'neuro_breakfast', 'breakfast'),
            ('generate_brain_pancakes', 'neuro_breakfast', 'breakfast'),
            ('generate_cognitive_yogurt', 'neuro_breakfast', 'breakfast'),
            ('generate_neuro_muesli', 'neuro_breakfast', 'breakfast'),
            ('generate_muscle_breakfast', 'protein_breakfast', 'breakfast'),
            ('generate_energy_protein_shake', 'protein_breakfast', 'breakfast'),
            ('generate_satiety_omelette', 'protein_breakfast', 'breakfast'),
            ('generate_protein_waffles', 'protein_breakfast', 'breakfast'),
            ('generate_amino_toast', 'protein_breakfast', 'breakfast'),
            ('generate_anabolic_porridge', 'protein_breakfast', 'breakfast'),
            ('generate_repair_smoothie', 'protein_breakfast', 'breakfast'),
            ('generate_green_smoothie_bowl', 'veggie_breakfast', 'breakfast'),
            ('generate_vegetable_omelette', 'veggie_breakfast', 'breakfast'),
            ('generate_detox_breakfast', 'veggie_breakfast', 'breakfast'),
            ('generate_veggie_scramble', 'veggie_breakfast', 'breakfast'),
            ('generate_cleansing_bowl', 'veggie_breakfast', 'breakfast'),
            ('generate_fiber_toast', 'veggie_breakfast', 'breakfast'),
            ('generate_antioxidant_smoothie', 'veggie_breakfast', 'breakfast'),
            ('generate_energy_porridge', 'carbs_breakfast', 'breakfast'),
            ('generate_complex_carbs_toast', 'carbs_breakfast', 'breakfast'),
            ('generate_sustained_energy_meal', 'carbs_breakfast', 'breakfast'),
            ('generate_glycogen_breakfast', 'carbs_breakfast', 'breakfast'),
            ('generate_energy_bowl', 'carbs_breakfast', 'breakfast'),
            ('generate_carbs_pancakes', 'carbs_breakfast', 'breakfast'),
            ('generate_fuel_smoothie', 'carbs_breakfast', 'breakfast'),
            ('generate_fun_breakfast', 'energy_breakfast', 'breakfast'),
            ('generate_balanced_meal', 'energy_breakfast', 'breakfast'),
            ('generate_weekend_mood_meal', 'energy_breakfast', 'breakfast'),
            ('generate_friday_pancakes', 'energy_breakfast', 'breakfast'),
            ('generate_celebration_toast', 'energy_breakfast', 'breakfast'),
            ('generate_social_smoothie', 'energy_breakfast', 'breakfast'),
            ('generate_indulgence_bowl', 'energy_breakfast', 'breakfast'),
            ('generate_family_brunch', 'saturday_breakfast', 'breakfast'),
            ('generate_weekend_pancakes', 'saturday_breakfast', 'breakfast'),
            ('generate_shared_breakfast', 'saturday_breakfast', 'breakfast'),
            ('generate_saturday_omelette', 'saturday_breakfast', 'breakfast'),
            ('generate_family_waffles', 'saturday_breakfast', 'breakfast'),
            ('generate_team_smoothie', 'saturday_breakfast', 'breakfast'),
            ('generate_brunch_feast', 'sunday_breakfast', 'breakfast'),
            ('generate_lazy_breakfast', 'sunday_breakfast', 'breakfast'),
            ('generate_meal_prep_breakfast', 'sunday_breakfast', 'breakfast'),
            ('generate_sunday_porridge', 'sunday_breakfast', 'breakfast'),
            ('generate_prep_friendly_toast', 'sunday_breakfast', 'breakfast'),
            ('generate_efficient_smoothie', 'sunday_breakfast', 'breakfast'),
            ('generate_planning_omelette', 'sunday_breakfast', 'breakfast'),
            
            # Обеды (49 методов) - будут добавлены в следующих частях
            ('generate_brain_salmon_bowl', 'neuro_lunch', 'lunch'),
            ('generate_cognitive_chicken', 'neuro_lunch', 'lunch'),
            ('generate_neuro_salad', 'neuro_lunch', 'lunch'),
            # ... остальные методы обедов будут добавлены
        ]
        
        with self.db.get_connection() as conn:
            for method, recipe_type, content_category in recipe_methods:
                conn.execute('''
                    INSERT OR IGNORE INTO recipe_rotation 
                    (recipe_type, recipe_method, content_category, last_used, use_count)
                    VALUES (?, ?, ?, DATE('now', '-91 days'), 0)
                ''', (recipe_type, method, content_category))
    
    def fix_rotation_dates(self):
        """🔧 ИСПРАВЛЕНИЕ: Сброс дат ротации для всех рецептов"""
        with self.db.get_connection() as conn:
            conn.execute('''
                UPDATE recipe_rotation 
                SET last_used = DATE('now', '-91 days'), use_count = 0
            ''')
            logger.info("🔄 СБРОС ДАТ РОТАЦИИ: все рецепты теперь доступны")
        
        # Проверяем результат
        self.check_rotation_status()
    
    def get_content_category(self, recipe_type):
        """Получить категорию контента для типа рецепта"""
        return self.category_map.get(recipe_type, 'advice')
    
    def validate_content_type_for_current_time(self, requested_type, current_hour):
        """СТРОГАЯ ВАЛИДАЦИЯ типа контента по текущему времени"""
        requested_category = self.get_content_category(requested_type)
        
        # Определяем допустимые категории для текущего часа
        if 5 <= current_hour < 11:  # Утро: 5:00 - 10:59
            allowed_categories = ['breakfast', 'science', 'advice']
            fallback_type = 'neuro_advice' if 'neuro' in requested_type else 'protein_advice'
        elif 11 <= current_hour < 16:  # День: 11:00 - 15:59  
            allowed_categories = ['lunch', 'science', 'advice', 'cooking']
            fallback_type = 'neuro_advice' if 'neuro' in requested_type else 'protein_advice'
        elif 16 <= current_hour < 22:  # Вечер: 16:00 - 21:59
            allowed_categories = ['dinner', 'dessert', 'advice']
            fallback_type = 'neuro_advice' if 'neuro' in requested_type else 'protein_advice'
        else:  # Ночь: 22:00 - 4:59
            allowed_categories = ['advice', 'science']
            fallback_type = 'neuro_advice'
        
        # Проверяем валидность категории
        if requested_category not in allowed_categories:
            logger.warning(f"🚨 НЕВАЛИДНАЯ КАТЕГОРИЯ: {requested_type} ({requested_category}) в {current_hour}:00")
            logger.info(f"📋 Разрешены: {allowed_categories}")
            
            # Находим подходящий тип из той же тематики
            corrected_type = self._find_corrected_type(requested_type, allowed_categories)
            if corrected_type:
                logger.info(f"🔄 Автокоррекция: {requested_type} -> {corrected_type}")
                return corrected_type
            else:
                logger.warning(f"⚠️ Не удалось найти замену для {requested_type}, используем fallback")
                return fallback_type
        
        return requested_type
    
    def _find_corrected_type(self, original_type, allowed_categories):
        """Найти подходящий тип контента из разрешенных категорий"""
        # Извлекаем тематику из оригинального типа
        theme = original_type.split('_')[0]  # neuro, protein, veggie и т.д.
        
        # Ищем подходящий тип в той же тематике
        for candidate_type, category in self.category_map.items():
            if (candidate_type.startswith(theme) and 
                category in allowed_categories and
                candidate_type != original_type):
                return candidate_type
        
        # Если не нашли в той же тематике, ищем любой подходящий
        for candidate_type, category in self.category_map.items():
            if category in allowed_categories:
                return candidate_type
        
        return None
    
    def get_priority_recipe(self, recipe_type, weekday):
        """Умная ротация с учетом дня недели и СТРОГОЙ ВАЛИДАЦИИ ВРЕМЕНИ"""
        current_hour = TimeManager.get_kemerovo_hour()
        
        # ПРИОРИТЕТ 1: ВАЛИДАЦИЯ ВРЕМЕНИ - исправляем тип если нужно
        validated_type = self.validate_content_type_for_current_time(recipe_type, current_hour)
        
        if validated_type != recipe_type:
            logger.info(f"🕒 КОРРЕКЦИЯ ТИПА: {recipe_type} -> {validated_type} (время: {current_hour}:00)")
            recipe_type = validated_type
        
        # ПРИОРИТЕТ 2: Тематические рецепты для дня
        if weekday in self.priority_map and recipe_type in self.priority_map[weekday]:
            for method in self.priority_map[weekday][recipe_type]:
                if self._is_recipe_available(method):
                    return method
        
        # ПРИОРИТЕТ 3: Ротация по типу рецепта С ПРОВЕРКОЙ КАТЕГОРИИ
        return self.get_available_recipe(recipe_type)
    
    def _is_recipe_available(self, method_name):
        """Проверка доступности рецепта по ротации"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT last_used FROM recipe_rotation 
                WHERE recipe_method = ? AND last_used <= DATE('now', '-' || ? || ' days')
            ''', (method_name, self.rotation_period))
            return cursor.fetchone() is not None

    def get_available_recipe(self, recipe_type):
        """🔧 ИСПРАВЛЕННАЯ ЛОГИКА РОТАЦИИ - теперь работает правильно!"""
        expected_category = self.get_content_category(recipe_type)
        
        # ДИАГНОСТИКА: проверяем состояние ротации
        self._debug_rotation_status(recipe_type, expected_category)
        
        with self.db.get_connection() as conn:
            # 1. Попытка: точное соответствие типа + категории
            cursor = conn.execute('''
                SELECT recipe_method FROM recipe_rotation 
                WHERE recipe_type = ? AND content_category = ? 
                AND last_used <= DATE('now', '-' || ? || ' days')
                ORDER BY use_count ASC, last_used ASC
                LIMIT 1
            ''', (recipe_type, expected_category, self.rotation_period))
            
            result = cursor.fetchone()
            if result:
                method = result['recipe_method']
                conn.execute('''
                    UPDATE recipe_rotation 
                    SET last_used = DATE('now'), use_count = use_count + 1
                    WHERE recipe_method = ?
                ''', (method,))
                logger.info(f"✅ Найден рецепт точного соответствия: {method}")
                return method
            
            # 2. Попытка: любая категория с ротацией
            cursor = conn.execute('''
                SELECT recipe_method FROM recipe_rotation 
                WHERE content_category = ? 
                AND last_used <= DATE('now', '-' || ? || ' days')
                ORDER BY use_count ASC, last_used ASC
                LIMIT 1
            ''', (expected_category, self.rotation_period))
            
            result = cursor.fetchone()
            if result:
                method = result['recipe_method']
                conn.execute('''
                    UPDATE recipe_rotation 
                    SET last_used = DATE('now'), use_count = use_count + 1
                    WHERE recipe_method = ?
                ''', (method,))
                logger.info(f"🔄 Использован рецепт из категории {expected_category}: {method}")
                return method
            
            # 3. ПРИНУДИТЕЛЬНАЯ РОТАЦИЯ: берем самый редко используемый
            logger.warning(f"🚨 Принудительная ротация для категории {expected_category}")
            cursor = conn.execute('''
                SELECT recipe_method FROM recipe_rotation 
                WHERE content_category = ?
                ORDER BY use_count ASC, last_used ASC
                LIMIT 1
            ''', (expected_category,))
            
            result = cursor.fetchone()
            if result:
                method = result['recipe_method']
                conn.execute('''
                    UPDATE recipe_rotation 
                    SET last_used = DATE('now'), use_count = use_count + 1
                    WHERE recipe_method = ?
                ''', (method,))
                logger.info(f"🔄 Принудительная ротация: {method}")
                return method
        
        return self._get_guaranteed_fallback(recipe_type, expected_category)
    
    def _debug_rotation_status(self, recipe_type, expected_category):
        """Диагностика состояния ротации"""
        with self.db.get_connection() as conn:
            # Проверяем точное соответствие
            cursor = conn.execute('''
                SELECT COUNT(*) as total_count,
                       SUM(CASE WHEN last_used <= DATE('now', '-90 days') THEN 1 ELSE 0 END) as available_count
                FROM recipe_rotation 
                WHERE recipe_type = ? AND content_category = ?
            ''', (recipe_type, expected_category))
            
            result = cursor.fetchone()
            if result:
                logger.info(f"🔍 ДИАГНОСТИКА {recipe_type}: {result['available_count']}/{result['total_count']} доступно")
            
            # Проверяем категорию
            cursor = conn.execute('''
                SELECT COUNT(*) as total_count,
                       SUM(CASE WHEN last_used <= DATE('now', '-90 days') THEN 1 ELSE 0 END) as available_count
                FROM recipe_rotation 
                WHERE content_category = ?
            ''', (expected_category,))
            
            result = cursor.fetchone()
            if result:
                logger.info(f"🔍 ДИАГНОСТИКА категории {expected_category}: {result['available_count']}/{result['total_count']} доступно")
    
    def _get_guaranteed_fallback(self, recipe_type, expected_category):
        """Гарантированный fallback метод с логированием"""
        fallback_map = {
            'breakfast': 'generate_brain_boost_breakfast',
            'lunch': 'generate_brain_salmon_bowl',
            'dinner': 'generate_memory_fish', 
            'dessert': 'generate_family_dessert',
            'advice': 'generate_brain_nutrition_advice',
            'science': 'generate_monday_science',
            'cooking': 'generate_cooking_workshop'
        }
        
        fallback_method = fallback_map.get(expected_category, 'generate_brain_nutrition_advice')
        logger.error(f"🚨 КРИТИЧЕСКИЙ FALLBACK: {recipe_type} -> {fallback_method}")
        return fallback_method
    
    def check_rotation_status(self):
        """Проверка состояния ротации рецептов"""
        with self.db.get_connection() as conn:
            # Проверяем количество рецептов по категориям
            cursor = conn.execute('''
                SELECT content_category, 
                       COUNT(*) as total,
                       SUM(CASE WHEN last_used <= DATE('now', '-90 days') THEN 1 ELSE 0 END) as available,
                       SUM(CASE WHEN last_used > DATE('now', '-90 days') THEN 1 ELSE 0 END) as used_recently
                FROM recipe_rotation 
                GROUP BY content_category
            ''')
            
            status = {}
            for row in cursor:
                category = row['content_category']
                status[category] = {
                    'total': row['total'],
                    'available': row['available'],
                    'used_recently': row['used_recently'],
                    'availability_percent': round((row['available'] / row['total']) * 100, 1) if row['total'] > 0 else 0
                }
            
            logger.info("📊 СТАТУС РОТАЦИИ ПО КАТЕГОРИЯМ:")
            for category, stats in status.items():
                logger.info(f"   {category}: {stats['available']}/{stats['total']} доступно ({stats['availability_percent']}%)")
            
            return status

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
        ],
        'science': [
            'https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=600',
            'https://images.unsplash.com/photo-1559757148-5c350d0d3c56?w=600',
            'https://images.unsplash.com/photo-1532187863486-abf9dbad1b69?w=600',
        ],
        'cooking': [
            'https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=600',
            'https://images.unsplash.com/photo-1547592180-85f173990554?w=600',
            'https://images.unsplash.com/photo-1556910103-1c02745aae4d?w=600',
        ]
    }
    
    EMOJI_CATEGORIES = {
        'breakfast': ['🍳', '🥞', '🍲', '🥣', '☕', '🥐', '🍓', '🥑'],
        'lunch': ['🍝', '🍛', '🥘', '🍜', '🍱', '🥗', '🌯', '🥪'],
        'dinner': ['🌙', '🍽️', '🥘', '🍴', '✨', '🍷', '🕯️', '🌟'],
        'dessert': ['🍰', '🎂', '🍮', '🍨', '🧁', '🍫', '🍩', '🥮'],
        'advice': ['💡', '🎯', '📚', '🧠', '💪', '🥗', '💧', '👨‍⚕️'],
        'science': ['🔬', '🧪', '📊', '🎯', '🧠', '💫', '⚗️', '🔭'],
        'cooking': ['👨‍🍳', '🔪', '🥘', '🍳', '🧂', '🌶️', '🥕', '🍅'],
    }
    
    def get_photo_for_recipe(self, recipe_type):
        photo_category = self._map_recipe_to_photo(recipe_type)
        photos = self.FOOD_PHOTOS.get(photo_category, self.FOOD_PHOTOS['science'])
        return random.choice(photos)
    
    def _map_recipe_to_photo(self, recipe_type):
        mapping = {
            'neuro_science': 'science', 'protein_science': 'science', 'veggie_science': 'science',
            'carbs_science': 'science', 'balance_science': 'science', 'family_science': 'science',
            'planning_science': 'science',
            'neuro_breakfast': 'breakfast', 'protein_breakfast': 'breakfast', 'veggie_breakfast': 'breakfast',
            'carbs_breakfast': 'breakfast', 'energy_breakfast': 'breakfast', 'saturday_breakfast': 'breakfast',
            'sunday_breakfast': 'breakfast',
            'neuro_lunch': 'lunch', 'protein_lunch': 'lunch', 'veggie_lunch': 'lunch', 'carbs_lunch': 'lunch',
            'mediterranean_lunch': 'lunch', 'sunday_lunch': 'lunch',
            'neuro_dinner': 'dinner', 'protein_dinner': 'dinner', 'veggie_dinner': 'dinner', 'carbs_dinner': 'dinner',
            'light_dinner': 'dinner', 'family_dinner': 'dinner', 'meal_prep_dinner': 'dinner',
            'friday_dessert': 'dessert', 'saturday_dessert': 'dessert', 'sunday_dessert': 'dessert',
            'neuro_advice': 'advice', 'protein_advice': 'advice', 'veggie_advice': 'advice', 'carbs_advice': 'advice',
            'water_advice': 'advice', 'family_advice': 'advice', 'planning_advice': 'advice',
            'saturday_cooking': 'cooking'
        }
        return mapping.get(recipe_type, 'science')
    
    def generate_attractive_post(self, title, content, recipe_type, benefits):
        photo_url = self.get_photo_for_recipe(recipe_type)
        category = self._map_recipe_to_photo(recipe_type)
        main_emoji = random.choice(self.EMOJI_CATEGORIES.get(category, ['🔬']))
        
        post = f"""{main_emoji} <b>{title}</b>

<a href="{photo_url}">🖼️ ИЛЛЮСТРАЦИЯ</a>

{content}

🔬 НАУЧНАЯ ПОЛЬЗА:
{benefits}

─━━━━━━━━━━━━━━ ⋅∙∘ ★ ∘∙⋅ ━━━━━━━━━━━━─

🎯 Основано на исследованиях доказательной нутрициологии

📢 Подписывайтесь → @ppsupershef
💬 Обсуждаем рецепты → @ppsupershef_chat

😋 Вкусно | 💪 Полезно | ⏱️ Быстро | 🧠 Научно

🔄 Поделитесь с друзьями! → @ppsupershef"""
        
        return post
# ТЕЛЕГРАМ МЕНЕДЖЕР С ЗАЩИТОЙ ОТ ДУБЛИРОВАНИЯ И УЛУЧШЕННЫМ ЛОГИРОВАНИЕМ
class TelegramManager:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.sent_hashes = set()
        self.db = Database()
        self.init_duplicate_protection()
    
    def init_duplicate_protection(self):
        """Инициализация системы защиты от дублирования"""
        with self.db.get_connection() as conn:
            # Восстанавливаем sent_hashes из базы данных
            cursor = conn.execute('SELECT content_hash FROM sent_messages')
            for row in cursor:
                self.sent_hashes.add(row['content_hash'])
            
            logger.info(f"📊 Загружено {len(self.sent_hashes)} хешей из истории сообщений")
    
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
            
            # УЛУЧШЕННОЕ ЛОГИРОВАНИЕ ДУБЛИРОВАНИЯ
            logger.info(f"🔍 Проверка дублирования: хеш {content_hash[:8]}...")
            
            # ПРОВЕРКА ДУБЛИРОВАНИЯ В ПАМЯТИ
            if content_hash in self.sent_hashes:
                logger.warning(f"⚠️ Попытка отправить дубликат контента (память, хеш: {content_hash[:8]}...)")
                service_monitor.increment_duplicate_rejection()
                return False
            
            # ПРОВЕРКА ДУБЛИРОВАНИЯ В БАЗЕ ДАННЫХ
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'SELECT 1 FROM sent_messages WHERE content_hash = ?', 
                    (content_hash,)
                )
                if cursor.fetchone():
                    logger.warning(f"⚠️ Попытка отправить дубликат контента (БД, хеш: {content_hash[:8]}...)")
                    service_monitor.increment_duplicate_rejection()
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
            logger.info(f"📨 Ответ Telegram: {result.get('ok', False)}")
            
            if result.get('ok'):
                # СОХРАНЕНИЕ В ИСТОРИЮ ПРИ УСПЕШНОЙ ОТПРАВКЕ
                self.sent_hashes.add(content_hash)
                with self.db.get_connection() as conn:
                    # Извлекаем тип рецепта из текста для лучшего отслеживания
                    recipe_type = "unknown"
                    if "🧠 НАУКА ДНЯ" in text:
                        recipe_type = "science"
                    elif "ЗАВТРАК" in text:
                        recipe_type = "breakfast" 
                    elif "ОБЕД" in text:
                        recipe_type = "lunch"
                    elif "УЖИН" in text:
                        recipe_type = "dinner"
                    elif "СОВЕТ" in text:
                        recipe_type = "advice"
                    elif "ДЕСЕРТ" in text:
                        recipe_type = "dessert"
                    
                    conn.execute(
                        'INSERT INTO sent_messages (content_hash, message_text, recipe_type) VALUES (?, ?, ?)',
                        (content_hash, text[:500], recipe_type)  # Сохраняем первые 500 символов
                    )
                logger.info(f"✅ [{source}] Сообщение успешно отправлено в канал (хеш: {content_hash[:8]}...)")
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
    
    def cleanup_old_messages(self, days=90):
        """Очистка старых сообщений для экономии места"""
        with self.db.get_connection() as conn:
            conn.execute(
                'DELETE FROM sent_messages WHERE sent_at < DATE("now", ?)',
                (f"-{days} days",)
            )
            deleted_count = conn.total_changes
            
            # Также очищаем память
            cursor = conn.execute('SELECT content_hash FROM sent_messages')
            self.sent_hashes = {row['content_hash'] for row in cursor}
            logger.info(f"🧹 Очищены сообщения старше {days} дней: удалено {deleted_count} записей")
    
    def get_duplicate_stats(self):
        """Получить статистику по дублированию"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT recipe_type, COUNT(*) as count 
                FROM sent_messages 
                GROUP BY recipe_type
            ''')
            stats = {row['recipe_type']: row['count'] for row in cursor}
            
            cursor = conn.execute('SELECT COUNT(*) as total FROM sent_messages')
            total = cursor.fetchone()['total']
            
            return {
                'total_messages': total,
                'messages_by_type': stats,
                'memory_hashes': len(self.sent_hashes),
                'duplicate_rejections': service_monitor.duplicate_rejections
            }
# УМНЫЙ ГЕНЕРАТОР КОНТЕНТА С 245 УНИКАЛЬНЫМИ РЕЦЕПТАМИ И НАУЧНЫМИ СООБЩЕНИЯМИ
class SmartContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.visual_manager = VisualContentManager()
        self.db = Database()
        self.rotation_system = AdvancedRotationSystem()
    
    # 🔬 НАУЧНЫЕ СООБЩЕНИЯ ДЛЯ КАЖДОГО ДНЯ (7 УНИКАЛЬНЫХ)
    def generate_monday_science(self):
        content = """
🧠 ПОНЕДЕЛЬНИК: ЗАПУСКАЕМ МОЗГ НА ПОЛНУЮ МОЩНОСТЬ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: питание для когнитивных функций

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 🧩 ОМЕГА-3 ДГК
Строительный материал для нейронов
Улучшает нейропластичность на 28%
Источники: лосось, грецкие орехи, семена льна

• 💫 ХОЛИН И ФОСФОЛИПИДЫ  
Предшественник ацетилхолина - нейромедиатора памяти
Ускоряет передачу нервных импульсов
Источники: яйца, печень, арахис

• 🛡️ АНТИОКСИДАНТЫ
Защита митохондрий от окислительного стресса
Снижение возрастного когнитивного decline
Источники: ягоды, зеленый чай, темный шоколад

• 🔋 МИКРОЭЛЕМЕНТЫ
Магний - для синаптической пластичности
Цинк - для нейромедиаторного баланса
Железо - для оксигенации мозга

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Ясность мышления и концентрация
• Улучшение памяти и learning capacity
• Защита от mental fatigue
• Долгосрочная нейропротекция

#нейропитание #мозг #понедельник #концентрация
"""
        benefits = """• 🧠 Улучшение когнитивных функций на 40%
• 💡 Повышение продуктивности и креативности
• 🛡️ Защита от возрастных нарушений памяти
• ⚡ Быстрая реакция и ясность мышления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 НАУКА ДНЯ: ПИТАНИЕ ДЛЯ МОЗГА",
            content, "neuro_science", benefits
        )

    def generate_tuesday_science(self):
        content = """
💪 ВТОРНИК: СТРОИМ СИЛЬНОЕ ТЕЛО И МЫШЦЫ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: оптимизация белкового обмена

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 🏗️ АНАБОЛИЧЕСКОЕ ОКНО 
Пик синтеза мышечного белка через 24-48 часов после нагрузки
Оптимальное усвоение: 1.6-2.0 г белка на кг веса
Распределение: 20-40 г за прием пищи

• 🧬 АМИНОКИСЛОТНЫЙ ПРОФИЛЬ
BCAA: лейцин - ключевой активатор mTOR пути
Незаменимые аминокислоты: 9 must-have компонентов
Комплексный подход: животные + растительные источники

• 🔄 ВОССТАНОВЛЕНИЕ ТКАНЕЙ
Репарация мышечных волокон после активного понедельника
Синтез коллагена для соединительной ткани
Обновление ферментных систем организма

• ⚡ ЭНЕРГЕТИЧЕСКИЙ МЕТАБОЛИЗМ
Белки как альтернативный источник энергии
Термогенный эффект: 20-30% затрат на усвоение
Стабилизация уровня глюкозы в крови

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Активный синтез мышечного белка
• Ускоренное восстановление тканей
• Укрепление иммунной системы
• Длительное чувство сытости

#белки #мышцы #вторник #восстановление
"""
        benefits = """• 💪 Увеличение мышечной массы на 15-20%
• 🔄 Ускорение восстановления после нагрузок
• 🛡️ Укрепление иммунной системы
• ⚡ Повышение энергетического обмена"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 НАУКА ДНЯ: СИЛА БЕЛКОВ",
            content, "protein_science", benefits
        )

    def generate_wednesday_science(self):
        content = """
🥬 СРЕДА: ДЕТОКС И ВИТАМИННЫЙ БУСТ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: очищение и восстановление ресурсов

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 🧹 ПИК ТОКСИЧЕСКОЙ НАГРУЗКИ
Максимальное накопление метаболитов к середине недели
Окислительный стресс от городской среды и работы
Активация ферментных систем детокса

• 🌿 КЛЕТЧАТКА ДЛЯ МИКРОБИОМА
Норма: 25-30 г для эффективного очищения
Растворимая клетчатка: питание для полезных бактерий
Нерастворимая клетчатка: механическое очищение ЖКТ

• 🛡️ ФИТОНУТРИЕНТЫ ПРОТИВ СТРЕССА
Антиоксиданты: нейтрализация свободных радикалов
Полифенолы: модуляция воспалительных процессов
Глюкозинолаты: активация ферментов детокса II фазы

• 💧 ГИДРАТАЦИЯ И ДРЕНАЖ
Усиление выведения водорастворимых токсинов
Поддержка лимфатической системы
Оптимизация работы почек и печени

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Глубокое очищение организма
• Улучшение состава микробиома
• Снижение окислительного стресса  
• Прилив энергии и легкости

#детокс #овощи #среда #очищение
"""
        benefits = """• 🧹 Очищение организма от метаболитов
• 🦠 Улучшение состава микробиома на 40%
• 🛡️ Снижение окислительного стресса
• 💪 Укрепление иммунной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 НАУКА ДНЯ: СИЛА ОВОЩЕЙ",
            content, "veggie_science", benefits
        )

    def generate_thursday_science(self):
        content = """
🍠 ЧЕТВЕРГ: ЗАПАСАЕМ ЭНЕРГИЮ ДЛЯ ПРОДУКТИВНОСТИ!

⚡️ СЕГОДНЯШНИКИЙ ФОКУС: устойчивая энергия и ментальный фокус

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 🏃‍♂️ ПОДГОТОВКА К УИКЕНДУ
Восполнение запасов гликогена после рабочих дней
Создание энергетического резерва для активности
Оптимизация метаболической гибкости

• ⚡ УСТОЙЧИВАЯ ЭНЕРГИЯ
Низкий гликемический индекс: 55 и ниже
Медленное высвобождение глюкозы в кровь
Стабильный уровень энергии без скачков и спадов

• 🧠 МЕНТАЛЬНЫЙ ФОКUS
Глюкоза - единственный источник энергии для мозга
Поддержка когнитивных функций перед сложной пятницей
Стабилизация настроения и концентрации внимания

• 🔄 МЕТАБОЛИЧЕСКАЯ ОПТИМИЗАЦИЯ
Инсулиновая чувствительность: контроль ответа
Лептиновая сигнализация: регуляция аппетита
Митохондриальная функция: производство ATP

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Стабильная энергия на 6-8 часов
• Улучшение когнитивных функций
• Подготовка к активным выходным
• Оптимизация метаболического здоровья

#углеводы #энергия #четверг #фокус
"""
        benefits = """• ⚡ Стабильная энергия на 6-8 часов
• 🧠 Улучшение когнитивных функций на 25%
• 🏃‍♂️ Повышение физической производительности
• 📈 Оптимизация метаболического здоровья"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 НАУКА ДНЯ: ЭНЕРГИЯ УГЛЕВОДОВ",
            content, "carbs_science", benefits
        )

    def generate_friday_science(self):
        content = """
🎉 ПЯТНИЦА: БАЛАНС, РЕЛАКС И УМНОЕ УДОВОЛЬСТВИЕ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: психологический комфорт и социальная адаптация

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 😊 ПСИХОЛОГИЧЕСКИЙ РЕЛАКС
Снижение уровня кортизола перед выходными
Активация парасимпатической нервной системы
Баланс между дисциплиной и гибкостью

• 🍽️ СОЦИАЛЬНОЕ ПИТАНИЕ
Подготовка к вечерним мероприятиям и встречам
Культура умеренности и осознанного выбора
Интеграция здоровых привычек в социальную жизнь

• ⚖️ ПРИНЦИП 80/20
80% питательных и полезных продуктов
20% для удовольствия и социальных ситуаций
Отсутствие чувства вины и стресса

• 💫 ГОРМОНАЛЬНЫЙ БАЛАНС
Серотонин: продукты-предшественники хорошего настроения
Дофамин: умеренное вознаграждение без перегрузки
Окситоцин: социальное питание как bonding experience

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Психологическая разгрузка
• Социальная интеграция здоровых привычек
• Баланс между дисциплиной и гибкостью
• Положительный эмоциональный фон

#баланс #пятница #удовольствие #релакс
"""
        benefits = """• 😊 Снижение стресса и улучшение настроения
• 🍽️ Успешная интеграция в социальные ситуации
• ⚖️ Баланс между здоровьем и удовольствием
• 💫 Долгосрочная устойчивость привычек"""
        
        return self.visual_manager.generate_attractive_post(
            "🎉 НАУКА ДНЯ: БАЛАНС И УДОВОЛЬСТВИЕ",
            content, "balance_science", benefits
        )

    def generate_saturday_science(self):
        content = """
👨‍🍳 СУББОТА: СЕМЕЙНАЯ МАГИЯ НА КУХНЕ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: совместное творчество и пищевое образование

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• ❤️ СОВМЕСТНОЕ ПРИГОТОВЛЕНИЕ
Укрепление семейных bonds через кулинарию
Развитие пищевой культуры у детей
Создание позитивных ассоциаций со здоровой едой

• 🎨 КУЛИНАРНОЕ ОБРАЗОВАНИЕ
Обучение технике приготовления полезных блюд
Развитие сенсорного восприятия и вкуса
Формирование навыков осознанного выбора продуктов

• 👨‍👩‍👧‍👦 МЕЖПОКОЛЕНЧЕСКАЯ ПЕРЕДАЧА
Традиции здорового питания в семье
Обмен рецептами и кулинарными секретами
Создание family food heritage

• 🍽️ КУЛЬТУРА ПИТАНИЯ
Осознанное потребление без спешки
Развитие вкусовых предпочтений
Позитивное отношение к процессу еды

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Укрепление семейных связей
• Развитие кулинарных навыков
• Положительное отношение к здоровой еде
• Создание теплых воспоминаний

#семья #суббота #готовка #традиции
"""
        benefits = """• 👨‍👩‍👧‍👦 Укрепление семейных отношений на 35%
• 🎨 Развитие кулинарных навыков у всех членов семьи
• 🍽️ Формирование здоровых пищевых привычек
• 💫 Создание позитивных семейных традиций"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 НАУКА ДНЯ: СЕМЕЙНАЯ КУХНЯ",
            content, "family_science", benefits
        )

    def generate_sunday_science(self):
        content = """
📝 ВОСКРЕСЕНЬЕ: ИНВЕСТИЦИЯ В УСПЕШНУЮ НЕДЕЛЮ!

⚡️ СЕГОДНЯШНИЙ ФОКУС: стратегическое планирование и подготовка

🎯 НАУЧНАЯ СТРАТЕГИЯ:

• 🗓️ MEAL-PREP СИСТЕМА
Оптимизация времени и ресурсов на неделю
Снижение decision fatigue в рабочие дни
Гарантия соблюдения здорового рациона

• ⚖️ БАЛANS МАКРОНУТРИЕНТОВ
Расчет потребностей на предстоящую неделю
Распределение белков, жиров, углеводов
Учет предполагаемой физической активности

• 💰 ЭКОНОМИЯ РЕСУРСОВ
Снижение пищевых отходов через планирование
Оптимизация финансовых затрат на питание
Эффективное использование сезонных продуктов

• 🎯 ПРОАКТИВНЫЙ ПОДХОД
Предотвращение спонтанных нездоровых выборов
Снижение стресса от ежедневного приготовления
Создание feeling of control и уверенности

🎯 РЕЗУЛЬТАТ ЗА ДЕНЬ:
• Четкий план питания на неделю
• Подготовленные ингредиенты и блюда
• Снижение стресса от готовки
• Экономия времени и денег

#планирование #воскресенье #mealprep #организация
"""
        benefits = """• ⏱️ Экономия 5-7 часов в неделю на готовке
• 💰 Снижение затрат на питание на 20-30%
• 🍽️ Гарантия здорового рациона всю неделю
• 😌 Снижение стресса и decision fatigue"""
        
        return self.visual_manager.generate_attractive_post(
            "📝 НАУКА ДНЯ: ПЛАНИРОВАНИЕ ПИТАНИЯ",
            content, "planning_science", benefits
        )
    # 🧠 ПОНЕДЕЛЬНИК - НЕЙРОПИТАНИЕ (28 РЕЦЕПТОВ)
    
    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_brain_boost_breakfast(self):
        content = """
🧠 ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С ЛОСОСЕМ И АВОКАДО
КБЖУ: 380 ккал • Белки: 28г • Жиры: 25г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин - 147 мг/шт)
• Лосось слабосоленый - 120 г (Омега-3 - 2.5г/100г)
• Авокадо - 1 шт (калий - 485мг/100г)
• Шпинат - 80 г (лютеин - 12мг/100г)
• Семена чиа - 1 ст.л. (Омега-3 - 18г/100г)
• Оливковое масло - 1 ч.л.

Приготовление (12 минут):
1. Яйца взбить с щепоткой соли
2. Шпинат обжарить 1 минуту на оливковом масле
3. Залить яйцами, готовить на среднем огне 5 минут
4. Добавить нарезанный лосось и авокадо
5. Посыпать семенами чиа перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Холин из яиц + Омега-3 из лосося создают идеальную комбинацию для синтеза нейромедиаторов и защиты мембран нейронов.
"""
        benefits = """• 🥚 Яйца - холин для ацетилхолина (память)
• 🐟 Лосось - ДГК для нейропластичности
• 🥑 Авокадо - витамин E для защиты мозга
• 🥬 Шпинат - лютеин для когнитивных функций"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С ЛОСОСЕМ",
            content, "neuro_breakfast", benefits
        )

    def generate_focus_oatmeal(self):
        content = """
🎯 ОВСЯНКА ДЛЯ ФОКУСА С ГРЕЦКИМИ ОРЕХАМИ
КБЖУ: 350 ккал • Белки: 15г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 2 порции:
• Овсяные хлопья - 80 г (бета-глюканы)
• Грецкие орехи - 40 г (Омега-3 - 9г/100г)
• Черника - 100 г (антоцианы - 160мг/100г)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (натуральные сахара)
• Молоко - 200 мл

Приготовление (10 минут):
1. Овсянку варить с молоком 7 минут
2. Добавить измельченные грецкие орехи
3. Подавать с черникой, корицей и медом

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация медленных углеводов + Омега-3 обеспечивает стабильную энергию для мозга и улучшает нейронные связи.
"""
        benefits = """• 🌾 Овсянка - стабильная энергия для мозга
• 🌰 Грецкие орехи - Омега-3 для нейронов
• 🫐 Черника - антоцианы для памяти
• 🍯 Мед - быстрая энергия без спадов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ОВСЯНКА ДЛЯ ФОКУСА С ГРЕЦКИМИ ОРЕХАМИ",
            content, "neuro_breakfast", benefits
        )

    def generate_memory_smoothie(self):
        content = """
🧠 СМУЗИ ДЛЯ ПАМЯТИ: ШПИНАТ + ЧЕРНИКА + ЛЬНЯНОЕ СЕМЯ
КБЖУ: 280 ккал • Белки: 12г • Жиры: 10г • Углеводы: 35г

Ингредиенты на 2 порции:
• Шпинат - 100 г (фолат - 194мкг/100г)
• Черника - 150 г (флавоноиды)
• Банан - 1 шт (калий - 358мг)
• Льняное семя - 2 ст.л. (Омега-3 - 22г/100г)
• Греческий йогурт - 100 г (белок - 10г/100г)
• Вода - 200 мл

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу после приготовления

🎯 НАУЧНЫЙ ПОДХОД:
Флавоноиды черники улучшают нейронные связи, а Омега-3 из льняного семени поддерживает структурную целостность мозга.
"""
        benefits = """• 🥬 Шпинат - фолат для когнитивных функций
• 🫐 Черника - флавоноиды для нейропластичности
• 🌱 Льняное семя - Омега-3 для мембран нейронов
• 🍌 Банан - калий для нервной проводимости"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 СМУЗИ ДЛЯ ПАМЯТИ: ШПИНАТ + ЧЕРНИКА",
            content, "neuro_breakfast", benefits
        )

    def generate_neuro_omelette(self):
        content = """
💫 НЕЙРО-ОМЛЕТ С БРОККОЛИ И СЕМЕНАМИ ТЫКВЫ
КБЖУ: 320 ккал • Белки: 24г • Жиры: 22г • Углеводы: 8г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин)
• Брокколи - 150 г (витамин K - 101мкг/100г)
• Семена тыквы - 30 г (цинк - 7.6мг/100г)
• Сыр фета - 50 г (кальций)
• Куркума - 1 ч.л. (куркумин)
• Оливковое масло - 1 ч.л.

Приготовление (15 минут):
1. Брокколи отварить 5 минут, мелко нарезать
2. Яйца взбить с куркумой
3. Обжарить брокколи на оливковом масле
4. Залить яйцами, добавить сыр и семена
5. Готовить под крышкой 7-8 минут

🎯 НАУЧНЫЙ ПОДХОД:
Цинк из тыквенных семечек критически важен для синаптической передачи, а куркумин обладает нейропротекторными свойствами.
"""
        benefits = """• 🥚 Яйца - холин для нейромедиаторов
• 🥦 Брокколи - витамин K для когнитивных функций
• 🎃 Семена тыквы - цинк для синапсов
• 💛 Куркума - куркумин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 НЕЙРО-ОМЛЕТ С БРОККОЛИ И СЕМЕНАМИ",
            content, "neuro_breakfast", benefits
        )

    def generate_brain_pancakes(self):
        content = """
🥞 БЛИНЫ ДЛЯ МОЗГА С ЧЕРНИКОЙ И ГРЕЦКИМИ ОРЕХАМИ
КБЖУ: 340 ккал • Белки: 18г • Жиры: 16г • Углеводы: 32г

Ингредиенты на 2 порции:
• Овсяная мука - 100 г (клетчатка)
• Яйца - 2 шт (холин)
• Грецкие орехи - 40 г (Омега-3)
• Черника - 100 г (антиоксиданты)
• Творог - 100 г (казеин)
• Разрыхлитель - 1 ч.л.

Приготовление (20 минут):
1. Смешать муку, яйца, творог, разрыхлитель
2. Добавить измельченные орехи
3. Жарить на антипригарной сковороде
4. Подавать со свежей черникой

🎯 НАУЧНЫЙ ПОДХОД:
Медленные углеводы из овсяной муки обеспечивают стабильную энергию, а творог дает длительное чувство сытости.
"""
        benefits = """• 🌾 Овсяная мука - медленные углеводы
• 🥚 Яйца - строительный материал для мозга
• 🌰 Грецкие орехи - Омега-3 для нейронов
• 🫐 Черника - защита от окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 БЛИНЫ ДЛЯ МОЗГА С ЧЕРНИКОЙ И ОРЕХАМИ",
            content, "neuro_breakfast", benefits
        )

    def generate_cognitive_yogurt(self):
        content = """
🍦 ЙОГУРТ ДЛЯ КОГНИТИВНЫХ ФУНКЦИЙ С СЕМЕНАМИ
КБЖУ: 290 ккал • Белки: 20г • Жиры: 15г • Углеводы: 18г

Ингредиенты на 2 порции:
• Греческий йогурт - 300 г (пробиотики)
• Семена чиа - 2 ст.л. (Омега-3)
• Семена льна - 1 ст.л. (лигнаны)
• Миндаль - 30 г (витамин E)
• Мед - 1 ст.л. (антимикробные свойства)
• Корица - 1 ч.л.

Приготовление (2 минуты):
1. Йогурт смешать с семенами
2. Добавить измельченный миндаль
3. Заправить медом и корицей
4. Дать постоять 5 минут для набухания семян

🎯 НАУЧНЫЙ ПОДХОД:
Пробиотики из йогурта поддерживают ось "кишечник-мозг", а витамин E из миндаля защищает нейроны от повреждений.
"""
        benefits = """• 🥛 Греческий йогурт - пробиотики для оси кишечник-мозг
• 🌱 Семена чиа - Омега-3 для нейропластичности
• 🌰 Миндаль - витамин E для защиты нейронов
• 🍯 Мед - натуральные пребиотики"""
        
        return self.visual_manager.generate_attractive_post(
            "🍦 ЙОГУРТ ДЛЯ КОГНИТИВНЫХ ФУНКЦИЙ",
            content, "neuro_breakfast", benefits
        )

    def generate_neuro_muesli(self):
        content = """
🌾 НЕЙРО-МЮСЛИ С ОРЕХАМИ И СУХОФРУКТАМИ
КБЖУ: 370 ккал • Белки: 14г • Жиры: 18г • Углеводы: 40г

Ингредиенты на 2 порции:
• Овсяные хлопья - 80 г (бета-глюканы)
• Миндаль - 30 г (витамин E)
• Грецкие орехи - 30 г (Омега-3)
• Изюм - 40 г (бор - 2.2мг/100г)
• Семена подсолнечника - 20 г (витамин E)
• Яблоко - 1 шт (кверцетин)

Приготовление (5 минут):
1. Смешать все сухие ингредиенты
2. Добавить натертое яблоко
3. Залить молоком или йогуртом
4. Дать настояться 3-5 минут

🎯 НАУЧНЫЙ ПОДХОД:
Бор из изюма улучшает электрическую активность мозга, а кверцетин из яблок защищает нейроны от воспаления.
"""
        benefits = """• 🌾 Овсяные хлопья - энергия для умственной работы
• 🌰 Орехи - комплекс нейропротекторов
• 🍇 Изюм - бор для электрической активности
• 🍎 Яблоко - кверцетин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 НЕЙРО-МЮСЛИ С ОРЕХАМИ И СУХОФРУКТАМИ",
            content, "neuro_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_brain_salmon_bowl(self):
        content = """
🧠 ЛОСОСЕВАЯ ЧАША ДЛЯ МОЗГА С КИНОА
КБЖУ: 420 ккал • Белки: 35г • Жиры: 18г • Углеводы: 32г

Ингредиенты на 2 порции:
• Лосось - 200 г (Омега-3 - 2.5г/100г)
• Киноа - 100 г (белок - 14г/100г)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Шпинат - 100 г (железо - 2.7мг/100г)
• Морковь - 1 шт (витамин A)
• Лимонный сок - 2 ст.л.

Приготовление (20 минут):
1. Киноа варить 15 минут
2. Лосось запечь 12 минут при 200°C
3. Овощи нарезать, смешать с киноа
4. Добавить лосось, полить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Полноценный белок киноа содержит все незаменимые аминокислоты, необходимые для синтеза нейромедиаторов.
"""
        benefits = """• 🐟 Лосось - ДГК для нейронов
• 🌾 Киноа - полный набор аминокислот
• 🥑 Авокадо - полезные жиры для мембран
• 🥬 Шпинат - железо для оксигенации мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЛОСОСЕВАЯ ЧАША ДЛЯ МОЗГА С КИНОА",
            content, "neuro_lunch", benefits
        )

    def generate_cognitive_chicken(self):
        content = """
💪 КУРИЦА ДЛЯ КОГНИТИВНЫХ ФУНКЦИЙ С БРОККОЛИ
КБЖУ: 380 ккал • Белки: 40г • Жиры: 15г • Углеводы: 18г

Ингредиенты на 2 порции:
• Куриная грудка - 250 г (триптофан)
• Брокколи - 200 г (глюкозинолаты)
• Грецкие орехи - 40 г (мелатонин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

Приготовление (25 минут):
1. Курицу нарезать, обжарить 10 минут
2. Добавить брокколи и чеснок
3. Тушить 10 минут под крышкой
4. В конце добавить орехи и лимонный сок

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из курицы является предшественником серотонина, регулирующего настроение и когнитивные функции.
"""
        benefits = """• 🍗 Курица - триптофан для серотонина
• 🥦 Брокколи - глюкозинолаты для детокса
• 🌰 Грецкие орехи - мелатонин для циклов сна
• 🧄 Чеснок - аллицин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 КУРИЦА ДЛЯ КОГНИТИВНЫХ ФУНКЦИЙ С БРОККОЛИ",
            content, "neuro_lunch", benefits
        )

    def generate_neuro_salad(self):
        content = """
🥗 НЕЙРО-САЛАТ С ТУНЦОМ И ОВОЩАМИ
КБЖУ: 320 ккал • Белки: 28г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 2 порции:
• Тунец консервированный - 200 г (Омега-3)
• Руккола - 100 г (нитраты)
• Помидоры черри - 150 г (ликопин)
• Огурцы - 1 шт (вода 95%)
• Оливки - 50 г (мононенасыщенные жиры)
• Оливковое масло - 2 ст.л.

Приготовление (10 минут):
1. Овощи нарезать, смешать с рукколой
2. Добавить тунец и оливки
3. Заправить оливковым маслом
4. Аккуратно перемешать

🎯 НАУЧНЫЙ ПОДХОД:
Нитраты из рукколы улучшают кровоснабжение мозга, а ликопин из помидоров защищает от окислительного стресса.
"""
        benefits = """• 🐟 Тунец - Омега-3 для нейропластичности
• 🥬 Руккола - нитраты для кровоснабжения мозга
• 🍅 Помидоры - ликопин против стресса
• 🫒 Оливки - полезные жиры для мембран"""
        
        return self.visual_manager.generate_attractive_post(
            "🥗 НЕЙРО-САЛАТ С ТУНЦОМ И ОВОЩАМИ",
            content, "neuro_lunch", benefits
        )

    def generate_focus_soup(self):
        content = """
🎯 СУП ДЛЯ КОНЦЕНТРАЦИИ С ЧЕЧЕВИЦЕЙ И КУРКУМОЙ
КБЖУ: 350 ккал • Белки: 22г • Жиры: 12г • Углеводы: 42г

Ингредиенты на 2 порции:
• Чечевица - 150 г (фолат - 181мкг/100г)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 2 стебля (апигенин)
• Куркума - 2 ч.л. (куркумин)
• Кокосовое молоко - 200 мл (МСТ)
• Овощной бульон - 500 мл

Приготовление (25 минут):
1. Овощи нарезать кубиками
2. Обжарить с куркумой 3 минуты
3. Добавить чечевицу и бульон
4. Варить 20 минут, в конце добавить кокосовое молоко

🎯 НАУЧНЫЙ ПОДХОД:
Куркумин усиливает нейрогенез и улучшает когнитивные функции через активацию BDNF (нейротрофического фактора мозга).
"""
        benefits = """• 🌱 Чечевица - фолат для синтеза нейромедиаторов
• 🥕 Морковь - бета-каротин для антиоксидантной защиты
• 🥬 Сельдерей - апигенин против воспаления
• 💛 Куркума - куркумин для нейрогенеза"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 СУП ДЛЯ КОНЦЕНТРАЦИИ С ЧЕЧЕВИЦЕЙ И КУРКУМОЙ",
            content, "neuro_lunch", benefits
        )

    def generate_mind_bowl(self):
        content = """
🧠 ЧАША ДЛЯ УМА С НУТОМ И ШПИНАТОМ
КБЖУ: 380 ккал • Белки: 24г • Жиры: 16г • Углеводы: 38г

Ингредиенты на 2 порции:
• Нут - 200 г (магний - 48мг/100г)
• Шпинат - 150 г (лютеин)
• Сладкий картофель - 200 г (витамин A)
• Авокадо - 1/2 шт (мононенасыщенные жиры)
• Тахини - 2 ст.л. (кальций)
• Лимонный сок - 2 ст.л.

Приготовление (20 минут):
1. Нут и сладкий картофель запечь
2. Шпинат обжарить 2 минуты
3. Смешать все ингредиенты
4. Заправить тахини и лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Магний из нута регулирует NMDA-рецепторы, критически важные для синаптической пластичности и обучения.
"""
        benefits = """• 🫘 Нут - магний для синаптической пластичности
• 🥬 Шпинат - лютеин для когнитивных функций
• 🍠 Сладкий картофель - витамин A для зрения
• 🥑 Авокадо - полезные жиры для мембран"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЧАША ДЛЯ УМА С НУТОМ И ШПИНАТОМ",
            content, "neuro_lunch", benefits
        )

    def generate_brain_wrap(self):
        content = """
🌯 БУРРИТО ДЛЯ МОЗГА С ИНДЕЙКОЙ И АВОКАДО
КБЖУ: 360 ккал • Белки: 30г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 2 порции:
• Цельнозерновые лепешки - 2 шт (клетчатка)
• Грудка индейки - 200 г (триптофан)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Шпинат - 100 г (железо)
• Нут - 100 г (растительный белок)
• Греческий йогурт - 100 г

Приготовление (15 минут):
1. Индейку обжарить 8 минут
2. Авокадо размять вилкой
3. Собрать буррито: лепешка + авокадо + индейка + овощи
4. Завернуть и поджарить с двух сторон

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из индейки способствует синтезу серотонина, улучшающего настроение и когнитивные функции.
"""
        benefits = """• 🦃 Индейка - триптофан для серотонина
• 🥑 Авокадо - полезные жиры для гормонов
• 🥬 Шпинат - железо для оксигенации
• 🌾 Цельнозерновые лепешки - медленные углеводы"""
        
        return self.visual_manager.generate_attractive_post(
            "🌯 БУРРИТО ДЛЯ МОЗГА С ИНДЕЙКОЙ И АВОКАДО",
            content, "neuro_lunch", benefits
        )

    def generate_neuro_stir_fry(self):
        content = """
🔥 НЕЙРО-СТИР-ФРАЙ С ТОФУ И ОВОЩАМИ
КБЖУ: 340 ккал • Белки: 26г • Жиры: 20г • Углеводы: 18г

Ингредиенты на 2 порции:
• Тофу - 250 г (изофлавоны)
• Брокколи - 200 г (сульфорафан)
• Грибы шиитаке - 150 г (бета-глюканы)
• Болгарский перец - 1 шт (витамин C)
• Имбирь - 2 см (гингерол)
• Кунжутное масло - 1 ст.л.

Приготовление (20 минут):
1. Тофу обжарить до золотистой корочки
2. Добавить овощи и имбирь
3. Жарить на сильном огне 8-10 минут
4. Полить кунжутным маслом

🎯 НАУЧНЫЙ ПОДХОД:
Сульфорафан из брокколи активирует Nrf2 путь, усиливая антиоксидантную защиту клеток мозга.
"""
        benefits = """• 🧈 Тофу - изофлавоны для гормонального баланса
• 🥦 Брокколи - сульфорафан для детокса
• 🍄 Грибы - бета-глюканы для иммунитета
• 🟤 Имбирь - противовоспалительный эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 НЕЙРО-СТИР-ФРАЙ С ТОФУ И ОВОЩАМИ",
            content, "neuro_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_memory_fish(self):
        content = """
🧠 УЖИН ДЛЯ ПАМЯТИ: ЗАПЕЧЕННАЯ РЫБА С ОВОЩАМИ
КБЖУ: 380 ккал • Белки: 30г • Жиры: 20г • Углеводы: 18г

Ингредиенты на 2 порции:
• Белая рыба (треска) - 250 г (йод - 110мкг/100г)
• Брокколи - 200 г (витамин K - 101мкг/100г)
• Сладкий перец - 2 шт (витамин C - 128мг/100г)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Лимон - 1/2 шт

Приготовление (25 минут):
1. Рыбу посолить, поперчить
2. Овощи нарезать, смешать с чесноком
3. Запекать 20 минут при 180°C
4. Полить лимонным соком перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Йод из трески критически важен для функции щитовидной железы, которая регулирует метаболизм мозга.
"""
        benefits = """• 🐟 Треска - йод для функции щитовидки
• 🥦 Брокколи - витамин K для когнитивных функций
• 🌶️ Перец - витамин C для антиоксидантной защиты
• 🧄 Чеснок - противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УЖИН ДЛЯ ПАМЯТИ: ЗАПЕЧЕННАЯ РЫБА",
            content, "neuro_dinner", benefits
        )

    def generate_brain_omelette(self):
        content = """
💫 ВЕЧЕРНИЙ ОМЛЕТ ДЛЯ МОЗГА С ГРИБАМИ
КБЖУ: 310 ккал • Белки: 26г • Жиры: 20г • Углеводы: 8г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин)
• Шампиньоны - 200 г (витамин D)
• Шпинат - 100 г (лютеин)
• Семена тыквы - 2 ст.л. (цинк)
• Сыр - 50 г (триптофан)
• Оливковое масло - 1 ч.л.

Приготовление (15 минут):
1. Грибы обжарить 5 минут
2. Добавить шпинат, тушить 2 минуты
3. Залить взбитыми яйцами
4. Посыпать сыром и семенами
5. Готовить под крышкой 8 минут

🎯 НАУЧНЫЙ ПОДХОД:
Витамин D из грибов регулирует экспрессию генов, связанных с нейропластичностью и когнитивными функциями.
"""
        benefits = """• 🥚 Яйца - холин для ацетилхолина
• 🍄 Грибы - витамин D для нейропластичности
• 🥬 Шпинат - лютеин для зрения
• 🎃 Семена тыквы - цинк для синапсов"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 ВЕЧЕРНИЙ ОМЛЕТ ДЛЯ МОЗГА С ГРИБАМИ",
            content, "neuro_dinner", benefits
        )

    def generate_neuro_stew(self):
        content = """
🍲 НЕЙРО-РАГУ С ГОВЯДИНОЙ И ОВОЩАМИ
КБЖУ: 350 ккал • Белки: 32г • Жиры: 18г • Углеводы: 15г

Ингредиенты на 2 порции:
• Говядина - 250 г (железо - 2.6мг/100г)
• Морковь - 2 шт (бета-каротин)
• Цукини - 1 шт (калий)
• Лук - 1 шт (кверцетин)
• Томатная паста - 2 ст.л. (ликопин)
• Тимьян - 1 ч.л.

Приготовление (40 минут):
1. Говядину обжарить до румяной корочки
2. Добавить овощи и томатную пасту
3. Тушить 35 минут на медленном огне
4. Добавить тимьян в конце

🎯 НАУЧНЫЙ ПОДХОД:
Гемовое железо из говядины обеспечивает оптимальную оксигенацию мозга, улучшая когнитивные функции.
"""
        benefits = """• 🥩 Говядина - гемовое железо для крови
• 🥕 Морковь - бета-каротин для зрения
• 🥒 Цукини - калий для нервной системы
• 🧅 Лук - кверцетин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 НЕЙРО-РАГУ С ГОВЯДИНОЙ И ОВОЩАМИ",
            content, "neuro_dinner", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_brain_nutrition_advice(self):
        content = """
🧠 ПИТАНИЕ ДЛЯ МОЗГА: 5 ГЛАВНЫХ ПРИНЦИПОВ

💡 НАУЧНО ОБОСНОВАННЫЕ СОВЕТЫ:

1. 🥑 ПОЛЕЗНЫЕ ЖИРЫ
• Омега-3 улучшают нейропластичность на 28%
• Источники: лосось, грецкие орехи, семена льна
• Доза: 2-3 порции рыбы в неделю

2. 🍫 АНТИОКСИДАНТЫ  
• Защищают клетки мозга от окислительного стресса
• Источники: ягоды, темный шоколад, зеленый чай
• Доза: горсть ягод ежедневно

3. 🥚 ХОЛИН
• Предшественник ацетилхолина - нейромедиатора памяти
• Источники: яйца, печень, арахис
• Доза: 2-3 яйца в день

4. 💧 ВОДНЫЙ БАЛАНС
• Обезвоживание снижает когнитивные функции на 30%
• Норма: 30 мл на 1 кг веса
• Контроль: светлая моча

5. 🕒 РЕЖИМ ПИТАНИЯ
• Завтрак в течение часа после пробуждения
• Перерывы 3-4 часа между приемами пищи
• Легкий ужин за 3 часа до сна

🎯 ПРАКТИЧЕСКОЕ ЗАДАНИЕ:
Добавьте один продукт для мозга в каждый прием пищи сегодня!
"""
        benefits = """• 🧠 Улучшение памяти и концентрации на 40%
• 💡 Повышение продуктивности и креативности
• 🛡️ Защита от возрастных когнитивных нарушений
• ⚡ Быстрая реакция и ясность мышления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 СОВЕТ: ПИТАНИЕ ДЛЯ МОЗГА И ПАМЯТИ",
            content, "neuro_advice", benefits
        )

    def generate_focus_foods_advice(self):
        content = """
🎯 ПРОДУКТЫ ДЛЯ ФОКУСА И КОНЦЕНТРАЦИИ

🔬 НАУЧНЫЕ ФАКТЫ:

1. 🫐 ЧЕРНИКА - КОРОЛЕВА МОЗГА
• Улучшает нейронные связи
• Повышает обучаемость на 23%
• Защищает от возрастных изменений

2. 🌰 ГРЕЦКИЕ ОРЕХИ - ПИТАНИЕ ДЛЯ НЕЙРОНОВ
• Форма напоминает мозг не случайно
• Содержат мелатонин для регуляции сна
• Улучшают когнитивные функции

3. 🥬 ШПИНАТ - СИЛА ФОЛАТА
• Критически важен для синтеза ДНК
• Поддерживает нейрогенез
• Защищает от когнитивного спада

4. 🍫 ТЕМНЫЙ ШОКОЛАД - РАДОСТЬ ДЛЯ МОЗГА
• Теобромин улучшает настроение
• Флавоноиды усиливают кровоток
• Кофеин мягко стимулирует

5. 🥚 ЯЙЦА - ТОПЛИВО ДЛЯ ПАМЯТИ
• Холин - строительный материал
• Лютеин - защита зрения
• Белок - стабильная энергия

🎯 ПРАКТИКА: Съедайте горсть орехов при умственной работе!
"""
        benefits = """• 🎯 Улучшение концентрации и внимания
• 🧠 Ускорение обработки информации
• 💡 Повышение креативного мышления
• ⏱️ Увеличение продуктивного времени"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 СОВЕТ: ПРОДУКТЫ ДЛЯ ФОКУСА И КОНЦЕНТРАЦИИ",
            content, "neuro_advice", benefits
        )

    def generate_memory_boost_advice(self):
        content = """
🧠 КАК УЛУЧШИТЬ ПАМЯТЬ С ПОМОЩЬЮ ПИТАНИЯ

🎯 5 КЛЮЧЕВЫХ СТРАТЕГИЙ:

1. 🎯 ХОЛИН - ТОПЛИВО ДЛЯ ПАМЯТИ
• Ацетилхолин - главный нейромедиатор памяти
• Источники: яйца (желток), печень, арахис
• Доза: 550 мг/день для мужчин, 425 мг/день для женщин

2. 💫 ОМЕГА-3 - СТРОИТЕЛЬНЫЙ МАТЕРИАЛ
• ДГК составляет 30% серого вещества мозга
• Улучшает нейропластичность
• Источники: лосось, сардины, грецкие орехи

3. 🛡️ АНТИОКСИДАНТЫ - ЗАЩИТА
• Защищают гиппокамп - центр памяти
• Уменьшают возрастное снижение когнитивных функций
• Источники: ягоды, зеленый чай, куркума

4. 🔋 ГЛЮКОЗА - ЭНЕРГИЯ
• Мозг потребляет 20% всей глюкозы организма
• Медленные углеводы = стабильная энергия
• Источники: овсянка, киноа, сладкий картофель

5. 💧 ГИДРАТАЦИЯ - ПРОВОДНИК
• Обезвоживание ухудшает кратковременную память
• Вода необходима для производства нейромедиаторов
• Норма: 8 стаканов в день

🎯 ПРАКТИКА: Начните день с яичницы с авокадо!
"""
        benefits = """• 🧠 Улучшение кратковременной памяти на 25%
• 💡 Ускорение обработки информации
• 🛡️ Защита от возрастных нарушений
• ⚡ Повышение умственной энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 СОВЕТ: КАК УЛУЧШИТЬ ПАМЯТЬ ПИТАНИЕМ",
            content, "neuro_advice", benefits
        )
    # 💪 ВТОРНИК - БЕЛКОВЫЙ ДЕНЬ (28 РЕЦЕПТОВ)
    
    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_muscle_breakfast(self):
        content = """
💪 БЕЛКОВЫЙ ЗАВТРАК: ТВОРОЖНАЯ ЗАПЕКАНКА
КБЖУ: 350 ккал • Белки: 32г • Жиры: 12г • Углеводы: 25г

Ингредиенты на 2 порции:
• Творог 5% - 300 г (казеин - 28г/100г)
• Яйца - 2 шт (белок - 13г/100г)
• Овсяные хлопья - 40 г (клетчатка - 10г/100г)
• Ягоды - 150 г (антиоксиданты)
• Мед - 1 ст.л.
• Ванильный экстракт - 1 ч.л.

Приготовление (25 минут):
1. Творог смешать с яйцами и овсянкой
2. Добавить ваниль и мед
3. Выложить в форму, сверху ягоды
4. Запекать 20 минут при 180°C

🎯 НАУЧНЫЙ ПОДХОД:
Казеин из творога обеспечивает медленное высвобождение аминокислот в течение 6-8 часов, поддерживая синтез мышечного белка.
"""
        benefits = """• 🧀 Творог - медленный белок для сытости
• 🥚 Яйца - полноценный аминокислотный профиль
• 🌾 Овсянка - энергия для тренировок
• 🍓 Ягоды - антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ ЗАВТРАК ДЛЯ МЫШЦ",
            content, "protein_breakfast", benefits
        )

    def generate_energy_protein_shake(self):
        content = """
⚡️ ЭНЕРГЕТИЧЕСКИЙ ПРОТЕИНОВЫЙ КОКТЕЙЛЬ
КБЖУ: 320 ккал • Белки: 35г • Жиры: 8г • Углеводы: 25г

Ингредиенты на 2 порции:
• Сывороточный протеин - 2 мерные ложки (24г белка)
• Банан - 1 шт (калий - 358мг)
• Миндальное молоко - 300 мл (витамин E)
• Арахисовая паста - 2 ст.л. (белок - 25г/100г)
• Семена чиа - 1 ст.л. (Омега-3)
• Льняное семя - 1 ст.л. (лигнаны)

Приготовление (3 минуты):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу после приготовления

🎯 НАУЧНЫЙ ПОДХОД:
Сывороточный протеин имеет высокий показатель усвояемости (PDCAAS = 1.0) и быстро насыщает кровь аминокислотами.
"""
        benefits = """• 🥛 Сывороточный протеин - быстрые аминокислоты
• 🍌 Банан - калий для мышечных сокращений
• 🥜 Арахисовая паста - растительный белок
• 🌱 Семена - Омега-3 против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡️ ЭНЕРГЕТИЧЕСКИЙ ПРОТЕИНОВЫЙ КОКТЕЙЛЬ",
            content, "protein_breakfast", benefits
        )

    def generate_satiety_omelette(self):
        content = """
🍳 ОМЛЕТ СЫТНОСТИ С ИНДЕЙКОЙ И ОВОЩАМИ
КБЖУ: 380 ккал • Белки: 42г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 4 шт (лейцин - 1.1г/шт)
• Грудка индейки - 150 г (белок - 29г/100г)
• Шпинат - 100 г (железо)
• Помидоры - 2 шт (ликопин)
• Сыр моцарелла - 50 г (кальций)
• Оливковое масло - 1 ч.л.

Приготовление (20 минут):
1. Индейку нарезать, обжарить 8 минут
2. Добавить овощи, тушить 5 минут
3. Залить взбитыми яйцами
4. Посыпать сыром, готовить 7 минут

🎯 НАУЧНЫЙ ПОДХОД:
Лейцин из яиц активирует mTOR путь - ключевой регулятор синтеза мышечного белка.
"""
        benefits = """• 🥚 Яйца - лейцин для активации mTOR
• 🦃 Индейка - нежирный животный белок
• 🥬 Шпинат - железо для оксигенации мышц
• 🧀 Сыр - кальций для сокращений"""
        
        return self.visual_manager.generate_attractive_post(
            "🍳 ОМЛЕТ СЫТНОСТИ С ИНДЕЙКОЙ И ОВОЩАМИ",
            content, "protein_breakfast", benefits
        )

    def generate_protein_waffles(self):
        content = """
🧇 ПРОТЕИНОВЫЕ ВАФЛИ С ТВОРОГОМ И ЯГОДАМИ
КБЖУ: 340 ккал • Белки: 38г • Жиры: 10г • Углеводы: 28г

Ингредиенты на 2 порции:
• Творог - 200 г (казеин)
• Яичные белки - 6 шт (белок - 11г/100г)
• Овсяная мука - 60 г (клетчатка)
• Разрыхлитель - 1 ч.л.
• Ваниль - 1 ч.л.
• Ягоды - 150 г для подачи

Приготовление (20 минут):
1. Творог смешать с яичными белками
2. Добавить муку и разрыхлитель
3. Выпекать в вафельнице 5-7 минут
4. Подавать со свежими ягодами

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация казеина (медленный белок) и сывороточного белка (быстрый белок) обеспечивает оптимальный аминокислотный профиль.
"""
        benefits = """• 🧀 Творог - казеин для длительного насыщения
• 🥚 Яичные белки - чистый протеин
• 🌾 Овсяная мука - медленные углеводы
• 🍓 Ягоды - антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧇 ПРОТЕИНОВЫЕ ВАФЛИ С ТВОРОГОМ И ЯГОДАМИ",
            content, "protein_breakfast", benefits
        )

    def generate_amino_toast(self):
        content = """
🍞 АМИНО-ТОСТ С ЯЙЦОМ-ПАШОТ И АВОКАДО
КБЖУ: 360 ккал • Белки: 28г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 2 порции:
• Цельнозерновой хлеб - 4 ломтика (клетчатка)
• Яйца - 4 шт (все незаменимые аминокислоты)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Лосось слабосоленый - 100 г (Омега-3)
• Лимонный сок - 1 ст.л.
• Специи по вкусу

Приготовление (15 минут):
1. Хлеб поджарить
2. Приготовить яйца-пашот (3 минуты в кипящей воде)
3. Авокадо размять с лимонным соком
4. Собрать тосты: хлеб + авокадо + лосось + яйцо

🎯 НАУЧНЫЙ ПОДХОД:
Яйца содержат все 9 незаменимых аминокислот в идеальном соотношении для синтеза мышечного белка.
"""
        benefits = """• 🥚 Яйца - полный аминокислотный профиль
• 🥑 Авокадо - полезные жиры для гормонов
• 🐟 Лосось - Омега-3 против воспаления
• 🍞 Цельнозерновой хлеб - клетчатка для ЖКТ"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 АМИНО-ТОСТ С ЯЙЦОМ-ПАШОТ И АВОКАДО",
            content, "protein_breakfast", benefits
        )

    def generate_anabolic_porridge(self):
        content = """
🥣 АНАБОЛИЧЕСКАЯ КАША С ТВОРОГОМ И ОРЕХАМИ
КБЖУ: 390 ккал • Белки: 36г • Жиры: 15г • Углеводы: 30г

Ингредиенты на 2 порции:
• Гречневая крупа - 100 г (белок - 13г/100г)
• Творог - 200 г (казеин)
• Миндаль - 40 г (витамин E)
• Кунжут - 2 ст.л. (кальций - 975мг/100г)
• Корица - 1 ч.л.
• Мед - 1 ст.л.

Приготовление (20 минут):
1. Гречку варить 15 минут
2. Смешать с творогом и орехами
3. Добавить кунжут и корицу
4. Заправить медом перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Гречка содержит рутин, который улучшает усвоение белка и обладает противовоспалительными свойствами.
"""
        benefits = """• 🌾 Гречка - растительный белок + рутин
• 🧀 Творог - животный белок для баланса
• 🌰 Миндаль - витамин E для защиты клеток
• 🌱 Кунжут - кальций для нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🥣 АНАБОЛИЧЕСКАЯ КАША С ТВОРОГОМ И ОРЕХАМИ",
            content, "protein_breakfast", benefits
        )

    def generate_repair_smoothie(self):
        content = """
🔧 ВОССТАНОВИТЕЛЬНЫЙ СМУЗИ ПОСЛЕ ТРЕНИРОВКИ
КБЖУ: 310 ккал • Белки: 32г • Жиры: 8г • Углеводы: 28г

Ингредиенты на 2 порции:
• Греческий йогурт - 250 г (пробиотики)
• Сывороточный протеин - 1 мерная ложка
• Киви - 2 шт (витамин C - 93мг/шт)
• Шпинат - 50 г (магний)
• Имбирь - 1 см (гингерол)
• Вода - 200 мл

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной массы
3. Подавать сразу после тренировки

🎯 НАУЧНЫЙ ПОДХОД:
Сочетание быстрого протеина и витамина C ускоряет восстановление мышечных волокон после микротравм.
"""
        benefits = """• 🥛 Греческий йогурт - пробиотики + белок
• 💪 Сывороточный протеин - быстрые аминокислоты
• 🥝 Киви - витамин C для восстановления
• 🥬 Шпинат - магний для расслабления мышц"""
        
        return self.visual_manager.generate_attractive_post(
            "🔧 ВОССТАНОВИТЕЛЬНЫЙ СМУЗИ ПОСЛЕ ТРЕНИРОВКИ",
            content, "protein_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_amino_acids_bowl(self):
        content = """
🧬 АМИНОКИСЛОТНАЯ ЧАША С КУРИЦЕЙ И КИНОА
КБЖУ: 450 ккал • Белки: 48г • Жиры: 15г • Углеводы: 35г

Ингредиенты на 2 порции:
• Куриная грудка - 300 г (белок - 31г/100г)
• Киноа - 120 г (лизин - 0.2г/100г)
• Нут - 150 г (растительный белок)
• Болгарский перец - 2 шт (витамин C)
• Зелень - 50 г (хлорофилл)
• Оливковое масло - 1 ст.л.

Приготовление (25 минут):
1. Курицу запечь 20 минут при 200°C
2. Киноа и нут отварить
3. Овощи нарезать кубиками
4. Смешать все ингредиенты, заправить маслом

🎯 НАУЧНЫЙ ПОДХОД:
Лизин из киноа дополняет аминокислотный профиль курицы, создавая идеальную комбинацию для синтеза белка.
"""
        benefits = """• 🍗 Курица - высококачественный животный белок
• 🌾 Киноа - лизин для баланса аминокислот
• 🌱 Нут - растительный белок для разнообразия
• 🌶️ Перец - витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "🧬 АМИНОКИСЛОТНАЯ ЧАША С КУРИЦЕЙ И КИНОА",
            content, "protein_lunch", benefits
        )

    def generate_anabolic_lunch(self):
        content = """
💥 АНАБОЛИЧЕСКИЙ ОБЕД С ГОВЯДИНОЙ И БОБОВЫМИ
КБЖУ: 480 ккал • Белки: 52г • Жиры: 18г • Углеводы: 28г

Ингредиенты на 2 порции:
• Говядина - 250 г (железо - 2.6мг/100г)
• Чечевица - 150 г (белок - 9г/100г)
• Брокколи - 200 г (витамин C)
• Морковь - 1 шт (бета-каротин)
• Чеснок - 3 зубчика
• Томатная паста - 2 ст.л.

Приготовление (30 минут):
1. Говядину тушить 25 минут с томатной пастой
2. Чечевицу отварить отдельно
3. Овощи приготовить на пару
4. Подавать все компоненты вместе

🎯 НАУЧНЫЙ ПОДХОД:
Гемовое железо из говядины усваивается на 25% лучше, чем негемовое из растений, обеспечивая оптимальную оксигенацию мышц.
"""
        benefits = """• 🥩 Говядина - гемовое железо для крови
• 🌱 Чечевица - растительный белок + клетчатка
• 🥦 Брокколи - витамин C для иммунитета
• 🧄 Чеснок - противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "💥 АНАБОЛИЧЕСКИЙ ОБЕД С ГОВЯДИНОЙ И БОБОВЫМИ",
            content, "protein_lunch", benefits
        )

    def generate_repair_salad(self):
        content = """
🔩 САЛАТ ВОССТАНОВЛЕНИЯ С ТУНЦОМ И ЯЙЦОМ
КБЖУ: 380 ккал • Белки: 44г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 2 порции:
• Тунец консервированный - 200 г (селен - 36мкг/100г)
• Яйца вареные - 4 шт (цистеин)
• Спаржа - 150 г (глутатион)
• Руккола - 100 г (нитраты)
• Оливки - 50 г (витамин E)
• Лимонный сок - 2 ст.л.

Приготовление (15 минут):
1. Яйца отварить, нарезать четвертинками
2. Спаражу бланшировать 3 минуты
3. Смешать все ингредиенты
4. Заправить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Селен из тунца активирует глутатионпероксидазу - ключевой антиоксидантный фермент, защищающий клетки от окислительного стресса.
"""
        benefits = """• 🐟 Тунец - селен для антиоксидантной защиты
• 🥚 Яйца - цистеин для синтеза глутатиона
• 🌱 Спаржа - глутатион для детокса
• 🥬 Руккола - нитраты для кровотока"""
        
        return self.visual_manager.generate_attractive_post(
            "🔩 САЛАТ ВОССТАНОВЛЕНИЯ С ТУНЦОМ И ЯЙЦОМ",
            content, "protein_lunch", benefits
        )

    def generate_muscle_wrap(self):
        content = """
🌯 МЫШЕЧНЫЙ РУЛЕТ С ИНДЕЙКОЙ И ХУМУСОМ
КБЖУ: 420 ккал • Белки: 38г • Жиры: 16г • Углеводы: 32г

Ингредиенты на 2 порции:
• Цельнозерновые лепешки - 2 шт
• Грудка индейки - 250 г (белок)
• Хумус - 100 г (растительный белок)
• Огурцы - 1 шт (вода)
• Помидоры - 2 шт (ликопин)
• Шпинат - 100 г (железо)

Приготовление (15 минут):
1. Индейку запечь и нарезать полосками
2. Намазать лепешки хумусом
3. Выложить овощи и индейку
4. Плотно завернуть и поджарить

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация животного и растительного белка обеспечивает полный спектр аминокислот для оптимального синтеза мышечного белка.
"""
        benefits = """• 🦃 Индейка - нежирный животный белок
• 🫕 Хумус - растительный белок + клетчатка
• 🥒 Огурцы - гидратация организма
• 🥬 Шпинат - железо для энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🌯 МЫШЕЧНЫЙ РУЛЕТ С ИНДЕЙКОЙ И ХУМУСОМ",
            content, "protein_lunch", benefits
        )

    def generate_power_soup(self):
        content = """
💪 СИЛОВОЙ СУП С КУРИЦЕЙ И ФАСОЛЬЮ
КБЖУ: 390 ккал • Белки: 42г • Жиры: 12г • Углеводы: 28г

Ингредиенты на 2 порции:
• Куриная грудка - 250 г (белок)
• Фасоль - 150 г (растительный белок)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 2 стебля (натрий)
• Лук - 1 шт (кверцетин)
• Куриный бульон - 500 мл

Приготовление (30 минут):
1. Курицу отварить, нарезать кубиками
2. Овощи нарезать, обжарить 5 минут
3. Добавить фасоль и бульон
4. Варить 20 минут

🎯 НАУЧНЫЙ ПОДХОД:
Натрий из сельдерея поддерживает электролитный баланс, критически важный для мышечных сокращений.
"""
        benefits = """• 🍗 Курица - качественный животный белок
• 🫘 Фасоль - растительный белок + клетчатка
• 🥕 Морковь - антиоксиданты для восстановления
• 🥬 Сельдерей - электролиты для мышц"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СИЛОВОЙ СУП С КУРИЦЕЙ И ФАСОЛЬЮ",
            content, "protein_lunch", benefits
        )

    def generate_protein_plate(self):
        content = """
🍽️ БЕЛКОВАЯ ТАРЕЛКА С РЫБОЙ И ОВОЩАМИ
КБЖУ: 400 ккал • Белки: 46г • Жиры: 18г • Углеводы: 15г

Ингредиенты на 2 порции:
• Филе белой рыбы - 300 г (йод)
• Брокколи - 200 г (витамин C)
• Цветная капуста - 200 г (глюкозинолаты)
• Спаржа - 150 г (фолат)
• Лимон - 1/2 шт
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Рыбу запечь 15 минут
2. Овощи приготовить на пару
3. Полить лимонным соком и маслом
4. Подавать как сборную тарелку

🎯 НАУЧНЫЙ ПОДХОД:
Йод из рыбы необходим для оптимальной функции щитовидной железы, регулирующей метаболизм белков.
"""
        benefits = """• 🐟 Рыба - йод для щитовидной железы
• 🥦 Брокколи - витамин C для иммунитета
• 🥦 Цветная капуста - детокс для организма
• 🌱 Спаржа - фолат для синтеза ДНК"""
        
        return self.visual_manager.generate_attractive_post(
            "🍽️ БЕЛКОВАЯ ТАРЕЛКА С РЫБОЙ И ОВОЩАМИ",
            content, "protein_lunch", benefits
        )

    def generate_amino_burger(self):
        content = """
🍔 АМИНО-БУРГЕР С ГОВЯДИНОЙ И СЫРОМ
КБЖУ: 460 ккал • Белки: 44г • Жиры: 22г • Углеводы: 25г

Ингредиенты на 2 порции:
• Говяжий фарш - 300 г (креатин)
• Цельнозерновые булочки - 2 шт
• Сыр чеддер - 80 г (кальций)
• Помидоры - 2 шт (ликопин)
• Листья салата - 4 шт
• Авокадо - 1/2 шт (полезные жиры)

Приготовление (25 минут):
1. Сформировать котлеты из фарша
2. Обжарить по 4 минуты с каждой стороны
3. Собрать бургеры: булка + салат + котлета + сыр + овощи
4. Подавать сразу

🎯 НАУЧНЫЙ ПОДХОД:
Креатин из говядины повышает продуктивность высокоинтенсивных тренировок и ускоряет восстановление.
"""
        benefits = """• 🥩 Говядина - креатин для силы
• 🧀 Сыр - кальций для костей
• 🥑 Авокадо - полезные жиры для гормонов
• 🍅 Помидоры - антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍔 АМИНО-БУРГЕР С ГОВЯДИНОЙ И СЫРОМ",
            content, "protein_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_night_protein(self):
        content = """
🌙 НОЧНОЙ БЕЛОК: ТВОРОГ С КОРИЦЕЙ И ОРЕХАМИ
КБЖУ: 320 ккал • Белки: 38г • Жиры: 12г • Углеводы: 15г

Ингредиенты на 2 порции:
• Творог 5% - 400 г (казеин)
• Миндаль - 30 г (триптофан)
• Кедровые орехи - 20 г (цинк)
• Корица - 2 ч.л. (полифенолы)
• Ванильный экстракт - 1 ч.л.
• Стевия по вкусу

Приготовление (5 минут):
1. Творог смешать с корицей и ванилью
2. Добавить измельченные орехи
3. Подсластить стевией при необходимости
4. Подавать за 1-2 часа до сна

🎯 НАУЧНЫЙ ПОДХОД:
Казеин из творога медленно усваивается в течение 6-8 часов, обеспечивая постоянное поступление аминокислот во время сна.
"""
        benefits = """• 🧀 Творог - казеин для ночного синтеза белка
• 🌰 Миндаль - триптофан для мелатонина
• 🎄 Кедровые орехи - цинк для тестостерона
• 🟤 Корица - регуляция уровня сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 НОЧНОЙ БЕЛОК: ТВОРОГ С КОРИЦЕЙ И ОРЕХАМИ",
            content, "protein_dinner", benefits
        )

    def generate_recovery_dinner(self):
        content = """
🔄 УЖИН ВОССТАНОВЛЕНИЯ С ИНДЕЙКОЙ И САЛАТОМ
КБЖУ: 350 ккал • Белки: 42г • Жиры: 14г • Углеводы: 12г

Ингредиенты на 2 порции:
• Грудка индейки - 300 г (триптофан)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Огурцы - 2 шт (вода 95%)
• Помидоры черри - 150 г (ликопин)
• Руккола - 100 г (кальций)
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Индейку запечь 18 минут при 180°C
2. Овощи нарезать для салата
3. Авокадо нарезать ломтиками
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из индейки является предшественником серотонина и мелатонина, улучшая качество сна и восстановления.
"""
        benefits = """• 🦃 Индейка - триптофан для сна и настроения
• 🥑 Авокадо - полезные жиры для гормонов
• 🥒 Огурцы - гидратация на клеточном уровне
• 🍅 Помидоры - ликопин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ВОССТАНОВЛЕНИЯ С ИНДЕЙКОЙ И САЛАТОМ",
            content, "protein_dinner", benefits
        )

    def generate_lean_protein_meal(self):
        content = """
🥩 ПОСТНЫЙ БЕЛКОВЫЙ УЖИН С РЫБОЙ И СПАРЖЕЙ
КБЖУ: 320 ккал • Белки: 40г • Жиры: 12г • Углеводы: 8г

Ингредиенты на 2 порции:
• Филе белой рыбы - 300 г (йод)
• Спаржа - 200 г (фолат)
• Лимон - 1/2 шт (витамин C)
• Чеснок - 3 зубчика (аллицин)
• Укроп - 20 г (антиоксиданты)
• Оливковое масло - 1 ч.л.

Приготовление (20 минут):
1. Рыбу посолить, поперчить
2. Спаржу бланшировать 4 минуты
3. Запекать рыбу со спаржей 15 минут
4. Полить лимонным соком перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Йод из белой рыбы необходим для оптимальной функции щитовидной железы, регулирующей метаболизм белков.
"""
        benefits = """• 🐟 Белая рыба - йод для щитовидной железы
• 🌱 Спаржа - фолат для синтеза ДНК
• 🍋 Лимон - витамин C для иммунитета
• 🧄 Чеснок - противовоспалительный эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🥩 ПОСТНЫЙ БЕЛКОВЫЙ УЖИН С РЫБОЙ И СПАРЖЕЙ",
            content, "protein_dinner", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_protein_science_advice(self):
        content = """
💪 НАУКА БЕЛКА: КАК ОПТИМИЗИРОВАТЬ СИНТЕЗ МЫШЕЧНОГО БЕЛКА

🔬 КЛЮЧЕВЫЕ ПРИНЦИПЫ:

1. 🎯 ЛЕЙЦИНОВЫЙ ПОРОГ
• 2.5-3г лейцина за прием пищи
• Активирует mTOR путь синтеза белка
• Источники: яйца, сывороточный протеин, курица

2. ⏱️ ВРЕМЯ ПРИЕМА
• 20-40г белка каждые 3-4 часа
• Анаболическое окно: 2 часа после тренировки
• Ночной белок: казеин перед сном

3. 🧬 КАЧЕСТВО БЕЛКА
• PDCAAS - показатель усвояемости
• Животные белки: 1.0 (максимум)
• Растительные: комбинируйте для полноценности

4. 💧 ГИДРАТАЦИЯ
• 1г белка требует 7мл воды
• Обезвоживание снижает синтез на 30%
• Контролируйте цвет мочи

5. 🔄 РАЗНООБРАЗИЕ
• Комбинируйте животные и растительные источники
• Разные аминокислотные профили
• Снижение риска дефицита

🎯 ПРАКТИКА: Съедайте белок в каждый прием пищи!
"""
        benefits = """• 💪 Увеличение мышечной массы на 15-20%
• 🔄 Ускорение восстановления после нагрузок
• 🛡️ Укрепление иммунной системы
• ⚡ Повышение энергетического обмена"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СОВЕТ: НАУКА СИНТЕЗА МЫШЕЧНОГО БЕЛКА",
            content, "protein_advice", benefits
        )

    def generate_muscle_health_advice(self):
        content = """
🏋️ БЕЛОК ДЛЯ МЫШЕЧНОГО ЗДОРОВЬЯ ПОСЛЕ 30

📊 ВОЗРАСТНЫЕ ОСОБЕННОСТИ:

1. 🎯 САРКОПЕНИЯ ПРОФИЛАКТИКА
• После 30 теряем 3-5% мышц каждое десятилетие
• Белок замедляет потерю мышечной массы
• Силовые тренировки + питание = результат

2. 🥩 УВЕЛИЧЕНИЕ НОРМЫ
• Молодые: 1.2-1.6г/кг
• После 50: 1.6-2.0г/кг
• При тренировках: до 2.2г/кг

3. 🧬 КОСТНАЯ ТКАНЬ
• Белок улучшает плотность костей
• Снижает риск остеопороза
• Кальций + белок = синергия

4. 💊 СИНЕРГИЯ НУТРИЕНТОВ
• Витамин D улучжает усвоение белка
• Магний для мышечного расслабления
• Калий для сокращений

5. 🍽️ ПРАКТИЧЕСКИЕ СОВЕТЫ
• Завтрак: 30г белка
• Обед: 35-40г белка  
• Ужин: 25-30г белка
• Перекусы: 15-20г белка

🎯 ЗАДАНИЕ: Рассчитайте свою суточную норму белка!
"""
        benefits = """• 💪 Сохранение мышечной массы с возрастом
• 🦴 Укрепление костной ткани
• ⚡ Повышение энергии и выносливости
• 🛡️ Профилактика возрастных заболеваний"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ СОВЕТ: БЕЛОК ДЛЯ МЫШЕЧНОГО ЗДОРОВЬЯ",
            content, "protein_advice", benefits
        )

    def generate_amino_guide_advice(self):
        content = """
🧬 АМИНОКИСЛОТНЫЙ ГИД: КЛЮЧ К МЫШЕЧНОМУ РОСТУ

🔬 9 НЕЗАМЕНИМЫХ АМИНОКИСЛОТ:

1. 💪 BCAA (лейцин, изолейцин, валин)
• Лейцин - главный активатор mTOR
• 2.5г за прием для максимального синтеза
• Источники: сывороточный протеин, курица, яйца

2. 🎯 ЛИЗИН
• Критичен для синтеза карнитина
• Улучшает усвоение кальция
• Источники: рыба, мясо, бобовые

3. 🔋 МЕТИОНИН
• Предшественник цистеина
• Участвует в детоксе
• Источники: яйца, рыба, мясо

4. 🧠 ТРИПТОФАН
• Предшественник серотонина
• Регулирует сон и настроение
• Источники: индейка, бананы, овсянка

5. 💫 ПОЛНЫЕ БЕЛКИ
• Животные источники: полный набор
• Растительные: комбинируйте (рис + бобовые)
• Оптимальное соотношение 1:1

🎯 ПРАКТИКА: Комбинируйте разные источники белка!
"""
        benefits = """• 💪 Максимальный синтез мышечного белка
• 🔄 Ускоренное восстановление
• 🧠 Улучшение настроения и сна
• 🛡️ Укрепление иммунной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🧬 СОВЕТ: АМИНОКИСЛОТНЫЙ ГИД ДЛЯ РОСТА МЫШЦ",
            content, "protein_advice", benefits
        )
    # 🥬 СРЕДА - ОВОЩНОЙ ДЕНЬ (28 РЕЦЕПТОВ)
    
    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_green_smoothie_bowl(self):
        content = """
🥬 ЗЕЛЕНЫЙ СМУЗИ-БОУЛ ДЕТОКС
КБЖУ: 280 ккал • Белки: 12г • Жиры: 8г • Углеводы: 42г

Ингредиенты на 2 порции:
• Шпинат - 100 г (хлорофилл)
• Киви - 2 шт (витамин C - 93мг/шт)
• Банан - 1 шт (калий)
• Авокадо - 1/2 шт (здоровые жиры)
• Семена чиа - 1 ст.л. (Омега-3)
• Вода - 150 мл

Топпинги:
• Ягоды годжи - 2 ст.л.
• Кокосовая стружка - 1 ст.л.
• Семена подсолнечника - 1 ст.л.

Приготовление (8 минут):
1. Все ингредиенты взбить в блендере
2. Вылить в миску, украсить топпингами
3. Подавать сразу

🎯 НАУЧНЫЙ ПОДХОД:
Хлорофилл из зелени связывает токсины и тяжелые металлы, способствуя естественному очищению организма.
"""
        benefits = """• 🥬 Шпинат - хлорофилл для детокса
• 🥝 Киви - витамин C для иммунитета
• 🥑 Авокадо - полезные жиры для усвоения витаминов
• 🌱 Семена чиа - клетчатка для ЖКТ"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ЗЕЛЕНЫЙ СМУЗИ-БОУЛ ДЕТОКС",
            content, "veggie_breakfast", benefits
        )

    def generate_vegetable_omelette(self):
        content = """
🍳 ОВОЩНОЙ ОМЛЕТ С ЦУККИНИ И ПЕРЦЕМ
КБЖУ: 290 ккал • Белки: 20г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин)
• Цукини - 1 шт (калий - 261мг)
• Болгарский перец - 1 шт (витамин C)
• Помидоры черри - 100 г (ликопин)
• Лук - 1/2 шт (кверцетин)
• Оливковое масло - 1 ч.л.

Приготовление (20 минут):
1. Овощи нарезать кубиками
2. Обжарить 5 минут на оливковом масле
3. Залить взбитыми яйцами
4. Готовить под крышкой 10-12 минут

🎯 НАУЧНЫЙ ПОДХОД:
Кверцетин из лука обладает мощными антиоксидантными свойствами и защищает клетки от окислительного стресса.
"""
        benefits = """• 🥚 Яйца - белок для сытости
• 🥒 Цукини - калий для водного баланса
• 🌶️ Перец - витамин C для коллагена
• 🧅 Лук - кверцетин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍳 ОВОЩНОЙ ОМЛЕТ С ЦУККИНИ И ПЕРЦЕМ",
            content, "veggie_breakfast", benefits
        )

    def generate_detox_breakfast(self):
        content = """
🌿 ДЕТОКС-ЗАВТРАК: КАПУСТНЫЙ СМУЗИ С ИМБИРЕМ
КБЖУ: 220 ккал • Белки: 10г • Жиры: 6г • Углеводы: 35г

Ингредиенты на 2 порции:
• Капуста кале - 100 г (глюкозинолаты)
• Яблоко - 1 шт (пектин)
• Лимон - 1/2 шт (витамин C)
• Имбирь - 2 см (гингерол)
• Мята - 10 листьев (ментол)
• Вода - 200 мл

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Процедить при желании
4. Подавать сразу

🎯 НАУЧНЫЙ ПОДХОД:
Глюкозинолаты из капусты активируют ферменты детокса II фазы в печени, усиливая выведение токсинов.
"""
        benefits = """• 🥬 Капуста кале - глюкозинолаты для детокса
• 🍎 Яблоко - пектин для тяжелых металлов
• 🍋 Лимон - витамин C для глутатиона
• 🟤 Имбирь - гингерол против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ДЕТОКС-ЗАВТРАК: КАПУСТНЫЙ СМУЗИ С ИМБИРЕМ",
            content, "veggie_breakfast", benefits
        )

    def generate_veggie_scramble(self):
        content = """
🍲 СКРЭМБЛ С ОВОЩАМИ И ШПИНАТОМ
КБЖУ: 310 ккал • Белки: 22г • Жиры: 20г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 4 шт (лютеин)
• Шпинат - 100 г (железо)
• Грибы - 150 г (витамин D)
• Помидоры - 2 шт (ликопин)
• Чеснок - 2 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

Приготовление (15 минут):
1. Грибы и чеснок обжарить 5 минут
2. Добавить шпинат и помидоры
3. Влить взбитые яйца
4. Готовить, помешивая, 7-8 минут

🎯 НАУЧНЫЙ ПОДХОД:
Лютеин из яиц и шпината накапливается в макуле глаза, защищая от возрастной дегенерации желтого пятна.
"""
        benefits = """• 🥚 Яйца - лютеин для зрения
• 🥬 Шпинат - железо для энергии
• 🍄 Грибы - витамин D для иммунитета
• 🧄 Чеснок - аллицин для сердца"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 СКРЭМБЛ С ОВОЩАМИ И ШПИНАТОМ",
            content, "veggie_breakfast", benefits
        )

    def generate_cleansing_bowl(self):
        content = """
💚 ОЧИЩАЮЩАЯ ЧАША С КИНОА И ОВОЩАМИ
КБЖУ: 340 ккал • Белки: 14г • Жиры: 12г • Углеводы: 45г

Ингредиенты на 2 порции:
• Киноа - 100 г (белок)
• Брокколи - 150 г (сульфорафан)
• Морковь - 1 шт (бета-каротин)
• Свекла - 1 шт (нитраты)
• Авокадо - 1/2 шт (жиры)
• Лимонный сок - 2 ст.л.

Приготовление (25 минут):
1. Киноа отварить 15 минут
2. Овощи приготовить на пару
3. Смешать все ингредиенты
4. Заправить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Сульфорафан из брокколи активирует Nrf2 путь - главный регулятор антиоксидантной защиты клеток.
"""
        benefits = """• 🌾 Киноа - полноценный растительный белок
• 🥦 Брокколи - сульфорафан для детокса
• 🥕 Морковь - бета-каротин для зрения
• 🟣 Свекла - нитраты для кровотока"""
        
        return self.visual_manager.generate_attractive_post(
            "💚 ОЧИЩАЮЩАЯ ЧАША С КИНОА И ОВОЩАМИ",
            content, "veggie_breakfast", benefits
        )

    def generate_fiber_toast(self):
        content = """
🍞 ТОСТ С ОВОЩНЫМ ТОППИНГОМ И ХУМУСОМ
КБЖУ: 300 ккал • Белки: 15г • Жиры: 14г • Углеводы: 32г

Ингредиенты на 2 порции:
• Цельнозерновой хлеб - 4 ломтика (клетчатка)
• Хумус - 100 г (растительный белок)
• Огурцы - 1 шт (вода)
• Редька - 1 шт (глюкозинолаты)
• Руккола - 50 г (нитраты)
• Лимонный сок - 1 ст.л.

Приготовление (10 минут):
1. Хлеб поджарить
2. Намазать хумус
3. Овощи нарезать тонкими ломтиками
4. Выложить на тосты, полить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Клетчатка из цельнозернового хлеба служит пребиотиком, питающим полезную микрофлору кишечника.
"""
        benefits = """• 🍞 Цельнозерновой хлеб - клетчатка для микробиома
• 🫕 Хумус - растительный белок + клетчатка
• 🥒 Огурцы - гидратация + кремний
• 🟢 Редька - глюкозинолаты для печени"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 ТОСТ С ОВОЩНЫМ ТОППИНГОМ И ХУМУСОМ",
            content, "veggie_breakfast", benefits
        )

    def generate_antioxidant_smoothie(self):
        content = """
🛡️ АНТИОКСИДАНТНЫЙ СМУЗИ С ЯГОДАМИ И КАПУСТОЙ
КБЖУ: 270 ккал • Белки: 11г • Жиры: 7г • Углеводы: 42г

Ингредиенты на 2 порции:
• Капуста кале - 80 г (кверцетин)
• Черника - 100 г (антоцианы)
• Малина - 100 г (эллагиновая кислота)
• Банан - 1 шт (калий)
• Семена льна - 1 ст.л. (лигнаны)
• Вода - 200 мл

Приготовление (5 минут):
1. Все ингредиенты взбить в блендере
2. Подавать сразу после приготовления

🎯 НАУЧНЫЙ ПОДХОД:
Антоцианы из ягод и кверцетин из капусты синергетически усиливают антиоксидантную защиту клеток.
"""
        benefits = """• 🥬 Капуста кале - кверцетин против воспаления
• 🫐 Черника - антоцианы для мозга
• 🍓 Малина - эллагиновая кислота против рака
• 🌱 Семена льна - лигнаны для гормонального баланса"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ АНТИОКСИДАНТНЫЙ СМУЗИ С ЯГОДАМИ И КАПУСТОЙ",
            content, "veggie_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_rainbow_salad(self):
        content = """
🌈 РАДУЖНЫЙ САЛАТ С 7 ОВОЩАМИ
КБЖУ: 280 ккал • Белки: 12г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 2 порции:
• Красный: помидоры - 150 г (ликопин)
• Оранжевый: морковь - 1 шт (бета-каротин)
• Желтый: перец - 1 шт (витамин C)
• Зеленый: огурец - 1 шт (кремний)
• Синий: краснокачанная капуста - 100 г (антоцианы)
• Фиолетовый: свекла - 1 шт (бетаин)
• Белый: редис - 100 г (глюкозинолаты)

Заправка:
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.
• Горчица - 1 ч.л.
• Мед - 1 ч.л.

Приготовление (15 минут):
1. Все овощи нарезать
2. Смешать в большой миске
3. Приготовить заправку
4. Полить салат перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Разноцветные овощи содержат разные фитонутриенты, обеспечивая комплексную защиту от различных заболеваний.
"""
        benefits = """• 🍅 Помидоры - ликопин для простаты
• 🥕 Морковь - бета-каротин для зрения
• 🌶️ Перец - витамин C для иммунитета
• 🟣 Свекла - бетаин для печени"""
        
        return self.visual_manager.generate_attractive_post(
            "🌈 РАДУЖНЫЙ САЛАТ С 7 ОВОЩАМИ",
            content, "veggie_lunch", benefits
        )

    def generate_veggie_stew(self):
        content = """
🍲 ОВОЩНОЕ РАГУ С БОБОВЫМИ И ТРАВАМИ
КБЖУ: 320 ккал • Белки: 18г • Жиры: 10г • Углеводы: 45г

Ингредиенты на 2 порции:
• Кабачки - 2 шт (калий)
• Баклажаны - 1 шт (насунин)
• Фасоль - 150 г (растительный белок)
• Лук - 1 шт (кверцетин)
• Чеснок - 3 зубчика (аллицин)
• Томатная паста - 2 ст.л.
• Специи: орегано, базилик

Приготовление (30 минут):
1. Овощи нарезать кубиками
2. Обжарить лук и чеснок
3. Добавить остальные овощи и фасоль
4. Тушить 25 минут под крышкой

🎯 НАУЧНЫЙ ПОДХОД:
Насунин из баклажанов защищает мембраны клеток от повреждения свободными радикалами.
"""
        benefits = """• 🥒 Кабачки - калий для давления
• 🍆 Баклажаны - насунин для клеточных мембран
• 🫘 Фасоль - растительный белок + клетчатка
• 🧄 Чеснок - аллицин для сердечно-сосудистой системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 ОВОЩНОЕ РАГУ С БОБОВЫМИ И ТРАВАми",
            content, "veggie_lunch", benefits
        )

    def generate_cleansing_soup(self):
        content = """
💧 ОЧИЩАЮЩИЙ СУП ИЗ СЕЛЬДЕРЕЯ И ПЕТРУШКИ
КБЖУ: 180 ккал • Белки: 8г • Жиры: 6г • Углеводы: 25г

Ингредиенты на 2 порции:
• Сельдерей - 4 стебля (апигенин)
• Петрушка - 50 г (хлорофилл)
• Лук-порей - 1 шт (пребиотики)
• Картофель - 2 шт (калий)
• Морковь - 1 шт (бета-каротин)
• Овощной бульон - 500 мл

Приготовление (25 минут):
1. Овощи нарезать
2. Варить в бульоне 20 минут
3. Добавить петрушку в конце
4. Подавать теплым

🎯 НАУЧНЫЙ ПОДХОД:
Апигенин из сельдерея обладает противовоспалительными свойствами и поддерживает здоровье нервной системы.
"""
        benefits = """• 🥬 Сельдерей - апигенин против воспаления
• 🌿 Петрушка - хлорофилл для детокса
• 🟢 Лук-порей - пребиотики для микробиома
• 🥔 Картофель - калий для баланса жидкости"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ОЧИЩАЮЩИЙ СУП ИЗ СЕЛЬДЕРЕЯ И ПЕТРУШКИ",
            content, "veggie_lunch", benefits
        )

    def generate_veggie_wrap(self):
        content = """
🌯 ОВОЩНОЙ РУЛЕТ С АВОКАДО И ПРОРОСТКАМИ
КБЖУ: 290 ккал • Белки: 14г • Жиры: 16г • Углеводы: 28г

Ингредиенты на 2 порции:
• Цельнозерновые лепешки - 2 шт
• Авокадо - 1 шт (мононенасыщенные жиры)
• Морковь - 1 шт (бета-каротин)
• Огурцы - 1 шт (вода)
• Проростки подсолнечника - 50 г (ферменты)
• Тахини - 2 ст.л. (кальций)

Приготовление (10 минут):
1. Авокадо размять вилкой
2. Овощи нарезать соломкой
3. Намазать лепешки авокадо и тахини
4. Выложить овощи, завернуть

🎯 НАУЧНЫЙ ПОДХОД:
Ферменты из проростков улучшают пищеварение и увеличивают биодоступность питательных веществ.
"""
        benefits = """• 🥑 Авокадо - полезные жиры для усвоения витаминов
• 🥕 Морковь - бета-каротин для иммунитета
• 🌱 Проростки - ферменты для пищеварения
• 🫕 Тахини - кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🌯 ОВОЩНОЙ РУЛЕТ С АВОКАДО И ПРОРОСТКАМИ",
            content, "veggie_lunch", benefits
        )

    def generate_veggie_burger(self):
        content = """
🍔 ВЕГЕТАРИАНСКИЙ БУРГЕР С ЧЕЧЕВИЦЕЙ
КБЖУ: 350 ккал • Белки: 22г • Жиры: 14г • Углеводы: 38г

Ингредиенты на 2 порции:
• Чечевица - 150 г (белок)
• Морковь - 1 шт (бета-каротин)
• Лук - 1/2 шт (кверцетин)
• Овсяные хлопья - 50 г (клетчатка)
• Специи: кумин, кориандр
• Цельнозерновая булочка - 2 шт

Приготовление (30 минут):
1. Чечевицу отварить до мягкости
2. Овощи натереть на терке
3. Смешать все ингредиенты, сформировать котлеты
4. Обжарить по 4 минуты с каждой стороны

🎯 НАУЧНЫЙ ПОДХОД:
Клетчатка из чечевицы и овсянки служит пребиотиком, поддерживая здоровый микробиом кишечника.
"""
        benefits = """• 🌱 Чечевица - растительный белок + клетчатка
• 🥕 Морковь - антиоксиданты для защиты
• 🌾 Овсянка - бета-глюканы для холестерина
• 🧅 Лук - противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🍔 ВЕГЕТАРИАНСКИЙ БУРГЕР С ЧЕЧЕВИЦЕЙ",
            content, "veggie_lunch", benefits
        )

    def generate_veggie_pasta(self):
        content = """
🍝 ОВОЩНАЯ ПАСТА С ЦУККИНИ И БАЗИЛИКОМ
КБЖУ: 320 ккал • Белки: 16г • Жиры: 12г • Углеводы: 42г

Ингредиенты на 2 порции:
• Цельнозерновая паста - 120 г (клетчатка)
• Цукини - 2 шт (калий)
• Помидоры черри - 200 г (ликопин)
• Базилик - 30 г (эфирные масла)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 2 ст.л.

Приготовление (20 минут):
1. Пасту отварить al dente
2. Цукини нарезать спиралью
3. Обжарить овощи с чесноком
4. Смешать с пастой, добавить базилик

🎯 НАУЧНЫЙ ПОДХОД:
Эфирные масла базилика обладают антимикробными свойствами и поддерживают здоровье пищеварительной системы.
"""
        benefits = """• 🍝 Цельнозерновая паста - медленные углеводы
• 🥒 Цукини - калий для водного баланса
• 🍅 Помидоры - ликопин для простаты
• 🌿 Базилик - антимикробные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🍝 ОВОЩНАЯ ПАСТА С ЦУККИНИ И БАЗИЛИКОМ",
            content, "veggie_lunch", benefits
        )

    def generate_veggie_stir_fry(self):
        content = """
🔥 ОВОЩНОЙ СТИР-ФРАЙ С ТОФУ И БРОККОЛИ
КБЖУ: 340 ккал • Белки: 24г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 2 порции:
• Тофу - 200 г (изофлавоны)
• Брокколи - 200 г (сульфорафан)
• Морковь - 1 шт (бета-каротин)
• Грибы шиитаке - 100 г (бета-глюканы)
• Имбирь - 2 см (гингерол)
• Кунжутное масло - 1 ст.л.

Приготовление (20 минут):
1. Тофу обжарить до золотистой корочки
2. Добавить овощи и имбирь
3. Жарить на сильном огне 8-10 минут
4. Полить кунжутным маслом

🎯 НАУЧНЫЙ ПОДХОД:
Бета-глюканы из грибов шиитаке усиливают иммунный ответ и обладают противовоспалительными свойствами.
"""
        benefits = """• 🧈 Тофу - изофлавоны для гормонального баланса
• 🥦 Брокколи - сульфорафан против рака
• 🍄 Грибы - бета-глюканы для иммунитета
• 🟤 Имбирь - противовоспалительный эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ОВОЩНОЙ СТИР-ФРАЙ С ТОФУ И БРОККОЛИ",
            content, "veggie_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_roasted_vegetables(self):
        content = """
🔥 ЗАПЕЧЕННЫЕ ОВОЩИ С ТРАВАМИ И ОЛИВКОВЫМ МАСЛОМ
КБЖУ: 290 ккал • Белки: 10г • Жиры: 16г • Углеводы: 30г

Ингредиенты на 2 порции:
• Сладкий картофель - 2 шт (бета-каротин)
• Цветная капуста - 1/2 кочана (глюкозинолаты)
• Брокколи - 200 г (сульфорафан)
• Морковь - 2 шт (витамин A)
• Лук красный - 1 шт (кверцетин)
• Оливковое масло - 2 ст.л.
• Розмарин, тимьян

Приготовление (35 минут):
1. Овощи нарезать
2. Смешать с маслом и травами
3. Запекать 30 минут при 200°C
4. Подавать теплыми

🎯 НАУЧНЫЙ ПОДХОД:
Запекание сохраняет больше питательных веществ по сравнению с варкой, особенно жирорастворимые витамины.
"""
        benefits = """• 🍠 Сладкий картофель - бета-каротин для иммунитета
• 🥦 Цветная капуста - глюкозинолаты для детокса
• 🥦 Брокколи - сульфорафан против рака
• 🥕 Морковь - витамин A для кожи"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЗАПЕЧЕННЫЕ ОВОЩИ С ТРАВАМИ И ОЛИВКОВЫМ МАСЛОМ",
            content, "veggie_dinner", benefits
        )

    def generate_plant_based_dinner(self):
        content = """
🌱 РАСТИТЕЛЬНЫЙ УЖИН С ТОФУ И ОВОЩАМИ
КБЖУ: 340 ккал • Белки: 22г • Жиры: 18г • Углеводы: 25г

Ингредиенты на 2 порции:
• Тофу - 200 г (изофлавоны)
• Шпинат - 150 г (железо)
• Грибы шиитаке - 100 г (бета-глюканы)
• Спаржа - 100 г (глутатион)
• Чеснок - 3 зубчика
• Кунжутное масло - 1 ст.л.

Приготовление (20 минут):
1. Тофу обжарить до золотистой корочки
2. Добавить овощи, тушить 10 минут
3. Приправить чесноком и маслом
4. Подавать горячим

🎯 НАУЧНЫЙ ПОДХОД:
Изофлавоны из тофу обладают мягким эстрогеноподобным действием, полезным для гормонального баланса.
"""
        benefits = """• 🧈 Тофу - изофлавоны для гормонального баланса
• 🥬 Шпинат - железо для энергии
• 🍄 Грибы шиитаке - бета-глюканы для иммунитета
• 🌱 Спаржа - глутатион для детокса"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 РАСТИТЕЛЬНЫЙ УЖИН С ТОФУ И ОВОЩАМИ",
            content, "veggie_dinner", benefits
        )

    def generate_fiber_rich_meal(self):
        content = """
🌾 БОГАТАЯ КЛЕТЧАТКОЙ ЧАША С ОВОЩАМИ И СЕМЕНАМИ
КБЖУ: 310 ккал • Белки: 15г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 2 порции:
• Булгур - 100 г (клетчатка)
• Артишоки - 2 шт (инулин)
• Спаржа - 100 г (пребиотики)
• Авокадо - 1/2 шт (жиры)
• Семена подсолнечника - 2 ст.л. (витамин E)
• Лимонный сок - 2 ст.л.

Приготовление (25 минут):
1. Булгур отварить
2. Артишоки и спаржу приготовить на пару
3. Смешать все ингредиенты
4. Заправить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Инулин из артишоков служит пребиотиком, selectively питающим бифидобактерии в кишечнике.
"""
        benefits = """• 🌾 Булгур - клетчатка для пищеварения
• 🎨 Артишоки - инулин для бифидобактерий
• 🌱 Спаржа - пребиотики для микробиома
• 🥑 Авокадо - полезные жиры для усвоения витаминов"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 БОГАТАЯ КЛЕТЧАТКОЙ ЧАША С ОВОЩАМИ И СЕМЕНАМИ",
            content, "veggie_dinner", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_fiber_benefits_advice(self):
        content = """
🌿 СИЛА КЛЕТЧАТКИ: КАК ОВОЩИ МЕНЯЮТ ЗДОРОВЬЕ

🔬 НАУЧНЫЕ ФАКТЫ:

1. 🦠 МИКРОБИОМ
• 25-30г клетчатки в день
• Пребиотики питают полезные бактерии
• Короткоцепочечные жирные кислоты (КЦЖК)

2. 🩺 СЕРДЦЕ И СОСУДЫ
• Снижение холестерина на 15-20%
• Контроль артериального давления
• Уменьшение риска инсульта

3. 🍽️ ПИЩЕВАРЕНИЕ
• Профилактика запоров
• Снижение риска дивертикулеза
• Поддержка здорового веса

4. 🩸 САХАР В КРОВИ
• Медленное высвобождение глюкозы
• Улучшение инсулиновой чувствительности
• Профилактика диабета 2 типа

5. 🎯 ПРАКТИЧЕСКИЕ СОВЕТЫ
• Начинайте день с овощей
• Добавляйте овощи в каждый прием пищи
• Экспериментируйте с разными видами
• Сочетайте сырые и приготовленные

🎯 ЗАДАНИЕ: Съедайте 5 разных овощей сегодня!
"""
        benefits = """• 🦠 Улучшение состава микробиома на 40%
• 🩸 Снижение уровня холестерина
• 🍽️ Нормализация пищеварения
• 🩺 Укрепление сердечно-сосудистой системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 СОВЕТ: СИЛА ОВОЩЕЙ И КЛЕТЧАТКИ",
            content, "veggie_advice", benefits
        )

    def generate_antioxidant_guide_advice(self):
        content = """
🛡️ АНТИОКСИДАНТНЫЙ ЩИТ: КАК ЗАЩИТИТЬ КЛЕТКИ

🌈 ЦВЕТНАЯ ЗАЩИТА:

1. 🔴 КРАСНЫЕ (ликопин)
• Помидоры, арбуз, грейпфрут
• Защита простаты и кожи
• Усиление при тепловой обработке

2. 🟠 ОРАНЖЕВЫЕ (бета-каротин)
• Морковь, тыква, сладкий картофель
• Здоровье зрения и иммунитета
• Преобразуется в витамин A

3. 🟡 ЖЕЛТЫЕ (лютеин)
• Кукуруза, желтый перец, лимоны
• Защита макулы глаза
• Фильтрация синего света

4. 🟢 ЗЕЛЕНЫЕ (хлорофилл)
• Шпинат, капуста, брокколи
• Детокс и очищение
• Противовоспалительное действие

5. 🔵 СИНИЕ/ФИОЛЕТОВЫЕ (антоцианы)
• Черника, баклажаны, краснокачанная капуста
• Защита мозга и сердца
• Улучшение памяти

🎯 ПРАКТИКА: Создайте радугу на тарелке!
"""
        benefits = """• 🛡️ Защита клеток от окислительного стресса
• 🧠 Улучшение когнитивных функций
• 🩺 Снижение риска хронических заболеваний
• 💪 Укрепление иммунной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ СОВЕТ: АНТИОКСИДАНТНЫЙ ЩИТ ОВОЩЕЙ",
            content, "veggie_advice", benefits
        )

    def generate_detox_science_advice(self):
        content = """
🧹 НАУКА ДЕТОКСА: КАК ОВОЩИ ОЧИЩАЮТ ОРГАНИЗМ

🔬 ЕСТЕСТВЕННЫЕ МЕХАНИЗМЫ:

1. 🍃 ХЛОРОФИЛЛ
• Связывает тяжелые металлы
• Ускоряет выведение токсинов
• Улучшает оксигенацию крови

2. 🥦 ГЛЮКОЗИНОЛАТЫ
• Активируют ферменты детокса II фазы
• Усиливают выведение канцерогенов
• Защищают от рака

3. 🧅 СЕРАСОДЕРЖАЩИЕ СОЕДИНЕНИЯ
• Чеснок, лук, капуста
• Поддерживают синтез глутатиона
• Усиливают детокс в печени

4. 🍊 ФЛАВОНОИДЫ
• Улучшают функцию печени
• Защищают клетки от повреждений
• Усиливают антиоксидантную защиту

5. 💧 ВОДА И КЛЕТЧАТКА
• Выводят водорастворимые токсины
• Поддерживают регулярный стул
• Предотвращают реабсорбцию токсинов

🎯 ПРАКТИКА: Добавьте зеленые овощи в каждый прием пищи!
"""
        benefits = """• 🧹 Естественное очищение организма
• 🍃 Улучшение функции печени
• 🛡️ Защита от токсинов окружающей среды
• 💪 Укрепление иммунной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🧹 СОВЕТ: НАУКА ОВОЩНОГО ДЕТОКСА",
            content, "veggie_advice", benefits
        )
    # 🍠 ЧЕТВЕРГ - УГЛЕВОДНЫЙ ДЕНЬ (28 РЕЦЕПТОВ)
    
    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_energy_porridge(self):
        content = """
⚡️ ЭНЕРГЕТИЧЕСКАЯ ОВСЯНАЯ КАША С ФРУКТАМИ
КБЖУ: 380 ккал • Белки: 15г • Жиры: 10г • Углеводы: 62г

Ингредиенты на 2 порции:
• Овсяные хлопья - 100 г (бета-глюканы)
• Банан - 1 шт (калий - 358мг)
• Яблоко - 1 шт (пектин)
• Корица - 1 ч.л. (полифенолы)
• Мед - 1 ст.л. (натуральные сахара)
• Молоко - 300 мл

Приготовление (12 минут):
1. Овсянку варить с молоком 8 минут
2. Добавить нарезанные фрукты
3. Варить еще 3-4 минуты
4. Заправить медом и корицей

🎯 НАУЧНЫЙ ПОДХОД:
Бета-глюканы из овсянки образуют гель в кишечнике, замедляя усвоение углеводов и обеспечивая стабильную энергию.
"""
        benefits = """• 🌾 Овсянка - бета-глюканы для стабильной энергии
• 🍌 Банан - калий для мышечной функции
• 🍎 Яблоко - пектин для пищеварения
• 🍯 Мед - натуральные пребиотики"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡️ ЭНЕРГЕТИЧЕСКАЯ ОВСЯНАЯ КАША С ФРУКТАМИ",
            content, "carbs_breakfast", benefits
        )

    def generate_complex_carbs_toast(self):
        content = """
🍞 ТОСТ ИЗ ЦЕЛЬНОЗЕРНОВОГО ХЛЕБА С АВОКАДО
КБЖУ: 340 ккал • Белки: 12г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 2 порции:
• Цельнозерновой хлеб - 4 ломтика (клетчатка)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Помидоры - 2 шт (ликопин)
• Руккола - 50 г (нитраты)
• Лимонный сок - 1 ст.л.
• Семена кунжута - 1 ст.л.

Приготовление (10 минут):
1. Хлеб поджарить
2. Авокадо размять с лимонным соком
3. Намазать на тосты
4. Украсить помидорами, рукколой и семенами

🎯 НАУЧНЫЙ ПОДХОД:
Цельные зерна содержат все части зерновки, обеспечивая комплекс питательных веществ и медленное высвобождение энергии.
"""
        benefits = """• 🍞 Цельнозерновой хлеб - медленные углеводы
• 🥑 Авокадо - полезные жиры для усвоения
• 🍅 Помидоры - ликопин для антиоксидантной защиты
• 🌱 Семена кунжута - кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 ТОСТ ИЗ ЦЕЛЬНОЗЕРНОВОГО ХЛЕБА С АВОКАДО",
            content, "carbs_breakfast", benefits
        )

    def generate_sustained_energy_meal(self):
        content = """
🎯 ЗАВТРАК ДЛЯ УСТОЙЧИВОЙ ЭНЕРГИИ: ГРЕЧНЕВАЯ КАША
КБЖУ: 360 ккал • Белки: 18г • Жиры: 12г • Углеводы: 52г

Ингредиенты на 2 порции:
• Гречневая крупа - 120 г (рутин)
• Груша - 1 шт (растворимая клетчатка)
• Грецкие орехи - 30 г (Омега-3)
• Корица - 1 ч.л.
• Мед - 1 ст.л.
• Молоко - 300 мл

Приготовление (20 минут):
1. Гречку варить с молоком 15 минут
2. Добавить нарезанную грушу
3. Варить еще 3-4 минуты
4. Заправить орехами, медом и корицей

🎯 НАУЧНЫЙ ПОДХОД:
Гречка не содержит глютен и имеет низкий гликемический индекс (40), идеально подходит для стабильного уровня энергии.
"""
        benefits = """• 🌾 Гречка - рутин для сосудов + медленные углеводы
• 🍐 Груша - растворимая клетчатка для сытости
• 🌰 Грецкие орехи - Омега-3 для мозга
• 🍯 Мед - натуральная энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ЗАВТРАК ДЛЯ УСТОЙЧИВОЙ ЭНЕРГИИ: ГРЕЧНЕВАЯ КАША",
            content, "carbs_breakfast", benefits
        )

    def generate_glycogen_breakfast(self):
        content = """
🏃‍♂️ ЗАВТРАК ДЛЯ ВОСПОЛНЕНИЯ ГЛИКОГЕНА
КБЖУ: 420 ккал • Белки: 20г • Жиры: 14г • Углеводы: 58г

Ингредиенты на 2 порции:
• Сладкий картофель - 300 г (сложные углеводы)
• Яйца - 3 шт (белок)
• Шпинат - 100 г (железо)
• Авокадо - 1/2 шт (жиры)
• Оливковое масло - 1 ст.л.
• Специи по вкусу

Приготовление (25 минут):
1. Сладкий картофель запечь 20 минут
2. Яйца приготовить скрэмблом
3. Шпинат обжарить 2 минуты
4. Подавать все компоненты вместе

🎯 НАУЧНЫЙ ПОДХОД:
Сладкий картофель содержит резистентный крахмал, который ферментируется в кишечнике с образованием КЦЖК, полезных для здоровья.
"""
        benefits = """• 🍠 Сладкий картофель - сложные углеводы + резистентный крахмал
• 🥚 Яйца - белок для синтеза ферментов
• 🥬 Шпинат - железо для оксигенации
• 🥑 Авокадо - жиры для гормонального баланса"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃‍♂️ ЗАВТРАК ДЛЯ ВОСПОЛНЕНИЯ ГЛИКОГЕНА",
            content, "carbs_breakfast", benefits
        )

    def generate_energy_bowl_breakfast(self):
        content = """
💫 ЭНЕРГЕТИЧЕСКАЯ ЧАША С КИНОА И ЯГОДАМИ
КБЖУ: 390 ккал • Белки: 16г • Жиры: 15г • Углеводы: 55г

Ингредиенты на 2 порции:
• Киноа - 100 г (полноценный белок)
• Черника - 100 г (антоцианы)
• Малина - 100 г (эллагиновая кислота)
• Миндаль - 30 г (витамин E)
• Кокосовая стружка - 2 ст.л.
• Мед - 1 ст.л.

Приготовление (20 минут):
1. Киноа отварить 15 минут
2. Ягоды промыть
3. Смешать все ингредиенты
4. Заправить медом

🎯 НАУЧНЫЙ ПОДХОД:
Киноа содержит все 9 незаменимых аминокислот, что делает ее уникальным источником растительного белка.
"""
        benefits = """• 🌾 Киноа - полноценный белок + углеводы
• 🫐 Черника - антоцианы для когнитивных функций
• 🍓 Малина - эллагиновая кислота против воспаления
• 🌰 Миндаль - витамин E для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 ЭНЕРГЕТИЧЕСКАЯ ЧАША С КИНОА И ЯГОДАМИ",
            content, "carbs_breakfast", benefits
        )

    def generate_carbs_pancakes(self):
        content = """
🥞 УГЛЕВОДНЫЕ БЛИНЫ ИЗ ЦЕЛЬНОЙ МУКИ
КБЖУ: 350 ккал • Белки: 14г • Жиры: 10г • Углеводы: 52г

Ингредиенты на 2 порции:
• Цельнозерновая мука - 120 г (клетчатка)
• Яйца - 2 шт (белок)
• Молоко - 200 мл (кальций)
• Банан - 1 шт (натуральная сладость)
• Разрыхлитель - 1 ч.л.
• Кленовый сироп - 2 ст.л.

Приготовление (20 минут):
1. Смешать муку, яйца, молоко, банан
2. Добавить разрыхлитель
3. Жарить на антипригарной сковороде
4. Подавать с кленовым сиропом

🎯 НАУЧНЫЙ ПОДХОД:
Цельнозерновая мука сохраняет зародыш и оболочку зерна, содержащие витамины группы B, необходимые для энергетического обмена.
"""
        benefits = """• 🌾 Цельнозерновая мука - витамины группы B
• 🥚 Яйца - холин для мозга
• 🥛 Молоко - кальций для костей
• 🍌 Банан - натуральные сахара для энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 УГЛЕВОДНЫЕ БЛИНЫ ИЗ ЦЕЛЬНОЙ МУКИ",
            content, "carbs_breakfast", benefits
        )

    def generate_fuel_smoothie(self):
        content = """
⛽️ ТОПЛИВНЫЙ СМУЗИ ДЛЯ АКТИВНОГО ДНЯ
КБЖУ: 320 ккал • Белки: 12г • Жиры: 8г • Углеводы: 52г

Ингредиенты на 2 порции:
• Овсяные хлопья - 60 г (углеводы)
• Банан - 1 шт (калий)
• Финики - 3 шт (натуральные сахара)
• Шпинат - 50 г (железо)
• Семена льна - 1 ст.л. (Омега-3)
• Вода - 300 мл

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу

🎯 НАУЧНЫЙ ПОДХОД:
Финики содержат натуральные сахара (фруктозу и глюкозу) в сочетании с клетчаткой, обеспечивая быструю и устойчивую энергию.
"""
        benefits = """• 🌾 Овсяные хлопья - медленные углеводы
• 🍌 Банан - электролиты для гидратации
• 🫒 Финики - натуральная энергия + клетчатка
• 🌱 Семена льна - Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "⛽️ ТОПЛИВНЫЙ СМУЗИ ДЛЯ АКТИВНОГО ДНЯ",
            content, "carbs_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_glycogen_replenishment(self):
        content = """
🔄 ОБЕД ДЛЯ ВОССТАНОВЛЕНИЯ ГЛИКОГЕНА
КБЖУ: 480 ккал • Белки: 25г • Жиры: 15г • Углеводы: 65г

Ингредиенты на 2 порции:
• Бурый рис - 150 г (сложные углеводы)
• Куриная грудка - 200 г (белок)
• Брокколи - 200 г (клетчатка)
• Морковь - 1 шт (бета-каротин)
• Кунжутное масло - 1 ст.л.
• Соевый соус - 2 ст.л.

Приготовление (30 минут):
1. Бурый рис отварить 25 минут
2. Курицу запечь 20 минут
3. Овощи приготовить на пару
4. Смешать все компоненты

🎯 НАУЧНЫЙ ПОДХОД:
Бурый рис сохраняет отрубную оболочку, богатую витаминами группы B и магнием, критически важными для энергетического метаболизма.
"""
        benefits = """• 🍚 Бурый рис - магний + витамины B для энергии
• 🍗 Курица - белок для восстановления мышц
• 🥦 Брокколи - клетчатка для пищеварения
• 🥕 Морковь - бета-каротин для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ОБЕД ДЛЯ ВОССТАНОВЛЕНИЯ ГЛИКОГЕНА",
            content, "carbs_lunch", benefits
        )

    def generate_energy_bowl_lunch(self):
        content = """
💥 ЭНЕРГЕТИЧЕСКАЯ ЧАША С БУЛГУРОМ И ОВОЩАМИ
КБЖУ: 420 ккал • Белки: 18г • Жиры: 16г • Углеводы: 58г

Ингредиенты на 2 порции:
• Булгур - 120 г (быстрое приготовление)
• Нут - 150 г (растительный белок)
• Огурцы - 2 шт (вода)
• Помидоры - 2 шт (ликопин)
• Петрушка - 30 г (витамин K)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

Приготовление (20 минут):
1. Булгур залить кипятком на 15 минут
2. Нут отварить или использовать консервированный
3. Овощи нарезать
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Булгур имеет низкий гликемический индекс (48) и высокое содержание клетчатки, обеспечивая длительное насыщение.
"""
        benefits = """• 🌾 Булгур - клетчатка для сытости
• 🫘 Нут - растительный белок + клетчатка
• 🥒 Огурцы - гидратация организма
• 🍅 Помидоры - ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💥 ЭНЕРГЕТИЧЕСКАЯ ЧАША С БУЛГУРОМ И ОВОЩАМИ",
            content, "carbs_lunch", benefits
        )

    def generate_carbs_balance_meal(self):
        content = """
⚖️ СБАЛАНСИРОВАННЫЙ ОБЕД С УГЛЕВОДАМИ И БЕЛКОМ
КБЖУ: 460 ккал • Белки: 30г • Жиры: 18г • Углеводы: 52г

Ингредиенты на 2 порции:
• Картофель - 400 г (калий)
• Лосось - 200 г (Омега-3)
• Спаржа - 150 г (фолат)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (антиоксиданты)
• Оливковое масло - 1 ст.л.

Приготовление (30 минут):
1. Картофель запечь 25 минут
2. Лосось приготовить на пару 12 минут
3. Спаржу бланшировать 4 минуты
4. Подавать все компоненты вместе

🎯 НАУЧНЫЙ ПОДХОД:
Картофель, приготовленный и охлажденный, образует резистентный крахмал, который служит пребиотиком для микробиома.
"""
        benefits = """• 🥔 Картофель - калий + резистентный крахмал
• 🐟 Лосось - Омега-3 для мозга и сердца
• 🌱 Спаржа - фолат для синтеза ДНК
• 🍋 Лимон - витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ОБЕД С УГЛЕВОДАМИ И БЕЛКОМ",
            content, "carbs_lunch", benefits
        )

    def generate_pasta_power(self):
        content = """
🍝 ЭНЕРГЕТИЧЕСКАЯ ПАСТА С ОВОЩАМИ И СЫРОМ
КБЖУ: 450 ккал • Белки: 22г • Жиры: 16г • Углеводы: 58г

Ингредиенты на 2 порции:
• Цельнозерновая паста - 150 г (клетчатка)
• Цукини - 1 шт (калий)
• Болгарский перец - 1 шт (витамин C)
• Помидоры черри - 150 г (ликопин)
• Сыр пармезан - 50 г (кальций)
• Базилик - 20 г (эфирные масла)

Приготовление (25 минут):
1. Пасту отварить al dente
2. Овощи обжарить 8 минут
3. Смешать с пастой
4. Посыпать сыром и базиликом

🎯 НАУЧНЫЙ ПОДХОД:
Сложные углеводы из цельнозерновой пасты обеспечивают медленное высвобождение энергии, поддерживая стабильный уровень глюкозы.
"""
        benefits = """• 🍝 Цельнозерновая паста - медленные углеводы
• 🥒 Цукини - калий для нервной системы
• 🌶️ Перец - витамин C для иммунитета
• 🧀 Сыр - кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🍝 ЭНЕРГЕТИЧЕСКАЯ ПАСТА С ОВОЩАМИ И СЫРОМ",
            content, "carbs_lunch", benefits
        )

    def generate_quinoa_power_bowl(self):
        content = """
💪 СИЛОВАЯ ЧАША С КИНОА И ОВОЩАМИ
КБЖУ: 430 ккал • Белки: 24г • Жиры: 18г • Углеводы: 48г

Ингредиенты на 2 порции:
• Киноа - 120 г (полноценный белок)
• Сладкий картофель - 200 г (бета-каротин)
• Брокколи - 150 г (сульфорафан)
• Авокадо - 1/2 шт (полезные жиры)
• Семена тыквы - 2 ст.л. (цинк)
• Лимонный сок - 2 ст.л.

Приготовление (25 минут):
1. Киноа отварить 15 минут
2. Сладкий картофель запечь
3. Брокколи приготовить на пару
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Киноа содержит все 9 незаменимых аминокислот, обеспечивая полноценный белок для восстановления и роста мышц.
"""
        benefits = """• 🌾 Киноа - полноценный растительный белок
• 🍠 Сладкий картофель - сложные углеводы
• 🥦 Брокколи - антиоксиданты для защиты
• 🥑 Авокадо - полезные жиры для гормонов"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СИЛОВАЯ ЧАША С КИНОА И ОВОЩАМИ",
            content, "carbs_lunch", benefits
        )

    def generate_rice_nourishment(self):
        content = """
🍚 ПИТАТЕЛЬНЫЙ РИС С ОВОЩАМИ И ТОФУ
КБЖУ: 440 ккал • Белки: 26г • Жиры: 14г • Углеводы: 55г

Ингредиенты на 2 порции:
• Бурый рис - 150 г (магний)
• Тофу - 200 г (изофлавоны)
• Морковь - 2 шт (бета-каротин)
• Горошек - 100 г (растительный белок)
• Имбирь - 2 см (гингерол)
• Кунжутное масло - 1 ст.л.

Приготовление (30 минут):
1. Рис отварить 25 минут
2. Тофу обжарить до золотистой корочки
3. Овощи обжарить с имбирем
4. Смешать все компоненты

🎯 НАУЧНЫЙ ПОДХОД:
Магний из бурого риса участвует в более чем 300 биохимических реакциях, включая производство энергии.
"""
        benefits = """• 🍚 Бурый рис - магний для энергетического обмена
• 🧈 Тофу - растительный белок для мышц
• 🥕 Морковь - антиоксиданты для защиты
• 🟤 Имбирь - противовоспалительный эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🍚 ПИТАТЕЛЬНЫЙ РИС С ОВОЩАМИ И ТОФУ",
            content, "carbs_lunch", benefits
        )

    def generate_lentil_energy(self):
        content = """
🌱 ЭНЕРГЕТИЧЕСКАЯ ЧЕЧЕВИЦА С ОВОЩАМИ
КБЖУ: 410 ккал • Белки: 28г • Жиры: 12г • Углеводы: 52г

Ингредиенты на 2 порции:
• Чечевица - 150 г (белок + клетчатка)
• Лук - 1 шт (кверцетин)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 2 стебля (апигенин)
• Томатная паста - 2 ст.л.
• Специи: куркума, кумин

Приготовление (25 минут):
1. Чечевицу отварить 20 минут
2. Овощи обжарить 5 минут
3. Добавить томатную пасту и специи
4. Тушить 10 минут

🎯 НАУЧНЫЙ ПОДХОД:
Чечевица содержит резистентный крахмал, который ферментируется в толстом кишечнике с образованием короткоцепочечных жирных кислот.
"""
        benefits = """• 🌱 Чечевица - белок + резистентный крахмал
• 🧅 Лук - кверцетин против воспаления
• 🥕 Морковь - витамин A для иммунитета
• 🥬 Сельдерей - апигенин для нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 ЭНЕРГЕТИЧЕСКАЯ ЧЕЧЕВИЦА С ОВОЩАМИ",
            content, "carbs_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_slow_carbs_dinner(self):
        content = """
🌙 УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦА С ОВОЩАМИ
КБЖУ: 380 ккал • Белки: 22г • Жиры: 12г • Углеводы: 48г

Ингредиенты на 2 порции:
• Чечевица - 150 г (растительный белок)
• Цукини - 1 шт (калий)
• Баклажаны - 1 шт (насунин)
• Помидоры - 2 шт (ликопин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

Приготовление (25 минут):
1. Чечевицу отварить 20 минут
2. Овощи нарезать и обжарить
3. Смешать все ингредиенты
4. Тушить 5 минут под крышкой

🎯 НАУЧНЫЙ ПОДХОД:
Чечевица содержит медленно усваиваемые углеводы и резистентный крахмал, поддерживающий стабильный уровень сахара в крови.
"""
        benefits = """• 🌱 Чечевица - медленные углеводы + белок
• 🥒 Цукини - калий для водного баланса
• 🍆 Баклажаны - насунин для клеточных мембран
• 🧄 Чеснок - противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦЯ С ОВОЩАМИ",
            content, "carbs_dinner", benefits
        )

    def generate_energy_reserve_meal(self):
        content = """
🔋 УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА
КБЖУ: 350 ккал • Белки: 18г • Жиры: 14г • Углеводы: 42г

Ингредиенты на 2 порции:
• Киноа - 100 г (полноценный белок)
• Тыква - 300 г (бета-каротин)
• Шпинат - 100 г (железо)
• Семена тыквы - 2 ст.л. (цинк)
• Кокосовое молоко - 100 мл (среднецепочечные триглицериды)
• Куркума - 1 ч.л.

Приготовление (25 минут):
1. Киноа отварить
2. Тыкву запечь 20 минут
3. Шпинат обжарить 2 минуты
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Среднецепочечные триглицериды из кокосового молока быстро метаболизируются в печени, обеспечивая быструю энергию.
"""
        benefits = """• 🌾 Киноа - аминокислоты для восстановления
• 🎃 Тыква - бета-каротин для иммунитета
• 🥬 Шпинат - железо для энергии
• 🥥 Кокосовое молоко - быстрая энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА",
            content, "carbs_dinner", benefits
        )

    def generate_evening_carbs(self):
        content = """
🌃 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА
КБЖУ: 320 ккал • Белки: 15г • Жиры: 10г • Углеводы: 45г

Ингредиенты на 2 порции:
• Батат - 400 г (сложные углеводы)
• Творог - 150 г (триптофан)
• Банан - 1 шт (мелатонин)
• Корица - 1 ч.л.
• Мед - 1 ст.л.

Приготовление (20 минут):
1. Батат запечь 18 минут
2. Размять вилкой
3. Смешать с творогом и бананом
4. Заправить медом и корицей

🎯 НАУЧНЫЙ ПОДХОД:
Углеводы вечером способствуют транспорту триптофана через гематоэнцефалический барьер, улучшая синтез мелатонина.
"""
        benefits = """• 🍠 Батат - сложные углеводы для сытости
• 🧀 Творог - триптофан для серотонина
• 🍌 Банан - мелатонин для сна
• 🍯 Мед - натуральные сахара для релаксации"""
        
        return self.visual_manager.generate_attractive_post(
            "🌃 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА",
            content, "carbs_dinner", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_carbs_science_advice(self):
        content = """
🍠 НАУКА УГЛЕВОДОВ: КАК ИСПОЛЬЗОВАТЬ ИХ С ПОЛЬЗОЙ

🔬 ТИПЫ УГЛЕВОДОВ:

1. 🎯 СЛОЖНЫЕ УГЛЕВОДЫ
• Медленное высвобождение энергии
• Источники: цельнозерновые, бобовые, овощи
• Гликемический индекс: 55 и ниже

2. ⚡ ПРОСТЫЕ УГЛЕВОДЫ
• Быстрая энергия
• Источники: фрукты, мед, молоко
• Сочетать с клетчаткой и белком

3. 🌾 РЕЗИСТЕНТНЫЙ КРАХМАЛ
• Пребиотик для микробиома
• Образуется при охлаждении приготовленных углеводов
• Улучшает инсулиновую чувствительность

4. 🕒 ВРЕМЯ ПРИЕМА
• Утро: сложные углеводы для энергии
• После тренировки: быстрые углеводы для восстановления
• Вечер: умеренное количество для сна

5. 📊 РАСЧЕТ ПОТРЕБНОСТИ
• Средняя активность: 3-5г/кг
• Высокая активность: 5-7г/кг
• Индивидуальный подход

🎯 ПРАКТИКА: Выбирайте цельные источники углеводов!
"""
        benefits = """• ⚡ Стабильная энергия в течение дня
• 🧠 Улучшение когнитивных функций
• 🏃‍♂️ Повышение физической производительности
• 🩸 Контроль уровня сахара в крови"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 СОВЕТ: НАУКА УГЛЕВОДОВ И ЭНЕРГИИ",
            content, "carbs_advice", benefits
        )

    def generate_energy_management_advice(self):
        content = """
⚡️ УПРАВЛЕНИЕ ЭНЕРГИЕЙ: РОЛЬ УГЛЕВОДОВ

📈 ОПТИМИЗАЦИЯ ЭНЕРГЕТИЧЕСКОГО БАЛАНСА:

1. 🎯 ГЛИКОГЕНОВЫЕ ДЕПО
• Печень: 100-120г гликогена
• Мышцы: 300-400г гликогена
• Пополнение каждые 24 часа

2. 🧠 МОЗГ И УГЛЕВОДЫ
• 120г глюкозы в день для мозга
• Кетоновые тела как альтернатива
• Стабильное питание = стабильное мышление

3. 💪 ФИЗИЧЕСКАЯ АКТИВНОСТЬ
• Низкая интенсивность: жиры как топливо
• Высокая интенсивность: углеводы как топливо
• Углеводная загрузка перед соревнованиями

4. 🕒 СУПЕРКОМПЕНСАЦИЯ
• Истощение + насыщение = суперкомпенсация
• Увеличение запасов гликогена на 20-40%
• Для спортсменов и активных людей

5. 🍽️ ПРАКТИЧЕСКИЕ СОВЕТЫ
• Завтрак: 30% суточных углеводов
• Обед: 40% суточных углеборов
• Ужин: 20% суточных углеводов
• Перекусы: 10% суточных углеводов

🎯 ЗАДАНИЕ: Отслеживайте свои энергетические уровни!
"""
        benefits = """• ⚡ Оптимальный энергетический уровень
• 🧠 Ясность мышления и концентрация
• 💪 Улучшение спортивных результатов
• 📈 Стабильный метаболизм"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡️ СОВЕТ: УПРАВЛЕНИЕ ЭНЕРГИЕЙ С ПОМОЩЬЮ УГЛЕВОДОВ",
            content, "carbs_advice", benefits
        )

    def generate_glycemic_control_advice(self):
        content = """
📊 КОНТРОЛЬ ГЛИКЕМИЧЕСКОГО ОТВЕТА: КЛЮЧ К ЗДОРОВЬЮ

🔬 СТРАТЕГИИ СТАБИЛЬНОГО УРОВНЯ САХАРА:

1. 🎯 ГЛИКЕМИЧЕСКИЙ ИНДЕКС (ГИ)
• Низкий ГИ (55 и ниже): овсянка, чечевица
• Средний ГИ (56-69): банан, кукуруза
• Высокий ГИ (70+): белый хлеб, картофель

2. 🌾 ЦЕЛЬНЫЕ ИСТОЧНИКИ
• Сохраняют клетчатку и питательные вещества
• Медленное высвобождение энергии
• Поддержание сытости

3. 🍽️ КОМБИНАЦИИ ПИТАТЕЛЬНЫХ ВЕЩЕСТВ
• Углеводы + белок = замедление усвоения
• Углеводы + жиры = снижение ГИ
• Углеводы + клетчатка = стабильная энергия

4. 🕒 ВРЕМЯ ПРИЕМА
• Утро: сложные углеводы для энергии дня
• После тренировки: быстрые углеводы для восстановления
• Вечер: умеренное количество для сна

5. 📈 МОНИТОРИНГ РЕАКЦИИ
• Индивидуальные различия в реакции на углеводы
• Отслеживание энергетических уровней
• Коррекция на основе самочувствия

🎯 ПРАКТИКА: Начните с замены одного простого углевода на сложный!
"""
        benefits = """• 📊 Стабильный уровень сахара в крови
• ⚡ Постоянная энергия в течение дня
• 🍽️ Снижение риска инсулинорезистентности
• 💪 Улучшение спортивных результатов"""
        
        return self.visual_manager.generate_attractive_post(
            "📊 СОВЕТ: КОНТРОЛЬ ГЛИКЕМИЧЕСКОГО ОТВЕТА",
            content, "carbs_advice", benefits
        )
    # 🎉 ПЯТНИЦА - БАЛАНС И УДОВОЛЬСТВИЕ (35 РЕЦЕПТОВ)
    
    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_fun_breakfast(self):
        content = """
🎪 ПЯТНИЧНЫЙ ЗАВТРАК: ВЕСЕЛЫЕ БЛИНЫ С ЯГОДАМИ
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 52г

Ингредиенты на 2 порции:
• Цельнозерновая мука - 100 г (клетчатка)
• Яйца - 2 шт (белок)
• Молоко - 200 мл (кальций)
• Ягоды - 150 г (антиоксиданты)
• Греческий йогурт - 100 г (пробиотики)
• Кленовый сироп - 2 ст.л.

Приготовление (20 минут):
1. Смешать муку, яйца, молоко
2. Жарить блины на антипригарной сковороде
3. Подавать с йогуртом, ягодами и сиропом
4. Создать веселую композицию на тарелке

🎯 НАУЧНЫЙ ПОДХОД:
Позитивные эмоции от красивого приема пищи улучшают пищеварение через вагусный нерв и повышают усвоение питательных веществ.
"""
        benefits = """• 🌾 Цельнозерновая мука - витамины группы B
• 🥚 Яйца - холин для хорошего настроения
• 🥛 Греческий йогурт - пробиотики для кишечника
• 🍓 Ягоды - антиоксиданты для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🎪 ПЯТНИЧНЫЙ ЗАВТРАК: ВЕСЕЛЫЕ БЛИНЫ С ЯГОДАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_balanced_meal(self):
        content = """
⚖️ СБАЛАНСИРОВАННЫЙ ЗАВТРАК 80/20
КБЖУ: 420 ккал • Белки: 25г • Жиры: 18г • Углеводы: 45г

Ингредиенты на 2 порции:
• Овсянка - 80 г (сложные углеводы)
• Яйца - 3 шт (качественный белок)
• Авокадо - 1/2 шт (полезные жиры)
• Темный шоколад 85% - 20 г (полифенолы)
• Мед - 1 ч.л. (натуральная сладость)
• Корица - 1 ч.л.

Приготовление (15 минут):
1. Овсянку сварить с водой
2. Яйца приготовить всмятку
3. Авокадо нарезать ломтиками
4. Подавать все вместе с шоколадом

🎯 НАУЧНЫЙ ПОДХОД:
Принцип 80/20 позволяет сохранить психологический комфорт while maintaining nutritional quality, снижая риск срывов.
"""
        benefits = """• 🌾 Овсянка - стабильная энергия
• 🥚 Яйца - полноценный белок
• 🥑 Авокадо - мононенасыщенные жиры
• 🍫 Темный шоколад - улучшение настроения"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ЗАВТРАК 80/20",
            content, "energy_breakfast", benefits
        )

    def generate_weekend_mood_meal(self):
        content = """
😊 ЗАВТРАК ДЛЯ ХОРОШЕГО НАСТРОЕНИЯ
КБЖУ: 350 ккал • Белки: 20г • Жиры: 15г • Углеводы: 35г

Ингредиенты на 2 порции:
• Творог - 200 г (триптофан)
• Банан - 1 шт (дофаминовые прекурсоры)
• Грецкие орехи - 30 г (Омега-3)
• Клубника - 100 г (фолиевая кислота)
• Мед - 1 ст.л. (натуральные сахара)
• Ваниль - 1 ч.л.

Приготовление (5 минут):
1. Творог смешать с ванилью
2. Банан и клубнику нарезать
3. Смешать все ингредиенты
4. Заправить медом

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из творога является предшественником серотонина - "гормона счастья", улучшающего настроение.
"""
        benefits = """• 🧀 Творог - триптофан для серотонина
• 🍌 Банан - дофаминовые прекурсоры
• 🌰 Грецкие орехи - Омега-3 для мозга
• 🍓 Клубника - фолат для нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "😊 ЗАВТРАК ДЛЯ ХОРОШЕГО НАСТРОЕНИЯ",
            content, "energy_breakfast", benefits
        )

    def generate_friday_pancakes(self):
        content = """
🥞 ПЯТНИЧНЫЕ ПАНКЕЙКИ С КАРАМЕЛИЗИРОВАННЫМИ БАНАНАМИ
КБЖУ: 390 ккал • Белки: 16г • Жиры: 14г • Углеводы: 55г

Ингредиенты на 2 порции:
• Овсяная мука - 100 г (клетчатка)
• Яйца - 2 шт (белок)
• Молоко - 150 мл
• Бананы - 2 шт (калий)
• Кокосовое масло - 1 ст.л. (МСТ)
• Кленовый сироп - 2 ст.л.

Приготовление (20 минут):
1. Приготовить тесто для панкейков
2. Карамелизировать бананы на кокосовом масле
3. Подавать панкейки с бананами и сиропом

🎯 НАУЧНЫЙ ПОДХОД:
Умеренное количество натуральных сахаров из фруктов и сиропа обеспечивает удовольствие без резких скачков глюкозы.
"""
        benefits = """• 🌾 Овсяная мука - медленные углеводы
• 🥚 Яйца - строительные материалы для нейромедиаторов
• 🍌 Бананы - калий для нервной системы
• 🥥 Кокосовое масло - быстрая энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 ПЯТНИЧНЫЕ ПАНКЕЙКИ С КАРАМЕЛИЗИРОВАННЫМИ БАНАНАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_celebration_toast(self):
        content = """
🎊 ПРАЗДНИЧНЫЙ ТОСТ С РИКОТТОЙ И ФРУКТАМИ
КБЖУ: 320 ккал • Белки: 18г • Жиры: 12г • Углеводы: 38г

Ингредиенты на 2 порции:
• Хлеб чиабатта - 4 ломтика
• Сыр рикотта - 150 г (белок)
• Персик - 1 шт (бета-каротин)
• Мед - 1 ст.л.
• Мята - 10 листьев (ментол)
• Лимонная цедра - 1 ч.л.

Приготовление (10 минут):
1. Хлеб поджарить
2. Намазать рикотту
3. Украсить ломтиками персика
4. Полить медом, украсить мятой

🎯 НАУЧНЫЙ ПОДХОД:
Сочетание текстур и вкусов активирует больше сенсорных рецепторов, усиливая удовольствие от еды.
"""
        benefits = """• 🍞 Чиабатта - хрустящая текстура для удовольствия
• 🧀 Рикотта - нежный белок для сытости
• 🍑 Персик - бета-каротин для кожи
• 🌿 Мята - освежающий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🎊 ПРАЗДНИЧНЫЙ ТОСТ С РИКОТТОЙ И ФРУКТАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_social_smoothie(self):
        content = """
👥 СОЦИАЛЬНЫЙ СМУЗИ ДЛЯ ВСТРЕЧИ С ДРУЗЬЯМИ
КБЖУ: 280 ккал • Белки: 12г • Жиры: 8г • Углеводы: 42г

Ингредиенты на 2 порции:
• Манго - 1 шт (витамин C)
• Ананас - 150 г (бромелайн)
• Кокосовая вода - 200 мл (электролиты)
• Шпинат - 50 г (хлорофилл)
• Имбирь - 1 см (гингерол)
• Лайм - 1/2 шт

Приготовление (5 минут):
1. Все ингредиенты взбить в блендере
2. Разлить по красивым бокалам
3. Украсить долькой лайма

🎯 НАУЧНЫЙ ПОДХОД:
Бромелайн из ананаса улучшает пищеварение и обладает противовоспалительными свойствами, полезными после вечеринок.
"""
        benefits = """• 🥭 Манго - витамин C для иммунитета
• 🍍 Ананас - бромелайн для пищеварения
• 🥥 Кокосовая вода - гидратация
• 🟤 Имбирь - противовоспалительный эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "👥 СОЦИАЛЬНЫЙ СМУЗИ ДЛЯ ВСТРЕЧИ С ДРУЗЬЯМИ",
            content, "energy_breakfast", benefits
        )

    def generate_indulgence_bowl(self):
        content = """
🍧 ЧАША УДОВОЛЬСТВИЯ С ГРАНОЛОЙ И ШОКОЛАДОМ
КБЖУ: 360 ккал • Белки: 15г • Жиры: 16г • Углеводы: 45г

Ингредиенты на 2 порции:
• Греческий йогурт - 300 г (пробиотики)
• Домашняя гранола - 60 г (цельные зерна)
• Клубника - 100 г (антиоксиданты)
• Темный шоколад - 20 г (теобромин)
• Мед - 1 ст.л.
• Ванильный экстракт - 1 ч.л.

Приготовление (5 минут):
1. Йогурт смешать с ванилью
2. Выложить в миски
3. Добавить гранолу и фрукты
4. Посыпать тертым шоколадом

🎯 НАУЧНЫЙ ПОДХОД:
Теобромин из темного шоколада мягко стимулирует нервную систему и улучшает настроение без резких скачков.
"""
        benefits = """• 🥛 Греческий йогурт - пробиотики для микробиома
• 🌾 Гранола - цельные зерна для энергии
• 🍓 Клубника - антиоксиданты для защиты
• 🍫 Темный шоколад - теобромин для настроения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍧 ЧАША УДОВОЛЬСТВИЯ С ГРАНОЛОЙ И ШОКОЛАДОМ",
            content, "energy_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_mediterranean_feast(self):
        content = """
🌊 СРЕДИЗЕМНОМОРСКИЙ ПРАЗДНИК
КБЖУ: 450 ккал • Белки: 25г • Жиры: 22г • Углеводы: 42г

Ингредиенты на 2 порции:
• Лосось - 200 г (Омега-3)
• Киноа - 100 г (белок)
• Оливки - 50 г (мононенасыщенные жиры)
• Фета - 80 г (кальций)
• Огурцы - 2 шт (вода)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

Приготовление (20 минут):
1. Лосось запечь 15 минут
2. Киноа отварить
3. Смешать все ингредиенты
4. Заправить маслом и лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Средиземноморская диета ассоциируется с увеличенной продолжительностью жизни и снижением риска хронических заболеваний.
"""
        benefits = """• 🐟 Лосось - Омега-3 для сердца и мозга
• 🌾 Киноа - полноценный растительный белок
• 🫒 Оливки - полезные жиры для сосудов
• 🧀 Фета - кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🌊 СРЕДИЗЕМНОМОРСКИЙ ПРАЗДНИК",
            content, "mediterranean_lunch", benefits
        )

    def generate_social_lunch(self):
        content = """
👨‍👩‍👧‍👦 СОЦИАЛЬНЫЙ ОБЕД: ПАСТА С ПЕСТО И МОРЕПРОДУКТАМИ
КБЖУ: 480 ккал • Белки: 28г • Жиры: 18г • Углеводы: 55г

Ингредиенты на 2 порции:
• Цельнозерновая паста - 150 г (клетчатка)
• Креветки - 200 г (белок)
• Базилик - 50 г (эфирные масла)
• Кедровые орехи - 30 г (цинк)
• Пармезан - 50 г (кальций)
• Оливковое масло - 2 ст.л.

Приготовление (25 минут):
1. Пасту отварить al dente
2. Креветки обжарить 5 минут
3. Приготовить песто из базилика, орехов, сыра и масла
4. Смешать все компоненты

🎯 НАУЧНЫЙ ПОДХОД:
Совместные приемы пищи улучшают социальные связи и психологическое благополучие, что положительно влияет на здоровье.
"""
        benefits = """• 🍝 Цельнозерновая паста - медленные углеводы
• 🦐 Креветки - белок + селен для антиоксидантной защиты
• 🌿 Базилик - противовоспалительные свойства
• 🌰 Кедровые орехи - цинк для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СОЦИАЛЬНЫЙ ОБЕД: ПАСТА С ПЕСТО И МОРЕПРОДУКТАМИ",
            content, "mediterranean_lunch", benefits
        )

    def generate_celebration_meal(self):
        content = """
🎉 ПРАЗДНИЧНЫЙ ОБЕД С КУРИЦЕЙ И ОВОЩАМИ ГРИЛЬ
КБЖУ: 420 ккал • Белки: 35г • Жиры: 20г • Углеводы: 28г

Ингредиенты на 2 порции:
• Куриные бедра - 300 г (белок)
• Цукини - 2 шт (калий)
• Баклажаны - 1 шт (насунин)
• Перец - 2 шт (витамин C)
• Соус терияки - 3 ст.л.
• Кунжут - 1 ст.л.

Приготовление (30 минут):
1. Курицу и овощи замариновать в терияки
2. Обжарить на гриле или сковороде
3. Посыпать кунжутом перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Приготовление на гриле создает ароматические соединения (реакция Майяра), которые усиливают удовольствие от еды.
"""
        benefits = """• 🍗 Курица - качественный животный белок
• 🥒 Цукини - калий для водного баланса
• 🍆 Баклажаны - антиоксиданты для клеток
• 🌶️ Перец - витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🎉 ПРАЗДНИЧНЫЙ ОБЕД С КУРИЦЕЙ И ОВОЩАМИ ГРИЛЬ",
            content, "mediterranean_lunch", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_healthy_indulgence(self):
        content = """
🍫 ЗДОРОВОЕ УДОВОЛЬСТВИЕ: ШОКОЛАДНЫЙ МУСС ИЗ АВОКАДО
КБЖУ: 220 ккал • Белки: 8г • Жиры: 16г • Углеводы: 18г

Ингредиенты на 2 порции:
• Авокадо - 1 шт (полезные жиры)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Мед - 2 ст.л. (натуральные сахара)
• Ванильный экстракт - 1 ч.л.
• Миндальное молоко - 50 мл
• Ягоды для подачи

Приготовление (10 минут):
1. Авокадо очистить от кожуры
2. Все ингредиенты взбить в блендере
3. Охладить 30 минут
4. Подавать с ягодами

🎯 НАУЧНЫЙ ПОДХОД:
Флавоноиды какао улучшают кровоснабжение мозга и обладают антиоксидантными свойствами.
"""
        benefits = """• 🥑 Авокадо - мононенасыщенные жиры
• 🍫 Какао - флавоноиды для сосудов
• 🍯 Мед - натуральные пребиотики
• 🍓 Ягоды - антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ЗДОРОВОЕ УДОВОЛЬСТВИЕ: ШОКОЛАДНЫЙ МУСС ИЗ АВОКАДО",
            content, "friday_dessert", benefits
        )

    def generate_guilt_free_treat(self):
        content = """
🍰 ДЕСЕРТ БЕЗ ЧУВСТВА ВИНЫ: ЯБЛОЧНЫЙ КРАМБЛ
КБЖУ: 280 ккал • Белки: 8г • Жиры: 12г • Углеводы: 35г

Ингредиенты на 2 порции:
• Яблоки - 4 шт (кверцетин)
• Овсяные хлопья - 60 г (клетчатка)
• Миндальная мука - 40 г (белок)
• Корица - 2 ч.л. (полифенолы)
• Кокосовое масло - 2 ст.л. (МСТ)
• Мед - 1 ст.л.

Приготовление (30 минут):
1. Яблоки нарезать, смешать с корицей
2. Для крошки: овсянка + мука + мед + масло
3. Выложить яблоки в форму, посыпать крошкой
4. Запекать 25 минут при 180°C

🎯 НАУЧНЫЙ ПОДХОД:
Кверцетин из яблок обладает противовоспалительными и антиоксидантными свойствами.
"""
        benefits = """• 🍎 Яблоки - кверцетин против воспаления
• 🌾 Овсянка - бета-глюканы для холестерина
• 🌰 Миндальная мука - витамин E для кожи
• 🟤 Корица - регуляция уровня сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ДЕСЕРТ БЕЗ ЧУВСТВА ВИНЫ: ЯБЛОЧНЫЙ КРАМБЛ",
            content, "friday_dessert", benefits
        )

    def generate_weekend_dessert(self):
        content = """
🎊 ВЫХОДНОЙ ДЕСЕРТ: ТИРАМИСУ БЕЗ ВЫПЕЧКИ
КБЖУ: 250 ккал • Белки: 12г • Жиры: 14г • Углеводы: 22г

Ингредиенты на 2 порции:
• Рикотта - 200 г (белок)
• Кофе эспрессо - 100 мл (антиоксиданты)
• Какао-порошок - 2 ст.л.
• Мед - 2 ст.л.
• Ванильный экстракт - 1 ч.л.
• Печенье савоярди - 4 шт

Приготовление (15 минут + охлаждение):
1. Рикотту смешать с медом и ванилью
2. Печенье обмакнуть в кофе
3. Слоями выложить в креманки
4. Охладить 2 часа, посыпать какао

🎯 НАУЧНЫЙ ПОДХОД:
Кофе содержит хлорогеновую кислоту, которая улучшает чувствительность к инсулину и обладает антиоксидантными свойствами.
"""
        benefits = """• 🧀 Рикотта - легкоусвояемый белок
• ☕ Кофе - антиоксиданты для защиты клеток
• 🍫 Какао - магний для нервной системы
• 🍯 Мед - натуральные антимикробные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🎊 ВЫХОДНОЙ ДЕСЕРТ: ТИРАМИСУ БЕЗ ВЫПЕЧКИ",
            content, "friday_dessert", benefits
        )

    # 💧 СОВЕТЫ (7 рецептов)
    def generate_hydration_science(self):
        content = """
💧 НАУКА ГИДРАТАЦИИ: ВОДА КАК ОСНОВА ЗДОРОВЬЯ

🔬 КЛЮЧЕВЫЕ ФАКТЫ:

1. 🧠 МОЗГ И ВОДА
• 75% мозга состоит из воды
• Обезвоживание на 2% снижает когнитивные функции на 20%
• Концентрация, память, внимание

2. 💪 МЫШЦЫ И ЭНЕРГИЯ
• Вода - среда для всех биохимических реакций
• Транспорт питательных веществ
• Выведение метаболитов

3. 🍽️ ПИЩЕВАРЕНИЕ
• Смазка для пищеварительного тракта
• Растворение питательных веществ
• Предотвращение запоров

4. 🏃‍♂️ ФИЗИЧЕСКАЯ АКТИВНОСТЬ
• Регуляция температуры тела
• Смазка суставов
• Предотвращение судорог

5. 🎯 ПРАКТИЧЕСКИЕ СОВЕТЫ
• 30 мл на 1 кг веса в день
• Стакан воды после пробуждения
• Перед каждым приемом пищи
• Во время и после тренировки

🎯 ЗАДАНИЕ: Выпейте стакан воды прямо сейчас!
"""
        benefits = """• 🧠 Улучшение когнитивных функций
• 💪 Повышение энергии и выносливости
• 🍽️ Оптимизация пищеварения
• 🌡️ Лучшая терморегуляция"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 СОВЕТ: НАУКА ГИДРАТАЦИИ И ВОДНОГО БАЛАНСА",
            content, "water_advice", benefits
        )

    def generate_electrolyte_balance(self):
        content = """
⚡️ ЭЛЕКТРОЛИТНЫЙ БАЛАНС: КЛЮЧ К ЭНЕРГИИ И ЗДОРОВЬЮ

🧪 ОСНОВНЫЕ ЭЛЕКТРОЛИТЫ:

1. 🧂 НАТРИЙ
• Регуляция водного баланса
• Нервная проводимость
• Мышечные сокращения

2. 🥑 КАЛИЙ
• Баланс с натрием
• Здоровье сердца
• Нервная функция

3. 🥛 КАЛЬЦИЙ
• Кости и зубы
• Мышечные сокращения
• Свертывание крови

4. 🥬 МАГНИЙ
• 300+ биохимических реакций
• Производство энергии
• Расслабление мышц

5. 🍋 НАТУРАЛЬНЫЕ ИСТОЧНИКИ
• Бананы, авокадо, шпинат
• Орехи, семена, бобовые
• Молочные продукты, листовая зелень

🎯 ПРАКТИКА: Добавьте щепотку морской соли в воду после тренировки!
"""
        benefits = """• ⚡ Оптимальная энергия в течение дня
• 💪 Улучшение мышечной функции
• 🧠 Лучшая нервная проводимость
• 🏃‍♂️ Ускоренное восстановление"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡️ СОВЕТ: ЭЛЕКТРОЛИТНЫЙ БАЛАНС ДЛЯ ЭНЕРГИИ",
            content, "water_advice", benefits
        )

    def generate_detox_hydration(self):
        content = """
🌿 ДЕТОКС-ГИДРАТАЦИЯ: ОЧИЩЕНИЕ ЧЕРЕЗ ВОДУ

💧 СТРАТЕГИИ ОЧИЩЕНИЯ:

1. 🍋 ЛИМОННАЯ ВОДА
• Стимулирует выработку желчи
• Поддерживает функцию печени
• Усиливает выведение токсинов

2. 🟤 ИМБИРНЫЙ НАПИТОК
• Улучшает кровообращение
• Обладает противовоспалительными свойствами
• Стимулирует пищеварение

3. 🌿 МЯТНЫЙ ЧАЙ
• Расслабляет мышцы ЖКТ
• Улучшает отток желчи
• Освежает дыхание

4. 🥒 ОГУРЕЧНАЯ ВОДА
• Содержит кремний для соединительной ткани
• Поддерживает здоровье кожи
• Обеспечивает дополнительную гидратацию

5. 💫 КОКОСОВАЯ ВОДА
• Богата электролитами
• Восстанавливает минеральный баланс
• Поддерживает клеточную гидратацию

🎯 ПРАКТИКА: Начните день со стакана теплой воды с лимоном!
"""
        benefits = """• 🧹 Естественное очищение организма
• 💧 Улучшение клеточной гидратации
• 🍃 Поддержка функции печени
• ⚡ Повышение энергетического уровня"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 СОВЕТ: ДЕТОКС-ГИДРАТАЦИЯ ДЛЯ ОЧИЩЕНИЯ",
            content, "water_advice", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_social_dinner(self):
        content = """
🍷 СОЦИАЛЬНЫЙ УЖИН: СТЕЙК С ОВОЩАМИ И КРАСНЫМ ВИНОМ
КБЖУ: 480 ккал • Белки: 42г • Жиры: 28г • Углеводы: 18г

Ингредиенты на 2 порции:
• Говяжий стейк - 300 г (железо)
• Спаржа - 200 г (фолат)
• Грибы - 150 г (витамин D)
• Красное вино - 100 мл (ресвератрол)
• Чеснок - 3 зубчика
• Тимьян - 2 веточки

Приготовление (25 минут):
1. Стейк обжарить до желаемой прожарки
2. Овощи приготовить на гриле
3. Подавать с бокалом красного вина

🎯 НАУЧНЫЙ ПОДХОД:
Ресвератрол из красного вина активирует гены долголетия (сиртуины) и обладает кардиопротекторными свойствами.
"""
        benefits = """• 🥩 Говядина - гемовое железо для крови
• 🌱 Спаржа - фолат для синтеза ДНК
• 🍄 Грибы - витамин D для иммунитета
• 🍷 Красное вино - антиоксиданты для сердца"""
        
        return self.visual_manager.generate_attractive_post(
            "🍷 СОЦИАЛЬНЫЙ УЖИН: СТЕЙК С ОВОЩАМИ И КРАСНЫМ ВИНОМ",
            content, "light_dinner", benefits
        )

    def generate_evening_balance(self):
        content = """
🌙 ВЕЧЕРНИЙ БАЛАНС: ЛЕГКИЙ УЖИН ДЛЯ ХОРОШЕГО СНА
КБЖУ: 320 ккал • Белки: 25г • Жиры: 18г • Углеводы: 15г

Ингредиенты на 2 порции:
• Индейка - 200 г (триптофан)
• Авокадо - 1/2 шт (полезные жиры)
• Руккола - 100 г (кальций)
• Грецкие орехи - 20 г (мелатонин)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

Приготовление (15 минут):
1. Индейку запечь 12 минут
2. Авокадо нарезать ломтиками
3. Смешать все ингредиенты для салата

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из индейки и мелатонин из грецких орехов способствуют качественному сну и восстановлению.
"""
        benefits = """• 🦃 Индейка - триптофан для серотонина
• 🥑 Авокадо - полезные жиры для гормонов
• 🥬 Руккола - кальций для нервной системы
• 🌰 Грецкие орехи - мелатонин для сна"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 ВЕЧЕРНИЙ БАЛАНС: ЛЕГКИЙ УЖИН ДЛЯ ХОРОШЕГО СНА",
            content, "light_dinner", benefits
        )

    def generate_weekend_starter(self):
        content = """
🎯 СТАРТ ВЫХОДНЫХ: УЖИН ДЛЯ ПОДГОТОВКИ К ОТДЫХУ
КБЖУ: 350 ккал • Белки: 28г • Жиры: 20г • Углеводы: 18г

Ингредиенты на 2 порции:
• Лосось - 250 г (Омега-3)
• Киноа - 80 г (белок)
• Шпинат - 150 г (магний)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (антиоксиданты)
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Лосось приготовить на пару
2. Киноа отварить
3. Шпинат обжарить 2 минуты
4. Подавать все вместе

🎯 НАУЧНЫЙ ПОДХОД:
Омега-3 жирные кислоты из лосося обладают противовоспалительными свойствами и поддерживают здоровье мозга.
"""
        benefits = """• 🐟 Лосось - Омега-3 для мозга и сердца
• 🌾 Киноа - полноценный растительный белок
• 🥬 Шпинат - магний для расслабления
• 🍋 Лимон - витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 СТАРТ ВЫХОДНЫХ: УЖИН ДЛЯ ПОДГОТОВКИ К ОТДЫХУ",
            content, "light_dinner", benefits
        )
# 🏠 СУББОТА - СЕМЕЙНАЯ КУХНЯ (35 РЕЦЕПТОВ)

    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_family_brunch(self):
        content = """
👨‍👩‍👧‍👦 СЕМЕЙНЫЙ БРАНЧ: ВКУСНЫЕ ПАНКЕЙКИ ДЛЯ ВСЕХ
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 52г

Ингредиенты на 4 порции:
• Цельнозерновая мука - 200 г (клетчатка)
• Яйца - 4 шт (белок)
• Молоко - 300 мл (кальций)
• Бананы - 2 шт (калий)
• Греческий йогурт - 200 г (пробиотики)
• Кленовый сироп - 4 ст.л.
• Ягоды - 200 г (антиоксиданты)

Приготовление (25 минут):
1. Смешать муку, яйца, молоко - дети могут помочь!
2. Добавить размятые бананы
3. Жарить на антипригарной сковороде
4. Подавать с йогуртом, ягодами и сиропом

🎯 СЕМЕЙНЫЙ ПОДХОД:
Совместное приготовление развивает моторные навыки у детей и создает позитивные ассоциации со здоровой едой.
"""
        benefits = """• 👨‍👩‍👧‍👦 Совместное времяпрепровождение
• 🍌 Натуральная сладость без сахара
• 🌾 Цельные зерна для энергии
• 🥛 Пробиотики для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СЕМЕЙНЫЙ БРАНЧ: ПАНКЕЙКИ ДЛЯ ВСЕХ",
            content, "saturday_breakfast", benefits
        )

    def generate_weekend_pancakes(self):
        content = """
🥞 ВЫХОДНЫЕ ОЛАДЬИ С ЯБЛОЧНЫМ ПЮРЕ
КБЖУ: 350 ккал • Белки: 15г • Жиры: 10г • Углеводы: 52г

Ингредиенты на 4 порции:
• Овсяная мука - 150 г (бета-глюканы)
• Яблочное пюре - 200 г (пектин)
• Яйца - 3 шт (холин)
• Корица - 2 ч.л. (антиоксиданты)
• Миндальное молоко - 200 мл
• Грецкие орехи - 50 г (Омега-3)

Приготовление (20 минут):
1. Смешать все ингредиенты в большой миске
2. Дети могут формировать оладьи ложкой
3. Жарить по 3-4 минуты с каждой стороны
4. Украсить орехами и корицей

🎯 СЕМЕЙНЫЙ ПОДХОД:
Яблочное пюре заменяет сахар, обеспечивая натуральную сладость и полезную клетчатку.
"""
        benefits = """• 🍎 Натуральная сладость без сахара
• 🌾 Овсяная мука для пищеварения
• 🥚 Белок для сытости
• 🌰 Омега-3 для развития мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 ВЫХОДНЫЕ ОЛАДЬИ С ЯБЛОЧНЫМ ПЮРЕ",
            content, "saturday_breakfast", benefits
        )

    def generate_shared_breakfast(self):
        content = """
🍳 СКРЭМБЛ ДЛЯ ВСЕЙ СЕМЬИ С ОВОЩАМИ
КБЖУ: 320 ккал • Белки: 25г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 4 порции:
• Яйца - 8 шт (лютеин)
• Помидоры черри - 200 г (ликопин)
• Шпинат - 150 г (железо)
• Сладкий перец - 2 шт (витамин C)
• Сыр чеддер - 100 г (кальций)
• Зеленый лук - 30 г (пребиотики)

Приготовление (15 минут):
1. Дети могут помыть овощи и нарезать их
2. Взбить яйца в большой миске
3. Обжарить овощи, залить яйцами
4. Добавить сыр в конце приготовления

🎯 СЕМЕЙНЫЙ ПОДХОД:
Каждый член семьи участвует в процессе - от мытья овощей до сервировки.
"""
        benefits = """• 🥚 Высококачественный белок
• 🥬 Овощи разных цветов - разные витамины
• 🧀 Кальций для костей
• 🌱 Пребиотики для микробиома"""
        
        return self.visual_manager.generate_attractive_post(
            "🍳 СКРЭМБЛ ДЛЯ ВСЕЙ СЕМЬИ С ОВОЩАМИ",
            content, "saturday_breakfast", benefits
        )

    def generate_saturday_omelette(self):
        content = """
🧡 СУББОТНИЙ ОМЛЕТ С ГРИБАМИ И СЫРОМ
КБЖУ: 340 ккал • Белки: 28г • Жиры: 22г • Углеводы: 8г

Ингредиенты на 4 порции:
• Яйца - 8 шт (витамин D)
• Шампиньоны - 300 г (селен)
• Лук - 1 шт (кверцетин)
• Сыр моцарелла - 150 г (триптофан)
• Укроп - 20 г (антиоксиданты)
• Сметана - 100 г (пробиотики)

Приготовление (20 минут):
1. Дети могут натереть сыр и помыть грибы
2. Обжарить лук и грибы до золотистости
3. Залить взбитыми яйцами
4. Посыпать сыром и готовить под крышкой

🎯 СЕМЕЙНЫЙ ПОДХОД:
Процесс приготовления становится игрой - кто красивее украсит свою порцию?
"""
        benefits = """• 🍄 Селен для антиоксидантной защиты
• 🧀 Триптофан для хорошего настроения
• 🥚 Витамин D для иммунитета
• 🌿 Антиоксиданты против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧡 СУББОТНИЙ ОМЛЕТ С ГРИБАМИ И СЫРОМ",
            content, "saturday_breakfast", benefits
        )

    def generate_family_waffles(self):
        content = """
🧇 СЕМЕЙНЫЕ ВАФЛИ С ТВОРОГОМ И ЯГОДАМИ
КБЖУ: 360 ккал • Белки: 20г • Жиры: 14г • Углеводы: 42г

Ингредиенты на 4 порции:
• Творог - 300 г (казеин)
• Яйца - 4 шт (белок)
• Овсяные хлопья - 100 г (клетчатка)
• Разрыхлитель - 2 ч.л.
• Ванильный экстракт - 1 ч.л.
• Смесь ягод - 300 г (антиоксиданты)

Приготовление (30 минут):
1. Измельчить овсяные хлопья в блендере
2. Смешать все ингредиенты для теста
3. Дети могут заливать тесто в вафельницу
4. Подавать с свежими ягодами

🎯 СЕМЕЙНЫЙ ПОДХОД:
Каждый может создать свою вафлю с любимыми топпингами.
"""
        benefits = """• 🧀 Медленный белок для сытости
• 🥚 Полноценный аминокислотный профиль
• 🌾 Клетчатка для пищеварения
• 🍓 Антиоксиданты для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🧇 СЕМЕЙНЫЕ ВАФЛИ С ТВОРОГОМ И ЯГОДАМИ",
            content, "saturday_breakfast", benefits
        )

    def generate_team_smoothie(self):
        content = """
👥 КОМАНДНЫЙ СМУЗИ: КАЖДЫЙ ДОБАВЛЯЕТ СВОЙ ИНГРЕДИЕНТ
КБЖУ: 280 ккал • Белки: 12г • Жиры: 8г • Углеводы: 42г

Ингредиенты на 4 порции:
• Банан - 2 шт (калий)
• Клубника - 200 г (витамин C)
• Шпинат - 100 г (железо)
• Греческий йогурт - 200 г (пробиотики)
• Мед - 2 ст.л. (натуральные пребиотики)
• Семена чиа - 2 ст.л. (Омега-3)

Приготовление (10 минут):
1. Каждый член семьи выбирает свой фрукт
2. Дети могут мыть ягоды и зелень
3. Взрослые нарезают ингредиенты
4. Все вместе взбивают в блендере

🎯 СЕМЕЙНЫЙ ПОДХОД:
Командная работа создает чувство принадлежности и вовлеченности.
"""
        benefits = """• 🍌 Калий для нервной системы
• 🍓 Витамин C для иммунитета
• 🥬 Железо для энергии
• 🌱 Омега-3 для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "👥 КОМАНДНЫЙ СМУЗИ: КАЖДЫЙ ДОБАВЛЯЕТ СВОЙ ИНГРЕДИЕНТ",
            content, "saturday_breakfast", benefits
        )

    def generate_brunch_feast(self):
        content = """
🎪 БРАНЧ-ПРАЗДНИК: СБОРНАЯ ТАРЕЛКА ДЛЯ ВСЕХ
КБЖУ: 400 ккал • Белки: 22г • Жиры: 18г • Углеводы: 38г

Ингредиенты на 4 порции:
• Авокадо - 2 шт (полезные жиры)
• Яйца пашот - 4 шт (белок)
• Цельнозерновой хлеб - 8 ломтиков (клетчатка)
• Лосось слабосоленый - 200 г (Омега-3)
• Руккола - 100 г (кальций)
• Спаржа - 200 г (фолат)

Приготовление (20 минут):
1. Каждый готовит свой компонент
2. Дети могут тостить хлеб и мыть зелень
3. Взрослые готовят яйца и авокадо
4. Собираем общую тарелку для всей семьи

🎯 СЕМЕЙНЫЙ ПОДХОД:
Создание "шведского стола" позволяет каждому выбрать то, что нравится.
"""
        benefits = """• 🥑 Полезные жиры для гормонов
• 🐟 Омега-3 для мозга и сердца
• 🌾 Цельные зерна для энергии
• 🥬 Фолат для синтеза ДНК"""
        
        return self.visual_manager.generate_attractive_post(
            "🎪 БРАНЧ-ПРАЗДНИК: СБОРНАЯ ТАРЕЛКА ДЛЯ ВСЕХ",
            content, "saturday_breakfast", benefits
        )

    # 👨‍🍳 ГОТОВКА (7 рецептов)
    def generate_cooking_workshop(self):
        content = """
🎨 КУЛИНАРНЫЙ МАСТЕР-КЛАСС: ДОМАШНЯЯ ПИЦЦА
КБЖУ: 420 ккал • Белки: 24г • Жиры: 16г • Углеводы: 48г

Ингредиенты на 4 пиццы:
• Мука цельнозерновая - 400 г (клетчатка)
• Дрожжи - 20 г (витамины группы B)
• Томатный соус - 200 г (ликопин)
• Сыр моцарелла - 300 г (кальций)
• Овощи на выбор: перец, помидоры, грибы
• Куриная грудка - 300 г (белок)

Приготовление (60 минут):
1. Дети замешивают тесто - это весело!
2. Каждый создает свою пиццу с любимыми топпингами
3. Взрослые контролируют духовку
4. Дегустация и выбор лучшей пиццы

🎯 СЕМЕЙНЫЙ ПОДХОД:
Творческий процесс развивает воображение и кулинарные навыки.
"""
        benefits = """• 🍅 Ликопин для антиоксидантной защиты
• 🧀 Кальций для костей и зубов
• 🍗 Белок для мышц
• 🌾 Цельные зерна для пищеварения"""
        
        return self.visual_manager.generate_attractive_post(
            "🎨 КУЛИНАРНЫЙ МАСТЕР-КЛАСС: ДОМАШНЯЯ ПИЦЦА",
            content, "saturday_cooking", benefits
        )

    def generate_kids_friendly(self):
        content = """
👶 ДЕТСКИЕ КУЛИНАРНЫЕ ШЕДЕВРЫ: КУРИНЫЕ НУГГЕТСЫ
КБЖУ: 380 ккал • Белки: 32г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 4 порции:
• Куриное филе - 500 г (белок)
• Овсяные хлопья - 150 г (клетчатка)
• Яйца - 2 шт (холин)
• Специи: паприка, чесночный порошок
• Картофель - 4 шт (калий)
• Морковь - 2 шт (бета-каротин)

Приготовление (45 минут):
1. Дети могут измельчать овсяные хлопья
2. Взрослые нарезают курицу полосками
3. Все вместе панируют нуггетсы
4. Запекаем в духовке вместо жарки

🎯 СЕМЕЙНЫЙ ПОДХОД:
Здоровые версии любимых блюд приучают к правильному питанию.
"""
        benefits = """• 🍗 Высококачественный белок
• 🌾 Цельные зерна вместо белой муки
• 🥔 Калий для нервной системы
• 🥕 Витамин A для зрения"""
        
        return self.visual_manager.generate_attractive_post(
            "👶 ДЕТСКИЕ КУЛИНАРНЫЕ ШЕДЕВРЫ: КУРИНЫЕ НУГГЕТСЫ",
            content, "saturday_cooking", benefits
        )

    def generate_team_cooking(self):
        content = """
🤝 КОМАНДНАЯ РАБОТА: СБОРНЫЙ ОБЕД НА ВСЕХ
КБЖУ: 450 ккал • Белки: 28г • Жиры: 20г • Углеводы: 42г

Ингредиенты на 4 порции:
• Киноа - 200 г (полноценный белок)
• Овощи для гриля: кабачки, перец, баклажаны
• Куриные грудки - 400 г (белок)
• Соус песто - 100 г (полезные жиры)
• Салат: руккола, помидоры, огурцы

Распределение задач:
• Дети: мытье овощей, сервировка
• Подростки: нарезка, приготовление соуса
• Взрослые: гриль, контроль готовности

Приготовление (40 минут):
1. Каждый отвечает за свой участок работы
2. Совместная сборка блюд
3. Общая дегустация и обсуждение

🎯 СЕМЕЙНЫЙ ПОДХОД:
Распределение обязанностей учит ответственности и командной работе.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🥦 Овощи разных цветов - разные фитонутриенты
• 🍗 Животный белок для баланса
• 🌿 Полезные жиры для усвоения витаминов"""
        
        return self.visual_manager.generate_attractive_post(
            "🤝 КОМАНДНАЯ РАБОТА: СБОРНЫЙ ОБЕД НА ВСЕХ",
            content, "saturday_cooking", benefits
        )

    def generate_family_baking(self):
        content = """
🍪 СЕМЕЙНАЯ ВЫПЕЧКА: ПП-ПЕЧЕНЬЕ С ОВСЯНКОЙ
КБЖУ: 320 ккал • Белки: 12г • Жиры: 14г • Углеводы: 38г

Ингредиенты на 20 печений:
• Овсяные хлопья - 300 г (бета-глюканы)
• Бананы - 3 шт (натуральная сладость)
• Яйца - 2 шт (белок)
• Кокосовая стружка - 100 г (клетчатка)
• Темный шоколад 85% - 100 г (флавоноиды)
• Корица - 2 ч.л. (антиоксиданты)

Приготовление (35 минут):
1. Дети разминают бананы вилкой
2. Все вместе смешивают ингредиенты
3. Формируем печенье - можно разные фигурки!
4. Выпекаем 20 минут при 180°C

🎯 СЕМЕЙНЫЙ ПОДХОД:
Создание "семейного рецепта", который можно передавать из поколения в поколение.
"""
        benefits = """• 🌾 Бета-глюканы для холестерина
• 🍌 Натуральные сахара без вреда
• 🍫 Флавоноиды для сосудов
• 🟤 Антиоксиданты против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍪 СЕМЕЙНАЯ ВЫПЕЧКА: ПП-ПЕЧЕНЬЕ С ОВСЯНКОЙ",
            content, "saturday_cooking", benefits
        )

    def generate_weekend_bbq(self):
        content = """
🔥 ВЫХОДНОЙ БАРБЕКЮ: ЗДОРОВЫЕ ШАШЛЫЧКИ
КБЖУ: 380 ккал • Белки: 35г • Жиры: 18г • Углеводы: 22г

Ингредиенты на 4 порции:
• Куриное филе - 500 г (белок)
• Цукини - 2 шт (калий)
• Перец болгарский - 3 шт (витамин C)
• Лук красный - 2 шт (кверцетин)
• Маринад: йогурт, специи, лимонный сок
• Лаваш цельнозерновой - 4 шт

Приготовление (60 минут + маринование):
1. Все вместе нарезаем ингредиенты для шампуров
2. Дети могут нанизывать на шпажки - развивает моторику
3. Маринуем в йогуртовом маринаде 2 часа
4. Готовим на гриле или в духовке

🎯 СЕМЕЙНЫЙ ПОДХОД:
Активный отдых на свежем воздухе сочетается с полезным питанием.
"""
        benefits = """• 🍗 Постный белок для мышц
• 🥒 Овощи на гриле - максимум пользы
• 🧅 Кверцетин против воспаления
• 🍋 Витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ВЫХОДНОЙ БАРБЕКЮ: ЗДОРОВЫЕ ШАШЛЫЧКИ",
            content, "saturday_cooking", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_family_lasagna(self):
        content = """
🍝 СЕМЕЙНАЯ ЛАЗАНЬЯ С ОВОЩАМИ И ИНДЕЙКОЙ
КБЖУ: 420 ккал • Белки: 32г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 6 порций:
• Листы лазаньи - 12 шт (углеводы)
• Фарш индейки - 500 г (белок)
• Шпинат - 300 г (железо)
• Морковь - 2 шт (бета-каротин)
• Творог - 400 г (казеин)
• Сыр пармезан - 100 г (кальций)
• Томатный соус - 400 мл (ликопин)

Приготовление (60 минут):
1. Дети моют и нарезают овощи
2. Подростки готовят соус и фарш
3. Взрослые собирают лазанью слоями
4. Запекаем 40 минут до золотистой корочки

🎯 СЕМЕЙНЫЙ ПОДХОД:
Создание большого блюда на всю семью учит планированию и сотрудничеству.
"""
        benefits = """• 🦃 Постный белок для мышц
• 🥬 Железо для энергии
• 🧀 Кальций для костей
• 🍅 Ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍝 СЕМЕЙНАЯ ЛАЗАНЬЯ С ОВОЩАМИ И ИНДЕЙКОЙ",
            content, "family_dinner", benefits
        )

    def generate_saturday_pizza(self):
        content = """
🍕 СУББОТНЯЯ ПИЦЦА: КАЖДЫЙ СВОЙ УГОЛОК
КБЖУ: 380 ккал • Белки: 22г • Жиры: 16г • Углеводы: 42г

Ингредиенты на 4 порции:
• Тесто для пиццы - 1 большой пласт
• Томатный соус - 200 г (ликопин)
• Сыр моцарелла - 300 г (кальций)
• Овощи: перец, помидоры, лук, грибы
• Ветчина - 200 г (белок)
• Оливки - 100 г (полезные жиры)

Приготовление (35 минут):
1. Делим пиццу на 4 сектора
2. Каждый украшает свой сектор любимыми топпингами
3. Выпекаем 15-20 минут при 220°C
4. Дегустация и обмен кусочками

🎯 СЕМЕЙНЫЙ ПОДХОД:
Индивидуальный подход в рамках общего блюда удовлетворяет разные вкусы.
"""
        benefits = """• 🍅 Ликопин для простаты и кожи
• 🧀 Кальций для зубов и костей
• 🥩 Белок для сытости
• 🫒 Мононенасыщенные жиры для сердца"""
        
        return self.visual_manager.generate_attractive_post(
            "🍕 СУББОТНЯЯ ПИЦЦА: КАЖДЫЙ СВОЙ УГОЛОК",
            content, "family_dinner", benefits
        )

    def generate_shared_platter(self):
        content = """
🎪 БОЛЬШАЯ ТАРЕЛКА: СБОРНЫЙ УЖИН ДЛЯ ВСЕХ
КБЖУ: 350 ккал • Белки: 28г • Жиры: 20г • Углеводы: 18г

Ингредиенты на 4 порции:
• Запеченная курица - 400 г (белок)
• Овощи гриль: баклажаны, цукини, перец
• Киноа - 200 г (полноценный белок)
• Соусы: тахини, йогуртовый, песто
• Оливки и каперсы - 100 г
• Свежая зелень - 100 г

Приготовление (30 минут):
1. Каждый готовит свой компонент
2. Собираем общую большую тарелку
3. Каждый накладывает себе то, что хочет
4. Общаемся за ужином без спешки

🎯 СЕМЕЙНЫЙ ПОДХОД:
"Шведский стол" позволяет учитывать предпочтения каждого члена семьи.
"""
        benefits = """• 🍗 Разнообразные источники белка
• 🥦 Овощи разных цветов - разные витамины
• 🌾 Киноа - полноценный растительный белок
• 🌿 Свежая зелень - хлорофилл для детокса"""
        
        return self.visual_manager.generate_attractive_post(
            "🎪 БОЛЬШАЯ ТАРЕЛКА: СБОРНЫЙ УЖИН ДЛЯ ВСЕХ",
            content, "family_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_family_dessert(self):
        content = """
🍓 СЕМЕЙНЫЙ ДЕСЕРТ: ФРУКТОВАЯ ПИЦЦА
КБЖУ: 280 ккал • Белки: 12г • Жиры: 8г • Углеводы: 42г

Ингредиенты на 4 порции:
• Греческий йогурт - 400 г (пробиотики)
• Мед - 4 ст.л. (натуральные пребиотики)
• Ванильный экстракт - 2 ч.л.
• Фрукты: клубника, киви, банан, черника
• Кокосовая стружка - 50 г (клетчатка)
• Семена чиа - 2 ст.л. (Омега-3)

Приготовление (15 минут):
1. Смешать йогурт с медом и ванилью
2. Выложить "тесто" на большую тарелку
3. Дети украшают фруктами как пиццу
4. Посыпать кокосовой стружкой и семенами

🎯 СЕМЕЙНЫЙ ПОДХОД:
Творческий десерт без выпечки - безопасно даже для самых маленьких.
"""
        benefits = """• 🥛 Пробиотики для микробиома
• 🍯 Натуральные пребиотики
• 🍓 Витамины и антиоксиданты
• 🌱 Омега-3 для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🍓 СЕМЕЙНЫЙ ДЕСЕРТ: ФРУКТОВАЯ ПИЦЦА",
            content, "saturday_dessert", benefits
        )

    def generate_weekend_treat(self):
        content = """
🎂 ВЫХОДНОЙ ТОРТИК: ТВОРОЖНО-ФРУКТОВЫЙ
КБЖУ: 320 ккал • Белки: 20г • Жиры: 12г • Углеводы: 35г

Ингредиенты на 6 порций:
• Творог - 500 г (казеин)
• Желатин - 20 г (коллаген)
• Мед - 4 ст.л.
• Ванильный экстракт - 2 ч.л.
• Фруктовое пюре - 300 г
• Орехи и ягоды для украшения

Приготовление (20 минут + охлаждение):
1. Дети могут измельчать фрукты в пюре
2. Взрослые работают с желатином
3. Все вместе украшают торт
4. Охлаждаем 4 часа до застывания

🎯 СЕМЕЙНЫЙ ПОДХОД:
Создание праздничного настроения в обычный выходной день.
"""
        benefits = """• 🧀 Медленный белок для ночного восстановления
• 🍓 Натуральные фрукты вместо сахара
• 🌰 Орехи - полезные жиры и витамин E
• 🥛 Коллаген для кожи и суставов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎂 ВЫХОДНОЙ ТОРТИК: ТВОРОЖНО-ФРУКТОВЫЙ",
            content, "saturday_dessert", benefits
        )

    def generate_shared_sweets(self):
        content = """
🍫 ОБЩИЕ СЛАДОСТИ: ШОКОЛАДНЫЕ ФОНДЮ
КБЖУ: 250 ккал • Белки: 8г • Жиры: 14г • Углеводы: 25г

Ингредиенты на 4 порции:
• Темный шоколад 85% - 200 г (флавоноиды)
• Кокосовые сливки - 200 мл (МСТ)
• Мед - 2 ст.л.
• Фрукты для макания: бананы, клубника, яблоки
• Орехи: миндаль, грецкие орехи

Приготовление (15 минут):
1. Растопить шоколад с кокосовыми сливками
2. Каждый нарезает свои любимые фрукты
3. Ставим фондю в центр стола
4. Макаем фрукты и общаемся

🎯 СЕМЕЙНЫЙ ПОДХОД:
Интерактивный десерт создает атмосферу ресторана дома.
"""
        benefits = """• 🍫 Флавоноиды для сосудов и мозга
• 🥥 Среднецепочечные триглицериды для энергии
• 🍎 Клетчатка для пищеварения
• 🌰 Витамин E для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ОБЩИЕ СЛАДОСТИ: ШОКОЛАДНЫЕ ФОНДЮ",
            content, "saturday_dessert", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_family_nutrition_advice(self):
        content = """
👨‍👩‍👧‍👦 СЕМЕЙНОЕ ПИТАНИЕ: КАК СОХРАНИТЬ БАЛАНС И ГАРМОНИЮ

🎯 5 КЛЮЧЕВЫХ ПРИНЦИПОВ СЕМЕЙНОГО ПИТАНИЯ:

1. 🎪 СОВМЕСТНЫЕ ТРАПЕЗЫ
• Еда - это не только питание, но и общение
• Минимум 1 совместный прием пищи в день
• Отключаем гаджеты за столом

2. 👶 УЧЕТ ВОЗРАСТНЫХ ОСОБЕННОСТЕЙ
• Дети: больше кальция и белка для роста
• Подростки: железо и цинк для развития
• Взрослые: антиоксиданты и клетчатка
• Пожилые: витамин D и белок против саркопении

3. 🍽️ ГИБКОСТЬ И УВАЖЕНИЕ
• Учитываем вкусовые предпочтения каждого
• Не заставляем есть то, что не нравится
• Предлагаем здоровые альтернативы

4. 🎨 ТВОРЧЕСКИЙ ПОДХОД
• Превращаем готовку в игру
• Украшаем блюда вместе
• Создаем семейные кулинарные традиции

5. 📚 ОБРАЗОВАНИЕ ЧЕРЕЗ ПРАКТИКУ
• Объясняем пользу продуктов в доступной форме
• Учим читать этикетки
• Вовлекаем в планирование меню

🎯 ПРАКТИЧЕСКОЕ ЗАДАНИЕ:
Проведите семейный кулинарный вечер в эти выходные!
"""
        benefits = """• 👨‍👩‍👧‍👦 Укрепление семейных связей на 40%
• 🍽️ Формирование здоровых пищевых привычек
• 🎨 Развитие кулинарных навыков у детей
• 💫 Создание позитивных семейных традиций"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СОВЕТ: СЕМЕЙНОЕ ПИТАНИЕ И ГАРМОНИЯ",
            content, "family_advice", benefits
        )

    def generate_cooking_together_advice(self):
        content = """
👨‍🍳 СОВМЕСТНАЯ ГОТОВКА: КАК ПРЕВРАТИТЬ КУХНЮ В СЕМЕЙНЫЙ КЛУБ

🎯 РАСПРЕДЕЛЕНИЕ ОБЯЗАННОСТЕЙ ПО ВОЗРАСТАМ:

👶 ДЕТИ 3-6 ЛЕТ:
• Мытье овощей и фруктов
• Перемешивание ингредиентов
• Украшение готовых блюд
• Сервировка стола

🧒 ДЕТИ 7-12 ЛЕТ:
• Нарезка мягких продуктов
• Взвешивание ингредиентов
• Приготовление простых соусов
• Контроль времени по таймеру

👦 ПОДРОСТКИ 13-17 ЛЕТ:
• Работа с духовкой и плитой
• Приготовление сложных блюд
• Планирование меню
• Бюджетирование покупок

👨‍👩 ВЗРОСЛЫЕ:
• Контроль безопасности
• Обучение технике приготовления
• Координация процесса
• Создание сложных компонентов

🎯 БЕЗОПАСНОСТЬ НА КУХНЕ:
• Обучаем правильному обращению с ножами
• Контролируем работу с горячими поверхностями
• Создаем безопасную среду для самых маленьких

🎯 ПРАКТИКА: Назначьте каждого ответственным за свой участок!
"""
        benefits = """• 🔪 Развитие моторных навыков и координации
• 🧮 Обучение математике через взвешивание
• ⏱️ Развитие чувства времени и ответственности
• 💰 Финансовая грамотность через планирование покупок"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 СОВЕТ: СОВМЕСТНАЯ ГОТОВКА С ДЕТЬМИ",
            content, "family_advice", benefits
        )
# 📝 ЧАСТЬ 11 - ВОСКРЕСЕНЬЕ - ПЛАНИРОВАНИЕ (35 РЕЦЕПТОВ)

    # 🍽️ ЗАВТРАКИ (7 рецептов)
    def generate_brunch_feast(self):
        content = """
🥘 ВОСКРЕСНЫЙ БРАНЧ: ЗАПАСАЕМСЯ ЭНЕРГИЕЙ НА НЕДЕЛЮ
КБЖУ: 420 ккал • Белки: 25г • Жиры: 18г • Углеводы: 45г

Ингредиенты на 4 порции + заготовки:
• Яйца - 8 шт (белок)
• Овсяные хлопья - 200 г (бета-глюканы) 
• Греческий йогурт - 500 г (пробиотики)
• Ягоды замороженные - 300 г (антиоксиданты)
• Семена чиа - 50 г (Омега-3)
• Орехи грецкие - 100 г (мелатонин)

Приготовление (30 минут):
1. Варим 4 яйца вкрутую на завтраки на неделю
2. Готовим овсянку порционно в банках
3. Делаем йогуртовые парфе с ягодами
4. Упаковываем в контейнеры для быстрых завтраков

🎯 MEAL PREP СТРАТЕГИЯ:
Приготовление завтраков на 3 дня вперед экономит 15 минут каждое утро.
"""
        benefits = """• 🥚 Белок для сытости до обеда
• 🌾 Медленные углеводы для энергии
• 🥛 Пробиотики для иммунитета
• 🍓 Антиоксиданты против окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "🥘 ВОСКРЕСНЫЙ БРАНЧ: ЗАПАС ЭНЕРГИИ НА НЕДЕЛЮ",
            content, "sunday_breakfast", benefits
        )

    def generate_lazy_breakfast(self):
        content = """
😴 ЛЕНИВЫЙ ЗАВТРАК: ГОТОВИМ 5 ПОРЦИЙ ЗА РАЗ
КБЖУ: 380 ккал • Белки: 20г • Жиры: 15г • Углеводы: 42г

Ингредиенты на 5 порций:
• Творог 5% - 600 г (казеин)
• Овсяные хлопья - 150 г (клетчатка)
• Яблоки - 3 шт (пектин)
• Корица - 2 ст.л. (антиоксиданты)
• Миндаль - 100 г (витамин E)
• Стевия - по вкусу

Приготовление (20 минут):
1. Яблоки нарезать кубиками
2. Смешать все ингредиенты в большой миске
3. Разложить по 5 порционным контейнерам
4. Хранить в холодильнике до 4 дней

🎯 MEAL PREP СТРАТЕГИЯ:
Готовые завтраки экономят время и гарантируют здоровый старт дня.
"""
        benefits = """• 🧀 Медленный белок для длительной сытости
• 🍎 Растворимая клетчатка для пищеварения
• 🌰 Витамин E для защиты клеток
• 🟤 Регуляция уровня сахара в крови"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ЛЕНИВЫЙ ЗАВТРАК: 5 ПОРЦИЙ ЗА 20 МИНУТ",
            content, "sunday_breakfast", benefits
        )

    def generate_meal_prep_breakfast(self):
        content = """
📦 ЗАВТРАКИ В БАНКАХ: ГОТОВАЯ СИСТЕМА НА НЕДЕЛЮ
КБЖУ: 350 ккал • Белки: 18г • Жиры: 12г • Углеводы: 45г

Ингредиенты на 7 банок:
• Овсяные хлопья - 350 г (бета-глюканы)
• Семена льна - 70 г (лигнаны)
• Кокосовая стружка - 100 г (МСТ)
• Протеин ванильный - 140 г (белок)
• Сухофрукты без сахара - 200 г
• Орехи - 200 г

Сборка (15 минут):
1. В каждую банку: 50г овсянки + 10г семян
2. Добавить 20г протеина + 15г кокосовой стружки
3. Верхний слой: 30г сухофруктов + 30г орехов
4. Утром залить горячей водой/молоком

🎯 MEAL PREP СТРАТЕГИЯ:
Идеальное решение для самых занятых утр - просто добавить жидкость!
"""
        benefits = """• 🌾 Бета-глюканы для контроля холестерина
• 🌱 Лигнаны для гормонального баланса
• 🥥 Быстрая энергия без скачков сахара
• 💪 Белок для мышечного синтеза"""
        
        return self.visual_manager.generate_attractive_post(
            "📦 ЗАВТРАКИ В БАНКАХ: СИСТЕМА НА 7 ДНЕЙ",
            content, "sunday_breakfast", benefits
        )

    def generate_sunday_porridge(self):
        content = """
🍲 ВОСКРЕСНАЯ КАША: БАЗА ДЛЯ ВСЕЙ НЕДЕЛИ
КБЖУ: 320 ккал • Белки: 15г • Жиры: 10г • Углеводы: 45г

Ингредиенты на 4 порции + заготовки:
• Гречневая крупа - 300 г (рутин)
• Тыква - 500 г (бета-каротин)
• Кунжут - 50 г (кальций)
• Корица - 1 ст.л. (полифенолы)
• Яблоки - 4 шт (кверцетин)

Приготовление (25 минут):
1. Гречку отварить до готовности
2. Тыкву запечь и размять в пюре
3. Смешать гречку с тыквенным пюре
4. Разложить на 4 порции, украсить перед подачей

🎯 MEAL PREP СТРАТЕГИЯ:
Готовую кашу можно разогревать 3 дня, добавляя свежие фрукты.
"""
        benefits = """• 🌾 Рутин для укрепления сосудов
• 🎃 Бета-каротин для иммунитета и зрения
• 🌱 Кальций для костей и нервной системы
• 🍎 Кверцетин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 ВОСКРЕСНАЯ КАША: БАЗА ДЛЯ ЗАВТРАКОВ",
            content, "sunday_breakfast", benefits
        )

    def generate_prep_friendly_toast(self):
        content = """
🍞 ТОСТЫ ДЛЯ MEAL PREP: ЗАГОТОВКИ НА УТРО
КБЖУ: 290 ккал • Белки: 16г • Жиры: 12г • Углеводы: 30г

Ингредиенты на 4 порции:
• Хлеб цельнозерновой - 8 ломтиков (клетчатка)
• Авокадо - 2 шт (мононенасыщенные жиры)
• Творожный сыр - 200 г (белок)
• Лосось слабосоленый - 200 г (Омега-3)
• Руккола - 100 г (нитраты)
• Лимонный сок - 2 ст.л.

Подготовка (15 минут):
1. Намазать творожный сыр на хлеб
2. Авокадо размять с лимонным соком
3. Упаковать компоненты отдельно
4. Утром собрать за 2 минуты

🎯 MEAL PREP СТРАТЕГИЯ:
Раздельное хранение компонентов сохраняет свежесть и хрусткость.
"""
        benefits = """• 🥑 Полезные жиры для усвоения витаминов
• 🐟 Омега-3 для мозга и против воспаления
• 🥬 Нитраты для улучшения кровотока
• 🌾 Цельные зерна для стабильной энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 ТОСТЫ ДЛЯ MEAL PREP: СБОРКА ЗА 2 МИНУТЫ",
            content, "sunday_breakfast", benefits
        )

    def generate_efficient_smoothie(self):
        content = """
⚡ ЭФФЕКТИВНЫЙ СМУЗИ: ЗАМОРОЗКА НА НЕДЕЛЮ
КБЖУ: 280 ккал • Белки: 18г • Жиры: 8г • Углеводы: 35г

Ингредиенты на 7 порций:
• Шпинат замороженный - 500 г (железо)
• Бананы - 7 шт (калий)
• Ягоды замороженные - 700 г (антиоксиданты)
• Протеин ванильный - 210 г (белок)
• Семена льна - 70 г (Омега-3)
• Миндальное молоко - 1 л

Подготовка (20 минут):
1. В каждый пакет/контейнер: горсть шпината
2. Добавить по 1 банану и 100г ягод
3. Добавить 30г протеина + 10г семян
4. Утром взбить с 200 мл молока

🎯 MEAL PREP СТРАТЕГИЯ:
Замороженные смеси сохраняют питательные вещества до 3 месяцев.
"""
        benefits = """• 🥬 Железо для энергии и оксигенации
• 🍌 Калий для нервной и мышечной функции
• 🫐 Антиоксиданты против окислительного стресса
• 🌱 Омега-3 для мозга и против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭФФЕКТИВНЫЙ СМУЗИ: 7 ПОРЦИЙ В МОРОЗИЛКЕ",
            content, "sunday_breakfast", benefits
        )

    def generate_planning_omelette(self):
        content = """
📊 ОМЛЕТ ДЛЯ ПЛАНИРОВАНИЯ: БЕЛКОВЫЙ ЗАПАС
КБЖУ: 310 ккал • Белки: 28г • Жиры: 18г • Углеводы: 8г

Ингредиенты на 4 порции:
• Яйца - 12 шт (холин)
• Брокколи - 300 г (сульфорафан)
• Грибы - 300 г (витамин D)
• Лук - 2 шт (кверцетин)
• Сыр фета - 200 г (кальций)
• Зелень - 100 г (хлорофилл)

Приготовление (30 минут):
1. Овощи нарезать и обжарить
2. Залить взбитыми яйцами
3. Запечь в духовке 20 минут
4. Разрезать на 4 порции, хранить 3 дня

🎯 MEAL PREP СТРАТЕГИЯ:
Порционные омлеты - готовый завтрак или обед с высоким содержанием белка.
"""
        benefits = """• 🥚 Холин для мозга и памяти
• 🥦 Сульфорафан для детокса и против рака
• 🍄 Витамин D для иммунитета и костей
• 🧀 Кальций для нервной проводимости"""
        
        return self.visual_manager.generate_attractive_post(
            "📊 ОМЛЕТ ДЛЯ ПЛАНИРОВАНИЯ: БЕЛК НА 3 ДНЯ",
            content, "sunday_breakfast", benefits
        )

    # 🍽️ ОБЕДЫ (7 рецептов)
    def generate_weekly_prep_lunch(self):
        content = """
🍱 ОБЕДЫ НА НЕДЕЛЮ: СИСТЕМА КОНТЕЙНЕРОВ
КБЖУ: 450 ккал • Белки: 35г • Жиры: 18г • Углеводы: 42г

Ингредиенты на 5 обедов:
• Куриные грудки - 1 кг (белок)
• Бурый рис - 500 г (магний)
• Брокколи - 1 кг (сульфорафан)
• Морковь - 500 г (бета-каротин)
• Нут - 400 г (растительный белок)
• Соус терияки без сахара - 200 мл

Приготовление (45 минут):
1. Курицу запечь целиком (25 минут)
2. Рис и нут отварить (20 минут)
3. Овощи приготовить на пару (10 минут)
4. Разложить по 5 контейнерам

🎯 MEAL PREP СТРАТЕГИЯ:
5 готовых обедов экономят 2.5 часа в неделю!
"""
        benefits = """• 🍗 Высококачественный белок для мышц
• 🍚 Магний для энергетического обмена
• 🥦 Антиоксиданты для защиты клеток
• 🥕 Витамин A для иммунитета и зрения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍱 ОБЕДЫ НА НЕДЕЛЮ: 5 КОНТЕЙНЕРОВ ЗА 45 МИНУТ",
            content, "sunday_lunch", benefits
        )

    def generate_batch_cooking_lunch(self):
        content = """
👨‍🍳 ПОРЦИОННАЯ ГОТОВКА: ОСНОВЫ ДЛЯ РАЗНЫХ БЛЮД
КБЖУ: 400 ккал • Белки: 30г • Жиры: 15г • Углеводы: 45г

БАЗОВЫЕ КОМПОНЕНТЫ (на 4-6 обедов):
• Фарш индейки - 800 г (белок)
• Киноа - 400 г (полноценный белок)
• Овощная смесь: перец, цукини, лук - 1.5 кг
• Чечевица - 300 г (клетчатка)
• Томатный соус - 500 мл (ликопин)

Приготовление (60 минут):
1. Фарш обжарить с луком (15 минут)
2. Киноа и чечевицу отварить (20 минут)
3. Овощи нарезать и разделить на порции
4. Создать основу для разных блюд недели

🎯 MEAL PREP СТРАТЕГИЯ:
Одни базовые компоненты = 5 разных блюд в течение недели.
"""
        benefits = """• 🦃 Постный белок для мышечного синтеза
• 🌾 Полный набор аминокислот
• 🥬 Разнообразие овощей - разные витамины
• 🍅 Ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 ПОРЦИОННАЯ ГОТОВКА: БАЗА ДЛЯ 5 РАЗНЫХ ОБЕДОВ",
            content, "sunday_lunch", benefits
        )

    def generate_efficient_lunch(self):
        content = """
⚡ ЭФФЕКТИВНЫЙ ОБЕД: МИНИМУМ ВРЕМЕНИ - МАКСИМУМ ПОЛЬЗЫ
КБЖУ: 380 ккал • Белки: 32г • Жиры: 16г • Углеводы: 35г

Ингредиенты на 4 обеда:
• Лосось - 600 г (Омега-3)
• Сладкий картофель - 800 г (бета-каротин)
• Спаржа - 600 г (фолат)
• Булгур - 300 г (клетчатка)
• Лимон - 2 шт (витамин C)
• Травы: розмарин, укроп

Приготовление (35 минут):
1. Лосось и овощи запечь на одном противне (25 минут)
2. Булгур залить кипятком на 15 минут
3. Разделить на 4 контейнера
4. Сбрызнуть лимонным соком перед едой

🎯 MEAL PREP СТРАТЕГИЯ:
Метод "one pan" - максимум пользы при минимуме мытья посуды.
"""
        benefits = """• 🐟 Омега-3 для мозга и против воспаления
• 🍠 Сложные углеводы для энергии
• 🌱 Фолат для синтеза ДНК
• 🍋 Витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭФФЕКТИВНЫЙ ОБЕД: ОДИН ПРОТИВЕНЬ - 4 ПОРЦИИ",
            content, "sunday_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_weekly_prep_chicken(self):
        content = """
🍗 КУРИЦА НА НЕДЕЛЮ: УНИВЕРСАЛЬНАЯ ОСНОВА
КБЖУ: 320 ккал • Белки: 40г • Жиры: 14г • Углеводы: 8г

Ингредиенты на 4-6 ужинов:
• Куриные бедра - 1.2 кг (белок)
• Брокколи - 800 г (глюкозинолаты)
• Цветная капуста - 800 г (сульфорафан)
• Морковь - 500 г (бета-каротин)
• Лук - 3 шт (кверцетин)
• Чеснок - 1 головка (аллицин)

Приготовление (40 минут):
1. Курицу нарезать, замариновать (10 минут)
2. Овощи нарезать крупно
3. Запекать 30 минут при 200°C
4. Разделить на контейнеры для разных блюд

🎯 MEAL PREP СТРАТЕГИЯ:
Универсальная основа для салатов, рагу, обертываний.
"""
        benefits = """• 🍗 Высококачественный белок для восстановления
• 🥦 Детокс-компоненты для очищения
• 🥕 Антиоксиданты для защиты от стресса
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🍗 КУРИЦА НА НЕДЕЛЮ: ОСНОВА ДЛЯ 6 УЖИНОВ",
            content, "meal_prep_dinner", benefits
        )

    def generate_batch_cooking(self):
        content = """
👨‍🍳 МАССОВАЯ ГОТОВКА: СУПЫ И РАГУ НА ЗАМОРОЗКУ
КБЖУ: 280 ккал • Белки: 22г • Жиры: 10г • Углеводы: 28г

Ингредиенты на 8-10 порций:
• Говядина - 1 кг (железо)
• Овощи: сельдерей, морковь, лук - 2 кг
• Чечевица - 400 г (растительный белок)
• Томаты в собственном соку - 800 г (ликопин)
• Специи: лавровый лист, тимьян
• Бульон овощной - 2 л

Приготовление (90 минут):
1. Мясо обжарить до корочки (15 минут)
2. Овощи нарезать кубиками
3. Тушить 1.5 часа на медленном огне
4. Разлить по контейнерам, заморозить

🎯 MEAL PREP СТРАТЕГИЯ:
Замороженные порции - готовый ужин за 10 минут разогрева.
"""
        benefits = """• 🥩 Гемовое железо для профилактики анемии
• 🥬 Овощное разнообразие - полный набор витаминов
• 🌱 Растительный и животный белок для баланса
• 🍅 Термообработанные томаты - максимум ликопина"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 МАССОВАЯ ГОТОВКА: 10 ПОРЦИЙ СУПА В МОРОЗИЛКЕ",
            content, "meal_prep_dinner", benefits
        )

    def generate_container_meal(self):
        content = """
📦 КОНТЕЙНЕРНЫЕ УЖИНЫ: ГОТОВАЯ СБОРКА
КБЖУ: 350 ккал • Белки: 30г • Жиры: 16г • Углеводы: 25г

Ингредиенты на 4 ужина:
• Тофу - 600 г (изофлавоны)
• Киноа - 300 г (полноценный белок)
• Овощи на пару: брокколи, цветная капуста - 1 кг
• Авокадо - 2 шт (полезные жиры)
• Нут - 400 г (клетчатка)
• Тахини - 100 г (кальций)

Сборка (20 минут):
1. Тофу обжарить кубиками (10 минут)
2. Киноа отварить (15 минут)
3. Овощи приготовить на пару (8 минут)
4. Собрать 4 контейнера в стиле "боул"

🎯 MEAL PREP СТРАТЕГИЯ:
Готовые боулы - здоровый ужин без мыслей "что приготовить".
"""
        benefits = """• 🧈 Изофлавоны для гормонального баланса
• 🌾 Полноценный растительный белок
• 🥑 Полезные жиры для усвоения витаминов
• 🫕 Кальций для костей и нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "📦 КОНТЕЙНЕРНЫЕ УЖИНЫ: 4 БОУЛА НА ВЕЧЕР",
            content, "meal_prep_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_weekly_treat(self):
        content = """
🍰 НЕДЕЛЬНЫЙ ДЕСЕРТ: ЗДОРОВЫЕ СЛАДОСТИ ВПРОК
КБЖУ: 180 ккал • Белки: 12г • Жиры: 8г • Углеводы: 18г

Ингредиенты на 8 порций:
• Творог - 600 г (казеин)
• Желатин - 30 г (коллаген)
• Какао-порошок - 50 г (флавоноиды)
• Стевия - по вкусу
• Ванильный экстракт - 2 ч.л.
• Ягоды для украшения - 200 г

Приготовление (20 минут + охлаждение):
1. Творог взбить с какао и стевией
2. Добавить растворенный желатин
3. Разлить по 8 формам, украсить ягодами
4. Охладить 4 часа, хранить 5 дней

🎯 MEAL PREP СТРАТЕГИЯ:
Готовые десерты предотвращают спонтанные покупки сладостей.
"""
        benefits = """• 🧀 Медленный белок для ночного восстановления
• 🍫 Флавоноиды для улучшения кровотока
• 0️⃣ Без сахара - безопасно для инсулина
• 🍓 Антиоксиданты для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 НЕДЕЛЬНЫЙ ДЕСЕРТ: 8 ПОРЦИЙ БЕЗ САХАРА",
            content, "sunday_dessert", benefits
        )

    def generate_prep_friendly_dessert(self):
        content = """
❄️ ДЕСЕРТ ДЛЯ ЗАМОРОЗКИ: ПОЛЕЗНОЕ МОРОЖЕНОЕ
КБЖУ: 160 ккал • Белки: 10г • Жиры: 6г • Углеводы: 18г

Ингредиенты на 12 порций:
• Бананы спелые - 6 шт (натуральная сладость)
• Ягоды замороженные - 400 г (антиоксиданты)
• Греческий йогурт - 400 г (пробиотики)
• Ванильный протеин - 120 г (белок)
• Миндальное молоко - 200 мл

Приготовление (15 минут):
1. Бананы очистить, нарезать, заморозить
2. Все ингредиенты взбить в блендере
3. Разлить по формам для мороженого
4. Заморозить 6 часов, хранить 1 месяц

🎯 MEAL PREP СТРАТЕГИЯ:
Замороженные десерты всегда под рукой для здорового перекуса.
"""
        benefits = """• 🍌 Натуральная сладость без добавленного сахара
• 🫐 Антиоксиданты против окислительного стресса
• 🥛 Пробиотики для здоровья кишечника
• 💪 Белок для мышечного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "❄️ ДЕСЕРТ ДЛЯ ЗАМОРОЗКИ: ПОЛЕЗНОЕ МОРОЖЕНОЕ",
            content, "sunday_dessert", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_meal_prep_guide_advice(self):
        content = """
📊 MEAL PREP ГИД: КАК ПЛАНИРОВАТЬ ПИТАНИЕ НА НЕДЕЛЮ

🎯 5 СТУПЕНЕЙ УСПЕШНОГО MEAL PREP:

1. 📝 ПЛАНИРОВАНИЕ (10 минут)
• Составьте меню на неделю с учетом расписания
• Учитывайте сезонность продуктов
• Создайте список покупок

2. 🛒 ПОКУПКИ (60-90 минут)
• Закупайтесь 1 раз в неделю
• Выбирайте качественные продукты
• Покупайте оптом для экономии

3. 🍳 ПРИГОТОВЛЕНИЕ (2-3 часа в воскресенье)
• Начните с самых долгих процессов
• Используйте многозадачность (духовка + плита)
• Привлекайте семью для помощи

4. 📦 УПАКОВКА (30 минут)
• Используйте одинаковые контейнеры
• Подписывайте даты приготовления
• Распределяйте по дням недели

5. 🗄️ ХРАНЕНИЕ
• Холодильник: 3-4 дня
• Морозильник: 1-3 месяца
• Раздельное хранение соусов и хрустящих компонентов

🎯 РАСЧЕТ ЭКОНОМИИ:
• Время: экономия 5-7 часов в неделю
• Деньги: снижение затрат на 20-30%
• Здоровье: 100% контроль качества

🎯 ПРАКТИЧЕСКОЕ ЗАДАНИЕ:
Спланируйте свое первое воскресенье meal prep!
"""
        benefits = """• ⏱️ Экономия 5-7 часов в неделю на готовке
• 💰 Снижение затрат на питание на 20-30%
• 🍽️ Гарантия здорового рациона всю неделю
• 😌 Снижение стресса и decision fatigue"""
        
        return self.visual_manager.generate_attractive_post(
            "📊 СОВЕТ: ПОЛНЫЙ ГИД ПО MEAL PREP",
            content, "planning_advice", benefits
        )

    def generate_weekly_planning_advice(self):
        content = """
🗓️ НЕДЕЛЬНОЕ ПЛАНИРОВАНИЕ: СИСТЕМА ДЛЯ ЗАНЯТЫХ

📈 ШАБЛОН ПЛАНИРОВАНИЯ НА НЕДЕЛЮ:

ПОНЕДЕЛЬНИК - 🧠 МОЗГ:
• Завтрак: овсянка с орехами + ягоды
• Обед: лосось + киноа + брокколи
• Ужин: омлет с овощами + авокадо

ВТОРНИК - 💪 СИЛА:
• Завтрак: творог + фрукты + семена
• Обед: курица + бурый рис + овощи
• Ужин: рыба + сладкий картофель + спаржа

СРЕДА - 🥬 ОЧИЩЕНИЕ:
• Завтрак: зеленый смузи + орехи
• Обед: овощной суп + нут
• Ужин: тофу + овощи гриль + киноа

ЧЕТВЕРГ - 🍠 ЭНЕРГИЯ:
• Завтрак: овсяные блинчики + ягоды
• Обед: паста из цельных злаков + соус
• Ужин: чечевица + овощи + авокадо

ПЯТНИЦА - 🎉 БАЛАНС:
• Завтрак: йогуртовое парфе + гранола
• Обед: салат с курицей/рыбой
• Ужин: домашняя пицца/бургеры ПП

СУББОТА - 👨‍👩‍👧‍👦 СЕМЬЯ:
• Бранч: совместное приготовление
• Ужин: семейное любимое блюдо

ВОСКРЕСЕНЬЕ - 📝 ПЛАНИРОВАНИЕ:
• Завтрак: остатки недели
• Meal prep на новую неделю

🎯 ИНСТРУМЕНТЫ:
• Приложения для планирования меню
• Магнитная доска на холодильник
• Облачный гугл-документ для семьи

🎯 ПРАКТИКА: Создайте свой первый недельный план!
"""
        benefits = """• 📊 Полный контроль над питанием
• ⏰ Экономия времени на принятие решений
• 💵 Снижение пищевых отходов и затрат
• 🍎 Гарантия сбалансированного рациона"""
        
        return self.visual_manager.generate_attractive_post(
            "🗓️ СОВЕТ: НЕДЕЛЬНАЯ СИСТЕМА ПЛАНИРОВАНИЯ",
            content, "planning_advice", benefits
        )

    def generate_efficient_cooking_advice(self):
        content = """
⚡ ЭФФЕКТИВНАЯ ГОТОВКА: МАКСИМУМ РЕЗУЛЬТАТА ПРИ МИНИМУМЕ УСИЛИЙ

🎯 7 ПРИНЦИПОВ ЭФФЕКТИВНОЙ ГОТОВКИ:

1. 🔄 МНОГОЗАДАЧНОСТЬ
• Духовка + плита + мультиварка одновременно
• Пока варится - нарезаем следующее
• Используем время ожидания продуктивно

2. 🎯 ПАРТИЙНАЯ ГОТОВКА
• Готовим 2-3 блюда одновременно
• Используем одинаковые температуры
• Объединяем процессы (овощи на один противень)

3. 🗂️ СИСТЕМА КОНТЕЙНЕРОВ
• Одинаковые размеры для удобства хранения
• Стеклянные контейнеры для СВЧ и духовки
• Разделители для разных компонентов

4. 🔪 ПОДГОТОВКА ИНГРЕДИЕНТОВ
• Мойка и нарезка всех овощей за раз
• Порционная заморозка мяса/рыбы
• Готовые смеси специй

5. 🍳 УМНАЯ ТЕХНИКА
• Мультиварка с отложенным стартом
• Блендер для соусов и смузи
• Вакуумный упаковщик для заморозки

6. 📚 СТАНДАРТНЫЕ РЕЦЕПТЫ
• 10-15 проверенных рецептов
• Похожие техники приготовления
• Варьирование ингредиентов

7. 🔁 СИСТЕМА РОТАЦИИ
• Не повторять блюда 2 дня подряд
• Использовать сезонные продукты
• Планировать разнообразие

🎯 РАСЧЕТ ЭФФЕКТИВНОСТИ:
• Обычная готовка: 60-90 минут в день = 7-10 часов/неделя
• Meal prep: 3-4 часа в воскресенье = экономия 50% времени

🎯 ПРАКТИКА: Примените 2 принципа на этой неделе!
"""
        benefits = """• ⏱️ Сокращение времени готовки на 50%
• 💪 Снижение усталости от кухонных дел
• 🍽️ Больше разнообразия в рационе
• 😊 Увеличение удовольствия от процесса"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ СОВЕТ: ЭФФЕКТИВНАЯ ГОТОВКА ДЛЯ ЗАНЯТЫХ",
            content, "planning_advice", benefits
        )
# 🚀 ЧАСТЬ 12 - ИНТЕРФЕЙС И ЗАПУСК СИСТЕМЫ

# Flask роуты для управления системой
@app.route('/')
def dashboard():
    """Главная панель управления ботом"""
    dashboard_html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>🍏 Умный Кулинарный Бот</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            .header { text-align: center; margin-bottom: 40px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .stat-card { background: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 4px solid #28a745; }
            .btn { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; margin: 5px; }
            .btn-success { background: #28a745; }
            .btn-warning { background: #ffc107; color: black; }
            .btn-danger { background: #dc3545; }
            .logs { background: #1a1a1a; color: #00ff00; padding: 20px; border-radius: 8px; font-family: monospace; height: 300px; overflow-y: scroll; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🍏 Умный Кулинарный Бот</h1>
                <p>Система автоматической публикации рецептов в Telegram</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>📊 Статус системы</h3>
                    <p id="status">Загрузка...</p>
                </div>
                <div class="stat-card">
                    <h3>⏰ Время</h3>
                    <p id="timeInfo">Загрузка...</p>
                </div>
                <div class="stat-card">
                    <h3>📨 Сообщения</h3>
                    <p id="messageStats">Загрузка...</p>
                </div>
                <div class="stat-card">
                    <h3>🔄 Ротация</h3>
                    <p id="rotationStats">Загрузка...</p>
                </div>
            </div>

            <div style="text-align: center; margin: 30px 0;">
                <h3>🚀 Быстрые действия</h3>
                <button class="btn btn-success" onclick="sendManualPost()">📝 Создать ручной пост</button>
                <button class="btn" onclick="checkRotation()">🔄 Проверить ротацию</button>
                <button class="btn btn-warning" onclick="forceCleanup()">🧹 Очистка кэша</button>
                <button class="btn btn-danger" onclick="emergencyStop()">🛑 Аварийная остановка</button>
            </div>

            <div>
                <h3>📋 Логи системы</h3>
                <div class="logs" id="logs">
                    Загрузка логов...
                </div>
            </div>
        </div>

        <script>
            function updateDashboard() {
                fetch('/api/status')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('status').innerHTML = `🟢 Система активна<br>Аптайм: ${Math.round(data.uptime_seconds/3600)}ч`;
                        document.getElementById('timeInfo').innerHTML = `Сервер: ${data.server_time}<br>Кемерово: ${data.kemerovo_time}`;
                        document.getElementById('messageStats').innerHTML = `Отправлено: ${data.messages_sent}<br>Дубликатов: ${data.duplicate_rejections}`;
                        document.getElementById('rotationStats').innerHTML = `Рецептов: ${data.total_recipes}<br>Доступно: ${data.available_recipes}`;
                    });
                
                fetch('/api/logs')
                    .then(r => r.text())
                    .then(logs => {
                        document.getElementById('logs').innerHTML = logs;
                    });
            }

            function sendManualPost() {
                fetch('/api/manual-post', { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        alert(data.message);
                        updateDashboard();
                    });
            }

            function checkRotation() {
                fetch('/api/rotation-status')
                    .then(r => r.json())
                    .then(data => {
                        let status = '📊 Статус ротации:\\n';
                        for (const [category, stats] of Object.entries(data.rotation_status)) {
                            status += `${category}: ${stats.available}/${stats.total} (${stats.availability_percent}%)\\n`;
                        }
                        alert(status);
                    });
            }

            function forceCleanup() {
                fetch('/api/cleanup', { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        alert(data.message);
                        updateDashboard();
                    });
            }

            function emergencyStop() {
                if (confirm('⚠️ ВЫ УВЕРЕНЫ? Это остановит все запланированные посты!')) {
                    fetch('/api/emergency-stop', { method: 'POST' })
                        .then(r => r.json())
                        .then(data => {
                            alert(data.message);
                            updateDashboard();
                        });
                }
            }

            // Обновляем каждые 10 секунд
            setInterval(updateDashboard, 10000);
            updateDashboard();
        </script>
    </body>
    </html>
    '''
    return dashboard_html

@app.route('/api/status')
@require_api_key
def api_status():
    """API статуса системы"""
    times = TimeManager.get_current_times()
    rotation_status = AdvancedRotationSystem().check_rotation_status()
    
    total_recipes = sum(stats['total'] for stats in rotation_status.values())
    available_recipes = sum(stats['available'] for stats in rotation_status.values())
    
    return jsonify({
        "status": "active",
        "uptime_seconds": service_monitor.get_status()["uptime_seconds"],
        "server_time": times['server_time'],
        "kemerovo_time": times['kemerovo_time'],
        "messages_sent": service_monitor.request_count,
        "duplicate_rejections": service_monitor.duplicate_rejections,
        "total_recipes": total_recipes,
        "available_recipes": available_recipes
    })

@app.route('/api/manual-post', methods=['POST'])
@require_api_key
@rate_limit
def manual_post():
    """Ручная отправка поста"""
    try:
        generator = SmartContentGenerator()
        telegram = TelegramManager()
        
        # Определяем текущий день и время для контекста
        weekday = TimeManager.get_kemerovo_weekday()
        hour = TimeManager.get_kemerovo_hour()
        
        # Выбираем тип контента по текущему времени
        if 5 <= hour < 11:
            content_type = 'neuro_breakfast' if weekday == 0 else 'protein_breakfast'
        elif 11 <= hour < 16:
            content_type = 'neuro_lunch' if weekday == 0 else 'protein_lunch'
        elif 16 <= hour < 22:
            content_type = 'neuro_dinner' if weekday == 0 else 'protein_dinner'
        else:
            content_type = 'neuro_advice'
        
        # Получаем метод для генерации контента
        rotation_system = AdvancedRotationSystem()
        method_name = rotation_system.get_priority_recipe(content_type, weekday)
        
        if hasattr(generator, method_name):
            content = getattr(generator, method_name)()
            
            # Добавляем пометку о ручной отправке
            content = content.replace("🎯 Основано на исследованиях", "🔄 РУЧНОЙ ПОСТ\\n🎯 Основано на исследованиях")
            
            if telegram.send_message(content):
                return jsonify({"status": "success", "message": "✅ Пост успешно отправлен вручную"})
            else:
                return jsonify({"status": "error", "message": "❌ Ошибка отправки поста"})
        else:
            return jsonify({"status": "error", "message": f"❌ Метод {method_name} не найден"})
            
    except Exception as e:
        logger.error(f"❌ Ошибка ручной отправки: {str(e)}")
        return jsonify({"status": "error", "message": f"❌ Ошибка: {str(e)}"})

@app.route('/api/rotation-status')
@require_api_key
def rotation_status():
    """Статус ротации рецептов"""
    try:
        rotation_system = AdvancedRotationSystem()
        status = rotation_system.check_rotation_status()
        return jsonify({"rotation_status": status})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/cleanup', methods=['POST'])
@require_api_key
def cleanup():
    """Очистка кэша и старых сообщений"""
    try:
        telegram = TelegramManager()
        telegram.cleanup_old_messages(30)  # Очистка сообщений старше 30 дней
        
        with Database().get_connection() as conn:
            conn.execute('DELETE FROM content_cache WHERE created_at < DATE("now", "-7 days")')
        
        return jsonify({"status": "success", "message": "✅ Кэш успешно очищен"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/logs')
@require_api_key
def get_logs():
    """Получение последних логов"""
    try:
        with open('bot.log', 'r', encoding='utf-8') as f:
            logs = f.readlines()[-50:]  # Последние 50 строк
        return '<br>'.join(logs[::-1])  # Новые сверху
    except Exception as e:
        return f"Ошибка чтения логов: {str(e)}"

@app.route('/api/emergency-stop', methods=['POST'])
@require_api_key
def emergency_stop():
    """Аварийная остановка системы"""
    try:
        schedule.clear()
        logger.critical("🛑 СИСТЕМА ОСТАНОВЛЕНА ПО КОМАНДЕ ПОЛЬЗОВАТЕЛЯ")
        return jsonify({"status": "success", "message": "🛑 Система остановлена"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# СИСТЕМА ПЛАНИРОВАНИЯ
def schedule_posts():
    """Настройка расписания публикаций"""
    
    # Очищаем предыдущее расписание
    schedule.clear()
    
    # Время публикаций (время Кемерово)
    post_times = [
        '07:00',  # Утренний пост
        '12:00',  # Обеденный пост  
        '18:00',  # Вечерний пост
        '21:00'   # Совет дня
    ]
    
    # Конвертируем время и настраиваем расписание
    for kemerovo_time in post_times:
        server_time = TimeManager.kemerovo_to_server(kemerovo_time)
        schedule.every().day.at(server_time).do(send_scheduled_post, kemerovo_time)
        logger.info(f"📅 Настроено время публикации: {kemerovo_time} Кемерово -> {server_time} Сервер")

def send_scheduled_post(scheduled_time):
    """Отправка запланированного поста"""
    try:
        logger.info(f"⏰ ЗАПУСК ПО РАСПИСАНИЮ: {scheduled_time}")
        
        generator = SmartContentGenerator()
        telegram = TelegramManager()
        rotation_system = AdvancedRotationSystem()
        
        # Определяем день недели и текущий час
        weekday = TimeManager.get_kemerovo_weekday()
        current_hour = TimeManager.get_kemerovo_hour()
        
        # Определяем тип контента по времени суток
        content_type = rotation_system.validate_content_type_for_current_time(
            get_content_type_for_time(current_hour, weekday), 
            current_hour
        )
        
        # Получаем метод для генерации контента
        method_name = rotation_system.get_priority_recipe(content_type, weekday)
        
        if hasattr(generator, method_name):
            content = getattr(generator, method_name)()
            
            if telegram.send_message(content):
                logger.info(f"✅ Успешно отправлен пост: {method_name}")
            else:
                logger.error(f"❌ Ошибка отправки поста: {method_name}")
        else:
            logger.error(f"❌ Метод не найден: {method_name}")
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в send_scheduled_post: {str(e)}")

def get_content_type_for_time(hour, weekday):
    """Определение типа контента по времени суток и дню недели"""
    day_themes = {
        0: 'neuro',  # Понедельник
        1: 'protein', # Вторник
        2: 'veggie',  # Среда
        3: 'carbs',   # Четверг
        4: 'balance', # Пятница
        5: 'family',  # Суббота
        6: 'planning' # Воскресенье
    }
    
    theme = day_themes.get(weekday, 'neuro')
    
    if 5 <= hour < 11:    # Утро: 5:00 - 10:59
        return f'{theme}_breakfast'
    elif 11 <= hour < 16: # День: 11:00 - 15:59
        return f'{theme}_lunch'
    elif 16 <= hour < 20: # Ранний вечер: 16:00 - 19:59
        return f'{theme}_dinner'
    else:                 # Поздний вечер: 20:00 - 4:59
        return f'{theme}_advice'

# СИСТЕМА МОНИТОРИНГА И ЗАПУСКА
def run_scheduler():
    """Запуск планировщика в отдельном потоке"""
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"❌ Ошибка в планировщике: {e}")
            time.sleep(10)

def start_keep_alive():
    """Функция поддержания активности на Render"""
    def keep_alive():
        while True:
            try:
                if Config.RENDER_APP_URL:
                    response = requests.get(f"{Config.RENDER_APP_URL}/api/status", timeout=10)
                    service_monitor.update_keep_alive()
                    logger.info(f"♻️ Keep-alive: {response.status_code}")
                time.sleep(300)  # Каждые 5 минут
            except Exception as e:
                logger.warning(f"⚠️ Keep-alive ошибка: {e}")
                time.sleep(60)
    
    Thread(target=keep_alive, daemon=True).start()

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    try:
        logger.info("🚀 ЗАПУСК СИСТЕМЫ УМНОГО КУЛИНАРНОГО БОТА")
        
        # Инициализация базы данных
        Database()
        
        # Настройка расписания
        schedule_posts()
        
        # Запуск планировщика в отдельном потоке
        scheduler_thread = Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # Запуск keep-alive для Render
        start_keep_alive()
        
        # Проверка ротации
        rotation_system = AdvancedRotationSystem()
        rotation_system.check_rotation_status()
        
        logger.info("✅ СИСТЕМА УСПЕШНО ЗАПУЩЕНА")
        logger.info("📊 Статус доступен по адресу: /")
        
        # Запуск Flask приложения
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        raise
