import os
import logging
import sqlite3
import hashlib
import requests
import schedule
import threading
import time
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, jsonify, request, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

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

class Config:
    """Конфигурация приложения"""
    # Telegram настройки
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'your-telegram-bot-token-here')
    TELEGRAM_CHANNEL = os.environ.get('TELEGRAM_CHANNEL', '@your_channel')
    
    # Безопасность
    ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'simple-secure-token-2024')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fallback-secret-key-for-development')
    
    # База данных
    DATABASE_URL = os.environ.get('DATABASE_URL', 'recipe_bot.db')
    
    # Настройки ротации
    ROTATION_DAYS = 30
    CONTENT_TYPES = ['breakfast', 'lunch', 'dinner', 'dessert', 'advice']
    
    # Расписание (время Кемерово UTC+7)
    SCHEDULE_CONFIG = {
        'weekdays': {
            '08:30': 'advice',
            '09:00': 'breakfast', 
            '12:00': 'lunch',
            '18:00': 'dinner',
            '20:00': 'dessert'
        },
        'weekends': {
            '08:30': 'advice',
            '10:00': 'breakfast',
            '13:00': 'lunch',
            '19:00': 'dinner', 
            '20:00': 'dessert'
        }
    }
    
    # Настройки Flask
    FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.environ.get('FLASK_PORT', 5000))
    FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

