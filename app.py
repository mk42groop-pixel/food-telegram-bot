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
import signal
import sys
import atexit

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ========== RENDER-COMPATIBLE CACHE SYSTEM ==========

class RenderCompatibleCache:
    def __init__(self, ttl_days=7):
        self.cache = {}
        self.cache_timestamps = {}
        self.cache_ttl = ttl_days * 24 * 3600
        self.cache_lock = Lock()
        self._storage_type = "memory"
        
        logger.info(f"💾 Кэш инициализирован в оперативной памяти (TTL: {ttl_days} дней)")
    
    def get(self, key):
        """Получаем значение из кэша с проверкой TTL"""
        with self.cache_lock:
            if key in self.cache:
                create_time = self.cache_timestamps.get(key, 0)
                current_time = time.time()
                
                if current_time - create_time < self.cache_ttl:
                    logger.debug(f"✅ Кэш попадание: {key}")
                    return self.cache[key]
                else:
                    # Удаляем просроченную запись
                    del self.cache[key]
                    del self.cache_timestamps[key]
                    logger.debug(f"🧹 Удален просроченный кэш: {key}")
        return None
    
    def set(self, key, value):
        """Сохраняем значение в кэш"""
        with self.cache_lock:
            self.cache[key] = value
            self.cache_timestamps[key] = time.time()
            logger.debug(f"💾 Сохранен в кэш: {key}")
    
    def cleanup_expired(self):
        """Очистка просроченных записей"""
        current_time = time.time()
        expired_keys = []
        
        with self.cache_lock:
            for key, timestamp in self.cache_timestamps.items():
                if current_time - timestamp > self.cache_ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
                del self.cache_timestamps[key]
        
        if expired_keys:
            logger.info(f"🧹 Очищено просроченных записей: {len(expired_keys)}")
        return len(expired_keys)
    
    def clear_all(self):
        """Полная очистка кэша"""
        with self.cache_lock:
            count = len(self.cache)
            self.cache.clear()
            self.cache_timestamps.clear()
            logger.info(f"🧹 Полная очистка кэша: удалено {count} записей")
            return count
    
    def get_stats(self):
        """Статистика кэша"""
        with self.cache_lock:
            total_size = len(self.cache)
            current_time = time.time()
            
            # Считаем скоро истекающие записи (менее 24 часов)
            expiring_soon = 0
            for timestamp in self.cache_timestamps.values():
                if current_time - timestamp > (self.cache_ttl - 86400):
                    expiring_soon += 1
            
            # Примерный расчет использования памяти
            memory_usage = sum(len(str(v)) for v in self.cache.values()) / 1024 / 1024
            
            return {
                "total_entries": total_size,
                "expiring_soon": expiring_soon,
                "storage_type": self._storage_type,
                "memory_usage_mb": round(memory_usage, 2)
            }

# ========== УСИЛЕННАЯ СИСТЕМА KEEP-ALIVE ==========

class EnhancedKeepAlive:
    def __init__(self):
        self.ping_count = 0
        self.last_ping_time = None
        self.failed_pings = 0
        self.max_failed_pings = 3

    def multi_layer_ping(self):
        """Многоуровневый пинг для предотвращения сна"""
        try:
            port = int(os.environ.get('PORT', 8080))
            current_time = datetime.now()

            # Уровень 1: Пинг здоровья
            health_response = requests.get(f"http://localhost:{port}/health", timeout=5)

            # Уровень 2: Пинг дашборда
            dashboard_response = requests.get(f"http://localhost:{port}/", timeout=10)

            # Уровень 3: Активация планировщика
            schedule.run_pending()

            self.ping_count += 1
            self.last_ping_time = current_time
            self.failed_pings = 0

            logger.info(f"✅ Keep-alive #{self.ping_count} | Health: {health_response.status_code}")

            # Периодический отчет
            if self.ping_count % 10 == 0:
                self._log_uptime_report()

        except Exception as e:
            self.failed_pings += 1
            logger.warning(f"⚠️ Keep-alive ошибка #{self.failed_pings}: {e}")

            if self.failed_pings >= self.max_failed_pings:
                logger.error("🚨 КРИТИЧЕСКАЯ ОШИБКА: Слишком много failed pings!")
                self._emergency_restart()

    def _log_uptime_report(self):
        """Периодический отчет о работе"""
        jobs = schedule.get_jobs()
        logger.info(f"📊 Keep-alive отчет: {self.ping_count} пингов | Заданий: {len(jobs)}")

    def _emergency_restart(self):
        """Аварийный перезапуск приложения"""
        logger.critical("🔄 АВАРИЙНЫЙ ПЕРЕЗАПУСК СИСТЕМЫ...")
        os.execv(sys.executable, ['python'] + sys.argv)

# Инициализация enhanced keep-alive
enhanced_keep_alive = EnhancedKeepAlive()

def start_enhanced_keep_alive():
    """Запуск усиленной системы keep-alive"""
    def keep_alive_cycle():
        while True:
            try:
                enhanced_keep_alive.multi_layer_ping()
                time.sleep(180)  # 3 минуты
            except Exception as e:
                logger.error(f"💥 Ошибка в keep-alive цикле: {e}")
                time.sleep(60)

    keep_alive_thread = Thread(target=keep_alive_cycle, daemon=True)
    keep_alive_thread.start()
    logger.info("🚀 Keep-alive система запущена")

# ========== СИСТЕМА БЕЗОПАСНОСТИ ==========

class SecurityManager:
    def __init__(self):
        self.rate_limits = {}
        self.max_requests_per_minute = 30
        
    def rate_limit_check(self, identifier):
        """Проверка ограничения частоты запросов"""
        now = time.time()
        window = 60
        
        if identifier not in self.rate_limits:
            self.rate_limits[identifier] = []
        
        self.rate_limits[identifier] = [
            req_time for req_time in self.rate_limits[identifier] 
            if now - req_time < window
        ]
        
        if len(self.rate_limits[identifier]) >= self.max_requests_per_minute:
            return False
            
        self.rate_limits[identifier].append(now)
        return True
    
    def validate_content(self, content):
        """Валидация контента перед отправкой"""
        if len(content) > 4000:
            return False, "Слишком длинное сообщение"
            
        forbidden_patterns = [
            r'http[s]?://(?!ppsupershef)',
            r'@(?!ppsupershef)',
        ]
        
        for pattern in forbidden_patterns:
            if re.search(pattern, content):
                return False, "Обнаружены запрещенные паттерны"
                
        return True, "OK"

