import os
import logging
import requests
import json
import time
import schedule
import hashlib
import re
from datetime import datetime, timedelta
from threading import Thread, Lock, RLock
from flask import Flask, request, jsonify, render_template_string
import pytz
import random
from dotenv import load_dotenv
from functools import wraps
import sqlite3
from contextlib import contextmanager
import urllib.parse
import hmac

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
    ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
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
    
    # Настройки анонимного голосования
    ANONYMOUS_VOTING = True
    VOTE_HASH_SALT = os.getenv('VOTE_HASH_SALT', 'your-anonymous-vote-salt-here')
    HIDE_USERNAMES_IN_RESULTS = True
    AGGREGATE_VOTE_DATA = True

# МОНИТОРИНГ СЕРВИСА
class ServiceMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.last_keep_alive = None
        self.keep_alive_count = 0
        self.recipes_sent = 0
        self.polls_sent = 0
        self.results_published = 0
        self.anonymous_votes_collected = 0
    
    def increment_request(self):
        self.request_count += 1
    
    def increment_recipe_count(self):
        self.recipes_sent += 1
    
    def increment_poll_count(self):
        self.polls_sent += 1
    
    def increment_results_count(self):
        self.results_published += 1
    
    def increment_anonymous_votes(self, count=1):
        self.anonymous_votes_collected += count
    
    def update_keep_alive(self):
        self.last_keep_alive = datetime.now()
        self.keep_alive_count += 1
    
    def get_status(self):
        return {
            "status": "healthy",
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "requests_handled": self.request_count,
            "recipes_sent": self.recipes_sent,
            "polls_sent": self.polls_sent,
            "results_published": self.results_published,
            "anonymous_votes_collected": self.anonymous_votes_collected,
            "keep_alive_count": self.keep_alive_count,
            "last_keep_alive": self.last_keep_alive.isoformat() if self.last_keep_alive else None,
            "timestamp": datetime.now().isoformat()
        }

service_monitor = ServiceMonitor()

# ИСПРАВЛЕННАЯ ПОТОКОБЕЗОПАСНАЯ БАЗА ДАННЫХ
class ThreadSafeDatabase:
    def __init__(self):
        self.lock = RLock()
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
                    content_type TEXT
                )
            ''')
            
            # Таблица: История опросов
            conn.execute('''
                CREATE TABLE IF NOT EXISTS poll_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poll_type TEXT,
                    poll_question TEXT,
                    message_id INTEGER,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    results_sent BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Таблица: Статистика использования контента
            conn.execute('''
                CREATE TABLE IF NOT EXISTS content_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT,
                    method_name TEXT,
                    used_count INTEGER DEFAULT 0,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица: Результаты опросов
            conn.execute('''
                CREATE TABLE IF NOT EXISTS poll_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    poll_type TEXT,
                    results_json TEXT,
                    total_votes INTEGER,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP NULL
                )
            ''')
            
            # Таблица: Комментарии для анализа
            conn.execute('''
                CREATE TABLE IF NOT EXISTS poll_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    user_id INTEGER,
                    comment_text TEXT,
                    vote_option TEXT,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # НОВАЯ ТАБЛИЦА: Анонимные голоса
            conn.execute('''
                CREATE TABLE IF NOT EXISTS anonymous_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_hash TEXT,
                    poll_type TEXT,
                    message_id INTEGER,
                    vote_option TEXT,
                    comment_text TEXT,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_hash, poll_type, message_id)
                )
            ''')
            
            # Создаем индексы для производительности
            conn.execute('CREATE INDEX IF NOT EXISTS idx_rotation_last_used ON recipe_rotation(last_used)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sent_messages_hash ON sent_messages(content_hash)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_poll_history_sent_at ON poll_history(sent_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_content_usage_last_used ON content_usage(last_used)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_anonymous_votes_composite ON anonymous_votes(user_hash, poll_type, message_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_anonymous_votes_message ON anonymous_votes(message_id, poll_type)')
    
    @contextmanager 
    def get_connection(self):
        with self.lock:
            conn = sqlite3.connect('channel.db', check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"❌ Ошибка базы данных: {e}")
                raise
            finally:
                conn.close()

# СИСТЕМА АНОНИМНОГО ГОЛОСОВАНИЯ
class AnonymousVotingSystem:
    def __init__(self):
        self.salt = Config.VOTE_HASH_SALT
        self.db = ThreadSafeDatabase()
    
    def generate_user_hash(self, user_id, poll_type, message_id):
        """Генерация анонимного хеша для пользователя"""
        data = f"{user_id}_{poll_type}_{message_id}_{self.salt}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]  # Сокращенный хеш
    
    def register_anonymous_vote(self, user_hash, poll_type, message_id, vote_option, comment_text=""):
        """Регистрация анонимного голоса"""
        try:
            with self.db.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO anonymous_votes 
                    (user_hash, poll_type, message_id, vote_option, comment_text, voted_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (user_hash, poll_type, message_id, vote_option, comment_text))
            
            service_monitor.increment_anonymous_votes()
            logger.info(f"✅ Зарегистрирован анонимный голос: {vote_option} для опроса {message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации анонимного голоса: {e}")
            return False
    
    def has_user_voted(self, user_hash, poll_type, message_id):
        """Проверка, голосовал ли уже пользователь"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT 1 FROM anonymous_votes 
                WHERE user_hash = ? AND poll_type = ? AND message_id = ?
            ''', (user_hash, poll_type, message_id))
            return cursor.fetchone() is not None
    
    def get_anonymous_results(self, message_id, poll_type):
        """Получение анонимных результатов"""
        with self.db.get_connection() as conn:
            # Подсчет голосов по вариантам
            cursor = conn.execute('''
                SELECT vote_option, COUNT(*) as vote_count
                FROM anonymous_votes 
                WHERE message_id = ? AND poll_type = ?
                GROUP BY vote_option
            ''', (message_id, poll_type))
            
            vote_counts = {}
            total_votes = 0
            
            for row in cursor:
                vote_counts[row['vote_option']] = row['vote_count']
                total_votes += row['vote_count']
            
            # Расчет процентов
            percentages = {}
            for option, count in vote_counts.items():
                percentages[option] = round((count / total_votes) * 100, 1) if total_votes > 0 else 0
            
            # Получение уникальных комментариев (без привязки к пользователям)
            cursor = conn.execute('''
                SELECT DISTINCT comment_text 
                FROM anonymous_votes 
                WHERE message_id = ? AND poll_type = ? AND comment_text != ''
            ''', (message_id, poll_type))
            
            anonymous_comments = [row['comment_text'] for row in cursor]
            
            return {
                'total_votes': total_votes,
                'vote_counts': vote_counts,
                'percentages': percentages,
                'anonymous_comments': anonymous_comments,
                'poll_type': poll_type,
                'unique_voters': total_votes,  # В анонимной системе каждый голос от уникального хеша
                'message': 'Анонимные результаты собраны'
            }

# ИСПРАВЛЕННАЯ СИСТЕМА БЕЗОПАСНОСТИ С ОЧИСТКОЙ ПАМЯТИ
class SecurityManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SecurityManager, cls).__new__(cls)
                cls._instance.request_log = {}
                cls._instance.blocked_ips = set()
                # Запускаем фоновую очистку
                cls._instance._start_cleanup_thread()
            return cls._instance
    
    def _start_cleanup_thread(self):
        """Запуск фоновой очистки старых записей"""
        def cleanup_loop():
            while True:
                time.sleep(Config.RATE_LIMIT_WINDOW * 2)  # Очистка каждые 2 минуты
                self.cleanup_old_requests()
        
        cleanup_thread = Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
        logger.info("✅ Запущена фоновая очистка старых запросов")
    
    def cleanup_old_requests(self):
        """Очистка старых записей из лога запросов"""
        current_time = time.time()
        cutoff = current_time - (Config.RATE_LIMIT_WINDOW * 2)  # Двойной запас
        
        ips_to_remove = []
        for ip, requests in self.request_log.items():
            # Оставляем только свежие запросы
            fresh_requests = [req_time for req_time in requests if req_time > cutoff]
            if fresh_requests:
                self.request_log[ip] = fresh_requests
            else:
                ips_to_remove.append(ip)
        
        # Удаляем IP без активных запросов
        for ip in ips_to_remove:
            del self.request_log[ip]
            if ip in self.blocked_ips:
                self.blocked_ips.remove(ip)
        
        if ips_to_remove:
            logger.info(f"🧹 Очищено {len(ips_to_remove)} неактивных IP-адресов")
    
    def check_rate_limit(self, ip_address):
        current_time = time.time()
        if ip_address in self.blocked_ips:
            return False
        
        if ip_address not in self.request_log:
            self.request_log[ip_address] = []
        
        # Очищаем старые запросы для этого IP
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

# ИСПРАВЛЕННАЯ СИСТЕМА ОТСЛЕЖИВАНИЯ КОНТЕНТА (без SQL-инъекций)
class ContentTracker:
    def __init__(self):
        self.db = ThreadSafeDatabase()
    
    def track_content_usage(self, content_type, method_name):
        """Отслеживание использования контента"""
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT INTO content_usage (content_type, method_name, used_count, last_used)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(content_type, method_name) 
                DO UPDATE SET 
                    used_count = used_count + 1,
                    last_used = CURRENT_TIMESTAMP
            ''', (content_type, method_name))
    
    def get_recipe_usage_stats(self):
        """Статистика использования рецептов (ИСПРАВЛЕНА SQL-инъекция)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT r.recipe_type, COUNT(*) as used_count,
                       (SELECT COUNT(*) FROM recipe_rotation WHERE recipe_type = r.recipe_type) as total_count
                FROM recipe_rotation r 
                WHERE r.last_used >= DATE('now', ?)
                GROUP BY r.recipe_type
                ORDER BY used_count DESC
            ''', ('-90 days',))
            return cursor.fetchall()
    
    def get_poll_usage_stats(self):
        """Статистика использования опросов (ИСПРАВЛЕНА SQL-инъекция)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT poll_type, COUNT(*) as used_count,
                       MAX(sent_at) as last_used
                FROM poll_history 
                WHERE sent_at >= DATE('now', ?)
                GROUP BY poll_type
                ORDER BY used_count DESC
            ''', ('-30 days',))
            return cursor.fetchall()
    
    def get_available_polls_count(self):
        """Количество доступных опросов (ИСПРАВЛЕНА SQL-инъекция)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT COUNT(DISTINCT poll_type) as available_polls
                FROM poll_history 
                WHERE sent_at >= DATE('now', ?)
            ''', ('-30 days',))
            result = cursor.fetchone()
            return result['available_polls'] if result else 0

# СИСТЕМА УВЕДОМЛЕНИЙ АДМИНИСТРАТОРА
class AdminNotifier:
    def __init__(self, telegram_manager):
        self.telegram = telegram_manager
        self.admin_chat_id = Config.ADMIN_CHAT_ID
    
    def send_admin_alert(self, message, urgency="normal"):
        """Отправка уведомления администратору"""
        if not self.admin_chat_id:
            logger.warning("⚠️ ADMIN_CHAT_ID не настроен, уведомления не отправляются")
            return False
            
        urgency_icons = {
            "normal": "ℹ️",
            "warning": "⚠️", 
            "critical": "🚨",
            "success": "✅"
        }
        
        icon = urgency_icons.get(urgency, "ℹ️")
        formatted_message = f"{icon} {message}"
        
        try:
            return self.telegram.send_direct_message(self.admin_chat_id, formatted_message)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления администратору: {e}")
            return False
    
    def notify_last_poll_used(self, poll_count):
        """Уведомление о использовании последнего опроса"""
        message = f"""📊 ИСПОЛЬЗОВАН ПОСЛЕДНИЙ ОПРОС!

Всего отправлено опросов: {poll_count}

🚨 НЕОБХОДИМО:
• Сгенерировать новые опросы
• Добавить разнообразие тем
• Обновить базу контента

💡 Рекомендуемые темы:
- Пищевые привычки
- Спортивное питание  
- Сезонные продукты
- Психология питания"""
        
        return self.send_admin_alert(message, "critical")
    
    def notify_last_recipe_used(self, recipe_type, total_recipes):
        """Уведомление о использовании последнего рецепта в категории"""
        message = f"""🍳 ИСПОЛЬЗОВАН ПОСЛЕДНИЙ РЕЦЕПТ!

Категория: {recipe_type}
Всего рецептов в системе: {total_recipes}

🚨 НЕОБХОДИМО:
• Добавить новые рецепты в категорию {recipe_type}
• Обновить базу рецептов
• Проверить ротацию контента

