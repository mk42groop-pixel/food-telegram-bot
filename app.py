import os
import logging
import requests
import json
import time
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
    
    # СИСТЕМНЫЙ ПРОМПТ ДЛЯ YANDEX GPT
    SYSTEM_PROMPT = """Ты эксперт по осознанному долголетию и нейропитанию, нутрициолог и Шеф-повар ресторанов Мишлен. Твоя задача - создавать контент, который превращает прием пищи в инструмент для улучшения качества жизни.

ФИЛОСОФИЯ: 
"Осознанное питание как инвестиция в энергичную, долгую и продуктивную жизнь"

ТРЕБОВАНИЯ К ФОРМАТУ:
1. Начинай с эмоционального триггера о качестве жизни
2. Добавляй научное обоснование пользы ТЕЗИСНО:
   • Основные полезные компоненты
   • Ключевые витамины/минералы  
   • Главные преимущества для здоровья
3. Давай практические рецепты с точными количествами
4. Объясняй механизм действия на организм ТЕЗИСНО:
   • Как работает в теле
   • Влияние на системы организма
   • Эффекты для метаболизма

ОСОБЕННОСТИ РЕЦЕПТОВ:
- Техники шеф-повара Мишлен, адаптированные для дома
- Научно обоснованная польза каждого ингредиента
- Баланс вкуса и функциональности
- Доступные в России ингредиенты с максимальной пользой

ТОН:
- Дружеский, но экспертный
- Мотивирующий, но без излишнего энтузиазма  
- Научный, но доступный
- Вдохновляющий на изменения

Всегда используй эмодзи для визуального оформления."""
    
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
    
    def get_channel_info(self):
        """Получение информации о канале"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/getChat"
            payload = {
                'chat_id': self.channel
            }
            response = self.session.post(url, json=payload)
            result = response.json()
            
            if result.get('ok'):
                return {
                    "status": "success",
                    "title": result['result'].get('title', 'Unknown'),
                    "username": result['result'].get('username', 'Unknown'),
                    "type": result['result'].get('type', 'Unknown')
                }
            return {"status": "error", "message": "Не удалось получить информацию о канале"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_member_count(self):
        """Получение количества подписчиков"""
        try:
            url = f"https://api.telegram.org/bot{self.token}/getChatMembersCount"
            payload = {
                'chat_id': self.channel
            }
            response = self.session.post(url, json=payload)
            result = response.json()
            
            if result.get('ok'):
                return result['result']
            return 0
        except Exception as e:
            logger.error(f"❌ Ошибка получения количества подписчиков: {e}")
            return 0

# 🧠 ИНТЕГРИРОВАННЫЙ ГЕНЕРАТОР КОНТЕНТА С YANDEX GPT
class AIContentGenerator:
    def __init__(self):
        self.formatter = ModernContentFormatter()
        self.telegram = SecureTelegramManager()
        self.yandex_key = config.YANDEX_GPT_API_KEY
        self.yandex_folder = config.YANDEX_FOLDER_ID
        
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
                    'maxTokens': 2000
                },
                'messages': [
                    {
                        'role': 'system',
                        'text': self.formatter.SYSTEM_PROMPT
                    },
                    {
                        'role': 'user',
                        'text': prompt
                    }
                ]
            }
            
            logger.info("🔄 Генерация контента через Yandex GPT...")
            response = requests.post(url, headers=headers, json=data, timeout=30)
            result = response.json()
            
            if 'result' in result:
                content = result['result']['alternatives'][0]['message']['text']
                logger.info("✅ Контент успешно сгенерирован")
                return content
            else:
                logger.error(f"❌ Ошибка Yandex GPT: {result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Исключение в Yandex GPT: {str(e)}")
            return None

    def generate_daily_content(self, day_type, meal_type="breakfast"):
        """Генерация контента по типу дня через AI"""
        content_map = {
            'monday': {
                'theme': 'neuro', 
                'titles': {
                    'breakfast': '🧠 НЕЙРОЗАВТРАК ДЛЯ ЯСНОСТИ УМА',
                    'lunch': '🎯 ОБЕД ДЛЯ ФОКУСА И КОНЦЕНТРАЦИИ',
                    'dinner': '🌙 ВОССТАНАВЛИВАЮЩИЙ УЖИН ДЛЯ НЕРВНОЙ СИСТЕМЫ',
                    'dessert': '🍫 УМНЫЙ ДЕСЕРТ ДЛЯ КОГНИТИВНЫХ ФУНКЦИЙ',
                    'advice': '💡 ПРИНЦИП НЕЙРОПИТАНИЯ ДЛЯ ЯСНОСТИ УМА'
                },
                'prompts': {
                    'breakfast': """Создай рецепт завтрака, который запускает когнитивные функции на полную мощность.""",
                    'lunch': """Создай рецепт обеда для поддержания ментальной энергии и фокуса во второй половине дня.""",
                    'dinner': """Создай рецепт ужина, который восстанавливает нервную систему и готовит мозг к качественному сну.""",
                    'dessert': """Создай рецепт УМНОГО ДЕСЕРТА для улучшения когнитивных функций.""",
                    'advice': """Создай короткий принцип нейропитания (1-2 предложения) с научным обоснованием его пользы для мозга и когнитивных функций."""
                }
            },
            'tuesday': {
                'theme': 'energy',
                'titles': {
                    'breakfast': '⚡ ЭНЕРГО-ЗАВТРАК ДЛЯ АКТИВНОГО ДНЯ',
                    'lunch': '🏃 ОБЕД ДЛЯ ВЫНОСЛИВОСТИ И ЭНЕРГИИ', 
                    'dinner': '💪 ВОССТАНАВЛИВАЮЩИЙ УЖИН ДЛЯ МЫШЦ',
                    'dessert': '🍓 ЭНЕРГЕТИЧЕСКИЙ ДЕСЕРТ ДЛЯ ТОНУСА',
                    'advice': '💡 ПРИНЦИП ЭНЕРГЕТИЧЕСКОГО ПИТАНИЯ ДЛЯ ВЫНОСЛИВОСТИ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт завтрака, который заряжает клеточные электростанции - митохондрии.""",
                    'lunch': """Создай рецепт обеда для поддержания физической энергии и выносливости.""",
                    'dinner': """Создай рецепт ужина для восстановления мышц и подготовки к следующему дню.""",
                    'dessert': """Создай рецепт ЭНЕРГЕТИЧЕСКОГО ДЕСЕРТА для поддержания тонуса и энергии.""",
                    'advice': """Создай короткий принцип энергетического питания (1-2 предложения) с научным обоснованием его пользы для митохондрий и выносливости."""
                }
            },
            'wednesday': {
                'theme': 'longevity',
                'titles': {
                    'breakfast': '🛡️ ЗАВТРАК ДОЛГОЖИТЕЛЯ',
                    'lunch': '🌿 ОБЕД ДЛЯ ДОЛГОЛЕТИЯ',
                    'dinner': '🌙 УЖИН ДЛЯ КЛЕТОЧНОГО ОБНОВЛЕНИЯ',
                    'dessert': '🍇 АНТИЭЙДЖ ДЕСЕРТ ДЛЯ МОЛОДОСТИ',
                    'advice': '💡 ПРИНЦИП ПИТАНИЯ ДЛЯ АКТИВАЦИИ ГЕНОВ ДОЛГОЛЕТИЯ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт завтрака, который активирует гены долголетия.""",
                    'lunch': """Создай рецепт обеда с геропротекторными свойствами.""",
                    'dinner': """Создай рецепт ужина, способствующего клеточному обновлению.""",
                    'dessert': """Создай рецепт АНТИЭЙДЖ ДЕСЕРТА для замедления старения и сохранения молодости.""",
                    'advice': """Создай короткий принцип питания для долголетия (1-2 предложения) с научным обоснованием его пользы для активации генов долголетия и клеточного обновления."""
                }
            },
            'thursday': {
                'theme': 'gastronomy',
                'titles': {
                    'breakfast': '🎨 ТВОРЧЕСКИЙ ЗАВТРАК',
                    'lunch': '🍽️ РЕСТОРАННЫЙ ОБЕД С ПОЛЬЗОЙ',
                    'dinner': '🌙 ГАСТРОНОМИЧЕСКИЙ УЖИН',
                    'dessert': '🎭 ШЕФ-ДЕСЕРТ ОТ МИШЛЕН С ПОЛЬЗОЙ',
                    'advice': '💡 ПРИНЦИП ГАСТРОНОМИЧЕСКОГО ОСОЗНАНИЯ В ПИТАНИИ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт завтрака ресторанного уровня с максимальной пользой.""",
                    'lunch': """Создай рецепт изысканного обеда, который доказывает что полезное может быть вкусным.""",
                    'dinner': """Создай рецепт ужина для гастрономического наслаждения с пользой для здоровья.""",
                    'dessert': """Создай рецепт ШЕФ-ДЕСЕРТА ОТ МИШЛЕН ресторанного уровня с научно обоснованной пользой.""",
                    'advice': """Создай короткий принцип гастрономического осознания (1-2 предложения) с научным обоснованием его пользы для сочетания вкуса и пользы."""
                }
            },
            'friday': {
                'theme': 'analytics', 
                'titles': {
                    'breakfast': '📊 АНАЛИТИЧЕСКИЙ ЗАВТРАК',
                    'lunch': '🎯 ОБЕД ДЛЯ ПОДВЕДЕНИЯ ИТОГОВ',
                    'dinner': '🌙 УЖИН ДЛЯ ПЛАНОВ НА ВЫХОДНЫЕ',
                    'dessert': '🍍 ДЕСЕРТ ДЛЯ ОСМЫСЛЕНИЯ НЕДЕЛИ',
                    'advice': '💡 ПРИНЦИП АНАЛИТИЧЕСКОГО ПОДХОДА К ПИТАНИЮ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт завтрака, который помогает анализировать неделю и планировать день.""",
                    'lunch': """Создай рецепт обеда для подведения итогов недели и анализа достижений.""",
                    'dinner': """Создай рецепт ужина, который помогает планировать выходные и восстанавливать силы.""",
                    'dessert': """Создай рецепт ДЕСЕРТА ДЛЯ ОСМЫСЛЕНИЯ, который помогает анализировать прошедшую неделю.""",
                    'advice': """Создай короткий принцип аналитического подхода к питанию (1-2 предложения) с научным обоснованием его пользы для планирования и осознанного выбора."""
                }
            },
            'saturday': {
                'theme': 'shopping',
                'titles': {
                    'breakfast': '🥗 СУББОТНИЙ БРАНЧ',
                    'lunch': '🍲 СЕМЕЙНЫЙ ОБЕД',
                    'dinner': '🌙 СУББОТНИЙ УЖИН',
                    'dessert': '🧁 СУББОТНИЙ ДЕСЕРТ ДЛЯ СЕМЬИ',
                    'advice': '💡 ПРИНЦИП УМНЫХ ПРОДУКТОВЫХ ВЫБОРОВ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт субботнего бранча для всей семьи.""",
                    'lunch': """Создай рецепт семейного обеда из продуктов умного чек-листа.""",
                    'dinner': """Создай рецепт ужина для спокойного субботнего вечера.""",
                    'dessert': """Создай рецепт СЕМЕЙНОГО СУББОТНЕГО ДЕСЕРТА, который понравится и детям, и взрослым.""",
                    'advice': """Создай короткий принцип умных продуктовых выборов (1-2 предложения) с научным обоснованием его пользы для здоровья семьи и бюджета."""
                }
            },
            'sunday': {
                'theme': 'rituals',
                'titles': {
                    'breakfast': '🍳 ВОСКРЕСНЫЙ БРАНЧ-РИТУАЛ',
                    'lunch': '🥘 ВОСКРЕСНЫЙ ОБЕД', 
                    'dinner': '🌙 ВОСКРЕСНЫЙ УЖИН ДЛЯ ПОДГОТОВКИ К НЕДЕЛЕ',
                    'dessert': '🍮 ВОСКРЕСНЫЙ ДЕСЕРТ-РИТУАЛ ДЛЯ НАСТРОЯ',
                    'advice': '💡 ПРИНЦИП ПИТАТЕЛЬНЫХ РИТУАЛОВ ДЛЯ КАЧЕСТВА ЖИЗНИ'
                },
                'prompts': {
                    'breakfast': """Создай рецепт воскресного бранча как ритуала подготовки к неделе.""",
                    'lunch': """Создай рецепт воскресного обеда для семейного времяпрепровождения.""",
                    'dinner': """Создай рецепт ужина, который настраивает на продуктивную неделю.""",
                    'dessert': """Создай рецепт ВОСКРЕСНОГО ДЕСЕРТА-РИТУАЛА для настройки на новую неделю.""",
                    'advice': """Создай короткий принцип питательных ритуалов (1-2 предложения) с научным обоснованием его пользы для психологического комфорта и качества жизни."""
                }
            }
        }
        
        day_data = content_map.get(day_type, content_map['monday'])
        theme = day_data['theme']
        title = day_data['titles'].get(meal_type, day_data['titles']['breakfast'])
        base_prompt = day_data['prompts'].get(meal_type, day_data['prompts']['breakfast'])
        
        # Дополняем промпт в зависимости от типа приема пищи
        if meal_type == 'advice':
            full_prompt = f"""{base_prompt}

Формат: Короткий принцип (1-2 предложения) + научное обоснование пользы

Тема дня: {theme} - {day_data['titles']['breakfast'].split(' ', 1)[1]}

Сделай текст мотивирующим и практичным для применения."""
        else:
            full_prompt = f"""{base_prompt}

Эмоциональный триггер: "{random.choice(self.formatter.THEMES[theme]['triggers'])}"

Требования:
- Время приготовления: {"до 15 минут" if meal_type == "breakfast" else "до 30 минут" if meal_type == "lunch" else "до 25 минут" if meal_type == "dinner" else "до 20 минут"}
- Ингредиенты доступны в российских магазинах
- Учитывай сезонность продуктов
- Добавь научное обоснование пользы

Формат:
1. Ингредиенты с точными количествами
2. Пошаговое приготовление
3. Научное обоснование пользы
4. Советы по сервировке"""
        
        # Пытаемся сгенерировать через AI
        ai_content = self.generate_with_yandex_gpt(full_prompt)
        
        if ai_content:
            content = ai_content
            logger.info(f"✅ Использован AI-генерированный контент для {meal_type}")
        else:
            # Фолбэк на локальный контент
            content = self._generate_fallback_content(theme, title, meal_type)
            logger.info(f"⚠️ Использован фолбэк-контент для {meal_type}")
        
        return self.formatter.create_modern_message(theme, title, content, meal_type)
    
    def _generate_fallback_content(self, theme, title, meal_type):
        """Фолбэк контент если AI недоступен"""
        if meal_type == 'advice':
            advice_map = {
                'neuro': """🎯 <b>ПРИНЦИП: "КОРМИТЕ МОЗГ, А НЕ ЭМОЦИИ"</b>

💡 Каждый прием пищи начинайте с вопроса: "Что нужно моему мозгу для ясности и концентрации?"

🔬 <b>Научное обоснование:</b>
• Мозг потребляет 20% всей энергии тела
• Омега-3 укрепляют нейронные связи
• Антиоксиданты защищают от окислительного стресса

⚡ <b>Результат:</b> Улучшение памяти, концентрации и когнитивной гибкости""",
                'energy': """🎯 <b>ПРИНЦИП: "ТОПЛИВО ДЛЯ МИТОХОНДРИЙ"</b>

💡 Выбирайте продукты, которые заряжают клеточные электростанции, а не просто утоляют голод.

🔬 <b>Научное обоснование:</b>
• Митохондрии производят 90% энергии тела
• Магний активирует АТФ-синтез
• Коэнзим Q10 улучшает клеточное дыхание

⚡ <b>Результат:</b> Стабильная энергия в течение дня, повышение выносливости""",
                'longevity': """🎯 <b>ПРИНЦИП: "АКТИВИРУЙТЕ ГЕНЫ ДОЛГОЛЕТИЯ"</b>

💡 Каждый продукт в вашей тарелке должен включать генетические программы восстановления.

🔬 <b>Научное обоснование:</b>
• Сиртуины активируются при ограничении калорий
• Аутофагия очищает клетки от повреждений
• Теломераза защищает хромосомы

⚡ <b>Результат:</b> Замедление старения, улучшение клеточного здоровья""",
                'gastronomy': """🎯 <b>ПРИНЦИП: "ПРЕВРАТИТЕ ЕДУ В ИСКУССТВО"</b>

💡 Каждый прием пищи - это возможность для творчества и наслаждения, а не просто необходимость.

🔬 <b>Научное обоснование:</b>
• Эстетика пищи активирует центры удовольствия
• Разнообразие вкусов тренирует сенсорные рецепторы
• Осознанное питание улучшает пищеварение

⚡ <b>Результат:</b> Улучшение пищеварения, снижение стресса, повышение удовлетворенности""",
                'analytics': """🎯 <b>ПРИНЦИП: "ДАННЫЕ ДЛЯ ЗДОРОВЬЯ"</b>

💡 Отслеживайте не калории, а качество питательных веществ и их влияние на ваше состояние.

🔬 <b>Научное обоснование:</b>
• Биохакинг позволяет персонализировать питание
• Анализ маркеров выявляет индивидуальные потребности
• Планирование предотвращает импульсивные выборы

⚡ <b>Результат:</b> Оптимизация здоровья, предотвращение заболеваний""",
                'shopping': """🎯 <b>ПРИНЦИП: "ИНВЕСТИЦИЯ В КАЧЕСТВО"</b>

💡 Покупайте не продукты, а инвестируйте в свое здоровое будущее с каждым выбором в магазине.

🔬 <b>Научное обоснование:</b>
• Органические продукты содержат больше антиоксидантов
• Качественные белки лучше усваиваются
• Сезонные овощи имеют максимальную питательную ценность

⚡ <b>Результат:</b> Улучшение здоровья, экономия на лечении""",
                'rituals': """🎯 <b>ПРИНЦИП: "РИТУАЛЫ ДЛЯ БАЛАНСА"</b>

💡 Создайте пищевые ритуалы, которые становятся якорями стабильности в хаотичном мире.

🔬 <b>Научное обоснование:</b>
• Ритуалы снижают уровень кортизола
• Регулярность улучшает циркадные ритмы
• Осознанность нормализует пищевое поведение

⚡ <b>Результат:</b> Снижение стресса, улучшение метаболизма"""
            }
            return advice_map.get(theme, advice_map['neuro'])
        else:
            # Существующий фолбэк для приемов пищи
            recipes = {
                'neuro': {
                    'breakfast': """🥑 Омлет с авокадо и шпинатом

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
                    'dessert': """🍫 Шоколадный мусс из авокадо

Ингредиенты (2 порции):
• 🥑 Авокадо - 2 спелых
• 🍫 Какао-порошок - 3 ст.л.
• 🍯 Мед - 2 ст.л. 
• 🍌 Банан - 1 шт
• 🌰 Грецкие орехи - 30 г

Приготовление (10 минут):
1. Очистите авокадо и банан
2. Взбейте в блендере до кремообразной массы
3. Добавьте какао и мед, взбейте еще раз
4. Охладите 15 минут, посыпьте орехами

💡 Научное обоснование:
• Авокадо - олеиновая кислота для нейронов
• Какао - флавоноиды для памяти
• Грецкие орехи - омега-3 для пластичности

⚡ Механизм действия:
• Укрепляет мембраны нейронов
• Улучшает синаптическую передачу
• Повышает когнитивную гибкость"""
                },
                # ... остальной существующий фолбэк контент
            }
            theme_recipes = recipes.get(theme, recipes['neuro'])
            return theme_recipes.get(meal_type, theme_recipes['breakfast'])
    
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

🍰 <b>ДЛЯ УМНЫХ ДЕСЕРТОВ:</b>
• 🥑 Авокадо - 2 шт
• 🍫 Какао-порошок - 100 г
• 🍯 Натуральный мед - 300 г
• 🥛 Кокосовое молоко - 400 мл
• 💎 Семена чиа - 50 г
• 🍋 Агар-агар - 30 г
• 🍓 Смесь ягод - 500 г

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
        """Генерация советов экспертов через AI"""
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
        
        ai_content = self.generate_with_yandex_gpt(prompt)
        
        if ai_content:
            return ai_content
        else:
            # Фолбэк совет
            return """🎯 <b>ПРИНЦИП: "ЕШЬТЕ ЦВЕТА РАДУГИ"</b>

🎯 <b>ФОРМУЛИРОВКА:</b> Каждый день включайте в рацион продукты всех цветов радуги.

🔬 <b>НАУЧНОЕ ОБОСНОВАНИЕ:</b>
• 🔴 Красные - ликопин против рака
• 🟠 Оранжевые - бета-каротин для зрения  
• 🟢 Зеленые - лютеин для мозга
• 🔵 Синие - антоцианы для сердца

⚡ <b>МЕХАНИЗМ ДЕЙСТВИЯ:</b>
• Обеспечивает фитонутриентное разнообразие
• Укрепляет антиоксидантную защиту
• Снижает системное воспаление

💡 <b>ПРАКТИЧЕСКОЕ ПРИМЕНЕНИЕ:</b> Добавьте 3 разных цвета в каждый прием пищи.

📈 <b>РЕЗУЛЬТАТЫ:</b> Укрепление иммунной системы, защита от хронических заболеваний."""
    
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

# 📊 Класс для аналитики канала
class ChannelAnalytics:
    def __init__(self):
        self.telegram = SecureTelegramManager()
    
    def get_full_stats(self):
        """Полная статистика канала"""
        try:
            member_count = self.telegram.get_member_count()
            channel_info = self.telegram.get_channel_info()
            bot_info = self.telegram.test_connection()
            
            return {
                "status": "success",
                "member_count": member_count,
                "channel_title": channel_info.get('title', 'Unknown') if channel_info.get('status') == 'success' else 'Unknown',
                "channel_username": channel_info.get('username', 'Unknown') if channel_info.get('status') == 'success' else 'Unknown',
                "bot_username": bot_info.get('bot_username', 'Unknown'),
                "bot_status": bot_info.get('status', 'error'),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def generate_analytics_report(self):
        """Генерация отчета аналитики"""
        stats = self.get_full_stats()
        
        if stats["status"] == "success":
            report = f"""📊 <b>ПОЛНАЯ СТАТИСТИКА КАНАЛА</b>

👥 <b>Подписчиков:</b> {stats['member_count']}
📺 <b>Канал:</b> {stats['channel_title']}
🔗 <b>Username:</b> @{stats['channel_username']}
🤖 <b>Бот:</b> @{stats['bot_username']}
🕐 <b>Отчет сгенерирован:</b> {stats['timestamp']}

💫 <b>КОНТЕНТ-СТРАТЕГИЯ:</b>
• 🧠 Пн: Нейропитание для ума
• ⚡ Вт: Энергия для достижений
• 🛡️ Ср: Стратегии долголетия  
• 🍽️ Чт: Гастрономия с пользой
• 📊 Пт: Аналитика и планы
• 🛒 Сб: Умные покупки
• 📈 Вс: Ритуалы и мотивация

🎯 <b>ЕЖЕДНЕВНЫЙ КОНТЕНТ:</b>
• 🍳 07:00 - Завтрак
• 🍲 12:00 - Обед
• 🍰 17:00 - Умный десерт
• 🌙 19:00 - Ужин
• 💡 21:00 - Советы экспертов

#аналитика #отчет #статистика"""
            return report
        else:
            return "❌ Не удалось получить статистику канала"

# 🕐 АВТОМАТИЧЕСКИЙ ПЛАНИРОВЩИК БЕЗ ВНЕШНИХ ЗАВИСИМОСТЕЙ
class AutoScheduler:
    """Автоматический планировщик без внешних зависимостей"""
    
    def __init__(self):
        self.telegram = SecureTelegramManager()
        self.content_gen = AIContentGenerator()
        self.last_sent = {}  # Кэш последних отправленных сообщений
        self.running = True
        
    def should_send_meal(self, meal_type, current_time):
        """Проверяет, нужно ли отправлять сообщение"""
        schedule = {
            'breakfast': '07:00',
            'lunch': '12:00', 
            'dessert': '17:00',
            'dinner': '19:00',
            'advice': '21:00'  # ДОБАВЛЕНО время для советов
        }
        
        scheduled_time = schedule.get(meal_type)
        if not scheduled_time:
            return False
            
        # Точное совпадение времени
        if current_time == scheduled_time:
            # Проверяем, не отправляли ли уже сегодня
            today = datetime.now(config.KEMEROVO_TIMEZONE).date().isoformat()
            key = f"{today}_{meal_type}"
            
            if key not in self.last_sent:
                self.last_sent[key] = True
                # Очищаем старые записи (больше 1 дня)
                self._clean_old_entries()
                return True
                
        return False
    
    def _clean_old_entries(self):
        """Очищает старые записи из кэша"""
        today = datetime.now(config.KEMEROVO_TIMEZONE).date().isoformat()
        keys_to_remove = []
        
        for key in self.last_sent.keys():
            key_date = key.split('_')[0]
            if key_date != today:
                keys_to_remove.append(key)
                
        for key in keys_to_remove:
            del self.last_sent[key]
    
    def send_scheduled_meal(self, meal_type):
        """Отправка запланированного сообщения"""
        try:
            current_time = datetime.now(config.KEMEROVO_TIMEZONE)
            weekday = current_time.strftime('%A').lower()
            
            logger.info(f"🕐 Автоматическая отправка {meal_type} для {weekday}")
            
            content = self.content_gen.generate_daily_content(weekday, meal_type)
            success = self.telegram.send_message(content)
            
            if success:
                logger.info(f"✅ {meal_type} автоматически отправлен в {current_time.strftime('%H:%M')}")
            else:
                logger.error(f"❌ Ошибка автоматической отправки {meal_type}")
                
            return success
            
        except Exception as e:
            logger.error(f"❌ Исключение при отправке {meal_type}: {e}")
            return False
    
    def run_scheduler(self):
        """Основной цикл планировщика"""
        logger.info("🚀 Автоматический планировщик запущен")
        
        while self.running:
            try:
                # Текущее время в Кемерово
                now = datetime.now(config.KEMEROVO_TIMEZONE)
                current_time_str = now.strftime('%H:%M')
                current_weekday = now.strftime('%A').lower()
                
                # Проверяем все типы сообщений (ДОБАВЛЕН advice)
                meal_types = ['breakfast', 'lunch', 'dessert', 'dinner', 'advice']
                
                for meal_type in meal_types:
                    if self.should_send_meal(meal_type, current_time_str):
                        # Запускаем в отдельном потоке чтобы не блокировать основной
                        thread = Thread(
                            target=self.send_scheduled_meal,
                            args=(meal_type,),
                            daemon=True
                        )
                        thread.start()
                
                # Также проверяем специальные сообщения
                self._check_special_messages(now, current_time_str)
                
                # Ждем 55 секунд до следующей проверки
                time.sleep(55)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике: {e}")
                time.sleep(60)  # Ждем минуту при ошибке
    
    def _check_special_messages(self, now, current_time_str):
        """Проверяет специальные сообщения (чек-листы, аналитика)"""
        try:
            # Чек-лист покупок в субботу в 10:00
            if (now.strftime('%A').lower() == 'saturday' and 
                current_time_str == '10:00' and 
                f"shopping_{now.date().isoformat()}" not in self.last_sent):
                
                content = self.content_gen.generate_shopping_list()
                success = self.telegram.send_message(content)
                
                if success:
                    self.last_sent[f"shopping_{now.date().isoformat()}"] = True
                    logger.info("✅ Автоматический чек-лист отправлен")
            
            # Отчет аналитики в воскресенье в 11:00
            elif (now.strftime('%A').lower() == 'sunday' and 
                  current_time_str == '11:00' and 
                  f"analytics_{now.date().isoformat()}" not in self.last_sent):
                
                analytics = ChannelAnalytics()
                report = analytics.generate_analytics_report()
                success = self.telegram.send_message(report)
                
                if success:
                    self.last_sent[f"analytics_{now.date().isoformat()}"] = True
                    logger.info("✅ Автоматический отчет аналитики отправлен")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка отправки специальных сообщений: {e}")
    
    def stop(self):
        """Остановка планировщика"""
        self.running = False
        logger.info("🛑 Автоматический планировщик остановлен")

# 🚀 СОВРЕМЕННЫЙ ДАШБОРД С 6 ВКЛАДКАМИ
@app.route('/')
def modern_dashboard():
    """Современный дашборд управления каналом"""
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
        content_gen = AIContentGenerator()
        analytics = ChannelAnalytics()
        
        bot_info = telegram.test_connection()
        channel_stats = analytics.get_full_stats()
        current_times = TimeZoneConverter.get_current_times()
        
        bot_status = "✅ Активен" if bot_info.get('status') == 'success' else "❌ Ошибка"
        ai_status = "✅ Доступен" if content_gen.yandex_key else "❌ Не настроен"
        member_count = channel_stats.get('member_count', 0) if channel_stats.get('status') == 'success' else 0
        
        # Расписание публикаций С ДЕСЕРТАМИ И СОВЕТАМИ
        schedule_data = {
            'monday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '🧠 Нейрозавтрак'},
                {'time': '12:00', 'type': 'lunch', 'name': '🎯 Обед для фокуса'},
                {'time': '17:00', 'type': 'dessert', 'name': '🍫 Умный десерт для мозга'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Восстанавливающий ужин'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип нейропитания'}
            ],
            'tuesday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '⚡ Энерго-завтрак'},
                {'time': '12:00', 'type': 'lunch', 'name': '🏃 Обед для выносливости'},
                {'time': '17:00', 'type': 'dessert', 'name': '🍓 Энергетический десерт'},
                {'time': '19:00', 'type': 'dinner', 'name': '💪 Восстанавливающий ужин'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип энергетики'}
            ],
            'wednesday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '🛡️ Завтрак долгожителя'},
                {'time': '12:00', 'type': 'lunch', 'name': '🌿 Обед для долголетия'},
                {'time': '17:00', 'type': 'dessert', 'name': '🍇 Антиэйдж десерт'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Ужин для обновления'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип долголетия'}
            ],
            'thursday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '🎨 Творческий завтрак'},
                {'time': '12:00', 'type': 'lunch', 'name': '🍽️ Ресторанный обед'},
                {'time': '17:00', 'type': 'dessert', 'name': '🎭 Шеф-десерт от Мишлен'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Гастрономический ужин'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип гастрономии'}
            ],
            'friday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '📊 Аналитический завтрак'},
                {'time': '12:00', 'type': 'lunch', 'name': '🎯 Обед для итогов'},
                {'time': '17:00', 'type': 'dessert', 'name': '🍍 Десерт для осмысления'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Ужин для планов'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип аналитики'}
            ],
            'saturday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '🥗 Субботний бранч'},
                {'time': '12:00', 'type': 'lunch', 'name': '🍲 Семейный обед'},
                {'time': '17:00', 'type': 'dessert', 'name': '🧁 Субботний десерт'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Субботний ужин'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип покупок'}
            ],
            'sunday': [
                {'time': '07:00', 'type': 'breakfast', 'name': '🍳 Воскресный бранч'},
                {'time': '12:00', 'type': 'lunch', 'name': '🥘 Воскресный обед'},
                {'time': '17:00', 'type': 'dessert', 'name': '🍮 Воскресный десерт-ритуал'},
                {'time': '19:00', 'type': 'dinner', 'name': '🌙 Ужин для подготовки'},
                {'time': '21:00', 'type': 'advice', 'name': '💡 Принцип ритуалов'}
            ]
        }
        
        today_schedule = schedule_data.get(weekday, [])
        
        html = f'''
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>@ppsupershef - Умный дашборд</title>
            <style>
                :root {{
                    --primary: #8B5CF6;
                    --secondary: #F59E0B;
                    --success: #10B981;
                    --danger: #EF4444;
                    --warning: #F59E0B;
                    --info: #3B82F6;
                    --dark: #1F2937;
                    --light: #F9FAFB;
                    --gray: #6B7280;
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
                    max-width: 1400px;
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
                
                .header h1 {{
                    font-size: 2.5rem;
                    margin-bottom: 10px;
                    color: var(--dark);
                }}
                
                .header p {{
                    font-size: 1.2rem;
                    color: var(--gray);
                    font-weight: 500;
                }}
                
                .tabs {{
                    display: flex;
                    background: white;
                    border-radius: 15px;
                    padding: 10px;
                    margin-bottom: 24px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    flex-wrap: wrap;
                }}
                
                .tab {{
                    flex: 1;
                    min-width: 120px;
                    padding: 15px 20px;
                    text-align: center;
                    background: none;
                    border: none;
                    border-radius: 10px;
                    cursor: pointer;
                    font-weight: 600;
                    color: var(--gray);
                    transition: all 0.3s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }}
                
                .tab:hover {{
                    background: #F3F4F6;
                    color: var(--dark);
                }}
                
                .tab.active {{
                    background: var(--primary);
                    color: white;
                }}
                
                .tab-content {{
                    display: none;
                    background: white;
                    border-radius: 20px;
                    padding: 30px;
                    margin-bottom: 24px;
                    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
                }}
                
                .tab-content.active {{
                    display: block;
                    animation: fadeIn 0.5s ease;
                }}
                
                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(10px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}
                
                .stats-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                
                .stat-card {{
                    background: linear-gradient(135deg, var(--primary), #A78BFA);
                    color: white;
                    padding: 25px;
                    border-radius: 15px;
                    text-align: center;
                    box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);
                }}
                
                .stat-card.warning {{
                    background: linear-gradient(135deg, var(--warning), #FBBF24);
                }}
                
                .stat-card.success {{
                    background: linear-gradient(135deg, var(--success), #34D399);
                }}
                
                .stat-card.danger {{
                    background: linear-gradient(135deg, var(--danger), #F87171);
                }}
                
                .stat-card.info {{
                    background: linear-gradient(135deg, var(--info), #60A5FA);
                }}
                
                .stat-icon {{
                    font-size: 2.5rem;
                    margin-bottom: 15px;
                }}
                
                .stat-card h3 {{
                    font-size: 1.1rem;
                    margin-bottom: 8px;
                    opacity: 0.9;
                }}
                
                .stat-card .value {{
                    font-size: 2rem;
                    font-weight: bold;
                    margin-bottom: 5px;
                }}
                
                .stat-card .description {{
                    font-size: 0.9rem;
                    opacity: 0.8;
                }}
                
                .actions-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin: 25px 0;
                }}
                
                .btn {{
                    background: var(--primary);
                    color: white;
                    border: none;
                    padding: 16px 20px;
                    border-radius: 12px;
                    font-size: 15px;
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
                .btn-warning {{ background: var(--warning); }}
                .btn-danger {{ background: var(--danger); }}
                .btn-info {{ background: var(--info); }}
                
                .schedule-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin: 25px 0;
                }}
                
                .schedule-card {{
                    background: #F8FAFC;
                    border: 2px solid #E5E7EB;
                    border-radius: 15px;
                    padding: 20px;
                    transition: all 0.3s ease;
                }}
                
                .schedule-card:hover {{
                    border-color: var(--primary);
                    transform: translateY(-2px);
                }}
                
                .schedule-time {{
                    font-size: 1.1rem;
                    font-weight: bold;
                    color: var(--primary);
                    margin-bottom: 8px;
                }}
                
                .schedule-name {{
                    font-size: 1rem;
                    color: var(--dark);
                    margin-bottom: 12px;
                }}
                
                .schedule-actions {{
                    display: flex;
                    gap: 10px;
                }}
                
                .schedule-btn {{
                    flex: 1;
                    padding: 8px 12px;
                    border: none;
                    border-radius: 8px;
                    background: var(--primary);
                    color: white;
                    cursor: pointer;
                    font-size: 0.9rem;
                    transition: all 0.3s ease;
                }}
                
                .schedule-btn:hover {{
                    opacity: 0.9;
                    transform: translateY(-1px);
                }}
                
                .diagnostics-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin: 25px 0;
                }}
                
                .diagnostic-card {{
                    background: #F8FAFC;
                    border-radius: 15px;
                    padding: 20px;
                    border-left: 4px solid var(--primary);
                }}
                
                .diagnostic-card.success {{ border-left-color: var(--success); }}
                .diagnostic-card.warning {{ border-left-color: var(--warning); }}
                .diagnostic-card.danger {{ border-left-color: var(--danger); }}
                
                .diagnostic-header {{
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 15px;
                }}
                
                .diagnostic-icon {{
                    font-size: 1.5rem;
                }}
                
                .diagnostic-title {{
                    font-weight: 600;
                    color: var(--dark);
                }}
                
                .diagnostic-status {{
                    margin-left: auto;
                    padding: 4px 12px;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: 600;
                }}
                
                .status-success {{ background: #D1FAE5; color: var(--success); }}
                .status-warning {{ background: #FEF3C7; color: var(--warning); }}
                .status-danger {{ background: #FEE2E2; color: var(--danger); }}
                
                .diagnostic-description {{
                    color: var(--gray);
                    font-size: 0.9rem;
                    margin-bottom: 15px;
                }}
                
                .diagnostic-actions {{
                    display: flex;
                    gap: 10px;
                }}
                
                .manual-input {{
                    width: 100%;
                    min-height: 150px;
                    padding: 15px;
                    border: 2px solid #E5E7EB;
                    border-radius: 12px;
                    font-family: inherit;
                    font-size: 14px;
                    resize: vertical;
                    margin-bottom: 15px;
                }}
                
                .manual-input:focus {{
                    outline: none;
                    border-color: var(--primary);
                }}
                
                .time-info {{
                    background: #F8FAFC;
                    border-radius: 12px;
                    padding: 15px;
                    margin: 20px 0;
                    text-align: center;
                }}
                
                .time-info p {{
                    margin: 5px 0;
                    color: var(--gray);
                }}
                
                .footer {{
                    text-align: center;
                    margin-top: 40px;
                    color: white;
                    opacity: 0.8;
                }}
                
                @media (max-width: 768px) {{
                    .container {{ padding: 15px; }}
                    .header {{ padding: 20px; }}
                    .header h1 {{ font-size: 2rem; }}
                    .tabs {{ flex-direction: column; }}
                    .tab {{ min-width: auto; }}
                    .stats-grid {{ grid-template-columns: 1fr; }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎪 Умный дашборд @ppsupershef</h1>
                    <p>Полное управление контентом для Клуба Осознанного Долголетия</p>
                    <div style="margin-top: 15px; padding: 10px; background: #F0F9FF; border-radius: 10px; display: inline-block;">
                        <strong>🕐 Автопостинг активен:</strong> 5 постов в день • 07:00, 12:00, 17:00, 19:00, 21:00
                    </div>
                </div>
                
                <div class="tabs">
                    <button class="tab active" onclick="openTab('dashboard')">
                        📊 Дашборд
                    </button>
                    <button class="tab" onclick="openTab('meals')">
                        🍽️ Приемы пищи
                    </button>
                    <button class="tab" onclick="openTab('schedule')">
                        🗓️ Расписание
                    </button>
                    <button class="tab" onclick="openTab('analytics')">
                        📈 Статистика
                    </button>
                    <button class="tab" onclick="openTab('diagnostics')">
                        🔧 Диагностика
                    </button>
                    <button class="tab" onclick="openTab('manual')">
                        ✍️ Ручная отправка
                    </button>
                </div>
                
                <!-- ВКЛАДКА ДАШБОРДА -->
                <div id="dashboard" class="tab-content active">
                    <h2>📊 Обзор системы</h2>
                    
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-icon">👥</div>
                            <h3>Подписчики</h3>
                            <div class="value">{member_count}</div>
                            <div class="description">Активная аудитория</div>
                        </div>
                        
                        <div class="stat-card success">
                            <div class="stat-icon">🤖</div>
                            <h3>Статус бота</h3>
                            <div class="value">{bot_status}</div>
                            <div class="description">{bot_info.get('bot_username', 'Неизвестен')}</div>
                        </div>
                        
                        <div class="stat-card {'success' if content_gen.yandex_key else 'warning'}">
                            <div class="stat-icon">🧠</div>
                            <h3>Yandex GPT</h3>
                            <div class="value">{ai_status}</div>
                            <div class="description">{"Генерация AI активна" if content_gen.yandex_key else "Требуется настройка"}</div>
                        </div>
                        
                        <div class="stat-card info">
                            <div class="stat-icon">📅</div>
                            <h3>Сегодня</h3>
                            <div class="value">{day_name_ru}</div>
                            <div class="description">{day_theme}</div>
                        </div>
                    </div>
                    
                    <div class="time-info">
                        <p><strong>🕐 Текущее время:</strong> {current_times['kemerovo_time']} (Кемерово)</p>
                        <p><strong>🌍 Серверное время:</strong> {current_times['server_time']} (UTC)</p>
                        <p><strong>🚀 Автопостинг:</strong> Активен • Следующая проверка: через 55 сек</p>
                    </div>
                    
                    <div class="actions-grid">
                        <button class="btn btn-success" onclick="sendMeal('breakfast')">
                            🍳 AI Завтрак
                        </button>
                        <button class="btn" onclick="sendContent('shopping')">
                            🛒 Чек-лист
                        </button>
                        <button class="btn btn-warning" onclick="sendMeal('dessert')">
                            🍰 Умный десерт
                        </button>
                        <button class="btn btn-info" onclick="sendMeal('advice')">
                            💡 Советы экспертов
                        </button>
                    </div>
                </div>
                
                <!-- ВКЛАДКА ПРИЕМОВ ПИЩИ -->
                <div id="meals" class="tab-content">
                    <h2>🍽️ Генерация контента</h2>
                    <p style="color: var(--gray); margin-bottom: 25px;">AI-генерация рецептов и советов</p>
                    
                    <div class="actions-grid">
                        <button class="btn" onclick="sendMeal('breakfast')">
                            🍳 Завтрак
                        </button>
                        <button class="btn btn-success" onclick="sendMeal('lunch')">
                            🍲 Обед
                        </button>
                        <button class="btn btn-warning" onclick="sendMeal('dinner')">
                            🌙 Ужин
                        </button>
                        <button class="btn btn-info" onclick="sendMeal('dessert')">
                            🍰 Умный десерт
                        </button>
                        <button class="btn" style="background: #8B5CF6;" onclick="sendMeal('advice')">
                            💡 Советы экспертов
                        </button>
                    </div>
                    
                    <div style="background: #F0F9FF; border-radius: 15px; padding: 20px; margin: 25px 0;">
                        <h3 style="color: var(--info); margin-bottom: 15px;">🎯 Сегодняшний контент ({day_name_ru})</h3>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                            <div style="background: white; padding: 15px; border-radius: 10px; text-align: center;">
                                <div style="font-size: 2rem; margin-bottom: 10px;">🍳</div>
                                <strong>Завтрак</strong>
                                <p style="color: var(--gray); font-size: 0.9rem; margin-top: 5px;">07:00 • {day_theme}</p>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px; text-align: center;">
                                <div style="font-size: 2rem; margin-bottom: 10px;">🍲</div>
                                <strong>Обед</strong>
                                <p style="color: var(--gray); font-size: 0.9rem; margin-top: 5px;">12:00 • Энергия</p>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px; text-align: center;">
                                <div style="font-size: 2rem; margin-bottom: 10px;">🍰</div>
                                <strong>Десерт</strong>
                                <p style="color: var(--gray); font-size: 0.9rem; margin-top: 5px;">17:00 • Умное наслаждение</p>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px; text-align: center;">
                                <div style="font-size: 2rem; margin-bottom: 10px;">🌙</div>
                                <strong>Ужин</strong>
                                <p style="color: var(--gray); font-size: 0.9rem; margin-top: 5px;">19:00 • Восстановление</p>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px; text-align: center;">
                                <div style="font-size: 2rem; margin-bottom: 10px;">💡</div>
                                <strong>Советы</strong>
                                <p style="color: var(--gray); font-size: 0.9rem; margin-top: 5px;">21:00 • {day_theme}</p>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- ВКЛАДКА РАСПИСАНИЯ -->
                <div id="schedule" class="tab-content">
                    <h2>🗓️ Расписание публикаций</h2>
                    <p style="color: var(--gray); margin-bottom: 25px;">Все время указано по Кемерово (UTC+7)</p>
                    
                    <div style="background: #F0F9FF; border-radius: 15px; padding: 20px; margin-bottom: 25px;">
                        <h3 style="color: var(--info); margin-bottom: 15px;">📅 Сегодня: {day_name_ru} • {day_theme}</h3>
                        <div class="schedule-grid">
                            {"".join([f'''
                            <div class="schedule-card">
                                <div class="schedule-time">🕐 {item["time"]}</div>
                                <div class="schedule-name">{item["name"]}</div>
                                <div class="schedule-actions">
                                    <button class="schedule-btn" style="background: var(--success);" onclick="sendMeal('{item["type"]}')">
                                        📤 Отправить сейчас
                                    </button>
                                </div>
                            </div>
                            ''' for item in today_schedule])}
                        </div>
                    </div>
                    
                    <h3 style="margin-bottom: 20px;">📋 Полное недельное расписание</h3>
                    <div style="background: white; border-radius: 15px; padding: 20px; border: 2px solid #E5E7EB;">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px;">
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--primary); margin-bottom: 10px;">Понедельник</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">🧠 Нейропитание</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--warning); margin-bottom: 10px;">Вторник</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">⚡ Энергия</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--success); margin-bottom: 10px;">Среда</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">🛡️ Долголетие</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: #EC4899; margin-bottom: 10px;">Четверг</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">🍽️ Гастрономия</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--info); margin-bottom: 10px;">Пятница</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">📊 Аналитика</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--primary); margin-bottom: 10px;">Суббота</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">🛒 Покупки</div>
                            </div>
                            <div style="text-align: center;">
                                <div style="font-weight: bold; color: var(--warning); margin-bottom: 10px;">Воскресенье</div>
                                <div style="font-size: 0.9rem; color: var(--gray);">📈 Ритуалы</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- ВКЛАДКА СТАТИСТИКИ -->
                <div id="analytics" class="tab-content">
                    <h2>📈 Аналитика канала</h2>
                    
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-icon">👥</div>
                            <h3>Подписчики</h3>
                            <div class="value">{member_count}</div>
                            <div class="description">Текущая аудитория</div>
                        </div>
                        
                        <div class="stat-card success">
                            <div class="stat-icon">📊</div>
                            <h3>Контент-план</h3>
                            <div class="value">35/нед</div>
                            <div class="description">Постов в неделю</div>
                        </div>
                        
                        <div class="stat-card info">
                            <div class="stat-icon">🎯</div>
                            <h3>Охват</h3>
                            <div class="value">100%</div>
                            <div class="description">Качество контента</div>
                        </div>
                        
                        <div class="stat-card warning">
                            <div class="stat-icon">💫</div>
                            <h3>Философия</h3>
                            <div class="value">Осознанность</div>
                            <div class="description">Основной фокус</div>
                        </div>
                    </div>
                    
                    <div class="actions-grid">
                        <button class="btn btn-success" onclick="sendAnalyticsReport()">
                            📊 Отправить отчет в канал
                        </button>
                        <button class="btn" onclick="updateStats()">
                            🔄 Обновить статистику
                        </button>
                        <button class="btn btn-info" onclick="checkSchedulerStatus()">
                            🕐 Статус планировщика
                        </button>
                    </div>
                    
                    <div style="background: #F0F9FF; border-radius: 15px; padding: 25px; margin-top: 25px;">
                        <h3 style="color: var(--info); margin-bottom: 20px;">📋 Детальная статистика</h3>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <div style="font-weight: bold; color: var(--dark);">Канал</div>
                                <div style="color: var(--gray); font-size: 0.9rem;">@{channel_stats.get('channel_username', 'Unknown')}</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <div style="font-weight: bold; color: var(--dark);">Название</div>
                                <div style="color: var(--gray); font-size: 0.9rem;">{channel_stats.get('channel_title', 'Unknown')}</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <div style="font-weight: bold; color: var(--dark);">Бот</div>
                                <div style="color: var(--gray); font-size: 0.9rem;">@{bot_info.get('bot_username', 'Unknown')}</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <div style="font-weight: bold; color: var(--dark);">Статус</div>
                                <div style="color: var(--gray); font-size: 0.9rem;">{bot_status}</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- ВКЛАДКА ДИАГНОСТИКИ -->
                <div id="diagnostics" class="tab-content">
                    <h2>🔧 Диагностика системы</h2>
                    <p style="color: var(--gray); margin-bottom: 25px;">Проверка всех компонентов системы и устранение ошибок</p>
                    
                    <div class="diagnostics-grid">
                        <div class="diagnostic-card {'success' if bot_info.get('status') == 'success' else 'danger'}">
                            <div class="diagnostic-header">
                                <div class="diagnostic-icon">🤖</div>
                                <div class="diagnostic-title">Telegram Bot</div>
                                <div class="diagnostic-status {'status-success' if bot_info.get('status') == 'success' else 'status-danger'}">
                                    {bot_status}
                                </div>
                            </div>
                            <div class="diagnostic-description">
                                Проверка подключения бота к Telegram API
                            </div>
                            <div class="diagnostic-actions">
                                <button class="schedule-btn" style="background: var(--info);" onclick="testConnection()">
                                    Тестировать
                                </button>
                            </div>
                        </div>
                        
                        <div class="diagnostic-card {'success' if content_gen.yandex_key else 'warning'}">
                            <div class="diagnostic-header">
                                <div class="diagnostic-icon">🧠</div>
                                <div class="diagnostic-title">Yandex GPT API</div>
                                <div class="diagnostic-status {'status-success' if content_gen.yandex_key else 'status-warning'}">
                                    {ai_status}
                                </div>
                            </div>
                            <div class="diagnostic-description">
                                {"API ключ настроен, генерация контента доступна" if content_gen.yandex_key else "Требуется настройка API ключа"}
                            </div>
                            <div class="diagnostic-actions">
                                <button class="schedule-btn" style="background: var(--warning);" onclick="alert('Добавьте YANDEX_GPT_API_KEY в файл .env')">
                                    Инструкция
                                </button>
                            </div>
                        </div>
                        
                        <div class="diagnostic-card success">
                            <div class="diagnostic-header">
                                <div class="diagnostic-icon">🌍</div>
                                <div class="diagnostic-title">Часовые пояса</div>
                                <div class="diagnostic-status status-success">
                                    ✅ Настроены
                                </div>
                            </div>
                            <div class="diagnostic-description">
                                Сервер: UTC, Кемерово: Asia/Novokuznetsk
                            </div>
                            <div class="diagnostic-actions">
                                <button class="schedule-btn" style="background: var(--info);" onclick="showTimeInfo()">
                                    Время
                                </button>
                            </div>
                        </div>
                        
                        <div class="diagnostic-card success">
                            <div class="diagnostic-header">
                                <div class="diagnostic-icon">📊</div>
                                <div class="diagnostic-title">Канал</div>
                                <div class="diagnostic-status status-success">
                                    ✅ Доступен
                                </div>
                            </div>
                            <div class="diagnostic-description">
                                {channel_stats.get('channel_title', 'Канал доступен')}
                            </div>
                            <div class="diagnostic-actions">
                                <button class="schedule-btn" style="background: var(--info);" onclick="testChannel()">
                                    Проверить
                                </button>
                            </div>
                        </div>
                    </div>
                    
                    <div class="actions-grid" style="margin-top: 30px;">
                        <button class="btn btn-warning" onclick="runFullDiagnostics()">
                            🔧 Полная диагностика
                        </button>
                        <button class="btn btn-success" onclick="sendTestMessage()">
                            📨 Тестовое сообщение
                        </button>
                        <button class="btn btn-info" onclick="showDebugInfo()">
                            🐛 Отладочная информация
                        </button>
                    </div>
                </div>
                
                <!-- ВКЛАДКА РУЧНОЙ ОТПРАВКИ -->
                <div id="manual" class="tab-content">
                    <h2>✍️ Ручная отправка сообщений</h2>
                    <p style="color: var(--gray); margin-bottom: 25px;">Отправка произвольного контента в канал</p>
                    
                    <textarea 
                        id="manualContent" 
                        class="manual-input" 
                        placeholder="Введите текст сообщения для Telegram... Поддерживается HTML-разметка для форматирования"
                    ></textarea>
                    
                    <div class="actions-grid">
                        <button class="btn btn-success" onclick="sendManualContent()">
                            📤 Отправить в канал
                        </button>
                        <button class="btn" onclick="previewManualContent()">
                            👁️ Предпросмотр
                        </button>
                        <button class="btn btn-warning" onclick="clearManualContent()">
                            🗑️ Очистить
                        </button>
                    </div>
                    
                    <div style="background: #F0F9FF; border-radius: 15px; padding: 20px; margin-top: 25px;">
                        <h3 style="color: var(--info); margin-bottom: 15px;">💡 Советы по форматированию</h3>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <strong>Жирный текст</strong>
                                <div style="color: var(--gray); font-size: 0.9rem;">&lt;b&gt;текст&lt;/b&gt;</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <strong>Курсив</strong>
                                <div style="color: var(--gray); font-size: 0.9rem;">&lt;i&gt;текст&lt;/i&gt;</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <strong>Ссылка</strong>
                                <div style="color: var(--gray); font-size: 0.9rem;">&lt;a href="url"&gt;текст&lt;/a&gt;</div>
                            </div>
                            <div style="background: white; padding: 15px; border-radius: 10px;">
                                <strong>Эмодзи</strong>
                                <div style="color: var(--gray); font-size: 0.9rem;">🎪 🧠 ⚡ 🛡️ 🍰 💡</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="footer">
                    <p>🎪 Клуб Осознанного Долголетия @ppsupershef</p>
                    <p>💫 Питание как инвестиция в качество жизни • 🧠 Нейронаука • 🛡️ Долголетие • 🍰 Умные десерты • 💡 Осознанность</p>
                </div>
            </div>
            
            <script>
                function openTab(tabName) {{
                    // Скрыть все вкладки
                    document.querySelectorAll('.tab-content').forEach(tab => {{
                        tab.classList.remove('active');
                    }});
                    
                    // Убрать активный класс со всех кнопок
                    document.querySelectorAll('.tab').forEach(tab => {{
                        tab.classList.remove('active');
                    }});
                    
                    // Показать выбранную вкладку
                    document.getElementById(tabName).classList.add('active');
                    
                    // Добавить активный класс к выбранной кнопке
                    event.currentTarget.classList.add('active');
                }}
                
                async function testConnection() {{
                    try {{
                        const response = await fetch('/health');
                        const data = await response.json();
                        if (data.status === 'healthy') {{
                            alert('✅ Все системы работают нормально!\\\\n🤖 Бот: ' + data.bot_username + '\\\\n🧠 Yandex GPT: ' + data.ai_status);
                        }} else {{
                            alert('❌ Есть проблемы с системой: ' + data.message);
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
                
                async function sendMeal(mealType) {{
                    try {{
                        const response = await fetch(`/send-meal/${{mealType}}`);
                        const data = await response.json();
                        if (data.status === 'success') {{
                            const mealNames = {{
                                'breakfast': 'Завтрак',
                                'lunch': 'Обед',
                                'dinner': 'Ужин', 
                                'dessert': 'Умный десерт',
                                'advice': 'Советы экспертов'
                            }};
                            alert(`✅ ${{mealNames[mealType] || 'Контент'}} успешно отправлен!`);
                        }} else {{
                            alert('❌ Ошибка отправки: ' + (data.message || 'Неизвестная ошибка'));
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка сети при отправке');
                    }}
                }}
                
                async function sendAnalyticsReport() {{
                    try {{
                        const response = await fetch('/send-analytics-report');
                        const data = await response.json();
                        if (data.status === 'success') {{
                            alert('✅ Отчет статистики отправлен в канал!');
                        }} else {{
                            alert('❌ Ошибка отправки отчета');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка сети при отправке отчета');
                    }}
                }}
                
                async function runFullDiagnostics() {{
                    try {{
                        const response = await fetch('/full-diagnostics');
                        const data = await response.json();
                        
                        let message = '🔧 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ\\\\n\\\\n';
                        
                        if (data.bot_status === 'success') {{
                            message += '✅ Бот: Активен (' + data.bot_username + ')\\\\n';
                        }} else {{
                            message += '❌ Бот: Ошибка (' + data.bot_message + ')\\\\n';
                        }}
                        
                        if (data.ai_available) {{
                            message += '✅ Yandex GPT: Доступен\\\\n';
                        }} else {{
                            message += '⚠️ Yandex GPT: Не настроен\\\\n';
                        }}
                        
                        if (data.channel_status === 'success') {{
                            message += '✅ Канал: Доступен (' + data.member_count + ' подписчиков)\\\\n';
                        }} else {{
                            message += '❌ Канал: Ошибка доступа\\\\n';
                        }}
                        
                        message += '✅ Часовые пояса: Настроены\\\\n';
                        message += '✅ Веб-интерфейс: Работает\\\\n';
                        
                        alert(message);
                        
                    }} catch (error) {{
                        alert('❌ Ошибка диагностики: ' + error);
                    }}
                }}
                
                async function sendTestMessage() {{
                    try {{
                        const response = await fetch('/test-channel');
                        const data = await response.json();
                        if (data.status === 'success') {{
                            alert('✅ Тестовое сообщение отправлено в канал!');
                        }} else {{
                            alert('❌ Ошибка отправки тестового сообщения');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка сети при отправке теста');
                    }}
                }}
                
                async function checkSchedulerStatus() {{
                    try {{
                        const response = await fetch('/scheduler-status');
                        const data = await response.json();
                        
                        if (data.status === 'active') {{
                            let message = '🕐 СТАТУС ПЛАНИРОВЩИКА\\\\n\\\\n';
                            message += '✅ Статус: Активен\\\\n';
                            message += '🕐 Текущее время: ' + data.current_time_kemerovo + '\\\\n';
                            message += '📅 День недели: ' + data.current_weekday + '\\\\n';
                            message += '⏱️ Следующая проверка: ' + data.next_check + '\\\\n\\\\n';
                            message += '📋 РАСПИСАНИЕ:\\\\n';
                            message += '• 🍳 Завтрак: ' + data.schedule.breakfast + '\\\\n';
                            message += '• 🍲 Обед: ' + data.schedule.lunch + '\\\\n';
                            message += '• 🍰 Десерт: ' + data.schedule.dessert + '\\\\n';
                            message += '• 🌙 Ужин: ' + data.schedule.dinner + '\\\\n';
                            message += '• 💡 Советы: ' + data.schedule.advice + '\\\\n';
                            message += '• 🛒 Чек-лист: ' + data.schedule.shopping_list + '\\\\n';
                            message += '• 📊 Аналитика: ' + data.schedule.analytics;
                            
                            alert(message);
                        }} else {{
                            alert('❌ Планировщик не активен');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка проверки статуса планировщика');
                    }}
                }}
                
                async function sendManualContent() {{
                    const content = document.getElementById('manualContent').value;
                    if (!content) {{
                        alert('Введите текст сообщения');
                        return;
                    }}
                
                    try {{
                        const response = await fetch('/send-manual-content', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ content: content }})
                        }});
                        
                        const data = await response.json();
                        if (data.status === 'success') {{
                            alert('✅ Сообщение отправлено в канал!');
                            document.getElementById('manualContent').value = '';
                        }} else {{
                            alert('❌ Ошибка: ' + data.message);
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка сети при отправке');
                    }}
                }}
                
                function previewManualContent() {{
                    const content = document.getElementById('manualContent').value;
                    if (!content) {{
                        alert('Введите текст для предпросмотра');
                        return;
                    }}
                    
                    const previewWindow = window.open('', '_blank');
                    previewWindow.document.write(`
                        <html>
                            <head>
                                <title>Предпросмотр сообщения</title>
                                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                                <style>
                                    body {{ 
                                        font-family: Arial, sans-serif; 
                                        padding: 20px;
                                        background: #f5f5f5;
                                    }}
                                    .preview-container {{
                                        background: white;
                                        padding: 20px;
                                        border-radius: 10px;
                                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                                    }}
                                </style>
                            </head>
                            <body>
                                <div class="preview-container">
                                    <h3>👁️ Предпросмотр сообщения</h3>
                                    <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                                        ${{content}}
                                    </div>
                                    <button onclick="window.close()" style="margin-top: 20px; padding: 10px 20px; background: #8B5CF6; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                        Закрыть
                                    </button>
                                </div>
                            </body>
                        </html>
                    `);
                }}
                
                function clearManualContent() {{
                    if (confirm('Очистить текстовое поле?')) {{
                        document.getElementById('manualContent').value = '';
                    }}
                }}
                
                function showTimeInfo() {{
                    alert('🕐 Информация о времени:\\\\n\\\\nСервер: UTC\\\\nКемерово: Asia/Novokuznetsk (UTC+7)\\\\n\\\\nВсе расписания указаны по времени Кемерово.');
                }}
                
                function showDebugInfo() {{
                    alert('🐛 Отладочная информация:\\\\n\\\\nДля получения детальной информации откройте консоль разработчика (F12) и проверьте вкладку Console.');
                    console.log('🔧 Отладочная информация системы:');
                    console.log('- Текущее время:', new Date().toString());
                    console.log('- User Agent:', navigator.userAgent);
                    console.log('- Screen:', screen.width + 'x' + screen.height);
                }}
                
                async function testChannel() {{
                    try {{
                        const response = await fetch('/test-channel');
                        const data = await response.json();
                        if (data.status === 'success') {{
                            alert('✅ Канал доступен, тестовое сообщение отправлено!');
                        }} else {{
                            alert('❌ Проблемы с доступом к каналу');
                        }}
                    }} catch (error) {{
                        alert('❌ Ошибка проверки канала');
                    }}
                }}
                
                async function updateStats() {{
                    location.reload();
                }}
                
                // Показать уведомление о загрузке
                window.addEventListener('load', function() {{
                    console.log('✅ Умный дашборд загружен');
                    console.log('🎪 Клуб Осознанного Долголетия @ppsupershef');
                    console.log('🍰 Умные десерты добавлены в расписание на 17:00');
                    console.log('💡 Советы экспертов добавлены в расписание на 21:00');
                    console.log('🕐 Автоматический планировщик активен');
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

# 📊 Дополнительные маршруты для нового функционала
@app.route('/send-meal/<meal_type>')
@rate_limit()
def send_meal(meal_type):
    """Отправка конкретного приема пищи"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        
        content = content_gen.generate_daily_content(weekday, meal_type)
        success = telegram.send_message(content)
        
        meal_names = {
            'breakfast': 'завтрак',
            'lunch': 'обед', 
            'dinner': 'ужин',
            'dessert': 'умный десерт',
            'advice': 'советы экспертов'
        }
        
        return jsonify({
            "status": "success" if success else "error",
            "message": f"{meal_names.get(meal_type, 'контент')} отправлен",
            "ai_generated": bool(content_gen.yandex_key)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-analytics-report')
@rate_limit()
def send_analytics_report():
    """Отправка отчета аналитики в канал"""
    try:
        telegram = SecureTelegramManager()
        analytics = ChannelAnalytics()
        
        report = analytics.generate_analytics_report()
        success = telegram.send_message(report)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "Отчет аналитики отправлен"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/full-diagnostics')
def full_diagnostics():
    """Полная диагностика системы"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        analytics = ChannelAnalytics()
        
        bot_info = telegram.test_connection()
        channel_stats = analytics.get_full_stats()
        
        return jsonify({
            "status": "success",
            "bot_status": bot_info.get('status'),
            "bot_username": bot_info.get('bot_username'),
            "bot_message": bot_info.get('message', 'OK'),
            "ai_available": bool(content_gen.yandex_key),
            "channel_status": channel_stats.get('status'),
            "member_count": channel_stats.get('member_count', 0),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/scheduler-status')
def scheduler_status():
    """Статус автоматического планировщика"""
    try:
        now = datetime.now(config.KEMEROVO_TIMEZONE)
        current_time = now.strftime('%H:%M')
        weekday = now.strftime('%A').lower()
        
        # Русские названия дней
        weekdays_ru = {
            'monday': 'Понедельник',
            'tuesday': 'Вторник', 
            'wednesday': 'Среда',
            'thursday': 'Четверг',
            'friday': 'Пятница',
            'saturday': 'Суббота',
            'sunday': 'Воскресенье'
        }
        
        return jsonify({
            "status": "active",
            "current_time_kemerovo": current_time,
            "current_weekday": weekdays_ru.get(weekday, weekday),
            "next_check": "через 55 секунд",
            "schedule": {
                "breakfast": "07:00",
                "lunch": "12:00",
                "dessert": "17:00", 
                "dinner": "19:00",
                "advice": "21:00",
                "shopping_list": "Суббота 10:00",
                "analytics": "Воскресенье 11:00"
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# 🔧 Существующие маршруты (остаются без изменений)
@app.route('/health')
def health_check():
    """Проверка здоровья системы"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        bot_info = telegram.test_connection()
        
        return jsonify({
            "status": "healthy" if bot_info.get('status') == 'success' else "degraded",
            "bot_status": bot_info.get('status'),
            "bot_username": bot_info.get('bot_username'),
            "ai_status": "available" if content_gen.yandex_key else "unavailable",
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
🧠 Yandex GPT: {"✅ Подключен" if config.YANDEX_GPT_API_KEY else "⚠️ Не настроен"}
📊 Контент-план: 35 постов/неделю
🍰 Умные десерты: 17:00 ежедневно
💡 Советы экспертов: 21:00 ежедневно
🎯 Философия: Питание как инвестиция в качество жизни

💫 <b>РАСПИСАНИЕ КОНТЕНТА:</b>
• 🍳 07:00 - Завтрак
• 🍲 12:00 - Обед  
• 🍰 17:00 - УМНЫЙ ДЕСЕРТ
• 🌙 19:00 - Ужин
• 💡 21:00 - СОВЕТЫ ЭКСПЕРТОВ

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
    """Отправка завтрака сгенерированного через AI"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        
        content = content_gen.generate_daily_content(weekday, "breakfast")
        success = telegram.send_message(content)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "AI-завтрак отправлен",
            "ai_generated": bool(content_gen.yandex_key)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-shopping-list')
@rate_limit()
def send_shopping_list():
    """Отправка чек-листа покупок"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        
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
    """Отправка советов экспертов через AI"""
    try:
        telegram = SecureTelegramManager()
        content_gen = AIContentGenerator()
        
        current_time = datetime.now(config.KEMEROVO_TIMEZONE)
        weekday = current_time.strftime('%A').lower()
        
        content = content_gen.generate_daily_content(weekday, "advice")
        success = telegram.send_message(content)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": "AI-советы отправлены",
            "ai_generated": bool(content_gen.yandex_key)
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

# 🚀 ЗАПУСК ПРИЛОЖЕНИЯ С АВТОМАТИЧЕСКИМ ПЛАНИРОВЩИКОМ
if __name__ == '__main__':
    logger.info("🚀 Запуск умного дашборда с AI-генерацией контента")
    logger.info("🍰 Умные десерты добавлены в расписание на 17:00")
    logger.info("💡 Советы экспертов добавлены в расписание на 21:00")
    
    # Проверка обязательных компонентов
    telegram = SecureTelegramManager()
    content_gen = AIContentGenerator()
    
    bot_test = telegram.test_connection()
    if bot_test.get('status') == 'success':
        logger.info(f"✅ Бот @{bot_test.get('bot_username')} готов к работе")
    else:
        logger.warning(f"⚠️ Проблемы с ботом: {bot_test.get('message')}")
    
    if content_gen.yandex_key:
        logger.info("✅ Yandex GPT настроен и готов к генерации контента")
    else:
        logger.warning("⚠️ Yandex GPT не настроен - будет использоваться фолбэк-контент")
    
    # Запуск автоматического планировщика
    scheduler = AutoScheduler()
    scheduler_thread = Thread(target=scheduler.run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("✅ Автоматический планировщик запущен в фоновом режиме")
    
    # Информация о расписании
    logger.info("📅 Расписание автоматических публикаций:")
    logger.info("   🍳 Завтрак: 07:00")
    logger.info("   🍲 Обед: 12:00") 
    logger.info("   🍰 Десерт: 17:00")
    logger.info("   🌙 Ужин: 19:00")
    logger.info("   💡 Советы: 21:00")
    logger.info("   🛒 Чек-лист: Суббота 10:00")
    logger.info("   📊 Аналитика: Воскресенье 11:00")
    
    app.run(host='0.0.0.0', port=10000, debug=False)