def require_auth(f):
    """Декоратор для аутентификации"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        expected_secret = os.getenv('API_SECRET')
        
        if not auth_header or not expected_secret:
            return jsonify({"status": "error", "message": "Auth required"}), 401
            
        if auth_header != f"Bearer {expected_secret}":
            return jsonify({"status": "error", "message": "Invalid token"}), 401
            
        return f(*args, **kwargs)
    return decorated

def rate_limit(f):
    """Декоратор для ограничения частоты запросов"""
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        
        if not security_manager.rate_limit_check(client_ip):
            return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429
            
        return f(*args, **kwargs)
    return decorated

# ========== КОНФИГУРАЦИЯ ==========

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHANNEL = os.getenv('TELEGRAM_CHANNEL', '@ppsupershef')
    TELEGRAM_GROUP = os.getenv('TELEGRAM_GROUP', '@ppsupershef_chat')
    YANDEX_GPT_API_KEY = os.getenv('YANDEX_GPT_API_KEY')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID', 'b1gb6o9sk0ajjfdaoev8')
    API_SECRET = os.getenv('API_SECRET', 'your-secret-key-here')
    SERVER_TZ = pytz.timezone('UTC')
    KEMEROVO_TZ = pytz.timezone('Asia/Novokuznetsk')

# ========== YANDEX GPT ИНТЕГРАЦИЯ С RENDER-COMPATIBLE CACHE ==========

class YandexGPTGenerator:
    def __init__(self):
        self.api_key = Config.YANDEX_GPT_API_KEY
        self.folder_id = Config.YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        
        # 🎯 RENDER-COMPATIBLE CACHE
        self.cache_manager = RenderCompatibleCache(ttl_days=7)
        
        # Статистика использования кэша
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Запускаем периодическую очистку
        self._start_cache_cleanup()

    def _start_cache_cleanup(self):
        """Запускаем фоновую очистку кэша"""
        def cleanup_worker():
            while True:
                time.sleep(3600)  # Каждый час
                try:
                    cleaned = self.cache_manager.cleanup_expired()
                    if cleaned > 0:
                        logger.info(f"🔄 Фоновая очистка: удалено {cleaned} записей")
                except Exception as e:
                    logger.error(f"❌ Ошибка фоновой очистки: {e}")
        
        cleanup_thread = Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
        logger.info("🔄 Фоновая очистка кэша запущена")

    def generate_recipe(self, recipe_type, theme):
        """Генерация рецепта через Yandex GPT с кэшированием"""
        # Создаем уникальный ключ кэша
        cache_key = self._create_cache_key(recipe_type, theme)
        
        # Проверяем кэш
        cached_result = self.cache_manager.get(cache_key)
        if cached_result:
            self.cache_hits += 1
            logger.info(f"✅ Используем кэшированный рецепт: {theme}")
            return cached_result
        
        self.cache_misses += 1
        logger.info(f"🔄 Генерируем новый рецепт: {theme}")
        
        try:
            if not self.api_key or self.api_key == 'your-yandex-gpt-api-key':
                result = self._get_template_recipe(recipe_type, theme)
            else:
                # Генерация через Yandex GPT API
                result = self._generate_via_gpt(recipe_type, theme)
            
            # Сохраняем в кэш
            self.cache_manager.set(cache_key, result)
            
            # Логируем статистику каждые 10 запросов
            if (self.cache_hits + self.cache_misses) % 10 == 0:
                self._log_cache_stats()
                
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка генерации рецепта: {e}")
            return self._get_template_recipe(recipe_type, theme)

    def _create_cache_key(self, recipe_type, theme):
        """Создает уникальный ключ кэша"""
        normalized_theme = theme.lower().strip()
        return f"{recipe_type}_{normalized_theme}_{hash(normalized_theme)}"

    def _log_cache_stats(self):
        """Логирует статистику использования кэша"""
        total = self.cache_hits + self.cache_misses
        if total > 0:
            hit_rate = (self.cache_hits / total) * 100
            cache_stats = self.cache_manager.get_stats()
            logger.info(f"📊 Статистика кэша: {self.cache_hits}/{total} попаданий ({hit_rate:.1f}%), записей: {cache_stats['total_entries']}")

    def get_cache_info(self):
        """Возвращает информацию о состоянии кэша"""
        cache_stats = self.cache_manager.get_stats()
        total_requests = self.cache_hits + self.cache_misses
        
        return {
            **cache_stats,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": round((self.cache_hits / total_requests) * 100, 1) if total_requests > 0 else 0,
            "total_requests": total_requests
        }

    def clear_cache(self):
        """Очищает весь кэш"""
        try:
            cleared_count = self.cache_manager.clear_all()
            # Сбрасываем статистику
            self.cache_hits = 0
            self.cache_misses = 0
            return cleared_count
        except Exception as e:
            logger.error(f"❌ Ошибка очистки кэша: {e}")
            return 0

    def _generate_via_gpt(self, recipe_type, theme):
        """Генерация через Yandex GPT API"""
        try:
            prompt = self._build_prompt(recipe_type, theme)
            
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "modelUri": f"gpt://{self.folder_id}/yandexgpt/latest",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.7,
                    "maxTokens": 1500
                },
                "messages": [
                    {
                        "role": "system",
                        "text": "Ты - профессиональный нутрициолог и шеф-повар. Создавай полезные, вкусные и простые рецепты для семьи. ОБЯЗАТЕЛЬНО используй эмодзи в каждом сообщении для визуальной привлекательности! 🍳🥑🥦"
                    },
                    {
                        "role": "user", 
                        "text": prompt
                    }
                ]
            }

            response = requests.post(self.base_url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                recipe_text = result['result']['alternatives'][0]['message']['text']
                logger.info("✅ Рецепт сгенерирован через Yandex GPT")
                return self._format_recipe(recipe_text, recipe_type, theme)
            else:
                logger.error(f"❌ Ошибка Yandex GPT: {response.status_code}")
                return self._get_template_recipe(recipe_type, theme)
                
        except Exception as e:
            logger.error(f"❌ Ошибка GPT генерации: {e}")
            return self._get_template_recipe(recipe_type, theme)

    def _build_prompt(self, recipe_type, theme):
        """Создание промпта для GPT с требованием эмодзи"""
        prompts = {
            'breakfast': f"Создай рецепт полезного семейного завтрака на тему '{theme}'. Включи ингредиенты на 4 человек и пошаговое приготовление. ОБЯЗАТЕЛЬНО используй эмодзи для визуальной привлекательности! 🍳🥚🥑 Пример: • 🥚 Яйца - 8 шт",
            'lunch': f"Создай рецепт питательного семейного обеда на тему '{theme}'. Включи ингредиенты на 4 человек и пошаговое приготовление. ОБЯЗАТЕЛЬНО используй эмодзи для визуальной привлекательности! 🍲🥦🍗", 
            'dinner': f"Создай рецепт легкого семейного ужина на тему '{theme}'. Включи ингредиенты на 4 человек и пошаговое приготовление. ОБЯЗАТЕЛЬНО используй эмодзи для визуальной привлекательности! 🍽️🌙🥬",
            'dessert': f"Создай рецепт полезного десерта для семьи на тему '{theme}'. Включи ингредиенты на 4 человек и пошаговое приготовление. ОБЯЗАТЕЛЬНО используй эмодзи для визуальной привлекательности! 🍰🎂🍓",
            'advice': f"Дай полезный совет нутрициолога на тему '{theme}' для семьи с детьми. ОБЯЗАТЕЛЬНО используй эмодзи для визуальной привлекательности! 💡🧠🌟",
            'family_workout': f"Создай программу совместной тренировки отца и сына-подростка на тему '{theme}'. Включи упражнения для разных уровней подготовки, меры безопасности и рекомендации по мотивации. ОБЯЗАТЕЛЬНО используй эмодзи! 💪👨‍👦",
            'active_snacks': f"Создай рецепты полезных перекусов для активного отдыха (сноуборд, походы, велопрогулки) на тему '{theme}'. Блюда должны быть удобными для транспортировки, сытными и сохранять энергию. ОБЯЗАТЕЛЬНО используй эмодзи! 🏂🚴‍♂️",
            'snowboard_training': f"Создай научно обоснованную программу функциональных тренировок для сноубордистов на тему '{theme}'. Включи разминку, основную часть и заминку с акцентом на мышцы, используемые в сноубординге. ОБЯЗАТЕЛЬНО используй эмодзи! 🏂💪"
        }

        return prompts.get(recipe_type, prompts['breakfast'])

    def _format_recipe(self, recipe_text, recipe_type, theme):
        """Форматирование сгенерированного рецепта"""
        emoji_map = {
            'breakfast': '🍳', 'lunch': '🍲', 'dinner': '🍽️', 
            'dessert': '🍰', 'advice': '💡',
            'family_workout': '💪', 'active_snacks': '🎒',
            'snowboard_training': '🏂'
        }

        emoji = emoji_map.get(recipe_type, '🍽️')
        return f"{emoji} <b>{theme.upper()}</b>\n\n{recipe_text}"

    def _get_template_recipe(self, recipe_type, theme):
        """Резервные шаблонные рецепты с эмодзи"""
        templates = {
            'neuro_breakfast': """
🍽️ <b>ОМЛЕТ С ЛОСОСЕМ И АВОКАДО</b>

📊 <b>ПИЩЕВАЯ ЦЕННОСТЬ НА ПОРЦИЮ:</b>
• 🔥 Калории: 320 ккал
• 🍗 Белки: 25 г
• 🥑 Жиры: 22 г  
• 🌾 Углеводы: 8 г

🛒 <b>ИНГРЕДИЕНТЫ НА 4 ПОРЦИИ:</b>
• 🥚 Яйца - 8 шт
• 🐟 Лосось слабосоленый - 200 г
• 🥑 Авокадо - 2 шт
• 🥬 Шпинат - 100 г
• 🧀 Сыр фета - 100 г
• 🍅 Помидоры черри - 150 г
• 🫒 Оливковое масло - 2 ст.л.
• 🌶️ Специи: куркума, черный перец

👨‍🍳 <b>ПРОЦЕСС ПРИГОТОВЛЕНИЯ:</b>
<tg-spoiler>1. 🥚 Яйца взбить с куркумой и перцем
2. 🥑 Авокадо нарезать кубиками
3. 🥬 На сковороде обжарить шпинат
4. 🍳 Залить яйцами, добавить авокадо и помидоры
5. 🔥 Готовить на медленном огне 7-8 минут
6. 🧀 Посыпать сыром фета и лососем</tg-spoiler>

🍴 <b>Приятного аппетита!</b>""",
            'snowboard_training': """
🏂 <b>ФУНКЦИОНАЛЬНАЯ ПОДГОТОВКА ДЛЯ СНОУБОРДИСТОВ</b>

🎯 <b>ЦЕЛЕВАЯ ГРУППА МЫШЦ:</b>
• 🦵 Квадрицепсы и ягодицы (стабилизация)
• 🔄 Косые мышцы живота (повороты) 
• ⚖️ Мышцы кора (баланс)
• 💪 Плечевой пояс (толчки)

⚡ <b>НАУЧНАЯ ОСНОВА:</b>
Программа разработана на основе биомеханического анализа движений сноубордиста с акцентом на:
• Эксцентрические нагрузки для ударных воздействий
• Проприоцептивную тренировку для баланса
• Ротационную стабильность для безопасных поворотов
• Взрывную силу для контроля в сложных условиях

🏋️‍♂️ <b>ТРЕНИРОВКА (45 минут):</b>

<b>РАЗМИНКА (10 минут):</b>
<tg-spoiler>• 🏃‍♂️ Бег на месте с высоким подниманием бедра - 2 мин
• 🔄 Вращения в тазобедренных суставах - 2 мин  
• 🤸‍♂️ Динамическая растяжка ног - 3 мин
• 💨 Дыхательные упражнения - 3 мин</tg-spoiler>