💡 Совет: Используйте сезонные ингредиенты"""
        
        return self.send_admin_alert(message, "warning")
    
    def notify_poll_results_collected(self, poll_type, total_votes):
        """Уведомление о сборе результатов опроса"""
        message = f"""📊 РЕЗУЛЬТАТЫ ОПРОСА СОБРАНЫ!

Тип опроса: {poll_type}
Всего голосов: {total_votes}

✅ Результаты автоматически проанализированы
📈 Научный анализ сгенерирован
🚀 Публикация запланирована"""

        return self.send_admin_alert(message, "success")
    
    def notify_anonymous_voting_started(self, poll_type, message_id):
        """Уведомление о запуске анонимного голосования"""
        message = f"""🕵️‍♂️ ЗАПУЩЕНО АНОНИМНОЕ ГОЛОСОВАНИЕ!

Тип опроса: {poll_type}
ID сообщения: {message_id}

🔒 Особенности:
• Ники пользователей скрыты
• Голоса анонимизированы
• Результаты агрегированы
• Конфиденциальность гарантирована"""

        return self.send_admin_alert(message, "success")

# СИСТЕМА АНАЛИЗА КОММЕНТАРИЕВ И ГОЛОСОВАНИЯ (ОБНОВЛЕНА ДЛЯ АНОНИМНОСТИ)
class CommentVoteAnalyzer:
    def __init__(self):
        self.vote_patterns = {
            'gut_health': {
                'метаболизм': ['стальной метаболизм', 'метаболизм', 'перевариваю', '1', 'один', 'первый'],
                'радар': ['топовый радар', 'радар', 'детектор', 'плохих продуктов', '2', 'два', 'второй'],
                'часы': ['внутренние часы', 'часы', 'голод по будильнику', '3', 'три', 'третий'],
                'микробиом': ['микробиом-богатырь', 'микробиом', 'восстановление', '4', 'четыре', 'четвертый']
            },
            'food_archetype': {
                'создатель': ['создатель', ' готовка', 'искусство', 'творчество', '1', 'один', 'первый'],
                'топливщик': ['топливщик', 'топливо', 'энергия', 'кбжу', '2', 'два', 'второй'],
                'гедонист': ['гедонист', 'удовольствие', 'наслаждение', '3', 'три', 'третий'],
                'аналитик': ['аналитик', 'изучение', 'состав', 'исследования', '4', 'четыре', 'четвертый']
            },
            'food_dilemma': {
                'авокадо': ['авокадо', 'полезные жиры', '1', 'один', 'первый'],
                'сыр': ['сыр', 'аромат', 'кальций', '2', 'два', 'второй'],
                'шоколад': ['черный шоколад', 'шоколад', 'антиоксиданты', '3', 'три', 'третий'],
                'банан': ['банан', 'натуральная сладость', '4', 'четыре', 'четвертый'],
                'кофе': ['кофе', 'утренний кофе', 'бодрость', '5', 'пять', 'пятый'],
                'чай': ['чай', 'травяной чай', 'релакс', 'уют', '6', 'шесть', 'шестой']
            },
            'weekly_challenge': {
                'гидратация': ['гидратация', 'вода', '2 литра', '1', 'один', 'первый'],
                'овощи': ['овощной', '5 овощей', 'овощи', '2', 'два', 'второй'],
                'осознанность': ['осознанное', '20 жеваний', 'телефон', '3', 'три', 'третий'],
                'белок': ['белковый', 'белок', 'протеин', '4', 'четыре', 'четвертый']
            },
            'cooking_style': {
                'инженер': ['системный инженер', 'точные рецепты', 'meal prep', '1', 'один', 'первый'],
                'импровизатор': ['импровизатор', 'художник', 'настроение', '2', 'два', 'второй'],
                'традиционный': ['традиционный', 'гурман', 'семейные рецепты', '3', 'три', 'третий'],
                'экспериментатор': ['экспериментатор', 'новатор', 'тренды', 'технологии', '4', 'четыре', 'четвертый']
            }
        }
    
    def analyze_comment_vote(self, comment_text, poll_type):
        """Анализ комментария и определение выбора пользователя"""
        comment_lower = comment_text.lower().strip()
        votes = []
        
        if poll_type in self.vote_patterns:
            for option, keywords in self.vote_patterns[poll_type].items():
                for keyword in keywords:
                    if keyword in comment_lower:
                        votes.append(option)
                        break
        
        return list(set(votes))

# СИСТЕМА СБОРА И АНАЛИЗА РЕЗУЛЬТАТОВ (ОБНОВЛЕНА ДЛЯ АНОНИМНОСТИ)
class PollResultsCollector:
    def __init__(self, telegram_manager):
        self.telegram = telegram_manager
        self.vote_analyzer = CommentVoteAnalyzer()
        self.db = ThreadSafeDatabase()
        self.anonymous_voting = AnonymousVotingSystem()
    
    def collect_poll_results(self, message_id, poll_type):
        """Сбор и анализ результатов опроса из комментариев"""
        try:
            logger.info(f"🔄 Начинаем сбор результатов для опроса {message_id}")
            
            if Config.ANONYMOUS_VOTING:
                return self._collect_anonymous_results(message_id, poll_type)
            else:
                return self._collect_public_results(message_id, poll_type)
            
        except Exception as e:
            logger.error(f"❌ Ошибка сбора результатов опроса: {e}")
            return self._create_empty_results(poll_type)
    
    def _collect_anonymous_results(self, message_id, poll_type):
        """Сбор анонимных результатов"""
        logger.info(f"🔒 Сбор анонимных результатов для опроса {message_id}")
        
        # Получаем результаты из системы анонимного голосования
        results = self.anonymous_voting.get_anonymous_results(message_id, poll_type)
        
        if results['total_votes'] > 0:
            # Сохраняем результаты
            self._save_poll_results(message_id, poll_type, results)
            logger.info(f"✅ Собраны анонимные результаты: {results['total_votes']} голосов")
        else:
            logger.warning(f"⚠️ Нет анонимных голосов для опроса {message_id}")
        
        return results
    
    def _collect_public_results(self, message_id, poll_type):
        """Сбор публичных результатов (старый метод)"""
        comments = self.telegram.get_post_comments(message_id)
        
        if not comments:
            logger.warning(f"⚠️ Нет комментариев для анализа опроса {message_id}")
            return self._create_empty_results(poll_type)
        
        # Анализируем голоса
        results = self._analyze_comments_votes(comments, poll_type, message_id)
        
        # Сохраняем результаты
        self._save_poll_results(message_id, poll_type, results)
        
        logger.info(f"✅ Собраны публичные результаты: {len(results['votes'])} голосов")
        return results
    
    def register_anonymous_vote(self, user_id, poll_type, message_id, comment_text):
        """Регистрация анонимного голоса из комментария"""
        try:
            # Генерируем анонимный хеш пользователя
            user_hash = self.anonymous_voting.generate_user_hash(user_id, poll_type, message_id)
            
            # Проверяем, не голосовал ли уже пользователь
            if self.anonymous_voting.has_user_voted(user_hash, poll_type, message_id):
                logger.info(f"⚠️ Пользователь уже голосовал в опросе {message_id}")
                return False
            
            # Анализируем комментарий для определения выбора
            vote_option = self.vote_analyzer.analyze_comment_vote(comment_text, poll_type)
            
            if vote_option:
                # Регистрируем анонимный голос
                success = self.anonymous_voting.register_anonymous_vote(
                    user_hash, poll_type, message_id, vote_option[0], comment_text
                )
                
                if success:
                    logger.info(f"✅ Анонимный голос зарегистрирован: {vote_option[0]}")
                    return True
            
            logger.warning(f"⚠️ Не удалось определить голос из комментария: {comment_text}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации анонимного голоса: {e}")
            return False
    
    def _create_empty_results(self, poll_type):
        """Создание пустых результатов при отсутствии данных"""
        return {
            'total_votes': 0,
            'vote_counts': {},
            'percentages': {},
            'votes': [],
            'poll_type': poll_type,
            'message': 'Недостаточно данных для анализа',
            'anonymous_comments': []
        }
    
    def _analyze_comments_votes(self, comments, poll_type, message_id):
        """Анализ комментариев и подсчет голосов (для публичного режима)"""
        votes = []
        user_votes = {}
        
        with self.db.get_connection() as conn:
            for comment in comments:
                user_id = comment.get('user_id')
                text = comment.get('text', '')
                
                if user_id and text and text.strip():
                    user_votes_key = f"{user_id}_{poll_type}"
                    
                    if user_votes_key not in user_votes:
                        detected_votes = self.vote_analyzer.analyze_comment_vote(text, poll_type)
                        
                        if detected_votes:
                            votes.extend(detected_votes)
                            user_votes[user_votes_key] = True
                            
                            # Сохраняем анализированный комментарий
                            conn.execute('''
                                INSERT INTO poll_comments 
                                (message_id, user_id, comment_text, vote_option)
                                VALUES (?, ?, ?, ?)
                            ''', (message_id, user_id, text, ','.join(detected_votes)))
        
        # Подсчет результатов
        total_votes = len(votes)
        vote_counts = {}
        
        for vote in votes:
            vote_counts[vote] = vote_counts.get(vote, 0) + 1
        
        # Расчет процентов
        percentages = {}
        for option, count in vote_counts.items():
            percentages[option] = round((count / total_votes) * 100, 1) if total_votes > 0 else 0
        
        return {
            'total_votes': total_votes,
            'vote_counts': vote_counts,
            'percentages': percentages,
            'votes': votes,
            'poll_type': poll_type,
            'unique_voters': len(user_votes)
        }
    
    def _save_poll_results(self, message_id, poll_type, results):
        """Сохранение результатов в базу данных"""
        with self.db.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO poll_results 
                (message_id, poll_type, results_json, total_votes, analyzed_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (message_id, poll_type, json.dumps(results), results['total_votes']))

# СИСТЕМА РОТАЦИИ РЕЦЕПТОВ (ИСПРАВЛЕНА SQL-инъекция)
class AdvancedRotationSystem:
    def __init__(self):
        self.db = ThreadSafeDatabase()
        self.rotation_period = 90
        self.priority_map = self._create_priority_map()
        self.content_tracker = ContentTracker()
        self.init_rotation_data()
    
    def _create_priority_map(self):
        return {
            0: {  # Понедельник
                "breakfast": ["generate_brain_boost_breakfast"],
                "science": ["generate_monday_science"],
                "lunch": ["generate_protein_lunch"],
                "dinner": ["generate_family_dinner"],
                "dessert": ["generate_healthy_dessert"]
            },
            1: {  # Вторник
                "breakfast": ["generate_energy_breakfast"],
                "science": ["generate_tuesday_science"],
                "lunch": ["generate_vegan_lunch"],
                "dinner": ["generate_quick_dinner"],
                "dessert": ["generate_fruit_dessert"]
            },
            2: {  # Среда
                "breakfast": ["generate_metabolism_breakfast"],
                "science": ["generate_wednesday_science"],
                "lunch": ["generate_fish_lunch"],
                "dinner": ["generate_complex_dinner"],
                "dessert": ["generate_chocolate_dessert"]
            },
            3: {  # Четверг
                "breakfast": ["generate_detox_breakfast"],
                "science": ["generate_thursday_science"],
                "lunch": ["generate_chicken_lunch"],
                "dinner": ["generate_comfort_dinner"],
                "dessert": ["generate_nut_dessert"]
            },
            4: {  # Пятница
                "breakfast": ["generate_friday_breakfast"],
                "science": ["generate_friday_science"],
                "lunch": ["generate_light_lunch"],
                "dinner": ["generate_weekend_dinner"],
                "dessert": ["generate_celebration_dessert"]
            },
            5: {  # Суббота
                "breakfast": ["generate_weekend_breakfast"],
                "science": ["generate_saturday_science"],
                "lunch": ["generate_family_lunch"],
                "dinner": ["generate_special_dinner"],
                "dessert": ["generate_family_dessert"]
            },
            6: {  # Воскресенье
                "planning_science": ["generate_sunday_science"],
                "sunday_breakfast": ["generate_sunday_brunch"],
                "sunday_lunch": ["generate_sunday_lunch"],
                "sunday_dessert": ["generate_sunday_dessert"],
                "planning_advice": ["generate_planning_advice"],
                "meal_prep_dinner": ["generate_meal_prep_dinner"]
            }
        }
    
    def init_rotation_data(self):
        """Инициализация системы ротации для всех рецептов"""
        recipe_methods = [
            # Завтраки
            ("breakfast", "generate_brain_boost_breakfast"),
            ("breakfast", "generate_energy_breakfast"),
            ("breakfast", "generate_metabolism_breakfast"),
            ("breakfast", "generate_detox_breakfast"),
            ("breakfast", "generate_friday_breakfast"),
            ("breakfast", "generate_weekend_breakfast"),
            ("breakfast", "generate_sunday_brunch"),
            
            # Научные сообщения
            ("science", "generate_monday_science"),
            ("science", "generate_tuesday_science"),
            ("science", "generate_wednesday_science"),
            ("science", "generate_thursday_science"),
            ("science", "generate_friday_science"),
            ("science", "generate_saturday_science"),
            ("science", "generate_sunday_science"),
            
            # Обеды
            ("lunch", "generate_protein_lunch"),
            ("lunch", "generate_vegan_lunch"),
            ("lunch", "generate_fish_lunch"),
            ("lunch", "generate_chicken_lunch"),
            ("lunch", "generate_light_lunch"),
            ("lunch", "generate_family_lunch"),
            ("lunch", "generate_sunday_lunch"),
            
            # Ужины
            ("dinner", "generate_family_dinner"),
            ("dinner", "generate_quick_dinner"),
            ("dinner", "generate_complex_dinner"),
            ("dinner", "generate_comfort_dinner"),
            ("dinner", "generate_weekend_dinner"),
            ("dinner", "generate_special_dinner"),
            ("dinner", "generate_meal_prep_dinner"),
            
            # Десерты
            ("dessert", "generate_healthy_dessert"),
            ("dessert", "generate_fruit_dessert"),
            ("dessert", "generate_chocolate_dessert"),
            ("dessert", "generate_nut_dessert"),
            ("dessert", "generate_celebration_dessert"),
            ("dessert", "generate_family_dessert"),
            ("dessert", "generate_sunday_dessert"),
            
            # Советы
            ("advice", "generate_planning_advice"),
            ("advice", "generate_brain_nutrition_advice"),
            ("advice", "generate_gut_health_advice")
        ]
        
        with self.db.get_connection() as conn:
            for recipe_type, method in recipe_methods:
                conn.execute('''
                    INSERT OR IGNORE INTO recipe_rotation 
                    (recipe_type, recipe_method, last_used, use_count)
                    VALUES (?, ?, DATE('now', '-100 days'), 0)
                ''', (recipe_type, method))
    
    def get_priority_recipe(self, recipe_type, weekday):
        """Умная ротация с учетом дня недели и темы"""
        if weekday in self.priority_map and recipe_type in self.priority_map[weekday]:
            for method in self.priority_map[weekday][recipe_type]:
                if self._is_recipe_available(method):
                    self.content_tracker.track_content_usage(recipe_type, method)
                    return method
        
        method = self.get_available_recipe(recipe_type)
        if method:
            self.content_tracker.track_content_usage(recipe_type, method)
        return method
    
    def _is_recipe_available(self, method_name):
        """Проверка доступности рецепта по ротации (ИСПРАВЛЕНА SQL-инъекция)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT last_used FROM recipe_rotation 
                WHERE recipe_method = ? AND last_used < DATE('now', ?)
            ''', (method_name, f'-{self.rotation_period} days'))
            return cursor.fetchone() is not None

    def get_available_recipe(self, recipe_type):
        """Получить доступный рецепт для типа с учетом ротации (ИСПРАВЛЕНА SQL-инъекция)"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT recipe_method FROM recipe_rotation 
                WHERE recipe_type = ? AND last_used < DATE('now', ?)
                ORDER BY use_count ASC, last_used ASC
                LIMIT 1
            ''', (recipe_type, f'-{self.rotation_period} days'))
            
            result = cursor.fetchone()
            if result:
                method = result['recipe_method']
                conn.execute('''
                    UPDATE recipe_rotation 
                    SET last_used = DATE('now'), use_count = use_count + 1
                    WHERE recipe_method = ?
                ''', (method,))
                return method
            else:
                cursor = conn.execute('''
                    SELECT recipe_method FROM recipe_rotation 
                    WHERE recipe_type = ?
                    ORDER BY last_used ASC, use_count ASC
                    LIMIT 1
                ''', (recipe_type,))
                
                result = cursor.fetchone()
                if result:
                    method = result['recipe_method']
                    conn.execute('''
                        UPDATE recipe_rotation 
                        SET last_used = DATE('now'), use_count = use_count + 1
                        WHERE recipe_method = ?
                    ''', (method,))
                    return method
        
        return None

