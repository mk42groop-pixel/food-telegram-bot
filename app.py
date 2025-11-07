import os
import logging
import sqlite3
from datetime import datetime, timedelta
import jwt
from functools import wraps
from flask import request, jsonify
import hashlib

class Config:
    """Конфигурация приложения с безопасными настройками"""
    
    # Безопасность
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-key-change-in-production')
    ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'default-admin-token-change-me')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHANNEL = os.environ.get('TELEGRAM_CHANNEL', '@test_channel')
    
    # База данных
    DATABASE_URL = os.environ.get('DATABASE_URL', 'recipe_bot.db')
    
    # Время (ИСПРАВЛЕНО по требованиям)
    KEMEROVO_TIMEZONE = 7  # UTC+7
    SERVER_TIMEZONE = 3    # UTC+3 (Москва)
    
    # Новое расписание (ИСПРАВЛЕНО)
    SCHEDULE_CONFIG = {
        'weekdays': {    # Пн-Пт
            '08:30': 'advice',    # Утренний совет
            '09:00': 'breakfast', # Завтрак
            '12:00': 'lunch',     # Обед
            '18:00': 'dinner',    # Ужин
            '20:00': 'dessert'    # Десерт
        },
        'weekends': {    # Сб-Вс  
            '08:30': 'advice',    # Утренний совет
            '10:00': 'breakfast', # Завтрак (позже)
            '13:00': 'lunch',     # Обед
            '19:00': 'dinner',    # Ужин
            '20:00': 'dessert'    # Десерт
        }
    }
    
    # Настройки ротации
    ROTATION_DAYS = 30  # Дней до повторного использования рецепта
    CONTENT_TYPES = ['breakfast', 'lunch', 'dinner', 'dessert', 'advice']

