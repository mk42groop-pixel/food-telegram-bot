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
                "Нейроны любят правильную пищу",
                "Мозг заслуживает лучшего топлива"
            ]
        },
        'energy': {
            'emoji': '⚡', 
            'name': 'Энергия',
            'color': '#F59E0B',
            'triggers': [
                "Зарядитесь энергией на весь день",
                "Топливо для ваших амбиций",
                "Энергия для великих свершений"
            ]
        },
        'longevity': {
            'emoji': '🛡️',
            'name': 'Долголетие', 
            'color': '#10B981',
            'triggers': [
                "Инвестируйте в свое здоровое будущее",
                "Каждый прием пищи - шаг к долголетию",
                "Долголетие начинается сегодня"
            ]
        },
        'gastronomy': {
            'emoji': '🍽️',
            'name': 'Гастрономия',
            'color': '#EC4899', 
            'triggers': [
                "Наслаждение с пользой для здоровья",
                "Изысканность в каждой тарелке",
                "Гастрономия как искусство"
            ]
        },
        'analytics': {
            'emoji': '📊',
            'name': 'Аналитика',
            'color': '#3B82F6',
            'triggers': [
                "Планируйте свое питание осознанно",
                "Аналитика для лучших решений", 
                "Стратегия вашего здоровья"
            ]
        },
        'shopping': {
            'emoji': '🛒',
            'name': 'Покупки',
            'color': '#8B5CF6',
            'triggers': [
                "Умные покупки - основа здоровья",
                "Инвестируйте в качественные продукты",
                "Ваша корзина - ваш выбор здоровья"
            ]
        },
        'rituals': {
            'emoji': '📈',
            'name': 'Ритуалы',
            'color': '#F59E0B',
            'triggers': [
                "Создайте ритуалы для здоровья",
                "Воскресенье - время для планирования",
                "Начните неделю с правильного настроя"
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

# 🕐 Конвертер времени
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
            'thursday': ('gastronomy', '🎨 ТВОРЧЕСКИЙ ЗАВТРАК'),
            'friday': ('analytics', '📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК'),
            'saturday': ('shopping', '🥗 СУББОТНИЙ БРАНЧ'),
            'sunday': ('rituals', '🍳 ВОСКРЕСНЫЙ РИТУАЛ')
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

💡 Польза: Активирует гены долголетия""",
            
            'gastronomy': """🍳 Гренки с авокадо и яйцом-пашот

Ингредиенты (1 порция):
• 🍞 Хлеб цельнозерновой - 2 ломтика
• 🥑 Авокадо - 1 шт
• 🥚 Яйца - 2 шт
• 🥬 Руккола - 30 г
• ⚫ Семена кунжута - 1 ч.л.

Приготовление (15 минут):
1. Подсушите хлеб на сковороде
2. Разомните авокадо с солью
3. Приготовьте яйца-пашот (3 минуты)
4. Соберите: хлеб + авокадо + руккола + яйцо

💡 Польза: Изысканный вкус с максимальной пользой""",
            
            'analytics': """🥣 Творожная масса с орехами

Ингредиенты (1 порция):
• 🧀 Творог 5% - 150 г
• 🌰 Грецкие орехи - 30 г
• 🍯 Мед - 1 ст.л.
• 🟣 Изюм - 20 г
• 🍋 Лимонный сок - 1 ч.л.

Приготовление (5 минут):
1. Смешайте творог с медом и соком
2. Добавьте орехи и изюм
3. Подавайте с хлебцами

💡 Польза: Идеально для ясности мышления"""
        }
        
        return recipes.get(theme, recipes['neuro'])
    
    def generate_shopping_list(self):
        """Генерация умного чек-листа покупок"""
        season = self._get_current_season()
        
        shopping_list = f"""🛒 <b>УМНЫЙ ЧЕК-ЛИСТ НА НЕДЕЛЮ</b>

🎯 Основа для осознанного долголетия ({season})

🧠 <b>ДЛЯ МОЗГА И НЕРВНОЙ СИСТЕМЫ:</b>
• 🌰 Грецкие орехи - 200 г
• 🥑 Авокадо - 3-4 шт
• 🐟 Жирная рыба - 500 г
• 🥚 Яйца - 10 шт
• 🍫 Темный шоколад 85% - 100 г

💪 <b>ДЛЯ ЭНЕРГИИ И ТОНУСА:</b>
• 🌾 Овсяные хлопья - 500 g
• 🍌 Бананы - 1 кг
• 💎 Семена чиа - 100 г
• 🍗 Куриная грудка - 1 кг
• 🟤 Гречневая крупа - 500 г

🛡️ <b>ДЛЯ ДОЛГОЛЕТИЯ:</b>
• 🟡 Куркума - 50 г
• 🟠 Имбирь - 100 г
• ⚪ Чеснок - 3 головки
• 🍓 Ягоды (замороженные) - 500 г
• 🥬 Зеленые овощи - 1 кг

💡 <b>СОВЕТЫ ОТ ШЕФ-ПОВАРА:</b>
• Покупайте сезонные местные продукты
• Читайте составы - избегайте рафинированного сахара
• Планируйте меню на неделю вперед
• Храните орехи и семена в холодильнике

🎯 <b>ФИЛОСОФИЯ ПОКУПОК:</b>
Каждый продукт в вашей корзине - это инвестиция в ваше долголетие и качество жизни!

#чеклист #умныепокупки #{season}"""
        
        return shopping_list
    
    def generate_expert_advice(self):
        """Генерация советов экспертов"""
        advice = """🎯 <b>ПРИНЦИП: "ЕШЬТЕ ЦВЕТА РАДУГИ"</b>

🎯 <b>ФОРМУЛИРОВКА:</b> Каждый день включайте в рацион продукты всех цветов радуги - красные, оранжевые, желтые, зеленые, синие, фиолетовые.

🔬 <b>НАУЧНОЕ ОБОСНОВАНИЕ:</b>
• 🔴 Красные - ликопин против рака
• 🟠 Оранжевые - бета-каротин для зрения  
• 🟡 Желтые - витамин C для иммунитета
• 🟢 Зеленые - лютеин для мозга
• 🔵 Синие - антоцианы для сердца
• 🟣 Фиолетовые - ресвератрол для долголетия

⚡ <b>МЕХАНИЗМ ДЕЙСТВИЯ:</b>
• Обеспечивает фитонутриентное разнообразие
• Укрепляет антиоксидантную защиту
• Снижает системное воспаление
• Поддерживает микробиом

💡 <b>ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ:</b> Сделайте свой обед разноцветным - салат из помидоров, моркови, перца, огурцов и капусты.

📈 <b>РЕЗУЛЬТАТЫ:</b> Укрепление иммунной системы, снижение воспаления, защита от хронических заболеваний.

🎯 <b>ПРОСТОЙ ШАГ:</b> Добавьте хотя бы 3 разных цвета в каждый основной прием пищи."""
        
        return advice
    
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

# 🌐 СОВРЕМЕННЫЙ FLASK ИНТЕРФЕЙС
@app.route('/')
def modern_dashboard():
    """Современная главная страница"""
    try:
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        
        # Правильные русские названия дней
        day_name_ru = {
            'monday': 'Понедельник', 
            'tuesday': 'Вторник', 
            'wednesday': 'Среда', 
            'thursday': 'Четверг',
            'friday': 'Пятница', 
            'saturday': 'Суббота', 
            'sunday': 'Воскресенье'
        }.get(weekday, 'День')
        
        # Тема дня
        day_theme = {
            'monday': '🧠 Нейропитание',
            'tuesday': '⚡ Энергия', 
            'wednesday': '🛡️ Долголетие',
            'thursday': '🍽️ Гастрономия',
            'friday': '📊 Аналитика',
            'saturday': '🛒 Покупки',
            'sunday': '📈 Ритуалы'
        }.get(weekday, '🎯 Осознанность')

        # Статистика
        telegram = SecureTelegramManager()
        bot_info = telegram.test_connection()
        bot_status = "✅ Активен" if bot_info.get('status') == 'success' else "❌ Ошибка"
        
        html = f'''
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
                    --danger: #EF4444;
                    --dark: #1F2937;
                    --light: #F9FAFB;
                }}
                
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    color: var(--dark);
                    line-height: 1.6;
                }}
                
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                
                .header {{
                    background: white;
                    border-radius: 20px;
                    padding: 40px 30px;
                    margin-bottom: 24px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
                    text-align: center;
                }}
                
                .header h1 {{
                    font-size: 2.5rem;
                    margin-bottom: 16px;
                    color: var(--dark);
                }}
                
                .header p {{
                    font-size: 1.2rem;
                    color: #6B7280;
                    font-weight: 500;
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 20px;
                    margin: 30px 0;
                }}
                
                .stat-card {{
                    background: white;
                    padding: 30px 24px;
                    border-radius: 16px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    text-align: center;
                    transition: transform 0.2s ease;
                }}
                
                .stat-card:hover {{
                    transform: translateY(-5px);
                }}
                
                .stat-icon {{
                    font-size: 3rem;
                    margin-bottom: 16px;
                }}
                
                .stat-card h3 {{
                    font-size: 1.3rem;
                    margin-bottom: 8px;
                    color: var(--dark);
                }}
                
                .stat-card p {{
                    color: #6B7280;
                    font-size: 1.1rem;
                }}
                
                .status-success {{
                    color: var(--success);
                    font-weight: bold;
                }}
                
                .status-error {{
                    color: var(--danger);
                    font-weight: bold;
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 16px;
                    margin: 30px 0;
                }}
                
                .btn {{
                    background: var(--primary);
                    color: white;
                    border: none;
                    padding: 18px 24px;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 10px;
                    text-decoration: none;
                }}
                
                .btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(139, 92, 246, 0.4);
                }}
                
                .btn-success {{ background: var(--success); }}
                .btn-warning {{ background: var(--secondary); }}
                .btn-danger {{ background: var(--danger); }}
                
                .content-preview {{
                    background: white;
                    border-radius: 16px;
                    padding: 30px;
                    margin: 30px 0;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                }}
                
                .content-preview h3 {{
                    margin-bottom: 20px;
                    color: var(--dark);
                    font-size: 1.4rem;
                }}
                
                .footer {{
                    text-align: center;
                    margin-top: 40px;
                    color: white;
                    opacity: 0.8;
                }}
                
                @media (max-width: 768px) {{
                    .container {{ padding: 15px; }}
                    .header {{ padding: 30px 20px; }}
                    .header h1 {{ font-size: 2rem; }}
                    .stat-card {{ padding: 20px 16px; }}
                    .btn {{ padding: 16px 20px; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎪 Клуб Осознанного Долголетия</h1>
                    <p>Питание как инвестиция в качество жизни</p>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon">📅</div>
                        <h3>{day_name_ru}</h3>
                        <p>Тема: {day_theme}</p>
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-icon">🤖</div>
                        <h3>Статус бота</h3>
                        <p class="{'status-success' if bot_info.get('status') == 'success' else 'status-error'}">
                            {bot_status}
                        </p>
                        {f'<p><small>@{bot_info.get("bot_username", "")}</small></p>' if bot_info.get('bot_username') else ''}
                    </div>
                    
                    <div class="stat-card">
                        <div class="stat-icon">📊</div>
                        <h3>Контент-план</h3>
                        <p>45 постов в неделю</p>
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
                    <h3>🎯 Быстрый предпросмотр</h3>
                    <button class="btn btn-success" onclick="sendPreview()">
                        📤 Отправить тестовый пост
                    </button>
                </div>
                
                <div class="footer">
                    <p>Система управления каналом @ppsupershef</p>
                    <p>🎯 Осознанное питание • 💫 Долголетие • 🧠 Нейронаука</p>
                </div>
            </div>
            
            <script>
                async function testConnection() {{
                    try {{
                        const response = await fetch('/health');
                        const data = await response.json();
                        if (data.status === 'healthy') {{
                            alert('✅ Система работает отлично!\\\\n🤖 Бот активен\\\\n📊 Все компоненты готовы');
                        }} else {{
                            alert('❌ Есть проблемы с системой');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка подключения к серверу');
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
                            if (data.status === 'success') {{
                                alert('✅ Контент успешно отправлен в канал!');
                            }} else {{
                                alert('❌ Ошибка отправки: ' + (data.message || 'Неизвестная ошибка'));
                            }}
                        }} catch (error) {{
                            alert('❌ Ошибка сети при отправке контента');
                        }}
                    }}
                }}
                
                async function sendPreview() {{
                    try {{
                        const response = await fetch('/test-channel');
                        const data = await response.json();
                        if (data.status === 'success') {{
                            alert('✅ Тестовый пост отправлен в канал!\\\\n📨 Проверьте канал @ppsupershef');
                        }} else {{
                            alert('❌ Ошибка отправки тестового поста');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка сети при отправке тестового поста');
                    }}
                }}
                
                // Показать уведомление о загрузке
                window.addEventListener('load', function() {{
                    console.log('✅ Панель управления загружена');
                }});
            </script>
        </body>
        </html>
        '''
        return html
        
    except Exception as e:
        logger.error(f"Ошибка дашборда: {e}")
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Ошибка - Клуб Осознанного Долголетия</title>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    text-align: center;
                }
                .error-container {
                    background: rgba(255,255,255,0.1);
                    padding: 40px;
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                }
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1>⚠️ Временные неполадки</h1>
                <p>Система управления временно недоступна</p>
                <p>Попробуйте обновить страницу через несколько минут</p>
            </div>
        </body>
        </html>
        """

@app.route('/health')
def health_check():
    """Проверка здоровья системы"""
    try:
        telegram = SecureTelegramManager()
        bot_info = telegram.test_connection()
        
        return jsonify({
            "status": "healthy" if bot_info.get('status') == 'success' else "degraded",
            "bot_status": bot_info.get('status'),
            "bot_username": bot_info.get('bot_username'),
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": "✅ Система работает нормально" if bot_info.get('status') == 'success' else "⚠️ Проблемы с ботом"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "❌ Критическая ошибка системы",
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })

@app.route('/test-channel')
def test_channel():
    """Тестирование канала"""
    try:
        telegram = SecureTelegramManager()
        current_times = TimeZoneConverter.get_current_times()
        
        test_message = f"""🎪 <b>ТЕСТ СИСТЕМЫ УПРАВЛЕНИЯ</b>

✅ Клуб Осознанного Долголетия @ppsupershef
🤖 Автопостинг активирован
📊 Контент-план: 45 постов/неделю
🎯 Философия: Питание как инвестиция в качество жизни

💫 <b>РАСПИСАНИЕ КОНТЕНТА:</b>
• 🧠 Пн: Нейропитание для ума
• ⚡ Вт: Энергия для достижений  
• 🛡️ Ср: Стратегии долголетия
• 🍽️ Чт: Гастрономия с пользой
• 📊 Пт: Аналитика и планы
• 🛒 Сб: Умные покупки
• 📈 Вс: Ритуалы и мотивация

🕐 <b>Время публикации:</b> {current_times['kemerovo_time']}

#тест #диагностика #клуб"""
        
        success = telegram.send_message(test_message)
        return jsonify({
            "status": "success" if success else "error", 
            "message": "Тестовое сообщение отправлено" if success else "Ошибка отправки"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-breakfast')
@rate_limit()
def send_breakfast():
    """Отправка завтрака"""
    try:
        telegram = SecureTelegramManager()
        content_gen = EfficientContentGenerator()
        
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        
        content = content_gen.generate_daily_content(weekday)
        success = telegram.send_message(content)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Завтрак отправлен" if success else "Ошибка отправки"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-shopping-list')
@rate_limit()
def send_shopping_list():
    """Отправка чек-листа покупок"""
    try:
        telegram = SecureTelegramManager()
        content_gen = EfficientContentGenerator()
        
        content = content_gen.generate_shopping_list()
        success = telegram.send_message(content)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Чек-лист отправлен" if success else "Ошибка отправки"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-advice')
@rate_limit()
def send_advice():
    """Отправка советов экспертов"""
    try:
        telegram = SecureTelegramManager()
        content_gen = EfficientContentGenerator()
        
        content = content_gen.generate_expert_advice()
        success = telegram.send_message(content)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Советы отправлены" if success else "Ошибка отправки"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-manual-content', methods=['POST'])
@rate_limit()
def send_manual_content():
    """Отправка ручного контента"""
    try:
        telegram = SecureTelegramManager()
        data = request.get_json()
        
        if not data or 'content' not in data:
            return jsonify({"status": "error", "message": "Отсутствует содержимое"})
            
        content = data['content']
        if not content.strip():
            return jsonify({"status": "error", "message": "Пустое сообщение"})
        
        current_times = TimeZoneConverter.get_current_times()
        content_with_footer = f"{content}\n\n🕐 Опубликовано: {current_times['kemerovo_time']}"
        
        success = telegram.send_message(content_with_footer)
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

# 🚀 ЗАПУСК ПРИЛОЖЕНИЯ
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
