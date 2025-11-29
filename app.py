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

# ========== СИСТЕМА РАЗНООБРАЗИЯ РЕЦЕПТОВ ==========

class RecipeDiversityManager:
    def __init__(self):
        self.used_ingredients = set()
        self.used_cooking_methods = set()
        self.used_exercises = set()
        self.recipe_history = []
        self.max_history_size = 100
        self.diversity_lock = RLock()
        
        # БИБЛИОТЕКА РОССИЙСКИХ ПРОДУКТОВ
        self.protein_sources = [
            "🍗 куриная грудка", "🦃 индейка", "🥩 говядина", "🐷 свинина", "🐄 телятина",
            "🐟 треска", "🐠 минтай", "🐡 горбуша", "🐟 сельдь", "🐟 скумбрия", "🐟 камбала",
            "🍗 куриные бедра", "🥓 свиная вырезка", "🐇 кролик", "🦃 индейка грудка",
            "🍖 телячья печень", "🍗 куриная печень", "🥚 яйца", "🧀 творог", "🧀 сыр"
        ]
        
        self.vegetable_rotation = [
            "🥔 картофель", "🥕 морковь", "🍠 свекла", "🥬 капуста", "🥒 огурцы", "🍅 помидоры",
            "🧅 лук репчатый", "🌱 лук зеленый", "🧄 чеснок", "🌶️ редис", "🥒 редис дайкон",
            "🥒 кабачки", "🍆 баклажаны", "🫑 перец болгарский", "🎃 тыква", "🌶️ редис",
            "🌿 зелень петрушки", "🌿 укроп", "🌱 зеленый лук", "🌿 щавель", "🥬 шпинат",
            "🥦 брокколи", "🥬 цветная капуста", "🥬 брюссельская капуста", "🌿 сельдерей"
        ]
        
        self.cooking_methods = [
            "🔥 запекание в духовке", "💨 приготовление на пару", "🍲 томление",
            "🍳 быстрая обжарка", "🍜 варка", "🥘 тушение", "🍵 припускание",
            "🧅 пассерование", "💧 бланширование", "🍖 бразирование"
        ]
        
        self.cuisine_styles = [
            "🇷🇺 русская", "🍅 средиземноморская", "🍝 европейская", "🥩 кавказская", 
            "🍚 азиатская", "🌯 восточная", "🌮 мексиканская"
        ]

    def get_unique_ingredients(self, count=3):
        """Возвращает уникальные российские ингредиенты"""
        with self.diversity_lock:
            available_proteins = [p for p in self.protein_sources if p not in self.used_ingredients]
            available_veggies = [v for v in self.vegetable_rotation if v not in self.used_ingredients]
            
            # Если доступных ингредиентов мало, очищаем историю
            if len(available_proteins) < 5:
                available_proteins = self.protein_sources
                self.used_ingredients.clear()
                
            if len(available_veggies) < 8:
                available_veggies = self.vegetable_rotation
                self.used_ingredients.clear()
            
            selected_protein = random.choice(available_proteins)
            selected_veggies = random.sample(available_veggies, min(count, len(available_veggies)))
            
            # Обновляем использованные ингредиенты
            self.used_ingredients.update([selected_protein] + selected_veggies)
            
            return selected_protein, selected_veggies

    def get_unique_cooking_method(self):
        """Возвращает уникальный метод приготовления"""
        with self.diversity_lock:
            available_methods = [m for m in self.cooking_methods if m not in self.used_cooking_methods]
            
            if not available_methods:
                available_methods = self.cooking_methods
                self.used_cooking_methods.clear()
                
            selected_method = random.choice(available_methods)
            self.used_cooking_methods.add(selected_method)
            
            return selected_method

    def get_cuisine_style(self):
        """Возвращает случайный кулинарный стиль"""
        return random.choice(self.cuisine_styles)

    def record_recipe(self, recipe_text, recipe_type):
        """Записывает рецепт в историю"""
        with self.diversity_lock:
            self.recipe_history.append({
                'text': recipe_text,
                'type': recipe_type,
                'timestamp': datetime.now()
            })
            
            # Обрезаем историю если нужно
            if len(self.recipe_history) > self.max_history_size:
                self.recipe_history.pop(0)

    def check_similarity(self, new_recipe_text, threshold=0.3):
        """Проверяет схожесть с предыдущими рецептами"""
        with self.diversity_lock:
            if not self.recipe_history:
                return False
                
            new_words = set(re.findall(r'[а-яё]{4,}', new_recipe_text.lower()))
            
            for old_recipe in self.recipe_history[-10:]:
                old_words = set(re.findall(r'[а-яё]{4,}', old_recipe['text'].lower()))
                
                common_words = len(new_words.intersection(old_words))
                total_words = len(new_words.union(old_words))
                
                similarity = common_words / total_words if total_words > 0 else 0
                
                if similarity > threshold:
                    return True
                    
            return False

# ========== УСИЛЕННАЯ СИСТЕМА KEEP-ALIVE ==========

class EnhancedKeepAlive:
    def __init__(self):
        self.ping_count = 0
        self.last_ping_time = None
        self.failed_pings = 0
        self.max_failed_pings = 3
        self.ping_lock = Lock()

    def multi_layer_ping(self):
        """Многоуровневый пинг для предотвращения сна"""
        with self.ping_lock:
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
                time.sleep(180)
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
        self.rate_lock = Lock()
        
    def rate_limit_check(self, identifier):
        """Проверка ограничения частоты запросов"""
        with self.rate_lock:
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

# ========== УЛУЧШЕННАЯ YANDEX GPT ИНТЕГРАЦИЯ ==========