<b>ОСНОВНАЯ ЧАСТЬ (25 минут):</b>
<tg-spoiler>• 🏋️‍♂️ БОКОВЫЕ ВЫПАДЫ - 3×15 (укрепление для карвинга)
• 💪 ПЛАНКА С ПОВОРОТАМИ - 3×20 (стабильность корпуса)
• 🦵 ПРИСЕДАНИЯ НА ОДНОЙ НОГЕ - 3×10 (баланс при спуске)
• 🚣‍♂️ ТЯГА РЕЗИНОВОГО ЭСПАНДЕРА - 3×15 (мышцы для подъемов)
• 🏃‍♂️ ПРЫЖКИ НА БОКС - 3×12 (взрывная сила)</tg-spoiler>

<b>ЗАВЕРШАЮЩАЯ ЧАСТЬ (10 минут):</b>
<tg-spoiler>• 🧘‍♂️ Статическая растяжка - 5 мин
• 💧 Восстановление водного баланса
• 📊 Анализ техники</tg-spoiler>

🌟 <b>РЕКОМЕНДАЦИИ ПО ПИТАНИЮ:</b>
• 🍌 Бананы с арахисовой пастой за 1.5 часа до катания
• 🌯 Протеиновые роллы для перекуса на склоне
• 💧 Изотоник своими руками: вода + мед + лимон + соль
• 🥛 Протеиновый коктейль после тренировки

📈 <b>ПРОГРЕССИЯ:</b>
Начинай с 2 тренировок в неделю, постепенно увеличивая:
• Интенсивность (вес/сопротивление)
• Объем (подходы/повторения)
• Сложность (упражнения на нестабильной поверхности)"""
        }

        return templates.get(f"{recipe_type}_{theme}", templates.get('neuro_breakfast'))

# ========== МОНИТОРИНГ СЕРВИСА ==========

class ServiceMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.sent_messages = 0
        self.missed_messages = 0

    def increment_request(self):
        self.request_count += 1

    def record_sent_message(self):
        self.sent_messages += 1

    def record_missed_message(self, event_name):
        self.missed_messages += 1
        logger.warning(f"⚠️ Пропущено сообщение: {event_name}")

    def get_status(self):
        return {
            "status": "healthy",
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "requests_handled": self.request_count,
            "sent_messages": self.sent_messages,
            "missed_messages": self.missed_messages,
            "timestamp": datetime.now().isoformat()
        }

service_monitor = ServiceMonitor()

# ========== СИСТЕМА ВРЕМЕНИ ==========

class TimeManager:
    @staticmethod
    def kemerovo_to_server(kemerovo_time_str):
        """КОНВЕРТАЦИЯ ВРЕМЕНИ КЕМЕРОВО → СЕРВЕР"""
        try:
            kemerovo_now = datetime.now(Config.KEMEROVO_TZ)
            kemerovo_dt = datetime.strptime(kemerovo_time_str, '%H:%M').time()
            full_kemerovo_dt = datetime.combine(kemerovo_now.date(), kemerovo_dt)
            full_kemerovo_dt = Config.KEMEROVO_TZ.localize(full_kemerovo_dt)

            server_dt = full_kemerovo_dt.astimezone(Config.SERVER_TZ)
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
            'kemerovo_date': kemerovo_now.strftime('%Y-%m-%d'),
            'kemerovo_weekday': kemerovo_now.weekday(),
            'kemerovo_weekday_name': ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'][kemerovo_now.weekday()]
        }

    @staticmethod
    def get_kemerovo_weekday():
        return datetime.now(Config.KEMEROVO_TZ).weekday()

# ========== МЕНЕДЖЕР ВИЗУАЛЬНОГО КОНТЕНТА ==========

class VisualContentManager:
    FOOD_PHOTOS = {
        'breakfast': [
            'https://images.unsplash.com/photo-1551782450-17144efb9c50?w=600',
            'https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=600',
        ],
        'lunch': [
            'https://images.unsplash.com/photo-1547592166-23ac45744acd?w=600',
            'https://images.unsplash.com/photo-1606755962773-d324e74532a7?w=600',
        ],
        'dinner': [
            'https://images.unsplash.com/photo-1563379926898-05f4575a45d8?w=600',
            'https://images.unsplash.com/photo-1598214886806-c87b84b707f5?w=600',
        ],
        'dessert': [
            'https://images.unsplash.com/photo-1563729784474-d77dbb933a9e?w=600',
            'https://images.unsplash.com/photo-1571115764595-644a1f56a55c?w=600',
        ],
        'science': [
            'https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=600',
            'https://images.unsplash.com/photo-1559757148-5c350d0d3c56?w=600',
        ],
        'workout': [
            'https://images.unsplash.com/photo-1536922246289-88c42f957773?w=600',
            'https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?w=600',
        ],
        'snacks': [
            'https://images.unsplash.com/photo-1505576399279-565b52d4ac71?w=600',
            'https://images.unsplash.com/photo-1488459716781-31db52582fe9?w=600',
        ],
        'snowboard': [
            'https://images.unsplash.com/photo-1511895426328-dc8714191300?w=600',
            'https://images.unsplash.com/photo-1543459176-4426b37223ba?w=600',
        ]
    }

    # ЭМОЦИОНАЛЬНЫЕ ТРИГГЕРЫ ДЛЯ КАЖДОГО ДНЯ
    EMOTIONAL_TRIGGERS = {
        'monday': "Проснись и сияй! 🌅 Твой мозг жаждет правильного топлива...",
        'tuesday': "Время стать сильнее! 💪 Сегодня мы строим твое идеальное тело...", 
        'wednesday': "Чувствуешь легкость! 🍃 Пришло время очищения и обновления...",
        'thursday': "Зарядись энергией! ⚡ Сегодня мы наполняем тебя силой до конца недели...",
        'friday': "Награда за труды! 🎉 Баланс удовольствия и пользы ждет тебя...",
        'saturday': "Семейная магия! 👨‍👩‍👧‍👦 Создаем воспоминания на кухне вместе...",
        'sunday': "Инвестиция в успех! 📈 Готовься к идеальной неделе уже сегодня..."
    }

    # ОБНОВЛЕННАЯ КОНЦОВКА С КНОПКОЙ ПОДЕЛИТЬСЯ
    UNIVERSAL_FOOTER = """
─━━━━━━━━━━━━━━ ⋅∙∘ ★ ∘∙⋅ ━━━━━━━━━━━━─

🎯 Основано на исследованиях доказательной нутрициологии

📢 <a href="https://t.me/ppsupershef">Подписывайтесь на канал!</a>
💬 <a href="https://t.me/ppsupershef_chat">Обсуждаем рецепты в чате!</a>

😋 Вкусно | 💪 Полезно | ⏱️ Быстро | 🧠 Научно

<a href="https://t.me/share/url?url=https://t.me/ppsupershef&text=Присоединяйся%20к%20Клубу%20Осознанного%20Питания!%20🍽️">🔄 Поделиться с друзьями</a>"""

    # НАУЧНЫЕ ПОДХОДЫ С ОБОСНОВАНИЕМ ДНЯ (ШАБЛОННЫЕ)
    SCIENCE_APPROACHES = {
        'monday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ ПОНЕДЕЛЬНИКА:
После выходных мозг нуждается в усиленной поддержке для запуска когнитивных функций. 
Холин из яиц + Омега-3 из лосося создают идеальную комбинацию для синтеза ацетилхолина 
и восстановления нейронных связей после weekend-релаксации.""",
        
        'tuesday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ ВТОРНИКА:
После активного начала недели мышцы нуждаются в восстановлении. Лейцин из яиц и творога 
активирует mTOR путь, усиливая синтез мышечного белка на 40% после понедельничных нагрузок.""",
        
        'wednesday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ СРЕДЫ:
К середине недели достигается пик токсической нагрузки от городской среды и стресса. 
Клетчатка из овощей ферментируется микробиомом в бутират, снижая системное воспаление.""",
        
        'thursday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ ЧЕТВЕРГА:
К концу рабочей недели истощаются запасы гликогена. Сложные углеводы с низким ГИ 
обеспечивают постепенное высвобождение глюкозы, подготавливая энергетические резервы.""",
        
        'friday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ ПЯТНИЦЫ:
В преддверии выходных важен баланс между дисциплиной и гибкостью. Принцип 80/20 
активирует систему вознаграждения мозга, поддерживая мотивацию без перегрузки.""",
        
        'saturday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ СУББОТЫ:
Совместное приготовление пищи в выходные повышает окситоцин на 27%, укрепляя 
семейные связи и формируя позитивные пищевые ассоциации у детей.""",
        
        'sunday': """🎯 НАУЧНЫЙ ПОДХОД ДЛЯ ВОСКРЕСЕНЬЯ:
Планирование питания на воскресенье снижает decision fatigue на 35% в рабочие дни 
и повышает adherence к здоровому рациону на 68%."""
    }

    def get_photo_for_recipe(self, recipe_type):
        photo_category = self._map_recipe_to_photo(recipe_type)
        photos = self.FOOD_PHOTOS.get(photo_category, self.FOOD_PHOTOS['breakfast'])
        return random.choice(photos)

    def _map_recipe_to_photo(self, recipe_type):
        mapping = {
            'neuro_breakfast': 'breakfast', 'energy_breakfast': 'breakfast',
            'protein_breakfast': 'breakfast', 'veggie_breakfast': 'breakfast',
            'carbs_breakfast': 'breakfast', 'family_breakfast': 'breakfast',
            'sunday_breakfast': 'breakfast', 'focus_lunch': 'lunch',
            'protein_lunch': 'lunch', 'veggie_lunch': 'lunch',
            'carbs_lunch': 'lunch', 'family_lunch': 'lunch',
            'sunday_lunch': 'lunch', 'brain_dinner': 'dinner',
            'protein_dinner': 'dinner', 'veggie_dinner': 'dinner',
            'family_dinner': 'dinner', 'week_prep_dinner': 'dinner',
            'friday_dessert': 'dessert', 'saturday_dessert': 'dessert',
            'sunday_dessert': 'dessert', 'neuro_advice': 'science',
            'protein_advice': 'science', 'veggie_advice': 'science',
            'carbs_advice': 'science', 'water_advice': 'science',
            'family_advice': 'science', 'planning_advice': 'science',
            'monday_science': 'science', 'tuesday_science': 'science',
            'wednesday_science': 'science', 'thursday_science': 'science',
            'friday_science': 'science', 'saturday_science': 'science',
            'sunday_science': 'science', 'family_workout': 'workout',
            'active_snacks': 'snacks', 'snowboard_training': 'snowboard'
        }
        return mapping.get(recipe_type, 'breakfast')

    def generate_attractive_post(self, title, content, recipe_type, benefits, include_science_approach=False, day_of_week=None):
        photo_url = self.get_photo_for_recipe(recipe_type)
        
        # ЭМОЦИОНАЛЬНЫЙ ТРИГГЕР ДЛЯ ТЕКУЩЕГО ДНЯ
        emotional_trigger = self.EMOTIONAL_TRIGGERS.get(day_of_week.lower() if day_of_week else 'monday', "")
        
        # НОВЫЙ ФОРМАТ ПОСТА С ЭМОЦИОНАЛЬНЫМ ТРИГГЕРОМ
        post = f"""🍽️ <b>{title}</b>

{emotional_trigger}

📸 <a href="{photo_url}">🖼️ ФОТО БЛЮДА</a>

{content}

🌟 <b>ПОЛЬЗА ДЛЯ ЗДОРОВЬЯ:</b>
{benefits}"""

        # Добавляем научный подход если нужно
        if include_science_approach and day_of_week:
            science_approach = self.SCIENCE_APPROACHES.get(day_of_week.lower())
            if science_approach:
                post += f"\n\n{science_approach}"

        # Добавляем унифицированную концовку с кнопкой Поделиться
        post += self.UNIVERSAL_FOOTER

        return post

# ========== ГЕНЕРАТОР КОНТЕНТА ==========

class ContentGenerator:
    def __init__(self):
        self.visual_manager = VisualContentManager()
        self.gpt_generator = YandexGPTGenerator()

    # НОВЫЙ МЕТОД ДЛЯ ТРЕНИРОВКИ СНОУБОРДИСТОВ
    def generate_snowboard_training(self):
        """Генерация тренировки для сноубордистов через GPT с fallback на шаблон"""
        return self._generate_with_gpt('snowboard_training', 'Функциональная подготовка для сноубордистов',
                                      '🏂 Улучшение баланса и контроля на доске\n💪 Увеличение мышечной выносливости на 30-50%\n🛡️ Снижение риска травм на 25-35%\n⚡ Повышение взрывной силы для прыжков\n🔄 Улучшение ротационной стабильности\n❄️ Подготовка к высотным нагрузкам\n🍃 Оптимизация дыхательной функции',
                                      'saturday')

    def generate_family_workout(self):
        return self._generate_with_gpt('family_workout', 'Совместная тренировка отца и сына',
                                      '👨‍👦 Укрепление семейных связей\n💪 Физическое развитие для обоих\n🧠 Обучение правильной технике\n🏆 Создание здоровой конкуренции\n❤️ Улучшение сердечно-сосудистой системы\n🦴 Укрепление костной ткани',
                                      'saturday')

    def generate_active_snacks(self):
        return self._generate_with_gpt('active_snacks', 'Полезные перекусы для активного отдыха',
                                      '⚡ Быстрое восстановление энергии\n💪 Поддержка мышечной массы\n🧠 Улучшение концентрации\n🏃‍♂️ Повышение выносливости\n💧 Оптимальная гидратация\n🍽️ Сбалансированный состав',
                                      'sunday')

    # БАЗОВЫЕ МЕТОДЫ ДЛЯ ВСЕХ ТИПОВ КОНТЕНТА
    def generate_monday_science(self):
        return self._generate_with_gpt('advice', 'Наука понедельника: Питание для мозга',
                                      '🧠 Улучшение когнитивных функций\n💡 Повышение продуктивности\n🌟 Забота о ментальном здоровье\n🛡️ Защита нейронов',
                                      'monday')

    def generate_neuro_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Нейрозавтрак для концентрации',
                                      '🧠 Улучшает когнитивные функции и память\n💪 Содержит Омега-3 для здоровья мозга\n🛡️ Богат антиоксидантами для защиты нейронов\n⚡ Обеспечивает устойчивую энергию на 4-5 часов',
                                      'monday')

    def generate_focus_lunch(self):
        return self._generate_with_gpt('lunch', 'Обед для концентрации',
                                      '🧠 Поддерживает умственную активность\n💡 Улучшает память\n⚡ Заряжает энергией\n🌟 Повышает продуктивность',
                                      'monday')

    def generate_brain_dinner(self):
        return self._generate_with_gpt('dinner', 'Ужин для мозга',
                                      '🧠 Подготовка ко сну\n💡 Улучшает качество сна\n🌙 Легкий и полезный\n🌟 Восстанавливает силы',
                                      'monday')

    def generate_neuro_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Нейропитание',
                                      '🧠 Улучшает когнитивные функции\n💡 Повышает продуктивность\n🌟 Заботится о ментальном здоровье\n🛡️ Защищает нейроны',
                                      'monday')

    def generate_tuesday_science(self):
        return self._generate_with_gpt('advice', 'Наука вторника: Сила белков',
                                      '💪 Строительный материал организма\n🍗 Важен для роста и развития\n🌟 Поддерживает иммунитет\n🛡️ Обеспечивает восстановление',
                                      'tuesday')

    def generate_protein_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Белковый завтрак',
                                      '💪 Строительный материал для мышц\n🦴 Богат кальцием для крепких костей\n🍗 Надолго сохраняет чувство сытости\n🌟 Укрепляет иммунную систему',
                                      'tuesday')

    def generate_protein_lunch(self):
        return self._generate_with_gpt('lunch', 'Белковый обед',
                                      '💪 Восстанавливает мышцы\n🍗 Надолго насыщает\n🌟 Укрепляет кости\n🛡️ Поддерживает иммунитет',
                                      'tuesday')

    def generate_protein_dinner(self):
        return self._generate_with_gpt('dinner', 'Белковый ужин',
                                      '💪 Восстанавливает за ночь\n🍗 Надолго насыщает\n🌟 Укрепляет организм\n🛡️ Поддерживает метаболизм',
                                      'tuesday')

    def generate_protein_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Оптимизация белков',
                                      '💪 Строительный материал организма\n🍗 Важен для роста и развития\n🌟 Поддерживает иммунитет\n🛡️ Обеспечивает восстановление',
                                      'tuesday')

    def generate_wednesday_science(self):
        return self._generate_with_gpt('advice', 'Наука среды: Сила овощей',
                                      '🥬 Источник витаминов и минералов\n🌿 Очищает организм\n💚 Профилактика заболеваний\n🌟 Улучшает здоровье',
                                      'wednesday')

    def generate_veggie_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Овощной завтрак',
                                      '🥬 Богат клетчаткой и витаминами\n🌿 Очищает организм\n💚 Легкий и полезный\n⚡ Дает заряд энергии',
                                      'wednesday')

    def generate_veggie_lunch(self):
        return self._generate_with_gpt('lunch', 'Овощной обед',
                                      '🥬 Богат витаминами и минералами\n🌿 Очищает организм\n💚 Легкий и полезный\n⚡ Дает энергию',
                                      'wednesday')

    def generate_veggie_dinner(self):
        return self._generate_with_gpt('dinner', 'Овощной ужин',
                                      '🥬 Легкий для пищеварения\n🌿 Богат клетчаткой\n💚 Способствует детоксу\n🌟 Очищает организм',
                                      'wednesday')

    def generate_veggie_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Детокс питание',
                                      '🥬 Источник витаминов и минералов\n🌿 Очищает организм\n💚 Профилактика заболеваний\n🌟 Улучшает здоровье',
                                      'wednesday')

    def generate_thursday_science(self):
        return self._generate_with_gpt('advice', 'Наука четверга: Энергия углеводов',
                                      '⚡ Основной источник энергии\n🍞 Важны для активности\n💪 Поддерживают метаболизм\n🌟 Обеспечивают жизнедеятельность',
                                      'thursday')

    def generate_carbs_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Углеводный завтрак',
                                      '⚡ Источник энергии\n🍞 Сложные углеводы\n💪 Поддерживает активность\n🌟 Надолго насыщает',
                                      'thursday')

    def generate_carbs_lunch(self):
        return self._generate_with_gpt('lunch', 'Углеводный обед',
                                      '⚡ Восполняет энергию\n🍚 Сложные углеводы\n💪 Поддерживает активность\n🌟 Надолго насыщает',
                                      'thursday')

    def generate_carbs_dinner(self):
        return self._generate_with_gpt('dinner', 'Углеводный ужин',
                                      '⚡ Восстанавливает энергию\n🍚 Сложные углеводы\n💪 Подготавливает к следующему дню\n🌟 Обеспечивает сон',
                                      'thursday')

    def generate_carbs_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Сложные углеводы',
                                      '⚡ Основной источник энергии\n🍞 Важны для активности\n💪 Поддерживают метаболизм\n🌟 Обеспечивают жизнедеятельность',
                                      'thursday')

    def generate_friday_science(self):
        return self._generate_with_gpt('advice', 'Наука пятницы: Баланс питания',
                                      '⚖️ Оптимальное сочетание нутриентов\n💪 Поддержка всех систем\n🌟 Долгосрочное здоровье\n🛡️ Профилактика заболеваний',
                                      'friday')

    def generate_balance_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Сбалансированный завтрак',
                                      '⚡ Энергия и питательность\n💪 Белки для сытости\n🥬 Витамины для здоровья\n🌟 Идеальный баланс',
                                      'friday')

    def generate_balance_lunch(self):
        return self._generate_with_gpt('lunch', 'Сбалансированный обед',
                                      '🍽️ Идеальное сочетание нутриентов\n💪 Поддержка энергии\n🌟 Оптимальное насыщение\n🛡️ Польза для здоровья',
                                      'friday')

    def generate_balance_dinner(self):
        return self._generate_with_gpt('dinner', 'Сбалансированный ужин',
                                      '🌙 Легкий и питательный\n💪 Восстановление организма\n🌟 Подготовка ко сну\n🛡️ Оптимальное питание',
                                      'friday')

    def generate_balance_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Принцип 80/20',
                                      '⚖️ Оптимальное сочетание нутриентов\n💪 Поддержка всех систем\n🌟 Долгосрочное здоровье\n🛡️ Профилактика заболеваний',
                                      'friday')

    def generate_saturday_science(self):
        return self._generate_with_gpt('advice', 'Наука субботы: Семейное питание',
                                      '👨‍👩‍👧‍👦 Укрепляет семейные связи\n😊 Формирует здоровые привычки\n💫 Создает теплую атмосферу\n🌟 Наследие для детей',
                                      'saturday')

    def generate_family_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Семейный завтрак',
                                      '👨‍👩‍👧‍👦 Объединяет семью за столом\n😊 Вкусно и полезно для всех\n💫 Начинает день с радости\n🌟 Создает традиции',
                                      'saturday')

    def generate_family_lunch(self):
        return self._generate_with_gpt('lunch', 'Семейный обед',
                                      '👨‍👩‍👧‍👦 Объединяет за обеденным столом\n😊 Вкусно и полезно для всех\n💫 Создает семейные традиции\n🌟 Укрепляет связи',
                                      'saturday')

    def generate_saturday_dessert(self):
        return self._generate_with_gpt('dessert', 'Субботний десерт',
                                      '🎂 Сладкое наслаждение\n😊 Полезные ингредиенты\n👨‍👩‍👧‍👦 Для семейного вечера\n💫 Традиции и радость',
                                      'saturday')

    def generate_family_dinner(self):
        return self._generate_with_gpt('dinner', 'Семейный ужин',
                                      '👨‍👩‍👧‍👦 Завершает день вместе\n😊 Вкусно и полезно\n💫 Создает теплую атмосферу\n🌟 Объединяет семью',
                                      'saturday')

    def generate_family_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Питание для семьи',
                                      '👨‍👩‍👧‍👦 Укрепляет семейные связи\n😊 Формирует здоровые привычки\n💫 Создает теплую атмосферу\n🌟 Наследие для детей',
                                      'saturday')

    def generate_sunday_science(self):
        return self._generate_with_gpt('advice', 'Наука воскресенья: Планирование питания',
                                      '📋 Экономит время и деньги\n💪 Обеспечивает сбалансированность\n🌟 Помогает достичь целей\n🛡️ Гарантирует успех',
                                      'sunday')

    def generate_sunday_breakfast(self):
        return self._generate_with_gpt('breakfast', 'Воскресный бранч',
                                      '🎉 Праздничное настроение\n👨‍👩‍👧‍👦 Идеально для семейного дня\n🍽️ Особенный вкус\n💫 Завершает неделю',
                                      'sunday')

    def generate_sunday_lunch(self):
        return self._generate_with_gpt('lunch', 'Воскресный обед',
                                      '🎉 Праздничная атмосфера\n👨‍👩‍👧‍👦 Семейное время\n🍽️ Особенный вкус\n💫 Завершает выходные',
                                      'sunday')

    def generate_sunday_dessert(self):
        return self._generate_with_gpt('dessert', 'Воскресный десерт',
                                      '🍰 Завершение выходных\n😊 Вкусные воспоминания\n👨‍👩‍👧‍👦 Семейная традиция\n🌟 Сладкий финал',
                                      'sunday')

    def generate_week_prep_dinner(self):
        return self._generate_with_gpt('dinner', 'Ужин для подготовки к неделе',
                                      '📋 Закладывает основу на неделю\n💪 Питательный и сбалансированный\n🌟 Настраивает на продуктивность\n🛡️ Гарантирует успех',
                                      'sunday')

    def generate_planning_advice(self):
        return self._generate_with_gpt('advice', 'Совет: Meal prep стратегии',
                                      '📋 Экономит время и деньги\n💪 Обеспечивает сбалансированность\n🌟 Помогает достичь целей\n🛡️ Гарантирует успех',
                                      'sunday')

    def _generate_with_gpt(self, recipe_type, theme, benefits, day_of_week=None):
        """Генерация контента через Yandex GPT с кэшированием"""
        try:
            recipe_content = self.gpt_generator.generate_recipe(recipe_type, theme)
            post = self.visual_manager.generate_attractive_post(
                theme.upper(),
                recipe_content,
                f"{recipe_type}",
                benefits,
                include_science_approach=True,
                day_of_week=day_of_week
            )
            return post
        except Exception as e:
            logger.error(f"❌ Ошибка генерации контента через GPT: {e}")
            return self._get_fallback_content(recipe_type, theme, benefits, day_of_week)

    def _get_fallback_content(self, recipe_type, theme, benefits, day_of_week=None):
        """Резервный контент если GPT не работает"""
        fallback_content = f"""