class SecurityManager:
    """Упрощенный менеджер безопасности для дашборда"""
    
    @staticmethod
    def require_auth(f):
        """Декоратор для аутентификации API - УПРОЩЕННАЯ ВЕРСИЯ"""
        @wraps(f)
        def decorated(*args, **kwargs):
            # ✅ РАЗРЕШАЕМ ДОСТУП К ПУБЛИЧНЫМ ЭНДПОИНТАМ
            public_endpoints = [
                '/', '/api/status', '/api/logs', '/api/health', 
                '/api/system-info', '/api/rotation-status'
            ]
            
            if request.path in public_endpoints and request.method == 'GET':
                logger.info(f"✅ GET доступ разрешен к публичному эндпоинту: {request.path}")
                return f(*args, **kwargs)
            
            # ✅ ДЛЯ ЗАЩИЩЕННЫХ ЭНДПОИНТОВ ПРОВЕРЯЕМ ТОКЕН
            token = request.headers.get('Authorization')
            
            if not token or not token.startswith('Bearer '):
                logger.warning(f"❌ Отсутствует или неверный формат токена для {request.path}")
                return jsonify({"error": "Требуется аутентификация"}), 401
            
            token_value = token.replace('Bearer ', '')
            
            # ✅ ПРОСТАЯ ПРОВЕРКА ТОКЕНА
            if token_value != Config.ADMIN_TOKEN:
                logger.warning(f"❌ Неверный токен! Ожидался: {Config.ADMIN_TOKEN[:8]}..., Получен: {token_value[:8]}...")
                return jsonify({"error": "Неверный токен"}), 401
            
            logger.info(f"✅ Аутентификация успешна для {request.path}")
            return f(*args, **kwargs)
        return decorated
    
    @staticmethod
    def hash_content(content):
        """Хеширование контента для проверки дубликатов"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()

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
        logger.info("✅ База данных инициализирована")
    
    def _create_tables(self):
        """Создание таблиц с защитой от дублирования"""
        try:
            with self.connection:
                # Таблица кэша контента
                self.connection.execute('''
                    CREATE TABLE IF NOT EXISTS content_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content_hash TEXT UNIQUE,
                        content_type TEXT NOT NULL,
                        method_name TEXT NOT NULL,
                        content_text TEXT NOT NULL,
                        used_count INTEGER DEFAULT 0,
                        last_used DATE,
                        created_at DATE DEFAULT CURRENT_DATE,
                        UNIQUE(content_hash, content_type)
                    )
                ''')
                
                # Таблица истории отправки
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
                
                # Таблица системных логов (для дашборда)
                self.connection.execute('''
                    CREATE TABLE IF NOT EXISTS system_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        level TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Создание индексов для производительности
                self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_hash ON content_cache(content_hash)')
                self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_type ON content_cache(content_type)')
                self.connection.execute('CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_messages(sent_at)')
                self.connection.execute('CREATE INDEX IF NOT EXISTS idx_logs_created ON system_logs(created_at)')
                
            logger.info("✅ Таблицы базы данных созданы/проверены")
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")
            raise
    
    def get_connection(self):
        """Получение соединения с базой данных"""
        return self.connection
    
    def log_system_event(self, level, message):
        """Логирование системных событий в базу данных"""
        try:
            with self.connection:
                self.connection.execute(
                    'INSERT INTO system_logs (level, message) VALUES (?, ?)',
                    (level, message)
                )
        except Exception as e:
            logger.error(f"❌ Ошибка записи в системные логи: {e}")
    
    def cleanup_old_records(self):
        """Очистка старых записей"""
        try:
            with self.connection:
                # Очистка кэша контента старше 60 дней
                deleted_cache = self.connection.execute(
                    'DELETE FROM content_cache WHERE created_at < DATE("now", "-60 days")'
                ).rowcount
                
                # Очистка истории отправки старше 30 дней
                deleted_messages = self.connection.execute(
                    'DELETE FROM sent_messages WHERE sent_at < DATETIME("now", "-30 days")'
                ).rowcount
                
                # Очистка системных логов старше 90 дней
                deleted_logs = self.connection.execute(
                    'DELETE FROM system_logs WHERE created_at < DATETIME("now", "-90 days")'
                ).rowcount
                
                logger.info(f"🧹 Очистка БД: кэш={deleted_cache}, сообщения={deleted_messages}, логи={deleted_logs}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка очистки БД: {e}")

# Инициализация Flask приложения
app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY

# Инициализация Rate Limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Глобальные переменные для хранения экземпляров
database_instance = None
security_manager = None

def initialize_services():
    """Инициализация всех сервисов"""
    global database_instance, security_manager
    
    try:
        # Инициализация базы данных
        database_instance = Database()
        
        # Инициализация менеджера безопасности
        security_manager = SecurityManager()
        
        # Первоначальная очистка старых записей
        database_instance.cleanup_old_records()
        
        logger.info("✅ Все сервисы успешно инициализированы")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации сервисов: {e}")
        return False

# Базовые роуты для проверки работы
@app.route('/')
def index():
    """Главная страница - редирект на дашборд"""
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    """Страница дашборда (временная заглушка)"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Recipe Bot - Dashboard</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .status { padding: 20px; background: #f0f0f0; border-radius: 10px; }
            .success { color: green; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h1>🍳 Recipe Bot Dashboard</h1>
        <div class="status">
            <h2>Статус системы:</h2>
            <p>✅ Flask приложение работает</p>
            <p>✅ База данных инициализирована</p>
            <p>🔧 Полный дашборд будет доступен после сборки всех компонентов</p>
        </div>
        <div style="margin-top: 20px;">
            <a href="/api/status">Проверить статус API</a> | 
            <a href="/api/health">Health Check</a>
        </div>
    </body>
    </html>
    """

@app.route('/api/status')
def api_status():
    """API статуса системы"""
    db_status = "✅ Работает" if database_instance else "❌ Не инициализирована"
    
    return jsonify({
        "status": "active",
        "timestamp": datetime.now().isoformat(),
        "database": db_status,
        "flask": "✅ Работает",
        "version": "1.0"
    })

@app.route('/api/health')
def api_health():
    """Health check для мониторинга"""
    return jsonify({
        "status": "healthy",
        "service": "recipe-bot",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/test-db')
def api_test_db():
    """Тест работы базы данных"""
    try:
        if not database_instance:
            return jsonify({"error": "База данных не инициализирована"}), 500
            
        with database_instance.get_connection() as conn:
            result = conn.execute("SELECT COUNT(*) as count FROM sqlite_master").fetchone()
            
        return jsonify({
            "status": "success",
            "tables_count": result['count'],
            "message": "База данных работает корректно"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Обработчики ошибок
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Ресурс не найден"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 ошибка: {error}")
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Слишком много запросов"}), 429

# Инициализация при запуске
if __name__ == '__main__':
    logger.info("🚀 Запуск инициализации Recipe Bot...")
    
    if initialize_services():
        logger.info("✅ Инициализация завершена успешно")
        logger.info(f"🌐 Веб-интерфейс будет доступен по: http://{Config.FLASK_HOST}:{Config.FLASK_PORT}")
        
        # Запуск Flask приложения
        app.run(
            host=Config.FLASK_HOST,
            port=Config.FLASK_PORT,
            debug=Config.FLASK_DEBUG,
            use_reloader=False
        )
    else:
        logger.error("❌ Не удалось инициализировать сервисы. Приложение не запущено.")
else:
    # Инициализация при импорте (для WSGI и т.д.)
    initialize_services()
    class SecurityManager:
    """Упрощенный менеджер безопасности для дашборда"""
    
    @staticmethod
    def require_auth(f):
        """Декоратор для аутентификации API - УПРОЩЕННАЯ ВЕРСИЯ"""
        @wraps(f)
        def decorated(*args, **kwargs):
            # ВСЕГДА РАЗРЕШАЕМ GET ЗАПРОСЫ (мониторинг)
            if request.method == 'GET':
                logger.info(f"✅ GET доступ разрешен к {request.path}")
                return f(*args, **kwargs)
            
            # ДЛЯ POST/DELETE/PUT ПРОВЕРЯЕМ ТОКЕН
            token = request.headers.get('Authorization')
            
            if not token or not token.startswith('Bearer '):
                logger.warning(f"❌ Отсутствует токен для {request.path}")
                return jsonify({"error": "Требуется аутентификация"}), 401
            
            token_value = token.replace('Bearer ', '')
            
            # ПРОСТАЯ ПРОВЕРКА ТОКЕНА
            if token_value != Config.ADMIN_TOKEN:
                logger.warning(f"❌ Неверный токен для {request.path}")
                return jsonify({"error": "Неверный токен"}), 401
            
            logger.info(f"✅ Аутентификация успешна для {request.path}")
            return f(*args, **kwargs)
        return decorated
    
    @staticmethod
    def hash_content(content):
        """Хеширование контента для проверки дубликатов"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()

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
            # Таблица кэша контента
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS content_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,
                    content_type TEXT NOT NULL,
                    method_name TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    used_count INTEGER DEFAULT 0,
                    last_used DATE,
                    created_at DATE DEFAULT CURRENT_DATE,
                    UNIQUE(content_hash, content_type)
                )
            ''')
            
            # Таблица истории отправки
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
            
            # Создание индексов
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_hash ON content_cache(content_hash)')
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_content_type ON content_cache(content_type)')
            self.connection.execute('CREATE INDEX IF NOT EXISTS idx_sent_date ON sent_messages(sent_at)')
    
    def get_connection(self):
        """Получение соединения с базой данных"""
        return self.connection
    
    def cleanup_old_records(self):
        """Очистка старых записей"""
        with self.connection:
            self.connection.execute(
                'DELETE FROM content_cache WHERE created_at < DATE("now", "-60 days")'
            )
            self.connection.execute(
                'DELETE FROM sent_messages WHERE sent_at < DATETIME("now", "-30 days")'
            )
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
        uptime = datetime.now() - self.start_time
        return {
            "status": "active",
            "uptime_seconds": uptime.total_seconds(),
            "request_count": self.request_count,
            "error_count": self.error_count,
            "duplicate_rejections": self.duplicate_rejections,
            "last_keep_alive": self.last_keep_alive.isoformat()
        }

class TimeManager:
    """Менеджер времени для работы с часовыми поясами"""
    
    @staticmethod
    def get_kemerovo_time():
        """Получение текущего времени в Кемерово (UTC+7)"""
        return datetime.utcnow() + timedelta(hours=7)
    
    @staticmethod
    def get_kemerovo_weekday():
        """Получение дня недели в Кемерово"""
        return TimeManager.get_kemerovo_time().weekday()
    
    @staticmethod
    def get_kemerovo_hour():
        """Получение часа в Кемерово"""
        return TimeManager.get_kemerovo_time().hour
    
    @staticmethod
    def kemerovo_to_server(kemerovo_time_str):
        """Конвертация времени Кемерово в серверное время"""
        try:
            # Серверное время = Кемерово - 7 часов
            kemerovo_time = datetime.strptime(kemerovo_time_str, '%H:%M')
            server_time = (kemerovo_time - timedelta(hours=7)).strftime('%H:%M')
            return server_time
        except Exception as e:
            logger.error(f"Ошибка конвертации времени: {e}")
            return kemerovo_time_str
    
    @staticmethod
    def get_current_times():
        """Получение текущего времени на сервере и в Кемерово"""
        server_time = datetime.utcnow().strftime('%H:%M')
        kemerovo_time = TimeManager.get_kemerovo_time().strftime('%H:%M')
        return {
            'server_time': server_time,
            'kemerovo_time': kemerovo_time
        }
    
    @staticmethod
    def is_weekend():
        """Проверка是否是 выходной день"""
        weekday = TimeManager.get_kemerovo_weekday()
        return weekday >= 5  # 5=суббота, 6=воскресенье
    
    @staticmethod
    def get_current_content_type():
        """Определение типа контента по текущему времени"""
        current_hour = TimeManager.get_kemerovo_hour()
        is_weekend = TimeManager.is_weekend()
        
        if is_weekend:
            # Выходные: 08:30, 10:00, 13:00, 19:00, 20:00
            if current_hour == 8: return 'advice'
            elif current_hour == 10: return 'breakfast'
            elif current_hour == 13: return 'lunch'
            elif current_hour == 19: return 'dinner'
            elif current_hour == 20: return 'dessert'
        else:
            # Будни: 08:30, 09:00, 12:00, 18:00, 20:00
            if current_hour == 8: return 'advice'
            elif current_hour == 9: return 'breakfast'
            elif current_hour == 12: return 'lunch'
            elif current_hour == 18: return 'dinner'
            elif current_hour == 20: return 'dessert'
        
        return None

# Инициализация мониторинга
service_monitor = ServiceMonitor()
class VisualManager:
    """Менеджер визуального оформления постов"""
    
    def generate_attractive_post(self, title, content, post_type, benefits):
        """Генерация привлекательного поста для Telegram"""
        return f"""
{title}
{content}
        
💫 <b>ПРЕИМУЩЕСТВА:</b>
{benefits}
        
#{post_type} #здоровоепитание #рецепт
"""

class ScientificContentGenerator:
    """Генератор научно-обоснованного контента (общий)"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🧠 СОВЕТЫ (7 рецептов)
    def generate_science_tip(self):
        """Научный совет по питанию"""
        content = """
🔬 <b>НАУЧНЫЙ СОВЕТ: СИЛА БЕЛКА ДЛЯ СЫТОСТИ</b>

Исследования показывают, что белок - самый насыщающий макронутриент. 
Добавление белковых продуктов к каждому приему пищи помогает:

• Снизить уровень грелина (гормона голода)
• Повысить уровень пептида YY (гормона сытости)  
• Увеличить термогенез (сжигание калорий)
• Сохранить мышечную массу

🎯 <b>ПРАКТИКА:</b> Добавьте 20-30г белка к каждому основному приему пищи!
"""
        benefits = """• 🎯 Контроль аппетита
• 💪 Сохранение мышц
• 🔥 Ускорение метаболизма
• 🧠 Улучшение когнитивных функций"""
        
        return self.visual_manager.generate_attractive_post(
            "🔬 НАУЧНЫЙ СОВЕТ: СИЛА БЕЛКА",
            content, "science_advice", benefits
        )

    def generate_nutrition_advice(self):
        """Совет по нутрициологии"""
        content = """
🥦 <b>ФУНКЦИОНАЛЬНОЕ ПИТАНИЕ: ЕДА КАК МЕДИЦИНА</b>

Современная нутрициология рассматривает пищу как инструмент влияния на здоровье:

• <b>Куркума</b> - куркумин (противовоспалительное)
• <b>Жирная рыба</b> - Омега-3 (здоровье мозга)
• <b>Ягоды</b> - антоцианы (антиоксиданты)
• <b>Чеснок</b> - аллицин (иммунная поддержка)

🎯 <b>ПРАКТИКА:</b> Включайте 2-3 функциональных продукта ежедневно!
"""
        benefits = """• 🌿 Природные антиоксиданты
• 🧠 Поддержка когнитивного здоровья
• ❤️ Укрепление сердечно-сосудистой системы
• 🔋 Повышение энергетического уровня"""
        
        return self.visual_manager.generate_attractive_post(
            "🥦 СОВЕТ: ФУНКЦИОНАЛЬНОЕ ПИТАНИЕ",
            content, "nutrition_advice", benefits
        )

    def generate_health_tip(self):
        """Совет по здоровому образу жизни"""
        content = """
💧 <b>ГИДРАЦИЯ: ВОДА КАК ОСНОВА ЗДОРОВЬЯ</b>

Вода участвует в каждом процессе организма:

• <b>Мозг</b>: 75% воды - улучшение когнитивных функций
• <b>Мышцы</b>: электролитный баланс - предотвращение судорог
• <b>Почки</b>: детоксикация - выведение метаболитов
• <b>Кожа</b>: увлажнение - защитный барьер

🎯 <b>ФОРМУЛА:</b> 30 мл на 1 кг веса в день
"""
        benefits = """• 🧠 Улучшение концентрации и памяти
• 💪 Повышение физической производительности
• 🌿 Естественная детоксикация
• 🧖 Улучшение состояния кожи"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 СОВЕТ: ОСНОВЫ ГИДРАЦИИ",
            content, "health_advice", benefits
        )

    def generate_cooking_tip(self):
        """Совет по приготовлению пищи"""
        content = """
👨‍🍳 <b>НАУКА ПРИГОТОВЛЕНИЯ: СОХРАНЕНИЕ НУТРИЕНТОВ</b>

Правильные техники приготовления сохраняют питательные вещества:

• <b>Пароварка</b>: сохраняет водорастворимые витамины (B, C)
• <b>Запекание</b>: минимизирует потерю минералов
• <b>Бланширование</b>: сохраняет цвет и текстуру овощей
• <b>Сыроедение</b>: максимум ферментов и витаминов

🎯 <b>ПРАКТИКА:</b> Чередуйте способы приготовления для максимальной пользы!
"""
        benefits = """• ♨️ Сохранение витаминов и минералов
• 🎨 Улучшение вкуса и текстуры
• 🔥 Оптимальная усвояемость
• 🌈 Разнообразие в питании"""
        
        return self.visual_manager.generate_attractive_post(
            "👨‍🍳 СОВЕТ: НАУКА ПРИГОТОВЛЕНИЯ",
            content, "cooking_advice", benefits
        )

    def generate_wellness_advice(self):
        """Совет по оздоровлению"""
        content = """
🌿 <b>ЦИРКАДНЫЕ РИТМЫ: КОГДА ЧТО ЕСТЬ</b>

Наши биологические часы влияют на метаболизм:

• <b>Утро</b>: высокая чувствительность к инсулину - углеводы
• <b>Обед</b>: пик пищеварительных ферментов - белки
• <b>Вечер</b>: подготовка ко сну - легкие блюда
• <b>Ночь</b>: восстановление - минимум пищи

🎯 <b>ПРАКТИКА:</b> Синхронизируйте питание с природными ритмами!
"""
        benefits = """• ⏰ Оптимальное усвоение питательных веществ
• 😴 Улучшение качества сна
• ⚖️ Баланс гормонов голода и сытости
• 🔄 Естественная регуляция метаболизма"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 СОВЕТ: ЦИРКАДНЫЕ РИТМЫ ПИТАНИЯ",
            content, "wellness_advice", benefits
        )

    def generate_fitness_tip(self):
        """Совет по фитнесу и питанию"""
        content = """
💪 <b>ПИТАНИЕ ДО И ПОСЛЕ ТРЕНИРОВКИ</b>

Стратегия питания вокруг тренировок влияет на результаты:

• <b>За 2-3 часа до</b>: сложные углеводы + белок (энергия)
• <b>За 30-60 минут до</b>: быстрые углеводы (топливо)
• <b>Сразу после</b>: белок + простые углеводы (восстановление)
• <b>Через 2 часа после</b>: полноценный прием пищи

🎯 <b>ФОРМУЛА:</b> 20г белка + 40г углеводов после тренировки
"""
        benefits = """• 🚀 Повышение эффективности тренировок
• 🔄 Ускоренное восстановление
• 💥 Рост мышечной массы
• ♻️ Восполнение энергетических запасов"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 СОВЕТ: ПИТАНИЕ ДЛЯ ТРЕНИРОВОК",
            content, "fitness_advice", benefits
        )

    def generate_lifestyle_advice(self):
        """Совет по образу жизни"""
        content = """
🌱 <b>ОСОЗНАННОЕ ПИТАНИЕ: МЕДЛЕННЫЙ ПРИЕМ ПИЩИ</b>

Медленное питание улучшает пищеварение и контроль порций:

• <b>Тщательное пережевывание</b>: механическое измельчение + ферменты слюны
• <b>20-минутное правило</b>: сигнал сытости доходит до мозга
• <b>Отсутствие отвлечений</b>: фокус на процессе еды
• <b>Наслаждение вкусом</b>: психологическое насыщение

🎯 <b>ПРАКТИКА:</b> Выделите 20-30 минут на каждый прием пищи без гаджетов!
"""
        benefits = """• 🍽️ Улучшение пищеварения и усвоения
• 🎯 Контроль порций и веса
• 😌 Снижение стресса
• 🧘 Повышение осознанности"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 СОВЕТ: ОСОЗНАННОЕ ПИТАНИЕ",
            content, "lifestyle_advice", benefits
        )

    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_energy_breakfast(self):
        """Энергетический завтрак для продуктивного утра"""
        content = """
🍳 <b>ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОМЛЕТ С ОВОЩАМИ</b>
КБЖУ: 380 ккал • Белки: 28г • Жиры: 22г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 4 шт (холин для мозга)
• Шпинат - 100 г (железо)
• Помидоры - 2 шт (ликопин)
• Грибы - 150 г (витамин D)
• Сыр - 50 г (кальций)
• Оливковое масло - 1 ст.л.

<b>Приготовление (15 минут):</b>
1. Овощи нарезать и обжарить 5 минут
2. Залить взбитыми яйцами
3. Готовить под крышкой 7-8 минут
4. Посыпать сыром за 2 минуты до готовности

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Белок яиц обладает высокой биодоступностью (98%), обеспечивая максимальное усвоение аминокислот для синтеза нейромедиаторов.
"""
        benefits = """• 🧠 Холин для памяти и когнитивных функций
• 💪 Высококачественный белок для мышц
• 🌿 Антиоксиданты для защиты клеток
• 🔋 Стабильная энергия без резких скачков сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🍳 ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОМЛЕТ С ОВОЩАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_protein_breakfast(self):
        """Белковый завтрак для сытости"""
        content = """
🥚 <b>БЕЛКОВЫЙ ЗАВТРАК: ТВОРОЖНАЯ ЗАПЕКАНКА</b>
КБЖУ: 320 ккал • Белки: 35г • Жиры: 12г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Яйца - 2 шт (альбумин)
• Яблоко - 1 шт (пектин)
• Корица - 1 ч.л. (антиоксиданты)
• Миндаль - 30 г (витамин E)

<b>Приготовление (25 минут):</b>
1. Творог смешать с яйцами и корицей
2. Яблоко нарезать кубиками
3. Выложить в форму, посыпать миндалем
4. Запекать 20 минут при 180°C

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога усваивается медленно (4-6 часов), обеспечивая продолжительное чувство сытости и постоянное поступление аминокислот в кровь.
"""
        benefits = """• ⏱️ Медленное высвобождение аминокислот
• 🎯 Длительное чувство сытости (4-6 часов)
• 💪 Стимуляция мышечного синтеза
• 🍎 Клетчатка для здоровья микробиома"""
        
        return self.visual_manager.generate_attractive_post(
            "🥚 БЕЛКОВЫЙ ЗАВТРАК: ТВОРОЖНАЯ ЗАПЕКАНКА",
            content, "protein_breakfast", benefits
        )

    def generate_fiber_breakfast(self):
        """Завтрак, богатый клетчаткой"""
        content = """
🌾 <b>ЗАВТРАК С КЛЕТЧАТКОЙ: ОВСЯНКА С СЕМЕНАМИ</b>
КБЖУ: 350 ккал • Белки: 15г • Жиры: 14г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 100 г (бета-глюканы)
• Семена льна - 2 ст.л. (лигнаны)
• Семена чиа - 2 ст.л. (Омега-3)
• Ягоды - 150 г (антиоксиданты)
• Корица - 1 ч.л. (полифенолы)

<b>Приготовление (10 минут):</b>
1. Овсянку варить 8 минут
2. Добавить семена и корицу
3. Подавать с свежими ягодами
4. Можно добавить ложку протеина

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-глюканы овсянки образуют вязкий гель в кишечнике, замедляя всасывание глюкозы и снижая гликемический ответ на 30-40%.
"""
        benefits = """• 🌾 Снижение гликемического индекса
• 🫀 Контроль уровня холестерина
• 🧠 Омега-3 для когнитивного здоровья
• 🍓 Антиоксиданты против окислительного стресса"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 ЗАВТРАК С КЛЕТЧАТКОЙ: ОВСЯНКА С СЕМЕНАМИ",
            content, "fiber_breakfast", benefits
        )

    def generate_balanced_breakfast(self):
        """Сбалансированный завтрак"""
        content = """
⚖️ <b>СБАЛАНСИРОВАННЫЙ ЗАВТРАК: АВОКАДО-ТОСТ</b>
КБЖУ: 420 ккал • Белки: 20г • Жиры: 25г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Хлеб цельнозерновой - 4 ломтика (клетчатка)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Яйцо пашот - 2 шт (белок)
• Лосось слабосоленый - 100 г (Омега-3)
• Руккола - 50 г (кальций)

<b>Приготовление (15 минут):</b>
1. Хлеб поджарить
2. Авокадо размять вилкой
3. Приготовить яйца пашот
4. Собрать тосты слоями

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание сложных углеводов, полезных жиров и белка обеспечивает стабильный уровень энергии на 4-5 часов и оптимальное усвоение жирорастворимых витаминов.
"""
        benefits = """• ⚡ Стабильная энергия на 4-5 часов
• 🧠 Омега-3 для мозга и против воспаления
• 🌿 Клетчатка для пищеварения
• 💪 Полноценный белок для сытости"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ЗАВТРАК: АВОКАДО-ТОСТ",
            content, "balanced_breakfast", benefits
        )

    def generate_quick_breakfast(self):
        """Быстрый завтрак для занятых"""
        content = """
⚡ <b>БЫСТРЫЙ ЗАВТРАК: ПРОТЕИНОВЫЙ КОКТЕЙЛЬ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Протеин ванильный - 2 мерные ложки (белок)
• Банан - 1 шт (калий)
• Миндальное молоко - 400 мл (витамин E)
• Овсяные хлопья - 50 г (углеводы)
• Арахисовая паста - 2 ст.л. (полезные жиры)

<b>Приготовление (3 минуты):</b>
1. Все ингредиенты поместить в блендер
2. Взбить до однородной консистенции
3. Перелить в стаканы
4. Можно добавить лед

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Жидкая форма питания ускоряет усвоение нутриентов, обеспечивая быстрое поступление аминокислот в кровоток для немедленного использования организмом.
"""
        benefits = """• ⏱️ Приготовление за 3 минуты
• 🚀 Быстрое усвоение питательных веществ
• 💪 Высокое содержание белка
• 🍌 Натуральные источники энергии"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ БЫСТРЫЙ ЗАВТРАК: ПРОТЕИНОВЫЙ КОКТЕЙЛЬ",
            content, "quick_breakfast", benefits
        )

    def generate_healthy_breakfast(self):
        """Здоровый завтрак для ЖКТ"""
        content = """
🌟 <b>ЗДОРОВЫЙ ЗАВТРАК: ГРЕЧНЕВАЯ КАША</b>
КБЖУ: 340 ккал • Белки: 12г • Жиры: 8г • Углеводы: 58г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (рутин)
• Тыква - 300 г (бета-каротин)
• Кунжут - 2 ст.л. (кальций)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (натуральные пребиотики)

<b>Приготовление (20 минут):</b>
1. Гречку отварить 15 минут
2. Тыкву запечь и размять
3. Смешать все ингредиенты
4. Заправить медом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гречка не содержит глютена и богата резистентным крахмалом, который служит пищей для полезных бактерий кишечника, поддерживая здоровье микробиома.
"""
        benefits = """• 🌾 Без глютена - подходит для чувствительных
• 🦠 Пребиотики для микробиома кишечника
• 🫀 Рутин для укрепления сосудов
• 🎃 Бета-каротин для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🌟 ЗДОРОВЫЙ ЗАВТРАК: ГРЕЧНЕВАЯ КАША",
            content, "healthy_breakfast", benefits
        )

    def generate_smart_breakfast(self):
        """Умный завтрак для мозга"""
        content = """
🧠 <b>УМНЫЙ ЗАВТРАК: ЯГОДНЫЙ ПАРФЕ</b>
КБЖУ: 320 ккал • Белки: 18г • Жиры: 10г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Черника - 150 г (антоцианы)
• Грецкие орехи - 40 г (Омега-3)
• Семена чиа - 2 ст.л. (клетчатка)
• Мед - 1 ст.л. (натуральные сахара)

<b>Приготовление (5 минут):</b>
1. Слоями выложить йогурт и ягоды
2. Посыпать орехами и семенами
3. Полить медом
4. Охладить 10 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод проникают через гематоэнцефалический барьер и накапливаются в областях мозга, ответственных за обучение и память, улучшая когнитивные функции.
"""
        benefits = """• 🧠 Улучшение памяти и концентрации
• 🦠 Пробиотики для здоровья кишечника
• 🫀 Антиоксиданты для защиты клеток
• 🌰 Омега-3 для нейропротекции"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УМНЫЙ ЗАВТРАК: ЯГОДНЫЙ ПАРФЕ",
            content, "smart_breakfast", benefits
        )

# Создание экземпляра генератора
scientific_generator = ScientificContentGenerator()
class MondayContentGenerator:
    """Генератор контента для понедельника - детокс и очищение"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_detox_breakfast(self):
        """Детокс-завтрак для очищения организма"""
        content = """
🌿 <b>ДЕТОКС-ЗАВТРАК: ЗЕЛЕНЫЙ СМУЗИ БОУЛ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 8г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Шпинат - 100 г (хлорофилл)
• Банан - 1 шт (калий)
• Авокадо - 1/2 шт (глутатион)
• Семена чиа - 2 ст.л. (клетчатка)
• Вода кокосовая - 200 мл (электролиты)
• Лимон - 1/2 шт (витамин C)

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Вылить в миску
3. Украсить семенами чиа и ягодами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Хлорофилл из зелени связывает токсины и тяжелые металлы, способствуя их выведению через ЖКТ, а глутатион из авокадо поддерживает работу печени.
"""
        benefits = """• 🌿 Хлорофилл для детоксикации
• 🥑 Глутатион для здоровья печени
• 🌾 Клетчатка для очищения ЖКТ
• 🍋 Витамин C для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ДЕТОКС-ЗАВТРАК: ЗЕЛЕНЫЙ СМУЗИ БОУЛ",
            content, "detox_breakfast", benefits
        )

    def generate_fiber_breakfast(self):
        """Завтрак, богатый клетчаткой"""
        content = """
🍎 <b>ЗАВТРАК С КЛЕТЧАТКОЙ: ОВСЯНКА С ЯБЛОКАМИ</b>
КБЖУ: 320 ккал • Белки: 12г • Жиры: 8г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 100 г (бета-глюканы)
• Яблоки - 2 шт (пектин)
• Семена льна - 2 ст.л. (лигнаны)
• Корица - 1 ч.л. (полифенолы)
• Грецкие орехи - 30 г (Омега-3)

<b>Приготовление (15 минут):</b>
1. Овсянку варить 10 минут
2. Яблоки натереть на терке
3. Добавить семена и специи
4. Украсить орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Растворимая клетчатка (пектин и бета-глюканы) образует гель в кишечнике, замедляя всасывание сахаров и связывая желчные кислоты, снижая уровень холестерина.
"""
        benefits = """• 🍎 Пектин для здоровья кишечника
• 🌾 Бета-глюканы для контроля холестерина
• 🌱 Лигнаны для гормонального баланса
• 🧠 Омега-3 для когнитивного здоровья"""
        
        return self.visual_manager.generate_attractive_post(
            "🍎 ЗАВТРАК С КЛЕТЧАТКОЙ: ОВСЯНКА С ЯБЛОКАМИ",
            content, "fiber_breakfast", benefits
        )

    def generate_alkaline_breakfast(self):
        """Щелочной завтрак для баланса pH"""
        content = """
🥒 <b>ЩЕЛОЧНОЙ ЗАВТРАК: ОГУРЕЧНЫЙ СМУЗИ</b>
КБЖУ: 180 ккал • Белки: 8г • Жиры: 6г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Огурцы - 2 шт (кремний)
• Сельдерей - 4 стебля (натрий)
• Лимон - 1/2 шт (цитраты)
• Имбирь - 1 см (гингерол)
• Мята - 10 листьев (ментол)
• Спирулина - 1 ч.л. (хлорофилл)

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Процедить через сито
3. Подавать охлажденным
4. Украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Овощи с высоким содержанием минералов (калий, магний, кальций) помогают нейтрализовать кислотную нагрузку современного питания, поддерживая оптимальный pH крови.
"""
        benefits = """• ⚖️ Баланс кислотно-щелочного равновесия
• 💧 Гидратация на клеточном уровне
• 🧪 Естественное очищение организма
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🥒 ЩЕЛОЧНОЙ ЗАВТРАК: ОГУРЕЧНЫЙ СМУЗИ",
            content, "alkaline_breakfast", benefits
        )

    def generate_liver_breakfast(self):
        """Завтрак для поддержки печени"""
        content = """
🍋 <b>ЗАВТРАК ДЛЯ ПЕЧЕНИ: ГРЕЧКА С ЛИМОНОМ</b>
КБЖУ: 300 ккал • Белки: 10г • Жиры: 5г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (рутин)
• Лимон - 1 шт (витамин C)
• Оливковое масло - 1 ст.л. (полифенолы)
• Петрушка - 20 г (апигенин)
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (20 минут):</b>
1. Гречку отварить до готовности
2. Добавить куркуму при варке
3. Заправить оливковым маслом и лимонным соком
4. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Куркумин активирует ферменты второй фазы детоксикации в печени, усиливая выведение токсинов, а апигенин из петрушки поддерживает регенерацию гепатоцитов.
"""
        benefits = """• 🧪 Активация детокс-ферментов печени
• 🛡️ Защита клеток печени
• 🔥 Противовоспалительное действие
• 💪 Укрепление сосудов"""
        
        return self.visual_manager.generate_attractive_post(
            "🍋 ЗАВТРАК ДЛЯ ПЕЧЕНИ: ГРЕЧКА С ЛИМОНОМ",
            content, "liver_breakfast", benefits
        )

    def generate_digestive_breakfast(self):
        """Завтрак для улучшения пищеварения"""
        content = """
🍐 <b>ЗАВТРАК ДЛЯ ПИЩЕВАРЕНИЯ: ГРУШЕВАЯ КАША</b>
КБЖУ: 280 ккал • Белки: 8г • Жиры: 6г • Углеводы: 50г

<b>Ингредиенты (на 2 порции):</b>
• Пшено - 100 г (магний)
• Груши - 2 шт (сорбитол)
• Имбирь - 1 см (гингерол)
• Корица - 1 ч.л. (эфирные масла)
• Семена фенхеля - 1 ч.л. (анетол)

<b>Приготовление (25 минут):</b>
1. Пшено промыть и отварить 20 минут
2. Груши нарезать кубиками
3. Добавить специи и груши за 5 минут до готовности
4. Настоять 5 минут под крышкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сорбитол из груш мягко стимулирует перистальтику кишечника, а гингерол и анетол обладают спазмолитическим действием, уменьшая вздутие и дискомфорт.
"""
        benefits = """• 🌀 Улучшение перистальтики кишечника
• 🔥 Снижение воспаления в ЖКТ
• 💫 Уменьшение вздутия и газообразования
• 🧂 Естественное очищение"""
        
        return self.visual_manager.generate_attractive_post(
            "🍐 ЗАВТРАК ДЛЯ ПИЩЕВАРЕНИЯ: ГРУШЕВАЯ КАША",
            content, "digestive_breakfast", benefits
        )

    def generate_antioxidant_breakfast(self):
        """Антиоксидантный завтрак"""
        content = """
🫐 <b>АНТИОКСИДАНТНЫЙ ЗАВТРАК: ЯГОДНЫЙ КИНОА</b>
КБЖУ: 320 ккал • Белки: 12г • Жиры: 10г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 100 г (кверцетин)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Грецкие орехи - 30 г (полифенолы)
• Корица - 1 ч.л. (циннамальдегид)

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Ягоды промыть и обсушить
3. Смешать киноа с ягодами
4. Посыпать орехами и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод нейтрализуют свободные радикалы, защищая клетки от окислительного стресса, который является основной причиной старения и многих заболеваний.
"""
        benefits = """• 🛡️ Защита от окислительного стресса
• 🧬 Замедление клеточного старения
• ❤️ Укрепление сердечно-сосудистой системы
• 🧠 Нейропротекторное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🫐 АНТИОКСИДАНТНЫЙ ЗАВТРАК: ЯГОДНЫЙ КИНОА",
            content, "antioxidant_breakfast", benefits
        )

    def generate_hydration_breakfast(self):
        """Гидратирующий завтрак"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЙ ЗАВТРАК: АРБУЗНЫЙ САЛАТ</b>
КБЖУ: 220 ккал • Белки: 6г • Жиры: 4г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 600 г (ликопин)
• Огурец - 1 шт (кремний)
• Мята - 20 г (ментол)
• Фета - 100 г (кальций)
• Лимонный сок - 2 ст.л. (цитраты)

<b>Приготовление (10 минут):</b>
1. Арбуз и огурец нарезать кубиками
2. Фету раскрошить
3. Смешать все ингредиенты
4. Полить лимонным соком, украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз на 92% состоит из воды и содержит электролиты (калий, магний), способствуя быстрому восполнению жидкости и минералов после ночного обезвоживания.
"""
        benefits = """• 💦 Быстрое восполнение жидкости
• ⚡ Восстановление электролитного баланса
• 🍉 Ликопин для антиоксидантной защиты
• 🧊 Охлаждающий и освежающий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЙ ЗАВТРАК: АРБУЗНЫЙ САЛАТ",
            content, "hydration_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_cleansing_lunch(self):
        """Очищающий обед для детокса"""
        content = """
🥗 <b>ОЧИЩАЮЩИЙ ОБЕД: САЛАТ С КИНОА И ОВОЩАМИ</b>
КБЖУ: 350 ккал • Белки: 18г • Жиры: 12г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 100 г (полноценный белок)
• Брокколи - 200 г (сульфорафан)
• Морковь - 2 шт (бета-каротин)
• Авокадо - 1/2 шт (мононенасыщенные жиры)
• Лимонный сок - 2 ст.л. (витамин C)
• Оливковое масло - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Брокколи приготовить на пару 8 минут
3. Овощи нарезать, смешать с киноа
4. Заправить маслом и лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сульфорафан из брокколи активирует ферменты второй фазы детоксикации в печени, усиливая выведение канцерогенов и токсинов из организма.
"""
        benefits = """• 🥦 Сульфорафан для активации детокс-ферментов
• 🥑 Полезные жиры для усвоения витаминов
• 🍋 Витамин C для поддержки иммунитета
• 🌾 Полноценный растительный белок"""
        
        return self.visual_manager.generate_attractive_post(
            "🥗 ОЧИЩАЮЩИЙ ОБЕД: САЛАТ С КИНОА И ОВОЩАМИ",
            content, "cleansing_lunch", benefits
        )

    def generate_alkaline_lunch(self):
        """Щелочной обед для баланса pH"""
        content = """
🥒 <b>ЩЕЛОЧНОЙ ОБЕД: ОВОЩНОЙ СУП-ПЮРЕ</b>
КБЖУ: 280 ккал • Белки: 12г • Жиры: 6г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Цукини - 2 шт (калий)
• Сельдерей - 4 стебля (натрий)
• Шпинат - 100 г (магний)
• Лук - 1 шт (кверцетин)
• Чеснок - 3 зубчика (аллицин)
• Зелень петрушки - 30 г (хлорофилл)

<b>Приготовление (25 минут):</b>
1. Овощи нарезать кубиками
2. Варить 20 минут до мягкости
3. Взбить блендером в пюре
4. Добавить зелень перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Овощи богаты минералами (калий, магний), которые помогают нейтрализовать кислотную нагрузку от современных диет, поддерживая оптимальный pH крови 7.35-7.45.
"""
        benefits = """• ⚖️ Баланс кислотно-щелочного равновесия
• 🥬 Минералы для электролитного баланса
• 🧄 Противовоспалительные компоненты
• 💧 Гидратация и очищение"""
        
        return self.visual_manager.generate_attractive_post(
            "🥒 ЩЕЛОЧНОЙ ОБЕД: ОВОЩНОЙ СУП-ПЮРЕ",
            content, "alkaline_lunch", benefits
        )

    def generate_liver_lunch(self):
        """Обед для поддержки печени"""
        content = """
🍋 <b>ОБЕД ДЛЯ ПЕЧЕНИ: СВЕКЛА С ЯБЛОКАМИ</b>
КБЖУ: 320 ккал • Белки: 10г • Жиры: 8г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 3 шт (бетаин)
• Яблоки - 2 шт (пектин)
• Грецкие орехи - 40 г (аргинин)
• Лимонный сок - 2 ст.л. (витамин C)
• Укроп - 20 г (эфирные масла)

<b>Приготовление (30 минут):</b>
1. Свеклу запечь 25 минут
2. Очистить и нарезать соломкой
3. Яблоки натереть на терке
4. Смешать все ингредиенты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бетаин из свеклы защищает клетки печени от повреждения и способствует оттоку желчи, улучшая переваривание жиров и выведение токсинов.
"""
        benefits = """• 🍠 Бетаин для защиты гепатоцитов
• 💚 Улучшение оттока желчи
• 🧪 Поддержка детоксикации
• 🍏 Пектин для связывания токсинов"""
        
        return self.visual_manager.generate_attractive_post(
            "🍋 ОБЕД ДЛЯ ПЕЧЕНИ: СВЕКЛА С ЯБЛОКАМИ",
            content, "liver_lunch", benefits
        )

    def generate_digestive_lunch(self):
        """Обед для улучшения пищеварения"""
        content = """
🌿 <b>ОБЕД ДЛЯ ПИЩЕВАРЕНИЯ: СУП С ИМБИРЕМ</b>
КБЖУ: 290 ккал • Белки: 15г • Жиры: 8г • Углеводы: 40г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 500 г (бета-каротин)
• Морковь - 2 шт (клетчатка)
• Имбирь - 3 см (гингерол)
• Куркума - 1 ч.л. (куркумин)
• Кокосовое молоко - 200 мл (МСТ)
• Лимонный сок - 1 ст.л.

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Варить 25 минут до мягкости
3. Добавить специи за 5 минут до готовности
4. Взбить блендером, добавить кокосовое молоко

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гингерол из имбиря стимулирует выработку пищеварительных ферментов и ускоряет опорожнение желудка, уменьшая вздутие и чувство тяжести после еды.
"""
        benefits = """• 🔥 Стимуляция пищеварительных ферментов
• 💫 Ускорение моторики ЖКТ
• 🛡️ Противовоспалительное действие
• 🥥 Легкие жиры для усвоения витаминов"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ОБЕД ДЛЯ ПИЩЕВАРЕНИЯ: СУП С ИМБИРЕМ",
            content, "digestive_lunch", benefits
        )

    def generate_antioxidant_lunch(self):
        """Антиоксидантный обед"""
        content = """
🍅 <b>АНТИОКСИДАНТНЫЙ ОБЕД: ТОМАТНЫЙ СУП</b>
КБЖУ: 310 ккал • Белки: 12г • Жиры: 10г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Помидоры - 800 г (ликопин)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Базилик - 30 г (эвгенол)
• Оливковое масло - 2 ст.л. (полифенолы)

<b>Приготовление (35 минут):</b>
1. Помидоры бланшировать и очистить от кожицы
2. Лук и чеснок обжарить до прозрачности
3. Добавить помидоры, тушить 20 минут
4. Взбить блендером, добавить базилик

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Термическая обработка томатов увеличивает биодоступность ликопина на 300%, усиливая его антиоксидантные свойства и способность защищать от УФ-излучения.
"""
        benefits = """• 🍅 Ликопин для защиты от УФ-излучения
• 🧅 Кверцетин против воспаления
• 🧄 Антимикробные свойства
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🍅 АНТИОКСИДАНТНЫЙ ОБЕД: ТОМАТНЫЙ СУП",
            content, "antioxidant_lunch", benefits
        )

    def generate_hydration_lunch(self):
        """Гидратирующий обед"""
        content = """
💦 <b>ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩИ НА ПАРУ</b>
КБЖУ: 240 ккал • Белки: 10г • Жиры: 6г • Углеводы: 38г

<b>Ингредиенты (на 2 порции):</b>
• Цветная капуста - 400 г (глюкозинолаты)
• Болгарский перец - 2 шт (витамин C)
• Кабачки - 2 шт (калий)
• Спаржа - 150 г (аспарагин)
• Соус тахини - 2 ст.л. (кальций)

<b>Приготовление (20 минут):</b>
1. Овощи нарезать крупными кусками
2. Приготовить на пару 12-15 минут
3. Подавать с соусом тахини
4. Можно сбрызнуть лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Приготовление на пару сохраняет до 90% водорастворимых витаминов и минералов, обеспечивая максимальную гидратацию и питательную ценность блюда.
"""
        benefits = """• ♨️ Сохранение витаминов и минералов
• 💧 Максимальная гидратация
• 🥦 Глюкозинолаты для детокса
• 🧂 Естественный вкус без соли"""
        
        return self.visual_manager.generate_attractive_post(
            "💦 ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩИ НА ПАРУ",
            content, "hydration_lunch", benefits
        )

    def generate_fiber_lunch(self):
        """Обед, богатый клетчаткой"""
        content = """
🌾 <b>ОБЕД С КЛЕТЧАТКОЙ: ЧЕЧЕВИЧНЫЙ СУП</b>
КБЖУ: 380 ккал • Белки: 22г • Жиры: 8г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Чечевица красная - 150 г (растворимая клетчатка)
• Морковь - 2 шт (бета-каротин)
• Сельдерей - 3 стебля (апигенин)
• Лук - 1 шт (пребиотики)
• Тмин - 1 ч.л. (против метеоризма)
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Чечевицу промыть
3. Варить все вместе 25 минут
4. Добавить специи за 5 минут до готовности

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Растворимая клетчатка чечевицы служит пищей для полезных бактерий кишечника, производящих короткоцепочечные жирные кислоты, которые укрепляют кишечный барьер.
"""
        benefits = """• 🦠 Питание для полезной микробиоты
• 🛡️ Укрепление кишечного барьера
• 🧪 Производство бутирата
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 ОБЕД С КЛЕТЧАТКОЙ: ЧЕЧЕВИЧНЫЙ СУП",
            content, "fiber_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_light_dinner(self):
        """Легкий ужин для пищеварения"""
        content = """
🐟 <b>ЛЕГКИЙ УЖИН: РЫБА НА ПАРУ С ОВОЩАМИ</b>
КБЖУ: 320 ккал • Белки: 35г • Жиры: 12г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Филе белой рыбы - 400 г (легкий белок)
• Брокколи - 200 г (клетчатка)
• Морковь - 2 шт (бета-каротин)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (эфирные масла)
• Имбирь - 1 см (гингерол)

<b>Приготовление (20 минут):</b>
1. Рыбу и овощи выложить в пароварку
2. Готовить 15 минут на пару
3. Полить лимонным соком
4. Посыпать укропом и имбирем

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Приготовление на пару сохраняет водорастворимые витамины (B, C) и предотвращает образование канцерогенных соединений, возникающих при жарке при высоких температурах.
"""
        benefits = """• 🐟 Легкоусвояемый белок
• ♨️ Сохранение питательных веществ
• 🥦 Клетчатка для ночного очищения
• 🧂 Естественный вкус без лишней соли"""
        
        return self.visual_manager.generate_attractive_post(
            "🐟 ЛЕГКИЙ УЖИН: РЫБА НА ПАРУ С ОВОЩАМИ",
            content, "light_dinner", benefits
        )

    def generate_alkaline_dinner(self):
        """Щелочной ужин"""
        content = """
🥬 <b>ЩЕЛОЧНОЙ УЖИН: ШПИНАТ С ГРИБАМИ</b>
КБЖУ: 280 ккал • Белки: 25г • Жиры: 12г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Шпинат - 400 г (магний)
• Шампиньоны - 300 г (селен)
• Чеснок - 3 зубчика (аллицин)
• Лимонный сок - 2 ст.л. (цитраты)
• Кедровые орехи - 30 г (цинк)

<b>Приготовление (15 минут):</b>
1. Шпинат промыть и обсушить
2. Грибы нарезать пластинами
3. Обжарить грибы с чесноком 8 минут
4. Добавить шпинат, готовить 2 минуты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Листовые зеленые овощи богаты минералами (магний, калий), которые помогают нейтрализовать кислотную нагрузку и поддерживают оптимальный pH внутренней среды.
"""
        benefits = """• ⚖️ Поддержка кислотно-щелочного баланса
• 🧪 Минералы для детоксикации
• 🍄 Селен для антиоксидантной защиты
• 🌿 Хлорофилл для очищения крови"""
        
        return self.visual_manager.generate_attractive_post(
            "🥬 ЩЕЛОЧНОЙ УЖИН: ШПИНАТ С ГРИБАМИ",
            content, "alkaline_dinner", benefits
        )

    def generate_liver_dinner(self):
        """Ужин для поддержки печени"""
        content = """
🍠 <b>УЖИН ДЛЯ ПЕЧЕНИ: ТУШЕНАЯ КАПУСТА</b>
КБЖУ: 290 ккал • Белки: 18г • Жиры: 10г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Капуста белокочанная - 600 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Куркума - 1 ч.л. (куркумин)
• Семена укропа - 1 ч.л. (против метеоризма)

<b>Приготовление (25 минут):</b>
1. Овощи нашинковать
2. Тушить на медленном огне 20 минут
3. Добавить специи за 5 минут до готовности
4. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глюкозинолаты из капусты активируют ферменты печени, ответственные за детоксикацию, и способствуют выведению избытка эстрогенов из организма.
"""
        benefits = """• 🥬 Активация детокс-ферментов печени
• ♻️ Выведение избытка гормонов
• 🔥 Противовоспалительное действие
• 💫 Улучшение пищеварения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍠 УЖИН ДЛЯ ПЕЧЕНИ: ТУШЕНАЯ КАПУСТА",
            content, "liver_dinner", benefits
        )

    def generate_digestive_dinner(self):
        """Ужин для улучшения пищеварения"""
        content = """
🍲 <b>УЖИН ДЛЯ ПИЩЕВАРЕНИЯ: ТЫКВЕННОЕ ПЮРЕ</b>
КБЖУ: 250 ккал • Белки: 12г • Жиры: 8г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 800 г (бета-каротин)
• Картофель - 2 шт (калий)
• Имбирь - 2 см (гингерол)
• Мускатный орех - 1/4 ч.л. (миристицин)
• Кокосовые сливки - 100 мл (МСТ)

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Запечь 25 минут до мягкости
3. Размять в пюре
4. Добавить специи и кокосовые сливки

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-каротин из тыквы преобразуется в витамин A, который необходим для поддержания целостности слизистой оболочки ЖКТ и заживления повреждений.
"""
        benefits = """• 🎃 Витамин A для здоровья слизистой ЖКТ
• 🔥 Противовоспалительные свойства
• 💫 Улучшение моторики кишечника
• 🥥 Легкие жиры для усвоения"""
        
        return self.visual_manager.generate_attractive_post(
            "🍲 УЖИН ДЛЯ ПИЩЕВАРЕНИЯ: ТЫКВЕННОЕ ПЮРЕ",
            content, "digestive_dinner", benefits
        )

    def generate_antioxidant_dinner(self):
        """Антиоксидантный ужин"""
        content = """
🍆 <b>АНТИОКСИДАНТНЫЙ УЖИН: БАКЛАЖАНЫ ГРИЛЬ</b>
КБЖУ: 270 ккал • Белки: 15г • Жиры: 12г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Баклажаны - 2 шт (насунин)
• Помидоры - 3 шт (ликопин)
• Базилик - 30 г (эвгенол)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 2 ст.л. (полифенолы)

<b>Приготовление (20 минут):</b>
1. Баклажаны нарезать кружками
2. Приготовить на гриле 8 минут с каждой стороны
3. Помидоры нарезать дольками
4. Собрать слоями, полить маслом с чесноком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Насунин из баклажанов является мощным антиоксидантом, защищающим клеточные мембраны от повреждения свободными радикалами, особенно в жировых слоях.
"""
        benefits = """• 🍆 Защита клеточных мембран
• 🍅 Ликопин для антиоксидантной защиты
• 🌿 Противовоспалительные свойства
• 🧄 Антимикробное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🍆 АНТИОКСИДАНТНЫЙ УЖИН: БАКЛАЖАНЫ ГРИЛЬ",
            content, "antioxidant_dinner", benefits
        )

    def generate_hydration_dinner(self):
        """Гидратирующий ужин"""
        content = """
🥒 <b>ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ</b>
КБЖУ: 220 ккал • Белки: 18г • Жиры: 12г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Огурцы - 3 шт (кремний)
• Творог - 300 г (белок)
• Укроп - 30 г (эфирные масла)
• Лимонный сок - 2 ст.л. (витамин C)
• Семена подсолнечника - 30 г (витамин E)

<b>Приготовление (10 минут):</b>
1. Огурцы нарезать кубиками
2. Творог смешать с укропом
3. Соединить все ингредиенты
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Огурцы на 95% состоят из структурированной воды, которая легче проникает в клетки и способствует эффективной гидратации на клеточном уровне.
"""
        benefits = """• 💧 Глубокая клеточная гидратация
• 🧀 Легкий белок для ночного восстановления
• 🌱 Кремний для здоровья соединительной ткани
• 🍋 Витамин C для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🥒 ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ",
            content, "hydration_dinner", benefits
        )

    def generate_fiber_dinner(self):
        """Ужин, богатый клетчаткой"""
        content = """
🌱 <b>УЖИН С КЛЕТЧАТКОЙ: СТРУЧКОВАЯ ФАСОЛЬ</b>
КБЖУ: 300 ккал • Белки: 22г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Стручковая фасоль - 500 г (нерастворимая клетчатка)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (пребиотики)
• Чеснок - 3 зубчика (аллицин)
• Миндальные лепестки - 30 г (витамин E)

<b>Приготовление (20 минут):</b>
1. Фасоль бланшировать 5 минут
2. Овощи нарезать соломкой
3. Обжарить с чесноком 10 минут
4. Посыпать миндальными лепестками

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нерастворимая клетчатка стручковой фасоли увеличивает объем стула и ускоряет его прохождение через кишечник, предотвращая запоры и способствуя регулярному очищению.
"""
        benefits = """• 🚀 Ускорение кишечного транзита
• 🛡️ Профилактика запоров
• 🦠 Питание для микробиоты
• 🌿 Очищение кишечника"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 УЖИН С КЛЕТЧАТКОЙ: СТРУЧКОВАЯ ФАСОЛЬ",
            content, "fiber_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_detox_dessert(self):
        """Детокс-десерт для вечера"""
        content = """
🍐 <b>ДЕТОКС-ДЕСЕРТ: ГРУШЕВОЕ ПЮРЕ С КОРИЦЕЙ</b>
КБЖУ: 180 ккал • Белки: 8г • Жиры: 6г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Груши - 4 шт (растворимая клетчатка)
• Творог - 150 г (белок)
• Корица - 2 ч.л. (антиоксиданты)
• Миндаль - 20 г (витамин E)
• Мед - 1 ч.л. (натуральные ферменты)

<b>Приготовление (15 минут):</b>
1. Груши запечь 12 минут до мягкости
2. Размять вилкой в пюре
3. Смешать с творогом и корицей
4. Украсить миндалем и медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Груши содержат сорбитол и пищевые волокна, которые мягко стимулируют перистальтику кишечника и способствуют естественному очищению организма.
"""
        benefits = """• 🍐 Сорбитол для мягкого очищения
• 🧀 Белок для ночного восстановления
• 🟤 Антиоксиданты для защиты клеток
• 🌰 Витамин E для здоровья кожи"""
        
        return self.visual_manager.generate_attractive_post(
            "🍐 ДЕТОКС-ДЕСЕРТ: ГРУШЕВОЕ ПЮРЕ С КОРИЦЕЙ",
            content, "detox_dessert", benefits
        )

    def generate_alkaline_dessert(self):
        """Щелочной десерт"""
        content = """
🍈 <b>ЩЕЛОЧНОЙ ДЕСЕРТ: ДЫНЯ С МЯТОЙ</b>
КБЖУ: 150 ккал • Белки: 6г • Жиры: 4г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Дыня - 600 г (цитруллин)
• Лайм - 1 шт (цитраты)
• Мята - 20 г (ментол)
• Семена чиа - 1 ст.л. (Омега-3)
• Кокосовая стружка - 2 ст.л. (клетчатка)

<b>Приготовление (10 минут):</b>
1. Дыню нарезать кубиками
2. Сбрызнуть соком лайма
3. Добавить мяту и семена чиа
4. Посыпать кокосовой стружкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Дыня имеет высокий pH (8.5-9.0) и богата минералами, которые помогают нейтрализовать кислотную нагрузку и поддерживать оптимальный кислотно-щелочной баланс.
"""
        benefits = """• ⚖️ Нейтрализация кислотности
• 💧 Глубокая гидратация
• 🍈 Цитруллин для детокса аммиака
• 🌿 Освежающий и очищающий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🍈 ЩЕЛОЧНОЙ ДЕСЕРТ: ДЫНЯ С МЯТОЙ",
            content, "alkaline_dessert", benefits
        )

    def generate_liver_dessert(self):
        """Десерт для поддержки печени"""
        content = """
🍇 <b>ДЕСЕРТ ДЛЯ ПЕЧЕНИ: ВИНОГРАД С ОРЕХАМИ</b>
КБЖУ: 220 ккал • Белки: 10г • Жиры: 12г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Виноград - 300 г (ресвератрол)
• Грецкие орехи - 50 г (аргинин)
• Корица - 1 ч.л. (полифенолы)
• Лимонная цедра - 1 ч.л. (антиоксиданты)
• Мед - 1 ч.л. (ферменты)

<b>Приготовление (5 минут):</b>
1. Виноград промыть и обсушить
2. Орехи измельчить
3. Смешать все ингредиенты
4. Охладить 15 минут перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Ресвератрол из винограда активирует сиртуины - белки долголетия, которые защищают клетки печени от повреждения и способствуют их регенерации.
"""
        benefits = """• 🍇 Активация белков долголетия
• 🛡️ Защита гепатоцитов от повреждения
• 🔄 Стимуляция регенерации печени
• 🌰 Аргинин для детокса аммиака"""
        
        return self.visual_manager.generate_attractive_post(
            "🍇 ДЕСЕРТ ДЛЯ ПЕЧЕНИ: ВИНОГРАД С ОРЕХАМИ",
            content, "liver_dessert", benefits
        )

    def generate_digestive_dessert(self):
        """Десерт для улучшения пищеварения"""
        content = """
🍎 <b>ДЕСЕРТ ДЛЯ ПИЩЕВАРЕНИЯ: ЗАПЕЧЕННЫЕ ЯБЛОКИ</b>
КБЖУ: 190 ккал • Белки: 8г • Жиры: 6г • Углеводы: 30г

<b>Ингредиенты (на 2 порции):</b>
• Яблоки - 4 шт (пектин)
• Корица - 2 ч.л. (эфирные масла)
• Имбирь - 1 ч.л. (гингерол)
• Грецкие орехи - 30 г (Омега-3)
• Мед - 2 ч.л. (пребиотики)

<b>Приготовление (25 минут):</b>
1. Яблоки вымыть и удалить сердцевину
2. Нафаршировать орехами и специями
3. Запекать 20 минут при 180°C
4. Полить медом перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пектин из яблок образует гель в кишечнике, замедляя всасывание сахаров и способствуя росту полезных бактерий, производящих короткоцепочечные жирные кислоты.
"""
        benefits = """• 🍎 Пектин для здоровья микробиоты
• 🔥 Противовоспалительное действие
• 🦠 Стимуляция роста полезных бактерий
• 🧂 Регуляция уровня сахара в крови"""
        
        return self.visual_manager.generate_attractive_post(
            "🍎 ДЕСЕРТ ДЛЯ ПИЩЕВАРЕНИЯ: ЗАПЕЧЕННЫЕ ЯБЛОКИ",
            content, "digestive_dessert", benefits
        )

    def generate_antioxidant_dessert(self):
        """Антиоксидантный десерт"""
        content = """
🫐 <b>АНТИОКСИДАНТНЫЙ ДЕСЕРТ: ЯГОДНОЕ ЖЕЛЕ</b>
КБЖУ: 160 ккал • Белки: 12г • Жиры: 4г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Смесь ягод - 300 г (антоцианы)
• Желатин - 20 г (коллаген)
• Стевия - по вкусу
• Лимонный сок - 1 ст.л. (витамин C)
• Мята - для украшения

<b>Приготовление (15 минут + охлаждение):</b>
1. Ягоды взбить в пюре
2. Растворить желатин
3. Смешать все ингредиенты
4. Разлить по формам, охладить 4 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод проникают через гематоэнцефалический барьер и накапливаются в областях мозга, ответственных за обучение и память, улучшая когнитивные функции.
"""
        benefits = """• 🧠 Улучшение когнитивных функций
• 🛡️ Защита от окислительного стресса
• 💪 Коллаген для здоровья суставов и кожи
• 🍓 Натуральные антиоксиданты"""
        
        return self.visual_manager.generate_attractive_post(
            "🫐 АНТИОКСИДАНТНЫЙ ДЕСЕРТ: ЯГОДНОЕ ЖЕЛЕ",
            content, "antioxidant_dessert", benefits
        )

    def generate_hydration_dessert(self):
        """Гидратирующий десерт"""
        content = """
🍉 <b>ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА</b>
КБЖУ: 140 ккал • Белки: 6г • Жиры: 2г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 800 г (ликопин)
• Лайм - 1 шт (цитраты)
• Мята - 15 г (ментол)
• Стевия - по вкусу
• Вода - 100 мл

<b>Приготовление (10 минут + заморозка):</b>
1. Арбуз очистить от косточек и взбить
2. Добавить сок лайма и стевию
3. Разлить по формам и заморозить
4. Перед подачей размять вилкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз содержит L-цитруллин, который преобразуется в L-аргинин и способствует расширению сосудов, улучшая кровообращение и доставку питательных веществ к клеткам.
"""
        benefits = """• 💧 Глубокая гидратация
• 🩸 Улучшение микроциркуляции
• 🍉 Ликопин для защиты от УФ-излучения
• 🧊 Освежающий и тонизирующий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "🍉 ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА",
            content, "hydration_dessert", benefits
        )

    def generate_fiber_dessert(self):
        """Десерт, богатый клетчаткой"""
        content = """
🌰 <b>ДЕСЕРТ С КЛЕТЧАТКОЙ: ФИНИКОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 8 трюфелей):</b>
• Финики - 200 г (растворимая клетчатка)
• Овсяные хлопья - 80 г (нерастворимая клетчатка)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Кокосовая стружка - 50 г (МСТ)
• Корица - 1 ч.л. (антиоксиданты)

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание растворимой и нерастворимой клетчатки обеспечивает комплексное воздействие на пищеварительную систему: замедление всасывания сахаров и ускорение кишечного транзита.
"""
        benefits = """• 🌾 Комплексное воздействие клетчатки
• 🍫 Антиоксиданты для защиты сосудов
• 🥥 Быстрая энергия без скачков сахара
• 🧂 Натуральная сладость без рафинированного сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🌰 ДЕСЕРТ С КЛЕТЧАТКОЙ: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "fiber_dessert", benefits
        )

# Создание экземпляра генератора
monday_generator = MondayContentGenerator()
class TuesdayContentGenerator:
    """Генератор контента для вторника - белки и мышечная масса"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_protein_power_breakfast(self):
        """Белковый завтрак для энергии и сытости"""
        content = """
🍗 <b>БЕЛКОВЫЙ ЗАВТРАК: КУРИНЫЕ ОМЛЕТ-МАФФИНЫ</b>
КБЖУ: 350 ккал • Белки: 40г • Жиры: 18г • Углеводы: 8г

<b>Ингредиенты (на 4 маффина):</b>
• Куриное филе - 300 г (лейцин)
• Яйца - 4 шт (полноценный белок)
• Шпинат - 100 г (железо)
• Сыр пармезан - 50 г (кальций)
• Болгарский перец - 1 шт (витамин C)

<b>Приготовление (25 минут):</b>
1. Курицу нарезать кубиками, обжарить
2. Смешать с взбитыми яйцами и овощами
3. Разлить по формам для маффинов
4. Запекать 20 минут при 180°C

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лейцин из куриного филе активирует mTOR pathway - ключевой сигнальный путь для синтеза мышечного белка, особенно важный после ночного голодания.
"""
        benefits = """• 💪 Лейцин для активации мышечного синтеза
• 🥚 Полный набор аминокислот
• 🧀 Кальций для костей и нервной системы
• 🌿 Железо для оксигенации мышц"""
        
        return self.visual_manager.generate_attractive_post(
            "🍗 БЕЛКОВЫЙ ЗАВТРАК: КУРИНЫЕ ОМЛЕТ-МАФФИНЫ",
            content, "protein_breakfast", benefits
        )

    def generate_amino_acid_breakfast(self):
        """Завтрак с полным набором аминокислот"""
        content = """
🥛 <b>АМИНОКИСЛОТНЫЙ ЗАВТРАК: ТВОРОГ С ОРЕХАМИ</b>
КБЖУ: 380 ккал • Белки: 38г • Жиры: 20г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Грецкие орехи - 50 г (аргинин)
• Миндаль - 30 г (валин)
• Семена тыквы - 30 г (цистеин)
• Ягоды годжи - 20 г (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Творог выложить в миски
2. Добавить орехи и семена
3. Украсить ягодами годжи
4. Можно добавить ложку меда

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Комбинация животных и растительных белков обеспечивает полный спектр незаменимых аминокислот, необходимых для синтеза мышечной ткани и ферментов.
"""
        benefits = """• 🧬 Полный спектр аминокислот
• ⏱️ Медленное и быстрое усвоение белка
• 🌰 Аргинин для кровообращения
• 🍒 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🥛 АМИНОКИСЛОТНЫЙ ЗАВТРАК: ТВОРОГ С ОРЕХАМИ",
            content, "amino_breakfast", benefits
        )

    def generate_muscle_breakfast(self):
        """Завтрак для роста мышц"""
        content = """
💪 <b>ЗАВТРАК ДЛЯ МЫШЦ: ГОВЯЖЬИ ОЛАДЬИ</b>
КБЖУ: 420 ккал • Белки: 45г • Жиры: 22г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Говяжий фарш - 400 г (гемовое железо)
• Яйца - 2 шт (холин)
• Лук - 1 шт (кверцетин)
• Овсяные отруби - 40 г (клетчатка)
• Специи: паприка, чесночный порошок

<b>Приготовление (20 минут):</b>
1. Смешать все ингредиенты
2. Сформировать оладьи
3. Обжарить по 4-5 минут с каждой стороны
4. Подавать с овощным салатом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гемовое железо из красного мяса обладает высокой биодоступностью (15-35%) и необходимо для производства гемоглобина, обеспечивающего оксигенацию мышц во время тренировок.
"""
        benefits = """• 🥩 Высокая биодоступность железа
• 💨 Улучшение оксигенации мышц
• 🧠 Холин для нервно-мышечной передачи
• 🌾 Клетчатка для контроля аппетита"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 ЗАВТРАК ДЛЯ МЫШЦ: ГОВЯЖЬИ ОЛАДЬИ",
            content, "muscle_breakfast", benefits
        )

    def generate_recovery_breakfast(self):
        """Завтрак для восстановления"""
        content = """
🔄 <b>ЗАВТРАК ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ЯЙЦОМ</b>
КБЖУ: 450 ккал • Белки: 42г • Жиры: 28г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 300 г (Омега-3)
• Яйца - 4 шт (протеин)
• Авокадо - 1 шт (витамин E)
• Шпинат - 100 г (магний)
• Лимон - 1/2 шт (витамин C)

<b>Приготовление (15 минут):</b>
1. Лосось приготовить на гриле 8 минут
2. Яйца сварить вкрутую
3. Авокадо нарезать ломтиками
4. Подавать со шпинатом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты из лосося уменьшают воспаление после тренировок и ускоряют восстановление мышечных волокон, снижая болезненность.
"""
        benefits = """• 🐟 Снижение воспаления после нагрузок
• 🔄 Ускорение мышечного восстановления
• 🥑 Антиоксиданты для защиты клеток
• 🥬 Магний для расслабления мышц"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ЗАВТРАК ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ЯЙЦОМ",
            content, "recovery_breakfast", benefits
        )

    def generate_energy_breakfast(self):
        """Энергетический белковый завтрак"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ИНДЕЙКА С КИНОА</b>
КБЖУ: 400 ккал • Белки: 38г • Жиры: 15г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Киноа - 100 г (полноценный белок)
• Брокколи - 200 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Оливковое масло - 1 ст.л.

<b>Приготовление (25 минут):</b>
1. Индейку нарезать и обжарить
2. Киноа отварить 15 минут
3. Овощи приготовить на пару
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Триптофан из индейки является предшественником серотонина, который улучшает настроение и мотивацию, важные для регулярных тренировок.
"""
        benefits = """• 🦃 Триптофан для хорошего настроения
• 🌾 Полноценный растительный белок
• 🥦 Антиоксиданты для защиты
• 🔋 Стабильная энергия на 4-5 часов"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ИНДЕЙКА С КИНОА",
            content, "energy_breakfast", benefits
        )

    def generate_strength_breakfast(self):
        """Завтрак для силы"""
        content = """
🏋️ <b>ЗАВТРАК ДЛЯ СИЛЫ: ТУНЕЦ С БОБАМИ</b>
КБЖУ: 430 ккал • Белки: 48г • Жиры: 18г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Тунец консервированный - 2 банки (селен)
• Бобы эдамаме - 200 г (растительный белок)
• Яйца - 2 шт (витамин D)
• Руккола - 100 г (кальций)
• Оливковое масло - 2 ст.л.

<b>Приготовление (10 минут):</b>
1. Бобы отварить 5 минут
2. Смешать все ингредиенты
3. Заправить оливковым маслом
4. Посолить по вкусу

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Селен из тунца является кофактором глутатионпероксидазы - ключевого антиоксидантного фермента, защищающего клетки от окислительного стресса во время интенсивных тренировок.
"""
        benefits = """• 🐟 Селен для антиоксидантной защиты
• 🌱 Растительный и животный белок
• 🥚 Витамин D для костей и иммунитета
• 🥬 Кальций для мышечных сокращений"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ ЗАВТРАК ДЛЯ СИЛЫ: ТУНЕЦ С БОБАМИ",
            content, "strength_breakfast", benefits
        )

    def generate_endurance_breakfast(self):
        """Завтрак для выносливости"""
        content = """
🏃 <b>ЗАВТРАК ДЛЯ ВЫНОСЛИВОСТИ: ЯЙЦА С КУРИЦЕЙ</b>
КБЖУ: 460 ккал • Белки: 52г • Жиры: 24г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Куриная грудка - 400 г (белок)
• Яйца - 6 шт (аминокислоты)
• Шпинат - 150 г (нитраты)
• Грибы - 200 г (витамин D)
• Сыр чеддер - 80 г (кальций)

<b>Приготовление (20 минут):</b>
1. Курицу нарезать и обжарить
2. Яйца взбить и приготовить скрэмбл
3. Грибы обжарить отдельно
4. Смешать все ингредиенты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из шпината улучшают эффективность митохондрий и увеличивают выносливость, позволяя тренироваться дольше и интенсивнее.
"""
        benefits = """• 🥬 Улучшение митохондриальной функции
• 💪 Высокое содержание белка
• 🍄 Витамин D для силы и иммунитета
• 🧀 Кальций для нервно-мышечной проводимости"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃 ЗАВТРАК ДЛЯ ВЫНОСЛИВОСТИ: ЯЙЦА С КУРИЦЕЙ",
            content, "endurance_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_protein_lunch(self):
        """Белковый обед для сытости"""
        content = """
🍖 <b>БЕЛКОВЫЙ ОБЕД: ГОВЯДИНА С ОВОЩАМИ</b>
КБЖУ: 480 ккал • Белки: 50г • Жиры: 25г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (креатин)
• Брокколи - 300 г (сульфорафан)
• Цветная капуста - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Говядину нарезать и обжарить
2. Овощи приготовить на пару
3. Смешать мясо с овощами
4. Заправить оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Креатин из красного мяса накапливается в мышцах и служит быстрым источником энергии для высокоинтенсивных упражнений, увеличивая силу и мощность.
"""
        benefits = """• 🥩 Креатин для силы и мощности
• 🥦 Антиоксиданты для восстановления
• 🔥 Высокое содержание белка
• 💪 Поддержка мышечной массы"""
        
        return self.visual_manager.generate_attractive_post(
            "🍖 БЕЛКОВЫЙ ОБЕД: ГОВЯДИНА С ОВОЩАМИ",
            content, "protein_lunch", benefits
        )

    def generate_amino_lunch(self):
        """Обед с полным аминокислотным профилем"""
        content = """
🧬 <b>АМИНОКИСЛОТНЫЙ ОБЕД: ИНДЕЙКА С ЧЕЧЕВИЦЕЙ</b>
КБЖУ: 420 ккал • Белки: 45г • Жиры: 15г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Чечевица - 150 г (лизин)
• Шпинат - 200 г (железо)
• Лук - 1 шт (кверцетин)
• Чеснок - 3 зубчика (аллицин)

<b>Приготовление (35 минут):</b>
1. Индейку нарезать и обжарить
2. Чечевицу отварить 25 минут
3. Овощи обжарить с чесноком
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание животного и растительного белка обеспечивает оптимальный аминокислотный профиль, покрывая потребности в незаменимых аминокислотах для синтеза мышечной ткани.
"""
        benefits = """• 🦃 Оптимальный аминокислотный профиль
• 🌱 Растительный белок с клетчаткой
• 🥬 Железо для оксигенации
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🧬 АМИНОКИСЛОТНЫЙ ОБЕД: ИНДЕЙКА С ЧЕЧЕВИЦЕЙ",
            content, "amino_lunch", benefits
        )

    def generate_muscle_lunch(self):
        """Обед для роста мышц"""
        content = """
💪 <b>ОБЕД ДЛЯ МЫШЦ: КУРИЦА С НУТОМ</b>
КБЖУ: 450 ккал • Белки: 48г • Жиры: 18г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (лейцин)
• Нут - 200 г (растительный белок)
• Болгарский перец - 2 шт (витамин C)
• Брокколи - 250 г (сульфорафан)
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (40 минут):</b>
1. Нут замочить на ночь, отварить 30 минут
2. Курицу нарезать и обжарить
3. Овощи приготовить на пару
4. Смешать все с куркумой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лейцин из курицы является ключевым регулятором синтеза мышечного белка, активируя mTOR комплекс - главный сигнальный путь мышечного роста.
"""
        benefits = """• 🍗 Лейцин для активации мышечного роста
• 🌱 Растительный белок с клетчаткой
• 🟤 Противовоспалительное действие
• 🥦 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 ОБЕД ДЛЯ МЫШЦ: КУРИЦА С НУТОМ",
            content, "muscle_lunch", benefits
        )

    def generate_recovery_lunch(self):
        """Обед для восстановления"""
        content = """
🔄 <b>ОБЕД ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С КИНОА</b>
КБЖУ: 520 ккал • Белки: 42г • Жиры: 28г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Киноа - 150 г (полноценный белок)
• Авокадо - 1 шт (витамин E)
• Спаржа - 200 г (фолат)
• Лимон - 1 шт (витамин C)

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Киноа отварить 15 минут
3. Спаржу приготовить на гриле
4. Подавать с авокадо и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты модулируют воспалительный ответ после тренировок, ускоряя восстановление и уменьшая мышечную болезненность.
"""
        benefits = """• 🐟 Снижение воспаления после нагрузок
• 🌾 Полноценный растительный белок
• 🥑 Антиоксиданты для защиты клеток
• 🌱 Фолат для синтеза ДНК"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ОБЕД ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С КИНОА",
            content, "recovery_lunch", benefits
        )

    def generate_energy_lunch(self):
        """Энергетический обед"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ ОБЕД: ИНДЕЙКА С БАТАТОМ</b>
КБЖУ: 480 ккал • Белки: 45г • Жиры: 15г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Батат - 400 г (сложные углеводы)
• Брокколи - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Батат запечь 25 минут
2. Индейку нарезать и обжарить
3. Овощи приготовить на пару
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сложные углеводы из батата обеспечивают постепенное высвобождение глюкозы, поддерживая стабильный уровень энергии и предотвращая резкие скачки инсулина.
"""
        benefits = """• 🍠 Стабильная энергия на 4-5 часов
• 🦃 Триптофан для настроения и сна
• 🥦 Антиоксиданты для защиты
• 🔥 Сбалансированное соотношение БЖУ"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ОБЕД: ИНДЕЙКА С БАТАТОМ",
            content, "energy_lunch", benefits
        )

    def generate_strength_lunch(self):
        """Обед для силы"""
        content = """
🏋️ <b>ОБЕД ДЛЯ СИЛЫ: ГОВЯДИНА С ТЫКВОЙ</b>
КБЖУ: 500 ккал • Белки: 52г • Жиры: 22г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (креатин)
• Тыква - 500 г (бета-каротин)
• Шпинат - 200 г (железо)
• Чеснок - 4 зубчика (аллицин)
• Розмарин - 2 веточки (антиоксиданты)

<b>Приготовление (40 минут):</b>
1. Тыкву запечь 30 минут
2. Говядину обжарить с розмарином
3. Шпинат обжарить с чесноком
4. Подавать все вместе

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Креатин фосфат служит быстрым источником энергии для мышечных сокращений во время высокоинтенсивных упражнений, увеличивая максимальную силу на 5-15%.
"""
        benefits = """• 🥩 Креатин для увеличения силы
• 🎃 Бета-каротин для антиоксидантной защиты
• 🥬 Железо для оксигенации мышц
• 🌿 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ ОБЕД ДЛЯ СИЛЫ: ГОВЯДИНА С ТЫКВОЙ",
            content, "strength_lunch", benefits
        )

    def generate_endurance_lunch(self):
        """Обед для выносливости"""
        content = """
🏃 <b>ОБЕД ДЛЯ ВЫНОСЛИВОСТИ: КУРИЦА С КИНОА</b>
КБЖУ: 460 ккал • Белки: 48г • Жиры: 18г • Углеводы: 38г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (белок)
• Киноа - 150 г (магний)
• Свекла - 2 шт (нитраты)
• Яблоко - 1 шт (кверцетин)
• Грецкие орехи - 40 г (Омега-3)

<b>Приготовление (35 минут):</b>
1. Курицу нарезать и обжарить
2. Киноа отварить 15 минут
3. Свеклу запечь 30 минут
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают эффективность митохондрий и увеличивают выносливость на 15-25%, позволяя тренироваться дольше и интенсивнее.
"""
        benefits = """• 🍠 Улучшение митохондриальной функции
• 🍗 Высокое содержание белка
• 🌰 Омега-3 для противовоспалительного действия
• 🍎 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃 ОБЕД ДЛЯ ВЫНОСЛИВОСТИ: КУРИЦА С КИНОА",
            content, "endurance_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_protein_dinner(self):
        """Белковый ужин для ночного восстановления"""
        content = """
🍖 <b>БЕЛКОВЫЙ УЖИН: ТВОРОГ С ОРЕХАМИ</b>
КБЖУ: 320 ккал • Белки: 35г • Жиры: 16г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Миндаль - 40 г (витамин E)
• Грецкие орехи - 30 г (Омега-3)
• Семена тыквы - 20 г (цинк)
• Корица - 1 ч.л. (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Добавить орехи и семена
3. Посыпать корицей
4. Можно добавить ягоды

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога усваивается медленно (6-8 часов), обеспечивая постоянное поступление аминокислот в кровь в течение ночи и предотвращая катаболизм мышечной ткани.
"""
        benefits = """• ⏱️ Медленное высвобождение аминокислот
• 💪 Предотвращение ночного катаболизма
• 🌰 Цинк для синтеза тестостерона
• 🟤 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🍖 БЕЛКОВЫЙ УЖИН: ТВОРОГ С ОРЕХАМИ",
            content, "protein_dinner", benefits
        )

    def generate_amino_dinner(self):
        """Ужин с полным аминокислотным профилем"""
        content = """
🧬 <b>АМИНОКИСЛОТНЫЙ УЖИН: РЫБА С ЧЕЧЕВИЦЕЙ</b>
КБЖУ: 380 ккал • Белки: 42г • Жиры: 15г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Белая рыба - 400 г (легкий белок)
• Чечевица - 150 г (лизин)
• Шпинат - 200 г (железо)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (эфирные масла)

<b>Приготовление (25 минут):</b>
1. Рыбу приготовить на пару 12 минут
2. Чечевицу отварить 20 минут
3. Шпинат обжарить 3 минуты
4. Подавать с лимоном и укропом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание животного и растительного белка обеспечивает оптимальный аминокислотный профиль для ночного восстановления и синтеза мышечной ткани.
"""
        benefits = """• 🐟 Легкоусвояемый белок
• 🌱 Растительный белок с клетчаткой
• 🥬 Железо для оксигенации
• 🍋 Витамин C для усвоения железа"""
        
        return self.visual_manager.generate_attractive_post(
            "🧬 АМИНОКИСЛОТНЫЙ УЖИН: РЫБА С ЧЕЧЕВИЦЕЙ",
            content, "amino_dinner", benefits
        )

    def generate_muscle_dinner(self):
        """Ужин для роста мышц"""
        content = """
💪 <b>УЖИН ДЛЯ МЫШЦ: КУРИЦА С БРОККОЛИ</b>
КБЖУ: 350 ккал • Белки: 45г • Жиры: 14г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (лейцин)
• Брокколи - 400 г (сульфорафан)
• Цветная капуста - 300 г (глюкозинолаты)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Курицу нарезать и обжарить
2. Овощи приготовить на пару
3. Смешать с чесноком и маслом
4. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лейцин из курицы активирует синтез мышечного белка во время сна, когда процессы восстановления и роста наиболее активны.
"""
        benefits = """• 🍗 Активация ночного синтеза белка
• 🥦 Антиоксиданты для восстановления
• 🧄 Противовоспалительные свойства
• 🔥 Высокое содержание белка"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 УЖИН ДЛЯ МЫШЦ: КУРИЦА С БРОККОЛИ",
            content, "muscle_dinner", benefits
        )

    def generate_recovery_dinner(self):
        """Ужин для восстановления"""
        content = """
🔄 <b>УЖИН ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ШПИНАТОМ</b>
КБЖУ: 420 ккал • Белки: 38г • Жиры: 28г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Шпинат - 400 г (магний)
• Грибы - 200 г (витамин D)
• Лимон - 1/2 шт (витамин C)
• Оливковое масло - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Лосось запечь 15 минут
2. Шпинат и грибы обжарить
3. Полить лимонным соком
4. Заправить оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты модулируют воспалительные процессы во время сна, ускоряя восстановление поврежденных мышечных волокон.
"""
        benefits = """• 🐟 Снижение воспаления во время сна
• 🥬 Магний для расслабления мышц
• 🍄 Витамин D для иммунитета
• 🍋 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ШПИНАТОМ",
            content, "recovery_dinner", benefits
        )

    def generate_energy_dinner(self):
        """Энергетический ужин"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ УЖИН: ИНДЕЙКА С ОВОЩАМИ</b>
КБЖУ: 380 ккал • Белки: 42г • Жиры: 18г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Цукини - 2 шт (калий)
• Болгарский перец - 2 шт (витамин C)
• Лук - 1 шт (кверцетин)
• Розмарин - 2 веточки

<b>Приготовление (25 минут):</b>
1. Индейку нарезать и обжарить
2. Овощи нарезать кубиками
3. Тушить все вместе 15 минут
4. Добавить розмарин в конце

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Триптофан из индейки способствует выработке мелатонина и серотонина, улучшая качество сна, что критически важно для восстановления после тренировок.
"""
        benefits = """• 🦃 Улучшение качества сна
• 🥒 Легкие овощи для пищеварения
• 🌿 Антиоксиданты для защиты
• 💤 Поддержка ночного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ УЖИН: ИНДЕЙКА С ОВОЩАМИ",
            content, "energy_dinner", benefits
        )

    def generate_strength_dinner(self):
        """Ужин для силы"""
        content = """
🏋️ <b>УЖИН ДЛЯ СИЛЫ: ГОВЯДИНА С КАПУСТОЙ</b>
КБЖУ: 400 ккал • Белки: 45г • Жиры: 20г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Говяжий фарш - 400 г (креатин)
• Капуста белокочанная - 500 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Томатная паста - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Фарш обжарить с луком
2. Капусту нашинковать
3. Тушить все вместе 20 минут
4. Добавить томатную пасту

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Креатин из говядины пополняет запасы креатинфосфата в мышцах, обеспечивая готовность к высокоинтенсивным нагрузкам на следующий день.
"""
        benefits = """• 🥩 Восполнение запасов креатина
• 🥬 Антиоксиданты для защиты
• 🥕 Бета-каротин для иммунитета
• 🔥 Высокое содержание белка"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ УЖИН ДЛЯ СИЛЫ: ГОВЯДИНА С КАПУСТОЙ",
            content, "strength_dinner", benefits
        )

    def generate_endurance_dinner(self):
        """Ужин для выносливости"""
        content = """
🏃 <b>УЖИН ДЛЯ ВЫНОСЛИВОСТИ: КУРИЦА С СВЕКЛОЙ</b>
КБЖУ: 420 ккал • Белки: 48г • Жиры: 16г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (белок)
• Свекла - 3 шт (нитраты)
• Яблоко - 1 шт (пектин)
• Грецкие орехи - 40 г (Омега-3)
• Лимонный сок - 2 ст.л.

<b>Приготовление (40 минут):</b>
1. Курицу нарезать и обжарить
2. Свеклу запечь 35 минут
3. Яблоко натереть на терке
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают эффективность использования кислорода мышцами, увеличивая выносливость и отдаляя наступление усталости.
"""
        benefits = """• 🍠 Улучшение оксигенации мышц
• 🍗 Высокое содержание белка
• 🌰 Омега-3 для противовоспалительного действия
• 🍎 Пектин для здоровья кишечника"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃 УЖИН ДЛЯ ВЫНОСЛИВОСТИ: КУРИЦА С СВЕКЛОЙ",
            content, "endurance_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_protein_dessert(self):
        """Белковый десерт"""
        content = """
🍦 <b>БЕЛКОВЫЙ ДЕСЕРТ: ТВОРОЖНО-ЯГОДНОЕ МОРОЖЕНОЕ</b>
КБЖУ: 280 ккал • Белки: 32г • Жиры: 8г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Ягоды замороженные - 200 г (антиоксиданты)
• Протеин ванильный - 1 мерная ложка
• Миндальное молоко - 100 мл
• Стевия - по вкусу

<b>Приготовление (10 минут + заморозка):</b>
1. Все ингредиенты взбить в блендере
2. Перелить в контейнер
3. Заморозить 4 часа
4. Перед подачей размять вилкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога обеспечивает медленное высвобождение аминокислот в течение ночи, поддерживая положительный азотистый баланс и предотвращая катаболизм.
"""
        benefits = """• ⏱️ Медленное высвобождение аминокислот
• 🍓 Антиоксиданты для восстановления
• 💪 Высокое содержание белка
• 🧊 Освежающий и питательный"""
        
        return self.visual_manager.generate_attractive_post(
            "🍦 БЕЛКОВЫЙ ДЕСЕРТ: ТВОРОЖНО-ЯГОДНОЕ МОРОЖЕНОЕ",
            content, "protein_dessert", benefits
        )

    def generate_amino_dessert(self):
        """Десерт с полным аминокислотным профилем"""
        content = """
🧬 <b>АМИНОКИСЛОТНЫЙ ДЕСЕРТ: ОРЕХОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 320 ккал • Белки: 18г • Жиры: 22г • Углеводы: 18г

<b>Ингредиенты (на 8 трюфелей):</b>
• Миндаль - 100 г (валин)
• Грецкие орехи - 100 г (аргинин)
• Финики - 150 г (натуральная сладость)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут):</b>
1. Орехи измельчить в блендере
2. Добавить финики и какао
3. Сформировать шарики
4. Обвалять в кокосовой стружке

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание разных видов орехов обеспечивает полный спектр аминокислот, включая BCAA, необходимых для восстановления и роста мышечной ткани.
"""
        benefits = """• 🌰 Полный спектр аминокислот
• 🍫 Антиоксиданты для защиты сосудов
• 🥥 Натуральная сладость без сахара
• 💪 Поддержка мышечного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🧬 АМИНОКИСЛОТНЫЙ ДЕСЕРТ: ОРЕХОВЫЕ ТРЮФЕЛИ",
            content, "amino_dessert", benefits
        )

    def generate_muscle_dessert(self):
        """Десерт для роста мышц"""
        content = """
💪 <b>ДЕСЕРТ ДЛЯ МЫШЦ: ПРОТЕИНОВЫЙ ПУДИНГ</b>
КБЖУ: 300 ккал • Белки: 35г • Жиры: 12г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Протеин шоколадный - 1 мерная ложка
• Семена чиа - 2 ст.л. (Омега-3)
• Какао-порошок - 1 ст.л. (флавоноиды)
• Стевия - по вкусу

<b>Приготовление (5 минут + настаивание):</b>
1. Смешать все ингредиенты
2. Охладить 2 часа
3. Украсить ягодами
4. Подавать охлажденным

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Белок из йогурта и протеина обеспечивает быстрое поступление аминокислот в кровоток, запуская синтез мышечного белка после вечерней тренировки.
"""
        benefits = """• 🚀 Быстрое усвоение белка
• 🦠 Пробиотики для здоровья кишечника
• 🌱 Омега-3 для противовоспалительного действия
• 🍫 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 ДЕСЕРТ ДЛЯ МЫШЦ: ПРОТЕИНОВЫЙ ПУДИНГ",
            content, "muscle_dessert", benefits
        )

    def generate_recovery_dessert(self):
        """Десерт для восстановления"""
        content = """
🔄 <b>ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ЯГОДНЫЙ ПАРФЕ</b>
КБЖУ: 280 ккал • Белки: 25г • Жиры: 10г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Творог - 300 г (казеин)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Миндаль - 30 г (витамин E)
• Корица - 1 ч.л. (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Слоями выложить творог и ягоды
2. Посыпать миндалем и корицей
3. Охладить 15 минут
4. Подавать сразу

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод уменьшают окислительный стресс после тренировок, ускоряя восстановление и уменьшая повреждение мышечных волокон.
"""
        benefits = """• 🍓 Снижение окислительного стресса
• 🧀 Медленный белок для ночного восстановления
• 🌰 Витамин E для защиты клеток
• 🟤 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ЯГОДНЫЙ ПАРФЕ",
            content, "recovery_dessert", benefits
        )

    def generate_energy_dessert(self):
        """Энергетический десерт"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЕ РОЛЛЫ</b>
КБЖУ: 320 ккал • Белки: 22г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (калий)
• Арахисовая паста - 4 ст.л. (белок)
• Овсяные хлопья - 60 г (углеводы)
• Кокосовая стружка - 2 ст.л.
• Корица - 1 ч.л.

<b>Приготовление (10 минут):</b>
1. Бананы размять вилкой
2. Смешать с арахисовой пастой и овсянкой
3. Сформировать роллы
4. Обвалять в кокосовой стружке с корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Калий из бананов восстанавливает электролитный баланс после тренировок, предотвращая мышечные судороги и улучшая нервно-мышечную проводимость.
"""
        benefits = """• 🍌 Восстановление электролитного баланса
• 🥜 Белок и полезные жиры
• 🌾 Сложные углеводы
• 🟤 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЕ РОЛЛЫ",
            content, "energy_dessert", benefits
        )

    def generate_strength_dessert(self):
        """Десерт для силы"""
        content = """
🏋️ <b>ДЕСЕРТ ДЛЯ СИЛЫ: ШОКОЛАДНЫЕ КОНФЕТЫ</b>
КБЖУ: 350 ккал • Белки: 28г • Жиры: 20г • Углеводы: 18г

<b>Ингредиенты (на 8 конфет):</b>
• Протеин шоколадный - 2 мерные ложки
• Арахисовая паста - 4 ст.л.
• Кокосовое масло - 2 ст.л. (МСТ)
• Какао-порошок - 2 ст.л.
• Стевия - по вкусу

<b>Приготовление (15 минут + охлаждение):</b>
1. Смешать все ингредиенты
2. Сформировать конфеты
3. Охладить 2 часа
4. Хранить в холодильнике

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Среднецепочечные триглицериды (МСТ) из кокосового масла быстро метаболизируются в печени, производя кетоновые тела - эффективный источник энергии для мозга и мышц.
"""
        benefits = """• 🥥 Быстрая энергия для мозга и мышц
• 💪 Высокое содержание белка
• 🍫 Антиоксиданты для защиты
• 🔥 Поддержка метаболизма"""
        
        return self.visual_manager.generate_attractive_post(
            "🏋️ ДЕСЕРТ ДЛЯ СИЛЫ: ШОКОЛАДНЫЕ КОНФЕТЫ",
            content, "strength_dessert", benefits
        )

    def generate_endurance_dessert(self):
        """Десерт для выносливости"""
        content = """
🏃 <b>ДЕСЕРТ ДЛЯ ВЫНОСЛИВОСТИ: ФИНИКОВЫЕ ШАРИКИ</b>
КБЖУ: 380 ккал • Белки: 25г • Жиры: 15г • Углеводы: 42г

<b>Ингредиенты (на 8 шариков):</b>
• Финики - 200 г (натуральные сахара)
• Овсяные хлопья - 100 г (сложные углеводы)
• Протеин ванильный - 1 мерная ложка
• Семена подсолнечника - 50 г (витамин E)
• Корица - 1 ч.л.

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание простых и сложных углеводов обеспечивает как быстрое, так и продолжительное высвобождение энергии, поддерживая выносливость во время длительных тренировок.
"""
        benefits = """• ⚡ Быстрая и медленная энергия
• 🌾 Сложные углеводы для выносливости
• 🌰 Витамин E для антиоксидантной защиты
• 💪 Белок для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃 ДЕСЕРТ ДЛЯ ВЫНОСЛИВОСТИ: ФИНИКОВЫЕ ШАРИКИ",
            content, "endurance_dessert", benefits
        )

# Создание экземпляра генератора
tuesday_generator = TuesdayContentGenerator()
class WednesdayContentGenerator:
    """Генератор контента для среды - энергия и выносливость"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_energy_boost_breakfast(self):
        """Энергетический завтрак для бодрости"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С СУХОФРУКТАМИ</b>
КБЖУ: 420 ккал • Белки: 18г • Жиры: 12г • Углеводы: 65г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 120 г (сложные углеводы)
• Изюм - 50 г (быстрые углеводы)
• Курага - 50 г (калий)
• Грецкие орехи - 40 г (Омега-3)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (натуральные сахара)

<b>Приготовление (15 минут):</b>
1. Овсянку варить 10 минут
2. Сухофрукты нарезать
3. Добавить орехи и специи
4. Заправить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание сложных и простых углеводов обеспечивает как немедленный приток энергии, так и продолжительное высвобождение глюкозы в кровь.
"""
        benefits = """• ⚡ Мгновенная и продолжительная энергия
• 🍇 Калий для нервной системы
• 🌰 Омега-3 для мозга
• 🟤 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ЗАВТРАК: ОВСЯНКА С СУХОФРУКТАМИ",
            content, "energy_breakfast", benefits
        )

    def generate_carb_loading_breakfast(self):
        """Углеводная загрузка для энергии"""
        content = """
🍌 <b>УГЛЕВОДНЫЙ ЗАВТРАК: БАНАНОВЫЕ ПАНКЕЙКИ</b>
КБЖУ: 380 ккал • Белки: 15г • Жиры: 10г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (калий)
• Овсяная мука - 100 г (сложные углеводы)
• Яйца - 2 шт (белок)
• Молоко - 150 мл (кальций)
• Кленовый сироп - 2 ст.л. (натуральные сахара)
• Корица - 1 ч.л.

<b>Приготовление (20 минут):</b>
1. Бананы размять вилкой
2. Смешать все ингредиенты
3. Жарить на антипригарной сковороде
4. Подавать с сиропом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Калий из бананов поддерживает электролитный баланс и нервно-мышечную проводимость, что критически важно для выносливости.
"""
        benefits = """• 🍌 Калий для нервно-мышечной функции
• 🌾 Сложные углеводы для энергии
• 🥚 Белок для сытости
• 🍯 Натуральная сладость"""
        
        return self.visual_manager.generate_attractive_post(
            "🍌 УГЛЕВОДНЫЙ ЗАВТРАК: БАНАНОВЫЕ ПАНКЕЙКИ",
            content, "carb_breakfast", benefits
        )

    def generate_endurance_breakfast(self):
        """Завтрак для выносливости"""
        content = """
🏃 <b>ЗАВТРАК ДЛЯ ВЫНОСЛИВОСТИ: ГРЕЧКА С МЕДОМ</b>
КБЖУ: 450 ккал • Белки: 18г • Жиры: 8г • Углеводы: 80г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (сложные углеводы)
• Мед - 3 ст.л. (глюкоза)
• Яблоки - 2 шт (фруктоза)
• Корица - 1 ч.л. (антиоксиданты)
• Грецкие орехи - 30 г (Омега-3)

<b>Приготовление (20 минут):</b>
1. Гречку отварить 15 минут
2. Яблоки натереть на терке
3. Смешать все ингредиенты
4. Заправить медом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание глюкозы и фруктозы обеспечивает оптимальное пополнение гликогеновых запасов печени и мышц для продолжительной физической активности.
"""
        benefits = """• 🍯 Оптимальное пополнение гликогена
• 🍎 Разные источники углеводов
• 🌰 Омега-3 для противовоспалительного действия
• 🟤 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🏃 ЗАВТРАК ДЛЯ ВЫНОСЛИВОСТИ: ГРЕЧКА С МЕДОМ",
            content, "endurance_breakfast", benefits
        )

    def generate_mitochondrial_breakfast(self):
        """Завтрак для митохондриальной функции"""
        content = """
🔋 <b>ЗАВТРАК ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ЯЙЦОМ</b>
КБЖУ: 350 ккал • Белки: 20г • Жиры: 12г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 3 шт (нитраты)
• Яйца - 4 шт (белок)
• Шпинат - 100 г (железо)
• Грецкие орехи - 30 г (Омега-3)
• Лимонный сок - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Свеклу запечь 25 минут
2. Яйца сварить вкрутую
3. Шпинат обжарить 2 минуты
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают эффективность митохондрий, увеличивая производство АТФ - основной энергетической валюты клеток.
"""
        benefits = """• 🍠 Улучшение митохондриальной эффективности
• 🥚 Качественный белок
• 🥬 Железо для оксигенации
• 🌰 Омега-3 для защиты клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 ЗАВТРАК ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ЯЙЦОМ",
            content, "mitochondrial_breakfast", benefits
        )

    def generate_hydration_breakfast(self):
        """Гидратирующий завтрак для энергии"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЙ ЗАВТРАК: АРБУЗНЫЙ ФЕТА-САЛАТ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 600 г (ликопин + вода)
• Сыр фета - 150 г (белок)
• Мята - 20 г (ментол)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Арбуз нарезать кубиками
2. Фету раскрошить
3. Смешать с мятой
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз на 92% состоит из воды и содержит электролиты, обеспечивая быструю гидратацию после ночного обезвоживания.
"""
        benefits = """• 💦 Быстрое восполнение жидкости
• 🍉 Ликопин для антиоксидантной защиты
• 🧀 Белок для сытости
• 🌿 Освежающий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЙ ЗАВТРАК: АРБУЗНЫЙ ФЕТА-САЛАТ",
            content, "hydration_breakfast", benefits
        )

    def generate_electrolyte_breakfast(self):
        """Завтрак для электролитного баланса"""
        content = """
⚡ <b>ЭЛЕКТРОЛИТНЫЙ ЗАВТРАК: БАНАН-ШПИНАТ СМУЗИ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 8г • Углеводы: 50г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (калий)
• Шпинат - 100 г (магний)
• Кокосовая вода - 400 мл (электролиты)
• Семена чиа - 2 ст.л. (кальций)
• Мед - 1 ст.л. (глюкоза)

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Подавать сразу
3. Можно добавить лед
4. Украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Кокосовая вода содержит натуральные электролиты (калий, натрий, магний), необходимые для поддержания гидратации и нервно-мышечной функции.
"""
        benefits = """• 🥥 Натуральные электролиты
• 🍌 Калий для мышц
• 🥬 Магний для расслабления
• 🌱 Кальций для нервной проводимости"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭЛЕКТРОЛИТНЫЙ ЗАВТРАК: БАНАН-ШПИНАТ СМУЗИ",
            content, "electrolyte_breakfast", benefits
        )

    def generate_mental_energy_breakfast(self):
        """Завтрак для ментальной энергии"""
        content = """
🧠 <b>ЗАВТРАК ДЛЯ МОЗГА: ЯГОДНЫЙ ПАРФЕ</b>
КБЖУ: 350 ккал • Белки: 20г • Жиры: 12г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Гранола - 60 г (сложные углеводы)
• Мед - 1 ст.л. (глюкоза)

<b>Приготовление (5 минут):</b>
1. Слоями выложить йогурт и ягоды
2. Посыпать гранолой
3. Полить медом
4. Охладить 10 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод улучшают когнитивные функции и защищают нейроны от окислительного стресса, повышая ментальную энергию и концентрацию.
"""
        benefits = """• 🍓 Улучшение когнитивных функций
• 🦠 Пробиотики для мозга и кишечника
• 🌾 Сложные углеводы для энергии
• 🍯 Быстрая глюкоза для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЗАВТРАК ДЛЯ МОЗГА: ЯГОДНЫЙ ПАРФЕ",
            content, "mental_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_sustained_energy_lunch(self):
        """Обед для продолжительной энергии"""
        content = """
🔋 <b>ОБЕД ДЛЯ ПРОДОЛЖИТЕЛЬНОЙ ЭНЕРГИИ: КИНОА С ОВОЩАМИ</b>
КБЖУ: 480 ккал • Белки: 22г • Жиры: 18г • Углеводы: 65г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 150 г (сложные углеводы)
• Батат - 400 г (бета-каротин)
• Брокколи - 300 г (глюкозинолаты)
• Нут - 200 г (растительный белок)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Киноа отварить 15 минут
2. Батат запечь 25 минут
3. Овощи приготовить на пару
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сложные углеводы из киноа и батата обеспечивают медленное высвобождение глюкозы, поддерживая стабильный уровень энергии на 4-6 часов.
"""
        benefits = """• ⏱️ Медленное высвобождение энергии
• 🌾 Полноценный растительный белок
• 🍠 Бета-каротин для иммунитета
• 🥦 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 ОБЕД ДЛЯ ПРОДОЛЖИТЕЛЬНОЙ ЭНЕРГИИ: КИНОА С ОВОЩАМИ",
            content, "sustained_lunch", benefits
        )

    def generate_carb_complex_lunch(self):
        """Обед с комплексом углеводов"""
        content = """
🌾 <b>УГЛЕВОДНЫЙ КОМПЛЕКС: ПАСТА ИЗ ЦЕЛЬНЫХ ЗЛАКОВ</b>
КБЖУ: 520 ккал • Белки: 25г • Жиры: 15г • Углеводы: 80г

<b>Ингредиенты (на 2 порции):</b>
• Паста цельнозерновая - 200 г (сложные углеводы)
• Куриное филе - 300 г (белок)
• Помидоры - 4 шт (ликопин)
• Базилик - 30 г (антиоксиданты)
• Чеснок - 3 зубчика (аллицин)

<b>Приготовление (25 минут):</b>
1. Пасту отварить al dente
2. Курицу нарезать и обжарить
3. Приготовить томатный соус
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цельнозерновая паста имеет низкий гликемический индекс и обеспечивает продолжительное высвобождение энергии без резких скачков сахара.
"""
        benefits = """• 🍝 Медленные углеводы для энергии
• 🍗 Качественный белок
• 🍅 Ликопин для антиоксидантной защиты
• 🌿 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 УГЛЕВОДНЫЙ КОМПЛЕКС: ПАСТА ИЗ ЦЕЛЬНЫХ ЗЛАКОВ",
            content, "carb_complex_lunch", benefits
        )

    def generate_mitochondrial_lunch(self):
        """Обед для митохондриального здоровья"""
        content = """
🔬 <b>ОБЕД ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ГРЕЦКИМИ ОРЕХАМИ</b>
КБЖУ: 450 ккал • Белки: 18г • Жиры: 25г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 4 шт (нитраты)
• Грецкие орехи - 80 г (Омега-3)
• Руккола - 100 г (кальций)
• Козий сыр - 100 г (белок)
• Лимонный сок - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Свеклу запечь 30 минут
2. Орехи измельчить
3. Смешать все ингредиенты
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают эффективность работы митохондрий, увеличивая производство АТФ и улучшая физическую производительность.
"""
        benefits = """• 🍠 Улучшение митохондриальной функции
• 🌰 Омега-3 для противовоспалительного действия
• 🥬 Кальций для нервной проводимости
• 🧀 Белок для сытости"""
        
        return self.visual_manager.generate_attractive_post(
            "🔬 ОБЕД ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ГРЕЦКИМИ ОРЕХАМИ",
            content, "mitochondrial_lunch", benefits
        )

    def generate_hydration_lunch(self):
        """Гидратирующий обед"""
        content = """
💦 <b>ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩНОЙ СУП</b>
КБЖУ: 380 ккал • Белки: 20г • Жиры: 12г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Цукини - 2 шт (вода)
• Сельдерей - 4 стебля (натрий)
• Морковь - 3 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Чечевица - 100 г (белок)
• Зелень - 30 г

<b>Приготовление (35 минут):</b>
1. Овощи нарезать кубиками
2. Чечевицу промыть
3. Варить 30 минут до готовности
4. Добавить зелень перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Овощной суп обеспечивает не только гидратацию, но и электролиты, необходимые для поддержания водно-солевого баланса.
"""
        benefits = """• 💧 Глубокая гидратация
• 🥕 Электролиты для баланса
• 🌱 Растительный белок
• 🧅 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💦 ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩНОЙ СУП",
            content, "hydration_lunch", benefits
        )

    def generate_electrolyte_lunch(self):
        """Обед для электролитного баланса"""
        content = """
⚡ <b>ЭЛЕКТРОЛИТНЫЙ ОБЕД: АВОКАДО-КИНОА САЛАТ</b>
КБЖУ: 520 ккал • Белки: 22г • Жиры: 28г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 150 г (магний)
• Авокадо - 2 шт (калий)
• Помидоры - 3 шт (калий)
• Огурцы - 2 шт (кремний)
• Лимонный сок - 3 ст.л. (цитраты)
• Оливковое масло - 2 ст.л.

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Овощи нарезать кубиками
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Авокадо и помидоры богаты калием, который работает в паре с натрием для поддержания электролитного баланса и нервно-мышечной функции.
"""
        benefits = """• 🥑 Калий для нервно-мышечной функции
• 🍅 Дополнительные источники калия
• 🌾 Магний для расслабления
• 🥒 Кремний для соединительной ткани"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭЛЕКТРОЛИТНЫЙ ОБЕД: АВОКАДО-КИНОА САЛАТ",
            content, "electrolyte_lunch", benefits
        )

    def generate_mental_clarity_lunch(self):
        """Обед для ментальной ясности"""
        content = """
🎯 <b>ОБЕД ДЛЯ МЕНТАЛЬНОЙ ЯСНОСТИ: ЛОСОСЬ С БРОККОЛИ</b>
КБЖУ: 480 ккал • Белки: 38г • Жиры: 28г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Брокколи - 400 г (холин)
• Киноа - 100 г (сложные углеводы)
• Чеснок - 4 зубчика (аллицин)
• Лимон - 1/2 шт (витамин C)

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Брокколи приготовить на пару
3. Киноа отварить 15 минут
4. Подавать с лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты из лосося улучшают текучесть клеточных мембран нейронов, усиливая коммуникацию между клетками мозга.
"""
        benefits = """• 🐟 Улучшение нейронной коммуникации
• 🥦 Холин для памяти
• 🌾 Стабильная энергия для мозга
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ОБЕД ДЛЯ МЕНТАЛЬНОЙ ЯСНОСТИ: ЛОСОСЬ С БРОККОЛИ",
            content, "mental_lunch", benefits
        )

    def generate_energy_dense_lunch(self):
        """Энергоемкий обед"""
        content = """
🔥 <b>ЭНЕРГОЕМКИЙ ОБЕД: КУРИЦА С БАТАТОМ</b>
КБЖУ: 550 ккал • Белки: 45г • Жиры: 18г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (белок)
• Батат - 600 г (сложные углеводы)
• Брокколи - 300 г (клетчатка)
• Морковь - 2 шт (бета-каротин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Батат запечь 30 минут
2. Курицу нарезать и обжарить
3. Овощи приготовить на пару
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Батат содержит резистентный крахмал, который служит пищей для полезных бактерий кишечника и обеспечивает продолжительное высвобождение энергии.
"""
        benefits = """• 🍠 Резистентный крахмал для энергии
• 🍗 Высокое содержание белка
• 🥦 Клетчатка для сытости
• 🥕 Бета-каротин для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЭНЕРГОЕМКИЙ ОБЕД: КУРИЦА С БАТАТОМ",
            content, "energy_dense_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_sustained_energy_dinner(self):
        """Ужин для продолжительной энергии"""
        content = """
🌙 <b>УЖИН ДЛЯ ЭНЕРГИИ: ЧЕЧЕВИЦА С ОВОЩАМИ</b>
КБЖУ: 420 ккал • Белки: 25г • Жиры: 14г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Чечевица - 150 г (растительный белок)
• Цукини - 1 шт (калий)
• Баклажаны - 1 шт (насунин)
• Помидоры - 2 шт (ликопин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

<b>Приготовление (25 минут):</b>
1. Чечевицу отварить 20 минут
2. Овощи нарезать и обжарить
3. Смешать все ингредиенты
4. Тушить 5 минут под крышкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Чечевица содержит медленно усваиваемые углеводы и резистентный крахмал, поддерживающий стабильный уровень сахара в крови и обеспечивающий продолжительное чувство сытости.
"""
        benefits = """• 🌱 Медленные углеводы + растительный белок
• 🥒 Калий для водного баланса
• 🍆 Насунин для клеточных мембран
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН ДЛЯ ЭНЕРГИИ: ЧЕЧЕВИЦА С ОВОЩАМИ",
            content, "sustained_dinner", benefits
        )

    def generate_energy_reserve_dinner(self):
        """Ужин для создания энергетического резерва"""
        content = """
🔋 <b>УЖИН ДЛЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА</b>
КБЖУ: 450 ккал • Белки: 20г • Жиры: 16г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (полноценный белок)
• Тыква - 300 г (бета-каротин)
• Шпинат - 100 г (железо)
• Семена тыквы - 2 ст.л. (цинк)
• Кокосовое молоко - 100 мл (МСТ)
• Куркума - 1 ч.л.

<b>Приготовление (25 минут):</b>
1. Киноа отварить
2. Тыкву запечь 20 минут
3. Шпинат обжарить 2 минуты
4. Смешать все ингредиенты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Среднецепочечные триглицериды (МСТ) из кокосового молока быстро метаболизируются в печени, производя кетоновые тела - эффективный источник энергии для мозга и мышц.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🎃 Бета-каротин для иммунитета
• 🥬 Железо для энергии
• 🥥 МСТ для альтернативного энергоснабжения"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА",
            content, "energy_reserve_dinner", benefits
        )

    def generate_evening_carbs_dinner(self):
        """Вечерние углеводы для энергии"""
        content = """
😴 <b>ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ ЭНЕРГИИ</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Батат - 400 г (сложные углеводы)
• Творог - 150 г (триптофан)
• Банан - 1 шт (мелатонин)
• Корица - 1 ч.л.
• Мед - 1 ст.л.
• Грецкие орехи - 30 г

<b>Приготовление (20 минут):</b>
1. Батат запечь 18 минут
2. Размять вилкой
3. Смешать с творогом и бананом
4. Заправить медом и корицей, посыпать орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Углеводы вечером способствуют транспорту триптофана через гематоэнцефалический барьер, улучшая синтез серотонина и мелатонина - гормонов, регулирующих сон.
"""
        benefits = """• 🍠 Сложные углеводы для сытости
• 🧀 Триптофан для серотонина
• 🍌 Мелатонин для сна
• 🌰 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ ЭНЕРГИИ",
            content, "evening_carbs_dinner", benefits
        )

    def generate_mitochondrial_dinner(self):
        """Ужин для митохондриального здоровья"""
        content = """
🔬 <b>УЖИН ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ГРЕЙПФРУТОМ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 10г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 3 шт (нитраты)
• Грейпфрут - 1 шт (витамин C)
• Руккола - 100 г (кальций)
• Кедровые орехи - 30 г (цинк)
• Лимонный сок - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Свеклу запечь 25 минут
2. Грейпфрут очистить от пленок
3. Смешать все ингредиенты
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают эффективность митохондрий, увеличивая производство АТФ и улучшая энергетический метаболизм клеток.
"""
        benefits = """• 🍠 Улучшение митохондриальной функции
• 🍊 Витамин C для антиоксидантной защиты
• 🥬 Кальций для нервной системы
• 🌰 Цинк для иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "🔬 УЖИН ДЛЯ МИТОХОНДРИЙ: СВЕКЛА С ГРЕЙПФРУТОМ",
            content, "mitochondrial_dinner", benefits
        )

    def generate_hydration_dinner(self):
        """Гидратирующий ужин"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ</b>
КБЖУ: 280 ккал • Белки: 20г • Жиры: 15г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Огурцы - 3 шт (вода)
• Творог - 300 г (белок)
• Укроп - 30 г (эфирные масла)
• Лимонный сок - 2 ст.л. (витамин C)
• Семена подсолнечника - 30 г (витамин E)

<b>Приготовление (10 минут):</b>
1. Огурцы нарезать кубиками
2. Творог смешать с укропом
3. Соединить все ингредиенты
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Огурцы на 95% состоят из структурированной воды, которая легче проникает в клетки и способствует эффективной гидратации на клеточном уровне.
"""
        benefits = """• 💧 Глубокая клеточная гидратация
• 🧀 Легкий белок для ночного восстановления
• 🌱 Кремний для здоровья соединительной ткани
• 🍋 Витамин C для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ",
            content, "hydration_dinner", benefits
        )

    def generate_electrolyte_dinner(self):
        """Ужин для электролитного баланса"""
        content = """
⚡ <b>ЭЛЕКТРОЛИТНЫЙ УЖИН: АВОКАДО-ШПИНАТ САЛАТ</b>
КБЖУ: 420 ккал • Белки: 22г • Жиры: 32г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Авокадо - 2 шт (калий)
• Шпинат - 200 г (магний)
• Помидоры - 3 шт (калий)
• Сыр фета - 150 г (кальций)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

<b>Приготовление (15 минут):</b>
1. Авокадо нарезать кубиками
2. Шпинат промыть и обсушить
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Авокадо и шпинат богаты калием и магнием - ключевыми электролитами, необходимыми для нервно-мышечной функции и поддержания гидратации.
"""
        benefits = """• 🥑 Калий для нервной системы
• 🥬 Магний для расслабления мышц
• 🧀 Кальций для костей
• 🍅 Дополнительные электролиты"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭЛЕКТРОЛИТНЫЙ УЖИН: АВОКАДО-ШПИНАТ САЛАТ",
            content, "electrolyte_dinner", benefits
        )

    def generate_mental_recovery_dinner(self):
        """Ужин для ментального восстановления"""
        content = """
🧠 <b>УЖИН ДЛЯ МЕНТАЛЬНОГО ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С АСПАРАГУСОМ</b>
КБЖУ: 450 ккал • Белки: 35г • Жиры: 28г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Спаржа - 300 г (фолат)
• Киноа - 100 г (магний)
• Чеснок - 3 зубчика (аллицин)
• Лимон - 1/2 шт (витамин C)

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Спаржу приготовить на гриле
3. Киноа отварить 15 минут
4. Подавать с лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты из лосося поддерживают здоровье клеточных мембран нейронов и улучшают когнитивные функции, включая память и концентрацию.
"""
        benefits = """• 🐟 Улучшение когнитивных функций
• 🌱 Фолат для синтеза нейромедиаторов
• 🌾 Магний для расслабления
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УЖИН ДЛЯ МЕНТАЛЬНОГО ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С АСПАРАГУСОМ",
            content, "mental_recovery_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_energy_dessert(self):
        """Энергетический десерт"""
        content = """
🍰 <b>ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА</b>
КБЖУ: 280 ккал • Белки: 12г • Жиры: 14г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (натуральная сладость)
• Семена чиа - 4 ст.л. (Омега-3 + клетчатка)
• Миндальное молоко - 300 мл
• Ванильный экстракт - 1 ч.л.
• Корица - 1 ч.л.
• Грецкие орехи - 30 г

<b>Приготовление (5 минут + настаивание):</b>
1. Бананы размять вилкой
2. Смешать с семенами чиа и молоком
3. Добавить ваниль и корицу
4. Настаивать 4 часа или overnight, посыпать орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Семена чиа образуют гель при контакте с жидкостью, что замедляет переваривание углеводов и обеспечивает постепенное высвобождение энергии, предотвращая резкие скачки сахара.
"""
        benefits = """• 🍌 Натуральные сахара для энергии
• 🌱 Омега-3 для противовоспалительного действия
• 🌾 Клетчатка для контроля гликемического ответа
• 🌰 Полифенолы для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА",
            content, "energy_dessert", benefits
        )

    def generate_carbs_treat_dessert(self):
        """Углеводное лакомство"""
        content = """
🎯 <b>УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 8 трюфелей):</b>
• Финики - 200 г (натуральные сахара)
• Овсяные хлопья - 80 г (сложные углеводы)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Арахисовая паста - 2 ст.л. (белок)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут + охлаждение):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке, охладить

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Финики содержат натуральные сахара (фруктозу и глюкозу) в сочетании с клетчаткой, что обеспечивает более медленное высвобождение энергии по сравнению с рафинированным сахаром.
"""
        benefits = """• 🫒 Натуральные сахара с клетчаткой
• 🌾 Сложные углеводы для продолжительной энергии
• 🍫 Флавоноиды для улучшения кровотока
• 🥜 Белок для баланса макронутриентов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "carbs_treat_dessert", benefits
        )

    def generate_mitochondrial_dessert(self):
        """Десерт для митохондриального здоровья"""
        content = """
🔋 <b>ДЕСЕРТ ДЛЯ МИТОХОНДРИЙ: ЯГОДНОЕ ПЮРЕ</b>
КБЖУ: 180 ккал • Белки: 8г • Жиры: 6г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Черника - 200 г (антоцианы)
• Малина - 150 г (эллаговая кислота)
• Гранат - 1 шт (пуникалагины)
• Лимонный сок - 1 ст.л.
• Мята - для украшения

<b>Приготовление (10 минут):</b>
1. Ягоды и гранат очистить
2. Взбить в блендере в пюре
3. Добавить лимонный сок
4. Украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод защищают митохондрии от окислительного стресса и улучшают их функцию, увеличивая производство энергии в клетках.
"""
        benefits = """• 🍓 Защита митохондрий от стресса
• 🍇 Мощные антиоксиданты
• 🍋 Витамин C для усиления действия
• 🌿 Освежающий и питательный"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 ДЕСЕРТ ДЛЯ МИТОХОНДРИЙ: ЯГОДНОЕ ПЮРЕ",
            content, "mitochondrial_dessert", benefits
        )

    def generate_hydration_dessert(self):
        """Гидратирующий десерт"""
        content = """
💦 <b>ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА</b>
КБЖУ: 140 ккал • Белки: 6г • Жиры: 2г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 800 г (ликопин)
• Лайм - 1 шт (цитраты)
• Мята - 15 г (ментол)
• Стевия - по вкусу
• Вода - 100 мл

<b>Приготовление (10 минут + заморозка):</b>
1. Арбуз очистить от косточек и взбить
2. Добавить сок лайма и стевию
3. Разлить по формам и заморозить
4. Перед подачей размять вилкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз содержит L-цитруллин, который преобразуется в L-аргинин и способствует расширению сосудов, улучшая кровообращение и доставку питательных веществ к клеткам.
"""
        benefits = """• 💧 Глубокая гидратация
• 🩸 Улучшение микроциркуляции
• 🍉 Ликопин для защиты от УФ-излучения
• 🧊 Освежающий и тонизирующий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "💦 ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА",
            content, "hydration_dessert", benefits
        )

    def generate_electrolyte_dessert(self):
        """Десерт для электролитного баланса"""
        content = """
⚡ <b>ЭЛЕКТРОЛИТНЫЙ ДЕСЕРТ: КОКОСОВЫЕ КУБИКИ</b>
КБЖУ: 220 ккал • Белки: 8г • Жиры: 15г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Кокосовое молоко - 400 мл (электролиты)
• Банан - 1 шт (калий)
• Мед - 1 ст.л. (глюкоза)
• Ванильный экстракт - 1 ч.л.
• Кокосовая стружка - 2 ст.л.

<b>Приготовление (10 минут + заморозка):</b>
1. Все ингредиенты взбить в блендере
2. Разлить по формам для льда
3. Заморозить 4 часа
4. Посыпать кокосовой стружкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Кокосовое молоко содержит натуральные электролиты (калий, натрий, магний), необходимые для поддержания водно-солевого баланса.
"""
        benefits = """• 🥥 Натуральные электролиты
• 🍌 Калий для нервной системы
• 🍯 Быстрая энергия
• 🧊 Освежающий и питательный"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭЛЕКТРОЛИТНЫЙ ДЕСЕРТ: КОКОСОВЫЕ КУБИКИ",
            content, "electrolyte_dessert", benefits
        )

    def generate_mental_energy_dessert(self):
        """Десерт для ментальной энергии"""
        content = """
🧠 <b>ДЕСЕРТ ДЛЯ МЕНТАЛЬНОЙ ЭНЕРГИИ: ШОКОЛАДНЫЕ ШАРИКИ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 18г • Углеводы: 22г

<b>Ингредиенты (на 8 шариков):</b>
• Финики - 150 г (натуральные сахара)
• Грецкие орехи - 100 г (Омега-3)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Кокосовое масло - 2 ст.л. (МСТ)
• Корица - 1 ч.л.

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Флавоноиды какао улучшают кровоснабжение мозга и усиливают нейрогенез - образование новых нейронов, улучшая когнитивные функции.
"""
        benefits = """• 🍫 Улучшение кровоснабжения мозга
• 🌰 Омега-3 для нейропротекции
• 🥥 Быстрая энергия для мозга
• 🟤 Антиоксиданты для защиты нейронов"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ДЕСЕРТ ДЛЯ МЕНТАЛЬНОЙ ЭНЕРГИИ: ШОКОЛАДНЫЕ ШАРИКИ",
            content, "mental_energy_dessert", benefits
        )

    def generate_recovery_dessert(self):
        """Десерт для восстановления энергии"""
        content = """
🔄 <b>ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ТВОРОЖНО-ФРУКТОВАЯ ЗАПЕКАНКА</b>
КБЖУ: 320 ккал • Белки: 28г • Жиры: 12г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Творог - 400 г (казеин)
• Яблоки - 2 шт (пектин)
• Яйца - 2 шт (белок)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (натуральные сахара)

<b>Приготовление (35 минут):</b>
1. Творог смешать с яйцами
2. Яблоки нарезать кубиками
3. Выложить в форму, запекать 30 минут
4. Полить медом перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога обеспечивает медленное высвобождение аминокислот в течение ночи, поддерживая восстановительные процессы и пополнение энергетических запасов.
"""
        benefits = """• ⏱️ Медленное высвобождение питательных веществ
• 🍎 Натуральные углеводы для энергии
• 🥚 Качественный белок
• 🟤 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ТВОРОЖНО-ФРУКТОВАЯ ЗАПЕКАНКА",
            content, "recovery_dessert", benefits
        )

# Создание экземпляра генератора
wednesday_generator = WednesdayContentGenerator()
class ThursdayContentGenerator:
    """Генератор контента для четверга - углеводы и энергия"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (7 рецептов)
    def generate_carbs_energy_breakfast(self):
        """Углеводный завтрак для энергии"""
        content = """
🍞 <b>УГЛЕВОДНЫЙ ЗАВТРАК: ЦЕЛЬНОЗЕРНОВЫЕ ТОСТЫ</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Хлеб цельнозерновой - 4 ломтика (сложные углеводы)
• Авокадо - 1 шт (полезные жиры)
• Яйца - 2 шт (белок)
• Помидоры - 2 шт (ликопин)
• Руккола - 50 г (кальций)
• Лимонный сок - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Хлеб поджарить
2. Авокадо размять с лимонным соком
3. Яйца сварить вкрутую
4. Собрать тосты слоями

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сложные углеводы из цельнозернового хлеба обеспечивают постепенное высвобождение глюкозы, поддерживая стабильный уровень энергии на 3-4 часа.
"""
        benefits = """• 🌾 Медленные углеводы для энергии
• 🥑 Полезные жиры для усвоения витаминов
• 🥚 Белок для сытости
• 🍅 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍞 УГЛЕВОДНЫЙ ЗАВТРАК: ЦЕЛЬНОЗЕРНОВЫЕ ТОСТЫ",
            content, "carbs_breakfast", benefits
        )

    def generate_quick_carbs_breakfast(self):
        """Быстрые углеводы для энергии"""
        content = """
🍌 <b>БЫСТРЫЕ УГЛЕВОДЫ: БАНАНОВЫЙ СМУЗИ</b>
КБЖУ: 350 ккал • Белки: 15г • Жиры: 8г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (быстрые углеводы)
• Овсяные хлопья - 50 г (сложные углеводы)
• Миндальное молоко - 400 мл
• Мед - 1 ст.л. (глюкоза)
• Корица - 1 ч.л. (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Подавать сразу
3. Можно добавить протеин
4. Украсить корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание быстрых и сложных углеводов обеспечивает как немедленный приток энергии, так и продолжительное высвобождение глюкозы.
"""
        benefits = """• ⚡ Мгновенная и продолжительная энергия
• 🍌 Калий для нервной системы
• 🌾 Клетчатка для сытости
• 🍯 Натуральные сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🍌 БЫСТРЫЕ УГЛЕВОДЫ: БАНАНОВЫЙ СМУЗИ",
            content, "quick_carbs_breakfast", benefits
        )

    def generate_complex_carbs_breakfast(self):
        """Комплекс углеводов для энергии"""
        content = """
🌾 <b>КОМПЛЕКС УГЛЕВОДОВ: ГРЕЧНЕВАЯ КАША</b>
КБЖУ: 420 ккал • Белки: 15г • Жиры: 10г • Углеводы: 75г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (сложные углеводы)
• Изюм - 50 г (быстрые углеводы)
• Яблоки - 2 шт (фруктоза)
• Корица - 1 ч.л. (антиоксиданты)
• Грецкие орехи - 30 г (Омега-3)

<b>Приготовление (20 минут):</b>
1. Гречку отварить 15 минут
2. Яблоки натереть на терке
3. Добавить изюм и орехи
4. Посыпать корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гречка содержит резистентный крахмал, который служит пищей для полезных бактерий кишечника и обеспечивает продолжительное высвобождение энергии.
"""
        benefits = """• 🌾 Резистентный крахмал для энергии
• 🍇 Разные источники углеводов
• 🌰 Омега-3 для противовоспалительного действия
• 🍎 Пектин для здоровья кишечника"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 КОМПЛЕКС УГЛЕВОДОВ: ГРЕЧНЕВАЯ КАША",
            content, "complex_carbs_breakfast", benefits
        )

    def generate_fiber_carbs_breakfast(self):
        """Углеводы с клетчаткой"""
        content = """
🍎 <b>УГЛЕВОДЫ С КЛЕТЧАТКОЙ: ОВСЯНКА С ЯБЛОКАМИ</b>
КБЖУ: 380 ккал • Белки: 12г • Жиры: 8г • Углеводы: 70г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 120 г (бета-глюканы)
• Яблоки - 3 шт (пектин)
• Семена льна - 2 ст.л. (лигнаны)
• Корица - 1 ч.л. (полифенолы)
• Мед - 1 ст.л. (натуральные сахара)

<b>Приготовление (15 минут):</b>
1. Овсянку варить 10 минут
2. Яблоки натереть на терке
3. Добавить семена и специи
4. Заправить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Растворимая клетчатка (пектин и бета-глюканы) замедляет всасывание углеводов, предотвращая резкие скачки сахара в крови.
"""
        benefits = """• 🍎 Контроль уровня сахара в крови
• 🌾 Снижение гликемического индекса
• 🌱 Гормональный баланс
• 🍯 Натуральная сладость"""
        
        return self.visual_manager.generate_attractive_post(
            "🍎 УГЛЕВОДЫ С КЛЕТЧАТКОЙ: ОВСЯНКА С ЯБЛОКАМИ",
            content, "fiber_carbs_breakfast", benefits
        )

    def generate_energy_dense_breakfast(self):
        """Энергоемкий завтрак"""
        content = """
🔥 <b>ЭНЕРГОЕМКИЙ ЗАВТРАК: ПШЕННАЯ КАША</b>
КБЖУ: 450 ккал • Белки: 18г • Жиры: 12г • Углеводы: 75г

<b>Ингредиенты (на 2 порции):</b>
• Пшено - 150 г (сложные углеводы)
• Тыква - 400 г (бета-каротин)
• Изюм - 50 г (быстрые углеводы)
• Кунжут - 2 ст.л. (кальций)
• Корица - 1 ч.л. (антиоксиданты)

<b>Приготовление (25 минут):</b>
1. Пшено промыть и отварить 20 минут
2. Тыкву запечь и размять
3. Смешать все ингредиенты
4. Посыпать кунжутом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пшено богато сложными углеводами и имеет низкий гликемический индекс, обеспечивая продолжительное высвобождение энергии.
"""
        benefits = """• 🌾 Низкий гликемический индекс
• 🎃 Бета-каротин для иммунитета
• 🍇 Быстрая энергия
• 🌱 Кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЭНЕРГОЕМКИЙ ЗАВТРАК: ПШЕННАЯ КАША",
            content, "energy_dense_breakfast", benefits
        )

    def generate_smart_carbs_breakfast(self):
        """Умные углеводы для мозга"""
        content = """
🧠 <b>УМНЫЕ УГЛЕВОДЫ: ЯГОДНЫЙ КИНОА</b>
КБЖУ: 400 ккал • Белки: 18г • Жиры: 12г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (полноценный белок)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Грецкие орехи - 40 г (Омега-3)
• Мед - 1 ст.л. (глюкоза)

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Ягоды промыть
3. Смешать все ингредиенты
4. Заправить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод улучшают когнитивные функции и защищают нейроны, а углеводы обеспечивают энергию для работы мозга.
"""
        benefits = """• 🍓 Улучшение когнитивных функций
• 🌾 Полноценный белок
• 🌰 Омега-3 для мозга
• 🍯 Энергия для умственной деятельности"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УМНЫЕ УГЛЕВОДЫ: ЯГОДНЫЙ КИНОА",
            content, "smart_carbs_breakfast", benefits
        )

    def generate_hydrating_carbs_breakfast(self):
        """Гидратирующие углеводы"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЕ УГЛЕВОДЫ: АРБУЗНЫЙ САЛАТ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 10г • Углеводы: 50г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 800 г (вода + углеводы)
• Фета - 150 г (белок)
• Мята - 20 г (ментол)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Арбуз нарезать кубиками
2. Фету раскрошить
3. Смешать с мятой
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз обеспечивает одновременно гидратацию и быстрые углеводы, идеально для восстановления водного и энергетического баланса.
"""
        benefits = """• 💦 Гидратация + энергия
• 🧀 Белок для сытости
• 🌿 Освежающий эффект
• 🍉 Ликопин для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЕ УГЛЕВОДЫ: АРБУЗНЫЙ САЛАТ",
            content, "hydrating_carbs_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (7 рецептов)
    def generate_slow_carbs_lunch(self):
        """Медленные углеводы на обед"""
        content = """
⏱️ <b>МЕДЛЕННЫЕ УГЛЕВОДЫ: БУЛГУР С ОВОЩАМИ</b>
КБЖУ: 480 ккал • Белки: 20г • Жиры: 15г • Углеводы: 70г

<b>Ингредиенты (на 2 порции):</b>
• Булгур - 150 г (сложные углеводы)
• Нут - 200 г (растительный белок)
• Баклажаны - 2 шт (клетчатка)
• Помидоры - 3 шт (ликопин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Булгур залить кипятком на 15 минут
2. Нут отварить 25 минут
3. Овощи запечь
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Булгур имеет низкий гликемический индекс и обеспечивает медленное высвобождение энергии, поддерживая стабильный уровень сахара в крови.
"""
        benefits = """• 🌾 Стабильный уровень энергии
• 🌱 Растительный белок
• 🍆 Клетчатка для пищеварения
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "⏱️ МЕДЛЕННЫЕ УГЛЕВОДЫ: БУЛГУР С ОВОЩАМИ",
            content, "slow_carbs_lunch", benefits
        )

    def generate_energy_lunch(self):
        """Энергетический обед"""
        content = """
⚡ <b>ЭНЕРГЕТИЧЕСКИЙ ОБЕД: ПАСТА С ОВОЩАМИ</b>
КБЖУ: 520 ккал • Белки: 25г • Жиры: 18г • Углеводы: 75г

<b>Ингредиенты (на 2 порции):</b>
• Паста цельнозерновая - 200 г (сложные углеводы)
• Куриное филе - 300 г (белок)
• Брокколи - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Томатный соус - 200 мл (ликопин)

<b>Приготовление (25 минут):</b>
1. Пасту отварить al dente
2. Курицу нарезать и обжарить
3. Овощи приготовить на пару
4. Смешать с томатным соусом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цельнозерновая паста обеспечивает комплекс углеводов для продолжительной энергии, а белок поддерживает сытость и мышечную функцию.
"""
        benefits = """• 🍝 Продолжительная энергия
• 🍗 Качественный белок
• 🥦 Антиоксиданты для защиты
• 🍅 Ликопин для здоровья"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЭНЕРГЕТИЧЕСКИЙ ОБЕД: ПАСТА С ОВОЩАМИ",
            content, "energy_lunch", benefits
        )

    def generate_complex_carbs_lunch(self):
        """Комплекс углеводов на обед"""
        content = """
🌾 <b>КОМПЛЕКС УГЛЕВОДОВ: КУСКУС С ОВОЩАМИ</b>
КБЖУ: 460 ккал • Белки: 22г • Жиры: 12г • Углеводы: 70г

<b>Ингредиенты (на 2 порции):</b>
• Кускус - 150 г (быстрые углеводы)
• Чечевица - 150 г (сложные углеводы)
• Цукини - 2 шт (калий)
• Перец - 2 шт (витамин C)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

<b>Приготовление (20 минут):</b>
1. Кускус залить кипятком на 10 минут
2. Чечевицу отварить 15 минут
3. Овощи обжарить
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание быстрых и сложных углеводов обеспечивает как немедленный приток энергии, так и продолжительное высвобождение глюкозы.
"""
        benefits = """• ⚡ Мгновенная и продолжительная энергия
• 🌱 Растительный белок
• 🥒 Электролиты для баланса
• 🍋 Витамин C для усвоения"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 КОМПЛЕКС УГЛЕВОДОВ: КУСКУС С ОВОЩАМИ",
            content, "complex_carbs_lunch", benefits
        )

    def generate_fiber_rich_lunch(self):
        """Обед, богатый клетчаткой"""
        content = """
🥦 <b>ОБЕД С КЛЕТЧАТКОЙ: ОВОЩНОЙ РАГУ</b>
КБЖУ: 420 ккал • Белки: 18г • Жиры: 15г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Картофель - 400 г (сложные углеводы)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (клетчатка)
• Лук - 2 шт (пребиотики)
• Зелень - 30 г (хлорофилл)
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Овощи нарезать кубиками
2. Тушить 30 минут до мягкости
3. Добавить зелень в конце
4. Заправить оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Растворимая и нерастворимая клетчатка из овощей замедляет всасывание углеводов и поддерживает здоровье микробиома кишечника.
"""
        benefits = """• 🥔 Контроль уровня сахара
• 🥕 Антиоксиданты для защиты
• 🌿 Пребиотики для микробиома
• 💫 Улучшение пищеварения"""
        
        return self.visual_manager.generate_attractive_post(
            "🥦 ОБЕД С КЛЕТЧАТКОЙ: ОВОЩНОЙ РАГУ",
            content, "fiber_rich_lunch", benefits
        )

    def generate_energy_dense_lunch(self):
        """Энергоемкий обед"""
        content = """
🔥 <b>ЭНЕРГОЕМКИЙ ОБЕД: РИС С ОВОЩАМИ</b>
КБЖУ: 500 ккал • Белки: 20г • Жиры: 15г • Углеводы: 80г

<b>Ингредиенты (на 2 порции):</b>
• Бурый рис - 200 г (сложные углеводы)
• Нут - 200 г (растительный белок)
• Брокколи - 300 г (глюкозинолаты)
• Морковь - 3 шт (бета-каротин)
• Кунжут - 2 ст.л. (кальций)
• Соус терияки - 3 ст.л.

<b>Приготовление (40 минут):</b>
1. Рис отварить 30 минут
2. Нут отварить 25 минут
3. Овощи приготовить на пару
4. Смешать с соусом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бурый рис содержит больше клетчатки и питательных веществ по сравнению с белым рисом, обеспечивая более медленное высвобождение энергии.
"""
        benefits = """• 🍚 Медленное высвобождение энергии
• 🌱 Растительный белок
• 🥦 Антиоксиданты для защиты
• 🌱 Кальций для костей"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЭНЕРГОЕМКИЙ ОБЕД: РИС С ОВОЩАМИ",
            content, "energy_dense_lunch", benefits
        )

    def generate_smart_carbs_lunch(self):
        """Умные углеводы для мозга"""
        content = """
🧠 <b>УМНЫЕ УГЛЕВОДЫ: СВЕКЛА С КИНОА</b>
КБЖУ: 450 ккал • Белки: 22г • Жиры: 18г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 4 шт (нитраты)
• Киноа - 150 г (полноценный белок)
• Грецкие орехи - 50 г (Омега-3)
• Руккола - 100 г (кальций)
• Лимонный сок - 3 ст.л.
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Свеклу запечь 30 минут
2. Киноа отварить 15 минут
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы улучшают кровоснабжение мозга, а углеводы обеспечивают энергию для когнитивных функций.
"""
        benefits = """• 🍠 Улучшение мозгового кровотока
• 🌾 Энергия для умственной деятельности
• 🌰 Омега-3 для нейропротекции
• 🥬 Кальций для нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УМНЫЕ УГЛЕВОДЫ: СВЕКЛА С КИНОА",
            content, "smart_carbs_lunch", benefits
        )

    def generate_hydrating_carbs_lunch(self):
        """Гидратирующий обед с углеводами"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩНОЙ СУП</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 10г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Картофель - 400 г (углеводы)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (вода)
• Лук - 2 шт (кверцетин)
• Чечевица - 100 г (белок)
• Зелень - 30 г

<b>Приготовление (40 минут):</b>
1. Овощи нарезать кубиками
2. Чечевицу промыть
3. Варить 35 минут до готовности
4. Добавить зелень перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Овощной суп обеспечивает одновременно гидратацию и углеводы для энергии, идеально для поддержания водного и энергетического баланса.
"""
        benefits = """• 💦 Гидратация + энергия
• 🥔 Сложные углеводы
• 🌱 Растительный белок
• 🧅 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЙ ОБЕД: ОВОЩНОЙ СУП",
            content, "hydrating_carbs_lunch", benefits
        )

    # 🍽️ УЖИНЫ (7 рецептов)
    def generate_slow_carbs_dinner(self):
        """Ужин с медленными углеводами"""
        content = """
🌙 <b>УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦА С ОВОЩАМИ</b>
КБЖУ: 420 ккал • Белки: 25г • Жиры: 14г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Чечевица - 150 г (растительный белок)
• Цукини - 1 шт (калий)
• Баклажаны - 1 шт (насунин)
• Помидоры - 2 шт (ликопин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.

<b>Приготовление (25 минут):</b>
1. Чечевицу отварить 20 минут
2. Овощи нарезать и обжарить
3. Смешать все ингредиенты
4. Тушить 5 минут под крышкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Чечевица содержит медленно усваиваемые углеводы и резистентный крахмал, поддерживающий стабильный уровень сахара в крови и обеспечивающий продолжительное чувство сытости.
"""
        benefits = """• 🌱 Медленные углеводы + растительный белок
• 🥒 Калий для водного баланса
• 🍆 Насунин для клеточных мембран
• 🧄 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 УЖИН С МЕДЛЕННЫМИ УГЛЕВОДАМИ: ЧЕЧЕВИЦА С ОВОЩАМИ",
            content, "slow_carbs_dinner", benefits
        )

    def generate_energy_reserve_dinner(self):
        """Ужин для создания энергетического резерва"""
        content = """
🔋 <b>УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА</b>
КБЖУ: 450 ккал • Белки: 20г • Жиры: 16г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (полноценный белок)
• Тыква - 300 г (бета-каротин)
• Шпинат - 100 г (железо)
• Семена тыквы - 2 ст.л. (цинк)
• Кокосовое молоко - 100 мл (МСТ)
• Куркума - 1 ч.л.

<b>Приготовление (25 минут):</b>
1. Киноа отварить
2. Тыкву запечь 20 минут
3. Шпинат обжарить 2 минуты
4. Смешать все ингредиенты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Среднецепочечные триглицериды (МСТ) из кокосового молока быстро метаболизируются в печени, производя кетоновые тела - эффективный источник энергии для мозга и мышц.
"""
        benefits = """• 🌾 Полноценный растительный белок
• 🎃 Бета-каротин для иммунитета
• 🥬 Железо для энергии
• 🥥 МСТ для альтернативного энергоснабжения"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ СОЗДАНИЯ ЭНЕРГЕТИЧЕСКОГО РЕЗЕРВА",
            content, "energy_reserve_dinner", benefits
        )

    def generate_evening_carbs_dinner(self):
        """Вечерние углеводы для качественного сна"""
        content = """
😴 <b>ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Батат - 400 г (сложные углеводы)
• Творог - 150 г (триптофан)
• Банан - 1 шт (мелатонин)
• Корица - 1 ч.л.
• Мед - 1 ст.л.
• Грецкие орехи - 30 г

<b>Приготовление (20 минут):</b>
1. Батат запечь 18 минут
2. Размять вилкой
3. Смешать с творогом и бананом
4. Заправить медом и корицей, посыпать орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Углеводы вечером способствуют транспорту триптофана через гематоэнцефалический барьер, улучшая синтез серотонина и мелатонина - гормонов, регулирующих сон.
"""
        benefits = """• 🍠 Сложные углеводы для сытости
• 🧀 Триптофан для серотонина
• 🍌 Мелатонин для сна
• 🌰 Омега-3 для противовоспалительного эффекта"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ВЕЧЕРНИЕ УГЛЕВОДЫ ДЛЯ КАЧЕСТВЕННОГО СНА",
            content, "evening_carbs_dinner", benefits
        )

    def generate_light_carbs_dinner(self):
        """Легкий углеводный ужин"""
        content = """
🌿 <b>ЛЕГКИЙ УГЛЕВОДНЫЙ УЖИН: ОВОЩИ НА ПАРУ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 8г • Углеводы: 50г

<b>Ингредиенты (на 2 порции):</b>
• Картофель - 400 г (углеводы)
• Морковь - 3 шт (бета-каротин)
• Брокколи - 300 г (глюкозинолаты)
• Цветная капуста - 300 г (сульфорафан)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (25 минут):</b>
1. Овощи нарезать
2. Приготовить на пару 20 минут
3. Заправить маслом и лимоном
4. Посолить по вкусу

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Приготовление на пару сохраняет водорастворимые витамины и минералы, обеспечивая максимальную питательную ценность при минимальной калорийности.
"""
        benefits = """• ♨️ Сохранение питательных веществ
• 🥔 Легкие углеводы
• 🥦 Антиоксиданты для защиты
• 💫 Улучшение пищеварения"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ЛЕГКИЙ УГЛЕВОДНЫЙ УЖИН: ОВОЩИ НА ПАРУ",
            content, "light_carbs_dinner", benefits
        )

    def generate_fiber_dinner(self):
        """Ужин, богатый клетчаткой"""
        content = """
🌱 <b>УЖИН С КЛЕТЧАТКОЙ: СТРУЧКОВАЯ ФАСОЛЬ</b>
КБЖУ: 350 ккал • Белки: 22г • Жиры: 12г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Стручковая фасоль - 500 г (нерастворимая клетчатка)
• Морковь - 2 шт (бета-каротин)
• Лук - 1 шт (пребиотики)
• Чеснок - 3 зубчика (аллицин)
• Миндальные лепестки - 30 г (витамин E)

<b>Приготовление (20 минут):</b>
1. Фасоль бланшировать 5 минут
2. Овощи нарезать соломкой
3. Обжарить с чесноком 10 минут
4. Посыпать миндальными лепестками

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нерастворимая клетчатка стручковой фасоли увеличивает объем стула и ускоряет его прохождение через кишечник, предотвращая запоры.
"""
        benefits = """• 🚀 Ускорение кишечного транзита
• 🛡️ Профилактика запоров
• 🥕 Антиоксиданты для защиты
• 🌰 Витамин E для кожи"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 УЖИН С КЛЕТЧАТКОЙ: СТРУЧКОВАЯ ФАСОЛЬ",
            content, "fiber_dinner", benefits
        )

    def generate_smart_carbs_dinner(self):
        """Умные углеводы для вечера"""
        content = """
🎯 <b>УМНЫЕ УГЛЕВОДЫ ДЛЯ ВЕЧЕРА: ТЫКВЕННОЕ ПЮРЕ</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 800 г (бета-каротин)
• Картофель - 2 шт (углеводы)
• Имбирь - 2 см (гингерол)
• Мускатный орех - 1/4 ч.л. (миристицин)
• Кокосовые сливки - 100 мл (МСТ)

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Запечь 25 минут до мягкости
3. Размять в пюре
4. Добавить специи и кокосовые сливки

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-каротин из тыквы преобразуется в витамин A, который необходим для здоровья зрения и иммунной системы, особенно важных в вечернее время.
"""
        benefits = """• 🎃 Витамин A для зрения и иммунитета
• 🥔 Сложные углеводы
• 🔥 Противовоспалительные свойства
• 🥥 Легкие жиры для усвоения"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 УМНЫЕ УГЛЕВОДЫ ДЛЯ ВЕЧЕРА: ТЫКВЕННОЕ ПЮРЕ",
            content, "smart_carbs_dinner", benefits
        )

    def generate_hydrating_carbs_dinner(self):
        """Гидратирующий углеводный ужин"""
        content = """
💦 <b>ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ</b>
КБЖУ: 280 ккал • Белки: 20г • Жиры: 15г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Огурцы - 3 шт (вода)
• Творог - 300 г (белок)
• Укроп - 30 г (эфирные масла)
• Лимонный сок - 2 ст.л. (витамин C)
• Семена подсолнечника - 30 г (витамин E)

<b>Приготовление (10 минут):</b>
1. Огурцы нарезать кубиками
2. Творог смешать с укропом
3. Соединить все ингредиенты
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Огурцы на 95% состоят из структурированной воды, которая легче проникает в клетки и способствует эффективной гидратации на клеточном уровне.
"""
        benefits = """• 💧 Глубокая клеточная гидратация
• 🧀 Легкий белок для ночного восстановления
• 🌱 Кремний для здоровья соединительной ткани
• 🍋 Витамин C для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "💦 ГИДРАТИРУЮЩИЙ УЖИН: ОГУРЕЧНЫЙ САЛАТ",
            content, "hydrating_carbs_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (7 рецептов)
    def generate_energy_dessert(self):
        """Энергетический десерт"""
        content = """
🍰 <b>ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА</b>
КБЖУ: 280 ккал • Белки: 12г • Жиры: 14г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (натуральная сладость)
• Семена чиа - 4 ст.л. (Омега-3 + клетчатка)
• Миндальное молоко - 300 мл
• Ванильный экстракт - 1 ч.л.
• Корица - 1 ч.л.
• Грецкие орехи - 30 г

<b>Приготовление (5 минут + настаивание):</b>
1. Бананы размять вилкой
2. Смешать с семенами чиа и молоком
3. Добавить ваниль и корицу
4. Настаивать 4 часа или overnight, посыпать орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Семена чиа образуют гель при контакте с жидкостью, что замедляет переваривание углеводов и обеспечивает постепенное высвобождение энергии, предотвращая резкие скачки сахара.
"""
        benefits = """• 🍌 Натуральные сахара для энергии
• 🌱 Омега-3 для противовоспалительного действия
• 🌾 Клетчатка для контроля гликемического ответа
• 🌰 Полифенолы для антиоксидантной защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍰 ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ: БАНАНОВЫЙ ПУДИНГ С ЧИА",
            content, "energy_dessert", benefits
        )

    def generate_carbs_treat_dessert(self):
        """Углеводное лакомство"""
        content = """
🎯 <b>УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 8 трюфелей):</b>
• Финики - 200 г (натуральные сахара)
• Овсяные хлопья - 80 г (сложные углеводы)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Арахисовая паста - 2 ст.л. (белок)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут + охлаждение):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке, охладить

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Финики содержат натуральные сахара (фруктозу и глюкозу) в сочетании с клетчаткой, что обеспечивает более медленное высвобождение энергии по сравнению с рафинированным сахаром.
"""
        benefits = """• 🫒 Натуральные сахара с клетчаткой
• 🌾 Сложные углеводы для продолжительной энергии
• 🍫 Флавоноиды для улучшения кровотока
• 🥜 Белок для баланса макронутриентов"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 УГЛЕВОДНОЕ ЛАКОМСТВО: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "carbs_treat_dessert", benefits
        )

    def generate_light_carbs_dessert(self):
        """Легкий углеводный десерт"""
        content = """
🌙 <b>ЛЕГКИЙ УГЛЕВОДНЫЙ ДЕСЕРТ: ЯБЛОЧНОЕ ПЮРЕ</b>
КБЖУ: 180 ккал • Белки: 8г • Жиры: 6г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Яблоки - 4 шт (пектин)
• Корица - 1 ч.л. (антиоксиданты)
• Лимонный сок - 1 ст.л.
• Мед - 1 ч.л. (натуральные сахара)
• Грецкие орехи - 20 г

<b>Приготовление (15 минут):</b>
1. Яблоки запечь 12 минут
2. Размять в пюре
3. Добавить корицу и лимонный сок
4. Украсить орехами и медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пектин из яблок образует гель в кишечнике, замедляя всасывание сахаров и способствуя росту полезных бактерий кишечника.
"""
        benefits = """• 🍎 Контроль уровня сахара в крови
• 🟤 Антиоксиданты для защиты
• 🌰 Полезные жиры
• 🍯 Натуральная сладость"""
        
        return self.visual_manager.generate_attractive_post(
            "🌙 ЛЕГКИЙ УГЛЕВОДНЫЙ ДЕСЕРТ: ЯБЛОЧНОЕ ПЮРЕ",
            content, "light_carbs_dessert", benefits
        )

    def generate_fiber_dessert(self):
        """Десерт, богатый клетчаткой"""
        content = """
🌾 <b>ДЕСЕРТ С КЛЕТЧАТКОЙ: ОВСЯНОЕ ПЕЧЕНЬЕ</b>
КБЖУ: 320 ккал • Белки: 12г • Жиры: 14г • Углеводы: 42г

<b>Ингредиенты (на 8 печений):</b>
• Овсяные хлопья - 200 г (бета-глюканы)
• Бананы - 2 шт (натуральная сладость)
• Изюм - 50 г (быстрые углеводы)
• Корица - 1 ч.л. (антиоксиданты)
• Кокосовая стружка - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Бананы размять вилкой
2. Смешать все ингредиенты
3. Сформировать печенья
4. Запекать 20 минут при 180°C

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-глюканы овсянки снижают гликемический ответ и способствуют чувству сытости, предотвращая переедание в вечернее время.
"""
        benefits = """• 🌾 Снижение гликемического индекса
• 🍌 Натуральная сладость без сахара
• 🍇 Быстрая энергия
• 🟤 Антиоксиданты для защиты"""
        
        return self.visual_manager.generate_attractive_post(
            "🌾 ДЕСЕРТ С КЛЕТЧАТКОЙ: ОВСЯНОЕ ПЕЧЕНЬЕ",
            content, "fiber_dessert", benefits
        )

    def generate_smart_carbs_dessert(self):
        """Умный углеводный десерт"""
        content = """
🧠 <b>УМНЫЙ УГЛЕВОДНЫЙ ДЕСЕРТ: ЯГОДНЫЙ ПАРФЕ</b>
КБЖУ: 280 ккал • Белки: 18г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Гранола - 60 г (сложные углеводы)
• Мед - 1 ст.л. (глюкоза)

<b>Приготовление (5 минут):</b>
1. Слоями выложить йогурт и ягоды
2. Посыпать гранолой
3. Полить медом
4. Охладить 10 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод улучшают когнитивные функции и защищают нейроны от окислительного стресса, а углеводы обеспечивают энергию для мозга.
"""
        benefits = """• 🍓 Улучшение когнитивных функций
• 🦠 Пробиотики для здоровья кишечника
• 🌾 Сложные углеводы для энергии
• 🍯 Быстрая глюкоза для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УМНЫЙ УГЛЕВОДНЫЙ ДЕСЕРТ: ЯГОДНЫЙ ПАРФЕ",
            content, "smart_carbs_dessert", benefits
        )

    def generate_hydrating_carbs_dessert(self):
        """Гидратирующий углеводный десерт"""
        content = """
💧 <b>ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА</b>
КБЖУ: 140 ккал • Белки: 6г • Жиры: 2г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 800 г (ликопин)
• Лайм - 1 шт (цитраты)
• Мята - 15 г (ментол)
• Стевия - по вкусу
• Вода - 100 мл

<b>Приготовление (10 минут + заморозка):</b>
1. Арбуз очистить от косточек и взбить
2. Добавить сок лайма и стевию
3. Разлить по формам и заморозить
4. Перед подачей размять вилкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Арбуз содержит L-цитруллин, который преобразуется в L-аргинин и способствует расширению сосудов, улучшая кровообращение и доставку питательных веществ к клеткам.
"""
        benefits = """• 💧 Глубокая гидратация
• 🩸 Улучшение микроциркуляции
• 🍉 Ликопин для защиты от УФ-излучения
• 🧊 Освежающий и тонизирующий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ГИДРАТИРУЮЩИЙ ДЕСЕРТ: АРБУЗНЫЙ ГРАНИТА",
            content, "hydrating_carbs_dessert", benefits
        )

    def generate_recovery_carbs_dessert(self):
        """Десерт для восстановления энергии"""
        content = """
🔄 <b>ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ТВОРОЖНО-ФРУКТОВАЯ ЗАПЕКАНКА</b>
КБЖУ: 320 ккал • Белки: 28г • Жиры: 12г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Творог - 400 г (казеин)
• Яблоки - 2 шт (пектин)
• Яйца - 2 шт (белок)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (натуральные сахара)

<b>Приготовление (35 минут):</b>
1. Творог смешать с яйцами
2. Яблоки нарезать кубиками
3. Выложить в форму, запекать 30 минут
4. Полить медом перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога обеспечивает медленное высвобождение аминокислот в течение ночи, поддерживая восстановительные процессы и пополнение энергетических запасов.
"""
        benefits = """• ⏱️ Медленное высвобождение питательных веществ
• 🍎 Натуральные углеводы для энергии
• 🥚 Качественный белок
• 🟤 Антиоксиданты для восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ДЕСЕРТ ВОССТАНОВЛЕНИЯ: ТВОРОЖНО-ФРУКТОВАЯ ЗАПЕКАНКА",
            content, "recovery_carbs_dessert", benefits
        )

# Создание экземпляра генератора
thursday_generator = ThursdayContentGenerator()
class FridayContentGenerator:
    """Генератор контента для пятницы - полезные жиры и когнитивное здоровье"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (9 рецептов)
    def generate_brain_boost_breakfast(self):
        """Завтрак для усиления работы мозга"""
        content = """
🧠 <b>ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С АВОКАДО И ЛОСОСЕМ</b>
КБЖУ: 420 ккал • Белки: 30г • Жиры: 32г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 4 шт (холин)
• Лосось слабосоленый - 150 г (ДГК)
• Авокадо - 1 шт (олеиновая кислота)
• Шпинат - 100 г (лютеин)
• Грецкие орехи - 30 г (полифенолы)
• Оливковое масло - 1 ст.л.

<b>Приготовление (15 минут):</b>
1. Яйца взбить с щепоткой соли
2. Приготовить омлет на оливковом масле
3. Авокадо нарезать ломтиками
4. Лосось нарезать пластинами
5. Подавать омлет с авокадо, лососем и шпинатом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ДГК (докозагексаеновая кислота) из лосося составляет 30% серого вещества мозга и улучшает нейропластичность, усиливая связи между нейронами.
"""
        benefits = """• 🧠 Улучшение нейропластичности
• 💭 Усиление когнитивных функций  
• 🛡️ Защита клеток мозга
• 🔥 Долгая энергия без сонливости"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЗАВТРАК ДЛЯ МОЗГА: ОМЛЕТ С АВОКАДО И ЛОСОСЕМ",
            content, "brain_boost_breakfast", benefits
        )

    def generate_focus_breakfast(self):
        """Завтрак для концентрации и внимания"""
        content = """
🎯 <b>ЗАВТРАК ДЛЯ КОНЦЕНТРАЦИИ: ТВОРОГ С СЕМЕНАМИ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 22г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (тирозин)
• Семена чиа - 3 ст.л. (альфа-линоленовая кислота)
• Семена льна - 2 ст.л. (лигнаны)
• Тыквенные семечки - 30 г (цинк)
• Черника - 100 г (антоцианы)
• Мед - 1 ч.л. (глюкоза)

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Добавить все семена
3. Украсить черникой
4. Полить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Тирозин из творога является предшественником дофамина и норадреналина - нейромедиаторов, отвечающих за внимание, мотивацию и умственную концентрацию.
"""
        benefits = """• 🎯 Улучшение фокуса и внимания
• 💪 Стимуляция выработки нейромедиаторов
• 🧠 Поддержка когнитивных функций
• 🌱 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ЗАВТРАК ДЛЯ КОНЦЕНТРАЦИИ: ТВОРОГ С СЕМЕНАМИ",
            content, "focus_breakfast", benefits
        )

    def generate_memory_breakfast(self):
        """Завтрак для улучшения памяти"""
        content = """
📚 <b>ЗАВТРАК ДЛЯ ПАМЯТИ: ГРЕЧКА С ГРЕЦКИМИ ОРЕХАМИ</b>
КБЖУ: 450 ккал • Белки: 18г • Жиры: 28г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (рутин)
• Грецкие орехи - 80 г (полифенолы)
• Кокосовое молоко - 200 мл (МСТ)
• Корица - 1 ч.л. (циннамальдегид)
• Мед - 1 ст.л. (натуральные сахара)
• Изюм - 30 г (бор)

<b>Приготовление (20 минут):</b>
1. Гречку отварить 15 минут
2. Орехи измельчить
3. Смешать с кокосовым молоком
4. Добавить изюм и корицу
5. Заправить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Полифенолы грецких орехов уменьшают окислительный стресс и воспаление в гиппокампе - области мозга, ответственной за формирование памяти.
"""
        benefits = """• 📚 Улучшение работы гиппокампа
• 🛡️ Защита от окислительного стресса
• 🔥 Альтернативная энергия для мозга
• 🌿 Противовоспалительные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 ЗАВТРАК ДЛЯ ПАМЯТИ: ГРЕЧКА С ГРЕЦКИМИ ОРЕХАМИ",
            content, "memory_breakfast", benefits
        )

    def generate_mental_energy_breakfast(self):
        """Завтрак для ментальной энергии"""
        content = """
⚡ <b>ЗАВТРАК ДЛЯ МЕНТАЛЬНОЙ ЭНЕРГИИ: ЯЙЦА С ШПИНАТОМ</b>
КБЖУ: 350 ккал • Белки: 28г • Жиры: 24г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 6 шт (холин)
• Шпинат - 200 г (магний)
• Грибы - 200 г (витамин D)
• Сыр фета - 100 г (триптофан)
• Оливковое масло - 1 ст.л.
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (15 минут):</b>
1. Шпинат обжарить 3 минуты
2. Добавить нарезанные грибы
3. Влить взбитые яйца с куркумой
4. Готовить скрэмбл 8 минут
5. Добавить раскрошенную фету

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Холин из яиц является предшественником ацетилхолина - нейромедиатора, критически важного для обучения, памяти и мышечного контроля.
"""
        benefits = """• ⚡ Улучшение ментальной энергии
• 🧠 Усиление нейромедиаторной активности
• 💪 Поддержка мышечной функции
• 🛡️ Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ЗАВТРАК ДЛЯ МЕНТАЛЬНОЙ ЭНЕРГИИ: ЯЙЦА С ШПИНАТОМ",
            content, "mental_energy_breakfast", benefits
        )

    def generate_neuro_protection_breakfast(self):
        """Завтрак для нейропротекции"""
        content = """
🛡️ <b>ЗАВТРАК ДЛЯ НЕЙРОПРОТЕКЦИИ: СМУЗИ С ЧЕРНИКОЙ И АВОКАДО</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 22г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Черника - 200 г (антоцианы)
• Авокадо - 1 шт (глутатион)
• Миндальное молоко - 300 мл (витамин E)
• Семена чиа - 2 ст.л. (Омега-3)
• Шпинат - 50 г (фолат)
• Мед - 1 ст.л. (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Подавать сразу
3. Можно добавить лед
4. Украсить ягодами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы черники преодолевают гематоэнцефалический барьер и накапливаются в областях мозга, ответственных за обучение и память, улучшая нейронные связи.
"""
        benefits = """• 🛡️ Защита нейронов от повреждений
• 🧠 Улучшение нейронных связей
• 🌿 Мощные антиоксиданты
• 💧 Глубокая гидратация"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ЗАВТРАК ДЛЯ НЕЙРОПРОТЕКЦИИ: СМУЗИ С ЧЕРНИКОЙ И АВОКАДО",
            content, "neuro_protection_breakfast", benefits
        )

    def generate_cognitive_balance_breakfast(self):
        """Завтрак для когнитивного баланса"""
        content = """
⚖️ <b>ЗАВТРАК ДЛЯ КОГНИТИВНОГО БАЛАНСА: КИНОА С ОРЕХАМИ</b>
КБЖУ: 380 ккал • Белки: 20г • Жиры: 18г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (магний)
• Миндаль - 50 г (рибофлавин)
• Кешью - 40 г (цинк)
• Кокосовая стружка - 2 ст.л. (МСТ)
• Кленовый сироп - 1 ст.л.
• Корица - 1 ч.л.

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Орехи измельчить
3. Смешать все ингредиенты
4. Заправить сиропом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Магний регулирует NMDA-рецепторы в мозге, предотвращая их чрезмерную активацию, что снижает риск эксайтотоксичности и поддерживает когнитивный баланс.
"""
        benefits = """• ⚖️ Баланс нейротрансмиттеров
• 🧠 Защита от эксайтотоксичности
• 💪 Поддержка нервной системы
• 🔥 Стабильная энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ЗАВТРАК ДЛЯ КОГНИТИВНОГО БАЛАНСА: КИНОА С ОРЕХАМИ",
            content, "cognitive_balance_breakfast", benefits
        )

    def generate_brain_hydration_breakfast(self):
        """Завтрак для гидратации мозга"""
        content = """
💧 <b>ЗАВТРАК ДЛЯ ГИДРАТАЦИИ МОЗГА: АРБУЗНЫЙ САЛАТ С ФЕТОЙ</b>
КБЖУ: 280 ккал • Белки: 18г • Жиры: 12г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Арбуз - 600 г (L-цитруллин)
• Сыр фета - 150 г (кальций)
• Мята - 20 г (ментол)
• Огурцы - 1 шт (кремний)
• Лимонный сок - 2 ст.л.
• Оливковое масло - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Арбуз нарезать кубиками
2. Огурцы нарезать тонкими ломтиками
3. Фету раскрошить
4. Смешать с мятой
5. Заправить соком и маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Мозг на 75% состоит из воды, и даже незначительное обезвоживание (2%) может ухудшить когнитивные функции, внимание и кратковременную память.
"""
        benefits = """• 💧 Оптимальная гидратация мозга
• 🧠 Улучшение когнитивных функций
• 🩸 Улучшение микроциркуляции
• 🌿 Освежающий и тонизирующий эффект"""
        
        return self.visual_manager.generate_attractive_post(
            "💧 ЗАВТРАК ДЛЯ ГИДРАТАЦИИ МОЗГА: АРБУЗНЫЙ САЛАТ С ФЕТОЙ",
            content, "brain_hydration_breakfast", benefits
        )

    def generate_neurogenesis_breakfast(self):
        """Завтрак для стимуляции нейрогенеза"""
        content = """
🌟 <b>ЗАВТРАК ДЛЯ НЕЙРОГЕНЕЗА: ЛОСОСЬ С ЯЙЦОМ ПАШОТ</b>
КБЖУ: 460 ккал • Белки: 40г • Жиры: 32г • Углеводы: 6г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 300 г (Омега-3)
• Яйца - 4 шт (холин)
• Спаржа - 150 г (фолат)
• Авокадо - 1/2 шт (витамин E)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (антиоксиданты)

<b>Приготовление (20 минут):</b>
1. Лосось приготовить на пару 12 минут
2. Яйца сварить пашот 4 минуты
3. Спаржу бланшировать 3 минуты
4. Подавать с авокадо и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты стимулируют нейрогенез - образование новых нейронов в гиппокампе, улучшая способность к обучению и адаптации.
"""
        benefits = """• 🌟 Стимуляция образования новых нейронов
• 📚 Улучшение способности к обучению
• 🧠 Повышение нейропластичности
• 💪 Поддержка когнитивного здоровья"""
        
        return self.visual_manager.generate_attractive_post(
            "🌟 ЗАВТРАК ДЛЯ НЕЙРОГЕНЕЗА: ЛОСОСЬ С ЯЙЦОМ ПАШОТ",
            content, "neurogenesis_breakfast", benefits
        )

    def generate_mood_breakfast(self):
        """Завтрак для улучшения настроения"""
        content = """
😊 <b>ЗАВТРАК ДЛЯ НАСТРОЕНИЯ: БАНАНОВЫЕ ПАНКЕЙКИ</b>
КБЖУ: 420 ккал • Белки: 22г • Жиры: 18г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (триптофан)
• Овсяная мука - 100 г (сложные углеводы)
• Яйца - 2 шт (витамин D)
• Грецкие орехи - 40 г (селен)
• Кленовый сироп - 2 ст.л.
• Корица - 1 ч.л.

<b>Приготовление (20 минут):</b>
1. Бананы размять вилкой
2. Смешать все ингредиенты
3. Жарить на антипригарной сковороде
4. Подавать с сиропом и орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Триптофан из бананов преобразуется в серотонин - "гормон счастья", который улучшает настроение, снижает тревожность и регулирует сон.
"""
        benefits = """• 😊 Улучшение настроения
• 🧘 Снижение тревожности
• 💤 Регуляция циклов сна
• 🔥 Стабильная энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "😊 ЗАВТРАК ДЛЯ НАСТРОЕНИЯ: БАНАНОВЫЕ ПАНКЕЙКИ",
            content, "mood_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (9 рецептов)
    def generate_brain_lunch(self):
        """Обед для когнитивного здоровья"""
        content = """
🧠 <b>ОБЕД ДЛЯ МОЗГА: САЛАТ С ТУНЦОМ И АВОКАДО</b>
КБЖУ: 480 ккал • Белки: 35г • Жиры: 32г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Тунец консервированный - 2 банки (ДГК)
• Авокадо - 1 шт (олеиновая кислота)
• Руккола - 100 г (витамин K)
• Оливки - 50 г (полифенолы)
• Красный лук - 1/2 шт (кверцетин)
• Оливковое масло - 2 ст.л. (олеокантал)
• Лимонный сок - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Тунец размять вилкой
2. Авокадо нарезать кубиками
3. Лук нарезать полукольцами
4. Смешать все ингредиенты
5. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ДГК из тунца увеличивает текучесть клеточных мембран нейронов, улучшая коммуникацию между клетками мозга и скорость обработки информации.
"""
        benefits = """• 🧠 Ускорение нейронной коммуникации
• 💭 Улучшение скорости мышления
• 🛡️ Защита мембран нейронов
• 🔥 Стабильная энергия"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ОБЕД ДЛЯ МОЗГА: САЛАТ С ТУНЦОМ И АВОКАДО",
            content, "brain_lunch", benefits
        )

    def generate_focus_lunch(self):
        """Обед для поддержания фокуса"""
        content = """
🎯 <b>ОБЕД ДЛЯ ФОКУСА: КУРИЦА С БРОККОЛИ И ГРЕЦКИМИ ОРЕХАМИ</b>
КБЖУ: 520 ккал • Белки: 45г • Жиры: 28г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (триптофан)
• Брокколи - 400 г (холин)
• Грецкие орехи - 60 г (Омега-3)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Лимон - 1/2 шт

<b>Приготовление (25 минут):</b>
1. Курицу нарезать и обжарить
2. Брокколи приготовить на пару
3. Орехи измельчить
4. Смешать все компоненты
5. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Холин из брокколи является предшественником ацетилхолина - нейромедиатора, который играет ключевую роль в поддержании внимания и концентрации.
"""
        benefits = """• 🎯 Улучшение концентрации внимания
• 💪 Поддержка нейромедиаторной системы
• 🧠 Усиление когнитивных функций
• 🌿 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ОБЕД ДЛЯ ФОКУСА: КУРИЦА С БРОККОЛИ И ГРЕЦКИМИ ОРЕХАМИ",
            content, "focus_lunch", benefits
        )

    def generate_memory_lunch(self):
        """Обед для улучшения памяти"""
        content = """
📚 <b>ОБЕД ДЛЯ ПАМЯТИ: ЛОСОСЬ С КИНОА И ШПИНАТОМ</b>
КБЖУ: 550 ккал • Белки: 42г • Жиры: 32г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (ЭПК)
• Киноа - 150 г (магний)
• Шпинат - 200 г (лютеин)
• Авокадо - 1 шт (мононенасыщенные жиры)
• Кедровые орехи - 30 г (цинк)
• Лимонный сок - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Лосось запечь 15 минут
2. Киноа отварить 15 минут
3. Шпинат обжарить 3 минуты
4. Смешать все ингредиенты
5. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ЭПК (эйкозапентаеновая кислота) из лосося улучшает кровоснабжение гиппокампа и способствует формированию долговременной памяти.
"""
        benefits = """• 📚 Улучшение долговременной памяти
• 🩸 Улучшение мозгового кровотока
• 🧠 Поддержка гиппокампа
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 ОБЕД ДЛЯ ПАМЯТИ: ЛОСОСЬ С КИНОА И ШПИНАТОМ",
            content, "memory_lunch", benefits
        )

    def generate_mental_clarity_lunch(self):
        """Обед для ментальной ясности"""
        content = """
💎 <b>ОБЕД ДЛЯ МЕНТАЛЬНОЙ ЯСНОСТИ: САЛАТ С СЕМГОЙ И СПАРЖЕЙ</b>
КБЖУ: 480 ккал • Белки: 38г • Жиры: 30г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Семга слабосоленая - 300 г (астаксантин)
• Спаржа - 200 г (глутатион)
• Руккола - 100 г (нитраты)
• Кедровые орехи - 40 г (витамин E)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (15 минут):</b>
1. Спаржа бланшировать 4 минуты
2. Семгу нарезать пластинами
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Астаксантин из семги преодолевает гематоэнцефалический барьер и защищает митохондрии нейронов от окислительного стресса, улучшая ясность мышления.
"""
        benefits = """• 💎 Улучшение ментальной ясности
• 🛡️ Защита митохондрий нейронов
• 🧠 Снижение мозгового тумана
• 🌿 Мощная антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "💎 ОБЕД ДЛЯ МЕНТАЛЬНОЙ ЯСНОСТИ: САЛАТ С СЕМГОЙ И СПАРЖЕЙ",
            content, "mental_clarity_lunch", benefits
        )

    def generate_neuro_energy_lunch(self):
        """Обед для нейроэнергетики"""
        content = """
⚡ <b>ОБЕД ДЛЯ НЕЙРОЭНЕРГЕТИКИ: ГОВЯДИНА С ГРЕЧКОЙ</b>
КБЖУ: 580 ккал • Белки: 48г • Жиры: 25г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (гемовое железо)
• Гречневая крупа - 150 г (рутин)
• Шпинат - 200 г (фолат)
• Грибы - 200 г (эрготионеин)
• Лук - 1 шт (кверцетин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Говядину нарезать и обжарить
2. Гречку отварить 15 минут
3. Овощи обжарить отдельно
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гемовое железо из красного мяса необходимо для производства миелина - изолирующей оболочки нейронов, которая ускоряет передачу нервных импульсов.
"""
        benefits = """• ⚡ Ускорение нервной проводимости
• 💪 Поддержка миелинизации
• 🧠 Улучшение скорости мышления
• 🔥 Высокая энергетическая ценность"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ОБЕД ДЛЯ НЕЙРОЭНЕРГЕТИКИ: ГОВЯДИНА С ГРЕЧКОЙ",
            content, "neuro_energy_lunch", benefits
        )

    def generate_cognitive_support_lunch(self):
        """Обед для когнитивной поддержки"""
        content = """
🛟 <b>ОБЕД ДЛЯ КОГНИТИВНОЙ ПОДДЕРЖКИ: ИНДЕЙКА С ЧЕЧЕВИЦЕЙ</b>
КБЖУ: 520 ккал • Белки: 52г • Жиры: 18г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 500 г (триптофан)
• Чечевица - 200 г (фолат)
• Брокколи - 300 г (сульфорафан)
• Морковь - 2 шт (бета-каротин)
• Чеснок - 3 зубчика (аллицин)
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (40 минут):</b>
1. Индейку нарезать и обжарить
2. Чечевицу отварить 25 минут
3. Овощи приготовить на пару
4. Смешать с куркумой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Фолат из чечевицы необходим для метилирования ДНК в мозге и синтеза нейромедиаторов, поддерживая когнитивные функции на клеточном уровне.
"""
        benefits = """• 🛟 Поддержка когнитивных функций
• 🧬 Участие в метилировании ДНК
• 💪 Синтез нейромедиаторов
• 🌿 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🛟 ОБЕД ДЛЯ КОГНИТИВНОЙ ПОДДЕРЖКИ: ИНДЕЙКА С ЧЕЧЕВИЦЕЙ",
            content, "cognitive_support_lunch", benefits
        )

    def generate_brain_circulation_lunch(self):
        """Обед для улучшения мозгового кровообращения"""
        content = """
🩸 <b>ОБЕД ДЛЯ МОЗГОВОГО КРОВООБРАЩЕНИЯ: СВЕКЛА С ГРЕЦКИМИ ОРЕХАМИ</b>
КБЖУ: 450 ккал • Белки: 22г • Жиры: 28г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 4 шт (нитраты)
• Грецкие орехи - 80 г (аргинин)
• Руккола - 100 г (нитраты)
• Козий сыр - 100 г (кальций)
• Лимонный сок - 3 ст.л.
• Оливковое масло - 2 ст.л.

<b>Приготовление (35 минут):</b>
1. Свеклу запечь 30 минут
2. Орехи измельчить
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Нитраты из свеклы преобразуются в оксид азота, который расширяет кровеносные сосуды и улучшает перфузию мозга, усиливая доставку кислорода и питательных веществ.
"""
        benefits = """• 🩸 Улучшение мозгового кровотока
• 💨 Усиление оксигенации мозга
• 🧠 Улучшение когнитивных функций
• 🌿 Снижение артериального давления"""
        
        return self.visual_manager.generate_attractive_post(
            "🩸 ОБЕД ДЛЯ МОЗГОВОГО КРОВООБРАЩЕНИЯ: СВЕКЛА С ГРЕЦКИМИ ОРЕХАМИ",
            content, "brain_circulation_lunch", benefits
        )

    def generate_neuro_transmitter_lunch(self):
        """Обед для поддержки нейромедиаторов"""
        content = """
🧪 <b>ОБЕД ДЛЯ НЕЙРОМЕДИАТОРОВ: ЯЙЦА С ШПИНАТОМ И ГРИБАМИ</b>
КБЖУ: 480 ккал • Белки: 38г • Жиры: 32г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 6 шт (холин)
• Шпинат - 300 г (магний)
• Шампиньоны - 300 г (витамин D)
• Лук - 1 шт (кверцетин)
• Сыр пармезан - 50 г (тирозин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Лук и грибы обжарить 10 минут
2. Добавить шпинат, готовить 3 минуты
3. Влить взбитые яйца
4. Готовить скрэмбл 8 минут
5. Посыпать пармезаном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Холин из яиц и тирозин из сыра являются строительными блоками для ацетилхолина и дофамина - нейромедиаторов, отвечающих за обучение, мотивацию и удовольствие.
"""
        benefits = """• 🧪 Поддержка синтеза нейромедиаторов
• 🎯 Улучшение мотивации и обучения
• 💭 Усиление когнитивных функций
• 🌿 Сбалансированный профиль питательных веществ"""
        
        return self.visual_manager.generate_attractive_post(
            "🧪 ОБЕД ДЛЯ НЕЙРОМЕДИАТОРОВ: ЯЙЦА С ШПИНАТОМ И ГРИБАМИ",
            content, "neuro_transmitter_lunch", benefits
        )

    def generate_anti_inflammatory_lunch(self):
        """Обед с противовоспалительным действием"""
        content = """
🌿 <b>ОБЕД С ПРОТИВОВОСПАЛИТЕЛЬНЫМ ДЕЙСТВИЕМ: ЛОСОСЬ С КУРКУМОЙ</b>
КБЖУ: 520 ккал • Белки: 42г • Жиры: 35г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Брокколи - 400 г (сульфорафан)
• Куркума - 2 ч.л. (куркумин)
• Чеснок - 4 зубчика (аллицин)
• Имбирь - 2 см (гингерол)
• Кокосовое молоко - 100 мл (МСТ)
• Лимонный сок - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Лосось запечь с куркумой 15 минут
2. Брокколи приготовить на пару
3. Приготовить соус из кокосового молока и специй
4. Полить лосося соусом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Куркумин и Омега-3 синергетически подавляют NF-κB - главный регулятор воспалительных процессов в мозге, снижая нейровоспаление.
"""
        benefits = """• 🌿 Снижение нейровоспаления
• 🛡️ Защита от окислительного стресса
• 🧠 Поддержка когнитивного здоровья
• 💪 Усиление противовоспалительного действия"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ОБЕД С ПРОТИВОВОСПАЛИТЕЛЬНЫМ ДЕЙСТВИЕМ: ЛОСОСЬ С КУРКУМОЙ",
            content, "anti_inflammatory_lunch", benefits
        )

    # 🍽️ УЖИНЫ (9 рецептов)
    def generate_cognitive_dinner(self):
        """Ужин для когнитивного здоровья"""
        content = """
💭 <b>УЖИН ДЛЯ МОЗГА: ЛОСОСЬ С БРОККОЛИ</b>
КБЖУ: 420 ккал • Белки: 38г • Жиры: 25г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Брокколи - 400 г (сульфорафан)
• Грецкие орехи - 40 г (мелатонин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Лимон - 1/2 шт

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Брокколи приготовить на пару
3. Измельчить орехи с чесноком
4. Подавать с оливковым маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сульфорафан из брокколи активирует Nrf2 путь - ключевой регулятор антиоксидантной защиты, защищая мозг от окислительного стресса.
"""
        benefits = """• 🛡️ Активация антиоксидантной защиты
• 🧠 Защита от окислительного стресса
• 💤 Улучшение качества сна
• 🌿 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "💭 УЖИН ДЛЯ МОЗГА: ЛОСОСЬ С БРОККОЛИ",
            content, "cognitive_dinner", benefits
        )

    def generate_brain_recovery_dinner(self):
        """Ужин для восстановления мозга"""
        content = """
🔄 <b>УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ МОЗГА: ТУНЕЦ С АВОКАДО</b>
КБЖУ: 450 ккал • Белки: 35г • Жиры: 32г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Тунец стейк - 400 г (ДГК)
• Авокадо - 1 шт (глутатион)
• Шпинат - 200 г (магний)
• Помидоры черри - 150 г (ликопин)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Тунец обжарить по 2 минуты с каждой стороны
2. Авокадо нарезать ломтиками
3. Шпинат обжарить 2 минуты
4. Смешать все ингредиенты
5. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глутатион из авокадо является главным антиоксидантом мозга и участвует в детоксикации, защищая нейроны от повреждения свободными радикалами.
"""
        benefits = """• 🔄 Восстановление антиоксидантной защиты
• 🧠 Детоксикация мозговой ткани
• 🛡️ Защита от окислительного стресса
• 💪 Поддержка клеточного здоровья"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ МОЗГА: ТУНЕЦ С АВОКАДО",
            content, "brain_recovery_dinner", benefits
        )

    def generate_neuro_protection_dinner(self):
        """Ужин для нейропротекции"""
        content = """
🛡️ <b>УЖИН ДЛЯ НЕЙРОПРОТЕКЦИИ: СЕМГА С СПАРЖЕЙ</b>
КБЖУ: 480 ккал • Белки: 40г • Жиры: 34г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Семга - 400 г (астаксантин)
• Спаржа - 300 г (глутатион)
• Чеснок - 4 зубчика (аллицин)
• Лимон - 1/2 шт (витамин C)
• Оливковое масло - 1 ст.л.
• Розмарин - 2 веточки

<b>Приготовление (25 минут):</b>
1. Семгу запечь с розмарином 15 минут
2. Спаржу обжарить с чесноком 8 минут
3. Полить лимонным соком
4. Подавать с оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Астаксантин из семги в 6000 раз сильнее витамина C по антиоксидантной активности и защищает мозг от перекисного окисления липидов.
"""
        benefits = """• 🛡️ Мощная нейропротекция
• 🧠 Защита от перекисного окисления
• 🌿 Сильное антиоксидантное действие
• 💪 Поддержка клеточных мембран"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ УЖИН ДЛЯ НЕЙРОПРОТЕКЦИИ: СЕМГА С СПАРЖЕЙ",
            content, "neuro_protection_dinner", benefits
        )

    def generate_sleep_quality_dinner(self):
        """Ужин для улучшения качества сна"""
        content = """
💤 <b>УЖИН ДЛЯ КАЧЕСТВЕННОГО СНА: ИНДЕЙКА С БАТАТОМ</b>
КБЖУ: 420 ккал • Белки: 38г • Жиры: 12г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Батат - 400 г (калий)
• Шпинат - 200 г (магний)
• Грибы - 200 г (витамин D)
• Оливковое масло - 1 ст.л.
• Розмарин - 1 веточка

<b>Приготовление (35 минут):</b>
1. Батат запечь 25 минут
2. Индейку обжарить с розмарином
3. Шпинат и грибы обжарить 5 минут
4. Подавать все вместе

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Триптофан из индейки преобразуется в серотонин, а затем в мелатонин - гормон, регулирующий циркадные ритмы и качество сна.
"""
        benefits = """• 💤 Улучшение качества сна
• 🕒 Регуляция циркадных ритмов
• 🧠 Восстановление когнитивных функций
• 🌙 Подготовка к ночному восстановлению"""
        
        return self.visual_manager.generate_attractive_post(
            "💤 УЖИН ДЛЯ КАЧЕСТВЕННОГО СНА: ИНДЕЙКА С БАТАТОМ",
            content, "sleep_quality_dinner", benefits
        )

    def generate_brain_detox_dinner(self):
        """Ужин для детоксикации мозга"""
        content = """
🧪 <b>УЖИН ДЛЯ ДЕТОКСИКАЦИИ МОЗГА: КАПУСТА С ЧЕСНОКОМ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Капуста белокочанная - 600 г (глюкозинолаты)
• Чеснок - 6 зубчиков (сера)
• Лимонный сок - 3 ст.л. (витамин C)
• Оливковое масло - 2 ст.л.
• Семена укропа - 1 ч.л.
• Куркума - 1 ч.л.

<b>Приготовление (25 минут):</b>
1. Капусту нашинковать
2. Обжарить с чесноком 15 минут
3. Добавить специи
4. Тушить под крышкой 5 минут
5. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глюкозинолаты из капусты активируют ферменты второй фазы детоксикации в глиальных клетках мозга, усиливая выведение токсинов.
"""
        benefits = """• 🧪 Активация детокс-ферментов мозга
• 🧠 Очищение мозговой ткани
• 🛡️ Защита от нейротоксинов
• 🌿 Поддержка глиальных клеток"""
        
        return self.visual_manager.generate_attractive_post(
            "🧪 УЖИН ДЛЯ ДЕТОКСИКАЦИИ МОЗГА: КАПУСТА С ЧЕСНОКОМ",
            content, "brain_detox_dinner", benefits
        )

    def generate_neuro_plasticity_dinner(self):
        """Ужин для нейропластичности"""
        content = """
🌀 <b>УЖИН ДЛЯ НЕЙРОПЛАСТИЧНОСТИ: ГОВЯДИНА С ГРИБАМИ</b>
КБЖУ: 460 ккал • Белки: 42г • Жиры: 28г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (креатин)
• Шампиньоны - 400 г (эрготионеин)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Тимьян - 1 ч.л.

<b>Приготовление (30 минут):</b>
1. Говядину нарезать и обжарить
2. Грибы и лук обжарить отдельно
3. Смешать все ингредиенты
4. Тушить с тимьяном 10 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Креатин из говядины увеличивает энергетические запасы в нейронах, поддерживая синаптическую пластичность и способность к обучению.
"""
        benefits = """• 🌀 Улучшение нейропластичности
• ⚡ Повышение энергетических запасов нейронов
• 📚 Усиление способности к обучению
• 💪 Поддержка синаптической функции"""
        
        return self.visual_manager.generate_attractive_post(
            "🌀 УЖИН ДЛЯ НЕЙРОПЛАСТИЧНОСТИ: ГОВЯДИНА С ГРИБАМИ",
            content, "neuro_plasticity_dinner", benefits
        )

    def generate_mood_support_dinner(self):
        """Ужин для поддержки настроения"""
        content = """
😊 <b>УЖИН ДЛЯ ПОДДЕРЖКИ НАСТРОЕНИЯ: КУРИЦА С ОРЕХАМИ</b>
КБЖУ: 520 ккал • Белки: 45г • Жиры: 32г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (триптофан)
• Грецкие орехи - 80 г (Омега-3)
• Шпинат - 200 г (фолат)
• Лук - 1 шт (кверцетин)
• Оливковое масло - 2 ст.л.
• Лимонный сок - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Курицу нарезать и обжарить
2. Орехи измельчить
3. Шпинат обжарить 3 минуты
4. Смешать все компоненты
5. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты увеличивают текучесть клеточных мембран и усиливают сигнализацию серотониновых рецепторов, улучшая настроение.
"""
        benefits = """• 😊 Улучшение настроения
• 🧠 Усиление серотониновой сигнализации
• 💪 Противовоспалительное действие
• 🌿 Поддержка эмоционального баланса"""
        
        return self.visual_manager.generate_attractive_post(
            "😊 УЖИН ДЛЯ ПОДДЕРЖКИ НАСТРОЕНИЯ: КУРИЦА С ОРЕХАМИ",
            content, "mood_support_dinner", benefits
        )

    def generate_stress_resistance_dinner(self):
        """Ужин для устойчивости к стрессу"""
        content = """
🌊 <b>УЖИН ДЛЯ УСТОЙЧИВОСТИ К СТРЕССУ: ТВОРОГ С ОВОЩАМИ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 18г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (триптофан)
• Огурцы - 2 шт (кремний)
• Помидоры - 2 шт (ликопин)
• Укроп - 30 г (эфирные масла)
• Семена тыквы - 30 г (магний)
• Лимонный сок - 2 ст.л.

<b>Приготовление (10 минут):</b>
1. Овощи нарезать кубиками
2. Творог смешать с укропом
3. Добавить семена тыквы
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Магний из тыквенных семечек регулирует активность гипоталамо-гипофизарно-надпочечниковой оси, снижая выработку кортизола в ответ на стресс.
"""
        benefits = """• 🌊 Снижение реакции на стресс
• 🧘 Регуляция уровня кортизола
• 💪 Поддержка надпочечников
• 🌿 Успокаивающее действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌊 УЖИН ДЛЯ УСТОЙЧИВОСТИ К СТРЕССУ: ТВОРОГ С ОВОЩАМИ",
            content, "stress_resistance_dinner", benefits
        )

    def generate_brain_energy_dinner(self):
        """Ужин для энергоснабжения мозга"""
        content = """
🔋 <b>УЖИН ДЛЯ ЭНЕРГОСНАБЖЕНИЯ МОЗГА: ПЕЧЕНЬ С ЛУКОМ</b>
КБЖУ: 350 ккал • Белки: 38г • Жиры: 15г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Куриная печень - 400 г (витамин B12)
• Лук - 2 шт (кверцетин)
• Яблоки - 2 шт (пектин)
• Оливковое масло - 2 ст.л.
• Тимьян - 1 ч.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Печень промыть и обсушить
2. Лук обжарить до золотистости
3. Добавить печень, жарить 8 минут
4. Добавить яблоки и тимьян
5. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Витамин B12 из печени необходим для миелинизации нервных волокон и производства энергии в митохондриях нейронов.
"""
        benefits = """• 🔋 Улучшение энергоснабжения нейронов
• 💪 Поддержка миелинизации
• 🧠 Ускорение нервной проводимости
• 🌿 Высокая питательная ценность"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ ЭНЕРГОСНАБЖЕНИЯ МОЗГА: ПЕЧЕНЬ С ЛУКОМ",
            content, "brain_energy_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (8 рецептов)
    def generate_brain_dessert(self):
        """Десерт для здоровья мозга"""
        content = """
🍫 <b>ДЕСЕРТ ДЛЯ МОЗГА: ШОКОЛАДНЫЕ ШАРИКИ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 22г • Углеводы: 25г

<b>Ингредиенты (на 8 шариков):</b>
• Финики - 150 г (натуральные сахара)
• Грецкие орехи - 100 г (Омега-3)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Кокосовое масло - 2 ст.л. (МСТ)
• Семена чиа - 2 ст.л. (альфа-линоленовая кислота)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке
5. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Флавоноиды какао увеличивают приток крови к мозгу, усиливая нейрогенез в зубчатой извилине гиппокампа - области, критически важной для памяти.
"""
        benefits = """• 🧠 Улучшение мозгового кровотока
• 🌟 Стимуляция нейрогенеза
• 📚 Улучшение памяти
• 🍫 Натуральные антиоксиданты"""
        
        return self.visual_manager.generate_attractive_post(
            "🍫 ДЕСЕРТ ДЛЯ МОЗГА: ШОКОЛАДНЫЕ ШАРИКИ",
            content, "brain_dessert", benefits
        )

    def generate_memory_dessert(self):
        """Десерт для улучшения памяти"""
        content = """
📚 <b>ДЕСЕРТ ДЛЯ ПАМЯТИ: ЯГОДНЫЙ ПАРФЕ</b>
КБЖУ: 280 ккал • Белки: 18г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Черника - 150 г (антоцианы)
• Малина - 100 г (эллаговая кислота)
• Грецкие орехи - 40 г (полифенолы)
• Мед - 1 ст.л. (натуральные сахара)
• Мята - для украшения

<b>Приготовление (5 минут):</b>
1. Слоями выложить йогурт и ягоды
2. Посыпать измельченными орехами
3. Полить медом
4. Украсить мятой
5. Охладить 15 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы черники накапливаются в гиппокампе и улучшают пространственную память, усиливая нейронные связи в этой критически важной области.
"""
        benefits = """• 📚 Улучшение пространственной памяти
• 🧠 Усиление нейронных связей
• 🦠 Поддержка микробиома
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 ДЕСЕРТ ДЛЯ ПАМЯТИ: ЯГОДНЫЙ ПАРФЕ",
            content, "memory_dessert", benefits
        )

    def generate_focus_dessert(self):
        """Десерт для концентрации"""
        content = """
🎯 <b>ДЕСЕРТ ДЛЯ КОНЦЕНТРАЦИИ: БАНАНОВЫЙ ПУДИНГ</b>
КБЖУ: 300 ккал • Белки: 15г • Жиры: 14г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (калий)
• Семена чиа - 4 ст.л. (Омега-3)
• Миндальное молоко - 300 мл
• Миндаль - 30 г (рибофлавин)
• Корица - 1 ч.л. (циннамальдегид)
• Мед - 1 ст.л.

<b>Приготовление (5 минут + настаивание):</b>
1. Бананы размять вилкой
2. Смешать с семенами чиа и молоком
3. Добавить корицу и мед
4. Настаивать 4 часа или overnight
5. Посыпать миндалем перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Калий из бананов регулирует электрическую активность нейронов, поддерживая оптимальную возбудимость клеток мозга для поддержания концентрации.
"""
        benefits = """• 🎯 Улучшение концентрации внимания
• ⚡ Регуляция нейронной активности
• 🧠 Поддержка электрических свойств нейронов
• 🌿 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ДЕСЕРТ ДЛЯ КОНЦЕНТРАЦИИ: БАНАНОВЫЙ ПУДИНГ",
            content, "focus_dessert", benefits
        )

    def generate_mood_enhancing_dessert(self):
        """Десерт для улучшения настроения"""
        content = """
😊 <b>ДЕСЕРТ ДЛЯ НАСТРОЕНИЯ: ФИНИКОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 8 трюфелей):</b>
• Финики - 200 г (триптофан)
• Овсяные хлопья - 80 г (сложные углеводы)
• Какао-порошок - 3 ст.л. (фенилэтиламин)
• Арахисовая паста - 2 ст.л. (белок)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут + охлаждение):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке
5. Охладить 2 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Фенилэтиламин из какао стимулирует выработку эндорфинов и дофамина, создавая чувство удовольствия и улучшая настроение.
"""
        benefits = """• 😊 Улучшение настроения
• 💫 Стимуляция выработки эндорфинов
• 🧠 Усиление дофаминовой активности
• 🍫 Натуральный антидепрессант"""
        
        return self.visual_manager.generate_attractive_post(
            "😊 ДЕСЕРТ ДЛЯ НАСТРОЕНИЯ: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "mood_enhancing_dessert", benefits
        )

    def generate_neuro_protection_dessert(self):
        """Десерт для нейропротекции"""
        content = """
🛡️ <b>ДЕСЕРТ ДЛЯ НЕЙРОПРОТЕКЦИИ: ЯГОДНОЕ ЖЕЛЕ</b>
КБЖУ: 180 ккал • Белки: 12г • Жиры: 6г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Смесь ягод - 300 г (антоцианы)
• Желатин - 20 г (глицин)
• Стевия - по вкусу
• Лимонный сок - 1 ст.л. (витамин C)
• Мята - для украшения

<b>Приготовление (15 минут + охлаждение):</b>
1. Ягоды взбить в пюре
2. Растворить желатин
3. Смешать все ингредиенты
4. Разлить по формам
5. Охладить 4 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глицин из желатина является ингибиторным нейромедиатором, который защищает нейроны от эксайтотоксичности и снижает тревожность.
"""
        benefits = """• 🛡️ Защита от эксайтотоксичности
• 🧘 Снижение тревожности
• 🧠 Улучшение качества сна
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ДЕСЕРТ ДЛЯ НЕЙРОПРОТЕКЦИИ: ЯГОДНОЕ ЖЕЛЕ",
            content, "neuro_protection_dessert", benefits
        )

    def generate_brain_energy_dessert(self):
        """Десерт для энергии мозга"""
        content = """
⚡ <b>ДЕСЕРТ ДЛЯ ЭНЕРГИИ МОЗГА: КОКОСОВЫЕ КУБИКИ</b>
КБЖУ: 220 ккал • Белки: 8г • Жиры: 15г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Кокосовое молоко - 400 мл (МСТ)
• Банан - 1 шт (калий)
• Мед - 1 ст.л. (глюкоза)
• Ванильный экстракт - 1 ч.л.
• Кокосовая стружка - 2 ст.л.

<b>Приготовление (10 минут + заморозка):</b>
1. Все ингредиенты взбить в блендере
2. Разлить по формам для льда
3. Заморозить 4 часа
4. Посыпать кокосовой стружкой перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Среднецепочечные триглицериды (МСТ) из кокосового молока быстро метаболизируются в кетоновые тела - эффективный источник энергии для мозга, особенно при умственных нагрузках.
"""
        benefits = """• ⚡ Быстрая энергия для мозга
• 🧠 Альтернативное топливо для нейронов
• 💪 Поддержка когнитивных функций
• 🥥 Легкое и освежающее"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ДЕСЕРТ ДЛЯ ЭНЕРГИИ МОЗГА: КОКОСОВЫЕ КУБИКИ",
            content, "brain_energy_dessert", benefits
        )

    def generate_cognitive_balance_dessert(self):
        """Десерт для когнитивного баланса"""
        content = """
⚖️ <b>ДЕСЕРТ ДЛЯ КОГНИТИВНОГО БАЛАНСА: ЯБЛОЧНОЕ ПЮРЕ</b>
КБЖУ: 190 ккал • Белки: 8г • Жиры: 6г • Углеводы: 30г

<b>Ингредиенты (на 2 порции):</b>
• Яблоки - 4 шт (пектин)
• Корица - 1 ч.л. (антиоксиданты)
• Лимонный сок - 1 ст.л.
• Грецкие орехи - 20 г (Омега-3)
• Мед - 1 ч.л. (натуральные сахара)

<b>Приготовление (15 минут):</b>
1. Яблоки запечь 12 минут
2. Размять в пюре
3. Добавить корицу и лимонный сок
4. Украсить орехами и медом
5. Охладить 30 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пектин из яблок регулирует уровень сахара в крови, предотвращая резкие колебания, которые могут негативно влиять на когнитивные функции и настроение.
"""
        benefits = """• ⚖️ Стабилизация уровня сахара в крови
• 🧠 Поддержка когнитивного баланса
• 💫 Предотвращение перепадов настроения
• 🌿 Пребиотическое действие"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ДЕСЕРТ ДЛЯ КОГНИТИВНОГО БАЛАНСА: ЯБЛОЧНОЕ ПЮРЕ",
            content, "cognitive_balance_dessert", benefits
        )

    def generate_stress_relief_dessert(self):
        """Десерт для снятия стресса"""
        content = """
🌿 <b>ДЕСЕРТ ДЛЯ СНЯТИЯ СТРЕССА: ЛАВАНДОВЫЙ ПУДИНГ</b>
КБЖУ: 260 ккал • Белки: 12г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Авокадо - 1 шт (глутатион)
• Банан - 1 шт (магний)
• Миндальное молоко - 200 мл
• Мед - 1 ст.л. (успокаивающее)
• Лаванда сушеная - 1 ч.л. (линалоол)
• Семена чиа - 2 ст.л.

<b>Приготовление (5 минут + настаивание):</b>
1. Все ингредиенты взбить в блендере
2. Добавить лаванду
3. Настаивать 2 часа в холодильнике
4. Украсить свежей лавандой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Линалоол из лаванды модулирует GABA-ергическую систему, усиливая тормозные процессы в мозге и снижая тревожность и стресс.
"""
        benefits = """• 🌿 Снижение тревожности и стресса
• 🧘 Успокаивающее действие на нервную систему
• 💤 Улучшение качества сна
• 🛡️ Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ДЕСЕРТ ДЛЯ СНЯТИЯ СТРЕССА: ЛАВАНДОВЫЙ ПУДИНГ",
            content, "stress_relief_dessert", benefits
        )

# Создание экземпляра генератора
friday_generator = FridayContentGenerator()
class SaturdayContentGenerator:
    """Генератор контента для субботы - иммунитет и восстановление"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (9 рецептов)
    def generate_immune_boost_breakfast(self):
        """Завтрак для усиления иммунитета"""
        content = """
🛡️ <b>ЗАВТРАК ДЛЯ ИММУНИТЕТА: ЦИТРУСОВЫЙ СМУЗИ БОУЛ</b>
КБЖУ: 320 ккал • Белки: 18г • Жиры: 10г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Апельсины - 2 шт (витамин C)
• Киви - 2 шт (витамин K)
• Имбирь - 3 см (гингерол)
• Куркума - 1 ч.л. (куркумин)
• Миндальное молоко - 300 мл (витамин E)
• Семена чиа - 2 ст.л. (клетчатка)
• Мед - 1 ст.л. (антимикробные свойства)

<b>Приготовление (5 минут):</b>
1. Цитрусы очистить от кожуры
2. Все ингредиенты взбить в блендере
3. Вылить в миску
4. Украсить семенами чиа и дольками киви

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Витамин C стимулирует производство и функцию лейкоцитов, усиливая способность иммунной системы бороться с патогенами и ускоряя восстановление.
"""
        benefits = """• 🛡️ Усиление функции лейкоцитов
• 🦠 Повышение устойчивости к инфекциям
• 🔥 Противовоспалительное действие
• 💪 Ускорение восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ЗАВТРАК ДЛЯ ИММУНИТЕТА: ЦИТРУСОВЫЙ СМУЗИ БОУЛ",
            content, "immune_boost_breakfast", benefits
        )

    def generate_gut_health_breakfast(self):
        """Завтрак для здоровья кишечника"""
        content = """
🦠 <b>ЗАВТРАК ДЛЯ ЗДОРОВЬЯ КИШЕЧНИКА: ПРОБИОТИЧЕСКАЯ ОВСЯНКА</b>
КБЖУ: 350 ккал • Белки: 20г • Жиры: 12г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 120 г (бета-глюканы)
• Греческий йогурт - 200 г (пробиотики)
• Банан - 1 шт (пребиотики)
• Семена льна - 2 ст.л. (клетчатка)
• Ягоды годжи - 20 г (полисахариды)
• Корица - 1 ч.л. (антимикробные свойства)

<b>Приготовление (15 минут):</b>
1. Овсянку варить 10 минут
2. Добавить йогурт и банан
3. Посыпать семенами и ягодами
4. Добавить корицу

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пробиотики из йогурта колонизируют кишечник полезными бактериями, которые составляют 70% иммунной системы и производят короткоцепочечные жирные кислоты.
"""
        benefits = """• 🦠 Поддержка микробиома кишечника
• 🛡️ Усиление иммунного барьера
• 💪 Производство бутирата
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🦠 ЗАВТРАК ДЛЯ ЗДОРОВЬЯ КИШЕЧНИКА: ПРОБИОТИЧЕСКАЯ ОВСЯНКА",
            content, "gut_health_breakfast", benefits
        )

    def generate_antiviral_breakfast(self):
        """Завтрак с противовирусными свойствами"""
        content = """
🦠 <b>ЗАВТРАК С ПРОТИВОВИРУСНЫМИ СВОЙСТВАМИ: ИМБИРНАЯ КАША</b>
КБЖУ: 380 ккал • Белки: 15г • Жиры: 8г • Углеводы: 65г

<b>Ингредиенты (на 2 порции):</b>
• Пшено - 150 г (магний)
• Имбирь - 4 см (гингерол)
• Чеснок - 2 зубчика (аллицин)
• Лимон - 1/2 шт (витамин C)
• Мед - 2 ст.л. (прополис)
• Корица - 1 ч.л. (циннамальдегид)

<b>Приготовление (25 минут):</b>
1. Пшено промыть и отварить 20 минут
2. Добавить тертый имбирь и чеснок
3. Заправить лимонным соком и медом
4. Посыпать корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Аллицин из чеснока обладает мощной противовирусной активностью, ингибируя репликацию вирусов и усиливая иммунный ответ.
"""
        benefits = """• 🦠 Подавление репликации вирусов
• 🛡️ Усиление иммунного ответа
• 🔥 Противовоспалительное действие
• 💪 Антимикробные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🦠 ЗАВТРАК С ПРОТИВОВИРУСНЫМИ СВОЙСТВАМИ: ИМБИРНАЯ КАША",
            content, "antiviral_breakfast", benefits
        )

    def generate_lymphatic_breakfast(self):
        """Завтрак для поддержки лимфатической системы"""
        content = """
🌊 <b>ЗАВТРАК ДЛЯ ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: КРАСНАЯ ЧЕЧЕВИЦА</b>
КБЖУ: 420 ккал • Белки: 28г • Жиры: 10г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Красная чечевица - 200 г (цинк)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (натрий)
• Куркума - 2 ч.л. (куркумин)
• Лимонный сок - 2 ст.л. (витамин C)
• Петрушка - 30 г (хлорофилл)

<b>Приготовление (20 минут):</b>
1. Чечевицу отварить 15 минут
2. Овощи нарезать и обжарить
3. Смешать с куркумой
4. Заправить лимонным соком и петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из чечевицы необходим для развития и активации T-лимфоцитов - ключевых клеток иммунной системы, которые идентифицируют и уничтожают патогены.
"""
        benefits = """• 🌊 Поддержка лимфатической системы
• 🦠 Активация T-лимфоцитов
• 🛡️ Усиление клеточного иммунитета
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌊 ЗАВТРАК ДЛЯ ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: КРАСНАЯ ЧЕЧЕВИЦА",
            content, "lymphatic_breakfast", benefits
        )

    def generate_antioxidant_immune_breakfast(self):
        """Антиоксидантный завтрак для иммунитета"""
        content = """
🍇 <b>АНТИОКСИДАНТНЫЙ ЗАВТРАК: ЯГОДНЫЙ КИНОА</b>
КБЖУ: 360 ккал • Белки: 18г • Жиры: 12г • Углеводы: 52г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (кверцетин)
• Гранат - 1 шт (пуникалагины)
• Черника - 150 г (антоцианы)
• Грецкие орехи - 40 г (полифенолы)
• Мед - 1 ст.л. (прополис)
• Корица - 1 ч.л.

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Гранат очистить от зерен
3. Смешать все ингредиенты
4. Заправить медом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пуникалагины из граната защищают иммунные клетки от окислительного стресса и усиливают их способность к фагоцитозу - поглощению патогенов.
"""
        benefits = """• 🍇 Защита иммунных клеток от стресса
• 🦠 Усиление фагоцитарной активности
• 🛡️ Антиоксидантная защита
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🍇 АНТИОКСИДАНТНЫЙ ЗАВТРАК: ЯГОДНЫЙ КИНОА",
            content, "antioxidant_immune_breakfast", benefits
        )

    def generate_anti_inflammatory_breakfast(self):
        """Противовоспалительный завтрак"""
        content = """
🌿 <b>ПРОТИВОВОСПАЛИТЕЛЬНЫЙ ЗАВТРАК: КУРКУМНЫЙ СМУЗИ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 8г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Ананас - 300 г (бромелайн)
• Куркума - 2 ч.л. (куркумин)
• Черный перец - 1/4 ч.л. (пиперин)
• Кокосовое молоко - 200 мл (МСТ)
• Шпинат - 50 г (магний)
• Мед - 1 ст.л.

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Подавать сразу
3. Можно добавить лед
4. Украсить щепоткой куркумы

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Куркумин подавляет активность NF-κB - главного регулятора воспалительных процессов, снижая производство провоспалительных цитокинов.
"""
        benefits = """• 🌿 Снижение системного воспаления
• 🛡️ Подавление провоспалительных цитокинов
• 💪 Усиление противовоспалительного ответа
• 🔥 Облегчение симптомов воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ПРОТИВОВОСПАЛИТЕЛЬНЫЙ ЗАВТРАК: КУРКУМНЫЙ СМУЗИ",
            content, "anti_inflammatory_breakfast", benefits
        )

    def generate_immune_cell_breakfast(self):
        """Завтрак для производства иммунных клеток"""
        content = """
🩸 <b>ЗАВТРАК ДЛЯ ПРОИЗВОДСТВА ИММУННЫХ КЛЕТОК: ПЕЧЕНЬ С ЯЙЦОМ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 22г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Куриная печень - 300 г (железо)
• Яйца - 4 шт (витамин D)
• Лук - 1 шт (кверцетин)
• Шпинат - 100 г (фолат)
• Оливковое масло - 2 ст.л.
• Тимьян - 1 ч.л. (тимол)

<b>Приготовление (20 минут):</b>
1. Печень промыть и обжарить 8 минут
2. Яйца приготовить скрэмбл
3. Лук и шпинат обжарить
4. Смешать все с тимьяном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Железо из печени необходимо для производства гемоглобина и оксигенации тканей, а также для пролиферации и дифференцировки иммунных клеток в костном мозге.
"""
        benefits = """• 🩸 Поддержка гемопоэза в костном мозге
• 🦠 Производство иммунных клеток
• 💪 Улучшение оксигенации тканей
• 🛡️ Усиление иммунного ответа"""
        
        return self.visual_manager.generate_attractive_post(
            "🩸 ЗАВТРАК ДЛЯ ПРОИЗВОДСТВА ИММУННЫХ КЛЕТОК: ПЕЧЕНЬ С ЯЙЦОМ",
            content, "immune_cell_breakfast", benefits
        )

    def generate_mucosal_immunity_breakfast(self):
        """Завтрак для слизистого иммунитета"""
        content = """
👄 <b>ЗАВТРАК ДЛЯ СЛИЗИСТОГО ИММУНИТЕТА: ТЫКВЕННАЯ КАША</b>
КБЖУ: 350 ккал • Белки: 18г • Жиры: 10г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 500 г (бета-каротин)
• Овсяные хлопья - 100 г (бета-глюканы)
• Миндаль - 40 г (витамин E)
• Корица - 1 ч.л. (антимикробные свойства)
• Мед - 1 ст.л. (прополис)
• Имбирь - 2 см (гингерол)

<b>Приготовление (25 минут):</b>
1. Тыкву запечь 20 минут
2. Овсянку варить 10 минут
3. Смешать с тыквой и специями
4. Посыпать миндалем

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-каротин преобразуется в витамин A, который поддерживает целостность слизистых оболочек - первого барьера иммунной системы против патогенов.
"""
        benefits = """• 👄 Укрепление слизистых барьеров
• 🛡️ Защита от проникновения патогенов
• 💪 Поддержка эпителиальных тканей
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "👄 ЗАВТРАК ДЛЯ СЛИЗИСТОГО ИММУНИТЕТА: ТЫКВЕННАЯ КАША",
            content, "mucosal_immunity_breakfast", benefits
        )

    def generate_adaptive_immunity_breakfast(self):
        """Завтрак для адаптивного иммунитета"""
        content = """
🎯 <b>ЗАВТРАК ДЛЯ АДАПТИВНОГО ИММУНИТЕТА: ГРИБЫ С ЯЙЦАМИ</b>
КБЖУ: 320 ккал • Белки: 28г • Жиры: 18г • Углеводы: 15г

<b>Ингредиенты (на 2 порции):</b>
• Шиитаке грибы - 300 г (бета-глюканы)
• Яйца - 4 шт (витамин D)
• Чеснок - 3 зубчика (аллицин)
• Шпинат - 100 г (железо)
• Оливковое масло - 2 ст.л.
• Петрушка - 20 г (витамин C)

<b>Приготовление (20 минут):</b>
1. Грибы обжарить 10 минут
2. Добавить чеснок и шпинат
3. Влить взбитые яйца
4. Готовить скрэмбл 8 минут
5. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-глюканы из грибов шиитаке активируют дендритные клетки, которые представляют антигены T-лимфоцитам, усиливая адаптивный иммунный ответ.
"""
        benefits = """• 🎯 Активация адаптивного иммунитета
• 🦠 Усиление презентации антигенов
• 🛡️ Поддержка T-клеточного ответа
• 💪 Противовирусные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ЗАВТРАК ДЛЯ АДАПТИВНОГО ИММУНИТЕТА: ГРИБЫ С ЯЙЦАМИ",
            content, "adaptive_immunity_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (9 рецептов)
    def generate_immune_support_lunch(self):
        """Обед для поддержки иммунной системы"""
        content = """
🛡️ <b>ОБЕД ДЛЯ ПОДДЕРЖКИ ИММУННОЙ СИСТЕМЫ: КУРИНЫЙ СУП</b>
КБЖУ: 420 ккал • Белки: 35г • Жиры: 15г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 400 г (цистеин)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (натрий)
• Лук - 2 шт (кверцетин)
• Чеснок - 6 зубчиков (аллицин)
• Имбирь - 3 см (гингерол)
• Куркума - 1 ч.л. (куркумин)

<b>Приготовление (40 минут):</b>
1. Курицу отварить 25 минут
2. Овощи нарезать кубиками
3. Добавить в бульон, варить 15 минут
4. Добавить специи за 5 минут до готовности

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цистеин из куриного белка разжижает мокроту и обладает противовоспалительными свойствами, облегчая симптомы респираторных инфекций.
"""
        benefits = """• 🛡️ Поддержка иммунной функции
• 🫁 Облегчение респираторных симптомов
• 🔥 Противовоспалительное действие
• 💪 Ускорение восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ОБЕД ДЛЯ ПОДДЕРЖКИ ИММУННОЙ СИСТЕМЫ: КУРИНЫЙ СУП",
            content, "immune_support_lunch", benefits
        )

    def generate_antimicrobial_lunch(self):
        """Обед с антимикробными свойствами"""
        content = """
🧄 <b>ОБЕД С АНТИМИКРОБНЫМИ СВОЙСТВАМИ: ЧЕСНОЧНЫЙ СТЕЙК</b>
КБЖУ: 480 ккал • Белки: 42г • Жиры: 28г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Говяжий стейк - 500 г (цинк)
• Чеснок - 8 зубчиков (аллицин)
• Розмарин - 3 веточки (карнозол)
• Брокколи - 400 г (сульфорафан)
• Оливковое масло - 2 ст.л.
• Лимон - 1/2 шт

<b>Приготовление (25 минут):</b>
1. Стейк обжарить с чесноком и розмарином
2. Брокколи приготовить на пару
3. Полить лимонным соком
4. Подавать с оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Аллицин из чеснока обладает широким спектром антимикробной активности против бактерий, вирусов и грибов, усиливая врожденный иммунитет.
"""
        benefits = """• 🧄 Широкий спектр антимикробной активности
• 🦠 Подавление патогенных микроорганизмов
• 🛡️ Усиление врожденного иммунитета
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🧄 ОБЕД С АНТИМИКРОБНЫМИ СВОЙСТВАМИ: ЧЕСНОЧНЫЙ СТЕЙК",
            content, "antimicrobial_lunch", benefits
        )

    def generate_gut_immunity_lunch(self):
        """Обед для кишечного иммунитета"""
        content = """
🦠 <b>ОБЕД ДЛЯ КИШЕЧНОГО ИММУНИТЕТА: КИМЧИ С ТОФУ</b>
КБЖУ: 350 ккал • Белки: 25г • Жиры: 12г • Углеводы: 40г

<b>Ингредиенты (на 2 порции):</b>
• Тофу - 400 г (изофлавоны)
• Кимчи - 200 г (пробиотики)
• Шпинат - 200 г (хлорофилл)
• Грибы - 200 г (бета-глюканы)
• Кунжутное масло - 1 ст.л.
• Семена кунжута - 2 ст.л.

<b>Приготовление (20 минут):</b>
1. Тофу нарезать и обжарить
2. Добавить грибы и шпинат
3. Смешать с кимчи
4. Заправить кунжутным маслом
5. Посыпать семенами кунжута

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пробиотики из кимчи колонизируют кишечник и стимулируют производство IgA - иммуноглобулина, который защищает слизистые оболочки от патогенов.
"""
        benefits = """• 🦠 Стимуляция производства IgA
• 🛡️ Защита слизистых оболочек
• 💪 Поддержка кишечного барьера
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🦠 ОБЕД ДЛЯ КИШЕЧНОГО ИММУНИТЕТА: КИМЧИ С ТОФУ",
            content, "gut_immunity_lunch", benefits
        )

    def generate_lymph_cleansing_lunch(self):
        """Обед для очищения лимфатической системы"""
        content = """
🌿 <b>ОБЕД ДЛЯ ОЧИЩЕНИЯ ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: СВЕКЛА С ЯБЛОКАМИ</b>
КБЖУ: 320 ккал • Белки: 15г • Жиры: 8г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 4 шт (бетаин)
• Яблоки - 3 шт (пектин)
• Лимонный сок - 3 ст.л. (витамин C)
• Имбирь - 2 см (гингерол)
• Петрушка - 30 г (хлорофилл)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Свеклу запечь 25 минут
2. Яблоки натереть на терке
3. Смешать все ингредиенты
4. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бетаин из свеклы поддерживает функцию печени - основного органа детоксикации, который фильтрует лимфу и удаляет токсины и патогены.
"""
        benefits = """• 🌿 Поддержка детоксикации печени
• 🩸 Очищение лимфатической системы
• 🛡️ Удаление токсинов и патогенов
• 💪 Улучшение иммунной функции"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ОБЕД ДЛЯ ОЧИЩЕНИЯ ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: СВЕКЛА С ЯБЛОКАМИ",
            content, "lymph_cleansing_lunch", benefits
        )

    def generate_cytokine_balance_lunch(self):
        """Обед для баланса цитокинов"""
        content = """
⚖️ <b>ОБЕД ДЛЯ БАЛАНСА ЦИТОКИНОВ: ЛОСОСЬ С КУРКУМОЙ</b>
КБЖУ: 450 ккал • Белки: 38г • Жиры: 28г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Куркума - 2 ч.л. (куркумин)
• Брокколи - 400 г (сульфорафан)
• Чеснок - 4 зубчика (аллицин)
• Кинза - 20 г (антиоксиданты)
• Лимонный сок - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Лосось запечь с куркумой 15 минут
2. Брокколи приготовить на пару
3. Смешать с чесноком и кинзой
4. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты модулируют производство цитокинов, снижая провоспалительные (IL-6, TNF-α) и усиливая противовоспалительные цитокины (IL-10).
"""
        benefits = """• ⚖️ Баланс провоспалительных и противовоспалительных цитокинов
• 🔥 Снижение системного воспаления
• 🛡️ Усиление противовоспалительного ответа
• 💪 Поддержка иммунной регуляции"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ОБЕД ДЛЯ БАЛАНСА ЦИТОКИНОВ: ЛОСОСЬ С КУРКУМОЙ",
            content, "cytokine_balance_lunch", benefits
        )

    def generate_immune_modulation_lunch(self):
        """Обед для модуляции иммунного ответа"""
        content = """
🎛️ <b>ОБЕД ДЛЯ МОДУЛЯЦИИ ИММУННОГО ОТВЕТА: ГРИБНОЙ РИСОТТО</b>
КБЖУ: 480 ккал • Белки: 22г • Жиры: 18г • Углеводы: 65г

<b>Ингредиенты (на 2 порции):</b>
• Бурый рис - 200 г (селен)
• Грибы шиитаке - 200 г (лентинан)
• Грибы майтаке - 200 г (бета-глюканы)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Пармезан - 50 г (цинк)

<b>Приготовление (35 минут):</b>
1. Рис отварить 30 минут
2. Грибы обжарить с луком и чесноком
3. Смешать все компоненты
4. Посыпать пармезаном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лентинан из грибов шиитаке модулирует иммунный ответ, усиливая активность макрофагов и натуральных киллеров без чрезмерной стимуляции воспаления.
"""
        benefits = """• 🎛️ Сбалансированная модуляция иммунного ответа
• 🦠 Активация макрофагов и NK-клеток
• 🛡️ Усиление врожденного иммунитета
• 💪 Противовирусные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "🎛️ ОБЕД ДЛЯ МОДУЛЯЦИИ ИММУННОГО ОТВЕТА: ГРИБНОЙ РИСОТТО",
            content, "immune_modulation_lunch", benefits
        )

    def generate_antioxidant_defense_lunch(self):
        """Обед для антиоксидантной защиты"""
        content = """
🍅 <b>ОБЕД ДЛЯ АНТИОКСИДАНТНОЙ ЗАЩИТЫ: ТОМАТНЫЙ СУП</b>
КБЖУ: 350 ккал • Белки: 18г • Жиры: 12г • Углеводы: 48г

<b>Ингредиенты (на 2 порции):</b>
• Помидоры - 800 г (ликопин)
• Лук - 2 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Базилик - 30 г (эвгенол)
• Оливковое масло - 2 ст.л.
• Красный перец - 1 шт (витамин C)

<b>Приготовление (30 минут):</b>
1. Помидоры бланшировать и очистить
2. Лук и чеснок обжарить
3. Варить 20 минут
4. Взбить блендером
5. Добавить базилик

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Ликопин из томатов защищает иммунные клетки от окислительного стресса, усиливая их выживаемость и функциональность при борьбе с инфекциями.
"""
        benefits = """• 🍅 Защита иммунных клеток от окислительного стресса
• 🛡️ Усиление выживаемости иммунных клеток
• 💪 Улучшение функциональности иммунной системы
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🍅 ОБЕД ДЛЯ АНТИОКСИДАНТНОЙ ЗАЩИТЫ: ТОМАТНЫЙ СУП",
            content, "antioxidant_defense_lunch", benefits
        )

    def generate_interferon_boost_lunch(self):
        """Обед для усиления интерферонов"""
        content = """
🦠 <b>ОБЕД ДЛЯ УСИЛЕНИЯ ИНТЕРФЕРОНОВ: ИНДЕЙКА С БРОККОЛИ</b>
КБЖУ: 520 ккал • Белки: 48г • Жиры: 22г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 500 г (триптофан)
• Брокколи - 500 г (глюкозинолаты)
• Чеснок - 6 зубчиков (аллицин)
• Имбирь - 3 см (гингерол)
• Куркума - 1 ч.л. (куркумин)
• Лимонный сок - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Индейку нарезать и обжарить
2. Брокколи приготовить на пару
3. Смешать с чесноком и специями
4. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глюкозинолаты из брокколи активируют Nrf2 путь, который усиливает производство интерферонов - ключевых противовирусных белков иммунной системы.
"""
        benefits = """• 🦠 Усиление производства интерферонов
• 🛡️ Противовирусная защита
• 💪 Активация Nrf2 пути
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🦠 ОБЕД ДЛЯ УСИЛЕНИЯ ИНТЕРФЕРОНОВ: ИНДЕЙКА С БРОККОЛИ",
            content, "interferon_boost_lunch", benefits
        )

    def generate_immune_memory_lunch(self):
        """Обед для иммунной памяти"""
        content = """
📚 <b>ОБЕД ДЛЯ ИММУННОЙ ПАМЯТИ: ЧЕЧЕВИЦА С ОВОЩАМИ</b>
КБЖУ: 450 ккал • Белки: 28г • Жиры: 15г • Углеводы: 60г

<b>Ингредиенты (на 2 порции):</b>
• Чечевица - 200 г (цинк)
• Морковь - 3 шт (бета-каротин)
• Цукини - 2 шт (кремний)
• Лук - 2 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Петрушка - 30 г (витамин C)

<b>Приготовление (30 минут):</b>
1. Чечевицу отварить 20 минут
2. Овощи нарезать и обжарить
3. Смешать все компоненты
4. Заправить маслом и петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из чечевицы необходим для развития памяти B- и T-лимфоцитов, которые обеспечивают долгосрочную защиту от ранее встреченных патогенов.
"""
        benefits = """• 📚 Поддержка иммунной памяти
• 🦠 Долгосрочная защита от патогенов
• 🛡️ Развитие памяти B- и T-лимфоцитов
• 💪 Усиление адаптивного иммунитета"""
        
        return self.visual_manager.generate_attractive_post(
            "📚 ОБЕД ДЛЯ ИММУННОЙ ПАМЯТИ: ЧЕЧЕВИЦА С ОВОЩАМИ",
            content, "immune_memory_lunch", benefits
        )

    # 🍽️ УЖИНЫ (9 рецептов)
    def generate_recovery_dinner(self):
        """Ужин для восстановления иммунной системы"""
        content = """
🔄 <b>УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ ИММУННОЙ СИСТЕМЫ: РЫБА НА ПАРУ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 22г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Белая рыба - 400 г (селен)
• Брокколи - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Имбирь - 3 см (гингерол)
• Лимон - 1/2 шт (витамин C)
• Укроп - 20 г (эфирные масла)

<b>Приготовление (20 минут):</b>
1. Рыбу и овощи выложить в пароварку
2. Готовить 15 минут на пару
3. Полить лимонным соком
4. Посыпать укропом и имбирем

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Селен из рыбы является кофактором глутатионпероксидазы - ключевого антиоксидантного фермента, который защищает иммунные клетки от окислительного повреждения.
"""
        benefits = """• 🔄 Восстановление иммунных клеток
• 🛡️ Защита от окислительного повреждения
• 💪 Поддержка антиоксидантной системы
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ ИММУННОЙ СИСТЕМЫ: РЫБА НА ПАРУ",
            content, "recovery_dinner", benefits
        )

    def generate_anti_stress_dinner(self):
        """Ужин для снижения стресса и поддержки иммунитета"""
        content = """
😌 <b>УЖИН ДЛЯ СНИЖЕНИЯ СТРЕССА: ИНДЕЙКА С ШПИНАТОМ</b>
КБЖУ: 420 ккал • Белки: 45г • Жиры: 18г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 500 г (триптофан)
• Шпинат - 400 г (магний)
• Грибы - 200 г (эрготионеин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Мускатный орех - 1/4 ч.л. (успокаивающее)

<b>Приготовление (25 минут):</b>
1. Индейку нарезать и обжарить
2. Шпинат и грибы обжарить отдельно
3. Смешать все компоненты
4. Добавить мускатный орех

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Хронический стресс повышает уровень кортизола, который подавляет функцию иммунных клеток. Магний из шпината помогает регулировать стрессовую реакцию.
"""
        benefits = """• 😌 Снижение уровня стресса
• 🧘 Регуляция уровня кортизола
• 🛡️ Поддержка иммунной функции
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "😌 УЖИН ДЛЯ СНИЖЕНИЯ СТРЕССА: ИНДЕЙКА С ШПИНАТОМ",
            content, "anti_stress_dinner", benefits
        )

    def generate_detox_immune_dinner(self):
        """Ужин для детоксикации и иммунитета"""
        content = """
🧪 <b>УЖИН ДЛЯ ДЕТОКСИКАЦИИ И ИММУНИТЕТА: КАПУСТА С ЧЕСНОКОМ</b>
КБЖУ: 280 ккал • Белки: 18г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Капуста белокочанная - 600 г (глюкозинолаты)
• Чеснок - 6 зубчиков (сера)
• Лимонный сок - 3 ст.л. (витамин C)
• Имбирь - 3 см (гингерол)
• Оливковое масло - 2 ст.л.
• Семена укропа - 1 ч.л.

<b>Приготовление (25 минут):</b>
1. Капусту нашинковать
2. Обжарить с чесноком и имбирем 15 минут
3. Добавить семена укропа
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Глюкозинолаты активируют ферменты второй фазы детоксикации в печени, усиливая выведение токсинов, которые могут ослаблять иммунную систему.
"""
        benefits = """• 🧪 Активация детокс-ферментов
• 🛡️ Удаление иммуносупрессивных токсинов
• 💪 Поддержка функции печени
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🧪 УЖИН ДЛЯ ДЕТОКСИКАЦИИ И ИММУНИТЕТА: КАПУСТА С ЧЕСНОКОМ",
            content, "detox_immune_dinner", benefits
        )

    def generate_sleep_immune_dinner(self):
        """Ужин для улучшения сна и иммунитета"""
        content = """
💤 <b>УЖИН ДЛЯ УЛУЧШЕНИЯ СНА И ИММУНИТЕТА: ТВОРОГ С БАНАНОМ</b>
КБЖУ: 320 ккал • Белки: 35г • Жиры: 12г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (триптофан)
• Бананы - 2 шт (мелатонин)
• Миндаль - 30 г (магний)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ст.л. (успокаивающее)
• Семена тыквы - 2 ст.л. (цинк)

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Бананы нарезать кружками
3. Добавить орехи и семена
4. Заправить медом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Качественный сон усиливает производство цитокинов и антител, а также улучшает функцию T-клеток, делая иммунную систему более эффективной.
"""
        benefits = """• 💤 Улучшение качества сна
• 🛡️ Усиление производства цитокинов и антител
• 💪 Улучшение функции T-клеток
• 🌙 Поддержка циркадных ритмов"""
        
        return self.visual_manager.generate_attractive_post(
            "💤 УЖИН ДЛЯ УЛУЧШЕНИЯ СНА И ИММУНИТЕТА: ТВОРОГ С БАНАНОМ",
            content, "sleep_immune_dinner", benefits
        )

    def generate_lymph_drainage_dinner(self):
        """Ужин для дренажа лимфатической системы"""
        content = """
🌊 <b>УЖИН ДЛЯ ДРЕНАЖА ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: ОВОЩИ НА ПАРУ</b>
КБЖУ: 240 ккал • Белки: 15г • Жиры: 6г • Углеводы: 38г

<b>Ингредиенты (на 2 порции):</b>
• Цветная капуста - 400 г (глюкозинолаты)
• Брокколи - 300 г (сульфорафан)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (натрий)
• Лимонный сок - 2 ст.л. (витамин C)
• Имбирь - 2 см (гингерол)

<b>Приготовление (20 минут):</b>
1. Овощи нарезать крупными кусками
2. Приготовить на пару 15 минут
3. Полить лимонным соком
4. Посыпать тертым имбирем

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Овощи на пару сохраняют максимум питательных веществ, которые поддерживают лимфатический дренаж и удаление токсинов из межклеточного пространства.
"""
        benefits = """• 🌊 Поддержка лимфатического дренажа
• 🧪 Удаление токсинов из тканей
• 🛡️ Улучшение иммунного надзора
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌊 УЖИН ДЛЯ ДРЕНАЖА ЛИМФАТИЧЕСКОЙ СИСТЕМЫ: ОВОЩИ НА ПАРУ",
            content, "lymph_drainage_dinner", benefits
        )

    def generate_immune_barrier_dinner(self):
        """Ужин для укрепления иммунных барьеров"""
        content = """
🚧 <b>УЖИН ДЛЯ УКРЕПЛЕНИЯ ИММУННЫХ БАРЬЕРОВ: ТЫКВЕННОЕ ПЮРЕ</b>
КБЖУ: 290 ккал • Белки: 18г • Жиры: 10г • Углеводы: 38г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 800 г (бета-каротин)
• Картофель - 2 шт (калий)
• Чеснок - 4 зубчика (аллицин)
• Кокосовые сливки - 100 мл (лауриновая кислота)
• Мускатный орех - 1/4 ч.л. (миристицин)
• Петрушка - 20 г (витамин C)

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Запечь 25 минут до мягкости
3. Размять в пюре
4. Добавить кокосовые сливки и специи
5. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бета-каротин поддерживает целостность эпителиальных барьеров (кожа, слизистые), которые являются первой линией защиты от патогенов.
"""
        benefits = """• 🚧 Укрепление эпителиальных барьеров
• 🛡️ Первая линия защиты от патогенов
• 💪 Поддержка целостности слизистых
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🚧 УЖИН ДЛЯ УКРЕПЛЕНИЯ ИММУННЫХ БАРЬЕРОВ: ТЫКВЕННОЕ ПЮРЕ",
            content, "immune_barrier_dinner", benefits
        )

    def generate_mitochondrial_immune_dinner(self):
        """Ужин для митохондриального здоровья иммунных клеток"""
        content = """
🔋 <b>УЖИН ДЛЯ МИТОХОНДРИАЛЬНОГО ЗДОРОВЬЯ: ГОВЯДИНА С ГРИБАМИ</b>
КБЖУ: 460 ккал • Белки: 42г • Жиры: 28г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (коэнзим Q10)
• Шампиньоны - 400 г (эрготионеин)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Розмарин - 2 веточки (антиоксиданты)

<b>Приготовление (30 минут):</b>
1. Говядину нарезать и обжарить
2. Грибы и лук обжарить отдельно
3. Смешать все ингредиенты
4. Добавить розмарин

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Коэнзим Q10 из говядины поддерживает функцию митохондрий в иммунных клетках, обеспечивая их энергией для эффективной борьбы с патогенами.
"""
        benefits = """• 🔋 Поддержка митохондрий иммунных клеток
• ⚡ Обеспечение энергией для иммунного ответа
• 🛡️ Усиление функции иммунных клеток
• 💪 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 УЖИН ДЛЯ МИТОХОНДРИАЛЬНОГО ЗДОРОВЬЯ: ГОВЯДИНА С ГРИБАМИ",
            content, "mitochondrial_immune_dinner", benefits
        )

    def generate_adaptive_recovery_dinner(self):
        """Ужин для восстановления адаптивного иммунитета"""
        content = """
🔄 <b>УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ АДАПТИВНОГО ИММУНИТЕТА: КУРИЦА С ЧЕЧЕВИЦЕЙ</b>
КБЖУ: 520 ккал • Белки: 52г • Жиры: 18г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (цистеин)
• Чечевица - 200 г (цинк)
• Морковь - 3 шт (бета-каротин)
• Лук - 2 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Куркума - 1 ч.л. (куркумин)
• Петрушка - 30 г (витамин C)

<b>Приготовление (35 минут):</b>
1. Курицу нарезать и обжарить
2. Чечевицу отварить 20 минут
3. Овощи обжарить отдельно
4. Смешать все с куркумой
5. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из чечевицы необходим для тимопоэза - процесса созревания T-лимфоцитов в тимусе, которые являются основой адаптивного иммунитета.
"""
        benefits = """• 🔄 Восстановление адаптивного иммунитета
• 🦠 Поддержка созревания T-лимфоцитов
• 🛡️ Усиление клеточного иммунитета
• 💪 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ АДАПТИВНОГО ИММУНИТЕТА: КУРИЦА С ЧЕЧЕВИЦЕЙ",
            content, "adaptive_recovery_dinner", benefits
        )

    def generate_innate_immunity_dinner(self):
        """Ужин для врожденного иммунитета"""
        content = """
🛡️ <b>УЖИН ДЛЯ ВРОЖДЕННОГО ИММУНИТЕТА: ЛОСОСЬ С КИНОА</b>
КБЖУ: 480 ккал • Белки: 38г • Жиры: 25г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Киноа - 150 г (кверцетин)
• Шпинат - 200 г (лютеин)
• Чеснок - 4 зубчика (аллицин)
• Лимонный сок - 2 ст.л. (витамин C)
• Кинза - 20 г (антиоксиданты)

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Киноа отварить 15 минут
3. Шпинат обжарить 3 минуты
4. Смешать все ингредиенты
5. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Омега-3 жирные кислоты усиливают фагоцитарную активность макрофагов и нейтрофилов - ключевых клеток врожденного иммунитета, которые первыми реагируют на инфекцию.
"""
        benefits = """• 🛡️ Усиление врожденного иммунитета
• 🦠 Улучшение фагоцитарной активности
• 💪 Быстрый ответ на инфекции
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ УЖИН ДЛЯ ВРОЖДЕННОГО ИММУНИТЕТА: ЛОСОСЬ С КИНОА",
            content, "innate_immunity_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (8 рецептов)
    def generate_immune_dessert(self):
        """Десерт для поддержки иммунитета"""
        content = """
🍯 <b>ДЕСЕРТ ДЛЯ ПОДДЕРЖКИ ИММУНИТЕТА: МЕДОВЫЕ ФИНИКИ</b>
КБЖУ: 280 ккал • Белки: 8г • Жиры: 10г • Углеводы: 45г

<b>Ингредиенты (на 8 шариков):</b>
• Финики - 200 г (натуральные сахара)
• Грецкие орехи - 80 г (Омега-3)
• Мед - 3 ст.л. (прополис)
• Корица - 1 ч.л. (антимикробные свойства)
• Имбирь - 1 ч.л. (гингерол)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке
5. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Прополис из меда обладает мощными антимикробными и иммуномодулирующими свойствами, усиливая сопротивляемость организма инфекциям.
"""
        benefits = """• 🍯 Антимикробные и иммуномодулирующие свойства
• 🛡️ Усиление сопротивляемости инфекциям
• 💪 Противовоспалительное действие
• 🌿 Натуральная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🍯 ДЕСЕРТ ДЛЯ ПОДДЕРЖКИ ИММУНИТЕТА: МЕДОВЫЕ ФИНИКИ",
            content, "immune_dessert", benefits
        )

    def generate_probiotic_dessert(self):
        """Пробиотический десерт"""
        content = """
🦠 <b>ПРОБИОТИЧЕСКИЙ ДЕСЕРТ: ЙОГУРТОВЫЙ ПАРФЕ</b>
КБЖУ: 240 ккал • Белки: 18г • Жиры: 8г • Углеводы: 30г

<b>Ингредиенты (на 2 порции):</b>
• Греческий йогурт - 400 г (пробиотики)
• Киви - 2 шт (витамин C)
• Банан - 1 шт (пребиотики)
• Семена чиа - 2 ст.л. (клетчатка)
• Мед - 1 ст.л. (антимикробные свойства)
• Мята - для украшения

<b>Приготовление (5 минут):</b>
1. Слоями выложить йогурт и фрукты
2. Посыпать семенами чиа
3. Полить медом
4. Украсить мятой
5. Охладить 15 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Пробиотики из йогурта колонизируют кишечник и стимулируют производство IgA, усиливая слизистый иммунитет - первую линию защиты от патогенов.
"""
        benefits = """• 🦠 Колонизация кишечника полезными бактериями
• 🛡️ Усиление слизистого иммунитета
• 💪 Производство иммуноглобулина A
• 🌿 Поддержка микробиома"""
        
        return self.visual_manager.generate_attractive_post(
            "🦠 ПРОБИОТИЧЕСКИЙ ДЕСЕРТ: ЙОГУРТОВЫЙ ПАРФЕ",
            content, "probiotic_dessert", benefits
        )

    def generate_antioxidant_immune_dessert(self):
        """Антиоксидантный десерт для иммунитета"""
        content = """
🍓 <b>АНТИОКСИДАНТНЫЙ ДЕСЕРТ: ЯГОДНОЕ ЖЕЛЕ</b>
КБЖУ: 180 ккал • Белки: 12г • Жиры: 4г • Углеводы: 30г

<b>Ингредиенты (на 2 порции):</b>
• Клубника - 200 г (эллаговая кислота)
• Малина - 150 г (антоцианы)
• Черника - 150 г (флавоноиды)
• Желатин - 20 г (глицин)
• Лимонный сок - 1 ст.л. (витамин C)
• Стевия - по вкусу

<b>Приготовление (15 минут + охлаждение):</b>
1. Ягоды взбить в пюре
2. Растворить желатин
3. Смешать все ингредиенты
4. Разлить по формам
5. Охладить 4 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы из ягод защищают иммунные клетки от окислительного стресса, усиливая их выживаемость и функциональность при борьбе с инфекциями.
"""
        benefits = """• 🍓 Защита иммунных клеток от окислительного стресса
• 🛡️ Усиление выживаемости иммунных клеток
• 💪 Улучшение функциональности иммунной системы
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🍓 АНТИОКСИДАНТНЫЙ ДЕСЕРТ: ЯГОДНОЕ ЖЕЛЕ",
            content, "antioxidant_immune_dessert", benefits
        )

    def generate_anti_inflammatory_dessert(self):
        """Противовоспалительный десерт"""
        content = """
🌿 <b>ПРОТИВОВОСПАЛИТЕЛЬНЫЙ ДЕСЕРТ: КУРКУМНЫЙ ПУДИНГ</b>
КБЖУ: 220 ккал • Белки: 15г • Жиры: 10г • Углеводы: 25г

<b>Ингредиенты (на 2 порции):</b>
• Авокадо - 1 шт (мононенасыщенные жиры)
• Банан - 1 шт (калий)
• Куркума - 2 ч.л. (куркумин)
• Черный перец - 1/4 ч.л. (пиперин)
• Кокосовое молоко - 100 мл (МСТ)
• Мед - 1 ст.л. (прополис)
• Корица - 1 ч.л.

<b>Приготовление (5 минут):</b>
1. Все ингредиенты взбить в блендере
2. Разлить по креманкам
3. Охладить 2 часа
4. Посыпать корицей перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Куркумин подавляет активность COX-2 и LOX ферментов, снижая производство провоспалительных простагландинов и лейкотриенов.
"""
        benefits = """• 🌿 Снижение системного воспаления
• 🛡️ Подавление провоспалительных медиаторов
• 💪 Усиление противовоспалительного ответа
• 🔥 Облегчение симптомов воспаления"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ПРОТИВОВОСПАЛИТЕЛЬНЫЙ ДЕСЕРТ: КУРКУМНЫЙ ПУДИНГ",
            content, "anti_inflammatory_dessert", benefits
        )

    def generate_zinc_boost_dessert(self):
        """Десерт для усиления цинка"""
        content = """
⚡ <b>ДЕСЕРТ ДЛЯ УСИЛЕНИЯ ЦИНКА: ТЫКВЕННЫЕ КОНФЕТЫ</b>
КБЖУ: 260 ккал • Белки: 12г • Жиры: 14г • Углеводы: 28г

<b>Ингредиенты (на 8 конфет):</b>
• Тыквенные семечки - 100 г (цинк)
• Финики - 150 г (натуральные сахара)
• Какао-порошок - 2 ст.л. (магний)
• Кокосовое масло - 2 ст.л. (МСТ)
• Корица - 1 ч.л. (антиоксиданты)
• Ванильный экстракт - 1 ч.л.

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Семечки измельчить в блендере
3. Смешать все ингредиенты
4. Сформировать конфеты
5. Охладить 2 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из тыквенных семечек необходим для развития и активации T-лимфоцитов, а также для производства антител B-лимфоцитами.
"""
        benefits = """• ⚡ Поддержка развития T-лимфоцитов
• 🦠 Усиление производства антител
• 🛡️ Активация адаптивного иммунитета
• 💪 Противовирусные свойства"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ДЕСЕРТ ДЛЯ УСИЛЕНИЯ ЦИНКА: ТЫКВЕННЫЕ КОНФЕТЫ",
            content, "zinc_boost_dessert", benefits
        )

    def generate_vitamin_c_dessert(self):
        """Десерт, богатый витамином C"""
        content = """
🍊 <b>ДЕСЕРТ, БОГАТЫЙ ВИТАМИНОМ C: ЦИТРУСОВЫЙ ГРАНИТА</b>
КБЖУ: 140 ккал • Белки: 6г • Жиры: 2г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Апельсины - 3 шт (витамин C)
• Грейпфрут - 1 шт (нарингин)
• Лимон - 1/2 шт (лимонен)
• Мед - 1 ст.л. (прополис)
• Мята - 15 г (ментол)
• Вода - 100 мл

<b>Приготовление (10 минут + заморозка):</b>
1. Цитрусы выжать, получить сок
2. Добавить мед и воду
3. Разлить по формам и заморозить
4. Перед подачей размять вилкой
5. Украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Витамин C усиливает хемотаксис и фагоцитоз нейтрофилов, улучшая их способность находить и уничтожать патогены в очаге инфекции.
"""
        benefits = """• 🍊 Усиление функции нейтрофилов
• 🦠 Улучшение фагоцитарной активности
• 🛡️ Ускорение иммунного ответа
• 💪 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🍊 ДЕСЕРТ, БОГАТЫЙ ВИТАМИНОМ C: ЦИТРУСОВЫЙ ГРАНИТА",
            content, "vitamin_c_dessert", benefits
        )

    def generate_selenium_rich_dessert(self):
        """Десерт, богатый селеном"""
        content = """
🌰 <b>ДЕСЕРТ, БОГАТЫЙ СЕЛЕНОМ: БРАЗИЛЬСКИЕ ОРЕХИ В ШОКОЛАДЕ</b>
КБЖУ: 300 ккал • Белки: 10г • Жиры: 22г • Углеводы: 22г

<b>Ингредиенты (на 8 конфет):</b>
• Бразильские орехи - 100 г (селен)
• Темный шоколад - 100 г (флавоноиды)
• Кокосовое масло - 1 ст.л. (МСТ)
• Мед - 1 ст.л. (прополис)
• Морская соль - щепотка

<b>Приготовление (15 минут):</b>
1. Шоколад растопить с кокосовым маслом
2. Добавить мед и соль
3. Орехи обмакнуть в шоколад
4. Выложить на пергамент
5. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Селен из бразильских орехов является кофактором глутатионпероксидазы, защищающей иммунные клетки от перекисного окисления липидов.
"""
        benefits = """• 🌰 Защита иммунных клеток от окислительного повреждения
• 🛡️ Поддержка антиоксидантной системы
• 💪 Усиление функции иммунных клеток
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌰 ДЕСЕРТ, БОГАТЫЙ СЕЛЕНОМ: БРАЗИЛЬСКИЕ ОРЕХИ В ШОКОЛАДЕ",
            content, "selenium_rich_dessert", benefits
        )

    def generate_immune_relaxation_dessert(self):
        """Десерт для релаксации и иммунитета"""
        content = """
😌 <b>ДЕСЕРТ ДЛЯ РЕЛАКСАЦИИ И ИММУНИТЕТА: ЛАВАНДОВЫЙ ЧАЙ</b>
КБЖУ: 80 ккал • Белки: 2г • Жиры: 0г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Цветки лаванды - 2 ст.л. (линалоол)
• Мед - 2 ст.л. (прополис)
• Лимон - 1/2 шт (витамин C)
• Имбирь - 2 см (гингерол)
• Вода - 500 мл

<b>Приготовление (10 минут):</b>
1. Лаванду залить кипятком
2. Настаивать 5 минут
3. Добавить тертый имбирь
4. Процедить, добавить мед и лимон
5. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Линалоол из лаванды активирует парасимпатическую нервную систему, снижая уровень кортизола и создавая оптимальные условия для работы иммунной системы.
"""
        benefits = """• 😌 Активация парасимпатической нервной системы
• 🧘 Снижение уровня кортизола
• 🛡️ Создание оптимальных условий для иммунитета
• 💪 Успокаивающее и расслабляющее действие"""
        
        return self.visual_manager.generate_attractive_post(
            "😌 ДЕСЕРТ ДЛЯ РЕЛАКСАЦИИ И ИММУНИТЕТА: ЛАВАНДОВЫЙ ЧАЙ",
            content, "immune_relaxation_dessert", benefits
        )

# Создание экземпляра генератора
saturday_generator = SaturdayContentGenerator()
class SundayContentGenerator:
    """Генератор контента для воскресенья - баланс и подготовка к неделе"""
    
    def __init__(self):
        self.visual_manager = VisualManager()
    
    # 🍳 ЗАВТРАКИ (9 рецептов)
    def generate_weekly_balance_breakfast(self):
        """Сбалансированный завтрак для подготовки к неделе"""
        content = """
⚖️ <b>СБАЛАНСИРОВАННЫЙ ЗАВТРАК: БЕЛКОВО-УГЛЕВОДНЫЙ КОМПЛЕКС</b>
КБЖУ: 420 ккал • Белки: 25г • Жиры: 18г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 4 шт (полноценный белок)
• Авокадо - 1 шт (полезные жиры)
• Цельнозерновой хлеб - 4 ломтика (сложные углеводы)
• Помидоры - 2 шт (ликопин)
• Шпинат - 100 г (магний)
• Оливковое масло - 1 ст.л.

<b>Приготовление (15 минут):</b>
1. Яйца приготовить скрэмбл
2. Хлеб поджарить
3. Авокадо нарезать ломтиками
4. Собрать тосты с яйцами и овощами
5. Полить оливковым маслом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сбалансированное соотношение белков, жиров и углеводов обеспечивает стабильный уровень энергии и поддерживает оптимальный метаболизм для продуктивной недели.
"""
        benefits = """• ⚖️ Идеальный баланс макронутриентов
• 🔥 Стабильная энергия на 4-5 часов
• 💪 Поддержка метаболизма
• 🧠 Подготовка к умственным нагрузкам"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ЗАВТРАК: БЕЛКОВО-УГЛЕВОДНЫЙ КОМПЛЕКС",
            content, "weekly_balance_breakfast", benefits
        )

    def generate_metabolic_boost_breakfast(self):
        """Завтрак для ускорения метаболизма"""
        content = """
🔥 <b>ЗАВТРАК ДЛЯ МЕТАБОЛИЗМА: ОВСЯНКА С КОРИЦЕЙ И ЯБЛОКАМИ</b>
КБЖУ: 380 ккал • Белки: 18г • Жиры: 12г • Углеводы: 58г

<b>Ингредиенты (на 2 порции):</b>
• Овсяные хлопья - 120 г (бета-глюканы)
• Яблоки - 2 шт (пектин)
• Корица - 2 ч.л. (циннамальдегид)
• Грецкие орехи - 40 г (Омега-3)
• Семена льна - 2 ст.л. (лигнаны)
• Мед - 1 ст.л. (ферменты)

<b>Приготовление (15 минут):</b>
1. Овсянку варить 10 минут
2. Яблоки натереть на терке
3. Добавить корицу и орехи
4. Заправить медом и семенами льна

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Циннамальдегид из корицы активирует термогенез и увеличивает расход энергии, подготавливая метаболизм к активной неделе.
"""
        benefits = """• 🔥 Активация термогенеза
• ⚡ Увеличение расхода энергии
• 💪 Подготовка метаболизма
• 🍎 Стабилизация уровня сахара"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ЗАВТРАК ДЛЯ МЕТАБОЛИЗМА: ОВСЯНКА С КОРИЦЕЙ И ЯБЛОКАМИ",
            content, "metabolic_boost_breakfast", benefits
        )

    def generate_hormonal_balance_breakfast(self):
        """Завтрак для гормонального баланса"""
        content = """
🎭 <b>ЗАВТРАК ДЛЯ ГОРМОНАЛЬНОГО БАЛАНСА: ТВОРОГ С СЕМЕНАМИ</b>
КБЖУ: 350 ккал • Белки: 32г • Жиры: 18г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (тирозин)
• Семена тыквы - 30 г (цинк)
• Семена льна - 2 ст.л. (лигнаны)
• Семена подсолнечника - 30 г (витамин E)
• Корица - 1 ч.л. (регулятор инсулина)
• Ягоды - 100 г (антиоксиданты)

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Добавить все семена
3. Посыпать корицей
4. Украсить ягодами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из тыквенных семечек поддерживает функцию щитовидной железы и производство тестостерона, обеспечивая гормональный баланс на предстоящую неделю.
"""
        benefits = """• 🎭 Поддержка гормонального баланса
• 🦋 Оптимизация функции щитовидной железы
• 💪 Синтез важных гормонов
• 🌿 Фитоэстрогены для баланса"""
        
        return self.visual_manager.generate_attractive_post(
            "🎭 ЗАВТРАК ДЛЯ ГОРМОНАЛЬНОГО БАЛАНса: ТВОРОГ С СЕМЕНАМИ",
            content, "hormonal_balance_breakfast", benefits
        )

    def generate_stress_resistance_breakfast(self):
        """Завтрак для устойчивости к стрессу"""
        content = """
🛡️ <b>ЗАВТРАК ДЛЯ УСТОЙЧИВОСТИ К СТРЕССУ: БАНАНОВЫЕ ПАНКЕЙКИ</b>
КБЖУ: 400 ккал • Белки: 22г • Жиры: 15г • Углеводы: 52г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (магний)
• Овсяная мука - 100 г (триптофан)
• Яйца - 2 шт (холин)
• Грецкие орехи - 40 г (Омега-3)
• Кленовый сироп - 2 ст.л.
• Корица - 1 ч.л.

<b>Приготовление (20 минут):</b>
1. Бананы размять вилкой
2. Смешать все ингредиенты
3. Жарить на антипригарной сковороде
4. Подавать с сиропом и орехами

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Магний из бананов регулирует активность HPA-оси (гипоталамо-гипофизарно-надпочечниковой), снижая выработку кортизола в ответ на стресс.
"""
        benefits = """• 🛡️ Снижение реакции на стресс
• 🧘 Регуляция уровня кортизола
• 💪 Поддержка надпочечников
• 😌 Успокаивающее действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ЗАВТРАК ДЛЯ УСТОЙЧИВОСТИ К СТРЕССУ: БАНАНОВЫЕ ПАНКЕЙКИ",
            content, "stress_resistance_breakfast", benefits
        )

    def generate_energy_reserve_breakfast(self):
        """Завтрак для создания энергетических резервов"""
        content = """
🔋 <b>ЗАВТРАК ДЛЯ ЭНЕРГЕТИЧЕСКИХ РЕЗЕРВОВ: ГРЕЧНЕВАЯ КАША С МАСЛОМ</b>
КБЖУ: 450 ккал • Белки: 18г • Жиры: 20г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Гречневая крупа - 150 г (сложные углеводы)
• Сливочное масло - 30 г (жирорастворимые витамины)
• Яйца - 2 шт (белок)
• Яблоки - 2 шт (пектин)
• Корица - 1 ч.л.
• Мед - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Гречку отварить 15 минут
2. Добавить сливочное масло
3. Яйца сварить вкрутую
4. Яблоки натереть на терке
5. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сложные углеводы гречки пополняют запасы гликогена в печени и мышцах, создавая энергетический резерв для продуктивной недели.
"""
        benefits = """• 🔋 Пополнение запасов гликогена
• ⚡ Создание энергетического резерва
• 💪 Подготовка к физическим нагрузкам
• 🧠 Поддержка умственной активности"""
        
        return self.visual_manager.generate_attractive_post(
            "🔋 ЗАВТРАК ДЛЯ ЭНЕРГЕТИЧЕСКИХ РЕЗЕРВОВ: ГРЕЧНЕВАЯ КАША С МАСЛОМ",
            content, "energy_reserve_breakfast", benefits
        )

    def generate_digestive_prep_breakfast(self):
        """Завтрак для подготовки пищеварительной системы"""
        content = """
🌿 <b>ЗАВТРАК ДЛЯ ПИЩЕВАРЕНИЯ: КИНОА С ИМБИРЕМ И КУРКУМОЙ</b>
КБЖУ: 380 ккал • Белки: 20г • Жиры: 12г • Углеводы: 52г

<b>Ингредиенты (на 2 порции):</b>
• Киноа - 120 г (клетчатка)
• Имбирь - 3 см (гингерол)
• Куркума - 1 ч.л. (куркумин)
• Кокосовое молоко - 200 мл (МСТ)
• Банан - 1 шт (пребиотики)
• Мед - 1 ст.л.

<b>Приготовление (20 минут):</b>
1. Киноа отварить 15 минут
2. Добавить тертый имбирь и куркуму
3. Залить кокосовым молоком
4. Добавить банан и мед

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гингерол из имбиря стимулирует выработку пищеварительных ферментов и желчи, подготавливая ЖКТ к эффективному перевариванию пищи в течение недели.
"""
        benefits = """• 🌿 Стимуляция пищеварительных ферментов
• 💫 Улучшение моторики ЖКТ
• 🦠 Подготовка микробиома
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ЗАВТРАК ДЛЯ ПИЩЕВАРЕНИЯ: КИНОА С ИМБИРЕМ И КУРКУМОЙ",
            content, "digestive_prep_breakfast", benefits
        )

    def generate_cognitive_prep_breakfast(self):
        """Завтрак для когнитивной подготовки"""
        content = """
🧠 <b>ЗАВТРАК ДЛЯ КОГНИТИВНОЙ ПОДГОТОВКИ: ЯЙЦА С ЛОСОСЕМ</b>
КБЖУ: 420 ккал • Белки: 35г • Жиры: 28г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Яйца - 4 шт (холин)
• Лосось слабосоленый - 150 г (ДГК)
• Шпинат - 100 г (лютеин)
• Авокадо - 1/2 шт (олеиновая кислота)
• Оливковое масло - 1 ст.л.
• Лимонный сок - 1 ст.л.

<b>Приготовление (15 минут):</b>
1. Яйца приготовить скрэмбл
2. Лосось нарезать пластинами
3. Шпинат обжарить 2 минуты
4. Собрать блюдо с авокадо
5. Полить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ДГК из лосося усиливает текучесть клеточных мембран нейронов, улучшая синаптическую передачу и готовя мозг к интенсивной умственной работе.
"""
        benefits = """• 🧠 Улучшение синаптической передачи
• 💭 Подготовка к умственным нагрузкам
• 🧪 Усиление нейромедиаторной активности
• 🔥 Долгая энергия для мозга"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ЗАВТРАК ДЛЯ КОГНИТИВНОЙ ПОДГОТОВКИ: ЯЙЦА С ЛОСОСЕМ",
            content, "cognitive_prep_breakfast", benefits
        )

    def generate_weekly_detox_breakfast(self):
        """Завтрак для детоксикации перед неделей"""
        content = """
🍋 <b>ЗАВТРАК ДЛЯ ДЕТОКСИКАЦИИ: ЦИТРУСОВЫЙ СМУЗИ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 8г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Апельсины - 2 шт (витамин C)
• Лимон - 1/2 шт (лимонен)
• Имбирь - 3 см (гингерол)
• Шпинат - 50 г (хлорофилл)
• Семена чиа - 2 ст.л. (клетчатка)
• Вода - 200 мл

<b>Приготовление (5 минут):</b>
1. Цитрусы очистить от кожуры
2. Все ингредиенты взбить в блендере
3. Подавать сразу
4. Можно добавить лед

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лимонен из цитрусов активирует ферменты печени, ответственные за детоксикацию, очищая организм перед началом новой недели.
"""
        benefits = """• 🍋 Активация детокс-ферментов печени
• 🧪 Очищение от накопленных токсинов
• 💪 Подготовка к метаболическим нагрузкам
• 🌿 Антиоксидантная защита"""
        
        return self.visual_manager.generate_attractive_post(
            "🍋 ЗАВТРАК ДЛЯ ДЕТОКСИКАЦИИ: ЦИТРУСОВЫЙ СМУЗИ",
            content, "weekly_detox_breakfast", benefits
        )

    def generate_muscle_prep_breakfast(self):
        """Завтрак для подготовки мышц"""
        content = """
💪 <b>ЗАВТРАК ДЛЯ ПОДГОТОВКИ МЫШЦ: ТВОРОГ С БАНАНОМ</b>
КБЖУ: 360 ккал • Белки: 32г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Бананы - 2 шт (калий)
• Миндаль - 30 г (магний)
• Семена тыквы - 20 г (цинк)
• Мед - 1 ст.л. (гликоген)
• Корица - 1 ч.л.

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Бананы нарезать кружками
3. Добавить орехи и семена
4. Заправить медом и корицей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога обеспечивает медленное высвобождение аминокислот, создавая белковый резерв для восстановления и роста мышц в течение недели.
"""
        benefits = """• 💪 Создание белкового резерва
• 🔄 Медленное высвобождение аминокислот
• 🏃 Подготовка к физическим нагрузкам
• 💥 Поддержка мышечного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 ЗАВТРАК ДЛЯ ПОДГОТОВКИ МЫШЦ: ТВОРОГ С БАНАНОМ",
            content, "muscle_prep_breakfast", benefits
        )

    # 🍲 ОБЕДЫ (9 рецептов)
    def generate_balanced_nutrition_lunch(self):
        """Сбалансированный обед для комплексной подготовки"""
        content = """
⚖️ <b>СБАЛАНСИРОВАННЫЙ ОБЕД: КУРИЦА С КИНОА И ОВОЩАМИ</b>
КБЖУ: 520 ккал • Белки: 45г • Жиры: 22г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (белок)
• Киноа - 150 г (полноценный белок)
• Брокколи - 300 г (глюкозинолаты)
• Морковь - 2 шт (бета-каротин)
• Авокадо - 1 шт (полезные жиры)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Курицу нарезать и обжарить
2. Киноа отварить 15 минут
3. Овощи приготовить на пару
4. Смешать все компоненты
5. Добавить авокадо и масло

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Комплексное сочетание белков, сложных углеводов и полезных жиров обеспечивает все необходимые нутриенты для оптимального функционирования организма в течение недели.
"""
        benefits = """• ⚖️ Полноценный профиль нутриентов
• 🔥 Сбалансированная энергия
• 💪 Поддержка всех систем организма
• 🧠 Оптимальная умственная и физическая форма"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ СБАЛАНСИРОВАННЫЙ ОБЕД: КУРИЦА С КИНОА И ОВОЩАМИ",
            content, "balanced_nutrition_lunch", benefits
        )

    def generate_metabolic_flexibility_lunch(self):
        """Обед для метаболической гибкости"""
        content = """
🔄 <b>ОБЕД ДЛЯ МЕТАБОЛИЧЕСКОЙ ГИБКОСТИ: ЛОСОСЬ С БАТАТОМ</b>
КБЖУ: 550 ккал • Белки: 38г • Жиры: 28г • Углеводы: 45г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (Омега-3)
• Батат - 400 г (сложные углеводы)
• Брокколи - 300 г (клетчатка)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.
• Лимон - 1/2 шт

<b>Приготовление (35 минут):</b>
1. Батат запечь 25 минут
2. Лосось запечь 15 минут
3. Брокколи приготовить на пару
4. Смешать все компоненты
5. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание Омега-3 и сложных углеводов улучшает чувствительность к инсулину и способность организма эффективно переключаться между источниками энергии.
"""
        benefits = """• 🔄 Улучшение метаболической гибкости
• 🍬 Оптимизация чувствительности к инсулину
• ⚡ Эффективное использование энергии
• 💪 Подготовка к изменяющимся нагрузкам"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 ОБЕД ДЛЯ МЕТАБОЛИЧЕСКОЙ ГИБКОСТИ: ЛОСОСЬ С БАТАТОМ",
            content, "metabolic_flexibility_lunch", benefits
        )

    def generate_hormonal_support_lunch(self):
        """Обед для гормональной поддержки"""
        content = """
🎯 <b>ОБЕД ДЛЯ ГОРМОНАЛЬНОЙ ПОДДЕРЖКИ: ГОВЯДИНА С БРОККОЛИ</b>
КБЖУ: 480 ккал • Белки: 42г • Жиры: 25г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Говяжья вырезка - 500 г (цинк)
• Брокколи - 500 г (индол-3-карбинол)
• Грибы - 200 г (витамин D)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Говядину нарезать и обжарить
2. Брокколи приготовить на пару
3. Грибы и лук обжарить
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из говядины и индол-3-карбинол из брокколи поддерживают оптимальный метаболизм эстрогенов и функцию щитовидной железы.
"""
        benefits = """• 🎯 Поддержка метаболизма гормонов
• 🦋 Оптимизация функции щитовидной железы
• 💪 Баланс эстрогенов
• 🔥 Подготовка эндокринной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🎯 ОБЕД ДЛЯ ГОРМОНАЛЬНОЙ ПОДДЕРЖКИ: ГОВЯДИНА С БРОККОЛИ",
            content, "hormonal_support_lunch", benefits
        )

    def generate_stress_management_lunch(self):
        """Обед для управления стрессом"""
        content = """
😌 <b>ОБЕД ДЛЯ УПРАВЛЕНИЯ СТРЕССОМ: ИНДЕЙКА С ШПИНАТОМ</b>
КБЖУ: 450 ккал • Белки: 48г • Жиры: 18г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 500 г (триптофан)
• Шпинат - 400 г (магний)
• Киноа - 100 г (сложные углеводы)
• Грибы - 200 г (эрготионеин)
• Чеснок - 4 зубчика (аллицин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Индейку нарезать и обжарить
2. Киноа отварить 15 минут
3. Шпинат и грибы обжарить
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Магний из шпината регулирует активность NMDA-рецепторов и снижает выработку кортизола, подготавливая нервную систему к стрессовым ситуациям.
"""
        benefits = """• 😌 Снижение чувствительности к стрессу
• 🧘 Регуляция уровня кортизола
• 💪 Поддержка нервной системы
• 🌿 Успокаивающее действие"""
        
        return self.visual_manager.generate_attractive_post(
            "😌 ОБЕД ДЛЯ УПРАВЛЕНИЯ СТРЕССОМ: ИНДЕЙКА С ШПИНАТОМ",
            content, "stress_management_lunch", benefits
        )

    def generate_energy_optimization_lunch(self):
        """Обед для оптимизации энергетики"""
        content = """
⚡ <b>ОБЕД ДЛЯ ОПТИМИЗАЦИИ ЭНЕРГЕТИКИ: ПАСТА С ТУНЦОМ</b>
КБЖУ: 580 ккал • Белки: 42г • Жиры: 22г • Углеводы: 65г

<b>Ингредиенты (на 2 порции):</b>
• Паста цельнозерновая - 200 г (сложные углеводы)
• Тунец консервированный - 2 банки (коэнзим Q10)
• Брокколи - 300 г (хром)
• Помидоры - 3 шт (ликопин)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Пасту отварить al dente
2. Тунец размять вилкой
3. Овощи обжарить с чесноком
4. Смешать все компоненты

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Коэнзим Q10 из тунца поддерживает функцию митохондрий, улучшая производство АТФ и энергетическую эффективность клеток.
"""
        benefits = """• ⚡ Улучшение митохондриальной функции
• 🔋 Повышение производства АТФ
• 💪 Оптимизация энергетического метаболизма
• 🧠 Подготовка к энергозатратам"""
        
        return self.visual_manager.generate_attractive_post(
            "⚡ ОБЕД ДЛЯ ОПТИМИЗАЦИИ ЭНЕРГЕТИКИ: ПАСТА С ТУНЦОМ",
            content, "energy_optimization_lunch", benefits
        )

    def generate_digestive_health_lunch(self):
        """Обед для здоровья пищеварительной системы"""
        content = """
🌱 <b>ОБЕД ДЛЯ ЗДОРОВЬЯ ПИЩЕВАРЕНИЯ: ЧЕЧЕВИЧНЫЙ СУП</b>
КБЖУ: 420 ккал • Белки: 28г • Жиры: 12г • Углеводы: 58г

<b>Ингредиенты (на 2 порции):</b>
• Чечевица - 200 г (растворимая клетчатка)
• Морковь - 3 шт (бета-каротин)
• Сельдерей - 4 стебля (пребиотики)
• Лук - 2 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Куркума - 1 ч.л. (куркумин)
• Петрушка - 30 г (хлорофилл)

<b>Приготовление (35 минут):</b>
1. Овощи нарезать кубиками
2. Чечевицу промыть
3. Варить все вместе 30 минут
4. Добавить специи за 5 минут до готовности
5. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Растворимая клетчатка чечевицы служит пищей для полезных бактерий кишечника, укрепляя микробиом перед неделей возможных пищевых стрессов.
"""
        benefits = """• 🌱 Укрепление кишечного микробиома
• 🦠 Поддержка полезных бактерий
• 💪 Улучшение кишечного барьера
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🌱 ОБЕД ДЛЯ ЗДОРОВЬЯ ПИЩЕВАРЕНИЯ: ЧЕЧЕВИЧНЫЙ СУП",
            content, "digestive_health_lunch", benefits
        )

    def generate_cognitive_reserve_lunch(self):
        """Обед для когнитивного резерва"""
        content = """
🧠 <b>ОБЕД ДЛЯ КОГНИТИВНОГО РЕЗЕРВА: ЛОСОСЬ С ГРЕЦКИМИ ОРЕХАМИ</b>
КБЖУ: 520 ккал • Белки: 38г • Жиры: 35г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (ДГК)
• Грецкие орехи - 80 г (полифенолы)
• Шпинат - 300 г (лютеин)
• Киноа - 100 г (магний)
• Лимонный сок - 2 ст.л.
• Оливковое масло - 2 ст.л.

<b>Приготовление (25 минут):</b>
1. Лосось запечь 15 минут
2. Киноа отварить 15 минут
3. Шпинат обжарить 3 минуты
4. Смешать все с орехами
5. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ДГК из лосося и полифенолы грецких орехов усиливают нейропластичность и создают когнитивный резерв для обработки информации в течение недели.
"""
        benefits = """• 🧠 Усиление нейропластичности
• 💭 Создание когнитивного резерва
• 📚 Подготовка к умственным нагрузкам
• 🔥 Защита нейронов"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ОБЕД ДЛЯ КОГНИТИВНОГО РЕЗЕРВА: ЛОСОСЬ С ГРЕЦКИМИ ОРЕХАМИ",
            content, "cognitive_reserve_lunch", benefits
        )

    def generate_immune_preparation_lunch(self):
        """Обед для иммунной подготовки"""
        content = """
🛡️ <b>ОБЕД ДЛЯ ИММУННОЙ ПОДГОТОВКИ: КУРИЦА С ЧЕСНОКОМ</b>
КБЖУ: 480 ккал • Белки: 45г • Жиры: 22г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Куриное филе - 500 г (цистеин)
• Чеснок - 8 зубчиков (аллицин)
• Брокколи - 400 г (сульфорафан)
• Морковь - 3 шт (бета-каротин)
• Лук - 1 шт (кверцетин)
• Оливковое масло - 2 ст.л.
• Куркума - 1 ч.л.

<b>Приготовление (30 минут):</b>
1. Курицу нарезать и обжарить
2. Добавить чеснок и лук
3. Овощи приготовить на пару
4. Смешать с куркумой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Аллицин из чеснока активирует макрофаги и усиливает производство антител, подготавливая иммунную систему к возможным вызовам недели.
"""
        benefits = """• 🛡️ Активация иммунных клеток
• 🦠 Усиление производства антител
• 💪 Подготовка к иммунным вызовам
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ОБЕД ДЛЯ ИММУННОЙ ПОДГОТОВКИ: КУРИЦА С ЧЕСНОКОМ",
            content, "immune_preparation_lunch", benefits
        )

    def generate_detox_support_lunch(self):
        """Обед для поддержки детоксикации"""
        content = """
🍃 <b>ОБЕД ДЛЯ ПОДДЕРЖКИ ДЕТОКСИКАЦИИ: СВЕКЛА С ЯБЛОКАМИ</b>
КБЖУ: 350 ккал • Белки: 15г • Жиры: 10г • Углеводы: 55г

<b>Ингредиенты (на 2 порции):</b>
• Свекла - 4 шт (бетаин)
• Яблоки - 3 шт (пектин)
• Грецкие орехи - 40 г (аргинин)
• Лимонный сок - 3 ст.л. (витамин C)
• Имбирь - 2 см (гингерол)
• Оливковое масло - 2 ст.л.

<b>Приготовление (30 минут):</b>
1. Свеклу запечь 25 минут
2. Яблоки натереть на терке
3. Орехи измельчить
4. Смешать все ингредиенты
5. Заправить маслом и лимоном

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Бетаин из свеклы поддерживает функцию печени и усиливает выведение токсинов, очищая организм перед началом новой недели.
"""
        benefits = """• 🍃 Поддержка функции печени
• 🧪 Усиление выведения токсинов
• 💪 Очищение организма
• 🔥 Подготовка к метаболическим нагрузкам"""
        
        return self.visual_manager.generate_attractive_post(
            "🍃 ОБЕД ДЛЯ ПОДДЕРЖКИ ДЕТОКСИКАЦИИ: СВЕКЛА С ЯБЛОКАМИ",
            content, "detox_support_lunch", benefits
        )

    # 🍽️ УЖИНЫ (9 рецептов)
    def generate_weekly_recovery_dinner(self):
        """Ужин для восстановления перед неделей"""
        content = """
🔄 <b>УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: ТВОРОГ С ОРЕХАМИ</b>
КБЖУ: 320 ккал • Белки: 35г • Жиры: 16г • Углеводы: 12г

<b>Ингредиенты (на 2 порции):</b>
• Творог 5% - 400 г (казеин)
• Миндаль - 30 г (витамин E)
• Грецкие орехи - 30 г (Омега-3)
• Семена тыквы - 20 г (цинк)
• Корица - 1 ч.л. (антиоксиданты)
• Мед - 1 ч.л.

<b>Приготовление (5 минут):</b>
1. Творог разделить на порции
2. Добавить орехи и семена
3. Посыпать корицей
4. Полить медом

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Казеин из творога обеспечивает медленное высвобождение аминокислот в течение ночи, поддерживая восстановительные процессы и подготовку к неделе.
"""
        benefits = """• 🔄 Медленное высвобождение аминокислот
• 💪 Поддержка ночного восстановления
• 🛌 Подготовка к продуктивной неделе
• 🌙 Оптимизация процессов восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ДЛЯ ВОССТАНОВЛЕНИЯ: ТВОРОГ С ОРЕХАМИ",
            content, "weekly_recovery_dinner", benefits
        )

    def generate_sleep_optimization_dinner(self):
        """Ужин для оптимизации сна"""
        content = """
💤 <b>УЖИН ДЛЯ ОПТИМИЗАЦИИ СНА: ИНДЕЙКА С БАТАТОМ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 12г • Углеводы: 42г

<b>Ингредиенты (на 2 порции):</b>
• Филе индейки - 400 г (триптофан)
• Батат - 400 г (сложные углеводы)
• Шпинат - 200 г (магний)
• Грибы - 200 г (эрготионеин)
• Оливковое масло - 1 ст.л.
• Мускатный орех - 1/4 ч.л.

<b>Приготовление (30 минут):</b>
1. Батат запечь 25 минут
2. Индейку обжарить
3. Шпинат и грибы обжарить
4. Смешать все компоненты
5. Добавить мускатный орех

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Триптофан из индейки преобразуется в серотонин и мелатонин, обеспечивая качественный сон, необходимый для восстановления перед неделей.
"""
        benefits = """• 💤 Улучшение качества сна
• 🌙 Стимуляция производства мелатонина
• 🛌 Глубокое восстановление
• 😴 Подготовка к продуктивному пробуждению"""
        
        return self.visual_manager.generate_attractive_post(
            "💤 УЖИН ДЛЯ ОПТИМИЗАЦИИ СНА: ИНДЕЙКА С БАТАТОМ",
            content, "sleep_optimization_dinner", benefits
        )

    def generate_muscle_recovery_dinner(self):
        """Ужин для мышечного восстановления"""
        content = """
💪 <b>УЖИН ДЛЯ МЫШЕЧНОГО ВОССТАНОВЛЕНИЯ: РЫБА С ОВОЩАМИ</b>
КБЖУ: 350 ккал • Белки: 38г • Жиры: 15г • Углеводы: 22г

<b>Ингредиенты (на 2 порции):</b>
• Белая рыба - 400 г (легкий белок)
• Брокколи - 300 г (глюкозинолаты)
• Цветная капуста - 300 г (сульфорафан)
• Морковь - 2 шт (бета-каротин)
• Лимонный сок - 2 ст.л.
• Укроп - 20 г (эфирные масла)

<b>Приготовление (20 минут):</b>
1. Рыбу и овощи приготовить на пару
2. Полить лимонным соком
3. Посыпать укропом
4. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Легкий белок рыбы обеспечивает аминокислоты для восстановления мышечных волокон без нагрузки на пищеварительную систему перед сном.
"""
        benefits = """• 💪 Поддержка мышечного восстановления
• 🏃 Обеспечение аминокислотами
• 🔄 Легкое усвоение
• 🌙 Оптимизация ночного восстановления"""
        
        return self.visual_manager.generate_attractive_post(
            "💪 УЖИН ДЛЯ МЫШЕЧНОГО ВОССТАНОВЛЕНИЯ: РЫБА С ОВОЩАМИ",
            content, "muscle_recovery_dinner", benefits
        )

    def generate_nervous_system_dinner(self):
        """Ужин для поддержки нервной системы"""
        content = """
🧘 <b>УЖИН ДЛЯ ПОДДЕРЖКИ НЕРВНОЙ СИСТЕМЫ: ТЫКВЕННОЕ ПЮРЕ</b>
КБЖУ: 280 ккал • Белки: 18г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Тыква - 800 г (бета-каротин)
• Картофель - 2 шт (калий)
• Имбирь - 2 см (гингерол)
• Мускатный орех - 1/4 ч.л. (миристицин)
• Кокосовые сливки - 100 мл (МСТ)
• Корица - 1 ч.л.

<b>Приготовление (30 минут):</b>
1. Овощи нарезать кубиками
2. Запечь 25 минут до мягкости
3. Размять в пюре
4. Добавить специи и кокосовые сливки

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Калий из картофеля регулирует электрическую активность нейронов, а миристицин из мускатного ореха обладает мягким седативным действием.
"""
        benefits = """• 🧘 Регуляция нервной активности
• 😌 Успокаивающее действие
• 💤 Подготовка к качественному сну
• 🌙 Поддержка нервной системы"""
        
        return self.visual_manager.generate_attractive_post(
            "🧘 УЖИН ДЛЯ ПОДДЕРЖКИ НЕРВНОЙ СИСТЕМЫ: ТЫКВЕННОЕ ПЮРЕ",
            content, "nervous_system_dinner", benefits
        )

    def generate_hormonal_balance_dinner(self):
        """Ужин для гормонального баланса"""
        content = """
⚖️ <b>УЖИН ДЛЯ ГОРМОНАЛЬНОГО БАЛАНСА: КАПУСТА С ЧЕСНОКОМ</b>
КБЖУ: 220 ккал • Белки: 15г • Жиры: 8г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Капуста белокочанная - 600 г (индол-3-карбинол)
• Чеснок - 6 зубчиков (аллицин)
• Лимонный сок - 2 ст.л. (витамин C)
• Семена укропа - 1 ч.л.
• Оливковое масло - 1 ст.л.
• Куркума - 1 ч.л.

<b>Приготовление (25 минут):</b>
1. Капусту нашинковать
2. Обжарить с чесноком 15 минут
3. Добавить специи
4. Заправить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Индол-3-карбинол из капусты поддерживает оптимальный метаболизм эстрогенов, способствуя гормональному балансу во время ночного восстановления.
"""
        benefits = """• ⚖️ Поддержка метаболизма гормонов
• 🌙 Ночная регуляция гормонального фона
• 💪 Баланс эстрогенов
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ УЖИН ДЛЯ ГОРМОНАЛЬНОГО БАЛАНСА: КАПУСТА С ЧЕСНОКОМ",
            content, "hormonal_balance_dinner", benefits
        )

    def generate_metabolic_reset_dinner(self):
        """Ужин для метаболического перезапуска"""
        content = """
🔄 <b>УЖИН ДЛЯ МЕТАБОЛИЧЕСКОГО ПЕРЕЗАПУСКА: ОВОЩИ НА ПАРУ</b>
КБЖУ: 180 ккал • Белки: 12г • Жиры: 4г • Углеводы: 30г

<b>Ингредиенты (на 2 порции):</b>
• Брокколи - 300 г (глюкозинолаты)
• Цветная капуста - 300 г (сульфорафан)
• Морковь - 3 шт (бета-каротин)
• Цукини - 1 шт (кремний)
• Лимонный сок - 2 ст.л.
• Имбирь - 2 см (гингерол)

<b>Приготовление (20 минут):</b>
1. Овощи нарезать
2. Приготовить на пару 15 минут
3. Полить лимонным соком
4. Посыпать тертым имбирем

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Легкий ужин из овощей на пару дает отдых пищеварительной системе, позволяя метаболизму перезагрузиться перед началом новой недели.
"""
        benefits = """• 🔄 Отдых для пищеварительной системы
• 🍃 Метаболический перезапуск
• 💫 Очищение организма
• 🌙 Подготовка к эффективному метаболизму"""
        
        return self.visual_manager.generate_attractive_post(
            "🔄 УЖИН ДЛЯ МЕТАБОЛИЧЕСКОГО ПЕРЕЗАПУСКА: ОВОЩИ НА ПАРУ",
            content, "metabolic_reset_dinner", benefits
        )

    def generate_immune_support_dinner(self):
        """Ужин для поддержки иммунитета"""
        content = """
🛡️ <b>УЖИН ДЛЯ ПОДДЕРЖКИ ИММУНИТЕТА: ГРИБНОЙ СУП</b>
КБЖУ: 280 ккал • Белки: 22г • Жиры: 10г • Углеводы: 32г

<b>Ингредиенты (на 2 порции):</b>
• Грибы шиитаке - 300 г (лентинан)
• Грибы шампиньоны - 200 г (эрготионеин)
• Лук - 1 шт (кверцетин)
• Чеснок - 4 зубчика (аллицин)
• Сельдерей - 3 стебля (пребиотики)
• Петрушка - 30 г (хлорофилл)

<b>Приготовление (30 минут):</b>
1. Грибы и овощи нарезать
2. Варить 25 минут
3. Добавить чеснок за 5 минут до готовности
4. Посыпать петрушкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Лентинан из грибов шиитаке активирует макрофаги и натуральные киллеры, усиливая иммунный надзор во время ночного восстановления.
"""
        benefits = """• 🛡️ Активация иммунных клеток
• 🌙 Усиление иммунного надзора ночью
• 💪 Подготовка к иммунным вызовам
• 🔥 Противовоспалительное действие"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ УЖИН ДЛЯ ПОДДЕРЖКИ ИММУНИТЕТА: ГРИБНОЙ СУП",
            content, "immune_support_dinner", benefits
        )

    def generate_cognitive_recovery_dinner(self):
        """Ужин для когнитивного восстановления"""
        content = """
🧠 <b>УЖИН ДЛЯ КОГНИТИВНОГО ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ШПИНАТОМ</b>
КБЖУ: 380 ккал • Белки: 35г • Жиры: 24г • Углеводы: 8г

<b>Ингредиенты (на 2 порции):</b>
• Лосось - 400 г (ДГК)
• Шпинат - 400 г (лютеин)
• Грецкие орехи - 30 г (полифенолы)
• Чеснок - 3 зубчика (аллицин)
• Оливковое масло - 1 ст.л.
• Лимон - 1/2 шт

<b>Приготовление (20 минут):</b>
1. Лосось запечь 15 минут
2. Шпинат обжарить с чесноком
3. Измельчить орехи
4. Смешать все компоненты
5. Полить лимонным соком

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
ДГК из лосося поддерживает восстановление синаптических связей и консолидацию памяти во время ночного сна.
"""
        benefits = """• 🧠 Восстановление синаптических связей
• 📚 Консолидация памяти
• 🌙 Ночное когнитивное восстановление
• 💭 Подготовка к умственной работе"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 УЖИН ДЛЯ КОГНИТИВНОГО ВОССТАНОВЛЕНИЯ: ЛОСОСЬ С ШПИНАТОМ",
            content, "cognitive_recovery_dinner", benefits
        )

    def generate_detox_final_dinner(self):
        """Финальный ужин для детоксикации"""
        content = """
🍃 <b>ФИНАЛЬНЫЙ УЖИН ДЛЯ ДЕТОКСИКАЦИИ: ОГУРЕЧНЫЙ САЛАТ</b>
КБЖУ: 180 ккал • Белки: 15г • Жиры: 8г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Огурцы - 3 шт (вода)
• Творог - 200 г (белок)
• Укроп - 30 г (эфирные масла)
• Лимонный сок - 2 ст.л. (витамин C)
• Семена подсолнечника - 20 г (витамин E)
• Мята - 10 г (ментол)

<b>Приготовление (10 минут):</b>
1. Огурцы нарезать кубиками
2. Творог смешать с укропом
3. Соединить все ингредиенты
4. Заправить лимонным соком
5. Украсить мятой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Огурцы на 95% состоят из структурированной воды, которая способствует гидратации и выведению токсинов, завершая процесс очищения перед неделей.
"""
        benefits = """• 🍃 Финальное очищение организма
• 💧 Глубокая гидратация
• 🧪 Выведение остаточных токсинов
• 🌙 Подготовка к чистой неделе"""
        
        return self.visual_manager.generate_attractive_post(
            "🍃 ФИНАЛЬНЫЙ УЖИН ДЛЯ ДЕТОКСИКАЦИИ: ОГУРЕЧНЫЙ САЛАТ",
            content, "detox_final_dinner", benefits
        )

    # 🍰 ДЕСЕРТЫ (8 рецептов)
    def generate_weekly_prep_dessert(self):
        """Десерт для подготовки к неделе"""
        content = """
📅 <b>ДЕСЕРТ ДЛЯ ПОДГОТОВКИ К НЕДЕЛЕ: ФИНИКОВЫЕ ТРЮФЕЛИ</b>
КБЖУ: 240 ккал • Белки: 8г • Жиры: 10г • Углеводы: 35г

<b>Ингредиенты (на 8 трюфелей):</b>
• Финики - 200 г (натуральные сахара)
• Овсяные хлопья - 80 г (сложные углеводы)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Арахисовая паста - 2 ст.л. (белок)
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Обвалять в кокосовой стружке
5. Охладить 2 часа

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Сочетание натуральных сахаров и сложных углеводов создает энергетический резерв, который будет постепенно высвобождаться в течение недели.
"""
        benefits = """• 📅 Создание энергетического резерва
• ⚡ Постепенное высвобождение энергии
• 💪 Подготовка к нагрузкам
• 🍫 Натуральная польза"""
        
        return self.visual_manager.generate_attractive_post(
            "📅 ДЕСЕРТ ДЛЯ ПОДГОТОВКИ К НЕДЕЛЕ: ФИНИКОВЫЕ ТРЮФЕЛИ",
            content, "weekly_prep_dessert", benefits
        )

    def generate_sleep_enhancement_dessert(self):
        """Десерт для улучшения сна"""
        content = """
😴 <b>ДЕСЕРТ ДЛЯ УЛУЧШЕНИЯ СНА: БАНАНОВЫЙ ПУДИНГ</b>
КБЖУ: 280 ккал • Белки: 15г • Жиры: 12г • Углеводы: 35г

<b>Ингредиенты (на 2 порции):</b>
• Бананы - 2 шт (мелатонин)
• Семена чиа - 4 ст.л. (Омега-3)
• Миндальное молоко - 300 мл
• Миндаль - 20 г (магний)
• Корица - 1 ч.л.
• Мед - 1 ст.л.

<b>Приготовление (5 минут + настаивание):</b>
1. Бананы размять вилкой
2. Смешать с семенами чиа и молоком
3. Добавить корицу и мед
4. Настаивать 4 часа или overnight
5. Посыпать миндалем перед подачей

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Мелатонин из бананов и магний из миндаля синергетически улучшают качество сна, обеспечивая глубокое восстановление перед неделей.
"""
        benefits = """• 😴 Улучшение качества сна
• 🌙 Стимуляция производства мелатонина
• 🛌 Глубокое восстановление
• 💤 Подготовка к продуктивному пробуждению"""
        
        return self.visual_manager.generate_attractive_post(
            "😴 ДЕСЕРТ ДЛЯ УЛУЧШЕНИЯ СНА: БАНАНОВЫЙ ПУДИНГ",
            content, "sleep_enhancement_dessert", benefits
        )

    def generate_stress_relief_dessert(self):
        """Десерт для снятия стресса"""
        content = """
🌿 <b>ДЕСЕРТ ДЛЯ СНЯТИЯ СТРЕССА: ЛАВАНДОВЫЙ МЕД</b>
КБЖУ: 120 ккал • Белки: 2г • Жиры: 0г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Мед - 4 ст.л. (прополис)
• Цветки лаванды - 1 ст.л. (линалоол)
• Лимонный сок - 1 ст.л.
• Теплая вода - 400 мл

<b>Приготовление (5 минут):</b>
1. Мед смешать с лавандой
2. Добавить лимонный сок
3. Залить теплой водой
4. Настаивать 5 минут
5. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Линалоол из лаванды активирует парасимпатическую нервную систему, снижая уровень кортизола и подготавливая организм к спокойной неделе.
"""
        benefits = """• 🌿 Активация парасимпатической системы
• 🧘 Снижение уровня кортизола
• 😌 Успокаивающее действие
• 💫 Подготовка к спокойной неделе"""
        
        return self.visual_manager.generate_attractive_post(
            "🌿 ДЕСЕРТ ДЛЯ СНЯТИЯ СТРЕССА: ЛАВАНДОВЫЙ МЕД",
            content, "stress_relief_dessert", benefits
        )

    def generate_metabolic_boost_dessert(self):
        """Десерт для ускорения метаболизма"""
        content = """
🔥 <b>ДЕСЕРТ ДЛЯ УСКОРЕНИЯ МЕТАБОЛИЗМА: ИМБИРНЫЕ КОНФЕТЫ</b>
КБЖУ: 180 ккал • Белки: 6г • Жиры: 8г • Углеводы: 25г

<b>Ингредиенты (на 8 конфет):</b>
• Финики - 150 г (натуральные сахара)
• Имбирь - 3 см (гингерол)
• Кокосовое масло - 2 ст.л. (МСТ)
• Корица - 1 ч.л. (циннамальдегид)
• Лимонный сок - 1 ст.л.
• Кокосовая стружка - для обваливания

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Имбирь натереть на терке
3. Смешать все ингредиенты
4. Сформировать конфеты
5. Обвалять в кокосовой стружке

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Гингерол из имбиря активирует термогенез и увеличивает расход энергии, подготавливая метаболизм к активной неделе.
"""
        benefits = """• 🔥 Активация термогенеза
• ⚡ Увеличение расхода энергии
• 💪 Подготовка метаболизма
• 🌿 Натуральные стимуляторы"""
        
        return self.visual_manager.generate_attractive_post(
            "🔥 ДЕСЕРТ ДЛЯ УСКОРЕНИЯ МЕТАБОЛИЗМА: ИМБИРНЫЕ КОНФЕТЫ",
            content, "metabolic_boost_dessert", benefits
        )

    def generate_immune_final_dessert(self):
        """Финальный десерт для иммунитета"""
        content = """
🛡️ <b>ФИНАЛЬНЫЙ ДЕСЕРТ ДЛЯ ИММУНИТЕТА: ЯГОДНОЕ ПЮРЕ</b>
КБЖУ: 160 ккал • Белки: 8г • Жиры: 4г • Углеводы: 28г

<b>Ингредиенты (на 2 порции):</b>
• Черника - 200 г (антоцианы)
• Малина - 150 г (эллаговая кислота)
• Гранат - 1 шт (пуникалагины)
• Лимонный сок - 1 ст.л. (витамин C)
• Мята - для украшения

<b>Приготовление (10 минут):</b>
1. Ягоды и гранат очистить
2. Взбить в блендере в пюре
3. Добавить лимонный сок
4. Украсить мятой
5. Охладить 30 минут

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Антоцианы и пуникалагины защищают иммунные клетки и усиливают их функцию, создавая иммунный резерв на предстоящую неделю.
"""
        benefits = """• 🛡️ Защита иммунных клеток
• 💪 Создание иммунного резерва
• 🌿 Антиоксидантная защита
• 🍓 Подготовка к иммунным вызовам"""
        
        return self.visual_manager.generate_attractive_post(
            "🛡️ ФИНАЛЬНЫЙ ДЕСЕРТ ДЛЯ ИММУНИТЕТА: ЯГОДНОЕ ПЮРЕ",
            content, "immune_final_dessert", benefits
        )

    def generate_cognitive_prep_dessert(self):
        """Десерт для когнитивной подготовки"""
        content = """
🧠 <b>ДЕСЕРТ ДЛЯ КОГНИТИВНОЙ ПОДГОТОВКИ: ШОКОЛАДНЫЕ ШАРИКИ</b>
КБЖУ: 280 ккал • Белки: 12г • Жиры: 18г • Углеводы: 25г

<b>Ингредиенты (на 8 шариков):</b>
• Финики - 150 г (натуральные сахара)
• Грецкие орехи - 80 г (Омега-3)
• Какао-порошок - 3 ст.л. (флавоноиды)
• Кокосовое масло - 2 ст.л. (МСТ)
• Семена чиа - 2 ст.л. (альфа-линоленовая кислота)

<b>Приготовление (15 минут):</b>
1. Финики замочить на 30 минут
2. Все ингредиенты измельчить в блендере
3. Сформировать шарики
4. Охладить 1 час

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Флавоноиды какао улучшают мозговой кровоток и нейропластичность, подготавливая мозг к интенсивной умственной работе на неделе.
"""
        benefits = """• 🧠 Улучшение мозгового кровотока
• 💭 Усиление нейропластичности
• 📚 Подготовка к умственным нагрузкам
• 🍫 Когнитивная поддержка"""
        
        return self.visual_manager.generate_attractive_post(
            "🧠 ДЕСЕРТ ДЛЯ КОГНИТИВНОЙ ПОДГОТОВКИ: ШОКОЛАДНЫЕ ШАРИКИ",
            content, "cognitive_prep_dessert", benefits
        )

    def generate_hormonal_balance_dessert(self):
        """Десерт для гормонального баланса"""
        content = """
⚖️ <b>ДЕСЕРТ ДЛЯ ГОРМОНАЛЬНОГО БАЛАНСА: ТЫКВЕННЫЕ СЕМЕЧКИ В МЕДЕ</b>
КБЖУ: 220 ккал • Белки: 10г • Жиры: 14г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Тыквенные семечки - 60 г (цинк)
• Мед - 3 ст.л. (прополис)
• Корица - 1 ч.л. (регулятор инсулина)
• Кокосовая стружка - 2 ст.л.
• Ванильный экстракт - 1/2 ч.л.

<b>Приготовление (10 минут):</b>
1. Семечки обжарить на сухой сковороде
2. Смешать с медом и специями
3. Сформировать небольшие порции
4. Посыпать кокосовой стружкой

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Цинк из тыквенных семечек поддерживает функцию щитовидной железы и производство половых гормонов, обеспечивая гормональный баланс.
"""
        benefits = """• ⚖️ Поддержка гормонального баланса
• 🦋 Оптимизация функции щитовидной железы
• 💪 Синтез важных гормонов
• 🌿 Натуральная регуляция"""
        
        return self.visual_manager.generate_attractive_post(
            "⚖️ ДЕСЕРТ ДЛЯ ГОРМОНАЛЬНОГО БАЛАНСА: ТЫКВЕННЫЕ СЕМЕЧКИ В МЕДЕ",
            content, "hormonal_balance_dessert", benefits
        )

    def generate_final_recovery_dessert(self):
        """Финальный десерт для восстановления"""
        content = """
🌟 <b>ФИНАЛЬНЫЙ ДЕСЕРТ ДЛЯ ВОССТАНОВЛЕНИЯ: ЗОЛОТОЕ МОЛОКО</b>
КБЖУ: 180 ккал • Белки: 8г • Жиры: 10г • Углеводы: 18г

<b>Ингредиенты (на 2 порции):</b>
• Кокосовое молоко - 400 мл (МСТ)
• Куркума - 2 ч.л. (куркумин)
• Корица - 1 ч.л. (антиоксиданты)
• Имбирь - 2 см (гингерол)
• Черный перец - 1/4 ч.л. (пиперин)
• Мед - 1 ст.л.

<b>Приготовление (10 минут):</b>
1. Молоко подогреть
2. Добавить все специи
3. Варить 5 минут на медленном огне
4. Добавить мед
5. Подавать теплым

🔬 <b>НАУЧНЫЙ ПОДХОД:</b>
Куркумин и гингерол синергетически снижают воспаление и поддерживают восстановительные процессы, завершая подготовку организма к неделе.
"""
        benefits = """• 🌟 Комплексное восстановление
• 🔥 Снижение системного воспаления
• 💪 Поддержка восстановительных процессов
• 🌙 Идеальное завершение дня"""
        
        return self.visual_manager.generate_attractive_post(
            "🌟 ФИНАЛЬНЫЙ ДЕСЕРТ ДЛЯ ВОССТАНОВЛЕНИЯ: ЗОЛОТОЕ МОЛОКО",
            content, "final_recovery_dessert", benefits
        )

# Создание экземпляра генератора
sunday_generator = SundayContentGenerator()
class ContentScheduler:
    """Планировщик контента с автоматической ротацией"""
    
    def __init__(self):
        self.telegram_manager = TelegramManager()
        self.rotation_system = AdvancedRotationSystem()
        self.daily_generators = {
            0: monday_generator,      # Понедельник
            1: tuesday_generator,     # Вторник  
            2: wednesday_generator,   # Среда
            3: thursday_generator,    # Четверг
            4: friday_generator,      # Пятница
            5: saturday_generator,    # Суббота
            6: sunday_generator       # Воскресенье
        }
    
    def get_current_generator(self):
        """Получение генератора для текущего дня"""
        weekday = TimeManager.get_kemerovo_weekday()
        return self.daily_generators.get(weekday, monday_generator)
    
    def generate_and_send_content(self, content_type):
        """Генерация и отправка контента"""
        try:
            generator = self.get_current_generator()
            method_name = self.rotation_system.get_priority_recipe(
                content_type, TimeManager.get_kemerovo_weekday()
            )
            
            if hasattr(generator, method_name):
                content = getattr(generator, method_name)()
                success = self.telegram_manager.send_message(
                    content, content_type, method_name
                )
                
                if success:
                    logger.info(f"✅ Успешно отправлен {content_type} в {TimeManager.get_kemerovo_time()}")
                    return True
                else:
                    logger.error(f"❌ Ошибка отправки {content_type}")
                    return False
            else:
                logger.error(f"❌ Метод {method_name} не найден")
                return False
                
        except Exception as e:
            logger.error(f"❌ Исключение при отправке {content_type}: {e}")
            return False
    
    def scheduled_breakfast(self):
        """Запланированная отправка завтрака"""
        return self.generate_and_send_content('breakfast')
    
    def scheduled_lunch(self):
        """Запланированная отправка обеда"""
        return self.generate_and_send_content('lunch')
    
    def scheduled_dinner(self):
        """Запланированная отправка ужина"""
        return self.generate_and_send_content('dinner')
    
    def scheduled_dessert(self):
        """Запланированная отправка десерта"""
        return self.generate_and_send_content('dessert')
    
    def scheduled_advice(self):
        """Запланированная отправка совета"""
        return self.generate_and_send_content('advice')
    
    def setup_schedule(self):
        """Настройка расписания отправки"""
        try:
            # Очистка существующего расписания
            schedule.clear()
            
            # Получение расписания из конфигурации
            schedule_config = Config.SCHEDULE_CONFIG
            
            for time_str, content_type in schedule_config['weekdays'].items():
                server_time = TimeManager.kemerovo_to_server(time_str)
                schedule.every().monday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                schedule.every().tuesday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                schedule.every().wednesday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                schedule.every().thursday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                schedule.every().friday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                logger.info(f"📅 Настроено расписание будни: {time_str} -> {content_type} (сервер: {server_time})")
            
            for time_str, content_type in schedule_config['weekends'].items():
                server_time = TimeManager.kemerovo_to_server(time_str)
                schedule.every().saturday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                schedule.every().sunday.at(server_time).do(
                    getattr(self, f'scheduled_{content_type}')
                )
                logger.info(f"📅 Настроено расписание выходные: {time_str} -> {content_type} (сервер: {server_time})")
            
            # Ежедневное обслуживание в 03:00 по Кемерово
            maintenance_time = TimeManager.kemerovo_to_server('03:00')
            schedule.every().day.at(maintenance_time).do(self.daily_maintenance)
            
            logger.info("✅ Расписание успешно настроено")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка настройки расписания: {e}")
            return False
    
    def daily_maintenance(self):
        """Ежедневное обслуживание"""
        try:
            logger.info("🔧 Запуск ежедневного обслуживания")
            
            # Очистка старых записей
            self.telegram_manager.cleanup_old_messages(30)
            
            # Обновление keep-alive
            service_monitor.update_keep_alive()
            
            # Проверка соединения с Telegram
            telegram_status = self.telegram_manager.test_connection()
            
            logger.info(f"✅ Обслуживание завершено. Telegram: {'✅' if telegram_status else '❌'}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обслуживания: {e}")

# Инициализация планировщика
content_scheduler = ContentScheduler()

# HTML шаблон для дашборда
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Recipe Bot Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
        }
        
        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .header p {
            font-size: 1.1rem;
            opacity: 0.9;
        }
        
        .dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        
        @media (max-width: 768px) {
            .dashboard {
                grid-template-columns: 1fr;
            }
        }
        
        .card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
        }
        
        .card h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.4rem;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #eee;
        }
        
        .status-item:last-child {
            border-bottom: none;
        }
        
        .status-label {
            font-weight: 600;
            color: #555;
        }
        
        .status-value {
            font-weight: 700;
        }
        
        .status-good {
            color: #27ae60;
        }
        
        .status-warning {
            color: #f39c12;
        }
        
        .status-error {
            color: #e74c3c;
        }
        
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 25px;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
            text-decoration: none;
            display: inline-block;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
        }
        
        .btn:active {
            transform: translateY(0);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #27ae60 0%, #2ecc71 100%);
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #f39c12 0%, #f1c40f 100%);
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
        }
        
        .logs {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            max-height: 400px;
            overflow-y: auto;
        }
        
        .log-entry {
            padding: 8px 0;
            border-bottom: 1px solid #eee;
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
        }
        
        .log-entry:last-child {
            border-bottom: none;
        }
        
        .log-time {
            color: #666;
            margin-right: 10px;
        }
        
        .log-info {
            color: #27ae60;
        }
        
        .log-warning {
            color: #f39c12;
        }
        
        .log-error {
            color: #e74c3c;
        }
        
        .rotation-status {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .rotation-item {
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }
        
        .rotation-percent {
            font-size: 1.5rem;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .percent-good {
            color: #27ae60;
        }
        
        .percent-warning {
            color: #f39c12;
        }
        
        .percent-danger {
            color: #e74c3c;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🍳 Recipe Bot Dashboard</h1>
            <p>Панель управления кулинарным ботом</p>
        </div>
        
        <div class="dashboard">
            <div class="card">
                <h2>📊 Статус системы</h2>
                <div id="status-content">
                    <div class="status-item">
                        <span class="status-label">Статус бота:</span>
                        <span class="status-value status-good" id="bot-status">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Telegram соединение:</span>
                        <span class="status-value" id="telegram-status">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Подписчики:</span>
                        <span class="status-value" id="subscribers-count">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Время сервера:</span>
                        <span class="status-value" id="server-time">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Время Кемерово:</span>
                        <span class="status-value" id="kemerovo-time">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Аптайм:</span>
                        <span class="status-value" id="uptime">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Отправлено сообщений:</span>
                        <span class="status-value" id="sent-count">Загрузка...</span>
                    </div>
                    <div class="status-item">
                        <span class="status-label">Ошибки:</span>
                        <span class="status-value" id="error-count">Загрузка...</span>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h2>🔄 Статус ротации</h2>
                <div id="rotation-content">
                    <div class="rotation-status" id="rotation-stats">
                        <!-- Динамически заполняется JavaScript -->
                    </div>
                </div>
            </div>
        </div>
        
        <div class="controls">
            <button class="btn btn-success" onclick="sendManualPost('breakfast')">
                🍳 Отправить завтрак
            </button>
            <button class="btn btn-success" onclick="sendManualPost('lunch')">
                🍲 Отправить обед
            </button>
            <button class="btn btn-success" onclick="sendManualPost('dinner')">
                🍽️ Отправить ужин
            </button>
            <button class="btn btn-success" onclick="sendManualPost('dessert')">
                🍰 Отправить десерт
            </button>
            <button class="btn btn-warning" onclick="sendManualPost('advice')">
                💡 Отправить совет
            </button>
            <button class="btn" onclick="refreshAll()">
                🔄 Обновить все
            </button>
        </div>
        
        <div class="card">
            <h2>📋 Быстрая отправка</h2>
            <div class="controls">
                <button class="btn btn-success" onclick="sendDailyMenu()">
                    📅 Отправить дневное меню
                </button>
                <button class="btn btn-warning" onclick="testConnection()">
                    🔌 Тест соединения
                </button>
                <button class="btn btn-danger" onclick="emergencyStop()">
                    🚫 Аварийная остановка
                </button>
            </div>
        </div>
        
        <div class="logs">
            <h2>📝 Последние логи</h2>
            <div id="logs-content">
                <!-- Динамически заполняется JavaScript -->
            </div>
        </div>
    </div>

    <script>
        let authToken = '''' + Config.ADMIN_TOKEN + '''';
        
        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${days}д ${hours}ч ${minutes}м`;
        }
        
        function updateStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('bot-status').textContent = data.status;
                    document.getElementById('telegram-status').textContent = 
                        data.telegram_connected ? '✅ Подключено' : '❌ Ошибка';
                    document.getElementById('telegram-status').className = 
                        data.telegram_connected ? 'status-value status-good' : 'status-value status-error';
                    document.getElementById('subscribers-count').textContent = data.subscribers_count;
                    document.getElementById('server-time').textContent = data.current_times.server_time;
                    document.getElementById('kemerovo-time').textContent = data.current_times.kemerovo_time;
                    document.getElementById('uptime').textContent = formatUptime(data.uptime_seconds);
                    document.getElementById('sent-count').textContent = data.request_count;
                    document.getElementById('error-count').textContent = data.error_count;
                })
                .catch(error => {
                    console.error('Ошибка обновления статуса:', error);
                });
        }
        
        function updateRotation() {
            fetch('/api/rotation-status')
                .then(response => response.json())
                .then(data => {
                    const rotationStats = document.getElementById('rotation-stats');
                    rotationStats.innerHTML = '';
                    
                    for (const [contentType, stats] of Object.entries(data)) {
                        const rotationItem = document.createElement('div');
                        rotationItem.className = 'rotation-item';
                        
                        const percentClass = stats.availability_percent > 70 ? 'percent-good' : 
                                           stats.availability_percent > 30 ? 'percent-warning' : 'percent-danger';
                        
                        rotationItem.innerHTML = `
                            <div style="font-weight: bold; margin-bottom: 5px;">${getContentTypeName(contentType)}</div>
                            <div class="rotation-percent ${percentClass}">${stats.availability_percent}%</div>
                            <div style="font-size: 0.8rem; color: #666;">
                                ${stats.available}/${stats.total} доступно
                            </div>
                        `;
                        
                        rotationStats.appendChild(rotationItem);
                    }
                })
                .catch(error => {
                    console.error('Ошибка обновления ротации:', error);
                });
        }
        
        function getContentTypeName(type) {
            const names = {
                'breakfast': '🍳 Завтраки',
                'lunch': '🍲 Обеды', 
                'dinner': '🍽️ Ужины',
                'dessert': '🍰 Десерты',
                'advice': '💡 Советы'
            };
            return names[type] || type;
        }
        
        function updateLogs() {
            fetch('/api/logs?limit=10')
                .then(response => response.json())
                .then(data => {
                    const logsContent = document.getElementById('logs-content');
                    logsContent.innerHTML = '';
                    
                    data.logs.forEach(log => {
                        const logEntry = document.createElement('div');
                        logEntry.className = 'log-entry';
                        
                        let logClass = 'log-info';
                        if (log.includes('❌') || log.includes('ERROR')) logClass = 'log-error';
                        else if (log.includes('⚠️') || log.includes('WARNING')) logClass = 'log-warning';
                        
                        // Извлекаем время и сообщение
                        const parts = log.split(' - ');
                        const time = parts[0] || '';
                        const message = parts.slice(1).join(' - ') || log;
                        
                        logEntry.innerHTML = `
                            <span class="log-time">${time}</span>
                            <span class="${logClass}">${message}</span>
                        `;
                        
                        logsContent.appendChild(logEntry);
                    });
                })
                .catch(error => {
                    console.error('Ошибка обновления логов:', error);
                });
        }
        
        function sendManualPost(contentType) {
            if (!confirm(`Отправить ${getContentTypeName(contentType)}?`)) return;
            
            fetch('/api/manual-post', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + authToken
                },
                body: JSON.stringify({
                    post_type: contentType
                })
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'Успешно отправлено!');
                updateLogs();
            })
            .catch(error => {
                alert('Ошибка отправки: ' + error);
            });
        }
        
        function sendDailyMenu() {
            if (!confirm('Отправить полное дневное меню?')) return;
            
            const types = ['breakfast', 'lunch', 'dinner', 'dessert'];
            let sentCount = 0;
            
            types.forEach(type => {
                fetch('/api/manual-post', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + authToken
                    },
                    body: JSON.stringify({
                        post_type: type
                    })
                })
                .then(response => response.json())
                .then(data => {
                    sentCount++;
                    if (sentCount === types.length) {
                        alert('Полное меню отправлено!');
                        updateLogs();
                    }
                })
                .catch(error => {
                    console.error(`Ошибка отправки ${type}:`, error);
                });
            });
        }
        
        function testConnection() {
            fetch('/api/test-telegram', {
                headers: {
                    'Authorization': 'Bearer ' + authToken
                }
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'Тест завершен');
                updateStatus();
            })
            .catch(error => {
                alert('Ошибка теста: ' + error);
            });
        }
        
        function emergencyStop() {
            if (!confirm('ВНИМАНИЕ! Это остановит все запланированные отправки. Продолжить?')) return;
            
            fetch('/api/emergency-stop', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + authToken
                }
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'Бот остановлен');
                updateStatus();
            })
            .catch(error => {
                alert('Ошибка остановки: ' + error);
            });
        }
        
        function refreshAll() {
            updateStatus();
            updateRotation();
            updateLogs();
        }
        
        // Автоматическое обновление каждые 30 секунд
        setInterval(refreshAll, 30000);
        
        // Первоначальная загрузка
        document.addEventListener('DOMContentLoaded', function() {
            refreshAll();
        });
    </script>
</body>
</html>
'''