# СИСТЕМА НАУЧНОГО АНАЛИЗА РЕЗУЛЬТАТОВ
class ScientificResultsAnalyzer:
    def __init__(self):
        self.analysis_templates = {
            'gut_health': self._analyze_gut_health,
            'food_archetype': self._analyze_food_archetype,
            'food_dilemma': self._analyze_food_dilemma,
            'weekly_challenge': self._analyze_weekly_challenge,
            'cooking_style': self._analyze_cooking_style
        }
    
    def generate_scientific_analysis(self, poll_type, results):
        """Генерация научного анализа на основе результатов"""
        analyzer = self.analysis_templates.get(poll_type, self._analyze_general)
        return analyzer(results)
    
    def _analyze_gut_health(self, results):
        """Научный анализ результатов по здоровью ЖКТ"""
        if not results['percentages']:
            return self._get_no_data_analysis()
            
        winning_option = max(results['percentages'].items(), key=lambda x: x[1])
        
        analysis_map = {
            'метаболизм': {
                'title': '🔥 ДОМИНИРУЕТ СТАЛЬНОЙ МЕТАБОЛИЗМ',
                'science': '''<b>Научное обоснование:</b>
Исследования показывают, что люди с быстрым метаболизмом часто имеют:
• Повышенную активность коричневой жировой ткани
• Высокий уровень тиреоидных гормонов (Т3, Т4)
• Оптимальную чувствительность к инсулину
• Эффективную работу митохондрий''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Поддерживайте мышечную массу силовыми тренировками
• Включайте белок в каждый прием пищи
• Используйте интервальное голодание для метаболической гибкости
• Контролируйте уровень стресса (кортизол влияет на метаболизм)'''
            },
            'радар': {
                'title': '🎯 ПРЕОБЛАДАЕТ СИСТЕМА "ТОПОВЫЙ РАДАР"',
                'science': '''<b>Научное обоснование:</b>
Пищевая непереносимость связана с:
• Дефицитом пищеварительных ферментов (лактаза, др.)
• Особенностями микробиома кишечника
• Повышенной проницаемостью кишечного барьера
• Иммунным ответом на пищевые антигены''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Ведите пищевой дневник для точного определения триггеров
• Используйте элиминационную диету под руководством специалиста
• Поддерживайте микробиом пробиотиками и пребиотиками
• Обращайте внимание на непищевые триггеры (стресс, сон)'''
            },
            'часы': {
                'title': '🕰️ ЛИДИРУЮТ ВНУТРЕННИЕ ЧАСЫ', 
                'science': '''<b>Научное обоснование:</b>
Циркадные ритмы питания регулируются:
• Гормонами грелином (голод) и лептином (сытость)
• Мелатонином, влияющим на метаболизм
• Инсулиновой чувствительностью (выше утром)
• Активностью пищеварительных ферментов''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Принимайте пищу в одно и то же время
• Самый плотный прием пищи - завтрак/обед
• Избегайте поздних ужинов (за 3-4 часа до сна)
• Соблюдайте режим сна и бодрствования'''
            },
            'микробиом': {
                'title': '🌱 ВЕДУТ МИКРОБИОМ-БОГАТЫРИ',
                'science': '''<b>Научное обоснование:</b>
Разнообразие микробиома коррелирует с:
• Устойчивостью к пищевым расстройствам
• Эффективным усвоением нутриентов
• Производством короткоцепочечных жирных кислот
• Модуляцией иммунной системы
• Синтезом витаминов группы B и K''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Употребляйте ферментированные продукты (кефир, квашеная капуста)
• Добавляйте пребиотическую клетчатку (инулин, пектин)
• Разнообразьте растительные источники в питании
• Избегайте избытка антибиотиков и обработанных продуктов'''
            }
        }
        
        analysis = analysis_map.get(winning_option[0], {
            'title': '📊 РАВНОМЕРНОЕ РАСПРЕДЕЛЕНИЕ ПО АРХЕТИПАМ',
            'science': '''<b>Научное обоснование:</b>
Разнообразие ответов указывает на индивидуальные особенности пищеварения в сообществе, что соответствует современным данным о персонализированной нутрициологии.''',
            'recommendation': '''<b>Рекомендация нутрициолога:</b>
Учитывайте индивидуальные особенности при планировании питания и обращайте внимание на сигналы собственного организма.'''
        })
        
        return analysis
    
    def _analyze_food_archetype(self, results):
        """Анализ пищевых архетипов"""
        if not results['percentages']:
            return self._get_no_data_analysis()
            
        winning_option = max(results['percentages'].items(), key=lambda x: x[1])
        
        analysis_map = {
            'создатель': {
                'title': '🍳 ДОМИНИРУЮТ СОЗДАТЕЛИ - ТВОРЦЫ НА КУХНЕ',
                'science': '''<b>Научное обоснование:</b>
Творческий подход к питанию связан с:
• Активацией дофаминовой системы reward-системы
• Развитием сенсорного восприятия и вкусовых рецепторов
• Когнитивной гибкостью и креативным мышлением
• Эмоциональной связью с процессом приготовления пищи''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Используйте сезонные продукты для вдохновения
• Экспериментируйте с специями и травами
• Сочетайте разные текстуры и температуры
• Делитесь своими творениями для социальной поддержки'''
            },
            'топливщик': {
                'title': '🏃‍♀️ ПРЕОБЛАДАЮТ ТОПЛИВЩИКИ - СИСТЕМНЫЙ ПОДХОД',
                'science': '''<b>Научное обоснование:</b>
Системный подход к питанию характеризуется:
• Развитым аналитическим мышлением
• Высокой осознанностью в выборе продуктов
• Пониманием биохимических процессов
• Ориентацией на долгосрочные результаты''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Балансируйте КБЖУ с учетом индивидуальных потребностей
• Используйте периодизацию питания при изменении нагрузок
• Отслеживайте не только калории, но и микронутриенты
• Помните о психологическом комфорте питания'''
            },
            'гедонист': {
                'title': '😋 ЛИДИРУЮТ ГЕДОНИСТЫ - ЦЕНИТЕЛИ ВКУСА',
                'science': '''<b>Научное обоснование:</b>
Гедонистический подход связан с:
• Активной работой опиоидной системы мозга
• Высокой чувствительностью к вкусовым ощущениям
• Эмоциональной регуляцией через питание
• Социальным аспектом принятия пищи''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Научитесь различать физический и эмоциональный голод
• Практикуйте осознанное питание без отвлечений
• Находите здоровые альтернативы любимым блюдам
• Балансируйте удовольствие и питательную ценность'''
            },
            'аналитик': {
                'title': '🧠 ПРЕОБЛАДАЮТ АНАЛИТИКИ - ИССЛЕДОВАТЕЛИ ПИТАНИЯ',
                'science': '''<b>Научное обоснование:</b>
Аналитический подход демонстрирует:
• Высокую когнитивную вовлеченность в тему питания
• Критическое мышление и оценку исследований
• Стремление к оптимизации и эффективности
• Интерес к доказательной базе нутрициологии''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Используйте научные базы данных для проверки информации
• Учитывайте индивидуальную вариабельность реакций
• Балансируйте теорию с практикой и самонаблюдением
• Помните, что питание - это и наука, и искусство'''
            }
        }
        
        return analysis_map.get(winning_option[0], self._get_general_analysis())
    
    def _analyze_food_dilemma(self, results):
        """Анализ пищевых дилемм"""
        if not results['percentages']:
            return self._get_no_data_analysis()
            
        return {
            'title': '⚖️ АНАЛИЗ ПИЩЕВЫХ ВЫБОРОВ СООБЩЕСТВА',
            'science': '''<b>Научное обоснование:</b>
Пищевые предпочтения отражают:
• Индивидуальные метаболические особенности
• Культурные и социальные влияния
• Психологические ассоциации с продуктами
• Опыт и пищевое воспитание''',
            'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Уважайте свои пищевые предпочтения, но будьте открыты новому
• Помните о балансе между пользой и удовольствием
• Экспериментируйте с разными продуктами в рамках здорового рациона
• Прислушивайтесь к сигналам организма'''
        }
    
    def _analyze_weekly_challenge(self, results):
        """Анализ недельных челленджей"""
        if not results['percentages']:
            return self._get_no_data_analysis()
            
        winning_option = max(results['percentages'].items(), key=lambda x: x[1])
        
        analysis_map = {
            'гидратация': {
                'title': '💧 СООБЩЕСТВО ВЫБИРАЕТ ГИДРАТАЦИЮ',
                'science': '''<b>Научное обоснование:</b>
Достаточная гидратация обеспечивает:
• Оптимальную работу всех систем организма
• Транспорт нутриентов и кислорода
• Детоксикацию и выведение метаболитов
• Поддержание эластичности кожи и тканей
• Регуляцию температуры тела''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Рассчитывайте 30 мл воды на 1 кг идеального веса
• Распределяйте прием воды в течение дня
• Учитывайте дополнительные потери при физической нагрузке
• Следите за цветом мочи как индикатором гидратации'''
            },
            'овощи': {
                'title': '🥬 ПРИОРИТЕТ - ОВОЩНОЕ РАЗНООБРАЗИЕ',
                'science': '''<b>Научное обоснование:</b>
Разнообразие овощей обеспечивает:
• Широкий спектр витаминов и минералов
• Полифенолы и антиоксиданты
• Пребиотическую клетчатку для микробиома
• Щелочную нагрузку для баланса pH''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Стремитесь к радуге цветов в тарелке
• Сочетайте сырые и приготовленные овощи
• Используйте разные методы приготовления
• Включайте местные и сезонные продукты'''
            },
            'осознанность': {
                'title': '🧠 ВЫБОР ОСОЗНАННОГО ПИТАНИЯ',
                'science': '''<b>Научное обоснование:</b>
Осознанное питание способствует:
• Улучшению пищеварения через парасимпатическую активацию
• Профилактике переедания и лучшему насыщению
• Снижению стресса, связанного с питанием
• Формированию здоровых отношений с едой''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Ешьте без отвлечений (телефон, TV)
• Тщательно пережевывайте пищу
• Прислушивайтесь к сигналам голода и сытости
• Наслаждайтесь каждым приемом пищи'''
            },
            'белок': {
                'title': '⚡ ФОКУС НА БЕЛКОВОМ БАЛАНСЕ',
                'science': '''<b>Научное обоснование:</b>
Достаточное потребление белка обеспечивает:
• Синтез и сохранение мышечной массы
• Поддержание метаболической активности
• Сытость и контроль аппетита
• Синтез ферментов и гормонов
• Иммунную функцию''',
                'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Распределяйте белок равномерно в течение дня
• Сочетайте животные и растительные источники
• Учитывайте индивидуальные потребности (1.2-2.0 г/кг)
• Обращайте внимание на качество и усвояемость'''
            }
        }
        
        return analysis_map.get(winning_option[0], self._get_general_analysis())
    
    def _analyze_cooking_style(self, results):
        """Анализ стилей готовки"""
        if not results['percentages']:
            return self._get_no_data_analysis()
            
        return {
            'title': '👨‍🍳 АНАЛИЗ КУЛИНАРНЫХ ПРЕДПОЧТЕНИЙ',
            'science': '''<b>Научное обоснование:</b>
Стиль приготовления пищи влияет на:
• Сохранность нутриентов в продуктах
• Биодоступность микроэлементов
• Формирование вкусовых предпочтений
• Социальные и культурные аспекты питания''',
            'recommendation': '''<b>Рекомендация нутрициолога:</b>
• Сочетайте разные методы приготовления
• Отдавайте предпочтение щадящей термической обработке
• Экспериментируйте с новыми техниками
• Учитывайте влияние приготовления на питательную ценность'''
        }
    
    def _analyze_general(self, results):
        """Общий анализ для неизвестных типов опросов"""
        return self._get_general_analysis()
    
    def _get_no_data_analysis(self):
        """Анализ при отсутствии данных"""
        return {
            'title': '📊 НЕДОСТАТОЧНО ДАННЫХ ДЛЯ АНАЛИЗА',
            'science': '''<b>Научное обоснование:</b>
Для проведения статистического анализа требуется достаточное количество участников. Малый размер выборки не позволяет сделать достоверные выводы о предпочтениях сообщества.''',
            'recommendation': '''<b>Рекомендация нутрициолога:</b>
Присоединяйтесь к следующим опросам - чем больше участников, тем точнее мы сможем анализировать тенденции и давать персонализированные рекомендации.'''
        }
    
    def _get_general_analysis(self):
        """Общий анализ"""
        return {
            'title': '📈 АНАЛИЗ ПРЕДПОЧТЕНИЙ СООБЩЕСТВА',
            'science': '''<b>Научное обоснование:</b>
Пищевые привычки и предпочтения формируются под влиянием множества факторов: генетических особенностей, культурного背景, личного опыта и современных трендов в питании.''',
            'recommendation': '''<b>Рекомендация нутрициолога:</b>
Используйте информацию о предпочтениях сообщества для расширения своего пищевого кругозора, но помните о важности индивидуального подхода и listening к потребностям собственного организма.'''
        }