class SecurityManager:
    """Менеджер безопасности для аутентификации и авторизации"""
    
    @staticmethod
    def generate_token(user_id):
        """Генерация JWT токена"""
        payload = {
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(days=30)
        }
        return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')
    
    @staticmethod
    def verify_token(token):
        """Проверка JWT токена"""
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            return payload['user_id']
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def hash_content(content):
        """Хеширование контента для проверки дубликатов"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def require_auth(f):
        """Декоратор для аутентификации API"""
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get('Authorization')
            if not token or not token.startswith('Bearer '):
                return jsonify({"error": "Требуется аутентификация"}), 401
            
            token = token.replace('Bearer ', '')
            if token != Config.ADMIN_TOKEN:
                return jsonify({"error": "Неверный токен"}), 401
            
            return f(*args, **kwargs)
        return decorated

class Database:
    """Управление базой данных с защитой от дублирования"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Инициализация базы данных"""
        self.connection = sqlite3.connect(Config.DATABASE_URL, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self):
        """Создание таблиц с защитой от дублирования"""
        with self.connection:
            # Таблица кэша контента (ИСПРАВЛЕНО - добавлен UNIQUE)
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS content_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,  -- ЗАЩИТА ОТ ДУБЛИРОВАНИЯ
                    content_type TEXT NOT NULL,
                    method_name TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    last_used DATE,
                    created_at DATE DEFAULT CURRENT_DATE,
                    UNIQUE(content_hash, content_type)
                )
            ''')
            
            # Таблица истории отправки (ИСПРАВЛЕНО - добавлены индексы)
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS sent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message_id INTEGER,
                    UNIQUE(content_hash, sent_at)
                )
            ''')
            
            # Таблица статистики (НОВАЯ - для точного подсчета)
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS recipe_stats (
                    content_type TEXT PRIMARY KEY,
                    total_count INTEGER DEFAULT 0,
                    available_count INTEGER DEFAULT 0,
                    last_updated DATE DEFAULT CURRENT_DATE
                )
            ''')
            
            # Создание индексов для производительности
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_hash ON content_cache(content_hash)')
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_type ON content_cache(content_type)')
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_messages(sent_at)')
    
    def get_connection(self):
        """Получение соединения с базой данных"""
        return self.connection
    
    def cleanup_old_records(self):
        """Очистка старых записей для предотвращения роста БД"""
        with self.connection:
            # Удаляем записи кэша старше 60 дней
            self.connection.execute(
                'DELETE FROM content_cache WHERE created_at < DATE("now", "-60 days")'
            )
            # Удаляем историю отправки старше 30 дней
            self.connection.execute(
                'DELETE FROM sent_messages WHERE sent_at < DATETIME("now", "-30 days")'
            )
    
    def update_recipe_stats(self):
        """Обновление статистики рецептов (ИСПРАВЛЕНО - точный подсчет)"""
        with self.connection:
            for content_type in Config.CONTENT_TYPES:
                # Подсчет общего количества уникальных рецептов
                total = self.connection.execute(
                    'SELECT COUNT(DISTINCT content_hash) FROM content_cache WHERE content_type = ?',
                    (content_type,)
                ).fetchone()[0]
                
                # Подсчет доступных рецептов (не использовались в последние ROTATION_DAYS)
                available = self.connection.execute('''
                    SELECT COUNT(DISTINCT cc.content_hash) 
                    FROM content_cache cc
                    LEFT JOIN sent_messages sm ON cc.content_hash = sm.content_hash 
                        AND sm.sent_at > DATE("now", ?)
                    WHERE cc.content_type = ? AND sm.id IS NULL
                ''', (f"-{Config.ROTATION_DAYS} days", content_type)).fetchone()[0]
                
                # Обновление статистики
                self.connection.execute('''
                    INSERT OR REPLACE INTO recipe_stats 
                    (content_type, total_count, available_count, last_updated)
                    VALUES (?, ?, ?, CURRENT_DATE)
                ''', (content_type, total, available))

class ServiceMonitor:
    """Мониторинг службы для отслеживания состояния системы"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0
        self.duplicate_rejections = 0
        self.last_keep_alive = datetime.now()
    
    def update_keep_alive(self):
        """Обновление времени последней активности"""
        self.last_keep_alive = datetime.now()
    
    def get_status(self):
        """Получение статуса системы"""
        current_time = datetime.now()
        uptime = current_time - self.start_time
        
        return {
            "status": "active",
            "uptime_seconds": uptime.total_seconds(),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "duplicate_rejections": self.duplicate_rejections,
            "last_keep_alive": self.last_keep_alive.isoformat(),
            "hours_until_restart": (24 - uptime.total_seconds() / 3600) % 24
        }

# Инициализация глобальных объектов
security_manager = SecurityManager()
database = Database()
service_monitor = ServiceMonitor()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('RecipeBot')

def initialize_system():
    """Инициализация системы при запуске"""
    try:
        logger.info("🚀 ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ КУЛИНАРНОГО БОТА")
        
        # Очистка старых записей
        database.cleanup_old_records()
        
        # Первоначальное обновление статистики
        database.update_recipe_stats()
        
        logger.info("✅ СИСТЕМА УСПЕШНО ИНИЦИАЛИЗИРОВАНА")
        return True
        
    except Exception as e:
        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ИНИЦИАЛИЗАЦИИ: {e}")
        return False

# Автоматическая инициализация при импорте
if __name__ != "__main__":
    initialize_system()
    import time
import schedule
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Optional
import random
import re

class TimeManager:
    """Управление временем с учетом временных зон сервера и Кемерово"""
    
    @staticmethod
    def get_current_times() -> Dict[str, str]:
        """Получение текущего времени сервера и Кемерово"""
        try:
            # Время сервера (UTC+3)
            server_tz = pytz.timezone('Europe/Moscow')
            server_time = datetime.now(server_tz)
            
            # Время Кемерово (UTC+7)
            kemerovo_tz = pytz.timezone('Asia/Novosibirsk')  # Ближайшая к Кемерово
            kemerovo_time = datetime.now(kemerovo_tz)
            
            return {
                'server_time': server_time.strftime('%H:%M'),
                'kemerovo_time': kemerovo_time.strftime('%H:%M'),
                'server_full': server_time.strftime('%Y-%m-%d %H:%M:%S'),
                'kemerovo_full': kemerovo_time.strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            # Fallback на вычисление разницы
            server_time = datetime.utcnow() + timedelta(hours=3)
            kemerovo_time = datetime.utcnow() + timedelta(hours=7)
            
            return {
                'server_time': server_time.strftime('%H:%M'),
                'kemerovo_time': kemerovo_time.strftime('%H:%M'),
                'server_full': server_time.strftime('%Y-%m-%d %H:%M:%S'),
                'kemerovo_full': kemerovo_time.strftime('%Y-%m-%d %H:%M:%S')
            }
    
    @staticmethod
    def get_kemerovo_time() -> datetime:
        """Получение текущего времени в Кемерово"""
        try:
            kemerovo_tz = pytz.timezone('Asia/Novosibirsk')
            return datetime.now(kemerovo_tz)
        except:
            return datetime.utcnow() + timedelta(hours=7)
    
    @staticmethod
    def get_kemerovo_hour() -> int:
        """Получение текущего часа в Кемерово"""
        return TimeManager.get_kemerovo_time().hour
    
    @staticmethod
    def get_kemerovo_weekday() -> int:
        """Получение текущего дня недели в Кемерово (0-пн, 6-вс)"""
        return TimeManager.get_kemerovo_time().weekday()
    
    @staticmethod
    def kemerovo_to_server(kemerovo_time: str) -> str:
        """Конвертация времени из Кемерово в серверное время"""
        try:
            # Парсим время Кемерово
            kemerovo_hour, kemerovo_minute = map(int, kemerovo_time.split(':'))
            
            # Вычисляем разницу (Кемерово UTC+7, Сервер UTC+3)
            time_diff = 4  # 7 - 3 = 4 часа разницы
            
            # Конвертируем в серверное время
            server_hour = (kemerovo_hour - time_diff) % 24
            
            return f"{server_hour:02d}:{kemerovo_minute:02d}"
        except Exception as e:
            logger.error(f"Ошибка конвертации времени {kemerovo_time}: {e}")
            return kemerovo_time
    
    @staticmethod
    def is_weekend() -> bool:
        """Проверка, является ли сегодня выходным днем"""
        weekday = TimeManager.get_kemerovo_weekday()
        return weekday >= 5  # 5=суббота, 6=воскресенье
    
    @staticmethod
    def get_current_content_type() -> str:
        """Определение типа контента по текущему времени (ИСПРАВЛЕНО)"""
        hour = TimeManager.get_kemerovo_hour()
        weekday = TimeManager.get_kemerovo_weekday()
        
        # Тема дня (ИСПРАВЛЕНО - убраны несуществующие типы)
        day_themes = {
            0: 'neuro',      # Пн - Нейропитание
            1: 'protein',    # Вт - Белки
            2: 'veggie',     # Ср - Овощи
            3: 'carbs',      # Чт - Углеводы
            4: 'energy',     # Пт - Энергия (было balance)
            5: 'family',     # Сб - Семейная кухня
            6: 'planning'    # Вс - Планирование
        }
        
        theme = day_themes.get(weekday, 'neuro')
        
        # Определение типа контента по времени (ИСПРАВЛЕНО)
        if 5 <= hour < 11:
            return f'{theme}_breakfast'
        elif 11 <= hour < 16:
            return f'{theme}_lunch'
        elif 16 <= hour < 20:
            return f'{theme}_dinner'
        elif hour == 20:
            return f'{theme}_dessert'  # НОВОЕ - десерт в 20:00
        else:
            return f'{theme}_advice'

class AdvancedRotationSystem:
    """Улучшенная система ротации контента с защитой от дублирования"""
    
    def __init__(self):
        self.db = Database()
        self.content_mapping = self._build_content_mapping()
    
    def _build_content_mapping(self) -> Dict[str, List[str]]:
        """Построение маппинга типов контента на методы (ИСПРАВЛЕНО)"""
        
        # ОСНОВНЫЕ ТИПЫ КОНТЕНТА (ИСПРАВЛЕНО - только реально существующие)
        mapping = {
            # Понедельник - Нейропитание
            'neuro_breakfast': [
                'generate_brain_breakfast', 'generate_focus_smoothie',
                'generate_memory_omelette', 'generate_neuro_pancakes'
            ],
            'neuro_lunch': [
                'generate_brain_lunch', 'generate_focus_bowl',
                'generate_memory_salad', 'generate_neuro_soup'
            ],
            'neuro_dinner': [
                'generate_brain_dinner', 'generate_sleep_salmon',
                'generate_calm_chicken', 'generate_neuro_stew'
            ],
            'neuro_dessert': [
                'generate_brain_dessert', 'generate_focus_treat'
            ],
            'neuro_advice': [
                'generate_brain_nutrition_advice', 'generate_focus_foods_advice'
            ],
            
            # Вторник - Белки
            'protein_breakfast': [
                'generate_muscle_breakfast', 'generate_energy_eggs',
                'generate_strength_smoothie', 'generate_power_omelette'
            ],
            'protein_lunch': [
                'generate_muscle_lunch', 'generate_protein_bowl',
                'generate_strength_salad', 'generate_power_soup'
            ],
            'protein_dinner': [
                'generate_muscle_dinner', 'generate_recovery_fish',
                'generate_repair_chicken', 'generate_protein_stew'
            ],
            'protein_dessert': [
                'generate_protein_dessert', 'generate_muscle_treat'
            ],
            'protein_advice': [
                'generate_protein_science_advice', 'generate_muscle_health_advice'
            ],
            
            # Среда - Овощи
            'veggie_breakfast': [
                'generate_detox_breakfast', 'generate_cleanse_smoothie',
                'generate_fiber_omelette', 'generate_green_pancakes'
            ],
            'veggie_lunch': [
                'generate_detox_lunch', 'generate_cleanse_bowl',
                'generate_fiber_salad', 'generate_green_soup'
            ],
            'veggie_dinner': [
                'generate_detox_dinner', 'generate_cleanse_fish',
                'generate_alkaline_chicken', 'generate_veggie_stew'
            ],
            'veggie_dessert': [
                'generate_detox_dessert', 'generate_cleanse_treat'
            ],
            'veggie_advice': [
                'generate_detox_science_advice', 'generate_fiber_health_advice'
            ],
            
            # Четверг - Углеводы
            'carbs_breakfast': [
                'generate_energy_breakfast', 'generate_fuel_smoothie',
                'generate_glycogen_pancakes', 'generate_carbs_omelette'
            ],
            'carbs_lunch': [
                'generate_glycogen_replenishment', 'generate_energy_bowl_lunch',
                'generate_carbs_balance_meal', 'generate_pasta_power'
            ],
            'carbs_dinner': [
                'generate_slow_carbs_dinner', 'generate_energy_reserve_meal',
                'generate_evening_carbs', 'generate_carbs_stew'
            ],
            'carbs_dessert': [
                'generate_energy_dessert', 'generate_carbs_treat'
            ],
            'carbs_advice': [
                'generate_carbs_science_advice', 'generate_energy_management_advice'
            ],
            
            # Пятница - Энергия (было Balance)
            'energy_breakfast': [
                'generate_fun_breakfast', 'generate_balanced_meal',
                'generate_weekend_mood_meal', 'generate_friday_pancakes'
            ],
            'energy_lunch': [
                'generate_mediterranean_feast', 'generate_social_lunch',
                'generate_celebration_meal', 'generate_energy_lunch'
            ],
            'energy_dinner': [
                'generate_social_dinner', 'generate_evening_balance',
                'generate_weekend_starter', 'generate_energy_dinner'
            ],
            'energy_dessert': [
                'generate_healthy_indulgence', 'generate_guilt_free_treat',
                'generate_weekend_dessert', 'generate_energy_treat'
            ],
            'energy_advice': [
                'generate_hydration_science', 'generate_electrolyte_balance'
            ],
            
            # Суббота - Семейная кухня
            'family_breakfast': [
                'generate_family_brunch', 'generate_weekend_pancakes',
                'generate_shared_breakfast', 'generate_saturday_omelette'
            ],
            'family_lunch': [
                'generate_cooking_workshop', 'generate_kids_friendly',
                'generate_team_cooking', 'generate_family_baking'
            ],
            'family_dinner': [
                'generate_family_lasagna', 'generate_saturday_pizza',
                'generate_shared_platter', 'generate_family_dinner'
            ],
            'family_dessert': [
                'generate_family_dessert', 'generate_weekend_treat',
                'generate_shared_sweets', 'generate_family_treat'
            ],
            'family_advice': [
                'generate_family_nutrition_advice', 'generate_cooking_together_advice'
            ],
            
            # Воскресенье - Планирование
            'planning_breakfast': [
                'generate_brunch_feast', 'generate_lazy_breakfast',
                'generate_meal_prep_breakfast', 'generate_sunday_porridge'
            ],
            'planning_lunch': [
                'generate_weekly_prep_lunch', 'generate_batch_cooking_lunch',
                'generate_efficient_lunch', 'generate_planning_lunch'
            ],
            'planning_dinner': [
                'generate_weekly_prep_chicken', 'generate_batch_cooking',
                'generate_container_meal', 'generate_planning_dinner'
            ],
            'planning_dessert': [
                'generate_weekly_treat', 'generate_prep_friendly_dessert',
                'generate_planning_dessert', 'generate_meal_prep_treat'
            ],
            'planning_advice': [
                'generate_meal_prep_guide_advice', 'generate_weekly_planning_advice'
            ]
        }
        
        return mapping
    
    def get_priority_recipe(self, content_type: str, weekday: int) -> str:
        """Получение приоритетного рецепта для заданного типа контента"""
        try:
            available_methods = self.content_mapping.get(content_type, [])
            
            if not available_methods:
                logger.warning(f"⚠️ Нет методов для типа контента: {content_type}")
                return self._get_fallback_method(content_type)
            
            # Получаем историю использования за последние ROTATION_DAYS дней
            used_methods = self._get_recently_used_methods(content_type)
            
            # Ищем неиспользованные методы
            unused_methods = [m for m in available_methods if m not in used_methods]
            
            if unused_methods:
                selected_method = random.choice(unused_methods)
                logger.info(f"🎯 Выбран свежий рецепт: {selected_method}")
            else:
                # Все методы использовались - берем самый старый
                selected_method = self._get_oldest_used_method(content_type, available_methods)
                logger.info(f"🔄 Все рецепты использовались, берем самый старый: {selected_method}")
            
            return selected_method
            
        except Exception as e:
            logger.error(f"❌ Ошибка в get_priority_recipe: {e}")
            return self._get_fallback_method(content_type)
    
    def _get_recently_used_methods(self, content_type: str) -> List[str]:
        """Получение методов, использованных в последние ROTATION_DAYS дней"""
        try:
            with self.db.get_connection() as conn:
                result = conn.execute('''
                    SELECT DISTINCT cc.method_name 
                    FROM content_cache cc
                    JOIN sent_messages sm ON cc.content_hash = sm.content_hash
                    WHERE cc.content_type = ? 
                    AND sm.sent_at > DATETIME('now', ?)
                ''', (content_type, f"-{Config.ROTATION_DAYS} days"))
                
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"❌ Ошибка получения истории методов: {e}")
            return []
    
    def _get_oldest_used_method(self, content_type: str, available_methods: List[str]) -> str:
        """Получение самого старого использованного метода"""
        try:
            with self.db.get_connection() as conn:
                result = conn.execute('''
                    SELECT cc.method_name, MAX(sm.sent_at) as last_used
                    FROM content_cache cc
                    JOIN sent_messages sm ON cc.content_hash = sm.content_hash
                    WHERE cc.content_type = ? AND cc.method_name IN ({})
                    GROUP BY cc.method_name
                    ORDER BY last_used ASC
                    LIMIT 1
                '''.format(','.join(['?'] * len(available_methods))), 
                [content_type] + available_methods)
                
                row = result.fetchone()
                return row[0] if row else random.choice(available_methods)
                
        except Exception as e:
            logger.error(f"❌ Ошибка поиска старого метода: {e}")
            return random.choice(available_methods)
    
    def _get_fallback_method(self, content_type: str) -> str:
        """Резервный метод при ошибках (ИСПРАВЛЕНО)"""
        fallbacks = {
            'breakfast': 'generate_brain_breakfast',
            'lunch': 'generate_brain_lunch', 
            'dinner': 'generate_brain_dinner',
            'dessert': 'generate_brain_dessert',
            'advice': 'generate_brain_nutrition_advice'
        }
        
        # Извлекаем базовый тип (neuro_breakfast -> breakfast)
        base_type = content_type.split('_')[-1] if '_' in content_type else content_type
        return fallbacks.get(base_type, 'generate_brain_nutrition_advice')
    
    def check_rotation_status(self) -> Dict[str, Dict]:
        """Проверка статуса ротации для всех типов контента (ИСПРАВЛЕНО)"""
        status = {}
        
        try:
            for content_type in self.content_mapping.keys():
                available_methods = self.content_mapping[content_type]
                used_methods = self._get_recently_used_methods(content_type)
                
                available_count = len([m for m in available_methods if m not in used_methods])
                total_count = len(available_methods)
                
                status[content_type] = {
                    'total': total_count,
                    'available': available_count,
                    'availability_percent': round((available_count / total_count) * 100, 1) if total_count > 0 else 0,
                    'used_recently': len(used_methods)
                }
            
            # Обновляем статистику в БД
            self.db.update_recipe_stats()
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки статуса ротации: {e}")
        
        return status
    
    def validate_content_type_for_current_time(self, content_type: str, current_hour: int) -> str:
        """Валидация типа контента для текущего времени (ИСПРАВЛЕНО)"""
        valid_types = {
            'breakfast': range(5, 11),    # 5-10 утра
            'lunch': range(11, 16),       # 11-15 дня  
            'dinner': range(16, 20),      # 16-19 вечера
            'dessert': [20],              # 20:00 десерт
            'advice': [8, 21]             # 8:30 и 21:00 советы
        }
        
        base_type = content_type.split('_')[-1] if '_' in content_type else content_type
        
        # Проверяем, подходит ли тип контента для текущего времени
        if base_type in valid_types and current_hour not in valid_types[base_type]:
            # Если не подходит - определяем правильный тип
            return TimeManager.get_current_content_type()
        
        return content_type

class VisualManager:
    """Менеджер визуального оформления контента"""
    
    @staticmethod
    def generate_attractive_post(title: str, content: str, content_type: str, benefits: str = "") -> str:
        """Генерация привлекательного поста с эмодзи и форматированием"""
        
        # Эмодзи для разных типов контента
        emoji_map = {
            'breakfast': '🍳', 'lunch': '🍲', 'dinner': '🍽️', 
            'dessert': '🍰', 'advice': '💡'
        }
        
        base_emoji = emoji_map.get(content_type.split('_')[-1], '📝')
        
        # Очистка контента от лишних пробелов
        content = re.sub(r'\n\s*\n', '\n\n', content.strip())
        
        # Сборка финального поста
        post_parts = []
        
        # Заголовок
        post_parts.append(f"{base_emoji} {title.upper()}")
        post_parts.append("")  # Пустая строка
        
        # Основной контент
        post_parts.append(content)
        
        # Польза (если есть)
        if benefits:
            post_parts.append("")
            post_parts.append("🌟 ПОЛЬЗА ДЛЯ ЗДОРОВЬЯ:")
            post_parts.append(benefits)
        
        # Хештеги
        post_parts.append("")
        post_parts.append(VisualManager._generate_hashtags(content_type))
        
        return '\n'.join(post_parts)
    
    @staticmethod
    def _generate_hashtags(content_type: str) -> str:
        """Генерация релевантных хештегов"""
        hashtags = {
            'neuro': ['#мозг', '#память', '#концентрация', '#нейропитание'],
            'protein': ['#белок', '#мышцы', '#восстановление', '#протеин'],
            'veggie': ['#овощи', '#детокс', '#клетчатка', '#здоровье'],
            'carbs': ['#углеводы', '#энергия', '#гликоген', '#топливо'],
            'energy': ['#баланс', '#удовольствие', '#пп', '#здоровоепитание'],
            'family': ['#семья', '#дети', '#совместноеприготовление', '#традиции'],
            'planning': ['#план', '#подготовка', '#mealprep', '#организация']
        }
        
        theme = content_type.split('_')[0] if '_' in content_type else 'neuro'
        base_hashtags = hashtags.get(theme, ['#здоровоепитание', '#пп', '#рецепты'])
        
        time_hashtags = {
            'breakfast': ['#завтрак', '#утро', '#энергия'],
            'lunch': ['#обед', '#перерыв', '#сытно'],
            'dinner': ['#ужин', '#вечер', '#легко'],
            'dessert': ['#десерт', '#сладости', '#ппдесерт'],
            'advice': ['#совет', '#польза', '#образование']
        }
        
        time_type = content_type.split('_')[-1] if '_' in content_type else 'advice'
        time_tags = time_hashtags.get(time_type, ['#питание', '#зож'])
        
        all_hashtags = base_hashtags + time_tags
        return ' '.join(all_hashtags[:8])  # Ограничиваем количество
    
    @staticmethod
    def format_nutrition_facts(calories: int, protein: int, fats: int, carbs: int) -> str:
        """Форматирование пищевой ценности"""
        return f"🍽️ КБЖУ: {calories} ккал • Белки: {protein}г • Жиры: {fats}г • Углеводы: {carbs}г"
        import requests
import json
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
import sys
import traceback
from typing import Dict, List, Optional, Tuple

class EnhancedLogger:
    """Улучшенная система логирования с ротацией и структурированием"""
    
    def __init__(self):
        self.logger = logging.getLogger('RecipeBotEnhanced')
        self.logger.setLevel(logging.INFO)
        
        # Форматтер с детальной информацией
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый обработчик с ротацией
        file_handler = RotatingFileHandler(
            'bot_enhanced.log',
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        
        # Консольный обработчик
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        
        # Добавляем обработчики
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def log_message_sent(self, content_type: str, method_name: str, message_id: int, success: bool = True):
        """Логирование отправки сообщения"""
        status = "✅ УСПЕХ" if success else "❌ ОШИБКА"
        self.logger.info(f"{status} | Отправка {content_type} | Метод: {method_name} | ID: {message_id}")
    
    def log_rotation_decision(self, content_type: str, selected_method: str, available_count: int, total_count: int):
        """Логирование решения системы ротации"""
        self.logger.info(f"🔄 РОТАЦИЯ | {content_type} | Выбран: {selected_method} | Доступно: {available_count}/{total_count}")
    
    def log_system_health(self, uptime: float, memory_usage: float, queue_size: int):
        """Логирование состояния системы"""
        self.logger.info(f"📊 ЗДОРОВЬЕ | Аптайм: {uptime:.1f}ч | Память: {memory_usage:.1f}% | Очередь: {queue_size}")
    
    def log_error_with_traceback(self, error_message: str, exception: Exception = None):
        """Логирование ошибок с трейсбэком"""
        self.logger.error(f"🚨 ОШИБКА: {error_message}")
        if exception:
            self.logger.error(f"🔍 ТРЕЙСБЭК: {traceback.format_exc()}")
    
    def log_telegram_api_call(self, method: str, success: bool, response_time: float, details: str = ""):
        """Логирование вызовов Telegram API"""
        status = "✅" if success else "❌"
        self.logger.info(f"📡 TELEGRAM API | {method} | {status} | Время: {response_time:.2f}с | {details}")

class TelegramManager:
    """Управление взаимодействием с Telegram API с улучшенным мониторингом"""
    
    def __init__(self):
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.logger = EnhancedLogger()
        self.db = Database()
        self.last_api_call = datetime.now()
        self.api_call_count = 0
    
    def _make_telegram_request(self, method: str, data: Dict = None, files: Dict = None) -> Optional[Dict]:
        """Выполнение запроса к Telegram API с обработкой ошибок"""
        start_time = datetime.now()
        
        try:
            url = f"{self.base_url}/{method}"
            
            if files:
                response = requests.post(url, data=data, files=files, timeout=30)
            else:
                response = requests.post(url, json=data, timeout=30)
            
            response_time = (datetime.now() - start_time).total_seconds()
            self.api_call_count += 1
            self.last_api_call = datetime.now()
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.logger.log_telegram_api_call(method, True, response_time, "Успех")
                    return result['result']
                else:
                    error_description = result.get('description', 'Неизвестная ошибка')
                    self.logger.log_telegram_api_call(method, False, response_time, f"Ошибка API: {error_description}")
                    return None
            else:
                self.logger.log_telegram_api_call(method, False, response_time, f"HTTP {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            response_time = (datetime.now() - start_time).total_seconds()
            self.logger.log_telegram_api_call(method, False, response_time, "Таймаут")
            return None
        except requests.exceptions.RequestException as e:
            response_time = (datetime.now() - start_time).total_seconds()
            self.logger.log_telegram_api_call(method, False, response_time, f"Ошибка сети: {str(e)}")
            return None
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds()
            self.logger.log_telegram_api_call(method, False, response_time, f"Неожиданная ошибка: {str(e)}")
            return None
    
    def send_message(self, text: str, content_type: str = "unknown", method_name: str = "unknown") -> bool:
        """Отправка сообщения в канал с проверкой дубликатов"""
        try:
            # Проверка дубликатов перед отправкой
            content_hash = SecurityManager.hash_content(text)
            
            if self._is_duplicate_content(content_hash):
                service_monitor.duplicate_rejections += 1
                self.logger.logger.warning(f"🔄 ДУБЛИКАТ | Пропуск отправки | Хеш: {content_hash[:16]}...")
                return False
            
            # Отправка сообщения
            data = {
                'chat_id': self.channel,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            result = self._make_telegram_request('sendMessage', data)
            
            if result and 'message_id' in result:
                message_id = result['message_id']
                
                # Сохраняем в историю
                self._save_to_sent_messages(content_hash, content_type, message_id)
                
                # Логируем успех
                self.logger.log_message_sent(content_type, method_name, message_id, True)
                service_monitor.request_count += 1
                
                return True
            else:
                self.logger.log_message_sent(content_type, method_name, 0, False)
                return False
                
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка отправки сообщения: {str(e)}", e)
            return False
    
    def get_channel_info(self) -> Optional[Dict]:
        """Получение информации о канале (включая количество подписчиков)"""
        try:
            # Метод getChat для получения информации о канале
            data = {'chat_id': self.channel}
            result = self._make_telegram_request('getChat', data)
            
            if result:
                channel_info = {
                    'title': result.get('title', 'Неизвестно'),
                    'username': result.get('username', 'Неизвестно'),
                    'description': result.get('description', ''),
                    'member_count': result.get('members_count', 0),
                    'type': result.get('type', 'Неизвестно')
                }
                return channel_info
            return None
            
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка получения информации о канале: {str(e)}", e)
            return None
    
    def get_subscribers_count(self) -> int:
        """Получение количества подписчиков канала"""
        try:
            channel_info = self.get_channel_info()
            if channel_info and 'member_count' in channel_info:
                return channel_info['member_count']
            return 0
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка получения количества подписчиков: {str(e)}", e)
            return 0
    
    def test_connection(self) -> bool:
        """Проверка соединения с Telegram API"""
        try:
            result = self._make_telegram_request('getMe')
            if result and result.get('is_bot'):
                self.logger.logger.info("✅ Проверка соединения с Telegram: УСПЕХ")
                return True
            else:
                self.logger.logger.error("❌ Проверка соединения с Telegram: ОШИБКА")
                return False
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка проверки соединения: {str(e)}", e)
            return False
    
    def _is_duplicate_content(self, content_hash: str) -> bool:
        """Проверка дублирования контента"""
        try:
            with self.db.get_connection() as conn:
                result = conn.execute(
                    'SELECT 1 FROM sent_messages WHERE content_hash = ? AND sent_at > DATETIME("now", "-7 days")',
                    (content_hash,)
                )
                return result.fetchone() is not None
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка проверки дубликатов: {str(e)}", e)
            return False
    
    def _save_to_sent_messages(self, content_hash: str, content_type: str, message_id: int):
        """Сохранение отправленного сообщения в историю"""
        try:
            with self.db.get_connection() as conn:
                conn.execute(
                    'INSERT INTO sent_messages (content_hash, content_type, message_id) VALUES (?, ?, ?)',
                    (content_hash, content_type, message_id)
                )
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка сохранения в историю: {str(e)}", e)
    
    def cleanup_old_messages(self, days: int = 30):
        """Очистка старых сообщений из истории"""
        try:
            with self.db.get_connection() as conn:
                deleted_count = conn.execute(
                    'DELETE FROM sent_messages WHERE sent_at < DATETIME("now", ?)',
                    (f"-{days} days",)
                ).rowcount
                
                self.logger.logger.info(f"🧹 Очистка истории | Удалено записей: {deleted_count}")
                
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка очистки истории: {str(e)}", e)
    
    def get_delivery_stats(self) -> Dict:
        """Получение статистики доставки сообщений"""
        try:
            with self.db.get_connection() as conn:
                # Статистика за последние 7 дней
                weekly_stats = conn.execute('''
                    SELECT 
                        COUNT(*) as total_messages,
                        COUNT(DISTINCT content_hash) as unique_messages,
                        MIN(sent_at) as first_message,
                        MAX(sent_at) as last_message
                    FROM sent_messages 
                    WHERE sent_at > DATETIME('now', '-7 days')
                ''').fetchone()
                
                # Статистика по типам контента
                type_stats = conn.execute('''
                    SELECT content_type, COUNT(*) as count
                    FROM sent_messages 
                    WHERE sent_at > DATETIME('now', '-7 days')
                    GROUP BY content_type
                    ORDER BY count DESC
                ''').fetchall()
                
                return {
                    'weekly_total': weekly_stats['total_messages'],
                    'weekly_unique': weekly_stats['unique_messages'],
                    'first_message': weekly_stats['first_message'],
                    'last_message': weekly_stats['last_message'],
                    'by_type': {row['content_type']: row['count'] for row in type_stats},
                    'api_calls_total': self.api_call_count,
                    'last_api_call': self.last_api_call.isoformat()
                }
                
        except Exception as e:
            self.logger.log_error_with_traceback(f"Ошибка получения статистики: {str(e)}", e)
            return {}
    
    def send_manual_post(self, post_type: str, generator) -> Tuple[bool, str]:
        """Ручная отправка поста определенного типа"""
        try:
            self.logger.logger.info(f"🔄 РУЧНАЯ ОТПРАВКА | Тип: {post_type}")
            
            # Определяем метод генерации на основе типа
            rotation_system = AdvancedRotationSystem()
            weekday = TimeManager.get_kemerovo_weekday()
            
            method_name = rotation_system.get_priority_recipe(post_type, weekday)
            
            if hasattr(generator, method_name):
                content = getattr(generator, method_name)()
                
                # Добавляем пометку о ручной отправке
                marked_content = content.replace(
                    "🎯 НАУЧНЫЙ ПОДХОД:", 
                    "🔄 РУЧНАЯ ОТПРАВКА\n🎯 НАУЧНЫЙ ПОДХОД:"
                )
                
                success = self.send_message(marked_content, post_type, method_name)
                
                if success:
                    return True, f"✅ Ручной пост ({post_type}) успешно отправлен!"
                else:
                    return False, f"❌ Ошибка отправки ручного поста ({post_type})"
            else:
                return False, f"❌ Метод {method_name} не найден для типа {post_type}"
                
        except Exception as e:
            error_msg = f"❌ Ошибка ручной отправки: {str(e)}"
            self.logger.log_error_with_traceback(error_msg, e)
            return False, error_msg

# Инициализация глобальных объектов
enhanced_logger = EnhancedLogger()
telegram_manager = TelegramManager()

def test_telegram_connection():
    """Тестирование подключения к Telegram при запуске"""
    if telegram_manager.test_connection():
        enhanced_logger.logger.info("✅ Telegram подключение: УСПЕХ")
        
        # Получаем информацию о канале
        channel_info = telegram_manager.get_channel_info()
        if channel_info:
            enhanced_logger.logger.info(f"📊 Информация о канале: {channel_info['title']} | Подписчики: {channel_info.get('member_count', 'N/A')}")
        return True
    else:
        enhanced_logger.logger.error("❌ Telegram подключение: ОШИБКА")
        return False

# Автоматическое тестирование при импорте
if __name__ != "__main__":
    test_telegram_connection()

# Класс должен быть на уровне модуля (без лишних отступов)
class ScientificContentGenerator:
    """Генератор научно-обоснованного контента о питании"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
        self.db = Database()
    
    def generate_brain_nutrition_advice(self):
        """Совет по нейропитанию для улучшения когнитивных функций"""
        content = """
🧠 НАУКА ПИТАНИЯ ДЛЯ МОЗГА: КАК ЕДА ВЛИЯЕТ НА ВАШИ МОЗГОВЫЕ ФУНКЦИИ

🔬 КЛЮЧЕВЫЕ НУТРИЕНТЫ ДЛЯ МОЗГА:

1. 🫐 ОМЕГА-3 ЖИРНЫЕ КИСЛОТЫ
   • Улучшают текучесть клеточных мембран нейронов
   • Усиливают синаптическую пластичность
   • Снижают нейровоспаление
   • Источники: лосось, грецкие орехи, семена льна

2. 🥦 АНТИОКСИДАНТЫ
   • Защищают от окислительного стресса
   • Уменьшают повреждение свободными радикалами
   • Улучшают кровоснабжение мозга
   • Источники: ягоды, темный шоколад, зеленый чай

3. 🥚 ХОЛИН
   • Предшественник ацетилхолина - нейромедиатора памяти
   • Поддерживает целостность клеточных мембран
   • Участвует в синтезе миелиновых оболочек
   • Источники: яйца, печень, соя

4. 🌿 ФЛАВОНОИДЫ
   • Усиливают нейрогенез в гиппокампе
   • Улучшают cerebral blood flow
   • Замедляют возрастное снижение когнитивных функций
   • Источники: какао, цитрусовые, зеленые листовые овощи

🎯 ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:
• Завтрак с яйцами и авокадо для холина и полезных жиров
• Перекус грецкими орехами и ягодами для Омега-3 и антиоксидантов
• Ужин с жирной рыбой 2-3 раза в неделю
• Зеленый чай вместо кофе для флавоноидов

💡 НАУЧНЫЙ ФАКТ: 
Исследования показывают, что средиземноморская диета ассоциируется 
со снижением риска когнитивных нарушений на 35%.
"""
        benefits = """• 🧠 Улучшение памяти и концентрации
• ⚡ Повышение умственной энергии
• 🛡️ Защита от возрастных изменений
• 💫 Улучшение нейропластичности"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 СОВЕТ: НАУКА ПИТАНИЯ ДЛЯ МОЗГА",
            content, "neuro_advice", benefits
        )
    
    def generate_protein_science_advice(self):
        """Научный совет о роли белка в организме"""
        content = """
💪 НАУКА БЕЛКА: СТРОИТЕЛЬНЫЕ БЛОКИ ВАШЕГО ТЕЛА

🔬 БИОЛОГИЧЕСКАЯ РОЛЬ БЕЛКОВ:

1. 🏗️ СТРУКТУРНАЯ ФУНКЦИЯ
   • Коллаген - каркас соединительной ткани
   • Актин и миозин - мышечные сокращения
   • Кератин - волосы, ногти, кожа

2. 🛡️ ИММУННАЯ СИСТЕМА
   • Антитела (иммуноглобулины) - защита от патогенов
   • Цитокины - регуляция иммунного ответа
   • Система комплемента - врожденный иммунитет

3. ⚡ ФЕРМЕНТАТИВНАЯ АКТИВНОСТЬ
   • Ускорение биохимических реакций в 10^8-10^20 раз
   • Специфичность к субстратам
   • Регуляция метаболических путей

4. 🚚 ТРАНСПОРТНАЯ ФУНКЦИЯ
   • Гемоглобин - транспорт кислорода
   • Липопротеины - транспорт липидов
   • Трансферрин - транспорт железа

🧬 АМИНОКИСЛОТНЫЙ ПРОФИЛЬ:
• 9 незаменимых аминокислот
• 11 заменимых аминокислот
• 6 условно незаменимых аминокислот

📊 РАСЧЕТ ПОТРЕБНОСТИ:
• Средняя активность: 1.2-1.6 г/кг
• Силовые тренировки: 1.6-2.2 г/кг
• Выносливость: 1.4-1.8 г/кг
• Пожилые люди: 1.2-1.5 г/кг (профилактика саркопении)

🎯 КАЧЕСТВО БЕЛКА:
• PDCAAS (Protein Digestibility Corrected Amino Acid Score)
• Яйцо: 1.00 (эталон)
• Сыворотка: 1.00
• Говядина: 0.92
• Соя: 0.91
• Пшеница: 0.42

💡 НАУЧНЫЙ ФАКТ:
Синтез мышечного белка максимально стимулируется при потреблении 
20-40 г высококачественного белка за один прием пищи.
"""
        benefits = """• 💪 Поддержка мышечной массы
• 🛡️ Укрепление иммунной системы
• ⚡ Улучшение метаболизма
• 🔄 Ускорение восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СОВЕТ: НАУКА БЕЛКА И АМИНОКИСЛОТ",
            content, "protein_advice", benefits
        )
    
    def generate_detox_science_advice(self):
        """Научный совет о детоксикации и роли овощей"""
        content = """
🌿 НАУКА ДЕТОКСА: КАК ОВОЩИ ОЧИЩАЮТ ОРГАНИЗМ

🔬 ЕСТЕСТВЕННЫЕ СИСТЕМЫ ДЕТОКСИКАЦИИ:

1. ♻️ ПЕЧЕНЬ - ГЛАВНЫЙ ФИЛЬТР
   • Фаза 1: цитохром P450 - окисление токсинов
   • Фаза 2: конъюгация - связывание с молекулами
   • Фаза 3: выведение через желчь

2. 🫁 ДЫХАТЕЛЬНАЯ СИСТЕМА
   • Выведение летучих соединений
   • Газообмен через альвеолы
   • Мукоцилиарный клиренс

3. 🧴 КОЖА
   • Выведение липофильных токсинов
   • Потоотделение
   • Кожное сало

4. 🫘 ПОЧКИ
   • Фильтрация крови
   • Реабсорбция питательных веществ
   • Выведение водорастворимых токсинов

🥦 КЛЮЧЕВЫЕ ОВОЩИ ДЛЯ ДЕТОКСА:

1. 🥬 КРЕСТОЦВЕТНЫЕ ОВОЩИ
   • Сульфорафан - активация ферментов детоксикации
   • Глюкозинолаты - поддержка функции печени
   • Индол-3-карбинол - баланс эстрогенов

2. 🟢 ЗЕЛЕНЫЕ ЛИСТОВЫЕ
   • Хлорофилл - связывание тяжелых металлов
   • Клетчатка - улучшение перистальтики
   • Фолат - поддержка метилирования

3. 🧄 ЛУК И ЧЕСНОК
   • Аллицин - антимикробное действие
   • Селен - антиоксидантная защита
   • Сера - поддержка синтеза глутатиона

4. 🥕 ОРАНЖЕВЫЕ ОВОЩИ
   • Бета-каротин - защита клеточных мембран
   • Витамин A - регенерация слизистых
   • Клетчатка - связывание токсинов

🎯 ПРАКТИЧЕСКИЕ СОВЕТЫ:
• 5 порций овощей разных цветов ежедневно
• Ферментированные овощи для пробиотиков
• Зеленые смузи для хлорофилла
• Приготовление на пару для сохранения нутриентов

💡 НАУЧНЫЙ ФАКТ:
Сульфорафан из брокколи увеличивает активность ферментов 
детоксикации печени на 200-300%.
"""
        benefits = """• 🧹 Естественное очищение организма
• 🍃 Улучшение функции печени
• 💚 Усиление антиоксидантной защиты
• 🔄 Оптимизация метаболизма"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 СОВЕТ: НАУКА ДЕТОКСА И ОВОЩЕЙ",
            content, "veggie_advice", benefits
        )
    
    def generate_carbs_science_advice(self):
        """Научный совет об углеводах и энергии"""
        content = """
⚡ НАУКА УГЛЕВОДОВ: ИСТОЧНИКИ ЭНЕРГИИ ДЛЯ ТЕЛА И МОЗГА

🔬 ТИПЫ УГЛЕВОДОВ И ИХ МЕТАБОЛИЗМ:

1. 🎯 СЛОЖНЫЕ УГЛЕВОДЫ
   • Медленное высвобождение глюкозы
   • Гликемический индекс: 55 и ниже
   • Источники: цельнозерновые, бобовые, овощи
   • Польза: стабильная энергия, сытость

2. ⚡ ПРОСТЫЕ УГЛЕВОДЫ
   • Быстрое высвобождение энергии
   • Гликемический индекс: 70 и выше
   • Источники: фрукты, мед, молоко
   • Польза: быстрая энергия, восстановление

3. 🌾 РЕЗИСТЕНТНЫЙ КРАХМАЛ
   • Не переваривается в тонком кишечнике
   • Ферментируется в толстом кишечнике
   • Образует короткоцепочечные жирные кислоты
   • Польза: пребиотик, улучшение инсулиновой чувствительности

4. 🍠 КЛЕТЧАТКА
   • Растворимая: гелеобразование, снижение холестерина
   • Нерастворимая: увеличение объема стула
   • Польза: здоровье ЖКТ, контроль веса

🏃‍♂️ УГЛЕВОДЫ И ФИЗИЧЕСКАЯ АКТИВНОСТЬ:

• Низкая интенсивность: жиры как основное топливо
• Средняя интенсивность: 50/50 жиры и углеводы
• Высокая интенсивность: углеводы как основное топливо
• Предельная интенсивность: только углеводы

🧠 УГЛЕВОДЫ И МОЗГ:

• Мозг потребляет 120 г глюкозы в сутки
• 20% от общего расхода энергии организма
• Кетоновые тела как альтернативное топливо
• Стабильный уровень глюкозы = стабильное настроение

📊 РАСЧЕТ ПОТРЕБНОСТИ:

• Средняя активность: 3-5 г/кг массы тела
• Высокая активность: 5-7 г/кг массы тела
• Спортсмены: 8-10 г/кг массы тела
• Кетогенная диета: менее 50 г/сутки

🎯 ВРЕМЯ ПРИЕМА:

• Утро: сложные углеводы для энергии дня
• Перед тренировкой: легкоусвояемые углеводы
• После тренировки: быстрые углеводы + белок
• Вечер: умеренное количество сложных углеводов

💡 НАУЧНЫЙ ФАКТ:
Гликогеновые депо печени (100-120 г) и мышц (300-400 г) 
могут быть полностью истощены за 90 минут интенсивной тренировки.
"""
        benefits = """• ⚡ Стабильная энергия в течение дня
• 🧠 Улучшение когнитивных функций
• 💪 Повышение спортивной производительности
• 🍽️ Длительное чувство сытости"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ СОВЕТ: НАУКА УГЛЕВОДОВ И ЭНЕРГИИ",
            content, "carbs_advice", benefits
        )
    
    def generate_hydration_science(self):
        """Научный совет о гидратации и водном балансе"""
        content = """
💧 НАУКА ГИДРАТАЦИИ: ВОДА КАК ОСНОВА ЖИЗНИ И ЗДОРОВЬЯ

🔬 ФИЗИОЛОГИЧЕСКИЕ ФУНКЦИИ ВОДЫ:

1. 🧪 УНИВЕРСАЛЬНЫЙ РАСТВОРИТЕЛЬ
   • Среда для всех биохимических реакций
   • Транспорт питательных веществ
   • Выведение метаболических отходов

2. 🌡️ ТЕРМОРЕГУЛЯЦИЯ
   • Потоотделение - охлаждение организма
   • Теплоемкость - поддержание стабильной температуры
   • Кровообращение - распределение тепла

3. 🛡️ ЗАЩИТА И СМАЗКА
   • Цереброспинальная жидкость - защита мозга
   • Синовиальная жидкость - смазка суставов
   • Амниотическая жидкость - защита плода

4. ⚡ ЭЛЕКТРОЛИТНЫЙ БАЛАНС
   • Натрий-калиевый насос - клеточная функция
   • Проведение нервных импульсов
   • Мышечные сокращения

📊 СИМПТОМЫ ОБЕЗВОЖИВАНИЯ:

• 1-2%: жажда, снижение выносливости
• 3-5%: сухость во рту, снижение силы
• 6-8%: головная боль, головокружение
• 10%+: нарушение координации, спутанность сознания

🎯 РАСЧЕТ ПОТРЕБНОСТИ:

• Базовый расчет: 30 мл на 1 кг массы тела
• При физической активности: +500-1000 мл
• В жарком климате: +1000-2000 мл
• Во время болезни: +500-1500 мл

⚡ ЭЛЕКТРОЛИТЫ И ИХ ФУНКЦИИ:

• Натрий: водный баланс, нервная проводимость
• Калий: сердечный ритм, мышечные сокращения
• Кальций: кости, свертывание крови, нейромедиаторы
• Магний: 300+ ферментативных реакций, энергия

🥤 ИСТОЧНИКИ ГИДРАТАЦИИ:

• Вода: чистая гидратация
• Овощи и фрукты: 80-95% воды + электролиты
• Супы и бульоны: вода + минералы
• Травяные чаи: гидратация + фитонутриенты

🎯 ПРАКТИЧЕСКИЕ СОВЕТЫ:

• Стакан воды после пробуждения
• По стакану воды перед каждым приемом пищи
• Пить во время и после тренировки
• Мониторинг цвета мочи (светло-желтый = норма)

💡 НАУЧНЫЙ ФАКТ:
Обезвоживание всего на 2% снижает когнитивные функции 
и физическую производительность на 20-30%.
"""
        benefits = """• 💧 Оптимальная гидратация всех тканей
• ⚡ Улучшение энергетического уровня
• 🧠 Улучшение когнитивных функций
• 🏃‍♂️ Повышение физической производительности"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 СОВЕТ: НАУКА ГИДРАТАЦИИ И ВОДНОГО БАЛАНСА",
            content, "energy_advice", benefits
        )
    
    def generate_family_nutrition_advice(self):
        """Совет по семейному питанию и формированию привычек"""
        content = """
👨‍👩‍👧‍👦 НАУКА СЕМЕЙНОГО ПИТАНИЯ: КАК СОЗДАТЬ ЗДОРОВЫЕ ТРАДИЦИИ

🔬 ПСИХОЛОГИЯ ПИТАНИЯ В СЕМЬЕ:

1. 🍽️ СОВМЕСТНЫЕ ТРАПЕЗЫ
   • Укрепление семейных связей
   • Развитие социальных навыков у детей
   • Формирование здоровых пищевых привычек
   • Снижение риска расстройств пищевого поведения

2. 🎯 РОЛЕВОЕ МОДЕЛИРОВАНИЕ
   • Дети копируют пищевое поведение родителей
   • Позитивный пример здорового выбора
   • Обучение через наблюдение и участие
   • Формирование отношения к еде как к удовольствию и питанию

3. 🏠 КУХНЯ КАК ОБРАЗОВАТЕЛЬНОЕ ПРОСТРАНСТВО
   • Развитие моторных навыков через приготовление
   • Обучение математике через взвешивание
   • Изучение биологии через продукты
   • Развитие ответственности через распределение задач

📊 ВОЗРАСТНЫЕ ОСОБЕННОСТИ:

👶 ДЕТИ 2-6 ЛЕТ:
• Высокая потребность в белке для роста
• Кальций для развития костей
• Железо для когнитивного развития
• Небольшие порции, частые приемы пищи

🧒 ДЕТИ 7-12 ЛЕТ:
• Увеличение потребности в энергии
• Кальций для пика костной массы
• Цинк для иммунитета и роста
• Формирование самостоятельных привычек

👦 ПОДРОСТКИ 13-18 ЛЕТ:
• Пик роста и развития
• Высокая потребность в железе (особенно у девочек)
• Кальций для достижения максимальной костной массы
• Белок для мышечного развития

🎯 СТРАТЕГИИ УСПЕХА:

1. 🎪 ПРЕДСКАЗУЕМОСТЬ И РИТУАЛЫ
   • Регулярное время приемов пищи
   • Семейные традиции (воскресные завтраки)
   • Совместное планирование меню
   • Еженедельные "новые блюда"

2. 🎨 ТВОРЧЕСКИЙ ПОДХОД
   • Цветная сервировка
   • Интересные формы и подача
   • Тематические ужины
   • Кулинарные эксперименты

3. 📚 ОБРАЗОВАНИЕ БЕЗ НАЗОЙЛИВОСТИ
   • Обсуждение пользы продуктов в игровой форме
   • Чтение этикеток вместе
   • Посещение фермерских рынков
   • Выращивание зелени на подоконнике

💡 НАУЧНЫЙ ФАКТ:
Исследования показывают, что семьи, которые регулярно 
едят вместе, имеют на 40% более низкий риск ожирения 
у детей и лучшие академические результаты.
"""
        benefits = """• 👨‍👩‍👧‍👦 Укрепление семейных связей
• 🍎 Формирование здоровых пищевых привычек
• 🎯 Профилактика расстройств пищевого поведения
• 💫 Создание позитивных семейных традиций"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СОВЕТ: НАУКА СЕМЕЙНОГО ПИТАНИЯ",
            content, "family_advice", benefits
        )
    
    def generate_meal_prep_guide_advice(self):
        """Научный совет о планировании питания и meal prep"""
        content = """
📊 НАУКА ПЛАНИРОВАНИЯ ПИТАНИЯ: КАК ОПТИМИЗИРОВАТЬ ВРЕМЯ И ЗДОРОВЬЕ

🔬 ПСИХОЛОГИЧЕСКИЕ И ФИЗИОЛОГИЧЕСКИЕ ПРЕИМУЩЕСТВА:

1. 🧠 СНИЖЕНИЕ COGNITIVE LOAD
   • Меньше решений о еде в течение дня
   • Снижение decision fatigue
   • Сохранение ментальной энергии для важных задач
   • Уменьшение стресса от "что приготовить?"

2. 🍽️ КОНТРОЛЬ ПОРЦИЙ И КАЧЕСТВА
   • Точный расчет калорий и нутриентов
   • Предотвращение импульсных покупок
   • Гарантия сбалансированного рациона
   • Снижение потребления обработанных продуктов

3. 💰 ЭКОНОМИЯ РЕСУРСОВ
   • Снижение пищевых отходов на 20-30%
   • Экономия времени на 5-7 часов в неделю
   • Снижение затрат на питание на 15-25%
   • Оптимизация использования продуктов

📈 НАУЧНЫЕ ПРИНЦИПЫ MEAL PREP:

1. 🎯 БАЛАНС МАКРОНУТРИЕНТОВ
   • Белки: 25-30% от общей калорийности
   • Жиры: 25-35% от общей калорийности  
   • Углеводы: 40-50% от общей калорийности
   • Клетчатка: 25-35 г в сутки

2. ⏱️ ОПТИМИЗАЦИЯ ВРЕМЕНИ ПРИГОТОВЛЕНИЯ
   • Партионная готовка (batch cooking)
   • Одновременное использование духовки и плиты
   • Приготовление компонентов, а не блюд
   • Использование мультиварки и духовки

3. 🗂️ СИСТЕМА ХРАНЕНИЯ
   • Герметичные контейнеры для сохранения свежести
   • Раздельное хранение компонентов
   • Маркировка даты приготовления
   • Заморозка порций на 2-4 недели

🎯 5-ШАГОВАЯ СИСТЕМА MEAL PREP:

1. 📝 ПЛАНИРОВАНИЕ (15 минут)
   • Составление меню на неделю
   • Учет сезонности продуктов
   • Создание списка покупок

2. 🛒 ПОКУПКИ (60-90 минут)
   • Закупка на неделю вперед
   • Выбор качественных продуктов
   • Покупка оптом для экономии

3. 🍳 ПРИГОТОВЛЕНИЕ (2-3 часа)
   • Мытье и нарезка овощей
   • Приготовление круп и белков
   • Создание соусов и заправок

4. 📦 УПАКОВКА (30 минут)
   • Порционирование по контейнерам
   • Подписывание дат
   • Распределение по дням недели

5. 🗄️ ХРАНЕНИЕ
   • Холодильник: 3-4 дня
   • Морозильник: 1-3 месяца
   • Комнатная температура: 2-4 часа

💡 НАУЧНЫЙ ФАКТ:
Исследования показывают, что люди, которые планируют питание,
потребляют на 15% больше овощей и фруктов и имеют на 20% 
более низкий индекс массы тела по сравнению с теми, 
кто не планирует свое питание.
"""
        benefits = """• ⏱️ Экономия 5-7 часов в неделю
• 💰 Снижение затрат на питание на 20-30%
• 🍎 Гарантия сбалансированного рациона
• 😌 Снижение стресса и decision fatigue"""
        
        return self.visual_manager.generate_attractive_post(
            "📊 СОВЕТ: НАУКА ПЛАНИРОВАНИЯ ПИТАНИЯ",
            content, "planning_advice", benefits
        )

# Создание экземпляра генератора
scientific_generator = ScientificContentGenerator()
class MondayContentGenerator:
    """Генератор контента для понедельника - нейропитание и мозг"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_brain_breakfast(self):
        """Завтрак для улучшения когнитивных функций"""
        content = """
🧠 ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С ШПИНАТОМ И ГРЕЦКИМИ ОРЕХАМИ
КБЖУ: 420 ккал • Белки: 28г • Жиры: 32г • Углеводы: 8г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин для памяти)
• Шпинат - 100 г (фолат для нейротрансмиттеров)
• Грецкие орехи - 30 г (Омега-3 для мембран нейронов)
• Авокадо - 1/2 шт (мононенасыщенные жиры для кровотока)
• Оливковое масло - 1 ст.л. (антиоксиданты)
• Куркума - 1 ч.л. (противовоспалительное действие)

Приготовление (15 минут):
1. Яйца взбить с куркумой
2. Шпинат обжарить 2 минуты
3. Залить яйцами, готовить 5-7 минут
4. Подавать с авокадо и грецкими орехами

🎯 НАУЧНЫЙ ПОДХОД:
Холин из яиц является предшественником ацетилхолина - нейромедиатора памяти и обучения.
"""
        benefits = """• 🥚 Холин для синтеза нейромедиаторов
• 🥬 Фолат для метилирования и репарации ДНК
• 🌰 Омега-3 для текучести мембран нейронов
• 🟤 Куркумин для снижения нейровоспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С ШПИНАТОМ",
            content, "neuro_breakfast", benefits
        )

    def generate_focus_smoothie(self):
        """Смузи для концентрации и фокуса"""
        content = """
💫 СМУЗИ ДЛЯ ФОКУСА: ЧЕРНИКА И ШПИНАТ
КБЖУ: 320 ккал • Белки: 15г • Жиры: 12г • Углеводы: 38г

Ингредиенты на 2 порции:
• Черника - 150 г (антоцианы для защиты нейронов)
• Шпинат - 100 г (лютеин для когнитивного здоровья)
• Греческий йогурт - 200 г (тирозин для нейромедиаторов)
• Семена льна - 2 ст.л. (альфа-линоленовая кислота)
• Миндальное молоко - 300 мл (витамин E)
• Мед - 1 ст.л. (быстрая энергия для мозга)

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу для максимальной пользы

🎯 НАУЧНЫЙ ПОДХОД:
Антоцианы из черники улучшают нейронные связи в гиппокампе - области мозга, отвечающей за память.
"""
        benefits = """• 🫐 Антоцианы для улучшения нейропластичности
• 🥬 Лютеин для защиты от окислительного стресса
• 🥛 Тирозин для синтеза дофамина и норадреналина
• 🌱 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 СМУЗИ ДЛЯ ФОКУСА: ЧЕРНИКА И ШПИНАТ",
            content, "neuro_breakfast", benefits
        )

    def generate_memory_omelette(self):
        """Омлет для улучшения памяти"""
        content = """
📚 ОМЛЕТ ДЛЯ ПАМЯТИ: С ЛОСОСЕМ И БРОККОЛИ
КБЖУ: 380 ккал • Белки: 35г • Жиры: 24г • Углеводы: 6г

Ингредиенты на 2 порции:
• Яйца - 4 шт (холин для ацетилхолина)
• Лосось слабосоленый - 100 г (ДГК для синапсов)
• Брокколи - 150 г (сульфорафан для детокса)
• Лук - 1/2 шт (кверцетин для защиты нейронов)
• Оливковое масло - 1 ст.л.
• Укроп - 20 г (антиоксиданты)

Приготовление (20 минут):
1. Лук и брокколи обжарить 5 минут
2. Добавить лосось кубиками
3. Залить взбитыми яйцами
4. Готовить под крышкой 10 минут

🎯 НАУЧНЫЙ ПОДХОД:
Докозагексаеновая кислота (ДГК) из лосося составляет 30% структурных липидов мозга и улучшает синаптическую пластичность.
"""
        benefits = """• 🥚 Холин для нейромедиатора памяти
• 🐟 ДГК для структурной целостности мозга
• 🥦 Сульфорафан для активации детокс-ферментов
• 🧅 Кверцетин для защиты от нейродегенерации"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 ОМЛЕТ ДЛЯ ПАМЯТИ: С ЛОСОСЕМ И БРОККОЛИ",
            content, "neuro_breakfast", benefits
        )

    def generate_neuro_pancakes(self):
        """Блинчики для здоровья нервной системы"""
        content = """
🥞 НЕЙРОБЛИНЧИКИ: С БАНАНОМ И КОРИЦЕЙ
КБЖУ: 350 ккал • Белки: 18г • Жиры: 14г • Углеводы: 42г

Ингредиенты на 2 порции:
• Овсяная мука - 100 г (витамины группы B)
• Бананы - 2 шт (калий для нервной проводимости)
• Яйца - 2 шт (холин для миелиновых оболочек)
• Корица - 2 ч.л. (полифенолы для защиты)
• Грецкие орехи - 30 г (мелатонин для циркадных ритмов)
• Кленовый сироп - 2 ст.л.

Приготовление (20 минут):
1. Бананы размять вилкой
2. Смешать с яйцами и мукой
3. Добавить корицу и орехи
4. Жарить на антипригарной сковороде

🎯 НАУЧНЫЙ ПОДХОД:
Калий из бананов необходим для поддержания мембранного потенциала нейронов и проведения нервных импульсов.
"""
        benefits = """• 🌾 Витамины B для энергетического метаболизма нейронов
• 🍌 Калий для проведения нервных импульсов
• 🥚 Холин для миелинизации нервных волокон
• 🟤 Полифенолы для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 НЕЙРОБЛИНЧИКИ: С БАНАНОМ И КОРИЦЕЙ",
            content, "neuro_breakfast", benefits
        )

    def generate_brain_boost_bowl(self):
        """Энергетическая чаша для работы мозга"""
        content = """
⚡ ЭНЕРГЕТИЧЕСКАЯ ЧАША ДЛЯ МОЗГА
КБЖУ: 380 ккал • Белки: 20г • Жиры: 18г • Углеводы: 38г

Ингредиенты на 2 порции:
• Гречка - 100 г (рутин для сосудов мозга)
• Творог - 200 г (триптофан для серотонина)
• Миндаль - 40 г (рибофлавин для энергии)
• Яблоко - 1 шт (кверцетин против воспаления)
• Мед - 1 ст.л. (глюкоза для нейронов)
• Корица - 1 ч.л.

Приготовление (15 минут):
1. Гречку отварить до готовности
2. Яблоко нарезать кубиками
3. Смешать все ингредиенты
4. Заправить медом и корицей

🎯 НАУЧНЫЙ ПОДХОД:
Рутин из гречки укрепляет капилляры головного мозга, улучшая микроциркуляцию и доставку кислорода.
"""
        benefits = """• 🌾 Рутин для укрепления церебральных капилляров
• 🧀 Триптофан для синтеза серотонина
• 🌰 Рибофлавин для клеточного дыхания
• 🍎 Кверцетин для противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКАЯ ЧАША ДЛЯ МОЗГА",
            content, "neuro_breakfast", benefits
        )

    def generate_cognitive_oatmeal(self):
        """Овсянка для когнитивного здоровья"""
        content = """
🎯 ОВСЯНКА ДЛЯ ЯСНОСТИ МЫШЛЕНИЯ
КБЖУ: 340 ккал • Белки: 16г • Жиры: 12г • Углеводы: 45г

Ингредиенты на 2 порции:
• Овсяные хлопья - 80 г (бета-глюканы для холестерина)
• Семена чиа - 2 ст.л. (Омега-3 для мембран)
• Какао-порошок - 2 ст.л. (флавоноиды для кровотока)
• Банан - 1 шт (витамин B6 для нейротрансмиттеров)
• Миндальное молоко - 400 мл (витамин E)
• Стевия - по вкусу

Приготовление (10 минут):
1. Овсянку варить с молоком 7 минут
2. Добавить какао и семена чиа
3. Подавать с бананом и стевией

🎯 НАУЧНЫЙ ПОДХОД:
Флавоноиды какао улучшают церебральный кровоток и усиливают нейроваскулярную связь в областях мозга, связанных с обучением.
"""
        benefits = """• 🌾 Бета-глюканы для контроля холестерина
• 🌱 Омега-3 для структурной целостности нейронов
• 🍫 Флавоноиды для улучшения церебрального кровотока
• 🍌 Витамин B6 для синтеза ГАМК и серотонина"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ОВСЯНКА ДЛЯ ЯСНОСТИ МЫШЛЕНИЯ",
            content, "neuro_breakfast", benefits
        )

    def generate_neuro_toast(self):
        """Тосты для нервной системы"""
        content = """
🍞 НЕЙРОТОСТЫ С АВОКАДО И ЯЙЦОМ ПАШОТ
КБЖУ: 360 ккал • Белки: 22г • Жиры: 20г • Углеводы: 24г

Ингредиенты на 2 порции:
• Хлеб цельнозерновой - 4 ломтика (клетчатка для микробиома)
• Авокадо - 1 шт (лютеин для когнитивного старения)
• Яйца - 2 шт (холин для развития мозга)
• Семена тыквы - 2 ст.л. (цинк для нейротрансмиттеров)
• Лимонный сок - 1 ст.л. (витамин C)
• Специи по вкусу

Приготовление (15 минут):
1. Хлеб поджарить
2. Авокадо размять с лимонным соком
3. Яйца приготовить пашот
4. Собрать тосты, посыпать семенами

🎯 НАУЧНЫЙ ПОДХОД:
Лютеин из авокадо накапливается в мозге и связан с улучшением когнитивных функций, особенно у пожилых людей.
"""
        benefits = """• 🥑 Лютеин для защиты от когнитивного старения
• 🥚 Холин для развития и функционирования мозга
• 🌰 Цинк для модуляции нейротрансмиттеров
• 🍞 Клетчатка для продукции короткоцепочечных жирных кислот"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 НЕЙРОТОСТЫ С АВОКАДО И ЯЙЦОМ ПАШОТ",
            content, "neuro_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_brain_lunch(self):
        """Обед для оптимальной работы мозга"""
        content = """
🧠 ОБЕД ДЛЯ МОЗГА: КУРИЦА С КУРКУМОЙ И ОВОЩАМИ
КБЖУ: 450 ккал • Белки: 38г • Жиры: 22г • Углеводы: 28г

Ингредиенты на 2 порции:
• Куриная грудка - 300 г (триптофан для серотонина)
• Брокколи - 200 г (глюкозинолаты для детокса)
• Морковь - 2 шт (бета-каротин для защиты)
• Куркума - 1 ст.л. (куркумин против воспаления)
• Кунжутное масло - 1 ст.л. (сезамол)
• Чеснок - 3 зубчика (аллицин)

Приготовление (25 минут):
1. Курицу нарезать, обжарить с куркумой
2. Овощи нарезать, добавить к курице
3. Тушить 15 минут под крышкой
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Куркумин преодолевает гематоэнцефалический барьер и обладает нейропротекторными свойствами, снижая риск нейродегенеративных заболеваний.
"""
        benefits = """• 🍗 Триптофан для синтеза серотонина
• 🥦 Глюкозинолаты для активации детокс-путей
• 🥕 Бета-каротин для антиоксидантной защиты
• 🟤 Куркумин для снижения нейровоспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ОБЕД ДЛЯ МОЗГА: КУРИЦА С КУРКУМОЙ",
            content, "neuro_lunch", benefits
        )

    def generate_focus_bowl(self):
        """Чаша для концентрации внимания"""
        content = """
🎯 ЧАША ДЛЯ КОНЦЕНТРАЦИИ: КИНОА С ОВОЩАМИ
КБЖУ: 420 ккал • Белки: 24г • Жиры: 18г • Углеводы: 48г

Ингредиенты на 2 порции:
• Киноа - 120 г (магний для синапсов)
• Нут - 150 г (витамин B6 для нейротрансмиттеров)
• Шпинат - 100 г (магний для релаксации)
• Гранат - 1/2 шт (пуникалагин для памяти)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

Приготовление (20 минут):
1. Киноа и нут отварить
2. Шпинат обжарить 2 минуты
3. Гранат очистить от зерен
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Магний из киноа и шпината регулирует NMDA-рецепторы, участвующие в синаптической пластичности и процессах обучения.
"""
        benefits = """• 🌾 Магний для регуляции NMDA-рецепторов
• 🫘 Витамин B6 для синтеза ГАМК
• 🥬 Магний для мышечной и нервной релаксации
• 🍓 Пуникалагин для улучшения вербальной памяти"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ЧАША ДЛЯ КОНЦЕНТРАЦИИ: КИНОА С ОВОЩАМИ",
            content, "neuro_lunch", benefits
        )

    def generate_memory_salad(self):
        """Салат для улучшения памяти"""
        content = """
📚 САЛАТ ДЛЯ ПАМЯТИ: С ЛОСОСЕМ И АВОКАДО
КБЖУ: 480 ккал • Белки: 32г • Жиры: 35г • Углеводы: 12г

Ингредиенты на 2 порции:
• Лосось на гриле - 200 г (ДГК для синапсов)
• Авокадо - 1 шт (лютеин для когнитивного здоровья)
• Руккола - 100 г (нитраты для кровотока)
• Грецкие орехи - 40 г (полифенолы)
• Клюква сушеная - 30 г (проантоцианидины)
• Оливковое масло - 2 ст.л.

Приготовление (15 минут):
1. Лосось нарезать кубиками
2. Авокадо нарезать ломтиками
3. Смешать все ингредиенты
4. Заправить оливковым маслом

🎯 НАУЧНЫЙ ПОДХОД:
Докозагексаеновая кислота (ДГК) составляет до 30% фосфолипидов мембран нейронов и критически важна для синаптической передачи.
"""
        benefits = """• 🐟 ДГК для структурной целостности нейронов
• 🥑 Лютеин для накопления в мозговой ткани
• 🥬 Нитраты для улучшения церебральной перфузии
• 🌰 Полифенолы для защиты от окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 САЛАТ ДЛЯ ПАМЯТИ: С ЛОСОСЕМ И АВОКАДО",
            content, "neuro_lunch", benefits
        )

    def generate_neuro_soup(self):
        """Суп для здоровья нервной системы"""
        content = """
🍲 НЕЙРОСУП: ТЫКВЕННЫЙ С ИМБИРЕМ
КБЖУ: 320 ккал • Белки: 18г • Жиры: 12г • Углеводы: 38г

Ингредиенты на 2 порции:
• Тыква - 500 г (бета-каротин для защиты)
• Морковь - 2 шт (витамин A для зрения)
• Имбирь - 3 см (гингерол против воспаления)
• Кокосовое молоко - 200 мл (МСТ для энергии)
• Лук - 1 шт (кверцетин)
• Овощной бульон - 500 мл

Приготовление (30 минут):
1. Овощи нарезать кубиками
2. Варить в бульоне 20 минут
3. Добавить имбирь и кокосовое молоко
4. Взбить блендером до кремообразной консистенции

🎯 НАУЧНЫЙ ПОДХОД:
Среднецепочечные триглицериды (МСТ) из кокосового молока метаболизируются в кетоновые тела, которые являются альтернативным источником энергии для мозга.
"""
        benefits = """• 🎃 Бета-каротин для антиоксидантной защиты
• 🥕 Витамин A для зрительной функции
• 🟤 Гингерол для снижения нейровоспаления
• 🥥 МСТ для продукции кетоновых тел"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 НЕЙРОСУП: ТЫКВЕННЫЙ С ИМБИРЕМ",
            content, "neuro_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_brain_dinner(self):
        """Ужин для восстановления мозга"""
        content = """
🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ МОЗГА: ИНДЕЙКА С БРОККОЛИ
КБЖУ: 380 ккал • Белки: 42г • Жиры: 18г • Углеводы: 15г

Ингредиенты на 2 порции:
• Индейка - 300 г (триптофан для сна)
• Брокколи - 250 г (сульфорафан для детокса)
• Цветная капуста - 200 г (холин)
• Миндаль - 30 г (магний для релаксации)
• Оливковое масло - 1 ст.л.
• Розмарин - 1 веточка (карнозиновая кислота)

Приготовление (25 минут):
1. Индейку нарезать, замариновать с розмарином
2. Овощи нарезать соцветиями
3. Запекать 20 минут при 180°C
4. Посыпать миндалем перед подачей

🎯 НАУЧНЫЙ ПОДХОД:
Триптофан из индейки является предшественником мелатонина - гормона сна, который также обладает нейропротекторными свойствами.
"""
        benefits = """• 🦃 Триптофан для синтеза мелатонина
• 🥦 Сульфорафан для активации детокс-ферментов
• 🥦 Холин для структурной целостности мембран
• 🌰 Магний для GABA-ергической передачи"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ МОЗГА: ИНДЕЙКА С БРОККОЛИ",
            content, "neuro_dinner", benefits
        )

    def generate_sleep_salmon(self):
        """Ужин для качественного сна"""
        content = """
😴 ЛОСОСЬ ДЛЯ КАЧЕСТВЕННОГО СНА
КБЖУ: 400 ккал • Белки: 35г • Жиры: 26г • Углеводы: 8г

Ингредиенты на 2 порции:
• Лосось - 300 г (витамин D для нейротрансмиттеров)
• Шпинат - 150 г (магний для релаксации)
• Спаржа - 150 г (фолат для метилирования)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (антиоксиданты)
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Лосось приготовить на пару 12 минут
2. Овощи обжарить 5 минут
3. Подавать с лимонным соком и укропом

🎯 НАУЧНЫЙ ПОДХОД:
Витамин D регулирует экспрессию генов, участвующих в синтезе нейротрансмиттеров, и связан с качеством сна и настроением.
"""
        benefits = """• 🐟 Витамин D для регуляции нейротрансмиттеров
• 🥬 Магний для активации парасимпатической системы
• 🌱 Фолат для процессов метилирования в мозге
• 🍋 Витамин C для синтеза норадреналина"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ЛОСОСЬ ДЛЯ КАЧЕСТВЕННОГО СНА",
            content, "neuro_dinner", benefits
        )

    def generate_calm_chicken(self):
        """Ужин для релаксации и спокойствия"""
        content = """
☁️ КУРИЦА ДЛЯ СПОКОЙСТВИЯ: С БАЗИЛИКОМ И ОРЕХАМИ
КБЖУ: 360 ккал • Белки: 38г • Жиры: 20г • Углеводы: 6г

Ингредиенты на 2 порции:
• Куриное филе - 300 г (триптофан)
• Базилик - 50 г (эвгенол для релаксации)
• Кедровые орехи - 30 г (цинк для ГАМК)
• Чеснок - 2 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

Приготовление (20 минут):
1. Курицу нарезать кубиками
2. Обжарить с чесноком и базиликом
3. Добавить кедровые орехи
4. Подавать с лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Цинк из кедровых орехов модулирует GABA-рецепторы, усиливая тормозную нейротрансмиссию и способствуя релаксации.
"""
        benefits = """• 🍗 Триптофан для серотонинового пути
• 🌿 Эвгенол для мышечной релаксации
• 🌰 Цинк для модуляции GABA-рецепторов
• 🧄 Аллицин для противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "☁️ КУРИЦА ДЛЯ СПОКОЙСТВИЯ: С БАЗИЛИКОМ И ОРЕГАНОМ",
            content, "neuro_dinner", benefits
        )

    def generate_neuro_stew(self):
        """Рагу для здоровья нервной системы"""
        content = """
🍲 НЕЙРОРАГУ: С ЧЕЧЕВИЦЕЙ И ОВОЩАМИ
КБЖУ: 350 ккал • Белки: 24г • Жиры: 10г • Углеводы: 45г

Ингредиенты на 2 порции:
• Чечевица - 150 г (фолат для нейротрансмиттеров)
• Цукини - 1 шт (калий для проводимости)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 2 стебля (апигенин)
• Томаты - 2 шт (ликопин)
• Специи: куркума, кумин

Приготовление (30 минут):
1. Чечевицу отварить 20 минут
2. Овощи нарезать кубиками
3. Тушить все вместе 10 минут
4. Добавить специи в конце

🎯 НАУЧНЫЙ ПОДХОД:
Фолат из чечевицы критически важен для метилирования ДНК в нейронах и синтеза нейротрансмиттеров, включая серотонин и дофамин.
"""
        benefits = """• 🌱 Фолат для метилирования и синтеза нейротрансмиттеров
• 🥒 Калий для поддержания мембранного потенциала
• 🥕 Бета-каротин для антиоксидантной защиты
• 🥬 Апигенин для нейрогенеза"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 НЕЙРОРАГУ: С ЧЕЧЕВИЦЕЙ И ОВОЩАМИ",
            content, "neuro_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_brain_dessert(self):
        """Десерт для когнитивного здоровья"""
        content = """
🍫 ДЕСЕРТ ДЛЯ МОЗГА: ШОКОЛАДНЫЙ МУСС С АВОКАДО
КБЖУ: 280 ккал • Белки: 8г • Жиры: 22г • Углеводы: 18г

Ингредиенты на 2 порции:
• Авокадо - 1 шт (лютеин для когнитивного здоровья)
• Какао-порошок - 3 ст.л. (флавоноиды для кровотока)
• Мед - 2 ст.л. (глюкоза для энергии)
• Кокосовые сливки - 100 мл (МСТ для кетонов)
• Ванильный экстракт - 1 ч.л.
• Ягоды для подачи - 100 г

Приготовление (10 минут + охлаждение):
1. Авокадо очистить от кожуры
2. Все ингредиенты взбить в блендере
3. Охладить 2 часа
4. Подавать с ягодами

🎯 НАУЧНЫЙ ПОДХОД:
Флавоноиды какао улучшают эндотелий-зависимую вазодилатацию, увеличивая церебральный кровоток и оксигенацию мозга.
"""
        benefits = """• 🥑 Лютеин для накопления в мозговой ткани
• 🍫 Флавоноиды для улучшения церебральной перфузии
• 🍯 Глюкоза для немедленного энергоснабжения нейронов
• 🥥 МСТ для альтернативного энергоснабжения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ДЕСЕРТ ДЛЯ МОЗГА: ШОКОЛАДНЫЙ МУСС С АВОКАДО",
            content, "neuro_dessert", benefits
        )

    def generate_focus_treat(self):
        """Десерт для улучшения фокуса"""
        content = """
🎯 ДЕСЕРТ ДЛЯ ФОКУСА: БАНОЧНО-ОРЕХОВЫЕ КОНФЕТЫ
КБЖУ: 220 ккал • Белки: 6г • Жиры: 14г • Углеводы: 22г

Ингредиенты на 8 конфет:
• Финики - 200 г (натуральная сладость)
• Грецкие орехи - 100 г (Омега-3 для мембран)
• Миндаль - 50 г (рибофлавин для энергии)
• Какао-порошок - 2 ст.л. (теобромин)
• Кокосовая стружка - 50 г (для обваливания)

Приготовление (15 минут + охлаждение):
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке, охладить

🎯 НАУЧНЫЙ ПОДХОД:
Теобромин из какао является мягким стимулятором, улучшающим когнитивные функции без выраженных побочных эффектов кофеина.
"""
        benefits = """• 🫒 Натуральные сахара для энергии без резких скачков
• 🌰 Омега-3 для структурной целостности нейронов
• 🌰 Рибофлавин для клеточного дыхания
• 🍫 Теобромин для мягкой стимуляции когнитивных функций"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ДЕСЕРТ ДЛЯ ФОКУСА: БАНОЧНО-ОРЕХОВЫЕ КОНФЕТЫ",
            content, "neuro_dessert", benefits
        )

# Создание экземпляра генератора
monday_generator = MondayContentGenerator()
class TuesdayContentGenerator:
    """Генератор контента для вторника - белки и мышечное здоровье"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_muscle_breakfast(self):
        """Завтрак для мышечного синтеза и восстановления"""
        content = """
💪 БЕЛКОВЫЙ ЗАВТРАК: СКРЭМБЛ С ТВОРОГОМ И ОВОЩАМИ
КБЖУ: 420 ккал • Белки: 45г • Жиры: 22г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 5 шт (30г белка, лейцин для синтеза)
• Творог 5% - 150 г (15г казеина)
• Шпинат - 100 г (железо для оксигенации)
• Помидоры - 2 шт (ликопин для восстановления)
• Оливковое масло - 1 ст.л.
• Зеленый лук - 20 г

Приготовление (15 минут):
1. Яйца взбить с творогом до однородности
2. Овощи нарезать, обжарить 3 минуты
3. Залить яично-творожной смесью
4. Готовить 7-10 минут на среднем огне

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация сывороточного белка (яйца) и казеина (творог) обеспечивает как быстрый, так и пролонгированный аминокислотный профиль для мышечного синтеза.
"""
        benefits = """• 🥚 Быстрый белок для немедленного синтеза
• 🧀 Медленный белок для продолжительной поддержки
• 🥬 Железо для транспорта кислорода к мышцам
• 🍅 Ликопин для снижения окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 БЕЛКОВЫЙ ЗАВТРАК: СКРЭМБЛ С ТВОРОГОМ",
            content, "protein_breakfast", benefits
        )

    def generate_energy_eggs(self):
        """Энергетический завтрак с высоким содержанием белка"""
        content = """
⚡ ЭНЕРГЕТИЧЕСКИЕ ЯЙЦА: ФАРШИРОВАННЫЕ С КУРИЦЕЙ
КБЖУ: 380 ккал • Белки: 40г • Жиры: 20г • Углеводы: 8г

Ингредиенты на 2 порции:
• Яйца - 6 шт (36г полноценного белка)
• Куриная грудка - 150 г (35г белка)
• Авокадо - 1/2 шт (полезные жиры)
• Греческий йогурт - 100 г (10г белка)
• Горчица - 1 ч.л.
• Укроп - 20 г

Приготовление (20 минут):
1. Яйца сварить вкрутую, очистить
2. Курицу отварить, измельчить
3. Желтки смешать с курицей, йогуртом и горчицей
4. Нафаршировать яйца, подавать с авокадо

🎯 НАУЧНЫЙ ПОДХОД:
Яйца содержат все 9 незаменимых аминокислот в идеальном соотношении, что делает их эталонным источником белка с биодоступностью 97%.
"""
        benefits = """• 🥚 Полноценный аминокислотный профиль
• 🍗 Дополнительный белок для синтеза
• 🥑 Полезные жиры для гормонального баланса
• 🥛 Пробиотики для усвоения нутриентов"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЕ ЯЙЦА: ФАРШИРОВАННЫЕ С КУРИЦЕЙ",
            content, "protein_breakfast", benefits
        )

    def generate_strength_smoothie(self):
        """Протеиновый смузи для силы и энергии"""
        content = """
💥 СИЛОВОЙ СМУЗИ: БАНАН И МИНДАЛЬ
КБЖУ: 350 ккал • Белки: 28г • Жиры: 14г • Углеводы: 32г

Ингредиенты на 2 порции:
• Греческий йогурт - 300 г (30г белка)
• Банан - 2 шт (калий для сокращений)
• Миндаль - 50 г (витамин E для защиты)
• Семена чиа - 2 ст.л. (клетчатка)
• Мед - 1 ст.л. (гликоген)
• Ванильный экстракт - 1 ч.л.

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу после приготовления

🎯 НАУЧНЫЙ ПОДХОД:
Калий из бананов необходим для поддержания мембранного потенциала мышечных клеток и нормального мышечного сокращения.
"""
        benefits = """• 🥛 30г белка для мышечного синтеза
• 🍌 Калий для электролитного баланса
• 🌰 Витамин E для защиты клеточных мембран
• 🌱 Клетчатка для стабильной энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "💥 СИЛОВОЙ СМУЗИ: БАНАН И МИНДАЛЬ",
            content, "protein_breakfast", benefits
        )

    def generate_power_omelette(self):
        """Омлет для силы и выносливости"""
        content = """
🏋️ ОМЛЕТ СИЛЫ: С ГОВЯДИНОЙ И ОВОЩАМИ
КБЖУ: 450 ккал • Белки: 48г • Жиры: 25г • Углеводы: 10г

Ингредиенты на 2 порции:
• Яйца - 6 шт (36г белка)
• Говяжий фарш - 200 г (40г белка, железо)
• Болгарский перец - 1 шт (витамин C)
• Лук - 1/2 шт (кверцетин)
• Шпинат - 100 г (фолат)
• Оливковое масло - 1 ст.л.

Приготовление (25 минут):
1. Фарш обжарить с луком 10 минут
2. Добавить овощи, готовить 5 минут
3. Залить взбитыми яйцами
4. Готовить под крышкой 8-10 минут

🎯 НАУЧНЫЙ ПОДХОД:
Гемовое железо из говядины обладает высокой биодоступностью (15-35%) и критически важно для синтеза гемоглобина и миоглобина - белков, переносящих кислород в мышцы.
"""
        benefits = """• 🥚 Высококачественный яичный белок
• 🥩 Гемовое железо для оксигенации мышц
• 🌶️ Витамин C для усвоения негемового железа
• 🥬 Фолат для синтеза ДНК в делящихся клетках"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ ОМЛЕТ СИЛЫ: С ГОВЯДИНОЙ И ОВОЩАМИ",
            content, "protein_breakfast", benefits
        )

    def generate_protein_pancakes(self):
        """Белковые блинчики для длительной сытости"""
        content = """
🥞 ПРОТЕИНОВЫЕ БЛИНЧИКИ: С ТВОРОГОМ И ЯГОДАМИ
КБЖУ: 380 ккал • Белки: 35г • Жиры: 12г • Углеводы: 35г

Ингредиенты на 2 порции:
• Творог 5% - 250 г (25г белка)
• Овсяная мука - 80 г (12г белка)
• Яйца - 2 шт (12г белка)
• Разрыхлитель - 1 ч.л.
• Ягоды - 150 г (антиоксиданты)
• Стевия - по вкусу

Приготовление (20 минут):
1. Творог, яйца и муку смешать в блендере
2. Добавить разрыхлитель и стевию
3. Жарить на антипригарной сковороде
4. Подавать с свежими ягодами

🎯 НАУЧНЫЙ ПОДХОД:
Казеин из творога образует в желудке гель, который замедляет опорожнение желудка и обеспечивает продолжительное высвобождение аминокислот в кровоток (до 7 часов).
"""
        benefits = """• 🧀 Медленный белок для продолжительного синтеза
• 🌾 Растительный белок для разнообразия аминокислот
• 🥚 Полноценный аминокислотный профиль
• 🍓 Антиоксиданты для восстановления после нагрузок"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 ПРОТЕИНОВЫЕ БЛИНЧИКИ: С ТВОРОГОМ И ЯГОДАМИ",
            content, "protein_breakfast", benefits
        )

    def generate_amino_toast(self):
        """Тосты с высоким содержанием аминокислот"""
        content = """
🍞 АМИНОКИСЛОТНЫЕ ТОСТЫ: С ЯЙЦОМ И ЛОСОСЕМ
КБЖУ: 400 ккал • Белки: 38г • Жиры: 18г • Углеводы: 24г

Ингредиенты на 2 порции:
• Хлеб цельнозерновой - 4 ломтика (8г белка)
• Яйца пашот - 4 шт (24г белка)
• Лосось слабосоленый - 100 г (20г белка)
• Авокадо - 1/2 шт (полезные жиры)
• Руккола - 50 г (нитраты)
• Лимонный сок - 1 ст.л.

Приготовление (15 минут):
1. Хлеб поджарить
2. Приготовить яйца пашот
3. Авокадо размять с лимонным соком
4. Собрать тосты слоями

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация животных и растительных источников белка обеспечивает полный спектр аминокислот и синергетический эффект для мышечного синтеза.
"""
        benefits = """• 🍞 Растительный белок с клетчаткой
• 🥚 Высокобиодоступный животный белок
• 🐟 Омега-3 для противовоспалительного эффекта
• 🥑 Полезные жиры для усвоения жирорастворимых витаминов"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 АМИНОКИСЛОТНЫЕ ТОСТЫ: С ЯЙЦОМ И ЛОСОСЕМ",
            content, "protein_breakfast", benefits
        )

    def generate_muscle_fuel_bowl(self):
        """Энергетическая чаша для мышечного топлива"""
        content = """
🔥 ЧАША МЫШЕЧНОГО ТОПЛИВА: КИНОА С ИНДЕЙКОЙ
КБЖУ: 420 ккал • Белки: 42г • Жиры: 15г • Углеводы: 35г

Ингредиенты на 2 порции:
• Киноа - 120 г (16г полноценного белка)
• Индейка - 200 г (40г белка)
• Брокколи - 150 г (растительный белок)
• Морковь - 2 шт (бета-каротин)
• Тахини - 2 ст.л. (аминокислоты)
• Лимонный сок - 2 ст.л.

Приготовление (25 минут):
1. Киноа отварить 15 минут
2. Индейку запечь 20 минут
3. Овощи приготовить на пару
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Киноа - один из немногих растительных продуктов, содержащих все 9 незаменимых аминокислот, что делает его ценным источником белка для вегетарианцев и веганов.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🦃 Постный животный белок
• 🥦 Дополнительный растительный белок
• 🫕 Сезам для метионина и цистеина"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЧАША МЫШЕЧНОГО ТОПЛИВА: КИНОА С ИНДЕЙКОЙ",
            content, "protein_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_muscle_lunch(self):
        """Обед для мышечного роста и восстановления"""
        content = """
💪 ОБЕД ДЛЯ РОСТА МЫШЦ: КУРИЦА С БУРЫМ РИСОМ
КБЖУ: 520 ккал • Белки: 50г • Жиры: 18г • Углеводы: 45г

Ингредиенты на 2 порции:
• Куриная грудка - 400 г (80г белка)
• Бурый рис - 150 г (12г белка, магний)
• Брокколи - 200 г (растительный белок)
• Морковь - 2 шт (витамин A)
• Кунжутное масло - 1 ст.л.
• Соевый соус - 2 ст.л.

Приготовление (30 минут):
1. Рис отварить 25 минут
2. Курицу запечь 20 минут
3. Овощи приготовить на пару
4. Смешать все компоненты

🎯 НАУЧНЫЙ ПОДХОД:
Лейцин из куриной грудки активирует mTOR-путь - ключевой регулятор синтеза мышечного белка. Порция в 30-40г белка максимально стимулирует мышечный синтез.
"""
        benefits = """• 🍗 Лейцин для активации mTOR-пути
• 🍚 Магний для мышечного расслабления
• 🥦 Растительный белок для разнообразия аминокислот
• 🥕 Витамин A для иммунной функции"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 ОБЕД ДЛЯ РОСТА МЫШЦ: КУРИЦА С БУРЫМ РИСОМ",
            content, "protein_lunch", benefits
        )

    def generate_protein_bowl(self):
        """Протеиновая чаша для восстановления"""
        content = """
🔄 ВОССТАНОВИТЕЛЬНАЯ ЧАША: С ТУНЦОМ И НУТОМ
КБЖУ: 480 ккал • Белки: 46г • Жиры: 20г • Углеводы: 32г

Ингредиенты на 2 порции:
• Тунец консервированный - 200 г (50г белка)
• Нут - 150 г (15г белка)
• Огурцы - 2 шт (вода)
• Помидоры - 2 шт (ликопин)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

Приготовление (15 минут):
1. Нут отварить или использовать консервированный
2. Овощи нарезать кубиками
3. Смешать все ингредиенты
4. Заправить маслом и лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Тунец богат селеном - микроэлементом, который входит в состав глутатионпероксидазы, ключевого антиоксидантного фермента, защищающего мышечные клетки от окислительного повреждения.
"""
        benefits = """• 🐟 Селен для антиоксидантной защиты
• 🫘 Растительный белок с клетчаткой
• 🥒 Гидратация для восстановления
• 🍅 Ликопин для снижения воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ВОССТАНОВИТЕЛЬНАЯ ЧАША: С ТУНЦОМ И НУТОМ",
            content, "protein_lunch", benefits
        )

    def generate_strength_salad(self):
        """Салат для силы и выносливости"""
        content = """
💥 САЛАТ СИЛЫ: С ГОВЯДИНОЙ И КИНОА
КБЖУ: 460 ккал • Белки: 44г • Жиры: 22г • Углеводы: 25г

Ингредиенты на 2 порции:
• Говядина стейк - 300 г (60г белка, креатин)
• Киноа - 100 г (14г белка)
• Руккола - 100 г (нитраты)
• Грецкие орехи - 40 г (Омега-3)
• Сыр пармезан - 50 г (15г белка)
• Бальзамический уксус - 2 ст.л.

Приготовление (25 минут):
1. Говядину обжарить до средней прожарки
2. Киноа отварить 15 минут
3. Смешать все ингредиенты
4. Заправить бальзамиком

🎯 НАУЧНЫЙ ПОДХОД:
Говядина - естественный источник креатина, который увеличивает запасы фосфокреатина в мышцах, улучшая производительность при высокоинтенсивных упражнениях на 10-15%.
"""
        benefits = """• 🥩 Креатин для энергетического метаболизма
• 🌾 Полноценный растительный белок
• 🥬 Нитраты для улучшения кровотока
• 🌰 Омега-3 для противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "💥 САЛАТ СИЛЫ: С ГОВЯДИНОЙ И КИНОА",
            content, "protein_lunch", benefits
        )

    def generate_power_soup(self):
        """Энергетический суп для силы"""
        content = """
⚡ СУП СИЛЫ: ЧЕЧЕВИЧНЫЙ С КУРИЦЕЙ
КБЖУ: 400 ккал • Белки: 38г • Жиры: 12г • Углеводы: 40г

Ингредиенты на 2 порции:
• Чечевица - 150 г (25г белка)
• Куриное филе - 200 г (40г белка)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 2 стебля (натрий)
• Лук - 1 шт (кверцетин)
• Овощной бульон - 1 л

Приготовление (35 минут):
1. Курицу отварить в бульоне 20 минут
2. Добавить овощи и чечевицу
3. Варить 15 минут до готовности
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Чечевица содержит значительное количество BCAA (лейцин, изолейцин, валин), которые составляют 35% мышечного белка и могут использоваться непосредственно мышцами как источник энергии.
"""
        benefits = """• 🌱 BCAA для непосредственного энергоснабжения
• 🍗 Высококачественный животный белок
• 🥕 Бета-каротин для антиоксидантной защиты
• 🥬 Электролиты для гидратации"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ СУП СИЛЫ: ЧЕЧЕВИЧНЫЙ С КУРИЦЕЙ",
            content, "protein_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_muscle_dinner(self):
        """Ужин для ночного мышечного восстановления"""
        content = """
🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: ТВОРОГ С ОРЕХАМИ
КБЖУ: 350 ккал • Белки: 40г • Жиры: 16г • Углеводы: 12г

Ингредиенты на 2 порции:
• Творог 5% - 400 г (40г казеина)
• Миндаль - 50 г (10г белка, магний)
• Семена тыквы - 30 г (7г белка, цинк)
• Корица - 1 ч.л. (антиоксиданты)
• Стевия - по вкусу
• Ванильный экстракт - 1 ч.л.

Приготовление (5 минут):
1. Творог смешать с ванилью и стевией
2. Добавить орехи и семена
3. Посыпать корицей
4. Подавать комнатной температуры

🎯 НАУЧНЫЙ ПОДХОД:
Казеин из творога медленно переваривается, обеспечивая продолжительное высвобождение аминокислот в кровоток в течение 6-7 часов, что идеально для ночного мышечного восстановления.
"""
        benefits = """• 🧀 Медленный белок для ночного синтеза
• 🌰 Магний для мышечного расслабления
• 🎃 Цинк для иммунной функции
• 🟤 Антиоксиданты для снижения воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: ТВОРОГ С ОРЕХАМИ",
            content, "protein_dinner", benefits
        )

    def generate_recovery_fish(self):
        """Рыба для восстановления после нагрузок"""
        content = """
🔄 ВОССТАНОВИТЕЛЬНАЯ РЫБА: ТРЕСКА С ОВОЩАМИ
КБЖУ: 380 ккал • Белки: 42г • Жиры: 15г • Углеводы: 18г

Ингредиенты на 2 порции:
• Треска - 400 г (70г белка)
• Цукини - 2 шт (калий)
• Болгарский перец - 1 шт (витамин C)
• Лимон - 1/2 шт (витамин C)
• Оливковое масло - 1 ст.л.
• Укроп - 20 г

Приготовление (25 минут):
1. Треску запечь с лимоном 20 минут
2. Овощи обжарить 8-10 минут
3. Подавать рыбу с овощами и укропом

🎯 НАУЧНЫЙ ПОДХОД:
Треска - отличный источник селена и йода. Йод необходим для синтеза тиреоидных гормонов, которые регулируют метаболизм и влияют на мышечную функцию.
"""
        benefits = """• 🐟 Йод для функции щитовидной железы
• 🥒 Калий для электролитного баланса
• 🌶️ Витамин C для синтеза коллагена
• 🍋 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ВОССТАНОВИТЕЛЬНАЯ РЫБА: ТРЕСКА С ОВОЩАМИ",
            content, "protein_dinner", benefits
        )

    def generate_repair_chicken(self):
        """Курица для репарации мышечных тканей"""
        content = """
🔧 КУРИЦА ДЛЯ РЕПАРАЦИИ: С БРОККОЛИ И ГРИБАМИ
КБЖУ: 400 ккал • Белки: 48г • Жиры: 18г • Углеводы: 12г

Ингредиенты на 2 порции:
• Куриные бедра - 400 г (60г белка)
• Брокколи - 250 г (растительный белок)
• Шампиньоны - 200 г (витамин D)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Специи по вкусу

Приготовление (30 минут):
1. Курицу нарезать, обжарить 10 минут
2. Добавить овощи и чеснок
3. Тушить 15 минут под крышкой
4. Подавать горячим

🎯 НАУЧНЫЙ ПОДХОД:
Витамин D из грибов (при УФ-облучении) регулирует экспрессию более 200 генов, включая гены, участвующие в мышечном синтезе и функции. Дефицит витамина D ассоциирован с мышечной слабостью.
"""
        benefits = """• 🍗 Высококачественный животный белок
• 🥦 Растительный белок для разнообразия
• 🍄 Витамин D для мышечной функции
• 🧄 Противовоспалительные соединения"""
        
        return self.visual_manager.generate_attractive_post(
            "🔧 КУРИЦА ДЛЯ РЕПАРАЦИИ: С БРОККОЛИ И ГРИБАМИ",
            content, "protein_dinner", benefits
        )

    def generate_protein_stew(self):
        """Рагу для мышечного здоровья"""
        content = """
🍲 МЫШЕЧНОЕ РАГУ: С ИНДЕЙКОЙ И ФАСОЛЬЮ
КБЖУ: 420 ккал • Белки: 45г • Жиры: 14г • Углеводы: 35г

Ингредиенты на 2 порции:
• Фарш индейки - 300 г (55г белка)
• Фасоль красная - 150 г (20г белка)
• Томаты в собственном соку - 400 г (ликопин)
• Лук - 1 шт (кверцетин)
• Морковь - 2 шт (бета-каротин)
• Специи: паприка, кумин

Приготовление (40 минут):
1. Фарш обжарить с луком 10 минут
2. Добавить овощи и фасоль
3. Тушить 25-30 минут
4. Добавить специи в конце

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация животного и растительного белка создает синергетический эффект, улучшая общий аминокислотный скор и усвояемость белка на 15-20% по сравнению с изолированными источниками.
"""
        benefits = """• 🦃 Постный животный белок
• 🫘 Растительный белок с клетчаткой
• 🍅 Ликопин для антиоксидантной защиты
• 🥕 Бета-каротин для иммунной функции"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 МЫШЕЧНОЕ РАГУ: С ИНДЕЙКОЙ И ФАСОЛЬЮ",
            content, "protein_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_protein_dessert(self):
        """Протеиновый десерт для удовлетворения сладкого"""
        content = """
🍫 ПРОТЕИНОВЫЙ ДЕСЕРТ: ШОКОЛАДНЫЙ ПУДИНГ
КБЖУ: 280 ккал • Белки: 25г • Жиры: 12г • Углеводы: 20г

Ингредиенты на 2 порции:
• Творог 5% - 300 г (30г белка)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Желатин - 10 г (коллаген)
• Стевия - по вкусу
• Ванильный экстракт - 1 ч.л.
• Ягоды - 100 г (антиоксиданты)

Приготовление (15 минут + охлаждение):
1. Желатин растворить согласно инструкции
2. Творог взбить с какао и стевией
3. Добавить желатин, перемешать
4. Разлить по формам, охладить 4 часа

🎯 НАУЧНЫЙ ПОДХОД:
Коллаген из желатина содержит уникальный аминокислотный профиль (глицин, пролин, гидроксипролин), который поддерживает здоровье соединительной ткани, суставов и кожи.
"""
        benefits = """• 🧀 Казеин для продолжительного синтеза
• 🍫 Флавоноиды для улучшения кровотока
• 🧪 Коллаген для соединительной ткани
• 🍓 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ПРОТЕИНОВЫЙ ДЕСЕРТ: ШОКОЛАДНЫЙ ПУДИНГ",
            content, "protein_dessert", benefits
        )

    def generate_muscle_treat(self):
        """Полезное лакомство для мышц"""
        content = """
🎯 МЫШЕЧНОЕ ЛАКОМСТВО: БЕЛКОВЫЕ БАРЫ
КБЖУ: 240 ккал • Белки: 20г • Жиры: 10г • Углеводы: 18г

Ингредиенты на 8 баров:
• Протеин ванильный - 100 г (80г белка)
• Овсяные хлопья - 100 г (13г белка)
• Арахисовая паста - 80 г (20г белка)
• Мед - 3 ст.л. (связующий компонент)
• Семена чиа - 2 ст.л. (Омега-3)
• Кокосовая стружка - 50 г

Приготовление (20 минут + охлаждение):
1. Все ингредиенты смешать в блендере
2. Выложить в форму, уплотнить
3. Охладить 2 часа
4. Нарезать на бары

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация быстрого (сывороточный протеин) и медленного (овес) белка обеспечивает как немедленное, так и пролонгированное высвобождение аминокислот, идеальное для перекуса до или после тренировки.
"""
        benefits = """• 💨 Быстрый белок для немедленного синтеза
• 🌾 Медленный белок для продолжительной поддержки
• 🥜 Полезные жиры для гормонального баланса
• 🌱 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 МЫШЕЧНОЕ ЛАКОМСТВО: БЕЛКОВЫЕ БАРЫ",
            content, "protein_dessert", benefits
        )

# Создание экземпляра генератора
tuesday_generator = TuesdayContentGenerator()
class WednesdayContentGenerator:
    """Генератор контента для среды - овощи, детокс и клетчатка"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_detox_breakfast(self):
        """Завтрак для очищения и детокса"""
        content = """
🌿 ДЕТОКС-ЗАВТРАК: ЗЕЛЕНЫЙ СМУЗИ БОУЛ
КБЖУ: 320 ккал • Белки: 15г • Жиры: 12г • Углеводы: 38г

Ингредиенты на 2 порции:
• Шпинат - 150 г (хлорофилл для детокса)
• Киви - 2 шт (витамин C для глутатиона)
• Авокадо - 1/2 шт (глутатион для печени)
• Семена льна - 2 ст.л. (клетчатка для ЖКТ)
• Имбирь - 2 см (гингерол для пищеварения)
• Вода - 300 мл

Приготовление (5 минут):
1. Все ингредиенты поместить в блендер
2. Взбивать до однородной консистенции
3. Подавать сразу для максимальной пользы

🎯 НАУЧНЫЙ ПОДХОД:
Хлорофилл из зеленых листовых овощей структурно похож на гемоглобин и способен связывать тяжелые металлы и токсины, облегчая их выведение из организма.
"""
        benefits = """• 🥬 Хлорофилл для связывания токсинов
• 🥝 Витамин C для синтеза глутатиона
• 🥑 Глутатион для детоксикации печени
• 🌱 Клетчатка для очищения кишечника"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ДЕТОКС-ЗАВТРАК: ЗЕЛЕНЫЙ СМУЗИ БОУЛ",
            content, "veggie_breakfast", benefits
        )

    def generate_cleanse_smoothie(self):
        """Очищающий смузи для пищеварения"""
        content = """
💚 ОЧИЩАЮЩИЙ СМУЗИ: СЕЛЬДЕРЕЙ И ЯБЛОКО
КБЖУ: 280 ккал • Белки: 8г • Жиры: 10г • Углеводы: 42г

Ингредиенты на 2 порции:
• Сельдерей - 4 стебля (натрий для электролитов)
• Яблоко - 2 шт (пектин для детокса)
• Огурец - 1 шт (кремний для соединительной ткани)
• Лимон - 1/2 шт (лимонен для печени)
• Мята - 10 листьев (ментол для пищеварения)
• Вода - 400 мл

Приготовление (5 минут):
1. Яблоко и огурец нарезать
2. Все ингредиенты взбить в блендере
3. Процедить при желании
4. Подавать охлажденным

🎯 НАУЧНЫЙ ПОДХОД:
Пектин из яблок образует гель в кишечнике, который связывает токсины, тяжелые металлы и избыток холестерина, способствуя их выведению.
"""
        benefits = """• 🥬 Натрий для электролитного баланса
• 🍎 Пектин для связывания токсинов
• 🥒 Кремний для здоровья соединительной ткани
• 🍋 Лимонен для стимуляции детокс-ферментов"""
        
        return self.visual_manager.generate_attractive_post(
            "💚 ОЧИЩАЮЩИЙ СМУЗИ: СЕЛЬДЕРЕЙ И ЯБЛОКО",
            content, "veggie_breakfast", benefits
        )

    def generate_fiber_omelette(self):
        """Омлет с высоким содержанием клетчатки"""
        content = """
🥦 КЛЕТЧАТОЧНЫЙ ОМЛЕТ: С БРОККОЛИ И ГРИБАМИ
КБЖУ: 350 ккал • Белки: 28г • Жиры: 22г • Углеводы: 12г

Ингредиенты на 2 порции:
• Яйца - 4 шт (белок для сытости)
• Брокколи - 200 г (сульфорафан для детокса)
• Шампиньоны - 150 г (бета-глюканы для иммунитета)
• Лук - 1/2 шт (инулин для микробиома)
• Шпинат - 100 г (магний для расслабления)
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Овощи нарезать, обжарить 5 минут
2. Залить взбитыми яйцами
3. Готовить под крышкой 10-12 минут
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Инулин из лука и других овощей является пребиотиком - пищей для полезных бактерий кишечника, способствуя росту бифидобактерий и производству короткоцепочечных жирных кислот.
"""
        benefits = """• 🥚 Белок для длительной сытости
• 🥦 Сульфорафан для активации детокс-ферментов
• 🍄 Бета-глюканы для иммунной модуляции
• 🧅 Инулин для питания полезной микробиоты"""
        
        return self.visual_manager.generate_attractive_post(
            "🥦 КЛЕТЧАТОЧНЫЙ ОМЛЕТ: С БРОККОЛИ И ГРИБАМИ",
            content, "veggie_breakfast", benefits
        )

    def generate_green_pancakes(self):
        """Зеленые блинчики с овощами"""
        content = """
🥬 ЗЕЛЕНЫЕ БЛИНЧИКИ: СО ШПИНАТОМ И КАБАЧКОМ
КБЖУ: 320 ккал • Белки: 18г • Жиры: 14г • Углеводы: 35г

Ингредиенты на 2 порции:
• Цельнозерновая мука - 100 г (клетчатка)
• Шпинат - 150 г (железо для энергии)
• Кабачок - 1 шт (калий для баланса)
• Яйца - 2 шт (холин для печени)
• Разрыхлитель - 1 ч.л.
• Оливковое масло - 1 ст.л.

Приготовление (25 минут):
1. Шпинат и кабачок измельчить в блендере
2. Смешать с мукой, яйцами и разрыхлителем
3. Жарить на антипригарной сковороде
4. Подавать с авокадо или хумусом

🎯 НАУЧНЫЙ ПОДХОД:
Калий из кабачков помогает поддерживать кислотно-щелочной баланс и противодействует закисляющему эффекту современного рациона, способствуя детоксикации на клеточном уровне.
"""
        benefits = """• 🌾 Цельные зерна для пищеварения
• 🥬 Железо для оксигенации тканей
• 🥒 Калий для кислотно-щелочного баланса
• 🥚 Холин для метаболизма в печени"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ЗЕЛЕНЫЕ БЛИНЧИКИ: СО ШПИНАТОМ И КАБАЧКОМ",
            content, "veggie_breakfast", benefits
        )

    def generate_alkaline_bowl(self):
        """Щелочная чаша для баланса pH"""
        content = """
⚖️ ЩЕЛОЧНАЯ ЧАША: С КИНОА И ОВОЩАМИ
КБЖУ: 340 ккал • Белки: 16г • Жиры: 12г • Углеводы: 45г

Ингредиенты на 2 порции:
• Киноа - 100 г (белок с щелочным эффектом)
• Авокадо - 1 шт (полезные жиры)
• Огурец - 1 шт (вода и минералы)
• Ростки брокколи - 50 г (сульфорафан)
• Лимонный сок - 2 ст.л. (цитраты)
• Тыквенные семечки - 2 ст.л. (цинк)

Приготовление (15 минут):
1. Киноа отварить 15 минут
2. Овощи нарезать кубиками
3. Смешать все ингредиенты
4. Заправить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Щелочные продукты (овощи, фрукты) помогают компенсировать кислотную нагрузку от животного белка и зерновых, снижая риск остеопороза и поддерживая оптимальный pH крови.
"""
        benefits = """• 🌾 Щелочной белок для баланса pH
• 🥑 Полезные жиры для усвоения витаминов
• 🥒 Гидратация и минералы
• 🌱 Сульфорафан для активации детокса"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ЩЕЛОЧНАЯ ЧАША: С КИНОА И ОВОЩАМИ",
            content, "veggie_breakfast", benefits
        )

    def generate_detox_toast(self):
        """Детокс-тосты с овощными спредами"""
        content = """
🍞 ДЕТОКС-ТОСТЫ: С АВОКАДО И РЕДИСОМ
КБЖУ: 300 ккал • Белки: 12г • Жиры: 18г • Углеводы: 25г

Ингредиенты на 2 порции:
• Хлеб из пророщенных зерен - 4 ломтика (ферменты)
• Авокадо - 1 шт (глутатион)
• Редис - 8 шт (сернистые соединения)
• Огурец - 1/2 шт (кремний)
• Листья салата - 4 шт (хлорофилл)
• Лимонный сок - 1 ст.л.

Приготовление (10 минут):
1. Хлеб поджарить
2. Авокадо размять с лимонным соком
3. Овощи нарезать тонкими ломтиками
4. Собрать тосты слоями

🎯 НАУЧНЫЙ ПОДХОД:
Сернистые соединения из редиса и других крестоцветных овощей поддерживают работу системы детоксикации печени, особенно фазу II конъюгации.
"""
        benefits = """• 🌾 Ферменты из пророщенных зерен
• 🥑 Глутатион для детоксикации печени
• 🌶️ Сернистые соединения для конъюгации
• 🥒 Кремний для соединительной ткани"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 ДЕТОКС-ТОСТЫ: С АВОКАДО И РЕДИСОМ",
            content, "veggie_breakfast", benefits
        )

    def generate_veggie_scramble(self):
        """Овощной скрэмбл для легкого начала дня"""
        content = """
🥗 ОВОЩНОЙ СКРЭМБЛ: С ТОФУ И ОВОЩАМИ
КБЖУ: 320 ккал • Белки: 25г • Жиры: 18г • Углеводы: 15г

Ингредиенты на 2 порции:
• Тофу - 300 г (растительный белок)
• Болгарский перец - 1 шт (витамин C)
• Цукини - 1 шт (калий)
• Лук - 1/2 шт (кверцетин)
• Куркума - 1 ч.л. (куркумин)
• Оливковое масло - 1 ст.л.

Приготовление (20 минут):
1. Тофу размять вилкой
2. Овощи нарезать кубиками
3. Обжарить овощи 5 минут
4. Добавить тофу и куркуму, готовить 10 минут

🎯 НАУЧНЫЙ ПОДХОД:
Растительные белки, такие как соевый белок из тофу, создают меньшую кислотную нагрузку на организм по сравнению с животными белками, способствуя поддержанию щелочного баланса.
"""
        benefits = """• 🧈 Растительный белок с низкой кислотной нагрузкой
• 🌶️ Витамин C для синтеза коллагена
• 🥒 Калий для электролитного баланса
• 🟤 Куркумин для противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "🥗 ОВОЩНОЙ СКРЭМБЛ: С ТОФУ И ОВОЩАМИ",
            content, "veggie_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_detox_lunch(self):
        """Обед для глубокого очищения"""
        content = """
🌱 ДЕТОКС-ОБЕД: СУП ИЗ КАПУСТЫ И СЕЛЬДЕРЕЯ
КБЖУ: 280 ккал • Белки: 12г • Жиры: 8г • Углеводы: 42г

Ингредиенты на 2 порции:
• Капуста белокочанная - 300 г (глюкозинолаты)
• Сельдерей - 4 стебля (фталиды)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Чеснок - 3 зубчика (аллицин)
• Овощной бульон - 1 л

Приготовление (35 минут):
1. Овощи нарезать
2. Варить в бульоне 25-30 минут
3. Добавить специи по вкусу
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Глюкозинолаты из капусты преобразуются в изотиоцианаты (например, сульфорафан), которые активируют Nrf2-путь - главный регулятор антиоксидантной и детокс-защиты клеток.
"""
        benefits = """• 🥬 Глюкозинолаты для активации Nrf2-пути
• 🥬 Фталиды для снижения артериального давления
• 🥕 Бета-каротин для антиоксидантной защиты
• 🧄 Аллицин для антимикробного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 ДЕТОКС-ОБЕД: СУП ИЗ КАПУСТЫ И СЕЛЬДЕРЕЯ",
            content, "veggie_lunch", benefits
        )

    def generate_cleanse_bowl(self):
        """Очищающая чаша с сырыми овощами"""
        content = """
💫 ОЧИЩАЮЩАЯ ЧАША: СЫРЫЕ ОВОЩИ С ХУМУСОМ
КБЖУ: 350 ккал • Белки: 15г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 2 порции:
• Морковь - 2 шт (бета-каротин)
• Огурец - 1 шт (кремний)
• Болгарский перец - 1 шт (витамин C)
• Брокколи - 150 г (сульфорафан)
• Нут - 150 г (растительный белок)
• Тахини - 2 ст.л. (кальций)

Приготовление (15 минут):
1. Овощи нарезать соломкой
2. Нут отварить или использовать консервированный
3. Приготовить соус из тахини и лимонного сока
4. Подавать овощи с хумусом и соусом

🎯 НАУЧНЫЙ ПОДХОД:
Сырые овощи содержат живые ферменты (амилазы, протеазы, липазы), которые помогают пищеварению и сохраняют термочувствительные витамины, такие как витамин C и некоторые витамины группы B.
"""
        benefits = """• 🥕 Живые ферменты для пищеварения
• 🥒 Кремний для здоровья соединительной ткани
• 🌶️ Витамин C для синтеза коллагена
• 🥦 Сульфорафан для активации детокса"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 ОЧИЩАЮЩАЯ ЧАША: СЫРЫЕ ОВОЩИ С ХУМУСОМ",
            content, "veggie_lunch", benefits
        )

    def generate_fiber_salad(self):
        """Салат с высоким содержанием клетчатки"""
        content = """
🥗 КЛЕТЧАТОЧНЫЙ САЛАТ: С АРТИШОКАМИ И СПАРЖЕЙ
КБЖУ: 320 ккал • Белки: 18г • Жиры: 20г • Углеводы: 25г

Ингредиенты на 2 порции:
• Артишоки консервированные - 200 г (инулин)
• Спаржа - 150 г (аспарагин)
• Руккола - 100 г (нитраты)
• Авокадо - 1/2 шт (полезные жиры)
• Семена подсолнечника - 30 г (витамин E)
• Лимонный сок - 2 ст.л.

Приготовление (15 минут):
1. Спаржу бланшировать 3 минуты
2. Артишоки нарезать
3. Смешать все ингредиенты
4. Заправить лимонным соком

🎯 НАУЧНЫЙ ПОДХОД:
Инулин из артишоков является пребиотиком, который избирательно стимулирует рост бифидобактерий и лактобацилл, производящих короткоцепочечные жирные кислоты (бутират, ацетат, пропионат).
"""
        benefits = """• 🌸 Инулин для питания полезной микробиоты
• 🌱 Аспарагин для функции почек
• 🥬 Нитраты для улучшения кровотока
• 🌰 Витамин E для защиты клеточных мембран"""
        
        return self.visual_manager.generate_attractive_post(
            "🥗 КЛЕТЧАТОЧНЫЙ САЛАТ: С АРТИШОКАМИ И СПАРЖЕЙ",
            content, "veggie_lunch", benefits
        )

    def generate_green_soup(self):
        """Зеленый суп для очищения"""
        content = """
💚 ЗЕЛЕНЫЙ ДЕТОКС-СУП: ШПИНАТ И БРОККОЛИ
КБЖУ: 290 ккал • Белки: 20г • Жиры: 12г • Углеводы: 28г

Ингредиенты на 2 порции:
• Шпинат - 200 г (хлорофилл)
• Брокколи - 250 г (сульфорафан)
• Лук-порей - 1 шт (пребиотики)
• Картофель - 2 шт (калий)
• Овощной бульон - 800 мл
• Специи: мускатный орех, черный перец

Приготовление (30 минут):
1. Овощи нарезать
2. Варить в бульоне 20 минут
3. Взбить блендером до кремообразной консистенции
4. Добавить специи по вкусу

🎯 НАУЧНЫЙ ПОДХОД:
Хлорофилл из зеленых листовых овощей может связываться с канцерогенами (такими как гетероциклические амины), образуя молекулярные комплексы, которые препятствуют их абсорбции в желудочно-кишечном тракте.
"""
        benefits = """• 🥬 Хлорофилл для связывания канцерогенов
• 🥦 Сульфорафан для активации детокс-ферментов
• 🧅 Пребиотики для микробиома
• 🥔 Калий для электролитного баланса"""
        
        return self.visual_manager.generate_attractive_post(
            "💚 ЗЕЛЕНЫЙ ДЕТОКС-СУП: ШПИНАТ И БРОККОЛИ",
            content, "veggie_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_detox_dinner(self):
        """Ужин для вечернего очищения"""
        content = """
🌙 ВЕЧЕРНИЙ ДЕТОКС: ТУШЕНЫЕ ОВОЩИ С ЧЕЧЕВИЦЕЙ
КБЖУ: 380 ккал • Белки: 22г • Жиры: 10г • Углеводы: 55г

Ингредиенты на 2 порции:
• Чечевица - 150 г (растительный белок)
• Баклажаны - 1 шт (насунин)
• Цукини - 1 шт (калий)
• Помидоры - 2 шт (ликопин)
• Лук - 1 шт (кверцетин)
• Оливковое масло - 1 ст.л.

Приготовление (35 минут):
1. Чечевицу отварить 20 минут
2. Овощи нарезать кубиками
3. Тушить все вместе 15 минут
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Насунин из баклажанов является мощным антиоксидантом антоцианином, который защищает липиды клеточных мембран от окислительного повреждения, особенно в мозге.
"""
        benefits = """• 🌱 Растительный белок с клетчаткой
• 🍆 Насунин для защиты клеточных мембран
• 🥒 Калий для кислотно-щелочного баланса
• 🍅 Ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 ВЕЧЕРНИЙ ДЕТОКС: ТУШЕНЫЕ ОВОЩИ С ЧЕЧЕВИЦЕЙ",
            content, "veggie_dinner", benefits
        )

    def generate_cleanse_fish(self):
        """Рыба с овощами для легкого ужина"""
        content = """
🐟 ЛЕГКАЯ РЫБА: ТРЕСКА С ОВОЩАМИ НА ПАРУ
КБЖУ: 350 ккал • Белки: 38г • Жиры: 12г • Углеводы: 18г

Ингредиенты на 2 порции:
• Треска - 400 г (белок с низким содержанием жира)
• Цветная капуста - 200 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Спаржа - 150 г (аспарагин)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г

Приготовление (25 минут):
1. Рыбу и овощи приготовить на пару 15-20 минут
2. Полить лимонным соком
3. Посыпать укропом
4. Подавать горячим

🎯 НАУЧНЫЙ ПОДХОД:
Приготовление на пару сохраняет водорастворимые витамины (C, B) и предотвращает образование продвинутых гликированных конечных продуктов (AGEs), которые могут способствовать воспалению и окислительному стрессу.
"""
        benefits = """• 🐟 Постный белок для легкого усвоения
• 🥦 Глюкозинолаты для детокса
• 🥕 Бета-каротин для антиоксидантной защиты
• 🌱 Аспарагин для функции почек"""
        
        return self.visual_manager.generate_attractive_post(
            "🐟 ЛЕГКАЯ РЫБА: ТРЕСКА С ОВОЩАМИ НА ПАРУ",
            content, "veggie_dinner", benefits
        )

    def generate_alkaline_chicken(self):
        """Щелочной ужин с курицей и овощами"""
        content = """
⚖️ ЩЕЛОЧНОЙ УЖИН: КУРИЦА С ОВОЩАМИ
КБЖУ: 400 ккал • Белки: 42г • Жиры: 18г • Углеводы: 20г

Ингредиенты на 2 порции:
• Куриная грудка - 300 г (белок)
• Брокколи - 200 г (щелочной эффект)
• Шпинат - 150 г (магний)
• Грибы - 150 г (витамин D)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

Приготовление (30 минут):
1. Курицу нарезать кубиками
2. Овощи нарезать
3. Запекать все вместе 25 минут
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация животного белка с большим количеством щелочных овощей помогает сбалансировать кислотную нагрузку рациона, снижая экскрецию кальция с мочой и поддерживая минеральную плотность костей.
"""
        benefits = """• 🍗 Белок для сытости и восстановления
• 🥦 Щелочные овощи для баланса pH
• 🥬 Магний для расслабления
• 🍄 Витамин D для усвоения кальция"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ЩЕЛОЧНОЙ УЖИН: КУРИЦА С ОВОЩАМИ",
            content, "veggie_dinner", benefits
        )

    def generate_veggie_stew(self):
        """Овощное рагу для комфортного ужина"""
        content = """
🍲 ОВОЩНОЕ РАГУ: С КАРТОФЕЛЕМ И КАПУСТОЙ
КБЖУ: 320 ккал • Белки: 15г • Жиры: 8г • Углеводы: 52г

Ингредиенты на 2 порции:
• Картофель - 400 г (резистентный крахмал)
• Капуста белокочанная - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Сельдерей - 2 стебля (фталиды)
• Томатная паста - 2 ст.л.

Приготовление (40 минут):
1. Овощи нарезать кубиками
2. Тушить на медленном огне 30-35 минут
3. Добавить томатную пасту в конце
4. Подавать с зеленью

🎯 НАУЧНЫЙ ПОДХОД:
Приготовленный и охлажденный картофель образует резистентный крахмал, который ферментируется в толстом кишечнике с образованием бутирата - короткоцепочечной жирной кислоты, обладающей противовоспалительными свойствами и поддерживающей здоровье слизистой кишечника.
"""
        benefits = """• 🥔 Резистентный крахмал для продукции бутирата
• 🥬 Глюкозинолаты для активации детокса
• 🥕 Бета-каротин для антиоксидантной защиты
• 🥬 Фталиды для снижения давления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 ОВОЩНОЕ РАГУ: С КАРТОФЕЛЕМ И КАПУСТОЙ",
            content, "veggie_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_detox_dessert(self):
        """Детокс-десерт для сладкоежек"""
        content = """
🍏 ДЕТОКС-ДЕСЕРТ: ЯБЛОЧНЫЙ КРАМБЛ БЕЗ САХАРА
КБЖУ: 240 ккал • Белки: 8г • Жиры: 12г • Углеводы: 28г

Ингредиенты на 2 порции:
• Яблоки - 4 шт (пектин)
• Овсяные хлопья - 60 г (бета-глюканы)
• Грецкие орехи - 40 г (Омега-3)
• Корица - 2 ч.л. (полифенолы)
• Кокосовое масло - 2 ст.л. (МСТ)
• Стевия - по вкусу

Приготовление (30 минут):
1. Яблоки нарезать, смешать с корицей
2. Для крошки: овсянка + орехи + масло + стевия
3. Выложить в форму, запекать 25 минут
4. Подавать теплым

🎯 НАУЧНЫЙ ПОДХОД:
Полифенолы корицы улучшают чувствительность к инсулину и могут снижать уровень глюкозы в крови натощак на 10-15%, что особенно важно при метаболическом синдроме.
"""
        benefits = """• 🍎 Пектин для связывания токсинов
• 🌾 Бета-глюканы для контроля холестерина
• 🌰 Омега-3 для противовоспалительного эффекта
• 🟤 Полифенолы для улучшения чувствительности к инсулину"""
        
        return self.visual_manager.generate_attractive_post(
            "🍏 ДЕТОКС-ДЕСЕРТ: ЯБЛОЧНЫЙ КРАМБЛ БЕЗ САХАРА",
            content, "veggie_dessert", benefits
        )

    def generate_cleanse_treat(self):
        """Очищающее лакомство"""
        content = """
💚 ОЧИЩАЮЩЕЕ ЛАКОМСТВО: ФИНИКОВЫЕ ШАРИКИ
КБЖУ: 220 ккал • Белки: 6г • Жиры: 10г • Углеводы: 30г

Ингредиенты на 8 шариков:
• Финики - 200 г (натуральная сладость)
• Семена льна - 50 г (клетчатка)
• Кокосовая стружка - 50 г (МСТ)
• Какао-порошок - 2 ст.л. (флавоноиды)
• Имбирь молотый - 1 ч.л. (гингерол)
• Корица - 1 ч.л.

Приготовление (15 минут + охлаждение):
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Охладить 1 час

🎯 НАУЧНЫЙ ПОДХОД:
Слизистые волокна семян льна образуют гель в кишечнике, который замедляет опорожнение желудка, улучшает контроль уровня сахара в крови и связывает желчные кислоты, способствуя выведению холестерина.
"""
        benefits = """• 🫒 Натуральные сахара без рафинированных продуктов
• 🌱 Слизистые волокна для здоровья ЖКТ
• 🥥 МСТ для альтернативного энергоснабжения
• 🍫 Флавоноиды для улучшения кровотока"""
        
        return self.visual_manager.generate_attractive_post(
            "💚 ОЧИЩАЮЩЕЕ ЛАКОМСТВО: ФИНИКОВЫЕ ШАРИКИ",
            content, "veggie_dessert", benefits
        )

# Создание экземпляра генератора
wednesday_generator = WednesdayContentGenerator()
class ThursdayContentGenerator:
    """Генератор контента для четверга - углеводы и энергия"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_energy_breakfast(self):
        """Энергетический завтрак с углеводами"""
        content = """
⚡ ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С БАНАНОМ И МЕДОМ
КБЖУ: 420 ккал • Белки: 18г • Жиры: 12г • Углеводы: 68г

Ингредиенты на 2 порции:
• Овсяные хлопья - 100 г (сложные углеводы)
• Банан - 2 шт (быстрые углеводы + калий)
• Мед - 2 ст.л. (глюкоза для мозга)
• Грецкие орехи - 30 г (Омега-3)
• Корица - 1 ч.л. (регуляция сахара)
• Молоко - 400 мл (белок)

Приготовление (10 минут):
1. Овсянку варить с молоком 7 минут
2. Банан нарезать кружочками
3. Добавить мед, орехи и корицу
4. Подавать горячим

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация сложных (овсянка) и простых (банан, мед) углеводов обеспечивает как немедленное, так и продолжительное высвобождение энергии, идеальное для начала активного дня.
"""
        benefits = """• 🌾 Сложные углеводы для продолжительной энергии
• 🍌 Быстрые углеводы для немедленного топлива
• 🍯 Глюкоза для мозговой активности
• 🌰 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С БАНАНОМ И МЕДОМ",
            content, "carbs_breakfast", benefits
        )

    def generate_fuel_smoothie(self):
        """Топливный смузи для энергии"""
        content = """
⛽️ ТОПЛИВНЫЙ СМУЗИ: ОВСЯНКА, БАНАН, ФИНИКИ
КБЖУ: 380 ккал • Белки: 15г • Жиры: 8г • Углеводы: 65г

Ингредиенты на 2 порции:
• Овсяные хлопья - 60 г (бета-глюканы)
• Банан - 2 шт (калий)
• Финики - 4 шт (натуральные сахара)
• Миндальное молоко - 400 мл
• Семена чиа - 2 ст.л. (Омега-3)
• Ванильный экстракт - 1 ч.л.

Приготовление (5 минут):
1. Овсянку измельчить в блендере
2. Добавить остальные ингредиенты
3. Взбивать до однородности
4. Подавать сразу

🎯 НАУЧНЫЙ ПОДХОД:
Бета-глюканы из овсянки образуют вязкий гель в кишечнике, который замедляет усвоение углеводов и обеспечивает стабильный уровень энергии без резких скачков сахара.
"""
        benefits = """• 🌾 Бета-глюканы для контроля гликемического ответа
• 🍌 Калий для нервно-мышечной функции
• 🫒 Натуральные сахара для быстрой энергии
• 🌱 Омега-3 для баланса воспалительных процессов"""
        
        return self.visual_manager.generate_attractive_post(
            "⛽️ ТОПЛИВНЫЙ СМУЗИ: ОВСЯНКА, БАНАН, ФИНИКИ",
            content, "carbs_breakfast", benefits
        )

    def generate_glycogen_pancakes(self):
        """Блинчики для пополнения гликогена"""
        content = """
🥞 ГЛИКОГЕНОВЫЕ БЛИНЧИКИ: ЦЕЛЬНОЗЕРНОВЫЕ С ЯГОДАМИ
КБЖУ: 350 ккал • Белки: 16г • Жиры: 10г • Углеводы: 52г

Ингредиенты на 2 порции:
• Цельнозерновая мука - 120 г (медленные углеводы)
• Яйца - 2 шт (белок)
• Молоко - 200 мл (кальций)
• Ягоды - 150 г (антиоксиданты)
• Кленовый сироп - 2 ст.л. (натуральный подсластитель)
• Разрыхлитель - 1 ч.л.

Приготовление (20 минут):
1. Смешать муку, яйца, молоко, разрыхлитель
2. Жарить на антипригарной сковороде
3. Подавать с ягодами и сиропом
4. Украсить мятой

🎯 НАУЧНЫЙ ПОДХОД:
Цельнозерновая мука сохраняет зародыш и оболочку зерна, содержащие витамины группы B, необходимые для преобразования углеводов в энергию через цикл Кребса.
"""
        benefits = """• 🌾 Цельные зерна для стабильной энергии
• 🥚 Белок для баланса макронутриентов
• 🥛 Кальций для нервной проводимости
• 🍓 Антиоксиданты для защиты от окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 ГЛИКОГЕНОВЫЕ БЛИНЧИКИ: ЦЕЛЬНОЗЕРНОВЫЕ С ЯГОДАМИ",
            content, "carbs_breakfast", benefits
        )

    def generate_carbs_omelette(self):
        """Омлет с углеводным компонентом"""
        content = """
🍠 УГЛЕВОДНЫЙ ОМЛЕТ: С БАТАТОМ И ШПИНАТОМ
КБЖУ: 390 ккал • Белки: 25г • Жиры: 18г • Углеводы: 35г

Ингредиенты на 2 порции:
• Яйца - 4 шт (белок)
• Батат - 200 г (сложные углеводы)
• Шпинат - 100 г (железо)
• Лук - 1/2 шт (кверцетин)
• Оливковое масло - 1 ст.л.
• Специи по вкусу

Приготовление (25 минут):
1. Батат нарезать кубиками, запечь 15 минут
2. Лук обжарить, добавить шпинат
3. Залить взбитыми яйцами
4. Готовить 8-10 минут

🎯 НАУЧНЫЙ ПОДХОД:
Батат содержит сложные углеводы с низким гликемическим индексом (54) и богат бета-каротином, который преобразуется в витамин A, необходимый для зрения и иммунной функции.
"""
        benefits = """• 🥚 Высококачественный белок
• 🍠 Сложные углеводы с низким ГИ
• 🥬 Железо для транспорта кислорода
• 🧅 Кверцетин для противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 УГЛЕВОДНЫЙ ОМЛЕТ: С БАТАТОМ И ШПИНАТОМ",
            content, "carbs_breakfast", benefits
        )

    def generate_energy_bowl_breakfast(self):
        """Энергетическая чаша с киноа и ягодами"""
        content = """
💫 ЭНЕРГЕТИЧЕСКАЯ ЧАША С КИНОА И ЯГОДАМИ
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

Ингредиенты на 2 порции:
• Киноа - 100 г (полноценный белок + углеводы)
• Черника - 100 г (антоцианы)
• Малина - 100 г (эллагиновая кислота)
• Миндаль - 30 г (витамин E)
• Кленовый сироп - 1 ст.л.
• Кокосовая стружка - 2 ст.л.

Приготовление (20 минут):
1. Киноа отварить 15 минут
2. Ягоды промыть
3. Смешать все ингредиенты
4. Заправить сиропом

🎯 НАУЧНЫЙ ПОДХОД:
Киноа содержит все 9 незаменимых аминокислот, что делает ее уникальным источником растительного белка, одновременно обеспечивая качественные углеводы для энергии.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🫐 Антоцианы для когнитивных функций
• 🍓 Эллагиновая кислота против воспаления
• 🌰 Витамин E для защиты клеточных мембран"""
        
        return self.visual_manager.generate_attractive_post(
            "💫 ЭНЕРГЕТИЧЕСКАЯ ЧАША С КИНОА И ЯГОДАМИ",
            content, "carbs_breakfast", benefits
        )

    def generate_carbs_pancakes(self):
        """Углеводные блинчики из цельнозерновой муки"""
        content = """
🥞 УГЛЕВОДНЫЕ БЛИНЫ ИЗ ЦЕЛЬНОЙ МУКИ
КБЖУ: 360 ккал • Белки: 16г • Жиры: 10г • Углеводы: 55г

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
Цельнозерновая мука сохраняет зародыш и оболочку зерна, содержащие витамины группы B, необходимые для энергетического обмена и преобразования углеводов в АТФ.
"""
        benefits = """• 🌾 Витамины группы B для энергетического метаболизма
• 🥚 Белок для сбалансированного питания
• 🥛 Кальций для костей и нервной системы
• 🍌 Натуральные сахара для быстрой энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 УГЛЕВОДНЫЕ БЛИНЫ ИЗ ЦЕЛЬНОЙ МУКИ",
            content, "carbs_breakfast", benefits
        )

    def generate_quick_energy_toast(self):
        """Быстрые тосты для энергии"""
        content = """
🍞 БЫСТРЫЕ ЭНЕРГЕТИЧЕСКИЕ ТОСТЫ
КБЖУ: 320 ккал • Белки: 15г • Жиры: 12г • Углеводы: 42г

Ингредиенты на 2 порции:
• Хлеб цельнозерновой - 4 ломтика (сложные углеводы)
• Арахисовая паста - 4 ст.л. (белок + жиры)
• Банан - 1 шт (быстрые углеводы)
• Мед - 1 ст.л. (глюкоза)
• Семена чиа - 1 ст.л. (Омега-3)
• Корица - 1 ч.л.

Приготовление (5 минут):
1. Хлеб поджарить
2. Намазать арахисовую пасту
3. Выложить ломтики банана
4. Полить медом, посыпать семенами и корицей

🎯 НАУЧНЫЙ ПОДХОД:
Комбинация сложных углеводов (хлеб), быстрых углеводов (банан, мед) и полезных жиров (арахисовая паста) создает идеальный баланс для стабильного высвобождения энергии в течение нескольких часов.
"""
        benefits = """• 🍞 Сложные углеводы для продолжительной энергии
• 🥜 Белок и жиры для сытости
• 🍌 Быстрые углеводы для немедленного топлива
• 🌱 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 БЫСТРЫЕ ЭНЕРГЕТИЧЕСКИЕ ТОСТЫ",
            content, "carbs_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_glycogen_replenishment(self):
        """Обед для восстановления гликогена"""
        content = """
🔄 ОБЕД ДЛЯ ВОССТАНОВЛЕНИЯ ГЛИКОГЕНА
КБЖУ: 520 ккал • Белки: 28г • Жиры: 18г • Углеводы: 72г

Ингредиенты на 2 порции:
• Бурый рис - 200 г (сложные углеводы + магний)
• Куриная грудка - 250 г (белок)
• Брокколи - 200 г (клетчатка)
• Морковь - 2 шт (бета-каротин)
• Кунжутное масло - 1 ст.л.
• Соевый соус - 2 ст.л.

Приготовление (30 минут):
1. Бурый рис отварить 25 минут
2. Курицу запечь 20 минут
3. Овощи приготовить на пару
4. Смешать все компоненты

🎯 НАУЧНЫЙ ПОДХОД:
Бурый рис сохраняет отрубную оболочку, богатую магнием - кофактором для более чем 300 ферментативных реакций, включая те, что участвуют в производстве энергии из углеводов.
"""
        benefits = """• 🍚 Магний для энергетического метаболизма
• 🍗 Белок для мышечного восстановления
• 🥦 Клетчатка для здоровья ЖКТ
• 🥕 Бета-каротин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ОБЕД ДЛЯ ВОССТАНОВЛЕНИЯ ГЛИКОГЕНА",
            content, "carbs_lunch", benefits
        )

    def generate_energy_bowl_lunch(self):
        """Энергетическая чаша с булгуром"""
        content = """
💥 ЭНЕРГЕТИЧЕСКАЯ ЧАША С БУЛГУРОМ И ОВОЩАМИ
КБЖУ: 480 ккал • Белки: 22г • Жиры: 20г • Углеводы: 60г

Ингредиенты на 2 порции:
• Булгур - 150 г (быстрое приготовление)
• Нут - 150 г (растительный белок)
• Огурцы - 2 шт (гидратация)
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
Булгур имеет низкий гликемический индекс (48) и высокое содержание клетчатки, обеспечивая медленное высвобождение энергии и длительное чувство сытости.
"""
        benefits = """• 🌾 Низкий ГИ для стабильного уровня энергии
• 🫘 Растительный белок для синтеза
• 🥒 Гидратация для общего здоровья
• 🍅 Ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💥 ЭНЕРГЕТИЧЕСКАЯ ЧАША С БУЛГУРОМ И ОВОЩАМИ",
            content, "carbs_lunch", benefits
        )

    def generate_carbs_balance_meal(self):
        """Сбалансированный обед с углеводами"""
        content = """
⚖️ СБАЛАНСИРОВАННЫЙ ОБЕД С УГЛЕВОДАМИ И БЕЛКОМ
КБЖУ: 500 ккал • Белки: 32г • Жиры: 20г • Углеводы: 55г

Ингредиенты на 2 порции:
• Картофель - 400 г (калий + резистентный крахмал)
• Лосось - 250 г (Омега-3 + белок)
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
Картофель, приготовленный и охлажденный, образует резистентный крахмал, который служит пребиотиком для микробиома и производит короткоцепочечные жирные кислоты, улучшающие чувствительность к инсулину.
"""
        benefits = """• 🥔 Резистентный крахмал для здоровья кишечника
• 🐟 Омега-3 для противовоспалительного действия
• 🌱 Фолат для синтеза ДНК
• 🍋 Витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ОБЕД С УГЛЕВОДАМИ И БЕЛКОМ",
            content, "carbs_lunch", benefits
        )

    def generate_pasta_power(self):
        """Энергетическая паста с овощами"""
        content = """
🍝 ЭНЕРГЕТИЧЕСКАЯ ПАСТА С ОВОЩАМИ И СЫРОМ
КБЖУ: 520 ккал • Белки: 25г • Жиры: 18г • Углеводы: 70г

Ингредиенты на 2 порции:
• Цельнозерновая паста - 180 г (медленные углеводы)
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
Сложные углеводы из цельнозерновой пасты обеспечивают медленное высвобождение энергии, поддерживая стабильный уровень глюкозы в крови и предотвращая энергетические спады.
"""
        benefits = """• 🍝 Медленные углеводы для продолжительной энергии
• 🥒 Калий для нервной системы
• 🌶️ Витамин C для иммунитета
• 🧀 Кальций для костей и зубов"""
        
        return self.visual_manager.generate_attractive_post(
            "🍝 ЭНЕРГЕТИЧЕСКАЯ ПАСТА С ОВОЩАМИ И СЫРОМ",
            content, "carbs_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_slow_carbs_dinner(self):
        """Ужин с медленными углеводами"""
        content = """
🌙 УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦА С ОВОЩАМИ
КБЖУ: 420 ккал • Белки: 25г • Жиры: 14г • Углеводы: 55г

Ингредиенты на 2 порции:
• Чечевица - 150 г (растительный белок + клетчатка)
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
Чечевица содержит медленно усваиваемые углеводы и резистентный крахмал, поддерживающий стабильный уровень сахара в крови и обеспечивающий продолжительное чувство сытости.
"""
        benefits = """• 🌱 Медленные углеводы + растительный белок
• 🥒 Калий для водного баланса
• 🍆 Насунин для клеточных мембран
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦА С ОВОЩАМИ",
            content, "carbs_dinner", benefits
        )

    def generate_energy_reserve_meal(self):
        """Ужин для создания энергетического резерва"""
        content = """
🔋 УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА
КБЖУ: 450 ккал • Белки: 20г • Жиры: 16г • Углеводы: 60г

Ингредиенты на 2 порции:
• Киноа - 120 г (полноценный белок)
• Тыква - 300 г (бета-каротин)
• Шпинат - 100 г (железо)
• Семена тыквы - 2 ст.л. (цинк)
• Кокосовое молоко - 100 мл (МСТ)
• Куркума - 1 ч.л.

Приготовление (25 минут):
1. Киноа отварить
2. Тыкву запечь 20 минут
3. Шпинат обжарить 2 минуты
4. Смешать все ингредиенты

🎯 НАУЧНЫЙ ПОДХОД:
Среднецепочечные триглицериды (МСТ) из кокосового молока быстро метаболизируются в печени, производя кетоновые тела - эффективный источник энергии для мозга и мышц.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🎃 Бета-каротин для иммунитета
• 🥬 Железо для энергии
• 🥥 МСТ для альтернативного энергоснабжения"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА",
            content, "carbs_dinner", benefits
        )

    def generate_evening_carbs(self):
        """Вечерние углеводы для качественного сна"""
        content = """
😴 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

Ингредиенты на 2 порции:
• Батат - 400 г (сложные углеводы)
• Творог - 150 г (триптофан)
• Банан - 1 шт (мелатонин)
• Корица - 1 ч.л.
• Мед - 1 ст.л.
• Грецкие орехи - 30 г

Приготовление (20 минут):
1. Батат запечь 18 минут
2. Размять вилкой
3. Смешать с творогом и бананом
4. Заправить медом и корицей, посыпать орехами

🎯 НАУЧНЫЙ ПОДХОД:
Углеводы вечером способствуют транспорту триптофана через гематоэнцефалический барьер, улучшая синтез серотонина и мелатонина - гормонов, регулирующих сон.
"""
        benefits = """• 🍠 Сложные углеводы для сытости
• 🧀 Триптофан для серотонина
• 🍌 Мелатонин для сна
• 🌰 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА",
            content, "carbs_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_energy_dessert(self):
        """Энергетический десерт"""
        content = """
🍰 ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА
КБЖУ: 280 ккал • Белки: 12г • Жиры: 14г • Углеводы: 32г

Ингредиенты на 2 порции:
• Бананы - 2 шт (натуральная сладость)
• Семена чиа - 4 ст.л. (Омега-3 + клетчатка)
• Миндальное молоко - 300 мл
• Ванильный экстракт - 1 ч.л.
• Корица - 1 ч.л.
• Грецкие орехи - 30 г

Приготовление (5 минут + настаивание):
1. Бананы размять вилкой
2. Смешать с семенами чиа и молоком
3. Добавить ваниль и корицу
4. Настаивать 4 часа или overnight, посыпать орехами

🎯 НАУЧНЫЙ ПОДХОД:
Семена чиа образуют гель при контакте с жидкостью, что замедляет переваривание углеводов и обеспечивает постепенное высвобождение энергии, предотвращая резкие скачки сахара.
"""
        benefits = """• 🍌 Натуральные сахара для энергии
• 🌱 Омега-3 для противовоспалительного действия
• 🌾 Клетчатка для контроля гликемического ответа
• 🌰 Полифенолы для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА",
            content, "carbs_dessert", benefits
        )

    def generate_carbs_treat(self):
        """Углеводное лакомство"""
        content = """
🎯 УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

Ингредиенты на 8 трюфелей:
• Финики - 200 г (натуральные сахара)
• Овсяные хлопья - 80 г (сложные углеводы)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Арахисовая паста - 2 ст.л. (белок)
• Кокосовая стружка - для обваливания

Приготовление (15 минут + охлаждение):
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке, охладить

🎯 НАУЧНЫЙ ПОДХОД:
Финики содержат натуральные сахара (фруктозу и глюкозу) в сочетании с клетчаткой, что обеспечивает более медленное высвобождение энергии по сравнению с рафинированным сахаром.
"""
        benefits = """• 🫒 Натуральные сахара с клетчаткой
• 🌾 Сложные углеводы для продолжительной энергии
• 🍫 Флавоноиды для улучшения кровотока
• 🥜 Белок для баланса макронутриентов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "carbs_dessert", benefits
        )

# Создание экземпляра генератора
thursday_generator = ThursdayContentGenerator()
class FridayContentGenerator:
    """Генератор контента для пятницы - баланс, удовольствие и разнообразие"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_fun_breakfast(self):
        """Веселый завтрак для хорошего настроения"""
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
        """Сбалансированный завтрак 80/20"""
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
Принцип 80/20 позволяет сохранить психологический комфорт while maintaining nutritional quality, снижая риск срывов и формируя устойчивые пищевые привычки.
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
        """Завтрак для хорошего настроения"""
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
Триптофан из творога является предшественником серотонина - "гормона счастья", улучшающего настроение и регулирующего эмоциональное состояние.
"""
        benefits = """• 🧀 Триптофан для серотонина
• 🍌 Дофаминовые прекурсоры
• 🌰 Омега-3 для мозга
• 🍓 Фолат для нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "😊 ЗАВТРАК ДЛЯ ХОРОШЕГО НАСТРОЕНИЯ",
            content, "energy_breakfast", benefits
        )

    def generate_friday_pancakes(self):
        """Пятничные панкейки с карамелизированными бананами"""
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
Умеренное количество натуральных сахаров из фруктов и сиропа обеспечивает удовольствие без резких скачков глюкозы, поддерживая стабильное настроение.
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
        """Праздничный тост с рикоттой и фруктами"""
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
Сочетание текстур и вкусов активирует больше сенсорных рецепторов, усиливая удовольствие от еды и способствуя психологическому насыщению.
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
        """Социальный смузи для встречи с друзьями"""
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
Бромелайн из ананаса улучшает пищеварение и обладает противовоспалительными свойствами, полезными после вечеринок и социальных мероприятий.
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
        """Чаша удовольствия с гранолой и шоколадом"""
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
Теобромин из темного шоколада мягко стимулирует нервную систему и улучшает настроение без резких скачков, характерных для кофеина.
"""
        benefits = """• 🥛 Греческий йогурт - пробиотики для микробиома
• 🌾 Гранола - цельные зерна для энергии
• 🍓 Клубника - антиоксиданты для защиты
• 🍫 Темный шоколад - теобромин для настроения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍧 ЧАША УДОВОЛЬСТВИЯ С ГРАНОЛОЙ И ШОКОЛАДОМ",
            content, "energy_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_mediterranean_feast(self):
        """Средиземноморский праздник"""
        content = """
🌊 СРЕДИЗЕМНОМОРСКИЙ ПРАЗДНИК
КБЖУ: 480 ккал • Белки: 28г • Жиры: 25г • Углеводы: 42г

Ингредиенты на 2 порции:
• Лосось - 250 г (Омега-3)
• Киноа - 120 г (полноценный белок)
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
Средиземноморская диета ассоциируется с увеличенной продолжительностью жизни и снижением риска хронических заболеваний благодаря балансу полезных жиров, антиоксидантов и клетчатки.
"""
        benefits = """• 🐟 Омега-3 для сердца и мозга
• 🌾 Полноценный растительный белок
• 🫒 Полезные жиры для сосудов
• 🧀 Кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🌊 СРЕДИЗЕМНОМОРСКИЙ ПРАЗДНИК",
            content, "energy_lunch", benefits
        )

    def generate_social_lunch(self):
        """Социальный обед с друзьями"""
        content = """
👨‍👩‍👧‍👦 СОЦИАЛЬНЫЙ ОБЕД: ПАСТА С ПЕСТО И МОРЕПРОДУКТАМИ
КБЖУ: 520 ккал • Белки: 32г • Жиры: 22г • Углеводы: 55г

Ингредиенты на 2 порции:
• Цельнозерновая паста - 180 г (клетчатка)
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
Совместные приемы пищи улучшают социальные связи и психологическое благополучие, что положительно влияет на общее здоровье и снижает уровень стресса.
"""
        benefits = """• 🍝 Цельнозерновая паста - медленные углеводы
• 🦐 Креветки - белок + селен для антиоксидантной защиты
• 🌿 Базилик - противовоспалительные свойства
• 🌰 Кедровые орехи - цинк для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍👩‍👧‍👦 СОЦИАЛЬНЫЙ ОБЕД: ПАСТА С ПЕСТО И МОРЕПРОДУКТАМИ",
            content, "energy_lunch", benefits
        )

    def generate_celebration_meal(self):
        """Праздничный обед с курицей и овощами гриль"""
        content = """
🎉 ПРАЗДНИЧНЫЙ ОБЕД С КУРИЦЕЙ И ОВОЩАМИ ГРИЛЬ
КБЖУ: 450 ккал • Белки: 38г • Жиры: 22г • Углеводы: 28г

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
Приготовление на гриле создает ароматические соединения (реакция Майяра), которые усиливают удовольствие от еды и способствуют психологическому насыщению.
"""
        benefits = """• 🍗 Курица - качественный животный белок
• 🥒 Цукини - калий для водного баланса
• 🍆 Баклажаны - антиоксиданты для клеток
• 🌶️ Перец - витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🎉 ПРАЗДНИЧНЫЙ ОБЕД С КУРИЦЕЙ И ОВОЩАМИ ГРИЛЬ",
            content, "energy_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_social_dinner(self):
        """Социальный ужин с друзьями"""
        content = """
🍷 СОЦИАЛЬНЫЙ УЖИН: СТЕЙК С ОВОЩАМИ
КБЖУ: 480 ккал • Белки: 42г • Жиры: 28г • Углеводы: 18г

Ингредиенты на 2 порции:
• Говяжий стейк - 300 г (железо)
• Спаржа - 200 г (фолат)
• Грибы - 150 г (витамин D)
• Чеснок - 3 зубчика
• Тимьян - 2 веточки
• Оливковое масло - 1 ст.л.

Приготовление (25 минут):
1. Стейк обжарить до желаемой прожарки
2. Овощи приготовить на гриле
3. Подавать с зеленью и специями

🎯 НАУЧНЫЙ ПОДХОД:
Железо из красного мяса обладает высокой биодоступностью и необходимо для производства гемоглобина, предотвращая анемию и поддерживая энергетический уровень.
"""
        benefits = """• 🥩 Гемовое железо для профилактики анемии
• 🌱 Фолат для синтеза ДНК
• 🍄 Витамин D для иммунитета
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🍷 СОЦИАЛЬНЫЙ УЖИН: СТЕЙК С ОВОЩАМИ",
            content, "energy_dinner", benefits
        )

    def generate_evening_balance(self):
        """Вечерний баланс для хорошего сна"""
        content = """
🌙 ВЕЧЕРНИЙ БАЛАНС: ЛЕГКИЙ УЖИН ДЛЯ ХОРОШЕГО СНА
КБЖУ: 350 ккал • Белки: 28г • Жиры: 20г • Углеводы: 15г

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
Триптофан из индейки и мелатонин из грецких орехов способствуют качественному сну и восстановлению, регулируя циркадные ритмы.
"""
        benefits = """• 🦃 Триптофан для серотонина
• 🥑 Полезные жиры для гормонов
• 🥬 Кальций для нервной системы
• 🌰 Мелатонин для сна"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 ВЕЧЕРНИЙ БАЛАНС: ЛЕГКИЙ УЖИН ДЛЯ ХОРОШЕГО СНА",
            content, "energy_dinner", benefits
        )

    def generate_weekend_starter(self):
        """Старт выходных - ужин для подготовки к отдыху"""
        content = """
🎯 СТАРТ ВЫХОДНЫХ: УЖИН ДЛЯ ПОДГОТОВКИ К ОТДЫХУ
КБЖУ: 380 ккал • Белки: 32г • Жиры: 22г • Углеводы: 18г

Ингредиенты на 2 порции:
• Лосось - 250 г (Омега-3)
• Киноа - 100 г (белок)
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
Омега-3 жирные кислоты из лосося обладают противовоспалительными свойствами и поддерживают здоровье мозга, способствуя психологическому расслаблению.
"""
        benefits = """• 🐟 Омега-3 для мозга и сердца
• 🌾 Полноценный растительный белок
• 🥬 Магний для расслабления
• 🍋 Витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 СТАРТ ВЫХОДНЫХ: УЖИН ДЛЯ ПОДГОТОВКИ К ОТДЫХУ",
            content, "energy_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_healthy_indulgence(self):
        """Здоровое удовольствие - шоколадный мусс из авокадо"""
        content = """
🍫 ЗДОРОВОЕ УДОВОЛЬСТВИЕ: ШОКОЛАДНЫЙ МУСС ИЗ АВОКАДО
КБЖУ: 240 ккал • Белки: 8г • Жиры: 18г • Углеводы: 18г

Ингредиенты на 2 порции:
• Авокадо - 1 шт (полезные жиры)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Мед - 2 ст.л. (натуральные сахара)
• Ванильный экстракт - 1 ч.л.
• Миндальное молоко - 50 мл
• Ягоды для подачи - 100 г

Приготовление (10 минут):
1. Авокадо очистить от кожуры
2. Все ингредиенты взбить в блендере
3. Охладить 30 минут
4. Подавать с ягодами

🎯 НАУЧНЫЙ ПОДХОД:
Флавоноиды какао улучшают кровоснабжение мозга и обладают антиоксидантными свойствами, поддерживая когнитивные функции и настроение.
"""
        benefits = """• 🥑 Мононенасыщенные жиры
• 🍫 Флавоноиды для сосудов
• 🍯 Натуральные пребиотики
• 🍓 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ЗДОРОВОЕ УДОВОЛЬСТВИЕ: ШОКОЛАДНЫЙ МУСС ИЗ АВОКАДО",
            content, "energy_dessert", benefits
        )

    def generate_guilt_free_treat(self):
        """Десерт без чувства вины - яблочный крамбл"""
        content = """
🍰 ДЕСЕРТ БЕЗ ЧУВСТВА ВИНЫ: ЯБЛОЧНЫЙ КРАМБЛ
КБЖУ: 280 ккал • Белки: 8г • Жиры: 12г • Углеводы: 38г

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
Кверцетин из яблок обладает противовоспалительными и антиоксидантными свойствами, поддерживая здоровье сосудов и снижая риск хронических заболеваний.
"""
        benefits = """• 🍎 Кверцетин против воспаления
• 🌾 Бета-глюканы для холестерина
• 🌰 Витамин E для кожи
• 🟤 Регуляция уровня сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ДЕСЕРТ БЕЗ ЧУВСТВА ВИНЫ: ЯБЛОЧНЫЙ КРАМБЛ",
            content, "energy_dessert", benefits
        )

    def generate_weekend_dessert(self):
        """Выходной десерт - тирамису без выпечки"""
        content = """
🎊 ВЫХОДНОЙ ДЕСЕРТ: ТИРАМИСУ БЕЗ ВЫПЕЧКИ
КБЖУ: 260 ккал • Белки: 12г • Жиры: 14г • Углеводы: 22г

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
Кофе содержит хлорогеновую кислоту, которая улучшает чувствительность к инсулину и обладает антиоксидантными свойствами, поддерживая метаболическое здоровье.
"""
        benefits = """• 🧀 Легкоусвояемый белок
• ☕ Антиоксиданты для защиты клеток
• 🍫 Магний для нервной системы
• 🍯 Натуральные антимикробные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🎊 ВЫХОДНОЙ ДЕСЕРТ: ТИРАМИСУ БЕЗ ВЫПЕЧКИ",
            content, "energy_dessert", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_hydration_science(self):
        """Наука гидратации для энергии"""
        content = """
💧 НАУКА ГИДРАТАЦИИ: ВОДА КАК ОСНОВА ЭНЕРГИИ

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
            content, "energy_advice", benefits
        )

    def generate_electrolyte_balance(self):
        """Электролитный баланс для энергии"""
        content = """
⚡️ ЭЛЕКТРОЛИТНЫЙ БАЛАНС: КЛЮЧ К ЭНЕРГИИ

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
            content, "energy_advice", benefits
        )

# Создание экземпляра генератора
friday_generator = FridayContentGenerator()
class SaturdayContentGenerator:
    """Генератор контента для субботы - семейная кухня и совместное приготовление"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_family_brunch(self):
        """Семейный бранч для выходного дня"""
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
            content, "family_breakfast", benefits
        )

    def generate_weekend_pancakes(self):
        """Выходные оладьи с яблочным пюре"""
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
Яблочное пюре заменяет сахар, обеспечивая натуральную сладость и полезную клетчатку для здорового пищеварения.
"""
        benefits = """• 🍎 Натуральная сладость без сахара
• 🌾 Овсяная мука для пищеварения
• 🥚 Белок для сытости
• 🌰 Омега-3 для развития мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🥞 ВЫХОДНЫЕ ОЛАДЬИ С ЯБЛОЧНЫМ ПЮРЕ",
            content, "family_breakfast", benefits
        )

    def generate_shared_breakfast(self):
        """Скрэмбл для всей семьи с овощами"""
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
Каждый член семьи участвует в процессе - от мытья овощей до сервировки, развивая командный дух и кулинарные навыки.
"""
        benefits = """• 🥚 Высококачественный белок
• 🥬 Овощи разных цветов - разные витамины
• 🧀 Кальций для костей
• 🌱 Пребиотики для микробиома"""
        
        return self.visual_manager.generate_attractive_post(
            "🍳 СКРЭМБЛ ДЛЯ ВСЕЙ СЕМЬИ С ОВОЩАМИ",
            content, "family_breakfast", benefits
        )

    def generate_saturday_omelette(self):
        """Субботний омлет с грибами и сыром"""
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
Процесс приготовления становится игрой - кто красивее украсит свою порцию? Это развивает творческие способности.
"""
        benefits = """• 🍄 Селен для антиоксидантной защиты
• 🧀 Триптофан для хорошего настроения
• 🥚 Витамин D для иммунитета
• 🌿 Антиоксиданты против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧡 СУББОТНИЙ ОМЛЕТ С ГРИБАМИ И СЫРОМ",
            content, "family_breakfast", benefits
        )

    def generate_family_waffles(self):
        """Семейные вафли с творогом и ягодами"""
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
Каждый может создать свою вафлю с любимыми топпингами, развивая самостоятельность в выборе здоровой еды.
"""
        benefits = """• 🧀 Медленный белок для сытости
• 🥚 Полноценный аминокислотный профиль
• 🌾 Клетчатка для пищеварения
• 🍓 Антиоксиданты для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🧇 СЕМЕЙНЫЕ ВАФЛИ С ТВОРОГОМ И ЯГОДАМИ",
            content, "family_breakfast", benefits
        )

    def generate_team_smoothie(self):
        """Командный смузи - каждый добавляет свой ингредиент"""
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
Командная работа создает чувство принадлежности и вовлеченности, укрепляя семейные связи.
"""
        benefits = """• 🍌 Калий для нервной системы
• 🍓 Витамин C для иммунитета
• 🥬 Железо для энергии
• 🌱 Омега-3 для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "👥 КОМАНДНЫЙ СМУЗИ: КАЖДЫЙ ДОБАВЛЯЕТ СВОЙ ИНГРЕДИЕНТ",
            content, "family_breakfast", benefits
        )

    def generate_brunch_feast(self):
        """Бранч-праздник - сборная тарелка для всех"""
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
Создание "шведского стола" позволяет каждому выбрать то, что нравится, уважая индивидуальные предпочтения.
"""
        benefits = """• 🥑 Полезные жиры для гормонов
• 🐟 Омега-3 для мозга и сердца
• 🌾 Цельные зерна для энергии
• 🥬 Фолат для синтеза ДНК"""
        
        return self.visual_manager.generate_attractive_post(
            "🎪 БРАНЧ-ПРАЗДНИК: СБОРНАЯ ТАРЕЛКА ДЛЯ ВСЕХ",
            content, "family_breakfast", benefits
        )

    # 👨‍🍳 ОБЕДЫ - СОВМЕСТНАЯ ГОТОВКА (7 рецептов)
    def generate_cooking_workshop(self):
        """Кулинарный мастер-класс: домашняя пицца"""
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
Творческий процесс развивает воображение и кулинарные навыки, создавая позитивные воспоминания.
"""
        benefits = """• 🍅 Ликопин для антиоксидантной защиты
• 🧀 Кальций для костей и зубов
• 🍗 Белок для мышц
• 🌾 Цельные зерна для пищеварения"""
        
        return self.visual_manager.generate_attractive_post(
            "🎨 КУЛИНАРНЫЙ МАСТЕР-КЛАСС: ДОМАШНЯЯ ПИЦЦА",
            content, "family_lunch", benefits
        )

    def generate_kids_friendly(self):
        """Детские кулинарные шедевры: куриные наггетсы"""
        content = """
👶 ДЕТСКИЕ КУЛИНАРНЫЕ ШЕДЕВРЫ: КУРИНЫЕ НАГГЕТСЫ
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
3. Все вместе панируют наггетсы
4. Запекаем в духовке вместо жарки

🎯 СЕМЕЙНЫЙ ПОДХОД:
Здоровые версии любимых блюд приучают к правильному питанию без чувства лишения.
"""
        benefits = """• 🍗 Высококачественный белок
• 🌾 Цельные зерна вместо белой муки
• 🥔 Калий для нервной системы
• 🥕 Витамин A для зрения"""
        
        return self.visual_manager.generate_attractive_post(
            "👶 ДЕТСКИЕ КУЛИНАРНЫЕ ШЕДЕВРЫ: КУРИНЫЕ НАГГЕТСЫ",
            content, "family_lunch", benefits
        )

    def generate_team_cooking(self):
        """Командная работа: сборный обед на всех"""
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
Распределение обязанностей учит ответственности и командной работе, важным для семейной гармонии.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🥦 Овощи разных цветов - разные фитонутриенты
• 🍗 Животный белок для баланса
• 🌿 Полезные жиры для усвоения витаминов"""
        
        return self.visual_manager.generate_attractive_post(
            "🤝 КОМАНДНАЯ РАБОТА: СБОРНЫЙ ОБЕД НА ВСЕХ",
            content, "family_lunch", benefits
        )

    def generate_family_baking(self):
        """Семейная выпечка: ПП-печенье с овсянкой"""
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
Создание "семейного рецепта", который можно передавать из поколения в поколение, укрепляет традиции.
"""
        benefits = """• 🌾 Бета-глюканы для холестерина
• 🍌 Натуральные сахара без вреда
• 🍫 Флавоноиды для сосудов
• 🟤 Антиоксиданты против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍪 СЕМЕЙНАЯ ВЫПЕЧКА: ПП-ПЕЧЕНЬЕ С ОВСЯНКОЙ",
            content, "family_lunch", benefits
        )

    def generate_weekend_bbq(self):
        """Выходной барбекю: здоровые шашлычки"""
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
Активный отдых на свежем воздухе сочетается с полезным питанием, создавая здоровые семейные традиции.
"""
        benefits = """• 🍗 Постный белок для мышц
• 🥒 Овощи на гриле - максимум пользы
• 🧅 Кверцетин против воспаления
• 🍋 Витамин C для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ВЫХОДНОЙ БАРБЕКЮ: ЗДОРОВЫЕ ШАШЛЫЧКИ",
            content, "family_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_family_lasagna(self):
        """Семейная лазанья с овощами и индейкой"""
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
Создание большого блюда на всю семью учит планированию и сотрудничеству, важным жизненным навыкам.
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
        """Субботняя пицца: каждый свой уголок"""
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
Индивидуальный подход в рамках общего блюда удовлетворяет разные вкусы, учая уважению к предпочтениям других.
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
        """Большая тарелка: сборный ужин для всех"""
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
"Шведский стол" позволяет учитывать предпочтения каждого члена семьи, создавая атмосферу свободы выбора.
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
        """Семейный десерт: фруктовая пицца"""
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
Творческий десерт без выпечки - безопасно даже для самых маленьких, развивая фантазию и любовь к готовке.
"""
        benefits = """• 🥛 Пробиотики для микробиома
• 🍯 Натуральные пребиотики
• 🍓 Витамины и антиоксиданты
• 🌱 Омега-3 для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🍓 СЕМЕЙНЫЙ ДЕСЕРТ: ФРУКТОВАЯ ПИЦЦА",
            content, "family_dessert", benefits
        )

    def generate_weekend_treat(self):
        """Выходной тортик: творожно-фруктовый"""
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
Создание праздничного настроения в обычный выходной день укрепляет семейные традиции и создает теплые воспоминания.
"""
        benefits = """• 🧀 Медленный белок для ночного восстановления
• 🍓 Натуральные фрукты вместо сахара
• 🌰 Орехи - полезные жиры и витамин E
• 🥛 Коллаген для кожи и суставов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎂 ВЫХОДНОЙ ТОРТИК: ТВОРОЖНО-ФРУКТОВЫЙ",
            content, "family_dessert", benefits
        )

    def generate_shared_sweets(self):
        """Общие сладости: шоколадные фондю"""
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
Интерактивный десерт создает атмосферу ресторана дома, превращая прием пищи в особое событие.
"""
        benefits = """• 🍫 Флавоноиды для сосудов и мозга
• 🥥 Среднецепочечные триглицериды для энергии
• 🍎 Клетчатка для пищеварения
• 🌰 Витамин E для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ОБЩИЕ СЛАДОСТИ: ШОКОЛАДНЫЕ ФОНДЮ",
            content, "family_dessert", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_family_nutrition_advice(self):
        """Совет по семейному питанию и гармонии"""
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
        """Совет по совместной готовке с детьми"""
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

# Создание экземпляра генератора
saturday_generator = SaturdayContentGenerator()
class SundayContentGenerator:
    """Генератор контента для воскресенья - планирование питания и meal prep"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_brunch_feast(self):
        """Воскресный бранч: запасаемся энергией на неделю"""
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
            content, "planning_breakfast", benefits
        )

    def generate_lazy_breakfast(self):
        """Ленивый завтрак: готовим 5 порций за раз"""
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
Готовые завтраки экономят время и гарантируют здоровый старт дня даже в самые занятые утра.
"""
        benefits = """• 🧀 Медленный белок для длительной сытости
• 🍎 Растворимая клетчатка для пищеварения
• 🌰 Витамин E для защиты клеток
• 🟤 Регуляция уровня сахара в крови"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ЛЕНИВЫЙ ЗАВТРАК: 5 ПОРЦИЙ ЗА 20 МИНУТ",
            content, "planning_breakfast", benefits
        )

    def generate_meal_prep_breakfast(self):
        """Завтраки в банках: готовая система на неделю"""
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
Идеальное решение для самых занятых утр - просто добавить жидкость и завтрак готов за 5 минут!
"""
        benefits = """• 🌾 Бета-глюканы для контроля холестерина
• 🌱 Лигнаны для гормонального баланса
• 🥥 Быстрая энергия без скачков сахара
• 💪 Белок для мышечного синтеза"""
        
        return self.visual_manager.generate_attractive_post(
            "📦 ЗАВТРАКИ В БАНКАХ: СИСТЕМА НА 7 ДНЕЙ",
            content, "planning_breakfast", benefits
        )

    def generate_sunday_porridge(self):
        """Воскресная каша: база для всей недели"""
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
Готовую кашу можно разогревать 3 дня, добавляя свежие фрукты для разнообразия вкуса.
"""
        benefits = """• 🌾 Рутин для укрепления сосудов
• 🎃 Бета-каротин для иммунитета и зрения
• 🌱 Кальций для костей и нервной системы
• 🍎 Кверцетин против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 ВОСКРЕСНАЯ КАША: БАЗА ДЛЯ ЗАВТРАКОВ",
            content, "planning_breakfast", benefits
        )

    def generate_prep_friendly_toast(self):
        """Тосты для meal prep: заготовки на утро"""
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
Раздельное хранение компонентов сохраняет свежесть и хрусткость, обеспечивая ресторанное качество завтрака.
"""
        benefits = """• 🥑 Полезные жиры для усвоения витаминов
• 🐟 Омега-3 для мозга и против воспаления
• 🥬 Нитраты для улучшения кровотока
• 🌾 Цельные зерна для стабильной энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 ТОСТЫ ДЛЯ MEAL PREP: СБОРКА ЗА 2 МИНУТЫ",
            content, "planning_breakfast", benefits
        )

    def generate_efficient_smoothie(self):
        """Эффективный смузи: заморозка на неделю"""
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
Замороженные смеси сохраняют питательные вещества до 3 месяцев и экономят время на подготовку.
"""
        benefits = """• 🥬 Железо для энергии и оксигенации
• 🍌 Калий для нервной и мышечной функции
• 🫐 Антиоксиданты против окислительного стресса
• 🌱 Омега-3 для мозга и против воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭФФЕКТИВНЫЙ СМУЗИ: 7 ПОРЦИЙ В МОРОЗИЛКЕ",
            content, "planning_breakfast", benefits
        )

    def generate_planning_omelette(self):
        """Омлет для планирования: белковый запас"""
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
Порционные омлеты - готовый завтрак или обед с высоким содержанием белка для насыщения на 4-5 часов.
"""
        benefits = """• 🥚 Холин для мозга и памяти
• 🥦 Сульфорафан для детокса и против рака
• 🍄 Витамин D для иммунитета и костей
• 🧀 Кальций для нервной проводимости"""
        
        return self.visual_manager.generate_attractive_post(
            "📊 ОМЛЕТ ДЛЯ ПЛАНИРОВАНИЯ: БЕЛК НА 3 ДНЯ",
            content, "planning_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_weekly_prep_lunch(self):
        """Обеды на неделю: система контейнеров"""
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
5 готовых обедов экономят 2.5 часа в неделю и гарантируют сбалансированное питание.
"""
        benefits = """• 🍗 Высококачественный белок для мышц
• 🍚 Магний для энергетического обмена
• 🥦 Антиоксиданты для защиты клеток
• 🥕 Витамин A для иммунитета и зрения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍱 ОБЕДЫ НА НЕДЕЛЮ: 5 КОНТЕЙНЕРОВ ЗА 45 МИНУТ",
            content, "planning_lunch", benefits
        )

    def generate_batch_cooking_lunch(self):
        """Порционная готовка: основы для разных блюд"""
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
Одни базовые компоненты = 5 разных блюд в течение недели без ощущения однообразия.
"""
        benefits = """• 🦃 Постный белок для мышечного синтеза
• 🌾 Полный набор аминокислот
• 🥬 Разнообразие овощей - разные витамины
• 🍅 Ликопин для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 ПОРЦИОННАЯ ГОТОВКА: БАЗА ДЛЯ 5 РАЗНЫХ ОБЕДОВ",
            content, "planning_lunch", benefits
        )

    def generate_efficient_lunch(self):
        """Эффективный обед: минимум времени - максимум пользы"""
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
Метод "one pan" - максимум пользы при минимуме мытья посуды, идеально для воскресной готовки.
"""
        benefits = """• 🐟 Омега-3 для мозга и против воспаления
• 🍠 Сложные углеводы для энергии
• 🌱 Фолат для синтеза ДНК
• 🍋 Витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭФФЕКТИВНЫЙ ОБЕД: ОДИН ПРОТИВЕНЬ - 4 ПОРЦИИ",
            content, "planning_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_weekly_prep_chicken(self):
        """Курица на неделю: универсальная основа"""
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
Универсальная основа для салатов, рагу, обертываний и других блюд на всю неделю.
"""
        benefits = """• 🍗 Высококачественный белок для восстановления
• 🥦 Детокс-компоненты для очищения
• 🥕 Антиоксиданты для защиты от стресса
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🍗 КУРИЦА НА НЕДЕЛЮ: ОСНОВА ДЛЯ 6 УЖИНОВ",
            content, "planning_dinner", benefits
        )

    def generate_batch_cooking(self):
        """Массовая готовка: супы и рагу на заморозку"""
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
Замороженные порции - готовый ужин за 10 минут разогрева, спасающий в самые занятые дни.
"""
        benefits = """• 🥩 Гемовое железо для профилактики анемии
• 🥬 Овощное разнообразие - полный набор витаминов
• 🌱 Растительный и животный белок для баланса
• 🍅 Термообработанные томаты - максимум ликопина"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 МАССОВАЯ ГОТОВКА: 10 ПОРЦИЙ СУПА В МОРОЗИЛКЕ",
            content, "planning_dinner", benefits
        )

    def generate_container_meal(self):
        """Контейнерные ужины: готовая сборка"""
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
Готовые боулы - здоровый ужин без мыслей "что приготовить", экономящий время и силы.
"""
        benefits = """• 🧈 Изофлавоны для гормонального баланса
• 🌾 Полноценный растительный белок
• 🥑 Полезные жиры для усвоения витаминов
• 🫕 Кальций для костей и нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "📦 КОНТЕЙНЕРНЫЕ УЖИНЫ: 4 БОУЛА НА ВЕЧЕР",
            content, "planning_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_weekly_treat(self):
        """Недельный десерт: здоровые сладости впрок"""
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
Готовые десерты предотвращают спонтанные покупки сладостей и помогают контролировать сахар.
"""
        benefits = """• 🧀 Медленный белок для ночного восстановления
• 🍫 Флавоноиды для улучшения кровотока
• 0️⃣ Без сахара - безопасно для инсулина
• 🍓 Антиоксиданты для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 НЕДЕЛЬНЫЙ ДЕСЕРТ: 8 ПОРЦИЙ БЕЗ САХАРА",
            content, "planning_dessert", benefits
        )

    def generate_prep_friendly_dessert(self):
        """Десерт для заморозки: полезное мороженое"""
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
Замороженные десерты всегда под рукой для здорового перекуса без чувства вины.
"""
        benefits = """• 🍌 Натуральная сладость без добавленного сахара
• 🫐 Антиоксиданты против окислительного стресса
• 🥛 Пробиотики для здоровья кишечника
• 💪 Белок для мышечного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "❄️ ДЕСЕРТ ДЛЯ ЗАМОРОЗКИ: ПОЛЕЗНОЕ МОРОЖЕНОЕ",
            content, "planning_dessert", benefits
        )

    # 💡 СОВЕТЫ (7 рецептов)
    def generate_meal_prep_guide_advice(self):
        """Гид по meal prep: как планировать питание на неделю"""
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
        """Недельное планирование: система для занятых"""
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
        """Эффективная готовка: максимум результата при минимуме усилий"""
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

# Создание экземпляра генератора
sunday_generator = SundayContentGenerator()
from flask import Flask, render_template_string, jsonify, request
import threading
import time
import schedule
import os

# Инициализация Flask приложения
app = Flask(__name__)

# Импорт всех созданных компонентов
from part1_config import Config, Database, SecurityManager, service_monitor, logger
from part2_systems import TimeManager, AdvancedRotationSystem, VisualManager
from part3_telegram import TelegramManager, EnhancedLogger
from part4_scientific import ScientificContentGenerator
from part5_monday import MondayContentGenerator
from part6_tuesday import TuesdayContentGenerator
from part7_wednesday import WednesdayContentGenerator
from part8_thursday import ThursdayContentGenerator
from part9_friday import FridayContentGenerator
from part10_saturday import SaturdayContentGenerator
from part11_sunday import SundayContentGenerator

class SmartContentGenerator:
    """Умный генератор контента, объединяющий все дни недели"""
    
    def __init__(self):
        self.generators = {
            'scientific': ScientificContentGenerator(),
            'monday': MondayContentGenerator(),
            'tuesday': TuesdayContentGenerator(),
            'wednesday': WednesdayContentGenerator(),
            'thursday': ThursdayContentGenerator(),
            'friday': FridayContentGenerator(),
            'saturday': SaturdayContentGenerator(),
            'sunday': SundayContentGenerator()
        }
    
    def get_generator_for_day(self, weekday: int):
        """Получение генератора для текущего дня недели"""
        day_generators = {
            0: self.generators['monday'],      # Понедельник
            1: self.generators['tuesday'],     # Вторник
            2: self.generators['wednesday'],   # Среда
            3: self.generators['thursday'],    # Четверг
            4: self.generators['friday'],      # Пятница
            5: self.generators['saturday'],    # Суббота
            6: self.generators['sunday']       # Воскресенье
        }
        return day_generators.get(weekday, self.generators['monday'])

class SmartScheduler:
    """Умный планировщик с новым расписанием"""
    
    def __init__(self):
        self.content_generator = SmartContentGenerator()
        self.rotation_system = AdvancedRotationSystem()
        self.telegram_manager = TelegramManager()
        self.time_manager = TimeManager()
    
    def schedule_posts(self):
        """Настройка расписания публикаций согласно новым требованиям"""
        schedule.clear()
        
        # НОВОЕ РАСПИСАНИЕ согласно требованиям
        schedule_config = Config.SCHEDULE_CONFIG
        
        for day_type, times in schedule_config.items():
            for kemerovo_time, content_type in times.items():
                server_time = TimeManager.kemerovo_to_server(kemerovo_time)
                
                if day_type == 'weekdays':
                    # Пн-Пт: 08:30 совет, 09:00 завтрак, 12:00 обед, 18:00 ужин, 20:00 десерт
                    schedule.every().monday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                    schedule.every().tuesday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                    schedule.every().wednesday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                    schedule.every().thursday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                    schedule.every().friday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                else:
                    # Сб-Вс: 08:30 совет, 10:00 завтрак, 13:00 обед, 19:00 ужин, 20:00 десерт
                    schedule.every().saturday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                    schedule.every().sunday.at(server_time).do(
                        self.send_scheduled_post, content_type, kemerovo_time
                    )
                
                logger.info(f"📅 Настроено время: {kemerovo_time} Кемерово -> {server_time} Сервер ({content_type})")
    
    def send_scheduled_post(self, content_type: str, scheduled_time: str):
        """Отправка запланированного поста"""
        try:
            logger.info(f"⏰ ЗАПУСК ПО РАСПИСАНИЮ: {scheduled_time} -> {content_type}")
            
            weekday = TimeManager.get_kemerovo_weekday()
            current_hour = TimeManager.get_kemerovo_hour()
            
            # Валидация типа контента для текущего времени
            validated_type = self.rotation_system.validate_content_type_for_current_time(
                content_type, current_hour
            )
            
            # Получаем генератор для текущего дня
            day_generator = self.content_generator.get_generator_for_day(weekday)
            
            # Получаем метод для генерации контента
            method_name = self.rotation_system.get_priority_recipe(validated_type, weekday)
            
            if hasattr(day_generator, method_name):
                content = getattr(day_generator, method_name)()
                success = self.telegram_manager.send_message(content, validated_type, method_name)
                
                if success:
                    logger.info(f"✅ Успешно отправлен пост: {validated_type}")
                else:
                    logger.error(f"❌ Ошибка отправки поста: {validated_type}")
            else:
                logger.error(f"❌ Метод {method_name} не найден в генераторе")
                
        except Exception as e:
            logger.error(f"❌ Ошибка в send_scheduled_post: {str(e)}")

# Создание экземпляров
smart_scheduler = SmartScheduler()
telegram_manager = TelegramManager()
database = Database()

# HTML шаблон для дашборда
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>🍏 Умный Кулинарный Бот</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }
        
        .header {
            text-align: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 3px solid #f8f9fa;
        }
        
        .header h1 {
            color: #2c3e50;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .header p {
            color: #7f8c8d;
            font-size: 1.2em;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }
        
        .stat-card h3 {
            font-size: 1.1em;
            margin-bottom: 15px;
            opacity: 0.9;
        }
        
        .stat-card p {
            font-size: 1.8em;
            font-weight: bold;
        }
        
        .controls-section {
            background: #f8f9fa;
            padding: 30px;
            border-radius: 15px;
            margin: 30px 0;
        }
        
        .section-title {
            color: #2c3e50;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        
        .manual-controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .btn {
            padding: 15px 25px;
            border: none;
            border-radius: 10px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .breakfast-btn { background: #ff6b6b; color: white; }
        .lunch-btn { background: #4ecdc4; color: white; }
        .dinner-btn { background: #45b7d1; color: white; }
        .dessert-btn { background: #96ceb4; color: white; }
        .success-btn { background: #2ecc71; color: white; }
        .warning-btn { background: #f39c12; color: white; }
        .danger-btn { background: #e74c3c; color: white; }
        .info-btn { background: #3498db; color: white; }
        
        .schedule-table {
            width: 100%;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            margin-bottom: 25px;
        }
        
        .schedule-table table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .schedule-table th {
            background: #34495e;
            color: white;
            padding: 15px;
            text-align: center;
        }
        
        .schedule-table td {
            padding: 12px 15px;
            text-align: center;
            border-bottom: 1px solid #ecf0f1;
        }
        
        .schedule-table tr:nth-child(even) {
            background: #f8f9fa;
        }
        
        .logs-container {
            background: #1a1a1a;
            color: #00ff00;
            padding: 20px;
            border-radius: 10px;
            font-family: 'Courier New', monospace;
            height: 300px;
            overflow-y: auto;
            margin-top: 20px;
        }
        
        .log-entry {
            margin-bottom: 5px;
            line-height: 1.4;
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }
        
        .status-active { background: #2ecc71; }
        .status-error { background: #e74c3c; }
        .status-warning { background: #f39c12; }
        
        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }
            
            .header h1 {
                font-size: 2em;
            }
            
            .manual-controls {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🍏 Умный Кулинарный Бот</h1>
            <p>Система автоматической публикации рецептов в Telegram</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>📊 Статус системы</h3>
                <p id="status">Загрузка...</p>
            </div>
            <div class="stat-card">
                <h3>👥 Подписчики</h3>
                <p id="subscribersCount">Загрузка...</p>
            </div>
            <div class="stat-card">
                <h3>⏰ Время сервера / Кемерово</h3>
                <p id="timeInfo">Загрузка...</p>
            </div>
            <div class="stat-card">
                <h3>📨 Сообщения отправлено</h3>
                <p id="messageStats">Загрузка...</p>
            </div>
        </div>

        <div class="controls-section">
            <h2 class="section-title">🎛️ Ручное управление постами</h2>
            <div class="manual-controls">
                <button class="btn breakfast-btn" onclick="sendManualPost('breakfast')">
                    🍳 Завтрак
                </button>
                <button class="btn lunch-btn" onclick="sendManualPost('lunch')">
                    🍲 Обед
                </button>
                <button class="btn dinner-btn" onclick="sendManualPost('dinner')">
                    🍽️ Ужин
                </button>
                <button class="btn dessert-btn" onclick="sendManualPost('dessert')">
                    🍰 Десерт
                </button>
            </div>
            
            <h2 class="section-title">⚙️ Управление системой</h2>
            <div class="manual-controls">
                <button class="btn success-btn" onclick="checkRotation()">
                    🔄 Проверить ротацию
                </button>
                <button class="btn info-btn" onclick="getSchedule()">
                    📅 Текущее расписание
                </button>
                <button class="btn warning-btn" onclick="forceCleanup()">
                    🧹 Очистка кэша
                </button>
                <button class="btn danger-btn" onclick="emergencyStop()">
                    🛑 Аварийная остановка
                </button>
            </div>
        </div>

        <div class="controls-section">
            <h2 class="section-title">📅 Расписание публикаций</h2>
            <div class="schedule-table">
                <table>
                    <thead>
                        <tr>
                            <th>Время</th>
                            <th>Понедельник-Пятница</th>
                            <th>Суббота-Воскресенье</th>
                        </tr>
                    </thead>
                    <tbody id="scheduleTable">
                        <!-- Заполняется JavaScript -->
                    </tbody>
                </table>
            </div>
        </div>

        <div class="controls-section">
            <h2 class="section-title">📊 Логи системы</h2>
            <div class="logs-container" id="logs">
                Загрузка логов...
            </div>
        </div>
    </div>

    <script>
        // Обновление дашборда
        function updateDashboard() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status').innerHTML = 
                        `<span class="status-indicator status-active"></span>Система активна<br>
                         <small>Аптайм: ${Math.round(data.uptime_seconds/3600)}ч</small>`;
                    
                    document.getElementById('subscribersCount').innerHTML = 
                        `${data.subscribers_count || 'Загрузка...'}`;
                    
                    document.getElementById('timeInfo').innerHTML = 
                        `${data.server_time}<br><small>${data.kemerovo_time}</small>`;
                    
                    document.getElementById('messageStats').innerHTML = 
                        `${data.messages_sent}<br><small>Дубликатов: ${data.duplicate_rejections}</small>`;
                })
                .catch(error => {
                    document.getElementById('status').innerHTML = 
                        `<span class="status-indicator status-error"></span>Ошибка подключения`;
                });
            
            fetch('/api/logs')
                .then(r => r.text())
                .then(logs => {
                    document.getElementById('logs').innerHTML = logs;
                });
            
            updateScheduleTable();
        }
        
        // Обновление таблицы расписания
        function updateScheduleTable() {
            const scheduleData = {
                '08:30': { weekdays: '✅ Совет', weekends: '✅ Совет' },
                '09:00': { weekdays: '✅ Завтрак', weekends: '❌' },
                '10:00': { weekdays: '❌', weekends: '✅ Завтрак' },
                '12:00': { weekdays: '✅ Обед', weekends: '❌' },
                '13:00': { weekdays: '❌', weekends: '✅ Обед' },
                '18:00': { weekdays: '✅ Ужин', weekends: '❌' },
                '19:00': { weekdays: '❌', weekends: '✅ Ужин' },
                '20:00': { weekdays: '✅ Десерт', weekends: '✅ Десерт' }
            };
            
            let tableHTML = '';
            for (const [time, schedules] of Object.entries(scheduleData)) {
                tableHTML += `
                    <tr>
                        <td><strong>${time}</strong></td>
                        <td>${schedules.weekdays}</td>
                        <td>${schedules.weekends}</td>
                    </tr>
                `;
            }
            document.getElementById('scheduleTable').innerHTML = tableHTML;
        }
        
        // Ручная отправка поста
        function sendManualPost(postType) {
            if (!confirm(`Создать ${getPostTypeName(postType)} пост в Telegram канал?`)) return;
            
            fetch('/api/manual-post', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ type: postType })
            })
            .then(r => r.json())
            .then(data => {
                alert(data.message);
                updateDashboard();
            })
            .catch(error => {
                alert('❌ Ошибка отправки поста');
            });
        }
        
        function getPostTypeName(type) {
            const names = {
                'breakfast': 'завтрак',
                'lunch': 'обед',
                'dinner': 'ужин',
                'dessert': 'десерт'
            };
            return names[type] || type;
        }
        
        // Проверка ротации
        function checkRotation() {
            fetch('/api/rotation-status')
                .then(r => r.json())
                .then(data => {
                    let status = '📊 Статус ротации:\\n\\n';
                    for (const [category, stats] of Object.entries(data.rotation_status)) {
                        status += `${category}: ${stats.available}/${stats.total} (${stats.availability_percent}%)\\n`;
                    }
                    alert(status);
                });
        }
        
        // Получение расписания
        function getSchedule() {
            const schedule = {
                'Будни (Пн-Пт)': [
                    '08:30 - Совет',
                    '09:00 - Завтрак', 
                    '12:00 - Обед',
                    '18:00 - Ужин',
                    '20:00 - Десерт'
                ],
                'Выходные (Сб-Вс)': [
                    '08:30 - Совет',
                    '10:00 - Завтрак',
                    '13:00 - Обед', 
                    '19:00 - Ужин',
                    '20:00 - Десерт'
                ]
            };
            
            let message = '📅 ТЕКУЩЕЕ РАСПИСАНИЕ\\n\\n';
            for (const [dayType, times] of Object.entries(schedule)) {
                message += `${dayType}:\\n`;
                times.forEach(time => message += `• ${time}\\n`);
                message += '\\n';
            }
            alert(message);
        }
        
        // Очистка кэша
        function forceCleanup() {
            if (!confirm('Очистить кэш и старые сообщения?')) return;
            
            fetch('/api/cleanup', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    alert(data.message);
                    updateDashboard();
                });
        }
        
        // Аварийная остановка
        function emergencyStop() {
            if (!confirm('ВЫ УВЕРЕНЫ? Это остановит все запланированные посты!')) return;
            
            fetch('/api/emergency-stop', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    alert(data.message);
                });
        }
        
        // Обновляем каждые 10 секунд
        setInterval(updateDashboard, 10000);
        updateDashboard();
    </script>
</body>
</html>
'''

