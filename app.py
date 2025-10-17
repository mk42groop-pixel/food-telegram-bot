import os
import logging
import requests
import json
import time
import schedule
from datetime import datetime, timedelta
from threading import Thread, Lock
from flask import Flask, request, jsonify, render_template_string
import pytz
import random
from dotenv import load_dotenv
from functools import wraps
import secrets

# Безопасная настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET', secrets.token_hex(32))

# 🔒 Безопасная конфигурация
class SecureConfig:
    def __init__(self):
        load_dotenv()
        
        # Обязательные токены
        self.TELEGRAM_BOT_TOKEN = self._get_secure_env('TELEGRAM_BOT_TOKEN')
        self.YANDEX_GPT_API_KEY = self._get_secure_env('YANDEX_GPT_API_KEY')
        
        # Опциональные с значениями по умолчанию
        self.TELEGRAM_CHANNEL = self._get_secure_env('TELEGRAM_CHANNEL', '-1003152210862')
        self.TELEGRAM_GROUP = self._get_secure_env('TELEGRAM_GROUP', '@ppsupershef_chat')
        self.YANDEX_FOLDER_ID = self._get_secure_env('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
        self.DEEPSEEK_API_KEY = self._get_secure_env('DEEPSEEK_API_KEY', '')
        
        # Настройки времени
        self.SERVER_TIMEZONE = pytz.timezone('UTC')
        self.KEMEROVO_TIMEZONE = pytz.timezone('Asia/Novokuznetsk')
        
        self._validate_config()
    
    def _get_secure_env(self, key, default=None):
        """Безопасное получение переменных окружения"""
        value = os.getenv(key, default)
        if value is None:
            logger.warning(f"⚠️ Отсутствует переменная окружения: {key}")
        return value
    
    def _validate_config(self):
        """Валидация конфигурации"""
        if not self.TELEGRAM_BOT_TOKEN:
            raise ValueError("❌ TELEGRAM_BOT_TOKEN обязателен для работы")
        if not self.YANDEX_GPT_API_KEY:
            logger.warning("⚠️ YANDEX_GPT_API_KEY отсутствует - AI функции недоступны")

# 🔒 Декораторы безопасности
def rate_limit(requests_per_minute=30):
    def decorator(f):
        requests = []
        lock = Lock()
        
        @wraps(f)
        def decorated_function(*args, **kwargs):
            with lock:
                now = time.time()
                # Удаляем старые запросы
                requests[:] = [req for req in requests if now - req < 60]
                
                if len(requests) >= requests_per_minute:
                    return jsonify({
                        "status": "error", 
                        "message": "Слишком много запросов"
                    }), 429
                
                requests.append(now)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_token = request.headers.get('Authorization')
        expected_token = os.getenv('ADMIN_TOKEN')
        
        if expected_token and auth_token != f"Bearer {expected_token}":
            return jsonify({"status": "error", "message": "Неавторизован"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Инициализация конфигурации
try:
    config = SecureConfig()
    logger.info("✅ Безопасная конфигурация загружена")
except Exception as e:
    logger.error(f"❌ Ошибка конфигурации: {e}")
    exit(1)

# 🎨 Улучшенный класс форматирования
class ModernContentFormatter:
    """Современный форматировщик контента"""
    
    THEMES = {
        'neuro': {
            'emoji': '🧠',
            'name': 'Нейропитание',
            'color': '#8B5CF6',
            'triggers': [
                "Ясность ума начинается с завтрака",
                "Нейроны любят правильную пищу"
            ]
        },
        'energy': {
            'emoji': '⚡', 
            'name': 'Энергия',
            'color': '#F59E0B',
            'triggers': [
                "Зарядитесь энергией на весь день",
                "Топливо для ваших амбиций"
            ]
        },
        'longevity': {
            'emoji': '🛡️',
            'name': 'Долголетие', 
            'color': '#10B981',
            'triggers': [
                "Инвестируйте в свое здоровое будущее",
                "Каждый прием пищи - шаг к долголетию"
            ]
        }
    }
    
    @staticmethod
    def create_modern_message(theme_type, title, content, recipe_type):
        """Создает современное сообщение"""
        theme = ModernContentFormatter.THEMES.get(theme_type, ModernContentFormatter.THEMES['neuro'])
        
        header = f"""🎪 <b>КЛУБ ОСОЗНАННОГО ДОЛГОЛЕТИЯ</b>

{theme['emoji']} <b>{theme['name'].upper()}</b>

{random.choice(theme['triggers'])}

<b>{title}</b>"""
        
        footer = f"""
---
💫 <b>Присоединяйтесь к клубу осознанного питания!</b>

📢 <b>Канал:</b> @ppsupershef
💬 <b>Чат:</b> @ppsupershef_chat

😋 Вкусно | 💪 Полезно | 👨‍🍳 Приготовлю

#осознанноепитание #{theme_type}"""
        
        return header + "\n\n" + content + footer

# 🔧 Улучшенный менеджер Telegram
class SecureTelegramManager:
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.channel = config.TELEGRAM_CHANNEL
        self.session = requests.Session()
        self.session.timeout = (10, 30)  # 10s connect, 30s read
        
        # Кэш для избежания дублирования
        self.message_cache = set()
        self.cache_lock = Lock()
    
    def _create_message_hash(self, content):
        """Создает хеш сообщения для избежания дублирования"""
        import hashlib
        return hashlib.md5(content.encode()).hexdigest()
    
    @rate_limit(requests_per_minute=20)
    def send_message(self, content, parse_mode='HTML'):
        """Безопасная отправка сообщения"""
        try:
            # Проверка дублирования
            message_hash = self._create_message_hash(content)
            with self.cache_lock:
                if message_hash in self.message_cache:
                    logger.warning("⚠️ Попытка отправить дублирующее сообщение")
                    return False
                self.message_cache.add(message_hash)
                # Ограничиваем размер кэша
                if len(self.message_cache) > 100:
                    self.message_cache.clear()
            
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                'chat_id': self.channel,
                'text': content,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = self.session.post(url, json=payload)
            
            if response.status_code == 429:
                # Rate limiting - ждем и повторяем
                retry_after = response.json().get('parameters', {}).get('retry_after', 30)
                logger.warning(f"⚠️ Rate limit, ждем {retry_after} секунд")
                time.sleep(retry_after)
                return self.send_message(content, parse_mode)
            
            result = response.json()
            
            if result.get('ok'):
                logger.info("✅ Сообщение отправлено")
                return True
            else:
                logger.error(f"❌ Ошибка Telegram: {result.get('description')}")
                # Удаляем из кэша при ошибке
                with self.cache_lock:
                    self.message_cache.discard(message_hash)
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {str(e)}")
            with self.cache_lock:
                self.message_cache.discard(message_hash)
            return False
    
    def test_connection(self):
        """Тестирование подключения"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/getMe"
            response = self.session.get(url)
            result = response.json()
            
            if result.get('ok'):
                return {
                    "status": "success",
                    "bot_username": result['result']['username'],
                    "bot_id": result['result']['id']
                }
            return {"status": "error", "message": "Неверный токен"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# 🎯 Упрощенный генератор контента
class EfficientContentGenerator:
    def __init__(self):
        self.formatter = ModernContentFormatter()
        self.telegram = SecureTelegramManager()
    
    def generate_daily_content(self, day_type):
        """Генерация контента по типу дня"""
        content_map = {
            'monday': ('neuro', '🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА'),
            'tuesday': ('energy', '⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ'),
            'wednesday': ('longevity', '🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ'),
            'thursday': ('neuro', '🎨 ТВОРЧЕСКИЙ ЗАВТРАК'),
            'friday': ('energy', '📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК'),
            'saturday': ('longevity', '🥗 СУББОТНИЙ БРАНЧ'),
            'sunday': ('neuro', '🍳 ВОСКРЕСНЫЙ РИТУАЛ')
        }
        
        theme, title = content_map.get(day_type, ('neuro', '🍳 УМНЫЙ ЗАВТРАК'))
        
        # Здесь будет логика генерации через AI
        content = self._generate_fallback_content(theme, title)
        
        return self.formatter.create_modern_message(theme, title, content, "breakfast")
    
    def _generate_fallback_content(self, theme, title):
        """Фолбэк контент если AI недоступен"""
        recipes = {
            'neuro': """🥑 Омлет с авокадо и шпинатом

Ингредиенты (1 порция):
• 🥚 Яйца - 2 шт
• 🥑 Авокадо - ½ шт  
• 🥬 Шпинат - 50 г
• 🌰 Грецкие орехи - 20 г
• 🫒 Оливковое масло - 1 ч.л.

Приготовление (10 минут):
1. Взбейте яйца со щепоткой соли
2. Обжарьте шпинат 2 минуты
3. Влейте яйца, готовьте 5-7 минут
4. Подавайте с авокадо и орехами

💡 Польза: Улучшает когнитивные функции, защищает мозг""",
            
            'energy': """🥣 Энергетическая овсянка

Ингредиенты (1 порция):
• 🌾 Овсяные хлопья - 50 г  
• 🍌 Банан - 1 шт
• 🌰 Миндаль - 20 г
• 💎 Семена чиа - 1 ст.л.
• 🟤 Корица - ½ ч.л.

Приготовление (5 минут):
1. Залейте овсянку горячей водой
2. Добавьте банан и семена
3. Посыпьте орехами и корицей

💡 Польза: Стабильная энергия на 4-5 часов""",
            
            'longevity': """🍲 Гречневая каша с куркумой

Ингредиенты (1 порция):
• 🟤 Гречка - 50 г
• 🟡 Куркума - 1 ч.л.
• 🍓 Ягоды - 100 г
• 🌰 Грецкие орехи - 20 г
• 💚 Льняное масло - 1 ч.л.

Приготовление (15 минут):
1. Сварите гречневую кашу
2. Добавьте куркуму за 2 минуты
3. Подавайте с ягодами и маслом

💡 Польза: Активирует гены долголетия"""
        }
        
        return recipes.get(theme, recipes['neuro'])

# 🌐 Современный Flask интерфейс
@app.route('/')
def modern_dashboard():
    """Современная главная страница"""
    try:
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        day_name_ru = {
            'monday': 'Понедельник', 'tuesday': 'Вторник', 
            'wednesday': 'Среда', 'thursday': 'Четверг',
            'friday': 'Пятница', 'saturday': 'Суббота', 
            'sunday': 'Воскресенье'
        }.get(weekday, 'День')
        
        # Статистика
        telegram = SecureTelegramManager()
        bot_info = telegram.test_connection()
        
        html = f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>@ppsupershef - Осознанное питание</title>
            <style>
                :root {{
                    --primary: #8B5CF6;
                    --secondary: #F59E0B;
                    --success: #10B981;
                    --dark: #1F2937;
                    --light: #F9FAFB;
                }}
                
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                
                body {{
                    font-family: 'Segoe UI', system-ui, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    color: var(--dark);
                }}
                
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                
                .header {{
                    background: white;
                    border-radius: 20px;
                    padding: 30px;
                    margin-bottom: 24px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
                    text-align: center;
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin: 24px 0;
                }}
                
                .stat-card {{
                    background: white;
                    padding: 24px;
                    border-radius: 16px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    text-align: center;
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 16px;
                    margin: 24px 0;
                }}
                
                .btn {{
                    background: var(--primary);
                    color: white;
                    border: none;
                    padding: 16px 24px;
                    border-radius: 12px;
                    font-size: 16px;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }}
                
                .btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(139, 92, 246, 0.3);
                }}
                
                .btn-success {{ background: var(--success); }}
                .btn-warning {{ background: var(--secondary); }}
                
                .content-preview {{
                    background: white;
                    border-radius: 16px;
                    padding: 24px;
                    margin: 24px 0;
                }}
                
                @media (max-width: 768px) {{
                    .container {{ padding: 12px; }}
                    .header {{ padding: 20px; }}
                    .stat-card {{ padding: 16px; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="font-size: 2.5rem; margin-bottom: 16px;">🎪 Клуб Осознанного Долголетия</h1>
                    <p style="font-size: 1.2rem; color: #6B7280;">Питание как инвестиция в качество жизни</p>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div style="font-size: 3rem; margin-bottom: 16px;">📅</div>
                        <h3>{day_name_ru}</h3>
                        <p>Тема: {ModernContentFormatter.THEMES.get(weekday[:3], {}).get('name', 'Осознанность')}</p>
                    </div>
                    
                    <div class="stat-card">
                        <div style="font-size: 3rem; margin-bottom: 16px;">🤖</div>
                        <h3>Статус бота</h3>
                        <p>{'✅ Активен' if bot_info.get('status') == 'success' else '❌ Ошибка'}</p>
                    </div>
                    
                    <div class="stat-card">
                        <div style="font-size: 3rem; margin-bottom: 16px;">⚡</div>
                        <h3>Контент-план</h3>
                        <p>42 поста в неделю</p>
                    </div>
                </div>
                
                <div class="actions-grid">
                    <button class="btn" onclick="sendContent('breakfast')">
                        🍳 Завтрак
                    </button>
                    <button class="btn btn-success" onclick="sendContent('shopping')">
                        🛒 Чек-лист
                    </button>
                    <button class="btn btn-warning" onclick="testConnection()">
                        🔧 Диагностика
                    </button>
                    <button class="btn" onclick="sendContent('advice')">
                        💡 Советы
                    </button>
                </div>
                
                <div class="content-preview">
                    <h3 style="margin-bottom: 16px;">🎯 Быстрый предпросмотр</h3>
                    <button class="btn" onclick="sendPreview()">
                        📤 Отправить тестовый пост
                    </button>
                </div>
            </div>
            
            <script>
                async function testConnection() {{
                    try {{
                        const response = await fetch('/health');
                        const data = await response.json();
                        alert(data.status === 'healthy' ? '✅ Система работает' : '❌ Есть проблемы');
                    }} catch (error) {{
                        alert('❌ Ошибка подключения');
                    }}
                }}
                
                async function sendContent(type) {{
                    const endpoints = {{
                        'breakfast': '/send-breakfast',
                        'shopping': '/send-shopping-list', 
                        'advice': '/send-advice'
                    }};
                    
                    if (endpoints[type]) {{
                        try {{
                            const response = await fetch(endpoints[type]);
                            const data = await response.json();
                            alert(data.status === 'success' ? '✅ Отправлено' : '❌ Ошибка');
                        }} catch (error) {{
                            alert('❌ Ошибка сети');
                        }}
                    }}
                }}
                
                async function sendPreview() {{
                    try {{
                        const response = await fetch('/test-channel');
                        const data = await response.json();
                        alert(data.status === 'success' ? '✅ Тест отправлен' : '❌ Ошибка');
                    }} catch (error) {{
                        alert('❌ Ошибка сети');
                    }}
                }}
            </script>
        </body>
        </html>
        """
        return html
        
    except Exception as e:
        logger.error(f"Ошибка дашборда: {e}")
        return "🚧 Система временно недоступна"

# 🚀 Запуск приложения
if __name__ == '__main__':
    logger.info("🚀 Запуск безопасной системы управления контентом")
    
    # Проверка обязательных компонентов
    telegram = SecureTelegramManager()
    bot_test = telegram.test_connection()
    
    if bot_test.get('status') == 'success':
        logger.info(f"✅ Бот @{bot_test.get('bot_username')} готов к работе")
    else:
        logger.warning(f"⚠️ Проблемы с ботом: {bot_test.get('message')}")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