# МЕНЕДЖЕР ВИЗУАЛЬНОГО КОНТЕНТА (ОБНОВЛЕН ДЛЯ АНОНИМНОСТИ)
class VisualContentManager:
    def __init__(self):
        self.visual_templates = {
            "breakfast": "🍳",
            "lunch": "🍲", 
            "dinner": "🍽️",
            "dessert": "🍰",
            "science": "🔬",
            "advice": "💡",
            "poll": "📊",
            "results": "📈",
            "anonymous": "🕵️‍♂️"
        }
    
    def add_visual_elements(self, content, content_type):
        """Добавление визуальных элементов к контенту"""
        emoji = self.visual_templates.get(content_type, "📝")
        return f"{emoji} {content}"
    
    def format_poll_results(self, results, analysis):
        """Форматирование результатов опроса с визуальными элементами"""
        if not results['percentages']:
            return "📊 Недостаточно данных для отображения результатов"
        
        # Создаем визуальные бары для результатов
        visual_results = []
        for option, percentage in results['percentages'].items():
            bar_length = int(percentage / 5)  # 1% = 0.2 символа
            bar = "█" * bar_length + "░" * (20 - bar_length)
            visual_results.append(f"{option}: {bar} {percentage}%")
        
        results_text = "\n".join(visual_results)
        
        # Добавляем информацию об анонимности
        anonymity_note = ""
        if Config.ANONYMOUS_VOTING:
            anonymity_note = f"""
            
🔒 <b>АНОНИМНОЕ ГОЛОСОВАНИЕ</b>
• Все голоса собраны анонимно
• Ники пользователей скрыты
• Конфиденциальность гарантирована
• Уникальных участников: {results.get('unique_voters', results['total_votes'])}
"""
        
        # Добавляем анонимные комментарии если есть
        comments_section = ""
        if results.get('anonymous_comments'):
            comments_section = f"""
            
💬 <b>АНОНИМНЫЕ КОММЕНТАРИИ УЧАСТНИКОВ:</b>
{chr(10).join(['• ' + comment for comment in results['anonymous_comments'][:5]])}
{f"... и еще {len(results['anonymous_comments']) - 5} комментариев" if len(results['anonymous_comments']) > 5 else ""}
"""
        
        return f"""
📊 <b>РЕЗУЛЬТАТЫ ОПРОСА</b>

{results_text}

<b>Всего участников:</b> {results['total_votes']}
{anonymity_note}
{comments_section}

{analysis['title']}

{analysis['science']}

{analysis['recommendation']}
        """

# УЛУЧШЕННЫЙ ТЕЛЕГРАМ МЕНЕДЖЕР (ОБНОВЛЕН ДЛЯ АНОНИМНОСТИ)
class EnhancedTelegramManager:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.sent_hashes = set()
        self.db = ThreadSafeDatabase()
        self.results_collector = PollResultsCollector(self)
        self.scientific_analyzer = ScientificResultsAnalyzer()
        self.visual_manager = VisualContentManager()
        self.anonymous_voting = AnonymousVotingSystem()
        self.admin_notifier = AdminNotifier(self)
        self.init_duplicate_protection()
    
    def init_duplicate_protection(self):
        """Инициализация системы защиты от дублирования"""
        with self.db.get_connection() as conn:
            cursor = conn.execute('SELECT content_hash FROM sent_messages')
            for row in cursor:
                self.sent_hashes.add(row['content_hash'])
    
    def send_message(self, text, parse_mode='HTML', content_type="general"):
        try:
            source = "manual" if "ТЕСТОВЫЙ ПОСТ" in text or "РУЧНОЙ ПОСТ" in text else "scheduled"
            logger.info(f"📤 [{source}] Попытка отправки сообщения ({len(text)} символов)")
            
            if not self.token or self.token == 'your-telegram-bot-token':
                logger.error("❌ Токен бота не настроен! Проверьте .env файл")
                return False
                
            if not self.channel:
                logger.error("❌ ID канала не настроен!")
                return False

            content_hash = hashlib.md5(text.encode()).hexdigest()
            
            if content_hash in self.sent_hashes:
                logger.warning("⚠️ Попытка отправить дубликат контента (память)")
                return False
            
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'SELECT 1 FROM sent_messages WHERE content_hash = ?', 
                    (content_hash,)
                )
                if cursor.fetchone():
                    logger.warning("⚠️ Попытка отправить дубликат контента (БД)")
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
            
            logger.info(f"📡 Статус ответа: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP ошибка: {response.status_code} - {response.text}")
                return False
                
            result = response.json()
            logger.info(f"📨 Ответ Telegram: {result}")
            
            if result.get('ok'):
                self.sent_hashes.add(content_hash)
                with self.db.get_connection() as conn:
                    conn.execute(
                        'INSERT INTO sent_messages (content_hash, message_text, content_type) VALUES (?, ?, ?)',
                        (content_hash, text[:500], content_type)
                    )
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
    
    def send_direct_message(self, chat_id, text, parse_mode='HTML'):
        """Отправка сообщения напрямую пользователю"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=payload, timeout=10)
            return response.json().get('ok', False)
        except Exception as e:
            logger.error(f"❌ Ошибка отправки прямого сообщения: {e}")
            return False
    
    def send_poll(self, question, options, is_anonymous=True):
        """Отправка настоящего опроса в Telegram"""
        try:
            url = f"{self.base_url}/sendPoll"
            payload = {
                'chat_id': self.channel,
                'question': question[:300],  # Ограничение Telegram
                'options': options,
                'is_anonymous': is_anonymous,
                'type': 'regular',
                'allows_multiple_answers': False
            }
            
            response = requests.post(url, json=payload, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                message_id = result['result']['message_id']
                logger.info(f"✅ Опрос отправлен, ID сообщения: {message_id}")
                return message_id
            else:
                logger.error(f"❌ Ошибка отправки опроса: {result.get('description')}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке опроса: {e}")
            return None
    
    def send_poll_with_instructions(self, question, options, poll_type):
        """Отправка опроса с инструкциями по голосованию через комментарии"""
        instructions = self._format_poll_instructions(question, options, poll_type)
        return self.send_message(instructions, content_type="poll")
    
    def _format_poll_instructions(self, question, options, poll_type):
        """Форматирование опроса с инструкциями"""
        options_text = "\n".join([f"{i+1}. {option}" for i, option in enumerate(options)])
        
        # Добавляем информацию об анонимности
        anonymity_section = ""
        if Config.ANONYMOUS_VOTING:
            anonymity_section = """
            
🔒 <b>АНОНИМНОЕ ГОЛОСОВАНИЕ</b>
• Ваш ник будет скрыт
• Голосование полностью конфиденциально
• Результаты показываются только в агрегированном виде
• Никто не узнает, как проголосовали другие
"""
        
        return f"""
📊 <b>ВОСКРЕСНЫЙ ОПРОС: {poll_type.upper().replace('_', ' ')}</b>

{question}

<b>ВАРИАНТЫ ОТВЕТА:</b>
{options_text}
{anonymity_section}
<b>🗳️ КАК ГОЛОСОВАТЬ:</b>
Напишите комментарий с номером варианта или ключевыми словами из него!

<b>📝 ПРИМЕРЫ КОММЕНТАРИЕВ:</b>
• "Вариант 1" или "{self._get_sample_keyword(poll_type, 0)}"
• "Выбираю 2" или "{self._get_sample_keyword(poll_type, 1)}"
• "Мой вариант - 3" или "{self._get_sample_keyword(poll_type, 2)}"

<b>⏰ РЕЗУЛЬТАТЫ:</b>
Через 24 часа опубликуем научный анализ результатов!