# Flask роуты
@app.route('/')
def dashboard():
    """Главная панель управления ботом"""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/status')
@SecurityManager.require_auth
def api_status():
    """API статуса системы"""
    try:
        times = TimeManager.get_current_times()
        rotation_status = AdvancedRotationSystem().check_rotation_status()
        subscribers_count = telegram_manager.get_subscribers_count()
        
        total_recipes = sum(stats['total'] for stats in rotation_status.values())
        available_recipes = sum(stats['available'] for stats in rotation_status.values())
        
        return jsonify({
            "status": "active",
            "uptime_seconds": service_monitor.get_status()["uptime_seconds"],
            "server_time": times['server_time'],
            "kemerovo_time": times['kemerovo_time'],
            "subscribers_count": subscribers_count,
            "messages_sent": service_monitor.request_count,
            "duplicate_rejections": service_monitor.duplicate_rejections,
            "total_recipes": total_recipes,
            "available_recipes": available_recipes
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logs')
@SecurityManager.require_auth
def get_logs():
    """Получение последних логов"""
    try:
        with open('bot_enhanced.log', 'r', encoding='utf-8') as f:
            logs = f.readlines()[-50:]  # Последние 50 строк
        return '<br>'.join(['<div class="log-entry">' + line.strip() + '</div>' for line in logs[::-1]])
    except Exception as e:
        return f"Ошибка чтения логов: {str(e)}"

@app.route('/api/rotation-status')
@SecurityManager.require_auth
def rotation_status():
    """Статус ротации рецептов"""
    try:
        rotation_system = AdvancedRotationSystem()
        status = rotation_system.check_rotation_status()
        return jsonify({"rotation_status": status})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/manual-post', methods=['POST'])
@SecurityManager.require_auth
def manual_post():
    """Ручная отправка поста"""
    try:
        data = request.get_json()
        post_type = data.get('type', 'breakfast')
        
        logger.info(f"🔄 ЗАПУСК РУЧНОЙ ОТПРАВКИ: {post_type}")
        
        weekday = TimeManager.get_kemerovo_weekday()
        generator = smart_scheduler.content_generator.get_generator_for_day(weekday)
        
        success, message = telegram_manager.send_manual_post(post_type, generator)
        
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500
            
    except Exception as e:
        error_msg = f"❌ Ошибка ручной отправки: {str(e)}"
        logger.error(error_msg)
        return jsonify({"status": "error", "message": error_msg}), 500

@app.route('/api/cleanup', methods=['POST'])
@SecurityManager.require_auth
def cleanup():
    """Очистка кэша и старых сообщений"""
    try:
        telegram_manager.cleanup_old_messages(30)
        database.cleanup_old_records()
        
        return jsonify({"status": "success", "message": "✅ Кэш успешно очищен"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/emergency-stop', methods=['POST'])
@SecurityManager.require_auth
def emergency_stop():
    """Аварийная остановка системы"""
    try:
        schedule.clear()
        logger.critical("🛑 СИСТЕМА ОСТАНОВЛЕНА ПО КОМАНДЕ ПОЛЬЗОВАТЕЛЯ")
        return jsonify({"status": "success", "message": "🛑 Система остановлена"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
                # Самопинг для поддержания активности
                requests.get(f"http://localhost:{os.environ.get('PORT', 5000)}/api/status", timeout=10)
                service_monitor.update_keep_alive()
                time.sleep(300)  # Каждые 5 минут
            except Exception as e:
                time.sleep(60)
    
    Thread(target=keep_alive, daemon=True).start()

# Запуск приложения
if __name__ == '__main__':
    try:
        logger.info("🚀 ЗАПУСК СИСТЕМЫ УМНОГО КУЛИНАРНОГО БОТА")
        
        # Инициализация базы данных
        database = Database()
        
        # Настройка расписания
        smart_scheduler.schedule_posts()
        
        # Запуск планировщика в отдельном потоке
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # Проверка ротации
        rotation_system = AdvancedRotationSystem()
        rotation_status = rotation_system.check_rotation_status()
        logger.info(f"📊 Статус ротации: {len(rotation_status)} категорий")
        
        # Тестирование Telegram подключения
        if telegram_manager.test_connection():
            subscribers = telegram_manager.get_subscribers_count()
            logger.info(f"✅ Telegram подключение: УСПЕХ | Подписчики: {subscribers}")
        else:
            logger.error("❌ Telegram подключение: ОШИБКА")
        
        # Запуск keep-alive для Render
        start_keep_alive()
        
        logger.info("✅ СИСТЕМА УСПЕШНО ЗАПУЩЕНА")
        
        # Запуск Flask приложения
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        raise