class EnhancedYandexGPTGenerator:
    def __init__(self):
        self.api_key = Config.YANDEX_GPT_API_KEY
        self.folder_id = Config.YANDEX_FOLDER_ID
        self.base_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        
        self.cache_manager = RenderCompatibleCache(ttl_days=7)
        self.diversity_manager = RecipeDiversityManager()
        
        self.cache_hits = 0
        self.cache_misses = 0
        self.regeneration_attempts = 0
        self.generation_lock = RLock()
        
        self._start_cache_cleanup()

    def _start_cache_cleanup(self):
        """Запускаем фоновую очистку кэша"""
        def cleanup_worker():
            while True:
                time.sleep(3600)
                try:
                    cleaned = self.cache_manager.cleanup_expired()
                    if cleaned > 0:
                        logger.info(f"🔄 Фоновая очистка: удалено {cleaned} записей")
                except Exception as e:
                    logger.error(f"❌ Ошибка фоновой очистки: {e}")
        
        cleanup_thread = Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()
        logger.info("🔄 Фоновая очистка кэша запущена")

    def generate_content(self, content_type, theme):
        """Универсальная генерация контента с разделением типов"""
        cache_key = self._create_cache_key(content_type, theme)
        
        # Первая проверка кэша без блокировки
        cached_result = self.cache_manager.get(cache_key)
        if cached_result:
            self.cache_hits += 1
            logger.info(f"✅ Используем кэшированный контент: {theme}")
            return cached_result
        
        # Генерация с блокировкой для предотвращения дублирования
        with self.generation_lock:
            # Повторная проверка кэша после получения блокировки
            cached_result = self.cache_manager.get(cache_key)
            if cached_result:
                self.cache_hits += 1
                logger.info(f"✅ Используем кэшированный контент (после блокировки): {theme}")
                return cached_result
            
            self.cache_misses += 1
            logger.info(f"🔄 Генерируем новый контент: {theme}")
            
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    if not self.api_key or self.api_key == 'your-yandex-gpt-api-key':
                        result = self._get_template_content(content_type, theme)
                    else:
                        result = self._generate_via_enhanced_gpt(content_type, theme)
                    
                    if not self.diversity_manager.check_similarity(result):
                        self.cache_manager.set(cache_key, result)
                        self.diversity_manager.record_recipe(result, content_type)
                        
                        if (self.cache_hits + self.cache_misses) % 10 == 0:
                            self._log_cache_stats()
                            
                        return result
                    else:
                        self.regeneration_attempts += 1
                        logger.warning(f"🔄 Контент слишком похож, пробуем снова... (попытка {attempt + 1})")
                        time.sleep(1)  # Задержка между попытками
                        continue

                except Exception as e:
                    logger.error(f"❌ Ошибка генерации контента (попытка {attempt + 1}): {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
            
            logger.warning("⚠️ Используем шаблонный контент после всех попыток")
            return self._get_template_content(content_type, theme)

    def _create_cache_key(self, content_type, theme):
        """Создает уникальный ключ кэша"""
        normalized_theme = theme.lower().strip()
        return f"{content_type}_{normalized_theme}_{hashlib.md5(normalized_theme.encode()).hexdigest()[:8]}"

    def _log_cache_stats(self):
        """Логирует статистику использования кэша"""
        total = self.cache_hits + self.cache_misses
        if total > 0:
            hit_rate = (self.cache_hits / total) * 100
            cache_stats = self.cache_manager.get_stats()
            diversity_stats = f"Попыток регенерации: {self.regeneration_attempts}"
            logger.info(f"📊 Статистика кэша: {self.cache_hits}/{total} попаданий ({hit_rate:.1f}%), {diversity_stats}")

    def get_cache_info(self):
        """Возвращает информацию о состоянии кэша"""
        cache_stats = self.cache_manager.get_stats()
        total_requests = self.cache_hits + self.cache_misses
        
        return {
            **cache_stats,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "regeneration_attempts": self.regeneration_attempts,
            "hit_rate": round((self.cache_hits / total_requests) * 100, 1) if total_requests > 0 else 0,
            "total_requests": total_requests,
            "unique_ingredients_used": len(self.diversity_manager.used_ingredients),
            "cooking_methods_used": len(self.diversity_manager.used_cooking_methods)
        }

    def clear_cache(self):
        """Очищает весь кэш"""
        try:
            cleared_count = self.cache_manager.clear_all()
            self.cache_hits = 0
            self.cache_misses = 0
            self.regeneration_attempts = 0
            self.diversity_manager.used_ingredients.clear()
            self.diversity_manager.used_cooking_methods.clear()
            self.diversity_manager.recipe_history.clear()
            return cleared_count
        except Exception as e:
            logger.error(f"❌ Ошибка очистки кэша: {e}")
            return 0

    def _generate_via_enhanced_gpt(self, content_type, theme):
        """Генерация через Yandex GPT API с улучшенными промптами"""
        try:
            if 'training' in content_type or 'workout' in content_type:
                prompt = self._build_training_prompt(content_type, theme)
                system_role = self._get_training_system_role()
            elif 'advice' in content_type or 'science' in content_type:
                prompt = self._build_nutrition_advice_prompt(content_type, theme)
                system_role = self._get_nutrition_system_role()
            else:
                prompt = self._build_recipe_prompt(content_type, theme)
                system_role = self._get_recipe_system_role()
            
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "modelUri": f"gpt://{self.folder_id}/yandexgpt/latest",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.8,
                    "maxTokens": 2000
                },
                "messages": [
                    {
                        "role": "system",
                        "text": system_role
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
                content_text = result['result']['alternatives'][0]['message']['text']
                logger.info(f"✅ Уникальный {content_type} сгенерирован через Yandex GPT")
                return self._format_content(content_text, content_type, theme)
            else:
                logger.error(f"❌ Ошибка Yandex GPT: {response.status_code} - {response.text}")
                return self._get_template_content(content_type, theme)
                
        except Exception as e:
            logger.error(f"❌ Ошибка GPT генерации: {e}")
            return self._get_template_content(content_type, theme)

    def _get_recipe_system_role(self):
        return """Ты - профессиональный нутрициолог и шеф-повар с 45-летним опытом. 
Создавай УНИКАЛЬНЫЕ, полезные и вкусные рецепты для семьи. 

🚨 ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
1. ❗ ИСПОЛЬЗУЙ ЭМОДЗИ В КАЖДОМ РАЗДЕЛЕ И ПУНКТЕ - это обязательное условие
2. ❗ Каждый заголовок, пункт списка и раздел должен содержать эмодзи
3. ❗ Эмодзи должны быть релевантны содержанию и улучшать восприятие
4. ❗ Без эмодзи контент считается невалидным
5. Соблюдай точные пропорции на 4 человек
6. Включай научное обоснование пользы блюда
7. Используй только распространенные в России продукты
8. Исключи тхину, пастернак, ревень, топинамбур, кольраби, мангольд
9. Исключи копчение, гриль, мангал

📝 СТРУКТУРА РЕЦЕПТА С ЭМОДЗИ:
🎯 ЗАГОЛОВОК С ЭМОДЗИ
📊 ПИЩЕВАЯ ЦЕННОСТЬ (каждый пункт с эмодзи)
🛒 ИНГРЕДИЕНТЫ (каждый пункт с эмодзи)
👨‍🍳 ПРОЦЕСС ПРИГОТОВЛЕНИЯ (каждый шаг с эмодзи)
💡 НАУЧНОЕ ОБОСНОВАНИЕ (с эмодзи)

✨ КРИТИЧЕСКИ ВАЖНО: Если в ответе нет эмодзи в каждом разделе - контент не принимается!"""

    def _get_training_system_role(self):
        return """Ты - профессиональный тренер с 45-летним опытом подготовки спортсменов. 
Создавай безопасные и эффективные программы тренировок для разных уровней подготовки.

🚨 ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
1. ❗ ИСПОЛЬЗУЙ ЭМОДЗИ В КАЖДОМ РАЗДЕЛЕ И ПУНКТЕ - это обязательное условие
2. ❗ Каждый заголовок, упражнение и раздел должен содержать эмодзи
3. ❗ Эмодзи должны быть релевантны содержанию и улучшать восприятие
4. ❗ Без эмодзи контент считается невалидным
5. Соблюдай принцип постепенной прогрессии нагрузок
6. Включай научное обоснование эффективности упражнений
7. Предоставляй альтернативы для разных уровней подготовки
8. Акцент на правильную технику выполнения

💪 СТРУКТУРА ТРЕНИРОВКИ С ЭМОДЗИ:
🎯 ЗАГОЛОВОК С ЭМОДЗИ
⏱️ ПРОДОЛЖИТЕЛЬНОСТЬ И УРОВЕНЬ (с эмодзи)
🏃‍♂️ РАЗМИНКА (каждое упражнение с эмодзи)
💪 ОСНОВНАЯ ЧАСТЬ (каждое упражнение с эмодзи)
🧘‍♂️ ЗАМИНКА (каждое упражнение с эмодзи)
💡 НАУЧНОЕ ОБОСНОВАНИЕ (с эмодзи)

✨ КРИТИЧЕСКИ ВАЖНО: Если в ответе нет эмодзи в каждом разделе - контент не принимается!"""

    def _get_nutrition_system_role(self):
        return """Ты - профессор нутрициологии с 50-летним опытом исследований. 
Создавай научно обоснованные рекомендации по питанию и здоровому образу жизни.

🚨 ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
1. ❗ ИСПОЛЬЗУЙ ЭМОДЗИ В КАЖДОМ РАЗДЕЛЕ И ПУНКТЕ - это обязательное условие
2. ❗ Каждый заголовок, рекомендация и раздел должен содержать эмодзи
3. ❗ Эмодзи должны быть релевантны содержанию и улучшать восприятие
4. ❗ Без эмодзи контент считается невалидным
5. Основывайся на доказательной медицине
6. Предоставляй практические рекомендации
7. Учитывай российские пищевые традиции
8. Избегай медицинских назначений и рекомендаций по БАДам

🧠 СТРУКТУРА СОВЕТА С ЭМОДЗИ:
🎯 ЗАГОЛОВОК С ЭМОДЗИ
🔬 НАУЧНАЯ ОСНОВА (каждый пункт с эмодзи)
💡 РЕКОМЕНДАЦИИ (каждый пункт с эмодзи)
⚠️ ОШИБКИ (каждый пункт с эмодзи)
📊 РЕЗУЛЬТАТЫ (с эмодзи)
🗓️ ПЛАН (каждый пункт с эмодзи)

✨ КРИТИЧЕСКИ ВАЖНО: Если в ответе нет эмодзи в каждом разделе - контент не принимается!"""

    def _build_recipe_prompt(self, recipe_type, theme):
        """Промпт для генерации РЕЦЕПТОВ с российскими продуктами"""
        protein, veggies = self.diversity_manager.get_unique_ingredients(3)
        cooking_method = self.diversity_manager.get_unique_cooking_method()
        cuisine_style = self.diversity_manager.get_cuisine_style()
        
        base_prompt = f"""
🎯 Создай АБСОЛЮТНО УНИКАЛЬНЫЙ рецепт {recipe_type} на тему '{theme}'

🌟 КЛЮЧЕВЫЕ ТРЕБОВАНИЯ К УНИКАЛЬНОСТИ:
• 🍗 Основной белок: {protein}
• 🥬 Овощи: {', '.join(veggies)}
• 🍳 Способ приготовления: {cooking_method}
• 🌍 Кулинарный стиль: {cuisine_style}
• 🇷🇺 Используй только распространенные в России продукты

🚨 ЗАПРЕЩЕНО ИСПОЛЬЗОВАТЬ:
• ❌ Тхина, пастернак, ревень, топинамбур, кольраби, мангольд
• ❌ Копчение, гриль, мангал
• ❌ Экзотические импортные продукты

📝 ОБЯЗАТЕЛЬНАЯ СТРУКТУРА С ЭМОДЗИ:
1. 🎯 ЗАГОЛОВОК С ЭМОДЗИ
2. 📊 ПИЩЕВАЯ ЦЕННОСТЬ НА ПОРЦИЮ (каждый пункт с эмодзи)
3. 🛒 ИНГРЕДИЕНТЫ НА 4 ПОРЦИИ (каждый пункт с эмодзи)
4. 👨‍🍳 ПРОЦЕСС ПРИГОТОВЛЕНИЯ (каждый шаг с эмодзи)
5. 💡 НАУЧНОЕ ОБОСНОВАНИЕ ПОЛЬЗЫ (с эмодзи)

✨ ОБЯЗАТЕЛЬНО:
• ❗ КАЖДЫЙ пункт должен содержать эмодзи - это критически важно!
• ❗ Эмодзи должны быть релевантны содержанию
• ❗ Заголовки и подзаголовки с эмодзи
• ❗ Списки с эмодзи для каждого пункта
• ❗ Без эмодзи контент не принимается!

🎯 ЦЕЛЬ: Создать по-настоящему уникальный рецепт из доступных российских продуктов!"""

        return base_prompt

    def _build_training_prompt(self, training_type, theme):
        """Промпт для генерации ТРЕНИРОВОК"""
        training_focus = {
            'family_workout': "👨‍👩‍👧‍👦 функциональные упражнения для отца и сына разного возраста",
            'snowboard_training': "🏂 специфические упражнения для подготовки к сезону сноубординга", 
            'active_snacks': "🎒 рецепты энергетических перекусов для активного отдыха"
        }
        
        focus = training_focus.get(training_type, "💪 общая физическая подготовка")
        
        base_prompt = f"""
🎯 Создай программу {training_type} на тему '{theme}'

🌟 КЛЮЧЕВЫЕ ТРЕБОВАНИЯ:
• 🎯 Фокус: {focus}
• 🛡️ Безопасная техника выполнения
• 📈 Постепенная прогрессия нагрузок
• 👥 Учет разных уровней подготовки

📝 ОБЯЗАТЕЛЬНАЯ СТРУКТУРА С ЭМОДЗИ:
1. 🎯 ЗАГОЛОВОК С ЭМОДЗИ
2. ⏱️ ПРОДОЛЖИТЕЛЬНОСТЬ И УРОВЕНЬ СЛОЖНОСТИ (с эмодзи)
3. 🏃‍♂️ РАЗМИНКА (5-10 минут, каждое упражнение с эмодзи)
4. 💪 ОСНОВНАЯ ЧАСТЬ (упражнения с подходами/повторениями, каждое с эмодзи)
5. 🧘‍♂️ ЗАМИНКА И РАСТЯЖКА (каждое упражнение с эмодзи)
6. 💡 НАУЧНОЕ ОБОСНОВАНИЕ ЭФФЕКТИВНОСТИ (с эмодзи)

✨ ОБЯЗАТЕЛЬНО:
• ❗ КАЖДОЕ упражнение должно содержать эмодзи - это критически важно!
• ❗ Эмодзи должны быть релевантны упражнению
• ❗ Заголовки и подзаголовки с эмодзи
• ❗ Каждый пункт в списке с эмодзи
• ❗ Без эмодзи контент не принимается!

🎯 ЦЕЛЬ: Создать эффективную и безопасную программу тренировок!"""

        return base_prompt

    def _build_nutrition_advice_prompt(self, advice_type, theme):
        """Специализированный промпт для советов нутрициолога"""
        advice_focus = {
            'monday_science': "🧠 нейропитание и поддержка когнитивных функций в условиях стресса начала недели",
            'tuesday_science': "💪 белковый метаболизм и восстановление после физических нагрузок",
            'wednesday_science': "🍃 детокс и поддержка работы ЖКТ в середине недели",
            'thursday_science': "⚡ энергетический метаболизм и подготовка к финалу недели",
            'friday_science': "⭐ баланс питания и психология пищевого поведения",
            'saturday_science': "👨‍👩‍👧‍👦 семейная нутрициология и совместное питание",
            'sunday_science': "📊 планирование питания и подготовка к новой неделе"
        }
        
        focus = advice_focus.get(advice_type, "🍽️ общие принципы здорового питания")
        
        base_prompt = f"""
🎯 Создай научно обоснованный совет нутрициолога на тему '{theme}'

🌟 КЛЮЧЕВЫЕ ТРЕБОВАНИЯ:
• 🎯 Фокус: {focus}
• 🔬 Научная достоверность информации
• 💡 Практическая применимость советов
• 🇷🇺 Учет российских пищевых традиций

📝 ОБЯЗАТЕЛЬНАЯ СТРУКТУРА С ЭМОДЗИ:
1. 🎯 ЗАГОЛОВОК С ЭМОДЗИ
2. 🔬 НАУЧНАЯ ОСНОВА (с объяснением физиологических процессов, каждый пункт с эмодзи)
3. 💡 ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ (каждый пункт с эмодзи)
4. ⚠️ РАСПРОСТРАНЕННЫЕ ОШИБКИ (каждый пункт с эмодзи)
5. 📊 ИЗМЕРИМЫЕ РЕЗУЛЬТАТЫ (с эмодзи)
6. 🗓️ ПЛАН ВНЕДРЕНИЯ В ЖИЗНЬ (каждый пункт с эмодзи)

✨ ОБЯЗАТЕЛЬНО:
• ❗ КАЖДЫЙ пункт должен содержать эмодзи - это критически важно!
• ❗ Эмодзи должны быть релевантны содержанию
• ❗ Заголовки и подзаголовки с эмодзи
• ❗ Списки с эмодзи для каждого пункта
• ❗ Без эмодзи контент не принимается!

🎓 КРИТИЧЕСКИЕ ТЕМЫ ДЛЯ РАСКРЫТИЯ:
• 💧 Водный баланс и гидратация
• ⏰ Циркадные ритмы и питание
• ⚖️ Баланс макронутриентов
• 🌿 Микронутриенты и их значение
• 🧠 Пищевое поведение и привычки

🎯 ЦЕЛЬ: Создать профессиональный, научно обоснованный совет от нутрициолога!"""

        return base_prompt

    def _format_content(self, content_text, content_type, theme):
        """Форматирование контента с учетом типа"""
        # Проверяем наличие эмодзи в сгенерированном контенте
        emoji_pattern = re.compile(
            u'['
            u'\U0001F600-\U0001F64F'  # emoticons
            u'\U0001F300-\U0001F5FF'  # symbols & pictographs
            u'\U0001F680-\U0001F6FF'  # transport & map symbols
            u'\U0001F1E0-\U0001F1FF'  # flags (iOS)
            u'\U00002702-\U000027B0'
            u'\U000024C2-\U0001F251'
            u']+', 
            flags=re.UNICODE
        )
        
        # Если эмодзи нет, добавляем базовые в заголовок
        if not emoji_pattern.search(content_text):
            logger.warning("⚠️ В сгенерированном контенте отсутствуют эмодзи, добавляем базовые")
            content_text = f"🎯 {content_text}"

        emoji_map = {
            'breakfast': '🍳', 'lunch': '🍲', 'dinner': '🍽️', 
            'dessert': '🍰', 'advice': '💡', 'science': '🔬',
            'monday_science': '🧠', 'tuesday_science': '💪',
            'wednesday_science': '🍃', 'thursday_science': '⚡',
            'friday_science': '⭐', 'saturday_science': '👨‍👩‍👧‍👦',
            'sunday_science': '📊', 'nutrition_advice': '🥗',
            'water_science': '💧', 'circadian_advice': '⏰',
            'metabolism_science': '🔥', 'family_nutrition': '👨‍👩‍👧‍👦',
            'planning_science': '📊', 'family_workout': '💪',
            'active_snacks': '🎒', 'snowboard_training': '🏂'
        }

        emoji = emoji_map.get(content_type, '💡')
        
        if 'advice' in content_type or 'science' in content_type:
            hashtag = "\n\n#советы_нутрициолога #здоровое_питание"
        elif 'training' in content_type or 'workout' in content_type:
            hashtag = "\n\n#тренировки #фитнес"
        else:
            hashtag = "\n\n#рецепты #здоровое_питание"
        
        return f"{emoji} <b>{theme.upper()}</b>\n\n{content_text}{hashtag}"

    def _get_template_content(self, content_type, theme):
        """Шаблонный контент если GPT не работает"""
        if 'training' in content_type or 'workout' in content_type:
            return self._get_training_template(content_type, theme)
        elif 'advice' in content_type or 'science' in content_type:
            return self._get_nutrition_template(content_type, theme)
        else:
            return self._get_recipe_template(content_type, theme)

    def _get_nutrition_template(self, content_type, theme):
        """Шаблон для советов нутрициолога С ЭМОДЗИ"""
        templates = {
            'monday_science': """🧠 <b>НЕЙРОПИТАНИЕ ДЛЯ СТАРТА НЕДЕЛИ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
📈 Понедельник - пик выработки кортизола и норадреналина
🧠 Требуется усиленная нейроподдержка для запуска когнитивных процессов

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 🥚 Завтрак с яйцами (холин для ацетилхолина)
• 🐟 Омега-3 для восстановления нейронных связей
• 💧 Усиленная гидратация для детоксикации
• 🥬 Листовая зелень для фолатов

⚡ <b>РЕЗУЛЬТАТ:</b> Улучшение концентрации на 40%, снижение стресса на 25%""",

            'tuesday_science': """💪 <b>БЕЛКОВЫЙ МЕТАБОЛИЗМ И ВОССТАНОВЛЕНИЕ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
🔄 Вторник - активация mTOR пути после понедельничных нагрузок
💪 Оптимальное время для синтеза мышечного белка

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 🍗 Разнообразие белковых источников
• ⏰ Равномерное распределение протеина
• 🥛 Лейцин из молочных продуктов
• 🌱 Растительные белки для микробиома

💥 <b>РЕЗУЛЬТАТ:</b> Ускорение восстановления на 35%, улучшение состава тела""",
            
            'wednesday_science': """🍃 <b>ДЕТОКС И ОЧИЩЕНИЕ В СЕРЕДИНЕ НЕДЕЛИ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
🔄 Среда - пик токсической нагрузки
🫁 Активация систем детоксикации печени

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 🥦 Крестоцветные для глутатиона
• 💧 Усиленный водный режим
• 🍎 Пектины для связывания токсинов
• 🥬 Клетчатка для микробиома

🌿 <b>РЕЗУЛЬТАТ:</b> Снижение воспаления на 30%, улучшение пищеварения""",
            
            'thursday_science': """⚡ <b>ЭНЕРГЕТИЧЕСКИЙ МЕТАБОЛИЗМ ДЛЯ ФИНАЛА</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
🔋 Четверг - истощение гликогеновых запасов
⚡ Оптимизация митохондриальной функции

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 🍠 Сложные углеводы с низким ГИ
• 🥑 Полезные жиры для мембран
• 🔋 Кофакторы энергетического обмена
• ⏰ Синхронизация с циркадными ритмами

🚀 <b>РЕЗУЛЬТАТ:</b> Стабильная энергия на 6-8 часов, улучшение выносливости""",
            
            'friday_science': """⭐ <b>БАЛАНС ПИТАНИЯ И ПСИХОЛОГИЯ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
🎯 Пятница - баланс между дофаминовой системой вознаграждения
😊 Поддержание дисциплины питания

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 🎯 Принцип 80/20 для гибкости
• 😊 Осознанное потребление
• 🍫 Здоровые альтернативы
• 👨‍👩‍👧‍👦 Социальный аспект питания

🌈 <b>РЕЗУЛЬТАТ:</b> Снижение стресса питания на 45%, устойчивые привычки""",
            
            'saturday_science': """👨‍👩‍👧‍👦 <b>СЕМЕЙНАЯ НУТРИЦИОЛОГИЯ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
❤️ Суббота - повышение окситоцина при совместных трапезах
👶 Формирование пищевых привычек у детей

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 👪 Совместное приготовление пищи
• 🎨 Вовлечение детей в процесс
• 📚 Образовательный компонент
• 💫 Создание традиций

❤️ <b>РЕЗУЛЬТАТ:</b> Укрепление семейных связей, формирование здоровых привычек""",
            
            'sunday_science': """📊 <b>ПЛАНИРОВАНИЕ ПИТАНИЯ НА НЕДЕЛЮ</b>

🔬 <b>НАУЧНАЯ ОСНОВА:</b>
🧠 Воскресенье - снижение decision fatigue при планировании
⚡ Оптимизация когнитивных ресурсов на неделю

💡 <b>ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:</b>
• 📝 Составление меню на неделю
• 🛒 Планирование закупок
• 🍱 Подготовка ингредиентов
• ⏱️ Оптимизация времени готовки

🎯 <b>РЕЗУЛЬТАТ:</b> Экономия 5+ часов в неделю, снижение стресса на 60%"""
        }
        
        return templates.get(content_type, f"🔬 <b>{theme}</b>\n\n🎯 Научный совет по питанию и здоровому образу жизни.\n💡 Практические рекомендации для всей семьи.\n🌟 Доказательная нутрициология.")

    def _get_training_template(self, content_type, theme):
        """Шаблон для тренировок С ЭМОДЗИ"""
        return f"""💪 <b>{theme.upper()}</b>

⏱️ <b>ПРОГРАММА ТРЕНИРОВКИ:</b>
• 🕐 Продолжительность: 30-45 минут
• 🎯 Уровень: начальный/средний
• 🏠 Оборудование: минимальное

🏃‍♂️ <b>РАЗМИНКА (5-10 минут):</b>
• 🚶‍♂️ Ходьба на месте
• 🔄 Вращения суставами
• 🤸‍♂️ Динамическая растяжка

💪 <b>ОСНОВНАЯ ЧАСТЬ:</b>
• 🏋️‍♂️ Упражнение 1: 3 подхода по 10-15 повторений
• 🏋️‍♀️ Упражнение 2: 3 подхода по 10-15 повторений  
• 🏋️ Упражнение 3: 3 подхода по 10-15 повторений

🧘‍♂️ <b>ЗАМИНКА:</b>
• 🤸‍♀️ Статическая растяжка 5-7 минут
• 🌬️ Глубокое дыхание

💡 <b>НАУЧНОЕ ОБОСНОВАНИЕ:</b>
🏃‍♂️ Регулярные тренировки улучшают метаболизм
❤️ Укрепляют сердечно-сосудистую систему
💫 Повышают качество жизни"""

    def _get_recipe_template(self, content_type, theme):
        """Шаблон для рецептов С ЭМОДЗИ"""
        
        # Базовые ингредиенты с эмодзи
        protein_options = ["🍗 куриная грудка", "🥩 говядина", "🐟 треска", "🦐 креветки", "🥚 яйца"]
        veggie_options = ["🥕 морковь", "🥦 брокколи", "🍅 помидоры", "🫑 перец", "🥬 шпинат"]
        carb_options = ["🍚 гречка", "🌾 овсянка", "🥔 картофель", "🍠 батат"]
        
        selected_protein = random.choice(protein_options)
        selected_veggies = random.sample(veggie_options, 2)
        selected_carb = random.choice(carb_options)
        
        return f"""🍽️ <b>{theme.upper()}</b>

📊 <b>ПИЩЕВАЯ ЦЕННОСТЬ НА ПОРЦИЮ:</b>
• 🔥 Калории: 320-380 ккал
• 🍗 Белки: 25-30 г
• 🥑 Жиры: 12-18 г  
• 🌾 Углеводы: 25-35 г
• 🌿 Клетчатка: 6-9 г

🛒 <b>ИНГРЕДИЕНТЫ НА 4 ПОРЦИИ:</b>
• {selected_protein} - 400 г
• {selected_veggies[0]} - 200 г
• {selected_veggies[1]} - 150 г  
• {selected_carb} - 200 г
• 🧅 Лук репчатый - 1 шт
• 🧄 Чеснок - 2 зубчика
• 🌿 Зелень петрушки - пучок
• 🫒 Оливковое масло - 2 ст.л.
• 🧂 Соль, перец - по вкусу

👨‍🍳 <b>ПРОЦЕСС ПРИГОТОВЛЕНИЯ:</b>
<tg-spoiler>
1. 🥣 Подготовить все ингредиенты
2. 🍳 Обжарить лук и чеснок
3. 🥘 Добавить основной белок
4. 🥬 Добавить овощи
5. 🔥 Готовить 20-25 минут
6. 🌿 Добавить зелень перед подачей
</tg-spoiler>

💡 <b>НАУЧНАЯ ПОЛЬЗА:</b>
⚖️ Сбалансированное сочетание нутриентов
💪 Оптимальное содержание белка
🌿 Богатство клетчаткой
⚡ Стабильная энергия на 4-5 часов"""

# ========== МОНИТОРИНГ СЕРВИСА ==========

class ServiceMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.request_count = 0
        self.sent_messages = 0
        self.missed_messages = 0
        self.monitor_lock = Lock()

    def increment_request(self):
        with self.monitor_lock:
            self.request_count += 1

    def record_sent_message(self):
        with self.monitor_lock:
            self.sent_messages += 1

    def record_missed_message(self, event_name):
        with self.monitor_lock:
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

    # РАСШИРЕННЫЕ ЭМОЦИОНАЛЬНЫЕ ТРИГГЕРЫ
    EMOTIONAL_TRIGGERS_RECIPES = {
        'monday': "Проснись и сияй! 🌅 Твой мозг жаждет правильного топлива...",
        'tuesday': "Время стать сильнее! 💪 Сегодня мы строим твое идеальное тело...", 
        'wednesday': "Чувствуешь легкость! 🍃 Пришло время очищения и обновления...",
        'thursday': "Зарядись энергией! ⚡ Сегодня мы наполняем тебя силой до конца недели...",
        'friday': "Награда за труды! 🎉 Баланс удовольствия и пользы ждет тебя...",
        'saturday': "Семейная магия! 👨‍👩‍👧‍👦 Создаем воспоминания на кухне вместе...",
        'sunday': "Инвестиция в успех! 📈 Готовься к идеальной неделе уже сегодня..."
    }

    EMOTIONAL_TRIGGERS_WORKOUTS = {
        'monday': "Заряд бодрости на всю неделю! 💥 Начинаем с правильного настроя...",
        'tuesday': "Сила растет с каждым движением! 🏋️‍♂️ Совершенствуй свою форму...",
        'wednesday': "Преодолей середину пути! 🌉 Твое тело благодарно за заботу...",
        'thursday': "Энергия для прорыва! 🚀 Готовься к финальному рывку...",
        'friday': "Награда за упорство! 🏆 Ты стал сильнее, чем в понедельник...",
        'saturday': "Семейная сила! 👨‍👦 Совместные достижения сближают...",
        'sunday': "Фундамент будущих побед! 📊 Готовь тело к новым свершениям..."
    }

    EMOTIONAL_TRIGGERS_NUTRITION = {
        'monday': "Мудрость питания на старте недели! 🧠 Заложи основу успеха...",
        'tuesday': "Наука о теле раскрывает секреты! 🔬 Углубляем знания...",
        'wednesday': "Гармония метаболизма! ⚖️ Балансируем системы организма...",
        'thursday': "Энергия правильных решений! 💡 Меняем привычки сегодня...",
        'friday': "Итоги недели мудрости! 📚 Закрепляем полезные знания...",
        'saturday': "Семейная нутрициология! 👨‍👩‍👧‍👦 Объединяем заботу о здоровье...",
        'sunday': "Планирование здоровья! 🗓️ Готовимся к идеальной неделе..."
    }

    # НАУЧНЫЕ ПОДХОДЫ С БИОЛОГИЧЕСКИМ ОБОСНОВАНИЕМ
    SCIENCE_APPROACHES = {
        'monday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ ПОНЕДЕЛЬНИКА:

После выходных происходит резкая активация симпатической нервной системы:
• 📈 Кортизол +80% - требует холина и фосфолипидов для синтеза нейромедиаторов
• 🧠 Норадреналин +60% - необходим тирозин и фенилаланин
• ⚡ Гликоген истощен - нужны сложные углеводы с низким ГИ
• 🛡️ Окислительный стресс - антиоксиданты для защиты нейронов

💫 РЕКОМЕНДАЦИЯ: Завтрак с яйцами, авокадо и цельнозерновыми для плавного запуска когнитивных функций.""",
        
        'tuesday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ ВТОРНИКА:

Активация анаболических процессов после понедельничных нагрузок:
• 💪 mTOR путь активирован на 40% - оптимально для синтеза белка
• 🧬 Транскрипция мышечных генов усилена - нужен лейцин
• 🔄 Восстановление микротравм - требуются BCAA
• 🦠 Микробиом адаптирован - время для разнообразия белков

💫 РЕКОМЕНДАЦИЯ: Ротация белковых источников для полного аминокислотного профиля.""",
        
        'wednesday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ СРЕДЫ:

Пик детоксикационной нагрузки и воспалительных процессов:
• 🫁 CYP450 система печени активна - нужны индол-3-карбинол
• 🦠 Кишечный барьер напряжен - требуются бутираты
• 🌿 Глутатион истощен - необходим селен и цистеин
• 🔥 NF-kB активирован - противовоспалительные нутриенты

💫 РЕКОМЕНДАЦИЯ: Овощи семейства крестоцветных и клетчатка для поддержки детокса.""",
        
        'thursday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ ЧЕТВЕРГА:

Оптимизация энергетического метаболизма для финала недели:
• 🔋 Митохондриальная биогенез +25% - нужны коэнзим Q10
• 🍬 Инсулиновая чувствительность снижена - требуются хром
• ⚡ Циркадные ритмы стабилизированы - время для синхронизации
• 🧠 Нейротрансмиттеры сбалансированы - фокус на энергию

💫 РЕКОМЕНДАЦИЯ: Сложные углеводы с равномерным высвобождением глюкозы.""",
        
        'friday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ ПЯТНИЦЫ:

Баланс между дофаминовой системой и метаболическим здоровьем:
• 🎯 Дофамин +35% - требует контроля за reward системой
• 😊 Серотонин стабилен - основа для осознанного выбора
• 🍽️ Грелин/лептин сбалансированы - оптимально для гибкости
• ❤️ Окситоцин повышен - социальный аспект питания

💫 РЕКОМЕНДАЦИЯ: Принцип 80/20 для поддержания мотивации без перегрузки.""",
        
        'saturday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ СУББОТЫ:

Синхронизация семейных ритмов и пищевого поведения:
• 👪 Окситоцин +27% - укрепление связей через совместные трапезы
• 🧒 Нейропластичность детского мозга усилена - формирование привычек
• 💫 Микробиомы семьи синхронизируются - обмен штаммами
• 😊 Эндорфины повышены - еда как удовольствие и объединение

💫 РЕКОМЕНДАЦИЯ: Совместное приготовление для усиления семейных связей.""",
        
        'sunday': """🎯 БИОЛОГИЧЕСКОЕ ОБОСНОВАНИЕ ДЛЯ ВОСКРЕСЕНЬЯ:

Когнитивная подготовка к новой неделе и планирование:
• 🧠 Prefrontal cortex активен - оптимально для планирования
• 📉 Decision fatigue минимален - экономия 35% ментальной энергии
• 🗓️ Проспективная память усилена - реализация планов на 68%
• ⏰ Циркадные ритмы предсказуемы - синхронизация с графиком

💫 РЕКОМЕНДАЦИЯ: Планирование питания для снижения стресса в рабочие дни."""
    }

    UNIVERSAL_FOOTER = """
─━━━━━━━━━━━━━━ ⋅∙∘ ★ ∘∙⋅ ━━━━━━━━━━━━─

🎯 Основано на исследованиях доказательной нутрициологии

📢 Подписывайтесь на канал!
💬 Обсуждаем рецепты в чате!

😋 Вкусно | 💪 Полезно | ⏱️ Быстро | 🧠 Научно

🔄 Поделиться с друзьями"""

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

    def get_emotional_trigger(self, content_type, day_of_week):
        """Возвращает соответствующий эмоциональный триггер для типа контента"""
        day_key = day_of_week.lower()
        
        if 'training' in content_type or 'workout' in content_type:
            return self.EMOTIONAL_TRIGGERS_WORKOUTS.get(day_key, "")
        elif 'advice' in content_type or 'science' in content_type:
            return self.EMOTIONAL_TRIGGERS_NUTRITION.get(day_key, "")
        else:
            return self.EMOTIONAL_TRIGGERS_RECIPES.get(day_key, "")

    def generate_attractive_post(self, title, content, content_type, benefits, emotional_trigger="", include_science_approach=False, day_of_week=None):
        photo_url = self.get_photo_for_recipe(content_type)
        
        # Используем переданный эмоциональный триггер
        emotional_intro = emotional_trigger
        
        # НОВЫЙ ФОРМАТ ПОСТА С ЭМОЦИОНАЛЬНЫМ ТРИГГЕРОМ
        post = f"""🍽️ <b>{title}</b>

{emotional_intro}

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

# ========== УЛУЧШЕННЫЙ ГЕНЕРАТОР КОНТЕНТА ==========

class EnhancedContentGenerator:
    def __init__(self):
        self.visual_manager = VisualContentManager()
        self.gpt_generator = EnhancedYandexGPTGenerator()
        self.generator_lock = RLock()

    # НАУЧНЫЕ СОВЕТЫ НУТРИЦИОЛОГА ДЛЯ КАЖДОГО ДНЯ
    def generate_monday_science(self):
        return self._generate_with_enhanced_gpt('monday_science', 'Нейропитание для старта недели',
                                              '🧠 Улучшение когнитивных функций\n💡 Повышение концентрации внимания\n⚡ Снижение стрессовой нагрузки\n🌟 Оптимизация нейромедиаторного баланса',
                                              'monday')

    def generate_tuesday_science(self):
        return self._generate_with_enhanced_gpt('tuesday_science', 'Белковый метаболизм и восстановление',
                                              '💪 Ускорение синтеза мышечного белка\n🔄 Оптимизация аминокислотного профиля\n🌟 Улучшение восстановления после нагрузок\n🍗 Разнообразие белковых источников',
                                              'tuesday')

    def generate_wednesday_science(self):
        return self._generate_with_enhanced_gpt('wednesday_science', 'Детокс и очищение в середине недели',
                                              '🍃 Снижение воспалительных процессов\n💧 Улучшение детоксикационной функции\n🌟 Оптимизация работы ЖКТ\n🔄 Восстановление микробиома кишечника',
                                              'wednesday')

    def generate_thursday_science(self):
        return self._generate_with_enhanced_gpt('thursday_science', 'Энергетический метаболизм для финала недели',
                                              '⚡ Стабильное высвобождение энергии\n🔋 Улучшение митохондриальной функции\n🌟 Оптимизация углеводного обмена\n💪 Повышение выносливости',
                                              'thursday')

    def generate_friday_science(self):
        return self._generate_with_enhanced_gpt('friday_science', 'Баланс питания и психология',
                                              '⭐ Снижение стресса питания\n😊 Формирование здоровых отношений с едой\n🌟 Баланс между дисциплиной и гибкостью\n💫 Устойчивые пищевые привычки',
                                              'friday')

    def generate_saturday_science(self):
        return self._generate_with_enhanced_gpt('saturday_science', 'Семейная нутрициология',
                                              '👨‍👩‍👧‍👦 Укрепление семейных связей\n🍽️ Формирование здоровых привычек у детей\n💫 Создание пищевых традиций\n🌟 Совместное приготовление пищи',
                                              'saturday')

    def generate_sunday_science(self):
        return self._generate_with_enhanced_gpt('sunday_science', 'Планирование питания на неделю',
                                              '📊 Снижение decision fatigue на 35%\n💪 Повышение adherence к здоровому рациону на 68%\n🌟 Экономия времени и ресурсов\n🗓️ Оптимизация пищевого поведения',
                                              'sunday')

    # ДОБАВЛЕННЫЕ МЕТОДЫ ДЛЯ ИСПРАВЛЕНИЯ ОШИБОК
    def generate_mental_energy_lunch(self):
        """Обед для ментальной энергии (для понедельника)"""
        return self._generate_with_enhanced_gpt('lunch', 'Обед для ментальной энергии',
                                              '🧠 Поддержка когнитивных функций\n💡 Улучшение концентрации внимания\n⚡ Стабильное высвобождение энергии\n🌟 Оптимизация нейромедиаторного баланса',
                                              'monday')

    def generate_neuro_recovery_dinner(self):
        """Ужин для восстановления нейронов (для понедельника)"""
        return self._generate_with_enhanced_gpt('dinner', 'Ужин для восстановления нейронов',
                                              '🧠 Восстановление нейронных связей\n💤 Улучшение качества сна\n🌙 Оптимизация процессов детоксикации\n🌟 Подготовка мозга к следующему дню',
                                              'monday')

    def generate_neuro_advice(self):
        """Совет по нейропитанию (для понедельника)"""
        return self._generate_with_enhanced_gpt('advice', 'Совет: Нейропитание',
                                              '🧠 Улучшение когнитивных функций\n💡 Повышение нейропластичности\n⚡ Оптимизация энергетического метаболизма\n🛡️ Нейропротекторное действие',
                                              'monday')

    def generate_water_advice(self):
        """Совет по гидратации (для вторника)"""
        return self._generate_with_enhanced_gpt('water_science', 'Совет: Оптимальная гидратация',
                                              '💧 Роль воды в метаболизме\n🧠 Влияние на когнитивные функции\n🏃‍♂️ Гидратация при физических нагрузках\n🌡️ Регуляция температуры тела',
                                              'tuesday')

    def generate_veggie_advice(self):
        """Совет по овощному питанию (для среды)"""
        return self._generate_with_enhanced_gpt('veggie_advice', 'Совет: Детокс питание',
                                              '🥬 Источник витаминов и минералов\n🌿 Очищает организм\n💚 Профилактика заболеваний\n🌟 Улучшает здоровье',
                                              'wednesday')

    def generate_carbs_advice(self):
        """Совет по углеводам (для четверга)"""
        return self._generate_with_enhanced_gpt('carbs_advice', 'Совет: Сложные углеводы',
                                              '⚡ Основной источник энергии\n🍞 Важны для активности\n💪 Поддерживают метаболизм\n🌟 Обеспечивают жизнедеятельность',
                                              'thursday')

    def generate_balance_advice(self):
        """Совет по балансу питания (для пятницы)"""
        return self._generate_with_enhanced_gpt('balance_advice', 'Совет: Принцип 80/20',
                                              '⚖️ Оптимальное сочетание нутриентов\n💪 Поддержка всех систем\n🌟 Долгосрочное здоровье\n🛡️ Профилактика заболеваний',
                                              'friday')

    def generate_family_advice(self):
        """Совет по семейному питанию (для субботы)"""
        return self._generate_with_enhanced_gpt('family_advice', 'Совет: Питание для семьи',
                                              '👨‍👩‍👧‍👦 Укрепление семейных связей\n😊 Формирование здоровых привычек\n💫 Создает теплую атмосферу\n🌟 Наследие для детей',
                                              'saturday')

    def generate_planning_advice(self):
        """Совет по планированию питания (для воскресенья)"""
        return self._generate_with_enhanced_gpt('planning_advice', 'Совет: Meal prep стратегии',
                                              '📋 Экономит время и деньги\n💪 Обеспечивает сбалансированность\n🌟 Помогает достичь целей\n🛡️ Гарантирует успех',
                                              'sunday')

    # МЕТОДЫ ДЛЯ ТРЕНИРОВОК
    def generate_snowboard_training(self):
        return self._generate_with_enhanced_gpt('snowboard_training', 'Функциональная подготовка для сноубордистов',
                                              '🏂 Улучшение баланса и контроля на доске\n💪 Увеличение мышечной выносливости на 30-50%\n🛡️ Снижение риска травм на 25-35%\n⚡ Повышение взрывной силы для прыжков',
                                              'saturday')

    def generate_family_workout(self):
        return self._generate_with_enhanced_gpt('family_workout', 'Совместная тренировка отца и сына',
                                              '👨‍👦 Укрепление семейных связей\n💪 Физическое развитие для обоих\n🧠 Обучение правильной технике\n🏆 Создание здоровой конкуренции',
                                              'saturday')

    def generate_active_snacks(self):
        return self._generate_with_enhanced_gpt('active_snacks', 'Полезные перекусы для активного отдыха',
                                              '⚡ Быстрое восстановление энергии\n💪 Поддержка мышечной массы\n🧠 Улучшение концентрации\n🏃‍♂️ Повышение выносливости',
                                              'sunday')

    # СУЩЕСТВУЮЩИЕ МЕТОДЫ ДЛЯ РЕЦЕПТОВ
    def generate_cognitive_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Завтрак для когнитивных функций',
                                              '🧠 Улучшение памяти и концентрации\n💡 Повышение нейропластичности\n⚡ Стабильная энергия на 4-5 часов\n🛡️ Защита нейронов от окислительного стресса',
                                              'monday')

    def generate_protein_rotation_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Завтрак с ротацией белков',
                                              '💪 Разнообразие аминокислотного профиля\n🔄 Предотвращение пищевой непереносимости\n🌟 Оптимизация синтеза мышечного белка\n🍗 Альтернативные источники протеина',
                                              'tuesday')

    def generate_novel_protein_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Обед с новым источником белка',
                                              '💪 Расширение спектра аминокислот\n🆕 Предотвращение пищевой монотонности\n🌟 Стимуляция микробиома кишечника\n🍽️ Обогащение рациона новыми нутриентами',
                                              'tuesday')

    def generate_seafood_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Ужин с морскими белками',
                                              '🐟 Богатый источник Омега-3\n💪 Легкоусвояемый белок\n🦐 Микроэлементы (йод, селен, цинк)\n🌟 Поддержка сердечно-сосудистой системы',
                                              'tuesday')

    def generate_veggie_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Овощной завтрак',
                                              '🥬 Богат клетчаткой и витаминами\n🌿 Очищает организм\n💚 Легкий и полезный\n⚡ Дает заряд энергии',
                                              'wednesday')

    def generate_veggie_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Овощной обед',
                                              '🥬 Богат витаминами и минералами\n🌿 Очищает организм\n💚 Легкий и полезный\n⚡ Дает энергию',
                                              'wednesday')

    def generate_veggie_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Овощной ужин',
                                              '🥬 Легкий для пищеварения\n🌿 Богат клетчаткой\n💚 Способствует детоксу\n🌟 Очищает организм',
                                              'wednesday')

    def generate_carbs_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Углеводный завтрак',
                                              '⚡ Источник энергии\n🍞 Сложные углеводы\n💪 Поддерживает активность\n🌟 Надолго насыщает',
                                              'thursday')

    def generate_carbs_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Углеводный обед',
                                              '⚡ Восполняет энергию\n🍚 Сложные углеводы\n💪 Поддерживает активность\n🌟 Надолго насыщает',
                                              'thursday')

    def generate_carbs_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Углеводный ужин',
                                              '⚡ Восстанавливает энергию\n🍚 Сложные углеводы\n💪 Подготавливает к следующему дню\n🌟 Обеспечивает сон',
                                              'thursday')

    def generate_balance_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Сбалансированный завтрак',
                                              '⚡ Энергия и питательность\n💪 Белки для сытости\n🥬 Витамины для здоровья\n🌟 Идеальный баланс',
                                              'friday')

    def generate_balance_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Сбалансированный обед',
                                              '🍽️ Идеальное сочетание нутриентов\n💪 Поддержка энергии\n🌟 Оптимальное насыщение\n🛡️ Польза для здоровья',
                                              'friday')

    def generate_balance_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Сбалансированный ужин',
                                              '🌙 Легкий и питательный\n💪 Восстановление организма\n🌟 Подготовка ко сну\n🛡️ Оптимальное питание',
                                              'friday')

    def generate_family_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Семейный завтрак',
                                              '👨‍👩‍👧‍👦 Объединяет семью за столом\n😊 Вкусно и полезно для всех\n💫 Начинает день с радости\n🌟 Создает традиции',
                                              'saturday')

    def generate_family_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Семейный обед',
                                              '👨‍👩‍👧‍👦 Объединяет за обеденным столом\n😊 Вкусно и полезно для всех\n💫 Создает семейные традиции\n🌟 Укрепляет связи',
                                              'saturday')

    def generate_saturday_dessert(self):
        return self._generate_with_enhanced_gpt('dessert', 'Субботний десерт',
                                              '🎂 Сладкое наслаждение\n😊 Полезные ингредиенты\n👨‍👩‍👧‍👦 Для семейного вечера\n💫 Традиции и радость',
                                              'saturday')

    def generate_family_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Семейный ужин',
                                              '👨‍👩‍👧‍👦 Завершает день вместе\n😊 Вкусно и полезно\n💫 Создает теплую атмосферу\n🌟 Объединяет семью',
                                              'saturday')

    def generate_sunday_breakfast(self):
        return self._generate_with_enhanced_gpt('breakfast', 'Воскресный бранч',
                                              '🎉 Праздничное настроение\n👨‍👩‍👧‍👦 Идеально для семейного дня\n🍽️ Особенный вкус\n💫 Завершает неделю',
                                              'sunday')

    def generate_sunday_lunch(self):
        return self._generate_with_enhanced_gpt('lunch', 'Воскресный обед',
                                              '🎉 Праздничная атмосфера\n👨‍👩‍👧‍👦 Семейное время\n🍽️ Особенный вкус\n💫 Завершает выходные',
                                              'sunday')

    def generate_sunday_dessert(self):
        return self._generate_with_enhanced_gpt('dessert', 'Воскресный десерт',
                                              '🍰 Завершение выходных\n😊 Вкусные воспоминания\n👨‍👩‍👧‍👦 Семейная традиция\n🌟 Сладкий финал',
                                              'sunday')

    def generate_week_prep_dinner(self):
        return self._generate_with_enhanced_gpt('dinner', 'Ужин для подготовки к неделе',
                                              '📋 Закладывает основу на неделю\n💪 Питательный и сбалансированный\n🌟 Настраивает на продуктивность\n🛡️ Гарантирует успех',
                                              'sunday')

    def _generate_with_enhanced_gpt(self, content_type, theme, benefits, day_of_week=None):
        """Генерация контента через улучшенный Yandex GPT с правильными триггерами"""
        with self.generator_lock:
            try:
                # Генерируем контент
                content = self.gpt_generator.generate_content(content_type, theme)
                
                # Получаем соответствующий эмоциональный триггер
                emotional_trigger = self.visual_manager.get_emotional_trigger(content_type, day_of_week)
                
                # Форматируем пост
                post = self.visual_manager.generate_attractive_post(
                    theme.upper(),
                    content,
                    content_type,
                    benefits,
                    emotional_trigger=emotional_trigger,
                    include_science_approach=True,
                    day_of_week=day_of_week
                )
                return post
            except Exception as e:
                logger.error(f"❌ Ошибка генерации контента через GPT: {e}")
                return self._get_fallback_content(content_type, theme, benefits, day_of_week)

    def _get_fallback_content(self, content_type, theme, benefits, day_of_week=None):
        """Резервный контент если GPT не работает"""
        emotional_trigger = self.visual_manager.get_emotional_trigger(content_type, day_of_week)
        
        fallback_content = f"""
📊 <b>ПИЩЕВАЯ ЦЕННОСТЬ НА ПОРЦИЮ:</b>
• 🔥 Калории: 300-400 ккал
• 🍗 Белки: 20-30 г
• 🥑 Жиры: 15-25 g
• 🌾 Углеводы: 20-30 г
• 🌿 Клетчатка: 5-8 г

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

💡 <b>НАУЧНАЯ ПОЛЬЗА:</b>
Сбалансированное сочетание нутриентов обеспечивает оптимальное питание для всей семьи."""

        return self.visual_manager.generate_attractive_post(
            theme.upper(),
            fallback_content,
            content_type,
            benefits,
            emotional_trigger=emotional_trigger,
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
        self.telegram_lock = RLock()

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
        with self.telegram_lock:
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

# ========== УЛУЧШЕННЫЙ ПЛАНИРОВЩИК КОНТЕНТА ==========

class EnhancedContentScheduler:
    def __init__(self):
        # ОБНОВЛЕННОЕ РАСПИСАНИЕ С НАУЧНЫМИ СОВЕТАМИ В 8:30
        self.kemerovo_schedule = {
            # ПОНЕДЕЛЬНИК (0) - НЕЙРОПИТАНИЕ
            0: {
                "08:30": {"name": "🧠 Нейропитание для старта недели", "type": "monday_science", "method": "generate_monday_science"},
                "09:00": {"name": "🍳 Завтрак для когнитивных функций", "type": "cognitive_breakfast", "method": "generate_cognitive_breakfast"},
                "13:00": {"name": "🍲 Обед для ментальной энергии", "type": "mental_energy_lunch", "method": "generate_mental_energy_lunch"},
                "19:00": {"name": "🥗 Ужин для восстановления нейронов", "type": "neuro_recovery_dinner", "method": "generate_neuro_recovery_dinner"}
            },
            # ВТОРНИК (1) - БЕЛКОВЫЙ МЕТАБОЛИЗМ
            1: {
                "08:30": {"name": "💪 Белковый метаболизм и восстановление", "type": "tuesday_science", "method": "generate_tuesday_science"},
                "09:00": {"name": "🥚 Завтрак: Чередование белков", "type": "protein_rotation_breakfast", "method": "generate_protein_rotation_breakfast"},
                "13:00": {"name": "🍗 Обед: Новый источник белка", "type": "novel_protein_lunch", "method": "generate_novel_protein_lunch"},
                "19:00": {"name": "🐟 Ужин: Морские белки", "type": "seafood_dinner", "method": "generate_seafood_dinner"}
            },
            # СРЕДА (2) - ДЕТОКС И ОЧИЩЕНИЕ
            2: {
                "08:30": {"name": "🍃 Детокс и очищение в середине недели", "type": "wednesday_science", "method": "generate_wednesday_science"},
                "09:00": {"name": "🥬 Овощной завтрак", "type": "veggie_breakfast", "method": "generate_veggie_breakfast"},
                "13:00": {"name": "🥦 Обед: Овощное разнообразие", "type": "veggie_lunch", "method": "generate_veggie_lunch"},
                "19:00": {"name": "🥑 Ужин: Легкие овощные блюда", "type": "veggie_dinner", "method": "generate_veggie_dinner"}
            },
            # ЧЕТВЕРГ (3) - ЭНЕРГЕТИЧЕСКИЙ МЕТАБОЛИЗМ
            3: {
                "08:30": {"name": "⚡ Энергетический метаболизм для финала недели", "type": "thursday_science", "method": "generate_thursday_science"},
                "09:00": {"name": "🍠 Углеводный завтрак", "type": "carbs_breakfast", "method": "generate_carbs_breakfast"},
                "13:00": {"name": "🍚 Обед: Сложные углеводы", "type": "carbs_lunch", "method": "generate_carbs_lunch"},
                "19:00": {"name": "🥔 Ужин: Углеводы для восстановления", "type": "carbs_dinner", "method": "generate_carbs_dinner"}
            },
            # ПЯТНИЦА (4) - БАЛАНС ПИТАНИЯ
            4: {
                "08:30": {"name": "⭐ Баланс питания и психология", "type": "friday_science", "method": "generate_friday_science"},
                "09:00": {"name": "🥞 Сбалансированный завтрак", "type": "balance_breakfast", "method": "generate_balance_breakfast"},
                "13:00": {"name": "🍝 Обед: Идеальный баланс", "type": "balance_lunch", "method": "generate_balance_lunch"},
                "19:00": {"name": "🍽️ Ужин: Сбалансированный финал недели", "type": "balance_dinner", "method": "generate_balance_dinner"}
            },
            # СУББОТА (5) - СЕМЕЙНАЯ НУТРИЦИОЛОГИЯ И АКТИВНОСТЬ
            5: {
                "08:30": {"name": "👨‍👩‍👧‍👦 Семейная нутрициология", "type": "saturday_science", "method": "generate_saturday_science"},
                "10:00": {"name": "🍳 Семейный завтрак", "type": "family_breakfast", "method": "generate_family_breakfast"},
                "11:00": {"name": "💪 Семейная тренировка", "type": "family_workout", "method": "generate_family_workout"},
                "14:00": {"name": "🏂 Тренировка для сноубордистов", "type": "snowboard_training", "method": "generate_snowboard_training"},
                "13:00": {"name": "👨‍🍳 Семейный обед", "type": "family_lunch", "method": "generate_family_lunch"},
                "16:00": {"name": "🎂 Семейный десерт", "type": "saturday_dessert", "method": "generate_saturday_dessert"},
                "19:00": {"name": "🍽️ Семейный ужин", "type": "family_dinner", "method": "generate_family_dinner"}
            },
            # ВОСКРЕСЕНЬЕ (6) - ПЛАНИРОВАНИЕ И АКТИВНЫЙ ОТДЫХ
            6: {
                "08:30": {"name": "📊 Планирование питания на неделю", "type": "sunday_science", "method": "generate_sunday_science"},
                "10:00": {"name": "☀️ Воскресный бранч", "type": "sunday_breakfast", "method": "generate_sunday_breakfast"},
                "13:00": {"name": "🛒 Обед + план на неделю", "type": "sunday_lunch", "method": "generate_sunday_lunch"},
                "16:00": {"name": "🍰 Воскресный десерт", "type": "sunday_dessert", "method": "generate_sunday_dessert"},
                "17:00": {"name": "🎒 Полезные перекусы для активного отдыха", "type": "active_snacks", "method": "generate_active_snacks"},
                "19:00": {"name": "📋 Ужин для подготовки", "type": "week_prep_dinner", "method": "generate_week_prep_dinner"}
            }
        }

        self.server_schedule = self._convert_schedule_to_server()
        self.is_running = False
        self.telegram = TelegramManager()
        self.generator = EnhancedContentGenerator()
        self.scheduler_lock = RLock()
        self.running_jobs = set()

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

        logger.info("🚀 Запуск улучшенного планировщика контента...")

        if not self.validate_generator_methods():
            logger.error("❌ Критические ошибки валидации! Планировщик не запущен.")
            return False

        schedule.clear()

        for day, day_schedule in self.server_schedule.items():
            for server_time, event in day_schedule.items():
                self._schedule_event(day, server_time, event)

        self.is_running = True
        self._run_scheduler()

        logger.info("✅ Улучшенный планировщик запущен")
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
            job_key = f"{day}_{server_time}_{event['method']}"
            
            # Проверяем, не выполняется ли уже эта задача
            with self.scheduler_lock:
                if job_key in self.running_jobs:
                    logger.warning(f"⚠️ Задача {event['name']} уже выполняется, пропускаем")
                    return
                self.running_jobs.add(job_key)
            
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
            finally:
                # Освобождаем задачу
                with self.scheduler_lock:
                    self.running_jobs.discard(job_key)

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
                .diversity-stats {{ background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎪 Умный дашборд @ppsupershef</h1>
                    <p>Клуб Осознанного Питания - 42 поста в неделю с научным подходом и системой разнообразия</p>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 15px;">
                        <div>🟢 СИСТЕМА РАЗНООБРАЗИЯ АКТИВНА</div>
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

                <div class="diversity-stats">
                    <h3>🎯 Статистика системы разнообразия</h3>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['unique_ingredients_used']}</div>
                            <div class="stat-label">🥕 Уникальных ингредиентов</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['cooking_methods_used']}</div>
                            <div class="stat-label">🍳 Методов приготовления</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['regeneration_attempts']}</div>
                            <div class="stat-label">🔄 Попыток регенерации</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{cache_info['hit_rate']}%</div>
                            <div class="stat-label">⚡ Эффективность кэша</div>
                        </div>
                    </div>
                    <p><small>💡 Система автоматически предотвращает повторение рецептов и ингредиентов</small></p>
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
                            <div class="stat-number">{cache_info['total_requests']}</div>
                            <div class="stat-label">📊 Всего запросов</div>
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
                        <h3>🔧 Управление системой разнообразия</h3>
                        <button class="btn" onclick="testSend()">🧪 Тест отправки</button>
                        <button class="btn" onclick="testGPT()">🤖 Тест генерации</button>
                        <button class="btn" onclick="forceKeepAlive()">🔄 Keep-alive</button>
                        <button class="btn btn-success" onclick="sendSnowboardTraining()">🏂 Тренировка сноубордистов</button>
                        <button class="btn" onclick="sendFamilyWorkout()">💪 Семейная тренировка</button>
                        <button class="btn" onclick="sendActiveSnacks()">🎒 Активные перекусы</button>
                        <button class="btn btn-warning" onclick="clearCache()">🧹 Очистить кэш и историю</button>
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
                    if (confirm('Очистить весь кэш и историю разнообразия? Это вызовет повторную генерацию всех рецептов.')) {{
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
    cache_info = gpt_generator.get_cache_info()
    success = telegram_manager.send_message("🧪 <b>ТЕСТ СИСТЕМЫ РАЗНООБРАЗИЯ</b>\n\n✅ 42 поста в неделю\n🤖 Улучшенная генерация с ротацией\n🛡️ Система предотвращения повторов\n🏂 Тренировки для сноубордистов\n👥 Подписчики: " + str(telegram_manager.get_member_count()) + f"\n🎯 Уникальных ингредиентов: {cache_info['unique_ingredients_used']}")
    return jsonify({"status": "success" if success else "error"})

@app.route('/test-gpt')
def test_gpt():
    try:
        test_content = content_generator.generate_monday_science()
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
    """Очистка кэша GPT и системы разнообразия"""
    try:
        cleared_count = gpt_generator.clear_cache()
        logger.info(f"🧹 Кэш и история разнообразия очищены вручную: удалено {cleared_count} записей")
        return jsonify({"status": "success", "cleared_count": cleared_count})
    except Exception as e:
        logger.error(f"❌ Ошибка очистки кэша: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/cache-info')
def cache_info():
    """Информация о состоянии кэша и системы разнообразия"""
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
gpt_generator = EnhancedYandexGPTGenerator()
content_generator = EnhancedContentGenerator()
content_scheduler = EnhancedContentScheduler()

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
        logger.info("🚀 УЛУЧШЕННАЯ СИСТЕМА ЗАПУЩЕНА")
        logger.info("🧠 Научные подходы: АКТИВНЫ (8:30 каждый день)")
        logger.info("🎯 Система разнообразия: АКТИВНА")
        logger.info("🛡️ Защита от сна: АКТИВНА")
        logger.info("💾 Render-Compatible Cache: АКТИВЕН (7 дней TTL)")
        logger.info("🏂 Тренировки для сноубордистов: ДОБАВЛЕНЫ")
        logger.info("💪 Семейные тренировки: ДОБАВЛЕНЫ")
        logger.info("🎒 Активные перекусы: ДОБАВЛЕНЫ")
        logger.info("📊 Реальный счетчик подписчиков: АКТИВЕН")
        
        # Получаем реальное количество подписчиков при запуске
        member_count = telegram_manager.get_member_count()
        logger.info(f"👥 Реальное количество подписчиков: {member_count}")

        # Получаем информацию о системе разнообразия
        cache_info = gpt_generator.get_cache_info()
        logger.info(f"💾 Инициализирована система разнообразия: {cache_info['unique_ingredients_used']} ингредиентов, {cache_info['cooking_methods_used']} методов")

        # Тестовое сообщение о запуске улучшенной системы
        current_times = TimeManager.get_current_times()
        telegram_manager.send_with_fallback(f"""
🎪 <b>УЛУЧШЕННАЯ СИСТЕМА @ppsupershef АКТИВИРОВАНА!</b>

✅ <b>Запущены все улучшенные функции:</b>
• 📊 42 поста в неделю с системой разнообразия
• 🧠 НАУЧНЫЕ СОВЕТЫ В 8:30 КАЖДЫЙ ДЕНЬ
• 🤖 Улучшенная генерация с ротацией ингредиентов
• 💾 Умное кэширование (Render-compatible)
• 🛡️ Усиленный keep-alive
• 📱 Умный дашборд с мониторингом разнообразия
• 🏂 Тренировки для сноубордистов
• 💪 Семейные тренировки
• 🎒 Перекусы для активного отдыха

🎯 <b>СИСТЕМА РАЗНООБРАЗИЯ:</b>
• 🥕 {cache_info['unique_ingredients_used']}+ уникальных ингредиентов
• 🍳 {cache_info['cooking_methods_used']}+ методов приготовления
• 🔄 Автоматическая ротация рецептов

⏰ Время Кемерово: {current_times['kemerovo_time']}
📅 День: {current_times['kemerovo_weekday_name']}
👥 Подписчиков: {member_count}
💾 Система разнообразия: активна

💫 <b>Каждый пост теперь абсолютно уникален с научным обоснованием!</b>

🔄 Поделиться с друзьями
        """, "Запуск улучшенной системы")

    else:
        logger.error("❌ Не удалось запустить улучшенную систему")

except Exception as e:
    logger.error(f"❌ Ошибка запуска улучшенной системы: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))

    print("🚀 Запуск улучшенной системы @ppsupershef")
    print("🎯 Контент-план: 42 поста в неделю с системой разнообразия")
    print("🧠 Особенности: научные подходы + ротация ингредиентов")
    print("🤖 Генерация: Улучшенный Yandex GPT + система предотвращения повторов")
    print("💾 Кэширование: Render-Compatible Cache (7 дней TTL)")
    print("🛡️ Защита от сна: активна")
    print("📱 Дашборд: улучшенный с мониторингом разнообразия")
    print("💫 Система разнообразия: активна")
    print("🏂 Тренировки для сноубордистов: добавлены")
    print("💪 Семейные тренировки: добавлены")
    print("🎒 Активные перекусы: добавлены")
    print("📊 Реальный счетчик подписчиков: активен")
    print("🔍 Автоматическое предотвращение повторов: активно")

    app.run(host='0.0.0.0', port=port, debug=False)