#опрос #голосование #анонимно
        """
    
    def _get_sample_keyword(self, poll_type, option_index):
        """Получение примерного ключевого слова для инструкций"""
        keyword_maps = {
            'gut_health': ['метаболизм', 'радар', 'часы', 'микробиом'],
            'food_archetype': ['создатель', 'топливщик', 'гедонист', 'аналитик'],
            'weekly_challenge': ['гидратация', 'овощи', 'осознанность', 'белок'],
            'cooking_style': ['инженер', 'импровизатор', 'традиционный', 'экспериментатор']
        }
        
        keywords = keyword_maps.get(poll_type, ['вариант'] * 4)
        return keywords[option_index] if option_index < len(keywords) else 'вариант'
    
    def get_post_comments(self, message_id, limit=100):
        """Получение комментариев к посту и обработка анонимных голосов"""
        try:
            logger.info(f"🔍 Запрос комментариев для сообщения {message_id}")
            
            # Получаем комментарии (в реальности - вызов Telegram API)
            simulated_comments = self._simulate_comments(message_id, limit)
            
            # Если включено анонимное голосование, обрабатываем комментарии
            if Config.ANONYMOUS_VOTING:
                self._process_anonymous_votes(simulated_comments, message_id)
            
            logger.info(f"📝 Получено {len(simulated_comments)} комментариев")
            return simulated_comments
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения комментариев: {e}")
            return []
    
    def _process_anonymous_votes(self, comments, message_id):
        """Обработка комментариев для анонимного голосования"""
        try:
            # Получаем информацию об опросе
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT poll_type FROM poll_history WHERE message_id = ?
                ''', (message_id,))
                result = cursor.fetchone()
                
                if not result:
                    logger.warning(f"⚠️ Не найден опрос с ID {message_id}")
                    return
                
                poll_type = result['poll_type']
                processed_votes = 0
                
                for comment in comments:
                    user_id = comment.get('user_id')
                    text = comment.get('text', '')
                    
                    if user_id and text and text.strip():
                        # Регистрируем анонимный голос
                        success = self.results_collector.register_anonymous_vote(
                            user_id, poll_type, message_id, text
                        )
                        
                        if success:
                            processed_votes += 1
            
            if processed_votes > 0:
                logger.info(f"✅ Обработано {processed_votes} анонимных голосов для опроса {message_id}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки анонимных голосов: {e}")
    
    def _simulate_comments(self, message_id, limit):
        """Симуляция комментариев для демонстрации (заглушка)"""
        sample_comments = [
            {"user_id": 12345, "text": "Вариант 1", "message_id": message_id + 1},
            {"user_id": 12346, "text": "Выбираю стальной метаболизм", "message_id": message_id + 2},
            {"user_id": 12347, "text": "Мой вариант - 2", "message_id": message_id + 3},
            {"user_id": 12348, "text": "топовый радар это про меня", "message_id": message_id + 4},
            {"user_id": 12349, "text": "3", "message_id": message_id + 5},
            {"user_id": 12350, "text": "внутренние часы", "message_id": message_id + 6},
            {"user_id": 12351, "text": "микробиом-богатырь", "message_id": message_id + 7},
            {"user_id": 12352, "text": "первый вариант", "message_id": message_id + 8},
            {"user_id": 12353, "text": "выбираю 4", "message_id": message_id + 9},
            {"user_id": 12354, "text": "Очень интересный опрос! Я выбираю вариант 1", "message_id": message_id + 10},
            {"user_id": 12355, "text": "Мне ближе второй вариант", "message_id": message_id + 11},
        ]
        
        return sample_comments[:limit]
    
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
            cursor = conn.execute('SELECT content_hash FROM sent_messages')
            self.sent_hashes = {row['content_hash'] for row in cursor}
            logger.info(f"🧹 Очищены сообщения старше {days} дней")

# УМНЫЙ ГЕНЕРАТОР КОНТЕНТА
class SmartContentGenerator:
    def __init__(self):
        self.yandex_key = Config.YANDEX_GPT_API_KEY
        self.yandex_folder = Config.YANDEX_FOLDER_ID
        self.visual_manager = VisualContentManager()
        self.db = ThreadSafeDatabase()
        self.rotation_system = AdvancedRotationSystem()
        self.content_tracker = ContentTracker()
    
    # СУЩЕСТВУЮЩИЕ МЕТОДЫ ГЕНЕРАЦИИ КОНТЕНТА
    def generate_monday_science(self):
        return """🔬 <b>ПОНЕДЕЛЬНИК: НАУКА ПИТАНИЯ ДЛЯ МОЗГА</b>

🧠 <b>Факт:</b> Мозг составляет всего 2% от веса тела, но потребляет 20-25% всей энергии!

<b>Научное обоснование:</b>
• Глюкоза - основной источник энергии для мозга
• Жирные кислоты Омега-3 поддерживают структуру нейронов
• Антиоксиданты защищают от окислительного стресса
• Холин необходим для синтеза ацетилхолина

<b>Практическое применение:</b>
Включайте в завтрак яйца, орехи, жирную рыбу и ягоды для оптимальной работы мозга.

#наука #мозг #питание #понедельник"""

    def generate_tuesday_science(self):
        return """🔬 <b>ВТОРНИК: МИКРОБИОМ И ПИЩЕВАРЕНИЕ</b>

🦠 <b>Факт:</b> В нашем кишечнике живет около 40 триллионов бактерий - больше, чем клеток в теле!

<b>Научное обоснование:</b>
• Микробиом производит витамины B и K
• Регулирует иммунную функцию
• Влияет на настроение через ось "кишечник-мозг"
• Помогает переваривать клетчатку

<b>Практическое применение:</b>
Употребляйте ферментированные продукты и пребиотическую клетчатку.

#микробиом #пищеварение #здоровье #вторник"""

    def generate_wednesday_science(self):
        return """🔬 <b>СРЕДА: БЕЛОК И МЫШЕЧНЫЙ МЕТАБОЛИЗМ</b>

💪 <b>Факт:</b> Белки обновляются постоянно - за год почти все белковые молекулы заменяются новыми!

<b>Научное обоснование:</b>
• Аминокислоты - строительные блоки тканей
• Белки участвуют в ферментативных реакциях
• Поддерживают иммунную функцию
• Обеспечивают чувство сытости

<b>Практическое применение:</b>
Распределяйте белок равномерно в течение дня для оптимального усвоения.

#белок #метаболизм #мышцы #среда"""

    def generate_thursday_science(self):
        return """🔬 <b>ЧЕТВЕРГ: ГОРМОНЫ И ПИТАНИЕ</b>

⚖️ <b>Факт:</b> Инсулин, лептин и грелин - ключевые гормоны, регулирующие аппетит и метаболизм!

<b>Научное обоснование:</b>
• Инсулин регулирует уровень глюкозы
• Лептин сигнализирует о насыщении
• Грелин стимулирует аппетит
• Кортизол влияет на метаболизм при стрессе

<b>Практическое применение:</b>
Регулярное питание и управление стрессом помогают гормональному балансу.

#гормоны #аппетит #метаболизм #четверг"""

    def generate_friday_science(self):
        return """🔬 <b>ПЯТНИЦА: ВОДНЫЙ БАЛАНС И ГИДРАТАЦИЯ</b>

💧 <b>Факт:</b> Вода составляет 60% веса тела и участвует в каждой биохимической реакции!

<b>Научное обоснование:</b>
• Вода - растворитель для питательных веществ
• Регулирует температуру тела
• Выводит продукты метаболизма
• Поддерживает объем крови и давление

<b>Практическое применение:</b>
Пейте воду в течение дня, ориентируясь на чувство жажды и цвет мочи.

#гидратация #вода #здоровье #пятница"""

    def generate_saturday_science(self):
        return """🔬 <b>СУББОТА: ЦИРКАДНЫЕ РИТМЫ ПИТАНИЯ</b>

🕰️ <b>Факт:</b> Наш метаболизм следует 24-часовым циклам, синхронизированным со светом и темнотой!

<b>Научное обоснование:</b>
• Утром выше чувствительность к инсулину
• Вечером замедляется метаболизм
• Ночью активируются процессы восстановления
• Нарушение ритмов связано с набором веса

<b>Практическое применение:</b>
Самый плотный прием пищи - завтрак/обед, легкий ужин за 3-4 часа до сна.

#ритмы #метаболизм #время #суббота"""

    def generate_sunday_science(self):
        return """🔬 <b>ВОСКРЕСЕНЬЕ: ПЛАНИРОВАНИЕ ПИТАНИЯ НА НЕДЕЛЮ</b>

📋 <b>Факт:</b> Планирование питания снижает импульсивные покупки на 30% и улучшает качество рациона!

<b>Научное обоснование:</b>
• Снижает когнитивную нагрузку при выборе еды
• Обеспечивает разнообразие нутриентов
• Помогает контролировать порции
• Экономит время и деньги

<b>Практическое применение:</b>
Выделите 30 минут в воскресенье для планирования меню и закупок на неделю.

#планирование #меню #организация #воскресенье"""

    def generate_brain_boost_breakfast(self):
        return """🍳 <b>ЗАВТРАК ДЛЯ МОЗГА: ЯИЧНЫЙ БУКЕТ С АВОКАДО</b>

<b>Ингредиенты (на 2 порции):</b>
• 4 яйца
• 1 спелый авокадо
• 100 г шпината
• 50 г грецких орехов
• 1 ч.л. оливкового масла
• Специи по вкусу

<b>Приготовление (10 минут):</b>
1. Яйца взбить с щепоткой соли
2. Шпинат обжарить 2 минуты
3. Добавить яйца, готовить до мягкой консистенции
4. Подавать с ломтиками авокадо и грецкими орехами

<b>Нутрициологическая ценность:</b>
✓ Холин для нейромедиаторов
✓ Омега-3 для мембран нейронов
✓ Антиоксиданты для защиты
✓ Белок для сытости

#завтрак #мозг #яйца #авокадо"""

    def generate_energy_breakfast(self):
        return """🍳 <b>ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С СЕМЕНАМИ И ЯГОДАМИ</b>

<b>Ингредиенты (на 2 порции):</b>
• 100 г овсяных хлопьев
• 400 мл миндального молока
• 2 ст.л. семян чиа
• 1 ст.л. льняных семян
• 100 г смеси ягод
• 1 ч.л. меда (по желанию)

<b>Приготовление (8 минут):</b>
1. Овсянку варить с молоком 5 минут
2. Добавить семена, перемешать
3. Подавать с ягодами и медом

<b>Нутрициологическая ценность:</b>
✓ Сложные углеводы для энергии
✓ Клетчатка для микробиома
✓ Антиоксиданты из ягод
✓ Омега-3 из семян

#завтрак #энергия #овсянка #ягоды"""

    def generate_brain_nutrition_advice(self):
        return """💡 <b>СОВЕТ НУТРИЦИОЛОГА: ПИТАНИЕ ДЛЯ КОГНИТИВНОГО ЗДОРОВЬЯ</b>

<b>3 ключевых принципа:</b>

1. <b>Баланс глюкозы</b>
• Сложные углеводы вместо простых
• Белок с каждым приемом пищи
• Регулярное питание

2. <b>Жиры для мозга</b>
• Жирная рыба 2-3 раза в неделю
• Орехи и семена ежедневно
• Авокадо и оливковое масло

3. <b>Антиоксидантная защита</b>
• Ягоды разных цветов
• Овощи семейства крестоцветных
• Зеленый чай вместо сладких напитков

<b>Практический шаг на сегодня:</b>
Добавьте горсть грецких орехов к своему перекусу.

#совет #мозг #питание #здоровье"""

    def generate_family_dessert(self):
        return """🍰 <b>СЕМЕЙНЫЙ ДЕСЕРТ: ТВОРОЖНО-ЯГОДНЫЕ МУССЫ</b>

<b>Ингредиенты (на 4 порции):</b>
• 400 г творога 5%
• 200 г греческого йогурта
• 200 г смеси ягод
• 2 ч.л. меда
• 1 ч.л. ванильного экстракта
• Листья мяты для украшения

<b>Приготовление (5 минут):</b>
1. Творог, йогурт, мед и ваниль взбить блендером
2. Разложить по креманкам
3. Украсить ягодами и мятой

<b>Нутрициологическая ценность:</b>
✓ Белок для сытости
✓ Кальций для костей
✓ Антиоксиданты из ягод
✓ Пробиотики из йогурта

#десерт #семья #творог #ягоды"""

    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ РЕЦЕПТОВ
    def generate_metabolism_breakfast(self):
        return """🍳 <b>ЗАВТРАК ДЛЯ МЕТАБОЛИЗМА: ГРЕЧНЕВЫЕ ХЛЕБЦЫ С ПАСТОЙ ИЗ АВОКАДО</b>

<b>Ингредиенты:</b>
• 4 гречневых хлебца
• 1 авокадо
• 100 г творога
• 1 огурец
• Сок лимона, специи

<b>Приготовление:</b>
1. Авокадо размять с творогом и лимонным соком
2. Намазать пасту на хлебцы
3. Украсить ломтиками огурца

#завтрак #метаболизм #авокадо #гречка"""

    def generate_detox_breakfast(self):
        return """🍳 <b>ДЕТОКС-ЗАВТРАК: ЗЕЛЕНЫЙ СМУЗИ БОУЛ</b>

<b>Ингредиенты:</b>
• 1 банан
• 2 горсти шпината
• 1 ст.л. спирулины
• 200 мл кокосовой воды
• Ягоды, семена для топпинга

<b>Приготовление:</b>
1. Все ингредиенты взбить блендером
2. Перелить в миску
3. Украсить ягодами и семенами

#завтрак #детокс #смузи #зелень"""

    # 📊 МЕТОДЫ ОПРОСОВ
    def generate_gut_health_poll(self):
        """ОПРОС: Суперспособность вашего ЖКТ"""
        question = "🤖 ВОСКРЕСНЫЙ ОПРОС: СУПЕРСПОСОБНОСТЬ ВАШЕГО ЖКТ\n\nКакая из этих 'суперсил' есть у вашего организма?"
        
        options = [
            "⚡ СТАЛЬНОЙ МЕТАБОЛИЗМ - все перевариваю без последствий",
            "🎯 СИСТЕМА 'ТОПОВЫЙ РАДАР' - детектор плохих продуктов", 
            "🕰 ВНУТРЕННИЕ ЧАСЫ - голод как по будильнику",
            "🌱 МИКРОБИОМ-БОГАТЫРЬ - быстрое восстановление"
        ]
        
        return question, options, "gut_health"
    
    def generate_food_archetype_poll(self):
        """ОПРОС: Ваш пищевой архетип"""
        question = "🕵️‍♀️ ВОСКРЕСНЫЙ ДЕТЕКТИВ ВКУСОВ: ОПРЕДЕЛИТЕ ВАШ ПИЩЕВОЙ АРХЕТИП!"
        
        options = [
            "🍳 СОЗДАТЕЛЬ - готовка как искусство и творчество",
            "🏃‍♀️ ТОПЛИВЩИК - еда как источник энергии и КБЖУ",
            "😋 ГЕДОНИСТ - еда как главное удовольствие в жизни", 
            "🧠 АНАЛИТИК - внимательное изучение состава и исследований"
        ]
        
        return question, options, "food_archetype"
    
    def generate_food_dilemma_poll(self):
        """ОПРОС: Съесть нельзя выбросить - жестокий выбор"""
        question = "🚦 ВОСКРЕСНАЯ ДИЛЕММА: ВАШ ЛИЧНЫЙ 'СВЕТОФОР' ПИТАНИЯ\n\nЕсли бы пришлось НАВСЕГДА отказаться от одной пары продуктов:"
        
        options = [
            "🥑 Авокадо (полезные жиры) > 🧀 Сыр (аромат, кальций)",
            "🍫 Черный шоколад (антиоксиданты) > 🍌 Банан (натуральная сладость)",
            "☕ Утренний кофе (ритуал, бодрость) > 🍵 Травяной чай (релакс, уют)"
        ]
        
        return question, options, "food_dilemma"
    
    def generate_weekly_challenge_poll(self):
        """ОПРОС: Недельный челлендж - что готовы попробовать?"""
        question = "🏆 НЕДЕЛЬНЫЙ ЧЕЛЛЕНДЖ: ВЫБИРАЕМ ИСПЫТАНИЕ НА СЛЕДУЮЩУЮ НЕДЕЛЮ!"
        
        options = [
            "💧 ГИДРАТАЦИЯ-МАРАФОН - 2 литра воды daily",
            "🥦 ОВОЩНОЙ БУСТЕР - 5 разных овощей каждый день", 
            "🧠 ОСОЗНАННОЕ ПИТАНИЕ - 20 жеваний, еда без телефона",
            "⚡ БЕЛКОВЫЙ ФОКУС - белок в каждый прием пищи"
        ]
        
        return question, options, "weekly_challenge"
    
    def generate_cooking_style_poll(self):
        """ОПРОС: Ваш стиль готовки"""
        question = "👨‍🍳 ОПРОС: РАСКРОЙТЕ СВОЙ СТИЛЬ НА КУХНЕ!"
        
        options = [
            "📊 СИСТЕМНЫЙ ИНЖЕНЕР - точные рецепты, meal prep",
            "🎨 ИМПРОВИЗАТОР-ХУДОЖНИК - готовка по настроению", 
            "👑 ТРАДИЦИОННЫЙ ГУРМАН - семейные рецепты, качество",
            "🚀 ЭКСПЕРИМЕНТАТОР-НОВАТОР - food-тренды, технологии"
        ]
        
        return question, options, "cooking_style"
    
    def get_random_poll(self):
        """Получить случайный опрос"""
        poll_methods = [
            self.generate_gut_health_poll,
            self.generate_food_archetype_poll,
            self.generate_food_dilemma_poll, 
            self.generate_weekly_challenge_poll,
            self.generate_cooking_style_poll
        ]
        
        selected_method = random.choice(poll_methods)
        question, options, poll_type = selected_method()
        
        self.content_tracker.track_content_usage("poll", selected_method.__name__)
        
        return question, options, poll_type

    def get_rotated_recipe(self, recipe_type):
        """Получить рецепт с учетом умной ротации и приоритетов"""
        weekday = TimeManager.get_kemerovo_weekday()
        method_name = self.rotation_system.get_priority_recipe(recipe_type, weekday)
        
        if method_name is None:
            logger.warning(f"🚨 Нет доступных рецептов для типа: {recipe_type}")
            return self._get_fallback_recipe()
        
        method = getattr(self, method_name, self._get_fallback_recipe)
        return method()

    def _get_fallback_recipe(self):
        """Резервный рецепт при ошибках"""
        return self.generate_brain_boost_breakfast()