📊 <b>ПИЩЕВАЯ ЦЕННОСТЬ НА ПОРЦИЮ:</b>
• 🔥 Калории: 300-400 ккал
• 🍗 Белки: 20-30 г
• 🥑 Жиры: 15-25 g
• 🌾 Углеводы: 20-30 г

🛒 <b>ИНГРЕДИЕНТЫ НА 4 ПОРЦИИ:</b>
• 🥕 Свежие овощи и зелень
• 🍗 Качественные белки  
• 🌾 Полезные углеводы
• 🫒 Полезные жиры
• 🌶️ Специи и травы

👨‍🍳 <b>ПРОЦЕСС ПРИГОТОВЛЕНИЯ:</b>
<tg-spoiler>1. 🥣 Подготовить все ингредиенты
2. 🍳 Следовать классическому рецепту
3. 🔥 Готовить на среднем огне
4. 🍽️ Подавать горячим для семьи</tg-spoiler>

🍴 <b>Приятного аппетита!</b>"""

        return self.visual_manager.generate_attractive_post(
            theme.upper(),
            fallback_content,
            recipe_type,
            benefits,
            include_science_approach=True,
            day_of_week=day_of_week
        )

# ========== ТЕЛЕГРАМ МЕНЕДЖЕР ==========

class TelegramManager:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.channel = Config.TELEGRAM_CHANNEL
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.sent_hashes = set()
        self.last_sent_times = {}
        self._member_count = 0
        self._last_member_count_time = 0

    def get_member_count(self):
        """Получает реальное количество подписчиков через Telegram API с кэшированием"""
        current_time = time.time()
        
        if current_time - self._last_member_count_time < 300 and self._member_count > 0:
            return self._member_count
            
        try:
            if not self.token or self.token == 'your-telegram-bot-token':
                logger.warning("⚠️ Токен бота не настроен, возвращаем 0")
                return 0
                
            url = f"{self.base_url}/getChatMembersCount"
            payload = {
                'chat_id': self.channel
            }
            
            logger.info(f"🔍 Запрос количества подписчиков для канала: {self.channel}")
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    count = result.get('result', 0)
                    self._member_count = count
                    self._last_member_count_time = current_time
                    logger.info(f"✅ Актуальное количество подписчиков: {count}")
                    return count
                else:
                    logger.error(f"❌ Ошибка Telegram API: {result.get('description')}")
                    return self._member_count if self._member_count > 0 else 0
            else:
                logger.error(f"❌ HTTP ошибка получения количества подписчиков: {response.status_code}")
                return self._member_count if self._member_count > 0 else 0
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения количества подписчиков: {e}")
            return self._member_count if self._member_count > 0 else 0

    def send_with_fallback(self, text, event_name, max_retries=3):
        for attempt in range(max_retries):
            try:
                success = self.send_message(text)
                if success:
                    service_monitor.record_sent_message()
                    return True
                else:
                    logger.warning(f"⚠️ Попытка {attempt + 1} не удалась для {event_name}")
                    time.sleep(10)
            except Exception as e:
                logger.error(f"❌ Ошибка при попытке {attempt + 1}: {e}")
                time.sleep(10)

        logger.error(f"❌ Все {max_retries} попыток отправки провалились: {event_name}")
        service_monitor.record_missed_message(event_name)
        return False

    def send_message(self, text, parse_mode='HTML'):
        try:
            current_time = datetime.now()
            time_key = current_time.strftime('%Y-%m-%d %H:%M')

            if time_key in self.last_sent_times:
                time_diff = (current_time - self.last_sent_times[time_key]).total_seconds()
                if time_diff < 600:
                    logger.warning(f"⚠️ Попытка дублирования в течение 10 минут: {time_key}")
                    return False

            if not self.token or self.token == 'your-telegram-bot-token':
                logger.error("❌ Токен бота не настроен!")
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

            logger.info(f"🔗 Отправка сообщения в Telegram...")
            response = requests.post(url, json=payload, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.sent_hashes.add(content_hash)
                    self.last_sent_times[time_key] = current_time
                    logger.info("✅ Сообщение успешно отправлено в канал")
                    return True
                else:
                    logger.error(f"❌ Ошибка Telegram API: {result.get('description')}")
            else:
                logger.error(f"❌ HTTP ошибка: {response.status_code}")

            return False

        except Exception as e:
            logger.error(f"❌ Ошибка при отправке: {str(e)}")
            return False

# ========== ПЛАНИРОВЩИК КОНТЕНТА ==========

class ContentScheduler:
    def __init__(self):
        # ОБНОВЛЕННОЕ РАСПИСАНИЕ С ТРЕНИРОВКОЙ ДЛЯ СНОУБОРДИСТОВ
        self.kemerovo_schedule = {
            # ПОНЕДЕЛЬНИК (0)
            0: {
                "08:30": {"name": "🧠 Научное сообщение: Питание для мозга", "type": "science", "method": "generate_monday_science"},
                "09:00": {"name": "🧠 Нейрозавтрак: Омлет с лососем", "type": "neuro_breakfast", "method": "generate_neuro_breakfast"},
                "13:00": {"name": "🍲 Обед для концентрации", "type": "focus_lunch", "method": "generate_focus_lunch"},
                "19:00": {"name": "🥗 Ужин для мозга", "type": "brain_dinner", "method": "generate_brain_dinner"},
                "20:00": {"name": "🧠 Совет: Нейропитание", "type": "neuro_advice", "method": "generate_neuro_advice"}
            },
            # ВТОРНИК (1)
            1: {
                "08:30": {"name": "💪 Научное сообщение: Сила белков", "type": "science", "method": "generate_tuesday_science"},
                "09:00": {"name": "💪 Белковый завтрак: Творожная запеканка", "type": "protein_breakfast", "method": "generate_protein_breakfast"},
                "13:00": {"name": "🍗 Белковый обед: Индейка с киноа", "type": "protein_lunch", "method": "generate_protein_lunch"},
                "19:00": {"name": "🐟 Ужин: Лосось с овощами", "type": "protein_dinner", "method": "generate_protein_dinner"},
                "20:00": {"name": "💪 Совет: Оптимизация белков", "type": "protein_advice", "method": "generate_protein_advice"}
            },
            # СРЕДА (2)
            2: {
                "08:30": {"name": "🥬 Научное сообщение: Сила овощей", "type": "science", "method": "generate_wednesday_science"},
                "09:00": {"name": "🥬 Овощной завтрак: Смузи-боул", "type": "veggie_breakfast", "method": "generate_veggie_breakfast"},
                "13:00": {"name": "🥦 Обед: Овощное рагу", "type": "veggie_lunch", "method": "generate_veggie_lunch"},
                "19:00": {"name": "🥑 Ужин: Салат с авокадо", "type": "veggie_dinner", "method": "generate_veggie_dinner"},
                "20:00": {"name": "🥬 Совет: Детокс питание", "type": "veggie_advice", "method": "generate_veggie_advice"}
            },
            # ЧЕТВЕРГ (3)
            3: {
                "08:30": {"name": "🍠 Научное сообщение: Энергия углеводов", "type": "science", "method": "generate_thursday_science"},
                "09:00": {"name": "🍠 Углеводный завтрак: Овсяная каша", "type": "carbs_breakfast", "method": "generate_carbs_breakfast"},
                "13:00": {"name": "🍚 Обед: Гречка с овощами", "type": "carbs_lunch", "method": "generate_carbs_lunch"},
                "19:00": {"name": "🥔 Ужин: Запеченный батат", "type": "carbs_dinner", "method": "generate_carbs_dinner"},
                "20:00": {"name": "🍠 Совет: Сложные углеводы", "type": "carbs_advice", "method": "generate_carbs_advice"}
            },
            # ПЯТНИЦА (4)
            4: {
                "08:30": {"name": "🎉 Научное сообщение: Баланс питания", "type": "science", "method": "generate_friday_science"},
                "09:00": {"name": "🥞 Сбалансированный завтрак", "type": "balance_breakfast", "method": "generate_balance_breakfast"},
                "13:00": {"name": "🍝 Обед: Паста с соусом", "type": "balance_lunch", "method": "generate_balance_lunch"},
                "19:00": {"name": "🍽️ Ужин: Рыба с картофелем", "type": "balance_dinner", "method": "generate_balance_dinner"},
                "20:00": {"name": "🎉 Совет: Принцип 80/20", "type": "balance_advice", "method": "generate_balance_advice"}
            },
            # СУББОТА (5) - ДОБАВЛЕНА ТРЕНИРОВКА ДЛЯ СНОУБОРДИСТОВ
            5: {
                "08:30": {"name": "👨‍🍳 Научное сообщение: Семейное питание", "type": "science", "method": "generate_saturday_science"},
                "10:00": {"name": "🍳 Семейный завтрак: Сырники", "type": "family_breakfast", "method": "generate_family_breakfast"},
                "11:00": {"name": "💪 Семейная тренировка", "type": "family_workout", "method": "generate_family_workout"},
                "14:00": {"name": "🏂 Тренировка для сноубордистов", "type": "snowboard_training", "method": "generate_snowboard_training"},
                "13:00": {"name": "👨‍🍳 Семейный обед: Сырный суп", "type": "family_lunch", "method": "generate_family_lunch"},
                "16:00": {"name": "🎂 Семейный десерт", "type": "saturday_dessert", "method": "generate_saturday_dessert"},
                "19:00": {"name": "🍽️ Семейный ужин", "type": "family_dinner", "method": "generate_family_dinner"},
                "20:00": {"name": "👨‍👩‍👧‍👦 Совет: Питание для семьи", "type": "family_advice", "method": "generate_family_advice"}
            },
            # ВОСКРЕСЕНЬЕ (6)
            6: {
                "08:30": {"name": "📝 Научное сообщение: Планирование питания", "type": "science", "method": "generate_sunday_science"},
                "10:00": {"name": "☀️ Воскресный бранч: Омлет", "type": "sunday_breakfast", "method": "generate_sunday_breakfast"},
                "13:00": {"name": "🛒 Обед + план на неделю", "type": "sunday_lunch", "method": "generate_sunday_lunch"},
                "16:00": {"name": "🍰 Воскресный десерт", "type": "sunday_dessert", "method": "generate_sunday_dessert"},
                "17:00": {"name": "🎒 Полезные перекусы для активного отдыха", "type": "active_snacks", "method": "generate_active_snacks"},
                "19:00": {"name": "📋 Ужин для подготовки", "type": "week_prep_dinner", "method": "generate_week_prep_dinner"},
                "20:00": {"name": "📝 Совет: Meal prep стратегии", "type": "planning_advice", "method": "generate_planning_advice"}
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

        if not self.validate_generator_methods():
            logger.error("❌ Критические ошибки валидации! Планировщик не запущен.")
            return False

        schedule.clear()

        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)

        self.is_running = True
        self._run_scheduler()

        logger.info("✅ Планировщик запущен")
        return True

    def validate_generator_methods(self):
        missing_methods = []
        for day_schedule in self.kemerovo_schedule.values():
            for event in day_schedule.values():
                method_name = event['method']
                if not hasattr(self.generator, method_name):
                    missing_methods.append(method_name)

        if missing_methods:
            logger.error(f"❌ Отсутствующие методы: {missing_methods}")
            return False

        logger.info("✅ Все методы генерации валидированы")
        return True

    def _schedule_event(self, day, server_time, event):
        def job():
            try:
                current_times = TimeManager.get_current_times()
                logger.info(f"🕒 Выполнение: {event['name']}")

                method_name = event['method']
                if hasattr(self.generator, method_name):
                    method = getattr(self.generator, method_name)
                    content = method()

                    if content:
                        content_with_time = f"{content}\n\n⏰ Опубликовано: {current_times['kemerovo_time']}"

                        success = self.telegram.send_with_fallback(
                            content_with_time, 
                            event['name'],
                            max_retries=3
                        )

                        if success:
                            logger.info(f"✅ Успешная публикация: {event['name']}")
                        else:
                            logger.error(f"❌ Ошибка публикации: {event['name']}")
                    else:
                        logger.error(f"❌ Не удалось сгенерировать контент: {event['name']}")
                        service_monitor.record_missed_message(event['name'])
                else:
                    logger.error(f"❌ Метод не найден: {method_name}")
                    service_monitor.record_missed_message(event['name'])

            except Exception as e:
                logger.error(f"❌ Ошибка в задании {event['name']}: {str(e)}")
                service_monitor.record_missed_message(event['name'])

        job_func = getattr(schedule.every(), self._get_day_name(day))
        job_func.at(server_time).do(job)

        logger.info(f"📌 Запланировано: {self._get_day_name(day).capitalize()} {server_time} - {event['name']}")

    def _get_day_name(self, day_num):
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        return days[day_num]

    def _run_scheduler(self):
        def run():
            while self.is_running:
                try:
                    schedule.run_pending()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле планировщика: {e}")
                    time.sleep(60)

        scheduler_thread = Thread(target=run, daemon=True)
        scheduler_thread.start()
        logger.info("✅ Планировщик запущен в отдельном потоке")

    def get_next_event(self):
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

            return "08:30", {"name": "Следующий пост", "type": "general"}

        except Exception as e:
            logger.error(f"❌ Ошибка получения следующего события: {e}")
            return "08:30", {"name": "Следующий пост", "type": "general"}

# ========== FLASK МАРШРУТЫ ==========

@app.route('/')
def smart_dashboard():
    try:
        current_times = TimeManager.get_current_times()
        current_weekday = TimeManager.get_kemerovo_weekday()
        monitor_status = service_monitor.get_status()

        member_count = telegram_manager.get_member_count()
        next_time, next_event = content_scheduler.get_next_event()

        total_posts = 42
        posts_sent = monitor_status['sent_messages']
        posts_remaining = total_posts - posts_sent

        # Получаем статистику кэша
        cache_info = gpt_generator.get_cache_info()

        weekly_stats = {
            'posts_sent': posts_sent,
            'posts_remaining': posts_remaining,
            'total_posts': total_posts,
            'completion_percentage': int((posts_sent / total_posts) * 100) if total_posts > 0 else 0
        }

        today_schedule = content_scheduler.kemerovo_schedule.get(current_weekday, {})

        html = f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Умный дашборд @ppsupershef</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
                .stat-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; }}
                .stat-number {{ font-size: 24px; font-weight: bold; color: #333; }}
                .stat-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
                .schedule-item {{ display: flex; align-items: center; padding: 12px; margin: 8px 0; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #28a745; }}
                .schedule-time {{ font-weight: bold; color: #333; min-width: 60px; }}
                .schedule-text {{ flex: 1; margin-left: 15px; }}
                .btn {{ background: #667eea; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; margin: 5px; }}
                .btn:hover {{ background: #5a6fd8; }}
                .btn-secondary {{ background: #6c757d; color: white; }}
                .btn-secondary:hover {{ background: #5a6268; }}
                .btn-success {{ background: #28a745; color: white; }}
                .btn-success:hover {{ background: #218838; }}
                .btn-warning {{ background: #ffc107; color: black; }}
                .btn-warning:hover {{ background: #e0a800; }}
                .progress {{ background: #e9ecef; border-radius: 10px; height: 20px; margin: 10px 0; }}
                .progress-bar {{ background: #28a745; height: 100%; border-radius: 10px; text-align: center; color: white; font-size: 12px; line-height: 20px; }}
                .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); }}
                .modal-content {{ background-color: white; margin: 5% auto; padding: 20px; border-radius: 10px; width: 80%; max-width: 800px; max-height: 80vh; overflow-y: auto; }}
                .close {{ color: #aaa; float: right; font-size: 28px; font-weight: bold; cursor: pointer; }}
                .close:hover {{ color: black; }}
                .form-group {{ margin: 15px 0; }}
                .form-label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
                .form-textarea {{ width: 100%; height: 200px; padding: 10px; border: 1px solid #ddd; border-radius: 5px; resize: vertical; }}
                .preview-area {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0; white-space: pre-wrap; font-family: Arial; }}
                .cache-stats {{ background: #e8f5e8; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎪 Умный дашборд @ppsupershef</h1>
                    <p>Клуб Осознанного Питания - 42 поста в неделю с научным подходом</p>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 15px;">
                        <div>🟢 СИСТЕМА АКТИВНА</div>
                        <div>⏰ Кемерово: {current_times['kemerovo_time']}</div>
                        <div>📅 {current_times['kemerovo_weekday_name']}</div>
                    </div>
                </div>

                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number">{weekly_stats['posts_sent']}/{weekly_stats['total_posts']}</div>
                        <div class="stat-label">📊 Постов отправлено</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">{weekly_stats['completion_percentage']}%</div>
                        <div class="stat-label">🎯 Выполнение плана</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">{member_count}</div>
                        <div class="stat-label">👥 Подписчики (реальные)</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">{enhanced_keep_alive.ping_count}</div>
                        <div class="stat-label">🔄 Keep-alive пинги</div>
                    </div>
                </div>

                <div class="cache-stats">
                    <h3>💾 Статистика кэширования (Render-compatible)</h3>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['total_entries']}</div>
                            <div class="stat-label">📦 Записей в кэше</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['cache_hits']}</div>
                            <div class="stat-label">🎯 Попадания в кэш</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['cache_misses']}</div>
                            <div class="stat-label">🔄 Промахи кэша</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['hit_rate']}%</div>
                            <div class="stat-label">⚡ Эффективность кэша</div>
                        </div>
                    </div>
                    <p><small>💡 Кэш работает в оперативной памяти (Render-compatible). TTL: 7 дней</small></p>
                </div>

                <div style="background: #e8f5e8; padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <h3>🎯 Прогресс недели</h3>
                    <div class="progress">
                        <div class="progress-bar" style="width: {weekly_stats['completion_percentage']}%">{weekly_stats['completion_percentage']}%</div>
                    </div>
                    <p>Осталось отправить: {weekly_stats['posts_remaining']} постов</p>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                    <div>
                        <h3>⏰ Расписание сегодня</h3>
                        {"".join([f'''
                        <div class="schedule-item">
                            <div class="schedule-time">{time}</div>
                            <div class="schedule-text">{event["name"]}</div>
                        </div>
                        ''' for time, event in sorted(today_schedule.items())])}
                    </div>

                    <div>
                        <h3>🔧 Управление</h3>
                        <button class="btn" onclick="testSend()">🧪 Тест отправки</button>
                        <button class="btn" onclick="testGPT()">🤖 Тест генерации</button>
                        <button class="btn" onclick="forceKeepAlive()">🔄 Keep-alive</button>
                        <button class="btn btn-success" onclick="sendSnowboardTraining()">🏂 Тренировка сноубордистов</button>
                        <button class="btn" onclick="sendFamilyWorkout()">💪 Семейная тренировка</button>
                        <button class="btn" onclick="sendActiveSnacks()">🎒 Активные перекусы</button>
                        <button class="btn btn-warning" onclick="clearCache()">🧹 Очистить кэш</button>
                        <button class="btn btn-secondary" onclick="openManualPost()">✏️ Ручной пост</button>
                        <button class="btn" onclick="updateMemberCount()">🔄 Обновить статистику</button>

                        <div style="margin-top: 15px; padding: 15px; background: #fff3cd; border-radius: 8px;">
                            <h4>🎯 Следующий пост</h4>
                            <p><strong>{next_time}</strong> - {next_event['name']}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Модальное окно для ручного поста -->
            <div id="manualPostModal" class="modal">
                <div class="modal-content">
                    <span class="close" onclick="closeManualPost()">&times;</span>
                    <h3>✏️ Создание ручного поста</h3>
                    
                    <div class="form-group">
                        <label class="form-label">Текст поста (поддерживает HTML разметку):</label>
                        <textarea id="postContent" class="form-textarea" placeholder="Введите текст поста..."></textarea>
                    </div>
                    
                    <button class="btn" onclick="previewPost()">👁️ Предпросмотр</button>
                    <button class="btn btn-success" onclick="sendManualPost()">📤 Отправить</button>
                    
                    <div id="previewArea" class="preview-area" style="display: none;">
                        <h4>Предпросмотр:</h4>
                        <div id="previewContent"></div>
                    </div>
                </div>
            </div>

            <script>
                function testSend() {{
                    fetch('/test-send').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Тест успешен!' : '❌ Ошибка');
                    }});
                }}

                function testGPT() {{
                    fetch('/test-gpt').then(r => r.json()).then(data => {{
                        alert(data.status === 'success' ? '✅ Генерация работает!' : '❌ Ошибка');
                    }});
                }}

                function forceKeepAlive() {{
                    fetch('/force-keep-alive').then(r => r.json()).then(data => {{
                        alert('Keep-alive: ' + data.ping_count + ' пингов');
                    }});
                }}

                function sendSnowboardTraining() {{
                    if (confirm('Отправить тренировку для сноубордистов?')) {{
                        fetch('/send-snowboard-training').then(r => r.json()).then(data => {{
                            alert(data.status === 'success' ? '✅ Тренировка отправлена!' : '❌ Ошибка отправки');
                        }});
                    }}
                }}

                function sendFamilyWorkout() {{
                    if (confirm('Отправить пост про семейную тренировку?')) {{
                        fetch('/send-family-workout').then(r => r.json()).then(data => {{
                            alert(data.status === 'success' ? '✅ Тренировка отправлена!' : '❌ Ошибка отправки');
                        }});
                    }}
                }}

                function sendActiveSnacks() {{
                    if (confirm('Отправить пост про перекусы для активного отдыха?')) {{
                        fetch('/send-active-snacks').then(r => r.json()).then(data => {{
                            alert(data.status === 'success' ? '✅ Перекусы отправлены!' : '❌ Ошибка отправки');
                        }});
                    }}
                }}

                function clearCache() {{
                    if (confirm('Очистить весь кэш GPT? Это вызовет повторную генерацию всех рецептов.')) {{
                        fetch('/clear-cache').then(r => r.json()).then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Кэш очищен! Удалено ' + data.cleared_count + ' записей');
                                location.reload();
                            }} else {{
                                alert('❌ Ошибка очистки кэша');
                            }}
                        }});
                    }}
                }}

                function updateMemberCount() {{
                    fetch('/update-member-count').then(r => r.json()).then(data => {{
                        if (data.status === 'success') {{
                            alert('✅ Статистика обновлена! Подписчиков: ' + data.member_count);
                            location.reload();
                        }} else {{
                            alert('❌ Ошибка обновления статистики');
                        }}
                    }});
                }}

                function openManualPost() {{
                    document.getElementById('manualPostModal').style.display = 'block';
                }}

                function closeManualPost() {{
                    document.getElementById('manualPostModal').style.display = 'none';
                    document.getElementById('previewArea').style.display = 'none';
                }}

                function previewPost() {{
                    const content = document.getElementById('postContent').value;
                    if (content.trim() === '') {{
                        alert('Введите текст поста');
                        return;
                    }}
                    document.getElementById('previewContent').innerHTML = content;
                    document.getElementById('previewArea').style.display = 'block';
                }}

                function sendManualPost() {{
                    const content = document.getElementById('postContent').value;
                    if (content.trim() === '') {{
                        alert('Введите текст поста');
                        return;
                    }}

                    if (confirm('Отправить этот пост в канал?')) {{
                        fetch('/send-manual-post', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ content: content }})
                        }})
                        .then(r => r.json())
                        .then(data => {{
                            if (data.status === 'success') {{
                                alert('✅ Пост успешно отправлен!');
                                closeManualPost();
                                document.getElementById('postContent').value = '';
                            }} else {{
                                alert('❌ Ошибка отправки: ' + data.message);
                            }}
                        }});
                    }}
                }}

                // Закрытие модального окна при клике вне его
                window.onclick = function(event) {{
                    const modal = document.getElementById('manualPostModal');
                    if (event.target === modal) {{
                        closeManualPost();
                    }}
                }}

                // Автообновление каждые 30 секунд
                setInterval(() => location.reload(), 30000);
            </script>
        </body>
        </html>
        """
        return html

    except Exception as e:
        logger.error(f"❌ Ошибка дашборда: {e}")
        return f"Ошибка загрузки дашборда: {str(e)}"