# Flask роуты
@app.route('/')
def dashboard():
    """Главная страница дашборда"""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/status')
def api_status():
    """API статуса системы"""
    telegram_connected = content_scheduler.telegram_manager.test_connection()
    subscribers_count = content_scheduler.telegram_manager.get_subscribers_count()
    
    status_data = service_monitor.get_status()
    status_data.update({
        'telegram_connected': telegram_connected,
        'subscribers_count': subscribers_count,
        'current_times': TimeManager.get_current_times()
    })
    
    return jsonify(status_data)

@app.route('/api/rotation-status')
def api_rotation_status():
    """API статуса ротации"""
    rotation_status = content_scheduler.rotation_system.check_rotation_status()
    return jsonify(rotation_status)

@app.route('/api/logs')
def api_logs():
    """API получения логов"""
    try:
        with open('bot.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        limit = request.args.get('limit', 50, type=int)
        recent_logs = lines[-limit:] if len(lines) > limit else lines
        
        return jsonify({
            'logs': [line.strip() for line in recent_logs],
            'total_count': len(lines)
        })
    except Exception as e:
        return jsonify({'error': str(e), 'logs': []})

@app.route('/api/manual-post', methods=['POST'])
@SecurityManager.require_auth
def api_manual_post():
    """API ручной отправки поста"""
    try:
        data = request.get_json()
        post_type = data.get('post_type')
        
        if not post_type:
            return jsonify({'error': 'Не указан тип поста'}), 400
        
        generator = content_scheduler.get_current_generator()
        success, message = content_scheduler.telegram_manager.send_manual_post(post_type, generator)
        
        if success:
            return jsonify({'message': message})
        else:
            return jsonify({'error': message}), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка ручной отправки: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/test-telegram')
@SecurityManager.require_auth
def api_test_telegram():
    """API теста соединения с Telegram"""
    try:
        success = content_scheduler.telegram_manager.test_connection()
        if success:
            return jsonify({'message': '✅ Соединение с Telegram установлено'})
        else:
            return jsonify({'error': '❌ Ошибка соединения с Telegram'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/emergency-stop', methods=['POST'])
@SecurityManager.require_auth
def api_emergency_stop():
    """API аварийной остановки"""
    try:
        schedule.clear()
        logger.warning("⚠️ ВСЕ ЗАПЛАНИРОВАННЫЕ ОТПРАВКИ ОСТАНОВЛЕНЫ ПО КОМАНДЕ ПОЛЬЗОВАТЕЛЯ")
        return jsonify({'message': '✅ Все запланированные отправки остановлены'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system-info')
def api_system_info():
    """API системной информации"""
    import platform
    import psutil
    
    try:
        system_info = {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'processor': platform.processor(),
            'memory_usage': f"{psutil.virtual_memory().percent}%",
            'cpu_usage': f"{psutil.cpu_percent()}%",
            'disk_usage': f"{psutil.disk_usage('/').percent}%"
        }
        return jsonify(system_info)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/health')
def api_health():
    """API здоровья для мониторинга"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

def run_scheduler():
    """Запуск планировщика в отдельном потоке"""
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"❌ Ошибка в планировщике: {e}")
            time.sleep(10)

def start_application():
    """Запуск приложения"""
    try:
        logger.info("🚀 Запуск Recipe Bot Application")
        
        # Тест соединения с Telegram
        telegram_ok = content_scheduler.telegram_manager.test_connection()
        if not telegram_ok:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Нет соединения с Telegram")
            return False
        
        # Настройка расписания
        schedule_ok = content_scheduler.setup_schedule()
        if not schedule_ok:
            logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось настроить расписание")
            return False
        
        # Запуск планировщика в отдельном потоке
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        # Проверка ротации
        rotation_status = content_scheduler.rotation_system.check_rotation_status()
        logger.info("📊 Статус ротации контента:")
        for content_type, stats in rotation_status.items():
            status_icon = "✅" if stats['availability_percent'] > 50 else "⚠️" if stats['availability_percent'] > 20 else "❌"
            logger.info(f"   {status_icon} {content_type}: {stats['available']}/{stats['total']} ({stats['availability_percent']}%)")
        
        logger.info("✅ Приложение успешно запущено")
        logger.info("🌐 Дашборд доступен по адресу: http://localhost:5000")
        logger.info("⏰ Планировщик активен, отправка по расписанию")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        return False

# Запуск приложения
if __name__ == '__main__':
    success = start_application()
    if success:
        # Запуск Flask приложения
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            use_reloader=False
        )
    else:
        logger.error("❌ Невозможно запустить приложение из-за критических ошибок")