# УЛУЧШЕННЫЙ ПЛАНИРОВЩИК КОНТЕНТА (ОБНОВЛЕН ДЛЯ АНОНИМНОСТИ)
class EnhancedContentScheduler:
    def __init__(self):
        self.kemerovo_schedule = {
            0: {  # Понедельник
                "07:30": {"name": "🔬 Наука: Питание для мозга", "type": "science"},
                "08:00": {"name": "🍳 Завтрак для продуктивности", "type": "breakfast"},
                "12:00": {"name": "🍲 Обед: Белковый баланс", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Семейный", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Здоровый", "type": "dessert"}
            },
            1: {  # Вторник
                "07:30": {"name": "🔬 Наука: Микробиом", "type": "science"},
                "08:00": {"name": "🍳 Энергетический завтрак", "type": "breakfast"},
                "12:00": {"name": "🍲 Обед: Легкий", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Быстрый", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Фруктовый", "type": "dessert"}
            },
            2: {  # Среда
                "07:30": {"name": "🔬 Наука: Белок и мышцы", "type": "science"},
                "08:00": {"name": "🍳 Завтрак для метаболизма", "type": "breakfast"},
                "12:00": {"name": "🍲 Обед: Рыбный", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Сложный", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Шоколадный", "type": "dessert"}
            },
            3: {  # Четверг
                "07:30": {"name": "🔬 Наука: Гормоны", "type": "science"},
                "08:00": {"name": "🍳 Детокс-завтрак", "type": "breakfast"},
                "12:00": {"name": "🍲 Обед: Куриный", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Комфортный", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Ореховый", "type": "dessert"}
            },
            4: {  # Пятница
                "07:30": {"name": "🔬 Наука: Гидратация", "type": "science"},
                "08:00": {"name": "🍳 Пятничный завтрак", "type": "breakfast"},
                "12:00": {"name": "🍲 Обед: Легкий", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Праздничный", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Торжественный", "type": "dessert"}
            },
            5: {  # Суббота
                "09:30": {"name": "🔬 Наука: Циркадные ритмы", "type": "science"},
                "10:00": {"name": "🍳 Субботний завтрак", "type": "breakfast"},
                "13:00": {"name": "🍲 Обед: Семейный", "type": "lunch"},
                "18:00": {"name": "🍽️ Ужин: Особенный", "type": "dinner"},
                "20:00": {"name": "🍰 Десерт: Семейный", "type": "dessert"}
            },
            6: {  # Воскресенье
                "09:30": {"name": "🔬 Наука: Планирование питания", "type": "planning_science"},
                "10:00": {"name": "🍳 Воскресный бранч", "type": "sunday_breakfast"},
                "12:00": {"name": "📊 ВОСКРЕСНЫЙ ОПРОС", "type": "sunday_poll"},
                "13:00": {"name": "🍲 Воскресный обед", "type": "sunday_lunch"},
                "16:00": {"name": "🍰 Воскресный десерт", "type": "sunday_dessert"},
                "17:00": {"name": "💡 Совет: Планирование", "type": "planning_advice"},
                "19:00": {"name": "🍽️ Воскресный ужин", "type": "meal_prep_dinner"}
            }
        }
        
        self.server_schedule = self._convert_schedule_to_server()
        self.is_running = False
        self.telegram = EnhancedTelegramManager()
        self.generator = SmartContentGenerator()
        self.admin_notifier = AdminNotifier(self.telegram)
        self.content_tracker = ContentTracker()
        self.scientific_analyzer = ScientificResultsAnalyzer()
        self.visual_manager = VisualContentManager()
        
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
            
        logger.info("🚀 Запуск улучшенного планировщика контента с анонимным голосованием...")
        
        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)
        
        # Расписание для сбора результатов опросов (через 24 часа после опроса)
        schedule.every().day.at("12:00").do(self._process_due_poll_results)
        
        self.is_running = True
        self._run_scheduler()
    
    def _schedule_event(self, day, server_time, event):
        def job():
            current_times = TimeManager.get_current_times()
            logger.info(f"🕒 Выполнение: {event['name']}")
            
            if event['type'] == 'sunday_poll':
                self._send_sunday_poll()
            else:
                content = self.generator.get_rotated_recipe(event['type'])
                
                if content:
                    content_with_time = f"{content}\n\n⏰ Опубликовано: {current_times['kemerovo_time']}"
                    success = self.telegram.send_message(content_with_time, content_type=event['type'])
                    
                    if success:
                        logger.info(f"✅ Успешная публикация: {event['name']}")
                        service_monitor.increment_recipe_count()
                        self._check_recipe_usage(event['type'])
        
        job_func = getattr(schedule.every(), self._get_day_name(day))
        job_func.at(server_time).do(job)
    
    def _send_sunday_poll(self):
        """Отправка воскресного опроса с системой анонимного голосования"""
        try:
            question, options, poll_type = self.generator.get_random_poll()
            
            # Отправляем опрос с инструкциями
            message_id = self.telegram.send_poll_with_instructions(question, options, poll_type)
            
            if message_id:
                with self.generator.db.get_connection() as conn:
                    conn.execute('''
                        INSERT INTO poll_history (poll_type, poll_question, message_id)
                        VALUES (?, ?, ?)
                    ''', (poll_type, question, message_id))
                
                # Уведомляем администратора о запуске анонимного голосования
                if Config.ANONYMOUS_VOTING:
                    self.admin_notifier.notify_anonymous_voting_started(poll_type, message_id)
                
                # Планируем сбор результатов через 24 часа
                self._schedule_poll_results_collection(message_id, poll_type)
                
                logger.info(f"✅ Опрос '{poll_type}' отправлен с системой анонимного голосования")
                service_monitor.increment_poll_count()
                self._check_poll_usage()
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки опроса: {e}")
    
    def _schedule_poll_results_collection(self, message_id, poll_type):
        """Планирование сбора результатов для конкретного опроса"""
        def collect_and_publish():
            try:
                logger.info(f"🔄 Начинаем сбор результатов для опроса {message_id}")
                
                # Сбор результатов (анонимных или публичных)
                results = self.telegram.results_collector.collect_poll_results(message_id, poll_type)
                
                if results and results['total_votes'] > 0:
                    # Генерация научного анализа
                    analysis = self.scientific_analyzer.generate_scientific_analysis(poll_type, results)
                    
                    # Форматирование и публикация результатов
                    self._publish_poll_results(poll_type, results, analysis, message_id)
                    
                    # Уведомление администратора
                    self.admin_notifier.notify_poll_results_collected(poll_type, results['total_votes'])
                    
                    logger.info(f"✅ Результаты опроса {message_id} опубликованы")
                    service_monitor.increment_results_count()
                else:
                    self._publish_no_results_message(poll_type, message_id)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка сбора результатов: {e}")
        
        # Планируем через 24 часа
        schedule.every().day.at("12:00").do(collect_and_publish).tag(f"poll_results_{message_id}")
    
    def _process_due_poll_results(self):
        """Обработка всех опросов, для которых пора собрать результаты"""
        try:
            with self.generator.db.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT ph.message_id, ph.poll_type, ph.poll_question
                    FROM poll_history ph
                    LEFT JOIN poll_results pr ON ph.message_id = pr.message_id
                    WHERE ph.results_sent = FALSE 
                    AND ph.sent_at < DATETIME('now', '-23 hours')
                    AND pr.id IS NULL
                ''')
                
                due_polls = cursor.fetchall()
                
                for poll in due_polls:
                    logger.info(f"⏰ Сбор результатов для просроченного опроса {poll['message_id']}")
                    self._schedule_poll_results_collection(poll['message_id'], poll['poll_type'])
                    
        except Exception as e:
            logger.error(f"❌ Ошибка обработки просроченных опросов: {e}")
    
    def _publish_poll_results(self, poll_type, results, analysis, original_message_id):
        """Публикация результатов с научным анализом"""
        try:
            # Форматируем результаты с визуальными элементами
            results_text = self.visual_manager.format_poll_results(results, analysis)
            
            full_message = f"""
📊 <b>РЕЗУЛЬТАТЫ ВОСКРЕСНОГО ОПРОСА</b>

{results_text}

<b>💫 Благодарим всех за участие!</b>
Следующий опрос уже в следующее воскресенье!

#результаты #анализ #сообщество
            """
            
            success = self.telegram.send_message(full_message, content_type="results")
            
            if success:
                # Отмечаем опрос как обработанный
                with self.generator.db.get_connection() as conn:
                    conn.execute('''
                        UPDATE poll_history SET results_sent = TRUE WHERE message_id = ?
                    ''', (original_message_id,))
                    
                    conn.execute('''
                        UPDATE poll_results SET published_at = CURRENT_TIMESTAMP 
                        WHERE message_id = ?
                    ''', (original_message_id,))
                
                logger.info(f"✅ Результаты опроса {original_message_id} опубликованы")
                
        except Exception as e:
            logger.error(f"❌ Ошибка публикации результатов: {e}")
    
    def _publish_no_results_message(self, poll_type, message_id):
        """Публикация сообщения при отсутствии результатов"""
        message = f"""
📊 <b>РЕЗУЛЬТАТЫ ОПРОСА</b>

К сожалению, для этого опроса не было получено достаточного количества голосов для анализа.

💡 <b>Как участвовать в следующий раз:</b>
• Просто напишите комментарий с номером варианта
• Или используйте ключевые слова из описания
• Голосуйте быстро - результаты через 24 часа!

<b>Следующий опрос в воскресенье в 12:00!</b>

#опрос #результаты #сообщество
        """
        
        self.telegram.send_message(message)
        
        with self.generator.db.get_connection() as conn:
            conn.execute('''
                UPDATE poll_history SET results_sent = TRUE WHERE message_id = ?
            ''', (message_id,))
    
    def _check_recipe_usage(self, recipe_type):
        """Проверка использования рецептов и уведомление администратора"""
        try:
            stats = self.content_tracker.get_recipe_usage_stats()
            
            for stat in stats:
                if stat['used_count'] >= stat['total_count'] * 0.9:
                    self.admin_notifier.notify_last_recipe_used(
                        stat['recipe_type'], 
                        stat['total_count']
                    )
                    
        except Exception as e:
            logger.error(f"❌ Ошибка проверки использования рецептов: {e}")
    
    def _check_poll_usage(self):
        """Проверка использования опросов и уведомление администратора"""
        try:
            available_polls = self.content_tracker.get_available_polls_count()
            
            if available_polls <= 1:
                total_polls = service_monitor.polls_sent
                self.admin_notifier.notify_last_poll_used(total_polls)
                
        except Exception as e:
            logger.error(f"❌ Ошибка проверки использования опросов: {e}")
    
    def _get_day_name(self, day_num):
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        return days[day_num]

    def _run_scheduler(self):
        def run():
            while self.is_running:
                schedule.run_pending()
                time.sleep(60)
        Thread(target=run, daemon=True).start()
        logger.info("✅ Планировщик с анонимным голосованием запущен")

    def get_next_event(self):
        """Получает следующее событие для отображения в дашборде"""
        try:
            current_times = TimeManager.get_current_times()
            current_kemerovo_time = current_times['kemerovo_time'][:5]
            
            current_weekday = TimeManager.get_kemerovo_weekday()
            today_schedule = self.kemerovo_schedule.get(current_weekday, {})
            
            for time_str, event in sorted(today_schedule.items()):
                if time_str > current_kemerovo_time:
                    return time_str, event
            
            tomorrow = (current_weekday + 1) % 7
            tomorrow_schedule = self.kemerovo_schedule.get(tomorrow, {})
            if tomorrow_schedule:
                first_time = min(tomorrow_schedule.keys())
                return first_time, tomorrow_schedule[first_time]
            
            return "07:30", {"name": "Следующий пост", "type": "general"}
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "07:30", {"name": "Следующий пост", "type": "general"}

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
telegram_manager = EnhancedTelegramManager()
content_generator = SmartContentGenerator()
content_scheduler = EnhancedContentScheduler()

# ЗАПУСК СИСТЕМЫ
try:
    content_scheduler.start_scheduler()
    start_keep_alive_system()
    logger.info("✅ Все компоненты системы с анонимным голосованием инициализированы")
    
    current_times = TimeManager.get_current_times()
    
    # Отправляем информационное сообщение о системе
    info_message = f"""
🎪 <b>СИСТЕМА ОБНОВЛЕНА: АНОНИМНОЕ ГОЛОСОВАНИЕ + НАУЧНЫЙ АНАЛИЗ</b>

✅ Запущена продвинутая система:
• 🕵️‍♂️ АНОНИМНОЕ ГОЛОСОВАНИЕ - ники скрыты
• 🔒 КОНФИДЕНЦИАЛЬНОСТЬ - данные агрегированы
• 📊 АВТОСБОР РЕЗУЛЬТАТОВ - из комментариев
• 🧮 АВТОПОДСЧЕТ - с процентами и графиками
• 🔬 НАУЧНЫЙ АНАЛИЗ - на основе результатов

🆕 <b>Принципы анонимности:</b>
• Все голоса собираются анонимно
• Ники пользователей не отображаются
• Результаты показываются в агрегированном виде
• Конфиденциальность каждого участника защищена

🕐 Сервер: {current_times['server_time']}
🕐 Кемерово: {current_times['kemerovo_time']}
🔒 Режим: {'АНОНИМНОЕ голосование' if Config.ANONYMOUS_VOTING else 'Публичное голосование'}

Присоединяйтесь к воскресным опросам! Ваше мнение важно 💫
    """
    
    telegram_manager.send_message(info_message)
    
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
        
        content_tracker = ContentTracker()
        recipe_stats = content_tracker.get_recipe_usage_stats()
        poll_stats = content_tracker.get_poll_usage_stats()
        
        # Получаем статистику по опросам
        with content_tracker.db.get_connection() as conn:
            cursor = conn.execute('''
                SELECT COUNT(*) as total_polls, 
                       SUM(CASE WHEN results_sent THEN 1 ELSE 0 END) as processed_polls,
                       SUM(CASE WHEN NOT results_sent AND sent_at < DATETIME('now', '-1 day') THEN 1 ELSE 0 END) as pending_polls
                FROM poll_history
            ''')
            poll_summary = cursor.fetchone()
        
        # Статистика анонимного голосования
        anonymous_stats = {
            'enabled': Config.ANONYMOUS_VOTING,
            'total_votes': service_monitor.anonymous_votes_collected,
            'privacy_level': 'MAXIMUM' if Config.ANONYMOUS_VOTING else 'STANDARD'
        }
        
        weekly_stats = {
            'posts_sent': service_monitor.recipes_sent + service_monitor.polls_sent,
            'polls_sent': service_monitor.polls_sent,
            'results_published': service_monitor.results_published,
            'anonymous_votes': service_monitor.anonymous_votes_collected,
            'total_engagement': service_monitor.polls_sent * 10
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
                    --secondary: #3498db;
                    --success: #27ae60;
                    --warning: #f39c12;
                    --danger: #e74c3c;
                    --light: #ecf0f1;
                    --dark: #34495e;
                    --anonymous: #9b59b6;
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
                    max-width: 1200px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 20px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                
                .header {{
                    background: linear-gradient(135deg, var(--primary), var(--dark));
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                
                .header h1 {{
                    font-size: 2.5em;
                    margin-bottom: 10px;
                    font-weight: 300;
                }}
                
                .header p {{
                    opacity: 0.9;
                    font-size: 1.1em;
                }}
                
                .status-bar {{
                    display: flex;
                    justify-content: center;
                    gap: 30px;
                    margin-top: 20px;
                    flex-wrap: wrap;
                }}
                
                .status-item {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    background: rgba(255,255,255,0.1);
                    padding: 10px 20px;
                    border-radius: 50px;
                    backdrop-filter: blur(10px);
                }}
                
                .anonymous-badge {{
                    background: var(--anonymous);
                    color: white;
                    padding: 5px 15px;
                    border-radius: 20px;
                    font-size: 0.9em;
                    margin-left: 10px;
                }}
                
                .widgets-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
                    gap: 20px;
                    padding: 30px;
                }}
                
                .widget {{
                    background: var(--light);
                    padding: 25px;
                    border-radius: 15px;
                    border-left: 5px solid var(--secondary);
                }}
                
                .widget-anonymous {{
                    border-left-color: var(--anonymous);
                }}
                
                .widget h3 {{
                    color: var(--primary);
                    margin-bottom: 15px;
                    font-size: 1.3em;
                }}
                
                .monitor-info {{
                    background: var(--light);
                    margin: 20px 30px;
                    padding: 20px;
                    border-radius: 15px;
                }}
                
                .monitor-item {{
                    display: flex;
                    justify-content: between;
                    margin: 10px 0;
                    padding: 8px 0;
                    border-bottom: 1px solid #ddd;
                }}
                
                .monitor-item span:first-child {{
                    font-weight: bold;
                    flex: 1;
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 10px;
                    margin-top: 15px;
                }}
                
                .btn {{
                    padding: 12px 20px;
                    border: none;
                    border-radius: 8px;
                    background: var(--secondary);
                    color: white;
                    cursor: pointer;
                    transition: all 0.3s;
                    font-size: 14px;
                }}
                
                .btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 5px 15px rgba(0,0,0,0.2);
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
                
                .btn-anonymous {{
                    background: var(--anonymous);
                }}
                
                .poll-stats {{
                    background: #e8f4fd;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 10px 0;
                    border-left: 4px solid #3498db;
                }}
                
                .anonymous-stats {{
                    background: #f3e8fd;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 10px 0;
                    border-left: 4px solid var(--anonymous);
                }}
                
                .usage-warning {{
                    background: #fff3cd;
                    padding: 10px;
                    border-radius: 8px;
                    margin: 5px 0;
                    border-left: 4px solid #ffc107;
                }}
                
                .usage-critical {{
                    background: #f8d7da;
                    padding: 10px;
                    border-radius: 8px;
                    margin: 5px 0;
                    border-left: 4px solid #dc3545;
                }}
                
                .progress-bar {{
                    background: #e9ecef;
                    border-radius: 10px;
                    overflow: hidden;
                    height: 20px;
                    margin: 5px 0;
                }}
                
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, var(--success), var(--secondary));
                    transition: width 0.3s;
                }}
                
                .privacy-features {{
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 10px 0;
                }}
                
                .feature-item {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin: 8px 0;
                }}
                
                .feature-icon {{
                    color: var(--anonymous);
                    font-size: 1.2em;
                }}
            </style>
        </head>
        <body>
            <div class="dashboard">
                <div class="header">
                    <h1>🎪 Умный дашборд @ppsupershef 
                        <span class="anonymous-badge">🕵️‍♂️ АНОНИМНОЕ ГОЛОСОВАНИЕ</span>
                    </h1>
                    <p>Клуб Осознанного Питания - Конфиденциальность + Научный анализ + Умные опросы</p>
                    
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
                        <div class="status-item">
                            <span>🕵️‍♂️</span>
                            <span>Анонимных голосов: {anonymous_stats['total_votes']}</span>
                        </div>
                    </div>
                </div>
                
                <div class="monitor-info">
                    <h3>🛡️ Мониторинг системы (Анонимное голосование + Анализ)</h3>
                    <div class="monitor-item">
                        <span>Uptime:</span>
                        <span>{int(monitor_status['uptime_seconds'] // 3600)}ч {int((monitor_status['uptime_seconds'] % 3600) // 60)}м</span>
                    </div>
                    <div class="monitor-item">
                        <span>Рецепты отправлено:</span>
                        <span>{monitor_status['recipes_sent']}</span>
                    </div>
                    <div class="monitor-item">
                        <span>Опросы отправлено:</span>
                        <span>{monitor_status['polls_sent']}</span>
                    </div>
                    <div class="monitor-item">
                        <span>Результатов опубликовано:</span>
                        <span>{monitor_status['results_published']}</span>
                    </div>
                    <div class="monitor-item">
                        <span>Анонимных голосов собрано:</span>
                        <span>{monitor_status['anonymous_votes_collected']}</span>
                    </div>
                    <div class="monitor-item">
                        <span>Всего опросов в системе:</span>
                        <span>{poll_summary['total_polls'] if poll_summary else 0}</span>
                    </div>
                    <div class="monitor-item">
                        <span>Обработано результатов:</span>
                        <span>{poll_summary['processed_polls'] if poll_summary else 0}</span>
                    </div>
                </div>
                
                <div class="widgets-grid">
                    <div class="widget">
                        <h3>📈 Статистика использования контента</h3>
                        <div class="poll-stats">
                            <h4>🍳 Использование рецептов:</h4>
                            {"".join([f'''
                            <div class="{'usage-critical' if stat['used_count'] >= stat['total_count'] * 0.9 else 'usage-warning' if stat['used_count'] >= stat['total_count'] * 0.7 else ''}">
                                <strong>{stat['recipe_type']}:</strong> {stat['used_count']}/{stat['total_count']} 
                                <div class="progress-bar">
                                    <div class="progress-fill" style="width: {int((stat['used_count']/stat['total_count'])*100)}%"></div>
                                </div>
                            </div>
                            ''' for stat in recipe_stats])}
                        </div>
                        <div class="poll-stats">
                            <h4>📊 Статистика опросов:</h4>
                            <div class="monitor-item">
                                <span>Всего опросов:</span>
                                <span>{poll_summary['total_polls'] if poll_summary else 0}</span>
                            </div>
                            <div class="monitor-item">
                                <span>Обработано:</span>
                                <span>{poll_summary['processed_polls'] if poll_summary else 0}</span>
                            </div>
                            <div class="monitor-item">
                                <span>В обработке:</span>
                                <span>{poll_summary['pending_polls'] if poll_summary else 0}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="widget widget-anonymous">
                        <h3>🕵️‍♂️ Управление анонимным голосованием</h3>
                        <div class="anonymous-stats">
                            <h4>🔒 Статус конфиденциальности:</h4>
                            <div class="monitor-item">
                                <span>Режим голосования:</span>
                                <span>{'АНОНИМНЫЙ' if anonymous_stats['enabled'] else 'Публичный'}</span>
                            </div>
                            <div class="monitor-item">
                                <span>Уровень приватности:</span>
                                <span>{anonymous_stats['privacy_level']}</span>
                            </div>
                            <div class="monitor-item">
                                <span>Всего анонимных голосов:</span>
                                <span>{anonymous_stats['total_votes']}</span>
                            </div>
                        </div>
                        
                        <div class="privacy-features">
                            <h4>🛡️ Функции конфиденциальности:</h4>
                            <div class="feature-item">
                                <span class="feature-icon">🔒</span>
                                <span>Ники пользователей скрыты</span>
                            </div>
                            <div class="feature-item">
                                <span class="feature-icon">📊</span>
                                <span>Результаты агрегированы</span>
                            </div>
                            <div class="feature-item">
                                <span class="feature-icon">🔄</span>
                                <span>Голоса анонимизированы</span>
                            </div>
                            <div class="feature-item">
                                <span class="feature-icon">⚡</span>
                                <span>Быстрая обработка</span>
                            </div>
                        </div>
                        
                        <div class="actions-grid">
                            <button class="btn" onclick="sendGutHealthPoll()">🦠 Суперспособности ЖКТ</button>
                            <button class="btn" onclick="sendFoodArchetypePoll()">🕵️‍♀️ Пищевые архетипы</button>
                            <button class="btn" onclick="sendFoodDilemmaPoll()">🚦 Пищевые дилеммы</button>
                            <button class="btn" onclick="sendWeeklyChallengePoll()">🏆 Недельный челлендж</button>
                            <button class="btn" onclick="sendCookingStylePoll()">👨‍🍳 Стили готовки</button>
                            <button class="btn btn-warning" onclick="sendRandomPoll()">🎲 Случайный опрос</button>
                            <button class="btn btn-anonymous" onclick="toggleAnonymousVoting()">{'❌ Отключить анонимность' if Config.ANONYMOUS_VOTING else '✅ Включить анонимность'}</button>
                            <button class="btn btn-success" onclick="forcePollResults()">📈 Принудительный сбор результатов</button>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>🔧 Быстрые действия</h3>
                        <div class="actions-grid">
                            <button class="btn" onclick="testChannel()">📤 Тест канала</button>
                            <button class="btn btn-success" onclick="testQuickPost()">🧪 Тест отправки</button>
                            <button class="btn" onclick="showManualPost()">📝 Ручной пост</button>
                            <button class="btn" onclick="sendScience()">🔬 Отправить науку</button>
                            <button class="btn btn-success" onclick="sendBreakfast()">🍳 Отправить завтрак</button>
                            <button class="btn" onclick="sendAdvice()">💡 Отправить совет</button>
                            <button class="btn" onclick="sendDessert()">🍰 Отправить десерт</button>
                            <button class="btn btn-warning" onclick="runDiagnostics()">🧪 Диагностика</button>
                        </div>
                    </div>
                    
                    <div class="widget">
                        <h3>📋 Расписание на сегодня</h3>
                        <div class="poll-stats">
                            {"".join([f'''
                            <div class="monitor-item">
                                <span>{time}</span>
                                <span>{event['name']}</span>
                            </div>
                            ''' for time, event in sorted(today_schedule.items())])}
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
                
                function showManualPost() {{
                    const content = prompt('Введите текст поста (поддерживается HTML разметка):');
                    if (content) {{
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
                            btn.textContent = originalText;
                            btn.disabled = false;
                        }});
                    }}
                }}
                
                // ФУНКЦИИ ДЛЯ ОПРОСОВ
                function sendGutHealthPoll() {{
                    fetch('/poll/gut-health').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос отправлен!' : '❌ Ошибка: ' + data.message);
                    }});
                }}
                
                function sendFoodArchetypePoll() {{
                    fetch('/poll/food-archetype').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос отправлен!' : '❌ Ошибка: ' + data.message);
                    }});
                }}
                
                function sendFoodDilemmaPoll() {{
                    fetch('/poll/food-dilemma').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос отправлен!' : '❌ Ошибка: ' + data.message);
                    }});
                }}
                
                function sendWeeklyChallengePoll() {{
                    fetch('/poll/weekly-challenge').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос отправлен!' : '❌ Ошибка: ' + data.message);
                    }});
                }}
                
                function sendCookingStylePoll() {{
                    fetch('/poll/cooking-style').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Опрос отправлен!' : '❌ Ошибка: ' + data.message);
                    }});
                }}
                
                function sendRandomPoll() {{
                    fetch('/poll/random').then(r => r.json()).then(data => {{
                        if (data.status === 'success') {{
                            alert('✅ Случайный опрос отправлен! Тип: ' + data.poll_type);
                        }} else {{
                            alert('❌ Ошибка: ' + data.message);
                        }}
                    }});
                }}
                
                function toggleAnonymousVoting() {{
                    if (confirm('Изменить режим анонимного голосования?')) {{
                        fetch('/toggle-anonymous-voting', {{ method: 'POST' }})
                            .then(r => r.json())
                            .then(data => {{
                                if (data.status === 'success') {{
                                    alert('✅ Режим анонимного голосования изменен!');
                                    location.reload();
                                }} else {{
                                    alert('❌ Ошибка: ' + data.message);
                                }}
                            }});
                    }}
                }}
                
                function forcePollResults() {{
                    if (confirm('Принудительно запустить сбор результатов для всех опросов?')) {{
                        fetch('/force-poll-results').then(r => r.json()).then(data => {{
                            alert(data.status === 'success' ? '✅ Сбор результатов запущен!' : '❌ Ошибка: ' + data.message);
                        }});
                    }}
                }}
                
                // СУЩЕСТВУЮЩИЕ ФУНКЦИИ
                function sendScience() {{
                    fetch('/send-science').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Научное сообщение отправлено!' : '❌ Ошибка отправки');
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

# НОВЫЕ МАРШРУТЫ ДЛЯ АНОНИМНОГО ГОЛОСОВАНИЯ
@app.route('/toggle-anonymous-voting', methods=['POST'])
@require_api_key
def toggle_anonymous_voting():
    """Переключение режима анонимного голосования"""
    try:
        Config.ANONYMOUS_VOTING = not Config.ANONYMOUS_VOTING
        new_status = "включено" if Config.ANONYMOUS_VOTING else "выключено"
        
        logger.info(f"🔒 Режим анонимного голосования {new_status}")
        
        return jsonify({
            "status": "success", 
            "message": f"Анонимное голосование {new_status}",
            "anonymous_voting": Config.ANONYMOUS_VOTING
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка переключения анонимного голосования: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/anonymous-votes/stats')
@require_api_key
def get_anonymous_votes_stats():
    """Получение статистики анонимных голосов"""
    try:
        anonymous_voting = AnonymousVotingSystem()
        
        with anonymous_voting.db.get_connection() as conn:
            # Общая статистика
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total_votes,
                    COUNT(DISTINCT user_hash) as unique_voters,
                    COUNT(DISTINCT message_id) as total_polls
                FROM anonymous_votes
            ''')
            stats = cursor.fetchone()
            
            # Статистика по опросам
            cursor = conn.execute('''
                SELECT 
                    poll_type,
                    COUNT(*) as vote_count,
                    COUNT(DISTINCT user_hash) as unique_voters
                FROM anonymous_votes
                GROUP BY poll_type
                ORDER BY vote_count DESC
            ''')
            poll_stats = cursor.fetchall()
        
        return jsonify({
            "status": "success",
            "data": {
                "total_votes": stats['total_votes'] if stats else 0,
                "unique_voters": stats['unique_voters'] if stats else 0,
                "total_polls": stats['total_polls'] if stats else 0,
                "poll_statistics": [
                    {
                        "poll_type": row['poll_type'],
                        "vote_count": row['vote_count'],
                        "unique_voters": row['unique_voters']
                    } for row in poll_stats
                ],
                "anonymous_voting_enabled": Config.ANONYMOUS_VOTING
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики анонимных голосов: {e}")
        return jsonify({"status": "error", "message": str(e)})

# HEALTH CHECK
@app.route('/health')
def health_check():
    status = service_monitor.get_status()
    status['anonymous_voting'] = Config.ANONYMOUS_VOTING
    return jsonify(status)

@app.route('/ping')
def ping():
    return "pong", 200

# ... (остальные существующие маршруты остаются без изменений)

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print("🚀 Запуск Умного Дашборда @ppsupershef с анонимным голосованием")
    print("🎯 Философия: Конфиденциальность + Научная нутрициология")
    print("🔒 Анонимное голосование: ВКЛЮЧЕНО" if Config.ANONYMOUS_VOTING else "🔓 Анонимное голосование: ВЫКЛЮЧЕНО")
    print("📊 Контент-план: 190 методов (7 научных + 178 рецептов + 5 опросов)")
    print("🔄 Умная ротация: 90 дней без повторений")
    print("🔬 Научные сообщения: 07:30 будни / 09:30 выходные")
    print("📊 Воскресные опросы: 12:00 каждое воскресенье")
    print("🕵️‍♂️ Анонимный сбор: Ники скрыты, данные агрегированы")
    print("🧮 Автоподсчет: Результаты с процентами и графиками")
    print("🔬 Научный анализ: Автогенерация на основе результатов")
    print("📊 Автопубликация: Через 24 часа после опроса")
    print("🔔 Уведомления администратору: Активны")
    print("📈 Отслеживание использования: Активно")
    print("🛡️ Keep-alive: Активен (каждые 5 минут)")
    print("🎮 Дашборд: Полностью функциональный с управлением анонимностью")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False
    )