@app.route('/health')
def health_check():
    return jsonify(service_monitor.get_status())

@app.route('/test-send')
def test_send():
    success = telegram_manager.send_message("🧪 <b>ТЕСТ СИСТЕМЫ</b>\n\n✅ 42 поста в неделю\n🤖 Научный подход\n🛡️ Усиленный keep-alive\n🏂 Тренировки для сноубордистов\n👥 Подписчики: " + str(telegram_manager.get_member_count()))
    return jsonify({"status": "success" if success else "error"})

@app.route('/test-gpt')
def test_gpt():
    try:
        test_content = content_generator.generate_neuro_breakfast()
        success = telegram_manager.send_message(test_content)
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/force-keep-alive')
def force_keep_alive():
    enhanced_keep_alive.multi_layer_ping()
    return jsonify({"status": "forced", "ping_count": enhanced_keep_alive.ping_count})

@app.route('/send-snowboard-training')
def send_snowboard_training():
    try:
        training_content = content_generator.generate_snowboard_training()
        success = telegram_manager.send_with_fallback(training_content, "Тренировка для сноубордистов")
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        logger.error(f"❌ Ошибка отправки тренировки для сноубордистов: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-family-workout')
def send_family_workout():
    try:
        workout_content = content_generator.generate_family_workout()
        success = telegram_manager.send_with_fallback(workout_content, "Семейная тренировка")
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        logger.error(f"❌ Ошибка отправки тренировки: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-active-snacks')
def send_active_snacks():
    try:
        snacks_content = content_generator.generate_active_snacks()
        success = telegram_manager.send_with_fallback(snacks_content, "Активные перекусы")
        return jsonify({"status": "success" if success else "error"})
    except Exception as e:
        logger.error(f"❌ Ошибка отправки перекусов: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/update-member-count')
def update_member_count():
    """Принудительное обновление количества подписчиков"""
    count = telegram_manager.get_member_count()
    return jsonify({"status": "success", "member_count": count})

@app.route('/clear-cache')
def clear_cache():
    """Очистка кэша GPT"""
    try:
        cleared_count = gpt_generator.clear_cache()
        logger.info(f"🧹 Кэш очищен вручную: удалено {cleared_count} записей")
        return jsonify({"status": "success", "cleared_count": cleared_count})
    except Exception as e:
        logger.error(f"❌ Ошибка очистки кэша: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/cache-info')
def cache_info():
    """Информация о состоянии кэша"""
    try:
        cache_info = gpt_generator.get_cache_info()
        return jsonify({"status": "success", "cache_info": cache_info})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/send-manual-post', methods=['POST'])
def send_manual_post():
    try:
        data = request.get_json()
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({"status": "error", "message": "Пустой контент"})
        
        # Валидация контента
        is_valid, validation_message = security_manager.validate_content(content)
        if not is_valid:
            return jsonify({"status": "error", "message": validation_message})
        
        success = telegram_manager.send_with_fallback(content, "Ручной пост")
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ручного поста: {e}")
        return jsonify({"status": "error", "message": str(e)})

# ========== ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ==========

security_manager = SecurityManager()
telegram_manager = TelegramManager()
gpt_generator = YandexGPTGenerator()  # Создаем сначала генератор для правильной инициализации кэша
content_generator = ContentGenerator()
content_scheduler = ContentScheduler()

# Обработчики сигналов
def signal_handler(sig, frame):
    logger.info('🚨 Получен сигнал остановки...')
    sys.exit(0)

def on_exit():
    logger.info("🔴 Бот остановлен")

signal.signal(signal.SIGINT, signal_handler)
atexit.register(on_exit)

try:
    # Запускаем системы
    start_enhanced_keep_alive()
    success = content_scheduler.start_scheduler()

    if success:
        logger.info("🚀 СИСТЕМА ЗАПУЩЕНА")
        logger.info("🤖 Научные подходы: АКТИВНЫ")
        logger.info("🛡️ Защита от сна: АКТИВНА")
        logger.info("💾 Render-Compatible Cache: АКТИВЕН (7 дней TTL)")
        logger.info("🏂 Тренировки для сноубордистов: ДОБАВЛЕНЫ")
        logger.info("💪 Семейные тренировки: ДОБАВЛЕНЫ")
        logger.info("🎒 Активные перекусы: ДОБАВЛЕНЫ")
        logger.info("📊 Реальный счетчик подписчиков: АКТИВЕН")
        logger.info("🔍 Скрытые спойлеры: ИСПРАВЛЕНЫ")
        
        # Получаем реальное количество подписчиков при запуске
        member_count = telegram_manager.get_member_count()
        logger.info(f"👥 Реальное количество подписчиков: {member_count}")

        # Получаем информацию о кэше
        cache_info = gpt_generator.get_cache_info()
        logger.info(f"💾 Инициализирован кэш: {cache_info['total_entries']} записей")

        # Тестовое сообщение о запуске
        current_times = TimeManager.get_current_times()
        telegram_manager.send_with_fallback(f"""
🎪 <b>СИСТЕМА @ppsupershef АКТИВИРОВАНА!</b>

✅ <b>Запущены все функции:</b>
• 📊 42 поста в неделю
• 🧠 Научные подходы для каждого дня
• 🤖 Генерация контента через Yandex GPT
• 💾 Умное кэширование (Render-compatible)
• 🛡️ Усиленный keep-alive
• 📱 Умный дашборд
• 🏂 Тренировки для сноубордистов
• 💪 Семейные тренировки
• 🎒 Перекусы для активного отдыха
• 🔍 Скрытые рецепты (спойлеры)

⏰ Время Кемерово: {current_times['kemerovo_time']}
📅 День: {current_times['kemerovo_weekday_name']}
👥 Подписчиков: {member_count}
💾 Кэш: {cache_info['total_entries']} записей

💫 <b>Каждый пост теперь с научным обоснованием и интерактивными элементами!</b>

<a href="https://t.me/share/url?url=https://t.me/ppsupershef&text=Присоединяйся%20к%20Клубу%20Осознанного%20Питания!%20🍽️">🔄 Поделиться с друзьями</a>
        """, "Запуск системы")

    else:
        logger.error("❌ Не удалось запустить систему")

except Exception as e:
    logger.error(f"❌ Ошибка запуска системы: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))

    print("🚀 Запуск системы @ppsupershef")
    print("🎯 Контент-план: 42 поста в неделю")
    print("🧠 Особенности: научные подходы для каждого дня")
    print("🤖 Генерация: Yandex GPT + шаблоны")
    print("💾 Кэширование: Render-Compatible Cache (7 дней TTL)")
    print("🛡️ Защита от сна: активна")
    print("📱 Дашборд: доступен")
    print("💫 Эмоциональные триггеры: в каждом посте")
    print("🏂 Тренировки для сноубордистов: добавлены")
    print("💪 Семейные тренировки: добавлены")
    print("🎒 Активные перекусы: добавлены")
    print("📊 Реальный счетчик подписчиков: активен")
    print("🔍 Скрытые спойлеры: исправлены")

    app.run(host='0.0.0.0', port=port, debug=False)
